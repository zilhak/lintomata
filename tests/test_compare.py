"""Step 3-b — 비교 파이프라인 엔진 테스트.

**대역을 쓰지 않는다.** `NodeOutcome`/`RunResult`/`StateMachine`/`node_exec` 를 전부
대역으로 갈아끼웠더니 **진짜 구현과의 정합이 한 번도 안 태워졌고**, 그 사이에 구동
결함 두 개가 통째로 가려졌다 (MODULES.md R4-7). `FakeStateMachine.snapshot` 은 문자열을
주는데 진짜는 bool 을 준다 — 그 차이조차 안 드러났다.

짚는 것:
  - 구동 순서·구간 전이·not run 전파가 **`engine.drive` 한 벌**로 도는가 (R4-1)
  - 파이프라인의 **모든 노드가 네 상태 중 정확히 하나**에 들어가는가 (R4-2)
  - 분배가 **스크립트가 낸 값 그대로** 흐르는가 (R4-5)
  - target 무관한 결과가 target 수만큼 중복되지 않는가 (R4-6)
  - **엔진은 `==` 만 안다** — 허용 오차도 반올림도 없다
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping

from lintomata.checks import reachability
from lintomata.engine import compare
from lintomata.engine.result import RunResult
from lintomata.errors import NotRunCause
from lintomata.model import Pipeline
from lintomata.store.entries import Store

STARTED_AT = 1_700_000_000_000


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

WRONG_OUTPUT = """\
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
    return returnResult(Buttons(count="셋이요"))
"""

WATCH = """\
from dataclasses import dataclass


@dataclass
class Buttons:
    count: int


@dataclass
class State:
    phase: bool


@dataclass
class Args:
    input: Buttons
    state: State


@dataclass
class Seen:
    phase: bool


def runNode(args: Args) -> Seen:
    return returnResult(Seen(phase=args.state.phase))
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


def run(pipeline, config, tmp_path, store: Store | None = None, env: dict | None = None):
    return compare.run_compare_pipeline(
        pipeline,
        config,
        store=store or Store(tmp_path / "home"),
        env=env or {"HOME": str(tmp_path)},
        started_at_ms=STARTED_AT,
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


FOUR_STATES = {"pass", "violation", "not_run", "error"}


def assert_four_states(pipeline: Pipeline, result: Any) -> dict[str, str]:
    """★ **파이프라인의 모든 노드가 네 상태 중 정확히 하나에 들어간다** (R4-2).

    어느 상태에도 없이 리포트에서 조용히 사라지는 노드가 있으면 그건 거짓
    리포트다 (`schema.md` 9절). 한 클래스의 결함을 통째로 막는 가드다.
    """
    ids = [pn.id for pn in pipeline.nodes]
    assert set(result.outcomes) == set(ids), "결과가 없는 노드가 있다"

    reported: dict[str, set[str]] = {}
    for finding in result.findings:
        if finding.node:
            reported.setdefault(finding.node, set()).add(finding.status)

    for node_id in ids:
        status = result.outcomes[node_id].status
        assert status in FOUR_STATES
        assert node_id in reported, f"{node_id} 가 리포트에서 사라졌다"
        assert reported[node_id] == {status}, (node_id, reported[node_id], status)
    return {node_id: result.outcomes[node_id].status for node_id in ids}


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


def test_엔진은_같음_만_안다_반올림하지_않는다():
    """**허용 오차도 무시 필드도 엔진에 두지 않는다** (`schema.md` 12절).

    정규화는 비교용 데이터를 내보내는 **스크립트**가 한다 — 좌표 반올림도
    타임스탬프 제거도 도메인 지식이고, 도메인 지식은 언제나 스크립트 쪽에 있다.
    엔진이 한 번이라도 값을 손보면 그 순간 "동일하다"의 뜻이 흐려진다.
    """
    assert compare.all_same({"legacy": 3.0, "v2": 3.0001}) is False
    assert compare.all_same({"legacy": {"x": 3.0}, "v2": {"x": 3.0001}}) is False
    assert compare.all_same({"legacy": 3.0, "v2": 3.0}) is True


def test_리포트_취합도_반올림하지_않는다(tmp_path):
    """`_plain` 은 구조를 펴기만 한다 — 값은 손대지 않는다."""
    assert compare._plain([1.0, {"x": 2.00001}]) == [1.0, {"x": 2.00001}]


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
    assert assert_four_states(pipeline, result) == {"detect": "pass", "shape": "pass"}


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

    assert assert_four_states(pipeline, result) == {
        "detect": "violation",
        "shape": "violation",
    }
    assert not [f for f in result.findings if f.status == "not_run"]


def test_분배는_스크립트가_낸_값을_그대로_넘긴다(tmp_path):
    """**재구성하지 않는다** (R4-5).

    앞단이 낸 dataclass 인스턴스가 다른 무언가로 바뀌면 `dataclasses.asdict` 나
    `isinstance` 를 쓰는 스크립트가 값 검증에서는 되고 비교에서만 안 된다 —
    "스크립트의 모양이 값 검증과 완전히 같다" 가 깨진다.
    """
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 7, "v2": 7, "v3": 7}, ["legacy", "v2", "v3"]
    )
    result, report = run(pipeline, config, tmp_path)

    detected = compare.collect_target_values(result, "detect")
    assert set(detected) == {"legacy", "v2", "v3"}
    for target, value in detected.items():
        assert dataclasses.is_dataclass(value) and not isinstance(value, type)
        assert type(value).__name__ == "Buttons"
        assert dataclasses.asdict(value) == {"count": 7}
    # target 마다 스크립트가 다르므로 **클래스도 다르다** — 그래서 비교는 편 값으로 한다.
    assert type(detected["legacy"]) is not type(detected["v2"])
    assert report.root["detect"].values == {
        "legacy": {"count": 7},
        "v2": {"count": 7},
        "v3": {"count": 7},
    }


