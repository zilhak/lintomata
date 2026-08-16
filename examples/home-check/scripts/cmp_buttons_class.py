"""비교용 Perceive (target: beta) — 클래스 이름으로 버튼을 인식한다.

`class` 에 `btn` 토큰이 있으면 버튼으로 본다. 마크업은 `span` 이지만 사람에게는
버튼이므로 개념 층에서는 alpha 와 같은 값이 나와야 한다.

훑는 방법과 라벨 정규화는 `lintomata_lib.buttons` 와 공유한다 — 그래야 개념 층
비교가 마크업 차이가 아니라 **개념 차이**만 잡는다.
"""

from dataclasses import dataclass

from lintomata_lib import buttons


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
    labels = buttons.collect(
        args.input.html, lambda tag, attrs: "btn" in attrs.get("class", "").split()
    )
    return returnResult(Percept(count=len(labels), labels=labels))
