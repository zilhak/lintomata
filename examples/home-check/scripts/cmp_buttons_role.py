"""비교용 Extract (target: gamma) — `role="button"` 으로 버튼을 인식한다.

마크업은 `<a>` 링크지만 역할이 버튼이므로 버튼으로 센다.

훑는 방법과 라벨 정규화는 `lintomata_lib.buttons` 와 공유한다.
"""

from dataclasses import dataclass

from lintomata_lib import buttons


@dataclass
class Data:
    source: str
    html: str


@dataclass
class Args:
    input: Data


@dataclass
class Meaning:
    count: int
    labels: list[str]


def runNode(args: Args) -> Meaning:
    labels = buttons.collect(
        args.input.html, lambda tag, attrs: attrs.get("role") == "button"
    )
    return returnResult(Meaning(count=len(labels), labels=labels))
