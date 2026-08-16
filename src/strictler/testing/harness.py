"""노드 단위테스트 실행 (`schema.md` 14절).

### 이 모듈의 자리 — **별개 검사 카테고리**다

| 카테고리 | 검사 대상 | 묻는 것 | 어디서 |
|---|---|---|---|
| 프로그램 검사 | Target | 기획대로 돌아가는가 | Spec 실행 |
| **Perceive 스크립트 검사** | **Perceive 스크립트** | **개념을 제대로 인식하는가** | **여기** |

*"이 HTML 을 주면 버튼을 3개로 인식하는가"* 가 정확히 이것이다. Perceive 스크립트가
틀리면 검사 전체가 **조용히** 무의미해지므로 별도 카테고리로 둔다. 별도 파이프라인은
필요 없다 — `.test.json` 이 하는 일이 이미 그것이다.

### 등록 검사와 다르다 — **스크립트를 실제로 돌린다**

| | 스크립트를 | 잡는 것 |
|---|---|---|
| 등록/수정 시 검사 (`checks.*`) | **안 돌린다** | 선언·형식·금지 패턴 |
| **단위테스트 (여기)** | **돌린다** | 선언한 대로 실제로 동작하는가 |

**pydantic 경계 검증이 실제 값을 만나는 자리**가 여기와 `engine.exec` 둘뿐이다.

### 기본 제공이 확인하는 것 — 케이스마다 순서대로

| | 확인 | 실패하면 |
|---|---|---|
| 1 | `args` 가 스크립트의 `Args` 선언에 맞는가 | **테스트 정의가 잘못됨** (`STR-TEST-001`) |
| 2 | `runNode` 가 예외 없이 끝나는가 | 오류 (`STR-TEST-002`) |
| 3 | `returnResult()` 반환값이 선언된 출력 타입에 맞는가 | 오류 (`STR-TEST-003`) |

**1번을 따로 세는 이유:** 스크립트가 아니라 **테스트 쪽이 틀린 경우**라 에러 메시지가
달라야 한다. AI 가 fixture 를 잘못 썼는지 스크립트를 잘못 썼는지 구분되어야 자기 수정이 된다.

`expect` 를 준 케이스는 값 대조까지 간다 (`STR-TEST-004`). 안 주면 타입만 본다 —
**기대값을 안 써도 타입 검증은 공짜로 따라온다**, 그게 "기본 제공" 의 의미다.

### 노드 타입별로 추가되는 기본 검사

- **Action — 값 동일성.** `input == output` 이 계약이므로 타입이 아니라 **값**이 같은지를
  자동 검사한다. 사용자가 `expect` 를 안 써도 된다 — **기대값이 곧 입력**이다 (`STR-TEST-005`).
- **Reckon — 기댓값 반응성.** "기댓값 하드코딩 금지" 는 정적으로는 `Args.params` 에 필드가
  *있는지*까지만 본다. 받아놓고 안 쓰면 못 잡는다. `input` 이 같고 `params` 만 다른
  대조쌍이 없으면 **경고**(`STR-TEST-006`), 있는데 판정이 전부 같으면 **오류**(`STR-TEST-007`).
  → **정적으로는 못 잡는 하드코딩을 여기서 잡는다.**

### 결정성 검사는 하지 않는다

같은 입력으로 두 번 돌려 같은 결과가 나오는지 보는 건 값싸고 강력하지만,
**Perceive 안에서 AI 를 부르면 당연히 실패한다.** "노드 내부는 input/output 만 맞추면
된다" 와 정면으로 충돌하므로 하지 않는다 (`schema.md` 16절 — 폐기된 안).

### ★ `STR-TEST-006` 의 `status` 가 `violation` 인 이유

`Status` 는 `pass`/`violation`/`not_run`/`error` **넷이 전부**이고 `warning` 이 없다
(`errors.py` — 확정). 그래서 규칙표의 "경고 / 오류" 라는 **세기 차이**를 이 어휘로 옮긴다:

| 규칙 | status | 왜 |
|---|---|---|
| `-006` 대조쌍 없음 (**경고**) | `violation` | 테스트 커버리지 문제 — **정상 결과**다. 도구는 제대로 돌았다 (종료 코드 1) |
| `-007` 기댓값 무반응 (**오류**) | `error` | 스크립트가 기댓값을 안 쓴다 — 검사 자체가 무의미해진 것 (종료 코드 2) |

새 상태를 만들지 않는다. 4상태는 `schema.md` 9절이 확정한 것이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from strictler import refs, rules
from strictler.checks import pipeline as pipeline_checks
from strictler.checks.node import check_node, findings_of, load_node, resolve_script, shape_findings
from strictler.checks.script import ScriptContract
from strictler.engine import drive as drive_loop
from strictler.engine import exec as node_exec
from strictler.engine.runtime import VERDICT_PASSED
from strictler.errors import Finding, StrictlerError
from strictler.model import Node, NodeTest, TestCase
from strictler.store.entries import Store
from strictler.typesys.registry import TypeKey

__all__ = [
    "FILE_KEY",
    "load_node_test",
    "run_node_test",
    "check_requested_node",
    "run_case",
    "materialize_args",
    "check_action_transparency",
    "check_reckon_contrast",
]


FILE_KEY = "$file"
"""`bytes` fixture 의 표식 — `{"$file": "<절대경로>"}`.

