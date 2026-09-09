# LICENSING.md — redistribution posture for Bee's Ultimate Grammar Dictionary

UGD-15 licensing / redistribution audit. For every included source this records
the **basis for inclusion as reported**, the **required attribution**, and
whether **public redistribution is permitted**.

This gate governs a future publish step ONLY. It does not block building the
local ULTIMATE dictionary, and nothing is published by this document.

Audit date: 2026-09-09. Repository revision: branch `ugd-15/licensing-audit`,
parent `b5fdba1`. Every claim below is either read out of locked source bytes
(`data/sources/<source>/SOURCE.lock.json`) or fetched live and quoted; the
distinction is stated per row.

## Integrity of the evidence base

All 611 files pinned across the ten `SOURCE.lock.json` manifests re-hash
byte-exact to their recorded digests (0 mismatched, 0 missing):

| source | pinned files | mismatched/missing |
|---|---|---|
| bunpou | 1 | 0 |
| bunpro | 1 | 0 |
| dojg | 2 | 0 |
| donna_toki | 3 | 0 |
| edewakaru | 6 | 0 |
| imabi | 502 | 0 |
| nihongo_net | 8 | 0 |
| nihongo_no_sensei | 7 | 0 |
| ninjal_bunkei | 3 | 0 |
| yokubi | 78 | 0 |
| **total** | **611** | **0** |

## Two different populations — do not conflate them

**Acquired and locked (10 sources)** is not the same set as **shipped in the
current build (5 sources)**.

The current artifact `dist/bees-ultimate-grammar-dictionary.zip`
(sha256 `33546769dd33…`, 1,706,586 B, 2,419 entries, 3 term banks) declares
exactly five sources in `tag_bank_1.json`:

`dojg`, `donna_toki`, `edewakaru`, `nihongo_net`, `nihongo_no_sensei`

A substring scan of all three term banks finds **zero** occurrences of
`Yokubi` / `yoku.bi`, `IMABI` / `imabi`, `Bunpro` / `bunpro`,
`日本語文型データベース` / `NINJAL` / `ninjal`, or `bunpou`. Those five sources are
acquired and locked but do not reach the packaged bytes today; only
`dojg`, `donna_toki`, `edewakaru`, `nihongo_net`, `nihongo_no_sensei` are
registered extractors (`bugd.sources.registry.source_names()`), and
`data/extracted/` additionally holds `ninjal_bunkei.json` (800 points) which the
current bank generator does not package.

## Summary table

Tier and `redistributable` values are quoted from each source's locked
`provenance`, not restated from memory. A blank tier means the lock records no
licence block at all.

