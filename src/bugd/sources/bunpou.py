"""文法 (bunpou) — the user's personal 文法.apkg Anki deck.

Source: a local Anki `.apkg` export, notetype `文法 Cloze`, 534 notes / 534
grammar points. The package is a ZIP whose `collection.anki21b` member is a
zstd-compressed SQLite database (new-schema Anki). This module reads the locked
bytes, decompresses, and maps one note's fields onto a `GrammarPoint`.

Field layout (per SOURCES.md), in note field order:

    文型 | 意味 | 接続 | JLPTレベル | 備考 |
    例文1 .. 例文15  (human example sentences, HTML with <strong> highlights) |
    AI丁寧度 | AI例文1 | AI英訳1 | AI例文2 | AI英訳2   (AI-generated)

`文型` is the headword, `意味` the gloss, `接続` the structure/formation, `備考`
notes, and `例文1..15` the human-authored examples. Fields prefixed `AI…` are
AI-generated and are SEGREGATED into `GrammarPoint.ai_generated` (never merged
into the human meaning/explanation), per the project's no-LLM-as-fact rule. The
two AI example sentences are attached as `Example` objects flagged
`ai_generated=True` so a downstream renderer can keep them behind a labelled
disclosure or drop them.
"""

from __future__ import annotations

import html
import io
import re
import sqlite3
import tempfile
import zipfile

from ..jsonio import MalformedPayload
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock
from .registry import register_extractor

APKG_NAME = "文法.apkg"
NOTETYPE = "文法 Cloze"

#: Note field order for the 文法 Cloze notetype (SOURCES.md).
FIELD_NAMES = (
    "文型", "意味", "接続", "JLPTレベル", "備考",
    *[f"例文{i}" for i in range(1, 16)],
    "AI丁寧度", "AI例文1", "AI英訳1", "AI例文2", "AI英訳2",
)

_RT = re.compile(r"<rt\b[^>]*>.*?</rt>", re.DOTALL)
_RP = re.compile(r"<rp\b[^>]*>.*?</rp>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\u3000]+")
_STRONG = re.compile(r"<strong\b[^>]*>(.*?)</strong>", re.DOTALL | re.IGNORECASE)
_JLPT = re.compile(r"[nN]?([1-5])")


