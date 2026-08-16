"""등록소(`store.entries` / `store.graph`) 테스트 — Step 1-d.

실제 `~/.strictler` 를 건드리지 않는다. 모든 테스트가 `STRICTLER_HOME` 을
`tmp_path` 로 바꿔 쓴다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.store import entries, graph
from strictler.store.entries import (
    RegistryIndex,
    Store,
    default_home,
    hash_file,
    new_id,
)
from strictler.store.graph import RefGraph


# ── 공통 fixture ─────────────────────────────────────────────────────────────


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "strictler-home"
    monkeypatch.setenv("STRICTLER_HOME", str(target))
    return target


@pytest.fixture()
def store(home: Path) -> Store:
    return Store()


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


SCRIPT_SRC = """\
def runNode(args):
    return returnResult()
"""


# ── default_home ─────────────────────────────────────────────────────────────


def test_default_home_uses_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRICTLER_HOME", str(tmp_path / "elsewhere"))
    assert default_home() == tmp_path / "elsewhere"


def test_default_home_falls_back_to_dot_strictler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRICTLER_HOME", raising=False)
    assert default_home() == Path.home() / ".strictler"


def test_default_home_rejects_relative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRICTLER_HOME", "./somewhere")
    with pytest.raises(StrictlerError):
        default_home()


def test_store_creates_layout(store: Store, home: Path) -> None:
    for subdir in ("scripts", "nodes", "pipelines", "specs"):
        assert (home / subdir).is_dir()


# ── id 발급 ──────────────────────────────────────────────────────────────────


def test_new_id_prefix_per_kind() -> None:
    assert new_id("script").startswith("sc_")
    assert new_id("node").startswith("nd_")
    assert new_id("pipeline").startswith("pl_")
    assert new_id("spec").startswith("sp_")
    assert new_id("node") != new_id("node")


def test_add_issues_prefixed_id_per_kind(store: Store, tmp_path: Path) -> None:
    script = write(tmp_path / "detect.py", SCRIPT_SRC)
    node = write(tmp_path / "detect.json", '{"type": "perceive"}')
    pipeline = write(tmp_path / "flow.json", '{"info": {}}')
    spec = write(tmp_path / "login.json", '{"plan": []}')

    assert store.add("script", script).id.startswith("sc_")
    assert store.add("node", node).id.startswith("nd_")
    assert store.add("pipeline", pipeline).id.startswith("pl_")
    assert store.add("spec", spec).id.startswith("sp_")


# ── add / show / read ────────────────────────────────────────────────────────


def test_show_works_after_source_is_deleted(store: Store, tmp_path: Path) -> None:
    source = write(tmp_path / "detect.py", SCRIPT_SRC)
    entry = store.add("script", source, name="detect-buttons")
    source.unlink()

    shown = store.show(entry.id)
    assert shown.id == entry.id
    assert shown.name == "detect-buttons"
    assert store.read(entry.id) == SCRIPT_SRC
    assert store.path_of(entry.id).is_file()


def test_add_defaults_name_to_file_stem(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    assert entry.name == "detect"


def test_add_rejects_missing_source(store: Store, tmp_path: Path) -> None:
    with pytest.raises(StrictlerError):
        store.add("script", tmp_path / "nope.py")


def test_add_rejects_non_utf8_source(store: Store, tmp_path: Path) -> None:
    """UTF-8 이 아닌 파일은 raw `UnicodeDecodeError` 가 아니라 `StrictlerError` 다.

    위반도 not run 도 아닌 **오류**(도구가 못 돈 것)이므로 가이드가 붙어야 한다.
    """
    source = tmp_path / "cp949.py"
    source.write_bytes("# 버튼\n".encode("cp949"))

    with pytest.raises(StrictlerError) as excinfo:
        store.add("script", source)
    assert "UTF-8" in excinfo.value.message
    assert store.list() == []


def test_update_rejects_non_utf8_source(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    bad = tmp_path / "cp949.py"
    bad.write_bytes("# 버튼\n".encode("cp949"))

    with pytest.raises(StrictlerError):
        store.update(entry.id, bad)
    assert store.read(entry.id) == SCRIPT_SRC


def test_read_rejects_a_tampered_non_utf8_copy(store: Store, tmp_path: Path) -> None:
    """등록소 복사본이 UTF-8 이 아니게 되면 `StrictlerError` 다.

    등록소에 들어갈 때는 UTF-8 이었으나 **정적 검사 루트를 피해 직접 고치는 것**이
    `STR-REG-001` 이 상정하는 시나리오다. `verify_hash` 를 먼저 부른다는 보장이
    없으므로 `read()` 가 raw `UnicodeDecodeError` 를 내면 안 된다.
    """
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    store.path_of(entry.id).write_bytes("# 버튼\n".encode("cp949"))

    with pytest.raises(StrictlerError) as excinfo:
        store.read(entry.id)
    assert "UTF-8" in excinfo.value.message
    assert str(store.path_of(entry.id)) in excinfo.value.message


def test_show_unknown_id_is_an_error(store: Store) -> None:
    with pytest.raises(StrictlerError):
        store.show("nd_deadbeef")


def test_list_filters_by_kind(store: Store, tmp_path: Path) -> None:
    store.add("script", write(tmp_path / "a.py", SCRIPT_SRC))
    store.add("script", write(tmp_path / "b.py", SCRIPT_SRC))
    store.add("node", write(tmp_path / "n.json", "{}"))

    assert len(store.list()) == 3
    assert len(store.list("script")) == 2
    assert [e.kind for e in store.list("node")] == ["node"]


def test_index_is_persisted_as_json(store: Store, tmp_path: Path, home: Path) -> None:
    entry = store.add("script", write(tmp_path / "a.py", SCRIPT_SRC))
    raw = json.loads((home / "registry.json").read_text(encoding="utf-8"))
    assert raw["entries"][entry.id]["kind"] == "script"
    # 새 Store 인스턴스가 같은 인덱스를 읽는다.
    assert Store().show(entry.id).hash == entry.hash


# ── 해시 대조 (STR-REG-001) ──────────────────────────────────────────────────


def test_verify_hash_detects_direct_edit(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    assert store.verify_hash(entry.id) is True

    # 정적 검사 루트를 피해 등록소 파일을 직접 고친다.
    store.path_of(entry.id).write_text(SCRIPT_SRC + "# tampered\n", encoding="utf-8")
    assert store.verify_hash(entry.id) is False


def test_verify_hash_false_when_copy_is_gone(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    store.path_of(entry.id).unlink()
    assert store.verify_hash(entry.id) is False


def test_test_json_gets_its_own_hash(store: Store, tmp_path: Path) -> None:
    """등록소의 `.test.json` 도 해시로 무단 수정을 막는다 (R6-7).

    **노드 해시와 섞지 않는다** — 한 해시로 합치면 테스트 유무가 노드 해시를 바꿔
    기존 등록 id 의 해시가 전부 달라진다.
    """
    node = write(tmp_path / "detect.json", '{"info": {}, "type": "perceive"}')
    write(tmp_path / "detect.test.json", '{"node": "x", "cases": []}')

    entry = store.add("node", node)

    assert entry.hash == hash_file(node)  # 노드 해시는 노드 파일만 본다
    assert entry.test_hash and entry.test_hash != entry.hash
    assert store.verify_test_hash(entry.id) is True

    stored = store.test_path("node", entry.id)
    assert stored is not None
    stored.write_text('{"node": "y", "cases": []}', encoding="utf-8")
    assert store.verify_test_hash(entry.id) is False
    assert store.verify_hash(entry.id) is True  # 노드 파일은 멀쩡하다


def test_no_test_json_means_no_test_hash(store: Store, tmp_path: Path) -> None:
    """**없는 것은 깨진 것이 아니다.**"""
    node = write(tmp_path / "detect.json", '{"info": {}, "type": "perceive"}')
    entry = store.add("node", node)

    assert entry.test_hash == ""
    assert store.verify_test_hash(entry.id) is True


def test_update_refreshes_the_test_hash(store: Store, tmp_path: Path) -> None:
    node = write(tmp_path / "detect.json", '{"info": {}, "type": "perceive"}')
    test = write(tmp_path / "detect.test.json", '{"node": "x", "cases": []}')
    entry = store.add("node", node)
    before = entry.test_hash

    write(test, '{"node": "x", "cases": [{"name": "c", "args": {}}]}')
    updated = store.update(entry.id, node)

    assert updated.test_hash not in ("", before)
    assert store.verify_test_hash(entry.id) is True

    # 원본에서 테스트가 사라지면 등록소의 것도, 해시도 함께 걷힌다.
    test.unlink()
    assert store.update(entry.id, node).test_hash == ""
    assert store.verify_test_hash(entry.id) is True


def test_hash_file_matches_content(tmp_path: Path) -> None:
    one = write(tmp_path / "one.py", SCRIPT_SRC)
    same = write(tmp_path / "same.py", SCRIPT_SRC)
    other = write(tmp_path / "other.py", SCRIPT_SRC + "\n")
    assert hash_file(one) == hash_file(same)
    assert hash_file(one) != hash_file(other)


# ── update ───────────────────────────────────────────────────────────────────


def test_update_keeps_id_and_refreshes_content(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC), name="detect")
    before = entry.hash

    changed = write(tmp_path / "detect2.py", SCRIPT_SRC + "# v2\n")
    updated = store.update(entry.id, changed)

    assert updated.id == entry.id
    assert updated.name == "detect"
    assert updated.hash != before
    assert store.read(entry.id).endswith("# v2\n")
    assert store.verify_hash(entry.id) is True


def test_update_clears_own_broken_mark(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    index = store.load_index()
    index.entries[entry.id].broken = "validation"
    index.entries[entry.id].broken_detail = "STR-TYPE-004"
    store.save_index(index)

    updated = store.update(entry.id, write(tmp_path / "detect2.py", SCRIPT_SRC + "#\n"))
    assert updated.broken == ""
    assert updated.broken_detail == ""


def test_update_unknown_id_is_an_error(store: Store, tmp_path: Path) -> None:
    with pytest.raises(StrictlerError):
        store.update("sc_deadbeef", write(tmp_path / "a.py", SCRIPT_SRC))


# ── remove ───────────────────────────────────────────────────────────────────


def test_remove_deletes_entry_and_file(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC))
    path = store.path_of(entry.id)
    store.remove(entry.id)

    assert not path.exists()
    assert store.list() == []
    with pytest.raises(StrictlerError):
        store.show(entry.id)


def test_remove_unknown_id_is_an_error(store: Store) -> None:
    with pytest.raises(StrictlerError):
        store.remove("sc_deadbeef")


# ── 참조 수집과 그래프 ────────────────────────────────────────────────────────


def _chain(store: Store, tmp_path: Path) -> tuple[str, str, str, str]:
    """스크립트 → 노드 → 파이프라인 → Spec 사슬을 등록한다."""
    sc = store.add("script", write(tmp_path / "detect.py", SCRIPT_SRC), name="detect")
    node_src = write(
        tmp_path / "detect.json",
        json.dumps({"type": "perceive", "script": f"${{ref.{sc.id}}}"}),
    )
    nd = store.add("node", node_src, name="detect-buttons")
    pipeline_src = write(
        tmp_path / "flow.json",
        json.dumps({"nodes": [{"id": "detect", "source": f"${{ref.{nd.id}}}"}]}),
    )
    pl = store.add("pipeline", pipeline_src, name="login-flow")
    spec_src = write(
        tmp_path / "login-spec.json",
        json.dumps({"plan": [{"source": f"${{ref.{pl.id}}}"}]}),
    )
    sp = store.add("spec", spec_src, name="login")
    return sc.id, nd.id, pl.id, sp.id


def test_add_collects_ref_ids(store: Store, tmp_path: Path) -> None:
    sc_id, nd_id, pl_id, sp_id = _chain(store, tmp_path)
    assert store.show(sc_id).refs == []
    assert store.show(nd_id).refs == [sc_id]
    assert store.show(pl_id).refs == [nd_id]
    assert store.show(sp_id).refs == [pl_id]


def test_add_ignores_other_namespaces(store: Store, tmp_path: Path) -> None:
    source = write(
        tmp_path / "n.json",
        json.dumps({"script": "${env.HOME}/x.py", "params": "${config.expected}"}),
    )
    assert store.add("node", source).refs == []


PEP723_SRC = (
    "# /// script\n"
    '# requires-python = ">=3.11"\n'
    '# dependencies = ["pydantic>=2"]\n'
    "# ///\n" + SCRIPT_SRC
)


def test_add_records_declared_dependencies(store: Store, tmp_path: Path) -> None:
    """PEP 723 선언을 등록 시점에 기록한다 — 격리를 뒤집을 조건을 도구가 스스로
    검출하기 위한 재료다 (`schema.md` 6절)."""
    source = write(tmp_path / "n.py", PEP723_SRC)
    assert store.add("script", source).dependencies == ["pydantic>=2"]


def test_dependencies_are_empty_without_header(store: Store, tmp_path: Path) -> None:
    """**헤더가 없는 것이 정상이다.** 스크립트가 아닌 종류도 마찬가지."""
    assert store.add("script", write(tmp_path / "a.py", SCRIPT_SRC)).dependencies == []
    node = write(tmp_path / "a.json", json.dumps({"type": "sense"}))
    assert store.add("node", node).dependencies == []


def test_update_refreshes_declared_dependencies(store: Store, tmp_path: Path) -> None:
    entry = store.add("script", write(tmp_path / "n.py", PEP723_SRC))
    assert entry.dependencies == ["pydantic>=2"]
    plain = write(tmp_path / "plain.py", SCRIPT_SRC)
    assert store.update(entry.id, plain).dependencies == []


def test_declared_dependencies_unions_every_script(store: Store, tmp_path: Path) -> None:
    """안내 명령을 완전하게 만드는 재료 — `--with` 는 선언적이라 전부 필요하다."""
    assert store.declared_dependencies() == []  # 빈 등록소는 빈 목록 (폴백)

    store.add("script", write(tmp_path / "a.py", PEP723_SRC))
    other = (
        "# /// script\n"
        '# dependencies = ["selectolax>=0.3"]\n'
        "# ///\n" + SCRIPT_SRC
    )
    store.add("script", write(tmp_path / "b.py", other))
    store.add("script", write(tmp_path / "c.py", SCRIPT_SRC))  # 헤더 없음

    assert sorted(store.declared_dependencies()) == ["pydantic>=2", "selectolax>=0.3"]


def test_dependencies_and_dependents(store: Store, tmp_path: Path) -> None:
    sc_id, nd_id, pl_id, _sp_id = _chain(store, tmp_path)
    graph = RefGraph.build(store)

    assert graph.dependencies(nd_id) == [sc_id]
    assert graph.dependents(sc_id) == [nd_id]
    assert graph.dependents(nd_id) == [pl_id]
    assert graph.dependents(sc_id) != graph.transitive_dependents(sc_id)


def test_transitive_dependents_walks_the_whole_chain(
    store: Store, tmp_path: Path
) -> None:
    sc_id, nd_id, pl_id, sp_id = _chain(store, tmp_path)
    graph = RefGraph.build(store)

    assert graph.transitive_dependents(sc_id) == [nd_id, pl_id, sp_id]
    assert graph.transitive_dependents(nd_id) == [pl_id, sp_id]
    assert graph.transitive_dependents(sp_id) == []


def test_transitive_dependents_survives_a_cycle(store: Store, tmp_path: Path) -> None:
    a = store.add("node", write(tmp_path / "a.json", "{}"))
    b = store.add("node", write(tmp_path / "b.json", "{}"))
    index = store.load_index()
    index.entries[a.id].refs = [b.id]
    index.entries[b.id].refs = [a.id]
    store.save_index(index)

    graph = RefGraph.build(store)
    assert graph.transitive_dependents(a.id) == [b.id]


# ── 참조 깨짐 (STR-REG-004) ──────────────────────────────────────────────────


def test_remove_leaves_dependents_ref_broken(store: Store, tmp_path: Path) -> None:
    sc_id, nd_id, _pl_id, _sp_id = _chain(store, tmp_path)

    store.remove(sc_id)  # 참조가 있어도 막지 않는다

    graph = RefGraph.build(store)
    findings = graph.broken_refs()

    assert [f.rule_id for f in findings] == ["STR-REG-004"]
    assert findings[0].path == nd_id
    assert graph.entries[nd_id].broken == "ref"
    assert graph.entries[nd_id].broken_detail == sc_id
    # 참조가 멀쩡한 나머지는 건드리지 않는다.
    assert graph.entries[_pl_id].broken == ""


def test_graph_calls_finding_with_the_fields_dict(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`rules.finding` 은 슬롯 값을 `fields` 딕셔너리로만 받는다 (계약 개정 R1-2).

    `**fields` 로 넘기면 keyword-only `path`/`node` 와 동명 슬롯이 충돌한다.
    여기서는 그래프가 **개정된 시그니처로만** 부르는지를 본다 — 다른 형태로
    부르면 대역이 `TypeError` 로 터진다.
    """
    calls: list[tuple[str, dict[str, object]]] = []

    def spy(
        rule_id: str,
        *,
        path: str = "",
        node: str = "",
        fields: dict[str, object] | None = None,
    ) -> Finding:
        calls.append((rule_id, dict(fields or {})))
        return Finding(status="error", path=path, node=node, rule_id=rule_id)

    sc_id, nd_id, _pl_id, _sp_id = _chain(store, tmp_path)
    store.remove(sc_id)
    monkeypatch.setattr(rules, "finding", spy)

    RefGraph.build(store).broken_refs()
    # `STR-REG-004` 의 슬롯은 `{id}` 하나뿐이다 (계약 개정 R2-8). 선언되지 않은
    # 슬롯을 얹으면 R1-3 의 슬롯 검증에 걸려 런타임에 터진다.
    assert calls == [("STR-REG-004", {"id": sc_id})]


