"""스크립트 하나를 로드·실행하고 input/output 을 검증한다 (`schema.md` 6·7절).

**사용자 코드 실행에 샌드박싱은 하지 않는다.** ESLint 플러그인·vite 플러그인·
jest transform 이 전부 사용자 코드를 그냥 로드해 실행한다. lint 계열의 표준
신뢰 모델을 그대로 따른다 (`schema.md` 16절 — 폐기된 안).

**★ 노드 내부는 input / output 만 맞추면 된다.** 내부에서 AI 를 부르든 파일을 읽든
네트워크를 타든 엔진은 관여하지 않는다. **순수함수는 강제하지 않는다.**
AI 를 껴서 output 을 잘못 내놓으면 **타입 계약에 걸려 그냥 에러**다. 그걸로 충분하다.

**pydantic 경계 검증이 실제 값을 만나는 자리**가 여기와 단위테스트 하네스 둘뿐이다.

여기서 나가는 실패는 전부 **오류**(`error`)다 — 위반이 아니다. 스크립트가 예외를
내는 것도, 선언한 타입과 다른 값을 내놓는 것도 *기획과 다르다* 가 아니라
*도구가 못 돈 것*이다 (`schema.md` 9절).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, Mapping

from pydantic import BaseModel, ValidationError

from lintomata import deps
from lintomata.checks.script import RESULT_FN, ScriptContract
from lintomata.errors import Finding, LintomataError
from lintomata.locale import message, translate
from lintomata.model import LIBRARY_NAMESPACE
from lintomata.typesys.primitives import PRIMITIVES, TypeRef, element_type, is_list
from lintomata.typesys.registry import TypeKey, TypeRegistry

__all__ = [
    "ENTRYPOINT",
    "load_script",
    "compile_source",
    "build_args",
    "invoke",
    "validate_input",
    "validate_output",
    "as_mapping",
]


ENTRYPOINT = "runNode"
"""진입점 이름은 고정이다 (`schema.md` 6절). 엔진이 찾는 것은 이 이름 하나뿐이고,
출력은 스크립트가 `returnResult()` 로 내보낸 것이 그대로 반환값이 된다."""


def _return_result(value: Any) -> Any:
    """`returnResult()` — 출력 함수. **엔진이 스크립트에 넣어 준다.**

    이름이 고정인 두 심볼 중 하나인데(`runNode` / `returnResult`), `runNode` 는
    스크립트가 **정의**하는 것이고 이쪽은 스크립트가 **호출**하는 것이다.
    어디에도 정의가 없으면 모든 스크립트가 `NameError` 로 죽으므로 로드 시점에
    모듈 전역에 심는다 — `import` 한 줄을 모든 스크립트에 강요하지 않기 위해서다.

    하는 일은 **값을 그대로 돌려주는 것뿐**이다. 여기서 뭘 하기 시작하면 그게
    "내장 동작" 이 된다 — 타입 검증은 `validate_output` 의 몫이다.
    """
    return value


# ── 로드 ─────────────────────────────────────────────────────────────────────


def compile_source(module: ModuleType, path: Path) -> None:
    """파일을 **소스에서 컴파일해** 모듈 네임스페이스에 실행한다.

    ★ **바이트코드 캐시를 쓰지 않는다** (`schema.md` 2절). `spec.loader.exec_module`
    를 쓰면 파이썬이 `__pycache__/*.pyc` 를 만들고 다음 로드 때 그것을 읽는데,
    pyc 의 무효화 기준은 **원본의 mtime + 크기**뿐이다. 이 도구는 그 기준을 못 믿어서
    **내용 해시**로 검증 결과를 재사용하는데(`checks/contracts.py`), 그 밑에서
    mtime 기반 캐시가 돌면 **원본은 바뀌었는데 옛 바이트코드가 실행되어 거짓 통과**가
    난다 — 리포트가 검사하지 않은 것을 통과라고 말하는 자리다.

    두 방향을 같이 막는다: 소스에서 직접 컴파일하므로 **기존 pyc 를 읽지 않고**,
    `sys.dont_write_bytecode` 로 로드 도중의 **쓰기도 막는다**(스크립트가 최상단에서
    import 하는 것들까지). 전역 상태이므로 **끝나면 원래 값으로 되돌린다.**

    바이트로 읽어 넘긴다 — 인코딩 선언(`# -*- coding: -*-`)은 `compile` 이 본다.
    """
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    finally:
        sys.dont_write_bytecode = saved


def load_script(path: Path, libraries: Mapping[str, Path] | None = None) -> ModuleType:
    """스크립트 파일을 모듈로 로드한다.

    **의존성 격리는 없다 — 스크립트는 lintomata 와 같은 프로세스에 로드된다**
    (`schema.md` 6절). 그래서 스크립트의 `import` 는 lintomata 가 설치된 환경에서
    풀린다. PEP 723 헤더는 **선언일 뿐 격리를 만들지 않는다** — 등록 시점에
    `deps.check_dependencies` 가 그 선언을 읽어 확인할 뿐이다.
    여기서는 그냥 로드하고, 못 찾은 모듈이 헤더에 선언돼 있으면 설치 명령을 안내한다.

    모듈 이름은 **경로 해시**로 만든다. 파일 이름을 그대로 쓰면 서로 다른
    파이프라인의 같은 이름 스크립트가 `sys.modules` 에서 충돌한다.

    **`returnResult` 를 모듈 전역에 심어 준다** — 스크립트가 정의하지 않는 고정
    이름이기 때문이다. 스크립트가 자기 것을 정의하거나 import 하면 그쪽이 이긴다
    (exec 이 나중이므로).

    `libraries` 는 **노드가 배선한 것**이다 (`{슬롯: 파일}`, `schema.md` 6.5절).
    로드 **직전에** `lintomata_lib.<슬롯>` 으로 심고 로드가 끝나면 **걷는다** —
    `_installed_libraries` 참조. `sys.path` 는 건드리지 않는다: 형제 파일 import 를
    되게 만드는 것이 아니라, **배선된 것만** 그 네임스페이스로 들어오게 하는 것이다.

    본문은 `spec.loader.exec_module` 이 아니라 `compile_source` 로 돌린다 —
    **바이트코드 캐시를 읽지도 쓰지도 않기 위해서다.** 이유는 거기에 적혀 있다.
    """
    tag = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    name = f"lintomata_node_{tag}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LintomataError(
            message(
                "Cannot load the script as a module: {path}\n"
                "A node script must be a single `.py` file.",
                path=path,
            )
        )
    module = importlib.util.module_from_spec(spec)
    setattr(module, RESULT_FN, _return_result)
    sys.modules[name] = module
    try:
        with _installed_libraries(libraries or {}):
            compile_source(module, path)
    except BaseException as exc:  # noqa: BLE001 - 사용자 코드는 무엇이든 던질 수 있다
        sys.modules.pop(name, None)
        raise LintomataError(_load_failure(path, exc)) from exc
    return module


@contextmanager
def _installed_libraries(libraries: Mapping[str, Path]) -> Iterator[None]:
    """`lintomata_lib.<슬롯>` 을 **로드하는 동안만** 심는다 (`schema.md` 6.5절).

    ### 왜 네임스페이스인가
    같은 이름의 실제 패키지를 가리는 사고를 막기 위해서다. `import buttons` 였다면
    PyPI 의 `buttons` 를 조용히 덮어쓴다.

    ### 왜 끝나면 걷는가 — **남의 배선을 보지 않게**
    `sys.modules` 는 프로세스 전역이라 남겨두면 **다음 노드가 앞 노드의 배선을
    본다.** 스크립트는 `from lintomata_lib import X` 를 모듈 최상단에서만 쓰므로
    (`LNT-LIB-005`) 로드가 끝난 시점에 필요한 참조는 이미 붙잡혀 있고, 그 뒤에
    남은 것은 사고의 재료뿐이다. 늦은 import 는 조용히 남의 것을 집는 대신
    `ImportError` 로 터진다 — **틀린 값보다 오류가 낫다.**

    라이브러리 모듈 자체는 스크립트와 마찬가지로 **경로 해시**로 이름 지어
    `sys.modules` 에 남는다. 여기서 걷는 것은 `lintomata_lib` **네임스페이스**뿐이다.
    """
    package = ModuleType(LIBRARY_NAMESPACE)
    package.__doc__ = (
        "The library namespace lintomata installs from the node's wiring."
    )
    installed = [LIBRARY_NAMESPACE]
    saved = {LIBRARY_NAMESPACE: sys.modules.get(LIBRARY_NAMESPACE)}

    for slot, source in libraries.items():
        setattr(package, slot, _load_library(source))
        full = f"{LIBRARY_NAMESPACE}.{slot}"
        saved[full] = sys.modules.get(full)
        installed.append(full)
        sys.modules[full] = getattr(package, slot)
    sys.modules[LIBRARY_NAMESPACE] = package

    try:
        yield
    finally:
        for full in installed:
            previous = saved.get(full)
            if previous is None:
                sys.modules.pop(full, None)
            else:
                sys.modules[full] = previous


def _load_library(path: Path) -> ModuleType:
    """라이브러리 파일 하나를 모듈로. **`returnResult` 는 심지 않는다** — 노드가 아니다.

    이름은 스크립트와 같은 규칙(경로 해시)이라 서로 다른 경로의 같은 파일명이
    `sys.modules` 에서 충돌하지 않는다. 로드 방식도 같다 — **바이트코드 캐시를
    쓰지 않는다**(`compile_source`). 라이브러리도 등록소가 해시로 관리하는 파일이다.
    """
    tag = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    name = f"lintomata_library_{tag}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LintomataError(
            message(
                "Cannot load the library as a module: {path}\n"
                "A library must be a single `.py` file.",
                path=path,
            )
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        compile_source(module, path)
    except BaseException as exc:  # noqa: BLE001 - 사용자 코드는 무엇이든 던질 수 있다
        sys.modules.pop(name, None)
        raise LintomataError(
            message(
                "Loading the library raised: {path}\n"
                "{detail}\n"
                "Importing a library must have no side effect — keep function "
                "definitions only.",
                path=path,
                detail=f"{type(exc).__name__}: {exc}",
            )
        ) from exc
    return module


def _load_failure(path: Path, exc: BaseException) -> str:
    """로드 실패 메시지. **`ModuleNotFoundError` 는 따로 안내한다.**

    모듈을 못 찾은 것은 **부작용 문제가 아니다.** 둘을 한 문구로 묶으면
    *"import 만으로 부작용이 없어야 한다"* 를 읽고 엉뚱한 곳을 고치게 된다 —
    읽는 주체가 AI 라서 안내가 곧 수정 방향이다.

    그 밖의 예외(상수 계산 실패 등)에는 기존 안내가 그대로 맞다.
    """
    head = message(
        "Loading the script raised: {path}\n{detail}\n",
        path=path,
        detail=f"{type(exc).__name__}: {exc}",
    )
    guide = _missing_module_guide(path, exc)
    if guide:
        return head + guide
    return head + message(
        "It blew up at module top level (imports, constant computation …). "
        "Importing a node script must have no side effect — put the actual work "
        "inside `runNode(args)`."
    )


def _missing_module_guide(path: Path, exc: BaseException) -> str:
    """`ModuleNotFoundError` 전용 안내. 다른 예외면 `""`.

    **형제 파일 import 는 되지 않는다.** 스크립트가 있는 디렉터리는 `sys.path` 에
    없고(엔진이 넣지 않는다), 등록하면 **스크립트 파일 하나만** 등록소로 복사되므로
    옆 파일은 따라오지 않는다 — 등록소는 *"파일 하나 = 엔트리 하나"* 위에 서 있고
    `schema.md` 2절이 **원본을 지워도 된다**고 못 박았다. 옆 파일에 기대면 그 약속이
    깨진다. 그래서 이 안내는 **경로를 고치라고 하지 않고 구조를 바꾸라고 한다.**

    PEP 723 헤더에 선언된 모듈이면 그 대조 결과를 **위에 얹는다**
    (`deps.missing_module_hint`) — 선언은 했는데 환경에 없는 것이므로 고칠 곳이
    다르고, 요구 원문 그대로의 설치 명령을 줄 수 있다.

    **원인이 확정된 자리에는 다른 방향을 얹지 않는다.** 못 찾은 것이 **설치된
    패키지의 서브모듈**이면(`pydantic.없는것`) 형제 파일 이야기는 잡음이다 —
    그 문단은 **원인을 모르는 경우**(헤더에 선언도 없는 경우)에만 붙는다.
    거기가 이 안내가 가장 쓸모 있는 자리다.

    **소스를 못 읽는 것은 여기서 문제 삼지 않는다.** 이미 실패한 예외에 문장을
    덧붙이는 자리라서, 여기서 새 예외를 내면 원인이 뭉개진다.
    """
    if not isinstance(exc, ImportError) or not exc.name:
        return ""

    if exc.name == LIBRARY_NAMESPACE or exc.name.startswith(f"{LIBRARY_NAMESPACE}."):
        # **안 배선된 슬롯**을 가져오려 한 것이다. `from X import Y` 실패는
        # `ModuleNotFoundError` 가 아니라 그냥 `ImportError` 로 온다 — 네임스페이스
        # 자체는 (비어 있을지언정) 언제나 심겨 있기 때문이다.
        # 원인이 확정된 자리이므로 형제 파일 이야기는 얹지 않는다.
        return message(
            "`{namespace}` only ever holds **the library slots the node wired** — "
            "this script has no such wiring.\n"
            'Add `"libraries": { "<slot>": "${ref.lb_...}" }` to the node JSON '
            "(an absolute path works too). At registration time `LNT-LIB-001` "
            "points at the same thing.",
            namespace=LIBRARY_NAMESPACE,
        )

    if not isinstance(exc, ModuleNotFoundError):
        # 여기부터는 *모듈을 못 찾은 것* 에 대한 안내다. 다른 종류의 `ImportError`
        # (이름을 못 가져온 것)에 설치 명령을 붙이면 엉뚱한 곳을 고치게 된다.
        return ""

    submodule = deps.missing_submodule_hint(exc.name)
    if submodule:
        return submodule

    declared = ""
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    else:
        hint = deps.missing_module_hint(source, exc.name)
        declared = f"{hint}\n" if hint else ""

    return declared + message(
        "Module not found: `{module}`. **Importing a sibling file does not work** "
        "— the directory the script sits in is not on `sys.path`, and "
        "registration copies the script file alone into the registry, so the file "
        "next to it does not come along.\n"
        "Shared logic goes one of three ways: (1) **register it as a library and "
        "let the node wire it** — `lintomata library add <file>`, then "
        '`"libraries": { "<slot>": "${ref.lb_...}" }` in the node JSON and '
        "`from lintomata_lib import <slot>` in the script (this is the way for "
        "project-specific decision logic). (2) Instead of sharing the function, "
        "**reuse the node that makes that decision**. (3) If it is generic "
        "third-party code, make it a small package and install it into the "
        "lintomata environment — `uv tool install lintomata --with <package>`, "
        "then declare it in the PEP 723 header so it is checked at registration "
        "time.",
        module=exc.name,
    )


# ── 값 조립 ──────────────────────────────────────────────────────────────────


def as_mapping(value: Any) -> dict[str, Any]:
    """dataclass 인스턴스 / pydantic 모델 / 매핑을 **얕은 dict** 로 본다.

    중첩은 재귀 시점에 다시 이 함수를 거치므로 여기서 깊이 펼치지 않는다 —
    깊이 펼치면 `bytes` 같은 값까지 건드리게 된다.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, BaseModel):
        return {name: getattr(value, name) for name in type(value).model_fields}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    raise LintomataError(
        message(
            "This value cannot be read as a dataclass: {value} ({type})\n"
            "Values travelling between nodes must be dataclasses declared by the "
            "script (`schema.md` §7 — a composite type is always a dataclass).",
            value=repr(value),
            type=type(value).__name__,
        )
    )


