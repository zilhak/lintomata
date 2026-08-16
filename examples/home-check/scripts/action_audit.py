"""Action — 행위. 관측 사실을 감사 로그에 한 줄 남기고 **값은 그대로 흘려보낸다.**

`input == output` 이 계약이다. 데이터 변환은 하지 않고 부작용만 일으킨다.
실행 시각은 엔진이 `${state.__startedAt}` 로 `params` 에 넣어 준다 — 스크립트가
시간을 직접 읽는 것은 금지다.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Sensum:
    source: str
    html: str


@dataclass
class AuditParams:
    logPath: str
    startedAt: int


@dataclass
class Args:
    input: Sensum
    params: AuditParams


def runNode(args: Args) -> Sensum:
    line = f"{args.params.startedAt}\t{args.input.source}\t{len(args.input.html)}\n"
    Path(args.params.logPath).parent.mkdir(parents=True, exist_ok=True)
    with open(args.params.logPath, "a", encoding="utf-8") as handle:
        handle.write(line)
    return returnResult(args.input)
