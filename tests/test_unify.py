"""Tests for the merge stage: many per-source rows -> ONE unified dataset.

The properties asserted here are the ones whose violation is invisible in a
green build: a stale keymap silently deleting a third of the corpus, an example
vanishing without appearing in the removal count, a written form becoming
unfindable, a JLPT conflict being quietly reconciled, or the AI channel leaking
into human-authored fields.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.jsonio import MalformedPayload, dump_json
from bugd.model import Example
from bugd.unify import (
    KIND_POINT,
    KIND_REDIRECT,
    Contribution,
    StaleKeymap,
    build_redirects,
    choose_headword,
    contribution_from_json,
    contribution_to_json,
    dedupe_examples,
    ensure_consistent,
    entry_from_json,
    entry_to_json,
    load_extracted,
    load_keymap,
    natural_key,
    parse_keymap,
    read_unified,
    run_unify,
    unify,
    write_unified,
)

# --------------------------------------------------------------------------
# fixtures: a tiny corpus with the same shape as the real one
# --------------------------------------------------------------------------


def _row(source, source_id, expression, **extra):
    record = {
        "source": source,
        "source_id": source_id,
        "expression": expression,
        "variants": [],
        "reading": extra.pop("reading", expression),
        "meaning": None,
        "structure": None,
        "nuance": None,
        "explanation": None,
        "notes": None,
        "jlpt": None,
        "examples": [],
        "tags": [],
        "ai_generated": {},
        "provenance": {},
    }
    record.update(extra)
    return record


def _example(japanese, english=None, ai=False, highlight=()):
    return {
        "japanese": japanese,
        "english": english,
        "highlight": list(highlight),
        "ai_generated": ai,
    }


def _point(canonical_key, bucket_key, expression, **extra):
    point = {
        "canonicalKey": canonical_key,
        "bucketKey": bucket_key,
        "expression": expression,
        "axes": {"variety": "standard", "era": "modern"},
        "disambiguator": extra.pop("disambiguator", ""),
        "lookupForms": extra.pop("lookupForms", [expression]),
        "jlptLevels": extra.pop("jlptLevels", []),
        "observedRegisters": extra.pop("observedRegisters", []),
        "observedSignatures": extra.pop("observedSignatures", []),
        "contributors": [],
        "sourceCount": 1,
    }
    point.update(extra)
    return point


def _keymap(rows_to_keys, points):
    from bugd.keymap import substance_hash

    return parse_keymap(
        {
            "schemaVersion": 1,
            "assignments": [
                {
                    "source": source,
                    "sourceId": record["source_id"],
                    "substanceHash": substance_hash(record),
                    "canonicalKey": key,
                }
                for source, record, key in rows_to_keys
            ],
            "points": points,
        }
    )


# --------------------------------------------------------------------------
# the fail-closed gate that motivated this stage's design
# --------------------------------------------------------------------------


def test_a_substantive_row_missing_from_the_keymap_fails_closed():
    """The defect this stage exists to make impossible.

    A keymap built against a superseded extraction left 1,664 substantive rows
    unresolved. A merge that treated "not in the keymap" as "skip" would have
    dropped a third of the dictionary and still reported success, so an absent
    row must raise rather than be tolerated.
    """
    known = _row("dojg", "A", "あえて")
    stranger = _row("dojg", "B", "あくまでも")
    keymap = _keymap([("dojg", known, "あえて")], [_point("あえて", "あえて", "あえて")])

    with pytest.raises(StaleKeymap) as caught:
        ensure_consistent([("dojg", known), ("dojg", stranger)], keymap)
    assert "dojg:B" in str(caught.value)
    # The message must name the fix, not just the symptom.
    assert "make keymap" in str(caught.value)


def test_a_declared_alias_is_allowed_to_be_unassigned():
    """Aliases are demoted to lookup forms by design, so they are not a defect."""
    assigned = _row("donna_toki", "A", "あいまって")
    alias = _row(
        "donna_toki",
        "B",
        "相まって",
        provenance={"entryShape": "alias-redirect", "aliasOf": "あいまって"},
    )
    keymap = _keymap(
        [("donna_toki", assigned, "あいまって")],
        [_point("あいまって", "あいまって", "あいまって")],
    )
    ensure_consistent([("donna_toki", assigned), ("donna_toki", alias)], keymap)


def test_a_mutated_substance_hash_is_caught_not_silently_reassigned():
    """Editing a row's prose changes its identity; the merge must notice."""
    record = _row("dojg", "A", "あえて", meaning="Deliberately")
    keymap = _keymap([("dojg", record, "あえて")], [_point("あえて", "あえて", "あえて")])
    edited = dict(record, meaning="Deliberately (revised)")
    with pytest.raises(StaleKeymap):
        ensure_consistent([("dojg", edited)], keymap)


