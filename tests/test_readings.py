"""Regression tests for the reading gate and the reading-correction overlay.

These assert the *property* — a contribution reading must be a structurally
possible kana rendering of its own written expression — not the nine specific
strings UGD-11c-B corrected. The gate is deliberately a structural check (see
`bugd.readings`); tests pin what it can and cannot claim so a future change that
weakens it into silently passing an impossible reading, or into flagging a
legitimate jukujikun/rendaku reading, fails here.
"""

from __future__ import annotations

import pytest

from bugd.reading_corrections import (
    ReadingCorrection,
    StaleCorrection,
    apply_corrections,
    load_corrections,
)
from bugd.readings import has_kanji, is_plausible_reading


# --------------------------------------------------------------------------
# the property: plausible vs structurally impossible
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression, reading",
    [
        # straightforward on/kun coverage
        ("結構", "けっこう"),
        ("間に", "あいだに"),
        ("込む", "こむ"),
        ("の下で", "のもとで"),
        ("の下で", "のしたで"),  # both した and もと are attested for 下
        ("んな風", "んなふう"),
        # rendaku / gemination / long-vowel allowances
        ("気味", "ぎみ"),
        ("通り", "どおり"),
        ("離れ", "ばなれ"),
        # jukujikun / gikun / ateji whole-run allowances
        ("如何", "いかん"),
        ("如何", "いかが"),
        ("心地", "ここち"),
        ("挙句", "あげく"),
        ("甲斐", "かい"),
        ("甲斐", "がい"),
        # supplementary readings (colloquial 言=ゆう, classical 如=しく)
        ("ように言う", "ようにゆう"),
        ("に如くはない", "にしくはない"),
        # inflection/particle tail may diverge from the reading
        ("ても始まる", "てもはじまらない"),
        ("には及ぶ", "にはおよばない"),
        # reading == expression is always plausible (never rendered as furigana)
        ("に決まっている", "に決まっている"),
        ("その上", "その上"),
        # no kanji: nothing to contradict
        ("だけ", "だけ"),
        ("わけにはいかない", "わけにはいかない"),
        # empty / missing reading
        ("結構", ""),
        ("結構", None),
    ],
)
def test_plausible_readings_pass(expression, reading):
    assert is_plausible_reading(expression, reading)


@pytest.mark.parametrize(
    "expression, reading",
    [
        # 構 has no カ reading, so けっか cannot be produced from 結構 — this is the
        # class the gate exists to catch. (結果 is けっか; 結構 is not.)
        ("結構", "けっか"),
        # synthetic structurally-impossible pairs (NOT any of the 9 corrected
        # strings): a common kanji forced onto an unrelated reading.
        ("水", "ひ"),        # 水 is みず/すい, never ひ
        ("犬猫", "とりうお"),  # 犬=いぬ/けん, 猫=ねこ/びょう; とりうお is impossible
        ("行く", "たべる"),   # 行 cannot read たべ
        ("日本語", "えいご"),  # structurally impossible rendering
    ],
)
def test_impossible_readings_fail(expression, reading):
    assert not is_plausible_reading(expression, reading)


def test_gate_is_structural_not_semantic():
    """The gate catches structural impossibility, not wrong-sense readings.

    Six of the nine UGD-11c-B defects carried a reading that is attested for the
    kanji but wrong for the grammar point's sense (下=した where もと is meant).
    The gate cannot and does not claim to catch those — only semantic review can.
    This test pins that boundary so no one mistakes the gate for a semantic oracle.
    """
    # attested-but-wrong-sense: gate passes (correctly, structurally)
    assert is_plausible_reading("の下で", "のしたで")
    assert is_plausible_reading("如何", "いかが")
    # genuinely impossible: gate fails
    assert not is_plausible_reading("結構", "けっか")


def test_alternative_spellings_are_judged_separately():
    """`A・B` in one headword lists alternative spellings of ONE pattern.

    NINJAL, bunpou, bunpro and IMABI write alternatives this way (43 kanji-bearing
    rows), so the reading renders EACH alternative rather than the concatenation.
    Judged as one string the gate sees two kanji runs (即, 則) and only one そく in
    the reading, and rejected four correct NINJAL readings.

    Asserted as the property, and paired with the refusal below so the relaxation
    cannot become "ignore everything after a separator".
    """
    assert is_plausible_reading("～に即して・～に則して", "～にそくして")
    assert is_plausible_reading("～反面・～半面", "～はんめん")
    assert is_plausible_reading("～に即し・～に則し", "～にそくし")


def test_one_bad_alternative_still_fails_the_gate():
    """EVERY alternative must be renderable, not merely one of them.

    The counterpart to the test above: a relaxation that accepted a headword as
    soon as any single alternative matched would let a genuine defect through on
    the back of its correct sibling.
    """
    assert not is_plausible_reading("～に即して・～結構して", "～にそくして")


