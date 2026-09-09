"""Post-extraction content corrections for confirmed source defects.

A source's publisher bytes are immutable: the extractor reads them under a
digest-checked lock (``bugd.sources.base.Extractor.read_locked_bytes``) and this
module never touches those bytes or the ``SOURCE.lock.json`` digests. Instead it
rewrites the extractor's *output* ``GrammarPoint`` records, so the corpus that
flows into the merge reflects the review's confirmed dispositions while the
locked inputs stay byte-exact and reproducible.

Every correction is one confirmed defect from an adversarial, byte-verified
review (UGD-11c). A correction is a **deletion**, never an authored replacement:

* ``drop_example``  — remove one defective example sentence from a contribution.
* ``remove_span``   — delete a wrong/self-contradictory clause from a text field
                      in place, cleaning up orphaned boundary punctuation, and
                      leave the rest of the publisher's text verbatim.
* ``clear_field``   — the whole field is the wrong statement; drop the field.

No paraphrase and no model-authored grammar content is ever introduced, per the
review's fail-closed rules.

Fail closed: the target span of every correction must be located exactly in the
matching record. A correction whose ``verbatim`` (or ``remove``) span cannot be
found is a stale/misapplied correction and raises ``CorrectionError`` rather than
silently doing nothing — the same discipline the extractors' lock uses.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections import defaultdict

from .jsonio import MalformedPayload, load_json
from .model import Example, GrammarPoint

#: Corrections shipped in the repo. One file per fix card keeps provenance
#: legible; all files in this directory are applied.
#: The content overlay's own directory. It must NOT be `data/corrections/`: that
#: directory is shared with UGD-11c-C's `structure_corrections.json` and
#: UGD-11c-B's `readings.json`, and this loader globs `*.json` and fails closed on
#: any file carrying a `corrections` list it cannot parse. Pointed at the shared
#: directory it read the other two overlays as malformed content manifests and
#: aborted `make extract` with `Correction.field must be a non-empty string`.
DEFAULT_CORRECTIONS_DIR = pathlib.Path("data/corrections/content")

_TEXT_FIELDS = ("meaning", "structure", "nuance", "explanation", "notes", "jlpt")

_DISPOSITIONS = ("drop_example", "remove_span", "clear_field", "replace_span")

#: Delimiters that may be orphaned at a cut boundary when a mid-sentence clause
#: is removed. Cleaning them is still deletion (of source bytes the removal
#: stranded), not authoring.
_LEADING_ORPHAN = re.compile(r"^[\s\u3000、。，．,\.・：:；;）\)]+")
_TRAILING_COMMA = re.compile(r"[、，,]\s*$")
_PUNCT_ONLY_LINE = re.compile(r"[\s\u3000、。，．,\.・：:；;「」（）\(\)]*")
_BLANK_RUN = re.compile(r"\n{3,}")


class CorrectionError(MalformedPayload):
    """A correction could not be located or is malformed — fail closed."""


def _clean_after_removal(text: str, span: str) -> str:
    """Remove ``span`` from ``text`` once and tidy the cut boundary.

    Deterministic: strips leading orphaned delimiters that the removal exposed,
    drops a dangling coordinating comma left on the preceding fragment, discards
    lines that became punctuation-only, and collapses blank-line runs. Produces
    the same output for the same input on every run.
    """
    idx = text.find(span)
    if idx < 0:
        raise CorrectionError(f"remove span not found: {span!r}")
    before = text[:idx]
    after = _LEADING_ORPHAN.sub("", text[idx + len(span):])
    before = _TRAILING_COMMA.sub("", before).rstrip()
    if after.strip():
        needs_break = before and not before.endswith("\n") and not after.startswith("\n")
        joined = before + ("\n" if needs_break else "") + after
    else:
        joined = before
    kept = []
    for line in joined.split("\n"):
        stripped = line.strip()
        if stripped and _PUNCT_ONLY_LINE.fullmatch(stripped):
            continue
        kept.append(line.rstrip())
    return _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()


@dataclasses.dataclass(frozen=True)
class Correction:
    source: str
    source_id: str
    field: str
    disposition: str
    verbatim: str
    remove: str | None = None  # explicit span to delete when != verbatim
    replacement: str | None = None  # exact replacement text for replace_span
    cluster: str = ""
    issue: str = ""

    def __post_init__(self) -> None:
        for name in ("source", "source_id", "field", "disposition", "verbatim"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CorrectionError(f"Correction.{name} must be a non-empty string")
        if self.disposition not in _DISPOSITIONS:
            raise CorrectionError(f"unknown disposition: {self.disposition!r}")
        if self.disposition == "drop_example" and self.field != "examples":
            raise CorrectionError("drop_example must target the examples field")
        if self.disposition in ("remove_span", "clear_field") and self.field not in _TEXT_FIELDS:
            raise CorrectionError(
                f"{self.disposition} must target a text field, not {self.field!r}"
            )
        if self.disposition == "replace_span":
            if self.field not in _TEXT_FIELDS and self.field != "examples":
                raise CorrectionError(
                    f"replace_span must target a text field or examples, not {self.field!r}"
                )
            if not isinstance(self.replacement, str) or not self.replacement:
                raise CorrectionError("replace_span requires a non-empty replacement")
            if self.replacement == self.verbatim:
                raise CorrectionError("replace_span replacement equals verbatim (no-op)")

    @property
    def target(self) -> str:
        return self.remove or self.verbatim


def load_corrections(
    corrections_dir: pathlib.Path = DEFAULT_CORRECTIONS_DIR,
) -> list[Correction]:
    """Load every correction manifest in the directory (sorted, deterministic).

    A manifest is a JSON object carrying a ``corrections`` list. Sidecar files in
    the same directory that are objects *without* a ``corrections`` key (a
    resolution report, an index) are skipped rather than treated as manifests, so
    a report can live beside the manifest without breaking the build. A file that
    is neither shape is malformed and fails closed.
    """
    directory = pathlib.Path(corrections_dir)
    if not directory.is_dir():
        return []
    out: list[Correction] = []
    for path in sorted(directory.glob("*.json")):
        payload = load_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CorrectionError(f"malformed corrections file: {path}")
        if "corrections" not in payload:
            continue  # a sidecar (report/index), not a correction manifest
        if not isinstance(payload["corrections"], list):
            raise CorrectionError(f"malformed corrections file: {path}")
        for item in payload["corrections"]:
            if not isinstance(item, dict):
                raise CorrectionError(f"malformed correction entry in {path}")
            out.append(
                Correction(
                    source=item.get("source", ""),
                    source_id=item.get("source_id", ""),
                    field=item.get("field", ""),
                    disposition=item.get("disposition", ""),
                    verbatim=item.get("verbatim", ""),
                    remove=item.get("remove"),
                    replacement=item.get("replacement"),
                    cluster=item.get("cluster", ""),
                    issue=item.get("issue", ""),
                )
            )
    return out


def _apply_one(point: GrammarPoint, correction: Correction) -> GrammarPoint:
    """Apply one correction to a matching point. Returns the rewritten point.

    Fail closed: raises if the correction's span is not present in this point.
    """
    if correction.disposition == "drop_example":
        kept = tuple(ex for ex in point.examples if correction.verbatim not in _example_text(ex))
        if len(kept) == len(point.examples):
            raise CorrectionError(
                f"drop_example verbatim not found in {correction.source}/{correction.source_id}: "
                f"{correction.verbatim!r}"
            )
        return dataclasses.replace(point, examples=kept)

    if correction.disposition == "replace_span" and correction.field == "examples":
        assert correction.replacement is not None  # guarded in __post_init__
        new_examples = []
        changed = False
        for ex in point.examples:
            jp = ex.japanese
            en = ex.english
            new_jp = jp.replace(correction.verbatim, correction.replacement) if jp else jp
            new_en = en.replace(correction.verbatim, correction.replacement) if en else en
            new_hl = tuple(
                h.replace(correction.verbatim, correction.replacement) for h in ex.highlight
            )
            if new_jp != jp or new_en != en or new_hl != ex.highlight:
                changed = True
                ex = dataclasses.replace(
                    ex, japanese=new_jp, english=new_en, highlight=new_hl
                )
            new_examples.append(ex)
        if not changed:
            raise CorrectionError(
                f"replace_span verbatim not found in any example of "
                f"{correction.source}/{correction.source_id}: {correction.verbatim!r}"
            )
        return dataclasses.replace(point, examples=tuple(new_examples))

    current = getattr(point, correction.field)
    if not current or correction.verbatim not in str(current):
        raise CorrectionError(
            f"{correction.disposition} verbatim not found in "
            f"{correction.source}/{correction.source_id} field {correction.field}: "
            f"{correction.verbatim!r}"
        )
    if correction.disposition == "clear_field":
        return dataclasses.replace(point, **{correction.field: None})
    if correction.disposition == "replace_span":
        assert correction.replacement is not None  # guarded in __post_init__
        # Replace every occurrence: a confirmed unambiguous typo is wrong
        # wherever it appears in the same field (e.g. the same misspelling in two
        # worked examples inside one explanation).
        replaced = str(current).replace(correction.verbatim, correction.replacement)
        return dataclasses.replace(point, **{correction.field: replaced})
    # remove_span
    if correction.target not in str(current):
        raise CorrectionError(
            f"remove span not found in {correction.source}/{correction.source_id} "
            f"field {correction.field}: {correction.target!r}"
        )
    cleaned = _clean_after_removal(str(current), correction.target)
    return dataclasses.replace(point, **{correction.field: cleaned or None})


def _example_text(ex: Example) -> str:
    parts = [ex.japanese or "", ex.english or ""]
    parts.extend(ex.highlight or ())
    return "\n".join(parts)


def apply_corrections(
    points: list[GrammarPoint],
    corrections: list[Correction],
    *,
    source: str | None = None,
) -> tuple[list[GrammarPoint], dict[str, object]]:
    """Apply corrections to a list of points; return the corrected list + a report.

    A correction is matched by **content**, not by identity: it applies to every
    point of its ``source`` whose target field actually contains the verbatim
    span. This matters because the community sources duplicate a shared example
    or explanation across closely related variant entries (``など`` / ``なんか`` /
    ``なんて``, ``を通して`` / ``を通じて``, the two senses of ``後に`` …), so a defect the
    review flagged once physically recurs in several records. Removing it only
    from the one ``source_id`` the reviewer attributed it to would leave the same
    defect standing in its siblings and the finding would survive re-review. The
    ``source_id`` on each correction is retained as provenance.

    Fail closed: a correction whose span is present in no point of its source
    **in the original input** raises ``CorrectionError`` — a stale correction is
    a loud build failure, not a silent no-op. Corrections may legitimately
    overlap (two findings quote the same defective example at different lengths);
    once one drops the shared example the others find it already gone. That is
    not a stale correction, so presence is judged against an original snapshot
    while edits are applied to the live list. ``applied`` counts corrections that
    were satisfied; ``pointsChanged`` counts the records actually rewritten.
    """
    relevant = [c for c in corrections if source is None or c.source == source]

    def _present(point: GrammarPoint, c: Correction) -> bool:
        if c.disposition == "drop_example" or c.field == "examples":
            return any(c.verbatim in _example_text(ex) for ex in point.examples)
        field_value = getattr(point, c.field)
        return bool(field_value) and c.verbatim in str(field_value)

    # Snapshot the original per-source records so the fail-closed guard sees the
    # defect even after a sibling correction has already removed it.
    original = list(points)

    applied = 0
    points_changed = 0
    per_disposition: dict[str, int] = defaultdict(int)
    for c in relevant:
        present_in_original = any(
            p.source == c.source and _present(p, c) for p in original
        )
        if not present_in_original:
            raise CorrectionError(
                f"correction span not found in any {c.source} record "
                f"(source_id provenance {c.source_id!r}, field {c.field}): {c.verbatim!r}"
            )
        matched = 0
        for idx, point in enumerate(points):
            if point.source != c.source or not _present(point, c):
                continue
            points[idx] = _apply_one(point, c)
            matched += 1
        applied += 1
        points_changed += matched
        per_disposition[c.disposition] += 1

    return points, {
        "applied": applied,
        "pointsChanged": points_changed,
        "byDisposition": dict(sorted(per_disposition.items())),
        "source": source,
    }


__all__ = [
    "Correction",
    "CorrectionError",
    "DEFAULT_CORRECTIONS_DIR",
    "load_corrections",
    "apply_corrections",
]
