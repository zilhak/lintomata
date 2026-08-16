# MODULES.md — 모듈 경계와 공개 시그니처 계약

> **이 문서는 무엇인가.** 구현이 여러 갈래로 병렬 진행되는 동안 모듈 간 경계와 공개 시그니처를
> 고정하기 위해 쓴 계약서다. 각 라운드의 독립 리뷰가 계약 자체의 결함을 찾아내면
> **계약 개정(R1~R6)** 으로 기록했고, 그 개정 블록이 **본문보다 우선한다.**
>
> **왜 남기나.** R1~R7 은 "왜 지금 구조가 이렇게 됐는지" 의 근거다 — 예를 들어
> 타입 등록기의 키가 `(origin, name)` 인 이유(모든 노드 스크립트가 `Args` 를 선언한다),
> 구동 루프가 `engine/drive.py` 하나인 이유(둘로 두었더니 실제로 갈렸다),
> Action 이 타입 검사를 받는 이유(투명성은 면제가 아니다) 가 전부 여기 있다.
> 본문의 "Step" 표기는 그 병렬 진행의 흔적이다.

> ## ⚠️ 계약 개정 R7 (2026-08-16, conductor) — **R6~R1 보다 우선한다. 등록 종류 `library` 신설**
>
> `schema.md` 6.5절이 확정한 **다섯 번째 등록 종류**를 들인다. 형제 파일 `import` 가
> 되지 않으므로(등록하면 파일 하나만 복사된다) 공유는 등록소를 통해서 한다.
>
> ### R7-1. 등록 종류가 **다섯**이다 — `script` / `library` / `node` / `pipeline` / `spec`
> `model.EntryKind` 에 `"library"`, `ID_PREFIXES` 에 `"lb_"`, `store.SUBDIRS` 에
> `libraries/` 가 붙는다. **CRUD 다섯은 다른 종류와 완전히 같다** — 종류마다 다른
> 명령을 두지 않는다. `strictler library test` 는 **없다**(`schema.md` 6.5절: 라이브러리엔
> `runNode` 계약이 없어 하네스가 맞지 않는다 — 쓰는 쪽 **노드 단위테스트로 간접 검증**된다).
>
> ### R7-2. `checks/library.py` 신설 — **금지 표는 복제하지 않는다** ★
> 라이브러리에도 금지 패턴(시간·랜덤·subprocess)이 **스크립트와 똑같이** 걸린다.
> 안 걸면 거기서 `import time` 을 해 **금지가 통째로 우회된다.**
> → 판정은 `checks.script.check_bans` **그 함수**가 한다. 두 벌로 만들면 갈리고,
> 갈린 쪽이 곧 우회로가 된다 (R4-1 계열 사고가 정확히 그거였다).
>
> **시그니처 변경:** `check_bans(source, path, contract: ScriptContract | None)`.
> `None` 이면 `STR-BAN-004`(미선언 state 참조)를 보지 않는다 — 라이브러리에는
> 선언된 state 가 없어 판정할 근거가 아예 없다. 나머지 셋은 그대로 돈다.
>
> ```python
> NAMESPACE = "strictler_lib"
> def check_library(source: str, path: str,
>                   known_dependencies: tuple[str, ...] | list[str] = ()) -> list[Finding]
> def check_no_nesting(tree: ast.Module, path: str) -> list[Finding]   # STR-LIB-003
> def check_no_dataclass(tree: ast.Module, path: str) -> list[Finding] # STR-LIB-004
> ```
>
> ### R7-3. `list`/`show` 는 **어느 등록소를 보고 있는지**를 낸다 (`--json` 포함)
> `STRICTLER_HOME` 을 깜빡하고 전역 `~/.strictler` 에 조용히 쓰는 것이 가장 흔한 사고고,
> 목록이 비어 있을 때 *"등록이 안 된 것"* 과 *"다른 등록소를 보고 있는 것"* 이 구분되지
> 않는다. 라이브러리처럼 **공유되는 것**에서 특히 아프다.
> → `list --json` 은 배열이 아니라 `{home, kind, entries}` 다 (**형태 변경**).
> → 라이브러리는 **아무도 안 쓰면** 목록에 표시된다 (`schema.md` 6.5절: 강제하지 않고 보이게 한다).
>
> ### R7-4. 배선은 선언/사용 분리 그대로 — 새 개념이 늘지 않는다
> | | 어디 | 무엇 |
> |---|---|---|
> | `from strictler_lib import buttons` | **스크립트** | 능력 선언 — `ScriptContract.library_slots` 로 뽑는다 |
> | `"libraries": { "buttons": … }` | **노드 JSON** | 사용 선언 — `Node.libraries` |
>
> **허용 형태는 모듈 최상단의 `from strictler_lib import <이름>` 하나뿐이다**(`STR-LIB-005`).
> 정적으로 슬롯을 못 뽑으면 배선 검사가 무의미해지고, **함수 안의 import 는 주입 창을 놓친다**
> (아래 R7-5). `LIBRARY_NAMESPACE` 의 **정본은 `model`** — 이름이 갈리면 *선언한 슬롯*과
> *주입되는 이름*이 어긋나 조용히 `ImportError` 가 난다.
>
> ```python
> # checks/library.py
> def check_wiring(node: Node, contract: ScriptContract, *, path: str) -> list[Finding]   # LIB-001/002
> def resolve_libraries(node: Node, *, store: Store,
>                       env: Mapping[str,str]) -> tuple[dict[str, Path], list[Finding]]
> # checks/node.py
> def check_libraries(node, contract, source_path: str, *, store, env) -> list[Finding]
> # engine/drive.py — 실행 시점(해시 대조 포함). **값 검증·비교·단위테스트 셋이 이걸 쓴다**
> def resolve_libraries(node: Node, *, store, env, path: str,
>                       node_id: str) -> tuple[dict[str, Path], list[Finding]]
> # engine/exec.py · testing/harness.py
> def load_script(path: Path, libraries: Mapping[str, Path] | None = None) -> ModuleType
> def run_case(node, contract, script_path, case, *, env, libraries=None)
> ```
>
> ### R7-5. 주입은 **로드하는 동안만** — 끝나면 걷는다 ★
> `sys.modules` 는 프로세스 전역이다. `strictler_lib` 를 남겨두면 **다음 노드가 앞 노드의
> 배선을 본다** — 조용히 틀린 판정 로직으로 리포트가 나가는 종류의 사고다.
> → `engine/exec._installed_libraries` 가 로드 직전에 심고 `finally` 에서 되돌린다.
> **`sys.path` 는 건드리지 않는다** — 형제 파일 import 를 되게 만드는 것이 아니라,
> 배선된 것만 그 네임스페이스로 들어오게 하는 것이다.
>
> ### R7-6. 계약 캐시는 키를 그대로 두되 **버전을 올린다** (`CACHE_VERSION` 1 → 2)
> `library_slots` 는 **스크립트 자신의 바이트에서** 뽑은 것이라 키(경로 + 그 파일 해시)는
> 여전히 옳다 — 라이브러리의 *내용*은 계약에 들어오지 않는다. 그러나 **payload 모양이
> 바뀌었으므로** 버전을 안 올리면 옛 캐시가 *슬롯이 하나도 없는 계약*으로 되살아나
> `STR-LIB-001` 이 영영 안 걸린다. 라이브러리를 고쳤을 때 무효화돼야 하는 것(상위의 검증)은
> 캐시가 아니라 **등록소의 전이적 재검증**이 맡는다. 자리가 다르다.

> ## ⚠️ 계약 개정 R6 (2026-08-16, conductor) — **R5~R1 보다 우선한다. 최종 라운드**
>
> 최종 Gate 4(리뷰어 2명 독립)가 찾아낸 것. **rules.md 는 61개가 됐다.**
>
> ### R6-1. ★★ `node test <id>` 가 **요청한 노드가 아닌 다른 노드**를 돌린다 — 거짓 리포트
> `cli.py` 는 id 로 **테스트 파일 경로만** 찾고, `testing/harness.py` 는 그 파일의 `node` 필드로
> **노드를 다시 해석**한다. **둘이 일치하는지 아무도 안 본다.** conductor 가 직접 재현:
> ```
> $ strictler node test nd_1d371c3e        # 노드 a 를 요청
> pass 1 …
> [pass] …/b.json > cases[0] c0 > b        # ← 노드 b 가 돌았다
> ```
> **lint 도구에서 가장 나쁜 종류다.** 통과했다고 보고하는데 검사한 것이 다른 것이다.
>
> 같은 뿌리에서 **R5-2 의 목표가 반만 달성된다** — `.test.json` 의 `node` 가 경로면 파일은 복사되지만
> 참조는 원본을 가리키므로 **원본을 지우면 죽는다**(재현됨). R5-2 가 없애려던 바로 그 상황이다.
>
> → **`node test <id>` 로 부르면 그 id 의 등록소 노드가 정본이다.**
> `node_test.node` 는 **대조용으로만** 쓰고, 다른 노드를 가리키면 **`STR-TEST-008`**(신설, 슬롯
> `{requested}` `{declared}`). `node` 필드를 경로로 해석하지 않는다 → 원본 삭제와 무관해진다.
> `node test <경로>` 형태는 지금처럼 `node` 필드를 따른다.
>
> ### R6-2. ★ **네 번째 대역 은폐** — `tests/test_cli.py` 가 `harness` 를 갈아끼운다
> `test_cli.py` 가 `harness.load_node_test`/`run_node_test` 를 대역으로 바꾼다. Step 4-a 는 merge 됐다.
> **R6-1 이 안 잡힌 원인이 정확히 이것이다** — 진짜 하네스로 한 번만 돌렸으면 드러난다.
> (Step 1 `typesys`, Step 2 `rules`, Step 3 `compare` 에 이어 **네 번째**다)
> → 대역을 벗겨라. 파일 docstring 의 "Step 4-a 가 아직 stub 이라" 도 낡았다.
>
> ### R6-3. `STR-TEST-005`(Action 값 동일성) Finding 에 `node` 가 비어 있다
> 다른 TEST 규칙은 전부 `node=who` 인데 여기만 `fields={}` 로 나가 **Action 결과만 노드 이름 칸이 빈다.**
>
> ### R6-4. `engine/state.py` 의 `_delay_ms` 가 `${env.X}` 를 전개하지 않는다
> R5-1 이 params 를 통일했는데 **전이 `delay` 에 같은 문제가 남았다.**
> ```
> delay: "${env.SETTLE_MS}"  →  전이의 `delay` 가 정수로 풀리지 않았습니다: '${env.SETTLE_MS}'
> ```
> 조용히 틀리지 않고 오류로 멈추므로 R5-1 만큼 중대하지는 않다. 그러나 **R5-1 이 문제 삼은
> "같은 문서 안에서 자리마다 `${env.X}` 동작이 갈린다" 가 여기 남았고**, guide 가 `${config.X}` 만 말해
> **env 를 쓴 사람을 엉뚱한 데로 보낸다.** → **`config` → `state` → `env` 로 통일한다.**
>
> ### R6-5. 뮤테이션 생존 — 가드를 넣어라
> | 지워도 778 전부 통과 | 어디 | 왜 문제인가 |
> |---|---|---|
> | `_report_exit_code` 의 **not_run 분기** | `cli.py` | R4-3 대로 `state_unreachable` not_run 은 **오류 없이도 난다** → **종료 코드가 조용히 0** 이 될 수 있다 |
> | Reckon 대조쌍의 **`params` 상이 조건** | `harness.py` | 지우면 `input`·`params` 가 똑같은 중복 케이스 둘이 쌍으로 세어져 **`-007` 오탐** |
> | 경로 Spec 의 **실행 전 정적 검사** | `cli.py` | 기존 테스트가 모델 검증만 태우고 `check_registration` 을 안 태운다 |
> | `${env.X}` 를 마지막이 아닌 자리로 옮김 | `refs` 합성 | config 값이 `${state.X}` 를 품는 케이스가 없다 |
>
> ### R6-6. `STR-REF-002` 의 guide 를 자리 중립으로 (rules.md 개정 완료)
> `_resolve_node_file` 이 이 규칙을 재사용하는데 guide 는 *"파이프라인의 `source` 는…"* 이라고 말한다.
> 고쳐야 할 곳은 **노드 테스트의 `node` 필드**인데 AI 는 파이프라인을 본다 —
> **R2-6 이 세운 "규칙을 나누는 기준은 증상이 아니라 고치는 방법" 에 걸린다.**
> 규칙을 늘리지 않고 **guide 를 자리 중립으로 일반화했다.**
>
> ### R6-7. 등록소의 `.test.json` 에도 해시를 둔다
> R5-2 가 테스트를 *"노드 정의 묶음의 일부"* 로 승격시켰는데 해시가 없어
> schema.md 2절의 *"정적 검사 루트를 피해 등록소 파일을 직접 고치는 것을 막는다"* 가 안 걸린다.
> → **별도 필드**로 둔다(노드 해시에 섞으면 **기존 등록 id 의 해시가 전부 바뀐다**).
>
> ### R6-8. Spec 의 `tool.<name>.path` 가 경로 규칙을 안 탄다
> `${env.없는변수}/bin/pw` 도 `./bin/pw` 도 `spec add`·`check` 를 그냥 통과한다(실측).
> schema.md 13절: *"Spec 실행 시: 모든 경로가 전개 후 절대경로인지"*.
>
> ### R6-9. `rules.py` 자기 설명 카운트가 낡았다
> 파일 상단이 "59개 … GRAPH 2", 다른 곳이 "58개". **지금 61개 / GRAPH 3 / TEST 8** 이다.
>
> ### R6-10. (판정: 현행 유지) `node test <id>` 에 테스트가 없으면 종료 코드 `2` 가 맞다
> 사용자가 **명시적으로 "돌려라"** 라고 했는데 도구가 못 돈 것이다.
> `check <없는 경로>`=2 · R5-5(등록 거부=2)와 결이 같다.
> *"테스트가 없는 것은 오류가 아니다"* 는 **등록·목록 층**의 이야기지 **실행 요청**의 이야기가 아니다.
>
> ### R6-11. (기록만) `expand_all` 이 리터럴 `${...}` 기댓값을 불가능하게 만든다
> params 의 잔여 `${` 를 전부 막으므로, 템플릿 문자열을 기댓값으로 쓰는 Reckon 은 쓸 수 없다.
> R5-1 이 그렇게 지시했으므로 계약대로다. **이스케이프 문법을 지금 만들지 않는다** — 필요해지면 그때.


