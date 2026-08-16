"""Step 4-b — CLI 배선 (`cli.py`).

**대역을 쓰지 않는다.** 진짜 등록소·진짜 검사기·진짜 엔진으로 돈다 — Step 1 통합에서
남의 모듈을 stub 으로 끼고 돌린 탓에 규칙 슬롯 누락 11건이 merge 시점까지 안 잡혔다.
여기서 진짜 구현을 그대로 쓰면 슬롯 누락이 곧바로 `StrictlerError` 로 터진다.
(예외는 `testing.harness` 하나 — Step 4-a 가 아직 stub 이라 `node test` 배선만 대역으로 본다)

짚는 것:
  - **CRUD 넷이 종류 4개 모두에 대해 도는가**
  - **잘못된 것을 `add` 하면 등록소에 안 들어가는가**
  - **`update` 후 id 가 유지되고 상위가 전이적으로 재검증되는가**
  - **`remove` 후 `list` 가 참조 깨짐을 표시하는가**
  - **종료 코드 0/1/2 — 특히 위반(1) 과 오류(2) 가 안 섞이는가**
  - **모든 오류 경로의 `Finding.rule_id` 가 기대값인가** (슬롯 누락은 여기서 터진다)
  - `$STRICTLER_HOME` 을 tmp 로 돌려 **사용자 홈을 오염시키지 않는가**
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from strictler import cli
from strictler.store.entries import Store

# ── 스크립트 본문 ────────────────────────────────────────────────────────────

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

VANTAGE_TITLE = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        title: str

    @dataclass
    class Params:
        url: str

    @dataclass
    class Args:
        params: Params

    def runNode(args: Args) -> Scene:
        return returnResult(Scene(title=args.params.url))
"""

PERCEIVE = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args) -> Percept:
        return returnResult(Percept(count=len(args.input.url)))
"""

RECKON = """
    from dataclasses import dataclass

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Expect:
        expected: int

    @dataclass
    class Verdict:
        passed: bool
        rule: str
        message: str

    @dataclass
    class Args:
        input: Percept
        params: Expect

    def runNode(args: Args) -> Verdict:
        ok = args.input.count == args.params.expected
        return returnResult(Verdict(
            passed=ok,
            rule="expectedCount",
            message=f"{args.params.expected}개 기대, {args.input.count}개 관측",
        ))
"""

RAISES = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    @dataclass
    class Percept:
        count: int

    @dataclass
    class Args:
        input: Scene

    def runNode(args: Args) -> Percept:
        raise RuntimeError("여기서 터진다")
"""

BROKEN = """
    from dataclasses import dataclass

    @dataclass
    class Scene:
        url: str

    def 진입점이_없다(args):
        return Scene(url="x")
"""


