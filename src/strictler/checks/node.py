"""노드 JSON 로드와 검증 — **노드 등록 시** (`schema.md` 13절).

| 검증 | 규칙 |
|---|---|
| `script` 가 실재하는지, 경로 규칙을 지키는지 | `STR-REF-001` / `STR-PATH-001`~`003` |
| `${ref.<id>}` 의 접두가 그 자리가 요구하는 종류와 맞는지 | `STR-REG-003` |
| 스크립트가 `runNode(args: Args)` / `returnResult()` 형태인지 | `STR-CONTRACT-001`~`003` |
| `Args` 필드가 `input`/`params`/`state` 중에서만 쓰였는지 | `STR-CONTRACT-004` |
| 선언된 타입이 primitive 집합 + dataclass 뿐인지 | `STR-TYPE-001`~`003` |
| Reckon 이면 `Args.params` 에 기댓값 필드가 있는지 | `STR-CONTRACT-005` |
| Action 이면 input 타입 == output 타입인지 | `STR-CONTRACT-006` |
| 금지 패턴이 없는지 | `STR-BAN-001`~`004` |
| `Args.state` 필드 이름에 `__` 접두를 쓰지 않았는지 | `STR-STATE-001` |

즉 **노드 검사 = 노드 JSON 자체 검사 + 그 스크립트를 노드 타입과 함께 검사**다.

⚠ stub. Step 2 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from strictler.checks.script import ScriptContract
from strictler.errors import Finding
from strictler.model import Node
from strictler.store.entries import Store

__all__ = ["load_node", "resolve_script", "check_node"]


def load_node(raw: Mapping[str, Any], path: str) -> tuple[Node | None, list[Finding]]:
    """JSON dict 를 `Node` 모델로 로드한다.

    pydantic 검증 실패(모르는 키, 잘못된 `type` 값 등)를 `Finding` 으로 바꿔 낸다 —
    pydantic 에러가 구조화돼 있어 AI 가 읽고 자기 수정하기 좋다.
    """
    raise NotImplementedError("Step 2에서 구현")


def resolve_script(
    node: Node,
    *,
    store: Store,
    env: Mapping[str, str],
    config: Mapping[str, Any] | None = None,
    target: str = "",
) -> tuple[Path | None, list[Finding]]:
    """노드의 `script` 를 실제 파일 경로로 푼다.

    `${ref.sc_...}` 면 등록소에서, 경로면 경로 규칙을 적용해서.
    `${config.X}` 도 올 수 있다 — 비교 파이프라인에서 target 별로 스크립트가
    갈리는 자리다 (`schema.md` 12절). 그래서 `config`/`target` 을 받는다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_node(
    node: Node,
    source_path: str,
    *,
    store: Store,
    env: Mapping[str, str],
) -> tuple[ScriptContract | None, list[Finding]]:
    """노드 하나의 등록 시 정적 검사 전체.

    성공하면 그 스크립트의 `ScriptContract` 를 함께 준다 — 파이프라인 검사가 이걸 쓴다.
    """
    raise NotImplementedError("Step 2에서 구현")
