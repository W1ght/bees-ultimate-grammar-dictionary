# `data/` layout

Everything under `data/` except this file and the `.gitkeep` markers is
gitignored: it is acquired or generated, and often large. The layout is the
contract between pipeline stages.

```
data/
  sources/<source-name>/          raw acquired bytes  (gitignored)
    SOURCE.lock.json              digest lock of every consumed file
    <original files...>
  extracted/<source-name>.json    normalized GrammarPoint records  (gitignored)
  merge/keymap.json               cross-source canonical keymap + report  (gitignored)
  merged/corpus.json              the one unified MergedEntry corpus  (gitignored)
```

## `data/sources/<source-name>/`

One directory per registered source; the name matches `Extractor.name`. It holds
the untouched bytes the extractor consumed — an `.apkg`, a scraped HTML tree, a
downloaded dictionary ZIP — plus a `SOURCE.lock.json`:

```json
{
  "source": "bunpro",
  "acquiredAt": "2026-09-08T00:00:00Z",
  "files": {
    "Bunpro Grammar Reference.apkg": {
      "sha256": "<64 hex chars>",
      "byteCount": 256729320
    }
  }
}
```

Rules enforced by `bugd.sources.base`:

* an extractor may read only files listed in its own lock, via
  `Extractor.read_locked_bytes`;
* a digest or byte-count mismatch fails the build closed — a partially
  re-downloaded or truncated source never silently produces a degraded
  dictionary;
* locked paths must be relative, forward-slashed, and free of `.`/`..`
  components.

Large binary inputs are not copied into the repository. For inputs that already
live elsewhere on disk (e.g. the local Anki decks named in `SOURCES.md`), place a
symlink or a small acquisition script in the source directory and lock the
resolved bytes.

## `data/extracted/<source-name>.json`

One artifact per source, written by `make extract`:

```json
{
  "source": "...",
  "label": "human-facing attribution label",
  "aiGeneratedSource": false,
  "consumed": {"<relative path>": "<sha256>"},
  "stats": {},
  "points": [ /* serialized GrammarPoint records */ ]
}
```

Extractors preserve the whole tail. Compact-card truncation is a rendering
decision made in `bugd.banks`, never here.

### Row identity: `row_uid` vs `source_id`

Each serialized record carries **two** identifiers, and they mean different
things:

| field | meaning | unique? |
| --- | --- | --- |
| `source_id` | the producer's own handle, usually its headword or bank sequence | **no** |
| `row_uid` | `<source>:<ordinal>` — this build's identity for the row | **yes**, within a source |

`source_id` is not unique and never was: one `edewakaru` `source_id` names 22
different rows, and across the five sources 435 handles are reused. That is not a
source defect — a dictionary legitimately publishes several senses of `あまり` —
but it means `(source, source_id)` cannot address a claim. Measured on the merged
dataset before `row_uid` existed: **289** handles named 2+ genuinely different
source records, **742** contributions carried an ambiguous handle, and on **54**
entries one handle asserted two different JLPT levels.

`row_uid` is assigned once, in `ExtractResult.__post_init__`, from the row's
1-based position in its source's deterministic emission order. Consequences worth
knowing:

* **it fails closed on a repeat.** A duplicate raises `DuplicateRowIdentity`
  rather than renumbering, because renumbering would silently repoint every claim
  that already cites the id;
* **the grammar is explicit ASCII.** `<source>:<positive-decimal>` with no sign,
  underscore, or non-ASCII digit — `int()` accepts `1_0`, `+1` and `１`, any of
  which would let two spellings of one ordinal coexist;
* **the merge stage re-checks it** and refuses to build a contribution from an
  unstamped row, so a stale `data/extracted/` cannot reintroduce ambiguous
  claims;
* **it is dataset identity, not card content.** Nothing renders it; adding it
  left the packaged bank bytes unchanged.

Audit it with `scripts/audit/row_identity.py` (uniqueness plus a check that each
uid names the row whose substance the contribution actually restates) and
`scripts/audit/attribution_precision.py --handle sourceId|rowUid`, which measures
the same collision count under either handle.

## `data/merge/keymap.json`

Written by `scripts/build_keymap.py` (module: `bugd.keymap`): the authority for
*which source rows are the same grammar point*. The merge stage reads it through
`bugd.keymap_io` and falls back to derived keys only when it is absent.

```json
{
  "schemaVersion": 1,
  "assignments": [
    {"source": "dojg", "sourceId": "ながら", "substanceHash": "<sha256>",
     "canonicalKey": "ながら"}
  ],
  "points": [
    {"canonicalKey": "ながら", "expression": "ながら",
     "lookupForms": ["ながら"], "axes": {"variety": "standard", "era": "modern"},
     "contributors": [/* row identities */], "sourceCount": 2,
     "observedRegisters": [], "observedSignatures": [], "jlptLevels": ["N4"]}
  ],
  "report": { /* every ambiguous case and the guard that decided it */ }
}
```

A row's identity is `(source, sourceId, substanceHash)`. The hash is required
because `sourceId` is **not** unique: edewakaru ships `も` eleven times and
donna_toki `お` six times as genuinely different senses, so addressing rows by
`(source, sourceId)` alone would make them collide.

Canonical keys are `<key>`, `<key>#<disambiguator>` when a bucket holds several
distinct senses, and are prefixed `<variety>/<era>:` outside the default
`standard/modern` scope so a classical form can never collide with its modern
homograph.

The matcher folds on positive attested evidence or refuses — a missed fold is
untidy, a wrong fold destroys a distinction the source authors made. `report`
enumerates refusals in full rather than counting them, so a reviewer can check
that e.g. `ないことはある` and `ないことはない` stayed apart and see which guard did
it. Regenerate with:

```
PYTHONPATH=src python3 scripts/build_keymap.py
```

## `data/merged/corpus.json`

Written by `make merge`: the unified corpus plus the per-source attribution
labels the tag bank is generated from. Every merged entry keeps its full list of
contributing source records, so attribution survives to the rendered card.
