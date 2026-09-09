"""The one interchange record every source normalizes into.

`GrammarPoint` is the contract between stage boundaries: per-source extractors
emit it, the merge stage unifies it, and the bank generator is the only stage
allowed to know about Yomitan structured content. Adding a source must not
require touching the merge or bank stages.

Field policy notes carried from SOURCES.md:

* `source` is mandatory on every record — merged entries keep per-source
  attribution, so a user always sees which grammar source a statement came from.
* AI/LLM-generated source fields are never presented as authoritative dictionary
  fact. They are carried separately in `ai_generated` and may only be rendered
  behind an explicitly labelled closed disclosure (or dropped entirely).
* Compact-card selection is a rendering decision. Extractors preserve the whole
  tail; they must not truncate to a card budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .jsonio import MalformedPayload

# JLPT levels accepted verbatim from sources; anything else is normalized away
# rather than guessed at.
JLPT_LEVELS = ("N5", "N4", "N3", "N2", "N1")

#: Canonical grammar for a row identity: the source name, a colon, and a
#: positive decimal ordinal with no sign, underscore, or non-ASCII digit. Written
#: as an explicit ASCII grammar because `int()` accepts `1_0`, `+1` and Unicode
#: digits, any of which would let two spellings of one ordinal exist.
ROW_UID_ORDINAL = re.compile(r"[1-9][0-9]*\Z", re.ASCII)


def row_uid(source: str, ordinal: int) -> str:
    """Build the stable unique identity of one extracted source row."""
    if not isinstance(source, str) or not source.strip() or ":" in source:
        raise MalformedPayload(f"a row uid needs a colon-free source name, got {source!r}")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise MalformedPayload(f"a row uid ordinal must be a positive integer, got {ordinal!r}")
    return f"{source}:{ordinal}"


def row_uid_matches(value: str, source: str) -> bool:
    """True when `value` is exactly `<source>:<positive-decimal-ordinal>`."""
    if not isinstance(value, str):
        return False
    prefix = f"{source}:"
    if not value.startswith(prefix):
        return False
    return bool(ROW_UID_ORDINAL.fullmatch(value[len(prefix) :]))


@dataclass(frozen=True)
class Example:
    """One example sentence.

    `japanese` is the surface sentence. `english` is a translation when the
    source supplies one — never machine-translated by this build. `highlight`
    holds the substrings the source marked as the grammar point in context.

    `japanese_html` carries the source's own inline markup for the same sentence
    when it ships any — Bunpro annotates 98.7% of its 21,142 example sentences
    with `<ruby>`/`<rt>` furigana, which flattening to `japanese` would silently
    discard. It is kept as raw source HTML rather than converted structured
    content because conversion is the bank stage's job, not an extractor's, and
    because `japanese` must stay a plain string for `sentence_key` duplicate
    counting and for `highlight` substring matching.

    Invariant: when `japanese_html` is set, its flattened surface text equals
    `japanese`. The two can never disagree about what the sentence says; one is
    strictly the annotated form of the other.
    """

    japanese: str
    english: str | None = None
    highlight: tuple[str, ...] = ()
    ai_generated: bool = False
    japanese_html: str | None = None


@dataclass(frozen=True)
class GrammarPoint:
    """One normalized grammar point from one source.

    Merging happens on `merge_key`; `source` + `source_id` stay attached so the
    unified entry can attribute every rendered section.
    """

    source: str
    source_id: str
    # Headword(s) the user looks up. `expression` is canonical; `variants` are
    # additional lookup forms that must resolve to the same entry.
    expression: str
    #: Unique identity of the extracted row this record came from, `<source>:<n>`.
    #:
    #: `source_id` is the producer's own handle and is **not unique**: one
    #: `source_id` names up to 22 different rows in `edewakaru`, so
    #: `(source, source_id)` addressed 2+ genuinely different records on 289
    #: handles and asserted two JLPT levels under one handle on 54 entries.
    #: `row_uid` is assigned once per extracted row by `ExtractResult`, which
    #: fails closed on a repeat, so a claim can always be traced back to exactly
    #: one source record. Empty only on records that are not extracted source
    #: rows (a synthesised redirect pointer), never on a source row.
    row_uid: str = ""
    variants: tuple[str, ...] = ()
    reading: str | None = None

    # Human-authored substance.
    meaning: str | None = None
    structure: str | None = None
    nuance: str | None = None
    explanation: str | None = None
    notes: str | None = None
    jlpt: str | None = None

    # Japanese-language counterparts of `nuance`/`explanation`. Sources that
    # author both languages (Bunpro's Nuance_JP/Explanation_JP) keep them apart
    # from the English fields so the card can disclose them under their own
    # `lang="ja"` section instead of concatenating two languages into one blob.
    nuance_ja: str | None = None
    explanation_ja: str | None = None

    examples: tuple[Example, ...] = ()
    tags: tuple[str, ...] = ()

    # Source fields flagged as AI/LLM-generated, kept segregated from the fields
    # above so they can never be rendered as authoritative dictionary content.
    ai_generated: dict[str, object] = field(default_factory=dict)

    # Free-form per-source provenance (deck notetype, lesson URL, revision...).
    provenance: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source", "source_id", "expression"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise MalformedPayload(f"GrammarPoint.{name} must be a non-empty string")
        if self.jlpt is not None and self.jlpt not in JLPT_LEVELS:
            raise MalformedPayload(f"GrammarPoint.jlpt is not a known level: {self.jlpt!r}")
        if self.row_uid and not row_uid_matches(self.row_uid, self.source):
            raise MalformedPayload(
                f"GrammarPoint.row_uid {self.row_uid!r} is not {self.source!r}:<ordinal>"
            )

    @property
    def merge_key(self) -> str:
        """Key the merge stage groups on.

        Deliberately naive at scaffold time: the real cross-source alignment
        policy (normalization, variant folding, tie-breaking) is decided by the
        merge card, and every rule belongs in `bugd.merge`, not here.
        """
        return self.expression


__all__ = [
    "Example",
    "GrammarPoint",
    "JLPT_LEVELS",
    "ROW_UID_ORDINAL",
    "row_uid",
    "row_uid_matches",
]
