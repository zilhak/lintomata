"""`deps.py` — PEP 723 의존성 선언 확인 (`STR-DEP-001/002/003`).

**격리를 만들지 않는다**(`schema.md` 6절). 여기서 검증하는 것은 *"선언을 읽어
지금 환경에 있는지 확인하고 설치 명령을 안내한다"* 하나뿐이다.

★ 규칙 셋을 나눈 기준이 **고치는 방법**이므로, 셋이 서로 다른 상황에서 나오는지를
짝으로 둔다. 메시지에 **설치 명령이 들어 있는지**도 단언한다 — 그 문구가 곧 AI
자기 수정 루프의 성능이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strictler import deps
from strictler.checks import script as sc
from strictler.errors import Finding

PATH = "/abs/scripts/node.py"


def ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


def header(*lines: str) -> str:
    """PEP 723 블록 하나를 만든다."""
    body = "\n".join(f"# {line}" if line else "#" for line in lines)
    return f"# /// script\n{body}\n# ///\n"


# 헤더가 있는 스크립트 — 선언한 패키지가 실제로 깔려 있는 경우 (pydantic 은 본체 의존성).
WITH_HEADER = header('requires-python = ">=3.11"', 'dependencies = ["pydantic>=2"]') + '''
from dataclasses import dataclass

import pydantic


@dataclass
class Html:
    text: str


@dataclass
class Args:
    input: Html


@dataclass
class Percept:
    count: int


def runNode(args: Args) -> Percept:
    return returnResult(Percept(count=len(args.input.text)))
'''

NO_HEADER = WITH_HEADER.split("# ///\n", 1)[1]


# --- 헤더 읽기 -------------------------------------------------------------


def test_no_header_is_normal() -> None:
    """**헤더가 없는 것이 정상이다** — stdlib 만 쓰는 스크립트가 대부분이다."""
    declared, findings = deps.read_header(NO_HEADER, PATH)
    assert findings == []
    assert declared.present is False
    assert declared.dependencies == ()
    assert deps.check_dependencies(NO_HEADER, PATH) == []


def test_header_is_read() -> None:
    declared, findings = deps.read_header(WITH_HEADER, PATH)
    assert findings == []
    assert declared.present is True
    assert declared.requires_python == ">=3.11"
    assert declared.dependencies == ("pydantic>=2",)


def test_declared_package_present_passes() -> None:
    assert deps.check_dependencies(WITH_HEADER, PATH) == []


def test_other_block_types_are_not_ours() -> None:
    """PEP 723 는 블록 종류를 이름으로 가른다 — `script` 가 아닌 것은 우리 것이 아니다."""
    source = "# /// pyproject\n# [tool.x]\n# y = 1\n# ///\n" + NO_HEADER
    declared, findings = deps.read_header(source, PATH)
    assert findings == []
    assert declared.present is False


def test_marker_not_for_this_environment_is_skipped() -> None:
    """지금 이 환경에서 안 쓰일 요구까지 강제하면 리눅스 전용 의존성을 적은
    스크립트가 맥에서 등록조차 안 된다."""
    source = header(
        'dependencies = ["definitely-not-installed-xyz; sys_platform == \\"nonesuch\\""]'
    ) + NO_HEADER
    assert deps.check_dependencies(source, PATH) == []


# --- STR-DEP-001 — 선언한 패키지가 없다 ------------------------------------


def test_missing_package() -> None:
    source = header('dependencies = ["definitely-not-installed-xyz"]') + NO_HEADER
    findings = deps.check_dependencies(source, PATH)
    assert ids(findings) == ["STR-DEP-001"]
    assert "definitely-not-installed-xyz" in findings[0].message
    # 설치 명령이 곧 자기 수정 신호다.
    assert (
        "uv tool install strictler --with 'definitely-not-installed-xyz'"
        in findings[0].message
    )
    assert findings[0].status == "error"


def test_all_missing_packages_are_collected() -> None:
    """실패는 최대한 수집한다 — 하나 걸렸다고 나머지를 멈추지 않는다."""
    source = header(
        'dependencies = ["definitely-not-installed-xyz", "also-not-installed-zzz"]'
    ) + NO_HEADER
    findings = deps.check_dependencies(source, PATH)
    assert ids(findings) == ["STR-DEP-001", "STR-DEP-001"]


# --- STR-DEP-002 — 헤더 형식이 잘못됐다 ------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        pytest.param("# /// script\n# dependencies = [\n# ///\n", id="broken-toml"),
        pytest.param('# /// script\n# dependencies = "pydantic"\n# ///\n', id="not-a-list"),
        pytest.param("# /// script\n# dependencies = [1, 2]\n# ///\n", id="not-strings"),
        pytest.param(
            '# /// script\n# requires-python = 311\n# ///\n', id="requires-python-not-str"
        ),
        pytest.param(
            '# /// script\n# dependencies = ["=="]\n# ///\n', id="not-pep508"
        ),
        pytest.param(
            "# /// script\n# dependencies = []\n# ///\n"
            "# /// script\n# dependencies = []\n# ///\n",
            id="two-blocks",
        ),
    ],
)
def test_malformed_header(block: str) -> None:
    findings = deps.check_dependencies(block + NO_HEADER, PATH)
    assert ids(findings) == ["STR-DEP-002"]
    assert "# /// script" in findings[0].message  # 올바른 형식을 보여준다


def test_malformed_header_stops_dependency_checks() -> None:
    """읽히지 않은 헤더에서 의존성을 억지로 뽑으면 그 다음 규칙이 헛것을 검사한다."""
    source = (
        '# /// script\n# dependencies = ["definitely-not-installed-xyz"\n# ///\n'
        + NO_HEADER
    )
    assert ids(deps.check_dependencies(source, PATH)) == ["STR-DEP-002"]


# --- STR-DEP-003 — 설치돼 있는데 버전이 안 맞는다 ---------------------------


def test_version_unsatisfied() -> None:
    source = header('dependencies = ["pydantic<1"]') + NO_HEADER
    findings = deps.check_dependencies(source, PATH)
    assert ids(findings) == ["STR-DEP-003"]
    assert "pydantic<1" in findings[0].message
    assert "uv tool install strictler --with 'pydantic<1'" in findings[0].message


def test_name_normalization_pep503() -> None:
    """`My_Pkg == my-pkg` — 정규화가 없으면 깔려 있는 것도 없다고 나온다."""
    source = header('dependencies = ["PyDantic"]') + NO_HEADER
    assert deps.check_dependencies(source, PATH) == []


# --- 검사 배선 -------------------------------------------------------------


def test_check_script_runs_dependency_check() -> None:
    """등록 시점의 정본은 `check_script` 다 — 여기 안 걸리면 등록소에 그냥 들어간다."""
    source = header('dependencies = ["definitely-not-installed-xyz"]') + NO_HEADER
    assert "STR-DEP-001" in ids(sc.check_script(source, PATH))
    assert sc.check_script(WITH_HEADER, PATH) == []


# --- 실행 시점 안내 ---------------------------------------------------------


def test_missing_module_hint() -> None:
    source = header('dependencies = ["selectolax>=0.3"]') + NO_HEADER
    hint = deps.missing_module_hint(source, "selectolax")
    assert "uv tool install strictler --with 'selectolax>=0.3'" in hint


def test_missing_module_hint_only_for_declared() -> None:
    """선언에 없으면 추측하지 않는다 — 엉뚱한 패키지 이름을 안내하게 된다."""
    assert deps.missing_module_hint(NO_HEADER, "selectolax") == ""
    source = header('dependencies = ["pydantic>=2"]') + NO_HEADER
    assert deps.missing_module_hint(source, "selectolax") == ""


def test_load_script_appends_install_command(tmp_path: Path) -> None:
    """실행 시점 `ModuleNotFoundError` 에 설치 명령이 붙는다 (예외 텍스트만 나가지 않는다)."""
    from strictler.engine import exec as engine_exec
    from strictler.errors import StrictlerError

    path = tmp_path / "node.py"
    path.write_text(
        header('dependencies = ["definitely-not-installed-xyz"]')
        + "import definitely_not_installed_xyz\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictlerError) as exc:
        engine_exec.load_script(path)
    assert (
        "uv tool install strictler --with 'definitely-not-installed-xyz'"
        in exc.value.message
    )


def test_load_script_without_header_still_explains_module_not_found(
    tmp_path: Path,
) -> None:
    """헤더가 없어도 **모듈을 못 찾은 것**은 부작용 문제가 아니다 — 따로 안내한다."""
    from strictler.engine import exec as engine_exec
    from strictler.errors import StrictlerError

    path = tmp_path / "node.py"
    path.write_text("import definitely_not_installed_xyz\n", encoding="utf-8")
    with pytest.raises(StrictlerError) as exc:
        engine_exec.load_script(path)
    message = exc.value.message
    assert "definitely_not_installed_xyz" in message
    # 선언에 없으므로 요구 원문을 짚는 PEP 723 안내는 붙지 않는다.
    assert "uv tool install strictler --with 'definitely" not in message
    # 대신 구조를 바꾸라는 안내가 나온다.
    assert "형제 파일 import 는 되지 않습니다" in message
    assert "부작용" not in message


def test_sibling_file_import_fails_with_structural_guide(tmp_path: Path) -> None:
    """★ conductor 실측: **옆에 있어도 형제 파일은 import 되지 않는다.**

    스크립트 디렉터리는 `sys.path` 에 없고, 등록하면 스크립트 파일 하나만 복사되므로
    옆 파일은 따라오지 않는다. 안내는 경로를 고치라고 하지 않고 **구조를 바꾸라고** 한다.
    """
    from strictler.engine import exec as engine_exec
    from strictler.errors import StrictlerError

    (tmp_path / "button_lib.py").write_text("def is_button(x):\n    return True\n", encoding="utf-8")
    path = tmp_path / "node.py"
    path.write_text("from button_lib import is_button\n", encoding="utf-8")

    with pytest.raises(StrictlerError) as exc:
        engine_exec.load_script(path)
    message = exc.value.message
    assert "button_lib" in message
    assert "형제 파일 import 는 되지 않습니다" in message
    assert "노드를 재사용" in message
    assert "uv tool install strictler --with <패키지>" in message


def test_other_load_errors_keep_the_side_effect_guide(tmp_path: Path) -> None:
    """모듈 최상위에서 터지는 **다른** 예외에는 기존 안내가 그대로 맞다."""
    from strictler.engine import exec as engine_exec
    from strictler.errors import StrictlerError

    path = tmp_path / "node.py"
    path.write_text("VALUE = 1 // 0\n", encoding="utf-8")
    with pytest.raises(StrictlerError) as exc:
        engine_exec.load_script(path)
    assert "import 만으로 부작용이 없어야" in exc.value.message
    assert "형제 파일" not in exc.value.message
