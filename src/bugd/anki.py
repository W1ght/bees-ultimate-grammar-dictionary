"""Read notes out of an Anki `.apkg` export.

Shared by every Anki-backed source. An `.apkg` is a ZIP whose collection member
is a SQLite database; modern exports (`collection.anki21b`) zstd-compress it,
older ones (`collection.anki2`) store it raw. Per-note field values live in one
`notes.flds` string split on the ASCII unit separator, and the field *names* live
in a separate table keyed by notetype, so field order must be read from the
database rather than assumed.

Everything here is read-only and fail-closed:

* archive members, decompressed size, member count, and note count are bounded
  before anything is parsed, so a hostile or truncated export cannot exhaust
  memory;
* the collection is opened read-only through a URI, and the `unicase` collation
  Anki registers at runtime is supplied as a no-op comparison so schema queries
  do not fail on a stock `sqlite3`;
* a note whose field count does not match its notetype is a hard error, not a
  silently short record.
"""

from __future__ import annotations

import io
import pathlib
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass

from .jsonio import MalformedPayload

#: Anki's per-note field separator (ASCII unit separator).
FIELD_SEPARATOR = "\x1f"

#: Collection members, most recent format first.
COLLECTION_MEMBERS = ("collection.anki21b", "collection.anki21", "collection.anki2")

#: Bounds. The Bunpro export is the largest real input: 257 MB of archive,
#: ~14.9k members, a 30 MB collection, 964 notes. Each ceiling is a generous
#: multiple of that so a legitimate deck passes while a decompression bomb or a
#: runaway member count fails closed.
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 200_000
MAX_COLLECTION_BYTES = 512 * 1024 * 1024
MAX_NOTES = 500_000


class AnkiPackageError(MalformedPayload):
    """An `.apkg` is malformed, unsupported, or exceeds a safety bound."""


@dataclass(frozen=True)
class AnkiNote:
    """One note: its id, its notetype name, and its named field values."""

    note_id: int
    notetype: str
    fields: dict[str, str]
    tags: tuple[str, ...] = ()


def read_apkg_notes(apkg_bytes: bytes, *, notetype: str) -> list[AnkiNote]:
    """Read every note of `notetype` out of the in-memory `.apkg` bytes.

    Notes are returned in ascending note-id order, which is the deck's own stable
    order, so two runs over the same bytes always produce the same sequence.
    """
    collection = extract_collection(apkg_bytes)
    with tempfile.TemporaryDirectory(prefix="bugd-anki-") as directory:
        path = pathlib.Path(directory) / "collection.sqlite"
        path.write_bytes(collection)
        return _read_notes(path, notetype=notetype)


def extract_collection(apkg_bytes: bytes) -> bytes:
    """Return the decompressed SQLite collection from `.apkg` bytes."""
    if not isinstance(apkg_bytes, bytes) or not apkg_bytes:
        raise AnkiPackageError("apkg payload is empty")
    if len(apkg_bytes) > MAX_ARCHIVE_BYTES:
        raise AnkiPackageError(f"apkg exceeds {MAX_ARCHIVE_BYTES} bytes")

    try:
        archive = zipfile.ZipFile(io.BytesIO(apkg_bytes))
    except zipfile.BadZipFile as error:
        raise AnkiPackageError(f"apkg is not a valid ZIP: {error}") from error

    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise AnkiPackageError(f"apkg has more than {MAX_ARCHIVE_MEMBERS} members")
    names = {info.filename for info in infos}

    member = next((name for name in COLLECTION_MEMBERS if name in names), None)
    if member is None:
        raise AnkiPackageError(
            f"apkg has no collection member (looked for {', '.join(COLLECTION_MEMBERS)})"
        )
    info = archive.getinfo(member)
    if info.file_size > MAX_COLLECTION_BYTES:
        raise AnkiPackageError(f"{member} exceeds {MAX_COLLECTION_BYTES} bytes")

    raw = archive.read(member)
    if raw.startswith(b"SQLite format 3\x00"):
        return raw
    return _zstd_decompress(raw, member=member)


