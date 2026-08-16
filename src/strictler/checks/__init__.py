"""정적 검사 — **등록/수정 시점에 돈다** (`schema.md` 13절).

검사에 걸리면 **명확한 에러를 뱉고 등록/수정이 실패**한다. 잘못된 것이 저장되지 않는다.

| 시점 | 대상 | 실패하면 |
|---|---|---|
| **노드 등록** | 노드 JSON + 그 스크립트 | 등록 실패 — 저장되지 않는다 |
| **파이프라인 등록** | 파이프라인 JSON + 참조된 노드들 | 등록 실패 |
| **Spec 실행** | config 채움 + 경로 전개 + `tool` + 해시 대조 | 실행 실패 |

**등록 검사는 스크립트를 안 돌린다**(형식·선언·금지 패턴).
**단위테스트는 돌린다**(선언대로 동작하는가) — `strictler.testing`.

→ AI 저작 워크플로우의 안전망이 여기 있다. **잘못 쓴 순간 걸리고, 돌려보기 전에 자기 수정한다.**

- `script` — 스크립트 AST 검사 (노드 계약·타입·금지 패턴)
- `node` — 노드 JSON 로드와 검증
- `pipeline` — 파이프라인 JSON 로드와 검증 (DAG·배선 타입·상태 매핑·비교 계약)
- `reachability` — 도달 가능성 판정기

⚠ stub. Step 2 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path

from strictler.errors import Finding
from strictler.model import EntryKind
from strictler.store.entries import Store

__all__ = ["check_registration"]


def check_registration(kind: EntryKind, source: Path, store: Store) -> list[Finding]:
    """등록/수정 시점의 정적 검사 진입점. 종류에 맞는 검사기로 넘긴다.

    빈 목록이면 통과 — 그때만 등록소에 저장된다.
    스크립트는 그 자체로도 검사되지만 노드 타입을 알아야 하는 검사
    (Reckon 기댓값 필드, Action input==output)는 노드 등록 시에 돈다.
    """
    raise NotImplementedError("Step 2에서 구현")
