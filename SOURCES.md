# Bee's Ultimate Grammar Dictionary — Source Inventory

Goal: ONE unified Yomitan dictionary ("Bee's Ultimate Grammar Dictionary") combining
every grammar source into a single installable ZIP with unified lookup + per-source
attribution. Not separate dictionaries. Progressive disclosure: compact card + closed
`details` sections for the tail (readings, extra examples, provenance).

Model policy (Bedrock-only, per user): every Kanban worker pinned to
`global.anthropic.claude-opus-5` (provider bedrock), reasoning max.
(Latest Bedrock Opus, launched 2026-07-24; global inference ID confirmed on AWS model card.)

## Local Anki decks (authoritative primary inputs — already on disk)

### 1. 文法.apkg  (`/home/skerraut/documents/文法.apkg`, 7.5 MB)
- Notetype: `文法 Cloze`
- 534 notes / 534 cards
- Fields: 文型, 意味, 接続, JLPTレベル, 備考,
  例文1..例文15 (Japanese example sentences, HTML with <strong> highlights),
  AI丁寧度 (AI politeness/register tag), AI例文1, AI英訳1, AI例文2, AI英訳2 (AI-generated examples w/ English)
- Rich human-written 意味/接続/備考 + up to 15 real example sentences per point.
- NOTE: fields prefixed `AI…` are AI-generated — flag/segregate per user policy
  (no LLM-generated content presented as authoritative dictionary fact; keep behind a labelled disclosure or drop).

### 2. Bunpro Grammar Reference.apkg  (`/home/skerraut/Documents/Bunpro Grammar Reference.apkg`, 257 MB)
- Notetype: `Bunpro Grammar Model Final V3`
- 964 notes / 964 cards  (large — media-heavy, 14,885 zip members)
- Fields: Grammar_Order, ID, Title, Meaning, JLPT, Structure, Nuance, Nuance_JP,
  Explanation, Explanation_JP, Rest_Examples_HTML, Front/Back (multiple cloze pairs),
  Add Reverse, Text, Back Extra, Occlusion, Image, Header
- Substantive EN + JP explanations, nuance, structure, many example sentences (Rest_Examples_HTML), images.
- User confirmed Bunpro is OK to use (prior session).

### Anki .apkg extraction notes
- `collection.anki21b` inside the .apkg is a **zstd-compressed** SQLite DB (new Anki export format).
  Decompress with python `zstandard` then open as sqlite3.
- New-Anki schema: notetypes in `notetypes` table, fields in `fields` table (ord/ntid),
  note field values in `notes.flds` split on `\x1f` (US, 0x1f).
- Media files are numbered members (`0`,`1`,...) mapped by the `media` JSON manifest member.

## Web / community sources to scrape or find existing dictionaries for
Prefer finding an EXISTING Yomitan dict / Anki deck before re-scraping from scratch.
- Yokubi (yoku.bi) — repo: github.com/Morgawr/yokubi. Grammar lessons.
- IMABI (imabi.org) — large; modern + classical lessons.
- DoJG — Dictionary of Japanese Grammar (A/I/A Dictionary of Basic/Intermediate/Advanced JP Grammar). Existing Yomitan dicts exist (search MarvNC / yomitan-dictionaries community).
- NINJAL grammar patterns, Donna Toki Dou Tsukau (どんなときどう使う), Tae Kim, 日本語NET, 絵でわかる日本語, Nihongo no Sensei — check for existing Yomitan/Anki exports first.

## Attribution
- Preserve per-source label on every merged entry: a statement is never detached
  from the source that made it.

## Reference data (validation gates, not dictionary content)

### KANJIDIC2 — per-kanji reading gate
- Source: KANJIDIC2, Electronic Dictionary Research and Development Group (EDRDG),
  licence CC BY-SA 4.0. https://www.edrdg.org/wiki/index.php/KANJIDIC_Project
- Used only by the reading gate (`src/bugd/readings.py`) to check that a
  contribution's `reading` is a structurally possible kana rendering of its own
  written form. It is NOT dictionary content and ships as a distilled asset, not
  the full XML.
- Distilled asset: `src/bugd/data/kanji_readings.json` (on/kun/nanori readings
  only, hiragana; 13,108 kanji). Its `_provenance` block pins the upstream XML.gz
  `sha256` and `databaseVersion`; the asset is byte-reproducible from that pinned
  source via `python scripts/distil_kanjidic.py <kanjidic2.xml.gz> src/bugd/data/kanji_readings.json`
  (stdlib-only, no third-party dependency).
- Pinned upstream: kanjidic2.xml.gz, sha256
  `dccb9cf78b3a56d139350939cec2afe4efd866eff213f9be8cd0dd5cbdcfead6`,
  database version `2026-251`.

### Reading corrections (UGD-11c-B)
- `data/corrections/readings.json` is an evidence-backed overlay correcting nine
  upstream publisher readings that are impossible/wrong for their written form.
  Applied deterministically at merge (contribution level, keymap-preserving),
  fail-closed if any correction matches no row. Each entry cites its evidence;
  none is invented. See the file's `_meta` block.