def test_an_unreadable_keymap_schema_is_refused():
    with pytest.raises(MalformedPayload, match="schemaVersion"):
        parse_keymap({"schemaVersion": 99, "assignments": [], "points": []})


def test_an_assignment_naming_an_unknown_point_is_refused():
    """A dangling canonicalKey means the artifact is internally inconsistent."""
    with pytest.raises(MalformedPayload, match="no point record"):
        parse_keymap(
            {
                "schemaVersion": 1,
                "assignments": [
                    {
                        "source": "dojg",
                        "sourceId": "A",
                        "substanceHash": "deadbeef",
                        "canonicalKey": "missing",
                    }
                ],
                "points": [],
            }
        )


def test_a_missing_keymap_file_names_the_command_that_builds_it(tmp_path):
    with pytest.raises(MalformedPayload) as caught:
        load_keymap(tmp_path / "absent.json")
    assert "make keymap" in str(caught.value)


# --------------------------------------------------------------------------
# grouping: refused senses become ONE entry, not N cards
# --------------------------------------------------------------------------


def test_refused_senses_of_one_bucket_become_one_entry_with_ordered_senses():
    """UGD-07 refuses to fold senses it cannot prove identical.

    Rendering those as sibling cards for one lookup form is the outcome the
    matcher explicitly asked this stage to avoid, so they must arrive as one
    entry carrying several senses.
    """
    first = _row("edewakaru", "1", "ない", meaning="Negative")
    second = _row("edewakaru", "2", "ない", meaning="Nonexistent")
    keymap = _keymap(
        [("edewakaru", first, "ない#sense1"), ("edewakaru", second, "ない#sense2")],
        [
            _point("ない#sense1", "ない", "ない", disambiguator="sense1"),
            _point("ない#sense2", "ない", "ない", disambiguator="sense2"),
        ],
    )
    entries, _ = unify(
        [("edewakaru", first), ("edewakaru", second)], keymap, {"edewakaru": "絵でわかる"}
    )
    points = [e for e in entries if e.kind == KIND_POINT]
    assert len(points) == 1
    assert [s.disambiguator for s in points[0].senses] == ["sense1", "sense2"]


def test_ordinal_senses_are_ordered_numerically_not_lexicographically():
    """`#sense10` must not sort before `#sense2`.

    18 real buckets carry >=10 ordinal senses (`お` has 14, `あまり` 11), so
    lexicographic ordering visibly shuffles the producer's own sense order on the
    busiest cards in the dictionary.
    """
    rows = [_row("edewakaru", str(n), "お", meaning=f"sense {n}") for n in range(1, 12)]
    keymap = _keymap(
        [("edewakaru", row, f"お#sense{n}") for n, row in enumerate(rows, start=1)],
        [
            _point(f"お#sense{n}", "お", "お", disambiguator=f"sense{n}")
            for n in range(1, 12)
        ],
    )
    entries, _ = unify(
        [("edewakaru", row) for row in rows], keymap, {"edewakaru": "絵でわかる"}
    )
    ordinals = [int(s.disambiguator.removeprefix("sense")) for s in entries[0].senses]
    assert ordinals == list(range(1, 12))
    # And the primitive itself, so the property survives a refactor of `unify`.
    assert natural_key("sense2") < natural_key("sense10")
    assert sorted(["sense10", "sense2"], key=natural_key) == ["sense2", "sense10"]


def test_the_bucket_key_wins_as_headword_when_a_source_writes_it_that_way():
    """1,679 of 1,696 real buckets are written as their key by some source."""
    assert choose_headword("に対して", ["に対する", "に対して"]) == "に対して"


def test_a_headword_is_never_synthesised_when_no_source_writes_the_bucket_key():
    """The fallback must still be a form a source really publishes."""
    chosen = choose_headword("ともなく", ["ともなしに", "ともなく2"])
    assert chosen in {"ともなしに", "ともなく2"}


def test_choosing_a_headword_with_no_expressions_is_refused():
    with pytest.raises(MalformedPayload):
        choose_headword("x", [])


# --------------------------------------------------------------------------
# every source keeps its attribution and its substance
# --------------------------------------------------------------------------


def test_each_source_keeps_its_own_labelled_contribution():
    """Two sources describing one point stay two attributed statements."""
    a = _row("dojg", "A", "から", meaning="Because", jlpt="N5")
    b = _row("nihongo_net", "B", "から", meaning="Since", jlpt="N4")
    keymap = _keymap(
        [("dojg", a, "から"), ("nihongo_net", b, "から")],
        [_point("から", "から", "から", jlptLevels=["N4", "N5"])],
    )
    entries, stats = unify(
        [("dojg", a), ("nihongo_net", b)],
        keymap,
        {"dojg": "DoJG", "nihongo_net": "日本語NET"},
    )
    entry = entries[0]
    assert entry.sources == ("dojg", "nihongo_net")
    assert [c.source_label for c in entry.contributions] == ["DoJG", "日本語NET"]
    # Both meanings survive; neither is chosen over the other at merge time.
    assert {c.meaning for c in entry.contributions} == {"Because", "Since"}
    assert stats["unified"]["multiSourceEntries"] == 1


