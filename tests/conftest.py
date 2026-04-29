import os
import sys
import tempfile

# --- must run before any jpintel_mcp import so Settings picks up test env ---
_TMP_DIR = tempfile.mkdtemp(prefix="jpintel-test-")
_DB_PATH = os.path.join(_TMP_DIR, "jpintel.db")
os.environ["JPINTEL_DB_PATH"] = _DB_PATH
os.environ["API_KEY_SALT"] = "test-salt"
os.environ["RATE_LIMIT_FREE_PER_DAY"] = "100"
# D9 burst throttle (api/middleware/rate_limit.py) is per-second and shared
# across every test on the 'testclient' IP; leaving it active would 429 the
# 6th anon call in a chain. The dedicated test file (test_rate_limit.py)
# clears this var inside its own fixtures so it CAN exercise the middleware.
os.environ.setdefault("RATE_LIMIT_BURST_DISABLED", "1")

# purge any already-imported jpintel_mcp modules so Settings re-reads env
for mod in list(sys.modules):
    if mod.startswith("jpintel_mcp"):
        del sys.modules[mod]

import json  # noqa: E402
import sqlite3  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def tmp_db_path() -> Path:
    return Path(_DB_PATH)


@pytest.fixture(scope="session")
def seeded_db(tmp_db_path: Path) -> Path:
    from jpintel_mcp.db.session import init_db

    init_db(tmp_db_path)
    now = datetime.now(UTC).isoformat()

    programs = [
        {
            "unified_id": "UNI-test-s-1",
            "primary_name": "テスト S-tier 補助金",
            "tier": "S",
            "prefecture": "東京都",
            "authority_level": "国",
            "program_kind": "補助金",
            "amount_max_man_yen": 1000,
            "funding_purpose": ["設備投資"],
            "target_types": ["sole_proprietor", "corporation"],
        },
        {
            "unified_id": "UNI-test-a-1",
            "primary_name": "青森 認定新規就農者 支援事業",
            "tier": "A",
            "prefecture": "青森県",
            "authority_level": "都道府県",
            "program_kind": "補助金",
            "amount_max_man_yen": 500,
            "funding_purpose": ["継承"],
            "target_types": ["認定新規就農者"],
        },
        {
            "unified_id": "UNI-test-b-1",
            "primary_name": "B-tier 融資 スーパーL資金",
            "tier": "B",
            "prefecture": None,
            "authority_level": "国",
            "program_kind": "融資",
            "amount_max_man_yen": 30000,
        },
        {
            "unified_id": "UNI-test-x-1",
            "primary_name": "除外されたプログラム",
            "tier": "X",
            "excluded": 1,
            "exclusion_reason": "old",
        },
    ]

    conn = sqlite3.connect(tmp_db_path)
    conn.row_factory = sqlite3.Row
    for p in programs:
        conn.execute(
            """INSERT INTO programs(
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
                p["unified_id"], p["primary_name"], None,
                p.get("authority_level"), None, p.get("prefecture"), None,
                p.get("program_kind"), None,
                p.get("amount_max_man_yen"), None, None,
                None, p.get("tier"), None, None, None,
                p.get("excluded", 0), p.get("exclusion_reason"),
                None, None,
                json.dumps(p.get("target_types", []), ensure_ascii=False),
                json.dumps(p.get("funding_purpose", []), ensure_ascii=False),
                None, None,
                None, None, now,
            ),
        )
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)",
            (p["unified_id"], p["primary_name"], "", p["primary_name"]),
        )

    conn.execute(
        """INSERT INTO exclusion_rules(
            rule_id, kind, severity, program_a, program_b,
            program_b_group_json, description, source_notes,
            source_urls_json, extra_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "excl-test-mutex", "absolute", "critical",
            "keiei-kaishi-shikin", "koyo-shuno-shikin",
            json.dumps([]), "テスト排他ルール", "test source",
            json.dumps(["https://example.com"]), None,
        ),
    )
    conn.execute(
        """INSERT INTO exclusion_rules(
            rule_id, kind, severity, program_a, program_b,
            program_b_group_json, description, source_notes,
            source_urls_json, extra_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "excl-test-prereq", "prerequisite", "critical",
            "seinen-shuno-shikin", "認定新規就農者",
            json.dumps([]), "前提条件テスト", "test source",
            json.dumps([]), None,
        ),
    )
    # Migration 051 dual-key rule: program_a is a primary_name string, but
    # program_a_uid resolves to UNI-test-s-1. Lets us assert that callers
    # passing a unified_id still trigger a name-keyed rule (P0-3 / J10).
    conn.execute(
        """INSERT INTO exclusion_rules(
            rule_id, kind, severity, program_a, program_b,
            program_b_group_json, description, source_notes,
            source_urls_json, extra_json,
            program_a_uid, program_b_uid
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "excl-test-uid-mutex", "absolute", "high",
            "テスト S-tier 補助金", "B-tier 融資 スーパーL資金",
            json.dumps([]), "uid-keyed テスト排他ルール", "test source",
            json.dumps(["https://example.com/uid"]), None,
            "UNI-test-s-1", "UNI-test-b-1",
        ),
    )
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES (?,?,?)",
        ("last_ingested_at", now, now),
    )
    conn.commit()
    conn.close()

    return tmp_db_path


