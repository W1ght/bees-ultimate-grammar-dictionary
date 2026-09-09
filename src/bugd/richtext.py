"""Source HTML -> Yomitan structured content.

Every grammar source in this project ships HTML, not plain text. The real decks
carry tags Yomitan's term-bank schema does not accept (`h2`, `p`, `strong`,
`audio`, `button`, `svg`, `sup`, `del`, ...), Anki cloze markers, and `&nbsp;`
entities. Yomitan validates structured content against a closed tag allowlist, so
unmapped markup must be *converted*, never passed through.

Conversion policy:

* the allowlist is exactly what the pinned term-bank schema permits;
* known semantic tags are mapped to a permitted equivalent that preserves the
  source's meaning (`strong`/`b` -> bold `span`, `em`/`i` -> italic `span`,
  `p`/`h2`/`h4` -> `div`, `ul`/`ol`/`li` kept, `ruby`/`rt`/`rp` kept);
* structurally irrelevant or non-renderable tags are dropped but their text is
  kept (`span` with a source class, `section`, `a` used as a popout marker);
* media/interaction tags (`audio`, `button`, `svg`, `path`, `img`) are dropped
  *with* their subtree: this dictionary does not repackage deck audio, and a
  dangling `img` path would fail media-reference validation;
* anything unrecognised degrades to its text content rather than being emitted as
  an invalid tag, so a new source cannot silently break schema validation.

Nothing here invents content: no translation, no generated glosses. The only
transformations are markup mapping, entity decoding, and whitespace collapsing.
"""

from __future__ import annotations

import html.parser
import re
from typing import Any

#: Tags the pinned Yomitan term-bank schema permits in structured content.
ALLOWED_TAGS = frozenset(
    {
        "br",
        "ruby",
        "rt",
        "rp",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "span",
        "div",
        "ol",
        "ul",
        "li",
        "details",
        "summary",
        "img",
        "a",
    }
)

#: Source tags mapped onto a permitted tag that preserves their meaning.
_TAG_MAP = {
    "p": "div",
    "h1": "div",
    "h2": "div",
    "h3": "div",
    "h4": "div",
    "h5": "div",
    "h6": "div",
    "section": "div",
    "article": "div",
    "rb": "span",
    "small": "span",
    "strong": "span",
    "b": "span",
    "em": "span",
    "i": "span",
    "u": "span",
    "del": "span",
    "s": "span",
    "sup": "span",
    "sub": "span",
    "mark": "span",
    "code": "span",
    "font": "span",
    "center": "div",
}

#: Emphasis carried across the mapping above, so a source's `<strong>` stays
#: visually strong instead of silently flattening to plain text.
_TAG_STYLE: dict[str, dict[str, Any]] = {
    "strong": {"fontWeight": "bold"},
    "b": {"fontWeight": "bold"},
    "mark": {"fontWeight": "bold"},
    "em": {"fontStyle": "italic"},
    "i": {"fontStyle": "italic"},
    "u": {"textDecorationLine": "underline"},
    "del": {"textDecorationLine": "line-through"},
    "s": {"textDecorationLine": "line-through"},
    "sup": {"verticalAlign": "super", "fontSize": "0.8em"},
    "sub": {"verticalAlign": "sub", "fontSize": "0.8em"},
    "small": {"fontSize": "0.85em"},
}

#: Dropped together with their subtree: deck audio/interaction/vector chrome and
#: raw `img` references this dictionary does not repackage.
_DROP_SUBTREE = frozenset(
    {"audio", "button", "svg", "path", "video", "source", "track", "script", "style", "img", "iframe"}
)

_VOID = frozenset({"br", "hr", "img", "source", "track", "wbr", "input", "meta", "link"})

#: Anki cloze wrapper: `{{c1::text}}` / `{{c1::text::hint}}`. The deck's cloze
#: markers are review scaffolding, not dictionary content, so the answer text is
#: kept and the marker removed.
_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::.*?)?\}\}", re.S)

_WS = re.compile(r"[ \t\f\v\u00a0]+")
#: A LONE carriage return, i.e. one the source did not pair with a newline. This
#: producer emits `社\rの長` inside a word as a line-wrap hint from whatever tool
#: built the deck, and `community.clean` only normalises the `\r\n` pair. Leaving
#: `\r` inside `_WS` turned it into a SPACE mid-word (`社 長`, `会 社`) and glued
#: `長い時間rather` where the CR was the only separator between the Japanese and
#: English halves of a line. Measured over the corpus it is 1 prose field with 6
#: occurrences, every one between two Japanese characters and zero in any example,
#: so it is normalised to the same soft wrap as a newline and then resolved by the
#: language-aware join rule below rather than being hard-coded to one outcome.
_LONE_CR = re.compile(r"\r\n?")

