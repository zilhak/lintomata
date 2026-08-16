"""값 검증 파이프라인 구동과 Spec 단위 실행 (`schema.md` 9·11·13절).

**★ 이건 lint 다. 실행 파이프라인이 아니다.**
복구·재시도·되돌아가기·대체 경로를 **만들지 않는다.** 실패하면 그 지점에서 진행하지
않는다. 그게 전부다.

**실패는 최대한 수집하고, 여파는 not run 이다.**
한 번의 실행에서 확인 가능한 실패를 전부 모은다. 한 `plan` 항목이 실패해도
다른 항목은 전부 돈다. 단 실패 지점의 뒷단을 억지로 이어가면 **실패가 전파되어
원인이 뭉개지므로**, 도달 불가가 된 노드를 **전수 검사해서** 싹 다 `not_run` 으로 바꾼다.

**전파 경로가 둘이다:**

| 경로 | 내용 |
|---|---|
| **데이터 의존** | 실패한 노드의 출력을 `inputs` 로 받는 노드들 |
| **상태 의존** | **상태를 변경할 노드가 실패하면**, 그 상태에 조건이 걸린 노드들도 `not run` |

두 번째를 놓치기 쉽다. `transitions` 의 `after` 가 실패하면 그 전이가 일어나지 않고,
그 상태를 `when` 으로 기다리던 노드들은 영원히 조건을 만족하지 못한다.

**증거 캡처는 하지 않는다.** 위반은 정상 결과이므로 수습할 것이 없다 —
lint 가 스크린샷을 남기지 않는 것과 같다.

**★ 실행 순서는 파이프라인 `nodes` 선언 순서다** (MODULES.md R3-7).
`checks.reachability.simulate().order` 가 참조 구현이고 여기가 그 순서를 따른다 —
다르게 돌면 "등록은 통과했는데 실행에선 못 닿는다" 가 된다. 그래서 구동 루프는
`simulate()` 의 전개(선언 순서 tie-break + 전이 구간 한 칸씩 지나가기)를 **그대로**
옮겨 놓았다.

**★ `engine.compare` 를 top-level 로 import 하지 않는다.** 공용 결과 타입은
`engine.result` 에 있고 `compare` 도 거기에만 의존한다. `kind: compare` 디스패치는
`run_plan_item` **안에서 지역 import** 로 한다 — 양방향 top-level import 는
`ImportError` 로 터진다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from strictler import refs, rules
from strictler.checks import node as node_checks
from strictler.checks import pipeline as pipeline_checks
from strictler.checks import script as script_checks
from strictler.checks.node import dedupe, findings_of
from strictler.checks.script import ScriptContract
from strictler.engine import exec as node_exec
from strictler.engine.result import NodeOutcome, RunResult
from strictler.engine.state import StateMachine
from strictler.errors import Finding, NotRunCause, StrictlerError
from strictler.model import Node, NodeType, Pipeline, PipelineNode, Spec
from strictler.report import Report, build_report, write_compare_report
from strictler.store.entries import Store

__all__ = [
    "NodeOutcome",
    "RunResult",
    "VERDICT_PASSED",
    "VERDICT_RULE",
    "VERDICT_MESSAGE",
    "run_spec",
    "run_plan_item",
    "run_pipeline",
    "propagate_not_run",
    "topo_order",
]


VERDICT_PASSED = "passed"
"""Reckon 의 출력(`Verdict`)에서 **판정**을 담는 필드 이름. `bool`.

