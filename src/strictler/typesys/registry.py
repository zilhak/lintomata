"""dataclass 등록기 — 집합 정규화, 부분집합 병합, 그래프 검사용 동일성 판정.

`schema.md` 7절이 근거다. 이름이 `registry` 지만 **등록소(`strictler.store`)와 무관하다** —
이건 *타입 등록기*다.

**★ 키는 `(origin, name)` 이다.** 모든 노드 스크립트가 `Args` 라는 **고정 이름**을 선언하므로
(`schema.md` 6절) 이름만으로는 두 번째 노드부터 충돌한다. 그래서:

| | 규칙 |
|---|---|
| **키** | `(origin, name)` — `origin` 은 그 dataclass 를 선언한 스크립트 경로 |
| **필드 타입 참조 해석** | **같은 `origin` 스코프 안에서**. `Button` 은 그 스크립트의 `Button` 이다 |
| **타입 동일성 판정** | **전역, 그리고 구조로.** 이름이 달라도 구조가 같으면 같은 타입이다 |

즉 **이름은 스코프 안에서만 의미가 있고, 동일성은 구조로 전역 판정**한다.

⚠ **해석은 "선언한 쪽"의 스코프에서 한다 — "조회한 쪽"이 아니다.** 병합(표현 층)을 거치면
한 병합 클래스의 필드들이 서로 다른 origin 에서 온다. 필드 타입을 이름으로만 들고 다니다가
조회한 키의 origin 에서 다시 찾으면, 그 이름이 없으면 도구 오류로 터지고 **우연히 있으면
조용한 오답**이 된다. 그래서 병합 시점에 `_ResolvedType` 으로 `TypeKey` 를 못 박는다.

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
(합집합이 성립하지 않는 경우 — 같은 필드명의 타입이 갈릴 때 — 는 `STR-TYPE-006`)

⚠ 오배선 탐지력이 약해지는 것은 **감수한다**. `ButtonCount(count:int)` 와
`MenuCount(count:int)` 는 동일하다. 배선은 파이프라인 JSON 에 노드 id 로 명시적으로
쓰므로 타입 검사가 잡아주길 기대할 실수가 아니고, 값의 의미는 Reckon 이 잡는다.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, create_model

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.typesys.primitives import TypeRef, element_type, is_list, is_primitive

__all__ = ["TypeKey", "FieldSpec", "DataclassSpec", "TypeRegistry"]


_PY_PRIMITIVES: dict[str, type] = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "bytes": bytes,
}


class TypeKey(NamedTuple):
    """등록기의 키 — `(origin, name)`.

    `origin` 은 선언한 스크립트 경로. 노드마다 `Args` 가 있으므로 이름만으로는 키가 안 된다.
    `tuple` 이므로 `("a.py", "Args")` 를 그대로 넘겨도 된다.
    """

    origin: str
    name: str

    def __str__(self) -> str:
        return f"`{self.name}`({self.origin})" if self.origin else f"`{self.name}`"


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

    **`origin` 은 필수 인자다.** 기본값을 두면 등록 주체가 빠뜨렸을 때 모든 dataclass 가
    `""` 스코프로 몰려 `Args` 이름 충돌이 되살아난다 — 키를 `(origin, name)` 으로 둔 이유
    자체가 무너진다. 빠뜨리면 `TypeError` 로 즉시 드러나야 한다.
    """

    __slots__ = ("name", "fields", "origin")

    def __init__(self, name: str, fields: tuple[FieldSpec, ...], origin: str) -> None:
        self.name = name
        self.fields = tuple(fields)
        self.origin = origin

    def __repr__(self) -> str:
        return f"DataclassSpec({self.name!r}, {self.fields!r}, origin={self.origin!r})"

    @property
    def key(self) -> TypeKey:
        """등록기 키 `(origin, name)`."""
        return TypeKey(self.origin, self.name)

    def raw_set(self) -> frozenset[tuple[str, str]]:
        """정규화 전의 `(필드명, 선언 표기)` 집합. 중복 등록 판정에만 쓴다."""
        return frozenset((f.name, str(f.type)) for f in self.fields)


