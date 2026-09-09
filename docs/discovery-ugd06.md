# UGD-06 discovery report — grammar-source inclusion decisions

Scope of this card after the 2026-09-09 correction: (1) integrate the staged
NINJAL 日本語文型データベース into the frozen contract, (2) resolve Tae Kim with a
recorded decision, and (3) leave the five already-integrated community sources
untouched. Decisions were recorded on the Kanban card BEFORE any import; this
file makes them durable in the repository.

Tiers: A = clean public licence · B = community derivative of a free public
site · C = community derivative of a commercial print work · X = excluded.

## Included sources (per-source JSONL at `data/sources/<name>/points.jsonl`)

| source | records | tier | redistributable | acquisition |
|---|---|---|---|---|
| `ninjal_bunkei` | 800 | A | yes (CC BY 4.0) | official NINJAL repository dataset, DOI 10.15084/0002000610, v2026.01.26, locked ZIP sha256 `21db3087…a6a9` |
| `dojg` | 535 | C | no — publish-blocked | aiko-tanaka/Grammar-Dictionaries@4314e00f5 (itazuraneko Anki lineage; The Japan Times print content) |
| `donna_toki` | 1082 | C | no — publish-blocked | public mirror byte-matching the distributed …文型辞典_1_05.zip term bank (ALC print lineage) |
| `nihongo_net` | 628 | B | no — publish-blocked | aiko-tanaka@4314e00f5/nihongo_kyoushi (site is All Rights Reserved) |
| `edewakaru` | 1248 | B | no — publish-blocked | aiko-tanaka@4314e00f5/edewakaru, text-only variant (site has 利用規約, no CC grant) |
| `nihongo_no_sensei` | 1479 | B | no — publish-blocked | aiko-tanaka@4314e00f5/nihongo_no_sensei (site has 利用規約; 意味 fields are Chinese and stay language-tagged) |

Every emitted record carries `licenseTier` and `redistributable` in its
provenance so the licensing gate (UGD-15) can act mechanically; local ULTIMATE
builds are never blocked by tier (SOURCES.md policy: licensing is a separate
gate). No source in this card ships LLM-generated fields; `ai_generated` is
empty everywhere. JLPT is only ever read from a source's own level tag —
NINJAL's `<Level>` 1–5 is its teaching-difficulty axis and is kept verbatim in
provenance as `ninjalLevels`, never coerced onto JLPT.

### NINJAL integration notes

* Extractor: `src/bugd/sources/ninjal_bunkei.py`, a plain `Extractor` over the
  locked distribution ZIP (hand-authored per-headword XML, not a community
  Yomitan bank).
* Producer conventions honoured: inline `〓漢字〔かな〕` furigana reduces to the
  base form; `｛…｝` example spans become `Example.highlight`; multi-sense
  entries flatten without collapsing to the first sense.
* Distribution defect handled: 21 of the 800 ZIP members lack the UTF-8 name
  flag, so `zipfile` decodes their Shift-JIS names as cp437 mojibake
  (`Åóé╡Åπé¬éΦé▄é╖` for 召し上がります). `member_name()` re-encodes cp437 and
  decodes CP932 — verified to round-trip all 800 members with unique stems —
  and both record identity (`source_id`, `provenance.sourceFile`) and the
  deterministic member ordering use the recovered names.

## Excluded source: Tae Kim's Guide to Japanese Grammar (tier X)

Decision: documented-but-excluded. Nothing was scraped.

* **Licence is NOT the blocker.** guidetojapanese.org/learn/grammar declares
  CC BY-NC-SA 3.0 US (re-verified live 2026-09-09) — the cleanest web-source
  licence in this card after NINJAL's.
* **No usable per-grammar-point export exists.** Verified absent from:
  aiko-tanaka/Grammar-Dictionaries (repo listing), MarvNC's collection and
  dict-stats, Kuuube's index, Yomitan's pinned `recommended-dictionaries.json`
  (387 entries scanned, zero Tae Kim hits), and GitHub repository search
  (`taekim+japanese+grammar`, `tae+kim+yomitan`, `guidetojapanese+dictionary`,
  `taekim+anki+grammar` — 0 relevant datasets).
* Adjacent repositories checked and rejected as inputs:
  * `bunpou/japanese-grammar-db` (GPL-3.0): its `build/db.json` holds 484 rows
    (62 Tae Kim) of `{link, title, source, id}` only — a link index with no
    grammar content, so nothing to extract.
  * `AmeRaino/taekim-grammar-md`, `maitodesu/tae-kim-enhanced`,
    `isaacphi/tae_kim_anki`: chapter-prose conversions or example-only decks,
    not headword-keyed grammar entries.
* **Root cause:** the guide is pedagogical chapter prose. Converting it to
  dictionary entries requires editorial prose→headword segmentation, which is
  its own card with its own review gates — not a side effect of a discovery
  card. Under the "documented-but-excluded rather than scraped recklessly"
  rule, it stays out.

## Boundaries held

* Nothing scraped: every included source is an already-published dataset or an
  official repository download.
* Deterministic: two consecutive `extract` runs of `ninjal_bunkei` produce
  byte-identical `points.jsonl` and `data/extracted/ninjal_bunkei.json`.
* Fail-closed: the extractor refuses to run when the locked archive digest is
  missing; corrupt XML members abort the build instead of being skipped.
