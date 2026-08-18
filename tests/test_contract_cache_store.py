"""등록소 캐시 — **해시가 그대로면 다시 파싱하지 않는다** (`schema.md` 2절).

`examples/home-check` 를 **`${ref.<id>}` 로 다시 배선해서** 등록한다. 저장소의
예제는 경로 참조로 배선돼 있어(fresh clone 에서 id 가 달라지므로 그게 맞다)
등록 경로를 태우지 못한다 — 캐시가 듣는 자리가 바로 거기라서 여기서 따로 만든다.

**보는 것은 빠름이 아니라 같음이다:**

- 두 번째 실행이 첫 실행과 **리포트 전문이 같다**
- 두 번째 실행은 스크립트를 **한 번도 파싱하지 않는다**
- 등록 후 등록소 파일을 직접 고치면 **여전히 `LNT-REG-001`** — 캐시가 가리지 않는다
- 캐시가 **정적 검사를 대신하지 않는다** — 등록은 여전히 금지 패턴에서 거부된다

**대역을 쓰지 않는다.** 진짜 등록소·진짜 CLI 로 돈다.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from lintomata import cli
from lintomata.checks import script as script_checks
from lintomata.checks.contracts import CACHE_VERSION
from lintomata.store.entries import CACHE_SUBDIR

EXAMPLE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "home-check"

_REF_RE = re.compile(
    r"\$\{env\.LINTOMATA_EXAMPLE_ROOT\}/(?:scripts|nodes|pipelines)/([\w.]+)"
)
"""등록소 참조로 갈아끼울 자리 — 스크립트·노드·파이프라인만. `targets/` 는 그대로 둔다."""


class Counter:
    """진짜 `extract_contract` 를 부르면서 횟수만 센다 (대역이 아니다)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        real = script_checks.extract_contract

        def counted(source: str, path: str):  # type: ignore[no-untyped-def]
            self.calls.append(path)
            return real(source, path)

        monkeypatch.setattr(script_checks, "extract_contract", counted)


@pytest.fixture()
def registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, str]:
    """예제를 `${ref.<id>}` 로 다시 배선해 전부 등록한다. `{파일이름: id}`."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    shutil.copytree(EXAMPLE_ROOT, work)
    monkeypatch.setenv("LINTOMATA_HOME", str(home))
    monkeypatch.setenv("LINTOMATA_EXAMPLE_ROOT", str(work))
    monkeypatch.setenv("LINTOMATA_EXAMPLE_OUT", str(tmp_path / "out"))

    ids: dict[str, str] = {}

    def add(kind: str, path: Path) -> str:
        code = cli.main([kind, "add", str(path)])
        out = capsys.readouterr().out
        assert code == 0, out
        return out.split()[0]

    def rewire(path: Path) -> None:
        text = _REF_RE.sub(lambda m: "${ref." + ids[m.group(1)] + "}", path.read_text("utf-8"))
        path.write_text(text, encoding="utf-8")

    for script in sorted((work / "scripts").glob("*.py")):
        ids[script.name] = add("script", script)
    for node in sorted((work / "nodes").glob("*.json")):
        if node.name.endswith(".test.json"):
            continue
        rewire(node)
        ids[node.name] = add("node", node)
    for pipeline in sorted((work / "pipelines").glob("*.json")):
        rewire(pipeline)
        ids[pipeline.name] = add("pipeline", pipeline)
    for spec in sorted((work / "specs").glob("*.json")):
        rewire(spec)
        ids[spec.name] = add("spec", spec)

    ids["__home__"] = str(home)
    ids["__work__"] = str(work)
    return ids


def check(capsys: pytest.CaptureFixture[str], spec_id: str) -> tuple[int, dict]:
    code = cli.main(["check", spec_id, "--json"])
    return code, json.loads(capsys.readouterr().out)


RUNNABLE = [("home_ok.json", 0), ("home_broken.json", 1), ("compare_ok.json", 0)]
"""돌려볼 Spec 과 그 종료 코드. **값 검증과 비교를 둘 다 태운다** —
캐시를 한쪽에만 붙이면 두 파이프라인 종류의 동작이 갈린다 (R4-1 이 실제로 겪었다)."""


@pytest.mark.parametrize(("spec", "expected"), RUNNABLE)
def test_두_번째_실행이_첫_실행과_같다(
    registered: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    spec: str,
    expected: int,
) -> None:
    """캐시가 있는 실행과 없는 실행의 결과가 다르면 그건 캐시가 아니라 결함이다."""
    first_code, first = check(capsys, registered[spec])
    second_code, second = check(capsys, registered[spec])

    assert (first_code, second_code) == (expected, expected)
    assert first == second


@pytest.mark.parametrize(("spec", "expected"), RUNNABLE)
def test_두_번째_실행은_스크립트를_다시_파싱하지_않는다(
    registered: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    spec: str,
    expected: int,
) -> None:
    """`schema.md` 2절: *등록은 검증 결과를 재사용하는 기제다.*

    ★ **비교 파이프라인(`compare_ok`)도 함께 태운다.** 값 검증에만 캐시를 붙이고
    비교를 빠뜨려도 결과는 같으므로 리포트 대조로는 안 잡힌다 — R4-1 이 겪은
    비대칭이 정확히 그 모양이었다. 여기서 **파싱 횟수로** 고정한다.
    """
    check(capsys, registered[spec])  # 캐시를 채운다

    counter = Counter(monkeypatch)
    code, _ = check(capsys, registered[spec])

    assert code == expected
    assert counter.calls == []


def test_캐시_파일이_등록소_안에_쌓인다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """자리는 `$LINTOMATA_HOME/cache/<id>.json` 이고 키(해시·버전)를 함께 적는다."""
    check(capsys, registered["home_ok.json"])

    cache_dir = Path(registered["__home__"]) / CACHE_SUBDIR
    written = sorted(cache_dir.glob("sc_*.json"))
    assert written != []
    payload = json.loads(written[0].read_text("utf-8"))
    assert payload["version"] == CACHE_VERSION
    assert len(payload["hash"]) == 64
    # 등록소 폴더에는 등록된 것만 있다 — 캐시를 등록소 파일 옆에 흘리지 않는다.
    # (`__pycache__` 는 스크립트를 실제로 로드한 파이썬이 만드는 것이라 별개다.)
    scripts = Path(registered["__home__"]) / "scripts"
    assert [p.name for p in scripts.iterdir() if p.suffix == ".json"] == []


def test_캐시_포맷_버전이_다르면_버린다(
    registered: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lintomata 를 올려 추출 방식이 바뀌면 옛 캐시는 무효다.

    ⚠ **리포트가 같은지로 물 수 없다.** 버전을 무시하고 옛 캐시를 그대로 써도
    같은 파일에서 나온 계약이라 리포트는 어차피 같다 — 버전 가드를 통째로 지워도
    통과해 버린다. 그래서 **다시 파싱했는지**를 본다.
    """
    check(capsys, registered["home_ok.json"])

    cached = sorted((Path(registered["__home__"]) / CACHE_SUBDIR).glob("sc_*.json"))
    assert cached != []
    for path in cached:
        payload = json.loads(path.read_text("utf-8"))
        payload["version"] = CACHE_VERSION + 1
        path.write_text(json.dumps(payload), encoding="utf-8")

    counter = Counter(monkeypatch)
    code, _ = check(capsys, registered["home_ok.json"])

    assert code == 0
    # 버전이 다른 캐시는 없는 것으로 쳤다 — 전부 다시 뽑았다.
    assert len(counter.calls) == len(cached)


