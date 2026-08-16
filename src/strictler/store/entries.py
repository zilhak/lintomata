"""등록소 인덱스와 CRUD (`schema.md` 2절).

**등록 시 정적 검사를 통과해야 저장된다.** 잘못된 것이 등록소에 들어가지 않는다.
**실행 시 해시를 대조한다** — 정적 검사 루트를 피해 등록소 파일을 직접 고치는 것을 막는다.

**수정은 id 를 유지한다.** 참조가 안 깨진다. 대신 상위를 전이적으로 재검증한다 —
수정은 참조가 멀쩡한 채로 **검증만 조용히 무효화**하기 때문이다.

**삭제도 수정도 막지 않는다.** 막으면 교착이 생긴다(하위를 고치려면 상위를 먼저
고쳐야 하는데 상위는 하위 때문에 못 고친다). 대신 목록 조회에서 깨짐을 표시한다.

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from strictler.model import EntryKind

__all__ = [
    "SUBDIRS",
    "RegistryEntry",
    "RegistryIndex",
    "default_home",
    "hash_file",
    "new_id",
    "Store",
]


SUBDIRS: dict[str, str] = {
    "script": "scripts",
    "node": "nodes",
    "pipeline": "pipelines",
    "spec": "specs",
}
"""종류 → 등록소 하위 폴더 이름."""


class RegistryEntry(BaseModel):
    """`registry.json` 의 항목 하나."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """`sc_` / `nd_` / `pl_` / `sp_` 접두 + 자동 발급 부분."""

    kind: EntryKind
    name: str
    """등록 시 사람이 적은 이름. **참조는 이름이 아니라 id 로 한다.**"""

    hash: str
    """등록 당시 파일 내용의 해시. 실행 시 재계산해 대조 (`STR-REG-001`)."""

    registered_at: str
    """ISO8601. 등록/수정 시각."""

    refs: list[str] = Field(default_factory=list)
    """이 항목이 참조하는 다른 항목의 id 들. 역방향 추적의 재료 (`graph.py`)."""

    broken: str = ""
    """깨짐 표시. `""` | `"ref"`(`STR-REG-004`, 대상 삭제) |
    `"validation"`(`STR-REG-005`, 대상 수정으로 상위 검증 무효화)."""

    broken_detail: str = ""
    """깨진 이유 — 없어진 id 또는 실패한 규칙 id."""


class RegistryIndex(BaseModel):
    """`registry.json` 전체."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    entries: dict[str, RegistryEntry] = Field(default_factory=dict)


def default_home() -> Path:
    """`$STRICTLER_HOME` 이 있으면 그것, 없으면 `~/.strictler`.

    경로 규칙(절대경로)이 여기에도 적용된다.
    """
    raise NotImplementedError("Step 1에서 구현")


def hash_file(path: Path) -> str:
    """파일 내용의 해시. 등록 시 저장하고 실행 시 재계산해 대조한다."""
    raise NotImplementedError("Step 1에서 구현")


def new_id(kind: EntryKind) -> str:
    """종류에 맞는 접두를 붙인 새 id 를 발급한다 (`nd_e5f6a7b8`)."""
    raise NotImplementedError("Step 1에서 구현")


class Store:
    """등록소 하나. 폴더 하나에 대응한다."""

    def __init__(self, home: Path | None = None) -> None:
        """`home` 이 없으면 `default_home()`. 없는 폴더는 만든다."""
        raise NotImplementedError("Step 1에서 구현")

    # ── 인덱스 ──────────────────────────────────────────────────────────────

    def load_index(self) -> RegistryIndex:
        """`registry.json` 을 읽는다. 없으면 빈 인덱스."""
        raise NotImplementedError("Step 1에서 구현")

    def save_index(self, index: RegistryIndex) -> None:
        """`registry.json` 을 쓴다."""
        raise NotImplementedError("Step 1에서 구현")

    # ── CRUD ────────────────────────────────────────────────────────────────

    def add(self, kind: EntryKind, source: Path, name: str = "") -> RegistryEntry:
        """파일을 복사해 등록한다. **호출 전에 정적 검사가 통과해 있어야 한다.**

        검사 자체는 `checks.check_registration` 이 하고 CLI 가 순서를 잡는다 —
        등록소는 저장만 책임진다.
        """
        raise NotImplementedError("Step 1에서 구현")

    def list(self, kind: EntryKind | None = None) -> list[RegistryEntry]:
        """목록. `kind` 를 주면 그 종류만. 깨짐 표시가 함께 나온다."""
        raise NotImplementedError("Step 1에서 구현")

    def show(self, entry_id: str) -> RegistryEntry:
        """항목 하나. 없으면 `STR-REG-002`."""
        raise NotImplementedError("Step 1에서 구현")

    def update(self, entry_id: str, source: Path) -> RegistryEntry:
        """내용 교체. **id 유지**, 해시 갱신.

        상위 전이적 재검증은 `graph.RefGraph.revalidate()` 가 이어받는다.
        """
        raise NotImplementedError("Step 1에서 구현")

    def remove(self, entry_id: str) -> None:
        """삭제. **참조가 있어도 막지 않는다.**"""
        raise NotImplementedError("Step 1에서 구현")

    # ── 조회 ────────────────────────────────────────────────────────────────

    def path_of(self, entry_id: str) -> Path:
        """등록소 안의 실제 파일 경로."""
        raise NotImplementedError("Step 1에서 구현")

    def read(self, entry_id: str) -> str:
        """등록소 파일 내용을 읽는다."""
        raise NotImplementedError("Step 1에서 구현")

    def verify_hash(self, entry_id: str) -> bool:
        """복사본의 해시가 등록 당시와 같은지. 실행 시점 검사 (`STR-REG-001`)."""
        raise NotImplementedError("Step 1에서 구현")