> ## ⚠️ 계약 개정 R5 (2026-08-16, conductor) — **R4~R1 보다 우선한다**
>
> **Step 5 E2E 검증**(CLI 로 끝까지 실행)이 찾아낸 결함이다. 단위테스트 749개가 통과하는 상태에서
> **CLI 표면에서만 드러난 것들**이라 성격이 다르다.
>
> ### R5-1. ★ `config` 값 안의 `${env.X}` 가 스크립트에 **전개되지 않은 채로** 간다 (중대)
> **검증과 전달이 서로 다른 문자열을 본다.**
> - `checks/pipeline.py` 의 `_check_one_value` 는 `refs.expand_path(str(value), env)` 로 **전개해서 검증**한다
> - `engine/runtime.py` 의 `params = refs.expand_state(refs.expand_config(pn.params, config), snapshot)` 는
>   **`expand_env` 를 부르지 않는다.** `engine/compare.py` 의 `_params_for` 도 같다
>
> 실측: `pagePath: "${env.DEMO_ROOT}/targets/home.html"` → 등록·경로검증 통과 →
> 스크립트가 `FileNotFoundError: '${env.DEMO_ROOT}/targets/home.html'` 로 터진다.
>
> **왜 중대한가.** schema.md 3절이 *"모든 경로는 절대 경로다. 단, 환경변수를 쓸 수 있다"* 를 못 박았고
> **이식성은 환경변수가 담당한다**(머신·CI 마다 값만 다르고 Spec 은 그대로 커밋)가 설계 전제인데,
> **스크립트에 값을 넘기는 자리에서만 그 전제가 깨진다.** `${env.X}` 는 `plan[].source`·노드 `source`·
> 노드 `script`·`report` 에서는 정상 동작하므로 **같은 문서 안에서 자리마다 동작이 갈린다.**
> 게다가 증상이 `FileNotFoundError` 라 **"대상 파일이 없다" 로 오독된다.**
>
> → **params(및 스크립트에 넘기는 모든 값)에도 env 를 전개한다. 합성 순서는 `config` → `state` → `env`**
> (config·state 값이 `${env.Y}` 를 품을 수 있으므로 env 가 마지막이다).
> → **전개 후에도 `${` 가 남으면 `STR-REF-007`** 로 잡는다 (`expand_path` 와 같은 논리).
> 리터럴로 통과시키면 나중에 엉뚱한 오류로 원인이 뭉개진다.
>
> ### R5-2. `strictler node test <node-id>` 가 사실상 동작하지 않는다
> `.test.json` 은 등록 대상이 아니고 `node add` 가 옆의 테스트 파일을 복사해 주지도 않는다.
> → **사용자가 등록소 디렉터리에 손으로 파일을 넣어야만** 성립한다.
> **등록소는 도구가 관리하는 영역**(해시로 무단 수정을 막는 바로 그 디렉터리)이라 이건 모델과 어긋나고,
> *"등록 후 원본을 지워도 된다"* 를 따르면 **단위테스트를 다시 돌릴 방법이 없어진다.**
>
> → **`node add`/`update` 가 옆의 `<노드파일>.test.json` 을 함께 복사한다.** (결정)
> 근거: schema.md 14절이 테스트를 **`<노드파일>.test.json`**, 즉 *노드 파일 옆*으로 규정했다 —
> 노드 정의 묶음의 일부지 **다섯 번째 등록 종류가 아니다**(종류는 넷으로 고정).
> `strictler node test <경로>` 형태도 그대로 유지한다.
>
> ### R5-3. `inputs` 가 서로 다른 앞단 둘 이상 → **등록 시점**에 `STR-GRAPH-003` (rules.md **60개**)
> 지금은 등록이 통과하고 **실행에서 규칙 id 없는 맨 `Finding`** 으로 터진다.
> `Args.input` 이 필드 하나인 것은 계약에 이미 있고 **파이프라인 JSON 만 봐도 판정 가능**하다.
> → `checks/pipeline.py` 로 옮기고 `STR-GRAPH-003`(슬롯 `{nodes}`)을 붙인다.
>
> ### R5-4. 참조 대상이 **검증 깨짐**이면 상위도 검증 깨짐이다 (전이적)
> 실측: `pl_e32a44f2` 가 `✕ 검증 깨짐` 인데 그것을 참조하는 `sp_04eb9f74` 는 `○` 로 나왔다.
> Spec 등록 검사가 형태만 보므로 재검증이 통과해 버린다. 그러나 **그 Spec 은 돌릴 수 없다** —
> `spec list` 만 보는 사람에게 거짓말을 한다. schema.md 2절이 *"상위를 전이적으로 재검증한다"* 라고 했다.
> → **참조 대상이 깨져 있으면 상위도 깨짐으로 표시한다.**
>
> ### R5-5. (판정: 현행 유지) `add` 실패의 종료 코드 `2` 는 **맞다**
> "정적 검사에 걸려 등록 안 됨" 이 lint 의 정상 동작처럼 보이지만, CLAUDE.md 의 3구분상
> **계약 위반은 "오류"** 다(위반은 *Target 이 기획과 다른 것*이지 스크립트가 계약을 어긴 것이 아니다).
> `remove`/`list` 의 깨짐 표시를 `1` 로 둔 것과 결이 다른 것은 **성격이 실제로 다르기 때문**이다 —
> 깨짐 표시는 상태 보고고, 등록 거부는 도구가 진행을 못 한 것이다. **바꾸지 마라.**
>
> ### R5-6. (기록만) `script add` 가 `STR-CONTRACT-005/-006/-007` 을 건너뛰는 것은 **설계대로**다
> 스크립트만으로는 노드 타입을 모른다. 판정 필드 없는 Reckon 스크립트는 **스크립트로는 등록되고
> 노드로 등록할 때 걸린다.** 이게 네 층 분리의 자연스러운 귀결이다.


> ## ⚠️ 계약 개정 R4 (2026-08-16, conductor) — **R3·R2·R1 보다 우선한다**
>
> Step 3 Gate 4 리뷰 2건의 판정. **핵심 교훈: 같은 규칙을 두 모듈이 각자 구현했더니 실제로 갈렸다.**
>
> ### R4-1. **구동 루프를 `engine/drive.py` 로 뽑아 하나로 만든다** ★★
> `runtime` 과 `compare` 가 **같은 구동 규칙을 각자 구현**했고, 리뷰가 실측으로 **셋 다 갈렸다**:
>
> | 규칙 | `runtime` | `compare` | 결과 |
> |---|---|---|---|
> | 구간 전이(R3-6) | `steps_after()`+`enter()` 로 한 칸씩 | `after_node()` 로 통째로 밀어버림 | **중간 상태를 기다리는 노드가 not_run** |
> | 실행 순서(R3-7) | `ready()` 재스캔 + drain | **정적 topo 정렬** | **통과할 노드에 거짓 not_run** |
> | 실행 시 해시 대조 | 있음 | **없음** | 등록소 파일을 고쳐도 그냥 돈다 |
>
> **두 번째는 lint 결과 자체가 틀리는 것이다** — 통과할 노드를 위반도 아닌 not run 으로 보고한다.
>
> → **`engine/drive.py` 를 신설**해 아래를 한 곳에 둔다. `runtime`·`compare` 가 **둘 다 이걸 쓴다**:
> - `ready()` 재스캔 기반 구동 (정적 topo 정렬 금지 — `when` 이 상태에 걸리므로 순서가 동적이다)
> - **구간 전이 drain** (`steps_after()` + `enter()`, R3-6)
> - **동시 실행 가능 노드는 파이프라인 선언 순서** (R3-7)
> - **실행 시점 해시 대조** (`STR-REG-001`) — schema.md 2·13절
>
> ⚠ `drive.py` 는 `runtime` 도 `compare` 도 import 하지 않는다 (`engine.result`·`engine.state`·`engine.exec` 까지만).
>
> ### R4-2. ★ **모든 노드는 네 상태 중 정확히 하나에 들어간다** (불변식)
> 리뷰가 **어느 상태에도 없이 리포트에서 조용히 사라지는 노드**를 재현했다. schema.md 9절이 금지하는 상태다.
> → **`pass` / `violation` / `not_run` / `error` — 파이프라인의 모든 노드가 정확히 하나.**
> **이걸 검사하는 테스트를 값 검증·비교 양쪽에 반드시 넣어라.** 한 클래스의 결함을 통째로 막는 가드다.
>
> ### R4-3. 미해결 `delay` 는 **0 이 아니라 "모름"** 이다
> `checks.reachability` 는 `"${config.settleMs}"` 를 `0` 으로 **추측**하고, `engine.state` 는 config 를 풀어
> 실제 값을 쓴다 → 정렬이 갈린다. schema.md 15절 예시가 바로 그 형태다.
>
> → **두 층으로 나눈다:**
> - **등록 시점**(`reachability`): 미해결 `delay` 는 **모름**이다. 그 순서에 의존하는 판정은
>   **`STR-STATE-006/007` 을 내지 않는다.** 알 수 없는 것으로 등록을 막지 않는다 (lint 는 보수적으로)
> - **실행 시점**(`drive`): config 가 풀렸으므로 **실제 값으로 판정**한다. 도달 불가로 밝혀지면
>   **`not_run(state_unreachable)`** 이다 — 등록 실패가 아니다. **config 가 도달성을 바꾸는 것은 정상**이고
>   (같은 파이프라인에 다른 Spec config), not run 은 애초에 정상 결과다
>
> ### R4-4. Reckon 출력의 판정 필드 = **`passed: bool`** (규칙 신설, rules.md **59개**)
> 엔진이 Reckon 출력에서 통과/위반을 읽으려면 규약이 필요한데 어느 문서에도 없었다.
> 구현자가 `passed: bool` 로 정한 것을 **확정한다.**
> → **`STR-CONTRACT-007` reckon-verdict-missing** 을 신설했다. **등록 시점에 강제한다**
> (`checks/script.py` 의 `check_node_type_form`) — 지금은 런타임에야 터져서
> schema.md 6절 *"돌리기 전에 잡아 자기 수정 신호를 준다"* 와 어긋난다.
>
> ### R4-5. `compare` 는 분배 시 **원래 반환값을 그대로** 넘긴다
> 지금 `registry.to_value()` 로 재구성해 **pydantic 모델**을 넘기는데, 값 검증 파이프라인은
> 앞단 스크립트의 **dataclass 인스턴스**를 그대로 넘긴다. `dataclasses.asdict`/`isinstance` 를 쓰는
> 스크립트가 갈린다 → **"스크립트 모양이 값 검증과 완전히 같다" 가 깨진다.**
> → 취합은 값을 **보관만** 하고 재구성하지 않는다. 타입 검증은 별개로 한다.
>
> ### R4-6. `compare` 도 target 무관한 Finding 을 dedupe 한다
> `_input_for` 를 target 루프 안에서 부르므로 배선 오류가 **target 수만큼 중복**된다.
> `runtime` 은 `dedupe(result.findings)` 를 거친다. ⚠ `STR-CMP-004` 처럼 **메시지에 target 이 박히는
> 것은 target 별로 나오는 게 정상**이다 — 그건 dedupe 대상이 아니다.
>
> ### R4-7. 대역이 결함을 가렸다 — **실제 구현으로 태워라**
> `tests/test_compare.py` 가 `NodeOutcome`/`RunResult`/`StateMachine`/`node_exec` 를 **전부 대역**으로
> 갈아끼워, 진짜 구현과의 정합이 **한 번도 안 태워졌다.** `FakeStateMachine.snapshot` 은 문자열을 주는데
> 진짜는 bool 을 준다. **R4-1 의 결함 두 개가 가려진 원인이 정확히 이것이다.**
> (Step 1 의 `typesys` autouse 대역, Step 2 의 `rules` 대역에 이어 **세 번째**다)
> → **Step 3-a 산출물은 merge 됐다. 대역을 벗기고 진짜 구현으로 돌려라.**
>
> ### R4-8. 공개 시그니처 추가분을 계약에 반영 (본문 대체)
> ```python
> def run_spec(spec, *, store, env, started_at_ms, spec_name: str = "") -> Report
> def run_plan_item(spec, index, *, store, env, started_at_ms, spec_name: str = "") -> list[Finding]
> def run_pipeline(pipeline, config, *, store, env, started_at_ms, path,
>                  tool: Mapping[str, Any] | None = None) -> RunResult
> ```
> `tool` 은 `STR-TOOL-001/002` 가 실행 시점 규칙이라 필요하고, `spec_name` 은 리포트 `path` 첫 조각용이다.
>
> ### R4-9. `engine/result.py` 를 얼린 것은 **conductor 의 계약 실수**였다
> Step 0 이 `raise NotImplementedError` stub 으로 만든 파일을 구현 없이 "누구도 고치지 않는다" 로 얼렸다 —
> 아무도 못 고치면 영원히 stub 이다. Step 3-a 가 계약에 적힌 필드 그대로 구현한 것을 **승인한다.**
> **지금부터 이 파일은 다시 확정이다** — 필드 추가는 conductor 를 거친다.
>
> ### R4-10. 테스트가 못 잡은 것들 (뮤테이션 생존) — 가드를 넣어라
> | 지워도 테스트가 통과한 것 | 어디 |
> |---|---|
> | `recheck_resolved` 호출 전체 | `runtime` (값 검증·비교 양쪽) |
> | `${state.__startedAt}` 의 params 주입 | `runtime` |
> | `all_same` 에 **float 반올림 정규화**를 심음 | `compare` ★ **"엔진은 `==` 만 안다" 의 핵심 불변식인데 가드가 없다** |
>
> `3.0` vs `3.0001` 이 **위반으로 나오는** 테스트를 넣어라.
>
> ### R4-11. (후순위, 기록만) 해시 재사용이 구현돼 있지 않다
> `run_pipeline` 이 매 실행마다 전 노드를 재검사한다. schema.md 2절 *"해시가 그대로면 재검사하지 않는다 —
> 등록은 검증 결과를 재사용하는 기제"* 와 어긋나지만 **성능 문제일 뿐**이라 지금 고치지 않는다.


