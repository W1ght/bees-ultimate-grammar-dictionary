"""Canonical JSON serialisation shared by every stage.

Deterministic bytes are a build requirement: the same normalized corpus must
produce the same artifact digest, so every JSON member is written with sorted
keys, no insignificant whitespace, and no ASCII escaping of Japanese text.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def dump_json(value: Any) -> str:
    """Serialise `value` to canonical, deterministic JSON text."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_json(text: str | bytes) -> Any:
    """Parse JSON text, rejecting non-finite numbers."""
    return json.loads(text, parse_constant=_reject_constant)


def _reject_constant(name: str) -> Any:
    raise MalformedPayload(f"JSON contains the non-finite constant {name}")


def content_hash(value: Any) -> str:
    """Stable sha256 of the canonical serialisation of `value`."""
    return hashlib.sha256(dump_json(value).encode("utf-8")).hexdigest()


class MalformedPayload(ValueError):
    """A source, intermediate, or artifact payload failed validation.

    Raised instead of silently coercing: a partial or malformed corpus must fail
    the build closed rather than ship a quietly degraded dictionary.
    """


__all__ = ["dump_json", "load_json", "content_hash", "MalformedPayload"]
