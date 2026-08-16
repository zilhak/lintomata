"""Step 2-b 테스트 공용 대역 — **`checks.script`(2-a) 와 `checks.reachability`(2-c) 만** 흉내낸다.

⚠ **`rules` / `refs` / `typesys` / `store` 는 대역을 쓰지 않는다.** Step 1 통합에서
남의 모듈을 stub 으로 끼고 돌린 탓에 슬롯 계약 위반 11건이 merge 시점까지 안 잡혔다.
여기서 진짜 구현을 그대로 쓰면 **규칙 슬롯 누락이 곧바로 `LintomataError` 로 터진다.**
"""

from __future__ import annotations

from typing import Any

from lintomata.typesys.primitives import parse_type
from lintomata.typesys.registry import DataclassSpec, FieldSpec


def dc(name: str, origin: str, **fields: str) -> DataclassSpec:
    """`dc("Args", "a.py", input="Html")` → `DataclassSpec`."""
    return DataclassSpec(
        name,
        tuple(FieldSpec(fname, parse_type(expr)) for fname, expr in fields.items()),
        origin,
    )


class FakeContract:
    """`ScriptContract` 의 **공개 필드만** 갖는 대역 (MODULES.md `checks/script.py` 절).

    2-a 가 아직 `NotImplementedError` 라 실제 계약 객체를 만들 수 없다. 필드 이름과
    의미는 MODULES.md 를 그대로 따른다 — 여기서 이름이 어긋나면 통합 때 터진다.
    """

    def __init__(
        self,
        path: str,
        *,
        dataclasses: dict[str, DataclassSpec] | None = None,
        input_type: str = "",
        params_type: str = "",
        state_type: str = "",
        state_names: tuple[str, ...] = (),
        output_type: str = "",
        tool_calls: list[tuple[str, str]] | None = None,
        library_slots: tuple[str, ...] = (),
    ) -> None:
        self.path = path
        self.dataclasses = dataclasses or {}
        self.input_type = input_type
        self.params_type = params_type
        self.state_type = state_type
        self.state_names = state_names
        self.output_type = output_type
        self.tool_calls = tool_calls or []
        self.library_slots = library_slots


def contract(
    origin: str,
    *,
    input_fields: dict[str, str] | None = None,
    output_fields: dict[str, str] | None = None,
    state_fields: dict[str, str] | None = None,
    params_fields: dict[str, str] | None = None,
    input_name: str = "In",
    output_name: str = "Out",
    state_name: str = "St",
    params_name: str = "Pm",
) -> FakeContract:
    """필드 딕셔너리에서 계약 하나를 조립한다. 선언 안 한 자리는 `""` 로 남는다."""
    declared: dict[str, DataclassSpec] = {}
    args_fields: dict[str, str] = {}

    if input_fields is not None:
        declared[input_name] = dc(input_name, origin, **input_fields)
        args_fields["input"] = input_name
    if params_fields is not None:
        declared[params_name] = dc(params_name, origin, **params_fields)
        args_fields["params"] = params_name
    if state_fields is not None:
        declared[state_name] = dc(state_name, origin, **state_fields)
        args_fields["state"] = state_name
    if output_fields is not None:
        declared[output_name] = dc(output_name, origin, **output_fields)

    declared["Args"] = dc("Args", origin, **args_fields)
    return FakeContract(
        origin,
        dataclasses=declared,
        input_type=input_name if input_fields is not None else "",
        params_type=params_name if params_fields is not None else "",
        state_type=state_name if state_fields is not None else "",
        state_names=tuple(state_fields) if state_fields else (),
        output_type=output_name if output_fields is not None else "",
    )


class ScriptStub:
    """`checks.script` 의 두 함수를 대역으로 갈아끼우는 도우미.

    경로 → 계약 표를 들고 `check_script` / `extract_contract` 를 흉내낸다.
    `check_script` 가 낼 `Finding` 도 경로별로 심을 수 있다 — 노드 타입이 실제로
    전달되는지 확인하려면 그 인자를 받아봐야 한다.
    """

    def __init__(self) -> None:
        self.by_path: dict[str, FakeContract] = {}
        self.findings: dict[str, list[Any]] = {}
        self.seen_types: list[tuple[str, Any]] = []
        self.seen_known: list[tuple[str, list[str]]] = []
        """`known_dependencies` 로 받은 것 — 등록소의 선언이 실제로 흘러오는지 본다."""

    def put(self, path: str, made: FakeContract) -> FakeContract:
        self.by_path[str(path)] = made
        return made

    def install(self, monkeypatch: Any) -> None:
        import lintomata.checks.script as script_module

        def check_script(
            source: str,
            path: str,
            node_type: Any = None,
            known_dependencies: Any = (),
            *,
            cache: Any = None,
        ) -> list[Any]:
            self.seen_types.append((path, node_type))
            self.seen_known.append((path, list(known_dependencies)))
            return list(self.findings.get(path, []))

        def extract_contract(source: str, path: str) -> tuple[Any, list[Any]]:
            return self.by_path.get(path, FakeContract(path)), []

        monkeypatch.setattr(script_module, "check_script", check_script)
        monkeypatch.setattr(script_module, "extract_contract", extract_contract)


def stub_reachability(monkeypatch: Any) -> None:
    """도달 가능성(2-c)은 별도 담당이다 — 여기서는 통과시킨다."""
    import lintomata.checks.reachability as reach

    monkeypatch.setattr(
        reach, "check_reachability", lambda pipeline, node_states, source_path: []
    )