> ## ⚠️ 계약 개정 R3 (2026-08-16, conductor) — **R2·R1 보다 우선한다**
>
> Step 2 Gate 4 리뷰 3건의 판정이다. 앞 개정·본문과 다르면 **여기가 맞다.**
> **child 는 이 문서를 고치지 마라.**
>
> ### R3-1. `typesys.primitives.check_allowed` 가 **세 실패 경로 전부 깨져 있다** ★ (main 결함)
> `rules.finding()` 에 `fields` 를 안 넘긴다. conductor 가 main 에서 직접 재현:
> ```
> dict[str,int] → StrictlerError: 규칙 STR-TYPE-001 … 자리표시자 값이 주어지지 않았습니다: file
> Optional[str] → STR-TYPE-002 … file
> Button        → STR-TYPE-003 … type, file
> ```
> **`STR-TYPE-001~003` 을 내는 유일한 자리가 전부 터진다.** Step 1 통합 결함(11건)과 정확히 같은 종류이고,
> 유일한 호출자인 `checks/script.py` 가 stub 이라 지금까지 안 걸렸다.
> `tests/test_typesys.py` 의 **autouse `rules.finding` 대역이 이 결함을 가렸다** — 대역을 제거한다.
>
> → **`check_allowed` 가 슬롯을 채우게 고치고, `checks/script.py` 는 복제한
> `_FORBIDDEN_TYPE_RULE`/`_check_type_allowed` 를 지우고 `check_allowed` 에 위임한다.** 이중 관리 소멸.
> (2-a 리뷰가 "뮤테이션 생존 2건" 으로 지적한 미커버 분기도 복제본 쪽이라 함께 사라진다)
>
> ### R3-2. `checks/script.py` — 통과형 `returnResult(args.input)` 에서 출력 타입을 못 뽑는다 ★
> `_value_type` 이 `ast.Attribute`(`args.input`)를 처리하지 않아 `output_type=""` 이 되고
> **교과서적 Action 이 `STR-CONTRACT-006` 으로 오탐된다.** conductor 재현:
> ```
> def runNode(args: Args):          # 반환 어노테이션 없음
>     return returnResult(args.input)
> → input_type='Form', output_type='', ['STR-CONTRACT-006']   ← 오탐
> ```
> Action 만의 문제가 아니다 — **CLAUDE.md 가 조건 분기의 표준 표현으로 못박은
> "스크립트가 그냥 `input` 을 반환한다" 가 모든 노드 타입에서 깨진다.**
> → `<진입점인자>.input` → `contract.input_type` 매핑을 추가한다.
>
> ### R3-3. **Action 자신의 계약도 대조한다** — `X.out == Action.in`
> 지금은 `X.out={count:int}` / `Action.in=out={junk:str}` / `Y.in={count:int}` 가 무검사 통과한다.
>
> **투명성의 뜻은 "Action 을 끼워도 X→Y 대응이 깨지지 않는다" 이지 "Action 은 타입검사 면제" 가 아니다.**
> Action 스크립트는 실제로 그 데이터를 `Args.input` 으로 받는다. 불일치는 **실행 시 계약 위반
> (= 도구가 못 돈 것)** 이 되는데, 정적으로 잡을 수 있는 것을 런타임까지 미룰 이유가 없다 —
> schema.md 6절이 **"AI 가 스크립트를 잘못 썼을 때 돌리기 전에 잡아 자기 수정 신호를 준다"** 를
> 형식 제한의 명시적 목적으로 적어뒀다.
> `input==output`(CONTRACT-006)이 이미 강제되므로 **`X.out == Action.in` 을 더하면 셋이 전부 같아진다**
> = schema.md 5절 "상단과 하단이 하나의 노드".
>
> → `check_wiring_types` 는 **Action 을 건너뛴 X→Y 대조에 더해 X.out == Action.in 도 본다.**
> 테스트 단언은 "낀 배선과 안 낀 배선의 **Finding 목록이 완전히 동일**" → **"판정(통과/위반)이 같다"** 로 완화.
>
> ### R3-4. 비교 파이프라인의 config 의존 검사는 **Spec 실행 시점**이다
> `STR-CMP-002` 는 `when: P` 인데 **실제로는 P 에서 못 돈다.** target 별 스크립트를 Spec 의
> `config` 가 채우므로 파이프라인 등록 시점엔 알 수 없기 때문이다. 부수적으로 비교 파이프라인의
> 노드 스크립트는 등록 시 계약·금지 검사를 **전혀 안 받는다**(`_contracts_by_target` 이 findings 를 버린다).
>
> 설계 결함이 아니라 **검사 시점 배정 누락**이다 — schema.md 13절의 세 번째 시점(Spec 실행)이 제자리다.
>
> → **`checks/pipeline.py` 에 진입점을 신설한다:**
> ```python
> def recheck_resolved(pipeline: Pipeline, config: Mapping[str, Any], *,
>                      store: Store, env: Mapping[str, str],
>                      source_path: str) -> list[Finding]
> ```
> config 가 풀린 뒤 **Spec 실행 시점에 engine 이 호출한다.** 하는 일:
> target 별 스크립트 `check_script` + `check_compare`(CMP-002/003) + 계약이 모인 뒤의
> `check_wiring_types`·`check_state_mapping` 재검.
> rules.md 의 `STR-CMP-002`/`-003` when 을 **`P R`** 로 개정했다.
> ⚠ 테스트가 쓰던 비정상 형태(`{"type":"str", "default": {…dict…}}`)도 정리한다.
>
> ### R3-5. `checks/pipeline.py` 공개 시그니처 정정 (본문 대체)
> ```python
> def check_wiring_types(pipeline, contracts, registry, source_path, *,
>                        node_types: Mapping[str, NodeType]) -> list[Finding]   # ★ node_types 필수
> def check_cycle(dag, source_path, *, exempt: Collection[str] = ()) -> list[Finding]
> def check_config_values(...) -> list[Finding]     # STR-PATH-004 + config default 주입 (R1-6)
> def build_registry(...) -> TypeRegistry
> def recheck_resolved(...) -> list[Finding]        # R3-4 신설
> ```
> **`node_types` 없이는 Action 투명성 구현이 원리적으로 불가능하다**(노드 타입을 알 방법이 없다).
> 본문의 `check_wiring_types(pipeline, contracts, registry, source_path)` 는 계약 쪽 결함이었다.
> `exempt` 는 `transitions.after` 로 상태만 미는 노드가 `STR-GRAPH-002` 오탐이 되는 것을 막는다.
>
> ### R3-6. `checks/reachability.py` — 같은 `after` 를 갖는 transition 이 둘 이상일 때 자기모순 ★
> `current = to` 로 **마지막 하나만** 반영하면서 `reachable_states` 에는 **전부** 넣는다.
> 한 `ReachResult` 안에서 두 필드가 반대를 말하고, **전이 선언 순서를 뒤집으면 등록 성패가 뒤집힌다.**
> `{after:A, to:loading}` + `{after:A, to:done, delay:5000}` 은 문법상 정상이고
> schema.md 8절이 `delay` 로 표현하려던 **구간** 그 자체다.
>
> → **구간으로 전개한다.** 같은 `after` 의 전이를 **`delay` 오름차순(없으면 0), 같으면 선언 순서**로
> 차례로 지나가고, **각 중간 상태에서 대기 중이던 노드를 그 자리에서 실행 가능**으로 본다.
> `current` 와 `reachable_states` 가 일치하게 된다.
>
> ### R3-7. **동시 실행 가능 노드의 순서 = 파이프라인 선언 순서** (계약)
> 지금 이 tie-break 가 `reachability.py` 모듈 안에서만 선언돼 있는데 **등록 성패를 가른다.**
> `engine.runtime` 이 다른 순서로 돌면 "등록은 통과했는데 실행에선 못 닿는다" 가 된다.
> → **계약으로 못 박는다: 동시에 실행 가능한 노드는 파이프라인의 `nodes` 선언 순서로 돈다.**
> `reachability.simulate().order` 가 **참조 구현**이고 `engine.runtime` 은 이 순서를 따른다.
>
> ### R3-8. `STR-STATE-007` 은 **`when` 으로 막힌 노드에만** 낸다
> 지금은 데이터 의존으로 막힌 노드에도 나가는데, 그 규칙의 guide 는 `when` 을 확인하라고 말한다 —
> `when` 이 아예 없는 노드에 그 가이드가 나가면 **AI 가 엉뚱한 곳을 고친다**(R2-6 과 같은 문제).
>
> **데이터 의존 막힘은 언제나 원인이 따로 보고된다:**
> | 데이터로 막힌 이유 | 이미 보고하는 규칙 |
> |---|---|
> | 존재하지 않는 노드 id 를 가리킴 | `STR-REF-003` |
> | 의존 대상이 도달 불가 | 그 대상이 `STR-STATE-007` 로 |
> | 순환 | `STR-GRAPH-001` |
>
> → **새 규칙이 필요 없다. defer 하면 된다** — 이 모듈이 스스로 세운 "이미 보고된 것은 다시 내지 않는다"
> 원칙과 일관되고, `-007` 의 guide 가 항상 유효해진다.
> (`ReachResult.unreachable` 에는 그대로 담는다 — 정보는 남기고 Finding 만 안 낸다)
>
> ### R3-9. `STR-STATE-006` 의 슬롯이 둘이 됐다 — `{name}` + `{mapped}` (rules.md 개정 완료)
> 노드 어휘와 파이프라인 상태 이름은 **다른 층**인데 하나만 보여서, JSON 의 어느 자리를 고쳐야 하는지가
> 안 드러났다. `when` 에 적힌 것과 전이를 추가할 자리가 다르다.
>
> ### R3-10. `check_tool_calls` 현행 유지 — 미선언 함수 + 미선언 경로는 위반이 아니다
> schema.md 6절 예시(`run_shell("...")`)와 표면상 어긋나 보이지만 **현행이 맞다.**
> 전부 잡으면 `open("/etc/hosts")` 가 `STR-TOOL-001` 이 되어 **"파일 IO 자유" 원칙을 깬다.**
> 어떤 함수가 외부 도구 호출인지 아는 것은 **내장 도메인 지식**이고 이 도구는 그걸 갖지 않는다.
> `run_shell` 류는 `STR-BAN-003`(직접 subprocess 호출)이 잡을 자리다.
> 실제로 잡히는 것은 **선언된 경로를 미선언 함수로** 또는 **선언된 함수를 미선언 경로로** 부르는 경우다.
>
> ### R3-11. 출력 타입이 dataclass 가 아니면 `STR-CONTRACT-003` (rules.md 개정 완료)
> `-> str` 같은 primitive 반환에 아무 규칙도 안 났다. guide 는 이미 "반환 타입은 dataclass" 라고
> 말하는데 **강제하는 규칙이 없었다.** 타입 동일성을 **구조로** 판정하는 이상 primitive 출력은 성립하지 않는다.
> 규칙을 새로 파지 않는다 — 두 경우 모두 "`returnResult()` 로 dataclass 를 내보내라" 로 고치기 때문이다.
>
> ### R3-12. `extract_contract` 의 두 번째 반환값이 항상 빈 목록이다
> 형태만 맞고 내용이 없어 **후속 Step 이 `extract_contract` 만 부르고 통과로 오해할 여지**가 있다.
> → 추출 단계 고유의 오류가 있으면 담고, 없으면 **docstring 에 "검증은 `check_script` 가 한다" 를 명시**한다.
> 어느 쪽인지 판단해서 보고하라.
>
> ### R3-13. `ENGINE_STATE_FIELDS` 3중 복제를 없앤다 — 정본은 `model/`
> `engine/state.py` · `refs.py` · `checks/script.py` 세 곳에 복제돼 있다.
> 규칙 위반은 아니지만 **엔진 제공 필드가 늘면 `STR-BAN-004` 오탐이 난다.**
> → **`model/__init__.py` 에 정본을 두고 셋이 import 한다.** `model` 은 최하층이라 순환이 없다.
> ⚠ `model/__init__.py` 는 확정 파일이지만 **이 항목에 한해 conductor 가 수정을 승인한다.**
> 상수 추가 외에는 손대지 마라.
>
> ### R3-14. `check_registration(kind="pipeline")` 정상 경로에 테스트가 없다
> CLI 가 쓸 유일한 진입점인데 유효한 파이프라인 파일로 부르는 테스트가 없다.


