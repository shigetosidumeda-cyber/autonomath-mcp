"""Contract tests for /v1/programs/by_corporate_form +
/v1/programs/{unified_id}/eligibility_by_form.

The matrix endpoints lift the 法人格 axis from
``am_program_eligibility_predicate_json`` (5,702 rows whose
``$.target_entity_types`` array carries the entity-type filter) and the
``am_target_profile`` 43-row taxonomy.

Module-skips when autonomath.db is missing locally — same convention
as test_houjin_endpoint.py / test_annotation_tools.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTONOMATH_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))

if not _AUTONOMATH_DB.exists():
    pytest.skip(
        f"autonomath.db ({_AUTONOMATH_DB}) not present; "
        "skipping /v1/programs/by_corporate_form suite.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def _pin_jpintel_db_for_anon_quota(seeded_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep anon quota writes on the seeded jpintel DB during full-suite runs.

    Mirrors test_houjin_endpoint.py — corporate_form router is mounted with
    AnonIpLimitDep so the anon counter must point at the test DB to avoid
    cross-test pollution on a developer machine.
    """
    from jpintel_mcp.api import anon_limit as _anon_limit
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "db_path", seeded_db)
    monkeypatch.setattr(_anon_limit.settings, "db_path", seeded_db)


def _pick_sample_unified_id(form_predicate_value: str = "corporation") -> str | None:
    """Find a UNI-* whose predicate JSON lists `form_predicate_value`.

    Used to source live test inputs that won't break when the predicate
    corpus churns. Returns None if the corpus is too thin (test then skips).
    """
    c = sqlite3.connect(f"file:{_AUTONOMATH_DB}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        row = c.execute(
            """
            SELECT program_id
              FROM am_program_eligibility_predicate_json
             WHERE EXISTS (
                 SELECT 1 FROM json_each(
                     json_extract(predicate_json, '$.target_entity_types')
                 )
                 WHERE value = ?
             )
             LIMIT 1
            """,
            (form_predicate_value,),
        ).fetchone()
        return row["program_id"] if row else None
    finally:
        c.close()


def _pick_sole_only_unified_id() -> str | None:
    """Find a UNI-* whose predicate `target_entity_types` is *only*
    `["sole_proprietor"]` — used to assert that 株式会社 is `not_allowed`.
    """
    c = sqlite3.connect(f"file:{_AUTONOMATH_DB}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        # JSON array equality via json_each count + value match.
        rows = c.execute(
            """
            SELECT program_id, predicate_json
              FROM am_program_eligibility_predicate_json
             WHERE predicate_json LIKE '%target_entity_types%'
             LIMIT 200
            """
        ).fetchall()
        for r in rows:
            try:
                obj = json.loads(r["predicate_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            tet = obj.get("target_entity_types")
            if isinstance(tet, list) and tet == ["sole_proprietor"]:
                return r["program_id"]
        return None
    finally:
        c.close()


# ---------------------------------------------------------------------------
# /v1/programs/by_corporate_form
# ---------------------------------------------------------------------------


def test_by_corporate_form_short_code_returns_envelope(client: TestClient) -> None:
    """Short-code form (`goudou`) returns the documented envelope shape."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "goudou", "limit": 10},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "applied_filters",
        "programs",
        "count",
        "_disclaimer",
        "_form_caveat",
    ):
        assert key in body, f"missing envelope key: {key}"
    af = body["applied_filters"]
    assert af["form_code"] == "goudou"
    assert af["form_label"] == "合同会社"
    assert af["form_entity_class"] == "corporation"
    assert af["limit"] == 10
    assert isinstance(body["programs"], list)
    assert body["count"] == len(body["programs"])
    assert "税務助言" in body["_disclaimer"]
    assert "§52" in body["_disclaimer"]
    assert "公募要領" in body["_form_caveat"]


def test_by_corporate_form_jp_label_normalises(client: TestClient) -> None:
    """JP label (`株式会社`) is accepted and normalises to short code."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "株式会社", "limit": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_filters"]["form_code"] == "kabushiki"
    assert body["applied_filters"]["form_label"] == "株式会社"


def test_by_corporate_form_with_industry_jsic_filter(client: TestClient) -> None:
    """Combined form + industry filter still returns valid envelope."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "goudou", "industry_jsic": "D", "limit": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_filters"]["industry_jsic"] == "D"
    # Each row must NOT contradict the industry filter — either no
    # `predicate_industries_jsic` (universal) or it includes 'D'.
    for p in body["programs"]:
        ind = p.get("predicate_industries_jsic")
        if ind is not None:
            assert "D" in ind, f"industry filter leaked: {p}"


def test_by_corporate_form_unknown_form_returns_422(client: TestClient) -> None:
    """Unknown form short code is rejected at the input boundary."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "weirdform_xyz"},
    )
    assert r.status_code == 422, r.text


def test_by_corporate_form_invalid_industry_jsic_returns_422(client: TestClient) -> None:
    """industry_jsic must be a single A-T letter; 'AA' fails."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "goudou", "industry_jsic": "AA"},
    )
    assert r.status_code == 422


def test_by_corporate_form_npo_short_code(client: TestClient) -> None:
    """NPO short code maps to entity_class=npo."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "npo", "limit": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    af = body["applied_filters"]
    assert af["form_code"] == "npo"
    assert af["form_entity_class"] == "npo"
    assert af["form_label"] == "NPO法人"


def test_by_corporate_form_school_corp_short_code(client: TestClient) -> None:
    """学校法人 short code resolves correctly."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "school", "limit": 3},
    )
    assert r.status_code == 200, r.text
    af = r.json()["applied_filters"]
    assert af["form_code"] == "school"
    assert af["form_label"] == "学校法人"
    assert af["form_entity_class"] == "school_corporation"


def test_by_corporate_form_sole_proprietor(client: TestClient) -> None:
    """個人事業主 short code passes through."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "sole", "limit": 3},
    )
    assert r.status_code == 200, r.text
    af = r.json()["applied_filters"]
    assert af["form_code"] == "sole"
    assert af["form_entity_class"] == "sole_proprietor"


