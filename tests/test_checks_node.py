"""`checks/node.py` — 노드 JSON 로드와 등록 시 검증 (Step 2-b).

**경계를 짚는다.** 구현을 되돌리면 깨지는 것만 쓴다:

- `${config.X}` 인 `script` 는 오류가 **아니다** (비교 노드의 정상 형태)
- `${ref.pl_...}` 를 스크립트 자리에 쓰면 `STR-REG-003`
- 노드 타입이 **실제로** `check_script` 로 넘어가는가
- **모든 오류 경로의 `Finding.rule_id` 가 기대값인가** — 슬롯을 빠뜨리면
  `rules.finding()` 이 `StrictlerError` 를 내면서 규칙 id 가 통째로 사라진다.
  이 단언이 곧 슬롯 계약 검증이다 (Step 1 통합 사고의 원인).
"""

from __future__ import annotations

import json

import pytest

from strictler import checks, rules
from strictler.checks import node as node_checks
from strictler.errors import StrictlerError
from strictler.model import Node
from strictler.store.entries import Store
from tests._fakes import FakeContract, ScriptStub, contract, stub_reachability


@pytest.fixture()
def store(tmp_path) -> Store:
    return Store(home=tmp_path / "home")


def node_of(script: str, *, kind: str = "perceive", name: str = "detect-buttons") -> Node:
    return Node.model_validate(
        {
            "info": {"name": name, "description": "무엇이 버튼인지 판정한다"},
            "type": kind,
            "script": script,
        }
    )


def ids(findings) -> list[str]:
    return [item.rule_id for item in findings]


# ── load_node ────────────────────────────────────────────────────────────────


def test_load_node_reads_the_three_fields():
    node, findings = node_checks.load_node(
        {
            "info": {"name": "detect", "description": "설명"},
            "type": "reckon",
            "script": "/abs/x.py",
        },
        "n.json",
    )
    assert findings == []
    assert node is not None
    assert (node.info.name, node.type, node.script) == ("detect", "reckon", "/abs/x.py")


def test_load_node_rejects_unknown_key_and_unknown_type():
    node, findings = node_checks.load_node(
        {
            "info": {"name": "detect", "description": "설명"},
            "type": "sniff",
            "script": "/abs/x.py",
            "extra": 1,
        },
        "n.json",
    )
    assert node is None
    # 두 결함이 각각 하나씩 — 하나로 뭉치면 AI 가 어디를 고칠지 모른다.
    assert len(findings) == 2
    assert {item.path for item in findings} == {"n.json"}
    assert all(item.status == "error" for item in findings)
    # 스키마 형태 오류에는 대응하는 규칙이 없다 (`rules.md` 에 자리가 없다).
    assert ids(findings) == ["", ""]


# ── resolve_script ───────────────────────────────────────────────────────────


def test_resolve_script_finds_registered_script(store, tmp_path):
    src = tmp_path / "detect.py"
    src.write_text("def runNode(args): ...\n", encoding="utf-8")
    entry = store.add("script", src, name="detect")

    path, findings = node_checks.resolve_script(
        node_of(f"${{ref.{entry.id}}}"), store=store, env={}
    )
    assert findings == []
    assert path == store.path_of(entry.id)


def test_resolve_script_unknown_ref_is_reg_002(store):
    path, findings = node_checks.resolve_script(
        node_of("${ref.sc_deadbeef}"), store=store, env={}
    )
    assert path is None
    assert ids(findings) == ["STR-REG-002"]
    assert "sc_deadbeef" in findings[0].message


def test_resolve_script_wrong_prefix_is_reg_003(store):
    """스크립트 자리에 파이프라인 id 를 쓰면 **자리와 접두가 어긋난 것**이다."""
    path, findings = node_checks.resolve_script(
        node_of("${ref.pl_c9d0e1f2}"), store=store, env={}
    )
    assert path is None
    assert ids(findings) == ["STR-REG-003"]


def test_resolve_script_relative_path_is_path_001(store):
    path, findings = node_checks.resolve_script(
        node_of("./scripts/detect.py"), store=store, env={}
    )
    assert path is None
    assert ids(findings) == ["STR-PATH-001"]


def test_resolve_script_undefined_env_is_path_002(store):
    path, findings = node_checks.resolve_script(
        node_of("${env.PROJECT_ROOT}/detect.py"), store=store, env={}
    )
    assert path is None
    assert ids(findings) == ["STR-PATH-002"]


def test_resolve_script_missing_file_is_ref_001(store, tmp_path):
    path, findings = node_checks.resolve_script(
        node_of(str(tmp_path / "nope.py")), store=store, env={}
    )
    assert path is None
    assert ids(findings) == ["STR-REF-001"]


def test_resolve_script_defers_unfilled_config_reference(store):
    """`${config.buttonScript}` 는 비교 노드의 **정상 형태**다 — 오류가 아니다.

    Spec 이 채우는 값이라 노드 등록 시점엔 어느 파일인지 알 수 없다.
    억지로 전개하면 `STR-REF-007` 이 나면서 정상적인 노드를 등록조차 못 하게 된다.
    """
    path, findings = node_checks.resolve_script(
        node_of("${config.buttonScript}"), store=store, env={}
    )
    assert (path, findings) == (None, [])


