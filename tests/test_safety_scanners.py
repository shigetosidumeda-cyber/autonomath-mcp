"""Tests for ``jpintel_mcp.safety_scanners`` + ``scripts/safety/scan_outputs.py``.

Coverage:

* No-hit detection (regression scanner finds bare no_hit packets).
* No-hit detection (regression scanner accepts properly-gapped no_hit packets).
* Forbidden English wording detection.
* Forbidden Japanese wording detection.
* Allowed/forbidden boundary (whitelist + ``該当なし`` semantics).
* S3 + local file CLI support.

The scanners are pure-Python and file-based, so we do not need a TestClient
or DB fixture. We use ``tmp_path`` + ``monkeypatch`` for filesystem and S3
adapters.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Make the CLI module importable directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from safety import scan_outputs as cli  # noqa: E402

from jpintel_mcp.safety_scanners import (  # noqa: E402
    ALLOWED_WORDING,
    FORBIDDEN_JA,
    FORBIDDEN_WORDING,
    NO_HIT_NOT_ABSENCE_CODE,
    scan_forbidden_claims,
    scan_forbidden_claims_in_file,
    scan_no_hit_regressions,
    scan_no_hit_regressions_in_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _gap(code: str = NO_HIT_NOT_ABSENCE_CODE) -> dict[str, Any]:
    return {
        "gap_id": code,
        "gap_type": code,
        "gap_status": "known_gap",
        "explanation": "scoped observation only",
    }


def _no_hit_packet(*, with_gap: bool, packet_id: str = "p-001") -> dict[str, Any]:
    packet: dict[str, Any] = {
        "packet_id": packet_id,
        "result": "no_hit",
        "checked_scope": "S/A tier, 2026-05-15",
        "hits": [],
        "known_gaps": [],
    }
    if with_gap:
        packet["known_gaps"].append(_gap())
    return packet


def _envelope(packets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "header": {
            "schema_version": "jpcir.p0.v1",
            "object_id": "env-1",
            "object_type": "search_response",
            "created_at": "2026-05-16T00:00:00Z",
        },
        "packets": packets,
    }


# ---------------------------------------------------------------------------
# 1. No-hit regression scanner
# ---------------------------------------------------------------------------


def test_no_hit_with_gap_is_safe() -> None:
    envelope = _envelope([_no_hit_packet(with_gap=True)])
    assert scan_no_hit_regressions(envelope) == []


def test_no_hit_without_gap_is_flagged() -> None:
    envelope = _envelope([_no_hit_packet(with_gap=False)])
    violations = scan_no_hit_regressions(envelope)
    assert len(violations) == 1
    v = violations[0]
    assert v.scanner == "no_hit_regression"
    assert v.code == "missing_no_hit_not_absence_gap"
    assert v.packet_id == "p-001"
    assert v.path.startswith("$.packets[0]")


def test_no_hit_multiple_packets_isolated() -> None:
    envelope = _envelope(
        [
            _no_hit_packet(with_gap=True, packet_id="ok"),
            _no_hit_packet(with_gap=False, packet_id="bad-1"),
            _no_hit_packet(with_gap=False, packet_id="bad-2"),
        ]
    )
    violations = scan_no_hit_regressions(envelope)
    assert {v.packet_id for v in violations} == {"bad-1", "bad-2"}


def test_no_hit_status_field_triggers_detection() -> None:
    packet = {
        "packet_id": "s1",
        "status": "no_hit",
        "known_gaps": [],
    }
    assert len(scan_no_hit_regressions(packet)) == 1


def test_no_hit_boolean_field_triggers_detection() -> None:
    packet = {"object_id": "b1", "no_hit": True}
    violations = scan_no_hit_regressions(packet)
    assert len(violations) == 1
    assert violations[0].packet_id == "b1"


def test_no_hit_observed_alias() -> None:
    packet = {"packet_id": "o1", "no_hit_observed": True}
    assert len(scan_no_hit_regressions(packet)) == 1


def test_no_hit_empty_hits_with_scope() -> None:
    packet = {"packet_id": "h1", "hits": [], "checked_scope": "all"}
    assert len(scan_no_hit_regressions(packet)) == 1


def test_no_hit_empty_hits_without_scope_is_not_no_hit() -> None:
    # Just an empty hits array without a checked_scope is not a no-hit
    # observation envelope — could be a not-yet-populated container.
    packet = {"packet_id": "x", "hits": []}
    assert scan_no_hit_regressions(packet) == []


def test_no_hit_self_declared_lease_shape() -> None:
    # NoHitLease shape carries no_hit_semantics on the same dict.
    lease = {
        "lease_id": "lease-1",
        "checked_scope": "all",
        "result": "no_hit",
        "no_hit_semantics": NO_HIT_NOT_ABSENCE_CODE,
    }
    assert scan_no_hit_regressions(lease) == []


def test_no_hit_gap_code_field_variants_all_accepted() -> None:
    for field in ("code", "gap_id", "gap_type", "no_hit_semantics"):
        packet = {
            "packet_id": f"f-{field}",
            "result": "no_hit",
            "known_gaps": [{field: NO_HIT_NOT_ABSENCE_CODE}],
        }
        assert scan_no_hit_regressions(packet) == [], f"field={field}"


def test_no_hit_gap_alternate_container_names() -> None:
    for container in ("known_gaps", "gaps", "gap_coverage", "gap_coverage_entries"):
        packet = {
            "packet_id": f"c-{container}",
            "result": "no_hit",
            container: [{"code": NO_HIT_NOT_ABSENCE_CODE}],
        }
        assert scan_no_hit_regressions(packet) == [], f"container={container}"


def test_no_hit_wrong_gap_code_still_flagged() -> None:
    packet = {
        "packet_id": "w",
        "result": "no_hit",
        "known_gaps": [{"code": "other_gap_kind"}],
    }
    assert len(scan_no_hit_regressions(packet)) == 1


def test_no_hit_file_loader_round_trips(tmp_path: Path) -> None:
    env = _envelope([_no_hit_packet(with_gap=False, packet_id="f-1")])
    p = tmp_path / "envelope.json"
    p.write_text(json.dumps(env), encoding="utf-8")
    violations = scan_no_hit_regressions_in_file(p)
    assert len(violations) == 1
    assert violations[0].source == str(p)


def test_no_hit_file_loader_handles_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    violations = scan_no_hit_regressions_in_file(p)
    assert len(violations) == 1
    assert violations[0].code == "unparseable_json"


def test_no_hit_packet_id_resolution_falls_back_to_object_id() -> None:
    packet = {"object_id": "obj-9", "result": "no_hit"}
    violations = scan_no_hit_regressions(packet)
    assert violations[0].packet_id == "obj-9"


def test_no_hit_packet_id_unknown_when_no_identifier() -> None:
    packet = {"result": "no_hit"}
    violations = scan_no_hit_regressions(packet)
    assert violations[0].packet_id == "<unknown>"


# ---------------------------------------------------------------------------
# 2. Forbidden-claim scanner — English
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", list(FORBIDDEN_WORDING))
def test_each_english_forbidden_word_is_flagged(phrase: str) -> None:
    envelope = {
        "packet_id": "p",
        "summary": f"The applicant is {phrase} for this program.",
    }
    violations = scan_forbidden_claims(envelope)
    codes = {v.code for v in violations}
    assert "forbidden_english_wording" in codes


def test_english_case_insensitive() -> None:
    envelope = {"packet_id": "p", "summary": "This is SAFE to apply."}
    violations = scan_forbidden_claims(envelope)
    assert any("safe" in v.detail for v in violations)


def test_english_inside_long_phrase_flagged() -> None:
    envelope = {
        "packet_id": "p",
        "narrative": "Per our analysis, no violation was detected on the corp.",
    }
    violations = scan_forbidden_claims(envelope)
    assert any("no violation" in v.detail for v in violations)


# ---------------------------------------------------------------------------
# 3. Forbidden-claim scanner — Japanese
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", list(FORBIDDEN_JA))
def test_each_japanese_forbidden_phrase_is_flagged(phrase: str) -> None:
    envelope = {"packet_id": "p", "body": f"判定: {phrase}"}
    violations = scan_forbidden_claims(envelope)
    assert any(phrase in v.detail for v in violations)


def test_japanese_gainai_alone_is_not_forbidden() -> None:
    # 該当なし alone is OK — it's the canonical no_hit rendering.
    envelope = {"packet_id": "p", "summary": "該当なし"}
    assert scan_forbidden_claims(envelope) == []


def test_japanese_problem_phrase_flagged_even_with_no_hit_context() -> None:
    envelope = {
        "packet_id": "p",
        "summary": "該当なし、問題ありません。",
    }
    violations = scan_forbidden_claims(envelope)
    assert any("問題ありません" in v.detail for v in violations)


# ---------------------------------------------------------------------------
# 4. Allowed/forbidden boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("allowed", list(ALLOWED_WORDING))
def test_each_allowed_phrase_is_never_flagged(allowed: str) -> None:
    envelope = {"packet_id": "p", "summary": f"key: {allowed}"}
    violations = scan_forbidden_claims(envelope)
    assert violations == [], f"allowed={allowed!r} produced {violations}"


def test_allowed_phrase_blocks_substring_match() -> None:
    # 'not_enough_public_evidence' contains the bare substring 'not '
    # but should NOT trigger 'no issue' / 'no violation' detection because
    # the whitelist masks the phrase before substring scanning.
    envelope = {
        "packet_id": "p",
        "summary": "Coverage: not_enough_public_evidence on S tier.",
    }
    assert scan_forbidden_claims(envelope) == []


def test_no_hit_not_absence_marker_is_allowed_in_text() -> None:
    envelope = {
        "packet_id": "p",
        "rationale": "Semantics: no_hit_not_absence (scoped observation only).",
    }
    assert scan_forbidden_claims(envelope) == []


def test_professional_review_caveat_is_allowed_phrase() -> None:
    envelope = {
        "packet_id": "p",
        "note": "professional_review_caveat applies; consult 税理士.",
    }
    assert scan_forbidden_claims(envelope) == []


# ---------------------------------------------------------------------------
# 5. CLI + S3 + local file support
# ---------------------------------------------------------------------------


def test_cli_clean_directory_returns_zero(tmp_path: Path) -> None:
    p = tmp_path / "clean.json"
    p.write_text(
        json.dumps(_envelope([_no_hit_packet(with_gap=True, packet_id="ok")])),
        encoding="utf-8",
    )
    out = io.StringIO()
    rc = cli.run([str(tmp_path)], stream=out)
    assert rc == 0
    report = json.loads(out.getvalue())
    assert report["summary"]["violation_count"] == 0
    assert report["summary"]["files_scanned"] == 1


def test_cli_dirty_file_returns_nonzero(tmp_path: Path) -> None:
    p = tmp_path / "dirty.json"
    envelope = _envelope([_no_hit_packet(with_gap=False, packet_id="bad")])
    envelope["packets"][0]["summary"] = "Applicant is eligible and safe."
    p.write_text(json.dumps(envelope), encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(p)], stream=out)
    assert rc == 1
    report = json.loads(out.getvalue())
    scanners = {v["scanner"] for v in report["violations"]}
    assert "no_hit_regression" in scanners
    assert "forbidden_claim" in scanners


def test_cli_missing_path_returns_violation(tmp_path: Path) -> None:
    out = io.StringIO()
    rc = cli.run([str(tmp_path / "nonexistent.json")], stream=out)
    assert rc == 1
    report = json.loads(out.getvalue())
    assert report["summary"]["violation_count"] == 1
    assert report["violations"][0]["code"] == "missing_path"


def test_cli_argparse_rejects_zero_args() -> None:
    with pytest.raises(SystemExit):
        cli._parse_argv([])


def test_cli_recursive_walk_finds_nested_json(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "envelope.json").write_text(
        json.dumps(_envelope([_no_hit_packet(with_gap=True)])),
        encoding="utf-8",
    )
    (tmp_path / "ignored.txt").write_text("noise", encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(tmp_path)], stream=out)
    assert rc == 0
    report = json.loads(out.getvalue())
    assert report["summary"]["files_scanned"] == 1


def test_cli_handles_unparseable_file(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(p)], stream=out)
    assert rc == 1
    report = json.loads(out.getvalue())
    assert report["summary"]["violation_count"] == 1
    assert report["violations"][0]["code"] == "unparseable_json"


def test_forbidden_claim_file_loader_handles_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    violations = scan_forbidden_claims_in_file(p)
    assert len(violations) == 1
    assert violations[0].code == "unparseable_json"


def test_cli_s3_uri_handled_via_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate the S3 dispatch path uses the prefix walker.

    We don't depend on a live S3 service: we monkey-patch the iterator that
    yields ``(uri, envelope)`` to confirm dispatch happens and the scanner
    aggregates violations across the yielded objects.
    """

    def fake_iter(uri: str) -> Any:
        yield (
            "s3://demo-bucket/key-a.json",
            _envelope([_no_hit_packet(with_gap=True, packet_id="a")]),
        )
        yield (
            "s3://demo-bucket/key-b.json",
            _envelope([_no_hit_packet(with_gap=False, packet_id="b")]),
        )

    monkeypatch.setattr(cli, "_iter_s3_objects", fake_iter)
    out = io.StringIO()
    rc = cli.run(["s3://demo-bucket/"], stream=out)
    assert rc == 1
    report = json.loads(out.getvalue())
    assert report["summary"]["files_scanned"] == 2
    bad_packets = {v["packet_id"] for v in report["violations"]}
    assert "b" in bad_packets
    assert "a" not in bad_packets


