"""Cross-source grammar-point matching: which source rows are the SAME point?

This module is the single authority for cross-source alignment. It reads the
normalized per-source artifacts in `data/extracted/*.json` and emits
`data/merge/keymap.json`: an explicit assignment of every source row to a
canonical grammar point, plus a report of the ambiguous cases and exactly why
each was folded or refused.

The design bias is asymmetric on purpose. A missed fold shows the user the same
point twice, which is untidy. A wrong fold silently merges two different grammar
points into one card and *destroys* a distinction the source authors made
deliberately. So every rule below either folds on positive attested evidence or
refuses, and no similarity score is ever allowed to outvote a refusal.

Pipeline, in order:

1. **Partition.** Scope every row by `(variety, era)` (`bugd.axes`). Rows that
   disagree are never candidates, so no later rule can fold a classical 如し onto
   a modern ようだ. Register does *not* partition — measured against the corpus it
   is prose commentary about a point far more often than a property of it, and
   partitioning on it splits correct folds. It is recorded and reported instead.

2. **Demote producer-declared aliases.** 1,167 of 4,972 rows are the producers'
   own redirect/synthetic-lookup rows, not independent opinions. Counting them as
   corroboration would let one source appear to agree with itself. Demotion is
   proven lossless before it is applied: `donna_toki`'s 421 alias rows have empty
   bodies, and `nihongo_no_sensei`'s 746 synthetic rows are byte-identical to
   their own `canonicalExpression` row. They become lookup forms on the point they
   redirect to, never contributors.

3. **Collapse byte-identical rows.** A row's identity is
   `(source, source_id, substance_hash)`. `source_id` alone is *not* unique —
   edewakaru ships `も` eleven times as eleven different senses — so collapsing on
   it would destroy homographs. Collapsing on substance destroys nothing: all 91
   collisions are exact duplicates.

4. **Tier A — partition-scoped bijection.** When a normalized key is claimed by
   several sources and *each* contributes exactly one row, the sources are talking
   about one point: 558 groups. If any source contributes two or more rows to the
   key it is a homograph fan, the correspondence is ambiguous, and the group is
   refused (191 groups) and separated by a source-derived disambiguator.

5. **Tier B — attested variant links.** A producer naming another source's exact
   headword as a variant is evidence, but raw variant edges are unsafe: they
   include polarity flips (`ないことはある` / `ないことはない`) and generic hubs
   (`限りだ` -> `です`). Guarded down to reading-identity or reciprocal links with
   bounded in-degree, then restricted to strictly pairwise edges, 54 survive.
   Transitive closure is rejected outright — it merged 8 rows into one point.

The attachment signature (`bugd.signature`) is deliberately never a fold gate.
Requiring signature equality refuses 540 of 697 correct bijective folds, and
sub-matching inside refused buckets manufactures false ones (`て` "very" onto `て`
"because"). It is recorded as an observed attribute and used only to *separate*
rows that already collide.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib

from .axes import partition_axes, registers
from .jsonio import MalformedPayload, content_hash, load_json
from .normalize import lookup_key, lookup_keys, sentence_key
from .polarity import is_polarity_flip, kana_identity
from .signature import signature, signature_label

#: Fields making up a row's learner-visible substance. Two rows agreeing on all
#: of these are the same row twice, whatever ids the producer gave them.
SUBSTANCE_FIELDS = (
    "expression",
    "reading",
    "meaning",
    "structure",
    "nuance",
    "explanation",
    "notes",
    "jlpt",
)

#: Maximum number of distinct rows that may name a key as their variant before it
#: is treated as a generic hub rather than a specific variant claim. Measured: 2
#: keeps every attested orthographic pair and kills 限りだ->です / それなりに->の.
MAX_VARIANT_IN_DEGREE = 2

#: Shortest key length a Tier B link may involve. One-character keys are particles
#: that appear inside unrelated points.
MIN_TIER_B_KEY_LENGTH = 2

#: Deterministic source precedence for choosing a canonical written form. Ordered
#: by how close the source's headwords are to plain dictionary forms.
SOURCE_PRECEDENCE = (
    "dojg",
    "edewakaru",
    "donna_toki",
    "nihongo_net",
    "nihongo_no_sensei",
)


@dataclasses.dataclass(frozen=True)
class RowId:
    """Total identity of one source row.

    `source_id` is included because it is the producer's own handle and keeps the
    keymap auditable against the source deck; `substance` is included because
    `source_id` is not unique.
    """

    source: str
    source_id: str
    substance: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "sourceId": self.source_id,
            "substanceHash": self.substance,
        }

    @property
    def sort_key(self) -> tuple[int, str, str]:
        try:
            rank = SOURCE_PRECEDENCE.index(self.source)
        except ValueError:
            rank = len(SOURCE_PRECEDENCE)
        return rank, self.source_id, self.substance


def substance_hash(record: dict[str, object]) -> str:
    """Stable hash of a row's learner-visible substance.

    Example sentences are included through `sentence_key` so that whitespace-only
    differences do not manufacture two identities, while a genuinely different
    example set keeps two rows apart.
    """
    body: dict[str, object] = {field: record.get(field) for field in SUBSTANCE_FIELDS}
    examples = record.get("examples") or ()
    if not isinstance(examples, (list, tuple)):
        raise MalformedPayload("record 'examples' must be a list")
    rendered = []
    for example in examples:
        if not isinstance(example, dict) or not isinstance(example.get("japanese"), str):
            raise MalformedPayload("each example needs a 'japanese' string")
        english = example.get("english")
        rendered.append([sentence_key(example["japanese"]), (english or "").strip()])
    body["examples"] = rendered
    return content_hash(body)


def is_declared_alias(record: dict[str, object]) -> bool:
    """True when the producer itself marks the row a redirect, not a point.

    Three shapes are recognised, all producer-declared: an explicit `aliasOf`,
    a `syntheticLookupForm` flag, or `entryShape == "alias-redirect"`. Nothing is
    inferred from a row being short or bodyless.
    """
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return bool(
        provenance.get("aliasOf")
        or provenance.get("syntheticLookupForm")
        or provenance.get("entryShape") == "alias-redirect"
    )


def alias_targets(record: dict[str, object]) -> list[str]:
    """Keys a declared alias row redirects to, in decreasing reliability.

    Explicit producer fields come first, then `?query=` links the producer wrote
    into the row, then declared variants. Everything here is producer-authored;
    no target is guessed from string similarity.
    """
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    candidates: list[str] = []

    for field in ("aliasOf", "canonicalExpression"):
        value = provenance.get(field)
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    links = provenance.get("producerLinks")
    if isinstance(links, (list, tuple)):
        for link in links:
            if isinstance(link, str) and "?query=" in link:
                candidates.append(link.split("?query=")[-1])

    variants = record.get("variants")
    if isinstance(variants, (list, tuple)):
        candidates.extend(variant for variant in variants if isinstance(variant, str))

    keys: list[str] = []
    for candidate in candidates:
        key = lookup_key(candidate)
        if key and key not in keys:
            keys.append(key)
    return keys


def primary_key(record: dict[str, object]) -> str | None:
    """The one normalized key a row is filed under, or None when it has none."""
    expression = record.get("expression")
    if not isinstance(expression, str):
        raise MalformedPayload("record 'expression' must be a string")
    keys = lookup_keys(expression)
    return keys[0] if keys else None


def variant_keys(record: dict[str, object]) -> list[str]:
    """Declared variant keys that are not just the row's own lookup forms."""
    own = set(lookup_keys(str(record.get("expression") or "")))
    variants = record.get("variants")
    if not isinstance(variants, (list, tuple)):
        return []
    keys: list[str] = []
    for variant in variants:
        if not isinstance(variant, str):
            continue
        key = lookup_key(variant)
        if key and key not in own and key not in keys:
            keys.append(key)
    return keys


