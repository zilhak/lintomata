"""Perceive — 지각. **무엇이 버튼인가**를 판정한다. 이 프로젝트의 도메인 지식이다.

판정 자체는 **라이브러리에 있다** (`libraries/buttons.py`) — 비교용 인식 스크립트
셋과 같은 규칙을 써야 하기 때문이다. 노드가 그 슬롯에 무엇을 쓸지 배선하고
(`nodes/detect_buttons.json` 의 `libraries`), 여기서는 **필요하다고 선언만** 한다.

`when` 으로 실행 시점을 제어하기 위해 `Args.state.ready` 를 선언한다 — 노드 자기
어휘이고, 파이프라인이 실제 상태 이름으로 매핑한다.
"""

from dataclasses import dataclass

from strictler_lib import buttons


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


def runNode(args: Args) -> Percept:
    labels = buttons.collect(args.input.html, buttons.is_button)
    return returnResult(Percept(count=len(labels), labels=labels))
