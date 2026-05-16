"""Tests for ``scripts.aws_credit_ops.validate_run_artifacts``.

Coverage targets (~20 tests):

1. Happy-path: every invariant PASS on the valid fixture.
2. Broken fixture: every invariant FAIL.
3. Each individual invariant -- the broken fixture's specific failure must
   land under the right invariant key, not collapse onto another one.
4. CLI exit codes: 0 / 1 / 2 plus ``--json`` mode round-trip.
5. ``LocalDirSource`` round-trip + ``S3PrefixSource`` lazy boto3 import.
6. URI parser accepts ``s3://bucket/prefix`` and rejects malformed.

Wave 50 Stream supplement (2026-05-16). ``[lane:solo]``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "aws_credit_ops"
SRC_DIR = REPO_ROOT / "src"

# Add both paths so we can import the script under test plus the
# ``jpintel_mcp.safety_scanners`` package it depends on.
for entry in (str(SCRIPTS_DIR), str(SRC_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


_SPEC = importlib.util.spec_from_file_location(
    "validate_run_artifacts",
    SCRIPTS_DIR / "validate_run_artifacts.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
vra = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_run_artifacts"] = vra
_SPEC.loader.exec_module(vra)


FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "validate_run_artifacts"
VALID_DIR = FIXTURE_ROOT / "valid_run"
BROKEN_DIR = FIXTURE_ROOT / "broken_run"
SCHEMAS_DIR = REPO_ROOT / "schemas" / "jpcir"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_source(path: Path) -> Any:
    return vra.LocalDirSource(path)


def _run_validate(path: Path, **kwargs: Any) -> Any:
    schemas = vra.load_schemas(SCHEMAS_DIR)
    return vra.validate_run_artifacts(
        source=_build_source(path),
        schemas=schemas,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1) Happy path
# ---------------------------------------------------------------------------


def test_valid_fixture_passes_all_eight_invariants() -> None:
    report = _run_validate(VALID_DIR)
    assert report.all_pass, report.to_dict()
    assert set(report.invariants.keys()) == set(vra.INVARIANT_IDS)
    for inv in vra.INVARIANT_IDS:
        assert report.invariants[inv] is True, inv
    assert report.violations == []


def test_invariant_id_list_is_eight() -> None:
    assert len(vra.INVARIANT_IDS) == 8
    assert "schema_conformance" in vra.INVARIANT_IDS
    assert "forbidden_claim_absence" in vra.INVARIANT_IDS


# ---------------------------------------------------------------------------
# 2) Broken fixture sanity
# ---------------------------------------------------------------------------


def test_broken_fixture_fails_overall() -> None:
    report = _run_validate(BROKEN_DIR)
    assert not report.all_pass
    assert len(report.violations) > 0


def test_broken_fixture_fails_every_invariant() -> None:
    """The broken fixture intentionally violates every one of the 8."""
    report = _run_validate(BROKEN_DIR)
    for inv in vra.INVARIANT_IDS:
        assert report.invariants[inv] is False, f"{inv} should be FAIL"


# ---------------------------------------------------------------------------
# 3) Per-invariant coverage
# ---------------------------------------------------------------------------


def test_schema_conformance_violation_present() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {v.code for v in report.violations if v.invariant == "schema_conformance"}
    assert "schema_violation" in codes


def test_sha256_integrity_mismatch_present() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {v.code for v in report.violations if v.invariant == "sha256_integrity"}
    assert "sha256_mismatch" in codes


def test_source_receipt_consistency_dangling(tmp_path: Path) -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {
        v.code
        for v in report.violations
        if v.invariant == "source_receipt_consistency"
    }
    assert "dangling_receipt_id" in codes


def test_known_gap_enum_invalid_code() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {v.code for v in report.violations if v.invariant == "known_gap_enum"}
    assert "invalid_gap_code" in codes


def test_license_boundary_undeclared() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {
        v.code for v in report.violations if v.invariant == "license_boundary_defined"
    }
    assert "license_undeclared" in codes


def test_freshness_detects_old_receipt() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {
        v.code for v in report.violations if v.invariant == "freshness_within_window"
    }
    # Either the >TTL stale receipt or the missing-observed_at row hits the
    # invariant -- both are valid signals.
    assert codes & {"receipt_stale", "missing_observed_at"}


def test_no_hit_not_absence_detected() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {v.code for v in report.violations if v.invariant == "no_hit_not_absence"}
    assert "missing_no_hit_not_absence_gap" in codes


def test_forbidden_claim_english() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {
        v.code for v in report.violations if v.invariant == "forbidden_claim_absence"
    }
    assert "forbidden_english_wording" in codes


def test_forbidden_claim_japanese() -> None:
    report = _run_validate(BROKEN_DIR)
    codes = {
        v.code for v in report.violations if v.invariant == "forbidden_claim_absence"
    }
    assert "forbidden_japanese_wording" in codes


# ---------------------------------------------------------------------------
# 4) Helpers
# ---------------------------------------------------------------------------


def test_load_schemas_indexed_by_name() -> None:
    schemas = vra.load_schemas(SCHEMAS_DIR)
    # Every schema file under schemas/jpcir/ should be loaded.
    assert "source_receipt" in schemas
    assert "claim_ref" in schemas
    assert "known_gap" in schemas
    assert "jpcir_header" in schemas
    assert len(schemas) >= 20


def test_load_schemas_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        vra.load_schemas(tmp_path / "does-not-exist")


def test_parse_jsonl_skips_blanks_and_invalid() -> None:
    payload = b'{"a": 1}\n\n   \nnot json\n{"b": 2}\n'
    rows = vra.parse_jsonl(payload)
    assert rows == [{"a": 1}, {"b": 2}]


def test_parse_iso8601_handles_z_suffix() -> None:
    parsed = vra.parse_iso8601("2026-05-15T00:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert vra.parse_iso8601("not a date") is None
    assert vra.parse_iso8601("") is None


def test_hash_payload_matches_hashlib() -> None:
    data = b"jpcite-validator-test-blob"
    assert vra.hash_payload(data) == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 5) Source adapters
# ---------------------------------------------------------------------------


def test_local_dir_source_round_trips(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text('{"k": "v"}', encoding="utf-8")
    src = vra.LocalDirSource(tmp_path)
    assert src.read("x.json") == b'{"k": "v"}'
    assert src.read("missing.json") is None
    assert "x.json" in list(src.list_relative_names())
    assert tmp_path.as_posix() in src.display_prefix.replace("\\", "/")


def test_build_source_local_path() -> None:
    src = vra.build_source(str(VALID_DIR))
    assert isinstance(src, vra.LocalDirSource)


def test_build_source_s3_uri_parses() -> None:
    src = vra.build_source("s3://my-bucket/some/prefix")
    assert isinstance(src, vra.S3PrefixSource)
    assert src.display_prefix == "s3://my-bucket/some/prefix/"


def test_build_source_s3_uri_malformed() -> None:
    with pytest.raises(ValueError, match="Malformed s3 URI"):
        vra.build_source("s3://only-bucket-no-key")


# ---------------------------------------------------------------------------
# 6) CLI surface
# ---------------------------------------------------------------------------


def test_cli_exit_zero_on_valid(capsys: pytest.CaptureFixture[str]) -> None:
    code = vra.main([str(VALID_DIR)])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS (exit 0)" in out


def test_cli_exit_one_on_broken(capsys: pytest.CaptureFixture[str]) -> None:
    code = vra.main([str(BROKEN_DIR)])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL (exit 1)" in out


def test_cli_json_mode_returns_machine_readable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = vra.main([str(VALID_DIR), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    parsed = json.loads(out)
    assert parsed["all_pass"] is True
    assert parsed["invariants"]["schema_conformance"] is True


def test_cli_exit_two_on_missing_schemas_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = vra.main(
        [
            str(VALID_DIR),
            "--schemas-dir",
            str(tmp_path / "does-not-exist"),
        ]
    )
    assert code == 2


def test_cli_license_map_override(tmp_path: Path) -> None:
    """An external license-map file fills licenses for orphan source families."""
    # Construct a tiny prefix where one family has no receipt-side license
    # but is covered by the sidecar.
    prefix = tmp_path / "lic"
    prefix.mkdir()
    (prefix / "source_receipts.jsonl").write_text(
        json.dumps(
            {
                "receipt_id": "r1",
                "source_family_id": "orphan_fam",
                "source_url": "https://example.com/x",
                "observed_at": "2026-05-15T00:00:00Z",
                "access_method": "html",
                "support_state": "direct",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (prefix / "claim_refs.jsonl").write_text("", encoding="utf-8")
    (prefix / "known_gaps.jsonl").write_text("", encoding="utf-8")
    (prefix / "quarantine.jsonl").write_text("", encoding="utf-8")
    (prefix / "object_manifest.jsonl").write_text("", encoding="utf-8")
    (prefix / "run_manifest.json").write_text(
        json.dumps({"run_started_at": "2026-05-15T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    lic = tmp_path / "license_map.json"
    lic.write_text(json.dumps({"orphan_fam": "cc_by_4.0"}), encoding="utf-8")
    schemas = vra.load_schemas(SCHEMAS_DIR)
    report = vra.validate_run_artifacts(
        source=vra.LocalDirSource(prefix),
        schemas=schemas,
        license_map={"orphan_fam": "cc_by_4.0"},
    )
    assert report.invariants["license_boundary_defined"] is True


def test_cli_license_map_loads_from_file(tmp_path: Path) -> None:
    target = tmp_path / "lm.json"
    target.write_text(json.dumps({"egov_law": "cc_by_4.0"}), encoding="utf-8")
    assert vra.load_license_map(str(target)) == {"egov_law": "cc_by_4.0"}
    assert vra.load_license_map(None) == {}


def test_cli_license_map_bad_json(tmp_path: Path) -> None:
    target = tmp_path / "lm.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="license-map JSON must be an object"):
        vra.load_license_map(str(target))


# ---------------------------------------------------------------------------
# 7) Smoke + integration
# ---------------------------------------------------------------------------


def test_report_to_dict_roundtrip_has_eight_keys() -> None:
    report = _run_validate(VALID_DIR)
    data = report.to_dict()
    assert set(data["invariants"].keys()) == set(vra.INVARIANT_IDS)
    assert isinstance(data["violation_count"], int)


def test_render_text_report_includes_all_invariants() -> None:
    report = _run_validate(VALID_DIR)
    text = vra.render_text_report(report)
    for inv in vra.INVARIANT_IDS:
        assert inv in text
    assert "OVERALL:" in text
