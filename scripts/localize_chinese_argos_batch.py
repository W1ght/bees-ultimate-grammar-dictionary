#!/usr/bin/env python3
"""Fast offline Argos translation for the remaining English-only records."""

from __future__ import annotations

import hashlib
import json
import re
import argparse
from pathlib import Path

import argostranslate.package
import argostranslate.translate
from argostranslate import settings

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "work/translation-models/translate-en_zh-1_9.full.argosmodel"
CACHE = ROOT / "translation-cache.json"
PROTECTED = re.compile(r"<[^>\n]*>|https?://\S+|`[^`\n]*`|\{\{[^}\n]*\}\}|\{[^}\n]*\}|\[[^\]\n]{1,240}\]\([^\)\n]*\)")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff01-\uffef。、，．：；！？「」『』（）［］【】〔〕〈〉《》…〜～※]+")
LATIN = re.compile(r"[A-Za-z]")


def ensure_model():
    settings.inter_threads = 1
    settings.intra_threads = 2
    langs = argostranslate.translate.get_installed_languages()
    if not any(x.code == "en" for x in langs):
        argostranslate.package.install_from_path(str(MODEL))
    langs = argostranslate.translate.get_installed_languages()
    en = next(x for x in langs if x.code == "en")
    zh = next(x for x in langs if x.code == "zh")
    translator = en.get_translation(zh).underlying
    # PackageTranslation lazily constructs the CTranslate2 object.
    translator.translate("warm up")
    return translator


def protect(text: str):
    saved = []

    def save(m):
        token = f"ZXQJPN{len(saved):05d}Q"
        saved.append(m.group(0))
        return token

    return JAPANESE.sub(save, PROTECTED.sub(save, text)), saved


def restore(text: str, saved):
    for i, value in enumerate(saved):
        text = text.replace(f"ZXQJPN{i:05d}Q", value)
    return text


def split_text(text: str):
    """Return manageable pieces while retaining every newline exactly."""
    pieces = []
    buf = ""
    for part in re.split(r"(\n+)", text):
        if not part:
            continue
        while len(part) > 180:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(part[:360])
            part = part[360:]
        if buf and len(buf) + len(part) > 180:
            pieces.append(buf)
            buf = ""
        buf += part
        if part.startswith("\n"):
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces or [text]


def translate_batch(translator, texts):
    tokenized = [translator.pkg.tokenizer.encode(x) for x in texts]
    results = translator.translator.translate_batch(
        tokenized,
        replace_unknowns=True,
        max_batch_size=2048,
        batch_type="tokens",
        beam_size=1,
        num_hypotheses=1,
        return_scores=False,
    )
    return [translator.pkg.tokenizer.decode(x.hypotheses[0]) for x in results]


def translate_jobs(translator, jobs, cache):
    pending = []
    for job in jobs:
        cached = cache.get(job["cache_key"])
        if cached:
            job["result"] = cached
            continue
        protected, saved = protect(job["text"])
        job["saved"] = saved
        job["pieces"] = split_text(protected)
        job["result"] = None
        pending.extend((job, i, piece) for i, piece in enumerate(job["pieces"]) if LATIN.search(piece))
        for i, piece in enumerate(job["pieces"]):
            if not LATIN.search(piece):
                job.setdefault("translated", {})[i] = piece
    for start in range(0, len(pending), 128):
        batch = pending[start : start + 128]
        outputs = translate_batch(translator, [x[2] for x in batch])
        for (job, i, _), output in zip(batch, outputs):
            job.setdefault("translated", {})[i] = output
        if start and start % 320 == 0:
            print(f"[argos] translated pieces {start}/{len(pending)}", flush=True)
    for job in jobs:
        if job["result"] is None:
            joined = "".join(job["translated"][i] for i in range(len(job["pieces"])))
            job["result"] = restore(joined, job["saved"])
            cache[job["cache_key"]] = job["result"]


def ckey(source, field, text):
    return f"argos:{source}:{field}:{hashlib.sha256(text.encode()).hexdigest()}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", default=["dojg", "imabi", "yokubi"])
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--chunk-output")
    args = parser.parse_args()
    translator = ensure_model()
    cache_data = json.loads(CACHE.read_text()) if CACHE.exists() else {"entries": {}}
    cache = cache_data.setdefault("entries", {})
    for source in args.sources:
        path = ROOT / f"data/extracted/{source}.json"
        data = json.loads(path.read_text())
        jobs = []
        for index, point in enumerate(data["points"]):
            if index < args.start or (args.end is not None and index >= args.end):
                continue
            translation = point.setdefault("provenance", {}).setdefault("translationZh", {})
            for field in ("meaning", "nuance", "explanation", "structure"):
                text = point.get(field)
                if isinstance(text, str) and LATIN.search(text) and not translation.get(field):
                    jobs.append({"cache_key": ckey(source, field, text), "text": text, "kind": "field", "index": index, "field": field})
            existing = translation.setdefault("examples", {})
            for ex in point.get("examples") or []:
                japanese, english = ex.get("japanese"), ex.get("english")
                if isinstance(japanese, str) and isinstance(english, str) and english.strip() and not existing.get(japanese):
                    jobs.append({"cache_key": ckey(source, f"example:{japanese}", english), "text": english, "kind": "example", "index": index, "japanese": japanese})
        print(f"[argos] {source}: jobs={len(jobs)}", flush=True)
        translate_jobs(translator, jobs, cache)
        changed = 0
        for job in jobs:
            point = data["points"][job["index"]]
            translation = point["provenance"]["translationZh"]
            if job["kind"] == "field":
                translation[job["field"]] = job["result"]
            else:
                translation.setdefault("examples", {})[job["japanese"]] = job["result"]
            changed += 1
        if args.chunk_output:
            selected = [
                {"index": i, "translationZh": data["points"][i].get("provenance", {}).get("translationZh", {})}
                for i in range(args.start, min(args.end or len(data["points"]), len(data["points"])))
            ]
            Path(args.chunk_output).write_text(json.dumps(selected, ensure_ascii=False, separators=(",", ":")) + "\n")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        if not args.chunk_output:
            CACHE.write_text(json.dumps(cache_data, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"[argos] {source}: applied={changed}", flush=True)


if __name__ == "__main__":
    main()
