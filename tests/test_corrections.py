"""Byte-anchored source-defect corrections applied at the extract boundary.

UGD-11c-C: 100 cards stated a formation rule their own examples contradict; the
confirmed sub-class fixed here is a defect that lives in the immutable source
term-bank bytes (verified: the wrong string is present verbatim in the locked
source, not introduced by our extractor). These tests assert the correction
LAYER's guarantees as properties, not the specific strings:

* corrections apply to the normalized field and are fail-closed on a missing
  anchor (a drifted source can never silently ship an un-reviewed edit),
* the locked source bytes and their SOURCE.lock digests are never mutated, and
* after the real extract, no corrected card still spells a corrupted headword its
  own examples never use (the property UGD-11c flagged), while the defect the
  overlay targets is provably gone.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from bugd.corrections import (
    Correction,
    CorrectionError,
    apply_corrections,
    load_corrections,
)
from bugd.model import Example, GrammarPoint
from bugd.pipeline import point_from_json, run_extract
from bugd.structure_audit import audit_point

REPO = pathlib.Path(__file__).resolve().parents[1]
OVERLAY_PATH = REPO / "data" / "corrections" / "structure_corrections.json"
SOURCES_DIR = REPO / "data" / "sources"


def _point(**kw) -> GrammarPoint:
    base = dict(source="dojg", source_id="X", expression="X")
    base.update(kw)
    return GrammarPoint(**base)


# --------------------------------------------------------------------------
# the correction operation
# --------------------------------------------------------------------------


def test_replace_all_rewrites_every_occurrence_in_the_field():
    # A 接続 defect is repeated across every formation line; one correction must
    # fix all of them, not just the first.
    point = _point(
        source_id="にほかならない",
        expression="にほかならない",
        structure="A にはかならない\nB にはかならない\nC にはかならない",
    )
    correction = Correction(
        source="dojg",
        source_id="にほかならない",
        field="structure",
        op="replace_all",
        anchor="にはかならない",
        replacement="にほかならない",
    )
    result, applied = apply_corrections([point], [correction], source="dojg")
    assert "にはかならない" not in (result[0].structure or "")
    assert result[0].structure.count("にほかならない") == 3
    assert applied[0]["occurrences"] == 3


def test_correction_applies_to_every_point_sharing_the_source_id():
    # A source may repeat a source_id across the reviewer's split senses; the
    # extracted card carries one structure field per copy and all must be fixed.
    points = [
        _point(source_id="たって", expression="たって", structure="話しって"),
        _point(source_id="たって", expression="たって", structure="話しって"),
    ]
    correction = Correction(
        source="dojg",
        source_id="たって",
        field="structure",
        op="replace_all",
        anchor="話しって",
        replacement="話したって",
    )
    result, applied = apply_corrections(points, [correction], source="dojg")
    assert all("話しって" not in (p.structure or "") for p in result)
    assert applied[0]["occurrences"] == 2


def test_example_correction_rewrites_japanese_and_prunes_dead_highlight():
    point = _point(
        source_id="弾みに",
        expression="弾みに",
        examples=(
            Example(
                japanese="転んだ弾みに\n→転んだことでスマホを壊してしまった",
                highlight=("スマホを壊してしまった",),
            ),
        ),
    )
    correction = Correction(
        source="dojg",
        source_id="弾みに",
        field="examples",
        op="replace_all",
        anchor="スマホを壊してしまった",
        replacement="たまごを割ってしまった",
    )
    result, _ = apply_corrections([point], [correction], source="dojg")
    example = result[0].examples[0]
    assert "スマホを壊してしまった" not in example.japanese
    assert "たまごを割ってしまった" in example.japanese
    # a highlight span that no longer occurs in the corrected sentence is dropped
    assert example.highlight == ()


# --------------------------------------------------------------------------
# fail-closed behaviour
# --------------------------------------------------------------------------


def test_missing_anchor_raises_rather_than_silently_passing():
    # This is the whole point of anchoring: an already-applied or drifted source
    # must surface loudly, never become a no-op that lets a defect ship.
    point = _point(source_id="X", expression="X", structure="already correct")
    correction = Correction(
        source="dojg", source_id="X", field="structure",
        op="replace_all", anchor="NEVER-PRESENT", replacement="whatever",
    )
    with pytest.raises(CorrectionError, match="anchor not found"):
        apply_corrections([point], [correction], source="dojg")


def test_missing_source_id_is_skipped_not_fatal():
    # A correction whose card is absent from THIS run (a fixture set or an
    # `--only` subset) is skipped, not fatal — full-corpus coverage is asserted
    # separately. Drift within a PRESENT card still fails closed (see above).
    correction = Correction(
        source="dojg", source_id="ghost", field="structure",
        op="replace_all", anchor="a", replacement="b",
    )
    result, applied = apply_corrections([_point(source_id="real")], [correction], source="dojg")
    assert applied == []
    assert result[0].structure is None


def test_unsupported_op_is_rejected_at_construction():
    with pytest.raises(CorrectionError, match="unsupported correction op"):
        Correction(
            source="s", source_id="i", field="structure",
            op="delete", anchor="a", replacement="b",
        )


def test_noop_correction_is_rejected():
    with pytest.raises(CorrectionError, match="no-op"):
        Correction(
            source="s", source_id="i", field="structure",
            op="replace_all", anchor="same", replacement="same",
        )


def test_corrections_for_other_sources_are_ignored():
    correction = Correction(
        source="edewakaru", source_id="X", field="structure",
        op="replace_all", anchor="a", replacement="b",
    )
    # No dojg correction present -> dojg extraction is untouched and does not raise
    result, applied = apply_corrections([_point(source_id="X")], [correction], source="dojg")
    assert applied == []


# --------------------------------------------------------------------------
# the shipped overlay + the real corpus
# --------------------------------------------------------------------------


def test_overlay_loads_and_every_entry_is_well_formed():
    corrections = load_corrections(OVERLAY_PATH)
    assert corrections, "the corrections overlay should not be empty"
    # keys are unique per (source, source_id, field, anchor): a duplicated
    # correction would make the second application a guaranteed missing-anchor
    # failure once the first already rewrote the bytes.
    keys = [(c.source, c.source_id, c.field, c.anchor) for c in corrections]
    assert len(keys) == len(set(keys)), "duplicate correction key in overlay"


def test_locked_source_bytes_are_never_mutated_by_corrections():
    # The defect stays in the immutable source; the correction is an overlay, not
    # a rewrite. If this fails, a defect was laundered into "our" bytes and the
    # SOURCE.lock integrity gate would (rightly) break.
    lock = json.loads((SOURCES_DIR / "dojg" / "SOURCE.lock.json").read_text("utf-8"))
    bank = (SOURCES_DIR / "dojg" / "term_bank_1.json").read_bytes()
    assert hashlib.sha256(bank).hexdigest() == lock["files"]["term_bank_1.json"]["sha256"]
    # the raw source still contains the known defect the overlay corrects
    assert "にはかならない" in bank.decode("utf-8")


@pytest.fixture(scope="module")
def corrected_points(tmp_path_factory) -> dict[str, list[GrammarPoint]]:
    out = tmp_path_factory.mktemp("extracted")
    run_extract(sources_dir=SOURCES_DIR, extracted_dir=out)
    points: dict[str, list[GrammarPoint]] = {}
    for artifact in out.glob("*.json"):
        payload = json.loads(artifact.read_text("utf-8"))
        points[payload["source"]] = [point_from_json(p) for p in payload["points"]]
    return points


def test_every_overlay_correction_landed_in_the_real_extract(corrected_points):
    # Property: after extraction, the corrected form is present and the anchored
    # defect is absent in every card the correction targets. Asserted against the
    # overlay itself, so adding a correction automatically extends the check.
    for correction in load_corrections(OVERLAY_PATH):
        pts = [p for p in corrected_points[correction.source]
               if p.source_id == correction.source_id]
        assert pts, f"no extracted point for {correction.source}/{correction.source_id}"
        if correction.field == "examples":
            texts = [e.japanese for p in pts for e in p.examples]
        else:
            texts = [getattr(p, correction.field) or "" for p in pts]
        joined = "\n".join(texts)
        assert correction.anchor not in joined, (
            f"{correction.source}/{correction.source_id}: defect still present"
        )
        assert correction.replacement in joined


def test_corrected_cards_no_longer_spell_a_headword_their_examples_never_use(
    corrected_points,
):
    # The property UGD-11c flagged: a formation line must not spell a one-kana
    # corruption of the point's headword that appears in no example. For every
    # structure-field correction, the corrected card must clear that audit.
    for correction in load_corrections(OVERLAY_PATH):
        if correction.field != "structure":
            continue
        for point in corrected_points[correction.source]:
            if point.source_id != correction.source_id:
                continue
            corrupt_forms = {s["structure_form"] for s in audit_point(point)}
            assert correction.anchor not in corrupt_forms
