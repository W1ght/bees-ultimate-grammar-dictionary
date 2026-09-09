# Bee's Ultimate Grammar Dictionary

**ONE** unified Yomitan Japanese grammar dictionary. Ten grammar sources are
merged into a single dictionary with unified lookup and per-source attribution —
not a shelf of separate dictionaries to switch between.

This repository ships the **full, reproducible build pipeline** (extractors,
cross-source keymap, merge policy, Yomitan bank generation, fail-closed schema +
contract gates, and tests). You build the installable dictionary locally from
your own copies of the sources.

## What it is

A `make all` run extracts every source, folds cross-source orthographic/reading
variants into one canonical lookup key, merges contributions with per-source
attribution (conflicting JLPT levels and differing formation rules are preserved,
not silently reconciled), and emits a Yomitan structured-content term-bank ZIP.
Byte-reproducible: two builds over identical inputs produce an identical ZIP.

## Sources (per-source extracted points)

| Source | Points | Redistributable |
|---|--:|---|
| 文法 (bunpou, personal Anki deck) | 534 | No — personal deck |
| Bunpro Grammar Reference | 964 | No — proprietary/paid |
| DoJG (日本語文法辞典 / community) | 535 | No — Japan Times, no license |
| どんなときどう使う (donna_toki) | 1,082 | No — license unclear |
| 絵でわかる (edewakaru) | 1,248 | No — license unclear |
| 日本語net (nihongo_net) | 628 | No — license unclear |
| 日本語の先生 (nihongo_no_sensei) | 1,479 | No — license unclear |
| IMABI (imabi.net) | 494 | Yes — author-approved, with attribution |
| NINJAL 日本語文型データベース (ninjal_bunkei) | 800 | Yes — CC BY 4.0 |
| Yokubi — The Common Grammar Guide | 132 | Yes — CC BY 4.0 |
| **Total** | **7,896** | merges to **4,632** unified entries |

## Licensing / redistribution

See [`LICENSING.md`](LICENSING.md) for the full audit. Only IMABI, Yokubi, and
NINJAL ninjal_bunkei are publicly redistributable (CC BY 4.0 / author-approved,
with attribution). The other sources are the user's personal deck, a proprietary
service, or published content without a redistribution license.

**Therefore this public repository ships build automation and source code only —
no extracted source content and no pre-built dictionary ZIP.** Each record's
`redistributable` flag is authoritative and fail-closed; a publish step must
filter to `redistributable: true` records (or obtain rights clearance) before
distributing any built artifact. Build the dictionary yourself from sources you
are licensed to use.

## Quick start

```sh
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -e . jsonschema==4.26.0 pytest==9.1.1
npm install                 # adm-zip + ajv, for the independent Node validator

# place your own acquired sources under data/sources/<name>/ per SOURCES.md, then:
make all                    # extract -> keymap -> merge -> build -> validate
make test                   # full test suite
make validate-node          # independent Node/ajv schema check of the built ZIP
```

The built dictionary lands at `dist/bees-ultimate-grammar-dictionary.zip`
(import into Yomitan). The pipeline stages, the frozen entry-shape contract
(`docs/contract/`), and the convergence report (`docs/plans/`) document how the
artifact is produced and verified.

## Layout

- `src/bugd/` — extractors (`sources/`), keymap, merge (`unify.py`), bank
  generation (`banks.py`), corrections overlays.
- `scripts/` — keymap build/audit, acquisition, validators, run-on/beauty checks.
- `docs/contract/` — the frozen Yomitan term-bank entry-shape contract + JSON
  Schema (2020-12) + golden entries + `validate.py` gate.
- `tests/` — unit + corpus + pipeline tests.
- `SOURCES.md` — source inventory, deck field lists, model policy.
