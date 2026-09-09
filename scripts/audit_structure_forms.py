"""Report structure/接続 lines that spell a corrupted headword.

Advisory content audit (see bugd.structure_audit): a formation line that spells
the grammar point's own headword with a single internal-kana slip absent from
every other field of the same card. Prints one line per suspect plus a total.
Run from the repo root:

    python scripts/audit_structure_forms.py
"""

import json
import pathlib
import sys

sys.path.insert(0, "src")

from bugd.pipeline import point_from_json  # noqa: E402
from bugd.structure_audit import audit_points  # noqa: E402

EXTRACTED = pathlib.Path("data/extracted")


def main() -> int:
    suspects = []
    for artifact in sorted(EXTRACTED.glob("*.json")):
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        points = [point_from_json(item) for item in payload.get("points", [])]
        suspects.extend(audit_points(points))

    for suspect in suspects:
        print(
            f"{suspect['source']}/{suspect['source_id']}: "
            f"structure spells {suspect['structure_form']!r} "
            f"(headword {suspect['headword']!r}, differs at index {suspect['diff_index']})"
        )
    print(f"\n{len(suspects)} suspect formation line(s) across {EXTRACTED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
