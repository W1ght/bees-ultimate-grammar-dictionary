"""Deterministic per-source data corrections applied during extraction.

Some acquired sources carry data-layer defects — a typo, a paste from a
neighbouring entry, or a formula that the source's own examples violate. The
acquired bytes are locked and must never be hand-edited, so a correction cannot
live in the source directory. Instead every correction is a *recorded, replayable
transform* keyed by ``(source, source_id)``, applied to the extracted
``GrammarPoint`` right after the per-row parser produces it. A re-extract from the
untouched locked bytes therefore reproduces the corrected record byte-for-byte,
and any entry with no correction entry passes through identically.

This mirrors the established fix-up-table pattern (a keyed wrong→right map applied
at a single normalisation choke point) rather than rewriting merged output, which
would paper over the defect instead of fixing it at the layer that owns the data.

Scope: the eight Class-A cross-source data defects filed by UGD-11d-A
(card ``t_62bd276f``). Each defect is one source's field contradicting every
other contributing source AND that source's own examples; the verbatim wrong and
right strings below were re-confirmed present in the frozen extracted source JSON
by ``scripts/independent_reverify.py``. Nothing here invents a fix beyond those
eight — the table is closed and every entry cites its finding id.

A correction is one of:

* a ``ReplaceIn`` — replace a verbatim substring inside a named field, expecting
  an exact number of occurrences (a mismatch fails closed rather than silently
  correcting the wrong thing);
* a ``SetExpression`` — re-home a mis-scoped record onto a different headword so
  the merge stage groups it correctly (used only for A7, where nihongo_net's
  ``に至るまで`` record is actually a ``に至る`` record — its structure omits まで
  and none of its examples contain まで).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .model import Example, GrammarPoint


@dataclass(frozen=True)
class ReplaceIn:
    """Replace ``wrong`` with ``right`` inside ``field``, ``count`` times.

    ``count`` is the exact number of occurrences expected in the *whole* field
    (across every example when ``field == "examples"``). If the observed count
    differs the correction raises, so an upstream re-acquisition that changed the
    defect surfaces as a hard failure instead of an under- or over-correction.
    """

    field: str
    wrong: str
    right: str
    count: int
    finding: str

    def apply(self, point: GrammarPoint) -> GrammarPoint:
        if self.field == "examples":
            total = sum(ex.japanese.count(self.wrong) for ex in point.examples)
            self._check(point, total)
            examples = tuple(
                dataclasses.replace(
                    ex, japanese=ex.japanese.replace(self.wrong, self.right)
                )
                if self.wrong in ex.japanese
                else ex
                for ex in point.examples
            )
            return dataclasses.replace(point, examples=examples)

        value = getattr(point, self.field)
        if value is None:
            self._check(point, 0)
            return point
        self._check(point, value.count(self.wrong))
        return dataclasses.replace(
            point, **{self.field: value.replace(self.wrong, self.right)}
        )

    def _check(self, point: GrammarPoint, observed: int) -> None:
        if observed != self.count:
            raise SourceCorrectionError(
                f"correction {self.finding} for {point.source}#{point.source_id} "
                f"expected {self.count} occurrence(s) of {self.wrong!r} in "
                f"{self.field}, found {observed}"
            )


@dataclass(frozen=True)
class SetExpression:
    """Re-home a mis-scoped record onto ``expression`` (record split).

    ``expect`` is the current expression; a mismatch fails closed so the split is
    never applied to a record that has drifted from what was audited.
    """

    expression: str
    expect: str
    finding: str

    def apply(self, point: GrammarPoint) -> GrammarPoint:
        if point.expression != self.expect:
            raise SourceCorrectionError(
                f"correction {self.finding} for {point.source}#{point.source_id} "
                f"expected expression {self.expect!r}, found {point.expression!r}"
            )
        return dataclasses.replace(point, expression=self.expression)


class SourceCorrectionError(Exception):
    """A recorded correction did not match the extracted record it targets."""


Correction = ReplaceIn | SetExpression

# ---------------------------------------------------------------------------
# The closed table: eight Class-A defects (UGD-11d-A / card t_62bd276f).
# Keyed by (source, source_id). Corrections apply in listed order.
# ---------------------------------------------------------------------------

CORRECTIONS: dict[tuple[str, str], tuple[Correction, ...]] = {
    # A1. にほかならない — dojg misspells the headword: にはかならない (6x in the
    # structure table) and ことにほならない (1x, in an example). The same rows write
    # にほかならない correctly 13x; every other source agrees on にほかならない.
    ("dojg", "にほかならない"): (
        ReplaceIn("structure", "にはかならない", "にほかならない", 6, "A1"),
        ReplaceIn(
            "examples",
            "ことにほならない",
            "ことにほかならない",
            1,
            "A1",
        ),
    ),
    # A2. でしょう — nihongo_net's N row carries a ※ note that inserts だ, licensing
    # ×雨だでしょう. The noun attaches bare (edewakaru 名詞［辞書形］＋…でしょう,
    # donna_toki 「いい色でしょう」). Drop the copula from the note.
    ("nihongo_net", "でしょう"): (
        ReplaceIn("structure", "※Nだ + でしょう", "※Nでしょう", 1, "A2"),
    ),
    # A3. かどうか — nihongo_net keeps だ before かどうか for ナA and N, licensing
    # ×便利だかどうか. Standard rule (nihongo_no_sensei) is bare stem + (である/なの).
    ("nihongo_net", "かどうか"): (
        ReplaceIn(
            "structure",
            "ナA（普通形）だかどうか、〜 ※ナAだ",
            "ナA（語幹）（である／なの）かどうか、〜",
            1,
            "A3",
        ),
        ReplaceIn(
            "structure",
            "N（普通形）だかどうか、〜 ※Nだ",
            "N（である／なの）かどうか、〜",
            1,
            "A3",
        ),
    ),
    # A4. さえ — nihongo_net's verb row says さえあれば (×飲みさえあれば), contradicted
    # by its own example 飲みさえすれば and by donna_toki Vます＋さえすれば. Only the
    # verb row is wrong; さえあれば stays on the イAく／ナAで／N rows.
    ("nihongo_net", "さえ"): (
        ReplaceIn(
            "structure",
            "V（ます形）ます + さえあれば",
            "V（ます形）ます + さえすれば",
            1,
            "A4",
        ),
    ),
    # A5. ないでもない — nihongo_net's structure is pasted from 〜ものでもない; all four
    # rows and all eight of its own examples are V+ないでもない. Correct ものでもない
    # → ないでもない across the four structure rows.
    ("nihongo_net", "ないでもない"): (
        ReplaceIn("structure", "ものでもない", "ないでもない", 4, "A5"),
    ),
    # A6. かいがあって — nihongo_net's structure names あげく (paste error). The
    # formation is する動詞のNの＋かいがあって (donna_toki). Same paste fires on the
    # かいもなく record, which shares the identical structure block.
    ("nihongo_net", "かいがあって"): (
        ReplaceIn(
            "structure",
            "Nの + あげく ※Nはする動詞のN",
            "する動詞のNの + かいがあって",
            1,
            "A6",
        ),
    ),
    ("nihongo_net", "かいもなく"): (
        ReplaceIn(
            "structure",
            "Nの + あげく ※Nはする動詞のN",
            "する動詞のNの + かいがあって",
            1,
            "A6",
        ),
    ),
    # A7. に至るまで — nihongo_net's record is really a 〜に至る entry: its structure is
    # V（辞書形）+ に至る / N + に至る (no まで) and all three examples lack まで. Re-home
    # it onto the 〜に至る headword so it stops corrupting the range-meaning
    # に至るまで card and merges with the other sources' に至る records.
    ("nihongo_net", "に至るまで"): (
        SetExpression("に至る", "に至るまで", "A7"),
    ),
    # A8. ことは — dojg's noun rows drop the defining こと: 「いい人はいい人{だ/です}」
    # and 「いい人だったことは人{だった/でした}」. The well-formed noun pattern is
    # NであることはN{だ/です}（が） (edewakaru). The な-adjective rows (静かなことは…)
    # are already correct and are left untouched.
    ("dojg", "ことは"): (
        ReplaceIn(
            "structure",
            "| いい人はいい人{だ/です} | Someone is a good person |",
            "| いい人であることはいい人{だ/です} | Someone is a good person |",
            1,
            "A8",
        ),
        ReplaceIn(
            "structure",
            "| いい人だったことは人{だった/でした} | Someone was a good person |",
            "| いい人だったことはいい人{だった/でした} | Someone was a good person |",
            1,
            "A8",
        ),
    ),
}


def correct_point(point: GrammarPoint) -> GrammarPoint:
    """Apply every recorded correction for ``point``'s (source, source_id).

    Identity for any record with no correction entry, so unaffected points stay
    byte-identical through a re-extract.
    """
    corrections = CORRECTIONS.get((point.source, point.source_id))
    if not corrections:
        return point
    for correction in corrections:
        point = correction.apply(point)
    return point


__all__ = [
    "CORRECTIONS",
    "Correction",
    "ReplaceIn",
    "SetExpression",
    "SourceCorrectionError",
    "correct_point",
]
