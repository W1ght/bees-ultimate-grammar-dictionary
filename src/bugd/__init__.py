"""Bee's Ultimate Grammar Dictionary build pipeline.

One unified Yomitan dictionary assembled from many grammar sources.

Stages (see `bugd.cli`):

    extract   per-source extractors/normalizers  ->  data/extracted/<source>.json
    merge     unify + dedupe + attribute          ->  data/merged/corpus.json
    build     structured-content banks + ZIP      ->  build/<slug>.zip
    validate  pinned Yomitan schema validation    ->  pass/fail

Each stage reads only the previous stage's on-disk artifact, so any stage can be
re-run independently and every intermediate is inspectable.
"""

DICTIONARY_TITLE = "Bee's Ultimate Grammar Dictionary"
DICTIONARY_SLUG = "bees-ultimate-grammar-dictionary"
DICTIONARY_AUTHOR = "bee-san"
# Shown in Yomitan's dictionary details pane as the source of the dictionary.
DICTIONARY_URL = "https://github.com/bee-san/bees-ultimate-grammar-dictionary"

# Yomitan revision whose official schemas are pinned under schemas/.
YOMITAN_SCHEMA_REVISION = "26.8.24.0"

# Bank/format constants fixed by Yomitan's dictionary format.
DICTIONARY_FORMAT = 3
# Bank shard size: bounded so constrained (Android) imports advance bank by bank.
TERM_BANK_SHARD = 1000

__all__ = [
    "DICTIONARY_TITLE",
    "DICTIONARY_SLUG",
    "DICTIONARY_AUTHOR",
    "DICTIONARY_URL",
    "YOMITAN_SCHEMA_REVISION",
    "DICTIONARY_FORMAT",
    "TERM_BANK_SHARD",
]