def test_conflicting_jlpt_levels_are_shown_side_by_side_never_reconciled():
    """158 real entries disagree across sources; both statements are true."""
    a = _row("edewakaru", "A", "に反して", jlpt="N3")
    b = _row("nihongo_no_sensei", "B", "に反して", jlpt="N2")
    keymap = _keymap(
        [("edewakaru", a, "に反して"), ("nihongo_no_sensei", b, "に反して")],
        [_point("に反して", "に反して", "に反して", jlptLevels=["N2", "N3"])],
    )
    entries, stats = unify(
        [("edewakaru", a), ("nihongo_no_sensei", b)],
        keymap,
        {"edewakaru": "絵", "nihongo_no_sensei": "毎日"},
    )
    entry = entries[0]
    assert entry.jlpt_levels == ("N2", "N3")
    assert {(c.source, c.jlpt) for c in entry.contributions} == {
        ("edewakaru", "N3"),
        ("nihongo_no_sensei", "N2"),
    }
    assert stats["jlpt"]["entriesWithConflictingLevels"] == 1


def test_furigana_readings_are_preserved_per_contribution():
    """Every contribution keeps its own reading; the entry exposes a differing one."""
    row = _row("dojg", "A", "所詮", reading="しょせん", meaning="After all")
    keymap = _keymap([("dojg", row, "所詮")], [_point("所詮", "所詮", "所詮")])
    entries, _ = unify([("dojg", row)], keymap, {"dojg": "DoJG"})
    assert entries[0].reading == "しょせん"
    assert entries[0].contributions[0].reading == "しょせん"


def test_a_reading_identical_to_the_headword_is_not_carried_as_furigana():
    """Yomitan renders `reading == expression` as a redundant furigana pair."""
    row = _row("dojg", "A", "から", reading="から")
    keymap = _keymap([("dojg", row, "から")], [_point("から", "から", "から")])
    entries, _ = unify([("dojg", row)], keymap, {"dojg": "DoJG"})
    assert entries[0].reading is None
    # ...but the contribution still records what the source said.
    assert entries[0].contributions[0].reading == "から"


# --------------------------------------------------------------------------
# example de-duplication is scoped per source, and never empties a section
# --------------------------------------------------------------------------


def _contribution(source, source_id, sentences, **extra):
    return Contribution(
        source=source,
        source_id=source_id,
        source_label=source,
        canonical_key="k",
        expression="x",
        reading=None,
        meaning=extra.pop("meaning", None),
        structure=None,
        nuance=None,
        explanation=None,
        notes=None,
        jlpt=None,
        examples=tuple(Example(japanese=s) for s in sentences),
        **extra,
    )


def test_a_sentence_repeated_by_one_source_is_shown_once():
    kept, removed = dedupe_examples(
        [_contribution("dojg", "A", ["同じ文。", "別の文。"], meaning="m"),
         _contribution("dojg", "B", ["同じ文。"], meaning="m")]
    )
    assert removed == 1
    assert [len(c.examples) for c in kept] == [2, 0]
    assert kept[1].duplicate_examples_removed == 1


def test_the_same_sentence_from_two_sources_is_kept_twice():
    """Cross-source repetition is evidence two dictionaries agree, not noise.

    Exactly ONE duplicated sentence in the whole real corpus crosses a source
    boundary against 622 that repeat inside one source, so a global scope would
    erase that signal while removing almost nothing extra.
    """
    kept, removed = dedupe_examples(
        [_contribution("dojg", "A", ["同じ文。"], meaning="m"),
         _contribution("nihongo_net", "B", ["同じ文。"], meaning="m")]
    )
    assert removed == 0
    assert [len(c.examples) for c in kept] == [1, 1]


def test_dedup_never_empties_a_contribution_that_has_nothing_else_to_show():
    """`keep-last-when-emptied`.

    106 real rows are emptied by naive first-wins de-duplication and 4 of them
    carry no other substance, so they would render as a blank per-source section
    -- which reads as a broken card rather than as honest de-duplication.
    """
    kept, removed = dedupe_examples(
        [_contribution("dojg", "A", ["唯一の文。"], meaning="has prose"),
         _contribution("dojg", "B", ["唯一の文。"])]
    )
    # The second contribution has no meaning/structure/prose of its own, so its
    # only example is restored rather than leaving it invisible.
    assert [len(c.examples) for c in kept] == [1, 1]
    assert removed == 0


