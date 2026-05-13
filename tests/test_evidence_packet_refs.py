"""Tests for Evidence Packet endpoint references on saved-search/digest/webhook surfaces.

Section 17 step 9 of `docs/_internal/llm_resilient_business_plan_2026-04-30.md`:

    既存 saved search / webhook / digest をEvidence Packet参照つきにする

The brief is explicit on three things:
    1. NEW + MODIFIED programs in the digest carry an
       `evidence_packet_endpoint` field per row.
    2. webhook payloads for `program.amended` / `program.created` /
       `program.removed` carry `data.evidence_packet_endpoint`.
    3. Reference URL format is `/v1/evidence/packets/program/{program_id}`
       — the URL reference only, NOT the inlined packet body.

These tests verify the URL reference is populated correctly across all
three surfaces. The Evidence Packet route itself is in-flight (parallel
agent) — these tests do NOT depend on the route being live; they only
verify the cite-back URL is shaped correctly.

Schema posture: tests apply 079_saved_searches.sql + 099 channel columns +
113_weekly_digest_state.sql + 080_customer_webhooks.sql onto a tmp
jpintel.db, then exercise the digest cron + dispatcher + saved-search
endpoint directly.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


_PACKET_PREFIX = "/v1/evidence/packets/program/"


def _purge_jpintel_modules() -> None:
    """Force jpintel_mcp modules to re-read the active test DB env.

    These tests import the weekly-digest script under a one-off JPINTEL_DB_PATH.
    That script lazily imports api.programs, which in turn imports the L4 cache
    and db.session. Leaving those modules in sys.modules leaks the one-off DB
    into later API tests in the same pytest process.
    """
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp"):
            del sys.modules[mod]
    if "weekly_digest_under_test" in sys.modules:
        del sys.modules["weekly_digest_under_test"]


# ---------------------------------------------------------------------------
# Digest fixtures (mirrors test_weekly_digest.py — packet refs cross-cut)
# ---------------------------------------------------------------------------


def _apply_migration(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    cleaned_lines: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    import re

    pattern = re.compile(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
        re.IGNORECASE,
    )
    statements_to_remove: list[str] = []
    for m in pattern.finditer(cleaned):
        table, col = m.group(1), m.group(2)
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            existing = set()
        if col in existing:
            start = m.start()
            end = cleaned.find(";", start)
            if end > start:
                statements_to_remove.append(cleaned[start : end + 1])

    for stmt in statements_to_remove:
        cleaned = cleaned.replace(stmt, "")

    try:
        conn.executescript(cleaned)
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return
        raise


def _seed_programs(conn: sqlite3.Connection, programs: list[dict]) -> None:
    for p in programs:
        conn.execute(
            """INSERT OR REPLACE INTO programs(
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["unified_id"],
                p["primary_name"],
                None,
                p.get("authority_level", "国"),
                None,
                p.get("prefecture", "東京都"),
                None,
                p.get("program_kind", "補助金"),
                p.get("official_url"),
                p.get("amount_max_man_yen"),
                None,
                None,
                None,
                p.get("tier", "A"),
                None,
                None,
                None,
                p.get("excluded", 0),
                None,
                None,
                None,
                json.dumps(p.get("target_types", []), ensure_ascii=False),
                json.dumps(p.get("funding_purpose", []), ensure_ascii=False),
                None,
                None,
                None,
                None,
                p.get("updated_at", datetime.now(UTC).isoformat()),
            ),
        )


