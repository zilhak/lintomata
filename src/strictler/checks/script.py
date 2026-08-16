"""스크립트 AST 검사 — 노드 계약·타입·금지 패턴 (`schema.md` 6·13절).

**스크립트를 돌리지 않는다.** `ast` 로 읽어 선언과 형식만 본다.

### 진입점·출력 함수는 이름이 고정이다

| | 이름 | 규칙 |
|---|---|---|
| 진입점 | `runNode(args)` | 전 노드 타입 공통. `args` 의 타입은 dataclass **`Args`** |
| 출력 | `returnResult()` | 반환 타입은 dataclass. **이름은 자유** |

`Args` 만 이름이 고정인 것은 **엔진이 찾아야 하기 때문**이고, 반환 타입 이름을
고정하지 않는 것은 **구조로 매칭**하기 때문이다 (`schema.md` 7절).

### `Args` 는 세 필드로 출처를 나눈다

    input   앞단 노드들의 출력      ← DAG 가 준다
    params  Spec 이 채운 값        ← Spec 이 준다
    state   참조할 파이프라인 상태   ← 런타임이 준다

**쓰는 것만 선언한다.** 입력이 없는 Vantage 는 `input` 필드를 아예 두지 않는다.
**`Args.state` 가 곧 "필요 상태 선언"이다** — 별도 `need_state` 배열 같은 것은 없다.

### 금지는 전 노드 균일하다

시간 의존 / 랜덤 / 직접 subprocess / 미선언 state 참조.
**그 외에는 아무것도 금지하지 않는다** — 파일 IO·네트워크·환경변수 전부 자유다.
노드 내부에서 AI 를 부르든 상관하지 않는다. output 을 잘못 내놓으면 타입 계약에 걸릴 뿐이다.

⚠ **완벽한 정적 검사는 목표가 아니다.** `__import__("ti"+"me")` 같은 우회는 못 막는다.
사전에 추측할 수 있는 행위만 막고, **에러 메시지에 자연어 가이드를 넣는다** —
작성 주체가 AI 라는 전제 덕에 이게 유효하다.

### 파싱 불가는 위반이 아니라 `StrictlerError` 다

`ast.parse` 가 실패하면 **검사기가 일을 못 한 것**이지 규칙 위반이 아니다.
CLAUDE.md 의 3구분(위반 / not run / 오류) 중 세 번째다.
"""

from __future__ import annotations

import ast

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.model import ENGINE_STATE_FIELDS, NodeType
from strictler.typesys.primitives import TypeRef, check_allowed, parse_type
from strictler.typesys.registry import DataclassSpec, FieldSpec

__all__ = [
    "ScriptContract",
    "extract_contract",
    "check_script",
    "check_entrypoint",
    "check_args_shape",
    "check_types",
    "check_bans",
    "check_node_type_form",
    "check_tool_calls",
]


ENTRYPOINT = "runNode"
"""진입점 함수 이름. 고정이다 — 엔진이 이 이름으로 찾는다."""

RESULT_FN = "returnResult"
"""출력 함수 이름. 고정이다."""

ARGS_NAME = "Args"
"""`args` 의 타입으로 고정된 dataclass 이름."""

ARGS_FIELDS: tuple[str, ...] = ("input", "params", "state")
"""`Args` 가 가질 수 있는 필드. **쓰는 것만 선언한다** — 셋 다 있어야 하는 게 아니다."""

"""`ENGINE_STATE_FIELDS` — 엔진이 채워주는 state 필드. 사용자는 `__` 접두를 못 쓰므로
(`STR-STATE-001`) `Args.state` 에 선언할 수 없고, 그래서 **선언 없이 접근해도
`STR-BAN-004` 가 아니다.**

정본은 `model` 에 있다 (`engine/state.py`·`refs.py` 와 셋이 같은 것을 본다) —
복제해 두면 엔진 제공 필드가 늘 때 `STR-BAN-004` 오탐이 난다."""


