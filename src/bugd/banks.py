"""Yomitan structured-content bank generation.

This is the ONLY stage that knows about Yomitan's dictionary format. It turns
`MergedEntry` records into `term_bank_N.json` entries, `tag_bank_1.json`, and
`index.json`.

Card contract (frozen by the card-design card, enforced by tests):

* one canonical surface — a single structured term entry per grammar point;
* compact above the fold: expression, meaning, structure, JLPT;
* progressive disclosure — complete example sentences, per-source explanations,
  nuance, notes, and provenance live in native closed `details` sections;
* per-source attribution visible on every contributed section;
* AI-generated source fields, if rendered at all, only inside an explicitly
  labelled disclosure — never above the fold and never as unlabelled fact.

Nothing here may invent content: no generated meanings, mnemonics, etymology, or
machine translation.
"""

from __future__ import annotations

import re

from . import (
    DICTIONARY_AUTHOR,
    DICTIONARY_DOWNLOAD_URL,
    DICTIONARY_FORMAT,
    DICTIONARY_INDEX_URL,
    DICTIONARY_TITLE,
    DICTIONARY_URL,
    TERM_BANK_SHARD,
)
from .jsonio import MalformedPayload
from .merge import MergedEntry
from .model import GrammarPoint
from .dialects import prose_to_html
from .richtext import html_to_content, html_to_text

#: Marker attributes for this dictionary's own CSS.
#:
#: `StructuredContentGenerator._setElementDataset` capitalizes the first
#: character of every `data` key and prefixes `sc`, so a key of `grammarCard`
#: becomes `element.dataset.scGrammarCard`, i.e. the DOM attribute
#: `data-sc-grammar-card`. A key of `sc` would instead render as `data-sc-sc`,
#: which is why role names are spelled as the camelCase key here and matched as
#: the hyphenated attribute in `bugd.styles`.
CARD_ROOT_ROLE = "grammarCard"

#: Compact-card budget. Above the fold the card shows the single best meaning and
#: construction; the complete per-source substance lives in disclosures. These
#: bounds are a rendering decision only — nothing is dropped from the archive.
#:
#: `meaning` is a headline, not an essay. DoJG ships senses joined by `;` (up to
#: 375 chars, occasionally with an `---` separator and inlined examples), which
#: would push the disclosures off the first screen of the popup. The compact line
#: keeps whole `;`-delimited senses up to this budget and the complete meaning
#: stays visible in that source's own disclosure.
COMPACT_MEANING_BUDGET = 88

#: A compact construction badge is only useful when it reads as one formula.
#: DoJG's `structure` field is a full markdown-ish table (median 251 chars, max
#: 2284, pipes and row breaks) describing several patterns at once; rendering it
#: in a one-line badge produced `あえて | Verb | | | あえて反対する | ...`. Sources whose
#: structure does not fit a single formula are shown as a table-free
#: construction disclosure instead of a mangled badge.
COMPACT_STRUCTURE_BUDGET = 48

#: Example sentences rendered inside the (closed) Examples disclosure per source.
#: The tail is preserved: sources contribute up to 24 sentences for one point and
#: a scrolling popup is worse than a bounded, readable list.
EXAMPLES_PER_SOURCE = 6

#: One disclosure per contributing SOURCE, not per source record. Real corpora
#: contribute many records to one lookup form (`ない` has 25), and 25 stacked
#: summaries with repeated identical labels is not a readable card.
SENSES_PER_SOURCE = 4

#: Per-source explanation language, used to order the per-source disclosures on a
#: card: English-explaining dictionaries first, then monolingual Japanese ones.
#: A learner reading in English wants the English sources up top; the Japanese
#: monolingual sources follow for depth. Keyed on `Extractor.name` (stable), and
#: DECLARED rather than re-derived per entry so the ordering is deterministic and
#: the build stays byte-reproducible. Verified against the extracted corpus:
#: bunpro/dojg/donna_toki/imabi/yokubi explain in English; the rest are Japanese.
_SOURCE_EXPLANATION_LANG: dict[str, str] = {
    "bunpro": "en",
    "dojg": "en",
    "donna_toki": "en",
    "imabi": "en",
    "yokubi": "en",
    "bunpou": "ja",
    "edewakaru": "ja",
    "nihongo_net": "ja",
    "nihongo_no_sensei": "ja",
    "ninjal_bunkei": "ja",
}

#: Sort rank for a source's disclosure: English (0) before Japanese (1); an
#: unknown/new source sorts after both (2) rather than silently jumping the
#: English block, so adding a source without classifying it is visible, not
#: wrong. Ties are broken by the source's own contribution order (stable sort).
_SOURCE_LANG_RANK = {"en": 0, "ja": 1}


#: Code-point ranges that make a string Japanese for language-tagging purposes:
#: Hiragana, Katakana, CJK punctuation/iteration marks, halfwidth kana, and the
#: CJK Unified Ideographs blocks (including the extensions this corpus can carry).
_JAPANESE_RANGES = (
    (0x3000, 0x303F),  # CJK symbols and punctuation (〜 、 。 〔 〕 ・)
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana phonetic extensions
    (0xFF00, 0xFFEF),  # Halfwidth/fullwidth forms (Ａ Ｎ Ｖ ＋ ＝)
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x20000, 0x3FFFF),  # Supplementary ideographic plane (extensions B..)
)


def _is_japanese_text(text: str) -> bool:
    """True when a string contains Japanese script.

    Source `meaning` fields are NOT uniformly English: DoJG and どんなとき publish
    English glosses, while 絵でわかる日本語, 日本語NET, and 毎日のんびり日本語教師 publish
    Japanese ones (2963 of 4181 non-empty meanings contain Japanese). Hard-coding
    `lang="en"` on the compact line would mis-declare the majority of cards to
    screen readers and give the browser the wrong font and line-breaking rules,
    so the tag is derived from the text itself.
    """
    for character in text:
        codepoint = ord(character)
        for low, high in _JAPANESE_RANGES:
            if low <= codepoint <= high:
                return True
    return False


def _lang_of(text: str) -> str:
    """The BCP-47 tag to declare for a source string."""
    return "ja" if _is_japanese_text(text) else "en"


#: Kana. The presence of kana is what distinguishes Japanese from Chinese here:
#: both scripts use Han, and Han alone sits inside `_JAPANESE_RANGES`.
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9d]")

#: A run of Latin letters, enough to mark an English gloss.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")

#: Every Latin letter, and every kana/Han character, for a DOMINANCE test.
#:
#: `_lang_of` answers "does this contain Japanese at all", which is the right
#: question for declaring a field's language but the wrong one for a mixed line.
#: A translation like `２）Generally, くらい becomes ぐらい…` quotes the Japanese it
#: is explaining, so it contains kana and `_lang_of` calls it `ja` -- which is why
#: 1,412 English lines rendered identically to the Japanese beside them.
_LATIN_CHARS = re.compile(r"[A-Za-z]")
_JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: A line needs this many Latin letters before it can be called a translation, so
#: a Japanese line quoting a short Latin token (`N1`, `イA`, `A：`) is never
#: misread as English.
_TRANSLATION_MIN_LATIN = 8


def _is_latin_dominant(text: str) -> bool:
    """Is this line predominantly Latin script, i.e. a translation?

    Requires BOTH an absolute floor and a clear majority over the Japanese in the
    same line: a Japanese explanation may quote an English word or a JLPT level
    without becoming a translation, and a translation habitually quotes the
    Japanese pattern it explains.
    """
    latin = len(_LATIN_CHARS.findall(text))
    if latin < _TRANSLATION_MIN_LATIN:
        return False
    return latin > 2 * len(_JA_CHARS.findall(text))

#: The Chinese ellipsis/placeholder these glosses use (`太…`, `与…相同`).
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: Chinese punctuation: the gloss slot placeholder `…` and the enumeration comma
#: `，`. Japanese uses `〜` and `、` respectively.
_CHINESE_MARKS = re.compile(r"[\uff0c\u2026]")

#: A speaker label opening the line (`母：`, `A:`). Dialogue, not a gloss.
_SPEAKER_PREFIX = re.compile(r"^[^：:\s]{1,4}[：:]")


def _is_chinese_gloss(text: str) -> bool:
    """True when a source gloss is Chinese rather than Japanese or English.

    毎日のんびり日本語教師 publishes a Chinese translation column and its extractor
    already routes those lines to `provenance["meaningZh"]` -- but its detector's
    false negatives were still reaching the card: 487 of 1,990 compact meaning
    lines and 124 of 718 sense labels rendered as Chinese gloss lists, which the
    UGD-14 round-8 visual gate reported as unreadable headings
    (`…左右 大概… …多 与…相同 和…一样`). Because Han sits inside `_JAPANESE_RANGES`
    they were additionally declared `lang="ja"`.

    That producer-specific detector has been fixed at its own layer. This is the
    card's own defence in depth, and it uses the same evidence: in a kana-free,
    Latin-free line, Han plus the Chinese `…` slot placeholder or the Chinese
    enumeration comma `，` means Chinese. Japanese glosses in this corpus use `〜`
    for the slot and `、` for enumeration. An all-shared-Han line with no Chinese
    mark (`以前`, `五段動詞`, `程度`) is treated as Japanese: under-claiming is safer
    than mislabelling Japanese as Chinese.
    """
    if not text:
        return False
    if _KANA.search(text) or _LATIN_WORD.search(text):
        return False
    if not _HAN.search(text):
        return False
    # A dialogue turn is not a gloss: `母：…` is a speaker trailing off.
    if _SPEAKER_PREFIX.match(text):
        return False
    return bool(_CHINESE_MARKS.search(text))


