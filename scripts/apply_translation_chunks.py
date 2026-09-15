#!/usr/bin/env python3
"""Merge locally prepared Chinese translation chunks into extracted records.

Ingest is the gate. A chunk carries whatever the translator produced, and the
Argos run that produced v2026.09.14.4 produced placeholder debris and repetition
loops for most of IMABI, Yokubi and DoJG. Every value is checked against
`bugd.translation_quality` before it is written into an extracted record or into
the cache, and a rejected value is counted and reported by reason rather than
stored -- so a bad translation cannot reach the build by being cached first.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.translation_quality import degradation  # noqa: E402


def cache_key(source: str, field: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{source}:{field}:{digest}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extracted-dir", type=pathlib.Path, default=pathlib.Path("data/extracted"))
    parser.add_argument("--chunks-dir", type=pathlib.Path, default=pathlib.Path("translation-chunks"))
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("translation-cache.json"))
    args = parser.parse_args()

    if args.cache.is_file():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
    else:
        cache = {"version": 1, "entries": {}}
    entries = cache.setdefault("entries", {})
    if not isinstance(entries, dict):
        raise SystemExit(f"malformed translation cache: {args.cache}")
    applied = 0
    rejected: collections.Counter[str] = collections.Counter()
    for chunk_path in sorted(args.chunks_dir.glob("*.json")):
        parts = chunk_path.stem.split("-")
        if len(parts) != 3:
            raise SystemExit(f"invalid chunk filename: {chunk_path.name}")
        source = parts[0]
        source_path = args.extracted_dir / f"{source}.json"
        payload = json.loads(chunk_path.read_text(encoding="utf-8"))
        records = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not isinstance(records.get("points"), list):
            raise SystemExit(f"malformed translation chunk or extracted file: {chunk_path}")
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                raise SystemExit(f"malformed translation item: {chunk_path}")
            index = item["index"]
            if index < 0 or index >= len(records["points"]):
                raise SystemExit(f"translation index out of range: {chunk_path}: {index}")
            translation = item.get("translationZh")
            if not isinstance(translation, dict):
                raise SystemExit(f"missing translationZh: {chunk_path}: {index}")
            point = records["points"][index]
            provenance = point.setdefault("provenance", {})
            if not isinstance(provenance, dict):
                raise SystemExit(f"malformed provenance: {source}[{index}]")
            previous = provenance.setdefault("translationZh", {})
            if not isinstance(previous, dict):
                raise SystemExit(f"malformed existing translation: {source}[{index}]")
            example_english = {
                example.get("japanese"): example.get("english")
                for example in point.get("examples") or []
                if isinstance(example, dict)
            }
            accepted: dict[str, object] = {}
            for field, translated in translation.items():
                if field == "examples":
                    continue
                if not isinstance(translated, str):
                    accepted[field] = translated
                    continue
                original = point.get(field)
                original = original if isinstance(original, str) else ""
                reason = degradation(original, translated)
                if reason:
                    rejected[reason] += 1
                    continue
                accepted[field] = translated
                if original.strip():
                    entries[cache_key(source, field, original)] = {"translation": translated}
            translated_examples = translation.get("examples")
            if isinstance(translated_examples, dict):
                kept_examples = previous.get("examples")
                if not isinstance(kept_examples, dict):
                    kept_examples = {}
                for japanese, translated in translated_examples.items():
                    english = example_english.get(japanese)
                    if isinstance(translated, str):
                        reason = degradation(english if isinstance(english, str) else "", translated)
                        if reason:
                            rejected[reason] += 1
                            continue
                    kept_examples[japanese] = translated
                accepted["examples"] = kept_examples
                for example_index, example in enumerate(point.get("examples") or []):
                    if not isinstance(example, dict):
                        continue
                    japanese = example.get("japanese")
                    english = example.get("english")
                    translated = kept_examples.get(japanese) if isinstance(japanese, str) else None
                    if isinstance(english, str) and english.strip() and isinstance(translated, str):
                        entries[cache_key(source, f"example:{example_index}", english)] = {"translation": translated}
            previous.update(accepted)
            applied += 1
        source_path.write_text(
            json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    args.cache.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"[translate] applied {applied} translation records; cache entries={len(entries)}")
    if rejected:
        total = sum(rejected.values())
        detail = ", ".join(f"{reason}={count}" for reason, count in sorted(rejected.items()))
        print(f"[translate] rejected {total} degraded translations ({detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
