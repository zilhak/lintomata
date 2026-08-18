"""★ 일부러 출력을 primitive 로 낸 스크립트 — **등록이 실패해야** 정상이다 (LNT-CONTRACT-003).

타입 동일성은 **구조로** 판정한다(`(필드명, 타입)` 쌍의 집합). primitive 를 그대로
내보내면 대조할 구조가 없어서 뒷단과의 배선 검사가 성립하지 않는다.
→ 개수 하나를 내보내더라도 `@dataclass class Meaning: count: int` 처럼 감싼다.
   고친 판이 `scripts/extract_buttons.py` 다.
"""

from dataclasses import dataclass


@dataclass
class Data:
    source: str
    html: str


@dataclass
class Args:
    input: Data


def runNode(args: Args) -> int:
    return returnResult(args.input.html.count("<button"))
