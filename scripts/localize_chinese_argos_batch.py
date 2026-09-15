#!/usr/bin/env python3
"""Fast offline Argos translation for the remaining English-only records.

Japanese, links and markup are held OUT of the model instead of being replaced
with a sentinel and restored afterwards -- see
`bugd.translation_quality.split_protected` for why a sentinel cannot survive
subword NMT decoding and what v2026.09.14.4 shipped when it did not. Every
finished translation is then checked against the same invariant before it is
stored, so a run that degrades leaves the field untranslated rather than
publishing debris.
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
from argostranslate import settings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bugd.translation_quality import degradation, split_protected  # noqa: E402

MODEL = ROOT / "work/translation-models/translate-en_zh-1_9.full.argosmodel"
CACHE = ROOT / "translation-cache.json"
LATIN = re.compile(r"[A-Za-z]")

#: Characters of English handed to the model at once. Decoding an over-long
#: segment is what collapsed into `完全; ` x44 and `重音` x200; the split is made
#: at a sentence or line boundary so no segment starts mid-clause.
_MAX_SEGMENT = 600
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n+")


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


def split_text(text: str) -> list[str]:
    """Cut one translatable run into model-sized pieces, keeping every character.

    Splits only at a sentence end or a line break. The previous version sliced
    every 360 characters regardless of where that landed, which handed the model
    half-sentences and is the other half of why it looped. A single sentence
    longer than the budget is still passed whole: truncating it would lose text,
    and the quality gate will catch the result if the model cannot cope.
    """
    if len(text) <= _MAX_SEGMENT:
        return [text] if text else []
    # Cut only at boundaries, and only between them, so the pieces are
    # contiguous slices whose concatenation is the original string.
    boundaries = [match.end() for match in _SENTENCE_END.finditer(text)]
    boundaries.append(len(text))
    pieces: list[str] = []
    start = 0
    previous = 0
    for boundary in boundaries:
        if boundary - start > _MAX_SEGMENT and previous > start:
            pieces.append(text[start:previous])
            start = previous
        previous = boundary
    if start < len(text):
        pieces.append(text[start:])
    return [piece for piece in pieces if piece]


def translate_batch(translator, texts):
    tokenized = [translator.pkg.tokenizer.encode(x) for x in texts]
    results = translator.translator.translate_batch(
        tokenized,
        replace_unknowns=True,
        max_batch_size=2048,
        batch_type="tokens",
        # Greedy decoding (beam_size=1) is what fell into repetition loops on
        # long input; a beam plus a mild repetition penalty does not, and the
        # cost is wall-clock on a run that is done once.
        beam_size=4,
        repetition_penalty=1.1,
        num_hypotheses=1,
        return_scores=False,
    )
    return [translator.pkg.tokenizer.decode(x.hypotheses[0]) for x in results]


def translate_jobs(translator, jobs, cache, rejected):
    pending = []
    for job in jobs:
        cached = cache.get(job["cache_key"])
        if cached:
            job["result"] = cached
            continue
        # Only the translatable runs are ever sent to the model; the protected
        # runs are carried through untouched and re-joined in place.
        job["parts"] = [
            (translate, piece) for translate, piece in split_protected(job["text"])
        ]
        job["pieces"] = []
        for part_index, (translate, piece) in enumerate(job["parts"]):
            if not translate or not LATIN.search(piece):
                continue
            for segment in split_text(piece):
                job["pieces"].append((part_index, segment))
        job["result"] = None
        pending.extend((job, i, segment) for i, (_, segment) in enumerate(job["pieces"]))
    for start in range(0, len(pending), 128):
        batch = pending[start : start + 128]
        outputs = translate_batch(translator, [x[2] for x in batch])
        for (job, i, _), output in zip(batch, outputs):
            job.setdefault("translated", {})[i] = output
        if start and start % 320 == 0:
            print(f"[argos] translated pieces {start}/{len(pending)}", flush=True)
    for job in jobs:
        if job["result"] is not None:
            continue
        rendered: dict[int, list[str]] = collections.defaultdict(list)
        for i, (part_index, _) in enumerate(job["pieces"]):
            rendered[part_index].append(job.get("translated", {}).get(i, ""))
        out = []
        for part_index, (translate, piece) in enumerate(job["parts"]):
            if part_index in rendered:
                out.append("".join(rendered[part_index]))
            else:
                out.append(piece)
        result = "".join(out)
        reason = degradation(job["text"], result)
        if reason:
            # Storing it would serve it to the next build as if it had been
            # verified. Leave the field untranslated and say why.
            rejected[reason] += 1
            job["result"] = None
            continue
        job["result"] = result
        cache[job["cache_key"]] = result


def ckey(source, field, text):
    return f"argos:{source}:{field}:{hashlib.sha256(text.encode()).hexdigest()}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", default=["dojg", "imabi", "yokubi"])
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--chunk-output")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    translator = ensure_model()
    cache_data = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {"entries": {}}
    cache = cache_data.setdefault("entries", {})
    for source in args.sources:
        path = ROOT / f"data/extracted/{source}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = []
        for index, point in enumerate(data["points"]):
            if index < args.start or (args.end is not None and index >= args.end):
                continue
            translation = point.setdefault("provenance", {}).setdefault("translationZh", {})
            for field in ("meaning", "nuance", "explanation", "structure"):
                text = point.get(field)
                if isinstance(text, str) and LATIN.search(text) and (args.overwrite or not translation.get(field)):
                    jobs.append({"cache_key": ckey(source, field, text), "text": text, "kind": "field", "index": index, "field": field})
            existing = translation.setdefault("examples", {})
            for ex in point.get("examples") or []:
                japanese, english = ex.get("japanese"), ex.get("english")
                if isinstance(japanese, str) and isinstance(english, str) and english.strip() and (args.overwrite or not existing.get(japanese)):
                    jobs.append({"cache_key": ckey(source, f"example:{japanese}", english), "text": english, "kind": "example", "index": index, "japanese": japanese})
        print(f"[argos] {source}: jobs={len(jobs)}", flush=True)
        rejected: collections.Counter[str] = collections.Counter()
        translate_jobs(translator, jobs, cache, rejected)
        changed = 0
        for job in jobs:
            if job["result"] is None:
                continue
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
            Path(args.chunk_output).write_text(
                json.dumps(selected, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        else:
            path.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        if not args.chunk_output:
            CACHE.write_text(
                json.dumps(cache_data, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        print(f"[argos] {source}: applied={changed}", flush=True)
        if rejected:
            detail = ", ".join(f"{reason}={count}" for reason, count in sorted(rejected.items()))
            print(f"[argos] {source}: rejected={sum(rejected.values())} ({detail})", flush=True)


if __name__ == "__main__":
    main()
