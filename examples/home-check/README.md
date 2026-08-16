# examples/home-check

**다섯 노드 타입과 두 파이프라인 종류를 전부 태우는 예제.** 이 디렉터리만으로
`check` 와 `node test` 가 끝까지 돈다. 통합 테스트 [`tests/test_examples.py`](../../tests/test_examples.py)
가 이걸 CLI 로 그대로 태워 회귀를 막는다.

> **따라 만드는 법은 [`docs/AUTHORING.md`](../../docs/AUTHORING.md) 에 있다.**
> 이 파일은 **무엇이 어디 있는지**만 적은 지도다.

## 지도

```
targets/     검사 대상 HTML — 정상판·어긋난판·비교용 3벌(+어긋난 판)
libraries/   여러 스크립트가 나눠 쓰는 함수 (.py) — 버튼 판정의 본체
scripts/     노드 스크립트 (.py) — 다섯 타입 전부
nodes/       노드 정의 (.json) + 단위테스트 (<노드파일>.test.json)
pipelines/   page_check(값 검증) · buttons_same(비교, 대상 3개)
specs/       기획 — 통과·위반·not run·비교·혼합 시나리오
invalid/     ★ 일부러 틀린 것들 — 등록·단위테스트가 잡는 것을 보여준다
```

### 다섯 노드 타입이 어느 파일인가

| 타입 | 스크립트 | 노드 | 하는 일 |
|---|---|---|---|
| **Vantage** | `scripts/vantage_pick_page.py` | `nodes/pick_page.json` | 볼 HTML 파일 하나를 관측 지점으로 잡는다 |
| **Sense** | `scripts/sense_read_html.py` | `nodes/read_html.json` | 파일을 읽어 해석 없는 원시 HTML |
| **Perceive** | `scripts/perceive_buttons.py` · `perceive_menu.py` | `nodes/detect_buttons.json` · `detect_menu.json` | **무엇이 버튼인가**·메뉴 순서 |
| **Reckon** | `scripts/reckon_count.py` | `nodes/check_count.json` | 기댓값(`Args.params`)과 대조 |
| **Action** | `scripts/action_audit.py` | `nodes/audit.json` | 감사 로그 한 줄. 값은 그대로 통과 |

### 이 예제가 보여주는 것

- **Action 투명성** — `readHtml → audit → detectButtons` 배선이 타입 검사를 그대로 통과한다.
  Action 은 `input == output` 이라 타입 관점에서 투명하다 (`pipelines/page_check.json`).
- **상태머신** — `detectButtons` 는 자기 어휘 `ready` 로 쓰고(`perceive_buttons.py` 의 `Args.state`),
  파이프라인이 `{"ready": "observed"}` 로 매핑한다. 전이는 `transitions` 가 관리한다.
- **노드 재사용** — `nodes/check_count.json` **하나**를 `checkButtons` 와 `checkMenu`
  두 자리에 `params` 만 바꿔 배선했다. 재사용은 별도 문법이 아니라 근본 동작이다.
- **★ 비교 파이프라인** — `targets/variant_{alpha,beta,gamma}.html` 은 마크업이
  **완전히 다르다**(`<button>` / `class="btn"` / `role="button"`). 대상마다 인식
  스크립트가 다르고(`scripts/cmp_buttons_*.py`), 개념 층(버튼 개수·라벨)이 같으므로
  **통과한다.** Reckon 은 없다 — 동등 비교는 엔진이 한다.
- **도메인 지식은 사용자 쪽에만 있다** — `targets/home.html` 의
  `<div class="hero" data-decoy="true" role="button">배경 이미지</div>` 는
  *누를 수 있게 생긴 배경 장식*이라 버튼이 아니다. 이 판단은
  `libraries/buttons.py` 의 `is_button` 안에만 있고 엔진은 모른다.
- **★ 라이브러리** — 버튼을 지각하는 스크립트가 넷이다(값 검증용 하나, 비교용 셋).
  넷이 각자 HTML 을 훑으면 **라벨 정규화 규칙이 갈리는 순간 개념 층 비교가 조용히
  거짓이 된다.** 그래서 훑는 방법과 정규화는 `libraries/buttons.py` **하나**에 두고
  넷이 `from strictler_lib import buttons` 로 쓴다. 슬롯에 무엇을 쓸지는
  노드가 정한다 — `nodes/detect_buttons.json` · `compare_buttons.json` 의 `libraries`.

## 돌리는 법

경로 두 개를 환경변수로 준다 — **입력**(이 디렉터리)과 **출력**(Action 로그·비교 리포트).

```bash
export STRICTLER_EXAMPLE_ROOT=/절대경로/strictler/examples/home-check
export STRICTLER_EXAMPLE_OUT=/절대경로/쓰기가능한/출력디렉터리
export STRICTLER_HOME=$(mktemp -d)          # 등록소를 더럽히지 않으려면
```

### (a) 파일 경로로 바로

등록 없이 돈다. 예제는 전부 **경로 참조**로 배선돼 있다.

```bash
uv run strictler check     $STRICTLER_EXAMPLE_ROOT/specs/home_ok.json          # → 0
uv run strictler check     $STRICTLER_EXAMPLE_ROOT/specs/home_broken.json      # → 1 위반
uv run strictler check     $STRICTLER_EXAMPLE_ROOT/specs/home_missing.json     # → 2 오류+not run
uv run strictler check     $STRICTLER_EXAMPLE_ROOT/specs/compare_ok.json       # → 0
uv run strictler check     $STRICTLER_EXAMPLE_ROOT/specs/compare_diff.json     # → 1 위반
uv run strictler node test $STRICTLER_EXAMPLE_ROOT/nodes/detect_buttons.test.json
```

### (b) 등록 후 id 로

`libraries → scripts → nodes → pipelines → specs` 순서로 넣는다. **id 를 손으로 고칠 일이 없다** —
배선이 경로 참조라서 발급된 id 와 무관하다.

```bash
for f in $STRICTLER_EXAMPLE_ROOT/libraries/*.py;                   do uv run strictler library  add $f; done
for f in $STRICTLER_EXAMPLE_ROOT/scripts/*.py;                     do uv run strictler script   add $f; done
for f in $STRICTLER_EXAMPLE_ROOT/nodes/*.json;                     do case $f in *.test.json) continue;; esac
                                                                      uv run strictler node     add $f; done
for f in $STRICTLER_EXAMPLE_ROOT/pipelines/*.json;                 do uv run strictler pipeline add $f; done
for f in $STRICTLER_EXAMPLE_ROOT/specs/*.json;                     do uv run strictler spec     add $f; done

uv run strictler spec list                  # 발급된 id 확인
uv run strictler check     sp_xxxxxxxx
uv run strictler node test nd_xxxxxxxx      # 단위테스트는 노드와 함께 등록소로 복사된다
```

## `invalid/` — 일부러 틀린 것들

**여기 있는 것은 전부 등록이나 단위테스트에서 걸려야 정상이다.** 정상 예제와 섞지
않으려고 따로 뒀다. 무엇이 어떤 규칙 id 로 걸리는지는
[`docs/AUTHORING.md` 6절 실패 카탈로그](../../docs/AUTHORING.md#6-실패-카탈로그--ai-의-자기-수정용)
에 표로 있다.
