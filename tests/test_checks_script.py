"""`checks/script.py` — 스크립트 AST 검사.

**경계를 짚는다.** 구현을 되돌리면 깨지는 테스트여야 의미가 있다:
통과해야 하는 것(필드 생략·파일 IO·`__startedAt`)과 걸려야 하는 것을 짝으로 둔다.

★ **모든 오류 경로를 실제로 태워 `Finding.rule_id` 를 단언한다.**
슬롯이 비면 `rules.finding()` 이 `LintomataError` 를 내면서 규칙 id 가 통째로 사라지므로,
이 단언이 곧 슬롯 검증이다 (Step 1 통합에서 이게 없어 11건이 뒤늦게 깨졌다).
"""

from __future__ import annotations

import re

import pytest

from lintomata import model, refs, rules
from lintomata.checks import script as sc
from lintomata.engine import state
from lintomata.errors import Finding, LintomataError
from lintomata.typesys import primitives
from lintomata.typesys.registry import DataclassSpec, TypeRegistry

PATH = "/abs/scripts/node.py"


def ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


def only(findings: list[Finding], prefix: str) -> list[str]:
    return [rule_id for rule_id in ids(findings) if rule_id.startswith(prefix)]


# 최소한의 통과 스크립트 — 여기서 한 조각씩 무너뜨리며 경계를 본다.
GOOD = '''
from dataclasses import dataclass


@dataclass
class Html:
    text: str


@dataclass
class Params:
    expected: int


@dataclass
class State:
    stop: str


@dataclass
class Args:
    input: Html
    params: Params
    state: State


@dataclass
class Verdict:
    passed: bool


def runNode(args: Args) -> Verdict:
    if args.state.stop == "settled":
        pass
    return returnResult(Verdict(passed=len(args.input.text) == args.params.expected))
'''


def test_good_script_passes() -> None:
    assert sc.check_script(GOOD, PATH, "judge") == []


def test_contract_extracted() -> None:
    contract, findings = sc.extract_contract(GOOD, PATH)
    assert findings == []
    assert contract.input_type == "Html"
    assert contract.params_type == "Params"
    assert contract.state_type == "State"
    assert contract.state_names == ("stop",)
    assert contract.output_type == "Verdict"
    assert set(contract.dataclasses) == {"Html", "Params", "State", "Args", "Verdict"}


# --- 파싱 불가는 위반이 아니라 도구 오류 -----------------------------------


def test_syntax_error_is_tool_error_not_finding() -> None:
    with pytest.raises(LintomataError) as exc:
        sc.extract_contract("def runNode(args: Args)\n    pass\n", PATH)
    assert PATH in exc.value.message


# --- CONTRACT ------------------------------------------------------------


def test_args_missing() -> None:
    source = "def runNode(args):\n    return returnResult(1)\n"
    assert "LNT-CONTRACT-001" in ids(sc.check_script(source, PATH))


def test_entrypoint_forms() -> None:
    body = "\n    return returnResult(Out())\n"
    header = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "@dataclass\nclass Out:\n    x: int\n\n\n"
    )
    # 인자가 둘이면 형태가 다르다
    two = header + "def runNode(args: Args, extra: int):" + body
    assert "LNT-CONTRACT-002" in ids(sc.check_script(two, PATH))
    # 어노테이션이 `Args` 가 아니면 형태가 다르다
    wrong = header + "def runNode(args: Out):" + body
    assert "LNT-CONTRACT-002" in ids(sc.check_script(wrong, PATH))
    # 이름이 다르면 진입점이 없다
    renamed = header + "def run_node(args: Args):" + body
    assert "LNT-CONTRACT-002" in ids(sc.check_script(renamed, PATH))
    # 제대로 쓰면 안 걸린다
    ok = header + "def runNode(args: Args):" + body
    assert "LNT-CONTRACT-002" not in ids(sc.check_script(ok, PATH))


