"""**일부러 틀린 것** — 라이브러리가 `dataclass` 를 선언한다 (`LNT-LIB-004`, v1 제한).

노드 간 계약 타입이 스크립트 밖에서 생기면 계약 추출이 파일 하나만 파싱하므로
타입 레지스트리에 구멍이 난다. 이 선언은 그것을 쓰는 스크립트로 옮겨야 한다.
"""

from dataclasses import dataclass


@dataclass
class Button:
    label: str


def first(labels):
    return Button(label=labels[0])
