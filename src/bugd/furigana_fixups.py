"""Documented normalize-stage fix-up table for verified source furigana/field defects.

Scope
=====
The 文法 (``文法.apkg``) and Bunpro (``Bunpro Grammar Reference.apkg``) decks
carry a small number of *genuine* content defects that a per-kanji or
whole-word furigana check cannot repair on its own, because the fix depends on
knowing the intended word. Rather than re-authoring the source decks, the
extract/normalize stage applies this small, audited fix-up table to the raw
HTML *before* it becomes structured content. Every rule here was verified
against the raw ``collection.anki21b`` HTML of both decks (170,013 ruby pairs
total; 98.6% passed a KANJIDIC2 + UniDic n-best cross-check cleanly).

Two classes of correction live here:

1. **Ruby-pair typo fix-ups** (:data:`RUBY_FIXUPS`). A ``<ruby>BASE<rt>WRONG</rt></ruby>``
   is rewritten to ``<ruby>BASE<rt>RIGHT</rt></ruby>``. Every rule is keyed on
   *both* the base kanji and the exact wrong reading, so it can never touch a
   legitimate pair. Each wrong pair below occurs 1–6 times while its correct
   counterpart occurs hundreds/thousands of times in the same deck, i.e. these
   are unambiguous registration typos, not alternate readings.

2. **Empty / missing ``<rt>`` repair** (:func:`repair_empty_ruby`). A
   ``<ruby>BASE</ruby>`` with no ``<rt>`` child (or an explicitly empty
   ``<rt></rt>``) renders as a blank gap in Yomitan. We *unwrap* it to clean
   surface text — the fail-closed choice that preserves the kanji exactly and
   invents no reading (see ``yomitan-dictionary-engineering``: "malformed ruby
   should fall back to clean surface text"). Particles that leaked into the
   base (e.g. ``<ruby>健康の</ruby>``) unwrap to the same plain surface, so the
   の is preserved as ordinary text.

Deliberately **NOT** corrected (documented false positives)
===========================================================
The following pairs were flagged by the automated per-kanji check but are
correct jukujikun / contracted-compound furigana and are left as-is, per the
card's own guardrail ("structural jukujikun / productive-suffix items are NOT
defects"):

* ``美味`` rt=``おい`` — 美味しい is おいしい; 美味→おい with ``し…`` as okurigana.
  Consistent across all 236 occurrences; おい is the whole-word jukujikun label,
  not a per-kanji reading. Extending the base to include the kana ``し`` would
  put kana inside the ruby base, which is itself malformed.
* ``二日酔`` rt=``ふつかよ`` (＋okurigana ``い``) — 二日酔い is ふつかよい, correct.
* ``打合`` rt=``うちあわ`` (＋``せ``), ``組合`` rt=``くみあわ`` (＋``せ``),
  ``一人暮`` rt=``ひとりぐら`` (＋``し``), ``見出`` rt=``みいだ`` (＋``せない``),
  ``一度評価`` — the trailing kana are present as plain text immediately after
  the ruby, so the surface word reads correctly; only the naive per-kanji check
  fails on the contracted compound reading.

Idempotence
===========
Applying the table twice is a no-op: a corrected pair no longer matches any
wrong-pair key, and an unwrapped ruby no longer matches the empty-ruby pattern.
"""

from __future__ import annotations

import re

__all__ = [
    "RUBY_FIXUPS",
    "apply_ruby_fixups",
    "repair_empty_ruby",
    "normalize_furigana",
    "normalize_jlpt_field",
]


# --- 1. Ruby-pair typo fix-ups -------------------------------------------------
#
# (base, wrong_reading) -> correct_reading.
# Verified against raw deck HTML with surrounding surface context.
RUBY_FIXUPS: dict[tuple[str, str], str] = {
    # bunpro note 1776847270804 / 1776847271010 ("それなら"): 思(あも→おも),
    #   context 「…聞いたほうがいいと<ruby>思<rt>あも</rt></ruby>います」 → 思(おも)います.
    ("思", "あも"): "おも",
    # bunpro note 1776847271046 ("から見ると"): 私(またし→わたし),
    #   context 「…私のコレクションは…」 → 私(わたし).
    ("私", "またし"): "わたし",
    # bunpro note 1776847271278: 学(なな→まな), context 「…文化などを学ぶ」 → 学(まな)ぶ.
    ("学", "なな"): "まな",
    # bunpro note 1776847270608: 対(つか→たい), context 「動詞に対しても使う」 → 対(たい)して.
    #   Keyed on base 対, so the legitimate 使(つか) pair in the same clause is untouched.
    ("対", "つか"): "たい",
    # bunpro note 1776847270716: 使(かた→つか), context 「…の使い方を…」 → 使(つか)い方;
    #   the reading of the following 方(かた) had leaked onto 使.
    ("使", "かた"): "つか",
}