def _text(value: object) -> str:
    """Collapse a source scalar to a single-line string, or '' when absent."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return html_to_text(value)


def _prose(value: object, point: GrammarPoint | None = None) -> object | None:
    """Convert a source prose field to structured content, or None when empty.

    `point` supplies the producer whose notation the field is written in. Markup is
    part of the content — a table is a table because the author laid it out as one —
    so the source's dialect is resolved to HTML first and the shared converter then
    renders it. A source with no declared dialect (nine of the ten) passes through
    untouched; see `bugd.dialects`.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    if point is not None:
        value = prose_to_html(value, source=point.source)
    return html_to_content(value)


def _readable_meaning(value: object) -> str:
    """The first line of a source `meaning` this dictionary can actually display.

    毎日のんびり日本語教師 writes its meaning field as a Chinese gloss list, sometimes
    followed by a Japanese one:

        取决于…
        根据…
        ～によっては
        ～次第で（は）

    Taking the field verbatim put the Chinese lines on the card's primary line
    (487 of 1,990 compact meanings) and in its sense headings (124 of 718), which
    the round-8 visual gate reported as garbled unreadable headings. Skipping the
    Chinese lines keeps the SOURCE'S OWN words -- nothing is translated,
    reordered, or invented -- and returns '' when every line is Chinese so the
    caller can fall back to another field rather than print an empty heading.

    Lines are split from the RAW value, before `_text`: that helper collapses a
    multi-line field into one line, which would hide the per-line boundary this
    selection depends on.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    for raw_line in value.split("\n"):
        line = _text(raw_line).strip()
        if line and not _is_chinese_gloss(line):
            return line
    return ""


def _span(role: str, content: object, *, lang: str | None = None) -> dict:
    node: dict = {"tag": "span", "data": {role: ""}, "content": content}
    if lang is not None:
        node["lang"] = lang
    return node


#: A highlight this long or shorter is held on one line (`white-space: nowrap`),
#: so the grammar point the reader is looking for can never be split mid-word.
#: Above it, containment wins: a producer occasionally marks a WHOLE sentence,
#: which cannot be held unbroken in a 320px popup without overflowing it.
#: Measured over the packaged banks: 6,079 spans, 6,072 at or below this bound
#: and 7 above (20-60 chars).
HIGHLIGHT_NOWRAP_BUDGET = 18


def _highlight_sentence(sentence: str, highlights: tuple[str, ...] | list[str]) -> object:
    """Render a Japanese example, marking the grammar point where the source did.

    Only substrings the SOURCE marked are highlighted — nothing is inferred. The
    longest marker is applied first so a source shipping both `があっての` and
    `あっての` highlights the larger span rather than nesting the smaller one.

    A sentence-length marker additionally carries `hl-long`, which restores
    wrapping: CSS cannot measure text length, so the length decision is made here
    where it is known.
    """
    text = sentence
    if not text:
        return ""
    # Longest-first so a larger span wins over a nested smaller one; the string
    # itself is the deterministic tiebreak, because iterating the deduped set
    # otherwise leaves equal-length markers in arbitrary (hash) order and the
    # build stops being byte-reproducible.
    markers = sorted(
        {h for h in (highlights or ()) if isinstance(h, str) and h.strip()},
        key=lambda h: (-len(h), h),
    )
    if not markers:
        return text

    # Split on the source's markers, keeping them, without regex escaping games.
    parts: list[object] = [text]
    for marker in markers:
        nxt: list[object] = []
        for part in parts:
            if not isinstance(part, str):
                nxt.append(part)
                continue
            pieces = part.split(marker)
            for position, piece in enumerate(pieces):
                if position:
                    node = _span("hl", marker)
                    if len(marker) > HIGHLIGHT_NOWRAP_BUDGET:
                        node["data"]["hlLong"] = ""
                    nxt.append(node)
                if piece:
                    nxt.append(piece)
        parts = nxt
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0]
    return parts


def _headline(meaning: str) -> str:
    """Shorten a source meaning to a compact headline on a sense boundary.

    Sources join senses with `;` and DoJG sometimes appends an `---` rule plus
    inlined examples. Cutting mid-word would misrepresent the source, so this
    keeps whole `;`-delimited senses while they fit the budget and marks an
    elision with an ellipsis. The complete meaning is always still rendered in
    that source's own disclosure, so nothing is lost.
    """
    text = meaning.split("---")[0].strip(" ;\u3000")
    if len(text) <= COMPACT_MEANING_BUDGET:
        return text
    senses = [s.strip() for s in text.split(";") if s.strip()]
    kept: list[str] = []
    for sense in senses:
        candidate = "; ".join([*kept, sense])
        if kept and len(candidate) > COMPACT_MEANING_BUDGET:
            break
        kept.append(sense)
    headline = "; ".join(kept)
    if len(headline) > COMPACT_MEANING_BUDGET:
        # A single sense longer than the whole budget: cut on a word boundary.
        headline = headline[:COMPACT_MEANING_BUDGET].rsplit(" ", 1)[0]
    return f"{headline}…" if headline != text else headline


def _is_badge_structure(structure: str) -> bool:
    """True when a construction reads as ONE formula fit for a compact badge.

    A source's `structure` is only badge-worthy when it is short, free of table
    punctuation, and describes a SINGLE pattern. A multi-pattern structure fails
    the last test and is shown as a Construction disclosure instead.

    Checking only for `|` was not enough. Three of the four sources separate their
    patterns with a NEWLINE rather than a pipe, and `_text` collapses whitespace,
    so `名詞＋ほど＋名詞＋は～ない / 名詞＋くらい＋… / 名詞＋ぐらい＋…` arrived as one
    space-joined line that fit the budget and was badged. Round 13 filed exactly
    that as a must-fix: "three grammar-pattern variants (ほど/くらい/ぐらい) are
    concatenated on a single line separated only by spaces, creating a dense
    run-on segment". Measured over the extracted corpus: 2,547 multi-line
    structures (nihongo_no_sensei 1,197, edewakaru 544, dojg 475,
    nihongo_net 331), so this was corpus-wide rather than one entry.
    """
    if not structure or len(structure) > COMPACT_STRUCTURE_BUDGET:
        return False
    return "|" not in structure


def _structure_pattern_lines(point: GrammarPoint) -> list[str]:
    """The source's construction patterns, one per line, in source order."""
    raw = point.structure if isinstance(point.structure, str) else ""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _has_badge_structure(point: GrammarPoint) -> bool:
    """Is this source's construction renderable as one compact badge?"""
    structure = _text(point.structure)
    if not structure or not _is_badge_structure(structure):
        return False
    return len(_structure_pattern_lines(point)) <= 1


def _construction_section(point: GrammarPoint) -> dict | None:
    """A source's full construction table, rendered as real structured content.

    Used for sources whose `structure` describes several patterns -- DoJG in a
    pipe-delimited table, and three other sources one per LINE. Rows become list
    items so the popup shows the source's own patterns instead of a wall of `|`
    characters or a space-joined run-on line.

    Each cell is CONVERTED, not pasted. Sources keep inline markup in `structure`
    -- NINJAL marks the ending a conjugation drops with `<s>` in 526 places across
    168 cards (`i-A<s>い</s>＋かったあまり`) -- and building the row from the raw line
    put the literal characters `<s>` and `</s>` on the card in 107 of them while
    the marking they carry was lost. Conversion renders the omission as a real
    struck-through span, which is the whole point of the notation.
    """
    structure = _text(point.structure)
    if not structure or _has_badge_structure(point):
        return None
    raw = point.structure if isinstance(point.structure, str) else ""
    rows: list[dict] = []
    for line in raw.splitlines():
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        content: list[object] = []
        for cell in cells:
            converted = html_to_content(cell)
            if converted is None:
                continue
            if content:
                # Separator is appended only once a rendered cell is known to
                # follow, so a cell that converts to nothing cannot leave a
                # dangling ` · ` at the end of the row.
                content.append(" · ")
            content.extend(converted if isinstance(converted, list) else [converted])
        if not content:
            continue
        rows.append(
            {
                "tag": "li",
                "data": {"pattern": ""},
                "content": content[0] if len(content) == 1 else content,
            }
        )
    if not rows:
        return None
    return {"tag": "ul", "data": {"patterns": ""}, "content": rows}


#: A run of two or more wide spaces. DoJG uses a double EM SPACE (U+2003) to
#: separate the turns of a two-speaker example (`A:...\u2003\u2003B:...`) in 31
#: examples. Rendered inline it reads as a broken justification gap, so the turn
#: boundary becomes a real line break instead.
_TURN_SEPARATOR = re.compile(r"[\u2000-\u200a\u3000]{2,}")

#: The speaker labels the corpus actually uses. Two kinds appear: a Latin letter
#: with an optional index (`A：`, `Ｂ：`, `Ｓ２：`) and a ROLE NOUN (`母：`, `店員：`,
#: `上司：`). The role nouns are enumerated rather than matched as "one to four
#: kana/kanji", because an open-ended class splits in the wrong place: the corpus
#: contains `夫：…すまん妻：もっと…` and `娘：…父：…そうか娘：…`, where a generic
#: `{1,4}` label anchored on the preceding `…` consumes the tail of the previous
#: turn (`すまん妻`, `そうか娘`) and moves those words into the next speaker's line.
#: Measured over the corpus, the enumeration below reaches 806 of the 813 fields
#: a generic class reaches, and every one of the 7 it declines is a mis-split.
_SPEAKER_ROLES = (
    "お母さん", "母親", "彼女", "彼氏", "同僚", "部下", "上司", "社員", "店員", "店長",
    "学生", "先生", "医者", "患者", "観客", "歌手", "犯人", "警察", "息子", "娘",
    "母", "父", "夫", "妻", "兄", "弟", "姉", "妹", "客", "孫", "祖母", "祖父",
)

