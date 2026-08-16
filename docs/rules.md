# lintomata 검사 규칙 — ID 체계와 초기 테이블

> `schema.md` 13·14절의 검증 항목에 1:1 로 붙는 규칙 테이블.
> **초기 세팅이며, 늘어나는 것이 전제다.**

---

## 1. ID 체계

```
LNT-<CATEGORY>-<NNN>
```

```
LNT-CONTRACT-003        길지만 사람이 타이핑할 일이 없다.
                        읽는 주체가 AI 이므로 자기 설명적인 쪽이 낫다.
```

### 카테고리

| 카테고리 | 무엇 |
|---|---|
| `PATH` | 경로 규칙 — 절대경로, 환경변수 전개 |
| `REF` | 참조 무결성 — 존재하지 않는 id·노드·파일 |
| `GRAPH` | DAG 구조 — 순환, 배선 |
| `TYPE` | 타입 시스템 — 허용 타입, input==output |
| `CONTRACT` | 노드 계약 — `Args`, `runNode`, `returnResult`, 타입별 형식 요구 |
| `STATE` | 상태·상태머신·도달 가능성 |
| `BAN` | 금지 패턴 — 시간·랜덤·직접 subprocess |
| `DEP` | 스크립트 의존성 — PEP 723 선언과 현재 환경 |
| `TOOL` | 외부 도구 선언 |
| `CONFIG` | config 선언과 채움 |
| `CMP` | 비교 파이프라인 |
| `TEST` | 노드 단위테스트 |
| `REG` | 등록소 — 해시, 깨진 참조 |
| `LIB` | 라이브러리 — 슬롯 배선, 한 층 제한 |

### 증가 정책 — 늘어나는 것이 전제다

**한 번에 모든 케이스를 잡을 수 없다.** 써 보면서 추가한다. 그래서:

1. **카테고리별 독립 번호 공간.** 새 규칙은 그 카테고리의 최대 번호 + 1
2. **번호를 재사용하지 않는다.** 폐기해도 `status: deprecated` 로 남기고 번호는 비워둔다 —
   과거 리포트·문서에 남은 ID 가 다른 규칙을 가리키게 되면 안 된다
3. **카테고리도 추가 가능하다.** 자기 설명적인 이름이라 새 카테고리가 자연스럽게 붙는다
4. **규칙마다 `since` 와 `status` 를 기록**한다

### 규칙 엔트리 형태

```jsonc
{
  "id":     "LNT-CONTRACT-001",
  "name":   "args-dataclass-missing",     // 사람이 읽는 이름
  "since":  "0.1.0",
  "status": "active",                     // active | deprecated
  "when":   "node-register",              // node-register | pipeline-register | run | test
  "message": "`Args` dataclass 가 선언돼 있지 않습니다. (파일: {file})",
  "guide":   "모든 노드 스크립트는 `Args` 라는 이름의 dataclass 를 정의하고 runNode(args: Args) 형태여야 합니다. 필요한 필드만 선언하세요 — input / params / state."
}
```

**`guide` 는 에러 메시지에 이어붙는다.** 별도 필드로 리포트에 나가지 않는다(`schema.md` 11절).
**정적 검사가 못 잡는 것을 메우는 자리**이므로, 문구가 곧 AI 자기 수정 루프의 성능이다.

---

## 2. 초기 규칙 테이블

`when` 열: **N** = 노드 등록, **LB** = 라이브러리 등록, **P** = 파이프라인 등록,
**R** = 실행, **T** = 단위테스트

**`LB` 가 `N` 과 별개인 이유**는 검사 대상이 다르기 때문이다 — 라이브러리에는
`runNode` 도 `Args` 도 없어 노드 계약 검사가 통째로 해당 없고, 대신 노드에는 없는
제한(중첩 금지·`dataclass` 금지)이 걸린다 (`schema.md` 6.5절).

