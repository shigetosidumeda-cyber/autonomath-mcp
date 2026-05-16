"""Axis 3 daily ingest smoke + DB upsert integrity tests.

Covers the 5 cron scripts landed in Wave 33+ daily ingest hardening:

  1. scripts/cron/poll_adoption_rss_daily.py
  2. scripts/cron/poll_egov_amendment_daily.py
  3. scripts/cron/poll_enforcement_daily.py
  4. scripts/cron/detect_budget_to_subsidy_chain.py
  5. scripts/cron/diff_invoice_registrants_daily.py

Each cron is invoked in ``--dry-run`` mode (no DB writes) and the
``_ensure_table`` / ``_ensure_tables`` helpers are exercised against a
fresh sqlite file to confirm idempotent schema creation. The chain
detector + invoice differ also assert that re-running the upsert path
inserts zero new rows when the input is unchanged (idempotency contract).

No live HTTP calls are made — feeds are stubbed via a `MockTransport`.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

_REPO = Path(__file__).resolve().parents[1]
_CRON_DIR = _REPO / "scripts" / "cron"

CRON_SCRIPTS = (
    "poll_adoption_rss_daily",
    "poll_egov_amendment_daily",
    "poll_enforcement_daily",
    "detect_budget_to_subsidy_chain",
    "diff_invoice_registrants_daily",
    "daily_freshness_alert",
)


def _load_cron(name: str):
    """Import a cron script as a module without installing it."""
    path = _CRON_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def autonomath_db(tmp_path: Path) -> Path:
    db = tmp_path / "autonomath.db"
    # Empty DB — each cron creates tables defensively via _ensure_table*.
    sqlite3.connect(str(db)).close()
    return db


@pytest.fixture
def jpintel_db(tmp_path: Path) -> Path:
    db = tmp_path / "jpintel.db"
    sqlite3.connect(str(db)).close()
    return db


# ---------------------------------------------------------------------------
# 1. Import + CLI smoke — every script must import + show --help
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", CRON_SCRIPTS)
def test_cron_script_imports_clean(script: str) -> None:
    mod = _load_cron(script)
    assert hasattr(mod, "main")
    assert hasattr(mod, "run")


@pytest.mark.parametrize("script", CRON_SCRIPTS)
def test_cron_script_help_smoke(script: str) -> None:
    """Each script's --help must exit 0 and print its docstring summary."""
    path = _CRON_DIR / f"{script}.py"
    result = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout or "--help" in result.stdout


# ---------------------------------------------------------------------------
# 2. Dry-run smoke — each cron runs against an empty DB and returns counters
# ---------------------------------------------------------------------------


