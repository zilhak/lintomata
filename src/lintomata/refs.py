"""참조 문법과 경로 규칙 — `${env.X}` / `${config.X}` / `${state.X}` / `${ref.<id>}`.

`schema.md` 2·3절이 근거다.

**네임스페이스를 강제한다.** 같은 자리(`script`)에 환경변수와 config 가 둘 다 올 수
있으므로 구분이 필요하다. 네임스페이스가 없으면 `${BUTTONSCRIPT}` 를 봤을 때
"미정의 환경변수"인지 "config 오타"인지 구분 못 해 에러가 뭉개진다.
**그 에러를 읽는 주체가 AI 이므로 정밀해야 한다.**

**경로는 무조건 절대경로다:**

    `~` 전개  →  환경변수 전개  →  `~` 재전개  →  결과가 절대 경로 스타일이 아니면  →  무조건 에러

상대경로 금지로 cwd 의존성이 사라진다. 이식성은 환경변수가 담당한다 —
머신·CI 마다 값만 다르게 두면 Spec 은 그대로 커밋된다.
환경변수 값 자체가 상대경로여도 잡힌다 (`PROJECT_ROOT=./foo` → `LNT-PATH-003`).

**★ 환경변수 값 안의 `~` 도 전개한다.** `PROJECT_ROOT=~/proj` 는 흔한 설정이고,
`~` 를 허용한 논리("cwd 와 무관하게 홈으로 결정되므로 전개하면 절대경로다")가
env 값 안의 `~` 에도 그대로 적용된다. 그래서 전개가 **3단계**다 —
빠뜨리면 앞자리(`${env.R}/x`)는 "상대경로입니다" 오진단이 되고,
중간자리(`/srv/${env.S}/x`)는 리터럴 `~` 가 박힌 `/srv/~/proj/x` 가 **조용히 통과**한다.

**전개 후 `${` 가 남아 있으면 오류다.** 경로 해석 시점엔 모든 참조가 풀려 있어야 한다.
리터럴 경로 조각으로 통과시키면 나중에 "파일 없음"으로 원인이 뭉개진다.
**둘을 규칙으로 가른다** (MODULES.md R2-6): 문법이 깨진 것(`${X}` / 닫히지 않은 `${`)은
`LNT-REF-006`, **문법은 정상인데 안 풀린 것**(`${config.y}`)은 `LNT-REF-007` 이다.
`-006` 의 가이드("네임스페이스를 반드시 붙입니다")를 이미 네임스페이스가 붙은 참조에
주면 AI 가 엉뚱한 곳을 고친다 — **규칙을 나누는 기준은 증상이 아니라 고치는 방법이다.**

**여기서 나는 것은 전부 `error` 다.** 경로 규칙 위반도 미정의 환경변수도 위반이 아니라
**도구가 못 돈 것**이므로 `LintomataError` 로 던진다 (`schema.md` 9절).

**규칙 문구는 `rules` 가 만든다** (MODULES.md R2-7). 예전엔 `rules.md` 의 guide 를
손으로 복제했는데, 그러면 문서와 코드가 갈라진다. `rules` 는 `errors` 에만 의존하는
최하층이라 여기서 써도 순환이 생기지 않는다. 이 모듈이 직접 쓰는 문자열은
**규칙 문구가 아니라 구체값**(어느 환경변수인지, 어떤 경로였는지)뿐이다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from lintomata import rules
from lintomata.errors import Finding, LintomataError
from lintomata.locale import message, translate
from lintomata.model import ENGINE_STATE_FIELDS as _ENGINE_STATE_FIELDS
from lintomata.model import ID_PREFIXES, EntryKind

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
    "expand_all",
]


NAMESPACES: frozenset[str] = frozenset({"env", "config", "state", "ref"})
"""허용되는 네임스페이스 넷. 이 밖의 것을 쓰면 오류다."""

PLACEHOLDER_RE: str = r"\$\{(?P<ns>[a-z]+)\.(?P<name>[^}]+)\}"
"""`${<ns>.<name>}` 를 잡는 정규식 소스."""


_PLACEHOLDER_C = re.compile(PLACEHOLDER_RE)
"""`PLACEHOLDER_RE` 컴파일본."""

_BRACE_C = re.compile(r"\$\{[^{}]*\}")
"""`${...}` **전부**를 잡는다. 네임스페이스가 없는 것까지 걸러내야 하므로
`PLACEHOLDER_RE` 보다 넓게 훑고 나서 `_wellformed` 로 대조한다."""

"""`_ENGINE_STATE_FIELDS` — `__` 접두를 쓸 수 있는 것은 엔진 제공 필드뿐이다
(`schema.md` 8절). `__startedAt` 은 epoch 밀리초 정수.
**정본은 `model.ENGINE_STATE_FIELDS`** — `engine/state.py`·`checks/script.py` 와 같은 것을 본다."""

_KIND_LABEL: dict[EntryKind, str] = {
    "script": "script (`sc_`)",
    "library": "library (`lb_`)",
    "node": "node (`nd_`)",
    "pipeline": "pipeline (`pl_`)",
    "spec": "Spec (`sp_`)",
}
"""**원문은 영어다** (`schema.md` 2절). 쓰는 자리에서 `translate()` 한다 —
이 dict 는 import 시점에 확정되는데 로케일은 그보다 늦게 정해진다."""


def _fail(
    rule_id: str,
    *,
    detail: str = "",
    fields: dict[str, object] | None = None,
) -> NoReturn:
    """규칙 하나로 `LintomataError` 를 던진다.

    **위반이 아니라 오류다.** 경로 규칙 위반·미정의 환경변수는 lint 결과가 아니라
    도구가 못 돈 것이므로 `Finding(status="error")` 로 싣는다.

    **규칙 문구(message + guide)는 `rules.finding()` 이 만든다** — 여기서 손으로
    복제하지 않는다 (MODULES.md R2-7). `detail` 은 규칙 테이블에 슬롯이 없는
    **구체값**만 담는다 (어느 환경변수였는지, 전개 결과가 무엇이었는지).
    """
    item = rules.finding(rule_id, status="error", fields=fields)
    text = f"{detail}\n{item.message}" if detail else item.message
    raise LintomataError(text, [item.model_copy(update={"message": text})])


def _fail_plain(text: str) -> NoReturn:
    """규칙 id 가 붙지 않는 오류.

    **규칙이 없는 자리에만 쓴다.** "참조가 아니다"(`nd_abc`) 나 "자리가 다르다"
    (`${env.HOME}` 를 `${ref....}` 자리에) 는 참조 문법이 깨진 것이 아니라서
    `LNT-REF-006` 에 해당하지 않는다 — 억지로 묶으면 가이드가 엉뚱해진다.
    """
    raise LintomataError(text, [Finding(status="error", message=text)])


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
        parsed = _wellformed(raw)
        if parsed is None:
            _fail_malformed(raw)
        found.append(Placeholder(parsed[0], parsed[1], raw, m.start(), m.end()))
    return found


def _wellformed(raw: str) -> tuple[str, str] | None:
    """`${...}` 하나가 **문법상 온전한 참조**인지 본다 → `(ns, name)` 또는 `None`.

    온전하다 = `${<허용 네임스페이스>.<빈 문자열이 아닌 이름>}`.
    `None` 이면 `LNT-REF-006`(malformed) 이고, 값이 나오면 문법은 정상이다 —
    그때부터 남은 문제는 "안 풀렸다"(`LNT-REF-007`) 거나 "자리가 다르다" 뿐이다.
    """
    parsed = _PLACEHOLDER_C.fullmatch(raw)
    if parsed is None or parsed.group("ns") not in NAMESPACES:
        return None
    return parsed.group("ns"), parsed.group("name")


def _fail_malformed(raw: str) -> NoReturn:
    """`${...}` 인데 `${ns.name}` 형태가 아닌 것 — `LNT-REF-006`.

    네임스페이스 없음 / 모름 / 이름 비었음 셋이 전부 이 규칙이다 (`rules.md`
    `LNT-REF-006` 의 "잡는 것" 열이 셋을 그대로 열거한다). 셋을 코드에서 다시
    갈라 문구를 지어내지 않는다 — 규칙 문구는 `rules` 가 갖고 있고, 여기서
    보태는 것은 `{ref}` 슬롯에 넣을 **문제의 참조 원문**뿐이다.
    """
    _fail("LNT-REF-006", fields={"ref": raw})


def _fail_unresolved(raw: str, original: str) -> NoReturn:
    """문법은 정상인데 이 자리까지 전개되지 않고 살아남은 참조 — `LNT-REF-007`.

    `LNT-REF-006` 이 아니다 (MODULES.md R2-6). `${config.y}` 는 네임스페이스가
    이미 붙어 있으므로 `-006` 의 가이드를 주면 AI 가 엉뚱한 곳을 고친다.
    고쳐야 할 것은 **전개 순서 내지 빠진 config 값**이다.
    """
    _fail(
        "LNT-REF-007",
        detail=message("Written as: {raw}", raw=repr(original)),
        fields={"ref": raw},
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
    로드 시점에 잡힌다 (`LNT-REG-003`). 접두를 모르면 오류.

    **`expected` 는 "이 자리가 요구하는 종류"다.** 파이프라인의 `source` 자리에는
    노드만, Spec 의 `plan[].source` 자리에는 파이프라인만 올 수 있다 — 그 자리를
    아는 호출부가 `expected` 로 알려주면 접두와 대조해 `LNT-REG-003`(자리와 접두
    불일치)을 낸다. `expected` 없이는 이 규칙을 낼 방법이 없다.

    `expected=None` 이면 접두 해석만 하고 자리 대조는 하지 않는다 — 자리가
    정해지지 않은 호출부(목록 조회 등)는 그대로 쓰면 된다 (MODULES.md R1-5).
    """
    if not is_ref(value):
        _fail_not_ref(value)
    entry_id = value[len("${ref.") : -1]
    kind: EntryKind | None = next(
        (k for prefix, k in ID_PREFIXES.items() if entry_id.startswith(prefix)), None
    )
    if kind is None:
        known = " / ".join(translate(_KIND_LABEL[k]) for k in ID_PREFIXES.values())
        _fail(
            "LNT-REG-003",
            fields={
                "expected": message("one of {kinds}", kinds=known),
                "given": message("{id} (unknown prefix)", id=entry_id),
            },
        )
    if expected is not None and kind != expected:
        _fail(
            "LNT-REG-003",
            fields={
                "expected": translate(_KIND_LABEL[expected]),
                "given": message(
                    "{kind} ({id})", kind=translate(_KIND_LABEL[kind]), id=entry_id
                ),
            },
        )
    return kind, entry_id