def test_취합한_묶음이_노드를_건너_분배된다(tmp_path):
    """앞단 `{target: 값}` 이 뒷단에서 target 마다 자기 값 하나로 풀린다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 7, "v2": 7, "v3": 7}, ["legacy", "v2", "v3"]
    )
    result, report = run(pipeline, config, tmp_path)

    shaped = compare.collect_target_values(result, "shape")
    assert {t: v.count for t, v in shaped.items()} == {"legacy": 7, "v2": 7, "v3": 7}
    assert report.root["shape"].same is True


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
    """어느 노드를 비교할지는 파이프라인의 `compare` 가 정한다.

    담기지 않는 노드도 **돌아간 것 자체는 통과로 보고된다** — 안 그러면 그 노드가
    네 상태 어디에도 없이 리포트에서 사라진다 (R4-2).
    """
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 5, "v2": 5}, ["legacy", "v2"]
    )
    pipeline.compare = ["shape"]
    result, report = run(pipeline, config, tmp_path)

    assert set(report.root) == {"shape"}
    assert assert_four_states(pipeline, result) == {"detect": "pass", "shape": "pass"}


def test_리포트는_실행과_동시에_쌓이고_그대로_기록된다(tmp_path):
    """출력 위치는 Spec `plan` 항목이고, 파이프라인이 그쪽에 쌓는다."""
    from lintomata.report import write_compare_report

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
    assert compare.collect_target_values(RunResult(), "없음") == {}


# ── 구동 — 값 검증과 **같은 한 벌**로 돈다 (R4-1) ────────────────────────────


def order_fixture(tmp_path: Path, targets: list[str]):
    """`watch` 가 `tick` 보다 **먼저 선언된** 파이프라인.

    정적 topo 정렬은 `seed` 다음 층을 `[watch, tick]` 으로 보고 선언 순서대로 돌려
    `watch` 를 `idle` 상태에서 집는다 → 못 돌아서 **거짓 not run** 이 찍힌다.
    `ready()` 재스캔은 `tick` 이 상태를 민 뒤 `watch` 를 집는다.
    """
    shape = write(tmp_path, "shape.py", SHAPE)
    watch = write(tmp_path, "watch.py", WATCH)
    scoped: dict[str, dict[str, Any]] = {}
    for target in targets:
        detect = write(
            tmp_path, f"detect_{target}.py", DETECT.format(ptype="int", expr="args.params.bump")
        )
        scoped[target] = {"detectScript": str(detect), "bump": 2}

    nodes = [
        {
            "id": "seed",
            "source": node_file(tmp_path, "seed", "${config.detectScript}"),
            "params": {"bump": "${config.bump}"},
        },
        {
            "id": "watch",
            "source": node_file(tmp_path, "watch", str(watch), kind="sense"),
            "inputs": {"input": "seed"},
            "states": {"phase": "active"},
            "when": {"state": "phase"},
        },
        {
            "id": "tick",
            "source": node_file(tmp_path, "tick", str(shape)),
            "inputs": {"input": "seed"},
        },
    ]
    pipeline = build_pipeline(
        nodes,
        targets,
        ["watch"],
        states={"values": ["idle", "active"], "initial": "idle"},
        transitions=[{"after": "tick", "to": "active"}],
    )
    return pipeline, {"targets": scoped}


def test_상태를_기다리는_노드가_먼저_선언돼도_돈다(tmp_path):
    """재현 케이스 ② — 정적 topo 정렬은 여기서 **통과할 노드에 거짓 not run** 을 찍는다."""
    pipeline, config = order_fixture(tmp_path, ["legacy", "v2"])
    result, report = run(pipeline, config, tmp_path)

    assert list(result.outcomes) == ["seed", "tick", "watch"]
    assert assert_four_states(pipeline, result) == {
        "seed": "pass",
        "tick": "pass",
        "watch": "pass",
    }
    # `active` 에서 실제로 돌았다 — 상태를 읽어 그대로 내놓는 노드다.
    assert report.root["watch"].values["legacy"] == {"phase": True}


def test_실행_순서는_simulate_order_와_같다(tmp_path):
    """동시에 실행 가능한 노드는 파이프라인 `nodes` 선언 순서로 돈다 (R3-7).

    `reachability.simulate().order` 가 참조 구현이고 **값 검증도 비교도 그 순서를
    따른다** — 다르게 돌면 "등록은 통과했는데 실행에선 못 닿는다" 가 된다.
    """
    pipeline, config = order_fixture(tmp_path, ["legacy", "v2"])
    expected = reachability.simulate(
        pipeline, {pn.id: dict(pn.states) for pn in pipeline.nodes}
    ).order

    result, _ = run(pipeline, config, tmp_path)
    assert list(result.outcomes) == expected == ["seed", "tick", "watch"]


def test_순수_데이터_DAG_도_선언_순서로_돈다(tmp_path):
    """층 단위 정적 정렬은 `[a, c]` 를 한 층으로 보고 `a, c, b` 를 낸다.
    참조 구현은 `a` 를 돌린 뒤 **재스캔**해서 선언 순서대로 `b` 를 집는다."""
    shape = write(tmp_path, "shape.py", SHAPE)
    scoped: dict[str, dict[str, Any]] = {}
    for target in ("legacy", "v2"):
        detect = write(
            tmp_path, f"detect_{target}.py", DETECT.format(ptype="int", expr="args.params.bump")
        )
        scoped[target] = {"detectScript": str(detect), "bump": 2}

    source = node_file(tmp_path, "seed", "${config.detectScript}")
    nodes = [
        {"id": "a", "source": source, "params": {"bump": "${config.bump}"}},
        {
            "id": "b",
            "source": node_file(tmp_path, "shape", str(shape)),
            "inputs": {"input": "a"},
        },
        {"id": "c", "source": source, "params": {"bump": "${config.bump}"}},
    ]
    pipeline = build_pipeline(nodes, ["legacy", "v2"], ["b"])
    expected = reachability.simulate(
        pipeline, {pn.id: dict(pn.states) for pn in pipeline.nodes}
    ).order

    result, _ = run(pipeline, {"targets": scoped}, tmp_path)
    assert list(result.outcomes) == expected == ["a", "b", "c"]


def test_구간_전이의_중간_상태에서도_노드가_돈다(tmp_path):
    """재현 케이스 ① — 같은 `after` 의 전이 둘은 **구간**이다 (R3-6).

    구간을 통째로 밀면 `loading` 을 기다리던 `watch` 가 통째로 `not_run` 이 된다.
    """
    pipeline, config = order_fixture(tmp_path, ["legacy", "v2"])
    watch = next(pn for pn in pipeline.nodes if pn.id == "watch")
    watch.states = {"phase": "loading"}
    pipeline.states.values = ["idle", "loading", "done"]
    pipeline.transitions = [
        t.model_copy(update={"to": to, "delay": delay})
        for t, to, delay in zip(
            pipeline.transitions * 2, ["loading", "done"], [None, 0]
        )
    ]

    result, _ = run(pipeline, config, tmp_path)
    assert assert_four_states(pipeline, result) == {
        "seed": "pass",
        "tick": "pass",
        "watch": "pass",
    }


# ── 오류와 not run ───────────────────────────────────────────────────────────


def test_한_target_스크립트가_예외면_노드는_오류_뒷단은_not_run(tmp_path):
    """**스크립트 예외는 오류다.** 노드는 한 벌이므로 묶음이 안 차면 비교가 성립하지 않는다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 3}, ["legacy", "v2", "v3"]
    )
    boom = write(tmp_path, "boom.py", BOOM)
    config["targets"]["v3"]["detectScript"] = str(boom)

    result, report = run(pipeline, config, tmp_path)

    assert assert_four_states(pipeline, result) == {
        "detect": "error",
        "shape": "not_run",
    }
    assert "detect" not in report.root and "shape" not in report.root

    not_run = [f for f in result.findings if f.status == "not_run"]
    assert [f.node for f in not_run] == ["shape"]
    assert not_run[0].cause == NotRunCause(node="detect", reason="data_dependency")

    errors = [f for f in result.findings if f.status == "error"]
    assert any("v3" in f.message and "인식 실패" in f.message for f in errors)