### PATH — 경로 규칙

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-PATH-001` | relative-path | N P R | 전개 후 절대경로가 아니다 | 모든 경로는 절대경로여야 합니다. `~` 또는 `${env.X}` 를 쓰세요. cwd 에 의존하는 경로는 쓸 수 없습니다 |
| `LNT-PATH-002` | env-undefined | N P R | 참조한 환경변수가 정의돼 있지 않다 | `${env.X}` 가 가리키는 환경변수를 실행 환경에 정의하세요. 머신·CI 마다 값이 달라도 되도록 경로를 환경변수로 뺀 것입니다 |
| `LNT-PATH-003` | env-value-relative | R | 환경변수 값 자체가 상대경로다 | 환경변수 값이 절대경로여야 합니다. `PROJECT_ROOT=./foo` 같은 값은 cwd 의존을 되살립니다 |
| `LNT-PATH-004` | config-path-invalid | R | `path: true` 인 config 값이 경로 규칙을 어긴다 | 이 config 는 `path: true` 로 선언돼 경로 규칙이 적용됩니다. 절대경로를 넣으세요 |

### REF — 참조 무결성

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-REF-001` | script-not-found | N | 노드가 가리키는 파일이 없다 (`script` / `libraries` 공용) | 노드의 `script` 와 `libraries` 값은 등록된 것(`${ref.sc_...}` / `${ref.lb_...}`) 또는 실재하는 파일 경로여야 합니다 |
| `LNT-REF-002` | node-not-found | P | `source` 가 가리키는 노드가 없다 | `source` 는 등록된 노드(`${ref.nd_...}`) 또는 실재하는 노드 파일이어야 합니다 (파이프라인의 `source`, 노드 단위테스트의 `node` 등 노드를 가리키는 모든 자리) |
| `LNT-REF-003` | input-node-unknown | P | `inputs` 가 없는 노드 id 를 가리킨다 | `inputs` 의 값은 같은 파이프라인 안의 노드 `id` 여야 합니다. 노드 파일 경로가 아니라 `id` 입니다 |
| `LNT-REF-004` | transition-node-unknown | P | `transitions.after` 가 없는 노드 id 다 | `transitions.after` 는 같은 파이프라인 안의 노드 `id` 여야 합니다 |
| `LNT-REF-005` | compare-node-unknown | P | `compare` 가 없는 노드 id 를 가리킨다 | `compare` 에는 이 파이프라인의 노드 `id` 만 적을 수 있습니다 |
| `LNT-REF-006` | malformed-reference | N P R | 참조 문법이 깨졌다 — 네임스페이스가 없거나(`${X}`), 모르는 네임스페이스거나(`${vars.X}`), 이름이 비었다(`${env.}`) | 참조는 네임스페이스를 반드시 붙입니다 — `${env.X}` / `${config.X}` / `${state.X}` / `${ref.<id>}` 넷뿐입니다. 네임스페이스가 없으면 "미정의 환경변수인지 config 오타인지" 구분할 수 없어 에러가 뭉개집니다. 문제의 참조: {ref} |
| `LNT-REF-007` | unresolved-reference | N P R | 참조 문법은 정상인데 이 자리에 도달하기 전에 전개되지 않았다 (`${config.y}` 가 경로 해석까지 살아남음) | 이 자리에서는 모든 참조가 이미 풀려 있어야 합니다. 전개되지 않은 참조를 리터럴로 통과시키면 나중에 "파일 없음" 으로 원인이 뭉개집니다. `config` 선언에 빠진 값이 없는지, 전개 순서가 맞는지 확인하세요. 문제의 참조: {ref} |

### GRAPH — DAG 구조

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-GRAPH-001` | cycle | P | DAG 에 순환이 있다 | `inputs` 가 의존 관계를 만듭니다. 순환이 생기면 실행 순서가 정해지지 않습니다. 순환 경로: {cycle} |
| `LNT-GRAPH-002` | orphan-node | P | 어떤 노드도 참조하지 않고 자기도 아무것도 안 내놓는다 | 이 노드는 그래프에서 고립돼 있습니다. `inputs` 로 연결하거나, 필요 없으면 제거하세요 |
| `LNT-GRAPH-003` | ambiguous-input | P | `inputs` 가 **서로 다른 앞단 노드**를 둘 이상 가리킨다 | `Args.input` 은 필드 하나라 값도 하나만 받습니다. `inputs` 에 서로 다른 노드를 둘 이상 적으면 어느 것을 넣어야 할지 정할 수 없습니다. 문제의 앞단: {nodes} — 앞단을 하나로 줄이거나, 둘을 합치는 노드를 사이에 두세요 |

### TYPE — 타입 시스템

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-TYPE-001` | dict-forbidden | N | `dict` 를 타입으로 썼다 | 복합 타입은 반드시 `dataclass` 로 선언하세요. `dict` 를 허용하면 타입 계약이 무의미해집니다 |
| `LNT-TYPE-002` | optional-forbidden | N | `Optional` / `None` 을 썼다 | `Optional` 은 쓸 수 없습니다. 값이 없을 수 있는 필드는 선언하지 마세요 — `Args` 는 쓰는 필드만 선언합니다 |
| `LNT-TYPE-003` | unsupported-type | N | primitive·dataclass 가 아닌 타입을 썼다 | 쓸 수 있는 타입은 `int` `float` `str` `bool` `bytes` `list[T]` 와 `dataclass` 뿐입니다 |
| `LNT-TYPE-004` | io-mismatch | P | 앞단 output 정의와 뒷단 input 정의가 다르다 | 배선된 두 노드의 타입 정의가 다릅니다. 그래프 검사는 **엄격한 동일성**을 요구합니다. 앞단: {out} / 뒷단: {in} |
| `LNT-TYPE-005` | config-type-unknown | P | `config` 의 `type` 이 허용 집합에 없다 | `config` 의 `type` 은 스크립트와 같은 어휘를 씁니다 — `str` `int` `float` `bool` `bytes` `list[T]` |
| `LNT-TYPE-006` | merge-field-conflict | N P | 부분집합 연결 성분을 합집합 낼 때 **같은 필드명의 타입이 갈린다** | 병합 대상 {names} 에서 필드 `{field}` 의 타입이 갈립니다 ({types}). 부분집합 관계인 dataclass 들은 하나의 큰 dataclass 로 합쳐지므로, 같은 필드명은 같은 타입이어야 합니다. 개념이 다르면 필드명을 다르게 하세요 |
| `LNT-TYPE-007` | dataclass-cycle | N | dataclass 가 자기 자신을 (직접·간접으로) 참조한다 | `{cycle}` 이 순환 참조입니다. 타입은 중첩을 바닥부터 정규화하므로 재귀 타입을 선언할 수 없습니다. 트리 구조가 필요하면 `list[T]` 를 평평하게 펴서 부모 id 를 필드로 갖는 형태로 바꾸세요 |

