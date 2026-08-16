"""`strictler.refs` — 참조 문법 4종과 경로 규칙.

근거는 `schema.md` 2·3·12절, `rules.md` PATH·REG·CMP·STATE.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path

import pytest

from strictler.errors import StrictlerError
from strictler.refs import (
    NAMESPACES,
    Placeholder,
    collect_placeholders,
    expand_config,
    expand_env,
    expand_path,
    expand_state,
    is_ref,
    parse_ref,
)


def _rule_ids(exc: pytest.ExceptionInfo[StrictlerError]) -> list[str]:
    return [f.rule_id for f in exc.value.findings]


# ── 네임스페이스 ─────────────────────────────────────────────────────────────


def test_namespaces_are_exactly_four() -> None:
    assert NAMESPACES == frozenset({"env", "config", "state", "ref"})


@pytest.mark.parametrize(
    "raw, ns, name",
    [
        ("${env.HOME}", "env", "HOME"),
        ("${config.expectedFields}", "config", "expectedFields"),
        ("${state.capturing}", "state", "capturing"),
        ("${ref.nd_e5f6a7b8}", "ref", "nd_e5f6a7b8"),
    ],
)
def test_collect_placeholders_each_namespace(raw: str, ns: str, name: str) -> None:
    """네 네임스페이스 각각이 전개 대상으로 잡힌다."""
    found = collect_placeholders(raw)
    assert found == [Placeholder(ns, name, raw, 0, len(raw))]


def test_collect_placeholders_multiple_in_order_with_positions() -> None:
    value = "${env.ROOT}/x/${config.name}.py"
    found = collect_placeholders(value)
    assert [(p.ns, p.name) for p in found] == [("env", "ROOT"), ("config", "name")]
    assert value[found[0].start : found[0].end] == "${env.ROOT}"
    assert value[found[1].start : found[1].end] == "${config.name}"


def test_collect_placeholders_none_in_plain_string() -> None:
    assert collect_placeholders("/abs/path/no/refs") == []


def test_namespaceless_reference_rejected() -> None:
    """`${X}` 는 미정의 환경변수인지 config 오타인지 구분 못 하므로 에러다."""
    with pytest.raises(StrictlerError) as exc:
        collect_placeholders("${BUTTONSCRIPT}")
    assert "네임스페이스" in exc.value.message
    assert exc.value.findings[0].status == "error"


def test_unknown_namespace_rejected() -> None:
    with pytest.raises(StrictlerError) as exc:
        collect_placeholders("${vars.HOME}")
    assert "vars" in exc.value.message


def test_uppercase_namespace_rejected() -> None:
    """네임스페이스는 소문자 넷뿐이다."""
    with pytest.raises(StrictlerError):
        collect_placeholders("${Env.HOME}")


def test_empty_reference_name_rejected() -> None:
    with pytest.raises(StrictlerError) as exc:
        collect_placeholders("${env.}")
    assert "이름" in exc.value.message


# ── `${ref.<id>}` ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        ("${ref.sc_a1b2c3d4}", True),
        ("${ref.nd_e5f6a7b8}", True),
        ("${env.HOME}", False),
        ("${ref.nd_e5f6a7b8}/x", False),  # 값 전체가 참조 하나여야 한다
        ("/abs/path.json", False),
    ],
)
def test_is_ref(value: str, expected: bool) -> None:
    assert is_ref(value) is expected


@pytest.mark.parametrize(
    "value, kind, entry_id",
    [
        ("${ref.sc_a1b2c3d4}", "script", "sc_a1b2c3d4"),
        ("${ref.nd_e5f6a7b8}", "node", "nd_e5f6a7b8"),
        ("${ref.pl_c9d0e1f2}", "pipeline", "pl_c9d0e1f2"),
        ("${ref.sp_3a4b5c6d}", "spec", "sp_3a4b5c6d"),
    ],
)
def test_parse_ref_kind_from_prefix(value: str, kind: str, entry_id: str) -> None:
    """종류는 id 접두가 말해준다 (`schema.md` 2절)."""
    assert parse_ref(value) == (kind, entry_id)


def test_parse_ref_pipeline_in_node_slot_rejected() -> None:
    """`${ref.pl_...}` 를 노드 자리에 쓰면 잡힌다 — `STR-REG-003`."""
    with pytest.raises(StrictlerError) as exc:
        parse_ref("${ref.pl_c9d0e1f2}", expected="node")
    assert _rule_ids(exc) == ["STR-REG-003"]


def test_parse_ref_matching_kind_passes() -> None:
    assert parse_ref("${ref.nd_e5f6a7b8}", expected="node") == ("node", "nd_e5f6a7b8")


def test_parse_ref_unknown_prefix_rejected() -> None:
    with pytest.raises(StrictlerError) as exc:
        parse_ref("${ref.xx_deadbeef}")
    assert _rule_ids(exc) == ["STR-REG-003"]


def test_parse_ref_on_non_ref_rejected() -> None:
    with pytest.raises(StrictlerError):
        parse_ref("${env.HOME}")


# ── `${env.X}` 전개 ──────────────────────────────────────────────────────────


def test_expand_env_substitutes_only_env() -> None:
    out = expand_env("${env.ROOT}/x/${config.name}", {"ROOT": "/opt/p"})
    assert out == "/opt/p/x/${config.name}"


def test_expand_env_undefined_is_path_002() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_env("${env.NOPE}/x", {})
    assert _rule_ids(exc) == ["STR-PATH-002"]


# ── 경로 규칙 ────────────────────────────────────────────────────────────────


def test_expand_path_plain_absolute() -> None:
    assert expand_path("/opt/strictler/nodes/a.json", {}) == Path(
        "/opt/strictler/nodes/a.json"
    )


def test_expand_path_relative_is_path_001() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("nodes/a.json", {})
    assert _rule_ids(exc) == ["STR-PATH-001"]


def test_expand_path_dot_relative_is_path_001() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("./nodes/a.json", {})
    assert _rule_ids(exc) == ["STR-PATH-001"]


def test_expand_path_empty_is_path_001() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("", {})
    assert _rule_ids(exc) == ["STR-PATH-001"]


def test_expand_path_tilde_expands_to_absolute() -> None:
    """`~` 는 상대경로가 아니다 — cwd 와 무관하게 홈으로 결정된다."""
    out = expand_path("~/.playwright/playwright", {})
    assert out.is_absolute()
    assert out == Path(os.path.expanduser("~/.playwright/playwright"))


def test_expand_path_tilde_user_expands_to_absolute() -> None:
    """`~user` 도 `os.path.expanduser` 가 처리한다."""
    user = getpass.getuser()
    raw = f"~{user}/scripts/x.py"
    expanded = os.path.expanduser(raw)
    if expanded == raw:  # 이 환경에서 `~user` 를 못 푸는 경우
        pytest.skip(f"`~{user}` 전개 불가 환경")
    out = expand_path(raw, {})
    assert out.is_absolute()
    assert out == Path(expanded)


def test_expand_path_env_expands_to_absolute() -> None:
    out = expand_path("${env.PROJECT_ROOT}/pipelines/login.json", {"PROJECT_ROOT": "/srv/p"})
    assert out == Path("/srv/p/pipelines/login.json")


def test_expand_path_env_undefined_is_path_002() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("${env.PROJECT_ROOT}/x.json", {})
    assert _rule_ids(exc) == ["STR-PATH-002"]


def test_expand_path_env_value_dot_relative_is_path_003() -> None:
    """`PROJECT_ROOT=./foo` → cwd 의존을 되살리므로 에러."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("${env.PROJECT_ROOT}/x.json", {"PROJECT_ROOT": "./foo"})
    assert _rule_ids(exc) == ["STR-PATH-003"]


