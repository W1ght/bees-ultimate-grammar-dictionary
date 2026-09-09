"""Confirm the two UGD-11d findings rejected as `same_claim_both_sides` are now
addressable by claim handle.

UGD-11d had to reject 2 otherwise-valid findings (`になる` N5-vs-N4 and `られる`
passive-table-vs-potential-examples) purely because both sides resolved to one
`(source, sourceId)` handle. Under an ambiguous handle "same claim both sides" is
uninterpretable: it could mean two DIFFERENT records that happen to share a
headword, or one record contradicting itself. Those need opposite remedies.

The property this asserts is therefore NOT "the two sides differ" — it is that
each side is now attributable to EXACTLY ONE source record, and that the report
says which of the two shapes the finding really has:

  * `inter_record` — the sides name two different records, so the finding is a
    reportable per-record disagreement (`になる`: 1326 says N5, 1328 says N4);
  * `intra_record` — the sides name ONE record, so it is a genuine self-
    contradiction inside a single source row (`られる`: dojg:75 ships the passive
    formation table beside its own potential examples).

A first draft asserted `inter_record` for both and reported `られる` as FAIL. That
was a probe defect: `られる`'s two DoJG rows carry byte-identical structure text,
and the contradiction is structure-vs-EXAMPLE inside one row, not structure-vs-
structure across two. Requiring the sides to disagree would have hidden the
real shape.

This does NOT re-adjudicate either finding — both were low-confidence and that is
UGD-11d's call. It proves only that the identity blocker is gone.

Usage: unblocked_findings.py <unified.jsonl> <out.json>
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

#: The two rejections, transcribed from UGD-11d's
#: evidence/verified_findings.json -> rejected[] (files 0428.json, 0621.json).
#: The third rejection there is a caught hallucination, not an identity problem.
#: Each side names the field it was quoted from and a verbatim fragment of it.
CASES = [
    {
        "entryId": "になる",
        "source": "nihongo_no_sensei",
        "sourceId": "になる",
        "sideA": {"field": "jlpt", "quote": "N5"},
        "sideB": {"field": "jlpt", "quote": "N4"},
        "expectShape": "inter_record",
    },
    {
        "entryId": "られる",
        "source": "dojg",
        "sourceId": "られる",
        "sideA": {"field": "structure", "quote": "Group 1 verbs"},
        "sideB": {"field": "example", "quote": "私は日本語が読める"},
        "expectShape": "intra_record",
    },
]


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def side_text(contribution, field):
    """The text a side was quoted from, for one contribution."""
    if field == "example":
        return norm(
            " \u241e ".join(
                f"{x['japanese']} {x.get('english') or ''}"
                for x in contribution.get("examples", [])
            )
        )
    return norm(contribution.get(field))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unified", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    entries = {}
    for line in args.unified.open(encoding="utf-8"):
        entry = json.loads(line)
        if entry["kind"] == "point":
            entries[entry["entryId"]] = entry

    report = []
    ok = True
    for case in CASES:
        entry = entries.get(case["entryId"])
        if entry is None:
            report.append({**case, "verdict": "FAIL", "why": "entry not in the dataset"})
            ok = False
            continue
        under_handle = [
            c
            for sense in entry["senses"]
            for c in sense["contributions"]
            if c["source"] == case["source"] and c.get("sourceId") == case["sourceId"]
        ]
        by_uid = {c["rowUid"]: c for c in under_handle}
        result = {
            "entryId": case["entryId"],
            "oldHandle": f"{case['source']}#{case['sourceId']}",
            "contributionsUnderOldHandle": len(under_handle),
            "newHandles": sorted(by_uid),
        }
        problems = []
        if len(under_handle) < 2:
            problems.append("the old handle no longer covers 2+ contributions")
        if len(by_uid) != len(under_handle):
            problems.append("the new handles are not one per contribution")

        owners = {}
        for label in ("sideA", "sideB"):
            side = case[label]
            matched = [
                uid
                for uid, c in by_uid.items()
                if norm(side["quote"]) in side_text(c, side["field"])
            ]
            result[f"{label}Handles"] = sorted(matched)
            if not matched:
                problems.append(
                    f"{label} ({side['field']}: {side['quote']!r}) is attributable to no "
                    f"record at all"
                )
            owners[label] = set(matched)

        # A side's quote is not always unique on its own: DoJG's two られる rows ship
        # BYTE-IDENTICAL structure text, so `Group 1 verbs` legitimately matches
        # both. That is duplicated content, not ambiguous identity, and requiring
        # per-side uniqueness would report it as an identity failure. The claim
        # that matters is the SKILL 8.2 one: exactly one coherent record must
        # satisfy every side together (intra_record), or each side must have its
        # own single record (inter_record). Anything else is still ambiguous.
        if all(owners.values()):
            both = owners["sideA"] & owners["sideB"]
            if len(both) == 1:
                shape = "intra_record"
                attribution = {"record": sorted(both)[0]}
            elif len(owners["sideA"]) == 1 and len(owners["sideB"]) == 1 and not both:
                shape = "inter_record"
                attribution = {
                    "sideA": sorted(owners["sideA"])[0],
                    "sideB": sorted(owners["sideB"])[0],
                }
            else:
                shape = "ambiguous"
                attribution = {
                    "sideA": sorted(owners["sideA"]),
                    "sideB": sorted(owners["sideB"]),
                }
                problems.append(
                    "no single record satisfies both sides and neither side is unique"
                )
            result["shape"] = shape
            result["attribution"] = attribution
            if shape != case["expectShape"]:
                problems.append(f"shape is {shape}, expected {case['expectShape']}")

        result["verdict"] = "PASS" if not problems else "FAIL"
        result["problems"] = problems
        if problems:
            ok = False
        report.append(result)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("\nVERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
