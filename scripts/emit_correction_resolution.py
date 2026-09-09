"""Emit the per-item resolution report for UGD-11c-D from the corrections manifest.

Cross-checks every one of the 187 confirmed findings (clusters D + F) against the
shipped corrections and records, per item, the disposition applied. Writes
data/corrections/content/reports/ugd-11c-d.resolution.json.
"""

from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
CLUSTERS = REPO / "data" / "corrections" / "content" / "evidence"
MANIFEST = REPO / "data" / "corrections" / "content" / "ugd-11c-d.json"
OUT = REPO / "data" / "corrections" / "content" / "reports" / "ugd-11c-d.resolution.json"


def main() -> int:
    D = json.loads((CLUSTERS / "cluster_D.json").read_text())["findings"]
    F = json.loads((CLUSTERS / "cluster_F.json").read_text())["findings"]
    corr = json.loads(MANIFEST.read_text())["corrections"]

    # Index corrections by (source, source_id, verbatim) — for the one item split
    # across two surfaces the two records share (source, source_id) but differ by
    # field, so also index by (source, source_id, field, verbatim).
    by_key = {}
    for c in corr:
        by_key.setdefault((c["source"], c["source_id"]), []).append(c)

    resolved = []
    unresolved = []
    for cluster_name, findings in (("D", D), ("F", F)):
        for f in findings:
            cands = by_key.get((f["source"], f["source_id"]), [])
            # a finding is resolved if some correction on the same (source,
            # source_id) carries its verbatim, or a replace_span whose verbatim
            # is a substring of the finding's verbatim (typo inside a sentence)
            match = None
            for c in cands:
                if c["verbatim"] == f["verbatim"]:
                    match = c
                    break
                if c["disposition"] == "replace_span" and c["verbatim"] in f["verbatim"]:
                    match = c
                    break
            if match is None:
                unresolved.append({"source": f["source"], "source_id": f["source_id"],
                                   "field": f["field"], "verbatim": f["verbatim"]})
                continue
            resolved.append({
                "cluster": cluster_name,
                "source": f["source"],
                "source_id": f["source_id"],
                "sense_index": f["sense_index"],
                "field": match["field"],
                "verbatim": f["verbatim"],
                "disposition": match["disposition"],
                "issue": f["issue"],
                "second_opinion": f.get("second_opinion"),
                "justification": match.get("justification", ""),
            })

    from collections import Counter
    payload = {
        "card": "UGD-11c-D",
        "findingsTotal": len(D) + len(F),
        "resolvedTotal": len(resolved),
        "unresolvedTotal": len(unresolved),
        "byDisposition": dict(Counter(r["disposition"] for r in resolved)),
        "byCluster": dict(Counter(r["cluster"] for r in resolved)),
        "unresolved": unresolved,
        "items": resolved,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k not in ("items", "unresolved")},
                     ensure_ascii=False, indent=1))
    print("unresolved:", unresolved)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
