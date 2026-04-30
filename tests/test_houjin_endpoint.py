"""Contract tests for /v1/houjin/{bangou}.

Surfaces the gBizINFO + auxiliary corporate facts already in autonomath.db
(see api/houjin.py docstring). Module-skips when autonomath.db is missing
locally — same convention as test_annotation_tools.py / test_provenance_tools.py.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTONOMATH_DB = Path(
    os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))
)

if not _AUTONOMATH_DB.exists():
    pytest.skip(
        f"autonomath.db ({_AUTONOMATH_DB}) not present; "
        "skipping /v1/houjin/{bangou} suite.",
        allow_module_level=True,
    )

# Sample 法人番号 chosen from a live-DB walk (株式会社アンド・アイ —
# 8 adoption rows + 9+ corp.* facts). Picked because it exercises every
# major branch of the response composer in one round-trip.
_SAMPLE_BANGOU = "4120101047866"
_SAMPLE_NAME = "株式会社アンド・アイ"

# Bookyou 株式会社 (T8010001213708, the operator's own number). May not
# have a corporate_entity row in the gBizINFO snapshot — used as a sanity
# probe for the 404 path AS LONG AS no auxiliary join hits either. We
# assert dynamically below to handle the 'present in some auxiliary'
# case without flaking.
_BOOKYOU_BANGOU = "8010001213708"

# An invalid-format 法人番号 (not 13 digits). Path-level regex must 422.
_MALFORMED_BANGOU = "12345"


def _has_any_data(bangou: str) -> bool:
    """Probe autonomath.db directly: does this bangou show up anywhere?

    Used to make the 404 test resilient against ingest churn (if
    Bookyou eventually lands in jpi_invoice_registrants etc., the 404
    branch flips to 200 — but THIS test still passes by switching its
    assertion accordingly).
    """
    c = sqlite3.connect(f"file:{_AUTONOMATH_DB}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        for sql in (
            "SELECT 1 FROM am_entities WHERE canonical_id = ? AND record_kind='corporate_entity' LIMIT 1",
            "SELECT 1 FROM am_entity_facts WHERE entity_id = ? LIMIT 1",
        ):
            if c.execute(sql, (f"houjin:{bangou}",)).fetchone():
                return True
        for sql in (
            "SELECT 1 FROM jpi_invoice_registrants WHERE houjin_bangou = ? LIMIT 1",
            "SELECT 1 FROM jpi_adoption_records WHERE houjin_bangou = ? LIMIT 1",
            "SELECT 1 FROM am_enforcement_detail WHERE houjin_bangou = ? LIMIT 1",
        ):
            if c.execute(sql, (bangou,)).fetchone():
                return True
        return False
    finally:
        c.close()


def test_get_valid_houjin_returns_expected_envelope(client: TestClient) -> None:
    """Valid 法人番号 with rich gBizINFO facts returns 200 + full envelope.

    Pins the response shape so a future refactor cannot silently drop
    the disclaimer / namayoke caveat / corp_facts EAV.
    """
    if not _has_any_data(_SAMPLE_BANGOU):
        pytest.skip(
            f"sample 法人番号 {_SAMPLE_BANGOU} no longer in autonomath.db; "
            "pick a fresh one from `SELECT canonical_id FROM am_entities "
            "WHERE record_kind='corporate_entity' LIMIT 1;`"
        )

    r = client.get(f"/v1/houjin/{_SAMPLE_BANGOU}")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level envelope keys (contract surface).
    for key in (
        "basic",
        "corp_facts",
        "fact_count",
        "invoice_registration",
        "adoptions",
        "enforcement",
        "provenance",
        "_disclaimer",
        "_namayoke_caveat",
    ):
        assert key in body, f"missing envelope key: {key}"

    # `basic` block — distilled identity fields the docs promise.
    basic = body["basic"]
    assert basic["houjin_bangou"] == _SAMPLE_BANGOU
    # Either entity primary_name OR corp.legal_name fact must populate `name`.
    assert basic["name"], "basic.name unexpectedly empty"
    # Sample corp has 製造業 / 大阪府 / 79 employees on snapshot 2026-04-29.
    # We don't pin the exact strings (ingest may rewrite normalised forms);
    # we DO assert that at least one structural field flows through.
    assert any(
        basic.get(field) is not None
        for field in ("prefecture", "address", "employee_count", "industry_jsic_major")
    ), "basic block has no populated structural field — composer likely broken"

    # corp_facts EAV — at least one corp.* field must round-trip.
    assert isinstance(body["corp_facts"], dict)
    assert any(k.startswith("corp.") for k in body["corp_facts"]), (
        "corp_facts has no corp.* entries — EAV pull regressed"
    )
    # Every entry carries the (value, unit, kind) shape per docstring.
    for fname, fobj in body["corp_facts"].items():
        assert "value" in fobj, f"corp_facts[{fname}] missing 'value'"
        assert "unit" in fobj, f"corp_facts[{fname}] missing 'unit'"
        assert "kind" in fobj, f"corp_facts[{fname}] missing 'kind'"

    # houjin_bangou must NOT leak into corp_facts (we strip it as redundant).
    assert "houjin_bangou" not in body["corp_facts"]

    # Adoptions block — total is int, recent[] capped at 5.
    adoptions = body["adoptions"]
    assert isinstance(adoptions["total"], int)
    assert isinstance(adoptions["recent"], list)
    assert len(adoptions["recent"]) <= 5

    # Enforcement block — same shape.
    enforcement = body["enforcement"]
    assert isinstance(enforcement["total"], int)
    assert isinstance(enforcement["recent"], list)
    assert len(enforcement["recent"]) <= 5

    # Provenance block (auditor reproducibility).
    prov = body["provenance"]
    assert prov["canonical_id"] == f"houjin:{_SAMPLE_BANGOU}"
    assert "gBizINFO" in prov["data_origin"]

    # §52 fence + 名寄せ caveat — pinned strings (copy changes go through review).
    assert "税務助言" in body["_disclaimer"]
    assert "§52" in body["_disclaimer"]
    assert "名寄せ" in body["_namayoke_caveat"]

    # Response budget — under 50KB target.
    assert len(r.content) < 50_000, (
        f"response is {len(r.content)} bytes, > 50KB budget"
    )


def test_invalid_format_houjin_returns_422(client: TestClient) -> None:
    """Path regex rejects non-13-digit input as 422 (FastAPI validation)."""
    r = client.get(f"/v1/houjin/{_MALFORMED_BANGOU}")
    assert r.status_code == 422


def test_unknown_houjin_returns_404_with_envelope(client: TestClient) -> None:
    """A 13-digit 法人番号 not in any autonomath.db surface returns 404.

    The body is structured (NOT a bare detail string): it carries the
    pointer to the official gBizINFO lookup plus the disclaimer envelope.
    """
    # Synthetic bangou that is unlikely to exist anywhere. We probe live
    # to skip if it accidentally lands (autonomath.db churns at ingest time).
    miss_bangou = "9999999999999"
    if _has_any_data(miss_bangou):
        pytest.skip(
            f"synthetic miss bangou {miss_bangou} now has data; "
            "404 path can't be exercised without picking a fresher miss."
        )

    r = client.get(f"/v1/houjin/{miss_bangou}")
    assert r.status_code == 404, r.text
    body = r.json()

    # Pin the structured 404 keys.
    for key in (
        "detail",
        "houjin_bangou",
        "alternative",
        "_disclaimer",
        "_namayoke_caveat",
    ):
        assert key in body, f"missing 404 envelope key: {key}"

    assert body["houjin_bangou"] == miss_bangou
    # Pointer to the gBizINFO official lookup with the bangou query string.
    assert "info.gbiz.go.jp" in body["alternative"]
    assert miss_bangou in body["alternative"]


def test_anon_within_quota_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous caller within the 50/月 IP cap gets 200.

    Uses the autouse ``_reset_anon_rate_limit`` fixture (conftest.py) so
    the bucket starts at 0. We pin a small per-month cap to keep the
    setup tight without 50 hops.
    """
    if not _has_any_data(_SAMPLE_BANGOU):
        pytest.skip(f"sample 法人番号 {_SAMPLE_BANGOU} no longer in DB.")
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 5)

    r = client.get(
        f"/v1/houjin/{_SAMPLE_BANGOU}",
        headers={"x-forwarded-for": "198.51.100.201"},
    )
    assert r.status_code == 200, r.text
    # Anon 200s carry the friction-removal headers (S3, 2026-04-25).
    assert r.headers.get("X-Anon-Quota-Remaining") is not None


def test_anon_over_quota_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous caller hitting the 50/月 IP cap gets 429 on /v1/houjin too.

    Pinning the limit at 1 makes the second call cross the threshold;
    the conftest autouse fixture wipes anon_rate_limit between tests.
    """
    if not _has_any_data(_SAMPLE_BANGOU):
        pytest.skip(f"sample 法人番号 {_SAMPLE_BANGOU} no longer in DB.")
    from jpintel_mcp.config import settings

    # 1 call per month → 2nd call MUST 429.
    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 1)

    ip = "198.51.100.211"
    r1 = client.get(
        f"/v1/houjin/{_SAMPLE_BANGOU}",
        headers={"x-forwarded-for": ip},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.get(
        f"/v1/houjin/{_SAMPLE_BANGOU}",
        headers={"x-forwarded-for": ip},
    )
    assert r2.status_code == 429, (
        f"second anon call should 429 at limit=1; got {r2.status_code} {r2.text}"
    )
