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

from strictler import deps, rules
from strictler.checks import script as script_checks
from strictler.errors import Finding

__all__ = ["NAMESPACE", "check_library"]


NAMESPACE = "strictler_lib"
"""배선된 라이브러리가 들어오는 네임스페이스 (`schema.md` 6.5절).

**네임스페이스를 쓰는 이유**는 같은 이름의 실제 패키지를 가리는 사고를 막기
위해서다. 라이브러리 안에서 이 이름이 보이면 그건 **라이브러리 중첩**이다."""


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
