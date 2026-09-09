"""Partition axes that may never be folded: dialect variety, era, register.

The card asks the matcher to handle politeness registers and classical-vs-modern
without collapsing genuinely different points. These axes are handled by
*partitioning before matching*, not by scoring after it: two records that
disagree on variety or era are never candidates for the same canonical point, so
no similarity measure can ever fold them.

Register is treated differently on purpose. Measured against the real corpus,
register markers (`硬い`, `くだけた`, `丁寧`) are prose remarks *about* a point far
more often than they are a distinguishing property *of* it — 858 of 4,972 records
carry one, and the same point is routinely described as 硬い by one source and not
mentioned by another. Partitioning on register would therefore split correct
folds. Register is recorded as an observed attribute on every canonical point and
reported, but it does not partition.

Era and dialect do partition: a classical 如し and a modern ようだ are different
lexical items, and 関西弁 やん is not standard じゃない.
"""

from __future__ import annotations

import re

#: Explicit classical/literary-language markers.
CLASSICAL_RE = re.compile(r"古語|文語|古文|古典|雅語|擬古|古い言い方|古めかしい|漢文|古語由来")

#: Explicit regional-dialect markers.
DIALECT_RE = re.compile(r"関西弁|大阪弁|京都弁|方言|九州弁|東北弁")

#: Register/politeness remarks. Recorded, never partitioned on (see module docs).
REGISTER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("formal", r"硬い表現|かたい表現|書き言葉|文章語|改まった"),
    ("casual", r"くだけた|カジュアル|話し言葉|口語"),
    ("polite", r"丁寧|敬語|尊敬語|謙譲語"),
    ("blunt", r"ぞんざい|俗語|スラング|乱暴"),
)

_PROSE_FIELDS = ("meaning", "structure", "nuance", "explanation", "notes")


def _prose(record: dict[str, object]) -> str:
    chunks = [record.get(field) for field in _PROSE_FIELDS]
    tags = record.get("tags") or ()
    if isinstance(tags, (list, tuple)):
        chunks.extend(tags)
    return " ".join(str(chunk) for chunk in chunks if chunk)


def variety(record: dict[str, object]) -> str:
    """`"dialect"` when the source marks the point regional, else `"standard"`."""
    return "dialect" if DIALECT_RE.search(_prose(record)) else "standard"


def era(record: dict[str, object]) -> str:
    """`"classical"` when the source marks the point classical, else `"modern"`."""
    return "classical" if CLASSICAL_RE.search(_prose(record)) else "modern"


def registers(record: dict[str, object]) -> tuple[str, ...]:
    """Register remarks observed on a record, sorted. Reported, not partitioned."""
    prose = _prose(record)
    return tuple(sorted(label for label, pattern in REGISTER_PATTERNS if re.search(pattern, prose)))


def partition_axes(record: dict[str, object]) -> tuple[str, str]:
    """The `(variety, era)` pair a record's canonical key is scoped to."""
    return variety(record), era(record)


__all__ = [
    "CLASSICAL_RE",
    "DIALECT_RE",
    "REGISTER_PATTERNS",
    "era",
    "partition_axes",
    "registers",
    "variety",
]
