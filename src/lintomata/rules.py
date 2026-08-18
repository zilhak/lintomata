"""검사 규칙 테이블 — `LNT-<CATEGORY>-<NNN>`.

`rules.md` 전체가 근거다. 규칙 69개 (PATH 4 / REF 7 / GRAPH 3 / TYPE 7 /
CONTRACT 7 / STATE 7 / BAN 4 / DEP 3 / TOOL 2 / CONFIG 3 / CMP 4 / TEST 8 / REG 5 /
LIB 5).
**늘어나는 것이 전제다** — 카테고리별 독립 번호 공간, 번호 재사용 금지,
폐기해도 `status: deprecated` 로 남긴다.

**`guide` 는 별도 필드로 리포트에 나가지 않는다.** 에러 메시지 뒤에 이어붙는다
(`schema.md` 11절). 정적 검사가 못 잡는 것을 메우는 자리이므로,
그 문구가 곧 AI 자기 수정 루프의 성능이다.

**자리표시자는 `message` 와 `guide` 양쪽에 올 수 있다.** `rules.md` 2절의 guide 문구
자체가 `{cycle}` `{names}` `{exc}` 같은 슬롯을 갖고 있으므로 둘 다 채운다.
치환은 `str.format` 이 아니라 **`{식별자}` 형태만 골라 바꾸는 자체 치환기**다 —
guide 문구에 그대로 들어 있는 `${env.X}` `${ref.sc_...}` 같은 참조 문법을 건드리면 안 되기 때문.

**어떤 규칙이 어떤 슬롯을 요구하는지는 `Rule.slots` 에 데이터로 들어 있다.**
표로 따로 적어두면 코드와 문서가 갈라지므로 `message`+`guide` 에서 그대로 뽑는다.
`finding()`/`render()` 가 이걸로 누락을 검증한다 —
슬롯 값을 안 주면 조용히 넘어가지 않고 `LintomataError` 다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from lintomata.errors import Finding, NotRunCause, Status, LintomataError
from lintomata.locale import SLOT_RE, fill, translate
from lintomata.locale import message as _msg

__all__ = [
    "RuleWhen",
    "RuleStatus",
    "Rule",
    "RULES",
    "get_rule",
    "rules_for",
    "render",
    "finding",
]


RuleWhen = Literal[
    "node-register", "library-register", "pipeline-register", "run", "test", "list"
]
"""규칙이 도는 시점. `rules.md` 2절의 `when` 열 —
N=노드 등록, **LB=라이브러리 등록**, P=파이프라인 등록, R=실행, T=단위테스트,
그리고 목록 표시 전용(REG-004/005).

**라이브러리 등록이 별도 시점인 이유**는 검사 대상이 다르기 때문이다 — 라이브러리에는
`runNode` 도 `Args` 도 없어 노드 계약 검사가 통째로 해당 없고, 대신 노드에는 없는
제한(중첩 금지·dataclass 금지)이 걸린다 (`schema.md` 6.5절)."""

RuleStatus = Literal["active", "deprecated"]


class Rule(BaseModel):
    """규칙 엔트리 하나 (`rules.md` 1절)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    """`LNT-CONTRACT-001` 형태. 길지만 사람이 타이핑할 일이 없고, 읽는 주체가
    AI 이므로 자기 설명적인 쪽이 낫다."""

    name: str
    """사람이 읽는 이름 (`args-dataclass-missing`)."""

    since: str
    status: RuleStatus
    when: tuple[RuleWhen, ...]
    """한 규칙이 여러 시점에 돌 수 있다 (예: `LNT-PATH-001` 은 N P R)."""

    message: str
    """`{file}` 같은 자리표시자를 포함한다."""

    guide: str
    """자연어 수정 가이드. 메시지 뒤에 이어붙어 나간다. 여기에도 자리표시자가 올 수 있다."""

    slots: tuple[str, ...]
    """이 규칙이 요구하는 자리표시자 이름들 — `message`+`guide` 등장 순서.

    **손으로 적는 필드가 아니라 `_rule()` 이 문구에서 뽑는다.** 표로 따로 두면
    코드와 문서가 갈라진다. 검사기는 이걸 보고 무엇을 채워야 하는지 알 수 있고,
    `render()`/`finding()` 은 이걸로 누락을 잡는다.

    ⚠ `LNT-TYPE-004` 의 `in` 처럼 **파이썬 예약어인 슬롯**이 있다 —
    그래서 `finding()` 이 슬롯 값을 `fields` **딕셔너리**로 받는다.
    """