def _zstd_decompress(raw: bytes, *, member: str) -> bytes:
    """Decompress a zstd-framed collection member, bounded.

    Modern Anki exports zstd-compress the collection. `zstandard` is an optional
    dependency: a legacy `collection.anki2` export needs no decompressor at all,
    so a missing module is reported against the specific member that needed it
    rather than failing import of this module.
    """
    if not raw.startswith(b"\x28\xb5\x2f\xfd"):
        raise AnkiPackageError(f"{member} is neither SQLite nor a zstd frame")
    try:
        import zstandard
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise AnkiPackageError(
            f"{member} is zstd-compressed but the zstandard module is unavailable"
        ) from error
    try:
        plain = zstandard.ZstdDecompressor().decompress(raw, max_output_size=MAX_COLLECTION_BYTES)
    except zstandard.ZstdError as error:
        raise AnkiPackageError(f"{member} failed zstd decompression: {error}") from error
    if not plain.startswith(b"SQLite format 3\x00"):
        raise AnkiPackageError(f"{member} did not decompress to a SQLite database")
    return plain


def _read_notes(path: pathlib.Path, *, notetype: str) -> list[AnkiNote]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        # Anki registers `unicase` in its own runtime; stock sqlite3 does not
        # have it, and the schema references it, so queries against `fields` /
        # `notetypes` fail with "no such collation sequence" without this. The
        # only use here is ordering, so a plain comparison is sufficient.
        connection.create_collation("unicase", _unicase)
        connection.row_factory = sqlite3.Row

        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
        if "notes" not in tables:
            raise AnkiPackageError("collection has no notes table")
        if not {"notetypes", "fields"} <= tables:
            raise AnkiPackageError(
                "collection uses the legacy models JSON schema, which this reader "
                "does not support; export from a modern Anki version"
            )

        matches = [
            row["id"]
            for row in connection.execute("select id, name from notetypes")
            if row["name"] == notetype
        ]
        if not matches:
            available = sorted(row["name"] for row in connection.execute("select name from notetypes"))
            raise AnkiPackageError(
                f"notetype {notetype!r} is not in this collection (found: {', '.join(available)})"
            )
        if len(matches) > 1:
            raise AnkiPackageError(f"notetype {notetype!r} is ambiguous: {len(matches)} matches")
        notetype_id = matches[0]

        names = [
            row["name"]
            for row in connection.execute(
                "select ord, name from fields where ntid = ? order by ord", (notetype_id,)
            )
        ]
        if not names:
            raise AnkiPackageError(f"notetype {notetype!r} declares no fields")

        total = connection.execute(
            "select count(*) from notes where mid = ?", (notetype_id,)
        ).fetchone()[0]
        if total > MAX_NOTES:
            raise AnkiPackageError(f"collection has more than {MAX_NOTES} notes of {notetype!r}")

        notes: list[AnkiNote] = []
        for row in connection.execute(
            "select id, flds, tags from notes where mid = ? order by id", (notetype_id,)
        ):
            values = row["flds"].split(FIELD_SEPARATOR)
            if len(values) != len(names):
                raise AnkiPackageError(
                    f"note {row['id']} has {len(values)} field(s) but notetype "
                    f"{notetype!r} declares {len(names)}"
                )
            notes.append(
                AnkiNote(
                    note_id=int(row["id"]),
                    notetype=notetype,
                    fields=dict(zip(names, values)),
                    tags=tuple((row["tags"] or "").split()),
                )
            )
        return notes
    finally:
        connection.close()


def _unicase(left: str, right: str) -> int:
    left_folded = left.casefold()
    right_folded = right.casefold()
    if left_folded == right_folded:
        return (left > right) - (left < right)
    return (left_folded > right_folded) - (left_folded < right_folded)


__all__ = [
    "AnkiNote",
    "AnkiPackageError",
    "COLLECTION_MEMBERS",
    "FIELD_SEPARATOR",
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_MEMBERS",
    "MAX_COLLECTION_BYTES",
    "MAX_NOTES",
    "extract_collection",
    "read_apkg_notes",
]