def test_return_missing() -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "def runNode(args: Args):\n    return args.input\n"
    )
    assert "LNT-CONTRACT-003" in ids(sc.check_script(source, PATH))


def test_args_unknown_field() -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    config: str\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    findings = sc.check_script(source, PATH)
    assert "LNT-CONTRACT-004" in ids(findings)
    message = next(f.message for f in findings if f.rule_id == "LNT-CONTRACT-004")
    assert "config" in message


def test_args_field_omission_is_allowed() -> None:
    """입력이 없는 Prepare — `input` 을 아예 두지 않는다. 위반이 아니다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    url: str\n\n\n"
        "@dataclass\nclass Args:\n    params: Params\n\n\n"
        "@dataclass\nclass Context:\n    handle: str\n\n\n"
        "def runNode(args: Args) -> Context:\n"
        "    return returnResult(Context(handle=args.params.url))\n"
    )
    assert sc.check_script(source, PATH, "prepare") == []


def test_state_reserved_prefix() -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass State:\n    __startedAt: int\n\n\n"
        "@dataclass\nclass Args:\n    state: State\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args)\n"
    )
    assert "LNT-STATE-001" in ids(sc.check_script(source, PATH))


# --- TYPE ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "rule_id"),
    [
        ("dict", "LNT-TYPE-001"),
        ("dict[str, int]", "LNT-TYPE-001"),
        ("Optional[str]", "LNT-TYPE-002"),
        ("str | None", "LNT-TYPE-002"),
        ("set[str]", "LNT-TYPE-003"),
        ("Any", "LNT-TYPE-003"),
    ],
)
def test_type_vocabulary(annotation: str, rule_id: str) -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        f"@dataclass\nclass Args:\n    input: {annotation}\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert rule_id in ids(sc.check_script(source, PATH))


@pytest.mark.parametrize("annotation", ["int", "float", "str", "bool", "bytes", "list[str]"])
def test_primitives_pass(annotation: str) -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        f"@dataclass\nclass Args:\n    input: {annotation}\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert only(sc.check_script(source, PATH), "LNT-TYPE") == []


def test_nested_dataclass_is_registered_and_allowed() -> None:
    """중첩 dataclass 가 `dataclasses` 에 담기고, 리스트 원소로도 통과한다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Button:\n    label: str\n\n\n"
        "@dataclass\nclass Page:\n    buttons: list[Button]\n\n\n"
        "@dataclass\nclass Args:\n    input: Page\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    contract, _ = sc.extract_contract(source, PATH)
    assert set(contract.dataclasses) == {"Button", "Page", "Args"}
    page = contract.dataclasses["Page"]
    assert str(page.fields[0].type) == "list[Button]"
    assert only(sc.check_script(source, PATH), "LNT-TYPE") == []


def test_bad_return_annotation_is_caught() -> None:
    """`runNode` 의 반환 어노테이션도 선언된 타입이다 — 어휘 밖이면 걸린다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "def runNode(args: Args) -> dict:\n    return returnResult(args.input)\n"
    )
    assert "LNT-TYPE-001" in ids(sc.check_script(source, PATH))


def test_type_judgement_is_delegated_not_duplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정의 정본은 `primitives.check_allowed` 하나다 — 표를 복제하면 갈라진다.

    복제본이 되살아나면 이 대역이 안 불려 `dict` 가 그대로 걸리고 여기서 깨진다.
    """
    calls: list[str] = []

    def spy(t: object, **kwargs: object) -> list[Finding]:
        calls.append(str(t))
        return []

    monkeypatch.setattr(sc, "check_allowed", spy)
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: dict\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    contract, _ = sc.extract_contract(source, PATH)
    assert sc.check_types(contract) == []
    assert calls == ["dict"]


