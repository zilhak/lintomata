"""값 검증 파이프라인 구동과 Spec 단위 실행 (`schema.md` 9·11·13절).

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

**★ `engine.compare` 를 top-level 로 import 하지 마라.** 공용 결과 타입은
`engine.result` 에 있고 `compare` 도 거기에만 의존한다. `kind: compare` 디스패치는
`run_plan_item` **안에서 지역 import** 로 한다 — 양방향 top-level import 는
`ImportError` 로 터진다.

⚠ stub. Step 3 에서 구현한다.
"""

from __future__ import annotations

from typing import Any, Mapping

from strictler.engine.result import NodeOutcome, RunResult
from strictler.errors import Finding
from strictler.model import Pipeline, Spec
from strictler.report import Report
from strictler.store.entries import Store

__all__ = ["NodeOutcome", "RunResult", "run_spec", "run_plan_item", "run_pipeline", "propagate_not_run", "topo_order"]


def run_spec(
    spec: Spec,
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
) -> Report:
    """Spec 하나를 실행해 리포트를 만든다. `strictler check <spec-id>` 의 본체.

    실행 시 검증(`schema.md` 13절): config required 채움·타입, 경로 전개,
    `path: true` config, `tool` 선언, `kind: compare` 인데 `report` 없음,
    **등록소 파일 해시 대조**, 참조 id 삭제 여부.

    **한 `plan` 항목이 실패해도 다른 항목은 전부 돈다.**
    """
    raise NotImplementedError("Step 3에서 구현")


def run_plan_item(
    spec: Spec,
    index: int,
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
) -> list[Finding]:
    """`plan` 항목 하나를 실행한다. `kind` 를 보고 값 검증/비교로 갈린다.

    `path` 필드는 `"login.json > plan[0] > login-flow"` 형태로 여기서 만들어진다.

    **`kind: compare` 분기는 여기서 지역 import 로 한다:**

    ```python
    from strictler.engine.compare import run_compare_pipeline
    ```

    top-level 로 올리면 `runtime` ↔ `compare` 순환이 된다.
    """
    raise NotImplementedError("Step 3에서 구현")


def run_pipeline(
    pipeline: Pipeline,
    config: Mapping[str, Any],
    *,
    store: Store,
    env: Mapping[str, str],
    started_at_ms: int,
    path: str,
) -> RunResult:
    """값 검증 파이프라인 한 벌을 구동한다.

    위상 순서로 돌면서 상태머신을 함께 전개한다. 노드가 실패하면 그 지점에서
    진행하지 않고, 끝난 뒤 `propagate_not_run()` 으로 여파를 표기한다.

    **조건 분기는 엔진 문법이 없다** — "앞단 결과가 이러면 아무것도 안 한다"는
    스크립트가 `input` 을 그대로 반환하는 것으로 표현된다. **엔진에는 skip 개념이 없다.**
    """
    raise NotImplementedError("Step 3에서 구현")


def propagate_not_run(
    pipeline: Pipeline,
    result: RunResult,
    path: str,
) -> list[Finding]:
    """실패의 여파를 **전수 검사해서** `not_run` 으로 바꾼다 (`schema.md` 9절).

    데이터 의존과 상태 의존 두 경로를 모두 훑는다. **원인 노드는 바꾸는 그 시점에
    적는다** — `Finding.cause` 에 `{node, reason}`.
    """
    raise NotImplementedError("Step 3에서 구현")


def topo_order(dag: dict[str, list[str]]) -> list[str]:
    """의존 순서. 순환은 등록 시 이미 걸러졌으므로 여기선 없다고 본다."""
    raise NotImplementedError("Step 3에서 구현")
