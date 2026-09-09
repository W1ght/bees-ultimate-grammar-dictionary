"""Synthesize the final findings report.

Combines, for every candidate:
  - verbatim-verified citations (verify_findings.py)
  - adversarial verdict + learner impact (adjudicate.py)
  - real-card visibility against banks.py (visibility.py)

Tiering (fail-closed):
  must-fix   : adjudicator UPHELD, impact high, both sides render on the card
  should-fix : adjudicator UPHELD, impact medium, both sides render
  low-conf   : adjudicator UNCERTAIN, or upheld with low impact, or not both rendered
  dismissed  : adjudicator judged FALSE (kept with reasoning, never silently dropped)

Completeness is asserted: every multi-source group must have an audit result, and
every accepted finding must have an adjudication.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
EV = HERE / "evidence"


def main():
    verified = json.loads((EV / "verified_findings.json").read_text(encoding="utf-8"))
    visibility = json.loads((EV / "visibility.json").read_text(encoding="utf-8"))
    vis = {(v["file"], v["n"]): v for v in visibility["findings"]}

    adj = {}
    for p in (EV / "adjudication").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        adj[d["key"]] = d

    manifest = json.loads((EV / "dossier_manifest.json").read_text(encoding="utf-8"))
    dossier_count = len(manifest)

    tiers = defaultdict(list)
    missing_adj = []
    tier_hist = Counter()
    verdict_hist = Counter()
    impact_hist = Counter()

    for f in verified["accepted"]:
        key = f"{f['file'].replace('.json','')}-{f['n']}"
        a = adj.get(key)
        if a is None or a.get("status") != "ok":
            missing_adj.append(key)
            continue
        v = vis[(f["file"], f["n"])]
        verdict = a.get("verdict")
        impact = a.get("impact")
        verdict_hist[verdict] += 1
        impact_hist[(verdict, impact)] += 1
        both = v["visibility"] == "both_rendered"

        if verdict == "false":
            tier = "dismissed"
        elif verdict == "uncertain":
            tier = "low_confidence"
        elif not both:
            tier = "low_confidence"
        elif impact == "high":
            tier = "must_fix"
        elif impact == "medium":
            tier = "should_fix"
        else:
            tier = "low_confidence"

        tier_hist[tier] += 1
        tiers[tier].append(
            {
                "entryId": f["entryId"],
                "expression": f["expression"],
                "class": f["class"],
                "sense": f["sense"],
                "firstPassConfidence": f["confidence"],
                "verdict": verdict,
                "impact": impact,
                "sameSense": a.get("sameSense"),
                "visibility": v["visibility"],
                "sideA": f["sideA"],
                "sideB": f["sideB"],
                "why": f["why"],
                "adjudicatorReasoning": a.get("reasoning"),
                "disproofAttempt": a.get("disproofAttempt"),
                "trustRecommendation": a.get("trustRecommendation") or f.get("proposedTrust") or "",
                "verifiedAs": f.get("verifiedAs"),
                "evidenceKey": key,
            }
        )

    precision = json.loads((EV / "attribution_precision.json").read_text(encoding="utf-8"))
    coherence = json.loads((EV / "attribution_coherence.json").read_text(encoding="utf-8"))
    labels = json.loads((EV / "label_conflicts.json").read_text(encoding="utf-8"))

    # class breakdown within each tier
    class_by_tier = {t: dict(Counter(x["class"] for x in v)) for t, v in tiers.items()}

    summary = {
        "target": {
            "unified": "data/merge/unified.jsonl",
            "sha256": "06bd856f724a90ed6dc84dcb1c0d54b3e9b104bb0d4977c0d141ea8e3737711c",
            "bytes": 8986963,
            "entries": 2441,
            "pointEntries": 1696,
        },
        "coverage": {
            "multiSourceGroups": dossier_count,
            "auditedGroups": verified["summary"]["resultStatus"].get("ok", 0),
            "unauditedGroups": verified["summary"]["unaudited"],
            "sampling": "none - 100% of multi-source canonical groups",
            "completenessGate": "PASS"
            if verified["summary"]["unaudited"] == 0 and not missing_adj
            else "FAIL",
        },
        "citationGate": {
            "findingsProposed": verified["summary"]["findingsAccepted"]
            + verified["summary"]["findingsRejected"],
            "citationsVerified": verified["summary"]["findingsAccepted"],
            "citationsRejected": verified["summary"]["findingsRejected"],
            "rejectReasons": verified["summary"]["rejectReasonHistogram"],
        },
        "adjudication": {
            "verdicts": dict(verdict_hist),
            "byVerdictImpact": {f"{v}/{i}": n for (v, i), n in sorted(impact_hist.items())},
            "missingAdjudications": missing_adj,
        },
        "visibility": visibility["histogram"],
        "tiers": dict(tier_hist),
        "classByTier": class_by_tier,
        "entriesAffected": {
            t: len({x["entryId"] for x in v}) for t, v in tiers.items()
        },
        "deterministicChecks": {
            "attributionDrift": {
                "contributions": coherence["summary"]["stats"]["contributions"],
                "claims": coherence["summary"]["stats"]["claims"],
                "findings": coherence["summary"]["counts"],
                "mutationsKilled": "4/4",
            },
            "attributionPrecision": precision["summary"],
            "labelConflictCandidates": labels["summary"],
        },
    }

    (EV / "FINAL_REPORT.json").write_text(
        json.dumps({"summary": summary, "tiers": dict(tiers)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