### CONTRACT — 노드 계약

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-CONTRACT-001` | args-dataclass-missing | N | `Args` 가 선언돼 있지 않다 | 모든 노드 스크립트는 `Args` 라는 이름의 dataclass 를 정의하고 `runNode(args: Args)` 형태여야 합니다 |
| `LNT-CONTRACT-002` | entrypoint-missing | N | `runNode` 가 없거나 형태가 다르다 | 진입점 이름은 `runNode` 로 고정입니다. 인자는 하나이고 타입은 `Args` 여야 합니다 |
| `LNT-CONTRACT-003` | return-missing | N | `returnResult()` 를 호출하지 않는다 — **출력 타입이 dataclass 가 아닌 경우(primitive·미확정)도 포함** | 출력은 `returnResult()` 로 내보냅니다. 반환 타입은 dataclass 이고 이름은 자유입니다 — 타입 동일성을 **구조로** 판정하므로 primitive 를 그대로 내보낼 수 없습니다 |
| `LNT-CONTRACT-004` | args-unknown-field | N | `Args` 에 `input`/`params`/`state` 외의 필드가 있다 | `Args` 는 `input` / `params` / `state` 세 필드만 가질 수 있습니다. 쓰는 것만 선언하세요 |
| `LNT-CONTRACT-005` | reckon-expected-missing | N | Reckon 인데 `Args.params` 에 기댓값 필드가 없다 | Reckon 은 기댓값을 Spec 에서 받아야 합니다. 스크립트에 하드코딩하면 기획 파일이 껍데기가 됩니다. `Args.params` 에 기댓값 필드를 선언하세요 |
| `LNT-CONTRACT-006` | action-io-differ | N | Action 인데 input 타입과 output 타입이 다르다 | Action 은 데이터를 그대로 통과시킵니다. `Args.input` 타입과 반환 타입이 같아야 합니다. 변환이 필요하면 Perceive 를 쓰세요 |
| `LNT-CONTRACT-007` | reckon-verdict-missing | N | Reckon 의 출력 dataclass 에 판정 필드 `passed: bool` 이 없다 | Reckon 은 **판정**을 내는 노드입니다 — 출력 dataclass 에 `passed: bool` 필드가 있어야 엔진이 통과/위반을 가릅니다. 이게 없으면 실행할 때까지 아무도 모르고, 그때는 리포트가 아니라 오류가 납니다 |

### STATE — 상태·상태머신

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-STATE-001` | reserved-prefix | N P | 사용자 상태 이름에 `__` 접두를 썼다 | `__` 접두는 엔진 제공 필드 전용입니다 (`__startedAt` 등). 다른 이름을 쓰세요 |
| `LNT-STATE-002` | mapping-missing | P | 노드가 요구하는 상태가 `states` 에 매핑되지 않았다 | 노드의 `Args.state` 필드마다 파이프라인 상태 이름을 매핑해야 합니다. 누락: {names} |
| `LNT-STATE-003` | mapped-state-unknown | P | 매핑 대상이 `states.values` 에 없다 | 매핑한 이름이 파이프라인 상태 집합에 없습니다. `states.values` 에 추가하거나 이름을 고치세요 |
| `LNT-STATE-004` | when-undeclared | P | `when` 이 스크립트가 선언 안 한 상태를 참조한다 | `when` 은 노드 자기 어휘로 씁니다. 그 이름이 스크립트의 `Args.state` 에 선언돼 있어야 합니다 |
| `LNT-STATE-005` | transition-state-unknown | P | `transitions.to` 가 없는 상태다 | `transitions.to` 는 `states.values` 에 있는 상태여야 합니다 |
| `LNT-STATE-006` | state-unreachable | P | `when` 이 참조하는 상태로 가는 transition 이 없다 | 노드 어휘 `{name}` 은 파이프라인 상태 `{mapped}` 에 매핑돼 있는데, 그 상태로 가는 `transitions` 가 없어 노드가 영원히 실행되지 않습니다. 전이를 추가하거나 `when` 을 지우세요 (전이를 적는 자리는 파이프라인 어휘 `{mapped}` 쪽입니다) |
| `LNT-STATE-007` | node-unreachable | P | 상태머신을 돌려보니 도달할 수 없는 노드가 있다 | 조건과 그래프를 함께 돌려본 결과 이 노드에 도달할 수 없습니다. `when` 상태가 이 노드의 입력이 끝나기 전에만 참인지 확인하세요 |