# `{name}` 처럼 **점 없는 식별자 하나**만 자리표시자로 본다.
# guide 문구에 그대로 들어 있는 `${env.X}` `${ref.sc_...}` 는 점이 있어 걸리지 않는다.
#
# **정의는 `locale` 에 있다** — 이것이 곧 *번역이 보존해야 할 것*의 정의이므로,
# 카탈로그 검증과 같은 것을 봐야 한다. 두 벌로 두면 갈리고, 갈린 쪽이 곧 사고다.
_SLOT_RE = SLOT_RE


def _slots_of(*templates: str) -> tuple[str, ...]:
    """문구들에서 자리표시자 이름을 등장 순서대로 뽑는다 (중복 제거)."""
    found: dict[str, None] = {}
    for template in templates:
        for name in _SLOT_RE.findall(template):
            found[name] = None
    return tuple(found)


# 시점 약어 — `rules.md` 2절 표의 `when` 열 그대로.
_N: RuleWhen = "node-register"
_LB: RuleWhen = "library-register"
_P: RuleWhen = "pipeline-register"
_R: RuleWhen = "run"
_T: RuleWhen = "test"
_L: RuleWhen = "list"

_SINCE = "0.1.0"


def _rule(
    rule_id: str,
    name: str,
    when: tuple[RuleWhen, ...],
    message: str,
    guide: str,
) -> Rule:
    return Rule(
        id=rule_id,
        name=name,
        since=_SINCE,
        status="active",
        when=when,
        message=message,
        guide=guide,
        slots=_slots_of(message, guide),
    )


