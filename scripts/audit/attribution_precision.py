"""Measure attribution PRECISION: is the claim handle a unique row identity?

This is UGD-11d's `scripts/attribution_precision.py` (t_e97f7c1a) with ONE
change: the claim handle read from each contribution is selectable, so the same
measurement can be taken against the pre-fix handle `(source, sourceId)` and the
post-fix handle `rowUid`. Everything else -- the entry/sense walk, the NFKC+
whitespace normalisation, the five compared fields, the stats -- is unchanged, so
a drop in `collidingClaimIds` is attributable to the handle and not to a
re-written probe.

Usage:
    attribution_precision.py <unified.jsonl> <out.json> [--handle rowUid|sourceId]
"""
import argparse
import json
import sys
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

FIELDS = ("jlpt", "meaning", "structure", "explanation", "notes")


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def handle_of(contribution, handle):
    """The claim handle a reader would cite for this contribution.

    `sourceId` reproduces the pre-fix ambiguous handle. `rowUid` is the unique
    row identity; a contribution missing it is reported as the empty handle
    rather than silently skipped, so a partially-migrated dataset shows up as
    collisions instead of as a clean pass.
    """
    if handle == "sourceId":
        return f"{contribution['source']}#{contribution.get('sourceId', '')}"
    return contribution.get("rowUid", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unified", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--handle", choices=("rowUid", "sourceId"), default="rowUid")
    args = parser.parse_args()

    collisions = []
    stats = {"pointEntries": 0, "multiSourceEntries": 0, "entriesWithCollision": 0,
             "multiSourceEntriesWithCollision": 0, "collidingContributions": 0}
    field_divergence = defaultdict(int)
    contributions_seen = 0
    handles_missing = 0

    for line in args.unified.open(encoding="utf-8"):
        e = json.loads(line)
        if e["kind"] != "point":
            continue
        stats["pointEntries"] += 1
        pairs = defaultdict(list)
        sources_here = set()
        for sense in e["senses"]:
            for c in sense["contributions"]:
                contributions_seen += 1
                key = handle_of(c, args.handle)
                if not key:
                    handles_missing += 1
                sources_here.add(c["source"])
                pairs[(c["source"], key)].append((sense["canonicalKey"], c))
        multi_source = len(sources_here) >= 2
        if multi_source:
            stats["multiSourceEntries"] += 1

        entry_hit = False
        for (src, sid), items in pairs.items():
            if len(items) < 2:
                continue
            divergent = {}
            for f in FIELDS:
                vals = {norm(c.get(f)) for _sk, c in items if norm(c.get(f))}
                if len(vals) > 1:
                    divergent[f] = sorted(vals)
            if not divergent:
                continue
            entry_hit = True
            stats["collidingContributions"] += len(items)
            for f in divergent:
                field_divergence[f] += 1
            collisions.append(
                {
                    "entryId": e["entryId"],
                    "claimId": sid,
                    "contributions": len(items),
                    "senses": [sk for sk, _c in items],
                    "multiSourceEntry": multi_source,
                    "divergentFields": {
                        f: [v[:160] for v in vals] for f, vals in divergent.items()
                    },
                }
            )
        if entry_hit:
            stats["entriesWithCollision"] += 1
            if multi_source:
                stats["multiSourceEntriesWithCollision"] += 1

    summary = {
        "handle": args.handle,
        "unified": str(args.unified),
        "contributionsSeen": contributions_seen,
        "handlesMissing": handles_missing,
        "stats": stats,
        "collidingClaimIds": len(collisions),
        "divergentFieldHistogram": dict(
            sorted(field_divergence.items(), key=lambda kv: -kv[1])
        ),
        "jlptCollisions": sum(1 for c in collisions if "jlpt" in c["divergentFields"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary": summary, "collisions": collisions}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    shown = 0
    for c in collisions:
        if "jlpt" in c["divergentFields"] and shown < 5:
            print(c["entryId"], c["claimId"], c["senses"], c["divergentFields"]["jlpt"])
            shown += 1

    # UGD-16: fail closed so this can be a Makefile gate. With `--handle rowUid`
    # every claim must name a unique row: the UGD-11d-C acceptance gate is
    # collidingClaimIds == 0. `--handle sourceId` is the CONTROL -- it must keep
    # reporting the filed collisions, because source_id is deliberately still the
    # producer's non-unique headword, so a zero there would mean the probe stopped
    # measuring rather than that the defect was fixed.
    colliding = summary["collidingClaimIds"]
    if args.handle == "rowUid":
        if colliding:
            print(f"\nFAIL: {colliding} colliding claim id(s) under the rowUid handle")
            return 1
        if summary.get("handlesMissing"):
            print(f"\nFAIL: {summary['handlesMissing']} contribution(s) carry no rowUid")
            return 1
        print("\nOK: every claim names a unique row (collidingClaimIds == 0)")
        return 0
    if not colliding:
        print(
            "\nFAIL: the sourceId control reports 0 collisions. source_id is the "
            "producer's non-unique headword, so this means the probe stopped "
            "measuring, not that the defect was fixed."
        )
        return 1
    print(f"\nOK: control reproduces {colliding} colliding claim id(s) under sourceId")
    return 0


if __name__ == "__main__":
    sys.exit(main())