def test_expand_path_env_value_bare_relative_is_path_003() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("${env.PROJECT_ROOT}/x.json", {"PROJECT_ROOT": "foo/bar"})
    assert _rule_ids(exc) == ["STR-PATH-003"]


def test_expand_path_env_value_relative_marker_mid_path_is_path_003() -> None:
    """앞자리가 아니어도 `../` 로 시작하는 값은 상대경로임이 명백하다."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("/srv/${env.SUB}/x.json", {"SUB": "../up"})
    assert _rule_ids(exc) == ["STR-PATH-003"]


def test_expand_path_env_segment_mid_path_is_fine() -> None:
    """앞자리가 아닌 자리의 상대적 조각은 절대경로를 깨지 않는다."""
    out = expand_path("/srv/${env.SUB}/x.json", {"SUB": "p/q"})
    assert out == Path("/srv/p/q/x.json")


def test_expand_path_result_relative_is_path_001() -> None:
    """전개 결과가 상대경로면 에러 — 규칙의 마지막 관문."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("sub/${env.HOME}", {"HOME": "/home/u"})
    assert _rule_ids(exc) == ["STR-PATH-001"]


# ── `${config.X}` 전개 ───────────────────────────────────────────────────────


def test_expand_config_preserves_type_for_whole_string_ref() -> None:
    """문자열 전체가 참조 하나면 `2` 이지 `"2"` 가 아니다."""
    assert expand_config("${config.expectedFields}", {"expectedFields": 2}) == 2


