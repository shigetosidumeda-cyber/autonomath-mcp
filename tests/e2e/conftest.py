"""Playwright E2E fixtures for jpintel-mcp.

This sibling conftest intentionally does NOT import from the parent
`tests/conftest.py` — the parent mutates `os.environ` + sqlite test DB on
import, which we must avoid when running the suite against staging. The
e2e suite talks to a live deployment via HTTP only; DB interaction is
constrained to the optional fixture `seeded_api_key` which is a no-op
unless `JPINTEL_E2E_BASE_URL` points at localhost.

Browser constraints (MEMORY: feedback_playwright_screenshots):
  - viewport: 1440x900 (fits comfortably in the 1880 shell budget)
  - screenshots on failure only, capped at 1440 wide so `Read` never
    triggers the "image exceeds dimension limit" path
  - `page.wait_for_timeout` is avoided throughout the suite — all waits
    are explicit selectors / predicates so flakes don't compound
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from playwright.async_api import Browser, BrowserContext, Page

# --------------------------------------------------------------------------- #
# Pytest config
# --------------------------------------------------------------------------- #

# Register custom markers so pytest doesn't warn on `@pytest.mark.production`.
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "production: opt-in marker for tests that hit real prod. Skipped unless"
        " `--run-production` is passed on the CLI.",
    )
    config.addinivalue_line(
        "markers", "e2e: browser-driven smoke test (Playwright)."
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-production",
        action="store_true",
        default=False,
        help="Allow @pytest.mark.production tests to run (manual workflow only).",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Allow @pytest.mark.e2e browser tests to run against JPINTEL_E2E_BASE_URL.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip production/e2e tests unless explicitly requested."""
    run_production = config.getoption("--run-production")
    run_e2e = (
        config.getoption("--run-e2e")
        or os.environ.get("JPINTEL_E2E", "").strip().lower() in ("1", "true")
        or run_production
    )
    skip_prod = pytest.mark.skip(
        reason="@pytest.mark.production requires --run-production"
    )
    skip_e2e = pytest.mark.skip(
        reason="@pytest.mark.e2e requires --run-e2e or JPINTEL_E2E=1"
    )
    for item in items:
        if "production" in item.keywords and not run_production:
            item.add_marker(skip_prod)
        if "e2e" in item.keywords and not run_e2e:
            item.add_marker(skip_e2e)


# --------------------------------------------------------------------------- #
# Environment / base URL
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def base_url() -> str:
    """Origin the browser navigates to. Override via env for CI / staging."""
    url = os.environ.get("JPINTEL_E2E_BASE_URL", "http://localhost:8080").rstrip("/")
    return url


@pytest.fixture(scope="session")
def is_local_target(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


@pytest.fixture(scope="session")
def headless_env() -> bool:
    """CI = headless always. Local can override via JPINTEL_E2E_HEADLESS=0."""
    v = os.environ.get("JPINTEL_E2E_HEADLESS", "1").strip().lower()
    return v not in ("0", "false", "no")


# --------------------------------------------------------------------------- #
# Playwright — session-scoped browser, per-test context + page
# --------------------------------------------------------------------------- #
#
# A single browser process is reused across tests (session scope) because
# spinning up chromium per test is ~1s of overhead. A fresh BrowserContext
# per test isolates cookies, storage, and routed requests — a session
# cookie set in test_dashboard_flow will never leak into test_landing_flow.


@pytest_asyncio.fixture(scope="session")
async def playwright_instance() -> AsyncGenerator:
    async with async_playwright() as pw:
        yield pw


@pytest_asyncio.fixture(scope="session")
async def browser(
    playwright_instance, headless_env: bool
) -> AsyncGenerator[Browser, None]:
    # chromium only — CI installs just this one (~200MB smaller than all three).
    br = await playwright_instance.chromium.launch(headless=headless_env)
    try:
        yield br
    finally:
        await br.close()


@pytest_asyncio.fixture()
async def context(browser: Browser) -> AsyncGenerator[BrowserContext, None]:
    # Viewport 1440x900 — fits in the 1880px shell budget (screenshots of the
    # full page render under the hard cap; scrollable pages will crop to this
    # viewport unless a full_page screenshot is requested).
    ctx = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        # User-agent tag so production analytics can filter us out if needed.
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 jpintel-e2e/1.0"
        ),
        # Don't accept the real Stripe cookies — we never hit Stripe in E2E.
        accept_downloads=False,
    )
    # Global page timeout: 30s per test. Individual waits can set shorter.
    ctx.set_default_timeout(30_000)
    ctx.set_default_navigation_timeout(30_000)
    try:
        yield ctx
    finally:
        await ctx.close()