def test_by_corporate_form_limit_capped_at_200(client: TestClient) -> None:
    """limit > 200 is rejected at the validator (not silently capped)."""
    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "goudou", "limit": 1000},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /v1/programs/{unified_id}/eligibility_by_form
# ---------------------------------------------------------------------------


def test_eligibility_by_form_returns_15_axes(client: TestClient) -> None:
    """Matrix carries 15 法人格 codes — full closed enum."""
    uid = _pick_sample_unified_id("corporation")
    if uid is None:
        pytest.skip("no predicate row with target_entity_types=corporation")

    r = client.get(f"/v1/programs/{uid}/eligibility_by_form")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["unified_id"] == uid
    matrix = body["matrix"]
    expected_codes = {
        "kabushiki",
        "goudou",
        "goushi",
        "goumei",
        "npo",
        "ippan_shadan",
        "koueki_shadan",
        "ippan_zaidan",
        "koueki_zaidan",
        "school",
        "medical",
        "cooperative",
        "sole",
        "individual",
        "foreign",
    }
    assert set(matrix.keys()) == expected_codes, (
        f"matrix axes drifted: missing {expected_codes - set(matrix.keys())}"
    )

    # Every entry carries the (label, entity_class, verdict, reason) shape.
    for code, axis in matrix.items():
        for key in ("label", "entity_class", "verdict", "reason"):
            assert key in axis, f"matrix[{code}] missing {key}"
        assert axis["verdict"] in ("allowed", "not_allowed", "unspecified")

    # `corporation` predicate → kabushiki / goudou allowed.
    assert matrix["kabushiki"]["verdict"] == "allowed"
    assert matrix["goudou"]["verdict"] == "allowed"

    # §52 + form caveat surfaced verbatim.
    assert "税務助言" in body["_disclaimer"]
    assert "公募要領" in body["_form_caveat"]


def test_eligibility_by_form_sole_only_program_excludes_kabushiki(
    client: TestClient,
) -> None:
    """A program restricted to ['sole_proprietor'] marks kabushiki as not_allowed."""
    uid = _pick_sole_only_unified_id()
    if uid is None:
        pytest.skip("no sole-only predicate row in current snapshot")

    r = client.get(f"/v1/programs/{uid}/eligibility_by_form")
    assert r.status_code == 200, r.text
    matrix = r.json()["matrix"]

    assert matrix["sole"]["verdict"] == "allowed"
    assert matrix["kabushiki"]["verdict"] == "not_allowed"
    # The reason cites the predicate field that drove the verdict.
    assert "sole_proprietor" in matrix["kabushiki"]["reason"]


def test_eligibility_by_form_invalid_unified_id_returns_422(client: TestClient) -> None:
    """unified_id must match UNI-<10 hex>."""
    r = client.get("/v1/programs/NOT-A-VALID-ID/eligibility_by_form")
    assert r.status_code == 422


def test_eligibility_by_form_unknown_unified_id_returns_404(client: TestClient) -> None:
    """A well-formed unified_id with no predicate row 404s with structured envelope."""
    # Synthetic unified_id that won't exist in the predicate corpus.
    uid = "UNI-deadbeef00"
    r = client.get(f"/v1/programs/{uid}/eligibility_by_form")
    if r.status_code == 200:
        # If the corpus happens to contain this id the test is moot — skip.
        pytest.skip(f"synthetic uid {uid} unexpectedly present")
    assert r.status_code == 404, r.text
    body = r.json()
    for key in ("detail", "unified_id", "_disclaimer", "_form_caveat"):
        assert key in body, f"missing 404 key: {key}"
    assert body["unified_id"] == uid


def test_eligibility_by_form_no_target_entity_types_marks_all_allowed(
    client: TestClient,
) -> None:
    """A predicate row WITHOUT target_entity_types marks every axis allowed."""
    c = sqlite3.connect(f"file:{_AUTONOMATH_DB}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        row = c.execute(
            """
            SELECT program_id
              FROM am_program_eligibility_predicate_json
             WHERE json_extract(predicate_json, '$.target_entity_types') IS NULL
             LIMIT 1
            """,
        ).fetchone()
    finally:
        c.close()
    if row is None:
        pytest.skip("no predicate row missing target_entity_types in current snapshot")
    uid = row["program_id"]
    r = client.get(f"/v1/programs/{uid}/eligibility_by_form")
    assert r.status_code == 200, r.text
    matrix = r.json()["matrix"]
    # Every form should resolve to `allowed` because the predicate carries
    # no entity-type restriction (universal access).
    for code, axis in matrix.items():
        assert axis["verdict"] == "allowed", (
            f"matrix[{code}] should be allowed when predicate has no "
            f"target_entity_types; got {axis['verdict']}"
        )


# ---------------------------------------------------------------------------
# Anon quota — both routes inherit AnonIpLimitDep on mount.
# ---------------------------------------------------------------------------


def test_anon_within_quota_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anonymous caller within the daily IP cap gets 200."""
    from jpintel_mcp.api import anon_limit as _anon_limit
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 5)
    monkeypatch.setattr(_anon_limit.settings, "anon_rate_limit_per_day", 5)

    r = client.get(
        "/v1/programs/by_corporate_form",
        params={"form": "goudou", "limit": 1},
        headers={"x-forwarded-for": "198.51.100.231"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Anon-Quota-Remaining") is not None