스크린샷 같은 `bytes` 필드는 JSON 에 담을 수 없다. 경로로 주고 여기서 읽어 채운다.
경로 규칙(`refs.expand_path`)이 그대로 적용된다 — 절대경로 강제, 환경변수 전개."""

_ARGS = "Args"
"""진입점 인자 dataclass 의 고정 이름 (`schema.md` 6절)."""


# ── 로드 ─────────────────────────────────────────────────────────────────────


def load_node_test(path: Path, env: Mapping[str, str]) -> tuple[NodeTest | None, list[Finding]]:
    """`<노드파일>.test.json` 을 로드한다. `node` 자리에 경로 규칙을 적용한다.

    **JSON 으로 읽히지도 않으면 `StrictlerError`** — 위반이 아니라 도구가 못 돈 것이다.
    형태가 스키마와 다른 것(모르는 키, 빠진 키)은 `Finding` 으로 낸다: 그건 AI 가
    읽고 고칠 수 있는 결과다.

    `env` 를 받는 이유는 `node` 가 `${env.PROJECT_ROOT}/nodes/x.json` 형태로 올 수 있기
    때문이다. **여기서는 문법과 경로 규칙만 본다** — 실재 여부는 등록소를 봐야 알 수
    있으므로 `run_node_test` 가 판정한다. 여기서 걸리면 `(None, findings)` 이라
    같은 결과가 두 번 보고되지 않는다.
    """
    label = str(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise StrictlerError(
            f"테스트 파일을 읽을 수 없습니다: {path} ({exc})\n"
            "`<노드파일>.test.json` 은 UTF-8 JSON 파일이어야 합니다."
        ) from exc
    except json.JSONDecodeError as exc:
        raise StrictlerError(
            f"테스트 파일이 JSON 이 아닙니다: {path} ({exc})\n"
            "`<노드파일>.test.json` 의 구조는 `schema.md` 14절을 따르세요."
        ) from exc

    if not isinstance(raw, Mapping):
        raise StrictlerError(
            f"테스트 파일의 최상위가 객체가 아닙니다: {path} ({type(raw).__name__})\n"
            "`{\"node\": ..., \"cases\": [...]}` 형태여야 합니다."
        )

    try:
        node_test = NodeTest.model_validate(dict(raw))
    except ValidationError as exc:
        return None, shape_findings(exc, label, "노드 테스트")

    findings = _check_node_ref(node_test.node, label, env)
    if findings:
        return None, findings
    return node_test, []


def _check_node_ref(value: str, label: str, env: Mapping[str, str]) -> list[Finding]:
    """`node` 자리의 참조 문법·경로 규칙만 본다 (실재 여부는 보지 않는다)."""
    if refs.is_ref(value):
        try:
            refs.parse_ref(value, "node")
        except StrictlerError as exc:
            return findings_of(exc, path=label)
        return []
    try:
        refs.expand_path(value, env)
    except StrictlerError as exc:
        return findings_of(exc, path=label)
    return []


# ── 실행 ─────────────────────────────────────────────────────────────────────


def run_node_test(
    node_test: NodeTest,
    *,
    store: Store,
    env: Mapping[str, str],
    node_id: str = "",
) -> list[Finding]:
    """단위테스트 전체를 돌린다. `strictler node test <id>` 의 본체.

    케이스별 결과 + 노드 타입별 추가 검사(Action 값 동일성, Reckon 대조쌍)를 합친다.

    **★ `node_id` 를 받으면 그 id 의 등록소 노드가 정본이다** (R6-1).
    `node test <id>` 로 부른 경우가 그것이다 — 요청한 것이 그 노드이므로 테스트
    정의의 `node` 필드로 **다시 해석하지 않는다.** 예전에는 해석해 버려서
    **요청한 것과 다른 노드를 돌리고 `[pass]` 를 냈다.** 통과했다고 보고하는데
    검사한 것이 다른 것이면 그건 lint 도구에서 가장 나쁜 종류의 거짓 리포트다.
    `node` 필드는 **대조용으로만** 쓰고 어긋나면 `STR-TEST-008` 이다.
    `node test <경로>` 로 부르면 `node_id` 가 비고, 그때는 `node` 필드를 따른다.

    **정적으로 막힌 것은 돌리지 않는다.** `check_node` 가 결과를 내면 그걸 그대로
    보고하고 끝낸다 — `Args` 가 없는 스크립트를 억지로 돌려봐야 원인만 뭉개진다.
    저작 순서는 *등록으로 형식을 잡고 → 테스트로 동작을 잡고* 다 (`schema.md` 14절).

    **실패는 최대한 모은다.** 한 케이스가 실패해도 나머지 케이스는 전부 돈다.
    """
    label = node_test.node
    findings: list[Finding] = []
    node_path: Path | None

    if node_id:
        # 해시를 **대조부터** 한다. 정본이 흔들렸으면 그것과 무엇을 비교해도 무의미하고,
        # 그 상태에서 `STR-TEST-008` 을 내면 엉뚱한 곳(테스트의 `node` 필드)을 고치게 된다.
        node_path, findings = drive_loop.resolve_entry(
            _ref(node_id), "node", store=store, env=env, path=node_id
        )
        if node_path is None:
            return findings
        mismatch = check_requested_node(node_test.node, node_id, store=store, env=env)
        if mismatch:
            return mismatch
        label = node_id
    else:
        node_path, findings = _resolve_node_file(node_test.node, store=store, env=env)
    if node_path is None:
        return findings

    node, load_findings = load_node(_read_json(node_path), str(node_path))
    if node is None:
        return load_findings

    # 스크립트도 마찬가지다 — **실제로 돌리는 것이 그 파일**이므로 여기가 마지막 관문이다.
    # 삭제된 id 는 `resolve_script` 가 `STR-REG-002` 로 짚는다.
    tampered = drive_loop.verify_hash(
        node.script, store=store, path=label, node_id=node.info.name
    )
    if tampered:
        return tampered

    contract, static = check_node(node, str(node_path), store=store, env=env)
    if static:
        return static
    if contract is None:  # pragma: no cover - 결과 없이 계약이 비는 경로는 없다
        return []

    script_path, script_findings = resolve_script(node, store=store, env=env)
    if script_path is None:
        return [
            item.model_copy(update={"path": item.path or label}) for item in script_findings
        ]

    results: list[Finding] = []
    outputs: list[Any] = []
    for index, case in enumerate(node_test.cases):
        where = f"{label} > cases[{index}] {case.name}"
        value, case_findings = run_case(node, contract, script_path, case, env=env)
        outputs.append(value)
        if case_findings:
            results.extend(
                item.model_copy(update={"path": item.path or where}) for item in case_findings
            )
        else:
            results.append(Finding(status="pass", path=where, node=node.info.name))

    if node.type == "reckon":
        results.extend(
            item.model_copy(
                update={"path": item.path or label, "node": item.node or node.info.name}
            )
            for item in check_reckon_contrast(list(node_test.cases), outputs)
        )
    return results


def check_requested_node(
    declared: str, node_id: str, *, store: Store, env: Mapping[str, str]
) -> list[Finding]:
    """테스트의 `node` 가 **요청한 노드**를 가리키는지 대조한다 (`STR-TEST-008`).

    `node test <id>` 로 부르면 그 id 의 등록소 노드가 정본이므로 여기서 하는 일은
    **대조뿐이다** — 실행 대상을 고르지 않는다. 그래서 `node` 를 실행 대상 경로로
    해석하지 않고, 원본이 지워져 있어도 단위테스트는 그대로 돈다 (R5-2 의 목표).

    | 테스트의 `node` | 대조 |
    |---|---|
    | `${ref.<id>}` | id 를 그대로 비교한다 |
    | 등록소 사본 경로 | 같은 파일이므로 통과 |
    | 그 밖의 경로 | 파일이 있으면 등록소 사본과 **내용**을 비교한다 |
    | 그 밖의 경로인데 파일이 없다 | **대조하지 않는다** — 등록 후 원본을 지우는 것이 정상이다 |

    내용으로 비교하는 이유는 등록소가 원본 경로를 기억하지 않기 때문이다. 이름이
    아니라 정의가 같은지를 묻는 것이 이 자리의 질문이기도 하다.
    """
    canonical = store.path_of(node_id)

    if refs.is_ref(declared):
        try:
            refs.parse_ref(declared, "node")
        except StrictlerError as exc:  # pragma: no cover - 로드 단계가 이미 잡는다
            return findings_of(exc, path=declared)
        if declared[len("${ref.") : -1] == node_id:
            return []
        return _mismatch(node_id, declared)

    try:
        path = refs.expand_path(declared, env)
    except StrictlerError as exc:  # pragma: no cover - 로드 단계가 이미 잡는다
        return findings_of(exc, path=declared)
    if path == canonical:
        return []
    try:
        same = path.read_bytes() == canonical.read_bytes()
    except OSError:
        # 읽을 수 없으면 대조할 것이 없다. 정본은 어차피 등록소 노드다 —
        # 등록 후 원본을 지우는 것이 정상 사용법이므로 여기서 실패로 보지 않는다.
        return []
    return [] if same else _mismatch(node_id, declared)


def _mismatch(node_id: str, declared: str) -> list[Finding]:
    return [
        rules.finding(
            "STR-TEST-008",
            path=node_id,
            fields={"requested": node_id, "declared": declared},
        )
    ]


def _resolve_node_file(
    value: str, *, store: Store, env: Mapping[str, str]
) -> tuple[Path | None, list[Finding]]:
    """테스트가 가리키는 노드 파일을 찾는다.

    `${ref.nd_...}` 면 **등록소 해석을 `engine.drive` 에 맡긴다** — `check` 와 같은
    함수를 써야 등록소 무결성 판정이 갈리지 않는다 (R4-1 이 겪은 사고가 그것이다).
    거기서 `STR-REG-002`(삭제된 id) / `STR-REG-001`(등록 이후 직접 수정) 이 나온다.

    경로면 경로 규칙으로 푼다. 없으면 `STR-REF-002` — *"`source` 가 가리키는 노드를
    찾을 수 없다"* 와 같은 자리이므로 그 규칙을 그대로 쓴다. **등록소 밖 파일에는
    대조할 해시가 없다.**
    """
    if refs.is_ref(value):
        return drive_loop.resolve_entry(value, "node", store=store, env=env, path=value)

    try:
        path = refs.expand_path(value, env)
    except StrictlerError as exc:
        return None, findings_of(exc, path=value)

    if not path.is_file():
        return None, [rules.finding("STR-REF-002", path=value, fields={"source": str(path)})]
    return path, []


def _ref(entry_id: str) -> str:
    """id 를 참조 문법으로 되돌린다 — `engine.drive` 의 입구가 `${ref.<id>}` 라서다.

    `node test <id>` 로 부르면 id 를 직접 받지만, 해석·해시 대조는 `check` 와
    **같은 함수**를 써야 한다. 여기서 대조를 새로 짜면 두 벌이 되어 갈린다.
    """
    return "${ref." + entry_id + "}"


def _read_json(path: Path) -> dict[str, Any]:
    """노드 JSON 을 읽는다. 못 읽으면 **오류** — 위반이 아니다."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictlerError(
            f"노드 파일을 읽을 수 없습니다: {path} ({exc})\n"
            "노드 파일은 UTF-8 JSON 이어야 합니다."
        ) from exc
    if not isinstance(raw, Mapping):
        raise StrictlerError(
            f"노드 파일의 최상위가 객체가 아닙니다: {path} ({type(raw).__name__})"
        )
    return dict(raw)