def _fail_not_ref(value: object) -> NoReturn:
    """`${ref.<id>}` 자리에 그게 아닌 것이 왔다 — **두 갈래로 갈린다.**

    1. **문법이 깨진 참조** (`${ref.}` / `${vars.x}` / `${BUTTON}`) → `LNT-REF-006`.
       `rules.md` `LNT-REF-006` 이 열거한 세 경우 그 자체다. 예전엔 `is_ref()` 가
       `False` 를 돌려주는 바람에 형태 판별 이전 단계에서 **id 없이 튕겼다** —
       같은 입력이 `collect_placeholders` 로 가면 `-006` 이 붙는데 `parse_ref` 로
       가면 id 가 사라지는 비대칭이었다.
    2. **문법은 멀쩡한데 참조가 아니거나 자리가 다른 것** (`nd_abc`, `${env.HOME}`)
       → 규칙 없음. 고칠 곳이 "참조 문법" 이 아니므로 `-006` 으로 묶지 않는다.
    """
    if isinstance(value, str):
        m = _BRACE_C.fullmatch(value)
        if m is not None and _wellformed(value) is None:
            _fail_malformed(value)
    _fail_plain(
        message(
            "Not in `${ref.<id>}` form: {value}\n"
            "A reference must be the whole value, one reference and nothing else "
            "(e.g. ${ref.nd_e5f6a7b8}).",
            value=repr(value),
        )
    )


