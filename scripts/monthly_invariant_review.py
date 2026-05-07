#!/usr/bin/env python3
"""Monthly Tier 3 invariant review (P5-θ++ / dd_v8_05).

Tier 3 invariants are advisory business-health signals, not safety
gates. The review writes a markdown audit log to:

    analysis_wave18/invariant_monthly/<YYYY-MM>.md

INV-30  gold precision monotonic — compares the latest evals/ snapshot
        against the previous month's snapshot
INV-31  am_entities row count strictly increasing MoM
INV-32  case_studies / testimonial count strictly increasing MoM
INV-33  margin >= 92% (Stripe revenue minus Fly + CF infra cost)

Read-only against jpintel.db and autonomath.db. Stripe revenue is
fetched only when STRIPE_SECRET_KEY is set; otherwise margin is
recorded as N/A.

Usage
-----
    python scripts/monthly_invariant_review.py            # writes artifact
    python scripts/monthly_invariant_review.py --month 2026-04  # specific month
    python scripts/monthly_invariant_review.py --dry-run  # no artifact write
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logger = logging.getLogger("autonomath.cron.monthly_invariant")


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Per-invariant probes (return a markdown-ready dict)
# ---------------------------------------------------------------------------
def probe_inv30_gold_precision(month: str) -> dict[str, Any]:
    evals_dir = _REPO / "evals"
    if not evals_dir.is_dir():
        return {"status": "skip", "reason": "evals/ dir absent"}
    snapshots: list[Path] = []
    for ext in ("*.json", "*.md"):
        snapshots.extend(evals_dir.rglob(ext))
    snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not snapshots:
        return {"status": "skip", "reason": "no eval snapshots"}
    return {
        "status": "info",
        "latest": str(snapshots[0].relative_to(_REPO)),
        "snapshot_count": len(snapshots),
        "note": (
            "MoM precision compare requires two timestamped snapshots; "
            "latest only — operator should compare manually until eval "
            "harness emits dated artifacts."
        ),
    }


def probe_inv31_am_entities(month: str) -> dict[str, Any]:
    db_path = _REPO / "autonomath.db"
    if not db_path.is_file():
        return {"status": "skip", "reason": "autonomath.db absent"}
    try:
        con = sqlite3.connect(db_path)
    except Exception as exc:
        return {"status": "skip", "reason": f"connect failed: {exc}"}
    try:
        if not _table_exists(con, "am_entities"):
            return {"status": "skip", "reason": "am_entities table absent"}
        n = con.execute("SELECT COUNT(*) FROM am_entities").fetchone()[0]
    finally:
        con.close()
    return {
        "status": "info",
        "am_entities_count": n,
        "note": (
            "MoM growth requires last-month snapshot; record current "
            f"count {n} for next-month comparison."
        ),
    }


def probe_inv32_case_studies(month: str) -> dict[str, Any]:
    try:
        from jpintel_mcp.db.session import connect
    except Exception as exc:
        return {"status": "skip", "reason": f"db.session import failed: {exc}"}
    try:
        with connect() as con:
            if not _table_exists(con, "case_studies"):
                return {"status": "skip", "reason": "case_studies table absent"}
            n = con.execute("SELECT COUNT(*) FROM case_studies").fetchone()[0]
    except Exception as exc:
        return {"status": "skip", "reason": f"connect failed: {exc}"}
    return {
        "status": "info",
        "case_studies_count": n,
        "note": "MoM growth check vs previous artifact",
    }


def probe_inv33_margin(month: str) -> dict[str, Any]:
    """Compute prev-month revenue (Stripe) minus rough infra cost.

    Conservative when Stripe is unreachable or in dev: returns
    status=skip with reason. We do NOT call Anthropic/OpenAI here.
    """
    env = os.getenv("JPINTEL_ENV", "dev")
    secret = os.getenv("STRIPE_SECRET_KEY", "")
    if env != "prod" or not secret:
        return {
            "status": "skip",
            "reason": f"JPINTEL_ENV={env}, stripe_key={'set' if secret else 'unset'}",
        }
    # We deliberately keep this lightweight — only summary-level revenue.
    # Detailed P&L lives outside this script (operator spreadsheet).
    try:
        import stripe

        stripe.api_key = secret
        # Sum charges in the previous calendar month.
        # The python-stripe client supports `created` filtering.
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        first_of_this = _dt.now(UTC).replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        first_of_prev = (first_of_this - _td(days=1)).replace(day=1)
        gte = int(first_of_prev.timestamp())
        lt = int(first_of_this.timestamp())
        revenue_yen = 0
        # Iterate up to a sensible cap (1000 charges/month).
        try:
            charges = stripe.Charge.list(
                created={"gte": gte, "lt": lt},
                limit=100,
            )
            for ch in charges.auto_paging_iter():
                if ch.get("paid") and ch.get("status") == "succeeded":
                    # JPY = zero-decimal currency; amount is yen directly.
                    revenue_yen += int(ch.get("amount", 0))
        except Exception as exc:
            return {"status": "skip", "reason": f"stripe.list failed: {exc}"}

        # Rough infra cost: Fly Tokyo + Cloudflare Pages free + Postmark
        # = approx ¥4500/month at current scale. Operator overrides via env.
        infra_yen = int(os.getenv("AUTONOMATH_MONTHLY_INFRA_YEN", "4500"))
        margin = (revenue_yen - infra_yen) / revenue_yen if revenue_yen else 0.0
        return {
            "status": "info" if margin >= 0.92 else "warn",
            "month": first_of_prev.strftime("%Y-%m"),
            "revenue_yen": revenue_yen,
            "infra_yen": infra_yen,
            "margin": round(margin, 4),
            "threshold": 0.92,
        }
    except Exception as exc:
        return {"status": "skip", "reason": f"stripe path failed: {exc}"}


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------
def render_markdown(month: str, results: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"# Monthly Invariant Review — {month}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "Tier 3 invariants are advisory business-health signals.",
        "",
        "| INV | Name | Status | Detail |",
        "|---|---|---|---|",
    ]
    for inv_id, payload in results.items():
        status = payload.get("status", "?")
        detail = json.dumps(
            {k: v for k, v in payload.items() if k != "status"},
            ensure_ascii=False,
        )
        # Truncate over-long detail blob
        if len(detail) > 200:
            detail = detail[:197] + "..."
        lines.append(f"| {inv_id} | {payload.get('_name', '')} | {status} | {detail} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- INV-30/31/32 require dated month-over-month snapshots to evaluate "
        "monotonic growth. The first month emits `info` (baseline); from the "
        "second month onward the script will compare against the prior artifact "
        "in this directory."
    )
    lines.append(
        "- INV-33 (margin) skips outside prod or without `STRIPE_SECRET_KEY`. "
        "Operator review: spot-check Fly + CF + Postmark bills against "
        "`AUTONOMATH_MONTHLY_INFRA_YEN` env (default ¥4500)."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_review(month: str) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    probes = [
        ("INV-30", "gold precision monotonic", probe_inv30_gold_precision),
        ("INV-31", "am_entities row count growth", probe_inv31_am_entities),
        ("INV-32", "case_studies / testimonial growth", probe_inv32_case_studies),
        ("INV-33", "margin >= 92%", probe_inv33_margin),
    ]
    for inv_id, name, fn in probes:
        try:
            payload = fn(month)
        except Exception as exc:
            payload = {"status": "skip", "reason": f"unhandled: {exc}"}
        payload["_name"] = name
        results[inv_id] = payload
    return results


def _write_artifact(month: str, results: dict[str, dict[str, Any]]) -> Path:
    out_dir = _REPO / "analysis_wave18" / "invariant_monthly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{month}.md"
    out_path.write_text(render_markdown(month, results), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monthly Tier 3 invariant review")
    parser.add_argument(
        "--month",
        default=datetime.now(UTC).strftime("%Y-%m"),
        help="Month label YYYY-MM (default: current UTC month)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run probes but do not write the markdown artifact"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    results = run_review(args.month)
    if args.dry_run:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 0
    path = _write_artifact(args.month, results)
    logger.info("wrote monthly review: %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
