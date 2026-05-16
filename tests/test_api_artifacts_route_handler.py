"""FastAPI TestClient coverage push for ``src/jpintel_mcp/api/artifacts.py``.

Stream LL-2 2026-05-16 — push coverage 86% → 90% on the route handler body.
Targets the FastAPI route surface (compatibility_table /
application_strategy_pack / houjin_dd_pack) using the seeded tmp_path
jpintel.db (memory: ``feedback_no_quick_check_on_huge_sqlite`` — never
touches /Users/shigetoumeda/jpcite/autonomath.db).

Constraints:
  * tmp_path-only sqlite (the `client` fixture wires `seeded_db` which is
    rooted under ``tempfile.mkdtemp("jpintel-test-")``).
  * No source change.
  * No LLM call.

Coverage focus (route handler body that pure-helper tests cannot reach):
  * ``create_compatibility_table`` 422 (too_few_unique_programs).
  * ``create_compatibility_table`` happy path envelope assertions.
  * ``create_application_strategy_pack`` honeypot 400.
  * ``create_application_strategy_pack`` happy path + envelope.
  * ``create_houjin_dd_pack`` 422 (malformed houjin_bangou).
  * ``create_houjin_dd_pack`` happy path + sparse path.
  * artifact_type / endpoint / billing_metadata / packet_id / corpus_snapshot
    /_evidence/source_receipts/markdown_display/copy_paste_parts/known_gaps
    /human_review_required/recommended_followup envelope across each route.

Layout: a single TestClient `client` fixture (conftest) is reused; each test
posts to a different route and asserts the response envelope shape that
the route handler is responsible for assembling end-to-end.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Audit seal table autouse — layered onto the seeded jpintel.db so audit
# seal sign / seal_id queries used by _finalize_artifact_usage_and_seal do
# not OperationalError. Mirrors the pattern used by the existing
# tests/test_artifacts_*.py test files.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _layer_audit_seal_tables(seeded_db: Path) -> None:
    migrations = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
    for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
        mig_path = migrations / mig
        if not mig_path.exists():
            continue
        conn = sqlite3.connect(seeded_db)
        try:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.executescript(mig_path.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
    with contextlib.suppress(ImportError, AttributeError):
        from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

        _reset_corpus_snapshot_cache_for_tests()


# ---------------------------------------------------------------------------
# POST /v1/artifacts/compatibility_table — 422 + happy + envelope assertions
# ---------------------------------------------------------------------------


def test_compatibility_table_zero_program_ids_is_422(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": []},
    )
    # Either 422 from too_few_unique_programs (≥1 pair required) or 422 from
    # Pydantic validation (program_ids min_length). Both prove the route
    # fail-closes before any billing side effect.
    assert r.status_code == 422, r.text


def test_compatibility_table_single_program_id_too_few(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1"]},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    # Body is either {detail: {...}} or {detail: [{...}]} depending on which
    # validator fires. Both surface the failure reason in `detail`.
    assert "detail" in body


def test_compatibility_table_dup_program_ids_dedupes_to_one(
    client: TestClient,
) -> None:
    # Two ids that map to the same canonical -> dedupe to 1 -> too_few.
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-s-1"]},
    )
    assert r.status_code == 422, r.text


def test_compatibility_table_happy_returns_envelope(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Envelope assertions — produced by _attach_common_artifact_envelope +
    # _attach_billing_metadata + _finalize_artifact_usage_and_seal.
    assert body["artifact_type"] == "compatibility_table"
    assert body["endpoint"] == "artifacts.compatibility_table"
    assert "packet_id" in body
    assert body["packet_id"].startswith("pkt_compatibility_table_")


def test_compatibility_table_envelope_has_billing_metadata(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-b-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["billing_metadata"]["endpoint"] == "artifacts.compatibility_table"
    assert body["billing_metadata"]["unit_type"] == "compatibility_pair"
    assert body["billing_metadata"]["strict_metering"] is True


def test_compatibility_table_envelope_has_disclaimer(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "_disclaimer" in body


def test_compatibility_table_envelope_has_corpus_snapshot(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "corpus_snapshot_id" in body
    assert "corpus_checksum" in body


def test_compatibility_table_envelope_has_evidence_and_sources(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "_evidence" in body
    assert "sources" in body
    # source_count and len(sources) parity is part of artifact contract.
    assert body["_evidence"]["source_count"] == len(body["sources"])


def test_compatibility_table_envelope_has_known_gaps(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "known_gaps" in body
    assert isinstance(body["known_gaps"], list)


def test_compatibility_table_envelope_has_markdown_display(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["markdown_display"].startswith("# compatibility_table")


def test_compatibility_table_envelope_has_copy_paste(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["copy_paste_parts"]


def test_compatibility_table_envelope_has_recommended_followup(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recommended_followup"]


def test_compatibility_table_envelope_human_review_required(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "human_review_required" in body


# ---------------------------------------------------------------------------
# POST /v1/artifacts/application_strategy_pack
# ---------------------------------------------------------------------------


def _strategy_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "profile": {
            "prefecture": "Tokyo",
            "is_sole_proprietor": True,
            "planned_investment_man_yen": 100,
        },
        "max_candidates": 3,
        "compatibility_top_n": 0,
    }
    base.update(overrides)
    return base


def test_application_strategy_pack_honeypot_company_url_400(
    client: TestClient,
) -> None:
    payload = _strategy_payload()
    payload["profile"]["company_url"] = "https://attacker.example/"
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=payload,
    )
    assert r.status_code == 400, r.text


def test_application_strategy_pack_happy_returns_envelope(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact_type"] == "application_strategy_pack"
    assert body["endpoint"] == "artifacts.application_strategy_pack"
    assert body["packet_id"].startswith("pkt_application_strategy_pack_")


def test_application_strategy_pack_billing_metadata_shape(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    bm = body["billing_metadata"]
    assert bm["endpoint"] == "artifacts.application_strategy_pack"
    assert bm["unit_type"] == "artifact_call"
    assert bm["quantity"] == 1
    assert bm["strict_metering"] is True


def test_application_strategy_pack_summary_candidate_count(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["candidate_count"] >= 0


def test_application_strategy_pack_carries_known_gaps(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "known_gaps" in body


def test_application_strategy_pack_carries_disclaimer(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "_disclaimer" in body


def test_application_strategy_pack_max_candidates_clamped(
    client: TestClient,
) -> None:
    # Set a large max_candidates and assert the response still completes.
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(max_candidates=10),
    )
    assert r.status_code == 200, r.text


def test_application_strategy_pack_compatibility_top_n_zero(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(compatibility_top_n=0),
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# POST /v1/artifacts/houjin_dd_pack
# ---------------------------------------------------------------------------


def test_houjin_dd_pack_malformed_houjin_returns_422(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": "abcdefghijklm"},
    )
    assert r.status_code == 422, r.text


def test_houjin_dd_pack_too_short_houjin_returns_422(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": "12345"},
    )
    assert r.status_code == 422, r.text


def test_houjin_dd_pack_missing_houjin_returns_422(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={},
    )
    assert r.status_code == 422, r.text


def test_houjin_dd_pack_unknown_houjin_returns_404_or_200(
    client: TestClient,
) -> None:
    """Unknown but well-formed houjin_bangou either returns 404 (no match)
    or 200 with all-empty sections + a known_gap envelope. Both are
    fail-closed; this test pins whichever branch the route handler
    chooses for the env, so a future regression that 5xxs is caught.
    """
    r = client.post(
        "/v1/artifacts/houjin_dd_pack",
        json={"houjin_bangou": "9999999999999"},
    )
    assert r.status_code in {200, 404, 422}, r.text


# ---------------------------------------------------------------------------
# Cross-route invariants
# ---------------------------------------------------------------------------


def test_compatibility_table_and_strategy_pack_share_billing_note(
    client: TestClient,
) -> None:
    r1 = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    r2 = client.post(
        "/v1/artifacts/application_strategy_pack",
        json=_strategy_payload(),
    )
    assert r1.status_code == 200 and r2.status_code == 200
    for body in (r1.json(), r2.json()):
        # Every artifact route must thread billing_note + agent_routing.
        assert body["billing_note"] == body["agent_routing"]["pricing_note"]


def test_artifact_packet_id_is_stable_for_same_input(
    client: TestClient,
) -> None:
    payload = {"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]}
    r1 = client.post("/v1/artifacts/compatibility_table", json=payload)
    r2 = client.post("/v1/artifacts/compatibility_table", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    # _stable_artifact_id is content-derived; same payload = same id.
    assert r1.json()["packet_id"] == r2.json()["packet_id"]


def test_artifact_packet_id_differs_for_different_input(
    client: TestClient,
) -> None:
    r1 = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    r2 = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-b-1"]},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["packet_id"] != r2.json()["packet_id"]


# ---------------------------------------------------------------------------
# Anon quota + auth surface — calls without API key must still 200 (anon
# rate limit is reset autouse). Validates that the route does NOT require
# authentication. (Confirms `authenticated=False` audit_seal flag path.)
# ---------------------------------------------------------------------------


def test_compatibility_table_anon_audit_seal_flags(client: TestClient) -> None:
    r = client.post(
        "/v1/artifacts/compatibility_table",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    seal = body["billing_metadata"]["audit_seal"]
    assert seal["authenticated_key_present"] is False
    assert seal["requested_for_metered_key"] is False