**`LNT-STATE-006` / `-007` 이 핵심이다.** 도달 불가 노드는 실패도 not run 도 아니라
4상태 어디에도 안 들어간다 — **등록 자체를 막는다.**

### BAN — 금지 패턴

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-BAN-001` | time-dependency | N | 시간에 따라 결과가 달라지는 함수를 썼다 | 스크립트 안에서 시간을 읽을 수 없습니다. 실행 시각이 필요하면 `Args.state.__startedAt` (epoch ms) 을 쓰세요 |
| `LNT-BAN-002` | randomness | N | 랜덤을 썼다 | 랜덤은 전 노드 금지입니다. 같은 입력에 같은 결과가 나와야 리포트를 믿을 수 있습니다 |
| `LNT-BAN-003` | direct-subprocess | N | `subprocess` / `exec` 류를 직접 호출했다 | 임의 명령 실행은 금지입니다. 외부 도구가 필요하면 Spec 의 `tool` 에 경로와 허용 함수를 선언하고 그것을 쓰세요 |
| `LNT-BAN-004` | undeclared-state-access | N | `Args.state` 에 없는 상태를 참조했다 | 참조할 상태를 `Args.state` 에 미리 선언해야 합니다. 선언에 없는 것은 쓸 수 없습니다 |

⚠ **`__import__("ti"+"me")` 같은 우회는 잡히지 않는다.** 사전에 추측할 수 있는 행위만 막는다 —
그래서 이 카테고리의 `guide` 가 특히 중요하다.

### DEP — 스크립트 의존성 (PEP 723)

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-DEP-001` | dependency-missing | N | 헤더에 선언한 패키지가 **현재 환경에 없다** | 노드 스크립트는 lintomata 와 **같은 프로세스**에 로드되므로 `import` 가 lintomata 가 설치된 환경에서 풀립니다. 격리 환경을 만들어 주지 않으니 그 환경에 함께 설치하세요: {install} |
| `LNT-DEP-002` | dependency-header-malformed | N | **헤더 형식이 잘못됐다** (TOML 파싱 실패, `dependencies` 가 배열이 아님, PEP 508 이 아님, 블록 중복) | 헤더는 `# /// script` 로 열고 `# ///` 로 닫으며, 사이의 각 줄은 `# ` 로 시작하는 TOML 입니다. `dependencies` 는 PEP 508 문자열의 배열입니다. **헤더가 아예 없어도 됩니다** — stdlib 만 쓰는 스크립트에는 필요 없습니다 |
| `LNT-DEP-003` | dependency-version-unsatisfied | N | 패키지는 있는데 **설치된 버전이 선언한 요구를 만족하지 않는다** | 환경에는 패키지가 한 벌만 깔립니다. 설치된 것을 요구에 맞추거나 ({install}) 헤더의 요구를 실제로 쓰는 버전에 맞추세요 |

**헤더가 없는 것이 정상이다.** stdlib 만 쓰는 스크립트가 대부분이고, 그러면 검사할 것이 없다.

**셋 다 오류(`error`)다** — 위반이 아니다. 기획과 다른 것이 아니라 **도구가 못 도는 상태**다.

**충돌 검출을 따로 하지 않는다.** 환경에는 패키지가 한 벌만 깔리므로, 호환되지 않는 요구가
둘 있으면 반드시 한쪽이 `LNT-DEP-003` 에 걸린다. 등록소 전체를 훑어 충돌 쌍을 찾는 규칙은 없다.

### TOOL — 외부 도구

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-TOOL-001` | function-undeclared | R | `tool` 에 없는 함수를 호출했다 | 외부 도구 호출은 Spec 의 `tool` 에 함수명을 선언해야 합니다 |
| `LNT-TOOL-002` | executable-undeclared | R | 인자로 준 실행파일 경로가 `tool` 에 없다 | 함수에 넘긴 실행파일 경로가 `tool` 의 `path` 와 일치해야 합니다. 준 값: {path} |

### CONFIG — config 선언과 채움

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-CONFIG-001` | required-missing | R | `required: true` 인 config 를 Spec 이 안 채웠다 | 파이프라인이 요구하는 config 를 Spec 의 `plan` 항목에서 채우세요. 누락: {names} |
| `LNT-CONFIG-002` | value-type-mismatch | R | Spec 이 채운 값의 타입이 선언과 다르다 | 선언된 타입: {declared} / 준 값: {given} |
| `LNT-CONFIG-003` | unknown-key | R | 파이프라인이 선언하지 않은 config 를 채웠다 | 파이프라인이 선언한 config 만 채울 수 있습니다. 오타이거나 파이프라인 쪽 선언이 빠진 것입니다 |

