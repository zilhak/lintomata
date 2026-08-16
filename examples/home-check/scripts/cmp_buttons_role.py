"""비교용 Perceive (target: gamma) — `role="button"` 으로 버튼을 인식한다.

마크업은 `<a>` 링크지만 역할이 버튼이므로 버튼으로 센다.
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
        self._depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._depth > 0:
            self._depth += 1
            return
        table = {name: (value or "") for name, value in attrs}
        if table.get("role") == "button":
            self._depth = 1
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            self.labels.append(" ".join("".join(self._buffer).split()))

    def handle_data(self, data: str) -> None:
        if self._depth > 0:
            self._buffer.append(data)


def runNode(args: Args) -> Percept:
    reader = _Reader()
    reader.feed(args.input.html)
    reader.close()
    return returnResult(Percept(count=len(reader.labels), labels=reader.labels))
