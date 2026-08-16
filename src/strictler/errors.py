"""검사 결과 1건(`Finding`)과 도구 자신의 예외(`StrictlerError`).

`schema.md` 9·11절이 근거다.

**★ 이건 lint 다. 세 가지를 반드시 구분한다:**

| | 무엇 | 성격 |
|---|---|---|
| **위반** (`violation`) | 기획과 다르다 | **정상 결과.** 리포트에 담긴다 |
| **not run** (`not_run`) | 앞단 실패의 여파로 도달 불가 | **정상 결과.** 통과와 구분해 보고 |
| **오류** (`error`) | 스크립트 예외, 계약 위반, 경로 없음, 환경변수 미정의 | **비정상.** 도구가 못 돈 것 |

**고쳐야 할 것은 오류뿐이다.** 이 구분이 흐려지면 위반을 오류처럼 다루거나(불필요한
복구 로직), 오류를 위반처럼 다루게 된다(거짓 리포트).

`skipped` 상태는 **없다** — skip 은 엔진 개념이 아니다 (`schema.md` 10·16절).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Status", "NotRunCause", "Finding", "StrictlerError"]


Status = Literal["pass", "violation", "not_run", "error"]
"""결과 4상태. 이 넷이 전부다."""


class NotRunCause(BaseModel):
    """`not_run` 의 원인 — **not run 으로 바꾸는 그 시점에 적는다** (`schema.md` 9절).

    전파 경로가 둘이다:
    - `data_dependency` — 실패한 노드의 출력을 `inputs` 로 받았다
    - `state_unreachable` — 상태를 바꿀 노드가 실패해 그 전이가 일어나지 않았다
    """

    model_config = ConfigDict(extra="forbid")

    node: str
    """원인이 된 노드 id."""

    reason: str
    """`data_dependency` | `state_unreachable`."""


class Finding(BaseModel):
    """결과 1건. 리포트의 `results` 원소 그대로다 (`schema.md` 11절).

    **flat 리스트 + 경로 필드.** Spec→plan→pipeline→node 중첩으로 쌓지 않는다 —
    기계가 읽기 쉽고 AI 가 고치기 쉬운 쪽을 택한다.

    **가이드는 별도 필드가 아니라 `message` 에 포함한다.** `rules.py` 의 `guide` 가
    메시지 뒤에 이어붙는다 — 그 문구가 곧 AI 자기 수정 루프의 성능이다.

    JSON 직렬화 시 `rule_id` 는 `rule` 로 나간다 (`model_dump(by_alias=True)`).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Status

    path: str = ""
    """`"login.json > plan[0] > login-flow"` 형태의 위치 경로."""

    node: str = ""
    """노드 id. 리포트 누적 단위는 **노드별**이다."""

    rule_id: str = Field(default="", serialization_alias="rule")
    """`STR-<CATEGORY>-<NNN>` (`rules.md` 1절). 값 검증 위반은 Reckon 이 낸 규칙 이름이 올 수도 있다."""

    message: str = ""
    """사람/AI 가 읽는 설명. 규칙의 `message` + `guide` 가 이어붙은 것."""

    cause: NotRunCause | None = None
    """`status == "not_run"` 일 때만 채워진다."""


class StrictlerError(Exception):
    """**도구가 못 돈 것.** 위반이 아니라 오류다 (`schema.md` 9절).

    등록 실패, 경로 규칙 위반, 환경변수 미정의, 해시 불일치 같이 진행 자체가
    성립하지 않는 경우에 던진다. **위반을 이걸로 던지면 안 된다** — 위반은 정상
    결과이므로 `Finding` 으로 수집된다.

    CLI 경계에서 잡아 `findings` 를 리포트로 내고 비정상 종료 코드를 준다.
    """

    def __init__(self, message: str, findings: list[Finding] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.findings: list[Finding] = findings or []
