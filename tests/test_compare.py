"""Step 3-b — 비교 파이프라인 엔진 테스트.

⚠ **대역은 Step 3-a 가 아직 `NotImplementedError` 인 것들만** 쓴다
(`engine.result` / `engine.exec` / `engine.state`). 나머지 — `rules` `refs` `report`
`store` `checks.*` `typesys` — 는 **진짜 구현을 그대로 쓴다.** Step 1·2 통합에서 남의
모듈을 stub 으로 끼고 돌린 탓에 규칙 슬롯 누락이 merge 시점까지 안 잡혔기 때문이다.

`engine.exec` 대역은 **진짜로 스크립트를 로드해 돌린다.** 흉내만 내면 "취합→분배가
노드를 건너 제대로 흐르는가" 를 확인할 수 없다.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from strictler.engine import compare
from strictler.errors import Finding, NotRunCause
from strictler.model import Pipeline
from strictler.store.entries import Store

# ── Step 3-a 대역 ────────────────────────────────────────────────────────────


class FakeOutcome:
    """`engine.result.NodeOutcome` — MODULES.md 가 적어둔 공개 필드만 갖는다."""

    def __init__(self, node_id: str, status: str) -> None:
        self.node_id = node_id
        self.status = status
        self.value: Any = None
        self.findings: list[Finding] = []


class FakeRunResult:
    """`engine.result.RunResult`."""

    def __init__(self) -> None:
        self.outcomes: dict[str, FakeOutcome] = {}
        self.findings: list[Finding] = []


class FakeStateMachine:
    """`engine.state.StateMachine` — `transitions` 는 **시간만** 다룬다."""

    def __init__(self, states, transitions, config, started_at_ms) -> None:
        self.state = states.initial
        self.transitions = list(transitions)
        self.started_at_ms = started_at_ms

    @property
    def current(self) -> str:
        return self.state

    def after_node(self, node_id: str) -> None:
        for transition in self.transitions:
            if transition.after == node_id:
                self.state = transition.to

    def matches(self, node_state_mapping: Mapping[str, str], when_state: str) -> bool:
        return node_state_mapping.get(when_state, when_state) == self.state

    def snapshot(self, node_state_mapping: Mapping[str, str]) -> dict[str, Any]:
        snap: dict[str, Any] = {name: self.state for name in node_state_mapping}
        snap["__startedAt"] = self.started_at_ms
        return snap

    def blocked_by(self, node_id: str) -> list[str]:
        return [t.to for t in self.transitions if t.after == node_id]


_counter = itertools.count()


class FakeExec:
    """`engine.exec` — **진짜로 로드해서 돌린다.**

    `validate_input` / `validate_output` 은 기본이 통과다. 검증 실패의 여파를 보는
    테스트만 `stub_input` / `stub_output` 을 채운다.
    """

    def __init__(self) -> None:
        self.stub_input: list[Finding] = []
        self.stub_output: list[Finding] = []

    def load_script(self, path: Path):
        name = f"strictler_compare_test_{next(_counter)}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        module.returnResult = lambda value: value  # 출력 진입점은 이름 고정
        spec.loader.exec_module(module)
        return module

    def build_args(self, module, contract, *, input_value=None, params=None, state=None):
        kwargs: dict[str, Any] = {}
        if contract.input_type:
            kwargs["input"] = input_value
        if contract.params_type:
            kwargs["params"] = _fill(module, contract.params_type, params or {})
        if contract.state_type:
            kwargs["state"] = _fill(module, contract.state_type, state or {})
        return module.Args(**kwargs)

    def invoke(self, module, args):
        return module.runNode(args)

    def validate_input(self, contract, value, registry, *, path, node):
        return [item.model_copy() for item in self.stub_input]

    def validate_output(self, contract, value, registry, *, path, node):
        return [item.model_copy() for item in self.stub_output]


def _fill(module, type_name: str, values: Mapping[str, Any]):
    """`Args` 의 하위 dataclass 를 만든다. 선언에 없는 키는 넣지 않는다."""
    cls = getattr(module, type_name)
    declared = getattr(cls, "__annotations__", {})
    return cls(**{key: value for key, value in values.items() if key in declared})


@pytest.fixture(autouse=True)
def stub_step_3a(monkeypatch):
    """Step 3-a 산출물만 대역으로 바꾼다."""
    fake = FakeExec()
    monkeypatch.setattr(compare, "NodeOutcome", FakeOutcome)
    monkeypatch.setattr(compare, "RunResult", FakeRunResult)
    monkeypatch.setattr(compare, "StateMachine", FakeStateMachine)
    monkeypatch.setattr(compare, "node_exec", fake)
    return fake


# ── 픽스처 만들기 ────────────────────────────────────────────────────────────


DETECT = """\
from dataclasses import dataclass


