"""Stage orchestration: extract -> merge -> build -> validate.

Each stage reads the previous stage's on-disk artifact, so stages are runnable
independently and every intermediate is inspectable:

    data/sources/<source>/   raw acquired bytes + SOURCE.lock.json  (gitignored)
    data/extracted/<source>.json   normalized GrammarPoint records
    data/merged/corpus.json        unified MergedEntry corpus
    build/<slug>.zip               the one installable dictionary
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import pathlib
import shutil

from . import DICTIONARY_SLUG, YOMITAN_SCHEMA_REVISION
from . import unify
from .banks import build_banks, build_index, build_tag_bank
from .jsonio import MalformedPayload, content_hash, dump_json, load_json
from .merge import MergedEntry, merge_points
from .model import Example, GrammarPoint
from .package import build_zip, package_members
from .styles import STYLES_CSS
from .validate import term_entry_count, validate_zip

DEFAULT_SOURCES_DIR = pathlib.Path("data/sources")
DEFAULT_EXTRACTED_DIR = pathlib.Path("data/extracted")
DEFAULT_MERGED_DIR = pathlib.Path("data/merged")
DEFAULT_BUILD_DIR = pathlib.Path("build")
#: Distribution directory holding the one publishable artifact. A ZIP only
#: appears here after it has passed pinned-schema validation, so `dist/` never
#: contains an archive that failed the gate.
DEFAULT_DIST_DIR = pathlib.Path("dist")

#: Inspectable bank directory written alongside the ZIP. Packaging reads its
#: members from memory, so this directory is not a build input — it is the
#: reviewable form of the exact bytes that went into the archive, which is what
#: downstream schema/geometry/screenshot work needs to diff a card without
#: unzipping. Written from the same member map the ZIP is built from, so a member
#: here and its ZIP counterpart can never disagree.
BANKS_DIR_NAME = "banks"

MERGED_CORPUS_NAME = "corpus.json"


def zip_name() -> str:
    return f"{DICTIONARY_SLUG}.zip"


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------


def run_extract(
    *,
    sources_dir: pathlib.Path = DEFAULT_SOURCES_DIR,
    extracted_dir: pathlib.Path = DEFAULT_EXTRACTED_DIR,
    only: list[str] | None = None,
    corrections_path: pathlib.Path | None = None,
) -> dict[str, object]:
    """Run every registered extractor and write one artifact per source.

    After a source is extracted, the byte-anchored corrections overlay
    (`bugd.corrections`) is applied to its normalized points. The overlay fixes
    formation/gloss defects that live in the immutable source term-bank bytes —
    the SOURCE.lock digests and the locked bytes are never touched, so the
    integrity gate stays intact and every edit remains an auditable, reviewable
    entry rather than a laundered rewrite. Application is fail-closed: a
    correction whose anchor no longer matches its source raises, so a drifted
    source can never silently ship an un-reviewed edit.
    """
    from . import corrections as corrections_module
    from .sources import all_extractors, discover_extractors, get_extractor

    # Populate the registry by importing every source module. Without this the
    # registry is empty (nothing imports the modules for the pipeline) and the
    # stage writes zero artifacts while a stale data/extracted/*.json is silently
    # reused by the build -- exactly the cached-pre-fix-text trap UGD-08c warns of.
    discover_extractors()

    extracted_dir.mkdir(parents=True, exist_ok=True)
    classes = [get_extractor(name) for name in only] if only else all_extractors()

    overlay = corrections_module.load_corrections(
        corrections_path or corrections_module.DEFAULT_CORRECTIONS_PATH
    )

    written: dict[str, int] = {}
    corrected_total = 0
    for cls in classes:
        source_dir = sources_dir / cls.name
        if not only and not source_dir.is_dir():
            # A registered source whose raw bytes have not been acquired into
            # data/sources/<name>/ is simply not built yet -- skip it rather than
            # failing the whole stage on a missing lock. An explicit `--source`
            # request still runs so a typo or missing acquisition surfaces loudly.
            continue
        result = cls(source_dir).extract()
        points, applied = corrections_module.apply_corrections(
            result.points, overlay, source=cls.name
        )
        corrected_total += len(applied)
        stats = dict(result.stats)
        if applied:
            stats["corrections"] = applied
        payload = {
            "source": result.source,
            "label": cls.label or cls.name,
            "aiGeneratedSource": cls.ai_generated_source,
            "consumed": result.consumed,
            "stats": stats,
            "points": [point_to_json(point) for point in points],
        }
        (extracted_dir / f"{cls.name}.json").write_text(
            dump_json(payload) + "\n", encoding="utf-8"
        )
        written[cls.name] = len(points)
    return {
        "sources": written,
        "total": sum(written.values()),
        "corrections": corrected_total,
    }


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------


def run_merge(
    *,
    extracted_dir: pathlib.Path = DEFAULT_EXTRACTED_DIR,
    merged_dir: pathlib.Path = DEFAULT_MERGED_DIR,
    keymap_path: pathlib.Path | None = None,
    unified_path: pathlib.Path | None = None,
) -> dict[str, object]:
    """Merge every extracted artifact into the one unified corpus.

    The real cross-source policy lives in `bugd.unify`, driven by the keymap
    `make keymap` emits. It fails closed when the keymap and the extraction are
    not self-consistent, because the tolerant alternative silently deletes rows
    (a stale keymap left 1,664 substantive rows unresolved and a best-effort
    merge would have dropped them while reporting success).

    `data/merge/unified.jsonl` is the reviewable artifact; `data/merged/corpus.json`
    is its projection onto the bank generator's input contract, so the renderer
    keeps consuming the stage boundary it was written against.
    """
    keymap_path = keymap_path or unify.DEFAULT_KEYMAP_PATH
    unified_path = unified_path or unify.DEFAULT_UNIFIED_PATH

    rows, labels = unify.load_extracted(extracted_dir)
    keymap = unify.load_keymap(keymap_path)
    unified, stats = unify.unify(rows, keymap, labels)

    byte_count, digest = unify.write_unified(unified, unified_path)
    stats["artifact"] = {
        "path": str(unified_path),
        "byteCount": byte_count,
        "contentHash": digest,
        "keymapPath": str(keymap_path),
    }
    stats_path = unified_path.with_name(f"{unified_path.stem}.stats.json")
    stats_path.write_text(dump_json(stats) + "\n", encoding="utf-8")

    entries = unify.to_merged_entries(unified)
    corpus = {
        "sourceLabels": labels,
        "entries": [entry_to_json(entry) for entry in entries],
    }
    merged_dir.mkdir(parents=True, exist_ok=True)
    (merged_dir / MERGED_CORPUS_NAME).write_text(dump_json(corpus) + "\n", encoding="utf-8")
    return {
        "points": len(rows),
        "entries": len(entries),
        "pointEntries": stats["unified"]["pointEntries"],
        "redirectEntries": stats["unified"]["redirectEntries"],
        "contributions": stats["unified"]["contributions"],
        "sources": sorted(labels),
        "unifiedPath": str(unified_path),
        "statsPath": str(stats_path),
        "contentHash": content_hash(corpus),
    }


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def run_build(
    *,
    merged_dir: pathlib.Path = DEFAULT_MERGED_DIR,
    build_dir: pathlib.Path = DEFAULT_BUILD_DIR,
    dist_dir: pathlib.Path | None = None,
    revision: str | None = None,
    require_entries: bool = False,
) -> dict[str, object]:
    """Emit the ONE installable dictionary ZIP from the merged corpus.

    The build is its own gate: the archive is assembled in `build_dir`, validated
    against the pinned official Yomitan schemas, and only then published to
    `dist_dir`. A schema failure raises `SchemaValidationError` and leaves
    `dist/` untouched, so a ZIP present in `dist/` has always passed validation.

    Publishing is opt-in: `dist_dir` is `None` unless a caller (the CLI, driven
    by `make build`) asks for it, so building never writes outside `build_dir`
    as a side effect.

    A missing merged corpus is not an error while sources are still landing: the
    pipeline emits a valid empty-corpus ZIP so packaging, reproducibility, and
    schema validation are exercisable before source logic exists. Pass
    `require_entries=True` (the release gate) to refuse it.
    """
    corpus_path = merged_dir / MERGED_CORPUS_NAME
    if corpus_path.is_file():
        corpus = load_json(corpus_path.read_text(encoding="utf-8"))
        entries = [entry_from_json(item) for item in corpus["entries"]]
        source_labels = dict(corpus.get("sourceLabels") or {})
    else:
        corpus = {"sourceLabels": {}, "entries": []}
        entries = []
        source_labels = {}

    revision = revision or datetime.datetime.now(datetime.UTC).strftime("%Y.%m.%d")
    members = package_members(
        index=build_index(revision, source_labels=source_labels),
        banks=build_banks(entries),
        tag_bank=build_tag_bank(source_labels),
        styles_css=STYLES_CSS,
    )
    archive = build_zip(members)

    build_dir.mkdir(parents=True, exist_ok=True)
    zip_path = build_dir / zip_name()
    zip_path.write_bytes(archive)
    banks_dir = write_banks_dir(members, build_dir=build_dir)

    failures = validate_zip(zip_path, require_entries=require_entries)
    if failures:
        raise SchemaValidationError(zip_path, failures)

    digest = hashlib.sha256(archive).hexdigest()
    result: dict[str, object] = {
        "zipPath": str(zip_path),
        "banksDir": str(banks_dir),
        "revision": revision,
        "entries": len(entries),
        "termEntries": term_entry_count(zip_path),
        "members": sorted(members),
        "byteCount": len(archive),
        "sha256": digest,
        "contentHash": content_hash(corpus),
        "schemaRevision": YOMITAN_SCHEMA_REVISION,
    }

    if dist_dir is not None:
        result["distPath"] = str(publish_dist(archive, digest, dist_dir=dist_dir))
    return result


def write_banks_dir(
    members: dict[str, bytes | str],
    *,
    build_dir: pathlib.Path = DEFAULT_BUILD_DIR,
) -> pathlib.Path:
    """Write the packaged members to `build/banks/` for review.

    The directory is rebuilt from scratch each time so a bank that disappeared
    from the corpus (a shrinking `term_bank_N.json` tail) cannot linger and be
    mistaken for current output. Bytes are written exactly as packaged — not
    re-serialised — so `banks/term_bank_1.json` and the ZIP member are identical
    by construction rather than by convention.
    """
    banks_dir = build_dir / BANKS_DIR_NAME
    if banks_dir.exists():
        shutil.rmtree(banks_dir)
    for name, payload in members.items():
        target = banks_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload.encode("utf-8") if isinstance(payload, str) else payload)
    return banks_dir


def publish_dist(
    archive: bytes, digest: str, *, dist_dir: pathlib.Path = DEFAULT_DIST_DIR
) -> pathlib.Path:
    """Publish validated bytes to `dist/` plus a `SHA256SUMS` sidecar.

    The write is atomic (temp file + replace) so a reader never observes a
    half-written archive, and the sidecar records the digest of the exact bytes
    published rather than of a later rebuild.
    """
    dist_dir.mkdir(parents=True, exist_ok=True)
    dist_path = dist_dir / zip_name()
    _atomic_write(dist_path, archive)
    _atomic_write(
        dist_dir / "SHA256SUMS", f"{digest}  {zip_name()}\n".encode("utf-8")
    )
    return dist_path


def _atomic_write(path: pathlib.Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


class SchemaValidationError(MalformedPayload):
    """A built archive failed pinned Yomitan schema validation.

    Raised by `run_build` so the build fails closed: an invalid dictionary is
    never published to `dist/` and never reported as a successful build.
    """

    def __init__(self, zip_path: pathlib.Path, failures: list[str]) -> None:
        self.zip_path = zip_path
        self.failures = failures
        listed = "\n  - ".join(failures)
        super().__init__(
            f"{zip_path} failed pinned Yomitan schema validation "
            f"({len(failures)} failure(s)):\n  - {listed}"
        )


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def run_validate(
    *,
    build_dir: pathlib.Path = DEFAULT_BUILD_DIR,
    require_entries: bool = False,
) -> tuple[bool, list[str]]:
    """Validate the built ZIP against the pinned official Yomitan schemas."""
    zip_path = build_dir / zip_name()
    if not zip_path.is_file():
        return False, [f"no built artifact to validate: {zip_path}"]
    failures = validate_zip(zip_path, require_entries=require_entries)
    return not failures, failures


# --------------------------------------------------------------------------
# interchange (de)serialisation
# --------------------------------------------------------------------------


def point_to_json(point: GrammarPoint) -> dict:
    payload = dataclasses.asdict(point)
    payload["examples"] = [dataclasses.asdict(example) for example in point.examples]
    return payload


def point_from_json(payload: dict) -> GrammarPoint:
    if not isinstance(payload, dict):
        raise MalformedPayload("a GrammarPoint payload must be an object")
    data = dict(payload)
    examples = data.pop("examples", ()) or ()
    for name in ("variants", "tags"):
        if name in data and data[name] is not None:
            data[name] = tuple(data[name])
    return GrammarPoint(
        **data,
        examples=tuple(
            Example(
                japanese=item["japanese"],
                english=item.get("english"),
                highlight=tuple(item.get("highlight") or ()),
                ai_generated=bool(item.get("ai_generated")),
                # Rebuilt explicitly: this is the stage seam between extract and
                # merge, so a field omitted here is silently deleted from the
                # corpus. `japanese_html` carries the source's own furigana for
                # 98.7% of Bunpro's sentences.
                japanese_html=item.get("japanese_html"),
            )
            for item in examples
        ),
    )


def entry_to_json(entry: MergedEntry) -> dict:
    return {
        "expression": entry.expression,
        "variants": list(entry.variants),
        "contributions": [point_to_json(point) for point in entry.contributions],
    }


def entry_from_json(payload: dict) -> MergedEntry:
    if not isinstance(payload, dict):
        raise MalformedPayload("a MergedEntry payload must be an object")
    return MergedEntry(
        expression=payload["expression"],
        variants=tuple(payload.get("variants") or ()),
        contributions=[point_from_json(item) for item in payload.get("contributions") or []],
    )


__all__ = [
    "DEFAULT_SOURCES_DIR",
    "DEFAULT_EXTRACTED_DIR",
    "DEFAULT_MERGED_DIR",
    "DEFAULT_BUILD_DIR",
    "DEFAULT_DIST_DIR",
    "BANKS_DIR_NAME",
    "MERGED_CORPUS_NAME",
    "SchemaValidationError",
    "zip_name",
    "publish_dist",
    "write_banks_dir",
    "run_extract",
    "run_merge",
    "run_build",
    "run_validate",
    "point_to_json",
    "point_from_json",
    "entry_to_json",
    "entry_from_json",
]
