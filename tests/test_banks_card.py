"""UGD-09 regressions: bank emission, index metadata, and gate integrity.

These cover the properties this card is responsible for, using the production
code path rather than hand-written fixtures:

* `build/banks/` exists and is byte-identical to the packaged ZIP members;
* `index.json` carries the metadata the card contract requires (title, revision,
  author, url, sequenced) plus per-source attribution;
* the schema gate still FAILS closed on malformed structured content — the point
  of the fast validator is speed, never leniency;
* the compact block is never emitted empty, so no card renders as a bare
  disclosure list.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile

import pytest

from bugd import DICTIONARY_AUTHOR, DICTIONARY_TITLE, DICTIONARY_URL
from bugd.banks import build_banks, build_index, build_tag_bank, build_term_entry
from bugd.merge import MergedEntry
from bugd.model import Example, GrammarPoint
from bugd.package import build_zip, package_members
from bugd.pipeline import BANKS_DIR_NAME, run_build, write_banks_dir
from bugd.styles import STYLES_CSS
from bugd.validate import validate_zip

SOURCE_LABELS = {"dojg": "DoJG 日本語文法辞典(全集)", "edewakaru": "絵でわかる日本語"}


def _point(**overrides) -> GrammarPoint:
    fields = {
        "source": "dojg",
        "source_id": "p1",
        "expression": "わけではない",
        "reading": "わけではない",
        "meaning": "it does not mean that",
        "structure": "〔普通形〕＋わけではない",
        "jlpt": "N3",
        "explanation": "<p>Denies a conclusion someone might draw.</p>",
        "examples": (
            Example(
                japanese="嫌いなわけではない。",
                english="It's not that I dislike it.",
                highlight=("わけではない",),
            ),
        ),
        "provenance": {"sourceLabel": SOURCE_LABELS["dojg"]},
    }
    fields.update(overrides)
    return GrammarPoint(**fields)


def _corpus_on_disk(tmp_path: pathlib.Path, entries: list[MergedEntry]) -> pathlib.Path:
    from bugd.pipeline import MERGED_CORPUS_NAME, entry_to_json

    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    (merged_dir / MERGED_CORPUS_NAME).write_text(
        json.dumps(
            {
                "sourceLabels": SOURCE_LABELS,
                "entries": [entry_to_json(entry) for entry in entries],
            }
        ),
        encoding="utf-8",
    )
    return merged_dir


# --------------------------------------------------------------- build/banks/


def test_build_emits_banks_dir_byte_identical_to_the_zip(tmp_path):
    entries = [MergedEntry(expression="わけではない", contributions=[_point()])]
    merged_dir = _corpus_on_disk(tmp_path, entries)
    build_dir = tmp_path / "build"

    result = run_build(
        merged_dir=merged_dir, build_dir=build_dir, dist_dir=None, require_entries=True
    )

    banks_dir = pathlib.Path(result["banksDir"])
    assert banks_dir == build_dir / BANKS_DIR_NAME
    assert banks_dir.is_dir()

    with zipfile.ZipFile(result["zipPath"]) as archive:
        names = sorted(archive.namelist())
        assert "term_bank_1.json" in names
        for name in names:
            on_disk = banks_dir / name
            assert on_disk.is_file(), f"{name} missing from build/banks/"
            assert (
                hashlib.sha256(on_disk.read_bytes()).hexdigest()
                == hashlib.sha256(archive.read(name)).hexdigest()
            ), f"{name} differs between build/banks/ and the ZIP"

    on_disk_names = sorted(str(p.relative_to(banks_dir)) for p in banks_dir.rglob("*") if p.is_file())
    assert on_disk_names == names, "build/banks/ must mirror the ZIP exactly"


def test_banks_dir_is_rebuilt_so_a_stale_bank_cannot_linger(tmp_path):
    build_dir = tmp_path / "build"
    stale = build_dir / BANKS_DIR_NAME / "term_bank_9.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")

    write_banks_dir({"index.json": "{}"}, build_dir=build_dir)

    assert not stale.exists(), "a bank dropped from the corpus must not survive a rebuild"
    assert (build_dir / BANKS_DIR_NAME / "index.json").is_file()


# ----------------------------------------------------------------- index.json


def test_index_carries_the_required_card_contract_metadata():
    index = build_index("2026.09.08", source_labels=SOURCE_LABELS)

    assert index["title"] == DICTIONARY_TITLE
    assert index["revision"] == "2026.09.08"
    assert index["author"] == DICTIONARY_AUTHOR
    assert index["url"] == DICTIONARY_URL
    assert index["sequenced"] is True
    assert index["format"] == 3
    # Per-source attribution travels with the archive, not only inside cards.
    for label in SOURCE_LABELS.values():
        assert label in index["attribution"]
    # Local-only by default: no updater fields unless both URLs are supplied.
    assert "isUpdatable" not in index


def test_index_refuses_a_half_configured_updater():
    with pytest.raises(Exception):
        build_index("2026.09.08", index_url="https://example.test/index.json")


# ------------------------------------------------------------- card integrity


def test_a_card_never_renders_as_a_bare_sources_disclosure():
    """A card whose sources say nothing must still say something truthful.

    A card whose entire visible content is a `Sources` disclosure reads as a
    broken entry. The fallback states only what the source actually asserts —
    that it listed the point — and never invents a gloss, a reading, or a level.
    """
    bare = _point(
        meaning=None, structure=None, jlpt=None, explanation=None, examples=(),
        provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]},
    )
    entry = MergedEntry(expression="あいにく", contributions=[bare])

    card = build_term_entry(entry, 1)[5][0]["content"]

    def texts(node, out):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, list):
            for item in node:
                texts(item, out)
        elif isinstance(node, dict):
            texts(node.get("content"), out)
        return out

    def roles(node, found):
        if isinstance(node, list):
            for item in node:
                roles(item, found)
        elif isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                found.update(data.keys())
            for value in node.values():
                roles(value, found)
        return found

    present = roles(card, set())
    assert {"crossref", "listedOnly"} & present, (
        "an entry with no substance must still render a truthful statement, "
        f"got roles {sorted(present)}"
    )

    rendered = " ".join(texts(card, []))
    assert SOURCE_LABELS["edewakaru"] in rendered
    # Nothing may be invented to fill the space.
    for invented in ("N5", "N4", "N3", "N2", "N1"):
        assert invented not in rendered


def test_no_emitted_card_in_the_real_corpus_is_bare():
    """Corpus-wide gate: run the real merged corpus if it has been built.

    A single fixture cannot prove the fallback chain covers every real shape, so
    this scans every emitted card when the corpus is present and skips otherwise
    (a fresh clone has no `data/merged/`).
    """
    from bugd.pipeline import MERGED_CORPUS_NAME, entry_from_json

    corpus_path = pathlib.Path("data/merged") / MERGED_CORPUS_NAME
    if not corpus_path.is_file():
        pytest.skip("no merged corpus on disk")

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    entries = [entry_from_json(item) for item in corpus["entries"]]

    def roles(node, found):
        if isinstance(node, list):
            for item in node:
                roles(item, found)
        elif isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                found.update(data.keys())
            for value in node.values():
                roles(value, found)
        return found

    bare = []
    for position, entry in enumerate(entries, start=1):
        card = build_term_entry(entry, position)[5][0]["content"]
        compact_empty = not card["content"][0].get("content")
        present = roles(card, set())
        substantive = bool(
            {"crossref", "listedOnly", "sourceBlock", "prose", "examples", "patterns"} & present
        )
        if compact_empty and not substantive:
            bare.append(entry.expression)

    assert not bare, f"{len(bare)} cards would render as a bare Sources disclosure: {bare[:10]}"


def test_term_entries_are_one_canonical_structured_surface():
    entry = MergedEntry(expression="わけではない", contributions=[_point()])
    expression, reading, deftags, deinflectors, score, glossary, sequence, termtags = (
        build_term_entry(entry, 7)
    )

    assert expression == "わけではない"
    # reading == expression is a redundant furigana pair in Yomitan.
    assert reading == ""
    assert sequence == 7
    assert len(glossary) == 1, "one card per grammar point, not competing glossaries"
    assert glossary[0]["type"] == "structured-content"


# -------------------------------------------------------------- gate integrity


def _zip_with_bank(tmp_path: pathlib.Path, bank: list, name: str = "malformed.zip") -> pathlib.Path:
    members = package_members(
        index=build_index("2026.09.08", source_labels=SOURCE_LABELS),
        banks={"term_bank_1.json": bank},
        tag_bank=build_tag_bank(SOURCE_LABELS),
        styles_css=STYLES_CSS,
    )
    path = tmp_path / name
    path.write_bytes(build_zip(members))
    return path


def test_gate_still_rejects_a_tag_outside_yomitans_allowlist(tmp_path):
    """The fast validator must be no more permissive than the slow one.

    `p` is NOT in Yomitan's structured-content allowlist even though it is
    obvious HTML, so it is the sharpest available probe that the accelerated gate
    still enforces the real pinned schema.
    """
    entry = build_term_entry(
        MergedEntry(expression="わけではない", contributions=[_point()]), 1
    )
    entry[5][0]["content"]["content"].append({"tag": "p", "content": "not allowed"})

    failures = validate_zip(_zip_with_bank(tmp_path, [entry]), require_entries=True)

    assert failures, "a nested `p` tag must fail the pinned term-bank schema"
    assert any("term_bank_1.json" in failure for failure in failures)


@pytest.mark.parametrize(
    "bank, reason",
    [
        ([["surface", "", "", "", 0, ["gloss"], "not-an-int", ""]], "sequence must be integer"),
        ([["surface", ""]], "entry is too short"),
        ([["surface", "", "", "", 0, "plain-not-array", 1, ""]], "glossary must be an array"),
        ({"nope": True}, "bank must be an array"),
    ],
)
def test_gate_rejects_structurally_invalid_banks(tmp_path, bank, reason):
    failures = validate_zip(_zip_with_bank(tmp_path, bank), require_entries=True)
    assert failures, f"expected the gate to reject: {reason}"


def test_banks_shard_contiguously_with_positive_sequences():
    entries = [
        MergedEntry(expression=f"点{index}", contributions=[_point(source_id=f"p{index}")])
        for index in range(5)
    ]
    banks = build_banks(entries)

    assert sorted(banks) == ["term_bank_1.json"]
    sequences = [entry[6] for entry in banks["term_bank_1.json"]]
    assert sequences == [1, 2, 3, 4, 5]
