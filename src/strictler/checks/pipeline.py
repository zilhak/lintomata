"""파이프라인 JSON 로드와 검증 — **파이프라인 등록 시** (`schema.md` 13절).

| 검증 | 규칙 |
|---|---|
| `source` 가 가리키는 노드가 실재하는지 | `STR-REF-002` |
| `${ref.<id>}` 접두가 맞는지 / 등록소에 있는지 | `STR-REG-003` / `STR-REG-002` |
| `inputs` 가 가리키는 노드 id 가 실재하는지 | `STR-REF-003` |
| DAG 에 순환이 없는지 / 고립 노드가 없는지 | `STR-GRAPH-001` / `-002` |
| 등록된 dataclass 집합 정규화 후 **input 정의 == output 정의**인지 | `STR-TYPE-004` |
| 노드 `states` 매핑이 빠짐없고 대상이 `states.values` 에 실재하는지 | `STR-STATE-002` / `-003` |
| `when` 이 참조하는 상태 id 가 스크립트의 `Args.state` 에 선언됐는지 | `STR-STATE-004` |
| `transitions.after` 가 실재 노드 id 인지, `to` 가 실재 상태인지 | `STR-REF-004` / `STR-STATE-005` |
| 사용자 상태 이름에 `__` 접두가 없는지 | `STR-STATE-001` |
| `config` 선언의 `type` 이 primitive 집합에 속하는지 | `STR-TYPE-005` |
| `kind: compare` 일 때 `compare` 가 가리키는 노드가 실재하는지 | `STR-REF-005` |
| `kind: compare` 일 때 **target 별 스크립트가 같은 input/output/state 타입을 선언했는지** | `STR-CMP-002` |
| `targets` 가 2개 이상인지 | `STR-CMP-003` |

실행 시점의 config 채움(`STR-CONFIG-001`~`003`)과 `path: true` 검증(`STR-PATH-004`)도
여기 산다 — **`config` 를 선언한 것이 파이프라인이므로 그 값을 판정하는 것도 여기다**
(MODULES.md R1-6). `refs.expand_config` 는 **default 가 이미 채워진** config 를 받는다.

도달 가능성(`STR-STATE-006` / `-007`)은 `checks.reachability` 가 맡는다.

**`inputs` 가 DAG 를 만든다.** 별도 `edges` 섹션이 없다 — 입력 참조가 곧 의존 관계다.

### ★ Action 은 투명하다

`X ──▶ Action ──▶ Y` 는 실은 **`X ──▶ Y` 인데 그 사이에 Action 이 낀 형상**이다.
`check_wiring_types` 는 **Action 을 건너뛰고 상·하단 계약을 대조**한다.
그래서 "Action 을 어디에나 끼워 넣는다" 가 타입 체계와 충돌하지 않는다 —
낀 배선과 안 낀 배선의 판정이 **같아야** 하기 때문이다.

### `transitions` 는 시간만 다룬다

"실패했으니 다른 경로로" 같은 것은 없다. 조건 분기는 **스크립트가 그냥 `input` 을
반환**하는 것으로 표현한다. 엔진에 skip 개념이 없으므로 표현식 언어도 `skipWhen` 도 없다.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

from strictler import refs, rules
from strictler.checks import node as node_checks
from strictler.checks import reachability, script as script_checks
from strictler.checks.node import dedupe, findings_of, shape_findings
from strictler.checks.script import ScriptContract
from strictler.errors import Finding, StrictlerError
from strictler.model import Node, NodeType, Pipeline
from strictler.store.entries import Store
from strictler.typesys.primitives import (
    PRIMITIVES,
    TypeRef,
    element_type,
    is_list,
    is_primitive,
    parse_type,
)
from strictler.typesys.registry import TypeKey, TypeRegistry

__all__ = [
    "load_pipeline",
    "build_dag",
    "check_pipeline",
    "check_cycle",
    "check_wiring_types",
    "check_state_mapping",
    "check_transitions",
    "check_config_decls",
    "check_compare",
    "check_config_values",
]


_UNDECLARED = "(선언 없음)"
"""타입 선언이 아예 없는 자리를 `{out}`/`{in}` 슬롯에 적을 때 쓰는 표기."""


# ── 로드 ─────────────────────────────────────────────────────────────────────


def load_pipeline(raw: Mapping[str, Any], path: str) -> tuple[Pipeline | None, list[Finding]]:
    """JSON dict 를 `Pipeline` 모델로 로드한다. pydantic 검증 실패를 `Finding` 으로 바꾼다."""
    try:
        return Pipeline.model_validate(dict(raw)), []
    except ValidationError as exc:
        return None, shape_findings(exc, path, "파이프라인")


def build_dag(pipeline: Pipeline) -> dict[str, list[str]]:
    """`{노드 id: 그 노드가 의존하는 노드 id 들}`.

    `inputs` 의 값이 곧 엣지다. 별도 `edges` 섹션이 없다.
    같은 노드를 두 이름으로 받아도 의존은 한 번만 센다(순서 보존).
    """
    dag: dict[str, list[str]] = {}
    for pn in pipeline.nodes:
        deps = dag.setdefault(pn.id, [])
        for producer in pn.inputs.values():
            if producer not in deps:
                deps.append(producer)
    return dag


# ── 그래프 ───────────────────────────────────────────────────────────────────


def check_cycle(
    dag: dict[str, list[str]], source_path: str, *, exempt: frozenset[str] | set[str] | tuple[str, ...] = ()
) -> list[Finding]:
    """순환 판정 (`STR-GRAPH-001`). 순환 경로를 메시지에 넣는다.

    고립 노드(`STR-GRAPH-002`)도 여기서 함께 본다.

    `exempt` 는 **고립 판정에서 빼는 노드 id 들**이다. `transitions.after` 로 상태를
    미는 노드는 데이터를 안 내놓아도 그래프에서 제 몫을 한다 — 그걸 "고립" 이라
    부르고 제거를 권하면 파이프라인이 망가진다.

    노드가 하나뿐인 파이프라인은 고립 판정을 하지 않는다. 그 하나가 그래프 전체이고,
    "`inputs` 로 연결하거나 제거하세요" 라는 가이드가 성립하지 않기 때문이다.
    """
    findings: list[Finding] = []
    color: dict[str, int] = {}
    stack: list[str] = []
    reported: set[frozenset[str]] = set()

    def visit(nid: str) -> None:
        color[nid] = 1
        stack.append(nid)
        for dep in dag.get(nid, ()):
            if dep not in dag:
                continue  # 없는 노드 참조는 STR-REF-003 이 따로 잡는다
            mark = color.get(dep, 0)
            if mark == 0:
                visit(dep)
            elif mark == 1:
                loop = [*stack[stack.index(dep) :], dep]
                key = frozenset(loop)
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        rules.finding(
                            "STR-GRAPH-001",
                            path=source_path,
                            node=nid,
                            fields={"cycle": " → ".join(loop)},
                        )
                    )
        stack.pop()
        color[nid] = 2

    for nid in dag:
        if color.get(nid, 0) == 0:
            visit(nid)

    if len(dag) > 1:
        consumed = {dep for deps in dag.values() for dep in deps}
        for nid, deps in dag.items():
            if not deps and nid not in consumed and nid not in exempt:
                findings.append(
                    rules.finding(
                        "STR-GRAPH-002", path=source_path, node=nid, fields={"name": nid}
                    )
                )
    return findings


def check_wiring_types(
    pipeline: Pipeline,
    contracts: dict[str, ScriptContract],
    registry: TypeRegistry,
    source_path: str,
    node_types: Mapping[str, NodeType] | None = None,
) -> list[Finding]:
    """배선된 두 노드의 **선언된 정의가 동일한지** (`STR-TYPE-004`).

    **엄격한 동일성**이다. 부분집합 병합은 런타임 표현 층에서만 일어나고
    그래프 검사를 느슨하게 만들지 않는다 (`schema.md` 7절).
    이름이 달라도 구조가 같으면 같은 타입이다 — 판정은 `TypeRegistry` 가 한다.

    **Action 은 투명하다** — `X ──▶ Action ──▶ Y` 는 실은 `X ──▶ Y` 이므로
    Action 을 건너뛰고 상·하단의 계약을 대조한다. Action 자신의 선언은 **대조에
    끼지 않는다**. 그래야 "Action 을 낀 배선과 안 낀 배선의 판정이 같다" 가 성립한다
    (Action 의 input==output 은 `STR-CONTRACT-006` 이 노드 등록 시에 이미 강제했다).

    `node_types` 를 주지 않으면 건너뛸 대상을 알 수 없으므로 엣지를 그대로 대조한다 —
    올바른 Action(input==output)이라면 두 방식의 판정이 같다.
    """
    findings: list[Finding] = []
    by_id = {pn.id: pn for pn in pipeline.nodes}
    types: Mapping[str, NodeType] = node_types or {}

    for consumer in pipeline.nodes:
        if types.get(consumer.id) == "action":
            continue  # 투명 — 이 자리에서 대조하지 않는다
        downstream = contracts.get(consumer.id)
        if downstream is None:
            continue
        for producer_id in consumer.inputs.values():
            real = _skip_actions(producer_id, by_id, types)
            if real is None:
                continue
            upstream = contracts.get(real)
            if upstream is None:
                continue
            findings.extend(
                _compare_wiring(
                    registry,
                    upstream=upstream,
                    upstream_id=real,
                    downstream=downstream,
                    downstream_id=consumer.id,
                    source_path=source_path,
                )
            )
    return findings


def _skip_actions(
    node_id: str, by_id: Mapping[str, Any], types: Mapping[str, NodeType]
) -> str | None:
    """Action 을 거슬러 올라가 **실제로 값을 만드는 노드**를 찾는다.

    Action 은 데이터 변환을 하지 않고 부작용만 일으키므로, 그 출력은 곧 그 입력이다.
    입력이 여럿이면 첫 번째를 통과 경로로 본다 — Action 의 통과 값은 하나다.
    """
    seen: set[str] = set()
    current = node_id
    while types.get(current) == "action":
        if current in seen:
            return None  # 순환은 STR-GRAPH-001 이 잡는다
        seen.add(current)
        pn = by_id.get(current)
        if pn is None or not pn.inputs:
            return None
        current = next(iter(pn.inputs.values()))
    return current


def _compare_wiring(
    registry: TypeRegistry,
    *,
    upstream: ScriptContract,
    upstream_id: str,
    downstream: ScriptContract,
    downstream_id: str,
    source_path: str,
) -> list[Finding]:
    out_name = upstream.output_type
    in_name = downstream.input_type
    out_label = f"`{out_name or _UNDECLARED}` (노드 {upstream_id})"
    in_label = f"`{in_name or _UNDECLARED}` (노드 {downstream_id})"

    if not out_name or not in_name:
        return [
            rules.finding(
                "STR-TYPE-004",
                path=source_path,
                node=downstream_id,
                fields={"out": out_label, "in": in_label},
            )
        ]
    try:
        same = registry.same_definition(
            TypeKey(upstream.path, out_name), TypeKey(downstream.path, in_name)
        )
    except StrictlerError as exc:
        return findings_of(exc, path=source_path, node=downstream_id)
    if same:
        return []
    return [
        rules.finding(
            "STR-TYPE-004",
            path=source_path,
            node=downstream_id,
            fields={"out": out_label, "in": in_label},
        )
    ]


# ── 상태 ─────────────────────────────────────────────────────────────────────


def check_state_mapping(
    pipeline: Pipeline,
    contracts: dict[str, ScriptContract],
    source_path: str,
) -> list[Finding]:
    """상태 이름 매핑 (`STR-STATE-001`~`004`).

    노드는 자기 어휘로 필요 상태를 선언(`Args.state` 필드 이름)하고, 파이프라인의
    노드 `states` 가 이름 매핑을 갖는다 → 노드를 파이프라인 간에 그대로 재사용할 수 있다.
    **매핑 누락·존재하지 않는 상태 참조를 로드 시점에 잡는다** (자기 검증적 스키마).

    노드는 상태를 **읽기만** 한다 — 전이는 런타임 몫이다.
    """
    findings: list[Finding] = []
    values = set(pipeline.states.values)

    for name in pipeline.states.values:
        if name.startswith("__"):
            findings.append(
                rules.finding("STR-STATE-001", path=source_path, fields={"name": name})
            )

    if pipeline.states.initial not in values:
        findings.append(
            Finding(
                status="error",
                path=source_path,
                message=(
                    f"`states.initial` 이 `states.values` 에 없습니다: "
                    f"{pipeline.states.initial!r}\n"
                    f"선언된 상태: {', '.join(pipeline.states.values) or '(없음)'}. "
                    "초기 상태가 상태 집합 밖이면 어떤 `when` 도 판정할 수 없습니다."
                ),
            )
        )

    for pn in pipeline.nodes:
        for mapped in pn.states.values():
            if mapped not in values:
                findings.append(
                    rules.finding(
                        "STR-STATE-003",
                        path=source_path,
                        node=pn.id,
                        fields={"name": mapped},
                    )
                )
        contract = contracts.get(pn.id)
        if contract is None:
            continue  # 계약을 모르면 누락·미선언을 판정할 수 없다
        missing = [name for name in contract.state_names if name not in pn.states]
        if missing:
            findings.append(
                rules.finding(
                    "STR-STATE-002",
                    path=source_path,
                    node=pn.id,
                    fields={"names": ", ".join(missing)},
                )
            )
        if pn.when is not None and pn.when.state not in contract.state_names:
            findings.append(
                rules.finding(
                    "STR-STATE-004",
                    path=source_path,
                    node=pn.id,
                    fields={"name": pn.when.state},
                )
            )
    return findings


def check_transitions(pipeline: Pipeline, source_path: str) -> list[Finding]:
    """`transitions.after` 가 실재 노드인지, `to` 가 실재 상태인지
    (`STR-REF-004` / `STR-STATE-005`).

    `transitions` 는 **시간만** 다룬다. 노드 결과에 따른 분기 문법이 없으므로
    여기서 볼 것은 이름 두 개뿐이다.
    """
    findings: list[Finding] = []
    ids = {pn.id for pn in pipeline.nodes}
    values = set(pipeline.states.values)
    for transition in pipeline.transitions:
        if transition.after not in ids:
            findings.append(
                rules.finding(
                    "STR-REF-004", path=source_path, fields={"name": transition.after}
                )
            )
        if transition.to not in values:
            findings.append(
                rules.finding(
                    "STR-STATE-005", path=source_path, fields={"name": transition.to}
                )
            )
    return findings


# ── config ───────────────────────────────────────────────────────────────────


def check_config_decls(pipeline: Pipeline, source_path: str) -> list[Finding]:
    """`config` 선언의 `type` 이 primitive 어휘에 속하는지 (`STR-TYPE-005`).

    **타입 어휘를 두 벌 두지 않는다** — 스크립트와 같은 집합이다
    (`str` `int` `float` `bool` `bytes` `list[T]`). 다만 config 자리에는 dataclass 가
    올 수 없다: 선언할 스크립트가 없다.
    """
    findings: list[Finding] = []
    for name, decl in pipeline.config.items():
        if not _config_type_ok(decl.type):
            findings.append(
                rules.finding(
                    "STR-TYPE-005",
                    path=source_path,
                    node=name,
                    fields={"type": decl.type},
                )
            )
    return findings


def _config_type_ok(expr: str) -> bool:
    try:
        parsed = parse_type(expr)
    except StrictlerError:
        return False
    return _primitive_tree(parsed)


def _primitive_tree(t: TypeRef) -> bool:
    if is_primitive(t):
        return True
    if is_list(t):
        return _primitive_tree(element_type(t))
    return False


def check_config_values(
    pipeline: Pipeline,
    values: Mapping[str, Any],
    source_path: str,
    *,
    env: Mapping[str, str],
) -> tuple[dict[str, Any], list[Finding]]:
    """Spec 이 채운 config 값을 선언과 대조하고 **`default` 를 주입한다**.

    `STR-CONFIG-001`(required 누락) / `-002`(타입 불일치) / `-003`(선언 없는 키) /
    `STR-PATH-004`(`path: true` 인데 경로 규칙 위반).

    **`default` 주입이 여기 책임이다** (MODULES.md R1-6). `refs.expand_config` 가
    받는 config 는 이미 default 가 채워진 것이어야 한다 — 그래야 거기서 못 찾은
    `${config.X}` 가 **진짜 required 누락**이 되고 `STR-CONFIG-001` 재사용이 정당해진다.

    비교 파이프라인의 `targets.<이름>` 오버레이도 같은 선언으로 검사한다.
    required 는 **공통에 있거나 모든 target 에 있으면** 충족된 것으로 본다 —
    target 별로 갈리는 값이 바로 그 자리이기 때문이다 (`schema.md` 12절).
    """
    findings: list[Finding] = []
    resolved: dict[str, Any] = {}

    raw_targets = values.get("targets")
    overlays: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_targets, Mapping):
        overlays = {
            name: scope for name, scope in raw_targets.items() if isinstance(scope, Mapping)
        }

    for key in values:
        if key == "targets" and pipeline.info.kind == "compare":
            continue
        if key not in pipeline.config:
            findings.append(
                rules.finding("STR-CONFIG-003", path=source_path, fields={"name": key})
            )

    for scope_name, scope in overlays.items():
        for key in scope:
            if key not in pipeline.config:
                findings.append(
                    rules.finding(
                        "STR-CONFIG-003",
                        path=source_path,
                        node=f"targets.{scope_name}",
                        fields={"name": key},
                    )
                )

    for name, decl in pipeline.config.items():
        present_everywhere = bool(overlays) and all(
            name in scope for scope in overlays.values()
        )
        if name in values:
            resolved[name] = values[name]
        elif decl.default is not None:
            resolved[name] = decl.default
        elif decl.required and not present_everywhere:
            findings.append(
                rules.finding("STR-CONFIG-001", path=source_path, fields={"names": name})
            )

        for holder, scope_label in _value_holders(name, values, overlays):
            findings.extend(
                _check_one_value(name, decl, holder, scope_label, source_path, env)
            )

    if overlays:
        resolved["targets"] = {name: dict(scope) for name, scope in overlays.items()}
    return resolved, findings


def _value_holders(
    name: str, values: Mapping[str, Any], overlays: Mapping[str, Mapping[str, Any]]
) -> list[tuple[Any, str]]:
    """이 config 이름으로 실제로 들어온 값들 — 공통 + target 오버레이."""
    holders: list[tuple[Any, str]] = []
    if name in values:
        holders.append((values[name], ""))
    for scope_name, scope in overlays.items():
        if name in scope:
            holders.append((scope[name], f"targets.{scope_name}"))
    return holders


def _check_one_value(
    name: str,
    decl: Any,
    value: Any,
    scope_label: str,
    source_path: str,
    env: Mapping[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    if not _matches_type(decl.type, value):
        return [
            rules.finding(
                "STR-CONFIG-002",
                path=source_path,
                node=scope_label,
                fields={"name": name, "declared": decl.type, "given": repr(value)},
            )
        ]
    if not decl.path:
        return findings
    try:
        refs.expand_path(str(value), env)
    except StrictlerError as exc:
        item = rules.finding(
            "STR-PATH-004",
            path=source_path,
            node=scope_label,
            fields={"name": name, "value": repr(value)},
        )
        findings.append(
            item.model_copy(update={"message": f"{exc.message}\n{item.message}"})
        )
    return findings


def _matches_type(expr: str, value: Any) -> bool:
    """선언된 타입 표기와 실제 값이 맞는지. 어휘 밖 표기는 `check_config_decls` 몫이다."""
    try:
        parsed = parse_type(expr)
    except StrictlerError:
        return True
    return _matches(parsed, value)


def _matches(t: TypeRef, value: Any) -> bool:
    if is_list(t):
        return isinstance(value, list) and all(
            _matches(element_type(t), item) for item in value
        )
    if t.name not in PRIMITIVES:
        return True  # 어휘 밖 — STR-TYPE-005 가 따로 잡는다
    if t.name == "bool":
        return isinstance(value, bool)
    if t.name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t.name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t.name == "str":
        return isinstance(value, str)
    return isinstance(value, (bytes, bytearray))


# ── 비교 파이프라인 ──────────────────────────────────────────────────────────


def check_compare(
    pipeline: Pipeline,
    contracts_by_target: dict[str, dict[str, ScriptContract]],
    source_path: str,
) -> list[Finding]:
    """비교 파이프라인 전용 검사 (`STR-REF-005` / `STR-CMP-002` / `-003`).

    **비교가 성립하는 근거는 input/output/state 타입이 노드에 귀속되어 공통이라는 것**이다.
    `script` 경로와 `Args.params` 는 target 별로 갈려도 되지만 나머지는 같아야 한다
    (`schema.md` 12절).

    **대상 개수에 제한이 없다.** 짝지어 비교하는 것이 아니라 **목록 전부가 같은지**를
    묻는다 — 그래서 target 이 셋이든 열이든 하나만 어긋나면 위반이다.

    타입 대조는 **구조로** 한다. target 마다 스크립트가 다르므로 dataclass 이름은
    당연히 갈린다 — 이름으로 비교하면 정상적인 비교 파이프라인이 전부 걸린다.
    """
    findings: list[Finding] = []
    ids = {pn.id for pn in pipeline.nodes}

    if pipeline.info.kind != "compare":
        if pipeline.targets or pipeline.compare:
            findings.append(
                Finding(
                    status="error",
                    path=source_path,
                    message=(
                        "`kind: verify` 인데 `targets` / `compare` 가 채워져 있습니다.\n"
                        "이 둘은 `kind: compare` 전용입니다. 비교 파이프라인이면 "
                        "`info.kind` 를 `compare` 로 바꾸고, 아니면 두 섹션을 지우세요."
                    ),
                )
            )
        return findings

    if len(pipeline.targets) < 2:
        findings.append(
            rules.finding(
                "STR-CMP-003", path=source_path, fields={"count": len(pipeline.targets)}
            )
        )

    for name in pipeline.compare:
        if name not in ids:
            findings.append(
                rules.finding("STR-REF-005", path=source_path, fields={"name": name})
            )

    findings.extend(_check_target_types(pipeline, contracts_by_target, source_path))
    return findings


def _check_target_types(
    pipeline: Pipeline,
    contracts_by_target: dict[str, dict[str, ScriptContract]],
    source_path: str,
) -> list[Finding]:
    """target 별 스크립트의 input/output/state 타입이 **전부** 같은지 (`STR-CMP-002`)."""
    targets = [name for name in pipeline.targets if name in contracts_by_target]
    if len(targets) < 2:
        return []

    everything = [
        contract
        for target in targets
        for contract in contracts_by_target[target].values()
    ]
    registry, findings = build_registry(everything, source_path)
    if registry is None:
        return findings

    for pn in pipeline.nodes:
        present = [t for t in targets if pn.id in contracts_by_target[t]]
        if len(present) < 2:
            continue
        base = contracts_by_target[present[0]][pn.id]
        for target in present[1:]:
            other = contracts_by_target[target][pn.id]
            same, error = _same_io(registry, base, other)
            if error is not None:
                findings.extend(findings_of(error, path=source_path, node=pn.id))
                break
            if not same:
                findings.append(
                    rules.finding(
                        "STR-CMP-002",
                        path=source_path,
                        node=pn.id,
                        fields={"node": pn.id},
                    )
                )
                break
    return findings


def _same_io(
    registry: TypeRegistry, a: ScriptContract, b: ScriptContract
) -> tuple[bool, StrictlerError | None]:
    """`params` 를 뺀 나머지 — input / output / state 가 구조적으로 같은가."""
    if sorted(a.state_names) != sorted(b.state_names):
        return False, None
    for left, right in (
        (a.input_type, b.input_type),
        (a.output_type, b.output_type),
        (a.state_type, b.state_type),
    ):
        if not left or not right:
            if left != right:
                return False, None
            continue
        try:
            if not registry.same_definition(TypeKey(a.path, left), TypeKey(b.path, right)):
                return False, None
        except StrictlerError as exc:
            return False, exc
    return True, None


# ── 전체 ─────────────────────────────────────────────────────────────────────


def build_registry(
    contracts: list[ScriptContract], source_path: str
) -> tuple[TypeRegistry | None, list[Finding]]:
    """계약들이 선언한 dataclass 를 전부 등록기에 넣고 정규화한다.

    **키가 `(origin, name)`** 이므로 노드마다 있는 `Args` 가 충돌하지 않는다.
    정규화 중 순환 참조(`STR-TYPE-007`)·미지 타입(`STR-TYPE-003`)이 나오면 그때
    등록기가 규칙 id 를 붙여 던지고, 여기서 `Finding` 으로 받는다.
    """
    registry = TypeRegistry()
    try:
        for contract in contracts:
            for spec in contract.dataclasses.values():
                registry.register(spec)
        registry.normalize()
    except StrictlerError as exc:
        return None, findings_of(exc, path=source_path)
    return registry, []


def check_pipeline(
    pipeline: Pipeline,
    source_path: str,
    *,
    store: Store,
    env: Mapping[str, str],
) -> tuple[dict[str, ScriptContract], list[Finding]]:
    """파이프라인 하나의 등록 시 정적 검사 전체.

    참조된 노드들을 전부 로드·검사해 `{노드 id: ScriptContract}` 를 만들고,
    그걸 재료로 배선 타입·상태 매핑·비교 계약·도달 가능성을 본다.

    **실패를 최대한 모은다.** 한 노드가 깨져도 나머지는 전부 검사한다 —
    한 번의 실행에서 확인 가능한 것을 다 모으는 것이 lint 의 일이다.
    """
    findings: list[Finding] = []
    contracts: dict[str, ScriptContract] = {}
    node_types: dict[str, NodeType] = {}
    loaded: dict[str, Node] = {}

    seen: set[str] = set()
    for pn in pipeline.nodes:
        if pn.id in seen:
            findings.append(
                Finding(
                    status="error",
                    path=source_path,
                    node=pn.id,
                    message=(
                        f"노드 id 가 중복됩니다: {pn.id!r}\n"
                        "`inputs` 가 id 로 배선을 만드므로 id 는 파이프라인 안에서 "
                        "유일해야 합니다. 한쪽 이름을 바꾸세요."
                    ),
                )
            )
        seen.add(pn.id)

    for pn in pipeline.nodes:
        node, node_findings = _load_referenced_node(
            pn.source, store=store, env=env, source_path=source_path, node_id=pn.id
        )
        findings.extend(node_findings)
        if node is None:
            continue
        loaded[pn.id] = node
        node_types[pn.id] = node.type
        contract, contract_findings = node_checks.check_node(
            node, source_path, store=store, env=env
        )
        findings.extend(
            item.model_copy(update={"node": item.node or pn.id})
            for item in contract_findings
        )
        if contract is not None:
            contracts[pn.id] = contract

    for pn in pipeline.nodes:
        for producer in pn.inputs.values():
            if producer not in seen:
                findings.append(
                    rules.finding(
                        "STR-REF-003",
                        path=source_path,
                        node=pn.id,
                        fields={"name": producer},
                    )
                )

    dag = build_dag(pipeline)
    # 데이터를 안 내놓아도 제 몫을 하는 자리 둘 — 상태를 미는 노드와 비교 대상 노드.
    # 이걸 "고립" 이라 부르고 제거를 권하면 파이프라인이 망가진다.
    driven = {transition.after for transition in pipeline.transitions}
    driven |= set(pipeline.compare)
    findings.extend(check_cycle(dag, source_path, exempt=driven))
    findings.extend(check_state_mapping(pipeline, contracts, source_path))
    findings.extend(check_transitions(pipeline, source_path))
    findings.extend(check_config_decls(pipeline, source_path))

    registry, registry_findings = build_registry(list(contracts.values()), source_path)
    findings.extend(registry_findings)
    if registry is not None:
        findings.extend(
            check_wiring_types(
                pipeline, contracts, registry, source_path, node_types=node_types
            )
        )

    findings.extend(
        check_compare(
            pipeline,
            _contracts_by_target(pipeline, loaded, store=store, env=env),
            source_path,
        )
    )

    findings.extend(
        reachability.check_reachability(
            pipeline, {pn.id: dict(pn.states) for pn in pipeline.nodes}, source_path
        )
    )
    return contracts, dedupe(findings)


def _load_referenced_node(
    value: str,
    *,
    store: Store,
    env: Mapping[str, str],
    source_path: str,
    node_id: str,
) -> tuple[Node | None, list[Finding]]:
    """파이프라인 노드 항목의 `source` 를 실제 노드로 로드한다."""
    if refs.is_ref(value):
        try:
            refs.parse_ref(value, "node")
        except StrictlerError as exc:
            return None, findings_of(exc, path=source_path, node=node_id)
        entry_id = value[len("${ref.") : -1]
        try:
            store.show(entry_id)
        except StrictlerError:
            return None, [
                rules.finding(
                    "STR-REG-002",
                    path=source_path,
                    node=node_id,
                    fields={"id": entry_id},
                )
            ]
        path = store.path_of(entry_id)
    else:
        try:
            path = refs.expand_path(value, env)
        except StrictlerError as exc:
            return None, findings_of(exc, path=source_path, node=node_id)

    if not path.is_file():
        return None, [
            rules.finding(
                "STR-REF-002", path=source_path, node=node_id, fields={"source": value}
            )
        ]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [
            Finding(
                status="error",
                path=source_path,
                node=node_id,
                message=(
                    f"노드 파일을 읽을 수 없습니다: {path} ({exc})\n"
                    "노드 파일은 UTF-8 JSON 이어야 합니다."
                ),
            )
        ]
    if not isinstance(raw, dict):
        return None, [
            Finding(
                status="error",
                path=source_path,
                node=node_id,
                message=(
                    f"노드 파일의 최상위가 객체가 아닙니다: {path}\n"
                    "`info` / `type` / `script` 를 갖는 JSON 객체여야 합니다."
                ),
            )
        ]
    return node_checks.load_node(raw, str(path))


def _contracts_by_target(
    pipeline: Pipeline,
    loaded: Mapping[str, Node],
    *,
    store: Store,
    env: Mapping[str, str],
) -> dict[str, dict[str, ScriptContract]]:
    """`kind: compare` 일 때 target 별 계약을 모은다.

    target 별 스크립트는 `${config.X}` 로 갈리고 그 값은 **Spec 이 채운다**.
    등록 시점에 알 수 있는 것은 파이프라인이 선언한 `default` 뿐이므로, 그걸로
    풀리는 것만 모은다. 안 풀리는 것은 **오류가 아니라 "아직 모름"** 이다 —
    실행 시점에 진짜 값으로 다시 검사한다.
    """
    if pipeline.info.kind != "compare":
        return {}
    defaults = {
        name: decl.default
        for name, decl in pipeline.config.items()
        if decl.default is not None
    }
    gathered: dict[str, dict[str, ScriptContract]] = {}
    for target in pipeline.targets:
        for node_id, node in loaded.items():
            path, resolve_findings = node_checks.resolve_script(
                node, store=store, env=env, config=defaults, target=target
            )
            if path is None or resolve_findings:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            contract, _ = script_checks.extract_contract(source, str(path))
            gathered.setdefault(target, {})[node_id] = contract
    return gathered