@dataclasses.dataclass
class Row:
    """One substantive source row, with everything matching needs precomputed."""

    row_id: RowId
    record: dict[str, object]
    key: str
    axes: tuple[str, str]

    @property
    def expression(self) -> str:
        return str(self.record.get("expression") or "")

    @property
    def bucket(self) -> tuple[tuple[str, str], str]:
        """The partition-scoped key this row is filed under."""
        return self.axes, self.key

    @property
    def signature(self) -> frozenset[str] | None:
        structure = self.record.get("structure")
        return signature(structure if isinstance(structure, str) else None)

    @property
    def reading_identity(self) -> str:
        reading = self.record.get("reading")
        return kana_identity(reading if isinstance(reading, str) else None)


@dataclasses.dataclass
class AliasRow:
    """A producer-declared redirect row, demoted to a lookup form."""

    row_id: RowId
    record: dict[str, object]
    targets: list[str]
    axes: tuple[str, str]
    resolution: str = "unresolved"
    resolved_key: str | None = None

    @property
    def expression(self) -> str:
        return str(self.record.get("expression") or "")


def load_sources(extracted_dir: pathlib.Path) -> dict[str, list[dict[str, object]]]:
    """Read every normalized per-source artifact, keyed by source name."""
    if not extracted_dir.is_dir():
        raise MalformedPayload(f"no extracted sources at {extracted_dir}")
    sources: dict[str, list[dict[str, object]]] = {}
    for path in sorted(extracted_dir.glob("*.json")):
        payload = load_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise MalformedPayload(f"{path.name} must be a JSON object")
        name = payload.get("source")
        points = payload.get("points")
        if not isinstance(name, str) or not name.strip():
            raise MalformedPayload(f"{path.name} must carry a non-empty 'source'")
        if not isinstance(points, list):
            raise MalformedPayload(f"{path.name} must carry a 'points' list")
        if name in sources:
            raise MalformedPayload(f"two artifacts both claim source {name!r}")
        sources[name] = points
    if not sources:
        raise MalformedPayload(f"no *.json artifacts in {extracted_dir}")
    return sources