### CMP — 비교 파이프라인

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-CMP-001` | report-missing | R | `kind: compare` 인데 Spec 항목에 `report` 가 없다 | 비교 파이프라인은 결과를 실행과 동시에 쌓으므로 출력 위치가 필요합니다. `plan` 항목에 `report` 를 지정하세요 |
| `LNT-CMP-002` | target-type-differ | P R | target 별 스크립트가 다른 input/output/state 타입을 선언했다 | 인식 스크립트는 target 마다 달라도 되지만, **input/output/state 타입은 노드에 귀속되어 공통**이어야 비교가 성립합니다. `params` 는 달라도 됩니다 |
| `LNT-CMP-003` | targets-too-few | P R | `targets` 가 2개 미만이다 | 비교하려면 대상이 둘 이상이어야 합니다. 개수 상한은 없습니다 |
| `LNT-CMP-004` | target-config-missing | R | target 이 요구하는 config 가 `targets.<name>` 에도 공통에도 없다 | `${config.X}` 는 `targets.<현재target>` 에서 먼저 찾고 없으면 공통에서 찾습니다. 둘 다 없습니다: {name} |

### TEST — 노드 단위테스트

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-TEST-001` | fixture-type-mismatch | T | `args` 가 스크립트의 `Args` 선언에 안 맞는다 | **테스트 정의가 잘못됐습니다** (스크립트가 아니라). fixture 를 `Args` 선언에 맞추세요 |
| `LNT-TEST-002` | script-raised | T | `runNode` 가 예외를 냈다 | 스크립트가 예외로 끝났습니다: {exc} |
| `LNT-TEST-003` | output-type-mismatch | T | 반환값이 선언된 출력 타입에 안 맞는다 | 선언한 출력 타입과 실제 반환값이 다릅니다. 선언: {declared} / 실제: {actual} |
| `LNT-TEST-004` | expect-mismatch | T | `expect` 와 실제 값이 다르다 | 기대: {expect} / 실제: {actual} |
| `LNT-TEST-005` | action-not-transparent | T | Action 인데 반환값이 입력과 다르다 | Action 은 데이터를 그대로 통과시켜야 합니다. 부작용만 일으키고 값은 건드리지 마세요 |
| `LNT-TEST-006` | reckon-no-contrast-pair | T | Reckon 테스트에 통과/위반 대조쌍이 없다 (**경고**) | `input` 이 같고 `params` 만 다른 통과 케이스와 위반 케이스를 각각 두면 기댓값이 실제로 쓰이는지 검증됩니다 |
| `LNT-TEST-007` | reckon-expected-ignored | T | 대조쌍의 판정이 같다 | 기댓값을 바꿨는데 판정이 안 바뀝니다 — 기댓값을 쓰지 않고 하드코딩하고 있습니다 |
| `LNT-TEST-008` | test-node-mismatch | R | 단위테스트의 `node` 가 **요청한 노드와 다른 노드**를 가리킨다 | `lintomata node test <id>` 로 부르면 **그 id 의 노드가 정본**입니다. 테스트 정의의 `node` 가 다른 것을 가리키면 요청하지 않은 노드를 돌려 **거짓 리포트**가 됩니다. 요청: {requested} / 테스트가 가리키는 것: {declared} |