def expand_env(value: Any, env: Mapping[str, str]) -> Any:
    """`${env.X}` 만 전개한다. 미정의 환경변수는 `LNT-PATH-002`.

    `expand_config`/`expand_state` 와 같은 전개기를 쓰므로 **리스트·매핑을 재귀**하고
    문자열 전체가 참조 하나면 타입을 보존한다. `params` 가 중첩 구조일 수 있고,
    스크립트에 넘어가는 값도 `${env.X}` 를 품을 수 있기 때문이다 (R5-1).
    """
    return _expand(value, "env", lambda name: _env_lookup(name, env))


def _env_lookup(name: str, env: Mapping[str, str]) -> str:
    if name not in env:
        _fail("LNT-PATH-002", fields={"name": name})
    return env[name]


def expand_path(value: str, env: Mapping[str, str]) -> Path:
    """경로 규칙 전체를 적용해 절대경로를 만든다.

    **3단계다** (`schema.md` 3절):

        `~` 전개  →  `${env.X}` 전개  →  `~` 재전개  →  절대경로 검증

    어기면 `LNT-PATH-001`(전개 후에도 상대경로) / `-002`(env 미정의) /
    `-003`(env 값이 상대경로). 잔여 참조는 **문법이 깨졌으면 `LNT-REF-006`,
    문법은 정상인데 안 풀렸으면 `LNT-REF-007`** 이다 (R2-6).

    `~` 를 허용하는 이유: 상대경로가 아니라 cwd 와 무관하게 홈으로 결정되는
    규약이므로 전개하면 절대경로다. `${env.HOME}` 의 설탕 문법.
    **같은 논리가 env 값 안의 `~` 에도 적용되므로 재전개가 필요하다** —
    `PROJECT_ROOT=~/proj` 는 흔한 설정이다.

    **`LNT-PATH-004`(`path: true` 인 config 값이 경로 규칙을 어긴다)는 여기서 내지
    않는다.** 어떤 config 가 `path: true` 인지는 파이프라인 선언을 읽어야 알 수 있고,
    그건 `checks/pipeline.py`(Step 2-b) 의 일이다 (MODULES.md R1-6).
    `refs` 는 그 검사에 쓸 기제(`expand_path`)만 제공한다.
    """
    if not value:
        _fail(
            "LNT-PATH-001",
            detail=message("The path is empty."),
            fields={"path": repr(value)},
        )

    # ① `~` 전개 — `~` 와 `~user` 를 `os.path.expanduser` 가 처리한다.
    tilde = os.path.expanduser(value)

    # ② 환경변수 전개 — 값 자체가 상대경로면 그 자리에서 잡는다.
    #    ③ `~` 재전개를 여기서 값마다 한다. 값 안의 `~` 는 그 값이 놓이는 자리가
    #    앞자리든 중간자리든 똑같이 홈으로 결정되므로, 치환 전에 풀어야 앞자리는
    #    오진단(LNT-PATH-003)이 안 나고 중간자리는 리터럴 `~` 가 안 박힌다.
    def lookup(name: str, *, at_start: bool) -> str:
        raw = _env_lookup(name, env)
        resolved = os.path.expanduser(raw)
        if _is_relative_marker(resolved) or (at_start and not os.path.isabs(resolved)):
            _fail("LNT-PATH-003", fields={"name": name, "value": repr(raw)})
        return resolved

    expanded = _substitute(
        tilde, "env", lambda name, at_start=False: lookup(name, at_start=at_start),
        pass_position=True,
    )

    # ③ `~` 재전개 (고정점) — 치환 결과 맨 앞에 `~` 가 새로 생겼을 수 있다.
    expanded = os.path.expanduser(expanded)

    # ④ 잔여 `${` 는 오류 — 경로 해석 시점엔 모든 참조가 풀려 있어야 한다.
    _fail_if_unresolved(expanded, value)

    # ⑤ 절대경로 검증 — 아니면 무조건 에러.
    if not os.path.isabs(expanded):
        _fail(
            "LNT-PATH-001",
            detail=message("Written as: {raw}", raw=repr(value)),
            fields={"path": repr(expanded)},
        )
    return Path(expanded)


