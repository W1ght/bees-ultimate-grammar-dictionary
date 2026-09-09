# Unified Card Contract — Bee's Ultimate Grammar Dictionary

This is the ONE canonical Yomitan entry shape that every extractor (UGD-02..06),
the merge (UGD-08), and bank generation (UGD-09) MUST target. It is frozen here
and is authoritative. All figures below are derived from the built corpus and
cross-checked (`evidence/contract_invariants.txt`, `evidence/node_shapes.txt`,
`evidence/shape_census.txt`); see `docs/contract/shape.schema.json` for the
machine-checkable JSON shape and `docs/contract/golden/` for seven golden
entries that conform to this contract.

## Corpus census (frozen reference values)

- Total term-bank rows: **2419**, `sequence` min 1 / max 2419 / distinct 2419 / contiguous.
- `root lang="ja"`: 2419 (every card root carries `lang=ja`).
- Root child kinds after the compact block: `listedOnly` 109,
  `sourceBlock` 3661, `crossref` 242. (Per-source `sourceBlock`s are the only
  `details` children; there is no separate trailing attribution `details`.)
- `reading` non-empty on 866 rows; `reading == expression` never occurs (0).
- `score` is always 0; no `tags` and no `termTags` are ever populated.
- JLPT distribution: N1 519, N2 430, N3 451, N4 136, N5 58.

## Term-bank row shape (Yomitan term bank v3)

Each entry is the 8-element array:

```
[ expression, reading, definitionTags, deinflectionRules, score, [structuredContent], sequence, termTags ]
```

- `expression` (string): the grammar-point headword form. Indexed for lookup.
- `reading` (string): kana reading; MAY be empty (`""`) when identical to or not
  distinct from the expression. MUST NOT equal `expression`.
- `definitionTags` (string): always `""`.
- `deinflectionRules` (string): always `""`.
- `score` (number): always `0`.
- `structuredContent`: a single object `{ "type": "structured-content", "content": <grammarCard> }`.
- `sequence` (number): 1-based, unique, contiguous across the corpus. Groups
  aliases/variant headwords of the same grammar point onto one card.
- `termTags` (string): always `""`.

Headword indexing: the primary headword plus its aliases/variant forms are each
emitted as their own row sharing the same `sequence`, so a lookup on any alias
resolves to the same card.

## Structured-content role hierarchy

The `content` is an HTML-ish node tree. Every element is
`{ tag, content, data?: {<role>: ""}, lang?, href? }`. The role is carried as the
single key of `data` (e.g. `data: {"compact": ""}`), NOT as a class. Canonical
tree:

```
div role=grammarCard  lang=ja          (root, 2419)
├─ div role=compact                    (2419; may be empty — see fallback rule)
│  ├─ span role=meaning  lang=en|ja    (1990; en 870 / ja 1120)  — short gloss
│  └─ div  role=metarow                (1854)
│     ├─ span role=jlpt                (1594)   e.g. "N3"
│     └─ span role=structure lang=ja   (1543)   formation/structure
├─ details role=sourceBlock            (3661; one per contributing source)
│  ├─ summary → span role=sourceName   (3661)   per-source attribution badge
│  └─ (sense | senseLabel sense)+      (senseLabel 887 when >1 sense)
│     └─ div role=sense
│        ├─ div role=prose lang=ja     (explanation; may contain ruby)
│        ├─ ul  role=patterns          (1201) → li role=pattern (6479)
│        └─ ul  role=examples          (4102) → li role=example → span role=ja[/en]
├─ div role=crossref                   (242)  → text + a  (redirect to related point)
└─ div role=listedOnly lang=en         (109)  → text,a,text (external-link-only entries)
```

Node key sets are fixed per (tag, role) — see `evidence/node_shapes.txt`. Ruby is
represented as `ruby → (rt, text)` inside prose; do not flatten furigana into
plain text.

## Hard invariants (fail-closed; bank gen MUST reject violations)

1. Exactly one root `div role=grammarCard`, `lang=ja`, per row (2419).
2. Compact ordering: `meaning` MUST precede `metarow` (0 violations allowed).
3. The LAST root child is a `sourceBlock`, `crossref`, or `listedOnly` — never a
   data-less attribution `details`; there is no trailing "Sources" block. All
   `details` are shipped closed (never `open`).
4. A row MUST NOT have BOTH a `sourceBlock` and a compact fallback.
5. A row MUST NOT have both `crossref` and `listedOnly`.
6. No card may be empty or render as attribution-only: every card MUST carry at
   least one substantive child (a `sourceBlock`, `crossref`, or `listedOnly`);
   0 empty/attribution-only cards allowed.
7. `metarow` contains only `jlpt` and/or `structure` roles.
8. `sourceBlock` has exactly 2 children (summary + body).
9. External anchors are allowed only in `grammarCard > listedOnly` context
   (origins: edewakaru.com, nihongokyoshi-net.com).

### Empty-compact fallback rule

333 rows have an empty compact block; 320 of those carry a fallback
(`crossref` or `listedOnly`) so the card is never blank. The remaining **13**
known exceptions have an empty compact but DO render a `sourceBlock`
(so they are non-blank): かしら, しい, だい, ちょっと, つまらないものですが,
なんで, よね？, 所, 汚す, 汚れる, 決して, 濡らす, 濡れる. These 13 are accepted
and MUST remain non-blank via their sourceBlock. New/changed sources MUST NOT
introduce a blank or attribution-only card.

## Per-source attribution & AI-field handling

- Each contributing source renders its own `details role=sourceBlock` with a
  `span role=sourceName` badge (e.g. `DoJG 日本語文法辞典(全集)`), so provenance is
  visible per sense. The per-source `sourceName` badge IS the attribution — no
  separate trailing attribution block is emitted.
- AI-generated fields (from 文法.apkg) MUST be segregated into their own
  sourceBlock and clearly labelled as AI-generated in the `sourceName` badge;
  they are never merged into a human source's sense. AI disclosure lives in the
  entry, per the project's AI-disclosure rule.

## Redirects (refused / non-canonical forms)

161 refused headword forms are rendered as redirect entries (`crossref`):
139 declared-target, 13 core-identity, 9 unresolved. A redirect entry has an
empty compact and a `crossref` pointing at the canonical headword; it shares
lookup indexing so users landing on a variant reach the canonical card.

## Golden entries

`docs/contract/golden/` contains seven conforming examples covering the shape
space: `multi-source.json`, `single-source-minimal.json`, `crossref-redirect.json`,
`listed-only.json`, `ruby-in-prose.json`, `prose-annotations.json`,
`long-highlight.json`. Any extractor/merge output MUST validate against
`shape.schema.json` and match the structural conventions these goldens show.
