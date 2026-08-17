"""`locale` — 출력 문자열 카탈로그 (`schema.md` 2절 「출력 언어」).

★ **이 파일의 중심은 슬롯 집합 일치 검사다.** 번역이 `{id}` 같은 자리표시자를 하나라도
빠뜨리면 렌더가 어긋나 **규칙 id 가 출력에서 통째로 사라진다** — 이 프로젝트가 실제로
겪은 사고다(MODULES.md R1-2/R1-3, 11건). 정적으로 잡을 수 있는 유일한 자리가 여기다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from lintomata import locale
from lintomata.locale import (
    DEFAULT_LOCALE,
    available_locales,
    catalog,
    config_locale,
    fill,
    message,
    resolve_locale,
    scan_option,
    slot_mismatches,
    slots_of,
    translate,
)
from lintomata.rules import RULES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lintomata"

_TRANSLATING = {"message", "_msg", "translate", "_"}
"""원문을 카탈로그에 태우는 호출들. `cli` 는 `_` / `_msg`, 나머지는 `message`."""


@pytest.fixture(autouse=True)
def _restore_locale():
    """로케일은 모듈 전역이다 — 테스트가 서로를 오염시키지 않게 되돌린다."""
    before = locale.current_locale()
    yield
    locale.set_locale(before)


# ── ★ 슬롯 집합 일치 — 이 기능의 유일한 안전장치 ─────────────────────


@pytest.mark.parametrize("name", [x for x in available_locales() if x != DEFAULT_LOCALE])
def test_catalogs_preserve_slot_sets(name: str) -> None:
    """**모든 로케일 · 모든 문자열**이 원문과 정확히 같은 슬롯 집합을 갖는다."""
    bad = slot_mismatches(catalog(name))
    assert bad == [], "\n".join(
        f"[{name}] {source!r}: 빠진 슬롯 {missing or '-'} / 남는 슬롯 {extra or '-'}"
        for source, missing, extra in bad
    )


def test_slot_mismatch_is_actually_detected() -> None:
    """검사기 자체가 무는지 본다 — 카탈로그가 비어도 이 테스트는 산다.

    `test_catalogs_preserve_slot_sets` 는 카탈로그가 깨끗하면 통과하므로, 그것만으로는
    *검사기가 죽어 있어도* 초록이다. 그래서 일부러 틀린 것을 넣어 확인한다.
    """
    dropped = slot_mismatches({"cannot resolve {id}": "{id} 를 풀 수 없습니다"})
    assert dropped == []

    dropped = slot_mismatches({"cannot resolve {id}": "참조를 풀 수 없습니다"})
    assert dropped == [("cannot resolve {id}", "id", "")]

    invented = slot_mismatches({"cannot resolve": "{id} 를 풀 수 없습니다"})
    assert invented == [("cannot resolve", "", "id")]

    both = slot_mismatches({"{a} and {b}": "{b} 그리고 {c}"})
    assert both == [("{a} and {b}", "a", "c")]


def test_slot_order_may_differ_but_the_set_may_not() -> None:
    """어순은 언어마다 다르다 — 보존해야 하는 것은 **집합**이지 순서가 아니다."""
    assert slot_mismatches({"{a} then {b}": "{b} 다음에 {a}"}) == []


def test_reference_syntax_is_not_a_slot() -> None:
    """문구에 그대로 들어 있는 `${env.X}` 는 자리표시자가 아니다 (점이 있다)."""
    assert slots_of("use ${env.HOME} or ${ref.sc_1}") == frozenset()
    assert slots_of("{path} under ${env.X}") == frozenset({"path"})


def test_ko_covers_every_rule_string() -> None:
    """규칙 69개의 `message`+`guide` 138개가 전부 `ko` 에 있다.

    빠져도 영어가 나갈 뿐 도구는 돈다 — 그래서 **테스트가 아니면 아무도 모른다.**
    """
    entries = catalog("ko")
    missing = [
        (rule.id, field)
        for rule in RULES.values()
        for field in ("message", "guide")
        if getattr(rule, field) not in entries
    ]
    assert missing == []


def _translated_literals() -> dict[str, list[str]]:
    """`src` 전체에서 **번역을 타는 원문 리터럴**을 걷는다 — `{원문: [위치…]}`.

    f-string 으로 값을 미리 박은 문자열은 여기 걸리지 않는다(리터럴이 아니다) —
    그런 것은 애초에 카탈로그의 키가 될 수 없으므로 `message()` 로 못 쓴다.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in _TRANSLATING or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                where = f"{path.relative_to(ROOT)}:{node.lineno}"
                found.setdefault(first.value, []).append(where)
    return found


