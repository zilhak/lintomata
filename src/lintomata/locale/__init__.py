"""출력 문자열 카탈로그 (`schema.md` 2절 「출력 언어」).

**CLI 가 내보내는 모든 문자열의 원문은 영어다.** 한글을 비롯한 다른 언어는
`<locale>.json` 카탈로그로 얹는다. 어휘의 정본은 옆의 `GLOSSARY.md`.

### 키는 영어 원문 문자열이다 (gettext 의 msgid 방식)

`"path.absolute.required"` 같은 **키를 새로 발명하지 않는다.** 문자열이 수십 곳에
흩어져 있는데 거기에 키를 붙이는 작업은 그 자체로 번역보다 크고, 키와 원문이
갈라지면 *"이 키가 지금 무슨 문장이었더라"* 를 아무도 모르게 된다.
→ 원문을 고치면 키가 바뀐다. 카탈로그도 **같은 커밋에서** 고친다.

### 로케일 결정 순서 — `--lang` > 등록소 `config.json` 의 `locale` > `en`

**환경변수를 두지 않는다. `LANG`/`LC_ALL` 도 읽지 않는다** (`schema.md` 2절이 명시적으로
금지한다). 리포트는 **산출물**이라 로케일을 주변 환경에서 주워오면 CI 와 로컬이 다른
리포트를 낸다. 경로 규칙이 cwd 의존성을 없앤 것과 같은 이유다.

`config.json` 이 없거나 깨졌으면 **조용히 `en` 으로 간다.** 설정 파일 때문에 검사가
못 도는 것은 과하다 — 그건 lint 결과가 아니라 도구가 못 돈 것이 되어버린다.

### 카탈로그에 없으면 영어 원문을 그대로 낸다

**절대 예외를 내지 않는다.** 번역이 덜 됐다는 이유로 검사가 멈추면, 번역이 판정에
영향을 주는 셈이 된다 (`schema.md` 2절: `config.json` 에는 표현만 들어간다).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence

__all__ = [
    "DEFAULT_LOCALE",
    "SLOT_RE",
    "available_locales",
    "catalog",
    "config_locale",
    "current_locale",
    "fill",
    "message",
    "resolve_locale",
    "scan_option",
    "set_locale",
    "slot_mismatches",
    "slots_of",
    "translate",
]


DEFAULT_LOCALE = "en"
"""원문의 언어. 이 로케일에는 카탈로그가 없다 — 원문이 곧 출력이다."""

SLOT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
"""자리표시자 하나. **`{name}` 처럼 점 없는 식별자 하나**만 자리표시자로 본다.

문구에 그대로 들어 있는 `${env.X}` `${ref.sc_...}` 같은 참조 문법은 점이 있어
걸리지 않는다 — 번역이 그걸 건드리면 안 되기 때문이다.