### REG — 등록소

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-REG-001` | hash-mismatch | R | 등록소 파일의 해시가 등록 당시와 다르다 | 등록된 파일이 검사를 거치지 않고 변경됐습니다. 삭제 후 재등록하세요 |
| `LNT-REG-002` | ref-not-found | P R | `${ref.<id>}` 가 등록소에 없다 | 참조한 id 가 없습니다 (삭제됐거나 오타). `lintomata list` 로 확인하세요: {id} |
| `LNT-REG-003` | ref-kind-mismatch | N P | `${ref.<id>}` 의 접두가 그 자리가 요구하는 종류와 다르다 | 이 자리에는 {expected} 가 와야 합니다. 준 것: {given} (접두 `sc_`=스크립트 `nd_`=노드 `pl_`=파이프라인 `sp_`=Spec) |
| `LNT-REG-004` | ref-broken | — | **삭제**된 대상을 참조하는 상위가 있다 (**목록 표시**) | 참조 대상이 삭제되어 구성이 깨졌습니다. 없어진 참조: {id}. 대상을 다시 등록하고 이 요소의 참조를 새 id 로 고치세요 |
| `LNT-REG-005` | validation-broken | — | 참조 대상이 **수정**되어 상위 검증이 더는 통과하지 않는다 (**목록 표시**) | 참조 대상이 수정되어 이 구성의 검증이 무효화됐습니다. 실패한 규칙: {rule}. 이 요소를 고쳐 다시 `update` 하세요 |

**`LNT-REG-004` / `-005` 는 실패가 아니라 상태 표시다.**
삭제도 수정도 막지 않고 `lintomata <종류> list` 에서 깨짐을 드러낸다.

| 깨짐 | 원인 | 참조는 |
|---|---|---|
| **참조 깨짐** (`-004`) | 대상이 **삭제**됨 | 끊겼다 — 눈에 보인다 |
| **검증 깨짐** (`-005`) | 대상이 **수정**됨 | 멀쩡하다 — **조용히 무효화된 것을 드러내야 한다** |

**`-005` 를 잡으려면 수정 시 상위를 전이적으로 재검증해야 한다.**
`registry.json` 의 참조 그래프를 역방향으로 타고 올라간다 (`schema.md` 2절).

### LIB — 라이브러리 (`schema.md` 6.5절)

| ID | name | when | 잡는 것 | guide |
|---|---|---|---|---|
| `LNT-LIB-001` | library-slot-unwired | N | 스크립트가 요구하는 슬롯을 노드가 배선하지 않았다 | 스크립트의 `from lintomata_lib import <이름>` 은 **능력 선언**이고, 그 슬롯에 무엇을 쓸지는 **노드가** 정합니다. 노드 JSON 에 `"libraries": { "<이름>": "${ref.lb_...}" }` 를 넣으세요 — 절대경로(`${env.X}` 포함)도 됩니다. 배선이 빠진 슬롯: {names} |
| `LNT-LIB-002` | library-slot-unused | N | 노드가 배선했는데 스크립트가 쓰지 않는다 | 노드의 `libraries` 는 스크립트가 요구한 슬롯에만 답합니다. 쓰지 않는 배선은 참조 그래프만 넓혀 **라이브러리를 고칠 때 상관없는 노드까지 재검증**하게 만듭니다. 남는 배선: {names} |
| `LNT-LIB-003` | library-nested-import | LB | 라이브러리가 다른 라이브러리를 import 한다 | 라이브러리는 **한 층뿐**입니다 — 허용하면 그때부터 패키지 매니저를 만들게 됩니다. 그 함수를 이 파일 안에 두거나, 쓰는 쪽 스크립트가 두 슬롯을 각각 배선하세요 |
| `LNT-LIB-004` | library-dataclass-forbidden | LB | 라이브러리가 `dataclass` 를 선언했다 (**v1 제한**) | v1 의 라이브러리는 **함수만** 제공합니다. 계약 타입이 스크립트 밖에서 생기면 계약 추출이 파일 하나만 파싱하므로 타입 레지스트리에 구멍이 납니다. 그 dataclass 는 쓰는 쪽 **스크립트로 옮기세요** |
| `LNT-LIB-005` | library-import-form | N | 스크립트가 `lintomata_lib` 를 허용되지 않은 형태로 import 했다 | 허용되는 형태는 **모듈 최상단의 `from lintomata_lib import <이름>`** 하나뿐입니다. `import lintomata_lib` / `from lintomata_lib.<x> import y` / `import *` / 함수 안 import 는 **슬롯을 정적으로 뽑을 수 없어** 배선 검사가 무의미해집니다 |

**배선한 참조가 라이브러리가 아닌 경우(`${ref.sc_...}` 등)에는 새 규칙을 만들지 않았다** —
`LNT-REG-003`(자리와 접두 불일치)이 이미 그 자리이고, 고치는 법도 같다(접두를 맞춘다).

---

## 3. 규칙 수 요약

| 카테고리 | 초기 규칙 수 |
|---|---|
| PATH | 4 |
| REF | 7 |
| GRAPH | 3 |
| TYPE | 7 |
| CONTRACT | 7 |
| STATE | 7 |
| BAN | 4 |
| DEP | 3 |
| TOOL | 2 |
| CONFIG | 3 |
| CMP | 4 |
| TEST | 8 |
| REG | 5 |
| LIB | 5 |
| **합계** | **69** |

**이건 시작점이다.** 쓰다 보면 빠진 케이스가 나올 것이고, 그때 카테고리 끝에 번호를 붙여 추가한다.
번호는 재사용하지 않는다.

---

## 4. 증가 이력

**"늘어나는 것이 전제"** 라고 설계한 대로, 실제 구현 중 발견된 구멍을 규칙으로 추가한다.
번호는 재사용하지 않는다.

| 추가된 규칙 | 언제 | 왜 |
|---|---|---|
| `LNT-TYPE-006` merge-field-conflict | Step 1-a 리뷰 | `A(y:int)`, `B(x:int,y:int)`, `C(x:str,y:int)` — 셋 다 개별로는 적법한데 `A⊂B`, `A⊂C` 로 한 성분이 되면 합집합에 `x:int`/`x:str` 가 공존해 표현 불가. schema.md 7절 "연결 성분을 통째로 합집합 내면 모호함 자체가 생기지 않는다" 가 이 경우를 상정하지 않았다 |
| `LNT-TYPE-007` dataclass-cycle | Step 1-a 리뷰 | `N(kids: list[N])` 같은 재귀 타입. 중첩을 바닥부터 정규화하는 이상 거절이 필연이고 설계대로지만, 규칙 id 없이 raw 오류로 나가고 있었다 |
| `LNT-REF-006` malformed-reference | Step 1-c 리뷰 | 네임스페이스 없음/모름/이름 비었음. REF-001~005 는 전부 "대상을 못 찾음" 이라 이 종류를 담을 자리가 없었다 |

| `LNT-REF-007` unresolved-reference | Step 1-c 재리뷰 | R1-8 이 "잔여 `${` 를 에러로" 만 정하고 규칙 id 를 지정하지 않아 구현자가 `LNT-REF-006` 을 골랐다. 그런데 `${config.y}` 는 **문법이 정상**이다 — 잘못된 건 전개 순서다. `-006` 의 guide("네임스페이스를 반드시 붙입니다")를 받으면 AI 가 엉뚱한 곳을 고친다. **원인이 다르면 고치는 방법도 다르므로 규칙을 나눈다** |

| `LNT-CONTRACT-007` reckon-verdict-missing | Step 3-a 리뷰 | 엔진이 Reckon 출력에서 통과/위반을 읽으려면 **판정 필드 규약**이 필요한데 어느 문서에도 없었다. 구현자가 `passed: bool` 로 정하고 돌렸지만 **등록 시점 강제가 없어** 필드 없는 Reckon 이 등록을 통과하고 런타임에야 터진다 — schema.md 6절의 *"돌리기 전에 잡아 자기 수정 신호를 준다"* 와 정면으로 어긋난다 |

| `LNT-GRAPH-003` ambiguous-input | Step 5 E2E | **등록은 통과하고 실행에서 터졌다.** `Args.input` 이 필드 하나인 것은 스크립트 계약에 이미 있고 파이프라인 JSON 만 봐도 판정 가능한데 실행까지 미뤄졌고, 게다가 **규칙 id 없는 맨 `Finding`** 이라 리포트에서 기계적으로 특정할 수 없었다. schema.md 6절의 *"돌리기 전에 잡아 자기 수정 신호를 준다"* 에 정면으로 걸린다 |

| `LNT-TEST-008` test-node-mismatch | 최종 리뷰 | **`node test <id>` 가 요청한 노드가 아닌 다른 노드를 돌리고 `[pass]` 를 냈다** — lint 도구에서 가장 나쁜 **거짓 리포트**다. id 로 경로만 찾고, 그 파일의 `node` 필드로 노드를 *다시* 해석하는데 둘이 일치하는지 아무도 안 봤다 |

| `LNT-DEP-001` `-002` `-003` (**카테고리 신설**) | 의존성 모델 확정 후 | `schema.md` 6절이 *"엔진은 헤더를 읽어 등록 시점에 `import` 가능한지 확인하고, 안 되면 규칙으로 잡아 설치 명령을 안내한다"* 로 확정했는데 **그 규칙이 없었다.** 격리를 하지 않기로 한 이상(스크립트는 lintomata 와 같은 환경에서 `import` 가 풀린다) 선언과 현재 환경이 어긋나면 **실행 시점에 `ModuleNotFoundError` 로 터진다** — schema.md 6절의 *"돌리기 전에 잡아 자기 수정 신호를 준다"* 에 걸린다 |

**`LNT-DEP` 를 셋으로 나눈 근거는 `LNT-REF-007` 과 같다 — 고치는 방법이 셋 다 다르다.**
증상은 전부 *"선언한 의존성이 지금 환경과 안 맞는다"* 하나로 보이지만, AI 가 해야 할 일은 갈린다:

| 규칙 | 고치는 곳 | 고치는 법 |
|---|---|---|
| `-001` 없다 | **환경** | 설치한다 (`uv tool install lintomata --with '...'`) |
| `-002` 형식이 틀렸다 | **헤더** | 헤더를 고친다 — 설치할 것이 없다 |
| `-003` 버전이 안 맞는다 | **환경 또는 헤더** | 버전을 맞추거나 요구를 고친다 — **둘 중 어느 쪽이 옳은지는 사람이 안다** |

하나로 합쳤다면 `-002`(설치할 것이 없는데) 에도 설치 명령이 붙어 AI 를 엉뚱한 수정으로 유도한다.
**규칙을 나누는 기준은 "증상" 이 아니라 "고치는 방법"** 이라는 기준을 그대로 적용한 것이다.

**충돌 검출은 규칙으로 만들지 않았다.** 환경에는 패키지가 한 벌만 깔리므로 호환 불가 요구가
둘 있으면 반드시 한쪽이 `-003` 에 걸린다 — 등록소 전체를 훑는 별도 검사는 같은 사실을 두 번 본다.

**앞 셋은 "규칙 id 없는 raw 오류로 나가던 것에 id 를 붙인 것"** 이다.
id 가 없으면 리포트에서 원인을 특정할 수 없고, 가이드 문구를 붙일 자리도 없다.

### 문구·검사시점 개정 (Step 2 리뷰)

규칙을 늘리지 않고 기존 규칙을 고친 것들이다. **번호는 그대로다.**

| 규칙 | 무엇을 고쳤나 | 왜 |
|---|---|---|
| `LNT-STATE-006` | 슬롯 `{name}` 하나 → **`{name}`(노드 어휘) + `{mapped}`(파이프라인 상태)** | 노드는 자기 어휘로 상태를 선언하고 파이프라인이 매핑을 갖는다(schema.md 8절). 한 이름만 보이면 **JSON 의 어느 자리를 고쳐야 하는지가 안 드러난다** — `when` 에 적힌 것과 전이를 추가할 자리가 다른 층이다 |
| `LNT-CMP-002` `-003` | when `P` → **`P R`** | target 별 스크립트는 **Spec 의 `config` 가 채우므로 파이프라인 등록 시점엔 알 수 없다.** 등록 시점 판정만 두면 비교 파이프라인에서 이 규칙이 영영 안 돈다. schema.md 13절의 세 번째 검사 시점(Spec 실행)이 제자리다 |
| `LNT-CONTRACT-003` | "`returnResult()` 미호출" → **출력 타입이 dataclass 가 아닌 경우 포함** | guide 는 이미 "반환 타입은 dataclass" 라고 말하는데 **강제하는 규칙이 없었다.** 타입 동일성을 구조로 판정하는 이상 primitive 출력은 성립하지 않는다 |

**규칙을 새로 파지 않고 기존 것을 고친 기준:** 원인이 같고 **고치는 방법도 같으면** 같은 규칙이다.
`LNT-CONTRACT-003` 의 두 경우(미호출 / dataclass 아님)는 둘 다 "`returnResult()` 로 dataclass 를 내보내라" 로 고친다.

**`LNT-REF-007` 은 성격이 다르다** — id 가 있긴 했는데 **틀린 id** 였다.
guide 가 AI 를 엉뚱한 수정으로 유도하면 "에러 메시지에 자연어 가이드를 넣는다" 는 설계 의도가 역효과를 낸다.
**규칙을 나누는 기준은 "증상" 이 아니라 "고치는 방법"** 이다.

### `LNT-LIB` — 라이브러리 (**카테고리 신설**, 64 → 69)

**등록 종류 `library` 를 신설하면서 함께 붙였다** (`schema.md` 6.5절). 다섯으로 나눈 기준은
언제나처럼 **증상이 아니라 고치는 방법**이다 — 다섯 다 고치는 파일도 고치는 줄도 다르다:

| 규칙 | 고치는 곳 | 고치는 법 |
|---|---|---|
| `-001` 슬롯 미배선 | **노드 JSON** | `libraries` 에 배선을 넣는다 |
| `-002` 안 쓰는 배선 | **노드 JSON** | 그 배선을 뺀다 (또는 스크립트에서 쓴다) |
| `-003` 라이브러리 중첩 | **라이브러리** | 그 import 를 없앤다 — 한 층만 |
| `-004` 라이브러리의 dataclass | **라이브러리 → 스크립트** | 타입 선언을 쓰는 쪽으로 옮긴다 (v1 제한) |
| `-005` import 형태 | **스크립트** | `from lintomata_lib import <이름>` 으로 고친다 |

`-001` 과 `-002` 를 하나로 묶으면 *"배선이 안 맞습니다"* 가 되는데, **넣어야 할 때와 빼야 할 때에
같은 문구가 나간다.** `-003` 과 `-005` 도 마찬가지다 — 전자는 import 자체가 잘못이고
후자는 import 는 맞는데 형태만 틀렸다.

**새 규칙을 만들지 **않은** 것 둘:**

- **배선한 참조가 라이브러리가 아니다** (`${ref.sc_...}` 를 `libraries` 에 썼다)
  → `LNT-REG-003`(자리와 접두 불일치)이 이미 그 자리다. 고치는 법도 같다.
- **배선한 라이브러리 파일이 없다** → `LNT-REF-001`. 아래 문구 개정 참조.

`when` 에 **`LB`(라이브러리 등록)** 시점이 새로 생겼다 — 라이브러리에는 `runNode` 도 `Args` 도
없어 노드 계약 검사가 통째로 해당 없고, 대신 노드에는 없는 제한이 걸리므로 같은 시점이 아니다.

### 문구 개정 (library 신설)

| 규칙 | 무엇을 고쳤나 | 왜 |
|---|---|---|
| `LNT-REF-001` | *"노드의 `script` 를 찾을 수 없다"* → **`script`/`libraries` 자리 공용** | 노드가 가리키는 파일이 없다는 사실은 두 자리에서 똑같이 난다. `libraries` 에서 나는데 guide 가 `script` 만 말하면 **AI 가 엉뚱한 줄을 고친다** — R6-6 이 `LNT-REF-002` 에 한 것과 같은 처치다 |
| `LNT-REG-003` | 접두 목록에 **`lb_`=라이브러리** 추가 | 종류가 다섯이 됐는데 넷만 열거하면, 라이브러리 자리를 틀린 AI 에게 **선택지에 없는 것**을 고르라고 하는 꼴이다 |
