#!/usr/bin/env python3
"""Merge locally prepared Chinese translation chunks into extracted records."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib


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
            previous.update(translation)
            for field, translated in translation.items():
                if field == "examples" or not isinstance(translated, str):
                    continue
                original = point.get(field)
                if isinstance(original, str) and original.strip():
                    entries[cache_key(source, field, original)] = {"translation": translated}
            translated_examples = translation.get("examples")
            if isinstance(translated_examples, dict):
                for example_index, example in enumerate(point.get("examples") or []):
                    if not isinstance(example, dict):
                        continue
                    japanese = example.get("japanese")
                    english = example.get("english")
                    translated = translated_examples.get(japanese) if isinstance(japanese, str) else None
                    if isinstance(english, str) and english.strip() and isinstance(translated, str):
                        entries[cache_key(source, f"example:{example_index}", english)] = {"translation": translated}
            applied += 1
        source_path.write_text(
            json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    args.cache.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[translate] applied {applied} translation records; cache entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