값 검증 파이프라인이 성립하려면 엔진이 Reckon 의 출력을 통과/위반으로 읽을 수
있어야 한다. 비교 파이프라인에서 **동등 비교를 엔진이 하는 것**과 같은 자리다 —
`schema.md` 12절: *"내장 동작 없음 원칙과 충돌하지 않는다. 동등 비교는 도메인
지식이 아니라 일반 연산이다."* 무엇이 통과인지의 **판단은 여전히 스크립트가** 하고,
엔진은 그 결론을 읽기만 한다."""

VERDICT_RULE = "rule"
"""위반일 때 리포트의 `rule` 자리에 나갈 이름. 없으면 비운다
(`schema.md` 11절 예시의 `"rule": "expectedCount"` — Reckon 이 낸 규칙 이름)."""

VERDICT_MESSAGE = "message"
"""위반일 때 리포트의 `message` 자리에 나갈 설명."""


# ── Spec ─────────────────────────────────────────────────────────────────────


def run_spec(
    spec: Spec,
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    spec_name: str = "",
) -> Report:
    """Spec 하나를 실행해 리포트를 만든다. `strictler check <spec-id>` 의 본체.

    실행 시 검증(`schema.md` 13절): config required 채움·타입, 경로 전개,
    `path: true` config, `tool` 선언, `kind: compare` 인데 `report` 없음,
    **등록소 파일 해시 대조**, 참조 id 삭제 여부.

    **한 `plan` 항목이 실패해도 다른 항목은 전부 돈다.**

    `spec_name` 은 리포트 `path` 의 첫 조각(`"login.json"`)이다. 등록소 항목 이름이든
    파일 이름이든 **부르는 쪽이 정한다** — Spec 문서 자체에는 자기 이름이 없다.
    """
    findings: list[Finding] = []
    for index in range(len(spec.plan)):
        try:
            findings.extend(
                run_plan_item(
                    spec,
                    index,
                    store=store,
                    env=env,
                    started_at_ms=started_at_ms,
                    spec_name=spec_name,
                )
            )
        except StrictlerError as exc:
            # 한 항목이 못 돌아도 다른 항목은 전부 돈다.
            findings.extend(findings_of(exc, path=_plan_path(spec_name, index, "")))
    return build_report(findings)


def _plan_path(spec_name: str, index: int, pipeline_name: str) -> str:
    """리포트의 위치 문자열 — `"login.json > plan[0] > login-flow"`."""
    parts = [part for part in (spec_name, f"plan[{index}]", pipeline_name) if part]
    return " > ".join(parts)


def run_plan_item(
    spec: Spec,
    index: int,
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    spec_name: str = "",
) -> list[Finding]:
    """`plan` 항목 하나를 실행한다. `kind` 를 보고 값 검증/비교로 갈린다.

    `path` 필드는 `"login.json > plan[0] > login-flow"` 형태로 여기서 만들어진다.

    **`kind: compare` 분기는 여기서 지역 import 로 한다** — top-level 로 올리면
    `runtime` ↔ `compare` 순환이 된다.
    """
    item = spec.plan[index]
    where = _plan_path(spec_name, index, "")

    source_path, findings = _resolve_pipeline(item.source, store=store, env=env, path=where)
    if source_path is None:
        return findings

    raw, read_findings = _read_json(source_path, where, "파이프라인")
    findings.extend(read_findings)
    if raw is None:
        return findings

    pipeline, load_findings = pipeline_checks.load_pipeline(raw, str(source_path))
    findings.extend(
        finding.model_copy(update={"path": where}) for finding in load_findings
    )
    if pipeline is None:
        return findings

    path = _plan_path(spec_name, index, pipeline.info.name)
    config, config_findings = pipeline_checks.check_config_values(
        pipeline, item.config, path, env=env
    )
    findings.extend(config_findings)
    if any(finding.status == "error" for finding in config_findings):
        # config 가 안 풀리면 그 뒤는 전부 추측이 된다 — 그 지점에서 진행하지 않는다.
        return findings

    if pipeline.info.kind == "compare":
        findings.extend(
            _run_compare(
                pipeline,
                item.report,
                config,
                store=store,
                env=env,
                started_at_ms=started_at_ms,
                path=path,
            )
        )
        return findings

    result = run_pipeline(
        pipeline,
        config,
        store=store,
        env=env,
        started_at_ms=started_at_ms,
        path=path,
        tool=spec.tool,
    )
    findings.extend(result.findings)
    return findings


def _run_compare(
    pipeline: Pipeline,
    report_target: str | None,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    path: str,
) -> list[Finding]:
    """비교 파이프라인 디스패치 (`schema.md` 12절).

    **리포트 출력 위치는 Spec `plan` 항목의 `report` 다** — 없으면 `STR-CMP-001`.
    비교 파이프라인은 실행과 동시에 결과 리포트를 쌓으므로 쌓을 자리가 없으면
    실행할 이유가 없다.

    **`recheck_resolved` 를 여기서도 부른다** (MODULES.md R3-4). `STR-CMP-002` 와
    target 별 스크립트의 계약·금지 검사는 config 가 풀린 지금이 **유일한 자리**다 —
    비교 파이프라인이야말로 그 재검이 신설된 이유다.
    """
    if not report_target:
        return [rules.finding("STR-CMP-001", path=path)]
    try:
        out = refs.expand_path(report_target, env)
    except StrictlerError as exc:
        return findings_of(exc, path=path)

    findings = pipeline_checks.recheck_resolved(
        pipeline, config, store=store, env=env, source_path=path
    )
    if any(finding.status == "error" for finding in findings):
        return findings

    # ★ 지역 import — top-level 로 올리면 `runtime` ↔ `compare` 순환이다.
    from strictler.engine.compare import run_compare_pipeline

    result, compare_report = run_compare_pipeline(
        pipeline, config, store=store, env=env, started_at_ms=started_at_ms, path=path
    )
    write_compare_report(compare_report, out)
    findings.extend(result.findings)
    return findings


# ── 파이프라인 구동 ──────────────────────────────────────────────────────────


class _NodeRun:
    """구동에 필요한 노드 한 벌 — 노드 정의 + 스크립트 경로 + 계약."""

    def __init__(self, node: Node, script_path: Path, contract: ScriptContract) -> None:
        self.node = node
        self.script_path = script_path
        self.contract = contract


def run_pipeline(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    path: str,
    tool: Mapping[str, Any] | None = None,
) -> RunResult:
    """값 검증 파이프라인 한 벌을 구동한다.

    선언 순서로 돌면서 상태머신을 함께 전개한다. 노드가 실패하면 그 지점에서
    진행하지 않고, 끝난 뒤 `propagate_not_run()` 으로 여파를 표기한다.

    **조건 분기는 엔진 문법이 없다** — "앞단 결과가 이러면 아무것도 안 한다"는
    스크립트가 `input` 을 그대로 반환하는 것으로 표현된다. **엔진에는 skip 개념이 없다.**

    `tool` 은 Spec 의 `tool` 선언이다 — `STR-TOOL-001`/`-002` 는 **실행 시점** 규칙이라
    파이프라인만으로는 판정할 수 없다.
    """
    result = RunResult()

    # ① config 가 풀린 뒤의 재검 (MODULES.md R3-4). 비교 파이프라인의 target 별
    #    스크립트는 등록 시점에 검사 자체가 불가능하므로 여기가 유일한 자리다.
    result.findings.extend(
        pipeline_checks.recheck_resolved(
            pipeline, config, store=store, env=env, source_path=path
        )
    )

    # ② 노드·스크립트 로드 + 등록소 무결성(해시 대조).
    loaded, load_findings = _load_nodes(pipeline, config, store=store, env=env, path=path)
    result.findings.extend(load_findings)

    # ③ `tool` 대조 — 실행 시점 규칙.
    if tool:
        for node_id, item in loaded.items():
            result.findings.extend(
                finding.model_copy(update={"path": path, "node": node_id})
                for finding in script_checks.check_tool_calls(item.contract, dict(tool))
            )

    # ④ 정적으로 막힌 노드는 돌리지 않는다 — 여파는 not run 이다.
    for node_id in _broken_nodes(pipeline, loaded, result.findings):
        result.outcomes[node_id] = NodeOutcome(node_id, "error")

    if any(finding.status == "error" and not finding.node for finding in result.findings):
        # 노드에 귀속되지 않은 오류 = 파이프라인 자체가 성립하지 않는다.
        result.findings.extend(propagate_not_run(pipeline, result, path))
        result.findings = dedupe(result.findings)
        return result

    registry, registry_findings = pipeline_checks.build_registry(
        [item.contract for item in loaded.values()], path
    )
    result.findings.extend(registry_findings)
    if registry is None:
        result.findings = dedupe(result.findings)
        return result

    try:
        machine = StateMachine(pipeline.states, pipeline.transitions, config, started_at_ms)
    except StrictlerError as exc:
        result.findings.extend(findings_of(exc, path=path))
        result.findings = dedupe(result.findings)
        return result

    _drive(pipeline, loaded, machine, registry, config, path, result)
    result.findings.extend(propagate_not_run(pipeline, result, path))
    result.findings = dedupe(result.findings)
    return result


def _broken_nodes(
    pipeline: Pipeline, loaded: Mapping[str, _NodeRun], findings: list[Finding]
) -> list[str]:
    """돌릴 수 없는 노드들 — 로드 실패했거나 정적 오류가 귀속된 노드."""
    broken = {
        finding.node
        for finding in findings
        if finding.status == "error" and finding.node
    }
    broken |= {pn.id for pn in pipeline.nodes if pn.id not in loaded}
    return [pn.id for pn in pipeline.nodes if pn.id in broken]


def _drive(
    pipeline: Pipeline,
    loaded: Mapping[str, _NodeRun],
    machine: StateMachine,
    registry: Any,
    config: Mapping[str, Any],
    path: str,
    result: RunResult,
) -> None:
    """전개 — `checks.reachability.simulate()` 와 **같은 규칙**으로 돈다 (R3-7).

    1. 아직 안 돈 노드를 **선언 순서대로** 훑어 첫 번째 실행 가능한 것을 집는다
    2. 그 노드를 돌리고, 성공하면 그 노드를 `after` 로 삼는 전이 구간을 지나간다
    3. 지나가는 **각 상태마다** 1 로 되돌아가 그 자리에서 실행 가능해진 노드를 소진한다

    실패한 노드는 **전이를 밀지 않는다** — 그게 not run 의 두 번째 경로다.
    """
    declared = set(pipeline.states.values)
    done: set[str] = set(result.outcomes)
    succeeded: set[str] = set()

    def waits_for(pn: PipelineNode) -> str | None:
        """이 노드가 기다리는 파이프라인 상태. 번역 불가면 제약 없음으로 본다.

        번역이 안 되는 것은 `STR-STATE-002`/`-003`/`-004` 가 등록 시점에 이미
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
            if pn.id in done or pn.id not in loaded:
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
            outcome = _run_node(pn, loaded[pn.id], machine, registry, config, path, result)
            result.outcomes[pn.id] = outcome
            result.findings.extend(outcome.findings)
            if outcome.status == "error":
                continue  # 실패한 노드는 전이를 밀지 않는다
            succeeded.add(pn.id)
            for delay, to in machine.steps_after(pn.id):
                machine.enter(to, delay)
                drain()

    drain()