**정의가 여기 있는 이유**는 이것이 곧 *번역이 보존해야 할 것*의 정의이기 때문이다.
`rules` 가 이걸 가져다 쓴다 (두 벌로 두면 갈리고, 갈린 쪽이 곧 사고다).
"""

_DIR = Path(__file__).resolve().parent
_current: str = DEFAULT_LOCALE
_cache: dict[str, dict[str, str]] = {}


# ── 카탈로그 ─────────────────────────────────────────────────────────────────


def available_locales() -> tuple[str, ...]:
    """쓸 수 있는 로케일 — `en` + 이 폴더의 `<locale>.json` 들."""
    found = sorted(path.stem for path in _DIR.glob("*.json"))
    return (DEFAULT_LOCALE, *(name for name in found if name != DEFAULT_LOCALE))


def catalog(locale: str) -> dict[str, str]:
    """`<locale>.json` 을 읽어 준다. **읽을 수 없으면 빈 카탈로그다** (예외 없음).

    `en` 은 원문 자체이므로 카탈로그가 없다.
    """
    if locale in _cache:
        return _cache[locale]
    loaded: dict[str, str] = {}
    if locale and locale != DEFAULT_LOCALE:
        try:
            raw = json.loads((_DIR / f"{locale}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            raw = None
        if isinstance(raw, dict):
            loaded = {
                key: value
                for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    _cache[locale] = loaded
    return loaded


def current_locale() -> str:
    """지금 출력에 쓰이는 로케일."""
    return _current


def set_locale(locale: str) -> str:
    """출력 로케일을 정한다. 빈 값이면 `en`. 반환값은 실제로 정해진 로케일이다."""
    global _current
    _current = locale.strip() or DEFAULT_LOCALE
    return _current


def translate(text: str) -> str:
    """원문 → 현재 로케일의 문장. **없으면 원문 그대로.**"""
    if _current == DEFAULT_LOCALE:
        return text
    return catalog(_current).get(text, text)


def fill(template: str, fields: Mapping[str, object]) -> str:
    """`{식별자}` 자리표시자를 `fields` 로 치환한다.

    **모르는 이름은 그대로 둔다.** 문구에 `` `{...}` `` 처럼 자리표시자가 아닌
    중괄호가 그대로 들어 있는 자리가 있고(코드 예시), 번역이 원문에 없는 슬롯을
    만들어낼 수도 있다. 거기서 `KeyError` 로 터지면 **번역 오타가 도구를 못 돌게
    만든다** — 그건 lint 결과가 아니라 도구가 못 돈 것이 되어버린다.
    어긋난 카탈로그는 `slot_mismatches` 가 테스트에서 잡는다.

    ★ `str.format` 을 쓰지 않는 이유가 이것이다.
    """
    return SLOT_RE.sub(
        lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0),
        template,
    )


def message(template: str, /, **fields: object) -> str:
    """원문 → 번역 → 자리표시자 치환. **오류 문구를 만드는 유일한 통로다.**

    ★ **자리표시자를 f-string 으로 미리 박으면 안 된다.** 그러면 값이 섞인 문자열이
    카탈로그의 키가 되어 **어떤 번역과도 맞지 않는다** — 경로 하나 바뀔 때마다
    다른 키가 된다. 값은 `{path}` 처럼 슬롯으로 남기고 여기서 채운다.

    `raise LintomataError(message("… {path} …", path=path))` 가 표준 형태다.
    """
    return fill(translate(template), fields)


# ── 로케일 결정 ──────────────────────────────────────────────────────────────


def scan_option(argv: Sequence[str], name: str) -> str:
    """파서를 만들기 **전에** `--lang` / `--home` 을 argv 에서 직접 꺼낸다.

    ★ **닭과 달걀이다.** argparse 의 `help=` 는 **파서를 만들 때** 확정되는데
    `--lang` 은 그 파서가 파싱한다 → 파서를 만들고 나서 로케일을 정하면
    `lintomata --lang ko --help` 가 영어로 나온다. 그래서 선스캔한다.

    `--lang ko` 와 `--lang=ko` 두 형태를 본다. `--` 뒤는 옵션이 아니므로 멈춘다.
    **여기서 형식을 판정하지 않는다** — 잘못된 값은 argparse 가 제 자리에서 잡는다.
    """
    flag = f"--{name}"
    prefix = f"{flag}="
    for index, token in enumerate(argv):
        if token == "--":
            break
        if token == flag:
            return argv[index + 1] if index + 1 < len(argv) else ""
        if token.startswith(prefix):
            return token[len(prefix) :]
    return ""


def _home_of(argv: Sequence[str]) -> Path | None:
    """`config.json` 을 찾을 등록소 경로. **폴더를 만들지 않는다.**

    `store.default_home()` 과 같은 자리를 보지만 그것을 부르지는 않는다 —
    저쪽은 상대경로에 예외를 내고 폴더를 만든다. 로케일을 정하는 것뿐인데
    등록소가 생기거나 검사가 멈추면 안 된다.
    """
    raw = (scan_option(argv, "home") or os.environ.get("LINTOMATA_HOME", "")).strip()
    home = Path(os.path.expanduser(raw or "~/.lintomata"))
    return home if home.is_absolute() else None


def config_locale(home: Path | None) -> str:
    """`$LINTOMATA_HOME/config.json` 의 `locale`. **없거나 깨졌으면 빈 문자열.**"""
    if home is None:
        return ""
    try:
        raw = json.loads((home / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    value = raw.get("locale", "")
    return value.strip() if isinstance(value, str) else ""


def resolve_locale(argv: Sequence[str]) -> str:
    """`--lang` > 등록소 `config.json` 의 `locale` > `en`. **환경변수는 보지 않는다.**"""
    return scan_option(argv, "lang").strip() or config_locale(_home_of(argv)) or DEFAULT_LOCALE


# ── 슬롯 보존 — 이 기능의 유일한 안전장치 ────────────────────────────────────


def slots_of(text: str) -> frozenset[str]:
    """문구가 요구하는 자리표시자 이름의 **집합**. 순서는 보지 않는다.

    어순은 언어마다 다르므로 순서까지 맞추라고 하면 번역이 부자연스러워진다.
    보존해야 하는 것은 **집합**이다.
    """
    return frozenset(SLOT_RE.findall(text))


def slot_mismatches(entries: dict[str, str]) -> list[tuple[str, str, str]]:
    """원문과 번역의 슬롯 집합이 어긋난 항목들 — `(원문, 빠진 것, 남는 것)`.

    ★ **이것이 이 기능의 유일한 안전장치다** (`schema.md` 2절).
    번역이 `{id}` 같은 자리표시자를 하나라도 빠뜨리면 렌더가 어긋나
    **규칙 id 가 출력에서 통째로 사라진다** — 실제로 겪은 사고다
    (MODULES.md R1-2/R1-3, 11건). 정적으로 잡을 수 있는 유일한 자리가 여기다.
    """
    bad: list[tuple[str, str, str]] = []
    for source, translated in entries.items():
        want = slots_of(source)
        got = slots_of(translated)
        if want != got:
            bad.append((source, _join(want - got), _join(got - want)))
    return bad


def _join(names: Iterable[str]) -> str:
    return ", ".join(sorted(names))
