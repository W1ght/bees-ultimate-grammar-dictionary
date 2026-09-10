"""CLI stage wiring: each stage runs standalone and reads only the prior artifact."""

from __future__ import annotations

import pytest

from bugd.cli import main
from bugd.jsonio import dump_json
from bugd.pipeline import (
    MERGED_CORPUS_NAME,
    point_to_json,
    run_merge,
    zip_name,
)


def _args(stage, tmp_path, *extra):
    # Every directory is redirected under tmp_path, including --dist-dir: the CLI
    # publishes to `dist/` by default, so a test that omitted it would write the
    # repository's real distribution directory as a side effect of running the
    # suite. The same applies to --unified: the merge stage's default output is
    # `data/merge/unified.jsonl`, and a stage test that let it default TRUNCATED
    # the repository's real unified dataset to zero bytes.
    return [
        "--sources-dir", str(tmp_path / "sources"),
        "--extracted-dir", str(tmp_path / "extracted"),
        "--corrections-dir", str(tmp_path / "corrections"),
        "--merged-dir", str(tmp_path / "merged"),
        "--keymap", str(tmp_path / "keymap.json"),
        "--unified", str(tmp_path / "unified.jsonl"),
        "--build-dir", str(tmp_path / "build"),
        "--dist-dir", str(tmp_path / "dist"),
        *extra,
        stage,
    ]


def test_build_stage_exits_zero_with_no_sources(tmp_path, capsys):
    assert main(_args("build", tmp_path, "--revision", "2026.09.08")) == 0
    assert (tmp_path / "build" / zip_name()).is_file()
    assert "[build]" in capsys.readouterr().out


def test_validate_stage_passes_on_the_stub_build(tmp_path, capsys):
    main(_args("build", tmp_path, "--revision", "2026.09.08"))
    assert main(_args("validate", tmp_path)) == 0
    assert "validation passed" in capsys.readouterr().out


def test_validate_stage_fails_without_a_build(tmp_path):
    assert main(_args("validate", tmp_path)) == 1


