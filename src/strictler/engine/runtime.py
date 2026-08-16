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

**★ 구동 루프는 `engine.drive` 하나뿐이다** (MODULES.md R4-1).
`ready()` 재스캔·구간 전이 drain·선언 순서 tie-break·실행 시점 해시 대조가 전부
거기 있고 **`compare` 도 같은 것을 쓴다.** 여기에 복제해 두면 두 벌이 갈리고,
갈리는 순간 lint 결과 자체가 틀린다 (통과할 노드에 거짓 not run).

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
from strictler.checks.contracts import ScriptCache
from strictler.checks.node import dedupe, findings_of
from strictler.checks.script import ScriptContract
from strictler.engine import drive as drive_loop
from strictler.engine import exec as node_exec
from strictler.engine.result import NodeOutcome, RunResult
from strictler.engine.state import StateMachine
from strictler.errors import Finding, StrictlerError
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

    계약 캐시(`checks.contracts.ScriptCache`)는 **Spec 하나가 도는 동안** 산다.
    `plan` 항목들이 같은 파이프라인·노드를 쓰는 것이 흔하기 때문이다. 키가
    내용 해시라 도중에 파일이 바뀌면 그냥 빗나간다.
    """
    tool_findings = _check_tool_paths(spec, env, spec_name)
    if tool_findings:
        # `tool` 은 Spec 전체에 걸린 선언이다 — 경로가 안 서면 `STR-TOOL-002` 대조가
        # 통째로 무의미해지므로 그 지점에서 진행하지 않는다.
        return build_report(tool_findings)

    cache = ScriptCache(store)
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
                    cache=cache,
                )
            )
        except StrictlerError as exc:
            # 한 항목이 못 돌아도 다른 항목은 전부 돈다.
            findings.extend(findings_of(exc, path=_plan_path(spec_name, index, "")))
    return build_report(findings)


def _check_tool_paths(
    spec: Spec, env: Mapping[str, str], spec_name: str
) -> list[Finding]:
    """`tool.<name>.path` 도 경로 규칙을 탄다 (R6-8).

    **실행 시점이다** — `schema.md` 13절이 *"모든 경로가 전개 후 절대경로인지,
    참조 환경변수가 정의됐는지"* 를 Spec 실행 시 검증으로 두었다. 등록 시점에는
    실행 환경의 환경변수를 알 수 없으므로 `${env.X}` 를 쓴 정상 Spec 이 등록조차
    되지 못한다.

    **존재 여부는 보지 않는다.** 외부 도구는 사용자가 설치하고 경로만 받는 것이
    설계다 (`schema.md` 3절) — 여기서 보는 것은 경로 규칙뿐이다.
    """
    findings: list[Finding] = []
    for name, decl in spec.tool.items():
        where = " > ".join(part for part in (spec_name, f"tool.{name}") if part)
        try:
            refs.expand_path(decl.path, env)
        except StrictlerError as exc:
            findings.extend(findings_of(exc, path=where))
    return findings


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
    cache: ScriptCache | None = None,
) -> list[Finding]:
    """`plan` 항목 하나를 실행한다. `kind` 를 보고 값 검증/비교로 갈린다.

    `path` 필드는 `"login.json > plan[0] > login-flow"` 형태로 여기서 만들어진다.

    **`kind: compare` 분기는 여기서 지역 import 로 한다** — top-level 로 올리면
    `runtime` ↔ `compare` 순환이 된다.

    `cache` 를 안 주면 이 항목 동안만 사는 것을 만든다 — **두 파이프라인 종류가
    같은 것을 쓴다** (R4-1: 한쪽만 다르게 두면 실제로 갈린다).
    """
    cache = cache if cache is not None else ScriptCache(store)
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
                cache=cache,
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
        cache=cache,
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
    cache: ScriptCache | None = None,
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

    cache = cache if cache is not None else ScriptCache(store)
    findings = pipeline_checks.recheck_resolved(
        pipeline, config, store=store, env=env, source_path=path, cache=cache
    )
    if any(finding.status == "error" for finding in findings):
        return findings

    # ★ 지역 import — top-level 로 올리면 `runtime` ↔ `compare` 순환이다.
    from strictler.engine.compare import run_compare_pipeline

    result, compare_report = run_compare_pipeline(
        pipeline,
        config,
        store=store,
        env=env,
        started_at_ms=started_at_ms,
        path=path,
        cache=cache,
    )
    write_compare_report(compare_report, out)
    findings.extend(result.findings)
    return findings


# ── 파이프라인 구동 ──────────────────────────────────────────────────────────


class _NodeRun:
    """구동에 필요한 노드 한 벌 — 노드 정의 + 스크립트 경로 + 계약 + 배선된 라이브러리."""

    def __init__(
        self,
        node: Node,
        script_path: Path,
        contract: ScriptContract,
        libraries: dict[str, Path] | None = None,
    ) -> None:
        self.node = node
        self.script_path = script_path
        self.contract = contract
        self.libraries = libraries or {}
        """`{슬롯: 파일}`. `load_script` 가 로드 직전에 심는다 (`schema.md` 6.5절)."""


def run_pipeline(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    path: str,
    tool: Mapping[str, Any] | None = None,
    cache: ScriptCache | None = None,
) -> RunResult:
    """값 검증 파이프라인 한 벌을 구동한다.

    선언 순서로 돌면서 상태머신을 함께 전개한다. 노드가 실패하면 그 지점에서
    진행하지 않고, 끝난 뒤 `propagate_not_run()` 으로 여파를 표기한다.

    **조건 분기는 엔진 문법이 없다** — "앞단 결과가 이러면 아무것도 안 한다"는
    스크립트가 `input` 을 그대로 반환하는 것으로 표현된다. **엔진에는 skip 개념이 없다.**

    `tool` 은 Spec 의 `tool` 선언이다 — `STR-TOOL-001`/`-002` 는 **실행 시점** 규칙이라
    파이프라인만으로는 판정할 수 없다.

    `cache` 는 재검(①)과 로드(②)가 **같은 파일을 두 번 파싱하지 않게** 한다.
    """
    cache = cache if cache is not None else ScriptCache(store)
    result = RunResult()

    # ① config 가 풀린 뒤의 재검 (MODULES.md R3-4). 비교 파이프라인의 target 별
    #    스크립트는 등록 시점에 검사 자체가 불가능하므로 여기가 유일한 자리다.
    result.findings.extend(
        pipeline_checks.recheck_resolved(
            pipeline, config, store=store, env=env, source_path=path, cache=cache
        )
    )

    # ② 노드·스크립트 로드 + 등록소 무결성(해시 대조).
    loaded, load_findings = _load_nodes(
        pipeline, config, store=store, env=env, path=path, cache=cache
    )
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
        return _close(pipeline, result, path)

    registry, registry_findings = pipeline_checks.build_registry(
        [item.contract for item in loaded.values()], path
    )
    result.findings.extend(registry_findings)
    if registry is None:
        return _close(pipeline, result, path)

    try:
        machine = StateMachine(
            pipeline.states, pipeline.transitions, config, started_at_ms, env=env
        )
    except StrictlerError as exc:
        result.findings.extend(findings_of(exc, path=path))
        return _close(pipeline, result, path)

    drive_loop.drive(
        pipeline,
        machine=machine,
        runnable=loaded,
        run_node=lambda pn: _run_node(
            pn, loaded[pn.id], machine, registry, config, env, path, result
        ),
        result=result,
    )
    return _close(pipeline, result, path)


def _close(pipeline: Pipeline, result: RunResult, path: str) -> RunResult:
    """남은 노드를 `not_run` 으로 확정하고 결과를 정리한다.

    **어느 반환 경로로 나가든 여기를 지난다** — 그래야 파이프라인의 모든 노드가
    네 상태 중 정확히 하나에 들어간다 (R4-2). 중간에 그냥 `return` 하면 그 노드들이
    리포트에서 조용히 사라지고, 그건 거짓 리포트다.
    """
    result.findings.extend(drive_loop.finalize(pipeline, result, path))
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


def _run_node(
    pn: PipelineNode,
    item: _NodeRun,
    machine: StateMachine,
    registry: Any,
    config: Mapping[str, Any],
    env: Mapping[str, str],
    path: str,
    result: RunResult,
) -> NodeOutcome:
    """노드 하나를 실제로 돌린다. 실패는 전부 **오류**다 — 위반이 아니다."""
    contract = item.contract
    node_id = pn.id
    try:
        module = node_exec.load_script(item.script_path, item.libraries)

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
        # `config` → `state` → `env` 순으로 끝까지 전개한다 (R5-1). env 를 빠뜨리면
        # 검증은 전개된 절대경로를 보고 스크립트는 `${env.X}` 원문을 받는다.
        params = refs.expand_all(pn.params, config=config, state=snapshot, env=env)
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

    **정본은 등록 시점의 `checks.pipeline.check_ambiguous_input` 이다** (R5-3).
    파이프라인 JSON 만 보면 판정이 끝나므로 실행까지 미룰 이유가 없다.
    여기 남은 것은 **2선 방어**다 — 등록소를 거치지 않고 경로로 직접 가리킨
    파이프라인처럼 등록 검사를 안 지난 것이 들어올 수 있다.

    **규칙 id 를 붙인다.** 맨 `Finding` 으로 내면 리포트에서 기계적으로 특정할 수
    없고, 같은 사실이 자리에 따라 다른 모양으로 나온다.
    """
    return rules.finding(
        "STR-GRAPH-003",
        path=path,
        node=pn.id,
        fields={"nodes": ", ".join(producers)},
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


propagate_not_run = drive_loop.finalize
"""실패의 여파를 **전수 검사해서** `not_run` 으로 바꾼다 — 정본은 `engine.drive` 다.

값 검증과 비교가 **같은 전파 규칙**을 써야 하므로 여기에 복제하지 않는다 (R4-1)."""


# ── 로드 ─────────────────────────────────────────────────────────────────────


def _load_nodes(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
    cache: ScriptCache | None = None,
) -> tuple[dict[str, _NodeRun], list[Finding]]:
    """파이프라인의 노드들을 실제 파일까지 풀어 구동 재료를 만든다.

    **등록소 무결성은 여기서 본다** — 해시가 등록 당시와 다르면 `STR-REG-001`.
    정적 검사 루트를 피해 등록소 파일을 직접 고친 경우가 그것이다.
    계약·금지 검사는 `recheck_resolved` 가 이미 했으므로 여기서 다시 하지 않는다.
    """
    cache = cache if cache is not None else ScriptCache(store)
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
        findings.extend(
            drive_loop.verify_hash(node.script, store=store, path=path, node_id=pn.id)
        )

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
            contract, extracted = cache.contract(source, str(script_path))
        except StrictlerError as exc:
            findings.extend(findings_of(exc, path=path, node=pn.id))
            continue
        findings.extend(
            finding.model_copy(update={"path": path, "node": pn.id})
            for finding in extracted
        )

        # 배선된 라이브러리도 **실행 직전에 해시를 대조한다** — 노드 스크립트와
        # 같은 규칙이다 (`schema.md` 2·6.5절). 무단 수정된 라이브러리를 그냥
        # 돌리면 검증된 적 없는 판정 로직으로 리포트가 나간다.
        libraries, library_findings = drive_loop.resolve_libraries(
            node, store=store, env=env, path=path, node_id=pn.id
        )
        findings.extend(library_findings)
        if any(item.status == "error" for item in library_findings):
            # **못 푼 채로 돌리지 않는다.** 스크립트를 못 푼 경우와 같은 처리다 —
            # 억지로 로드하면 스크립트가 `ImportError` 로 죽으면서 *"배선이 없다"* 는
            # **거짓 안내**가 원인(파일이 없다) 위에 덮인다. 여파는 `not_run` 이다.
            continue
        loaded[pn.id] = _NodeRun(node, script_path, contract, libraries)

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
    source_path, findings = drive_loop.resolve_entry(
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
    """Spec `plan` 항목의 `source` 를 파이프라인 파일로 푼다.

    해석과 해시 대조는 `engine.drive` 가 한다 — `compare` 와 **같은 것**을 써야
    등록소 무결성 판정이 갈리지 않는다 (R4-1).
    """
    return drive_loop.resolve_entry(value, "pipeline", store=store, env=env, path=path)


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
