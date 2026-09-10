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
from .reading_corrections import (
    DEFAULT_CORRECTIONS_PATH as DEFAULT_READING_CORRECTIONS_PATH,
)
from .reading_corrections import load_corrections as load_reading_corrections
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
#: Distribution directory holding the built artifact. A ZIP only appears here
#: after it has passed pinned-schema validation, so `dist/` never contains an
#: archive that failed the gate.
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


def _unacquired_reason(source_dir: pathlib.Path) -> str | None:
    """Why this source cannot be extracted yet, or ``None`` if it can.

    "Acquired" means the bytes the lock PINS are on disk, not that the directory
    exists: `SOURCE.lock.json` is committed for every source (it is the
    reproducibility contract -- 611 files pinned by sha256), so in a fresh clone
    every `data/sources/<name>/` directory exists while holding only that lock.

    Returns a human-readable reason so the caller can REPORT the skip. A silently
    smaller dictionary is the failure mode this project fails closed against, so
    a skip must be visible in the stage's output.
    """
    from .sources.base import SOURCE_LOCK_NAME, load_source_lock

    source_dir = pathlib.Path(source_dir)
    if not source_dir.is_dir():
        return "no source directory"
    if not (source_dir / SOURCE_LOCK_NAME).is_file():
        return f"no {SOURCE_LOCK_NAME}"
    try:
        locked = load_source_lock(source_dir)
    except MalformedPayload as error:
        # A malformed lock is a real defect, not an unacquired source. Let the
        # extractor raise it so it cannot be mistaken for "not built yet".
        raise error
    missing = [name for name in locked if not (source_dir / name).exists()]
    if not missing:
        return None
    shown = ", ".join(sorted(missing)[:3])
    if len(missing) > 3:
        shown += f", +{len(missing) - 3} more"
    return f"{len(missing)} of {len(locked)} locked file(s) not acquired ({shown})"


def run_extract(
    *,
    sources_dir: pathlib.Path = DEFAULT_SOURCES_DIR,
    extracted_dir: pathlib.Path = DEFAULT_EXTRACTED_DIR,
    only: list[str] | None = None,
    corrections_path: pathlib.Path | None = None,
    corrections_dir: pathlib.Path | None = None,
) -> dict[str, object]:
    """Run every registered extractor and write one artifact per source.

    Two independent, reviewable correction overlays are applied to the normalized
    records after extraction and before the per-source artifact is written. In
    both cases the locked publisher bytes and their SOURCE.lock digests are
    untouched, so the integrity gate stays intact and every edit stays an
    auditable entry rather than a laundered rewrite:

    * `bugd.structure_corrections` (UGD-11c-C) is byte-anchored and fixes
      formation/gloss defects that live in the immutable source term-bank bytes.
      Fail-closed: a correction whose anchor no longer matches raises, so a
      drifted source can never silently ship an un-reviewed edit.
    * `bugd.content_corrections` (UGD-11c-D) applies the confirmed content
      dispositions (drop_example / remove_span / clear_field / replace_span) from
      the review.

    Structure runs first because its anchors are quoted from the publisher's
    original bytes; a content disposition that drops or trims the same field
    would otherwise make the anchor unmatchable and fail the build closed.

    The registry populates itself on first query: `all_extractors()` calls
    `load_source_modules()`, which imports every source module so its
    `@register_extractor` runs. Without that the registry is empty, the stage
    writes zero artifacts, and the build silently reuses a stale
    `data/extracted/*.json` -- the cached-pre-fix-text trap.
    """
    from . import structure_corrections as corrections_module
    from .content_corrections import DEFAULT_CORRECTIONS_DIR
    from .content_corrections import apply_corrections as apply_content_corrections
    from .content_corrections import load_corrections as load_content_corrections
    from .sources import all_extractors, get_extractor


    extracted_dir.mkdir(parents=True, exist_ok=True)
    classes = [get_extractor(name) for name in only] if only else all_extractors()

    overlay = corrections_module.load_corrections(
        corrections_path or corrections_module.DEFAULT_CORRECTIONS_PATH
    )
    correction_dir = corrections_dir if corrections_dir is not None else DEFAULT_CORRECTIONS_DIR
    content_corrections = load_content_corrections(correction_dir)

    written: dict[str, int] = {}
    corrected_total = 0
    corrections_report: dict[str, object] = {}
    skipped: dict[str, str] = {}
    for cls in classes:
        source_dir = sources_dir / cls.name
        if not only:
            unacquired = _unacquired_reason(source_dir)
            if unacquired is not None:
                # A registered source whose raw bytes have not been acquired is
                # simply not built yet -- skip it rather than failing the whole
                # stage. Keyed on the LOCKED PAYLOAD, not on the directory
                # existing: every source directory exists in a fresh clone because
                # `SOURCE.lock.json` is committed (it is the reproducibility
                # contract), so a directory check skipped nothing and a clean
                # clone that had acquired only some sources could not run
                # `make extract` at all.
                #
                # The skip is REPORTED, not silent: the reason lands in the
                # stage's output so a missing acquisition is visible rather than
                # presenting as a quietly smaller dictionary. An explicit
                # `--source` request still runs and still fails loudly, so a typo
                # or a genuinely broken acquisition surfaces.
                skipped[cls.name] = unacquired
                continue
        result = cls(source_dir).extract()
        points, applied = corrections_module.apply_corrections(
            result.points, overlay, source=cls.name
        )
        corrected_total += len(applied)
        stats = dict(result.stats)
        if applied:
            stats["corrections"] = applied
        if content_corrections:
            points, report = apply_content_corrections(
                points, content_corrections, source=cls.name
            )
            if report["applied"]:
                corrections_report[cls.name] = report

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
    out: dict[str, object] = {
        "sources": written,
        "total": sum(written.values()),
        "corrections": corrected_total,
    }
    if skipped:
        # Reported, with the reason, so an unacquired source is never invisible.
        out["skippedSources"] = skipped
    if corrections_report:
        out["contentCorrections"] = corrections_report
    return out


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------


