# LICENSING.md — Redistribution posture for Bee's Ultimate Grammar Dictionary

This is the UGD-15 licensing / redistribution audit. It records, per included
source, the **basis for inclusion as reported**, the **required attribution**,
and whether **public redistribution** is permitted. This gate governs any future
publish step ONLY; it does not affect building the local dictionary. Nothing is
published by this document.

Per-source records carry a `licenseTier` and `redistributable` flag in their
`provenance` (see `src/bugd/sources/*.py`); this file is the human-readable
summary of those machine-enforced values.

## Summary table

| Source | Basis for inclusion (as reported) | Attribution | Public redistribution | Tier |
|---|---|---|---|---|
| 文法.apkg (bunpou) | User-owned personal Anki deck; provenance of underlying content unknown | Personal deck (no public attribution string) | **No** — unknown upstream rights | C / redistributable:false |
| Bunpro | User confirmed OK to use locally (prior session); Bunpro is a paid proprietary subscription service | "Bunpro Grammar Reference" | **No** — proprietary paid content | C / redistributable:false |
| IMABI | IMABI authors approved full-content use (per user) | "IMABI (imabi.net)" | **Yes** — author-approved, with attribution | A / redistributable:true |
| Yokubi | CC BY 4.0 (declared in repo LICENSE + src/Credits.md; acquired & locked) | "Yokubi — The Common Grammar Guide (https://yoku.bi), CC BY 4.0" | **Yes** — with attribution | A / redistributable:true |
| DoJG (日本語文法辞典) | Verbatim content from The Japan Times' published grammar dictionaries; upstream repo carries no license | Japan Times DoJG (source acknowledgement) | **No** — third-party published, no license | C / redistributable:false |
| NINJAL 日本語文型データベース (ninjal_bunkei) | CC BY 4.0 (acquired & locked) | NINJAL 日本語文型データベース, CC BY 4.0 | **Yes** — with attribution | A / redistributable:true |
| donna_toki, edewakaru, nihongo_net, nihongo_no_sensei (community) | Community-authored Yomitan/deck content; license varies / not clearly granted | Per-source community attribution | **No** unless the specific source's terms are cleared | C / redistributable:false (conservative) |

## Redistribution decision

- **Publishable now (with attribution):** IMABI (A, author-approved), Yokubi
  (A, CC BY 4.0), NINJAL ninjal_bunkei (A, CC BY 4.0).
- **NOT publishable without further clearance:** 文法/bunpou (personal, unknown
  upstream), Bunpro (proprietary paid), DoJG (Japan Times, no license), and the
  community sources (license unclear) — all tier C, `redistributable:false`.
- The build's per-record `redistributable` flag is authoritative and fail-closed:
  a publish step MUST filter to `redistributable:true` records (or obtain
  explicit clearance) before shipping any source's content publicly. This gate
  does not itself publish anything.

## Attribution requirements (for any permitted publication)

Every published record must carry its source's attribution string (above). The
CC BY 4.0 sources (Yokubi, NINJAL) additionally require a link to the license
(https://creativecommons.org/licenses/by/4.0/) and indication of any changes.

## Note

This audit reflects inclusion bases **as reported** to the build (user
statements + acquired LICENSE/Credits files locked in each source's
`SOURCE.lock.json`). It is not legal advice; a publish decision for the tier-C
sources requires explicit rights clearance from the respective owners.