@pytest.mark.parametrize("name", sorted(primitives.FORBIDDEN))
def test_every_forbidden_name_is_rejected_through_check_script(name: str) -> None:
    """`primitives.FORBIDDEN` 전부가 스크립트 검사까지 실제로 걸린다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        f"@dataclass\nclass Args:\n    input: {name}\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert only(sc.check_script(source, PATH), "LNT-TYPE") != []


@pytest.mark.parametrize("annotation", ["str | int", "Button[int]"])
def test_union_and_parameterized_dataclass_are_rejected(annotation: str) -> None:
    """어휘 밖 합집합과 **매개변수 붙은 dataclass** — 위임 전 복제본에서 미커버였던 두 분기."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Button:\n    label: str\n\n\n"
        f"@dataclass\nclass Args:\n    input: {annotation}\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert only(sc.check_script(source, PATH), "LNT-TYPE") == ["LNT-TYPE-003"]


# --- BAN — 금지 4종 각각 --------------------------------------------------


def _with_body(body: str, *, state_field: str = "stop") -> str:
    return (
        "from dataclasses import dataclass\n\n\n"
        f"@dataclass\nclass State:\n    {state_field}: str\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    state: State\n\n\n"
        "def runNode(args: Args):\n"
        f"{body}"
        "    return returnResult(args.input)\n"
    )


@pytest.mark.parametrize(
    ("head", "body", "rule_id"),
    [
        ("import time\n", "    now = time.time()\n", "LNT-BAN-001"),
        ("from datetime import datetime\n", "    now = datetime.now()\n", "LNT-BAN-001"),
        ("import random\n", "    x = random.random()\n", "LNT-BAN-002"),
        ("import os\n", "    x = os.urandom(4)\n", "LNT-BAN-002"),
        ("import subprocess\n", "    subprocess.run(['ls'])\n", "LNT-BAN-003"),
        ("import os\n", "    os.system('ls')\n", "LNT-BAN-003"),
        ("", "    exec('1')\n", "LNT-BAN-003"),
    ],
)
def test_bans(head: str, body: str, rule_id: str) -> None:
    source = head + _with_body(body)
    assert rule_id in ids(sc.check_script(source, PATH))


def test_ban_follows_import_alias() -> None:
    """`import os as o` 로 이름을 바꿔도 따라간다 — 사전에 추측 가능한 우회다."""
    source = "import os as o\n" + _with_body("    o.system('ls')\n")
    assert "LNT-BAN-003" in ids(sc.check_script(source, PATH))


def test_undeclared_state_access() -> None:
    source = _with_body("    x = args.state.settled\n")
    findings = sc.check_script(source, PATH)
    assert "LNT-BAN-004" in ids(findings)
    assert "settled" in next(f.message for f in findings if f.rule_id == "LNT-BAN-004")


def test_declared_state_access_passes() -> None:
    assert only(sc.check_script(_with_body("    x = args.state.stop\n"), PATH), "LNT-BAN") == []


def test_engine_state_field_needs_no_declaration() -> None:
    """`__startedAt` 은 엔진이 준다. 사용자는 `__` 를 선언할 수 없으므로(STATE-001)
    선언 없이 읽는 것이 정상이다."""
    source = _with_body("    started = args.state.__startedAt\n")
    assert only(sc.check_script(source, PATH), "LNT-BAN") == []


