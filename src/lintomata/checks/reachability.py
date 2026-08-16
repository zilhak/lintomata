"""도달 가능성 판정기 — **파이프라인 등록 시의 핵심 검사** (`schema.md` 13절).

**도달 불가 노드는 실패도 아니고 not run 도 아니라 4상태 어디에도 안 들어간다.**
→ 정적으로 잡아 **등록 자체를 막는다.**

| 검증 | 규칙 |
|---|---|
| `when` 이 참조하는 상태로 가는 transition 이 존재하는지 | `LNT-STATE-006` |
| 조건과 그래프만으로 상태머신을 돌려 안 닿는 노드가 없는지 | `LNT-STATE-007` |

조건과 그래프만으로 상태머신을 돌려보면 정적으로 판정된다 —
`transitions` 는 **시간만** 다루고 노드 결과에 따른 분기가 존재하지 않으므로
(`schema.md` 10절), 실행 없이 전개가 결정된다.
**이 성질이 이 모듈의 존재 근거다** — 설계에 없는 분기 개념을 도입하면 성립하지 않는다.

⚠ **not run 과 혼동하지 마라.** 여기서 잡는 것은 *구성 자체가 잘못돼 영원히 못 닿는 것*이고
등록 시점에 등록을 막는다. 앞단 실패의 여파로 *이번 실행에서* 못 닿은 것은 `not run` 이고
실행 시점에 엔진이 낸다 (`engine.runtime.propagate_not_run`).

## 전개 모델 — 상태는 언제나 하나다

파이프라인 상태는 **한 번에 하나**이고, 전이는 노드가 끝날 때만 일어난다.
그래서 전개는 다음 고정점이다:

1. 아직 안 돈 노드를 **선언 순서대로** 훑어 첫 번째 실행 가능한 것을 집는다 —
   `inputs` 의존이 전부 끝났고 `when` 이 **현재 상태**와 맞는 노드
2. 그 노드를 실행한 것으로 치고, 그 노드를 `after` 로 삼는 전이들을 **구간으로 지나간다**
3. 지나가는 **각 상태마다** 1 로 되돌아가 그 자리에서 실행 가능해진 노드를 전부 소진한다
4. 더 집을 노드가 없으면 끝. 남은 노드가 도달 불가다

실행할 때마다 노드가 하나씩 소진되므로 **전이가 사이클을 이뤄도 끝난다.**
한 번 조건이 안 맞았던 노드도 상태가 옮겨간 뒤 다시 본다.

**같은 `after` 를 갖는 전이가 둘 이상이면 그것은 구간이다.**
`{after:A, to:loading}` + `{after:A, to:done, delay:5000}` 은 `schema.md` 8절이
`delay` 로 표현하려던 구간 그 자체다 — 금지할 것이 아니라 **전개할 것**이다.
`delay` **오름차순(없으면 0), 같으면 선언 순서**로 차례로 지나가고,
각 중간 상태에서 대기 중이던 노드를 그 자리에서 실행 가능으로 본다.
마지막 하나만 반영하면 `reachable_states` 와 최종 상태가 서로 반대를 말하고
**전이 선언 순서를 뒤집으면 등록 성패가 뒤집힌다** (MODULES.md R3-6).

## ★ 안 풀린 `delay` 는 0 이 아니라 **모름**이다 (MODULES.md R4-3)

`delay: "${config.settleMs}"` 는 **Spec 이 값을 채우기 전까지 순서를 알 수 없다.**
여기서 `0` 으로 추측하면 등록 시점과 실행 시점(`engine.state` 는 config 를 풀어 실제
값을 쓴다)이 갈리고, **추측으로 등록을 막는** 일이 생긴다.

→ **두 층으로 나눈다.**

| 층 | 무엇을 하나 |
|---|---|
| 등록 시점 (여기) | 순서를 모르는 구간이 있으면 그 구간이 만드는 상태를 기다리는 노드에 **`-007` 을 내지 않는다** |
| 실행 시점 (`engine.drive`) | config 가 풀렸으니 **실제 값으로 판정**. 못 닿으면 `not_run(state_unreachable)` |

**config 가 도달성을 바꾸는 것은 정상이다** — 같은 파이프라인을 다른 Spec config 로
돌리는 것이 설계이고, not run 은 애초에 정상 결과다. 알 수 없는 것으로 등록을 막지
않는다 (lint 는 보수적으로). 전개 자체는 `0` 으로 가정해 계속한다 — `order` 는 있어야
하고, 그 순서에 기댄 **판정만** 내지 않는다.

**★ 동시에 실행 가능한 노드들의 순서는 파이프라인의 `nodes` 선언 순서다. 이것은 계약이다**
(MODULES.md R3-7). 상태가 하나뿐이라 순서를 정하지 않으면 결과가 갈리고,
**등록 성패까지 갈린다** — 등록은 통과했는데 실행에선 못 닿는 일이 생기면 안 된다.
→ `simulate().order` 가 **참조 구현**이고 `engine.runtime` 이 이 순서를 따른다.

## 다른 규칙이 이미 보고한 것은 여기서 다시 내지 않는다

`when` 을 파이프라인 상태로 번역할 수 없는 경우(매핑 누락 `LNT-STATE-002`,
매핑 대상이 `states.values` 에 없음 `LNT-STATE-003`, 노드가 선언 안 한 상태
`LNT-STATE-004`)는 **그 규칙들이 이미 원인을 짚었다.** 여기서 `-006`/`-007` 을 겹쳐
내면 AI 가 엉뚱한 곳을 고치므로, 그런 노드는 **상태 제약이 없는 것처럼** 전개한다.

같은 이유로 **데이터 의존으로 막힌 노드에는 `-007` 을 내지 않는다** (MODULES.md R3-8).
`-007` 의 guide 는 `when` 을 확인하라고 말하는데, `when` 이 없는 노드가 그걸 받으면
AI 가 엉뚱한 곳을 고친다. 데이터로 막힌 이유는 언제나 따로 보고된다 —
없는 노드 id 는 `LNT-REF-003`, 의존 대상이 도달 불가면 그 대상이 `-007` 로,
순환은 `LNT-GRAPH-001`. **`ReachResult.unreachable` 에는 그대로 담는다** —
정보는 남기고 Finding 만 안 낸다.
"""