def partition_rows(
    sources: dict[str, list[dict[str, object]]],
) -> tuple[list[Row], list[AliasRow], dict[str, int]]:
    """Split every source row into substantive rows and demoted alias rows.

    Byte-identical rows within one source collapse onto one `RowId` here, which is
    where duplicate deck rows stop being able to corroborate each other.
    """
    substantive: dict[RowId, Row] = {}
    aliases: dict[RowId, AliasRow] = {}
    stats: collections.Counter[str] = collections.Counter()

    for name in sorted(sources):
        for record in sources[name]:
            if not isinstance(record, dict):
                raise MalformedPayload(f"source {name!r} contains a non-object point")
            source_id = record.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise MalformedPayload(f"source {name!r} has a row without a source_id")
            row_id = RowId(name, source_id, substance_hash(record))
            axes = partition_axes(record)
            stats["rows"] += 1

            if is_declared_alias(record):
                stats["aliasRows"] += 1
                if row_id in aliases:
                    stats["aliasRowsCollapsed"] += 1
                    continue
                aliases[row_id] = AliasRow(row_id, record, alias_targets(record), axes)
                continue

            key = primary_key(record)
            if key is None:
                # Fail closed rather than dropping substance: a row that cannot be
                # keyed is a normalization defect, not a row to discard.
                raise MalformedPayload(
                    f"{name}:{source_id!r} produced no lookup key from {record.get('expression')!r}"
                )
            if row_id in substantive:
                stats["duplicateRowsCollapsed"] += 1
                continue
            substantive[row_id] = Row(row_id, record, key, axes)

    # A handful of rows are shipped by one source both flagged and unflagged with
    # byte-identical substance (measured: 6 in nihongo_no_sensei, e.g. ようが).
    # The substantive copy is the real point, so drop the alias twin — keeping both
    # would let one row appear as a contributor and as a redirect to itself.
    for row_id in list(aliases):
        if row_id in substantive:
            del aliases[row_id]
            stats["aliasTwinsOfSubstantiveDropped"] += 1

    stats["substantiveRows"] = len(substantive)
    stats["aliasRowsKept"] = len(aliases)
    return list(substantive.values()), list(aliases.values()), dict(stats)


def index_buckets(rows: list[Row]) -> dict[tuple[tuple[str, str], str], dict[str, list[Row]]]:
    """Group rows by partition-scoped key, then by source within each key."""
    buckets: dict[tuple[tuple[str, str], str], dict[str, list[Row]]] = {}
    for row in rows:
        per_source = buckets.setdefault(row.bucket, {})
        per_source.setdefault(row.row_id.source, []).append(row)
    return buckets


def classify_buckets(
    buckets: dict[tuple[tuple[str, str], str], dict[str, list[Row]]],
) -> tuple[list, list, list]:
    """Split buckets into Tier A folds, cross-source collisions, and single-source.

    Three genuinely different situations, which must not be conflated:

    * **fold** — several sources, each contributing exactly one row. A bijection:
      the sources are describing one point, so the rows fold.
    * **cross-source collision** — several sources, at least one contributing two
      or more rows. Which of that source's senses does the other source's row
      match? Unanswerable from the data, so the fold is refused.
    * **single-source** — one source only. Nothing to align. If that source
      contributed several rows it is a homograph fan (edewakaru's eleven `も`),
      which needs a disambiguator but is not a cross-source refusal.
    """
    folds, collisions, single = [], [], []
    for bucket in sorted(buckets, key=lambda item: (item[0], item[1])):
        per_source = buckets[bucket]
        multi = any(len(rows) > 1 for rows in per_source.values())
        if len(per_source) == 1:
            single.append(bucket)
        elif multi:
            collisions.append(bucket)
        else:
            folds.append(bucket)
    return folds, collisions, single


def variant_in_degree(rows: list[Row]) -> collections.Counter[str]:
    """How many distinct rows name each key as a variant.

    A key many unrelated rows point at is a generic hub (`です`, `の`), not a
    specific variant claim, so in-degree bounds Tier B.
    """
    degree: collections.Counter[str] = collections.Counter()
    for row in rows:
        for key in variant_keys(row.record):
            degree[key] += 1
    return degree


@dataclasses.dataclass(frozen=True)
class VariantLink:
    """One accepted Tier B edge: two rows the producers attest are one point."""

    left: RowId
    right: RowId
    left_key: str
    right_key: str
    reason: str

    @property
    def ends(self) -> frozenset[RowId]:
        return frozenset({self.left, self.right})

    def as_dict(self) -> dict[str, object]:
        return {
            "left": self.left.as_dict(),
            "leftKey": self.left_key,
            "right": self.right.as_dict(),
            "rightKey": self.right_key,
            "reason": self.reason,
        }


@dataclasses.dataclass(frozen=True)
class RefusedLink:
    """One rejected Tier B edge and the guard that rejected it."""

    left_expression: str
    right_expression: str
    left_key: str
    right_key: str
    guard: str

    def as_dict(self) -> dict[str, object]:
        return {
            "leftExpression": self.left_expression,
            "rightExpression": self.right_expression,
            "leftKey": self.left_key,
            "rightKey": self.right_key,
            "guard": self.guard,
        }