| Source | Basis for inclusion (as reported) | Attribution required | Public redistribution | Tier / flag | In current ZIP |
|---|---|---|---|---|---|
| 文法.apkg (`bunpou`) | The user's own private 文法 Anki export (534 notes), symlinked from `~/documents` and pinned by digest. Lock states: "the user's own private deck; not third-party redistributable content". Rights in the underlying content are not established. | Personal deck — no public attribution string | **No** | `D` / `redistributable:false` | No |
| Bunpro (`bunpro`) | Local Anki export from the user's Documents; user confirmed local use is OK. Bunpro is a paid proprietary service. Live ToS (fetched 2026-09-09) states "The materials contained in this website are protected by applicable copyright and trademark law" and contains **no** licence or redistribution grant. | "Bunpro Grammar Reference" | **No** — proprietary, no grant | *(no licence block in lock)* | No |
| IMABI (`imabi`) | 502 pages acquired via `imabi.org/wp-json/wp/v2/pages`. **User reports the IMABI authors approved full-content use.** No published licence exists to corroborate this: `/terms/`, `/license/`, `/copyright/` all return 404 and the site footer says only "Copyright 2009-2026". | "IMABI (imabi.net)" | **Only on the strength of the reported author approval.** Not independently verifiable from any public document. | *(no licence block in lock)* | No |
| Yokubi (`yokubi`) | CC BY 4.0, **declared by the source and verified in locked bytes**: `data/sources/yokubi/LICENSE` is the CC BY 4.0 text ("Attribution 4.0 International") and `src/Credits.md` says "The project is licensed under the Creative Commons By-Attribution 4.0 license" and grants Use / Redistribute / Modify "even commercially, as long as you attribute the original work". Pinned at rev `b1c0938b…`, tarball sha256 `1ac85af8…`. | "Yokubi — The Common Grammar Guide (https://yoku.bi), CC BY 4.0" + licence link | **Yes** — with attribution | `A` / `redistributable:true` | No |
| DoJG (`dojg`) | 535 points extracted from `github.com/aiko-tanaka/Grammar-Dictionaries` @ `4314e00f…`. Content is verbatim from The Japan Times' published 日本語文法辞典 volumes (basic 86 / intermediate 191 / advanced 258). GitHub API reports the repo's `license` as **null** and `/master/LICENSE` returns 404. Lock: "unlicensed community derivative of a commercial print work". | "DoJG 日本語文法辞典(全集)" | **No** — third-party commercial print work, no licence | `C` / `redistributable:false` | **Yes** |
| どんなときどう使う (`donna_toki`) | 1,082 entries from a public mirror (`donnatoki_1_05.zip`), absent from aiko-tanaka HEAD. Also a derivative of a commercial print dictionary; same unlicensed upstream. | "どんなときどう使う 日本語表現文型辞典" | **No** | `C` / `redistributable:false` | **Yes** |
| 絵でわかる日本語 (`edewakaru`) | 1,248 entries via the same unlicensed aiko-tanaka repo. Producer `edewakaru.com` publishes a 利用規約, which resolves to the **livedoor platform terms** (`livedoor 利用規約`), not a content-reuse grant. | "絵でわかる日本語" | **No** | `B` / `redistributable:false` | **Yes** |
| 日本語NET (`nihongo_net`) | 628 entries via the same unlicensed repo. Producer `nihongokyoshi-net.com` footer reads "日本語NET All Rights Reserved." — rights asserted, no grant. | "日本語NET JLPT文法解説まとめ" | **No** | `B` / `redistributable:false` | **Yes** |
| 毎日のんびり日本語教師 (`nihongo_no_sensei`) | 1,479 entries via the same unlicensed repo; meaning sections are Chinese (`meaningZh`). Producer page `nihongonosensei.net/?page_id=10246` no longer serves the 利用規約 — the domain now returns unrelated online-casino content, so the producer's terms are **unobtainable**. | "毎日のんびり日本語教師" | **No** | `B` / `redistributable:false` | **Yes** |
| NINJAL 日本語文型データベース (`ninjal_bunkei`) | CC BY 4.0, **verified in locked bytes**: `readme.txt` declares `ライセンス: CC BY 4.0`, DOI `10.15084/0002000610`, editors パルデシ・プラシャント / 砂川有里子, publisher 国立国語研究所 研究系, version 2026.01.26. | "日本語文型データベース", 国立国語研究所 研究系, CC BY 4.0 + licence link | **Yes** — with attribution | `A` / `redistributable:true` | No (extracted, not packaged) |

## Redistribution decision

**Publishable with attribution (verified licence in locked bytes):**
- Yokubi — CC BY 4.0
- NINJAL 日本語文型データベース — CC BY 4.0

**Publishable only on reported permission, not independently verifiable:**
- IMABI — the authors' approval is a user report; no public licence exists. A
  publish step should obtain that approval in writing before relying on it.

**NOT publishable without rights clearance:**
- 文法/`bunpou` (private deck, upstream rights unknown)
- Bunpro (proprietary paid service, ToS asserts copyright, no grant)
- DoJG and どんなときどう使う (verbatim commercial print works, upstream repo unlicensed)
- 絵でわかる日本語, 日本語NET, 毎日のんびり日本語教師 (producers assert rights or publish only
  platform terms; one producer's terms are now unobtainable)

### Blocking finding for any future publish step

**Every source in the current build is `redistributable:false`.** All five
sources packaged in `dist/bees-ultimate-grammar-dictionary.zip` are tier B/C
with `redistributable:false`; both tier-A sources (Yokubi, NINJAL) are absent
from the ZIP. Publishing the current artifact as-is would redistribute *only*
non-redistributable content.

**There is no publish-time filter.** `redistributable` is recorded in
provenance and carried through extraction, but no code in the build path
(`src/bugd/banks.py`, `src/bugd/unify.py`, `src/bugd/pipeline.py`) reads it —
the flag appears only in the acquisition scripts that write it. It is therefore
**advisory metadata, not a machine-enforced gate**. A publish step must add an
explicit fail-closed filter on `provenance.redistributable` (and assert the
resulting corpus is non-empty) before shipping anything publicly.

## Attribution requirements for any permitted publication

Every published record must carry its source's attribution string from the
table above. The two CC BY 4.0 sources additionally require a link to
https://creativecommons.org/licenses/by/4.0/ and an indication of changes made
(both are transformed: prose is re-segmented into Yomitan structured content).

## Scope and standing

This audit reports inclusion bases **as reported** to the build — user
statements plus licence documents acquired and digest-locked in each source's
`SOURCE.lock.json` — together with live verification performed on 2026-09-09.
It is not legal advice. Publishing any tier B/C/D source requires explicit
rights clearance from the respective owner.
