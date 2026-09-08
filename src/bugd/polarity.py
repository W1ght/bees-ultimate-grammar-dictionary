"""Tail-anchored polarity of a grammar-point surface form.

A polarity flip is the single most dangerous fold in this corpus, because the
flipped pair is *lexically almost identical* and the producers routinely list one
as a declared variant of the other:

    ないことはある   /  ないことはない
    と言えなくもある /  と言えなくもない
    と言ったらある   /  といったらない

Those are opposite grammar points. A naive "does the string contain ない" test
gets them backwards — `ないことはある` contains ない but is affirmative — so
polarity is read from the **tail** after stripping copula/sentence-final
particles.

Bare single-mora tails (`ん`, `ず`, `ぬ`) are deliberately NOT negative markers:
they are ordinary morae in unrelated words (`一旦`→いったん, `を問わず`), and
treating them as negation splits correct folds. Only multi-mora endings that can
only be negation are recognized. Unrecognized tails return `"none"`, which
compares equal to itself — polarity refuses folds it is sure about, and abstains
otherwise.
"""

from __future__ import annotations

import re
import unicodedata

#: Endings that can only be negation in a grammar-point headword.
NEGATIVE_TAILS: tuple[str, ...] = (
    "ありはしない",
    "ざるをえない",
    "ざるを得ない",
    "はしない",
    "ません",
    "ずに",
    "ない",
    "なし",
    "なく",
    "まい",
)

#: Affirmative endings that a negative counterpart is routinely flipped from.
POSITIVE_TAILS: tuple[str, ...] = (
    "できる",
    "ある",
    "あり",
    "する",
    "いる",
)

#: Copula and sentence-final material stripped before reading the tail, so that
#: `ないことはないだ` and `ないことはない` agree.
_TRAILING = re.compile(r"(?:です|でした|だった|だろう|でしょう|だ|よ|ね|な|の)+$")
_PUNCTUATION = "。．.、， 　\u3000"

_KATAKANA_TO_HIRAGANA = {chr(code): chr(code - 0x60) for code in range(0x30A1, 0x30F7)}


def kana_identity(text: str | None) -> str:
    """Hiragana-only skeleton of a form: the reading two spellings share.

    `今更` and `いまさら` are one point spelled two ways. Their *readings* are
    identical, and every source in this corpus populates `reading` on every row,
    so kana identity is measured evidence rather than a guess.
    """
    normalized = unicodedata.normalize("NFKC", text or "")
    folded = "".join(_KATAKANA_TO_HIRAGANA.get(character, character) for character in normalized)
    return "".join(character for character in folded if "\u3041" <= character <= "\u309f")


def polarity(text: str | None) -> str:
    """`"neg"`, `"pos"`, or `"none"` (abstain) for one surface form."""
    trimmed = unicodedata.normalize("NFKC", text or "").strip(_PUNCTUATION)
    trimmed = _TRAILING.sub("", trimmed)
    if not trimmed:
        return "none"
    for tail in NEGATIVE_TAILS:
        if trimmed.endswith(tail):
            return "neg"
    for tail in POSITIVE_TAILS:
        if trimmed.endswith(tail):
            return "pos"
    return "none"


def polarity_agrees(left: str | None, right: str | None) -> bool:
    """True unless two forms are a *known* polarity flip of each other.

    Only an explicit `pos` versus `neg` opposition is a flip. When either side is
    `"none"` the tail was not recognized, and this function abstains (returns
    True) rather than refusing — that is the documented contract of `polarity`.

    Treating `"none"` as disagreement was measured to over-refuse real folds:
    `ずに`/`ないで`, `ている`/`ておる`, and `がっている`/`がる` are each one point,
    and only one side of each pair has a recognizable polarity tail.
    """
    left_polarity, right_polarity = polarity(left), polarity(right)
    return {left_polarity, right_polarity} != {"pos", "neg"}


def is_polarity_flip(left: str | None, right: str | None) -> bool:
    """True when two forms are a known affirmative/negative pair."""
    return not polarity_agrees(left, right)


__all__ = [
    "NEGATIVE_TAILS",
    "POSITIVE_TAILS",
    "is_polarity_flip",
    "kana_identity",
    "polarity",
    "polarity_agrees",
]
