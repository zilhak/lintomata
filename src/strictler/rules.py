"""검사 규칙 테이블 — `STR-<CATEGORY>-<NNN>`.

`rules.md` 전체가 근거다. 규칙 64개 (PATH 4 / REF 7 / GRAPH 3 / TYPE 7 /
CONTRACT 7 / STATE 7 / BAN 4 / DEP 3 / TOOL 2 / CONFIG 3 / CMP 4 / TEST 8 / REG 5).
**늘어나는 것이 전제다** — 카테고리별 독립 번호 공간, 번호 재사용 금지,
폐기해도 `status: deprecated` 로 남긴다.

**`guide` 는 별도 필드로 리포트에 나가지 않는다.** 에러 메시지 뒤에 이어붙는다
(`schema.md` 11절). 정적 검사가 못 잡는 것을 메우는 자리이므로,
그 문구가 곧 AI 자기 수정 루프의 성능이다.

**자리표시자는 `message` 와 `guide` 양쪽에 올 수 있다.** `rules.md` 2절의 guide 문구
자체가 `{cycle}` `{names}` `{exc}` 같은 슬롯을 갖고 있으므로 둘 다 채운다.
치환은 `str.format` 이 아니라 **`{식별자}` 형태만 골라 바꾸는 자체 치환기**다 —
guide 문구에 그대로 들어 있는 `${env.X}` `${ref.sc_...}` 같은 참조 문법을 건드리면 안 되기 때문.

**어떤 규칙이 어떤 슬롯을 요구하는지는 `Rule.slots` 에 데이터로 들어 있다.**
표로 따로 적어두면 코드와 문서가 갈라지므로 `message`+`guide` 에서 그대로 뽑는다.
`finding()`/`render()` 가 이걸로 누락을 검증한다 —
슬롯 값을 안 주면 조용히 넘어가지 않고 `StrictlerError` 다.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from strictler.errors import Finding, NotRunCause, Status, StrictlerError

__all__ = [
    "RuleWhen",
    "RuleStatus",
    "Rule",
    "RULES",
    "get_rule",
    "rules_for",
    "render",
    "finding",
]


RuleWhen = Literal["node-register", "pipeline-register", "run", "test", "list"]
"""규칙이 도는 시점. `rules.md` 2절의 `when` 열 —
N=노드 등록, P=파이프라인 등록, R=실행, T=단위테스트, 그리고 목록 표시 전용(REG-004/005)."""

RuleStatus = Literal["active", "deprecated"]


class Rule(BaseModel):
    """규칙 엔트리 하나 (`rules.md` 1절)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    """`STR-CONTRACT-001` 형태. 길지만 사람이 타이핑할 일이 없고, 읽는 주체가
    AI 이므로 자기 설명적인 쪽이 낫다."""

    name: str
    """사람이 읽는 이름 (`args-dataclass-missing`)."""

    since: str
    status: RuleStatus
    when: tuple[RuleWhen, ...]
    """한 규칙이 여러 시점에 돌 수 있다 (예: `STR-PATH-001` 은 N P R)."""

    message: str
    """`{file}` 같은 자리표시자를 포함한다."""

    guide: str
    """자연어 수정 가이드. 메시지 뒤에 이어붙어 나간다. 여기에도 자리표시자가 올 수 있다."""

    slots: tuple[str, ...]
    """이 규칙이 요구하는 자리표시자 이름들 — `message`+`guide` 등장 순서.

    **손으로 적는 필드가 아니라 `_rule()` 이 문구에서 뽑는다.** 표로 따로 두면
    코드와 문서가 갈라진다. 검사기는 이걸 보고 무엇을 채워야 하는지 알 수 있고,
    `render()`/`finding()` 은 이걸로 누락을 잡는다.

    ⚠ `STR-TYPE-004` 의 `in` 처럼 **파이썬 예약어인 슬롯**이 있다 —
    그래서 `finding()` 이 슬롯 값을 `fields` **딕셔너리**로 받는다.
    """


# `{name}` 처럼 **점 없는 식별자 하나**만 자리표시자로 본다.
# guide 문구에 그대로 들어 있는 `${env.X}` `${ref.sc_...}` 는 점이 있어 걸리지 않는다.
_SLOT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _slots_of(*templates: str) -> tuple[str, ...]:
    """문구들에서 자리표시자 이름을 등장 순서대로 뽑는다 (중복 제거)."""
    found: dict[str, None] = {}
    for template in templates:
        for name in _SLOT_RE.findall(template):
            found[name] = None
    return tuple(found)


