"""Reader for the cross-source canonical keymap produced by the matching card.

The merge stage consumes `data/merge/keymap.json` when it exists and derives its
own keys when it does not, so merging is runnable before the matcher lands and
switches to the matcher's authority the moment its artifact appears. Which
authority produced a given key is recorded per section (`keyOrigin`) and counted
in the merge stats, so a unified corpus never hides where its alignment came
from.

Two on-disk shapes are accepted because they are both lossless renderings of the
same mapping:

* ``{"assignments": [{"source": ..., "sourceId": ..., "substanceHash": ...,
  "canonicalKey": ...}, ...]}``
* ``{"assignments": {"<source>\\u001f<sourceId>\\u001f<substanceHash>": "<key>", ...}}``

``substanceHash`` is part of the identity because ``sourceId`` is **not unique** in
this corpus: measured against `data/extracted/*.json`, edewakaru ships `も` eleven
times and donna_toki ships `お` six times, as genuinely different senses that must
receive different canonical keys. Addressing rows by `(source, sourceId)` alone
would make those rows collide and be rejected as contradictory. The hash is
omitted only by legacy two-part payloads, which are still accepted so a keymap
written before this identity was measured keeps loading.

A record whose pair is absent from the keymap falls back to a derived key rather
than being dropped: a partial keymap must never silently delete a source's
substance.
"""

from __future__ import annotations

import pathlib

from .jsonio import MalformedPayload, load_json

#: Separator used by the flat-mapping shape. Chosen because no source name, source
#: id, or hex hash in this corpus can contain a unit separator.
PAIR_SEPARATOR = "\u001f"

KEYMAP_NAME = "keymap.json"

#: Identity of one source row: source, the producer's own id, and the substance
#: hash that disambiguates a producer's repeated ids.
RowKey = tuple[str, str, str]


def _pair(source: object, source_id: object, substance: object = "") -> RowKey:
    if not isinstance(source, str) or not source.strip():
        raise MalformedPayload("keymap assignment needs a non-empty source")
    if not isinstance(source_id, str) or not source_id.strip():
        raise MalformedPayload("keymap assignment needs a non-empty sourceId")
    if substance is None:
        substance = ""
    if not isinstance(substance, str):
        raise MalformedPayload("keymap substanceHash must be a string when present")
    return source, source_id, substance


def parse_keymap(payload: object) -> dict[RowKey, str]:
    """Normalize either accepted keymap shape into one `(source, id, hash) -> key` map."""
    if not isinstance(payload, dict):
        raise MalformedPayload("keymap.json must be a JSON object")
    assignments = payload.get("assignments")
    if assignments is None:
        raise MalformedPayload("keymap.json must carry an 'assignments' member")

    mapping: dict[RowKey, str] = {}

    if isinstance(assignments, dict):
        items = []
        for flat, key in assignments.items():
            if not isinstance(flat, str) or PAIR_SEPARATOR not in flat:
                raise MalformedPayload(f"malformed keymap pair: {flat!r}")
            parts = flat.split(PAIR_SEPARATOR)
            if len(parts) == 2:
                source, source_id, substance = parts[0], parts[1], ""
            elif len(parts) == 3:
                source, source_id, substance = parts
            else:
                raise MalformedPayload(f"malformed keymap pair: {flat!r}")
            items.append((source, source_id, substance, key))
    elif isinstance(assignments, list):
        items = []
        for item in assignments:
            if not isinstance(item, dict):
                raise MalformedPayload("keymap assignments must be objects")
            items.append(
                (
                    item.get("source"),
                    item.get("sourceId"),
                    item.get("substanceHash") or "",
                    item.get("canonicalKey"),
                )
            )
    else:
        raise MalformedPayload("keymap 'assignments' must be an object or a list")

    for source, source_id, substance, key in items:
        row = _pair(source, source_id, substance)
        if not isinstance(key, str) or not key.strip():
            raise MalformedPayload(f"keymap canonicalKey must be a non-empty string for {row}")
        previous = mapping.get(row)
        if previous is not None and previous != key:
            raise MalformedPayload(
                f"keymap assigns {row} to two canonical keys: {previous!r} and {key!r}"
            )
        mapping[row] = key
    return mapping


def load_keymap(directory: pathlib.Path) -> dict[RowKey, str] | None:
    """Load `<directory>/keymap.json`, or `None` when the matcher has not run.

    A malformed keymap fails closed (raises) rather than being ignored: silently
    falling back to derived keys would present matcher-authored alignment that
    was never actually applied.
    """
    path = directory / KEYMAP_NAME
    if not path.is_file():
        return None
    return parse_keymap(load_json(path.read_text(encoding="utf-8")))


__all__ = ["KEYMAP_NAME", "PAIR_SEPARATOR", "RowKey", "load_keymap", "parse_keymap"]