def test_s3_uri_split_helpers() -> None:
    assert cli._looks_like_s3("s3://b/key")
    assert not cli._looks_like_s3("/tmp/x")
    assert cli._split_s3_uri("s3://b/key/inner") == ("b", "key/inner")
    assert cli._split_s3_uri("s3://onlybucket") == ("onlybucket", "")


def test_violation_to_dict_round_trip() -> None:
    envelope = _envelope([_no_hit_packet(with_gap=False)])
    violations = scan_no_hit_regressions(envelope, source="/tmp/x.json")
    d = violations[0].to_dict()
    assert d["scanner"] == "no_hit_regression"
    assert d["code"] == "missing_no_hit_not_absence_gap"
    assert d["source"] == "/tmp/x.json"


def test_envelope_with_only_safe_no_hits_scans_clean() -> None:
    env = _envelope(
        [
            _no_hit_packet(with_gap=True, packet_id=f"safe-{idx}")
            for idx in range(5)
        ]
    )
    assert scan_no_hit_regressions(env) == []
    assert scan_forbidden_claims(env) == []


def test_main_entrypoint_no_targets_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``run([])`` returns 2 (argparse rejects this — bypass for the branch).
    rc = cli.run([])
    assert rc == 2


def test_cli_combined_summary_reports_targets(tmp_path: Path) -> None:
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_envelope([_no_hit_packet(with_gap=True)])), encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(p)], stream=out)
    assert rc == 0
    report = json.loads(out.getvalue())
    assert report["summary"]["targets"] == [str(p)]


