"""Regressions for the cross-source matcher (`bugd.keymap`).

Two layers, deliberately separated:

* **unit** — synthetic records exercising one rule at a time, so a failure names
  the guard that broke rather than "the corpus moved";
* **corpus** — properties asserted against the real `data/extracted/*.json` when
  it is present, because the guards were derived from measurements of that corpus
  and a silent drift in it is exactly what these tests exist to catch. They skip
  cleanly when the extracted artifacts are absent (fresh clone, PR CI).

The corpus counts are pinned. If a source is re-extracted and a count moves, the
test fails on purpose: a changed fold count is a review event, not a detail.
"""

from __future__ import annotations

import collections
import json
import pathlib
import tempfile

import pytest

from bugd.jsonio import MalformedPayload, dump_json
from bugd.keymap import (
    Row,
    alias_targets,
    build_keymap,
    canonical_key,
    disambiguate,
    index_buckets,
    is_declared_alias,
    partition_rows,
    propose_variant_links,
    substance_hash,
    variant_in_degree,
    variant_keys,
)
from bugd.keymap_io import PAIR_SEPARATOR, parse_keymap
from bugd.polarity import is_polarity_flip, polarity

EXTRACTED = pathlib.Path("data/extracted")


def record(
    source_id: str,
    expression: str,
    *,
    reading: str | None = None,
    meaning: str | None = None,
    structure: str | None = None,
    variants: tuple[str, ...] = (),
    provenance: dict[str, object] | None = None,
    examples: tuple[dict[str, object], ...] = (),
    **extra: object,
) -> dict[str, object]:
    """One normalized source row in the on-disk shape the matcher consumes."""
    return {
        "source_id": source_id,
        "expression": expression,
        "reading": reading if reading is not None else expression,
        "meaning": meaning,
        "structure": structure,
        "nuance": None,
        "explanation": None,
        "notes": None,
        "jlpt": None,
        "variants": list(variants),
        "tags": [],
        "examples": [dict(example) for example in examples],
        "ai_generated": {},
        "provenance": dict(provenance or {}),
        **extra,
    }


def rows_of(**sources: list[dict[str, object]]) -> tuple[list[Row], list, dict[str, int]]:
    return partition_rows({name: points for name, points in sources.items()})


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


def test_substance_hash_ignores_whitespace_in_examples_but_not_content() -> None:
    base = record("x", "から", examples=({"japanese": "朝 から 夜", "english": "a"},))
    spaced = record("x", "から", examples=({"japanese": "朝から夜", "english": "a"},))
    different = record("x", "から", examples=({"japanese": "朝から昼", "english": "a"},))
    assert substance_hash(base) == substance_hash(spaced)
    assert substance_hash(base) != substance_hash(different)


def test_source_id_alone_does_not_identify_a_row() -> None:
    """Two senses sharing a source_id must stay two rows with two keys."""
    rows, _, stats = rows_of(
        edewakaru=[
            record("も", "も", meaning="also", structure="名詞"),
            record("も", "も", meaning="even", structure="動ます形"),
        ]
    )
    assert stats["substantiveRows"] == 2
    assert len({row.row_id for row in rows}) == 2
    keys = {canonical_key(row.bucket, d) for row, d, _ in disambiguate(rows)}
    assert len(keys) == 2


def test_byte_identical_rows_collapse_to_one() -> None:
    duplicate = record("ったらない", "ったらない", meaning="extremely")
    rows, _, stats = rows_of(dojg=[duplicate, dict(duplicate)])
    assert stats["substantiveRows"] == 1
    assert stats["duplicateRowsCollapsed"] == 1


def test_row_without_a_lookup_key_fails_closed() -> None:
    with pytest.raises(MalformedPayload, match="no lookup key"):
        rows_of(dojg=[record("blank", "〜")])


def test_row_without_a_source_id_fails_closed() -> None:
    broken = record("x", "から")
    broken["source_id"] = ""
    with pytest.raises(MalformedPayload, match="source_id"):
        rows_of(dojg=[broken])


# --------------------------------------------------------------------------
# alias demotion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provenance",
    [
        {"aliasOf": "あいまって"},
        {"syntheticLookupForm": True},
        {"entryShape": "alias-redirect"},
    ],
)
def test_every_declared_alias_shape_is_recognized(provenance: dict[str, object]) -> None:
    assert is_declared_alias(record("x", "相まって", provenance=provenance))


def test_an_unflagged_row_is_never_inferred_to_be_an_alias() -> None:
    """A bodyless row is not an alias unless the producer says so."""
    assert not is_declared_alias(record("x", "から"))