> ## ⚠️ 계약 개정 R2 (2026-08-16, conductor) — **R1 보다 우선한다**
>
> Step 1 **재리뷰**(Gate 4 recheck)가 찾아낸 것을 반영한 2차 개정이다. R1·본문과 다르면 **여기가 맞다.**
> **child 는 이 문서를 고치지 마라** — 심볼릭 링크로 모든 worktree 가 같은 파일을 본다.
>
> ### R2-1. `typesys/registry.py` — 병합된 필드의 타입 이름이 **엉뚱한 origin 스코프에서 해석된다** ★블로킹
> R1-1 이 "필드 타입 참조 해석은 같은 `origin` 스코프 안에서" 를 요구했는데, **병합(표현 층)을 거친
> 경로에서 그 규칙이 깨진다.** `_union_fields()` 가 `fields.setdefault(name, type)` 로 **맨 `TypeRef` 만**
> 저장해 그 필드를 기여한 멤버의 `origin` 이 소실되고, `build_model()` 이 `조회한 키의 origin` 에서
> 그 이름을 다시 찾는다. **conductor 가 직접 재현했다:**
>
> | 케이스 | 증상 |
> |---|---|
> | `sense.Args(input:str)` + `reckon.Args(input:str, params:P)`, `P(expected:int)` | `build_model(sense.Args)` → `StrictlerError: 타입 P 를 ...` — **이 설계에서 가장 흔한 노드 조합**이 도구 오류로 터진다 |
> | `a.py: Btn(label:str), Args(input:Btn)` / `b.py: Widget(label:str), Args(input:Widget)` | `same_definition` 은 `True`(설계대로)인데 `build_model(b.Args)` 만 터진다. schema.md 7절 "이름이 달라도 구조가 같으면 같은 타입" 을 정면으로 못 쓰게 만든다 |
> | `a.py: Button(icon:str), Small(x:int)` / `b.py: Button(label:str), Big(x:int, b:Button)` | `build_model(a.Small)` 에 `b` 필드가 생기고 **엉뚱한 `Button` 에 바인딩된다 — 예외조차 안 난다(조용한 오답)** |
>
> → **`_union_fields` 가 필드마다 "해석 완료된 `TypeKey`" 를 함께 들고 다니고, `_py_type` 이 그걸 쓴다.**
> 조회한 키의 `origin` 으로 재해석하지 않는다. 구현 방식은 담당자 재량이나 **위 세 케이스가 전부
> 통과해야 하고, 셋 다 테스트로 고정한다.**
>
> ⚠ 이건 **"고쳐야 할 세 번째"**(도구가 못 돈 것)다. 위반도 not run 도 아니다 — CLAUDE.md 의 3구분 참조.
>
> ### R2-2. `typesys` 공개 표면을 계약으로 못 박는다
> `checks/script.py`(2-a) · `checks/pipeline.py`(2-b) · `engine/exec.py`(3-a) · `testing/harness.py`(4-a) 가
> 전부 이걸 호출한다. **추측하지 말고 아래를 그대로 쓴다.**
>
> ```python
> class TypeKey(NamedTuple):        # 등록기 키
>     origin: str                   # 선언한 스크립트 경로
>     name: str
>
> class FieldSpec:
>     def __init__(self, name: str, type: TypeRef) -> None
>
> class DataclassSpec:
>     def __init__(self, name: str, fields: tuple[FieldSpec, ...], origin: str) -> None   # ★ origin 필수
>     key: TypeKey                                    # property → TypeKey(origin, name)
>     def raw_set(self) -> frozenset[tuple[str, str]]
>
> class TypeRegistry:
>     def register(self, spec: DataclassSpec) -> None
>     def normalize(self) -> None                     # register 전부 → normalize 1회 → 조회
>     def field_set(self, key: TypeKey) -> frozenset[tuple[str, str]]
>     def same_definition(self, a: TypeKey, b: TypeKey) -> bool
>     def is_subset(self, a: TypeKey, b: TypeKey) -> bool
>     def merge_components(self) -> dict[TypeKey, TypeKey]
>     def build_model(self, key: TypeKey) -> type[BaseModel]
>     def to_value(self, key: TypeKey, raw: Any) -> Any
> ```
>
> **호출 순서 계약: `register()` 전부 → `normalize()` 한 번 → 조회.** 정규화 전 조회는 `StrictlerError` 다.
>
> ### R2-3. `DataclassSpec.origin` 에서 기본값 `= ""` 를 없앤다 (필수 인자)
> 기본값이 있으면 등록 주체(`checks/script.py`, **다른 child**)가 빠뜨렸을 때 모든 dataclass 가 `""`
> 스코프로 몰리고, **R1-1 이 없애려던 `Args` 충돌이 그대로 되살아난다.**
> 계약 본문·R1 의 `origin: str = ""` 표기는 이걸로 대체된다.
>
> ### R2-4. `STR-TYPE-006` 의 `path` 를 채운다
> `-007` 은 `path=key.origin` 을 채우는데 `-006` 은 비어 있다. 병합은 등록기 전역 연산이라 단일 `path` 가
> 없다는 건 맞지만, 리포트에 위치가 없으면 원인을 못 찾는다.
> → **성분 멤버를 정렬한 첫 번째의 `origin`** 을 넣는다 (결정적이어야 하므로 정렬).
>
> ### R2-5. 등록기의 미지 타입 오류에 `STR-TYPE-003` 을 붙인다
> `_unknown_type_message` 경로가 맨 `StrictlerError` 로 나간다. `STR-TYPE-003`(unsupported-type, 슬롯 없음)이
> 정확히 그 자리다. `checks/script.py` 가 1차로 잡더라도 **2선 방어에도 id 는 있어야 한다** — R1-7 과 같은 논리.
>
> ### R2-6. 새 규칙 `STR-REF-007` unresolved-reference (rules.md **58개**)
> R1-8 이 "잔여 `${` 를 에러로" 만 정하고 id 를 지정하지 않아 구현자가 `STR-REF-006` 을 골랐다.
> 그런데 `${config.y}` 는 **문법이 정상**이다 — 잘못된 건 전개 순서다. `-006` 의 guide
> ("네임스페이스를 반드시 붙입니다")를 받은 AI 는 **엉뚱한 곳을 고친다.**
>
> | 입력 | 규칙 |
> |---|---|
> | `${X}` / `${vars.X}` / `${env.}` — 네임스페이스 없음·모름·이름 비었음 | **`STR-REF-006`** malformed |
> | `${env.HOME/x` — 닫히지 않음 | **`STR-REF-006`** malformed |
> | `/x/${config.y}/z` — 문법은 정상인데 안 풀림 | **`STR-REF-007`** unresolved ← 신설 |
>
> **규칙을 나누는 기준은 "증상" 이 아니라 "고치는 방법" 이다.**
>
> ### R2-7. `refs` 는 `rules` 를 의존해도 된다 — guide 손복제를 없앤다
> 계약 본문이 `refs` 의 의존을 `model`·`errors` 로 적어둔 탓에 `refs.py` 가 **rules.md 의 guide 문구를
> 손으로 복제**하고 있다. R1-3 이 `slots` 를 데이터로 둔 취지(코드/문서 분리 방지)와 이 모듈만 어긋난다.
> **`rules` 는 `errors` 에만 의존하는 최하층이라 순환이 생기지 않는다**(conductor 확인).
> → `refs` 의 의존에 **`rules` 를 추가**한다. 손복제한 문구를 `rules.render()`/`rules.finding()` 로 바꾼다.
>
> ### R2-8. `STR-REG-004` 의 message 에 `{id}` 슬롯을 넣었다 (rules.md 개정 완료)
> 코드가 `fields={"id":…, "ref":…}` 로 **같은 값을 두 이름으로** 넘기는데 규칙에는 슬롯이 없었다.
> R1-3 대로 미선언 필드를 거부하면 런타임에 터진다. `STR-REG-002` 가 이미 `{id}` 를 쓰는 선례가 있다.
> → rules.md 를 개정했다. 코드는 **`fields={"id": ref_id}` 하나만** 남긴다.
>
> ### R2-9. `store` 의 나머지 raw `UnicodeDecodeError` 도 감싼다
> R1 이 `_read_source` 만 고쳤는데 같은 논리가 두 자리에 미반영이다.
> - `Store.read()` — **정적 검사 루트를 피해 등록소 파일을 직접 고치는 것이 바로 `STR-REG-001` 이 상정하는
>   시나리오다.** `verify_hash` 호출 순서가 보장되지 않으면 raw 예외가 먼저 난다
> - `load_index()` — `JSONDecodeError` 는 감쌌지만 `UnicodeDecodeError` 는 안 감쌌다