#: A run of newlines that the source used as a paragraph break. Sources publish
#: prose with hard line breaks at semantic boundaries and blank lines between
#: paragraphs; 2,318 of the 9,400 prose fields in the current corpus contain a
#: blank line. Collapsing every newline to a space turned those into one
#: unreadable run-on block in the rendered card, so paragraph breaks survive as
#: `\n` and only single (soft-wrap) newlines become spaces. The card sets
#: `white-space: pre-line`, which renders a `\n` as a line break.
_PARA_BREAK = re.compile(r"[ \t\u3000]*\n(?:[ \t\u3000]*\n)+[ \t\u3000]*")
#: A single newline whose NEXT line opens a list item. Sources publish numbered
#: and circled-digit lists with one hard break per item and no blank line
#: between them, so the soft-wrap rule below glued them into a run-on paragraph:
#: `…使う。 ２）話者の意志を… ３）意味・用法は…`. Measured over the corpus, 2,107
#: such newlines span 885 records in 5 sources. The lookahead deliberately
#: anchors on the START of the following line, so an enumerator used as an
#: inline reference (`同時動作（N４）`, `例文（７）（８）`) keeps collapsing.
_LIST_BREAK = re.compile(
    r"[ \t\u3000]*\n[ \t\u3000]*(?=(?:[１-９][）)]|[①-⑳❶-❿]|\([1-9]\)|[1-9]\)))"
)
#: A single newline whose NEXT line opens a DIALOGUE TURN. These sources publish a
#: two-speaker exchange with one hard break per turn and no blank line, so the
#: soft-wrap rule glued the turns together:
#: `B：３００円しか当たらなかったよ A：当たっただけましだよ！`. The UGD-14 round-8 visual
#: gate filed that as a run-on.
#:
#: Same shape as `_LIST_BREAK`: anchored on the START of the following line, so a
#: role noun or letter occurring mid-sentence keeps collapsing, and only a line
#: that OPENS with `<label>：` is treated as a new turn.
_DIALOGUE_BREAK = re.compile(
    r"[ \t\u3000]*\n[ \t\u3000]*"
    r"(?=(?:お母さん|母親|彼女|彼氏|同僚|部下|上司|社員|店員|店長|学生|先生|医者"
    r"|患者|観客|歌手|犯人|警察|息子|娘|母|父|夫|妻|兄|弟|姉|妹|客|孫|祖母|祖父)"
    r"[A-Za-zＡ-Ｚ0-9０-９]?[：:]"
    r"|[A-Za-zＡ-Ｚａ-ｚ][0-9０-９]?[：:])"
)
#: Any remaining single newline: the producer's own soft wrap.
_SOFT_BREAK = re.compile(r"[ \t\u3000]*\n[ \t\u3000]*")
#: The line FOLLOWING a soft wrap opens one of the producer's structural markers
#: -- an annotation bracket, a derivation arrow, a bullet, or a table cell pipe.
#: Such a line is its own rendered line, so the wrap is semantic and must survive
#: as a break. Without this, joining the wrap replaces a spacing defect with a
#: worse run-on: `…秘密なんてありません【〜と〜との関係の中のこと】夫と妻の関係の中のこと`.
#:
#: Deliberately excludes `（` / `(`: a parenthesis after Japanese text is usually
#: an INLINE reference the producer soft-wrapped before (`同時動作\n（N４）のほかに`),
#: not a block of its own. An ASCII parenthesised enumerator that really does open
#: a list item is already handled by `_LIST_BREAK`.
_MARKER_OPEN = re.compile(r"[【〈《→⇒⇔←＝=※＊・…｜|]")
#: The line PRECEDING a soft wrap closed a sentence or an annotation block, so the
#: next line starts a new one and the break is semantic.
_SENTENCE_END = re.compile(r"[。！？!?：:；;】〉》］\]）)」』]")
#: A genuine Latin word boundary, where the joining space is required. Japanese
#: has no inter-word space, so a wrap between two Japanese characters must join
#: with NOTHING -- inserting a space there is what made the round-8 visual gate
#: report `私たち夫婦の 間 に秘密なんてありません` and `友達を待っている 間、音楽を…` as
#: broken text rendering. Measured over the corpus: 17,839 joins, 13,537 breaks,
#: 92 spaces, and zero cases where a glue fuses two Latin alphanumerics.
_LATIN_END = re.compile(r"[A-Za-z0-9,.;:!?)\]}\"'”’]")
_LATIN_OPEN = re.compile(r"[A-Za-z0-9(\[{\"'“‘]")
#: A script CHANGE also needs the space, in either direction. DoJG writes a
#: bilingual gloss line whose halves are separated only by a wrap
#: (`…or 長い時間\rrather than about…`), so gluing produced `長い時間rather`. A
#: Japanese character adjacent to a Latin word is a real word boundary even though
#: neither side alone satisfies the Latin test above.
_JAPANESE_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_CHAR = re.compile(r"[A-Za-z0-9]")
#: A shared trailing run marking two lines as items of the same producer list.
#: These sources publish a variant list with one item per line and NO bullet:
#:
#:     食べっぷり / 飲みっぷり / 言いっぷり / 仕事っぷり など
#:     愛してやまない / 尊敬してやまない / 期待してやまない など
#:
#: Every item repeats the entry's own grammar point, so the wrap between them is
#: semantic. Line LENGTH cannot detect this -- a wrapped sentence
#: (`告白しようとしたが、` / `いざとなると`) is just as short -- but the repeated tail
#: can: the list items share one, the wrapped sentence shares none. The tail must
#: itself be Japanese text so two lines merely ending in the same punctuation do
#: not qualify.
_JAPANESE_RUN = re.compile(r"^[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+$")
#: Minimum shared tail. At 1 character every line ending in `だ`/`る` would pair.
_PARALLEL_TAIL_MIN = 2
#: A construction-pattern line: the producer's slot notation, joined by the
#: corpus's FULLWIDTH PLUS. These are published one per line, and the shared-tail
#: rule above misses them because their tails legitimately differ
#: (`あまり／あんまり＋イ形容詞語幹＋くない` next to `あまり＋動ない形`), which glued them
#: into `…くないあまり＋動ない形`.
#:
#: The line must be notation ONLY -- no sentence-ending punctuation and no
#: enumerator prefix -- because a numbered explanation sentence can also quote a
#: pattern (`２）例文のように、「～」は「形容詞の語幹＋さ」が多い。`) and must keep wrapping
#: like the prose it is.
_PATTERN_LINE = re.compile(
    r"^(?![０-９\d][）)])(?=[^。．！？!?]*$).*[＋].*$"
)
#: Sentinel standing in for a paragraph break while inline runs are collapsed.
#: It must be a character `_WS` does not match and that cannot occur in source
#: text: `\v` is in `_WS`, so using it silently ate every paragraph break.
_PARA_SENTINEL = "\x00"


