"""값 검증 엔진과 비교 엔진이 **둘 다** 쓰는 실행 결과 자료구조.

`runtime` 과 `compare` 는 서로를 import 하지 않는다 — 공용 결과 타입을 여기 두고
**둘 다 이 모듈에만 의존**한다. 양방향 top-level import 는 `ImportError` 로 터진다.

`run_spec` 이 `kind` 를 보고 값 검증/비교로 디스패치하는 구조는 그대로다
(`schema.md` 3·12절). 디스패치는 **함수 호출 시점의 지역 import** 로 한다.

⚠ Step 3 이전에 확정된 파일이다 — 여기 있는 것은 **자료구조뿐이고 로직이 없다.**
필드를 추가해야 하면 conductor 를 거친다 (Step 3-a·3-b 의 파일 교집합이 되기 때문).
"""

from __future__ import annotations

from typing import Any

from lintomata.errors import Finding, Status

__all__ = ["NodeOutcome", "RunResult"]


class NodeOutcome:
    """노드 하나의 실행 결과.

    필드: `node_id`, `status`(`Status`), `value`(출력값 — 통과했을 때만),
    `findings`(그 노드가 낸 결과들).

    비교 파이프라인에서는 `value` 가 `{target: 출력값}` 묶음이다 —
    **취합/분배는 엔진이 하고 스크립트는 자기 target 값 하나만 다룬다.**
    """

    def __init__(self, node_id: str, status: Status) -> None:
        self.node_id = node_id
        self.status: Status = status
        self.value: Any = None
        self.findings: list[Finding] = []

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"NodeOutcome({self.node_id!r}, {self.status!r})"


class RunResult:
    """파이프라인 한 벌의 실행 결과.

    필드: `outcomes`(`dict[str, NodeOutcome]`), `findings`(`list[Finding]`).
    """

    def __init__(self) -> None:
        self.outcomes: dict[str, NodeOutcome] = {}
        self.findings: list[Finding] = []

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"RunResult(outcomes={sorted(self.outcomes)}, findings={len(self.findings)})"