def propose_variant_links(
    rows: list[Row],
    buckets: dict[tuple[tuple[str, str], str], dict[str, list[Row]]],
) -> tuple[list[VariantLink], list[RefusedLink]]:
    """Tier B: accept producer-attested variant edges that survive every guard.

    A candidate exists when a row declares a variant whose normalized key is
    owned, inside the same partition, by exactly one row of exactly one *other*
    source. That unambiguous-target requirement is itself a guard: a variant
    pointing into a homograph fan is not a usable claim.

    Guards, each measured against the real corpus:

    * **polarity** — refuses `ないことはある` / `ないことはない` and
      `と言ったらある` / `といったらない`, which the producers really do list as
      each other's variants;
    * **in-degree** — refuses generic hubs (`限りだ` -> `です`, `それなりに` -> `の`);
    * **key length** — refuses single-character particle keys;
    * **evidence** — requires either identical kana reading (one point spelled two
      ways: `今更`/`いまさら`) or a reciprocal declaration from the other row. A
      one-way link with a different reading is a *related* point, not the same one.
    """
    degree = variant_in_degree(rows)
    by_id = {row.row_id: row for row in rows}
    accepted: dict[frozenset[RowId], VariantLink] = {}
    refused: list[RefusedLink] = []

    for row in sorted(rows, key=lambda item: item.row_id.sort_key):
        for key in variant_keys(row.record):
            per_source = buckets.get((row.axes, key)) or {}
            others = {
                name: found
                for name, found in per_source.items()
                if name != row.row_id.source
            }
            other = _link_target(row, others)
            if other is None:
                continue

            reciprocal = row.key in variant_keys(other.record)
            guard = _link_guard(row, other, key, degree, reciprocal)
            if guard is not None:
                refused.append(
                    RefusedLink(row.expression, other.expression, row.key, key, guard)
                )
                continue

            reason = (
                "reading-identity"
                if row.reading_identity and row.reading_identity == other.reading_identity
                else "reciprocal"
            )
            ends = frozenset({row.row_id, other.row_id})
            if len(ends) != 2:
                continue
            previous = accepted.get(ends)
            # Both directions of one undirected edge can be observed; the stronger
            # reason wins so the report names the real evidence.
            if previous is None or (
                previous.reason == "reciprocal" and reason == "reading-identity"
            ):
                accepted[ends] = VariantLink(row.row_id, other.row_id, row.key, key, reason)

    strict, chained = _restrict_to_pairwise(accepted, by_id)
    refused.extend(chained)
    return strict, refused


def _link_target(row: Row, others: dict[str, list[Row]]) -> Row | None:
    """The one row a variant claim can point at, or None when it is ambiguous.

    A variant key must resolve to a single row of a single *other* source. Where
    exactly one other source owns the bucket that is immediate.

    Where SEVERAL other sources own it, the bucket is not automatically a
    homograph fan: several producers listing the same kana headword is
    corroboration. The problem is that only five of the ten sources state a
    reading at all -- 2,757 of 7,896 rows have none (bunpou 534/534, bunpro
    964/964, imabi 494/494, yokubi 132/132, ninjal 633/800) -- so 791 of 2,985
    buckets mix reading-bearing and reading-silent rows. Requiring every row in
    the bucket to agree on a reading therefore let any reading-less source
    permanently block orthographic folding into it: `や否や` stopped folding with
    `やいなや` the moment bunpou/511 joined that bucket beside donna_toki.

    Two looser rules were measured and rejected. Treating a missing reading as
    agreement proposes 208 extra edges including outright polarity errors
    (`てはいく` <-> `てはいけない`, `なければなる` <-> `なければならない`) and still nets
    zero after the pairwise check while losing the `に即して`/`に則して` pair.
    Linking to a bucket representative re-points existing edges and loses
    `に反する`/`に反して` and `に応じた`/`に応じて`.

    So require positive evidence on the endpoint actually linked: exactly one row
    states the proposer's own reading, and every other row there states none, so
    nothing contradicts. A row stating a DIFFERENT reading still refuses the
    claim. Measured on the full corpus this adds 10 edges, all genuine kanji/kana
    spellings of one point (`や否や`/`やいなや`, `甲斐`/`かい`, `の内`/`のうち`,
    `振る`/`ぶる`, `抜く`/`ぬく`, `恐れがある`/`おそれがある`, ...) and loses none. The
    `には当たる`/`にはあたらない` polarity ambiguity is still refused, by the existing
    strict-pairwise degree check.
    """
    if not others:
        return None
    if len(others) == 1:
        (_, found), = others.items()
        return found[0] if len(found) == 1 else None
    if any(len(found) != 1 for found in others.values()):
        # A source contributing two rows to one bucket IS a homograph fan.
        return None
    if not row.reading_identity:
        return None
    candidates = [found[0] for found in others.values()]
    matching = [r for r in candidates if r.reading_identity == row.reading_identity]
    silent = [r for r in candidates if not r.reading_identity]
    if len(matching) != 1 or len(matching) + len(silent) != len(candidates):
        return None
    return matching[0]