@pytest.fixture()
def weekly_db(tmp_path: Path) -> Iterator[Path]:
    """Build a fresh jpintel.db with all required tables for digest tests."""
    db_path = tmp_path / "jpintel.db"
    old_db_path = os.environ.get("JPINTEL_DB_PATH")
    old_jpcite_db_path = os.environ.get("JPCITE_DB_PATH")
    old_salt = os.environ.get("API_KEY_SALT")
    os.environ["JPINTEL_DB_PATH"] = str(db_path)
    os.environ["JPCITE_DB_PATH"] = str(db_path)
    os.environ["API_KEY_SALT"] = "test-salt"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS programs (
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
                subsidy_rate TEXT,
                trust_level TEXT,
                tier TEXT,
                coverage_score REAL,
                gap_to_tier_s_json TEXT,
                a_to_j_coverage_json TEXT,
                excluded INTEGER NOT NULL DEFAULT 0,
                exclusion_reason TEXT,
                crop_categories_json TEXT,
                equipment_category TEXT,
                target_types_json TEXT,
                funding_purpose_json TEXT,
                amount_band TEXT,
                application_window_json TEXT,
                enriched_json TEXT,
                source_mentions_json TEXT,
                updated_at TEXT,
                source_url TEXT,
                source_fetched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status INTEGER NOT NULL,
                latency_ms INTEGER,
                key_hash TEXT,
                anon_ip_hash TEXT,
                client_tag TEXT,
                is_anonymous INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        _apply_migration(conn, REPO / "scripts" / "migrations" / "079_saved_searches.sql")
        _apply_migration(conn, REPO / "scripts" / "migrations" / "099_recurring_engagement.sql")
        _apply_migration(conn, REPO / "scripts" / "migrations" / "113_weekly_digest_state.sql")

        base_now = datetime.now(UTC)
        _seed_programs(
            conn,
            [
                {
                    "unified_id": "epkt-1",
                    "primary_name": "Evidence Sample 1",
                    "prefecture": "東京都",
                    "tier": "A",
                    "amount_max_man_yen": 500.0,
                    "official_url": "https://example.gov.jp/p/1",
                    "updated_at": (base_now - timedelta(days=1)).isoformat(),
                },
                {
                    "unified_id": "epkt-2",
                    "primary_name": "Evidence Sample 2",
                    "prefecture": "東京都",
                    "tier": "A",
                    "amount_max_man_yen": 1000.0,
                    "official_url": "https://example.gov.jp/p/2",
                    "updated_at": (base_now - timedelta(days=2)).isoformat(),
                },
            ],
        )

        common_query = json.dumps(
            {"prefecture": "東京都"}, ensure_ascii=False, separators=(",", ":")
        )
        conn.execute(
            "INSERT INTO saved_searches("
            "  api_key_hash, name, query_json, frequency, notify_email,"
            "  channel_format, channel_url, last_run_at, created_at,"
            "  is_active"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "key_hash_evidence",
                "Evidence Test (週次)",
                common_query,
                "weekly",
                "evidence@example.com",
                "email",
                None,
                None,
                base_now.isoformat(),
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    _purge_jpintel_modules()

    try:
        yield db_path
    finally:
        if old_db_path is None:
            os.environ.pop("JPINTEL_DB_PATH", None)
        else:
            os.environ["JPINTEL_DB_PATH"] = old_db_path
        if old_jpcite_db_path is None:
            os.environ.pop("JPCITE_DB_PATH", None)
        else:
            os.environ["JPCITE_DB_PATH"] = old_jpcite_db_path
        if old_salt is None:
            os.environ.pop("API_KEY_SALT", None)
        else:
            os.environ["API_KEY_SALT"] = old_salt
        _purge_jpintel_modules()


def _import_digest_module():
    spec = importlib.util.spec_from_file_location(
        "weekly_digest_under_test",
        REPO / "scripts" / "cron" / "weekly_digest.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fetch_active_weekly(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT id, api_key_hash, name, query_json, frequency, notify_email, "
        "       last_run_at, created_at, last_result_signature "
        "  FROM saved_searches "
        " WHERE frequency = 'weekly' AND is_active = 1"
    ).fetchone()


# ---------------------------------------------------------------------------
# Digest tests — Section 17 step 9 wiring on weekly_digest.py
# ---------------------------------------------------------------------------


def test_digest_json_payload_includes_evidence_packet_endpoint_for_new(weekly_db: Path):
    """JSON envelope: each NEW row carries `evidence_packet_endpoint`."""
    mod = _import_digest_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_active_weekly(conn)
        assert row is not None
        outcome = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert outcome["status"] == "sent"
        payload = outcome["json_payload"]
        assert payload["summary"]["new_count"] == 2

        for hit in payload["hits"]:
            assert hit["delta"] == "NEW"
            assert "evidence_packet_endpoint" in hit, hit
            url = hit["evidence_packet_endpoint"]
            assert url.startswith(_PACKET_PREFIX), url
            assert url.endswith(hit["unified_id"]), url
            # 5-field summary head present (NOT the full packet body).
            assert "evidence_summary" in hit
            summary = hit["evidence_summary"]
            assert set(summary.keys()) == {
                "primary_name",
                "source_url",
                "fetched_at",
                "license",
                "last_amendment_diff_id",
            }
    finally:
        conn.close()


def test_digest_endpoint_is_relative_path_not_full_packet(weekly_db: Path):
    """URL reference is the relative path, NOT a JSON-inlined packet body."""
    mod = _import_digest_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_active_weekly(conn)
        outcome = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        payload = outcome["json_payload"]
        for hit in payload["hits"]:
            url = hit["evidence_packet_endpoint"]
            # Format check.
            assert url == f"/v1/evidence/packets/program/{hit['unified_id']}"
            # The hit dict must NOT carry the full packet (that would be
            # too big — the brief explicitly forbids inlining).
            assert "evidence_packet" not in hit, (
                "digest must emit URL reference only, not inlined packet"
            )
    finally:
        conn.close()


def test_digest_email_renders_endpoint_as_url(weekly_db: Path):
    """Email plaintext + html bodies render the endpoint as a clickable URL."""
    mod = _import_digest_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_active_weekly(conn)
        outcome = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        plaintext = outcome["plaintext_preview"]
        # Plaintext: "Evidence: https://jpcite.com/v1/evidence/packets/program/..."
        assert "Evidence:" in plaintext
        assert "/v1/evidence/packets/program/epkt-" in plaintext
        # The plaintext URL is fully qualified (includes the public origin)
        # so a copy-paste from a plain-text email lands on the right host.
        assert "https://jpcite.com/v1/evidence/packets/program/" in plaintext
    finally:
        conn.close()


def test_digest_modified_section_carries_endpoint(weekly_db: Path):
    """MODIFIED rows also carry `evidence_packet_endpoint`.

    We exercise the renderer directly with a synthetic diff so we are NOT
    coupled to the upstream MODIFIED-detection path (which has a separate
    pre-existing limitation around updated_at propagation through
    _build_search_response — out of scope for this Evidence Packet wire-up).
    """
    mod = _import_digest_module()
    # Synthetic diff with one NEW + one MODIFIED + one unchanged hit so we
    # can verify the renderer attaches `evidence_packet_endpoint` for all
    # three classes correctly: NEW yes, MODIFIED yes, unchanged no.
    diff = {
        "all_count": 3,
        "new": ["mod-test-new"],
        "modified": ["mod-test-mod"],
        "removed": [],
        "hits": [
            {
                "unified_id": "mod-test-new",
                "primary_name": "NEW row",
                "prefecture": "東京都",
                "amount_max_man_yen": 100.0,
                "_delta": "NEW",
                "source_url": "https://example.gov/new",
                "license": "cc-by-4.0",
                "source_fetched_at": "2026-04-30T00:00:00Z",
                "last_amendment_diff_id": None,
            },
            {
                "unified_id": "mod-test-mod",
                "primary_name": "MODIFIED row",
                "prefecture": "東京都",
                "amount_max_man_yen": 200.0,
                "_delta": "MODIFIED",
                "source_url": "https://example.gov/mod",
                "license": "cc-by-4.0",
                "source_fetched_at": "2026-04-30T00:00:00Z",
                "last_amendment_diff_id": 42,
            },
            {
                "unified_id": "mod-test-unchanged",
                "primary_name": "Unchanged row",
                "prefecture": "東京都",
                "amount_max_man_yen": 300.0,
                "_delta": "",
                "source_url": "https://example.gov/u",
                "license": "cc-by-4.0",
                "source_fetched_at": "2026-04-30T00:00:00Z",
                "last_amendment_diff_id": None,
            },
        ],
    }
    payload = mod._render_json(
        saved_name="MOD test",
        saved_id=42,
        diff=diff,
        manage_url="https://jpcite.com/dashboard.html#saved-searches",
        now_iso="2026-04-30T00:00:00Z",
    )
    by_id = {h["unified_id"]: h for h in payload["hits"]}
    # NEW + MODIFIED carry the endpoint reference.
    assert "evidence_packet_endpoint" in by_id["mod-test-new"]
    assert by_id["mod-test-new"]["evidence_packet_endpoint"].endswith("mod-test-new")
    assert "evidence_packet_endpoint" in by_id["mod-test-mod"]
    assert by_id["mod-test-mod"]["evidence_packet_endpoint"].endswith("mod-test-mod")
    # Unchanged rows DO NOT carry the endpoint (only NEW/MODIFIED need
    # cite-back follow-up).
    assert "evidence_packet_endpoint" not in by_id["mod-test-unchanged"]

    # 5-field summary is populated for NEW + MODIFIED (per the brief).
    new_summary = by_id["mod-test-new"]["evidence_summary"]
    assert new_summary["primary_name"] == "NEW row"
    assert new_summary["source_url"] == "https://example.gov/new"
    assert new_summary["license"] == "cc-by-4.0"
    assert new_summary["fetched_at"] == "2026-04-30T00:00:00Z"
    assert new_summary["last_amendment_diff_id"] is None
    mod_summary = by_id["mod-test-mod"]["evidence_summary"]
    assert mod_summary["last_amendment_diff_id"] == 42


# ---------------------------------------------------------------------------
# Webhook dispatcher tests — Section 17 step 9 wiring on dispatch_webhooks.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def webhook_key_local(seeded_db: Path) -> str:
    """Authenticated paid key for webhook tests."""
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_evidence_test",
        tier="paid",
        stripe_subscription_id="sub_evidence_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_customer_webhooks_table(seeded_db: Path):
    """Apply migration 080 onto the test DB and clear rows between cases."""
    sql_path = REPO / "scripts" / "migrations" / "080_customer_webhooks.sql"
    sql = sql_path.read_text(encoding="utf-8")
    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.execute("DELETE FROM webhook_deliveries")
        c.execute("DELETE FROM customer_webhooks")
        c.execute("DELETE FROM programs WHERE unified_id LIKE 'EP-%'")
        c.commit()
    finally:
        c.close()
    yield


class _MockResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.is_success = 200 <= status_code < 300


class _MockClient:
    def __init__(self, responses=None):
        self._responses = list(responses or [(200, "")])
        self._idx = 0
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def post(self, url, *, content=None, headers=None, timeout=None, **_):
        self.calls.append((url, content, dict(headers or {})))
        idx = min(self._idx, len(self._responses) - 1)
        self._idx += 1
        resp = self._responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return _MockResponse(*resp)


def _backdate_existing(db_path: Path) -> None:
    c = sqlite3.connect(db_path)
    c.execute("UPDATE programs SET updated_at = '1990-01-01T00:00:00+00:00'")
    c.commit()
    c.close()


def _seed_program(db_path: Path, unified_id: str = "EP-1") -> None:
    c = sqlite3.connect(db_path)
    c.execute(
        "INSERT OR REPLACE INTO programs("
        "  unified_id, primary_name, official_url, source_url, prefecture,"
        "  program_kind, tier, excluded, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))",
        (
            unified_id,
            "Evidence Webhook Program",
            "https://example.gov/p",
            "https://example.gov/p/source",
            "全国",
            "subsidy",
            "A",
        ),
    )
    c.commit()
    c.close()


def _register_webhook(
    db_path: Path,
    api_key_hash: str,
    url: str,
    event_types: list[str],
    secret: str = "whsec_evidence",
) -> int:
    c = sqlite3.connect(db_path)
    cur = c.execute(
        "INSERT INTO customer_webhooks(api_key_hash, url, event_types_json, "
        "secret_hmac, status, failure_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', 0, datetime('now'), datetime('now'))",
        (api_key_hash, url, json.dumps(event_types), secret),
    )
    wid = cur.lastrowid
    c.commit()
    c.close()
    return wid


def test_webhook_program_created_payload_carries_evidence_endpoint(
    seeded_db,
    webhook_key_local,
    monkeypatch,
):
    """program.created webhook payload includes data.evidence_packet_endpoint."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key_local)
    secret = "whsec_evidence_created"
    _backdate_existing(seeded_db)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/ep",
        ["program.created"],
        secret=secret,
    )
    _seed_program(seeded_db, unified_id="EP-CREATED-1")

    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    summary = dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )
    assert summary["deliveries_succeeded"] == 1

    sent_url, sent_body, sent_headers = mock.calls[0]
    payload = json.loads(sent_body.decode())
    assert payload["event_type"] == "program.created"
    data = payload["data"]
    # Section 17 step 9 — required keys per the brief.
    assert data["entity_id"] == "EP-CREATED-1"
    assert data["evidence_packet_endpoint"] == ("/v1/evidence/packets/program/EP-CREATED-1")
    assert "diff_id" in data
    assert "field_name" in data
    assert "source_url" in data
    assert "corpus_snapshot_id" in data

    # The full packet body MUST NOT be inlined.
    assert "evidence_packet" not in data, (
        "webhook payload must emit URL reference only, not the inlined packet"
    )

    # HMAC still matches over the augmented body.
    expected_sig = "hmac-sha256=" + hmac.new(secret.encode(), sent_body, hashlib.sha256).hexdigest()
    assert sent_headers["X-Jpcite-Signature"] == expected_sig
    assert sent_headers["X-Zeimu-Signature"] == expected_sig


def test_webhook_evidence_endpoint_is_relative_path(
    seeded_db,
    webhook_key_local,
    monkeypatch,
):
    """The reference URL is `/v1/evidence/packets/program/{program_id}`."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key_local)
    _backdate_existing(seeded_db)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/fmt",
        ["program.created"],
        secret="whsec_fmt",
    )
    _seed_program(seeded_db, unified_id="EP-FMT-7")

    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    _sent_url, sent_body, _sent_headers = mock.calls[0]
    payload = json.loads(sent_body.decode())
    endpoint = payload["data"]["evidence_packet_endpoint"]
    # Exact format match per the brief.
    assert endpoint == "/v1/evidence/packets/program/EP-FMT-7"
    # Relative path (not absolute URL); the customer's HTTP client resolves
    # against the API host they registered the webhook for.
    assert not endpoint.startswith("http://")
    assert not endpoint.startswith("https://")


def test_webhook_program_amended_payload_carries_evidence_endpoint(
    seeded_db,
    webhook_key_local,
    monkeypatch,
    tmp_path,
):
    """program.amended payload carries entity_id + diff_id + endpoint."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key_local)
    _backdate_existing(seeded_db)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/amended",
        ["program.amended"],
        secret="whsec_amended",
    )

    # Build a tmp autonomath.db with a single am_amendment_diff row.
    am_path = tmp_path / "autonomath.db"
    am_conn = sqlite3.connect(str(am_path))
    am_conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_amendment_diff (
            diff_id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL,
            source_url TEXT
        );
        INSERT INTO am_amendment_diff(
            diff_id, entity_id, field_name, prev_value, new_value,
            detected_at, source_url
        ) VALUES (
            42, 'EP-AMENDED-1', 'amount_max_man_yen', '500', '1000',
            datetime('now'), 'https://example.gov/p/amended'
        );
        """
    )
    am_conn.commit()
    am_conn.close()

    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        autonomath_db=am_path,
        jpintel_db=seeded_db,
    )
    assert len(mock.calls) >= 1, "expected at least one program.amended delivery"

    _sent_url, sent_body, _sent_headers = mock.calls[0]
    payload = json.loads(sent_body.decode())
    assert payload["event_type"] == "program.amended"
    data = payload["data"]
    # Per the brief — these MUST be present.
    assert data["entity_id"] == "EP-AMENDED-1"
    assert data["diff_id"] == 42
    assert data["field_name"] == "amount_max_man_yen"
    assert data["source_url"] == "https://example.gov/p/amended"
    assert "corpus_snapshot_id" in data
    assert data["evidence_packet_endpoint"] == ("/v1/evidence/packets/program/EP-AMENDED-1")
    # No full packet body inlined.
    assert "evidence_packet" not in data


