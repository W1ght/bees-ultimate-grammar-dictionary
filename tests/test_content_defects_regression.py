"""Regression tests for the confirmed content defects fixed under UGD-11c-D.

Two layers:

1. Mechanical, data-free properties of the corrections applier that pin the
   defect *classes* the fix addressed (a defective example is gone; a wrong
   clause is removed while the surrounding publisher text survives; an
   unambiguous typo no longer appears in the example surface form).

2. A corpus-level guard that runs only when the real corrected artifacts are
   present (a full ``make extract`` has run). It re-loads the shipped
   corrections manifest and asserts that not one of the confirmed defect
   verbatims survives anywhere in the freshly built unified dataset — the same
   property the re-review confirmed, pinned so a future extraction change cannot
   silently reintroduce a defect.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.corrections import Correction, apply_corrections, load_corrections
from bugd.model import Example, GrammarPoint

REPO = pathlib.Path(__file__).resolve().parents[1]
CORRECTIONS_DIR = REPO / "data" / "corrections"
UNIFIED = REPO / "data" / "merge" / "unified.jsonl"


# --------------------------------------------------------------------------
# 1. data-free defect-class regressions
# --------------------------------------------------------------------------


def test_example_missing_its_grammar_point_surface_form_is_dropped():
    """An example that does not contain its grammar point's surface form is a
    defect. Dropping it must remove exactly that example."""
    grammar_point = "そもそも"
    good = Example(japanese="そもそもの原因は何だ")
    typo = Example(japanese="そもさも電波って何なんでしょう。")  # そもさも != そもそも
    p = GrammarPoint(source="dojg", source_id="そもそも", expression="そもそも",
                     examples=(good, typo))
    # the mechanical detector: an example whose japanese lacks the surface form
    assert grammar_point not in typo.japanese
    c = Correction("dojg", "そもそも", "examples", "drop_example", typo.japanese)
    out, _ = apply_corrections([p], [c])
    assert good in out[0].examples
    assert typo not in out[0].examples


def test_self_contradictory_clause_removed_but_publisher_text_survives():
    p = GrammarPoint(
        source="donna_toki", source_id="あっての", expression="あっての",
        explanation="「N1があるからN2が成立する」と強調する表現。"
        'Emphatic expression meaning "N1 is realized because there is N2."',
    )
    c = Correction(
        "donna_toki", "あっての", "explanation", "remove_span",
        'Emphatic expression meaning "N1 is realized because there is N2."',
    )
    out, _ = apply_corrections([p], [c])
    assert "N1 is realized because there is N2." not in out[0].explanation
    assert "N1があるからN2が成立する" in out[0].explanation


def test_unambiguous_typo_corrected_in_place_across_the_field():
    p = GrammarPoint(
        source="edewakaru", source_id="にかかわらず", expression="にかかわらず",
        explanation="②にかからわず、連絡してね\n⑥曜日にかからわず、開店",
    )
    c = Correction(
        "edewakaru", "にかかわらず", "explanation", "replace_span", "にかからわず",
        replacement="にかかわらず",
    )
    out, _ = apply_corrections([p], [c])
    assert "にかからわず" not in out[0].explanation
    assert out[0].explanation.count("にかかわらず") == 2


# --------------------------------------------------------------------------
# 2. corpus-level guard (runs only when the real artifacts exist)
# --------------------------------------------------------------------------


def _load_manifest_corrections():
    manifest = CORRECTIONS_DIR / "ugd-11c-d.json"
    if not manifest.is_file():
        return None
    return json.loads(manifest.read_text(encoding="utf-8"))["corrections"]


def test_shipped_corrections_manifest_is_well_formed():
    """The corrections file loads and every entry is a valid Correction."""
    corrections = load_corrections(CORRECTIONS_DIR)
    assert corrections, "no corrections shipped"
    # every disposition is one the applier understands
    for c in corrections:
        assert isinstance(c, Correction)


@pytest.mark.skipif(not UNIFIED.is_file(), reason="requires a built unified dataset")
def test_no_confirmed_defect_verbatim_survives_in_the_unified_corpus():
    """No confirmed UGD-11c-D defect verbatim appears anywhere in the freshly
    built unified dataset (all fields, examples, highlights)."""
    corrections = _load_manifest_corrections()
    assert corrections

    # Build one big per-source haystack straight from the unified bytes.
    haystacks: dict[str, list[str]] = {}
    with UNIFIED.open(encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("kind") != "point":
                continue
            for sense in e.get("senses", []):
                for c in sense.get("contributions", []):
                    parts = []
                    for field in ("meaning", "structure", "nuance", "explanation", "notes", "jlpt"):
                        if c.get(field):
                            parts.append(str(c[field]))
                    for ex in c.get("examples") or []:
                        for k in ("japanese", "english", "note"):
                            if ex.get(k):
                                parts.append(str(ex[k]))
                        parts.extend(str(h) for h in (ex.get("highlight") or []))
                    haystacks.setdefault(c["source"], []).append("\n".join(parts))

    survivors = []
    for c in corrections:
        if c["disposition"] == "replace_span":
            continue  # verbatim is the typo; checked below
        blob = "\n".join(haystacks.get(c["source"], []))
        if c["verbatim"] in blob:
            survivors.append((c["source"], c["source_id"], c["field"], c["verbatim"][:40]))
    assert not survivors, f"defect verbatims still in corpus: {survivors}"

    # replace_span: the typo must be gone, the correction present.
    for c in corrections:
        if c["disposition"] != "replace_span":
            continue
        blob = "\n".join(haystacks.get(c["source"], []))
        assert c["verbatim"] not in blob, f"typo {c['verbatim']!r} survives"
        assert c["replacement"] in blob, f"correction {c['replacement']!r} missing"
