"""비교 파이프라인 구동 — 프로그램 ↔ 프로그램 동일성 검증 (`schema.md` 12절).

**노드도 그래프도 한 벌이다.** 동일 노드를 여러 벌의 형상에 적용하는 것이고,
**target 별로 갈리는 것은 스크립트와 그 스크립트가 쓰는 값(`params`) 뿐이다.**

| | 갈리나 | 왜 |
|---|---|---|
| `Args.input` / 출력 타입 | **공통** | 파이프라인 구동 개념이다. 노드에 귀속되므로 갈릴 수 없다 |
| `Args.state` | **공통** | 같은 이유 |
| `script` 경로 | **갈림** | 인식 방법이 A/B 마다 다른 것이 설계다 |
| `Args.params` | **갈림** | 스크립트가 갈라지니 거기 필요한 값도 갈라진다 |

### 실행 방식

노드가 실행되면 **내부적으로 target 별 스크립트를 각각 실행**하고, **결과 전부를
취합해 다음 노드로 넘긴다.** 다음 노드는 그 묶음을 받아 target 마다 자기 스크립트를 또 실행한다.

**취합/분배는 엔진이 한다.** 스크립트는 자기 target 의 값 하나만 받고 하나만 내놓는다
→ **스크립트의 모양이 값 검증 파이프라인과 완전히 같다.**

### 비교와 Verdict

**Reckon 이 필요 없다** — Verdict 를 엔진이 만든다. "내장 동작 없음" 원칙과 충돌하지
않는다: **동등 비교는 도메인 지식이 아니라 일반 연산**이다.

**위반 판정은 `targets` 목록 전부가 같은 값을 뱉느냐**이지 짝지어 비교하는 것이 아니다.
하나만 어긋나도 위반. **"동일하다"는 정말로 동일하다는 뜻이다** — 허용 오차도 무시
필드도 엔진에 두지 않는다. 정규화는 스크립트가 알아서 한다. **엔진은 `==` 만 안다.**

### ★ 이건 lint 다

**위반은 정상 결과다.** 값이 갈렸다고 뒷단을 멈추지 않는다 — 노드는 멀쩡히 값을
내놨고, 한 번의 실행에서 확인 가능한 차이를 **전부 모으는** 것이 목적이다.
뒷단을 끊는 것은 **오류**(스크립트 예외·계약 위반)뿐이고, 그 여파는 `not_run` 이다.
복구·재시도·대체 경로는 없다.

**★ `engine.runtime` 을 import 하지 마라.** 공용 결과 타입(`RunResult`/`NodeOutcome`)은
`engine.result` 에 있다. `runtime` 이 `kind` 를 보고 이쪽으로 디스패치하므로,
반대 방향 import 를 만들면 순환이 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from strictler import refs, rules
from strictler.checks import node as node_checks
from strictler.checks import pipeline as pipeline_checks
from strictler.checks import script as script_checks
from strictler.checks.script import ScriptContract
from strictler.engine import exec as node_exec
from strictler.engine.result import NodeOutcome, RunResult
from strictler.engine.state import StateMachine
from strictler.errors import Finding, NotRunCause, StrictlerError
from strictler.model import Node, Pipeline, PipelineNode
from strictler.report import CompareReport, build_compare_report
from strictler.store.entries import Store
from strictler.typesys.registry import TypeKey, TypeRegistry

__all__ = [
    "resolve_target_config",
    "run_compare_pipeline",
    "collect_target_values",
    "all_same",
]


def resolve_target_config(config: Mapping[str, Any], target: str) -> dict[str, Any]:
    """target `T` 로 도는 동안의 config 를 만든다.

    **`targets.T` 에서 먼저 찾고, 없으면 공통에서** 찾는다 — 그 우선순위를 **병합
    순서**로 굳힌다. 공통 위에 `targets.T` 오버레이를 얹은 평평한 매핑이 결과다.
    `targets` 키 자체는 config 값이 아니라 오버레이 서랍이므로 결과에서 뺀다.

    **둘 다 없으면 `STR-CMP-004`** — 그 판정은 값을 실제로 찾는 시점, 즉
    `refs.expand_config(값, 이_매핑, target)` 안에서 난다. `target` 을 계속 함께
    넘기기 때문에 없는 이름은 `STR-CONFIG-001` 이 아니라 `STR-CMP-004` 로 나온다.
    """
    merged = {key: value for key, value in config.items() if key != "targets"}
    drawer = config.get("targets")
    if isinstance(drawer, Mapping):
        overlay = drawer.get(target)
        if isinstance(overlay, Mapping):
            merged.update(overlay)
    return merged


def run_compare_pipeline(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    path: str,
) -> tuple[RunResult, CompareReport]:
    """비교 파이프라인 한 벌을 구동한다.

    노드마다 target 별 스크립트를 전부 돌리고 결과를 취합한다. `compare` 에 적힌
    노드의 취합 결과가 target 간 동일한지 엔진이 비교해 Verdict 를 만든다.

    **실행과 동시에 결과 리포트를 쌓는다** — 무엇이 어디서 어떻게 달랐는지.
    출력 위치는 Spec `plan` 항목의 `report` 이고, 파일로 쓰는 것은 부르는 쪽이다.
    """
    result = RunResult()

    if pipeline.info.kind != "compare":
        result.findings.append(
            Finding(
                status="error",
                path=path,
                message=(
                    f"비교 엔진이 `kind: {pipeline.info.kind}` 파이프라인을 받았습니다.\n"
                    "비교 구동은 `info.kind` 가 `compare` 인 파이프라인 전용입니다. "
                    "값 검증 파이프라인은 값 검증 엔진으로 돌리세요."
                ),
            )
        )
        return result, build_compare_report({})

    targets = list(pipeline.targets)
    if len(targets) < 2:
        result.findings.append(
            rules.finding("STR-CMP-003", path=path, fields={"count": len(targets)})
        )
        return result, build_compare_report({})

    target_configs = {name: resolve_target_config(config, name) for name in targets}

    prepared, prep_findings = _prepare(
        pipeline, targets, target_configs, store=store, env=env, path=path
    )
    result.findings.extend(prep_findings)
    if prepared is None:
        return result, build_compare_report({})

    values = _walk(
        pipeline,
        targets,
        target_configs,
        prepared=prepared,
        result=result,
        # 전이 지연은 그래프의 성질이라 target 별로 갈리지 않는다 — 공통 config 다.
        common=resolve_target_config(config, ""),
        started_at_ms=started_at_ms,
        path=path,
    )
    return result, build_compare_report(values)


def collect_target_values(result: RunResult, node_id: str) -> dict[str, Any]:
    """한 노드의 `{target: 출력값}` 을 꺼낸다.

    돌지 않은 노드(`not_run`)나 오류로 끝난 노드는 묶음이 없다 — 빈 매핑이다.
    """
    outcome = result.outcomes.get(node_id)
    if outcome is None or not isinstance(outcome.value, Mapping):
        return {}
    return dict(outcome.value)


def all_same(values: Mapping[str, Any]) -> bool:
    """전부 같은 값인지. **엔진은 `==` 만 안다.**

    "둘을 짝지어 비교"가 아니라 **전체가 한 값으로 일치하느냐**를 묻는다. 그래서
    대상이 셋이든 열이든 판정 방식이 같고, 하나만 어긋나면 위반이다.
    비교는 `Percept` 층에서 한다 — `Sensum` 은 비교 대상이 아니다.
    """
    outputs = list(values.values())
    return all(item == outputs[0] for item in outputs[1:])


# ── 준비 — 노드 한 벌 + target 별 스크립트 ────────────────────────────────────


class _Prepared:
    """구동에 필요한 것들. 노드는 한 벌, 스크립트만 target 별로 갈린다."""

    def __init__(self) -> None:
        self.nodes: dict[str, PipelineNode] = {}
        self.scripts: dict[str, dict[str, tuple[Path, ScriptContract]]] = {}
        self.registry: TypeRegistry | None = None


def _prepare(
    pipeline: Pipeline,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
) -> tuple[_Prepared | None, list[Finding]]:
    """노드를 한 벌 로드하고 target 별로 실제 도는 스크립트를 푼다."""
    findings: list[Finding] = []
    prepared = _Prepared()
    contracts: list[ScriptContract] = []

    for pn in pipeline.nodes:
        prepared.nodes[pn.id] = pn
        # 노드 파일을 푸는 규칙(경로·`${ref.nd_}`·REG/REF 판정)은 파이프라인 검사와
        # 같은 것을 써야 한다. 여기서 복제하면 두 벌이 갈린다.
        node, load_findings = pipeline_checks._load_referenced_node(
            pn.source, store=store, env=env, source_path=path, node_id=pn.id
        )
        findings.extend(load_findings)
        if node is None:
            continue
        for target in targets:
            resolved, gathered = _resolve_one(
                node,
                node_id=pn.id,
                target=target,
                config=target_configs[target],
                store=store,
                env=env,
                path=path,
            )
            findings.extend(gathered)
            if resolved is None:
                continue
            prepared.scripts.setdefault(pn.id, {})[target] = resolved
            contracts.append(resolved[1])

    # 여기서 멈추지 않는다. 못 푼 노드는 제 자리에서 `error` 가 되고 그 여파가
    # `not_run` 으로 퍼진다 — **실패는 최대한 수집한다** (`schema.md` 9절).
    registry, registry_findings = pipeline_checks.build_registry(contracts, path)
    findings.extend(registry_findings)
    if registry is None:
        return None, findings
    prepared.registry = registry
    return prepared, findings


def _resolve_one(
    node: Node,
    *,
    node_id: str,
    target: str,
    config: Mapping[str, Any],
    store: Store,
    env: Mapping[str, str],
    path: str,
) -> tuple[tuple[Path, ScriptContract] | None, list[Finding]]:
    """이 target 에서 실제로 도는 스크립트 경로와 그 계약."""
    script_path, raw = node_checks.resolve_script(
        node, store=store, env=env, config=config, target=target
    )
    findings = [
        item.model_copy(
            update={"path": item.path or path, "node": item.node or node_id}
        )
        for item in raw
    ]
    if script_path is None:
        if not findings:
            findings.append(
                Finding(
                    status="error",
                    path=path,
                    node=node_id,
                    message=(
                        f"실행 시점인데 노드의 `script` 가 아직 안 풀렸습니다: "
                        f"{node.script!r} (target: {target})\n"
                        "Spec 의 `config.targets.<이름>` 또는 공통 `config` 에서 "
                        "이 값을 채우세요."
                    ),
                )
            )
        return None, findings

    try:
        source = script_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        findings.append(
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=(
                    f"스크립트를 읽을 수 없습니다: {script_path} ({exc})\n"
                    "노드 스크립트는 Python 소스이고 UTF-8 이어야 합니다."
                ),
            )
        )
        return None, findings

    try:
        contract, extracted = script_checks.extract_contract(source, str(script_path))
    except StrictlerError as exc:
        # 파싱이 안 되는 것은 위반이 아니라 검사기가 못 돈 것이다.
        findings.extend(node_checks.findings_of(exc, path=path, node=node_id))
        return None, findings
    findings.extend(
        item.model_copy(update={"path": item.path or path, "node": item.node or node_id})
        for item in extracted
    )
    if any(item.status == "error" for item in extracted):
        return None, findings
    return (script_path, contract), findings


# ── 구동 ─────────────────────────────────────────────────────────────────────


def _walk(
    pipeline: Pipeline,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    prepared: _Prepared,
    result: RunResult,
    common: Mapping[str, Any],
    started_at_ms: int,
    path: str,
) -> dict[str, dict[str, Any]]:
    """DAG 를 훑으며 노드마다 target 전부를 돌리고 취합한다."""
    machine = StateMachine(
        pipeline.states, list(pipeline.transitions), common, started_at_ms
    )
    dag = pipeline_checks.build_dag(pipeline)
    compare_ids = set(pipeline.compare)
    values: dict[str, dict[str, Any]] = {}
    # 상태 의존 `not_run` 의 원인 추적 — 실패한 노드가 밀지 못한 상태들.
    blocked_states: dict[str, str] = {}

    for node_id in _topo_order(dag, [pn.id for pn in pipeline.nodes]):
        pn = prepared.nodes[node_id]

        cause = _blocking_cause(pn, dag.get(node_id, []), result, machine, blocked_states)
        if cause is not None:
            _record(result, node_id, "not_run", findings=[], cause_of=cause, path=path)
            for state in machine.blocked_by(node_id):
                blocked_states.setdefault(state, cause.node)
            continue

        scripts = prepared.scripts.get(node_id, {})
        missing = [target for target in targets if target not in scripts]
        if missing:
            # 준비 단계가 이미 오류를 냈다. 여기서 억지로 이어가면 원인이 뭉개진다.
            _record(result, node_id, "error", findings=[], path=path)
            for state in machine.blocked_by(node_id):
                blocked_states.setdefault(state, node_id)
            continue

        outputs, node_findings = _run_targets(
            pn,
            targets,
            target_configs,
            scripts=scripts,
            registry=prepared.registry,
            result=result,
            machine=machine,
            path=path,
        )

        if outputs is None:
            _record(result, node_id, "error", findings=node_findings, path=path)
            for state in machine.blocked_by(node_id):
                blocked_states.setdefault(state, node_id)
            continue

        status = "pass"
        if node_id in compare_ids:
            values[node_id] = outputs
            same = all_same(outputs)
            node_findings.append(_verdict(node_id, outputs, same=same, path=path))
            if not same:
                status = "violation"

        # **위반은 뒷단을 끊지 않는다.** 값은 멀쩡히 나왔고, 차이는 전부 모은다.
        _record(result, node_id, status, findings=node_findings, value=outputs, path=path)
        machine.after_node(node_id)

    return values


def _run_targets(
    pn: PipelineNode,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    scripts: Mapping[str, tuple[Path, ScriptContract]],
    registry: TypeRegistry,
    result: RunResult,
    machine: StateMachine,
    path: str,
) -> tuple[dict[str, Any] | None, list[Finding]]:
    """한 노드의 target 별 스크립트를 전부 돌려 `{target: 출력값}` 으로 취합한다.

    **스크립트는 자기 target 의 값 하나만 받고 하나만 내놓는다** — 분배도 취합도
    엔진의 몫이라 스크립트의 모양이 값 검증 파이프라인과 완전히 같다.
    """
    findings: list[Finding] = []
    outputs: dict[str, Any] = {}
    state = machine.snapshot(pn.states)
    failed = False

    for target in targets:
        script_path, contract = scripts[target]
        raw_input, input_findings = _input_for(pn, result, target, path=path)
        findings.extend(input_findings)
        if input_findings:
            failed = True
            continue

        input_value, shaped = _shape(
            raw_input, contract.input_type, contract, registry, pn.id, target, path=path
        )
        if shaped is not None:
            findings.append(shaped)
            failed = True
            continue

        params, param_findings = _params_for(
            pn, target_configs[target], target, state, path=path
        )
        findings.extend(param_findings)
        if params is None:
            failed = True
            continue

        try:
            module = node_exec.load_script(script_path)
            args = node_exec.build_args(
                module, contract, input_value=input_value, params=params, state=state
            )
        except StrictlerError as exc:
            findings.extend(node_checks.findings_of(exc, path=path, node=pn.id))
            failed = True
            continue
        except Exception as exc:  # noqa: BLE001 - 사용자 코드 로드는 무엇이든 낼 수 있다
            findings.append(_script_error(pn.id, target, script_path, exc, path=path))
            failed = True
            continue

        checked = node_exec.validate_input(
            contract, input_value, registry, path=path, node=pn.id
        )
        findings.extend(_tag(checked, target))
        if checked:
            failed = True
            continue

        try:
            value = node_exec.invoke(module, args)
        except Exception as exc:  # noqa: BLE001 - 스크립트 예외는 **오류**다
            findings.append(_script_error(pn.id, target, script_path, exc, path=path))
            failed = True
            continue

        checked = node_exec.validate_output(
            contract, value, registry, path=path, node=pn.id
        )
        findings.extend(_tag(checked, target))
        if checked:
            failed = True
            continue

        bundled, dumped = _dump(value, contract, registry, pn.id, target, path=path)
        if dumped is not None:
            findings.append(dumped)
            failed = True
            continue
        outputs[target] = bundled

    if failed:
        return None, findings
    return outputs, findings


def _input_for(
    pn: PipelineNode, result: RunResult, target: str, *, path: str
) -> tuple[Any, list[Finding]]:
    """앞단 묶음에서 이 target 의 값 하나를 꺼낸다 (**분배**)."""
    producers: list[str] = []
    for producer in pn.inputs.values():
        if producer not in producers:
            producers.append(producer)
    if not producers:
        return None, []
    if len(producers) > 1:
        return None, [
            Finding(
                status="error",
                path=path,
                node=pn.id,
                message=(
                    "`inputs` 가 서로 다른 앞단 노드 "
                    f"{', '.join(producers)} 를 가리킵니다.\n"
                    "`Args.input` 은 값 하나입니다 — 노드 하나에서만 입력을 받도록 "
                    "배선하고, 여러 앞단이 필요하면 합치는 노드를 하나 두세요."
                ),
            )
        ]
    return collect_target_values(result, producers[0]).get(target), []


def _shape(
    raw: Any,
    type_name: str,
    contract: ScriptContract,
    registry: TypeRegistry,
    node_id: str,
    target: str,
    *,
    path: str,
) -> tuple[Any, Finding | None]:
    """앞단 묶음의 값을 **이 스크립트가 선언한 input 타입**으로 세운다 (분배).

    묶음은 target 을 건너 오가므로 스크립트마다 다른 클래스가 된다 — 그래서 취합은
    평평한 데이터로 하고, 분배할 때 뒷단이 선언한 타입으로 다시 세운다.
    """
    if not type_name or raw is None:
        return None, None
    try:
        return registry.to_value(TypeKey(contract.path, type_name), raw), None
    except Exception as exc:  # noqa: BLE001 - pydantic / 등록기 어느 쪽이든 계약 위반이다
        return None, Finding(
            status="error",
            path=path,
            node=node_id,
            message=(
                f"target `{target}` 의 입력을 `{type_name}` 으로 세울 수 없습니다.\n"
                f"{type(exc).__name__}: {exc}\n"
                "앞단 출력 정의와 이 노드의 `Args.input` 정의가 같아야 합니다."
            ),
        )


def _dump(
    value: Any,
    contract: ScriptContract,
    registry: TypeRegistry,
    node_id: str,
    target: str,
    *,
    path: str,
) -> tuple[Any, Finding | None]:
    """출력을 **평평한 데이터**로 만든다 (취합).

    target 마다 스크립트가 다르므로 같은 개념도 서로 다른 클래스로 나온다 —
    클래스를 그대로 두면 `==` 이 언제나 거짓이라 비교가 성립하지 않는다.
    등록기가 아는 구조로 한 번 세워서 평평하게 펴면 **개념 층에서** 비교된다.
    리포트에 그대로 실릴 수 있는 형태이기도 하다.
    """
    if not contract.output_type:
        return None, Finding(
            status="error",
            path=path,
            node=node_id,
            message=(
                f"target `{target}` 의 스크립트가 출력 타입을 선언하지 않았습니다: "
                f"{contract.path}\n"
                "출력은 `returnResult()` 로 dataclass 를 내보내야 합니다 — "
                "비교는 그 구조를 보고 합니다."
            ),
        )
    try:
        model = registry.to_value(TypeKey(contract.path, contract.output_type), value)
    except Exception as exc:  # noqa: BLE001 - 계약 위반이지 위반이 아니다
        return None, Finding(
            status="error",
            path=path,
            node=node_id,
            message=(
                f"target `{target}` 의 출력이 선언한 `{contract.output_type}` 과 "
                f"맞지 않습니다.\n{type(exc).__name__}: {exc}"
            ),
        )
    return model.model_dump(), None


def _params_for(
    pn: PipelineNode,
    config: Mapping[str, Any],
    target: str,
    state: Mapping[str, Any],
    *,
    path: str,
) -> tuple[dict[str, Any] | None, list[Finding]]:
    """`params` 의 `${config.X}` / `${state.X}` 를 이 target 기준으로 전개한다.

    **`params` 는 target 별로 갈린다** — 스크립트가 갈라지니 거기 필요한 값도 갈라진다.
    없는 이름은 `STR-CMP-004` 다 (`targets.<이름>` 에도 공통에도 없다).
    """
    try:
        expanded = refs.expand_config(dict(pn.params), config, target)
        expanded = refs.expand_state(expanded, state)
    except StrictlerError as exc:
        return None, node_checks.findings_of(exc, path=path, node=pn.id)
    return dict(expanded), []


# ── not run 전파 ─────────────────────────────────────────────────────────────


def _blocking_cause(
    pn: PipelineNode,
    deps: list[str],
    result: RunResult,
    machine: StateMachine,
    blocked_states: Mapping[str, str],
) -> NotRunCause | None:
    """이 노드가 도달 불가가 됐는지. 전파 경로는 **둘**이다 (`schema.md` 9절).

    ① **데이터 의존** — 앞단이 오류로 끝났거나 애초에 돌지 않았다.
    ② **상태 의존** — 상태를 밀어야 할 노드가 실패해 전이가 일어나지 않았고,
       그 상태를 `when` 으로 기다리는 노드는 영원히 조건을 만족하지 못한다.

    **위반은 여기 해당 없다.** 위반한 노드도 값은 내놨으므로 뒷단은 그대로 돈다.
    """
    for dep in deps:
        upstream = result.outcomes.get(dep)
        if upstream is None or upstream.status in ("error", "not_run"):
            # 원인은 **최초로 못 돈 노드**다. 중간 노드를 가리키면 원인이 뭉개진다.
            origin = _origin_of(upstream) if upstream is not None else None
            return NotRunCause(node=origin or dep, reason="data_dependency")

    if pn.when is not None:
        mapped = pn.states.get(pn.when.state, pn.when.state)
        culprit = blocked_states.get(mapped)
        if culprit is not None:
            return NotRunCause(node=culprit, reason="state_unreachable")
        if not machine.matches(pn.states, pn.when.state):
            return NotRunCause(node=pn.id, reason="state_unreachable")
    return None


def _origin_of(outcome: NodeOutcome) -> str | None:
    """이미 `not_run` 인 노드가 적어둔 최초 원인 노드."""
    for item in outcome.findings:
        if item.cause is not None:
            return item.cause.node
    return None


# ── 결과 기록 ────────────────────────────────────────────────────────────────


def _record(
    result: RunResult,
    node_id: str,
    status: str,
    *,
    findings: list[Finding],
    value: Any = None,
    cause_of: NotRunCause | None = None,
    path: str,
) -> None:
    """노드 하나의 결과를 `RunResult` 에 남긴다.

    **`not_run` 의 원인은 바꾸는 그 시점에 적는다** (`schema.md` 9절).
    """
    collected = list(findings)
    if cause_of is not None:
        collected.append(
            Finding(status="not_run", path=path, node=node_id, cause=cause_of)
        )
    outcome = NodeOutcome(node_id, status)
    outcome.findings = collected
    if value is not None:
        outcome.value = value
    result.outcomes[node_id] = outcome
    result.findings.extend(collected)


def _verdict(
    node_id: str, outputs: Mapping[str, Any], *, same: bool, path: str
) -> Finding:
    """엔진이 만드는 Verdict — **Reckon 이 필요 없는 자리**.

    "내장 동작 없음" 원칙과 충돌하지 않는다: **동등 비교는 도메인 지식이 아니라
    일반 연산**이다. 무엇을 무시해도 되는지는 스크립트가 정규화로 이미 정했다.
    """
    if same:
        return Finding(
            status="pass",
            path=path,
            node=node_id,
            message=(
                f"대상 {len(outputs)}개가 같은 값을 내놨습니다: "
                f"{', '.join(sorted(outputs))}"
            ),
        )
    return Finding(
        status="violation",
        path=path,
        node=node_id,
        message=(
            "대상 간 출력이 다릅니다.\n"
            + "\n".join(f"  {name}: {outputs[name]!r}" for name in outputs)
            + "\n판정은 목록 전부가 같은 값을 뱉느냐입니다 — 하나만 어긋나도 위반입니다. "
            "무시해도 되는 차이(좌표 반올림·타임스탬프 등)라면 비교용 데이터를 "
            "내보내는 스크립트에서 정규화하세요. 엔진은 `==` 만 압니다."
        ),
    )


def _script_error(
    node_id: str, target: str, script_path: Path, exc: Exception, *, path: str
) -> Finding:
    """스크립트가 예외를 냈다 — **오류**다. 위반이 아니다 (`schema.md` 9절)."""
    return Finding(
        status="error",
        path=path,
        node=node_id,
        message=(
            f"target `{target}` 의 스크립트가 예외로 끝났습니다: {script_path}\n"
            f"{type(exc).__name__}: {exc}"
        ),
    )


def _tag(findings: list[Finding], target: str) -> list[Finding]:
    """어느 target 에서 난 것인지 메시지에 남긴다."""
    return [
        item.model_copy(update={"message": f"[target: {target}] {item.message}"})
        for item in findings
    ]


# ── DAG ──────────────────────────────────────────────────────────────────────


def _topo_order(dag: Mapping[str, list[str]], declared: list[str]) -> list[str]:
    """의존이 먼저 오도록 정렬한다. 같은 층은 **선언 순서**를 지킨다.

    순환은 등록 시점(`STR-GRAPH-001`)에 이미 막혔다. 그래도 남으면 선언 순서로
    뒤에 붙인다 — 그 노드들은 앞단 결과가 없어 `not_run` 이 된다.
    """
    order: list[str] = []
    placed: set[str] = set()
    remaining = list(declared)
    while remaining:
        ready = [
            node_id
            for node_id in remaining
            if all(dep in placed or dep not in dag for dep in dag.get(node_id, ()))
        ]
        if not ready:
            order.extend(remaining)
            break
        order.extend(ready)
        placed.update(ready)
        remaining = [node_id for node_id in remaining if node_id not in placed]
    return order