def test_expand_config_interpolates_inside_string() -> None:
    out = expand_config("${config.root}/scripts/x.py", {"root": "/srv/p"})
    assert out == "/srv/p/scripts/x.py"


def test_expand_config_recurses_into_containers() -> None:
    out = expand_config(
        {"a": ["${config.n}", "x-${config.n}"]},
        {"n": 3},
    )
    assert out == {"a": [3, "x-3"]}


def test_expand_config_leaves_other_namespaces_alone() -> None:
    assert expand_config("${env.HOME}/x", {}) == "${env.HOME}/x"


def test_expand_config_non_string_passthrough() -> None:
    assert expand_config(2000, {}) == 2000


def test_expand_config_missing_without_target_is_config_001() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_config("${config.nope}", {})
    assert _rule_ids(exc) == ["STR-CONFIG-001"]


def test_expand_config_target_scope_wins_over_common() -> None:
    config = {
        "buttonScript": "/common.py",
        "targets": {"v2": {"buttonScript": "/v2.py"}},
    }
    assert expand_config("${config.buttonScript}", config, target="v2") == "/v2.py"


def test_expand_config_falls_back_to_common_when_target_lacks_it() -> None:
    config = {"settleMs": 2000, "targets": {"v2": {"buttonScript": "/v2.py"}}}
    assert expand_config("${config.settleMs}", config, target="v2") == 2000


def test_expand_config_missing_in_both_is_cmp_004() -> None:
    config = {"targets": {"v2": {"buttonScript": "/v2.py"}}}
    with pytest.raises(StrictlerError) as exc:
        expand_config("${config.roleAttr}", config, target="v2")
    assert _rule_ids(exc) == ["STR-CMP-004"]


# ── `${state.X}` 전개 ────────────────────────────────────────────────────────


def test_expand_state_user_state() -> None:
    assert expand_state("${state.phase}", {"phase": "capturing"}) == "capturing"


def test_expand_state_engine_field_started_at() -> None:
    """`__startedAt` 은 엔진이 채우는 epoch 밀리초 정수다."""
    assert expand_state("${state.__startedAt}", {"__startedAt": 1755300000000}) == 1755300000000


def test_expand_state_reserved_prefix_is_state_001() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_state("${state.__mine}", {"__mine": "x"})
    assert _rule_ids(exc) == ["STR-STATE-001"]


def test_expand_state_unmapped_is_state_002() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_state("${state.phase}", {})
    assert _rule_ids(exc) == ["STR-STATE-002"]


def test_expand_state_leaves_other_namespaces_alone() -> None:
    assert expand_state("${config.x}", {}) == "${config.x}"
