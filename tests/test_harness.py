"""Step 4-a — 노드 단위테스트 하네스 (`testing/harness.py`).

**대역을 쓰지 않는다.** 실제 스크립트 파일·노드 JSON·등록소로 돌린다 — Step 1·2 통합에서
남의 모듈을 stub 으로 끼고 돌린 탓에 규칙 슬롯 계약 위반 14건이 merge 시점까지 안 잡혔기
때문이다. 여기서 진짜 구현을 그대로 쓰면 슬롯 누락이 곧바로 `LintomataError` 로 터진다.

짚는 것:
  - 3단계가 **각자 자기 규칙 id** 로 나오는가 (①은 테스트가, ②③은 스크립트가 틀린 것)
  - **Action 의 값 동일성이 `expect` 없이도** 자동 검사되는가
  - **Reckon 반응성** — 대조쌍이 없으면 `-006`, 있는데 판정이 같으면 `-007`.
    **기댓값을 하드코딩한 스크립트를 실제로 만들어** `-007` 이 나오는지 본다
  - 입력 없는 노드(`Args` 에 `input` 필드 없음)의 fixture 가 도는가
  - `bytes` fixture(`{"$file": ...}`)가 실제 파일에서 채워지는가
  - **모든 오류 경로를 태워 `Finding.rule_id` 가 기대값인지** 확인한다
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from lintomata import rules
from lintomata.errors import Finding, LintomataError
from lintomata.model import NodeTest
from lintomata.model import TestCase as Case
from lintomata.store.entries import Store
from lintomata.testing import harness


# ── fixture 조립 ─────────────────────────────────────────────────────────────


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    return path


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class Project:
    """스크립트 → 노드 → 테스트 세 층을 실제 파일로 깐다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = Store(root / "home")
        self.env = {"HOME": str(root), "PROJECT_ROOT": str(root)}

    def script(self, name: str, body: str) -> Path:
        return write(self.root / "scripts" / f"{name}.py", body)

    def node(self, name: str, node_type: str, script: Path | str) -> Path:
        return write_json(
            self.root / "nodes" / f"{name}.json",
            {
                "info": {"name": name, "description": f"{name} 노드"},
                "type": node_type,
                "script": str(script),
            },
        )

    def test_file(self, node_path: Path | str, cases: list[dict[str, Any]]) -> NodeTest:
        return NodeTest.model_validate({"node": str(node_path), "cases": cases})

    def run(self, node_test: NodeTest) -> list[Finding]:
        return harness.run_node_test(node_test, store=self.store, env=self.env)

    def register(self, node_path: Path) -> str:
        """노드를 등록소에 넣고 id 를 준다 — `node test <id>` 형태를 재현한다."""
        return self.store.add("node", node_path).id

    def run_by_id(self, node_test: NodeTest, node_id: str) -> list[Finding]:
        """**id 로 부른 경우** — 그 id 의 등록소 노드가 정본이다 (R6-1)."""
        return harness.run_node_test(
            node_test, store=self.store, env=self.env, node_id=node_id
        )


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    return Project(tmp_path)


def ids(findings: list[Finding]) -> list[str]:
    return [item.rule_id for item in findings]


def statuses(findings: list[Finding]) -> list[str]:
    return [item.status for item in findings]


# ── 스크립트 본문들 ──────────────────────────────────────────────────────────

PERCEIVE = """
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=args.input.html.count("<button")))
"""

PERCEIVE_BAD_OUTPUT = """
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count="셋"))
"""

PERCEIVE_RAISES = """
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        if not args.input.html:
            raise ValueError("버튼을 셀 수 없습니다")
        return returnResult(Percept(count=1))
"""

RECKON = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Params:
        expected: int

    @dataclass
    class Verdict:
        passed: bool
        message: str

    @dataclass
    class Args:
        input: Percept
        params: Params

    def runNode(args: Args) -> Verdict:
        ok = args.input.count == args.params.expected
        return returnResult(Verdict(passed=ok, message="" if ok else "개수가 다릅니다"))
