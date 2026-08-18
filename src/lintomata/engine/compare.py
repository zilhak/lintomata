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

**Judge 가 필요 없다** — Verdict 를 엔진이 만든다. "내장 동작 없음" 원칙과 충돌하지
않는다: **동등 비교는 도메인 지식이 아니라 일반 연산**이다.

**위반 판정은 `targets` 목록 전부가 같은 값을 뱉느냐**이지 짝지어 비교하는 것이 아니다.
하나만 어긋나도 위반. **"동일하다"는 정말로 동일하다는 뜻이다** — 허용 오차도 무시
필드도 엔진에 두지 않는다. 정규화는 스크립트가 알아서 한다. **엔진은 `==` 만 안다.**

### ★ 이건 lint 다

**위반은 정상 결과다.** 값이 갈렸다고 뒷단을 멈추지 않는다 — 노드는 멀쩡히 값을
내놨고, 한 번의 실행에서 확인 가능한 차이를 **전부 모으는** 것이 목적이다.
뒷단을 끊는 것은 **오류**(스크립트 예외·계약 위반)뿐이고, 그 여파는 `not_run` 이다.
복구·재시도·대체 경로는 없다.

### ★ 구동 루프는 `engine.drive` 하나다

`ready()` 재스캔·구간 전이 drain·선언 순서 tie-break·실행 시점 해시 대조를 **여기에
복제하지 않는다** (MODULES.md R4-1). 값 검증과 각자 구현했더니 실제로 갈렸고,
정적 topo 정렬로 돌던 탓에 **통과할 노드에 거짓 not run** 이 찍혔다.
비교 엔진이 따로 정하는 것은 **한 노드를 target 마다 돌려 취합하는 방법**뿐이다.

**★ `engine.runtime` 을 import 하지 마라.** 공용 결과 타입(`RunResult`/`NodeOutcome`)은
`engine.result` 에 있다. `runtime` 이 `kind` 를 보고 이쪽으로 디스패치하므로,
반대 방향 import 를 만들면 순환이 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lintomata import refs, rules
from lintomata.checks import node as node_checks
from lintomata.checks import pipeline as pipeline_checks
from lintomata.checks import script as script_checks
from lintomata.checks.contracts import ScriptCache
from lintomata.checks.node import dedupe
from lintomata.checks.script import ScriptContract
from lintomata.engine import drive as drive_loop
from lintomata.engine import exec as node_exec
from lintomata.engine.result import NodeOutcome, RunResult
from lintomata.engine.state import StateMachine
from lintomata.errors import Finding, LintomataError
from lintomata.locale import message
from lintomata.model import Node, Pipeline, PipelineNode
from lintomata.report import CompareReport, build_compare_report
from lintomata.store.entries import Store
from lintomata.typesys.registry import TypeRegistry

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

    **둘 다 없으면 `LNT-CMP-004`** — 그 판정은 값을 실제로 찾는 시점, 즉
    `refs.expand_config(값, 이_매핑, target)` 안에서 난다. `target` 을 계속 함께
    넘기기 때문에 없는 이름은 `LNT-CONFIG-001` 이 아니라 `LNT-CMP-004` 로 나온다.
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
    cache: ScriptCache | None = None,
) -> tuple[RunResult, CompareReport]:
    """비교 파이프라인 한 벌을 구동한다.

    노드마다 target 별 스크립트를 전부 돌리고 결과를 취합한다. `compare` 에 적힌
    노드의 취합 결과가 target 간 동일한지 엔진이 비교해 Verdict 를 만든다.

    **실행과 동시에 결과 리포트를 쌓는다** — 무엇이 어디서 어떻게 달랐는지.
    출력 위치는 Spec `plan` 항목의 `report` 이고, 파일로 쓰는 것은 부르는 쪽이다.

    `cache` 는 값 검증과 **같은 것**이다 (`checks.contracts`). 한쪽에만 붙이면
    두 파이프라인 종류의 동작이 갈린다 — R4-1 이 실제로 겪은 자리다.
    """
    cache = cache if cache is not None else ScriptCache(store)
    result = RunResult()

    if pipeline.info.kind != "compare":
        result.findings.append(
            Finding(
                status="error",
                path=path,
                message=message(
                    "The compare engine was handed a `kind: {kind}` pipeline.\n"
                    "Compare driving is only for pipelines whose `info.kind` is "
                    "`compare`. Run a verify pipeline on the verify engine.",
                    kind=pipeline.info.kind,
                ),
            )
        )
        return _close(pipeline, result, path), build_compare_report({})

    targets = list(pipeline.targets)
    if len(targets) < 2:
        result.findings.append(
            rules.finding("LNT-CMP-003", path=path, fields={"count": len(targets)})
        )
        return _close(pipeline, result, path), build_compare_report({})

    target_configs = {name: resolve_target_config(config, name) for name in targets}

    prepared, prep_findings = _prepare(
        pipeline, targets, target_configs, store=store, env=env, path=path, cache=cache
    )
    result.findings.extend(prep_findings)
    if prepared is None:
        return _close(pipeline, result, path), build_compare_report({})

    # 전이 지연은 그래프의 성질이라 target 별로 갈리지 않는다 — 공통 config 다.
    common = resolve_target_config(config, "")
    try:
        machine = StateMachine(
            pipeline.states, list(pipeline.transitions), common, started_at_ms, env=env
        )
    except LintomataError as exc:
        result.findings.extend(node_checks.findings_of(exc, path=path))
        return _close(pipeline, result, path), build_compare_report({})

    values = _walk(
        pipeline,
        targets,
        target_configs,
        prepared=prepared,
        result=result,
        machine=machine,
        env=env,
        path=path,
    )
    return _close(pipeline, result, path), build_compare_report(values)


