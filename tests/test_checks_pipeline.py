"""`checks/pipeline.py` — 파이프라인 로드와 등록 시 검증 (Step 2-b).

**경계를 짚는다.** 특히 이 넷은 구현을 되돌리면 반드시 깨진다:

1. **Action 투명성** — `X→Action→Y` 와 `X→Y` 의 판정이 같아야 한다
2. **순환 검출** — `inputs` 가 엣지이므로 별도 `edges` 없이 잡아야 한다
3. **비교 파이프라인** — `script`·`params` 는 갈려도 되고 input/output/state 는 갈리면 위반.
   **target 이 3개 이상**인 경우까지 본다 (2개만 보면 짝비교 가정이 숨는다)
4. **`Finding.rule_id`** — 슬롯을 빠뜨리면 `rules.finding()` 이 터지며 규칙 id 가 사라진다
"""

from __future__ import annotations

import json

import pytest

from strictler import rules
from strictler.checks import pipeline as pipe
from strictler.model import Pipeline
from strictler.store.entries import Store
from tests._fakes import ScriptStub, contract, stub_reachability


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(home=tmp_path / "home")


def ids(findings) -> list[str]:
    return [item.rule_id for item in findings]


def make(**over) -> Pipeline:
    """최소 파이프라인 하나. 필요한 부분만 덮어쓴다."""
    base: dict = {
        "info": {"name": "p", "description": "설명", "kind": "verify"},
        "states": {"values": ["idle"], "initial": "idle"},
        "nodes": [],
    }
    base.update(over)
    return Pipeline.model_validate(base)


def n(node_id: str, *, inputs=None, states=None, when=None, source="/abs/n.json") -> dict:
    item: dict = {"id": node_id, "source": source}
    if inputs:
        item["inputs"] = inputs
    if states:
        item["states"] = states
    if when:
        item["when"] = {"state": when}
    return item


# ── load_pipeline / build_dag ────────────────────────────────────────────────


def test_load_pipeline_rejects_unknown_key():
    loaded, findings = pipe.load_pipeline(
        {
            "info": {"name": "p", "description": "d", "kind": "verify"},
            "states": {"values": ["idle"], "initial": "idle"},
            "nodes": [],
            "edges": [],
        },
        "p.json",
    )
    assert loaded is None
    assert ids(findings) == [""]
    assert "edges" in findings[0].message


def test_build_dag_takes_edges_from_inputs_only():
    """별도 `edges` 섹션이 없다 — 입력 참조가 곧 의존 관계다."""
    dag = pipe.build_dag(
        make(
            nodes=[
                n("page"),
                n("html", inputs={"scene": "page"}),
                n("form", inputs={"a": "html", "b": "html"}),
            ]
        )
    )
    assert dag == {"page": [], "html": ["page"], "form": ["html"]}


# ── check_cycle / orphan ─────────────────────────────────────────────────────


def test_check_cycle_reports_the_loop_path():
    findings = pipe.check_cycle({"a": ["b"], "b": ["a"]}, "p.json")
    assert ids(findings) == ["STR-GRAPH-001"]
    assert "→" in findings[0].message


def test_check_cycle_reports_self_loop():
    findings = pipe.check_cycle({"a": ["a"]}, "p.json")
    assert ids(findings) == ["STR-GRAPH-001"]


def test_check_cycle_reports_each_loop_once():
    """같은 순환을 진입점마다 다시 내면 리포트가 부풀어 원인이 묻힌다."""
    findings = pipe.check_cycle({"a": ["b"], "b": ["c"], "c": ["a"]}, "p.json")
    assert ids(findings) == ["STR-GRAPH-001"]


def test_orphan_node_is_reported():
    findings = pipe.check_cycle({"a": [], "b": ["a"], "lonely": []}, "p.json")
    assert ids(findings) == ["STR-GRAPH-002"]
    assert findings[0].node == "lonely"


