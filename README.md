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

설계 정본은 저장소에 커밋되지 않는 작업 폴더(`.claude-workspace/`)에 있다.

| 문서 | 무엇 |
|---|---|
| `schema.md` | 확정 사항 정본 — 네 층 구조·등록소·타입 시스템·노드 계약·리포트 |
| `rules.md` | 검사 규칙 ID 체계와 초기 테이블 (54개) |
| `conductor/MODULES.md` | 모듈 경계와 공개 시그니처 계약 |

## 현재 상태

**스캐폴딩 단계.** 데이터 모델(`strictler.model`)과 CLI 표면은 서 있고,
검사기·엔진·등록소는 시그니처만 있는 stub 이다.
