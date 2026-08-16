"""CLI 표면 — 등록소가 중심이다 (`schema.md` 2절).

**종류 넷에 CRUD 가 완전하다.** `<종류>` = `script` / `node` / `pipeline` / `spec`

    strictler <종류> add    <파일>          정적 검사 후 등록. 통과해야 저장된다. id 발급
    strictler <종류> list                   목록. 깨진 구성 표시
    strictler <종류> show   <id>            상세 — 내용·해시·참조 관계
    strictler <종류> update <id> <파일>     내용 교체. id 유지. 상위 전이적 재검증
    strictler <종류> remove <id>            삭제. 참조가 있어도 막지 않는다

실행 계열은 따로 선다:

    strictler node test <id>                노드 단위테스트 (실제 실행)
    strictler check <spec-id>               검사 실행

MCP 서버가 같은 표면을 그대로 노출한다 — AI 가 쓰고 등록하면 그 자리에서 걸리는 것이
저작 루프의 핵심이다.

### 종료 코드 — `schema.md` 9절의 4상태와 맞춘다

| 코드 | 의미 |
|---|---|
| `0` | 통과만 있음 |
| `1` | **위반 또는 not run** 이 있음 — **정상 결과다. 도구는 제대로 돌았다** |
| `2` | **오류**(도구가 못 돌았다) 또는 사용법 오류 |

**`1` 과 `2` 를 섞지 않는다.** 위반은 lint 가 제 일을 한 것이고, 오류는 도구가 못 돈 것이다.

⚠ **등록소의 깨짐 표시(`STR-REG-004`/`-005`)는 `1` 이다.** `Finding.status` 는 `error` 지만
그건 *그 구성이 지금 성립하지 않는다*는 뜻이지 *도구가 못 돌았다*는 뜻이 아니다 —
`schema.md` 2절이 **"깨진 상태도 정상적으로 보고되는 결과"** 라고 못 박았고, 삭제도 수정도
막지 않는 것이 그 때문이다. `list`/`show`/`update`/`remove` 는 자기가 할 일을 끝냈으므로
`2`(도구가 못 돌았다)를 낼 수 없다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from strictler import rules
from strictler.errors import Finding, StrictlerError
from strictler.model import EntryKind
from strictler.report import Report, build_report, render_json, render_text
from strictler.store.entries import RegistryEntry, Store
from strictler.store.graph import RefGraph

__all__ = ["build_parser", "main"]


KINDS: tuple[EntryKind, ...] = ("script", "node", "pipeline", "spec")

_ID_PREFIX: dict[str, str] = {
    "script": "sc_",
    "node": "nd_",
    "pipeline": "pl_",
    "spec": "sp_",
}

_KIND_LABEL = {
    "script": "스크립트 (.py) — 실제 동작 코드",
    "node": "노드 (JSON) — 동작 정의",
    "pipeline": "파이프라인 (JSON) — 노드들의 DAG 구성",
    "spec": "Spec (JSON) — 기획",
}


# ── 공용 ─────────────────────────────────────────────────────────────────────


def _store(args: argparse.Namespace) -> Store:
    """`--home` 또는 `$STRICTLER_HOME` (기본 `~/.strictler`) 의 등록소.

    `--home` 도 **절대경로여야 한다** — 등록소가 cwd 에 따라 달라지면 등록의 의미가
    없어진다 (`schema.md` 3절 경로 규칙). `~` 는 cwd 와 무관하므로 허용한다.
    """
    raw = str(getattr(args, "home", "") or "").strip()
    if not raw:
        return Store()
    home = Path(os.path.expanduser(raw))
    if not home.is_absolute():
        raise StrictlerError(
            f"--home 이 절대경로가 아닙니다: {raw}\n"
            "등록소 경로는 cwd 와 무관해야 합니다. `/srv/strictler` 나 `~/.strictler` "
            "처럼 절대경로로 주세요."
        )
    return Store(home)


def _source(value: str) -> Path:
    """CLI 인자로 받은 파일 경로. **여기는 셸이 주는 자리라 상대경로를 허용한다.**

    절대경로 규칙은 Spec·파이프라인 *문서 안에* 적히는 경로에 걸린다 — 그것이
    cwd 의존성을 없애는 자리다. `strictler script add ./detect_buttons.py` 는
    `schema.md` 2절의 예시 그대로다.
    """
    return Path(os.path.expanduser(value))


def _exit_code(findings: Sequence[Finding]) -> int:
    """결과 목록 → 종료 코드. **위반(1) 과 오류(2) 를 섞지 않는다.**"""
    if any(f.status == "error" for f in findings):
        return 2
    if any(f.status in ("violation", "not_run") for f in findings):
        return 1
    return 0


def _emit(findings: Sequence[Finding], *, as_json: bool = False) -> Report:
    """결과를 사람이 읽는 형태 또는 `report.render_json` 으로 낸다."""
    report = build_report(list(findings))
    print(render_json(report) if as_json else render_text(report))
    return report


def _print_broken(findings: Sequence[Finding]) -> None:
    """등록소의 **깨짐 표시**를 낸다 — 4상태 요약을 붙이지 않는다.

    `STR-REG-004`/`-005` 는 `Finding.status` 가 `error` 지만 그건 *그 구성이 지금
    성립하지 않는다*는 뜻이지 *도구가 못 돌았다*는 뜻이 아니다. 4상태 요약 헤더를
    붙이면 `error 1` 이라고 적어놓고 종료 코드는 `1` 을 내는 모순이 눈에 보인다 —
    성격이 다른 산출물이므로 형식도 섞지 않는다 (`schema.md` 2절).
    """
    for item in findings:
        where = " > ".join(part for part in (item.path, item.node) if part)
        print(f"  {where} ({item.rule_id})" if where else f"  ({item.rule_id})")
        for line in item.message.splitlines():
            if line:
                print(f"    {line}")


def _report_exit_code(report: Report) -> int:
    """리포트 요약 → 종료 코드."""
    if report.summary.error:
        return 2
    if report.summary.violation or report.summary.not_run:
        return 1
    return 0


def _entry_of(store: Store, entry_id: str, kind: EntryKind) -> RegistryEntry:
    """id 로 항목을 꺼내되 **그 자리가 요구하는 종류인지** 확인한다.

    `strictler node show pl_c9d0e1f2` 는 사용법 오류다 — 접두가 종류를 말한다.
    """
    entry = store.show(entry_id)
    if entry.kind != kind:
        raise _kind_mismatch(entry_id, entry.kind, kind)
    return entry


def _kind_mismatch(entry_id: str, actual: str, expected: EntryKind) -> StrictlerError:
    """자리가 요구하는 종류와 id 의 종류가 다르다 — **사용법 오류**다."""
    return StrictlerError(
        f"이 자리에는 {expected} 가 와야 하는데 {entry_id} 는 {actual} 입니다.\n"
        f"접두가 종류를 말합니다 (`sc_`=스크립트 `nd_`=노드 `pl_`=파이프라인 "
        f"`sp_`=Spec). `strictler {actual} <명령>` 으로 부르세요."
    )


def _marked_index(store: Store) -> tuple[dict[str, RegistryEntry], RefGraph]:
    """인덱스를 읽고 **참조 깨짐을 그 자리에서 다시 계산해** 얹는다.

    참조 깨짐은 삭제 시점에 계산할 수 없다 — 지워지는 쪽은 자기를 참조하는 상위를
    모른다. 그래서 조회할 때마다 인덱스에서 다시 판정한다. 검증 깨짐은 반대로
    수정 시점에만 계산되므로 `revalidate` 가 인덱스에 적어둔 것을 그대로 읽는다.

    **그 위에 전이를 얹는다** (R5-4) — 참조 대상이 깨졌으면 상위도 깨진 것이다.
    Spec 등록 검사는 형태만 보므로 이걸 안 하면 돌릴 수 없는 Spec 이 `○` 로 나온다.
    """
    entries = store.load_index().entries
    graph = RefGraph(entries)
    graph.broken_refs()
    graph.propagate_broken()
    return entries, graph


def _broken_mark(entry: RegistryEntry) -> str:
    """`schema.md` 2절의 목록 표기."""
    if entry.broken == "ref":
        return f"✕ 참조 깨짐 — {entry.broken_detail} 없음"
    if entry.broken == "validation":
        return f"✕ 검증 깨짐 — {entry.broken_detail}"
    return "○"


def _now_ms() -> int:
    """실행 시각 (epoch 밀리초).

    **엔진은 시각을 읽지 않는다 — 호출자가 준다.** CLI 가 바로 그 호출자다
    (`schema.md` 8절, MODULES.md 공통 규칙 6). 엔진이 직접 읽으면 테스트가
    비결정적이 되고 `${state.__startedAt}` 이 한 실행 안에서 흔들린다.
    """
    return int(time.time() * 1000)


# ── 핸들러 ───────────────────────────────────────────────────────────────────


def cmd_add(args: argparse.Namespace) -> int:
    """`strictler <종류> add <파일>` — 정적 검사 후 등록. 통과해야 저장된다.

    `schema.md` 2·13절. `checks.check_registration` → `store.Store.add` 로 이어진다.
    **순서가 계약이다** — 검사에 걸린 것은 등록소에 들어가지 않는다.
    """
    from strictler.checks import check_registration

    kind: EntryKind = args.kind
    store = _store(args)
    source = _source(args.file)

    findings = check_registration(kind, source, store)
    if findings:
        print(f"등록하지 않았습니다 — 정적 검사를 통과해야 저장됩니다: {source}")
        _emit(findings)
        return _exit_code(findings)

    entry = store.add(kind, source, name=args.name)
    print(f"{entry.id}  {entry.name}  ({entry.kind}) 등록됨")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """`strictler <종류> list` — 목록. **깨진 구성을 표시한다.**

    참조 깨짐(`STR-REG-004`, 대상 삭제)과 검증 깨짐(`STR-REG-005`, 대상 수정)
    두 종류를 구분해 낸다. `schema.md` 2절.

    **깨짐은 실패가 아니라 상태 표시다** — 그래서 `2` 가 아니라 `1` 이다.
    """
    kind: EntryKind = args.kind
    store = _store(args)
    entries, _ = _marked_index(store)
    listed = sorted(
        (entry for entry in entries.values() if entry.kind == kind),
        key=lambda entry: entry.id,
    )

    if args.json:
        print(
            json.dumps(
                [entry.model_dump() for entry in listed], ensure_ascii=False, indent=2
            )
        )
    elif not listed:
        print(f"등록된 {kind} 가 없습니다.")
    else:
        for entry in listed:
            print(f"{entry.id}  {entry.name}  {_broken_mark(entry)}")

    return 1 if any(entry.broken for entry in listed) else 0


def cmd_show(args: argparse.Namespace) -> int:
    """`strictler <종류> show <id>` — 상세. 내용·해시·참조 관계. `schema.md` 2절."""
    kind: EntryKind = args.kind
    store = _store(args)
    entry = _entry_of(store, args.id, kind)

    entries, graph = _marked_index(store)
    entry = entries.get(entry.id, entry)
    dependencies = graph.dependencies(entry.id)
    dependents = graph.dependents(entry.id)
    file_path = store.path_of(entry.id)
    content = store.read(entry.id)
    # 단위테스트는 노드와 함께 등록된다 — 있는지 없는지가 보여야 `node test <id>` 가
    # 왜 안 도는지 알 수 있다 (R5-2).
    test_path = store.test_path(entry.kind, entry.id)
    has_test = test_path is not None and test_path.is_file()

    if args.json:
        detail: dict[str, Any] = entry.model_dump()
        detail["path"] = str(file_path)
        detail["dependencies"] = dependencies
        detail["dependents"] = dependents
        detail["content"] = content
        if test_path is not None:
            detail["test"] = str(test_path) if has_test else ""
        print(json.dumps(detail, ensure_ascii=False, indent=2))
    else:
        print(f"{entry.id}  {entry.name}  ({entry.kind})")
        print(f"  상태           {_broken_mark(entry)}")
        print(f"  해시           {entry.hash}")
        print(f"  등록시각       {entry.registered_at}")
        print(f"  파일           {file_path}")
        if test_path is not None:
            print(f"  단위테스트     {test_path if has_test else '없음'}")
        print(f"  참조하는 것    {', '.join(dependencies) or '-'}")
        print(f"  참조하는 상위  {', '.join(dependents) or '-'}")
        print("--- 내용 ---")
        print(content)

    return 1 if entry.broken else 0


def cmd_update(args: argparse.Namespace) -> int:
    """`strictler <종류> update <id> <파일>` — 내용 교체. **id 유지.**

    수정의 비용은 참조가 아니라 검증에 있다 — 참조가 멀쩡한 채로 검증만 조용히
    무효화되므로 **상위를 전이적으로 재검증한다**. `schema.md` 2절.

    **재검증 실패가 수정을 막지 않는다.** 막으면 교착이 생긴다 — 하위를 고치려면
    상위를 먼저 고쳐야 하는데 상위는 하위 때문에 못 고친다.
    """
    from strictler.checks import check_registration

    kind: EntryKind = args.kind
    store = _store(args)
    _entry_of(store, args.id, kind)
    source = _source(args.file)

    findings = check_registration(kind, source, store)
    if findings:
        print(f"수정하지 않았습니다 — 새 내용도 정적 검사를 통과해야 합니다: {source}")
        _emit(findings)
        return _exit_code(findings)

    entry = store.update(args.id, source)
    print(f"{entry.id}  {entry.name}  내용 교체됨 (id 유지)")

    broken = RefGraph.build(store).revalidate(store, entry.id)
    if not broken:
        return 0
    print("상위 재검증에서 검증 깨짐이 나왔습니다 — 수정 자체는 성사됐습니다:")
    _print_broken(broken)
    return 1


def cmd_remove(args: argparse.Namespace) -> int:
    """`strictler <종류> remove <id>` — 삭제. **참조가 있어도 막지 않는다.**

    막으면 교착이 생긴다(하위를 고치려면 상위를 먼저 고쳐야 하는데 상위는 하위
    때문에 못 고친다). 대신 목록 조회에서 깨짐을 드러낸다. `schema.md` 2절.
    """
    kind: EntryKind = args.kind
    store = _store(args)
    _entry_of(store, args.id, kind)

    # 참조 깨짐은 삭제 뒤에는 계산할 수 없다 — 지워진 쪽은 자기를 참조하는 상위를
    # 모른다. 그래서 상위 목록을 **삭제 전에** 뽑아둔다.
    dependents = RefGraph.build(store).dependents(args.id)
    store.remove(args.id)
    print(f"{args.id} 를 삭제했습니다.")

    if not dependents:
        return 0
    print("이 삭제로 참조가 깨진 구성이 있습니다 (삭제는 막지 않습니다):")
    _print_broken(
        [
            rules.finding("STR-REG-004", path=dep_id, fields={"id": args.id})
            for dep_id in dependents
        ]
    )
    return 1


def cmd_node_test(args: argparse.Namespace) -> int:
    """`strictler node test <id>` — 노드 단위테스트. **실제로 스크립트를 돌린다.**

    등록 검사(형식)와 성격이 다르므로 별도 명령이다. `schema.md` 14절.

    테스트 정의는 `<노드파일>.test.json` 이고 **등록 종류가 아니라 노드 정의 묶음의
    일부다**(등록되는 종류는 스크립트·노드·파이프라인·Spec 넷으로 고정).
    그래서 `node add`/`update` 가 **노드 파일 옆의 그것을 함께 복사한다** (R5-2).

    인자는 두 가지로 받는다: 노드 id 면 등록소의 노드 파일 옆
    (`nodes/<id>.test.json`)을 보고, 파일 경로면 그 파일을 그대로 쓴다.
    **등록하지 않고 돌리는 경로를 남겨두는 것**이 후자다.
    """
    from strictler.testing import harness

    store = _store(args)
    env = os.environ
    test_path = _node_test_path(store, args.id)

    node_test, findings = harness.load_node_test(test_path, env)
    if node_test is not None:
        findings = list(findings) + harness.run_node_test(
            node_test, store=store, env=env
        )

    _emit(findings, as_json=args.json)
    return _exit_code(findings)


def _node_test_path(store: Store, value: str) -> Path:
    """`node test` 의 인자를 테스트 파일 경로로 푼다."""
    if value.startswith(_ID_PREFIX["node"]):
        entry = _entry_of(store, value, "node")
        path = store.test_path(entry.kind, entry.id)
        if path is None or not path.is_file():
            raise StrictlerError(
                f"이 노드에는 단위테스트가 등록돼 있지 않습니다: {entry.id}\n"
                "테스트 정의는 `<노드파일>.test.json` 이고 **노드와 함께 복사된다** — "
                "노드 파일 옆에 그 이름으로 두고 `strictler node add`/`update` 를 "
                "다시 하면 등록소에 함께 들어갑니다. 등록 없이 돌리려면 파일 경로를 "
                "직접 주세요: `strictler node test /abs/path/detect_buttons.test.json`"
            )
        return path

    path = _source(value)
    if not path.is_file():
        raise StrictlerError(
            f"노드 단위테스트 파일이 없습니다: {path}\n"
            "노드 id (`nd_...`) 또는 `<노드파일>.test.json` 경로를 주세요."
        )
    return path


def cmd_check(args: argparse.Namespace) -> int:
    """`strictler check <spec-id>` — 검사 실행. `schema.md` 11·13절.

    한 `plan` 항목이 실패해도 다른 항목은 전부 돈다. 실패의 여파는 `not_run` 이다.

    **등록된 Spec 은 해시만 그대로면 다시 검사하지 않는다** — 등록은 편의가 아니라
    검증 결과를 재사용하는 기제다. 반대로 경로로 준 Spec 은 검증된 적이 없으므로
    실행 전에 검사한다 (`schema.md` 2절 "경로 참조도 가능하지만 비싸다").
    """
    from strictler.engine.runtime import run_spec

    store = _store(args)
    env = os.environ

    source, spec_name, findings = _resolve_spec(store, args.spec)
    # Spec 을 못 찾았거나(등록소 무결성) 검사에 걸렸으면 그 지점에서 진행하지 않는다.
    if source is None or findings:
        _emit(findings, as_json=args.json)
        return _exit_code(findings)

    spec, load_findings = _load_spec(source)
    if spec is None:
        _emit(load_findings, as_json=args.json)
        return _exit_code(load_findings)

    report = run_spec(
        spec,
        store=store,
        env=env,
        started_at_ms=_now_ms(),
        spec_name=spec_name,
    )
    print(render_json(report) if args.json else render_text(report))
    return _report_exit_code(report)


def _resolve_spec(store: Store, value: str) -> tuple[Path | None, str, list[Finding]]:
    """`check` 의 인자를 Spec 파일로 푼다 — id 면 등록소, 아니면 경로.

    등록소 항목은 **해시를 대조한다**(`STR-REG-001`) — 정적 검사 루트를 피해
    등록소 파일을 직접 고치는 것을 막는 자리다. 삭제된 id 는 `STR-REG-002`.
    """
    from strictler.checks import check_registration

    if value.startswith(_ID_PREFIX["spec"]):
        entry = store.load_index().entries.get(value)
        if entry is None:
            return None, "", [
                rules.finding("STR-REG-002", path=value, fields={"id": value})
            ]
        if entry.kind != "spec":
            raise _kind_mismatch(value, entry.kind, "spec")
        if not store.verify_hash(entry.id):
            return None, "", [
                rules.finding("STR-REG-001", path=entry.id, fields={"id": entry.id})
            ]
        return store.path_of(entry.id), entry.name, []

    source = _source(value)
    if not source.is_file():
        raise StrictlerError(
            f"Spec 파일이 없습니다: {source}\n"
            "등록된 Spec 은 id (`sp_...`) 로, 등록 안 한 것은 파일 경로로 줍니다."
        )
    return source, source.name, check_registration("spec", source, store)


def _load_spec(source: Path) -> tuple[Any, list[Finding]]:
    """Spec JSON 을 모델로 만든다. 읽기·형태 실패는 위반이 아니라 **오류**다."""
    from pydantic import ValidationError

    from strictler.checks.node import shape_findings
    from strictler.model import Spec

    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [
            Finding(
                status="error",
                path=str(source),
                message=(
                    f"Spec 파일을 읽을 수 없습니다: {source} ({exc})\n"
                    "Spec 은 UTF-8 JSON 이어야 합니다."
                ),
            )
        ]
    try:
        return Spec.model_validate(raw), []
    except ValidationError as exc:
        return None, shape_findings(exc, str(source), "Spec")


# ── 파서 ─────────────────────────────────────────────────────────────────────


def _add_crud_subcommands(kind: EntryKind, parser: argparse.ArgumentParser) -> None:
    """한 종류에 대한 CRUD 서브커맨드를 붙인다."""
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)

    p_add = sub.add_parser("add", help="정적 검사 후 등록. 통과해야 저장된다")
    p_add.add_argument("file", help="등록할 파일 경로")
    p_add.add_argument("--name", default="", help="등록 이름 (생략 시 파일명)")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="목록. 깨진 구성 표시")
    p_list.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="상세 — 내용·해시·참조 관계")
    p_show.add_argument("id", help=f"{kind} id")
    p_show.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p_show.set_defaults(func=cmd_show)

    p_update = sub.add_parser("update", help="내용 교체. id 유지. 상위 전이적 재검증")
    p_update.add_argument("id", help=f"{kind} id")
    p_update.add_argument("file", help="새 내용 파일 경로")
    p_update.set_defaults(func=cmd_update)

    p_remove = sub.add_parser("remove", help="삭제. 참조가 있어도 막지 않는다")
    p_remove.add_argument("id", help=f"{kind} id")
    p_remove.set_defaults(func=cmd_remove)

    if kind == "node":
        p_test = sub.add_parser("test", help="노드 단위테스트 (실제 실행)")
        p_test.add_argument("id", help="node id")
        p_test.add_argument("--json", action="store_true", help="JSON 으로 출력")
        p_test.set_defaults(func=cmd_node_test)


def build_parser() -> argparse.ArgumentParser:
    """`strictler` 의 전체 argparse 트리를 만든다."""
    parser = argparse.ArgumentParser(
        prog="strictler",
        description="기획대로 돌아가는지를 검사하는 도구 — QA 의 프로그램화, lint 의 인간 버전",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예:\n"
            "  strictler script  add    ./detect_buttons.py\n"
            "  strictler node    update nd_e5f6a7b8 ./detect_buttons.json\n"
            "  strictler node    test   nd_e5f6a7b8\n"
            "  strictler pipeline list\n"
            "  strictler check   sp_3a4b5c6d\n"
        ),
    )
    parser.add_argument(
        "--home",
        default="",
        help="등록소 경로 (기본: $STRICTLER_HOME 또는 ~/.strictler)",
    )

    sub = parser.add_subparsers(dest="kind", metavar="<종류|명령>", required=True)

    for kind in KINDS:
        kind_parser = sub.add_parser(kind, help=_KIND_LABEL[kind])
        _add_crud_subcommands(kind, kind_parser)

    p_check = sub.add_parser("check", help="검사 실행")
    p_check.add_argument("spec", help="spec id (sp_...) 또는 Spec 파일 경로")
    p_check.add_argument("--json", action="store_true", help="리포트를 JSON 으로 출력")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """진입점. 반환값이 종료 코드다.

    종료 코드 규약 (`schema.md` 9절의 4상태와 맞춘다):
      0 — 통과만 있음
      1 — 위반 또는 not run 이 있음 (**정상 결과**, 도구는 제대로 돌았다)
      2 — 오류 (도구가 못 돌았다) 또는 사용법 오류

    `StrictlerError` 는 **도구가 못 돈 것**이다 (`schema.md` 9절) — 위반이 아니므로
    `2` 다. 위반과 not run 은 예외가 아니라 `Finding` 으로 돌아와 `1` 이 된다.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except StrictlerError as exc:
        print(exc.message, file=sys.stderr)
        if exc.findings:
            print(render_text(build_report(list(exc.findings))), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