def test_alias_targets_prefer_explicit_fields_over_links() -> None:
    alias = record(
        "相まって",
        "相まって",
        variants=("あいまって",),
        provenance={
            "aliasOf": "あいまって",
            "producerLinks": ["?query=とあいまって"],
            "entryShape": "alias-redirect",
        },
    )
    assert alias_targets(alias)[0] == "あいまって"
    assert "とあいまって" in alias_targets(alias)


def test_alias_rows_never_become_contributors() -> None:
    payload = {
        "donna_toki": [
            record("あいまって", "あいまって", meaning="combined with"),
            record(
                "相まって",
                "相まって",
                provenance={"aliasOf": "あいまって", "entryShape": "alias-redirect"},
            ),
        ]
    }
    rows, aliases, stats = partition_rows(payload)
    assert stats["substantiveRows"] == 1
    assert len(aliases) == 1
    assert rows[0].expression == "あいまって"


def test_alias_twin_of_a_substantive_row_is_dropped() -> None:
    """One source shipping a row both flagged and unflagged keeps the real one."""
    body = record("ようが", "ようが", meaning="whether or not")
    twin = dict(body)
    twin["provenance"] = {"syntheticLookupForm": True}
    rows, aliases, stats = partition_rows({"nihongo_no_sensei": [body, twin]})
    assert stats["substantiveRows"] == 1
    assert stats["aliasTwinsOfSubstantiveDropped"] == 1
    assert aliases == []
    assert rows[0].expression == "ようが"


# --------------------------------------------------------------------------
# Tier A: bijection folds, collisions refused
# --------------------------------------------------------------------------


def test_bijective_bucket_folds_to_one_key() -> None:
    payload = build_keymap_from(
        dojg=[record("ながら", "ながら", meaning="while")],
        edewakaru=[record("ながら", "ながら", meaning="although")],
    )
    points = payload["points"]
    assert len(points) == 1
    assert points[0]["sourceCount"] == 2
    assert points[0]["canonicalKey"] == "ながら"


def test_collision_bucket_is_refused_not_folded() -> None:
    """One source with two senses of a key blocks the cross-source fold."""
    payload = build_keymap_from(
        dojg=[record("ながら", "ながら", meaning="while", structure="動ます形")],
        edewakaru=[
            record("ながら", "ながら", meaning="although", structure="名詞"),
            record("ながら2", "ながら", meaning="while", structure="動辞書形"),
        ],
    )
    assert payload["report"]["tierA"]["refusedCollisionBuckets"] == 1
    assert payload["report"]["tierA"]["bijectiveBuckets"] == 0
    # No point may contain rows from both sources: the correspondence is unknown.
    assert all(point["sourceCount"] == 1 for point in payload["points"])


def test_single_source_fan_is_not_reported_as_a_cross_source_collision() -> None:
    payload = build_keymap_from(
        edewakaru=[
            record("も", "も", meaning="also", structure="名詞"),
            record("も2", "も", meaning="even", structure="動ます形"),
        ]
    )
    report = payload["report"]["tierA"]
    assert report["refusedCollisionBuckets"] == 0
    assert report["singleSourceBuckets"] == 1
    assert len(payload["points"]) == 2


def test_classical_never_folds_onto_modern() -> None:
    payload = build_keymap_from(
        dojg=[record("ごとし", "ごとし", meaning="like", notes="古語の助動詞")],
        edewakaru=[record("ごとし", "ごとし", meaning="like")],
    )
    keys = {point["canonicalKey"] for point in payload["points"]}
    assert keys == {"ごとし", "standard/classical:ごとし"}


def test_dialect_never_folds_onto_standard() -> None:
    payload = build_keymap_from(
        dojg=[record("やん", "やん", meaning="isn't it", notes="関西弁")],
        edewakaru=[record("やん", "やん", meaning="isn't it")],
    )
    assert len(payload["points"]) == 2


def test_register_does_not_partition_but_is_recorded() -> None:
    """A point described as 硬い by one source still folds, and records it."""
    payload = build_keymap_from(
        dojg=[record("にて", "にて", meaning="at", notes="硬い表現です")],
        edewakaru=[record("にて", "にて", meaning="at")],
    )
    assert len(payload["points"]) == 1
    assert payload["points"][0]["observedRegisters"] == ["formal"]


# --------------------------------------------------------------------------
# disambiguators
# --------------------------------------------------------------------------