def test_resolve_script_uses_target_scope_first(store, tmp_path):
    legacy = tmp_path / "legacy.py"
    v2 = tmp_path / "v2.py"
    for f in (legacy, v2):
        f.write_text("x = 1\n", encoding="utf-8")
    config = {"targets": {"legacy": {"s": str(legacy)}, "v2": {"s": str(v2)}}}

    got_legacy, _ = node_checks.resolve_script(
        node_of("${config.s}"), store=store, env={}, config=config, target="legacy"
    )
    got_v2, _ = node_checks.resolve_script(
        node_of("${config.s}"), store=store, env={}, config=config, target="v2"
    )
    assert (got_legacy, got_v2) == (legacy, v2)


def test_resolve_script_missing_target_config_is_cmp_004(store):
    path, findings = node_checks.resolve_script(
        node_of("${config.s}"), store=store, env={}, config={}, target="v3"
    )
    assert path is None
    assert ids(findings) == ["STR-CMP-004"]


# ── check_node ───────────────────────────────────────────────────────────────


def test_check_node_passes_node_type_to_script_checker(store, tmp_path, monkeypatch):
    """노드 타입별로 갈리는 검사(Reckon 기댓값·Action 투명성)의 유일한 통로다."""
    src = tmp_path / "judge.py"
    src.write_text("def runNode(args): ...\n", encoding="utf-8")
    stub = ScriptStub()
    stub.put(str(src), FakeContract(str(src), output_type="Verdict"))
    stub.install(monkeypatch)

    contract, findings = node_checks.check_node(
        node_of(str(src), kind="reckon"), "judge.json", store=store, env={}
    )
    assert findings == []
    assert contract is not None and contract.output_type == "Verdict"
    assert stub.seen_types == [(str(src), "reckon")]


def test_check_node_fills_source_path_on_resolve_findings(store):
    _, findings = node_checks.check_node(
        node_of("./rel.py"), "nodes/detect.json", store=store, env={}
    )
    assert ids(findings) == ["STR-PATH-001"]
    assert findings[0].path == "nodes/detect.json"
    assert findings[0].node == "detect-buttons"


def test_check_node_deduplicates_findings_from_both_script_entrypoints(
    store, tmp_path, monkeypatch
):
    """`check_script` 와 `extract_contract` 가 같은 결함을 내도 리포트엔 한 번만."""
    src = tmp_path / "bad.py"
    src.write_text("x = 1\n", encoding="utf-8")
    duplicated = rules.finding("STR-CONTRACT-001", path=str(src), fields={"file": str(src)})

    import strictler.checks.script as script_module

    monkeypatch.setattr(
        script_module,
        "check_script",
        lambda source, path, node_type=None, known_dependencies=(): [duplicated],
    )
    monkeypatch.setattr(
        script_module,
        "extract_contract",
        lambda source, path: (FakeContract(path), [duplicated]),
    )

    _, findings = node_checks.check_node(
        node_of(str(src)), "bad.json", store=store, env={}
    )
    assert ids(findings) == ["STR-CONTRACT-001"]


def test_check_node_reports_tool_error_for_non_utf8_script(store, tmp_path, monkeypatch):
    """읽을 수 있는 자리까지 왔는데 못 읽는 것은 **도구가 못 돈 것**이다 — 위반이 아니다."""
    src = tmp_path / "broken.py"
    src.write_bytes(b"\xff\xfe not utf-8")
    ScriptStub().install(monkeypatch)

    with pytest.raises(StrictlerError) as caught:
        node_checks.check_node(node_of(str(src)), "n.json", store=store, env={})
    assert "UTF-8" in caught.value.message


# ── check_registration 디스패처 ─────────────────────────────────────────────


def test_check_registration_dispatches_script_without_a_node_type(tmp_path, store, monkeypatch):
    """스크립트 단독 등록에는 노드 타입이 없다 — 타입별 형식 요구는 노드 등록 시에 돈다."""
    src = tmp_path / "detect.py"
    src.write_text("def runNode(args): ...\n", encoding="utf-8")
    stub = ScriptStub()
    stub.install(monkeypatch)

    assert checks.check_registration("script", src, store) == []
    assert stub.seen_types == [(str(src), None)]


def test_check_registration_runs_node_checks_with_the_declared_type(
    tmp_path, store, monkeypatch
):
    src = tmp_path / "judge.py"
    src.write_text("def runNode(args): ...\n", encoding="utf-8")
    stub = ScriptStub()
    stub.install(monkeypatch)

    node_file = tmp_path / "judge.json"
    node_file.write_text(
        json.dumps(
            {
                "info": {"name": "judge", "description": "d"},
                "type": "action",
                "script": str(src),
            }
        ),
        encoding="utf-8",
    )
    assert checks.check_registration("node", node_file, store) == []
    assert stub.seen_types == [(str(src), "action")]


