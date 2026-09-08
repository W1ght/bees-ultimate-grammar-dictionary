"""Merge stage: many per-source records -> one unified corpus.

The merge stage is the only place cross-source alignment policy lives. It groups
normalized `GrammarPoint` records into `MergedEntry` objects keyed by lookup
form, preserves every contributing source, and never silently discards a source's
substance.

Policy the implementing card must decide and encode here (not in extractors, not
in the bank generator):

* which normalization is applied before grouping (width, kana, okurigana,
  bracketed alternatives, trailing particles);
* deterministic ordering of contributing sources within one entry;
* variant/alias forms that must resolve to the same entry;
* de-duplication of learner-visible duplicates (identical example sentences
  arriving from two sources) as distinct from source-identity de-duplication;
* how conflicting JLPT levels or structures across sources are presented —
  shown side by side with attribution, never averaged or silently picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .jsonio import MalformedPayload
from .model import GrammarPoint


@dataclass
class MergedEntry:
    """One unified dictionary entry backed by one or more sources."""

    expression: str
    variants: tuple[str, ...] = ()
    contributions: list[GrammarPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.expression, str) or not self.expression.strip():
            raise MalformedPayload("MergedEntry.expression must be a non-empty string")

    @property
    def sources(self) -> tuple[str, ...]:
        """Contributing source names, in contribution order, de-duplicated."""
        seen: dict[str, None] = {}
        for point in self.contributions:
            seen.setdefault(point.source, None)
        return tuple(seen)


def merge_points(points: list[GrammarPoint]) -> list[MergedEntry]:
    """Group normalized points into unified entries.

    Scaffold behaviour: group on `GrammarPoint.merge_key` with stable ordering,
    so the stage seam and its artifact shape are exercisable end to end. The real
    alignment policy replaces this body; the signature is the contract.
    """
    grouped: dict[str, MergedEntry] = {}
    for point in points:
        if not isinstance(point, GrammarPoint):
            raise MalformedPayload("merge_points accepts GrammarPoint records only")
        entry = grouped.get(point.merge_key)
        if entry is None:
            entry = MergedEntry(expression=point.expression)
            grouped[point.merge_key] = entry
        entry.contributions.append(point)

    for entry in grouped.values():
        variants: dict[str, None] = {}
        for point in entry.contributions:
            for variant in point.variants:
                if variant != entry.expression:
                    variants.setdefault(variant, None)
        entry.variants = tuple(variants)

    return [grouped[key] for key in sorted(grouped)]


__all__ = ["MergedEntry", "merge_points"]