def test_single_node_pipeline_is_not_orphan():
    """그 하나가 그래프 전체다 — "연결하거나 제거하세요" 가 성립하지 않는다."""
    assert pipe.check_cycle({"only": []}, "p.json") == []


def test_transition_driver_is_not_orphan():
    """`transitions.after` 로 상태를 미는 노드는 데이터를 안 내놓아도 제 몫을 한다."""
    findings = pipe.check_cycle(
        {"a": [], "b": ["a"], "tick": []}, "p.json", exempt={"tick"}
    )
    assert findings == []


# ── check_wiring_types ───────────────────────────────────────────────────────


def wired(nodes, contracts, node_types=None):
    registry, findings = pipe.build_registry(list(contracts.values()), "p.json")
    assert findings == [] and registry is not None
    return pipe.check_wiring_types(
        make(nodes=nodes), contracts, registry, "p.json", node_types=node_types
    )


def test_wiring_passes_when_definitions_match():
    contracts = {
        "x": contract("x.py", output_fields={"count": "int"}),
        "y": contract("y.py", input_fields={"count": "int"}, output_fields={"ok": "bool"}),
    }
    assert wired([n("x"), n("y", inputs={"v": "x"})], contracts) == []


def test_wiring_matches_structurally_not_by_name():
    """이름이 달라도 구조가 같으면 같은 타입이다 (`schema.md` 7절)."""
    contracts = {
        "x": contract("x.py", output_fields={"count": "int"}, output_name="ButtonCount"),
        "y": contract("y.py", input_fields={"count": "int"}, input_name="MenuCount"),
    }
    assert wired([n("x"), n("y", inputs={"v": "x"})], contracts) == []


def test_wiring_is_strict_equality_not_subset():
    """부분집합 병합은 **표현 층에서만** 일어난다. 그래프 검사는 엄격한 동일성이다."""
    contracts = {
        "x": contract("x.py", output_fields={"count": "int"}),
        "y": contract("y.py", input_fields={"count": "int", "label": "str"}),
    }
    findings = wired([n("x"), n("y", inputs={"v": "x"})], contracts)
    assert ids(findings) == ["STR-TYPE-004"]
    assert findings[0].node == "y"


def test_wiring_reports_missing_declaration():
    contracts = {
        "x": contract("x.py"),  # output 선언 없음
        "y": contract("y.py", input_fields={"count": "int"}),
    }
    findings = wired([n("x"), n("y", inputs={"v": "x"})], contracts)
    assert ids(findings) == ["STR-TYPE-004"]
    assert "선언 없음" in findings[0].message


def test_action_is_transparent_verdict_is_identical_with_and_without_it():
    """★ `X ──▶ Action ──▶ Y` 와 `X ──▶ Y` 의 판정이 **같아야** 한다.

    Action 자신의 선언은 대조에 끼지 않는다 — 끼면 "어디에나 끼워 넣는다" 가
    타입 체계와 충돌한다.
    """
    x = contract("x.py", output_fields={"count": "int"})
    y = contract("y.py", input_fields={"count": "int"})
    click = contract("click.py", input_fields={"count": "int"}, output_fields={"count": "int"})

    direct = wired([n("x"), n("y", inputs={"v": "x"})], {"x": x, "y": y})
    through = wired(
        [n("x"), n("click", inputs={"v": "x"}), n("y", inputs={"v": "click"})],
        {"x": x, "click": click, "y": y},
        node_types={"x": "sense", "click": "action", "y": "reckon"},
    )
    assert direct == through == []


def test_action_transparency_does_not_hide_a_real_mismatch():
    x = contract("x.py", output_fields={"count": "int"})
    y = contract("y.py", input_fields={"label": "str"})
    click = contract("click.py", input_fields={"count": "int"}, output_fields={"count": "int"})

    direct = wired([n("x"), n("y", inputs={"v": "x"})], {"x": x, "y": y})
    through = wired(
        [n("x"), n("click", inputs={"v": "x"}), n("y", inputs={"v": "click"})],
        {"x": x, "click": click, "y": y},
        node_types={"x": "sense", "click": "action", "y": "reckon"},
    )
    assert ids(direct) == ids(through) == ["STR-TYPE-004"]