#: A role may carry a Latin index when a scene has several of the same role
#: (`客A：ハンバーガーにします客B：…`). The indexed forms are listed FIRST so `客A`
#: wins over a bare `客`: Python's alternation is leftmost-first, not longest, so
#: putting the bare roles first split between `客` and `A：` and orphaned the role
#: onto its own line.
_SPEAKER_LABEL = (
    "(?:"
    + "|".join(
        f"{role}[A-Za-zＡ-Ｚ0-9０-９]"
        for role in sorted(_SPEAKER_ROLES, key=len, reverse=True)
    )
    + "|"
    + "|".join(sorted(_SPEAKER_ROLES, key=len, reverse=True))
    + r"|[A-Za-zＡ-Ｚａ-ｚ][0-9０-９]?)"
)

#: A speaker label opening a NEW turn. edewakaru, DoJG and donna_toki write
#: dialogue as `Ａ：…Ｂ：…` with no separator at all, so the wide-space rule above
#: misses them and the turns render as one run-on line. Measured over the corpus:
#: 806 example fields across 352 records in 3 sources (edewakaru 558, dojg 195,
#: donna_toki 53).
#:
#: A break is inserted only when the label is preceded by sentence-final
#: punctuation or a closing bracket -- i.e. the previous turn actually ended --
#: and never at the start of a fragment, so the first speaker gets no leading
#: break. That keeps ordinary prose (`ratio A:B`, a gloss ending in `B：`) intact.
#:
#: The WAVE DASH (U+301C) and FULLWIDTH TILDE (U+FF5E) count as turn-final too.
#: This corpus's casual dialogue routinely lengthens the last vowel instead of
#: closing with `。`/`！` (`娘：ただいま〜母：いいところに帰ってきたわね`), and round 8
#: filed two of those as run-ons. `〜` is also the corpus's grammar-pattern
#: placeholder (`〜くらい`, `〜ほど〜はない`), so it is only accepted in the same
#: position as any other turn-final mark -- immediately before a speaker label
#: bearing a colon. Measured over the corpus that matches 46 boundaries, all in
#: edewakaru, and every one is a real turn change.
_SPEAKER_TURN = re.compile(
    r"(?<=[。．？！?!、」』）\)\u2026\u3001\u301c\uff5e])[\u2000-\u200a\u3000\u00a0 ]*"
    rf"(?={_SPEAKER_LABEL})(?=[^：:]{{1,5}}[：:])"
)

#: The run OPENS with a speaker label, i.e. it is a transcribed dialogue.
#:
#: A producer prefix is allowed before the label because edewakaru writes
#: `［例］ A：…B：…` and `（デパートで）客：…` -- a bracketed section marker or a stage
#: direction, not part of the dialogue. Only brackets and spaces may precede it,
#: so ordinary prose that merely contains a colon later is not misread as a
#: transcript.
_OPENS_WITH_SPEAKER = re.compile(
    rf"^[\u2000-\u200a\u3000\s]*"
    rf"(?:[［\[（(【「][^］\]）)】」]{{0,20}}[］\]）)】」][\u2000-\u200a\u3000\s]*)*"
    rf"(?:{_SPEAKER_LABEL})[：:]"
)

#: Any later speaker label, with no requirement on what precedes it.
#:
#: Punctuation anchoring cannot finish the job. Measured over the corpus, 35
#: distinct characters precede a second speaker label, and the long tail is
#: sentence-final PARTICLES with no punctuation at all -- `よ` (60), `ね` (58),
#: `い` (47), `の` (26), `わ` (12), `て`/`す` (10), `し` (9), `た` (7), `か` (6) --
#: as in `A：今日はすごく寒いねB：うん。雪が降るかもね`. Anchoring on "any kana" would
#: fire throughout ordinary prose.
#:
#: The LINE supplies the missing evidence instead: when it opens with a speaker
#: label it is a transcript, and inside a transcript a later label is a turn
#: change. Applied only under `_OPENS_WITH_SPEAKER`, this splits 1,080 dialogue
#: lines with 2 turns in 925 of them, and the only mis-splits it produced before
#: `_SPEAKER_LABEL` was made longest-first were the three `客A/客B/客C` rows.
_LATER_SPEAKER = re.compile(rf"(?<=.)(?={_SPEAKER_LABEL}[：:])")

#: A well-formed turn: the piece a split produced must itself begin with a
#: complete speaker label. Used to REJECT a split that landed inside one.
_STARTS_WITH_SPEAKER = re.compile(rf"^{_SPEAKER_LABEL}[：:]")


def _mark_later_speakers(text: str) -> str:
    """Insert a boundary marker before each later speaker label in a transcript.

    `re.sub` cannot do this directly. In `客A：…客B：…` BOTH offsets match -- before
    `客A` and before `A` -- because a bare role and an indexed role are both valid
    labels, and a zero-width `sub` takes every match, which orphans `客` onto the
    previous line. So candidate offsets are collected and the EARLIEST wins,
    consuming the whole `客A` label; any later offset inside a label already
    claimed is discarded.

    Scanning starts AFTER the run's opening label, so the first speaker never
    gets a leading break. Without that, `［例］ A：…B：…` marked before `A：` too and
    the leading `［例］` was torn onto its own line.
    """
    opening = _OPENS_WITH_SPEAKER.match(text)
    start_at = opening.end() if opening else 0
    marks: list[int] = []
    for match in _LATER_SPEAKER.finditer(text, start_at):
        start = match.start()
        if marks and start <= marks[-1] + _label_length(text, marks[-1]):
            continue
        marks.append(start)
    if not marks:
        return text
    out: list[str] = []
    previous = 0
    for start in marks:
        out.append(text[previous:start])
        previous = start
    out.append(text[previous:])
    return "\x00".join(out)


def _label_length(text: str, start: int) -> int:
    """Character length of the speaker label beginning at `start`."""
    match = _STARTS_WITH_SPEAKER.match(text, start)
    return (match.end() - start) if match else 1


def _split_dialogue_turns(content: object) -> object:
    """Turn a source's turn separator into a `br`.

    Handles all three forms the corpus uses: a run of wide spaces (DoJG), a
    speaker label following the end of the previous turn (edewakaru, donna_toki),
    and -- when the text is recognisably a transcript -- a label following a bare
    sentence-final particle with no punctuation at all.

    Applied AFTER highlighting so a marker spanning the separator is unaffected,
    and only to string fragments, so highlight/ruby nodes pass through intact.
    The transcript test reads the JOINED text, because highlighting has already
    split the sentence into several fragments and the opening label may sit in a
    different fragment from a later one.
    """
    parts: list[object] = content if isinstance(content, list) else [content]
    joined = "".join(part for part in parts if isinstance(part, str))
    transcript = bool(_OPENS_WITH_SPEAKER.match(joined))
    out: list[object] = []
    for index, part in enumerate(parts):
        if not isinstance(part, str):
            out.append(part)
            continue
        # Normalise the wide-space form to the same boundary, then split once, so
        # `A:…\u2003\u2003B:…` yields ONE break rather than two.
        marked = _TURN_SEPARATOR.sub("\x00", part)
        marked = _SPEAKER_TURN.sub("\x00", marked)
        if transcript:
            # The producer's stage direction ends in `）`, which the punctuation
            # rule above reads as turn-final -- so `（デパートで）客：…` split the
            # direction onto its own line. Drop a marker that falls inside the
            # run's opening prefix; the first speaker never opens a new turn.
            opening = _OPENS_WITH_SPEAKER.match(marked.replace("\x00", ""))
            if index == 0 and opening:
                head, sep, tail = marked.partition("\x00")
                if sep and len(head) < opening.end():
                    marked = head + tail
            # A highlight node splits the sentence, so a fragment AFTER the first
            # one can begin with the next speaker's label:
            #   ["A：…教え", <hl てください>, "B：いいですよ"]
            # Its label is at offset 0 of its own fragment, which the "later
            # label" rule cannot see. Treat any non-first fragment as continuing
            # the run, so an opening label there is still a turn change.
            offset = 0 if index == 0 else 1
            prefixed = ("\ufffd" + marked) if offset else marked
            prefixed = _mark_later_speakers(prefixed)
            marked = prefixed[offset:] if offset else prefixed
            # Collapse a boundary the punctuation rule and the transcript rule
            # both found, so one turn change never yields two breaks.
            marked = re.sub("\x00{2,}", "\x00", marked)
            # Reject a split that landed INSIDE a word rather than before a
            # label: `夫：…すまん妻：…` breaks before `妻：` where the real turn
            # boundary is mid-word. A well-formed turn starts with a complete
            # label, so a piece that does not is re-joined to the one before it.
            fragments = marked.split("\x00")
            rebuilt = [fragments[0]]
            for fragment in fragments[1:]:
                if _STARTS_WITH_SPEAKER.match(fragment):
                    rebuilt.append(fragment)
                else:
                    rebuilt[-1] += fragment
            marked = "\x00".join(rebuilt)
            # A leading marker means this fragment OPENS a new turn; emit the
            # break before the fragment instead of an empty first piece.
            if marked.startswith("\x00"):
                out.append({"tag": "br"})
                marked = marked[1:]
        pieces = [p for p in marked.split("\x00")]
        if len(pieces) == 1:
            # `marked` rather than `part`: a leading turn marker may already have
            # been consumed above, and the rest of the fragment is unchanged.
            out.append(pieces[0])
            continue
        for position, piece in enumerate(pieces):
            if position:
                out.append({"tag": "br"})
            if piece:
                out.append(piece)
    if not out:
        return content
    return out[0] if len(out) == 1 else out


