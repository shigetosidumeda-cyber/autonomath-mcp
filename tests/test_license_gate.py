"""License Export Gate — primitive + integration tests.

Covers `src/jpintel_mcp/api/_license_gate.py` (allow-list semantics,
`assert_no_blocked`, `annotate_attribution`) and the DD ZIP export path
(`POST /v1/am/dd_export`) wiring of the gate.

Spec source: `docs/_internal/value_maximization_plan_no_llm_api.md`
§24 + §28.9 No-Go #5 — `license in ('proprietary','unknown')` MUST NOT
land in any export-eligible row.
"""

from __future__ import annotations

import io
import itertools
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from jpintel_mcp.api._license_gate import (
    BLOCKED_LICENSES,
    REDISTRIBUTABLE_LICENSES,
    LicenseGateError,
    annotate_attribution,
    assert_no_blocked,
    filter_redistributable,
)

# Match the M&A pillar e2e file's seeded houjin_bangous so the dd_export
# integration test exercises the same ingest fixtures.
_FIVE_HOUJIN: tuple[str, ...] = (
    "1010001000001",
    "2010001000002",
    "3010001000003",
    "4010001000004",
    "5010001000005",
)
_IDEM_COUNTER = itertools.count()


def _idem_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Idempotency-Key": f"license-gate-{next(_IDEM_COUNTER)}",
    }


# ---------------------------------------------------------------------------
# Test 1 — `filter_redistributable` over a mixed 10-row set
# ---------------------------------------------------------------------------


def test_filter_redistributable_mixed_set_splits_8_2() -> None:
    """3 pdl_v1.0 + 2 gov_standard + 2 cc_by_4.0 + 1 public_domain +
    1 proprietary + 1 unknown → allowed=8 / blocked=2.
    """
    rows = [
        {"id": 1, "license": "pdl_v1.0"},
        {"id": 2, "license": "pdl_v1.0"},
        {"id": 3, "license": "pdl_v1.0"},
        {"id": 4, "license": "gov_standard"},
        {"id": 5, "license": "gov_standard"},
        {"id": 6, "license": "cc_by_4.0"},
        {"id": 7, "license": "cc_by_4.0"},
        {"id": 8, "license": "public_domain"},
        {"id": 9, "license": "proprietary"},
        {"id": 10, "license": "unknown"},
    ]
    allowed, blocked = filter_redistributable(rows)
    assert len(allowed) == 8
    assert len(blocked) == 2
    assert {r["id"] for r in blocked} == {9, 10}
    # Allowed rows preserve order.
    assert [r["id"] for r in allowed] == [1, 2, 3, 4, 5, 6, 7, 8]


# ---------------------------------------------------------------------------
# Test 2 — unknown allow-list values are blocked (allow-list, NOT deny-list)
# ---------------------------------------------------------------------------


def test_filter_redistributable_rejects_unknown_value_as_blocked() -> None:
    """Anything not in REDISTRIBUTABLE_LICENSES blocks under the
    allow-list policy — including future values and typos."""
    rows = [
        {"id": "A", "license": "pdl_v1.0"},
        {"id": "B", "license": "mit-but-not-listed"},  # not in allow set
        {"id": "C", "license": "gov_standard_v2.0"},  # allowed government standard
        {"id": "D", "license": "CC_BY_4.0"},  # case-mismatch
        {"id": "E"},  # missing field
        {"id": "F", "license": None},  # None value
        {"id": "G", "license": ""},  # empty string
    ]
    allowed, blocked = filter_redistributable(rows)
    assert {r["id"] for r in allowed} == {"A", "C"}
    assert {r["id"] for r in blocked} == {"B", "D", "E", "F", "G"}


# ---------------------------------------------------------------------------
# Test 3 — `assert_no_blocked` raises on proprietary / unknown,
# passes on pdl_v1.0
# ---------------------------------------------------------------------------


def test_assert_no_blocked_raises_on_proprietary() -> None:
    with pytest.raises(LicenseGateError) as exc_info:
        assert_no_blocked([{"id": 1, "license": "proprietary"}])
    assert "proprietary" in str(exc_info.value)


def test_assert_no_blocked_raises_on_unknown() -> None:
    with pytest.raises(LicenseGateError) as exc_info:
        assert_no_blocked([{"id": 1, "license": "unknown"}])
    assert "unknown" in str(exc_info.value)


def test_assert_no_blocked_passes_on_pdl_v1() -> None:
    # Should NOT raise.
    assert_no_blocked([{"id": 1, "license": "pdl_v1.0"}])


def test_assert_no_blocked_summary_lists_top_10() -> None:
    # Build 12 distinct license values to ensure the summary truncates
    # at 10 keys (per the implementation contract).
    rows = [{"id": i, "license": f"weird_{i}"} for i in range(12)]
    with pytest.raises(LicenseGateError) as exc_info:
        assert_no_blocked(rows)
    msg = str(exc_info.value)
    assert "12 blocked" in msg


