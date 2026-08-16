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

**★ `engine.runtime` 을 import 하지 마라.** 공용 결과 타입(`RunResult`/`NodeOutcome`)은
`engine.result` 에 있다. `runtime` 이 `kind` 를 보고 이쪽으로 디스패치하므로,
반대 방향 import 를 만들면 순환이 된다.

⚠ stub. Step 3 에서 구현한다.
"""

from __future__ import annotations

from typing import Any, Mapping

from strictler.engine.result import RunResult
from strictler.model import Pipeline
from strictler.report import CompareReport
from strictler.store.entries import Store

__all__ = [
    "resolve_target_config",
    "run_compare_pipeline",
    "collect_target_values",
    "all_same",
]


def resolve_target_config(config: Mapping[str, Any], target: str) -> dict[str, Any]:
    """target `T` 로 도는 동안의 config 를 만든다.

    **`targets.T` 에서 먼저 찾고, 없으면 공통에서** 찾는다. 둘 다 없으면 `STR-CMP-004`.
    """
    raise NotImplementedError("Step 3에서 구현")


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
    출력 위치는 Spec `plan` 항목의 `report` 다.
    """
    raise NotImplementedError("Step 3에서 구현")


def collect_target_values(result: RunResult, node_id: str) -> dict[str, Any]:
    """한 노드의 `{target: 출력값}` 을 꺼낸다."""
    raise NotImplementedError("Step 3에서 구현")


def all_same(values: Mapping[str, Any]) -> bool:
    """전부 같은 값인지. **엔진은 `==` 만 안다.**

    "둘을 짝지어 비교"가 아니라 **전체가 한 값으로 일치하느냐**를 묻는다.
    비교는 `Percept` 층에서 한다 — `Sensum` 은 비교 대상이 아니다.
    """
    raise NotImplementedError("Step 3에서 구현")
