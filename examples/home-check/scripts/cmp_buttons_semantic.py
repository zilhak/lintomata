"""비교용 Perceive (target: alpha) — 시맨틱 마크업에서 버튼을 인식한다.

target 마다 **인식 스크립트가 다른 것이 설계**다. HTML 이 완전히 달라도 개념 층
(버튼 개수와 라벨)이 같으면 통과한다. input/output 타입은 노드에 귀속되어 공통이다.
"""

from dataclasses import dataclass
from html.parser import HTMLParser


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


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: list[str] = []
        self._open = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "button":
            self._open = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._open:
            self._open = False
            self.labels.append(" ".join("".join(self._buffer).split()))

    def handle_data(self, data: str) -> None:
        if self._open:
            self._buffer.append(data)


def runNode(args: Args) -> Percept:
    reader = _Reader()
    reader.feed(args.input.html)
    reader.close()
    return returnResult(Percept(count=len(reader.labels), labels=reader.labels))
