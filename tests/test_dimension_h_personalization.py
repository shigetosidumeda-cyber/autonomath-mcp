"""Dim H — personalization_v2 REST endpoint tests (Wave 46).

Covers ``src/jpintel_mcp/api/personalization_v2.py`` (Wave 43.2.8) which
ships ``GET /v1/me/recommendations``. The existing ``test_dimension_g_h``
suite tests the migration + cron paths; this file fills the REST-surface
gap surfaced by the dim 19 audit (`test MISSING` rating, 4.50/10).

Posture
-------
* Pure unit test — no heavy ``seeded_db`` fixture, no live network. We
  mount the router under a tiny ``FastAPI()`` app and inject test
  doubles via ``app.dependency_overrides``.
* No LLM SDK imports (verified by ``test_no_llm_in_production.py``).
* Schemas are seeded by re-applying ``264_personalization_score.sql``
  on a fresh tempdir sqlite — same pattern as ``test_dimension_g_h``.

Cases
-----
1. happy-path: 200 with one scored program, breakdown + reasoning
   envelope intact.
2. empty result: 200 with ``items=[]``, ``total=0``, ``refreshed_at=None``.
3. unknown client_id: 404 ``client_id not found for this api_key``.
4. missing api_key on ApiContext: 401 ``api_key required``.
5. cross-tenant isolation: api_key_hash mismatch returns 404 (other
   tenant's profile is invisible).
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_264 = REPO_ROOT / "scripts" / "migrations" / "264_personalization_score.sql"


def _apply_sql(conn: sqlite3.Connection, sql_path: pathlib.Path) -> None:
    conn.executescript(sql_path.read_text(encoding="utf-8"))


def _build_jp_conn(tmp_path: pathlib.Path) -> sqlite3.Connection:
    # ``check_same_thread=False`` matches the prod connection pool which is
    # accessed across the FastAPI worker pool. TestClient happens to spin up
    # the route on a worker thread distinct from the fixture creator so we
    # must opt out of the default safety check.
    conn = sqlite3.connect(tmp_path / "jpintel.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            tier TEXT,
            prefecture TEXT,
            program_kind TEXT,
            source_url TEXT,
            official_url TEXT,
            excluded INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE client_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT NOT NULL,
            name_label TEXT NOT NULL,
            jsic_major TEXT,
            prefecture TEXT,
            employee_count INTEGER,
            capital_yen INTEGER
        );
        """
    )
    return conn


def _build_am_conn(tmp_path: pathlib.Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "autonomath.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_sql(conn, MIG_264)
    return conn


def _seed_program(conn: sqlite3.Connection, **overrides: Any) -> None:
    row = {
        "unified_id": "P-DIM-H-1",
        "primary_name": "ものづくり補助金 (製造業 設備投資)",
        "tier": "S",
        "prefecture": "東京都",
        "program_kind": "subsidy",
        "source_url": "https://example.gov.jp/p1",
        "official_url": "https://example.gov.jp/p1/official",
        "excluded": 0,
    }
    row.update(overrides)
    conn.execute(
        """INSERT INTO programs(
                unified_id, primary_name, tier, prefecture, program_kind,
                source_url, official_url, excluded)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            row["unified_id"],
            row["primary_name"],
            row["tier"],
            row["prefecture"],
            row["program_kind"],
            row["source_url"],
            row["official_url"],
            row["excluded"],
        ),
    )


def _seed_profile(
    conn: sqlite3.Connection,
    api_key_hash: str,
    name_label: str = "テスト顧問先",
) -> int:
    cur = conn.execute(
        """INSERT INTO client_profiles(
                api_key_hash, name_label, jsic_major, prefecture,
                employee_count, capital_yen)
           VALUES (?,?,?,?,?,?)""",
        (api_key_hash, name_label, "E", "東京都", 50, 10_000_000),
    )
    profile_id = cur.lastrowid
    assert profile_id is not None
    return int(profile_id)


def _seed_score(
    am_conn: sqlite3.Connection,
    *,
    api_key_hash: str,
    client_id: int,
    program_id: str,
    score: int,
    industry_pack: str = "pack_manufacturing",
) -> None:
    am_conn.execute(
        """INSERT INTO am_personalization_score(
                api_key_hash, client_id, program_id, score,
                score_breakdown_json, reasoning_json, industry_pack,
                refreshed_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            api_key_hash,
            client_id,
            program_id,
            score,
            '{"client_fit": 40, "industry_pack": 25, "saved_search": 10}',
            '{"client_fit_reason": "JSIC E + 東京都 一致", '
            '"saved_searches_matched": ["製造業 設備投資 watch"]}',
            industry_pack,
            "2026-05-12T01:00:00.000Z",
        ),
    )
    am_conn.commit()


class _StubApiContext:
    def __init__(self, key_hash: str | None = "kh-test") -> None:
        self.key_hash = key_hash
        self.tier = "paid"


@pytest.fixture()
def pers_client(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, sqlite3.Connection, sqlite3.Connection]]:
    from jpintel_mcp.api import deps as deps_module
    from jpintel_mcp.api import personalization_v2 as pers_module

    jp_conn = _build_jp_conn(tmp_path)
    am_conn = _build_am_conn(tmp_path)

    # The endpoint opens its own am_conn via ``_resolve_am_conn`` reading
    # ``settings.autonomath_db_path``. Point it at our temp DB and keep the
    # fixture-owned connection alive so seed data is visible to the route.
    monkeypatch.setattr(
        "jpintel_mcp.config.settings.autonomath_db_path",
        tmp_path / "autonomath.db",
        raising=False,
    )

    app = FastAPI()
    app.include_router(pers_module.router)
    app.dependency_overrides[deps_module.require_key] = lambda: _StubApiContext()
    app.dependency_overrides[deps_module.get_db] = lambda: jp_conn

    with TestClient(app) as client:
        yield client, jp_conn, am_conn

    jp_conn.close()
    am_conn.close()


