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

## Community Yomitan dictionaries (acquired or scraped)

### DoJG — 日本語文法辞典(全集)
- Source: aiko-tanaka/Grammar-Dictionaries, `dojg/`
- Dictionary of Japanese Grammar (Basic/Intermediate/Advanced), English
- Existing Yomitan banks

### HJGP — 日本語文型辞典 (monolingual)
- Source: HuangAntimony/Nihongo-Bunkei-Jiten, pinned commit `35308928ed5cffb3a8b2f2709a54b59b896748cf`
- A Handbook of Japanese Grammar Patterns — monolingual Japanese
- 1,245 Yomitan structured-content entries with rich furigana, data-role-annotated semantic blocks
- Direct Extractor (not CommunityBankExtractor) — walks the structured content JSON tree
- Extraction: 1,245 points, 1,076 with meaning, 535 with examples, 533 with structure

### HJGP EN — 日本語文型辞典 英語版
- Source: 日本語文型辞典 bilingual Yomitan banks (A Handbook of Japanese Grammar Patterns for Teachers and Learners)
- English edition with bilingual examples (Japanese + English translations)
- CommunityBankExtractor with line-based text parsing
- Extraction: 1,049 points, 932 with examples (all with English translations)

### NINJAL — 日本語文型データベース
- Source: NINJAL (National Institute for Japanese Language and Linguistics), DOI 10.15084/0002000610
- Grammar pattern database, Japanese

### 日本語NET — JLPT文法解説まとめ
- Source: scraped from nihongokyoshi-net.com (replaces aiko-tanaka/Grammar-Dictionaries `nihongo_kyoushi/` May 2022 data)
- JLPT grammar explanations with meaning, structure, examples, English translations
- Split one bank per JLPT level (N1–N5)

### 絵でわかる日本語
- Source: aiko-tanaka/Grammar-Dictionaries, `edewakaru/`
- Grammar explained through illustrations, Japanese

### Donna Toki — どんなときどう使う 日本語表現文型辞典
- Source: donna_v1.04 Yomitan banks
- "When and How to Use" expression pattern dictionary, English/Japanese

### 毎日のんびり日本語教師 (Nihongo no Sensei)
- Source: aiko-tanaka/Grammar-Dictionaries, `nihongo_no_sensei/`
- Grammar explanations for Japanese teachers, Japanese/Chinese

### Yokubi
- Source: Morgawr/yokubi mdBook markdown
- The Common Grammar Guide (yoku.bi), English

### IMABI
- Source: imabi.org lesson pages
- Comprehensive Japanese grammar lessons (modern + classical), English

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
