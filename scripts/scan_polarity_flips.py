"""Corpus scan for the polarity-flipped-headword property (UGD-11c-A).

Acceptance criterion 2: after the extraction-level polarity repair, no point
entry has a headword ending in 〜ある while the card's OWN READING teaches the
〜ない counterpart. The reading is the publisher's phonetic transcription of the
same headword, so a headword whose reading is negative while its surface is
affirmative is the exact defect this card removes.

This reads the *extracted* records (post-repair; the repair runs inside
`CommunityBankExtractor.extract`), so run `make extract` first. It reports the
number of contributions whose 〜ある headword contradicts its own reading — this
must be zero — and, for context, the count of genuine 〜ある headwords whose
reading agrees with them (left untouched).

The two donna_toki rows the repair deliberately abstains on — と言ったらある and
所ではある, where the publisher flipped BOTH the expression and the reading so no
self-consistent extraction signal remains — are enumerated and justified in
docs/notes/UGD-11c-A-polarity-flip.md rather than guessed at here.

Exit status is non-zero when the defect property is present, so the scan can gate
a build the same way the other audits do.
"""

import json
import pathlib
import sys
import unicodedata

sys.path.insert(0, "src")

from bugd.pipeline import point_from_json
from bugd.polarity import polarity

EXTRACTED = pathlib.Path("data/extracted")


def _nfkc(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "")


def scan(extracted: pathlib.Path) -> tuple[list[tuple[str, str, str]], int]:
    """Return (defects, agreeing_aru_count) over an extracted-records directory."""
    defects: list[tuple[str, str, str]] = []
    agreeing = 0
    for path in sorted(extracted.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("points", []):
            point = point_from_json(record)
            if not _nfkc(point.expression).endswith("ある"):
                continue
            if polarity(point.reading) == "neg":
                defects.append((point.source, point.expression, point.reading or ""))
            else:
                agreeing += 1
    return defects, agreeing


def main() -> int:
    if not EXTRACTED.is_dir():
        print(f"no extracted data at {EXTRACTED}; run `make extract` first", file=sys.stderr)
        return 2

    defects, agreeing = scan(EXTRACTED)

    print(f"〜ある headwords whose OWN reading is negative (the defect): {len(defects)}")
    for source, expr, reading in defects:
        print(f"  DEFECT {source}: {expr!r} (reading {reading!r})")
    print(f"〜ある headwords whose reading agrees (genuine affirmatives, untouched): {agreeing}")

    if defects:
        print("\nFAIL: a headword still contradicts its own reading.", file=sys.stderr)
        return 1
    print("\nOK: no 〜ある headword contradicts its own reading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