def _run_node(
    pn: PipelineNode,
    item: _NodeRun,
    machine: StateMachine,
    registry: Any,
    config: Mapping[str, Any],
    path: str,
    result: RunResult,
) -> NodeOutcome:
    """노드 하나를 실제로 돌린다. 실패는 전부 **오류**다 — 위반이 아니다."""
    contract = item.contract
    node_id = pn.id
    try:
        module = node_exec.load_script(item.script_path)

        # 같은 노드를 두 이름으로 받아도 값은 하나다 — 중복은 걷어낸다.
        producers = list(dict.fromkeys(pn.inputs.values()))
        if len(producers) > 1:
            return _errored(node_id, [_ambiguous_input(pn, producers, path)])
        input_value = result.outcomes[producers[0]].value if producers else None

        if input_value is not None:
            mismatched = node_exec.validate_input(
                contract, input_value, registry, path=path, node=node_id
            )
            if mismatched:
                return _errored(node_id, mismatched)

        snapshot = machine.snapshot(pn.states)
        params = refs.expand_state(refs.expand_config(pn.params, config), snapshot)
        args = node_exec.build_args(
            module, contract, input_value=input_value, params=params, state=snapshot
        )
        output = node_exec.invoke(module, args)
    except StrictlerError as exc:
        return _errored(node_id, findings_of(exc, path=path, node=node_id))

    mismatched = node_exec.validate_output(
        contract, output, registry, path=path, node=node_id
    )
    if mismatched:
        return _errored(node_id, mismatched)

    finding = _node_finding(node_id, item.node.type, output, path)
    if finding.status == "error":
        return _errored(node_id, [finding])
    outcome = NodeOutcome(node_id, finding.status)
    outcome.value = output
    outcome.findings = [finding]
    return outcome


