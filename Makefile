# Bee's Ultimate Grammar Dictionary — build pipeline
#
# Stages, each reading only the previous stage's on-disk artifact:
#   extract  -> data/extracted/<source>.json
#   keymap   -> data/merge/keymap.json + AMBIGUITY.md
#   merge    -> data/merge/unified.jsonl (+ unified.stats.json)
#               and data/merged/corpus.json (bank-generator input)
#   build    -> build/bees-ultimate-grammar-dictionary.zip
#   validate -> pinned official Yomitan schema validation (python + node)

# Prefer the project venv over whatever `python3` happens to resolve to. A bare
# `python3` can be an unrelated interpreter on PATH (here: the agent runner's own
# venv), which lacks `zstandard` and fails `extract` on the Anki-backed sources
# while the pure-Python schema fallback silently makes `build` ~7x slower.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

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

# The PUBLIC artifact is a different dictionary from the local one, so it gets
# its own directories throughout: a filtered extracted corpus, its own keymap and
# unified dataset, its own merged corpus, and its own build/dist tree. Nothing
# public is ever written into the local build's paths, so `make all` and
# `make public` can both be present on disk without one masquerading as the other.
PUBLIC_EXTRACTED := data/extracted-public
PUBLIC_MERGE_DIR := data/merge-public
PUBLIC_MERGED     := data/merged-public
PUBLIC_BUILD      := build-public
PUBLIC_DIST       := dist-public
PUBLIC_ZIP := $(PUBLIC_BUILD)/bees-ultimate-grammar-dictionary.zip

.PHONY: all extract keymap merge build validate validate-node audit-packaged test scan-polarity clean help \
        publish-filter public public-validate-node audit-public

help:
	@printf 'targets: extract keymap merge build validate validate-node audit-packaged test scan-polarity all public clean\n'

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
	$(PY) scripts/audit_readings.py
	$(PY) scripts/resolve_reading_disagreements.py

build:
	$(PY) -m bugd.cli build

validate:
	$(PY) -m bugd.cli validate

# Packaged-bytes audits. `validate` proves the archive matches Yomitan's pinned
# schemas; these prove it carries the WORK -- per-source attribution, working
# redirects, and each source's own JLPT level on the 158 entries whose sources
# disagree. A gate that is never run is not a gate, so both are targets.
# Deterministic attribution regressions (UGD-11d). Both read the merged artifact,
# take ~2s, and need no LLM or network, so any future merge change has to pass them:
#   coherence  - every claim a contribution makes fits inside ONE source row, so no
#                card can present a blend of two records as one source's statement.
#   precision  - the claim handle names a unique row. Run with --handle rowUid: the
#                acceptance gate is collidingClaimIds == 0. `--handle sourceId` is
#                the control and still reports the filed 289, since source_id is
#                deliberately still the producer's non-unique headword.
# UGD-11d's LLM passes (build_dossiers/llm_audit/adjudicate/synthesize/...) are
# audit tooling, not build steps, and are deliberately NOT wired in here.
audit-attribution:
	$(PY) scripts/audit/attribution_coherence.py
	$(PY) scripts/audit/attribution_precision.py data/merge/unified.jsonl data/merge/attribution_precision.json --handle rowUid

audit-packaged:
	$(PY) scripts/audit_packaged_merge.py
	$(PY) scripts/audit_packaged_jlpt.py

# Independent Node/ajv cross-check of the same artifact against the same pinned
# schemas. Requires `npm install`.
validate-node:
	$(NODE) scripts/validate_yomitan.mjs $(ZIP)

test:
	$(PY) -m pytest -q

# Corpus scan for the UGD-11c-A polarity-flipped-headword property: after
# extraction, no 〜ある headword may contradict its own (negative) reading.
# Reads data/extracted, so run `make extract` first.
scan-polarity:
	$(PY) scripts/scan_polarity_flips.py

all: extract keymap merge build validate

# ---------------------------------------------------------------------------
# PUBLIC artifact
# ---------------------------------------------------------------------------
#
# The public release is a DIFFERENT dictionary from the local one. UGD-15's
# licensing audit found eight of the ten acquired sources are not publicly
# redistributable, and named the missing gate: `provenance.redistributable` was
# advisory metadata that no build-path module read. `publish-filter` is that
# gate. It keeps only records whose own provenance grants redistribution, fails
# closed if that leaves nothing, and reports every excluded source so the
# exclusion list can be checked against LICENSING.md.
#
# The remaining stages are the SAME code as the local build, pointed at the
# filtered corpus -- the public artifact is not a separate renderer, so it cannot
# drift from the one the tests and audits cover.
publish-filter: 
	$(PY) -m bugd.cli --public-dir $(PUBLIC_EXTRACTED) publish-filter

public: publish-filter
	$(PY) scripts/build_keymap.py --extracted-dir $(PUBLIC_EXTRACTED) --merge-dir $(PUBLIC_MERGE_DIR)
	$(PY) -m bugd.cli \
	  --extracted-dir $(PUBLIC_EXTRACTED) \
	  --keymap $(PUBLIC_MERGE_DIR)/keymap.json \
	  --unified $(PUBLIC_MERGE_DIR)/unified.jsonl \
	  --merged-dir $(PUBLIC_MERGED) \
	  merge
	$(PY) -m bugd.cli \
	  --merged-dir $(PUBLIC_MERGED) \
	  --build-dir $(PUBLIC_BUILD) \
	  --dist-dir $(PUBLIC_DIST) \
	  --require-entries \
	  build
	$(PY) -m bugd.cli --build-dir $(PUBLIC_BUILD) --require-entries validate
	$(PY) scripts/audit_public_archive.py $(PUBLIC_ZIP) $(PUBLIC_EXTRACTED)

public-validate-node:
	$(NODE) scripts/validate_yomitan.mjs $(PUBLIC_ZIP)

# Independent packaged-bytes proof that the public archive carries nothing from a
# source the redistribution filter excluded, and that every admitted source is
# both present and attributed. A gate that is never run is not a gate.
audit-public:
	$(PY) scripts/audit_public_archive.py $(PUBLIC_ZIP) $(PUBLIC_EXTRACTED)

clean:
	rm -rf build dist data/extracted data/merged \
	       $(PUBLIC_EXTRACTED) $(PUBLIC_MERGE_DIR) $(PUBLIC_MERGED) $(PUBLIC_BUILD) $(PUBLIC_DIST)
