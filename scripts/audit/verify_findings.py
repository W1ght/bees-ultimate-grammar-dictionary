"""Fail-closed verification of every LLM finding against the frozen dataset.

A finding is ACCEPTED only if, for BOTH sides:
  - the claimId exists in that entry's dossier;
  - the named field exists on that claim;
  - the quote is an exact contiguous substring of that field's verbatim text
    (or of one of the claim's example sentences when field == "example").

Anything else is REJECTED with a machine-readable reason. Rejection is not a
softer accept: a rejected finding is excluded from the must-fix list and counted
as a hallucination/citation defect of the audit run.

Also enforces completeness: every dossier must have a status=="ok" result.
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DOSSIERS = HERE / "dossiers"
FINDINGS = HERE / "evidence" / "llm_findings"

VALID_CLASS = {"meaning", "jlpt", "register", "formation", "example"}
VALID_FIELD = {"jlpt", "meaning", "structure", "explanation", "notes", "example"}
VALID_CONF = {"high", "low"}


def index_dossier(d):
    """claimId -> {field: text, '__examples__': [ja...]}"""
    idx = {}
    for sense in d["senses"]:
        for src in sense["sources"]:
            slot = idx.setdefault(src["claimId"], {"__examples__": [], "__senses__": set()})
            slot["__senses__"].add(sense["canonicalKey"])
            for f, v in src["claims"].items():
                # a claimId can appear in several senses; keep all texts per field
                slot.setdefault(f, [])
                slot[f].append(v)
            for ex in src["examples"]:
                slot["__examples__"].append(ex["ja"])
                if ex.get("en"):
                    slot["__examples__"].append(ex["en"])
    return idx


def loosen(s):
    """Only whitespace/NFKC tolerance -- never content tolerance."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def quote_ok(quote, texts):
    if not quote:
        return False, "empty_quote"
    for t in texts:
        if quote in t:
            return True, "exact"
    lq = loosen(quote)
    for t in texts:
        if lq and lq in loosen(t):
            return True, "whitespace_normalized"
    return False, "quote_not_in_source_text"


def verify_side(side, idx):
    if not isinstance(side, dict):
        return False, "malformed_side", None
    cid = side.get("claimId")
    field = side.get("field")
    quote = side.get("quote") or ""
    if cid not in idx:
        return False, f"unknown_claimId:{cid}", None
    if field not in VALID_FIELD:
        return False, f"invalid_field:{field}", None
    slot = idx[cid]
    if field == "example":
        texts = slot["__examples__"]
    else:
        texts = slot.get(field) or []
        if not texts:
            # the model may quote an example while naming a text field, or vice
            # versa; try every text this claim actually carries before rejecting
            alt = [t for k, v in slot.items() if k not in ("__examples__", "__senses__") for t in v]
            ok, how = quote_ok(quote, alt + slot["__examples__"])
            if ok:
                return False, f"field_mismatch_but_quote_present:{field}", how
            return False, f"field_absent_on_claim:{field}", None
    ok, how = quote_ok(quote, texts)
    if ok:
        return True, how, how
    # quote may live on another field of the same claim
    alt = [t for k, v in slot.items() if k not in ("__examples__", "__senses__") for t in v]
    ok2, how2 = quote_ok(quote, alt + slot["__examples__"])
    if ok2:
        return False, f"field_mismatch_but_quote_present:{field}", how2
    return False, "quote_not_in_source_text", None


def main():
    dossier_files = sorted(DOSSIERS.glob("*.json"))
    accepted, rejected = [], []
    unaudited = []
    status_hist = Counter()
    class_hist = Counter()
    reject_hist = Counter()

    for dp in dossier_files:
        fp = FINDINGS / dp.name
        if not fp.exists():
            unaudited.append({"file": dp.name, "reason": "no_result"})
            continue
        res = json.loads(fp.read_text(encoding="utf-8"))
        status_hist[res.get("status")] += 1
        if res.get("status") != "ok":
            unaudited.append(
                {"file": dp.name, "entryId": res.get("entryId"), "reason": res.get("status")}
            )
            continue
        d = json.loads(dp.read_text(encoding="utf-8"))
        idx = index_dossier(d)
        for k, f in enumerate(res.get("findings", [])):
            base = {
                "file": dp.name,
                "entryId": d["entryId"],
                "expression": d["expression"],
                "n": k,
                "class": f.get("class"),
                "confidence": f.get("confidence"),
                "sense": f.get("sense") or "",
                "sideA": f.get("sideA"),
                "sideB": f.get("sideB"),
                "why": f.get("why"),
                "proposedTrust": f.get("proposedTrust") or "",
            }
            problems = []
            if f.get("class") not in VALID_CLASS:
                problems.append(f"invalid_class:{f.get('class')}")
            if f.get("confidence") not in VALID_CONF:
                problems.append(f"invalid_confidence:{f.get('confidence')}")
            okA, whyA, howA = verify_side(f.get("sideA"), idx)
            okB, whyB, howB = verify_side(f.get("sideB"), idx)
            if not okA:
                problems.append(f"sideA:{whyA}")
            if not okB:
                problems.append(f"sideB:{whyB}")
            if (
                okA
                and okB
                and f["sideA"].get("claimId") == f["sideB"].get("claimId")
                and f.get("class") != "example"
            ):
                problems.append("same_claim_both_sides")
            if problems:
                base["rejectReasons"] = problems
                rejected.append(base)
                for p in problems:
                    reject_hist[p.split(":")[0] + ":" + p.split(":")[1] if ":" in p else p] += 1
            else:
                base["verifiedAs"] = {"sideA": howA, "sideB": howB}
                accepted.append(base)
                class_hist[(f["class"], f["confidence"])] += 1

    summary = {
        "dossiers": len(dossier_files),
        "resultStatus": dict(status_hist),
        "unaudited": len(unaudited),
        "findingsAccepted": len(accepted),
        "findingsRejected": len(rejected),
        "acceptedByClassConfidence": {f"{c}/{k}": v for (c, k), v in sorted(class_hist.items())},
        "rejectReasonHistogram": dict(reject_hist.most_common()),
        "entriesWithAcceptedFindings": len({a["entryId"] for a in accepted}),
        "completenessGate": "PASS" if not unaudited else "FAIL",
    }
    (HERE / "evidence" / "verified_findings.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "accepted": accepted,
                "rejected": rejected,
                "unaudited": unaudited,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if unaudited:
        print("\nUNAUDITED (first 10):", json.dumps(unaudited[:10], ensure_ascii=False))


if __name__ == "__main__":
    main()