def test_dedup_does_empty_a_contribution_that_still_has_prose():
    """The exception is narrow: prose keeps the section visible on its own."""
    kept, removed = dedupe_examples(
        [_contribution("dojg", "A", ["唯一の文。"], meaning="m"),
         _contribution("dojg", "B", ["唯一の文。"], meaning="different prose")]
    )
    assert [len(c.examples) for c in kept] == [1, 0]
    assert removed == 1


def test_examples_are_conserved_end_to_end():
    """Nothing may vanish without being counted as removed."""
    a = _row("dojg", "A", "から", meaning="m", examples=[_example("文一。"), _example("文二。")])
    b = _row("dojg", "B", "から", meaning="m2", examples=[_example("文一。"), _example("文三。")])
    keymap = _keymap(
        [("dojg", a, "から#sense1"), ("dojg", b, "から#sense2")],
        [
            _point("から#sense1", "から", "から", disambiguator="sense1"),
            _point("から#sense2", "から", "から", disambiguator="sense2"),
        ],
    )
    entries, stats = unify([("dojg", a), ("dojg", b)], keymap, {"dojg": "DoJG"})
    before = 4
    after = stats["examples"]["total"]
    assert after + stats["examples"]["sameSourceDuplicatesRemoved"] == before
    assert after == 3


# --------------------------------------------------------------------------
# the AI channel stays segregated (fixtures, not corpus evidence)
# --------------------------------------------------------------------------


def test_ai_generated_fields_travel_in_their_own_channel():
    """No source ships AI fields yet, so this is proven synthetically.

    The point is structural: an AI-authored gloss must never land in `meaning`,
    where a renderer would present it as authoritative dictionary fact.
    """
    row = _row(
        "bunpou",
        "A",
        "からこそ",
        meaning="Precisely because",
        ai_generated={"mnemonic": "LLM-written memory hook", "difficulty": "hard"},
    )
    keymap = _keymap([("bunpou", row, "からこそ")], [_point("からこそ", "からこそ", "からこそ")])
    entries, stats = unify([("bunpou", row)], keymap, {"bunpou": "文法"})
    contribution = entries[0].contributions[0]
    assert contribution.ai_generated == {
        "mnemonic": "LLM-written memory hook",
        "difficulty": "hard",
    }
    # Human-authored substance is untouched by the AI channel.
    assert contribution.meaning == "Precisely because"
    assert "LLM" not in (contribution.meaning or "")
    assert stats["aiChannel"]["contributionsWithAiFields"] == 1
    # And it survives a serialisation round trip under its own key.
    payload = contribution_to_json(contribution)
    assert payload["aiGenerated"] == contribution.ai_generated
    assert payload["meaning"] == "Precisely because"
    assert contribution_from_json(payload).ai_generated == contribution.ai_generated


def test_an_ai_flagged_example_keeps_its_flag_through_the_merge():
    row = _row(
        "bunpou",
        "A",
        "からこそ",
        meaning="m",
        examples=[_example("人が書いた文。"), _example("AIが書いた文。", ai=True)],
    )
    keymap = _keymap([("bunpou", row, "からこそ")], [_point("からこそ", "からこそ", "からこそ")])
    entries, stats = unify([("bunpou", row)], keymap, {"bunpou": "文法"})
    flags = {e.japanese: e.ai_generated for e in entries[0].contributions[0].examples}
    assert flags == {"人が書いた文。": False, "AIが書いた文。": True}
    assert stats["aiChannel"]["aiFlaggedExamples"] == 1


def test_the_ai_channel_reports_zero_without_claiming_it_is_absent():
    """A zero must never read as "the channel was dropped"."""
    row = _row("dojg", "A", "から", meaning="m")
    keymap = _keymap([("dojg", row, "から")], [_point("から", "から", "から")])
    _, stats = unify([("dojg", row)], keymap, {"dojg": "DoJG"})
    assert stats["aiChannel"]["contributionsWithAiFields"] == 0
    assert stats["aiChannel"]["channelPreserved"] is True
    assert "synthetic fixtures" in stats["aiChannel"]["note"]
    assert "fixture-covered" in stats["media"]["note"]


def test_an_ai_channel_that_is_not_an_object_is_refused():
    row = _row("bunpou", "A", "からこそ", ai_generated="not an object")
    keymap = _keymap([("bunpou", row, "からこそ")], [_point("からこそ", "からこそ", "からこそ")])
    with pytest.raises(MalformedPayload, match="ai_generated"):
        unify([("bunpou", row)], keymap, {"bunpou": "文法"})


# --------------------------------------------------------------------------
# findability: no written form the corpus ships becomes unlookupable
# --------------------------------------------------------------------------


