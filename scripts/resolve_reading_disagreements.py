"""Acceptance #3: resolve or justify every cross-source reading disagreement.

Reads data/merge/reading_audit.json (produced by audit_readings.py against the
corrected corpus) and classifies each expression whose sources disagree on the
reading into a resolution category, writing a human-readable justification per
row to data/merge/reading_disagreements_resolved.json.

The policy: the unified dataset carries readings PER CONTRIBUTION and never
reconciles them (UGD-08), because a genuine multi-reading expression (甲斐
かい/がい, 得る うる/える) is a true statement about each source. A disagreement
is therefore only a defect if one of the readings is not a plausible rendering
of the expression — and the plausibility gate already fails closed on those.
This pass documents that every surviving disagreement is benign, with the reason.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.readings import has_kanji, is_plausible_reading, normalize_kana  # noqa: E402

AUDIT = pathlib.Path("data/merge/reading_audit.json")
OUT = pathlib.Path("data/merge/reading_disagreements_resolved.json")


def classify(expression: str, readings: dict[str, list[str]]) -> tuple[str, str]:
    """Return (category, justification) for one disagreement."""
    variants = list(readings)
    norm = {v: normalize_kana(v) for v in variants}

    # A) One source leaves reading == expression (carried as no furigana), the
    #    other supplies a kana reading. Not a reading conflict: the identity one
    #    never renders as furigana, so both are self-consistent.
    identity = [v for v in variants if v == expression]
    if identity and len(variants) > len(identity):
        return (
            "reading-vs-identity",
            f"{expression!r} is carried by one source as its own written form "
            f"(reading == expression, never rendered as furigana) and by another "
            f"with an explicit kana reading; these do not conflict.",
        )

    # B) The readings differ only by an inflection/particle tail (だけ / だけに,
    #    際に さい / さいに): a scope difference in how far each source's headword
    #    extends, not a disagreement about how a kanji is read.
    shortest = min(norm.values(), key=len)
    if all(r.startswith(shortest) or shortest.startswith(r) for r in norm.values()):
        return (
            "inflection-scope",
            f"the readings are prefixes of one another "
            f"({', '.join(sorted(set(norm.values())))}); the sources cover the "
            f"pattern to different inflection/particle depths, not a kanji-reading "
            f"conflict.",
        )

    # C) Genuine multi-reading of a kanji-bearing expression, every reading
    #    plausible (rendaku, on/kun, colloquial, or distinct senses). Preserved
    #    per source by design.
    if has_kanji(expression) and all(is_plausible_reading(expression, r) for r in variants):
        return (
            "genuine-multi-reading",
            f"{expression!r} legitimately takes more than one reading "
            f"({', '.join(sorted(variants))}) — rendaku / on-kun / colloquial or "
            f"distinct senses; each is plausible for the written form and is kept "
            f"attributed to its source rather than reconciled.",
        )

    # D) Kana-only expression with variant kana forms — nothing to check against
    #    a kanji reading; preserved per source.
    if not has_kanji(expression):
        return (
            "kana-only-variant",
            f"{expression!r} has no kanji; the differing kana forms are surface "
            f"variants each source publishes, with no reading to contradict.",
        )

    return ("needs-review", "no automatic justification; review required.")


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    resolved = []
    unresolved = []
    for row in audit["readingDisagreements"]:
        category, justification = classify(row["expression"], row["readings"])
        entry = {
            "expression": row["expression"],
            "readings": row["readings"],
            "category": category,
            "justification": justification,
        }
        resolved.append(entry)
        if category == "needs-review":
            unresolved.append(row["expression"])

    counts: dict[str, int] = {}
    for entry in resolved:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1

    OUT.write_text(
        json.dumps(
            {
                "total": len(resolved),
                "byCategory": counts,
                "allResolved": not unresolved,
                "resolved": resolved,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[reading-disagreements] {len(resolved)} disagreements")
    for category, count in sorted(counts.items()):
        print(f"    {category}: {count}")
    if unresolved:
        print(f"[reading-disagreements] FAIL: {len(unresolved)} need manual review: {unresolved}")
        return 1
    print(f"[reading-disagreements] OK — every disagreement justified, wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
