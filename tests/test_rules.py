"""`rules.py` — 규칙 테이블 57개와 `Finding` 생성 헬퍼."""

from __future__ import annotations

import re

import pytest

from strictler.errors import NotRunCause, StrictlerError
from strictler.rules import RULES, finding, get_rule, render, rules_for

ID_RE = re.compile(r"^STR-[A-Z]+-\d{3}$")

# `rules.md` 3절 "규칙 수 요약" 그대로.
EXPECTED_COUNTS = {
    "PATH": 4,
    "REF": 6,
    "GRAPH": 2,
    "TYPE": 7,
    "CONTRACT": 6,
    "STATE": 7,
    "BAN": 4,
    "TOOL": 2,
    "CONFIG": 3,
    "CMP": 4,
    "TEST": 7,
    "REG": 5,
}


def test_rule_count_is_57() -> None:
    assert len(RULES) == 57
    assert sum(EXPECTED_COUNTS.values()) == 57


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
        assert isinstance(rule.slots, tuple)


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
    f = finding("STR-CONTRACT-001", fields={"file": "/abs/x.py"})
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
        fields={"name": "checkToken"},
    )
    assert f.status == "not_run"
    assert f.path == "login.json > plan[0] > login-flow"
    assert f.node == "checkToken"
    assert f.cause == cause


def test_guide_is_not_a_separate_field_on_finding() -> None:
    """guide 는 메시지에 이어붙을 뿐 `Finding` 의 필드가 아니다 (schema.md 11절)."""
    f = finding("STR-CONTRACT-001", fields={"file": "/abs/x.py"})
    assert "guide" not in f.model_dump(by_alias=True)
    assert get_rule("STR-CONTRACT-001").guide in f.message


def test_finding_takes_no_fields_when_rule_has_no_slots() -> None:
    rule = get_rule("STR-TEST-005")
    assert rule.slots == ()
    f = finding("STR-TEST-005", status="violation")
    assert f.message.endswith(rule.guide)


def test_finding_missing_slot_lists_what_the_rule_needs() -> None:
    """에러 메시지가 자기 수정 신호가 되어야 한다 (읽는 주체가 AI)."""
    with pytest.raises(StrictlerError) as exc:
        finding("STR-TYPE-006", fields={"field": "x"})
    text = str(exc.value)
    assert "names" in text
    assert "types" in text
    assert "STR-TYPE-006" in text


# ── 슬롯 ↔ 파라미터 충돌 — R1-2 가 고친 실제 버그 ─────────────────────


def test_finding_slot_named_path_is_not_eaten_by_the_path_parameter() -> None:
    """`{path}` 슬롯과 `Finding.path` 는 서로 다른 것이다.

    `**fields` 였을 때는 keyword-only `path` 가 슬롯을 가로채
    `STR-PATH-001` 을 렌더할 방법이 아예 없었다.
    """
    f = finding(
        "STR-PATH-001",
        status="violation",
        path="login.json > plan[0] > login-flow",
        node="captureHtml",
        fields={"path": "./relative/script.py"},
    )
    assert f.path == "login.json > plan[0] > login-flow"
    assert "./relative/script.py" in f.message
    assert "{path}" not in f.message


def test_finding_slot_named_path_inside_guide_only() -> None:
    """`STR-TOOL-002` 는 `{path}` 가 **guide 에만** 있다 — 이름 변경 불가한 원문."""
    f = finding(
        "STR-TOOL-002",
        status="violation",
        path="login.json > plan[0] > login-flow",
        fields={"path": "/usr/local/bin/node"},
    )
    assert "/usr/local/bin/node" in f.message
    assert "{path}" not in f.message


def test_finding_slot_named_node_is_not_eaten_by_the_node_parameter() -> None:
    f = finding(
        "STR-CMP-002",
        status="violation",
        node="detectButtons",
        fields={"node": "detectButtons"},
    )
    assert f.node == "detectButtons"
    assert "{node}" not in f.message


def test_finding_accepts_python_keyword_slot() -> None:
    """`STR-TYPE-004` 의 `{in}` 은 예약어라 딕셔너리로만 넘길 수 있다."""
    f = finding("STR-TYPE-004", fields={"out": "Percept", "in": "Sensum"})
    assert "Percept" in f.message
    assert "Sensum" in f.message
    assert "{in}" not in f.message


# ── 전수 라운드트립 — 모든 규칙이 실제로 렌더된다 ─────────────────────


def _dummy_fields(rule_id: str) -> dict[str, object]:
    return {name: f"<{name}>" for name in get_rule(rule_id).slots}


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_renders_with_its_declared_slots(rule_id: str) -> None:
    """`slots` 만으로 `render()`/`finding()` 이 예외 없이 돌아야 한다.

    규칙 두어 개만 찔러보면 슬롯↔파라미터 충돌 같은 경계를 지나친다 —
    실제로 `STR-PATH-001`/`STR-TOOL-002`/`STR-CMP-002` 가 무조건 터지고 있었다.
    """
    rule = get_rule(rule_id)
    fields = _dummy_fields(rule_id)

    text = render(rule_id, **fields)
    f = finding(rule_id, path="p", node="n", fields=fields)

    assert f.message == text
    assert f.rule_id == rule_id
    for name in rule.slots:
        assert f"<{name}>" in text
        # 채워지지 않고 그대로 샌 자리표시자가 없어야 한다.
        assert f"{{{name}}}" not in text


def test_declared_slots_cover_every_placeholder_in_message_and_guide() -> None:
    """`slots` 는 손으로 적는 필드가 아니라 문구에서 뽑은 것이다."""
    slot_re = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
    for rule in RULES.values():
        found = list(
            dict.fromkeys(slot_re.findall(rule.message) + slot_re.findall(rule.guide))
        )
        assert list(rule.slots) == found, rule.id


def test_reference_syntax_is_never_mistaken_for_a_slot() -> None:
    """guide 의 `${env.X}` `${ref.<id>}` 는 점이 있어 슬롯이 아니다."""
    for rule in RULES.values():
        assert "env" not in rule.slots, rule.id
        assert "config" not in rule.slots, rule.id
        assert "state" not in rule.slots, rule.id


# ── 신설 규칙 3개 (rules.md 4절 증가 이력) ────────────────────────────


def test_new_rules_exist_with_declared_when_and_slots() -> None:
    assert get_rule("STR-TYPE-006").when == ("node-register", "pipeline-register")
    assert set(get_rule("STR-TYPE-006").slots) == {"names", "field", "types"}

    assert get_rule("STR-TYPE-007").when == ("node-register",)
    assert get_rule("STR-TYPE-007").slots == ("cycle",)

    assert get_rule("STR-REF-006").when == ("node-register", "pipeline-register", "run")
    assert get_rule("STR-REF-006").slots == ("ref",)


def test_malformed_reference_guide_keeps_namespace_examples() -> None:
    text = render("STR-REF-006", ref="${vars.X}")
    assert "${env.X}" in text
    assert "${ref.<id>}" in text
    assert "${vars.X}" in text
