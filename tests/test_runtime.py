"""Step 3-a — 값 검증 실행 엔진 (`engine/runtime.py`).

**대역을 쓰지 않는다.** 실제 스크립트 파일·노드 JSON·파이프라인 JSON·등록소로 돌린다 —
Step 1 통합에서 남의 모듈을 stub 으로 끼고 돌린 탓에 슬롯 계약 위반 11건이 merge
시점까지 안 잡혔기 때문이다. 여기서 진짜 구현을 그대로 쓰면 규칙 슬롯 누락이 곧바로
`StrictlerError` 로 터진다.

짚는 것:
  - not run 전파 **두 경로 각각**과 `NotRunCause.reason` 이 올바로 갈리는가
  - 한 노드가 실패해도 다른 노드는 전부 도는가 (실패는 최대한 수집한다)
  - 스크립트 예외 → `error`(위반 아님), 타입 계약 위반 → `error`
  - 통과형 스크립트(`return returnResult(args.input)`)가 조건 분기로 동작하는가
  - `started_at_ms` 를 주입하므로 결과가 결정적인가
  - 실행 순서 == `checks.reachability.simulate().order` (계약 R3-7)
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from strictler import rules
from strictler.checks import reachability
from strictler.engine import runtime
from strictler.errors import Finding
from strictler.model import Pipeline, Spec
from strictler.report import render_json
from strictler.store.entries import Store

STARTED_AT = 1_700_000_000_000


# ── fixture 조립 ─────────────────────────────────────────────────────────────


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    return path


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class Project:
    """스크립트 → 노드 → 파이프라인 → Spec 네 층을 실제 파일로 깐다."""

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

    def pipeline(self, name: str, **body: Any) -> Path:
        raw: dict[str, Any] = {
            "info": {"name": name, "description": f"{name} 파이프라인", "kind": "verify"},
            "states": {"values": ["idle"], "initial": "idle"},
            "nodes": [],
        }
        raw.update(body)
        return write_json(self.root / "pipelines" / f"{name}.json", raw)

    def spec(self, plan: list[dict[str, Any]], tool: dict[str, Any] | None = None) -> Spec:
        raw: dict[str, Any] = {
            "info": {"description": "테스트 Spec"},
            "plan": plan,
        }
        if tool is not None:
            raw["tool"] = tool
        return Spec.model_validate(raw)

    def load_pipeline(self, path: Path) -> Pipeline:
        return Pipeline.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def run(self, path: Path, config: dict[str, Any] | None = None, **kw: Any) -> Any:
        return runtime.run_pipeline(
            self.load_pipeline(path),
            config or {},
            store=self.store,
            env=self.env,
            started_at_ms=STARTED_AT,
            path="p",
            **kw,
        )


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    return Project(tmp_path)


# ── 스크립트 본문들 ──────────────────────────────────────────────────────────

VANTAGE = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Params:
        url: str

    @dataclass
    class Args:
        params: Params

    def runNode(args: Args) -> Scene:
        return returnResult(Scene(url=args.params.url))
"""

PERCEIVE = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=len(args.input.url)))
"""

RECKON = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Expect:
        expected: int

    @dataclass
    class Verdict:
        passed: bool
        rule: str
        message: str

    @dataclass
    class Args:
        input: Percept
        params: Expect

    def runNode(args: Args) -> Verdict:
        ok = args.input.count == args.params.expected
        return returnResult(Verdict(
            passed=ok,
            rule="expectedCount",
            message=f"{args.params.expected}개 기대, {args.input.count}개 관측",
        ))
"""

PASSTHROUGH = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args):
        return returnResult(args.input)
"""

PASSTHROUGH_PERCEPT = """
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

RAISES = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args) -> Percept:
        if args.input.url:
            raise RuntimeError("여기서 터진다")
        return returnResult(Percept(count=0))
"""

WRONG_OUTPUT = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count="셋이요"))
"""

WAITING = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Traffic:
        size: int

    @dataclass
    class St:
        stop: bool

    @dataclass
    class Args:
        input: Scene
        state: St

    def runNode(args: Args) -> Traffic:
        return returnResult(Traffic(size=1 if args.state.stop else 0))
"""


BARE_RECKON = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Expect:
        expected: int

    @dataclass
    class Verdict:
        note: str

    @dataclass
    class Args:
        input: Percept
        params: Expect

    def runNode(args: Args) -> Verdict:
        return returnResult(Verdict(note="판정을 안 담았다"))
"""

