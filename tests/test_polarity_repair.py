"""Extraction-level repair of publisher-flipped headword polarity.

These assert a *property* — a repaired headword's polarity agrees with the row's
own reading, and the rule abstains whenever the reading does not witness the flip
— rather than the specific strings that motivated it. New flipped rows in a
future term-bank revision are covered without editing this file; a genuine
affirmative that happens to look flippable is protected by the same property.
"""

from __future__ import annotations

import pytest

from bugd.model import GrammarPoint
from bugd.polarity import polarity
from bugd.sources.polarity_repair import negative_counterpart, repair_point


def _point(expression: str, reading: str | None, **kwargs) -> GrammarPoint:
    kwargs.setdefault("source", "fixture")
    kwargs.setdefault("source_id", "1")
    return GrammarPoint(expression=expression, reading=reading, **kwargs)


# ---------------------------------------------------------------------------
# The rule fires: a flipped expression whose own reading spells the negative.
# ---------------------------------------------------------------------------

#: (expression, reading) pairs — an affirmative surface whose reading is the
#: fixed-negative form. Includes a kanji-bearing headword so the kana-subsequence
#: reconciliation (not a naive prefix) is exercised.
FLIPPED = [
    ("なくもある", "なくもない"),
    ("までもある", "までもない"),
    ("どころではある", "どころではない"),
    ("てすむことではある", "てすむことではない"),
    ("と言えなくもある", "といえなくもない"),      # kanji 言 only in expression
    ("に越したことはある", "にこしたことはない"),    # kanji 越 only in expression
    ("たものではある", "たものではない"),
]


@pytest.mark.parametrize("expression, reading", FLIPPED)
def test_flipped_headword_is_rewritten_to_agree_with_its_reading(expression, reading):
    point = _point(expression, reading)
    repaired = repair_point(point)

    # The property: the repaired headword is negative, matching the reading.
    assert repaired.expression != expression
    assert polarity(repaired.expression) == "neg"
    assert polarity(repaired.reading) == "neg"
    # The publisher's exact original bytes are preserved for audit, never lost.
    assert repaired.provenance["upstreamExpression"] == expression
    assert repaired.provenance["polarityRepaired"] == "reading"


def test_flip_drops_the_nonexistent_affirmative_as_a_lookup_variant():
    # The affirmative is not a real form, so it must not survive as a lookup key.
    point = _point("どころではある", "どころではない", variants=("どころではある", "どころじゃない"))
    repaired = repair_point(point)
    assert "どころではある" not in repaired.variants
    assert "どころじゃない" in repaired.variants  # a genuine alternate is kept


# ---------------------------------------------------------------------------
# The rule abstains: no trustworthy self-consistent signal.
# ---------------------------------------------------------------------------


def test_genuine_affirmative_is_left_untouched():
    # 〜たことがある is a real affirmative ("have done X"); its reading agrees, and
    # a negative sibling in the tags is a different pattern, not evidence of a flip.
    point = _point("たことがある", "たことがある", variants=("たことがない",))
    assert repair_point(point) is point
    assert negative_counterpart("たことがある", "たことがある") is None


def test_abstains_when_reading_is_also_flipped():
    # donna_toki flipped BOTH columns: reading agrees with the wrong affirmative,
    # so reading and definitionTags disagree. Fail closed — leave it for a human.
    point = _point("と言ったらある", "といったらある", variants=("といったらない",))
    assert repair_point(point) is point
    assert negative_counterpart("と言ったらある", "といったらある") is None


def test_abstains_when_reading_is_missing():
    point = _point("どころではある", None)
    assert repair_point(point) is point


def test_abstains_when_candidate_does_not_reconcile_with_reading():
    # Reading is negative but is NOT the tail-flip of the expression: not a
    # confident flip of THIS headword, so no rewrite.
    assert negative_counterpart("どころではある", "まったくべつのよみない") is None


def test_a_real_negative_headword_is_not_dragged_through_the_flip():
    # Already negative: nothing to flip, reading agrees, leave it.
    point = _point("ばかりでなく", "ばかりでなく")
    assert repair_point(point) is point


# ---------------------------------------------------------------------------
# Every community source gets the rule, uniformly, at extract time.
# ---------------------------------------------------------------------------


def test_community_extract_reports_and_applies_the_repair(tmp_path):
    """A flipped term-bank row is corrected by CommunityBankExtractor.extract."""
    import hashlib

    from bugd.jsonio import dump_json
    from bugd.sources.base import SOURCE_LOCK_NAME
    from bugd.sources.community import CommunityBankExtractor

    class _Fixture(CommunityBankExtractor):
        name = "polarity-fixture"
        label = "Polarity Fixture"
        members = ("term_bank_1.json",)

        def parse(self, row):
            return _point(row.expression, row.reading, source=self.name, source_id="1")

    # A minimal format-3 term-bank row with the flip in `expression` and the
    # correct negative in `reading`.
    bank = [["なくもある", "なくもない", "", "", 0, ["gloss"], 1, ""]]
    payload = (dump_json(bank) + "\n").encode("utf-8")
    directory = tmp_path / "polarity-fixture"
    directory.mkdir()
    (directory / "term_bank_1.json").write_bytes(payload)
    lock = {
        "source": "polarity-fixture",
        "files": {
            "term_bank_1.json": {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byteCount": len(payload),
            }
        },
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")

    result = _Fixture(directory).extract()

    assert result.stats["polarityRepaired"] == 1
    (repaired,) = result.points
    assert repaired.expression == "なくもない"
    assert polarity(repaired.expression) == "neg"
    assert repaired.provenance["upstreamExpression"] == "なくもある"
