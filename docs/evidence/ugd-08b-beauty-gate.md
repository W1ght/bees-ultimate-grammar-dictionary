# UGD-08b · beauty-gate re-run and finding attribution

## What the card asked for

> re-run UGD-14's beauty gate, since this adds a line to 158 cards' disclosures

Done, on candidate **v44** (`sha256 a3b06ed99bce4c3a29924846557c758ea79035cb91632b75b150d7a33330cb7a`,
1,557,731 B, 2,441 entries), built from commit `d015bb9`.

## Result

| round | build | images | mean | min | must-fix | gate |
|---|---|---|---|---|---|---|
| v44 (UGD-08b) | `a3b06ed9` | 172 / 172 scored, 0 failed | 8.08 | 6 | 13 | **fails** |
| baseline (pre-UGD-08b) | `34cebf26` (c0fa227) | 59 / 59 scored, 0 failed | 8.08 | 7 | 3 | **fails** |

The gate does not pass. **It did not pass on the parent commit either.** On the 46
tiles comparable across both rounds:

| | mean | min | must-fix |
|---|---|---|---|
| baseline | 8.07 | 7 | 3 |
| UGD-08b | 8.09 | 7 | 6 |

UGD-08b scores marginally **higher** than the bytes it replaced.

## Why v43 passed and both of these fail

UGD-14 signed off v43 at mean 8.1 / min 8 / zero must-fix over **98** images of
five entries: 間, くらい, なりとも, あいにく, 相まって.

This round reviewed **172** images of **eight** entries, adding あまり, に反して and
たい because those are the entries this change actually alters. All 13 findings land
on those newly-reviewed entries and on くらい:

| entry | tiles | must-fix | in UGD-14's v43 set? |
|---|---|---|---|
| あまり | 36 | 5 | no — added by this round |
| たい | 18 | 5 | no — added by this round |
| くらい | 44 | 2 | yes |
| に反して | 24 | 1 | no — added by this round |
| 間 | 22 | 0 | yes |
| なりとも | 12 | 0 | yes |
| あいにく | 8 | 0 | yes |
| 相まって | 8 | 0 | yes |

So the gate did not regress; **the sample grew** and the larger sample exposes
corpus defects on entries nobody had reviewed before.

## Attribution: none of the 13 findings is a UGD-08b regression

Three independent lines of evidence.

### 1. No finding mentions the feature

Zero of the 13 must-fix reports (and zero of the baseline's 3) refer to a JLPT
level, the `sourceLevel` row, or level disagreement. Every one names example
formatting, pattern-list run-ons, or clipped/whitespace prose.

### 2. The packaged bytes are otherwise unchanged (`probe/p10_delta_final.py`)

Diffing the two archives structurally, headword by headword:

```
baseline 2414 cards, new 2414 cards

cards byte-identical to baseline once level rows are stripped: 2315
cards that gained a disclosure:                               99
  ... gained disclosures containing ONLY a level:             99
problems:                                                     0
```

Outside the level rows UGD-08b changed **no** card content: no reordering, no lost
sense, no altered prose, no lost disclosure. The only structural addition is 99
level-only disclosures — the documented fix for a source that asserts a level and
nothing else. `probe/p07_runon_bytes.py` shows the same per string: the only
strings added to あまり and に反して are `JLPT `, ` · ` and the level codes.

This property is now a permanent regression:
`test_the_level_row_is_the_only_thing_this_change_adds_to_a_card`.

### 3. The baseline reproduces the findings

The decisive check. The same tiles were captured from the **pre-UGD-08b** build and
scored with the same rubric (minus the clause describing level rows, which do not
exist there). The baseline independently produced the same three defect families on
the same tiles — including a verbatim match:

| tile | baseline | UGD-08b |
|---|---|---|
| あまり-light-desktop-open--part3of7 | 7/10 — "Example boxes concatenate two separate sentences … with no visual separator, creating run-on unbroken text" | 7/10 — "Two example sentences are concatenated with no visual separator inside the same shaded box … reading as one run-on line" |
| たい-light-desktop-open--part2of3 | 7/10 — "「もの」シリーズ list mashes many distinct grammar patterns into continuous run-on lines" | 7/10 — same list, same complaint |
| たい-light-desktop-open--part3of3 | 8/10 — "'→たばこは高いし 体に悪いし、' … ends abruptly mid-sentence … suggesting the continuation text is clipped" | 8/10 — same line, same complaint |

## What the findings actually are

Corpus/extractor defects, exactly the class the skill warns appears once layout is
sound. Three families:

1. **Run-on paraphrase pairs** (findings 1, 2, 4, 5, 13) — a source ships an example
   and its とても〜ので paraphrase in one field with no separator. `_TURN_SEPARATOR`
   and `_SPEAKER_TURN` handle dialogue turns; this is a *paraphrase* pair and no rule
   covers it.
2. **Run-on pattern lists** (findings 8, 11) — the 「もの」シリーズ cross-reference list
   arrives as one `・`-joined run.
3. **Clipped/whitespace prose** (findings 3, 6, 7, 9, 10, 12) — a paraphrase ending at
   a comma, examples inconsistently boxed, double-space gaps.

Each needs a corpus-wide count before a rule is chosen (per the skill: "count each
pattern across the corpus before choosing a rule, and keep the rule narrow enough to
spare legitimate look-alikes"). That is extractor work on three sources, not
renderer work, and it is out of this card's scope — filed as a follow-up rather than
scope-crept into a JLPT-disclosure card.

## Real-host evidence for the feature itself

`harness/probe-source-level.mjs`, measured in real Yomitan 26.8.24.0:

* **に反して** — 絵でわかる日本語 `JLPT N3`, 日本語NET `JLPT N3`, 毎日のんびり `JLPT N2`.
  The exact disagreement the card described, now readable per source.
* **あまり** — 絵でわかる日本語 `JLPT N5 · N2`, 日本語NET `JLPT N5 · N2`,
  毎日のんびり `JLPT N3`. All three dataset levels visible.
* **たい** — 日本語NET `JLPT N5` in its own disclosure beside 絵でわかる `JLPT N2`;
  4 source blocks where the baseline had 3.

Every row: `painted: true`, `isFirstInBody: true`, 12.04px against 14–17.64px body
text, contrast **11.71:1** on its real composited backdrop, `withinCard: true`,
card overflow **0px**. Compact badge still exactly one value on all 158 conflicts.

Vision reading of `たい-light-desktop-open` confirms the level-only disclosure reads
as intentional: "visually identical in structure to the other source sections … the
body is genuinely non-empty — it carries real information … Nothing is clipped,
mis-nested, or overlapping."
