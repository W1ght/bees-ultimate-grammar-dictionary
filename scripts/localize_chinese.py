#!/usr/bin/env python3
"""Apply the fork's language policy to extracted source artifacts.

The publisher bytes stay locked and untouched.  English-only sources keep their
English fields and receive a separate Chinese translation under
``provenance.translationZh``.  Sources containing Japanese (including Japanese /
English editions) lose only their English prose and example translations.

Translations are generated through the OpenAI Chat Completions API and cached by
source/field/text digest.  The cache is an Actions cache artifact, not dictionary
content, so rerunning an update only translates new or changed strings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.translation_quality import degradation  # noqa: E402

ENGLISH_ONLY = frozenset({"dojg", "bunpro", "imabi", "yokubi"})
TEXT_FIELDS = ("meaning", "structure", "nuance", "explanation", "notes")
_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN = re.compile(r"[A-Za-z]")
_CACHE_VERSION = 1


class TranslationError(RuntimeError):
    pass


def _latin_dominant(text: str) -> bool:
    latin = len(_LATIN.findall(text))
    japanese = len(_JAPANESE.findall(text))
    return latin >= 8 and latin > 2 * japanese


def strip_english(text: object) -> object:
    """Remove English paragraphs/lines while retaining Japanese content.

    A line dominated by Latin text is translation prose even when it quotes the
    Japanese pattern, so it is removed as a whole. Short mixed formula labels
    remain intact.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    kept: list[str] = []
    for line in text.splitlines():
        if line.strip() and _latin_dominant(line):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return result or None


