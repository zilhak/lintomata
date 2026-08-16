# 저작 가이드 — 검사를 하나 만들어 돌리기까지

**이 문서의 독자는 AI 다.** lintomata 는 기획 데이터도 노드 스크립트도 AI 가 쓴다는 전제로
설계됐다 — 사람은 전문을 읽지 않고 AI 가 요약한 의도를 읽고 승인한다.
그러니 이 문서는 소개글이 아니라 **따라 하는 순서와 판단 기준**이다.

- **레퍼런스는 [`docs/schema.md`](schema.md)** — 필드 목록·문법·계약의 정본이다. 여기서 되풀이하지 않고 링크한다.
- **규칙 id 는 [`docs/rules.md`](rules.md)** — 69개 전체와 각 규칙의 `guide`.
- **여기서 인용하는 파일은 전부 [`examples/home-check`](../examples/home-check)** 에 실재한다.
  이 문서의 명령과 출력은 **실제로 돌려서 받은 것**이다.

돌리기 전에 두 경로를 환경변수로 준다 (예제 README 참조):

```bash
export LINTOMATA_EXAMPLE_ROOT=<저장소>/examples/home-check
export LINTOMATA_EXAMPLE_OUT=<쓰기 가능한 출력 디렉터리>
export LINTOMATA_HOME=$(mktemp -d)
```

---

## 1. 요구에서 구조로 — 무엇을 먼저 정하는가

들어온 요구: *"홈 화면이 기획대로 보이는지 검사하고 싶다."*

**먼저 정하는 것은 노드가 아니라 "사람이 무엇을 보는가" 다.** 이 예제에서는 둘로 갈랐다 —
**버튼이 3개이고 라벨이 순서대로인가**, **메뉴가 4개이고 순서대로인가**.
여기까지가 기획이고, 나머지는 이 문장을 네 단계로 쪼개는 기계적인 작업이다.

| 묻는 것 | 답이 곧 | 예제 |
|---|---|---|
| **어디를 볼 것인가?** | **Vantage** | `targets/home.html` 파일 하나를 관측 지점으로 잡는다 |
| **거기서 원시 데이터를 어떻게 가져오는가?** | **Sense** | 그 파일을 읽어 HTML 문자열을 낸다 |
| **그 원시 데이터에 무슨 의미를 부여하는가?** | **Perceive** | 이 마크업에서 **무엇이 버튼인가**를 판정한다 |
| **그 의미를 기획과 어떻게 대조하는가?** | **Reckon** | 버튼이 3개인지, 라벨 순서가 맞는지 |
| **중간에 무슨 행위를 끼워야 하는가?** | **Action** | 관측 사실을 감사 로그에 남긴다 |

### 갈림길에서 쓰는 판단 기준

- **Vantage / Sense** — *"대상을 정하는 것"* 과 *"대상에서 값을 꺼내는 것"* 의 경계다.
  `vantage_pick_page.py` 는 파일 경로만 정하고 **읽지 않는다**. 읽는 것은 `sense_read_html.py` 다.
  경로를 정하는 쪽과 읽는 쪽을 나누면 **같은 Sense 를 다른 Vantage 에 붙일 수 있다.**
- **Sense / Perceive** — **해석이 들어가면 Perceive 다.** HTML 문자열 그 자체는 Sense,
  *"이 요소는 버튼이다"* 는 Perceive. `perceive_buttons.py` 가 `data-decoy="true"` 를
  버튼에서 빼는 것이 바로 해석이다.
- **Perceive / Reckon** — **기획과 대조하면 Reckon 이다.** 버튼을 세는 것은 Perceive,
  *"3개여야 하는데 2개다"* 는 Reckon. 대조 기준(3)은 Perceive 가 알아서는 안 된다.
- **Action** — 지각도 판정도 아닌 **행위**다. 클릭·입력·기록. `input == output` 이라
  타입 관점에서 투명하고 노드 사이 어디에나 끼워 넣을 수 있다.

### 이 판단이 만들어낸 그래프

```
pickPage ─▶ readHtml ─▶ audit ─┬─▶ detectButtons ─▶ checkButtons
(Vantage)   (Sense)   (Action) │   (Perceive)        (Reckon)
                               └─▶ detectMenu    ─▶ checkMenu
                                   (Perceive)        (Reckon)
```

`audit` 이 `readHtml` 과 `detectButtons` 사이에 있는데도 타입 검사가 통과한다 —
**Action 은 투명하다.** 실제로는 `readHtml ──▶ detectButtons` 이고 그 사이에서 부작용만 난다.

---

## 2. 각 층에 무엇을 쓰는가

