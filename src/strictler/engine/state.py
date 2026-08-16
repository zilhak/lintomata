"""파이프라인 상태머신 (`schema.md` 8절).

**전이는 파이프라인 구동 엔진이 수행한다.** 상태는 파이프라인에 있으므로 파이프라인이
관리한다. **노드는 상태를 읽기만 하고**(`when`) 결과만 반환한다.
→ 재사용 노드가 남의 파이프라인 상태를 오염시킬 수 없고, 이름 매핑이 읽기 전용이라 단순해진다.

**`transitions` 는 시간만 다룬다.** `after` — 그 노드가 끝나면. `delay` — 그 뒤 지연.
노드 결과에 따른 분기 문법은 존재하지 않는다 (`schema.md` 10절).

### state 는 "엔진의 실행 상태" 하나다

`capturing` 같은 사용자 정의 상태와 실행 시각 같은 엔진 제공 값은 성질이 다른 두 가지가
아니다. 둘 다 엔진의 실행 상태이고, `Args.state` 라는 **하나의 dataclass 안의 필드들**이다.

- **`__` 접두는 엔진 제공 필드 예약** — `${state.__startedAt}`. 사용자 상태 이름에 금지
- 실행 시각 형식은 **epoch 밀리초 정수**. 문자열 포맷을 주면 스크립트가 파싱하다가
  로케일·타임존 비결정성이 새어들어온다

### 파이프라인 상태는 **한 번에 하나**다

`states.values` 는 상태 변수 목록이 아니라 **상태 이름 목록**이고 `initial` 이 그중 하나다.
그래서 노드가 자기 어휘로 선언한 상태 이름의 "현재 값" 은 **지금 그 상태인가**(`bool`)다.
`snapshot()` 이 그 bool 들을 담아 준다.

### 같은 `after` 를 갖는 전이가 둘 이상이면 그것은 **구간**이다

`{after:A, to:loading}` + `{after:A, to:done, delay:5000}` 은 `schema.md` 8절이 `delay` 로
표현하려던 구간 그 자체다. **`delay` 오름차순(없으면 0), 같으면 선언 순서**로 차례로
지나간다 — `checks.reachability` 와 **같은 규칙이어야 한다** (MODULES.md R3-6).
중간 상태에서 대기 중이던 노드가 그 자리에서 돌아야 하므로, 구동부는 `after_node()`
대신 `steps_after()` + `enter()` 로 **한 칸씩** 지나가며 그 사이에 노드를 소진한다.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from strictler import refs
from strictler.errors import StrictlerError
from strictler.model import ENGINE_STATE_FIELDS, States, Transition

__all__ = ["ENGINE_FIELDS", "StateMachine"]


ENGINE_FIELDS: tuple[str, ...] = tuple(sorted(ENGINE_STATE_FIELDS))
"""엔진이 자동으로 채워주는 필드들. 사용자가 `states.values` 에 선언하지 않는다.

**정본은 `model.ENGINE_STATE_FIELDS`** — `refs.py`·`checks/script.py` 와 같은 것을 본다.
복제해 두면 엔진 제공 필드가 늘 때 `STR-BAN-004` 오탐이 난다."""


_sleep = time.sleep
"""`delay` 를 실제로 기다리는 자리. 테스트가 갈아끼울 수 있게 모듈 변수로 둔다.