def _ambiguous_input(pn: PipelineNode, producers: list[str], path: str) -> Finding:
    """서로 다른 앞단 노드를 둘 이상 받았다 — **어느 것이 `Args.input` 인지 모른다.**

    `Args.input` 은 필드 **하나**이고 (`schema.md` 6절) `check_wiring_types` 는
    `inputs` 하나하나를 그 하나와 대조한다. 그래서 서로 다른 앞단이 둘 이상이면
    타입은 통과해도 값은 하나만 들어가고 나머지는 조용히 사라진다.
    **조용히 하나를 고르면 거짓 리포트**가 되므로 오류로 낸다.
    """
    return Finding(
        status="error",
        path=path,
        node=pn.id,
        message=(
            f"서로 다른 앞단 노드를 둘 이상 받았습니다: {', '.join(producers)}\n"
            "`Args.input` 은 필드 하나라 값도 하나만 받을 수 있습니다. 앞단을 하나로 "
            "줄이거나, 여럿을 합쳐야 한다면 그 합치는 일을 하는 노드를 앞에 두고 "
            "그 출력을 받으세요."
        ),
    )


def _errored(node_id: str, findings: list[Finding]) -> NodeOutcome:
    outcome = NodeOutcome(node_id, "error")
    outcome.findings = list(findings)
    return outcome


