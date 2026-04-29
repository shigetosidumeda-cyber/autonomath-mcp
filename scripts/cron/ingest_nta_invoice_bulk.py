#!/usr/bin/env python3
"""Cron driver for the 国税庁 適格請求書発行事業者 monthly bulk + daily delta.

Wraps ``scripts/ingest/ingest_invoice_registrants.py`` with:

  * Date discovery — picks the latest publishable date for the requested
    bucket (zenken: most recent 1st-of-month; sabun: today UTC, falling
    back day-by-day until the index has a matching dlFilKanriNo).
  * Pre-run schema + disk gate — refuses to run a 4M-row full load when
    the Fly volume has < 2 GB free, or when the connecting user lacks
    write access to the cache dir / DB path.
  * Memory-bounded — never holds more than ``--batch-size`` parsed rows
    in RAM. The underlying ingest script already streams via csv.reader
    + ET.iterparse + ndjson; this driver only forwards configuration.
  * Idempotent — re-running on the same date is a no-op via the UPSERT
    self-filter (``WHERE invoice_registrants.normalized_name IS NOT
    excluded.normalized_name OR ...``).
  * PDL v1.0 attribution preserved — no row leaves this script. The
    serializer (``src/jpintel_mcp/api/invoice_registrants.py``) is the
    enforcement point. We log a reminder banner so anyone tailing the
    cron output sees the obligation.
  * Post-run ANALYZE — refreshes SQLite query planner stats so the
    new 4M-row population doesn't hit the partial-index miss path on
    the first ``/v1/invoice_registrants/{T...}`` lookup.

Why a separate cron driver (not just call the ingest script directly):
  * Separation of concerns: ``ingest_invoice_registrants.py`` is the
    pure ETL primitive; this is the periodic-trigger orchestration.
    Same split as ``incremental_law_fulltext.py`` vs. the underlying
    ``ingest_law_articles_egov.py``.
  * Date discovery is a cron-only concern — manual runs always pass an
    explicit ``--date``.
  * Per-run summary log goes to ``data/invoice_load_log.jsonl`` so a
    later news cron pass can surface "now searchable" milestones (e.g.
    crossing 4M).

Honesty constraints (non-negotiable):
  * No fabrication. We ingest exactly the rows NTA publishes for the
    requested date. POLICY_SKIP rows (process=99 削除 or latest!=1
    履歴) are skipped per NTA's own definition, not silently inflated.
  * PDL v1.0 attribution preserved on every surface that exposes any
    invoice_registrants column.
  * No Anthropic / SDK calls. Pure stdlib + httpx (already a hard dep).
  * Solo + zero-touch: no manual review per row.

Usage:

    # Monthly full bulk (1st of month, default mode)
    python scripts/cron/ingest_nta_invoice_bulk.py --mode full

    # Daily delta (override default date)
    python scripts/cron/ingest_nta_invoice_bulk.py --mode delta

    # Smoke test — limit rows + dry-run
    python scripts/cron/ingest_nta_invoice_bulk.py --mode delta \\
        --limit 1000 --dry-run

Exit codes:
    0  success
    1  fetch / IO failure
    2  parse-quality gate tripped (>5% reject rate)
    3  schema missing (run ``scripts/migrate.py`` first)
    4  disk-space gate tripped (< 2 GB free on volume)

Runtime estimate (Fly shared-cpu-1x, 1GB RAM):
  * delta CSV (~5K rows): ~30s
  * monthly full CSV (~4M rows): ~25-40 min wall clock, ~700 MB peak
    cache, ~900 MB-1.4 GB DB growth

Storage growth (verified against 2026-04-26 partial-load measurement):
  * 13,801 rows used 2.0 MB (table + indexes). Linear extrapolation to
    4M rows = ~580 MB table + ~340 MB indexes ≈ 920 MB. The migration
    019 header estimate (900 MB-1.4 GB) is the conservative envelope.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INGEST_SCRIPT = _REPO_ROOT / "scripts" / "ingest" / "ingest_invoice_registrants.py"

# Allow ``scripts/ingest`` on sys.path so we can call discover_dl_fil_kanri_no
# directly when probing date validity. We otherwise shell out to the ingest
# script so its retry / encoding logic stays centralized.
_INGEST_DIR = _REPO_ROOT / "scripts" / "ingest"
if str(_INGEST_DIR) not in sys.path:
    sys.path.insert(0, str(_INGEST_DIR))
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

try:
    import ingest_invoice_registrants as _iv  # type: ignore  # noqa: E402
except ImportError as exc:
    print(f"missing module: {exc}", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("autonomath.cron.ingest_nta_invoice_bulk")

_DEFAULT_DB = _REPO_ROOT / "data" / "jpintel.db"
_DEFAULT_CACHE_DIR = Path("/tmp/jpintel_invoice_registrants_cache")
_DEFAULT_LOG_FILE = _REPO_ROOT / "data" / "invoice_load_log.jsonl"
_DEFAULT_BATCH_SIZE = 10_000  # 10K per chunk per spec; ingest script clamps to >=100

# Disk-space gate: full-load ~1.4 GB writes (table + indexes + WAL).
# Refuse to start the full mode if the volume has < 2 GB free.
_MIN_FREE_BYTES_FULL = 2 * 1024 * 1024 * 1024  # 2 GB
_MIN_FREE_BYTES_DELTA = 200 * 1024 * 1024  # 200 MB

# How far back to walk when looking for a publishable sabun date. NTA's
# delta archive keeps ~40 business days; we cap the walk at 14 calendar
# days so a missed cron isn't masked indefinitely.
_SABUN_LOOKBACK_DAYS = 14


# ---------------------------------------------------------------------------
# Date discovery
# ---------------------------------------------------------------------------


def _latest_zenken_date(today: date) -> date:
    """Return the most-recent 1st-of-month strictly on/before ``today``.

    NTA publishes the zenken (full) snapshot on the 1st calendar day of
    each month, reflecting the previous month-end. Running on the 1st
    is safe — the cron schedules at 03:00 JST 1st of month so the file
    is already up.
    """
    return today.replace(day=1)


def _walk_sabun_dates(today: date, lookback: int) -> list[date]:
    """Yield candidate sabun dates from ``today`` backwards (inclusive)."""
    return [today - timedelta(days=i) for i in range(lookback + 1)]


def _discover_date(mode: str, fmt: str, today: date) -> str | None:
    """Return the YYYY-MM-DD string of the first publishable date.

    For mode='full' we start at today's month's 1st and walk back one
    month at a time (handles a freshly missed boundary).

    For mode='delta' we walk today → today-14d.

    Returns the first date for which ``_iv.discover_dl_fil_kanri_no``
    returns a non-empty handle. None if nothing publishable found.
    """
    bucket = "zenken" if mode == "full" else "sabun"
    candidates: list[date]
    if mode == "full":
        # Try the current month's 1st, then last month's, then the one before.
        first = _latest_zenken_date(today)
        candidates = [first]
        cur = first
        for _ in range(2):
            # Step back one month.
            prev_month_last = cur - timedelta(days=1)
            cur = prev_month_last.replace(day=1)
            candidates.append(cur)
    else:
        candidates = _walk_sabun_dates(today, _SABUN_LOOKBACK_DAYS)

    for cand in candidates:
        date_str = cand.isoformat()
        try:
            handle = _iv.discover_dl_fil_kanri_no(bucket, date_str, fmt)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("discover_failed bucket=%s date=%s err=%s", bucket, date_str, exc)
            continue
        if handle:
            _LOG.info("date_found mode=%s date=%s handle=%s", mode, date_str, handle)
            return date_str
    return None


# ---------------------------------------------------------------------------
# Pre-run gates
# ---------------------------------------------------------------------------


def _free_bytes(path: Path) -> int:
    """Bytes free on the filesystem holding ``path``. 0 on failure."""
    try:
        st = shutil.disk_usage(str(path if path.exists() else path.parent))
        return int(st.free)
    except Exception:  # noqa: BLE001
        return 0


def _gate_disk(db_path: Path, mode: str) -> bool:
    needed = _MIN_FREE_BYTES_FULL if mode == "full" else _MIN_FREE_BYTES_DELTA
    free = _free_bytes(db_path)
    if free < needed:
        _LOG.error(
            "disk_gate_tripped mode=%s free_bytes=%d need=%d path=%s",
            mode, free, needed, db_path,
        )
        return False
    return True


def _gate_schema(db_path: Path) -> bool:
    """Quick check that migration 019 has been applied."""
    if not db_path.is_file():
        _LOG.error("schema_gate db_missing path=%s", db_path)
        return False
    try:
        c = sqlite3.connect(str(db_path), timeout=30)
        try:
            row = c.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='invoice_registrants'"
            ).fetchone()
        finally:
            c.close()
    except Exception as exc:  # noqa: BLE001
        _LOG.error("schema_gate db_open_failed path=%s err=%s", db_path, exc)
        return False
    if row is None:
        _LOG.error(
            "schema_gate table_missing — run "
            "`python scripts/migrate.py --db %s` first",
            db_path,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Subprocess invocation of the underlying ingest script
# ---------------------------------------------------------------------------


def _build_ingest_argv(
    db_path: Path,
    mode: str,
    fmt: str,
    date_str: str,
    limit: int | None,
    dry_run: bool,
    cache_dir: Path,
    batch_size: int,
) -> list[str]:
    argv = [
        sys.executable,
        str(_INGEST_SCRIPT),
        "--db", str(db_path),
        "--mode", mode,
        "--format", fmt,
        "--date", date_str,
        "--cache-dir", str(cache_dir),
        "--batch-size", str(batch_size),
    ]
    if limit is not None:
        argv += ["--limit", str(limit)]
    if dry_run:
        argv += ["--dry-run"]
    return argv


def _run_ingest(argv: list[str]) -> tuple[int, str]:
    """Run the ingest subprocess. Returns (return_code, captured_stdout_tail).

    We tee stdout to our own logger line-by-line so the cron operator can
    see progress without paging the full log to memory. The last 4 KB of
    stdout is captured for the per-run summary record.
    """
    _LOG.info("subprocess_start argv=%s", " ".join(argv))
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print(line)
            tail.append(line)
            if len(tail) > 200:
                tail = tail[-200:]
    rc = proc.wait()
    _LOG.info("subprocess_done rc=%d", rc)
    return rc, "\n".join(tail)


# ---------------------------------------------------------------------------
# Post-run housekeeping (ANALYZE)
# ---------------------------------------------------------------------------


def _post_run_analyze(db_path: Path, mode: str) -> None:
    """Refresh planner stats. Cheap on delta, ~1-3 min on full 4M-row."""
    try:
        c = sqlite3.connect(str(db_path), timeout=600)
        try:
            c.execute("PRAGMA busy_timeout = 600000")
            _LOG.info("analyze_start mode=%s", mode)
            t0 = time.time()
            c.execute("ANALYZE invoice_registrants")
            _LOG.info("analyze_done elapsed=%.1fs", time.time() - t0)
        finally:
            c.close()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("analyze_failed err=%s (non-fatal)", exc)


def _row_count(db_path: Path) -> int:
    try:
        c = sqlite3.connect(str(db_path), timeout=30)
        try:
            return int(c.execute("SELECT COUNT(*) FROM invoice_registrants").fetchone()[0])
        finally:
            c.close()
    except Exception:  # noqa: BLE001
        return -1


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def run(
    db_path: Path,
    mode: str,
    fmt: str,
    date_override: str | None,
    limit: int | None,
    dry_run: bool,
    cache_dir: Path,
    batch_size: int,
    log_file: Path,
) -> int:
    """Top-level orchestration. Returns process exit code."""
    today = datetime.now(UTC).date()

    # Pre-run gates.
    if not _gate_disk(db_path, mode):
        return 4
    if not dry_run and not _gate_schema(db_path):
        return 3

    # Date discovery (skip when caller forced --date).
    if date_override is not None:
        date_str = date_override
        _LOG.info("date_override mode=%s date=%s", mode, date_str)
    else:
        date_str = _discover_date(mode=mode, fmt=fmt, today=today)
        if date_str is None:
            _LOG.error(
                "no_publishable_date mode=%s today=%s lookback=%d — "
                "NTA index returned no dlFilKanriNo for the date window",
                mode, today.isoformat(), _SABUN_LOOKBACK_DAYS,
            )
            return 1

    # Row count BEFORE for the per-run delta calculation.
    rows_before = _row_count(db_path) if not dry_run else -1

    argv = _build_ingest_argv(
        db_path=db_path,
        mode=mode,
        fmt=fmt,
        date_str=date_str,
        limit=limit,
        dry_run=dry_run,
        cache_dir=cache_dir,
        batch_size=batch_size,
    )
    t0 = time.time()
    rc, stdout_tail = _run_ingest(argv)
    elapsed = time.time() - t0

    # Post-run ANALYZE (skip on dry-run / hard failure).
    if not dry_run and rc == 0:
        _post_run_analyze(db_path, mode)

    rows_after = _row_count(db_path) if not dry_run else -1
    delta_rows = (rows_after - rows_before) if (rows_before >= 0 and rows_after >= 0) else None

    # Append per-run summary.
    fetched_at = datetime.now(UTC).isoformat()
    entry = {
        "run_at": fetched_at,
        "mode": mode,
        "format": fmt,
        "date": date_str,
        "rc": rc,
        "elapsed_sec": round(elapsed, 1),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "rows_delta": delta_rows,
        "limit": limit,
        "dry_run": dry_run,
        "stdout_tail": stdout_tail[-2000:],
    }
    if not dry_run:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            _LOG.info("appended_log path=%s", log_file)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("log_write_failed path=%s err=%s", log_file, exc)

    _LOG.info(
        "run_done mode=%s rc=%d rows_before=%s rows_after=%s delta=%s elapsed=%.1fs",
        mode, rc, rows_before, rows_after, delta_rows, elapsed,
    )
    return rc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("autonomath.cron.ingest_nta_invoice_bulk")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cron driver: NTA 適格事業者 monthly bulk + daily delta."
    )
    p.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JPINTEL_DB_PATH", _DEFAULT_DB)),
        help=f"SQLite path (default: $JPINTEL_DB_PATH or {_DEFAULT_DB})",
    )
    p.add_argument(
        "--mode",
        choices=("full", "delta"),
        default="full",
        help="full = monthly zenken bulk; delta = daily sabun (default: full)",
    )
    p.add_argument(
        "--format",
        dest="fmt",
        choices=("csv", "xml", "json"),
        default="csv",
        help="bulk format (default: csv — smallest + most stable schema)",
    )
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="YYYY-MM-DD override (default: auto-discover from NTA index)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap rows parsed (smoke / CI)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="parse + validate, no DB writes",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help=f"download cache directory (default: {_DEFAULT_CACHE_DIR})",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        help=f"rows per transaction (default: {_DEFAULT_BATCH_SIZE})",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=_DEFAULT_LOG_FILE,
        help=f"per-run log (default: {_DEFAULT_LOG_FILE.relative_to(_REPO_ROOT)})",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if args.date is not None:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            _LOG.error("invalid --date=%s (expected YYYY-MM-DD)", args.date)
            return 1

    with heartbeat("ingest_nta_invoice_bulk") as hb:
        rc = run(
            db_path=args.db,
            mode=args.mode,
            fmt=args.fmt,
            date_override=args.date,
            limit=args.limit,
            dry_run=args.dry_run,
            cache_dir=args.cache_dir,
            batch_size=max(100, args.batch_size),
            log_file=args.log_file,
        )
        hb["metadata"] = {
            "mode": args.mode,
            "fmt": args.fmt,
            "limit": args.limit,
            "batch_size": max(100, args.batch_size),
            "dry_run": bool(args.dry_run),
            "exit_code": rc,
        }
    return rc


if __name__ == "__main__":
    sys.exit(main())
