#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""§10.10 (5) Hallucination Guard — narrative rollback + customer-credit helper.

Given a quarantine_id, this helper:
    1. Looks up the (narrative_id, narrative_table) pair from
       am_narrative_quarantine.
    2. UPDATEs the parent narrative row to is_active=0 (idempotent).
    3. Cloudflare Cache Tags purge for `narrative:{table}:{id}` so any edge
       cache copy is invalidated immediately.
    4. SELECTs DISTINCT api_key_id from `am_narrative_serve_log` for the
       last 30 days who consumed the bad narrative — counts `n` requests
       per affected key.
    5. Issues a Stripe credit-note (¥3 × n) per affected api_key_id — calls
       the existing operator-side billing helper, NO LLM.
    6. Sends a Postmark email per affected api_key_id with the
       `narrative_corrected` template.

Per `feedback_no_operator_llm_api`: NO LLM SDK import here.

Usage:
    uv run python tools/offline/narrative_rollback.py --quarantine-id 42
    uv run python tools/offline/narrative_rollback.py --quarantine-id 42 --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("autonomath.offline.narrative_rollback")


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.offline.narrative_rollback")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _resolve_db_path(arg_path: Path | None) -> Path:
    if arg_path:
        return arg_path
    env = os.environ.get("AUTONOMATH_DB_PATH")
    if env:
        return Path(env)
    return Path("./autonomath.db")


def _purge_cf_cache(tag: str) -> bool:
    """Cloudflare cache purge by tag. Requires CF_API_TOKEN + CF_ZONE_ID env."""
    token = os.environ.get("CF_API_TOKEN")
    zone = os.environ.get("CF_ZONE_ID")
    if not token or not zone:
        logger.info("cf_purge_skipped reason=missing_env tag=%s", tag)
        return False
    url = f"https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"
    body = json.dumps({"tags": [tag]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("cf_purge_failed tag=%s err=%s", tag, str(exc)[:160])
        return False


def _stripe_credit(api_key_id: int, yen: int) -> bool:
    """Issue a Stripe credit-note via the operator-side helper.

    Returns True on success, False if the helper is not available (or the
    Stripe SDK is not configured in this environment).
    """
    if yen <= 0:
        return False
    try:
        # Late import so this script runs even when the production package
        # is not on the PYTHONPATH.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from jpintel_mcp.billing import stripe_edge_cases  # type: ignore[import-not-found]
    except ImportError:
        logger.info(
            "stripe_credit_skipped reason=billing_module_missing key=%d yen=%d",
            api_key_id,
            yen,
        )
        return False

    issuer = getattr(stripe_edge_cases, "issue_credit_note_for_api_key", None)
    if issuer is None:
        logger.info(
            "stripe_credit_skipped reason=helper_not_implemented key=%d yen=%d",
            api_key_id,
            yen,
        )
        return False
    try:
        issuer(api_key_id=api_key_id, amount_yen=yen, reason="narrative_corrected")
        return True
    except Exception as exc:  # noqa: BLE001 — operator-side, log and continue
        logger.warning(
            "stripe_credit_failed key=%d yen=%d err=%s",
            api_key_id,
            yen,
            str(exc)[:160],
        )
        return False


def _postmark_email(api_key_id: int, narrative_id: int, n_requests: int) -> bool:
    """Send the operator-side narrative_corrected email via Postmark."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from jpintel_mcp.email import get_client  # type: ignore[import-not-found]
    except ImportError:
        logger.info(
            "postmark_email_skipped reason=email_module_missing key=%d",
            api_key_id,
        )
        return False
    try:
        client = get_client()
        send = getattr(client, "send_with_template", None)
        if send is None:
            logger.info(
                "postmark_email_skipped reason=template_helper_missing key=%d",
                api_key_id,
            )
            return False
        send(
            template_alias="narrative_corrected",
            template_model={
                "narrative_id": narrative_id,
                "n_requests": n_requests,
                "credit_yen": n_requests * 3,
            },
            api_key_id=api_key_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("postmark_email_failed key=%d err=%s", api_key_id, str(exc)[:160])
        return False


def rollback(*, db_path: Path, quarantine_id: int, dry_run: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    summary: dict = {
        "quarantine_id": quarantine_id,
        "narrative_id": None,
        "narrative_table": None,
        "affected_api_keys": 0,
        "stripe_credits": 0,
        "emails_sent": 0,
        "cf_purged": False,
        "dry_run": dry_run,
    }
    try:
        row = conn.execute(
            "SELECT narrative_id, narrative_table FROM am_narrative_quarantine "
            "WHERE quarantine_id = ?",
            (quarantine_id,),
        ).fetchone()
        if row is None:
            logger.warning("quarantine_id_not_found quarantine_id=%d", quarantine_id)
            return summary
        narrative_id = int(row["narrative_id"])
        table = str(row["narrative_table"])
        summary["narrative_id"] = narrative_id
        summary["narrative_table"] = table

        if not dry_run:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    f"UPDATE {table} SET is_active=0 WHERE narrative_id=?",
                    (narrative_id,),
                )

        tag = f"narrative:{table}:{narrative_id}"
        if dry_run:
            logger.info("cf_purge_dry_run tag=%s", tag)
        else:
            summary["cf_purged"] = _purge_cf_cache(tag)

        # 30-day fan-out from am_narrative_serve_log.
        try:
            affected = conn.execute(
                "SELECT api_key_id, COUNT(*) AS n "
                "  FROM am_narrative_serve_log "
                " WHERE narrative_id = ? AND narrative_table = ? "
                "   AND served_at >= datetime('now','-30 days') "
                "   AND api_key_id IS NOT NULL "
                " GROUP BY api_key_id",
                (narrative_id, table),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("serve_log_select_failed err=%s", str(exc)[:160])
            affected = []

        summary["affected_api_keys"] = len(affected)
        for r in affected:
            kid = int(r["api_key_id"])
            n = int(r["n"])
            if dry_run:
                logger.info("credit_dry_run key=%d n=%d yen=%d", kid, n, n * 3)
                continue
            if _stripe_credit(kid, n * 3):
                summary["stripe_credits"] += 1
            if _postmark_email(kid, narrative_id, n):
                summary["emails_sent"] += 1

        if not dry_run:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "UPDATE am_narrative_quarantine "
                    "SET resolved_at = ?, resolution = 'rolled_back' "
                    "WHERE quarantine_id = ?",
                    (datetime.now(UTC).isoformat(), quarantine_id),
                )
            conn.commit()
    finally:
        conn.close()
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="§10.10 narrative rollback + customer-credit helper")
    p.add_argument("--db", type=Path, default=None)
    p.add_argument("--quarantine-id", type=int, required=True)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = _resolve_db_path(args.db)
    summary = rollback(
        db_path=db_path,
        quarantine_id=int(args.quarantine_id),
        dry_run=bool(args.dry_run),
    )
    logger.info("rollback_done %s", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