from __future__ import annotations

from typing import Any

from lintomata import rules
from lintomata.errors import Finding
from lintomata.model import Pipeline, PipelineNode

__all__ = ["ReachResult", "simulate", "check_reachability"]


class ReachResult:
    """정적 시뮬레이션 결과.

    필드:
      `reachable`          — 언젠가 실행될 수 있는 노드 id 집합
      `unreachable`        — 영원히 실행되지 않는 노드 id 집합
      `reachable_states`   — 초기 상태에서 실제로 들어가지는 상태 이름 집합
      `order`              — 실행 순서. **동시 실행 가능한 노드는 선언 순서다 —
                             이것은 계약이고 `engine.drive` 가 이 순서를 따른다**
                             (MODULES.md R3-7)
      `unknown_order_states` — 통과 순서를 **모르는** 구간이 만드는 상태들.
                             `delay` 가 아직 안 풀린 `${config.X}` 라 등록 시점에는
                             순서를 알 수 없다 (MODULES.md R4-3)
    """

    def __init__(self) -> None:
        self.reachable: set[str] = set()
        self.unreachable: set[str] = set()
        self.reachable_states: set[str] = set()
        self.order: list[str] = []
        self.unknown_order_states: set[str] = set()


def _wait_state(
    node: PipelineNode,
    node_states: dict[str, dict[str, str]],
    declared: set[str],
) -> str | None:
    """이 노드가 기다리는 **파이프라인 상태 이름**. 조건이 없거나 번역 불가면 `None`.

    `when` 은 노드 자기 어휘로 쓰여 있고 `node_states` 가 파이프라인 상태 이름으로
    번역한다 (`schema.md` 8절). 번역이 안 되는 것은 `LNT-STATE-002`/`-003`/`-004`
    가 이미 보고했으므로 여기서는 제약 없음으로 다룬다.
    """
    if node.when is None:
        return None
    mapped = node_states.get(node.id, {}).get(node.when.state)
    if mapped is None or mapped not in declared:
        return None
    return mapped


def _outgoing(pipeline: Pipeline) -> dict[str, list[str]]:
    """`{after: [지나가는 상태, ...]}` — 같은 `after` 의 전이는 **구간**이다.

    `delay` 오름차순(없으면 0), 같으면 선언 순서. `delay` 가 아직 안 풀린
    `${config.X}` 문자열이면 전개를 위해 `0` 으로 가정한다 —
    **그 가정에 기댄 판정은 `_unknown_order_states()` 가 따로 걸러낸다** (R4-3).
    """
    grouped: dict[str, list[tuple[int, int, str]]] = {}
    for index, transition in enumerate(pipeline.transitions):
        delay = transition.delay if isinstance(transition.delay, int) else 0
        grouped.setdefault(transition.after, []).append((delay, index, transition.to))
    return {
        after: [to for _, _, to in sorted(items)] for after, items in grouped.items()
    }