class _ResolvedType(NamedTuple):
    """**이름 해석이 끝난** 타입 하나.

    맨 `TypeRef` 는 `Button` 이라는 *이름*만 들고 있어서, 그걸 어느 스크립트의 `Button`
    으로 읽을지는 **그 필드를 선언한 dataclass 의 `origin`** 에 달려 있다. 병합(표현 층)을
    거치면 필드가 다른 origin 에서 온 것과 섞이므로, 이름만 들고 다니면 **조회한 키의
    origin 에서 엉뚱한 타입을 다시 찾게 된다** — 예외가 나면 그나마 다행이고, 우연히
    같은 이름이 있으면 **조용한 오답**이 된다.

    그래서 병합 시점에 이름을 `TypeKey` 로 못 박아 들고 다닌다. 그 뒤로는 어떤 origin 도
    다시 보지 않는다.

    | 필드 | 무엇 |
    |---|---|
    | `ref` | 원래 표기 (`list[Button]`) — 에러 메시지용 |
    | `key` | dataclass 참조일 때 **해석 완료된** `(origin, name)` |
    | `element` | `list[T]` 의 `T` (역시 해석 완료) |
    """

    ref: TypeRef
    key: TypeKey | None = None
    element: _ResolvedType | None = None


class TypeRegistry:
    """모든 노드의 dataclass 선언을 모아 집합 검사를 거는 등록기.

    사용 순서: `register()` 를 전부 부른 뒤 `normalize()` 한 번 → 이후 조회.
    조회는 전부 `TypeKey`(= `(origin, name)`)로 한다.
    """

    def __init__(self) -> None:
        self._specs: dict[TypeKey, DataclassSpec] = {}
        self._normalized = False
        # 정규화 산출물
        self._struct: dict[TypeKey, str] = {}
        """dataclass 키 → 구조 서명. 이름이 아니라 구조로 비교하기 위한 것."""
        self._fields: dict[TypeKey, dict[str, TypeRef]] = {}
        self._canon_fields: dict[TypeKey, frozenset[tuple[str, str]]] = {}
        # 병합 산출물 (지연 계산)
        self._merge_map: dict[TypeKey, TypeKey] | None = None
        self._merged_fields: dict[TypeKey, dict[str, _ResolvedType]] = {}
        self._models: dict[TypeKey, type[BaseModel]] = {}

    # --- 등록 ------------------------------------------------------------

    def register(self, spec: DataclassSpec) -> None:
        """dataclass 선언 하나를 등록한다.

        **같은 `origin` 안에서** 같은 이름이 다른 정의로 오면 오류다. 다른 스크립트가
        같은 이름(`Args`)을 쓰는 것은 충돌이 아니다 — 키가 `(origin, name)` 이기 때문이다.
        """
        key = spec.key
        existing = self._specs.get(key)
        if existing is not None:
            if existing.raw_set() != spec.raw_set():
                raise StrictlerError(
                    f"dataclass `{spec.name}` 가 같은 스크립트({spec.origin or '?'}) 안에서 "
                    "서로 다른 정의로 두 번 선언됐습니다. "
                    "한 스크립트 안에서 같은 이름은 같은 필드 구성이어야 합니다 — "
                    "다른 개념이면 이름을 다르게 두세요."
                )
            return
        names = [f.name for f in spec.fields]
        if len(set(names)) != len(names):
            raise StrictlerError(
                f"dataclass `{spec.name}` 에 같은 이름의 필드가 두 번 있습니다. "
                "필드 이름은 dataclass 안에서 유일해야 합니다."
            )
        self._specs[key] = spec
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

        순환 참조(A 가 B 를, B 가 A 를 필드로)가 있으면 `STR-TYPE-007`.
        """
        order = self._topo_order()
        for key in order:
            spec = self._specs[key]
            fields = {f.name: f.type for f in spec.fields}
            canon = frozenset((f.name, self._canon(f.type, spec)) for f in spec.fields)
            self._fields[key] = fields
            self._canon_fields[key] = canon
            self._struct[key] = "{" + ",".join(sorted(f"{n}:{t}" for n, t in canon)) + "}"
        self._normalized = True

    def _topo_order(self) -> list[TypeKey]:
        """의존하는 것이 먼저 오도록 정렬한다. 순환이면 `STR-TYPE-007`."""
        order: list[TypeKey] = []
        state: dict[TypeKey, int] = {}  # 0=방문중, 1=완료
        stack: list[TypeKey] = []

        def visit(key: TypeKey) -> None:
            mark = state.get(key)
            if mark == 1:
                return
            if mark == 0:
                loop = [*stack[stack.index(key) :], key]
                raise _rule_error(
                    "STR-TYPE-007",
                    path=key.origin,
                    fields={"cycle": " → ".join(k.name for k in loop)},
                )
            state[key] = 0
            stack.append(key)
            for dep in self._deps(self._specs[key]):
                visit(dep)
            stack.pop()
            state[key] = 1
            order.append(key)

        for key in sorted(self._specs):
            visit(key)
        return order

    def _deps(self, spec: DataclassSpec) -> list[TypeKey]:
        found: list[TypeKey] = []
        for field in spec.fields:
            self._collect_refs(self._resolve(field.type, spec.key), found)
        return found

    def _collect_refs(self, resolved: _ResolvedType, out: list[TypeKey]) -> None:
        if resolved.key is not None:
            out.append(resolved.key)
        elif resolved.element is not None:
            self._collect_refs(resolved.element, out)

    def _resolve(self, t: TypeRef, owner: TypeKey) -> _ResolvedType:
        """타입 표기 하나의 **이름을 `owner` 스코프에서 해석해** 못 박는다.

        `owner` 는 그 필드를 선언한 dataclass 의 키다 — 이름 해석은 언제나
        **선언한 스크립트의 origin** 안에서 한다 (조회한 쪽의 origin 이 아니다).
        """
        if is_primitive(t):
            return _ResolvedType(t)
        if is_list(t):
            return _ResolvedType(t, element=self._resolve(element_type(t), owner))
        ref = TypeKey(owner.origin, t.name)
        if ref in self._specs and not t.args:
            return _ResolvedType(t, key=ref)
        raise self._unknown_type_error(t, owner)

    def _unknown_type_error(self, t: TypeRef, owner: TypeKey) -> StrictlerError:
        """미지 타입 — `STR-TYPE-003`(unsupported-type).

        `checks/script.py` 가 등록 전에 1차로 잡지만, **2선 방어에도 규칙 id 는 있어야 한다.**
        id 없는 맨 예외로 나가면 리포트에서 무엇이 걸렸는지 기계적으로 알 수 없다.
        """
        where = f"`{owner.name}`" + (f" ({owner.origin})" if owner.origin else "")
        return _rule_error(
            "STR-TYPE-003",
            path=owner.origin,
            node=owner.name,
            fields={},
            message=(
                f"{where} 의 필드 타입 `{t}` 를 해석할 수 없습니다. "
                "쓸 수 있는 타입은 `int` `float` `str` `bool` `bytes` `list[T]` 와 "
                "**같은 스크립트가** 선언한 dataclass 뿐입니다 — 다른 스크립트의 dataclass 는 "
                "이름으로 참조할 수 없습니다."
            ),
        )

    def _canon(self, t: TypeRef, spec: DataclassSpec) -> str:
        """타입 하나를 **이름이 아니라 구조로** 표기한다.

        중첩 dataclass 는 이미 정규화가 끝나 있으므로(위상 정렬) 그 구조 서명을 쓴다.
        → `Outer(b: ButtonCount)` 와 `Outer2(b: MenuCount)` 는 같은 정의가 된다.
        서명에 이름도 origin 도 들어가지 않으므로 **동일성 판정은 전역**이다.
        """
        if is_primitive(t):
            return t.name
        if is_list(t):
            return f"list[{self._canon(element_type(t), spec)}]"
        ref = TypeKey(spec.origin, t.name)
        if ref in self._struct:
            return self._struct[ref]
        raise self._unknown_type_error(t, spec.key)

    def _require_normalized(self) -> None:
        if not self._normalized:
            raise StrictlerError(
                "TypeRegistry 를 정규화하지 않고 조회했습니다. "
                "`register()` 를 전부 부른 뒤 `normalize()` 를 한 번 부르고 조회하세요."
            )

    def _require_known(self, key: TypeKey) -> None:
        if key not in self._specs:
            raise StrictlerError(
                f"dataclass {TypeKey(*key)} 가 등록되어 있지 않습니다. "
                "스크립트가 선언한 dataclass 만 타입으로 쓸 수 있고, "
                "조회 키는 `(origin, name)` 입니다."
            )

    # --- 조회 ------------------------------------------------------------

    def field_set(self, key: TypeKey) -> frozenset[tuple[str, str]]:
        """정규화된 `(필드명, 타입표기)` 쌍의 집합. 모든 비교의 기반이다.

        타입표기는 **구조 서명**이므로 origin 이 달라도 구조가 같으면 같은 집합이 나온다.
        """
        self._require_normalized()
        self._require_known(key)
        return self._canon_fields[key]

    def same_definition(self, a: TypeKey, b: TypeKey) -> bool:
        """**그래프 검사용 — 엄격한 동일성.** 두 필드 집합이 완전히 같은가.

        파이프라인 배선 검사(`STR-TYPE-004`)가 이걸 쓴다. 이름·origin 이 달라도
        구조가 같으면 참이다 — **구조적 동일성이지 명목적 동일성이 아니다.**
        """
        return self.field_set(a) == self.field_set(b)

    def is_subset(self, a: TypeKey, b: TypeKey) -> bool:
        """`a` 의 필드 집합이 `b` 의 부분집합인가. 병합 대상 판정용."""
        return self.field_set(a) <= self.field_set(b)

    # --- 병합 (표현 층) ---------------------------------------------------

    def merge_components(self) -> dict[TypeKey, TypeKey]:
        """부분집합 격자의 **연결 성분 전체를 합집합**으로 병합한다.

        반환: `{원래 키: 병합 클래스 키}`. 런타임 표현 층에서만 쓰인다 —
        그래프 검사는 여전히 선언된 정의로 한다.
        """
        self._require_normalized()
        if self._merge_map is not None:
            return dict(self._merge_map)

        keys = sorted(self._specs)
        parent = {k: k for k in keys}

        def find(x: TypeKey) -> TypeKey:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: TypeKey, y: TypeKey) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[max(rx, ry)] = min(rx, ry)

        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                fa, fb = self._canon_fields[a], self._canon_fields[b]
                if fa <= fb or fb <= fa:
                    union(a, b)

        components: dict[TypeKey, list[TypeKey]] = {}
        for k in keys:
            components.setdefault(find(k), []).append(k)

        merge_map: dict[TypeKey, TypeKey] = {}
        merged_fields: dict[TypeKey, dict[str, TypeRef]] = {}
        for members in components.values():
            # 병합 클래스 = 필드가 가장 많은 것, 동수면 키 사전순. 결정적이면 충분하다.
            label = sorted(members, key=lambda k: (-len(self._canon_fields[k]), k))[0]
            merged_fields[label] = self._union_fields(members)
            for member in members:
                merge_map[member] = label

        self._merge_map = merge_map
        self._merged_fields = merged_fields
        return dict(merge_map)

    def _union_fields(self, members: list[TypeKey]) -> dict[str, _ResolvedType]:
        """연결 성분 하나의 필드 합집합. 같은 필드명의 타입이 갈리면 `STR-TYPE-006`.

        **필드마다 "해석 완료된" 타입을 들고 나간다.** 맨 `TypeRef` 만 저장하면 그 필드를
        기여한 멤버의 `origin` 이 소실되고, 나중에 `build_model()` 이 **조회한 키의 origin**
        에서 이름을 다시 찾아 엉뚱한 타입에 바인딩한다 (조용한 오답).
        """
        ordered = sorted(members)
        fields: dict[str, _ResolvedType] = {}
        seen: dict[str, tuple[TypeKey, str]] = {}
        for member in ordered:
            canon_of = dict(self._canon_fields[member])
            for fname, ftype in self._fields[member].items():
                canon = canon_of[fname]
                previous = seen.get(fname)
                if previous is not None and previous[1] != canon:
                    owner, owner_canon = previous
                    raise _rule_error(
                        "STR-TYPE-006",
                        # 병합은 등록기 전역 연산이라 단일 위치가 없다. 리포트에 위치가
                        # 아예 없으면 원인을 못 찾으므로 **정렬한 첫 멤버**의 origin 을 쓴다
                        # (정렬해야 결정적이다).
                        path=ordered[0].origin,
                        fields={
                            "names": ", ".join(str(m) for m in ordered),
                            "field": fname,
                            "types": f"{owner} 는 {owner_canon} / {member} 는 {canon}",
                        },
                    )
                seen[fname] = (member, canon)
                if fname not in fields:
                    # 이름 해석은 **기여한 멤버의 스코프**에서 지금 끝낸다.
                    fields[fname] = self._resolve(ftype, member)
        return fields

    # --- pydantic 경계 ----------------------------------------------------

    def build_model(self, key: TypeKey) -> type[BaseModel]:
        """키에 해당하는(병합된) 타입의 pydantic 모델을 만든다.

        **pydantic 경계 검증이 실제 값을 만나는 자리**는 노드 단위테스트와
        엔진의 input/output 검증 둘뿐이다 (`schema.md` 14절).

        병합 클래스의 여분 필드는 비어 있을 수 있다 — 그건 **표현 층의 구현
        디테일(미설정 센티널)**이지 스크립트가 선언하는 타입에 `Optional` 이
        들어가는 게 아니다. 그 필드를 읽는 노드는 그 필드를 채우는 노드하고만
        연결된다는 것을 그래프 검사가 이미 보장했다.
        """
        self._require_normalized()
        self._require_known(key)
        key = TypeKey(*key)
        cached = self._models.get(key)
        if cached is not None:
            return cached

        label = self.merge_components()[key]
        own = self._fields[key]
        merged = self._merged_fields[label]

        definitions: dict[str, Any] = {}
        for fname in sorted(merged):
            # ★ `key.origin` 으로 다시 해석하지 않는다 — 병합 시점에 이미 해석이 끝났다.
            annotation = self._py_type(merged[fname])
            if fname in own:
                definitions[fname] = (annotation, ...)
            else:
                definitions[fname] = (annotation | None, None)

        model = create_model(
            label.name,
            __config__=ConfigDict(extra="forbid", from_attributes=True, protected_namespaces=()),
            **definitions,
        )
        self._models[key] = model
        return model

    def _py_type(self, resolved: _ResolvedType) -> Any:
        """**해석 완료된** 타입을 pydantic 어노테이션으로 바꾼다.

        여기서 이름을 다시 찾지 않는다 — `origin` 을 받지 않는 것이 그 보장이다.
        """
        if resolved.key is not None:
            return self.build_model(resolved.key)
        if resolved.element is not None:
            return list[self._py_type(resolved.element)]  # type: ignore[misc]
        return _PY_PRIMITIVES[resolved.ref.name]

    def to_value(self, key: TypeKey, raw: Any) -> Any:
        """JSON 원값을 그 타입의 인스턴스로 만든다. 단위테스트 fixture 와 리포트가 쓴다."""
        model = self.build_model(key)
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        return model.model_validate(raw, from_attributes=True)


def _rule_error(
    rule_id: str,
    *,
    path: str = "",
    node: str = "",
    fields: dict[str, object],
    message: str = "",
) -> StrictlerError:
    """규칙 id 가 붙은 `StrictlerError` 를 만든다.

    타입 등록기가 내는 것은 전부 **오류**다 — 위반이 아니다. 하지만 규칙 id 없이
    맨 예외로 나가면 리포트에서 무엇이 걸렸는지 기계적으로 알 수 없으므로,
    `Finding` 을 함께 실어 보낸다 (`errors.StrictlerError.findings`).

    `message` 를 주면 예외 문구로 그걸 쓴다 — 슬롯 없는 규칙(`STR-TYPE-003`)은
    규칙 문구만으로는 **어느 dataclass 의 어느 필드**인지 알 수 없기 때문이다.
    `Finding` 쪽 문구는 규칙 테이블 그대로 둔다.
    """
    found: Finding = rules.finding(rule_id, path=path, node=node, fields=fields)
    return StrictlerError(message or found.message or rule_id, [found])
