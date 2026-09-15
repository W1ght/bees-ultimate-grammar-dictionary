#!/usr/bin/env python3
"""Drop the Chinese translations that v2026.09.14.4 shipped broken.

`scripts/apply_translation_chunks.py` now refuses a degraded translation at
ingest, but the extracted artifacts and the translation cache already committed
to this repository were written before that gate existed: they carry the Argos
run's placeholder debris (`ZQQJPN00014`, `齐·杰普恩00092Q`) and its beam-1
repetition loops (`重音` x200), and `data/sources/` does not hold the locked
publisher bytes those artifacts were extracted from, so they cannot simply be
re-extracted.

This pass removes only the values that fail `bugd.translation_quality`. The
source's own English is never touched, so a card that loses its Chinese prose
falls back to the text the publisher wrote. Reports what it removed, by source
and by reason, and rewrites nothing when there is nothing to remove.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.translation_quality import degradation, has_placeholder_debris  # noqa: E402


def _clean_point(point: dict, counts: collections.Counter) -> bool:
    provenance = point.get("provenance")
    if not isinstance(provenance, dict):
        return False
    translations = provenance.get("translationZh")
    if not isinstance(translations, dict):
        return False
    changed = False
    for field in [key for key in translations if key != "examples"]:
        value = translations[field]
        if not isinstance(value, str):
            continue
        original = point.get(field)
        reason = degradation(original if isinstance(original, str) else "", value)
        if reason:
            counts[reason] += 1
            del translations[field]
            changed = True
    examples = translations.get("examples")
    if isinstance(examples, dict):
        english = {
            example.get("japanese"): example.get("english")
            for example in point.get("examples") or []
            if isinstance(example, dict)
        }
        for japanese in list(examples):
            value = examples[japanese]
            if not isinstance(value, str):
                continue
            source = english.get(japanese)
            reason = degradation(source if isinstance(source, str) else "", value)
            if reason:
                counts[f"example:{reason}"] += 1
                del examples[japanese]
                changed = True
        if not examples:
            del translations["examples"]
            changed = True
    if not translations:
        del provenance["translationZh"]
        changed = True
    return changed


def clean_extracted(path: pathlib.Path, *, dry_run: bool) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    payload = json.loads(path.read_text(encoding="utf-8"))
    points = payload.get("points")
    if not isinstance(points, list):
        raise SystemExit(f"malformed extracted artifact: {path}")
    changed = False
    for point in points:
        if isinstance(point, dict) and _clean_point(point, counts):
            changed = True
    if changed and not dry_run:
        payload.setdefault("stats", {})["translationQuarantine"] = dict(sorted(counts.items()))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return counts


def clean_cache(path: pathlib.Path, *, dry_run: bool) -> int:
    """Drop cache entries carrying sentinel debris.

    The cache is keyed by a digest of the source text, so the source is not
    recoverable here and only the source-free check can run. That is enough: a
    cached value kept back would otherwise be re-served to the next build as if
    it had been verified.
    """
    if not path.is_file():
        return 0
    cache = json.loads(path.read_text(encoding="utf-8"))
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        raise SystemExit(f"malformed translation cache: {path}")
    doomed = [
        key
        for key, value in entries.items()
        if isinstance(value, dict) and has_placeholder_debris(value.get("translation"))
    ]
    if doomed and not dry_run:
        for key in doomed:
            del entries[key]
        path.write_text(
            json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return len(doomed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted-dir", type=pathlib.Path, default=pathlib.Path("data/extracted"))
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("translation-cache.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    total = 0
    for path in sorted(args.extracted_dir.glob("*.json")):
        counts = clean_extracted(path, dry_run=args.dry_run)
        if counts:
            detail = ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items()))
            print(f"[quarantine] {path.stem}: removed {sum(counts.values())} ({detail})")
            total += sum(counts.values())
    removed = clean_cache(args.cache, dry_run=args.dry_run)
    print(f"[quarantine] removed {total} degraded translations, {removed} cache entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
