"""허용 타입 어휘와 타입 표현 파싱 (`schema.md` 7절).

쓸 수 있는 것은 둘뿐이다:

| | 무엇 |
|---|---|
| **primitive** | `int` `float` `str` `bool` `bytes` `list[T]` |
| **노드 사전 선언 타입** | 복합 타입은 **무조건 `dataclass`**. C++ 의 `struct` 같은 자리 |

- **`dict` 금지** (`STR-TYPE-001`) — 허용하면 "복합은 dataclass 강제"가 한 줄로 무의미해진다
- **`None` / `Optional` 금지** (`STR-TYPE-002`) — "있을 수도 없을 수도"가 부분집합 규칙과
  겹쳐 판정이 흐려진다
- `bytes` 는 스크린샷, `list[T]` 는 버튼 목록 때문에 필요하다

**파이프라인 `config` 선언의 `type` 도 같은 어휘를 쓴다** (`STR-TYPE-005`) —
타입 어휘를 두 벌 두지 않는다.

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from strictler.errors import Finding

__all__ = [
    "PRIMITIVES",
    "FORBIDDEN",
    "TypeRef",
    "parse_type",
    "is_primitive",
    "is_list",
    "element_type",
    "check_allowed",
]


PRIMITIVES: frozenset[str] = frozenset({"int", "float", "str", "bool", "bytes"})
"""`list[T]` 는 매개변수를 가지므로 여기 없다 — `is_list()` 로 따로 본다."""

FORBIDDEN: frozenset[str] = frozenset({"dict", "Dict", "Optional", "None", "NoneType", "Any"})
"""이름만 보고 즉시 거절하는 것들. `dict` → `STR-TYPE-001`, `Optional`/`None` → `STR-TYPE-002`."""


class TypeRef:
    """파싱된 타입 표현 하나.

    필드: `name`(`"int"` / `"list"` / dataclass 이름), `args`(`list[T]` 의 `T` 들).
    `list[Button]` 이면 `name="list"`, `args=(TypeRef("Button"),)`.
    """

    def __init__(self, name: str, args: tuple[TypeRef, ...] = ()) -> None:
        raise NotImplementedError("Step 1에서 구현")

    def __str__(self) -> str:
        """`"list[Button]"` 처럼 원래 표기로 되돌린다. 에러 메시지에 쓴다."""
        raise NotImplementedError("Step 1에서 구현")


def parse_type(expr: str) -> TypeRef:
    """`"list[Button]"` 같은 타입 표기를 `TypeRef` 로 파싱한다.

    AST 검사기(`checks.script`)와 파이프라인 `config` 검증이 같이 쓴다.
    """
    raise NotImplementedError("Step 1에서 구현")


def is_primitive(t: TypeRef) -> bool:
    """`int` `float` `str` `bool` `bytes` 중 하나인지."""
    raise NotImplementedError("Step 1에서 구현")


def is_list(t: TypeRef) -> bool:
    """`list[T]` 인지."""
    raise NotImplementedError("Step 1에서 구현")


def element_type(t: TypeRef) -> TypeRef:
    """`list[T]` 의 `T`. 리스트가 아니면 오류."""
    raise NotImplementedError("Step 1에서 구현")


def check_allowed(t: TypeRef, *, known: frozenset[str], path: str, node: str = "") -> list[Finding]:
    """타입 하나가 허용 집합에 드는지 본다.

    `known` 은 그 스크립트가 선언한 dataclass 이름들. primitive 도 `list[T]` 도
    `known` 도 아니면 `STR-TYPE-003`, `dict` 면 `STR-TYPE-001`,
    `Optional`/`None` 이면 `STR-TYPE-002`.
    """
    raise NotImplementedError("Step 1에서 구현")