def _node_finding(node_id: str, node_type: NodeType, output: Any, path: str) -> Finding:
    """노드 하나의 결과 1건. **Reckon 만 위반을 낼 수 있다.**

    나머지 네 타입은 기획과 대조하지 않으므로 (`schema.md` 5절) 돌아간 것 자체가
    통과다. Reckon 의 출력에서 `passed` 를 읽어 통과/위반을 가른다.
    """
    if node_type != "reckon":
        return Finding(status="pass", path=path, node=node_id)

    try:
        data = node_exec.as_mapping(output)
    except StrictlerError as exc:
        return Finding(status="error", path=path, node=node_id, message=exc.message)

    if VERDICT_PASSED not in data or not isinstance(data[VERDICT_PASSED], bool):
        return Finding(
            status="error",
            path=path,
            node=node_id,
            message=(
                f"Reckon 의 출력에 `{VERDICT_PASSED}: bool` 필드가 없습니다 "
                f"(필드: {', '.join(sorted(data)) or '(없음)'})\n"
                f"Reckon 은 판정을 내놓는 노드이므로 반환 dataclass 에 "
                f"`{VERDICT_PASSED}: bool` 을 두어야 엔진이 통과/위반을 읽을 수 "
                f"있습니다. 위반 설명은 `{VERDICT_MESSAGE}: str`, 규칙 이름은 "
                f"`{VERDICT_RULE}: str` 로 함께 내보내면 리포트에 그대로 실립니다. "
                "**판단은 스크립트가 하고 엔진은 그 결론을 읽기만 합니다.**"
            ),
        )

    if data[VERDICT_PASSED]:
        return Finding(status="pass", path=path, node=node_id)

    rule_name = data.get(VERDICT_RULE, "")
    message = data.get(VERDICT_MESSAGE, "")
    return Finding(
        status="violation",
        path=path,
        node=node_id,
        rule_id=str(rule_name) if rule_name else "",
        message=str(message) if message else _default_violation_message(data),
    )


def _default_violation_message(data: Mapping[str, Any]) -> str:
    """Reckon 이 설명을 안 붙였을 때의 최소 문구.

    **비워 두지 않는다** — 사람이 읽는 것은 AI 요약이고, 요약할 것이 없으면
    "어떤 규칙인지" 가 전달되지 않는다 (`CLAUDE.md` 의도 필드 절).
    """
    shown = ", ".join(f"{k}={v!r}" for k, v in sorted(data.items()) if k != VERDICT_PASSED)
    return (
        f"기획과 다릅니다. Verdict: {shown or '(설명 필드 없음)'}\n"
        f"Reckon 의 반환 dataclass 에 `{VERDICT_MESSAGE}: str` 을 두면 이 자리에 "
        "그 문구가 그대로 실립니다."
    )


# ── not run 전파 ─────────────────────────────────────────────────────────────