def test_깨진_캐시는_없는_캐시다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """파생물이 본 검사를 막으면 안 된다 — 손상됐으면 그냥 다시 뽑는다."""
    first_code, first = check(capsys, registered["home_ok.json"])

    for path in (Path(registered["__home__"]) / CACHE_SUBDIR).glob("sc_*.json"):
        path.write_text("{ 깨진 JSON", encoding="utf-8")

    second_code, second = check(capsys, registered["home_ok.json"])
    assert (first_code, second_code) == (0, 0)
    assert first == second


def test_등록소_파일을_직접_고치면_여전히_STR_REG_001(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """★ **캐시가 이걸 가리면 안 된다.** 정적 검사 루트를 피한 수정을 잡는 자리다."""
    check(capsys, registered["home_ok.json"])  # 캐시를 채워 둔다

    target = Path(registered["__home__"]) / "scripts" / f"{registered['extract_buttons.py']}.py"
    target.write_text(target.read_text("utf-8") + "\n# 몰래 고쳤다\n", encoding="utf-8")

    code, report = check(capsys, registered["home_ok.json"])
    assert code == 2
    assert "LNT-REG-001" in {item.get("rule") for item in report["results"]}


def test_고쳐진_등록소_파일은_캐시가_아니라_다시_파싱된다(
    registered: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """키가 **내용 해시**라 무효화가 저절로 된다 — 옛 계약을 돌려주지 않는다."""
    check(capsys, registered["home_ok.json"])

    target = Path(registered["__home__"]) / "scripts" / f"{registered['extract_buttons.py']}.py"
    target.write_text(target.read_text("utf-8") + "\n# 몰래 고쳤다\n", encoding="utf-8")

    counter = Counter(monkeypatch)
    check(capsys, registered["home_ok.json"])

    assert [Path(p).name for p in counter.calls] == [
        f"{registered['extract_buttons.py']}.py"
    ]


def test_항목을_지우면_캐시도_사라진다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """등록소에 못 쓰는 파일을 남겨 두지 않는다."""
    check(capsys, registered["home_ok.json"])
    entry_id = registered["extract_buttons.py"]
    cached = Path(registered["__home__"]) / CACHE_SUBDIR / f"{entry_id}.json"
    assert cached.is_file()

    # 종료 코드 1 은 "참조가 깨졌다" 는 표시다 — 삭제는 막지 않는다 (`schema.md` 2절).
    assert cli.main(["script", "remove", entry_id]) == 1
    capsys.readouterr()

    assert not cached.exists()


def test_항목을_고치면_캐시도_사라진다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """`update` 도 마찬가지다. 해시가 달라져 어차피 안 읽히지만 **남겨 두지 않는다.**"""
    check(capsys, registered["home_ok.json"])
    entry_id = registered["extract_buttons.py"]
    cached = Path(registered["__home__"]) / CACHE_SUBDIR / f"{entry_id}.json"
    assert cached.is_file()

    source = Path(registered["__work__"]) / "scripts" / "extract_buttons.py"
    source.write_text(source.read_text("utf-8") + "\n# 주석 한 줄\n", encoding="utf-8")
    assert cli.main(["script", "update", entry_id, str(source)]) == 0
    capsys.readouterr()

    assert not cached.exists()


def test_캐시가_있어도_등록_시_정적_검사는_그대로_돈다(
    registered: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """캐시는 **재사용**이지 **삭제**가 아니다 — 금지 패턴은 여전히 등록을 막는다."""
    check(capsys, registered["home_ok.json"])

    bad = EXAMPLE_ROOT / "invalid" / "bad_banned.py"
    code = cli.main(["script", "add", str(bad)])
    out = capsys.readouterr().out

    assert code == 2
    assert "Not registered" in out
    assert "LNT-BAN-001" in out
