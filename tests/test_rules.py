"""`rules.py` — 규칙 테이블 54개와 `Finding` 생성 헬퍼."""

from __future__ import annotations

import re

import pytest

from strictler.errors import NotRunCause, StrictlerError
from strictler.rules import RULES, finding, get_rule, render, rules_for

ID_RE = re.compile(r"^STR-[A-Z]+-\d{3}$")

# `rules.md` 3절 "규칙 수 요약" 그대로.
EXPECTED_COUNTS = {
    "PATH": 4,
    "REF": 5,
    "GRAPH": 2,
    "TYPE": 5,
    "CONTRACT": 6,
    "STATE": 7,
    "BAN": 4,
    "TOOL": 2,
    "CONFIG": 3,
    "CMP": 4,
    "TEST": 7,
    "REG": 5,
}


def test_rule_count_is_54() -> None:
    assert len(RULES) == 54
    assert sum(EXPECTED_COUNTS.values()) == 54


def test_category_counts_match_rules_md() -> None:
    counts: dict[str, int] = {}
    for rule_id in RULES:
        category = rule_id.split("-")[1]
        counts[category] = counts.get(category, 0) + 1
    assert counts == EXPECTED_COUNTS


def test_ids_are_well_formed_and_unique() -> None:
    for rule_id, rule in RULES.items():
        assert ID_RE.match(rule_id), rule_id
        assert rule.id == rule_id
    # dict 키라 중복은 구조적으로 불가능하지만, 테이블 자체에 중복이 없는지도 본다.
    ids = [rule.id for rule in RULES.values()]
    assert len(ids) == len(set(ids))


def test_numbers_are_contiguous_per_category() -> None:
    """카테고리별 독립 번호 공간 — 초기 테이블은 001부터 빈 번호 없이 이어진다."""
    by_category: dict[str, list[int]] = {}
    for rule_id in RULES:
        _, category, num = rule_id.split("-")
        by_category.setdefault(category, []).append(int(num))
    for category, nums in by_category.items():
        assert sorted(nums) == list(range(1, EXPECTED_COUNTS[category] + 1)), category


def test_every_rule_has_name_since_status_when() -> None:
    names = set()
    for rule in RULES.values():
        assert rule.name
        assert rule.name not in names, rule.name
        names.add(rule.name)
        assert rule.since == "0.1.0"
        assert rule.status == "active"
        assert rule.when
        assert rule.message
        assert rule.guide


def test_rule_is_frozen() -> None:
    rule = get_rule("STR-PATH-001")
    with pytest.raises(Exception):
        rule.id = "STR-PATH-999"  # type: ignore[misc]


def test_get_rule_unknown_id_raises() -> None:
    with pytest.raises(StrictlerError) as exc:
        get_rule("STR-PATH-999")
    assert "STR-PATH-999" in str(exc.value)


def test_get_rule_typo_does_not_pass_silently() -> None:
    with pytest.raises(StrictlerError):
        get_rule("STR-CONTRACT-01")


def test_rules_for_when() -> None:
    node_ids = {rule.id for rule in rules_for("node-register")}
    assert "STR-CONTRACT-001" in node_ids
    assert "STR-PATH-001" in node_ids  # N P R
    assert "STR-GRAPH-001" not in node_ids

    list_ids = {rule.id for rule in rules_for("list")}
    assert list_ids == {"STR-REG-004", "STR-REG-005"}

    test_ids = {rule.id for rule in rules_for("test")}
    assert len(test_ids) == EXPECTED_COUNTS["TEST"]


def test_rules_for_covers_every_rule() -> None:
    seen: set[str] = set()
    for when in ("node-register", "pipeline-register", "run", "test", "list"):
        seen |= {rule.id for rule in rules_for(when)}
    assert seen == set(RULES)


def test_render_fills_message_and_appends_guide() -> None:
    text = render("STR-CONTRACT-001", file="/abs/scripts/detect.py")
    rule = get_rule("STR-CONTRACT-001")
    assert "/abs/scripts/detect.py" in text
    assert text.endswith(rule.guide)
    assert "{file}" not in text


def test_render_fills_slots_inside_guide() -> None:
    """`rules.md` 의 guide 문구 자체가 슬롯을 갖는다 (`{cycle}` 등)."""
    text = render("STR-GRAPH-001", cycle="a -> b -> a")
    assert "a -> b -> a" in text
    assert "{cycle}" not in text


def test_render_keeps_reference_syntax_untouched() -> None:
    """guide 에 그대로 들어 있는 `${env.X}` 는 자리표시자가 아니다."""
    text = render("STR-PATH-001", path="./relative")
    assert "${env.X}" in text


def test_render_accepts_keyword_named_slot() -> None:
    """`STR-TYPE-004` 의 guide 슬롯 `{in}` 은 파이썬 예약어라 dict 로 넘긴다."""
    text = render("STR-TYPE-004", **{"out": "Percept", "in": "Sensum"})
    assert "Percept" in text
    assert "Sensum" in text


def test_render_missing_slot_raises() -> None:
    with pytest.raises(StrictlerError) as exc:
        render("STR-GRAPH-001")
    assert "cycle" in str(exc.value)


def test_render_unknown_rule_raises() -> None:
    with pytest.raises(StrictlerError):
        render("STR-NOPE-001", file="x")


def test_finding_defaults_to_error() -> None:
    f = finding("STR-CONTRACT-001", file="/abs/x.py")
    assert f.status == "error"
    assert f.rule_id == "STR-CONTRACT-001"
    assert "/abs/x.py" in f.message
    assert f.cause is None


def test_finding_carries_path_node_cause() -> None:
    cause = NotRunCause(node="captureHtml", reason="state_unreachable")
    f = finding(
        "STR-STATE-007",
        status="not_run",
        path="login.json > plan[0] > login-flow",
        node="checkToken",
        cause=cause,
        name="checkToken",
    )
    assert f.status == "not_run"
    assert f.path == "login.json > plan[0] > login-flow"
    assert f.node == "checkToken"
    assert f.cause == cause


def test_guide_is_not_a_separate_field_on_finding() -> None:
    """guide 는 메시지에 이어붙을 뿐 `Finding` 의 필드가 아니다 (schema.md 11절)."""
    f = finding("STR-CONTRACT-001", file="/abs/x.py")
    assert "guide" not in f.model_dump(by_alias=True)
    assert get_rule("STR-CONTRACT-001").guide in f.message