def run_case(
    node: Node,
    contract: ScriptContract,
    script_path: Path,
    case: TestCase,
    *,
    env: Mapping[str, str],
) -> tuple[Any, list[Finding]]:
    """케이스 하나를 돌린다. 반환값과 결과들을 함께 준다.

    반환값은 Reckon 대조쌍 검사가 이어서 쓴다. **믿을 수 없는 값은 `None` 으로 준다** —
    타입이 안 맞는 출력으로 반응성을 논하면 결론이 거짓이 된다.

    `path` 는 비워 둔다 — 몇 번째 케이스인지는 부르는 쪽이 안다 (`run_node_test`).
    """
    who = node.info.name
    registry, registry_findings = pipeline_checks.build_registry([contract], contract.path)
    if registry is None:
        return None, [
            item.model_copy(update={"node": item.node or who}) for item in registry_findings
        ]

    # ① fixture 가 `Args` 선언에 맞는가 — **테스트 쪽이 틀린 경우**다.
    try:
        raw = materialize_args(case.args, contract, env)
    except StrictlerError as exc:
        return None, [_fixture_finding(who, exc.message)]
    try:
        registry.to_value(TypeKey(contract.path, _ARGS), raw)
    except ValidationError as exc:
        return None, [_fixture_finding(who, f"{contract.path}\n{exc}")]
    except StrictlerError as exc:
        return None, [_fixture_finding(who, exc.message)]

    try:
        module = node_exec.load_script(script_path)
    except StrictlerError as exc:
        return None, [Finding(status="error", node=who, message=exc.message)]

    try:
        args = node_exec.build_args(
            module,
            contract,
            input_value=raw.get("input"),
            params=raw.get("params"),
            state=raw.get("state"),
        )
    except StrictlerError as exc:
        return None, [_fixture_finding(who, exc.message)]

    # ② `runNode` 가 예외 없이 끝나는가.
    try:
        output = node_exec.invoke(module, args)
    except StrictlerError as exc:
        return None, [rules.finding("STR-TEST-002", node=who, fields={"exc": exc.message})]

    # ③ 반환값이 선언된 출력 타입에 맞는가.
    mismatched = node_exec.validate_output(contract, output, registry, path="", node=who)
    if mismatched:
        return None, [
            _with_detail(
                rules.finding(
                    "STR-TEST-003",
                    node=who,
                    fields={
                        "declared": contract.output_type or "(선언 없음)",
                        "actual": _describe(output),
                    },
                ),
                "\n".join(item.message for item in mismatched),
            )
        ]

    findings: list[Finding] = []

    # ④ `expect` 를 준 케이스만 값까지 본다 (커스텀 층).
    if case.expect is not None:
        try:
            expected = materialize_args(case.expect, contract, env)
        except StrictlerError as exc:
            return output, [_fixture_finding(who, exc.message)]
        actual = _plain(output)
        if _plain(expected) != actual:
            findings.append(
                rules.finding(
                    "STR-TEST-004",
                    node=who,
                    fields={"expect": _repr(expected), "actual": _repr(actual)},
                )
            )

    # ⑤ 노드 타입별 추가 — Action 은 `expect` 없이도 값 동일성을 본다.
    if node.type == "action":
        # 노드 이름을 여기서 채운다 — 다른 TEST 규칙은 전부 `node` 가 차 있는데
        # Action 결과만 비면 리포트의 노드 칸이 그 줄에서만 빈다 (R6-3).
        findings.extend(
            item.model_copy(update={"node": item.node or who})
            for item in check_action_transparency(
                case, getattr(args, "input", None), output
            )
        )

    return output, findings