# 시점 약어 — `rules.md` 2절 표의 `when` 열 그대로.
_N: RuleWhen = "node-register"
_P: RuleWhen = "pipeline-register"
_R: RuleWhen = "run"
_T: RuleWhen = "test"
_L: RuleWhen = "list"

_SINCE = "0.1.0"


def _rule(
    rule_id: str,
    name: str,
    when: tuple[RuleWhen, ...],
    message: str,
    guide: str,
) -> Rule:
    return Rule(
        id=rule_id,
        name=name,
        since=_SINCE,
        status="active",
        when=when,
        message=message,
        guide=guide,
        slots=_slots_of(message, guide),
    )


_TABLE: tuple[Rule, ...] = (
    # ── PATH — 경로 규칙 ────────────────────────────────────────────────
    _rule(
        "STR-PATH-001",
        "relative-path",
        (_N, _P, _R),
        "전개 후에도 절대경로가 아닙니다: {path}",
        "모든 경로는 절대경로여야 합니다. `~` 또는 `${env.X}` 를 쓰세요. "
        "cwd 에 의존하는 경로는 쓸 수 없습니다",
    ),
    _rule(
        "STR-PATH-002",
        "env-undefined",
        (_N, _P, _R),
        "참조한 환경변수가 정의돼 있지 않습니다: {name}",
        "`${env.X}` 가 가리키는 환경변수를 실행 환경에 정의하세요. "
        "머신·CI 마다 값이 달라도 되도록 경로를 환경변수로 뺀 것입니다",
    ),
    _rule(
        "STR-PATH-003",
        "env-value-relative",
        (_R,),
        "환경변수 `{name}` 의 값 자체가 상대경로입니다: {value}",
        "환경변수 값이 절대경로여야 합니다. `PROJECT_ROOT=./foo` 같은 값은 "
        "cwd 의존을 되살립니다",
    ),
    _rule(
        "STR-PATH-004",
        "config-path-invalid",
        (_R,),
        "`path: true` 로 선언된 config `{name}` 의 값이 경로 규칙을 어깁니다: {value}",
        "이 config 는 `path: true` 로 선언돼 경로 규칙이 적용됩니다. 절대경로를 넣으세요",
    ),
    # ── REF — 참조 무결성 ──────────────────────────────────────────────
    _rule(
        "STR-REF-001",
        "script-not-found",
        (_N,),
        "노드의 `script` 를 찾을 수 없습니다: {script}",
        "노드의 `script` 는 등록된 스크립트(`${ref.sc_...}`) 또는 "
        "실재하는 파일 경로여야 합니다",
    ),
    _rule(
        "STR-REF-002",
        "node-not-found",
        (_P,),
        "`source` 가 가리키는 노드를 찾을 수 없습니다: {source}",
        "`source` 는 등록된 노드(`${ref.nd_...}`) 또는 실재하는 노드 파일이어야 "
        "합니다 (파이프라인의 `source`, 노드 단위테스트의 `node` 등 노드를 "
        "가리키는 모든 자리)",
    ),
    _rule(
        "STR-REF-003",
        "input-node-unknown",
        (_P,),
        "`inputs` 가 이 파이프라인에 없는 노드 id 를 가리킵니다: {name}",
        "`inputs` 의 값은 같은 파이프라인 안의 노드 `id` 여야 합니다. "
        "노드 파일 경로가 아니라 `id` 입니다",
    ),
    _rule(
        "STR-REF-004",
        "transition-node-unknown",
        (_P,),
        "`transitions.after` 가 이 파이프라인에 없는 노드 id 입니다: {name}",
        "`transitions.after` 는 같은 파이프라인 안의 노드 `id` 여야 합니다",
    ),
    _rule(
        "STR-REF-005",
        "compare-node-unknown",
        (_P,),
        "`compare` 가 이 파이프라인에 없는 노드 id 를 가리킵니다: {name}",
        "`compare` 에는 이 파이프라인의 노드 `id` 만 적을 수 있습니다",
    ),
    _rule(
        "STR-REF-006",
        "malformed-reference",
        (_N, _P, _R),
        "참조 문법이 깨졌습니다 — 네임스페이스가 없거나, 모르는 네임스페이스거나, "
        "이름이 비었습니다: {ref}",
        "참조는 네임스페이스를 반드시 붙입니다 — `${env.X}` / `${config.X}` / "
        "`${state.X}` / `${ref.<id>}` 넷뿐입니다. 네임스페이스가 없으면 "
        '"미정의 환경변수인지 config 오타인지" 구분할 수 없어 에러가 뭉개집니다. '
        "문제의 참조: {ref}",
    ),
    _rule(
        "STR-REF-007",
        "unresolved-reference",
        (_N, _P, _R),
        "참조 문법은 정상인데 이 자리에 도달하기 전에 전개되지 않았습니다: {ref}",
        "이 자리에서는 모든 참조가 이미 풀려 있어야 합니다. 전개되지 않은 참조를 "
        '리터럴로 통과시키면 나중에 "파일 없음" 으로 원인이 뭉개집니다. '
        "`config` 선언에 빠진 값이 없는지, 전개 순서가 맞는지 확인하세요. "
        "문제의 참조: {ref}",
    ),
    # ── GRAPH — DAG 구조 ───────────────────────────────────────────────
    _rule(
        "STR-GRAPH-001",
        "cycle",
        (_P,),
        "DAG 에 순환이 있습니다.",
        "`inputs` 가 의존 관계를 만듭니다. 순환이 생기면 실행 순서가 정해지지 않습니다. "
        "순환 경로: {cycle}",
    ),
    _rule(
        "STR-GRAPH-002",
        "orphan-node",
        (_P,),
        "노드 `{name}` 은 어떤 노드도 참조하지 않고 자기도 아무것도 내놓지 않습니다.",
        "이 노드는 그래프에서 고립돼 있습니다. `inputs` 로 연결하거나, "
        "필요 없으면 제거하세요",
    ),
    _rule(
        "STR-GRAPH-003",
        "ambiguous-input",
        (_P,),
        "`inputs` 가 서로 다른 앞단 노드를 둘 이상 가리킵니다: {nodes}",
        "`Args.input` 은 필드 하나라 값도 하나만 받습니다. `inputs` 에 서로 다른 "
        "노드를 둘 이상 적으면 어느 것을 넣어야 할지 정할 수 없습니다. "
        "문제의 앞단: {nodes} — 앞단을 하나로 줄이거나, 둘을 합치는 노드를 사이에 두세요",
    ),
    # ── TYPE — 타입 시스템 ─────────────────────────────────────────────
    _rule(
        "STR-TYPE-001",
        "dict-forbidden",
        (_N,),
        "`dict` 를 타입으로 썼습니다. (파일: {file})",
        "복합 타입은 반드시 `dataclass` 로 선언하세요. `dict` 를 허용하면 "
        "타입 계약이 무의미해집니다",
    ),
    _rule(
        "STR-TYPE-002",
        "optional-forbidden",
        (_N,),
        "`Optional` / `None` 을 타입으로 썼습니다. (파일: {file})",
        "`Optional` 은 쓸 수 없습니다. 값이 없을 수 있는 필드는 선언하지 마세요 — "
        "`Args` 는 쓰는 필드만 선언합니다",
    ),
    _rule(
        "STR-TYPE-003",
        "unsupported-type",
        (_N,),
        "primitive 도 dataclass 도 아닌 타입을 썼습니다: {type} (파일: {file})",
        "쓸 수 있는 타입은 `int` `float` `str` `bool` `bytes` `list[T]` 와 "
        "`dataclass` 뿐입니다",
    ),
    _rule(
        "STR-TYPE-004",
        "io-mismatch",
        (_P,),
        "앞단 output 정의와 뒷단 input 정의가 다릅니다.",
        "배선된 두 노드의 타입 정의가 다릅니다. 그래프 검사는 **엄격한 동일성**을 "
        "요구합니다. 앞단: {out} / 뒷단: {in}",
    ),
    _rule(
        "STR-TYPE-005",
        "config-type-unknown",
        (_P,),
        "`config` 의 `type` 이 허용 집합에 없습니다: {type}",
        "`config` 의 `type` 은 스크립트와 같은 어휘를 씁니다 — "
        "`str` `int` `float` `bool` `bytes` `list[T]`",
    ),
    _rule(
        "STR-TYPE-006",
        "merge-field-conflict",
        (_N, _P),
        "부분집합 연결 성분을 합집합 낼 때 같은 필드명의 타입이 갈립니다: {field}",
        "병합 대상 {names} 에서 필드 `{field}` 의 타입이 갈립니다 ({types}). "
        "부분집합 관계인 dataclass 들은 하나의 큰 dataclass 로 합쳐지므로, "
        "같은 필드명은 같은 타입이어야 합니다. 개념이 다르면 필드명을 다르게 하세요",
    ),
    _rule(
        "STR-TYPE-007",
        "dataclass-cycle",
        (_N,),
        "dataclass 가 자기 자신을 (직접·간접으로) 참조합니다.",
        "`{cycle}` 이 순환 참조입니다. 타입은 중첩을 바닥부터 정규화하므로 "
        "재귀 타입을 선언할 수 없습니다. 트리 구조가 필요하면 `list[T]` 를 "
        "평평하게 펴서 부모 id 를 필드로 갖는 형태로 바꾸세요",
    ),
    # ── CONTRACT — 노드 계약 ───────────────────────────────────────────
    _rule(
        "STR-CONTRACT-001",
        "args-dataclass-missing",
        (_N,),
        "`Args` dataclass 가 선언돼 있지 않습니다. (파일: {file})",
        "모든 노드 스크립트는 `Args` 라는 이름의 dataclass 를 정의하고 "
        "`runNode(args: Args)` 형태여야 합니다",
    ),
    _rule(
        "STR-CONTRACT-002",
        "entrypoint-missing",
        (_N,),
        "진입점 `runNode` 가 없거나 형태가 다릅니다. (파일: {file})",
        "진입점 이름은 `runNode` 로 고정입니다. 인자는 하나이고 타입은 `Args` 여야 합니다",
    ),
    _rule(
        "STR-CONTRACT-003",
        "return-missing",
        (_N,),
        "`returnResult()` 로 dataclass 를 내보내지 않습니다 — 호출이 없거나 "
        "출력 타입이 dataclass 가 아닙니다(primitive·미확정). (파일: {file})",
        "출력은 `returnResult()` 로 내보냅니다. 반환 타입은 dataclass 이고 "
        "이름은 자유입니다 — 타입 동일성을 **구조로** 판정하므로 primitive 를 "
        "그대로 내보낼 수 없습니다",
    ),
    _rule(
        "STR-CONTRACT-004",
        "args-unknown-field",
        (_N,),
        "`Args` 에 `input`/`params`/`state` 외의 필드가 있습니다: {names}",
        "`Args` 는 `input` / `params` / `state` 세 필드만 가질 수 있습니다. "
        "쓰는 것만 선언하세요",
    ),
    _rule(
        "STR-CONTRACT-005",
        "reckon-expected-missing",
        (_N,),
        "Reckon 노드인데 `Args.params` 에 기댓값 필드가 없습니다. (파일: {file})",
        "Reckon 은 기댓값을 Spec 에서 받아야 합니다. 스크립트에 하드코딩하면 "
        "기획 파일이 껍데기가 됩니다. `Args.params` 에 기댓값 필드를 선언하세요",
    ),
    _rule(
        "STR-CONTRACT-006",
        "action-io-differ",
        (_N,),
        "Action 노드인데 input 타입과 output 타입이 다릅니다. (파일: {file})",
        "Action 은 데이터를 그대로 통과시킵니다. `Args.input` 타입과 반환 타입이 "
        "같아야 합니다. 변환이 필요하면 Perceive 를 쓰세요",
    ),
    _rule(
        "STR-CONTRACT-007",
        "reckon-verdict-missing",
        (_N,),
        "Reckon 노드인데 출력 dataclass 에 판정 필드 `passed: bool` 이 없습니다. "
        "(파일: {file})",
        "Reckon 은 **판정**을 내는 노드입니다 — 출력 dataclass 에 `passed: bool` "
        "필드가 있어야 엔진이 통과/위반을 가릅니다. 이게 없으면 실행할 때까지 "
        "아무도 모르고, 그때는 리포트가 아니라 오류가 납니다",
    ),
    # ── STATE — 상태·상태머신 ──────────────────────────────────────────
    _rule(
        "STR-STATE-001",
        "reserved-prefix",
        (_N, _P),
        "사용자 상태 이름에 `__` 접두를 썼습니다: {name}",
        "`__` 접두는 엔진 제공 필드 전용입니다 (`__startedAt` 등). 다른 이름을 쓰세요",
    ),
    _rule(
        "STR-STATE-002",
        "mapping-missing",
        (_P,),
        "노드가 요구하는 상태가 `states` 에 매핑되지 않았습니다.",
        "노드의 `Args.state` 필드마다 파이프라인 상태 이름을 매핑해야 합니다. "
        "누락: {names}",
    ),
    _rule(
        "STR-STATE-003",
        "mapped-state-unknown",
        (_P,),
        "매핑 대상이 `states.values` 에 없습니다: {name}",
        "매핑한 이름이 파이프라인 상태 집합에 없습니다. `states.values` 에 "
        "추가하거나 이름을 고치세요",
    ),
    _rule(
        "STR-STATE-004",
        "when-undeclared",
        (_P,),
        "`when` 이 스크립트가 선언하지 않은 상태를 참조합니다: {name}",
        "`when` 은 노드 자기 어휘로 씁니다. 그 이름이 스크립트의 `Args.state` 에 "
        "선언돼 있어야 합니다",
    ),
    _rule(
        "STR-STATE-005",
        "transition-state-unknown",
        (_P,),
        "`transitions.to` 가 `states.values` 에 없는 상태입니다: {name}",
        "`transitions.to` 는 `states.values` 에 있는 상태여야 합니다",
    ),
    _rule(
        "STR-STATE-006",
        "state-unreachable",
        (_P,),
        "`when` 이 참조하는 상태로 가는 transition 이 없습니다.",
        "노드 어휘 `{name}` 은 파이프라인 상태 `{mapped}` 에 매핑돼 있는데, "
        "그 상태로 가는 `transitions` 가 없어 노드가 영원히 실행되지 않습니다. "
        "전이를 추가하거나 `when` 을 지우세요 "
        "(전이를 적는 자리는 파이프라인 어휘 `{mapped}` 쪽입니다)",
    ),
    _rule(
        "STR-STATE-007",
        "node-unreachable",
        (_P,),
        "상태머신을 돌려보니 노드 `{name}` 에 도달할 수 없습니다.",
        "조건과 그래프를 함께 돌려본 결과 이 노드에 도달할 수 없습니다. "
        "`when` 상태가 이 노드의 입력이 끝나기 전에만 참인지 확인하세요",
    ),
    # ── BAN — 금지 패턴 ────────────────────────────────────────────────
    _rule(
        "STR-BAN-001",
        "time-dependency",
        (_N,),
        "시간에 따라 결과가 달라지는 함수를 썼습니다: {name} (파일: {file})",
        "스크립트 안에서 시간을 읽을 수 없습니다. 실행 시각이 필요하면 "
        "`Args.state.__startedAt` (epoch ms) 을 쓰세요",
    ),
    _rule(
        "STR-BAN-002",
        "randomness",
        (_N,),
        "랜덤을 썼습니다: {name} (파일: {file})",
        "랜덤은 전 노드 금지입니다. 같은 입력에 같은 결과가 나와야 리포트를 믿을 수 있습니다",
    ),
    _rule(
        "STR-BAN-003",
        "direct-subprocess",
        (_N,),
        "`subprocess` / `exec` 류를 직접 호출했습니다: {name} (파일: {file})",
        "임의 명령 실행은 금지입니다. 외부 도구가 필요하면 Spec 의 `tool` 에 "
        "경로와 허용 함수를 선언하고 그것을 쓰세요",
    ),
    _rule(
        "STR-BAN-004",
        "undeclared-state-access",
        (_N,),
        "`Args.state` 에 없는 상태를 참조했습니다: {name} (파일: {file})",
        "참조할 상태를 `Args.state` 에 미리 선언해야 합니다. 선언에 없는 것은 쓸 수 없습니다",
    ),
    # ── DEP — 스크립트 의존성 (PEP 723) ────────────────────────────────
    _rule(
        "STR-DEP-001",
        "dependency-missing",
        (_N,),
        "PEP 723 헤더에 선언한 패키지가 이 환경에 없습니다: {requirement} (파일: {file})",
        "노드 스크립트는 strictler 와 **같은 프로세스**에 로드되므로 `import` 가 "
        "strictler 가 설치된 환경에서 풀립니다. 격리 환경을 만들어 주지 않으니 "
        "그 환경에 함께 설치하세요: {install}",
    ),
    _rule(
        "STR-DEP-002",
        "dependency-header-malformed",
        (_N,),
        "PEP 723 헤더를 읽을 수 없습니다: {reason} (파일: {file})",
        "헤더는 `# /// script` 로 열고 `# ///` 로 닫으며, 사이의 각 줄은 `# ` 로 "
        "시작하는 TOML 입니다. `dependencies` 는 PEP 508 문자열의 배열입니다:\n"
        '  # /// script\n'
        '  # requires-python = ">=3.11"\n'
        '  # dependencies = ["selectolax>=0.3"]\n'
        "  # ///\n"
        "헤더가 아예 없어도 됩니다 — stdlib 만 쓰는 스크립트에는 필요 없습니다",
    ),
    _rule(
        "STR-DEP-003",
        "dependency-version-unsatisfied",
        (_N,),
        "설치된 버전이 선언한 요구를 만족하지 않습니다: {requirement} "
        "(설치된 것: {installed}) (파일: {file})",
        "환경에는 패키지가 한 벌만 깔립니다. 설치된 것을 요구에 맞추거나 "
        "({install}) 헤더의 요구를 실제로 쓰는 버전에 맞추세요",
    ),
    # ── TOOL — 외부 도구 ───────────────────────────────────────────────
    _rule(
        "STR-TOOL-001",
        "function-undeclared",
        (_R,),
        "Spec 의 `tool` 에 없는 함수를 호출했습니다: {name}",
        "외부 도구 호출은 Spec 의 `tool` 에 함수명을 선언해야 합니다",
    ),
    _rule(
        "STR-TOOL-002",
        "executable-undeclared",
        (_R,),
        "인자로 준 실행파일 경로가 `tool` 에 선언돼 있지 않습니다.",
        "함수에 넘긴 실행파일 경로가 `tool` 의 `path` 와 일치해야 합니다. 준 값: {path}",
    ),
    # ── CONFIG — config 선언과 채움 ────────────────────────────────────
    _rule(
        "STR-CONFIG-001",
        "required-missing",
        (_R,),
        "`required: true` 인 config 를 Spec 이 채우지 않았습니다.",
        "파이프라인이 요구하는 config 를 Spec 의 `plan` 항목에서 채우세요. 누락: {names}",
    ),
    _rule(
        "STR-CONFIG-002",
        "value-type-mismatch",
        (_R,),
        "config `{name}` 에 채운 값의 타입이 선언과 다릅니다.",
        "선언된 타입: {declared} / 준 값: {given}",
    ),
    _rule(
        "STR-CONFIG-003",
        "unknown-key",
        (_R,),
        "파이프라인이 선언하지 않은 config 를 채웠습니다: {name}",
        "파이프라인이 선언한 config 만 채울 수 있습니다. 오타이거나 "
        "파이프라인 쪽 선언이 빠진 것입니다",
    ),
    # ── CMP — 비교 파이프라인 ──────────────────────────────────────────
    _rule(
        "STR-CMP-001",
        "report-missing",
        (_R,),
        "`kind: compare` 인데 Spec 항목에 `report` 가 없습니다.",
        "비교 파이프라인은 결과를 실행과 동시에 쌓으므로 출력 위치가 필요합니다. "
        "`plan` 항목에 `report` 를 지정하세요",
    ),
    _rule(
        "STR-CMP-002",
        "target-type-differ",
        (_P, _R),
        "target 별 스크립트가 서로 다른 input/output/state 타입을 선언했습니다: {node}",
        "인식 스크립트는 target 마다 달라도 되지만, **input/output/state 타입은 "
        "노드에 귀속되어 공통**이어야 비교가 성립합니다. `params` 는 달라도 됩니다",
    ),
    _rule(
        "STR-CMP-003",
        "targets-too-few",
        (_P, _R),
        "`targets` 가 2개 미만입니다: {count}",
        "비교하려면 대상이 둘 이상이어야 합니다. 개수 상한은 없습니다",
    ),
    _rule(
        "STR-CMP-004",
        "target-config-missing",
        (_R,),
        "target 이 요구하는 config 가 `targets.<target>` 에도 공통에도 없습니다.",
        "`${config.X}` 는 `targets.<현재target>` 에서 먼저 찾고 없으면 공통에서 "
        "찾습니다. 둘 다 없습니다: {name}",
    ),
    # ── TEST — 노드 단위테스트 ─────────────────────────────────────────
    _rule(
        "STR-TEST-001",
        "fixture-type-mismatch",
        (_T,),
        "`args` fixture 가 스크립트의 `Args` 선언에 맞지 않습니다.",
        "**테스트 정의가 잘못됐습니다** (스크립트가 아니라). fixture 를 `Args` 선언에 맞추세요",
    ),
    _rule(
        "STR-TEST-002",
        "script-raised",
        (_T,),
        "`runNode` 가 예외를 냈습니다.",
        "스크립트가 예외로 끝났습니다: {exc}",
    ),
    _rule(
        "STR-TEST-003",
        "output-type-mismatch",
        (_T,),
        "반환값이 선언된 출력 타입에 맞지 않습니다.",
        "선언한 출력 타입과 실제 반환값이 다릅니다. 선언: {declared} / 실제: {actual}",
    ),
    _rule(
        "STR-TEST-004",
        "expect-mismatch",
        (_T,),
        "`expect` 와 실제 값이 다릅니다.",
        "기대: {expect} / 실제: {actual}",
    ),
    _rule(
        "STR-TEST-005",
        "action-not-transparent",
        (_T,),
        "Action 노드인데 반환값이 입력과 다릅니다.",
        "Action 은 데이터를 그대로 통과시켜야 합니다. 부작용만 일으키고 값은 건드리지 마세요",
    ),
    _rule(
        "STR-TEST-006",
        "reckon-no-contrast-pair",
        (_T,),
        "Reckon 테스트에 통과/위반 대조쌍이 없습니다.",
        "`input` 이 같고 `params` 만 다른 통과 케이스와 위반 케이스를 각각 두면 "
        "기댓값이 실제로 쓰이는지 검증됩니다",
    ),
    _rule(
        "STR-TEST-007",
        "reckon-expected-ignored",
        (_T,),
        "대조쌍의 판정이 같습니다.",
        "기댓값을 바꿨는데 판정이 안 바뀝니다 — 기댓값을 쓰지 않고 하드코딩하고 있습니다",
    ),
    _rule(
        "STR-TEST-008",
        "test-node-mismatch",
        (_R,),
        "단위테스트의 `node` 가 **요청한 노드와 다른 노드**를 가리킵니다.",
        "`strictler node test <id>` 로 부르면 **그 id 의 노드가 정본**입니다. "
        "테스트 정의의 `node` 가 다른 것을 가리키면 요청하지 않은 노드를 돌려 "
        "**거짓 리포트**가 됩니다. 요청: {requested} / "
        "테스트가 가리키는 것: {declared}",
    ),
    # ── REG — 등록소 ───────────────────────────────────────────────────
    _rule(
        "STR-REG-001",
        "hash-mismatch",
        (_R,),
        "등록소 파일의 해시가 등록 당시와 다릅니다: {id}",
        "등록된 파일이 검사를 거치지 않고 변경됐습니다. 삭제 후 재등록하세요",
    ),
    _rule(
        "STR-REG-002",
        "ref-not-found",
        (_P, _R),
        "참조가 등록소에 없습니다: {id}",
        "참조한 id 가 없습니다 (삭제됐거나 오타). `strictler list` 로 확인하세요: {id}",
    ),
    _rule(
        "STR-REG-003",
        "ref-kind-mismatch",
        (_N, _P),
        "참조의 접두가 그 자리가 요구하는 종류와 다릅니다.",
        "이 자리에는 {expected} 가 와야 합니다. 준 것: {given} "
        "(접두 `sc_`=스크립트 `nd_`=노드 `pl_`=파이프라인 `sp_`=Spec)",
    ),
    _rule(
        "STR-REG-004",
        "ref-broken",
        (_L,),
        "참조 대상이 삭제되어 구성이 깨졌습니다: {id}",
        "참조 대상이 삭제되어 구성이 깨졌습니다. 없어진 참조: {id}. "
        "대상을 다시 등록하고 이 요소의 참조를 새 id 로 고치세요",
    ),
    _rule(
        "STR-REG-005",
        "validation-broken",
        (_L,),
        "참조 대상이 수정되어 상위 검증이 더는 통과하지 않습니다: {id}",
        "참조 대상이 수정되어 이 구성의 검증이 무효화됐습니다. 실패한 규칙: {rule}. "
        "이 요소를 고쳐 다시 `update` 하세요",
    ),
)


