# Bee's Ultimate Grammar Dictionary

**ONE** unified Yomitan Japanese grammar dictionary. Ten grammar sources are
merged into a single installable dictionary with unified lookup and per-source
attribution — not a shelf of separate dictionaries to switch between.

Look up `に反して` once and get all ten sources' explanations of it, each labelled
with who said it, in one card.

---

## Install

1. Download `bees-ultimate-grammar-dictionary.zip` from
   [Releases](../../releases).
2. Open Yomitan → **Settings** → **Dictionaries** → **Import**.
3. Select the ZIP. It imports as ONE dictionary.

Requires Yomitan 26.8.24.0 or newer (the schema revision this build validates
against).

### What's in it

- **4,901 entries** — 2,943 grammar-point cards plus 1,958 redirect cards, so an
  alternative spelling still finds its point.
- **6,656 source contributions** across 4,481 senses. 1,028 entries carry more
  than one source; 104 carry five, and 10 carry nine.
- **71,973 example sentences**, 40,568 with the source's own English translation
  and 40,549 with the grammar point highlighted exactly where the source marked
  it.
- **1,601 entries carry a JLPT level.** On the 253 where sources disagree, every
  source's level is shown against that source — nothing is averaged or voted on.
- `sha256` of the published asset is recorded on the release, and the build is
  byte-reproducible: repeated builds from the same locked bytes produce the
  identical archive.

---

## Sources

Every record carries its source's label, and every card shows it on the section
that source contributed. Counts are from the real build
(`data/merge/unified.stats.json`).