def _link_guard(
    row: Row,
    other: Row,
    key: str,
    degree: collections.Counter[str],
    reciprocal: bool,
) -> str | None:
    """The guard refusing this edge, or None when every guard passes."""
    if is_polarity_flip(row.key, key):
        return "polarity-flip"
    if degree[key] > MAX_VARIANT_IN_DEGREE:
        return "generic-hub"
    if len(row.key) < MIN_TIER_B_KEY_LENGTH or len(key) < MIN_TIER_B_KEY_LENGTH:
        return "key-too-short"
    same_reading = bool(row.reading_identity) and row.reading_identity == other.reading_identity
    if not same_reading and not reciprocal:
        return "one-way-different-reading"
    return None


def _restrict_to_pairwise(
    accepted: dict[frozenset[RowId], VariantLink],
    by_id: dict[RowId, Row],
) -> tuple[list[VariantLink], list[RefusedLink]]:
    """Keep only edges whose both endpoints participate in exactly one edge.

    Transitive closure over these edges was measured and rejected: it chained
    `を中心に`/`を中心にして`/`を中心として` and the `に応じて` fan into 8-row points.
    Requiring strict pairwise degree keeps every unambiguous orthographic pair and
    refuses exactly the chains.
    """
    degree: collections.Counter[RowId] = collections.Counter()
    for ends in accepted:
        for end in ends:
            degree[end] += 1

    strict: list[VariantLink] = []
    chained: list[RefusedLink] = []
    for ends, link in accepted.items():
        if all(degree[end] == 1 for end in ends):
            strict.append(link)
        else:
            chained.append(
                RefusedLink(
                    by_id[link.left].expression,
                    by_id[link.right].expression,
                    link.left_key,
                    link.right_key,
                    "chained-not-pairwise",
                )
            )
    strict.sort(key=lambda link: (link.left.sort_key, link.right.sort_key))
    chained.sort(key=lambda item: (item.left_key, item.right_key))
    return strict, chained


def disambiguate(rows: list[Row]) -> list[tuple[Row, str, str]]:
    """Assign a form/usage disambiguator to rows colliding on one key.

    Returns `(row, disambiguator, basis)` triples. The disambiguator is derived
    from something the source actually says, in a fixed precedence, so it is
    stable across builds and meaningful to a reader:

    1. **signature** — the attachment differs (`動ない形` vs `動辞書形`);
    2. **form** — the written headword differs though it normalizes alike
       (`ずに` vs `ないで`);
    3. **sense** — nothing observable separates them, so an ordinal is used. This
       is the honest fallback: it says "the source ships two senses here and does
       not tell us how they differ" instead of pretending to know.

    The ordinal in case 3 is ordered by the producer's own `source_id` then
    substance hash, never by iteration order, so it is reproducible.
    """
    ordered = sorted(rows, key=lambda row: row.row_id.sort_key)
    if len(ordered) == 1:
        return [(ordered[0], "", "unique")]

    labels = [signature_label(row.signature) for row in ordered]
    if all(labels) and len(set(labels)) == len(ordered):
        return [(row, str(label), "signature") for row, label in zip(ordered, labels)]

    forms = [row.expression for row in ordered]
    if len(set(forms)) == len(ordered):
        return [(row, form, "form") for row, form in zip(ordered, forms)]

    return [(row, f"sense{index + 1}", "sense") for index, row in enumerate(ordered)]


def canonical_key(bucket: tuple[tuple[str, str], str], disambiguator: str) -> str:
    """Render one canonical grammar-point key.

    Shape: `<key>` for an unambiguous point, `<key>#<disambiguator>` when a
    disambiguator is needed, prefixed with the partition axis when it is not the
    default `(standard, modern)` — so a classical point can never collide with its
    modern homograph, and the common case stays readable.
    """
    (variety, era), key = bucket
    scope = "" if (variety, era) == ("standard", "modern") else f"{variety}/{era}:"
    suffix = f"#{disambiguator}" if disambiguator else ""
    return f"{scope}{key}{suffix}"