> ## ⚠️ 계약 개정 R1 (2026-08-16, conductor) — **본문보다 이 절이 우선한다**
>
> Step 1 Gate 4 리뷰 4건이 찾아낸 계약 결함을 반영한 개정이다. 본문의 해당 항목과 다르면 **여기가 맞다.**
> **이 절과 본문을 child 가 고치지 마라** — MODULES.md 는 심볼릭 링크로 4개 worktree 가 같은 파일을 본다.
>
> ### R1-1. `typesys/registry.py` 의 키를 `(origin, name)` 으로 바꾼다 ★
> 지금 registry 는 dataclass **이름**을 전역 키로 쓴다. 그런데 schema.md 6절상 **모든 노드 스크립트가
> `Args` 라는 고정 이름을 선언**하므로, 파이프라인의 두 번째 노드를 등록하는 순간
> `dataclass 'Args' 가 서로 다른 정의로 두 번 등록됐습니다` 로 터진다. Step 2-b 가 착수하면 즉시 발생한다.
>
> - **키는 `(origin, name)`.** `origin` 은 그 dataclass 를 선언한 스크립트 경로다
> - **필드 타입 참조 해석은 같은 `origin` 스코프 안에서** 한다 (`Button` 은 그 스크립트의 `Button`)
> - **구조 동일성 판정은 여전히 전역**이다 — schema.md 7절 "이름이 달라도 구조가 같으면 같은 타입.
>   구조적 동일성이지 명목적 동일성이 아니다"
> - 즉 **이름은 스코프 안에서만 의미가 있고, 타입 동일성은 구조로 전역 판정**한다
> - 공개 시그니처(`field_set`, `same_definition`, `register` 등)는 이에 맞게 `origin` 을 받도록 개정한다
>
> ### R1-2. `rules.finding()` 시그니처 — `**fields` → `fields: dict`
> `finding(rule_id, *, path, node, **fields)` 는 keyword-only 파라미터가 **동명 슬롯을 잡아먹는다.**
> `STR-PATH-001`(`{path}`), `STR-TOOL-002`(`{path}`), `STR-CMP-002`(`{node}`) 세 규칙이 렌더 불가능하다.
> `{path}` 는 rules.md 원문 슬롯이라 이름을 바꿀 수도 없다.
>
> → **`finding(rule_id, *, path: str, node: str, fields: dict[str, object] | None = None)`** 로 개정.
> 슬롯 값은 `fields` 딕셔너리로만 넘긴다. 이름 충돌이 구조적으로 불가능해진다.
>
> ### R1-3. 규칙 엔트리에 `slots` 필드를 추가한다
> `_fill` 은 슬롯 값이 없으면 `StrictlerError` 를 낸다(옳다 — 리포트에 `{cycle}` 이 새면 검사기 버그다).
> 그런데 **어떤 규칙에 어떤 슬롯이 필요한지가 어디에도 없다.** 후속 Step 담당자가 런타임에 터뜨린다.
>
> → 규칙 엔트리에 **`slots: tuple[str, ...]`** 을 추가한다 (message + guide 양쪽에서 추출).
> 코드와 문서가 갈라지지 않도록 **표가 아니라 데이터로** 둔다. `finding()` 이 이걸로 누락을 검증한다.
> ⚠ `STR-TYPE-004` 의 슬롯은 **`{in}`** 이다 — 파이썬 예약어라 `fields={"in": ...}` 형태로만 넘길 수 있다.
>
> ### R1-4. `rules.render()` 는 guide 의 슬롯도 채운다 (구현이 옳다)
> 본문은 `message.format(**fields) + "\n" + guide` 로 적혀 있으나, **rules.md 의 guide 문구 자체가
> 슬롯을 갖는다** (`STR-GRAPH-001` `{cycle}`, `STR-TOOL-002` `{path}`, `STR-CONFIG-001` `{names}`,
> `STR-TEST-002/003/004` 등은 슬롯이 guide 에만 있다). 안 채우면 리포트에 `{cycle}` 이 그대로 샌다.
> 또 `str.format` 은 쓸 수 없다 — guide 안의 `${env.X}` 를 필드 참조로 해석해 터진다. 자체 슬롯 정규식이 맞다.
>
> ### R1-5. `refs.parse_ref` 시그니처 (코드가 옳다)
> `parse_ref(value: str, expected: EntryKind | None = None) -> tuple[EntryKind, str]` 로 개정.
> `expected` 없이는 STR-REG-003(자리와 접두 불일치)을 낼 수 없다.
>
> ### R1-6. 책임 경계 두 건을 못 박는다
> - **`STR-PATH-004`(path: true config)는 `checks/pipeline.py`(Step 2-b) 가 낸다.** `refs` 는 기제만 제공한다
> - **`config` 의 `default` 주입은 `checks/pipeline.py` 의 책임이다.** `refs` 가 받는 config 는
>   이미 default 가 채워진 것이다 → `refs` 에서 미해결 `${config.X}` 는 진짜 required 누락이므로
>   `STR-CONFIG-001` 재사용이 정당해진다
>
> ### R1-7. 새 규칙 3개 (rules.md 57개로 증가)
> | 규칙 | 무엇 |
> |---|---|
> | `STR-TYPE-006` merge-field-conflict | 부분집합 연결 성분 합집합 시 같은 필드명의 타입이 갈림 |
> | `STR-TYPE-007` dataclass-cycle | dataclass 자기·상호 참조 |
> | `STR-REF-006` malformed-reference | 네임스페이스 없음/모름/이름 비었음 |
>
> 셋 다 **규칙 id 없는 raw 오류로 나가던 것에 id 를 붙인 것**이다.
>
> ### R1-8. `expand_path` 는 잔여 `${` 를 에러로 잡는다
> 경로 해석 시점엔 모든 참조가 풀려 있어야 한다. 남은 `${config.y}` 나 닫히지 않은 `${env.HOME/x` 를
> 리터럴 경로 조각으로 통과시키면 나중에 "파일 없음" 으로 원인이 뭉개진다.
> (`expand_config`/`expand_state` 는 다른 네임스페이스를 남기는 게 맞다 — 합성 순서 때문)
>
> ### R1-9. 경로 전개는 3단계다 — `~` → env → **`~` 재전개**
> schema.md 3절이 개정됐다. `PROJECT_ROOT=~/proj` 는 흔한 설정인데 지금은
> 앞자리면 "상대경로입니다" **오진단**, 중간자리면 `/srv/~/proj/x` 가 **조용히 통과**한다.
> `~` 를 허용한 논리가 env 값 안의 `~` 에도 그대로 적용된다.


> Step 0 스캐폴딩의 산출물. **이후 병렬 child 들이 서로 안 겹치게 하는 계약 문서**다.
> 근거는 `schema.md`(설계 정본)와 `rules.md`(규칙 54개).
>
> **규칙:**
> 1. **자기 담당 파일만 고친다.** 남의 파일 시그니처가 필요하면 여기 적힌 것을 그대로 믿고 쓴다.
> 2. 여기 적힌 **공개 시그니처는 계약이다.** 바꿔야 하면 conductor 에게 보고하고 이 문서를 먼저 고친다.
> 3. **내부 헬퍼는 자유롭게 추가**해도 된다. 공개 표면만 계약이다.
> 4. `raise NotImplementedError("Step N에서 구현")` 이 남아 있으면 그건 그 Step 담당자의 몫이다.

---

## 0. 의존 방향

```
                      model  ────────────────┐   (누구에게도 의존하지 않는다)
                        │                    │
        errors ─────────┤                    │
          │             │                    │
        rules ── report │                    │
          │             │                    │
        refs ── deps ───┤                    │
          │             │                    │
    typesys.primitives ─┤                    │
          │             │                    │
    typesys.registry    │                    │
          │             │                    │
      store.entries ── store.graph           │
          │                                  │
    checks.script ── checks.node ── checks.pipeline ── checks.reachability
          │                                  │
    engine.state ── engine.exec ── engine.result ─┬─ engine.runtime
                                                  └─ engine.compare
                                             │
                                    testing.harness
                                             │
                                           cli
```

**역방향 import 금지.** 순환이 생기면 그건 경계를 잘못 그은 것이다.

**★ `engine.runtime` 과 `engine.compare` 는 서로를 import 하지 않는다.**
공용 결과 타입(`RunResult`/`NodeOutcome`)은 **`engine.result`** 에 있고 둘 다 거기에만 의존한다.
`run_spec` 이 `kind` 를 보고 비교 엔진으로 디스패치하는 구조는 **그대로 유지**하되
(`schema.md` 3·12절), 그 디스패치는 `run_plan_item` **안에서 지역 import** 로 한다.
top-level 양방향 import 를 만들면 실제로 `ImportError` 로 터진다.

---

## 1. Step 배정 — 파일 교집합 0

| Step | child | 담당 파일 | 건드리면 안 되는 것 |
|---|---|---|---|
| **1-a** 타입시스템 | 1 | `typesys/primitives.py`, `typesys/registry.py` | 그 외 전부 |
| **1-b** 규칙+리포터 | 2 | `rules.py`, `report.py` | `errors.py` (Step 0 확정) |
| **1-c** 경로·참조 | 3 | `refs.py` | — |
| **1-d** 등록소 | 4 | `store/entries.py`, `store/graph.py` | — |
| **2-a** 스크립트 AST 검사 | 1 | `checks/script.py` | — |
| **2-b** 스키마 로더 검증 | 2 | `checks/node.py`, `checks/pipeline.py`, `checks/__init__.py` | — |
| **2-c** 도달가능성 | 3 | `checks/reachability.py` | — |
| **3-a** 값 검증 엔진 | 1 | `engine/state.py`, `engine/exec.py`, `engine/runtime.py` | — |
| **3-b** 비교 엔진 | 2 | `engine/compare.py` | — |
| **4-a** 단위테스트 하네스 | 1 | `testing/harness.py` | — |
| **4-b** CLI 배선 | 2 | `cli.py` | — |

**아래 넷은 Step 0 에서 확정됐다. 누구도 고치지 않는다 — 고쳐야 하면 conductor 를 거친다.**

| 파일 | 왜 확정인가 |
|---|---|
| `model/__init__.py` | 모든 층이 여기 의존한다 |
| `errors.py` | 모든 층이 여기 의존한다 |
| **`engine/result.py`** | **Step 3-a(runtime)·3-b(compare) 가 둘 다 쓴다.** 어느 쪽도 이 파일을 고치지 않는다 — 고치면 두 child 의 파일 교집합이 생긴다 |
| **`pyproject.toml`** | 전원이 건드릴 유인이 있는 유일한 파일이다. 의존성 추가가 필요하면 conductor 에게 보고한다 (테스트용 `pytest` 는 이미 `[dependency-groups] dev` 에 있다) |
| **`engine/__init__.py`** | `NodeOutcome`/`RunResult` 재수출이 들어 있다. **재수출은 지금 있는 것이 전부다** — Step 3-a 가 `run_spec` 을, 3-b 가 `run_compare_pipeline` 을 여기 추가하려 들면 두 child 의 파일 교집합이 생긴다. 필요하면 `from strictler.engine.runtime import run_spec` 처럼 모듈에서 직접 import 하라 |

---

## 2. 모듈별 계약

### `src/strictler/model/__init__.py` — ✅ **완성**

**책임.** 네 층(Spec / Pipeline / Node / Script)의 JSON 구조를 pydantic 모델로 정의한다.
**JSON 문서의 형태만** 정의하고, 값의 의미 검증은 하지 않는다.

**의존.** 없음. (최하층)
**근거.** `schema.md` 3·4·5·14절.

```python
EntryKind    = Literal["script","node","pipeline","spec"]
ID_PREFIXES: dict[str, EntryKind]        # {"sc_":"script","nd_":"node","pl_":"pipeline","sp_":"spec"}
NodeType     = Literal["vantage","sense","perceive","reckon","action"]
PipelineKind = Literal["verify","compare"]
STRICT       = ConfigDict(extra="forbid")

# Spec (3절)
class SpecInfo:  description: str; version: str = ""
class ToolDecl:  path: str; functions: list[str] = []
class PlanItem:  source: str; description: str
                 config: dict[str, Any] = {}; report: str | None = None
class Spec:      info: SpecInfo; tool: dict[str, ToolDecl] = {}; plan: list[PlanItem]

# Pipeline (4절)
class PipelineInfo: name: str; description: str; kind: PipelineKind
class ConfigDecl:   type: str; required: bool; default: Any = None
                    description: str = ""; path: bool = False
class States:       values: list[str]; initial: str
class Transition:   after: str; to: str; delay: int | str | None = None
class When:         state: str
class PipelineNode: id: str; source: str
                    inputs: dict[str,str] = {}; params: dict[str,Any] = {}
                    states: dict[str,str] = {}; when: When | None = None
class Pipeline:     info: PipelineInfo; config: dict[str, ConfigDecl] = {}
                    states: States; transitions: list[Transition] = []
                    nodes: list[PipelineNode]
                    targets: list[str] = []; compare: list[str] = []

# Node (5절)
class NodeInfo: name: str; description: str
class Node:     info: NodeInfo; type: NodeType; script: str

# NodeTest (14절)
class TestCase: name: str; args: dict[str,Any]; expect: dict[str,Any] | None = None
class NodeTest: node: str; cases: list[TestCase]
```

⚠ **혼동 주의.** 여기 쓰인 `X | None` / `dict[...]` 은 **엔진 자신의 코드**다.
`schema.md` 7절의 "`dict` 금지 / `Optional` 금지"는 **사용자가 작성하는 노드 스크립트의
타입 선언**에 적용되는 규칙이지 엔진 구현에 적용되는 규칙이 아니다.

⚠ **`targets` / `compare` 는 `list = []` 기본값**이다. `kind: verify` 인데 비어 있지 않으면
파이프라인 검사가 잡는다. `STR-CMP-003`(2개 미만) 판정에도 빈 리스트로 충분하다.

---

### `src/strictler/errors.py` — ✅ **완성**

**책임.** 결과 1건(`Finding`)과 도구 자신의 예외(`StrictlerError`).

**의존.** 없음.
**근거.** `schema.md` 9·11절.

```python
Status       = Literal["pass","violation","not_run","error"]     # 이 넷이 전부. skip 없음
NotRunReason = Literal["data_dependency","state_unreachable"]    # not run 전파 경로. 정확히 둘

class NotRunCause:  node: str; reason: NotRunReason
class Finding:      status: Status
                    path: str = ""           # "login.json > plan[0] > login-flow"
                    node: str = ""
                    rule_id: str = ""        # 직렬화 시 "rule" 로 나감
                    message: str = ""        # 규칙 message + guide 가 이어붙은 것
                    cause: NotRunCause | None = None

class StrictlerError(Exception):
    def __init__(self, message: str, findings: list[Finding] | None = None)
    .message: str
    .findings: list[Finding]
```

**`reason` 은 자유 문자열이 아니라 `Literal` 둘이다.** `schema.md` 9절이 not run 전파 경로를
**정확히 둘**로 확정했으므로(데이터 의존 / 상태 의존), 새 사유를 만들지 마라 —
필요하면 conductor 를 거쳐 `schema.md` 부터 고친다.

