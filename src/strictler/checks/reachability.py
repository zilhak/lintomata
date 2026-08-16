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
**이 성질이 이 모듈의 존재 근거다** — 설계에 없는 분기 개념을 도입하면 성립하지 않는다.

⚠ **not run 과 혼동하지 마라.** 여기서 잡는 것은 *구성 자체가 잘못돼 영원히 못 닿는 것*이고
등록 시점에 등록을 막는다. 앞단 실패의 여파로 *이번 실행에서* 못 닿은 것은 `not run` 이고
실행 시점에 엔진이 낸다 (`engine.runtime.propagate_not_run`).

## 전개 모델 — 상태는 언제나 하나다

파이프라인 상태는 **한 번에 하나**이고, 전이는 노드가 끝날 때만 일어난다.
그래서 전개는 다음 라운드 반복의 고정점이다:

1. 아직 안 돈 노드를 **선언 순서대로** 훑는다
2. `inputs` 의존이 전부 끝났고 `when` 이 **현재 상태**와 맞으면 실행 가능으로 표시한다
3. 그 노드를 `after` 로 삼는 전이가 있으면 **즉시** 상태를 옮긴다
4. 한 라운드가 아무것도 새로 실행하지 못하면 끝. 남은 노드가 도달 불가다

라운드마다 최소 한 노드가 소진되므로 **전이가 사이클을 이뤄도 끝난다.**
한 번 조건이 안 맞았던 노드도 다음 라운드에 다시 본다 — 상태는 그 사이에 옮겨갈 수 있다.

**동시에 실행 가능한 노드들의 순서는 선언 순서로 정한다.** 상태가 하나뿐이므로
순서를 정하지 않으면 결과가 갈린다. 이 선택은 임의가 아니라 *결정적이어야 한다*는
요구에서 나온 것이고, 엔진도 같은 순서로 돈다.

## 다른 규칙이 이미 보고한 것은 여기서 다시 내지 않는다

`when` 을 파이프라인 상태로 번역할 수 없는 경우(매핑 누락 `STR-STATE-002`,
매핑 대상이 `states.values` 에 없음 `STR-STATE-003`, 노드가 선언 안 한 상태
`STR-STATE-004`)는 **그 규칙들이 이미 원인을 짚었다.** 여기서 `-006`/`-007` 을 겹쳐
내면 AI 가 엉뚱한 곳을 고치므로, 그런 노드는 **상태 제약이 없는 것처럼** 전개한다.
"""

from __future__ import annotations

from strictler import rules
from strictler.errors import Finding
from strictler.model import Pipeline, PipelineNode

__all__ = ["ReachResult", "simulate", "check_reachability"]


class ReachResult:
    """정적 시뮬레이션 결과.

    필드:
      `reachable`          — 언젠가 실행될 수 있는 노드 id 집합
      `unreachable`        — 영원히 실행되지 않는 노드 id 집합
      `reachable_states`   — 초기 상태에서 실제로 들어가지는 상태 이름 집합
      `order`              — 실행 가능한 순서 하나 (전개가 노드를 소진한 순서)
    """

    def __init__(self) -> None:
        self.reachable: set[str] = set()
        self.unreachable: set[str] = set()
        self.reachable_states: set[str] = set()
        self.order: list[str] = []


def _wait_state(
    node: PipelineNode,
    node_states: dict[str, dict[str, str]],
    declared: set[str],
) -> str | None:
    """이 노드가 기다리는 **파이프라인 상태 이름**. 조건이 없거나 번역 불가면 `None`.

    `when` 은 노드 자기 어휘로 쓰여 있고 `node_states` 가 파이프라인 상태 이름으로
    번역한다 (`schema.md` 8절). 번역이 안 되는 것은 `STR-STATE-002`/`-003`/`-004`
    가 이미 보고했으므로 여기서는 제약 없음으로 다룬다.
    """
    if node.when is None:
        return None
    mapped = node_states.get(node.id, {}).get(node.when.state)
    if mapped is None or mapped not in declared:
        return None
    return mapped


def simulate(pipeline: Pipeline, node_states: dict[str, dict[str, str]]) -> ReachResult:
    """조건과 그래프만으로 상태머신을 돌려본다.

    `node_states` 는 `{노드 id: {노드 어휘: 파이프라인 상태 이름}}` — `when` 을
    파이프라인 상태로 번역하는 데 쓴다.

    전개 규칙은 모듈 docstring 참조. 남은 노드가 `unreachable` 이다.
    """
    result = ReachResult()

    declared = set(pipeline.states.values)
    nodes = list(pipeline.nodes)
    waits = {node.id: _wait_state(node, node_states, declared) for node in nodes}
    # `inputs` 가 DAG 를 만든다 — 값이 앞단 노드 id 다 (`schema.md` 4절).
    deps = {node.id: tuple(node.inputs.values()) for node in nodes}

    outgoing: dict[str, list[str]] = {}
    for transition in pipeline.transitions:
        outgoing.setdefault(transition.after, []).append(transition.to)

    current = pipeline.states.initial
    result.reachable_states.add(current)

    executed: set[str] = set()
    progressed = True
    while progressed:
        progressed = False
        for node in nodes:
            if node.id in executed:
                continue
            if not all(dep in executed for dep in deps[node.id]):
                continue
            wait = waits[node.id]
            if wait is not None and wait != current:
                continue
            executed.add(node.id)
            result.order.append(node.id)
            progressed = True
            # 전이는 노드가 끝나는 그 자리에서 일어난다 — 뒤 노드는 바뀐 상태를 본다.
            for to in outgoing.get(node.id, ()):
                current = to
                result.reachable_states.add(to)

    result.reachable = set(executed)
    result.unreachable = {node.id for node in nodes} - executed
    return result


def check_reachability(
    pipeline: Pipeline,
    node_states: dict[str, dict[str, str]],
    source_path: str,
) -> list[Finding]:
    """`STR-STATE-006` / `-007` 판정.

    `-006`: `when` 이 참조하는 상태로 가는 transition 이 아예 없다 →
            노드가 영원히 실행되지 않는다. **고치는 방법은 전이를 추가하는 것.**
    `-007`: 전이는 있는데 그래프와 함께 돌려보니 그 조합에 닿지 못한다.
            **고치는 방법은 조건과 배선의 순서를 바로잡는 것.**

    한 노드에 둘 다 내지 않는다 — `-006` 이 더 구체적인 진단이므로 그쪽만 낸다.
    규칙을 나누는 기준은 증상이 아니라 **고치는 방법**이다.
    """
    findings: list[Finding] = []
    declared = set(pipeline.states.values)

    # 초기 상태는 전이 없이도 처음부터 참이다 — 전이가 없다고 죽은 상태가 아니다.
    entered_by_transition = {pipeline.states.initial}
    entered_by_transition.update(transition.to for transition in pipeline.transitions)

    dead_when: set[str] = set()
    for node in pipeline.nodes:
        wait = _wait_state(node, node_states, declared)
        if wait is None or wait in entered_by_transition:
            continue
        dead_when.add(node.id)
        findings.append(
            rules.finding(
                "STR-STATE-006",
                path=source_path,
                node=node.id,
                fields={"name": wait},
            )
        )

    result = simulate(pipeline, node_states)
    for node in pipeline.nodes:
        if node.id in result.unreachable and node.id not in dead_when:
            findings.append(
                rules.finding(
                    "STR-STATE-007",
                    path=source_path,
                    node=node.id,
                    fields={"name": node.id},
                )
            )
    return findings
