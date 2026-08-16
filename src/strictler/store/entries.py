"""등록소 인덱스와 CRUD (`schema.md` 2절).

**등록 시 정적 검사를 통과해야 저장된다.** 잘못된 것이 등록소에 들어가지 않는다.
**실행 시 해시를 대조한다** — 정적 검사 루트를 피해 등록소 파일을 직접 고치는 것을 막는다.

**수정은 id 를 유지한다.** 참조가 안 깨진다. 대신 상위를 전이적으로 재검증한다 —
수정은 참조가 멀쩡한 채로 **검증만 조용히 무효화**하기 때문이다.

**삭제도 수정도 막지 않는다.** 막으면 교착이 생긴다(하위를 고치려면 상위를 먼저
고쳐야 하는데 상위는 하위 때문에 못 고친다). 대신 목록 조회에서 깨짐을 표시한다.

이 모듈은 **저장만 책임진다.** 등록 전 정적 검사는 `checks.check_registration` 이
하고 순서는 CLI 가 잡는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from strictler.errors import StrictlerError
from strictler.model import ID_PREFIXES, EntryKind
from strictler.refs import PLACEHOLDER_RE

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


_EXTENSIONS: dict[str, str] = {
    "script": ".py",
    "node": ".json",
    "pipeline": ".json",
    "spec": ".json",
}
"""종류 → 등록소 안에서 쓰는 확장자. 스크립트 언어는 Python 하나뿐이다."""

_PREFIX_OF: dict[str, str] = {kind: prefix for prefix, kind in ID_PREFIXES.items()}
"""종류 → id 접두. `model.ID_PREFIXES` 의 역방향."""

_INDEX_NAME = "registry.json"

_PLACEHOLDER = re.compile(PLACEHOLDER_RE)
"""`${ns.name}` 스캐너. 여기서는 `ns == "ref"` 인 것만 본다."""


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

    경로 규칙(절대경로)이 여기에도 적용된다 — `~` 를 전개한 뒤에도 절대경로가
    아니면 오류다. cwd 에 따라 등록소가 달라지면 등록의 의미가 없어진다.
    """
    raw = os.environ.get("STRICTLER_HOME", "").strip() or "~/.strictler"
    home = Path(os.path.expanduser(raw))
    if not home.is_absolute():
        raise StrictlerError(
            f"STRICTLER_HOME 이 절대경로가 아닙니다: {raw}\n"
            "등록소 경로는 cwd 와 무관해야 합니다. "
            "`/home/me/.strictler` 나 `~/.strictler` 처럼 절대경로로 지정하세요."
        )
    return home


