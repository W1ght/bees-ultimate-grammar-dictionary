"""The pinned schemas must be the official Yomitan bytes the build claims."""

from __future__ import annotations

import hashlib

import pytest

from bugd import YOMITAN_SCHEMA_REVISION
from bugd.validate import SCHEMA_DIR, load_schema

# sha256 of each schema as published at yomidevs/yomitan tag 26.8.24.0
# (ext/data/schemas/), verified byte-identical to that tagged checkout.
PINNED_SCHEMA_DIGESTS = {
    "dictionary-index-schema.json":
        "dde43ca9ef1580ab638f49bb13bd7d5c55646afd655ff99cf429492598feb69b",
    "dictionary-tag-bank-v3-schema.json":
        "4f537818b3d4be4c40f92c991578f74d73f2239002b608eb10169ab1d63aee0b",
    "dictionary-term-bank-v3-schema.json":
        "665904fcaac715a018a7df6b49d3ace08390d614a9da4f62222bce32c8030b87",
    "dictionary-term-meta-bank-v3-schema.json":
        "7236ea5627731175c9cb3b2d22785598ae005be050e538f8fa331a6d27262369",
}


def test_schema_revision_is_pinned():
    assert YOMITAN_SCHEMA_REVISION == "26.8.24.0"


@pytest.mark.parametrize("name,digest", sorted(PINNED_SCHEMA_DIGESTS.items()))
def test_pinned_schema_bytes_are_unchanged(name, digest):
    raw = (SCHEMA_DIR / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest


def test_no_unexpected_schema_files():
    assert sorted(p.name for p in SCHEMA_DIR.glob("*.json")) == sorted(PINNED_SCHEMA_DIGESTS)


@pytest.mark.parametrize("name", sorted(PINNED_SCHEMA_DIGESTS))
def test_schemas_are_draft07(name):
    assert load_schema(name)["$schema"] == "http://json-schema.org/draft-07/schema#"
