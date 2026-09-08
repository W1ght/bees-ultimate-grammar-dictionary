"""Guards on what this suite is actually measuring.

A rendered-behaviour suite is only worth its runtime if it is pointed at the real
renderer and the real card. These tests make both facts explicit, so the suite
cannot report green while silently testing a stand-in or a stale Yomitan.
"""

from __future__ import annotations

import pytest

from harness import card_builder
from harness.yomitan_harness import EXPECTED_YOMITAN_VERSION, yomitan_revision


def test_harness_renders_the_pinned_yomitan_revision():
    """The renderer under test is the version `make validate` pins."""
    revision = yomitan_revision()
    assert revision["describe"].startswith(EXPECTED_YOMITAN_VERSION), (
        f"harness would render Yomitan {revision['describe']!r} "
        f"({revision['commit'][:12]}) but the dictionary is built and validated "
        f"against {EXPECTED_YOMITAN_VERSION}"
    )
    assert not revision["dirty"], (
        "the pinned Yomitan checkout has uncommitted changes to tracked files, "
        "so measurements against it are not reproducible:\n"
        f"{revision['dirty']}"
    )


@pytest.mark.xfail(
    card_builder.active_builder() != "production",
    reason=(
        "UGD-09's bugd.banks.build_term_entry still raises NotImplementedError, "
        "so this suite is measuring the contract stand-in in "
        "tests/harness/reference_card.py. XPASS here is the signal to re-run "
        "every geometry and behaviour result against the shipped card."
    ),
    strict=True,
)
def test_suite_uses_the_production_composer_once_it_exists():
    """The stand-in is temporary and must not outlive UGD-09's composer.

    `harness/reference_card.py` implements `docs/card-contract.md` so this suite
    can measure rendered behaviour before the production composer lands. The
    moment `bugd.banks.build_term_entry` stops raising `NotImplementedError`,
    `card_builder` switches to it automatically and this xfail becomes a strict
    XPASS failure -- a loud, unmissable prompt to re-measure rather than a green
    run over a stand-in.
    """
    assert card_builder.active_builder() == "production"


def test_card_root_role_matches_the_shipped_stylesheet():
    """The role the tests target is the one `styles.css` actually styles.

    Yomitan sets structured-content `data` keys through `element.dataset[key]`,
    which prefixes `sc` and upper-cases the first character. A `DOMStringMap`
    setter throws on a name containing `-` followed by a lowercase letter and the
    generator swallows that exception, so a hyphen-case role silently emits *no
    attribute at all* and the whole stylesheet stops applying. Asserting the
    round-trip keeps that failure loud.
    """
    from bugd.banks import CARD_ROOT_ROLE
    from bugd.styles import STYLES_CSS

    role = card_builder.CARD_ROOT_KEY
    assert "-" not in role, (
        f"card root role {role!r} contains a hyphen; Yomitan's dataset "
        "assignment would throw and emit no attribute at all"
    )
    expected_attribute = "data-sc-" + "".join(
        f"-{char.lower()}" if char.isupper() else char for char in role
    )
    assert card_builder.CARD_ROOT_SELECTOR == f"[{expected_attribute}]", (
        f"selector {card_builder.CARD_ROOT_SELECTOR} does not match the "
        f"attribute {expected_attribute} that role {role!r} produces"
    )
    assert expected_attribute in STYLES_CSS, (
        f"the shipped stylesheet does not target {expected_attribute}; it styles "
        f"role {CARD_ROOT_ROLE!r} instead, so none of its rules would apply"
    )
