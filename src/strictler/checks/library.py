"""라이브러리 정적 검사 — **등록/수정 시점에 돈다** (`schema.md` 6.5절).

라이브러리는 **여러 스크립트가 나눠 쓰는 함수의 본체**다. 형제 파일 `import` 는
되지 않으므로(등록하면 파일 하나만 복사된다) 공유는 **등록소를 통해서** 한다.

### 스크립트와 같은 것 / 다른 것

| | 스크립트 | 라이브러리 |
|---|---|---|
| 금지 패턴 (시간·랜덤·subprocess) | ✅ | ✅ **똑같이** |
| PEP 723 의존성 확인 | ✅ | ✅ **똑같이** (같은 환경에 로드된다) |
| `runNode` / `Args` / 출력 타입 요구 | ✅ | ❌ 노드가 아니다 |
| 다른 라이브러리 `import` | (배선된 것만) | ❌ **금지 — 한 층만** (`STR-LIB-003`) |
| `dataclass` 선언 | ✅ | ❌ **v1 금지** (`STR-LIB-004`) |

**금지 패턴을 라이브러리에 안 걸면 거기서 `import time` 을 해 금지가 통째로
우회된다.** 그래서 판정은 `checks.script.check_bans` **그 함수**가 한다 —
여기에 표를 복제하면 두 벌이 갈리고, 갈린 쪽이 곧 우회로가 된다.

`dataclass` 금지 이유는 타입 레지스트리다: 노드 간 계약 타입이 스크립트 밖에서
생기면 `extract_contract` 가 파일 하나만 파싱하므로 등록에 구멍이 난다. **v2 다.**

⚠ **`strictler library test` 는 없다.** 라이브러리엔 `runNode` 계약이 없어 지금
하네스가 그대로 맞지 않는다 — 라이브러리는 그것을 쓰는 **노드 단위테스트를 통해
간접 검증**된다 (`schema.md` 6.5절).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Mapping

from strictler import deps, refs, rules
from strictler.checks import script as script_checks
from strictler.checks.script import ScriptContract
from strictler.errors import Finding, StrictlerError
from strictler.model import LIBRARY_NAMESPACE, Node
from strictler.store.entries import Store

__all__ = ["NAMESPACE", "check_library", "check_wiring", "resolve_libraries"]


NAMESPACE = LIBRARY_NAMESPACE
"""배선된 라이브러리가 들어오는 네임스페이스 (`schema.md` 6.5절). **정본은 `model`.**

라이브러리 **안에서** 이 이름이 보이면 그건 라이브러리 중첩이다 (`STR-LIB-003`).
스크립트 안에서 보이는 것은 정상이고, 형태만 `STR-LIB-005` 가 본다."""


def check_library(
    source: str,
    path: str,
    known_dependencies: tuple[str, ...] | list[str] = (),
) -> list[Finding]:
    """라이브러리 하나의 전체 정적 검사. **파일을 돌리지 않는다.**

    `known_dependencies` 는 스크립트 검사와 같은 용도다 — 등록소가 이미 아는 선언을
    받아 안내 명령(`uv tool install --with`)을 완전하게 만든다. 판정에는 관여하지
    않는다.

    **실패를 최대한 수집한다** — 하나 걸렸다고 나머지를 멈추지 않는다.

    파싱이 안 되는 것은 위반이 아니라 검사기가 못 돈 것이므로 `StrictlerError` 다
    (`checks.script._parse` 와 같은 자리).
    """
    tree = script_checks._parse(source, path)
    findings: list[Finding] = []
    # `contract=None` — 라이브러리에는 선언된 state 가 없다. 나머지 금지는 그대로다.
    findings.extend(script_checks.check_bans(source, path, None))
    findings.extend(check_no_nesting(tree, path))
    findings.extend(check_no_dataclass(tree, path))
    findings.extend(deps.check_dependencies(source, path, known_dependencies))
    return findings


def check_no_nesting(tree: ast.Module, path: str) -> list[Finding]:
    """라이브러리가 다른 라이브러리를 쓰지 않는지 (`STR-LIB-003`).

    **형태를 가리지 않는다** — `import strictler_lib` 든
    `from strictler_lib import x` 든 라이브러리 안에서는 전부 중첩이고, 고치는 법도
    하나다: 그 import 를 없앤다. (스크립트 쪽의 *형태* 문제는 `STR-LIB-005` 다 —
    거기서는 import 자체가 정상이고 형태만 틀린 것이라 고치는 곳이 다르다.)
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for name in _namespace_uses(tree):
        if name in seen:
            continue
        seen.add(name)
        findings.append(rules.finding("STR-LIB-003", path=path, fields={"name": name}))
    return findings


def check_no_dataclass(tree: ast.Module, path: str) -> list[Finding]:
    """라이브러리가 `dataclass` 를 선언하지 않는지 — **v1 제한** (`STR-LIB-004`).

    노드 간 계약 타입은 **스크립트가** 선언한다. 라이브러리에 두면 타입 레지스트리가
    보지 못하는 정의가 생긴다.

    ★ **탐지는 `checks.script._is_dataclass` 가 한다.** 데코레이터 형태를 여기서 다시
    판별하면 `@dataclass(frozen=True)` 같은 변형에서 두 판정이 갈린다.
    """
    return [
        rules.finding("STR-LIB-004", path=path, fields={"name": stmt.name})
        for stmt in ast.walk(tree)
        if isinstance(stmt, ast.ClassDef) and script_checks._is_dataclass(stmt)
    ]


