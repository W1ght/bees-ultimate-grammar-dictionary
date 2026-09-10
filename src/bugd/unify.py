"""Unify every source into ONE dataset, keyed by the cross-source keymap.

This is the stage that turns 4,972 per-source rows into the single canonical
grammar dictionary. It is deliberately the only place that knows how sources are
combined; `bugd.keymap` decides *which* rows are the same grammar point, and this
module decides *what one unified entry looks like* once they are.

Design decisions, each measured against the real corpus rather than assumed:

**The keymap is the authority, and disagreement is fatal.**
`unify` resolves every row through `data/merge/keymap.json`. It never falls back
to a derived key when a row is missing from the keymap, because the fallback is
exactly how corpus loss stays invisible: replaying a keymap built against a
superseded extraction left 1,664 substantive rows unresolved, and a tolerant
merge would have silently dropped a third of the dictionary while reporting
success. `ensure_consistent` raises `StaleKeymap` instead.

**One entry per (partition axes, bucketKey), not per canonical key.**
The keymap refuses to fold 210 buckets whose senses it cannot prove identical,
so it emits several canonical points sharing one `bucketKey` (`ない` yields 19).
Rendering those as 19 sibling cards for one lookup form is the outcome UGD-07
explicitly asked this stage to avoid, so an entry groups every point in one
bucket and keeps the refused senses as ordered `senses` inside it. Measured:
2,609 canonical points -> 1,696 unified entries.

**Senses are ordered naturally, not lexicographically.**
Sorting on `canonicalKey` puts `#sense10` before `#sense2`; 18 buckets have >=10
ordinal senses, so a reader of `お` (14 senses) or `あまり` (11) would see the
producer's own sense order shuffled. Ordering uses a digit-aware key.

**Every source's substance is kept, attributed, and never reconciled.**
JLPT levels genuinely conflict across sources (158 buckets: `に反して` is N2 to
one source and N3 to another), so levels are carried per contribution and
per entry as an observed set. Nothing is averaged, voted, or picked.

**De-duplication is scoped per source, because cross-source repetition is
evidence, not noise.** Exactly 1 duplicated example sentence in the whole corpus
crosses a source boundary while 622 repeat inside one source; collapsing across
sources would erase the fact that two independent dictionaries chose the same
sentence. When de-duplication would empty a row that has no other substance,
the row keeps its examples (`keep-last-when-emptied`) so a contribution never
becomes invisible: 106 rows are emptied by naive first-wins, 4 of which would
render nothing at all.

**Findability is preserved exactly.** 750 written forms in the corpus are not a
unified entry's headword. Dropping them loses lookups a user can perform today,
so each becomes a `redirect` entry pointing at the entry that holds the
substance. Resolution routes, in the precedence the code applies:
**declared** (702) uses the producer's own `aliasOf`/`canonicalExpression`/
`seeAlso` or internal `?query=` link; **reading** (41) resolves a kana-only
declared target through a reading that lands in exactly ONE entry; **folded** (2)
covers a form with no usable declaration whose own rows were folded into an entry
written differently. Because `declared` is tried first it absorbs 587 forms that
were also reachable as a folded lookup form, which is why `folded` is small. The
5 forms that stay ambiguous or targetless are reported as `unresolved` rather
than attached to a guess.

**The AI channel and media are built and tested, not observed.** The corpus
currently carries 0 AI-generated fields and 0 media references (文法/UGD-02 has
not landed and extractors strip `img`). This module therefore preserves both
channels structurally and the suite proves it with synthetic fixtures; no claim
is made that corpus evidence exercised them.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import typing
from collections import Counter, defaultdict

from .jsonio import MalformedPayload, content_hash, dump_json, load_json
from .reading_corrections import ReadingCorrection, StaleCorrection
from .keymap import alias_targets, is_declared_alias, substance_hash
from .model import JLPT_LEVELS, Example, GrammarPoint, row_uid_matches
from .normalize import PLACEHOLDER_TILDES

if typing.TYPE_CHECKING:  # pragma: no cover - import cycle broken at runtime
    from .merge import MergedEntry

#: Default location of the keymap artifact this stage resolves rows through.
DEFAULT_KEYMAP_PATH = pathlib.Path("data/merge/keymap.json")

#: Default output of this stage.
DEFAULT_UNIFIED_PATH = pathlib.Path("data/merge/unified.jsonl")

#: Default stats sidecar written next to the unified dataset.
DEFAULT_STATS_PATH = pathlib.Path("data/merge/unified.stats.json")

#: Keymap schema revision this module knows how to read.
SUPPORTED_KEYMAP_SCHEMA = 1

#: Entry kinds. A `point` carries substance; a `redirect` exists purely so a
#: written form a source ships stays findable.
KIND_POINT = "point"
KIND_REDIRECT = "redirect"

_SUBSTANCE_FIELDS = ("meaning", "structure", "nuance", "explanation", "notes")

_DIGITS = re.compile(r"(\d+)")


class StaleKeymap(MalformedPayload):
    """The keymap and the extracted corpus are not self-consistent.

    Raised instead of merging on a best-effort basis. The failure names the
    unresolved rows so the fix (`make keymap`) is obvious, because the tolerant
    alternative silently deletes corpus.
    """

    def __init__(self, unresolved: list[tuple[str, str]], total: int) -> None:
        self.unresolved = unresolved
        self.total = total
        shown = ", ".join(f"{source}:{source_id}" for source, source_id in unresolved[:5])
        super().__init__(
            f"{len(unresolved)} of {total} substantive rows are absent from the keymap "
            f"({shown}{', ...' if len(unresolved) > 5 else ''}). The keymap was built "
            f"against a different extraction; rebuild it with `make keymap` rather than "
            f"merging on derived keys, which would silently drop these rows."
        )


def natural_key(text: str) -> tuple[object, ...]:
    """Sort key that orders embedded integers numerically.

    `#sense2` must precede `#sense10`. Plain lexicographic ordering does not, and
    18 buckets carry >=10 ordinal senses, so the producer's own sense order would
    be visibly shuffled on the busiest cards in the dictionary.
    """
    parts = _DIGITS.split(text)
    return tuple(int(part) if part.isdigit() else part for part in parts)


# --------------------------------------------------------------------------
# unified record shapes
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Contribution:
    """One source's statement about one grammar point, with attribution intact.

    A contribution is never merged into another contribution: it is the unit the
    card renders under a labelled per-source disclosure, so `source`,
    `source_id`, `source_label` and `provenance` stay attached to the exact prose
    they came from.

    `row_uid` is the machine identity of the one extracted source row this
    contribution restates; `source_id` remains the producer's human-facing
    headword and is deliberately NOT unique (one `edewakaru` `source_id` names 22
    rows). Attribution must be keyed on `row_uid`: keying on
    `(source, source_id)` addressed 2+ genuinely different records on 289 handles
    and put two different JLPT levels under one handle on 54 entries.
    """

    source: str
    source_id: str
    source_label: str
    canonical_key: str
    expression: str
    reading: str | None
    meaning: str | None
    structure: str | None
    nuance: str | None
    explanation: str | None
    notes: str | None
    jlpt: str | None
    row_uid: str = ""
    examples: tuple[Example, ...] = ()
    tags: tuple[str, ...] = ()
    ai_generated: dict[str, object] = dataclasses.field(default_factory=dict)
    provenance: dict[str, object] = dataclasses.field(default_factory=dict)
    duplicate_examples_removed: int = 0

    @property
    def has_substance(self) -> bool:
        return bool(self.examples) or any(
            getattr(self, name) for name in _SUBSTANCE_FIELDS
        )


@dataclasses.dataclass(frozen=True)
class Sense:
    """One canonical point inside a unified entry.

    A bucket the keymap refused to fold contributes several senses; a folded
    bucket contributes exactly one. `disambiguator` and `disambiguator_basis` are
    the keymap's own account of *why* this sense is separate, so a card can label
    it with something the source actually says instead of an opaque ordinal.
    """

    canonical_key: str
    disambiguator: str
    expression: str
    contributions: tuple[Contribution, ...]

    @property
    def sources(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for contribution in self.contributions:
            seen.setdefault(contribution.source, None)
        return tuple(seen)


@dataclasses.dataclass(frozen=True)
class UnifiedEntry:
    """One entry of the single unified dictionary."""

    entry_id: str
    kind: str
    expression: str
    reading: str | None
    axes: dict[str, str]
    bucket_key: str
    lookup_forms: tuple[str, ...]
    senses: tuple[Sense, ...] = ()
    jlpt_levels: tuple[str, ...] = ()
    registers: tuple[str, ...] = ()
    signatures: tuple[str, ...] = ()
    redirect_targets: tuple[str, ...] = ()
    redirect_basis: str = ""
    redirect_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in (KIND_POINT, KIND_REDIRECT):
            raise MalformedPayload(f"unknown unified entry kind: {self.kind!r}")
        if not isinstance(self.expression, str) or not self.expression.strip():
            raise MalformedPayload("UnifiedEntry.expression must be a non-empty string")
        if self.kind == KIND_POINT and not self.senses:
            raise MalformedPayload(f"a {KIND_POINT} entry must carry at least one sense")
        if self.kind == KIND_REDIRECT and self.senses:
            raise MalformedPayload(f"a {KIND_REDIRECT} entry must not carry senses")

    @property
    def contributions(self) -> tuple[Contribution, ...]:
        return tuple(c for sense in self.senses for c in sense.contributions)

    @property
    def sources(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for contribution in self.contributions:
            seen.setdefault(contribution.source, None)
        return tuple(seen)


# --------------------------------------------------------------------------
# keymap resolution
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Keymap:
    """The parsed keymap: row -> canonical key, plus each point's own record."""

    assignments: dict[tuple[str, str, str], str]
    points: dict[str, dict[str, object]]

    def key_for(self, source: str, record: dict[str, object]) -> str | None:
        return self.assignments.get(
            (source, str(record.get("source_id") or ""), substance_hash(record))
        )