def test_disambiguator_prefers_signature_then_form_then_ordinal() -> None:
    signature_rows, _, _ = rows_of(
        dojg=[
            record("a", "そう", structure="動ます形"),
            record("b", "そう", structure="名詞"),
        ]
    )
    assert {basis for _, _, basis in disambiguate(signature_rows)} == {"signature"}

    form_rows, _, _ = rows_of(
        dojg=[record("a", "〜ずに"), record("b", "ずに")],
    )
    assert {basis for _, _, basis in disambiguate(form_rows)} == {"form"}

    opaque_rows, _, _ = rows_of(
        dojg=[record("a", "から", meaning="one"), record("b", "から", meaning="two")],
    )
    labels = disambiguate(opaque_rows)
    assert {basis for _, _, basis in labels} == {"sense"}
    assert sorted(d for _, d, _ in labels) == ["sense1", "sense2"]


def test_ordinal_disambiguator_is_stable_under_input_reordering() -> None:
    first = record("a", "から", meaning="one")
    second = record("b", "から", meaning="two")
    forward, _, _ = rows_of(dojg=[first, second])
    backward, _, _ = rows_of(dojg=[second, first])
    assert [(row.row_id.source_id, d) for row, d, _ in disambiguate(forward)] == [
        (row.row_id.source_id, d) for row, d, _ in disambiguate(backward)
    ]


def test_canonical_key_shape() -> None:
    assert canonical_key((("standard", "modern"), "から"), "") == "から"
    assert canonical_key((("standard", "modern"), "から"), "sense2") == "から#sense2"
    assert canonical_key((("standard", "classical"), "ごとし"), "") == "standard/classical:ごとし"


def build_keymap_from(**sources: list[dict[str, object]]) -> dict[str, object]:
    """Run the whole matcher over synthetic sources via a temp directory."""
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory)
        for name, points in sources.items():
            (path / f"{name}.json").write_text(
                dump_json({"source": name, "points": points}), encoding="utf-8"
            )
        return build_keymap(path)


# --------------------------------------------------------------------------
# Tier B guards. Each test states the fold that must NOT happen.
# --------------------------------------------------------------------------


def link_between(**sources: list[dict[str, object]]):
    rows, _, _ = rows_of(**sources)
    return propose_variant_links(rows, index_buckets(rows))


def test_reading_identity_folds_two_spellings_of_one_point() -> None:
    accepted, _ = link_between(
        dojg=[record("今更", "今更", reading="いまさら", variants=("いまさら",))],
        edewakaru=[record("いまさら", "いまさら", reading="いまさら")],
    )
    assert [link.reason for link in accepted] == ["reading-identity"]


def test_reciprocal_declaration_folds_an_okurigana_pair() -> None:
    accepted, _ = link_between(
        dojg=[record("を踏まえて", "を踏まえて", reading="をふまえて", variants=("を踏まえ",))],
        edewakaru=[record("を踏まえ", "を踏まえ", reading="をふまえ", variants=("を踏まえて",))],
    )
    assert [link.reason for link in accepted] == ["reciprocal"]


def test_polarity_flip_is_refused_even_when_the_producer_declares_it() -> None:
    """The most dangerous fold in the corpus: affirmative onto its negation."""
    accepted, refused = link_between(
        dojg=[
            record(
                "ないことはある",
                "ないことはある",
                reading="ないことはある",
                variants=("ないことはない",),
            )
        ],
        edewakaru=[
            record(
                "ないことはない",
                "ないことはない",
                reading="ないことはない",
                variants=("ないことはある",),
            )
        ],
    )
    assert accepted == []
    assert "polarity-flip" in {item.guard for item in refused}


def test_affirmative_containing_nai_is_not_mistaken_for_a_negative() -> None:
    """`ないことはある` contains ない but is affirmative: polarity reads the tail."""
    assert polarity("ないことはある") == "pos"
    assert polarity("ないことはない") == "neg"
    assert is_polarity_flip("ないことはある", "ないことはない")


def test_polarity_abstains_on_an_unrecognized_tail() -> None:
    """`ずに`/`ないで` are one point; only one side has a readable polarity tail."""
    assert polarity("ないで") == "none"
    assert not is_polarity_flip("ずに", "ないで")
    assert not is_polarity_flip("ている", "ておる")


def test_generic_hub_is_refused() -> None:
    """A key many rows point at is a copula, not a specific variant claim."""
    pointers = [
        record(f"p{index}", f"限り{index}だ", reading=f"かぎり{index}だ", variants=("です",))
        for index in range(4)
    ]
    accepted, refused = link_between(
        dojg=pointers,
        edewakaru=[record("です", "です", reading="です")],
    )
    assert accepted == []
    assert "generic-hub" in {item.guard for item in refused}


