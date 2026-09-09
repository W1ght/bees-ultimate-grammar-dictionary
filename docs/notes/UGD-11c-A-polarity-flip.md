# UGD-11c-A — polarity-flipped headwords: fix and residual justification

## Defect

Twelve reviewer-confirmed cards were keyed on an affirmative surface form ending
in 〜ある while the card's reading, structure, explanation and every example teach
the FIXED-NEGATIVE pattern (〜に越したことはない, 〜どころではない, 〜までもない, …).
The affirmative is not a variant — for most of these it is not a Japanese pattern
at all — so the headword and lookup key contradict the card's own content.

The flip is UPSTREAM, in the immutable publisher term-bank bytes, and confined to
the `expression` column: the publisher's own `reading` and `definitionTags`
columns still carry the correct negative form. It is not introduced by extraction
or merge, and UGD-07's polarity guard is behaving correctly — it already refuses
to fold these affirmative/negative pairs, which is why they survive as separate
visible entries.

## Fix — one systematic rule at extraction, driven by the source's own evidence

`src/bugd/sources/polarity_repair.py` rewrites a flipped headword to its negative
form, and `CommunityBankExtractor.extract` applies it to every row of every
community source after per-source finalisation. The rule is fail-closed:

A headword is rewritten to the negative form **only when**

1. `expression` is affirmative and ends in a positive tail with a direct negative
   counterpart (`ある`→`ない`); and
2. the row's **own `reading`** is negative; and
3. flipping that tail yields a candidate whose kana skeleton is a subsequence of
   the reading (kanji in the expression expand to their reading), i.e. the
   candidate and the reading are the *same* form differing only in the tail.

The reading is the trustworthy witness because it is the publisher's phonetic
transcription of the *identical* headword — it cannot legitimately differ in
polarity from the surface. Nothing about the meaning is guessed.

On a rewrite the original affirmative surface is preserved in
`provenance.upstreamExpression` (with `provenance.polarityRepaired = "reading"`),
so the publisher's exact bytes are never lost, and the non-existent affirmative is
dropped from the lookup variants so it can't reintroduce the defect for a user.

`definitionTags` are deliberately **not** trusted to *drive* a rewrite. A tag
column routinely lists a genuinely distinct negative pattern beside an affirmative
one — 〜たことがある carries 〜たことがない, 〜に限りがある carries 〜に限りがない — so
"a negative form appears in the tags" is not evidence of a flip. Treating it as
one would corrupt those correct affirmative headwords. When the reading agrees
with the affirmative surface while the tags disagree, the evidence is in conflict
and the rule abstains.

## Effect (measured against the frozen candidate's extracted records)

`scripts/scan_polarity_flips.py` counts contributions whose 〜ある headword
contradicts its own reading:

* before the rule: **28** (all from edewakaru and nihongo_net — the two sources
  the upstream flip was traced to);
* after the rule: **0**.

All eight reviewer-confirmed cluster-A cards that are true 〜ある/〜ない flips are
among the 28 corrected (ことはある, てすむことではある, と言えなくもある, たものではある,
というものではある, どころではある ×2, に越したことはある). No genuine affirmative
(〜たことがある, 〜ことがある, 〜つつある, 〜てある, 〜恐れがある, 〜甲斐がある, 〜に限りがある …)
is touched, because their readings are affirmative and the rule requires a
negative reading to fire.

## Residual cases justified in writing

Two cluster-A cards remain unrepaired **by design**, because the publisher flipped
BOTH the `expression` and the `reading` — so the reading no longer witnesses the
negative, the reading and the definitionTags disagree, and there is no
self-consistent extraction signal left to distinguish them from a genuine
affirmative-with-a-negative-sibling. Per the fail-closed contract the rule
abstains, they stay as separate visible entries (which UGD-07's guard already
guarantees), and they are recorded here for a human to adjudicate:

| source | headword | reading (also flipped) | correct pattern | evidence |
| --- | --- | --- | --- | --- |
| donna_toki | と言ったらある | といったらある | 〜といったらない（〜ったらない／〜といったらありはしない） | structure `イＡい／Ｎ＋といったらない`; definitionTag `といったらない` |
| donna_toki | 所ではある | どころではある | 〜どころではない（〜どころじゃない） | definitionTag `どころではない`; all examples negative |

Neither 〜といったらある nor 〜どころではある is a Japanese pattern; both are the
donna_toki mirror's double-flip of a fixed-negative idiom. They are the only two
residual 〜ある headwords whose sole negative evidence lives in the tag column, and
they are left for the source-corrections track (UGD-11d-a) rather than rewritten
from the untrusted tag column here.

## Two co-located non-〜ある defects (out of this rule's scope)

Cluster-A also bundled two findings that are not 〜ある polarity flips and are not
addressed by this headword rule:

* nihongo_net `てはなる` (structure field) — a 〜てはならない vs 〜てならない content
  issue;
* nihongo_net `ばかりなく` (structure field) — a missing で: 〜ばかりでなく.

Both are formation/content defects that belong with the wrong-formation-rules
track (UGD-11c-C), not the headword-polarity rule; they are noted here only so the
partition is explicit.

## Guarantees

* UGD-07's polarity guard (`src/bugd/polarity.py`) is unchanged (byte-identical to
  HEAD) — the guard is correct; only the input it was fed was flipped.
* `tests/test_polarity_repair.py` asserts the *property* (a repaired headword's
  polarity agrees with its own reading; the rule abstains when the reading does
  not witness the flip; genuine affirmatives and reading/tag disagreements are
  left untouched), not the specific twelve strings, so a new flipped row in a
  future term-bank revision is covered without editing the test.