# ── 프로젝트 조립 ────────────────────────────────────────────────────────────


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    return path


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class Project:
    """네 층을 실제 파일로 깔고 CLI 를 그 위에서 돌린다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"

    # 파일 만들기 ------------------------------------------------------------

    def script(self, name: str, body: str) -> Path:
        return write(self.root / "scripts" / f"{name}.py", body)

    def node(self, name: str, node_type: str, script: Path | str) -> Path:
        return write_json(
            self.root / "nodes" / f"{name}.json",
            {
                "info": {"name": name, "description": f"{name} 노드"},
                "type": node_type,
                "script": str(script),
            },
        )

    def pipeline(self, name: str, nodes: list[dict[str, Any]], **body: Any) -> Path:
        raw: dict[str, Any] = {
            "info": {
                "name": name,
                "description": f"{name} 파이프라인",
                "kind": "verify",
            },
            "states": {"values": ["idle"], "initial": "idle"},
            "nodes": nodes,
            "config": {
                "url": {"type": "str", "required": True},
                "expected": {"type": "int", "required": True},
            },
        }
        raw.update(body)
        return write_json(self.root / "pipelines" / f"{name}.json", raw)

    def spec(self, name: str, source: str, config: dict[str, Any]) -> Path:
        return write_json(
            self.root / "specs" / f"{name}.json",
            {
                "info": {"description": f"{name} Spec"},
                "plan": [
                    {"source": source, "description": "기본 경로", "config": config}
                ],
            },
        )

    # CLI 돌리기 -------------------------------------------------------------

    def run(self, *argv: str) -> int:
        return cli.main(["--home", str(self.home), *argv])

    @property
    def store(self) -> Store:
        return Store(self.home)

    def ids(self, kind: str) -> list[str]:
        return sorted(entry.id for entry in self.store.list(kind))  # type: ignore[arg-type]

    def id_of(self, kind: str, name: str) -> str:
        """id 는 자동 발급이라 **등록 순서와 무관하다** — 이름으로 찾는다."""
        found = [
            entry.id
            for entry in self.store.list(kind)  # type: ignore[arg-type]
            if entry.name == name
        ]
        assert len(found) == 1, (kind, name, found)
        return found[0]

    def only(self, kind: str) -> str:
        found = self.ids(kind)
        assert len(found) == 1, found
        return found[0]


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    return Project(tmp_path)


def three_nodes(project: Project) -> tuple[Path, Path, Path]:
    """`page → buttons → check` 세 노드. 전부 절대경로로 이어 붙인다."""
    page = project.node("page", "vantage", project.script("page", VANTAGE))
    buttons = project.node("buttons", "perceive", project.script("buttons", PERCEIVE))
    check = project.node("check", "reckon", project.script("check", RECKON))
    return page, buttons, check


def wiring(page: Path, buttons: Path, check: Path) -> list[dict[str, Any]]:
    return [
        {"id": "page", "source": str(page), "params": {"url": "${config.url}"}},
        {"id": "buttons", "source": str(buttons), "inputs": {"scene": "page"}},
        {
            "id": "check",
            "source": str(check),
            "inputs": {"percept": "buttons"},
            "params": {"expected": "${config.expected}"},
        },
    ]


def basic_pipeline(project: Project) -> Path:
    return project.pipeline("basic", wiring(*three_nodes(project)))


def rule_ids(out: str) -> set[str]:
    """사람이 읽는 출력에서 규칙 id 를 긁는다 — `render_text` 가 `(STR-...)` 로 낸다."""
    return {
        token.strip("()")
        for line in out.splitlines()
        for token in line.split()
        if token.startswith("(STR-") and token.endswith(")")
    }


# ── CRUD 넷 × 종류 넷 ────────────────────────────────────────────────────────


def register_all(project: Project) -> dict[str, str]:
    """스크립트 → 노드 → 파이프라인 → Spec 을 **참조로 이어서** 전부 등록한다."""
    page_script = project.script("page", VANTAGE)
    buttons_script = project.script("buttons", PERCEIVE)
    assert project.run("script", "add", str(page_script)) == 0
    assert project.run("script", "add", str(buttons_script)) == 0
    sc_page = project.id_of("script", "page")
    sc_buttons = project.id_of("script", "buttons")

    page = project.node("page", "vantage", f"${{ref.{sc_page}}}")
    buttons = project.node("buttons", "perceive", f"${{ref.{sc_buttons}}}")
    assert project.run("node", "add", str(page)) == 0
    assert project.run("node", "add", str(buttons)) == 0
    nd_page = project.id_of("node", "page")
    nd_buttons = project.id_of("node", "buttons")

    pipeline = project.pipeline(
        "two",
        [
            {
                "id": "page",
                "source": f"${{ref.{nd_page}}}",
                "params": {"url": "${config.url}"},
            },
            {
                "id": "buttons",
                "source": f"${{ref.{nd_buttons}}}",
                "inputs": {"scene": "page"},
            },
        ],
    )
    assert project.run("pipeline", "add", str(pipeline)) == 0
    pl = project.only("pipeline")

    spec = project.spec("login", f"${{ref.{pl}}}", {"url": "https://x", "expected": 9})
    assert project.run("spec", "add", str(spec)) == 0
    sp = project.only("spec")

    return {
        "script": sc_page,
        "node": nd_page,
        "pipeline": pl,
        "spec": sp,
        "script2": sc_buttons,
        "node2": nd_buttons,
    }


REPLACEMENT: dict[str, str] = {}


@pytest.mark.parametrize("kind", ["script", "node", "pipeline", "spec"])
def test_CRUD_넷이_종류_넷_모두에_대해_돈다(
    project: Project, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    page, buttons, check = three_nodes(project)
    sources = {
        "script": project.root / "scripts" / "page.py",
        "node": page,
        "pipeline": project.pipeline("basic", wiring(page, buttons, check)),
        "spec": None,
    }
    if kind == "spec":
        sources["spec"] = project.spec(
            "login",
            str(project.pipeline("basic", wiring(page, buttons, check))),
            {"url": "https://x", "expected": 9},
        )

    source = sources[kind]
    assert source is not None

    # add
    assert project.run(kind, "add", str(source), "--name", "고른이름") == 0
    entry_id = project.only(kind)
    assert entry_id.startswith(cli._ID_PREFIX[kind])
    capsys.readouterr()

    # list
    assert project.run(kind, "list") == 0
    listed = capsys.readouterr().out
    assert entry_id in listed and "고른이름" in listed and "○" in listed

    # show
    assert project.run(kind, "show", entry_id) == 0
    shown = capsys.readouterr().out
    assert entry_id in shown
    assert source.read_text(encoding="utf-8").splitlines()[0] in shown

    # update — id 가 유지된다
    before = project.store.show(entry_id)
    assert project.run(kind, "update", entry_id, str(source)) == 0
    capsys.readouterr()
    assert project.ids(kind) == [entry_id]
    assert project.store.show(entry_id).hash == before.hash

    # remove
    assert project.run(kind, "remove", entry_id) == 0
    capsys.readouterr()
    assert project.ids(kind) == []
    assert project.run(kind, "list") == 0
    assert "없습니다" in capsys.readouterr().out


def test_json_출력이_기계가_읽는_형태다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("script", "add", str(project.script("page", VANTAGE))) == 0
    entry_id = project.only("script")
    capsys.readouterr()

    assert project.run("script", "list", "--json") == 0
    listed = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in listed] == [entry_id]

    assert project.run("script", "show", entry_id, "--json") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == entry_id
    assert shown["hash"] == project.store.show(entry_id).hash
    assert "runNode" in shown["content"]
    assert shown["dependencies"] == [] and shown["dependents"] == []


# ── 잘못된 것은 등록소에 들어가지 않는다 ─────────────────────────────────────


def test_잘못된_스크립트를_add_하면_등록되지_않는다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = project.script("bad", BROKEN)

    assert project.run("script", "add", str(bad)) == 2

    out = capsys.readouterr().out
    assert "STR-CONTRACT-001" in rule_ids(out)
    assert project.ids("script") == []
    # 복사본조차 만들어지지 않는다 — 검사 통과가 저장의 전제다
    assert list((project.home / "scripts").iterdir()) == []


def test_잘못된_노드를_add_하면_등록되지_않는다(project: Project) -> None:
    node = project.node("bad", "perceive", project.script("bad", BROKEN))
    assert project.run("node", "add", str(node)) == 2
    assert project.ids("node") == []


def test_앞단이_모호한_파이프라인은_add_에서_걸린다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """**돌리기 전에 잡아 자기 수정 신호를 준다** (R5-3, `schema.md` 6절).

    전에는 등록이 통과하고 `check` 에서 **규칙 id 없는 오류**로 터졌다 —
    리포트에서 기계적으로 특정할 수 없었다.
    """
    page, buttons, check = three_nodes(project)
    nodes = wiring(page, buttons, check)
    nodes[2]["inputs"] = {"percept": "buttons", "other": "page"}
    ambiguous = project.pipeline("ambiguous", nodes)

    assert project.run("pipeline", "add", str(ambiguous)) == 2

    out = capsys.readouterr().out
    assert "STR-GRAPH-003" in rule_ids(out)
    assert project.ids("pipeline") == []


def test_같은_앞단을_두_이름으로_받는_파이프라인은_그대로_등록된다(
    project: Project,
) -> None:
    """값은 하나이므로 모호할 것이 없다 — 걸리는 것은 **서로 다른 노드**뿐이다."""
    page, buttons, check = three_nodes(project)
    nodes = wiring(page, buttons, check)
    nodes[2]["inputs"] = {"percept": "buttons", "also": "buttons"}

    assert project.run("pipeline", "add", str(project.pipeline("twice", nodes))) == 0


def test_없는_파일을_add_하면_오류다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("script", "add", str(project.root / "없다.py")) == 2
    assert "등록할 파일이 없습니다" in capsys.readouterr().err


def test_update_도_통과해야_성사된다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    good = project.script("page", VANTAGE)
    assert project.run("script", "add", str(good)) == 0
    entry_id = project.only("script")
    before = project.store.read(entry_id)
    capsys.readouterr()

    assert project.run("script", "update", entry_id, str(project.script("bad", BROKEN))) == 2
    assert "STR-CONTRACT-001" in rule_ids(capsys.readouterr().out)
    # 내용이 바뀌지 않았다 — 검사에 걸린 것은 등록소에 들어가지 않는다
    assert project.store.read(entry_id) == before


# ── update — id 유지 + 상위 전이적 재검증 ────────────────────────────────────


def test_update_는_id_를_유지하고_상위를_전이적으로_재검증한다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    capsys.readouterr()

    # 스크립트의 출력 타입을 바꾼다 — 스크립트 자체는 여전히 정상이다.
    changed = project.script("page", VANTAGE_TITLE)
    assert project.run("script", "update", ids["script"], str(changed)) == 1

    out = capsys.readouterr().out
    assert "STR-REG-005" in rule_ids(out)
    # id 가 유지된다 — 참조가 안 깨진다
    assert project.ids("script") == sorted([ids["script"], ids["script2"]])

    # 전이적이다: 스크립트 → 노드 → 파이프라인 → Spec 순으로 올라간다.
    # 배선 타입이 어긋난 것은 파이프라인이므로 거기에 표시가 붙는다.
    pipeline_entry = project.store.show(ids["pipeline"])
    assert pipeline_entry.broken == "validation"
    assert pipeline_entry.broken_detail == "STR-TYPE-004"

    # 목록이 그것을 드러낸다
    assert project.run("pipeline", "list") == 1
    listed = capsys.readouterr().out
    assert "검증 깨짐" in listed and "STR-TYPE-004" in listed


def test_참조_대상이_검증_깨짐이면_상위도_깨짐으로_나온다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """**깨짐은 전이적이다** (R5-4).

    Spec 등록 검사는 형태만 보므로 재검증이 그냥 통과한다 — 그런데 그 Spec 은
    **돌릴 수 없다.** `spec list` 만 보는 사람에게 `○` 는 거짓말이다.
    """
    ids = register_all(project)
    assert project.run("script", "update", ids["script"], str(project.script("page", VANTAGE_TITLE))) == 1
    capsys.readouterr()

    assert project.run("spec", "list") == 1
    listed = capsys.readouterr().out
    assert "검증 깨짐" in listed
    assert ids["pipeline"] in listed  # 어디서 깨졌는지가 보인다

    assert project.run("spec", "show", ids["spec"]) == 1
    assert "검증 깨짐" in capsys.readouterr().out

    # **저장하지는 않는다** — 아래가 고쳐지면 그 자리에서 사라져야 하는 파생값이다.
    assert project.store.show(ids["spec"]).broken == ""


def test_아래가_고쳐지면_상위의_전이_표시도_사라진다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    assert project.run("script", "update", ids["script"], str(project.script("page", VANTAGE_TITLE))) == 1
    assert project.run("script", "update", ids["script"], str(project.script("page", VANTAGE))) == 0
    capsys.readouterr()

    assert project.run("spec", "list") == 0
    assert "검증 깨짐" not in capsys.readouterr().out


def test_참조_대상이_삭제돼도_상위의_상위까지_번진다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """참조 깨짐도 같은 논리다 — 사라진 것을 참조하는 파이프라인을 참조하는 Spec 도
    돌릴 수 없다. 다만 Spec 자신의 참조는 멀쩡하므로 표시는 **검증 깨짐**이다."""
    ids = register_all(project)
    assert project.run("node", "remove", ids["node"]) == 1
    capsys.readouterr()

    assert project.run("pipeline", "list") == 1
    assert "참조 깨짐" in capsys.readouterr().out

    assert project.run("spec", "list") == 1
    assert "검증 깨짐" in capsys.readouterr().out


def test_상위가_다시_통과하면_검증_깨짐_표시가_걷힌다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    assert project.run("script", "update", ids["script"], str(project.script("page", VANTAGE_TITLE))) == 1
    assert project.run("script", "update", ids["script"], str(project.script("page", VANTAGE))) == 0
    capsys.readouterr()

    assert project.store.show(ids["pipeline"]).broken == ""
    assert project.run("pipeline", "list") == 0


# ── remove — 막지 않고 표시한다 ──────────────────────────────────────────────


def test_remove_후_list_가_참조_깨짐을_표시한다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    capsys.readouterr()

    # 참조가 있어도 삭제를 막지 않는다 — 대신 깨짐을 드러낸다
    assert project.run("script", "remove", ids["script"]) == 1
    removed_out = capsys.readouterr().out
    assert "STR-REG-004" in rule_ids(removed_out)
    assert project.store.list("script") == [project.store.show(ids["script2"])]

    assert project.run("node", "list") == 1
    listed = capsys.readouterr().out
    assert "참조 깨짐" in listed and ids["script"] in listed

    # show 도 같은 깨짐을 드러낸다
    assert project.run("node", "show", ids["node"]) == 1
    assert "참조 깨짐" in capsys.readouterr().out


def test_참조가_없으면_remove_는_0_이다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("script", "add", str(project.script("page", VANTAGE))) == 0
    entry_id = project.only("script")
    capsys.readouterr()
    assert project.run("script", "remove", entry_id) == 0
    assert "삭제했습니다" in capsys.readouterr().out


# ── 사용법 오류는 2 다 ───────────────────────────────────────────────────────


def test_종류가_다른_id_를_주면_사용법_오류다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("script", "add", str(project.script("page", VANTAGE))) == 0
    entry_id = project.only("script")
    capsys.readouterr()

    assert project.run("node", "show", entry_id) == 2
    assert "이 자리에는 node 가 와야" in capsys.readouterr().err


def test_없는_id_를_주면_오류다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("node", "show", "nd_00000000") == 2
    assert "등록소에 없는 id" in capsys.readouterr().err


def test_home_이_상대경로면_오류다(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--home", "./여기", "script", "list"]) == 2
    assert "절대경로가 아닙니다" in capsys.readouterr().err


def test_인자가_없으면_argparse_가_2_로_끝낸다() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2


# ── check — 종료 코드 0 / 1 / 2 ──────────────────────────────────────────────


def test_통과만_있으면_0_이다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = project.spec("login", str(basic_pipeline(project)), {"url": "https://x", "expected": 9})

    assert project.run("check", str(spec)) == 0

    out = capsys.readouterr().out
    assert out.startswith("pass 3  violation 0  not_run 0  error 0")


def test_위반이_있으면_1_이다_오류와_섞이지_않는다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = project.spec("login", str(basic_pipeline(project)), {"url": "https://x", "expected": 3})

    # 위반은 lint 가 제 일을 한 것이다 — 도구는 제대로 돌았다
    assert project.run("check", str(spec)) == 1

    out = capsys.readouterr().out
    assert "violation 1" in out
    assert "error 0" in out


def test_위반은_error_카운트를_올리지_않는다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = project.spec("login", str(basic_pipeline(project)), {"url": "https://x", "expected": 3})

    assert project.run("check", str(spec), "--json") == 1

    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == {"pass": 2, "violation": 1, "not_run": 0, "error": 0}
    assert report["results"][-1]["status"] == "violation"


def test_스크립트가_터지면_2_다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    page = project.node("page", "vantage", project.script("page", VANTAGE))
    boom = project.node("boom", "perceive", project.script("boom", RAISES))
    check = project.node("check", "reckon", project.script("check", RECKON))
    pipeline = project.pipeline(
        "boom",
        [
            {"id": "page", "source": str(page), "params": {"url": "${config.url}"}},
            {"id": "boom", "source": str(boom), "inputs": {"scene": "page"}},
            {
                "id": "check",
                "source": str(check),
                "inputs": {"percept": "boom"},
                "params": {"expected": "${config.expected}"},
            },
        ],
    )
    spec = project.spec("login", str(pipeline), {"url": "https://x", "expected": 9})

    # 스크립트 예외는 **도구가 못 돈 것**이다 — 위반(1) 이 아니다
    assert project.run("check", str(spec), "--json") == 2

    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["error"] == 1
    assert report["summary"]["violation"] == 0
    # 여파는 not run 이다 — 통과와 구분해 보고하되 종료 코드는 오류(2) 가 이긴다
    assert report["summary"]["not_run"] == 1
    downstream = [item for item in report["results"] if item["status"] == "not_run"]
    assert downstream[0]["node"] == "check"
    assert downstream[0]["cause"] == {"node": "boom", "reason": "data_dependency"}


def test_not_run_은_1_이다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """오류의 여파(not run)만 있는 파이프라인은 없다 — 오류가 함께 있으므로 2 다.

    그래서 not run 이 `1` 로 나오는 자리는 `_exit_code` 단위로 직접 확인한다.
    """
    from strictler.errors import Finding, NotRunCause

    not_run = Finding(
        status="not_run",
        node="check",
        cause=NotRunCause(node="buttons", reason="data_dependency"),
    )
    assert cli._exit_code([not_run]) == 1
    assert cli._exit_code([Finding(status="violation")]) == 1
    assert cli._exit_code([Finding(status="pass")]) == 0
    assert cli._exit_code([Finding(status="violation"), Finding(status="error")]) == 2


def test_등록된_Spec_은_id_로_돌린다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    capsys.readouterr()

    assert project.run("check", ids["spec"]) == 0
    assert "pass 2" in capsys.readouterr().out


def test_없는_spec_id_는_STR_REG_002_다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("check", "sp_00000000") == 2
    assert "STR-REG-002" in rule_ids(capsys.readouterr().out)


def test_등록_이후_직접_고친_Spec_은_STR_REG_001_이다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = register_all(project)
    capsys.readouterr()

    # 정적 검사 루트를 피해 등록소 파일을 직접 고친다
    stored = project.store.path_of(ids["spec"])
    stored.write_text(
        stored.read_text(encoding="utf-8").replace("기본 경로", "몰래 고침"),
        encoding="utf-8",
    )

    assert project.run("check", ids["spec"]) == 2
    assert "STR-REG-001" in rule_ids(capsys.readouterr().out)


def test_경로로_준_Spec_은_실행_전에_검사한다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = write_json(project.root / "specs" / "bad.json", {"info": {}, "plan": []})

    assert project.run("check", str(spec)) == 2
    assert "스키마에 맞지 않습니다" in capsys.readouterr().out


def test_없는_Spec_경로는_오류다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("check", str(project.root / "없다.json")) == 2
    assert "Spec 파일이 없습니다" in capsys.readouterr().err


def test_check_는_시각을_스스로_주입한다(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """**엔진은 시각을 읽지 않는다 — 호출자가 준다.** CLI 가 그 호출자다."""
    from strictler.engine import runtime

    seen: dict[str, Any] = {}

    def fake_run_spec(spec: Any, **kw: Any) -> Any:
        seen.update(kw)
        from strictler.report import build_report

        return build_report([])

    monkeypatch.setattr(runtime, "run_spec", fake_run_spec)
    spec = project.spec("login", str(basic_pipeline(project)), {"url": "https://x", "expected": 9})

    assert project.run("check", str(spec)) == 0
    assert isinstance(seen["started_at_ms"], int)
    assert seen["started_at_ms"] > 1_600_000_000_000
    assert seen["spec_name"] == "login.json"


# ── node add/update/remove 가 옆의 `.test.json` 을 함께 다룬다 (R5-2) ────────


def node_with_test(project: Project) -> tuple[Path, Path]:
    """노드 파일과 **그 옆의** `<노드파일>.test.json` 을 만든다."""
    node = project.node("page", "vantage", project.script("page", VANTAGE))
    test = write_json(
        node.with_suffix(".test.json"),
        {
            "node": str(node),
            "cases": [
                {
                    "name": "url 을 그대로 담는다",
                    "args": {"params": {"url": "https://x"}},
                    "expect": {"url": "https://x"},
                }
            ],
        },
    )
    return node, test


def test_node_add_가_옆의_test_json_을_함께_복사한다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """**등록소는 도구가 관리하는 영역**이다 (R5-2).

    함께 복사하지 않으면 `node test <id>` 가 사용자가 등록소 디렉터리에 손으로
    파일을 넣어야만 성립하고, *"등록 후 원본을 지워도 된다"* 를 따르면 단위테스트를
    다시 돌릴 방법이 없어진다.
    """
    node, test = node_with_test(project)
    assert project.run("node", "add", str(node)) == 0
    node_id = project.only("node")
    capsys.readouterr()

    stored = project.store.test_path("node", node_id)
    assert stored is not None and stored.is_file()
    assert project.store.has_test(node_id)

    # 손으로 등록소에 넣지 않아도 `node test <id>` 가 돈다 — 대역 없이 진짜 하네스로.
    assert project.run("node", "test", node_id) == 0
    assert "pass 1" in capsys.readouterr().out


def test_ref_로_노드를_가리킨_테스트는_원본을_지워도_돈다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """*"등록 후 원본을 지워도 된다"* 가 단위테스트에도 성립한다 (R5-2).

    테스트가 노드를 `${ref.<id>}` 로 가리키면 등록소 안에서 완결된다 — 그래서
    id 를 받은 뒤 테스트를 붙여 `update` 하는 것이 자연스러운 저작 순서다.
    """
    node, test = node_with_test(project)
    assert project.run("node", "add", str(node)) == 0
    node_id = project.only("node")

    write_json(
        test,
        {
            "node": f"${{ref.{node_id}}}",
            "cases": [
                {
                    "name": "url 을 그대로 담는다",
                    "args": {"params": {"url": "https://x"}},
                    "expect": {"url": "https://x"},
                }
            ],
        },
    )
    assert project.run("node", "update", node_id, str(node)) == 0
    capsys.readouterr()

    node.unlink()
    test.unlink()
    assert project.run("node", "test", node_id) == 0
    assert "pass 1" in capsys.readouterr().out


def test_테스트가_없는_노드도_정상_등록된다(project: Project) -> None:
    """**없으면 그냥 없는 것이다 — 오류가 아니다.**"""
    node = project.node("page", "vantage", project.script("page", VANTAGE))
    assert project.run("node", "add", str(node)) == 0
    assert project.store.has_test(project.only("node")) is False


def test_node_show_가_단위테스트_유무를_드러낸다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    node, _test = node_with_test(project)
    assert project.run("node", "add", str(node)) == 0
    node_id = project.only("node")
    capsys.readouterr()

    assert project.run("node", "show", node_id) == 0
    assert "단위테스트" in capsys.readouterr().out


def test_node_update_가_테스트를_따라_교체하고_없으면_걷는다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    node, test = node_with_test(project)
    assert project.run("node", "add", str(node)) == 0
    node_id = project.only("node")

    # 테스트만 고쳐 다시 등록하면 등록소의 것도 따라온다.
    write_json(test, {"node": str(node), "cases": []})
    assert project.run("node", "update", node_id, str(node)) == 0
    stored = project.store.test_path("node", node_id)
    assert stored is not None
    assert json.loads(stored.read_text(encoding="utf-8"))["cases"] == []

    # 원본에서 사라지면 등록소에서도 걷는다 — 등록된 적 없는 테스트가 남으면 유령이다.
    test.unlink()
    assert project.run("node", "update", node_id, str(node)) == 0
    assert project.store.has_test(node_id) is False
    capsys.readouterr()


def test_node_remove_는_테스트도_함께_지운다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    node, _test = node_with_test(project)
    assert project.run("node", "add", str(node)) == 0
    node_id = project.only("node")
    stored = project.store.test_path("node", node_id)
    assert stored is not None and stored.is_file()

    assert project.run("node", "remove", node_id) == 0
    assert not stored.exists()
    capsys.readouterr()


# ── node test — 실제 실행 계열 배선 ──────────────────────────────────────────


def test_node_test_는_등록된_노드_옆의_test_json_을_돌린다(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from strictler.errors import Finding
    from strictler.testing import harness

    assert project.run("node", "add", str(project.node("page", "vantage", project.script("page", VANTAGE)))) == 0
    node_id = project.only("node")
    test_path = project.store.path_of(node_id).with_suffix(".test.json")
    write_json(test_path, {"node": str(project.store.path_of(node_id)), "cases": []})
    capsys.readouterr()

    seen: dict[str, Any] = {}

    def fake_load(path: Path, env: Any) -> tuple[object, list[Finding]]:
        seen["path"] = path
        return object(), []

    def fake_run(node_test: object, **kw: Any) -> list[Finding]:
        seen["ran"] = node_test
        return [Finding(status="pass", node="page")]

    monkeypatch.setattr(harness, "load_node_test", fake_load)
    monkeypatch.setattr(harness, "run_node_test", fake_run)

    assert project.run("node", "test", node_id) == 0
    assert seen["path"] == test_path
    assert "pass 1" in capsys.readouterr().out


def test_node_test_는_실패를_그대로_종료_코드로_낸다(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from strictler import rules
    from strictler.errors import Finding
    from strictler.testing import harness

    test_file = write_json(project.root / "page.test.json", {"node": "x", "cases": []})

    monkeypatch.setattr(
        harness, "load_node_test", lambda path, env: (object(), [])
    )
    monkeypatch.setattr(
        harness,
        "run_node_test",
        lambda node_test, **kw: [
            rules.finding(
                "STR-TEST-002",
                node="page",
                fields={"exc": "RuntimeError: 터졌다"},
            )
        ],
    )

    assert project.run("node", "test", str(test_file)) == 2
    assert "STR-TEST-002" in rule_ids(capsys.readouterr().out)


def test_test_json_이_없으면_오류다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("node", "add", str(project.node("page", "vantage", project.script("page", VANTAGE)))) == 0
    node_id = project.only("node")
    capsys.readouterr()

    assert project.run("node", "test", node_id) == 2
    assert "단위테스트가 등록돼 있지 않습니다" in capsys.readouterr().err

    assert project.run("node", "test", str(project.root / "없다.test.json")) == 2
    assert "단위테스트 파일이 없습니다" in capsys.readouterr().err


# ── 규칙 슬롯 — CLI 가 직접 만드는 것 ────────────────────────────────────────


def test_CLI_가_직접_만드는_규칙은_슬롯이_전부_채워진다() -> None:
    """슬롯을 빠뜨리면 **규칙 id 가 사라지는 게 아니라 `StrictlerError` 로 터진다.**

    `cli.py` 가 `rules.finding` 을 직접 부르는 자리는 셋이다 —
    `STR-REG-004`(remove), `STR-REG-002`/`-001`(check). 눈으로 읽지 말고 돌려서 본다.
    """
    from strictler import rules

    for rule_id in ("STR-REG-001", "STR-REG-002", "STR-REG-004"):
        made = rules.finding(rule_id, path="자리", fields={"id": "sc_1a2b3c4d"})
        assert made.rule_id == rule_id
        assert "{" not in made.message
        assert "sc_1a2b3c4d" in made.message


def test_깨짐_표시는_4상태_요약을_붙이지_않는다(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """`error 1` 이라고 적어놓고 종료 코드 `1` 을 내는 모순을 만들지 않는다."""
    ids = register_all(project)
    capsys.readouterr()

    assert project.run("script", "remove", ids["script"]) == 1

    out = capsys.readouterr().out
    assert "STR-REG-004" in rule_ids(out)
    assert "violation 0" not in out  # 4상태 요약 헤더가 없다


# ── 등록소 위치 — 사용자 홈을 오염시키지 않는다 ──────────────────────────────


def test_STRICTLER_HOME_을_따른다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "strictler-home"
    fake_user_home = tmp_path / "user"
    fake_user_home.mkdir()
    monkeypatch.setenv("STRICTLER_HOME", str(home))
    monkeypatch.setenv("HOME", str(fake_user_home))

    project = Project(tmp_path)
    script = project.script("page", VANTAGE)

    # `--home` 없이 — `$STRICTLER_HOME` 이 잡는다
    assert cli.main(["script", "add", str(script)]) == 0
    capsys.readouterr()

    assert (home / "registry.json").is_file()
    assert list((home / "scripts").glob("sc_*.py"))
    assert not (fake_user_home / ".strictler").exists()