def test_single_character_key_is_refused() -> None:
    accepted, refused = link_between(
        dojg=[record("所", "所", reading="ところ", variants=("へ",))],
        edewakaru=[record("へ", "へ", reading="へ", variants=("所",))],
    )
    assert accepted == []
    assert "key-too-short" in {item.guard for item in refused}


def test_one_way_link_with_a_different_reading_is_refused() -> None:
    """A one-directional claim between differently-read forms is relatedness."""
    accepted, refused = link_between(
        dojg=[record("ばかりして", "ばかりして", reading="ばかりして", variants=("てばかりはいられない",))],
        edewakaru=[record("てばかりはいられない", "てばかりはいられない", reading="てばかりはいられない")],
    )
    assert accepted == []
    assert {item.guard for item in refused} <= {"one-way-different-reading", "polarity-flip"}


def test_variant_into_a_homograph_fan_is_not_a_usable_claim() -> None:
    """An ambiguous target cannot attest identity, so no link is proposed."""
    accepted, _ = link_between(
        dojg=[record("にわたって", "にわたって", reading="にわたって", variants=("にわたる",))],
        edewakaru=[
            record("a", "にわたる", reading="にわたる", meaning="one"),
            record("b", "にわたる", reading="にわたる", meaning="two"),
        ],
    )
    assert accepted == []


def test_chained_links_are_refused_rather_than_transitively_closed() -> None:
    """を中心に/を中心にして/を中心として must not become one 3-way point."""
    accepted, refused = link_between(
        dojg=[record("を中心にして", "を中心にして", reading="をちゅうしんにして", variants=("を中心に", "を中心として"))],
        edewakaru=[
            record("を中心に", "を中心に", reading="をちゅうしんに", variants=("を中心にして",)),
            record("を中心として", "を中心として", reading="をちゅうしんとして", variants=("を中心にして",)),
        ],
    )
    assert accepted == []
    assert "chained-not-pairwise" in {item.guard for item in refused}


def test_a_reading_silent_source_does_not_block_an_orthographic_fold() -> None:
    """A row that states no reading supplies no evidence -- and must not veto.

    Only five of the ten sources state a reading at all, so a bucket routinely
    mixes reading-bearing and reading-silent rows. Treating "no reading" as
    disagreement meant any reading-less source joining the target bucket
    permanently blocked the fold: `や否や` split from `やいなや` the moment
    bunpou/511 landed there beside donna_toki.

    Asserted as the property (silence does not veto), not as the one pair.
    """
    accepted, _ = link_between(
        dojg=[record("や否や", "や否や", reading="やいなや", variants=("やいなや",))],
        donna_toki=[record("やいなや", "やいなや", reading="やいなや")],
        # An absent reading normalizes to "" (verified on the real bunpou row).
        bunpou=[record("511", "やいなや", reading="")],
    )
    assert [link.reason for link in accepted] == ["reading-identity"]


def test_a_contradicting_reading_still_refuses_the_fold() -> None:
    """Silence is not evidence, but a DIFFERENT stated reading is a refusal.

    The counterpart to the test above: the relaxation must only ignore rows that
    say nothing, never rows that disagree. Without this, ignoring readings
    wholesale proposed polarity errors such as `てはいく` <-> `てはいけない`.
    """
    accepted, _ = link_between(
        dojg=[record("や否や", "や否や", reading="やいなや", variants=("やいなや",))],
        donna_toki=[record("やいなや", "やいなや", reading="やいなや")],
        nihongo_net=[record("other", "やいなや", reading="やひや")],
    )
    assert accepted == []


def test_two_rows_stating_the_same_reading_remain_ambiguous() -> None:
    """The linked endpoint must be the unique row that attests the reading.

    Two rows both stating the proposer's reading is a homograph fan, not
    corroboration: there is no single record to point at.
    """
    accepted, _ = link_between(
        dojg=[record("や否や", "や否や", reading="やいなや", variants=("やいなや",))],
        donna_toki=[record("やいなや", "やいなや", reading="やいなや")],
        nihongo_net=[record("also", "やいなや", reading="やいなや")],
    )
    assert accepted == []


def test_a_reading_silent_proposer_cannot_claim_a_multi_source_bucket() -> None:
    """The proposer's own reading is the evidence; without it there is none.

    Called directly rather than through the corpus: no reading-less row in the
    real corpus reaches the multi-source branch (measured: 0), so a mutation
    deleting this guard survives a full-suite run as a no-op. Guard branches that
    the corpus does not exercise must be probed with synthetic inputs or they are
    untested by construction.
    """
    from bugd.keymap import _link_target

    rows, _, _ = rows_of(
        dojg=[record("や否や", "や否や", reading="", variants=("やいなや",))],
        donna_toki=[record("やいなや", "やいなや", reading="やいなや")],
        bunpou=[record("511", "やいなや", reading="")],
    )
    proposer = next(r for r in rows if r.row_id.source == "dojg")
    others = {
        r.row_id.source: [r] for r in rows if r.row_id.source != "dojg"
    }
    assert _link_target(proposer, others) is None


