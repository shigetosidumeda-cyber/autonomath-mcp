import contextlib
import os
import sys
import tempfile

# --- must run before any jpintel_mcp import so Settings picks up test env ---
_TMP_DIR = tempfile.mkdtemp(prefix="jpintel-test-")
_DB_PATH = os.path.join(_TMP_DIR, "jpintel.db")
_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
_AUTONOMATH_DB_PATH = os.environ.get(
    "JPCITE_AUTONOMATH_DB_PATH",
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        os.path.join(_REPO_ROOT, "autonomath.db"),
    ),
)
_AUTONOMATH_GRAPH_DB_PATH = os.environ.get(
    "JPCITE_AUTONOMATH_GRAPH_DB_PATH",
    os.environ.get(
        "AUTONOMATH_GRAPH_DB_PATH",
        os.path.join(_REPO_ROOT, "graph.sqlite"),
    ),
)
os.environ["JPINTEL_DB_PATH"] = _DB_PATH
os.environ["JPCITE_DB_PATH"] = _DB_PATH
os.environ["API_KEY_SALT"] = "test-salt"
os.environ["RATE_LIMIT_FREE_PER_DAY"] = "100"
# D9 burst throttle (api/middleware/rate_limit.py) is per-second and shared
# across every test on the 'testclient' IP; leaving it active would 429 the
# 6th anon call in a chain. The dedicated test file (test_rate_limit.py)
# clears this var inside its own fixtures so it CAN exercise the middleware.
os.environ.setdefault("RATE_LIMIT_BURST_DISABLED", "1")
# Cluster A (R8 audit 2026-05-07): the experimental router include in
# `api/main.py:_include_experimental_router` defaults the gate to OFF, so
# routes such as `/v1/intel/*`, `/v1/artifacts/*`, `/v1/calculator/savings`
# return 404 `route_not_found` under TestClient unless the env flag is set
# before app import. R8_PYTEST_BASELINE_FAIL_AUDIT counted 108 fails on
# this single fingerprint across 23 test files. Live re-run with the flag
# set converts every one of them back to PASS, so we activate it here at
# module-import scope (fixture scope is too late because `create_app()` is
# called by client fixtures that import the module before the fixture body
# runs). Production boot is unaffected: the flag is read fresh from the
# real env on Fly.io, where it is intentionally off until each surface is
# launch-cleared. Test-session-only.
os.environ.setdefault("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "1")
os.environ.setdefault("JPCITE_EXPERIMENTAL_API_ENABLED", "1")
# Wave 21-23 default-ON gates: source already defaults these to ON
# (`composition_tools.py:_ENABLED`, `wave22_tools.py:_ENABLED`,
# `industry_packs.py:_ENABLED` all read `os.environ.get(..., "1")`), but
# pinning them here keeps the flag matrix explicit and makes test-runner
# overrides obvious. Re-pinning to "1" is a no-op when source default is
# already "1"; if a future config change flips a default to "0", these
# lines keep the test surface stable instead of silently regressing.
#
# Wave 47.A flip (2026-05-13): we now mirror each AUTONOMATH_* setdefault
# with its JPCITE_* canonical counterpart so the `_jpcite_env_bridge.get_flag`
# helper finds the canonical key first and does NOT emit a DeprecationWarning
# during normal test runs. Operators who explicitly set ONLY the legacy key
# (no JPCITE_ mirror) still see the warning — that is the desired signal that
# tells them to flip to the canonical name. Both names continue to work.
os.environ.setdefault("AUTONOMATH_COMPOSITION_ENABLED", "1")
os.environ.setdefault("JPCITE_COMPOSITION_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE22_ENABLED", "1")
os.environ.setdefault("JPCITE_WAVE22_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1")
os.environ.setdefault("JPCITE_INDUSTRY_PACKS_ENABLED", "1")
# Snapshot tool (DEEP-22) — config.py defaults autonomath_snapshot_enabled
# to True; mirror at env-var layer so any os.getenv-style reader (e.g.
# autonomath_tools.snapshot_tool) sees a truthy value under TestClient.
os.environ.setdefault("AUTONOMATH_SNAPSHOT_ENABLED", "1")
os.environ.setdefault("JPCITE_SNAPSHOT_ENABLED", "1")
# AUTONOMATH_REASONING_ENABLED + AUTONOMATH_36_KYOTEI_ENABLED stay OFF
# by default (production posture per CLAUDE.md "broken-tool gates" /
# 36協定 launch gate). Tests that need them set them locally.

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


def _restore_autonomath_paths() -> None:
    os.environ["AUTONOMATH_DB_PATH"] = _AUTONOMATH_DB_PATH
    # Mirror the canonical JPCITE_* name so `get_flag` finds it first and
    # the legacy-fallback DeprecationWarning does not fire during tests.
    # Both names continue to resolve to the same path.
    os.environ["JPCITE_AUTONOMATH_DB_PATH"] = _AUTONOMATH_DB_PATH
    os.environ["AUTONOMATH_GRAPH_DB_PATH"] = _AUTONOMATH_GRAPH_DB_PATH
    os.environ["JPCITE_AUTONOMATH_GRAPH_DB_PATH"] = _AUTONOMATH_GRAPH_DB_PATH
    try:
        from jpintel_mcp.config import settings

        settings.autonomath_db_path = Path(_AUTONOMATH_DB_PATH)
        _sync_imported_settings_singleton(settings)
    except Exception:
        pass
    module = sys.modules.get("jpintel_mcp.mcp.autonomath_tools.db")
    if module is not None:
        try:
            module.AUTONOMATH_DB_PATH = Path(_AUTONOMATH_DB_PATH)
            module.GRAPH_DB_PATH = Path(_AUTONOMATH_GRAPH_DB_PATH)
        except Exception:
            pass


def _reset_autonomath_state() -> None:
    """Drop every known process-local cache surface so tests don't bleed.

    R8 deep audit (2026-05-07) profiled ~85 collection-order failures whose
    in-isolation runs PASS. Root cause was distributed: each surface kept its
    own dict/lru_cache/lock-guarded bucket, and the prior reset list only hit
    5 of them. Pollution chains looked like:

      test_X monkeypatches settings → test_Y inherits stale lru_cache →
      _load_*_cached returns wrong path → row count drift → assertion fail.

    The list below is the full, audited set. Each entry is best-effort:
    a missing module or a not-yet-imported reset helper is silently skipped
    so the fixture stays cheap. Adding a new in-memory cache to the codebase?
    Append the (module, callable) pair here and pollution stays bounded.

    Tuple shape:
        (module_name, attr_name, kind)
    where kind ∈ {"call" — invoke as ()-arity reset, "cache_clear" — call
    .cache_clear() on the attr (lru_cache surfaces)}.
    """
    targets: tuple[tuple[str, str, str], ...] = (
        # Autonomath-side caches (already covered pre-hardening).
        ("jpintel_mcp.mcp.autonomath_tools.db", "close_all", "call"),
        ("jpintel_mcp.api.evidence", "reset_composer", "call"),
        ("jpintel_mcp.services.evidence_packet", "_reset_cache_for_tests", "call"),
        ("jpintel_mcp.api.funding_stack", "reset_checker", "call"),
        ("jpintel_mcp.mcp.autonomath_tools.funding_stack_tools", "_reset_checker", "call"),
        # Snapshot helper (DEEP-22 / Wave 22 — corpus_snapshot_id must
        # re-derive after a test mutates the underlying corpus).
        ("jpintel_mcp.mcp.autonomath_tools.snapshot_helper", "_reset_cache_for_tests", "call"),
        ("jpintel_mcp.api._corpus_snapshot", "_reset_cache_for_tests", "call"),
        ("jpintel_mcp.api._audit_seal", "_reset_corpus_snapshot_cache_for_tests", "call"),
        # Wave 24 tool resolver — caches importlib.import_module() results,
        # so a test that monkeypatches a wave24 module before run #2 silently
        # re-runs the un-patched callable from the cache.
        ("jpintel_mcp.api.wave24_endpoints", "_reset_wave24_tool_cache", "call"),
        # Confidence / stats / cost / dashboard / contribute caches (each
        # holds its own dict + Lock; un-cleared bleed shows up as stale
        # row counts, stale Stripe billing previews, or stale rate-limit
        # buckets refusing legit retries).
        ("jpintel_mcp.api.confidence", "_reset_confidence_cache", "call"),
        ("jpintel_mcp.api.stats", "_reset_stats_cache", "call"),
        ("jpintel_mcp.api.cost", "_reset_preview_rate_state", "call"),
        ("jpintel_mcp.api.dashboard", "_reset_billing_cache_state", "call"),
        ("jpintel_mcp.api.contribute", "_reset_rate_limit_store", "call"),
        ("jpintel_mcp.api.subscribers", "_reset_rate_limit_state", "call"),
        # me.py session + billing-portal rate-limit deques.
        ("jpintel_mcp.api.me", "_reset_session_rate_limit_state", "call"),
        ("jpintel_mcp.api.me", "_reset_billing_portal_rate_limit_state", "call"),
        # Middleware caches not already in _reset_anon_rate_limit (the
        # autouse fixture below covers rate_limit + per_ip_endpoint; here
        # we add cap_cache + kill_switch which weren't in the original list).
        ("jpintel_mcp.api.middleware.customer_cap", "_reset_cap_cache_state", "call"),
        ("jpintel_mcp.api.middleware.kill_switch", "_reset_kill_switch_state", "call"),
        # business_law_detector — module exposes reload_catalog() which
        # cache_clears the two lru_cache loaders.
        ("jpintel_mcp.api._business_law_detector", "reload_catalog", "call"),
        # billing.stripe_usage — _get_subscription_item_id is lru_cache(4096),
        # exposed via _clear_subscription_item_cache(). A monkeypatched stripe
        # SDK in test_credit_pack / test_stripe_* would otherwise stick.
        ("jpintel_mcp.billing.stripe_usage", "_clear_subscription_item_cache", "call"),
        # R8 round 2 — additional cache surfaces missing from the round-1
        # list. `api/meta.py:_reset_meta_cache` is the meta endpoint
        # surface (search + freshness reads) and `api/programs.py:_clear_program_cache`
        # is the program-detail dict cache. Both bleed across tests when
        # not reset (search returns stale rowcounts in test_email order).
        ("jpintel_mcp.api.meta", "_reset_meta_cache", "call"),
        ("jpintel_mcp.api.programs", "_clear_program_cache", "call"),
        # R8 round 3 — `mcp.autonomath_tools.evidence_packet_tools` carries
        # a paths-keyed `_composer` singleton built lazily; tests that
        # monkeypatch jpintel/autonomath db paths before exercising the
        # MCP tool (test_evidence_packet, test_evidence_batch) get a stale
        # composer instance from a prior test's paths. Clear after every
        # test so the next call rebuilds against the current paths.
        (
            "jpintel_mcp.mcp.autonomath_tools.evidence_packet_tools",
            "_reset_composer",
            "call",
        ),
    )

    for module_name, attr_name, kind in targets:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        try:
            target = getattr(module, attr_name, None)
            if target is None:
                continue
            if kind == "call":
                target()
            elif kind == "cache_clear":
                clear = getattr(target, "cache_clear", None)
                if clear is not None:
                    clear()
        except Exception:
            # Reset hooks are best-effort. A failure here MUST NOT mask
            # the test under inspection — we'd rather a downstream test
            # see slightly-stale state than turn the whole suite red.
            pass

    # Drop any direct lru_cache surfaces that don't expose a public reset
    # helper. Only modules that have already been imported are touched —
    # importing them here would change boot order and break tests that
    # rely on lazy import side effects (e.g. _no_llm_in_production guard).
    cache_clear_targets: tuple[tuple[str, str], ...] = (
        ("jpintel_mcp.api.meta_freshness", "_load_registry_cached"),
        ("jpintel_mcp.mcp.autonomath_tools.static_resources", "_load_json"),
        ("jpintel_mcp.mcp.autonomath_tools.tools", "_enum_values_cached"),
        ("jpintel_mcp.db.id_translator", "program_unified_to_canonical"),
        ("jpintel_mcp.db.id_translator", "program_canonical_to_unified"),
    )
    for module_name, attr_name in cache_clear_targets:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        attr = getattr(module, attr_name, None)
        if attr is None:
            continue
        clear = getattr(attr, "cache_clear", None)
        if clear is None:
            continue
        with contextlib.suppress(Exception):
            clear()


def _sync_imported_settings_singleton(current_settings) -> None:
    """Re-bind modules that imported ``settings`` before config reloads.

    Some boot-gate tests intentionally reload ``jpintel_mcp.config``. After
    that, tests that patch ``jpintel_mcp.config.settings`` can miss modules
    that already did ``from jpintel_mcp.config import settings``. Keep all
    imported app modules on the canonical singleton at the start of each test.
    """
    current_log_usage = None
    deps_module = sys.modules.get("jpintel_mcp.api.deps")
    if deps_module is not None:
        current_log_usage = getattr(deps_module, "log_usage", None)
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith("jpintel_mcp."):
            continue
        with contextlib.suppress(Exception):
            if hasattr(module, "settings"):
                module.settings = current_settings
            if (
                current_log_usage is not None
                and module_name != "jpintel_mcp.api.deps"
                and hasattr(module, "log_usage")
            ):
                module.log_usage = current_log_usage


@pytest.fixture(scope="session")
def tmp_db_path() -> Path:
    return Path(_DB_PATH)


@pytest.fixture(scope="session")
def jpintel_seeded_db(tmp_db_path: Path) -> Path:
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
                p["unified_id"],
                p["primary_name"],
                None,
                p.get("authority_level"),
                None,
                p.get("prefecture"),
                None,
                p.get("program_kind"),
                None,
                p.get("amount_max_man_yen"),
                None,
                None,
                None,
                p.get("tier"),
                None,
                None,
                None,
                p.get("excluded", 0),
                p.get("exclusion_reason"),
                None,
                None,
                json.dumps(p.get("target_types", []), ensure_ascii=False),
                json.dumps(p.get("funding_purpose", []), ensure_ascii=False),
                None,
                None,
                None,
                None,
                now,
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
            "excl-test-mutex",
            "absolute",
            "critical",
            "keiei-kaishi-shikin",
            "koyo-shuno-shikin",
            json.dumps([]),
            "テスト排他ルール",
            "test source",
            json.dumps(["https://example.com"]),
            None,
        ),
    )
    conn.execute(
        """INSERT INTO exclusion_rules(
            rule_id, kind, severity, program_a, program_b,
            program_b_group_json, description, source_notes,
            source_urls_json, extra_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            "excl-test-prereq",
            "prerequisite",
            "critical",
            "seinen-shuno-shikin",
            "認定新規就農者",
            json.dumps([]),
            "前提条件テスト",
            "test source",
            json.dumps([]),
            None,
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
            "excl-test-uid-mutex",
            "absolute",
            "high",
            "テスト S-tier 補助金",
            "B-tier 融資 スーパーL資金",
            json.dumps([]),
            "uid-keyed テスト排他ルール",
            "test source",
            json.dumps(["https://example.com/uid"]),
            None,
            "UNI-test-s-1",
            "UNI-test-b-1",
        ),
    )
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES (?,?,?)",
        ("last_ingested_at", now, now),
    )
    conn.commit()
    conn.close()

    return tmp_db_path


@pytest.fixture(scope="session")
def seeded_db(jpintel_seeded_db: Path) -> Path:
    return jpintel_seeded_db


@pytest.fixture(autouse=True)
def _reset_anon_rate_limit(jpintel_seeded_db: Path):
    """Zero the anon_rate_limit table between tests.

    The default anon quota is 3/day. Without this, the /v1 tests that
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
    _restore_autonomath_paths()
    _reset_autonomath_state()
    # Some modules temporarily point settings.db_path / JPINTEL_DB_PATH at a
    # specialized fixture DB. Reset both before every test so API auth,
    # funnel, feedback, and anon quota checks all hit the seeded integration DB.
    os.environ["JPINTEL_DB_PATH"] = str(jpintel_seeded_db)
    os.environ["JPCITE_DB_PATH"] = str(jpintel_seeded_db)
    try:
        from jpintel_mcp.config import settings

        settings.db_path = jpintel_seeded_db
        _sync_imported_settings_singleton(settings)
    except ImportError:
        pass

    c = sqlite3.connect(jpintel_seeded_db)
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
    _reset_autonomath_state()
    _restore_autonomath_paths()
    _reset_autonomath_state()


@pytest.fixture(autouse=True)
def _sync_bg_task_queue(jpintel_seeded_db: Path, monkeypatch):
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
    from jpintel_mcp import email as _email_pkg
    from jpintel_mcp.api import _bg_task_queue as _q
    from jpintel_mcp.api import _bg_task_worker as _w
    from jpintel_mcp.api import billing as _billing
    from jpintel_mcp.api import me as _me
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
    async_only_kinds = {"stripe_status_refresh"}

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
        if kind in async_only_kinds:
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
def client(jpintel_seeded_db: Path) -> TestClient:
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def paid_key(jpintel_seeded_db: Path) -> str:
    """A metered ("paid") API key. Use when exercising fields=full / batch /
    metered paths.

    Each test gets its own key so quota exhaustion in one test cannot leak
    into another. Callers pass it as `headers={"X-API-Key": paid_key}`.
    """
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(jpintel_seeded_db)
    c.row_factory = sqlite3.Row
    import uuid

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    raw = issue_key(c, customer_id="cus_test_paid", tier="paid", stripe_subscription_id=sub_id)
    c.commit()
    c.close()
    return raw
