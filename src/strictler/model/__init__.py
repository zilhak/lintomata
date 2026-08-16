"""네 층(Spec / Pipeline / Node / Script)의 JSON 구조를 그대로 옮긴 pydantic 데이터 모델.

`schema.md` 3·4·5·14절이 근거다. 이 모듈은 **JSON 문서의 형태만** 정의한다 —
값의 의미 검증(경로 규칙, 참조 무결성, 타입 계약, 도달 가능성)은 `strictler.checks.*` 가 한다.

⚠ 혼동 주의: 여기 쓰인 `X | None` / `dict[...]` 은 **엔진 자신의 코드**다.
`schema.md` 7절의 "`dict` 금지 / `Optional` 금지"는 **사용자가 작성하는 노드 스크립트의
타입 선언**에 적용되는 규칙이지 엔진 구현에 적용되는 규칙이 아니다.

모든 모델은 `extra="forbid"` 다. 스키마에 없는 키를 쓰면 로드 시점에 걸린다 —
작성 주체가 AI 이므로 오타가 조용히 무시되는 것보다 즉시 걸리는 편이 낫다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ENGINE_STATE_FIELDS",
    "EntryKind",
    "ID_PREFIXES",
    "NodeType",
    "PipelineKind",
    "STRICT",
    "SpecInfo",
    "ToolDecl",
    "PlanItem",
    "Spec",
    "PipelineInfo",
    "ConfigDecl",
    "States",
    "Transition",
    "When",
    "PipelineNode",
    "Pipeline",
    "NodeInfo",
    "Node",
    "TestCase",
    "NodeTest",
]


# ── 공통 어휘 ────────────────────────────────────────────────────────────────

EntryKind = Literal["script", "node", "pipeline", "spec"]
"""등록소가 다루는 네 종류 (`schema.md` 2절)."""

ID_PREFIXES: dict[str, EntryKind] = {
    "sc_": "script",
    "nd_": "node",
    "pl_": "pipeline",
    "sp_": "spec",
}
"""자동 발급 id 의 접두 → 종류. **종류는 id 접두가 말해준다** (`schema.md` 2절)."""

NodeType = Literal["vantage", "sense", "perceive", "reckon", "action"]
"""다섯 노드 타입 (`schema.md` 5절). 노드 파일의 `type` 필드."""

PipelineKind = Literal["verify", "compare"]
"""파이프라인 종류 (`schema.md` 4절). `plan` 항목의 필수 필드가 이것에 따라 갈리므로
로드 시점에 가장 먼저 알아야 한다 — 그래서 `info` 최상위에 있다."""

STRICT = ConfigDict(extra="forbid")
"""모든 스키마 모델 공통 설정. 선언되지 않은 키는 오류."""

ENGINE_STATE_FIELDS: frozenset[str] = frozenset({"__startedAt"})
"""엔진이 자동으로 채워주는 `Args.state` 필드 (`schema.md` 8절).

`__` 접두는 엔진 예약이라 사용자가 `Args.state` 에 선언할 수 없고(`STR-STATE-001`),
그래서 **선언 없이 읽어도 `STR-BAN-004` 가 아니다.**