def test_webhook_backwards_compat_extra_field_only(
    seeded_db,
    webhook_key_local,
    monkeypatch,
):
    """Adding `evidence_packet_endpoint` is JSON-additive — existing fields
    on data still present and unchanged."""
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import dispatch_webhooks as dw

    key_hash = hash_api_key(webhook_key_local)
    _backdate_existing(seeded_db)
    _register_webhook(
        seeded_db,
        key_hash,
        "https://hooks.example.com/compat",
        ["program.created"],
        secret="whsec_compat",
    )
    _seed_program(seeded_db, unified_id="EP-COMPAT-1")

    mock = _MockClient(responses=[(200, "")])
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "Client", lambda *a, **k: mock)
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._bill_one_delivery",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.cron.dispatch_webhooks._is_safe_webhook",
        lambda url: (True, None),
    )

    dw.run(
        since_iso="2000-01-01T00:00:00+00:00",
        dry_run=False,
        jpintel_db=seeded_db,
    )

    _sent_url, sent_body, _sent_headers = mock.calls[0]
    payload = json.loads(sent_body.decode())
    data = payload["data"]
    # Pre-existing fields must STILL be present (no breaking removals).
    assert data["unified_id"] == "EP-COMPAT-1"
    assert data["name"] == "Evidence Webhook Program"
    assert data["prefecture"] == "全国"
    assert data["program_kind"] == "subsidy"
    assert data["tier"] == "A"
    # New field added on top.
    assert "evidence_packet_endpoint" in data


