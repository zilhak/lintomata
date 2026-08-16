"""도달 가능성 판정기 — **파이프라인 등록 시의 핵심 검사** (`schema.md` 13절).

**도달 불가 노드는 실패도 아니고 not run 도 아니라 4상태 어디에도 안 들어간다.**
→ 정적으로 잡아 **등록 자체를 막는다.**

| 검증 | 규칙 |
|---|---|
| `when` 이 참조하는 상태로 가는 transition 이 존재하는지 | `STR-STATE-006` |
| 조건과 그래프만으로 상태머신을 돌려 안 닿는 노드가 없는지 | `STR-STATE-007` |

조건과 그래프만으로 상태머신을 돌려보면 정적으로 판정된다 —
`transitions` 는 **시간만** 다루고 노드 결과에 따른 분기가 존재하지 않으므로
(`schema.md` 10절), 실행 없이 전개가 결정된다.

⚠ stub. Step 2 에서 구현한다.
"""

from __future__ import annotations

from strictler.errors import Finding
from strictler.model import Pipeline

__all__ = ["ReachResult", "simulate", "check_reachability"]


class ReachResult:
    """정적 시뮬레이션 결과.

    필드:
      `reachable`          — 언젠가 실행될 수 있는 노드 id 집합
      `unreachable`        — 영원히 실행되지 않는 노드 id 집합
      `reachable_states`   — 초기 상태에서 도달 가능한 상태 이름 집합
      `order`              — 실행 가능한 순서 하나 (위상 정렬 + 상태 전개)
    """

    def __init__(self) -> None:
        raise NotImplementedError("Step 2에서 구현")


def simulate(pipeline: Pipeline, node_states: dict[str, dict[str, str]]) -> ReachResult:
    """조건과 그래프만으로 상태머신을 돌려본다.

    `node_states` 는 `{노드 id: {노드 어휘: 파이프라인 상태 이름}}` — `when` 을
    파이프라인 상태로 번역하는 데 쓴다.

    전개 규칙: 초기 상태에서 시작해 (1) `inputs` 의존이 전부 만족되고
    (2) `when` 상태가 현재 상태와 맞는 노드를 실행 가능으로 표시하고,
    (3) `transitions.after` 가 그 노드면 상태를 전이시킨다. 더 이상 진행이
    없을 때까지 반복. 남은 노드가 `unreachable` 이다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_reachability(
    pipeline: Pipeline,
    node_states: dict[str, dict[str, str]],
    source_path: str,
) -> list[Finding]:
    """`STR-STATE-006` / `-007` 판정.

    `-006`: `when` 이 참조하는 상태로 가는 transition 이 아예 없다 →
            노드가 영원히 실행되지 않는다.
    `-007`: 전이는 있는데 그래프와 함께 돌려보니 그 조합에 닿지 못한다.
    """
    raise NotImplementedError("Step 2에서 구현")