def resolve_aliases(
    aliases: list[AliasRow],
    assignment: dict[RowId, str],
    rows: list[Row],
) -> dict[str, list[str]]:
    """Attach each demoted alias row's lookup form to the point it redirects to.

    Returns `canonicalKey -> [extra lookup forms]`. An alias whose target cannot
    be resolved contributes no lookup form and is reported: inventing a point for
    it would fabricate an entry the producer never wrote.

    The polarity guard here is not optional, and it is evaluated against the
    point's **accumulated** forms rather than only the redirect target. Producers
    routinely file an affirmative form as a redirect near its negative counterpart
    — measured on this corpus, unguarded alias resolution attaches `うとする` to
    `うとしない` and `ことこの上ある` to `ことこの上ない`, so looking up the
    affirmative would show the negative point.

    Checking only the target is not enough: `は欲しくない`[neg] and
    `を欲しがっている`[pos] are each individually a non-flip against the target
    `が欲しい`[none], yet accepting both puts an affirmative and a negation on one
    card. So each candidate form is compared against every form the point already
    carries, and a lookup form is gated exactly like a Tier B fold — because to the
    user, sharing a lookup form *is* being one point.
    """
    by_key: dict[tuple[tuple[str, str], str], list[Row]] = {}
    for row in rows:
        by_key.setdefault(row.bucket, []).append(row)

    # Forms each canonical point already carries, so accumulated polarity is known.
    accumulated: dict[str, list[str]] = {}
    for row in rows:
        key = assignment.get(row.row_id)
        if key is None:
            continue
        form = row.expression.strip()
        if form and form not in accumulated.setdefault(key, []):
            accumulated[key].append(form)

    extra: dict[str, list[str]] = {}
    for alias in sorted(aliases, key=lambda item: item.row_id.sort_key):
        alias_key = primary_key(alias.record)
        target_rows: list[Row] = []
        for key in alias.targets:
            # Prefer the alias's own source: a producer redirecting inside its own
            # deck is a stronger claim than a coincidental cross-source key match.
            found = by_key.get((alias.axes, key)) or []
            same_source = [row for row in found if row.row_id.source == alias.row_id.source]
            candidates = same_source or found
            if not candidates:
                continue
            if alias_key is not None and is_polarity_flip(alias_key, key):
                # The redirect points at the opposite polarity. Refuse: this is the
                # single most dangerous fold in the corpus.
                alias.resolution = "polarity-flip"
                target_rows = []
                break
            target_rows = candidates
            alias.resolution = "same-source" if same_source else "cross-source"
            break
        if not target_rows:
            if alias.resolution != "polarity-flip":
                alias.resolution = "unresolved"
            continue

        keys = {assignment[row.row_id] for row in target_rows if row.row_id in assignment}
        if len(keys) != 1:
            # The redirect target is itself split across several canonical points,
            # so which one the alias names is ambiguous. Refuse rather than guess.
            alias.resolution = "ambiguous-target"
            continue
        (resolved,) = keys
        form = alias.expression.strip()
        if not form:
            continue

        present = accumulated.setdefault(resolved, [])
        if any(is_polarity_flip(form, existing) for existing in present):
            # Individually fine against the target, jointly a pos/neg card.
            alias.resolution = "polarity-flip"
            continue

        alias.resolved_key = resolved
        if form not in present:
            present.append(form)
        forms = extra.setdefault(resolved, [])
        if form not in forms:
            forms.append(form)
    return extra


def build_keymap(extracted_dir: pathlib.Path) -> dict[str, object]:
    """Run the whole matcher and return the `keymap.json` payload.

    The payload is the product contract: `assignments` is the mapping table the
    merge stage consumes, `points` describes each canonical point and which source
    rows fold into it, and `report` records every ambiguous case with the guard or
    evidence that decided it. Nothing is summarised away — a refusal is as much a
    result as a fold.
    """
    sources = load_sources(extracted_dir)
    rows, aliases, stats = partition_rows(sources)
    buckets = index_buckets(rows)
    folds, collision_buckets, single_buckets = classify_buckets(buckets)
    fold_set = set(folds)
    collision_set = set(collision_buckets)

    # --- assign a canonical key to every substantive row ------------------------
    assignment: dict[RowId, str] = {}
    disambiguator_basis: collections.Counter[str] = collections.Counter()
    point_rows: dict[str, list[Row]] = {}
    buckets_of: dict[str, tuple[tuple[str, str], str]] = {}
    collisions: list[dict[str, object]] = []
    collision_rows_by_entry: list[list[Row]] = []

    for bucket in sorted(buckets, key=lambda item: (item[0], item[1])):
        per_source = buckets[bucket]
        bucket_rows = [row for name in sorted(per_source) for row in per_source[name]]

        if bucket in fold_set:
            # Tier A: a bijection across sources. Every row is the SAME point, so
            # they share one undisambiguated key — this is the fold.
            key = canonical_key(bucket, "")
            for row in bucket_rows:
                assignment[row.row_id] = key
                point_rows.setdefault(key, []).append(row)
            buckets_of[key] = bucket
            disambiguator_basis["fold"] += 1
            continue

        # Otherwise the rows are distinct senses: a refused cross-source collision
        # or a single-source homograph fan. Each gets a source-derived
        # disambiguator so the distinction the producer made survives.
        groups = disambiguate(bucket_rows)
        for row, disambiguator, basis in groups:
            key = canonical_key(bucket, disambiguator)
            assignment[row.row_id] = key
            point_rows.setdefault(key, []).append(row)
            buckets_of[key] = bucket
            disambiguator_basis[basis] += 1
        if bucket in collision_set:
            collisions.append(
                {
                    "bucketKey": bucket[1],
                    "axes": {"variety": bucket[0][0], "era": bucket[0][1]},
                    "rowCount": len(bucket_rows),
                    "sources": {name: len(found) for name, found in sorted(per_source.items())},
                    "disambiguatorBasis": groups[0][2] if groups else "unique",
                    # Restated after Tier B; see below.
                    "canonicalKeys": sorted({assignment[row.row_id] for row in bucket_rows}),
                }
            )
            collision_rows_by_entry.append(bucket_rows)

    # --- Tier B: merge attested variant pairs into one point --------------------
    links, refused_links = propose_variant_links(rows, buckets)
    merged = _apply_links(links, assignment, point_rows)
    for item in merged:
        buckets_of.pop(str(item["absorbedKey"]), None)

    # Tier B runs after the collisions were recorded, so a refused bucket may name
    # a key that has since been absorbed into a variant pair. Restate the surviving
    # keys from the final assignment rather than shipping a stale list.
    for collision, collision_rows in zip(collisions, collision_rows_by_entry):
        collision["canonicalKeys"] = sorted(
            {assignment[row.row_id] for row in collision_rows}
        )

    # --- demoted alias rows become lookup forms on the point they redirect to ---
    extra_forms = resolve_aliases(aliases, assignment, rows)

    points = _render_points(point_rows, extra_forms, buckets_of)
    report = _render_report(
        stats=stats,
        folds=folds,
        refused_buckets=collision_buckets,
        singletons=single_buckets,
        collisions=collisions,
        links=links,
        refused_links=refused_links,
        aliases=aliases,
        merged=merged,
        disambiguator_basis=disambiguator_basis,
        points=points,
    )

    return {
        "schemaVersion": 1,
        "assignments": [
            {**row_id.as_dict(), "canonicalKey": key}
            for row_id, key in sorted(assignment.items(), key=lambda item: item[0].sort_key)
        ],
        "points": points,
        "report": report,
    }


