import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")
from bugd.keymap import is_declared_alias, substance_hash
from bugd.unify import KIND_POINT, KIND_REDIRECT, load_extracted, load_keymap, read_unified

rows, labels = load_extracted(pathlib.Path("data/extracted"))
keymap = load_keymap(pathlib.Path("data/merge/keymap.json"))
entries = read_unified(pathlib.Path("data/merge/unified.jsonl"))
stats = json.load(open("data/merge/unified.stats.json"))

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'OK ' if ok else 'FAIL'}  {label}: got {got}, want {want}")
    if not ok:
        fail.append(label)


# --- example conservation: every example is either kept or accounted for ---
matched_rows = []
seen = set()
dup_rows = 0
for source, record in rows:
    key = keymap.key_for(source, record)
    if key is None:
        continue
    ident = (source, str(record.get("source_id") or ""), substance_hash(record))
    if ident in seen:
        dup_rows += 1
        continue
    seen.add(ident)
    matched_rows.append((source, record))

check("collapsed duplicate rows", dup_rows, stats["corpus"]["collapsedDuplicateRows"])
check("contributions == unique assigned rows", len(matched_rows), stats["unified"]["contributions"])

pre = sum(len(r.get("examples") or []) for _, r in matched_rows)
post = stats["examples"]["total"]
removed = stats["examples"]["sameSourceDuplicatesRemoved"]
check("examples conserved (pre == post + removed)", pre, post + removed)

kept = sum(len(c.examples) for e in entries if e.kind == KIND_POINT for c in e.contributions)
check("examples in artifact == stats total", kept, post)

declared = sum(c.duplicate_examples_removed for e in entries for c in e.contributions)
check("per-contribution removals sum to stats", declared, removed)

# --- no contribution lost ---
artifact_ids = Counter(
    (c.source, c.source_id, c.canonical_key)
    for e in entries
    if e.kind == KIND_POINT
    for c in e.contributions
)
check("every assigned row appears exactly once", len(artifact_ids), len(matched_rows))
check("no contribution duplicated", max(artifact_ids.values()), 1)

# --- findability: every written form in the corpus is reachable ---
corpus_forms = {str(r["expression"]) for _, r in rows}
reachable = {e.expression for e in entries}
missing = sorted(corpus_forms - reachable)
unresolved = {u["expression"] for u in stats["redirects"]["unresolved"]}
check("unreachable forms == reported unresolved", set(missing), unresolved)
# Was 5 before the Bunpro source existed. Bunpro supplies それまでだ as a real N1
# point (source_id 943, 11 examples), which resolves the redirect donna_toki had
# declared as `aliasOf: それまでだ` and that previously dangled because no source
# carried that headword. Attributed by running keymap+merge with and without
# data/extracted/bunpro.json: the only difference is それまでだ leaving this set,
# and nothing new enters it.
check("unresolved count", len(unresolved), 4)

# --- every redirect points somewhere real ---
heads = {e.expression for e in entries if e.kind == KIND_POINT}
bad = [e.expression for e in entries if e.kind == KIND_REDIRECT and not set(e.redirect_targets) <= heads]
check("every redirect target is a point entry", bad, [])
check("every redirect has >=1 target", [e.expression for e in entries if e.kind == KIND_REDIRECT and not e.redirect_targets], [])

# --- sense ordering is natural, not lexicographic ---
misordered = []
for e in entries:
    if len(e.senses) < 10:
        continue
    ordinals = []
    for s in e.senses:
        d = s.disambiguator
        if d.startswith("sense") and d[5:].isdigit():
            ordinals.append(int(d[5:]))
    if ordinals != sorted(ordinals):
        misordered.append(e.expression)
check("no entry has misordered ordinal senses", misordered, [])

# --- JLPT conflicts preserved, never reconciled ---
conf = [e for e in entries if len(e.jlpt_levels) > 1]
check("conflicting-level entries reported", len(conf), stats["jlpt"]["entriesWithConflictingLevels"])
sample = next(e for e in conf if e.expression == "に反して") if any(e.expression == "に反して" for e in conf) else conf[0]
per_source_levels = sorted({(c.source, c.jlpt) for c in sample.contributions if c.jlpt})
print(f"      e.g. {sample.expression}: entry levels {sample.jlpt_levels}, per source {per_source_levels}")
check("conflicting entry keeps >1 distinct source level", len({l for _, l in per_source_levels}) > 1, True)

print()
print("FAILURES:", fail if fail else "none")
sys.exit(1 if fail else 0)
