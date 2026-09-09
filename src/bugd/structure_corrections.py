"""Byte-anchored source-defect corrections applied at the extract boundary.

Some source term banks ship a formation rule (the `structure` / 接続 field) or an
example whose stated Japanese the same card's own examples contradict — a learner
reading the compact card is told how to build a pattern and the rule is wrong.
UGD-11c located 100 such cases against the frozen candidate and confirmed the
largest cluster lives in the *immutable source bytes*, not in this repo's
extractor (`data/sources/dojg/term_bank_1.json` literally contains
「にはかならない」 in the 接続 table while every example correctly reads
「にほかならない」). The extractor is faithful; the publisher's bytes are wrong.

The locked source bytes must not be edited — the SOURCE.lock digests are a
fail-closed integrity gate and rewriting a term bank would either break the lock
or launder a defect into "our" bytes with no audit trail. So corrections are a
*separate, versioned overlay* applied to the normalized `GrammarPoint` AFTER
extraction and BEFORE the per-source artifact is written. Each correction is:

* **Byte-anchored** — it names the exact wrong substring (`anchor`) it expects to
  find in the targeted field. If the anchor is absent (the source drifted, or a
  prior correction already ran), application raises. A silently changed source
  can therefore never ship an un-reviewed edit.
* **Evidence-bounded** — the scope rule (UGD-11c-C acceptance #2) is that a
  correction may only restore a form the card's OWN examples/headword already
  demonstrate. Findings whose fix would require inventing a rule, or that collide
  with UGD-11c's corpus-wide refutations (edewakaru's ［辞書形］ house notation, the
  132 double-marker lines), are NOT encoded here; they live in the data file's
  `documented_not_corrected` block with a reason, so the decision is auditable
  rather than silent.

`op` is `replace_all`: every occurrence of `anchor` in the field becomes
`replacement`. `replace_all` (not first-only) so a defect repeated across the
three formation lines of one 接続 table is fixed uniformly; the anchor is chosen
specific enough that it never matches unintended text in the same card.
"""

from __future__ import annotations

import dataclasses
import pathlib

from .jsonio import MalformedPayload, load_json
from .model import Example, GrammarPoint

#: The corrections overlay ships in the repo (tracked), beside the data stages.
DEFAULT_CORRECTIONS_PATH = pathlib.Path("data/corrections/structure_corrections.json")

#: Fields a correction may target. `structure` is a plain string; `examples` is a
#: tuple of Example, and the anchor is matched/replaced inside each example's
#: `japanese` surface text (never the English gloss, which sources rarely carry).
_STRING_FIELDS = ("meaning", "structure", "explanation", "notes", "expression")
_EXAMPLE_FIELD = "examples"


class CorrectionError(MalformedPayload):
    """A correction is malformed or its anchor was not found — fail closed."""


