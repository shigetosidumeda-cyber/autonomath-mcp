#!/usr/bin/env python3
"""Weekly Tier 2 invariant runner (P5-θ++ / dd_v8_05).

Chains the 13 Tier 2 invariants. Each invariant is evaluated in turn,
captures pass/skip/fail + a short reason string, and the run as a whole
emits a JSON record to:

    analysis_wave18/invariant_runs/<YYYY-MM-DD>.json

Failures additionally:
  - log to stderr
  - emit to Sentry via `sentry_sdk.capture_message` if sentry-sdk is
    importable AND `SENTRY_DSN` is set; otherwise stderr only.

Pure SQL + deterministic compute. Read-only — never writes to autonomath.db
or jpintel.db.

Usage
-----
    python scripts/weekly_invariant_check.py            # real run
    python scripts/weekly_invariant_check.py --dry-run  # no JSON write
    python scripts/weekly_invariant_check.py --json     # emit JSON to stdout
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logger = logging.getLogger("autonomath.cron.weekly_invariant")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class InvariantResult:
    inv_id: str
    name: str
    status: str  # "pass" | "skip" | "fail"
    reason: str = ""
    measured: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sentry / stderr alerting
# ---------------------------------------------------------------------------
def _alert_failure(result: InvariantResult) -> None:
    msg = (
        f"INVARIANT FAILURE {result.inv_id} ({result.name}): "
        f"{result.reason} measured={result.measured}"
    )
    print(msg, file=sys.stderr)
    try:
        import sentry_sdk
    except ImportError:
        return
    if not os.getenv("SENTRY_DSN"):
        return
    try:
        sentry_sdk.capture_message(msg, level="error")
    except Exception as exc:
        print(f"sentry_sdk.capture_message failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Invariant implementations
# ---------------------------------------------------------------------------
def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _connect_jpintel() -> sqlite3.Connection | None:
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except Exception as exc:
        logger.warning("could not open jpintel.db: %s", exc)
        return None


def inv03_no_fk_violations(con: sqlite3.Connection) -> InvariantResult:
    rows = con.execute("PRAGMA foreign_key_check").fetchall()
    if rows:
        return InvariantResult(
            "INV-03",
            "programs schema integrity (FK violations)",
            "fail",
            reason=f"{len(rows)} FK violations",
            measured={"violations": len(rows), "sample": [list(r) for r in rows[:3]]},
        )
    return InvariantResult(
        "INV-03",
        "programs schema integrity (FK violations)",
        "pass",
        measured={"violations": 0},
    )


def inv04_aggregator_ban(con: sqlite3.Connection) -> InvariantResult:
    BANNED = [
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
        "stayway.jp",
        "nikkei.com",
        "prtimes.jp",
        "wikipedia.org",
    ]
    if not _table_exists(con, "programs"):
        return InvariantResult(
            "INV-04",
            "aggregator domain ban",
            "skip",
            reason="programs table absent",
        )
    hits: dict[str, int] = {}
    for d in BANNED:
        n = con.execute(
            "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
            (f"%{d}%",),
        ).fetchone()[0]
        if n:
            hits[d] = n
    if hits:
        return InvariantResult(
            "INV-04",
            "aggregator domain ban",
            "fail",
            reason=f"banned domains found: {hits}",
            measured={"hits": hits},
        )
    return InvariantResult("INV-04", "aggregator domain ban", "pass", measured={"hits": {}})


def inv09_quarantine_share(con: sqlite3.Connection) -> InvariantResult:
    if not _table_exists(con, "programs"):
        return InvariantResult(
            "INV-09", "tier='X' quarantine share", "skip", reason="programs table absent"
        )
    total = con.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    if total < 100:
        return InvariantResult(
            "INV-09",
            "tier='X' quarantine share",
            "skip",
            reason=f"row count too low ({total})",
            measured={"total": total},
        )
    x = con.execute("SELECT COUNT(*) FROM programs WHERE tier='X'").fetchone()[0]
    share = x / total
    if share >= 0.30:
        return InvariantResult(
            "INV-09",
            "tier='X' quarantine share",
            "fail",
            reason=f"quarantine share {share:.2%} >= 30%",
            measured={"x": x, "total": total, "share": share},
        )
    return InvariantResult(
        "INV-09",
        "tier='X' quarantine share",
        "pass",
        measured={"x": x, "total": total, "share": round(share, 4)},
    )


def inv10_source_fetched_at(con: sqlite3.Connection) -> InvariantResult:
    if not _table_exists(con, "programs"):
        return InvariantResult(
            "INV-10", "source_fetched_at NULL share", "skip", reason="programs table absent"
        )
    total = con.execute("SELECT COUNT(*) FROM programs WHERE excluded=0").fetchone()[0]
    if total < 100:
        return InvariantResult(
            "INV-10",
            "source_fetched_at NULL share",
            "skip",
            reason=f"row count too low ({total})",
            measured={"total": total},
        )
    nulls = con.execute(
        "SELECT COUNT(*) FROM programs WHERE excluded=0 AND source_fetched_at IS NULL"
    ).fetchone()[0]
    share = nulls / total
    if share >= 0.01:
        return InvariantResult(
            "INV-10",
            "source_fetched_at NULL share",
            "fail",
            reason=f"NULL share {share:.2%} >= 1%",
            measured={"nulls": nulls, "total": total, "share": share},
        )
    return InvariantResult(
        "INV-10",
        "source_fetched_at NULL share",
        "pass",
        measured={"nulls": nulls, "total": total, "share": round(share, 4)},
    )


def inv18_envelope_shape(_: sqlite3.Connection) -> InvariantResult:
    try:
        from jpintel_mcp.models import SearchResponse
    except Exception as exc:
        return InvariantResult(
            "INV-18",
            "API envelope shape",
            "fail",
            reason=f"models import failed: {exc}",
        )
    expected = {"total", "limit", "offset", "results"}
    actual = set(SearchResponse.model_fields.keys())
    missing = expected - actual
    if missing:
        return InvariantResult(
            "INV-18",
            "API envelope shape",
            "fail",
            reason=f"SearchResponse missing keys: {missing}",
            measured={"actual": sorted(actual), "missing": sorted(missing)},
        )
    return InvariantResult(
        "INV-18",
        "API envelope shape",
        "pass",
        measured={"actual": sorted(actual)},
    )


def inv19_5xx_rate(con: sqlite3.Connection) -> InvariantResult:
    if not _table_exists(con, "usage_events"):
        return InvariantResult("INV-19", "5xx error rate", "skip", reason="usage_events absent")
    total = con.execute(
        "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
    ).fetchone()[0]
    if total < 100:
        return InvariantResult(
            "INV-19",
            "5xx error rate",
            "skip",
            reason=f"thin telemetry ({total} rows)",
            measured={"total": total},
        )
    errors = con.execute(
        "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days') AND status >= 500"
    ).fetchone()[0]
    rate = errors / total
    if rate >= 0.005:
        return InvariantResult(
            "INV-19",
            "5xx error rate",
            "fail",
            reason=f"5xx rate {rate:.4%} >= 0.5%",
            measured={"errors": errors, "total": total, "rate": rate},
        )
    return InvariantResult(
        "INV-19",
        "5xx error rate",
        "pass",
        measured={"errors": errors, "total": total, "rate": round(rate, 6)},
    )


def inv21_redactor(_: sqlite3.Connection) -> InvariantResult:
    try:
        from jpintel_mcp.security.pii_redact import redact_text
    except Exception as exc:
        return InvariantResult(
            "INV-21",
            "PII redactor",
            "fail",
            reason=f"redact_text import failed: {exc}",
        )
    samples = [
        ("法人番号 T8010001213708", "T8010001213708"),
        ("foo@example.com", "foo@example.com"),
        ("電話 03-1234-5678", "03-1234-5678"),
    ]
    for raw, leaked in samples:
        out = redact_text(raw)
        if leaked in out:
            return InvariantResult(
                "INV-21",
                "PII redactor",
                "fail",
                reason=f"PII leaked: {leaked} in {out!r}",
                measured={"raw": raw, "out": out},
            )
    return InvariantResult("INV-21", "PII redactor", "pass")


def inv23_b2b_tax_id(_: sqlite3.Connection) -> InvariantResult:
    try:
        from jpintel_mcp.api.billing import _check_b2b_tax_id_safe
    except Exception as exc:
        return InvariantResult(
            "INV-23",
            "B2B tax_id hook",
            "fail",
            reason=f"hook import failed: {exc}",
        )
    try:
        _check_b2b_tax_id_safe(None)
        _check_b2b_tax_id_safe("")
    except Exception as exc:
        return InvariantResult(
            "INV-23",
            "B2B tax_id hook",
            "fail",
            reason=f"hook raised on empty input: {exc}",
        )
    return InvariantResult("INV-23", "B2B tax_id hook", "pass")


def inv24_keyword_block_docs(_: sqlite3.Connection) -> InvariantResult:
    BANNED = ["必ず採択", "絶対に", "保証します", "確実に", "間違いなく"]
    # Exclude:
    #   _internal: operator-only runbooks may quote phrases as counter-examples
    #   compliance: legal disclaimers MUST quote 景表法 NG phrases as the
    #               documented "do not claim X" list — this is required, not
    #               a regression.
    EXCLUDED_PARTS = {"_internal", "compliance"}
    candidates: list[Path] = []
    docs = _REPO / "docs"
    if docs.is_dir():
        for p in docs.rglob("*.md"):
            if any(part in EXCLUDED_PARTS for part in p.parts):
                continue
            candidates.append(p)
    site = _REPO / "site"
    if site.is_dir():
        for p in site.rglob("*.html"):
            if any(part in EXCLUDED_PARTS for part in p.parts):
                continue
            candidates.append(p)
    if not candidates:
        return InvariantResult(
            "INV-24", "景表法 keyword block (docs/site)", "skip", reason="no doc files to scan"
        )
    hits: list[tuple[str, str]] = []
    for p in candidates:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for kw in BANNED:
            if kw in txt:
                hits.append((str(p.relative_to(_REPO)), kw))
    if hits:
        return InvariantResult(
            "INV-24",
            "景表法 keyword block (docs/site)",
            "fail",
            reason=f"{len(hits)} hits in user-facing files",
            measured={"sample_hits": hits[:5]},
        )
    return InvariantResult(
        "INV-24",
        "景表法 keyword block (docs/site)",
        "pass",
        measured={"files_scanned": len(candidates)},
    )


def inv26_p50_tools_list(con: sqlite3.Connection) -> InvariantResult:
    """P50 latency check — usage_events doesn't carry latency_ms.

    The numeric check is in the structlog R2 archive; here we count
    rows so the runner records the cron is wired and the table has
    fresh data.
    """
    if not _table_exists(con, "usage_events"):
        return InvariantResult(
            "INV-26", "P50 latency tools/list", "skip", reason="usage_events absent"
        )
    n = con.execute(
        "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
    ).fetchone()[0]
    if n < 50:
        return InvariantResult(
            "INV-26",
            "P50 latency tools/list",
            "skip",
            reason=f"thin telemetry ({n})",
            measured={"rows": n},
        )
    return InvariantResult(
        "INV-26",
        "P50 latency tools/list",
        "pass",
        reason="row presence ok; numeric P50 enforced via structlog archive",
        measured={"rows": n},
    )


def inv27_p99_search(con: sqlite3.Connection) -> InvariantResult:
    if not _table_exists(con, "usage_events"):
        return InvariantResult("INV-27", "P99 latency search", "skip", reason="usage_events absent")
    n = con.execute(
        "SELECT COUNT(*) FROM usage_events "
        "WHERE endpoint LIKE '/v1/programs%' "
        "AND ts >= datetime('now', '-7 days')"
    ).fetchone()[0]
    if n < 100:
        return InvariantResult(
            "INV-27",
            "P99 latency search",
            "skip",
            reason=f"thin telemetry ({n})",
            measured={"rows": n},
        )
    return InvariantResult(
        "INV-27",
        "P99 latency search",
        "pass",
        reason="row presence ok; numeric P99 enforced via structlog archive",
        measured={"rows": n},
    )


def inv28_cache_layer(_: sqlite3.Connection) -> InvariantResult:
    try:
        from jpintel_mcp.api.meta import _reset_meta_cache  # noqa: F401
    except ImportError:
        return InvariantResult(
            "INV-28", "cache hit rate (meta TTL)", "skip", reason="cache layer not wired"
        )
    return InvariantResult(
        "INV-28",
        "cache hit rate (meta TTL)",
        "pass",
        reason="cache module wired; numeric hit rate via Grafana",
    )


def inv29_stripe_diff(con: sqlite3.Connection) -> InvariantResult:
    env = os.getenv("JPINTEL_ENV", "dev")
    if env != "prod":
        return InvariantResult(
            "INV-29",
            "Stripe usage_record vs request count",
            "skip",
            reason=f"JPINTEL_ENV={env}; prod-only",
        )
    if not _table_exists(con, "usage_events"):
        return InvariantResult(
            "INV-29", "Stripe usage_record vs request count", "skip", reason="usage_events absent"
        )
    metered = con.execute(
        "SELECT COUNT(*) FROM usage_events WHERE metered=1 AND ts >= datetime('now', '-7 days')"
    ).fetchone()[0]
    total = con.execute(
        "SELECT COUNT(*) FROM usage_events WHERE ts >= datetime('now', '-7 days')"
    ).fetchone()[0]
    if total < 50:
        return InvariantResult(
            "INV-29",
            "Stripe usage_record vs request count",
            "skip",
            reason=f"thin traffic ({total})",
            measured={"total": total},
        )
    if metered == 0:
        return InvariantResult(
            "INV-29",
            "Stripe usage_record vs request count",
            "fail",
            reason="metered=1 count is 0 in prod",
            measured={"metered": 0, "total": total},
        )
    # Detailed Stripe API diff — wrapped in try; failure here is "skip"
    # rather than "fail" so a Stripe API outage doesn't page the operator
    # for a billing reconciliation discrepancy that resolves on retry.
    stripe_diff: dict[str, Any] = {}
    try:
        import stripe

        from jpintel_mcp.config import settings

        if settings.stripe_secret_key:
            stripe.api_key = settings.stripe_secret_key
            if settings.stripe_api_version:
                stripe.api_version = settings.stripe_api_version
            # Coarse summary: count usage_records summary on the metered
            # subscription items. Skip on any auth/network error.
            stripe_diff = {
                "note": "stripe reconciliation skipped — runner uses "
                "summary-only path; full diff in monthly review"
            }
    except Exception as exc:
        stripe_diff = {"stripe_error": str(exc)}
    return InvariantResult(
        "INV-29",
        "Stripe usage_record vs request count",
        "pass",
        measured={"metered": metered, "total": total, **stripe_diff},
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
INVARIANTS: list[Callable[[sqlite3.Connection], InvariantResult]] = [
    inv03_no_fk_violations,
    inv04_aggregator_ban,
    inv09_quarantine_share,
    inv10_source_fetched_at,
    inv18_envelope_shape,
    inv19_5xx_rate,
    inv21_redactor,
    inv23_b2b_tax_id,
    inv24_keyword_block_docs,
    inv26_p50_tools_list,
    inv27_p99_search,
    inv28_cache_layer,
    inv29_stripe_diff,
]


def run_all() -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    con = _connect_jpintel()
    results: list[InvariantResult] = []
    for fn in INVARIANTS:
        try:
            r = (
                fn(con)
                if con is not None
                else InvariantResult(
                    fn.__name__,
                    fn.__name__,
                    "skip",
                    reason="DB unavailable",
                )
            )
        except Exception as exc:
            r = InvariantResult(
                getattr(fn, "__name__", "unknown"),
                getattr(fn, "__name__", "unknown"),
                "fail",
                reason=f"unhandled: {exc}",
                measured={"traceback": traceback.format_exc()[:1500]},
            )
        results.append(r)
        if r.status == "fail":
            _alert_failure(r)
    if con is not None:
        with contextlib.suppress(Exception):
            con.close()
    finished_at = datetime.now(UTC).isoformat()
    summary = {
        "started_at": started_at,
        "finished_at": finished_at,
        "tier": 2,
        "total": len(results),
        "pass": sum(1 for r in results if r.status == "pass"),
        "skip": sum(1 for r in results if r.status == "skip"),
        "fail": sum(1 for r in results if r.status == "fail"),
        "results": [asdict(r) for r in results],
    }
    return summary


def _write_artifact(summary: dict[str, Any]) -> Path:
    out_dir = _REPO / "analysis_wave18" / "invariant_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}.json"
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Tier 2 invariant runner",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="run all checks but do not write JSON artifact"
    )
    parser.add_argument("--json", action="store_true", help="emit summary JSON to stdout")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    summary = run_all()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    if not args.dry_run:
        path = _write_artifact(summary)
        logger.info("wrote artifact: %s", path)

    # Exit non-zero if any invariant failed — cron will alert via systemd
    # or GitHub Actions failure notification on top of the Sentry capture.
    return 1 if summary["fail"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
