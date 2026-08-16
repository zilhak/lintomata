"""Perceive — 지각. **무엇이 버튼인가**를 판정한다. 이 프로젝트의 도메인 지식이다.

`<button>` 이 있다고 그게 버튼인 것이 아니다. 여기서 정한 규칙:

- `<button>` 태그이면 버튼이다
- `role="button"` 이면 버튼이다 (마크업이 `div`/`a` 여도 사람에겐 버튼이다)
- 단 `data-decoy="true"` 는 **누를 수 있게 생긴 배경 장식**이므로 버튼이 아니다

`when` 으로 실행 시점을 제어하기 위해 `Args.state.ready` 를 선언한다 — 노드 자기
어휘이고, 파이프라인이 실제 상태 이름으로 매핑한다.
"""

from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class Sensum:
    source: str
    html: str


@dataclass
class PerceiveState:
    ready: bool


@dataclass
class Args:
    input: Sensum
    state: PerceiveState


@dataclass
class Percept:
    count: int
    labels: list[str]


class _ButtonReader(HTMLParser):
    """버튼으로 인정된 요소의 텍스트만 모은다."""

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
        if table.get("data-decoy") == "true":
            return
        if tag == "button" or table.get("role") == "button":
            self._depth = 1
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            self.labels.append("".join(self._buffer).strip())

    def handle_data(self, data: str) -> None:
        if self._depth > 0:
            self._buffer.append(data)


def runNode(args: Args) -> Percept:
    reader = _ButtonReader()
    reader.feed(args.input.html)
    reader.close()
    return returnResult(Percept(count=len(reader.labels), labels=reader.labels))