@dataclass
class Params:
    bump: {ptype}


@dataclass
class Args:
    params: Params


@dataclass
class Buttons:
    count: int


def runNode(args: Args) -> Buttons:
    return returnResult(Buttons(count={expr}))
"""

SHAPE = """\
from dataclasses import dataclass


@dataclass
class Buttons:
    count: int


@dataclass
class Args:
    input: Buttons


@dataclass
class Shape:
    count: int


def runNode(args: Args) -> Shape:
    return returnResult(Shape(count=args.input.count))
"""

BOOM = """\
from dataclasses import dataclass


@dataclass
class Params:
    bump: int


@dataclass
class Args:
    params: Params


@dataclass
class Buttons:
    count: int


def runNode(args: Args) -> Buttons:
    raise ValueError("인식 실패")
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def node_file(tmp_path: Path, name: str, script: str, kind: str = "perceive") -> str:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "info": {"name": name, "description": f"{name} 노드"},
                "type": kind,
                "script": script,
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def build_pipeline(nodes: list[dict], targets: list[str], compare_ids: list[str], **extra):
    raw = {
        "info": {"name": "cmp", "description": "동일성 검증", "kind": "compare"},
        "states": {"values": ["idle"], "initial": "idle"},
        "nodes": nodes,
        "targets": targets,
        "compare": compare_ids,
    }
    raw.update(extra)
    return Pipeline.model_validate(raw)


def run(pipeline, config, tmp_path):
    return compare.run_compare_pipeline(
        pipeline,
        config,
        store=Store(tmp_path / "home"),
        env={"HOME": str(tmp_path)},
        started_at_ms=1_700_000_000_000,
        path="cmp.json > plan[0] > cmp",
    )


def chain_fixture(
    tmp_path: Path,
    counts: Mapping[str, Any],
    targets: list[str],
    ptypes: Mapping[str, str] | None = None,
):
    """detect(target 별 스크립트) ──▶ shape(공유 스크립트) 2단 체인.

    `counts` 가 target 별 `params.bump` 값이다. **`params` 는 target 별로 갈린다** —
    스크립트가 갈라지니 거기 필요한 값도 갈라지고, `ptypes` 를 주면 **타입까지** 갈린다.
    """
    shape = write(tmp_path, "shape.py", SHAPE)
    scoped: dict[str, dict[str, Any]] = {}
    for target, count in counts.items():
        ptype = (ptypes or {}).get(target, "int")
        expr = "args.params.bump" if ptype == "int" else "int(args.params.bump)"
        detect = write(
            tmp_path, f"detect_{target}.py", DETECT.format(ptype=ptype, expr=expr)
        )
        scoped[target] = {"detectScript": str(detect), "bump": count}

    nodes = [
        {
            "id": "detect",
            "source": node_file(tmp_path, "detect", "${config.detectScript}"),
            "params": {"bump": "${config.bump}"},
        },
        {
            "id": "shape",
            "source": node_file(tmp_path, "shape", str(shape)),
            "inputs": {"input": "detect"},
        },
    ]
    pipeline = build_pipeline(nodes, targets, ["detect", "shape"])
    config = {"targets": scoped}
    return pipeline, config


# ── all_same — 짝비교가 아니라 전체 일치 ─────────────────────────────────────


def test_all_same_전부_같으면_참():
    assert compare.all_same({"a": 3, "b": 3, "c": 3, "d": 3}) is True


def test_all_same_셋_중_하나만_달라도_위반():
    assert compare.all_same({"legacy": 3, "v2": 3, "v3": 2}) is False


def test_all_same_짝비교가_아니다():
    # 짝지어 비교하면 (a,b) 통과·(b,c) 통과라고 넘어갈 수 있는 배치.
    assert compare.all_same({"a": 1, "b": 1, "c": 2, "d": 2}) is False


def test_all_same_원소가_없거나_하나면_참():
    assert compare.all_same({}) is True
    assert compare.all_same({"only": 1}) is True


# ── resolve_target_config ────────────────────────────────────────────────────


def test_targets_오버레이가_공통을_이긴다():
    config = {"settleMs": 2000, "targets": {"legacy": {"settleMs": 50, "prefix": "btn-"}}}
    resolved = compare.resolve_target_config(config, "legacy")
    assert resolved == {"settleMs": 50, "prefix": "btn-"}