"""

RECKON_HARDCODED = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Params:
        expected: int

    @dataclass
    class Verdict:
        passed: bool
        message: str

    @dataclass
    class Args:
        input: Percept
        params: Params

    def runNode(args: Args) -> Verdict:
        ok = args.input.count == 3
        return returnResult(Verdict(passed=ok, message="" if ok else "개수가 다릅니다"))
"""

ACTION_PASSTHROUGH = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Percept

    def runNode(args: Args):
        return returnResult(args.input)
"""

ACTION_MUTATES = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Percept

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=args.input.count + 1))
"""

VANTAGE = """
    from dataclasses import dataclass

    @dataclass
    class Params:
        url: str

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Args:
        params: Params

    def runNode(args: Args) -> Scene:
        return returnResult(Scene(url=args.params.url))
"""

SENSE_BYTES = """
    from dataclasses import dataclass

    @dataclass
    class Shot:
        image: bytes

    @dataclass
    class Size:
        size: int

    @dataclass
    class Args:
        input: Shot

    def runNode(args: Args) -> Size:
        return returnResult(Size(size=len(args.input.image)))
"""

SENSE_BYTES_LIST = """
    from dataclasses import dataclass

    @dataclass
    class Shots:
        images: list[bytes]

    @dataclass
    class Total:
        total: int

    @dataclass
    class Args:
        input: Shots

    def runNode(args: Args) -> Total:
        return returnResult(Total(total=sum(len(one) for one in args.input.images)))
"""

FORGOT_RETURN = """
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        returnResult(Percept(count=1))
"""

UNIMPORTABLE = """
    import lintomata_그런_모듈은_없다
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=0))
"""

BANNED = """
    import time
    from dataclasses import dataclass

    @dataclass
    class Sensum:
        html: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Sensum

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=int(time.time())))
"""


def perceive_node(project: Project, body: str = PERCEIVE, name: str = "detect") -> Path:
    return project.node(name, "perceive", project.script(name, body))


# ── 로드 ─────────────────────────────────────────────────────────────────────


def test_load_node_test_reads_file(project: Project) -> None:
    node_path = perceive_node(project)
    path = write_json(
        project.root / "nodes" / "detect.test.json",
        {"node": str(node_path), "cases": [{"name": "평범", "args": {"input": {"html": ""}}}]},
    )

    node_test, findings = harness.load_node_test(path, project.env)

    assert findings == []
    assert node_test is not None
    assert node_test.node == str(node_path)
    assert node_test.cases[0].expect is None


def test_load_node_test_shape_error_is_a_finding(project: Project) -> None:
    path = write_json(
        project.root / "nodes" / "x.test.json",
        {"node": str(project.root / "nodes" / "x.json"), "cases": [{"name": "a"}]},
    )

    node_test, findings = harness.load_node_test(path, project.env)

    assert node_test is None
    assert findings and all(item.status == "error" for item in findings)
    assert "cases.0.args" in findings[0].message


def test_load_node_test_applies_path_rule(project: Project) -> None:
    path = write_json(project.root / "x.test.json", {"node": "nodes/x.json", "cases": []})

    node_test, findings = harness.load_node_test(path, project.env)

    assert node_test is None
    assert ids(findings) == ["LNT-PATH-001"]


def test_load_node_test_broken_json_is_an_error(project: Project) -> None:
    path = write(project.root / "x.test.json", "{ not json")

    with pytest.raises(LintomataError):
        harness.load_node_test(path, project.env)


def test_load_node_test_accepts_registered_ref(project: Project) -> None:
    node_path = perceive_node(project)
    entry = project.store.add("node", node_path)
    path = write_json(
        project.root / "x.test.json",
        {"node": f"${{ref.{entry.id}}}", "cases": []},
    )

    node_test, findings = harness.load_node_test(path, project.env)

    assert findings == []
    assert node_test is not None


# ── 대상 노드 찾기 ───────────────────────────────────────────────────────────