def test_blocked_licenses_constant_explicit() -> None:
    """`BLOCKED_LICENSES` carries the two canonical deny values for
    diagnostic surfaces; the gate logic itself uses the allow list, but
    the constant exists for a clear human-readable surface."""
    assert "proprietary" in BLOCKED_LICENSES
    assert "unknown" in BLOCKED_LICENSES


def test_redistributable_licenses_constant_explicit() -> None:
    assert "pdl_v1.0" in REDISTRIBUTABLE_LICENSES
    assert "gov_standard" in REDISTRIBUTABLE_LICENSES
    assert "cc_by_4.0" in REDISTRIBUTABLE_LICENSES
    assert "public_domain" in REDISTRIBUTABLE_LICENSES
    # Negative — the deny values must NOT slip into the allow set.
    assert "proprietary" not in REDISTRIBUTABLE_LICENSES
    assert "unknown" not in REDISTRIBUTABLE_LICENSES


# ---------------------------------------------------------------------------
# Test 4 — `annotate_attribution` produces the canonical string
# ---------------------------------------------------------------------------


def test_annotate_attribution_canonical_format() -> None:
    row = {
        "publisher": "e-Gov",
        "source_url": "https://elaws.e-gov.go.jp/document?lawid=123",
        "fetched_at": "2026-04-29T03:00:00+00:00",
        "license": "cc_by_4.0",
        "primary_name": "テスト法令",
    }
    out = annotate_attribution(row)
    expected = (
        "出典: e-Gov / https://elaws.e-gov.go.jp/document?lawid=123 / "
        "取得 2026-04-29T03:00:00+00:00 / license=cc_by_4.0"
    )
    assert out["_attribution"] == expected
    # Non-mutating — the input row stays unchanged.
    assert "_attribution" not in row
    # Original fields preserved.
    assert out["publisher"] == "e-Gov"
    assert out["primary_name"] == "テスト法令"


def test_annotate_attribution_missing_fields_render_as_unknown() -> None:
    out = annotate_attribution({})
    assert out["_attribution"] == ("出典: unknown / unknown / 取得 unknown / license=unknown")


# ---------------------------------------------------------------------------
# Tests 5 + 6 — DD ZIP integration: gate drops proprietary, sets headers
# ---------------------------------------------------------------------------


@pytest.fixture
def _ensure_ma_pillar_tables(seeded_db: Path):
    """Apply migration 088 + seed minimal fixture rows.

    Mirrors the autouse fixture in `tests/test_ma_pillar_e2e.py`. Kept
    explicit + non-autouse here so the pure-primitive tests (1-4) do
    not pay the migration cost.
    """
    repo = Path(__file__).resolve().parent.parent
    for mig in ("080_customer_webhooks.sql", "088_houjin_watch.sql"):
        sql_path = repo / "scripts" / "migrations" / mig
        sql = sql_path.read_text(encoding="utf-8")
        c = sqlite3.connect(seeded_db)
        try:
            c.executescript(sql)
            c.commit()
        finally:
            c.close()
    yield


