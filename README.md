# Bee's Ultimate Grammar Dictionary

**ONE** unified Yomitan Japanese grammar dictionary. Ten grammar sources are
merged into a single installable dictionary with unified lookup and per-source
attribution — not a shelf of separate dictionaries to switch between.

Look up `に反して` once and get all ten sources' explanations of it, each labelled
with who said it, in one card.

---

## Two artifacts, and the difference matters

This repository produces **two different dictionaries from the same code**:

| | sources | entries | who can have it |
| --- | --- | --- | --- |
| **Public release** (`make public`) | 2 — the CC BY 4.0 ones | 1,550 | anyone; attached to [Releases](../../releases) |
| **Full local build** (`make all`) | 10 | 4,901 | you, from sources you have your own right to use |

Eight of the ten sources are **not publicly redistributable** (see
[LICENSING.md](LICENSING.md)). So the released ZIP is built through a fail-closed
redistribution filter that keeps only records whose own provenance grants public
redistribution. The other eight never reach the published bytes — that is
machine-enforced and independently re-checked in the packaged archive, not a
promise.

If you have your own licensed copies of the other sources (your own Bunpro
export, the 文法 deck, etc.), acquire them locally and `make all` gives you the
full 4,901-entry dictionary. Nothing about that build is published.

---

## Install (public release)

1. Download `bees-ultimate-grammar-dictionary.zip` from
   [Releases](../../releases).
2. Open Yomitan → **Settings** → **Dictionaries** → **Import**.
3. Select the ZIP. It imports as ONE dictionary.

Requires Yomitan 26.8.24.0 or newer (the schema revision this build validates
against).

### What's in the public release

- **1,550 entries** — 832 grammar-point cards + 718 redirect cards so an
  alternative spelling still finds its point.
- **932 source contributions**, 897 senses, 50 entries where both sources
  contribute to the same point.
- **9,846 example sentences**, 9,808 of them with the grammar point highlighted
  exactly where the source marked it.
- `sha256` of the published asset is recorded on the release, and the build is
  byte-reproducible: three consecutive builds from the same locked bytes produce
  the identical archive.

---

## Sources and attribution

Every record carries its source's attribution, and every card shows it on the
contributed section. Counts are from the real build (`data/merge/unified.stats.json`).

### In the public release

