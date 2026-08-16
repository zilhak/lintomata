"""Sense — 감각 입력. 관측 지점의 파일을 읽어 해석 없는 원시 HTML 을 낸다.

파일이 없으면 예외가 난다. 그건 위반이 아니라 **오류**다 — 검사 자체가 못 돈 것이다.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Scene:
    source: str


@dataclass
class Sensum:
    source: str
    html: str


@dataclass
class Args:
    input: Scene


def runNode(args: Args) -> Sensum:
    html = Path(args.input.source).read_text(encoding="utf-8")
    return returnResult(Sensum(source=args.input.source, html=html))