**★ 반드시 지킬 것.** 위반(`violation`)과 not run 은 **정상 결과**다 — `Finding` 으로 수집한다.
`StrictlerError` 는 **도구가 못 돈 것**에만 쓴다. 이 구분이 흐려지면 위반을 오류처럼 다루거나
(불필요한 복구 로직) 오류를 위반처럼 다루게 된다(거짓 리포트).

---

### `src/strictler/rules.py` — Step 1-b

**책임.** 규칙 테이블 54개와 `Finding` 생성 헬퍼. **`guide` 를 메시지 뒤에 이어붙이는 자리.**

**의존.** `errors`.
**근거.** `rules.md` 전체, `schema.md` 11절.

```python
RuleWhen   = Literal["node-register","pipeline-register","run","test","list"]
RuleStatus = Literal["active","deprecated"]

class Rule:  id: str; name: str; since: str; status: RuleStatus
             when: tuple[RuleWhen, ...]; message: str; guide: str      # frozen

RULES: dict[str, Rule]                                   # ← 54개로 채운다

def get_rule(rule_id: str) -> Rule
def rules_for(when: RuleWhen) -> list[Rule]
def render(rule_id: str, **fields: object) -> str        # message.format(**fields) + "\n" + guide
def finding(rule_id: str, *, status: Status = "error", path: str = "", node: str = "",
            cause: NotRunCause | None = None, **fields: object) -> Finding
```

**`finding()` 이 다른 모듈들이 가장 많이 쓰는 진입점**이다. 검사기는 규칙 id 와 자리표시자 값만 준다.
`rules.md` 2절 표의 `when` 열: N=`node-register`, P=`pipeline-register`, R=`run`, T=`test`.
`STR-REG-004`/`-005` 는 목록 표시 전용이라 `list`.

---

### `src/strictler/report.py` — Step 1-b

**책임.** 값 검증 리포트와 비교 리포트. **둘을 섞지 않는다** (필드가 안 겹친다).

**의존.** `errors`.
**근거.** `schema.md` 11·12절.

```python
class Summary:       passed: int = 0     # 직렬화 시 "pass"
                     violation: int = 0; not_run: int = 0; error: int = 0
class Report:        summary: Summary; results: list[Finding] = []
class CompareEntry:  same: bool; values: dict[str, Any]
class CompareReport(RootModel[dict[str, CompareEntry]])   # {노드 id: CompareEntry}

def build_report(findings: list[Finding]) -> Report
def render_json(report: Report) -> str                    # ↓ 직렬화 계약 참조
def render_text(report: Report) -> str
def build_compare_report(values: dict[str, dict[str, Any]]) -> CompareReport
def write_compare_report(report: CompareReport, path: Path) -> None
```

**flat 리스트 + 경로 필드.** 중첩으로 쌓지 않는다. 누적 단위는 **노드별**.

**★ `render_json` 직렬화 계약 — 세 가지를 전부 만족해야 한다:**

1. `by_alias=True` — `rule_id` → `rule`, `Summary.passed` → `pass`
2. `exclude_none=True` — `cause` 가 `None` 인 항목에서 `"cause": null` 이 나가지 않는다
3. **값이 빈 문자열인 필드는 출력에서 생략한다** — `rule_id`/`message`/`path`/`node` 의 기본값이
   `""` 라 그냥 덤프하면 `"rule": "", "message": ""` 가 딸려 나간다

**결과 JSON 은 `schema.md` 11절 예시와 키 구성까지 일치해야 한다.** 그 예시가 계약이다:

| 예시의 항목 | 있는 키 | **없는 키** |
|---|---|---|
| `status: "violation"` | `path` `node` `status` `rule` `message` | **`cause` 없음** |
| `status: "not_run"` | `path` `node` `status` `cause` | **`rule`·`message` 없음** |
| `status: "error"` | `path` `node` `status` `rule` `message` | **`cause` 없음** |

`by_alias=True` 만으로는 `{"rule":"","message":"","cause":null}` 이 새어나가 예시와 어긋난다.
(2)·(3) 은 별칭 처리와 별개의 요구다 — **셋 다 필요하다.**
`Summary` 는 4상태 카운트가 전부 나가야 하므로 **`0` 이어도 생략하지 않는다** —
생략 규칙은 **빈 문자열**과 **`None`** 에만 적용한다.

---

### `src/strictler/refs.py` — Step 1-c

**책임.** 참조 문법 4종 전개와 경로 규칙.

**의존.** `model`(`EntryKind`), `errors`.
**근거.** `schema.md` 2·3절, `rules.md` PATH·REG.

```python
NAMESPACES: frozenset[str]        # {"env","config","state","ref"}
PLACEHOLDER_RE: str               # r"\$\{(?P<ns>[a-z]+)\.(?P<name>[^}]+)\}"

class Placeholder:  ns: str; name: str; raw: str; start: int; end: int
    def __init__(self, ns, name, raw, start, end)

def collect_placeholders(value: str) -> list[Placeholder]
def is_ref(value: str) -> bool                                  # 값 전체가 ${ref.<id>} 하나인가
def parse_ref(value: str) -> tuple[EntryKind, str]              # → ("node","nd_e5f6a7b8")
def expand_env(value: str, env: Mapping[str,str]) -> str
def expand_path(value: str, env: Mapping[str,str]) -> Path      # ~ → env → 절대경로 검증
def expand_config(value: Any, config: Mapping[str,Any], target: str = "") -> Any
def expand_state(value: Any, state: Mapping[str,Any]) -> Any
```

**경로 규칙:** `~` 전개 → 환경변수 전개 → 절대경로가 아니면 **무조건 에러**.
`STR-PATH-001`(상대경로) / `-002`(env 미정의) / `-003`(env 값이 상대경로) / `-004`(`path:true` config).

**`expand_config` 의 `target`:** 주어지면 **`targets.<target>` 에서 먼저 찾고 없으면 공통에서**.
둘 다 없으면 `STR-CMP-004`. 문자열 전체가 참조 하나면 **타입을 보존해** 값 자체를 준다
(`"${config.expectedFields}"` → `2`, 문자열 `"2"` 가 아니라).

**`expand_state`:** `__` 접두는 엔진 제공 필드 예약(`__startedAt`, epoch ms 정수).
사용자 상태 이름에 쓰면 `STR-STATE-001`.

---

### `src/strictler/deps.py` — 의존성 확인 (추가)

**책임.** 스크립트의 PEP 723 헤더를 읽고 **선언한 패키지가 현재 환경에 있는지** 본다.
**격리를 만들지 않는다** — 확인하고 설치 명령을 안내하는 것이 전부다.

**의존.** `rules`, `errors`, `packaging`(런타임 의존성).
**근거.** `schema.md` 6절 *"스크립트의 의존성 — 격리하지 않는다"*, `rules.md` DEP.

```python
BLOCK_TYPE: str                   # "script" — PEP 723 블록 종류 이름

class Declared:                   # frozen dataclass
    present: bool = False         # 헤더가 있었는가. **없는 것이 정상이다**
    requires_python: str = ""
    dependencies: tuple[str, ...] = ()   # PEP 508 문자열 원문

def read_header(source: str, path: str) -> tuple[Declared, list[Finding]]   # STR-DEP-002
def declared_dependencies(source: str) -> tuple[str, ...]   # 관대하게 — 등록소 기록용
def check_dependencies(source: str, path: str, known: Iterable[str] = ()) -> list[Finding]
def install_command(requirement: str, known: Iterable[str] = ()) -> str
def missing_module_hint(source: str, module: str) -> str    # 헤더에 선언된 것을 못 찾았을 때
def missing_submodule_hint(module: str) -> str              # `a.b` 인데 `a` 는 설치돼 있을 때
```

**★ `--with` 는 선언적이다.** `uv tool install --with` 는 이전 `--with` 를 유지하지 않고
**적은 것만 남긴다.** 문제가 된 것 하나만 안내하면 그대로 따른 AI 가 **다른 스크립트의
의존성을 지운다** — lint 도구에서 잘못된 안내는 잘못된 리포트에 준한다.
그래서 `install_command` 는 `known`(= `Store.declared_dependencies()`)을 합쳐
**완전한 명령**을 만든다. `known` 이 비면 단순 형태로 폴백하고 **예외를 내지 않는다** —
안내 문자열을 만드는 자리라서 여기서 터지면 원래 `Finding` 이 사라진다.

**★ 설치돼 있는데 "없습니다" 라고 말하지 않는다.** `pydantic.없는것` 은 pydantic 이 없는
것이 아니라 서브모듈이 없는 것이다 — `missing_submodule_hint` 가 그 경우를 가르고,
그때는 **형제 파일 문단을 붙이지 않는다**(원인이 확정된 자리에 다른 방향을 얹지 않는다).

**`uv run --script` 로 격리 프로세스를 띄우지 않는다** — `schema.md` 16절의 폐기된 안이다.
스크립트는 strictler 와 같은 프로세스에 로드되므로 `import` 가 strictler 환경에서 풀린다.

**등록소 전체를 훑어 충돌 쌍을 찾는 코드를 만들지 마라.** 환경에는 패키지가 한 벌만
깔리므로 호환 불가 요구가 둘 있으면 반드시 한쪽이 `STR-DEP-003` 에 걸린다.

**설치 여부·버전은 `importlib.metadata`**, 이름 정규화는 **PEP 503**(`My_Pkg == my-pkg`).
환경 마커가 이 환경에 해당하지 않는 요구는 건너뛴다.

---

### `src/strictler/typesys/primitives.py` — Step 1-a

**책임.** 허용 타입 어휘와 타입 표현 파싱.

**의존.** `errors`, `rules`.
**근거.** `schema.md` 7절, `rules.md` TYPE.

```python
PRIMITIVES: frozenset[str]   # {"int","float","str","bool","bytes"}  ← list[T] 는 별도
FORBIDDEN:  frozenset[str]   # {"dict","Dict","Optional","None","NoneType","Any"}

class TypeRef:
    def __init__(self, name: str, args: tuple[TypeRef, ...] = ())
    name: str; args: tuple[TypeRef, ...]
    def __str__(self) -> str                 # "list[Button]" 로 되돌린다 (에러 메시지용)

def parse_type(expr: str) -> TypeRef
def is_primitive(t: TypeRef) -> bool
def is_list(t: TypeRef) -> bool
def element_type(t: TypeRef) -> TypeRef
def check_allowed(t: TypeRef, *, known: frozenset[str], path: str, node: str = "") -> list[Finding]
```

`known` = 그 스크립트가 선언한 dataclass 이름들.
`dict`→`STR-TYPE-001`, `Optional`/`None`→`STR-TYPE-002`, 그 밖→`STR-TYPE-003`.
**파이프라인 `config` 선언의 `type` 도 같은 어휘**를 쓴다(`STR-TYPE-005`) — 어휘를 두 벌 두지 않는다.

---

### `src/strictler/typesys/registry.py` — Step 1-a

**책임.** dataclass 등록기 — 집합 정규화, 부분집합 병합, 그래프 검사용 동일성 판정.
⚠ 이름이 `registry` 지만 **등록소(`store`)와 무관하다.** 이건 *타입 등록기*다.

**의존.** `typesys.primitives`, `errors`.
**근거.** `schema.md` 7절.

```python
class FieldSpec:      def __init__(self, name: str, type: TypeRef)
class DataclassSpec:  def __init__(self, name: str, fields: tuple[FieldSpec,...], origin: str = "")

class TypeRegistry:
    def register(self, spec: DataclassSpec) -> None
    def normalize(self) -> None                                   # 위상 정렬 후 바닥부터
    def field_set(self, name: str) -> frozenset[tuple[str,str]]   # (필드명, 타입표기)
    def same_definition(self, a: str, b: str) -> bool             # ★ 그래프 검사 — 엄격 동일성
    def is_subset(self, a: str, b: str) -> bool
    def merge_components(self) -> dict[str,str]                   # {원래 이름: 병합 클래스 이름}
    def build_model(self, name: str) -> type[BaseModel]           # pydantic 경계 검증용
    def to_value(self, name: str, raw: Any) -> Any
```

**사용 순서:** `register()` 전부 → `normalize()` 한 번 → 이후 조회.

**★ 두 층을 절대 섞지 마라:**
- **그래프 검사(정적)** = 선언된 정의, **엄격한 동일성** (`same_definition`)
- **데이터 취급(런타임)** = 표현, 부분집합 연결 성분을 합집합으로 병합 (`merge_components`)

병합이 타입 검사를 느슨하게 만드는 게 아니다 — 병합은 표현 층에서만 일어난다.
`ButtonCount(count:int) == MenuCount(count:int)` 로 판정되는 오배선 탐지력 약화는 **감수한다**
(값의 의미는 Reckon 이 잡는다). 최소 필드 수 조건이나 "이 타입은 고유하다" 표시를 넣지 마라.

---

### `src/strictler/store/entries.py` — Step 1-d

**책임.** 등록소 인덱스와 CRUD. **저장만 책임진다** — 정적 검사는 `checks` 가 하고 순서는 CLI 가 잡는다.