def test_violation_omits_source_when_none() -> None:
    envelope = _envelope([_no_hit_packet(with_gap=False)])
    violations = scan_no_hit_regressions(envelope)
    d = violations[0].to_dict()
    assert "source" not in d


def test_walker_descends_into_nested_lists() -> None:
    # Nested list of dicts inside a section.
    envelope = {
        "packet_id": "outer",
        "sections": [
            {"section_id": "s1", "items": [{"result": "no_hit"}]},
            {"section_id": "s2", "items": [{"result": "no_hit"}]},
        ],
    }
    violations = scan_no_hit_regressions(envelope)
    assert len(violations) == 2


def test_walker_descends_into_nested_text_for_forbidden() -> None:
    envelope = {
        "packet_id": "outer",
        "sections": [
            {"section_id": "s1", "body": "All checks are eligible."},
            {"section_id": "s2", "body": "問題ありません。"},
        ],
    }
    violations = scan_forbidden_claims(envelope)
    detail_blob = " | ".join(v.detail for v in violations)
    assert "eligible" in detail_blob
    assert "問題ありません" in detail_blob


def test_packet_id_resolves_to_nearest_dict_for_forbidden() -> None:
    envelope = {
        "packets": [
            {
                "packet_id": "near",
                "sections": [
                    {"section_id": "s1", "body": "This is safe."},
                ],
            }
        ]
    }
    violations = scan_forbidden_claims(envelope)
    assert any(v.packet_id == "near" for v in violations)