def test_a_descriptive_label_headword_is_out_of_the_gates_scope():
    """One NINJAL row is a LABEL, not a headword, and the gate cannot judge it.

    `可能の形 （～れる・～られる）` with reading `～れる（かのう）` is prose describing the
    potential form, with the two suffixes parenthesised; the reading inverts that
    and parenthesises the sense tag instead. The label 可能の形 reads かのうのかたち,
    so no kana-coverage rule can relate the two sides -- stripping parentheses
    leaves the bare label and makes it worse, not better.

    Pinned as a KNOWN LIMIT rather than papered over: the gate still reports it, and
    `scripts/audit_readings.py` carries it as a documented allowance. Inventing a
    rule that passed this row would have to accept an arbitrary label/reading pair
    and would stop catching real defects. Measured scope: exactly 1 of 1,513
    kanji-bearing rows.
    """
    assert not is_plausible_reading("可能の形 （～れる・～られる）", "～れる（かのう）")


def test_annotation_handling_does_not_disarm_the_structural_gate():
    """Stripping annotation must not turn the gate into a rubber stamp.

    A structurally impossible reading is still rejected when it carries a
    parenthetical tag or an alternative separator, so the notation handling cannot
    be used to launder a defect past the gate.
    """
    assert not is_plausible_reading("結構（かんじ）", "けっか")
    assert not is_plausible_reading("結構・結構", "けっか")


def test_has_kanji():
    assert has_kanji("結構")
    assert has_kanji("の下で")
    assert not has_kanji("だけ")
    assert not has_kanji("")


# --------------------------------------------------------------------------
# the correction overlay: shape, application, fail-closed on stale
# --------------------------------------------------------------------------


def test_shipped_overlay_targets_are_plausible():
    """Every correction in the shipped overlay must produce a plausible reading.

    A correction that swaps one impossible reading for another impossible one
    would be worse than useless; this guards the overlay itself.
    """
    corrections = load_corrections()
    assert corrections, "the shipped reading-correction overlay is empty"
    for c in corrections:
        assert is_plausible_reading(c.expression, c.to_reading), (
            f"correction {c.source}:{c.source_id} {c.from_reading!r}->{c.to_reading!r} "
            f"produces an implausible reading"
        )


def _row(source, source_id, expression, reading):
    return (
        source,
        {"source": source, "source_id": source_id, "expression": expression, "reading": reading},
    )


def test_apply_corrections_rewrites_matched_row():
    rows = [
        _row("edewakaru", "込む", "込む", "ごむ"),
        _row("dojg", "結構", "結構", "けっこう"),  # already correct, untouched
    ]
    corrections = [
        ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "test"),
    ]
    out, applied = apply_corrections(rows, corrections)
    assert out[0][1]["reading"] == "こむ"
    assert out[1][1]["reading"] == "けっこう"
    assert applied == [
        {"source": "edewakaru", "source_id": "込む", "expression": "込む", "from": "ごむ", "to": "こむ"}
    ]


def test_apply_corrections_is_byte_exact_on_from():
    """A correction only fires when the on-disk reading matches `from` exactly."""
    rows = [_row("edewakaru", "込む", "込む", "こむ")]  # already correct
    corrections = [ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "test")]
    with pytest.raises(StaleCorrection):
        apply_corrections(rows, corrections)


def test_stale_correction_fails_closed():
    """A correction matching no row raises rather than passing silently."""
    rows = [_row("dojg", "結構", "結構", "けっこう")]
    corrections = [ReadingCorrection("dojg", "無い点", "無い点", "x", "y", "test")]
    with pytest.raises(StaleCorrection, match="無い点"):
        apply_corrections(rows, corrections)


def test_a_correction_for_a_source_outside_the_corpus_is_not_stale():
    """Staleness is scoped to the sources the corpus actually carries.

    A corpus is legitimately narrower than the overlay after a single-source stage
    run (`--source dojg`), or in a checkout that has acquired only some sources.
    Raising there blocks the build for a reason that says nothing about drift —
    the overlay simply describes rows this corpus does not include.

    Verified against the shipped overlay's actual shape: all eight corrections
    target `dojg`, `edewakaru`, `nihongo_net`, `nihongo_no_sensei`, so a corpus
    without those sources would fail an unscoped gate.
    """
    rows = [_row("yokubi", "だ", "だ", None)]
    corrections = [ReadingCorrection("dojg", "の下で", "の下で", "のしたで", "のもとで", "t")]
    out, applied = apply_corrections(rows, corrections)
    assert applied == []
    assert out == rows


def test_the_gate_keeps_its_bite_on_every_source_in_the_corpus():
    """Scoping must not become "ignore anything that does not match".

    A correction whose source IS present but whose row is gone is exactly the
    drift the gate exists for, and must still raise even when a second,
    out-of-scope correction is present in the same overlay.
    """
    rows = [_row("dojg", "結構", "結構", "けっこう")]
    corrections = [
        ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "out of scope"),
        ReadingCorrection("dojg", "無い点", "無い点", "x", "y", "drifted"),
    ]
    with pytest.raises(StaleCorrection, match="無い点") as caught:
        apply_corrections(rows, corrections)
    # Only the in-scope correction is reported, so the message names the real
    # defect instead of burying it under out-of-scope noise.
    assert [c.source for c in caught.value.unmatched] == ["dojg"]