def test_variant_in_degree_counts_distinct_rows() -> None:
    rows, _, _ = rows_of(
        dojg=[
            record("a", "から", variants=("です",)),
            record("b", "まで", variants=("です",)),
        ]
    )
    assert variant_in_degree(rows)["です"] == 2


def test_variant_keys_exclude_the_rows_own_forms() -> None:
    assert variant_keys(record("x", "から", variants=("から", "かれ"))) == ["かれ"]


# --------------------------------------------------------------------------
# alias polarity: a lookup form is a fold from the user's point of view
# --------------------------------------------------------------------------


def test_alias_redirect_across_a_polarity_flip_is_refused() -> None:
    payload = build_keymap_from(
        nihongo_no_sensei=[
            record("うとしない", "うとしない", meaning="does not try to"),
            record(
                "うとする",
                "うとする",
                provenance={"aliasOf": "うとしない", "entryShape": "alias-redirect"},
            ),
        ]
    )
    forms = payload["points"][0]["lookupForms"]
    assert "うとする" not in forms
    assert payload["report"]["aliases"]["byResolution"].get("polarity-flip") == 1


def test_two_individually_safe_aliases_cannot_jointly_mix_polarity() -> None:
    """は欲しくない[neg] and を欲しがっている[pos] are each fine vs が欲しい[none]."""
    payload = build_keymap_from(
        edewakaru=[
            record("が欲しい", "が欲しい", meaning="want"),
            record(
                "は欲しくない",
                "は欲しくない",
                provenance={"aliasOf": "が欲しい", "entryShape": "alias-redirect"},
            ),
            record(
                "を欲しがっている",
                "を欲しがっている",
                provenance={"aliasOf": "が欲しい", "entryShape": "alias-redirect"},
            ),
        ]
    )
    for point in payload["points"]:
        polarities = {polarity(form) for form in point["lookupForms"]}
        assert not {"pos", "neg"} <= polarities


def test_alias_with_an_unresolvable_target_creates_no_point() -> None:
    payload = build_keymap_from(
        donna_toki=[
            record("から", "から", meaning="because"),
            record(
                "存在しない",
                "存在しない",
                provenance={"aliasOf": "まったく無関係", "entryShape": "alias-redirect"},
            ),
        ]
    )
    assert [point["canonicalKey"] for point in payload["points"]] == ["から"]
    assert payload["report"]["aliases"]["byResolution"].get("unresolved") == 1


# --------------------------------------------------------------------------
# keymap.json round-trip through the reader the merge stage uses
# --------------------------------------------------------------------------


def test_keymap_round_trips_through_the_consumer() -> None:
    payload = build_keymap_from(
        dojg=[record("ながら", "ながら", meaning="while")],
        edewakaru=[record("ながら", "ながら", meaning="although")],
    )
    mapping = parse_keymap(payload)
    assert len(mapping) == len(payload["assignments"])
    assert set(mapping.values()) == {"ながら"}


def test_flat_three_part_and_legacy_two_part_shapes_both_parse() -> None:
    three = {"assignments": {PAIR_SEPARATOR.join(("dojg", "から", "abc")): "から"}}
    two = {"assignments": {PAIR_SEPARATOR.join(("dojg", "から")): "から"}}
    assert parse_keymap(three) == {("dojg", "から", "abc"): "から"}
    assert parse_keymap(two) == {("dojg", "から", ""): "から"}


def test_two_senses_sharing_a_source_id_survive_the_round_trip() -> None:
    """The reason substanceHash is part of the identity at all."""
    payload = {
        "assignments": [
            {"source": "edewakaru", "sourceId": "も", "substanceHash": "a", "canonicalKey": "も#s1"},
            {"source": "edewakaru", "sourceId": "も", "substanceHash": "b", "canonicalKey": "も#s2"},
        ]
    }
    assert len(parse_keymap(payload)) == 2


def test_contradictory_assignment_fails_closed() -> None:
    payload = {
        "assignments": [
            {"source": "dojg", "sourceId": "から", "substanceHash": "a", "canonicalKey": "から"},
            {"source": "dojg", "sourceId": "から", "substanceHash": "a", "canonicalKey": "まで"},
        ]
    }
    with pytest.raises(MalformedPayload, match="two canonical keys"):
        parse_keymap(payload)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"assignments": 3},
        {"assignments": [{"source": "", "sourceId": "x", "canonicalKey": "k"}]},
        {"assignments": [{"source": "d", "sourceId": "x", "canonicalKey": ""}]},
        {"assignments": {"no-separator": "k"}},
    ],
)
def test_malformed_keymap_payloads_fail_closed(payload: object) -> None:
    with pytest.raises(MalformedPayload):
        parse_keymap(payload)


