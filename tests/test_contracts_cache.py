"""`checks.contracts.ScriptCache` — 같은 스크립트를 두 번 파싱하지 않는다.

**대역이 아니라 세는 것이다.** 진짜 `extract_contract` 를 그대로 부르되 몇 번
불렸는지만 기록한다 — 대역으로 갈아끼우면 이 프로젝트가 네 번 겪은
"대역이 결함을 가렸다"(R4-7·R6-2)를 또 하게 된다.

캐시가 지켜야 할 것은 **빠름이 아니라 같음**이다. 그래서 여기 있는 단언의 대부분은
"결과가 캐시 없을 때와 같은가" 쪽이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strictler.checks import script as script_checks
from strictler.checks.contracts import ContractPayload, ScriptCache
from strictler.errors import Finding, StrictlerError

SOURCE = '''\
from dataclasses import dataclass


@dataclass
class Html:
    text: str


@dataclass
class Args:
    input: Html


@dataclass
class Buttons:
    count: int


def runNode(args: Args) -> Buttons:
    return returnResult(Buttons(count=len(args.input.text)))
'''

PATH = "/abs/perceive.py"


class Counter:
    """진짜 `extract_contract` 를 부르면서 횟수만 센다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        real = script_checks.extract_contract

        def counted(source: str, path: str):  # type: ignore[no-untyped-def]
            self.calls.append(path)
            return real(source, path)

        monkeypatch.setattr(script_checks, "extract_contract", counted)


