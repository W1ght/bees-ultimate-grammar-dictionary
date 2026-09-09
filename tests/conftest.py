"""Shared test fixtures for the pipeline skeleton."""

from __future__ import annotations

import re

import pytest

from bugd.model import Example, GrammarPoint


def resolve_space_tokens(css: str) -> str:
    """Substitute the card's `--bugd-space-*` scale into a CSS string.

    The vertical rhythm moved from seven ad-hoc literal lengths to one four-step
    scale declared on `[data-sc-grammar-card]`. Existing tests assert real
    numbers by regex (`margin-top:\\s*([0-9.]+)em`), which is the right shape --
    a threshold test that only checked for the token NAME could not tell 0.2em
    from 2em and would stop biting.

    So resolve the tokens to their declared values first and keep asserting
    numbers. A token with no declaration is left as-is, which makes the assertion
    fail loudly rather than silently pass on an unresolvable value.
    """
    decls = dict(
        re.findall(r"(--bugd-space-[a-z]+):\s*([0-9.]+em)\s*;", css)
    )
    if not decls:  # pragma: no cover - guards a rename of the scale
        raise AssertionError("no --bugd-space-* scale found in the stylesheet")

    def sub(match: re.Match[str]) -> str:
        return decls.get(match.group(1), match.group(0))

    return re.sub(r"var\((--bugd-space-[a-z]+)\)", sub, css)


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
