#!/usr/bin/env python3
"""Daily kintone sync — saved_searches × integration_accounts (provider=kintone).

For every saved_search whose owning api_key has a kintone credential row,
re-runs the canonical search and POSTs the result rows into the
customer's kintone app via /k/v1/records.json.

Pricing (project_autonomath_business_model — immutable):
  Each delivered SYNC counts as ONE ¥3 request, NOT one-per-row. A 100-row
  bulk push is ¥3, not ¥300. Idempotency via integration_sync_log
  (provider='kintone', idempotency_key='ss{id}-YYYYMMDD').

Constraints:
  * No Anthropic / SDK calls. Pure SQLite + urllib.
  * Re-runs the same `_build_search_response` body builder as the live
    REST surface so the result matches what the customer would see via
    GET /v1/programs/search.
  * On HTTP 4xx/5xx from kintone the row is logged with status='error'
    and error_class — NO Stripe usage_record fires (consistent with the
    failed-delivery rule used by dispatch_webhooks.py).

Cron cadence: invoked daily at 04:30 JST via .github/workflows/
saved-searches-cron.yml (existing job — extends with --kintone flag).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Allow `python scripts/cron/sync_kintone.py` from repo root.
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "src"))

from jpintel_mcp.api._integration_tokens import load_account, record_sync  # noqa: E402
from jpintel_mcp.api.integrations import (  # noqa: E402
    MAX_INTEGRATION_RESULTS,
    _row_summary,
)
from jpintel_mcp.api.programs import _build_search_response  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("kintone.sync")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DB_PATH = os.environ.get("JPINTEL_DB_PATH", str(_REPO / "data" / "jpintel.db"))


def _push_records(
    domain: str, app_id: int, api_token: str, records: list[dict]
) -> tuple[int, str | None]:
    """Push records to kintone. Returns (posted_count, error_class)."""
    if not records:
        return 0, None
    try:
        req = urllib.request.Request(
            f"https://{domain}/k/v1/records.json",
            method="POST",
            data=json.dumps({"app": app_id, "records": records}, ensure_ascii=False).encode(
                "utf-8"
            ),
            headers={
                "Content-Type": "application/json",
                "X-Cybozu-API-Token": api_token,
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
            if 200 <= resp.status < 300:
                return len(records), None
            return 0, f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return 0, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


def _run() -> dict[str, int]:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    today = datetime.now(UTC).strftime("%Y%m%d")

    # Saved searches whose owning key has an active kintone account.
    rows = db.execute(
        """
        SELECT s.id AS saved_search_id, s.api_key_hash, s.query_json,
               s.name AS saved_name
          FROM saved_searches s
          JOIN integration_accounts a
            ON a.api_key_hash = s.api_key_hash
           AND a.provider = 'kintone'
           AND a.revoked_at IS NULL
        """
    ).fetchall()
    logger.info("kintone.sync candidates=%d", len(rows))

    delivered = 0
    skipped_dup = 0
    errored = 0

    for row in rows:
        idem_key = f"ss{row['saved_search_id']}-{today}"
        creds = load_account(db, api_key_hash=row["api_key_hash"], provider="kintone")
        if creds is None:
            logger.warning(
                "kintone.sync.creds_missing saved_search_id=%s",
                row["saved_search_id"],
            )
            continue

        try:
            query = json.loads(row["query_json"]) if row["query_json"] else {}
        except json.JSONDecodeError:
            query = {}

        body = _build_search_response(
            conn=db,
            q=query.get("q"),
            tier=None,
            prefecture=query.get("prefecture"),
            authority_level=query.get("authority_level"),
            funding_purpose=query.get("funding_purpose"),
            target_type=query.get("target_type"),
            amount_min=None,
            amount_max=None,
            include_excluded=False,
            limit=MAX_INTEGRATION_RESULTS,
            offset=0,
            fields="default",
            include_advisors=False,
            as_of_iso=None,
        )
        results = (body or {}).get("results", []) if isinstance(body, dict) else []
        records = []
        for r in results:
            s = _row_summary(r)
            records.append(
                {
                    "title": {"value": s["name"]},
                    "prefecture": {"value": s["prefecture"]},
                    "authority": {"value": s["authority"]},
                    "amount_label": {"value": s["amount"]},
                    "source_url": {"value": s["url"]},
                    "synced_by": {"value": "AutonoMath"},
                }
            )
        # Pre-flight idempotency check — if today's row already exists,
        # skip the POST so a cron re-run does not double-post.
        is_new, _ = record_sync(
            db,
            api_key_hash=row["api_key_hash"],
            provider="kintone",
            idempotency_key=idem_key,
            saved_search_id=row["saved_search_id"],
            status_label="ok",
            result_count=len(records),
        )
        if not is_new:
            skipped_dup += 1
            logger.info(
                "kintone.sync.dedup ss=%s key=%s",
                row["saved_search_id"],
                idem_key,
            )
            continue

        posted, error_class = _push_records(
            creds["domain"], int(creds["app_id"]), creds["api_token"], records
        )
        if error_class:
            errored += 1
            db.execute(
                "UPDATE integration_sync_log SET status='error', error_class=? "
                "WHERE provider='kintone' AND idempotency_key=?",
                (error_class, idem_key),
            )
            db.commit()
            logger.warning(
                "kintone.sync.err ss=%s err=%s",
                row["saved_search_id"],
                error_class,
            )
            continue

        # Stripe usage_record happens via report_usage_async at the REST
        # call sites; the cron path bills via the existing
        # `saved_searches.digest` event family — log_usage is invoked by
        # whichever cron orchestrator wraps this script. Here we ONLY emit
        # a structured INFO so downstream prometheus / sentry can count.
        delivered += 1
        logger.info("kintone.sync.ok ss=%s rows=%d", row["saved_search_id"], posted)

    logger.info(
        "kintone.sync.done delivered=%d skipped_dup=%d errored=%d",
        delivered,
        skipped_dup,
        errored,
    )
    db.close()
    return {
        "delivered": delivered,
        "skipped_dup": skipped_dup,
        "errored": errored,
        "candidates": len(rows),
    }


def main() -> int:
    with heartbeat("sync_kintone") as hb:
        counters = _run()
        hb["rows_processed"] = int(counters.get("delivered", 0) or 0)
        hb["rows_skipped"] = int(counters.get("skipped_dup", 0) or 0)
        hb["metadata"] = {
            "candidates": counters.get("candidates"),
            "errored": counters.get("errored"),
        }
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