def test_오버레이에_없으면_공통에서_찾는다():
    config = {"settleMs": 2000, "targets": {"v2": {"roleAttr": "data-role"}}}
    assert compare.resolve_target_config(config, "v2") == {
        "settleMs": 2000,
        "roleAttr": "data-role",
    }


def test_targets_서랍_자체는_config_값이_아니다():
    config = {"targets": {"legacy": {}}}
    assert compare.resolve_target_config(config, "legacy") == {}


def test_target_이_서랍에_없으면_공통만_남는다():
    config = {"settleMs": 1, "targets": {"legacy": {"x": 1}}}
    assert compare.resolve_target_config(config, "없는target") == {"settleMs": 1}


# ── 취합 / 분배 ──────────────────────────────────────────────────────────────


def test_대상_셋이_전부_같으면_통과(tmp_path):
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 3}, ["legacy", "v2", "v3"]
    )
    result, report = run(pipeline, config, tmp_path)

    assert [f.status for f in result.findings] == ["pass", "pass"]
    assert report.root["detect"].same is True
    assert report.root["shape"].same is True
    assert result.outcomes["shape"].status == "pass"


def test_대상_넷_중_하나만_달라도_위반이고_리포트에_전부_남는다(tmp_path):
    pipeline, config = chain_fixture(
        tmp_path,
        {"legacy": 3, "v2": 3, "v3": 2, "canary": 3},
        ["legacy", "v2", "v3", "canary"],
    )
    result, report = run(pipeline, config, tmp_path)

    entry = report.root["shape"]
    assert entry.same is False
    assert set(entry.values) == {"legacy", "v2", "v3", "canary"}
    assert entry.values["v3"] != entry.values["legacy"]

    violations = [f for f in result.findings if f.status == "violation"]
    assert {f.node for f in violations} == {"detect", "shape"}
    # 무엇이 어디서 어떻게 달랐는지가 메시지에 담긴다.
    message = next(f.message for f in violations if f.node == "shape")
    assert "v3" in message and "legacy" in message


def test_위반은_뒷단을_끊지_않는다(tmp_path):
    """**위반은 정상 결과다.** 차이는 전부 모은다 — 뒷단을 멈추는 것은 오류뿐이다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 2, "v3": 1}, ["legacy", "v2", "v3"]
    )
    result, _ = run(pipeline, config, tmp_path)

    assert result.outcomes["detect"].status == "violation"
    assert result.outcomes["shape"].status == "violation"
    assert not [f for f in result.findings if f.status == "not_run"]


def test_취합한_묶음이_노드를_건너_분배된다(tmp_path):
    """앞단 `{target: 값}` 이 뒷단에서 target 마다 자기 값 하나로 풀린다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 7, "v2": 7, "v3": 7}, ["legacy", "v2", "v3"]
    )
    result, _ = run(pipeline, config, tmp_path)

    detected = compare.collect_target_values(result, "detect")
    shaped = compare.collect_target_values(result, "shape")
    # 취합은 **평평한 데이터**다 — target 마다 클래스가 달라도 개념 층에서 비교된다.
    assert detected == {"legacy": {"count": 7}, "v2": {"count": 7}, "v3": {"count": 7}}
    assert shaped == detected
    assert compare.all_same(shaped) is True


def test_target_별_params_가_타입까지_달라도_통과한다(tmp_path):
    """`params` 는 갈려도 된다 — 스크립트가 갈라지니 거기 필요한 값도 갈라진다.

    input/output 만 노드에 귀속되어 공통이면 비교가 성립한다.
    """
    pipeline, config = chain_fixture(
        tmp_path,
        {"legacy": 4, "v2": "4", "v3": 4},
        ["legacy", "v2", "v3"],
        ptypes={"v2": "str"},
    )
    result, report = run(pipeline, config, tmp_path)

    assert report.root["detect"].same is True
    assert report.root["shape"].same is True
    assert not [f for f in result.findings if f.status in ("violation", "error")]