def test_forbidden_phrase_substring_matching_is_explicit() -> None:
    # By design, substring matching is case-insensitive but NOT
    # word-bounded — ``eligible`` matches inside ``...is eligible for X``.
    # We document the behavior so future regressions do not silently
    # change it. ``Eligibility`` (which does NOT contain ``eligible``)
    # remains a clean string — the substring rule is strict on letters.
    envelope = {"packet_id": "p", "summary": "Applicant is eligible for X."}
    violations = scan_forbidden_claims(envelope)
    assert any(v.code == "forbidden_english_wording" for v in violations)


def test_identifier_field_does_not_trigger_english_match() -> None:
    # ``packet_id="safe-001"`` must not match the forbidden ``safe`` phrase
    # because identifier fields are not prose. (Japanese in an identifier
    # would still be flagged — see test_japanese_in_identifier_flagged.)
    envelope = {"packet_id": "safe-001", "object_id": "eligible-x"}
    assert scan_forbidden_claims(envelope) == []


def test_japanese_in_identifier_still_flagged() -> None:
    # Japanese in an identifier field is itself a defect, so we keep
    # scanning Japanese forbidden phrases on identifier fields.
    envelope = {"packet_id": "問題ありません-1"}
    violations = scan_forbidden_claims(envelope)
    assert any(v.code == "forbidden_japanese_wording" for v in violations)


