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

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from strictler.model import EntryKind

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


class Placeholder:
    """문자열 안에서 발견된 참조 하나.

    필드: `ns`(네임스페이스), `name`(이름), `raw`(`${env.HOME}` 원문),
    `start`/`end`(원본 문자열에서의 위치).
    """

    def __init__(self, ns: str, name: str, raw: str, start: int, end: int) -> None:
        raise NotImplementedError("Step 1에서 구현")


def collect_placeholders(value: str) -> list[Placeholder]:
    """문자열에서 모든 `${ns.name}` 참조를 순서대로 뽑는다.

    네임스페이스가 `NAMESPACES` 밖이면 그 자리에서 오류를 낸다.
    """
    raise NotImplementedError("Step 1에서 구현")


def is_ref(value: str) -> bool:
    """값 전체가 `${ref.<id>}` 하나인지."""
    raise NotImplementedError("Step 1에서 구현")


def parse_ref(value: str) -> tuple[EntryKind, str]:
    """`${ref.nd_e5f6a7b8}` → `("node", "nd_e5f6a7b8")`.

    **종류는 id 접두가 말해준다** — 그래서 `${ref.pl_...}` 를 노드 자리에 쓰면
    로드 시점에 잡힌다 (`STR-REG-003`). 접두를 모르면 오류.
    """
    raise NotImplementedError("Step 1에서 구현")


def expand_env(value: str, env: Mapping[str, str]) -> str:
    """`${env.X}` 만 전개한다. 미정의 환경변수는 `STR-PATH-002`."""
    raise NotImplementedError("Step 1에서 구현")


def expand_path(value: str, env: Mapping[str, str]) -> Path:
    """경로 규칙 전체를 적용해 절대경로를 만든다.

    `~` 전개(`os.path.expanduser` 가 `~`·`~user` 처리) → `${env.X}` 전개 →
    절대경로 검증. 어기면 `STR-PATH-001` / `-002` / `-003`.

    `~` 를 허용하는 이유: 상대경로가 아니라 cwd 와 무관하게 홈으로 결정되는
    규약이므로 전개하면 절대경로다. `${env.HOME}` 의 설탕 문법.
    """
    raise NotImplementedError("Step 1에서 구현")


def expand_config(
    value: Any,
    config: Mapping[str, Any],
    target: str = "",
) -> Any:
    """`${config.X}` 를 전개한다. 문자열 전체가 참조 하나면 **타입을 보존해** 값 자체를 준다.

    `target` 이 주어지면(비교 파이프라인) **`targets.<target>` 에서 먼저 찾고,
    없으면 공통에서** 찾는다 (`schema.md` 12절). 둘 다 없으면 `STR-CMP-004`.
    """
    raise NotImplementedError("Step 1에서 구현")


def expand_state(value: Any, state: Mapping[str, Any]) -> Any:
    """`${state.X}` 를 전개한다.

    `__` 접두는 엔진 제공 필드 예약 (`${state.__startedAt}`, epoch 밀리초 정수).
    사용자 상태 이름에 `__` 접두를 쓰면 `STR-STATE-001`.
    """
    raise NotImplementedError("Step 1에서 구현")
