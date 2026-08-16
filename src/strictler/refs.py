"""참조 문법과 경로 규칙 — `${env.X}` / `${config.X}` / `${state.X}` / `${ref.<id>}`.

`schema.md` 2·3절이 근거다.

**네임스페이스를 강제한다.** 같은 자리(`script`)에 환경변수와 config 가 둘 다 올 수
있으므로 구분이 필요하다. 네임스페이스가 없으면 `${BUTTONSCRIPT}` 를 봤을 때
"미정의 환경변수"인지 "config 오타"인지 구분 못 해 에러가 뭉개진다.
**그 에러를 읽는 주체가 AI 이므로 정밀해야 한다.**

**경로는 무조건 절대경로다:**

    `~` 전개  →  환경변수 전개  →  결과가 절대 경로 스타일이 아니면  →  무조건 에러

상대경로 금지로 cwd 의존성이 사라진다. 이식성은 환경변수가 담당한다 —
머신·CI 마다 값만 다르게 두면 Spec 은 그대로 커밋된다.
환경변수 값 자체가 상대경로여도 잡힌다 (`PROJECT_ROOT=./foo` → `STR-PATH-003`).

**여기서 나는 것은 전부 `error` 다.** 경로 규칙 위반도 미정의 환경변수도 위반이 아니라
**도구가 못 돈 것**이므로 `StrictlerError` 로 던진다 (`schema.md` 9절).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from strictler.errors import Finding, StrictlerError
from strictler.model import ID_PREFIXES, EntryKind

__all__ = [
    "NAMESPACES",
    "PLACEHOLDER_RE",
    "Placeholder",
    "collect_placeholders",
    "is_ref",
    "parse_ref",
    "expand_env",
    "expand_path",
    "expand_config",
    "expand_state",
]


NAMESPACES: frozenset[str] = frozenset({"env", "config", "state", "ref"})
"""허용되는 네임스페이스 넷. 이 밖의 것을 쓰면 오류다."""

PLACEHOLDER_RE: str = r"\$\{(?P<ns>[a-z]+)\.(?P<name>[^}]+)\}"
"""`${<ns>.<name>}` 를 잡는 정규식 소스."""


_PLACEHOLDER_C = re.compile(PLACEHOLDER_RE)
"""`PLACEHOLDER_RE` 컴파일본."""

_BRACE_C = re.compile(r"\$\{(?P<body>[^{}]*)\}")
"""`${...}` **전부**를 잡는다. 네임스페이스가 없는 것까지 걸러내야 하므로
`PLACEHOLDER_RE` 보다 넓게 훑고 나서 대조한다."""

_ENGINE_STATE_FIELDS: frozenset[str] = frozenset({"__startedAt"})
"""`__` 접두를 쓸 수 있는 것은 엔진 제공 필드뿐이다 (`schema.md` 8절).
`__startedAt` 은 epoch 밀리초 정수."""

_KIND_LABEL: dict[EntryKind, str] = {
    "script": "스크립트(`sc_`)",
    "node": "노드(`nd_`)",
    "pipeline": "파이프라인(`pl_`)",
    "spec": "Spec(`sp_`)",
}


def _fail(message: str, rule_id: str = "") -> NoReturn:
    """오류 하나로 `StrictlerError` 를 던진다.

    **위반이 아니라 오류다.** 경로 규칙 위반·미정의 환경변수는 lint 결과가 아니라
    도구가 못 돈 것이므로 `Finding(status="error")` 로 싣는다.
    """
    raise StrictlerError(
        message,
        [Finding(status="error", rule_id=rule_id, message=message)],
    )


class Placeholder:
    """문자열 안에서 발견된 참조 하나.

    필드: `ns`(네임스페이스), `name`(이름), `raw`(`${env.HOME}` 원문),
    `start`/`end`(원본 문자열에서의 위치).
    """

    __slots__ = ("ns", "name", "raw", "start", "end")

    def __init__(self, ns: str, name: str, raw: str, start: int, end: int) -> None:
        self.ns = ns
        self.name = name
        self.raw = raw
        self.start = start
        self.end = end

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Placeholder):
            return NotImplemented
        return (
            self.ns == other.ns
            and self.name == other.name
            and self.raw == other.raw
            and self.start == other.start
            and self.end == other.end
        )

    def __hash__(self) -> int:
        return hash((self.ns, self.name, self.raw, self.start, self.end))

    def __repr__(self) -> str:
        return (
            f"Placeholder(ns={self.ns!r}, name={self.name!r}, raw={self.raw!r}, "
            f"start={self.start!r}, end={self.end!r})"
        )


def collect_placeholders(value: str) -> list[Placeholder]:
    """문자열에서 모든 `${ns.name}` 참조를 순서대로 뽑는다.

    네임스페이스가 `NAMESPACES` 밖이면 그 자리에서 오류를 낸다.
    """
    found: list[Placeholder] = []
    for m in _BRACE_C.finditer(value):
        raw = m.group(0)
        parsed = _PLACEHOLDER_C.fullmatch(raw)
        if parsed is None:
            _fail_malformed(raw, m.group("body"))
        ns = parsed.group("ns")
        name = parsed.group("name")
        if ns not in NAMESPACES:
            _fail_unknown_namespace(raw, ns)
        found.append(Placeholder(ns, name, raw, m.start(), m.end()))
    return found


def _fail_malformed(raw: str, body: str) -> NoReturn:
    """`${...}` 인데 `${ns.name}` 형태가 아닌 것들을 종류별로 갈라 알려준다."""
    ns, sep, name = body.partition(".")
    if not sep:
        _fail(
            f"참조에 네임스페이스가 없습니다: {raw}\n"
            f"쓸 수 있는 것은 ${{env.X}} / ${{config.X}} / ${{state.X}} / ${{ref.<id>}} 넷뿐입니다. "
            f"네임스페이스가 없으면 미정의 환경변수인지 config 오타인지 구분할 수 없습니다."
        )
    if ns not in NAMESPACES:
        _fail_unknown_namespace(raw, ns)
    _fail(
        f"참조의 이름이 비어 있습니다: {raw}\n"
        f"`${{{ns}.<이름>}}` 형태로 이름을 적으세요."
    )


def _fail_unknown_namespace(raw: str, ns: str) -> NoReturn:
    allowed = ", ".join(sorted(NAMESPACES))
    _fail(
        f"모르는 네임스페이스입니다: {raw} (네임스페이스: {ns!r})\n"
        f"쓸 수 있는 네임스페이스는 {allowed} 넷뿐입니다."
    )


def is_ref(value: str) -> bool:
    """값 전체가 `${ref.<id>}` 하나인지."""
    if not isinstance(value, str):
        return False
    parsed = _PLACEHOLDER_C.fullmatch(value)
    return parsed is not None and parsed.group("ns") == "ref"


def parse_ref(value: str, expected: EntryKind | None = None) -> tuple[EntryKind, str]:
    """`${ref.nd_e5f6a7b8}` → `("node", "nd_e5f6a7b8")`.

    **종류는 id 접두가 말해준다** — 그래서 `${ref.pl_...}` 를 노드 자리에 쓰면
    로드 시점에 잡힌다 (`STR-REG-003`). 접두를 모르면 오류.

    `expected` 를 주면 그 자리가 요구하는 종류와 대조까지 한다. 계약 시그니처는
    `parse_ref(value)` 이고 `expected` 는 선택 인자이므로 호출부는 그대로 써도 된다.
    """
    if not is_ref(value):
        _fail(
            f"`${{ref.<id>}}` 형태가 아닙니다: {value!r}\n"
            f"참조는 값 전체가 참조 하나여야 합니다 (예: ${{ref.nd_e5f6a7b8}})."
        )
    entry_id = value[len("${ref.") : -1]
    kind: EntryKind | None = next(
        (k for prefix, k in ID_PREFIXES.items() if entry_id.startswith(prefix)), None
    )
    if kind is None:
        known = " ".join(f"`{p}`={_KIND_LABEL[k]}" for p, k in ID_PREFIXES.items())
        _fail(
            f"모르는 id 접두입니다: {entry_id}\n종류는 id 접두가 말해줍니다 — {known}",
            rule_id="STR-REG-003",
        )
    if expected is not None and kind != expected:
        _fail(
            f"이 자리에는 {_KIND_LABEL[expected]} 가 와야 합니다. "
            f"준 것: {_KIND_LABEL[kind]} ({entry_id})\n"
            f"(접두 `sc_`=스크립트 `nd_`=노드 `pl_`=파이프라인 `sp_`=Spec)",
            rule_id="STR-REG-003",
        )
    return kind, entry_id


def expand_env(value: str, env: Mapping[str, str]) -> str:
    """`${env.X}` 만 전개한다. 미정의 환경변수는 `STR-PATH-002`."""
    return _substitute(value, "env", lambda name: _env_lookup(name, env))


def _env_lookup(name: str, env: Mapping[str, str]) -> str:
    if name not in env:
        _fail(
            f"정의되지 않은 환경변수입니다: ${{env.{name}}}\n"
            f"`${{env.{name}}}` 가 가리키는 환경변수를 실행 환경에 정의하세요. "
            f"머신·CI 마다 값이 달라도 되도록 경로를 환경변수로 뺀 것입니다.",
            rule_id="STR-PATH-002",
        )
    return env[name]


def expand_path(value: str, env: Mapping[str, str]) -> Path:
    """경로 규칙 전체를 적용해 절대경로를 만든다.

    `~` 전개(`os.path.expanduser` 가 `~`·`~user` 처리) → `${env.X}` 전개 →
    절대경로 검증. 어기면 `STR-PATH-001` / `-002` / `-003`.

    `~` 를 허용하는 이유: 상대경로가 아니라 cwd 와 무관하게 홈으로 결정되는
    규약이므로 전개하면 절대경로다. `${env.HOME}` 의 설탕 문법.
    """
    if not value:
        _fail(
            "경로가 비어 있습니다.\n"
            "모든 경로는 절대경로여야 합니다. `~` 또는 `${env.X}` 를 쓰세요.",
            rule_id="STR-PATH-001",
        )

    # ① `~` 전개 — `~` 와 `~user` 를 `os.path.expanduser` 가 처리한다.
    tilde = os.path.expanduser(value)

    # ② 환경변수 전개 — 값 자체가 상대경로면 그 자리에서 잡는다.
    def lookup(name: str, *, at_start: bool) -> str:
        resolved = _env_lookup(name, env)
        if _is_relative_marker(resolved) or (at_start and not os.path.isabs(resolved)):
            _fail(
                f"환경변수 값 자체가 상대경로입니다: ${{env.{name}}} = {resolved!r}\n"
                f"환경변수 값이 절대경로여야 합니다. `PROJECT_ROOT=./foo` 같은 값은 "
                f"cwd 의존을 되살립니다.",
                rule_id="STR-PATH-003",
            )
        return resolved

    expanded = _substitute(
        tilde, "env", lambda name, at_start=False: lookup(name, at_start=at_start),
        pass_position=True,
    )

    # ③ 절대경로 검증 — 아니면 무조건 에러.
    if not os.path.isabs(expanded):
        _fail(
            f"전개 후에도 절대경로가 아닙니다: {expanded!r} (원본: {value!r})\n"
            f"모든 경로는 절대경로여야 합니다. `~` 또는 `${{env.X}}` 를 쓰세요. "
            f"cwd 에 의존하는 경로는 쓸 수 없습니다.",
            rule_id="STR-PATH-001",
        )
    return Path(expanded)


def _is_relative_marker(value: str) -> bool:
    """`.` / `..` / `./…` / `../…` — 위치를 불문하고 상대경로임이 명백한 값."""
    return value in (".", "..") or value.startswith(("./", "../"))


def expand_config(
    value: Any,
    config: Mapping[str, Any],
    target: str = "",
) -> Any:
    """`${config.X}` 를 전개한다. 문자열 전체가 참조 하나면 **타입을 보존해** 값 자체를 준다.

    `target` 이 주어지면(비교 파이프라인) **`targets.<target>` 에서 먼저 찾고,
    없으면 공통에서** 찾는다 (`schema.md` 12절). 둘 다 없으면 `STR-CMP-004`.
    """
    return _expand(value, "config", lambda name: _config_lookup(name, config, target))


def _config_lookup(name: str, config: Mapping[str, Any], target: str) -> Any:
    if target:
        targets = config.get("targets")
        if isinstance(targets, Mapping):
            scope = targets.get(target)
            if isinstance(scope, Mapping) and name in scope:
                return scope[name]
    if name in config:
        return config[name]
    if target:
        _fail(
            f"`${{config.{name}}}` 를 찾을 수 없습니다 (target: {target}).\n"
            f"`${{config.X}}` 는 `targets.<현재target>` 에서 먼저 찾고 없으면 공통에서 "
            f"찾습니다. 둘 다 없습니다: {name}",
            rule_id="STR-CMP-004",
        )
    _fail(
        f"`${{config.{name}}}` 를 찾을 수 없습니다.\n"
        f"파이프라인이 요구하는 config 를 Spec 의 `plan` 항목에서 채우세요. 누락: {name}",
        rule_id="STR-CONFIG-001",
    )


def expand_state(value: Any, state: Mapping[str, Any]) -> Any:
    """`${state.X}` 를 전개한다.

    `__` 접두는 엔진 제공 필드 예약 (`${state.__startedAt}`, epoch 밀리초 정수).
    사용자 상태 이름에 `__` 접두를 쓰면 `STR-STATE-001`.
    """
    return _expand(value, "state", lambda name: _state_lookup(name, state))


def _state_lookup(name: str, state: Mapping[str, Any]) -> Any:
    if name.startswith("__") and name not in _ENGINE_STATE_FIELDS:
        known = ", ".join(sorted(_ENGINE_STATE_FIELDS))
        _fail(
            f"`__` 접두는 엔진 제공 필드 전용입니다: ${{state.{name}}}\n"
            f"엔진이 주는 것은 {known} 뿐입니다. 다른 이름을 쓰세요.",
            rule_id="STR-STATE-001",
        )
    if name not in state:
        _fail(
            f"참조한 상태가 없습니다: ${{state.{name}}}\n"
            f"노드의 `Args.state` 필드마다 파이프라인 상태 이름을 매핑해야 합니다. "
            f"누락: {name}",
            rule_id="STR-STATE-002",
        )
    return state[name]


# ── 전개 엔진 ────────────────────────────────────────────────────────────────


def _substitute(value: str, ns: str, lookup: Any, *, pass_position: bool = False) -> str:
    """`value` 안의 `${<ns>.X}` 를 전부 치환한다. 다른 네임스페이스는 그대로 둔다.

    치환 결과는 문자열로 이어붙는다 — 타입 보존은 `_expand` 쪽 일이다.
    """
    pieces: list[str] = []
    cursor = 0
    for ph in collect_placeholders(value):
        if ph.ns != ns:
            continue
        resolved = (
            lookup(ph.name, at_start=(ph.start == 0)) if pass_position else lookup(ph.name)
        )
        pieces.append(value[cursor : ph.start])
        pieces.append(str(resolved))
        cursor = ph.end
    pieces.append(value[cursor:])
    return "".join(pieces)


def _expand(value: Any, ns: str, lookup: Any) -> Any:
    """`${<ns>.X}` 를 전개하되 **문자열 전체가 참조 하나면 타입을 보존한다.**

    `"${config.expectedFields}"` → `2` (문자열 `"2"` 가 아니라).
    리스트·매핑은 원소마다 재귀한다 — `params` 가 중첩 구조일 수 있다.
    """
    if isinstance(value, str):
        found = collect_placeholders(value)
        if len(found) == 1 and found[0].ns == ns and found[0].raw == value:
            return lookup(found[0].name)
        return _substitute(value, ns, lookup)
    if isinstance(value, list):
        return [_expand(item, ns, lookup) for item in value]
    if isinstance(value, Mapping):
        return {key: _expand(item, ns, lookup) for key, item in value.items()}
    return value
