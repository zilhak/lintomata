"""★ 일부러 판정 필드를 뺀 Reckon — **노드 등록이 실패해야** 정상이다 (STR-CONTRACT-007).

출력 dataclass 에 `passed: bool` 이 없으면 엔진이 통과/위반을 읽을 수 없다.
등록 시점에 잡지 못하면 실행할 때까지 아무도 모르고, 그때는 리포트가 아니라 오류가 난다.
"""

from dataclasses import dataclass


@dataclass
class Percept:
    count: int
    labels: list[str]


@dataclass
class ExpectParams:
    expectedCount: int


@dataclass
class Verdict:
    ok: bool
    message: str


@dataclass
class Args:
    input: Percept
    params: ExpectParams


def runNode(args: Args) -> Verdict:
    return returnResult(
        Verdict(ok=args.input.count == args.params.expectedCount, message="판정 필드 이름이 규약과 다르다")
    )