★ **정본은 여기 하나다.** `engine/state.py`(`ENGINE_FIELDS`) · `refs.py` · `checks/script.py`
셋이 여기서 가져다 쓴다. 복제해 두면 엔진 제공 필드가 늘 때 `STR-BAN-004` 오탐이 난다.
`model` 은 최하층이라 세 곳 어디서 import 해도 순환이 없다."""


# ── Spec (`schema.md` 3절) ───────────────────────────────────────────────────


class SpecInfo(BaseModel):
    """Spec 의 메타. 단위테스트의 `describe` 에 해당한다."""

    model_config = STRICT

    description: str
    """이 파일이 무엇을 검사하는지."""

    version: str = ""


class ToolDecl(BaseModel):
    """외부 도구 하나의 선언 — **경로 + 허용 함수** (`schema.md` 6절).

    검사 강도는 얕다: 함수 호출 형태 전체가 아니라 **함수명 + 그 인자로 적힌
    실행파일 경로**를 대조하는 정도다. 인자 전체를 검증하려 들면 strictler 가
    외부 도구의 API 를 알아야 하고, 그건 "외부 도구는 철저히 외부로 분리한다"를 깬다.
    """

    model_config = STRICT

    path: str
    """실행파일 절대경로. 경로 규칙(`~`·`${env.X}` 전개 후 절대경로) 적용."""

    functions: list[str] = Field(default_factory=list)
    """스크립트가 호출해도 되는 함수명 목록. 여기 없는 함수를 부르면 `STR-TOOL-001`."""


class PlanItem(BaseModel):
    """`plan` 의 항목 하나 = 파이프라인 한 벌의 사용 선언. 단위테스트의 `it`.

    **무조건 파이프라인 참조다. 인라인 금지** (`schema.md` 3절).
    """

    model_config = STRICT

    source: str
    """파이프라인 파일 경로 또는 `${ref.pl_...}`. 경로 규칙 적용."""

    description: str
    """이 항목이 뭘 하려는 건지 — 항목별 의도."""

    config: dict[str, Any] = Field(default_factory=dict)
    """파이프라인이 선언한 config 변수들의 값.

    `kind: compare` 인 파이프라인이면 `targets` 키 아래에 target 별 값이 들어간다
    (`schema.md` 12절). target `T` 로 도는 동안 `${config.X}` 는 `targets.T` 에서
    먼저 찾고, 없으면 공통에서 찾는다.
    """

    report: str | None = None
    """비교 리포트 출력 위치. **`kind: compare` 인 파이프라인을 참조하면 필수**
    (`STR-CMP-001`). 값 검증 파이프라인에는 없다."""


class Spec(BaseModel):
    """기획 층 — 어떤 파이프라인을 쓰는지 + 무엇을 보장하는지 (`schema.md` 3절)."""

    model_config = STRICT

    info: SpecInfo
    tool: dict[str, ToolDecl] = Field(default_factory=dict)
    """외부 도구 호출 경로 전체. 키는 도구 이름."""

    plan: list[PlanItem]


# ── Pipeline (`schema.md` 4절) ───────────────────────────────────────────────


class PipelineInfo(BaseModel):
    """파이프라인의 자기 설명."""

    model_config = STRICT

    name: str
    description: str
    kind: PipelineKind


class ConfigDecl(BaseModel):
    """config 변수 하나의 **선언**. 파이프라인이 선언하고 Spec 이 값을 채운다.

    `description` 은 AI 가 Spec 을 쓸 때 읽는 설명이다.
    """

    model_config = STRICT

    type: str
    """`schema.md` 7절의 primitive 어휘와 같은 집합 — `str` `int` `float` `bool`
    `bytes` `list[T]`. 타입 어휘를 두 벌 두지 않는다. 허용 집합 밖이면 `STR-TYPE-005`.
    (`list[T]` 처럼 매개변수를 갖는 표기가 있어 Literal 이 아니라 `str` 이고,
    어휘 검증은 `strictler.typesys.primitives` 가 한다)"""

    required: bool
    default: Any = None
    """`required: false` 일 때 Spec 이 안 채우면 쓰이는 값."""

    description: str = ""

    path: bool = False
    """**타입이 아니라 검증 속성이다.** 경로냐 아니냐는 값의 타입이 아니라
    경로 규칙(절대경로·환경변수 전개)을 적용할지의 문제이므로 별도 플래그다.
    어기면 `STR-PATH-004`."""


class States(BaseModel):
    """파이프라인의 상태 집합과 초기값 (`schema.md` 8절)."""

    model_config = STRICT

    values: list[str]
    """사용자 정의 상태 이름들. `__` 접두 금지 (`STR-STATE-001`) — 엔진 제공 필드 전용."""

    initial: str


class Transition(BaseModel):
    """전이 규칙 하나. **런타임이 수행한다** — 노드는 상태를 읽기만 한다.

    **`transitions` 는 시간만 다룬다.** 노드 결과에 따른 분기 문법은 존재하지 않는다
    (`schema.md` 10절 — 이건 lint 다).
    """

    model_config = STRICT

    after: str
    """이 노드 id 가 끝나면."""

    to: str
    """이 상태로. `states.values` 에 있어야 한다 (`STR-STATE-005`)."""

    delay: int | str | None = None
    """전이까지의 지연(밀리초). `${config.settleMs}` 같은 참조가 올 수 있어 `str` 도 받는다."""


class When(BaseModel):
    """노드의 실행 조건. **노드 자기 어휘로 쓴다** — 파이프라인 상태 이름을 몰라도 된다."""

    model_config = STRICT

    state: str
    """스크립트가 `Args.state` 에 선언한 필드 이름 (`STR-STATE-004`)."""


class PipelineNode(BaseModel):
    """파이프라인 안의 노드 항목 — **노드 참조 + 배선**.

    **`inputs` 가 DAG 를 만든다.** 별도 `edges` 섹션이 없다 — 입력 참조가 곧 의존 관계다.
    **`type` 은 여기 없다.** 노드의 성질이지 사용처의 성질이 아니므로 노드 파일에 있다.
    """

    model_config = STRICT

    id: str
    """DAG 에서 참조되는 이름."""

    source: str
    """노드 파일 경로 또는 `${ref.nd_...}`. 경로 규칙 적용."""

    inputs: dict[str, str] = Field(default_factory=dict)
    """이름 붙은 다중 입력. `{스크립트가 받을 이름: 앞단 노드 id}`."""

    params: dict[str, Any] = Field(default_factory=dict)
    """스크립트에 넘길 값. `${config.X}` 참조로 기댓값을 주입한다."""

    states: dict[str, str] = Field(default_factory=dict)
    """`{노드 어휘: 파이프라인 상태 이름}` 매핑. 노드 재사용의 핵심."""

    when: When | None = None
    """실행 조건. 없으면 조건 없이 실행된다."""


class Pipeline(BaseModel):
    """DAG 구성 층 (`schema.md` 4절). Tekton 의 `Task` 자리."""

    model_config = STRICT

    info: PipelineInfo
    config: dict[str, ConfigDecl] = Field(default_factory=dict)
    states: States
    transitions: list[Transition] = Field(default_factory=list)
    nodes: list[PipelineNode]

    targets: list[str] = Field(default_factory=list)
    """**`kind: compare` 전용** (`schema.md` 12절). 비교 대상 이름 목록.
    개수 제한이 없다 — 둘도 되고 열도 된다. 단 2개 미만이면 `STR-CMP-003`."""

    compare: list[str] = Field(default_factory=list)
    """**`kind: compare` 전용.** 어느 노드의 출력을 target 간에 비교하는지.
    비교는 `Percept` 층에서 한다 — `Sensum` 은 비교 대상이 아니다."""


# ── Node (`schema.md` 5절) ───────────────────────────────────────────────────


class NodeInfo(BaseModel):
    """노드의 자기 설명."""

    model_config = STRICT

    name: str
    description: str


class Node(BaseModel):
    """동작 정의 층 (`schema.md` 5절). Tekton 의 `Step` 자리.

    ⚠ **노드 파일이 작은 것은 설계다.** 역할에 따라 분리한 결과이지 빈 자리가 아니다.
    """

    model_config = STRICT

    info: NodeInfo

    type: NodeType
    """타입별 스크립트 검사기는 **이 값을 보고** 그 스크립트를 검증한다."""

    script: str
    """스크립트 파일 경로 또는 `${ref.sc_...}`. `${config.X}` 도 올 수 있다 —
    비교 파이프라인에서 target 별로 스크립트가 갈리는 자리 (`schema.md` 12절)."""


# ── Node 단위테스트 (`schema.md` 14절) ───────────────────────────────────────


class TestCase(BaseModel):
    """단위테스트 케이스 하나.

    `expect` 를 안 써도 **타입 검증은 공짜로 따라온다** — 그게 "기본 제공"의 의미다.
    입력 fixture 는 어느 쪽이든 필요하다. 안 주면 돌릴 수가 없다.
    """

    model_config = STRICT

    name: str

    args: dict[str, Any]
    """**`Args` dataclass 를 JSON 으로 그대로 쓴 것.** 별도 문법이 없다 —
    dataclass 필드가 primitive + 중첩 dataclass + `list[T]` 뿐이라 JSON 으로 정확히 표현된다.
    `bytes` 필드만 예외로 `{"$file": "<절대경로>"}` 로 준다 (경로 규칙 적용)."""

    expect: dict[str, Any] | None = None
    """출력 dataclass 를 JSON 으로 쓴 것. 생략하면 타입만 본다."""


class NodeTest(BaseModel):
    """`<노드파일>.test.json` 의 구조.

    노드 파일을 두껍게 하지 않으므로 별도 파일이다.
    """

    model_config = STRICT

    node: str
    """검사 대상 노드 파일 경로 또는 `${ref.nd_...}`."""

    cases: list[TestCase]