def _fail_if_unresolved(expanded: str, original: str) -> None:
    """전개가 끝난 경로에 `${` 가 남았으면 오류다. **둘로 갈린다** (R2-6).

    | 남은 것 | 규칙 | 고칠 곳 |
    |---|---|---|
    | `${env.HOME/x` — 닫히지 않음 | `LNT-REF-006` | 참조 문법 |
    | `${X}` / `${vars.y}` — env 값이 끌고 들어온 깨진 참조 | `LNT-REF-006` | 참조 문법 |
    | `${config.y}` — 문법 정상, 안 풀림 | **`LNT-REF-007`** | 전개 순서·빠진 config |

    닫히지 않은 `${` 는 `${...}` 로 인식조차 되지 않아 `collect_placeholders` 를
    그냥 통과하므로 여기서 따로 잡는다.
    """
    at = expanded.find("${")
    if at < 0:
        return
    rest = expanded[at:]
    close = rest.find("}")
    if close < 0:
        _fail(
            "LNT-REF-006",
            detail=message("Never closed (written as: {raw})", raw=repr(original)),
            fields={"ref": rest},
        )
    raw = rest[: close + 1]
    if _wellformed(raw) is None:
        _fail(
            "LNT-REF-006",
            detail=message("Written as: {raw}", raw=repr(original)),
            fields={"ref": raw},
        )
    _fail_unresolved(raw, original)


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
    없으면 공통에서** 찾는다 (`schema.md` 12절). 둘 다 없으면 `LNT-CMP-004`.

    **`default` 주입은 여기 책임이 아니다.** 파이프라인이 선언한 config 의
    `default` 를 채우는 것은 `checks/pipeline.py`(Step 2-b) 이고, `expand_config`
    가 받는 `config` 는 **이미 default 가 채워진 것**이다 (MODULES.md R1-6).
    → 그래서 여기서 못 찾은 `${config.X}` 는 진짜 `required` 누락이고,
    `LNT-CONFIG-001`(required-missing) 재사용이 정당하다.

    ⚠ **다른 네임스페이스는 그대로 남긴다.** `${env.X}` 는 뒤이어 `expand_path`
    가, `${state.X}` 는 `expand_state` 가 푼다 — 합성 순서 때문에 여기서 잔여
    참조를 오류로 잡으면 안 된다. 잔여 검사는 최종 관문인 `expand_path` 가 한다.
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
            "LNT-CMP-004",
            detail=message("Current target: {target}", target=target),
            fields={"name": name},
        )
    _fail("LNT-CONFIG-001", fields={"names": name})


