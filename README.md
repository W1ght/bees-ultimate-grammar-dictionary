# Bee's Ultimate Grammar Dictionary

A unified Japanese grammar dictionary for [Yomitan](https://github.com/yomidevs/yomitan). Combines **12 sources** into a single installable dictionary with unified lookup and per-source attribution.

## Install

1. Download the latest `.zip` from [Releases](https://github.com/bee-san/bees-ultimate-grammar-dictionary/releases)
2. In Yomitan settings, go to Dictionaries → Import
3. Select the downloaded ZIP

## What's included

Every grammar point shows a compact card with progressive disclosure — click to expand per-source details, extra examples, and provenance.

### Sources

| Source | Name | Language | Description |
|--------|------|----------|-------------|
| DoJG | 日本語文法辞典(全集) | EN | Dictionary of Japanese Grammar (Basic/Intermediate/Advanced) |
| HJGP | 日本語文型辞典 | JA | A Handbook of Japanese Grammar Patterns — monolingual |
| HJGP EN | 日本語文型辞典 英語版 | EN | A Handbook of Japanese Grammar Patterns — English edition |
| NINJAL | 日本語文型データベース | JA | National Institute for Japanese Language and Linguistics grammar pattern database |
| 日本語NET | JLPT文法解説まとめ | JA | JLPT grammar explanations from nihongokyoshi-net.com |
| 絵でわかる | 絵でわかる日本語 | JA | Japanese grammar explained through illustrations |
| Donna Toki | どんなときどう使う 日本語表現文型辞典 | EN/JA | "When and How to Use" expression pattern dictionary |
| 日本語教師 | 毎日のんびり日本語教師 | JA/ZH | Grammar explanations for Japanese teachers |
| Bunpro | Bunpro Grammar Reference | EN | SRS-based grammar reference |
| 文法 | 文法 | JA | Personal grammar Anki deck |
| IMABI | IMABI | EN | Comprehensive Japanese grammar lessons (modern + classical) |
| Yokubi | Yokubi | EN | The Common Grammar Guide (yoku.bi) |

### What makes this different from installing them separately?

- **Single lookup**: one dictionary, one card per grammar point — not 12 separate popups
- **Merged entries**: when multiple sources describe the same grammar point, their contributions are merged into one card with per-source attribution
- **Deduplication**: the keymap stage aligns entries across sources so you don't see the same point repeated
- **Progressive disclosure**: compact by default, expand any source's details on demand

## Building from source

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make all
```

The pipeline stages:

1. **extract** — read each source's locked data into normalized `GrammarPoint` records
2. **keymap** — align entries across sources (which rows are the same grammar point?)
3. **merge** — combine aligned entries into a unified dataset
4. **build** — render the Yomitan dictionary ZIP
5. **validate** — verify against Yomitan's JSON schemas

## Adding a new source

1. Place source data in `data/sources/<name>/` with a `SOURCE.lock.json`
2. Write an extractor in `src/bugd/sources/<name>.py` (see existing extractors for patterns)
3. Register it with `@register_extractor`
4. Add to `SOURCE_PRECEDENCE` in `keymap.py` and `_SOURCE_EXPLANATION_LANG` in `banks.py`
5. Run `make all`

## License

Dictionary content retains its original licensing from each source. The build pipeline code is MIT.