def test_action_transparency_holds_without_node_types_for_a_valid_action():
    """`node_types` 를 못 받아도 판정이 달라지면 안 된다.

    올바른 Action 은 `input == output`(`STR-CONTRACT-006`)이므로 건너뛰든
    엣지를 그대로 대조하든 결론이 같다.
    """
    x = contract("x.py", output_fields={"count": "int"})
    y = contract("y.py", input_fields={"count": "int"})
    click = contract("click.py", input_fields={"count": "int"}, output_fields={"count": "int"})
    nodes = [n("x"), n("click", inputs={"v": "x"}), n("y", inputs={"v": "click"})]
    contracts = {"x": x, "click": click, "y": y}

    assert wired(nodes, contracts) == []
    assert wired(nodes, contracts, node_types={"click": "action"}) == []


def test_action_chain_is_skipped_all_the_way_up():
    x = contract("x.py", output_fields={"count": "int"})
    y = contract("y.py", input_fields={"count": "int"})
    # 중간 Action 들이 **엉뚱한 타입**을 선언해도 상·하단 계약이 맞으면 통과다.
    a1 = contract("a1.py", output_fields={"junk": "str"})
    a2 = contract("a2.py", output_fields={"junk": "str"})
    findings = wired(
        [
            n("x"),
            n("a1", inputs={"v": "x"}),
            n("a2", inputs={"v": "a1"}),
            n("y", inputs={"v": "a2"}),
        ],
        {"x": x, "a1": a1, "a2": a2, "y": y},
        node_types={"x": "sense", "a1": "action", "a2": "action", "y": "reckon"},
    )
    assert findings == []


# ── 상태 ─────────────────────────────────────────────────────────────────────


def test_state_mapping_missing_is_state_002():
    contracts = {"cap": contract("c.py", state_fields={"stop": "bool"})}
    findings = pipe.check_state_mapping(
        make(
            states={"values": ["idle", "settled"], "initial": "idle"},
            nodes=[n("cap")],
        ),
        contracts,
        "p.json",
    )
    assert ids(findings) == ["STR-STATE-002"]
    assert "stop" in findings[0].message


def test_mapped_state_not_in_values_is_state_003():
    contracts = {"cap": contract("c.py", state_fields={"stop": "bool"})}
    findings = pipe.check_state_mapping(
        make(
            states={"values": ["idle"], "initial": "idle"},
            nodes=[n("cap", states={"stop": "settled"})],
        ),
        contracts,
        "p.json",
    )
    assert ids(findings) == ["STR-STATE-003"]


def test_when_referencing_undeclared_state_is_state_004():
    """`when` 은 **노드 자기 어휘**로 쓴다 — 스크립트가 선언한 이름이어야 한다."""
    contracts = {"cap": contract("c.py", state_fields={"stop": "bool"})}
    findings = pipe.check_state_mapping(
        make(
            states={"values": ["idle", "settled"], "initial": "idle"},
            nodes=[n("cap", states={"stop": "settled"}, when="halt")],
        ),
        contracts,
        "p.json",
    )
    assert ids(findings) == ["STR-STATE-004"]


def test_reserved_prefix_in_state_values_is_state_001():
    findings = pipe.check_state_mapping(
        make(states={"values": ["idle", "__startedAt"], "initial": "idle"}), {}, "p.json"
    )
    assert ids(findings) == ["STR-STATE-001"]


def test_initial_state_outside_values_is_reported():
    findings = pipe.check_state_mapping(
        make(states={"values": ["idle"], "initial": "nowhere"}), {}, "p.json"
    )
    # 대응 규칙이 `rules.md` 에 없다 — 그래도 조용히 통과시키지 않는다.
    assert ids(findings) == [""]
    assert "initial" in findings[0].message


