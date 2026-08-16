"""Step 3-a — 스크립트 로드·실행과 경계 검증 (`engine/exec.py`).

**샌드박싱을 하지 않는다** — 실제 파일을 실제로 로드해 돌린다.
여기서 나가는 실패는 전부 **오류**다. 위반이 아니다.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from strictler.checks.script import extract_contract
from strictler.engine import exec as node_exec
from strictler.errors import StrictlerError
from strictler.typesys.registry import TypeRegistry

VANTAGE = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Params:
        url: str

    @dataclass
    class Args:
        params: Params

    def runNode(args: Args) -> Scene:
        return returnResult(Scene(url=args.params.url))
"""

NESTED = """
    from dataclasses import dataclass

    @dataclass
    class Button:
        label: str

    @dataclass
    class Screen:
        buttons: list[Button]
        title: str

    @dataclass
    class Count:
        count: int

    @dataclass
    class St:
        ready: bool

    @dataclass
    class Args:
        input: Screen
        state: St

    def runNode(args: Args) -> Count:
        return returnResult(Count(count=len(args.input.buttons) if args.state.ready else 0))
"""

BOOM_AT_IMPORT = """
    raise RuntimeError("import 시점에 터진다")
"""

BOOM_AT_RUN = """
    from dataclasses import dataclass

    @dataclass
    class Out:
        n: int

    @dataclass
    class Args:
        params: Out

    def runNode(args: Args) -> Out:
        if args.params.n:
            raise ValueError("돌다가 터진다")
        return returnResult(Out(n=0))
"""


def script(tmp_path: Path, name: str, body: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{name}.py"
    path.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def loaded(tmp_path: Path, name: str, body: str):
    path = script(tmp_path, name, body)
    contract, _ = extract_contract(path.read_text(encoding="utf-8"), str(path))
    return node_exec.load_script(path), contract


def registry_for(*contracts) -> TypeRegistry:
    registry = TypeRegistry()
    for contract in contracts:
        for spec in contract.dataclasses.values():
            registry.register(spec)
    registry.normalize()
    return registry


# ── 로드 ─────────────────────────────────────────────────────────────────────


def test_returnResult_는_엔진이_넣어_준다(tmp_path: Path) -> None:
    """스크립트 어디에도 정의가 없는 고정 이름이다 — 안 넣어 주면 전부 `NameError`."""
    module, _ = loaded(tmp_path, "v", VANTAGE)
    assert module.returnResult("그대로") == "그대로"


def test_같은_이름의_스크립트가_충돌하지_않는다(tmp_path: Path) -> None:
    one = script(tmp_path / "a", "same", VANTAGE)
    two = script(tmp_path / "b", "same", NESTED)
    assert node_exec.load_script(one) is not node_exec.load_script(two)


def test_로드_중_예외는_오류다(tmp_path: Path) -> None:
    with pytest.raises(StrictlerError) as caught:
        node_exec.load_script(script(tmp_path, "boom", BOOM_AT_IMPORT))
    assert "import 시점에 터진다" in caught.value.message


def test_없는_파일은_오류다(tmp_path: Path) -> None:
    with pytest.raises((StrictlerError, FileNotFoundError)):
        node_exec.load_script(tmp_path / "없다.py")


# ── Args 조립 ────────────────────────────────────────────────────────────────


def test_선언에_없는_필드는_채우지_않는다(tmp_path: Path) -> None:
    """입력이 없는 Vantage 는 `input` 필드를 아예 두지 않는다."""
    module, contract = loaded(tmp_path, "v", VANTAGE)
    args = node_exec.build_args(module, contract, params={"url": "https://x"})

    assert args.params.url == "https://x"
    assert not hasattr(args, "input")
    assert not hasattr(args, "state")


def test_중첩_dataclass_와_리스트를_옮긴다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    args = node_exec.build_args(
        module,
        contract,
        input_value={"buttons": [{"label": "확인"}, {"label": "취소"}], "title": "t"},
        state={"ready": True, "__startedAt": 1},
    )

    assert [b.label for b in args.input.buttons] == ["확인", "취소"]
    assert isinstance(args.input.buttons[0], module.Button)
    # `__startedAt` 은 스크립트가 선언할 수 없으므로 `Args.state` 에 들어가지 않는다.
    assert args.state.ready is True
    assert not hasattr(args.state, "__startedAt")


def test_앞단_노드의_출력을_그대로_받는다(tmp_path: Path) -> None:
    """서로 다른 스크립트의 dataclass 라도 구조가 같으면 옮겨진다."""
    producer, producer_contract = loaded(tmp_path, "v", VANTAGE)
    made = node_exec.invoke(
        producer, node_exec.build_args(producer, producer_contract, params={"url": "abcd"})
    )

    consumer_body = VANTAGE.replace(
        "class Args:\n        params: Params", "class Args:\n        input: Scene"
    ).replace("args.params.url", "args.input.url")
    consumer, consumer_contract = loaded(tmp_path, "c", consumer_body)
    args = node_exec.build_args(consumer, consumer_contract, input_value=made)

    assert args.input.url == "abcd"
    assert isinstance(args.input, consumer.Scene)


def test_input_을_선언했는데_앞단이_없으면_오류다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    with pytest.raises(StrictlerError) as caught:
        node_exec.build_args(module, contract, state={"ready": True})
    assert "Args.input" in caught.value.message


def test_필드가_모자라면_오류다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    with pytest.raises(StrictlerError) as caught:
        node_exec.build_args(
            module, contract, input_value={"buttons": []}, state={"ready": True}
        )
    assert "title" in caught.value.message


def test_리스트_자리에_리스트가_아닌_값이_오면_오류다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    with pytest.raises(StrictlerError):
        node_exec.build_args(
            module,
            contract,
            input_value={"buttons": "둘", "title": "t"},
            state={"ready": True},
        )


def test_as_mapping_은_dataclass_가_아닌_값을_거부한다() -> None:
    with pytest.raises(StrictlerError) as caught:
        node_exec.as_mapping(3)
    assert "dataclass" in caught.value.message


# ── 실행 ─────────────────────────────────────────────────────────────────────


def test_invoke_는_returnResult_값을_준다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "v", VANTAGE)
    args = node_exec.build_args(module, contract, params={"url": "https://x"})
    assert node_exec.invoke(module, args).url == "https://x"


