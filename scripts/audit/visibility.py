"""Which conflicts actually reach the rendered card?

banks.py renders one <details> per SOURCE with at most SENSES_PER_SOURCE=4
senses inside, and the compact block shows ONE headline meaning plus a JLPT
badge. A contradiction between two claims that both render is user-visible; a
contradiction involving a truncated sense is a dataset-only issue.

This maps every accepted finding onto the real generator so severity is measured,
not assumed.
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
BUGD = Path(
    "/home/skerraut/.hermes/kanban/boards/bees-ultimate-grammar-dictionary/"
    "workspaces/t_7122562e/wt"
)
sys.path.insert(0, str(BUGD / "src"))

from bugd import banks  # noqa: E402

SENSES_PER_SOURCE = banks.SENSES_PER_SOURCE
UNIFIED = HERE / "evidence" / "unified.frozen.jsonl"


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def main():
    entries = {}
    for line in UNIFIED.open(encoding="utf-8"):
        e = json.loads(line)
        if e["kind"] == "point":
            entries[e["entryId"]] = e

    verified = json.loads(
        (HERE / "evidence" / "verified_findings.json").read_text(encoding="utf-8")
    )

    out = []
    hist = Counter()
    for f in verified["accepted"]:
        e = entries[f["entryId"]]
        # replicate the generator's grouping: source label -> ordered contributions
        grouped = defaultdict(list)
        order = []
        for sense in e["senses"]:
            for c in sense["contributions"]:
                key = c["sourceLabel"]
                grouped[key].append((sense["canonicalKey"], c))
                order.append((key, sense["canonicalKey"], c))
        rendered_positions = {}
        for label, items in grouped.items():
            for i, (sk, c) in enumerate(items):
                rendered_positions[(label, sk, c["sourceId"], id(c))] = i

        def side_visible(side):
            cid = side["claimId"]
            src, sid = cid.split("#", 1)
            positions = []
            for label, items in grouped.items():
                for i, (sk, c) in enumerate(items):
                    if c["source"] == src and c["sourceId"] == sid:
                        # does this contribution carry the quoted text?
                        q = norm(side.get("quote"))
                        texts = [norm(c.get(k)) for k in
                                 ("jlpt", "meaning", "structure", "explanation", "notes")]
                        texts += [norm(x.get("japanese")) for x in c.get("examples", [])]
                        texts += [norm(x.get("english")) for x in c.get("examples", [])]
                        if q and any(q in t for t in texts if t):
                            positions.append(i)
            if not positions:
                return None, positions
            return min(positions) < SENSES_PER_SOURCE, positions

        visA, posA = side_visible(f["sideA"])
        visB, posB = side_visible(f["sideB"])
        if visA is None or visB is None:
            state = "unlocatable"
        elif visA and visB:
            state = "both_rendered"
        elif visA or visB:
            state = "one_truncated"
        else:
            state = "both_truncated"
        hist[state] += 1
        out.append(
            {
                "entryId": f["entryId"],
                "class": f["class"],
                "confidence": f["confidence"],
                "file": f["file"],
                "n": f["n"],
                "visibility": state,
                "sideAPositions": posA,
                "sideBPositions": posB,
            }
        )

    (HERE / "evidence" / "visibility.json").write_text(
        json.dumps(
            {"sensesPerSource": SENSES_PER_SOURCE, "histogram": dict(hist), "findings": out},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"sensesPerSource": SENSES_PER_SOURCE, "histogram": dict(hist)}, indent=1))
    by_class = defaultdict(Counter)
    for o in out:
        by_class[o["class"]][o["visibility"]] += 1
    print(json.dumps({k: dict(v) for k, v in by_class.items()}, indent=1))


if __name__ == "__main__":
    main()