def test_a_declared_alias_becomes_a_redirect_to_the_form_holding_the_substance():
    real = _row("donna_toki", "A", "とあいまって", meaning="Combined with")
    alias = _row(
        "donna_toki",
        "B",
        "相まって",
        provenance={"entryShape": "alias-redirect", "aliasOf": "とあいまって"},
    )
    keymap = _keymap(
        [("donna_toki", real, "とあいまって")],
        [_point("とあいまって", "とあいまって", "とあいまって")],
    )
    entries, stats = unify(
        [("donna_toki", real), ("donna_toki", alias)], keymap, {"donna_toki": "どんなとき"}
    )
    redirect = next(e for e in entries if e.kind == KIND_REDIRECT)
    assert redirect.expression == "相まって"
    assert redirect.redirect_targets == ("とあいまって",)
    assert redirect.redirect_basis == "declared"
    assert stats["redirects"]["byBasis"] == {"declared": 1}


def test_a_form_folded_into_a_differently_written_entry_still_redirects():
    """`いったん` was folded into `一旦`; without a redirect it is unfindable.

    33 real forms are in this position: their own rows were folded into an entry
    written differently, and they carry no alias declaration to fall back on.
    """
    kanji = _row("edewakaru", "A", "一旦", meaning="Once")
    kana = _row("nihongo_net", "B", "いったん", meaning="Once")
    keymap = _keymap(
        [("edewakaru", kanji, "一旦"), ("nihongo_net", kana, "一旦")],
        [_point("一旦", "一旦", "一旦", lookupForms=["一旦", "いったん"])],
    )
    entries, stats = unify(
        [("edewakaru", kanji), ("nihongo_net", kana)],
        keymap,
        {"edewakaru": "絵", "nihongo_net": "NET"},
    )
    redirect = next(e for e in entries if e.kind == KIND_REDIRECT)
    assert (redirect.expression, redirect.redirect_targets) == ("いったん", ("一旦",))
    assert redirect.redirect_basis == "folded"


def test_a_kana_only_declared_target_resolves_through_a_unique_reading():
    """The producer's `aliasOf` is kana while entries are keyed on kanji.

    41 real forms are only reachable this way, and the rule is deliberately
    conservative: a reading landing in more than one entry is NOT guessed at.
    """
    real = _row("donna_toki", "A", "を皮切りに", reading="をかわきりに", meaning="Starting with")
    alias = _row(
        "donna_toki",
        "B",
        "かわきりに",
        provenance={"entryShape": "alias-redirect", "aliasOf": "をかわきりに"},
    )
    keymap = _keymap(
        [("donna_toki", real, "を皮切りに")],
        [_point("を皮切りに", "を皮切りに", "を皮切りに")],
    )
    entries, stats = unify(
        [("donna_toki", real), ("donna_toki", alias)], keymap, {"donna_toki": "どんなとき"}
    )
    redirect = next(e for e in entries if e.kind == KIND_REDIRECT)
    assert redirect.redirect_targets == ("を皮切りに",)
    assert redirect.redirect_basis == "reading"


def test_an_ambiguous_reading_is_reported_unresolved_rather_than_guessed():
    """Two candidate entries means the target is unknown, not 50/50."""
    a = _row("donna_toki", "A", "を禁じ得ない", reading="をきんじえない", meaning="Cannot help")
    b = _row("donna_toki", "B", "を禁じえない", reading="をきんじえない", meaning="Cannot help but")
    alias = _row(
        "donna_toki",
        "C",
        "禁じ得ない",
        provenance={"entryShape": "alias-redirect", "aliasOf": "をきんじえない"},
    )
    keymap = _keymap(
        [("donna_toki", a, "を禁じ得ない"), ("donna_toki", b, "を禁じえない")],
        [
            _point("を禁じ得ない", "を禁じ得ない", "を禁じ得ない"),
            _point("を禁じえない", "を禁じえない", "を禁じえない"),
        ],
    )
    entries, stats = unify(
        [("donna_toki", a), ("donna_toki", b), ("donna_toki", alias)],
        keymap,
        {"donna_toki": "どんなとき"},
    )
    assert not [e for e in entries if e.kind == KIND_REDIRECT]
    assert stats["redirects"]["unresolvedCount"] == 1
    report = stats["redirects"]["unresolved"][0]
    assert report["expression"] == "禁じ得ない"
    # The report must name BOTH candidates so a human can adjudicate.
    assert len(report["readingCandidates"]) == 2