def check_wiring(
    node: Node, contract: ScriptContract, *, path: str
) -> list[Finding]:
    """스크립트가 요구한 슬롯과 노드가 배선한 슬롯이 맞는지 (`STR-LIB-001` / `-002`).

    선언/사용 분리 그대로다 — 스크립트가 *"이 슬롯이 필요합니다"*, 노드가
    *"그 슬롯엔 이걸 씁니다"*. **양쪽이 안 맞으면 고칠 곳이 서로 다르므로**
    규칙도 둘로 나뉜다: 빠진 것은 노드에 **넣고**, 남는 것은 노드에서 **뺀다**.

    ⚠ 배선 **값**(참조가 실재하는지, 라이브러리가 맞는지)은 여기서 보지 않는다 —
    `resolve_libraries` 의 일이다. 여기는 이름만 대조한다.
    """
    required = list(contract.library_slots)
    wired = list(node.libraries)

    findings: list[Finding] = []
    missing = [name for name in required if name not in wired]
    if missing:
        findings.append(
            rules.finding(
                "STR-LIB-001",
                path=path,
                node=node.info.name,
                fields={"names": ", ".join(missing)},
            )
        )
    extra = [name for name in wired if name not in required]
    if extra:
        findings.append(
            rules.finding(
                "STR-LIB-002",
                path=path,
                node=node.info.name,
                fields={"names": ", ".join(extra)},
            )
        )
    return findings


def resolve_libraries(
    node: Node, *, store: Store, env: Mapping[str, str]
) -> tuple[dict[str, Path], list[Finding]]:
    """노드가 배선한 라이브러리들을 실제 파일 경로로 푼다.

    `${ref.lb_...}` 면 등록소에서, 경로면 경로 규칙(`~` → env → 절대경로)으로.
    **2절의 "ref 는 로컬 최적화, 경로는 이식 가능" 이 그대로 적용된다** — 커밋할
    노드는 경로로 쓰고, 손에 든 등록소에서는 id 로 쓴다.

    | 잘못된 것 | 규칙 |
    |---|---|
    | `${ref.sc_...}` 처럼 **라이브러리가 아닌 것**을 배선했다 | `STR-REG-003` |
    | 그 id 가 등록소에 없다 | `STR-REG-002` |
    | 가리키는 파일이 없다 | `STR-REF-001` |
    | 경로 규칙 위반 | `STR-PATH-001`~`003` |

    **`STR-REG-003` 을 새로 파지 않았다** — *"이 자리에는 X 가 와야 하는데 Y 를 줬다"*
    는 이미 그 규칙의 자리이고 고치는 법도 같다(접두를 맞춘다).

    **못 푼 슬롯은 결과에서 빠진다.** 그 자리에서 진행하지 않는 것이고, 억지로 빈
    모듈을 넣으면 스크립트가 `AttributeError` 로 터져 원인이 뭉개진다.
    """
    resolved: dict[str, Path] = {}
    findings: list[Finding] = []

    for slot, value in node.libraries.items():
        found, gathered = _resolve_one(value, slot=slot, node=node, store=store, env=env)
        findings.extend(item.model_copy(update={"path": item.path or ""}) for item in gathered)
        if found is not None:
            resolved[slot] = found
    return resolved, findings


def _resolve_one(
    value: str, *, slot: str, node: Node, store: Store, env: Mapping[str, str]
) -> tuple[Path | None, list[Finding]]:
    """배선 값 하나를 파일로. 자리 표시(`path`)는 부르는 쪽이 채운다."""
    who = node.info.name
    if not isinstance(value, str):  # pragma: no cover - pydantic 이 이미 막는다
        return None, [
            Finding(
                status="error",
                node=who,
                message=f"`libraries.{slot}` 가 문자열이 아닙니다: {value!r}",
            )
        ]

    if refs.is_ref(value):
        try:
            _, entry_id = refs.parse_ref(value, "library")
        except StrictlerError as exc:
            return None, _findings_of(exc, node=who)
        try:
            store.show(entry_id)
        except StrictlerError:
            return None, [
                rules.finding("STR-REG-002", node=who, fields={"id": entry_id})
            ]
        path = store.path_of(entry_id)
    else:
        try:
            path = refs.expand_path(value, env)
        except StrictlerError as exc:
            return None, _findings_of(exc, node=who)

    if not path.is_file():
        return None, [
            rules.finding("STR-REF-001", node=who, fields={"script": str(path)})
        ]
    return path, []


def _findings_of(exc: StrictlerError, *, node: str) -> list[Finding]:
    """`refs` 가 던진 규칙 실린 예외를 `Finding` 목록으로.

    지역 import — `checks.node` 가 이 모듈을 쓰므로 top-level 이면 순환이다
    (`store.graph` 가 `checks` 를 부르는 것과 같은 자리).
    """
    from strictler.checks.node import findings_of

    return findings_of(exc, path="", node=node)


def _namespace_uses(tree: ast.Module) -> list[str]:
    """`strictler_lib` 를 건드리는 import 를 등장 순서대로 **원문 그대로** 모은다."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name
                for alias in node.names
                if alias.name == NAMESPACE or alias.name.startswith(f"{NAMESPACE}.")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == NAMESPACE or module.startswith(f"{NAMESPACE}."):
                found.extend(f"{module}.{alias.name}" for alias in node.names)
    return found
