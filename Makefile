# Bee's Ultimate Grammar Dictionary — build pipeline
#
# Stages, each reading only the previous stage's on-disk artifact:
#   extract  -> data/extracted/<source>.json
#   merge    -> data/merged/corpus.json
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

.PHONY: all extract merge build validate validate-node test clean help

help:
	@printf 'targets: extract merge build validate validate-node test all clean\n'

extract:
	$(PY) -m bugd.cli extract

merge:
	$(PY) -m bugd.cli merge

build:
	$(PY) -m bugd.cli build

validate:
	$(PY) -m bugd.cli validate

# Independent Node/ajv cross-check of the same artifact against the same pinned
# schemas. Requires `npm install`.
validate-node:
	$(NODE) scripts/validate_yomitan.mjs $(ZIP)

test:
	$(PY) -m pytest -q

all: extract merge build validate

clean:
	rm -rf build dist data/extracted data/merged
