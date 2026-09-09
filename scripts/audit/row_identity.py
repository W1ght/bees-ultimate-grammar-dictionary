"""Prove row identity is TOTAL, not merely non-colliding inside one entry.

`attribution_precision.py` only asks whether two same-handle contributions inside
one entry disagree. That is the filed defect's own measurement, but it is a weak
claim on its own: a handle could still be reused across two DIFFERENT entries and
pass it. This probe asserts the stronger properties the fix actually claims:

1. every contribution carries a `rowUid` matching `<source>:<positive-ordinal>`;
2. a `rowUid` is globally unique -- it appears in at most one contribution in the
   entire dataset, across all entries and senses;
3. every `rowUid` names exactly one extracted source row, and that row's
   substance is the one the contribution restates (so identity was not just
   made unique, it was made CORRECT);
4. `sourceId` is still the producer's human handle and is NOT claimed to be
   unique -- the histogram of its reuse is reported, not asserted away.

Usage: row_identity.py <unified.jsonl> <extracted-dir> <out.json>
"""
import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

UID = re.compile(r"[^:]+:[1-9][0-9]*\Z", re.ASCII)
#: Fields compared to prove a uid names the row whose substance is restated.
SUBSTANCE = ("meaning", "structure", "nuance", "explanation", "notes", "jlpt")


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unified", type=Path)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    rows_by_uid = {}
    source_id_counts = collections.defaultdict(collections.Counter)
    for path in sorted(args.extracted.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = payload["source"]
        for record in payload["points"]:
            uid = record.get("row_uid", "")
            if uid in rows_by_uid:
                print(f"FAIL extracted row uid reused: {uid}")
                return 1
            rows_by_uid[uid] = (source, record)
            source_id_counts[source][record.get("source_id")] += 1

    seen = {}
    malformed = []
    duplicated = []
    unknown = []
    substance_mismatch = []
    contributions = 0

    for line in args.unified.open(encoding="utf-8"):
        entry = json.loads(line)
        if entry["kind"] != "point":
            continue
        for sense in entry["senses"]:
            for c in sense["contributions"]:
                contributions += 1
                uid = c.get("rowUid", "")
                where = f"{entry['entryId']}/{sense['canonicalKey']}"
                if not UID.fullmatch(uid) or not uid.startswith(c["source"] + ":"):
                    malformed.append({"at": where, "rowUid": uid, "source": c["source"]})
                    continue
                if uid in seen:
                    duplicated.append({"rowUid": uid, "first": seen[uid], "second": where})
                    continue
                seen[uid] = where
                row = rows_by_uid.get(uid)
                if row is None:
                    unknown.append({"at": where, "rowUid": uid})
                    continue
                _source, record = row
                bad = [
                    field
                    for field in SUBSTANCE
                    if norm(c.get(field)) != norm(record.get(field))
                ]
                if bad or norm(c["expression"]) != norm(record.get("expression")):
                    substance_mismatch.append(
                        {"at": where, "rowUid": uid, "fields": bad or ["expression"]}
                    )

    reuse = {
        source: {
            "rows": sum(counter.values()),
            "distinctSourceIds": len(counter),
            "reusedSourceIds": sum(1 for v in counter.values() if v > 1),
            "maxRowsPerSourceId": max(counter.values()),
        }
        for source, counter in sorted(source_id_counts.items())
    }

    report = {
        "unified": str(args.unified),
        "extractedRows": len(rows_by_uid),
        "contributions": contributions,
        "distinctRowUids": len(seen),
        "malformedRowUids": malformed,
        "globallyDuplicatedRowUids": duplicated,
        "rowUidsNamingNoExtractedRow": unknown,
        "substanceMismatches": substance_mismatch,
        "sourceIdStillNotUnique": reuse,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    failures = {
        "malformed rowUid": malformed,
        "rowUid reused across the dataset": duplicated,
        "rowUid names no extracted row": unknown,
        "rowUid names a row with different substance": substance_mismatch,
    }
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)},
                     ensure_ascii=False, indent=1))
    ok = True
    for label, items in failures.items():
        print(f"{'OK  ' if not items else 'FAIL'} {label}: {len(items)}")
        if items:
            print("      e.g.", json.dumps(items[0], ensure_ascii=False))
            ok = False
    if len(seen) != contributions:
        print(f"FAIL distinct rowUids {len(seen)} != contributions {contributions}")
        ok = False
    else:
        print(f"OK   every contribution has its own rowUid: {contributions}")
    print("\nVERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
