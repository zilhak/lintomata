"""스크립트의 PEP 723 의존성 선언을 읽고 **현재 환경에 있는지 확인**한다
(`schema.md` 6절 — 스크립트의 의존성).

**격리하지 않는다.** 노드 스크립트는 lintomata 와 **같은 프로세스**에 로드되므로
스크립트의 `import` 는 lintomata 가 설치된 환경에서 풀린다. PEP 723 헤더는 **선언일
뿐 격리를 만들지 않는다** — 여기서 하는 일은 등록 시점에 그 선언을 읽어 확인하고,
없으면 설치 명령을 안내하는 것 하나뿐이다. 헤더를 보고 환경을 만들어 주지 않는다.

    # /// script
    # requires-python = ">=3.11"
    # dependencies = ["selectolax>=0.3", "anthropic"]
    # ///

**헤더가 없는 것이 정상이다.** stdlib 만 쓰는 스크립트가 대부분이고, 그러면 확인할
것이 없다 — 위반도 오류도 아니다.

규칙 셋으로 나뉘는 기준은 **고치는 방법**이다 (`rules.md` 증가 이력):

| 규칙 | 무엇 | 고치는 법 |
|---|---|---|
| `LNT-DEP-001` | 선언한 패키지가 환경에 없다 | 설치한다 |
| `LNT-DEP-002` | 헤더 형식이 잘못됐다 | 헤더를 고친다 |
| `LNT-DEP-003` | 설치된 버전이 요구를 만족하지 않는다 | 버전을 맞추거나 요구를 고친다 |

**충돌 검출을 따로 하지 않는다.** 환경에는 패키지가 한 벌만 깔리므로, 호환되지 않는
요구가 둘 있으면 반드시 한쪽이 `LNT-DEP-003` 에 걸린다.

**메시지에는 설치 명령이 들어간다.** 작성 주체가 AI 라는 전제이므로 에러가 곧
자기 수정 신호여야 한다 (`schema.md` 6절 — 완벽한 정적 검사는 목표가 아니다).
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as installed_version
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from lintomata import rules
from lintomata.errors import Finding

__all__ = [
    "BLOCK_TYPE",
    "Declared",
    "read_header",
    "declared_dependencies",
    "check_dependencies",
    "install_command",
    "missing_module_hint",
    "missing_submodule_hint",
]


BLOCK_TYPE = "script"
"""PEP 723 가 정한 블록 종류 이름. 다른 종류의 블록은 우리 것이 아니다."""

_BLOCK_RE = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)
"""PEP 723 정본의 정규식 그대로. 손으로 다시 쓰지 않는다 — 형식은 표준이 정한다."""


@dataclass(frozen=True)
class Declared:
    """스크립트가 헤더로 선언한 것. **없으면 `present == False`.**"""

    present: bool = False
    """PEP 723 `script` 블록이 있었는가. 없는 것은 정상이다."""

    requires_python: str = ""
    """`requires-python` 원문. 없으면 `""`. **여기서 판정하지는 않는다** —
    파이썬 버전은 lintomata 를 띄운 인터프리터가 정하고, 그건 스크립트가 고칠 수 있는
    자리가 아니다."""

    dependencies: tuple[str, ...] = field(default_factory=tuple)
    """`dependencies` 에 적힌 PEP 508 문자열들. **선언 원문 그대로** 보관한다 —
    등록소 엔트리에 적히는 것도 이것이다."""


def read_header(source: str, path: str) -> tuple[Declared, list[Finding]]:
    """스크립트 소스에서 PEP 723 `script` 블록을 읽는다.

    형식이 깨졌으면 `LNT-DEP-002` 하나를 내고 **빈 선언**을 돌려준다 — 읽히지 않은
    헤더에서 의존성을 억지로 뽑으면 그 다음 규칙들이 헛것을 검사한다.

    **파싱 실패는 `LintomataError` 가 아니다.** 스크립트 문법 오류(`ast.parse`)와 달리
    헤더는 사용자가 쓴 내용이고 고치는 법이 명확하므로 규칙으로 잡는다.
    """
    blocks = [
        match for match in _BLOCK_RE.finditer(source) if match.group("type") == BLOCK_TYPE
    ]
    if not blocks:
        return Declared(), []
    if len(blocks) > 1:
        return Declared(), [_malformed(path, f"`{BLOCK_TYPE}` 블록이 {len(blocks)}개입니다")]

    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )
    try:
        raw = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        return Declared(), [_malformed(path, f"TOML 을 읽을 수 없습니다 ({exc})")]

    requires_python = raw.get("requires-python", "")
    if not isinstance(requires_python, str):
        return Declared(), [_malformed(path, "`requires-python` 이 문자열이 아닙니다")]

    declared = raw.get("dependencies", [])
    if not isinstance(declared, list):
        return Declared(), [_malformed(path, "`dependencies` 가 배열이 아닙니다")]
    if not all(isinstance(item, str) for item in declared):
        return Declared(), [_malformed(path, "`dependencies` 의 원소가 문자열이 아닙니다")]

    return Declared(
        present=True,
        requires_python=requires_python,
        dependencies=tuple(declared),
    ), []


def declared_dependencies(source: str) -> tuple[str, ...]:
    """선언된 의존성 문자열만 **관대하게** 뽑는다 (등록소 기록용).

    형식이 깨졌으면 빈 튜플이다 — 여기서 규칙을 내지 않는다. 판정의 자리는
    `check_dependencies` 이고, 등록소는 검사를 통과한 것만 받는다.
    """
    declared, findings = read_header(source, "")
    return () if findings else declared.dependencies


def check_dependencies(
    source: str, path: str, known: Iterable[str] = ()
) -> list[Finding]:
    """`LNT-DEP-001` / `-002` / `-003`. **헤더가 없으면 빈 목록이다.**

    설치 여부와 버전은 `importlib.metadata` 로 본다 — 지금 이 프로세스가 실제로
    `import` 할 수 있는 것이 무엇인지가 유일한 근거이기 때문이다.

    **환경 마커가 이 환경에 해당하지 않는 요구는 건너뛴다** (`; sys_platform == ...`).
    지금 여기서 쓰이지 않을 패키지를 요구하면 리눅스 전용 의존성을 적은 스크립트가
    맥에서 등록되지 않는다.

    `known` 은 **등록소가 이미 알고 있는 다른 스크립트들의 선언**이다. 안내 명령을
    완전하게 만드는 데만 쓴다 (`install_command`) — 판정에는 관여하지 않는다.
    """
    declared, findings = read_header(source, path)
    if findings or not declared.present:
        return findings

    known = tuple(known)
    for raw in declared.dependencies:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            findings.append(
                _malformed(path, f"`dependencies` 의 `{raw}` 를 읽을 수 없습니다 ({exc})")
            )
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        findings.extend(_check_one(requirement, raw, path, known))
    return findings


def install_command(requirement: str, known: Iterable[str] = ()) -> str:
    """이 요구를 lintomata 환경에 까는 **완전한** 명령. 에러 메시지의 핵심이다.

    ★ **`uv tool install --with` 는 선언적이다** — 이전에 넣은 `--with` 를 유지하지
    않고 **적힌 것만 남긴다**. 그래서 문제가 된 것 하나만 적어 안내하면, 그대로 따른
    AI 가 **다른 스크립트의 의존성을 지워버린다.** 안내가 정반대로 작동하는 자리라
    등록소가 아는 선언을 전부 합쳐 완전한 명령을 만든다.

    `known` 이 비어 있으면(등록소가 비었거나 못 읽음) **단순 형태로 폴백**한다 —
    여기서 예외를 내지 않는다. 안내 문자열을 만드는 자리이므로, 실패하더라도
    원래의 `Finding` 이 사라지면 안 된다.

    같은 패키지의 **요구가 서로 다르면 둘 다 적는다.** 우리가 임의로 하나를 고르면
    안 된다 — uv 가 해결하거나 실패하는 것이 맞다 (`schema.md` 6절: 격리를 뒤집을
    조건은 *"호환되지 않는 버전을 요구하는 스크립트가 둘 이상"* 이다).
    """
    parts = " ".join(f"--with '{item}'" for item in _merge_requirements(known, requirement))
    return f"uv tool install lintomata {parts}"


def _merge_requirements(known: Iterable[str], requirement: str) -> list[str]:
    """`known` + 문제의 요구를 합집합으로. **정규화 이름 기준으로 중복을 없앤다.**

    같은 요구 문자열은 하나로 합치고(`PyDantic` 과 `pydantic` 은 같은 것),
    같은 패키지라도 요구가 다르면 둘 다 남긴다. 순서는 `(정규화 이름, 원문)` 정렬 —
    같은 등록소면 언제나 같은 명령이 나와야 한다.
    """
    collected: dict[tuple[str, str], None] = {}
    for item in (*known, requirement):
        text = str(item).strip()
        if not text:
            continue
        try:
            key = canonicalize_name(Requirement(text).name)
        except InvalidRequirement:
            key = text.lower()  # 읽을 수 없는 것도 버리지 않는다 — 안내에서 사라지면 더 나쁘다
        collected[(key, text)] = None
    return [text for _key, text in sorted(collected)]


def missing_module_hint(source: str, module: str) -> str:
    """실행 시점 `ModuleNotFoundError` 에 붙일 안내. 해당 없으면 `""`.

    헤더에 그 패키지가 **선언돼 있는데도** 없다는 것은 등록 이후에 환경이 바뀐
    것이다. 등록 시점에 이미 `LNT-DEP-001` 로 걸렸을 자리이므로, 실행 시점에도
    같은 문장(설치 명령)을 준다 — 예외 텍스트만 나가면 AI 가 고칠 곳을 못 찾는다.

    선언에 없으면 아무것도 붙이지 않는다. 그건 헤더에 적는 것을 빠뜨린 것이고
    (`LNT-DEP-001` 이 잡을 수 없는 자리), 여기서 추측으로 설치 명령을 만들면
    엉뚱한 패키지 이름을 안내하게 된다.

    ⚠ **여기서는 완전한 명령을 만들 수 없다.** 등록소를 모르는 자리이기 때문이다
    (실행 엔진은 `--home` 이 어디인지 이 함수에 알려주지 않는다). 그래서 단순 형태로
    폴백하되 **`--with` 가 선언적이라는 경고를 함께 낸다** — 등록 시점의
    `LNT-DEP-001` 은 등록소를 알고 있으므로 거기서 완전한 명령이 나간다.
    """
    if not module:
        return ""
    declared, findings = read_header(source, "")
    if findings or not declared.present:
        return ""
    root = canonicalize_name(module.split(".", 1)[0])
    for raw in declared.dependencies:
        try:
            name = Requirement(raw).name
        except InvalidRequirement:
            continue
        if canonicalize_name(name) == root:
            return (
                f"이 모듈은 스크립트의 PEP 723 헤더에 `{raw}` 로 선언돼 있지만 "
                "지금 환경에 없습니다. 노드 스크립트는 lintomata 와 같은 환경에서 "
                f"`import` 가 풀립니다 — 그쪽에 함께 설치하세요: {install_command(raw)}\n"
                "⚠ `--with` 는 **선언적**이라 적은 것만 남습니다. 다른 스크립트가 "
                "요구하는 것이 있으면 **전부 함께** 적으세요 "
                "(`lintomata script list` / `show <id>` 의 선언 의존성)."
            )
    return ""


def missing_submodule_hint(module: str) -> str:
    """`a.b` 를 못 찾았는데 **`a` 는 설치돼 있는** 경우의 안내. 아니면 `""`.

    ★ **없는 것은 패키지가 아니라 그 안의 모듈이다.** 이 구분을 안 하면
    *"`pydantic>=2` 로 선언돼 있지만 지금 환경에 없습니다"* 같은 **사실이 아닌 문장**이
    나간다 — pydantic 은 설치돼 있고, 없는 것은 서브모듈이다. lint 도구에서 잘못된
    안내는 잘못된 리포트에 준한다.

    **설치돼 있는지는 `find_spec` 으로 본다.** 배포판 이름(`importlib.metadata`)이
    아니라 **import 이름**이 기준이어야 한다 — 여기서 실패한 것이 `import` 이기 때문이다
    (`beautifulsoup4` 를 깔아도 import 이름은 `bs4` 다).
    """
    root = module.split(".", 1)[0]
    if not root or root == module or not _is_importable(root):
        return ""
    return (
        f"`{root}` 패키지는 설치돼 있으나 그 안에 `{module}` 이 없습니다. "
        "설치 문제가 아니라 **모듈 경로가 틀린 것**입니다 — 이름을 확인하거나, "
        "그 패키지 버전에 그 모듈이 있는지 확인하세요."
    )


def _is_importable(root: str) -> bool:
    """최상위 모듈을 지금 import 할 수 있는가. **부모를 실제로 import 하지 않는다.**

    `find_spec` 이 무엇이든 던지면 `False` 로 본다 — 안내 문자열을 만드는 자리라서
    여기서 예외를 내면 원래 오류가 뭉개진다.
    """
    try:
        return importlib.util.find_spec(root) is not None
    except BaseException:  # noqa: BLE001 - 남의 패키지가 무엇을 던질지 모른다
        return False


# --- 내부 ----------------------------------------------------------------


def _malformed(path: str, reason: str) -> Finding:
    return rules.finding(
        "LNT-DEP-002", path=path, fields={"reason": reason, "file": path}
    )


def _check_one(
    requirement: Requirement, raw: str, path: str, known: Iterable[str] = ()
) -> list[Finding]:
    """요구 하나 — 없으면 `-001`, 있는데 버전이 안 맞으면 `-003`."""
    try:
        found = installed_version(requirement.name)
    except PackageNotFoundError:
        return [
            rules.finding(
                "LNT-DEP-001",
                path=path,
                fields={
                    "requirement": raw,
                    "file": path,
                    "install": install_command(raw, known),
                },
            )
        ]
    if requirement.specifier and not requirement.specifier.contains(
        found, prereleases=True
    ):
        return [
            rules.finding(
                "LNT-DEP-003",
                path=path,
                fields={
                    "requirement": raw,
                    "installed": found,
                    "file": path,
                    "install": install_command(raw, known),
                },
            )
        ]
    return []