def test_recommendations_happy_path(
    pers_client: tuple[TestClient, sqlite3.Connection, sqlite3.Connection],
) -> None:
    client, jp_conn, am_conn = pers_client
    _seed_program(jp_conn)
    jp_conn.commit()
    profile_id = _seed_profile(jp_conn, api_key_hash="kh-test")
    jp_conn.commit()
    _seed_score(
        am_conn,
        api_key_hash="kh-test",
        client_id=profile_id,
        program_id="P-DIM-H-1",
        score=78,
    )

    r = client.get(f"/v1/me/recommendations?client_id={profile_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_id"] == profile_id
    assert body["client_label"] == "テスト顧問先"
    assert body["total"] == 1
    assert body["refreshed_at"].startswith("2026-05-12T")
    assert "Personalization scores are precomputed heuristics" in body["disclaimer"]
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert item["program_id"] == "P-DIM-H-1"
    assert item["score"] == 78
    assert item["score_breakdown"]["client_fit"] == 40
    assert item["score_breakdown"]["industry_pack"] == 25
    assert item["reasoning"]["industry_pack"] == "pack_manufacturing"
    assert "JSIC E" in item["reasoning"]["client_fit_reason"]
    assert "製造業 設備投資 watch" in item["reasoning"]["saved_searches_matched"]


def test_recommendations_empty_for_unscored_client(
    pers_client: tuple[TestClient, sqlite3.Connection, sqlite3.Connection],
) -> None:
    client, jp_conn, _am_conn = pers_client
    profile_id = _seed_profile(jp_conn, api_key_hash="kh-test")
    jp_conn.commit()
    # No am_personalization_score rows on purpose.
    r = client.get(f"/v1/me/recommendations?client_id={profile_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["refreshed_at"] is None


def test_recommendations_unknown_client_id_returns_404(
    pers_client: tuple[TestClient, sqlite3.Connection, sqlite3.Connection],
) -> None:
    client, *_ = pers_client
    r = client.get("/v1/me/recommendations?client_id=99999")
    assert r.status_code == 404, r.text
    body = r.json()
    assert "not found" in body["detail"].lower()


def test_recommendations_missing_api_key_returns_401(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ApiContext has no key_hash the route must short-circuit 401."""
    from jpintel_mcp.api import deps as deps_module
    from jpintel_mcp.api import personalization_v2 as pers_module

    jp_conn = _build_jp_conn(tmp_path)
    _build_am_conn(tmp_path)
    monkeypatch.setattr(
        "jpintel_mcp.config.settings.autonomath_db_path",
        tmp_path / "autonomath.db",
        raising=False,
    )

    app = FastAPI()
    app.include_router(pers_module.router)
    app.dependency_overrides[deps_module.require_key] = lambda: _StubApiContext(key_hash=None)
    app.dependency_overrides[deps_module.get_db] = lambda: jp_conn

    with TestClient(app) as client:
        r = client.get("/v1/me/recommendations?client_id=1")
    assert r.status_code == 401, r.text
    assert "api_key" in r.json()["detail"].lower()
    jp_conn.close()


def test_recommendations_tenant_isolation(
    pers_client: tuple[TestClient, sqlite3.Connection, sqlite3.Connection],
) -> None:
    """A profile owned by another api_key_hash is invisible (404)."""
    client, jp_conn, am_conn = pers_client
    _seed_program(jp_conn)
    # Seed under a DIFFERENT api_key_hash so the lookup misses for kh-test.
    other_profile_id = _seed_profile(jp_conn, api_key_hash="kh-other")
    jp_conn.commit()
    _seed_score(
        am_conn,
        api_key_hash="kh-other",
        client_id=other_profile_id,
        program_id="P-DIM-H-1",
        score=90,
    )
    r = client.get(f"/v1/me/recommendations?client_id={other_profile_id}")
    assert r.status_code == 404, r.text


def test_recommendations_score_breakdown_filters_non_numeric(
    pers_client: tuple[TestClient, sqlite3.Connection, sqlite3.Connection],
) -> None:
    """Defensive: non-numeric breakdown values must be silently dropped
    rather than crashing serialization (see ``score_breakdown={k: int(v)``).
    """
    client, jp_conn, am_conn = pers_client
    _seed_program(jp_conn)
    profile_id = _seed_profile(jp_conn, api_key_hash="kh-test")
    jp_conn.commit()
    am_conn.execute(
        """INSERT INTO am_personalization_score(
                api_key_hash, client_id, program_id, score,
                score_breakdown_json, reasoning_json, industry_pack,
                refreshed_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            "kh-test",
            profile_id,
            "P-DIM-H-1",
            55,
            '{"client_fit": 30, "note": "non-numeric should be filtered"}',
            "{}",
            "pack_manufacturing",
            "2026-05-12T02:00:00.000Z",
        ),
    )
    am_conn.commit()
    r = client.get(f"/v1/me/recommendations?client_id={profile_id}")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["score_breakdown"] == {"client_fit": 30}
