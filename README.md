# strictler

**기획대로 돌아가는지를 검사하는 도구.** QA 의 프로그램화, lint 의 인간 버전.

판정 기준은 코딩 컨벤션이 아니라 **기획**이고, 판정 근거는 AST 나 DOM 트리가 아니라 **형상(shape)** 이다.
HTML 구조가 아무리 파멸적이어도 기획대로 보이고 동작하면 통과다.

## 네 층 = 네 파일

```
Spec (JSON)  →  Pipeline (JSON)  →  Node (JSON)  →  Script (.py)
   기획           DAG 구성           동작 정의        실제 동작
```

**strictler 에 내장된 동작은 하나도 없다.** 다섯 노드 타입(Vantage / Sense / Perceive /
Reckon / Action)의 본체는 전부 사용자가 공급하는 스크립트이고, strictler 가 파는 것은
**파이프라인 엔진과 스키마**다.

## 설치와 사용

```bash
uv sync
uv run strictler --help
```

```
strictler <종류> add|list|show|update|remove     # <종류> = script|node|pipeline|spec
strictler node test <id>                         # 노드 단위테스트 (실제 실행)
strictler check <spec-id>                        # 검사 실행
```

## 문서

| 문서 | 무엇 |
|---|---|
| [`docs/AUTHORING.md`](docs/AUTHORING.md) | **저작 가이드** — 요구에서 네 층 파일까지, 단위테스트 붙이는 법, 결과 읽는 법, 실패 카탈로그. `examples/home-check` 를 따라간다 |
| [`docs/schema.md`](docs/schema.md) | **확정 사항 정본** — 네 층 구조·등록소·타입 시스템·노드 계약·상태머신·리포트·비교 파이프라인 |
| [`docs/rules.md`](docs/rules.md) | 검사 규칙 **61개** + ID 체계 + **증가 이력**(어떤 규칙이 왜 추가됐는지) |
| [`docs/MODULES.md`](docs/MODULES.md) | 모듈 경계와 공개 시그니처. 최상단 **계약 개정 R1~R6** 이 본문보다 우선한다 |

`schema.md` 16절에 **폐기된 안과 그 이유**가 있다.

## 예제

[`examples/home-check`](examples/home-check) — 다섯 노드 타입과 두 파이프라인 종류(값 검증 /
비교)를 전부 태우는 예제. 등록 없이 파일 경로만으로 끝까지 돈다.
[`tests/test_examples.py`](tests/test_examples.py) 가 이걸 CLI 로 그대로 태워 회귀를 막는다.

## 결과 상태 — 네 가지

이 도구의 사고 방식은 lint 의 것이지 실행 엔진의 것이 아니다. **"실패" 도 정상적인 상태다.**

| | 무엇 | 성격 |
|---|---|---|
| **통과** | 기획대로다 | |
| **위반** | 기획과 다르다 | **정상 결과.** 리포트에 담긴다 |
| **not run** | 앞단 실패의 여파로 도달 불가가 됐다 | **정상 결과.** 통과와 구분해 보고한다 |
| **오류** | 스크립트 예외·계약 위반·경로 없음 | **비정상.** 도구가 못 돈 것 |

종료 코드가 이 구분을 그대로 드러낸다 — `0` 통과만 / `1` **위반·not run** / `2` **오류**.

복구·재시도·대체 경로·skip 은 없다. 실패하면 그 지점에서 진행하지 않는다.

## 현재 상태

**동작한다.** 다섯 노드 타입과 두 파이프라인 종류(값 검증 / 비교)가 CLI 로 끝까지 돈다.

```
src/strictler/
  model/     네 층(Spec/Pipeline/Node/NodeTest)의 pydantic 모델
  typesys/   타입 어휘 + dataclass 집합 정규화 (구조 동일성·부분집합 병합)
  refs.py    ${env.X}/${config.X}/${state.X}/${ref.<id>} 전개, 절대경로 강제
  rules.py   검사 규칙 61개 + 슬롯 검증          report.py  리포트
  store/     등록소 CRUD·해시 대조·참조 그래프
  checks/    script(AST) · node · pipeline · reachability   ← 등록 시점 검사
  engine/    drive(구동 루프 정본) · state · exec · runtime(값 검증) · compare(비교)
  testing/   노드 단위테스트 하네스
  cli.py     CLI 표면
```

의존성은 **pydantic 하나**다 (CLI 는 표준 라이브러리 `argparse`).