def parse_keymap(payload: object) -> Keymap:
    """Parse a keymap artifact, refusing anything it cannot read exactly."""
    if not isinstance(payload, dict):
        raise MalformedPayload("a keymap payload must be an object")
    schema = payload.get("schemaVersion")
    if schema != SUPPORTED_KEYMAP_SCHEMA:
        raise MalformedPayload(
            f"unsupported keymap schemaVersion {schema!r}; "
            f"this build reads {SUPPORTED_KEYMAP_SCHEMA}"
        )

    raw_assignments = payload.get("assignments")
    raw_points = payload.get("points")
    if not isinstance(raw_assignments, list) or not isinstance(raw_points, list):
        raise MalformedPayload("a keymap needs `assignments` and `points` arrays")

    assignments: dict[tuple[str, str, str], str] = {}
    for item in raw_assignments:
        if not isinstance(item, dict):
            raise MalformedPayload("each keymap assignment must be an object")
        try:
            row = (str(item["source"]), str(item["sourceId"]), str(item["substanceHash"]))
            key = str(item["canonicalKey"])
        except KeyError as missing:
            raise MalformedPayload(f"keymap assignment lacks {missing}") from None
        assignments[row] = key

    points: dict[str, dict[str, object]] = {}
    for item in raw_points:
        if not isinstance(item, dict) or "canonicalKey" not in item:
            raise MalformedPayload("each keymap point must be an object with canonicalKey")
        points[str(item["canonicalKey"])] = item

    unknown = {key for key in assignments.values() if key not in points}
    if unknown:
        raise MalformedPayload(
            f"{len(unknown)} keymap assignment(s) name a canonicalKey with no point record: "
            f"{sorted(unknown)[:5]}"
        )
    return Keymap(assignments=assignments, points=points)


def load_keymap(path: pathlib.Path = DEFAULT_KEYMAP_PATH) -> Keymap:
    if not path.is_file():
        raise MalformedPayload(
            f"no keymap at {path}; run `make keymap` before merging. The merge stage "
            f"refuses to invent keys because a derived-key fallback silently drops rows."
        )
    return parse_keymap(load_json(path.read_text(encoding="utf-8")))


def load_extracted(
    extracted_dir: pathlib.Path,
) -> tuple[list[tuple[str, dict[str, object]]], dict[str, str]]:
    """Load every per-source artifact in a deterministic order.

    Returns `(rows, labels)` where each row is `(source, record)`. Source files
    are read in sorted order and rows keep their producer order inside a file, so
    the merge is reproducible without depending on filesystem iteration.
    """
    rows: list[tuple[str, dict[str, object]]] = []
    labels: dict[str, str] = {}
    for path in sorted(extracted_dir.glob("*.json")):
        payload = load_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
            raise MalformedPayload(f"malformed extracted artifact: {path}")
        source = str(payload.get("source") or "")
        if not source:
            raise MalformedPayload(f"extracted artifact declares no source: {path}")
        labels[source] = str(payload.get("label") or source)
        for record in payload["points"]:
            if not isinstance(record, dict):
                raise MalformedPayload(f"malformed record in {path}")
            rows.append((source, record))
    return rows, labels