#: A cell delimiter from a source that writes its construction table as text.
#: DoJG's `structure` fields look like `(i) A: | Sentence1 | |`, where `A:` is a
#: TABLE COLUMN HEADER, not a speaker. A turn break there would split a table row
#: mid-notation, so a line carrying pipe delimiters is never treated as dialogue.
_TABLE_LINE = re.compile(r"\|")


def _split_dialogue_prose(content: object) -> object:
    """Apply the turn splitter to prose, one line at a time.

    The splitter normally only runs on example sentences, but two sources wrote a
    two-speaker exchange inside an explanation/meaning field instead, and it
    shipped as a run-on line: `A：あした、晴れたらいいな。B：そうですね、…`.
    Measured over the corpus this is 2 real cases plus 2 DoJG table rows, which
    `_TABLE_LINE` excludes.

    Prose already carries the producer's own newlines (see `_paragraphs`), so each
    line is considered independently and a line without a turn boundary is
    returned unchanged.
    """
    if isinstance(content, str):
        if _TABLE_LINE.search(content):
            return content
        return _split_dialogue_turns(content)
    if isinstance(content, list):
        out: list[object] = []
        for item in content:
            split = _split_dialogue_prose(item)
            if isinstance(split, list) and isinstance(item, str):
                out.extend(split)
            else:
                out.append(split)
        return out
    return content


#: The kana/kanji a new Japanese sentence starts with. Hiragana, katakana, the
#: CJK ideograph block and its compatibility ideographs. A `。`/`！`/`？` followed
#: by one of these opens a fresh sentence; followed by anything else (a space, an
#: ASCII/fullwidth paren opening an English or Chinese gloss, a digit, `→`, the
#: end of the field) it does not, and no break is inserted.
_SENTENCE_START = (
    "\u3040-\u309f"  # hiragana
    "\u30a0-\u30ff"  # katakana
    "\u3400-\u9fff"  # CJK unified ideographs
    "\uf900-\ufaff"  # CJK compatibility ideographs
)

#: A sentence boundary WITHIN a single example: a sentence-final mark immediately
#: followed by the start of a new Japanese sentence. The lookbehind keeps the mark
#: attached to the sentence it closes; the lookahead requires a Japanese
#: sentence-start so a `。` before an English/Chinese translation, before `→`, or
#: at the very end of the field is never a boundary.
_EXAMPLE_SENTENCE_BOUNDARY = re.compile(
    rf"(?<=[。！？])(?=[{_SENTENCE_START}])"
)

#: A Japanese sentence-start on its own, for testing the leading character of the
#: NEXT fragment when a boundary fell at a fragment edge.
_EXAMPLE_SENTENCE_HEAD = re.compile(rf"[{_SENTENCE_START}]")

#: Quote / gloss delimiters. A `。` INSIDE an open quotation (`「…。…」`, `『…。…』`)
#: is part of the quoted speech, not a boundary between two example sentences, so
#: a split is suppressed while any quote is open. The same suppression applies
#: inside a parenthetical (`（…）`, `(...)`) because sources append a translation
#: or aside there -- a Chinese gloss `（内容有误。非常抱歉。）` uses CJK punctuation
#: that would otherwise be mis-split into the surrounding Japanese. Depth is
#: tracked across highlight/ruby fragments because a quote can span a highlighted
#: span.
_QUOTE_OPEN = "「『（("
_QUOTE_CLOSE = "」』）)"


def _first_text_char(node: object) -> str:
    """The first leaf character under a node (or the string itself), or ``""``."""
    if isinstance(node, str):
        return node[:1]
    if isinstance(node, dict):
        return _first_text_char(node.get("content"))
    if isinstance(node, list):
        for item in node:
            char = _first_text_char(item)
            if char:
                return char
    return ""


def _split_example_sentences(content: object) -> object:
    """Break a multi-sentence example field onto separate lines.

    Mirrors `_split_dialogue_turns`, but for the declarative case: a single
    example string that packs several sentences (`…だよ。とっても辛いんだ。いつも…`)
    renders as one run-on line under the example's `white-space: pre-line` CSS.
    Each internal sentence boundary becomes a `br`, exactly as a dialogue turn
    boundary does, so the sentences stack as separate lines.

    Applied AFTER dialogue splitting and only to STRING fragments, so highlight
    and ruby nodes pass through untouched -- a boundary that would fall inside a
    highlighted span is therefore never emitted. A boundary that falls at a
    fragment EDGE (`…じゃん。` followed by a highlight span opening the next
    sentence) still breaks, because the `br` goes BETWEEN the fragments, not
    inside the node. Quote depth is carried across fragments so a `。` inside
    `「…」` or a `（…）` gloss is left intact. Deterministic.
    """
    parts: list[object] = content if isinstance(content, list) else [content]
    out: list[object] = []
    depth = 0
    #: Whether the last emitted character was a sentence-final mark sitting
    #: outside any quote -- i.e. a break is owed if the next fragment opens a new
    #: Japanese sentence.
    pending_boundary = False
    for part in parts:
        if not isinstance(part, str):
            # A highlight/ruby node passes through, but if the previous fragment
            # ended a sentence and this node opens a new one, break before it.
            if pending_boundary and _EXAMPLE_SENTENCE_HEAD.match(
                _first_text_char(part) or ""
            ):
                out.append({"tag": "br"})
            out.append(part)
            pending_boundary = False
            # A node can change quote depth (a highlight may carry `「`/`）`).
            for char in _node_text(part):
                if char in _QUOTE_OPEN:
                    depth += 1
                elif char in _QUOTE_CLOSE and depth:
                    depth -= 1
            continue
        pieces: list[str] = []
        buffer: list[str] = []
        index = 0
        length = len(part)
        # A boundary owed from the previous fragment: break before this string if
        # it opens a new Japanese sentence.
        if pending_boundary and _EXAMPLE_SENTENCE_HEAD.match(part):
            out.append({"tag": "br"})
        pending_boundary = False
        while index < length:
            char = part[index]
            buffer.append(char)
            if char in _QUOTE_OPEN:
                depth += 1
            elif char in _QUOTE_CLOSE and depth:
                depth -= 1
            if depth == 0 and char in "。！？":
                if index + 1 < length:
                    # A new Japanese sentence follows in THIS fragment: break here.
                    if _EXAMPLE_SENTENCE_BOUNDARY.match(part, index + 1):
                        pieces.append("".join(buffer))
                        buffer = []
                else:
                    # The mark ends the fragment: a break may be owed to whatever
                    # fragment comes next (a highlight span, the next string).
                    pending_boundary = True
            index += 1
        if buffer:
            pieces.append("".join(buffer))
        for position, piece in enumerate(pieces):
            if position:
                out.append({"tag": "br"})
            if piece:
                out.append(piece)
    if not out:
        return content
    return out[0] if len(out) == 1 else out


def _node_text(node: object) -> str:
    """All leaf characters under a node, for quote-depth tracking."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return _node_text(node.get("content"))
    if isinstance(node, list):
        return "".join(_node_text(item) for item in node)
    return ""


def _examples_section(point: GrammarPoint) -> dict | None:
    """A closed `details` block of this source's example sentences."""
    items: list[dict] = []
    for example in point.examples[:EXAMPLES_PER_SOURCE]:
        japanese = example.japanese
        if not isinstance(japanese, str) or not japanese.strip():
            continue
        body: list[object] = [
            {
                "tag": "span",
                "data": {"ja": ""},
                "lang": "ja",
                "content": _split_example_sentences(
                    _split_dialogue_turns(
                        _highlight_sentence(japanese, example.highlight)
                    )
                ),
            }
        ]
        english = _text(example.english)
        if english:
            body.append(_span("en", _split_dialogue_turns(english), lang="en"))
        items.append({"tag": "li", "data": {"example": ""}, "content": body})
    if not items:
        return None
    return {"tag": "ul", "data": {"examples": ""}, "content": items}


def _source_label(point: GrammarPoint) -> str:
    """The human-facing name of the source that contributed a statement."""
    label = point.provenance.get("sourceLabel") if isinstance(point.provenance, dict) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return point.source