def test_스크립트_예외는_위반이_아니라_오류다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "b", BOOM_AT_RUN)
    args = node_exec.build_args(module, contract, params={"n": 1})

    with pytest.raises(StrictlerError) as caught:
        node_exec.invoke(module, args)
    assert "돌다가 터진다" in caught.value.message
    assert "오류" in caught.value.message


def test_진입점이_없으면_오류다(tmp_path: Path) -> None:
    module = node_exec.load_script(script(tmp_path, "e", "x = 1\n"))
    with pytest.raises(StrictlerError) as caught:
        node_exec.invoke(module, None)
    assert node_exec.ENTRYPOINT in caught.value.message


# ── 경계 검증 ────────────────────────────────────────────────────────────────


def test_선언과_맞는_값은_통과한다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    registry = registry_for(contract)
    value = {"buttons": [{"label": "확인"}], "title": "t"}

    assert node_exec.validate_input(contract, value, registry, path="p", node="n") == []


def test_선언과_다른_값은_오류다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    registry = registry_for(contract)

    findings = node_exec.validate_input(
        contract, {"buttons": [{"label": 3}], "title": "t"}, registry, path="p", node="n"
    )
    assert [f.status for f in findings] == ["error"]
    assert findings[0].node == "n"
    assert "Screen" in findings[0].message


def test_출력_검증도_같은_자리다(tmp_path: Path) -> None:
    module, contract = loaded(tmp_path, "n", NESTED)
    registry = registry_for(contract)

    assert node_exec.validate_output(
        contract, module.Count(count=1), registry, path="p", node="n"
    ) == []
    findings = node_exec.validate_output(
        contract, {"count": "하나"}, registry, path="p", node="n"
    )
    assert [f.status for f in findings] == ["error"]


def test_선언이_없으면_볼_것이_없다(tmp_path: Path) -> None:
    """입력을 안 받는 Vantage 의 `Args.input` 은 아예 없다."""
    module, contract = loaded(tmp_path, "v", VANTAGE)
    registry = registry_for(contract)

    assert node_exec.validate_input(contract, None, registry, path="p", node="v") == []


# ── 라이브러리 주입 (`schema.md` 6.5절) ──────────────────────────────────────


LIBRARY = """
    def measure(text):
        return len(text)
"""

USES_LIBRARY = """
    from strictler_lib import shared

    LENGTH = shared.measure("abcd")

    def runNode(args):
        return returnResult(shared.measure("xy"))
"""


def test_배선된_라이브러리는_로드_시점에_이미_있다(tmp_path: Path) -> None:
    """`from strictler_lib import shared` 는 **모듈 최상단**에서 풀린다 —
    주입이 `exec_module` 보다 늦으면 그 자리에서 `ImportError` 다."""
    library = script(tmp_path, "shared", LIBRARY)
    module = node_exec.load_script(
        script(tmp_path, "user", USES_LIBRARY), {"shared": library}
    )
    assert module.LENGTH == 4
    assert node_exec.invoke(module, None) == 2


def test_배선이_없으면_그냥_ImportError_다(tmp_path: Path) -> None:
    """**틀린 값보다 오류가 낫다.** 안내는 배선을 넣으라고 말한다."""
    with pytest.raises(StrictlerError) as caught:
        node_exec.load_script(script(tmp_path, "user", USES_LIBRARY))
    assert "libraries" in caught.value.message


def test_로드가_끝나면_네임스페이스를_걷는다(tmp_path: Path) -> None:
    """`sys.modules` 는 프로세스 전역이다 — 남겨두면 **다음 노드가 남의 배선을 본다.**"""
    import sys

    library = script(tmp_path, "shared", LIBRARY)
    node_exec.load_script(script(tmp_path, "user", USES_LIBRARY), {"shared": library})

    assert "strictler_lib" not in sys.modules
    assert "strictler_lib.shared" not in sys.modules


def test_라이브러리_모듈은_경로로_구분된다(tmp_path: Path) -> None:
    """같은 파일명이라도 다른 경로면 다른 모듈이다 — 스크립트와 같은 규칙."""
    one = script(tmp_path / "a", "shared", LIBRARY)
    two = script(tmp_path / "b", "shared", "def measure(text):\n    return 0\n")

    first = node_exec.load_script(script(tmp_path, "u1", USES_LIBRARY), {"shared": one})
    second = node_exec.load_script(script(tmp_path, "u2", USES_LIBRARY), {"shared": two})
    assert (first.LENGTH, second.LENGTH) == (4, 0)


def test_라이브러리_로드_중_예외는_오류다(tmp_path: Path) -> None:
    boom = script(tmp_path, "boom", "raise RuntimeError('여기서 터진다')\n")
    with pytest.raises(StrictlerError) as caught:
        node_exec.load_script(script(tmp_path, "user", USES_LIBRARY), {"shared": boom})
    assert "라이브러리" in caught.value.message
