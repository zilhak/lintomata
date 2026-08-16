"""비교용 Perceive (target: alpha) — 시맨틱 마크업에서 버튼을 인식한다.

target 마다 **인식 스크립트가 다른 것이 설계**다. HTML 이 완전히 달라도 개념 층
(버튼 개수와 라벨)이 같으면 통과한다. input/output 타입은 노드에 귀속되어 공통이다.

**훑는 방법과 라벨 정규화는 라이브러리와 공유한다** — 값 검증용 스크립트와 같은
규칙이어야 개념 층 비교가 성립한다. 갈리는 것은 *무엇을 버튼으로 볼 것인가* 뿐이다.
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
    labels = buttons.collect(args.input.html, lambda tag, attrs: tag == "button")
    return returnResult(Percept(count=len(labels), labels=labels))
