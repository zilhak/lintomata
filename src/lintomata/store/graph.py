"""등록소의 참조 그래프 — 역방향 추적과 깨짐 판정 (`schema.md` 2절).

**깨짐은 두 종류다:**

| 깨짐 | 원인 | 참조는 | 규칙 |
|---|---|---|---|
| **참조 깨짐** | 대상이 **삭제**됨 | 끊겼다 — 눈에 보인다 | `LNT-REG-004` |
| **검증 깨짐** | 대상이 **수정**됨 | 멀쩡하다 — **조용히 무효화된 것을 드러내야 한다** | `LNT-REG-005` |

**둘 다 실패가 아니라 상태 표시다.** 삭제도 수정도 막지 않고 `list` 에서 드러낸다.

`-005` 를 잡으려면 수정 시 상위를 **전이적으로** 재검증해야 한다:
스크립트 수정 → 노드 → 파이프라인 → Spec 순으로 올라간다.
"""

from __future__ import annotations

from collections import deque

from lintomata import rules
from lintomata.errors import Finding
from lintomata.store.entries import RegistryEntry, Store

__all__ = ["RefGraph"]


class RefGraph:
    """등록소 항목들 사이의 참조 그래프. 정방향·역방향 인접을 함께 갖는다."""

    def __init__(self, entries: dict[str, RegistryEntry]) -> None:
        self.entries: dict[str, RegistryEntry] = entries
        self._reverse: dict[str, list[str]] = {}
        for entry_id, entry in entries.items():
            for ref_id in entry.refs:
                bucket = self._reverse.setdefault(ref_id, [])
                if entry_id not in bucket:
                    bucket.append(entry_id)

    @classmethod
    def build(cls, store: Store) -> RefGraph:
        """등록소 인덱스에서 그래프를 만든다."""
        return cls(store.load_index().entries)

    def dependencies(self, entry_id: str) -> list[str]:
        """이 항목이 참조하는 것들 (아래쪽).

        **없어진 id 도 그대로 나온다** — 그것을 걸러내면 참조 깨짐이 안 보인다.
        """
        entry = self.entries.get(entry_id)
        return list(entry.refs) if entry is not None else []

    def dependents(self, entry_id: str) -> list[str]:
        """이 항목을 참조하는 것들 (위쪽, 1단계)."""
        return list(self._reverse.get(entry_id, []))

    def transitive_dependents(self, entry_id: str) -> list[str]:
        """이 항목을 참조하는 것들 전부 (위쪽, 전이적).

        수정 시 재검증 대상이 이것이다. 스크립트 → 노드 → 파이프라인 → Spec.
        아래쪽에서 가까운 순(BFS)으로 나오므로 그 순서대로 재검증하면 된다.
        """
        seen: set[str] = {entry_id}
        order: list[str] = []
        queue: deque[str] = deque(self.dependents(entry_id))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            order.append(current)
            queue.extend(self.dependents(current))
        return order

    def broken_refs(self) -> list[Finding]:
        """**참조 깨짐** 판정 — 삭제된 대상을 가리키는 항목들 (`LNT-REG-004`).

        판정한 결과를 항목의 `broken` 에 얹는다 — `list` 가 그것을 보여준다.
        **삭제를 막지 않으므로** 이 상태는 정상적으로 보고되는 결과다.
        """
        findings: list[Finding] = []
        for entry_id, entry in self.entries.items():
            missing = [ref for ref in entry.refs if ref not in self.entries]
            if not missing:
                continue
            entry.broken = "ref"
            entry.broken_detail = missing[0]
            for ref_id in missing:
                findings.append(
                    rules.finding(
                        "LNT-REG-004",
                        path=entry_id,
                        fields={"id": ref_id},
                    )
                )
        return findings

    def propagate_broken(self) -> list[Finding]:
        """**깨짐은 전이적이다** — 참조 대상이 깨졌으면 상위도 깨졌다 (R5-4).

        Spec 의 등록 검사는 형태만 보므로, 그것이 참조하는 파이프라인이 `✕ 검증 깨짐`
        이어도 Spec 재검증은 그냥 통과한다. **그러나 그 Spec 은 돌릴 수 없다** —
        `spec list` 만 보는 사람에게 `○` 는 거짓말이다. `schema.md` 2절의
        *"수정은 참조가 멀쩡한 채로 **검증만 조용히 무효화**한다"* 가 정확히 이 자리다.

        참조 깨짐(삭제)도 같은 논리다 — 사라진 것을 참조하는 파이프라인을 참조하는
        Spec 역시 돌릴 수 없다. 다만 **그 Spec 자신의 참조는 멀쩡하므로** 상위에
        얹는 표시는 언제나 `"validation"`(검증 깨짐)이다. `"ref"` 는 자기가 직접
        없는 id 를 가리킬 때만 붙는다.

        **판정만 하고 저장하지 않는다.** 얹은 표시는 아래쪽 상태에서 매번 다시
        계산되는 파생값이라, 저장하면 아래가 고쳐진 뒤에도 남아 거짓이 된다.
        """
        findings: list[Finding] = []
        # 아래에서 위로 번지므로 더 번질 것이 없을 때까지 훑는다.
        # 한 바퀴에 최소 하나는 새로 표시되므로 항목 수를 넘길 수 없다.
        for _ in range(len(self.entries) + 1):
            changed = False
            for entry_id, entry in self.entries.items():
                if entry.broken:
                    continue
                source = self._broken_dependency(entry)
                if source is None:
                    continue
                dep_id, detail = source
                entry.broken = "validation"
                entry.broken_detail = detail
                findings.append(
                    rules.finding(
                        "LNT-REG-005",
                        path=entry_id,
                        fields={"id": entry_id, "rule": detail},
                    )
                )
                changed = True
            if not changed:
                break
        return findings

    def _broken_dependency(self, entry: RegistryEntry) -> tuple[str, str] | None:
        """이 항목이 참조하는 것 중 깨진 첫 번째 — `(id, 상위에 적을 이유)`."""
        for ref_id in entry.refs:
            dep = self.entries.get(ref_id)
            if dep is None or not dep.broken:
                continue
            kind = "참조 깨짐" if dep.broken == "ref" else "검증 깨짐"
            detail = f"{ref_id} {kind}"
            return ref_id, f"{detail} ({dep.broken_detail})" if dep.broken_detail else detail
        return None

    def revalidate(self, store: Store, entry_id: str) -> list[Finding]:
        """`entry_id` 수정 후 상위를 전이적으로 재검증한다 (`LNT-REG-005`).

        재검증 자체는 `checks.check_registration` 을 다시 태우는 것이고,
        실패한 규칙 id 를 그 항목의 `broken_detail` 에 적어 `list` 에서 드러낸다.
        **재검증 실패가 수정을 막지는 않는다.**
        """
        # 지역 import — `checks` 가 `store.entries` 를 쓰므로 top-level 이면 순환이다.
        from lintomata.checks import check_registration

        findings: list[Finding] = []
        touched: list[str] = []
        for dep_id in self.transitive_dependents(entry_id):
            entry = self.entries.get(dep_id)
            if entry is None:
                continue
            results = check_registration(entry.kind, store.path_of(dep_id), store)
            touched.append(dep_id)
            if results:
                failed = results[0].rule_id
                entry.broken = "validation"
                entry.broken_detail = failed
                findings.append(
                    # `path` 와 슬롯 `{id}` 는 별개 채널이다 (계약 개정 R1-2) —
                    # 값이 같아도 둘 다 넘긴다.
                    rules.finding(
                        "LNT-REG-005",
                        path=dep_id,
                        fields={"id": dep_id, "rule": failed},
                    )
                )
            elif entry.broken == "validation":
                # 다시 통과했으면 표시를 걷는다. 참조 깨짐은 여기서 손대지 않는다.
                entry.broken = ""
                entry.broken_detail = ""
        self._persist(store, touched)
        # 전이는 **저장한 뒤에** 얹는다 — 파생값이라 인덱스에 굳으면 아래가 고쳐진
        # 뒤에도 남는다. 여기서 내는 것은 이번 수정의 보고용이다 (R5-4).
        findings.extend(self.propagate_broken())
        return findings

    def _persist(self, store: Store, entry_ids: list[str]) -> None:
        """재검증이 얹은 깨짐 표시를 인덱스에 남긴다.

        검증 깨짐은 **수정 시점에만 계산되므로** 저장해두지 않으면 다음 `list` 에서
        사라진다. (참조 깨짐은 인덱스만 보고 언제든 다시 계산된다.)
        """
        if not entry_ids:
            return
        index = store.load_index()
        for entry_id in entry_ids:
            entry = self.entries.get(entry_id)
            stored = index.entries.get(entry_id)
            if entry is None or stored is None:
                continue
            stored.broken = entry.broken
            stored.broken_detail = entry.broken_detail
        store.save_index(index)