#: The producer's own in-prose example marker. edewakaru and donna_toki write
#: their examples INSIDE the explanation field under an ［例］ / ［例文］ heading, so
#: those examples arrive as ordinary prose lines and received none of the example
#: styling that lifted `point.examples` items get. Round 9 filed that twice as a
#: must-fix ("example dialogue, derived-meaning arrows (→) and 【具体的な例】
#: annotations are not visually separated"). Measured over the corpus: 923 runs,
#: mean 4.4 lines.
_INLINE_EXAMPLE_MARKER = re.compile(r"^[\s\u3000]*[［\[]\s*例[^］\]]{0,6}[］\]][\s\u3000]*$")
#: A run of examples ends here.
#:
#: The producer separates the run from the prose after it with a BLANK line (886
#: of 923 runs) or a 【…】 section heading (36). But `bugd.richtext` collapses a
#: blank line to a single `\n` -- `_PARA_BREAK` writes one sentinel per run of
#: newlines -- so by the time `_paragraphs` sees the text the blank line is gone.
#: Round 10's screenshot caught the consequence: the tinted block swallowed the
#: closing explanatory sentence and the 【関連文法】 heading that followed it.
#:
#: So the run is ended on what survives into the node stream:
#:   * a 【…】 / 〈…〉 heading line, which is never example content;
#:   * a line that is neither an enumerated example nor a `→`/`＝` derivation and
#:     reads as an explanatory sentence -- the producer's closing remark.
_EXAMPLE_RUN_HEADING = re.compile(r"^[\s\u3000]*[【〈][^】〉]{1,24}[】〉][\s\u3000]*$")
#: A prose line that is structurally a SECTION HEADING rather than body text.
#:
#: The producers write their own subsection headings inline, fully bracketed on
#: their own line (`【関連文型】`, `［使い分け］`). Because every prose paragraph was
#: emitted as an identical `div`, those headings shipped at body weight and body
#: size. Round 9's visual gate filed that as the dominant systematic drag: 30 of
#: 92 images scored below 8, and their notes name it directly -- "the 【...】
#: bracket-style headers", "text hierarchy is mostly flat", "a dense wall of
#: Japanese text with little differentiation", "lacks visual hierarchy". Measured
#: over the packaged v23 banks: 917 `【…】` + 206 `［…］` heading lines against
#: 18,897 body lines, so this is a corpus-wide data-shape defect, not a
#: per-entry one.
#:
#: The pattern deliberately requires the WHOLE line to be one bracketed run: an
#: ordinary sentence that merely contains a bracketed quotation
#: (`「だって」は理由を…`) must stay body text.
_PROSE_HEADING = re.compile(r"^[\s\u3000]*[【〈［\[]([^】〉］\]]{1,24})[】〉］\]][\s\u3000]*$")
_EXAMPLE_ITEM = re.compile(r"^[\s\u3000]*(?:[①-⑳❶-❿]|[１-９][）)]|[→⇒➡＝=])")
#: A Japanese-script character, for the parallel-example-lead test below.
_JA_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
#: Minimum shared leading Japanese run marking two enumerator-less example lines
#: as parallel variants of one sentence. At two characters a shared opening
#: particle (`私は…` / `私も…`) would pair unrelated sentences.
_EXAMPLE_LEAD_MIN = 3
#: The producer's closing remark is a full sentence, and it is not an example line.
#: `。`/`！`/`？` covers most, but edewakaru habitually signs off with a polite verb
#: ending and an emoji instead of any punctuation at all
#: (`…しっかりと覚えておきましょう😊`), which is why the run over-ran in round 10.
#: Sentence-final polite endings are added as their own signal.
_EXAMPLE_RUN_CLOSER = re.compile(
    r"(?:[。！？]|ましょう|ください|です|ます|でしょう|ですね|ますね)"
    r"(?:[\s\u3000]*[\U0001F300-\U0001FAFF\u2600-\u27bf\ufe0f])*[\s\u3000]*$"
)


def _recurring_bracketed_labels(lines: list[str]) -> frozenset[str]:
    """Bracketed lines whose exact text RECURS inside one prose field.

    edewakaru does not use `【…】` only as a section heading. It also uses it as a
    per-example CLASSIFIER, repeating the same bracket after every specimen:

        ［例］
        このバッグは若い女の子の間で人気があるようだ
        【複数の人の中での状態】
        複数の人→若い女の子たち状態→人気
        OLの間で話題になっているカフェ
        【複数の人の中での状態】          <- the same label again
        ...

    Because `_ends_example_run` treated ANY bracketed heading as a boundary, the
    first specimen was boxed and every later one fell out as plain prose. Round 19
    filed that three separate times on 間 ("some get a shaded box with left rule
    while others are plain bold text ... for the same content role"), and
    `probe_role_sequence.py` confirmed the exact interleaving in the packaged
    bytes.

    Recurrence is the discriminator: a genuine section heading (`［説明］`,
    `［「〜ようだ」の形］`) appears ONCE in its field, while a per-example classifier
    repeats by construction. Measured over the whole source corpus, this reclaims
    31 example lines across 8 fields, all in edewakaru, and leaves the three
    entries `verify_round10_fixes.py` guards (ないものだ, ものだ, ようだ) untouched.
    """
    counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if _PROSE_HEADING.match(stripped) and not _INLINE_EXAMPLE_MARKER.match(stripped):
            counts[stripped] = counts.get(stripped, 0) + 1
    return frozenset(text for text, n in counts.items() if n > 1)


def _shares_example_lead(before: str, after: str) -> bool:
    """Do two adjacent enumerator-less example sentences share a leading stem?

    edewakaru writes some ［例］ runs as parallel variants of one sentence with no
    circled digit and no `→`, differing only in the slot around the grammar point:

        学校まで、どのくらいかかるの？
        学校まで、どれくらいかかるの？
        学校まで、何時間くらいかかるの？

    Every one ends in `？`, so `_EXAMPLE_RUN_CLOSER` reads the first as the
    producer's closing remark and drops the whole set out of the tinted box — the
    inconsistent-boxing defect the UGD-08c round filed on くらい (findings 6, 7). A
    real closing remark does not share a leading run with the next line, so a
    shared Japanese stem is the discriminator. Measured over edewakaru: 65 adjacent
    line pairs share a stem of three or more Japanese characters and none is a pair
    of prose remarks.

    The shared run must be Japanese script (not shared trailing punctuation) and at
    least three characters, so two unrelated sentences that merely open with the
    same particle do not pair.
    """
    shared = 0
    limit = min(len(before), len(after))
    while shared < limit and before[shared] == after[shared] and _JA_CHAR.match(before[shared]):
        shared += 1
    return shared >= _EXAMPLE_LEAD_MIN


def _ends_example_run(
    line: str,
    recurring: frozenset[str] = frozenset(),
    *,
    next_line: str = "",
    prev_line: str = "",
    is_first: bool = False,
) -> bool:
    """Does this prose line end the producer's ［例］ run?

    `recurring` carries the bracketed labels that repeat within the same field
    (see `_recurring_bracketed_labels`); those are per-example classifiers and
    must keep the run OPEN, or every specimen after the first loses its box.

    `is_first` marks the first content line after the ［例］ marker. The producer
    never opens a run with its closing remark, so that line is always a specimen
    even when it ends like a sentence (`差し支えなければ、お名前を教えていただけますか？`).
    Without this the enumerator-less runs closed on their own first line and the
    whole set fell out of the box (UGD-08c findings 6, 7; 69 runs / 62 fields).

    `next_line` lets a boundary look one line ahead so the run survives two shapes
    that continue it:

    * a `【…】` / `［…］` label immediately followed by another example item is a
      per-example annotation, not a section heading — it classifies the specimen
      above it and the run goes on (89 occurrences / 27 fields);
    * an enumerator-less example sentence followed by a parallel variant that
      shares its leading stem is one of a set, not a closing remark.
    """
    if is_first:
        return False
    if line.strip() in recurring:
        return False
    # A bracketed line that is immediately followed by another example item is a
    # per-example annotation (`【「持つ」は動詞】` before `②…`), not a section heading:
    # it classifies the specimen above it and the run continues. A real section
    # heading (`【関連文型】`) is followed by prose or by the field's end. This covers
    # both the 【…】/〈…〉 shape and any other bracketed heading.
    is_bracket_heading = bool(
        _EXAMPLE_RUN_HEADING.match(line)
        or (_PROSE_HEADING.match(line) and not _INLINE_EXAMPLE_MARKER.match(line))
    )
    if is_bracket_heading:
        if next_line and _EXAMPLE_ITEM.match(next_line):
            return False
        return True
    if _EXAMPLE_ITEM.match(line):
        return False
    # A dialogue turn is example content even though it ends like a sentence:
    # `妻：もう１０時よ！早く起きて！！` would otherwise close the run in the middle of
    # a two-speaker exchange and orphan the `夫：` reply outside the block.
    if _OPENS_WITH_SPEAKER.match(line):
        return False
    if _EXAMPLE_RUN_CLOSER.search(line):
        # A sentence-ending line that shares a leading stem with the previous or the
        # next line is one of a set of parallel example variants, not the closing
        # remark. The previous-line test keeps the LAST variant of a set boxed even
        # though the line after it is the real closing remark.
        stripped = line.strip()
        if next_line and _shares_example_lead(stripped, next_line.strip()):
            return False
        if prev_line and _shares_example_lead(stripped, prev_line.strip()):
            return False
        return True
    return False