def test_같은_소스는_한_번만_파싱된다(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = Counter(monkeypatch)
    cache = ScriptCache()

    first, _ = cache.contract(SOURCE, PATH)
    second, _ = cache.contract(SOURCE, PATH)

    assert len(counter.calls) == 1
    assert first is second


def test_내용이_바뀌면_다시_파싱한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """키는 경로 **+ 내용 해시**다. 경로만 쓰면 옛 계약을 돌려주게 된다."""
    counter = Counter(monkeypatch)
    cache = ScriptCache()

    cache.contract(SOURCE, PATH)
    changed, _ = cache.contract(SOURCE.replace("count: int", "count: str"), PATH)

    assert len(counter.calls) == 2
    assert changed.dataclasses["Buttons"].fields[0].type.name == "str"


def test_경로가_다르면_따로_센다(monkeypatch: pytest.MonkeyPatch) -> None:
    """`origin` 이 경로라 같은 소스라도 계약이 다르다 (R1-1)."""
    counter = Counter(monkeypatch)
    cache = ScriptCache()

    a, _ = cache.contract(SOURCE, "/abs/a.py")
    b, _ = cache.contract(SOURCE, "/abs/b.py")

    assert len(counter.calls) == 2
    assert a.dataclasses["Args"].origin == "/abs/a.py"
    assert b.dataclasses["Args"].origin == "/abs/b.py"


def test_돌려준_목록을_고쳐도_캐시가_오염되지_않는다() -> None:
    """부르는 쪽이 `findings.extend(...)` 를 한다 — 원본을 주면 다음 사람이 그걸 본다."""
    cache = ScriptCache()

    _, findings = cache.contract(SOURCE, PATH)
    findings.append(Finding(status="error", message="침입"))
    _, again = cache.contract(SOURCE, PATH)

    assert again == []


def test_파싱_실패는_캐시하지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """`StrictlerError` 는 위반이 아니라 검사기가 못 돈 것이다 — 그대로 올라간다."""
    counter = Counter(monkeypatch)
    cache = ScriptCache()
    broken = "def runNode(args: Args)\n    pass\n"

    for _ in range(2):
        with pytest.raises(StrictlerError):
            cache.contract(broken, PATH)

    assert len(counter.calls) == 2


def test_캐시를_써도_check_script_결과가_같다() -> None:
    """**검사를 건너뛰는 것이 아니다.** 계약 추출만 재사용한다."""
    plain = script_checks.check_script(SOURCE, PATH, "perceive")
    cached = script_checks.check_script(SOURCE, PATH, "perceive", cache=ScriptCache())

    assert [item.model_dump() for item in plain] == [item.model_dump() for item in cached]


@pytest.mark.parametrize("node_type", ["reckon", "action"])
def test_캐시를_써도_타입별_형식_판정이_같다(node_type: str) -> None:
    """`STR-CONTRACT-005/006/007` 은 계약을 재사용해도 그대로 나야 한다."""
    plain = script_checks.check_script(SOURCE, PATH, node_type)  # type: ignore[arg-type]
    cached = script_checks.check_script(
        SOURCE, PATH, node_type, cache=ScriptCache()  # type: ignore[arg-type]
    )

    assert [item.rule_id for item in plain] == [item.rule_id for item in cached]
    assert [item.rule_id for item in plain] != []


# ── 직렬화 — 캐시가 계약을 온전히 되살리는가 ─────────────────────────────────


EXAMPLE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "home-check"

SERIALIZED_ATTRS = {
    "path",
    "dataclasses",
    "input_type",
    "params_type",
    "state_type",
    "state_names",
    "output_type",
    "tool_calls",
    "library_slots",
    "_has_args",
    "_args_fields",
    "_has_entrypoint",
    "_entrypoint_ok",
    "_param_name",
    "_returns_result",
    "_type_uses",
}
"""`ContractPayload` 가 담는 속성 전부. **`_` 로 시작하는 내부 기록도 검사기가 읽는다.**"""


def test_직렬화가_ScriptContract_의_모든_속성을_덮는다() -> None:
    """★ 속성이 하나 늘었는데 여기 안 담기면 **캐시를 탄 실행만 판정이 달라진다.**

    `ScriptContract` 를 고치는 사람이 이 테스트로 캐시를 떠올리게 하는 자리다.
    이 목록을 고칠 때는 `checks.contracts.CACHE_VERSION` 도 올려야 한다.
    """
    contract, _ = script_checks.extract_contract(SOURCE, PATH)

    assert set(vars(contract)) == SERIALIZED_ATTRS


def _shape(contract) -> dict:  # type: ignore[no-untyped-def]
    """비교용으로 편 모습 — dataclass 선언까지 값으로 내린다."""
    plain = {
        name: value
        for name, value in vars(contract).items()
        if name != "dataclasses"
    }
    plain["dataclasses"] = {
        name: (spec.name, spec.origin, tuple((f.name, str(f.type)) for f in spec.fields))
        for name, spec in contract.dataclasses.items()
    }
    plain["_type_uses"] = tuple(str(used) for used in contract._type_uses)
    return plain


@pytest.mark.parametrize(
    "script", sorted((EXAMPLE_ROOT / "scripts").glob("*.py")), ids=lambda p: p.stem
)
def test_예제_스크립트가_직렬화를_왕복해도_같다(script: Path) -> None:
    """다섯 노드 타입 전부를 태운다 — `list[T]`·중첩 dataclass·`Args.state` 까지."""
    source = script.read_text(encoding="utf-8")
    original, _ = script_checks.extract_contract(source, str(script))

    restored = ContractPayload.of(original).to_contract()

    assert _shape(restored) == _shape(original)


def test_해석_안_되는_타입도_그대로_되살아난다() -> None:
    """`_type_of` 는 못 읽은 어노테이션을 **원문 그대로의 미지 타입**으로 남긴다.

    문자열로 접었다 펴면 되돌아온다는 보장이 없어서 구조 그대로 담는다 —
    여기서 뭉개지면 `STR-TYPE-003` 의 문구가 달라진다.
    """
    weird = SOURCE.replace("count: int", "count: Callable[[int], str]")
    original, _ = script_checks.extract_contract(weird, PATH)

    restored = ContractPayload.of(original).to_contract()

    assert str(restored.dataclasses["Buttons"].fields[0].type) == "Callable[[int], str]"
    assert _shape(restored) == _shape(original)


def test_한_번의_check_는_스크립트마다_한_번만_파싱한다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """노드 7개짜리 예제가 `extract_contract` 를 **21번** 부르던 자리다.

    `recheck_resolved` 가 한 번, 그 안의 `check_script` 가 또 한 번,
    `_load_nodes` 가 또 한 번. 셋 다 같은 파일에서 같은 계약을 뽑는다.
    """
    from strictler import cli

    monkeypatch.setenv("STRICTLER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STRICTLER_EXAMPLE_ROOT", str(EXAMPLE_ROOT))
    monkeypatch.setenv("STRICTLER_EXAMPLE_OUT", str(tmp_path / "out"))
    counter = Counter(monkeypatch)

    code = cli.main(["check", str(EXAMPLE_ROOT / "specs" / "home_ok.json"), "--json"])
    capsys.readouterr()

    assert code == 0
    # `check_count.json` 을 두 자리에 재사용하므로 노드 7개 / 스크립트 6개다.
    assert len(counter.calls) == len(set(counter.calls)) == 6
