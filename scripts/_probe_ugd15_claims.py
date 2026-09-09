"""Re-verify every factual claim asserted in LICENSING.md against real artifacts."""
import collections
import glob
import hashlib
import importlib
import json
import os
import sys
import zipfile

fails = []


def chk(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


p = "dist/bees-ultimate-grammar-dictionary.zip"
raw = open(p, "rb").read()
digest = hashlib.sha256(raw).hexdigest()
zf = zipfile.ZipFile(p)
banks = [m for m in zf.namelist() if m.startswith("term_bank_")]
entries = sum(len(json.loads(zf.read(m))) for m in banks)

chk(digest.startswith("33546769dd33"), f"zip digest 33546769dd33... (actual {digest[:12]})")
chk(len(raw) == 1706586, f"zip bytes 1706586 (actual {len(raw)})")
chk(entries == 2419, f"zip entries 2419 (actual {entries})")
chk(len(banks) == 3, f"3 term banks (actual {len(banks)})")

tags = sorted(t[0] for t in json.loads(zf.read("tag_bank_1.json")))
expect_tags = ["dojg", "donna_toki", "edewakaru", "nihongo_net", "nihongo_no_sensei"]
chk(tags == expect_tags, f"tag_bank sources {tags}")

blob = "".join(zf.read(m).decode("utf8") for m in banks)
for lab in ["Yokubi", "yoku.bi", "IMABI", "imabi", "Bunpro", "bunpro",
            "\u65e5\u672c\u8a9e\u6587\u578b\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9", "NINJAL", "ninjal", "bunpou"]:
    chk(blob.count(lab) == 0, f'zero "{lab}" in packaged banks (actual {blob.count(lab)})')

want = {
    "bunpou": ("D", False), "dojg": ("C", False), "donna_toki": ("C", False),
    "edewakaru": ("B", False), "nihongo_net": ("B", False),
    "nihongo_no_sensei": ("B", False), "ninjal_bunkei": ("A", True),
}
for s, (t, r) in want.items():
    prov = json.load(open(f"data/sources/{s}/SOURCE.lock.json")).get("provenance", {})
    chk(prov.get("licenseTier") == t and prov.get("redistributable") == r,
        f"{s} lock tier={prov.get('licenseTier')} redist={prov.get('redistributable')} (doc {t}/{r})")

for s in ["bunpro", "imabi"]:
    lk = json.load(open(f"data/sources/{s}/SOURCE.lock.json"))
    chk(not lk.get("provenance", {}).get("licenseTier"), f"{s} lock has NO licence block")

for s, c in [("dojg", 535), ("donna_toki", 1082), ("edewakaru", 1248),
             ("nihongo_net", 628), ("nihongo_no_sensei", 1479), ("ninjal_bunkei", 800)]:
    dd = json.load(open(f"data/extracted/{s}.json"))
    pts = dd.get("points", dd)
    chk(len(pts) == c, f"{s} extracted {len(pts)} (doc {c})")

pts = json.load(open("data/extracted/dojg.json"))
pts = pts.get("points", pts)
v = collections.Counter(x["provenance"].get("volume") for x in pts)
chk(v["\u57fa\u672c (Basic)"] == 86 and v["\u4e2d\u7d1a\u7de8 (Intermediate)"] == 191
    and v["\u4e0a\u7d1a\u7de8 (Advanced)"] == 258, f"dojg volumes {dict(v)}")

bp = "".join(open(f).read() for f in
             ["src/bugd/banks.py", "src/bugd/unify.py", "src/bugd/pipeline.py"] if os.path.exists(f))
chk("redistributable" not in bp, 'no "redistributable" read in banks/unify/pipeline')

chk("Attribution 4.0 International" in open("data/sources/yokubi/LICENSE").read(),
    "yokubi LICENSE is the CC BY 4.0 text")
cr = open("data/sources/yokubi/src/Credits.md").read()
chk("Creative Commons By-Attribution 4.0 license" in cr, "yokubi Credits.md declares CC BY-Attribution 4.0")
chk("even commercially, as long as you attribute the original work" in cr, "yokubi grant quote exact")

rd = open("data/sources/ninjal_bunkei/readme.txt").read()
chk("\u30e9\u30a4\u30bb\u30f3\u30b9: CC BY 4.0" in rd, "NINJAL readme declares CC BY 4.0")
chk("10.15084/0002000610" in rd, "NINJAL DOI present")

tot = 0
for lk in sorted(glob.glob("data/sources/*/SOURCE.lock.json")):
    f = json.load(open(lk)).get("files", {})
    tot += len(f)
chk(tot == 611, f"611 pinned files (actual {tot})")

sys.path.insert(0, "src")
for m in expect_tags:
    importlib.import_module(f"bugd.sources.{m}")
from bugd.sources.registry import source_names  # noqa: E402
chk(sorted(source_names()) == expect_tags, f"registry {sorted(source_names())}")

print("\n" + ("ALL CLAIMS VERIFIED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