| Source | Licence | Contributions | Entries | Examples | Attribution as shipped |
| --- | --- | --- | --- | --- | --- |
| [日本語文型データベース (NINJAL)](https://doi.org/10.15084/0002000610) | **CC BY 4.0** — declared in the source's own `readme.txt` | 800 | 765 | 9,552 | 日本語文型データベース, 国立国語研究所 研究系 |
| [Yokubi — The Common Grammar Guide](https://yoku.bi) | **CC BY 4.0** — `LICENSE` + `src/Credits.md` in the source repo | 132 | 117 | 294 | Yokubi — The Common Grammar Guide (https://yoku.bi), CC BY 4.0 |

Both are transformed: prose is re-segmented into Yomitan structured content.
CC BY 4.0 requires indicating changes, and that is the change.

### Local build only — NOT published

| Source | Contributions | Entries | Examples | Why it is not in the release |
| --- | --- | --- | --- | --- |
| [IMABI](https://imabi.org) | 494 | 491 | 18,660 | The authors' approval is on record as a **user report**; `imabi.org/terms/`, `/license/` and `/copyright/` all 404, so no document corroborates it. LICENSING.md's instruction is to obtain it in writing first. |
| Bunpro | 964 | 928 | 16,361 | Proprietary paid service; its ToS asserts copyright and grants nothing. |
| 文法 (`bunpou`) | 534 | 502 | 5,696 | A private personal Anki deck; rights in the underlying content are not established. |
| [DoJG 日本語文法辞典](https://github.com/aiko-tanaka/Grammar-Dictionaries) | 534 | 500 | 4,917 | Verbatim from The Japan Times' print volumes; upstream repo is unlicensed. |
| どんなときどう使う 日本語表現文型辞典 | 660 | 520 | 2,616 | Same: derivative of a commercial print dictionary, unlicensed upstream. |
| [絵でわかる日本語](https://www.edewakaru.com/) | 1,178 | 915 | 4,649 | Producer publishes only platform terms, not a content-reuse grant. |
| [日本語NET](https://nihongokyoshi-net.com/) | 627 | 584 | 3,055 | Producer footer asserts all rights reserved. |
| 毎日のんびり日本語教師 | 733 | 685 | 6,173 | Producer's 利用規約 is no longer obtainable. |

Full per-source basis, required attribution string, and redistribution posture:
**[LICENSING.md](LICENSING.md)**.

---

## Build it yourself

```sh
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -e .
npm install                 # adm-zip + ajv, for the independent Node validator

make public                 # the redistributable-only release artifact
make all                    # the full local dictionary (needs all ten sources)
make test
```

Acquired source bytes are **not** in this repository — they are large,
regenerable, and mostly not redistributable. What IS committed is every source's
`data/sources/<source>/SOURCE.lock.json`: a byte-for-byte digest manifest (611
files pinned in total) so an acquisition that drifts fails the build instead of
silently shipping different content.

Yokubi has an acquisition script (`scripts/acquire_yokubi.py`), as do the
community term-bank sources (`scripts/acquire_community_grammar.py`). NINJAL is a
manual download — put `nihongo_bunkei_database20260126.zip`, `headwords.txt` and
`readme.txt` from the [dataset's DOI page](https://doi.org/10.15084/0002000610)
into `data/sources/ninjal_bunkei/` and the lock verifies them. The remaining
sources are local exports you supply yourself into `data/sources/<source>/`,
matching that source's lock; `make public` needs none of them.

### The public build, stage by stage

```
publish-filter   data/extracted/*.json   ->  data/extracted-public/*.json
keymap           data/extracted-public/  ->  data/merge-public/keymap.json
merge            keymap + extracted      ->  data/merged-public/corpus.json
build            merged corpus           ->  build-public/…zip  (+ dist-public/)
validate         the built ZIP           ->  pinned Yomitan schemas
audit-public     the built ZIP           ->  no excluded source's bytes
```

Every stage after the filter is the **same code** the local build runs, pointed
at a different directory — so the public artifact cannot drift away from the one
the tests and audits cover.

### Gates

| Command | What it proves |
| --- | --- |
| `make validate` | the archive matches the pinned official Yomitan schemas (Python) |
| `make validate-node` / `public-validate-node` | the same archive, independently (Node + ajv) |
| `make audit-packaged` | the local archive carries the WORK: per-source attribution, working redirects, each source's own JLPT level on the 253 entries whose sources disagree |
| `make audit-public` | the public archive contains **zero** bytes from any excluded source, every admitted source is present *and* attributed, and the filter admitted exactly the set LICENSING.md clears |
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
ship, each attributed to whoever made it. 253 entries in the local build carry
conflicting JLPT levels; the card shows each source's level where that source
speaks, and the compact line stays one row. Nothing is voted on or averaged.

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

### Layout

```
src/bugd/
  model.py               GrammarPoint / Example — the one interchange record
  sources/               per-source extractors (one module per source)
  keymap.py              cross-source canonical key assignment
  unify.py               the merge policy
  banks.py               the ONLY stage that knows Yomitan structured content
  publish_filter.py      the fail-closed redistribution gate
  styles.py              the dictionary's scoped styles.css
  package.py             reproducible ZIP packaging
  pipeline.py / cli.py   stage orchestration
scripts/                 acquisition, keymap build/audit, packaged-bytes audits, validators
scripts/audit/           attribution coherence/precision probes and their mutation runners
schemas/                 pinned official Yomitan schemas
docs/contract/           the card shape contract + its golden files
tests/                   unit, corpus, and real-Yomitan harness suites
```

Adding a source touches `src/bugd/sources/` only. The merge stage never learns
source-specific rules and the bank generator never learns about sources at all.

---

## Licence

The build pipeline in this repository is MIT (see [LICENSE](LICENSE)).

Dictionary **content** is licensed by its own source. The published release
contains only CC BY 4.0 content and carries each source's required attribution in
`index.json`, in `tag_bank_1.json`, and on every contributed card section. See
[LICENSING.md](LICENSING.md) for the per-source audit.