# ── fixture ──────────────────────────────────────────────────────────────────


def materialize_args(
    raw: Mapping[str, Any],
    contract: ScriptContract,
    env: Mapping[str, str],
) -> Any:
    """JSON fixture 를 **실제 값으로** 만든다 — `bytes` 자리를 파일에서 읽어 채운다.

    `{"$file": "<절대경로>"}` 를 만나면 그 파일을 바이트로 읽어 그 자리에 넣는다.
    경로 규칙 그대로다(`refs.expand_path`) — 절대경로 강제, `~`·환경변수 전개.

    **`Args` 인스턴스를 만드는 것은 `engine.exec.build_args` 다.** 그건 스크립트가
    선언한 클래스가 필요해서 **모듈을 로드해야** 하고, 여기는 모듈을 모른다.
    이 함수가 만드는 것은 그 재료 — `{"input": ..., "params": ..., "state": ...}` 다.
    (같은 함수를 `expect` 에도 쓴다. `bytes` 를 기대값으로 적는 자리도 같은 문법이다)

    읽기 실패는 **테스트 정의가 잘못된 것**이라 `StrictlerError` 로 던진다 —
    부르는 쪽이 `STR-TEST-001` 로 바꾼다.

    **키가 `Args` 선언에 맞는지는 여기서 보지 않는다.** 그건 `Args` 를 pydantic 모델로
    세워 대조하는 자리(`run_case` ①)의 일이고, 거기가 필드 타입까지 함께 본다.
    두 곳에서 보면 같은 결과가 두 번 나온다.
    """
    return {name: _materialize(value, env, contract) for name, value in raw.items()}


