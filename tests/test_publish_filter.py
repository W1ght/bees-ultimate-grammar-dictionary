"""The publish-time redistribution filter (`bugd.publish_filter`).

Two layers, because they fail differently:

* `is_redistributable` is called DIRECTLY with synthetic records. Every guard in
  it is unreachable through the real corpus — all 7,896 extracted records carry a
  provenance dict with a boolean `redistributable` — so a mutation deleting the
  missing-provenance or missing-key branch is a no-op against real data and
  survives any corpus-driven test. Only direct calls can kill it.
* `filter_extracted` is exercised over real filtered artifacts written to a fresh
  tmp dir, so the on-disk contract (what is written, what is refused, what the
  manifest reports) is asserted against bytes rather than a return value.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.jsonio import MalformedPayload
from bugd.publish_filter import (
    UNVERIFIED_PERMISSION_BASES,
    EmptyPublicCorpus,
    filter_extracted,
    is_redistributable,
)


def _record(**provenance: object) -> dict[str, object]:
    return {"source_id": "x", "expression": "テスト", "provenance": dict(provenance)}


# ---------------------------------------------------------------------------
# is_redistributable — synthetic inputs, because the corpus cannot reach these
# ---------------------------------------------------------------------------


def test_a_verified_grant_is_admitted():
    assert is_redistributable(_record(redistributable=True)) is True


def test_a_declared_refusal_is_excluded():
    assert is_redistributable(_record(redistributable=False)) is False


def test_a_missing_flag_is_not_a_grant():
    """Absent is not permitted.

    `bunpro` and `imabi` carry no licence block in their SOURCE.lock at all, so
    a "not False" predicate would admit them on silence. No record in the real
    corpus omits the key, so this branch is only reachable by calling directly.
    """
    assert is_redistributable(_record(licenseTier="A")) is False


def test_a_missing_provenance_block_is_not_a_grant():
    assert is_redistributable({"source_id": "x"}) is False
    assert is_redistributable({"source_id": "x", "provenance": None}) is False
    assert is_redistributable({"source_id": "x", "provenance": "CC BY 4.0"}) is False


@pytest.mark.parametrize("truthy", [1, "true", "yes", ["CC-BY-4.0"], {"ok": 1}])
def test_a_truthy_non_boolean_is_not_a_grant(truthy):
    """Identity against True, not truthiness.

    A string `"false"` is truthy, so a `if flag:` test would publish a source
    that explicitly refused. Parametrised over the shapes a hand-edited or
    machine-generated lock could plausibly produce.
    """
    assert is_redistributable(_record(redistributable=truthy)) is False


def test_a_merely_reported_permission_is_not_a_licence():
    """UGD-15's second class: publishable only on reported permission.

    IMABI's grant is a user report — `imabi.org/terms/`, `/license/` and
    `/copyright/` all 404 — and the audit's instruction is to obtain the approval
    in writing before relying on it. So the flag alone must not admit it.
    """
    assert (
        is_redistributable(
            _record(redistributable=True, permissionBasis="user-reported")
        )
        is False
    )
    assert "user-reported" in UNVERIFIED_PERMISSION_BASES


def test_a_documented_basis_still_passes():
    """The permission-basis check must not reject every stated basis.

    Otherwise recording provenance more thoroughly would silently shrink the
    public corpus, which is the opposite of the intent.
    """
    assert (
        is_redistributable(
            _record(redistributable=True, permissionBasis="declared-by-source")
        )
        is True
    )


# ---------------------------------------------------------------------------
# filter_extracted — on-disk behaviour
# ---------------------------------------------------------------------------


def _artifact(
    directory: pathlib.Path, source: str, records: list[dict[str, object]]
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{source}.json").write_text(
        json.dumps({"source": source, "label": source.upper(), "points": records}),
        encoding="utf-8",
    )


def test_it_writes_only_the_admitted_sources(tmp_path):
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    _artifact(extracted, "granted", [_record(redistributable=True) for _ in range(3)])
    _artifact(extracted, "refused", [_record(redistributable=False) for _ in range(5)])

    manifest = filter_extracted(extracted_dir=extracted, public_dir=public)

    assert sorted(p.name for p in public.glob("*.json")) == ["granted.json"]
    assert manifest["admittedSources"] == {"granted": 3}
    assert manifest["excludedSources"] == {"refused": 5}
    assert manifest["consideredRecords"] == 8
    assert manifest["admittedRecords"] == 3
    assert manifest["excludedRecords"] == 5


def test_a_fully_excluded_source_gets_no_artifact_at_all(tmp_path):
    """No empty artifact for an excluded source.

    An artifact declaring a source with zero points would still put that
    source's label into the packaged tag bank and the index attribution while
    contributing no content — a false attribution claim in a published archive.
    """
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    _artifact(extracted, "granted", [_record(redistributable=True)])
    _artifact(extracted, "refused", [_record(redistributable=False)])

    filter_extracted(extracted_dir=extracted, public_dir=public)

    assert not (public / "refused.json").exists()


def test_it_preserves_every_other_field_of_the_artifact(tmp_path):
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    directory = extracted
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "granted.json").write_text(
        json.dumps(
            {
                "source": "granted",
                "label": "Granted Source",
                "aiGeneratedSource": False,
                "consumed": {"a.json": "deadbeef"},
                "stats": {"points": 1},
                "points": [_record(redistributable=True)],
            }
        ),
        encoding="utf-8",
    )

    filter_extracted(extracted_dir=extracted, public_dir=public)

    out = json.loads((public / "granted.json").read_text(encoding="utf-8"))
    assert out["label"] == "Granted Source"
    assert out["consumed"] == {"a.json": "deadbeef"}
    assert out["stats"] == {"points": 1}
    assert out["aiGeneratedSource"] is False


def test_it_fails_closed_when_nothing_is_redistributable(tmp_path):
    """An empty public corpus is the worst outcome, so it raises.

    A zero-entry archive passes schema validation and would publish
    successfully, shipping nothing while reporting success.
    """
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    _artifact(extracted, "refused", [_record(redistributable=False) for _ in range(4)])

    with pytest.raises(EmptyPublicCorpus) as caught:
        filter_extracted(extracted_dir=extracted, public_dir=public)
    assert caught.value.considered == 4
    assert not list(public.glob("*.json"))


def test_a_split_grant_inside_one_source_fails_closed(tmp_path):
    """A per-source grant must be uniform.

    Both cleared sources are wholesale CC BY 4.0, so a source where only some
    rows claim redistribution means the extractor stamps provenance
    inconsistently. Shipping the subset would launder that defect.
    """
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    _artifact(
        extracted,
        "mixed",
        [_record(redistributable=True), _record(redistributable=False)],
    )

    with pytest.raises(MalformedPayload, match="uniform"):
        filter_extracted(extracted_dir=extracted, public_dir=public)


def test_it_clears_a_stale_public_corpus_first(tmp_path):
    """A previous run's artifact must not survive into a new filter result.

    Otherwise a source that loses its grant keeps shipping from a leftover file,
    and `make public` would package a source the current filter excludes.
    """
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    public.mkdir(parents=True)
    (public / "stale.json").write_text(
        json.dumps({"source": "stale", "points": [_record(redistributable=True)]}),
        encoding="utf-8",
    )
    _artifact(extracted, "granted", [_record(redistributable=True)])

    filter_extracted(extracted_dir=extracted, public_dir=public)

    assert sorted(p.name for p in public.glob("*.json")) == ["granted.json"]


def test_a_malformed_artifact_raises_rather_than_being_skipped(tmp_path):
    extracted = tmp_path / "extracted"
    public = tmp_path / "public"
    extracted.mkdir(parents=True)
    (extracted / "broken.json").write_text(json.dumps({"points": []}), encoding="utf-8")

    with pytest.raises(MalformedPayload):
        filter_extracted(extracted_dir=extracted, public_dir=public)


def test_a_missing_extracted_corpus_raises(tmp_path):
    with pytest.raises(MalformedPayload):
        filter_extracted(
            extracted_dir=tmp_path / "nope", public_dir=tmp_path / "public"
        )