def test_ko_covers_every_translated_literal() -> None:
    """★ 규칙 문구만이 아니라 **오류 안내·CLI 문구도 전부** `ko` 에 있다.

    빠져도 영어가 나갈 뿐 도구는 돈다 — `test_ko_covers_every_rule_string` 과
    같은 이유로 **테스트가 아니면 아무도 모른다.** 새 문자열을 영어로만 넣고
    카탈로그를 안 채우면 여기서 걸린다.
    """
    entries = catalog("ko")
    missing = sorted(
        (source, places[0])
        for source, places in _translated_literals().items()
        if source not in entries
    )
    assert missing == []


def test_the_literal_collector_actually_finds_things() -> None:
    """수집기가 죽어 있으면 위 테스트가 **빈 집합을 통과**한다 — 그걸 막는다."""
    found = _translated_literals()
    assert len(found) > 100
    assert any(place.startswith("src/lintomata/cli.py") for places in found.values() for place in places)
    assert "the value emitted by `returnResult()`" in found


def test_message_translates_then_fills() -> None:
    """`message()` 는 **번역 → 치환** 순서다. 값이 먼저 박히면 키가 안 맞는다."""
    locale.set_locale("ko")
    text = message("Deleted {id}.", id="sc_1")
    assert text == "sc_1 를 삭제했습니다."

    locale.set_locale(DEFAULT_LOCALE)
    assert message("Deleted {id}.", id="sc_1") == "Deleted sc_1."


def test_fill_leaves_unknown_braces_alone() -> None:
    """★ `str.format` 이 아닌 이유 — 문구 안의 `` `{...}` `` 는 자리표시자가 아니다.

    번역이 원문에 없는 슬롯을 만들어낸 경우도 같다. 여기서 터지면
    **번역 오타가 도구를 못 돌게 만든다.**
    """
    assert fill("top level is an object (`{...}`)", {}) == "top level is an object (`{...}`)"
    assert fill("{a} and {b}", {"a": 1}) == "1 and {b}"
    assert fill("keep ${env.HOME}", {"env": "x"}) == "keep ${env.HOME}"


def test_rules_md_quotes_the_ko_catalog() -> None:
    """★ `docs/rules.md` 의 guide 열은 `ko.json` 에서 **인용한 것**이다.

    원문이 둘이면 반드시 갈린다 (`schema.md` 2절). 표 칸에 줄바꿈을 넣을 수 없으므로
    `guide` 안의 개행은 `<br>` 로 적는다 — 그것만 되돌려 글자 단위로 대조한다.
    """
    text = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")
    entries = catalog("ko")

    quoted: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 5:
            continue
        match = re.match(r"^`(LNT-[A-Z]+-\d{3})`$", cells[0])
        if match:
            quoted[match.group(1)] = cells[4].replace("<br>", "\n")

    assert set(quoted) == set(RULES), "rules.md 의 규칙 행이 테이블과 다르다"
    drifted = [
        rule_id
        for rule_id, guide in quoted.items()
        if guide != entries.get(RULES[rule_id].guide, RULES[rule_id].guide)
    ]
    assert drifted == []


def test_every_catalog_entry_is_a_nonempty_string() -> None:
    for name in available_locales():
        for key, value in catalog(name).items():
            assert key.strip(), name
            assert value.strip(), (name, key)


# ── 카탈로그 조회 — 없으면 원문. 예외를 내지 않는다 ───────────────────


def test_default_locale_has_no_catalog() -> None:
    assert catalog(DEFAULT_LOCALE) == {}
    assert DEFAULT_LOCALE in available_locales()


def test_unknown_locale_is_an_empty_catalog_not_an_error() -> None:
    assert catalog("zz-nope") == {}


def test_translate_falls_back_to_the_source_text() -> None:
    locale.set_locale("ko")
    assert translate("Print as JSON") == "JSON 으로 출력"
    # 카탈로그에 없는 문자열은 **그대로** 나간다 — 번역 누락이 도구를 멈추지 않는다.
    assert translate("no such string in the catalog") == "no such string in the catalog"


def test_translate_is_identity_under_en() -> None:
    locale.set_locale(DEFAULT_LOCALE)
    assert translate("Print as JSON") == "Print as JSON"


def test_set_locale_normalises_empty_to_en() -> None:
    assert locale.set_locale("") == DEFAULT_LOCALE
    assert locale.set_locale("  ko  ") == "ko"
    assert locale.current_locale() == "ko"


# ── 선스캔 — `--help` 의 닭과 달걀 ────────────────────────────────────


def test_scan_option_reads_both_spellings() -> None:
    assert scan_option(["--lang", "ko", "check", "x"], "lang") == "ko"
    assert scan_option(["--lang=ko", "check", "x"], "lang") == "ko"
    assert scan_option(["check", "x"], "lang") == ""


def test_scan_option_finds_it_before_help_would_be_built() -> None:
    """`--lang ko --help` 는 파서를 만들기 전에 로케일이 정해져야 한글이 나온다."""
    assert scan_option(["--lang", "ko", "--help"], "lang") == "ko"


def test_scan_option_stops_at_the_double_dash() -> None:
    assert scan_option(["--", "--lang", "ko"], "lang") == ""