def _materialize(value: Any, env: Mapping[str, str], contract: ScriptContract) -> Any:
    """`$file` 표식을 재귀적으로 바이트로 바꾼다."""
    if isinstance(value, Mapping):
        if FILE_KEY in value:
            return _read_bytes(value, env, contract)
        return {key: _materialize(item, env, contract) for key, item in value.items()}
    if isinstance(value, list):
        return [_materialize(item, env, contract) for item in value]
    return value


def _read_bytes(value: Mapping[str, Any], env: Mapping[str, str], contract: ScriptContract) -> bytes:
    if len(value) != 1:
        raise StrictlerError(
            f"`{FILE_KEY}` 는 그 객체의 유일한 키여야 합니다: {sorted(value)} ({contract.path})\n"
            f'`bytes` 필드는 `{{"{FILE_KEY}": "<절대경로>"}}` 로만 씁니다.'
        )
    target = value[FILE_KEY]
    if not isinstance(target, str):
        raise StrictlerError(
            f"`{FILE_KEY}` 의 값이 경로 문자열이 아닙니다: {target!r} ({contract.path})"
        )
    path = refs.expand_path(target, env)  # 경로 규칙 위반은 규칙 id 를 달고 나간다
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StrictlerError(
            f"fixture 파일을 읽을 수 없습니다: {path} ({exc})\n"
            f'`{FILE_KEY}` 가 가리키는 파일이 실재해야 합니다.'
        ) from exc


