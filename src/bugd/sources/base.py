"""Base contract every per-source extractor implements."""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass, field

from ..jsonio import MalformedPayload, load_json
from ..model import GrammarPoint

SOURCE_LOCK_NAME = "SOURCE.lock.json"

#: Per-source JSONL lands beside the locked bytes so a reviewer can read one
#: source's normalized records without running the merge stage. Shared by every
#: extractor family, not only the community-bank one, so a reviewer never has to
#: learn a per-source artifact name.
JSONL_NAME = "points.jsonl"


def write_points_jsonl(
    input_dir: pathlib.Path, points: list[GrammarPoint]
) -> pathlib.Path:
    """Write one source's records as JSONL into its own source directory.

    Deterministic by construction: records are written in the order the extractor
    emitted them, one canonical JSON object per line, so two runs over identical
    locked bytes produce identical files.
    """
    from ..jsonio import dump_json
    from ..pipeline import point_to_json

    path = pathlib.Path(input_dir) / JSONL_NAME
    path.write_text(
        "".join(dump_json(point_to_json(point)) + "\n" for point in points),
        encoding="utf-8",
    )
    return path


class SourceLockError(MalformedPayload):
    """A source directory's lock is missing, malformed, or does not match bytes."""


@dataclass
class ExtractResult:
    """What one extractor produced, plus the provenance to justify it."""

    source: str
    points: list[GrammarPoint] = field(default_factory=list)
    consumed: dict[str, str] = field(default_factory=dict)
    stats: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise MalformedPayload("ExtractResult.source must be a non-empty string")
        for point in self.points:
            if point.source != self.source:
                raise MalformedPayload(
                    f"extractor {self.source!r} emitted a point attributed to {point.source!r}"
                )


class Extractor:
    """One grammar source.

    Subclasses set `name` and implement `extract`. `input_dir` is
    `data/sources/<name>/`; nothing outside it may be read, and every file read
    must appear in that directory's `SOURCE.lock.json`.
    """

    name: str = ""
    #: Human-facing attribution label rendered on merged entries.
    label: str = ""
    #: Set when the source's substantive content is AI/LLM-generated and must be
    #: segregated behind a labelled disclosure rather than shown as fact.
    ai_generated_source: bool = False

    def __init__(self, input_dir: pathlib.Path) -> None:
        if not self.name:
            raise MalformedPayload(f"{type(self).__name__} does not declare a source name")
        self.input_dir = pathlib.Path(input_dir)

    def extract(self) -> ExtractResult:
        raise NotImplementedError(f"{type(self).__name__}.extract is not implemented yet")

    def read_locked_bytes(self, relative_path: str) -> bytes:
        """Read one locked input, failing closed on any digest mismatch."""
        lock = load_source_lock(self.input_dir)
        entry = lock.get(relative_path)
        if entry is None:
            raise SourceLockError(f"{relative_path!r} is not listed in {self.name}'s source lock")
        path = self.input_dir / relative_path
        if not path.is_file():
            raise SourceLockError(f"locked input is missing: {path}")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != entry["sha256"]:
            raise SourceLockError(
                f"{relative_path!r} digest mismatch: locked {entry['sha256']}, found {actual}"
            )
        if len(raw) != entry["byteCount"]:
            raise SourceLockError(f"{relative_path!r} byte count does not match its lock")
        return raw


def load_source_lock(input_dir: pathlib.Path) -> dict[str, dict]:
    """Load and shape-check one source directory's lock."""
    lock_path = pathlib.Path(input_dir) / SOURCE_LOCK_NAME
    if not lock_path.is_file():
        raise SourceLockError(f"missing source lock: {lock_path}")
    payload = load_json(lock_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise SourceLockError(f"malformed source lock: {lock_path}")
    files: dict[str, dict] = {}
    for relative_path, entry in payload["files"].items():
        pure = pathlib.PurePosixPath(relative_path)
        if (
            not relative_path
            or "\\" in relative_path
            or pure.is_absolute()
            or ".." in pure.parts
            or "." in pure.parts
            or str(pure) != relative_path
        ):
            raise SourceLockError(f"unsafe locked path: {relative_path!r}")
        if not isinstance(entry, dict):
            raise SourceLockError(f"malformed lock entry for {relative_path!r}")
        digest = entry.get("sha256")
        byte_count = entry.get("byteCount")
        if not isinstance(digest, str) or len(digest) != 64:
            raise SourceLockError(f"lock entry for {relative_path!r} has no sha256")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise SourceLockError(f"lock entry for {relative_path!r} has an invalid byteCount")
        files[relative_path] = entry
    return files


__all__ = [
    "Extractor",
    "ExtractResult",
    "SourceLockError",
    "SOURCE_LOCK_NAME",
    "JSONL_NAME",
    "load_source_lock",
    "write_points_jsonl",
]