def test_missing_node_file_is_ref_not_found(project: Project) -> None:
    node_test = project.test_file(project.root / "nodes" / "없다.json", [])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-REF-002"]


def test_unregistered_ref_is_reg_not_found(project: Project) -> None:
    node_test = project.test_file("${ref.nd_deadbeef}", [])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-REG-002"]


def test_registered_node_runs(project: Project) -> None:
    node_path = perceive_node(project)
    entry = project.store.add("node", node_path)
    node_test = project.test_file(
        f"${{ref.{entry.id}}}",
        [{"name": "버튼 둘", "args": {"input": {"html": "<button><button>"}}}],
    )

    findings = project.run(node_test)

    assert statuses(findings) == ["pass"]


def test_static_failure_stops_before_running(project: Project) -> None:
    node_path = project.node("banned", "perceive", project.script("banned", BANNED))
    node_test = project.test_file(
        node_path, [{"name": "돌면 안 된다", "args": {"input": {"html": ""}}}]
    )

    findings = project.run(node_test)

    assert "LNT-BAN-001" in ids(findings)
    assert not any(item.rule_id.startswith("LNT-TEST") for item in findings)


# ── 3단계 ────────────────────────────────────────────────────────────────────


def test_stage1_missing_fixture_field_blames_the_test(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(node_path, [{"name": "빈 fixture", "args": {"input": {}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001"]
    assert "The test definition is what is wrong here" in findings[0].message


def test_stage1_wrong_fixture_type_blames_the_test(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(node_path, [{"name": "타입 어긋남", "args": {"input": {"html": 3}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001"]


def test_stage1_unknown_args_key_blames_the_test(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(
        node_path,
        [{"name": "모르는 자리", "args": {"input": {"html": ""}, "params": {"expected": 1}}}],
    )

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001"]


def test_stage2_script_exception(project: Project) -> None:
    node_path = perceive_node(project, PERCEIVE_RAISES, "boom")
    node_test = project.test_file(node_path, [{"name": "터진다", "args": {"input": {"html": ""}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-002"]
    assert "버튼을 셀 수 없습니다" in findings[0].message


def test_stage3_output_type_mismatch(project: Project) -> None:
    node_path = perceive_node(project, PERCEIVE_BAD_OUTPUT, "badout")
    node_test = project.test_file(node_path, [{"name": "타입 어긋남", "args": {"input": {"html": ""}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-003"]
    assert "Percept" in findings[0].message


def test_stages_run_in_order(project: Project) -> None:
    """fixture 가 틀리면 스크립트를 아예 돌리지 않는다 — ① 이 ② 보다 먼저다."""
    node_path = perceive_node(project, PERCEIVE_RAISES, "order")
    node_test = project.test_file(node_path, [{"name": "fixture 부터 틀렸다", "args": {"input": {}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001"]


# ── expect (커스텀 층) ───────────────────────────────────────────────────────


def test_expect_match_passes(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "버튼 셋",
                "args": {"input": {"html": "<button><button><button>"}},
                "expect": {"count": 3},
            }
        ],
    )

    findings = project.run(node_test)

    assert statuses(findings) == ["pass"]


def test_expect_mismatch(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(
        node_path,
        [{"name": "하나뿐", "args": {"input": {"html": "<button>"}}, "expect": {"count": 3}}],
    )

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-004"]
    assert "'count': 3" in findings[0].message and "'count': 1" in findings[0].message


def test_no_expect_still_type_checks(project: Project) -> None:
    """기대값을 안 써도 타입 검증은 공짜로 따라온다."""
    node_path = perceive_node(project, PERCEIVE_BAD_OUTPUT, "freebie")
    node_test = project.test_file(node_path, [{"name": "expect 없음", "args": {"input": {"html": ""}}}])

    assert ids(project.run(node_test)) == ["LNT-TEST-003"]


# ── Action — 값 동일성 ───────────────────────────────────────────────────────


def test_action_transparency_checked_without_expect(project: Project) -> None:
    node_path = project.node("click", "action", project.script("click", ACTION_MUTATES))
    node_test = project.test_file(node_path, [{"name": "값을 건드린다", "args": {"input": {"count": 1}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-005"]
    assert "값을 건드린다" in findings[0].message
    # 다른 TEST 규칙은 전부 `node` 가 차 있다 — 여기만 비면 리포트의 노드 칸이
    # Action 결과에서만 빈다 (R6-3).
    assert findings[0].node == "click"


def test_action_passthrough_passes(project: Project) -> None:
    node_path = project.node("pass", "action", project.script("pass", ACTION_PASSTHROUGH))
    node_test = project.test_file(node_path, [{"name": "그대로 흘린다", "args": {"input": {"count": 2}}}])

    findings = project.run(node_test)

    assert statuses(findings) == ["pass"]


def test_action_transparency_compares_by_structure() -> None:
    """이름이 달라도 구조가 같으면 같은 값이다 (`schema.md` 7절). 중첩·리스트도 그렇다."""
    from dataclasses import dataclass, field

    @dataclass
    class Item:
        label: str

    @dataclass
    class Left:
        count: int
        items: list = field(default_factory=list)

    @dataclass
    class Right:
        count: int
        items: list = field(default_factory=list)

    case = Case.model_validate({"name": "n", "args": {}})
    assert harness.check_action_transparency(case, Left(1, [Item("a")]), Right(1, [Item("a")])) == []
    assert ids(
        harness.check_action_transparency(case, Left(1, [Item("a")]), Right(1, [Item("b")]))
    ) == ["LNT-TEST-005"]


# ── Reckon — 기댓값 반응성 ───────────────────────────────────────────────────


def reckon_cases(*pairs: tuple[int, int]) -> list[dict[str, Any]]:
    return [
        {
            "name": f"count={count} expected={expected}",
            "args": {"input": {"count": count}, "params": {"expected": expected}},
        }
        for count, expected in pairs
    ]


def test_reckon_with_contrast_pair_passes(project: Project) -> None:
    node_path = project.node("judge", "reckon", project.script("judge", RECKON))
    node_test = project.test_file(node_path, reckon_cases((3, 3), (3, 4)))

    findings = project.run(node_test)

    assert ids(findings) == ["", ""]
    assert statuses(findings) == ["pass", "pass"]


def test_reckon_without_contrast_pair_warns(project: Project) -> None:
    node_path = project.node("judge", "reckon", project.script("judge", RECKON))
    node_test = project.test_file(node_path, reckon_cases((3, 3), (5, 5)))

    findings = project.run(node_test)

    warned = [item for item in findings if item.rule_id == "LNT-TEST-006"]
    assert len(warned) == 1
    assert warned[0].status == "violation"  # 경고 — 정상 결과지 도구 실패가 아니다


def test_reckon_hardcoded_expected_is_an_error(project: Project) -> None:
    """★ 기댓값을 하드코딩한 스크립트를 실제로 만들어 `-007` 이 나오는지 본다."""
    node_path = project.node("hard", "reckon", project.script("hard", RECKON_HARDCODED))
    node_test = project.test_file(node_path, reckon_cases((3, 3), (3, 4)))

    findings = project.run(node_test)

    caught = [item for item in findings if item.rule_id == "LNT-TEST-007"]
    assert len(caught) == 1
    assert caught[0].status == "error"
    assert "yet both decide pass" in caught[0].message


def test_reckon_같은_params_케이스_둘은_대조쌍이_아니다(project: Project) -> None:
    """`params` 가 같으면 흔들어본 것이 아니다 — **쌍으로 세면 `-007` 오탐**이다.

    `input` 도 `params` 도 똑같은 중복 케이스 둘은 판정이 당연히 같으므로,
    쌍으로 세는 순간 "기댓값을 안 쓴다" 는 거짓 결론이 나온다. 대조쌍이 없는
    것이므로 나와야 할 것은 `-006`(경고)이다.
    """
    node_path = project.node("judge", "reckon", project.script("judge", RECKON))
    node_test = project.test_file(node_path, reckon_cases((3, 3), (3, 3)))

    findings = project.run(node_test)

    assert [item.rule_id for item in findings if item.rule_id] == ["LNT-TEST-006"]


def test_reckon_contrast_ignores_unreadable_verdicts(project: Project) -> None:
    """못 돈 케이스를 근거로 "기댓값을 안 쓴다" 고 단정하지 않는다."""
    cases = [
        Case.model_validate(
            {"name": "a", "args": {"input": {"count": 1}, "params": {"expected": 1}}}
        ),
        Case.model_validate(
            {"name": "b", "args": {"input": {"count": 1}, "params": {"expected": 2}}}
        ),
    ]

    findings = harness.check_reckon_contrast(cases, [None, None])

    assert ids(findings) == ["LNT-TEST-006"]


def test_reckon_contrast_not_run_for_other_types(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(node_path, [{"name": "한 건", "args": {"input": {"html": ""}}}])

    assert ids(project.run(node_test)) == [""]


# ── 그 밖의 형태 ─────────────────────────────────────────────────────────────


def test_node_without_input_runs(project: Project) -> None:
    """`Args` 에 `input` 필드가 없는 노드도 fixture 로 돈다."""
    node_path = project.node("open", "vantage", project.script("open", VANTAGE))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "params 만",
                "args": {"params": {"url": "https://example.test/"}},
                "expect": {"url": "https://example.test/"},
            }
        ],
    )

    assert statuses(project.run(node_test)) == ["pass"]


def test_bytes_fixture_is_read_from_file(project: Project) -> None:
    shot = project.root / "fixtures" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"\x89PNG\r\n")
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "스크린샷",
                "args": {"input": {"image": {"$file": "${env.PROJECT_ROOT}/fixtures/shot.png"}}},
                "expect": {"size": 6},
            }
        ],
    )

    assert statuses(project.run(node_test)) == ["pass"]


def test_bytes_fixture_missing_file_blames_the_test(project: Project) -> None:
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "없는 파일",
                "args": {"input": {"image": {"$file": "${env.PROJECT_ROOT}/없다.png"}}},
            }
        ],
    )

    assert ids(project.run(node_test)) == ["LNT-TEST-001"]


def test_bytes_fixture_relative_path_is_caught(project: Project) -> None:
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path,
        [{"name": "상대경로", "args": {"input": {"image": {"$file": "fixtures/shot.png"}}}}],
    )

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001"]
    assert (
        "LNT-PATH-001" in findings[0].message
        or "must be absolute" in findings[0].message
    )


def test_file_marker_must_be_alone(project: Project) -> None:
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "곁다리 키",
                "args": {"input": {"image": {"$file": "/tmp/x", "size": 1}}},
            }
        ],
    )

    assert ids(project.run(node_test)) == ["LNT-TEST-001"]


def test_every_case_runs_even_if_one_fails(project: Project) -> None:
    """실패는 최대한 모은다 — 한 케이스가 깨져도 나머지는 전부 돈다."""
    node_path = perceive_node(project)
    node_test = project.test_file(
        node_path,
        [
            {"name": "깨진 fixture", "args": {"input": {}}},
            {"name": "멀쩡", "args": {"input": {"html": "<button>"}}, "expect": {"count": 1}},
            {"name": "틀린 기대", "args": {"input": {"html": ""}}, "expect": {"count": 9}},
        ],
    )

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-001", "", "LNT-TEST-004"]
    assert [item.path.split(" > ")[-1] for item in findings] == [
        "cases[0] 깨진 fixture",
        "cases[1] 멀쩡",
        "cases[2] 틀린 기대",
    ]


def test_findings_carry_the_node_name(project: Project) -> None:
    node_path = perceive_node(project)
    node_test = project.test_file(node_path, [{"name": "a", "args": {"input": {}}}])

    assert {item.node for item in project.run(node_test)} == {"detect"}


def test_bytes_list_fixture(project: Project) -> None:
    shot = project.root / "fixtures" / "a.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"1234")
    node_path = project.node("shots", "sense", project.script("shots", SENSE_BYTES_LIST))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "여러 장",
                "args": {"input": {"images": [{"$file": str(shot)}, {"$file": str(shot)}]}},
                "expect": {"total": 8},
            }
        ],
    )

    assert statuses(project.run(node_test)) == ["pass"]


def test_file_marker_value_must_be_a_path(project: Project) -> None:
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path, [{"name": "숫자", "args": {"input": {"image": {"$file": 7}}}}]
    )

    assert ids(project.run(node_test)) == ["LNT-TEST-001"]


def test_bad_file_marker_in_expect_blames_the_test(project: Project) -> None:
    shot = project.root / "fixtures" / "a.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"1234")
    node_path = project.node("shot", "sense", project.script("shot", SENSE_BYTES))
    node_test = project.test_file(
        node_path,
        [
            {
                "name": "기대값 쪽 경로가 깨졌다",
                "args": {"input": {"image": {"$file": str(shot)}}},
                "expect": {"size": {"$file": "relative/x"}},
            }
        ],
    )

    assert ids(project.run(node_test)) == ["LNT-TEST-001"]


def test_forgotten_return_is_output_mismatch(project: Project) -> None:
    """`returnResult()` 를 부르고 `return` 을 빠뜨리면 반환값이 없다 — ③ 이 잡는다."""
    node_path = perceive_node(project, FORGOT_RETURN, "forgot")
    node_test = project.test_file(node_path, [{"name": "반환 없음", "args": {"input": {"html": ""}}}])

    findings = project.run(node_test)

    assert ids(findings) == ["LNT-TEST-003"]
    assert "(none)" in findings[0].message


def test_action_transparency_skips_when_no_input() -> None:
    """입력 없는 Action 은 대조할 것이 없다 — `LNT-CONTRACT-006` 이 등록 때 잡는다."""
    case = Case.model_validate({"name": "n", "args": {}})

    assert harness.check_action_transparency(case, None, object()) == []


# ── 참조·파일이 깨진 경우 ────────────────────────────────────────────────────


def test_wrong_ref_kind_on_load(project: Project) -> None:
    script_path = project.script("detect", PERCEIVE)
    entry = project.store.add("script", script_path)
    path = write_json(project.root / "x.test.json", {"node": f"${{ref.{entry.id}}}", "cases": []})

    node_test, findings = harness.load_node_test(path, project.env)

    assert node_test is None
    assert ids(findings) == ["LNT-REG-003"]


def test_wrong_ref_kind_on_run(project: Project) -> None:
    script_path = project.script("detect", PERCEIVE)
    entry = project.store.add("script", script_path)

    findings = project.run(project.test_file(f"${{ref.{entry.id}}}", []))

    assert ids(findings) == ["LNT-REG-003"]


def test_relative_node_path_on_run(project: Project) -> None:
    findings = project.run(project.test_file("nodes/x.json", []))

    assert ids(findings) == ["LNT-PATH-001"]


def test_broken_node_json_shape_is_a_finding(project: Project) -> None:
    node_path = write_json(project.root / "nodes" / "bad.json", {"info": {"name": "x"}})

    findings = project.run(project.test_file(node_path, []))

    assert findings and all(item.status == "error" for item in findings)
    assert "Node JSON" in findings[0].message


def test_unparseable_node_json_is_an_error(project: Project) -> None:
    node_path = write(project.root / "nodes" / "bad.json", "{ not json")

    with pytest.raises(LintomataError):
        project.run(project.test_file(node_path, []))


def test_node_json_top_level_must_be_an_object(project: Project) -> None:
    node_path = write_json(project.root / "nodes" / "list.json", [1, 2])

    with pytest.raises(LintomataError):
        project.run(project.test_file(node_path, []))


def test_test_file_must_be_utf8(project: Project) -> None:
    path = project.root / "x.test.json"
    path.write_bytes(b"\xff\xfe{}")

    with pytest.raises(LintomataError):
        harness.load_node_test(path, project.env)


def test_unimportable_script_is_an_error(project: Project) -> None:
    """모듈 최상위에서 터지는 것은 정적 검사가 못 잡는다 — 돌려봐야 안다."""
    node_path = perceive_node(project, UNIMPORTABLE, "unimportable")
    node_test = project.test_file(node_path, [{"name": "로드 실패", "args": {"input": {"html": ""}}}])

    findings = project.run(node_test)

    assert statuses(findings) == ["error"]
    assert ids(findings) == [""]  # 규칙 없는 오류 — 그래도 결과가 사라지지 않는다
    # 모듈을 못 찾은 것은 **부작용 문제가 아니다** — 못 찾은 이름을 짚어 안내한다.
    assert "lintomata_그런_모듈은_없다" in findings[0].message
    assert "Importing a sibling file does not work" in findings[0].message


def test_test_file_top_level_must_be_an_object(project: Project) -> None:
    path = write_json(project.root / "x.test.json", [1, 2])

    with pytest.raises(LintomataError):
        harness.load_node_test(path, project.env)


# ── R6-1. id 로 부르면 **그 id 의 등록소 노드가 정본**이다 ───────────────────


def test_id_로_부르면_등록소_노드를_돌린다(project: Project) -> None:
    """테스트의 `node` 필드로 노드를 *다시* 해석하지 않는다.

    해석해 버리면 **요청하지 않은 노드를 돌리고 통과를 보고**한다 — lint 도구에서
    가장 나쁜 종류의 거짓 리포트다.
    """
    node_path = project.node("open", "vantage", project.script("open", VANTAGE))
    node_id = project.register(node_path)
    node_test = project.test_file(
        node_path,
        [{"name": "c0", "args": {"params": {"url": "https://x"}}, "expect": {"url": "https://x"}}],
    )

    findings = project.run_by_id(node_test, node_id)

    assert statuses(findings) == ["pass"]
    assert findings[0].path.startswith(node_id)  # 요청한 것이 리포트에 남는다


def test_테스트가_다른_노드를_가리키면_STR_TEST_008(project: Project) -> None:
    """conductor 가 재현한 그 상황이다 — a 를 요청했는데 b 가 돌았다."""
    a = project.node("a", "vantage", project.script("a", VANTAGE))
    b = project.node("b", "perceive", project.script("b", PERCEIVE))
    a_id = project.register(a)
    project.register(b)

    findings = project.run_by_id(project.test_file(b, []), a_id)

    assert ids(findings) == ["LNT-TEST-008"]
    assert a_id in findings[0].message
    assert str(b) in findings[0].message


def test_ref_가_다른_노드_id_면_STR_TEST_008(project: Project) -> None:
    a = project.node("a", "vantage", project.script("a", VANTAGE))
    b = project.node("b", "perceive", project.script("b", PERCEIVE))
    a_id = project.register(a)
    b_id = project.register(b)

    findings = project.run_by_id(project.test_file(f"${{ref.{b_id}}}", []), a_id)

    assert ids(findings) == ["LNT-TEST-008"]


def test_자기_id_를_ref_로_가리키면_통과한다(project: Project) -> None:
    node_path = project.node("open", "vantage", project.script("open", VANTAGE))
    node_id = project.register(node_path)
    node_test = project.test_file(
        f"${{ref.{node_id}}}",
        [{"name": "c0", "args": {"params": {"url": "https://x"}}}],
    )

    assert statuses(project.run_by_id(node_test, node_id)) == ["pass"]


def test_원본이_지워져_있어도_id_로_돈다(project: Project) -> None:
    """*"등록 후 원본을 지워도 된다"* — `node` 를 경로로 해석하지 않으므로 무관하다.

    예전에는 여기서 `LNT-REF-002`(파일 없음)로 죽었다. R5-2 가 없애려던 바로 그
    상황이 `node` 재해석 때문에 남아 있었다.
    """
    node_path = project.node("open", "vantage", project.script("open", VANTAGE))
    node_id = project.register(node_path)
    node_test = project.test_file(
        node_path, [{"name": "c0", "args": {"params": {"url": "https://x"}}}]
    )
    node_path.unlink()

    assert statuses(project.run_by_id(node_test, node_id)) == ["pass"]


def test_경로로_부르면_node_필드가_실행_대상이다(project: Project) -> None:
    """`node test <경로>` 에는 요청한 id 가 없다 — 대조할 정본도 없다."""
    node_path = perceive_node(project)
    node_test = project.test_file(
        node_path, [{"name": "c0", "args": {"input": {"html": "<button>"}}}]
    )

    assert statuses(project.run(node_test)) == ["pass"]


# ── 규칙 슬롯 — 모든 오류 경로를 태운다 ──────────────────────────────────────


def test_every_test_rule_renders(project: Project) -> None:
    """이 모듈이 내는 규칙 전부가 슬롯 계약을 지키는가.

    슬롯을 빠뜨리면 `rules.finding()` 이 `LintomataError` 로 터진다 — 눈으로 읽지
    않고 실제로 태워서 확인한다.
    """
    fired: dict[str, Finding] = {}

    node_path = perceive_node(project)
    for cases in (
        [{"name": "①", "args": {"input": {}}}],
        [{"name": "④", "args": {"input": {"html": ""}}, "expect": {"count": 7}}],
    ):
        for item in project.run(project.test_file(node_path, cases)):
            if item.rule_id:
                fired[item.rule_id] = item

    for body, name, cases in (
        (PERCEIVE_RAISES, "raiser", [{"name": "②", "args": {"input": {"html": ""}}}]),
        (PERCEIVE_BAD_OUTPUT, "bad", [{"name": "③", "args": {"input": {"html": ""}}}]),
    ):
        for item in project.run(project.test_file(perceive_node(project, body, name), cases)):
            if item.rule_id:
                fired[item.rule_id] = item

    action = project.node("act", "action", project.script("act", ACTION_MUTATES))
    for item in project.run(project.test_file(action, [{"name": "⑤", "args": {"input": {"count": 1}}}])):
        if item.rule_id:
            fired[item.rule_id] = item

    judge = project.node("judge", "reckon", project.script("judge", RECKON))
    for item in project.run(project.test_file(judge, reckon_cases((3, 3), (5, 5)))):
        if item.rule_id:
            fired[item.rule_id] = item

    hard = project.node("hard", "reckon", project.script("hard", RECKON_HARDCODED))
    for item in project.run(project.test_file(hard, reckon_cases((3, 3), (3, 4)))):
        if item.rule_id:
            fired[item.rule_id] = item

    for item in project.run(project.test_file(project.root / "nodes" / "없다.json", [])):
        fired[item.rule_id] = item
    for item in project.run(project.test_file("${ref.nd_deadbeef}", [])):
        fired[item.rule_id] = item

    other = project.node("other", "vantage", project.script("other", VANTAGE))
    for item in project.run_by_id(project.test_file(other, []), project.register(judge)):
        fired[item.rule_id] = item

    assert set(fired) == {
        "LNT-TEST-001",
        "LNT-TEST-002",
        "LNT-TEST-003",
        "LNT-TEST-004",
        "LNT-TEST-005",
        "LNT-TEST-006",
        "LNT-TEST-007",
        "LNT-TEST-008",
        "LNT-REF-002",
        "LNT-REG-002",
    }
    for rule_id, item in fired.items():
        rule = rules.get_rule(rule_id)
        assert item.message.startswith(rule.message.split("{")[0])
        for slot in rule.slots:  # 슬롯이 리포트로 그대로 새지 않는가
            assert "{" + slot + "}" not in item.message