_TABLE: tuple[Rule, ...] = (
    # ── PATH — 경로 규칙 ────────────────────────────────────────────────
    _rule(
        "LNT-PATH-001",
        "relative-path",
        (_N, _P, _R),
        "Not an absolute path even after expansion: {path}",
        "Every path must be absolute. Use `~` or `${env.X}`. "
        "A path that depends on the cwd cannot be used — it is what makes the same "
        "check behave differently depending on where you ran it from",
    ),
    _rule(
        "LNT-PATH-002",
        "env-undefined",
        (_N, _P, _R),
        "The referenced environment variable is not defined: {name}",
        "Define the environment variable that `${env.X}` names in the environment you "
        "run in. Paths were pushed out into environment variables precisely so that "
        "each machine and each CI can hold a different value",
    ),
    _rule(
        "LNT-PATH-003",
        "env-value-relative",
        (_R,),
        "The value of environment variable `{name}` is itself a relative path: {value}",
        "The value must be an absolute path. Something like `PROJECT_ROOT=./foo` "
        "brings the cwd dependency straight back",
    ),
    _rule(
        "LNT-PATH-004",
        "config-path-invalid",
        (_R,),
        "The value of config `{name}`, declared with `path: true`, breaks the path "
        "rule: {value}",
        "This config is declared `path: true`, so the path rule applies to it. "
        "Fill it with an absolute path",
    ),
    # ── REF — 참조 무결성 ──────────────────────────────────────────────
    _rule(
        "LNT-REF-001",
        "script-not-found",
        (_N,),
        "Cannot find the file the node points at: {script}",
        "The node's `script` and `libraries` values must be either something "
        "registered (`${ref.sc_...}` / `${ref.lb_...}`) or a path to a file that "
        "exists",
    ),
    _rule(
        "LNT-REF-002",
        "node-not-found",
        (_P,),
        "Cannot find the node `source` points at: {source}",
        "It must be a registered node (`${ref.nd_...}`) or a node file that exists. "
        "This covers every position that names a node — a pipeline's `source`, "
        "a node unit test's `node`, and so on",
    ),
    _rule(
        "LNT-REF-003",
        "input-node-unknown",
        (_P,),
        "`inputs` names a node id that is not in this pipeline: {name}",
        "Every value in `inputs` must be the `id` of a node in the same pipeline. "
        "It is the `id`, not a path to a node file",
    ),
    _rule(
        "LNT-REF-004",
        "transition-node-unknown",
        (_P,),
        "`transitions.after` names a node id that is not in this pipeline: {name}",
        "`transitions.after` must be the `id` of a node in the same pipeline",
    ),
    _rule(
        "LNT-REF-005",
        "compare-node-unknown",
        (_P,),
        "`compare` names a node id that is not in this pipeline: {name}",
        "Only the `id` of a node in this pipeline can be listed in `compare`",
    ),
    _rule(
        "LNT-REF-006",
        "malformed-reference",
        (_N, _P, _R),
        "Broken reference syntax — the namespace is missing, the namespace is "
        "unknown, or the name is empty: {ref}",
        "A reference always carries a namespace — there are exactly four: "
        "`${env.X}` / `${config.X}` / `${state.X}` / `${ref.<id>}`. Without one, "
        '"an undefined environment variable" and "a misspelled config" cannot be '
        "told apart and the error collapses into a vague one. "
        "The offending reference: {ref}",
    ),
    _rule(
        "LNT-REF-007",
        "unresolved-reference",
        (_N, _P, _R),
        "The reference syntax is fine, but it was never expanded before reaching "
        "here: {ref}",
        "By this point every reference must already be resolved. Letting an "
        'unexpanded reference through as a literal turns the cause into a misleading '
        '"file not found" further downstream. Check that no value is missing from '
        "the `config` declaration and that the order of expansion is right. "
        "The offending reference: {ref}",
    ),
    # ── GRAPH — DAG 구조 ───────────────────────────────────────────────
    _rule(
        "LNT-GRAPH-001",
        "cycle",
        (_P,),
        "The DAG has a cycle.",
        "`inputs` is what creates the dependencies. With a cycle there is no "
        "execution order to pick. The cycle: {cycle}",
    ),
    _rule(
        "LNT-GRAPH-002",
        "orphan-node",
        (_P,),
        "Node `{name}` references no node and nothing references it.",
        "This node is isolated in the graph. Wire it up with `inputs`, or remove it "
        "if it is not needed",
    ),
    _rule(
        "LNT-GRAPH-003",
        "ambiguous-input",
        (_P,),
        "`inputs` names more than one distinct upstream node: {nodes}",
        "`Args.input` is one field, so it takes one value. With two different "
        "upstream nodes in `inputs` there is no way to decide which one goes in. "
        "The upstream nodes: {nodes} — reduce them to one, or put a node in between "
        "that merges the two",
    ),
    # ── TYPE — 타입 시스템 ─────────────────────────────────────────────
    _rule(
        "LNT-TYPE-001",
        "dict-forbidden",
        (_N,),
        "`dict` is used as a type. (file: {file})",
        "Declare every composite type as a `dataclass`. Allowing `dict` makes the "
        "dataclass requirement meaningless in a single line",
    ),
    _rule(
        "LNT-TYPE-002",
        "optional-forbidden",
        (_N,),
        "`Optional` / `None` is used as a type. (file: {file})",
        "`Optional` cannot be used. Do not declare a field that may be absent — "
        "`Args` declares only the fields it actually uses",
    ),
    _rule(
        "LNT-TYPE-003",
        "unsupported-type",
        (_N,),
        "A type that is neither a primitive nor a dataclass is used: {type} "
        "(file: {file})",
        "The only usable types are `int` `float` `str` `bool` `bytes` `list[T]` "
        "and a `dataclass`",
    ),
    _rule(
        "LNT-TYPE-004",
        "io-mismatch",
        (_P,),
        "The upstream output definition and the downstream input definition differ.",
        "The two wired nodes declare different type definitions. The graph check "
        "demands **strict identity**. Upstream: {out} / downstream: {in}",
    ),
    _rule(
        "LNT-TYPE-005",
        "config-type-unknown",
        (_P,),
        "The `type` of a `config` is not in the allowed set: {type}",
        "A `config` `type` uses the same vocabulary a script does — "
        "`str` `int` `float` `bool` `bytes` `list[T]`",
    ),
    _rule(
        "LNT-TYPE-006",
        "merge-field-conflict",
        (_N, _P),
        "Taking the union of a subset connected component, one field name carries "
        "two different types: {field}",
        "Field `{field}` is typed differently across the merge candidates {names} "
        "({types}). Dataclasses in a subset relation are merged into one larger "
        "dataclass, so the same field name must carry the same type. If the concepts "
        "differ, give the fields different names",
    ),
    _rule(
        "LNT-TYPE-007",
        "dataclass-cycle",
        (_N,),
        "A dataclass references itself, directly or indirectly.",
        "`{cycle}` is the cycle. Types normalise their nesting from the bottom up, "
        "so a recursive type cannot be declared. If you need a tree, flatten it into "
        "a `list[T]` whose items carry a parent id field",
    ),
    # ── CONTRACT — 노드 계약 ───────────────────────────────────────────
    _rule(
        "LNT-CONTRACT-001",
        "args-dataclass-missing",
        (_N,),
        "No `Args` dataclass is declared. (file: {file})",
        "Every node script defines a dataclass named `Args` and takes the form "
        "`runNode(args: Args)`",
    ),
    _rule(
        "LNT-CONTRACT-002",
        "entrypoint-missing",
        (_N,),
        "The entry point `runNode` is missing or has the wrong shape. (file: {file})",
        "The entry point name is fixed as `runNode`. It takes exactly one argument "
        "and that argument's type must be `Args`",
    ),
    _rule(
        "LNT-CONTRACT-003",
        "return-missing",
        (_N,),
        "No dataclass leaves through `returnResult()` — either the call is missing, "
        "or the output type is not a dataclass (a primitive, or undetermined). "
        "(file: {file})",
        "Output leaves through `returnResult()`. The return type is a dataclass and "
        "its name is free — type identity is decided **by structure**, so a "
        "primitive cannot be sent out as is",
    ),
    _rule(
        "LNT-CONTRACT-004",
        "args-unknown-field",
        (_N,),
        "`Args` has a field other than `input` / `params` / `state`: {names}",
        "`Args` may hold only those three fields. Declare only the ones you use",
    ),
    _rule(
        "LNT-CONTRACT-005",
        "judge-expected-missing",
        (_N,),
        "This is a Judge node, but `Args.params` has no expected-value field. "
        "(file: {file})",
        "A Judge takes its expected value from the Spec. Hard-coding it in the "
        "script turns the Spec file into an empty shell — editing the plan would no "
        "longer change the decision. Declare the expected-value field on "
        "`Args.params`",
    ),
    _rule(
        "LNT-CONTRACT-006",
        "act-io-differ",
        (_N,),
        "This is an Act node, but its input type and output type differ. "
        "(file: {file})",
        "An Act passes data straight through. The `Args.input` type and the "
        "return type must be the same. If you need to transform, use a Extract",
    ),
    _rule(
        "LNT-CONTRACT-007",
        "judge-verdict-missing",
        (_N,),
        "This is a Judge node, but its output dataclass has no decision field "
        "`passed: bool`. (file: {file})",
        "A Judge is the node that **decides** — the engine needs `passed: bool` on "
        "the output dataclass to tell `pass` from `violation`. Without it nobody "
        "finds out until the run, and at that point you get an error instead of a "
        "report",
    ),
    # ── STATE — 상태·상태머신 ──────────────────────────────────────────
    _rule(
        "LNT-STATE-001",
        "reserved-prefix",
        (_N, _P),
        "A user state name uses the `__` prefix: {name}",
        "The `__` prefix is reserved for engine-provided fields (`__startedAt` and "
        "the like). Pick another name",
    ),
    _rule(
        "LNT-STATE-002",
        "mapping-missing",
        (_P,),
        "A state the node requires is not bound in `states`.",
        "Every field on the node's `Args.state` must be bound to a pipeline state "
        "name. Missing: {names}",
    ),
    _rule(
        "LNT-STATE-003",
        "mapped-state-unknown",
        (_P,),
        "The bound target is not in `states.values`: {name}",
        "The name you bound to is not in the pipeline's state set. Add it to "
        "`states.values`, or fix the name",
    ),
    _rule(
        "LNT-STATE-004",
        "when-undeclared",
        (_P,),
        "`when` references a state the script never declared: {name}",
        "`when` is written in the node's own vocabulary. That name must be declared "
        "on the script's `Args.state`",
    ),
    _rule(
        "LNT-STATE-005",
        "transition-state-unknown",
        (_P,),
        "`transitions.to` names a state that is not in `states.values`: {name}",
        "`transitions.to` must be a state listed in `states.values`",
    ),
    _rule(
        "LNT-STATE-006",
        "state-unreachable",
        (_P,),
        "No transition leads to the state `when` references.",
        "The node vocabulary `{name}` is bound to pipeline state `{mapped}`, and no "
        "`transitions` entry leads to that state, so the node never runs. Add the "
        "transition or drop the `when` — a transition is written in the pipeline "
        "vocabulary, on the `{mapped}` side",
    ),
    _rule(
        "LNT-STATE-007",
        "node-unreachable",
        (_P,),
        "Running the state machine shows node `{name}` is unreachable.",
        "Running the conditions together with the graph, nothing ever reaches this "
        "node. Check whether its `when` state is true only before this node's inputs "
        "have finished",
    ),
    # ── BAN — 금지 패턴 ────────────────────────────────────────────────
    _rule(
        "LNT-BAN-001",
        "time-dependency",
        (_N,),
        "A function whose result changes with time is used: {name} (file: {file})",
        "A script cannot read the clock. If you need the run time, use "
        "`Args.state.__startedAt` (epoch ms)",
    ),
    _rule(
        "LNT-BAN-002",
        "randomness",
        (_N,),
        "Randomness is used: {name} (file: {file})",
        "Randomness is banned in every node type. The same input has to produce the "
        "same result, or the report cannot be trusted",
    ),
    _rule(
        "LNT-BAN-003",
        "direct-subprocess",
        (_N,),
        "`subprocess` / `exec` and the like are called directly: {name} "
        "(file: {file})",
        "Running arbitrary commands is banned. If you need an external tool, declare "
        "its path and allowed functions under the Spec's `tool` and go through that",
    ),
    _rule(
        "LNT-BAN-004",
        "undeclared-state-access",
        (_N,),
        "A state that is not on `Args.state` is referenced: {name} (file: {file})",
        "Declare the state on `Args.state` before referencing it. What is not "
        "declared cannot be used",
    ),
    # ── DEP — 스크립트 의존성 (PEP 723) ────────────────────────────────
    _rule(
        "LNT-DEP-001",
        "dependency-missing",
        (_N,),
        "A package declared in the PEP 723 header is not present in this "
        "environment: {requirement} (file: {file})",
        "A node script is loaded into the **same process** as lintomata, so its "
        "`import` resolves in the environment lintomata itself is installed in. "
        "No isolated environment is created for you — install it there as well: "
        "{install}\n"
        "⚠ `--with` is **declarative**: only what you list survives. The command "
        "above already carries everything the registry declares, so use it "
        "**verbatim**. Listing a subset wipes out the rest",
    ),
    _rule(
        "LNT-DEP-002",
        "dependency-header-malformed",
        (_N,),
        "Cannot read the PEP 723 header: {reason} (file: {file})",
        "The header opens with `# /// script` and closes with `# ///`, and every "
        "line between them is TOML behind a `# `. `dependencies` is an array of "
        "PEP 508 strings:\n"
        '  # /// script\n'
        '  # requires-python = ">=3.11"\n'
        '  # dependencies = ["selectolax>=0.3"]\n'
        "  # ///\n"
        "Having no header at all is fine — a script that only uses the stdlib does "
        "not need one",
    ),
    _rule(
        "LNT-DEP-003",
        "dependency-version-unsatisfied",
        (_N,),
        "The installed version does not satisfy the declared requirement: "
        "{requirement} (installed: {installed}) (file: {file})",
        "Only one copy of a package is installed in the environment. Either bring "
        "the installed one up to the requirement ({install}), or bring the header's "
        "requirement in line with the version you actually use.\n"
        "⚠ `--with` is **declarative**: only what you list survives. The command "
        "above already carries everything the registry declares, so use it "
        "**verbatim**. Listing a subset wipes out the rest",
    ),
    # ── TOOL — 외부 도구 ───────────────────────────────────────────────
    _rule(
        "LNT-TOOL-001",
        "function-undeclared",
        (_R,),
        "A function that is not in the Spec's `tool` is called: {name}",
        "Every external tool call must have its function name declared under the "
        "Spec's `tool`",
    ),
    _rule(
        "LNT-TOOL-002",
        "executable-undeclared",
        (_R,),
        "The executable path passed as an argument is not declared under `tool`.",
        "The executable path handed to the function must match the `path` under "
        "`tool`. Given: {path}",
    ),
    # ── CONFIG — config 선언과 채움 ────────────────────────────────────
    _rule(
        "LNT-CONFIG-001",
        "required-missing",
        (_R,),
        "The Spec does not fill a config declared `required: true`.",
        "Fill the config the pipeline requires in the Spec's `plan` entry. "
        "Missing: {names}",
    ),
    _rule(
        "LNT-CONFIG-002",
        "value-type-mismatch",
        (_R,),
        "The value filled into config `{name}` has a different type than declared.",
        "Declared type: {declared} / given value: {given}",
    ),
    _rule(
        "LNT-CONFIG-003",
        "unknown-key",
        (_R,),
        "A config the pipeline never declared is filled: {name}",
        "Only a config the pipeline declares can be filled. Either this is a typo, "
        "or the declaration is missing on the pipeline side",
    ),
    # ── CMP — 비교 파이프라인 ──────────────────────────────────────────
    _rule(
        "LNT-CMP-001",
        "report-missing",
        (_R,),
        "The pipeline is `kind: compare`, but the Spec entry has no `report`.",
        "A compare pipeline builds its result as it runs, so it needs somewhere to "
        "put it. Point `report` at that place in the `plan` entry",
    ),
    _rule(
        "LNT-CMP-002",
        "target-type-differ",
        (_P, _R),
        "The per-target scripts declare different input/output/state types: {node}",
        "The recognition script may differ per target, but the "
        "**input/output/state types belong to the node and must be shared** or there "
        "is nothing to compare. `params` may differ",
    ),
    _rule(
        "LNT-CMP-003",
        "targets-too-few",
        (_P, _R),
        "`targets` holds fewer than two entries: {count}",
        "Comparing takes at least two targets. There is no upper bound",
    ),
    _rule(
        "LNT-CMP-004",
        "target-config-missing",
        (_R,),
        "A config the target requires is in neither `targets.<target>` nor the "
        "shared config.",
        "`${config.X}` is looked up in `targets.<the current target>` first, and in "
        "the shared config only if it is not there. It is in neither: {name}",
    ),
    # ── TEST — 노드 단위테스트 ─────────────────────────────────────────
    _rule(
        "LNT-TEST-001",
        "fixture-type-mismatch",
        (_T,),
        "The `args` fixture does not match the script's `Args` declaration.",
        "**The test definition is what is wrong here**, not the script. Bring the "
        "fixture in line with the `Args` declaration",
    ),
    _rule(
        "LNT-TEST-002",
        "script-raised",
        (_T,),
        "`runNode` raised.",
        "The script ended in an exception: {exc}",
    ),
    _rule(
        "LNT-TEST-003",
        "output-type-mismatch",
        (_T,),
        "The returned value does not match the declared output type.",
        "The declared output type and what actually came back differ. "
        "Declared: {declared} / actual: {actual}",
    ),
    _rule(
        "LNT-TEST-004",
        "expect-mismatch",
        (_T,),
        "`expect` and the actual value differ.",
        "Expected: {expect} / actual: {actual}",
    ),
    _rule(
        "LNT-TEST-005",
        "act-not-transparent",
        (_T,),
        "This is an Act node, but the returned value differs from the input.",
        "An Act must pass data straight through. Cause the side effect and leave "
        "the value alone",
    ),
    _rule(
        "LNT-TEST-006",
        "judge-no-contrast-pair",
        (_T,),
        "The Judge test has no pass/violation contrast pair.",
        "Put in one passing case and one violating case that share the same `input` "
        "and differ only in `params` — that pair is what proves the expected value "
        "is actually used",
    ),
    _rule(
        "LNT-TEST-007",
        "judge-expected-ignored",
        (_T,),
        "Both halves of the contrast pair decide the same way.",
        "The expected value changed and the decision did not — the script is "
        "ignoring it and deciding on something hard-coded",
    ),
    _rule(
        "LNT-TEST-008",
        "test-node-mismatch",
        (_R,),
        "The unit test's `node` points at **a different node than the one "
        "requested**.",
        "When called as `lintomata node test <id>`, **the node with that id is "
        "authoritative**. If the test definition's `node` points somewhere else, a "
        "node you never asked for gets run and the report is **false**. "
        "Requested: {requested} / what the test points at: {declared}",
    ),
    # ── REG — 등록소 ───────────────────────────────────────────────────
    _rule(
        "LNT-REG-001",
        "hash-mismatch",
        (_R,),
        "The registry file's hash differs from the one taken at registration: {id}",
        "The registered file was changed without going through the checks. Remove it "
        "and register it again",
    ),
    _rule(
        "LNT-REG-002",
        "ref-not-found",
        (_P, _R),
        "The reference is not in the registry: {id}",
        "No such id — it was removed, or it is a typo. Check with `lintomata list`: "
        "{id}",
    ),
    _rule(
        "LNT-REG-003",
        "ref-kind-mismatch",
        (_N, _P),
        "The reference prefix is not the kind this position requires.",
        "This position takes {expected}. Given: {given} "
        "(prefixes: `sc_`=script `lb_`=library `nd_`=node `pl_`=pipeline `sp_`=Spec)",
    ),
    _rule(
        "LNT-REG-004",
        "ref-broken",
        (_L,),
        "Broken reference — what it points at was deleted: {id}",
        "The target of the reference was deleted, so this configuration no longer "
        "holds. The missing reference: {id}. Register the target again and point "
        "this entry at the new id",
    ),
    _rule(
        "LNT-REG-005",
        "validation-broken",
        (_L,),
        "Broken validation — what it points at was modified and this entry no longer "
        "passes: {id}",
        "The target of the reference was modified, which invalidated this "
        "configuration's validation. The rule that failed: {rule}. Fix this entry "
        "and `update` it again",
    ),
    # ── LIB — 라이브러리 (`schema.md` 6.5절) ───────────────────────────
    _rule(
        "LNT-LIB-001",
        "library-slot-unwired",
        (_N,),
        "A library slot the script requires is not wired on the node: {names}",
        "`from lintomata_lib import <name>` in the script is a "
        "**capability declaration** (\"I need this slot\"); what goes into the slot "
        "is decided by the **node**. Put "
        "`\"libraries\": { \"<name>\": \"${ref.lb_...}\" }` in the node JSON "
        "— an absolute path (`${env.X}` included) works too. The unwired slots: "
        "{names}",
    ),
    _rule(
        "LNT-LIB-002",
        "library-slot-unused",
        (_N,),
        "The script does not use a library slot the node wired: {names}",
        "A node's `libraries` answers only the slots the script asked for with "
        "`from lintomata_lib import <name>`. An unused wiring only widens the "
        "reference graph, so **editing that library revalidates nodes that have "
        "nothing to do with it**. Drop the wiring, or actually use it in the "
        "script. The leftover wiring: {names}",
    ),
    _rule(
        "LNT-LIB-003",
        "library-nested-import",
        (_LB,),
        "A library imports another library: {name}",
        "Libraries are **one layer only** — allow libraries to import each other and "
        "from that point on you are building a package manager. Keep the function in "
        "this file, or let the script that uses them wire both slots itself",
    ),
    _rule(
        "LNT-LIB-004",
        "library-dataclass-forbidden",
        (_LB,),
        "A library declares a `dataclass`: {name}",
        "A v1 library provides **functions only**. If a contract type between nodes "
        "is born outside a script, contract extract — which parses a single file "
        "— leaves a hole in the type registry. **Move this dataclass into the "
        "script** that uses it",
    ),
    _rule(
        "LNT-LIB-005",
        "library-import-form",
        (_N,),
        "`lintomata_lib` is imported in a form that is not allowed: {form}",
        "The only allowed form is "
        "**`from lintomata_lib import <name>` at module top level**. "
        "`import lintomata_lib`, `from lintomata_lib.<x> import y`, `import *`, and "
        "an import inside a function all make the slots "
        "**impossible to extract statically**, which makes the wiring check "
        "meaningless",
    ),
)


