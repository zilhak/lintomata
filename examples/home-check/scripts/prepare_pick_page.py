"""Prepare — 어디서 볼 것인가. 검사 대상 HTML 파일 하나를 관측 지점으로 잡는다.

입력은 없다(`Args` 에 `input` 필드를 두지 않는다). 볼 대상은 Spec 이 `params` 로 준다.
"""

from dataclasses import dataclass


@dataclass
class PickParams:
    pagePath: str


@dataclass
class Context:
    source: str


@dataclass
class Args:
    params: PickParams


def runNode(args: Args) -> Context:
    return returnResult(Context(source=args.params.pagePath))
