"""등록소 — strictler 가 파일을 관리한다 (`schema.md` 2절).

스크립트 / 노드 / 파이프라인 / Spec 넷 다 등록한다. 등록하면 `$STRICTLER_HOME`
(기본 `~/.strictler`) 아래로 **파일이 복사되고 해시가 함께 저장된다.**
사용자는 원본을 지워도 된다.

```
$STRICTLER_HOME/
  registry.json          인덱스 — id · 이름 · 종류 · 해시 · 등록시각 · 참조
  scripts/    sc_a1b2c3d4.py
  nodes/      nd_e5f6a7b8.json
  pipelines/  pl_c9d0e1f2.json
  specs/      sp_3a4b5c6d.json
```

**등록은 편의 기능이 아니라 검증 결과를 재사용하는 기제다.**
해시가 그대로면 이미 검증을 통과한 파일이므로 다시 검사하지 않는다.

- `entries` — 인덱스와 CRUD
- `graph` — 참조 그래프, 역방향 추적, 깨짐 판정
"""

from __future__ import annotations

from strictler.store.entries import (
    SUBDIRS,
    RegistryEntry,
    RegistryIndex,
    Store,
    default_home,
    hash_file,
    new_id,
)
from strictler.store.graph import RefGraph

__all__ = [
    "SUBDIRS",
    "RegistryEntry",
    "RegistryIndex",
    "Store",
    "default_home",
    "hash_file",
    "new_id",
    "RefGraph",
]
