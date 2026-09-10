"""Packaging, reproducibility, and pinned-schema validation of the built ZIP."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from bugd import (
    DICTIONARY_AUTHOR,
    DICTIONARY_FORMAT,
    DICTIONARY_TITLE,
    TERM_BANK_SHARD,
    YOMITAN_SCHEMA_REVISION,
)
from bugd.banks import (
    CARD_ROOT_ROLE,
    COMPACT_MEANING_BUDGET,
    build_banks,
    build_index,
    build_tag_bank,
    build_term_entry,
)
from bugd.jsonio import MalformedPayload, dump_json, load_json
from bugd.merge import MergedEntry, merge_points
from bugd.model import Example, GrammarPoint
from bugd.package import ZIP_DATE, build_zip, package_members
from bugd.pipeline import SchemaValidationError, run_build, run_validate, zip_name
from bugd.styles import STYLES_CSS
from bugd.validate import ALLOWED_EXTRA_MEMBERS, term_entry_count, validate_zip


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
    # indexUrl + downloadUrl, so a local-only index must omit all three. Both URLs
    # have to be switched off explicitly, because the published coordinates are the
    # default (a shipped archive has to say where it came from).
    index = build_index("2026.09.08", index_url=None, download_url=None)
    assert "isUpdatable" not in index
    assert "indexUrl" not in index
    assert "downloadUrl" not in index


def test_self_updating_index_needs_both_urls():
    with pytest.raises(MalformedPayload):
        build_index("1", index_url="https://example.invalid/index.json", download_url=None)
    with pytest.raises(MalformedPayload):
        build_index("1", index_url=None, download_url="https://example.invalid/d.zip")


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


def test_card_composition_renders_the_frozen_contract(sample_point):
    """The compact block, per-source disclosure, and attribution all render.

    Replaces the scaffold's `NotImplementedError` placeholder now that card
    composition has landed.
    """
    entry = merge_points([sample_point])[0]
    row = build_term_entry(entry, 1)

    # Positional term-bank shape.
    assert row[0] == "そうです"
    assert row[6] == 1
    assert len(row[5]) == 1, "one canonical structured-content surface per entry"

    card = row[5][0]
    assert card["type"] == "structured-content"
    root = card["content"]
    assert root["data"] == {CARD_ROOT_ROLE: ""}

    children = root["content"]
    # Compact first; all disclosures are per-source sourceBlocks. There is NO
    # trailing data-less "Sources" attribution details — each sourceBlock is
    # titled with its own source, so the source IS the attribution.
    assert children[0]["data"] == {"compact": ""}
    last = children[-1]
    is_attribution = (
        last.get("tag") == "details"
        and not last.get("data")
        and isinstance(last.get("content"), list)
        and last["content"][0].get("content") == "Sources"
    )
    assert not is_attribution, "no trailing data-less 'Sources' attribution block"

    # Every disclosure is a per-source sourceBlock (carries the sourceBlock role).
    details_children = [c for c in children if c.get("tag") == "details"]
    assert details_children, "a contributing source must produce a disclosure"
    assert all("sourceBlock" in (d.get("data") or {}) for d in details_children)

    # Every disclosure is closed by default: `details` without `open`.
    disclosures = details_children
    assert all("open" not in d for d in disclosures)

    # The compact line carries the meaning, construction badge, and JLPT.
    compact = json.dumps(children[0], ensure_ascii=False)
    assert "hearsay; I hear that" in compact
    assert "Verb[casual] + そうです" in compact
    assert "N4" in compact


def test_compact_meaning_is_bounded_on_a_sense_boundary():
    """A long multi-sense gloss is shortened between senses, never mid-word."""
    long_meaning = "; ".join(f"sense number {n} of the source gloss" for n in range(1, 8))
    point = GrammarPoint(
        source="fixture", source_id="1", expression="x", meaning=long_meaning
    )
    row = build_term_entry(merge_points([point])[0], 1)
    compact = row[5][0]["content"]["content"][0]
    rendered = compact["content"][0]["content"]
    assert len(rendered) <= COMPACT_MEANING_BUDGET + 1  # +1 for the ellipsis
    assert rendered.endswith("…")
    # Cut on a sense boundary, so no partial sense is shown.
    assert "sense number 1 of the source gloss" in rendered


def test_a_table_structure_is_not_used_as_a_compact_badge():
    """DoJG-style pipe tables become a Construction list, not a mangled chip."""
    point = GrammarPoint(
        source="fixture",
        source_id="1",
        expression="あえて",
        meaning="daringly",
        structure="あえて | Verb | |\n| あえて反対する | Someone dares to disagree |",
    )
    row = build_term_entry(merge_points([point])[0], 1)
    children = row[5][0]["content"]["content"]
    compact = json.dumps(children[0], ensure_ascii=False)
    assert "|" not in compact, "raw table pipes must never reach the compact card"
    assert "structure" not in compact, "a table is not a badge"
    # The source's patterns are still shown, in that source's disclosure.
    body = json.dumps(children[1], ensure_ascii=False)
    assert "あえて反対する" in body
    assert "pattern" in body


def test_meaning_language_is_declared_from_the_text():
    """Sources publish English AND Japanese meanings; the tag must match."""
    english = GrammarPoint(source="s", source_id="1", expression="a", meaning="during; while")
    japanese = GrammarPoint(source="s", source_id="2", expression="b", meaning="〜だけでもいいから")
    for point, expected in ((english, "en"), (japanese, "ja")):
        row = build_term_entry(merge_points([point])[0], 1)
        span = row[5][0]["content"]["content"][0]["content"][0]
        assert span["data"] == {"meaning": ""}
        assert span["lang"] == expected


def test_repeated_source_becomes_one_disclosure_with_labelled_senses():
    """Many records from one source must not stack identical summary rows."""
    points = [
        GrammarPoint(
            source="s",
            source_id=str(n),
            expression="ない",
            meaning=f"sense {n}",
            explanation=f"explanation {n}",
            provenance={"sourceLabel": "One Source"},
        )
        for n in range(1, 6)
    ]
    row = build_term_entry(merge_points(points)[0], 1)
    children = row[5][0]["content"]["content"]
    disclosures = [c for c in children if c.get("tag") == "details" and c.get("data")]
    assert len(disclosures) == 1, "one disclosure per SOURCE, not per record"
    summary = json.dumps(disclosures[0]["content"][0], ensure_ascii=False)
    assert summary.count("One Source") == 1
    body = json.dumps(disclosures[0]["content"][1], ensure_ascii=False)
    assert "senseLabel" in body


def test_an_alias_only_entry_points_at_the_canonical_form():
    """A spelling variant with no substance must not render as an empty card."""
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="相まって",
        provenance={"aliasOf": "あいまって", "sourceLabel": "Src"},
    )
    row = build_term_entry(merge_points([point])[0], 1)
    children = row[5][0]["content"]["content"]
    crossref = next(c for c in children if c.get("data") == {"crossref": ""})
    link = crossref["content"][1]
    assert link["tag"] == "a"
    assert link["href"] == "?query=あいまって&wildcards=off"
    assert link["content"] == "あいまって"


def test_a_listed_but_undescribed_headword_says_so_without_inventing_content():
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="おかわり",
        provenance={
            "sourceLabel": "絵でわかる日本語",
            "producerLinks": ["http://www.edewakaru.com/archives/20231311.html"],
        },
    )
    row = build_term_entry(merge_points([point])[0], 1)
    children = row[5][0]["content"]["content"]
    listed = next(c for c in children if c.get("data") == {"listedOnly": ""})
    text = json.dumps(listed, ensure_ascii=False)
    assert "without an explanation" in text
    assert "edewakaru.com" in text


def test_only_source_marked_substrings_are_highlighted():
    """Highlighting is source-driven; the longest marker wins over a substring."""
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="あっての",
        meaning="m",
        examples=(
            Example(japanese="過去があっての現在", highlight=("があっての", "あっての")),
        ),
    )
    row = build_term_entry(merge_points([point])[0], 1)
    body = json.dumps(row[5][0]["content"]["content"][1], ensure_ascii=False)
    assert '"hl"' in body
    # The longer marker is the one applied, not the nested shorter one.
    assert "があっての" in body


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


def test_summary_draws_its_own_disclosure_chevron():
    """`display: flex` on a summary removes Chromium's ::marker.

    Measured in real Yomitan 26.8.24.0: every summary reported
    `list-style-type: disclosure-closed` while painting no marker and leaving
    its first child at inset 0, so the source rows looked like static text.
    Flex is what centres the 44px hit area, so the chevron must be an explicit
    child box, the native markers must be suppressed so nothing paints twice,
    and it must rotate on open.
    """
    assert "summary::before" in STYLES_CSS
    assert "summary::-webkit-details-marker" in STYLES_CSS
    assert "details[open] > summary::before" in STYLES_CSS
    # currentColor keeps the chevron in forced-colors mode without a rule there.
    assert "border-right: 2px solid currentColor" in STYLES_CSS
    # A summary that is still `display: flex` without a drawn marker is the bug.
    assert "list-style: none" in STYLES_CSS


def test_summary_has_a_resting_boundary_not_only_a_hover_state():
    """A control row must look like a control before the pointer arrives.

    Round-2 review of the real host still called the rows out: the chevron alone
    (measured 6.3px, pure black -- not grey) did not make a 13-row stack read as
    interactive. The row carries its own surface at rest, and the enclosing
    `details` draws the boundary so an OPEN disclosure keeps its revealed body
    inside the box (round 6 filed three must-fix reports when the border closed
    above the body and the attribution appeared to fall outside it).
    """
    assert "--bugd-well:" in STYLES_CSS
    assert "--bugd-well-hover:" in STYLES_CSS
    summary_block = STYLES_CSS.split("[data-sc-grammar-card] summary {", 1)[1].split("}", 1)[0]
    assert "background: var(--bugd-well)" in summary_block
    # The row's fill must not double as a boundary; the box owns that.
    assert "border: 1px solid" not in summary_block
    assert "var(--bugd-rule)" not in summary_block
    # The edge is deliberately NOT --bugd-rule. At Yomitan's #eee a 1px edge on a
    # white background is barely a pixel of contrast, and review kept reading an
    # identically-bordered stack as "one row is boxed, the next has no boundary".
    # The disclosure therefore owns a stronger token than the card's hairlines.
    assert "--bugd-control-edge:" in STYLES_CSS
    details_block = STYLES_CSS.split("[data-sc-grammar-card] details {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--bugd-control-edge)" in details_block
    # A double divider: the box's border plus a separate rule on the wrapper.
    assert "border-top:" not in details_block
    # forced-colors must drop the translucent fill, which is not a system colour.
    forced = STYLES_CSS.split("@media (forced-colors: active)", 1)[1]
    assert "--bugd-well: Canvas" in forced


def test_metadata_chips_share_one_pill_radius():
    """The JLPT badge and the construction chip must read as one chip family."""
    assert "--bugd-pill:" in STYLES_CSS
    assert STYLES_CSS.count("border-radius: var(--bugd-pill)") >= 2


def test_forced_colors_does_not_paint_over_the_summary_label():
    """A forced hover background would erase the label behind it."""
    forced = STYLES_CSS.split("@media (forced-colors: active)", 1)[1]
    assert "summary:hover" in forced
    assert "background: transparent" in forced


def test_merged_entry_is_the_only_bank_input():
    assert MergedEntry(expression="x").contributions == []


def test_index_json_in_the_built_zip_is_canonical_json(tmp_path):
    run_build(merged_dir=tmp_path / "a", build_dir=tmp_path / "b", revision="2026.09.08")
    with zipfile.ZipFile(tmp_path / "b" / zip_name()) as archive:
        payload = load_json(archive.read("index.json").decode("utf-8"))
    assert payload["title"] == DICTIONARY_TITLE


# --------------------------------------------------------------------------
# release gate: dist publication, entry counts, and stray members
# --------------------------------------------------------------------------


def _term_entry(sequence: int, *, media_path: str | None = None) -> list:
    """One schema-valid structured-content term entry for packaging tests."""
    content: list = [{"tag": "div", "content": "hearsay; I hear that"}]
    if media_path is not None:
        content.append(
            {"tag": "img", "path": media_path, "collapsed": False, "collapsible": False}
        )
    return [
        "そうです", "", "fixture", "", 0,
        [{
            "type": "structured-content",
            "content": {"tag": "div", "data": {CARD_ROOT_ROLE: "root"}, "content": content},
        }],
        sequence, "",
    ]


def _built(tmp_path, members):
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(build_zip(members))
    return zip_path


def test_a_populated_archive_passes_the_full_gate(tmp_path):
    zip_path = _built(
        tmp_path,
        package_members(
            index=build_index("2026.09.08"),
            banks={"term_bank_1.json": [_term_entry(n, media_path="media/x.png") for n in (1, 2)]},
            tag_bank=build_tag_bank({"fixture": "Fixture Source"}),
            styles_css=STYLES_CSS,
            media={"x.png": b"\x89PNG\r\n\x1a\n"},
        ),
    )
    assert validate_zip(zip_path, require_entries=True) == []
    assert term_entry_count(zip_path) == 2


def test_term_entry_count_is_read_back_from_the_artifact(tmp_path):
    zip_path = _built(
        tmp_path,
        package_members(
            index=build_index("1"),
            banks={
                "term_bank_1.json": [_term_entry(1), _term_entry(2)],
                "term_bank_2.json": [_term_entry(3)],
            },
            styles_css=STYLES_CSS,
        ),
    )
    assert term_entry_count(zip_path) == 3


def test_require_entries_refuses_an_empty_dictionary(tmp_path):
    zip_path = _built(
        tmp_path, package_members(index=build_index("1"), banks={}, styles_css=STYLES_CSS)
    )
    # Structurally valid, so the default gate passes; the release gate does not.
    assert validate_zip(zip_path) == []
    failures = validate_zip(zip_path, require_entries=True)
    assert any("no term entries" in failure for failure in failures)


def test_validate_refuses_a_member_yomitan_would_silently_ignore(tmp_path):
    zip_path = _built(
        tmp_path,
        package_members(
            index=build_index("1"),
            banks={},
            styles_css=STYLES_CSS,
            extra={"README.md": "shipped but never imported"},
        ),
    )
    failures = validate_zip(zip_path)
    assert any("unrecognised archive member" in failure for failure in failures)


def test_notice_and_attribution_members_are_allowed(tmp_path):
    # A credits or notice file may travel with the archive without tripping the
    # stray-member gate.
    zip_path = _built(
        tmp_path,
        package_members(
            index=build_index("1"),
            banks={},
            styles_css=STYLES_CSS,
            extra={name: "x" for name in sorted(ALLOWED_EXTRA_MEMBERS)},
        ),
    )
    assert validate_zip(zip_path) == []


def test_validate_reports_duplicate_member_names(tmp_path):
    # zipfile permits duplicate names; Yomitan would read only one of them.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.json", dump_json(build_index("1")))
        archive.writestr("styles.css", "")
        archive.writestr("styles.css", "")
    zip_path = tmp_path / zip_name()
    zip_path.write_bytes(buffer.getvalue())
    failures = validate_zip(zip_path)
    assert any("duplicate member names" in failure for failure in failures)


def test_build_publishes_validated_bytes_to_dist(tmp_path):
    result = run_build(
        merged_dir=tmp_path / "absent",
        build_dir=tmp_path / "build",
        dist_dir=tmp_path / "dist",
        revision="2026.09.08",
    )
    dist_path = tmp_path / "dist" / zip_name()
    assert result["distPath"] == str(dist_path)
    # dist bytes are the exact validated build bytes, not a rebuild.
    assert dist_path.read_bytes() == (tmp_path / "build" / zip_name()).read_bytes()
    sums = (tmp_path / "dist" / "SHA256SUMS").read_text(encoding="utf-8")
    assert sums == f"{result['sha256']}  {zip_name()}\n"


def test_build_does_not_publish_unless_asked(tmp_path):
    result = run_build(
        merged_dir=tmp_path / "absent", build_dir=tmp_path / "build", revision="1"
    )
    assert "distPath" not in result
    assert not (tmp_path / "dist").exists()


def test_build_reports_the_artifacts_own_digest_and_entry_count(tmp_path):
    result = run_build(
        merged_dir=tmp_path / "absent", build_dir=tmp_path / "build", revision="2026.09.08"
    )
    zip_path = tmp_path / "build" / zip_name()
    assert result["sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert result["termEntries"] == term_entry_count(zip_path)
    assert result["schemaRevision"] == YOMITAN_SCHEMA_REVISION


def test_build_fails_closed_and_publishes_nothing_on_a_gate_failure(tmp_path):
    dist_dir = tmp_path / "dist"
    with pytest.raises(SchemaValidationError) as raised:
        run_build(
            merged_dir=tmp_path / "absent",
            build_dir=tmp_path / "build",
            dist_dir=dist_dir,
            revision="2026.09.08",
            require_entries=True,
        )
    assert any("no term entries" in failure for failure in raised.value.failures)
    assert not dist_dir.exists()


def test_dist_publication_is_atomic_over_an_existing_artifact(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / zip_name()).write_bytes(b"stale")
    result = run_build(
        merged_dir=tmp_path / "absent",
        build_dir=tmp_path / "build",
        dist_dir=dist_dir,
        revision="2026.09.08",
    )
    assert (dist_dir / zip_name()).read_bytes() != b"stale"
    assert sorted(p.name for p in dist_dir.iterdir()) == [
        "SHA256SUMS",
        zip_name(),
        "index.json",
    ]
    assert result["sha256"] in (dist_dir / "SHA256SUMS").read_text(encoding="utf-8")


def test_validate_stage_can_apply_the_release_gate(tmp_path):
    run_build(merged_dir=tmp_path / "absent", build_dir=tmp_path / "build", revision="1")
    assert run_validate(build_dir=tmp_path / "build") == (True, [])
    ok, failures = run_validate(build_dir=tmp_path / "build", require_entries=True)
    assert not ok
    assert any("no term entries" in failure for failure in failures)