def test_not_run_원인은_바로_앞의_막은_노드다(tmp_path):
    """원인은 **자기를 막은 노드**다 — 값 검증과 같은 규칙이어야 한다 (R4-1).

    3단 체인이면 `tail → shape → detect` 로 사슬이 이어져, 각 노드의 원인을 따라가면
    최초 실패 지점에 닿는다. 전부 최초 노드를 가리키게 하면 그 사슬이 사라진다.
    """
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 3, "v2": 3, "v3": 3}, ["legacy", "v2", "v3"]
    )
    tail = write(tmp_path, "tail.py", SHAPE)
    pipeline.nodes.append(
        pipeline.nodes[1].model_copy(
            update={
                "id": "tail",
                "source": node_file(tmp_path, "tail", str(tail)),
                "inputs": {"input": "shape"},
            }
        )
    )
    config["targets"]["legacy"]["detectScript"] = str(write(tmp_path, "boom2.py", BOOM))

    result, _ = run(pipeline, config, tmp_path)
    causes = {f.node: f.cause for f in result.findings if f.status == "not_run"}
    assert causes["shape"] == NotRunCause(node="detect", reason="data_dependency")
    assert causes["tail"] == NotRunCause(node="shape", reason="data_dependency")
    assert assert_four_states(pipeline, result) == {
        "detect": "error",
        "shape": "not_run",
        "tail": "not_run",
    }


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
    phase: bool