def _instantiate(
    module: ModuleType, type_name: str, raw: Any, contract: ScriptContract, where: str
) -> Any:
    """스크립트가 선언한 dataclass 하나를 값으로 만든다.

    **이 스크립트의 선언을 기준으로** 필드를 골라 담는다 — 병합 클래스가 끌고 온
    여분 필드는 여기서 자연히 떨어진다 (`schema.md` 7절: 병합은 표현 층에서만).
    """
    spec = contract.dataclasses.get(type_name)
    cls = getattr(module, type_name, None)
    if spec is None or cls is None:
        raise LintomataError(
            message(
                "The script has no dataclass `{type}`: {path} ({where})\n"
                "The type name `Args` declares and the actual class name must "
                "match.",
                type=type_name,
                path=contract.path,
                where=where,
            )
        )
    data = as_mapping(raw)
    kwargs: dict[str, Any] = {}
    for field in spec.fields:
        if field.name not in data:
            raise LintomataError(
                message(
                    "There is no value to fill `{type}.{field}` with "
                    "({where}, {path})\n"
                    "Fields present in the incoming value: {fields}. Every "
                    "declared field must be filled — there is no `Optional`, so "
                    "nothing may be left empty.",
                    type=type_name,
                    field=field.name,
                    where=where,
                    path=contract.path,
                    fields=", ".join(sorted(data)) or translate("(none)"),
                )
            )
        kwargs[field.name] = _coerce(module, field.type, data[field.name], contract, where)
    return cls(**kwargs)


