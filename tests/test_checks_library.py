"""`checks/library.py` — 라이브러리 정적 검사 (`schema.md` 6.5절).

짚는 것:
  - **금지 패턴이 스크립트와 똑같이 걸린다** — 안 걸리면 라이브러리가 우회로가 된다
  - 노드 계약(`runNode`/`Args`/출력 타입)은 **묻지 않는다** — 노드가 아니다
  - 라이브러리 중첩 금지 (`STR-LIB-003`) / `dataclass` 금지 (`STR-LIB-004`)
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from strictler.checks import library as lib
from strictler.errors import StrictlerError
from strictler.model import Node
from strictler.store.entries import Store

PATH = "/abs/libraries/buttons.py"

GOOD = """
    \"\"\"버튼 판정 — 프로젝트의 도메인 지식이 사는 자리.\"\"\"

    def is_button(tag, attrs):
        return tag == "button" or attrs.get("role") == "button"

    def normalize(text):
        return " ".join(text.split())
"""


def check(body: str) -> list[str]:
    findings = lib.check_library(dedent(body).lstrip("\n"), PATH)
    return [item.rule_id for item in findings]


def test_함수만_있는_라이브러리는_통과한다() -> None:
    assert check(GOOD) == []


def test_노드_계약을_묻지_않는다() -> None:
    """`runNode` 도 `Args` 도 출력 타입도 없다 — 그래도 통과다. **노드가 아니다.**"""
    assert "STR-CONTRACT-001" not in check(GOOD)
    assert "STR-CONTRACT-002" not in check(GOOD)
    assert "STR-CONTRACT-003" not in check(GOOD)


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        ("import time\n\ndef now():\n    return time.time()\n", "STR-BAN-001"),
        ("import random\n\ndef pick(xs):\n    return random.choice(xs)\n", "STR-BAN-002"),
        ("import subprocess\n\ndef go():\n    subprocess.run(['ls'])\n", "STR-BAN-003"),
        ("import os\n\ndef go():\n    os.system('ls')\n", "STR-BAN-003"),
    ],
    ids=["시간", "랜덤", "subprocess", "os.system"],
)
def test_금지_패턴은_스크립트와_똑같이_걸린다(body: str, rule: str) -> None:
    """**여기를 안 걸면 라이브러리에서 `import time` 을 해 금지가 통째로 우회된다.**"""
    assert rule in check(body)


def test_state_참조는_판정하지_않는다() -> None:
    """라이브러리에는 선언된 state 가 없다 — 근거 없이 `STR-BAN-004` 를 내지 않는다."""
    body = """
        def read(args):
            return args.state.ready
    """
    assert check(body) == []


@pytest.mark.parametrize(
    "line",
    [
        "from strictler_lib import other",
        "import strictler_lib",
        "from strictler_lib.other import helper",
    ],
    ids=["from-import", "import", "서브모듈"],
)
def test_라이브러리는_다른_라이브러리를_import_할_수_없다(line: str) -> None:
    """**한 층만.** 허용하면 그때부터 패키지 매니저를 만들게 된다."""
    assert check(f"{line}\n\ndef go():\n    return 1\n") == ["STR-LIB-003"]


def test_dataclass_선언은_v1_에서_막는다() -> None:
    """타입 레지스트리는 스크립트 파일 하나만 파싱한다 — 밖에서 생기면 구멍이 난다."""
    body = """
        from dataclasses import dataclass

        @dataclass
        class Button:
            label: str
    """
    findings = lib.check_library(dedent(body).lstrip("\n"), PATH)
    assert [item.rule_id for item in findings] == ["STR-LIB-004"]
    assert "Button" in findings[0].message


def test_dataclass_변형_데코레이터도_같은_판정을_받는다() -> None:
    """`@dataclass(frozen=True)` / `@dataclasses.dataclass` — 판정은 한 곳에서 한다."""
    body = """
        import dataclasses
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class A:
            x: int

        @dataclasses.dataclass
        class B:
            y: int
    """
    assert check(body) == ["STR-LIB-004", "STR-LIB-004"]


def test_실패를_최대한_모은다() -> None:
    """하나 걸렸다고 나머지를 멈추지 않는다."""
    body = """
        import time
        from strictler_lib import other
        from dataclasses import dataclass

        @dataclass
        class A:
            x: int
    """
    assert set(check(body)) == {"STR-BAN-001", "STR-LIB-003", "STR-LIB-004"}


def test_문법_오류는_위반이_아니라_오류다() -> None:
    """검사기가 못 돈 것이지 규칙 위반이 아니다."""
    with pytest.raises(StrictlerError):
        lib.check_library("def go(:\n", PATH)


def test_PEP723_헤더도_스크립트와_같이_본다() -> None:
    """라이브러리도 **같은 환경에 로드된다** — 의존성 모델이 같다."""
    body = """
        # /// script
        # dependencies = ["no-such-package-anywhere"]
        # ///

        def go():
            return 1
    """
    assert check(body) == ["STR-DEP-001"]


# ── 배선 — 선언(스크립트) / 사용(노드) 대조 ─────────────────────────────────



def node_of(script: str, libraries: dict[str, str]) -> Node:
    return Node.model_validate(
        {
            "info": {"name": "detect", "description": "설명"},
            "type": "perceive",
            "script": script,
            "libraries": libraries,
        }
    )


class FakeContract:
    def __init__(self, slots: tuple[str, ...]) -> None:
        self.library_slots = slots


def wiring(slots: tuple[str, ...], libraries: dict[str, str]) -> list[str]:
    findings = lib.check_wiring(
        node_of("/abs/s.py", libraries), FakeContract(slots), path="n.json"  # type: ignore[arg-type]
    )
    return [item.rule_id for item in findings]


def test_슬롯과_배선이_맞으면_통과다() -> None:
    assert wiring(("buttons",), {"buttons": "/abs/b.py"}) == []


def test_배선이_빠지면_STR_LIB_001() -> None:
    assert wiring(("buttons", "menus"), {"buttons": "/abs/b.py"}) == ["STR-LIB-001"]


def test_안_쓰는_배선은_STR_LIB_002() -> None:
    assert wiring((), {"buttons": "/abs/b.py"}) == ["STR-LIB-002"]


def test_빠진_것과_남는_것은_따로_보고된다() -> None:
    """고치는 법이 다르다 — 하나는 넣고 하나는 뺀다."""
    assert wiring(("menus",), {"buttons": "/abs/b.py"}) == ["STR-LIB-001", "STR-LIB-002"]


def test_resolve_는_절대경로를_그대로_푼다(tmp_path: Path) -> None:
    library = tmp_path / "buttons.py"
    library.write_text("def go():\n    return 1\n", encoding="utf-8")

    resolved, findings = lib.resolve_libraries(
        node_of("/abs/s.py", {"buttons": str(library)}),
        store=Store(tmp_path / "home"),
        env={},
    )
    assert findings == []
    assert resolved == {"buttons": library}


def test_resolve_는_없는_파일을_STR_REF_001_로_짚는다(tmp_path: Path) -> None:
    _, findings = lib.resolve_libraries(
        node_of("/abs/s.py", {"buttons": str(tmp_path / "없다.py")}),
        store=Store(tmp_path / "home"),
        env={},
    )
    assert [item.rule_id for item in findings] == ["STR-REF-001"]


def test_resolve_는_라이브러리가_아닌_참조를_STR_REG_003_으로_짚는다(tmp_path: Path) -> None:
    """**새 규칙을 파지 않았다** — 자리와 접두가 안 맞는 것은 이미 그 규칙의 자리다."""
    _, findings = lib.resolve_libraries(
        node_of("/abs/s.py", {"buttons": "${ref.sc_12345678}"}),
        store=Store(tmp_path / "home"),
        env={},
    )
    assert [item.rule_id for item in findings] == ["STR-REG-003"]


def test_resolve_는_없는_id_를_STR_REG_002_로_짚는다(tmp_path: Path) -> None:
    _, findings = lib.resolve_libraries(
        node_of("/abs/s.py", {"buttons": "${ref.lb_12345678}"}),
        store=Store(tmp_path / "home"),
        env={},
    )
    assert [item.rule_id for item in findings] == ["STR-REG-002"]


def test_resolve_는_상대경로를_STR_PATH_001_로_짚는다(tmp_path: Path) -> None:
    _, findings = lib.resolve_libraries(
        node_of("/abs/s.py", {"buttons": "./buttons.py"}),
        store=Store(tmp_path / "home"),
        env={},
    )
    assert [item.rule_id for item in findings] == ["STR-PATH-001"]
