"""`strictler.refs` — 참조 문법 4종과 경로 규칙.

근거는 `schema.md` 2·3·12절, `rules.md` PATH·REG·CMP·STATE.
"""

from __future__ import annotations

import getpass
import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from strictler import refs, rules
from strictler.errors import StrictlerError
from strictler.refs import (
    NAMESPACES,
    Placeholder,
    collect_placeholders,
    expand_config,
    expand_all,
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


@pytest.mark.parametrize(
    "value",
    [
        "${BUTTONSCRIPT}",  # 네임스페이스 없음
        "${vars.HOME}",  # 모르는 네임스페이스
        "${Env.HOME}",  # 대문자 — 모르는 네임스페이스
        "${env.}",  # 이름 비었음
    ],
)
def test_malformed_reference_is_ref_006(value: str) -> None:
    """네임스페이스 없음 / 모름 / 이름 비었음은 전부 `STR-REF-006` 이다."""
    with pytest.raises(StrictlerError) as exc:
        collect_placeholders(value)
    assert _rule_ids(exc) == ["STR-REF-006"]


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


@pytest.mark.parametrize(
    "value",
    [
        "${ref.}",  # 이름 비었음
        "${vars.x}",  # 모르는 네임스페이스
        "${BUTTON}",  # 네임스페이스 없음
    ],
)
def test_parse_ref_malformed_is_ref_006(value: str) -> None:
    """`parse_ref` 로 들어와도 `STR-REF-006` 이 붙는다.

    이 셋은 `rules.md` `STR-REF-006` 이 열거한 세 경우 **그 자체**다.
    `is_ref()` 가 `False` 를 돌려준다는 이유로 형태 판별 이전 단계에서 id 없이
    튕기면, 같은 입력이 `collect_placeholders` 로 가면 `-006` 이 붙는데
    `parse_ref` 로 가면 id 가 사라지는 비대칭이 생긴다.
    """
    with pytest.raises(StrictlerError) as exc:
        parse_ref(value)
    assert _rule_ids(exc) == ["STR-REF-006"]


@pytest.mark.parametrize(
    "value",
    [
        "nd_abc",  # 참조가 아니다
        "${env.HOME}",  # 문법은 멀쩡한데 자리가 다르다
    ],
)
def test_parse_ref_non_reference_is_not_ref_006(value: str) -> None:
    """성격이 다른 둘은 `-006` 으로 묶지 않는다.

    문법이 깨진 게 아니라서 "네임스페이스를 반드시 붙입니다" 가이드를 주면
    AI 가 엉뚱한 곳을 고친다. 규칙 없이 나가는 것이 맞다.
    """
    with pytest.raises(StrictlerError) as exc:
        parse_ref(value)
    assert _rule_ids(exc) == [""]


def test_parse_ref_malformed_message_comes_from_rules() -> None:
    """문구를 손으로 복제하지 않고 `rules` 에서 받는다 (R2-7)."""
    with pytest.raises(StrictlerError) as exc:
        parse_ref("${vars.x}")
    expected = rules.finding("STR-REF-006", fields={"ref": "${vars.x}"}).message
    assert exc.value.message.endswith(expected)


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


# ── 환경변수 값 안의 `~` — 3단계 전개 (`~` → env → `~` 재전개) ───────────────


def test_expand_path_env_value_tilde_at_start() -> None:
    """`PROJECT_ROOT=~/proj` 는 흔한 설정이다 — 상대경로 오진단이 나면 안 된다."""
    out = expand_path("${env.PROJECT_ROOT}/x.json", {"PROJECT_ROOT": "~/proj"})
    assert out.is_absolute()
    assert out == Path(os.path.expanduser("~/proj")) / "x.json"


def test_expand_path_env_value_tilde_mid_path() -> None:
    """중간자리의 `~` 도 전개된다 — 리터럴 `~` 가 박힌 채 조용히 통과하면 안 된다."""
    out = expand_path("/srv/${env.SUB}/x.json", {"SUB": "~/proj"})
    home = os.path.expanduser("~")
    assert "~" not in str(out)
    assert out == Path(f"/srv{home}/proj/x.json")


def test_expand_path_env_value_bare_tilde() -> None:
    """값이 `~` 하나여도 전개된다."""
    out = expand_path("${env.ROOT}/x.json", {"ROOT": "~"})
    assert out == Path(os.path.expanduser("~")) / "x.json"


@pytest.mark.parametrize("template", ["${env.R}/x.json", "/srv/${env.R}/x.json"])
def test_expand_path_env_value_tilde_user(template: str) -> None:
    """`~user` 형태도 `os.path.expanduser` 가 처리한다 — 앞자리·중간자리 모두."""
    user = getpass.getuser()
    raw = f"~{user}/proj"
    expanded = os.path.expanduser(raw)
    if expanded == raw:  # 이 환경에서 `~user` 를 못 푸는 경우
        pytest.skip(f"`~{user}` 전개 불가 환경")
    out = expand_path(template, {"R": raw})
    assert "~" not in str(out)
    assert out == Path(template.replace("${env.R}", expanded))


# ── 잔여 `${` — 경로 해석 시점엔 모든 참조가 풀려 있어야 한다 ────────────────


def test_expand_path_leftover_config_ref_is_ref_007() -> None:
    """전개 안 된 `${config.X}` 를 리터럴 조각으로 통과시키지 않는다.

    **`-006` 이 아니라 `-007` 이다** (R2-6): 문법은 완전히 정상이고 잘못된 건
    전개 순서다. 규칙을 나누는 기준은 "증상" 이 아니라 "고치는 방법" 이다.
    """
    with pytest.raises(StrictlerError) as exc:
        expand_path("/x/${config.y}/z", {})
    assert _rule_ids(exc) == ["STR-REF-007"]


def test_expand_path_leftover_state_ref_is_ref_007() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_path("/x/${state.phase}/z", {})
    assert _rule_ids(exc) == ["STR-REF-007"]


def test_expand_path_leftover_ref_at_start_is_ref_007_not_path_001() -> None:
    """앞자리에 남은 참조는 '상대경로' 가 아니라 '잔여 참조' 로 진단해야 한다."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("${config.root}/z", {})
    assert _rule_ids(exc) == ["STR-REF-007"]


def test_unresolved_message_names_the_reference_and_not_the_malformed_guide() -> None:
    """`-007` 은 `-006` 의 가이드를 주면 안 된다 — 그게 규칙을 나눈 이유다."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("/x/${config.y}/z", {})
    assert "${config.y}" in exc.value.message
    assert "네임스페이스를 반드시 붙입니다" not in exc.value.message
    expected = rules.finding("STR-REF-007", fields={"ref": "${config.y}"}).message
    assert exc.value.message.endswith(expected)


def test_expand_path_unclosed_brace_is_ref_006() -> None:
    """닫히지 않은 `${` 는 **문법이 깨진 것**이므로 `-006` 이다 — `-007` 과 갈린다."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("/opt/${env.HOME/x", {"HOME": "/home/u"})
    assert _rule_ids(exc) == ["STR-REF-006"]


def test_expand_path_unclosed_brace_from_env_value_is_ref_006() -> None:
    """환경변수 값이 `${` 를 끌고 들어와도 잡힌다."""
    with pytest.raises(StrictlerError) as exc:
        expand_path("${env.ROOT}/x", {"ROOT": "/srv/${config.a"})
    assert _rule_ids(exc) == ["STR-REF-006"]


@pytest.mark.parametrize("injected", ["${vars.a}", "${X}", "${env.}"])
def test_expand_path_malformed_from_env_value_is_ref_006(injected: str) -> None:
    """env 값이 **닫혀 있지만 깨진** 참조를 끌고 들어온 경우도 `-006` 이다.

    이쪽은 원본에 없던 참조라 `collect_placeholders` 를 통과해 버린다.
    """
    with pytest.raises(StrictlerError) as exc:
        expand_path("${env.ROOT}/x", {"ROOT": f"/srv/{injected}"})
    assert _rule_ids(exc) == ["STR-REF-006"]


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


# ── 회귀 방지 — `-007` 을 전개기까지 확대하지 않는다 ─────────────────────────
#
# `expand_config`/`expand_state` 가 **다른 네임스페이스를 남기는 것은 정상**이다
# (합성 순서 때문에 그게 맞다). 잔여 검사는 최종 관문인 `expand_path` 만 한다 —
# 여기까지 `STR-REF-007` 을 확대하면 합성 자체가 불가능해진다.


@pytest.mark.parametrize(
    "value",
    ["${env.HOME}/x", "/x/${state.phase}/z", "${env.R}/${state.p}/a"],
)
def test_expand_config_leaves_unresolved_others_without_error(value: str) -> None:
    assert expand_config(value, {}) == value


@pytest.mark.parametrize(
    "value",
    ["${env.HOME}/x", "/x/${config.y}/z", "${config.r}/${env.H}/a"],
)
def test_expand_state_leaves_unresolved_others_without_error(value: str) -> None:
    assert expand_state(value, {}) == value


def test_expand_env_leaves_unresolved_others_without_error() -> None:
    """`expand_env` 도 마찬가지다 — 경로 검증은 `expand_path` 의 몫이다."""
    assert expand_env("${env.R}/${config.y}", {"R": "/srv"}) == "/srv/${config.y}"


# ── 슬롯 누락 회귀 방지 — 오류 경로 전수 ─────────────────────────────────────
#
# `rules.Rule.slots` 가 요구하는 값을 `fields` 로 안 넘기면 `_render` 가 거절하고,
# **원래 나와야 할 규칙 id 가 사라진다** (findings 가 비고 슬롯 누락 오류로 바뀐다).
# 그래서 "오류 경로를 실제로 태워 `rule_id` 를 확인" 하는 것이 곧 슬롯 검증이다.
#
# 표가 낡지 않도록 `refs.py` 의 `_fail("STR-...")` 호출부를 소스에서 뽑아
# **전수 대조**한다 — 새 규칙을 내면서 여기 예제를 안 넣으면 테스트가 깨진다.

_ERROR_PATHS: list[tuple[str, Callable[[], object]]] = [
    ("STR-PATH-001", lambda: expand_path("nodes/a.json", {})),
    ("STR-PATH-001", lambda: expand_path("", {})),
    ("STR-PATH-002", lambda: expand_path("${env.NOPE}/x.json", {})),
    ("STR-PATH-003", lambda: expand_path("${env.R}/x.json", {"R": "./foo"})),
    ("STR-REF-006", lambda: collect_placeholders("${vars.HOME}")),
    ("STR-REF-006", lambda: expand_path("/opt/${env.HOME/x", {"HOME": "/home/u"})),
    ("STR-REF-007", lambda: expand_path("/x/${config.y}/z", {})),
    ("STR-REG-003", lambda: parse_ref("${ref.xx_deadbeef}")),
    ("STR-REG-003", lambda: parse_ref("${ref.pl_c9d0e1f2}", expected="node")),
    ("STR-CONFIG-001", lambda: expand_config("${config.nope}", {})),
    (
        "STR-CMP-004",
        lambda: expand_config("${config.nope}", {"targets": {"v2": {}}}, target="v2"),
    ),
    ("STR-STATE-001", lambda: expand_state("${state.__mine}", {"__mine": "x"})),
    ("STR-STATE-002", lambda: expand_state("${state.phase}", {})),
    # `expand_all` — 스크립트에 넘기는 값의 잔여 참조 (R5-1)
    (
        "STR-REF-007",
        lambda: expand_all(
            {"p": "${ref.sc_deadbeef}/x"}, config={}, state={}, env={}
        ),
    ),
]

_UNFILLED_SLOT_C = re.compile(r"(?<!\$)\{(\w+)\}")
"""`{name}` 은 안 채워진 슬롯, `${env.X}` 는 가이드 본문이다 (R1-4)."""

_FAIL_SITE_C = re.compile(r'_fail\(\s*\n?\s*"(STR-[A-Z]+-\d+)"')
"""`refs.py` 안의 `_fail("STR-...")` 호출부."""


@pytest.mark.parametrize(
    "rule_id, trigger",
    _ERROR_PATHS,
    ids=[f"{rule_id}-{i}" for i, (rule_id, _) in enumerate(_ERROR_PATHS)],
)
def test_error_path_carries_its_rule_id(
    rule_id: str, trigger: Callable[[], object]
) -> None:
    """오류 경로마다 규칙 id 가 살아 나온다 — 슬롯을 안 채우면 여기서 사라진다."""
    with pytest.raises(StrictlerError) as exc:
        trigger()
    assert _rule_ids(exc) == [rule_id]


@pytest.mark.parametrize(
    "rule_id, trigger",
    _ERROR_PATHS,
    ids=[f"{rule_id}-{i}" for i, (rule_id, _) in enumerate(_ERROR_PATHS)],
)
def test_error_path_leaves_no_unfilled_slot(
    rule_id: str, trigger: Callable[[], object]
) -> None:
    """리포트에 `{path}` 가 그대로 새면 그건 검사기의 버그다."""
    with pytest.raises(StrictlerError) as exc:
        trigger()
    assert _UNFILLED_SLOT_C.findall(exc.value.message) == []


def test_every_fail_site_in_refs_is_exercised() -> None:
    """`refs.py` 가 내는 규칙 전부가 위 표에 있다.

    새 `_fail` 을 추가하면서 예제를 안 넣으면 여기서 걸린다 — 슬롯 누락이
    "언젠가 실행됐을 때" 가 아니라 **이 자리에서** 드러난다.
    """
    source = Path(refs.__file__).read_text(encoding="utf-8")
    declared = set(_FAIL_SITE_C.findall(source))
    assert declared, "`_fail` 호출부를 하나도 못 찾았다 — 정규식이 낡았다"
    assert declared == {rule_id for rule_id, _ in _ERROR_PATHS}


# ── expand_all — 스크립트에 넘기는 값 (R5-1) ─────────────────────────────────


def test_expand_all_은_config_state_env_를_그_순서로_푼다() -> None:
    """**순서가 계약이다.** config·state 값이 `${env.Y}` 를 품을 수 있으므로 env 가
    마지막이다 — 반대로 하면 config 가 끌고 들어온 `${env.Y}` 가 그대로 남는다."""
    out = expand_all(
        {"page": "${config.pagePath}", "at": "${state.__startedAt}"},
        config={"pagePath": "${env.ROOT}/targets/home.html"},
        state={"__startedAt": 17},
        env={"ROOT": "/srv/demo"},
    )
    assert out == {"page": "/srv/demo/targets/home.html", "at": 17}


def test_expand_all_은_중첩_구조를_재귀한다() -> None:
    out = expand_all(
        {"paths": ["${env.ROOT}/a", {"deep": "${env.ROOT}/b"}]},
        config={},
        state={},
        env={"ROOT": "/srv"},
    )
    assert out == {"paths": ["/srv/a", {"deep": "/srv/b"}]}


def test_expand_all_은_타입을_보존한다() -> None:
    """문자열 전체가 참조 하나면 값 자체를 준다 — `"2"` 가 아니라 `2`."""
    out = expand_all({"n": "${config.n}"}, config={"n": 3}, state={}, env={})
    assert out == {"n": 3}


def test_expand_all_은_남은_참조를_STR_REF_007_로_잡는다() -> None:
    """리터럴로 통과시키면 나중에 엉뚱한 오류로 원인이 뭉개진다."""
    with pytest.raises(StrictlerError) as exc:
        expand_all({"p": "${ref.sc_deadbeef}/x"}, config={}, state={}, env={})
    assert _rule_ids(exc) == ["STR-REF-007"]


def test_expand_all_의_미정의_env_는_STR_PATH_002() -> None:
    with pytest.raises(StrictlerError) as exc:
        expand_all({"p": "${env.NOPE}/x"}, config={}, state={}, env={})
    assert _rule_ids(exc) == ["STR-PATH-002"]


def test_expand_all_은_target_을_받는다() -> None:
    """비교 파이프라인은 `targets.<이름>` 이 공통을 이긴다."""
    out = expand_all(
        {"s": "${config.script}"},
        config={"script": "공통", "targets": {"v2": {"script": "브이투"}}},
        state={},
        env={},
        target="v2",
    )
    assert out == {"s": "브이투"}
