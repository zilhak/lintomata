"""타입 시스템 테스트 (`schema.md` 7절).

`check_allowed` 는 `rules.finding()` 으로 `Finding` 을 만든다. 그 구현은 Step 1-b 의
몫이므로, 여기서는 규칙 id 만 확인할 수 있도록 최소 대역을 끼워 넣는다 — 검사 대상은
`typesys` 지 `rules` 가 아니다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.typesys.primitives import (
    TypeRef,
    check_allowed,
    element_type,
    is_list,
    is_primitive,
    parse_type,
)
from strictler.typesys.registry import DataclassSpec, FieldSpec, TypeRegistry


@pytest.fixture(autouse=True)
def _stub_rule_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_finding(rule_id: str, *, status: str = "error", path: str = "", node: str = "",
                     cause: object = None, **fields: object) -> Finding:
        return Finding(status=status, path=path, node=node, rule_id=rule_id,
                       message=str(fields.get("type", "")))

    monkeypatch.setattr(rules, "finding", fake_finding)


def dc(name: str, origin: str = "", **fields: str) -> DataclassSpec:
    return DataclassSpec(
        name, tuple(FieldSpec(k, parse_type(v)) for k, v in fields.items()), origin=origin
    )


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
    with pytest.raises(StrictlerError):
        parse_type(expr)


def test_primitive_and_list_predicates() -> None:
    assert is_primitive(parse_type("bytes"))
    assert not is_primitive(parse_type("Button"))
    assert is_list(parse_type("list[Button]"))
    assert not is_list(parse_type("list"))  # 매개변수 없는 list 는 T 를 모른다
    assert element_type(parse_type("list[Button]")) == TypeRef("Button")


def test_element_type_of_non_list_is_a_tool_error() -> None:
    with pytest.raises(StrictlerError):
        element_type(parse_type("int"))


# --- primitives: 허용 어휘 -------------------------------------------------


KNOWN = frozenset({"Button", "Page"})


@pytest.mark.parametrize("expr", ["int", "float", "str", "bool", "bytes",
                                  "Button", "list[Button]", "list[list[str]]"])
def test_check_allowed_accepts_vocabulary(expr: str) -> None:
    assert check_allowed(parse_type(expr), known=KNOWN, path="p") == []


@pytest.mark.parametrize("expr", ["dict", "dict[str, int]", "Dict[str, int]", "list[dict]"])
def test_dict_is_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["STR-TYPE-001"]


@pytest.mark.parametrize(
    "expr", ["Optional[str]", "typing.Optional[str]", "None", "NoneType", "str | None"]
)
def test_optional_is_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["STR-TYPE-002"]


@pytest.mark.parametrize("expr", ["Any", "set[str]", "Unknown", "list[Unknown]", "list",
                                  "Button[int]", "str | int"])
def test_unsupported_types_are_rejected(expr: str) -> None:
    assert ids(check_allowed(parse_type(expr), known=KNOWN, path="p")) == ["STR-TYPE-003"]


def test_finding_carries_location() -> None:
    found = check_allowed(parse_type("dict"), known=KNOWN, path="nodes/a.json", node="count")
    assert (found[0].path, found[0].node) == ("nodes/a.json", "count")


# --- registry: 집합 정규화 -------------------------------------------------


def test_field_order_does_not_matter() -> None:
    reg = normalized(dc("A", count="int", label="str"), dc("B", label="str", count="int"))
    assert reg.same_definition("A", "B")


def test_same_field_name_different_type_is_a_different_definition() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="str"))
    assert not reg.same_definition("A", "B")
    assert not reg.is_subset("A", "B")


def test_field_set_is_a_set_of_name_type_pairs() -> None:
    reg = normalized(dc("A", count="int", label="str"))
    assert reg.field_set("A") == frozenset({("count", "int"), ("label", "str")})


def test_nested_dataclasses_normalize_from_the_bottom_up() -> None:
    reg = normalized(
        dc("Inner", count="int"),
        dc("Outer", inner="Inner", title="str"),
        dc("Inner2", count="int"),
        dc("Outer2", inner="Inner2", title="str"),
    )
    # 중첩 타입이 이름이 아니라 구조로 정규화되므로 Outer 와 Outer2 는 같은 정의다
    assert reg.same_definition("Outer", "Outer2")
    assert reg.same_definition("Inner", "Inner2")


def test_nested_difference_propagates_upward() -> None:
    reg = normalized(
        dc("Inner", count="int"),
        dc("InnerX", count="str"),
        dc("Outer", inner="Inner"),
        dc("OuterX", inner="InnerX"),
    )
    assert not reg.same_definition("Outer", "OuterX")


def test_list_element_type_participates_in_normalization() -> None:
    reg = normalized(
        dc("Button", label="str"),
        dc("Buttons", items="list[Button]"),
        dc("Widget", label="str"),
        dc("Widgets", items="list[Widget]"),
        dc("Counts", items="list[int]"),
    )
    assert reg.same_definition("Buttons", "Widgets")
    assert not reg.same_definition("Buttons", "Counts")


def test_cycle_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", b="B"))
    reg.register(dc("B", a="A"))
    with pytest.raises(StrictlerError, match="순환"):
        reg.normalize()


def test_unknown_field_type_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", x="Nope"))
    with pytest.raises(StrictlerError):
        reg.normalize()


def test_same_name_two_definitions_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", x="int", origin="a.py"))
    reg.register(dc("A", x="int", origin="b.py"))  # 같은 정의는 그냥 통과
    with pytest.raises(StrictlerError):
        reg.register(dc("A", x="str", origin="c.py"))


def test_query_before_normalize_is_a_tool_error() -> None:
    reg = TypeRegistry()
    reg.register(dc("A", x="int"))
    with pytest.raises(StrictlerError, match="normalize"):
        reg.field_set("A")


def test_register_after_normalize_invalidates() -> None:
    reg = normalized(dc("A", x="int"))
    reg.register(dc("B", x="int", y="str"))
    with pytest.raises(StrictlerError, match="normalize"):
        reg.field_set("A")
    reg.normalize()
    assert reg.is_subset("A", "B")


# --- registry: 부분집합 병합 (표현 층) ------------------------------------


def test_subset_merges_into_one_component() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    assert reg.is_subset("A", "B")
    merged = reg.merge_components()
    assert merged["A"] == merged["B"] == "B"  # 필드가 많은 쪽 이름을 쓴다


def test_connected_component_is_unioned_even_when_the_top_is_not_unique() -> None:
    # A ⊂ B, A ⊂ C, B 와 C 는 서로 무관 — "가장 큰 것"이 유일하지 않다
    reg = normalized(
        dc("A", count="int"),
        dc("B", count="int", label="str"),
        dc("C", count="int", pos="int"),
    )
    assert reg.is_subset("A", "B") and reg.is_subset("A", "C")
    assert not reg.is_subset("B", "C") and not reg.is_subset("C", "B")

    merged = reg.merge_components()
    assert merged["A"] == merged["B"] == merged["C"]

    # 병합 클래스는 연결 성분 전체의 합집합을 갖는다
    model = reg.build_model("A")
    assert set(model.model_fields) == {"count", "label", "pos"}


def test_unrelated_types_stay_separate() -> None:
    reg = normalized(dc("A", count="int"), dc("B", label="str"))
    merged = reg.merge_components()
    assert merged["A"] != merged["B"]


def test_merging_does_not_loosen_the_graph_check() -> None:
    """병합은 표현 층에서만 일어난다 — 그래프 검사는 여전히 엄격한 동일성이다."""
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    assert reg.merge_components()["A"] == reg.merge_components()["B"]
    assert not reg.same_definition("A", "B")  # STR-TYPE-004 는 여전히 잡힌다


# --- registry: pydantic 경계 ----------------------------------------------


def test_build_model_requires_own_fields_and_leaves_merged_extras_unset() -> None:
    reg = normalized(dc("A", count="int"), dc("B", count="int", label="str"))
    model_a = reg.build_model("A")
    value = model_a.model_validate({"count": 3})
    assert value.count == 3
    assert value.label is None  # 여분 필드는 미설정 센티널이다

    with pytest.raises(ValidationError):
        reg.build_model("B").model_validate({"count": 3})  # B 는 label 이 자기 필드다


def test_to_value_builds_nested_instances() -> None:
    reg = normalized(dc("Inner", count="int"), dc("Outer", inner="Inner", items="list[str]"))
    value = reg.to_value("Outer", {"inner": {"count": 2}, "items": ["a", "b"]})
    assert value.inner.count == 2
    assert value.items == ["a", "b"]


def test_to_value_rejects_a_wrong_shape() -> None:
    reg = normalized(dc("A", count="int"))
    with pytest.raises(ValidationError):
        reg.to_value("A", {"count": "셋"})


def test_to_value_reads_plain_objects() -> None:
    reg = normalized(dc("A", count="int"))

    class Raw:
        count = 7

    assert reg.to_value("A", Raw()).count == 7