@dataclass
class Args:
    state: State


@dataclass
class Seen:
    phase: bool


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
    assert assert_four_states(pipeline, result) == {
        "capture": "error",
        "watch": "not_run",
    }
    cause = next(f.cause for f in result.findings if f.status == "not_run")
    assert cause == NotRunCause(node="capture", reason="state_unreachable")


def test_출력이_선언된_타입과_다르면_오류다(tmp_path):
    """계약 위반은 **오류**다 — 위반이 아니다."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1}, ["legacy", "v2"]
    )
    config["targets"]["legacy"]["detectScript"] = str(
        write(tmp_path, "bad.py", WRONG_OUTPUT)
    )
    result, report = run(pipeline, config, tmp_path)

    assert assert_four_states(pipeline, result) == {
        "detect": "error",
        "shape": "not_run",
    }
    assert report.root == {}
    assert any("[target: legacy]" in f.message for f in result.findings)


def test_script_가_안_풀리면_오류(tmp_path):
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1}, ["legacy", "v2"]
    )
    del config["targets"]["v2"]["detectScript"]
    result, report = run(pipeline, config, tmp_path)

    finding = next(f for f in result.findings if f.rule_id == "LNT-CMP-004")
    assert finding.node == "detect"
    # target 한 벌이 빠지면 비교가 성립하지 않는다 — 뒷단은 not run 이다.
    assert assert_four_states(pipeline, result) == {
        "detect": "error",
        "shape": "not_run",
    }
    assert report.root == {}


# ── 등록소 무결성 — **실행 시점** 규칙이다 (R4-1) ────────────────────────────


def test_등록소_파일이_수정되면_STR_REG_001(tmp_path):
    """등록은 검증 결과를 재사용하는 기제다 — 정적 검사 루트를 피해 파일을 고친
    것을 실행 직전에 잡지 않으면 등록이 아무것도 보장하지 않는다 (`schema.md` 2절)."""
    store = Store(tmp_path / "home")
    shape = write(tmp_path, "shape.py", SHAPE)
    node_path = Path(node_file(tmp_path, "shape", str(shape)))
    entry = store.add("node", node_path)
    store.path_of(entry.id).write_text("{}", encoding="utf-8")

    detects: dict[str, dict[str, Any]] = {}
    for target in ("legacy", "v2"):
        detect = write(
            tmp_path, f"detect_{target}.py", DETECT.format(ptype="int", expr="args.params.bump")
        )
        detects[target] = {"detectScript": str(detect), "bump": 1}

    nodes = [
        {
            "id": "detect",
            "source": node_file(tmp_path, "detect", "${config.detectScript}"),
            "params": {"bump": "${config.bump}"},
        },
        {
            "id": "shape",
            "source": "${ref." + entry.id + "}",
            "inputs": {"input": "detect"},
        },
    ]
    pipeline = build_pipeline(nodes, ["legacy", "v2"], ["detect"])
    result, _ = run(pipeline, {"targets": detects}, tmp_path, store=store)

    assert "LNT-REG-001" in {f.rule_id for f in result.findings}
    assert assert_four_states(pipeline, result)["shape"] == "error"


def test_등록된_스크립트가_수정되면_STR_REG_001(tmp_path):
    """`script` 자리의 `${ref.sc_...}` 도 같은 대조를 받는다 — target 별로 갈리므로
    `${config.X}` 를 편 값을 봐야 한다."""
    store = Store(tmp_path / "home")
    shape = write(tmp_path, "shape.py", SHAPE)
    entry = store.add("script", shape)
    store.path_of(entry.id).write_text(SHAPE + "\n# 몰래 고쳤다\n", encoding="utf-8")

    detects: dict[str, dict[str, Any]] = {}
    for target in ("legacy", "v2"):
        detect = write(
            tmp_path, f"detect_{target}.py", DETECT.format(ptype="int", expr="args.params.bump")
        )
        detects[target] = {
            "detectScript": str(detect),
            "bump": 1,
            "shapeScript": "${ref." + entry.id + "}",
        }

    nodes = [
        {
            "id": "detect",
            "source": node_file(tmp_path, "detect", "${config.detectScript}"),
            "params": {"bump": "${config.bump}"},
        },
        {
            "id": "shape",
            "source": node_file(tmp_path, "shape", "${config.shapeScript}"),
            "inputs": {"input": "detect"},
        },
    ]
    pipeline = build_pipeline(nodes, ["legacy", "v2"], ["detect"])
    result, _ = run(pipeline, {"targets": detects}, tmp_path, store=store)

    assert "LNT-REG-001" in {f.rule_id for f in result.findings}


# ── 규칙 슬롯 — 내 모듈이 내는 규칙 id 가 살아남는가 ─────────────────────────


def test_targets_가_둘_미만이면_STR_CMP_003(tmp_path):
    shape = write(tmp_path, "shape.py", SHAPE)
    pipeline = build_pipeline(
        [{"id": "shape", "source": node_file(tmp_path, "shape", str(shape))}],
        ["legacy"],
        ["shape"],
    )
    result, report = run(pipeline, {}, tmp_path)

    assert [f.rule_id for f in result.findings if f.rule_id] == ["LNT-CMP-003"]
    assert "1" in result.findings[0].message
    assert report.root == {}
    # 돌 수 없었어도 **노드는 리포트에서 사라지지 않는다** (R4-2).
    assert assert_four_states(pipeline, result) == {"shape": "not_run"}


def test_없는_config_는_STR_CMP_004_로_나온다(tmp_path):
    """`targets.<이름>` 에도 공통에도 없다 — `LNT-CONFIG-001` 이 아니다."""
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

    found = [f for f in result.findings if f.rule_id == "LNT-CMP-004"]
    assert [f.node for f in found] == ["shape", "shape"]
    # target 별로 갈리는 것은 **target 별로 나오는 게 정상**이다 (R4-6) —
    # 어느 대상이 잘못됐는지가 메시지에 박혀 있어 dedupe 로 뭉개지지 않는다.
    assert {f.message.splitlines()[0] for f in found} == {
        "현재 target: legacy",
        "현재 target: v2",
    }
    assert "없는값" in found[0].message


def test_배선_오류는_target_수만큼_중복되지_않는다(tmp_path):
    """`Args.input` 은 값 하나다. **배선 판정은 target 과 무관**하므로 한 번만 난다 (R4-6)."""
    pipeline, config = chain_fixture(
        tmp_path, {"legacy": 1, "v2": 1, "v3": 1}, ["legacy", "v2", "v3"]
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

    wiring = [f for f in result.findings if "more than one distinct upstream node" in f.message]
    assert len(wiring) == 1
    assert assert_four_states(pipeline, result)["shape"] == "error"


def test_내가_내는_규칙_전부가_렌더된다():
    """슬롯을 빠뜨리면 `LintomataError` 가 나면서 **규칙 id 가 사라진다.**

    눈으로 읽지 말고 실제로 태워서 확인한다 (Step 1 에서 11건, Step 2 에서 3건).
    """
    from lintomata import rules

    expected = {"LNT-CMP-003": {"count"}, "LNT-CMP-004": {"name"}}
    for rule_id, slots in expected.items():
        assert set(rules.get_rule(rule_id).slots) == slots

    assert rules.finding(
        "LNT-CMP-003", path="p", fields={"count": 1}
    ).rule_id == "LNT-CMP-003"
    assert rules.finding(
        "LNT-CMP-004", path="p", fields={"name": "x"}
    ).rule_id == "LNT-CMP-004"


# ── 잘못된 파이프라인 종류 ───────────────────────────────────────────────────


def test_값_검증_파이프라인을_받으면_오류(tmp_path):
    shape = write(tmp_path, "shape.py", SHAPE)
    raw = {
        "info": {"name": "v", "description": "값 검증", "kind": "verify"},
        "states": {"values": ["idle"], "initial": "idle"},
        "nodes": [{"id": "shape", "source": node_file(tmp_path, "shape", str(shape))}],
    }
    pipeline = Pipeline.model_validate(raw)
    result, report = run(pipeline, {}, tmp_path)

    assert [f.status for f in result.findings] == ["error", "not_run"]
    assert "verify" in result.findings[0].message
    assert report.root == {}


# ── R5-1. `params` 의 `${env.X}` 전개 — 값 검증과 **같은 자리, 같은 순서** ────

READS_FILE = """\
from dataclasses import dataclass