def _is_parallel_list_item(before_line: str, after_line: str) -> bool:
    """Do two adjacent lines look like items of the same unbulleted list?

    Compared on their leading words as well as their trailing run, because the LAST
    item of these lists carries a closing remark (`仕事っぷり など…（…）`) that destroys
    the shared tail while the item itself is still an item.
    """
    shared = 0
    limit = min(len(before_line), len(after_line))
    while shared < limit and before_line[-1 - shared] == after_line[-1 - shared]:
        shared += 1
    if shared >= _PARALLEL_TAIL_MIN and _JAPANESE_RUN.match(before_line[-shared:]):
        return True
    # The final item's own text still repeats the point, before its remark. Compare
    # the first whitespace-delimited word of each line the same way.
    before_word = before_line.split(" ")[0].split("\u3000")[0]
    after_word = after_line.split(" ")[0].split("\u3000")[0]
    if before_word == before_line and after_word == after_line:
        return False
    shared = 0
    limit = min(len(before_word), len(after_word))
    while shared < limit and before_word[-1 - shared] == after_word[-1 - shared]:
        shared += 1
    return bool(
        shared >= _PARALLEL_TAIL_MIN and _JAPANESE_RUN.match(before_word[-shared:])
    )


def _join_soft_break(text: str) -> str:
    """Resolve each of the producer's soft wraps to a break, a space, or nothing.

    A soft wrap is not always a soft wrap. These sources publish prose with a hard
    line break at every semantic boundary, so four different intentions arrive as
    the same single `\\n`:

    * a structural line (`【…】`, `→…`, a `|` table row) -- keep the break;
    * an item of an unbulleted variant list -- keep the break;
    * a Latin word or script boundary -- join with a space;
    * a wrap inside one Japanese sentence -- join with NOTHING.

    Japanese has no inter-word space, so the last case is the common one, and
    substituting a space there is what produced the visual gate's
    `私たち夫婦の 間 に秘密なんてありません` and the space before a `、`.
    """
    out: list[str] = []
    position = 0
    for match in _SOFT_BREAK.finditer(text):
        chunk = text[position : match.start()]
        out.append(chunk)
        stripped = chunk.rstrip(" \t\u3000" + _PARA_SENTINEL)
        before = stripped[-1:]
        after = text[match.end() : match.end() + 1]
        # The whole lines on each side of this wrap, for the list-item test.
        before_line = stripped.rsplit("\n", 1)[-1].rsplit(_PARA_SENTINEL, 1)[-1]
        after_line = re.split(
            rf"[\n{_PARA_SENTINEL}]", text[match.end() :], maxsplit=1
        )[0].rstrip(" \t\u3000")
        if not before or not after or after == _PARA_SENTINEL:
            joiner = _PARA_SENTINEL
        elif _MARKER_OPEN.match(after) or _SENTENCE_END.match(before):
            joiner = _PARA_SENTINEL
        elif _is_parallel_list_item(before_line, after_line):
            # A bullet-less variant list: every item repeats the grammar point.
            joiner = _PARA_SENTINEL
        elif _PATTERN_LINE.match(before_line) and _PATTERN_LINE.match(after_line):
            # Two adjacent construction patterns each own their line. Both sides
            # must be notation, so a pattern followed by an explanation sentence
            # still wraps as prose.
            joiner = _PARA_SENTINEL
        elif _LATIN_END.match(before) and _LATIN_OPEN.match(after):
            joiner = " "
        elif (
            _JAPANESE_CHAR.match(before) and _LATIN_WORD_CHAR.match(after)
        ) or (
            _LATIN_WORD_CHAR.match(before) and _JAPANESE_CHAR.match(after)
        ):
            # A script change is a word boundary even when neither side is
            # Latin-on-Latin: `…or 長い時間` + `rather than…`.
            joiner = " "
        else:
            joiner = ""
        out.append(joiner)
        position = match.end()
    out.append(text[position:])
    return "".join(out)