RULES: dict[str, Rule] = {rule.id: rule for rule in _TABLE}
"""규칙 id → 규칙. `rules.md` 2절의 64개."""

if len(RULES) != len(_TABLE):  # pragma: no cover - 테이블 오타 방지용 자기 검증
    raise StrictlerError("규칙 테이블에 중복 id 가 있습니다")


def get_rule(rule_id: str) -> Rule:
    """규칙 하나를 꺼낸다. 없으면 `StrictlerError` — 도구 자신의 버그이므로 오류다."""
    try:
        return RULES[rule_id]
    except KeyError:
        raise StrictlerError(
            f"등록되지 않은 규칙 id 입니다: {rule_id!r}. "
            "규칙 id 는 `rules.md` 2절 테이블에 있는 것만 쓸 수 있습니다."
        ) from None


def rules_for(when: RuleWhen) -> list[Rule]:
    """그 시점에 도는 `active` 규칙들을 준다."""
    return [
        rule
        for rule in _TABLE
        if rule.status == "active" and when in rule.when
    ]


def _fill(template: str, fields: dict[str, object]) -> str:
    """`{식별자}` 자리표시자를 `fields` 로 치환한다. 누락 검증은 호출자가 이미 했다."""
    return _SLOT_RE.sub(lambda m: str(fields[m.group(1)]), template)