def test_state_access_uses_actual_param_name() -> None:
    """진입점 인자 이름이 `args` 가 아니어도 따라간다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass State:\n    stop: str\n\n\n"
        "@dataclass\nclass Args:\n    state: State\n\n\n"
        "def runNode(a: Args):\n"
        "    x = a.state.settled\n"
        "    return returnResult(a)\n"
    )
    assert "LNT-BAN-004" in ids(sc.check_script(source, PATH))


def test_file_io_and_network_are_free() -> None:
    """금지 목록에 없는 것은 아무것도 막지 않는다 (`schema.md` 6절)."""
    source = "import os\nimport urllib.request\n" + _with_body(
        "    data = open('/etc/hosts').read()\n    root = os.environ['HOME']\n"
    )
    assert only(sc.check_script(source, PATH), "LNT-BAN") == []


# --- 노드 타입별 형식 요구 -------------------------------------------------


def test_judge_without_params_is_caught() -> None:
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "@dataclass\nclass Verdict:\n    ok: bool\n\n\n"
        "def runNode(args: Args) -> Verdict:\n"
        "    return returnResult(Verdict(ok=args.input == 'expected'))\n"
    )
    assert "LNT-CONTRACT-005" in ids(sc.check_script(source, PATH, "judge"))
    # 노드 타입을 모르면(스크립트 단독 등록) 타입별 요구는 안 돈다
    assert "LNT-CONTRACT-005" not in ids(sc.check_script(source, PATH))
    # 같은 스크립트라도 Extract 라면 요구가 없다
    assert "LNT-CONTRACT-005" not in ids(sc.check_script(source, PATH, "extract"))


def test_judge_with_empty_params_dataclass_is_caught() -> None:
    """`params` 필드만 있고 안이 비면 기댓값을 받을 자리가 없다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    pass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert "LNT-CONTRACT-005" in ids(sc.check_script(source, PATH, "judge"))


def test_judge_without_verdict_field_is_caught() -> None:
    """**등록 시점에 잡는다** (R4-4). 런타임까지 미루면 리포트가 아니라 오류가 난다 —
    `schema.md` 6절이 형식 제한의 목적으로 적어둔 "돌리기 전에 잡아 자기 수정 신호를
    준다" 가 정확히 이 자리다."""
    header = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    expected: int\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
    )
    missing = header + (
        "@dataclass\nclass Verdict:\n    note: str\n\n\n"
        "def runNode(args: Args) -> Verdict:\n"
        "    return returnResult(Verdict(note='x'))\n"
    )
    assert "LNT-CONTRACT-007" in ids(sc.check_script(missing, PATH, "judge"))
    # 노드 타입을 모르면(스크립트 단독 등록) 타입별 요구는 안 돈다
    assert "LNT-CONTRACT-007" not in ids(sc.check_script(missing, PATH))
    # 판정 노드가 아니면 요구가 없다
    assert "LNT-CONTRACT-007" not in ids(sc.check_script(missing, PATH, "extract"))

    ok = header + (
        "@dataclass\nclass Verdict:\n    passed: bool\n    message: str\n\n\n"
        "def runNode(args: Args) -> Verdict:\n"
        "    return returnResult(Verdict(passed=True, message='x'))\n"
    )
    assert sc.check_script(ok, PATH, "judge") == []


def test_verdict_field_must_be_bool() -> None:
    """엔진은 `passed` 를 `bool` 로 읽는다 — 이름만 맞고 타입이 다르면 못 읽는다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    expected: int\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
        "@dataclass\nclass Verdict:\n    passed: str\n\n\n"
        "def runNode(args: Args) -> Verdict:\n"
        "    return returnResult(Verdict(passed='yes'))\n"
    )
    assert "LNT-CONTRACT-007" in ids(sc.check_script(source, PATH, "judge"))


def test_verdict_field_name_matches_the_engine() -> None:
    """규약이 두 벌이면 등록은 통과하는데 실행에서 터진다."""
    from lintomata.engine import runtime

    assert sc.VERDICT_FIELD == runtime.VERDICT_PASSED


def test_non_dataclass_output_defers_to_contract_003() -> None:
    """출력이 dataclass 가 아니면 `-003` 이 이미 원인을 짚었다 — 겹쳐 내지 않는다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    expected: int\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
        "def runNode(args: Args) -> str:\n    return returnResult(args.input)\n"
    )
    found = only(sc.check_script(source, PATH, "judge"), "LNT-CONTRACT")
    assert found == ["LNT-CONTRACT-003"]


