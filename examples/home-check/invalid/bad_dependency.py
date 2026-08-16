# /// script
# requires-python = ">=3.11"
# dependencies = ["definitely-not-installed-xyz>=1"]
# ///
"""★ 일부러 없는 패키지를 선언한 스크립트 — **등록이 실패해야** 정상이다 (STR-DEP-001).

PEP 723 헤더는 **선언일 뿐 환경을 만들어 주지 않는다.** 노드 스크립트는 strictler 와
**같은 프로세스**에 로드되므로 `import` 가 strictler 가 설치된 환경에서 풀린다
(`schema.md` 6절 — 격리하지 않는다). 그래서 선언한 것이 그 환경에 없으면
등록 시점에 거절하고 설치 명령을 알려준다:

    uv tool install strictler --with 'definitely-not-installed-xyz>=1'

→ **헤더가 아예 없는 것이 정상이다.** `scripts/` 의 것들은 stdlib 만 쓰므로 헤더가 없다.
   외부 패키지를 실제로 쓸 때만 선언하고, 그 환경에 함께 깐다.
"""

from dataclasses import dataclass


@dataclass
class Sensum:
    source: str
    html: str


@dataclass
class Percept:
    count: int


@dataclass
class Args:
    input: Sensum


def runNode(args: Args) -> Percept:
    return returnResult(Percept(count=args.input.html.count("<button")))
