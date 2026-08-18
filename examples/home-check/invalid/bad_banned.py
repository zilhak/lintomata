"""★ 일부러 규칙을 어긴 스크립트 — 등록이 **실패해야 정상**이다.

담긴 위반:
  - `import time` / `import random`      시간 의존·랜덤 (LNT-BAN-001 / -002)
  - `subprocess.run(...)`                직접 subprocess (LNT-BAN-003)
  - `args.state.nowhere`                 미선언 state 참조 (LNT-BAN-004)
  - `notes: dict`                        dict 금지 (LNT-TYPE-001)
  - `hint: Optional[str]`                Optional 금지 (LNT-TYPE-002)
"""

import random
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Data:
    source: str
    html: str
    notes: dict
    hint: Optional[str]


@dataclass
class BadState:
    ready: bool


@dataclass
class Args:
    input: Data
    state: BadState


@dataclass
class Meaning:
    count: int


def runNode(args: Args) -> Meaning:
    subprocess.run(["ls"], check=False)
    seed = int(time.time()) + random.randint(0, 9)
    if args.state.nowhere:
        seed += 1
    return returnResult(Meaning(count=seed))
