"""`examples/home-check` 를 **CLI 로 그대로 태우는** 통합 테스트.

예제를 문서에서 끝내지 않고 **회귀 방어**로 만드는 자리다. 저장소에 들어 있는
예제가 fresh 등록소에서 처음부터 도는지, 네 상태와 종료 코드가 설계대로 갈리는지,
`invalid/` 의 "일부러 틀린 것"이 **기대한 규칙 id 로** 걸리는지를 본다.

**대역을 쓰지 않는다.** 진짜 등록소·진짜 검사기·진짜 엔진·진짜 하네스로 돈다.
그리고 **반드시 `cli.main()` 을 통해 태운다** — 내부 함수를 직접 부르면 CLI 배선
결함을 못 잡는다(이 프로젝트에서 실제로 그런 결함이 있었다: R6-1).

**사용자 홈을 오염시키지 않는다.** `$STRICTLER_HOME` 과 예제의 출력 디렉터리를
전부 `tmp_path` 아래로 돌린다.

예제가 안 돌면 **그게 본체의 결함**이다 — 여기서 예제를 고쳐 통과시키지 말 것.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from strictler import cli

# ── 예제 위치 ────────────────────────────────────────────────────────────────

EXAMPLE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "home-check"
"""저장소 안의 예제 루트. `${env.STRICTLER_EXAMPLE_ROOT}` 로 주입한다."""

SPECS = EXAMPLE_ROOT / "specs"
NODES = EXAMPLE_ROOT / "nodes"
SCRIPTS = EXAMPLE_ROOT / "scripts"
LIBRARIES = EXAMPLE_ROOT / "libraries"
INVALID = EXAMPLE_ROOT / "invalid"


@pytest.fixture()
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """등록소와 출력 디렉터리를 tmp 로 돌린다. 반환값은 출력 디렉터리."""
    out = tmp_path / "out"
    monkeypatch.setenv("STRICTLER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STRICTLER_EXAMPLE_ROOT", str(EXAMPLE_ROOT))
    monkeypatch.setenv("STRICTLER_EXAMPLE_OUT", str(out))
    return out


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    """CLI 를 그대로 부른다. `(종료 코드, stdout)`."""
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    """`--json` 리포트를 받아 파싱한다."""
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


def rule_ids(report: dict) -> set[str]:
    return {item["rule"] for item in report["results"] if item.get("rule")}


def text_rule_ids(out: str) -> set[str]:
    """`add` 는 `--json` 을 받지 않으므로 텍스트 출력에서 규칙 id 를 뽑는다."""
    return {
        token.strip("()")
        for line in out.splitlines()
        if line.startswith("[error]")
        for token in line.split()
        if token.startswith("(STR-")
    }


# ── 1. 값 검증 파이프라인 — 네 상태와 종료 코드 ──────────────────────────────


def test_정상_spec_은_통과만_하고_종료코드_0(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """기획대로인 대상 → 통과만. 일곱 노드가 전부 돈다."""
    code, report = run_json(capsys, "check", str(SPECS / "home_ok.json"))

    assert code == 0
    assert report["summary"] == {"pass": 7, "violation": 0, "not_run": 0, "error": 0}
    # Action 이 실제로 부작용을 냈다 — `${state.__startedAt}` 이 들어온다.
    line = (example / "audit.log").read_text(encoding="utf-8").strip()
    stamp, source, size = line.split("\t")
    assert int(stamp) > 0
    assert source.endswith("targets/home.html")
    assert int(size) > 0


def test_어긋난_대상은_위반이고_종료코드_1(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """**위반은 정상 결과다.** 오류(2) 가 아니라 1 이고, 뒷단이 멈추지 않는다."""
    code, report = run_json(capsys, "check", str(SPECS / "home_broken.json"))

    assert code == 1
    assert report["summary"] == {"pass": 5, "violation": 2, "not_run": 0, "error": 0}

    violations = {item["node"]: item for item in report["results"] if item["status"] == "violation"}
    assert set(violations) == {"checkButtons", "checkMenu"}
    # Reckon 이 낸 규칙 이름과 문구가 리포트에 그대로 실린다.
    assert violations["checkButtons"]["rule"] == "expectedCount"
    assert "3개 기대, 2개 관측" in violations["checkButtons"]["message"]
    assert "4개 기대, 3개 관측" in violations["checkMenu"]["message"]
    # 위반이 났는데도 뒷단(detectMenu)이 돌았다 — 실패는 최대한 모은다.
    assert any(
        item["node"] == "detectMenu" and item["status"] == "pass" for item in report["results"]
    )


def test_없는_대상은_오류와_not_run_이고_종료코드_2(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """앞단이 오류로 끝나면 여파는 **not run** 이다 — 통과와 구분해 보고한다."""
    code, report = run_json(capsys, "check", str(SPECS / "home_missing.json"))

    assert code == 2
    assert report["summary"] == {"pass": 1, "violation": 0, "not_run": 5, "error": 1}

    error = next(item for item in report["results"] if item["status"] == "error")
    assert error["node"] == "readHtml"
    assert "FileNotFoundError" in error["message"]

    causes = {
        item["node"]: item["cause"]
        for item in report["results"]
        if item["status"] == "not_run"
    }
    # 전파 경로가 둘이다 — 데이터로 막힌 것과 **상태**로 막힌 것.
    assert causes["audit"] == {"node": "readHtml", "reason": "data_dependency"}
    assert causes["detectButtons"] == {"node": "readHtml", "reason": "state_unreachable"}
    assert causes["checkButtons"] == {"node": "detectButtons", "reason": "data_dependency"}


# ── 2. 비교 파이프라인 — 대상 3개 ────────────────────────────────────────────


def test_비교_파이프라인은_마크업이_달라도_개념이_같으면_통과(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`<button>` / `class="btn"` / `role="button"` 셋이 같은 개념을 낸다."""
    code, report = run_json(capsys, "check", str(SPECS / "compare_ok.json"))

    assert code == 0
    assert report["summary"] == {"pass": 3, "violation": 0, "not_run": 0, "error": 0}

    written = json.loads((example / "compare_ok.json").read_text(encoding="utf-8"))
    assert set(written) == {"buttons"}
    assert written["buttons"]["same"] is True
    # 대상이 **셋** 이다 — 짝지어 비교하는 것이 아니다.
    assert set(written["buttons"]["values"]) == {"alpha", "beta", "gamma"}
    assert all(
        value == {"count": 3, "labels": ["시작하기", "문서 보기", "문의하기"]}
        for value in written["buttons"]["values"].values()
    )