@dataclass
class Params:
    pagePath: str


@dataclass
class Args:
    params: Params


@dataclass
class Buttons:
    count: int
    source: str


def runNode(args: Args) -> Buttons:
    with open(args.params.pagePath, encoding="utf-8") as fp:
        return returnResult(Buttons(count=len(fp.read()), source=args.params.pagePath))
"""


def env_config_fixture(tmp_path: Path):
    """`config` 값이 `${env.DEMO_ROOT}` 를 품고 그 값이 `params` 로 스크립트에 간다."""
    target = write(tmp_path, "home.html", "<main>안녕</main>")
    script = write(tmp_path, "reads.py", READS_FILE)
    nodes = [
        {
            "id": "read",
            "source": node_file(tmp_path, "read", str(script), kind="sense"),
            "params": {"pagePath": "${config.pagePath}"},
        }
    ]
    pipeline = build_pipeline(nodes, ["alpha", "beta"], ["read"])
    config = {"pagePath": "${env.DEMO_ROOT}/home.html"}
    return pipeline, config, target


def test_비교도_config_안의_env_참조를_스크립트까지_전개한다(tmp_path):
    """값 검증만 고치고 여기를 빠뜨리면 **비교에서만** 원문이 스크립트에 간다 (R5-1)."""
    pipeline, config, target = env_config_fixture(tmp_path)
    env = {"HOME": str(tmp_path), "DEMO_ROOT": str(tmp_path)}

    result, report = run(pipeline, config, tmp_path, env=env)

    assert [f for f in result.findings if f.status == "error"] == []
    written = report.model_dump()["read"]
    assert written["same"] is True
    # 스크립트가 **받은 값** 자체가 전개된 절대경로여야 한다.
    assert written["values"]["alpha"]["source"] == str(target)
    assert written["values"]["beta"]["source"] == str(target)
    assert_four_states(pipeline, result)


def test_비교의_params_에_남은_참조도_STR_REF_007_이다(tmp_path):
    pipeline, _config, _target = env_config_fixture(tmp_path)
    env = {"HOME": str(tmp_path), "DEMO_ROOT": str(tmp_path)}

    result, _ = run(pipeline, {"pagePath": "${ref.sc_deadbeef}/x"}, tmp_path, env=env)

    errs = [f for f in result.findings if f.status == "error"]
    assert {f.rule_id for f in errs} == {"LNT-REF-007"}
    assert_four_states(pipeline, result)


# ── 라이브러리 — 값 검증과 **같은 처리** ─────────────────────────────────────


def test_라이브러리를_못_풀면_그_노드는_준비에서_빠진다(tmp_path):
    """★ 한쪽만 고치면 또 갈린다 — `runtime._load_nodes` 와 같은 처리여야 한다.

    못 푼 채로 target 별 스크립트까지 풀어 두면 그 노드가 그대로 실행에 들어가고,
    스크립트가 `ImportError` 로 죽으면서 *"배선이 없습니다"* 라는 **거짓 안내**가
    진짜 원인(파일이 없다) 위에 덮인다.
    """
    script = write(tmp_path, "detect.py", DETECT.format(ptype="int", expr="args.params.bump"))
    path = tmp_path / "detect.json"
    path.write_text(
        json.dumps(
            {
                "info": {"name": "detect-buttons", "description": "버튼 인식"},
                "type": "perceive",
                "script": str(script),
                "libraries": {"buttons": str(tmp_path / "없다.py")},
            }
        ),
        encoding="utf-8",
    )
    pipeline = build_pipeline(
        [{"id": "detectButtons", "source": str(path), "params": {"bump": 1}}],
        ["alpha", "beta"],
        ["detectButtons"],
    )

    prepared, findings = compare._prepare(
        pipeline,
        ["alpha", "beta"],
        {"alpha": {}, "beta": {}},
        store=Store(tmp_path / "home"),
        env={"HOME": str(tmp_path)},
        path="cmp.json",
    )

    assert prepared is not None
    assert "detectButtons" not in prepared.scripts
    broken = [item for item in findings if item.status == "error"]
    assert [item.rule_id for item in broken] == ["LNT-REF-001"]
    # 파이프라인 문맥의 이름은 노드 id 하나다 — `info.name` 은 `detect-buttons` 다.
    assert [item.node for item in broken] == ["detectButtons"]
