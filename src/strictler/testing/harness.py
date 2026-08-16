"""노드 단위테스트 실행 (`schema.md` 14절).

### 기본 제공이 확인하는 것 — 케이스마다 순서대로

| | 확인 | 실패하면 |
|---|---|---|
| 1 | `args` 가 스크립트의 `Args` 선언에 맞는가 | **테스트 정의가 잘못됨** (`STR-TEST-001`) |
| 2 | `runNode` 가 예외 없이 끝나는가 | 오류 (`STR-TEST-002`) |
| 3 | `returnResult()` 반환값이 선언된 출력 타입에 맞는가 | 오류 (`STR-TEST-003`) |

**1번을 따로 세는 이유:** 스크립트가 아니라 **테스트 쪽이 틀린 경우**라 에러 메시지가
달라야 한다. AI 가 fixture 를 잘못 썼는지 스크립트를 잘못 썼는지 구분되어야 자기 수정이 된다.

### 노드 타입별로 추가되는 기본 검사

- **Action — 값 동일성까지 본다.** `input == output` 이 계약이므로 타입이 아니라 값이
  같은지를 자동 검사할 수 있다. 사용자가 `expect` 를 안 써도 된다 — **기대값이 곧
  입력**이기 때문이다 (`STR-TEST-005`).
- **Reckon — 기댓값 반응성.** "기댓값 하드코딩 금지"는 정적으로는 `Args.params` 에
  필드가 *있는지*까지만 본다. 받아놓고 안 쓰면 못 잡는다. 단, 값을 흔들어보는 것만으론
  안 된다 — `expected=3` 도 `expected=4` 도 실제가 2개면 둘 다 위반이라 결과가 같게
  나온다. **통과하는 기댓값과 위반하는 기댓값이 둘 다 있어야** 반응성이 증명된다.
  → `input` 이 같고 `params` 만 다른 통과/위반 쌍이 없으면 **경고**(`STR-TEST-006`),
    있는데 판정이 같으면 **오류**(`STR-TEST-007`).

### 결정성 검사는 하지 않는다

같은 입력으로 두 번 돌려 같은 결과가 나오는지 보는 건 값싸고 강력하지만,
**Perceive 안에서 AI 를 부르면 당연히 실패한다.** "노드 내부는 input/output 만 맞추면
된다"와 정면으로 충돌하므로 하지 않는다 (`schema.md` 16절 — 폐기된 안).

⚠ stub. Step 4 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from strictler.checks.script import ScriptContract
from strictler.errors import Finding
from strictler.model import Node, NodeTest, TestCase
from strictler.store.entries import Store

__all__ = [
    "load_node_test",
    "run_node_test",
    "run_case",
    "materialize_args",
    "check_action_transparency",
    "check_reckon_contrast",
]


def load_node_test(path: Path, env: Mapping[str, str]) -> tuple[NodeTest | None, list[Finding]]:
    """`<노드파일>.test.json` 을 로드한다. 경로 규칙 적용."""
    raise NotImplementedError("Step 4에서 구현")


def run_node_test(
    node_test: NodeTest,
    *,
    store: Store,
    env: Mapping[str, str],
) -> list[Finding]:
    """단위테스트 전체를 돌린다. `strictler node test <id>` 의 본체.

    케이스별 결과 + 노드 타입별 추가 검사(Action 투명성, Reckon 대조쌍)를 합친다.
    """
    raise NotImplementedError("Step 4에서 구현")


def run_case(
    node: Node,
    contract: ScriptContract,
    script_path: Path,
    case: TestCase,
    *,
    env: Mapping[str, str],
) -> tuple[Any, list[Finding]]:
    """케이스 하나를 돌린다. 반환값과 결과들을 함께 준다.

    반환값은 Action 투명성·Reckon 대조쌍 검사가 이어서 쓴다.
    """
    raise NotImplementedError("Step 4에서 구현")


def materialize_args(
    raw: Mapping[str, Any],
    contract: ScriptContract,
    env: Mapping[str, str],
) -> Any:
    """JSON fixture 를 실제 `Args` 인스턴스로 만든다.

    **`bytes` 필드**(스크린샷 등)는 JSON 에 못 담으므로 `{"$file": "<절대경로>"}` 로
    주고 엔진이 읽어 bytes 로 채운다. 경로 규칙 그대로 적용.
    """
    raise NotImplementedError("Step 4에서 구현")


def check_action_transparency(case: TestCase, input_value: Any, output_value: Any) -> list[Finding]:
    """Action 노드의 **값 동일성** 검사 (`STR-TEST-005`).

    Action 은 데이터를 그대로 통과시켜야 한다 — 부작용만 일으키고 값은 건드리지 않는다.
    """
    raise NotImplementedError("Step 4에서 구현")


def check_reckon_contrast(
    cases: list[TestCase],
    outputs: list[Any],
) -> list[Finding]:
    """Reckon 노드의 **기댓값 반응성** 검사 (`STR-TEST-006` 경고 / `-007` 오류).

    `input` 이 같고 `params` 만 다른 통과/위반 쌍을 찾아 판정이 실제로 갈리는지 본다.
    `-006` 이 경고인 이유: 규칙 위반이 아니라 테스트 커버리지 문제에 가깝기 때문.
    """
    raise NotImplementedError("Step 4에서 구현")