def test_text_field_set_lookup() -> None:
    # Sanity-check the text-field set used by the docstring contract — we
    # don't filter by it (we scan every leaf) but it documents intent.
    from jpintel_mcp.safety_scanners.forbidden_claim import _TEXT_FIELD_NAMES

    assert "summary" in _TEXT_FIELD_NAMES
    assert "body" in _TEXT_FIELD_NAMES
    assert "rationale" in _TEXT_FIELD_NAMES


# ---------------------------------------------------------------------------
# 6. End-to-end smoke
# ---------------------------------------------------------------------------


def test_end_to_end_clean_envelope_zero_violations(tmp_path: Path) -> None:
    envelope = {
        "header": {
            "schema_version": "jpcir.p0.v1",
            "object_id": "env-final",
            "object_type": "search_response",
            "created_at": "2026-05-16T00:00:00Z",
        },
        "packets": [
            {
                "packet_id": "p1",
                "result": "no_hit",
                "checked_scope": "S tier × 製造業",
                "known_gaps": [_gap()],
                "summary": (
                    "Outcome: candidate_priority unscored; "
                    "no_hit_not_absence; professional_review_caveat applies."
                ),
            }
        ],
    }
    p = tmp_path / "final.json"
    p.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(p)], stream=out)
    assert rc == 0
    report = json.loads(out.getvalue())
    assert report["summary"]["violation_count"] == 0


def test_end_to_end_dirty_envelope_reports_both_scanners(tmp_path: Path) -> None:
    envelope = {
        "packets": [
            {
                "packet_id": "bad",
                "result": "no_hit",
                "known_gaps": [],
                "summary": "Applicant is eligible. 問題ありません。",
            }
        ]
    }
    p = tmp_path / "dirty.json"
    p.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    out = io.StringIO()
    rc = cli.run([str(p)], stream=out)
    assert rc == 1
    report = json.loads(out.getvalue())
    scanners = {v["scanner"] for v in report["violations"]}
    codes = {v["code"] for v in report["violations"]}
    assert scanners == {"no_hit_regression", "forbidden_claim"}
    assert "missing_no_hit_not_absence_gap" in codes
    assert "forbidden_english_wording" in codes
    assert "forbidden_japanese_wording" in codes


def test_cwd_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scanner must work regardless of cwd."""
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"result": "no_hit"}), encoding="utf-8")
    monkeypatch.chdir(os.path.expanduser("~"))
    violations = scan_no_hit_regressions_in_file(p)
    assert len(violations) == 1