def test_act_must_be_transparent() -> None:
    header = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Form:\n    selector: str\n\n\n"
        "@dataclass\nclass Other:\n    selector: str\n\n\n"
        "@dataclass\nclass Args:\n    input: Form\n\n\n"
    )
    differ = header + (
        "def runNode(args: Args) -> Other:\n"
        "    return returnResult(Other(selector=args.input.selector))\n"
    )
    assert "LNT-CONTRACT-006" in ids(sc.check_script(differ, PATH, "act"))

    same = header + "def runNode(args: Args) -> Form:\n    return returnResult(args.input)\n"
    assert sc.check_script(same, PATH, "act") == []


def test_act_without_input_is_caught() -> None:
    """input 이 없으면 `input == output` 이 성립할 수 없다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    params: str\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.params)\n"
    )
    assert "LNT-CONTRACT-006" in ids(sc.check_script(source, PATH, "act"))


PASSTHROUGH = (
    "from dataclasses import dataclass\n\n\n"
    "@dataclass\nclass Form:\n    selector: str\n\n\n"
    "@dataclass\nclass Args:\n    input: Form\n\n\n"
    "def runNode(args: Args):\n"  # ★ 반환 어노테이션이 없다
    "    return returnResult(args.input)\n"
)
"""**통과형** — CLAUDE.md 가 조건 분기의 표준 표현으로 못박은
*"스크립트가 그냥 `input` 을 반환한다"*. Act 의 교과서적 모습이기도 하다."""


def test_passthrough_output_type_comes_from_input() -> None:
    """`returnResult(args.input)` 에서 출력 타입을 못 뽑으면 `output_type` 이 비고
    **교과서적 Act 가 `LNT-CONTRACT-006` 으로 오탐된다.**"""
    contract, _ = sc.extract_contract(PASSTHROUGH, PATH)
    assert (contract.input_type, contract.output_type) == ("Form", "Form")
    assert sc.check_script(PASSTHROUGH, PATH, "act") == []


@pytest.mark.parametrize("node_type", ["prepare", "collect", "extract", "judge", "act"])
def test_passthrough_is_not_an_act_only_concern(node_type: str) -> None:
    """조건 분기의 표준 표현이므로 **모든 노드 타입**에서 성립해야 한다.

    Judge 만 기댓값 자리(`-005`)와 판정 자리(`-007`)를 따로 요구한다 —
    둘 다 통과형과 무관한 요구다.
    """
    findings = only(sc.check_script(PASSTHROUGH, PATH, node_type), "LNT-CONTRACT")
    expected = ["LNT-CONTRACT-005", "LNT-CONTRACT-007"] if node_type == "judge" else []
    assert findings == expected


def test_passthrough_follows_the_actual_param_name() -> None:
    """진입점 인자 이름이 `args` 가 아니어도 따라간다."""
    source = PASSTHROUGH.replace("def runNode(args: Args):", "def runNode(a: Args):").replace(
        "returnResult(args.input)", "returnResult(a.input)"
    )
    contract, _ = sc.extract_contract(source, PATH)
    assert contract.output_type == "Form"


def test_passthrough_of_a_non_input_field_is_not_the_input_type() -> None:
    """`args.params` 는 입력이 아니다 — 통과형으로 오인하면 Act 검사가 무의미해진다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Form:\n    selector: str\n\n\n"
        "@dataclass\nclass Args:\n    input: Form\n    params: Form\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.params)\n"
    )
    contract, _ = sc.extract_contract(source, PATH)
    assert contract.output_type == ""


# --- 출력은 dataclass 여야 한다 (`LNT-CONTRACT-003`) -----------------------