def test_mapping_complete_and_known_passes():
    contracts = {"cap": contract("c.py", state_fields={"stop": "bool"})}
    assert (
        pipe.check_state_mapping(
            make(
                states={"values": ["idle", "settled"], "initial": "idle"},
                nodes=[n("cap", states={"stop": "settled"}, when="stop")],
            ),
            contracts,
            "p.json",
        )
        == []
    )


def test_transitions_check_both_names():
    findings = pipe.check_transitions(
        make(
            states={"values": ["idle"], "initial": "idle"},
            nodes=[n("a")],
            transitions=[{"after": "ghost", "to": "nowhere"}],
        ),
        "p.json",
    )
    assert ids(findings) == ["STR-REF-004", "STR-STATE-005"]


def test_transitions_only_carry_time():
    """`delay` 는 받아도 조건 표현식 같은 것은 스키마에 자리가 없다."""
    findings = pipe.check_transitions(
        make(
            states={"values": ["idle", "settled"], "initial": "idle"},
            nodes=[n("submit")],
            transitions=[{"after": "submit", "to": "settled", "delay": "${config.settleMs}"}],
        ),
        "p.json",
    )
    assert findings == []


# ── config ───────────────────────────────────────────────────────────────────


def test_config_decl_type_must_be_primitive_vocabulary():
    findings = pipe.check_config_decls(
        make(
            config={
                "ok": {"type": "list[str]", "required": True},
                "bad": {"type": "dict", "required": True},
                "alsoBad": {"type": "Button", "required": False},
            }
        ),
        "p.json",
    )
    assert ids(findings) == ["STR-TYPE-005", "STR-TYPE-005"]
    assert {item.node for item in findings} == {"bad", "alsoBad"}


def test_config_values_inject_defaults_before_refs_sees_them():
    """★ R1-6 — `refs.expand_config` 가 받는 config 는 **이미 default 가 채워진 것**이다.

    그래야 거기서 못 찾은 `${config.X}` 가 진짜 required 누락이 된다.
    """
    resolved, findings = pipe.check_config_values(
        make(
            config={
                "settleMs": {"type": "int", "required": False, "default": 2000},
                "url": {"type": "str", "required": True},
            }
        ),
        {"url": "https://x"},
        "p.json",
        env={},
    )
    assert findings == []
    assert resolved == {"settleMs": 2000, "url": "https://x"}


def test_config_required_missing_is_config_001():
    _, findings = pipe.check_config_values(
        make(config={"url": {"type": "str", "required": True}}), {}, "p.json", env={}
    )
    assert ids(findings) == ["STR-CONFIG-001"]
    assert "url" in findings[0].message


def test_config_type_mismatch_is_config_002_and_bool_is_not_int():
    _, findings = pipe.check_config_values(
        make(
            config={
                "count": {"type": "int", "required": True},
                "flag": {"type": "int", "required": True},
            }
        ),
        {"count": "3", "flag": True},
        "p.json",
        env={},
    )
    assert ids(findings) == ["STR-CONFIG-002", "STR-CONFIG-002"]


def test_config_unknown_key_is_config_003():
    _, findings = pipe.check_config_values(
        make(config={"url": {"type": "str", "required": True}}),
        {"url": "https://x", "typo": 1},
        "p.json",
        env={},
    )
    assert ids(findings) == ["STR-CONFIG-003"]


def test_config_path_true_enforces_path_rule(tmp_path):
    """★ R1-6 — `STR-PATH-004` 는 여기서 낸다. `refs` 는 기제만 제공한다."""
    decls = {"script": {"type": "str", "required": True, "path": True}}
    _, bad = pipe.check_config_values(
        make(config=decls), {"script": "./rel.py"}, "p.json", env={}
    )
    _, good = pipe.check_config_values(
        make(config=decls), {"script": str(tmp_path / "a.py")}, "p.json", env={}
    )
    assert ids(bad) == ["STR-PATH-004"]
    assert "절대경로" in bad[0].message
    assert good == []


