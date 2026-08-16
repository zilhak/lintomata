"""도달 가능성 판정기 테스트 — Step 2-c.

**경계를 짚는다.** 도달 가능/불가의 경계는 셋이다:
① `inputs` 의존으로 막힌 것, ② `when` 상태로 막힌 것,
③ 그 둘의 **순서** 때문에 막힌 것 (상태가 입력이 끝나기 전에 지나가 버린 경우).
세 경우가 서로 다른 규칙 id 로 갈리는지를 전부 단언한다.

**모든 오류 경로에서 `Finding.rule_id` 를 확인한다** — `rules.Rule.slots` 가 요구하는
슬롯을 `fields` 로 안 넘기면 `rules.finding()` 이 `StrictlerError` 를 내면서
**원래 나와야 할 규칙 id 가 사라진다.** 그래서 이 단언이 곧 슬롯 검증이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pytest

from strictler import rules
from strictler.checks.reachability import ReachResult, check_reachability, simulate
from strictler.errors import Finding
from strictler.model import (
    Pipeline,
    PipelineInfo,
    PipelineNode,
    States,
    Transition,
    When,
)


# ── 빌더 ─────────────────────────────────────────────────────────────────────


def _node(
    node_id: str,
    *,
    inputs: Mapping[str, str] | None = None,
    when: str | None = None,
) -> PipelineNode:
    return PipelineNode(
        id=node_id,
        source=f"/pipelines/nodes/{node_id}.json",
        inputs=dict(inputs or {}),
        when=When(state=when) if when is not None else None,
    )


def _pipeline(
    nodes: Sequence[PipelineNode],
    *,
    values: Sequence[str],
    initial: str,
    transitions: Iterable[tuple[str, str]] = (),
) -> Pipeline:
    return Pipeline(
        info=PipelineInfo(name="p", description="테스트용", kind="verify"),
        states=States(values=list(values), initial=initial),
        transitions=[Transition(after=after, to=to) for after, to in transitions],
        nodes=list(nodes),
    )


def _ids(findings: list[Finding], rule_id: str) -> set[str]:
    """그 규칙으로 지목된 노드 id 들."""
    return {f.node for f in findings if f.rule_id == rule_id}


def _assert_rendered(findings: list[Finding]) -> None:
    """슬롯이 전부 채워졌고 규칙 id 가 살아 있는지 — 리포트가 원인을 짚는 최소 조건."""
    for f in findings:
        assert f.rule_id, "규칙 id 가 비었다 — 리포트가 원인을 못 짚는다"
        assert f.status == "error"
        assert "{" not in f.message, f"슬롯이 안 채워졌다: {f.message!r}"
        # guide 가 메시지 뒤에 이어붙는다 (`schema.md` 11절) — AI 자기 수정의 재료다.
        assert rules.get_rule(f.rule_id).guide[:12] in f.message


# ── 정상 파이프라인 ──────────────────────────────────────────────────────────


def test_linear_pipeline_is_fully_reachable() -> None:
    pipeline = _pipeline(
        [
            _node("open"),
            _node("capture", inputs={"page": "open"}, when="active"),
            _node("judge", inputs={"html": "capture"}, when="active"),
        ],
        values=["idle", "capturing"],
        initial="idle",
        transitions=[("open", "capturing")],
    )
    node_states = {
        "capture": {"active": "capturing"},
        "judge": {"active": "capturing"},
    }

    result = simulate(pipeline, node_states)

    assert result.reachable == {"open", "capture", "judge"}
    assert result.unreachable == set()
    assert result.reachable_states == {"idle", "capturing"}
    assert check_reachability(pipeline, node_states, "p.json") == []


def test_when_on_initial_state_needs_no_transition() -> None:
    """초기 상태는 전이 없이도 처음부터 참이다 — `-006` 이 나오면 오진단이다."""
    pipeline = _pipeline(
        [_node("only", when="ready")],
        values=["idle"],
        initial="idle",
    )
    node_states = {"only": {"ready": "idle"}}

    assert simulate(pipeline, node_states).reachable == {"only"}
    assert check_reachability(pipeline, node_states, "p.json") == []


def test_order_is_expansion_order_not_declaration_order() -> None:
    pipeline = _pipeline(
        [
            _node("third", inputs={"x": "second"}),
            _node("second", inputs={"x": "first"}),
            _node("first"),
        ],
        values=["idle"],
        initial="idle",
    )

    assert simulate(pipeline, {}).order == ["first", "second", "third"]


def test_node_gets_another_chance_after_the_state_moves() -> None:
    """한 라운드에 조건이 안 맞았다고 끝이 아니다 — 상태가 그 뒤에 옮겨간다."""
    pipeline = _pipeline(
        [
            _node("waiter", when="ready"),  # 먼저 훑히지만 처음엔 조건이 안 맞는다
            _node("mover"),
        ],
        values=["idle", "armed"],
        initial="idle",
        transitions=[("mover", "armed")],
    )
    node_states = {"waiter": {"ready": "armed"}}

    result = simulate(pipeline, node_states)

    assert result.order == ["mover", "waiter"]
    assert result.unreachable == set()
    assert check_reachability(pipeline, node_states, "p.json") == []


# ── STR-STATE-006 — 그 상태로 가는 전이가 아예 없다 ──────────────────────────


def test_when_state_no_transition_targets_it() -> None:
    pipeline = _pipeline(
        [_node("open"), _node("ghost", when="done")],
        values=["idle", "capturing", "settled"],
        initial="idle",
        transitions=[("open", "capturing")],
    )
    node_states = {"ghost": {"done": "settled"}}

    findings = check_reachability(pipeline, node_states, "p.json")

    _assert_rendered(findings)
    assert [f.rule_id for f in findings] == ["STR-STATE-006"]
    assert findings[0].node == "ghost"
    assert findings[0].path == "p.json"
    # 슬롯에는 **파이프라인 상태 이름**이 들어간다 — 전이를 추가할 자리가 그쪽이므로.
    assert "settled" in findings[0].message
    # `-006` 이 났으면 같은 노드에 `-007` 을 겹쳐 내지 않는다.
    assert _ids(findings, "STR-STATE-007") == set()


# ── STR-STATE-007 — 전이는 있는데 그 조합에 못 닿는다 ────────────────────────


def test_transition_target_state_is_never_entered() -> None:
    """`settled` 로 가는 전이는 있지만, 그 전이를 일으킬 노드가 `settled` 를 기다린다."""
    pipeline = _pipeline(
        [_node("open"), _node("deadlocked", when="done")],
        values=["idle", "ready", "settled"],
        initial="idle",
        transitions=[("open", "ready"), ("deadlocked", "settled")],
    )
    node_states = {"deadlocked": {"done": "settled"}}

    result = simulate(pipeline, node_states)
    assert result.unreachable == {"deadlocked"}
    assert "settled" not in result.reachable_states

    findings = check_reachability(pipeline, node_states, "p.json")
    _assert_rendered(findings)
    assert [f.rule_id for f in findings] == ["STR-STATE-007"]
    assert findings[0].node == "deadlocked"
    assert "deadlocked" in findings[0].message


def test_state_passes_before_inputs_finish() -> None:
    """`-007` guide 가 상정하는 바로 그 형상 —
    `when` 상태가 이 노드의 입력이 끝나기 전에만 참이다."""
    pipeline = _pipeline(
        [
            _node("open"),  # 끝나면 상태가 idle 을 떠난다
            _node("late", inputs={"page": "open"}, when="fresh"),
        ],
        values=["idle", "capturing"],
        initial="idle",
        transitions=[("open", "capturing")],
    )
    node_states = {"late": {"fresh": "idle"}}

    findings = check_reachability(pipeline, node_states, "p.json")

    _assert_rendered(findings)
    # idle 은 초기 상태이므로 `-006` 이 아니다 — 전이가 없어서가 아니라 순서 때문이다.
    assert [f.rule_id for f in findings] == ["STR-STATE-007"]
    assert findings[0].node == "late"


def test_data_block_and_state_block_are_different_rules() -> None:
    """의존으로 막힌 것과 `when` 으로 막힌 것이 섞이면 AI 가 엉뚱한 곳을 고친다."""
    pipeline = _pipeline(
        [
            _node("gate"),
            _node("dataBlocked", inputs={"x": "nowhere"}),
            _node("stateBlocked", when="done"),
        ],
        values=["idle", "active", "gone"],
        initial="idle",
        transitions=[("gate", "active")],
    )
    node_states = {"stateBlocked": {"done": "gone"}}

    findings = check_reachability(pipeline, node_states, "p.json")

    _assert_rendered(findings)
    assert _ids(findings, "STR-STATE-006") == {"stateBlocked"}
    assert _ids(findings, "STR-STATE-007") == {"dataBlocked"}


def test_self_dependency_is_unreachable() -> None:
    pipeline = _pipeline(
        [_node("loop", inputs={"x": "loop"})],
        values=["idle"],
        initial="idle",
    )

    findings = check_reachability(pipeline, {}, "p.json")

    _assert_rendered(findings)
    assert _ids(findings, "STR-STATE-007") == {"loop"}


# ── 전이 사이클 — 정상 케이스에서 멈춘다 ─────────────────────────────────────


def test_transition_cycle_terminates_and_runs_each_node_once() -> None:
    pipeline = _pipeline(
        [
            _node("toggleOn", when="lo"),
            _node("toggleOff", when="hi"),
            _node("after", inputs={"x": "toggleOff"}, when="lo"),
        ],
        values=["low", "high"],
        initial="low",
        transitions=[("toggleOn", "high"), ("toggleOff", "low")],
    )
    node_states = {
        "toggleOn": {"lo": "low"},
        "toggleOff": {"hi": "high"},
        "after": {"lo": "low"},
    }

    result = simulate(pipeline, node_states)

    assert result.unreachable == set()
    # 실행된 노드를 다시 집어들면 여기서 걸린다 (안 걸리면 무한루프였다).
    assert result.order == ["toggleOn", "toggleOff", "after"]
    assert len(result.order) == len(set(result.order))
    assert result.reachable_states == {"low", "high"}


# ── 다른 규칙이 이미 보고한 것은 겹쳐 내지 않는다 ────────────────────────────


def test_unmapped_when_defers_to_state_mapping_rules() -> None:
    """매핑 누락은 `STR-STATE-002`/`-004` 의 몫 — 여기서 도달 불가로 겹쳐 내지 않는다."""
    pipeline = _pipeline(
        [_node("orphan", when="active")],
        values=["idle"],
        initial="idle",
    )

    assert simulate(pipeline, {}).reachable == {"orphan"}
    assert check_reachability(pipeline, {}, "p.json") == []


def test_mapped_state_outside_values_defers_to_state_003() -> None:
    pipeline = _pipeline(
        [_node("orphan", when="active")],
        values=["idle"],
        initial="idle",
    )
    node_states = {"orphan": {"active": "typo"}}

    assert simulate(pipeline, node_states).reachable == {"orphan"}
    assert check_reachability(pipeline, node_states, "p.json") == []


# ── 규칙 계약 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rule_id", ["STR-STATE-006", "STR-STATE-007"])
def test_rule_slots_are_what_this_module_fills(rule_id: str) -> None:
    """이 모듈이 채우는 슬롯이 규칙이 요구하는 슬롯과 정확히 같은가.

    규칙 문구가 바뀌어 슬롯이 늘면 `rules.finding()` 이 `StrictlerError` 를 내면서
    **규칙 id 가 사라진다.** 통합 전에 여기서 걸린다.
    """
    rule = rules.get_rule(rule_id)
    assert rule.slots == ("name",)
    assert "pipeline-register" in rule.when


def test_result_defaults_are_empty() -> None:
    result = ReachResult()
    assert result.reachable == set()
    assert result.unreachable == set()
    assert result.reachable_states == set()
    assert result.order == []
