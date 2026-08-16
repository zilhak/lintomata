"""리포터 — 값 검증 리포트와 비교 리포트.

`schema.md` 11·12절이 근거다.

**flat 리스트 + 경로 필드.** Spec→plan→pipeline→node 중첩으로 쌓지 않는다.
**요약 헤더에 4상태 카운트를 낸다.** 리포트 누적 단위는 **노드별**이다.

값 검증은 노드별 판정이고 비교는 노드별 대상 간 대조라 필드가 안 겹친다. **섞지 않는다.**
"""

from __future__ import annotations

import json
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
    summary = Summary()
    for f in findings:
        if f.status == "pass":
            summary.passed += 1
        elif f.status == "violation":
            summary.violation += 1
        elif f.status == "not_run":
            summary.not_run += 1
        else:
            summary.error += 1
    return Report(summary=summary, results=list(findings))


def _prune(entry: dict[str, Any]) -> dict[str, Any]:
    """빈 문자열 필드를 덜어낸다.

    `Finding` 의 `path`/`node`/`rule_id`/`message` 기본값이 `""` 라 그냥 덤프하면
    `"rule": "", "message": ""` 가 딸려 나가 `schema.md` 11절 예시와 키 구성이 어긋난다.
    """
    return {k: v for k, v in entry.items() if v != ""}


def render_json(report: Report) -> str:
    """`schema.md` 11절 형식 그대로 JSON 문자열을 만든다.

    직렬화 계약은 셋이다 — 셋 다 있어야 11절 예시와 **키 구성까지** 일치한다:

    1. `by_alias=True` — `rule_id`→`rule`, `Summary.passed`→`pass`
    2. `exclude_none=True` — `cause` 가 `None` 인 항목에서 `"cause": null` 이 나가지 않는다
    3. **빈 문자열 필드 생략** — `"rule": ""`, `"message": ""` 가 새어나가지 않는다

    생략은 **빈 문자열**과 **`None`** 에만 적용한다. `summary` 의 4상태 카운트는
    **`0` 이어도 생략하지 않는다.**
    """
    data = report.model_dump(by_alias=True, exclude_none=True)
    data["results"] = [_prune(entry) for entry in data["results"]]
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_text(report: Report) -> str:
    """터미널용 사람이 읽는 출력. 4상태를 구분해 보여준다."""
    s = report.summary
    lines = [
        f"pass {s.passed}  violation {s.violation}  "
        f"not_run {s.not_run}  error {s.error}",
    ]
    for f in report.results:
        where = " > ".join(part for part in (f.path, f.node) if part)
        head = f"[{f.status}] {where}" if where else f"[{f.status}]"
        if f.rule_id:
            head = f"{head} ({f.rule_id})"
        lines.append(head)
        for line in f.message.splitlines():
            if line:
                lines.append(f"    {line}")
        if f.cause is not None:
            lines.append(f"    cause: {f.cause.node} ({f.cause.reason})")
    return "\n".join(lines)


def build_compare_report(values: dict[str, dict[str, Any]]) -> CompareReport:
    """`{노드 id: {target: 값}}` 에서 비교 리포트를 만든다.

    **엔진은 `==` 만 안다.** 허용 오차도 무시 필드도 없다 — 정규화는 비교용 데이터를
    출력하는 노드의 스크립트가 알아서 한다 (`schema.md` 12절).

    **짝지어 비교하는 것이 아니라 목록 전부가 한 값으로 일치하느냐**를 묻는다.
    하나만 어긋나도 `same: false`.
    """
    entries: dict[str, CompareEntry] = {}
    for node_id, by_target in values.items():
        outputs = list(by_target.values())
        same = all(value == outputs[0] for value in outputs)
        entries[node_id] = CompareEntry(same=same, values=dict(by_target))
    return CompareReport(entries)


def write_compare_report(report: CompareReport, path: Path) -> None:
    """비교 리포트를 Spec `plan` 항목의 `report` 위치에 쓴다.

    **실행과 동시에 쌓는 산출물**이지 위반 후 사후 수습이 아니다 —
    "증거 캡처는 하지 않는다"(9절)와 성격이 다르다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report.model_dump(), ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")
