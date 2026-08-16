"""Perceive — 지각. **메뉴가 몇 개이고 어떤 순서인가.**

`<nav>` 안의 `<li>` 텍스트를 순서대로 뽑는다. 사람이 보는 것(메뉴 항목과 그 순서)만
남기고 마크업의 형태는 버린다.
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


class _MenuReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: list[str] = []
        self._in_nav = False
        self._in_item = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "nav":
            self._in_nav = True
        elif tag == "li" and self._in_nav:
            self._in_item = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav":
            self._in_nav = False
        elif tag == "li" and self._in_item:
            self._in_item = False
            self.labels.append("".join(self._buffer).strip())

    def handle_data(self, data: str) -> None:
        if self._in_item:
            self._buffer.append(data)


def runNode(args: Args) -> Percept:
    reader = _MenuReader()
    reader.feed(args.input.html)
    reader.close()
    return returnResult(Percept(count=len(reader.labels), labels=reader.labels))
