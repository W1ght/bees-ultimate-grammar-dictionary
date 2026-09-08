"""Model + merge + interchange round-trip behaviour of the skeleton."""

from __future__ import annotations

import pytest

from bugd.jsonio import MalformedPayload, content_hash, dump_json, load_json
from bugd.merge import MergedEntry, merge_points
from bugd.model import Example, GrammarPoint
from bugd.pipeline import entry_from_json, entry_to_json, point_from_json, point_to_json


def test_grammar_point_requires_source_attribution():
    with pytest.raises(MalformedPayload):
        GrammarPoint(source="", source_id="1", expression="そう")
    with pytest.raises(MalformedPayload):
        GrammarPoint(source="x", source_id="  ", expression="そう")
    with pytest.raises(MalformedPayload):
        GrammarPoint(source="x", source_id="1", expression="")


def test_grammar_point_rejects_unknown_jlpt_level():
    with pytest.raises(MalformedPayload):
        GrammarPoint(source="x", source_id="1", expression="そう", jlpt="N6")


def test_point_json_round_trip(sample_point):
    assert point_from_json(load_json(dump_json(point_to_json(sample_point)))) == sample_point


def test_merge_groups_by_key_and_keeps_every_contribution(sample_point):
    other = GrammarPoint(
        source="second",
        source_id="9",
        expression=sample_point.expression,
        variants=("そうな",),
        meaning="reportedly",
    )
    unrelated = GrammarPoint(source="second", source_id="10", expression="ようです")

    entries = merge_points([sample_point, other, unrelated])

    assert [entry.expression for entry in entries] == ["そうです", "ようです"]
    merged = entries[0]
    assert len(merged.contributions) == 2
    assert merged.sources == ("fixture", "second")
    assert set(merged.variants) == {"そうだ", "そうな"}


def test_merge_is_deterministic(sample_point):
    other = GrammarPoint(source="b", source_id="2", expression="あ")
    forward = merge_points([sample_point, other])
    backward = merge_points([other, sample_point])
    assert [entry.expression for entry in forward] == [entry.expression for entry in backward]


def test_merge_rejects_non_records():
    with pytest.raises(MalformedPayload):
        merge_points([{"expression": "そう"}])  # type: ignore[list-item]


def test_merged_entry_json_round_trip(sample_point):
    entry = merge_points([sample_point])[0]
    assert entry_from_json(load_json(dump_json(entry_to_json(entry)))) == entry


def test_merged_entry_requires_expression():
    with pytest.raises(MalformedPayload):
        MergedEntry(expression="")


def test_ai_generated_content_stays_segregated():
    point = GrammarPoint(
        source="bunpo",
        source_id="7",
        expression="そうです",
        meaning="hearsay",
        ai_generated={"politeness": "polite", "example": "AI例文"},
        examples=(Example(japanese="人が来るそうです。"),),
    )
    # Human-authored fields never absorb AI fields, and AI examples are flagged
    # per example so the card can keep them behind a labelled disclosure.
    assert "AI例文" not in (point.meaning or "")
    assert point.ai_generated["example"] == "AI例文"
    assert all(not example.ai_generated for example in point.examples)


def test_content_hash_is_stable_across_key_order():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_json_rejects_non_finite():
    with pytest.raises(MalformedPayload):
        load_json("NaN")
    with pytest.raises(ValueError):
        dump_json(float("inf"))
