"""값 검증 엔진과 비교 엔진이 **둘 다** 쓰는 실행 결과 자료구조.

`runtime` 과 `compare` 는 서로를 import 하지 않는다 — 공용 결과 타입을 여기 두고
**둘 다 이 모듈에만 의존**한다. 양방향 top-level import 는 `ImportError` 로 터진다.

`run_spec` 이 `kind` 를 보고 값 검증/비교로 디스패치하는 구조는 그대로다
(`schema.md` 3·12절). 디스패치는 **함수 호출 시점의 지역 import** 로 한다.

⚠ stub. Step 3 이전에 확정된 파일이다 — Step 3-a/3-b 어느 쪽도 이 파일을 고치지 않는다.
"""

from __future__ import annotations

from strictler.errors import Status

__all__ = ["NodeOutcome", "RunResult"]


class NodeOutcome:
    """노드 하나의 실행 결과.

    필드: `node_id`, `status`(`Status`), `value`(출력값 — 통과했을 때만),
    `findings`(그 노드가 낸 결과들).

    비교 파이프라인에서는 `value` 가 `{target: 출력값}` 묶음이다 —
    **취합/분배는 엔진이 하고 스크립트는 자기 target 값 하나만 다룬다.**
    """

    def __init__(self, node_id: str, status: Status) -> None:
        raise NotImplementedError("Step 3에서 구현")


class RunResult:
    """파이프라인 한 벌의 실행 결과.

    필드: `outcomes`(`dict[str, NodeOutcome]`), `findings`(`list[Finding]`).
    """

    def __init__(self) -> None:
        raise NotImplementedError("Step 3에서 구현")
