# GLOSSARY — 번역 일관성의 정본

> `schema.md` 2절 「출력 언어」가 확정한 대로, **CLI 가 내보내는 모든 문자열의 원문은 영어**이고
> 한글을 비롯한 다른 언어는 카탈로그(`<locale>.json`)로 얹는다.
> 이 파일은 **그 원문을 쓸 때와 카탈로그를 채울 때 쓰는 어휘를 고정한다.**
> 새 문자열을 쓰는 사람(실제로는 AI)은 여기 있는 단어를 그대로 쓰고, 없으면 여기 먼저 추가한다.

---

## 0. 번역 원칙 — 직역하지 마라

> 이 문장들의 **주 독자는 AI 다.** 목적은 *"돌리기 전에 잡아 자기 수정 신호를 주는 것"*
> (`schema.md` 6절). 그러니 **직역하지 말고, 영어에서도 그 목적을 하는 문장**으로 써라 —
> **무엇이 잘못됐는지 + 어디를 고치면 되는지**가 들어 있어야 한다.

이 원칙에서 따라 나오는 실무 규칙:

1. **고칠 자리를 이름으로 말한다.** "invalid configuration" 이 아니라
   `` `Args.state` `` / `` `transitions.to` `` / "the node JSON" 처럼 **파일과 필드**를 짚는다.
   AI 가 문장을 읽고 곧바로 열 파일이 정해져야 한다.
2. **왜 금지인지 한 줄을 붙인다.** 이유가 없으면 AI 는 우회로를 찾는다 —
   `` `dict` `` 금지에 "그러면 타입 계약이 무의미해진다"가 붙어야 dataclass 로 간다.
3. **슬롯은 원문과 정확히 같은 집합**이어야 한다. 하나라도 빠지면 렌더가 어긋나
   **규칙 id 가 출력에서 통째로 사라진다** — 실제로 겪은 사고다(MODULES.md R1-2/R1-3).
   `tests/test_locale.py` 가 이걸 강제한다.