def _paragraphize(data: str) -> str:
    """Collapse inline whitespace while keeping the source's paragraph breaks."""
    text = data.replace(_PARA_SENTINEL, "")
    # A lone `\r` is a wrap hint, not inline whitespace: normalise it to the same
    # newline every other wrap uses so one rule decides all of them.
    text = _LONE_CR.sub("\n", text)
    text = _PARA_BREAK.sub(_PARA_SENTINEL, text)
    # A list item's own break is semantic; it must survive the soft-wrap rule.
    text = _LIST_BREAK.sub(_PARA_SENTINEL, text)
    # So is a dialogue turn's.
    text = _DIALOGUE_BREAK.sub(_PARA_SENTINEL, text)
    text = _join_soft_break(text)
    text = _WS.sub(" ", text)
    # Ideographic space is a real space in Japanese prose, but a run of them
    # around a break is layout padding, not content.
    text = re.sub(rf"[ \u3000]*{_PARA_SENTINEL}[ \u3000]*", "\n", text)
    return text


def strip_cloze(text: str) -> str:
    """Unwrap Anki cloze markers, keeping the answer text."""
    previous = None
    current = text
    # Nested cloze deletions exist in real decks; unwrap until stable.
    while current != previous:
        previous = current
        current = _CLOZE.sub(r"\1", current)
    return current