def _render(rule_id: str, fields: dict[str, object]) -> str:
    """`message` 를 채우고 뒤에 채워진 `guide` 를 이어붙인다.

    슬롯 값이 없으면 **조용히 넘어가지 않고 오류**다 — 리포트에 `{cycle}` 이
    그대로 새어나가면 그건 검사기의 버그이지 위반이 아니다.
    필요한 슬롯 전부를 `Rule.slots` 에서 알려준다.
    """
    rule = get_rule(rule_id)
    missing = [name for name in rule.slots if name not in fields]
    if missing:
        raise StrictlerError(
            f"규칙 {rule_id} 의 자리표시자 값이 주어지지 않았습니다: "
            f"{', '.join(missing)}. "
            f"이 규칙이 요구하는 자리표시자는 {', '.join(rule.slots)} 입니다 "
            "(`rules.Rule.slots`). 값은 `fields` 딕셔너리로 넘깁니다."
        )
    return f"{_fill(rule.message, fields)}\n{_fill(rule.guide, fields)}"


def render(rule_id: str, **fields: object) -> str:
    """규칙의 `message` 를 `fields` 로 채우고 **뒤에 `guide` 를 이어붙여** 준다.

    이것이 `Finding.message` 에 들어가는 최종 문자열이다 (`schema.md` 11절).

    **`guide` 의 슬롯도 같은 `fields` 로 채운다.** `rules.md` 2절의 guide 문구
    자체가 `{cycle}` `{names}` `{path}` 같은 슬롯을 직접 갖고 있고
    (`STR-GRAPH-001`·`STR-TOOL-002`·`STR-CONFIG-001`·`STR-TEST-002/003/004` 등은
    슬롯이 **guide 에만** 있다), 안 채우면 리포트에 `{cycle}` 이 그대로 샌다.
    `message` 와 `guide` 는 하나의 슬롯 공간을 공유한다 — 그것이 `Rule.slots` 다.

    `{in}` 처럼 파이썬 예약어인 슬롯은 `render(rule_id, **{"in": ...})` 로 넘긴다.
    `Finding` 을 만들 때는 `finding(..., fields={...})` 를 쓴다.
    """
    return _render(rule_id, dict(fields))


