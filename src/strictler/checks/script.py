"""스크립트 AST 검사 — 노드 계약·타입·금지 패턴 (`schema.md` 6·13절).

**스크립트를 돌리지 않는다.** `ast` 로 읽어 선언과 형식만 본다.

### 진입점·출력 함수는 이름이 고정이다

| | 이름 | 규칙 |
|---|---|---|
| 진입점 | `runNode(args)` | 전 노드 타입 공통. `args` 의 타입은 dataclass **`Args`** |
| 출력 | `returnResult()` | 반환 타입은 dataclass. **이름은 자유** |

`Args` 만 이름이 고정인 것은 **엔진이 찾아야 하기 때문**이고, 반환 타입 이름을
고정하지 않는 것은 **구조로 매칭**하기 때문이다 (`schema.md` 7절).

### `Args` 는 세 필드로 출처를 나눈다

    input   앞단 노드들의 출력      ← DAG 가 준다
    params  Spec 이 채운 값        ← Spec 이 준다
    state   참조할 파이프라인 상태   ← 런타임이 준다

**쓰는 것만 선언한다.** 입력이 없는 Vantage 는 `input` 필드를 아예 두지 않는다.
**`Args.state` 가 곧 "필요 상태 선언"이다** — 별도 `need_state` 배열 같은 것은 없다.

### 금지는 전 노드 균일하다

시간 의존 / 랜덤 / 직접 subprocess / 미선언 state 참조.
**그 외에는 아무것도 금지하지 않는다** — 파일 IO·네트워크·환경변수 전부 자유다.
노드 내부에서 AI 를 부르든 상관하지 않는다. output 을 잘못 내놓으면 타입 계약에 걸릴 뿐이다.

⚠ **완벽한 정적 검사는 목표가 아니다.** `__import__("ti"+"me")` 같은 우회는 못 막는다.
사전에 추측할 수 있는 행위만 막고, **에러 메시지에 자연어 가이드를 넣는다** —
작성 주체가 AI 라는 전제 덕에 이게 유효하다.

⚠ stub. Step 2 에서 구현한다.
"""

from __future__ import annotations

from strictler.errors import Finding
from strictler.model import NodeType
from strictler.typesys.registry import DataclassSpec

__all__ = [
    "ScriptContract",
    "extract_contract",
    "check_script",
    "check_entrypoint",
    "check_args_shape",
    "check_types",
    "check_bans",
    "check_node_type_form",
    "check_tool_calls",
]


class ScriptContract:
    """스크립트에서 뽑아낸 **능력 선언**. 이후 층 전부가 이걸 보고 판단한다.

    필드:
      `path`         — 스크립트 경로 (에러 메시지용)
      `dataclasses`  — 선언된 dataclass 들 (`dict[str, DataclassSpec]`)
      `input_type`   — `Args.input` 의 타입 이름. 없으면 `""`
      `params_type`  — `Args.params` 의 타입 이름. 없으면 `""`
      `state_type`   — `Args.state` 의 타입 이름. 없으면 `""`
      `state_names`  — `Args.state` dataclass 의 필드 이름들 = **노드가 요구하는 상태 이름**
      `output_type`  — `returnResult()` 로 나가는 dataclass 이름
      `tool_calls`   — `(함수명, 실행파일 경로 인자)` 목록. 실행 시 Spec `tool` 과 대조
    """

    def __init__(self, path: str) -> None:
        raise NotImplementedError("Step 2에서 구현")


def extract_contract(source: str, path: str) -> tuple[ScriptContract, list[Finding]]:
    """스크립트 소스에서 계약을 뽑는다. 뽑는 도중 잡히는 형식 오류도 같이 낸다.

    파이프라인 검사·엔진·단위테스트가 전부 이 결과를 재료로 쓴다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_script(source: str, path: str, node_type: NodeType | None = None) -> list[Finding]:
    """스크립트 하나의 전체 정적 검사. 아래 검사들을 전부 돌려 합친다.

    `node_type` 이 없으면(스크립트 단독 등록) 타입별 형식 요구는 건너뛴다 —
    그건 노드 등록 시에 돈다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_entrypoint(contract: ScriptContract) -> list[Finding]:
    """`runNode(args: Args)` 형태인지, `returnResult()` 를 호출하는지.

    `STR-CONTRACT-001` (Args 미선언) / `-002` (진입점) / `-003` (반환).
    """
    raise NotImplementedError("Step 2에서 구현")


def check_args_shape(contract: ScriptContract) -> list[Finding]:
    """`Args` 가 `input`/`params`/`state` 외의 필드를 갖지 않는지 (`STR-CONTRACT-004`).

    `Args.state` 필드 이름에 `__` 접두를 사용자가 쓰지 않았는지도 본다
    (`STR-STATE-001` — `__` 는 엔진 제공 필드 예약).
    """
    raise NotImplementedError("Step 2에서 구현")


def check_types(contract: ScriptContract) -> list[Finding]:
    """선언된 타입이 primitive 집합 + dataclass 뿐인지.

    `STR-TYPE-001` (`dict`) / `-002` (`Optional`·`None`) / `-003` (그 밖).
    """
    raise NotImplementedError("Step 2에서 구현")


def check_bans(source: str, path: str, contract: ScriptContract) -> list[Finding]:
    """금지 패턴. `STR-BAN-001` (시간) / `-002` (랜덤) / `-003` (직접 subprocess) /
    `-004` (미선언 state 참조).

    `tool` 로 선언된 함수가 부가적으로 subprocess 를 띄우는 것은 막지 않는다 —
    `Args.state` 와 같은 구조다: **미리 선언하면 허용, 선언 없으면 에러.**
    """
    raise NotImplementedError("Step 2에서 구현")


def check_node_type_form(contract: ScriptContract, node_type: NodeType) -> list[Finding]:
    """노드 타입별 형식 요구 — **노드 타입별로 갈리는 유일한 검사**다.

    - Reckon: `Args.params` 에 기댓값 필드가 있어야 한다 (`STR-CONTRACT-005`).
      없으면 기획 파일이 껍데기가 되고, 기획을 고쳐도 판정이 안 바뀌며,
      "같은 기획을 A/B 에 돌린다"가 성립하지 않는다. **형식 제한이 그 자리를 없앤다.**
    - Action: `Args.input` 타입 == 반환 타입이어야 한다 (`STR-CONTRACT-006`).
      Action 은 중간에서 **부작용만** 일으키고 데이터 변환은 하지 않는다.
    """
    raise NotImplementedError("Step 2에서 구현")


def check_tool_calls(contract: ScriptContract, tool: dict[str, object]) -> list[Finding]:
    """스크립트의 외부 도구 호출이 Spec `tool` 선언 안에 드는지 (**실행 시점**).

    `STR-TOOL-001` (함수명 미선언) / `-002` (실행파일 경로 미선언).

    **검사 강도는 얕다** — 함수 호출 형태 전체가 아니라 **함수명 + 그 인자로 적힌
    실행파일 경로**를 대조하는 정도다. 인자 전체를 검증하려 들면 strictler 가 외부
    도구의 API 를 알아야 하고, 그건 "외부 도구는 철저히 외부로 분리한다"를 깬다.
    """
    raise NotImplementedError("Step 2에서 구현")
