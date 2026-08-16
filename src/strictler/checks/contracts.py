"""스크립트 계약의 재사용 — 같은 스크립트를 한 번의 실행 안에서 두 번 파싱하지 않는다.

한 번의 `check` 안에서 같은 스크립트가 **노드당 세 번** 파싱된다:

| 어디 | 왜 |
|---|---|
| `checks.pipeline.recheck_resolved` | config 가 풀린 뒤의 재검 (R3-4) |
| 그 안의 `checks.script.check_script` | 자기가 쓸 계약을 스스로 뽑는다 |
| `engine.runtime._load_nodes` / `engine.compare._resolve_one` | 구동 재료 |

**같은 파일에서는 같은 계약이 나온다.** 세 자리가 서로 다른 것을 보는 것이 아니므로
두 번째부터는 파싱할 이유가 없다. 검사를 **없애는** 것이 아니라 **AST 파싱 결과를
재사용**하는 것이다 — 판정에는 아무 영향이 없다.

### 키는 경로 + 내용 해시다

경로만 쓰면 실행 도중 파일이 바뀌었을 때 옛 계약을 돌려준다.
**틀린 캐시는 없는 캐시보다 훨씬 나쁘다** — lint 도구가 검사하지 않은 내용을
검사했다고 보고하게 된다.

### 수명은 한 번의 실행이다

모듈 전역에 두지 않는다. 프로세스에 남으면 테스트가 서로 오염되고, 등록소를
갈아끼운 다음 실행이 옛 결과를 본다.
"""

from __future__ import annotations

import hashlib

from strictler.checks import script as script_checks
from strictler.checks.script import ScriptContract
from strictler.errors import Finding

__all__ = ["ScriptCache"]


class ScriptCache:
    """한 번의 실행 동안 `(경로, 내용 해시) → 계약` 을 들고 있는다.

    `engine.runtime` 과 `engine.compare` 가 **둘 다 같은 것을 쓴다** — 한쪽만
    쓰면 두 파이프라인 종류의 동작이 갈린다 (R4-1 이 실제로 겪은 일이다).
    """

    def __init__(self) -> None:
        self._memo: dict[tuple[str, str], tuple[ScriptContract, list[Finding]]] = {}

    def contract(self, source: str, path: str) -> tuple[ScriptContract, list[Finding]]:
        """`extract_contract(source, path)` 과 **같은 것**을 돌려준다.

        **파싱 실패는 캐시하지 않는다.** `StrictlerError` 는 그대로 올라간다 —
        그건 위반이 아니라 검사기가 못 돈 것이고, 그 경로는 어차피 진행하지 않는다.
        """
        key = (path, hashlib.sha256(source.encode("utf-8")).hexdigest())
        hit = self._memo.get(key)
        if hit is None:
            # 모듈 속성으로 부른다 — `from ... import` 로 묶어두면 이 캐시를 거치는
            # 경로만 대역이 안 걸려 테스트가 두 가지 `extract_contract` 를 보게 된다.
            hit = script_checks.extract_contract(source, path)
            self._memo[key] = hit
        contract, findings = hit
        # 부르는 쪽이 이 목록에 `extend` 한다 — 원본을 주면 캐시가 오염된다.
        return contract, list(findings)
