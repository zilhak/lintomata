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

⚠ 이 모듈은 현재 **파싱 구조만** 완성돼 있다. 각 핸들러 본체는 Step 4 에서 배선한다.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from strictler.model import EntryKind

__all__ = ["build_parser", "main"]


KINDS: tuple[EntryKind, ...] = ("script", "node", "pipeline", "spec")

_KIND_LABEL = {
    "script": "스크립트 (.py) — 실제 동작 코드",
    "node": "노드 (JSON) — 동작 정의",
    "pipeline": "파이프라인 (JSON) — 노드들의 DAG 구성",
    "spec": "Spec (JSON) — 기획",
}


# ── 핸들러 (Step 4 에서 구현) ────────────────────────────────────────────────


def cmd_add(args: argparse.Namespace) -> int:
    """`strictler <종류> add <파일>` — 정적 검사 후 등록. 통과해야 저장된다.

    `schema.md` 2·13절. `checks.check_registration` → `store.Store.add` 로 이어진다.
    """
    raise NotImplementedError("Step 4에서 구현")


def cmd_list(args: argparse.Namespace) -> int:
    """`strictler <종류> list` — 목록. **깨진 구성을 표시한다.**

    참조 깨짐(`STR-REG-004`, 대상 삭제)과 검증 깨짐(`STR-REG-005`, 대상 수정)
    두 종류를 구분해 낸다. `schema.md` 2절.
    """
    raise NotImplementedError("Step 4에서 구현")


def cmd_show(args: argparse.Namespace) -> int:
    """`strictler <종류> show <id>` — 상세. 내용·해시·참조 관계. `schema.md` 2절."""
    raise NotImplementedError("Step 4에서 구현")


def cmd_update(args: argparse.Namespace) -> int:
    """`strictler <종류> update <id> <파일>` — 내용 교체. **id 유지.**

    수정의 비용은 참조가 아니라 검증에 있다 — 참조가 멀쩡한 채로 검증만 조용히
    무효화되므로 **상위를 전이적으로 재검증한다**. `schema.md` 2절.
    """
    raise NotImplementedError("Step 4에서 구현")


def cmd_remove(args: argparse.Namespace) -> int:
    """`strictler <종류> remove <id>` — 삭제. **참조가 있어도 막지 않는다.**

    막으면 교착이 생긴다(하위를 고치려면 상위를 먼저 고쳐야 하는데 상위는 하위
    때문에 못 고친다). 대신 목록 조회에서 깨짐을 드러낸다. `schema.md` 2절.
    """
    raise NotImplementedError("Step 4에서 구현")


def cmd_node_test(args: argparse.Namespace) -> int:
    """`strictler node test <id>` — 노드 단위테스트. **실제로 스크립트를 돌린다.**

    등록 검사(형식)와 성격이 다르므로 별도 명령이다. `schema.md` 14절.
    """
    raise NotImplementedError("Step 4에서 구현")


def cmd_check(args: argparse.Namespace) -> int:
    """`strictler check <spec-id>` — 검사 실행. `schema.md` 11·13절.

    한 `plan` 항목이 실패해도 다른 항목은 전부 돈다. 실패의 여파는 `not_run` 이다.
    """
    raise NotImplementedError("Step 4에서 구현")


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
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