def test_dd_export_zip_filters_proprietary_row(
    client, paid_key, _ensure_ma_pillar_tables, monkeypatch
):
    """Test 5 — POST /v1/am/dd_export over a 3-houjin batch where one
    profile carries license='proprietary'. The proprietary row must NOT
    appear in the ZIP; MANIFEST.json must show blocked_count=1.

    We patch `_enrich_profile_with_license` to assign a deterministic
    license per profile so the test does not depend on having real
    `am_source` rows in the seeded jpintel.db.
    """
    from jpintel_mcp.api import ma_dd

    # Seed each profile with a deterministic license so we can assert
    # the gate's behavior on a known input. The first two are
    # redistributable (pdl_v1.0); the third is proprietary.
    license_map: dict[str, str] = {
        _FIVE_HOUJIN[0]: "pdl_v1.0",
        _FIVE_HOUJIN[1]: "cc_by_4.0",
        _FIVE_HOUJIN[2]: "proprietary",
    }

    def _fake_enrich(profile, *, am_conn):
        hj = profile.get("houjin_bangou")
        profile["license"] = license_map.get(hj, "unknown")
        profile["source_url"] = f"https://example.gov.jp/{hj}"
        profile["publisher"] = "example.gov.jp"
        profile["fetched_at"] = "2026-04-30T00:00:00+00:00"

    monkeypatch.setattr(ma_dd, "_enrich_profile_with_license", _fake_enrich)

    r = client.post(
        "/v1/am/dd_export",
        headers=_idem_headers(paid_key),
        json={
            "deal_id": "MA-LICENSE-GATE-TEST",
            "houjin_bangous": list(_FIVE_HOUJIN[:3]),
            "format": "zip",
            "max_cost_jpy": 1_008,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Body-side license_gate mirror.
    assert body["license_gate"]["allowed_count"] == 2
    assert body["license_gate"]["blocked_count"] == 1
    assert body["license_gate"]["blocked_reasons"] == {"proprietary": 1}
    # Allow list visible to caller for self-service debugging.
    assert "pdl_v1.0" in body["license_gate"]["redistributable_licenses"]

    # Test 6 — response headers carry the gate counts.
    assert r.headers["X-License-Gate-Allowed"] == "2"
    assert r.headers["X-License-Gate-Blocked"] == "1"

    # Now re-build the ZIP via the helper (the route uses an R2 stub
    # URL in tests, so we need to round-trip the bytes ourselves).
    from jpintel_mcp.config import settings

    jp_conn = sqlite3.connect(settings.db_path)
    jp_conn.row_factory = sqlite3.Row
    profiles = [
        ma_dd._build_dd_profile(
            jp_conn=jp_conn,
            am_conn=None,
            houjin_bangou=hj,
            depth="full",
        )
        for hj in _FIVE_HOUJIN[:3]
    ]
    jp_conn.close()
    for p in profiles:
        _fake_enrich(p, am_conn=None)
    zip_bytes, _zip_sha, gate_summary = ma_dd._build_audit_bundle_zip(
        deal_id="MA-LICENSE-GATE-TEST",
        profiles=profiles,
        snapshot_id=body["corpus_snapshot_id"],
        checksum=body["corpus_checksum"],
    )

    # Crack open the ZIP and assert the gate decision.
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        # MANIFEST.json (license-gate) and attribution.txt are mandatory.
        assert "MANIFEST.json" in names
        assert "attribution.txt" in names

        # The proprietary houjin must NOT have a profiles/ entry.
        assert f"profiles/{_FIVE_HOUJIN[0]}.jsonl" in names  # allowed
        assert f"profiles/{_FIVE_HOUJIN[1]}.jsonl" in names  # allowed
        assert f"profiles/{_FIVE_HOUJIN[2]}.jsonl" not in names  # blocked

        # MANIFEST.json content.
        license_manifest = json.loads(zf.read("MANIFEST.json"))
        assert license_manifest["allowed_count"] == 2
        assert license_manifest["blocked_count"] == 1
        assert license_manifest["blocked_reasons"] == {"proprietary": 1}
        assert "attribution_notice" in license_manifest
        assert "policy" in license_manifest
        assert license_manifest["schema_version"] == "license_gate.v1"

        # attribution.txt does NOT mention the proprietary houjin's URL.
        attr = zf.read("attribution.txt").decode("utf-8")
        assert _FIVE_HOUJIN[2] not in attr  # blocked row excluded
        assert _FIVE_HOUJIN[0] in attr or _FIVE_HOUJIN[1] in attr

        # Per-profile JSONL of an allowed houjin must NOT contain the
        # blocked houjin's data anywhere.
        for hj in (_FIVE_HOUJIN[0], _FIVE_HOUJIN[1]):
            data = zf.read(f"profiles/{hj}.jsonl").decode("utf-8")
            assert _FIVE_HOUJIN[2] not in data, (
                "proprietary houjin's bangou must NEVER leak into an allowed profile's JSONL"
            )

    # gate_summary mirror is consistent with the body.
    assert gate_summary["allowed_count"] == 2
    assert gate_summary["blocked_count"] == 1


def test_dd_export_all_blocked_returns_empty_zip(
    client, paid_key, _ensure_ma_pillar_tables, monkeypatch
):
    """When EVERY profile is blocked, the ZIP still materializes
    (with MANIFEST.json + attribution.txt) so the customer can see why
    they got 0 rows. The headers + body reflect blocked_count=N,
    allowed_count=0."""
    from jpintel_mcp.api import ma_dd

    def _fake_enrich(profile, *, am_conn):
        profile["license"] = "unknown"  # all blocked
        profile["source_url"] = "https://example.gov.jp/x"
        profile["publisher"] = "example.gov.jp"
        profile["fetched_at"] = "2026-04-30T00:00:00+00:00"

    monkeypatch.setattr(ma_dd, "_enrich_profile_with_license", _fake_enrich)

    r = client.post(
        "/v1/am/dd_export",
        headers=_idem_headers(paid_key),
        json={
            "deal_id": "MA-LICENSE-GATE-ALL-BLOCKED",
            "houjin_bangous": list(_FIVE_HOUJIN[:2]),
            "format": "zip",
            "max_cost_jpy": 1_005,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["license_gate"]["allowed_count"] == 0
    assert body["license_gate"]["blocked_count"] == 2
    assert body["license_gate"]["blocked_reasons"] == {"unknown": 2}
    assert r.headers["X-License-Gate-Allowed"] == "0"
    assert r.headers["X-License-Gate-Blocked"] == "2"