| Source | Contributions | Entries | Examples |
| --- | --- | --- | --- |
| [Bunpro](https://bunpro.jp) | 964 | 928 | 16,361 |
| [IMABI](https://imabi.org) | 494 | 491 | 18,660 |
| [DoJG 日本語文法辞典](https://github.com/aiko-tanaka/Grammar-Dictionaries) | 534 | 500 | 4,917 |
| どんなときどう使う 日本語表現文型辞典 | 660 | 520 | 2,616 |
| [Yokubi — The Common Grammar Guide](https://yoku.bi) | 132 | 117 | 294 |
| [日本語文型データベース (NINJAL)](https://doi.org/10.15084/0002000610) | 800 | 765 | 9,552 |
| [絵でわかる日本語](https://www.edewakaru.com/) | 1,178 | 915 | 4,649 |
| [日本語NET](https://nihongokyoshi-net.com/) | 627 | 584 | 3,055 |
| 毎日のんびり日本語教師 | 733 | 685 | 6,173 |
| 文法 (`bunpou`) | 534 | 502 | 5,696 |

English-explaining sources are ordered first on a card, then the monolingual
Japanese ones.

---

## Build it yourself

```sh
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -e .
npm install                 # adm-zip + ajv, for the independent Node validator

make                        # the dictionary — extract, keymap, merge, build, validate
make test
```

`make` on its own builds the whole dictionary from every source
`data/sources/` actually holds. Extraction skips (with a reason) any source whose
locked bytes are not acquired, so a partial checkout still builds — it just
builds a smaller dictionary.

Acquired source bytes are **not** in this repository — they are large and
regenerable. What IS committed is every source's
`data/sources/<source>/SOURCE.lock.json`: a byte-for-byte digest manifest (611
files pinned in total) so an acquisition that drifts fails the build instead of
silently shipping different content.

Yokubi has an acquisition script (`scripts/acquire_yokubi.py`), as do the
community term-bank sources (`scripts/acquire_community_grammar.py`) and IMABI
(`scripts/acquire_imabi.py`). NINJAL is a manual download — put
`nihongo_bunkei_database20260126.zip`, `headwords.txt` and `readme.txt` from the
[dataset's DOI page](https://doi.org/10.15084/0002000610) into
`data/sources/ninjal_bunkei/` and the lock verifies them. The remaining sources
are local exports you supply yourself into `data/sources/<source>/`, matching
that source's lock.

### Stages

```
extract   data/sources/<source>/    ->  data/extracted/<source>.json
keymap    data/extracted/           ->  data/merge/keymap.json + AMBIGUITY.md
merge     keymap + extracted        ->  data/merge/unified.jsonl (+ stats)
                                        data/merged/corpus.json
build     merged corpus             ->  build/…zip  (+ dist/)
validate  the built ZIP             ->  pinned Yomitan schemas
```

Each stage reads only the previous stage's on-disk artifact, so any stage can be
re-run independently and every intermediate is inspectable.

`dist/` holds the published artifact, its `SHA256SUMS`, and `index.json`.
`index.json` is committed: the archive's own `indexUrl` points at it, so an
update checker (and Hachidori's dictionary installer) can read the current
revision without downloading the whole dictionary.

### Gates

| Command | What it proves |
| --- | --- |
| `make validate` | the archive matches the pinned official Yomitan schemas (Python) |
| `make validate-node` | the same archive, independently (Node + ajv) |
| `make audit-packaged` | the archive carries the WORK: per-source attribution, working redirects, each source's own JLPT level on the 253 entries whose sources disagree |
| `make audit-attribution` | every claim a card makes traces to ONE coherent source row, and each claim handle names a unique row |
| `make scan-polarity` | no headword contradicts its own reading |
| `python scripts/check_example_runons.py <zip>` | no example renders as a run-on (real run-ons: 0) |
| `python docs/contract/validate.py` | the card's structured-content shape contract |
| `make test` | the suite, including a real-Yomitan import/geometry harness |

`schemas/` holds the official schemas from
[yomidevs/yomitan](https://github.com/yomidevs/yomitan) tag **26.8.24.0**, with
their sha256 digests asserted in the suite, so a silent schema swap fails.
Validation runs twice against the same pinned bytes — once in Python, once in
Node/ajv — so a bug in one implementation is caught by the other.

---

## How the merge works

Four ideas do most of the work:

**One canonical surface.** A single structured term entry per grammar point. No
native `kanji_bank` — validation rejects it, because Yomitan routes kanji clicks
to a fixed unstyleable renderer that would supersede the card.

**Sources are never reconciled.** When two sources disagree, both statements
ship, each attributed to whoever made it. 253 entries carry conflicting JLPT
levels; the card shows each source's level where that source speaks, and the
compact line stays one row. Nothing is voted on or averaged.

**Progressive disclosure.** Compact above the fold; the complete tail (all
examples, each source's explanation, nuance, provenance) sits in native closed
`<details>` sections. Extractors preserve the whole tail — truncation is a
rendering decision, never an extraction one.

**Nothing is invented.** No LLM-generated meanings, mnemonics, etymology, or
machine translation as dictionary fact. Highlights mark only substrings the
source itself marked. Source fields that *are* AI-generated (the 文法 deck's
`AI…` fields) are carried in a segregated channel and are asserted absent from
the packaged bytes.

Corrections to source defects live in reviewable, byte-anchored overlays under
`data/corrections/` — not hand-edits, because the source bytes are digest-locked.
Each correction fails the build closed if its anchor no longer matches, so a
drifted source can never silently ship an unreviewed edit.

### Each source's markup is part of its content

A producer's prose is written in that producer's notation, and the notation
carries meaning: a table is a table because the author laid it out as one.
`src/bugd/dialects.py` is the one place that knows which notation a given source
writes.

Measured over the whole corpus, the ten sources divide into two dialects:

- **Yokubi writes GitHub-flavoured Markdown** — 44 pipe tables (conjugation
  grids, casual/polite pairs), 180 bold runs, 28 italic runs, 48 bullets, 26
  lesson links, and 149 backslash escapes. It now renders as real
  `table`/`ul`/emphasis nodes. Previously a card showed literal `**asterisks**`,
  a bare `|---------------|` separator as body text, and — because an escaped
  `\<verb\>` placeholder reached the HTML parser as a tag opening — silently
  dropped the rest of that paragraph.
- **Every other source writes plain text**, plus real HTML in two cases:
  NINJAL's `<s>ます</s>` omission markers and どんなとき's `<ruby>` furigana. Both
  already render correctly through the shared converter, so they deliberately get
  no dialect of their own. Their other conventions are structural rather than
  markup and are handled downstream: `【…】` section headings, `①②③` / `１）２）`
  list breaks, and the hard line breaks a source leaves behind when an inline
  highlight is stripped (92% of 絵でわかる日本語's single newlines fall mid-sentence)
  which the shared soft-wrap rule rejoins script-awarely.

IMABI's 17,549 `N. ` example lines and 145 `*` footnote markers are deliberately
**not** treated as Markdown: its own prose cross-references those numbers as
`Ex. N`, so rendering them as an ordered list would renumber them.

### Layout

```
src/bugd/
  model.py               GrammarPoint / Example — the one interchange record
  sources/               per-source extractors (one module per source)
  keymap.py              cross-source canonical key assignment
  unify.py               the merge policy
  dialects.py            per-source prose markup dialects
  banks.py               the ONLY stage that knows Yomitan structured content
  styles.py              the dictionary's scoped styles.css
  package.py             reproducible ZIP packaging
  pipeline.py / cli.py   stage orchestration
scripts/                 acquisition, keymap build/audit, packaged-bytes audits, validators
scripts/audit/           attribution coherence/precision probes and their mutation runners
schemas/                 pinned official Yomitan schemas
docs/contract/           the card shape contract + its golden files
tests/                   unit, corpus, and real-Yomitan harness suites
```

Adding a source touches `src/bugd/sources/` only, plus `dialects.py` if it writes
a notation no existing source does. The merge stage never learns source-specific
rules and the bank generator never learns about sources at all.

---

## Licence

The build pipeline in this repository is MIT (see [LICENSE](LICENSE)). Dictionary
content belongs to the source that wrote it, and every card names that source.
