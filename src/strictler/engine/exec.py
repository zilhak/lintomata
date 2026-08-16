"""스크립트 하나를 로드·실행하고 input/output 을 검증한다 (`schema.md` 6·7절).

**사용자 코드 실행에 샌드박싱은 하지 않는다.** ESLint 플러그인·vite 플러그인·
jest transform 이 전부 사용자 코드를 그냥 로드해 실행한다. lint 계열의 표준
신뢰 모델을 그대로 따른다 (`schema.md` 16절 — 폐기된 안).

**★ 노드 내부는 input / output 만 맞추면 된다.** 내부에서 AI 를 부르든 파일을 읽든
네트워크를 타든 엔진은 관여하지 않는다. **순수함수는 강제하지 않는다.**
AI 를 껴서 output 을 잘못 내놓으면 **타입 계약에 걸려 그냥 에러**다. 그걸로 충분하다.

**pydantic 경계 검증이 실제 값을 만나는 자리**가 여기와 단위테스트 하네스 둘뿐이다.

⚠ stub. Step 3 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from strictler.checks.script import ScriptContract
from strictler.errors import Finding
from strictler.typesys.registry import TypeRegistry

__all__ = [
    "load_script",
    "build_args",
    "invoke",
    "validate_input",
    "validate_output",
]


def load_script(path: Path) -> ModuleType:
    """스크립트 파일을 모듈로 로드한다.

    노드 스크립트는 PEP 723 헤더로 자기 의존성을 선언할 수 있다 — 스크립트 하나가
    자기완결 파일이 된다 (`CLAUDE.md` 구현 언어 절).
    """
    raise NotImplementedError("Step 3에서 구현")


def build_args(
    module: ModuleType,
    contract: ScriptContract,
    *,
    input_value: Any = None,
    params: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> Any:
    """스크립트가 선언한 `Args` 인스턴스를 만든다.

    **세 필드는 쓰는 것만 선언한다** — 입력이 없는 Vantage 는 `input` 필드를
    아예 두지 않으므로, 선언에 없는 필드는 채우지 않는다.
    """
    raise NotImplementedError("Step 3에서 구현")


def invoke(module: ModuleType, args: Any) -> Any:
    """`runNode(args)` 를 호출하고 `returnResult()` 로 나온 값을 준다.

    스크립트가 예외를 내면 그건 **오류**다 — 위반이 아니다 (`schema.md` 9절).
    호출자가 `Finding(status="error")` 로 바꾼다.
    """
    raise NotImplementedError("Step 3에서 구현")


def validate_input(
    contract: ScriptContract,
    value: Any,
    registry: TypeRegistry,
    *,
    path: str,
    node: str,
) -> list[Finding]:
    """앞단에서 온 값이 이 노드의 `Args.input` 선언에 맞는지 (pydantic 경계 검증)."""
    raise NotImplementedError("Step 3에서 구현")


def validate_output(
    contract: ScriptContract,
    value: Any,
    registry: TypeRegistry,
    *,
    path: str,
    node: str,
) -> list[Finding]:
    """반환값이 선언된 출력 타입에 맞는지.

    Action 이면 여기서 **값 동일성**(input == output)까지 볼 수 있다 —
    다만 그 검사의 정식 자리는 단위테스트다 (`STR-TEST-005`).
    """
    raise NotImplementedError("Step 3에서 구현")
