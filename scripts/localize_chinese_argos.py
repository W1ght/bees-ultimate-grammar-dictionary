#!/usr/bin/env python3
"""Fill missing English-to-Simplified-Chinese translations with local Argos."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import argostranslate.package
import argostranslate.translate


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "work/translation-models/translate-en_zh-1_9.full.argosmodel"
CACHE_PATH = ROOT / "translation-cache.json"
CHUNK_DIR = ROOT / "translation-chunks"

PROTECTED = re.compile(
    r"<[^>\n]*>|https?://\S+|`[^`\n]*`|\{\{[^}\n]*\}\}|\{[^}\n]*\}|"
    r"\[[^\]\n]{1,240}\]\([^\)\n]*\)"
)
JAPANESE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff01-\uffef。、，．：；！？「」『』（）［］【】〔〕〈〉《》…〜～※]+"
)
LATIN = re.compile(r"[A-Za-z]")


def install_model() -> None:
    langs = argostranslate.translate.get_installed_languages()
    if any(x.code == "en" for x in langs) and any(x.code == "zh" for x in langs):
        return
    if not MODEL.exists():
        raise SystemExit(f"missing local model: {MODEL}")
    argostranslate.package.install_from_path(str(MODEL))


def protect(text: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def save(match: re.Match[str]) -> str:
        token = f"ZXQJPN{len(saved):05d}Q"
        saved.append(match.group(0))
        return token

    text = PROTECTED.sub(save, text)
    text = JAPANESE.sub(save, text)
    return text, saved


def restore(text: str, saved: list[str]) -> str:
    for i, value in enumerate(saved):
        text = text.replace(f"ZXQJPN{i:05d}Q", value)
    return text


def translate_text(text: str, translator) -> str:
    if not isinstance(text, str) or not text.strip() or not LATIN.search(text):
        return text
    protected, saved = protect(text)
    # Translate paragraph/line groups independently so Markdown structure and
    # long IMABI pages remain stable and the local model gets manageable input.
    pieces = re.split(r"(\n+)", protected)
    groups: list[str] = []
    buf = ""
    for piece in pieces:
        if piece == "":
            continue
        if buf and len(buf) + len(piece) > 1200:
            groups.append(buf)
            buf = ""
        buf += piece
        if piece.startswith("\n") and buf.strip():
            groups.append(buf)
            buf = ""
    if buf:
        groups.append(buf)
    out = []
    for group in groups:
        if LATIN.search(group):
            out.append(translator.translate(group))
        else:
            out.append(group)
    return restore("".join(out), saved)


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
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {"entries": {}}
    cache.setdefault("entries", {})

    for source in args.sources:
        path = ROOT / f"data/extracted/{source}.json"
        data = json.loads(path.read_text())
        changed = 0
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
                    cache["entries"][cache_key] = result
                examples[japanese] = result
            if examples:
                translation["examples"] = examples
                changed += len(examples)
            if translation:
                provenance["translationZh"] = translation
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"[argos] {source}: changed={changed}")

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
