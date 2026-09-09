# Normalize-stage source fix-up table (UGD-11a)

The 文法 (`文法.apkg`) and Bunpro (`Bunpro Grammar Reference.apkg`) decks carry a
small number of **genuine** content defects that a per-kanji or whole-word
furigana check cannot repair on its own, because the correct fix depends on the
intended word. Rather than re-authoring the source decks, the extract/normalize
stage applies the audited fix-up table in `src/bugd/furigana_fixups.py` to raw
field HTML **before** it becomes Yomitan structured content.

All rules were verified against the raw `collection.anki21b` HTML of both decks
(170,013 `<ruby>` pairs total; 98.6% passed a KANJIDIC2 + UniDic n-best
cross-check cleanly). The fix-up pass is **idempotent** — running it twice is a
no-op.

## Integration seam

An extractor calls, per field:

```python
from bugd.furigana_fixups import normalize_furigana, normalize_jlpt_field

html = normalize_furigana(raw_field_html)          # ruby typo fixups + empty-ruby repair
level, jlpt_note = normalize_jlpt_field(raw_jlpt)  # -> GrammarPoint.jlpt + .notes
```

`normalize_furigana` runs `apply_ruby_fixups` (typo table) then
`repair_empty_ruby` (unwrap empty `<rt>`). `normalize_jlpt_field` returns a
validated `(level, note)` pair; `level` feeds `GrammarPoint.jlpt`, `note` (when
present) is appended to `GrammarPoint.notes`.

## 1. Ruby-pair typo fix-ups (Bunpro)

`<ruby>BASE<rt>WRONG</rt></ruby>` → `<ruby>BASE<rt>RIGHT</rt></ruby>`. Each rule
is keyed on **both** the base kanji and the exact wrong reading, so it can never
touch a legitimate pair. Every wrong pair occurs 1–6 times while its correct
counterpart occurs hundreds/thousands of times in the same deck — unambiguous
registration typos, not alternate readings.

| base | wrong `rt` | correct `rt` | occ. | notes | rationale |
|------|-----------|--------------|-----:|-------|-----------|
| 思 | あも | おも | 6 | 1776847270804, 1776847271010 | char-swap お⇄あ; 「…と思(おも)います」 |
| 私 | またし | わたし | 3 | 1776847271046 | char-swap わ⇄ま; 「私(わたし)のコレクション」 |
| 学 | なな | まな | 3 | 1776847271278 | char-swap ま⇄な; 学(まな)ぶ |
| 対 | つか | たい | 1 | 1776847270608 | 「動詞に対(たい)して」; keyed on 対 so the correct 使(つか) beside it is untouched |
| 使 | かた | つか | 1 | 1776847270716 | 「使(つか)い方(かた)」; the following 方 reading had leaked onto 使 |

Total: **14 occurrences across 6 notes.** After the pass the genuine-typo count
across both decks drops to **0** with the total well-formed ruby-pair count
unchanged (152,451 in Bunpro, 17,545 in 文法).

## 2. Empty / missing `<rt>` repair (文法)

16 `<ruby>BASE</ruby>` wrappers in 文法 have no `<rt>` child, which renders as a
blank gap in Yomitan. They are **unwrapped to clean surface text** — the
fail-closed choice that preserves the kanji exactly and invents no reading
(per `yomitan-dictionary-engineering`: "malformed ruby should fall back to
clean surface text"). Bases: 方法, 読, 料理 (note 1645020271779); 同, 同時, 勉強
×?, 見 ×?, 電話, 車, 朝, 食, 大学 (note 1645197734389); 相手, 健康の (note
1646481788889). `健康の` had the particle inside the base and unwraps to the
same plain `健康の`, so the の survives as ordinary text. After the pass 文法 has
**0** empty ruby and its well-formed ruby pairs are unchanged.

## 3. JLPT field normalization (文法)

`normalize_jlpt_field(raw) -> (level, note)`:

* `"<div><div><div>N3</div></div></div>"` (note 1647069276306) → `("N3", None)` —
  nested wrapper divs stripped, not carried into the badge as markup.
* `"N4<br>※N4では意味①のみ扱う。"` (note 1645780617415) →
  `("N4", "N4では意味①のみ扱う。")` — level split from footnote.
* Clean `"N5"` / `"N2"` → `("N5", None)` / `("N2", None)`; empty → `(None, None)`.
* A token outside N1..N5 is returned as note text, never guessed into a badge.

## Deliberately NOT corrected — documented false positives

These were flagged by the naive per-kanji check but are **correct** jukujikun /
contracted-compound furigana and are left as-is, per the card's guardrail
("structural jukujikun / productive-suffix items are NOT defects"):

* `美味` rt=`おい` — 美味しい is おいしい; 美味→おい is the whole-word jukujikun
  label with `し…` as okurigana. Consistent across all 236 occurrences.
  Extending the base to include the kana `し` would put kana inside the ruby
  base, which is itself malformed.
* `二日酔`/`ふつかよ`(+い), `打合`/`うちあわ`(+せ), `組合`/`くみあわ`(+せ),
  `一人暮`/`ひとりぐら`(+し), `見出`/`みいだ`(+せない), `一度評価` — the trailing
  okurigana is present as plain text immediately after the ruby, so the surface
  word reads correctly; only the per-kanji check fails on the contracted
  compound reading.
