"""Deterministic, evidence-backed reading corrections applied before merge.

Sources are read verbatim (``bugd.sources`` copies the publisher's reading
column unchanged), which is the correct faithful behaviour. A small, audited set
of upstream readings are nonetheless *impossible* renderings of their own written
form — a wrong reading makes the entry unfindable by its real kana and pollutes
the per-source disclosure. UGD-11c-B confirmed nine such cases (fresh single-card
LLM review, independent adversarial second opinion, byte-exact re-verification).

This module is the one documented exception to verbatim carry. It applies the
corrections in ``data/corrections/readings.json`` to the extracted rows before
they reach the merge, and it fails closed:

* every correction is matched byte-exact on ``(source, source_id, expression,
  from)`` so it can never silently rewrite a different value;
* a correction that matches zero rows raises ``StaleCorrection`` (the extraction
  drifted or the correction is obsolete) rather than passing silently;
* the correction is a no-op transform when applied twice, because after the
  first pass no row still carries the ``from`` value.

Corrections are data, not code: the reading targets come from independent
evidence (KANJIDIC2/UniDic and/or a sibling contribution on the same card that
already gives the right reading), never invented. See the ``evidence`` field on
each entry and the ``_meta`` block in the overlay for provenance.
"""

from __future__ import annotations

import dataclasses
import pathlib

from .jsonio import MalformedPayload, load_json

#: Default location of the tracked reading-correction overlay.
DEFAULT_CORRECTIONS_PATH = pathlib.Path("data/corrections/readings.json")

_REQUIRED_FIELDS = ("source", "source_id", "expression", "from", "to")


@dataclasses.dataclass(frozen=True)
class ReadingCorrection:
    """One evidence-backed reading correction, matched byte-exact."""

    source: str
    source_id: str
    expression: str
    from_reading: str
    to_reading: str
    evidence: str

    @property
    def match_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.source_id, self.expression, self.from_reading)


class StaleCorrection(MalformedPayload):
    """A declared correction matched no extracted row.

    Raised instead of applying corrections best-effort. A correction that
    matches nothing means the extraction it was written against has changed (or
    the correction is obsolete); silently ignoring it would let a stale overlay
    claim to fix a defect it no longer touches.
    """

    def __init__(self, unmatched: list[ReadingCorrection]) -> None:
        self.unmatched = unmatched
        shown = ", ".join(
            f"{c.source}:{c.source_id} {c.from_reading!r}->{c.to_reading!r}"
            for c in unmatched
        )
        super().__init__(
            f"{len(unmatched)} reading correction(s) matched no extracted row "
            f"({shown}). The extraction changed or the correction is stale; "
            f"update data/corrections/readings.json rather than shipping a "
            f"correction that fixes nothing."
        )


def load_corrections(
    path: pathlib.Path = DEFAULT_CORRECTIONS_PATH,
) -> list[ReadingCorrection]:
    """Parse the correction overlay. Missing file means no corrections."""
    if not path.is_file():
        return []
    payload = load_json(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("corrections"), list):
        raise MalformedPayload(f"malformed corrections overlay: {path}")
    corrections: list[ReadingCorrection] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in payload["corrections"]:
        if not isinstance(raw, dict):
            raise MalformedPayload("each correction must be an object")
        for field in _REQUIRED_FIELDS:
            value = raw.get(field)
            if not isinstance(value, str) or not value:
                raise MalformedPayload(
                    f"a correction is missing a non-empty `{field}`: {raw!r}"
                )
        if raw["from"] == raw["to"]:
            raise MalformedPayload(
                f"a correction's `from` and `to` are identical (no-op): {raw!r}"
            )
        correction = ReadingCorrection(
            source=raw["source"],
            source_id=raw["source_id"],
            expression=raw["expression"],
            from_reading=raw["from"],
            to_reading=raw["to"],
            evidence=str(raw.get("evidence") or ""),
        )
        if correction.match_key in seen:
            raise MalformedPayload(
                f"duplicate correction key {correction.match_key!r}"
            )
        seen.add(correction.match_key)
        corrections.append(correction)
    return corrections


def apply_corrections(
    rows: list[tuple[str, dict[str, object]]],
    corrections: list[ReadingCorrection],
) -> tuple[list[tuple[str, dict[str, object]]], list[dict[str, object]]]:
    """Return ``(rows, applied)`` with each correction's ``from`` swapped to ``to``.

    Rows are matched byte-exact on ``(source, source_id, expression, reading)``.
    ``applied`` is a per-row audit trail (one entry per row rewritten). Rows are
    shallow-copied before mutation so the caller's input is untouched.

    **Staleness is scoped to the sources the corpus actually carries.** A
    correction for a source that contributes NO rows here is not stale -- the
    corpus simply does not include that source, which happens legitimately
    whenever the corpus is narrower than the overlay -- a single-source stage run
    (`--source dojg`), or a checkout that has acquired only some sources. Raising
    there would make a narrower corpus fail for the wrong reason.

    A correction whose source IS present but whose row is not remains
    ``StaleCorrection``, which is the case the gate exists for: the extraction it
    was written against drifted, or the correction is obsolete. So the gate keeps
    its full bite on every source in scope, and only stops speaking about sources
    that are out of scope.
    """
    by_key: dict[tuple[str, str, str, str], ReadingCorrection] = {
        c.match_key: c for c in corrections
    }
    present_sources = {source for source, _ in rows}
    matched: set[tuple[str, str, str, str]] = set()
    applied: list[dict[str, object]] = []
    out: list[tuple[str, dict[str, object]]] = []
    for source, record in rows:
        key = (
            source,
            str(record.get("source_id") or ""),
            str(record.get("expression") or ""),
            str(record.get("reading")) if record.get("reading") is not None else "",
        )
        correction = by_key.get(key)
        if correction is None:
            out.append((source, record))
            continue
        matched.add(key)
        rewritten = dict(record)
        rewritten["reading"] = correction.to_reading
        out.append((source, rewritten))
        applied.append(
            {
                "source": correction.source,
                "source_id": correction.source_id,
                "expression": correction.expression,
                "from": correction.from_reading,
                "to": correction.to_reading,
            }
        )
    unmatched = [
        c
        for c in corrections
        if c.match_key not in matched and c.source in present_sources
    ]
    if unmatched:
        raise StaleCorrection(unmatched)
    return out, applied


__all__ = [
    "DEFAULT_CORRECTIONS_PATH",
    "ReadingCorrection",
    "StaleCorrection",
    "load_corrections",
    "apply_corrections",
]
