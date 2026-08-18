"""등록소 스크립트는 **바이트코드를 캐시하지 않는다** (`schema.md` 2절).

pyc 의 무효화 기준은 **원본의 mtime + 크기**뿐이다. 이 도구는 그 기준을 못 믿어서
**내용 해시**로 검증 결과를 재사용하는데(`checks/contracts.py`), 그 밑에서 mtime 기반
캐시가 돌면 **원본은 바뀌었는데 옛 바이트코드가 실행되어 거짓 통과**가 난다 —
리포트가 검사하지 않은 것을 통과라고 말하는 자리라서 가장 나쁜 종류의 결함이다.

여기서 보는 것은 셋이다:

- 로드해도 `__pycache__` 가 **생기지 않는다** (쓰기)
- **이미 있는 pyc 가 있어도** 원본대로 돈다 (읽기) — 같은 파일을 표준 로더로 읽으면
  옛 값이 나온다는 것까지 함께 확인해, 이 테스트가 헛돌지 않게 못 박는다
- 등록소 `update` 후 mtime 을 되돌려도 **거짓 통과가 나지 않는다** (전체 경로)
"""

from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from lintomata import cli
from lintomata.checks.script import extract_contract
from lintomata.engine import exec as node_exec
from lintomata.store.entries import BYTECODE_SUBDIR, SUBDIRS, Store

SOURCE = """
    from dataclasses import dataclass

    @dataclass
    class Params:
        seed: int

    @dataclass
    class Out:
        n: int

    @dataclass
    class Args:
        params: Params

    N = {n}

    def runNode(args: Args) -> Out:
        return returnResult(Out(n=N))
"""
"""`N` 한 글자만 다른 두 판을 만든다 — **길이가 같아야** pyc 무효화(mtime + 크기)를
빠져나가는 실제 상황이 재현된다."""


def _write(path: Path, n: int) -> None:
    path.write_text(dedent(SOURCE.format(n=n)), encoding="utf-8")


def _run(path: Path) -> int:
    """스크립트를 엔진으로 돌려 `Out.n` 을 받는다."""
    module = node_exec.load_script(path)
    contract, _ = extract_contract(path.read_text(encoding="utf-8"), str(path))
    args = node_exec.build_args(module, contract, params={"seed": 0})
    return int(node_exec.invoke(module, args).n)