@dataclasses.dataclass(frozen=True)
class Correction:
    """One byte-anchored field correction, keyed by (source, source_id, field)."""

    source: str
    source_id: str
    field: str
    op: str
    anchor: str
    replacement: str
    rationale: str = ""

    def __post_init__(self) -> None:
        for name in ("source", "source_id", "field", "op", "anchor"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CorrectionError(f"correction.{name} must be a non-empty string")
        if self.op != "replace_all":
            raise CorrectionError(f"unsupported correction op: {self.op!r}")
        if not isinstance(self.replacement, str):
            raise CorrectionError("correction.replacement must be a string")
        if self.anchor == self.replacement:
            raise CorrectionError(
                f"correction anchor equals replacement (no-op): {self.anchor!r}"
            )
        if self.field != _EXAMPLE_FIELD and self.field not in _STRING_FIELDS:
            raise CorrectionError(f"correction targets unknown field: {self.field!r}")


def load_corrections(path: pathlib.Path = DEFAULT_CORRECTIONS_PATH) -> list[Correction]:
    """Load the corrections overlay, or return an empty list when absent.

    A missing overlay is not an error: the extract stage runs before the overlay
    is authored, and a source with no known defects has nothing to correct.
    """
    path = pathlib.Path(path)
    if not path.is_file():
        return []
    payload = load_json(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("corrections"), list):
        raise CorrectionError(f"malformed corrections overlay: {path}")
    corrections: list[Correction] = []
    for item in payload["corrections"]:
        if not isinstance(item, dict):
            raise CorrectionError(f"malformed correction entry in {path}")
        corrections.append(
            Correction(
                source=item.get("source", ""),
                source_id=item.get("source_id", ""),
                field=item.get("field", ""),
                op=item.get("op", ""),
                anchor=item.get("anchor", ""),
                replacement=item.get("replacement", ""),
                rationale=item.get("rationale", ""),
            )
        )
    return corrections


def apply_corrections(
    points: list[GrammarPoint],
    corrections: list[Correction],
    *,
    source: str,
) -> tuple[list[GrammarPoint], list[dict[str, object]]]:
    """Return `points` with every correction for `source` applied.

    Fails closed: a correction whose (source_id, field) matches no point, or
    whose anchor is not present in the targeted field of any matched point,
    raises `CorrectionError`. That is the whole point of anchoring — a drifted
    source or an already-applied correction must surface loudly, never silently
    become a no-op that lets an un-reviewed source defect ship.
    """
    mine = [c for c in corrections if c.source == source]
    if not mine:
        return points, []

    # Index points by source_id. A source may repeat a source_id across the
    # reviewer's split senses; a field correction applies to every copy.
    by_id: dict[str, list[int]] = {}
    for index, point in enumerate(points):
        by_id.setdefault(point.source_id, []).append(index)

    result = list(points)
    applied: list[dict[str, object]] = []
    for correction in mine:
        targets = by_id.get(correction.source_id)
        if not targets:
            # The targeted card is not in THIS run (a fixture set or an `--only`
            # subset). That is not drift, so it is skipped rather than fatal. Full
            # corpus-coverage of the overlay is asserted by the regression suite
            # (`test_every_overlay_correction_landed_in_the_real_extract`), which
            # would catch a correction that matches no card in a complete build.
            continue
        hits = 0
        for index in targets:
            point = result[index]
            new_point, count = _apply_to_point(point, correction)
            if count:
                result[index] = new_point
                hits += count
        if hits == 0:
            raise CorrectionError(
                f"{source}/{correction.source_id}: anchor not found in field "
                f"{correction.field!r}: {correction.anchor!r}"
            )
        applied.append(
            {
                "source": source,
                "source_id": correction.source_id,
                "field": correction.field,
                "anchor": correction.anchor,
                "replacement": correction.replacement,
                "occurrences": hits,
            }
        )
    return result, applied


def _apply_to_point(
    point: GrammarPoint, correction: Correction
) -> tuple[GrammarPoint, int]:
    """Apply one correction to one point, returning the new point + hit count."""
    if correction.field == _EXAMPLE_FIELD:
        new_examples, count = _apply_to_examples(point.examples, correction)
        if not count:
            return point, 0
        return dataclasses.replace(point, examples=new_examples), count

    value = getattr(point, correction.field)
    if not value or correction.anchor not in value:
        return point, 0
    count = value.count(correction.anchor)
    fixed = value.replace(correction.anchor, correction.replacement)
    return dataclasses.replace(point, **{correction.field: fixed}), count


def _apply_to_examples(
    examples: tuple[Example, ...], correction: Correction
) -> tuple[tuple[Example, ...], int]:
    """Replace the anchor inside each example's Japanese surface text."""
    out: list[Example] = []
    count = 0
    for example in examples:
        if correction.anchor in example.japanese:
            count += example.japanese.count(correction.anchor)
            fixed = example.japanese.replace(correction.anchor, correction.replacement)
            # Highlights are substrings the source marked; drop any that no longer
            # occur in the corrected sentence rather than leave a dangling span.
            highlights = tuple(h for h in example.highlight if h in fixed)
            out.append(dataclasses.replace(example, japanese=fixed, highlight=highlights))
        else:
            out.append(example)
    return tuple(out), count


__all__ = [
    "Correction",
    "CorrectionError",
    "DEFAULT_CORRECTIONS_PATH",
    "apply_corrections",
    "load_corrections",
]
