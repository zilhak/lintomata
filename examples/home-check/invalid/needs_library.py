"""**일부러 틀린 것의 재료** — `buttons` 슬롯을 요구하는 스크립트.

스크립트 자체는 멀쩡하다(`script add` 는 통과한다). 요구한 슬롯을 노드가 배선하지
않은 것이 결함이고, 그건 노드 등록에서 `STR-LIB-001` 로 걸린다 — 능력 선언과
사용 선언은 층이 다르므로 걸리는 시점도 다르다.
"""

from dataclasses import dataclass

from strictler_lib import buttons


@dataclass
class Sensum:
    source: str
    html: str


@dataclass
class Args:
    input: Sensum


@dataclass
class Percept:
    count: int
    labels: list[str]


def runNode(args: Args) -> Percept:
    labels = buttons.collect(args.input.html, buttons.is_button)
    return returnResult(Percept(count=len(labels), labels=labels))
