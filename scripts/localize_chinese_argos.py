#!/usr/bin/env python3
"""Fill missing English-to-Simplified-Chinese translations with local Argos.

The single-string path. `scripts/localize_chinese_argos_batch.py` is the same
work batched; both hold Japanese, links and markup OUT of the model rather than
replacing them with a sentinel (see `bugd.translation_quality.split_protected`),
and both refuse to store a translation that fails the quality gate.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

import argostranslate.package
import argostranslate.translate


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bugd.translation_quality import degradation, split_protected  # noqa: E402

MODEL = ROOT / "work/translation-models/translate-en_zh-1_9.full.argosmodel"
CACHE_PATH = ROOT / "translation-cache.json"
CHUNK_DIR = ROOT / "translation-chunks"

LATIN = re.compile(r"[A-Za-z]")


def install_model() -> None:
    langs = argostranslate.translate.get_installed_languages()
    if any(x.code == "en" for x in langs) and any(x.code == "zh" for x in langs):
        return
    if not MODEL.exists():
        raise SystemExit(f"missing local model: {MODEL}")
    argostranslate.package.install_from_path(str(MODEL))


def _translate_groups(text: str, translator) -> str:
    """Translate one English run in paragraph-sized groups, losing no character."""
    groups: list[str] = []
    buf = ""
    for piece in re.split(r"(\n+)", text):
        if piece == "":
            continue
        if buf and len(buf) + len(piece) > 600:
            groups.append(buf)
            buf = ""
        buf += piece
        if piece.startswith("\n") and buf.strip():
            groups.append(buf)
            buf = ""
    if buf:
        groups.append(buf)
    return "".join(
        translator.translate(group) if LATIN.search(group) else group for group in groups
    )


def translate_text(text: str, translator) -> str:
    """Translate `text`, or return None when the result fails the quality gate."""
    if not isinstance(text, str) or not text.strip() or not LATIN.search(text):
        return text
    out = []
    for translate, piece in split_protected(text):
        # The protected runs never reach the model, so there is no sentinel to
        # mangle and nothing to restore afterwards.
        out.append(_translate_groups(piece, translator) if translate and LATIN.search(piece) else piece)
    result = "".join(out)
    return None if degradation(text, result) else result


def key(source: str, field: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"argos:{source}:{field}:{digest}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", default=["dojg", "imabi", "yokubi"])
    parser.add_argument("--write-chunks", action="store_true")
    args = parser.parse_args()

    install_model()
    langs = argostranslate.translate.get_installed_languages()
    en = next(x for x in langs if x.code == "en")
    zh = next(x for x in langs if x.code == "zh")
    translator = en.get_translation(zh)
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {"entries": {}}
    cache.setdefault("entries", {})

    for source in args.sources:
        path = ROOT / f"data/extracted/{source}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        rejected = collections.Counter()
        for index, point in enumerate(data.get("points", [])):
            provenance = point.setdefault("provenance", {})
            translation = provenance.setdefault("translationZh", {})
            for field in ("meaning", "nuance", "explanation", "structure"):
                value = point.get(field)
                if not isinstance(value, str) or not value.strip() or not LATIN.search(value):
                    continue
                if translation.get(field):
                    continue
                cache_key = key(source, field, value)
                result = cache["entries"].get(cache_key)
                if not result:
                    result = translate_text(value, translator)
                    if result is None:
                        rejected["field"] += 1
                        continue
                    cache["entries"][cache_key] = result
                translation[field] = result
                changed += 1
            examples = {}
            for example in point.get("examples") or []:
                japanese = example.get("japanese")
                english = example.get("english")
                if not isinstance(japanese, str) or not isinstance(english, str) or not english.strip():
                    continue
                cache_key = key(source, f"example:{japanese}", english)
                result = cache["entries"].get(cache_key)
                if not result:
                    result = translate_text(english, translator)
                    if result is None:
                        rejected["example"] += 1
                        continue
                    cache["entries"][cache_key] = result
                examples[japanese] = result
            if examples:
                translation["examples"] = examples
                changed += len(examples)
            if translation:
                provenance["translationZh"] = translation
        path.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"[argos] {source}: changed={changed}")
        if rejected:
            detail = ", ".join(f"{kind}={count}" for kind, count in sorted(rejected.items()))
            print(f"[argos] {source}: rejected={sum(rejected.values())} degraded ({detail})")

    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