def propagate_not_run(
    pipeline: Pipeline,
    result: RunResult,
    path: str,
) -> list[Finding]:
    """실패의 여파를 **전수 검사해서** `not_run` 으로 바꾼다 (`schema.md` 9절).

    데이터 의존과 상태 의존 두 경로를 모두 훑는다. **원인 노드는 바꾸는 그 시점에
    적는다** — `Finding.cause` 에 `{node, reason}`.

    | 경로 | 언제 |
    |---|---|
    | `data_dependency` | `inputs` 로 받는 노드가 실패했거나 그 자신이 not run 이다 |
    | `state_unreachable` | `when` 이 기다리는 상태로 가는 전이의 `after` 가 못 돌았다 |

    두 번째를 놓치기 쉽다. 전이는 **성공한 노드만** 민다 — 실패한 노드의 전이는
    일어나지 않고, 그 상태를 기다리던 노드는 영원히 조건을 못 만족한다.

    **여파가 아닌 것은 표기하지 않는다.** 원인을 짚을 수 없는 미실행 노드는
    구성 자체가 잘못된 경우인데, 그건 등록 시점의 `STR-STATE-007` 자리다.
    """
    by_id = {pn.id: pn for pn in pipeline.nodes}
    order = [pn.id for pn in pipeline.nodes]

    succeeded = {
        node_id
        for node_id, outcome in result.outcomes.items()
        if outcome.status in ("pass", "violation")
    }
    failed = {
        node_id for node_id, outcome in result.outcomes.items() if outcome.status == "error"
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

    return [
        Finding(status="not_run", path=path, node=node_id, cause=causes[node_id])
        for node_id in order
        if node_id in causes
    ]


def topo_order(dag: dict[str, list[str]]) -> list[str]:
    """의존 순서. 순환은 등록 시 이미 걸러졌으므로 여기선 없다고 본다.

    **동시에 가능한 것은 선언 순서**로 집는다 (R3-7) — `dag` 의 키 순서가 곧
    파이프라인의 `nodes` 선언 순서다 (`checks.pipeline.build_dag`).
    """
    order: list[str] = []
    done: set[str] = set()
    while len(done) < len(dag):
        picked = None
        for node_id, deps in dag.items():
            if node_id in done:
                continue
            if all(dep in done or dep not in dag for dep in deps):
                picked = node_id
                break
        if picked is None:
            break  # 순환 — `STR-GRAPH-001` 이 등록 시점에 이미 잡았다
        done.add(picked)
        order.append(picked)
    return order


# ── 로드 ─────────────────────────────────────────────────────────────────────


def _load_nodes(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
) -> tuple[dict[str, _NodeRun], list[Finding]]:
    """파이프라인의 노드들을 실제 파일까지 풀어 구동 재료를 만든다.

    **등록소 무결성은 여기서 본다** — 해시가 등록 당시와 다르면 `STR-REG-001`.
    정적 검사 루트를 피해 등록소 파일을 직접 고친 경우가 그것이다.
    계약·금지 검사는 `recheck_resolved` 가 이미 했으므로 여기서 다시 하지 않는다.
    """
    loaded: dict[str, _NodeRun] = {}
    findings: list[Finding] = []

    for pn in pipeline.nodes:
        node, node_findings = _load_node(
            pn.source, store=store, env=env, path=path, node_id=pn.id
        )
        findings.extend(node_findings)
        if node is None:
            continue

        script_path, raw_findings = node_checks.resolve_script(
            node, store=store, env=env, config=config, target=""
        )
        findings.extend(
            finding.model_copy(
                update={"path": finding.path or path, "node": finding.node or pn.id}
            )
            for finding in raw_findings
        )
        if script_path is None:
            continue
        findings.extend(_verify_hash(node.script, store=store, path=path, node_id=pn.id))

        try:
            source = script_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                Finding(
                    status="error",
                    path=path,
                    node=pn.id,
                    message=(
                        f"스크립트를 읽을 수 없습니다: {script_path} ({exc})\n"
                        "노드 스크립트는 Python 소스이고 UTF-8 이어야 합니다."
                    ),
                )
            )
            continue

        try:
            contract, extracted = script_checks.extract_contract(source, str(script_path))
        except StrictlerError as exc:
            findings.extend(findings_of(exc, path=path, node=pn.id))
            continue
        findings.extend(
            finding.model_copy(update={"path": path, "node": pn.id})
            for finding in extracted
        )
        loaded[pn.id] = _NodeRun(node, script_path, contract)

    return loaded, findings


