"""Tests for GET /v1/intel/program/{program_id}/full — composite bundle.

Coverage:
    1. Happy path — every requested section landed in the response, the
       envelope shape is correct (program_meta + eligibility + amendments
       + adoptions + similar + citations + audit_proof), corpus_snapshot_id
       + audit_seal + _disclaimer + _billing_unit:1 are present.
    2. include_sections filter — caller can strip heavy sections; the
       response only carries the requested keys.
    3. 404 — unknown program_id returns a structured 404 detail (not 500).
    4. Envelope corpus_snapshot_id present — auditor reproducibility field
       is wired through attach_corpus_snapshot.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def seeded_program_full_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> tuple[Path, str]:
    """Build a tmp autonomath.db slice carrying program_full substrate.

    Returns (db_path, target_program_id).

    Seeds:
      * `programs` (autonomath-side) with the target program.
      * `entity_id_map` mapping UNI- ↔ program: forms.
      * `am_program_eligibility_predicate` — 2 predicate rows.
      * `am_amendment_diff` — 2 amendment rows in scope.
      * `jpi_adoption_records` — 3 adoption rows for the target program.
      * `am_adopted_company_features` — 1 enrichment row.
      * `am_recommended_programs` — 2 houjin recommended into the target
        program AND into 1 peer program (so co-occurrence > 0).
      * `program_law_refs` — 2 law citations.
      * `nta_tsutatsu_index` — 2 通達 rows.
      * `audit_merkle_anchor` — 1 daily anchor.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            aliases_json TEXT,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            program_kind TEXT,
            official_url TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate REAL,
            tier TEXT,
            excluded INTEGER DEFAULT 0,
            source_url TEXT,
            source_fetched_at TEXT,
            application_window_json TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE entity_id_map (
            jpi_unified_id   TEXT NOT NULL,
            am_canonical_id  TEXT NOT NULL,
            match_method     TEXT NOT NULL,
            confidence       REAL NOT NULL,
            matched_at       TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (jpi_unified_id, am_canonical_id)
        );
        CREATE TABLE am_program_eligibility_predicate (
            predicate_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            program_unified_id    TEXT NOT NULL,
            predicate_kind        TEXT NOT NULL,
            operator              TEXT NOT NULL,
            value_text            TEXT,
            value_num             REAL,
            value_json            TEXT,
            is_required           INTEGER NOT NULL DEFAULT 1,
            source_url            TEXT,
            source_clause_quote   TEXT,
            extracted_at          TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE am_amendment_diff (
            diff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id      TEXT NOT NULL,
            field_name     TEXT NOT NULL,
            prev_value     TEXT,
            new_value      TEXT,
            prev_hash      TEXT,
            new_hash       TEXT,
            detected_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url     TEXT
        );
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            houjin_bangou TEXT,
            program_id TEXT,
            program_id_hint TEXT,
            program_name_raw TEXT,
            company_name_raw TEXT,
            announced_at TEXT,
            amount_granted_yen INTEGER,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.85
        );
        CREATE TABLE am_adopted_company_features (
            houjin_bangou           TEXT PRIMARY KEY,
            adoption_count          INTEGER NOT NULL DEFAULT 0,
            distinct_program_count  INTEGER NOT NULL DEFAULT 0,
            first_adoption_at       TEXT,
            last_adoption_at        TEXT,
            dominant_jsic_major     TEXT,
            dominant_prefecture     TEXT,
            enforcement_count       INTEGER NOT NULL DEFAULT 0,
            invoice_registered      INTEGER NOT NULL DEFAULT 0,
            loan_count              INTEGER NOT NULL DEFAULT 0,
            credibility_score       REAL,
            computed_at             TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE am_recommended_programs (
            houjin_bangou      TEXT NOT NULL,
            program_unified_id TEXT NOT NULL,
            rank               INTEGER NOT NULL,
            score              REAL NOT NULL,
            reason_json        TEXT,
            computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            source_snapshot_id TEXT,
            PRIMARY KEY (houjin_bangou, program_unified_id)
        );
        CREATE TABLE program_law_refs (
            program_unified_id TEXT NOT NULL,
            law_unified_id TEXT NOT NULL,
            ref_kind TEXT NOT NULL,
            article_citation TEXT,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.9,
            PRIMARY KEY(program_unified_id, law_unified_id, ref_kind, article_citation)
        );
        CREATE TABLE nta_tsutatsu_index (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            code                    TEXT NOT NULL UNIQUE,
            law_canonical_id        TEXT NOT NULL,
            article_number          TEXT NOT NULL,
            title                   TEXT,
            body_excerpt            TEXT,
            parent_code             TEXT,
            source_url              TEXT NOT NULL,
            last_amended            TEXT,
            refreshed_at            TEXT NOT NULL
        );
        CREATE TABLE audit_merkle_anchor (
            daily_date          TEXT PRIMARY KEY,
            row_count           INTEGER NOT NULL,
            merkle_root         TEXT NOT NULL,
            ots_proof           BLOB,
            github_commit_sha   TEXT,
            twitter_post_id     TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        """
    )

    target_uni = "UNI-pf-target-1"
    target_am = "program:test:pf-target-1"
    peer_uni = "UNI-pf-peer-1"

    # Programs
    conn.executemany(
        "INSERT INTO programs (unified_id, primary_name, tier, prefecture, "
        " authority_name, authority_level, program_kind, source_url, "
        " amount_max_man_yen, amount_min_man_yen, application_window_json, "
        " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                target_uni,
                "テスト DX 補助金 (program_full)",
                "S",
                "東京都",
                "経済産業省",
                "国",
                "補助金",
                "https://example.go.jp/koubo/v1.pdf",
                1500.0,
                100.0,
                '{"open_at":"2026-04-01","close_at":"2026-09-30"}',
                "2026-05-05T00:00:00",
            ),
            (
                peer_uni,
                "ピア補助金",
                "A",
                "東京都",
                "経済産業省",
                "国",
                "補助金",
                "https://example.go.jp/peer/v1.pdf",
                500.0,
                50.0,
                None,
                "2026-05-05T00:00:00",
            ),
        ],
    )

    # entity_id_map
    conn.execute(
        "INSERT INTO entity_id_map (jpi_unified_id, am_canonical_id, "
        " match_method, confidence) VALUES (?, ?, ?, ?)",
        (target_uni, target_am, "exact_name", 1.0),
    )

    # Eligibility predicates (2 rows)
    conn.executemany(
        "INSERT INTO am_program_eligibility_predicate "
        "(program_unified_id, predicate_kind, operator, value_text, "
        " value_num, is_required, source_url) VALUES (?,?,?,?,?,?,?)",
        [
            (
                target_uni,
                "capital_max",
                "<=",
                None,
                300_000_000.0,
                1,
                "https://example.go.jp/koubo/v1.pdf",
            ),
            (
                target_uni,
                "employee_max",
                "<=",
                None,
                300.0,
                1,
                "https://example.go.jp/koubo/v1.pdf",
            ),
        ],
    )

    # Amendment diff (2 rows for target + 1 for unrelated entity)
    conn.executemany(
        "INSERT INTO am_amendment_diff "
        "(entity_id, field_name, prev_value, new_value, detected_at, source_url) "
        "VALUES (?,?,?,?,?,?)",
        [
            (
                target_am,
                "eligibility_text",
                "中小企業のみ",
                "中小企業 + 小規模事業者",
                "2026-03-15T10:00:00",
                "https://example.go.jp/koubo/v2.pdf",
            ),
            (
                target_am,
                "amount_max_man_yen",
                "1000",
                "1500",
                "2026-06-20T10:00:00",
                "https://example.go.jp/koubo/v3.pdf",
            ),
            # Unrelated entity — must NOT appear.
            (
                "program:other:not-target",
                "amount_max_man_yen",
                "100",
                "200",
                "2026-04-15T10:00:00",
                None,
            ),
        ],
    )

    # Adoption records
    conn.executemany(
        "INSERT INTO jpi_adoption_records "
        "(houjin_bangou, program_id, company_name_raw, announced_at, "
        " amount_granted_yen, source_url, fetched_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (
                "9999999999991",
                target_uni,
                "テスト株式会社A",
                "2026-07-01T00:00:00",
                10_000_000,
                "https://example.go.jp/saitaku.pdf",
                "2026-07-02T00:00:00",
            ),
            (
                "9999999999992",
                target_uni,
                "テスト株式会社B",
                "2026-08-01T00:00:00",
                5_000_000,
                "https://example.go.jp/saitaku.pdf",
                "2026-08-02T00:00:00",
            ),
            (
                "9999999999993",
                target_uni,
                "テスト株式会社C",
                "2026-06-01T00:00:00",
                None,
                "https://example.go.jp/saitaku.pdf",
                "2026-06-02T00:00:00",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO am_adopted_company_features "
        "(houjin_bangou, adoption_count, last_adoption_at, "
        " dominant_prefecture, credibility_score) VALUES (?,?,?,?,?)",
        ("9999999999991", 5, "2026-07-01T00:00:00", "東京都", 0.92),
    )

    # Recommended programs — 2 houjin recommended into target + peer
    # so co-occurrence > 0 for the peer.
    conn.executemany(
        "INSERT INTO am_recommended_programs "
        "(houjin_bangou, program_unified_id, rank, score) VALUES (?,?,?,?)",
        [
            ("0100001000001", target_uni, 1, 0.91),
            ("0100001000001", peer_uni, 2, 0.71),
            ("0100001000002", target_uni, 1, 0.85),
            ("0100001000002", peer_uni, 2, 0.65),
        ],
    )

    # Law refs
    conn.executemany(
        "INSERT INTO program_law_refs "
        "(program_unified_id, law_unified_id, ref_kind, article_citation, "
        " source_url, fetched_at, confidence) VALUES (?,?,?,?,?,?,?)",
        [
            (
                target_uni,
                "LAW-aaaa111111",
                "authority",
                "第5条第2項",
                "https://elaws.e-gov.go.jp/example",
                "2026-04-01T00:00:00",
                0.95,
            ),
            (
                target_uni,
                "LAW-bbbb222222",
                "eligibility",
                "第10条",
                "https://elaws.e-gov.go.jp/example2",
                "2026-04-01T00:00:00",
                0.90,
            ),
        ],
    )

    # Tsutatsu (2 rows)
    conn.executemany(
        "INSERT INTO nta_tsutatsu_index "
        "(code, law_canonical_id, article_number, title, source_url, refreshed_at) "
        "VALUES (?,?,?,?,?,?)",
        [
            (
                "法基通-9-2-3",
                "law:hojin-zei-tsutatsu",
                "9-2-3",
                "資本金等の額",
                "https://www.nta.go.jp/example/9-2-3",
                "2026-04-01T00:00:00",
            ),
            (
                "消基通-5-1-1",
                "law:shouhi-zei-tsutatsu",
                "5-1-1",
                "課税対象",
                "https://www.nta.go.jp/example/5-1-1",
                "2026-04-01T00:00:00",
            ),
        ],
    )

    # Audit anchor
    conn.execute(
        "INSERT INTO audit_merkle_anchor "
        "(daily_date, row_count, merkle_root, ots_proof, github_commit_sha) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "2026-05-04",
            42,
            "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            b"\x00\x01ots-proof",
            "abc123def456abc123def456abc123def456abcd",
        ),
    )

    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)

    # corpus_snapshot cache is process-local — clear so each test sees the
    # fresh tmp DB instead of a stale snapshot from an earlier test.
    from jpintel_mcp.api._corpus_snapshot import _reset_cache_for_tests

    _reset_cache_for_tests()

    return db_path, target_uni


@pytest.fixture()
def program_full_client(seeded_db: Path, seeded_program_full_db) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test 1: Happy path — every section + envelope shape
# ---------------------------------------------------------------------------


def test_program_full_happy_path(program_full_client: TestClient, seeded_program_full_db) -> None:
    _db, program_id = seeded_program_full_db
    r = program_full_client.get(f"/v1/intel/program/{program_id}/full")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level shape
    assert body["program_id"] == program_id
    assert body["max_per_section"] == 5
    assert body["_billing_unit"] == 1
    assert isinstance(body["_disclaimer"], str)
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert "data_quality" in body
    assert isinstance(body["data_quality"]["missing_tables"], list)
    # All 7 default sections present.
    for key in (
        "program_meta",
        "eligibility_predicate",
        "amendments_recent",
        "adoptions_top",
        "similar_programs",
        "citations",
        "audit_proof",
    ):
        assert key in body, f"missing section: {key}"

    # program_meta shape
    meta = body["program_meta"]
    assert meta["id"] == program_id
    assert meta["name"]
    assert meta["tier"] == "S"
    assert meta["primary_url"]
    assert meta["expected_amount_max"] == 1500 * 10_000

    # eligibility — 2 predicate rows seeded
    elig = body["eligibility_predicate"]
    assert isinstance(elig, list)
    assert len(elig) == 2
    kinds = {row["kind"] for row in elig}
    assert "capital_max" in kinds
    assert "employee_max" in kinds

    # amendments — 2 rows in scope (1 unrelated row excluded)
    amends = body["amendments_recent"]
    assert isinstance(amends, list)
    assert len(amends) == 2
    # Sorted by date desc.
    dates = [a["date"] for a in amends]
    assert dates == sorted(dates, reverse=True)
    fields = {a["field_name"] for a in amends}
    assert fields == {"eligibility_text", "amount_max_man_yen"}

    # adoptions — 3 rows seeded, sorted by amount desc (NULLs last)
    adopts = body["adoptions_top"]
    assert isinstance(adopts, list)
    assert len(adopts) == 3
    assert adopts[0]["amount"] == 10_000_000
    assert adopts[1]["amount"] == 5_000_000
    # NULL amount lands last.
    assert adopts[2]["amount"] is None
    # Year extraction works.
    assert adopts[0]["year"] == 2026
    # Credibility enrichment for houjin 9999999999991.
    enriched = next(a for a in adopts if a["houjin_id"] == "9999999999991")
    assert enriched.get("credibility_score") == 0.92
    assert enriched.get("total_adoption_count") == 5

    # similar — peer should appear via co-occurrence walk
    sim = body["similar_programs"]
    assert isinstance(sim, list)
    assert len(sim) >= 1
    peer_row = next(s for s in sim if s["program_id"] == "UNI-pf-peer-1")
    assert peer_row["co_occurrence_count"] == 2
    assert peer_row["name"] == "ピア補助金"

    # citations — law + tsutatsu populated, hanrei is []
    cits = body["citations"]
    assert isinstance(cits, dict)
    assert "law" in cits and "tsutatsu" in cits and "hanrei" in cits
    assert len(cits["law"]) == 2
    assert len(cits["tsutatsu"]) == 2
    assert cits["hanrei"] == []

    # audit_proof — anchor surfaced with ots + github URLs
    proof = body["audit_proof"]
    assert proof["merkle_root"].startswith("sha256:")
    assert proof["github_sha"].startswith("abc123")
    assert proof["github_commit_url"].startswith("https://github.com/")
    assert proof["ots_url"] == "https://opentimestamps.org/"
    assert proof["last_anchored"] == "2026-05-04"


# ---------------------------------------------------------------------------
# Test 2: include_sections filter narrows the response
# ---------------------------------------------------------------------------


def test_program_full_include_sections_filter(
    program_full_client: TestClient, seeded_program_full_db
) -> None:
    _db, program_id = seeded_program_full_db
    r = program_full_client.get(
        f"/v1/intel/program/{program_id}/full",
        params=[
            ("include_sections", "meta"),
            ("include_sections", "audit_proof"),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["include_sections"] == ["meta", "audit_proof"]
    # Only the requested sections appear.
    assert "program_meta" in body
    assert "audit_proof" in body
    for stripped in (
        "eligibility_predicate",
        "amendments_recent",
        "adoptions_top",
        "similar_programs",
        "citations",
    ):
        assert stripped not in body, f"{stripped} should not appear when stripped"


# ---------------------------------------------------------------------------
# Test 3: 404 for unknown program_id
# ---------------------------------------------------------------------------


def test_program_full_unknown_program_returns_404(
    program_full_client: TestClient, seeded_program_full_db
) -> None:
    r = program_full_client.get("/v1/intel/program/UNI-does-not-exist-anywhere/full")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert "UNI-does-not-exist-anywhere" in detail
    assert "programs" in detail.lower() or "search" in detail.lower()


# ---------------------------------------------------------------------------
# Test 4: corpus_snapshot_id present (auditor reproducibility envelope)
# ---------------------------------------------------------------------------


def test_program_full_corpus_snapshot_id_present(
    program_full_client: TestClient, seeded_program_full_db
) -> None:
    _db, program_id = seeded_program_full_db
    r = program_full_client.get(
        f"/v1/intel/program/{program_id}/full",
        params=[("include_sections", "meta")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # attach_corpus_snapshot inserts both keys.
    assert "corpus_snapshot_id" in body
    assert body["corpus_snapshot_id"]
    assert "corpus_checksum" in body
    assert body["corpus_checksum"].startswith("sha256:") or body["corpus_checksum"].startswith(
        "unknown"
    )


# ---------------------------------------------------------------------------
# Test 5: invalid include_sections value returns 422
# ---------------------------------------------------------------------------


def test_program_full_invalid_include_sections_returns_422(
    program_full_client: TestClient, seeded_program_full_db
) -> None:
    _db, program_id = seeded_program_full_db
    r = program_full_client.get(
        f"/v1/intel/program/{program_id}/full",
        params=[("include_sections", "not_a_real_section")],
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_include_sections"
    assert "not_a_real_section" in str(detail)


# ---------------------------------------------------------------------------
# Test 6: paid final cap failure fails closed and does not bill
# ---------------------------------------------------------------------------


def test_program_full_paid_final_cap_failure_returns_503_without_usage_event(
    program_full_client: TestClient,
    seeded_program_full_db,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _db, program_id = seeded_program_full_db

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    import jpintel_mcp.api.deps as deps

    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = program_full_client.get(
        f"/v1/intel/program/{program_id}/full",
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, "intel.program_full"),
        ).fetchone()
    finally:
        conn.close()
    assert n == 0