# ---------------------------------------------------------------------------
# Saved-search "run now" path — /v1/me/saved_searches/{id}/results
# ---------------------------------------------------------------------------


def test_saved_search_results_includes_evidence_endpoint(
    client,
    webhook_key_local,
    seeded_db,
):
    """GET /v1/me/saved_searches/{id}/results — each row carries the URL ref."""
    # Apply 079 + 099 to the seeded DB so saved_searches table exists.
    repo = REPO
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"
    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        c.execute("DELETE FROM saved_searches")
        c.commit()
    finally:
        c.close()

    # Create a saved search via the API.
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": webhook_key_local},
        json={
            "name": "Evidence Run-Now Test",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "evidence@example.com",
        },
    )
    assert r.status_code == 201, r.text
    saved_id = r.json()["id"]

    # Run it now.
    rr = client.get(
        f"/v1/me/saved_searches/{saved_id}/results",
        headers={"X-API-Key": webhook_key_local},
    )
    assert rr.status_code == 200, rr.text
    body = rr.json()
    # The endpoint must surface corpus_snapshot_id (existing) AND
    # evidence_packet_endpoint per row (new).
    assert "corpus_snapshot_id" in body
    assert "results" in body
    # Even with zero seeded matches the response shape stays valid.
    if body["results"]:
        for row in body["results"]:
            program_id = row.get("unified_id")
            if program_id:
                assert "evidence_packet_endpoint" in row, row
                assert row["evidence_packet_endpoint"] == (
                    f"/v1/evidence/packets/program/{program_id}"
                )