def test_a_redirect_never_points_at_a_form_that_does_not_exist():
    """An unresolvable alias must be reported, never given a dangling target."""
    real = _row("donna_toki", "A", "ある", meaning="Exists")
    alias = _row(
        "donna_toki",
        "B",
        "それまでだ",
        provenance={"entryShape": "alias-redirect"},
    )
    keymap = _keymap([("donna_toki", real, "ある")], [_point("ある", "ある", "ある")])
    entries, stats = unify(
        [("donna_toki", real), ("donna_toki", alias)], keymap, {"donna_toki": "どんなとき"}
    )
    heads = {e.expression for e in entries if e.kind == KIND_POINT}
    for entry in entries:
        if entry.kind == KIND_REDIRECT:
            assert set(entry.redirect_targets) <= heads
    assert stats["redirects"]["unresolvedCount"] == 1


def test_a_redirect_entry_may_not_carry_senses_and_a_point_must():
    """The two kinds are structurally distinct, so neither can impersonate the other."""
    from bugd.unify import UnifiedEntry

    with pytest.raises(MalformedPayload, match="at least one sense"):
        UnifiedEntry(
            entry_id="x", kind=KIND_POINT, expression="x", reading=None,
            axes={"variety": "standard", "era": "modern"}, bucket_key="x",
            lookup_forms=("x",),
        )
    with pytest.raises(MalformedPayload, match="must not carry senses"):
        UnifiedEntry(
            entry_id="x", kind=KIND_REDIRECT, expression="x", reading=None,
            axes={"variety": "standard", "era": "modern"}, bucket_key="x",
            lookup_forms=("x",), senses=(object(),),  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------
# artifact: deterministic, round-trippable, JSONL
# --------------------------------------------------------------------------


def test_the_artifact_is_byte_identical_across_repeated_runs(tmp_path):
    a = _row("dojg", "A", "から", meaning="Because", examples=[_example("文。")])
    b = _row("nihongo_net", "B", "から", meaning="Since")
    keymap = _keymap(
        [("dojg", a, "から"), ("nihongo_net", b, "から")],
        [_point("から", "から", "から")],
    )
    rows = [("dojg", a), ("nihongo_net", b)]
    labels = {"dojg": "DoJG", "nihongo_net": "NET"}

    first, _ = unify(rows, keymap, labels)
    second, _ = unify(rows, keymap, labels)
    path_a, path_b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_unified(first, path_a)
    write_unified(second, path_b)
    assert path_a.read_bytes() == path_b.read_bytes()


def test_every_entry_survives_a_json_round_trip():
    row = _row(
        "dojg",
        "A",
        "所詮",
        reading="しょせん",
        meaning="After all",
        structure="Noun + 所詮",
        jlpt="N1",
        tags=["DOJG"],
        examples=[_example("文。", english="A sentence.", highlight=["所詮"])],
        provenance={"volume": "上級"},
    )
    keymap = _keymap(
        [("dojg", row, "所詮")],
        [_point("所詮", "所詮", "所詮", jlptLevels=["N1"], observedRegisters=["formal"])],
    )
    entries, _ = unify([("dojg", row)], keymap, {"dojg": "DoJG"})
    for entry in entries:
        assert entry_from_json(entry_to_json(entry)) == entry


def test_the_artifact_is_one_entry_per_line(tmp_path):
    row = _row("dojg", "A", "から", meaning="m")
    keymap = _keymap([("dojg", row, "から")], [_point("から", "から", "から")])
    entries, _ = unify([("dojg", row)], keymap, {"dojg": "DoJG"})
    path = tmp_path / "unified.jsonl"
    write_unified(entries, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(entries)
    assert all(json.loads(line)["entryId"] for line in lines)
    assert read_unified(path) == entries


def test_a_corrupt_line_names_its_line_number(tmp_path):
    path = tmp_path / "unified.jsonl"
    path.write_text('{"entryId":"a","kind":"point","expression":"x"}\n', encoding="utf-8")
    with pytest.raises(MalformedPayload, match=r"unified\.jsonl:1"):
        read_unified(path)


# --------------------------------------------------------------------------
# real-corpus properties
#
# These run against the checked-out extraction and keymap. They are pinned so a
# source re-extraction or a keymap rebuild that changes the shape of the merge
# fails ON PURPOSE rather than shipping a silently different dictionary.
# --------------------------------------------------------------------------

REPO = pathlib.Path(__file__).resolve().parents[1]
EXTRACTED = REPO / "data" / "extracted"
KEYMAP = REPO / "data" / "merge" / "keymap.json"

requires_corpus = pytest.mark.skipif(
    not EXTRACTED.is_dir() or not any(EXTRACTED.glob("*.json")) or not KEYMAP.is_file(),
    reason="no extracted corpus + keymap on disk (run `make extract && make keymap`)",
)


@pytest.fixture(scope="module")
def corpus():
    rows, labels = load_extracted(EXTRACTED)
    entries, stats = unify(rows, load_keymap(KEYMAP), labels)
    return rows, entries, stats


@requires_corpus
def test_the_real_corpus_merges_into_the_expected_shape(corpus):
    rows, entries, stats = corpus
    # Every number below moved when UGD-03 added the Bunpro source. Attributed by
    # running keymap+merge with and without data/extracted/bunpro.json: the row
    # delta is exactly its 964 records (4972 -> 5936) and no source disappears.
    assert stats["corpus"]["sourceRows"] == 5936
    assert stats["unified"]["pointEntries"] == 2100
    assert stats["unified"]["redirectEntries"] == 805
    assert stats["unified"]["entries"] == 2905
    # 3,179 canonical points collapse into 2,100 entries: the refused senses the
    # matcher could not fold arrive as senses, not as sibling cards.
    assert stats["unified"]["senses"] == 3179
    assert stats["unified"]["multiSenseEntries"] == 221
    assert stats["unified"]["multiSourceEntries"] == 878
    assert len(stats["corpus"]["sources"]) == 6
    assert "bunpro" in stats["corpus"]["sources"]


@requires_corpus
def test_every_assigned_row_reaches_the_unified_dataset_exactly_once(corpus):
    """The conservation property a silent drop would violate."""
    from bugd.keymap import substance_hash

    rows, entries, stats = corpus
    keymap = load_keymap(KEYMAP)
    unique = set()
    for source, record in rows:
        if keymap.key_for(source, record) is None:
            continue
        unique.add((source, str(record["source_id"]), substance_hash(record)))

    seen = [
        (c.source, c.source_id, c.canonical_key)
        for entry in entries
        if entry.kind == KIND_POINT
        for c in entry.contributions
    ]
    assert len(seen) == len(set(seen)) == len(unique) == stats["unified"]["contributions"]


@requires_corpus
def test_no_example_disappears_without_being_counted(corpus):
    from bugd.keymap import substance_hash

    rows, entries, stats = corpus
    keymap = load_keymap(KEYMAP)
    seen: set[tuple[str, str, str]] = set()
    before = 0
    for source, record in rows:
        if keymap.key_for(source, record) is None:
            continue
        identity = (source, str(record["source_id"]), substance_hash(record))
        if identity in seen:
            continue
        seen.add(identity)
        before += len(record.get("examples") or [])
    assert before == stats["examples"]["total"] + stats["examples"][
        "sameSourceDuplicatesRemoved"
    ]


@requires_corpus
def test_every_written_form_in_the_corpus_stays_findable(corpus):
    """Only the 4 forms the stats report as unresolved may be unreachable."""
    rows, entries, stats = corpus
    corpus_forms = {str(record["expression"]) for _, record in rows}
    reachable = {entry.expression for entry in entries}
    unresolved = {item["expression"] for item in stats["redirects"]["unresolved"]}
    assert corpus_forms - reachable == unresolved
    # Was 5 before UGD-03. Bunpro supplies それまでだ as a real N1 point, resolving
    # the redirect donna_toki declared as `aliasOf: それまでだ` that dangled while
    # no source carried that headword. Attributed by running keymap+merge with
    # and without bunpro.json: それまでだ is the only form that leaves this set,
    # and nothing new enters it.
    assert len(unresolved) == 4
    assert "それまでだ" not in unresolved


@requires_corpus
def test_every_redirect_target_is_a_real_point_entry(corpus):
    _, entries, _ = corpus
    heads = {e.expression for e in entries if e.kind == KIND_POINT}
    for entry in entries:
        if entry.kind == KIND_REDIRECT:
            assert entry.redirect_targets, entry.expression
            assert set(entry.redirect_targets) <= heads, entry.expression


@requires_corpus
def test_the_redirect_basis_breakdown_is_pinned(corpus):
    """Pin the emitted precedence, not a hand-counted one.

    An earlier probe counted forms by *eligibility* (696 declared / 33 folded /
    21 both), which is NOT what the code emits: `declared` is tried first and
    absorbs forms that would also have resolved as `folded`, so the emitted split
    is not the eligibility split. Pinning the emitted numbers stops the docstring
    and the handoff drifting away from the artifact again.

    UGD-03 moved this from 702/2/41 to 728/38/39. Bunpro writes its headwords with
    placeholder tildes and slot notation (`～ずつ`, `Verb[ないで]`,
    `う-Verb (Negative)`), so exactly 36 of its forms resolve by *folding* onto the
    base headword, and `declared` gains a net 26 (49 added, 23 reclassified). Two
    forms that previously needed the weaker `reading` basis -- ないほうがいい and
    関わる -- now resolve on a stronger basis, and no form newly falls back to
    `reading`. Verified by diffing the emitted per-basis form SETS with and
    without data/extracted/bunpro.json, not just the totals.
    """
    _, _, stats = corpus
    assert stats["redirects"]["byBasis"] == {"declared": 728, "folded": 38, "reading": 39}
    assert sum(stats["redirects"]["byBasis"].values()) == stats["unified"][
        "redirectEntries"
    ]
    assert stats["redirects"]["unresolvedCount"] == 4


@requires_corpus
def test_ordinal_senses_are_never_shuffled_in_the_real_corpus(corpus):
    """`#sense10` before `#sense2` would misorder 18 real entries."""
    _, entries, _ = corpus
    checked = 0
    for entry in entries:
        ordinals = [
            int(s.disambiguator.removeprefix("sense"))
            for s in entry.senses
            if s.disambiguator.startswith("sense")
            and s.disambiguator.removeprefix("sense").isdigit()
        ]
        if len(ordinals) >= 10:
            checked += 1
            assert ordinals == sorted(ordinals), entry.expression
    assert checked >= 18


@requires_corpus
def test_the_real_corpus_carries_no_ai_fields_and_no_media_but_keeps_both_channels(corpus):
    """Guards against a false claim in either direction.

    文法/UGD-02 has not landed, so a nonzero count here means a source started
    shipping AI fields and the card contract must be revisited before they are
    rendered anywhere.
    """
    _, _, stats = corpus
    assert stats["aiChannel"]["contributionsWithAiFields"] == 0
    assert stats["aiChannel"]["aiFlaggedExamples"] == 0
    assert stats["aiChannel"]["channelPreserved"] is True
    assert stats["media"]["references"] == 0


@requires_corpus
def test_conflicting_jlpt_levels_survive_the_real_merge(corpus):
    _, entries, stats = corpus
    conflicting = [e for e in entries if len(e.jlpt_levels) > 1]
    # 246 = the 158 pre-UGD-03 conflicts, unchanged, plus 88 entries where Bunpro
    # states a level that differs from another source's for the same point (e.g.
    # あげる: bunpro N5 vs nihongo_no_sensei N4). Attributed by recomputing each
    # conflicting entry's levels with bunpro's contributions excluded: exactly 88
    # entries drop to a single level, so no pre-existing conflict was lost.
    assert len(conflicting) == stats["jlpt"]["entriesWithConflictingLevels"] == 246
    # Each one must keep >1 DISTINCT level attributed to different sources,
    # otherwise the entry-level set is decorative.
    for entry in conflicting:
        per_source = {(c.source, c.jlpt) for c in entry.contributions if c.jlpt}
        assert len({level for _, level in per_source}) > 1, entry.expression


@requires_corpus
def test_bunpro_adds_jlpt_conflicts_without_erasing_the_pre_existing_ones(corpus):
    """The 158 -> 246 step must be additive, not a reshuffle.

    Pinning only the total would pass if Bunpro had destroyed pre-existing
    conflicts while adding more of its own. Recompute each conflicting entry's
    level set with Bunpro's contributions removed: the entries that still
    disagree are exactly the pre-UGD-03 population.
    """
    _, entries, _ = corpus
    conflicting = [e for e in entries if len(e.jlpt_levels) > 1]
    without_bunpro = [
        e
        for e in conflicting
        if len({c.jlpt for c in e.contributions if c.jlpt and c.source != "bunpro"}) > 1
    ]
    assert len(without_bunpro) == 158
    assert len(conflicting) - len(without_bunpro) == 88
    # Every added conflict genuinely involves Bunpro disagreeing with a peer.
    for entry in conflicting:
        if entry in without_bunpro:
            continue
        sources = {c.source for c in entry.contributions if c.jlpt}
        assert "bunpro" in sources, entry.expression
        assert len(sources) > 1, entry.expression


@requires_corpus
def test_the_real_merge_is_byte_reproducible(tmp_path, corpus):
    rows, entries, _ = corpus
    labels = load_extracted(EXTRACTED)[1]
    again, _ = unify(rows, load_keymap(KEYMAP), labels)
    first, second = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    write_unified(entries, first)
    write_unified(again, second)
    assert first.read_bytes() == second.read_bytes()


@requires_corpus
def test_the_stage_entry_point_writes_both_artifacts(tmp_path):
    stats = run_unify(
        extracted_dir=EXTRACTED,
        keymap_path=KEYMAP,
        unified_path=tmp_path / "unified.jsonl",
        stats_path=tmp_path / "unified.stats.json",
    )
    assert (tmp_path / "unified.jsonl").is_file()
    written = json.loads((tmp_path / "unified.stats.json").read_text(encoding="utf-8"))
    assert written == stats
    # The stats record which keymap produced them, so a reviewer can tell whether
    # a dataset and a keymap belong together.
    assert stats["artifact"]["keymapContentHash"]
    assert stats["artifact"]["byteCount"] > 0