def test_config_path_true_not_applied_when_flag_absent():
    """`path` 는 타입이 아니라 **검증 속성**이다 — 안 켜면 안 본다."""
    _, findings = pipe.check_config_values(
        make(config={"label": {"type": "str", "required": True}}),
        {"label": "./rel.py"},
        "p.json",
        env={},
    )
    assert findings == []


def test_config_required_may_live_only_in_every_target_scope():
    """target 별로 갈리는 값이 바로 그 자리다 (`schema.md` 12절)."""
    pipeline = make(
        info={"name": "p", "description": "d", "kind": "compare"},
        config={"buttonScript": {"type": "str", "required": True}},
        targets=["legacy", "v2", "v3"],
    )
    _, filled = pipe.check_config_values(
        pipeline,
        {"targets": {t: {"buttonScript": f"/abs/{t}.py"} for t in ("legacy", "v2", "v3")}},
        "p.json",
        env={},
    )
    _, hole = pipe.check_config_values(
        pipeline,
        {"targets": {"legacy": {"buttonScript": "/abs/l.py"}, "v2": {}, "v3": {}}},
        "p.json",
        env={},
    )
    assert filled == []
    assert ids(hole) == ["STR-CONFIG-001"]


# ── 비교 파이프라인 ──────────────────────────────────────────────────────────


def compare_pipeline(**over) -> Pipeline:
    base: dict = {
        "info": {"name": "cmp", "description": "d", "kind": "compare"},
        "states": {"values": ["idle"], "initial": "idle"},
        "nodes": [n("detectButtons")],
        "targets": ["legacy", "v2", "v3"],
        "compare": ["detectButtons"],
    }
    base.update(over)
    return Pipeline.model_validate(base)


def test_compare_allows_script_and_params_to_differ_per_target():
    """★ target 별로 갈려도 되는 것은 **스크립트 경로와 `params` 뿐**이다."""
    by_target = {
        "legacy": {
            "detectButtons": contract(
                "legacy.py",
                input_fields={"html": "str"},
                output_fields={"count": "int"},
                params_fields={"classPrefix": "str"},
            )
        },
        "v2": {
            "detectButtons": contract(
                "v2.py",
                input_fields={"html": "str"},
                output_fields={"count": "int"},
                params_fields={"roleAttr": "str"},
            )
        },
        "v3": {
            "detectButtons": contract(
                "v3.py",
                input_fields={"html": "str"},
                output_fields={"count": "int"},
                params_fields={"roleAttr": "str", "depth": "int"},
            )
        },
    }
    assert pipe.check_compare(compare_pipeline(), by_target, "p.json") == []


def test_compare_allows_two_targets_to_share_one_script():
    """`schema.md` 12절이 명시하는 형태 — `canary` 가 `v3` 의 스크립트를 그대로 쓴다."""
    shared = contract("v3.py", input_fields={"html": "str"}, output_fields={"count": "int"})
    by_target = {
        "legacy": {"detectButtons": contract("l.py", input_fields={"html": "str"}, output_fields={"count": "int"})},
        "v3": {"detectButtons": shared},
        "canary": {"detectButtons": shared},
    }
    pipeline = compare_pipeline(targets=["legacy", "v3", "canary"])
    assert pipe.check_compare(pipeline, by_target, "p.json") == []


def test_compare_node_without_consumers_is_not_orphan():
    """비교 대상 노드는 출력을 **엔진이** 가져간다 — 뒷단이 없어도 고립이 아니다."""
    findings = pipe.check_cycle(
        {"capture": [], "detectButtons": ["capture"], "extractMenu": ["capture"]},
        "p.json",
        exempt={"detectButtons", "extractMenu"},
    )
    assert findings == []