def expand_state(value: Any, state: Mapping[str, Any]) -> Any:
    """`${state.X}` 를 전개한다.

    `__` 접두는 엔진 제공 필드 예약 (`${state.__startedAt}`, epoch 밀리초 정수).
    사용자 상태 이름에 `__` 접두를 쓰면 `LNT-STATE-001`.

    ⚠ `expand_config` 와 마찬가지로 **다른 네임스페이스는 그대로 남긴다** (합성 순서).
    """
    return _expand(value, "state", lambda name: _state_lookup(name, state))


def _state_lookup(name: str, state: Mapping[str, Any]) -> Any:
    if name.startswith("__") and name not in _ENGINE_STATE_FIELDS:
        known = ", ".join(sorted(_ENGINE_STATE_FIELDS))
        _fail(
            "LNT-STATE-001",
            detail=message(
                "The engine only provides {names}.", names=known
            ),
            fields={"name": name},
        )
    if name not in state:
        _fail("LNT-STATE-002", fields={"names": name})
    return state[name]


def expand_all(
    value: Any,
    *,
    config: Mapping[str, Any],
    state: Mapping[str, Any],
    env: Mapping[str, str],
    target: str = "",
) -> Any:
    """**스크립트에 넘기는 값**을 끝까지 전개한다 — `config` → `state` → `env` (R5-1).

    `params` 를 스크립트에 넘기는 자리가 `expand_env` 를 안 불러 `${env.X}` 가
    **원문 그대로 스크립트에 도달했다.** `checks/pipeline.py` 는 `expand_path` 로
    **전개해서 검증**하므로 검증과 전달이 서로 다른 문자열을 봤고, 증상이
    `FileNotFoundError` 라 *"대상 파일이 없다"* 로 오독됐다.
    `schema.md` 3절이 *"이식성은 환경변수가 담당한다"* 를 설계 전제로 두었는데
    그 전제가 이 자리에서만 깨진 것이다.

    **순서가 계약이다.** `config`·`state` 값이 `${env.Y}` 를 품을 수 있으므로
    env 가 마지막이다. 반대로 하면 config 가 끌고 들어온 `${env.Y}` 가 그대로 남는다.

    **전개 후에도 `${` 가 남으면 오류다** — `expand_path` 와 같은 논리다.
    리터럴로 통과시키면 나중에 엉뚱한 오류로 원인이 뭉개진다.

    `target` 은 비교 파이프라인의 target 이름이다 (`expand_config` 와 같은 뜻).
    """
    expanded = expand_config(value, config, target)
    expanded = expand_state(expanded, state)
    expanded = expand_env(expanded, env)
    _fail_if_unresolved_deep(expanded, value)
    return expanded


def _fail_if_unresolved_deep(expanded: Any, original: Any) -> None:
    """전개가 끝난 값에 `${` 가 남았는지 **재귀로** 훑는다.

    문자열 하나에 대한 판정은 `_fail_if_unresolved` 와 같다 — 문법이 깨졌으면
    `LNT-REF-006`, 문법은 정상인데 안 풀렸으면 `LNT-REF-007`.
    """
    if isinstance(expanded, str):
        _fail_if_unresolved(expanded, original if isinstance(original, str) else expanded)
        return
    if isinstance(expanded, list):
        for item in expanded:
            _fail_if_unresolved_deep(item, item)
        return
    if isinstance(expanded, Mapping):
        for item in expanded.values():
            _fail_if_unresolved_deep(item, item)


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