**의존.** `model`, `refs`, `errors`.
**근거.** `schema.md` 2절, `rules.md` REG.

```python
SUBDIRS: dict[str,str]    # {"script":"scripts","node":"nodes","pipeline":"pipelines","spec":"specs"}

class RegistryEntry:  id: str; kind: EntryKind; name: str; hash: str; registered_at: str
                      test_hash: str = ""       # R6-7
                      refs: list[str] = []
                      dependencies: list[str] = []   # 스크립트의 PEP 723 선언 (원문)
                      broken: str = ""          # "" | "ref" | "validation"
                      broken_detail: str = ""
class RegistryIndex:  version: int = 1; entries: dict[str, RegistryEntry] = {}

def default_home() -> Path            # $STRICTLER_HOME 또는 ~/.strictler
def hash_file(path: Path) -> str
def new_id(kind: EntryKind) -> str    # "nd_e5f6a7b8"

class Store:
    def __init__(self, home: Path | None = None)
    def load_index(self) -> RegistryIndex
    def save_index(self, index: RegistryIndex) -> None
    def add(self, kind: EntryKind, source: Path, name: str = "") -> RegistryEntry
    def list(self, kind: EntryKind | None = None) -> list[RegistryEntry]
    def show(self, entry_id: str) -> RegistryEntry
    def update(self, entry_id: str, source: Path) -> RegistryEntry   # ★ id 유지
    def remove(self, entry_id: str) -> None                          # ★ 참조 있어도 막지 않는다
    def path_of(self, entry_id: str) -> Path
    def read(self, entry_id: str) -> str
    def verify_hash(self, entry_id: str) -> bool                     # STR-REG-001
    def declared_dependencies(self) -> list[str]     # 전 스크립트 PEP 723 선언의 합집합
```

**등록은 편의가 아니라 검증 결과를 재사용하는 기제다.** 해시가 그대로면 재검사하지 않는다.

**`dependencies` 는 `kind == "script"` 일 때만 채워진다** (`deps.declared_dependencies`).
`schema.md` 6절이 격리를 뒤집을 조건으로 못 박은 *"같은 패키지의 호환되지 않는 버전을
요구하는 스크립트가 둘 이상"* 을 **도구가 스스로 검출**하기 위한 재료다.

---

### `src/strictler/store/graph.py` — Step 1-d

**책임.** 참조 그래프, 역방향 추적, 깨짐 두 종류 판정.

**의존.** `store.entries`, `errors`, `rules`.
**근거.** `schema.md` 2절, `rules.md` `STR-REG-004`/`-005`.

```python
class RefGraph:
    def __init__(self, entries: dict[str, RegistryEntry])
    @classmethod
    def build(cls, store: Store) -> RefGraph
    def dependencies(self, entry_id: str) -> list[str]           # 아래쪽
    def dependents(self, entry_id: str) -> list[str]             # 위쪽 1단계
    def transitive_dependents(self, entry_id: str) -> list[str]  # 위쪽 전이적
    def broken_refs(self) -> list[Finding]                       # STR-REG-004
    def revalidate(self, store: Store, entry_id: str) -> list[Finding]   # STR-REG-005
```

| 깨짐 | 원인 | 참조는 |
|---|---|---|
| 참조 깨짐 (`-004`) | 대상 **삭제** | 끊겼다 — 눈에 보인다 |
| 검증 깨짐 (`-005`) | 대상 **수정** | 멀쩡하다 — **조용히 무효화된 것을 드러내야 한다** |

**둘 다 실패가 아니라 상태 표시다.** 재검증 실패가 수정을 막지 않는다 —
막으면 교착이 생긴다(하위를 고치려면 상위를 먼저 고쳐야 하는데 상위는 하위 때문에 못 고친다).

---

### `src/strictler/checks/__init__.py` — Step 2-b

**책임.** 등록/수정 시점 정적 검사의 진입점. 종류별 검사기로 넘기는 디스패처.

**의존.** `checks.node`, `checks.pipeline`, `checks.script`, `store.entries`.
**근거.** `schema.md` 13절.

```python
def check_registration(kind: EntryKind, source: Path, store: Store) -> list[Finding]
```

빈 목록이면 통과 — **그때만 등록소에 저장된다.**

---

### `src/strictler/checks/script.py` — Step 2-a

**책임.** 스크립트 AST 검사. **스크립트를 돌리지 않는다** — `ast` 로 선언과 형식만 본다.

**의존.** `typesys.*`, `errors`, `rules`, `deps`, `model`(`NodeType`).
**근거.** `schema.md` 6·13절, `rules.md` CONTRACT·TYPE·BAN·DEP·TOOL.

```python
class ScriptContract:
    def __init__(self, path: str)
    path: str
    dataclasses: dict[str, DataclassSpec]
    input_type:  str    # Args.input 의 타입 이름. 없으면 ""
    params_type: str
    state_type:  str
    state_names: tuple[str, ...]   # ★ Args.state 필드 이름 = 노드가 요구하는 상태 이름
    output_type: str               # returnResult() 로 나가는 dataclass 이름
    tool_calls:  list[tuple[str,str]]   # (함수명, 실행파일 경로 인자)

def extract_contract(source: str, path: str) -> tuple[ScriptContract, list[Finding]]
def check_script(source: str, path: str, node_type: NodeType | None = None,
                 known_dependencies: Iterable[str] = ()) -> list[Finding]
def check_entrypoint(contract) -> list[Finding]                    # CONTRACT-001~003
def check_args_shape(contract) -> list[Finding]                    # CONTRACT-004, STATE-001
def check_types(contract) -> list[Finding]                         # TYPE-001~003
def check_bans(source, path, contract) -> list[Finding]            # BAN-001~004
def check_node_type_form(contract, node_type: NodeType) -> list[Finding]   # CONTRACT-005/006
def check_tool_calls(contract, tool: dict[str, object]) -> list[Finding]   # TOOL-001/002 (실행 시점)
```

**`check_script` 는 `deps.check_dependencies` 도 함께 돌린다** (`STR-DEP-001/002/003`).
헤더를 읽어 지금 환경에 있는지 `importlib.metadata` 로 보기만 하므로
*"스크립트를 돌리지 않는다"* 는 그대로다.

**★ `ScriptContract` 가 이 프로젝트에서 가장 많이 재사용되는 자료구조다.**
파이프라인 검사(배선 타입·상태 매핑)·엔진(`Args` 조립)·단위테스트가 전부 이걸 재료로 쓴다.
필드를 추가해야 하면 conductor 에게 보고하고 이 문서를 먼저 고칠 것.

**노드 타입별로 갈리는 유일한 검사가 `check_node_type_form` 이다:**
- Reckon → `Args.params` 에 기댓값 필드 필수 (`STR-CONTRACT-005`)
- Action → `Args.input` 타입 == 반환 타입 (`STR-CONTRACT-006`)

**완벽한 정적 검사는 목표가 아니다.** `__import__("ti"+"me")` 는 못 막는다.
사전에 추측할 수 있는 행위만 막고 **에러 메시지의 자연어 가이드로 메운다** —
작성 주체가 AI 라는 전제 덕에 유효하다.

---

### `src/strictler/checks/node.py` — Step 2-b

**책임.** 노드 JSON 로드와 등록 시 검증. = 노드 JSON 검사 + **그 스크립트를 노드 타입과 함께 검사**.

**의존.** `checks.script`, `model`, `refs`, `store.entries`, `errors`, `rules`.
**근거.** `schema.md` 5·13절.

```python
def load_node(raw: Mapping[str,Any], path: str) -> tuple[Node | None, list[Finding]]
def resolve_script(node: Node, *, store: Store, env: Mapping[str,str],
                   config: Mapping[str,Any] | None = None,
                   target: str = "") -> tuple[Path | None, list[Finding]]
def check_node(node: Node, source_path: str, *, store: Store,
               env: Mapping[str,str]) -> tuple[ScriptContract | None, list[Finding]]
```

`resolve_script` 가 `config`/`target` 을 받는 이유: 비교 파이프라인에서 `script` 자리에
`${config.buttonScript}` 가 와서 **target 별로 스크립트가 갈리기** 때문이다 (`schema.md` 12절).

`check_node` 는 성공 시 `ScriptContract` 를 함께 준다 — **파이프라인 검사가 이걸 쓴다.**

---

### `src/strictler/checks/pipeline.py` — Step 2-b

**책임.** 파이프라인 JSON 로드와 등록 시 검증.

**의존.** `checks.node`, `checks.script`, `checks.reachability`, `typesys.registry`, `model`, `refs`, `store.entries`.
**근거.** `schema.md` 4·13절, `rules.md` REF·GRAPH·TYPE·STATE·CONFIG·CMP.

```python
def load_pipeline(raw: Mapping[str,Any], path: str) -> tuple[Pipeline | None, list[Finding]]
def build_dag(pipeline: Pipeline) -> dict[str, list[str]]     # {노드 id: 의존 노드 id 들}
def check_pipeline(pipeline: Pipeline, source_path: str, *, store: Store,
                   env: Mapping[str,str]) -> tuple[dict[str, ScriptContract], list[Finding]]
def check_cycle(dag, source_path: str) -> list[Finding]                      # GRAPH-001/002
def check_wiring_types(pipeline, contracts, registry: TypeRegistry,
                       source_path) -> list[Finding]                         # TYPE-004
def check_state_mapping(pipeline, contracts, source_path) -> list[Finding]   # STATE-001~004
def check_transitions(pipeline, source_path) -> list[Finding]                # REF-004, STATE-005
def check_config_decls(pipeline, source_path) -> list[Finding]               # TYPE-005
def check_compare(pipeline, contracts_by_target: dict[str, dict[str, ScriptContract]],
                  source_path) -> list[Finding]                              # REF-005, CMP-002/003
```

**`inputs` 가 DAG 를 만든다.** 별도 `edges` 섹션이 없다 — 입력 참조가 곧 의존 관계다.

**`check_wiring_types` 주의:** **Action 은 투명하다.**
`X ──▶ Action ──▶ Y` 는 실은 `X ──▶ Y` 이므로 **Action 을 건너뛰고** 상·하단 계약을 대조한다.

**`check_compare` 주의:** target 별로 갈려도 되는 것은 **`script` 경로와 `Args.params` 뿐**이다.
input/output/state 타입은 노드에 귀속되어 공통이어야 비교가 성립한다 (`STR-CMP-002`).

---

### `src/strictler/checks/reachability.py` — Step 2-c

**책임.** 도달 가능성 판정기. **파이프라인 등록 시의 핵심 검사.**

**의존.** `model`, `errors`, `rules`.
**근거.** `schema.md` 13절, `rules.md` `STR-STATE-006`/`-007`.

```python
class ReachResult:
    def __init__(self)
    reachable: set[str]; unreachable: set[str]
    reachable_states: set[str]; order: list[str]

def simulate(pipeline: Pipeline,
             node_states: dict[str, dict[str,str]]) -> ReachResult
def check_reachability(pipeline: Pipeline, node_states: dict[str, dict[str,str]],
                       source_path: str) -> list[Finding]
```

`node_states` = `{노드 id: {노드 어휘: 파이프라인 상태 이름}}` — `when` 을 파이프라인 상태로 번역하는 데 쓴다.

**★ 왜 정적으로 판정되나:** `transitions` 는 **시간만** 다루고 노드 결과에 따른 분기 문법이
존재하지 않으므로(`schema.md` 10절), 실행 없이 전개가 결정된다.

**전개 규칙:** 초기 상태에서 시작 → (1) `inputs` 의존이 전부 만족되고 (2) `when` 상태가 현재
상태와 맞는 노드를 실행 가능으로 표시 → (3) `transitions.after` 가 그 노드면 상태 전이 →
더 진행이 없을 때까지 반복. 남은 노드가 `unreachable`.

**도달 불가 노드는 실패도 not run 도 아니라 4상태 어디에도 안 들어간다** → **등록 자체를 막는다.**

---

### `src/strictler/engine/state.py` — Step 3-a

**책임.** 파이프라인 상태머신. **전이는 런타임이 수행하고 노드는 읽기만 한다.**

**의존.** `model`, `refs`.
**근거.** `schema.md` 8절.

```python
ENGINE_FIELDS: tuple[str,...]     # ("__startedAt",)

class StateMachine:
    def __init__(self, states: States, transitions: list[Transition],
                 config: Mapping[str,Any], started_at_ms: int)
    @property
    def current(self) -> str
    def after_node(self, node_id: str) -> None
    def matches(self, node_state_mapping: Mapping[str,str], when_state: str) -> bool
    def snapshot(self, node_state_mapping: Mapping[str,str]) -> dict[str,Any]
    def blocked_by(self, node_id: str) -> list[str]      # 이 노드 실패로 안 일어나는 전이의 도착 상태들
```

**`started_at_ms` 는 호출자가 준다** — 엔진 안에서 시각을 읽지 않으면 테스트가 결정적이 된다.
실행 시각 형식은 **epoch 밀리초 정수** (문자열 포맷을 주면 로케일·타임존 비결정성이 새어들어온다).