def test_broken_refs_is_empty_for_a_healthy_registry(
    store: Store, tmp_path: Path
) -> None:
    _chain(store, tmp_path)
    assert RefGraph.build(store).broken_refs() == []


# ── 검증 깨짐 (STR-REG-005) ─────────────────────────────────────────────────


def _mock_checks(
    monkeypatch: pytest.MonkeyPatch, failures: dict[str, str]
) -> list[str]:
    """`checks.check_registration` 을 대역으로 바꾼다.

    재검증 자체는 Step 2 의 몫이라 여기서는 "무엇이 재검증됐고 실패가 어떻게
    표시되는가"만 본다. `failures` 는 `{종류: 실패 규칙 id}`.
    """
    import strictler.checks as checks

    called: list[str] = []

    def fake(kind: str, source: Path, store: Store) -> list[Finding]:
        called.append(source.stem)
        rule_id = failures.get(kind, "")
        if not rule_id:
            return []
        return [Finding(status="error", rule_id=rule_id, message="mock")]

    monkeypatch.setattr(checks, "check_registration", fake)
    return called


def test_update_marks_dependents_validation_broken(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc_id, nd_id, pl_id, sp_id = _chain(store, tmp_path)
    called = _mock_checks(monkeypatch, {"pipeline": "STR-TYPE-004"})

    store.update(sc_id, write(tmp_path / "detect2.py", SCRIPT_SRC + "# v2\n"))
    graph = RefGraph.build(store)
    findings = graph.revalidate(store, sc_id)

    assert called == [nd_id, pl_id, sp_id]  # 전이적으로, 아래에서 위로
    # 깨진 파이프라인 자신 + 그것을 참조해 **덩달아 못 돌게 된 Spec** (R5-4).
    assert [f.rule_id for f in findings] == ["STR-REG-005", "STR-REG-005"]
    assert findings[0].path == pl_id
    assert findings[1].path == sp_id
    # 실패한 규칙 id 가 메시지에 실려 나간다. 대역이든 실제 구현이든 성립한다 —
    # `STR-REG-005` 의 guide 자체가 `{rule}` 슬롯을 갖기 때문이다 (`rules.md`).
    assert "STR-TYPE-004" in findings[0].message
    assert pl_id in findings[1].message

    # 인덱스에 남아 있어야 이후 `list` 에서 드러난다.
    reloaded = {e.id: e for e in Store().list()}
    assert reloaded[pl_id].broken == "validation"
    assert reloaded[pl_id].broken_detail == "STR-TYPE-004"
    assert reloaded[nd_id].broken == ""
    # 전이는 **파생값이라 저장하지 않는다** — 아래가 고쳐지면 그 자리에서 사라져야 한다.
    assert reloaded[sp_id].broken == ""
    assert graph.entries[sp_id].broken == "validation"


def test_revalidate_calls_finding_with_the_fields_dict(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재검증 쪽도 `fields` 딕셔너리로만 부른다 (계약 개정 R1-2)."""
    calls: list[tuple[str, dict[str, object]]] = []

    def spy(
        rule_id: str,
        *,
        path: str = "",
        node: str = "",
        fields: dict[str, object] | None = None,
    ) -> Finding:
        calls.append((rule_id, dict(fields or {})))
        return Finding(status="error", path=path, node=node, rule_id=rule_id)

    sc_id, _nd_id, _pl_id, _sp_id = _chain(store, tmp_path)
    _mock_checks(monkeypatch, {"pipeline": "STR-TYPE-004"})
    monkeypatch.setattr(rules, "finding", spy)

    RefGraph.build(store).revalidate(store, sc_id)
    # `STR-REG-005` 의 슬롯은 `{id}`·`{rule}` 둘이다. `path` 와 `{id}` 는 값이 같아도
    # 별개 채널이라 둘 다 넘겨야 한다 (계약 개정 R1-2).
    # 전이분(R5-4)도 같은 규약을 지킨다 — 슬롯 둘을 딕셔너리로만 넘긴다.
    assert calls[0] == ("STR-REG-005", {"id": _pl_id, "rule": "STR-TYPE-004"})
    assert [rule_id for rule_id, _ in calls] == ["STR-REG-005", "STR-REG-005"]
    assert set(calls[1][1]) == {"id", "rule"}
    assert calls[1][1]["id"] == _sp_id


def test_revalidate_clears_a_stale_validation_mark(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc_id, nd_id, pl_id, _sp_id = _chain(store, tmp_path)
    index = store.load_index()
    index.entries[pl_id].broken = "validation"
    index.entries[pl_id].broken_detail = "STR-TYPE-004"
    store.save_index(index)

    _mock_checks(monkeypatch, {})
    graph = RefGraph.build(store)
    assert graph.revalidate(store, sc_id) == []
    assert Store().show(pl_id).broken == ""


def test_revalidate_does_not_touch_ref_broken_mark(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc_id, nd_id, pl_id, _sp_id = _chain(store, tmp_path)
    index = store.load_index()
    index.entries[pl_id].broken = "ref"
    index.entries[pl_id].broken_detail = "nd_gone1234"
    store.save_index(index)

    _mock_checks(monkeypatch, {})
    graph = RefGraph.build(store)
    graph.revalidate(store, sc_id)

    assert Store().show(pl_id).broken == "ref"


def test_revalidate_of_a_leaf_does_nothing(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sc_id, _nd_id, _pl_id, sp_id = _chain(store, tmp_path)
    called = _mock_checks(monkeypatch, {"spec": "STR-TYPE-004"})

    graph = RefGraph.build(store)
    assert graph.revalidate(store, sp_id) == []
    assert called == []


# ── 인덱스 모델 ──────────────────────────────────────────────────────────────


def test_load_index_of_a_fresh_home_is_empty(store: Store) -> None:
    index = store.load_index()
    assert isinstance(index, RegistryIndex)
    assert index.entries == {}


def test_load_index_rejects_broken_json(store: Store, home: Path) -> None:
    (home / "registry.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(StrictlerError):
        store.load_index()


def test_load_index_rejects_non_utf8_index(store: Store, home: Path) -> None:
    """인덱스 손상은 반반이다 — 깨진 JSON 이거나 깨진 인코딩이거나.

    `JSONDecodeError` 만 감싸면 나머지 절반이 raw `UnicodeDecodeError` 로 샌다.
    """
    (home / "registry.json").write_bytes('{"version": 1, "name": "버튼"}'.encode("cp949"))
    with pytest.raises(StrictlerError) as excinfo:
        store.load_index()
    assert "UTF-8" in excinfo.value.message
    assert "registry.json" in excinfo.value.message


# ── 슬롯 누락 회귀 방지 — 등록소가 내는 오류 경로 전수 ───────────────────────
#
# `rules.Rule.slots` 를 `fields` 로 안 채우면 `_render` 가 거절하고 **규칙 id 가
# 사라진다**. 그래서 "오류 경로를 실제로 태워 `rule_id` 를 확인" 하는 것이 곧
# 슬롯 검증이다. 여기서는 `rules.finding` 을 대역으로 바꾸지 않는다 —
# 진짜 슬롯 강제를 통과해야 의미가 있다.

_UNFILLED_SLOT_C = re.compile(r"(?<!\$)\{(\w+)\}")
"""`{id}` 는 안 채워진 슬롯, `${env.X}` 는 가이드 본문이다."""

_FINDING_SITE_C = re.compile(r'rules\.finding\(\s*\n?\s*"(STR-[A-Z]+-\d+)"')
"""`store` 안의 `rules.finding("STR-...")` 호출부."""


def _broken_ref_findings(store: Store, tmp_path: Path) -> list[Finding]:
    sc_id, _nd_id, _pl_id, _sp_id = _chain(store, tmp_path)
    store.remove(sc_id)
    return RefGraph.build(store).broken_refs()


def _revalidate_findings(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[Finding]:
    sc_id, _nd_id, _pl_id, _sp_id = _chain(store, tmp_path)
    _mock_checks(monkeypatch, {"pipeline": "STR-TYPE-004"})
    store.update(sc_id, write(tmp_path / "detect2.py", SCRIPT_SRC + "# v2\n"))
    return RefGraph.build(store).revalidate(store, sc_id)


def test_broken_ref_finding_carries_its_rule_id(store: Store, tmp_path: Path) -> None:
    findings = _broken_ref_findings(store, tmp_path)
    assert [f.rule_id for f in findings] == ["STR-REG-004"]
    assert _UNFILLED_SLOT_C.findall(findings[0].message) == []


def test_revalidate_finding_carries_its_rule_id(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _revalidate_findings(store, tmp_path, monkeypatch)
    # 깨진 것 하나 + 그것을 참조해 덩달아 깨진 상위 하나 (R5-4). **둘 다** 슬롯이 찬다.
    assert [f.rule_id for f in findings] == ["STR-REG-005", "STR-REG-005"]
    assert [_UNFILLED_SLOT_C.findall(f.message) for f in findings] == [[], []]


def test_every_finding_site_in_store_is_exercised() -> None:
    """`store` 가 내는 규칙 전부가 위 둘로 실제 실행된다.

    새 `rules.finding` 을 추가하면서 오류 경로를 안 태우면 여기서 걸린다 —
    슬롯 누락이 "언젠가 실행됐을 때" 가 아니라 **이 자리에서** 드러난다.
    """
    declared: set[str] = set()
    for module in (entries, graph):
        source = Path(module.__file__).read_text(encoding="utf-8")
        declared |= set(_FINDING_SITE_C.findall(source))
    assert declared == {"STR-REG-004", "STR-REG-005"}
