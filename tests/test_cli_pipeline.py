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


def test_all_stage_runs_the_whole_pipeline(tmp_path, capsys):
    assert main(_args("all", tmp_path, "--revision", "2026.09.08")) == 0
    out = capsys.readouterr().out
    assert "[extract]" in out
    assert "[build]" in out
    assert "validation passed" in out


def test_extract_stage_with_no_registered_sources_writes_nothing(tmp_path):
    assert main(_args("extract", tmp_path)) == 0
    assert list((tmp_path / "extracted").glob("*.json")) == []


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