네 층은 **전부 별개 파일**이다: `Spec(JSON) → Pipeline(JSON) → Node(JSON) → Script(.py)`.
필드 레퍼런스는 [schema.md 1·3·4·5절](schema.md#1-네-층--네-파일).

### Script — 실제 동작 코드

[`examples/home-check/scripts/vantage_pick_page.py`](../examples/home-check/scripts/vantage_pick_page.py)

```python
@dataclass
class PickParams:
    pagePath: str

@dataclass
class Scene:
    source: str

@dataclass
class Args:
    params: PickParams

def runNode(args: Args) -> Scene:
    return returnResult(Scene(source=args.params.pagePath))
```

여기 있는 것은 **능력 선언**이다 — *"나는 `pagePath` 라는 파라미터를 받을 수 있다"*.
Vantage 라서 `Args` 에 `input` 이 없다.

### Node — 동작 정의

[`examples/home-check/nodes/pick_page.json`](../examples/home-check/nodes/pick_page.json)

```json
{
  "info": { "name": "pick-page", "description": "검사할 HTML 파일 하나를 관측 지점으로 잡는다" },
  "type": "vantage",
  "script": "${env.LINTOMATA_EXAMPLE_ROOT}/scripts/vantage_pick_page.py"
}
```

**`type` 은 노드에 있다** — 노드의 성질이지 사용처의 성질이 아니다.
`script` 는 등록된 스크립트(`${ref.sc_...}`) 또는 **실재하는 파일 경로**다.
예제는 경로를 쓴다 — **fresh clone 에서 새로 등록하면 id 가 달라지기 때문**이다.

### Pipeline — DAG 구성

[`examples/home-check/pipelines/page_check.json`](../examples/home-check/pipelines/page_check.json)

```json
{
  "id": "detectButtons",
  "source": "${env.LINTOMATA_EXAMPLE_ROOT}/nodes/detect_buttons.json",
  "inputs": { "sensum": "audit" },
  "states": { "ready": "observed" },
  "when": { "state": "ready" }
}
```

여기 있는 것은 **사용 선언**이다 — *"내 검사에서는 이 노드를 이렇게 배선하고,
그 노드가 말하는 `ready` 는 내 상태 `observed` 다"*. 스크립트가 받을 수 있는 것 중
**쓰는 것만** 적는다.

### Spec — 기획

[`examples/home-check/specs/home_ok.json`](../examples/home-check/specs/home_ok.json)

```json
{
  "info": { "description": "홈 화면(정상 판)이 기획대로 보이는지 검사한다", "version": "0.1.0" },
  "tool": {},
  "plan": [{
    "source": "${env.LINTOMATA_EXAMPLE_ROOT}/pipelines/page_check.json",
    "description": "버튼 3개(시작하기·문서 보기·문의하기)와 메뉴 4개가 기획 순서대로 있어야 한다",
    "config": {
      "pagePath": "${env.LINTOMATA_EXAMPLE_ROOT}/targets/home.html",
      "auditLog": "${env.LINTOMATA_EXAMPLE_OUT}/audit.log",
      "expectedButtonCount": 3,
      "expectedButtonLabels": ["시작하기", "문서 보기", "문의하기"],
      "expectedMenuCount": 4,
      "expectedMenuLabels": ["홈", "제품", "가격", "지원"]
    }
  }]
}
```

**기획 데이터는 여기 있다.** 파이프라인이 config 를 **선언**하고 Spec 이 **값을 채운다.**
`plan` 항목은 무조건 파이프라인 **참조**다 — 인라인 금지.

### 왜 네 개로 나뉘는가 — `check_count` 하나가 두 자리에 있다

노드 재사용은 별도 문법이 아니라 **근본 동작**이다. `page_check.json` 에서
같은 노드 파일이 두 번 나온다:

```json
{ "id": "checkButtons", "source": "…/nodes/check_count.json",
  "inputs": { "percept": "detectButtons" },
  "params": { "expectedCount": "${config.expectedButtonCount}",
              "expectedLabels": "${config.expectedButtonLabels}" } },
{ "id": "checkMenu",    "source": "…/nodes/check_count.json",
  "inputs": { "percept": "detectMenu" },
  "params": { "expectedCount": "${config.expectedMenuCount}",
              "expectedLabels": "${config.expectedMenuLabels}" } }
```

**스크립트도 노드도 그대로고 `params` 만 다르다.** 이게 가능한 이유가
"기댓값은 스크립트가 아니라 Spec 이 준다" 는 형식 제한이다 (다음 절).
층이 하나라도 합쳐졌으면 — 예컨대 Spec 안에 스크립트 본문이 있었으면 — 같은 판정 로직을
두 벌 복사해야 한다.

### 경로 규칙

**모든 경로는 절대경로다.** `~` 와 `${env.X}` 만 허용한다. 상대경로는 cwd 의존을 만든다.
이식성은 환경변수가 담당한다 — 예제가 `${env.LINTOMATA_EXAMPLE_ROOT}` 를 쓰는 이유이고,
그래서 이 Spec 들은 **머신에 묶이지 않고 저장소에 그대로 커밋돼 있다.**
자세히는 [schema.md 3절](schema.md#3-spec).

---

## 3. 스크립트 작성 규칙 — 형식 제한과 그 이유

### 고정된 것

| 무엇 | 규칙 |
|---|---|
| 진입점 | `def runNode(args: Args)` — 이름 고정, 인자 하나 |
| 출력 | `return returnResult(<dataclass>)` — 이름 고정 |
| 인자 타입 | **`Args`** 라는 고정 이름의 dataclass. 없으면 오류 |
| `Args` 의 필드 | `input` / `params` / `state` **셋뿐**. 쓰는 것만 선언한다 |
| 반환 타입 | 이름은 자유. **구조로 매칭**한다 |

`input` 은 앞단 노드가 준 값, `params` 는 Spec/파이프라인이 준 값,
`state` 는 파이프라인 상태(**읽기 전용**)다. 출처가 셋으로 갈라져 있으므로
*"이 값이 어디서 왔는가"* 가 선언만 보고 정해진다.

### ★ Reckon 은 기댓값을 `params` 로 받아야 한다

[`scripts/reckon_count.py`](../examples/home-check/scripts/reckon_count.py) 를 보라.
`ExpectParams` 에 `expectedCount` / `expectedLabels` 가 있고 `runNode` 가 그 값을 쓴다.

**하드코딩하면 무엇이 무너지는가:**

1. **기획 파일이 껍데기가 된다.** Spec 의 `expectedButtonCount: 3` 을 4로 고쳐도 판정이 안 바뀐다.
2. **"기획대로면 통과"라는 정의 자체가 무너진다.** 판정 기준이 기획이 아니라 스크립트에 있게 된다.
3. **같은 기획을 A/B 두 대상에 돌리는 용도**(리뉴얼 동일성 검증)가 성립하지 않는다.
4. **노드 재사용이 불가능해진다.** `check_count` 를 버튼과 메뉴 두 자리에 쓸 수 없다.

그래서 `Args.params` 에 기댓값 필드가 없으면 **등록이 실패한다**(`LNT-CONTRACT-005`).
그리고 필드만 두고 안 쓰는 경우는 정적으로 못 잡으므로 **단위테스트가 잡는다**(4절).

출력 dataclass에는 **`passed: bool` 이 있어야** 엔진이 통과/위반을 읽는다(`LNT-CONTRACT-007`).

### Action 은 `input == output`

[`scripts/action_audit.py`](../examples/home-check/scripts/action_audit.py) 의 반환은
`returnResult(args.input)` 이다. 데이터 변환은 하지 않고 부작용만 낸다.
input 타입과 output 타입이 다르면 등록이 실패한다(`LNT-CONTRACT-006`).
클릭 결과를 뒷단이 알아야 하면 **후속 Sense 가 다시 관측한다.**

### 타입 어휘

쓸 수 있는 것은 **primitive**(`int` `float` `str` `bool` `bytes` `list[T]`)와
**스크립트가 선언한 dataclass** 둘뿐이다.

| 금지 | 왜 |
|---|---|
| `dict` | 허용하면 dataclass 강제가 한 줄로 무의미해진다 (`LNT-TYPE-001`) |
| `Optional` / `None` | 부분집합 병합 규칙과 겹쳐 판정이 흐려진다. 값이 없을 수 있는 필드는 **선언하지 않는다** (`LNT-TYPE-002`) |
| primitive 를 그대로 반환 | 타입 동일성을 **구조로** 판정하므로 대조할 구조가 없다 (`LNT-CONTRACT-003`) |

배선된 두 노드는 **정의가 엄격히 동일**해야 한다 — 앞단 output 과 뒷단 input 을
`(필드명, 타입)` 쌍의 집합으로 대조한다(`LNT-TYPE-004`). 자세히는
[schema.md 7절](schema.md#7-타입-시스템).

### 금지 4종

| 금지 | 대신 | 규칙 |
|---|---|---|
| 시간 의존 (`time`, `datetime.now`) | `Args.state.__startedAt` (엔진이 준다, epoch ms) | `LNT-BAN-001` |
| 랜덤 | — 같은 입력에 같은 결과가 나와야 리포트를 믿을 수 있다 | `LNT-BAN-002` |
| 직접 `subprocess`/`exec` | Spec 의 `tool` 에 경로·허용 함수를 선언하고 그것을 쓴다 | `LNT-BAN-003` |
| 미선언 state 참조 | `Args.state` 에 먼저 선언한다 | `LNT-BAN-004` |

**그 밖에는 아무것도 금지하지 않는다.** 노드 안에서 AI 를 부르든 파일을 읽든 네트워크를
타든 상관없다 — output 이 계약과 다르면 타입 검사에 걸린다. 순수성은 요구하지 않는다.

`action_audit.py` 가 `${state.__startedAt}` 을 `params` 로 받아 로그에 찍는 것이
이 규칙의 실제 사용례다. 돌리면 이렇게 남는다:

```
1786874956395	…/examples/home-check/targets/home.html	612
```

### 외부 패키지를 쓰려면 — PEP 723 로 선언하고 **lintomata 환경에 설치한다**

stdlib 만 쓰면 아무것도 안 해도 된다. **대부분의 스크립트가 그렇고, 헤더가 없는 것이 정상이다.**

`selectolax` 같은 외부 패키지가 필요하면 두 가지를 한다.

**① 스크립트 맨 위에 PEP 723 헤더를 쓴다.**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["selectolax>=0.3"]
# ///
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser
```

각 줄이 `# ` 로 시작하고, 사이는 TOML 이며, `# ///` 로 닫는다. 파일 맨 위여야 한다.

**② lintomata 가 설치된 환경에 함께 깐다.**

```
uv tool install lintomata --with 'selectolax>=0.3'
```

> ### ⚠ `--with` 는 **선언적**이다 — 전부 함께 적어야 한다
>
> `uv tool install --with` 는 이전에 넣은 `--with` 를 **유지하지 않는다.** 적은 것만 남고
> 나머지는 **지워진다.**
>
> ```
> $ uv tool install lintomata --with 'typing-extensions>=4'
> Uninstalled 1 package in 1ms
>  - myproject-perceive-lib==0.1.0        ← 다른 스크립트가 쓰던 것이 사라졌다
> ```
>
> 그래서 하나를 추가할 때도 **이미 쓰는 것을 전부 나열**한다:
>
> ```
> uv tool install lintomata --with 'selectolax>=0.3' --with 'typing-extensions>=4'
> ```
>
> **`LNT-DEP-001` / `-003` 의 메시지는 이 완전한 명령을 만들어 준다** — 등록소에 선언된
> 것을 전부 모아 넣으므로 **그대로 복사해 쓰면 된다.** 직접 만들 때는
> `lintomata script list` / `show <id>` 의 **선언 의존성**으로 확인하라.

**★ 헤더는 선언일 뿐 환경을 만들어 주지 않는다.** 노드 스크립트는 lintomata 와 **같은
프로세스**에 로드되므로 `import` 는 lintomata 가 설치된 환경에서 풀린다 — 격리 환경도,
스크립트별 가상환경도 없다. ESLint 플러그인이 ESLint 와 같은 `node_modules` 를 쓰는 것과
같은 모델이다 (`schema.md` 6절).

**헤더를 쓰면 등록 시점에 확인한다.** 선언한 것이 환경에 없으면 `script add` 가 거절하고
설치 명령을 알려준다 — 돌려보기 전에 잡히는 자리다.

| 규칙 | 언제 | 무엇을 고치나 |
|---|---|---|
| `LNT-DEP-001` | 선언한 패키지가 환경에 없다 | **설치한다** (메시지에 명령이 그대로 들어 있다) |
| `LNT-DEP-002` | 헤더 형식이 잘못됐다 | **헤더를 고친다** — 설치할 것이 없다 |
| `LNT-DEP-003` | 설치된 버전이 요구를 만족하지 않는다 | 버전을 맞추거나 헤더의 요구를 고친다 |

> **HTML 파싱에는 `selectolax`(lexbor) 를 쓴다.** `BeautifulSoup` 은 lxml 백엔드로도
> 13배 느리다 (`CLAUDE.md` 실측표).

### 공용 로직을 여러 스크립트가 돌려쓰려면

**형제 파일 import 는 안 된다. 옆에 있어도 안 된다.**

```python
from button_lib import is_button      # ✕ ModuleNotFoundError — 파일이 옆에 있어도
```

스크립트가 있는 디렉터리는 `sys.path` 에 없다. 그리고 등록하면 **스크립트 파일 하나만**
`~/.lintomata/scripts/` 로 복사되므로 옆 파일은 따라오지 않는다 — `schema.md` 2절이
**원본을 지워도 된다**고 못 박았으므로, 옆 파일에 기대는 순간 그 약속이 깨진다.

**① 첫 번째 답은 노드 재사용이다.** 판정 *함수*를 공유하지 말고 **그 판정을 하는 노드**를
여러 파이프라인이 참조한다. 노드 재사용은 별도 기능이 아니라 **근본 동작**이다
(`schema.md` 1절). 네 층이 별개 파일인 이유가 이것이고, 이 문서 2절의
`check_count` 하나가 `checkButtons`·`checkMenu` 두 자리에 쓰이는 것이 그 실물이다.

**② 노드 재사용으로 안 풀리는 경우가 있다.** 예를 들어 **값 검증용 Perceive** 와
**동일성 비교용 Perceive** 는 출력이 달라 별개 노드여야 하는데(`schema.md` 12절),
*"무엇이 버튼인가"* 를 판정하는 로직은 같다. **그때가 라이브러리다.**

```bash
lintomata library add /abs/libraries/buttons.py       # ① 본체를 등록한다 → lb_9f8e7d6c
```

```jsonc
// ② 노드가 슬롯에 무엇을 쓸지 정한다 — **사용 선언**
{ "type": "perceive", "script": "${ref.sc_a1b2c3d4}",
  "libraries": { "buttons": "${ref.lb_9f8e7d6c}" } }
```

```python
# ③ 스크립트는 필요하다고 선언만 한다 — **능력 선언**
from lintomata_lib import buttons

found = buttons.collect(args.input.html, buttons.is_button)
```

**허용되는 import 형태는 이것 하나뿐이다.** `import lintomata_lib` 도,
`from lintomata_lib.x import y` 도, 함수 안에서의 import 도 `LNT-LIB-005` 다 —
슬롯을 정적으로 못 뽑으면 배선 검사가 무의미해지기 때문이다.

| 이런 실수 | 규칙 |
|---|---|
| 스크립트는 요구하는데 노드가 배선 안 함 | `LNT-LIB-001` — 노드에 넣는다 |
| 노드는 배선했는데 스크립트가 안 씀 | `LNT-LIB-002` — 배선을 뺀다 |
| 라이브러리가 다른 라이브러리를 import | `LNT-LIB-003` — **한 층만** |
| 라이브러리가 `dataclass` 를 선언 | `LNT-LIB-004` — 스크립트로 옮긴다 (v1 제한) |
| `${ref.sc_...}` 를 `libraries` 에 배선 | `LNT-REG-003` — 접두를 맞춘다 |

**배선은 `${ref.lb_...}` 말고 절대경로로도 된다** (`${env.X}` 포함). id 는 등록소마다
다르게 발급되므로 **커밋할 것은 경로로 쓴다** (`schema.md` 2절).

**라이브러리에도 금지 패턴이 그대로 걸린다** — 시간·랜덤·subprocess. 안 그러면
거기서 `import time` 을 해 금지가 통째로 우회된다. 라이브러리는 **함수만** 제공하고,
`dataclass` 는 v1 에서 막혀 있다(타입 레지스트리는 스크립트 파일 하나만 파싱한다).

**본체를 고치면 그것을 쓰는 노드·파이프라인·Spec 의 검증이 전이적으로 다시 돈다.**
*"본체가 한 곳에 있다"* 가 실제로 의미를 갖는 이유가 이것이다. `library show <id>` 가
그것을 쓰는 노드 전부를 보여주고, `library list` 는 **아무도 안 쓰는 것**을 표시한다.

**③ 범용 서드파티라면 작은 패키지로 만들어 설치한다.** 프로젝트 고유의 판정 로직은
라이브러리로, 범용은 패키지로 — 패키지는 **검증 경계 바깥**이라 해시도 금지 패턴 검사도
받지 않는다는 것이 차이다.

```
uv tool install lintomata --with /path/to/myproject-perceive-lib --with 'selectolax>=0.3'
```

(`--with` 는 선언적이므로 **이미 쓰는 것을 함께 적는다** — 위 경고 참조.)

```python
# /// script
# dependencies = ["myproject-perceive-lib>=0.1"]
# ///
from myproject_perceive import is_button
```

헤더로 선언하면 **등록 시점에 확인된다**(`LNT-DEP-001`). 패키지는 파일이 아니라
환경에 있으므로 원본을 지워도, 등록소로 복사돼도 그대로 풀린다.

> **`PYTHONPATH` 로도 되기는 한다. 권하지 않는다.** 등록 후 원본 폴더를 지우면 깨지고,
> 실행하는 셸마다 환경을 맞춰야 한다 — *"등록하면 원본을 지워도 된다"* 는 등록소 모델과
> 어긋난다. 되는 것과 기대도 되는 것은 다르다.

---

## 4. 단위테스트를 어떻게 붙이는가

**`<노드파일>.test.json`** 을 노드 파일 옆에 둔다. 별도 등록 종류가 아니라
노드 정의 묶음의 일부라서, `node add`/`update` 가 함께 등록소로 복사한다.
레퍼런스는 [schema.md 14절](schema.md#14-노드-단위테스트).

```json
{
  "node": "${env.LINTOMATA_EXAMPLE_ROOT}/nodes/detect_buttons.json",
  "cases": [
    { "name": "…", "args": { "input": {…}, "state": {…} }, "expect": {…} }
  ]
}
```

### 두 층위 — 같은 실행에서 함께 돈다

| 준 것 | 하는 검사 |
|---|---|
| `args` fixture 만 | **돌려서 타입이 맞는지** — 기본 제공 |
| `args` + `expect` | 그 위에 **값이 맞는지** — 커스텀 |

[`nodes/detect_buttons.test.json`](../examples/home-check/nodes/detect_buttons.test.json)
의 세 번째 케이스가 `expect` 없이 타입만 보는 것이다 (*"버튼 없는 페이지"*).

**등록 검사와 다르다.** 등록 검사는 스크립트를 **안 돌린다**(형식·선언·금지 패턴).
단위테스트는 **돌린다**(선언대로 동작하는가). 저작 순서는 *등록으로 형식을 잡고 →
테스트로 동작을 잡는다* 다.

### ★ Perceive 테스트가 이 도구에서 가장 중요하다

**Perceive 가 틀리면 검사 전체가 조용히 무의미해진다.** 버튼을 잘못 세면 Reckon 은
그 잘못된 수를 기획과 대조해 통과나 위반을 낸다 — 리포트는 멀쩡해 보이는데 내용이 거짓이다.
그래서 *"이 HTML 을 주면 버튼을 3개로 인식하는가"* 를 묻는 것이 **별도 검사 카테고리**다.

예제의 두 번째 케이스가 도메인 지식을 그대로 검사한다:

```json
{
  "name": "누를 수 있게 생긴 배경 장식은 버튼이 아니다",
  "args": {
    "input": { "source": "/tmp/fixture-b.html",
               "html": "<main><div class=\"hero\" data-decoy=\"true\" role=\"button\">배경</div><button>확인</button></main>" },
    "state": { "ready": true }
  },
  "expect": { "count": 1, "labels": ["확인"] }
}
```

`role="button"` 이 둘인데 **1개**를 기대한다. `<button>` 이 있다고 버튼인 것이 아니라는
판단이 여기서 실증된다.

```
$ uv run lintomata node test $LINTOMATA_EXAMPLE_ROOT/nodes/detect_buttons.test.json
pass 3  violation 0  not_run 0  error 0
[pass] …/nodes/detect_buttons.json > cases[0] 버튼 3개짜리 평범한 페이지 — 개수와 라벨까지 본다 > detect-buttons
[pass] …/nodes/detect_buttons.json > cases[1] 누를 수 있게 생긴 배경 장식은 버튼이 아니다 > detect-buttons
[pass] …/nodes/detect_buttons.json > cases[2] 버튼 없는 페이지 — 기대값 없이 타입만 확인 > detect-buttons
EXIT=0
```

### Action 은 `expect` 없이도 값 동일성이 자동 검사된다

`input == output` 이 계약이므로 **기대값이 곧 입력**이다. 적을 필요가 없다.
[`nodes/audit.test.json`](../examples/home-check/nodes/audit.test.json) 은 케이스 하나에
`expect` 가 없는데도 반환이 입력과 다르면 `LNT-TEST-005` 로 걸린다.

### ★ Reckon 은 대조쌍이 필요하다

**`input` 은 같고 `params` 만 다른 통과/위반 쌍**을 둔다.
[`nodes/check_count.test.json`](../examples/home-check/nodes/check_count.test.json) 의 앞 두 케이스가 그것이다:

```json
{ "name": "기획대로 3개 — 통과",
  "args": { "input": { "count": 3, "labels": ["시작하기","문서 보기","문의하기"] },
            "params": { "expectedCount": 3, "expectedLabels": ["시작하기","문서 보기","문의하기"] } },
  "expect": { "passed": true, "rule": "expectedCount", "message": "3개, 순서 일치" } },

{ "name": "같은 입력에 기댓값만 4개로 — 위반 (대조쌍)",
  "args": { "input": { "count": 3, "labels": ["시작하기","문서 보기","문의하기"] },
            "params": { "expectedCount": 4, "expectedLabels": ["시작하기","문서 보기","문의하기","베타 신청"] } } }
```

`input` 이 글자 하나까지 같고 `params` 만 다르다. **판정이 갈리지 않으면 기댓값을
안 쓰는 것이다** — 정적으로는 못 잡는 하드코딩을 여기서 잡는다.
대조쌍 자체가 없으면 `LNT-TEST-006`(경고), 있는데 판정이 같으면 `LNT-TEST-007`(오류).

`invalid/bad_reckon_hardcoded.py` 가 바로 그 경우다 — `Args.params` 에 기댓값 필드를
두고도 `runNode` 는 `args.input.count == 3` 을 박아 놨다:

```
$ uv run lintomata node test $LINTOMATA_EXAMPLE_ROOT/invalid/bad_reckon_hardcoded.test.json
pass 2  violation 0  not_run 0  error 1
[pass] …/invalid/bad_reckon_hardcoded.json > cases[0] 기댓값 3 — 통과가 나온다 > bad-reckon-hardcoded
[pass] …/invalid/bad_reckon_hardcoded.json > cases[1] input 은 같고 기댓값만 4 — 판정이 바뀌어야 하는데 안 바뀐다 > bad-reckon-hardcoded
[error] …/invalid/bad_reckon_hardcoded.json > bad-reckon-hardcoded (LNT-TEST-007)
    대조쌍의 판정이 같습니다.
    기댓값을 바꿨는데 판정이 안 바뀝니다 — 기댓값을 쓰지 않고 하드코딩하고 있습니다
    `기댓값 3 — 통과가 나온다` 과 `input 은 같고 기댓값만 4 — …` 은 `params` 가 다른데 판정이 둘 다 통과입니다.
    params: {'expectedCount': 3, …} vs {'expectedCount': 4, …}
EXIT=2
```

**케이스 둘은 각각 통과했다.** 스크립트가 예외를 낸 것도, 타입이 틀린 것도 아니다.
걸린 것은 *"판정이 갈리지 않는다"* 는 사실 쪽이다.

> **결정성 검사(같은 입력 2회 실행 비교)는 하지 않는다** — AI 를 부르는 Perceive 가
> 당연히 실패하기 때문이다.

---

## 5. 어떻게 돌리고 무엇이 성공인가

### 명령 — 두 가지 형태

```bash
# (a) 파일 경로로 바로. 등록 없이 돈다
uv run lintomata check     $LINTOMATA_EXAMPLE_ROOT/specs/home_ok.json
uv run lintomata node test $LINTOMATA_EXAMPLE_ROOT/nodes/detect_buttons.test.json

# (b) 등록 후 id 로. scripts → nodes → pipelines → specs 순서
uv run lintomata script add $LINTOMATA_EXAMPLE_ROOT/scripts/perceive_buttons.py
uv run lintomata node   add $LINTOMATA_EXAMPLE_ROOT/nodes/detect_buttons.json
uv run lintomata check      sp_xxxxxxxx
uv run lintomata node test  nd_xxxxxxxx
```

**등록은 편의가 아니라 검증 결과를 재사용하는 기제다.** 등록 시 정적 검사를 통과해야
저장되고, 실행 시 해시를 대조해 검사 루트를 피한 수정을 막는다. 해시가 그대로면
재검사하지 않는다. 경로로 준 것은 검증된 적이 없으므로 실행 전에 검사한다 — 그만큼 비싸다.

### ★ 결과 네 상태 — 무엇이 "성공" 인가

| 상태 | 무엇 | 성격 |
|---|---|---|
| **통과** | 기획대로다 | 결과 |
| **위반** | 기획과 다르다 | **정상 결과.** lint 가 제 일을 한 것 |
| **not run** | 앞단 실패의 여파로 도달 불가가 됐다 | **정상 결과.** 통과와 구분해 보고한다 |
| **오류** | 스크립트 예외·계약 위반·경로 없음·환경변수 미정의 | **비정상.** 도구가 못 돈 것 |

**★ 위반이 나온 것은 실패가 아니다.** 검사 대상이 기획과 다르다는 **산출물**이고,
그걸 찾아낸 것이 이 도구가 존재하는 이유다. **고쳐야 할 것은 오류(2)뿐이다.**

이걸 헷갈리면 AI 가 위반을 수습하려 든다 — 기댓값을 낮추거나, 스크립트에 예외를 넣거나,
재시도를 붙이거나. 전부 잘못이다. **복구·재시도·되돌아가기·대체 경로는 이 도구에 없다.**
위반이 나오면 그 사실을 그대로 보고하고 끝낸다.

종료 코드가 이 구분을 그대로 드러낸다:

| 코드 | 의미 |
|---|---|
| `0` | 통과만 있음 |
| `1` | **위반 또는 not run** 이 있음 — 도구는 제대로 돌았다 |
| `2` | **오류** — 도구가 못 돌았다 (또는 사용법 오류) |

### 실제 출력

**통과 — 종료 0**

```
$ uv run lintomata check $LINTOMATA_EXAMPLE_ROOT/specs/home_ok.json
pass 7  violation 0  not_run 0  error 0
[pass] home_ok.json > plan[0] > page-check > pickPage
[pass] home_ok.json > plan[0] > page-check > readHtml
[pass] home_ok.json > plan[0] > page-check > audit
[pass] home_ok.json > plan[0] > page-check > detectButtons
[pass] home_ok.json > plan[0] > page-check > checkButtons
[pass] home_ok.json > plan[0] > page-check > detectMenu
[pass] home_ok.json > plan[0] > page-check > checkMenu
EXIT=0
```

상태 전이가 실제로 일어나 `when` 이 걸린 `detectButtons` 가 돌았다.

**위반 — 종료 1**

같은 파이프라인·같은 노드에 **대상 파일만** `home_broken.html` 로 바꾼 Spec.

```
$ uv run lintomata check $LINTOMATA_EXAMPLE_ROOT/specs/home_broken.json
pass 5  violation 2  not_run 0  error 0
[pass] home_broken.json > plan[0] > page-check > pickPage
[pass] home_broken.json > plan[0] > page-check > readHtml
[pass] home_broken.json > plan[0] > page-check > audit
[pass] home_broken.json > plan[0] > page-check > detectButtons
[violation] home_broken.json > plan[0] > page-check > checkButtons (expectedCount)
    3개 기대, 2개 관측 (['시작하기', '문의하기'])
[pass] home_broken.json > plan[0] > page-check > detectMenu
[violation] home_broken.json > plan[0] > page-check > checkMenu (expectedCount)
    4개 기대, 3개 관측 (['홈', '제품', '지원'])
EXIT=1
```

**위반이 났는데도 뒷단이 멈추지 않았다** — 한 번의 실행에서 확인 가능한 실패를 전부 모은다.
Reckon 이 낸 규칙 이름(`expectedCount`)과 문구가 리포트에 그대로 실린다.

**오류 + not run — 종료 2**

```
$ uv run lintomata check $LINTOMATA_EXAMPLE_ROOT/specs/home_missing.json
pass 1  violation 0  not_run 5  error 1
[pass] home_missing.json > plan[0] > page-check > pickPage
[error] home_missing.json > plan[0] > page-check > readHtml
    `runNode` 가 예외를 냈습니다: …/scripts/sense_read_html.py
    FileNotFoundError: [Errno 2] No such file or directory: '…/targets/does_not_exist.html'
    스크립트 예외는 위반이 아니라 **오류**입니다 — 기획과 다른 것이 아니라 검사 자체가 못 돈 것입니다. 스크립트를 고치세요.
[not_run] home_missing.json > plan[0] > page-check > audit
    cause: readHtml (data_dependency)
[not_run] home_missing.json > plan[0] > page-check > detectButtons
    cause: readHtml (state_unreachable)
[not_run] home_missing.json > plan[0] > page-check > checkButtons
    cause: detectButtons (data_dependency)
[not_run] home_missing.json > plan[0] > page-check > detectMenu
    cause: audit (data_dependency)
[not_run] home_missing.json > plan[0] > page-check > checkMenu
    cause: detectMenu (data_dependency)
EXIT=2
```

**not run 은 통과와 확실히 구분된다.** 전파 경로가 둘이다 — 데이터로 막힌 것
(`data_dependency`)과 **상태**로 막힌 것(`state_unreachable`: `readHtml` 이 실패해
`observed` 전이가 안 일어났다). 일곱 노드가 네 상태 중 정확히 하나씩에 들어갔다.

**비교 파이프라인 — 전부 같으면 0**

```
$ uv run lintomata check $LINTOMATA_EXAMPLE_ROOT/specs/compare_ok.json
pass 3  violation 0  not_run 0  error 0
[pass] compare_ok.json > plan[0] > buttons-same > page
[pass] compare_ok.json > plan[0] > buttons-same > html
[pass] compare_ok.json > plan[0] > buttons-same > buttons
    대상 3개가 같은 값을 내놨습니다: alpha, beta, gamma
EXIT=0
```

리포트는 **실행과 동시에** `plan` 항목의 `report` 자리에 쌓인다:

```json
{ "buttons": { "same": true, "values": {
    "alpha": { "count": 3, "labels": ["시작하기","문서 보기","문의하기"] },
    "beta":  { "count": 3, "labels": ["시작하기","문서 보기","문의하기"] },
    "gamma": { "count": 3, "labels": ["시작하기","문서 보기","문의하기"] } } } }
```

세 대상의 **HTML 은 완전히 다르다**(`<button>` / `class="btn"` / `role="button"`).
인식 스크립트도 각각 다르다. 그런데 개념 층에서 같으므로 통과한다 — 이게 설계의 핵심 주장이다.
**Reckon 은 없다.** 동등 비교는 도메인 지식이 아니라 일반 연산이라 엔진이 한다.

**비교 파이프라인 — 하나만 달라도 1**

```
$ uv run lintomata check $LINTOMATA_EXAMPLE_ROOT/specs/compare_diff.json
pass 2  violation 1  not_run 0  error 0
[violation] compare_diff.json > plan[0] > buttons-same > buttons
    대상 간 출력이 다릅니다.
      alpha: {'count': 3, 'labels': ['시작하기', '문서 보기', '문의하기']}
      beta: {'count': 3, 'labels': ['시작하기', '문서 보기', '문의하기']}
      gamma: {'count': 4, 'labels': ['시작하기', '문서 보기', '문의하기', '베타 신청']}
    판정은 목록 전부가 같은 값을 뱉느냐입니다 — 하나만 어긋나도 위반입니다. 무시해도 되는 차이(좌표 반올림·타임스탬프 등)라면 비교용 데이터를 내보내는 스크립트에서 정규화하세요. 엔진은 `==` 만 압니다.
EXIT=1
```

**짝지어 비교하는 것이 아니라 목록 전부가 한 값으로 일치하느냐**를 묻는다.
대상 개수에 제한이 없다. 무시해도 되는 차이는 **엔진이 아니라 스크립트가** 정규화한다.

---

## 6. 실패 카탈로그 — AI 의 자기 수정용

**돌리기 전에 잡아 자기 수정 신호를 주는 것**이 형식 제한의 목적이다.
[`examples/home-check/invalid/`](../examples/home-check/invalid) 를 태우면 아래가 그대로 재현된다.
규칙 전체는 [`docs/rules.md`](rules.md).

| 무엇이 틀렸나 | 명령 | 규칙 id | 무엇을 고치나 |
|---|---|---|---|
| 시간·랜덤·subprocess·미선언 state, `dict`, `Optional` | `script add invalid/bad_banned.py` | `LNT-BAN-001/002/003/004`, `LNT-TYPE-001/002` | 시각은 `Args.state.__startedAt`, 외부 도구는 Spec 의 `tool`, 복합 타입은 dataclass, 없을 수 있는 필드는 **선언하지 않는다** |
| 출력이 dataclass 가 아니다 (primitive 반환) | `script add invalid/bad_output_primitive.py` | `LNT-CONTRACT-003` | 값 하나라도 dataclass 로 감싼다 — 타입 동일성을 **구조로** 판정한다 |
| PEP 723 헤더에 선언한 패키지가 환경에 없다 | `script add invalid/bad_dependency.py` | `LNT-DEP-001` | 메시지에 적힌 `uv tool install lintomata --with '...'` 를 그대로 실행한다. 헤더는 선언일 뿐이고 **격리 환경을 만들어 주지 않는다** |
| Reckon 인데 판정 필드가 없다 (`ok` 로 지음) | `node add invalid/bad_reckon_no_verdict.json` | `LNT-CONTRACT-007` | 출력 dataclass 에 `passed: bool` 을 둔다 |
| 한 노드에 서로 다른 앞단 둘을 배선 | `pipeline add invalid/pipeline_ambiguous.json` | `LNT-GRAPH-003` | `Args.input` 은 필드 하나다. 앞단을 하나로 줄이거나 둘을 합치는 노드를 사이에 둔다 |
| `when` 이 기다리는 상태로 가는 전이가 없다 | `pipeline add invalid/pipeline_dead_state.json` | `LNT-STATE-006` | `transitions` 를 추가하거나 `when` 을 지운다. 전이를 적는 자리는 **파이프라인 어휘** 쪽이다 |
| 라이브러리에서 시간을 읽는다 | `library add invalid/lib_banned.py` | `LNT-BAN-001` | 금지는 스크립트와 **똑같이** 걸린다 — 여기가 뚫리면 금지가 통째로 우회된다 |
| 라이브러리가 `dataclass` 를 선언한다 | `library add invalid/lib_dataclass.py` | `LNT-LIB-004` | 계약 타입은 스크립트에 둔다 (v1 제한) |
| 스크립트가 요구한 슬롯을 노드가 배선 안 함 | `node add invalid/bad_unwired.json` | `LNT-LIB-001` | 노드 JSON 에 `libraries` 배선을 넣는다 |
| Reckon 이 기댓값을 안 쓰고 하드코딩 | `node test invalid/bad_reckon_hardcoded.test.json` | `LNT-TEST-007` | `args.params` 의 기댓값을 실제로 읽는다. **정적으로는 못 잡혀 단위테스트에서 잡힌다** |

마지막 하나를 뺀 나머지는 **등록이 실패한다** — 등록소에 들어가지 않으므로 잘못된 것이 재사용될 일이 없다:

```
$ uv run lintomata pipeline add $LINTOMATA_EXAMPLE_ROOT/invalid/pipeline_ambiguous.json
등록하지 않았습니다 — 정적 검사를 통과해야 저장됩니다: …/invalid/pipeline_ambiguous.json
pass 0  violation 0  not_run 0  error 1
[error] …/invalid/pipeline_ambiguous.json > checkButtons (LNT-GRAPH-003)
    `inputs` 가 서로 다른 앞단 노드를 둘 이상 가리킵니다: detectButtons, detectMenu
    `Args.input` 은 필드 하나라 값도 하나만 받습니다. `inputs` 에 서로 다른 노드를 둘 이상 적으면 어느 것을 넣어야 할지 정할 수 없습니다. 문제의 앞단: detectButtons, detectMenu — 앞단을 하나로 줄이거나, 둘을 합치는 노드를 사이에 두세요
EXIT=2
```

**메시지에 규칙 id 와 자연어 가이드가 함께 붙는다.** 가이드 문구가 곧 자기 수정 루프의
성능이므로, 새 규칙을 추가할 때도 *"무엇을 고치면 되는지"* 를 반드시 적는다.

> **등록 실패의 종료 코드는 `2` 다.** 위반(1)이 아니다 — 등록이 안 됐다는 것은
> 리포트가 아니라 **도구가 요청한 일을 못 한 것**이기 때문이다.

---

## 7. 사람에게 승인받는 법

**사람은 스키마·스크립트 전문을 읽지 않는다.** AI 가 요약한 것을 읽고 승인한다.
그래서 `description` 은 장식이 아니라 **승인 대상 그 자체**다.

구조만 있고 의도가 없으면 AI 요약이 구조를 되풀이할 뿐이고, 위반 리포트도
*"어떤 규칙인지"* 를 전달하지 못한다.

| 자리 | 무엇을 적나 | 단위테스트로 치면 |
|---|---|---|
| `info.description` (Spec) | **이 파일이 무엇을 보장하는가** | `describe` |
| `plan[].description` | **이 항목이 무엇을 확인하려는 것인가** | `it` |
| `info.description` (Pipeline·Node) | 이 구성/노드가 무엇을 하는가 | — |

**나쁜 예 — 구조를 되풀이한다:**

```json
{ "description": "page_check 파이프라인을 실행한다" }
{ "description": "expectedButtonCount 를 3으로 설정" }
```

파일을 보면 아는 것이고, 사람이 승인할 근거가 없다.

**좋은 예 — 예제가 쓰는 것:**

```json
"info": { "description": "홈 화면(정상 판)이 기획대로 보이는지 검사한다" },
"plan": [{ "description": "버튼 3개(시작하기·문서 보기·문의하기)와 메뉴 4개가 기획 순서대로 있어야 한다" }]
```

**기획의 문장이 그대로 들어 있다.** 사람은 이 두 줄만 읽고
*"내가 말한 기획이 맞나"* 를 판단할 수 있고, 위반 리포트에도 이 문장이 경로로 실린다.

`invalid/` 가 아닌 예제 파일들의 `description` 을 그대로 본떠 쓰면 된다.
[`specs/all_in_one.json`](../examples/home-check/specs/all_in_one.json) 은 항목마다
*"정상 판 — 전부 통과해야 한다"* / *"어긋난 판 — 위반이 두 건 나와야 한다"* /
*"없는 대상 — 오류 1건과 그 여파로 not run"* 처럼 **기대 결과까지** 적어 뒀다.

---

## 이 문서가 설명한 것을 그대로 검사하는 테스트

[`tests/test_examples.py`](../tests/test_examples.py) 가 예제를 **CLI 로** 태운다 —
네 상태와 종료 코드, 비교 리포트 내용, 단위테스트, `invalid/` 의 규칙 id,
그리고 **fresh 등록소에서 처음부터 등록해 id 로 도는지**까지.

예제가 안 돌면 그건 예제의 문제가 아니라 **본체의 결함**이다.