def _load_node(
    value: str,
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
    node_id: str,
) -> tuple[Node | None, list[Finding]]:
    """파이프라인 노드 항목의 `source` 를 실제 노드 정의로 로드한다."""
    source_path, findings = _resolve_entry(
        value, "node", store=store, env=env, path=path, node_id=node_id
    )
    if source_path is None:
        return None, findings
    raw, read_findings = _read_json(source_path, path, "노드", node_id=node_id)
    findings.extend(read_findings)
    if raw is None:
        return None, findings
    node, load_findings = node_checks.load_node(raw, str(source_path))
    findings.extend(
        finding.model_copy(update={"path": path, "node": node_id})
        for finding in load_findings
    )
    return node, findings


def _resolve_pipeline(
    value: str, *, store: Store, env: Mapping[str, str], path: str
) -> tuple[Path | None, list[Finding]]:
    """Spec `plan` 항목의 `source` 를 파이프라인 파일로 푼다."""
    return _resolve_entry(value, "pipeline", store=store, env=env, path=path, node_id="")


def _resolve_entry(
    value: str,
    kind: Any,
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
    node_id: str,
) -> tuple[Path | None, list[Finding]]:
    """`${ref.<id>}` 또는 경로를 실제 파일로 푼다 — **해시 대조까지** 한다.

    `STR-REG-002`(삭제된 id) / `STR-REG-001`(등록 이후 직접 수정) 는 **실행 시점**
    규칙이다 (`schema.md` 13절 — 등록소 무결성).
    """
    if refs.is_ref(value):
        try:
            refs.parse_ref(value, kind)
        except StrictlerError as exc:
            return None, findings_of(exc, path=path, node=node_id)
        entry_id = value[len("${ref.") : -1]
        try:
            store.show(entry_id)
        except StrictlerError:
            return None, [
                rules.finding(
                    "STR-REG-002", path=path, node=node_id, fields={"id": entry_id}
                )
            ]
        if not store.verify_hash(entry_id):
            return None, [
                rules.finding(
                    "STR-REG-001", path=path, node=node_id, fields={"id": entry_id}
                )
            ]
        return store.path_of(entry_id), []

    try:
        resolved = refs.expand_path(value, env)
    except StrictlerError as exc:
        return None, findings_of(exc, path=path, node=node_id)
    if not resolved.is_file():
        return None, [
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=(
                    f"파일이 없습니다: {resolved}\n"
                    f"원본: {value!r}. 경로가 맞는지, 참조한 환경변수 값이 맞는지 "
                    "확인하세요."
                ),
            )
        ]
    return resolved, []


def _verify_hash(
    value: str, *, store: Store, path: str, node_id: str
) -> list[Finding]:
    """`${ref.<id>}` 로 참조한 등록소 파일의 해시를 대조한다 (`STR-REG-001`)."""
    if not refs.is_ref(value):
        return []
    entry_id = value[len("${ref.") : -1]
    try:
        store.show(entry_id)
    except StrictlerError:
        return []  # 삭제는 `resolve_script` 가 `STR-REG-002` 로 이미 짚었다
    if store.verify_hash(entry_id):
        return []
    return [rules.finding("STR-REG-001", path=path, node=node_id, fields={"id": entry_id})]


def _read_json(
    source_path: Path, path: str, label: str, node_id: str = ""
) -> tuple[dict[str, Any] | None, list[Finding]]:
    """JSON 파일 하나를 읽는다. 읽기 실패는 위반이 아니라 **오류**다."""
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=(
                    f"{label} 파일을 읽을 수 없습니다: {source_path} ({exc})\n"
                    f"{label} 파일은 UTF-8 JSON 이어야 합니다."
                ),
            )
        ]
    if not isinstance(raw, dict):
        return None, [
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=(
                    f"{label} 파일의 최상위가 객체가 아닙니다: {source_path}\n"
                    f"`schema.md` 의 {label} 구조를 그대로 따르세요."
                ),
            )
        ]
    return raw, []