# --- 금지 표 -------------------------------------------------------------
#
# **이름만 보고 사전에 추측할 수 있는 것**만 담는다. 우회는 애초에 목표가 아니다.

_BANNED_MODULES: dict[str, str] = {
    "time": "STR-BAN-001",
    "datetime": "STR-BAN-001",
    "random": "STR-BAN-002",
    "secrets": "STR-BAN-002",
    "subprocess": "STR-BAN-003",
}
"""import 하는 순간 걸리는 모듈 → 규칙 id. `os` 는 여기 없다 — 환경변수·경로는 자유다."""

_BANNED_CALLS: dict[str, str] = {
    # 랜덤 — 모듈 자체는 결정적이라 호출만 잡는다
    "os.urandom": "STR-BAN-002",
    "uuid.uuid4": "STR-BAN-002",
    "uuid.uuid1": "STR-BAN-002",
    # 직접 subprocess — `os` 는 자유지만 이 함수들은 임의 명령 실행이다
    "os.system": "STR-BAN-003",
    "os.popen": "STR-BAN-003",
    "os.fork": "STR-BAN-003",
    "os.execv": "STR-BAN-003",
    "os.execve": "STR-BAN-003",
    "os.execvp": "STR-BAN-003",
    "os.execl": "STR-BAN-003",
    "os.execlp": "STR-BAN-003",
    "os.spawnv": "STR-BAN-003",
    "os.spawnl": "STR-BAN-003",
    "os.posix_spawn": "STR-BAN-003",
    "exec": "STR-BAN-003",
    "eval": "STR-BAN-003",
}
"""호출해야 걸리는 것 → 규칙 id. import 로 이미 걸리는 모듈의 함수는 여기 두지 않는다
(같은 사실을 두 번 보고하게 된다)."""

