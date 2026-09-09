"""Post-extraction content corrections (``bugd.corrections``).

Covers the disposition semantics and the fail-closed guards that keep a stale
correction from silently doing nothing.
"""

from __future__ import annotations

import pathlib

import pytest

from bugd.corrections import (
    Correction,
    CorrectionError,
    apply_corrections,
    load_corrections,
)
from bugd.jsonio import dump_json
from bugd.model import Example, GrammarPoint


def _point(source="edewakaru", source_id="x", **kw) -> GrammarPoint:
    return GrammarPoint(source=source, source_id=source_id, expression=kw.pop("expression", "x"), **kw)


# --------------------------------------------------------------------------
# disposition semantics
# --------------------------------------------------------------------------


def test_drop_example_removes_only_the_defective_example():
    p = _point(
        examples=(
            Example(japanese="good one"),
            Example(japanese="そもさも broken"),
            Example(japanese="another good"),
        )
    )
    c = Correction("edewakaru", "x", "examples", "drop_example", "そもさも")
    out, report = apply_corrections([p], [c])
    assert [e.japanese for e in out[0].examples] == ["good one", "another good"]
    assert report["applied"] == 1


def test_remove_span_deletes_the_clause_and_cleans_the_boundary():
    p = _point(explanation="正しい説明です。まちがった説明です。あとの正しい文。")
    c = Correction("edewakaru", "x", "explanation", "remove_span", "まちがった説明です。")
    out, _ = apply_corrections([p], [c])
    assert "まちがった" not in (out[0].explanation or "")
    assert "正しい説明です。" in out[0].explanation
    assert "あとの正しい文。" in out[0].explanation


def test_clear_field_blanks_a_wholly_wrong_field():
    p = _point(meaning="entirely wrong gloss")
    c = Correction("edewakaru", "x", "meaning", "clear_field", "entirely wrong gloss")
    out, _ = apply_corrections([p], [c])
    assert out[0].meaning is None


def test_replace_span_fixes_an_unambiguous_typo_everywhere_in_a_field():
    p = _point(explanation="①にかからわず、A。②にかからわず、B。")
    c = Correction(
        "edewakaru", "x", "explanation", "replace_span", "にかからわず",
        replacement="にかかわらず",
    )
    out, _ = apply_corrections([p], [c])
    assert "にかからわず" not in out[0].explanation
    assert out[0].explanation.count("にかかわらず") == 2


def test_replace_span_fixes_the_typo_in_example_japanese_and_highlight():
    p = _point(
        examples=(Example(japanese="曜日にかからわず開店", highlight=("にかからわず",)),),
    )
    c = Correction(
        "edewakaru", "x", "examples", "replace_span", "にかからわず",
        replacement="にかかわらず",
    )
    out, _ = apply_corrections([p], [c])
    ex = out[0].examples[0]
    assert "にかからわず" not in ex.japanese
    assert ex.highlight == ("にかかわらず",)


# --------------------------------------------------------------------------
# content-based matching across duplicated siblings
# --------------------------------------------------------------------------


def test_correction_applies_to_every_sibling_that_shares_the_defect():
    # The same defective example duplicated across two variant entries: one
    # correction must clear both, or the finding survives re-review under the
    # sibling the reviewer did not name.
    shared = Example(japanese="学生時代は工場などのでバイト")
    p1 = _point(source_id="など", examples=(shared,))
    p2 = _point(source_id="なんて", examples=(shared,))
    c = Correction("edewakaru", "など", "examples", "drop_example", "工場などので")
    out, report = apply_corrections([p1, p2], [c])
    assert out[0].examples == ()
    assert out[1].examples == ()
    assert report["applied"] == 1
    assert report["pointsChanged"] == 2


def test_overlapping_corrections_on_the_same_example_do_not_fail_closed():
    # Two findings quote the same broken example at different lengths. Once the
    # first drops it the second finds it already gone; that is not a stale
    # correction.
    p = _point(examples=(Example(japanese="報酬が多かろう少ないかろう"),))
    c1 = Correction("edewakaru", "x", "examples", "drop_example", "少ないかろう")
    c2 = Correction("edewakaru", "x", "examples", "drop_example", "報酬が多かろう少ないかろう")
    out, report = apply_corrections([p], [c1, c2])
    assert out[0].examples == ()
    assert report["applied"] == 2  # both satisfied against the original snapshot


# --------------------------------------------------------------------------
# fail-closed guards
# --------------------------------------------------------------------------


def test_stale_correction_whose_span_is_absent_raises():
    p = _point(explanation="nothing wrong here")
    c = Correction("edewakaru", "x", "explanation", "remove_span", "span that is not present")
    with pytest.raises(CorrectionError):
        apply_corrections([p], [c])


def test_correction_targeting_a_source_with_no_matching_record_raises():
    p = _point(source="edewakaru", explanation="text")
    c = Correction("edewakaru", "x", "explanation", "remove_span", "text")
    # a correction for a different source that has no rows here must fail closed
    other = Correction("dojg", "y", "explanation", "remove_span", "text")
    with pytest.raises(CorrectionError):
        apply_corrections([p], [other], source="dojg")


def test_unknown_disposition_rejected():
    with pytest.raises(CorrectionError):
        Correction("s", "i", "meaning", "obliterate", "x")


def test_replace_span_requires_a_replacement():
    with pytest.raises(CorrectionError):
        Correction("s", "i", "meaning", "replace_span", "x")


def test_replace_span_replacement_must_differ():
    with pytest.raises(CorrectionError):
        Correction("s", "i", "meaning", "replace_span", "x", replacement="x")


def test_drop_example_must_target_examples_field():
    with pytest.raises(CorrectionError):
        Correction("s", "i", "meaning", "drop_example", "x")


# --------------------------------------------------------------------------
# loader
# --------------------------------------------------------------------------


def test_load_corrections_missing_dir_is_empty(tmp_path):
    assert load_corrections(tmp_path / "does-not-exist") == []


def test_load_corrections_round_trips_a_file(tmp_path):
    payload = {
        "corrections": [
            {
                "source": "edewakaru",
                "source_id": "x",
                "field": "examples",
                "disposition": "drop_example",
                "verbatim": "broken",
            }
        ]
    }
    (tmp_path / "c.json").write_text(dump_json(payload), encoding="utf-8")
    loaded = load_corrections(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].disposition == "drop_example"


def test_load_corrections_skips_a_sidecar_without_corrections_key(tmp_path):
    # A report/index dict (no ``corrections`` key) may live beside the manifest.
    (tmp_path / "report.json").write_text('{"items": []}', encoding="utf-8")
    assert load_corrections(tmp_path) == []


def test_load_corrections_rejects_a_malformed_manifest(tmp_path):
    # ``corrections`` present but not a list is a broken manifest, fail closed.
    (tmp_path / "bad.json").write_text('{"corrections": {}}', encoding="utf-8")
    with pytest.raises(CorrectionError):
        load_corrections(tmp_path)
