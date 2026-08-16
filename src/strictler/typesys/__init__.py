"""타입 시스템 — 좁게 강제한다 (`schema.md` 7절).

**내장 의미 타입(`Button` 같은 것)은 없다.** 하지만 타입 체계는 있고,
쓸 수 있는 타입을 강제해 범위를 좁힌다.

- `primitives` — 허용 타입 어휘(`int` `float` `str` `bool` `bytes` `list[T]`)와 파싱
- `registry` — dataclass 등록기, 집합 정규화, 부분집합 병합, 그래프 검사용 동일성 판정

**★ 그래프 검사와 데이터 취급은 서로 다른 층이다:**

| 층 | 대상 | 규칙 |
|---|---|---|
| 그래프 검사 (정적) | 선언된 정의 | input 정의 **==** output 정의. 엄격한 동일성 |
| 데이터 취급 (런타임) | 표현 | 부분집합 관계인 것들은 상위 큰 dataclass 하나를 같이 써버린다 |
"""

from __future__ import annotations

from strictler.typesys.primitives import (
    FORBIDDEN,
    PRIMITIVES,
    TypeRef,
    check_allowed,
    element_type,
    is_list,
    is_primitive,
    parse_type,
)
from strictler.typesys.registry import DataclassSpec, FieldSpec, TypeRegistry

__all__ = [
    "FORBIDDEN",
    "PRIMITIVES",
    "TypeRef",
    "check_allowed",
    "element_type",
    "is_list",
    "is_primitive",
    "parse_type",
    "DataclassSpec",
    "FieldSpec",
    "TypeRegistry",
]