# --------------------------------------------------------------------------
# end-to-end: corrections applied through the merge, keymap identity preserved
# --------------------------------------------------------------------------


def _full_row(source, source_id, expression, reading):
    return {
        "source": source,
        "source_id": source_id,
        # UGD-11d-C made row identity mandatory at the merge boundary: `source_id`
        # is not unique, so a contribution built from an unstamped row would not be
        # traceable to a single source record. `ExtractResult` stamps it for real
        # rows; a fixture must supply it or `unify` fails closed.
        "row_uid": f"{source}:1",
        "expression": expression,
        "variants": [],
        "reading": reading,
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


def _unify_keymap(rows_to_keys, points):
    from bugd.keymap import substance_hash
    from bugd.unify import parse_keymap

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


def _point(canonical_key, bucket_key, expression):
    return {
        "canonicalKey": canonical_key,
        "bucketKey": bucket_key,
        "expression": expression,
        "axes": {"variety": "standard", "era": "modern"},
        "disambiguator": "",
        "lookupForms": [expression],
        "jlptLevels": [],
        "observedRegisters": [],
        "observedSignatures": [],
        "contributors": [],
        "sourceCount": 1,
    }


def test_unify_applies_correction_at_contribution_level():
    """A defect reading is corrected in the emitted contribution, and the keymap
    (which keys on the *original* reading) still resolves the row — proving the
    correction is applied after alignment, not before it."""
    from bugd.unify import unify

    row = _full_row("edewakaru", "込む", "込む", "ごむ")  # the defect reading
    keymap = _unify_keymap([("edewakaru", row, "込む")], [_point("込む", "込む", "込む")])
    corrections = [ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "test")]

    entries, _ = unify([("edewakaru", row)], keymap, {"edewakaru": "絵でわかる"}, corrections=corrections)

    contribution = entries[0].contributions[0]
    assert contribution.reading == "こむ"  # corrected
    assert entries[0].reading == "こむ"     # entry furigana reflects the fix
    assert is_plausible_reading(contribution.expression, contribution.reading)


def test_unify_fails_closed_on_stale_correction():
    """A correction that matches no assembled contribution fails the merge."""
    from bugd.unify import unify

    row = _full_row("edewakaru", "込む", "込む", "こむ")  # already correct
    keymap = _unify_keymap([("edewakaru", row, "込む")], [_point("込む", "込む", "込む")])
    corrections = [ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "test")]

    with pytest.raises(StaleCorrection):
        unify([("edewakaru", row)], keymap, {"edewakaru": "絵でわかる"}, corrections=corrections)


def test_unify_scopes_staleness_to_the_sources_in_the_corpus():
    """`unify` keeps its OWN copy of the staleness gate — scope both.

    `bugd.unify` re-checks correction hits after contribution assembly, so
    scoping `reading_corrections.apply_corrections` alone leaves the public build
    failing at the merge stage instead. Both call sites are asserted, or the fix
    is half-applied and only the second one is discovered at release time.
    """
    from bugd.unify import unify

    row = _full_row("yokubi", "だ", "だ", None)
    keymap = _unify_keymap([("yokubi", row, "だ")], [_point("だ", "だ", "だ")])
    corrections = [ReadingCorrection("dojg", "の下で", "の下で", "のしたで", "のもとで", "t")]

    entries, _ = unify(
        [("yokubi", row)], keymap, {"yokubi": "Yokubi"}, corrections=corrections
    )
    assert entries[0].contributions[0].reading is None


def test_unify_still_fails_on_drift_within_a_present_source():
    """Scoping must not disarm the gate for a source the corpus does carry."""
    from bugd.unify import unify

    row = _full_row("edewakaru", "込む", "込む", "こむ")  # already correct
    keymap = _unify_keymap([("edewakaru", row, "込む")], [_point("込む", "込む", "込む")])
    corrections = [
        ReadingCorrection("dojg", "の下で", "の下で", "のしたで", "のもとで", "out of scope"),
        ReadingCorrection("edewakaru", "込む", "込む", "ごむ", "こむ", "drifted"),
    ]

    with pytest.raises(StaleCorrection) as caught:
        unify(
            [("edewakaru", row)],
            keymap,
            {"edewakaru": "絵でわかる"},
            corrections=corrections,
        )
    assert [c.source for c in caught.value.unmatched] == ["edewakaru"]


def test_unify_without_corrections_is_verbatim():
    """No corrections supplied ⇒ the reading is carried verbatim (faithful default)."""
    from bugd.unify import unify

    row = _full_row("edewakaru", "込む", "込む", "ごむ")
    keymap = _unify_keymap([("edewakaru", row, "込む")], [_point("込む", "込む", "込む")])

    entries, _ = unify([("edewakaru", row)], keymap, {"edewakaru": "絵でわかる"})
    assert entries[0].contributions[0].reading == "ごむ"
