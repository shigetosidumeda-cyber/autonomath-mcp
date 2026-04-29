#!/usr/bin/env python3
"""Daily cron: revoke expired trial API keys.

Sweeps `api_keys WHERE tier='trial' AND revoked_at IS NULL` and revokes
any row matching either expiration condition:

    * `trial_expires_at <= now()`        — 14-day deadline reached
    * `trial_requests_used >= 200`        — request cap exhausted

Both conditions are independent. The request middleware can also short-
circuit on cap exhaustion immediately (CustomerCapMiddleware path), but
we belt-and-suspenders here so a window between cap-hit and middleware
short-circuit cannot leave a key live indefinitely.

Posture (matches scripts/cron/* peers):
    * Idempotent — re-running mid-day is safe; revoke_key skips already-
      revoked rows (UPDATE ... WHERE revoked_at IS NULL). The follow-up
      email enqueue is dedup-keyed so even an over-eager re-run cannot
      double-mail.
    * Single-process — invoked once a day from GitHub Actions cron via
      flyctl ssh. No locking concerns at trial-volume.
    * Best-effort email — when revoking we ALSO enqueue the
      `trial_expired_email` task into bg_task_queue so the durable worker
      picks it up. A failed enqueue is logged but does not block revoke.
    * Telemetry — emits one structured log line per run with counts and
      a Sentry breadcrumb (info-level when ok, error when revokes raise).

Wiring:
    * `.github/workflows/trial-expire-cron.yml` runs this daily at 04:00
      JST (19:00 UTC) via flyctl ssh on the autonomath-api machine. See
      docs/_internal/cron_runbook.md (operator manual).

CLI:
    python scripts/cron/expire_trials.py             # real run
    python scripts/cron/expire_trials.py --dry-run   # log + count only
    python scripts/cron/expire_trials.py --limit 100 # cap revokes per run

Manual extension:
    A trial that the operator wants to extend (e.g. evaluator at a
    partner who needs another week) can be granted via SQL:

        UPDATE api_keys
           SET trial_expires_at = '2026-05-15T00:00:00+00:00'
         WHERE key_hash = '<hash>' AND tier = 'trial';

    The cron will respect the new value. There is intentionally NO API
    endpoint for extension — solo + zero-touch ops, no operator review
    surface (memory: feedback_zero_touch_solo).

No Anthropic / OpenAI / SDK calls. Pure SQL + bg_task_queue enqueue. The
existing async worker handles the post-revocation email send.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`. Mirrors the
# import preamble in scripts/cron/stripe_usage_backfill.py so cron jobs
# can be invoked directly via `python scripts/cron/expire_trials.py`
# from a base image that hasn't run editable-install.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue  # noqa: E402
from jpintel_mcp.billing.keys import revoke_key  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

try:  # observability is best-effort — never block cron on Sentry init
    from jpintel_mcp.observability import safe_capture_message  # noqa: E402
except Exception:  # pragma: no cover — defensive
    def safe_capture_message(*_a: Any, **_kw: Any) -> None:  # type: ignore[override]
        return None

logger = logging.getLogger("jpintel.cron.expire_trials")

# Same as TRIAL_REQUEST_CAP in api/signup.py — duplicated here so the cron
# stays self-contained (importing from api/signup pulls FastAPI into a
# pure DB script, which we want to avoid for cron isolation).
DEFAULT_REQUEST_CAP = 200

# Per-run safety cap. Without this, an operational error (e.g. clock-skew
# pushing 10k trial_expires_at into the past) could revoke every key in
# one run, locking out paying evaluators in the middle of an evaluation.
# 1000 is two orders of magnitude above realistic post-launch open-trial
# volume, so a normal run will hit the natural end of rows long before
# the cap. Excess rolls into the next day's run.
DEFAULT_LIMIT = 1000


def _emit_event(name: str, payload: dict[str, Any]) -> None:
    try:
        record = {"event": name, **payload}
        logger.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:  # pragma: no cover — telemetry is best-effort
        pass


def expire_due_trials(
    *,
    now: datetime | None = None,
    request_cap: int = DEFAULT_REQUEST_CAP,
    dry_run: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, int]:
    """Revoke every trial key whose deadline OR cap is exhausted.

    Returns a small counts dict: ``{scanned, revoked_expired, revoked_cap,
    skipped_already_revoked, email_enqueued, errors, dry_run}``. Used by
    tests + the operator's daily summary log.

    Rows are revoked one at a time inside their own implicit txn so a
    crash mid-loop only leaves a small tail un-revoked (next run picks
    up). We do NOT use a single bulk UPDATE because the email-enqueue
    side-effect needs the per-row trial_email value.

    ``dry_run=True`` performs the SELECT and the per-row classification
    (cap vs expired) but skips revoke_key() and the bg_task_queue enqueue.
    Counts are still populated as if the run had committed, so the operator
    can ``--dry-run`` a daily cadence change before flipping live.

    ``limit`` caps how many rows we revoke in a single run. Defaults to
    1000 (well above realistic open-trial volume). The SELECT itself
    binds LIMIT so over-limit rows are not even pulled into memory.
    """
    ts = now or datetime.now(UTC)
    now_iso = ts.isoformat()
    counts: dict[str, int] = {
        "scanned": 0,
        "revoked_expired": 0,
        "revoked_cap": 0,
        "skipped_already_revoked": 0,
        "email_enqueued": 0,
        "errors": 0,
        "dry_run": 1 if dry_run else 0,
    }

    conn = connect()
    try:
        # Pull every candidate row (up to ``limit``) into memory up-front.
        # Trial volume is bounded (< 10k open at any time even at growth),
        # so a one-shot SELECT is cheaper than a cursor-driven scan. The
        # ORDER BY + LIMIT pair gives stable, oldest-first revocation
        # which is fairer to a rolling backlog than ROWID order.
        rows = conn.execute(
            """SELECT key_hash, trial_email, trial_expires_at,
                      trial_requests_used
                 FROM api_keys
                WHERE tier = 'trial'
                  AND revoked_at IS NULL
                  AND (trial_expires_at <= ?
                       OR trial_requests_used >= ?)
                ORDER BY trial_expires_at ASC
                LIMIT ?""",
            (now_iso, request_cap, max(0, int(limit))),
        ).fetchall()

        counts["scanned"] = len(rows)

        for row in rows:
            key_hash = row["key_hash"]
            trial_email = row["trial_email"]
            expires_at = row["trial_expires_at"]
            used = int(row["trial_requests_used"] or 0)
            cause = (
                "cap"
                if used >= request_cap and (
                    not expires_at or expires_at > now_iso
                )
                else "expired"
            )

            if dry_run:
                # Tally without mutating. Same report shape as a live run
                # so flipping --dry-run off is a zero-surprise change.
                if cause == "cap":
                    counts["revoked_cap"] += 1
                else:
                    counts["revoked_expired"] += 1
                if trial_email:
                    counts["email_enqueued"] += 1
                _emit_event(
                    "trial.expired.dry_run",
                    {
                        "key_hash_prefix": key_hash[:8],
                        "cause": cause,
                        "trial_requests_used": used,
                        "trial_expires_at": expires_at,
                    },
                )
                continue

            try:
                ok = revoke_key(conn, key_hash)
            except Exception:
                # A revoke that throws is the only condition we exit non-
                # zero on. The next row keeps going so a single bad row
                # doesn't strand the whole batch.
                counts["errors"] += 1
                logger.warning(
                    "expire_trials.revoke_key failed key=%s",
                    key_hash[:8],
                    exc_info=True,
                )
                continue
            if not ok:
                # Race: someone else revoked between SELECT and UPDATE.
                counts["skipped_already_revoked"] += 1
                continue

            if cause == "cap":
                counts["revoked_cap"] += 1
            else:
                counts["revoked_expired"] += 1

            # Best-effort post-expiration mail. Wrapped in try/except —
            # failing to enqueue must NOT block subsequent revokes. The
            # `trial_followup:{key_hash}` dedup key means a defensive
            # re-revoke (which can't actually re-revoke — revoke_key
            # short-circuits on revoked_at IS NOT NULL) still cannot
            # double-mail.
            if trial_email:
                try:
                    _bg_enqueue(
                        conn,
                        kind="trial_expired_email",
                        payload={
                            "to": trial_email,
                            "key_last4": key_hash[-4:],
                            "cause": cause,
                            # Append ?from=trial so pricing.html can fire
                            # the trial-attribution banner ("トライアル
                            # 終了から続行する場合は ¥3.30/req")
                            # — pre-fix the URL pointed at /pricing.html
                            # bare and the banner never lit (Bug 2 from
                            # the 2026-04-29 funnel audit). The hash
                            # fragment positions the user at the paid
                            # API card directly.
                            "checkout_url": (
                                "https://zeimu-kaikei.ai/"
                                "pricing.html?from=trial#api-paid"
                            ),
                        },
                        dedup_key=f"trial_followup:{key_hash}",
                    )
                    counts["email_enqueued"] += 1
                except Exception:
                    logger.warning(
                        "trial_expired_email enqueue failed key=%s",
                        key_hash[:8],
                        exc_info=True,
                    )

            _emit_event(
                "trial.expired",
                {
                    "key_hash_prefix": key_hash[:8],
                    "cause": cause,
                    "trial_requests_used": used,
                    "trial_expires_at": expires_at,
                },
            )
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    _emit_event("cron.expire_trials.summary", counts)

    # Sentry breadcrumb — info on a clean run, error if any revoke raised.
    # Cron schedulers (GitHub Actions) retry on non-zero exit, so we keep
    # a clean operator inbox by only escalating on real failures.
    with contextlib.suppress(Exception):  # telemetry is best-effort
        safe_capture_message(
            f"expire_trials: scanned={counts['scanned']} "
            f"revoked_expired={counts['revoked_expired']} "
            f"revoked_cap={counts['revoked_cap']} "
            f"skipped={counts['skipped_already_revoked']} "
            f"email_enqueued={counts['email_enqueued']} "
            f"errors={counts['errors']} "
            f"dry_run={dry_run}",
            level="error" if counts["errors"] > 0 else "info",
            scanned=str(counts["scanned"]),
            revoked_expired=str(counts["revoked_expired"]),
            revoked_cap=str(counts["revoked_cap"]),
            errors=str(counts["errors"]),
            dry_run=str(dry_run),
        )

    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Revoke expired trial API keys (daily cron).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the revoke set but do not write to api_keys / bg_task_queue.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=(
            f"Cap rows revoked per run (default {DEFAULT_LIMIT}). "
            "Excess rolls into the next run."
        ),
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    with heartbeat("expire_trials") as hb:
        counts = expire_due_trials(dry_run=args.dry_run, limit=args.limit)
        logger.info(
            "expire_trials.done scanned=%d revoked_expired=%d revoked_cap=%d "
            "skipped=%d email_enqueued=%d errors=%d dry_run=%s",
            counts["scanned"],
            counts["revoked_expired"],
            counts["revoked_cap"],
            counts["skipped_already_revoked"],
            counts["email_enqueued"],
            counts["errors"],
            bool(counts["dry_run"]),
        )
        hb["rows_processed"] = int(
            (counts.get("revoked_expired", 0) or 0)
            + (counts.get("revoked_cap", 0) or 0)
        )
        hb["rows_skipped"] = int(counts.get("skipped_already_revoked", 0) or 0)
        hb["metadata"] = {
            "scanned": counts.get("scanned"),
            "email_enqueued": counts.get("email_enqueued"),
            "errors": counts.get("errors"),
            "dry_run": bool(counts.get("dry_run", args.dry_run)),
        }
    # Emit JSON to stdout for grep / jq pipelines
    # (mirrors stripe_usage_backfill.py).
    print(json.dumps(counts, indent=2, ensure_ascii=False))

    # Exit non-zero only on revoke exceptions, so cron schedulers (GH
    # Actions) retry. Empty windows are normal — exit 0.
    return 1 if counts["errors"] > 0 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_REQUEST_CAP",
    "expire_due_trials",
    "main",
]