def test_비교는_하나만_달라도_위반(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """판정은 **목록 전부가 같은 값을 뱉느냐**다."""
    code, report = run_json(capsys, "check", str(SPECS / "compare_diff.json"))

    assert code == 1
    assert report["summary"] == {"pass": 2, "violation": 1, "not_run": 0, "error": 0}

    written = json.loads((example / "compare_diff.json").read_text(encoding="utf-8"))
    assert written["buttons"]["same"] is False
    values = written["buttons"]["values"]
    assert values["alpha"] == values["beta"]
    assert values["gamma"]["count"] == 4


# ── 3. 한 Spec 에 네 상태 — 조용히 사라진 노드가 없다 ────────────────────────


def test_모든_노드가_네_상태_중_정확히_하나에_들어간다(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`all_in_one` 은 plan 4개(통과·위반·오류·비교)를 한 번에 돈다.

    한 항목이 실패해도 다른 항목은 전부 돈다. 그리고 **노드를 전수 검사해**
    각 노드가 4상태 중 정확히 하나에 들어갔는지 본다 — 조용히 사라진 노드가
    있으면 리포트가 거짓이 된다.
    """
    code, report = run_json(capsys, "check", str(SPECS / "all_in_one.json"))

    assert code == 2  # 오류가 하나라도 있으면 2
    summary = report["summary"]
    assert summary == {"pass": 15, "violation": 3, "not_run": 5, "error": 1}

    # page-check 7노드 × 3 + buttons-same 3노드 = 24
    assert sum(summary.values()) == 24
    assert len(report["results"]) == 24

    seen = [(item["path"], item["node"]) for item in report["results"]]
    assert len(set(seen)) == 24, "같은 노드가 두 번 보고됐다"
    assert {item["status"] for item in report["results"]} == {
        "pass",
        "violation",
        "not_run",
        "error",
    }
    # plan[2] 가 오류인데 plan[3] 비교는 정상 수행됐다.
    assert any(
        item["path"].startswith("all_in_one.json > plan[3]") and item["status"] != "not_run"
        for item in report["results"]
    )


# ── 4. 노드 단위테스트 ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["detect_buttons", "check_count", "audit"],
    ids=["perceive", "reckon", "action"],
)
def test_노드_단위테스트가_경로로_돈다(
    example: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """Perceive(값검사) · Reckon(대조쌍) · Action(값 동일성 자동검사)."""
    code, report = run_json(capsys, "node", "test", str(NODES / f"{name}.test.json"))

    assert code == 0, report
    assert report["summary"]["violation"] == 0
    assert report["summary"]["error"] == 0
    assert report["summary"]["pass"] >= 1


# ── 5. `invalid/` — 검사가 실제로 잡는가 ─────────────────────────────────────


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(
            ("script", "add", str(INVALID / "bad_banned.py")),
            {
                "STR-BAN-001",
                "STR-BAN-002",
                "STR-BAN-003",
                "STR-BAN-004",
                "STR-TYPE-001",
                "STR-TYPE-002",
            },
            id="금지-위반",
        ),
        pytest.param(
            ("script", "add", str(INVALID / "bad_output_primitive.py")),
            {"STR-CONTRACT-003"},
            id="출력이-dataclass-아님",
        ),
        pytest.param(
            ("script", "add", str(INVALID / "bad_dependency.py")),
            {"STR-DEP-001"},
            id="선언한-패키지가-환경에-없음",
        ),
        pytest.param(
            ("node", "add", str(INVALID / "bad_reckon_no_verdict.json")),
            {"STR-CONTRACT-007"},
            id="판정-필드-없는-Reckon",
        ),
        pytest.param(
            ("library", "add", str(INVALID / "lib_banned.py")),
            {"STR-BAN-001"},
            id="라이브러리에서-시간을-읽음",
        ),
        pytest.param(
            ("library", "add", str(INVALID / "lib_dataclass.py")),
            {"STR-LIB-004"},
            id="라이브러리가-dataclass-선언",
        ),
        pytest.param(
            ("node", "add", str(INVALID / "bad_unwired.json")),
            {"STR-LIB-001"},
            id="슬롯을-요구하는데-배선이-없음",
        ),
        pytest.param(
            ("pipeline", "add", str(INVALID / "pipeline_ambiguous.json")),
            {"STR-GRAPH-003"},
            id="모호한-inputs",
        ),
        pytest.param(
            ("pipeline", "add", str(INVALID / "pipeline_dead_state.json")),
            {"STR-STATE-006"},
            id="도달-불가-노드",
        ),
    ],
)
def test_일부러_틀린_것은_등록되지_않고_기대한_규칙이_나온다(
    example: Path,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    expected: set[str],
) -> None:
    """**등록 시점에 잡는 것이 요점이다** — 돌리기 전에 자기 수정 신호를 준다."""
    kind = argv[0]
    code, out = run(capsys, *argv)

    assert code == 2
    assert "등록하지 않았습니다" in out
    assert text_rule_ids(out) == expected

    # 등록소에 들어가지 않았다.
    listed_code, listed = run(capsys, kind, "list")
    assert listed_code == 0
    assert f"등록된 {kind} 가 없습니다." in listed


def test_기댓값_하드코딩은_단위테스트가_잡는다(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """정적으로는 못 잡는 자리다 — `input` 은 같고 `params` 만 다른 대조쌍으로 잡는다.

    케이스 둘은 각각 **통과**한다(스크립트가 예외를 내지도, 타입이 틀리지도
    않았다). 걸리는 것은 **판정이 갈리지 않는다**는 사실 쪽이다.
    """
    code, report = run_json(
        capsys, "node", "test", str(INVALID / "bad_reckon_hardcoded.test.json")
    )

    assert code == 2
    assert report["summary"]["pass"] == 2
    assert rule_ids(report) == {"STR-TEST-007"}


# ── 6. fresh 등록소로 처음부터 — id 참조가 남아 있으면 여기서 깨진다 ─────────


def test_fresh_등록소에_전부_등록하고_id_로_돈다(
    example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """예제는 **경로 참조**로 배선돼 있어 새로 발급된 id 와 무관하게 돈다.

    `${ref.sc_...}` 를 남겨두면 fresh clone 에서 다른 id 가 발급되어 여기서 깨진다.
    등록 순서(`scripts → nodes → pipelines → specs`)대로 넣고, 발급된 id 로
    `check` 와 `node test` 를 돌린다.
    """
    ids: dict[str, str] = {}

    def add(kind: str, path: Path) -> str:
        code, out = run(capsys, kind, "add", str(path))
        assert code == 0, out
        return out.split()[0]

    for library in sorted(LIBRARIES.glob("*.py")):
        add("library", library)
    for script in sorted(SCRIPTS.glob("*.py")):
        add("script", script)
    for node in sorted(NODES.glob("*.json")):
        if node.name.endswith(".test.json"):
            continue
        ids[node.stem] = add("node", node)
    for pipeline in sorted((EXAMPLE_ROOT / "pipelines").glob("*.json")):
        add("pipeline", pipeline)
    for spec in sorted(SPECS.glob("*.json")):
        ids[spec.stem] = add("spec", spec)

    # 깨진 구성이 하나도 없다.
    for kind in ("script", "library", "node", "pipeline", "spec"):
        code, out = run(capsys, kind, "list")
        assert code == 0, out
        assert "✕" not in out

    assert run(capsys, "check", ids["home_ok"])[0] == 0
    assert run(capsys, "check", ids["home_broken"])[0] == 1
    assert run(capsys, "check", ids["home_missing"])[0] == 2
    assert run(capsys, "check", ids["compare_ok"])[0] == 0
    assert run(capsys, "check", ids["compare_diff"])[0] == 1

    # 단위테스트가 노드와 함께 등록소로 복사된다 (R5-2) — id 형태가 그대로 돈다.
    code, out = run(capsys, "node", "test", ids["detect_buttons"])
    assert code == 0, out
    assert ids["detect_buttons"] in out


# ── 7. 배선된 라이브러리를 못 풀면 — 라벨 하나, 거짓 안내 없음, 여파는 not run ──


@pytest.fixture()
def broken_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """예제를 tmp 로 복사하고 **배선된 라이브러리 파일만 지운다.**

    예제 원본을 건드리지 않으려고 복사한다. 반환값은 복사본 루트.
    """
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "libraries" / "buttons.py").unlink()
    monkeypatch.setenv("STRICTLER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STRICTLER_EXAMPLE_ROOT", str(root))
    monkeypatch.setenv("STRICTLER_EXAMPLE_OUT", str(tmp_path / "out"))
    return root


def test_라이브러리를_못_풀면_노드_id_하나로_찍히고_실행되지_않는다(
    broken_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 세 가지를 한 번에 고정한다 (Gate 4 지적).

    1. **라벨이 노드 id 하나다** — 등록 검사에서 온 `info.name`(`detect-buttons`) 과
       구동에서 온 노드 id(`detectButtons`) 로 **같은 노드가 두 번** 찍히면
       같은 것인지 알 수 없고, `not run` 전파는 노드 id 로 대조하므로 여파도 어긋난다
    2. **그 노드를 돌리지 않는다** — 억지로 로드하면 스크립트가 `ImportError` 로 죽으며
       *"배선이 없습니다"* 라는 **거짓 안내**가 진짜 원인(파일이 없다) 위에 덮인다
    3. 여파는 `not_run` 이다
    """
    code, report = run_json(
        capsys, "check", str(broken_library / "specs" / "home_ok.json")
    )

    assert code == 2
    errors = [item for item in report["results"] if item["status"] == "error"]
    assert [item["node"] for item in errors] == ["detectButtons"]
    assert rule_ids(report) == {"STR-REF-001"}
    # 노드 `info.name` 으로는 아무것도 찍히지 않는다.
    assert all(item["node"] != "detect-buttons" for item in report["results"])
    # **거짓 안내가 없다** — 배선은 있고 파일이 없는 것이다.
    assert "배선이 없습니다" not in json.dumps(report, ensure_ascii=False)
    assert "ImportError" not in json.dumps(report, ensure_ascii=False)

    not_run = {item["node"]: item["cause"] for item in report["results"] if item["status"] == "not_run"}
    assert not_run == {"checkButtons": {"node": "detectButtons", "reason": "data_dependency"}}


def test_비교_파이프라인도_같은_형태로_낸다(
    broken_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """**한쪽만 고치면 또 갈린다** — 값 검증과 비교가 같은 처리를 받는다."""
    code, report = run_json(
        capsys, "check", str(broken_library / "specs" / "compare_ok.json")
    )

    assert code == 2
    errors = [item for item in report["results"] if item["status"] == "error"]
    assert [item["node"] for item in errors] == ["buttons"]
    assert rule_ids(report) == {"STR-REF-001"}
    assert all(item["node"] != "compare-buttons" for item in report["results"])
    assert "배선이 없습니다" not in json.dumps(report, ensure_ascii=False)
