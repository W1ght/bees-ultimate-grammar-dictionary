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

from . import DICTIONARY_SLUG
from .banks import build_banks, build_index, build_tag_bank
from .jsonio import MalformedPayload, content_hash, dump_json, load_json
from .merge import MergedEntry, merge_points
from .model import Example, GrammarPoint
from .package import build_zip, package_members
from .styles import STYLES_CSS
from .validate import validate_zip

DEFAULT_SOURCES_DIR = pathlib.Path("data/sources")
DEFAULT_EXTRACTED_DIR = pathlib.Path("data/extracted")
DEFAULT_MERGED_DIR = pathlib.Path("data/merged")
DEFAULT_BUILD_DIR = pathlib.Path("build")

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
) -> dict[str, object]:
    """Run every registered extractor and write one artifact per source."""
    from .sources import all_extractors, get_extractor

    extracted_dir.mkdir(parents=True, exist_ok=True)
    classes = [get_extractor(name) for name in only] if only else all_extractors()

    written: dict[str, int] = {}
    for cls in classes:
        result = cls(sources_dir / cls.name).extract()
        payload = {
            "source": result.source,
            "label": cls.label or cls.name,
            "aiGeneratedSource": cls.ai_generated_source,
            "consumed": result.consumed,
            "stats": result.stats,
            "points": [point_to_json(point) for point in result.points],
        }
        (extracted_dir / f"{cls.name}.json").write_text(
            dump_json(payload) + "\n", encoding="utf-8"
        )
        written[cls.name] = len(result.points)
    return {"sources": written, "total": sum(written.values())}


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------


def run_merge(
    *,
    extracted_dir: pathlib.Path = DEFAULT_EXTRACTED_DIR,
    merged_dir: pathlib.Path = DEFAULT_MERGED_DIR,
) -> dict[str, object]:
    """Merge every extracted artifact into the one unified corpus."""
    points: list[GrammarPoint] = []
    labels: dict[str, str] = {}
    for path in sorted(extracted_dir.glob("*.json")):
        payload = load_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
            raise MalformedPayload(f"malformed extracted artifact: {path}")
        labels[payload["source"]] = payload.get("label") or payload["source"]
        points.extend(point_from_json(item) for item in payload["points"])

    entries = merge_points(points)
    corpus = {
        "sourceLabels": labels,
        "entries": [entry_to_json(entry) for entry in entries],
    }
    merged_dir.mkdir(parents=True, exist_ok=True)
    (merged_dir / MERGED_CORPUS_NAME).write_text(dump_json(corpus) + "\n", encoding="utf-8")
    return {
        "points": len(points),
        "entries": len(entries),
        "sources": sorted(labels),
        "contentHash": content_hash(corpus),
    }


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def run_build(
    *,
    merged_dir: pathlib.Path = DEFAULT_MERGED_DIR,
    build_dir: pathlib.Path = DEFAULT_BUILD_DIR,
    revision: str | None = None,
) -> dict[str, object]:
    """Emit the ONE installable dictionary ZIP from the merged corpus.

    A missing merged corpus is not an error at scaffold time: the pipeline emits
    a valid, empty-corpus ZIP so the stage seam, packaging, reproducibility, and
    schema validation are all exercisable before any source logic exists.
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
        index=build_index(revision),
        banks=build_banks(entries),
        tag_bank=build_tag_bank(source_labels),
        styles_css=STYLES_CSS,
    )
    archive = build_zip(members)

    build_dir.mkdir(parents=True, exist_ok=True)
    zip_path = build_dir / zip_name()
    zip_path.write_bytes(archive)
    return {
        "zipPath": str(zip_path),
        "revision": revision,
        "entries": len(entries),
        "members": sorted(members),
        "byteCount": len(archive),
        "sha256": hashlib.sha256(archive).hexdigest(),
        "contentHash": content_hash(corpus),
    }


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def run_validate(
    *, build_dir: pathlib.Path = DEFAULT_BUILD_DIR
) -> tuple[bool, list[str]]:
    """Validate the built ZIP against the pinned official Yomitan schemas."""
    zip_path = build_dir / zip_name()
    if not zip_path.is_file():
        return False, [f"no built artifact to validate: {zip_path}"]
    failures = validate_zip(zip_path)
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
    "MERGED_CORPUS_NAME",
    "zip_name",
    "run_extract",
    "run_merge",
    "run_build",
    "run_validate",
    "point_to_json",
    "point_from_json",
    "entry_to_json",
    "entry_from_json",
]
