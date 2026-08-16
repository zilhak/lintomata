"""스크립트 계약의 재사용 — 같은 스크립트를 두 번 파싱하지 않는다.

두 층이다. 아래층이 없어도 위층은 그대로 돈다.

| 층 | 수명 | 무엇에 의존 | 어디에 |
|---|---|---|---|
| **① 실행 내 메모** | 한 번의 실행 | 경로 + 내용 해시 | 메모리 |
| **② 등록소 캐시** | 해시가 그대로인 동안 | **그 파일 바이트만** | `$LINTOMATA_HOME/cache/<id>.json` |

### ① 왜 필요한가

한 번의 `check` 안에서 같은 스크립트가 **노드당 세 번** 파싱된다:

| 어디 | 왜 |
|---|---|
| `checks.pipeline.recheck_resolved` | config 가 풀린 뒤의 재검 (R3-4) |
| 그 안의 `checks.script.check_script` | 자기가 쓸 계약을 스스로 뽑는다 |
| `engine.runtime._load_nodes` / `engine.compare._resolve_one` | 구동 재료 |

**같은 파일에서는 같은 계약이 나온다.** 세 자리가 서로 다른 것을 보는 것이 아니다.

### ② 등록은 검증 결과를 재사용하는 기제다

`schema.md` 2절: *"등록된 것은 해시만 그대로면 이미 검증을 통과한 파일이므로 다시
검사할 필요가 없다."* 여기서 재사용하는 것은 **`ScriptContract` 뿐**이다.

**무엇을 캐시하지 않는지가 더 중요하다:**

| 안 하는 것 | 왜 |
|---|---|
| `check_script` 의 `Finding` 들 | `LNT-DEP-*` 는 **지금 환경에 그 패키지가 깔려 있나**를 본다. 파일 바이트만으로 정해지지 않는다 |
| 배선 타입 대조·registry 병합·도달가능성 | 파이프라인 + 참조하는 전 노드/스크립트의 **조합**에 의존한다 |
| 경로 전개·`check_config_values`·`check_tool_calls` | `${env.X}` 와 Spec `config` 는 **실행할 때마다 달라진다** (R5-1 이 정확히 이 계열이었다) |
| 미등록(경로 참조) 파일 | 저장된 해시가 없다 = 재사용할 검증 결과가 없다 |
| **배선된 라이브러리의 검사 결과** | 라이브러리는 **다른 파일**이다. 키(`this` 파일 해시)에 안 들어가므로 캐시했다면 라이브러리를 고쳐도 옛 결과가 산다 |
| 노드 JSON 형식 검사 | 파일 바이트만으로 정해지긴 하지만 **재사용해도 남는 게 없다** — pydantic 재검증이 곧 그 검사라 캐시를 읽어 되살리는 값이 같은 일을 한다 |

**틀린 캐시는 없는 캐시보다 훨씬 나쁘다** — lint 도구가 검사하지 않은 것을
검사했다고 보고하게 된다. 애매하면 캐시하지 않는다.

### 무효화는 저절로 된다

키가 **id + 파일 해시**라 내용이 바뀌면 그냥 빗나간다. 등록소 파일을 정적 검사
루트 밖에서 고친 경우도 `entry.hash` 와 안 맞아 캐시가 없는 것으로 친다 —
그 사실 자체는 `LNT-REG-001` 이 따로 잡는다. **캐시가 그걸 가리지 않는다.**

포맷에는 버전을 박는다. lintomata 를 올려 추출 방식이 바뀌면 옛 캐시는 무효다.

### ★ 라이브러리가 붙어도 키는 그대로다 — **그래도 되는 이유가 있다**

계약에 `library_slots` 가 생겼지만 그것은 **이 스크립트 자신의 바이트에서** 뽑은
이름 목록이다(`from lintomata_lib import X`). **라이브러리의 *내용*은 계약에 한 톨도
들어오지 않는다** — 배선 값은 노드 JSON 에 있고, 그 검사는 캐시하지 않는다.

→ 라이브러리를 고쳐도 스크립트 계약은 정말로 그대로다. 반대로 **라이브러리를 고쳤을 때
무효화돼야 하는 것**(그것을 쓰는 노드·파이프라인·Spec 의 *검증*)은 캐시가 아니라
등록소의 전이적 재검증(`store.graph.RefGraph.revalidate`)이 맡는다. 자리가 다르다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from lintomata.checks import script as script_checks
from lintomata.checks.script import ScriptContract
from lintomata.errors import Finding, LintomataError
from lintomata.store.entries import Store
from lintomata.typesys.primitives import TypeRef
from lintomata.typesys.registry import DataclassSpec, FieldSpec

__all__ = ["CACHE_VERSION", "ScriptCache", "ContractPayload"]


CACHE_VERSION = 2
"""캐시 포맷 버전. **추출 방식이나 `ScriptContract` 의 모양이 바뀌면 올린다** —
버전이 다르면 캐시는 없는 것으로 친다. 옛 결과를 새 검사에 쓰면 조용히 틀린다.

