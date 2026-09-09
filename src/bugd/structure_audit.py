"""Content sanity audit: a formation line that spells a corrupted headword.

UGD-11c-C fixed 100 cards whose `structure`/接続 field stated a formation rule the
card's OWN examples contradict. The single most mechanical sub-signature was a
formation line that spells the grammar point's headword with a one-kana slip that
appears NOWHERE else on the card — e.g. the point 「にほかならない」 whose 接続 table
spelled 「にはかならない」 (は for ほ) in all three lines while every example used the
correct 「にほかならない」. A learner reading the compact card is handed a
misspelling of the pattern's own name.

This module is that cross-check, expressed as a *property*, not a string list:

    a structure field contains a kana run that is
      * the same length as the point's kana headword,
      * different from it in exactly ONE non-final position, and
      * absent from every other field of the same card (examples, meaning,
        explanation, notes) — while the correct headword IS attested there.

The non-final constraint is deliberate: Japanese inflection differs from the
citation form precisely at the final okurigana/particle cell (にわたる/にわたり,
ことがある/こともある), so a final-position difference is almost always a legitimate
paradigm cell the point is teaching, not a typo. An INTERNAL one-kana difference
that the card never uses anywhere else is the corruption signature.

The audit is ADVISORY, not a build gate. Japanese morphology is dense enough that
edit-distance-1 cannot perfectly separate a typo from an intentional alternant, so
turning this into a fail-closed gate would either miss real slips or reject
correct paradigm variation. It runs over the extracted points, reports its
suspects deterministically, and is used by the regression suite to assert two
things: the corrections removed the corruption signature from the fixed cards, and
the detector still fires on a corrupted input (so it can't silently rot into a
no-op). `scripts/audit_structure_forms.py` prints the current suspects for review.
"""

from __future__ import annotations

import re

from .model import GrammarPoint

#: Grammar-point headwords this audit reasons about: kana-only morphemes long
#: enough that a single-kana coincidence is unlikely (4+ kana).
_KANA_HEADWORD = re.compile(r"^[ぁ-んァ-ヶ]{4,}$")
_KANA_RUN = "[ぁ-んァ-ヶ]"


def _one_internal_substitution(candidate: str, headword: str) -> int | None:
    """Return the differing index if `candidate` is `headword` with exactly one
    non-final kana substituted, else None. Both must be the same length."""
    if len(candidate) != len(headword) or candidate == headword:
        return None
    positions = [i for i, (a, b) in enumerate(zip(candidate, headword)) if a != b]
    if len(positions) != 1:
        return None
    position = positions[0]
    if position == len(headword) - 1:  # final-cell difference == inflection, not a typo
        return None
    return position


def _card_body_excluding_structure(point: GrammarPoint) -> str:
    """Every place on the card the correct form could legitimately appear, except
    the structure field being audited."""
    parts = [point.meaning or "", point.explanation or "", point.notes or ""]
    for example in point.examples:
        parts.append(example.japanese)
        parts.append(example.english or "")
    return "\n".join(parts)


def audit_point(point: GrammarPoint) -> list[dict[str, object]]:
    """Return suspect corrupted-headword formation forms for one point."""
    headword = point.expression
    structure = point.structure or ""
    if not structure or not _KANA_HEADWORD.match(headword):
        return []
    body = _card_body_excluding_structure(point)
    # The correct headword must be attested elsewhere on the card, so a divergent
    # spelling in the formation line is a slip rather than the point's real name.
    if headword not in body:
        return []
    width = len(headword)
    runs = set(re.findall(rf"{_KANA_RUN}{{{width}}}", structure))
    suspects: list[dict[str, object]] = []
    for run in sorted(runs):
        if run == headword or run in body:
            continue
        position = _one_internal_substitution(run, headword)
        if position is None:
            continue
        suspects.append(
            {
                "source": point.source,
                "source_id": point.source_id,
                "headword": headword,
                "structure_form": run,
                "diff_index": position,
            }
        )
    return suspects


def audit_points(points: list[GrammarPoint]) -> list[dict[str, object]]:
    """Run the audit over a list of points, flattening all suspects."""
    suspects: list[dict[str, object]] = []
    for point in points:
        suspects.extend(audit_point(point))
    return suspects


__all__ = ["audit_point", "audit_points"]
