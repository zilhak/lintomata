"""Reckon — 판정. 지각한 것을 **기획과 대조**한다.

기댓값은 절대 하드코딩하지 않는다 — `Args.params` 로 Spec 이 준다. 그래야 기획을
고치면 판정이 바뀌고, 같은 노드를 버튼에도 메뉴에도 쓸 수 있다.

출력 dataclass 에는 `passed: bool` 이 있어야 엔진이 통과/위반을 읽는다.
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
    want_count = args.params.expectedCount
    want_labels = args.params.expectedLabels
    got_count = args.input.count
    got_labels = args.input.labels

    if got_count != want_count:
        return returnResult(
            Verdict(
                passed=False,
                rule="expectedCount",
                message=f"{want_count}개 기대, {got_count}개 관측 ({got_labels})",
            )
        )
    if got_labels != want_labels:
        return returnResult(
            Verdict(
                passed=False,
                rule="expectedLabels",
                message=f"{want_labels} 순서 기대, {got_labels} 관측",
            )
        )
    return returnResult(
        Verdict(passed=True, rule="expectedCount", message=f"{got_count}개, 순서 일치")
    )