#: A bracketed label at the START of a prose line, with content following it on
#: the SAME line (`【変化】日本語が話せなかった→…`, `【Ｎ４文法】～あげる／やる`).
#:
#: `_PROSE_HEADING` deliberately requires the whole line to be one bracketed run,
#: so it does not match these -- and reviewing a real-host v25 tile with my own
#: vision caught the consequence: `【具体的な例】涙が出る程度` still rendered at body
#: weight, indistinguishable from the sentences around it, which is the same flat
#: hierarchy round 9 complained about. Measured over the packaged v25 banks: 868
#: inline-prefix labels alongside 896 whole-line headings, so both shapes have to
#: be handled or the fix covers only half the corpus.
#:
#: Only the LEADING run is taken, and only when content follows it: a label is an
#: inline lead-in, not a heading, so it is emphasised in place rather than given
#: its own block.
_PROSE_INLINE_LABEL = re.compile(r"^[\s\u3000]*([【〈][^】〉]{1,24}[】〉])[\s\u3000]*(?=\S)")
#: An in-example line that DERIVES a meaning from the specimen above it
#: (`→とても疲れた`, `＝１時間悩んだあげくに、…`).
#:
#: A 7/10 tile review named this as the single biggest remaining improvement: the
#: specimen sentence and the `→` line paraphrasing it render identically, so a
#: derived meaning reads as a peer of the example rather than as something hanging
#: off it -- and because the gap within a set equals the gap between sets, uniform
#: spacing spends the cheapest grouping cue on nothing. Measured over the packaged
#: v26 banks: 1,416 derivation lines against 3,339 specimen lines.
_EXAMPLE_DERIVATION = re.compile(r"^[\s\u3000]*[→⇒➡＝=]")
#: An in-example line that ANNOTATES the set above it, opening with the producer's
#: own bracketed label (`【具体的な例】涙が出る程度`).
#:
#: It closes a set rather than opening one, which matters for where the grouping
#: gap goes. Reviewing the v27 real-host tile caught the consequence of ignoring
#: it: the gap landed above the annotation, detaching `【具体的な例】涙が出る程度`
#: from the ③ example it describes and gluing it to ④, so the reviewer read the
#: labels as "off by one" and the trailing annotation as an example-less orphan
#: block. Both complaints were one CSS adjacency bug, not a source-order defect --
#: the extracted source order is specimen, derivation, annotation, next specimen.
_EXAMPLE_ANNOTATION = re.compile(r"^[\s\u3000]*[【〈［\[][^】〉］\]]{1,24}[】〉］\]]")

#: A line that cannot OPEN a sentence: a bare connective particle, or a tail that
#: grammatically continues the clause before it.
#:
#: Defect 19. `_PROSE_HEADING` matches any wholly-bracketed short line, but
#: edewakaru also writes bracketed TERMS inline and wraps the sentence around
#: them, so one sentence arrives as several lines:
#:
#:     【複数の人の中での状態】     <- promoted to a section landmark
#:     や                          <- left as an orphaned connector
#:     【〜と〜の関係の中のこと】
#:     などを言いたい時に使います😊  <- orphaned sentence tail
#:
#: Round 24 filed exactly that ("only isolated connector words appear with large
#: surrounding empty space, as if list content is missing"). Raising landmark size
#: for defect 18 exposed the mismatch rather than causing it.
#:
#: The discriminator is what FOLLOWS: a real heading is followed by a
#: self-contained sentence, while an inline term is followed by a line that cannot
#: stand alone. Measured over the whole source corpus this reclassifies 11 of
#: 1,523 bracketed headings, all of them genuine `【…】や【…】など…` enumerations.
_CONTINUES_SENTENCE = re.compile(
    r"^[\s\u3000]*(?:"
    r"[やとかもねよなの](?:[\s\u3000]|$)"
    r"|など|なんか|とか|または|あるいは|及び|かつ"
    r"|という|といった|に関する|についての"
    r")"
)


def _prose_paragraph(line: str, next_line: str = "", field_lang: str = "ja") -> dict:
    """One prose paragraph, tagged as a section heading when it is one.

    A fully bracketed short line is the producer's own subsection heading, so it
    is emitted with a `proseHeading` role instead of as an identical body `div`.
    The stylesheet then gives it weight and space, which is what supplies the
    hierarchy round 9 reported missing across 30 of 92 images.

    A line that OPENS with a bracketed label and continues on the same line gets
    that label emphasised inline instead, because it leads into its own content
    rather than heading a following block.

    A predominantly-Latin line inside a JAPANESE field is a TRANSLATION of the
    explanation beside it, so it is marked `proseTranslation` and declares
    `lang="en"`. `field_lang` is what makes that conditional: five of the ten
    sources (`bunpro`, `dojg`, `donna_toki`, `imabi`, `yokubi`) explain IN English,
    so every paragraph they write is Latin-dominant and subordinating all of them
    would indent and quieten the primary explanation of half the corpus — the
    opposite of the distinction this role exists to draw. Reviewing a 7/10 v28
    tile: `２）基本的に、名詞につく場合は…` and
    `２）Generally, くらい becomes ぐらい…` rendered at the same size, weight, colour
    and indent, so the reader could not tell a translation from the primary
    explanation -- and because the producer emits the numbered Japanese points and
    then the numbered English ones, the visible numerals appeared to run 2,1,2,1,3.
    Measured 1,412 such lines in the packaged v28 banks. The source order is NOT
    changed; only the rendering distinguishes the two.

    The bracket characters are KEPT in every case: they are the producer's own
    typography, and stripping them would silently edit source text. Only the
    rendering weight changes.
    """
    stripped = line.strip()
    if _PROSE_HEADING.match(stripped):
        if next_line and _CONTINUES_SENTENCE.match(next_line.strip()):
            # Defect 19: the producer wrapped ONE sentence across lines around a
            # bracketed TERM (`【複数の人の中での状態】` / `や` /
            # `【〜と〜の関係の中のこと】` / `などを言いたい時に使います`). Promoting it to a
            # section landmark orphaned the connector on its own line under a big
            # bold heading, which round 24 filed as "isolated connector words with
            # large surrounding empty space, as if list content is missing".
            # Emphasised in place instead, using the same inline language as
            # `proseLabel`, so the sentence stays one unit.
            return {"tag": "div", "content": [_span("proseLabel", stripped)]}
        return {"tag": "div", "data": {"proseHeading": ""}, "content": stripped}
    match = _PROSE_INLINE_LABEL.match(stripped)
    if match:
        rest = stripped[match.end():]
        content: list[object] = [_span("proseLabel", match.group(1))]
        if rest:
            tail = _split_dialogue_prose(rest)
            content.extend(tail) if isinstance(tail, list) else content.append(tail)
        return {"tag": "div", "content": content}
    if field_lang == "ja" and _is_latin_dominant(stripped):
        return {
            "tag": "div",
            "data": {"proseTranslation": ""},
            "lang": "en",
            "content": _split_dialogue_prose(line),
        }
    return {"tag": "div", "content": _split_dialogue_prose(line)}


def _paragraphs(content: object, field_lang: str = "ja") -> object:
    """Split preserved paragraph breaks into sibling blocks.

    `bugd.richtext` keeps the producer's paragraph breaks as `\\n`, and the card
    sets `white-space: pre-line`, so they already render as line breaks. But a
    400-character explanation carrying eight breaks still reads as one dense
    block when consecutive lines merely touch. Emitting one `div` per paragraph
    lets the stylesheet space them, and keeps a single-paragraph field as a plain
    string so nothing is wrapped unnecessarily.

    A run following the producer's own ［例］ marker is additionally tagged
    `data-sc-inline-example`, so the stylesheet gives it the same bounded,
    rule-and-tint treatment as a lifted example instead of leaving it
    indistinguishable from the prose around it.
    """
    if isinstance(content, str):
        # The BLANK line is what ends an example run (measured: 739 of 739 blocks
        # end at one), so the raw split is kept and empty parts are used as the
        # terminator rather than filtered out up front.
        raw_parts = content.split("\n")
        if len([p for p in raw_parts if p.strip()]) <= 1:
            return _split_dialogue_prose(content)
        out: list[object] = []
        in_example = False
        example_first = False
        recurring = _recurring_bracketed_labels(raw_parts)

        def following(index: int) -> str:
            """The next non-blank line, or '' at the end of the field.

            `_prose_paragraph` needs it to tell a section heading from a bracketed
            TERM the producer wrapped a sentence around (defect 19).
            """
            for later in raw_parts[index + 1:]:
                if later.strip():
                    return later
            return ""

        def preceding(index: int) -> str:
            """The previous non-blank line, or '' at the start of the field.

            `_ends_example_run` uses it to keep the LAST variant of a parallel
            example set boxed even though the line after it is the closing remark.
            """
            for earlier in reversed(raw_parts[:index]):
                if earlier.strip():
                    return earlier
            return ""

        for position, part in enumerate(raw_parts):
            if not part.strip():
                in_example = False
                continue
            if _INLINE_EXAMPLE_MARKER.match(part):
                # The marker is a heading for the run, not an example itself.
                in_example = True
                example_first = True
                out.append({"tag": "div", "data": {"exampleLabel": ""}, "content": part.strip()})
                continue
            if in_example and _ends_example_run(
                part,
                recurring,
                next_line=following(position),
                prev_line=preceding(position),
                is_first=example_first,
            ):
                # The producer's closing remark or the next section heading. It is
                # prose, so it must fall OUTSIDE the tinted block.
                in_example = False
                example_first = False
                out.append(_prose_paragraph(part, following(position), field_lang))
                continue
            node = _prose_paragraph(part, following(position), field_lang)
            if in_example:
                example_first = False
                if part.strip() in recurring:
                    # A repeated bracketed label inside a run classifies the
                    # specimen ABOVE it, so it is an annotation, not a section
                    # heading. Left as a heading it would carry proseHeading,
                    # inlineExample and exampleAnnotation at once -- the same
                    # triple-role defect `verify_round10_fixes.py` guards -- and
                    # would be drawn as a section landmark inside the example box.
                    node = {"tag": "div", "content": part.strip()}
                node["data"] = dict(node.get("data") or {}, inlineExample="")
                # A derived meaning is subordinate to the specimen above it, not a
                # peer of it, so it carries its own role and the stylesheet indents
                # and quiets it.
                if _EXAMPLE_DERIVATION.match(part.strip()):
                    node["data"]["exampleDerivation"] = ""
                elif _EXAMPLE_ANNOTATION.match(part.strip()):
                    # Closes the set above it, so the grouping gap must NOT land
                    # here -- that is what detached it from the example it
                    # describes and made it look like an orphan block.
                    node["data"]["exampleAnnotation"] = ""
            out.append(node)
        return out
    if isinstance(content, list):
        out2: list[object] = []
        for item in content:
            split = _paragraphs(item, field_lang)
            out2.extend(split) if isinstance(split, list) and isinstance(item, str) else out2.append(split)
        return out2
    return content