def _locked_dojg_source(sources_dir):
    """Write a real, digest-locked one-row DoJG term bank.

    Built through the production lock shape rather than a stub: the extractor
    verifies sha256 and byteCount over the exact bytes on disk, so a fixture that
    faked the lock would not exercise the path the pipeline actually takes.
    """
    import hashlib

    target = sources_dir / "dojg"
    target.mkdir(parents=True, exist_ok=True)
    member = "term_bank_1.json"
    raw = dump_json(
        [
            [
                "そうです",
                "そうです",
                "",
                "",
                0,
                ["文法項目|そうです|Basic\n解説\nHearsay.\n意味\nI hear that\n接続\nVerb + そうです"],
                1,
                "dojg1",
            ]
        ]
    ).encode("utf-8")
    (target / member).write_bytes(raw)
    (target / "SOURCE.lock.json").write_text(
        dump_json(
            {
                "source": "dojg",
                "files": {
                    member: {
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "byteCount": len(raw),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return target


def _keymap_for_extracted(tmp_path):
    """Build the keymap from the extracted artifacts via the production builder."""
    from bugd.keymap import build_keymap

    payload = build_keymap(tmp_path / "extracted")
    (tmp_path / "keymap.json").write_text(dump_json(payload) + "\n", encoding="utf-8")
    return tmp_path / "keymap.json"


def test_all_stage_runs_the_whole_pipeline(tmp_path, capsys):
    # `all` runs `extract` first, and extract now really discovers the registered
    # sources, so a stage test cannot point it at an empty --sources-dir: every
    # extractor fails closed on a missing SOURCE.lock.json. Restricting the stage
    # to one source with a real locked bank keeps this a wiring test (does each
    # stage hand off to the next?) while still exercising the discovery seam.
    #
    # The keymap is built from the artifact extract just wrote, through the same
    # production builder `make keymap` uses. `all` deliberately does NOT build it
    # (merge refuses to invent keys, because a derived-key fallback silently drops
    # rows), so the keymap is a real prerequisite of the merge stage.
    _locked_dojg_source(tmp_path / "sources")
    assert main(_args("extract", tmp_path, "--source", "dojg")) == 0
    _keymap_for_extracted(tmp_path)

    # This corpus is ONE source's fixture bank, not the repository's real
    # extraction, so the canonical reading overlay (which is keyed to specific
    # real dojg rows) legitimately matches nothing here and the fail-closed
    # `StaleCorrection` guard fires correctly. Declare the isolated corpus rather
    # than weakening the guard: `tests/test_readings.py` still exercises it on
    # real drift, and all eight corrections are verified applied in the shipped
    # artifact.
    assert (
        main(
            _args(
                "all",
                tmp_path,
                "--revision",
                "2026.09.08",
                "--source",
                "dojg",
                "--no-reading-corrections",
            )
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "[extract]" in out
    assert "[merge]" in out
    assert "[build]" in out
    assert "validation passed" in out


def test_extract_stage_discovers_registered_sources_without_being_told_them(tmp_path):
    """Extract must find the sources by itself, not report an empty build.

    This replaces `test_extract_stage_with_no_registered_sources_writes_nothing`,
    which asserted extract wrote NOTHING when handed an empty sources dir. That
    passed for the wrong reason: nothing in the shipped code ever imported the
    concrete source modules, so the registry was empty in a complete checkout and
    `extract` was a silent no-op that still exited 0. The durable property is the
    opposite one -- extract discovers every registered source through the registry
    seam and actually produces that source's artifact.
    """
    _locked_dojg_source(tmp_path / "sources")
    assert main(_args("extract", tmp_path, "--source", "dojg")) == 0
    written = sorted(p.name for p in (tmp_path / "extracted").glob("*.json"))
    assert written == ["dojg.json"]


def test_extract_skips_a_source_whose_locked_bytes_are_not_acquired(tmp_path):
    """An unacquired source is skipped WITH A REASON, not a hard stage failure.

    The skip used to key on `data/sources/<name>/` existing. But
    `SOURCE.lock.json` is committed for every source -- it IS the reproducibility
    contract -- so in a fresh clone every source directory exists while holding
    only that lock, the check skipped nothing, and `make extract` died on the
    first unacquired source -- so a checkout that had acquired only some sources
    could not build at all.

    Keying on the locked PAYLOAD fixes it. Verified end to end: a clean checkout
    with only `ninjal_bunkei` and `yokubi` acquired extracts 932 points, reports 8
    skips, and reproduces the published archive byte for byte.
    """
    sources = tmp_path / "sources"
    _locked_dojg_source(sources)
    # A second source with its lock present but its locked bytes absent -- exactly
    # the fresh-clone shape.
    unacquired = sources / "donna_toki"
    unacquired.mkdir(parents=True, exist_ok=True)
    (unacquired / "SOURCE.lock.json").write_text(
        dump_json(
            {
                "source": "donna_toki",
                "files": {
                    "term_bank_1.json": {"sha256": "0" * 64, "byteCount": 1},
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(_args("extract", tmp_path)) == 0

    written = sorted(p.name for p in (tmp_path / "extracted").glob("*.json"))
    assert written == ["dojg.json"]


def test_an_unacquired_source_is_reported_not_silently_dropped(tmp_path, capsys):
    """The skip must be visible: a silently smaller dictionary is the failure mode.

    Asserts the source NAME and a reason naming the missing member reach the
    stage's output, not merely that the stage exited 0.
    """
    sources = tmp_path / "sources"
    _locked_dojg_source(sources)
    unacquired = sources / "donna_toki"
    unacquired.mkdir(parents=True, exist_ok=True)
    (unacquired / "SOURCE.lock.json").write_text(
        dump_json(
            {
                "source": "donna_toki",
                "files": {"term_bank_1.json": {"sha256": "0" * 64, "byteCount": 1}},
            }
        ),
        encoding="utf-8",
    )

    assert main(_args("extract", tmp_path)) == 0

    out = capsys.readouterr().out
    assert "skippedSources" in out
    assert "donna_toki" in out
    assert "term_bank_1.json" in out


def test_extract_stage_fails_closed_on_a_source_with_no_locked_input(tmp_path):
    # The counterpart honesty property: an unacquired source is a hard error, not
    # a quietly smaller dictionary.
    from bugd.sources import SourceLockError

    with pytest.raises(SourceLockError):
        main(_args("extract", tmp_path, "--source", "dojg"))


def _fixture_keymap(tmp_path, sample_point):
    """A keymap that actually describes the fixture corpus.

    The merge stage resolves rows through the keymap and fails closed on a row it
    cannot find, so a stage test must supply a keymap built for its own fixture
    rather than borrowing the repository's real one.
    """
    from bugd.keymap import substance_hash

    record = point_to_json(sample_point)
    path = tmp_path / "keymap.json"
    path.write_text(
        dump_json(
            {
                "schemaVersion": 1,
                "assignments": [
                    {
                        "source": sample_point.source,
                        "sourceId": sample_point.source_id,
                        "substanceHash": substance_hash(record),
                        "canonicalKey": sample_point.expression,
                    }
                ],
                "points": [
                    {
                        "canonicalKey": sample_point.expression,
                        "bucketKey": sample_point.expression,
                        "expression": sample_point.expression,
                        "axes": {"variety": "standard", "era": "modern"},
                        "disambiguator": "",
                        "lookupForms": [sample_point.expression],
                        "jlptLevels": [sample_point.jlpt] if sample_point.jlpt else [],
                        "observedRegisters": [],
                        "observedSignatures": [],
                        "contributors": [],
                        "sourceCount": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _fixture_extracted(tmp_path, sample_point):
    extracted = tmp_path / "extracted"
    extracted.mkdir(exist_ok=True)
    payload = {
        "source": sample_point.source,
        "label": "Fixture Source",
        "points": [point_to_json(sample_point)],
    }
    (extracted / "fixture.json").write_text(dump_json(payload), encoding="utf-8")
    return extracted


def test_merge_consumes_extracted_artifacts(tmp_path, sample_point):
    extracted = _fixture_extracted(tmp_path, sample_point)
    stats = run_merge(
        extracted_dir=extracted,
        merged_dir=tmp_path / "merged",
        keymap_path=_fixture_keymap(tmp_path, sample_point),
        unified_path=tmp_path / "unified.jsonl",
        # The synthetic fixture corpus is not described by the canonical reading
        # overlay; merge it with no corrections so the fail-closed stale-overlay
        # gate (exercised in test_readings.py) does not fire on unrelated data.
        corrections_path=None,
    )
    assert stats["points"] == 1
    assert stats["entries"] == 1
    assert stats["pointEntries"] == 1
    assert stats["sources"] == ["fixture"]
    assert (tmp_path / "merged" / MERGED_CORPUS_NAME).is_file()
    # The reviewable unified artifact and its stats sidecar are written too.
    assert (tmp_path / "unified.jsonl").is_file()
    assert (tmp_path / "unified.stats.json").is_file()


def test_merge_fails_closed_when_the_keymap_does_not_describe_the_corpus(
    tmp_path, sample_point
):
    """The stage may not merge on derived keys.

    A keymap built against a superseded extraction left 1,664 substantive rows
    unresolved; tolerating that would silently drop a third of the dictionary
    while reporting a successful merge.
    """
    from bugd.unify import StaleKeymap

    extracted = _fixture_extracted(tmp_path, sample_point)
    empty = tmp_path / "empty-keymap.json"
    empty.write_text(
        dump_json({"schemaVersion": 1, "assignments": [], "points": []}), encoding="utf-8"
    )
    with pytest.raises(StaleKeymap):
        run_merge(
            extracted_dir=extracted,
            merged_dir=tmp_path / "merged",
            keymap_path=empty,
            unified_path=tmp_path / "unified.jsonl",
        )
    # Nothing is written when the gate fires.
    assert not (tmp_path / "merged" / MERGED_CORPUS_NAME).exists()


def test_merge_refuses_a_missing_keymap(tmp_path, sample_point):
    from bugd.jsonio import MalformedPayload

    extracted = _fixture_extracted(tmp_path, sample_point)
    with pytest.raises(MalformedPayload, match="make keymap"):
        run_merge(
            extracted_dir=extracted,
            merged_dir=tmp_path / "merged",
            keymap_path=tmp_path / "absent.json",
            unified_path=tmp_path / "unified.jsonl",
        )


def test_merge_rejects_a_malformed_extracted_artifact(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "bad.json").write_text('{"source":"x"}', encoding="utf-8")
    with pytest.raises(Exception):
        run_merge(extracted_dir=extracted, merged_dir=tmp_path / "merged")


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(KeyError):
        main(_args("extract", tmp_path, "--source", "does-not-exist"))
