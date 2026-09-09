"""Emit the human-readable findings report from FINAL_REPORT.json.

Every entry carries both sides verbatim so a maintainer never has to trust the
audit; each item names its evidence key so the raw LLM response and adjudication
can be pulled from evidence/llm_findings/ and evidence/adjudication/.
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
EV = HERE / "evidence"


def block(x, i):
    lines = [
        f"### {i}. {x['entryId']}  [{x['class']}]"
        + (f"  sense={x['sense']}" if x["sense"] else ""),
        "",
        f"- side A `{x['sideA']['claimId']}` ({x['sideA']['field']}):",
        f"  > {x['sideA']['quote'].strip()}",
        f"- side B `{x['sideB']['claimId']}` ({x['sideB']['field']}):",
        f"  > {x['sideB']['quote'].strip()}",
        "",
        f"- conflict: {x['why'].strip()}",
        f"- adjudicated: {(x['adjudicatorReasoning'] or '').strip()}",
    ]
    if x.get("disproofAttempt"):
        lines.append(f"- strongest counter-argument: {x['disproofAttempt'].strip()}")
    if x.get("trustRecommendation"):
        lines.append(f"- suggested resolution: {x['trustRecommendation'].strip()}")
    lines += [
        f"- card visibility: {x['visibility']}; citations verified: "
        f"A={x['verifiedAs']['sideA']}, B={x['verifiedAs']['sideB']}",
        f"- evidence: `evidence/llm_findings/{x['evidenceKey'].split('-')[0]}.json` "
        f"+ `evidence/adjudication/{x['evidenceKey']}.json`",
        "",
    ]
    return "\n".join(lines)


def main():
    rep = json.loads((EV / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    s = rep["summary"]
    t = rep["tiers"]

    out = []
    out.append("# UGD-11d - Cross-source contradiction & consistency audit\n")
    out.append(f"Target: `{s['target']['unified']}` sha256 `{s['target']['sha256']}` "
               f"({s['target']['bytes']:,} B, {s['target']['entries']:,} entries, "
               f"{s['target']['pointEntries']:,} grammar points)\n")
    out.append("## Coverage\n")
    out.append(f"- multi-source canonical groups: **{s['coverage']['multiSourceGroups']}** "
               f"(of {s['target']['pointEntries']:,} grammar points)")
    out.append(f"- audited: **{s['coverage']['auditedGroups']}** / "
               f"{s['coverage']['multiSourceGroups']}; unaudited: "
               f"{s['coverage']['unauditedGroups']}")
    out.append(f"- sampling: {s['coverage']['sampling']}")
    out.append(f"- completeness gate: **{s['coverage']['completenessGate']}**\n")

    out.append("## Fail-closed citation gate\n")
    cg = s["citationGate"]
    out.append(f"- findings proposed: {cg['findingsProposed']}")
    out.append(f"- citations verified verbatim against the frozen dataset: "
               f"**{cg['citationsVerified']}**")
    out.append(f"- rejected: **{cg['citationsRejected']}** -> {cg['rejectReasons']}\n")

    out.append("## Adversarial adjudication\n")
    out.append(f"- verdicts: {s['adjudication']['verdicts']}")
    out.append(f"- by verdict/impact: {s['adjudication']['byVerdictImpact']}\n")

    out.append("## Result tiers\n")
    for k in ("must_fix", "should_fix", "low_confidence", "dismissed"):
        out.append(f"- {k}: **{s['tiers'].get(k, 0)}** findings across "
                   f"{s['entriesAffected'].get(k, 0)} entries; "
                   f"classes {s['classByTier'].get(k, {})}")
    out.append("")

    out.append("## MUST-FIX (adjudicated genuine, high learner impact, both sides render)\n")
    for i, x in enumerate(t["must_fix"], 1):
        out.append(block(x, i))

    out.append("## LOW-CONFIDENCE / human glance\n")
    for i, x in enumerate(t["low_confidence"], 1):
        out.append(block(x, i))

    out.append("## SHOULD-FIX summary (medium impact)\n")
    cls = Counter(x["class"] for x in t["should_fix"])
    out.append(f"{len(t['should_fix'])} findings, classes {dict(cls)}. "
               "Full detail in `evidence/FINAL_REPORT.json` under `tiers.should_fix`.\n")
    out.append("| entry | class | side A | side B |")
    out.append("|---|---|---|---|")
    for x in t["should_fix"]:
        qa = x["sideA"]["quote"].replace("\n", " ")[:40]
        qb = x["sideB"]["quote"].replace("\n", " ")[:40]
        out.append(
            f"| {x['entryId']} | {x['class']} | `{x['sideA']['claimId']}` {qa} "
            f"| `{x['sideB']['claimId']}` {qb} |"
        )
    out.append("")

    out.append("## Deterministic checks\n")
    dc = s["deterministicChecks"]
    out.append("### Attribution drift (scope item 5)\n")
    out.append(f"- {dc['attributionDrift']['contributions']:,} contributions, "
               f"{dc['attributionDrift']['claims']:,} claim strings")
    out.append(f"- findings: {dc['attributionDrift']['findings'] or 'NONE'}")
    out.append(f"- probe mutations killed: {dc['attributionDrift']['mutationsKilled']}\n")
    out.append("### Attribution precision (ambiguous claim handles)\n")
    ap = dc["attributionPrecision"]
    out.append(f"- {ap['collidingClaimIds']} `source#sourceId` handles name 2+ different "
               f"source records inside one entry ({ap['stats']['collidingContributions']} "
               f"contributions, {ap['stats']['multiSourceEntriesWithCollision']} multi-source "
               f"entries)")
    out.append(f"- divergent fields: {ap['divergentFieldHistogram']}\n")

    text = "\n".join(out)
    (EV / "FINDINGS.md").write_text(text, encoding="utf-8")
    print(f"wrote {EV / 'FINDINGS.md'} ({len(text):,} chars)")


if __name__ == "__main__":
    main()
