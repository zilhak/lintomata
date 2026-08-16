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
    env: dict[str, str] | None = None,
) -> StateMachine:
    return StateMachine(
        States(values=values, initial=initial),
        [Transition.model_validate(item) for item in (transitions or [])],
        config or {},
        STARTED_AT,
        env=env or {},
    )


def test_엔진_제공_필드의_정본은_model_이다() -> None:
    """복제해 두면 엔진 제공 필드가 늘 때 `STR-BAN-004` 오탐이 난다 (R3-13)."""
    assert set(ENGINE_FIELDS) == set(ENGINE_STATE_FIELDS)


def test_초기_상태에서_시작한다() -> None:
    assert machine(["idle", "settled"], "idle").current == "idle"


def step_through(m: StateMachine, node_id: str) -> None:
    """구동부(`engine.drive`)가 하는 것과 **같은 방식**으로 구간을 지나간다.

    통째로 미는 편의 함수를 두지 않는 이유가 이것이다 — 구간을 한 칸씩 지나가야
    중간 상태에서 대기 중이던 노드가 그 자리에서 돌 수 있다 (R4-1).
    """
    for delay, to in m.steps_after(node_id):
        m.enter(to, delay)


def test_전이는_해당_노드가_끝났을_때만_일어난다() -> None:
    m = machine(
        ["idle", "settled"], "idle", [{"after": "submit", "to": "settled"}]
    )
    step_through(m, "other")
    assert m.current == "idle"
    step_through(m, "submit")
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
    m = StateMachine(pipeline.states, pipeline.transitions, {}, STARTED_AT, env={})

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


def test_delay_는_env_로도_풀린다() -> None:
    """**같은 문서 안에서 자리마다 `${env.X}` 동작이 갈리면 안 된다** (R6-4).

    `params` 는 `config` → `state` → `env` 로 풀리는데 전이의 `delay` 만 env 를
    안 풀어서, `${env.X}` 를 쓴 사람이 *"정수로 풀리지 않았습니다"* 를 받았다.
    환경변수 값은 언제나 문자열이므로 정수 형태의 문자열을 정수로 읽는다.
    """
    m = machine(
        ["idle", "settled"],
        "idle",
        [{"after": "a", "to": "settled", "delay": "${env.SETTLE_MS}"}],
        env={"SETTLE_MS": "1500"},
    )
    assert m.steps_after("a") == [(1500, "settled")]


def test_delay_의_config_값이_env_를_품어도_풀린다() -> None:
    """합성 순서가 `config` → `state` → `env` 이므로 env 가 마지막이다."""
    m = machine(
        ["idle", "settled"],
        "idle",
        [{"after": "a", "to": "settled", "delay": "${config.settleMs}"}],
        {"settleMs": "${env.SETTLE_MS}"},
        env={"SETTLE_MS": "700"},
    )
    assert m.steps_after("a") == [(700, "settled")]


def test_delay_의_미정의_env_는_STR_PATH_002() -> None:
    with pytest.raises(StrictlerError) as caught:
        machine(
            ["idle", "settled"],
            "idle",
            [{"after": "a", "to": "settled", "delay": "${env.NOPE}"}],
        )
    assert [item.rule_id for item in caught.value.findings] == ["STR-PATH-002"]


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
    step_through(m, "a")

    assert waited == [0.25]
    assert m.current == "x"


def test_지연이_0_이면_기다리지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr(state_module, "_sleep", waited.append)

    step_through(machine(["idle", "x"], "idle", [{"after": "a", "to": "x"}]), "a")

    assert waited == []


def test_matches_는_노드_어휘를_파이프라인_상태로_번역한다() -> None:
    m = machine(["idle", "settled"], "idle", [{"after": "a", "to": "settled"}])

    assert m.matches({"stop": "settled"}, "stop") is False
    step_through(m, "a")
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
    step_through(m, "a")
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


def test_구간을_한_칸씩_지나가면_중간_상태를_실제로_거친다() -> None:
    """마지막 상태만 반영하면 **중간 상태를 기다리던 노드가 통째로 사라진다** (R4-1)."""
    m = machine(
        ["idle", "loading", "done"],
        "idle",
        [
            {"after": "a", "to": "loading"},
            {"after": "a", "to": "done", "delay": 10},
            {"after": "b", "to": "done"},
        ],
    )
    seen: list[str] = [m.current]
    for delay, to in m.steps_after("a"):
        m.enter(to, delay)
        seen.append(m.current)

    assert seen == ["idle", "loading", "done"]
    assert m.steps_after("b") == [(0, "done")]
    assert m.steps_after("없음") == []


def test_노드는_상태를_바꾸지_못한다() -> None:
    """전이는 런타임이 수행한다 — `steps_after` 는 **사본**을 준다."""
    m = machine(["idle", "x"], "idle", [{"after": "a", "to": "x"}])
    m.steps_after("a").clear()
    assert m.steps_after("a") == [(0, "x")]
