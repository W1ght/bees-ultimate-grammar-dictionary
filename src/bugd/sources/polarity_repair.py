"""Repair a headword whose polarity the publisher flipped in the wrong column.

Several of the community term banks ship rows where the ``expression`` column has
been flipped to the affirmative for a construction whose polarity is fixed and
negative. The flip is upstream — it is present in the immutable publisher bytes —
and it is confined to ``expression``: the publisher's own ``reading`` column still
spells the negative. From ``data/sources/edewakaru/term_bank_1.json``::

    expression='なくもある'  reading='なくもない'
    expression='までもある'  reading='までもない'

``〜なくもない`` / ``〜までもない`` are fossilised idioms; the affirmative
``〜なくもある`` is not a Japanese pattern, so an entry keyed on it teaches a form
that does not exist and contradicts its own reading, structure and examples.

Fixing this by hand-editing headwords, or by teaching the cross-source keymap to
fold the affirmative onto the negative, would both be wrong: the first does not
scale past the handful a reviewer happened to see, and the second would defeat
UGD-07's polarity guard, whose whole job is to REFUSE to fold an affirmative onto
its negative (they are opposite grammar points). The guard is correct; the input
it is fed is not. So the repair belongs here, at extraction, and is driven by the
source's own evidence rather than by a judgement about Japanese.

The rule, applied per row and fail-closed
-----------------------------------------
The publisher's ``reading`` is a phonetic transcription of the *same* headword, so
it cannot legitimately carry a different polarity from ``expression``. When it
does, the reading is the trustworthy witness:

1. ``expression`` is affirmative and ends in a positive tail that has a direct
   negative counterpart (``ある`` → ``ない``);
2. the row's own ``reading`` is negative;
3. flipping that tail yields a candidate whose kana skeleton is a subsequence of
   the reading (kanji in the expression expand to their reading), i.e. the
   candidate and the reading are the *same* form differing only in the tail.

Only then is the expression rewritten to the flipped (negative) form. The reading
is authoritative because it transcribes the identical headword; nothing about the
meaning is guessed.

``definitionTags`` are deliberately NOT trusted to *drive* a rewrite. A tag column
routinely lists a genuinely distinct negative pattern beside an affirmative one
(``たことがある`` carries ``たことがない`` as its natural opposite; ``に限りがある``
carries ``に限りがない``). Treating "a negative form appears in the tags" as a flip
would corrupt those correct affirmative headwords. So when the reading agrees with
the affirmative expression while the tags disagree, the evidence is in conflict
and this module ABSTAINS — the pair is left as separate visible entries (which is
exactly what UGD-07's guard already ensures), to be adjudicated by a human rather
than guessed at here.
"""

from __future__ import annotations

import unicodedata
from dataclasses import replace

from ..model import GrammarPoint
from ..polarity import kana_identity, polarity

#: Positive tails that have a single unambiguous negative counterpart reached by
#: flipping the final auxiliary. Both spell the copula/existence verb negated:
#: ``ある`` (exists) → ``ない`` (does not). Only tails whose negation is this exact
#: substitution belong here; anything whose negative is formed differently is left
#: for the reading-subsequence check to reject.
_POSITIVE_TO_NEGATIVE_TAIL: dict[str, str] = {
    "ある": "ない",
    "あり": "ない",
}


def _nfkc(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _is_subsequence(needle: str, haystack: str) -> bool:
    """True when every character of `needle` appears in `haystack`, in order.

    The affirmative expression may be written with kanji (`と言えなくもある`,
    `に越したことはある`) whose readings are only spelled out in the `reading`
    column. Its kana skeleton is therefore a *subsequence* of the reading, never
    a prefix, so equality is too strict and a plain suffix test misses the kanji.
    """
    iterator = iter(haystack)
    return all(character in iterator for character in needle)


def negative_counterpart(expression: str, reading: str | None) -> str | None:
    """The negative form of a polarity-flipped `expression`, or None to abstain.

    Returns a rewritten expression only when the row's own `reading` witnesses
    that the headword is negative and the flip is confined to the tail. Every
    other case — reading missing, reading affirmative, tail not flippable, or the
    flipped candidate not reconciling with the reading — returns None, so the
    caller leaves the record untouched.
    """
    surface = _nfkc(expression).strip()
    if not surface:
        return None
    # The expression must actually be affirmative; a reading that merely looks
    # negative must not drag a genuinely negative headword through the flip.
    if polarity(surface) != "pos":
        return None
    if polarity(reading) != "neg":
        return None

    for positive_tail, negative_tail in _POSITIVE_TO_NEGATIVE_TAIL.items():
        if not surface.endswith(positive_tail):
            continue
        candidate = surface[: -len(positive_tail)] + negative_tail
        candidate_kana = kana_identity(candidate)
        reading_kana = kana_identity(reading)
        if (
            candidate_kana.endswith(negative_tail)
            and reading_kana.endswith(negative_tail)
            and _is_subsequence(candidate_kana, reading_kana)
        ):
            return candidate
        # A flippable tail that does not reconcile with the reading is not a
        # confident flip: abstain rather than rewrite on a partial match.
        return None
    return None


def repair_point(point: GrammarPoint) -> GrammarPoint:
    """Return `point` with a flipped headword corrected, or unchanged.

    On a correction the original affirmative surface is preserved in
    `provenance['upstreamExpression']` and `provenance['polarityRepaired']` is set,
    so the rewrite is auditable and the publisher's exact bytes are never lost.
    The affirmative form is also NOT kept as a lookup variant: it is not a real
    Japanese form, so indexing it would reintroduce the defect for the user.
    """
    corrected = negative_counterpart(point.expression, point.reading)
    if corrected is None or corrected == point.expression:
        return point

    provenance = dict(point.provenance)
    provenance["upstreamExpression"] = point.expression
    provenance["polarityRepaired"] = "reading"

    # Drop the affirmative form if it was carried as a variant; keep any other
    # genuine alternate lookup forms untouched.
    variants = tuple(
        variant for variant in point.variants if _nfkc(variant) != _nfkc(point.expression)
    )
    return replace(point, expression=corrected, variants=variants, provenance=provenance)


__all__ = ["negative_counterpart", "repair_point"]