# --------------------------------------------------------------------------
# Real-corpus properties. Pinned: a moved count is a review event.
# --------------------------------------------------------------------------

#: The pinned corpus counts below are properties of the WHOLE corpus, so these
#: tests are only meaningful when every contributing source has been extracted.
#: Gating on "any *.json exists" made a single-source extraction (e.g. `bugd.cli
#: --source yokubi extract` while iterating on one extractor) report 7 loud
#: failures such as `assert 132 == 4972`, which read as keymap defects but were
#: only a partial corpus. Require the full set, and skip with a message naming
#: exactly which sources are missing.
CORPUS_SOURCES = (
    "dojg",
    "donna_toki",
    "edewakaru",
    "nihongo_net",
    "nihongo_no_sensei",
)


def _missing_corpus_sources() -> list[str]:
    if not EXTRACTED.is_dir():
        return list(CORPUS_SOURCES)
    return [name for name in CORPUS_SOURCES if not (EXTRACTED / f"{name}.json").is_file()]


pytestmark_corpus = pytest.mark.skipif(
    bool(_missing_corpus_sources()),
    reason=(
        "pinned counts need the full corpus; missing extracted sources: "
        f"{', '.join(_missing_corpus_sources()) or 'none'} (run `make extract`)"
    ),
)


@pytest.fixture(scope="module")
def corpus() -> dict[str, object]:
    missing = _missing_corpus_sources()
    if missing:
        pytest.skip(
            "pinned counts need the full corpus; missing extracted sources: "
            f"{', '.join(missing)} (run `make extract`)"
        )
    return build_keymap(EXTRACTED)


@pytestmark_corpus
def test_corpus_counts_are_pinned(corpus: dict[str, object]) -> None:
    report = corpus["report"]
    # 7896 = the 5936 six-source basis plus the four extractors UGD-16 convergence
    # landed: bunpou 534 + imabi 494 + ninjal_bunkei 800 + yokubi 132 = 1960.
    #
    # Attributed by rebuilding the keymap through the real production builder over
    # the same artifacts with those four `data/extracted/*.json` REMOVED: that
    # basis reports rows=5936 / substantiveRows=4696 exactly, reproducing this
    # pin's previous values, and the row-identity SETS
    # `{(source, sourceId, substanceHash)}` differ by exactly +1960 with **0 lost**
    # (gained per source: bunpou 534, imabi 494, ninjal_bunkei 800, yokubi 132).
    # So the growth is additive and nothing that was assigned stopped being
    # assigned.
    assert report["corpus"]["rows"] == 7896
    assert report["corpus"]["declaredAliasRows"] == 1167
    # Unmoved by convergence: the four new sources contribute no declared alias
    # and no duplicate of an existing row.
    #
    # 73, from 71 and originally 63: UGD-14 stopped shipping the edewakaru
    # blog-ring footer (`にほんブログ村` / `――以上――` / `語学(日本語)ランキング`) as
    # content. Those lines were the ONLY difference between otherwise
    # byte-identical records, so removing site chrome let the existing duplicate
    # collapse do its job.
    #
    # The 71 -> 73 step is the round-8 fix to `_strip_post_chrome`, which
    # previously dropped a marker only when it was the WHOLE line and therefore
    # missed 29 occurrences the producer had concatenated onto the end of real
    # text (`…イラストリスト】語学(日本語)ランキングにほんブログ村にほんブログ村――以上――`).
    assert report["corpus"]["duplicateRowsCollapsed"] == 73
    # 6656 = 4696 + the same 1960. Every one of the four new sources' rows arrives
    # substantive, matching the per-source set diff above.
    assert report["corpus"]["substantiveRows"] == 6656
    # Tier A grows with the corpus: 676 -> 821 bijective, 201 -> 217 refused.
    assert report["tierA"]["bijectiveBuckets"] == 821
    assert report["tierA"]["refusedCollisionBuckets"] == 217
    # Tier B DECREASED, 57 -> 49, which a totals-only repin would have hidden. Set
    # diff of `acceptedLinks`: +1 gained (`に応じて`↔`に応じた`) and 8 LOST --
    # `こととなると`↔`ことになると`, `ずに済む`↔`ないで済む`, `せいで`↔`せいか`,
    # `ともなく`↔`ともなしに`, `につれて`↔`につれ`, `によって`↔`により`,
    # `によると`↔`によれば`, `ようがない`↔`ようもない`.
    #
    # This is the known Tier-B fold-guard behaviour, not lost content: a newly
    # landed source adds a row to one side's bucket, so the pairwise guards
    # (`generic-hub`, `one-way-different-reading`) that keep an ambiguous fold from
    # merging two distinct points now fire. Verified that nothing became
    # unreachable: all 16 forms are still separate `point` entries in the emitted
    # keymap, and 0 contributor identities disappeared. The pair is split across
    # two cards rather than folded onto one -- a findability regression worth its
    # own card, NOT a conservation failure, and it cannot touch the public
    # artifact, whose corpus (ninjal_bunkei + yokubi) has 0 Tier-B links at all.
    assert report["tierB"]["accepted"] == 49
    assert len(corpus["points"]) == 4481


