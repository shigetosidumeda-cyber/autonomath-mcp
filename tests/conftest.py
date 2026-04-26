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