def test_compare_flags_output_type_divergence_in_the_third_target():
    """★ target 이 셋 이상 — **목록 전부가 같은지**를 묻는다. 짝비교가 아니다."""
    by_target = {
        "legacy": {"detectButtons": contract("l.py", input_fields={"html": "str"}, output_fields={"count": "int"})},
        "v2": {"detectButtons": contract("v2.py", input_fields={"html": "str"}, output_fields={"count": "int"})},
        "v3": {"detectButtons": contract("v3.py", input_fields={"html": "str"}, output_fields={"count": "str"})},
    }
    findings = pipe.check_compare(compare_pipeline(), by_target, "p.json")
    assert ids(findings) == ["STR-CMP-002"]
    assert findings[0].node == "detectButtons"


def test_compare_flags_state_divergence():
    by_target = {
        "legacy": {"detectButtons": contract("l.py", output_fields={"c": "int"}, state_fields={"stop": "bool"})},
        "v2": {"detectButtons": contract("v2.py", output_fields={"c": "int"}, state_fields={"stop": "bool"})},
        "v3": {"detectButtons": contract("v3.py", output_fields={"c": "int"}, state_fields={"halt": "bool"})},
    }
    findings = pipe.check_compare(compare_pipeline(), by_target, "p.json")
    assert ids(findings) == ["STR-CMP-002"]


def test_compare_reports_one_finding_per_node_not_per_pair():
    """짝마다 내면 target 이 열이면 아홉 줄이 쌓인다 — 원인은 하나다."""
    diverging = {
        t: {"detectButtons": contract(f"{t}.py", output_fields={"c": "int" if i == 0 else "str"})}
        for i, t in enumerate(("legacy", "v2", "v3"))
    }
    findings = pipe.check_compare(compare_pipeline(), diverging, "p.json")
    assert ids(findings) == ["STR-CMP-002"]


def test_compare_needs_at_least_two_targets():
    findings = pipe.check_compare(compare_pipeline(targets=["legacy"]), {}, "p.json")
    assert ids(findings) == ["STR-CMP-003"]


def test_compare_node_must_exist():
    findings = pipe.check_compare(
        compare_pipeline(compare=["detectButtons", "ghost"]), {}, "p.json"
    )
    assert ids(findings) == ["STR-REF-005"]


def test_verify_pipeline_must_not_carry_compare_sections():
    findings = pipe.check_compare(make(targets=["a", "b"]), {}, "p.json")
    assert ids(findings) == [""]
    assert "kind" in findings[0].message


# ── check_pipeline 통합 ──────────────────────────────────────────────────────


def build_project(tmp_path, monkeypatch, *, wiring_ok=True):
    """디스크에 실제 노드 JSON·스크립트를 깔고 계약만 대역으로 심는다."""
    stub = ScriptStub()
    scripts = {}
    for name in ("capture", "detect"):
        src = tmp_path / f"{name}.py"
        src.write_text("def runNode(args): ...\n", encoding="utf-8")
        scripts[name] = src

    stub.put(
        str(scripts["capture"]), contract(str(scripts["capture"]), output_fields={"html": "str"})
    )
    stub.put(
        str(scripts["detect"]),
        contract(
            str(scripts["detect"]),
            input_fields={"html": "str" if wiring_ok else "int"},
            output_fields={"count": "int"},
        ),
    )
    stub.install(monkeypatch)
    stub_reachability(monkeypatch)

    node_files = {}
    for name, kind in (("capture", "sense"), ("detect", "perceive")):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "info": {"name": name, "description": "d"},
                    "type": kind,
                    "script": str(scripts[name]),
                }
            ),
            encoding="utf-8",
        )
        node_files[name] = path
    return node_files


def test_check_pipeline_end_to_end_passes(tmp_path, monkeypatch, store):
    files = build_project(tmp_path, monkeypatch)
    pipeline = make(
        nodes=[
            n("capture", source=str(files["capture"])),
            n("detect", inputs={"html": "capture"}, source=str(files["detect"])),
        ]
    )
    contracts, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert findings == []
    assert set(contracts) == {"capture", "detect"}


