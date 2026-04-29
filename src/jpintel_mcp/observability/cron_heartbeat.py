"""Heartbeat / observability helper for ``scripts/cron/*.py`` entries.

Every cron emits exactly one row in ``cron_runs`` (migration 102) per
invocation — success OR failure. The single row carries enough metadata
to:

* Verify the cron actually executed (not just scheduled).
* Detect missed runs (last_run_at gap > expected interval).
* Surface failure rate per cron (``status='error'`` fraction).
* Drive the ``/v1/admin/cron_runs`` read-side endpoint.

Design constraints:

* **Never raises.** A heartbeat that itself raises masks the real cron
  outcome. The context manager swallows its own write errors and logs
  them; the wrapped cron's exception is always re-raised so the GitHub
  Actions run still turns red on failure.
* **Separate connection / autocommit.** The heartbeat opens a fresh
  ``sqlite3`` connection with ``isolation_level=None`` so the write
  cannot be rolled back by the cron's own transaction. If a cron commits
  a partial batch and then crashes, the heartbeat row still lands.
* **No billing meter.** This is internal observability — no
  ``usage_events`` row, no Stripe push.
* **No LLM calls.** Pure SQLite + stdlib. Per
  ``feedback_autonomath_no_api_use`` we cannot spend customer LLM tokens
  on infra paths.

Usage::

    from jpintel_mcp.observability.cron_heartbeat import heartbeat

    def run() -> dict:
        with heartbeat("run_saved_searches") as hb:
            ...  # existing cron body
            hb["rows_processed"] = emails_sent
            hb["rows_skipped"] = skipped_window + skipped_no_match
            hb["metadata"] = {"billed": billed, "frequency": "daily"}
            return summary

The context yields a mutable ``state`` dict the cron updates in place;
the helper reads it after the ``with`` body exits and writes the row.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.observability.cron_heartbeat")


def _default_db_path() -> str:
    """Mirror scripts/migrate.py default. Honour ``JPINTEL_DB_PATH`` env."""
    env = os.environ.get("JPINTEL_DB_PATH")
    if env:
        return env
    # Walk up from this file: src/jpintel_mcp/observability/cron_heartbeat.py
    # -> src/jpintel_mcp/observability -> src/jpintel_mcp -> src -> repo
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return str(repo_root / "data" / "jpintel.db")


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with seconds resolution."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Idempotently create ``cron_runs`` if migration 102 has not run.

    Mirrors the DDL in ``scripts/migrations/102_cron_runs_heartbeat.sql``.
    Lets the cron heartbeat survive on a fresh ``data/jpintel.db`` that
    has not yet had migrate.py applied (e.g. in unit tests).
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cron_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cron_name       TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT NOT NULL,
            rows_processed  INTEGER,
            rows_skipped    INTEGER,
            error_message   TEXT,
            metadata_json   TEXT,
            workflow_run_id TEXT,
            git_sha         TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cron_runs_name_started "
        "ON cron_runs (cron_name, started_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cron_runs_status_started "
        "ON cron_runs (status, started_at DESC)"
    )


def _truncate(text: str | None, limit: int = 500) -> str | None:
    """Cap error text so a run-away stack trace cannot bloat the DB."""
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _write_row(
    db_path: str,
    cron_name: str,
    started_at: str,
    status: str,
    state: dict[str, Any],
    error_message: str | None,
    workflow_run_id: str,
    git_sha: str,
) -> None:
    """Open an isolated autocommit connection and insert one row.

    Failure is logged but never raised — the cron's own exception (if
    any) is what should propagate.
    """
    finished_at = _now_iso()
    rows_processed = state.get("rows_processed")
    rows_skipped = state.get("rows_skipped")
    metadata = state.get("metadata")
    metadata_json = (
        json.dumps(metadata, ensure_ascii=False, default=str)
        if isinstance(metadata, dict) and metadata
        else None
    )

    conn: sqlite3.Connection | None = None
    try:
        # isolation_level=None = autocommit. The cron's own transactions
        # cannot roll back this row even if they wrap us.
        conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
        _ensure_table(conn)
        conn.execute(
            """INSERT INTO cron_runs (
                cron_name, started_at, finished_at, status,
                rows_processed, rows_skipped, error_message,
                metadata_json, workflow_run_id, git_sha
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cron_name,
                started_at,
                finished_at,
                status,
                int(rows_processed) if rows_processed is not None else None,
                int(rows_skipped) if rows_skipped is not None else None,
                _truncate(error_message),
                metadata_json,
                workflow_run_id or None,
                git_sha or None,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — observability cannot raise
        logger.warning(
            "cron_heartbeat write failed (non-fatal): cron=%s status=%s err=%s",
            cron_name,
            status,
            exc,
        )
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


@contextlib.contextmanager
def heartbeat(
    cron_name: str,
    db_path: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Context manager that emits one ``cron_runs`` row per invocation.

    Yields a mutable ``state`` dict with three writable keys:

    * ``rows_processed`` — script-defined unit (emails sent, diffs
      inserted, ...). Coerced to ``int`` on write.
    * ``rows_skipped`` — window-gated, dedup, idempotent skip. Coerced.
    * ``metadata`` — arbitrary JSON-serialisable dict, persisted in
      ``metadata_json``.

    On clean exit: writes ``status='ok'``.
    On exception: writes ``status='error'`` with truncated
    ``error_message = "<ExcClass>: <msg>"``, then re-raises.

    Args:
        cron_name: short identifier (``run_saved_searches``,
            ``dispatch_webhooks``, ...). Stored verbatim — keep it
            stable across releases or admin queries break.
        db_path: target SQLite path. Defaults to
            ``$JPINTEL_DB_PATH`` then ``./data/jpintel.db``.
    """
    resolved_path = db_path or _default_db_path()
    started_at = _now_iso()
    workflow_run_id = os.environ.get("GITHUB_RUN_ID", "")
    git_sha = (os.environ.get("GITHUB_SHA") or "")[:8]
    state: dict[str, Any] = {
        "rows_processed": 0,
        "rows_skipped": 0,
        "metadata": {},
    }

    try:
        yield state
    except BaseException as exc:
        # BaseException, not Exception: KeyboardInterrupt / SystemExit
        # also count as a failed run. We re-raise after logging so the
        # caller's exit code stays correct.
        err_text = f"{type(exc).__name__}: {exc}"
        _write_row(
            resolved_path,
            cron_name,
            started_at,
            "error",
            state,
            err_text,
            workflow_run_id,
            git_sha,
        )
        raise
    else:
        _write_row(
            resolved_path,
            cron_name,
            started_at,
            "ok",
            state,
            None,
            workflow_run_id,
            git_sha,
        )


__all__ = ["heartbeat"]