def _source_levels(points: list[GrammarPoint]) -> list[str]:
    """The JLPT levels one SOURCE asserts for this point, in its own order.

    Repeats are collapsed, distinct assertions are not. Measured over the corpus,
    160 of the 207 multi-sense disclosures repeat one level on every sense inside
    them (2x on 128, 3x on 23, 4x on 9), so a per-SENSE badge would stack the
    identical string up to four times while adding nothing. But `あまり` really
    does carry N2 AND N5 from `edewakaru` alone, so a source that disagrees with
    itself keeps both.
    """
    levels: list[str] = []
    for point in points:
        if point.jlpt and point.jlpt not in levels:
            levels.append(point.jlpt)
    return levels


def _source_level_block(levels: list[str]) -> dict | None:
    """One source's own JLPT claim, stated inside that source's disclosure.

    `_compact_block` renders JLPT above the fold from the FIRST contribution that
    supplies a level, which is right for a deliberately one-line compact block --
    but it meant the 158 entries carrying a cross-source disagreement showed a
    single badge and the other levels appeared nowhere in the packaged bytes. A
    learner reading the 絵でわかる日本語 section could not tell that source called
    `あまり` N2 while 毎日のんびり日本語教師 called it N3.

    Nothing is reconciled, voted on, or preferred here: both statements are true
    about their own source, so each is stated where that source speaks. The level
    is introduced by name because a bare `N2` in running prose does not say what
    it measures, unlike the compact badge which sits in a metadata row.
    """
    if not levels:
        return None
    body: list[object] = ["JLPT "]
    for position, level in enumerate(levels):
        if position:
            body.append(" · ")
        body.append(_span("jlpt", level))
    return {
        "tag": "div",
        "data": {"sourceLevel": ""},
        "lang": "en",
        "content": body,
    }


def _source_block(point: GrammarPoint) -> list[object]:
    """One contributing source's substance, as renderable nodes.

    Every statement stays attached to the source that made it: explanation,
    nuance, and notes are never merged across sources or averaged. Returns an
    empty list when this record has nothing to show.
    """
    body: list[object] = []
    for field_name in ("explanation", "nuance", "notes"):
        raw = getattr(point, field_name, None)
        content = _prose(raw, point)
        if content is not None:
            # Prose is Japanese for most sources but English for DoJG (373 of its
            # explanations); the card root declares `ja`, so an English block must
            # say so explicitly or it inherits the wrong language.
            field_lang = _lang_of(raw) if isinstance(raw, str) else "ja"
            node: dict = {
                "tag": "div",
                "data": {"prose": ""},
                "content": _paragraphs(content, field_lang),
            }
            if isinstance(raw, str):
                node["lang"] = field_lang
            body.append(node)
    construction = _construction_section(point)
    if construction is not None:
        body.append(construction)
    examples = _examples_section(point)
    if examples is not None:
        body.append(examples)
    if not body:
        return []
    return body


def _sense_label(point: GrammarPoint, ordinal: int, total: int) -> str:
    """A distinguishing label for one of several senses from the same source.

    Sources contribute several records to one lookup form (`ない` has 20 records
    from one source). Repeating the identical source name on each disclosure is
    unreadable, so a sense that carries its own meaning is labelled with it and
    the rest are numbered.
    """
    if total <= 1:
        return ""
    meaning = _readable_meaning(point.meaning)
    if meaning:
        return _headline(meaning)
    # A structure only serves as a label when it is ONE formula. A multi-pattern
    # structure collapses to a space-joined run-on here exactly as it did in the
    # compact badge -- round 14 caught the surviving instance in a sense-label
    # heading after the badge and Construction-list call sites were fixed, which is
    # why the label is gated on the point rather than on the flattened text.
    if _has_badge_structure(point):
        return _text(point.structure)
    return f"Sense {ordinal}"


def _source_blocks(entry: MergedEntry, headline: str = "") -> list[dict]:
    """One disclosure per contributing SOURCE, senses nested inside it.

    Grouping by source (rather than by source record) is what keeps a card
    readable: `ない` contributes 25 records across 5 sources, which previously
    produced 25 sibling disclosures with repeated identical summary labels. Now
    each source is one disclosure whose summary names the source once, and its
    individual senses are labelled subsections inside it.

    `headline` is the compact block's already-visible meaning. A sense label that
    repeats it verbatim is dropped: the compact meaning is selected FROM the first
    contribution, so the first sense of the first source reproduced it word for
    word ('Approximately; about' appeared twice, ~15px apart, on くらい). Only an
    exact repeat is dropped -- a differing label still distinguishes its sense, and
    the numbered fallback still applies when a source has several senses.

    A source that asserts ONLY a JLPT level earns a disclosure too. 7 of the 158
    cross-source level conflicts (`たい`, `で`, `方`, `もう`, `てはいけない`,
    `たらどうですか`, `を余儀なくされる`) hid behind a source whose whole record is a
    level plus a meaning/structure the compact block already absorbed, so it
    produced no disclosure at all and its level was unreachable in the packaged
    bytes. Admission is gated on the LEVEL, not on the bare record: letting every
    substance-less record in would give 24 cards a first `sourceBlock` alongside
    the compact fallback they already render, which the frozen contract forbids
    (invariant 4).
    """
    grouped: dict[str, list[GrammarPoint]] = {}
    source_key: dict[str, str] = {}
    for point in entry.contributions:
        label = _source_label(point)
        grouped.setdefault(label, []).append(point)
        # Remember the source NAME behind each rendered label so the blocks can be
        # ordered by the source's explanation language. First writer wins; a label
        # only ever maps to one source.
        source_key.setdefault(label, point.source)

    # English-explaining dictionaries first, then monolingual Japanese ones. A
    # stable sort keeps the original contribution order within each language
    # group, so the ordering is deterministic and the build stays reproducible.
    def _lang_rank(label: str) -> int:
        lang = _SOURCE_EXPLANATION_LANG.get(source_key.get(label, ""), "")
        return _SOURCE_LANG_RANK.get(lang, 2)

    ordered_labels = sorted(grouped, key=_lang_rank)

    blocks: list[dict] = []
    for label in ordered_labels:
        points = grouped[label]
        rendered: list[tuple[GrammarPoint, list[object]]] = []
        for point in points:
            body = _source_block(point)
            if body:
                rendered.append((point, body))
        levels = _source_levels(points)
        if not rendered and not levels:
            continue

        shown = rendered[:SENSES_PER_SOURCE]
        body: list[object] = []
        # The level heads the disclosure: it qualifies everything this source goes
        # on to say, and it must be reachable even when the source ships nothing
        # else (the 7 conflicts above).
        level_block = _source_level_block(levels)
        if level_block is not None:
            body.append(level_block)
        for ordinal, (point, sense_body) in enumerate(shown, start=1):
            sense_label = _sense_label(point, ordinal, len(shown))
            if sense_label and headline and sense_label == headline:
                sense_label = ""
            if sense_label:
                body.append(
                    {
                        "tag": "div",
                        "data": {"senseLabel": ""},
                        "lang": _lang_of(sense_label),
                        "content": sense_label,
                    }
                )
            body.append({"tag": "div", "data": {"sense": ""}, "content": sense_body})

        blocks.append(
            {
                "tag": "details",
                "data": {"sourceBlock": ""},
                "content": [
                    {
                        "tag": "summary",
                        "content": [_span("sourceName", label)],
                    },
                    {"tag": "div", "content": body},
                ],
            }
        )
    return blocks


def _alias_target(point: GrammarPoint) -> str:
    """The canonical form an alias-only source record points at.

    Sources ship spelling-variant stubs (`相まって` -> `あいまって`, `後` -> `あと`)
    that carry no meaning, structure, prose, or examples of their own. Rendering
    one as a card whose only content is a `Sources` disclosure is a dead end for
    the reader, so the card instead points at the form that holds the substance.

    Some `alias-redirect` records set `aliasOf` to the headword itself and carry
    the real target only as an internal `?query=` producer link (`あって` ->
    `?query=にあって`), so an internal producer link is consulted as well. Only
    internal `?query=` links are trusted here: an external URL is provenance, not
    a dictionary cross-reference.
    """
    provenance = point.provenance if isinstance(point.provenance, dict) else {}
    for key in ("aliasOf", "canonicalExpression", "seeAlso"):
        value = provenance.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != point.expression:
            return value.strip()

    links = provenance.get("producerLinks")
    if isinstance(links, (list, tuple)):
        for link in links:
            if not isinstance(link, str) or not link.startswith("?query="):
                continue
            target = link[len("?query=") :].split("&", 1)[0].strip()
            if target and target != point.expression:
                return target
    return ""


def _producer_page(point: GrammarPoint) -> str:
    """The source's own external page for this grammar point, if it published one."""
    provenance = point.provenance if isinstance(point.provenance, dict) else {}
    links = provenance.get("producerLinks")
    if isinstance(links, (list, tuple)):
        for link in links:
            if isinstance(link, str) and link.startswith(("http://", "https://")):
                return link
    return ""


