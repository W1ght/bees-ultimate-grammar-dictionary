#!/usr/bin/env python3
"""Fail-closed proof that a PUBLIC archive carries no excluded source's bytes.

`bugd.publish_filter` decides what may be published from each record's own
provenance. This script checks the *result* independently, in the packaged bytes,
because the two claims are different:

* the filter admitted only redistributable records  — a decision about inputs;
* the archive contains nothing from an excluded source — a fact about outputs.

A schema-valid archive with a correct entry count can still leak an excluded
producer's name through a stylesheet comment, an attribution string, a tag bank
label, or a cross-reference. That happened for real: a `styles.css` comment
illustrating JLPT disagreement named two of the excluded community sources, so
the public artifact shipped their names after the filter had removed all their
content. No dictionary content leaked, but a published archive naming a source it
deliberately excluded is a false provenance claim, so the gate treats any hit as
a failure and the comment was rewritten to be source-agnostic.

The scan reads EVERY member as text, not only the term banks, for that reason.

Usage:
    python3 scripts/audit_public_archive.py [ZIP] [PUBLIC_EXTRACTED_DIR]

Exits non-zero on any leak, on a missing admitted source, or when the archive's
declared sources disagree with the filtered corpus.
"""

from __future__ import annotations

import json
import pathlib
import sys
import zipfile

#: Names that identify each source in packaged bytes: its internal key plus the
#: producer's human-facing label(s). The internal key alone is not enough — a tag
#: bank ships the label, and attribution strings ship the producer's own name.
SOURCE_NEEDLES: dict[str, tuple[str, ...]] = {
    "bunpou": ("bunpou", "文法 Cloze"),
    "bunpro": ("bunpro", "Bunpro"),
    "dojg": ("dojg", "DoJG", "日本語文法辞典"),
    "donna_toki": ("donna_toki", "どんなときどう使う"),
    "edewakaru": ("edewakaru", "絵でわかる日本語"),
    "imabi": ("imabi", "IMABI"),
    "nihongo_net": ("nihongo_net", "日本語NET"),
    "nihongo_no_sensei": ("nihongo_no_sensei", "のんびり日本語教師"),
    "ninjal_bunkei": ("ninjal_bunkei", "日本語文型データベース"),
    "yokubi": ("yokubi", "Yokubi", "yoku.bi"),
}


#: The sources UGD-15 cleared for public redistribution, pinned INDEPENDENTLY of
#: the filter's own output.
#:
#: This pin is the point of the script. An earlier version derived the expected
#: set from `data/extracted-public/` — i.e. from the filter's result — which made
#: the gate self-referential: mutating `publish_filter.is_redistributable` to
#: accept a merely user-reported permission widened BOTH the archive and the
#: expectation, and the audit reported `FAILURES: none` while IMABI's 494 lessons
#: shipped. Verified by mutation: that exact change survived until this pin
#: existed.
#:
#: The basis is `LICENSING.md`'s redistribution decision, which admits only the
#: two sources whose CC BY 4.0 licence text is present in their own locked bytes:
#: Yokubi (`data/sources/yokubi/LICENSE` is the CC BY 4.0 text) and NINJAL
#: (`readme.txt` declares `ライセンス: CC BY 4.0` with DOI 10.15084/0002000610).
#: Widening it is a licensing decision that must be argued in LICENSING.md first,
#: not a code change.
CLEARED_FOR_PUBLIC: frozenset[str] = frozenset({"ninjal_bunkei", "yokubi"})


