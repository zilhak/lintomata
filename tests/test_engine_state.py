"""Step 3-a — 파이프라인 상태머신 (`engine/state.py`).

**전이는 런타임이 수행하고 노드는 읽기만 한다.** 여기서 짚는 것:
  - 같은 `after` 를 갖는 전이가 **구간**으로 전개되는가 (`delay` 오름차순 → 선언 순서)
  - 그 규칙이 `checks.reachability` 와 **같은가** (R3-6 — 다르면 등록 성패가 뒤집힌다)
  - `snapshot` 이 노드 어휘 → 현재 상태 여부 + `__startedAt` 를 담는가
  - `started_at_ms` 를 주입하므로 결과가 결정적인가
"""

from __future__ import annotations

from typing import Any

import pytest

from strictler.checks import reachability
from strictler.engine import state as state_module
from strictler.engine.state import ENGINE_FIELDS, StateMachine
from strictler.errors import StrictlerError
from strictler.model import ENGINE_STATE_FIELDS, Pipeline, States, Transition

STARTED_AT = 1_700_000_000_000


def machine(
    values: list[str],
    initial: str,
    transitions: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> StateMachine:
    return StateMachine(
        States(values=values, initial=initial),
        [Transition.model_validate(item) for item in (transitions or [])],
        config or {},
        STARTED_AT,
    )


def test_엔진_제공_필드의_정본은_model_이다() -> None:
    """복제해 두면 엔진 제공 필드가 늘 때 `STR-BAN-004` 오탐이 난다 (R3-13)."""
    assert set(ENGINE_FIELDS) == set(ENGINE_STATE_FIELDS)


def test_초기_상태에서_시작한다() -> None:
    assert machine(["idle", "settled"], "idle").current == "idle"


def test_after_node_가_전이를_수행한다() -> None:
    m = machine(
        ["idle", "settled"], "idle", [{"after": "submit", "to": "settled"}]
    )
    m.after_node("other")
    assert m.current == "idle"
    m.after_node("submit")
    assert m.current == "settled"


def test_같은_after_의_전이는_delay_오름차순_구간이다() -> None:
    """`{after:A, to:loading}` + `{after:A, to:done, delay:5000}` 은 구간이다 (R3-6)."""
    m = machine(
        ["idle", "loading", "done"],
        "idle",
        [
            {"after": "a", "to": "done", "delay": 5000},
            {"after": "a", "to": "loading"},
        ],
    )
    assert m.steps_after("a") == [(0, "loading"), (5000, "done")]


def test_delay_가_같으면_선언_순서다() -> None:
    m = machine(
        ["idle", "x", "y"],
        "idle",
        [{"after": "a", "to": "y"}, {"after": "a", "to": "x"}],
    )
    assert [to for _, to in m.steps_after("a")] == ["y", "x"]


def test_전이_구간_규칙이_reachability_와_같다() -> None:
    """다르면 '등록은 통과했는데 실행에선 못 닿는다' 가 된다 (R3-6/R3-7)."""
    raw = {
        "info": {"name": "p", "description": "d", "kind": "verify"},
        "states": {"values": ["idle", "loading", "done"], "initial": "idle"},
        "transitions": [
            {"after": "a", "to": "done", "delay": 5000},
            {"after": "a", "to": "loading"},
        ],
        "nodes": [{"id": "a", "source": "/x.json"}],
    }
    pipeline = Pipeline.model_validate(raw)
    m = StateMachine(pipeline.states, pipeline.transitions, {}, STARTED_AT)

    outgoing = reachability._outgoing(pipeline)
    assert [to for _, to in m.steps_after("a")] == outgoing["a"]


def test_delay_는_config_로_풀린다() -> None:
    m = machine(
        ["idle", "settled"],
        "idle",
        [{"after": "a", "to": "settled", "delay": "${config.settleMs}"}],
        {"settleMs": 2000},
    )
    assert m.steps_after("a") == [(2000, "settled")]


def test_delay_가_정수로_안_풀리면_오류다() -> None:
    with pytest.raises(StrictlerError) as caught:
        machine(
            ["idle", "settled"],
            "idle",
            [{"after": "a", "to": "settled", "delay": "${config.settleMs}"}],
            {"settleMs": "곧"},
        )
    assert "정수" in caught.value.message


def test_delay_가_음수면_오류다() -> None:
    with pytest.raises(StrictlerError):
        machine(["idle", "x"], "idle", [{"after": "a", "to": "x", "delay": -1}])


def test_enter_가_선언된_delay_만큼_기다린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """**시각을 읽는 것이 아니다** — 선언된 지연을 기다릴 뿐이라 결과는 결정적이다."""
    waited: list[float] = []
    monkeypatch.setattr(state_module, "_sleep", waited.append)

    m = machine(["idle", "x"], "idle", [{"after": "a", "to": "x", "delay": 250}])
    m.after_node("a")

    assert waited == [0.25]
    assert m.current == "x"


def test_지연이_0_이면_기다리지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr(state_module, "_sleep", waited.append)

    machine(["idle", "x"], "idle", [{"after": "a", "to": "x"}]).after_node("a")

    assert waited == []


def test_matches_는_노드_어휘를_파이프라인_상태로_번역한다() -> None:
    m = machine(["idle", "settled"], "idle", [{"after": "a", "to": "settled"}])

    assert m.matches({"stop": "settled"}, "stop") is False
    m.after_node("a")
    assert m.matches({"stop": "settled"}, "stop") is True
    # 매핑에 없는 이름은 만족될 수 없다 — `STR-STATE-002` 가 등록 시점에 짚는다.
    assert m.matches({"stop": "settled"}, "모름") is False


def test_snapshot_은_상태_여부와_실행_시각을_담는다() -> None:
    m = machine(["idle", "settled"], "idle", [{"after": "a", "to": "settled"}])

    assert m.snapshot({"go": "idle", "stop": "settled"}) == {
        "go": True,
        "stop": False,
        "__startedAt": STARTED_AT,
    }
    m.after_node("a")
    assert m.snapshot({"go": "idle", "stop": "settled"}) == {
        "go": False,
        "stop": True,
        "__startedAt": STARTED_AT,
    }


def test_snapshot_의_실행_시각은_호출자가_준_값_그대로다() -> None:
    """엔진 안에서 시각을 읽지 않으므로 결과가 결정적이다."""
    m = machine(["idle"], "idle")
    assert m.snapshot({})["__startedAt"] == STARTED_AT
    assert m.snapshot({})["__startedAt"] == STARTED_AT


def test_blocked_by_는_안_일어나게_되는_전이의_도착_상태들이다() -> None:
    """`not_run` 전파의 두 번째 경로(상태 의존)를 계산하는 재료다."""
    m = machine(
        ["idle", "loading", "done"],
        "idle",
        [
            {"after": "a", "to": "loading"},
            {"after": "a", "to": "done", "delay": 10},
            {"after": "b", "to": "done"},
        ],
    )
    assert m.blocked_by("a") == ["loading", "done"]
    assert m.blocked_by("b") == ["done"]
    assert m.blocked_by("없음") == []


def test_노드는_상태를_바꾸지_못한다() -> None:
    """전이는 런타임이 수행한다 — `steps_after` 는 **사본**을 준다."""
    m = machine(["idle", "x"], "idle", [{"after": "a", "to": "x"}])
    m.steps_after("a").clear()
    assert m.steps_after("a") == [(0, "x")]
