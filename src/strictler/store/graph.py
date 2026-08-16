"""등록소의 참조 그래프 — 역방향 추적과 깨짐 판정 (`schema.md` 2절).

**깨짐은 두 종류다:**

| 깨짐 | 원인 | 참조는 | 규칙 |
|---|---|---|---|
| **참조 깨짐** | 대상이 **삭제**됨 | 끊겼다 — 눈에 보인다 | `STR-REG-004` |
| **검증 깨짐** | 대상이 **수정**됨 | 멀쩡하다 — **조용히 무효화된 것을 드러내야 한다** | `STR-REG-005` |

**둘 다 실패가 아니라 상태 표시다.** 삭제도 수정도 막지 않고 `list` 에서 드러낸다.

`-005` 를 잡으려면 수정 시 상위를 **전이적으로** 재검증해야 한다:
스크립트 수정 → 노드 → 파이프라인 → Spec 순으로 올라간다.

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from strictler.errors import Finding
from strictler.store.entries import RegistryEntry, Store

__all__ = ["RefGraph"]


class RefGraph:
    """등록소 항목들 사이의 참조 그래프. 정방향·역방향 인접을 함께 갖는다."""

    def __init__(self, entries: dict[str, RegistryEntry]) -> None:
        raise NotImplementedError("Step 1에서 구현")

    @classmethod
    def build(cls, store: Store) -> RefGraph:
        """등록소 인덱스에서 그래프를 만든다."""
        raise NotImplementedError("Step 1에서 구현")

    def dependencies(self, entry_id: str) -> list[str]:
        """이 항목이 참조하는 것들 (아래쪽)."""
        raise NotImplementedError("Step 1에서 구현")

    def dependents(self, entry_id: str) -> list[str]:
        """이 항목을 참조하는 것들 (위쪽, 1단계)."""
        raise NotImplementedError("Step 1에서 구현")

    def transitive_dependents(self, entry_id: str) -> list[str]:
        """이 항목을 참조하는 것들 전부 (위쪽, 전이적).

        수정 시 재검증 대상이 이것이다. 스크립트 → 노드 → 파이프라인 → Spec.
        """
        raise NotImplementedError("Step 1에서 구현")

    def broken_refs(self) -> list[Finding]:
        """**참조 깨짐** 판정 — 삭제된 대상을 가리키는 항목들 (`STR-REG-004`)."""
        raise NotImplementedError("Step 1에서 구현")

    def revalidate(self, store: Store, entry_id: str) -> list[Finding]:
        """`entry_id` 수정 후 상위를 전이적으로 재검증한다 (`STR-REG-005`).

        재검증 자체는 `checks.check_registration` 을 다시 태우는 것이고,
        실패한 규칙 id 를 그 항목의 `broken_detail` 에 적어 `list` 에서 드러낸다.
        **재검증 실패가 수정을 막지는 않는다.**
        """
        raise NotImplementedError("Step 1에서 구현")