def _flatten(raw: str | None) -> str | None:
    """Flatten source HTML to plain text, dropping furigana readings."""
    if raw is None:
        return None
    text = _RT.sub("", raw)
    text = _RP.sub("", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip() or None


def _jlpt(raw: str | None) -> str | None:
    """Normalize a JLPT level label to N1..N5, or None when off-scale/empty."""
    if not raw:
        return None
    m = _JLPT.search(raw)
    return f"N{m.group(1)}" if m else None


def _example(raw_html: str | None, *, ai: bool, english: str | None = None) -> Example | None:
    """Build an Example from a sentence field; None when there is no sentence."""
    japanese = _flatten(raw_html)
    if not japanese:
        return None
    highlights = tuple(
        h for h in (_flatten(m) for m in _STRONG.findall(raw_html or "")) if h
    )
    return Example(
        japanese=japanese,
        english=_flatten(english),
        highlight=highlights,
        ai_generated=ai,
    )


def _read_notes(apkg_bytes: bytes) -> list[list[str]]:
    """Return each note's field list from the .apkg's collection database.

    Handles the new-schema zstd-compressed `collection.anki21b` and the legacy
    uncompressed `collection.anki2`, filtered to the 文法 Cloze notetype.
    """
    archive = zipfile.ZipFile(io.BytesIO(apkg_bytes))
    members = set(archive.namelist())
    last_error: Exception | None = None
    for member in ("collection.anki21b", "collection.anki2"):
        if member not in members:
            continue
        raw = archive.read(member)
        if member.endswith("21b"):
            try:
                import zstandard as zstd

                raw = zstd.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
            except Exception as error:  # pragma: no cover - env-specific
                last_error = error
                continue
        with tempfile.NamedTemporaryFile(suffix=".anki.db") as handle:
            handle.write(raw)
            handle.flush()
            try:
                con = sqlite3.connect(handle.name)
            except sqlite3.DatabaseError as error:
                last_error = error
                continue
            try:
                # Restrict to notes of the 文法 Cloze notetype when the schema
                # exposes notetypes; otherwise take all notes (single-notetype deck).
                try:
                    ntid = con.execute(
                        "SELECT id FROM notetypes WHERE name = ?", (NOTETYPE,)
                    ).fetchone()
                    if ntid is not None:
                        rows = con.execute(
                            "SELECT flds FROM notes WHERE mid = ?", (ntid[0],)
                        ).fetchall()
                    else:
                        rows = con.execute("SELECT flds FROM notes").fetchall()
                except sqlite3.OperationalError:
                    rows = con.execute("SELECT flds FROM notes").fetchall()
                return [row[0].split("\x1f") for row in rows]
            finally:
                con.close()
    raise MalformedPayload(
        f"bunpou: could not read a collection database from {APKG_NAME}: {last_error}"
    )


@register_extractor
class BunpouExtractor(Extractor):
    name = "bunpou"
    label = "文法"

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)
        if APKG_NAME not in lock:
            raise MalformedPayload(f"{self.name}: locked input is missing: {APKG_NAME}")
        raw = self.read_locked_bytes(APKG_NAME)
        consumed = {APKG_NAME: lock[APKG_NAME]["sha256"]}

        notes = _read_notes(raw)
        points: list[GrammarPoint] = []
        skipped: list[dict[str, object]] = []
        ai_note_count = 0

        for index, fields in enumerate(notes):
            named = {
                FIELD_NAMES[i]: fields[i]
                for i in range(min(len(fields), len(FIELD_NAMES)))
            }
            expression = _flatten(named.get("文型"))
            if not expression:
                skipped.append({"index": index, "reason": "no 文型 headword"})
                continue

            # Human-authored examples (例文1..15), attached in order, deduped.
            examples: list[Example] = []
            seen: set[str] = set()
            for i in range(1, 16):
                ex = _example(named.get(f"例文{i}"), ai=False)
                if ex and ex.japanese not in seen:
                    seen.add(ex.japanese)
                    examples.append(ex)

            # AI-generated examples segregated + flagged, never mixed with human.
            ai_examples = [
                ex
                for ex in (
                    _example(named.get("AI例文1"), ai=True, english=named.get("AI英訳1")),
                    _example(named.get("AI例文2"), ai=True, english=named.get("AI英訳2")),
                )
                if ex is not None
            ]
            for ex in ai_examples:
                if ex.japanese not in seen:
                    seen.add(ex.japanese)
                    examples.append(ex)

            ai_generated: dict[str, object] = {}
            politeness = _flatten(named.get("AI丁寧度"))
            if politeness:
                ai_generated["politeness"] = politeness
            if ai_examples:
                ai_generated["exampleCount"] = len(ai_examples)
            if ai_generated:
                ai_note_count += 1

            points.append(
                GrammarPoint(
                    source=self.name,
                    source_id=str(index),
                    expression=expression,
                    reading=None,
                    meaning=_flatten(named.get("意味")),
                    structure=_flatten(named.get("接続")),
                    notes=_flatten(named.get("備考")),
                    jlpt=_jlpt(named.get("JLPTレベル")),
                    examples=tuple(examples),
                    ai_generated=ai_generated,
                    provenance={
                        "sourceLabel": self.label,
                        "notetype": NOTETYPE,
                    },
                )
            )

        # Emit the reviewable per-source artifact at the contract path.
        from ..jsonio import dump_json
        from ..pipeline import point_to_json

        jsonl_path = self.input_dir / "points.jsonl"
        jsonl_path.write_text(
            "".join(dump_json(point_to_json(point)) + "\n" for point in points),
            encoding="utf-8",
        )

        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "notes": len(notes),
                "points": len(points),
                "skipped": skipped,
                "notetype": NOTETYPE,
                "withExamples": sum(1 for p in points if p.examples),
                "withAiFields": ai_note_count,
                "examples": sum(len(p.examples) for p in points),
                "jsonl": jsonl_path.name,
                "distinctSourceIds": len({p.source_id for p in points}),
            },
        )
