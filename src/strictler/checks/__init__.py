"""정적 검사 — **등록/수정 시점에 돈다** (`schema.md` 13절).

검사에 걸리면 **명확한 에러를 뱉고 등록/수정이 실패**한다. 잘못된 것이 저장되지 않는다.

| 시점 | 대상 | 실패하면 |
|---|---|---|
| **노드 등록** | 노드 JSON + 그 스크립트 | 등록 실패 — 저장되지 않는다 |
| **파이프라인 등록** | 파이프라인 JSON + 참조된 노드들 | 등록 실패 |
| **Spec 실행** | config 채움 + 경로 전개 + `tool` + 해시 대조 | 실행 실패 |

**등록 검사는 스크립트를 안 돌린다**(형식·선언·금지 패턴).
**단위테스트는 돌린다**(선언대로 동작하는가) — `strictler.testing`.

→ AI 저작 워크플로우의 안전망이 여기 있다. **잘못 쓴 순간 걸리고, 돌려보기 전에 자기 수정한다.**

- `script` — 스크립트 AST 검사 (노드 계약·타입·금지 패턴)
- `node` — 노드 JSON 로드와 검증
- `pipeline` — 파이프라인 JSON 로드와 검증 (DAG·배선 타입·상태 매핑·비교 계약)
- `reachability` — 도달 가능성 판정기

⚠ 하위 모듈 import 는 **함수 안에서** 한다. `checks.node` / `checks.pipeline` 이 이
패키지를 거쳐 서로를 참조하므로, 최상위에서 끌어오면 부분 초기화된 패키지를 보게 된다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from strictler.errors import Finding, StrictlerError
from strictler.model import EntryKind, Spec
from strictler.store.entries import Store

__all__ = ["check_registration"]


def check_registration(kind: EntryKind, source: Path, store: Store) -> list[Finding]:
    """등록/수정 시점의 정적 검사 진입점. 종류에 맞는 검사기로 넘긴다.

    빈 목록이면 통과 — 그때만 등록소에 저장된다.
    스크립트는 그 자체로도 검사되지만 노드 타입을 알아야 하는 검사
    (Reckon 기댓값 필드, Action input==output)는 노드 등록 시에 돈다.

    파일을 못 읽는 것은 **위반이 아니라 도구가 못 돈 것**이므로 `StrictlerError` 다
    (`schema.md` 9절). 반면 내용이 규칙에 어긋나는 것은 전부 `Finding` 이다.
    """
    from strictler.checks import node as node_checks
    from strictler.checks import pipeline as pipeline_checks
    from strictler.checks import script as script_checks

    path = Path(os.path.expanduser(str(source)))
    text = _read(path)
    env = os.environ

    if kind == "script":
        # 등록소가 아는 선언을 함께 넘긴다 — `uv tool install --with` 는 선언적이라
        # 안내 명령이 완전하지 않으면 **다른 스크립트의 의존성을 지운다**.
        return script_checks.check_script(
            text, str(path), known_dependencies=store.declared_dependencies()
        )

    raw = _parse_json(text, path)

    if kind == "node":
        node, findings = node_checks.load_node(raw, str(path))
        if node is None:
            return findings
        _, node_findings = node_checks.check_node(node, str(path), store=store, env=env)
        return findings + node_findings

    if kind == "pipeline":
        pipeline, findings = pipeline_checks.load_pipeline(raw, str(path))
        if pipeline is None:
            return findings
        _, pipeline_findings = pipeline_checks.check_pipeline(
            pipeline, str(path), store=store, env=env
        )
        return findings + pipeline_findings

    return _check_spec_shape(raw, str(path))


def _check_spec_shape(raw: object, path: str) -> list[Finding]:
    """Spec 은 **형태만** 본다.

    `schema.md` 13절의 Spec 검증 항목(config 채움·경로 전개·`tool`·해시 대조)은
    전부 **실행 시점**이다 — 등록 시점에는 참조된 파이프라인의 config 선언도
    실행 환경의 환경변수도 알 수 없다. 여기서 억지로 검사하면 정상적인 Spec 이
    등록조차 안 된다.
    """
    from strictler.checks.node import shape_findings

    try:
        Spec.model_validate(raw)
    except ValidationError as exc:
        return shape_findings(exc, path, "Spec")
    return []


def _read(path: Path) -> str:
    if not path.is_file():
        raise StrictlerError(
            f"등록할 파일이 없습니다: {path}\n"
            "경로를 확인하세요. 등록소는 파일을 복사해 보관하므로 원본이 있어야 합니다."
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise StrictlerError(
            f"등록할 파일이 UTF-8 이 아닙니다: {path} ({exc.reason}, byte {exc.start})\n"
            "등록 대상은 `.py` 스크립트와 `.json` 문서뿐이고 둘 다 UTF-8 이어야 합니다."
        ) from exc


def _parse_json(text: str, path: Path) -> dict[str, object]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StrictlerError(
            f"JSON 을 읽을 수 없습니다: {path} ({exc})\n"
            "노드·파이프라인·Spec 은 전부 JSON 문서입니다. 문법을 확인하세요."
        ) from exc
    if not isinstance(raw, dict):
        raise StrictlerError(
            f"JSON 의 최상위가 객체가 아닙니다: {path}\n"
            "네 층 문서는 전부 최상위가 객체(`{...}`)입니다."
        )
    return raw
