#!/usr/bin/env python3
"""Monthly PDF report fan-out cron.

Wave 35 Axis 6a (2026-05-12). Walks
``am_pdf_report_subscriptions`` (migration 244) and renders one PDF per
``enabled=1 AND cadence='monthly'`` row, in parallel batches of 10.

Schedule: 1st of every month at 06:00 JST via
``.github/workflows/axis6-output-monthly.yml``.

Memory references
-----------------
* feedback_no_operator_llm_api : pure reportlab, zero LLM calls.
* feedback_zero_touch_solo : the cron self-heals — failures get logged
  but do not page anyone.
* feedback_destruction_free_organization : the log table grows
  append-only; no rm / truncate.

CLI
---
::

    python scripts/cron/generate_pdf_reports_monthly.py
    python scripts/cron/generate_pdf_reports_monthly.py --dry-run
    python scripts/cron/generate_pdf_reports_monthly.py --client-id sub_abc
    python scripts/cron/generate_pdf_reports_monthly.py --max-workers 5
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import logging
import os
import secrets
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("generate_pdf_reports_monthly")

_AM_DB_PATH = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(os.environ.get("JPINTEL_DB", "autonomath.db")),
)

DEFAULT_MAX_WORKERS = 10
DEFAULT_PDF_R2_BUCKET = os.environ.get("PDF_REPORT_R2_BUCKET", "autonomath-backup")
DEFAULT_PAGE_TIMEOUT_S = 60


def _connect(read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(
            f"file:{_AM_DB_PATH}?mode=ro", uri=True, timeout=30.0, check_same_thread=False
        )
    else:
        conn = sqlite3.connect(_AM_DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _due_subscriptions(cadence: str, client_id: str | None) -> list[dict[str, Any]]:
    conn = _connect(read_only=True)
    try:
        if client_id:
            rows = conn.execute(
                "SELECT * FROM am_pdf_report_subscriptions WHERE client_id=? AND enabled=1",
                (client_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM am_pdf_report_subscriptions "
                "WHERE enabled=1 AND cadence=? ORDER BY client_id",
                (cadence,),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        log.warning("am_pdf_report_subscriptions missing — %s", exc)
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _log_generation(
    *,
    subscription_id: str | None,
    client_id: str,
    cadence: str | None,
    started_at: str,
    finished_at: str | None,
    success: bool,
    r2_key: str | None,
    byte_size: int | None,
    page_count: int | None,
    error_text: str | None,
    billing_units: int,
) -> None:
    log_id = f"log_{secrets.token_hex(8)}"
    try:
        conn = _connect(read_only=False)
    except sqlite3.Error as exc:
        log.warning("could not open autonomath.db for log insert: %s", exc)
        return
    try:
        conn.execute(
            """
            INSERT INTO am_pdf_report_generation_log
                (log_id, subscription_id, client_id, cadence, started_at,
                 finished_at, success, r2_key, byte_size, page_count,
                 error_text, billing_units)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                log_id,
                subscription_id,
                client_id,
                cadence,
                started_at,
                finished_at,
                1 if success else 0,
                r2_key,
                byte_size,
                page_count,
                error_text,
                billing_units,
            ),
        )
        if success and subscription_id:
            conn.execute(
                "UPDATE am_pdf_report_subscriptions SET "
                "last_generated_at=?, last_generated_r2_key=?, "
                "last_generated_byte_size=?, last_error=NULL, updated_at=? "
                "WHERE subscription_id=?",
                (finished_at, r2_key, byte_size, finished_at, subscription_id),
            )
        elif not success and subscription_id:
            conn.execute(
                "UPDATE am_pdf_report_subscriptions SET last_error=?, updated_at=? "
                "WHERE subscription_id=?",
                (error_text, finished_at, subscription_id),
            )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("am_pdf_report_generation_log insert failed: %s", exc)
    finally:
        conn.close()