**`blocked_by` 가 `not_run` 전파의 두 번째 경로(상태 의존)를 계산하는 재료다.**

---

### `src/strictler/engine/exec.py` — Step 3-a

**책임.** 스크립트 하나를 로드·실행하고 input/output 을 검증한다.

**의존.** `checks.script`(`ScriptContract`), `typesys.registry`, `errors`, `rules`.
**근거.** `schema.md` 6·7절.

```python
def load_script(path: Path) -> ModuleType
def build_args(module: ModuleType, contract: ScriptContract, *,
               input_value: Any = None, params: Mapping[str,Any] | None = None,
               state: Mapping[str,Any] | None = None) -> Any
def invoke(module: ModuleType, args: Any) -> Any          # runNode → returnResult 값
def validate_input(contract, value, registry: TypeRegistry, *, path: str, node: str) -> list[Finding]
def validate_output(contract, value, registry: TypeRegistry, *, path: str, node: str) -> list[Finding]
```

**샌드박싱은 하지 않는다.** ESLint·vite·jest 전부 사용자 코드를 그냥 로드해 실행한다 —
lint 계열의 표준 신뢰 모델을 그대로 따른다.

**의존성 격리도 없다** (`schema.md` 6절). 스크립트는 strictler 와 **같은 프로세스**에
로드되므로 `import` 가 strictler 환경에서 풀린다 — `uv run` 이 바깥에서 격리해 준다는
것은 **사실이 아니다**(`uv tool install` 로 전역 설치하면 그 "바깥" 이 없다).
`load_script`/`invoke` 는 `ModuleNotFoundError` 가 났을 때 그 모듈이 PEP 723 헤더에
선언돼 있으면 **설치 명령을 에러 메시지에 붙인다**(`deps.missing_module_hint`).

**`build_args` 주의:** `Args` 의 세 필드는 **쓰는 것만 선언**돼 있다. 입력이 없는 Vantage 는
`input` 필드가 아예 없으므로 **선언에 없는 필드를 채우면 안 된다.**

스크립트가 예외를 내면 그건 **오류**(`error`)다 — 위반이 아니다.

---

### `src/strictler/engine/result.py` — ✅ **확정 (Step 3 시작 전)**

**책임.** `runtime` 과 `compare` 가 **둘 다** 쓰는 실행 결과 자료구조. 이게 전부다 —
로직은 없다.

**의존.** `errors` 뿐. (`runtime`·`compare` 어느 쪽도 import 하지 않는다)
**근거.** `schema.md` 9·12절.

```python
class NodeOutcome:
    def __init__(self, node_id: str, status: Status)
    node_id: str; status: Status; value: Any; findings: list[Finding]
class RunResult:
    def __init__(self)
    outcomes: dict[str, NodeOutcome]; findings: list[Finding]
```

**★ Step 3-a 도 3-b 도 이 파일을 고치지 않는다.** 둘의 파일 교집합이 0 이려면 공용 타입이
어느 한쪽에 살 수 없다. 필드를 추가해야 하면 conductor 를 거친다.

비교 파이프라인에서는 `NodeOutcome.value` 가 `{target: 출력값}` 묶음이다 —
**취합/분배는 엔진이 하고 스크립트는 자기 target 값 하나만 다룬다.**

`engine/__init__.py` 가 `NodeOutcome`/`RunResult` 를 재수출한다.

---

### `src/strictler/engine/runtime.py` — Step 3-a

**책임.** 값 검증 파이프라인 구동, `not_run` 전파, Spec 단위 실행.

**의존.** `engine.result`, `engine.state`, `engine.exec`, `checks.*`, `report`, `store.*`.
**근거.** `schema.md` 9·11·13절.

**★ `engine.compare` 를 top-level 로 import 하지 마라.** `RunResult`/`NodeOutcome` 은
`engine.result` 에서 가져온다. `kind` 디스패치 구조는 그대로 두되, `run_plan_item` **안에서**
```python
from strictler.engine.compare import run_compare_pipeline
```
로 부른다. top-level 로 올리면 `compare` 와 양방향이 되어 `ImportError` 다.

```python
from strictler.engine.result import NodeOutcome, RunResult   # ← 여기서 온다

def run_spec(spec: Spec, *, store: Store, env: Mapping[str,str],
             started_at_ms: int) -> Report
def run_plan_item(spec: Spec, index: int, *, store: Store, env: Mapping[str,str],
                  started_at_ms: int) -> list[Finding]
def run_pipeline(pipeline: Pipeline, config: Mapping[str,Any], *, store: Store,
                 env: Mapping[str,str], started_at_ms: int, path: str) -> RunResult
def propagate_not_run(pipeline: Pipeline, result: RunResult, path: str) -> list[Finding]
def topo_order(dag: dict[str, list[str]]) -> list[str]
```

**★ 이건 lint 다.** 복구·재시도·되돌아가기·대체 경로를 **만들지 마라.**
실패하면 그 지점에서 진행하지 않는다. 그게 전부다.

**★ `propagate_not_run` 의 전파 경로가 둘이다 — 두 번째를 놓치기 쉽다:**
1. **데이터 의존** — 실패한 노드의 출력을 `inputs` 로 받는 노드들
2. **상태 의존** — `transitions.after` 가 실패하면 그 전이가 안 일어나고, 그 상태를 `when` 으로
   기다리던 노드들은 영원히 조건을 만족하지 못한다

**노드를 전수 검사해서** 도달 불가가 된 것을 싹 다 바꾼다. **원인은 바꾸는 그 시점에 적는다**
(`Finding.cause`).

**엔진에는 skip 개념이 없다.** "앞단 결과가 이러면 아무것도 안 한다"는 스크립트가 `input` 을
그대로 반환하는 것으로 표현되고, 엔진은 평소대로 타입만 검사한다.

**증거 캡처(스크린샷)를 넣지 마라** — 위반은 정상 결과라 수습할 것이 없다.

`run_plan_item` 이 `path` 문자열(`"login.json > plan[0] > login-flow"`)을 만드는 자리다.

---

### `src/strictler/engine/compare.py` — Step 3-b

**책임.** 비교 파이프라인 구동 — target 별 실행·취합·동등 비교.

**의존.** `engine.result`(`RunResult`), `report`, `refs`, `store.entries`, `model`.
**근거.** `schema.md` 12절.

**★ `engine.runtime` 을 import 하지 마라.** `runtime` 이 `kind` 를 보고 이쪽으로
디스패치하므로 반대 방향 import 는 순환이다. 공용 타입은 `engine.result` 에서 가져온다.

```python
from strictler.engine.result import RunResult                # ← 여기서 온다

def resolve_target_config(config: Mapping[str,Any], target: str) -> dict[str,Any]
def run_compare_pipeline(pipeline: Pipeline, config: Mapping[str,Any], *, store: Store,
                         env: Mapping[str,str], started_at_ms: int,
                         path: str) -> tuple[RunResult, CompareReport]
def collect_target_values(result: RunResult, node_id: str) -> dict[str,Any]
def all_same(values: Mapping[str,Any]) -> bool
```

**노드도 그래프도 한 벌이다.** target 별로 갈리는 것은 **스크립트와 그 `params` 뿐**.

**취합/분배는 엔진이 한다.** 스크립트는 자기 target 의 값 하나만 받고 하나만 내놓는다 →
**스크립트의 모양이 값 검증 파이프라인과 완전히 같다.** 비교용이라고 시그니처가 달라지지 않는다.

**Reckon 이 필요 없다** — Verdict 를 엔진이 만든다. "내장 동작 없음" 원칙과 충돌하지 않는다:
**동등 비교는 도메인 지식이 아니라 일반 연산**이다.

**★ 허용 오차도 무시 필드도 엔진에 두지 마라.** 정규화는 스크립트가 알아서 한다.
**엔진은 `==` 만 안다.** 판정은 **목록 전부가 같은 값이냐**이지 짝지어 비교가 아니다.

---

### `src/strictler/testing/harness.py` — Step 4-a

**책임.** 노드 단위테스트 실행. **등록 검사와 달리 스크립트를 실제로 돌린다.**

**의존.** `engine.exec`, `checks.node`, `checks.script`, `model`, `store.entries`, `refs`.
**근거.** `schema.md` 14절, `rules.md` TEST.

```python
def load_node_test(path: Path, env: Mapping[str,str]) -> tuple[NodeTest | None, list[Finding]]
def run_node_test(node_test: NodeTest, *, store: Store, env: Mapping[str,str]) -> list[Finding]
def run_case(node: Node, contract: ScriptContract, script_path: Path, case: TestCase, *,
             env: Mapping[str,str]) -> tuple[Any, list[Finding]]
def materialize_args(raw: Mapping[str,Any], contract: ScriptContract,
                     env: Mapping[str,str]) -> Any
def check_action_transparency(case: TestCase, input_value: Any, output_value: Any) -> list[Finding]
def check_reckon_contrast(cases: list[TestCase], outputs: list[Any]) -> list[Finding]
```

**케이스마다 순서대로 3단계:** ① `args` 가 `Args` 선언에 맞나(`STR-TEST-001` — **테스트 쪽이
틀린 경우**라 메시지가 달라야 한다) → ② `runNode` 가 예외 없이 끝나나(`-002`) →
③ 반환값이 선언된 출력 타입에 맞나(`-003`).

**노드 타입별 추가:**
- Action → **값 동일성**(`-005`). 사용자가 `expect` 를 안 써도 된다 — **기대값이 곧 입력**
- Reckon → **기댓값 반응성**. `input` 이 같고 `params` 만 다른 **통과/위반 쌍**이 없으면
  **경고**(`-006`), 있는데 판정이 같으면 **오류**(`-007`)

**`bytes` fixture** 는 `{"$file": "<절대경로>"}` 로 주고 `materialize_args` 가 읽어 채운다.

**★ 결정성 검사(2회 실행 비교)를 넣지 마라** — Perceive 안에서 AI 를 부르면 당연히 실패한다.

---

### `src/strictler/cli.py` — Step 4-b (골격은 Step 0 완성)

**책임.** argparse 표면과 핸들러 배선.

**의존.** 전부.
**근거.** `schema.md` 2절.

```python
KINDS: tuple[EntryKind,...]              # ("script","node","pipeline","spec")
def build_parser() -> argparse.ArgumentParser
def main(argv: Sequence[str] | None = None) -> int

# 핸들러 — 시그니처 고정, 본체가 Step 4-b 의 몫
def cmd_add(args)  / cmd_list(args)  / cmd_show(args)
def cmd_update(args) / cmd_remove(args) / cmd_node_test(args) / cmd_check(args)
```

**파싱 구조는 Step 0 에서 완성됐다** (`strictler --help`, `strictler node --help` 동작 확인).
Step 4-b 는 **핸들러 본체만** 채운다 — 서브커맨드 구조를 바꿔야 하면 conductor 를 거친다.

**종료 코드 규약** (`schema.md` 9절의 4상태와 맞춘다):

| 코드 | 의미 |
|---|---|
| `0` | 통과만 있음 |
| `1` | **위반 또는 not run** 이 있음 — 정상 결과, 도구는 제대로 돌았다 |
| `2` | **오류** (도구가 못 돌았다) 또는 사용법 오류 |

`add` 는 `checks.check_registration` → (통과 시) `store.add` 순서다.
`update` 는 `store.update` 후 `RefGraph.revalidate` 로 상위를 전이적으로 재검증한다.

---

## 3. 전 모듈 공통 — 반드시 지킬 것

1. **위반 ≠ 오류.** 위반과 not run 은 `Finding` 으로 수집하고, `StrictlerError` 는 도구가 못 돈 것에만.
2. **복구 로직을 만들지 마라.** 재시도·대체 경로·`skipWhen`·전이 조건 표현식 — 전부 폐기된 안이다.
3. **`schema.md` 16절의 폐기된 안을 다시 제안하지 마라.**
4. **에러 메시지에 자연어 가이드를 넣어라.** 읽는 주체가 AI 이고, 그 문구가 곧 자기 수정 루프의 성능이다.
5. **경로는 언제나 절대경로.** `refs.expand_path` 를 거치지 않고 경로를 만들지 마라.
6. **엔진 안에서 시각·랜덤을 읽지 마라.** `started_at_ms` 는 호출자가 준다.
7. **테스트는 각 Step 담당자가 자기 모듈에 대해 `tests/` 아래 추가한다.** Step 0 은 빈 패키지만 뒀다.
   **`pytest` 는 이미 `pyproject.toml` 의 `[dependency-groups] dev` 에 있다** — `uv run pytest` 로 돈다.
   **`pyproject.toml` 을 고치지 마라.** 새 의존성이 필요하면 conductor 에게 보고한다
   (전원이 이 파일을 건드리면 "파일 교집합 0" 이 깨진다).
8. **`engine.runtime` ↔ `engine.compare` 를 서로 import 하지 마라.** 공용 타입은 `engine.result`.