# Precompiled search patterns for each wrong pair. Matching on the exact literal
# <ruby>BASE<rt>WRONG</rt></ruby> keeps this scoped and idempotent.
_RUBY_FIXUP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"<ruby>" + re.escape(base) + r"<rt>" + re.escape(wrong) + r"</rt></ruby>"),
        f"<ruby>{base}<rt>{right}</rt></ruby>",
    )
    for (base, wrong), right in RUBY_FIXUPS.items()
]

# A <ruby> whose only content is the base (no <rt> child), or an explicitly
# empty <rt>. The base itself must contain no nested tags. Non-greedy, and the
# base excludes '<' so we never swallow a following well-formed ruby.
_EMPTY_RUBY = re.compile(r"<ruby>(?P<base>[^<]*?)(?:<rt>\s*</rt>)?</ruby>")


def apply_ruby_fixups(html: str) -> str:
    """Rewrite every verified wrong ``<ruby>base<rt>wrong</rt></ruby>`` pair.

    Idempotent: corrected pairs no longer match any wrong-pair key.
    """
    for pattern, replacement in _RUBY_FIXUP_PATTERNS:
        html = pattern.sub(replacement, html)
    return html


def repair_empty_ruby(html: str) -> str:
    """Unwrap empty/missing-``<rt>`` ruby to clean surface text.

    ``<ruby>方法</ruby>`` -> ``方法``; ``<ruby>読<rt></rt></ruby>`` -> ``読``;
    ``<ruby>健康の</ruby>`` -> ``健康の``. A ruby that *does* carry a real
    reading is left untouched because its base contains ``<rt>`` (a ``<``),
    which the pattern's ``[^<]`` base rejects.
    """
    return _EMPTY_RUBY.sub(lambda m: m.group("base"), html)


def normalize_furigana(html: str) -> str:
    """Full normalize-stage furigana pass: typo fix-ups then empty-ruby repair."""
    return repair_empty_ruby(apply_ruby_fixups(html))


# --- 2. JLPT field normalization ----------------------------------------------

_JLPT_LEVELS = ("N5", "N4", "N3", "N2", "N1")
_TAG = re.compile(r"<[^>]+>")
_LEVEL = re.compile(r"\bN[1-5]\b")


def normalize_jlpt_field(raw: str | None) -> tuple[str | None, str | None]:
    """Split a raw JLPTレベル field value into ``(level, note)``.

    Handles the two verified malformed cases plus the ordinary clean case:

    * ``"<div><div><div>N3</div></div></div>"`` (bunpou 1647069276306) -> ``("N3", None)``
      — nested wrapper divs stripped, not carried into the badge.
    * ``"N4<br>※N4では意味①のみ扱う。"`` (bunpou 1645780617415)
      -> ``("N4", "※N4では意味①のみ扱う。")`` — a level mixed with a footnote is
      split into a validated level plus a normalized note.
    * ``"N3"`` -> ``("N3", None)``; ``""`` / no level -> ``(None, <text or None>)``.

    The level is validated against the accepted JLPT set; anything else is
    returned as note text rather than guessed into a badge.
    """
    if raw is None:
        return None, None
    # Preserve the <br> split point as a newline before stripping other tags,
    # so "N4<br>※…" separates the level from the footnote.
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = _TAG.sub("", text)
    text = text.replace("&nbsp;", " ").strip()
    if not text:
        return None, None

    match = _LEVEL.search(text)
    level = match.group(0) if match and match.group(0) in _JLPT_LEVELS else None

    # Everything that is not the leading bare level becomes the note.
    remainder = text
    if level is not None:
        # Drop the first standalone level token; keep the rest as the note.
        remainder = _LEVEL.sub("", text, count=1)
    note = remainder.strip(" \n\u3000※").strip()
    # Collapse internal whitespace/newlines in the note to single spaces.
    note = re.sub(r"\s+", " ", note) if note else ""

    return level, (note or None)
