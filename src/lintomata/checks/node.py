"""노드 JSON 로드와 검증 — **노드 등록 시** (`schema.md` 13절).

| 검증 | 규칙 |
|---|---|
| `script` 가 실재하는지, 경로 규칙을 지키는지 | `LNT-REF-001` / `LNT-PATH-001`~`003` |
| `${ref.<id>}` 의 접두가 그 자리가 요구하는 종류와 맞는지 | `LNT-REG-003` |
| `${ref.<id>}` 가 등록소에 실재하는지 | `LNT-REG-002` |
| 스크립트가 `runNode(args: Args)` / `returnResult()` 형태인지 | `LNT-CONTRACT-001`~`003` |
| `Args` 필드가 `input`/`params`/`state` 중에서만 쓰였는지 | `LNT-CONTRACT-004` |
| 선언된 타입이 primitive 집합 + dataclass 뿐인지 | `LNT-TYPE-001`~`003` |
| Reckon 이면 `Args.params` 에 기댓값 필드가 있는지 | `LNT-CONTRACT-005` |
| Action 이면 input 타입 == output 타입인지 | `LNT-CONTRACT-006` |
| 금지 패턴이 없는지 | `LNT-BAN-001`~`004` |
| `Args.state` 필드 이름에 `__` 접두를 쓰지 않았는지 | `LNT-STATE-001` |
| 스크립트가 요구한 라이브러리 슬롯이 전부 배선됐는지 | `LNT-LIB-001` / `-002` |
| 배선한 것이 실재하는 라이브러리이고 그 자체로 성립하는지 | `LNT-REG-002`/`-003`, `LNT-LIB-003`/`-004` |

즉 **노드 검사 = 노드 JSON 자체 검사 + 그 스크립트를 노드 타입과 함께 검사**다.
아래쪽 절반(`LNT-CONTRACT-*` / `LNT-TYPE-001`~`003` / `LNT-BAN-*`)은 전부
`checks.script` 가 낸다 — 이 모듈은 **어느 스크립트를 어느 노드 타입으로 검사할지**
정하고 그 결과를 모은다.

### `${config.X}` 인 `script` 는 등록 시점에 검사할 수 없다 — 오류가 아니다

비교 파이프라인에서 `script` 자리에 `${config.buttonScript}` 가 오는 것이 설계다
(`schema.md` 12절). 그 값은 Spec 이 채우므로 **노드 등록 시점에는 어느 파일인지 알 수 없다.**
→ `config` 없이 부른 `resolve_script` 는 이걸 **오류가 아니라 "아직 모름"** 으로 다루고
`(None, [])` 를 준다. 억지로 전개하면 `LNT-REF-007`(미해결 참조)이 나면서
**정상적인 비교 노드를 등록조차 못 하게 된다.**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from lintomata import refs, rules
from lintomata.checks import script as script_checks
from lintomata.checks.script import ScriptContract
from lintomata.errors import Finding, LintomataError
from lintomata.model import Node
from lintomata.store.entries import Store

__all__ = ["load_node", "resolve_script", "check_node", "check_libraries"]


_CONFIG_MARK = "${config."
"""아직 전개되지 않은 config 참조의 표식. 문법 검사는 `refs` 가 한다."""


# ── 공통 헬퍼 (파이프라인 검사도 같이 쓴다) ──────────────────────────────────


def findings_of(exc: LintomataError, *, path: str, node: str = "") -> list[Finding]:
    """`LintomataError` 를 `Finding` 목록으로 바꾼다.

    `refs`·`typesys` 는 **오류를 예외로 던진다** — 규칙 id 가 붙은 `Finding` 을
    `exc.findings` 에 실어서. 반면 등록 검사는 **한 번에 최대한 많이 모으는 것**이
    목적이라 `list[Finding]` 을 돌려준다 (`schema.md` 9절). 그 경계가 여기다.

    실린 `Finding` 이 없으면(규칙 없는 오류) 문구만 담은 것을 하나 만든다 —
    **규칙 id 가 없다고 결과가 사라지면 안 된다.**
    """
    if not exc.findings:
        return [Finding(status="error", path=path, node=node, message=exc.message)]
    return [
        item.model_copy(
            update={"path": item.path or path, "node": item.node or node}
        )
        for item in exc.findings
    ]


def dedupe(findings: list[Finding]) -> list[Finding]:
    """같은 자리·같은 규칙·같은 문구의 결과를 한 번만 남긴다 (순서 보존).

    한 스크립트를 두 경로로 검사하면(예: `extract_contract` 와 `check_script`)
    같은 결과가 두 번 나올 수 있다. 리포트에 중복이 쌓이면 AI 가 "두 군데가 틀렸다"고
    읽는다.
    """
    seen: set[tuple[str, str, str, str]] = set()
    kept: list[Finding] = []
    for item in findings:
        mark = (item.status, item.path, item.node, item.message)
        if mark in seen:
            continue
        seen.add(mark)
        kept.append(item)
    return kept


def shape_findings(exc: ValidationError, path: str, label: str) -> list[Finding]:
    """pydantic 검증 실패를 `Finding` 으로 바꾼다.

    **규칙 id 가 없다.** `rules.md` 에 "JSON 형태가 스키마와 다르다" 를 담는 규칙이
    없기 때문이다 — 오류 위치마다 하나씩, 자연어 가이드를 붙여 낸다.
    pydantic 에러는 구조화돼 있어 그대로 옮기면 AI 가 읽고 자기 수정하기 좋다.
    """
    made: list[Finding] = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "(최상위)"
        made.append(
            Finding(
                status="error",
                path=path,
                message=(
                    f"{label} JSON 이 스키마에 맞지 않습니다 — `{where}`: {error['msg']}\n"
                    f"입력값: {error.get('input')!r}\n"
                    f"선언되지 않은 키는 쓸 수 없고(`extra=forbid`), 필수 키는 빠질 수 "
                    f"없습니다. `schema.md` 의 {label} 구조를 그대로 따르세요."
                ),
            )
        )
    return made


def has_unresolved_config(value: object) -> bool:
    """아직 전개되지 않은 `${config.X}` 를 품고 있는가."""
    return isinstance(value, str) and _CONFIG_MARK in value


# ── 로드 ─────────────────────────────────────────────────────────────────────


def load_node(raw: Mapping[str, Any], path: str) -> tuple[Node | None, list[Finding]]:
    """JSON dict 를 `Node` 모델로 로드한다.

    pydantic 검증 실패(모르는 키, 잘못된 `type` 값 등)를 `Finding` 으로 바꿔 낸다 —
    pydantic 에러가 구조화돼 있어 AI 가 읽고 자기 수정하기 좋다.
    """
    try:
        return Node.model_validate(dict(raw)), []
    except ValidationError as exc:
        return None, shape_findings(exc, path, "노드")


def resolve_script(
    node: Node,
    *,
    store: Store,
    env: Mapping[str, str],
    config: Mapping[str, Any] | None = None,
    target: str = "",
) -> tuple[Path | None, list[Finding]]:
    """노드의 `script` 를 실제 파일 경로로 푼다.

    `${ref.sc_...}` 면 등록소에서, 경로면 경로 규칙을 적용해서.
    `${config.X}` 도 올 수 있다 — 비교 파이프라인에서 target 별로 스크립트가
    갈리는 자리다 (`schema.md` 12절). 그래서 `config`/`target` 을 받는다.

    **`config` 를 안 주면 `${config.X}` 는 "아직 모름"이다** — `(None, [])`.
    오류가 아니다. 노드 등록 시점에 Spec 의 값을 알 수 없는 것은 결함이 아니라 순서다.
    """
    where = ""  # 파일 경로는 부르는 쪽(`check_node`)이 채운다
    raw = node.script

    if config is not None:
        try:
            resolved: object = refs.expand_config(raw, config, target)
        except LintomataError as exc:
            return None, findings_of(exc, path=where, node=node.info.name)
    else:
        resolved = raw

    if not isinstance(resolved, str):
        return None, [
            Finding(
                status="error",
                path=where,
                node=node.info.name,
                message=(
                    f"노드의 `script` 가 문자열이 아닙니다: {resolved!r}\n"
                    "`script` 에는 스크립트 파일의 절대경로 또는 `${ref.sc_...}` 가 옵니다."
                ),
            )
        ]

    if has_unresolved_config(resolved):
        # Spec 이 채울 값이다. 지금 전개하면 LNT-REF-007 이 나면서 정상적인
        # 비교 노드를 등록조차 못 하게 된다.
        return None, []

    if refs.is_ref(resolved):
        return _resolve_registered(resolved, store=store, where=where, node=node)
    return _resolve_path(resolved, env=env, where=where, node=node)


def _resolve_registered(
    value: str, *, store: Store, where: str, node: Node
) -> tuple[Path | None, list[Finding]]:
    """`${ref.sc_...}` 를 등록소 파일 경로로 푼다."""
    try:
        refs.parse_ref(value, "script")
    except LintomataError as exc:
        return None, findings_of(exc, path=where, node=node.info.name)

    entry_id = value[len("${ref.") : -1]
    try:
        store.show(entry_id)
    except LintomataError:
        return None, [
            rules.finding(
                "LNT-REG-002", path=where, node=node.info.name, fields={"id": entry_id}
            )
        ]

    path = store.path_of(entry_id)
    if not path.is_file():
        return None, [
            rules.finding(
                "LNT-REF-001", path=where, node=node.info.name, fields={"script": str(path)}
            )
        ]
    return path, []


def _resolve_path(
    value: str, *, env: Mapping[str, str], where: str, node: Node
) -> tuple[Path | None, list[Finding]]:
    """경로 문자열을 경로 규칙(`~` → env → `~` 재전개 → 절대경로)으로 푼다."""
    try:
        path = refs.expand_path(value, env)
    except LintomataError as exc:
        return None, findings_of(exc, path=where, node=node.info.name)
    if not path.is_file():
        return None, [
            rules.finding(
                "LNT-REF-001", path=where, node=node.info.name, fields={"script": str(path)}
            )
        ]
    return path, []


def check_node(
    node: Node,
    source_path: str,
    *,
    store: Store,
    env: Mapping[str, str],
) -> tuple[ScriptContract | None, list[Finding]]:
    """노드 하나의 등록 시 정적 검사 전체.

    성공하면 그 스크립트의 `ScriptContract` 를 함께 준다 — 파이프라인 검사가 이걸 쓴다.

    스크립트를 **돌리지 않는다.** `checks.script` 가 `ast` 로 읽어 선언과 형식만 본다.
    노드 타입을 함께 넘기는 것이 이 자리의 핵심이다 — Reckon 의 기댓값 필드 요구와
    Action 의 input==output 요구는 **노드 타입을 알아야만** 검사할 수 있다.
    """
    resolved, raw_findings = resolve_script(node, store=store, env=env)
    # `resolve_script` 는 파일 경로를 모른다 — 자리 표시는 여기서 채운다.
    findings = [
        item.model_copy(update={"path": item.path or source_path})
        for item in raw_findings
    ]
    if resolved is None:
        return None, findings
    script_path = resolved

    source = _read_script(script_path)
    findings.extend(
        script_checks.check_script(
            source,
            str(script_path),
            node.type,
            known_dependencies=store.declared_dependencies(),
        )
    )

    contract, extracted = script_checks.extract_contract(source, str(script_path))
    findings.extend(extracted)
    findings.extend(check_libraries(node, contract, source_path, store=store, env=env))
    return contract, dedupe(findings)


def check_libraries(
    node: Node,
    contract: ScriptContract,
    source_path: str,
    *,
    store: Store,
    env: Mapping[str, str],
) -> list[Finding]:
    """노드의 라이브러리 배선 검사 (`schema.md` 6.5절).

    셋을 한 자리에서 본다 — **셋 다 노드 등록이 막아야 할 것들**이기 때문이다:

    1. 슬롯이 맞는가 (`LNT-LIB-001` / `-002`)
    2. 배선한 것이 실재하는 라이브러리인가 (`LNT-REG-002`/`-003`, `LNT-REF-001`, 경로 규칙)
    3. **그 라이브러리 자체가 정적 검사를 통과하는가** (`LNT-BAN-*`, `LNT-LIB-003`/`-004`)

    3번을 여기서도 도는 이유는 **경로로 배선한 라이브러리는 등록을 안 지났기 때문**이다.
    등록된 것도 다시 보지만 그건 스크립트도 마찬가지다(`check_script`) — 노드 등록은
    *"이 노드가 지금 성립하는가"* 를 묻는 자리이고, 그 답은 참조하는 파일들의 현재
    내용에 달려 있다.

    ★ **`node` 를 채우지 않는다.** 스크립트 검사 결과와 같은 규칙이다 — 파이프라인
    안에서 불리면 그쪽이 **노드 id** 를 채운다. 여기서 `info.name` 을 박으면 같은
    노드가 리포트에 두 이름으로 찍힌다.
    """
    # 지역 import — `checks.library` 가 이 모듈의 `findings_of` 를 쓴다.
    from lintomata.checks import library as library_checks

    findings = library_checks.check_wiring(node, contract, path=source_path)
    resolved, resolve_findings = library_checks.resolve_libraries(
        node, store=store, env=env
    )
    findings.extend(
        item.model_copy(update={"path": item.path or source_path})
        for item in resolve_findings
    )

    known = store.declared_dependencies()
    for path in resolved.values():
        findings.extend(
            library_checks.check_library(
                _read_script(path), str(path), known_dependencies=known
            )
        )
    return findings


def _read_script(path: Path) -> str:
    """스크립트 본문을 읽는다.

    여기서 실패하는 것은 위반이 아니라 **도구가 못 돈 것**이다 — 존재는 이미
    `resolve_script` 가 확인했으므로, 여기 도달해서 못 읽는다면 권한·인코딩 문제다.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LintomataError(
            f"스크립트가 UTF-8 이 아닙니다: {path} ({exc.reason}, byte {exc.start})\n"
            "노드 스크립트는 Python 소스이고 UTF-8 이어야 합니다."
        ) from exc
    except OSError as exc:
        raise LintomataError(
            f"스크립트를 읽을 수 없습니다: {path} ({exc})\n"
            "파일 권한을 확인하세요."
        ) from exc