@pytest.mark.parametrize("input_type", ["str", "list[str]"])
def test_primitive_output_is_caught(input_type: str) -> None:
    """`-> str` 같은 primitive 반환은 성립하지 않는다 — 타입 동일성을 **구조로** 판정한다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        f"@dataclass\nclass Args:\n    input: {input_type}\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    assert "LNT-CONTRACT-003" in ids(sc.check_script(source, PATH))


def test_undetermined_output_is_caught() -> None:
    """무엇이 나가는지 못 뽑는 것도 같은 규칙이다 — 고치는 방법이 하나이기 때문이다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Out:\n    ok: bool\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "def runNode(args: Args):\n    return returnResult(build())\n"
    )
    assert "LNT-CONTRACT-003" in ids(sc.check_script(source, PATH))


def test_dataclass_output_passes() -> None:
    """짝 — 제대로 dataclass 를 내보내면 안 걸린다."""
    assert "LNT-CONTRACT-003" not in ids(sc.check_script(GOOD, PATH))


def test_output_type_from_return_result_argument() -> None:
    """반환 어노테이션이 없으면 `returnResult()` 의 인자에서 찾는다."""
    source = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Form:\n    selector: str\n\n\n"
        "@dataclass\nclass Args:\n    input: Form\n\n\n"
        "def runNode(args: Args):\n"
        "    out = Form(selector=args.input.selector)\n"
        "    return returnResult(out)\n"
    )
    contract, _ = sc.extract_contract(source, PATH)
    assert contract.output_type == "Form"
    assert sc.check_script(source, PATH, "act") == []


# --- TOOL — 실행 시점 -----------------------------------------------------


PLAYWRIGHT = "${env.HOME}/.playwright/playwright"
TOOL_DECL = {"playwright": {"path": PLAYWRIGHT, "functions": ["launch"]}}


def _tool_script(call: str) -> str:
    return (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        f"def runNode(args: Args):\n    {call}\n    return returnResult(args.input)\n"
    )


def test_tool_call_declared_passes() -> None:
    contract, _ = sc.extract_contract(_tool_script(f'launch("{PLAYWRIGHT}")'), PATH)
    assert contract.tool_calls == [("launch", PLAYWRIGHT)]
    assert sc.check_tool_calls(contract, TOOL_DECL) == []


def test_tool_executable_undeclared() -> None:
    contract, _ = sc.extract_contract(_tool_script('launch("/usr/bin/whatever")'), PATH)
    assert ids(sc.check_tool_calls(contract, TOOL_DECL)) == ["LNT-TOOL-002"]


def test_tool_function_undeclared() -> None:
    contract, _ = sc.extract_contract(_tool_script(f'run_shell("{PLAYWRIGHT}")'), PATH)
    assert ids(sc.check_tool_calls(contract, TOOL_DECL)) == ["LNT-TOOL-001"]


def test_plain_path_argument_is_not_a_tool_call() -> None:
    """파일 IO 는 자유다 — `open("/etc/hosts")` 를 도구 호출로 오인하면 그걸 막아버린다."""
    contract, _ = sc.extract_contract(_tool_script('open("/etc/hosts")'), PATH)
    assert contract.tool_calls == [("open", "/etc/hosts")]
    assert sc.check_tool_calls(contract, TOOL_DECL) == []


# --- 스크립트마다 `Args` 가 따로 있다 --------------------------------------


def test_two_scripts_each_declare_args_independently() -> None:
    """registry 키가 `(origin, name)` 인 이유 — 두 스크립트의 `Args` 가 안 부딪힌다."""
    collect = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    judge = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Params:\n    expected: int\n\n\n"
        "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
        "def runNode(args: Args):\n    return returnResult(args.input)\n"
    )
    a, _ = sc.extract_contract(collect, "/abs/a.py")
    b, _ = sc.extract_contract(judge, "/abs/b.py")

    assert a.dataclasses["Args"].origin == "/abs/a.py"
    assert b.dataclasses["Args"].origin == "/abs/b.py"
    assert a.params_type == ""
    assert b.params_type == "Params"

    registry = TypeRegistry()
    for spec in list(a.dataclasses.values()) + list(b.dataclasses.values()):
        registry.register(spec)
    registry.normalize()
    assert registry.field_set(a.dataclasses["Args"].key) != registry.field_set(
        b.dataclasses["Args"].key
    )


