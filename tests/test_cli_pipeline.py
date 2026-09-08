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
    # suite.
    return [
        "--sources-dir", str(tmp_path / "sources"),
        "--extracted-dir", str(tmp_path / "extracted"),
        "--merged-dir", str(tmp_path / "merged"),
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


def test_merge_consumes_extracted_artifacts(tmp_path, sample_point):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    payload = {
        "source": sample_point.source,
        "label": "Fixture Source",
        "points": [point_to_json(sample_point)],
    }
    (extracted / "fixture.json").write_text(dump_json(payload), encoding="utf-8")

    stats = run_merge(extracted_dir=extracted, merged_dir=tmp_path / "merged")
    assert stats["points"] == 1
    assert stats["entries"] == 1
    assert stats["sources"] == ["fixture"]
    assert (tmp_path / "merged" / MERGED_CORPUS_NAME).is_file()


def test_merge_rejects_a_malformed_extracted_artifact(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "bad.json").write_text('{"source":"x"}', encoding="utf-8")
    with pytest.raises(Exception):
        run_merge(extracted_dir=extracted, merged_dir=tmp_path / "merged")


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(KeyError):
        main(_args("extract", tmp_path, "--source", "does-not-exist"))