class ScriptContract:
    """스크립트에서 뽑아낸 **능력 선언**. 이후 층 전부가 이걸 보고 판단한다.

    필드:
      `path`         — 스크립트 경로 (에러 메시지용)
      `dataclasses`  — 선언된 dataclass 들 (`dict[str, DataclassSpec]`)
      `input_type`   — `Args.input` 의 타입 이름. 없으면 `""`
      `params_type`  — `Args.params` 의 타입 이름. 없으면 `""`
      `state_type`   — `Args.state` 의 타입 이름. 없으면 `""`
      `state_names`  — `Args.state` dataclass 의 필드 이름들 = **노드가 요구하는 상태 이름**
      `output_type`  — `returnResult()` 로 나가는 dataclass 이름
      `tool_calls`   — `(함수명, 실행파일 경로 인자)` 목록. 실행 시 Spec `tool` 과 대조

    `_` 로 시작하는 나머지는 **검사기끼리만 쓰는 기록**이다 (공개 계약이 아니다).
    `check_entrypoint` 등이 소스를 다시 파싱하지 않아도 되게 여기 담아 둔다.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.dataclasses: dict[str, DataclassSpec] = {}
        self.input_type: str = ""
        self.params_type: str = ""
        self.state_type: str = ""
        self.state_names: tuple[str, ...] = ()
        self.output_type: str = ""
        self.tool_calls: list[tuple[str, str]] = []

        # --- 내부 기록 (공개 계약 아님) ---
        self._has_args: bool = False
        self._args_fields: tuple[str, ...] = ()
        self._has_entrypoint: bool = False
        self._entrypoint_ok: bool = False
        self._param_name: str = "args"
        self._returns_result: bool = False
        self._type_uses: tuple[TypeRef, ...] = ()

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return (
            f"ScriptContract({self.path!r}, in={self.input_type!r}, "
            f"out={self.output_type!r}, states={self.state_names!r})"
        )


# --- 추출 ----------------------------------------------------------------


def extract_contract(source: str, path: str) -> tuple[ScriptContract, list[Finding]]:
    """스크립트 소스에서 계약을 뽑는다. 파이프라인 검사·엔진·단위테스트가 이 결과를 재료로 쓴다.

    ★ **두 번째 반환값은 언제나 빈 목록이다. 검증은 `check_script` 가 한다.**
    추출 단계에는 고유한 오류가 없기 때문이다 — 해석 안 되는 어노테이션은
    `_type_of` 가 **미지 타입 그대로** 남겨 `check_types` 가 `STR-TYPE-003` 으로 잡고,
    없는 `Args`·없는 진입점·안 나가는 출력은 전부 *"뽑을 게 없다"* 여서 계약이 비는
    것으로 표현되며 `check_entrypoint` 가 판정한다. 추출은 **읽기만** 한다.

    자리를 남겨 두는 것은 시그니처가 계약(MODULES.md)이기 때문이고, 나중에
    추출 고유의 오류가 생기면 여기에 담는다.
    → **`extract_contract` 만 부르고 통과로 판단하지 마라.** 검사는 `check_script` 다.

    **파싱이 안 되면 `StrictlerError`** — 위반이 아니라 검사기가 못 돈 것이다.
    """
    tree = _parse(source, path)
    contract = ScriptContract(path)
    findings: list[Finding] = []

    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef) and _is_dataclass(stmt):
            spec = _dataclass_spec(stmt, path)
            contract.dataclasses[spec.name] = spec

    _fill_args(contract)
    entrypoint = _find_entrypoint(tree)
    _fill_entrypoint(contract, entrypoint)
    _fill_output(contract, entrypoint, tree)
    _fill_type_uses(contract, entrypoint)
    contract.tool_calls = _collect_tool_calls(tree)

    return contract, findings


def check_script(source: str, path: str, node_type: NodeType | None = None) -> list[Finding]:
    """스크립트 하나의 전체 정적 검사. 아래 검사들을 전부 돌려 합친다.

    `node_type` 이 없으면(스크립트 단독 등록) 타입별 형식 요구는 건너뛴다 —
    그건 노드 등록 시에 돈다.

    **실패를 최대한 수집한다** — 하나 걸렸다고 나머지를 멈추지 않는다.
    """
    contract, findings = extract_contract(source, path)
    findings.extend(check_entrypoint(contract))
    findings.extend(check_args_shape(contract))
    findings.extend(check_types(contract))
    findings.extend(check_bans(source, path, contract))
    if node_type is not None:
        findings.extend(check_node_type_form(contract, node_type))
    return findings


def check_entrypoint(contract: ScriptContract) -> list[Finding]:
    """`runNode(args: Args)` 형태인지, `returnResult()` 로 **dataclass** 를 내보내는지.

    `STR-CONTRACT-001` (Args 미선언) / `-002` (진입점) / `-003` (반환).

    **`-003` 은 두 경우를 한 규칙으로 낸다** — `returnResult()` 미호출과
    **출력 타입이 dataclass 가 아닌 경우**(primitive·미확정). 타입 동일성을
    **구조로** 판정하는 이상 primitive 출력은 성립하지 않으므로, 둘 다 고치는 방법이
    *"`returnResult()` 로 dataclass 를 내보내라"* 하나다 (`rules.md` `STR-CONTRACT-003`).
    """
    findings: list[Finding] = []
    fields: dict[str, object] = {"file": contract.path}
    if not contract._has_args:
        findings.append(rules.finding("STR-CONTRACT-001", path=contract.path, fields=fields))
    if not contract._entrypoint_ok:
        findings.append(rules.finding("STR-CONTRACT-002", path=contract.path, fields=fields))
    if not contract._returns_result or contract.output_type not in contract.dataclasses:
        findings.append(rules.finding("STR-CONTRACT-003", path=contract.path, fields=fields))
    return findings


def check_args_shape(contract: ScriptContract) -> list[Finding]:
    """`Args` 가 `input`/`params`/`state` 외의 필드를 갖지 않는지 (`STR-CONTRACT-004`).

    `Args.state` 필드 이름에 `__` 접두를 사용자가 쓰지 않았는지도 본다
    (`STR-STATE-001` — `__` 는 엔진 제공 필드 예약).

    **필드 생략은 위반이 아니다.** 입력이 없는 Vantage 는 `input` 을 아예 두지 않는다.
    """
    findings: list[Finding] = []

    unknown = [name for name in contract._args_fields if name not in ARGS_FIELDS]
    if unknown:
        findings.append(
            rules.finding(
                "STR-CONTRACT-004",
                path=contract.path,
                fields={"names": ", ".join(unknown)},
            )
        )

    for name in contract.state_names:
        if name.startswith("__"):
            findings.append(
                rules.finding("STR-STATE-001", path=contract.path, fields={"name": name})
            )
    return findings


def check_types(contract: ScriptContract) -> list[Finding]:
    """선언된 타입이 primitive 집합 + dataclass 뿐인지.

    `STR-TYPE-001` (`dict`) / `-002` (`Optional`·`None`) / `-003` (그 밖).

    **검사 대상은 선언된 모든 타입**이다 — dataclass 필드 전부와 `runNode` 의 반환
    어노테이션. 같은 타입 표기가 여러 번 나와도 한 번만 보고한다.

    ★ **판정은 `typesys.primitives.check_allowed` 가 한다.** 여기서 표를 복제하면
    어휘가 두 벌이 되어 갈라진다 — 실제로 그랬다.
    """
    known = frozenset(contract.dataclasses)
    findings: list[Finding] = []
    seen: set[str] = set()
    for used in contract._type_uses:
        text = str(used)
        if text in seen:
            continue
        seen.add(text)
        findings.extend(check_allowed(used, known=known, path=contract.path))
    return findings


def check_bans(source: str, path: str, contract: ScriptContract) -> list[Finding]:
    """금지 패턴. `STR-BAN-001` (시간) / `-002` (랜덤) / `-003` (직접 subprocess) /
    `-004` (미선언 state 참조).

    `tool` 로 선언된 함수가 부가적으로 subprocess 를 띄우는 것은 막지 않는다 —
    `Args.state` 와 같은 구조다: **미리 선언하면 허용, 선언 없으면 에러.**
    """
    tree = _parse(source, path)
    aliases = _import_aliases(tree)
    allowed_states = set(contract.state_names) | ENGINE_STATE_FIELDS

    # (규칙, 이름) 로 중복을 없앤다 — 같은 사실을 두 번 보고하지 않는다.
    hits: dict[tuple[str, str], tuple[int, int]] = {}

    def record(rule_id: str, name: str, node: ast.AST) -> None:
        key = (rule_id, name)
        where = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
        if key not in hits or where < hits[key]:
            hits[key] = where

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                rule_id = _BANNED_MODULES.get(_root(alias.name))
                if rule_id:
                    record(rule_id, alias.name, node)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            rule_id = _BANNED_MODULES.get(_root(module))
            if rule_id:
                for alias in node.names:
                    record(rule_id, f"{module}.{alias.name}", node)
        elif isinstance(node, ast.Call):
            called = _resolve_call(node.func, aliases)
            rule_id = _BANNED_CALLS.get(called) if called else None
            if rule_id:
                record(rule_id, called, node)
        elif isinstance(node, ast.Attribute):
            state_name = _state_access(node, contract._param_name)
            if state_name is not None and state_name not in allowed_states:
                record("STR-BAN-004", state_name, node)

    return [
        rules.finding(rule_id, path=path, fields={"name": name, "file": path})
        for (rule_id, name), _ in sorted(hits.items(), key=lambda item: (item[1], item[0]))
    ]


def check_node_type_form(contract: ScriptContract, node_type: NodeType) -> list[Finding]:
    """노드 타입별 형식 요구 — **노드 타입별로 갈리는 유일한 검사**다.

    - Reckon: `Args.params` 에 기댓값 필드가 있어야 한다 (`STR-CONTRACT-005`).
      없으면 기획 파일이 껍데기가 되고, 기획을 고쳐도 판정이 안 바뀌며,
      "같은 기획을 A/B 에 돌린다"가 성립하지 않는다. **형식 제한이 그 자리를 없앤다.**
    - Action: `Args.input` 타입 == 반환 타입이어야 한다 (`STR-CONTRACT-006`).
      Action 은 중간에서 **부작용만** 일으키고 데이터 변환은 하지 않는다.
    """
    fields: dict[str, object] = {"file": contract.path}
    if node_type == "reckon" and not _has_expected_field(contract):
        return [rules.finding("STR-CONTRACT-005", path=contract.path, fields=fields)]
    if node_type == "action" and (
        not contract.input_type or contract.input_type != contract.output_type
    ):
        return [rules.finding("STR-CONTRACT-006", path=contract.path, fields=fields)]
    return []


def check_tool_calls(contract: ScriptContract, tool: dict[str, object]) -> list[Finding]:
    """스크립트의 외부 도구 호출이 Spec `tool` 선언 안에 드는지 (**실행 시점**).

    `STR-TOOL-001` (함수명 미선언) / `-002` (실행파일 경로 미선언).

    **검사 강도는 얕다** — 함수 호출 형태 전체가 아니라 **함수명 + 그 인자로 적힌
    실행파일 경로**를 대조하는 정도다. 인자 전체를 검증하려 들면 strictler 가 외부
    도구의 API 를 알아야 하고, 그건 "외부 도구는 철저히 외부로 분리한다"를 깬다.

    ★ **무엇이 "도구 호출" 인가는 `tool` 선언이 정한다.** 추출은 경로처럼 생긴 문자열
    인자를 가진 호출을 전부 모으지만(선언을 모르는 시점이므로), 판정은
    **함수명이 선언돼 있거나 경로가 선언돼 있는 것**만 대상으로 한다.
    그러지 않으면 `open("/etc/hosts")` 가 `STR-TOOL-001` 이 되어 **자유인 파일 IO 를
    막아버린다** (`schema.md` 6절: 파일 IO·네트워크는 전부 자유).
    """
    functions: set[str] = set()
    paths: set[str] = set()
    for decl in tool.values():
        functions.update(_decl_functions(decl))
        decl_path = _decl_path(decl)
        if decl_path:
            paths.add(decl_path)

    findings: list[Finding] = []
    for name, executable in contract.tool_calls:
        known_function = name in functions
        known_path = executable in paths
        if not known_function and not known_path:
            continue  # 도구 호출이 아니다 — 그냥 경로 문자열을 받는 보통 함수다
        if not known_function:
            findings.append(
                rules.finding("STR-TOOL-001", path=contract.path, fields={"name": name})
            )
        if not known_path:
            findings.append(
                rules.finding("STR-TOOL-002", path=contract.path, fields={"path": executable})
            )
    return findings


# --- 추출 내부 ------------------------------------------------------------


def _parse(source: str, path: str) -> ast.Module:
    """소스를 AST 로. 실패는 **위반이 아니라 도구가 못 돈 것**이다."""
    try:
        return ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise StrictlerError(
            f"스크립트를 파싱할 수 없습니다: {path} ({exc.lineno}행: {exc.msg}). "
            "노드 스크립트는 문법이 올바른 파이썬 파일이어야 합니다 — "
            "검사기는 파일을 돌리지 않고 `ast` 로 읽기만 하므로 문법 오류는 검사 자체를 막습니다."
        ) from exc


def _is_dataclass(node: ast.ClassDef) -> bool:
    """`@dataclass` / `@dataclasses.dataclass` / `@dataclass(frozen=True)` 를 알아본다."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "dataclass":
            return True
    return False