def _coerce(
    module: ModuleType, ref: TypeRef, value: Any, contract: ScriptContract, where: str
) -> Any:
    """선언된 타입에 맞춰 값을 이 스크립트의 어휘로 옮긴다."""
    if is_list(ref):
        if not isinstance(value, (list, tuple)):
            raise LintomataError(
                message(
                    "A non-list value arrived where `{type}` was declared: "
                    "{value} ({where})",
                    type=ref,
                    value=repr(value),
                    where=where,
                )
            )
        return [_coerce(module, element_type(ref), item, contract, where) for item in value]
    if ref.name in PRIMITIVES:
        return value
    return _instantiate(module, ref.name, value, contract, where)


def build_args(
    module: ModuleType,
    contract: ScriptContract,
    *,
    input_value: Any = None,
    params: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> Any:
    """스크립트가 선언한 `Args` 인스턴스를 만든다.

    **세 필드는 쓰는 것만 선언한다** — 입력이 없는 Prepare 는 `input` 필드를
    아예 두지 않으므로, 선언에 없는 필드는 채우지 않는다.

    반대로 **선언한 필드는 반드시 채운다.** `input` 을 선언했는데 배선이 없으면
    그건 오류다 — 빈 껍데기를 만들어 넣는 것은 `Optional` 금지의 취지에 어긋난다.
    """
    args_spec = contract.dataclasses.get("Args")
    args_cls = getattr(module, "Args", None)
    if args_spec is None or args_cls is None:
        raise LintomataError(
            message(
                "No `Args` dataclass found: {path}\n"
                "Every node script declares a dataclass named `Args` and takes "
                "the form `runNode(args: Args)`.",
                path=contract.path,
            )
        )

    sources: dict[str, Any] = {
        "input": input_value,
        "params": dict(params or {}),
        "state": _state_fields(contract, state or {}),
    }

    kwargs: dict[str, Any] = {}
    for field in args_spec.fields:
        if field.name not in sources:
            raise LintomataError(
                message(
                    "`Args` has an unknown field: {field} ({path})\n"
                    "The fields of `Args` are `input` / `params` / `state`, "
                    "nothing else.",
                    field=repr(field.name),
                    path=contract.path,
                )
            )
        value = sources[field.name]
        if field.name == "input" and value is None:
            raise LintomataError(
                message(
                    "`Args.input` is declared but no upstream value arrived: "
                    "{path}\n"
                    "Either add an `inputs` wiring to this node in the pipeline, "
                    "or — if the node takes no input — delete the `input` field "
                    "from `Args` (declare only what you use).",
                    path=contract.path,
                )
            )
        kwargs[field.name] = _coerce(
            module, field.type, value, contract, f"Args.{field.name}"
        )
    return args_cls(**kwargs)


def _state_fields(contract: ScriptContract, state: Mapping[str, Any]) -> dict[str, Any]:
    """`Args.state` 에 담을 것만 고른다.

    `__startedAt` 같은 엔진 제공 필드는 스크립트가 선언할 수 없으므로
    (`LNT-STATE-001`) 여기서 떨군다 — 그건 `${state.__startedAt}` 로 `params` 에서
    참조하는 자리다.
    """
    return {name: state[name] for name in contract.state_names if name in state}


def invoke(module: ModuleType, args: Any) -> Any:
    """`runNode(args)` 를 호출하고 `returnResult()` 로 나온 값을 준다.

    스크립트가 예외를 내면 그건 **오류**다 — 위반이 아니다 (`schema.md` 9절).
    호출자가 `Finding(status="error")` 로 바꾼다.
    """
    entry = getattr(module, ENTRYPOINT, None)
    if entry is None or not callable(entry):
        raise LintomataError(
            message(
                "No entry point `{entrypoint}(args)`: {path}\n"
                "The entry point name is fixed and the same for every node type.",
                entrypoint=ENTRYPOINT,
                path=getattr(module, "__file__", "?"),
            )
        )
    file = getattr(module, "__file__", "") or ""
    try:
        return entry(args)
    except BaseException as exc:  # noqa: BLE001 - 사용자 코드는 무엇이든 던질 수 있다
        # 늦은 import 가 `runNode` 안에서 터지는 경우도 있다 — 같은 안내를 준다.
        guide = _missing_module_guide(Path(file), exc) if file else ""
        raise LintomataError(
            message(
                "`{entrypoint}` raised: {path}\n"
                "{detail}\n"
                "A script exception is not a violation, it is an **error** — "
                "nothing differs from the plan, the check itself could not run. "
                "Fix the script.",
                entrypoint=ENTRYPOINT,
                path=file or "?",
                detail=f"{type(exc).__name__}: {exc}",
            )
            + (f"\n{guide}" if guide else "")
        ) from exc


# ── 경계 검증 ────────────────────────────────────────────────────────────────


def validate_input(
    contract: ScriptContract,
    value: Any,
    registry: TypeRegistry,
    *,
    path: str,
    node: str,
) -> list[Finding]:
    """앞단에서 온 값이 이 노드의 `Args.input` 선언에 맞는지 (pydantic 경계 검증)."""
    if not contract.input_type:
        return []  # 입력을 안 받는 노드 — 볼 것이 없다
    return _validate(contract, contract.input_type, value, registry, path=path, node=node,
                     where="`Args.input`", hint=translate("the upstream node's output"))


def validate_output(
    contract: ScriptContract,
    value: Any,
    registry: TypeRegistry,
    *,
    path: str,
    node: str,
) -> list[Finding]:
    """반환값이 선언된 출력 타입에 맞는지.

    Act 의 **값 동일성**(input == output)은 여기서 보지 않는다 —
    그 검사의 자리는 단위테스트다 (`LNT-TEST-005`).
    """
    if not contract.output_type:
        return []  # `LNT-CONTRACT-003` 이 등록 시점에 이미 잡았다
    return _validate(contract, contract.output_type, value, registry, path=path, node=node,
                     where=translate("the return type"),
                     hint=translate("the value emitted by `returnResult()`"))


def _validate(
    contract: ScriptContract,
    type_name: str,
    value: Any,
    registry: TypeRegistry,
    *,
    path: str,
    node: str,
    where: str,
    hint: str,
) -> list[Finding]:
    """실제 값을 선언된 타입에 맞춰 본다.

    **규칙 id 가 없다.** `rules.md` 에 "실행 중 값이 선언된 타입과 다르다" 를 담는
    규칙이 없기 때문이다 — 배선 불일치(`LNT-TYPE-004`)는 등록 시점의 *선언끼리*
    대조이지 값 대조가 아니다. 대신 자연어 가이드를 붙여 낸다.
    """
    try:
        registry.to_value(TypeKey(contract.path, type_name), value)
    except ValidationError as exc:
        return [
            Finding(
                status="error",
                path=path,
                node=node,
                message=message(
                    "{where} (`{type}`) does not match the actual value: {path}\n"
                    "{detail}\n"
                    "{hint} must have the same fields and types as the declared "
                    "dataclass. If the declaration is what is wrong rather than "
                    "the value, fix the dataclass in the script.",
                    where=where,
                    type=type_name,
                    path=contract.path,
                    detail=exc,
                    hint=hint,
                ),
            )
        ]
    except LintomataError as exc:
        return [Finding(status="error", path=path, node=node, message=exc.message)]
    return []