QUIET_RECKON = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Expect:
        expected: int

    @dataclass
    class Verdict:
        passed: bool

    @dataclass
    class Args:
        input: Percept
        params: Expect

    def runNode(args: Args) -> Verdict:
        return returnResult(Verdict(passed=args.input.count == args.params.expected))
"""

TOOL_USER = """
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

    def launch(binary):
        return binary

    def runNode(args: Args) -> Scene:
        launch("/opt/playwright/playwright")
        return returnResult(Scene(url=args.params.url))
"""


def basic(project: Project) -> Path:
    """`page → buttons → check` 세 노드짜리 값 검증 파이프라인."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    project.node("check", "reckon", project.script("check", RECKON))
    return project.pipeline(
        "basic",
        config={
            "url": {"type": "str", "required": True},
            "expected": {"type": "int", "required": True},
        },
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "check",
                "source": str(project.root / "nodes" / "check.json"),
                "inputs": {"percept": "buttons"},
                "params": {"expected": "${config.expected}"},
            },
        ],
    )


def statuses(findings: list[Finding]) -> dict[str, str]:
    return {finding.node: finding.status for finding in findings if finding.node}


def errors(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.status == "error"]


# ── 통과 경로 ────────────────────────────────────────────────────────────────


def test_모든_노드가_통과하면_pass_만_나온다(project: Project) -> None:
    path = basic(project)
    result = project.run(path, {"url": "https://x", "expected": len("https://x")})

    assert errors(result.findings) == []
    assert statuses(result.findings) == {"page": "pass", "buttons": "pass", "check": "pass"}
    assert set(result.outcomes) == {"page", "buttons", "check"}


def test_reckon_이_기댓값과_다르면_violation_이다(project: Project) -> None:
    path = basic(project)
    result = project.run(path, {"url": "https://x", "expected": 3})

    violations = [f for f in result.findings if f.status == "violation"]
    assert [f.node for f in violations] == ["check"]
    # `rule` 은 Reckon 이 낸 이름이 그대로 실린다 (`schema.md` 11절 예시).
    assert violations[0].rule_id == "expectedCount"
    assert "3개 기대" in violations[0].message
    # 위반은 정상 결과다 — 오류가 아니고, 뒷단이 not run 이 되지도 않는다.
    assert errors(result.findings) == []
    assert result.outcomes["check"].status == "violation"


def test_같은_입력이면_결과가_결정적이다(project: Project) -> None:
    path = basic(project)
    config = {"url": "https://x", "expected": 3}
    first = project.run(path, dict(config))
    second = project.run(path, dict(config))

    assert [(f.node, f.status, f.message) for f in first.findings] == [
        (f.node, f.status, f.message) for f in second.findings
    ]


def test_통과형_스크립트가_값을_그대로_흘려보낸다(project: Project) -> None:
    """조건 분기는 엔진 문법이 아니라 **스크립트가 `input` 을 반환**하는 것이다."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("relay", "action", project.script("relay", PASSTHROUGH))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    path = project.pipeline(
        "relay",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "relay",
                "source": str(project.root / "nodes" / "relay.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"scene": "relay"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert errors(result.findings) == []
    assert result.outcomes["relay"].value.url == "abcd"
    assert result.outcomes["buttons"].value.count == 4


# ── 오류 ─────────────────────────────────────────────────────────────────────


def test_스크립트_예외는_위반이_아니라_오류다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    path = project.pipeline(
        "boom",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert result.outcomes["boom"].status == "error"
    assert [f.status for f in result.findings if f.node == "boom"] == ["error"]
    assert "여기서 터진다" in "".join(f.message for f in result.findings if f.node == "boom")
    assert not [f for f in result.findings if f.status == "violation"]


def test_출력이_선언된_타입과_다르면_오류다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("bad", "perceive", project.script("bad", WRONG_OUTPUT))
    path = project.pipeline(
        "bad",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "bad",
                "source": str(project.root / "nodes" / "bad.json"),
                "inputs": {"scene": "page"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert result.outcomes["bad"].status == "error"
    assert not [f for f in result.findings if f.status == "violation"]


def test_한_노드가_실패해도_독립한_노드는_전부_돈다(project: Project) -> None:
    """실패는 최대한 수집한다 — 실패한 가지 밖은 멈추지 않는다."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    path = project.pipeline(
        "mixed",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"scene": "page"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert result.outcomes["boom"].status == "error"
    assert result.outcomes["buttons"].status == "pass"
    assert result.outcomes["page"].status == "pass"


