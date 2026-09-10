"""NINJAL 日本語文型データベース (Nihongo Bunkei Database).

Source: 国立国語研究所 (NINJAL) *Nihongo Bunkei Database*, version 2026.01.26,
DOI 10.15084/0002000610, editors プラシャント・パルデシ / 砂川 有里子. 800 sentence
patterns, one XML file per headword inside a single distribution ZIP.

Unlike the community Yomitan-bank sources this one ships hand-authored teaching
XML, so it is a plain `Extractor` rather than a `CommunityBankExtractor`. Each
`<Entry>` carries one or more `<Sense>` blocks:

    <SentencePattern>～〓間〔あいだ〕</SentencePattern>   headword (may carry furigana)
    <Reading>～あいだ</Reading>                          kana reading
    <Sense>
      <SenceCategory>〓時〔とき〕｜〓期間〔きかん〕</SenceCategory>  semantic label
      <Level>4</Level>                                 NINJAL difficulty 1–5
      <Usage>…</Usage>                                  what the pattern means
      <UsageNotes>…</UsageNotes>                        how it is used
      <Connection>
        <ConnectionType>Vる〓間〔あいだ〕…</ConnectionType> formation
        <ExampleSet><Example>…｛〓間〔あいだ〕｝…</Example></ExampleSet>
      </Connection>
    </Sense>

Producer conventions, per the distribution readme:

* Furigana is written inline as ``〓漢字〔かな〕``; the base form is kept and the
  parenthetical reading dropped, so display text reads ``漢字`` not ``漢字(かな)``.
* The grammar point inside an example is wrapped in ``｛…｝``; those substrings
  become an `Example.highlight` rather than being re-derived by string search.
* Line breaks are encoded ``&#10;`` and decoded by the XML parser.

Level is NINJAL's own teaching-difficulty axis (1–5), **not** a JLPT level, so —
exactly as DoJG's print-volume tag is — it is recorded in provenance and never
coerced onto the JLPT scale (the fail-closed "levels are read, never guessed"
policy the community base enforces).
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from ..jsonio import MalformedPayload, dump_json
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock
from .community import JSONL_NAME, clean
from .registry import register_extractor

#: The one locked ZIP holding every per-headword XML file.
_ARCHIVE = "nihongo_bunkei_database20260126.zip"

#: `〓漢字〔かな〕` → `漢字`: keep the base form, drop the reading annotation.
_FURIGANA = re.compile(r"〓([^〔〓]*)〔[^〕]*〕")
#: The grammar point highlighted inside an example sentence.
_HIGHLIGHT = re.compile(r"｛([^｝]*)｝")


def member_name(info: zipfile.ZipInfo) -> str:
    """Recover a member's real (CP932) filename.

    779 of the distribution's 800 members carry the UTF-8 name flag and decode
    correctly; the other 21 do not, so `zipfile` decodes their Shift-JIS bytes
    as cp437 and produces mojibake like ``Åóé╡Åπé¬éΦé▄é╖`` for 召し上がります.
    Re-encoding that cp437 string recovers the original bytes, which then
    decode as CP932 — verified to roundtrip for every member and to keep all
    800 stems unique.
    """
    if info.flag_bits & 0x800:
        return info.filename
    return info.filename.encode("cp437").decode("cp932")


def strip_furigana(text: str) -> str:
    """Drop inline ``〓base〔reading〕`` annotations, keeping the base form.

    A lone ``〓`` marker with no ``〔…〕`` (never observed but cheap to guard) is
    also removed so it can never leak into rendered text.
    """
    return _FURIGANA.sub(r"\1", text).replace("〓", "")


def example_from_text(raw: str) -> Example | None:
    """Turn one `<Example>` into an Example, lifting its ``｛…｝`` highlights."""
    highlights = tuple(
        clean(strip_furigana(match)) or ""
        for match in _HIGHLIGHT.findall(raw)
    )
    highlights = tuple(text for text in highlights if text)
    japanese = clean(strip_furigana(raw).replace("｛", "").replace("｝", ""))
    if not japanese:
        return None
    return Example(japanese=japanese, english=None, highlight=highlights)


@register_extractor
class NinjalBunkeiExtractor(Extractor):
    name = "ninjal_bunkei"
    label = "NINJAL 日本語文型データベース"

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)
        if _ARCHIVE not in lock:
            raise MalformedPayload(
                f"{self.name}: locked archive is missing: {_ARCHIVE}"
            )
        raw = self.read_locked_bytes(_ARCHIVE)

        points: list[GrammarPoint] = []
        members = 0
        skipped = 0
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = sorted(
                (
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and info.filename.endswith(".xml")
                ),
                key=member_name,
            )
            for info in entries:
                members += 1
                point = self._parse_entry(archive.read(info.filename), member_name(info))
                if point is None:
                    skipped += 1
                    continue
                points.append(point)

        self.write_jsonl(points)
        return ExtractResult(
            source=self.name,
            points=points,
            consumed={_ARCHIVE: lock[_ARCHIVE]["sha256"]},
            stats={
                "members": members,
                "points": len(points),
                "skipped": skipped,
                "withExamples": sum(1 for point in points if point.examples),
                "withJlpt": sum(1 for point in points if point.jlpt),
            },
        )

    def _parse_entry(self, raw: bytes, filename: str) -> GrammarPoint | None:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:  # a corrupt member is a build defect
            raise MalformedPayload(f"{self.name}: {filename} is not valid XML: {exc}")

        pattern = strip_furigana((root.findtext("SentencePattern") or "").strip())
        reading = clean(strip_furigana((root.findtext("Reading") or "").strip()))
        expression = clean(pattern) or reading
        if not expression:
            return None

        senses = root.findall("Sense")
        # Per-sense substance is flattened into the single-record contract: each
        # sense contributes a labelled block, so a multi-sense pattern keeps all
        # its senses instead of collapsing to the first.
        categories: list[str] = []
        levels: list[str] = []
        meaning_parts: list[str] = []
        notes_parts: list[str] = []
        structure_parts: list[str] = []
        examples: list[Example] = []

        for index, sense in enumerate(senses):
            prefix = f"[{index + 1}] " if len(senses) > 1 else ""
            category = clean(strip_furigana((sense.findtext("SenceCategory") or "").strip()))
            if category:
                categories.append(category)
            level = (sense.findtext("Level") or "").strip()
            if level:
                levels.append(level)

            usage = clean(strip_furigana((sense.findtext("Usage") or "")))
            if usage:
                meaning_parts.append(prefix + usage if prefix else usage)
            usage_notes = clean(strip_furigana((sense.findtext("UsageNotes") or "")))
            if usage_notes:
                notes_parts.append(prefix + usage_notes if prefix else usage_notes)

            for connection in sense.findall("Connection"):
                connection_type = clean(
                    strip_furigana((connection.findtext("ConnectionType") or "").strip())
                )
                if connection_type:
                    structure_parts.append(connection_type)
                for example_set in connection.findall("ExampleSet"):
                    for element in example_set.findall("Example"):
                        example = example_from_text(element.text or "")
                        if example is not None:
                            examples.append(example)

        provenance: dict[str, object] = {
            "sourceLabel": self.label,
            "sourceFile": filename,
        }
        if categories:
            provenance["senseCategories"] = categories
        if levels:
            # NINJAL's teaching-difficulty axis, kept verbatim as provenance —
            # deliberately NOT mapped onto JLPT, which this source does not
            # publish.
            provenance["ninjalLevels"] = levels

        return GrammarPoint(
            source=self.name,
            source_id=filename[:-4] if filename.endswith(".xml") else filename,
            expression=expression,
            reading=reading if reading and reading != expression else None,
            meaning="\n\n".join(meaning_parts) or None,
            structure="\n".join(dict.fromkeys(structure_parts)) or None,
            notes="\n\n".join(notes_parts) or None,
            jlpt=None,
            examples=tuple(examples),
            provenance=provenance,
        )

    def write_jsonl(self, points: list[GrammarPoint]) -> None:
        """Write this source's records as JSONL beside its locked bytes.

        Mirrors `CommunityBankExtractor.write_jsonl` so a reviewer can read one
        source's normalized records without running the merge stage.
        """
        from ..pipeline import point_to_json

        path = self.input_dir / JSONL_NAME
        path.write_text(
            "".join(dump_json(point_to_json(point)) + "\n" for point in points),
            encoding="utf-8",
        )


__all__ = ["NinjalBunkeiExtractor", "member_name", "strip_furigana", "example_from_text"]