# --------------------------------------------------------------------------- #
# Failure screenshots (on failure only, width-capped)
# --------------------------------------------------------------------------- #
#
# Approach: the sync pytest_runtest_makereport hook stashes pass/fail on the
# item; the async `page` fixture reads that flag during teardown and, if the
# test failed, snaps a screenshot while the event loop is still live.
# This avoids the "loop is closed" races that come from trying to run an
# async coroutine from a sync hook.
#
# Screenshots are written to tests/e2e/_artifacts/ at the default viewport
# (1440 wide, under the 1880px shell cap — safe to `Read` in the shell).


_ARTIFACT_DIR = Path(__file__).parent / "_artifacts"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    rep: pytest.TestReport = outcome.get_result()
    # Only record the call phase outcome; setup / teardown are their own.
    if rep.when == "call":
        item.__e2e_rep_call = rep  # type: ignore[attr-defined]


@pytest_asyncio.fixture()
async def page(
    request: pytest.FixtureRequest, context: BrowserContext
) -> AsyncGenerator[Page, None]:
    pg = await context.new_page()
    try:
        yield pg
    finally:
        # Only snap on failure. `__e2e_rep_call` is set by the hook above.
        rep = getattr(request.node, "__e2e_rep_call", None)
        if rep is not None and rep.failed:
            _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            safe = (
                rep.nodeid.replace("/", "_")
                .replace(":", "_")
                .replace("::", "__")
            )
            with contextlib.suppress(Exception):
                # Screenshots must never mask the real failure.
                await pg.screenshot(
                    path=str(_ARTIFACT_DIR / f"{safe}.png"), full_page=False
                )


# --------------------------------------------------------------------------- #
# API-key fixtures (local target only)
# --------------------------------------------------------------------------- #
#
# `seeded_api_key` creates a real api_keys row via the same `issue_key` path
# as `src/jpintel_mcp/billing/keys.py` so the dashboard flow can sign in.
# Direct DB insert — deliberately NOT going through Stripe Checkout.
#
# This fixture REFUSES to run against non-localhost to protect staging /
# prod analytics + billing. Tests that need it skip when `is_local_target`
# is False (unless JPINTEL_E2E_API_KEY is provided, in which case we reuse
# that one and don't touch the DB).


def _require_local_db(base_url: str) -> Path:
    if "localhost" not in base_url and "127.0.0.1" not in base_url:
        pytest.skip(
            "DB-writing fixtures are local-only (refuses to touch staging/prod)."
        )
    db_path = Path(
        os.environ.get("JPINTEL_E2E_DB_PATH", "./data/jpintel.db")
    ).resolve()
    if not db_path.exists():
        pytest.skip(f"local DB not found at {db_path}; start the API server first")
    return db_path


def _ensure_src_importable() -> None:
    """Make `jpintel_mcp` importable when running from repo root.

    The e2e suite may be invoked by a CI job that never did `pip install -e`;
    we fall back to adding `src/` to sys.path so `jpintel_mcp.billing.keys`
    resolves.
    """
    if "jpintel_mcp" in sys.modules:
        return
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _align_salt_with_server() -> None:
    """Ensure the salt the fixture uses to hash matches the uvicorn server.

    The sibling `tests/conftest.py` sets `API_KEY_SALT=test-salt` at import
    time, which leaks into this process too (pytest discovers both conftests
    when collecting `tests/e2e/`). The uvicorn server we're testing reads
    from `.env` at the repo root, so those two values drift — and a locally-
    hashed key won't match the one the server looks up on /v1/session.

    Resolution: read `.env` directly and re-align our salt. Only act when
    running against a local target (staging has its own secret management).
    """
    repo_root = Path(__file__).resolve().parents[2]
    env_file = repo_root / ".env"
    if not env_file.exists():
        return
    # Tiny parser — no python-dotenv dep in the e2e extras.
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k == "API_KEY_SALT" and v:
            os.environ["API_KEY_SALT"] = v
            # If jpintel_mcp.config was already imported with the stale salt,
            # drop it so the next import picks up the new env.
            for mod in list(sys.modules):
                if mod.startswith("jpintel_mcp"):
                    del sys.modules[mod]
            return