4. **문장 부호는 영어 관습으로.** 원문 한글의 ` — ` 는 영어에서도 ` — ` 로 두되,
   `` ` `` 로 감싼 식별자는 **번역하지 않는다**(코드다).
5. **명령형으로 끝낸다.** "…should be…" 보다 "Declare …" / "Use …" 가 자기 수정에 낫다.

---

## 1. 이미 영어로 고정된 것 — 앵커. 바꾸지 마라

번역 대상이 아니다. 한글 카탈로그에서도 **그대로 영어로 남긴다.**

| 갈래 | 고정된 이름 |
|---|---|
| 결과 상태 | `pass` · `violation` · `not_run` · `error` |
| 노드 타입 | `Vantage` · `Sense` · `Perceive` · `Reckon` · `Action` |
| 산출물 타입 | `Scene` · `Sensum` · `Percept` · `Verdict` |
| 고정 심볼 | `Args` · `runNode` · `returnResult` · `params` · `state` · `input` |
| 층 | `Spec` · `Pipeline` · `Node` · `Script` · `Library` |

여기에 더해 **JSON 필드명·CLI 옵션·규칙 id 는 전부 코드**다 — 번역하지 않는다:
`inputs` · `states` · `when` · `transitions` · `targets` · `compare` · `report` · `config` ·
`libraries` · `source` · `plan` · `tool` · `--lang` · `--home` · `LNT-BAN-001` …

---

## 2. 결정한 번역 — 근거와 함께

`Vantage`/`Sense`/`Percept`/`Reckon` 처럼 이미 고정된 것 말고, **이번에 정해야 했던 것들**이다.
"제안"이 아니라 **확정**이다. 바꾸려면 이 표를 먼저 고친다.

### 2.1 기획 → **plan**

**근거.** 이 도구의 판정 근거 그 자체다(`CLAUDE.md` 「경계」의 *판정 근거 = 기획*).
후보는 `design` / `intent` / `spec` / `plan` 이었다.

- `design` — 영어에서 아키텍처를 뜻해 *"제품 기획"* 이 안 나온다. 탈락.
- `intent` — 이미 **규칙마다 붙는 필드 이름**이다(`schema.md`: 사람이 알아볼 의도(intent) 필드).
  개념과 필드가 같은 이름이면 갈린다. 탈락.
- `spec` — 뜻은 가장 가깝지만 **`Spec` 은 층 이름**이다(§1 앵커). 소문자/대문자로만 갈리는
  구분은 리포트에서 살아남지 못한다. 탈락.
- **`plan` 채택.** 남은 것 중 뜻이 가장 곧고, `CLAUDE.md` 의 *"기획대로 돌아가면 통과"* 가
  "behaves as planned" 로 자연스럽게 옮겨진다.

> ⚠ **충돌 주의.** `plan` 은 **Spec 의 필드 이름**이기도 하다(`"plan": [ … ]`).
> → **개념을 말할 때는 the plan / as planned 처럼 평문**으로, **필드를 말할 때는 반드시
> 코드 폰트 `` `plan` ``** 으로 쓴다. 한 문장 안에 둘이 같이 나오면 필드 쪽을
> `` the `plan` entries `` 처럼 풀어 쓴다.
> 규칙 문구에서는 대개 **구체적인 `Spec` 을 짚는 편이 낫다** — 예: "hard-coding it turns the
> `Spec` file into an empty shell" (기획 파일이 껍데기가 됩니다).

### 2.2 형상 → **shape**

**근거.** `CLAUDE.md` 가 이미 *"형상(shape)"* 이라고 병기해 두었다. 확인 도장만 찍는다.
lint 의 중간표현이 AST 인 것에 대응하는 자리이므로 `form`/`appearance` 로 흐리지 않는다.

### 2.3 등록소 → **registry**

**근거.** `~/.lintomata` 에 파일과 해시를 넣고 id 를 발급하는 곳. `store` 는 **모듈 이름**
(`store/entries.py`)이라 개념어로 쓰면 층이 겹친다. `repository` 는 git 을 연상시킨다.
→ `registry` 하나로 간다. 동사는 **register** / **registration**(등록 검사 = registration check).

### 2.4 배선 → **wiring** (동사 **wire**)

**근거.** 두 자리에서 같은 뜻으로 쓰인다 — 파이프라인의 `inputs` 연결, 노드의 `libraries` 슬롯.
`binding` 은 **상태 이름 매핑**(§2.10)에 이미 쓰고 싶은 말이고, `connection` 은 네트워크를
연상시킨다. → 남는 배선은 **an unused wiring**, 빠진 배선은 **not wired**.

### 2.5 계약 → **contract**

**근거.** 논쟁 없음. `ScriptContract` 라는 **클래스 이름이 이미 그렇다.**
input/output 타입·`need_state`·파라미터를 묶어 부르는 말이 계약이다.

### 2.6 능력 선언 / 사용 선언 → **capability declaration** / **usage declaration**

**근거.** `schema.md` 가 파일 경계와 겹쳐 놓은 구분이다 —
스크립트가 *"이거 허용해주세요"*(능력), 파이프라인·노드가 *"내 검사에선 이거 쓸겁니다"*(사용).
`provides`/`requires` 로 옮기면 **방향이 뒤집혀 보인다**(스크립트가 요구하는 쪽인데 provide 로 읽힌다).
→ 명사는 위 두 개, 문장에서는 **"the script declares the capability"** /
**"the node declares how it is used"** 로 푼다.

### 2.7 슬롯 → **slot** — 뜻이 **둘**이다. 문맥을 반드시 붙여라

| 어느 슬롯 | 영어 | 어디 |
|---|---|---|
| 규칙 문구의 `{id}` 자리 | **placeholder slot** (짧게 `placeholder`) | `rules.Rule.slots`, 카탈로그 검증 |
| `from lintomata_lib import x` 의 `x` | **library slot** | `LNT-LIB-001/002/005` |

**그냥 `slot` 이라고만 쓰지 마라.** 둘 다 "빠졌다/안 맞는다"로 실패하므로 문맥 없이는
AI 가 엉뚱한 파일을 연다. 규칙 문구 안에서는 대개 후자이므로 **`library slot`** 이라고 적는다.
(자리표시자 = **placeholder**.)

### 2.8 여파 → **fallout** (형용사구 **knocked out by**)

**근거.** `CLAUDE.md` 의 *"실패는 최대한 수집하고, 여파는 not run 이다"* — 앞단 실패 때문에
**도달 불가가 된 뒷단**을 가리킨다. `side effect` 는 Action 의 부작용에 이미 쓴다(§2.12).
`cascade`/`propagation` 은 *"실패가 전파된다"* 는 인상을 줘서, 이 도구가 일부러 피한
**"실패 전파"** 와 헷갈린다. → 명사 **fallout**, 문장은
**"reported as `not_run` — this is fallout from the failure above, not a failure of its own."**

### 2.9 도달 불가 → **unreachable**

**근거.** 이미 규칙 이름이 그렇다 — `state-unreachable`(`LNT-STATE-006`),
`node-unreachable`(`LNT-STATE-007`). 앵커로 굳힌다. 명사는 **reachability**
(모듈 이름도 `checks/reachability.py`).

### 2.10 상태 이름 매핑 → **state binding** / 전이 → **transition**

**근거.** 노드 어휘 → 파이프라인 상태 이름의 대응은 **값이 아니라 이름의 매핑**이라
`mapping` 으로도 되지만, `states` 필드가 *"바인딩"* 이라는 별개 층이라는 점을
`schema.md` 가 강조한다. → 매핑 행위는 **bind/binding**, 자료로서의 대응표는 **the `states` map**.
전이는 그냥 **transition** (`transitions` 필드와 같은 말).

### 2.11 노드 단위테스트 → **node unit test**

**근거.** 하네스가 하는 일이 문자 그대로 단위테스트다(`schema.md`: *"이 HTML 을 주면
버튼을 3개로 인식하는가"*). `case` 는 그 안의 한 항목(`cases[0]`)이므로 층이 다르다.
→ 파일은 **the node unit test file** (`<노드파일>.test.json`), 한 항목은 **a case**.

### 2.12 깨짐 → **broken**. 두 종류를 **절대 뭉치지 마라**

| 한글 | 영어 | `RegistryEntry.broken` 값 | 언제 |
|---|---|---|---|
| 참조 깨짐 | **broken reference** | `"ref"` | 참조 **대상이 삭제**됐다 (`LNT-REG-004`) |
| 검증 깨짐 | **broken validation** | `"validation"` | 참조 **대상이 수정**되어 상위 검증이 무효화됐다 (`LNT-REG-005`) |

**근거.** 고치는 방법이 정반대다 — 앞은 *대상을 다시 등록*, 뒤는 *이 요소를 고쳐 `update`*.
한 단어(`broken`)로 뭉뚱그리면 자기 수정 신호가 죽는다. 저장 필드 값이 `ref`/`validation` 이므로
영어 표기도 그 두 낱말을 그대로 얹는다.

### 2.13 그 밖 — 자주 나오는 것들

| 한글 | 영어 | 비고 |
|---|---|---|
| 기댓값 | **expected value** | `Reckon` 이 `params` 로 받는 것 |
| 자리표시자 | **placeholder** | §2.7 |
| 전개 (`${env.X}`) | **expansion** / **expand** | "after expansion" |
| 절대경로 | **absolute path** | 상대경로는 **relative path** |
| 진입점 | **entry point** | `runNode` |
| 금지 패턴 | **banned pattern** | 카테고리 `BAN` |
| 판정 (행위) | **decision** / **decide** | ⚠ 산출물 타입 `Verdict` 와 구분 |
| 통과 / 위반 | **pass** / **violation** | §1 앵커 |
| 대조쌍 | **contrast pair** | `LNT-TEST-006/007` |
| 부분집합 병합 | **subset merge** | `typesys` |
| 연결 성분 | **connected component** | 같은 곳 |
| 투명하다 (`Action`) | **transparent** | 타입 검사에서 통과시킨다는 뜻 |
| 정본 | **authoritative** / **the source of truth** | `node test <id>` 의 id 가 정본 |
| 부작용 | **side effect** | `Action` 전용. §2.8 과 구분 |
| 검사 시점 (`when`) | **check point** | N / LB / P / R / T |
| 하드코딩 | **hard-code** (동사), **hard-coded** | `Reckon` 기댓값 |
| 껍데기 | **an empty shell** | *"기획 파일이 껍데기가 된다"* |

---

## 3. 카탈로그를 채울 때

- **키는 영어 원문 문자열 그대로**다 (gettext 의 msgid). 키를 새로 발명하지 않는다 —
  원문을 고치면 키가 바뀌므로, 카탈로그도 같은 커밋에서 고친다.
- **슬롯 집합이 원문과 정확히 같아야 한다.** 순서는 달라도 되고(언어마다 어순이 다르다),
  **집합은 같아야 한다.** `tests/test_locale.py::test_catalogs_preserve_slot_sets` 가 강제한다.
- 카탈로그에 **없는 키는 조용히 영어 원문이 나간다.** 예외를 내지 않는다 —
  번역이 덜 됐다고 검사가 못 도는 것은 과하다.
- **`docs/rules.md` 의 guide 열은 `ko.json` 에서 인용한 것**이다. 원문이 둘이면 갈린다 →
  `tests/test_locale.py::test_rules_md_quotes_the_ko_catalog` 가 일치를 강제한다.