@pytestmark_corpus
def test_every_substantive_row_is_assigned_exactly_once(corpus: dict[str, object]) -> None:
    assignments = corpus["assignments"]
    identities = {(a["source"], a["sourceId"], a["substanceHash"]) for a in assignments}
    assert len(identities) == len(assignments)
    assert len(assignments) == corpus["report"]["corpus"]["substantiveRows"]
    contributors = sum(len(point["contributors"]) for point in corpus["points"])
    assert contributors == len(assignments)


@pytestmark_corpus
def test_no_canonical_point_mixes_affirmative_and_negative(corpus: dict[str, object]) -> None:
    """The single most dangerous fold, asserted over the whole real corpus."""
    offenders = [
        point["canonicalKey"]
        for point in corpus["points"]
        if {"pos", "neg"} <= {polarity(form) for form in point["lookupForms"]}
    ]
    assert offenders == []


@pytestmark_corpus
@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("ないことはある", "ないことはない"),
        ("と言ったらある", "といったらない"),
        ("と言えなくもある", "と言えなくもない"),
        ("限りだ", "です"),
        ("それなりに", "の"),
    ],
)
def test_known_hazard_pairs_stay_separate(corpus: dict[str, object], left: str, right: str) -> None:
    keys = _keys_by_form(corpus)
    assert not (keys.get(left, set()) & keys.get(right, set()))


@pytestmark_corpus
@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("今更", "いまさら"),
        ("一旦", "いったん"),
        ("や否や", "やいなや"),
        ("を踏まえて", "を踏まえ"),
        ("に即して", "に則して"),
    ],
)
def test_known_orthographic_pairs_are_folded(
    corpus: dict[str, object], left: str, right: str
) -> None:
    keys = _keys_by_form(corpus)
    assert keys.get(left, set()) & keys.get(right, set()), f"{left}/{right} not folded"


@pytestmark_corpus
def test_a_homograph_fan_is_never_collapsed(corpus: dict[str, object]) -> None:
    """A source may contribute two rows to one point only via a Tier B pair."""
    merged = {item["canonicalKey"] for item in corpus["report"]["tierB"]["pointsMerged"]}
    offenders = []
    for point in corpus["points"]:
        per_source = collections.Counter(c["source"] for c in point["contributors"])
        if any(count > 1 for count in per_source.values()) and point["canonicalKey"] not in merged:
            offenders.append(point["canonicalKey"])
    assert offenders == []


@pytestmark_corpus
def test_tier_b_merges_never_cascade(corpus: dict[str, object]) -> None:
    merges = corpus["report"]["tierB"]["pointsMerged"]
    absorbed = collections.Counter(item["canonicalKey"] for item in merges)
    assert absorbed and max(absorbed.values()) == 1
    live = {point["canonicalKey"] for point in corpus["points"]}
    assert not [item for item in merges if item["absorbedKey"] in live]


@pytestmark_corpus
def test_classical_points_are_axis_scoped(corpus: dict[str, object]) -> None:
    for point in corpus["points"]:
        if point["axes"]["era"] == "classical":
            assert point["canonicalKey"].startswith(("standard/classical:", "dialect/classical:"))


