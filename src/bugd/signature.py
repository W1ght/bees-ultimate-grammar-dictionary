"""Attachment signature: one shared category vocabulary across five notations.

Each source writes what a grammar point attaches to in its own house notation::

    dojg               English    "Vnegative", "Adj(i)stem", "Noと"
    donna_toki         compact    "Ｖない＋でもない", "イAい", "ナA"
    edewakaru          verbose    "動詞［ない形］", "名詞［辞書形］"
    nihongo_net        mixed      "V（ナイ形）", "イAい", "ナAで"
    nihongo_no_sensei  compact    "動ない形", "イ形容詞", "ナ形語幹"

Two records can only be compared as the same grammar point if both notations map
into one vocabulary. `signature` projects a source's raw structure text onto a
frozen set of part-of-speech and verb-form labels.

Deliberate limits, measured against the real corpus:

* the projection is **lossy and one-way**. It is a *discriminator* used to keep
  homographs apart, never evidence that two records mean the same thing;
* an unrecognized notation yields the empty signature, which is reported as
  `None` (unknown), never as "attaches to nothing". A `None` signature can never
  authorize a fold — unknown fails closed;
* patterns are applied longest-first within each family and consumed from the
  residual text, so `動ない形` yields `{Verb, V-neg}` rather than double-counting.
"""

from __future__ import annotations

import re
import unicodedata

#: Part-of-speech the point attaches to.
PART_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Noun", r"名詞|\bNoun\b|\bN\b(?![a-z])|Ｎ|N[（(＋+]"),
    ("Verb", r"動詞|\bVerb\b|\bV\b(?![a-z])|Ｖ|V[（(＋+]|動[ますないてたるれ]"),
    ("Adj-i", r"イ[ＡA]|い形容詞|イ形容詞|イ形|\bAdj\(i\)|い-?Adjective|\[い\]\s*Adj"),
    ("Adj-na", r"ナ[ＡA]|な形容詞|ナ形容詞|ナ形|\bAdj\(na\)|な-?Adjective|\[な\]\s*Adj"),
    ("Phrase", r"文\b|文[＋+]|普通形の文|\bSentence\b|\bPhrase\b|\bClause\b"),
)

#: Inflected form the point attaches to.
FORM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("V-dict", r"辞書形|辞形|\(辞\)|\bVdictionary\b|Vる\b|\bDictionary form\b"),
    ("V-neg", r"ない形|ナイ形|否定形|\bVnegative\b|Vない|Vneg"),
    ("V-ta", r"た形|タ形|過去形|\bVpast\b|Vた|Vinformal past"),
    ("V-te", r"て形|テ形|\bVte\b|Vて"),
    ("V-stem", r"ます形|マス形|連用形|\bVmasu\b|Vます|Vstem"),
    ("V-vol", r"意向形|意志形|\bVvolitional\b|Vよう|Voo"),
    ("V-ba", r"ば形|バ形|条件形|\bVconditional\b|Vば"),
    ("V-caus", r"使役形|Vcausative|させる形"),
    ("V-pass", r"受身形|受動形|Vpassive|られる形"),
    ("V-pot", r"可能形|Vpotential"),
    ("V-plain", r"普通形|普通体|\bVinformal\b|\(普\)"),
    ("V-imp", r"命令形|Vimperative"),
)

_ALL_PATTERNS = PART_PATTERNS + FORM_PATTERNS


def signature(structure: str | None) -> frozenset[str] | None:
    """Project one source's structure notation onto the shared vocabulary.

    Returns `None` when the text is absent or matches no known notation, so the
    caller can distinguish *unknown* from *empty*.
    """
    if not structure or not isinstance(structure, str):
        return None
    residual = unicodedata.normalize("NFKC", structure)
    found: set[str] = set()
    for label, pattern in _ALL_PATTERNS:
        if re.search(pattern, residual):
            found.add(label)
            residual = re.sub(pattern, "", residual)
    return frozenset(found) or None


def signature_label(value: frozenset[str] | None) -> str | None:
    """Stable, sorted, JSON-serializable rendering of a signature."""
    if value is None:
        return None
    return "+".join(sorted(value))


__all__ = [
    "FORM_PATTERNS",
    "PART_PATTERNS",
    "signature",
    "signature_label",
]
