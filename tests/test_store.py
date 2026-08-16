"""등록소(`store.entries` / `store.graph`) 테스트 — Step 1-d.

실제 `~/.strictler` 를 건드리지 않는다. 모든 테스트가 `STRICTLER_HOME` 을
`tmp_path` 로 바꿔 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.store.entries import (
    RegistryIndex,
    Store,
    default_home,
    hash_file,
    new_id,
)
from strictler.store.graph import RefGraph


# ── rules.py 대역 ─────────────────────────────────────────────────────────────
#
# `rules.finding` 은 Step 1-b 담당이라 아직 stub 일 수 있다. 그때만 최소 대역을
# 끼운다 — 구현이 들어오면 이 fixture 는 아무것도 하지 않고 진짜 메시지가 돈다.


def _fallback_finding(
    rule_id: str,
    *,
    status: str = "error",
    path: str = "",
    node: str = "",
    cause: object = None,
    fields: dict[str, object] | None = None,
) -> Finding:
    detail = " ".join(f"{k}={v}" for k, v in sorted((fields or {}).items()))
    return Finding(
        status=status,  # type: ignore[arg-type]
        path=path,
        node=node,
        rule_id=rule_id,
        message=detail,
    )


@pytest.fixture(autouse=True)
def _rules_available(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        rules.finding("STR-REG-004", path="x", fields={"id": "y", "ref": "y"})
    except NotImplementedError:
        monkeypatch.setattr(rules, "finding", _fallback_finding)


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
    assert calls == [("STR-REG-004", {"id": sc_id, "ref": sc_id})]


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
    assert [f.rule_id for f in findings] == ["STR-REG-005"]
    assert findings[0].path == pl_id
    # 실패한 규칙 id 가 메시지에 실려 나간다. 대역이든 실제 구현이든 성립한다 —
    # `STR-REG-005` 의 guide 자체가 `{rule}` 슬롯을 갖기 때문이다 (`rules.md`).
    assert "STR-TYPE-004" in findings[0].message

    # 인덱스에 남아 있어야 이후 `list` 에서 드러난다.
    reloaded = {e.id: e for e in Store().list()}
    assert reloaded[pl_id].broken == "validation"
    assert reloaded[pl_id].broken_detail == "STR-TYPE-004"
    assert reloaded[nd_id].broken == ""
    assert reloaded[sp_id].broken == ""


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
    assert calls == [("STR-REG-005", {"rule": "STR-TYPE-004"})]


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
