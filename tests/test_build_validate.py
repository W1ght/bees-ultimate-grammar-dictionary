"""Packaging, reproducibility, and pinned-schema validation of the built ZIP."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from bugd import DICTIONARY_AUTHOR, DICTIONARY_FORMAT, DICTIONARY_TITLE, TERM_BANK_SHARD
from bugd.banks import build_banks, build_index, build_tag_bank, build_term_entry
from bugd.jsonio import MalformedPayload, load_json
from bugd.merge import MergedEntry, merge_points
from bugd.package import ZIP_DATE, build_zip, package_members
from bugd.pipeline import run_build, run_validate, zip_name
from bugd.styles import STYLES_CSS
from bugd.validate import validate_zip


def test_index_carries_the_unified_title_and_format():
    index = build_index("2026.09.08")
    assert index["title"] == DICTIONARY_TITLE
    assert index["format"] == DICTIONARY_FORMAT
    assert index["author"] == DICTIONARY_AUTHOR
    assert index["revision"] == "2026.09.08"
    assert index["sourceLanguage"] == "ja"


def test_index_requires_a_revision():
    with pytest.raises(MalformedPayload):
        build_index("")


def test_local_only_index_omits_the_updater_fields():
    # Yomitan's schema pins isUpdatable to const:true and makes it depend on
    # indexUrl + downloadUrl, so a local-only index must omit all three.
    index = build_index("2026.09.08")
    assert "isUpdatable" not in index
    assert "indexUrl" not in index
    assert "downloadUrl" not in index


def test_self_updating_index_needs_both_urls():
    with pytest.raises(MalformedPayload):
        build_index("1", index_url="https://example.invalid/index.json")
    with pytest.raises(MalformedPayload):
        build_index("1", download_url="https://example.invalid/d.zip")


def test_self_updating_index_validates_against_the_pinned_schema(tmp_path):
    index = build_index(
        "2026.09.08",
        index_url="https://example.invalid/index.json",
        download_url="https://example.invalid/d.zip",
    )
    assert index["isUpdatable"] is True
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(
        build_zip(package_members(index=index, banks={}, styles_css=STYLES_CSS))
    )
    assert validate_zip(zip_path) == []


def test_tag_bank_is_built_from_per_source_labels():
    bank = build_tag_bank({"bunpro": "Bunpro", "bunpo": "文法 deck"})
    assert [row[0] for row in bank] == ["bunpo", "bunpro"]
    assert all(row[1] == "source" for row in bank)
    assert bank[1][3] == "Bunpro"


def test_empty_corpus_yields_no_term_banks():
    assert build_banks([]) == {}


def test_card_composition_is_still_open(sample_point):
    entry = merge_points([sample_point])[0]
    with pytest.raises(NotImplementedError):
        build_term_entry(entry, 1)
    with pytest.raises(NotImplementedError):
        build_banks([entry])


def test_build_banks_rejects_non_entries():
    with pytest.raises(MalformedPayload):
        build_banks([{"expression": "x"}])  # type: ignore[list-item]


def test_bank_shard_size_is_bounded_for_constrained_imports():
    assert TERM_BANK_SHARD == 1000


@pytest.mark.parametrize(
    "name",
    ["/abs.json", "../escape.json", "back\\slash.json", "./here.json", "other/thing.json"],
)
def test_package_refuses_unsafe_or_non_root_members(name):
    with pytest.raises(MalformedPayload):
        build_zip({name: b"x"})


def test_media_subfolder_is_the_only_permitted_subfolder():
    archive = build_zip({"index.json": "{}", "media/chart.png": b"\x89PNG"})
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        assert sorted(opened.namelist()) == ["index.json", "media/chart.png"]


def test_zip_bytes_are_reproducible():
    members = package_members(index=build_index("2026.09.08"), banks={}, styles_css=STYLES_CSS)
    assert build_zip(members) == build_zip(members)


def test_zip_members_use_the_fixed_timestamp():
    archive = build_zip(package_members(index=build_index("1"), banks={}, styles_css=STYLES_CSS))
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        assert all(info.date_time == ZIP_DATE for info in opened.infolist())


def test_build_then_validate_end_to_end(tmp_path):
    build_dir = tmp_path / "build"
    result = run_build(
        merged_dir=tmp_path / "absent", build_dir=build_dir, revision="2026.09.08"
    )

    zip_path = build_dir / zip_name()
    assert zip_path.is_file()
    assert result["zipPath"] == str(zip_path)
    assert result["entries"] == 0
    assert "index.json" in result["members"]
    assert "styles.css" in result["members"]
    assert len(str(result["sha256"])) == 64

    assert validate_zip(zip_path) == []
    ok, failures = run_validate(build_dir=build_dir)
    assert (ok, failures) == (True, [])


def test_build_is_byte_reproducible_for_a_fixed_revision(tmp_path):
    first = run_build(merged_dir=tmp_path / "a", build_dir=tmp_path / "b1", revision="2026.09.08")
    second = run_build(merged_dir=tmp_path / "a", build_dir=tmp_path / "b2", revision="2026.09.08")
    assert first["sha256"] == second["sha256"]


def test_validate_reports_a_missing_artifact(tmp_path):
    ok, failures = run_validate(build_dir=tmp_path / "nothing")
    assert not ok
    assert any("no built artifact" in failure for failure in failures)


def test_validate_rejects_a_native_kanji_bank(tmp_path):
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(
        build_zip(
            {
                "index.json": '{"title":"t","revision":"1"}',
                "styles.css": "",
                "kanji_bank_1.json": "[]",
            }
        )
    )
    failures = validate_zip(zip_path)
    assert any("forbidden native kanji bank" in failure for failure in failures)


def test_validate_rejects_a_schema_violating_index(tmp_path):
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(build_zip({"index.json": '{"title":"t"}', "styles.css": ""}))
    failures = validate_zip(zip_path)
    assert any("does not match dictionary-index-schema.json" in failure for failure in failures)


def test_validate_rejects_non_contiguous_banks(tmp_path):
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(
        build_zip(
            {
                "index.json": '{"title":"t","revision":"1"}',
                "styles.css": "",
                "term_bank_2.json": "[]",
            }
        )
    )
    failures = validate_zip(zip_path)
    assert any("not contiguous" in failure for failure in failures)


def test_validate_rejects_dangling_media_references(tmp_path):
    entry = [
        "そう", "", "", "", 0,
        [{"type": "structured-content", "content": {"tag": "img", "path": "media/missing.png"}}],
        1, "",
    ]
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(
        build_zip(
            {
                "index.json": '{"title":"t","revision":"1"}',
                "styles.css": "",
                "term_bank_1.json": json.dumps([entry]),
            }
        )
    )
    failures = validate_zip(zip_path)
    assert any("dangling media reference: media/missing.png" in f for f in failures)


def test_styles_are_scoped_to_this_dictionarys_own_marker():
    assert "[data-sc-grammar-card]" in STYLES_CSS
    assert ":root" not in STYLES_CSS
    assert "forced-colors" in STYLES_CSS


def test_merged_entry_is_the_only_bank_input():
    assert MergedEntry(expression="x").contributions == []


def test_index_json_in_the_built_zip_is_canonical_json(tmp_path):
    run_build(merged_dir=tmp_path / "a", build_dir=tmp_path / "b", revision="2026.09.08")
    with zipfile.ZipFile(tmp_path / "b" / zip_name()) as archive:
        payload = load_json(archive.read("index.json").decode("utf-8"))
    assert payload["title"] == DICTIONARY_TITLE
