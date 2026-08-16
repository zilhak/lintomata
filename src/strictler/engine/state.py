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

⚠ stub. Step 3 에서 구현한다.
"""

from __future__ import annotations

from typing import Any, Mapping

from strictler.model import States, Transition

__all__ = ["ENGINE_FIELDS", "StateMachine"]


ENGINE_FIELDS: tuple[str, ...] = ("__startedAt",)
"""엔진이 자동으로 채워주는 필드들. 사용자가 `states.values` 에 선언하지 않는다."""


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
        raise NotImplementedError("Step 3에서 구현")

    @property
    def current(self) -> str:
        """현재 상태 이름."""
        raise NotImplementedError("Step 3에서 구현")

    def after_node(self, node_id: str) -> None:
        """노드 하나가 끝났음을 알린다. 해당하는 전이가 있으면 (지연 후) 수행한다."""
        raise NotImplementedError("Step 3에서 구현")

    def matches(self, node_state_mapping: Mapping[str, str], when_state: str) -> bool:
        """노드의 `when` 이 지금 만족되는지.

        `when` 은 **노드 자기 어휘**로 쓰였으므로 `node_state_mapping`
        (`{노드 어휘: 파이프라인 상태 이름}`)으로 번역해 현재 상태와 대조한다.
        """
        raise NotImplementedError("Step 3에서 구현")

    def snapshot(self, node_state_mapping: Mapping[str, str]) -> dict[str, Any]:
        """그 노드에게 줄 `Args.state` 값을 만든다.

        노드가 선언한 이름(`Args.state` 의 필드 이름)을 키로, 매핑된 파이프라인
        상태의 현재 값을 값으로 담는다. 엔진 제공 필드(`__startedAt`)를 함께 넣는다.
        """
        raise NotImplementedError("Step 3에서 구현")

    def blocked_by(self, node_id: str) -> list[str]:
        """이 노드가 실패했을 때 **일어나지 않게 되는 전이의 도착 상태들**.

        `not_run` 전파의 두 번째 경로(상태 의존)를 계산하는 재료다 (`schema.md` 9절).
        """
        raise NotImplementedError("Step 3에서 구현")
