"""파이프라인 구동 루프 — **값 검증과 비교가 둘 다 이걸 쓴다** (MODULES.md R4-1).

`runtime` 과 `compare` 가 같은 구동 규칙을 각자 구현했더니 **실제로 갈렸다.**
셋 다 lint 결과 자체를 틀리게 만드는 종류였다:

| 규칙 | 갈렸을 때 벌어진 일 |
|---|---|
| 구간 전이 | 마지막 상태만 반영해 **중간 상태를 기다리던 노드가 not_run** |
| 실행 순서 | 정적 topo 정렬로 돌아 **통과할 노드에 거짓 not_run** |
| 실행 시 해시 대조 | 등록소 파일을 정적 검사 루트 밖에서 고쳐도 그냥 돈다 |

→ 구동에 관한 판단은 **전부 이 모듈에만** 둔다. 부르는 쪽이 주는 것은
"노드 하나를 실제로 돌리는 방법"(`run_node`) 뿐이다.

### 왜 정적 topo 정렬이 금지인가

`when` 이 **상태**에 걸리므로 실행 가능 순서가 **동적**이다. 앞 노드가 상태를 밀어야
비로소 뒷 노드가 돌 수 있고, 그 사이 순서는 그래프만 봐서는 나오지 않는다.
→ 매번 `ready()` 로 **재스캔**한다. 동시에 가능한 노드의 tie-break 는
**파이프라인 `nodes` 선언 순서**다 (MODULES.md R3-7).
`checks.reachability.simulate().order` 가 참조 구현이고 여기가 그 전개를 그대로 옮겼다.

### ★ 이건 lint 다

실패한 노드는 **전이를 밀지 않는다.** 그게 not run 의 두 번째 경로다.
**위반은 뒷단을 끊지 않는다** — 노드는 멀쩡히 값을 내놨다.
복구·재시도·대체 경로·skip 은 없다.

### ★ 모든 노드는 네 상태 중 정확히 하나에 들어간다 (R4-2)

`pass` / `violation` / `not_run` / `error`. **어느 상태에도 없이 리포트에서 조용히
사라지는 노드가 있으면 그건 거짓 리포트다** (`schema.md` 9절). `finalize()` 가
구동 후 남은 노드를 **전수 검사해서** 싹 다 `not_run` 으로 바꾼다.

⚠ 이 모듈은 `runtime` 도 `compare` 도 import 하지 않는다. 순환이 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from lintomata import refs, rules
from lintomata.checks.node import findings_of
from lintomata.engine.result import NodeOutcome, RunResult
from lintomata.engine.state import StateMachine
from lintomata.errors import Finding, NotRunCause, LintomataError
from lintomata.locale import message
from lintomata.model import Node, Pipeline, PipelineNode
from lintomata.store.entries import Store

__all__ = ["resolve_entry", "verify_hash", "resolve_libraries", "drive", "finalize"]


# ── 등록소 무결성 — 실행 시점 규칙 ───────────────────────────────────────────


def resolve_entry(
    value: str,
    kind: Any,
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
    node_id: str = "",
) -> tuple[Path | None, list[Finding]]:
    """`${ref.<id>}` 또는 경로를 실제 파일로 푼다 — **해시 대조까지** 한다.

    `LNT-REG-002`(삭제된 id) / `LNT-REG-001`(등록 이후 직접 수정) 은 **실행 시점**
    규칙이다 (`schema.md` 2·13절). 등록은 편의가 아니라 **검증 결과를 재사용하는
    기제**이므로, 정적 검사 루트를 피해 파일을 고친 것을 실행 직전에 잡아야 한다.
    """
    if refs.is_ref(value):
        try:
            refs.parse_ref(value, kind)
        except LintomataError as exc:
            return None, findings_of(exc, path=path, node=node_id)
        entry_id = _entry_id(value)
        try:
            store.show(entry_id)
        except LintomataError:
            return None, [
                rules.finding(
                    "LNT-REG-002", path=path, node=node_id, fields={"id": entry_id}
                )
            ]
        if not store.verify_hash(entry_id):
            return None, [
                rules.finding(
                    "LNT-REG-001", path=path, node=node_id, fields={"id": entry_id}
                )
            ]
        return store.path_of(entry_id), []

    try:
        resolved = refs.expand_path(value, env)
    except LintomataError as exc:
        return None, findings_of(exc, path=path, node=node_id)
    if not resolved.is_file():
        return None, [
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=message(
                    "No such file: {path}\n"
                    "Written as: {raw}. Check the path, and check the value of any "
                    "environment variable it references.",
                    path=resolved,
                    raw=repr(value),
                ),
            )
        ]
    return resolved, []


def verify_hash(
    value: Any, *, store: Store, path: str, node_id: str = ""
) -> list[Finding]:
    """`${ref.<id>}` 로 참조한 등록소 파일의 해시를 대조한다 (`LNT-REG-001`).

    참조가 아니면 볼 것이 없다. 삭제된 id 는 `LNT-REG-002` 를 내는 쪽이 이미 짚었다.
    """
    if not isinstance(value, str) or not refs.is_ref(value):
        return []
    entry_id = _entry_id(value)
    try:
        store.show(entry_id)
    except LintomataError:
        return []
    if store.verify_hash(entry_id):
        return []
    return [rules.finding("LNT-REG-001", path=path, node=node_id, fields={"id": entry_id})]


def resolve_libraries(
    node: Node, *, store: Store, env: Mapping[str, str], path: str, node_id: str
) -> tuple[dict[str, Path], list[Finding]]:
    """노드가 배선한 라이브러리를 **실행 시점 규칙까지 얹어** 푼다 (`schema.md` 6.5절).

    푸는 규칙 자체는 등록 검사와 **같은 함수**(`checks.library.resolve_libraries`)를
    쓰고, 여기서 더하는 것은 **해시 대조**(`LNT-REG-001`) 하나다 — 등록소 파일을
    정적 검사 루트를 피해 고친 것을 실행 직전에 잡는 자리다.

    ★ **값 검증·비교·단위테스트 셋이 전부 이 함수를 쓴다.** 셋이 각자 풀면 갈리고,
    갈린 쪽만 무단 수정된 라이브러리를 그냥 돌린다 (R4-1 이 겪은 사고가 그것이다).

    ★ **`node` 는 파이프라인의 노드 id 로 **덮어쓴다** — `or` 가 아니다.**
    등록 검사에서 온 결과는 노드의 `info.name` 을 달고 오는데, 파이프라인 문맥에서
    한 노드를 가리키는 이름은 **노드 id 하나**여야 한다. 그러지 않으면 같은 노드가
    리포트에 두 이름으로 찍혀 같은 것인지 알 수 없고, `not run` 전파도 노드 id
    문자열로 대조하므로 **여파가 통째로 어긋난다**.
    """
    from lintomata.checks import library as library_checks

    resolved, raw = library_checks.resolve_libraries(node, store=store, env=env)
    findings = [
        item.model_copy(update={"path": item.path or path, "node": node_id})
        for item in raw
    ]
    for value in node.libraries.values():
        findings.extend(verify_hash(value, store=store, path=path, node_id=node_id))
    return resolved, findings


def _entry_id(value: str) -> str:
    return value[len("${ref.") : -1]


# ── 구동 ─────────────────────────────────────────────────────────────────────


def drive(
    pipeline: Pipeline,
    *,
    machine: StateMachine,
    runnable: Iterable[str],
    run_node: Callable[[PipelineNode], NodeOutcome],
    result: RunResult,
) -> None:
    """`ready()` 재스캔으로 전개한다 — `simulate()` 와 **같은 규칙**이다.

    1. 아직 안 돈 노드를 **선언 순서대로** 훑어 첫 번째 실행 가능한 것을 집는다
    2. 그 노드를 돌리고, 성공하면 그 노드를 `after` 로 삼는 전이 **구간**을 지나간다
    3. 지나가는 **각 상태마다** 1 로 되돌아가 그 자리에서 실행 가능해진 노드를 소진한다

    `runnable` 은 실제로 돌릴 수 있는 노드 id 들이다 — 로드에 실패했거나 정적 오류가
    귀속된 노드는 부르는 쪽이 이미 `error` 로 확정해 `result.outcomes` 에 넣어 둔다.
    이미 결과가 있는 노드는 다시 집지 않는다.
    """
    declared = set(pipeline.states.values)
    can_run = set(runnable)
    done: set[str] = set(result.outcomes)
    succeeded = {
        node_id
        for node_id, outcome in result.outcomes.items()
        if outcome.status in ("pass", "violation")
    }

    def waits_for(pn: PipelineNode) -> str | None:
        """이 노드가 기다리는 파이프라인 상태. 번역 불가면 제약 없음으로 본다.

        번역이 안 되는 것은 `LNT-STATE-002`/`-003`/`-004` 가 등록 시점에 이미
        짚었다 — 여기서 조용히 영원히 막아버리면 원인이 뭉개진다.
        """
        if pn.when is None:
            return None
        mapped = pn.states.get(pn.when.state)
        if mapped is None or mapped not in declared:
            return None
        return mapped

    def ready() -> PipelineNode | None:
        for pn in pipeline.nodes:
            if pn.id in done or pn.id not in can_run:
                continue
            if not all(dep in succeeded for dep in pn.inputs.values()):
                continue
            wait = waits_for(pn)
            if wait is not None and wait != machine.current:
                continue
            return pn
        return None

    def drain() -> None:
        while True:
            pn = ready()
            if pn is None:
                return
            done.add(pn.id)
            outcome = run_node(pn)
            result.outcomes[pn.id] = outcome
            result.findings.extend(outcome.findings)
            if outcome.status == "error":
                continue  # 실패한 노드는 전이를 밀지 않는다
            succeeded.add(pn.id)
            # 구간을 **한 칸씩** 지나간다 — 통째로 밀면 중간 상태를 기다리던
            # 노드가 통째로 사라진다 (R3-6).
            for delay, to in machine.steps_after(pn.id):
                machine.enter(to, delay)
                drain()

    drain()


# ── not run 전파 ─────────────────────────────────────────────────────────────


def finalize(pipeline: Pipeline, result: RunResult, path: str) -> list[Finding]:
    """구동이 끝난 뒤 **남은 노드를 전수 검사해서** `not_run` 으로 바꾼다.

    **★ 모든 노드는 네 상태 중 정확히 하나에 들어간다** (R4-2). 여기를 지나면
    파이프라인의 모든 노드가 `result.outcomes` 에 있고 결과 1건씩을 낸다 —
    어느 상태에도 없이 리포트에서 사라지는 노드는 없다.

    | 경로 | 언제 |
    |---|---|
    | `data_dependency` | `inputs` 로 받는 노드가 실패했거나 그 자신이 not run 이다 |
    | `state_unreachable` | `when` 이 기다리는 상태로 가는 전이의 `after` 가 못 돌았다 |

    두 번째를 놓치기 쉽다. 전이는 **성공한 노드만** 민다.

    **config 가 도달성을 바꾸는 것은 정상이다** (R4-3). 등록 시점에는 `delay` 가
    `${config.X}` 라 순서를 모르지만, 실행 시점에는 config 가 풀렸으므로 실제 값으로
    전개된다. 그래서 못 닿은 노드는 등록 실패가 아니라 **`not_run`** 이다 —
    같은 파이프라인을 다른 Spec config 로 돌리면 도달성이 달라지는 게 설계다.

    파이프라인 자체가 성립하지 않아 구동에 못 들어간 경우는 **원인 노드가 없다** —
    `cause` 를 비운다. 그 자리의 오류는 노드에 귀속되지 않은 `Finding` 이 이미
    말하고 있고, 없는 원인을 지어내면 AI 가 엉뚱한 곳을 고친다.
    """
    by_id = {pn.id: pn for pn in pipeline.nodes}
    order = [pn.id for pn in pipeline.nodes]

    succeeded = {
        node_id
        for node_id, outcome in result.outcomes.items()
        if outcome.status in ("pass", "violation")
    }
    failed = {
        node_id
        for node_id, outcome in result.outcomes.items()
        if outcome.status == "error"
    }

    # 전이는 성공한 노드만 민다 — 초기 상태는 전이 없이도 처음부터 참이다.
    entered = {pipeline.states.initial}
    entered.update(t.to for t in pipeline.transitions if t.after in succeeded)

    causes: dict[str, NotRunCause] = {}
    changed = True
    while changed:
        changed = False
        dead = failed | set(causes)
        for node_id in order:
            if node_id in succeeded or node_id in failed or node_id in causes:
                continue
            pn = by_id[node_id]

            blocker = next((p for p in pn.inputs.values() if p in dead), "")
            if blocker:
                causes[node_id] = NotRunCause(node=blocker, reason="data_dependency")
                changed = True
                continue

            if pn.when is None:
                continue
            wait = pn.states.get(pn.when.state)
            if wait is None or wait in entered:
                continue
            blocker = next(
                (t.after for t in pipeline.transitions if t.to == wait and t.after in dead),
                "",
            )
            if blocker:
                causes[node_id] = NotRunCause(node=blocker, reason="state_unreachable")
                changed = True

    findings: list[Finding] = []
    for node_id in order:
        if node_id in succeeded or node_id in failed:
            continue
        cause = causes.get(node_id) or _residual_cause(by_id[node_id], succeeded)
        finding = Finding(status="not_run", path=path, node=node_id, cause=cause)
        findings.append(finding)
        if node_id not in result.outcomes:
            outcome = NodeOutcome(node_id, "not_run")
            outcome.findings = [finding]
            result.outcomes[node_id] = outcome
    return findings


def _residual_cause(pn: PipelineNode, succeeded: set[str]) -> NotRunCause | None:
    """앞의 두 경로로 설명되지 않은 미실행 노드의 원인.

    - 앞단이 아예 없는 노드 id 를 가리키는 경우 (`LNT-REF-003` 이 짚은 그 자리)
    - config 가 풀린 뒤 보니 `when` 상태에 못 닿은 경우 — **실행 시점 판정**이고
      등록 실패가 아니다 (R4-3)
    - 파이프라인 자체가 성립하지 않아 구동에 못 들어간 경우 → 원인 노드가 없다
    """
    missing = next((p for p in pn.inputs.values() if p not in succeeded), "")
    if missing:
        return NotRunCause(node=missing, reason="data_dependency")
    if pn.when is not None:
        return NotRunCause(node=pn.id, reason="state_unreachable")
    return None
