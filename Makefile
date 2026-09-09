# Bee's Ultimate Grammar Dictionary — build pipeline
#
# Stages, each reading only the previous stage's on-disk artifact:
#   extract  -> data/extracted/<source>.json
#   keymap   -> data/merge/keymap.json + AMBIGUITY.md
#   merge    -> data/merge/unified.jsonl (+ unified.stats.json)
#               and data/merged/corpus.json (bank-generator input)
#   build    -> build/bees-ultimate-grammar-dictionary.zip
#   validate -> pinned official Yomitan schema validation (python + node)

PY ?= python3

# Resolve node through the shell rather than letting make exec a bare `node`.
# make short-circuits single-word recipes to a direct exec and uses its own PATH
# walk, which on this host hits an empty `/usr/bin/node` DIRECTORY that shadows
# the real interpreter and fails with "Permission denied".
NODE ?= $(shell command -v node 2>/dev/null || echo node)

PYTHONPATH := src
export PYTHONPATH

# Reproducible builds: fixed hash seed, UTC, C locale.
export PYTHONHASHSEED := 0
export TZ := UTC
export LC_ALL := C.UTF-8
export SOURCE_DATE_EPOCH := 0

ZIP := build/bees-ultimate-grammar-dictionary.zip

.PHONY: all extract keymap merge build validate validate-node audit-packaged test clean help

help:
	@printf 'targets: extract keymap merge build validate validate-node audit-packaged test all clean\n'

extract:
	$(PY) -m bugd.cli extract

# Cross-source canonical keymap (data/merge/keymap.json). Consumed by `merge`.
keymap:
	$(PY) scripts/build_keymap.py
	$(PY) scripts/audit_keymap.py
	$(PY) scripts/render_ambiguity_report.py

# Unified dataset (data/merge/unified.jsonl + unified.stats.json) and its
# projection onto the bank generator's input (data/merged/corpus.json). The audit
# runs as part of the target: it re-derives conservation, findability and
# ordering from the emitted artifact, so a merge that lost rows cannot pass.
merge:
	$(PY) -m bugd.cli merge
	$(PY) scripts/audit_unified.py

build:
	$(PY) -m bugd.cli build

validate:
	$(PY) -m bugd.cli validate

# Packaged-bytes audits. `validate` proves the archive matches Yomitan's pinned
# schemas; these prove it carries the WORK -- per-source attribution, working
# redirects, and each source's own JLPT level on the 158 entries whose sources
# disagree. A gate that is never run is not a gate, so both are targets.
audit-packaged:
	$(PY) scripts/audit_packaged_merge.py
	$(PY) scripts/audit_packaged_jlpt.py

# Independent Node/ajv cross-check of the same artifact against the same pinned
# schemas. Requires `npm install`.
validate-node:
	$(NODE) scripts/validate_yomitan.mjs $(ZIP)

test:
	$(PY) -m pytest -q

all: extract keymap merge build validate

clean:
	rm -rf build dist data/extracted data/merged