def _render_one(sub: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    client_id = str(sub.get("client_id", ""))
    cadence = str(sub.get("cadence", "monthly"))
    sub_id = str(sub.get("subscription_id", ""))
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()

    if not client_id:
        return {
            "subscription_id": sub_id,
            "client_id": "",
            "ok": False,
            "error": "empty client_id",
            "elapsed_ms": 0,
        }

    try:
        from jpintel_mcp.api.pdf_report import (
            _collect_client_context,
            _render_pdf,
        )

        am_conn = _connect(read_only=True)
        try:
            client_ctx = _collect_client_context(am_conn, client_id)
        finally:
            am_conn.close()

        if dry_run:
            elapsed = int((time.monotonic() - started) * 1000)
            log.info("dry-run client_id=%s ctx_keys=%s", client_id, list(client_ctx.keys()))
            return {
                "subscription_id": sub_id,
                "client_id": client_id,
                "ok": True,
                "dry_run": True,
                "elapsed_ms": elapsed,
            }

        blob, page_count = _render_pdf(client_id, client_ctx)
        sha256 = hashlib.sha256(blob).hexdigest()
        byte_size = len(blob)
        yyyymm = datetime.now(UTC).strftime("%Y%m")
        template = sub.get("r2_url_template") or "pdf_reports/{client_id}/{yyyymm}.pdf"
        r2_key = template.format(client_id=client_id, yyyymm=yyyymm)

        staging_dir = Path("/tmp/pdf_report_monthly")  # noqa: S108
        staging_dir.mkdir(parents=True, exist_ok=True)
        local = staging_dir / f"{client_id}-{yyyymm}.pdf"
        local.write_bytes(blob)

        uploaded = False
        try:
            from scripts.cron._r2_client import upload

            upload(local, r2_key, bucket=DEFAULT_PDF_R2_BUCKET)
            uploaded = True
        except (ImportError, RuntimeError, FileNotFoundError) as exc:
            log.warning("R2 upload skipped (kept local): %s", exc)

        finished_at = datetime.now(UTC).isoformat()
        _log_generation(
            subscription_id=sub_id,
            client_id=client_id,
            cadence=cadence,
            started_at=started_at,
            finished_at=finished_at,
            success=True,
            r2_key=r2_key,
            byte_size=byte_size,
            page_count=page_count,
            error_text=None,
            billing_units=10,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        log.info(
            "rendered client_id=%s bytes=%d sha256=%s elapsed_ms=%d uploaded=%s",
            client_id,
            byte_size,
            sha256[:12],
            elapsed,
            uploaded,
        )
        return {
            "subscription_id": sub_id,
            "client_id": client_id,
            "ok": True,
            "byte_size": byte_size,
            "sha256": sha256,
            "page_count": page_count,
            "r2_key": r2_key,
            "uploaded": uploaded,
            "elapsed_ms": elapsed,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.monotonic() - started) * 1000)
        log.exception("render failed client_id=%s", client_id)
        _log_generation(
            subscription_id=sub_id,
            client_id=client_id,
            cadence=cadence,
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            success=False,
            r2_key=None,
            byte_size=None,
            page_count=None,
            error_text=str(exc)[:300],
            billing_units=0,
        )
        return {
            "subscription_id": sub_id,
            "client_id": client_id,
            "ok": False,
            "error": str(exc)[:300],
            "elapsed_ms": elapsed,
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="generate_pdf_reports_monthly")
    p.add_argument("--cadence", default="monthly", choices=["monthly", "quarterly", "annual"])
    p.add_argument("--client-id", default=None, help="Limit to a single client")
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    p.add_argument("--dry-run", action="store_true", help="Skip render+upload+log")
    args = p.parse_args(argv)

    subs = _due_subscriptions(args.cadence, args.client_id)
    log.info("monthly PDF run: %d subscription(s) due", len(subs))
    if not subs:
        return 0

    results: list[dict[str, Any]] = []
    with cf.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(_render_one, s, args.dry_run): s for s in subs}
        for fut in cf.as_completed(futures, timeout=DEFAULT_PAGE_TIMEOUT_S * len(subs)):
            try:
                results.append(fut.result())
            except cf.TimeoutError:
                results.append({"ok": False, "error": "render timeout"})
            except Exception as exc:  # noqa: BLE001
                results.append({"ok": False, "error": str(exc)[:300]})

    ok_n = sum(1 for r in results if r.get("ok"))
    log.info(
        "monthly PDF run done: %d OK / %d failed / %d total",
        ok_n,
        len(results) - ok_n,
        len(results),
    )
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