def test_compare_에_적힌_노드만_리포트에_담긴다(tmp_path):
    """어느 노드를 비교할지는 파이프라인의 `compare` 가 정한다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 5, "v2": 5}, ["legacy", "v2"]
    )
    pipeline.compare = ["shape"]
    _, report = run(pipeline, config, tmp_path)
    assert set(report.root) == {"shape"}


def test_리포트는_실행과_동시에_쌓이고_그대로_기록된다(tmp_path):
    """출력 위치는 Spec `plan` 항목이고, 파이프라인이 그쪽에 쌓는다."""
    from strictler.report import write_compare_report

    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 9}, ["legacy", "v2", "v3"]
    )
    _, report = run(pipeline, config, tmp_path)

    out = tmp_path / "out" / "compare.json"
    write_compare_report(report, out)
    written = json.loads(out.read_text(encoding="utf-8"))

    assert written["shape"] == {
        "same": False,
        "values": {"legacy": {"count": 3}, "v2": {"count": 3}, "v3": {"count": 9}},
    }


def test_collect_target_values_는_돌지_않은_노드에_빈_매핑(tmp_path):
    result = FakeRunResult()
    assert compare.collect_target_values(result, "없음") == {}


# ── 오류와 not run ───────────────────────────────────────────────────────────


def test_한_target_스크립트가_예외면_노드는_오류_뒷단은_not_run(tmp_path):
    """**스크립트 예외는 오류다.** 노드는 한 벌이므로 묶음이 안 차면 비교가 성립하지 않는다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 3}, ["legacy", "v2", "v3"]
    )
    boom = write(tmp_path, "boom.py", BOOM)
    config["targets"]["v3"]["detectScript"] = str(boom)

    result, report = run(pipeline, config, tmp_path)

    assert result.outcomes["detect"].status == "error"
    assert result.outcomes["shape"].status == "not_run"
    assert "detect" not in report.root and "shape" not in report.root

    not_run = [f for f in result.findings if f.status == "not_run"]
    assert [f.node for f in not_run] == ["shape"]
    assert not_run[0].cause == NotRunCause(node="detect", reason="data_dependency")

    errors = [f for f in result.findings if f.status == "error"]
    assert any("v3" in f.message and "인식 실패" in f.message for f in errors)


def test_not_run_원인은_최초로_못_돈_노드다(tmp_path):
    """중간 노드를 가리키면 원인이 뭉개진다 — 3단 체인에서 확인한다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 3}, ["legacy", "v2", "v3"]
    )
    tail = write(tmp_path, "tail.py", SHAPE)
    pipeline.nodes.append(
        Pipeline.model_validate(
            {
                "info": {"name": "x", "description": "x", "kind": "compare"},
                "states": {"values": ["idle"], "initial": "idle"},
                "nodes": [
                    {
                        "id": "tail",
                        "source": node_file(tmp_path, "tail", str(tail)),
                        "inputs": {"input": "shape"},
                    }
                ],
                "targets": ["legacy", "v2", "v3"],
                "compare": [],
            }
        ).nodes[0]
    )
    config["targets"]["legacy"]["detectScript"] = str(write(tmp_path, "boom2.py", BOOM))

    result, _ = run(pipeline, config, tmp_path)
    causes = {f.node: f.cause for f in result.findings if f.status == "not_run"}
    assert causes["shape"] == NotRunCause(node="detect", reason="data_dependency")
    assert causes["tail"] == NotRunCause(node="detect", reason="data_dependency")


def test_상태를_밀_노드가_실패하면_기다리던_노드는_state_unreachable(tmp_path):
    """not run 전파의 **두 번째 경로**. 데이터 의존이 없어도 도달 불가가 된다."""
    boom = write(tmp_path, "boom.py", BOOM)
    watcher = write(
        tmp_path,
        "watch.py",
        """\
from dataclasses import dataclass


@dataclass
class State:
    phase: str


@dataclass
class Args:
    state: State


@dataclass
class Seen:
    phase: str


def runNode(args: Args) -> Seen:
    return returnResult(Seen(phase=args.state.phase))
""",
    )
    nodes = [
        {
            "id": "capture",
            "source": node_file(tmp_path, "capture", str(boom)),
            "params": {"bump": "${config.bump}"},
        },
        {
            "id": "watch",
            "source": node_file(tmp_path, "watch", str(watcher), kind="sense"),
            "states": {"phase": "active"},
            "when": {"state": "phase"},
        },
    ]
    pipeline = build_pipeline(
        nodes,
        ["legacy", "v2"],
        ["watch"],
        states={"values": ["idle", "active"], "initial": "idle"},
        transitions=[{"after": "capture", "to": "active"}],
    )
    config = {"targets": {"legacy": {"bump": 1}, "v2": {"bump": 1}}}

    result, _ = run(pipeline, config, tmp_path)
    assert result.outcomes["capture"].status == "error"
    cause = next(f.cause for f in result.findings if f.status == "not_run")
    assert cause == NotRunCause(node="capture", reason="state_unreachable")


def test_출력_검증이_걸리면_노드는_오류다(tmp_path, stub_step_3a):
    """계약 위반은 **오류**다 — 위반이 아니다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1}, ["legacy", "v2"]
    )
    stub_step_3a.stub_output = [
        Finding(status="error", message="출력 타입이 선언과 다릅니다.")
    ]
    result, report = run(pipeline, config, tmp_path)

    assert result.outcomes["detect"].status == "error"
    assert report.root == {}
    assert any("[target: legacy]" in f.message for f in result.findings)


