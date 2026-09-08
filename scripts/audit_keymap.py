"""Audit data/merge/keymap.json against the safety properties it claims.

Every check is a property that, if violated, means a genuinely different grammar
point was silently merged. These are the assertions a reviewer cares about.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, "src")
from bugd.keymap import substance_hash  # noqa: E402
from bugd.polarity import polarity  # noqa: E402

payload = json.loads(pathlib.Path("data/merge/keymap.json").read_text(encoding="utf-8"))
points = {p["canonicalKey"]: p for p in payload["points"]}
assignments = payload["assignments"]
report = payload["report"]
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# 1. Every substantive row is assigned exactly once, and identity is total.
ident = collections.Counter((a["source"], a["sourceId"], a["substanceHash"]) for a in assignments)
check(
    "assignment identity is unique",
    all(v == 1 for v in ident.values()),
    f"{len(assignments)} assignments / {len(ident)} identities",
)
check(
    "assignments match substantive row count",
    len(assignments) == report["corpus"]["substantiveRows"],
    f"{len(assignments)} vs {report['corpus']['substantiveRows']}",
)

# 2. Every assigned key exists as a point; every point has >=1 contributor.
missing = {a["canonicalKey"] for a in assignments} - set(points)
check("every assigned key has a point", not missing, f"missing={sorted(missing)[:3]}")
check(
    "every point has contributors",
    all(p["contributors"] for p in points.values()),
)
contrib_total = sum(len(p["contributors"]) for p in points.values())
check(
    "contributors account for every assignment",
    contrib_total == len(assignments),
    f"{contrib_total} vs {len(assignments)}",
)

# 3. NO POLARITY FLIP inside any canonical point. This is the killer check:
#    a known affirmative and its known negation must never share a point. Forms
#    whose tail is unrecognized ("none") abstain, matching polarity's contract.
mixed = []
for key, p in points.items():
    pols = {polarity(f) for f in p["lookupForms"]}
    if {"pos", "neg"} <= pols:
        mixed.append((key, p["lookupForms"]))
check("no polarity flip merged into one point", not mixed, f"{len(mixed)} violations {mixed[:3]}")

# 4. No point mixes partition axes (classical must never join modern).
axis_keys = [k for k, p in points.items() if p["axes"]["era"] == "classical"]
scoped = [k for k in axis_keys if not k.startswith(("standard/classical:", "dialect/classical:"))]
check("classical points are axis-scoped in the key", not scoped, f"{len(axis_keys)} classical")

# 5. One source may contribute two rows to one point ONLY via an accepted Tier B
#    variant pair (`につれ`/`につれて`). Without a Tier B merge it would mean a
#    homograph fan was collapsed, which is a real defect.
merged_keys = {m["canonicalKey"] for m in report["tierB"]["pointsMerged"]}
fanned = []
for key, p in points.items():
    per = collections.Counter(c["source"] for c in p["contributors"])
    if any(v > 1 for v in per.values()) and key not in merged_keys:
        fanned.append((key, dict(per)))
check(
    "no homograph fan collapsed (duplicate source only via Tier B)",
    not fanned,
    f"{len(fanned)} violations {fanned[:3]}",
)
dup_via_b = sum(
    1
    for key, p in points.items()
    if key in merged_keys
    and any(v > 1 for v in collections.Counter(c["source"] for c in p["contributors"]).values())
)
print(f"      (informational: {dup_via_b} points hold two rows of one source via a Tier B pair)")

# 6. Known-hazard pairs must be in DIFFERENT points.
HAZARDS = [
    ("ないことはある", "ないことはない"),
    ("と言ったらある", "といったらない"),
    ("と言えなくもある", "と言えなくもない"),
    ("限りだ", "です"),
    ("それなりに", "の"),
]
form_to_keys = collections.defaultdict(set)
for key, p in points.items():
    for form in p["lookupForms"]:
        form_to_keys[form].add(key)
bad = []
for left, right in HAZARDS:
    shared = form_to_keys.get(left, set()) & form_to_keys.get(right, set())
    if shared:
        bad.append((left, right, sorted(shared)))
check("hazard pairs stay in different points", not bad, f"{bad}")

# 7. Known-good orthographic pairs must be in the SAME point.
GOOD = [
    ("今更", "いまさら"),
    ("一旦", "いったん"),
    ("や否や", "やいなや"),
    ("を踏まえて", "を踏まえ"),
    ("に即して", "に則して"),
]
notfolded = []
for left, right in GOOD:
    if not (form_to_keys.get(left, set()) & form_to_keys.get(right, set())):
        notfolded.append((left, right, sorted(form_to_keys.get(left, ())), sorted(form_to_keys.get(right, ()))))
check("known orthographic pairs are folded", not notfolded, f"{notfolded}")

# 8. Tier B merges cannot cascade: no point may hold more than 2 Tier B keys.
merges = report["tierB"]["pointsMerged"]
absorbed = collections.Counter(m["canonicalKey"] for m in merges)
check(
    "no Tier B point absorbed more than one other",
    all(v == 1 for v in absorbed.values()),
    f"{len(merges)} merges, max absorbed={max(absorbed.values(), default=0)}",
)
still = [m["absorbedKey"] for m in merges if m["absorbedKey"] in points]
check("absorbed keys no longer exist as points", not still, f"{still[:3]}")

# 9. Determinism: rebuild and compare bytes.
sys.path.insert(0, "src")
from bugd.jsonio import dump_json  # noqa: E402
from bugd.keymap import build_keymap  # noqa: E402

again = build_keymap(pathlib.Path("data/extracted"))
check(
    "rebuild is byte-identical",
    dump_json(again) == dump_json(payload),
)

# 10. Alias rows never became contributors. Compared on FULL identity: a producer
#     may ship the same source_id as both a real point and a synthetic twin, and
#     only the identity-exact row is a genuine leak.
alias_ids = set()
for p in pathlib.Path("data/extracted").glob("*.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    for x in d["points"]:
        pr = x["provenance"]
        if pr.get("aliasOf") or pr.get("syntheticLookupForm") or pr.get("entryShape") == "alias-redirect":
            alias_ids.add((d["source"], x["source_id"], substance_hash(x)))
substantive_ids = set()
for p in pathlib.Path("data/extracted").glob("*.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    for x in d["points"]:
        pr = x["provenance"]
        if not (pr.get("aliasOf") or pr.get("syntheticLookupForm") or pr.get("entryShape") == "alias-redirect"):
            substantive_ids.add((d["source"], x["source_id"], substance_hash(x)))
leaked = [
    (c["source"], c["sourceId"])
    for p in points.values()
    for c in p["contributors"]
    if (c["source"], c["sourceId"], c["substanceHash"]) in alias_ids - substantive_ids
]
check("no declared alias row is a contributor", not leaked, f"{len(leaked)} leaked {leaked[:3]}")

print()
print(f"corpus: {report['corpus']}")
print(f"points: {report['canonicalPoints']}")
print(f"multi-source points: {sum(1 for p in points.values() if p['sourceCount'] > 1)}")
print(f"largest point: {max((len(p['contributors']), k) for k, p in points.items())}")
print()
print("FAILURES:", failures or "none")
raise SystemExit(1 if failures else 0)