def _cache_key(source: str, field: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{source}:{field}:{digest}"


def load_cache(path: pathlib.Path) -> dict[str, object]:
    if not path.is_file():
        return {"version": _CACHE_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TranslationError(f"cannot read translation cache {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
        raise TranslationError(f"unsupported translation cache: {path}")
    if not isinstance(payload.get("entries"), dict):
        raise TranslationError(f"translation cache has no entries object: {path}")
    return payload


def save_cache(path: pathlib.Path, cache: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _response_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationError("translation API returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise TranslationError("translation API returned empty content")
    return content.strip()


def translate_batch(items: list[tuple[str, str]], *, api_key: str, model: str) -> dict[str, str]:
    numbered = [{"id": key, "text": text} for key, text in items]
    prompt = (
        "Translate each English dictionary passage into Simplified Chinese. "
        "Return JSON exactly as {\"translations\":[{\"id\":\"...\",\"translation\":\"...\"}]} . "
        "Keep the same ids and count. Preserve HTML tags, Markdown markers, Japanese text, "
        "grammar placeholders such as 〜 and line breaks. Do not add commentary.\n\n"
        + json.dumps(numbered, ensure_ascii=False)
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are a careful English-to-Simplified-Chinese translator."},
                    {"role": "user", "content": prompt},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "W1ght/bees-ultimate-grammar-dictionary",
        },
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            if error.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2**attempt)
                continue
            raise TranslationError(f"translation API HTTP {error.code}: {body}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 4:
                raise TranslationError(f"translation API request failed: {error}") from error
            time.sleep(2**attempt)
    else:  # pragma: no cover
        raise TranslationError("translation API retry loop ended unexpectedly")

    try:
        decoded = json.loads(_response_text(payload))
    except (ValueError, TypeError) as error:
        raise TranslationError("translation API did not return valid JSON") from error
    translations = decoded.get("translations") if isinstance(decoded, dict) else None
    if not isinstance(translations, list):
        raise TranslationError("translation API JSON has no translations array")
    result: dict[str, str] = {}
    for item in translations:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("translation"), str):
            raise TranslationError("translation API returned a malformed translation item")
        result[item["id"]] = item["translation"].strip()
    expected = {key for key, _ in items}
    if set(result) != expected:
        raise TranslationError("translation API changed the batch ids")
    return result


def translate_texts(
    requests: list[tuple[str, str, str]],
    *,
    cache: dict[str, object],
    api_key: str,
    model: str,
) -> dict[str, str]:
    entries = cache["entries"]
    assert isinstance(entries, dict)
    result: dict[str, str] = {}
    pending: list[tuple[str, str]] = []
    for source, field, text in requests:
        key = _cache_key(source, field, text)
        cached = entries.get(key)
        if isinstance(cached, dict) and isinstance(cached.get("translation"), str):
            result[key] = cached["translation"]
        else:
            pending.append((key, text))
    for offset in range(0, len(pending), 16):
        batch = pending[offset : offset + 16]
        translated = translate_batch(batch, api_key=api_key, model=model)
        for key, value in translated.items():
            entries[key] = {"translation": value}
            result[key] = value
        print(f"[translate] {min(offset + len(batch), len(pending))}/{len(pending)} new strings")
        save_cache(_CURRENT_CACHE_PATH, cache)
    return result


_CURRENT_CACHE_PATH = pathlib.Path("translation-cache.json")


def localize_file(path: pathlib.Path, *, cache: dict[str, object], api_key: str, model: str) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("source")
    points = payload.get("points")
    if not isinstance(source, str) or not isinstance(points, list):
        raise TranslationError(f"malformed extracted artifact: {path}")
    changed = 0
    if source in ENGLISH_ONLY:
        requests: list[tuple[str, str, str]] = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                continue
            for field in TEXT_FIELDS:
                value = point.get(field)
                if isinstance(value, str) and value.strip():
                    requests.append((source, field, value))
            for example_index, example in enumerate(point.get("examples") or []):
                if isinstance(example, dict) and isinstance(example.get("english"), str) and example["english"].strip():
                    requests.append((source, f"example:{example_index}", example["english"]))
        translated = translate_texts(requests, cache=cache, api_key=api_key, model=model)
        for point in points:
            if not isinstance(point, dict):
                continue
            translations: dict[str, object] = {}
            for field in TEXT_FIELDS:
                value = point.get(field)
                if isinstance(value, str) and value.strip():
                    candidate = translated[_cache_key(source, field, value)]
                    # A translation that lost the Japanese it was explaining, or
                    # stopped early, is not published -- the card falls back to
                    # this source's own English. See `bugd.translation_quality`.
                    if not degradation(value, candidate):
                        translations[field] = candidate
            example_translations: dict[str, str] = {}
            for example_index, example in enumerate(point.get("examples") or []):
                if isinstance(example, dict) and isinstance(example.get("english"), str) and example["english"].strip():
                    key = _cache_key(source, f"example:{example_index}", example["english"])
                    japanese = example.get("japanese")
                    candidate = translated[key]
                    if (
                        isinstance(japanese, str)
                        and japanese.strip()
                        and not degradation(example["english"], candidate)
                    ):
                        example_translations[japanese] = candidate
            if any(translations.values()) or example_translations:
                translations["examples"] = example_translations
                provenance = point.setdefault("provenance", {})
                if not isinstance(provenance, dict):
                    provenance = {}
                    point["provenance"] = provenance
                provenance["translationZh"] = translations
                changed += 1
    else:
        for point in points:
            if not isinstance(point, dict):
                continue
            for field in TEXT_FIELDS:
                original = point.get(field)
                cleaned = strip_english(original)
                if cleaned != original:
                    point[field] = cleaned
                    changed += 1
            for example in point.get("examples") or []:
                if isinstance(example, dict) and example.get("english"):
                    example["english"] = None
                    changed += 1
    payload.setdefault("stats", {})["languagePolicy"] = {
        "mode": "english-plus-chinese" if source in ENGLISH_ONLY else "japanese-no-english",
        "changedRecords": changed,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted-dir", type=pathlib.Path, default=pathlib.Path("data/extracted"))
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("translation-cache.json"))
    parser.add_argument("--model", default=os.environ.get("OPENAI_TRANSLATION_MODEL") or "gpt-4o-mini")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="apply existing translations and the Japanese-only policy without calling an API",
    )
    args = parser.parse_args(argv)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not args.offline:
        raise SystemExit("OPENAI_API_KEY is required to create the Chinese side of English-only sources")
    global _CURRENT_CACHE_PATH
    _CURRENT_CACHE_PATH = args.cache
    cache = load_cache(args.cache)
    total = 0
    for path in sorted(args.extracted_dir.glob("*.json")):
        if args.offline and path.stem in ENGLISH_ONLY:
            continue
        total += localize_file(path, cache=cache, api_key=api_key, model=args.model)
    save_cache(args.cache, cache)
    print(f"[translate] localized {total} record/field changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