@pytest.fixture()
def seeded_api_key(
    base_url: str, is_local_target: bool
) -> Generator[dict[str, str], None, None]:
    """Yield a dict with `raw_key`, `key_hash`, `customer_id`, `tier`.

    Cleans up (revokes) the key on teardown so the DB doesn't accumulate
    orphaned rows across re-runs.
    """
    # Honour an externally supplied key (e.g. staging has a pre-seeded
    # test key), in which case we don't touch the DB at all.
    external = os.environ.get("JPINTEL_E2E_API_KEY", "").strip()
    if external:
        yield {
            "raw_key": external,
            "key_hash": "",  # unknown — we didn't compute it
            "customer_id": "cus_e2e_external",
            "tier": "paid",
            "external": "1",
        }
        return

    db_path = _require_local_db(base_url)
    _ensure_src_importable()
    # CRITICAL: Align salt with the running uvicorn server BEFORE importing
    # jpintel_mcp modules. The parent `tests/conftest.py` sets
    # `API_KEY_SALT=test-salt` at import time, which would otherwise cause
    # the hash we write to DB to be unreachable by the real server.
    _align_salt_with_server()

    # Local import — after _align_salt_with_server() so jpintel_mcp.config
    # is loaded with the correct salt.
    from jpintel_mcp.billing.keys import issue_key  # noqa: WPS433

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        raw = issue_key(
            conn,
            customer_id="cus_e2e_test",
            tier="paid",
            stripe_subscription_id=f"sub_e2e_{int(datetime.now(UTC).timestamp())}",
        )
        conn.commit()

        # Recompute hash for teardown revoke
        from jpintel_mcp.api.deps import hash_api_key  # noqa: WPS433

        key_hash = hash_api_key(raw)

        yield {
            "raw_key": raw,
            "key_hash": key_hash,
            "customer_id": "cus_e2e_test",
            "tier": "paid",
            "external": "0",
        }

        # Teardown — revoke so the key can't be reused if the test leaked
        # the raw value into a screenshot / log.
        conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            (datetime.now(UTC).isoformat(), key_hash),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def seeded_usage_events(
    seeded_api_key: dict[str, str], base_url: str
) -> Generator[list[str], None, None]:
    """Insert 30 days of deterministic usage_events rows for the seeded key.

    Returns the list of inserted ISO timestamps so the test can assert the
    dashboard graph shows the same data back.
    """
    if seeded_api_key.get("external") == "1":
        # We don't know the key_hash when the key was supplied externally;
        # skip so we don't write into an unrelated key's usage history.
        pytest.skip("seeded_usage_events needs a local-seeded key (DB write)")

    db_path = _require_local_db(base_url)

    key_hash = seeded_api_key["key_hash"]
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)

    conn = sqlite3.connect(db_path)
    inserted: list[str] = []
    try:
        # A gentle sinusoid over 30 days so the chart has a visible peak.
        # Using `int` with range stepping to avoid importing numpy in the
        # test dependency tree.
        for day_offset in range(30):
            ts_day = now - timedelta(days=29 - day_offset)
            # calls = 5 + 15*sin-ish: deterministic, non-zero, varies day-to-day
            calls = 5 + (day_offset * 7 + 3) % 20
            for i in range(calls):
                ts = (ts_day + timedelta(minutes=i)).isoformat()
                conn.execute(
                    "INSERT INTO usage_events"
                    "(key_hash, endpoint, ts, status, metered, params_digest) "
                    "VALUES (?, 'programs.search', ?, 200, 0, NULL)",
                    (key_hash, ts),
                )
                inserted.append(ts)
        conn.commit()

        yield inserted

        # Teardown — remove only the rows we inserted (match by key_hash; the
        # key is revoked on teardown of seeded_api_key anyway, so even a broad
        # delete can't affect another customer).
        conn.execute("DELETE FROM usage_events WHERE key_hash = ?", (key_hash,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Navigation helpers
# --------------------------------------------------------------------------- #


@pytest.fixture()
def url_for(base_url: str):
    """Return a function that builds `{base_url}{path}` safely."""

    def _build(path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return base_url + path

    return _build


__all__ = [
    "base_url",
    "browser",
    "context",
    "is_local_target",
    "page",
    "playwright_instance",
    "seeded_api_key",
    "seeded_usage_events",
    "url_for",
]
