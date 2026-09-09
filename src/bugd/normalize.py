"""Headword normalization shared by the matcher and the merge stage.

Every rule here was measured against the real 4,972-point corpus, and each one
folds a *presentation* difference only. Nothing folds a lexical difference:
okurigana, politeness register, kana/kanji spelling and particle attachment stay
distinct, because the grammar sources use them to keep genuinely different points
apart.

Measured behaviour of the separators (`data/extracted/*.json`):

* `/` and `／` — true alternates the producer advertises in one headword;
* `・` — also a true alternate separator, but ambiguous: it appears inside
  bracketed slot annotations (`Verb［た・ている］`) and inside ellipsis
  placeholders (`〜ほど・・・はない`), where splitting manufactures nonsense
  lookup forms. Both spans are masked before splitting;
* `⇒` / `=>` — dialect/derivation arrows.

`lookup_key` is the grouping key; the original written form is always preserved
separately for display, so a stripped key never reaches the card.
"""

from __future__ import annotations

import re
import unicodedata

#: Placeholder tildes. NFKC folds ～ (U+FF5E) onto ~ but leaves the wave dash
#: 〜 (U+301C) untouched, so every variant is listed explicitly.
PLACEHOLDER_TILDES = "〜～~"

#: Sense/branch markers a producer appends to disambiguate homographic entries.
#: Kept out of the grouping key; the source's own record still carries them.
SENSE_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮❶❷❸❹❺❻❼❽❾❿"

#: Ellipsis placeholders standing for "the rest of the clause" (〜ほど・・・はない).
#: These are NOT alternation separators.
ELLIPSES = ("・・・", "···", "……", "…", "...")

_LATIN_RE = re.compile(r"[A-Za-z]")
_BRACKETED_RE = re.compile(r"[（(][^）)]*[）)]|［[^］]*］|\[[^\]]*\]|【[^】]*】")
_SEPARATOR_RE = re.compile(r"\s*(?:/|／|・|⇒|=>|｜)\s*")
_TRIM = "・、。「」『』+＋,，:：;；!！?？ 　\u3000"


def _mask(text: str) -> tuple[str, list[str]]:
    """Replace spans that must survive separator splitting with placeholders."""
    kept: list[str] = []

    def take(fragment: str) -> str:
        kept.append(fragment)
        return f"\x00{len(kept) - 1}\x00"

    for ellipsis in ELLIPSES:
        text = text.replace(ellipsis, take(ellipsis))
    text = _BRACKETED_RE.sub(lambda match: take(match.group(0)), text)
    return text, kept


def _unmask(text: str, kept: list[str]) -> str:
    for index, fragment in enumerate(kept):
        text = text.replace(f"\x00{index}\x00", fragment)
    return text


def split_alternatives(headword: str) -> list[str]:
    """Split one source headword into the distinct lookup forms it advertises."""
    if not isinstance(headword, str):
        raise TypeError("split_alternatives expects a string")
    masked, kept = _mask(headword)
    forms: list[str] = []
    for part in _SEPARATOR_RE.split(masked):
        restored = _unmask(part, kept).strip()
        if restored and restored not in forms:
            forms.append(restored)
    return forms or [headword.strip()]


def lookup_key(form: str) -> str:
    """Normalized grouping key for one lookup form.

    Folds width/compatibility (NFKC), placeholder tildes, producer sense marks,
    bracketed slot annotations, ellipsis placeholders and whitespace. It
    deliberately does not fold okurigana, politeness or spelling.
    """
    if not isinstance(form, str):
        raise TypeError("lookup_key expects a string")
    text = unicodedata.normalize("NFKC", form)
    for ellipsis in ELLIPSES:
        text = text.replace(ellipsis, "")
    text = _BRACKETED_RE.sub("", text)
    text = "".join(character for character in text if character not in SENSE_MARKS)
    for tilde in PLACEHOLDER_TILDES:
        text = text.replace(tilde, "")
    text = re.sub(r"[\s\u3000]+", "", text)
    return text.strip(_TRIM)


def lookup_keys(form: str) -> list[str]:
    """Every grouping key one source headword resolves to, in source order."""
    keys: list[str] = []
    for alternative in split_alternatives(form):
        key = lookup_key(alternative)
        if key and key not in keys:
            keys.append(key)
    return keys


def is_metalinguistic(key: str) -> bool:
    """True when a key is a slot description (`Verb[る]`) rather than a form."""
    return bool(_LATIN_RE.search(key))


def sentence_key(sentence: str) -> str:
    """Identity of a learner-visible example sentence, for duplicate counting."""
    text = unicodedata.normalize("NFKC", sentence)
    return re.sub(r"[\s\u3000]+", "", text)


__all__ = [
    "ELLIPSES",
    "PLACEHOLDER_TILDES",
    "SENSE_MARKS",
    "is_metalinguistic",
    "lookup_key",
    "lookup_keys",
    "sentence_key",
    "split_alternatives",
]