def _apply_links(
    links: list[VariantLink],
    assignment: dict[RowId, str],
    point_rows: dict[str, list[Row]],
) -> list[dict[str, object]]:
    """Fold each accepted Tier B pair onto one canonical key.

    The surviving key is chosen deterministically (lexicographically smallest), so
    the same corpus always produces the same key. Because `_restrict_to_pairwise`
    already guaranteed every endpoint has degree one, applying these links cannot
    cascade: a fold here can never pull in a third point.
    """
    applied: list[dict[str, object]] = []
    for link in links:
        left_key = assignment.get(link.left)
        right_key = assignment.get(link.right)
        if left_key is None or right_key is None or left_key == right_key:
            continue
        keep, drop = sorted((left_key, right_key))
        moved = point_rows.pop(drop, [])
        for row in moved:
            assignment[row.row_id] = keep
        point_rows.setdefault(keep, []).extend(moved)
        applied.append(
            {
                "canonicalKey": keep,
                "absorbedKey": drop,
                "reason": link.reason,
                "left": link.left.as_dict(),
                "right": link.right.as_dict(),
            }
        )
    applied.sort(key=lambda item: (str(item["canonicalKey"]), str(item["absorbedKey"])))
    return applied


def _render_points(
    point_rows: dict[str, list[Row]],
    extra_forms: dict[str, list[str]],
    buckets_of: dict[str, tuple[tuple[str, str], str]],
) -> list[dict[str, object]]:
    """Describe every canonical point: its forms, contributors, and attributes.

    `bucketKey` and `disambiguator` are emitted separately from `canonicalKey` so
    the bank generator can group the refused senses of one headword under a single
    card with numbered sections. Without them, downstream would have to re-derive
    grouping by splitting on `#`, which is fragile — a Japanese headword may
    legitimately contain punctuation, and the axis prefix is also part of the key.
    Refusing a fold must not force the user to meet nineteen separate `ない` cards.
    """
    rendered: list[dict[str, object]] = []
    for key in sorted(point_rows):
        rows = sorted(point_rows[key], key=lambda row: row.row_id.sort_key)
        forms: list[str] = []
        for row in rows:
            form = row.expression.strip()
            if form and form not in forms:
                forms.append(form)
        for form in extra_forms.get(key, ()):
            if form not in forms:
                forms.append(form)

        observed_registers = sorted({label for row in rows for label in registers(row.record)})
        signatures = sorted({label for row in rows if (label := signature_label(row.signature))})
        jlpt = sorted({str(row.record["jlpt"]) for row in rows if row.record.get("jlpt")})
        (variety, era) = rows[0].axes
        (_, bucket_key) = buckets_of.get(key, (rows[0].axes, rows[0].key))
        disambiguator = key.split("#", 1)[1] if "#" in key else ""

        rendered.append(
            {
                "canonicalKey": key,
                # Shared by every sense the matcher refused to fold, so the card
                # generator can render them as one entry with numbered senses.
                "bucketKey": bucket_key,
                "disambiguator": disambiguator,
                "expression": forms[0] if forms else rows[0].expression,
                "lookupForms": forms,
                "axes": {"variety": variety, "era": era},
                "contributors": [row.row_id.as_dict() for row in rows],
                "sourceCount": len({row.row_id.source for row in rows}),
                # Recorded, never used as a fold gate (see module docstring).
                "observedRegisters": observed_registers,
                "observedSignatures": signatures,
                # Conflicting JLPT levels are listed side by side, never averaged.
                "jlptLevels": jlpt,
            }
        )
    return rendered