def test_script_가_안_풀리면_오류(tmp_path):
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1}, ["legacy", "v2"]
    )
    del config["targets"]["v2"]["detectScript"]
    result, report = run(pipeline, config, tmp_path)

    finding = next(f for f in result.findings if f.status == "error")
    assert finding.rule_id == "STR-CMP-004"
    # target 한 벌이 빠지면 비교가 성립하지 않는다 — 뒷단은 not run 이다.
    assert result.outcomes["detect"].status == "error"
    assert result.outcomes["shape"].status == "not_run"
    assert report.root == {}


# ── 규칙 슬롯 — 내 모듈이 내는 규칙 id 가 살아남는가 ─────────────────────────


def test_targets_가_둘_미만이면_STR_CMP_003(tmp_path):
    shape = write(tmp_path, "shape.py", SHAPE)
    pipeline = build_pipeline(
        [{"id": "shape", "source": node_file(tmp_path, "shape", str(shape))}],
        ["legacy"],
        ["shape"],
    )
    result, report = run(pipeline, {}, tmp_path)

    assert [f.rule_id for f in result.findings] == ["STR-CMP-003"]
    assert "1" in result.findings[0].message
    assert report.root == {}


def test_없는_config_는_STR_CMP_004_로_나온다(tmp_path):
    """`targets.<이름>` 에도 공통에도 없다 — `STR-CONFIG-001` 이 아니다."""
    shape = write(tmp_path, "shape.py", SHAPE)
    pipeline = build_pipeline(
        [
            {
                "id": "shape",
                "source": node_file(tmp_path, "shape", str(shape)),
                "params": {"prefix": "${config.없는값}"},
            }
        ],
        ["legacy", "v2"],
        ["shape"],
    )
    result, _ = run(pipeline, {"targets": {"legacy": {}, "v2": {}}}, tmp_path)

    finding = next(f for f in result.findings if f.rule_id == "STR-CMP-004")
    assert "없는값" in finding.message
    assert finding.node == "shape"


def test_내가_내는_규칙_전부가_렌더된다():
    """슬롯을 빠뜨리면 `StrictlerError` 가 나면서 **규칙 id 가 사라진다.**

    눈으로 읽지 말고 실제로 태워서 확인한다 (Step 1 에서 11건, Step 2 에서 3건).
    """
    from strictler import rules

    expected = {"STR-CMP-003": {"count"}, "STR-CMP-004": {"name"}}
    for rule_id, slots in expected.items():
        assert set(rules.get_rule(rule_id).slots) == slots

    assert rules.finding(
        "STR-CMP-003", path="p", fields={"count": 1}
    ).rule_id == "STR-CMP-003"
    assert rules.finding(
        "STR-CMP-004", path="p", fields={"name": "x"}
    ).rule_id == "STR-CMP-004"


# ── 잘못된 파이프라인 종류 ───────────────────────────────────────────────────


def test_값_검증_파이프라인을_받으면_오류(tmp_path):
    shape = write(tmp_path, "shape.py", SHAPE)
    raw = {
        "info": {"name": "v", "description": "값 검증", "kind": "verify"},
        "states": {"values": ["idle"], "initial": "idle"},
        "nodes": [{"id": "shape", "source": node_file(tmp_path, "shape", str(shape))}],
    }
    result, report = run(Pipeline.model_validate(raw), {}, tmp_path)

    assert [f.status for f in result.findings] == ["error"]
    assert "verify" in result.findings[0].message
    assert report.root == {}


# ── 배선 ─────────────────────────────────────────────────────────────────────


def test_앞단이_둘이면_오류다(tmp_path):
    """`Args.input` 은 값 하나다. 억지로 골라 넣으면 조용한 오답이 된다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1}, ["legacy", "v2"]
    )
    other = write(tmp_path, "other.py", DETECT.format(ptype="int", expr="1"))
    pipeline.nodes.append(
        pipeline.nodes[0].model_copy(
            update={
                "id": "other",
                "source": node_file(tmp_path, "other", str(other)),
            }
        )
    )
    shape = next(pn for pn in pipeline.nodes if pn.id == "shape")
    shape.inputs = {"a": "detect", "b": "other"}

    result, _ = run(pipeline, config, tmp_path)
    assert result.outcomes["shape"].status == "error"
    assert any("서로 다른 앞단" in f.message for f in result.findings)
