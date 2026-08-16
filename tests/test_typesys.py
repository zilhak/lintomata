"""타입 시스템 테스트 (`schema.md` 7절).

`check_allowed` 와 등록기는 **진짜 `rules.finding()`** 으로 `Finding` 을 만든다.
여기에 대역을 끼우면 **슬롯 누락이 통째로 가려진다** — 실제로 그랬고, 그 탓에
`LNT-TYPE-001~003` 을 내는 유일한 자리가 셋 다 `LintomataError` 로 터지는 것을
Step 2 까지 아무도 못 봤다. 대역을 두지 않는 것이 이 파일의 계약이다.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from lintomata.errors import Finding, LintomataError
from lintomata.typesys.primitives import (
    FORBIDDEN,
    TypeRef,
    check_allowed,
    element_type,
    is_list,
    is_primitive,
    parse_type,
)
from lintomata.typesys.registry import DataclassSpec, FieldSpec, TypeKey, TypeRegistry


def dc(name: str, origin: str = "a.py", **fields: str) -> DataclassSpec:
    return DataclassSpec(
        name, tuple(FieldSpec(k, parse_type(v)) for k, v in fields.items()), origin=origin
    )


def k(name: str, origin: str = "a.py") -> TypeKey:
    return TypeKey(origin, name)


def normalized(*specs: DataclassSpec) -> TypeRegistry:
    reg = TypeRegistry()
    for spec in specs:
        reg.register(spec)
    reg.normalize()
    return reg


def ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


# --- primitives: 파싱 ------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    ["int", "float", "str", "bool", "bytes", "list[str]", "list[list[Button]]", "Button"],
)
def test_parse_type_roundtrips(expr: str) -> None:
    assert str(parse_type(expr)) == expr


def test_parse_type_ignores_whitespace() -> None:
    assert parse_type("  list[ str ] ") == TypeRef("list", (TypeRef("str"),))


def test_parse_type_reads_union_so_optional_gets_a_proper_rule() -> None:
    parsed = parse_type("str | None")
    assert parsed.args == (TypeRef("str"), TypeRef("None"))
    assert str(parsed) == "str | None"


@pytest.mark.parametrize("expr", ["", "   ", "list[str", "list[]", "list[str] junk", "[str]"])
def test_parse_type_rejects_garbage(expr: str) -> None:
    with pytest.raises(LintomataError):
        parse_type(expr)


def test_primitive_and_list_predicates() -> None:
    assert is_primitive(parse_type("bytes"))
    assert not is_primitive(parse_type("Button"))
    assert is_list(parse_type("list[Button]"))
    assert not is_list(parse_type("list"))  # 매개변수 없는 list 는 T 를 모른다
    assert element_type(parse_type("list[Button]")) == TypeRef("Button")


def test_element_type_of_non_list_is_a_tool_error() -> None:
    with pytest.raises(LintomataError):
        element_type(parse_type("int"))


# --- primitives: 허용 어휘 -------------------------------------------------


KNOWN = frozenset({"Button", "Page"})


@pytest.mark.parametrize("expr", ["int", "float", "str", "bool", "bytes",
                                  "Button", "list[Button]", "list[list[str]]"])
def test_check_allowed_accepts_vocabulary(expr: str) -> None:
    assert check_allowed(parse_type(expr), known=KNOWN, path="p") == []


@pytest.mark.parametrize("expr", ["dict", "dict[str, int]", "Dict[str, int]", "list[dict]"])
def test_dict_is_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["LNT-TYPE-001"]


@pytest.mark.parametrize(
    "expr", ["Optional[str]", "typing.Optional[str]", "None", "NoneType", "str | None"]
)
def test_optional_is_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["LNT-TYPE-002"]


@pytest.mark.parametrize("expr", ["Any", "set[str]", "Unknown", "list[Unknown]", "list",
                                  "Button[int]", "str | int"])
def test_unsupported_types_are_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["LNT-TYPE-003"]


def test_every_forbidden_name_is_actually_rejected() -> None:
    """`FORBIDDEN` 이 재수출용 장식이 아니라 **판정이 실제로 쓰는 표**여야 한다."""
    for name in FORBIDDEN:
        found = check_allowed(parse_type(name), known=frozenset({name}), path="p")
        assert ids(found) != [], f"{name} 이 `known` 에 있다는 이유로 통과했다"


def test_finding_carries_location() -> None:
    found = check_allowed(parse_type("dict"), known=KNOWN, path="nodes/a.json", node="count")
    assert (found[0].path, found[0].node) == ("nodes/a.json", "count")


@pytest.mark.parametrize("expr", ["dict[str, int]", "Optional[str]", "Button[int]", "str | int"])
def test_every_rejection_path_fills_its_slots(expr: str) -> None:
    """★ 세 규칙(`-001`/`-002`/`-003`) 전부 **실제 `rules.finding()`** 을 태운다.

    슬롯을 빠뜨리면 `LintomataError` 가 나면서 규칙 id 가 통째로 사라진다 —
    `known=frozenset()` 으로 dataclass 도 없는 최악 조건에서 확인한다.
    """
    found = check_allowed(parse_type(expr), known=frozenset(), path="/abs/n.py")
    assert len(found) == 1
    assert found[0].rule_id.startswith("LNT-TYPE-")
    leftover = re.compile(r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_]*\}")
    assert not leftover.search(found[0].message), found[0].message
    assert "/abs/n.py" in found[0].message


def test_unsupported_type_message_names_the_type() -> None:
    """`{type}` 슬롯이 실제 표기로 채워진다 — 안 그러면 무엇이 문제인지 못 읽는다."""
    found = check_allowed(parse_type("set[str]"), known=frozenset(), path="/abs/n.py")
    assert "set[str]" in found[0].message


# --- registry: (origin, name) 키 -------------------------------------------


def test_every_script_declares_its_own_args_without_colliding() -> None:
    """모든 노드 스크립트가 `Args` 라는 고정 이름을 선언한다 (`schema.md` 6절)."""
    reg = normalized(
        dc("Args", origin="a.py", input="int"),
        dc("Args", origin="b.py", input="str"),
        dc("Args", origin="c.py", input="int"),
    )
    assert reg.field_set(k("Args", "a.py")) == frozenset({("input", "int")})
    # 이름이 같아도 정의가 다르면 다른 타입이고, 구조가 같으면 같은 타입이다 — 전역 구조 판정
    assert not reg.same_definition(k("Args", "a.py"), k("Args", "b.py"))
    assert reg.same_definition(k("Args", "a.py"), k("Args", "c.py"))


def test_structural_identity_ignores_names_and_origins() -> None:
    reg = normalized(
        dc("Args", origin="a.py", count="int"),
        dc("ButtonCount", origin="b.py", count="int"),
    )
    assert reg.same_definition(k("Args", "a.py"), k("ButtonCount", "b.py"))


def test_same_name_same_origin_two_definitions_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", origin="a.py", x="int"))
    reg.register(dc("A", origin="a.py", x="int"))  # 같은 정의는 그냥 통과
    with pytest.raises(LintomataError):
        reg.register(dc("A", origin="a.py", x="str"))


def test_field_type_names_resolve_inside_the_origin_scope() -> None:
    """`nodeA.Args` 의 `Button` 은 **nodeA 의** `Button` 이다."""
    reg = normalized(
        dc("Button", origin="a.py", label="str"),
        dc("Args", origin="a.py", input="Button"),
        dc("Button", origin="b.py", label="str", pos="int"),
        dc("Args", origin="b.py", input="Button"),
    )
    # 각자 자기 스코프의 Button 을 봤으므로 두 Args 는 다른 정의다
    assert not reg.same_definition(k("Args", "a.py"), k("Args", "b.py"))
    assert reg.field_set(k("Args", "a.py")) != reg.field_set(k("Args", "b.py"))


def test_a_dataclass_from_another_script_is_not_visible() -> None:
    reg = TypeRegistry()
    reg.register(dc("Button", origin="a.py", label="str"))
    reg.register(dc("Args", origin="b.py", input="Button"))
    with pytest.raises(LintomataError, match="같은 스크립트") as excinfo:
        reg.normalize()
    # 2선 방어에도 규칙 id 는 있어야 한다 — 맨 예외로 나가면 리포트가 무엇이 걸렸는지 모른다
    found = excinfo.value.findings[0]
    assert found.rule_id == "LNT-TYPE-003"
    assert (found.path, found.node) == ("b.py", "Args")


def test_an_unknown_field_type_carries_str_type_003() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", origin="a.py", x="Nope"))
    with pytest.raises(LintomataError) as excinfo:
        reg.normalize()
    assert ids(excinfo.value.findings) == ["LNT-TYPE-003"]


def test_dataclass_spec_requires_an_origin() -> None:
    """기본값을 두면 등록 주체가 빠뜨렸을 때 전부 `""` 스코프로 몰려 `Args` 충돌이 되살아난다."""
    with pytest.raises(TypeError):
        DataclassSpec("Args", (FieldSpec("input", parse_type("int")),))  # type: ignore[call-arg]


def test_lookup_with_an_unregistered_key_is_a_tool_error() -> None:
    reg = normalized(dc("A", origin="a.py", x="int"))
    with pytest.raises(LintomataError):
        reg.field_set(k("A", "b.py"))


# --- registry: 집합 정규화 -------------------------------------------------


def test_field_order_does_not_matter() -> None:
    reg = normalized(dc("A", count="int", label="str"), dc("B", label="str", count="int"))
    assert reg.same_definition(k("A"), k("B"))


def test_same_field_name_different_type_is_a_different_definition() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="str"))
    assert not reg.same_definition(k("A"), k("B"))
    assert not reg.is_subset(k("A"), k("B"))


def test_field_set_is_a_set_of_name_type_pairs() -> None:
    reg = normalized(dc("A", count="int", label="str"))
    assert reg.field_set(k("A")) == frozenset({("count", "int"), ("label", "str")})


def test_nested_dataclasses_normalize_from_the_bottom_up() -> None:
    reg = normalized(
        dc("Inner", count="int"),
        dc("Outer", inner="Inner", title="str"),
        dc("Inner2", count="int"),
        dc("Outer2", inner="Inner2", title="str"),
    )
    # 중첩 타입이 이름이 아니라 구조로 정규화되므로 Outer 와 Outer2 는 같은 정의다
    assert reg.same_definition(k("Outer"), k("Outer2"))
    assert reg.same_definition(k("Inner"), k("Inner2"))


def test_nested_difference_propagates_upward() -> None:
    reg = normalized(
        dc("Inner", count="int"),
        dc("InnerX", count="str"),
        dc("Outer", inner="Inner"),
        dc("OuterX", inner="InnerX"),
    )
    assert not reg.same_definition(k("Outer"), k("OuterX"))


def test_list_element_type_participates_in_normalization() -> None:
    reg = normalized(
        dc("Button", label="str"),
        dc("Buttons", items="list[Button]"),
        dc("Widget", label="str"),
        dc("Widgets", items="list[Widget]"),
        dc("Counts", items="list[int]"),
    )
    assert reg.same_definition(k("Buttons"), k("Widgets"))
    assert not reg.same_definition(k("Buttons"), k("Counts"))


def test_mutual_cycle_is_str_type_007() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", b="B"))
    reg.register(dc("B", a="A"))
    with pytest.raises(LintomataError) as excinfo:
        reg.normalize()
    assert ids(excinfo.value.findings) == ["LNT-TYPE-007"]
    assert excinfo.value.findings[0].path == "a.py"


def test_self_recursive_type_is_str_type_007() -> None:
    """`N(kids: list[N])` — 바닥부터 정규화하는 이상 재귀 타입은 거절이 필연이다."""
    reg = TypeRegistry()
    reg.register(dc("N", kids="list[N]"))
    with pytest.raises(LintomataError) as excinfo:
        reg.normalize()
    found = excinfo.value.findings[0]
    assert found.rule_id == "LNT-TYPE-007"
    assert "N → N" in found.message  # `{cycle}` 슬롯이 실제 순환으로 채워진다


def test_unknown_field_type_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", x="Nope"))
    with pytest.raises(LintomataError):
        reg.normalize()


def test_query_before_normalize_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", x="int"))
    with pytest.raises(LintomataError, match="normalize"):
        reg.field_set(k("A"))


def test_register_after_normalize_invalidates() -> None:
    reg = normalized(dc("A", x="int"))
    reg.register(dc("B", x="int", y="str"))
    with pytest.raises(LintomataError, match="normalize"):
        reg.field_set(k("A"))
    reg.normalize()
    assert reg.is_subset(k("A"), k("B"))


# --- registry: 부분집합 병합 (표현 층) ------------------------------------


def test_subset_merges_into_one_component() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    assert reg.is_subset(k("A"), k("B"))
    merged = reg.merge_components()
    assert merged[k("A")] == merged[k("B")] == k("B")  # 필드가 많은 쪽 이름을 쓴다


def test_connected_component_is_unioned_even_when_the_top_is_not_unique() -> None:
    # A ⊂ B, A ⊂ C, B 와 C 는 서로 무관 — "가장 큰 것"이 유일하지 않다
    reg = normalized(
        dc("A", count="int"),
        dc("B", count="int", label="str"),
        dc("C", count="int", pos="int"),
    )
    assert reg.is_subset(k("A"), k("B")) and reg.is_subset(k("A"), k("C"))
    assert not reg.is_subset(k("B"), k("C")) and not reg.is_subset(k("C"), k("B"))

    merged = reg.merge_components()
    assert merged[k("A")] == merged[k("B")] == merged[k("C")]

    # 병합 클래스는 연결 성분 전체의 합집합을 갖는다
    model = reg.build_model(k("A"))
    assert set(model.model_fields) == {"count", "label", "pos"}


def test_merge_across_origins_is_still_one_component() -> None:
    reg = normalized(
        dc("Args", origin="a.py", count="int"),
        dc("Args", origin="b.py", count="int", label="str"),
    )
    merged = reg.merge_components()
    assert merged[k("Args", "a.py")] == merged[k("Args", "b.py")] == k("Args", "b.py")


def test_unrelated_types_stay_separate() -> None:
    reg = normalized(dc("A", count="int"), dc("B", label="str"))
    merged = reg.merge_components()
    assert merged[k("A")] != merged[k("B")]


def test_merging_does_not_loosen_the_graph_check() -> None:
    """병합은 표현 층에서만 일어난다 — 그래프 검사는 여전히 엄격한 동일성이다."""
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    assert reg.merge_components()[k("A")] == reg.merge_components()[k("B")]
    assert not reg.same_definition(k("A"), k("B"))  # LNT-TYPE-004 는 여전히 잡힌다


def test_merge_field_conflict_is_str_type_006() -> None:
    """`A ⊂ B`, `A ⊂ C` 로 한 성분인데 `x` 의 타입이 갈려 합집합이 성립하지 않는다."""
    reg = normalized(
        dc("A", y="int"),
        dc("B", x="int", y="int"),
        dc("C", x="str", y="int"),
    )
    with pytest.raises(LintomataError) as excinfo:
        reg.merge_components()
    found = excinfo.value.findings[0]
    assert found.rule_id == "LNT-TYPE-006"
    assert "필드 `x`" in found.message  # `{field}` 슬롯이 실제 필드명으로 채워진다
    assert "`A`(a.py)" in found.message  # names 슬롯에 성분 전체가 들어간다


def test_merge_field_conflict_also_blocks_model_building() -> None:
    reg = normalized(
        dc("A", y="int"),
        dc("B", x="int", y="int"),
        dc("C", x="str", y="int"),
    )
    with pytest.raises(LintomataError) as excinfo:
        reg.build_model(k("A"))
    assert excinfo.value.findings[0].rule_id == "LNT-TYPE-006"


def test_merge_field_conflict_reports_a_deterministic_location() -> None:
    """병합은 전역 연산이라 단일 위치가 없다 — **정렬한 첫 멤버**의 origin 을 쓴다."""
    reg = normalized(
        dc("A", origin="z.py", y="int"),
        dc("B", origin="a.py", x="int", y="int"),
        dc("C", origin="b.py", x="str", y="int"),
    )
    with pytest.raises(LintomataError) as excinfo:
        reg.merge_components()
    assert excinfo.value.findings[0].path == "a.py"  # 등록 순서(z.py 가 먼저)와 무관해야 한다


def test_same_field_name_same_type_across_a_component_is_fine() -> None:
    reg = normalized(
        dc("A", y="int"),
        dc("B", x="int", y="int"),
        dc("C", x="int", y="int", z="str"),
    )
    assert set(reg.build_model(k("A")).model_fields) == {"x", "y", "z"}


# --- registry: 병합된 필드의 이름 해석 (R2-1) ------------------------------
#
# 병합 클래스의 필드들은 **서로 다른 origin** 에서 온다. 필드 타입을 이름으로만 들고 다니다
# 조회한 키의 origin 에서 다시 찾으면 도구가 못 도는 세 가지가 생긴다.


def test_merged_field_type_resolves_in_the_contributing_origin() -> None:
    """(a) 가장 흔한 노드 조합 — Sense 의 `Args` 가 Reckon 의 `Args` 와 병합된다."""
    reg = normalized(
        dc("Args", origin="sense.py", input="str"),
        dc("P", origin="reckon.py", expected="int"),
        dc("Args", origin="reckon.py", input="str", params="P"),
    )
    model = reg.build_model(k("Args", "sense.py"))
    # `params` 는 reckon.py 가 기여한 필드다 — sense.py 에는 `P` 가 없다
    assert set(model.model_fields) == {"input", "params"}
    assert model.model_validate({"input": "x"}).params is None
    assert model.model_validate({"input": "x", "params": {"expected": 3}}).params.expected == 3


def test_structurally_equal_nested_types_with_different_names_still_build() -> None:
    """(b) `same_definition` 이 True 인데 `build_model` 만 터지면 7절을 못 쓴다."""
    reg = normalized(
        dc("Btn", origin="a.py", label="str"),
        dc("Args", origin="a.py", input="Btn"),
        dc("Widget", origin="b.py", label="str"),
        dc("Args", origin="b.py", input="Widget"),
    )
    assert reg.same_definition(k("Args", "a.py"), k("Args", "b.py"))
    for origin in ("a.py", "b.py"):
        value = reg.to_value(k("Args", origin), {"input": {"label": "확인"}})
        assert value.input.label == "확인"


def test_a_merged_extra_field_binds_to_the_right_same_named_type() -> None:
    """(c) ★ 조용한 오답 — 예외조차 안 난다.

    `a.py` 와 `b.py` 가 **둘 다** `Button` 을 선언하고 정의가 다르다. `a.Small` 의 병합
    클래스에 `b.Big` 의 `b: Button` 이 들어오는데, 이걸 `a.py` 스코프에서 다시 찾으면
    `a.Button` 이 잡히고 **아무 예외 없이 틀린 모델**이 나온다.
    """
    reg = normalized(
        dc("Button", origin="a.py", icon="str"),
        dc("Small", origin="a.py", x="int"),
        dc("Button", origin="b.py", label="str"),
        dc("Big", origin="b.py", x="int", b="Button"),
    )
    model = reg.build_model(k("Small", "a.py"))
    assert set(model.model_fields) == {"x", "b"}

    # `b` 는 b.py 가 기여했으므로 **b.py 의** Button(label:str) 이어야 한다
    assert model.model_validate({"x": 1, "b": {"label": "확인"}}).b.label == "확인"
    with pytest.raises(ValidationError):
        model.model_validate({"x": 1, "b": {"icon": "a.py 의 Button 이 잡히면 통과해버린다"}})


# --- registry: pydantic 경계 ----------------------------------------------


def test_build_model_requires_own_fields_and_leaves_merged_extras_unset() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    model_a = reg.build_model(k("A"))
    value = model_a.model_validate({"count": 3})
    assert value.count == 3
    assert value.label is None  # 여분 필드는 미설정 센티널이다

    with pytest.raises(ValidationError):
        reg.build_model(k("B")).model_validate({"count": 3})  # B 는 label 이 자기 필드다


def test_to_value_builds_nested_instances() -> None:
    reg = normalized(dc("Inner", count="int"), dc("Outer", inner="Inner", items="list[str]"))
    value = reg.to_value(k("Outer"), {"inner": {"count": 2}, "items": ["a", "b"]})
    assert value.inner.count == 2
    assert value.items == ["a", "b"]


def test_to_value_resolves_nested_types_in_the_right_origin() -> None:
    reg = normalized(
        dc("Inner", origin="a.py", count="int"),
        dc("Outer", origin="a.py", inner="Inner"),
        dc("Inner", origin="b.py", count="int", label="str"),
        dc("Outer", origin="b.py", inner="Inner"),
    )
    assert reg.to_value(k("Outer", "a.py"), {"inner": {"count": 2}}).inner.count == 2
    with pytest.raises(ValidationError):
        # b.py 의 Inner 는 label 이 자기 필드다 — a.py 의 Inner 를 잘못 집었으면 통과해버린다
        reg.to_value(k("Outer", "b.py"), {"inner": {"count": 2}})


def test_to_value_rejects_a_wrong_shape() -> None:
    reg = normalized(dc("A", count="int"))
    with pytest.raises(ValidationError):
        reg.to_value(k("A"), {"count": "셋"})


def test_to_value_reads_plain_objects() -> None:
    reg = normalized(dc("A", count="int"))

    class Raw:
        count = 7

    assert reg.to_value(k("A"), Raw()).count == 7
