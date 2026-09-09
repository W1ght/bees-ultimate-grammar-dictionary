import pathlib
import sys

sys.path.insert(0, "src")
from bugd.jsonio import dump_json
from bugd.unify import run_unify

stats = run_unify(
    extracted_dir=pathlib.Path("data/extracted"),
    keymap_path=pathlib.Path("data/merge/keymap.json"),
    unified_path=pathlib.Path("data/merge/unified.jsonl"),
    stats_path=pathlib.Path("data/merge/unified.stats.json"),
)
import json

print(json.dumps(stats, ensure_ascii=False, indent=1)[:4000])
