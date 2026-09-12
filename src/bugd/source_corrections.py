"""Deterministic per-source data corrections applied during extraction.

Some acquired sources carry data-layer defects — a typo, a paste from a
neighbouring entry, or a formula that the source's own examples violate. The
acquired bytes are locked and must never be hand-edited, so a correction cannot
live in the source directory. Instead every correction is a *recorded, replayable
transform* keyed by ``(source, source_id)``, applied to the extracted
``GrammarPoint`` right after the per-row parser produces it. A re-extract from the
untouched locked bytes therefore reproduces the corrected record byte-for-byte,
and any entry with no correction entry passes through identically.

This mirrors the established fix-up-table pattern (a keyed wrong→right map applied
at a single normalisation choke point) rather than rewriting merged output, which
would paper over the defect instead of fixing it at the layer that owns the data.

Scope: the eight Class-A cross-source data defects filed by UGD-11d-A
(card ``t_62bd276f``). Each defect is one source's field contradicting every
other contributing source AND that source's own examples; the verbatim wrong and
right strings below were re-confirmed present in the frozen extracted source JSON
by ``scripts/independent_reverify.py``. Nothing here invents a fix beyond those
eight — the table is closed and every entry cites its finding id.

A correction is one of:

* a ``ReplaceIn`` — replace a verbatim substring inside a named field, expecting
  an exact number of occurrences (a mismatch fails closed rather than silently
  correcting the wrong thing);
* a ``SetExpression`` — re-home a mis-scoped record onto a different headword so
  the merge stage groups it correctly (used only for A7, where nihongo_net's
  ``に至るまで`` record is actually a ``に至る`` record — its structure omits まで
  and none of its examples contain まで).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .model import Example, GrammarPoint


@dataclass(frozen=True)
class ReplaceIn:
    """Replace ``wrong`` with ``right`` inside ``field``, ``count`` times.

    ``count`` is the exact number of occurrences expected in the *whole* field
    (across every example when ``field == "examples"``). If the observed count
    differs the correction raises, so an upstream re-acquisition that changed the
    defect surfaces as a hard failure instead of an under- or over-correction.
    """

    field: str
    wrong: str
    right: str
    count: int
    finding: str

    def apply(self, point: GrammarPoint) -> GrammarPoint:
        if self.field == "examples":
            total = sum(ex.japanese.count(self.wrong) for ex in point.examples)
            self._check(point, total)
            examples = tuple(
                dataclasses.replace(
                    ex, japanese=ex.japanese.replace(self.wrong, self.right)
                )
                if self.wrong in ex.japanese
                else ex
                for ex in point.examples
            )
            return dataclasses.replace(point, examples=examples)

        value = getattr(point, self.field)
        if value is None:
            self._check(point, 0)
            return point
        self._check(point, value.count(self.wrong))
        return dataclasses.replace(
            point, **{self.field: value.replace(self.wrong, self.right)}
        )

    def _check(self, point: GrammarPoint, observed: int) -> None:
        if observed != self.count:
            raise SourceCorrectionError(
                f"correction {self.finding} for {point.source}#{point.source_id} "
                f"expected {self.count} occurrence(s) of {self.wrong!r} in "
                f"{self.field}, found {observed}"
            )


@dataclass(frozen=True)
class SetExpression:
    """Re-home a mis-scoped record onto ``expression`` (record split).

    ``expect`` is the current expression; a mismatch fails closed so the split is
    never applied to a record that has drifted from what was audited.
    """

    expression: str
    expect: str
    finding: str

    def apply(self, point: GrammarPoint) -> GrammarPoint:
        if point.expression != self.expect:
            raise SourceCorrectionError(
                f"correction {self.finding} for {point.source}#{point.source_id} "
                f"expected expression {self.expect!r}, found {point.expression!r}"
            )
        return dataclasses.replace(point, expression=self.expression)


@dataclass(frozen=True)
class HedgeAbsolute:
    """Soften an unqualified absolute restriction into a source-attributed tendency.

    UGD-11d-B remedy. Twelve merged cards paired one source's ABSOLUTE
    prohibition (必ず… / 〜しか使えません / いけません / 使いません / ❌…) beside another
    source's sanctioned example that the prohibition forbids — a learner saw a
    rule and a counterexample to it on the same card with no guidance.

    The dictionary's contract is that every statement stays attributed to the
    source that made it, so the fix must NOT rewrite the claim to match the other
    source or delete it. Instead the absolute operator in ``anchor`` is replaced,
    in place inside the source's own prose, with ``hedged`` — the same statement
    re-cast as that source's *tendency* plus an inline note that other sources
    disagree. The statement stays byte-attributed to the source; only its modal
    force is lowered so the card no longer presents an unqualified rule next to a
    live counterexample.

    ``anchor`` must occur exactly ``count`` times in ``explanation`` (fail-closed:
    a drifted source surfaces as a hard error, never a silent miss). ``hedged``
    is asserted to (a) drop the absolute operator ``forbids`` and (b) contain the
    tendency marker, so a regression that reintroduces the absolute is caught.
    """

    anchor: str
    hedged: str
    forbids: str
    count: int
    finding: str
    field: str = "explanation"

    def apply(self, point: GrammarPoint) -> GrammarPoint:
        # Structural guards on the correction itself run regardless of which row
        # we landed on, so a malformed hedge fails at build time even before it
        # meets its anchor.
        if self.forbids and self.forbids not in self.anchor:
            raise SourceCorrectionError(
                f"hedge {self.finding}: absolute operator {self.forbids!r} is not "
                f"in the anchor {self.anchor!r}"
            )
        if self.forbids and self.forbids in self.hedged:
            raise SourceCorrectionError(
                f"hedge {self.finding}: hedged text still contains the absolute "
                f"operator {self.forbids!r}"
            )
        value = getattr(point, self.field)
        observed = value.count(self.anchor) if value else 0
        # UGD-11d proved source_id is NOT unique (max 22 rows/id): a single
        # (source, source_id) key can select several rows that share a headword
        # but carry different prose. The absolute paragraph lives on exactly the
        # rendering row; sibling rows under the same id legitimately lack the
        # anchor. Pass those through untouched (observed == 0) rather than fail.
        if observed == 0:
            return point
        if observed != self.count:
            raise SourceCorrectionError(
                f"hedge {self.finding} for {point.source}#{point.source_id} "
                f"expected {self.count} occurrence(s) of {self.anchor!r} in "
                f"{self.field}, found {observed}"
            )
        return dataclasses.replace(
            point, **{self.field: value.replace(self.anchor, self.hedged)}
        )


class SourceCorrectionError(Exception):
    """A recorded correction did not match the extracted record it targets."""


Correction = ReplaceIn | SetExpression | HedgeAbsolute

# ---------------------------------------------------------------------------
# The closed table: eight Class-A defects (UGD-11d-A / card t_62bd276f).
# Keyed by (source, source_id). Corrections apply in listed order.
# ---------------------------------------------------------------------------

CORRECTIONS: dict[tuple[str, str], tuple[Correction, ...]] = {
    # A1. にほかならない — dojg misspells the headword: にはかならない (6x in the
    # structure table) and ことにほならない (1x, in an example). The same rows write
    # にほかならない correctly 13x; every other source agrees on にほかならない.
    ("dojg", "にほかならない"): (
        ReplaceIn("structure", "にはかならない", "にほかならない", 6, "A1"),
        ReplaceIn(
            "examples",
            "ことにほならない",
            "ことにほかならない",
            1,
            "A1",
        ),
    ),
    # A3. かどうか — nihongo_net keeps だ before かどうか for ナA and N, licensing
    # ×便利だかどうか. Standard rule (nihongo_no_sensei) is bare stem + (である/なの).
    ("nihongo_net", "かどうか"): (
        ReplaceIn(
            "structure",
            "ナA（普通形）だかどうか、〜 ※ナAだ",
            "ナA（語幹）（である／なの）かどうか、〜",
            1,
            "A3",
        ),
        ReplaceIn(
            "structure",
            "N（普通形）だかどうか、〜 ※Nだ",
            "N（である／なの）かどうか、〜",
            1,
            "A3",
        ),
    ),
    # A4–A7 removed: entries no longer present in the re-scraped nihongo_net data
    # (2026-09 scrape from nihongokyoshi-net.com replaced aiko-tanaka community banks).
    # UGD-16. bunpou/247 glues an editorial comparison note onto its headword with
    # a newline: '〜向けに\n類似文型「〜向き」との違い'. A multi-line string is not a
    # lookup form -- the packaged ?query= cross-reference already truncated at the
    # break, so the rendered link and the headword disagreed, and the entry was
    # unreachable under either spelling. The note is prose ABOUT a different
    # pattern (〜向き) and stays in the record's meaning field, where the source
    # actually says it; only the headword is re-homed onto the form the row
    # documents. Recorded here rather than truncated in the display path, because
    # a display-layer cut would collide this row onto the genuine 向けに point (two
    # `point` entries, one headword, identical axes).
    ("bunpou", "247"): (
        SetExpression(
            "〜向けに",
            "〜向けに\n類似文型「〜向き」との違い",
            "UGD-16-headword-newline",
        ),
    ),
    # A8. ことは — dojg's noun rows drop the defining こと: 「いい人はいい人{だ/です}」
    # and 「いい人だったことは人{だった/でした}」. The well-formed noun pattern is
    # NであることはN{だ/です}（が） (edewakaru). The な-adjective rows (静かなことは…)
    # are already correct and are left untouched.
    ("dojg", "ことは"): (
        ReplaceIn(
            "structure",
            "| いい人はいい人{だ/です} | Someone is a good person |",
            "| いい人であることはいい人{だ/です} | Someone is a good person |",
            1,
            "A8",
        ),
        ReplaceIn(
            "structure",
            "| いい人だったことは人{だった/でした} | Someone was a good person |",
            "| いい人だったことはいい人{だった/でした} | Someone was a good person |",
            1,
            "A8",
        ),
    ),
    # -----------------------------------------------------------------------
    # UGD-11d-B: twelve absolute usage rules, each rendered on a card beside
    # another source's sanctioned counterexample. Hedge in place — the source's
    # own prose stays attributed, only its modal force is lowered and an inline
    # note records that other sources disagree. Keyed by the rendering row's
    # (source, source_id) confirmed via the frozen keymap (probe_rows.py); each
    # anchor occurs exactly once in that row's explanation.
    # -----------------------------------------------------------------------
    # B1. あげく — edewakaru asserts あげく is only for bad outcomes; dojg's
    # さんざん考えたあげく大学院へ進学することにした is a neutral/good outcome.
    ("edewakaru", "あげく"): (
        HedgeAbsolute(
            "「〜あげく」はよくない結果になったことに使います",
            "「〜あげく」はよくない結果になったことに使う傾向があります（他の辞書はよい結果の例も認めます）",
            "使います",
            1,
            "B1",
        ),
    ),
    # B2. か〜ないかのうちに — edewakaru requires 必ず「た形」; donna_toki's
    # 教室を飛び出していく ends in non-past. Same prose also renders on the
    # ないかのうちに row; the headword row か carries the shipped fix.
    ("edewakaru", "か"): (
        HedgeAbsolute(
            "後ろには必ず「た形」がくると覚えておきましょう",
            "後ろには多くの場合「た形」がくると覚えておきましょう（他の辞書は非過去の例も挙げています）",
            "必ず",
            1,
            "B2",
        ),
    ),
    # B4. が早いか — edewakaru calls natural-phenomenon subjects unnatural;
    # nihongo_no_sensei's 電話が来るが早いか、緊張で手が震え出した uses one.
    ("edewakaru", "が早いか"): (
        HedgeAbsolute(
            "自然現象や状態の発生などに使うと不自然になります",
            "自然現象や状態の発生などに使うと不自然になりやすいとされます（他の辞書はそうした例も認めます）",
            "不自然になります",
            1,
            "B4",
        ),
    ),
    # B5. が早いか — nihongo_no_sensei says past-only; donna_toki's
    # チャイムが鳴るが早いか、教室に入ってきます is habitual non-past.
    ("nihongo_no_sensei", "が早いか"): (
        HedgeAbsolute(
            "この文法は過去のことにしか使えません。",
            "この文法は主に過去のことに使われます。（他の辞書は非過去の例も挙げています）",
            "しか使えません",
            1,
            "B5",
        ),
    ),
    # B6. くせに — edewakaru restricts the subject to people; nihongo_no_sensei's
    # 道が狭いくせに車通りは多い takes a non-person subject. Same prose also renders
    # on くせして; the headword row くせに carries the shipped fix.
    ("edewakaru", "くせに"): (
        HedgeAbsolute(
            "人に使う（動物であればOKな場合もある）",
            "主に人（動物であればOKな場合もある）を対象にする傾向があります（他の辞書は物事を主語にする例も認めます）",
            "人に使う",
            1,
            "B6",
        ),
    ),
    # B9. すら — nihongo_no_sensei says the second clause must be negative; its
    # OWN examples #1/#6/#7/#11 are affirmative (e.g. 怒っているところすら可愛い).
    ("nihongo_no_sensei", "すら"): (
        HedgeAbsolute(
            "後件には否定形が呼応します。",
            "後件には否定形が呼応する傾向があります。（ただし当辞書の例文にも肯定形の後件が見られます）",
            "呼応します",
            1,
            "B9",
        ),
    ),
    # B10. せいか/せいで — nihongo_no_sensei says only bad outcomes; edewakaru's
    # ⭕️薬を飲んだせいか頭痛が治った is a good outcome. Renders on the せいで row
    # (canonicalKey せいか); the せいか/せいだ/せいにする rows are demoted.
    ("nihongo_no_sensei", "せいで"): (
        HedgeAbsolute(
            "後項にはその原因から発生した良くない結果を述べます",
            "後項にはその原因から発生した良くない結果を述べる傾向があります（他の辞書はよい結果の例も認めます）",
            "述べます",
            1,
            "B10",
        ),
    ),
    # B13. なり — edewakaru requires same subject before and after; dojg's
    # 部屋に入るなりルームサービスの人が…持ってきてくれた switches subject.
    ("edewakaru", "なり"): (
        HedgeAbsolute(
            "また、前と後ろの主語は同じでなければいけません",
            "また、前と後ろの主語は同じであることが多いです（他の辞書は主語が異なる例も挙げています）",
            "なければいけません",
            1,
            "B13",
        ),
    ),
    # B14. に至っては — donna_toki frames it as negative-evaluation extremes;
    # dojg's くらげにいたっては96%が水だ is a neutral extreme example.
    ("donna_toki", "に至っては"): (
        HedgeAbsolute(
            "マイナス評価の例がいくつかある中で～という極端な例を挙げて",
            "いくつかの例がある中で～という極端な例を挙げて（多くは否定的な評価だが、他の辞書は中立的な極端例も挙げています）",
            "マイナス評価",
            1,
            "B14",
        ),
    ),
    # B18. ようにも — donna_toki says the post-clause verb is the potential form;
    # edewakaru notes 「〜ない」 and potential-negative both occur.
    ("donna_toki", "ようにも"): (
        HedgeAbsolute(
            "「にも」の前後は同じ動詞を使い、前は意志動詞の意志形、後はその可能動詞である。",
            "「にも」の前後は同じ動詞を使い、前は意志動詞の意志形、後はその可能動詞であることが多い。（他の辞書は「〜ない」や可能形の否定形がくる場合も挙げています）",
            "である。",
            1,
            "B18",
        ),
    ),
    # B19. わ — nihongo_no_sensei claims good-meaning use is possible, but all 8
    # of its OWN examples describe unwelcome outcomes; edewakaru follows suit.
    ("nihongo_no_sensei", "わ"): (
        HedgeAbsolute(
            "良いことにも使えますが、どちらかというと悪い意味の用法が多めに感じます。",
            "どちらかというと悪い意味の用法が多めに感じます。（当辞書の例文はいずれも好ましくない結果を述べており、良い意味での用法は確認できません）",
            "良いことにも使えますが",
            1,
            "B19",
        ),
    ),
    # B20. をものともせずに — edewakaru forbids first-person subjects; nihongo_no_sensei's
    # 老いをものともせず、何歳になっても挑戦的でありたい is speaker-referential.
    ("edewakaru", "をものともせずに"): (
        HedgeAbsolute(
            "話し手自身のことには使えません",
            "話し手自身のことには使いにくいとされます（他の辞書は一人称の例も認めます）",
            "使えません",
            1,
            "B20",
        ),
    ),
}


def correct_point(point: GrammarPoint) -> GrammarPoint:
    """Apply every recorded correction for ``point``'s (source, source_id).

    Identity for any record with no correction entry, so unaffected points stay
    byte-identical through a re-extract.
    """
    corrections = CORRECTIONS.get((point.source, point.source_id))
    if not corrections:
        return point
    for correction in corrections:
        point = correction.apply(point)
    return point


__all__ = [
    "CORRECTIONS",
    "Correction",
    "HedgeAbsolute",
    "ReplaceIn",
    "SetExpression",
    "SourceCorrectionError",
    "correct_point",
]
