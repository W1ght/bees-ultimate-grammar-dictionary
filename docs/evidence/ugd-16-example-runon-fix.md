# UGD-16 — Example-sentence run-on fix

Beauty-gate must-fix: many EXAMPLE sentences rendered as run-ons — two or more
declarative sentences packed into one field with no visual separator, displayed
as a single mashed line under the example's `white-space: pre-line` CSS.

## The fix

**Where:** `src/bugd/banks.py`. A new helper `_split_example_sentences` is applied
in `_examples_section` to the Japanese span **after** `_split_dialogue_turns`
(dialogue splitting), exactly mirroring how dialogue speaker turns already become
`<br>` line breaks:

```python
"content": _split_example_sentences(
    _split_dialogue_turns(
        _highlight_sentence(japanese, example.highlight)
    )
),
```

**Boundary rule.** Insert a `<br>` at a sentence boundary WITHIN a single example
field, where a boundary is:

- a sentence-final mark `。` / `！` / `？`
- immediately followed by the **start of a new Japanese sentence** — a hiragana,
  katakana, CJK-ideograph or CJK-compatibility-ideograph character
  (`[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff\uf900-\ufaff]`)
- while **no quotation or parenthetical is open**.

Conservative guards (do NOT split):

- A `。` **inside a quotation** `「…。…」` / `『…。…』` — part of the quoted
  utterance, not a boundary between two example sentences. Quote depth is tracked.
- A `。` **inside a parenthetical** `（…）` / `(...)` — sources append a translation
  or aside there; a Chinese gloss `（内容有误。非常抱歉。）` uses CJK punctuation that
  would otherwise be mis-split into surrounding Japanese.
- A **trailing** `。` (end of field) — nothing new follows, so no break.
- A `。` **before the English/Chinese translation, before `→`, before a digit or a
  space** — the lookahead requires a Japanese sentence-start, so none of these match.
- A boundary that would fall **inside a highlight/ruby node** — the helper only
  splits string fragments; highlight/ruby nodes pass through untouched, exactly as
  `_split_dialogue_turns` does. A boundary at a fragment **edge** (`…じゃん。`
  followed by a highlight span opening the next sentence) still breaks, because the
  `<br>` is emitted **between** the fragments, not inside the node.

Deterministic: the same input always yields the same node list (no set/hash
iteration), so the build stays byte-reproducible.

## Before / after run-on counts

Measured with `scripts/check_example_runons.py` (committed): it loads the built
ZIP, walks every example `<li>` (`data == {"example": ""}`), reads only the
Japanese span (`data.ja`) — so a `。` before the English translation never counts —
and flags nodes with **≥2 sentence-final marks each followed by kana/kanji AND
zero `<br>`**.

| measure | before | after |
|---|---|---|
| example run-on nodes (≥2 JA sentence boundaries, 0 `<br>`) | **201** | **58** |
| — of which every boundary is inside a quote/paren (NOT a real run-on) | — | **58** |
| — **REAL run-ons** (a splittable boundary outside any quote) | **201** | **0** |

The task's original baseline of 8773 was measured against an earlier corpus state
in which multi-sentence content arrived concatenated into a single `japanese`
field; the current integrated corpus already stores many of those as separate
example rows, so the pre-fix real-run-on population on this build is 201. After the
fix, **the real (splittable) run-on count is 0.**

### Residual (58) — why they are not real run-ons

Every residual node has **all** of its sentence boundaries inside a quotation or a
parenthetical, so leaving them unsplit is correct:

- `「ご心配は要りません。私のほうでやります。」「どうもありがとうございます！本当に助かります！」`
  — the `。`/`！` sit inside quoted utterances.
- `子「今日の…中止になっちゃった。今日のために…」父「そりゃ…ってもんだ」`
  — role-speaker dialogue; every `。` is inside a `「…」` quote.
- `彼は…あわせる。「世の中に…気がするんです。…消えちゃうんです。…」`
  — one narration sentence plus a long single quoted monologue; the boundaries
  live inside the quote.

These are single quoted utterances, not two independent example sentences mashed
together, and the caution explicitly says a `。` inside `「…。…」` must not split.

## Concrete before → after renderings

`BEFORE` is the old pipeline output (`_split_dialogue_turns(_highlight_sentence(...))`);
`AFTER` is with `_split_example_sentences` applied. A `{"tag":"br"}` renders as a
real line break under `white-space: pre-line`.

**1. Directions** (`道に迷いました。銀行を探しています。どうすれば行けますか。`)

```
BEFORE: "道に迷いました。銀行を探さがしています。どうすれば行けますか。"
AFTER : ["道に迷いました。", {br}, "銀行を探さがしています。", {br}, "どうすれば行けますか。"]
```

**2. Simultaneous Action (…ながら…)** — the `AながらB` case

```
SRC   : 何だよ。静かだと思ったら、テレビを見｛〇 ながら・X つつ｝寝ちゃって。おい、風邪引くぞ。(男性語)
BEFORE: "何だよ。静かだと思ったら、…寝ちゃって。おい、風邪引くぞ。(男性語)"
AFTER : ["何だよ。", {br}, "静かだと思ったら、テレビを見｛〇 ながら・X つつ｝寝ちゃって。", {br}, "おい、風邪引くぞ。(男性語)"]
```

The trailing `(男性語)` annotation stays attached to the last sentence — the paren
is not split, and the `。` before the paren is trailing so it does not break.

**3. Agent Marker Ni** — three declarative sentences (ruby preserved)

```
BEFORE: "…開発かいはつを進すすめている。位置いちが少すこし…するものだ。ピッチでは…できる。"
AFTER : ["…開発かいはつを進すすめている。", {br}, "位置いちが少すこし…するものだ。", {br}, "ピッチでは…できる。"]
```

**4. `もの` — boundary at a highlight-span edge (Chinese gloss NOT split)**

```
SRC     : 諦めてもいいじゃん。だって辛いんだもん。（放弃也可以。因为很辛苦嘛。）
highlight: ["だって","もん"]
AFTER   : ["諦めてもいいじゃん。", {br}, <hl だって>, "辛いんだ", <hl もん>, "。（放弃也可以。因为很辛苦嘛。）"]
```

The first boundary falls at the edge of a highlight span (`。` ends the string,
`だって` opens the next sentence inside a highlight node) — the `<br>` goes between
the fragments. The Chinese translation `（…。…）` is left intact because it is inside
a parenthetical.

## Gates

- **Byte-stability:** `bugd.cli build` run twice → identical
  `sha256 = 2520b72f54c7cedd4747929153fe3dec997ce2d1dc6cb2608cd6ec01e2916124`
- **Tests:** `pytest -q` → **499 passed** (1 pre-existing warning), no regression,
  no test needed re-pinning.
- **Schema:** `make validate-node` → *Yomitan validation passed* (index + 5 term
  banks + tag bank, 4632 term entries).
- **Contract gate:** `docs/contract/validate.py docs/contract/golden` → **OK: 0 invalid**
  (all 8 golden fixtures PASS).
