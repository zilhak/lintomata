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
"""

from __future__ import annotations

import re

from strictler import rules
from strictler.errors import Finding, StrictlerError

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


_DICT_NAMES: frozenset[str] = frozenset({"dict", "Dict"})
_OPTIONAL_NAMES: frozenset[str] = frozenset({"Optional", "None", "NoneType"})

_UNION = "Union"
"""`A | B` 표기를 담는 내부 이름. 허용 어휘가 아니므로 언제나 거절된다."""

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class TypeRef:
    """파싱된 타입 표현 하나.

    필드: `name`(`"int"` / `"list"` / dataclass 이름), `args`(`list[T]` 의 `T` 들).
    `list[Button]` 이면 `name="list"`, `args=(TypeRef("Button"),)`.
    """

    __slots__ = ("name", "args")

    def __init__(self, name: str, args: tuple[TypeRef, ...] = ()) -> None:
        self.name = name
        self.args = tuple(args)

    @property
    def base(self) -> str:
        """모듈 수식을 뗀 이름. `typing.Optional` → `Optional`."""
        return self.name.rsplit(".", 1)[-1]

    def __str__(self) -> str:
        """`"list[Button]"` 처럼 원래 표기로 되돌린다. 에러 메시지에 쓴다."""
        if not self.args:
            return self.name
        if self.name == _UNION:
            return " | ".join(str(a) for a in self.args)
        return f"{self.name}[{', '.join(str(a) for a in self.args)}]"

    def __repr__(self) -> str:
        return f"TypeRef({str(self)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeRef):
            return NotImplemented
        return self.name == other.name and self.args == other.args

    def __hash__(self) -> int:
        return hash((self.name, self.args))


def parse_type(expr: str) -> TypeRef:
    """`"list[Button]"` 같은 타입 표기를 `TypeRef` 로 파싱한다.

    AST 검사기(`checks.script`)와 파이프라인 `config` 검증이 같이 쓴다.
    `A | B` 표기도 받아들인다 — 어휘로는 거절되지만, 파싱 단계에서 터지면
    `STR-TYPE-002` 같은 제대로 된 규칙 대신 도구 오류가 나기 때문이다.
    """
    text = expr.strip()
    if not text:
        raise StrictlerError(
            "타입 표기가 비어 있습니다. "
            "`int` `float` `str` `bool` `bytes` `list[T]` 또는 선언한 dataclass 이름을 쓰세요."
        )
    node, pos = _parse_union(text, 0)
    pos = _skip_ws(text, pos)
    if pos != len(text):
        raise StrictlerError(
            f"타입 표기 {expr!r} 를 해석할 수 없습니다 ({pos} 번째 글자 뒤가 남았습니다). "
            "`list[Button]` 처럼 이름과 대괄호만으로 쓰세요."
        )
    return node


def is_primitive(t: TypeRef) -> bool:
    """`int` `float` `str` `bool` `bytes` 중 하나인지."""
    return not t.args and t.name in PRIMITIVES


def is_list(t: TypeRef) -> bool:
    """`list[T]` 인지. 매개변수 없는 맨 `list` 는 `T` 를 모르므로 아니다."""
    return t.name == "list" and len(t.args) == 1


def element_type(t: TypeRef) -> TypeRef:
    """`list[T]` 의 `T`. 리스트가 아니면 오류."""
    if not is_list(t):
        raise StrictlerError(
            f"{t} 는 `list[T]` 가 아니므로 원소 타입이 없습니다."
        )
    return t.args[0]


def check_allowed(t: TypeRef, *, known: frozenset[str], path: str, node: str = "") -> list[Finding]:
    """타입 하나가 허용 집합에 드는지 본다.

    `known` 은 그 스크립트가 선언한 dataclass 이름들. primitive 도 `list[T]` 도
    `known` 도 아니면 `STR-TYPE-003`, `dict` 면 `STR-TYPE-001`,
    `Optional`/`None` 이면 `STR-TYPE-002`.
    """
    base = t.base

    if base in _DICT_NAMES:
        return [rules.finding("STR-TYPE-001", path=path, node=node, type=str(t))]
    if base in _OPTIONAL_NAMES:
        return [rules.finding("STR-TYPE-002", path=path, node=node, type=str(t))]

    if t.name == _UNION:
        # `str | None` 은 안쪽 `None` 이 STR-TYPE-002 를 낸다. 그 밖의 합집합은 어휘 밖이다.
        inner: list[Finding] = []
        for arg in t.args:
            inner.extend(check_allowed(arg, known=known, path=path, node=node))
        return inner or [rules.finding("STR-TYPE-003", path=path, node=node, type=str(t))]

    if is_primitive(t):
        return []
    if is_list(t):
        return check_allowed(element_type(t), known=known, path=path, node=node)
    if base in known and not t.args:
        return []
    return [rules.finding("STR-TYPE-003", path=path, node=node, type=str(t))]


# --- 파서 내부 ------------------------------------------------------------


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _parse_union(text: str, pos: int) -> tuple[TypeRef, int]:
    parts: list[TypeRef] = []
    node, pos = _parse_single(text, pos)
    parts.append(node)
    while True:
        pos = _skip_ws(text, pos)
        if pos < len(text) and text[pos] == "|":
            node, pos = _parse_single(text, pos + 1)
            parts.append(node)
            continue
        break
    if len(parts) == 1:
        return parts[0], pos
    return TypeRef(_UNION, tuple(parts)), pos


def _parse_single(text: str, pos: int) -> tuple[TypeRef, int]:
    pos = _skip_ws(text, pos)
    match = _IDENT_RE.match(text, pos)
    if match is None:
        raise StrictlerError(
            f"타입 표기 {text!r} 의 {pos} 번째 위치에서 타입 이름을 찾지 못했습니다. "
            "`int` `float` `str` `bool` `bytes` `list[T]` 또는 선언한 dataclass 이름을 쓰세요."
        )
    name = match.group(0)
    pos = _skip_ws(text, match.end())

    args: list[TypeRef] = []
    if pos < len(text) and text[pos] == "[":
        pos += 1
        while True:
            arg, pos = _parse_union(text, pos)
            args.append(arg)
            pos = _skip_ws(text, pos)
            if pos < len(text) and text[pos] == ",":
                pos += 1
                continue
            if pos < len(text) and text[pos] == "]":
                pos += 1
                break
            raise StrictlerError(
                f"타입 표기 {text!r} 의 대괄호가 닫히지 않았습니다. `list[Button]` 처럼 쓰세요."
            )
    return TypeRef(name, tuple(args)), pos