def _dataclass_spec(node: ast.ClassDef, path: str) -> DataclassSpec:
    """클래스 본문의 `이름: 타입` 선언만 필드로 삼는다."""
    fields: list[FieldSpec] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.append(FieldSpec(stmt.target.id, _type_of(stmt.annotation)))
    return DataclassSpec(node.name, tuple(fields), origin=path)


def _type_of(annotation: ast.expr) -> TypeRef:
    """어노테이션을 `TypeRef` 로. 해석이 안 되면 **원문 그대로의 미지 타입**으로 둔다 —
    그러면 `check_types` 가 `STR-TYPE-003` 으로 잡는다 (도구 오류로 터지지 않는다)."""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        text = annotation.value  # 문자열 어노테이션(`"Button"`)
    else:
        text = ast.unparse(annotation)
    try:
        return parse_type(text)
    except StrictlerError:
        return TypeRef(text)


def _fill_args(contract: ScriptContract) -> None:
    spec = contract.dataclasses.get(ARGS_NAME)
    if spec is None:
        return
    contract._has_args = True
    contract._args_fields = tuple(field.name for field in spec.fields)
    for field in spec.fields:
        if field.name == "input":
            contract.input_type = str(field.type)
        elif field.name == "params":
            contract.params_type = str(field.type)
        elif field.name == "state":
            contract.state_type = str(field.type)

    state_spec = contract.dataclasses.get(contract.state_type)
    if state_spec is not None:
        contract.state_names = tuple(field.name for field in state_spec.fields)


