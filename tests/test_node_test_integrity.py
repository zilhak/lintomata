"""`node test` 도 등록소 무결성을 본다 — 해시 대조 (`schema.md` 2·13절).

`check` 는 실행 직전에 `STR-REG-001` 로 잡는데 `node test` 는 안 봤다. 그래서
**등록소 파일을 정적 검사 루트 밖에서 고친 뒤에도 `[pass]` 가 나왔다.**
통과했다고 보고하는데 검사한 것이 검증을 통과한 그 내용이 아니면 거짓 리포트다.

**대역을 쓰지 않는다.** 진짜 등록소·진짜 CLI·진짜 하네스로 돈다 — 이 프로젝트에서
이 계열 결함이 리뷰를 빠져나간 원인이 매번 *"테스트가 stub 으로 진짜 모듈을 가린 것"*
이었다 (R6-1: `node test` 가 다른 노드를 돌리고 `[pass]` 를 찍었다).

**대조 자체는 `engine.drive` 가 한다** — `check` 와 같은 함수다. 두 벌이 되면 갈린다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from strictler import cli

EXAMPLE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "home-check"


@pytest.fixture()
def registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, str]:
    """`detect_buttons` 를 `${ref.sc_...}` 배선으로 등록한다. `{"home","node","script"}`."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    shutil.copytree(EXAMPLE_ROOT, work)
    monkeypatch.setenv("STRICTLER_HOME", str(home))
    monkeypatch.setenv("STRICTLER_EXAMPLE_ROOT", str(work))
    monkeypatch.setenv("STRICTLER_EXAMPLE_OUT", str(tmp_path / "out"))

    def add(kind: str, path: Path) -> str:
        code = cli.main([kind, "add", str(path)])
        out = capsys.readouterr().out
        assert code == 0, out
        return out.split()[0]

    script_id = add("script", work / "scripts" / "perceive_buttons.py")
    node_file = work / "nodes" / "detect_buttons.json"
    node_file.write_text(
        node_file.read_text("utf-8").replace(
            "${env.STRICTLER_EXAMPLE_ROOT}/scripts/perceive_buttons.py",
            "${ref." + script_id + "}",
        ),
        encoding="utf-8",
    )
    node_id = add("node", node_file)
    return {"home": str(home), "node": node_id, "script": script_id, "work": str(work)}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def rules_of(report: dict) -> set[str]:
    return {item["rule"] for item in report["results"] if item.get("rule")}


def tamper(path: Path) -> None:
    """정적 검사 루트를 피해 등록소 파일을 직접 고친다 — `STR-REG-001` 이 상정하는 그것."""
    path.write_text(path.read_text("utf-8") + "\n", encoding="utf-8")


def test_멀쩡하면_그대로_통과한다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = run(capsys, "node", "test", registered["node"])

    assert code == 0, report
    assert report["summary"]["error"] == 0
    assert report["summary"]["pass"] >= 1


def test_등록소_스크립트를_고치면_STR_REG_001(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 이 구멍이 이 커밋의 이유다 — 고쳐진 스크립트가 `[pass]` 로 나왔다."""
    tamper(Path(registered["home"]) / "scripts" / f"{registered['script']}.py")

    code, report = run(capsys, "node", "test", registered["node"])

    assert code == 2
    assert rules_of(report) == {"STR-REG-001"}
    assert report["summary"]["pass"] == 0


def test_등록소_노드_파일을_고치면_STR_REG_001(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """노드 쪽도 같다. **`STR-TEST-008` 이 아니다** — 대조할 정본 자체가 흔들렸다."""
    tamper(Path(registered["home"]) / "nodes" / f"{registered['node']}.json")

    code, report = run(capsys, "node", "test", registered["node"])

    assert code == 2
    assert rules_of(report) == {"STR-REG-001"}


def test_스크립트_등록을_지우면_STR_REG_002(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """삭제도 `check` 와 같은 규칙으로 나온다 — 새 규칙을 만들지 않는다."""
    assert cli.main(["script", "remove", registered["script"]]) == 1
    capsys.readouterr()

    code, report = run(capsys, "node", "test", registered["node"])

    assert code == 2
    assert "STR-REG-002" in rules_of(report)


def test_경로로_부르면_해시_대조가_없다(
    registered: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """등록소 밖 파일에는 대조할 해시가 없다 — 그 경로는 그대로 둔다.

    노드가 등록소 스크립트를 가리키므로 **스크립트 해시는 여전히 본다.**
    보지 않는 것은 *경로로 준 테스트·노드 파일* 쪽이다.
    """
    test_file = Path(registered["work"]) / "nodes" / "detect_buttons.test.json"

    code, report = run(capsys, "node", "test", str(test_file))

    assert code == 0, report
    assert report["summary"]["error"] == 0