def _render_report(
    *,
    stats: dict[str, int],
    folds: list,
    refused_buckets: list,
    singletons: list,
    collisions: list[dict[str, object]],
    links: list[VariantLink],
    refused_links: list[RefusedLink],
    aliases: list[AliasRow],
    merged: list[dict[str, object]],
    disambiguator_basis: collections.Counter[str],
    points: list[dict[str, object]],
) -> dict[str, object]:
    """The ambiguous-cases report the card asks for.

    Refusals are enumerated in full rather than counted, because a refusal is the
    reviewable decision: a reader must be able to check that `ないことはある` and
    `ないことはない` stayed apart, and see which guard did it.
    """
    guard_counts = collections.Counter(item.guard for item in refused_links)
    alias_counts = collections.Counter(alias.resolution for alias in aliases)
    per_source_contributions: collections.Counter[str] = collections.Counter()
    for point in points:
        for contributor in point["contributors"]:  # type: ignore[index]
            per_source_contributions[contributor["source"]] += 1  # type: ignore[index]

    multi_source = [point for point in points if int(point["sourceCount"]) > 1]  # type: ignore[arg-type]

    return {
        "corpus": {
            "rows": stats.get("rows", 0),
            "substantiveRows": stats.get("substantiveRows", 0),
            "declaredAliasRows": stats.get("aliasRows", 0),
            "duplicateRowsCollapsed": stats.get("duplicateRowsCollapsed", 0),
            "aliasRowsCollapsed": stats.get("aliasRowsCollapsed", 0),
            "contributionsBySource": dict(sorted(per_source_contributions.items())),
        },
        "canonicalPoints": {
            "total": len(points),
            "multiSource": len(multi_source),
            "singleSource": len(points) - len(multi_source),
        },
        "tierA": {
            "rule": "partition-scoped bijection: every contributing source has exactly one row",
            "bijectiveBuckets": len(folds),
            "refusedCollisionBuckets": len(refused_buckets),
            "singleSourceBuckets": len(singletons),
            "disambiguatorBasis": dict(sorted(disambiguator_basis.items())),
            # Every refused collision, so a reviewer can audit the split.
            "refusedCollisions": collisions,
        },
        "tierB": {
            "rule": (
                "producer-attested variant edge to an unambiguous single row of one other "
                "source, surviving polarity/in-degree/length/evidence guards and strictly pairwise"
            ),
            "accepted": len(links),
            "acceptedByReason": dict(
                sorted(collections.Counter(link.reason for link in links).items())
            ),
            "acceptedLinks": [link.as_dict() for link in links],
            "refused": len(refused_links),
            "refusedByGuard": dict(sorted(guard_counts.items())),
            "refusedLinks": [item.as_dict() for item in refused_links],
            "pointsMerged": merged,
            "transitiveClosure": (
                "rejected: measured 8-row blow-up chaining を中心に/を中心にして/を中心として "
                "and the に応じて fan; strict pairwise degree is required instead"
            ),
        },
        "aliases": {
            "rule": "producer-declared redirect rows are demoted to lookup forms, never contributors",
            "byResolution": dict(sorted(alias_counts.items())),
            "unresolved": [
                {
                    "source": alias.row_id.source,
                    "sourceId": alias.row_id.source_id,
                    "expression": alias.expression,
                    "targets": alias.targets,
                }
                for alias in sorted(aliases, key=lambda item: item.row_id.sort_key)
                if alias.resolution in ("unresolved", "ambiguous-target")
            ],
        },
        "notFoldGates": {
            "attachmentSignature": (
                "recorded and used only to separate colliding rows; requiring equality "
                "refuses 540 of 697 correct bijective folds and sub-matching inside refused "
                "buckets manufactures false folds"
            ),
            "register": (
                "recorded per point; measured as prose commentary rather than a distinguishing "
                "property, so partitioning on it would split correct folds"
            ),
        },
    }


__all__ = [
    "MAX_VARIANT_IN_DEGREE",
    "MIN_TIER_B_KEY_LENGTH",
    "SOURCE_PRECEDENCE",
    "SUBSTANCE_FIELDS",
    "AliasRow",
    "RefusedLink",
    "Row",
    "RowId",
    "VariantLink",
    "alias_targets",
    "build_keymap",
    "canonical_key",
    "classify_buckets",
    "disambiguate",
    "index_buckets",
    "is_declared_alias",
    "load_sources",
    "partition_rows",
    "primary_key",
    "propose_variant_links",
    "resolve_aliases",
    "substance_hash",
    "variant_in_degree",
    "variant_keys",
]
