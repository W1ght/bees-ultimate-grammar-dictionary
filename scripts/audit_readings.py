"""Reading audit gate, run as part of `make merge`.

Two fail-closed checks against the emitted unified dataset (data/merge/unified.jsonl):

1. **Plausibility gate (fail-closed).** Every kanji-bearing contribution
   `reading` must be a structurally possible kana rendering of its own
   `expression` (bugd.readings.is_plausible_reading). A new structural violation
   fails the build. This is the last-line guard the nine UGD-11c-B corrections
   were about; it catches structurally impossible readings (e.g. 結構->けっか),
   not context/sense reading errors (which only semantic review can catch — see
   the module docstring).

2. **Cross-source reading agreement (report + fail-closed on regressions).**
   Where two sources give the same written expression a *different* reading, the
   pair is surfaced. Genuine multi-reading expressions (甲斐 かい/がい,
   如何 いかん/いかが) are expected; the check fails only if a disagreement's
   readings are not BOTH plausible for the expression, i.e. one source is
   shipping an impossible reading the plausibility gate would also flag.

Writes data/merge/reading_audit.json for review. Exits non-zero on any failure.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.readings import has_kanji, is_plausible_reading  # noqa: E402

UNIFIED = pathlib.Path("data/merge/unified.jsonl")
REPORT = pathlib.Path("data/merge/reading_audit.json")


def _contributions(entries):
    for entry in entries:
        for sense in entry.get("senses", []):
            for contribution in sense.get("contributions", []):
                yield contribution


def main() -> int:
    entries = [json.loads(line) for line in UNIFIED.read_text(encoding="utf-8").splitlines() if line.strip()]

    # 1. Plausibility gate.
    checked = 0
    implausible = []
    # 2. Cross-source disagreement: expression -> {reading -> sources}
    by_expr: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))

    for contribution in _contributions(entries):
        expression = contribution.get("expression") or ""
        reading = contribution.get("reading")
        if reading:
            by_expr[expression][reading].add(contribution.get("source", ""))
        if not has_kanji(expression) or not reading:
            continue
        checked += 1
        if not is_plausible_reading(expression, reading):
            implausible.append(
                {
                    "source": contribution.get("source"),
                    "expression": expression,
                    "reading": reading,
                }
            )

    disagreements = []
    disagreement_failures = []
    for expression, readings in sorted(by_expr.items()):
        if len(readings) < 2:
            continue
        variants = sorted(readings)
        # Every reading of a disagreement must itself be plausible; an impossible
        # one is a real defect (and the plausibility gate above already caught it
        # if it is kanji-bearing).
        bad = [r for r in variants if has_kanji(expression) and not is_plausible_reading(expression, r)]
        record = {
            "expression": expression,
            "readings": {r: sorted(readings[r]) for r in variants},
            "allPlausible": not bad,
        }
        disagreements.append(record)
        if bad:
            disagreement_failures.append({"expression": expression, "implausible": bad})

    REPORT.write_text(
        json.dumps(
            {
                "checkedKanjiReadings": checked,
                "implausibleReadings": implausible,
                "readingDisagreements": disagreements,
                "disagreementCount": len(disagreements),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[reading-audit] checked {checked} kanji-bearing readings")
    print(f"[reading-audit] cross-source reading disagreements: {len(disagreements)}")
    ok = True
    if implausible:
        ok = False
        print(f"[reading-audit] FAIL: {len(implausible)} structurally implausible reading(s):")
        for item in implausible:
            print(f"    {item['source']} · {item['expression']} -> {item['reading']}")
    if disagreement_failures:
        ok = False
        print(f"[reading-audit] FAIL: {len(disagreement_failures)} disagreement(s) carry an implausible reading:")
        for item in disagreement_failures:
            print(f"    {item['expression']} -> implausible {item['implausible']}")
    if ok:
        print(f"[reading-audit] OK — wrote {REPORT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