`2` — `library_slots` 가 계약에 붙었다 (`schema.md` 6.5절). 버전을 안 올렸다면 옛
캐시가 **슬롯이 하나도 없는 계약**으로 되살아나 `LNT-LIB-001` 이 영영 안 걸린다."""


# ── 직렬화 ───────────────────────────────────────────────────────────────────


class TypePayload(BaseModel):
    """`TypeRef` 하나. **구조 그대로** 담는다 — 문자열로 접었다 펴지 않는다.

    `_type_of` 는 해석이 안 되는 어노테이션을 *원문 그대로의 미지 타입*으로 남기므로
    (`Callable[[int], str]` 같은 것) 다시 파싱하면 되돌아온다는 보장이 없다.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    args: list["TypePayload"] = []


class FieldPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: TypePayload


class DataclassPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    origin: str
    fields: list[FieldPayload]


class ContractPayload(BaseModel):
    """`ScriptContract` 한 벌의 직렬화 형태.

    **공개 필드와 `_` 내부 기록을 전부 담는다.** 검사기들이 `_args_fields`·
    `_entrypoint_ok` 같은 것을 그대로 읽으므로, 하나라도 빠지면 캐시를 탄
    실행만 판정이 달라진다. `tests/test_contracts_cache.py` 가 **속성 목록이
    빠짐없이 덮였는지**를 고정한다.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    dataclasses: list[DataclassPayload]
    input_type: str
    params_type: str
    state_type: str
    state_names: list[str]
    output_type: str
    tool_calls: list[tuple[str, str]]
    library_slots: list[str]
    has_args: bool
    args_fields: list[str]
    has_entrypoint: bool
    entrypoint_ok: bool
    param_name: str
    returns_result: bool
    type_uses: list[TypePayload]

    @classmethod
    def of(cls, contract: ScriptContract) -> ContractPayload:
        return cls(
            path=contract.path,
            dataclasses=[
                DataclassPayload(
                    name=spec.name,
                    origin=spec.origin,
                    fields=[
                        FieldPayload(name=field.name, type=_type_payload(field.type))
                        for field in spec.fields
                    ],
                )
                for spec in contract.dataclasses.values()
            ],
            input_type=contract.input_type,
            params_type=contract.params_type,
            state_type=contract.state_type,
            state_names=list(contract.state_names),
            output_type=contract.output_type,
            tool_calls=[(name, arg) for name, arg in contract.tool_calls],
            library_slots=list(contract.library_slots),
            has_args=contract._has_args,
            args_fields=list(contract._args_fields),
            has_entrypoint=contract._has_entrypoint,
            entrypoint_ok=contract._entrypoint_ok,
            param_name=contract._param_name,
            returns_result=contract._returns_result,
            type_uses=[_type_payload(used) for used in contract._type_uses],
        )

    def to_contract(self) -> ScriptContract:
        contract = ScriptContract(self.path)
        contract.dataclasses = {
            spec.name: DataclassSpec(
                spec.name,
                tuple(
                    FieldSpec(field.name, _type_ref(field.type)) for field in spec.fields
                ),
                origin=spec.origin,
            )
            for spec in self.dataclasses
        }
        contract.input_type = self.input_type
        contract.params_type = self.params_type
        contract.state_type = self.state_type
        contract.state_names = tuple(self.state_names)
        contract.output_type = self.output_type
        contract.tool_calls = [(name, arg) for name, arg in self.tool_calls]
        contract.library_slots = tuple(self.library_slots)
        contract._has_args = self.has_args
        contract._args_fields = tuple(self.args_fields)
        contract._has_entrypoint = self.has_entrypoint
        contract._entrypoint_ok = self.entrypoint_ok
        contract._param_name = self.param_name
        contract._returns_result = self.returns_result
        contract._type_uses = tuple(_type_ref(used) for used in self.type_uses)
        return contract


class _CacheFile(BaseModel):
    """디스크에 놓이는 것 전부. **키를 함께 적어 스스로 검증한다.**"""

    model_config = ConfigDict(extra="forbid")

    version: int
    hash: str
    """캐시를 만들 때 본 파일 내용의 해시. 등록소 인덱스의 `hash` 와 같은 값이다."""
    contract: ContractPayload


TypePayload.model_rebuild()


def _type_payload(ref: TypeRef) -> TypePayload:
    return TypePayload(name=ref.name, args=[_type_payload(arg) for arg in ref.args])


def _type_ref(payload: TypePayload) -> TypeRef:
    return TypeRef(payload.name, tuple(_type_ref(arg) for arg in payload.args))


# ── 캐시 ─────────────────────────────────────────────────────────────────────


class ScriptCache:
    """계약을 한 번만 뽑는다. `store` 를 주면 등록소 캐시까지 쓴다.

    `engine.runtime` 과 `engine.compare` 가 **둘 다 같은 것을 쓴다** — 한쪽만
    쓰면 두 파이프라인 종류의 동작이 갈린다 (R4-1 이 실제로 겪은 일이다).
    """

    def __init__(self, store: Store | None = None) -> None:
        self._store = store
        self._memo: dict[tuple[str, str], tuple[ScriptContract, list[Finding]]] = {}
        self._index_cache: dict[str, str] | None = None
        """등록소 인덱스의 `id → hash`. **실행 경로는 등록을 하지 않으므로**
        한 번의 실행 동안 바뀌지 않는다."""

    def contract(self, source: str, path: str) -> tuple[ScriptContract, list[Finding]]:
        """`extract_contract(source, path)` 과 **같은 것**을 돌려준다.

        **파싱 실패는 캐시하지 않는다.** `LintomataError` 는 그대로 올라간다 —
        그건 위반이 아니라 검사기가 못 돈 것이고, 그 경로는 어차피 진행하지 않는다.
        """
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        key = (path, digest)
        hit = self._memo.get(key)
        if hit is None:
            stored = self._load(path, digest)
            if stored is not None:
                hit = (stored, [])
            else:
                # 모듈 속성으로 부른다 — `from ... import` 로 묶어두면 이 캐시를 거치는
                # 경로만 대역이 안 걸려 테스트가 두 가지 `extract_contract` 를 보게 된다.
                hit = script_checks.extract_contract(source, path)
                self._save(path, digest, hit)
            self._memo[key] = hit
        contract, findings = hit
        # 부르는 쪽이 이 목록에 `extend` 한다 — 원본을 주면 캐시가 오염된다.
        return contract, list(findings)

    # ── 등록소 캐시 ─────────────────────────────────────────────────────────

    def _entry_hash(self, path: str) -> tuple[str, str]:
        """이 경로에 대응하는 `(엔트리 id, 등록 당시 해시)`. 등록소 밖이면 `("", "")`."""
        if self._store is None:
            return "", ""
        entry_id = self._store.entry_id_at(Path(path))
        if not entry_id.startswith("sc_"):
            return "", ""
        if self._index_cache is None:
            try:
                index = self._store.load_index()
            except LintomataError:
                # 인덱스가 손상됐다는 것은 다른 자리가 제대로 보고한다.
                # 캐시가 그것 때문에 실행을 막아서는 안 된다.
                self._index_cache = {}
                return "", ""
            self._index_cache = {
                key: value.hash for key, value in index.entries.items()
            }
        return entry_id, self._index_cache.get(entry_id, "")

    def _load(self, path: str, digest: str) -> ScriptContract | None:
        """캐시된 계약. 조금이라도 어긋나면 **없는 것으로 친다.**"""
        entry_id, registered = self._entry_hash(path)
        if not entry_id or registered != digest:
            # 등록 당시와 내용이 다르다 = 검사를 통과한 그 파일이 아니다.
            # 그 사실은 `LNT-REG-001` 이 따로 잡는다 — 여기서는 그냥 다시 뽑는다.
            return None
        cache_path = self._store.cache_path(entry_id)  # type: ignore[union-attr]
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = _CacheFile.model_validate(raw)
        except (OSError, ValueError, ValidationError):
            # 깨진 캐시는 없는 캐시다. 여기서 터지면 파생물이 본 검사를 막는 꼴이 된다.
            return None
        if cached.version != CACHE_VERSION or cached.hash != digest:
            return None
        if cached.contract.path != path:
            # 등록소를 통째로 옮기면 계약 안의 `origin` 이 옛 경로를 가리킨다.
            return None
        return cached.contract.to_contract()

    def _save(
        self, path: str, digest: str, extracted: tuple[ScriptContract, list[Finding]]
    ) -> None:
        """다음 실행이 쓸 수 있게 남긴다. **못 써도 그냥 넘어간다** — 캐시다."""
        contract, findings = extracted
        if findings:
            # 지금은 언제나 비어 있다(`extract_contract` 계약). 생기는 날이 오면
            # 캐시가 그걸 삼키지 않도록 여기서 멈춘다.
            return
        entry_id, registered = self._entry_hash(path)
        if not entry_id or registered != digest:
            return
        cache_path = self._store.cache_path(entry_id)  # type: ignore[union-attr]
        payload = _CacheFile(
            version=CACHE_VERSION, hash=digest, contract=ContractPayload.of(contract)
        )
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(payload.model_dump(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            return