def _close(pipeline: Pipeline, result: RunResult, path: str) -> RunResult:
    """남은 노드를 `not_run` 으로 확정하고 결과를 정리한다.

    **어느 반환 경로로 나가든 여기를 지난다** — 그래야 파이프라인의 모든 노드가
    네 상태 중 정확히 하나에 들어간다 (R4-2). 중간에 그냥 `return` 하면 그 노드들이
    리포트에서 조용히 사라지고, 그건 거짓 리포트다.

    **target 무관한 결과는 여기서 한 번만 남는다** (R4-6) — 배선 오류 같은 것이
    target 수만큼 쌓이면 AI 가 "여러 군데가 틀렸다"고 읽는다. target 별로 갈리는
    것은 메시지에 target 이 박혀 있어 지워지지 않는다.
    """
    result.findings.extend(drive_loop.finalize(pipeline, result, path))
    result.findings = dedupe(result.findings)
    return result


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
    비교는 `Meaning` 층에서 한다 — `Data` 는 비교 대상이 아니다.
    """
    outputs = list(values.values())
    return all(item == outputs[0] for item in outputs[1:])


# ── 준비 — 노드 한 벌 + target 별 스크립트 ────────────────────────────────────


class _Prepared:
    """구동에 필요한 것들. 노드는 한 벌, 스크립트만 target 별로 갈린다."""

    def __init__(self) -> None:
        self.nodes: dict[str, PipelineNode] = {}
        self.scripts: dict[str, dict[str, tuple[Path, ScriptContract]]] = {}
        self.libraries: dict[str, dict[str, Path]] = {}
        """`{노드 id: {슬롯: 파일}}` — **target 별로 갈리지 않는다.** 배선은 노드에
        있고 노드는 한 벌이다 (`schema.md` 6.5절)."""
        self.registry: TypeRegistry | None = None


def _prepare(
    pipeline: Pipeline,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    store: Store,
    env: Mapping[str, str],
    path: str,
    cache: ScriptCache | None = None,
) -> tuple[_Prepared | None, list[Finding]]:
    """노드를 한 벌 로드하고 target 별로 실제 도는 스크립트를 푼다."""
    cache = cache if cache is not None else ScriptCache(store)
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
        # **실행 시점 해시 대조** (`LNT-REG-001`) — 값 검증과 같은 자리에서 본다.
        # 등록은 검증 결과를 재사용하는 기제이므로, 정적 검사 루트를 피해 등록소
        # 파일을 고친 것을 실행 직전에 잡아야 한다 (`schema.md` 2·13절).
        findings.extend(
            drive_loop.verify_hash(pn.source, store=store, path=path, node_id=pn.id)
        )
        if node is None:
            continue
        # 라이브러리 배선은 **노드에** 있다 — target 마다 다시 풀면 같은 오류가
        # target 수만큼 쌓인다 (R4-6). 여기서 한 번만 푼다.
        libraries, library_findings = drive_loop.resolve_libraries(
            node, store=store, env=env, path=path, node_id=pn.id
        )
        findings.extend(library_findings)
        if any(item.status == "error" for item in library_findings):
            # 값 검증(`runtime._load_nodes`)과 **같은 처리다.** 한쪽만 고치면 갈린다 —
            # 못 푼 채로 로드하면 스크립트가 `ImportError` 로 죽으면서 거짓 안내가
            # 원인 위에 덮인다. 준비 안 된 노드는 `_mark_unprepared` 가 error 로
            # 확정하고 여파는 `drive.finalize` 가 `not_run` 으로 표기한다.
            continue
        prepared.libraries[pn.id] = libraries
        for target in targets:
            resolved, gathered = _resolve_one(
                node,
                node_id=pn.id,
                target=target,
                config=target_configs[target],
                store=store,
                env=env,
                path=path,
                cache=cache,
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
    cache: ScriptCache,
) -> tuple[tuple[Path, ScriptContract] | None, list[Finding]]:
    """이 target 에서 실제로 도는 스크립트 경로와 그 계약.

    ⚠ 여기서 나오는 결과에 target 을 덧붙이지 않는다. `LNT-CMP-004` 는 `refs` 가
    이미 "현재 target: X" 를 담아 주고, 나머지(경로·등록소 판정)는 경로가 문구에
    들어 있어 대상이 다르면 문구도 다르다. 문구까지 완전히 같다면 그건 정말로
    **같은 사실 하나**이므로 `_close` 의 dedupe 가 한 번만 남기는 것이 맞다 (R4-6).
    """
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
                    message=message(
                        "It is run time and the node's `script` is still "
                        "unexpanded: {value} (target: {target})\n"
                        "Fill this value in from the Spec's "
                        "`config.targets.<name>` or from the shared `config`.",
                        value=repr(node.script),
                        target=target,
                    ),
                )
            )
        return None, findings

    findings.extend(
        drive_loop.verify_hash(
            _expanded_script(node, config, target), store=store, path=path, node_id=node_id
        )
    )

    try:
        source = script_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        findings.append(
            Finding(
                status="error",
                path=path,
                node=node_id,
                message=message(
                    "Cannot read the script: {path} ({detail})\n"
                    "A node script is Python source and must be UTF-8.",
                    path=script_path,
                    detail=exc,
                ),
            )
        )
        return None, findings

    try:
        contract, extracted = cache.contract(source, str(script_path))
    except LintomataError as exc:
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


def _expanded_script(node: Node, config: Mapping[str, Any], target: str) -> Any:
    """`script` 자리의 값을 이 target 기준으로 편 것 — 해시 대조 대상을 고르기 위함.

    비교 파이프라인은 `script` 에 `${config.buttonScript}` 를 쓰고 그 값이
    `${ref.sc_...}` 일 수 있다. 원문 그대로 보면 등록소 참조인지 알 수 없다.
    못 펴면 원문을 준다 — 그 실패는 `resolve_script` 가 이미 짚었다.
    """
    try:
        return refs.expand_config(node.script, config, target)
    except LintomataError:
        return node.script


# ── 구동 ─────────────────────────────────────────────────────────────────────


def _walk(
    pipeline: Pipeline,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    prepared: _Prepared,
    result: RunResult,
    machine: StateMachine,
    env: Mapping[str, str],
    path: str,
) -> dict[str, dict[str, Any]]:
    """노드마다 target 전부를 돌리고 취합한다.

    **구동 순서·전이·not run 전파는 `engine.drive` 가 한다** (R4-1). 여기가 정하는
    것은 "한 노드를 어떻게 도느냐" 하나뿐이고, 그게 값 검증과 갈리는 유일한 지점이다.
    """
    compare_ids = set(pipeline.compare)
    values: dict[str, dict[str, Any]] = {}
    runnable = _mark_unprepared(pipeline, targets, prepared, result, path)

    def run_node(pn: PipelineNode) -> NodeOutcome:
        outputs, findings = _run_targets(
            pn,
            targets,
            target_configs,
            scripts=prepared.scripts[pn.id],
            libraries=prepared.libraries.get(pn.id, {}),
            registry=prepared.registry,
            result=result,
            machine=machine,
            env=env,
            path=path,
        )
        if outputs is None:
            return _outcome(pn.id, "error", findings)

        status = "pass"
        if pn.id in compare_ids:
            # 비교·리포트는 **평평한 데이터**로 한다 — target 마다 클래스가 다르므로
            # 인스턴스끼리는 `==` 이 언제나 거짓이 되어 비교가 성립하지 않는다.
            flat = {name: _plain(value) for name, value in outputs.items()}
            values[pn.id] = flat
            same = all_same(flat)
            findings.append(_verdict(pn.id, flat, same=same, path=path))
            if not same:
                status = "violation"
        else:
            # 비교 대상이 아니어도 **돌아간 것 자체가 통과다.** 결과를 안 남기면
            # 그 노드가 네 상태 어디에도 없이 리포트에서 사라진다 (R4-2).
            findings.append(Finding(status="pass", path=path, node=pn.id))

        # **위반은 뒷단을 끊지 않는다.** 값은 멀쩡히 나왔고, 차이는 전부 모은다.
        outcome = _outcome(pn.id, status, findings)
        # 분배할 값은 **스크립트가 낸 그대로** 넘긴다 — 재구성해서 넘기면
        # `dataclasses.asdict`/`isinstance` 를 쓰는 스크립트가 값 검증과 갈린다 (R4-5).
        outcome.value = outputs
        return outcome

    drive_loop.drive(
        pipeline, machine=machine, runnable=runnable, run_node=run_node, result=result
    )
    return values


def _mark_unprepared(
    pipeline: Pipeline,
    targets: list[str],
    prepared: _Prepared,
    result: RunResult,
    path: str,
) -> list[str]:
    """준비 단계에서 이미 막힌 노드를 `error` 로 확정하고, 돌릴 노드만 돌려준다.

    target 한 벌이라도 스크립트가 안 풀리면 묶음이 안 차서 비교가 성립하지 않는다.
    억지로 이어가면 원인이 뭉개지므로 그 자리에서 진행하지 않는다 — 여파는
    `drive.finalize` 가 `not_run` 으로 표기한다.
    """
    attributed = {
        finding.node
        for finding in result.findings
        if finding.status == "error" and finding.node
    }
    runnable: list[str] = []
    for pn in pipeline.nodes:
        missing = [t for t in targets if t not in prepared.scripts.get(pn.id, {})]
        if not missing and pn.id not in attributed:
            runnable.append(pn.id)
            continue
        findings: list[Finding] = []
        if pn.id not in attributed:
            findings.append(
                Finding(
                    status="error",
                    path=path,
                    node=pn.id,
                    message=message(
                        "This node's script is not ready on some targets: "
                        "{targets}\n"
                        "A comparison only holds once every target has produced a "
                        "value. Fix the errors above first.",
                        targets=", ".join(missing),
                    ),
                )
            )
            result.findings.extend(findings)
        result.outcomes[pn.id] = _outcome(pn.id, "error", findings)
    return runnable


def _outcome(node_id: str, status: str, findings: list[Finding]) -> NodeOutcome:
    outcome = NodeOutcome(node_id, status)  # type: ignore[arg-type]
    outcome.findings = list(findings)
    return outcome


def _plain(value: Any) -> Any:
    """비교·리포트용 **평평한 데이터**로 편다.

    target 마다 스크립트가 다르므로 같은 개념도 서로 다른 클래스로 나온다 —
    클래스를 그대로 두면 `==` 이 언제나 거짓이라 비교가 성립하지 않는다.
    dataclass 를 dict 로 펴면 **개념 층에서** 비교되고 리포트에 그대로 실린다.

    ⚠ **정규화가 아니다.** 반올림도 무시 필드도 허용 오차도 없다 — 구조를 펴기만
    하고 값은 손대지 않는다. `3.0` 과 `3.0001` 은 여기를 지나도 다른 값이다.
    무엇을 무시해도 되는지는 도메인 지식이고, 그건 스크립트 쪽에 있다.
    """
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    try:
        data = node_exec.as_mapping(value)
    except LintomataError:
        return value  # primitive — 펼 것이 없다
    return {name: _plain(item) for name, item in data.items()}


def _run_targets(
    pn: PipelineNode,
    targets: list[str],
    target_configs: Mapping[str, dict[str, Any]],
    *,
    scripts: Mapping[str, tuple[Path, ScriptContract]],
    libraries: Mapping[str, Path],
    registry: TypeRegistry,
    result: RunResult,
    machine: StateMachine,
    env: Mapping[str, str],
    path: str,
) -> tuple[dict[str, Any] | None, list[Finding]]:
    """한 노드의 target 별 스크립트를 전부 돌려 `{target: 출력값}` 으로 취합한다.

    **스크립트는 자기 target 의 값 하나만 받고 하나만 내놓는다** — 분배도 취합도
    엔진의 몫이라 스크립트의 모양이 값 검증 파이프라인과 완전히 같다.
    **값도 스크립트가 낸 그대로** 오간다 (R4-5): 재구성해서 넘기면 앞단이 낸
    dataclass 인스턴스가 다른 무언가로 바뀌어, 값 검증에서는 되는 스크립트가
    비교에서만 안 되는 일이 생긴다.
    """
    findings: list[Finding] = []
    outputs: dict[str, Any] = {}
    state = machine.snapshot(pn.states)
    failed = False

    # **배선 판정은 target 과 무관하다** — 루프 안에서 보면 같은 오류가 target
    # 수만큼 쌓인다 (R4-6). 여기서 한 번만 본다.
    producer, wiring = _producer_of(pn, path=path)
    if wiring:
        return None, wiring

    for target in targets:
        script_path, contract = scripts[target]
        input_value = (
            collect_target_values(result, producer).get(target) if producer else None
        )

        params, param_findings = _params_for(
            pn, target_configs[target], target, state, env=env, path=path
        )
        findings.extend(param_findings)
        if params is None:
            failed = True
            continue

        try:
            module = node_exec.load_script(script_path, libraries)
            args = node_exec.build_args(
                module, contract, input_value=input_value, params=params, state=state
            )
        except LintomataError as exc:
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

        if not contract.output_type:
            findings.append(
                Finding(
                    status="error",
                    path=path,
                    node=pn.id,
                    message=message(
                        "The script for target `{target}` declares no output "
                        "type: {path}\n"
                        "The output must leave through `returnResult()` as a "
                        "dataclass — the comparison reads that structure.",
                        target=target,
                        path=contract.path,
                    ),
                )
            )
            failed = True
            continue

        # **스크립트가 낸 값을 그대로 보관한다.** 재구성하지 않는다 (R4-5) —
        # 타입 검증은 바로 위 `validate_output` 이 이미 별개로 했다.
        outputs[target] = value

    if failed:
        return None, findings
    return outputs, findings


def _producer_of(pn: PipelineNode, *, path: str) -> tuple[str, list[Finding]]:
    """이 노드에 값을 주는 앞단 노드. **target 과 무관한 배선 판정**이다.

    **정본은 등록 시점의 `checks.pipeline.check_ambiguous_input`(`LNT-GRAPH-003`)**
    이고 여기는 2선 방어다 (R5-3). 값 검증(`runtime._ambiguous_input`)과 **같은
    규칙 id 로** 낸다 — 같은 사실이 엔진에 따라 다른 모양으로 나오면 안 된다.
    """
    producers: list[str] = []
    for producer in pn.inputs.values():
        if producer not in producers:
            producers.append(producer)
    if not producers:
        return "", []
    if len(producers) > 1:
        return "", [
            rules.finding(
                "LNT-GRAPH-003",
                path=path,
                node=pn.id,
                fields={"nodes": ", ".join(producers)},
            )
        ]
    return producers[0], []


def _params_for(
    pn: PipelineNode,
    config: Mapping[str, Any],
    target: str,
    state: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    path: str,
) -> tuple[dict[str, Any] | None, list[Finding]]:
    """`params` 를 이 target 기준으로 **끝까지** 전개한다 — `config` → `state` → `env`.

    **`params` 는 target 별로 갈린다** — 스크립트가 갈라지니 거기 필요한 값도 갈라진다.
    없는 이름은 `LNT-CMP-004` 다 (`targets.<이름>` 에도 공통에도 없다).

    **env 전개는 값 검증과 같은 자리에서 같은 순서로 한다** (R5-1) — 여기만 빠지면
    비교 파이프라인에서만 `${env.X}` 가 원문으로 스크립트에 도달한다.
    """
    try:
        expanded = refs.expand_all(
            dict(pn.params), config=config, state=state, env=env, target=target
        )
    except LintomataError as exc:
        return None, node_checks.findings_of(exc, path=path, node=pn.id)
    return dict(expanded), []


# ── 결과 기록 ────────────────────────────────────────────────────────────────


def _verdict(
    node_id: str, outputs: Mapping[str, Any], *, same: bool, path: str
) -> Finding:
    """엔진이 만드는 Verdict — **Judge 가 필요 없는 자리**.

    "내장 동작 없음" 원칙과 충돌하지 않는다: **동등 비교는 도메인 지식이 아니라
    일반 연산**이다. 무엇을 무시해도 되는지는 스크립트가 정규화로 이미 정했다.
    """
    if same:
        return Finding(
            status="pass",
            path=path,
            node=node_id,
            message=message(
                "All {count} targets produced the same value: {targets}",
                count=len(outputs),
                targets=", ".join(sorted(outputs)),
            ),
        )
    return Finding(
        status="violation",
        path=path,
        node=node_id,
        message=message(
            "The targets produced different outputs.\n"
            "{outputs}\n"
            "The decision is whether every target in the list yields the same "
            "value — one mismatch is a violation. If a difference is safe to "
            "ignore (rounded coordinates, timestamps …), normalize it in the "
            "script that emits the data for comparison. The engine only knows "
            "`==`.",
            outputs="\n".join(f"  {name}: {outputs[name]!r}" for name in outputs),
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
        message=message(
            "The script for target `{target}` ended in an exception: {path}\n"
            "{detail}",
            target=target,
            path=script_path,
            detail=f"{type(exc).__name__}: {exc}",
        ),
    )


def _tag(findings: list[Finding], target: str) -> list[Finding]:
    """어느 target 에서 난 것인지 메시지에 남긴다."""
    return [
        item.model_copy(update={"message": f"[target: {target}] {item.message}"})
        for item in findings
    ]
