"""Fail-closed redistribution filter for the PUBLIC artifact.

UGD-15's licensing audit (``LICENSING.md``) recorded that eight of the ten
acquired sources are not redistributable, and named the gap this module closes:

    "There is no publish-time filter. `redistributable` is recorded in
    provenance and carried through extraction, but no code in the build path
    reads it -- the flag appears only in the acquisition scripts that write it.
    It is therefore advisory metadata, not a machine-enforced gate. A publish
    step must add an explicit fail-closed filter on
    `provenance.redistributable` (and assert the resulting corpus is non-empty)
    before shipping anything publicly."

Design boundaries this module holds, in order of importance:

**Absent is not permitted.** The predicate is ``provenance.redistributable is
True``, not "not False". A source whose lock carries no licence block at all
(``bunpro``, ``imabi``) has no grant, so its records must be excluded even
though nothing says ``False``. Every one of the eight non-redistributable
sources would pass a ``!= False`` test on at least some rows, so this
distinction is the whole gate rather than a stylistic one.

**Per row, not per source.** The flag lives on each record's ``provenance``, so
that is where it is read. A source-level allowlist would silently ship a row
whose own provenance disagrees with its source's reputation.

**Fail closed on an empty result.** A filter that removes everything and
publishes a valid empty archive is the worst outcome: schema validation passes
and the release ships nothing. ``filter_extracted`` raises
``EmptyPublicCorpus`` instead.

**Non-destructive.** The filter writes a SEPARATE extracted directory and never
edits the full local corpus, so the local build (which legitimately uses all ten
sources) is unaffected and the public build is reproducible from the same locked
bytes.

**It reports what it dropped.** The manifest names every excluded source with
its row count and the reason, so a reviewer can check the exclusion list against
``LICENSING.md`` rather than trusting a total.
"""

from __future__ import annotations

import pathlib

from .jsonio import MalformedPayload, dump_json, load_json

#: Permission bases that are NOT a licence. A record carrying one of these has a
#: grant somebody *reported*, with no document that a third party could check.
#: UGD-15's decision for this class is explicit: "A publish step should obtain
#: that approval in writing before relying on it." Until such a document is
#: acquired and locked, these records stay out of the public artifact even when
#: their `redistributable` flag says True.
UNVERIFIED_PERMISSION_BASES = frozenset({"user-reported"})


class EmptyPublicCorpus(MalformedPayload):
    """Filtering left no redistributable record.

    Raised rather than emitting an empty public corpus: a valid, schema-passing
    archive with zero entries would publish successfully and ship nothing.
    """

    def __init__(self, considered: int) -> None:
        self.considered = considered
        super().__init__(
            f"the redistribution filter admitted 0 of {considered} extracted "
            f"records, so there is nothing to publish. Refusing to build an "
            f"empty public archive."
        )


def is_redistributable(record: dict[str, object]) -> bool:
    """Whether one extracted record may be redistributed publicly.

    Two conditions, both required:

    1. ``provenance.redistributable is True``. Strictly identity against
       ``True`` -- a missing flag, a missing provenance block, and a non-boolean
       truthy value are all NOT a grant, so the two sources whose lock carries no
       licence block at all (``bunpro``, ``imabi``) cannot pass on absence.
    2. ``provenance.permissionBasis`` is not a merely *reported* permission.
       UGD-15 separated "publishable with a verified licence in locked bytes"
       (Yokubi, NINJAL -- both CC BY 4.0, text present in the locked source) from
       "publishable only on reported permission, not independently verifiable"
       (IMABI: ``/terms/``, ``/license/`` and ``/copyright/`` all 404, and the
       only basis on record is a user statement). The audit's instruction for the
       second class is to obtain the approval **in writing** before relying on
       it, so an unwritten grant is excluded here rather than shipped.
    """
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return False
    if provenance.get("redistributable") is not True:
        return False
    if provenance.get("permissionBasis") in UNVERIFIED_PERMISSION_BASES:
        return False
    return True


def filter_extracted(
    *,
    extracted_dir: pathlib.Path,
    public_dir: pathlib.Path,
) -> dict[str, object]:
    """Write a redistributable-only copy of every extracted artifact.

    Reads ``extracted_dir/<source>.json``, keeps only records whose own
    provenance grants redistribution, and writes the survivors to
    ``public_dir/<source>.json`` in the same on-disk contract, so the keymap,
    merge, build and validate stages run over it unchanged.

    A source with zero surviving records is not written at all: an artifact
    declaring a source with an empty ``points`` list would put that source's
    label into the packaged tag bank and index attribution while contributing no
    content, which is a false attribution claim.

    Returns a manifest naming the admitted and excluded sources with row counts.
    """
    extracted_dir = pathlib.Path(extracted_dir)
    public_dir = pathlib.Path(public_dir)
    if not extracted_dir.is_dir():
        raise MalformedPayload(f"no extracted corpus at {extracted_dir}")

    public_dir.mkdir(parents=True, exist_ok=True)
    for stale in public_dir.glob("*.json"):
        stale.unlink()

    admitted: dict[str, int] = {}
    excluded: dict[str, int] = {}
    considered = 0

    for path in sorted(extracted_dir.glob("*.json")):
        payload = load_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
            raise MalformedPayload(f"malformed extracted artifact: {path}")
        source = str(payload.get("source") or "")
        if not source:
            raise MalformedPayload(f"extracted artifact declares no source: {path}")

        records = payload["points"]
        considered += len(records)
        kept = [r for r in records if isinstance(r, dict) and is_redistributable(r)]
        dropped = len(records) - len(kept)

        if not kept:
            excluded[source] = dropped
            continue
        if dropped:
            # A source that grants redistribution for only some of its rows is a
            # provenance defect, not something to paper over by shipping the
            # subset: the two admitted sources are wholesale CC BY 4.0, so a
            # partial grant means the extractor stamped rows inconsistently.
            raise MalformedPayload(
                f"{source}: {len(kept)} of {len(records)} records declare "
                f"redistributable:true. A per-source grant must be uniform; a "
                f"split means the extractor stamps provenance inconsistently."
            )

        admitted[source] = len(kept)
        out = dict(payload)
        out["points"] = kept
        (public_dir / path.name).write_text(
            dump_json(out) + "\n", encoding="utf-8"
        )

    if not admitted:
        raise EmptyPublicCorpus(considered)

    return {
        "consideredRecords": considered,
        "admittedSources": admitted,
        "admittedRecords": sum(admitted.values()),
        "excludedSources": excluded,
        "excludedRecords": sum(excluded.values()),
        "publicDir": str(public_dir),
    }