def admitted_sources(public_dir: pathlib.Path) -> set[str]:
    """Sources the filter actually wrote artifacts for."""
    found: set[str] = set()
    for path in sorted(public_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = str(payload.get("source") or "")
        if not source:
            raise SystemExit(f"filtered artifact declares no source: {path}")
        if not payload.get("points"):
            # publish_filter never writes an empty artifact; one here would put a
            # source's label into the tag bank while contributing no content.
            raise SystemExit(f"filtered artifact carries zero records: {path}")
        found.add(source)
    if not found:
        raise SystemExit(f"no filtered artifacts under {public_dir}")
    return found


def main(argv: list[str]) -> int:
    zip_path = pathlib.Path(
        argv[1] if len(argv) > 1 else "build-public/bees-ultimate-grammar-dictionary.zip"
    )
    public_dir = pathlib.Path(argv[2] if len(argv) > 2 else "data/extracted-public")

    if not zip_path.is_file():
        raise SystemExit(f"no public archive at {zip_path}")

    admitted = admitted_sources(public_dir)
    excluded = set(SOURCE_NEEDLES) - CLEARED_FOR_PUBLIC

    archive = zipfile.ZipFile(zip_path)
    members = archive.namelist()
    text = "".join(
        archive.read(name).decode("utf-8", "replace") for name in members
    )

    failures: list[str] = []

    print(f"archive: {zip_path} ({zip_path.stat().st_size} bytes, {len(members)} members)")
    print(f"filtered corpus: {public_dir}")
    print(f"cleared for public (pinned from LICENSING.md): {sorted(CLEARED_FOR_PUBLIC)}")
    print(f"filter admitted: {sorted(admitted)}")
    print(f"must be absent: {sorted(excluded)}\n")

    # The filter's own result is checked against the pin FIRST, so a loosened
    # predicate is caught even before the byte scan runs.
    print("--- the filter must admit exactly the cleared set ---")
    if admitted == set(CLEARED_FOR_PUBLIC):
        print(f"OK   filter admitted exactly {sorted(admitted)}")
    else:
        extra = sorted(admitted - CLEARED_FOR_PUBLIC)
        missing = sorted(CLEARED_FOR_PUBLIC - admitted)
        print(f"FAIL filter admitted {sorted(admitted)}; extra={extra} missing={missing}")
        failures.append(
            f"filter admitted {sorted(admitted)} but LICENSING.md clears "
            f"{sorted(CLEARED_FOR_PUBLIC)} (extra={extra}, missing={missing})"
        )

    print("\n--- every EXCLUDED source must be absent from every member ---")
    for source in sorted(excluded):
        counts = {n: text.count(n) for n in SOURCE_NEEDLES[source]}
        total = sum(counts.values())
        print(f"{'FAIL' if total else 'OK  '} {source:20} {counts}")
        if total:
            failures.append(f"excluded source {source} appears in the archive: {counts}")

    print("\n--- every ADMITTED source must be present and attributed ---")
    tag_bank = json.loads(archive.read("tag_bank_1.json"))
    tagged = {str(row[0]) for row in tag_bank}
    index = json.loads(archive.read("index.json"))
    attribution = str(index.get("attribution") or "")
    for source in sorted(admitted):
        counts = {n: text.count(n) for n in SOURCE_NEEDLES[source]}
        in_tags = source in tagged
        labels = [n for n in SOURCE_NEEDLES[source] if n != source]
        in_attr = any(label in attribution for label in labels)
        ok = sum(counts.values()) > 0 and in_tags and in_attr
        print(
            f"{'OK  ' if ok else 'FAIL'} {source:20} hits={counts} "
            f"tagBank={in_tags} indexAttribution={in_attr}"
        )
        if not ok:
            failures.append(
                f"admitted source {source}: hits={counts} tagBank={in_tags} "
                f"indexAttribution={in_attr}"
            )

    print("\n--- the archive must declare exactly the filtered sources ---")
    if tagged == admitted:
        print(f"OK   tag bank declares exactly {sorted(tagged)}")
    else:
        print(f"FAIL tag bank {sorted(tagged)} != filtered {sorted(admitted)}")
        failures.append(
            f"tag bank declares {sorted(tagged)} but the filtered corpus is {sorted(admitted)}"
        )

    print()
    if failures:
        print(f"FAILURES: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("FAILURES: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