def _headword_only_block(entry: MergedEntry) -> dict | None:
    """Honest handling of a record the source listed but never described.

    Some sources index a grammar point in a running list without shipping a
    meaning, structure, prose, or examples for it. Inventing a gloss would be
    fabricated dictionary content, and a card whose only content is a `Sources`
    disclosure reads as broken. Instead the card states plainly that the source
    lists the form without an explanation, and links the source's own page when
    one exists so the reader can go there.
    """
    for point in entry.contributions:
        page = _producer_page(point)
        if not page:
            continue
        return {
            "tag": "div",
            "data": {"listedOnly": ""},
            "lang": "en",
            "content": [
                f"Listed by {_source_label(point)} without an explanation — ",
                {"tag": "a", "href": page, "content": "see the source page"},
                ".",
            ],
        }
    # No redirect and no published page: 3 of 2,419 real corpus entries reach
    # here. Naming the source is still strictly more honest and more useful than
    # a card whose entire visible content is a `Sources` disclosure, so the same
    # statement is made without a link rather than left blank.
    names: list[str] = []
    for point in entry.contributions:
        label = _source_label(point)
        if label not in names:
            names.append(label)
    if not names:
        return None
    return {
        "tag": "div",
        "data": {"listedOnly": ""},
        "lang": "en",
        "content": f"Listed by {', '.join(names)} without an explanation.",
    }


def _crossreference_block(entry: MergedEntry) -> dict | None:
    """A visible 'see <form>' pointer for an entry with no substance of its own.

    Only emitted when the entry genuinely has nothing to show and a source names
    a canonical form. The target is a clickable internal Yomitan lookup, so the
    reader reaches the real card in one tap instead of hitting an empty card.
    """
    targets: list[str] = []
    for point in entry.contributions:
        target = _alias_target(point)
        if target and target != entry.expression and target not in targets:
            targets.append(target)
    if not targets:
        return None

    body: list[object] = ["see "]
    for position, target in enumerate(targets):
        if position:
            body.append(", ")
        body.append(
            {
                "tag": "a",
                "href": f"?query={target}&wildcards=off",
                "lang": "ja",
                "content": target,
            }
        )
    return {"tag": "div", "data": {"crossref": ""}, "content": body}


def _compact_block(entry: MergedEntry) -> tuple[dict, str]:
    """Above-the-fold block: meaning, then a quiet construction/JLPT row.

    Returns the block and the headline it rendered, so the disclosures below can
    avoid repeating that exact string as their first sense label.

    Selection is deterministic: the first contribution (merge order) that
    supplies each field wins, and conflicting values are NOT averaged or
    silently picked — they remain visible per source in the disclosures below.
    The headword itself is not repeated; Yomitan renders it with furigana
    immediately above this block.
    """
    meaning = ""
    structure = ""
    jlpt = ""
    for point in entry.contributions:
        if not meaning:
            # A source's Chinese translation column is skipped rather than shown
            # as this card's primary line; the next contribution may still
            # supply a Japanese or English gloss.
            candidate = _readable_meaning(point.meaning)
            if candidate:
                meaning = _headline(candidate)
        if not structure:
            candidate = _text(point.structure)
            # Only a single readable formula earns a compact badge; multi-pattern
            # structures are rendered in that source's Construction list instead.
            # `_has_badge_structure` also rejects NEWLINE-separated patterns, which
            # `_text` had been collapsing into one space-joined run-on badge.
            if _has_badge_structure(point):
                structure = candidate
        if not jlpt and point.jlpt:
            jlpt = point.jlpt

    body: list[object] = []
    if meaning:
        # Sources publish meanings in English OR Japanese; declare what this one
        # actually is rather than assuming English.
        body.append(_span("meaning", meaning, lang=_lang_of(meaning)))

    metarow: list[object] = []
    if structure:
        metarow.append(_span("structure", structure, lang="ja"))
    if jlpt:
        metarow.append(_span("jlpt", jlpt))
    if metarow:
        body.append({"tag": "div", "data": {"metarow": ""}, "content": metarow})

    return {"tag": "div", "data": {"compact": ""}, "content": body}, meaning


def build_term_entry(entry: MergedEntry, sequence: int) -> list:
    """Build one Yomitan v3 term-bank entry for a merged grammar point.

    Term-bank entry shape (Yomitan v3, positional):
        [expression, reading, definitionTags, deinflectors, score,
         [glossary...], sequence, termTags]

    The glossary carries exactly one structured-content object so the whole card
    is one canonical surface: compact meaning/construction/JLPT above the fold,
    then native closed `details` disclosures per contributing source. Each
    per-source disclosure is titled with its own source name, so the source IS
    the attribution — there is no trailing data-less "Sources" details block.
    """
    if not isinstance(entry, MergedEntry):
        raise MalformedPayload("build_term_entry accepts MergedEntry records only")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise MalformedPayload("term-entry sequence must be a positive integer")

    compact, headline = _compact_block(entry)
    content: list[object] = [compact]
    source_blocks = _source_blocks(entry, headline)
    if not source_blocks:
        # No per-source disclosure will render. Two honest fallbacks, in order:
        # an alias-only spelling variant points at the form carrying the
        # substance; a listed-but-undescribed headword says so and links the
        # source's own page. Neither invents dictionary content.
        fallback = _crossreference_block(entry) or _headword_only_block(entry)
        if fallback is not None:
            content.append(fallback)
    content.extend(source_blocks)
    # No separate "Sources" attribution disclosure: each per-source block is
    # already titled with its source, so the source IS the section title.

    reading = ""
    for point in entry.contributions:
        candidate = point.reading or ""
        # Yomitan treats reading == expression as a redundant furigana pair.
        if candidate and candidate != entry.expression:
            reading = candidate
            break

    return [
        entry.expression,
        reading,
        "",
        "",
        0,
        [
            {
                "type": "structured-content",
                "content": {
                    "tag": "div",
                    "data": {CARD_ROOT_ROLE: ""},
                    "lang": "ja",
                    "content": content,
                },
            }
        ],
        sequence,
        "",
    ]


def build_index(
    revision: str,
    *,
    index_url: str | None = DICTIONARY_INDEX_URL,
    download_url: str | None = DICTIONARY_DOWNLOAD_URL,
    source_labels: dict[str, str] | None = None,
) -> dict:
    """Build `index.json` for the unified dictionary.

    Yomitan's index schema pins `isUpdatable` to `const: true` and makes it depend
    on both `indexUrl` and `downloadUrl`, so a self-updating index is valid only as
    all three together — pass `index_url=None, download_url=None` for an archive
    that should not advertise updates.

    They default to the published coordinates because a reader has no other way to
    know where this archive came from. Hachidori re-reads the imported `index.json`
    and refuses any dictionary whose `indexUrl` does not equal the URL it was
    fetched under, so an archive built without these fields cannot be installed as
    one of its recommended dictionaries at all.

    `attribution` names every contributing source by its human-facing label, so the
    credit for each source travels with the archive and is visible in Yomitan's
    dictionary details pane rather than only inside individual cards.
    """
    if not isinstance(revision, str) or not revision.strip():
        raise MalformedPayload("index revision must be a non-empty string")
    index = {
        "title": DICTIONARY_TITLE,
        "revision": revision,
        "format": DICTIONARY_FORMAT,
        "author": DICTIONARY_AUTHOR,
        "url": DICTIONARY_URL,
        "description": (
            "One unified Japanese grammar dictionary combining multiple grammar "
            "sources with per-source attribution."
        ),
        "sourceLanguage": "ja",
        "targetLanguage": "en",
        "sequenced": True,
    }
    labels = sorted({label for label in (source_labels or {}).values() if label})
    if labels:
        index["attribution"] = (
            "Grammar content contributed by: " + "; ".join(labels) + "."
        )
    if (index_url is None) != (download_url is None):
        raise MalformedPayload("a self-updating index requires both indexUrl and downloadUrl")
    if index_url is not None and download_url is not None:
        index["indexUrl"] = index_url
        index["downloadUrl"] = download_url
        index["isUpdatable"] = True
    return index


def build_banks(entries: list[MergedEntry]) -> dict[str, list]:
    """Shard merged entries into named Yomitan bank members.

    Returns a mapping of ZIP member name -> bank payload. Sharding is bounded at
    `TERM_BANK_SHARD` ordered entries per bank so constrained imports can advance
    bank by bank. An empty corpus yields no bank members: a scaffold build is
    honest about having no entries rather than shipping a placeholder record.
    """
    for entry in entries:
        if not isinstance(entry, MergedEntry):
            raise MalformedPayload("build_banks accepts MergedEntry records only")

    banks: dict[str, list] = {}
    for offset in range(0, len(entries), TERM_BANK_SHARD):
        shard = entries[offset : offset + TERM_BANK_SHARD]
        number = offset // TERM_BANK_SHARD + 1
        banks[f"term_bank_{number}.json"] = [
            build_term_entry(entry, offset + position + 1)
            for position, entry in enumerate(shard)
        ]
    return banks


def build_tag_bank(source_labels: dict[str, str]) -> list:
    """Build `tag_bank_1.json` from per-source attribution labels.

    Tag-bank entry shape (Yomitan v3, positional):
        [name, category, order, notes, score]
    """
    bank = []
    for order, name in enumerate(sorted(source_labels)):
        bank.append([name, "source", order, source_labels[name], 0])
    return bank


__all__ = [
    "CARD_ROOT_ROLE",
    "build_index",
    "build_term_entry",
    "build_banks",
    "build_tag_bank",
]