# ── 노드 타입별 추가 검사 ────────────────────────────────────────────────────


def check_action_transparency(case: TestCase, input_value: Any, output_value: Any) -> list[Finding]:
    """Action 노드의 **값 동일성** 검사 (`STR-TEST-005`).

    Action 은 데이터를 그대로 통과시켜야 한다 — 부작용만 일으키고 값은 건드리지 않는다.
    `input == output` 이 계약이므로 **기대값이 곧 입력**이고, 사용자가 `expect` 를 쓰지
    않아도 자동으로 검사된다.

    비교는 **표현을 벗겨낸 값**으로 한다. 앞단 dataclass 와 반환 dataclass 는 이름이
    달라도 되고(타입 동일성은 구조로 판정한다), 같은 구조면 같은 값이어야 한다.

    입력이 없으면 대조할 것이 없다 — `Args.input` 없는 Action 은 `STR-CONTRACT-006` 이
    등록 시점에 이미 잡는다.
    """
    if input_value is None:
        return []
    given = _plain(input_value)
    got = _plain(output_value)
    if given == got:
        return []
    return [
        _with_detail(
            rules.finding("STR-TEST-005", fields={}),
            f"케이스: {case.name}\n입력: {_repr(given)}\n반환: {_repr(got)}",
        )
    ]