def test_check_registration_accepts_a_well_formed_pipeline(tmp_path, store, monkeypatch):
    """★ R3-14 — CLI 가 쓸 유일한 진입점의 **정상 경로**.

    파이프라인 파일 하나를 주면 참조된 노드들을 전부 로드·검사하고 빈 목록을 낸다.
    빈 목록일 때만 등록소에 저장되므로, 여기가 깨지면 정상적인 파이프라인이 등록조차
    안 된다.
    """
    stub = ScriptStub()
    scripts = {}
    for name, fields in (
        ("capture", {"output_fields": {"html": "str"}}),
        ("detect", {"input_fields": {"html": "str"}, "output_fields": {"count": "int"}}),
    ):
        src = tmp_path / f"{name}.py"
        src.write_text("def runNode(args): ...\n", encoding="utf-8")
        stub.put(str(src), contract(str(src), **fields))
        scripts[name] = src
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

    pipeline_file = tmp_path / "flow.json"
    pipeline_file.write_text(
        json.dumps(
            {
                "info": {"name": "flow", "description": "d", "kind": "verify"},
                "states": {"values": ["idle"], "initial": "idle"},
                "nodes": [
                    {"id": "capture", "source": str(node_files["capture"])},
                    {
                        "id": "detect",
                        "source": str(node_files["detect"]),
                        "inputs": {"html": "capture"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert checks.check_registration("pipeline", pipeline_file, store) == []
    assert set(stub.seen_types) == {
        (str(scripts["capture"]), "sense"),
        (str(scripts["detect"]), "perceive"),
    }


def test_check_registration_reports_a_broken_pipeline(tmp_path, store, monkeypatch):
    """같은 진입점이 배선 결함을 그대로 실어 낸다 — 빈 목록이 아니면 저장되지 않는다."""
    stub = ScriptStub()
    src = tmp_path / "detect.py"
    src.write_text("def runNode(args): ...\n", encoding="utf-8")
    stub.put(str(src), contract(str(src), output_fields={"count": "int"}))
    stub.install(monkeypatch)
    stub_reachability(monkeypatch)

    node_file = tmp_path / "detect.json"
    node_file.write_text(
        json.dumps(
            {
                "info": {"name": "detect", "description": "d"},
                "type": "perceive",
                "script": str(src),
            }
        ),
        encoding="utf-8",
    )
    pipeline_file = tmp_path / "flow.json"
    pipeline_file.write_text(
        json.dumps(
            {
                "info": {"name": "flow", "description": "d", "kind": "verify"},
                "states": {"values": ["idle"], "initial": "idle"},
                "nodes": [
                    {
                        "id": "detect",
                        "source": str(node_file),
                        "inputs": {"html": "ghost"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert ids(checks.check_registration("pipeline", pipeline_file, store)) == [
        "STR-REF-003"
    ]


def test_check_registration_reports_bad_spec_shape(tmp_path, store):
    spec_file = tmp_path / "login.json"
    spec_file.write_text(json.dumps({"info": {"description": "d"}}), encoding="utf-8")
    findings = checks.check_registration("spec", spec_file, store)
    assert ids(findings) == [""]
    assert "plan" in findings[0].message


def test_check_registration_accepts_a_well_formed_spec(tmp_path, store):
    spec_file = tmp_path / "login.json"
    spec_file.write_text(
        json.dumps(
            {
                "info": {"description": "로그인 검증"},
                "tool": {"node": {"path": "/usr/bin/node", "functions": []}},
                "plan": [{"source": "${ref.pl_c9d0e1f2}", "description": "의도"}],
            }
        ),
        encoding="utf-8",
    )
    assert checks.check_registration("spec", spec_file, store) == []


def test_check_registration_missing_file_is_a_tool_error(tmp_path, store):
    """파일이 없는 것은 위반이 아니라 **도구가 못 돈 것**이다."""
    with pytest.raises(StrictlerError):
        checks.check_registration("node", tmp_path / "nope.json", store)


def test_check_registration_broken_json_is_a_tool_error(tmp_path, store):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(StrictlerError):
        checks.check_registration("pipeline", bad, store)


# ── 슬롯 계약 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule_id",
    ["STR-REF-001", "STR-REG-002", "STR-REG-003", "STR-PATH-001", "STR-PATH-002"],
)
def test_every_rule_this_module_raises_has_its_slots_filled(rule_id):
    """이 모듈이 내는 규칙마다 슬롯이 하나도 안 빠졌는지.

    `rules.finding()` 은 슬롯이 비면 `StrictlerError` 를 내며 **규칙 id 가 통째로
    사라진다** — 위 테스트들이 `rule_id` 를 단언하는 것이 곧 이 검증이지만,
    규칙 쪽 슬롯이 늘어났을 때 여기서 먼저 깨지도록 못 박아 둔다.
    """
    assert rules.get_rule(rule_id).slots  # 전부 슬롯을 요구하는 규칙들이다
