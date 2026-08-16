"""리포터 — 값 검증 리포트와 비교 리포트.

`schema.md` 11·12절이 근거다.

**flat 리스트 + 경로 필드.** Spec→plan→pipeline→node 중첩으로 쌓지 않는다.
**요약 헤더에 4상태 카운트를 낸다.** 리포트 누적 단위는 **노드별**이다.

값 검증은 노드별 판정이고 비교는 노드별 대상 간 대조라 필드가 안 겹친다. **섞지 않는다.**

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel

from strictler.errors import Finding

__all__ = [
    "Summary",
    "Report",
    "CompareEntry",
    "CompareReport",
    "build_report",
    "render_json",
    "render_text",
    "build_compare_report",
    "write_compare_report",
]


class Summary(BaseModel):
    """요약 헤더 — 4상태 카운트 (`schema.md` 9·11절)."""

    model_config = ConfigDict(extra="forbid")

    # `pass` 는 예약어라 필드명을 그대로 쓸 수 없다. 직렬화 시 `pass` 로 나간다.
    passed: int = Field(default=0, serialization_alias="pass")
    violation: int = 0
    not_run: int = 0
    error: int = 0


class Report(BaseModel):
    """값 검증 리포트 전체."""

    model_config = ConfigDict(extra="forbid")

    summary: Summary
    results: list[Finding] = Field(default_factory=list)


class CompareEntry(BaseModel):
    """비교 노드 하나의 결과 (`schema.md` 12절).

    **위반 판정은 목록 전부가 같은 값을 뱉느냐**이지 짝지어 비교하는 것이 아니다.
    하나만 어긋나도 `same: false`.
    """

    model_config = ConfigDict(extra="forbid")

    same: bool
    values: dict[str, Any]
    """`{target 이름: 그 target 의 출력}`."""


class CompareReport(RootModel[dict[str, CompareEntry]]):
    """`{노드 id: CompareEntry}`. 값 검증 리포트와 섞지 않는다."""

    root: dict[str, CompareEntry] = Field(default_factory=dict)


def build_report(findings: list[Finding]) -> Report:
    """`Finding` 목록에서 요약 카운트를 세어 리포트를 만든다."""
    raise NotImplementedError("Step 1에서 구현")


def render_json(report: Report) -> str:
    """`schema.md` 11절 형식 그대로 JSON 문자열을 만든다.

    `model_dump(by_alias=True)` 로 `rule_id`→`rule`, `passed`→`pass` 변환이 걸린다.
    """
    raise NotImplementedError("Step 1에서 구현")


def render_text(report: Report) -> str:
    """터미널용 사람이 읽는 출력. 4상태를 구분해 보여준다."""
    raise NotImplementedError("Step 1에서 구현")


def build_compare_report(values: dict[str, dict[str, Any]]) -> CompareReport:
    """`{노드 id: {target: 값}}` 에서 비교 리포트를 만든다.

    **엔진은 `==` 만 안다.** 허용 오차도 무시 필드도 없다 — 정규화는 비교용 데이터를
    출력하는 노드의 스크립트가 알아서 한다 (`schema.md` 12절).
    """
    raise NotImplementedError("Step 1에서 구현")


def write_compare_report(report: CompareReport, path: Path) -> None:
    """비교 리포트를 Spec `plan` 항목의 `report` 위치에 쓴다.

    **실행과 동시에 쌓는 산출물**이지 위반 후 사후 수습이 아니다 —
    "증거 캡처는 하지 않는다"(9절)와 성격이 다르다.
    """
    raise NotImplementedError("Step 1에서 구현")