def test_check_pipeline_catches_wiring_mismatch_end_to_end(tmp_path, monkeypatch, store):
    files = build_project(tmp_path, monkeypatch, wiring_ok=False)
    pipeline = make(
        nodes=[
            n("capture", source=str(files["capture"])),
            n("detect", inputs={"html": "capture"}, source=str(files["detect"])),
        ]
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert ids(findings) == ["STR-TYPE-004"]


def test_check_pipeline_reports_unknown_input_node(tmp_path, monkeypatch, store):
    files = build_project(tmp_path, monkeypatch)
    pipeline = make(
        nodes=[
            n("capture", source=str(files["capture"])),
            n("detect", inputs={"html": "ghost"}, source=str(files["detect"])),
        ]
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert "STR-REF-003" in ids(findings)


def test_check_pipeline_reports_missing_node_file(tmp_path, monkeypatch, store):
    build_project(tmp_path, monkeypatch)
    pipeline = make(nodes=[n("ghost", source=str(tmp_path / "nope.json"))])
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert ids(findings) == ["STR-REF-002"]


def test_check_pipeline_reports_unregistered_node_ref(tmp_path, monkeypatch, store):
    build_project(tmp_path, monkeypatch)
    pipeline = make(nodes=[n("x", source="${ref.nd_deadbeef}")])
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert ids(findings) == ["STR-REG-002"]


def test_check_pipeline_keeps_checking_after_one_node_breaks(tmp_path, monkeypatch, store):
    """실패는 최대한 모은다 — 한 노드가 깨져도 나머지는 전부 돈다."""
    files = build_project(tmp_path, monkeypatch)
    pipeline = make(
        states={"values": ["idle"], "initial": "nowhere"},
        nodes=[
            n("capture", source=str(files["capture"])),
            n("broken", source=str(tmp_path / "gone.json")),
        ],
        transitions=[{"after": "ghost", "to": "idle"}],
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert "STR-REF-002" in ids(findings)
    assert "STR-REF-004" in ids(findings)


def test_check_pipeline_duplicate_node_id_is_reported(tmp_path, monkeypatch, store):
    files = build_project(tmp_path, monkeypatch)
    pipeline = make(
        nodes=[
            n("same", source=str(files["capture"])),
            n("same", source=str(files["detect"])),
        ]
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert any("중복" in item.message for item in findings)


def test_check_pipeline_gathers_target_contracts_when_they_resolve(
    tmp_path, monkeypatch, store
):
    """★ 노드도 그래프도 **한 벌**이다 — target 별로 갈리는 것은 스크립트와 그 값뿐.

    등록 시점에 알 수 있는 값은 파이프라인이 선언한 `default` 뿐이므로, 그걸로
    세 스크립트가 전부 풀릴 때에만 `STR-CMP-002` 를 판정한다.
    셋 중 **하나만** 어긋나도 위반이다 — 짝지어 비교하는 것이 아니다.
    """
    stub = ScriptStub()
    scripts = {}
    for target, out in (("legacy", "int"), ("v2", "int"), ("v3", "str")):
        src = tmp_path / f"{target}_buttons.py"
        src.write_text("def runNode(args): ...\n", encoding="utf-8")
        stub.put(str(src), contract(str(src), output_fields={"count": out}))
        scripts[target] = src
    stub.install(monkeypatch)
    stub_reachability(monkeypatch)

    node_file = tmp_path / "detect.json"
    node_file.write_text(
        json.dumps(
            {
                "info": {"name": "detect", "description": "d"},
                "type": "perceive",
                "script": "${config.buttonScript}",
            }
        ),
        encoding="utf-8",
    )

    pipeline = Pipeline.model_validate(
        {
            "info": {"name": "cmp", "description": "d", "kind": "compare"},
            "states": {"values": ["idle"], "initial": "idle"},
            # `${config.X}` 는 `targets.<현재 target>` 을 먼저 본다 (`schema.md` 12절).
            "config": {
                "targets": {
                    "type": "str",
                    "required": False,
                    "default": {t: {"buttonScript": str(p)} for t, p in scripts.items()},
                }
            },
            "nodes": [n("detectButtons", source=str(node_file))],
            "targets": ["legacy", "v2", "v3"],
            "compare": ["detectButtons"],
        }
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert ids(findings) == ["STR-CMP-002"]


def test_check_pipeline_defers_unresolvable_target_scripts_without_complaining(
    tmp_path, monkeypatch, store
):
    """Spec 이 채울 값은 등록 시점에 알 수 없다 — **오류가 아니라 "아직 모름"** 이다.

    여기서 억지로 전개하면 정상적인 비교 파이프라인이 등록조차 안 된다.
    """
    ScriptStub().install(monkeypatch)
    stub_reachability(monkeypatch)

    node_file = tmp_path / "detect.json"
    node_file.write_text(
        json.dumps(
            {
                "info": {"name": "detect", "description": "d"},
                "type": "perceive",
                "script": "${config.buttonScript}",
            }
        ),
        encoding="utf-8",
    )
    pipeline = Pipeline.model_validate(
        {
            "info": {"name": "cmp", "description": "d", "kind": "compare"},
            "states": {"values": ["idle"], "initial": "idle"},
            "config": {"buttonScript": {"type": "str", "required": True, "path": True}},
            "nodes": [n("detectButtons", source=str(node_file))],
            "targets": ["legacy", "v2", "v3"],
            "compare": ["detectButtons"],
        }
    )
    _, findings = pipe.check_pipeline(pipeline, "p.json", store=store, env={})
    assert findings == []


# ── 슬롯 계약 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule_id, fields",
    [
        ("STR-REF-002", {"source": "s"}),
        ("STR-REF-003", {"name": "x"}),
        ("STR-REF-004", {"name": "x"}),
        ("STR-REF-005", {"name": "x"}),
        ("STR-GRAPH-001", {"cycle": "a → a"}),
        ("STR-GRAPH-002", {"name": "x"}),
        ("STR-TYPE-004", {"out": "a", "in": "b"}),
        ("STR-TYPE-005", {"type": "dict"}),
        ("STR-STATE-001", {"name": "__x"}),
        ("STR-STATE-002", {"names": "stop"}),
        ("STR-STATE-003", {"name": "s"}),
        ("STR-STATE-004", {"name": "s"}),
        ("STR-STATE-005", {"name": "s"}),
        ("STR-CONFIG-001", {"names": "url"}),
        ("STR-CONFIG-002", {"name": "n", "declared": "int", "given": "'x'"}),
        ("STR-CONFIG-003", {"name": "typo"}),
        ("STR-CMP-002", {"node": "detect"}),
        ("STR-CMP-003", {"count": 1}),
        ("STR-PATH-004", {"name": "s", "value": "'./x'"}),
        ("STR-REG-002", {"id": "nd_x"}),
    ],
)
def test_this_module_supplies_every_slot_each_rule_declares(rule_id, fields):
    """★ 이 모듈이 쓰는 규칙마다 `Rule.slots` 를 하나도 안 빠뜨렸는지.

    슬롯이 비면 `rules.finding()` 이 `StrictlerError` 를 내면서 **원래 나와야 할
    규칙 id 가 사라진다** — 리포트가 원인을 못 짚게 된다. 위 테스트들이 실제
    오류 경로를 태워 `rule_id` 를 단언하고, 여기서는 슬롯 집합 자체를 못 박는다.
    """
    assert set(rules.get_rule(rule_id).slots) == set(fields)
    made = rules.finding(rule_id, fields=fields)
    assert made.rule_id == rule_id
    assert "{" not in made.message.replace("${", "")
