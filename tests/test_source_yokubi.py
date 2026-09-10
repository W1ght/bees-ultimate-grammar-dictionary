"""Behaviour tests for the Yokubi extractor.

These pin the honesty contract the card requires, not just the happy path:

* headwords come only from what a lesson title itself declares, so no grammar
  point boundary is ever invented;
* a lesson whose title declares no Japanese headword is reported as skipped with
  a recorded reason rather than segmented by guesswork;
* an example is attached to a headword only when the example text actually
  contains that headword; otherwise it stays lesson-scoped context;
* Yokubi's own `<b>` highlights become the example highlight spans, and the
  mdBook `{f|kanji|reading}` furigana markers degrade to clean surface text;
* every emitted point carries the attribution that credits the source.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.jsonio import MalformedPayload
from bugd.sources import SourceLockError
from bugd.sources.yokubi import (
    COVERAGE_NAME,
    JSONL_NAME,
    LESSON_ONLY_REASON,
    YOKUBI_ATTRIBUTION,
    YokubiExtractor,
    parse_examples,
    render_coverage,
    strip_inline_markup,
    title_headwords,
)


def write_source(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    target = root / "yokubi"
    lock_files = {}
    for relative, text in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        path.write_bytes(raw)
        import hashlib

        lock_files[relative] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byteCount": len(raw),
        }
    (target / "SOURCE.lock.json").write_text(
        json.dumps(
            {
                "source": "yokubi",
                "revision": "0" * 40,
                "files": lock_files,
            }
        ),
        encoding="utf-8",
    )
    return target


SUMMARY = """# Summary

- [Part 1](./Section1/Part1.md)
  - [Lesson 1: State of being with だ and です](./Section1/Part1/Lesson1.md)
  - [Lesson 4: Verbs](./Section1/Part1/Lesson4.md)
"""

LESSON1 = """# State of being with だ and です

The two copulas in Japanese are だ and です.

<pre>
ペン<b>だ</b>。
It's a pen.

ネコ<b>です</b>。
It is a cat.
</pre>

<div class="warning">
Reality check: だ is usually omitted.
</div>
"""

LESSON4 = """# Verbs

Japanese verbs conjugate.