def run_merge(
    *,
    extracted_dir: pathlib.Path = DEFAULT_EXTRACTED_DIR,
    merged_dir: pathlib.Path = DEFAULT_MERGED_DIR,
    keymap_path: pathlib.Path | None = None,
    unified_path: pathlib.Path | None = None,
    corrections_path: pathlib.Path | None = DEFAULT_READING_CORRECTIONS_PATH,
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

    `corrections_path` locates the evidence-backed reading-correction overlay,
    applied to the assembled contributions. It defaults to the canonical overlay
    (`data/corrections/readings.json`); pass `None` to merge with no corrections
    (used by callers that build an isolated corpus the canonical overlay does not
    describe). The overlay is keyed to a specific extraction and fails closed if a
    correction matches no row, so it must not be pointed at an unrelated corpus.
    """
    keymap_path = keymap_path or unify.DEFAULT_KEYMAP_PATH
    unified_path = unified_path or unify.DEFAULT_UNIFIED_PATH

    rows, labels = unify.load_extracted(extracted_dir)
    keymap = unify.load_keymap(keymap_path)
    corrections = (
        load_reading_corrections(corrections_path)
        if corrections_path is not None
        else []
    )
    unified, stats = unify.unify(rows, keymap, labels, corrections=corrections)

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
    index = build_index(revision, source_labels=source_labels)
    members = package_members(
        index=index,
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
        result["distPath"] = str(
            publish_dist(archive, digest, dist_dir=dist_dir, index=index)
        )
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
    archive: bytes,
    digest: str,
    *,
    dist_dir: pathlib.Path = DEFAULT_DIST_DIR,
    index: dict | None = None,
) -> pathlib.Path:
    """Publish validated bytes to `dist/` plus `SHA256SUMS` and `index.json`.

    The write is atomic (temp file + replace) so a reader never observes a
    half-written archive, and the sidecar records the digest of the exact bytes
    published rather than of a later rebuild.

    `index.json` is published BESIDE the archive, byte-identical to the copy inside
    it, because that is what the archive's own `indexUrl` points at: an update
    checker reads the small index to learn the current revision without downloading
    six megabytes of banks. Writing it from the same `index` dict the archive was
    packaged from is what keeps the two from disagreeing about the revision.
    """
    dist_dir.mkdir(parents=True, exist_ok=True)
    dist_path = dist_dir / zip_name()
    _atomic_write(dist_path, archive)
    _atomic_write(
        dist_dir / "SHA256SUMS", f"{digest}  {zip_name()}\n".encode("utf-8")
    )
    if index is not None:
        _atomic_write(dist_dir / "index.json", (dump_json(index) + "\n").encode("utf-8"))
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
