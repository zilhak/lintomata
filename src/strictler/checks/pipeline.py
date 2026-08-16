"""파이프라인 JSON 로드와 검증 — **파이프라인 등록 시** (`schema.md` 13절).

| 검증 | 규칙 |
|---|---|
| `source` 가 가리키는 노드가 실재하는지 | `STR-REF-002` |
| `${ref.<id>}` 접두가 맞는지 | `STR-REG-003` |
| `inputs` 가 가리키는 노드 id 가 실재하는지 | `STR-REF-003` |
| DAG 에 순환이 없는지 | `STR-GRAPH-001` |
| 등록된 dataclass 집합 정규화 후 **input 정의 == output 정의**인지 | `STR-TYPE-004` |
| 노드 `states` 매핑이 빠짐없고 대상이 `states.values` 에 실재하는지 | `STR-STATE-002` / `-003` |
| `when` 이 참조하는 상태 id 가 스크립트의 `Args.state` 에 선언됐는지 | `STR-STATE-004` |
| `transitions.after` 가 실재 노드 id 인지, `to` 가 실재 상태인지 | `STR-REF-004` / `STR-STATE-005` |
| 사용자 상태 이름에 `__` 접두가 없는지 | `STR-STATE-001` |
| `config` 선언의 `type` 이 primitive 집합에 속하는지 | `STR-TYPE-005` |
| `kind: compare` 일 때 `compare` 가 가리키는 노드가 실재하는지 | `STR-REF-005` |
| `kind: compare` 일 때 **target 별 스크립트가 같은 input/output/state 타입을 선언했는지** | `STR-CMP-002` |
| `targets` 가 2개 이상인지 | `STR-CMP-003` |

도달 가능성(`STR-STATE-006` / `-007`)은 `checks.reachability` 가 맡는다.

**`inputs` 가 DAG 를 만든다.** 별도 `edges` 섹션이 없다 — 입력 참조가 곧 의존 관계다.

⚠ stub. Step 2 에서 구현한다.
"""

from __future__ import annotations

from typing import Any, Mapping

from strictler.checks.script import ScriptContract
from strictler.errors import Finding
from strictler.model import Pipeline
from strictler.store.entries import Store
from strictler.typesys.registry import TypeRegistry

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
]


def load_pipeline(raw: Mapping[str, Any], path: str) -> tuple[Pipeline | None, list[Finding]]:
    """JSON dict 를 `Pipeline` 모델로 로드한다. pydantic 검증 실패를 `Finding` 으로 바꾼다."""
    raise NotImplementedError("Step 2에서 구현")


def build_dag(pipeline: Pipeline) -> dict[str, list[str]]:
    """`{노드 id: 그 노드가 의존하는 노드 id 들}`.

    `inputs` 의 값이 곧 엣지다.
    """
    raise NotImplementedError("Step 2에서 구현")


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
    """
    raise NotImplementedError("Step 2에서 구현")


def check_cycle(dag: dict[str, list[str]], source_path: str) -> list[Finding]:
    """순환 판정 (`STR-GRAPH-001`). 순환 경로를 메시지에 넣는다.

    고립 노드(`STR-GRAPH-002`)도 여기서 함께 본다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_wiring_types(
    pipeline: Pipeline,
    contracts: dict[str, ScriptContract],
    registry: TypeRegistry,
    source_path: str,
) -> list[Finding]:
    """배선된 두 노드의 **선언된 정의가 동일한지** (`STR-TYPE-004`).

    **엄격한 동일성**이다. 부분집합 병합은 런타임 표현 층에서만 일어나고
    그래프 검사를 느슨하게 만들지 않는다 (`schema.md` 7절).

    **Action 은 투명하다** — `X ──▶ Action ──▶ Y` 는 실은 `X ──▶ Y` 이므로
    Action 을 건너뛰고 상·하단의 계약을 대조한다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_state_mapping(
    pipeline: Pipeline,
    contracts: dict[str, ScriptContract],
    source_path: str,
) -> list[Finding]:
    """상태 이름 매핑 (`STR-STATE-001`~`004`).

    노드는 자기 어휘로 필요 상태를 선언(`Args.state` 필드 이름)하고, 파이프라인의
    노드 `states` 가 이름 매핑을 갖는다 → 노드를 파이프라인 간에 그대로 재사용할 수 있다.
    **매핑 누락·존재하지 않는 상태 참조를 로드 시점에 잡는다.**
    """
    raise NotImplementedError("Step 2에서 구현")


def check_transitions(pipeline: Pipeline, source_path: str) -> list[Finding]:
    """`transitions.after` 가 실재 노드인지, `to` 가 실재 상태인지
    (`STR-REF-004` / `STR-STATE-005`)."""
    raise NotImplementedError("Step 2에서 구현")


def check_config_decls(pipeline: Pipeline, source_path: str) -> list[Finding]:
    """`config` 선언의 `type` 이 primitive 어휘에 속하는지 (`STR-TYPE-005`)."""
    raise NotImplementedError("Step 2에서 구현")


def check_compare(
    pipeline: Pipeline,
    contracts_by_target: dict[str, dict[str, ScriptContract]],
    source_path: str,
) -> list[Finding]:
    """비교 파이프라인 전용 검사 (`STR-REF-005` / `STR-CMP-002` / `-003`).

    **비교가 성립하는 근거는 input/output/state 타입이 노드에 귀속되어 공통이라는 것**이다.
    `script` 경로와 `Args.params` 는 target 별로 갈려도 되지만 나머지는 같아야 한다
    (`schema.md` 12절).
    """
    raise NotImplementedError("Step 2에서 구현")