<pre>
見る／見ます, ichidan verb.
</pre>
"""


# ---------------------------------------------------------------------------
# headword derivation
# ---------------------------------------------------------------------------


def test_title_headwords_are_taken_only_from_the_title():
    assert title_headwords("State of being with だ and です") == ("だ", "です")


def test_title_headwords_split_on_tilde_placeholders():
    # 〜たり〜たり declares the form たり; the tilde is a placeholder, not a headword.
    assert title_headwords("Listing and repeating actions with 〜たり〜たり and ては") == (
        "たり",
        "ては",
    )


def test_title_headwords_split_alternatives_written_with_a_slash():
    assert title_headwords("Adversatives with が, けど, しかし, and ても/でも") == (
        "が",
        "けど",
        "しかし",
        "ても",
        "でも",
    )


def test_title_headwords_are_empty_when_the_title_declares_none():
    assert title_headwords("The causative form") == ()
    assert title_headwords("Counting things") == ()


def test_title_headwords_are_deduplicated_preserving_order():
    assert title_headwords("Making and becoming with なる and する plus なる") == (
        "なる",
        "する",
    )


# ---------------------------------------------------------------------------
# inline markup
# ---------------------------------------------------------------------------


def test_strip_inline_markup_removes_tags_and_decodes_entities():
    assert strip_inline_markup("<b>だ</b>&lt;verb&gt;てあげる") == "だ<verb>てあげる"


def test_strip_inline_markup_degrades_furigana_to_surface_text():
    assert strip_inline_markup("{f|事|こと}をする") == "事をする"


# ---------------------------------------------------------------------------
# example parsing
# ---------------------------------------------------------------------------


def test_parse_examples_pairs_japanese_with_its_english_line():
    examples, skipped = parse_examples(LESSON1)
    assert [(e.japanese, e.english) for e in examples] == [
        ("ペンだ。", "It's a pen."),
        ("ネコです。", "It is a cat."),
    ]
    assert skipped == []


def test_parse_examples_records_source_bold_spans_as_highlights():
    examples, _ = parse_examples(LESSON1)
    assert examples[0].highlight == ("だ",)
    assert examples[1].highlight == ("です",)


def test_parse_examples_never_marks_an_example_ai_generated():
    examples, _ = parse_examples(LESSON1)
    assert all(example.ai_generated is False for example in examples)


def test_parse_examples_skips_unpaired_groups_with_a_recorded_reason():
    examples, skipped = parse_examples(LESSON4)
    assert examples == []
    assert len(skipped) == 1
    assert skipped[0]["shape"] == "M"
    assert "reason" in skipped[0]
    assert skipped[0]["text"].startswith("見る")


def test_parse_examples_keeps_japanese_only_groups_without_inventing_english():
    examples, skipped = parse_examples("# T\n\n<pre>\n食べる\n</pre>\n")
    assert len(examples) == 1
    assert examples[0].japanese == "食べる"
    assert examples[0].english is None
    assert skipped == []


# ---------------------------------------------------------------------------
# extractor behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def extracted(tmp_path):
    target = write_source(
        tmp_path,
        {
            "src/SUMMARY.md": SUMMARY,
            "src/Section1/Part1.md": "# Part 1: Getting Started\n",
            "src/Section1/Part1/Lesson1.md": LESSON1,
            "src/Section1/Part1/Lesson4.md": LESSON4,
        },
    )
    return YokubiExtractor(target).extract()


def test_extractor_emits_one_point_per_title_declared_headword(extracted):
    assert [point.expression for point in extracted.points] == ["だ", "です"]


def test_extractor_attributes_every_point_to_yokubi(extracted):
    for point in extracted.points:
        assert point.source == "yokubi"
        assert point.provenance["attribution"] == YOKUBI_ATTRIBUTION
        assert point.provenance["lessonUrl"].startswith("https://yoku.bi/")


def test_extractor_records_the_pinned_revision_on_every_point(extracted):
    for point in extracted.points:
        assert point.provenance["revision"] == "0" * 40


def test_extractor_never_invents_a_meaning_or_jlpt_level(extracted):
    for point in extracted.points:
        assert point.meaning is None
        assert point.jlpt is None


def test_extractor_carries_the_lesson_prose_as_the_explanation(extracted):
    point = extracted.points[0]
    assert "The two copulas in Japanese are だ and です." in point.explanation


def test_extractor_attaches_an_example_only_when_it_contains_the_headword(extracted):
    by_expression = {point.expression: point for point in extracted.points}
    assert [e.japanese for e in by_expression["だ"].examples] == ["ペンだ。"]
    assert [e.japanese for e in by_expression["です"].examples] == ["ネコです。"]


def test_extractor_reports_lessons_without_a_declared_headword_as_skipped(extracted):
    skipped = extracted.stats["skippedLessons"]
    assert [item["title"] for item in skipped] == ["Verbs"]
    assert skipped[0]["reason"] == LESSON_ONLY_REASON
    assert skipped[0]["lesson"] == 4


def test_extractor_never_reports_a_lesson_as_both_covered_and_skipped(extracted):
    covered = {point.provenance["lesson"] for point in extracted.points}
    skipped = {item["lesson"] for item in extracted.stats["skippedLessons"]}
    assert covered.isdisjoint(skipped)


def test_extractor_counts_every_summary_lesson_exactly_once(extracted):
    stats = extracted.stats
    covered = len({point.provenance["lesson"] for point in extracted.points})
    assert covered + len(stats["skippedLessons"]) == stats["lessonsListed"]


def test_extractor_records_lesson_scoped_examples_rather_than_forcing_them(extracted):
    # Lesson 4's example matches no declared headword, so it must be counted as
    # unattached context, never silently attributed to a headword.
    assert extracted.stats["examplesUnattached"] >= 1


def test_extractor_output_is_deterministic(tmp_path):
    files = {
        "src/SUMMARY.md": SUMMARY,
        "src/Section1/Part1.md": "# Part 1\n",
        "src/Section1/Part1/Lesson1.md": LESSON1,
        "src/Section1/Part1/Lesson4.md": LESSON4,
    }
    first = YokubiExtractor(write_source(tmp_path / "a", files)).extract()
    second = YokubiExtractor(write_source(tmp_path / "b", files)).extract()
    assert [p.expression for p in first.points] == [p.expression for p in second.points]
    assert first.stats["skippedLessons"] == second.stats["skippedLessons"]


def test_extractor_fails_closed_on_a_tampered_lesson(tmp_path):
    target = write_source(
        tmp_path,
        {
            "src/SUMMARY.md": SUMMARY,
            "src/Section1/Part1.md": "# Part 1\n",
            "src/Section1/Part1/Lesson1.md": LESSON1,
            "src/Section1/Part1/Lesson4.md": LESSON4,
        },
    )
    (target / "src/Section1/Part1/Lesson1.md").write_text("# tampered\n", encoding="utf-8")
    with pytest.raises(SourceLockError):
        YokubiExtractor(target).extract()


def test_extractor_fails_closed_when_a_listed_lesson_is_absent_from_the_lock(tmp_path):
    target = write_source(
        tmp_path,
        {
            "src/SUMMARY.md": SUMMARY,
            "src/Section1/Part1.md": "# Part 1\n",
            "src/Section1/Part1/Lesson1.md": LESSON1,
        },
    )
    with pytest.raises(SourceLockError):
        YokubiExtractor(target).extract()


# ---------------------------------------------------------------------------
# emitted artifacts: JSONL records + coverage report
# ---------------------------------------------------------------------------


@pytest.fixture
def emitted(tmp_path):
    """The source directory after a real extraction, so the artifacts are on disk."""
    target = write_source(
        tmp_path,
        {
            "src/SUMMARY.md": SUMMARY,
            "src/Section1/Part1.md": "# Part 1\n",
            "src/Section1/Part1/Lesson1.md": LESSON1,
            "src/Section1/Part1/Lesson4.md": LESSON4,
        },
    )
    result = YokubiExtractor(target).extract()
    return target, result


def test_extract_writes_one_jsonl_record_per_point(emitted):
    target, result = emitted
    lines = (target / JSONL_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(result.points)
    assert [json.loads(line)["expression"] for line in lines] == [
        point.expression for point in result.points
    ]


def test_jsonl_records_carry_attribution_and_provenance(emitted):
    target, _ = emitted
    for line in (target / JSONL_NAME).read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert record["source"] == "yokubi"
        assert record["provenance"]["attribution"] == YOKUBI_ATTRIBUTION
        assert record["provenance"]["revision"] == "0" * 40


def test_jsonl_is_one_json_object_per_line_and_ends_with_a_newline(emitted):
    target, _ = emitted
    raw = (target / JSONL_NAME).read_text(encoding="utf-8")
    assert raw.endswith("\n")
    for line in raw.splitlines():
        assert isinstance(json.loads(line), dict)


def test_jsonl_bytes_are_deterministic_across_runs(emitted):
    target, _ = emitted
    first = (target / JSONL_NAME).read_bytes()
    YokubiExtractor(target).extract()
    assert (target / JSONL_NAME).read_bytes() == first


def test_coverage_report_is_written_and_names_the_source(emitted):
    target, _ = emitted
    text = (target / COVERAGE_NAME).read_text(encoding="utf-8")
    assert YOKUBI_ATTRIBUTION in text
    assert "0" * 40 in text


def test_coverage_report_records_a_reason_for_every_skipped_lesson(emitted):
    target, result = emitted
    text = (target / COVERAGE_NAME).read_text(encoding="utf-8")
    skipped = result.stats["skippedLessons"]
    assert skipped

    section = text.split("## Skipped lessons", 1)[1].split("## Skipped example groups", 1)[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("| ---") and "Lesson |" not in line
    ]
    assert len(rows) == len(skipped)
    for row, entry in zip(rows, skipped):
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[0] == str(entry["lesson"])
        assert str(entry["title"]) in cells[1]
        # The reason must be rendered, not merely present somewhere in the file.
        assert cells[2] == str(entry["reason"])
        assert cells[2]


def test_coverage_report_lists_every_covered_lesson_with_its_headwords(emitted):
    target, result = emitted
    text = (target / COVERAGE_NAME).read_text(encoding="utf-8")
    covered = result.stats["coveredLessons"]
    assert covered

    # Parse the rendered rows so an empty headword cell cannot pass: a lesson's
    # headwords are the whole point of the covered table.
    section = text.split("## Covered lessons", 1)[1].split("## Skipped lessons", 1)[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("| ---") and "Lesson |" not in line
    ]
    assert len(rows) == len(covered)
    for row, entry in zip(rows, covered):
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[0] == str(entry["lesson"])
        assert str(entry["title"]) in cells[1]
        assert cells[2] == ", ".join(f"`{head}`" for head in entry["headwords"])
        assert cells[2]
        assert cells[3] == str(entry["examplesAttached"])


def test_coverage_report_accounts_for_every_listed_lesson(emitted):
    _, result = emitted
    stats = result.stats
    assert stats["coveredCount"] + stats["skippedCount"] == stats["lessonsListed"]


def test_coverage_report_records_skipped_example_groups_with_their_lesson(emitted):
    target, result = emitted
    text = (target / COVERAGE_NAME).read_text(encoding="utf-8")
    groups = result.stats["exampleGroupsSkipped"]
    assert groups

    # Read the rendered rows, not just the stats dict: a skip is only reportable
    # when the report itself names the lesson that declared it. Asserting the
    # key exists in stats passes even when the row renders an empty cell.
    section = text.split("## Skipped example groups", 1)[1]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("| ---") and "Shape" not in line
    ]
    assert len(rows) == len(groups)
    for row, group in zip(rows, groups):
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[0] == str(group["lesson"])
        assert cells[1] == f"`{group['shape']}`"
        assert cells[-1] == str(group["reason"])


def test_render_coverage_fails_closed_when_a_lesson_is_unaccounted_for(emitted):
    """A report that silently loses a lesson must not be renderable."""
    _, result = emitted
    result.stats["lessonsListed"] = int(result.stats["lessonsListed"]) + 1
    with pytest.raises(MalformedPayload):
        render_coverage(result)