def _find_entrypoint(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == ENTRYPOINT:
            return stmt
    return None


def _fill_entrypoint(
    contract: ScriptContract, entrypoint: ast.FunctionDef | ast.AsyncFunctionDef | None
) -> None:
    if entrypoint is None:
        return
    contract._has_entrypoint = True
    spec = entrypoint.args
    positional = list(spec.posonlyargs) + list(spec.args)
    if len(positional) != 1 or spec.vararg or spec.kwarg or spec.kwonlyargs:
        return
    only = positional[0]
    contract._param_name = only.arg
    if only.annotation is None:
        return
    contract._entrypoint_ok = _type_of(only.annotation).base == ARGS_NAME


def _fill_output(
    contract: ScriptContract,
    entrypoint: ast.FunctionDef | ast.AsyncFunctionDef | None,
    tree: ast.Module,
) -> None:
    """출력 타입은 **반환 어노테이션 → `returnResult()` 인자** 순으로 찾는다.

    반환 타입 이름은 자유이므로 이름 규약으로는 못 찾는다. 대신 이 두 자리는
    AI 가 쓰는 형태에서 거의 언제나 하나는 있다.
    """
    scope: ast.AST = entrypoint if entrypoint is not None else tree
    call = _find_result_call(scope)
    contract._returns_result = call is not None

    if entrypoint is not None and entrypoint.returns is not None:
        name = _type_of(entrypoint.returns).base
        if name in contract.dataclasses:
            contract.output_type = name
            return

    if call is None or not call.args:
        return
    contract.output_type = _value_type(call.args[0], scope, contract)


def _find_result_call(scope: ast.AST) -> ast.Call | None:
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and _callee_name(node.func) == RESULT_FN:
            return node
    return None


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _value_type(value: ast.expr, scope: ast.AST, contract: ScriptContract) -> str:
    """`returnResult(...)` 에 넘긴 값의 dataclass 이름. 못 찾으면 `""`."""
    known = contract.dataclasses
    if isinstance(value, ast.Call):
        name = _callee_name(value.func)
        return name if name in known else ""
    if isinstance(value, ast.Attribute):
        # `returnResult(args.input)` — **통과형**. CLAUDE.md 가 조건 분기의 표준 표현으로
        # 못박은 *"스크립트가 그냥 `input` 을 반환한다"* 가 이 형태이고, Action 의
        # 교과서적 모습이기도 하다. 여기를 못 뽑으면 `output_type` 이 비어
        # `STR-CONTRACT-006` 이 오탐된다.
        if (
            value.attr == "input"
            and isinstance(value.value, ast.Name)
            and value.value.id == contract._param_name
        ):
            # `output_type` 은 **dataclass 이름**이라는 계약을 지킨다 — primitive 통과형은
            # 여기서 비우고 `STR-CONTRACT-003` 이 잡는다.
            return contract.input_type if contract.input_type in known else ""
        return ""
    if isinstance(value, ast.Name):
        # `result = Percept(...)` / `returnResult(result)` 형태를 한 단계만 따라간다.
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == value.id:
                        name = _callee_name(node.value.func)
                        if name in known:
                            return name
    return ""


def _fill_type_uses(
    contract: ScriptContract, entrypoint: ast.FunctionDef | ast.AsyncFunctionDef | None
) -> None:
    used: list[TypeRef] = []
    for spec in contract.dataclasses.values():
        used.extend(field.type for field in spec.fields)
    if entrypoint is not None and entrypoint.returns is not None:
        used.append(_type_of(entrypoint.returns))
    contract._type_uses = tuple(used)


def _collect_tool_calls(tree: ast.Module) -> list[tuple[str, str]]:
    """`(함수명, 경로처럼 생긴 문자열 인자)` 를 전부 모은다.

    **여기서는 거르지 않는다** — 무엇이 도구 호출인지는 Spec 의 `tool` 선언을 아는
    `check_tool_calls` 만 판정할 수 있다.
    """
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node.func)
        if not name:
            continue
        values = list(node.args) + [kw.value for kw in node.keywords]
        for value in values:
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and _is_path_like(value.value)
            ):
                found.append((name, value.value))
    return found