def _load_with_stock_importlib(path: Path, name: str) -> int:
    """표준 로더로 같은 파일을 읽는다 — **pyc 가 실제로 유독한지** 확인하는 대조군."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return int(module.N)
    finally:
        sys.modules.pop(name, None)


def _freeze_mtime(path: Path, stamp: tuple[int, int]) -> None:
    """mtime 을 되돌린다 — pyc 가 스스로를 유효하다고 믿게 만드는 조건."""
    os.utime(path, ns=stamp)


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_atime_ns, stat.st_mtime_ns)


# ── 쓰기 ─────────────────────────────────────────────────────────────────────


def test_load_script_writes_no_bytecode(tmp_path: Path) -> None:
    """로드해도 `__pycache__` 가 생기지 않고, 전역 플래그는 원래대로 돌아온다."""
    script = tmp_path / "count.py"
    _write(script, 1)
    saved = sys.dont_write_bytecode

    assert _run(script) == 1

    assert not (tmp_path / BYTECODE_SUBDIR).exists()
    assert list(tmp_path.rglob("*.pyc")) == []
    assert sys.dont_write_bytecode is saved


def test_flag_is_restored_when_the_script_blows_up(tmp_path: Path) -> None:
    """예외가 나도 `sys.dont_write_bytecode` 는 되돌아간다 — 전역 상태다."""
    script = tmp_path / "boom.py"
    script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    saved = sys.dont_write_bytecode

    with pytest.raises(Exception):
        node_exec.load_script(script)

    assert sys.dont_write_bytecode is saved


# ── 읽기 ─────────────────────────────────────────────────────────────────────


def test_stale_bytecode_is_not_read(tmp_path: Path) -> None:
    """**이미 만들어져 있는 pyc** 가 있어도 원본대로 돈다.

    수정 전 버전이 남겨 둔 pyc 를 그대로 재현한다: `N = 1` 로 컴파일해 두고,
    원본만 `N = 2` 로 갈아끼운 뒤 mtime 을 되돌린다 (크기는 같다).
    """
    script = tmp_path / "count.py"
    _write(script, 1)
    stamp = _stamp(script)
    size = script.stat().st_size

    pyc = Path(py_compile.compile(str(script), doraise=True))
    assert pyc.is_file()

    _write(script, 2)
    assert script.stat().st_size == size, "두 판의 길이가 같아야 재현이 성립한다"
    _freeze_mtime(script, stamp)

    # 대조군: 표준 로더는 옛 바이트코드를 읽어 `1` 을 준다 — pyc 는 실제로 유독하다.
    assert _load_with_stock_importlib(script, "stale_probe") == 1
    # 엔진은 소스에서 컴파일하므로 원본대로 `2`.
    assert _run(script) == 2


# ── 등록소 ───────────────────────────────────────────────────────────────────


def test_update_and_remove_purge_bytecode(tmp_path: Path) -> None:
    """`update` / `remove` 는 옛 버전이 남긴 pyc 도 걷는다."""
    store = Store(tmp_path / "home")
    source = tmp_path / "count.py"
    _write(source, 1)
    entry = store.add("script", source)

    copied = store.path_of(entry.id)
    py_compile.compile(str(copied), doraise=True)
    cache = copied.parent / BYTECODE_SUBDIR
    assert list(cache.glob(f"{entry.id}.*.pyc"))

    _write(source, 2)
    store.update(entry.id, source)
    assert list(cache.glob(f"{entry.id}.*.pyc")) == []

    py_compile.compile(str(copied), doraise=True)
    assert list(cache.glob(f"{entry.id}.*.pyc"))
    store.remove(entry.id)
    assert list(cache.glob(f"{entry.id}.*.pyc")) == []


NODE = {
    "info": {"name": "count", "description": "고정된 수를 내놓는다"},
    "type": "collect",
    "script": "",
}

NODE_TEST = {
    "node": "",
    "cases": [{"name": "1 이 나온다", "args": {"params": {"seed": 0}}, "expect": {"n": 1}}],
}


def test_updated_script_is_not_masked_by_stale_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 거짓 통과 재현 — 등록 → 실행 → `update` → mtime 되돌리기.

    `N = 1` 을 기대하는 단위테스트가 `N = 2` 로 바뀐 뒤에도 통과하면 그것이 거짓
    통과다. **진짜 등록소·진짜 CLI 로 돈다** — 대역을 쓰면 이 결함이 사는 자리를
    그대로 비껴간다.
    """
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("LINTOMATA_HOME", str(home))

    def add(kind: str, path: Path) -> str:
        code = cli.main([kind, "add", str(path)])
        out = capsys.readouterr().out
        assert code == 0, out
        return out.split()[0]  # `<id>  <이름>  (<종류>) 등록됨`

    script = work / "count.py"
    _write(script, 1)
    script_id = add("script", script)

    node = work / "count.json"
    node.write_text(
        json.dumps({**NODE, "script": f"${{ref.{script_id}}}"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (work / "count.test.json").write_text(
        json.dumps({**NODE_TEST, "node": str(node)}, ensure_ascii=False), encoding="utf-8"
    )
    node_id = add("node", node)

    code = cli.main(["node", "test", node_id])
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()

    # 등록소가 pyc 를 흘리지 않았다 — 흘렸다면 아래 update 가 그것을 되살린다.
    registry_script = home / SUBDIRS["script"] / f"{script_id}.py"
    assert list((home / SUBDIRS["script"]).rglob("*.pyc")) == []

    stamp = _stamp(registry_script)
    _write(script, 2)
    code = cli.main(["script", "update", script_id, str(script)])
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()
    # 크기가 같고 mtime 까지 같다 — pyc 무효화가 절대 걸리지 않는 조건.
    _freeze_mtime(registry_script, stamp)

    code = cli.main(["node", "test", node_id])
    out = capsys.readouterr().out
    assert code != 0, f"`N = 2` 인데 `N = 1` 기대가 통과했다 — 거짓 통과다:\n{out}"
    # 기댓값 불일치는 단위테스트 하네스가 `LNT-TEST-004` **오류**로 낸다 (종료 코드 2).
    assert "LNT-TEST-004" in out, out
    assert "Expected: {'n': 1} / actual: {'n': 2}" in out, out