def check_reckon_contrast(
    cases: list[TestCase],
    outputs: list[Any],
) -> list[Finding]:
    """Reckon 노드의 **기댓값 반응성** 검사 (`STR-TEST-006` 경고 / `-007` 오류).

    `input` 이 같고 `params` 만 다른 대조쌍을 찾아 **판정이 실제로 갈리는지** 본다.
    값을 흔들어보는 것만으론 안 된다 — `expected=3` 도 `expected=4` 도 실제가 2개면
    둘 다 위반이라 결과가 같다. **통과하는 기댓값과 위반하는 기댓값이 둘 다 있어야**
    반응성이 증명된다.

    | 상태 | 결과 |
    |---|---|
    | 판정이 갈리는 쌍이 하나라도 있다 | 통과 — 기댓값이 실제로 쓰인다 |
    | 대조쌍 자체가 없다 | `STR-TEST-006` (경고 = `violation`) |
    | 대조쌍은 있는데 판정이 전부 같다 | `STR-TEST-007` (오류) — **기댓값 하드코딩** |

    판정을 읽을 수 없는 케이스(실패했거나 출력에 `passed` 가 없는 것)는 **쌍으로 세지
    않는다.** 못 돈 케이스를 근거로 "기댓값을 안 쓴다" 고 단정하면 거짓 리포트가 된다.
    """
    verdicts = [_verdict_of(value) for value in outputs]

    groups: dict[str, list[int]] = {}
    for index, case in enumerate(cases):
        if index >= len(verdicts) or verdicts[index] is None:
            continue
        groups.setdefault(_key(case.args.get("input")), []).append(index)

    pairs: list[tuple[int, int]] = []
    for members in groups.values():
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                if _key(cases[left].args.get("params")) != _key(cases[right].args.get("params")):
                    pairs.append((left, right))

    if any(verdicts[left] != verdicts[right] for left, right in pairs):
        return []

    if not pairs:
        return [
            _with_detail(
                rules.finding("STR-TEST-006", status="violation", fields={}),
                "`input` 이 같고 `params` 만 다른 케이스 쌍이 없습니다 "
                f"(케이스 {len(cases)}개 중 판정을 읽을 수 있는 것 "
                f"{sum(1 for item in verdicts if item is not None)}개).",
            )
        ]

    left, right = pairs[0]
    return [
        _with_detail(
            rules.finding("STR-TEST-007", fields={}),
            f"`{cases[left].name}` 과 `{cases[right].name}` 은 `params` 가 다른데 "
            f"판정이 둘 다 {'통과' if verdicts[left] else '위반'}입니다.\n"
            f"params: {_repr(cases[left].args.get('params'))} vs "
            f"{_repr(cases[right].args.get('params'))}",
        )
    ]


def _verdict_of(output: Any) -> bool | None:
    """Reckon 출력에서 판정을 읽는다. 읽을 수 없으면 `None`.

    필드 이름은 `engine.runtime` 이 정본이다 — 여기서 다시 정의하면 두 벌이 된다.
    """
    if output is None:
        return None
    try:
        data = node_exec.as_mapping(output)
    except StrictlerError:
        return None
    value = data.get(VERDICT_PASSED)
    return value if isinstance(value, bool) else None


# ── 값 표현 ──────────────────────────────────────────────────────────────────


def _plain(value: Any) -> Any:
    """dataclass 껍데기를 벗겨 **비교 가능한 순수 값**으로 만든다.

    타입 동일성을 구조로 판정하므로(`schema.md` 7절) 비교도 구조로 한다 —
    클래스 이름이 달라도 같은 필드에 같은 값이면 같다.
    """
    if isinstance(value, (str, bytes, bool, int, float)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    try:
        data = node_exec.as_mapping(value)
    except StrictlerError:
        return value
    return {key: _plain(item) for key, item in data.items()}


def _key(value: Any) -> str:
    """fixture 조각 하나를 비교용 문자열로. JSON 이므로 정렬만 하면 결정적이다."""
    return json.dumps(_plain(value), sort_keys=True, ensure_ascii=False, default=repr)


def _repr(value: Any) -> str:
    return repr(_plain(value))


def _describe(value: Any) -> str:
    """실제 반환값의 **모양**을 한 줄로. 타입 불일치 메시지에 쓴다."""
    if value is None:
        return "(없음)"
    try:
        data = node_exec.as_mapping(value)
    except StrictlerError:
        return f"{type(value).__name__} ({value!r})"
    fields = ", ".join(f"{name}: {type(item).__name__}" for name, item in data.items())
    return f"{type(value).__name__}({fields})"


def _with_detail(finding: Finding, detail: str) -> Finding:
    """규칙 문구 뒤에 이 자리에서만 알 수 있는 사실을 덧붙인다.

    규칙 문구는 테이블 그대로 두고(리포트가 규칙끼리 비교 가능해야 한다) 구체적인
    값만 뒤에 붙인다. 읽는 주체가 AI 이므로 **무엇이 어떻게 달랐는지**가 곧 자기 수정
    루프의 성능이다.
    """
    return finding.model_copy(update={"message": f"{finding.message}\n{detail}"})


def _fixture_finding(node: str, detail: str) -> Finding:
    """`STR-TEST-001` — **스크립트가 아니라 테스트 정의가 잘못된 경우.**"""
    return _with_detail(rules.finding("STR-TEST-001", node=node, fields={}), detail)