def _is_path_like(text: str) -> bool:
    """절대경로 규칙(`schema.md` 3절)을 그대로 쓴다 — `/`·`~`·`${env.…}` 로 시작하는 것."""
    return text.startswith(("/", "~")) or text.startswith("${env.")


# --- 검사 내부 ------------------------------------------------------------


def _has_expected_field(contract: ScriptContract) -> bool:
    """Reckon 의 기댓값 자리가 실제로 있는가.

    **어느 필드가 기댓값인지는 판정하지 않는다** — 도메인 지식이라 도구가 모른다.
    `Args.params` 가 있고 내용이 비어 있지 않으면 된다. 값이 Spec 에서 온다는 것,
    그게 이 검사가 지키는 전부다.
    """
    if not contract.params_type:
        return False
    spec = contract.dataclasses.get(contract.params_type)
    if spec is None:
        return True  # primitive params — 값은 여전히 Spec 이 준다
    return bool(spec.fields)


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """지역 이름 → 원래 모듈 경로. `import os as o` 를 따라가기 위한 것."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    aliases[_root(alias.name)] = _root(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = f"{module}.{alias.name}" if module else alias.name
    return aliases


def _resolve_call(func: ast.expr, aliases: dict[str, str]) -> str:
    """호출 대상의 점 표기 이름을 import 별칭까지 풀어서 돌려준다."""
    dotted = _dotted(func)
    if not dotted:
        return ""
    head, _, rest = dotted.partition(".")
    target = aliases.get(head)
    if target is None:
        return dotted
    return f"{target}.{rest}" if rest else target


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else ""
    return ""


def _root(module: str) -> str:
    return module.split(".", 1)[0]


def _state_access(node: ast.Attribute, param_name: str) -> str | None:
    """`args.state.X` 형태면 `X` 를 돌려준다. 아니면 `None`."""
    inner = node.value
    if not isinstance(inner, ast.Attribute) or inner.attr != "state":
        return None
    if not isinstance(inner.value, ast.Name) or inner.value.id != param_name:
        return None
    return node.attr


def _decl_functions(decl: object) -> list[str]:
    functions = decl.get("functions") if isinstance(decl, dict) else getattr(decl, "functions", ())
    return [str(name) for name in (functions or ())]


def _decl_path(decl: object) -> str:
    value = decl.get("path") if isinstance(decl, dict) else getattr(decl, "path", "")
    return str(value or "")