def _unknown_order_states(pipeline: Pipeline) -> set[str]:
    """통과 순서를 **모르는** 구간이 만드는 상태들 (MODULES.md R4-3).

    구간(같은 `after` 의 전이 둘 이상) 안에 아직 안 풀린 `delay` 가 하나라도 있으면
    그 구간의 통과 순서는 **Spec 이 config 를 채워야 정해진다.** 전이가 하나뿐이면
    순서랄 것이 없으므로 모름이 아니다.
    """
    grouped: dict[str, list[Any]] = {}
    for transition in pipeline.transitions:
        grouped.setdefault(transition.after, []).append(transition)
    unknown: set[str] = set()
    for items in grouped.values():
        if len(items) < 2:
            continue
        if any(not isinstance(t.delay, int) and t.delay is not None for t in items):
            unknown.update(t.to for t in items)
    return unknown


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
    outgoing = _outgoing(pipeline)

    current = pipeline.states.initial
    result.reachable_states.add(current)
    executed: set[str] = set()

    def ready() -> PipelineNode | None:
        """지금 상태에서 실행 가능한 첫 노드 — **선언 순서**가 tie-break 다(계약)."""
        for node in nodes:
            if node.id in executed:
                continue
            if not all(dep in executed for dep in deps[node.id]):
                continue
            wait = waits[node.id]
            if wait is not None and wait != current:
                continue
            return node
        return None

    def drain() -> None:
        """지금 상태에서 더 집을 노드가 없을 때까지 소진한다."""
        while True:
            node = ready()
            if node is None:
                return
            executed.add(node.id)
            result.order.append(node.id)
            pass_through(node.id)

    def pass_through(node_id: str) -> None:
        """이 노드를 `after` 로 삼는 전이 구간을 차례로 지나간다.

        **각 중간 상태에서 대기 중이던 노드를 그 자리에서 실행 가능으로 본다** —
        마지막 상태만 반영하면 중간 상태를 기다리는 노드가 통째로 사라진다.
        """
        nonlocal current
        for to in outgoing.get(node_id, ()):
            current = to
            result.reachable_states.add(to)
            drain()

    drain()

    result.reachable = set(executed)
    result.unreachable = {node.id for node in nodes} - executed
    result.unknown_order_states = _unknown_order_states(pipeline)
    return result


def check_reachability(
    pipeline: Pipeline,
    node_states: dict[str, dict[str, str]],
    source_path: str,
) -> list[Finding]:
    """`LNT-STATE-006` / `-007` 판정.

    `-006`: `when` 이 참조하는 상태로 가는 transition 이 아예 없다 →
            노드가 영원히 실행되지 않는다. **고치는 방법은 전이를 추가하는 것.**
    `-007`: 전이는 있는데 그래프와 함께 돌려보니 그 조합에 닿지 못한다.
            **고치는 방법은 조건과 배선의 순서를 바로잡는 것.**

    한 노드에 둘 다 내지 않는다 — `-006` 이 더 구체적인 진단이므로 그쪽만 낸다.
    규칙을 나누는 기준은 증상이 아니라 **고치는 방법**이다.

    **`-007` 은 `when` 으로 막힌 노드에만 낸다** (MODULES.md R3-8) —
    즉 `inputs` 의존은 전부 도달 가능한데도 못 닿는 노드다. 데이터로 막힌 것은
    원인이 따로 보고되므로(`LNT-REF-003` / 그 대상의 `-007` / `LNT-GRAPH-001`)
    여기서 겹쳐 내지 않는다. `ReachResult.unreachable` 에는 그대로 남는다.
    """
    findings: list[Finding] = []
    declared = set(pipeline.states.values)

    # 초기 상태는 전이 없이도 처음부터 참이다 — 전이가 없다고 죽은 상태가 아니다.
    entered_by_transition = {pipeline.states.initial}
    entered_by_transition.update(transition.to for transition in pipeline.transitions)

    dead_when: set[str] = set()
    for node in pipeline.nodes:
        when = node.when
        wait = _wait_state(node, node_states, declared)
        if when is None or wait is None or wait in entered_by_transition:
            continue
        dead_when.add(node.id)
        # 두 층을 다 보여준다 — `when` 에 적는 것은 노드 어휘 `{name}` 이고
        # 전이를 추가할 자리는 파이프라인 어휘 `{mapped}` 다 (`schema.md` 8절).
        findings.append(
            rules.finding(
                "LNT-STATE-006",
                path=source_path,
                node=node.id,
                fields={"name": when.state, "mapped": wait},
            )
        )

    result = simulate(pipeline, node_states)
    for node in pipeline.nodes:
        if node.id not in result.unreachable or node.id in dead_when:
            continue
        # 데이터 의존이 하나라도 못 닿으면 그쪽이 원인이다 — 여기서 겹쳐 내지 않는다.
        if not all(dep in result.reachable for dep in node.inputs.values()):
            continue
        # **순서를 모르는 구간에 걸린 노드는 판정하지 않는다** (R4-3).
        # `delay` 가 아직 `${config.X}` 라 전개가 추측이었고, 추측으로 등록을 막으면
        # config 만 바꾸면 돌 파이프라인이 아예 등록되지 못한다. 실행 시점에
        # config 가 풀린 뒤 `engine.drive` 가 `not_run` 으로 판정한다.
        if _wait_state(node, node_states, declared) in result.unknown_order_states:
            continue
        findings.append(
            rules.finding(
                "LNT-STATE-007",
                path=source_path,
                node=node.id,
                fields={"name": node.id},
            )
        )
    return findings
