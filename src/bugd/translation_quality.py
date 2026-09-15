"""Reject a machine translation that lost or mangled what it had to preserve.

The fork's Chinese side is produced by translating an English-only source's prose
and example glosses. Both translation paths -- the hosted LLM in
`scripts/localize_chinese.py` and the offline Argos/CTranslate2 model in
`scripts/localize_chinese_argos_batch.py` -- promise the SAME invariant: the
Japanese the passage quotes, its URLs and its markup come back verbatim, because
a grammar explanation that has lost the pattern it is explaining explains
nothing.

The Argos path implemented that promise by substituting a `ZXQJPN00001Q`
sentinel for every protected run and replacing it back afterwards. A subword NMT
model does not treat a sentinel as opaque: it re-spelled them (`ZQQJPN000Q`,
`Z~JPN00111Q`), split them (`ZQJPN00015 Q`), and transliterated them into
Chinese (`齐·杰普恩00092Q`, `赞 贾 宾 夸 Q`), so the exact-string restore missed
and the sentinel shipped INSIDE the dictionary. Measured in the packaged
v2026.09.14.4 banks: 99.4% of IMABI's 494 Chinese explanations, 100% of Yokubi's
132, and 43.5% of DoJG's 1,545 carried sentinel debris, a runaway repetition loop
(`重音` x200), or both.

This module is the gate that makes that class of defect unshippable. It does not
judge translation STYLE -- no automated check can -- only whether the output
still satisfies the invariant the translator was given. A degraded translation is
dropped rather than rendered, and the card falls back to the source's own English,
which is what the reader can actually use.
"""

from __future__ import annotations

import re

#: Runs a translator must reproduce verbatim: Japanese (the thing being
#: explained), links, and inline markup. Mirrors the spans
#: `scripts/localize_chinese_argos_batch.py` protects, because the check has to
#: hold the translator to the promise it was actually given.
_JAPANESE_RUN = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿！-￯"
    r"。、，．：；！？「」『』（）［］【】〔〕〈〉《》…〜～※]+"
)
_URL = re.compile(r"https?://\S+")
_TAG = re.compile(r"<[^>\n]*>")

#: Debris from a mangled placeholder. The stem `JPN` followed by the ordinal is
#: what survives most re-spellings; `ZXQJPN` catches an intact sentinel that the
#: restore pass simply never ran on. Zero hits across the 2,169 English source
#: fields these translations were made from, so a match is debris, not content.
_SENTINEL_DEBRIS = re.compile(r"JPN\s?\d{2,6}|ZXQJPN|Z[XZQ~]?Q?JPN")

#: A unit of up to eight characters repeated back to back. Beam-1 decoding of an
#: over-long segment collapses into this (`完全; ` x44, `school` x30). The SOURCE
#: is measured the same way, because a source table legitimately repeats and a
#: faithful translation of it must be allowed to.
_REPEAT = re.compile(r"(.{1,8}?)\1{7,}")

#: Below this share of protected spans surviving, the passage has lost the
#: grammar it was explaining. Held off 1.0 because a translation may legitimately
#: fold a repeated quotation into one mention.
_MAX_LOST_SPAN_SHARE = 0.2

#: A translation this much shorter than its source stopped early. Chinese is
#: denser than English -- the healthy ratio across this corpus runs 0.21 to 0.94,
#: with a 0.28 median -- so 0.12 is well clear of a complete short translation.
_MIN_LENGTH_RATIO = 0.12
_MIN_LENGTH_CHECK_CHARS = 60


def protected_spans(text: str) -> tuple[str, ...]:
    """The runs of `text` a translation has to carry through unchanged."""
    if not isinstance(text, str) or not text:
        return ()
    spans: list[str] = []
    for pattern in (_URL, _TAG):
        spans.extend(pattern.findall(text))
    # A one-character Japanese run (`と`, `が`) is too common to be evidence: it
    # survives inside an unrelated word and would mask a real loss.
    spans.extend(run for run in _JAPANESE_RUN.findall(text) if len(run) >= 2)
    return tuple(dict.fromkeys(spans))


_PROTECTED = re.compile(
    r"<[^>\n]*>|https?://\S+|`[^`\n]*`|\{\{[^}\n]*\}\}|\{[^}\n]*\}"
    r"|\[[^\]\n]{1,240}\]\([^\)\n]*\)"
    r"|[぀-ヿ㐀-䶿一-鿿！-￯"
    r"。、，．：；！？「」『』（）［］【】〔〕〈〉《》…〜～※]+"
)


def split_protected(text: str) -> tuple[tuple[bool, str], ...]:
    """Cut `text` into `(translate, piece)` pairs along its protected runs.

    The fix for the sentinel class of defect, applied at the point where it was
    created. Substituting `ZXQJPN00001Q` for a protected run and translating the
    result asks a subword NMT model to carry an invented token through decoding
    unchanged, which it will not reliably do -- it re-spells, splits and
    transliterates it, and the exact-string restore then leaves the debris in
    place. Handing the model only the pieces BETWEEN the protected runs removes
    the requirement instead of restating it: the Japanese never enters the model,
    so there is nothing for it to mangle and nothing to restore.

    The cost is that a translated piece no longer sees the Japanese it sits
    beside. That is the right trade for a grammar dictionary, where losing the
    pattern being explained destroys the entry and a slightly flatter sentence
    does not.
    """
    if not isinstance(text, str) or not text:
        return ()
    pieces: list[tuple[bool, str]] = []
    cursor = 0
    for match in _PROTECTED.finditer(text):
        if match.start() > cursor:
            pieces.append((True, text[cursor : match.start()]))
        pieces.append((False, match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        pieces.append((True, text[cursor:]))
    return tuple(pieces)


def _longest_repeat_run(text: str) -> int:
    """How many times the most-repeated adjacent unit repeats."""
    longest = 0
    for match in _REPEAT.finditer(text):
        unit = len(match.group(1))
        if unit:
            longest = max(longest, len(match.group(0)) // unit)
    return longest


def degradation(source: str, translation: str) -> str | None:
    """Why `translation` is unusable as a translation of `source`, or None.

    Returns a short machine-readable reason so a caller can report WHICH promise
    was broken instead of only that one was.
    """
    if not isinstance(translation, str) or not translation.strip():
        return None
    if _SENTINEL_DEBRIS.search(translation):
        return "placeholder-leak"
    if not isinstance(source, str) or not source.strip():
        return None
    spans = protected_spans(source)
    if spans:
        lost = sum(1 for span in spans if span not in translation)
        if lost / len(spans) > _MAX_LOST_SPAN_SHARE:
            return "lost-source-spans"
    translated_run = _longest_repeat_run(translation)
    if translated_run >= 8 and translated_run >= 3 * _longest_repeat_run(source):
        return "runaway-repetition"
    if (
        len(source) >= _MIN_LENGTH_CHECK_CHARS
        and len(translation) < _MIN_LENGTH_RATIO * len(source)
    ):
        return "truncated"
    return None


def is_degraded(source: str, translation: str) -> bool:
    """True when `translation` must not be shown to a reader."""
    return degradation(source, translation) is not None


def has_placeholder_debris(translation: str) -> bool:
    """True when a mangled protection sentinel survives in the output.

    The one check that needs no source text, so it can be run over a translation
    cache whose keys are digests and whose originals are therefore unrecoverable.
    """
    return isinstance(translation, str) and bool(_SENTINEL_DEBRIS.search(translation))
