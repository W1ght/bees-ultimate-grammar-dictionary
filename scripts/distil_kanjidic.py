"""Distil KANJIDIC2 into the compact per-kanji reading map bugd.readings needs.

Input:  KANJIDIC2 XML.gz (EDRDG, CC BY-SA 4.0), pinned by sha256 in the output
        provenance header.
Output: src/bugd/data/kanji_readings.json — {kanji: [hiragana readings...]},
        plus a provenance block recording the source digest, version, and count.

The full ~1.5 MB XML is NOT vendored; only the on/kun/nanori readings the gate
reads are kept, so the shipped asset is a fraction of the size and its
provenance is auditable against the pinned upstream digest.

Dependency-free: katakana→hiragana folding is done with a stdlib codepoint
offset (the same helper bugd.readings uses), so regenerating the asset needs
nothing beyond CPython.

Usage:
    python scripts/distil_kanjidic.py <kanjidic2.xml.gz> src/bugd/data/kanji_readings.json
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import sys
import xml.etree.ElementTree as ET


def kata_to_hira(text: str) -> str:
    """Fold full-width katakana onto hiragana (U+30A1–U+30F6 -> -0x60)."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        out.append(chr(code - 0x60) if 0x30A1 <= code <= 0x30F6 else ch)
    return "".join(out)


def distil(xml_gz: pathlib.Path) -> tuple[dict[str, list[str]], str, str]:
    raw = xml_gz.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    readings: dict[str, list[str]] = {}
    version = ""
    with gzip.open(xml_gz, "rb") as fh:
        for _event, el in ET.iterparse(fh, events=("end",)):
            if el.tag == "database_version" and not version:
                version = (el.text or "").strip()
            if el.tag != "character":
                continue
            lit = el.findtext("literal")
            rs: set[str] = set()
            for r in el.iter("reading"):
                rtype = r.get("r_type")
                if rtype == "ja_on":
                    rs.add(kata_to_hira(r.text or ""))
                elif rtype == "ja_kun":
                    # kun readings carry okurigana after '.', e.g. つか.う
                    text = r.text or ""
                    rs.add(text.replace(".", "").replace("-", ""))
                    rs.add(text.split(".")[0].replace("-", ""))
            for n in el.iter("nanori"):
                if n.text:
                    rs.add(n.text)
            if lit:
                readings[lit] = sorted(x for x in rs if x)
            el.clear()
    return readings, digest, version


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <kanjidic2.xml.gz> <out.json>")
    src = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2])
    readings, digest, version = distil(src)
    payload = {
        "_provenance": {
            "source": "KANJIDIC2 (Electronic Dictionary Research and Development Group)",
            "licence": "CC BY-SA 4.0",
            "sourceSha256": digest,
            "databaseVersion": version,
            "kanjiCount": len(readings),
            "distilledBy": "scripts/distil_kanjidic.py",
            "note": "on/kun/nanori readings only, hiragana; okurigana split off kun",
        },
        "readings": readings,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} — {len(readings)} kanji, source sha256 {digest[:16]}…, {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