**시각을 읽는 것이 아니다** — `started_at_ms` 는 호출자가 주고, 여기서는 선언된
`delay` 만큼 기다릴 뿐이라 결과가 비결정적이 되지 않는다."""


def _delay_ms(raw: int | str | None, config: Mapping[str, Any]) -> int:
    """`delay` 를 밀리초 정수로 푼다.

    `${config.settleMs}` 같은 참조가 올 수 있어 `str` 도 받는다 (`model.Transition`).
    **실행 시점에는 config 가 이미 풀려 있어야 한다** — 안 풀리거나 정수가 아니면
    기다릴 시간을 모르는 것이므로 **오류**다 (위반이 아니다).
    """
    if raw is None:
        return 0
    if isinstance(raw, bool):  # bool 은 int 의 하위형이라 먼저 걸러낸다
        raise StrictlerError(
            f"전이의 `delay` 가 참/거짓입니다: {raw!r}\n"
            "`delay` 는 밀리초 정수이거나 `${config.X}` 참조여야 합니다."
        )
    if isinstance(raw, int):
        value: Any = raw
    else:
        value = refs.expand_config(raw, config)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StrictlerError(
            f"전이의 `delay` 가 정수로 풀리지 않았습니다: {raw!r} → {value!r}\n"
            "`delay` 는 밀리초 정수입니다. `${config.X}` 로 받는다면 그 config 의 "
            "`type` 을 `int` 로 선언하고 Spec 에서 정수를 채우세요."
        )
    if value < 0:
        raise StrictlerError(
            f"전이의 `delay` 가 음수입니다: {value}\n"
            "`delay` 는 전이까지 기다릴 밀리초이므로 0 이상이어야 합니다."
        )
    return value


class StateMachine:
    """파이프라인 하나의 상태를 들고 전이를 수행한다."""

    def __init__(
        self,
        states: States,
        transitions: list[Transition],
        config: Mapping[str, Any],
        started_at_ms: int,
    ) -> None:
        """`config` 는 `delay` 의 `${config.settleMs}` 를 풀기 위해 받는다.

        `started_at_ms` 는 **호출자가 준다** — 엔진 안에서 시각을 읽지 않으면
        테스트가 결정적이 된다.
        """
        self.states = states
        self.started_at_ms = started_at_ms
        self._current = states.initial

        grouped: dict[str, list[tuple[int, int, str]]] = {}
        for index, transition in enumerate(transitions):
            grouped.setdefault(transition.after, []).append(
                (_delay_ms(transition.delay, config), index, transition.to)
            )
        # `delay` 오름차순 → 선언 순서. `checks.reachability._outgoing` 과 같은 규칙이다.
        self._steps: dict[str, list[tuple[int, str]]] = {
            after: [(delay, to) for delay, _, to in sorted(items)]
            for after, items in grouped.items()
        }

    @property
    def current(self) -> str:
        """현재 상태 이름."""
        return self._current

    def steps_after(self, node_id: str) -> list[tuple[int, str]]:
        """이 노드가 끝났을 때 지나갈 `(지연 ms, 도착 상태)` 구간.

        구동부가 **한 칸씩** 지나가며 그 사이에 실행 가능해진 노드를 소진한다 —
        마지막 상태만 반영하면 중간 상태를 기다리는 노드가 통째로 사라진다 (R3-6).
        """
        return list(self._steps.get(node_id, ()))

    def enter(self, to: str, delay_ms: int = 0) -> None:
        """구간 한 칸을 지나간다 — 지연만큼 기다린 뒤 상태를 옮긴다."""
        if delay_ms > 0:
            _sleep(delay_ms / 1000)
        self._current = to

    def after_node(self, node_id: str) -> None:
        """노드 하나가 끝났음을 알린다. 해당하는 전이가 있으면 (지연 후) 수행한다."""
        for delay, to in self.steps_after(node_id):
            self.enter(to, delay)

    def matches(self, node_state_mapping: Mapping[str, str], when_state: str) -> bool:
        """노드의 `when` 이 지금 만족되는지.

        `when` 은 **노드 자기 어휘**로 쓰였으므로 `node_state_mapping`
        (`{노드 어휘: 파이프라인 상태 이름}`)으로 번역해 현재 상태와 대조한다.
        """
        return node_state_mapping.get(when_state) == self._current

    def snapshot(self, node_state_mapping: Mapping[str, str]) -> dict[str, Any]:
        """그 노드에게 줄 `Args.state` 값을 만든다.

        노드가 선언한 이름(`Args.state` 의 필드 이름)을 키로, 매핑된 파이프라인
        상태의 현재 값을 값으로 담는다. 파이프라인 상태는 한 번에 하나이므로
        "현재 값" 은 **지금 그 상태인가**(`bool`)다.
        엔진 제공 필드(`__startedAt`)를 함께 넣는다 — `${state.__startedAt}` 로
        `params` 에서 참조된다. `Args.state` 에는 선언될 수 없으므로
        (`STR-STATE-001`) `engine.exec.build_args` 가 선언된 필드만 골라 담는다.
        """
        snap: dict[str, Any] = {
            name: mapped == self._current for name, mapped in node_state_mapping.items()
        }
        snap["__startedAt"] = self.started_at_ms
        return snap

    def blocked_by(self, node_id: str) -> list[str]:
        """이 노드가 실패했을 때 **일어나지 않게 되는 전이의 도착 상태들**.

        `not_run` 전파의 두 번째 경로(상태 의존)를 계산하는 재료다 (`schema.md` 9절).
        """
        return [to for _, to in self.steps_after(node_id)]