def test_engine_state_fields_come_from_the_single_source() -> None:
    """정본은 `model` 하나다 — 복제해 두면 엔진 제공 필드가 늘 때 `LNT-BAN-004` 오탐이 난다."""
    assert sc.ENGINE_STATE_FIELDS is model.ENGINE_STATE_FIELDS
    assert refs._ENGINE_STATE_FIELDS is model.ENGINE_STATE_FIELDS
    assert set(state.ENGINE_FIELDS) == set(model.ENGINE_STATE_FIELDS)


def test_a_new_engine_state_field_needs_no_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정본에 필드가 하나 늘면 스크립트 검사도 **곧바로** 따라온다."""
    grown = frozenset(model.ENGINE_STATE_FIELDS | {"__attempt"})
    monkeypatch.setattr(sc, "ENGINE_STATE_FIELDS", grown)
    source = _with_body("    n = args.state.__attempt\n")
    assert only(sc.check_script(source, PATH), "LNT-BAN") == []


def test_extract_contract_never_reports_check_script_does() -> None:
    """`extract_contract` 의 두 번째 반환값은 언제나 빈 목록이다 — 검증은 `check_script` 다.

    이걸 통과로 오해하면 위반을 통째로 놓친다.
    """
    broken = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Args:\n    input: dict\n    junk: str\n\n\n"
        "def run_node(args):\n    return args.input\n"
    )
    contract, findings = sc.extract_contract(broken, PATH)
    assert findings == []
    assert contract.output_type == ""
    assert ids(sc.check_script(broken, PATH)) != []


def test_registered_specs_carry_origin() -> None:
    contract, _ = sc.extract_contract(GOOD, PATH)
    assert all(spec.origin == PATH for spec in contract.dataclasses.values())
    assert isinstance(contract.dataclasses["Args"], DataclassSpec)


# --- ★ 모든 오류 경로의 rule_id 와 슬롯 -----------------------------------


ALL_RULES = (
    "LNT-CONTRACT-001",
    "LNT-CONTRACT-002",
    "LNT-CONTRACT-003",
    "LNT-CONTRACT-004",
    "LNT-CONTRACT-005",
    "LNT-CONTRACT-006",
    "LNT-CONTRACT-007",
    "LNT-TYPE-001",
    "LNT-TYPE-002",
    "LNT-TYPE-003",
    "LNT-STATE-001",
    "LNT-BAN-001",
    "LNT-BAN-002",
    "LNT-BAN-003",
    "LNT-BAN-004",
    "LNT-TOOL-001",
    "LNT-TOOL-002",
)
"""이 모듈이 낼 수 있는 규칙 전부. 하나라도 슬롯이 비면 `finding()` 이
`LintomataError` 를 내면서 **규칙 id 가 통째로 사라진다** — 그걸 여기서 막는다."""


def _every_finding() -> list[Finding]:
    """모든 오류 경로를 실제로 태운다."""
    collected: list[Finding] = []
    collected.extend(sc.check_script("def runNode(a, b):\n    pass\n", PATH))  # 001·002·003
    collected.extend(
        sc.check_script(
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\nclass State:\n    __startedAt: int\n\n\n"
            "@dataclass\nclass Args:\n"
            "    input: dict\n    params: Optional[str]\n    state: State\n    extra: set[str]\n\n\n"
            "def runNode(args: Args):\n    return returnResult(args)\n",
            PATH,
        )
    )  # 004·TYPE-001/002/003·STATE-001
    collected.extend(sc.check_script(GOOD.replace("input: Html", "input: str"), PATH, "act"))
    collected.extend(
        sc.check_script(
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\nclass Args:\n    input: str\n\n\n"
            "def runNode(args: Args):\n    return returnResult(args.input)\n",
            PATH,
            "judge",
        )
    )  # 005
    collected.extend(
        sc.check_script(
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\nclass Params:\n    expected: int\n\n\n"
            "@dataclass\nclass Args:\n    input: str\n    params: Params\n\n\n"
            "@dataclass\nclass Verdict:\n    note: str\n\n\n"
            "def runNode(args: Args) -> Verdict:\n"
            "    return returnResult(Verdict(note='판정을 안 담았다'))\n",
            PATH,
            "judge",
        )
    )  # 007
    collected.extend(
        sc.check_script(
            "import time\nimport random\nimport subprocess\n" + _with_body("    x = args.state.no\n"),
            PATH,
        )
    )  # BAN 4종
    for source in (f'run_shell("{PLAYWRIGHT}")', 'launch("/usr/bin/whatever")'):
        contract, _ = sc.extract_contract(_tool_script(source), PATH)
        collected.extend(sc.check_tool_calls(contract, TOOL_DECL))
    return collected


def test_every_rule_path_is_reachable_and_keeps_its_id() -> None:
    produced = {f.rule_id for f in _every_finding()}
    assert produced == set(ALL_RULES)


def test_every_message_has_no_leftover_slot() -> None:
    """슬롯을 안 채운 채 나가면 리포트에 `{file}` 이 그대로 샌다 — 그건 검사기 버그다."""
    leftover = re.compile(r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_]*\}")
    for finding in _every_finding():
        assert not leftover.search(finding.message), (finding.rule_id, finding.message)


def test_findings_carry_location_and_guide() -> None:
    for finding in _every_finding():
        assert finding.status == "error"
        assert finding.path == PATH
        assert rules.get_rule(finding.rule_id).guide.split("{")[0][:12] in finding.message


# ── 라이브러리 슬롯 — 능력 선언 (`schema.md` 6.5절) ──────────────────────────


LIBRARY_USER = """
from dataclasses import dataclass