@pytestmark_corpus
def test_no_declared_alias_row_is_a_contributor(corpus: dict[str, object]) -> None:
    alias_ids, substantive_ids = set(), set()
    for path in sorted(EXTRACTED.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["points"]:
            identity = (payload["source"], row["source_id"], substance_hash(row))
            (alias_ids if is_declared_alias(row) else substantive_ids).add(identity)
    leaked = [
        contributor
        for point in corpus["points"]
        for contributor in point["contributors"]
        if (contributor["source"], contributor["sourceId"], contributor["substanceHash"])
        in alias_ids - substantive_ids
    ]
    assert leaked == []


@pytestmark_corpus
def test_build_is_deterministic(corpus: dict[str, object]) -> None:
    assert dump_json(build_keymap(EXTRACTED)) == dump_json(corpus)


@pytestmark_corpus
def test_published_artifact_matches_a_fresh_build() -> None:
    """data/merge/keymap.json must not drift from the producing code."""
    published = pathlib.Path("data/merge/keymap.json")
    if not published.is_file():
        pytest.skip("keymap.json not built; run scripts/build_keymap.py")
    assert dump_json(json.loads(published.read_text(encoding="utf-8"))) == dump_json(
        build_keymap(EXTRACTED)
    )


def _keys_by_form(corpus: dict[str, object]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {}
    for point in corpus["points"]:
        for form in point["lookupForms"]:
            keys.setdefault(form, set()).add(point["canonicalKey"])
    return keys


# --------------------------------------------------------------------------
# Downstream grouping: a refusal must not become N unrelated cards
# --------------------------------------------------------------------------


def test_refused_senses_share_a_bucket_key_for_downstream_grouping() -> None:
    """The card generator groups on bucketKey, never by splitting canonicalKey."""
    payload = build_keymap_from(
        edewakaru=[
            record("a", "ない", meaning="one"),
            record("b", "ない", meaning="two"),
            record("c", "ない", meaning="three"),
        ]
    )
    points = payload["points"]
    assert len(points) == 3
    assert {point["bucketKey"] for point in points} == {"ない"}
    assert sorted(point["disambiguator"] for point in points) == ["sense1", "sense2", "sense3"]


def test_a_folded_point_has_an_empty_disambiguator() -> None:
    payload = build_keymap_from(
        dojg=[record("ながら", "ながら", meaning="while")],
        edewakaru=[record("ながら", "ながら", meaning="although")],
    )
    point = payload["points"][0]
    assert point["disambiguator"] == ""
    assert point["bucketKey"] == point["canonicalKey"] == "ながら"


def test_bucket_key_excludes_the_axis_prefix() -> None:
    """bucketKey is the bare headword; the axis lives in axes/canonicalKey."""
    payload = build_keymap_from(
        dojg=[record("ごとし", "ごとし", meaning="like", notes="古語")],
    )
    point = payload["points"][0]
    assert point["canonicalKey"] == "standard/classical:ごとし"
    assert point["bucketKey"] == "ごとし"
    assert point["axes"] == {"variety": "standard", "era": "classical"}


@pytestmark_corpus
def test_every_refused_collision_stays_groupable(corpus: dict[str, object]) -> None:
    """Each refused sense card must be reachable by grouping on bucketKey.

    A sense may legitimately leave its origin bucket: Tier B moved
    `ことになる#sense5` into the `こととなる` point when the producers attested the
    pair. So the assertion is that every named key still *exists* and carries a
    bucketKey that groups it with its siblings — not that the whole set shares one
    bucket, which Tier B is allowed to break.
    """
    by_key = {point["canonicalKey"]: point for point in corpus["points"]}
    for item in corpus["report"]["tierA"]["refusedCollisions"]:
        for key in item["canonicalKeys"]:
            assert key in by_key, f"{key} named by a refusal but no longer a point"
            point = by_key[key]
            # Its bucketKey must group it with the other cards of that same bucket.
            siblings = [
                other
                for other in corpus["points"]
                if other["bucketKey"] == point["bucketKey"]
                and other["axes"] == point["axes"]
            ]
            assert point in siblings


@pytestmark_corpus
def test_no_refusal_names_a_key_tier_b_later_absorbed(corpus: dict[str, object]) -> None:
    """Collisions are recorded before Tier B; the report must be restated after.

    Measured: `ことになる#sense5`, `に従って#sense4` and `ようとする#sense6` were each
    absorbed into a variant pair after their bucket was recorded as refused. A
    report naming a key that no longer exists sends a reviewer to a dead card.
    """
    live = {point["canonicalKey"] for point in corpus["points"]}
    dangling = [
        key
        for item in corpus["report"]["tierA"]["refusedCollisions"]
        for key in item["canonicalKeys"]
        if key not in live
    ]
    assert dangling == []


@pytestmark_corpus
def test_absorbed_tier_b_keys_leave_no_dangling_bucket(corpus: dict[str, object]) -> None:
    live = {point["canonicalKey"] for point in corpus["points"]}
    for item in corpus["report"]["tierB"]["pointsMerged"]:
        assert item["absorbedKey"] not in live
        assert item["canonicalKey"] in live
