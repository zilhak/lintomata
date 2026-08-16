"""검사 규칙 테이블 — `STR-<CATEGORY>-<NNN>`.

`rules.md` 전체가 근거다. 초기 규칙 54개 (PATH 4 / REF 5 / GRAPH 2 / TYPE 5 /
CONTRACT 6 / STATE 7 / BAN 4 / TOOL 2 / CONFIG 3 / CMP 4 / TEST 7 / REG 5).
**늘어나는 것이 전제다** — 카테고리별 독립 번호 공간, 번호 재사용 금지,
폐기해도 `status: deprecated` 로 남긴다.

**`guide` 는 별도 필드로 리포트에 나가지 않는다.** 에러 메시지 뒤에 이어붙는다
(`schema.md` 11절). 정적 검사가 못 잡는 것을 메우는 자리이므로,
그 문구가 곧 AI 자기 수정 루프의 성능이다.

⚠ stub. Step 1 에서 `RULES` 를 54개로 채우고 함수 본체를 구현한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from strictler.errors import Finding, NotRunCause, Status

__all__ = [
    "RuleWhen",
    "RuleStatus",
    "Rule",
    "RULES",
    "get_rule",
    "rules_for",
    "render",
    "finding",
]


RuleWhen = Literal["node-register", "pipeline-register", "run", "test", "list"]
"""규칙이 도는 시점. `rules.md` 2절의 `when` 열 —
N=노드 등록, P=파이프라인 등록, R=실행, T=단위테스트, 그리고 목록 표시 전용(REG-004/005)."""

RuleStatus = Literal["active", "deprecated"]


class Rule(BaseModel):
    """규칙 엔트리 하나 (`rules.md` 1절)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    """`STR-CONTRACT-001` 형태. 길지만 사람이 타이핑할 일이 없고, 읽는 주체가
    AI 이므로 자기 설명적인 쪽이 낫다."""

    name: str
    """사람이 읽는 이름 (`args-dataclass-missing`)."""

    since: str
    status: RuleStatus
    when: tuple[RuleWhen, ...]
    """한 규칙이 여러 시점에 돌 수 있다 (예: `STR-PATH-001` 은 N P R)."""

    message: str
    """`{file}` 같은 `str.format` 자리표시자를 포함한다."""

    guide: str
    """자연어 수정 가이드. 메시지 뒤에 이어붙어 나간다."""


RULES: dict[str, Rule] = {}
"""규칙 id → 규칙. Step 1 에서 `rules.md` 2절의 54개로 채운다."""


def get_rule(rule_id: str) -> Rule:
    """규칙 하나를 꺼낸다. 없으면 `StrictlerError` — 도구 자신의 버그이므로 오류다."""
    raise NotImplementedError("Step 1에서 구현")


def rules_for(when: RuleWhen) -> list[Rule]:
    """그 시점에 도는 `active` 규칙들을 준다."""
    raise NotImplementedError("Step 1에서 구현")


def render(rule_id: str, **fields: object) -> str:
    """규칙의 `message` 를 `fields` 로 채우고 **뒤에 `guide` 를 이어붙여** 준다.

    이것이 `Finding.message` 에 들어가는 최종 문자열이다 (`schema.md` 11절).
    """
    raise NotImplementedError("Step 1에서 구현")


def finding(
    rule_id: str,
    *,
    status: Status = "error",
    path: str = "",
    node: str = "",
    cause: NotRunCause | None = None,
    **fields: object,
) -> Finding:
    """규칙 id 로 `Finding` 하나를 만든다. `render()` 를 태워 메시지를 채운다.

    검사기들이 가장 많이 쓰는 진입점이다.
    """
    raise NotImplementedError("Step 1에서 구현")