from lintomata_lib import buttons, menus

@dataclass
class Meaning:
    count: int

@dataclass
class Args:
    input: Meaning

def runNode(args: Args) -> Meaning:
    return returnResult(Meaning(count=buttons.count(menus.of(args.input))))
"""


def test_슬롯은_from_import_한_이름이다() -> None:
    contract, _ = sc.extract_contract(LIBRARY_USER, PATH)
    assert contract.library_slots == ("buttons", "menus")


def test_라이브러리를_안_쓰면_슬롯이_비어_있다() -> None:
    contract, _ = sc.extract_contract(GOOD, PATH)
    assert contract.library_slots == ()


def test_별칭은_가져오는_이름이_슬롯이다() -> None:
    """슬롯은 배선의 이름이고 지역 별칭은 그것과 무관하다."""
    source = "from lintomata_lib import buttons as b\n"
    contract, _ = sc.extract_contract(source, PATH)
    assert contract.library_slots == ("buttons",)
    assert sc.check_library_imports(source, PATH) == []


@pytest.mark.parametrize(
    "source",
    [
        "import lintomata_lib\n",
        "from lintomata_lib.buttons import find\n",
        "from lintomata_lib import *\n",
        "def runNode(args):\n    from lintomata_lib import buttons\n",
    ],
    ids=["모듈-import", "서브모듈", "별표", "함수-안"],
)
def test_슬롯을_못_뽑는_형태는_STR_LIB_005(source: str) -> None:
    """정적으로 슬롯을 못 뽑으면 배선 검사가 무의미해진다."""
    findings = sc.check_library_imports(source, PATH)
    assert [item.rule_id for item in findings] == ["LNT-LIB-005"]
    contract, _ = sc.extract_contract(source, PATH)
    assert contract.library_slots == ()


def test_올바른_형태는_아무_결과도_내지_않는다() -> None:
    assert sc.check_library_imports(LIBRARY_USER, PATH) == []