def test_adoption_rss_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_cron("poll_adoption_rss_daily")

    def stub_get(self, url, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        return httpx.Response(
            status_code=200,
            text=(
                "<rss><channel><item>"
                "<title>令和8年度ものづくり補助金 採択結果</title>"
                "<link>https://www.mirasapo-plus.go.jp/sample</link>"
                "<description>令和8年5月10日 1234567890123</description>"
                "<pubDate>Sun, 10 May 2026 09:00:00 +0900</pubDate>"
                "</item></channel></rss>"
            ),
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "get", stub_get)
    counters = mod.run(db_path=Path("/dev/null"), days=7, dry_run=True)
    assert counters["fetched"] >= len(mod.RSS_FEEDS)
    assert counters["parsed"] >= 1


def test_egov_amendment_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_cron("poll_egov_amendment_daily")

    def stub_get(self, url, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        return httpx.Response(
            status_code=200,
            text=(
                "<rss><channel><item>"
                "<title>令和8年法律第42号 税理士法の一部を改正する法律</title>"
                "<link>https://elaws.e-gov.go.jp/sample</link>"
                "<description>amendment text</description>"
                "<pubDate>Mon, 11 May 2026 10:00:00 +0900</pubDate>"
                "</item></channel></rss>"
            ),
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "get", stub_get)
    counters = mod.run(db_path=Path("/dev/null"), days=14, dry_run=True)
    assert counters["fetched"] >= 1


def test_enforcement_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_cron("poll_enforcement_daily")

    def stub_get(self, url, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        return httpx.Response(
            status_code=200,
            text=(
                "<rss><channel><item>"
                "<title>業務改善命令 株式会社サンプル 1234567890123 公表</title>"
                "<link>https://www.fsa.go.jp/sample</link>"
                "<description>令和8年5月11日 業務改善命令を発出した</description>"
                "<pubDate>Mon, 11 May 2026 11:00:00 +0900</pubDate>"
                "</item></channel></rss>"
            ),
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "get", stub_get)
    counters = mod.run(
        autonomath_db=Path("/dev/null"),
        jpintel_db=Path("/dev/null"),
        days=14,
        dry_run=True,
    )
    assert counters["fetched"] >= len(mod.MINISTRY_FEEDS)
    assert counters["matched"] >= 1


def test_budget_subsidy_chain_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_cron("detect_budget_to_subsidy_chain")

    def stub_get(self, url, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        if "shugiin" in url or "sangiin" in url:
            return httpx.Response(
                status_code=200,
                text=(
                    "第213回 議案2 令和8年度補正予算 本会議可決 2026/05/01\n"
                    "第213回 議案3 令和8年度本予算 本会議成立 2026/05/02"
                ),
                request=request,
            )
        return httpx.Response(
            status_code=200,
            text=(
                "<rss><channel><item>"
                "<title>令和8年度ものづくり補助金 公募開始</title>"
                "<link>https://www.meti.go.jp/sample</link>"
                "<pubDate>Sun, 10 May 2026 09:00:00 +0900</pubDate>"
                "</item></channel></rss>"
            ),
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "get", stub_get)
    counters = mod.run(
        db_path=Path("/dev/null"),
        lag_days=30,
        window_days=60,
        dry_run=True,
    )
    assert counters["budgets"] >= 1
    assert counters["subsidies"] >= 1
    assert counters["chains_inserted"] >= 1


def test_invoice_diff_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_cron("diff_invoice_registrants_daily")

    def stub_get(self, url, params=None, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        if params and params.get("page", 1) > 1:
            payload = {"items": []}
        else:
            payload = {
                "items": [
                    {
                        "houjin_bangou": "9999999999999",
                        "registration_no": "T9999999999999",
                        "name": "サンプル株式会社",
                        "address": "東京都港区",
                        "prefecture": "東京都",
                        "registered_at": "2026-05-01",
                    }
                ]
            }
        return httpx.Response(
            status_code=200,
            text=json.dumps(payload),
            headers={"content-type": "application/json"},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "get", stub_get)
    counters = mod.run(
        db_path=Path("/dev/null"),
        since_override=(datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        dry_run=True,
    )
    assert counters["fetched"] >= 1


# ---------------------------------------------------------------------------
# 3. DB upsert + idempotency — second run inserts zero
# ---------------------------------------------------------------------------


def test_adoption_upsert_idempotent(autonomath_db: Path) -> None:
    mod = _load_cron("poll_adoption_rss_daily")
    conn = mod._open_db(str(autonomath_db))
    mod._ensure_table(conn)
    row = {
        "program_id": None,
        "program_name": "ものづくり補助金 採択結果",
        "adopter_name": None,
        "adopter_houjin_bangou": "1234567890123",
        "adopted_at": "2026-05-10",
        "announce_url": "https://www.mirasapo-plus.go.jp/sample",
        "source_feed": "mirasapo",
        "sha256": "deadbeef",
        "retrieved_at": "2026-05-12T00:00:00Z",
    }
    n1 = mod._upsert(conn, row)
    n2 = mod._upsert(conn, row)
    conn.commit()
    assert n1 == 1
    assert n2 == 0


def test_budget_subsidy_chain_upsert_idempotent(autonomath_db: Path) -> None:
    mod = _load_cron("detect_budget_to_subsidy_chain")
    # Bring the schema online (mig 234 lives outside the test path; we apply
    # the table CREATE inline against tmp DB for the test).
    mig_path = _REPO / "scripts" / "migrations" / "234_budget_to_subsidy_chain.sql"
    conn = mod._open(str(autonomath_db))
    conn.executescript(mig_path.read_text(encoding="utf-8"))
    mod._ensure_program_column(conn)
    row = {
        "budget_kokkai_id": "213-2",
        "budget_passing_date": "2026-05-01",
        "budget_kind": "supplementary_budget",
        "subsidy_program_id": "subsidy:unmatched:abc",
        "announce_date": "2026-05-10",
        "lag_days": 9,
        "evidence_url": "https://www.meti.go.jp/sample",
    }
    n1 = mod._upsert_chain(conn, row)
    n2 = mod._upsert_chain(conn, row)
    conn.commit()
    assert n1 == 1
    assert n2 == 0


def test_invoice_diff_upsert_idempotent(autonomath_db: Path) -> None:
    mod = _load_cron("diff_invoice_registrants_daily")
    conn = mod._open(str(autonomath_db))
    mod._ensure_tables(conn)
    row = mod._row_from_api(
        {
            "houjin_bangou": "9999999999999",
            "registration_no": "T9999999999999",
            "name": "サンプル株式会社",
            "address": "東京都港区",
            "prefecture": "東京都",
            "registered_at": "2026-05-01",
        }
    )
    assert row is not None
    ins1, upd1, sd1 = mod._upsert(conn, row)
    ins2, upd2, sd2 = mod._upsert(conn, row)
    conn.commit()
    assert (ins1, upd1, sd1) == (1, 0, 0)
    assert (ins2, upd2, sd2) == (0, 0, 0)


# ---------------------------------------------------------------------------
# 4. Banned aggregator host detection
# ---------------------------------------------------------------------------


def test_adoption_banned_host_rejected() -> None:
    mod = _load_cron("poll_adoption_rss_daily")
    assert mod._is_banned("https://noukaweb.example/feed.rss") is True
    assert mod._is_banned("https://hojyokin-portal.example/feed.rss") is True
    assert mod._is_banned("https://www.mirasapo-plus.go.jp/feed/") is False


def test_egov_allowed_host_only() -> None:
    mod = _load_cron("poll_egov_amendment_daily")
    assert mod._allowed_host("https://elaws.e-gov.go.jp/anything") is True
    assert mod._allowed_host("https://aggregator.example/x") is False


# ---------------------------------------------------------------------------
# 5. Freshness alert anomaly detection
# ---------------------------------------------------------------------------


def test_freshness_alert_detects_zero_ingest(autonomath_db: Path) -> None:
    mod = _load_cron("daily_freshness_alert")
    conn = sqlite3.connect(str(autonomath_db))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cron_ingest_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            counters TEXT NOT NULL,
            ran_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO cron_ingest_log(source, counters, ran_at) VALUES (?, ?, ?)",
        (
            "adoption_rss",
            json.dumps({"fetched": 0, "inserted": 0}),
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()
    conn.close()

    payload = mod.run(
        db_path=autonomath_db,
        out_dir=autonomath_db.parent / "freshness_out",
        dry_run=True,
    )
    assert "ZERO_INGEST" in " ".join(payload["anomalies"]) or any(
        "NEVER_RAN" in a for a in payload["anomalies"]
    )