RULES: dict[str, Rule] = {rule.id: rule for rule in _TABLE}
"""규칙 id → 규칙. `rules.md` 2절의 69개."""

if len(RULES) != len(_TABLE):  # pragma: no cover - 테이블 오타 방지용 자기 검증
    raise LintomataError(_msg("The rule table has duplicate ids"))


def get_rule(rule_id: str) -> Rule:
    """규칙 하나를 꺼낸다. 없으면 `LintomataError` — 도구 자신의 버그이므로 오류다."""
    try:
        return RULES[rule_id]
    except KeyError:
        raise LintomataError(
            _msg(
                "Unknown rule id: {id}. Only the ids listed in the table in "
                "`rules.md` §2 can be used.",
                id=repr(rule_id),
            )
        ) from None


def rules_for(when: RuleWhen) -> list[Rule]:
    """그 시점에 도는 `active` 규칙들을 준다."""
    return [
        rule
        for rule in _TABLE
        if rule.status == "active" and when in rule.when
    ]


def _fill(template: str, fields: dict[str, object]) -> str:
    """`{식별자}` 자리표시자를 `fields` 로 치환한다. 누락 검증은 호출자가 이미 했다.

    **치환기는 `locale.fill` 하나다** — 오류 문구도 같은 것을 쓴다. 두 벌로 두면 갈린다.
    """
    return fill(template, fields)


