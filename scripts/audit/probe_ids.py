import json
import collections
from pathlib import Path

for p in sorted(Path("evidence/extracted").glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    c = collections.Counter(r["source_id"] for r in d["points"])
    dupes = {k: v for k, v in c.items() if v > 1}
    print(
        d["source"],
        "rows",
        len(d["points"]),
        "distinct source_id",
        len(c),
        "ids with >1 row",
        len(dupes),
        "max",
        max(c.values()),
    )
    if dupes:
        print("  e.g.", list(dupes.items())[:5])
