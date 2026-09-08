# Bee's Ultimate Grammar Dictionary

**ONE** unified Yomitan Japanese grammar dictionary. Every grammar source is
merged into a single installable ZIP with unified lookup and per-source
attribution — not a shelf of separate dictionaries to switch between.

Local-only unless explicitly asked to publish. The authoritative source
inventory, deck field lists, and model policy live in [`SOURCES.md`](SOURCES.md).

> **Status: pipeline skeleton.** The stage seams, packaging, reproducibility, and
> schema validation are complete and exercised end to end. No source logic exists
> yet — `make build` currently emits a valid, empty-corpus ZIP. Later cards fill
> in extractors, merge policy, and card composition.

## Quick start

```sh
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install jsonschema==4.26.0 pytest==9.1.1
npm install                 # adm-zip + ajv, for the independent Node validator

make build                  # -> build/bees-ultimate-grammar-dictionary.zip
make validate               # pinned official Yomitan schema validation (Python)
make validate-node          # the same artifact, independently (Node + ajv)
make test
```

`npm run build` / `validate` / `test` are thin wrappers over the same make
targets, so `PYTHONPATH` and the reproducibility environment are defined once.

## Pipeline

Four stages, each reading only the previous stage's on-disk artifact, so any
stage is re-runnable alone and every intermediate is inspectable:

| Stage | Target | Reads | Writes |
| --- | --- | --- | --- |
| extract | `make extract` | `data/sources/<source>/` | `data/extracted/<source>.json` |
| merge | `make merge` | `data/extracted/*.json` | `data/merged/corpus.json` |
| build | `make build` | `data/merged/corpus.json` | `build/bees-ultimate-grammar-dictionary.zip` |
| validate | `make validate` | the built ZIP | pass/fail |

`make all` runs the chain; `make clean` removes generated trees.

## Layout

```
src/bugd/
  model.py       GrammarPoint / Example — the one interchange record
  sources/       per-source extractors + normalizers (one module per source)
    base.py      Extractor contract + digest-locked source reading
    registry.py  the only place the pipeline learns which sources exist
  merge.py       cross-source unification into MergedEntry
  banks.py       the ONLY stage that knows Yomitan structured content
  styles.py      the dictionary's scoped styles.css
  package.py     reproducible ZIP packaging
  validate.py    pinned-schema validation (Python)
  pipeline.py    stage orchestration
  cli.py         python3 -m bugd.cli <stage>
scripts/validate_yomitan.mjs   independent Node/ajv validation of the same ZIP
schemas/         pinned official Yomitan schemas
data/            acquired + generated trees (see data/README.md)
tests/
```

Adding a source touches `src/bugd/sources/` only. The merge stage never learns
source-specific rules and the bank generator never learns about sources at all.

## Design constraints the skeleton enforces

- **One canonical surface.** A single structured term entry per grammar point.
  No native `kanji_bank` — validation rejects it, because Yomitan routes kanji
  clicks to a fixed unstyleable renderer that would supersede the card.
- **Progressive disclosure.** Compact above the fold; the tail (complete
  examples, per-source explanations, nuance, provenance) goes in native closed
  `details` sections. Extractors preserve the whole tail — truncation is a
  rendering decision in `banks.py`, never in an extractor.
- **Per-source attribution.** `source` is mandatory on every record and survives
  merging; `tag_bank_1.json` is generated from the per-source labels.
- **No invented content.** No LLM-generated meanings, mnemonics, etymology, or
  machine translation as dictionary fact. Source fields that *are* AI-generated
  (the `AI…` fields of the 文法 deck) are carried in a segregated
  `ai_generated` mapping and may only surface behind an explicitly labelled
  disclosure.
- **Fail closed.** A digest or byte-count mismatch on a locked source input
  aborts the build rather than shipping a quietly degraded corpus. Malformed
  payloads raise `MalformedPayload`; nothing is silently coerced.
- **Byte-reproducible artifacts.** Fixed member timestamps, permissions, sorted
  member order, canonical JSON, `PYTHONHASHSEED=0`, UTC, `LC_ALL=C.UTF-8`. Two
  builds of the same corpus produce identical bytes (verified in the suite).
- **Bounded bank shards.** At most 1,000 ordered entries per `term_bank_N.json`
  so constrained (Android) imports advance bank by bank.

## Pinned Yomitan schemas

`schemas/` holds the official schemas from
[yomidevs/yomitan](https://github.com/yomidevs/yomitan) tag **26.8.24.0**,
verified byte-identical to that tagged checkout. Their sha256 digests are
asserted in `tests/test_schemas_pinned.py`, so a silent schema swap fails the
suite. Validation runs twice against the same pinned bytes — once in Python
(`bugd.validate`) and once in Node/ajv (`scripts/validate_yomitan.mjs`) — so a
bug in one implementation is caught by the other.

Note the schema pins `isUpdatable` to `const: true` *and* makes it depend on both
`indexUrl` and `downloadUrl`. A local-only index therefore omits all three;
`build_index` only emits them together.

## Host note

`/usr/bin/node` on this machine is an empty directory shadowing the real
interpreter. GNU make execs single-word recipes directly (bypassing shell
resolution) and hits it, so the Makefile resolves `NODE` via
`command -v node`. Do not replace `$(NODE)` with a bare `node`.