# ── not run 전파 ─────────────────────────────────────────────────────────────


def test_데이터_의존_경로로_not_run_이_전파된다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    project.node("check", "reckon", project.script("check", RECKON))
    path = project.pipeline(
        "chain",
        config={
            "url": {"type": "str", "required": True},
            "expected": {"type": "int", "required": True},
        },
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "check",
                "source": str(project.root / "nodes" / "check.json"),
                "inputs": {"percept": "boom"},
                "params": {"expected": "${config.expected}"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd", "expected": 4})

    not_run = [f for f in result.findings if f.status == "not_run"]
    assert [f.node for f in not_run] == ["check"]
    assert not_run[0].cause is not None
    assert not_run[0].cause.node == "boom"
    assert not_run[0].cause.reason == "data_dependency"
    # not run 항목에는 규칙도 메시지도 없다 (`schema.md` 11절 예시).
    assert not_run[0].rule_id == ""
    assert not_run[0].message == ""


def test_상태_의존_경로로_not_run_이_전파된다(project: Project) -> None:
    """`transitions.after` 가 실패하면 그 전이가 안 일어나고, 그 상태를 기다리던
    노드는 영원히 조건을 만족하지 못한다 — **두 번째 전파 경로**."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    project.node("wait", "sense", project.script("wait", WAITING))
    path = project.pipeline(
        "stateful",
        config={"url": {"type": "str", "required": True}},
        states={"values": ["idle", "settled"], "initial": "idle"},
        transitions=[{"after": "boom", "to": "settled"}],
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "wait",
                "source": str(project.root / "nodes" / "wait.json"),
                "inputs": {"scene": "page"},
                "states": {"stop": "settled"},
                "when": {"state": "stop"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    not_run = [f for f in result.findings if f.status == "not_run"]
    assert [f.node for f in not_run] == ["wait"]
    assert not_run[0].cause is not None
    assert not_run[0].cause.node == "boom"
    # ★ 데이터로도 막혔지만(같은 `page` 는 성공했다) 원인은 상태 쪽이다.
    assert not_run[0].cause.reason == "state_unreachable"


def test_두_전파_경로가_한_실행에서_함께_갈린다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    project.node("check", "reckon", project.script("check", RECKON))
    project.node("wait", "sense", project.script("wait", WAITING))
    path = project.pipeline(
        "both",
        config={
            "url": {"type": "str", "required": True},
            "expected": {"type": "int", "required": True},
        },
        states={"values": ["idle", "settled"], "initial": "idle"},
        transitions=[{"after": "boom", "to": "settled"}],
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "check",
                "source": str(project.root / "nodes" / "check.json"),
                "inputs": {"percept": "boom"},
                "params": {"expected": "${config.expected}"},
            },
            {
                "id": "wait",
                "source": str(project.root / "nodes" / "wait.json"),
                "inputs": {"scene": "page"},
                "states": {"stop": "settled"},
                "when": {"state": "stop"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd", "expected": 4})

    reasons = {
        f.node: f.cause.reason
        for f in result.findings
        if f.status == "not_run" and f.cause is not None
    }
    assert reasons == {"check": "data_dependency", "wait": "state_unreachable"}


def test_not_run_은_전이적으로_전파된다(project: Project) -> None:
    """not run 이 된 노드가 밀어야 할 전이도 일어나지 않는다."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("boom", "perceive", project.script("boom", RAISES))
    project.node("relay", "action", project.script("relay", PASSTHROUGH_PERCEPT))
    project.node("wait", "sense", project.script("wait", WAITING))
    path = project.pipeline(
        "transitive",
        config={"url": {"type": "str", "required": True}},
        states={"values": ["idle", "settled"], "initial": "idle"},
        transitions=[{"after": "relay", "to": "settled"}],
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "boom",
                "source": str(project.root / "nodes" / "boom.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "relay",
                "source": str(project.root / "nodes" / "relay.json"),
                "inputs": {"scene": "boom"},
            },
            {
                "id": "wait",
                "source": str(project.root / "nodes" / "wait.json"),
                "inputs": {"scene": "page"},
                "states": {"stop": "settled"},
                "when": {"state": "stop"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    causes = {
        f.node: (f.cause.node, f.cause.reason)
        for f in result.findings
        if f.status == "not_run" and f.cause is not None
    }
    assert causes["relay"] == ("boom", "data_dependency")
    assert causes["wait"] == ("relay", "state_unreachable")


def test_propagate_not_run_은_아무_일도_없으면_아무것도_안_낸다(project: Project) -> None:
    path = basic(project)
    result = project.run(path, {"url": "https://x", "expected": 9})
    pipeline = project.load_pipeline(path)

    assert runtime.propagate_not_run(pipeline, result, "p") == []


# ── 실행 순서 계약 (R3-7) ────────────────────────────────────────────────────


def test_실행_순서는_simulate_order_와_같다(project: Project) -> None:
    """동시에 실행 가능한 노드는 파이프라인 `nodes` 선언 순서로 돈다 —
    `reachability.simulate().order` 가 참조 구현이다 (MODULES.md R3-7)."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("a", "perceive", project.script("a", PERCEIVE))
    project.node("b", "perceive", project.script("b", PERCEIVE))
    project.node("wait", "sense", project.script("wait", WAITING))
    path = project.pipeline(
        "ordered",
        config={"url": {"type": "str", "required": True}},
        states={"values": ["idle", "settled"], "initial": "idle"},
        transitions=[{"after": "a", "to": "settled"}],
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "wait",
                "source": str(project.root / "nodes" / "wait.json"),
                "inputs": {"scene": "page"},
                "states": {"stop": "settled"},
                "when": {"state": "stop"},
            },
            {"id": "a", "source": str(project.root / "nodes" / "a.json"),
             "inputs": {"scene": "page"}},
            {"id": "b", "source": str(project.root / "nodes" / "b.json"),
             "inputs": {"scene": "page"}},
        ],
    )
    pipeline = project.load_pipeline(path)
    expected = reachability.simulate(
        pipeline, {pn.id: dict(pn.states) for pn in pipeline.nodes}
    ).order

    result = project.run(path, {"url": "abcd"})
    ran = [f.node for f in result.findings if f.status in ("pass", "violation")]

    assert errors(result.findings) == []
    assert ran == expected == ["page", "a", "wait", "b"]


def test_topo_order_는_선언_순서를_tie_break_로_쓴다() -> None:
    dag = {"page": [], "b": ["page"], "a": ["page"], "check": ["a", "b"]}
    assert runtime.topo_order(dag) == ["page", "b", "a", "check"]


def test_topo_order_는_순환에서_멈춘다() -> None:
    assert runtime.topo_order({"a": ["b"], "b": ["a"]}) == []


# ── Spec 단위 ────────────────────────────────────────────────────────────────


def test_run_spec_이_path_문자열을_만든다(project: Project) -> None:
    path = basic(project)
    spec = project.spec(
        [
            {
                "source": str(path),
                "description": "기본",
                "config": {"url": "https://x", "expected": 9},
            }
        ]
    )
    report = runtime.run_spec(
        spec,
        store=project.store,
        env=project.env,
        started_at_ms=STARTED_AT,
        spec_name="login.json",
    )

    assert report.summary.passed == 3
    assert {f.path for f in report.results} == {"login.json > plan[0] > basic"}


def test_한_plan_항목이_실패해도_다른_항목은_전부_돈다(project: Project) -> None:
    path = basic(project)
    spec = project.spec(
        [
            {
                "source": str(project.root / "pipelines" / "없다.json"),
                "description": "깨진 항목",
            },
            {
                "source": str(path),
                "description": "멀쩡한 항목",
                "config": {"url": "https://x", "expected": 9},
            },
        ]
    )
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT, spec_name="s.json"
    )

    assert report.summary.error == 1
    assert report.summary.passed == 3
    assert any(f.path == "s.json > plan[0]" for f in report.results)


def test_config_required_누락은_STR_CONFIG_001_이다(project: Project) -> None:
    path = basic(project)
    spec = project.spec([{"source": str(path), "description": "값 없음", "config": {}}])
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT
    )

    assert {f.rule_id for f in report.results} == {"STR-CONFIG-001"}
    # config 가 안 풀리면 그 지점에서 진행하지 않는다 — 노드는 하나도 안 돈다.
    assert report.summary.passed == 0


def test_비교_파이프라인인데_report_가_없으면_STR_CMP_001(project: Project) -> None:
    path = project.pipeline(
        "cmp",
        info={"name": "cmp", "description": "비교", "kind": "compare"},
        targets=["old", "new"],
        nodes=[],
    )
    spec = project.spec([{"source": str(path), "description": "리포트 없음"}])
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT
    )

    assert [f.rule_id for f in report.results] == ["STR-CMP-001"]


def test_리포트_JSON_이_11절_예시와_키_구성이_같다(project: Project) -> None:
    path = basic(project)
    spec = project.spec(
        [
            {
                "source": str(path),
                "description": "위반",
                "config": {"url": "https://x", "expected": 3},
            }
        ]
    )
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT, spec_name="login.json"
    )
    data = json.loads(render_json(report))

    assert data["summary"] == {"pass": 2, "violation": 1, "not_run": 0, "error": 0}
    violation = next(item for item in data["results"] if item["status"] == "violation")
    assert set(violation) == {"path", "node", "status", "rule", "message"}
    passed = next(item for item in data["results"] if item["status"] == "pass")
    assert set(passed) == {"path", "node", "status"}


# ── 등록소 무결성 ────────────────────────────────────────────────────────────


def test_등록소_파일이_수정되면_STR_REG_001(project: Project) -> None:
    script = project.script("page", VANTAGE)
    node_path = project.node("page", "vantage", script)
    entry = project.store.add("node", node_path)
    # 정적 검사 루트를 피해 등록소 파일을 직접 고친 상황 그 자체.
    project.store.path_of(entry.id).write_text("{}", encoding="utf-8")

    path = project.pipeline(
        "reg",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": "${ref." + entry.id + "}",
                "params": {"url": "${config.url}"},
            }
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert "STR-REG-001" in {f.rule_id for f in result.findings}


def test_등록된_스크립트가_수정되면_STR_REG_001(project: Project) -> None:
    """노드의 `script` 자리에 있는 `${ref.sc_...}` 도 같은 대조를 받는다."""
    entry = project.store.add("script", project.script("page", VANTAGE))
    node_path = project.node("page", "vantage", "${ref." + entry.id + "}")
    project.store.path_of(entry.id).write_text(
        dedent(VANTAGE).lstrip("\n") + "\n# 몰래 고쳤다\n", encoding="utf-8"
    )

    path = project.pipeline(
        "regscript",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {"id": "page", "source": str(node_path), "params": {"url": "${config.url}"}}
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert "STR-REG-001" in {f.rule_id for f in result.findings}


def test_등록된_파이프라인은_ref_로_실행된다(project: Project) -> None:
    entry = project.store.add("pipeline", basic(project))
    spec = project.spec(
        [
            {
                "source": "${ref." + entry.id + "}",
                "description": "등록된 파이프라인",
                "config": {"url": "https://x", "expected": 9},
            }
        ]
    )
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT
    )

    assert report.summary.passed == 3
    assert report.summary.error == 0


def test_참조한_id_가_삭제되면_STR_REG_002(project: Project) -> None:
    script = project.script("page", VANTAGE)
    node_path = project.node("page", "vantage", script)
    entry = project.store.add("node", node_path)
    project.store.remove(entry.id)

    path = project.pipeline(
        "gone",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": "${ref." + entry.id + "}",
                "params": {"url": "${config.url}"},
            }
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert "STR-REG-002" in {f.rule_id for f in result.findings}


def test_tool_미선언_경로는_STR_TOOL_002_다(project: Project) -> None:
    """`STR-TOOL-001`/`-002` 는 **실행 시점** 규칙이다 — Spec 이 `tool` 을 갖기 때문."""
    project.node("page", "vantage", project.script("page", TOOL_USER))
    path = project.pipeline(
        "tooled",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            }
        ],
    )
    spec = project.spec(
        [{"source": str(path), "description": "도구", "config": {"url": "abcd"}}],
        tool={"playwright": {"path": "/opt/other/playwright", "functions": ["launch"]}},
    )
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT
    )

    assert "STR-TOOL-002" in {f.rule_id for f in report.results}


def test_선언된_경로면_통과한다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", TOOL_USER))
    path = project.pipeline(
        "tooled",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            }
        ],
    )
    spec = project.spec(
        [{"source": str(path), "description": "도구", "config": {"url": "abcd"}}],
        tool={"playwright": {"path": "/opt/playwright/playwright", "functions": ["launch"]}},
    )
    report = runtime.run_spec(
        spec, store=project.store, env=project.env, started_at_ms=STARTED_AT
    )

    assert [f.status for f in report.results] == ["pass"]


def test_같은_앞단을_두_이름으로_받아도_값은_하나다(project: Project) -> None:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    path = project.pipeline(
        "twice",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"scene": "page", "again": "page"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert errors(result.findings) == []
    assert result.outcomes["buttons"].value.count == 4


def test_서로_다른_앞단을_둘_받으면_오류다(project: Project) -> None:
    """`Args.input` 은 필드 하나다 — 조용히 하나를 고르면 거짓 리포트가 된다."""
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("relay", "action", project.script("relay", PASSTHROUGH))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    path = project.pipeline(
        "two-inputs",
        config={"url": {"type": "str", "required": True}},
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "relay",
                "source": str(project.root / "nodes" / "relay.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"a": "page", "b": "relay"},
            },
        ],
    )
    result = project.run(path, {"url": "abcd"})

    assert result.outcomes["buttons"].status == "error"
    assert "둘 이상" in "".join(f.message for f in result.findings if f.node == "buttons")


# ── Reckon 의 판정 읽기 ──────────────────────────────────────────────────────


def reckon_pipeline(project: Project, body: str) -> Path:
    project.node("page", "vantage", project.script("page", VANTAGE))
    project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    project.node("check", "reckon", project.script("check", body))
    return project.pipeline(
        "verdict",
        config={
            "url": {"type": "str", "required": True},
            "expected": {"type": "int", "required": True},
        },
        nodes=[
            {
                "id": "page",
                "source": str(project.root / "nodes" / "page.json"),
                "params": {"url": "${config.url}"},
            },
            {
                "id": "buttons",
                "source": str(project.root / "nodes" / "buttons.json"),
                "inputs": {"scene": "page"},
            },
            {
                "id": "check",
                "source": str(project.root / "nodes" / "check.json"),
                "inputs": {"percept": "buttons"},
                "params": {"expected": "${config.expected}"},
            },
        ],
    )


def test_판정_필드가_없는_Reckon_은_오류다(project: Project) -> None:
    """리포트가 조용히 전부 통과로 보이면 그건 거짓 리포트다."""
    path = reckon_pipeline(project, BARE_RECKON)
    result = project.run(path, {"url": "abcd", "expected": 4})

    assert result.outcomes["check"].status == "error"
    message = "".join(f.message for f in result.findings if f.node == "check")
    assert runtime.VERDICT_PASSED in message


def test_설명이_없는_위반에도_문구가_붙는다(project: Project) -> None:
    """사람이 읽는 것은 AI 요약이다 — 요약할 것이 없으면 규칙이 전달되지 않는다."""
    path = reckon_pipeline(project, QUIET_RECKON)
    result = project.run(path, {"url": "abcd", "expected": 99})

    violation = next(f for f in result.findings if f.status == "violation")
    assert violation.rule_id == ""
    assert violation.message
    assert "기획과 다릅니다" in violation.message


def test_판정이_통과면_pass_다(project: Project) -> None:
    path = reckon_pipeline(project, QUIET_RECKON)
    result = project.run(path, {"url": "abcd", "expected": 4})

    assert statuses(result.findings)["check"] == "pass"


# ── 규칙 슬롯 — 이 모듈이 내는 모든 규칙을 실제로 렌더해 본다 ────────────────


def test_이_모듈이_내는_모든_규칙의_슬롯이_채워진다() -> None:
    """슬롯을 빠뜨리면 `StrictlerError` 가 나면서 **원래 규칙 id 가 사라진다.**
    눈으로 읽지 않고 돌려서 확인한다."""
    made = {
        "STR-CMP-001": rules.finding("STR-CMP-001", path="p"),
        "STR-REG-001": rules.finding("STR-REG-001", path="p", fields={"id": "nd_1"}),
        "STR-REG-002": rules.finding("STR-REG-002", path="p", fields={"id": "nd_1"}),
    }
    for rule_id, finding in made.items():
        assert finding.rule_id == rule_id
        assert "{" not in finding.message
