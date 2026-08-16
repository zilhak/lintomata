"""dataclass 등록기 — 집합 정규화, 부분집합 병합, 그래프 검사용 동일성 판정.

`schema.md` 7절이 근거다. 이름이 `registry` 지만 **등록소(`strictler.store`)와 무관하다** —
이건 *타입 등록기*다.

**엔진은 구성 시점에 모든 dataclass 를 등록하고 집합 검사를 전체에 건다.**
각 dataclass 를 **`(필드명, 타입)` 쌍의 집합**으로 다루면 별도 규칙이 필요 없어진다:

| | 왜 규칙이 필요 없나 |
|---|---|
| 필드 순서 | 집합이므로 애초에 의미가 없다 |
| 이름만 vs 이름+타입 | 원소가 `(이름, 타입)` 쌍이므로 자동 |
| 중첩 dataclass | 중첩 필드 타입도 등록된 dataclass 이므로 **위상 정렬해 바닥부터 정규화**하면 재귀가 저절로 된다 |

**병합 단위: 부분집합 격자의 연결 성분 전체를 합집합으로 병합한다.**
`A ⊂ B`, `A ⊂ C`, `B`·`C` 무관 — "가장 큰 것"이 유일하지 않지만, **그래프 검사가
선언된 정의로 이뤄지므로 어느 쪽으로 병합해도 정확성에 영향이 없다.** 연결 성분을
통째로 합집합 내면 모호함 자체가 생기지 않고 잃는 것도 없다.

⚠ 오배선 탐지력이 약해지는 것은 **감수한다**. `ButtonCount(count:int)` 와
`MenuCount(count:int)` 는 동일하다. 배선은 파이프라인 JSON 에 노드 id 로 명시적으로
쓰므로 타입 검사가 잡아주길 기대할 실수가 아니고, 값의 의미는 Reckon 이 잡는다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from strictler.errors import StrictlerError
from strictler.typesys.primitives import PRIMITIVES, TypeRef, element_type, is_list, is_primitive

__all__ = ["FieldSpec", "DataclassSpec", "TypeRegistry"]


_PY_PRIMITIVES: dict[str, type] = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "bytes": bytes,
}


class FieldSpec:
    """dataclass 필드 하나. 필드: `name`, `type`(`TypeRef`)."""

    __slots__ = ("name", "type")

    def __init__(self, name: str, type: TypeRef) -> None:  # noqa: A002 - 계약상 이름 고정
        self.name = name
        self.type = type

    def __repr__(self) -> str:
        return f"FieldSpec({self.name!r}, {self.type!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FieldSpec):
            return NotImplemented
        return self.name == other.name and self.type == other.type

    def __hash__(self) -> int:
        return hash((self.name, self.type))


class DataclassSpec:
    """스크립트가 선언한 dataclass 하나.

    필드: `name`, `fields`(`tuple[FieldSpec, ...]`), `origin`(어느 스크립트에서 왔는지).
    """

    __slots__ = ("name", "fields", "origin")

    def __init__(self, name: str, fields: tuple[FieldSpec, ...], origin: str = "") -> None:
        self.name = name
        self.fields = tuple(fields)
        self.origin = origin

    def __repr__(self) -> str:
        return f"DataclassSpec({self.name!r}, {self.fields!r}, origin={self.origin!r})"

    def raw_set(self) -> frozenset[tuple[str, str]]:
        """정규화 전의 `(필드명, 선언 표기)` 집합. 중복 등록 판정에만 쓴다."""
        return frozenset((f.name, str(f.type)) for f in self.fields)


class TypeRegistry:
    """모든 노드의 dataclass 선언을 모아 집합 검사를 거는 등록기.

    사용 순서: `register()` 를 전부 부른 뒤 `normalize()` 한 번 → 이후 조회.
    """

    def __init__(self) -> None:
        self._specs: dict[str, DataclassSpec] = {}
        self._normalized = False
        # 정규화 산출물
        self._struct: dict[str, str] = {}
        """dataclass 이름 → 구조 서명. 이름이 아니라 구조로 비교하기 위한 것."""
        self._fields: dict[str, dict[str, TypeRef]] = {}
        self._canon_fields: dict[str, frozenset[tuple[str, str]]] = {}
        # 병합 산출물 (지연 계산)
        self._merge_map: dict[str, str] | None = None
        self._merged_fields: dict[str, dict[str, TypeRef]] = {}
        self._models: dict[str, type[BaseModel]] = {}

    # --- 등록 ------------------------------------------------------------

    def register(self, spec: DataclassSpec) -> None:
        """dataclass 선언 하나를 등록한다. 같은 이름이 다른 정의로 오면 오류."""
        existing = self._specs.get(spec.name)
        if existing is not None:
            if existing.raw_set() != spec.raw_set():
                raise StrictlerError(
                    f"dataclass `{spec.name}` 가 서로 다른 정의로 두 번 등록됐습니다 "
                    f"({existing.origin or '?'} / {spec.origin or '?'}). "
                    "같은 이름은 같은 필드 구성이어야 합니다 — 다른 개념이면 이름을 다르게 두세요."
                )
            return
        names = [f.name for f in spec.fields]
        if len(set(names)) != len(names):
            raise StrictlerError(
                f"dataclass `{spec.name}` 에 같은 이름의 필드가 두 번 있습니다. "
                "필드 이름은 dataclass 안에서 유일해야 합니다."
            )
        self._specs[spec.name] = spec
        self._invalidate()

    def _invalidate(self) -> None:
        self._normalized = False
        self._struct.clear()
        self._fields.clear()
        self._canon_fields.clear()
        self._merge_map = None
        self._merged_fields.clear()
        self._models.clear()

    # --- 정규화 ----------------------------------------------------------

    def normalize(self) -> None:
        """위상 정렬해 **바닥부터** 정규화한다. 중첩 dataclass 가 여기서 재귀적으로 풀린다.

        순환 참조(A 가 B 를, B 가 A 를 필드로)가 있으면 오류.
        """
        order = self._topo_order()
        for name in order:
            spec = self._specs[name]
            fields = {f.name: f.type for f in spec.fields}
            canon = frozenset((f.name, self._canon(f.type, spec)) for f in spec.fields)
            self._fields[name] = fields
            self._canon_fields[name] = canon
            self._struct[name] = "{" + ",".join(sorted(f"{n}:{t}" for n, t in canon)) + "}"
        self._normalized = True

    def _topo_order(self) -> list[str]:
        """의존하는 것이 먼저 오도록 정렬한다. 순환이면 오류."""
        order: list[str] = []
        state: dict[str, int] = {}  # 0=방문중, 1=완료
        stack: list[str] = []

        def visit(name: str) -> None:
            mark = state.get(name)
            if mark == 1:
                return
            if mark == 0:
                cycle = " → ".join([*stack[stack.index(name) :], name])
                raise StrictlerError(
                    f"dataclass 가 순환 참조합니다: {cycle}. "
                    "중첩 dataclass 는 바닥부터 정규화하므로 순환이 있으면 정의가 확정되지 않습니다."
                )
            state[name] = 0
            stack.append(name)
            for dep in self._deps(self._specs[name]):
                visit(dep)
            stack.pop()
            state[name] = 1
            order.append(name)

        for name in sorted(self._specs):
            visit(name)
        return order

    def _deps(self, spec: DataclassSpec) -> list[str]:
        found: list[str] = []
        for field in spec.fields:
            self._collect_refs(field.type, spec, found)
        return found

    def _collect_refs(self, t: TypeRef, spec: DataclassSpec, out: list[str]) -> None:
        if is_primitive(t):
            return
        if is_list(t):
            self._collect_refs(element_type(t), spec, out)
            return
        if t.name in self._specs and not t.args:
            out.append(t.name)
            return
        raise StrictlerError(self._unknown_type_message(t, spec))

    def _unknown_type_message(self, t: TypeRef, spec: DataclassSpec) -> str:
        where = f"`{spec.name}`" + (f" ({spec.origin})" if spec.origin else "")
        return (
            f"{where} 의 필드 타입 `{t}` 를 해석할 수 없습니다. "
            "쓸 수 있는 타입은 `int` `float` `str` `bool` `bytes` `list[T]` 와 "
            "같은 스크립트가 선언한 dataclass 뿐입니다."
        )

    def _canon(self, t: TypeRef, spec: DataclassSpec) -> str:
        """타입 하나를 **이름이 아니라 구조로** 표기한다.

        중첩 dataclass 는 이미 정규화가 끝나 있으므로(위상 정렬) 그 구조 서명을 쓴다.
        → `Outer(b: ButtonCount)` 와 `Outer2(b: MenuCount)` 는 같은 정의가 된다.
        """
        if is_primitive(t):
            return t.name
        if is_list(t):
            return f"list[{self._canon(element_type(t), spec)}]"
        if t.name in self._struct:
            return self._struct[t.name]
        raise StrictlerError(self._unknown_type_message(t, spec))

    def _require_normalized(self) -> None:
        if not self._normalized:
            raise StrictlerError(
                "TypeRegistry 를 정규화하지 않고 조회했습니다. "
                "`register()` 를 전부 부른 뒤 `normalize()` 를 한 번 부르고 조회하세요."
            )

    def _require_known(self, name: str) -> None:
        if name not in self._specs:
            raise StrictlerError(
                f"dataclass `{name}` 가 등록되어 있지 않습니다. "
                "스크립트가 선언한 dataclass 만 타입으로 쓸 수 있습니다."
            )

    # --- 조회 ------------------------------------------------------------

    def field_set(self, name: str) -> frozenset[tuple[str, str]]:
        """정규화된 `(필드명, 타입표기)` 쌍의 집합. 모든 비교의 기반이다."""
        self._require_normalized()
        self._require_known(name)
        return self._canon_fields[name]

    def same_definition(self, a: str, b: str) -> bool:
        """**그래프 검사용 — 엄격한 동일성.** 두 필드 집합이 완전히 같은가.

        파이프라인 배선 검사(`STR-TYPE-004`)가 이걸 쓴다.
        """
        return self.field_set(a) == self.field_set(b)

    def is_subset(self, a: str, b: str) -> bool:
        """`a` 의 필드 집합이 `b` 의 부분집합인가. 병합 대상 판정용."""
        return self.field_set(a) <= self.field_set(b)

    # --- 병합 (표현 층) ---------------------------------------------------

    def merge_components(self) -> dict[str, str]:
        """부분집합 격자의 **연결 성분 전체를 합집합**으로 병합한다.

        반환: `{원래 이름: 병합 클래스 이름}`. 런타임 표현 층에서만 쓰인다 —
        그래프 검사는 여전히 선언된 정의로 한다.
        """
        self._require_normalized()
        if self._merge_map is not None:
            return dict(self._merge_map)

        names = sorted(self._specs)
        parent = {n: n for n in names}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[max(rx, ry)] = min(rx, ry)

        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                fa, fb = self._canon_fields[a], self._canon_fields[b]
                if fa <= fb or fb <= fa:
                    union(a, b)

        components: dict[str, list[str]] = {}
        for n in names:
            components.setdefault(find(n), []).append(n)

        merge_map: dict[str, str] = {}
        merged_fields: dict[str, dict[str, TypeRef]] = {}
        for members in components.values():
            # 병합 클래스 이름 = 필드가 가장 많은 것, 동수면 사전순. 결정적이면 충분하다.
            label = sorted(members, key=lambda n: (-len(self._canon_fields[n]), n))[0]
            fields: dict[str, TypeRef] = {}
            seen_canon: dict[str, str] = {}
            for member in sorted(members):
                for fname, ftype in self._fields[member].items():
                    canon = dict(self._canon_fields[member])[fname]
                    if fname in seen_canon and seen_canon[fname] != canon:
                        raise StrictlerError(
                            f"병합 대상 {sorted(members)} 에서 필드 `{fname}` 의 타입이 갈립니다 "
                            f"({seen_canon[fname]} / {canon}). "
                            "부분집합으로 이어진 타입들은 같은 이름의 필드가 같은 타입이어야 "
                            "하나의 표현으로 합쳐집니다 — 다른 개념이면 필드 이름을 다르게 두세요."
                        )
                    seen_canon[fname] = canon
                    fields.setdefault(fname, ftype)
            for member in members:
                merge_map[member] = label
            merged_fields[label] = fields

        self._merge_map = merge_map
        self._merged_fields = merged_fields
        return dict(merge_map)

    # --- pydantic 경계 ----------------------------------------------------

    def build_model(self, name: str) -> type[BaseModel]:
        """이름에 해당하는(병합된) 타입의 pydantic 모델을 만든다.

        **pydantic 경계 검증이 실제 값을 만나는 자리**는 노드 단위테스트와
        엔진의 input/output 검증 둘뿐이다 (`schema.md` 14절).

        병합 클래스의 여분 필드는 비어 있을 수 있다 — 그건 **표현 층의 구현
        디테일(미설정 센티널)**이지 스크립트가 선언하는 타입에 `Optional` 이
        들어가는 게 아니다. 그 필드를 읽는 노드는 그 필드를 채우는 노드하고만
        연결된다는 것을 그래프 검사가 이미 보장했다.
        """
        self._require_normalized()
        self._require_known(name)
        cached = self._models.get(name)
        if cached is not None:
            return cached

        merge_map = self.merge_components()
        label = merge_map[name]
        own = self._fields[name]
        merged = self._merged_fields[label]

        definitions: dict[str, Any] = {}
        for fname in sorted(merged):
            annotation = self._py_type(merged[fname])
            if fname in own:
                definitions[fname] = (annotation, ...)
            else:
                definitions[fname] = (annotation | None, None)

        model = create_model(
            label,
            __config__=ConfigDict(extra="forbid", from_attributes=True, protected_namespaces=()),
            **definitions,
        )
        self._models[name] = model
        return model

    def _py_type(self, t: TypeRef) -> Any:
        if is_primitive(t):
            return _PY_PRIMITIVES[t.name]
        if is_list(t):
            return list[self._py_type(element_type(t))]  # type: ignore[misc]
        if t.name in self._specs:
            return self.build_model(t.name)
        raise StrictlerError(
            f"타입 `{t}` 를 값 검증 모델로 만들 수 없습니다. "
            f"쓸 수 있는 타입은 {sorted(PRIMITIVES)} 와 `list[T]`, 등록된 dataclass 뿐입니다."
        )

    def to_value(self, name: str, raw: Any) -> Any:
        """JSON 원값을 그 타입의 인스턴스로 만든다. 단위테스트 fixture 와 리포트가 쓴다."""
        model = self.build_model(name)
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        return model.model_validate(raw, from_attributes=True)
