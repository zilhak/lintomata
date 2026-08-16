"""★ 일부러 기댓값을 하드코딩한 Reckon — **등록은 통과하고 단위테스트가 잡아야** 정상이다.

`Args.params` 에 기댓값 필드가 **있기는 하다**(그래서 `LNT-CONTRACT-005` 는 안 걸린다).
그런데 `runNode` 가 그 값을 쓰지 않고 3 을 박아 놨다. 정적으로는 못 잡는 자리이고,
`input` 이 같고 `params` 만 다른 대조쌍의 판정이 갈리지 않는 것으로 잡힌다
(`LNT-TEST-007`).
"""

from dataclasses import dataclass


@dataclass
class Percept:
    count: int
    labels: list[str]


@dataclass
class ExpectParams:
    expectedCount: int
    expectedLabels: list[str]


@dataclass
class Verdict:
    passed: bool
    rule: str
    message: str


@dataclass
class Args:
    input: Percept
    params: ExpectParams


def runNode(args: Args) -> Verdict:
    passed = args.input.count == 3
    return returnResult(
        Verdict(
            passed=passed,
            rule="hardcodedCount",
            message=f"3개 기대(하드코딩), {args.input.count}개 관측",
        )
    )