def test_scan_option_tolerates_a_dangling_flag() -> None:
    """argparse 가 제 자리에서 잡을 일이다 — 선스캔이 먼저 터지면 안 된다."""
    assert scan_option(["--lang"], "lang") == ""


# ── 결정 순서 — `--lang` > config.json > en. 환경변수는 없다 ──────────


def _home_with_config(tmp_path, text: str):
    home = tmp_path / "reg"
    home.mkdir(exist_ok=True)
    (home / "config.json").write_text(text, encoding="utf-8")
    return home


def test_config_locale_reads_the_registry_config(tmp_path) -> None:
    home = _home_with_config(tmp_path, json.dumps({"locale": "ko"}))
    assert config_locale(home) == "ko"


def test_config_locale_is_silent_when_missing(tmp_path) -> None:
    assert config_locale(tmp_path / "nope") == ""
    assert config_locale(None) == ""


def test_broken_config_json_falls_back_silently(tmp_path) -> None:
    """설정 파일 때문에 검사가 못 도는 것은 과하다 — 조용히 `en` 으로 간다."""
    home = _home_with_config(tmp_path, "{ this is not json")
    assert config_locale(home) == ""


def test_config_json_of_the_wrong_shape_falls_back(tmp_path) -> None:
    assert config_locale(_home_with_config(tmp_path, "[1, 2]")) == ""
    assert config_locale(_home_with_config(tmp_path, '{"locale": 7}')) == ""
    assert config_locale(_home_with_config(tmp_path, "{}")) == ""


def test_resolve_prefers_lang_over_config(tmp_path, monkeypatch) -> None:
    home = _home_with_config(tmp_path, json.dumps({"locale": "ko"}))
    monkeypatch.delenv("LINTOMATA_HOME", raising=False)
    assert resolve_locale(["--home", str(home), "script", "list"]) == "ko"
    assert resolve_locale(["--home", str(home), "--lang", "en", "script", "list"]) == "en"


def test_resolve_reads_lintomata_home_when_no_home_flag(tmp_path, monkeypatch) -> None:
    home = _home_with_config(tmp_path, json.dumps({"locale": "ko"}))
    monkeypatch.setenv("LINTOMATA_HOME", str(home))
    assert resolve_locale(["script", "list"]) == "ko"


def test_resolve_defaults_to_en(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LINTOMATA_HOME", str(tmp_path / "empty"))
    assert resolve_locale(["script", "list"]) == DEFAULT_LOCALE


def test_relative_registry_home_does_not_blow_up(monkeypatch) -> None:
    """경로 규칙 위반은 `Store` 가 잡을 일이다 — 로케일을 정하다 죽으면 안 된다."""
    monkeypatch.setenv("LINTOMATA_HOME", "./relative")
    assert resolve_locale(["script", "list"]) == DEFAULT_LOCALE


def test_lang_never_comes_from_the_environment(tmp_path, monkeypatch) -> None:
    """★ `LANG`/`LC_ALL` 을 따라가지 않는다 (`schema.md` 2절).

    리포트는 산출물이라 로케일을 주변 환경에서 주워오면 CI 와 로컬이 다른 리포트를 낸다.
    """
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    monkeypatch.setenv("LINTOMATA_LANG", "ko")
    monkeypatch.setenv("LINTOMATA_HOME", str(tmp_path / "empty"))
    assert resolve_locale(["script", "list"]) == DEFAULT_LOCALE


# ── `--help` — 파서를 만들기 전에 로케일이 정해졌는가 ────────────────


def _help_text(argv, capsys, monkeypatch, home) -> str:
    from lintomata import cli

    monkeypatch.setenv("LINTOMATA_HOME", str(home))
    with pytest.raises(SystemExit):
        cli.main([*argv, "--help"])
    return capsys.readouterr().out


def test_help_is_english_by_default(tmp_path, capsys, monkeypatch) -> None:
    out = _help_text([], capsys, monkeypatch, tmp_path / "empty")
    assert "the code that actually runs" in out
    assert "실제 동작 코드" not in out


def test_help_follows_the_lang_flag(tmp_path, capsys, monkeypatch) -> None:
    """★ 선스캔이 없으면 여기가 영어로 나온다 — `help=` 는 파서 구성 시점에 확정된다."""
    out = _help_text(["--lang", "ko"], capsys, monkeypatch, tmp_path / "empty")
    assert "실제 동작 코드" in out
    assert "the code that actually runs" not in out


def test_help_follows_the_registry_config(tmp_path, capsys, monkeypatch) -> None:
    home = _home_with_config(tmp_path, json.dumps({"locale": "ko"}))
    assert "실제 동작 코드" in _help_text([], capsys, monkeypatch, home)
    # `--lang` 이 config 를 이긴다.
    out = _help_text(["--lang", "en"], capsys, monkeypatch, home)
    assert "the code that actually runs" in out