def _render(rule_id: str, fields: dict[str, object]) -> str:
    """`message` 를 채우고 뒤에 채워진 `guide` 를 이어붙인다.

    슬롯 값이 없으면 **조용히 넘어가지 않고 오류**다 — 리포트에 `{cycle}` 이
    그대로 새어나가면 그건 검사기의 버그이지 위반이 아니다.
    필요한 슬롯 전부를 `Rule.slots` 에서 알려준다.

    **누락 판정은 원문(`Rule.slots`) 기준이고, 치환은 번역된 문구에 한다.**
    로케일이 판정을 흔들면 안 되기 때문이다 — 종료 코드도 규칙 id 도 언어와 무관하다
    (`schema.md` 2절).
    """
    rule = get_rule(rule_id)
    missing = [name for name in rule.slots if name not in fields]
    if missing:
        raise LintomataError(
            _msg(
                "No value was given for placeholders of rule {id}: {missing}. "
                "This rule requires the placeholders {slots} (`rules.Rule.slots`). "
                "Pass the values in the `fields` dict.",
                id=rule_id,
                missing=", ".join(missing),
                slots=", ".join(rule.slots),
            )
        )
    message = _fill(translate(rule.message), fields)
    guide = _fill(translate(rule.guide), fields)
    return f"{message}\n{guide}"