def ensure_consistent(
    rows: list[tuple[str, dict[str, object]]], keymap: Keymap
) -> None:
    """Fail closed when a substantive row has no canonical key.

    A declared alias is *expected* to be unassigned (the keymap demotes it to a
    lookup form), so only non-alias rows count. Anything else means the keymap
    describes a different extraction than the one on disk.
    """
    unresolved: list[tuple[str, str]] = []
    substantive = 0
    for source, record in rows:
        if is_declared_alias(record):
            continue
        substantive += 1
        if keymap.key_for(source, record) is None:
            unresolved.append((source, str(record.get("source_id") or "")))
    if unresolved:
        raise StaleKeymap(unresolved, substantive)


# --------------------------------------------------------------------------
# contribution assembly
# --------------------------------------------------------------------------


def _examples_of(record: dict[str, object]) -> tuple[Example, ...]:
    raw = record.get("examples") or ()
    if not isinstance(raw, (list, tuple)):
        raise MalformedPayload("a record's `examples` must be an array")
    built: list[Example] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MalformedPayload("each example must be an object")
        japanese = item.get("japanese")
        if not isinstance(japanese, str) or not japanese.strip():
            raise MalformedPayload("an example needs a non-empty `japanese`")
        highlight = item.get("highlight") or ()
        if not isinstance(highlight, (list, tuple)):
            raise MalformedPayload("an example's `highlight` must be an array")
        built.append(
            Example(
                japanese=japanese,
                english=item.get("english") or None,
                highlight=tuple(str(h) for h in highlight),
                # The AI flag is preserved exactly, never inferred. A source that
                # does not declare it is not AI-flagged.
                ai_generated=bool(item.get("ai_generated")),
            )
        )
    return tuple(built)


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedPayload(f"expected text or null, got {type(value).__name__}")
    return value or None


