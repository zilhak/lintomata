"""도달 가능성 판정기 테스트 — Step 2-c.

**경계를 짚는다.** 도달 가능/불가의 경계는 셋이다:
① `inputs` 의존으로 막힌 것, ② `when` 상태로 막힌 것,
③ 그 둘의 **순서** 때문에 막힌 것 (상태가 입력이 끝나기 전에 지나가 버린 경우).
세 경우가 서로 다른 규칙 id 로 갈리는지를 전부 단언한다.

**모든 오류 경로에서 `Finding.rule_id` 를 확인한다** — `rules.Rule.slots` 가 요구하는
슬롯을 `fields` 로 안 넘기면 `rules.finding()` 이 `LintomataError` 를 내면서
**원래 나와야 할 규칙 id 가 사라진다.** 그래서 이 단언이 곧 슬롯 검증이다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

import pytest

from lintomata import rules
from lintomata.checks.reachability import ReachResult, check_reachability, simulate
from lintomata.errors import Finding
from lintomata.model import (
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
    transitions: Iterable[tuple[str, str] | tuple[str, str, int]] = (),
) -> Pipeline:
    """전이는 `(after, to)` 또는 `(after, to, delay)` 로 준다."""
    return Pipeline(
        info=PipelineInfo(name="p", description="테스트용", kind="verify"),
        states=States(values=list(values), initial=initial),
        transitions=[
            Transition(after=t[0], to=t[1], delay=t[2] if len(t) == 3 else None)
            for t in transitions
        ],
        nodes=list(nodes),
    )


def _ids(findings: list[Finding], rule_id: str) -> set[str]:
    """그 규칙으로 지목된 노드 id 들."""
    return {f.node for f in findings if f.rule_id == rule_id}


_SLOT_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _guide_fragment(rule_id: str) -> str:
    """guide 에서 슬롯이 없는 가장 긴 조각 — 렌더된 메시지에 그대로 남아 있어야 한다."""
    return max(_SLOT_RE.split(rules.get_rule(rule_id).guide), key=len)


def _assert_rendered(findings: list[Finding]) -> None:
    """슬롯이 전부 채워졌고 규칙 id 가 살아 있는지 — 리포트가 원인을 짚는 최소 조건."""
    for f in findings:
        assert f.rule_id, "규칙 id 가 비었다 — 리포트가 원인을 못 짚는다"
        assert f.status == "error"
        assert "{" not in f.message, f"슬롯이 안 채워졌다: {f.message!r}"
        # guide 가 메시지 뒤에 이어붙는다 (`schema.md` 11절) — AI 자기 수정의 재료다.
        assert _guide_fragment(f.rule_id) in f.message


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


# ── LNT-STATE-006 — 그 상태로 가는 전이가 아예 없다 ──────────────────────────


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
    assert [f.rule_id for f in findings] == ["LNT-STATE-006"]
    assert findings[0].node == "ghost"
    assert findings[0].path == "p.json"
    # 두 층이 **둘 다** 보여야 한다 (R3-9) — `when` 에 적힌 것은 노드 어휘 `done`,
    # 전이를 추가할 자리는 파이프라인 어휘 `settled` 다. 하나만 보이면
    # JSON 의 어느 자리를 고쳐야 하는지가 안 드러난다.
    assert "settled" in findings[0].message
    assert "done" in findings[0].message
    # `-006` 이 났으면 같은 노드에 `-007` 을 겹쳐 내지 않는다.
    assert _ids(findings, "LNT-STATE-007") == set()


# ── LNT-STATE-007 — 전이는 있는데 그 조합에 못 닿는다 ────────────────────────


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
    assert [f.rule_id for f in findings] == ["LNT-STATE-007"]
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
    assert [f.rule_id for f in findings] == ["LNT-STATE-007"]
    assert findings[0].node == "late"


def test_data_blocked_node_gets_no_finding_but_stays_unreachable() -> None:
    """데이터로 막힌 것에 `-007` 을 내면 AI 가 엉뚱한 곳을 고친다 (R3-8).

    `-007` 의 guide 는 `when` 을 확인하라고 말하는데 `dataBlocked` 에는 `when` 이
    아예 없다. 없는 노드 id 를 가리킨 것은 `LNT-REF-003` 이 이미 보고한다 —
    **정보는 `unreachable` 에 남기고 Finding 만 안 낸다.**
    """
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

    result = simulate(pipeline, node_states)
    assert result.unreachable == {"dataBlocked", "stateBlocked"}

    findings = check_reachability(pipeline, node_states, "p.json")

    _assert_rendered(findings)
    assert _ids(findings, "LNT-STATE-006") == {"stateBlocked"}
    assert _ids(findings, "LNT-STATE-007") == set()


def test_node_blocked_by_an_unreachable_dependency_defers_to_that_dependency() -> None:
    """의존 대상이 도달 불가면 **그 대상이** `-007` 로 보고된다 — 뒷단은 겹쳐 내지 않는다."""
    pipeline = _pipeline(
        [
            _node("open"),
            _node("late", inputs={"page": "open"}, when="fresh"),
            _node("tail", inputs={"x": "late"}),
        ],
        values=["idle", "capturing"],
        initial="idle",
        transitions=[("open", "capturing")],
    )
    node_states = {"late": {"fresh": "idle"}}

    result = simulate(pipeline, node_states)
    assert result.unreachable == {"late", "tail"}

    findings = check_reachability(pipeline, node_states, "p.json")

    _assert_rendered(findings)
    assert _ids(findings, "LNT-STATE-007") == {"late"}


def test_self_dependency_defers_to_the_cycle_rule() -> None:
    """자기 자신을 입력으로 받는 것은 순환이다 — `LNT-GRAPH-001` 의 몫이다 (R3-8)."""
    pipeline = _pipeline(
        [_node("loop", inputs={"x": "loop"})],
        values=["idle"],
        initial="idle",
    )

    assert simulate(pipeline, {}).unreachable == {"loop"}
    assert check_reachability(pipeline, {}, "p.json") == []


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


# ── 같은 `after` 의 전이 여럿 = 구간 (R3-6) ─────────────────────────────────


def _interval_pipeline(reversed_declaration: bool) -> Pipeline:
    """`{after:load, to:loading}` + `{after:load, to:done, delay:5000}` — `delay` 구간.

    `schema.md` 8절이 `delay` 로 표현하려던 형상 그 자체다. 문법상 정상이므로
    금지할 것이 아니라 전개할 것이다.
    """
    transitions: list[tuple[str, str] | tuple[str, str, int]] = [
        ("load", "loading"),
        ("load", "done", 5000),
    ]
    if reversed_declaration:
        transitions.reverse()
    return _pipeline(
        [
            _node("load"),
            _node("spinner", when="mid"),
            _node("result", when="end"),
        ],
        values=["idle", "loading", "done"],
        initial="idle",
        transitions=transitions,
    )


_INTERVAL_STATES = {"spinner": {"mid": "loading"}, "result": {"end": "done"}}


@pytest.mark.parametrize("reversed_declaration", [False, True])
def test_intermediate_state_of_an_interval_is_passed_through(
    reversed_declaration: bool,
) -> None:
    """중간 상태 `loading` 을 기다리는 노드가 그 자리에서 실행 가능해야 한다.

    마지막 전이만 반영하면 `spinner` 가 통째로 사라지고, `reachable_states` 는
    `loading` 을 담았다고 말해 **한 결과 안에서 두 필드가 반대를 말한다.**
    그리고 **전이 선언 순서를 뒤집으면 등록 성패가 뒤집힌다** — 그래서 두 순서를 다 돌린다.
    """
    pipeline = _interval_pipeline(reversed_declaration)

    result = simulate(pipeline, _INTERVAL_STATES)

    assert result.reachable == {"load", "spinner", "result"}
    assert result.unreachable == set()
    assert result.reachable_states == {"idle", "loading", "done"}
    # `delay` 오름차순 — `loading`(0) 을 지나 `done`(5000) 으로 간다.
    assert result.order == ["load", "spinner", "result"]
    assert check_reachability(pipeline, _INTERVAL_STATES, "p.json") == []


def test_interval_expansion_is_independent_of_declaration_order() -> None:
    """선언 순서를 뒤집어도 결과가 같다 — 순서는 `delay` 가 정한다."""
    forward = simulate(_interval_pipeline(False), _INTERVAL_STATES)
    backward = simulate(_interval_pipeline(True), _INTERVAL_STATES)

    assert forward.order == backward.order
    assert forward.reachable == backward.reachable
    assert forward.reachable_states == backward.reachable_states


def test_same_delay_keeps_declaration_order() -> None:
    """`delay` 가 같으면 선언 순서가 tie-break 다."""
    pipeline = _pipeline(
        [_node("go"), _node("second", when="b"), _node("first", when="a")],
        values=["idle", "a", "b"],
        initial="idle",
        transitions=[("go", "a", 100), ("go", "b", 100)],
    )
    node_states = {"first": {"a": "a"}, "second": {"b": "b"}}

    assert simulate(pipeline, node_states).order == ["go", "first", "second"]


def test_unresolved_delay_reference_is_treated_as_zero() -> None:
    """`delay` 가 아직 안 풀린 `${config.X}` 여도 구간 전개가 깨지지 않는다."""
    pipeline = Pipeline(
        info=PipelineInfo(name="p", description="테스트용", kind="verify"),
        states=States(values=["idle", "m", "z"], initial="idle"),
        transitions=[
            Transition(after="go", to="m", delay="${config.wait}"),
            Transition(after="go", to="z", delay=3000),
        ],
        nodes=[_node("go"), _node("mid", when="m")],
    )
    node_states = {"mid": {"m": "m"}}

    result = simulate(pipeline, node_states)

    assert result.reachable == {"go", "mid"}
    assert result.reachable_states == {"idle", "m", "z"}


# ── 다른 규칙이 이미 보고한 것은 겹쳐 내지 않는다 ────────────────────────────


def test_unmapped_when_defers_to_state_mapping_rules() -> None:
    """매핑 누락은 `LNT-STATE-002`/`-004` 의 몫 — 여기서 도달 불가로 겹쳐 내지 않는다."""
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


@pytest.mark.parametrize(
    ("rule_id", "slots"),
    [
        # R3-9 — `-006` 은 노드 어휘와 파이프라인 상태 **둘 다** 받는다.
        ("LNT-STATE-006", ("name", "mapped")),
        ("LNT-STATE-007", ("name",)),
    ],
)
def test_rule_slots_are_what_this_module_fills(
    rule_id: str, slots: tuple[str, ...]
) -> None:
    """이 모듈이 채우는 슬롯이 규칙이 요구하는 슬롯과 정확히 같은가.

    규칙 문구가 바뀌어 슬롯이 늘면 `rules.finding()` 이 `LintomataError` 를 내면서
    **규칙 id 가 사라진다.** 통합 전에 여기서 걸린다.
    """
    rule = rules.get_rule(rule_id)
    assert rule.slots == slots
    assert "pipeline-register" in rule.when


def test_result_defaults_are_empty() -> None:
    result = ReachResult()
    assert result.reachable == set()
    assert result.unreachable == set()
    assert result.reachable_states == set()
    assert result.order == []


# ── ★ 안 풀린 `delay` 는 0 이 아니라 모름이다 (MODULES.md R4-3) ──────────────


def _config_ordered_pipeline() -> tuple[Pipeline, dict[str, dict[str, str]]]:
    """구간의 통과 순서를 **Spec config 가 정하는** 파이프라인.

    `w` 는 `loading` 을 기다리는데 그때 앞단 `b`(= `done` 대기)가 아직 안 돌았다.
    그래서 `loading` 이 `done` **뒤에** 와야만 `w` 가 돈다 — `${config.d*}` 값에
    따라 도달성이 갈린다. 등록 시점에는 그 값을 알 수 없다.
    """
    pipeline = _pipeline(
        [
            _node("a"),
            _node("w", inputs={"t": "b"}, when="stop"),
            _node("b", when="stop"),
        ],
        values=["idle", "loading", "done"],
        initial="idle",
        transitions=[("a", "loading"), ("a", "done")],
    )
    pipeline.transitions[0].delay = "${config.d1}"
    pipeline.transitions[1].delay = "${config.d2}"
    return pipeline, {"w": {"stop": "loading"}, "b": {"stop": "done"}}


def test_unresolved_delay_does_not_block_registration() -> None:
    """추측으로 등록을 막지 않는다 — **config 만 바꾸면 돌 파이프라인**이다.

    `delay` 를 `0` 으로 추측하면 `loading → done` 순서가 되어 `w` 가 도달 불가로
    보이고 `LNT-STATE-007` 이 등록을 막는다. 실행 시점에는 `engine.state` 가 config 를
    풀어 실제 값을 쓰므로 두 층이 서로 다른 말을 하게 된다.
    """
    pipeline, node_states = _config_ordered_pipeline()
    findings = check_reachability(pipeline, node_states, "/p.json")

    assert _ids(findings, "LNT-STATE-007") == set()
    # 정보는 남긴다 — Finding 만 안 낸다.
    result = simulate(pipeline, node_states)
    assert "w" in result.unreachable
    assert result.unknown_order_states == {"loading", "done"}


def test_resolved_delay_still_blocks_registration() -> None:
    """값이 적혀 있으면 순서를 아는 것이므로 그대로 판정한다."""
    pipeline, node_states = _config_ordered_pipeline()
    pipeline.transitions[0].delay = 0
    pipeline.transitions[1].delay = 10
    findings = check_reachability(pipeline, node_states, "/p.json")

    assert _ids(findings, "LNT-STATE-007") == {"w"}
    _assert_rendered(findings)
    assert simulate(pipeline, node_states).unknown_order_states == set()


def test_single_transition_delay_is_never_unknown() -> None:
    """전이가 하나면 순서랄 것이 없다 — `delay` 가 안 풀렸어도 모름이 아니다."""
    pipeline = _pipeline(
        [_node("a"), _node("w", when="stop")],
        values=["idle", "gone"],
        initial="idle",
        transitions=[("a", "gone")],
    )
    pipeline.transitions[0].delay = "${config.settleMs}"

    assert simulate(pipeline, {"w": {"stop": "gone"}}).unknown_order_states == set()


def test_unknown_order_does_not_hide_other_unreachable_nodes() -> None:
    """모름은 **그 구간에 걸린 노드에만** 적용된다 — 무관한 도달 불가는 그대로 난다."""
    pipeline = _pipeline(
        [
            _node("a"),
            _node("w", when="stop"),
            _node("lost", when="never"),
        ],
        values=["idle", "loading", "done", "never"],
        initial="idle",
        transitions=[("a", "loading"), ("a", "done"), ("lost", "never")],
    )
    pipeline.transitions[0].delay = "${config.d1}"
    pipeline.transitions[1].delay = "${config.d2}"
    node_states = {"w": {"stop": "loading"}, "lost": {"never": "never"}}

    findings = check_reachability(pipeline, node_states, "/p.json")
    assert _ids(findings, "LNT-STATE-007") == {"lost"}