def finding(
    rule_id: str,
    *,
    status: Status = "error",
    path: str = "",
    node: str = "",
    cause: NotRunCause | None = None,
    fields: dict[str, object] | None = None,
) -> Finding:
    """규칙 id 로 `Finding` 하나를 만든다. 메시지는 규칙 문구에서 채워진다.

    검사기들이 가장 많이 쓰는 진입점이다.

    **슬롯 값은 `fields` 딕셔너리로만 넘긴다.** `**fields` 였을 때는 keyword-only
    파라미터 `path`/`node` 가 **동명 슬롯을 잡아먹어** `STR-PATH-001`(`{path}`)·
    `STR-TOOL-002`(`{path}`)·`STR-CMP-002`(`{node}`) 를 렌더할 방법이 아예 없었다.
    딕셔너리로 받으면 이름 충돌이 구조적으로 불가능하다.
    `{in}` 같은 파이썬 예약어 슬롯도 이 형태로만 넘길 수 있다.

    여기서 `path`/`node` 는 **`Finding` 이 가리키는 위치**이고,
    `fields["path"]`/`fields["node"]` 는 **규칙 문구의 슬롯**이다. 서로 다른 것이다.
    """
    return Finding(
        status=status,
        path=path,
        node=node,
        rule_id=rule_id,
        message=_render(rule_id, dict(fields or {})),
        cause=cause,
    )