def render(rule_id: str, **fields: object) -> str:
    """규칙의 `message` 를 `fields` 로 채우고 **뒤에 `guide` 를 이어붙여** 준다.

    이것이 `Finding.message` 에 들어가는 최종 문자열이다 (`schema.md` 11절).

    **`guide` 의 슬롯도 같은 `fields` 로 채운다.** `rules.md` 2절의 guide 문구
    자체가 `{cycle}` `{names}` `{path}` 같은 슬롯을 직접 갖고 있고
    (`LNT-GRAPH-001`·`LNT-TOOL-002`·`LNT-CONFIG-001`·`LNT-TEST-002/003/004` 등은
    슬롯이 **guide 에만** 있다), 안 채우면 리포트에 `{cycle}` 이 그대로 샌다.
    `message` 와 `guide` 는 하나의 슬롯 공간을 공유한다 — 그것이 `Rule.slots` 다.

    `{in}` 처럼 파이썬 예약어인 슬롯은 `render(rule_id, **{"in": ...})` 로 넘긴다.
    `Finding` 을 만들 때는 `finding(..., fields={...})` 를 쓴다.
    """
    return _render(rule_id, dict(fields))


def finding(
    rule_id: str,
    *,
    status: Status = "error",
    path: str = "",
    node: str = "",
    cause: NotRunCause | None = None,
    fields: dict[str, object] | None = None,
) -> Finding:
    """규칙 id 로 `Finding` 하나를 만든다. 메시지는 규칙 문구에서 채워진다.

    검사기들이 가장 많이 쓰는 진입점이다.

    **슬롯 값은 `fields` 딕셔너리로만 넘긴다.** `**fields` 였을 때는 keyword-only
    파라미터 `path`/`node` 가 **동명 슬롯을 잡아먹어** `LNT-PATH-001`(`{path}`)·
    `LNT-TOOL-002`(`{path}`)·`LNT-CMP-002`(`{node}`) 를 렌더할 방법이 아예 없었다.
    딕셔너리로 받으면 이름 충돌이 구조적으로 불가능하다.
    `{in}` 같은 파이썬 예약어 슬롯도 이 형태로만 넘길 수 있다.

    여기서 `path`/`node` 는 **`Finding` 이 가리키는 위치**이고,
    `fields["path"]`/`fields["node"]` 는 **규칙 문구의 슬롯**이다. 서로 다른 것이다.
    """
    return Finding(
        status=status,
        path=path,
        node=node,
        rule_id=rule_id,
        message=_render(rule_id, dict(fields or {})),
        cause=cause,
    )