def _mapping(value: object, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MalformedPayload(f"a record's `{field}` must be an object")
    return dict(value)


def build_contribution(
    source: str,
    record: dict[str, object],
    *,
    canonical_key: str,
    source_label: str,
    examples: tuple[Example, ...] | None = None,
    duplicate_examples_removed: int = 0,
) -> Contribution:
    """Turn one source row into one attributed contribution.

    The AI-generated channel travels as its own mapping and is never folded into
    the human-authored fields, so a downstream renderer physically cannot present
    it as authoritative dictionary fact by accident.
    """
    tags = record.get("tags") or ()
    if not isinstance(tags, (list, tuple)):
        raise MalformedPayload("a record's `tags` must be an array")
    uid = record.get("row_uid")
    if not isinstance(uid, str) or not row_uid_matches(uid, source):
        raise MalformedPayload(
            f"{source}:{record.get('source_id')!r} has no valid row_uid ({uid!r}). Re-run "
            f"`make extract`: attribution is keyed on row identity because source_id is "
            f"not unique, so merging a row without one would reintroduce ambiguous claims."
        )
    return Contribution(
        source=source,
        source_id=str(record.get("source_id") or ""),
        row_uid=uid,
        source_label=source_label,
        canonical_key=canonical_key,
        expression=str(record["expression"]),
        reading=_text_or_none(record.get("reading")),
        meaning=_text_or_none(record.get("meaning")),
        structure=_text_or_none(record.get("structure")),
        nuance=_text_or_none(record.get("nuance")),
        explanation=_text_or_none(record.get("explanation")),
        notes=_text_or_none(record.get("notes")),
        jlpt=_text_or_none(record.get("jlpt")),
        examples=_examples_of(record) if examples is None else examples,
        tags=tuple(str(tag) for tag in tags),
        ai_generated=_mapping(record.get("ai_generated"), "ai_generated"),
        provenance=_mapping(record.get("provenance"), "provenance"),
        duplicate_examples_removed=duplicate_examples_removed,
    )


def dedupe_examples(
    contributions: list[Contribution],
) -> tuple[list[Contribution], int]:
    """Drop learner-visible duplicate sentences WITHIN one source.

    Scoped per source on purpose. Exactly one duplicated sentence in the whole
    corpus crosses a source boundary against 622 that repeat inside one source,
    so a global scope would erase the (interesting) fact that two independent
    dictionaries chose the same sentence while removing almost nothing extra.

    `keep-last-when-emptied`: if de-duplication would leave a contribution with
    no examples AND it has no other substance, its examples are restored. 106
    rows are emptied by naive first-wins and 4 of them would otherwise render as
    a blank per-source section, which reads as a broken card rather than as
    honest de-duplication.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    result: list[Contribution] = []
    removed = 0
    for contribution in contributions:
        if not contribution.examples:
            result.append(contribution)
            continue
        scope = seen[contribution.source]
        kept: list[Example] = []
        dropped = 0
        for example in contribution.examples:
            sentence = example.japanese.strip()
            if sentence in scope:
                dropped += 1
                continue
            scope.add(sentence)
            kept.append(example)
        if not kept and not any(
            getattr(contribution, name) for name in _SUBSTANCE_FIELDS
        ):
            # Restoring keeps the section visible; the sentences are still marked
            # as duplicated so stats never overstate what was removed.
            result.append(contribution)
            continue
        removed += dropped
        result.append(
            dataclasses.replace(
                contribution,
                examples=tuple(kept),
                duplicate_examples_removed=dropped,
            )
        )
    return result, removed


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------


def _axes_of(point: dict[str, object]) -> dict[str, str]:
    axes = point.get("axes")
    if not isinstance(axes, dict):
        raise MalformedPayload(f"keymap point {point.get('canonicalKey')!r} lacks axes")
    return {"variety": str(axes.get("variety") or ""), "era": str(axes.get("era") or "")}


def _group_of(point: dict[str, object]) -> tuple[str, str, str]:
    axes = _axes_of(point)
    return axes["variety"], axes["era"], str(point.get("bucketKey") or "")


def display_headword(form: str) -> str:
    """Normalize a form for use as the emitted LOOKUP headword.

    Two transforms, both about reachability rather than content:

    1. **Strip leading placeholder marks.** A leading `〜`/`～`/`~` is a producer's
       slot placeholder meaning "something attaches here", not part of the written
       form -- `normalize.PLACEHOLDER_TILDES` already documents this and
       `lookup_key` already discards them, which is why stripping here cannot move
       any bucket's identity. It has to go from the emitted headword too, because
       Yomitan's `termsFind` matches from the START of the query text: a headword
       stored as `〜あとで` is unreachable, since the learner types `あとで` and the
       scan never matches. Measured on the convergence artifact, 1,198 of 4,623
       entries (26%) were stored tilde-first and therefore unlookupable, against 0
       in the pre-convergence 5-source baseline -- the five source families landed
       by UGD-16 publish their headwords with the placeholder attached, while the
       original five stripped it in `yomitan_bank.TermRow`.

       Only LEADING marks go: an interior tilde (`〜たりとも〜ない`) carries real
       structure about where the second slot falls.

    2. Nothing else. In particular a newline is NOT cut here. Exactly one row in
       the corpus (`bunpou` `〜向けに\\n類似文型「〜向き」との違い`) glues a comparison
       note onto its headword with a line break, and truncating it at this layer
       collides it onto the genuine `向けに` point -- two `point` entries sharing a
       headword with identical axes, which is a merge-identity defect rather than a
       display one. Repairing a producer's headword belongs in the recorded
       correction table, where the change is keyed, reviewable and replayable;
       `display_headword` only removes marks that were never part of the form.

    A form that reduces to nothing is returned untouched rather than emptied.
    """
    stripped = form.lstrip(PLACEHOLDER_TILDES + "\u3000 ")
    return stripped if stripped else form


def choose_headword(bucket_key: str, expressions: list[str]) -> str:
    """The written form the unified entry is looked up under.

    The bucket key wins when a contributing point actually writes it that way
    (1,679 of 1,696 buckets), because it is the form the matcher aligned on and
    it keeps the entry's identity and its headword in agreement. Otherwise the
    lexicographically first contributing expression is used, which is stable and
    is always a form some source really publishes -- never a synthesised string.

    The chosen form then has leading placeholder marks stripped so it is actually
    reachable by `termsFind`; see `display_headword`.
    """
    if bucket_key in expressions:
        return display_headword(bucket_key)
    if not expressions:
        raise MalformedPayload("cannot choose a headword with no expressions")
    return display_headword(sorted(expressions)[0])


def _entry_reading(contributions: tuple[Contribution, ...], expression: str) -> str | None:
    """The furigana reading, preserved from the first source that differs.

    Yomitan treats `reading == expression` as a redundant furigana pair, so a
    reading equal to the headword is not carried. Contribution order is the
    merge's deterministic order, so the choice is reproducible.
    """
    for contribution in contributions:
        reading = contribution.reading
        if reading and reading != expression:
            return reading
    return None


# --------------------------------------------------------------------------
# the unification pass
# --------------------------------------------------------------------------


def _string_list(point: dict[str, object], field: str) -> list[str]:
    """Read a keymap point's array field, refusing a non-array."""
    value = point.get(field)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise MalformedPayload(
            f"keymap point {point.get('canonicalKey')!r} field {field!r} must be an array"
        )
    return [str(item) for item in value]


def unify(
    rows: list[tuple[str, dict[str, object]]],
    keymap: Keymap,
    labels: dict[str, str],
    *,
    corrections: list[ReadingCorrection] | None = None,
) -> tuple[list[UnifiedEntry], dict[str, object]]:
    """Merge every source row into the one unified dataset.

    Returns `(entries, stats)`. Entries are ordered by headword then entry id, so
    the dataset is byte-reproducible for a given extraction and keymap.

    `corrections` is the evidence-backed reading-correction overlay. It is applied
    to the *assembled contributions*, not the raw rows, so the keymap's grouping
    identity (which includes the reading) is unchanged and only the carried
    reading is rewritten. It defaults to no corrections; the pipeline
    (`bugd.pipeline.run_merge`) loads `data/corrections/readings.json` and passes
    it in, keeping this function pure for callers that build their own rows.
    Every supplied correction must match at least one contribution or
    `StaleCorrection` is raised, so a stale overlay can never pass silently.
    """
    corrections = list(corrections or ())
    ensure_consistent(rows, keymap)

    # Byte-exact reading-correction lookup, keyed on the same tuple the overlay
    # declares. Applied to assembled contributions below; `_correction_hits`
    # records which corrections actually matched so a stale overlay fails closed.
    correction_by_key: dict[tuple[str, str, str, str], ReadingCorrection] = {
        c.match_key: c for c in corrections
    }
    correction_hits: set[tuple[str, str, str, str]] = set()

    def _corrected(contribution: Contribution) -> Contribution:
        key = (
            contribution.source,
            contribution.source_id,
            contribution.expression,
            contribution.reading or "",
        )
        correction = correction_by_key.get(key)
        if correction is None:
            return contribution
        correction_hits.add(key)
        return dataclasses.replace(contribution, reading=correction.to_reading)

    # 1. Bucket every assigned row by (axes, bucketKey), keeping producer order.
    grouped: dict[tuple[str, str, str], dict[str, list[tuple[str, dict[str, object]]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    collapsed_duplicate_rows = 0
    seen_rows: set[tuple[str, str, str]] = set()
    for source, record in rows:
        key = keymap.key_for(source, record)
        if key is None:
            continue
        identity = (source, str(record.get("source_id") or ""), substance_hash(record))
        if identity in seen_rows:
            # The keymap's row identity is (source, sourceId, substanceHash); a
            # repeat is a byte-identical duplicate shipped twice by one producer.
            collapsed_duplicate_rows += 1
            continue
        seen_rows.add(identity)
        grouped[_group_of(keymap.points[key])][key].append((source, record))

    # 2. Build one entry per bucket.
    entries: list[UnifiedEntry] = []
    duplicate_examples_removed = 0
    for group in sorted(grouped, key=lambda g: (g[0], g[1], natural_key(g[2]))):
        variety, era, bucket_key = group
        by_key = grouped[group]

        senses: list[Sense] = []
        # Sense order follows the canonical key naturally, so #sense2 precedes
        # #sense10 and a signature/form disambiguator stays alphabetical.
        for canonical_key in sorted(by_key, key=natural_key):
            point = keymap.points[canonical_key]
            members = by_key[canonical_key]
            contributions = [
                _corrected(
                    build_contribution(
                        source,
                        record,
                        canonical_key=canonical_key,
                        source_label=labels.get(source, source),
                    )
                )
                for source, record in members
            ]
            senses.append(
                Sense(
                    canonical_key=canonical_key,
                    disambiguator=str(point.get("disambiguator") or ""),
                    expression=str(point.get("expression") or bucket_key),
                    contributions=tuple(contributions),
                )
            )

        # 3. De-duplicate learner-visible examples across the whole entry, per
        #    source. Scoped at entry level so a sentence repeated by one source in
        #    two refused senses of the same bucket is shown once.
        flat, removed_here = dedupe_examples(
            [c for sense in senses for c in sense.contributions]
        )
        duplicate_examples_removed += removed_here
        cursor = 0
        rebuilt: list[Sense] = []
        for sense in senses:
            width = len(sense.contributions)
            rebuilt.append(
                dataclasses.replace(sense, contributions=tuple(flat[cursor : cursor + width]))
            )
            cursor += width
        senses = rebuilt

        expressions = [c.expression for sense in senses for c in sense.contributions]
        expression = choose_headword(bucket_key, expressions)

        lookup_forms: dict[str, None] = {expression: None}
        jlpt: dict[str, None] = {}
        registers: dict[str, None] = {}
        signatures: dict[str, None] = {}
        for canonical_key in sorted(by_key, key=natural_key):
            point = keymap.points[canonical_key]
            for form in _string_list(point, "lookupForms"):
                lookup_forms.setdefault(form, None)
            for level in _string_list(point, "jlptLevels"):
                jlpt.setdefault(level, None)
            for register in _string_list(point, "observedRegisters"):
                registers.setdefault(register, None)
            for signature in _string_list(point, "observedSignatures"):
                signatures.setdefault(signature, None)

        contributions = tuple(c for sense in senses for c in sense.contributions)
        entries.append(
            UnifiedEntry(
                entry_id=entry_id_for(variety, era, bucket_key),
                kind=KIND_POINT,
                expression=expression,
                reading=_entry_reading(contributions, expression),
                axes={"variety": variety, "era": era},
                bucket_key=bucket_key,
                lookup_forms=tuple(sorted(lookup_forms)),
                senses=tuple(senses),
                # Conflicting levels are carried side by side, never reconciled:
                # 158 buckets disagree across sources and both readings are true
                # statements about their own source.
                jlpt_levels=tuple(sorted(jlpt)),
                registers=tuple(sorted(registers)),
                signatures=tuple(sorted(signatures)),
            )
        )

    # Fail closed on a stale overlay: every declared correction whose SOURCE is in
    # this corpus must have matched at least one assembled contribution. A
    # correction that matched nothing while its source is present means the
    # extraction drifted or the correction is obsolete; ignoring it would let the
    # overlay claim to fix a defect it no longer touches.
    #
    # A correction for a source that contributes NO rows here is out of scope, not
    # stale. A corpus is legitimately narrower than the overlay after a
    # single-source stage run, or in a checkout that has acquired only some
    # sources. Failing there would block the build for the wrong reason while
    # telling us nothing about drift. Scoping keeps the gate's full bite on every
    # source actually in the corpus.
    present_sources = {source for source, _ in rows}
    unmatched = [
        c
        for c in corrections
        if c.match_key not in correction_hits and c.source in present_sources
    ]
    if unmatched:
        raise StaleCorrection(unmatched)

    # 4. Redirect entries for every written form that is not a headword.
    redirects, redirect_stats = build_redirects(rows, entries, labels)
    entries.extend(redirects)

    entries.sort(key=lambda entry: (natural_key(entry.expression), entry.entry_id))
    stats = summarise(
        entries,
        rows=rows,
        labels=labels,
        collapsed_duplicate_rows=collapsed_duplicate_rows,
        duplicate_examples_removed=duplicate_examples_removed,
        redirect_stats=redirect_stats,
    )
    return entries, stats

def entry_id_for(variety: str, era: str, bucket_key: str) -> str:
    """Stable id for a unified entry.

    The partition scope is only spelled out when it is not the default, matching
    the keymap's own key convention, so the common case stays readable and a
    classical point can never collide with its modern homograph.
    """
    scope = "" if (variety, era) == ("standard", "modern") else f"{variety}/{era}:"
    return f"{scope}{bucket_key}"


def redirect_id_for(form: str) -> str:
    return f"->{form}"


# --------------------------------------------------------------------------
# redirects: keep every written form findable
# --------------------------------------------------------------------------


def build_redirects(
    rows: list[tuple[str, dict[str, object]]],
    entries: list[UnifiedEntry],
    labels: dict[str, str],
) -> tuple[list[UnifiedEntry], dict[str, object]]:
    """Emit a redirect entry for every written form that is not a headword.

    750 of the corpus's 2,419 written forms are not a unified entry's headword.
    Dropping them would silently remove lookups a user can perform against the
    sources today, so each becomes a small entry pointing at the form that holds
    the substance. Three resolution routes, in decreasing directness:

    1. **declared** (702 real forms) — the producer's own `aliasOf`/
       `canonicalExpression`/`seeAlso` or an internal `?query=` link names a form
       that IS reachable;
    2. **folded** (2) — the form has no usable declaration but its own rows were
       folded into an entry written differently (`たい…` -> `たい`), so the entry
       that absorbed it is the target. This route is small only because
       `declared` is tried first and absorbs 587 forms that would also have
       resolved this way;
    3. **reading** (41) — the declared target is only spelled in kana while
       entries are keyed on kanji. Resolved ONLY when that reading lands in
       exactly one entry.

    Anything left is reported as `unresolved` (5 forms: 2 whose reading is
    ambiguous across two entries, 3 with no declared target at all) rather than
    attached to a guess.
    """
    by_expression: dict[str, UnifiedEntry] = {}
    by_form: dict[str, set[str]] = defaultdict(set)
    by_reading: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        by_expression.setdefault(entry.expression, entry)
        for form in entry.lookup_forms:
            by_form[form].add(entry.expression)
        for contribution in entry.contributions:
            if contribution.reading:
                by_reading[contribution.reading].add(entry.expression)

    # Every written form the corpus ships, with the rows that write it.
    forms: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for source, record in rows:
        forms[str(record["expression"])].append((source, record))

    redirects: list[UnifiedEntry] = []
    basis_counts: Counter[str] = Counter()
    unresolved: list[dict[str, object]] = []

    for form in sorted(forms, key=natural_key):
        if form in by_expression:
            continue
        members = forms[form]
        declared: list[str] = []
        for source, record in members:
            for target in alias_targets(record):
                if target != form and target not in declared:
                    declared.append(target)

        targets: list[str] = []
        basis = ""
        # 1. declared target that resolves to a real entry
        for target in declared:
            for expression in sorted(by_form.get(target, ())):
                if expression not in targets:
                    targets.append(expression)
        if targets:
            basis = "declared"
        else:
            # 2. this form's own rows were folded into a differently-written entry
            folded = sorted(
                {
                    expression
                    for expression in by_form.get(form, ())
                    if expression != form
                }
            )
            if folded:
                targets = folded
                basis = "folded"
            else:
                # 3. a kana-only declared target, resolved through readings and
                #    accepted only when it is unambiguous.
                candidates: set[str] = set()
                for target in declared:
                    candidates |= by_reading.get(target, set())
                if len(candidates) == 1:
                    targets = sorted(candidates)
                    basis = "reading"
                else:
                    unresolved.append(
                        {
                            "expression": form,
                            "declaredTargets": declared,
                            "readingCandidates": sorted(candidates),
                            "sources": sorted({source for source, _ in members}),
                        }
                    )
                    continue

        basis_counts[basis] += 1
        redirect_sources = sorted({source for source, _ in members})
        # NOT display_headword'd, deliberately. A redirect exists because `form` is
        # a DIFFERENT written form from its target; stripping the leading
        # placeholder here collapses `〜あげく` onto the point `あげく` that it
        # redirects to, which measured 1,061 self-redirects (headword listed among
        # its own targets) and 912 redirect headwords colliding with a point
        # headword, against 0 of each before. The point path strips because its
        # headword is the only surface for that entry; a redirect's whole purpose
        # is to be the other spelling, and its tilde-free form is already reachable
        # through the point it names.
        reading = ""
        for source, record in members:
            candidate = record.get("reading")
            if isinstance(candidate, str) and candidate and candidate != form:
                reading = candidate
                break
        redirects.append(
            UnifiedEntry(
                entry_id=redirect_id_for(form),
                kind=KIND_REDIRECT,
                expression=form,
                reading=reading or None,
                axes={"variety": "standard", "era": "modern"},
                bucket_key=form,
                lookup_forms=(form,),
                redirect_targets=tuple(targets),
                redirect_basis=basis,
                redirect_sources=tuple(
                    labels.get(source, source) for source in redirect_sources
                ),
            )
        )

    stats = {
        "emitted": len(redirects),
        "byBasis": dict(sorted(basis_counts.items())),
        "unresolved": unresolved,
        "unresolvedCount": len(unresolved),
    }
    return redirects, stats


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------


def example_to_json(example: Example) -> dict[str, object]:
    payload: dict[str, object] = {"japanese": example.japanese}
    if example.english:
        payload["english"] = example.english
    if example.highlight:
        payload["highlight"] = list(example.highlight)
    # Written only when true, so an AI-flagged sentence is visible in a diff
    # rather than buried among thousands of `false`s.
    if example.ai_generated:
        payload["aiGenerated"] = True
    return payload


def contribution_to_json(contribution: Contribution) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": contribution.source,
        "sourceId": contribution.source_id,
        # The unique machine identity of the source row. Written next to the
        # non-unique human handle so a reader can tell them apart at a glance.
        "rowUid": contribution.row_uid,
        "sourceLabel": contribution.source_label,
        "canonicalKey": contribution.canonical_key,
        "expression": contribution.expression,
    }
    for name, key in (
        ("reading", "reading"),
        ("meaning", "meaning"),
        ("structure", "structure"),
        ("nuance", "nuance"),
        ("explanation", "explanation"),
        ("notes", "notes"),
        ("jlpt", "jlpt"),
    ):
        value = getattr(contribution, name)
        if value:
            payload[key] = value
    if contribution.examples:
        payload["examples"] = [example_to_json(e) for e in contribution.examples]
    if contribution.tags:
        payload["tags"] = list(contribution.tags)
    # The AI channel keeps its own top-level key so no consumer can mistake it
    # for human-authored substance.
    if contribution.ai_generated:
        payload["aiGenerated"] = contribution.ai_generated
    if contribution.provenance:
        payload["provenance"] = contribution.provenance
    if contribution.duplicate_examples_removed:
        payload["duplicateExamplesRemoved"] = contribution.duplicate_examples_removed
    return payload


def entry_to_json(entry: UnifiedEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        "entryId": entry.entry_id,
        "kind": entry.kind,
        "expression": entry.expression,
        "axes": dict(entry.axes),
        "bucketKey": entry.bucket_key,
        "lookupForms": list(entry.lookup_forms),
    }
    if entry.reading:
        payload["reading"] = entry.reading
    if entry.senses:
        payload["senses"] = [
            {
                "canonicalKey": sense.canonical_key,
                "disambiguator": sense.disambiguator,
                "expression": sense.expression,
                "contributions": [contribution_to_json(c) for c in sense.contributions],
            }
            for sense in entry.senses
        ]
    if entry.jlpt_levels:
        payload["jlptLevels"] = list(entry.jlpt_levels)
    if entry.registers:
        payload["observedRegisters"] = list(entry.registers)
    if entry.signatures:
        payload["observedSignatures"] = list(entry.signatures)
    if entry.redirect_targets:
        payload["redirectTargets"] = list(entry.redirect_targets)
    if entry.redirect_basis:
        payload["redirectBasis"] = entry.redirect_basis
    if entry.redirect_sources:
        payload["redirectSources"] = list(entry.redirect_sources)
    return payload


def example_from_json(payload: dict[str, object]) -> Example:
    highlight = payload.get("highlight") or ()
    if not isinstance(highlight, (list, tuple)):
        raise MalformedPayload("an example's `highlight` must be an array")
    japanese = payload.get("japanese")
    if not isinstance(japanese, str) or not japanese.strip():
        raise MalformedPayload("an example needs a non-empty `japanese`")
    english = payload.get("english")
    return Example(
        japanese=japanese,
        english=english if isinstance(english, str) and english else None,
        highlight=tuple(str(item) for item in highlight),
        ai_generated=bool(payload.get("aiGenerated")),
    )


def contribution_from_json(payload: dict[str, object]) -> Contribution:
    if not isinstance(payload, dict):
        raise MalformedPayload("a contribution payload must be an object")
    examples = payload.get("examples") or ()
    if not isinstance(examples, (list, tuple)):
        raise MalformedPayload("a contribution's `examples` must be an array")
    tags = payload.get("tags") or ()
    if not isinstance(tags, (list, tuple)):
        raise MalformedPayload("a contribution's `tags` must be an array")
    removed = payload.get("duplicateExamplesRemoved") or 0
    if not isinstance(removed, int) or isinstance(removed, bool) or removed < 0:
        raise MalformedPayload("`duplicateExamplesRemoved` must be a non-negative integer")
    return Contribution(
        source=str(payload["source"]),
        source_id=str(payload.get("sourceId") or ""),
        row_uid=str(payload.get("rowUid") or ""),
        source_label=str(payload.get("sourceLabel") or payload["source"]),
        canonical_key=str(payload.get("canonicalKey") or ""),
        expression=str(payload["expression"]),
        reading=_text_or_none(payload.get("reading")),
        meaning=_text_or_none(payload.get("meaning")),
        structure=_text_or_none(payload.get("structure")),
        nuance=_text_or_none(payload.get("nuance")),
        explanation=_text_or_none(payload.get("explanation")),
        notes=_text_or_none(payload.get("notes")),
        jlpt=_text_or_none(payload.get("jlpt")),
        examples=tuple(
            example_from_json(item) if isinstance(item, dict) else _bad_example(item)
            for item in examples
        ),
        tags=tuple(str(tag) for tag in tags),
        ai_generated=_mapping(payload.get("aiGenerated"), "aiGenerated"),
        provenance=_mapping(payload.get("provenance"), "provenance"),
        duplicate_examples_removed=removed,
    )


def _bad_example(item: object) -> Example:
    raise MalformedPayload(f"each example must be an object, got {type(item).__name__}")


def entry_from_json(payload: object) -> UnifiedEntry:
    if not isinstance(payload, dict):
        raise MalformedPayload("a unified entry payload must be an object")
    axes = _mapping(payload.get("axes"), "axes")
    senses: list[Sense] = []
    for item in payload.get("senses") or ():
        if not isinstance(item, dict):
            raise MalformedPayload("each sense must be an object")
        contributions = item.get("contributions") or ()
        if not isinstance(contributions, (list, tuple)) or not contributions:
            raise MalformedPayload("a sense must carry at least one contribution")
        senses.append(
            Sense(
                canonical_key=str(item.get("canonicalKey") or ""),
                disambiguator=str(item.get("disambiguator") or ""),
                expression=str(item.get("expression") or payload["expression"]),
                contributions=tuple(contribution_from_json(c) for c in contributions),
            )
        )
    return UnifiedEntry(
        entry_id=str(payload["entryId"]),
        kind=str(payload["kind"]),
        expression=str(payload["expression"]),
        reading=_text_or_none(payload.get("reading")),
        axes={"variety": str(axes.get("variety") or ""), "era": str(axes.get("era") or "")},
        bucket_key=str(payload.get("bucketKey") or ""),
        lookup_forms=tuple(str(f) for f in payload.get("lookupForms") or ()),
        senses=tuple(senses),
        jlpt_levels=tuple(str(v) for v in payload.get("jlptLevels") or ()),
        registers=tuple(str(v) for v in payload.get("observedRegisters") or ()),
        signatures=tuple(str(v) for v in payload.get("observedSignatures") or ()),
        redirect_targets=tuple(str(v) for v in payload.get("redirectTargets") or ()),
        redirect_basis=str(payload.get("redirectBasis") or ""),
        redirect_sources=tuple(str(v) for v in payload.get("redirectSources") or ()),
    )


# --------------------------------------------------------------------------
# merge statistics
# --------------------------------------------------------------------------


def summarise(
    entries: list[UnifiedEntry],
    *,
    rows: list[tuple[str, dict[str, object]]],
    labels: dict[str, str],
    collapsed_duplicate_rows: int,
    duplicate_examples_removed: int,
    redirect_stats: dict[str, object],
) -> dict[str, object]:
    """Merge statistics, named for what they actually measure.

    Every count here is a fact about this build's inputs and outputs. Nothing is
    a quality score, a probability, or an estimate.
    """
    points = [e for e in entries if e.kind == KIND_POINT]
    redirects = [e for e in entries if e.kind == KIND_REDIRECT]
    contributions = [c for e in points for c in e.contributions]

    per_source: dict[str, dict[str, int]] = {}
    for source in sorted(labels):
        own = [c for c in contributions if c.source == source]
        per_source[source] = {
            "rows": sum(1 for s, _ in rows if s == source),
            "contributions": len(own),
            "examples": sum(len(c.examples) for c in own),
            "entries": sum(1 for e in points if source in e.sources),
        }

    sources_per_entry = Counter(len(e.sources) for e in points)
    senses_per_entry = Counter(len(e.senses) for e in points)

    def _histogram(counter: Counter[int]) -> dict[str, int]:
        """Histogram with STRING keys.

        JSON object keys are always strings, so an int-keyed histogram would make
        the returned dict and the written stats file disagree on type -- a
        consumer comparing them (or asserting a round trip) sees a spurious
        difference. Serialising the key here keeps one shape everywhere.
        """
        return {str(key): counter[key] for key in sorted(counter)}

    ai_contributions = sum(1 for c in contributions if c.ai_generated)
    ai_examples = sum(
        1 for c in contributions for example in c.examples if example.ai_generated
    )

    return {
        "corpus": {
            "sourceRows": len(rows),
            "declaredAliasRows": sum(1 for _, r in rows if is_declared_alias(r)),
            "collapsedDuplicateRows": collapsed_duplicate_rows,
            "sources": sorted(labels),
            "sourceLabels": dict(sorted(labels.items())),
        },
        "unified": {
            "entries": len(entries),
            "pointEntries": len(points),
            "redirectEntries": len(redirects),
            "contributions": len(contributions),
            "senses": sum(len(e.senses) for e in points),
            "multiSourceEntries": sum(1 for e in points if len(e.sources) > 1),
            "singleSourceEntries": sum(1 for e in points if len(e.sources) == 1),
            "multiSenseEntries": sum(1 for e in points if len(e.senses) > 1),
            "sourcesPerEntry": _histogram(sources_per_entry),
            "sensesPerEntry": _histogram(senses_per_entry),
            "distinctLookupForms": len({f for e in entries for f in e.lookup_forms}),
        },
        "examples": {
            "total": sum(len(c.examples) for c in contributions),
            "withEnglish": sum(
                1 for c in contributions for e in c.examples if e.english
            ),
            "withHighlight": sum(
                1 for c in contributions for e in c.examples if e.highlight
            ),
            "sameSourceDuplicatesRemoved": duplicate_examples_removed,
            "dedupeScope": "per-source-within-entry",
        },
        "furigana": {
            "entriesWithReading": sum(1 for e in entries if e.reading),
            "contributionsWithReading": sum(1 for c in contributions if c.reading),
        },
        "jlpt": {
            "entriesWithLevel": sum(1 for e in points if e.jlpt_levels),
            # Conflicts are REPORTED, never reconciled: both statements are true
            # about their own source, so the card shows them per source.
            "entriesWithConflictingLevels": sum(
                1 for e in points if len(e.jlpt_levels) > 1
            ),
            "policy": "levels are carried per source and never reconciled",
        },
        "aiChannel": {
            "contributionsWithAiFields": ai_contributions,
            "aiFlaggedExamples": ai_examples,
            # Stated explicitly so a zero is never read as "the channel is
            # missing". No source currently ships AI fields; the channel is
            # preserved structurally and proven by synthetic fixtures.
            "channelPreserved": True,
            "note": (
                "no current source declares AI-generated fields; the channel is "
                "carried separately from human-authored substance and is covered "
                "by synthetic fixtures rather than corpus evidence"
            ),
        },
        "media": {
            "references": 0,
            "note": (
                "no source ships media references (extractors drop `img` rather "
                "than package a dangling reference); media handling is structural "
                "and fixture-covered, not corpus-observed"
            ),
        },
        "redirects": redirect_stats,
        "perSource": per_source,
    }


# --------------------------------------------------------------------------
# stage entry point
# --------------------------------------------------------------------------


def write_unified(
    entries: list[UnifiedEntry], path: pathlib.Path
) -> tuple[int, str]:
    """Write the unified dataset as JSONL, one entry per line.

    JSONL because the dataset is a stream of independent entries: a reviewer can
    grep one headword, a diff shows entry-level churn instead of one 12 MB line,
    and a consumer can process it without loading the whole corpus. Each line is
    canonical JSON, so the file is byte-reproducible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [dump_json(entry_to_json(entry)) for entry in entries]
    payload = "".join(f"{line}\n" for line in lines)
    path.write_text(payload, encoding="utf-8")
    return len(payload.encode("utf-8")), content_hash([entry_to_json(e) for e in entries])


def read_unified(path: pathlib.Path) -> list[UnifiedEntry]:
    """Read a unified JSONL dataset back into entries."""
    entries: list[UnifiedEntry] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(entry_from_json(load_json(line)))
        except MalformedPayload as error:
            raise MalformedPayload(f"{path}:{number}: {error}") from error
    return entries


def run_unify(
    *,
    extracted_dir: pathlib.Path,
    keymap_path: pathlib.Path = DEFAULT_KEYMAP_PATH,
    unified_path: pathlib.Path = DEFAULT_UNIFIED_PATH,
    stats_path: pathlib.Path = DEFAULT_STATS_PATH,
) -> dict[str, object]:
    """Run the merge stage end to end and write both artifacts."""
    rows, labels = load_extracted(extracted_dir)
    keymap = load_keymap(keymap_path)
    entries, stats = unify(rows, keymap, labels)

    byte_count, digest = write_unified(entries, unified_path)
    stats["artifact"] = {
        "path": str(unified_path),
        "byteCount": byte_count,
        "contentHash": digest,
        "keymapPath": str(keymap_path),
        "keymapContentHash": content_hash(
            load_json(keymap_path.read_text(encoding="utf-8"))
        ),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(dump_json(stats) + "\n", encoding="utf-8")
    return stats


# --------------------------------------------------------------------------
# projection onto the bank generator's input contract
# --------------------------------------------------------------------------


def to_grammar_point(
    contribution: Contribution, *, expression: str, variants: tuple[str, ...] = ()
) -> GrammarPoint:
    """Project one contribution back onto the stage-boundary `GrammarPoint`.

    The bank generator consumes `MergedEntry`/`GrammarPoint`, and it must keep
    doing so: the unified dataset is the merge stage's reviewable artifact, not a
    reason to rewrite the renderer. Attribution the projection would otherwise
    lose (`sourceLabel`, the entry's own key, the sense that held it) is folded
    into `provenance`, where the renderer already looks for per-source detail.
    """
    provenance = dict(contribution.provenance)
    provenance.setdefault("sourceLabel", contribution.source_label)
    provenance["canonicalKey"] = contribution.canonical_key
    return GrammarPoint(
        source=contribution.source,
        source_id=contribution.source_id or contribution.expression,
        row_uid=contribution.row_uid,
        expression=expression,
        variants=variants,
        reading=contribution.reading,
        meaning=contribution.meaning,
        structure=contribution.structure,
        nuance=contribution.nuance,
        explanation=contribution.explanation,
        notes=contribution.notes,
        jlpt=contribution.jlpt if contribution.jlpt in JLPT_LEVELS else None,
        examples=contribution.examples,
        tags=contribution.tags,
        ai_generated=dict(contribution.ai_generated),
        provenance=provenance,
    )


def to_merged_entries(entries: list[UnifiedEntry]) -> list["MergedEntry"]:
    """Project the unified dataset onto the bank generator's input.

    Both entry kinds are projected. A redirect has no contributions of its own,
    so it is projected as a single alias-shaped point whose `aliasOf` names the
    entry holding the substance — exactly the shape `banks._crossreference_block`
    already renders as a clickable `see <form>` pointer. Dropping redirects here
    would silently undo the findability work the merge just did.
    """
    from .merge import MergedEntry

    merged: list[MergedEntry] = []
    for entry in entries:
        variants = tuple(f for f in entry.lookup_forms if f != entry.expression)
        if entry.kind == KIND_POINT:
            contributions = [
                to_grammar_point(c, expression=entry.expression, variants=variants)
                for c in entry.contributions
            ]
        else:
            target = entry.redirect_targets[0] if entry.redirect_targets else ""
            label = entry.redirect_sources[0] if entry.redirect_sources else ""
            contributions = [
                GrammarPoint(
                    source=entry.redirect_basis or "redirect",
                    source_id=entry.entry_id,
                    expression=entry.expression,
                    variants=variants,
                    reading=entry.reading,
                    provenance={
                        "entryShape": "alias-redirect",
                        "aliasOf": target,
                        "sourceLabel": label,
                        "redirectBasis": entry.redirect_basis,
                    },
                )
            ]
        merged.append(
            MergedEntry(
                expression=entry.expression,
                variants=variants,
                contributions=contributions,
            )
        )
    return merged


__all__ = [
    "Contribution",
    "DEFAULT_KEYMAP_PATH",
    "DEFAULT_STATS_PATH",
    "DEFAULT_UNIFIED_PATH",
    "KIND_POINT",
    "KIND_REDIRECT",
    "SUPPORTED_KEYMAP_SCHEMA",
    "Keymap",
    "Sense",
    "StaleKeymap",
    "UnifiedEntry",
    "build_contribution",
    "build_redirects",
    "choose_headword",
    "display_headword",
    "contribution_from_json",
    "contribution_to_json",
    "dedupe_examples",
    "ensure_consistent",
    "entry_from_json",
    "entry_id_for",
    "entry_to_json",
    "example_from_json",
    "example_to_json",
    "load_extracted",
    "load_keymap",
    "natural_key",
    "parse_keymap",
    "read_unified",
    "redirect_id_for",
    "run_unify",
    "summarise",
    "to_grammar_point",
    "to_merged_entries",
    "unify",
    "write_unified",
]
