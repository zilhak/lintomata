"""strictler — 기획대로 돌아가는지를 검사하는 도구.

**이건 lint 다. 실행 파이프라인이 아니다.** 판정 대상은 AST 가 아니라 형상(shape)이고,
판정 기준은 코딩 컨벤션이 아니라 기획이다.

strictler 가 제공하는 것: 스키마, DAG·상태머신 실행 엔진, 타입 계약 검증,
노드 단위테스트 하네스, 리포터. **내장 동작은 하나도 없다** — 모든 노드의 스크립트는
사용자(실제로는 AI)가 공급한다.

설계 정본은 `docs/schema.md`, 규칙 테이블은 `docs/rules.md`.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