@pytest.fixture(autouse=True)
def _reset_anon_rate_limit(seeded_db: Path):
    """Zero the anon_rate_limit table between tests.

    The default anon quota is 50/month. Without this, the 38 /v1 tests that
    share the TestClient IP exhaust the counter mid-suite and start getting
    429s for unrelated reasons. Scoped autouse so every test starts clean.
    Also clears the /v1/meta TTL cache so tests that mutate programs after
    an earlier meta read don't see stale counts.

    Also clears the D9 in-process token-bucket store
    (``api/middleware/rate_limit.py``). Without this every test after the
    5th anon call (or 20th authed call) on the shared 'testclient' IP
    starts to see 429 responses for unrelated reasons — the burst-throttle
    is short-window and per-process, so a single autouse reset per test
    keeps each test's bucket fresh.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM anon_rate_limit")
        c.commit()
    except sqlite3.OperationalError:
        # table may not exist until the app boots once; safe to skip
        pass
    finally:
        c.close()
    try:
        from jpintel_mcp.api.meta import _reset_meta_cache
        _reset_meta_cache()
    except ImportError:
        pass
    # Drop the per-key/IP token buckets so the burst limiter doesn't
    # accumulate across tests on the shared 'testclient' IP.
    try:
        from jpintel_mcp.api.middleware.rate_limit import (
            _reset_rate_limit_buckets,
        )
        _reset_rate_limit_buckets()
    except ImportError:
        pass
    # Drop per-endpoint per-IP buckets (e.g. /v1/programs/search 30/min cap)
    # so accumulated quota from earlier tests on the shared 'testclient' IP
    # does not 429 unrelated tests later in the run. This middleware was
    # added during Wave 21-22 and only `tests/api/test_search_fts5.py` had
    # a local autouse reset; without a global reset, every test that calls
    # /v1/programs/search after the 30th hit returns 429.
    try:
        from jpintel_mcp.api.middleware.per_ip_endpoint_limit import (
            _reset_per_ip_endpoint_buckets,
        )
        _reset_per_ip_endpoint_buckets()
    except ImportError:
        pass
    yield


@pytest.fixture(autouse=True)
def _sync_bg_task_queue(seeded_db: Path, monkeypatch):
    """Run bg_task_queue handlers inline in tests, and unify all
    `_get_email_client` / `get_client` resolution paths so a test patch
    on any one of them is observed by every handler.

    Production wires `api/_bg_task_queue.enqueue` to insert a row that an
    asyncio worker (`api/_bg_task_worker.run_worker_loop`) drains. The
    worker is NOT running under pytest, so any side-effect that the
    application code defers to the queue (welcome / dunning / key-rotated
    emails, Stripe status refresh, etc.) silently never executes — and
    assertions like `len(captured_emails) == 1` regress to 0.

    Additionally: `me._get_email_client`, `billing._get_email_client`,
    `email.get_client`, and `email.postmark.get_client` are FOUR distinct
    rebinding surfaces that all converge on the same Postmark client in
    production. The bg_task_worker handlers resolve via
    `jpintel_mcp.email.get_client` so a test that patches only
    `me._get_email_client` (legacy pattern) silently misses the
    queue-deferred path. We bridge them here: every direct lookup goes
    through a single mediator that returns the FIRST patched stub it
    finds. Test fakes pile up consistently.
    """
    from jpintel_mcp.api import _bg_task_queue as _q
    from jpintel_mcp.api import _bg_task_worker as _w
    from jpintel_mcp.api import billing as _billing
    from jpintel_mcp.api import me as _me
    from jpintel_mcp import email as _email_pkg
    from jpintel_mcp.email import postmark as _postmark

    _real_enqueue = _q.enqueue
    _real_billing_get = _billing._get_email_client
    _real_me_get = _me._get_email_client
    _real_email_get = _email_pkg.get_client
    _real_postmark_get = _postmark.get_client

    _seen_ids: set[int] = set()

    def _resolve_email_client():
        """Return whichever email-client stub the test has set, falling
        back to the production resolver.

        We only inspect the "upstream" patch surfaces (billing._get_email_client
        and me._get_email_client) — the email package surfaces themselves are
        ALWAYS bound to this resolver once the fixture runs, so re-entering
        them would recurse. The production fallback is the captured original
        `_real_postmark_get` (closed over before any patching happened).
        """
        for getter, baseline in (
            (_billing._get_email_client, _real_billing_get),
            (_me._get_email_client, _real_me_get),
        ):
            if getter is not baseline:
                return getter()
        return _real_postmark_get()

    monkeypatch.setattr(_email_pkg, "get_client", _resolve_email_client)
    monkeypatch.setattr(_postmark, "get_client", _resolve_email_client)

    # Kinds whose handler opens its own DB connection and would deadlock
    # against the caller's outstanding BEGIN IMMEDIATE writer (handler
    # path: bg_task_worker._db_connect() → UPDATE inside the handler →
    # SQLite busy_timeout-blocks until the request commits). We persist
    # the row but DON'T run the handler — tests that need the effect
    # must drain the queue manually after the request returns (the
    # billing-webhook tests do exactly this via claim_next + _dispatch_one).
    _ASYNC_ONLY_KINDS = {"stripe_status_refresh"}

    def _sync_enqueue(
        conn,
        kind,
        payload,
        dedup_key=None,
        run_at=None,
        max_attempts=5,
    ):
        row_id = _real_enqueue(
            conn,
            kind,
            payload,
            dedup_key=dedup_key,
            run_at=run_at,
            max_attempts=max_attempts,
        )
        if row_id in _seen_ids:
            return row_id
        _seen_ids.add(row_id)
        if kind in _ASYNC_ONLY_KINDS:
            return row_id
        handler = _w._HANDLERS.get(kind)
        if handler is None:
            return row_id
        # Fire the handler synchronously for the kinds whose effect tests
        # routinely assert (welcome / dunning / key_rotated / trial mails).
        # These handlers do read-only-or-additive writes that don't conflict
        # with the caller's transaction at the SQLite-row level.
        handler(payload)
        # Mark the row as 'done' so a subsequent manual queue drain inside
        # the test (e.g. test_billing_webhook_idempotency drains explicitly
        # to verify dedup row count) doesn't re-fire the same handler.
        # Use the caller's conn — opening a SECOND conn here would race
        # the caller's still-open BEGIN IMMEDIATE (the webhook handler
        # has not yet committed when sync_enqueue runs from inside its
        # request scope) and the second conn would block on busy_timeout.
        try:
            from jpintel_mcp.api._bg_task_queue import mark_done as _mark_done
            _mark_done(conn, row_id)
        except Exception:
            pass
        return row_id

    monkeypatch.setattr(_q, "enqueue", _sync_enqueue)
    yield


@pytest.fixture()
def client(seeded_db: Path) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def paid_key(seeded_db: Path) -> str:
    """A metered ("paid") API key. Use when exercising fields=full / batch /
    metered paths.

    Each test gets its own key so quota exhaustion in one test cannot leak
    into another. Callers pass it as `headers={"X-API-Key": paid_key}`.
    """
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    import uuid
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    raw = issue_key(c, customer_id="cus_test_paid", tier="paid", stripe_subscription_id=sub_id)
    c.commit()
    c.close()
    return raw
