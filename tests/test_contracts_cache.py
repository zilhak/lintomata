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
from strictler.checks.contracts import ScriptCache
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


# ── 한 번의 `check` 안에서 몇 번 파싱하는가 ──────────────────────────────────


EXAMPLE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "home-check"


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