class _Converter(html.parser.HTMLParser):
    """Convert one HTML fragment into a structured-content node list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._root: list[Any] = []
        self._stack: list[tuple[str, list[Any], dict[str, Any] | None]] = []
        self._drop_depth = 0

    # -- sinks -------------------------------------------------------------
    @property
    def _sink(self) -> list[Any]:
        return self._stack[-1][1] if self._stack else self._root

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._drop_depth:
            if tag not in _VOID:
                self._drop_depth += 1
            return
        if tag in _DROP_SUBTREE:
            if tag not in _VOID:
                self._drop_depth = 1
            return
        if tag == "br":
            self._sink.append({"tag": "br"})
            return
        if tag in _VOID:
            return

        mapped = tag if tag in ALLOWED_TAGS else _TAG_MAP.get(tag)
        style = _TAG_STYLE.get(tag)
        if mapped is None:
            # Unknown tag: keep its text, drop the element itself.
            self._stack.append(("", self._sink, None))
            return
        if mapped == "a":
            # Source anchors are popout/reference markers pointing at the
            # producer's own site; keep the visible text, drop the link.
            self._stack.append(("", self._sink, None))
            return
        self._stack.append((mapped, [], style))

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() == "br" and not self._drop_depth:
            self._sink.append({"tag": "br"})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._drop_depth:
            self._drop_depth -= 1
            return
        if not self._stack:
            return
        name, children, style = self._stack.pop()
        if not name:
            # Transparent element: its children were appended straight to the
            # parent sink, so there is nothing to wrap.
            return
        node: dict[str, Any] = {"tag": name}
        if children:
            node["content"] = children[0] if len(children) == 1 else children
        if style:
            node["style"] = dict(style)
        self._sink.append(node)

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        text = _paragraphize(strip_cloze(data))
        if not text.strip():
            # Keep a single separating space between inline siblings; drop pure
            # indentation noise from the source's pretty-printed HTML.
            if text and self._sink and isinstance(self._sink[-1], (dict, str)):
                if self._sink and isinstance(self._sink[-1], str) and self._sink[-1].endswith(" "):
                    return
                self._sink.append(" ")
            return
        self._sink.append(text)

    def result(self) -> list[Any]:
        while self._stack:
            self.handle_endtag(self._stack[-1][0] or "span")
        return self._root


def _tidy(nodes: list[Any]) -> list[Any]:
    """Drop leading/trailing whitespace nodes and collapse runs."""
    out: list[Any] = []
    for node in nodes:
        if isinstance(node, str):
            if not out and not node.strip():
                continue
            if out and isinstance(out[-1], str):
                merged = out[-1] + node
                out[-1] = _WS.sub(" ", merged)
                continue
        out.append(node)
    while out and isinstance(out[-1], str) and not out[-1].strip():
        out.pop()
    while out and isinstance(out[-1], dict) and out[-1].get("tag") == "br":
        out.pop()
    while out and isinstance(out[0], dict) and out[0].get("tag") == "br":
        out.pop(0)
    return out


def html_to_content(source: str | None) -> Any | None:
    """Convert a source HTML fragment to structured content.

    Returns `None` when the fragment carries no renderable content, so callers
    can omit a section instead of shipping an empty labelled block.
    """
    if source is None:
        return None
    if not isinstance(source, str):
        raise TypeError("html_to_content expects a string or None")
    if not source.strip():
        return None
    converter = _Converter()
    converter.feed(source)
    converter.close()
    nodes = _tidy(converter.result())
    if not nodes:
        return None
    if not _has_text(nodes):
        return None
    return nodes[0] if len(nodes) == 1 else nodes


def html_to_text(source: str | None) -> str:
    """Flatten a source HTML fragment to plain text.

    Used for headwords, ARIA-visible labels, and anywhere a single-line string is
    required rather than structured content.
    """
    if not source:
        return ""
    content = html_to_content(source)
    return collapse(_flatten(content))


def collapse(text: str) -> str:
    """Flatten to one line.

    Callers use this for headwords, labels, and anywhere a single-line string is
    required, so newlines must collapse too: prose now preserves the source's
    paragraph breaks, and `_WS` deliberately does not match `\\n`.
    """
    return _WS.sub(" ", text.replace("\n", " ")).strip()


def _flatten(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten(item) for item in node)
    if isinstance(node, dict):
        if node.get("tag") == "br":
            return " "
        if node.get("tag") in ("rt", "rp"):
            # Ruby annotation text is not part of the surface string, and neither
            # is `rp`: those are the fallback parentheses a browser shows ONLY
            # when it cannot render ruby, so a renderer that paints `rt` never
            # paints them. Flattening them produced `親切（）だ。` for the one
            # Bunpro sentence that ships `<rp>（</rp><rt>しんせつ</rt><rp>）</rp>`
            # -- an empty pair of parentheses in the plain-text surface, which is
            # also the string example dedup and highlight matching compare on.
            return ""
        return _flatten(node.get("content"))
    return ""


def _has_text(node: Any) -> bool:
    return bool(_flatten(node).strip())


def ruby_surface(node: Any) -> str:
    """The base (non-annotation) text of a converted node."""
    return collapse(_flatten(node))


__all__ = [
    "ALLOWED_TAGS",
    "collapse",
    "html_to_content",
    "html_to_text",
    "ruby_surface",
    "strip_cloze",
]