def hash_file(path: Path) -> str:
    """파일 내용의 해시. 등록 시 저장하고 실행 시 재계산해 대조한다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_id(kind: EntryKind) -> str:
    """종류에 맞는 접두를 붙인 새 id 를 발급한다 (`nd_e5f6a7b8`)."""
    prefix = _PREFIX_OF.get(kind)
    if prefix is None:
        raise StrictlerError(
            f"등록소가 모르는 종류입니다: {kind}\n"
            f"쓸 수 있는 종류: {', '.join(sorted(_PREFIX_OF))}"
        )
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _collect_refs(text: str) -> list[str]:
    """내용에서 `${ref.<id>}` 의 id 들을 등장 순서대로 뽑는다 (중복 제거).

    참조 그래프의 재료다. **존재 여부는 여기서 보지 않는다** — 없는 id 를 가리키는
    것도 그대로 기록해야 `graph.broken_refs()` 가 참조 깨짐을 드러낼 수 있다.
    """
    found: list[str] = []
    for match in _PLACEHOLDER.finditer(text):
        if match.group("ns") != "ref":
            continue
        ref_id = match.group("name").strip()
        if ref_id not in found:
            found.append(ref_id)
    return found


def _read_source(source: Path) -> tuple[Path, str]:
    """등록할 원본을 읽는다. 없으면 **오류** — 도구가 못 돈 것이다."""
    path = Path(os.path.expanduser(str(source)))
    if not path.is_absolute():
        path = path.resolve()
    if not path.is_file():
        raise StrictlerError(
            f"등록할 파일이 없습니다: {path}\n"
            "경로를 확인하세요. 등록소는 파일을 복사해 보관하므로 원본이 있어야 합니다."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # raw 예외로 새면 "도구가 못 돈 것" 이 규칙 id 도 가이드도 없이 나간다.
        raise StrictlerError(
            f"등록할 파일이 UTF-8 이 아닙니다: {path} ({exc.reason}, byte {exc.start})\n"
            "등록 대상은 `.py` 스크립트와 `.json` 문서뿐이고 둘 다 UTF-8 이어야 합니다. "
            "파일 인코딩을 UTF-8 로 바꿔 다시 등록하세요."
        ) from exc
    return path, text


def _now_iso() -> str:
    """등록/수정 시각. **등록 시점의 사실**이므로 여기서 읽는다 —
    실행 엔진이 시각을 읽지 않는 규칙(`started_at_ms`)과는 다른 자리다."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """등록소 하나. 폴더 하나에 대응한다."""

    def __init__(self, home: Path | None = None) -> None:
        """`home` 이 없으면 `default_home()`. 없는 폴더는 만든다."""
        self.home: Path = Path(home) if home is not None else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        for subdir in SUBDIRS.values():
            (self.home / subdir).mkdir(exist_ok=True)

    # ── 인덱스 ──────────────────────────────────────────────────────────────

    @property
    def index_path(self) -> Path:
        return self.home / _INDEX_NAME

    def load_index(self) -> RegistryIndex:
        """`registry.json` 을 읽는다. 없으면 빈 인덱스."""
        path = self.index_path
        if not path.is_file():
            return RegistryIndex()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # 손상은 반반이다 — 깨진 JSON 이거나 깨진 인코딩이거나.
            # 한쪽만 감싸면 나머지 절반이 raw 예외로 샌다.
            raise StrictlerError(
                f"등록소 인덱스가 UTF-8 이 아닙니다: {path} "
                f"({exc.reason}, byte {exc.start})\n"
                "`registry.json` 이 손상됐습니다. 손으로 고치지 말고 등록소를 다시 만드세요."
            ) from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrictlerError(
                f"등록소 인덱스를 읽을 수 없습니다: {path} ({exc})\n"
                "`registry.json` 이 손상됐습니다. 손으로 고치지 말고 등록소를 다시 만드세요."
            ) from exc
        return RegistryIndex.model_validate(raw)

    def save_index(self, index: RegistryIndex) -> None:
        """`registry.json` 을 쓴다."""
        self.index_path.write_text(
            json.dumps(index.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ── CRUD ────────────────────────────────────────────────────────────────

    def add(self, kind: EntryKind, source: Path, name: str = "") -> RegistryEntry:
        """파일을 복사해 등록한다. **호출 전에 정적 검사가 통과해 있어야 한다.**

        검사 자체는 `checks.check_registration` 이 하고 CLI 가 순서를 잡는다 —
        등록소는 저장만 책임진다.
        """
        path, text = _read_source(source)
        index = self.load_index()

        entry_id = new_id(kind)
        while entry_id in index.entries:
            entry_id = new_id(kind)

        entry = RegistryEntry(
            id=entry_id,
            kind=kind,
            name=name or path.stem,
            hash=hash_file(path),
            registered_at=_now_iso(),
            refs=_collect_refs(text),
        )
        shutil.copyfile(path, self._file_path(kind, entry_id))
        index.entries[entry_id] = entry
        self.save_index(index)
        return entry

    def list(self, kind: EntryKind | None = None) -> list[RegistryEntry]:
        """목록. `kind` 를 주면 그 종류만. 깨짐 표시가 함께 나온다.

        `broken == "validation"` 은 재검증(`graph.RefGraph.revalidate`)이 인덱스에
        적어둔 것이라 그대로 나오고, **참조 깨짐은 삭제 시점에 계산할 수 없으므로**
        (지워진 쪽은 자기를 참조하는 상위를 모른다) `graph.RefGraph.broken_refs()`
        가 목록 조회 시점에 얹는다.
        """
        entries = list(self.load_index().entries.values())
        if kind is None:
            return entries
        return [entry for entry in entries if entry.kind == kind]

    def show(self, entry_id: str) -> RegistryEntry:
        """항목 하나. 없으면 오류다."""
        index = self.load_index()
        entry = index.entries.get(entry_id)
        if entry is None:
            raise StrictlerError(
                f"등록소에 없는 id 입니다: {entry_id}\n"
                "삭제됐거나 오타입니다. `strictler <종류> list` 로 확인하세요 "
                "(접두 `sc_`=스크립트 `nd_`=노드 `pl_`=파이프라인 `sp_`=Spec)."
            )
        return entry

    def update(self, entry_id: str, source: Path) -> RegistryEntry:
        """내용 교체. **id 유지**, 해시 갱신.

        상위 전이적 재검증은 `graph.RefGraph.revalidate()` 가 이어받는다.
        """
        path, text = _read_source(source)
        index = self.load_index()
        entry = index.entries.get(entry_id)
        if entry is None:
            raise StrictlerError(
                f"등록소에 없는 id 입니다: {entry_id}\n"
                "수정은 이미 등록된 것에만 됩니다. 새 것이면 `add` 를 쓰세요."
            )

        shutil.copyfile(path, self._file_path(entry.kind, entry_id))
        entry.hash = hash_file(path)
        entry.registered_at = _now_iso()
        entry.refs = _collect_refs(text)
        # 새 내용이 검사를 통과해 들어온 것이므로 자기 자신의 깨짐 표시는 걷는다.
        # 상위의 깨짐은 재검증이 다시 판정한다.
        entry.broken = ""
        entry.broken_detail = ""
        self.save_index(index)
        return entry

    def remove(self, entry_id: str) -> None:
        """삭제. **참조가 있어도 막지 않는다.**

        막으면 교착이 생긴다. 깨진 것은 `graph.RefGraph.broken_refs()` 가 드러낸다.
        """
        index = self.load_index()
        entry = index.entries.pop(entry_id, None)
        if entry is None:
            raise StrictlerError(
                f"등록소에 없는 id 입니다: {entry_id}\n"
                "이미 삭제됐거나 오타입니다. `strictler <종류> list` 로 확인하세요."
            )
        self._file_path(entry.kind, entry_id).unlink(missing_ok=True)
        self.save_index(index)

    # ── 조회 ────────────────────────────────────────────────────────────────

    def _file_path(self, kind: EntryKind, entry_id: str) -> Path:
        return self.home / SUBDIRS[kind] / f"{entry_id}{_EXTENSIONS[kind]}"

    def path_of(self, entry_id: str) -> Path:
        """등록소 안의 실제 파일 경로."""
        entry = self.show(entry_id)
        return self._file_path(entry.kind, entry_id)

    def read(self, entry_id: str) -> str:
        """등록소 파일 내용을 읽는다.

        정상 경로로는 UTF-8 만 들어가지만, **정적 검사 루트를 피해 등록소 파일을
        직접 고치는 것이 바로 `STR-REG-001` 이 상정하는 시나리오다.**
        `verify_hash` 를 먼저 부른다는 보장이 없으므로 여기서도 감싼다.
        """
        path = self.path_of(entry_id)
        if not path.is_file():
            raise StrictlerError(
                f"등록소 파일이 없습니다: {path}\n"
                "인덱스에는 있는데 실제 파일이 사라졌습니다. 삭제 후 재등록하세요."
            )
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise StrictlerError(
                f"등록소 파일이 UTF-8 이 아닙니다: {path} "
                f"({exc.reason}, byte {exc.start})\n"
                "등록소 파일이 등록 이후에 직접 수정된 것으로 보입니다. "
                "원본을 UTF-8 로 고쳐 `update` 로 다시 등록하세요."
            ) from exc

    def verify_hash(self, entry_id: str) -> bool:
        """복사본의 해시가 등록 당시와 같은지. 실행 시점 검사 (`STR-REG-001`).

        해시가 그대로면 이미 검증을 통과한 그 내용이므로 **다시 검사하지 않는다** —
        등록은 편의가 아니라 검증 결과를 재사용하는 기제다.
        """
        entry = self.show(entry_id)
        path = self._file_path(entry.kind, entry_id)
        if not path.is_file():
            return False
        return hash_file(path) == entry.hash
