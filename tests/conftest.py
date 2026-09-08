"""Shared test fixtures for the pipeline skeleton."""

from __future__ import annotations

import pytest

from bugd.model import Example, GrammarPoint


@pytest.fixture
def sample_point() -> GrammarPoint:
    return GrammarPoint(
        source="fixture",
        source_id="1",
        expression="そうです",
        variants=("そうだ",),
        meaning="hearsay; I hear that",
        structure="Verb[casual] + そうです",
        jlpt="N4",
        examples=(
            Example(
                japanese="雨が降るそうです。",
                english="I hear it will rain.",
                highlight=("そうです",),
            ),
        ),
        provenance={"notetype": "fixture"},
    )
