#!/usr/bin/env python3
"""scripts/analyze_telemetry.py

Interactive DuckDB REPL for AutonoMath query telemetry.
Downloads telemetry archives from Cloudflare R2 to a local cache,
loads them into DuckDB, and opens an interactive SQL prompt with
pre-registered helper views.

Usage:
  python scripts/analyze_telemetry.py --date-range 2026-05-01:2026-05-07
  python scripts/analyze_telemetry.py --since 7d
  python scripts/analyze_telemetry.py --since 30d

Required env vars:
  CLOUDFLARE_API_TOKEN   — R2 read access (same token as archive script)
  CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID
  R2_BUCKET              — defaults to "autonomath-telemetry"

Optional:
  TELEMETRY_CACHE_DIR    — local cache dir, defaults to ~/.cache/autonomath-telemetry/
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
R2_BUCKET = os.environ.get("R2_BUCKET", "autonomath-telemetry")
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "autonomath-telemetry"
CACHE_DIR = Path(os.environ.get("TELEMETRY_CACHE_DIR", str(DEFAULT_CACHE_DIR)))

SAMPLE_QUERIES = """\
SAMPLE QUERIES:
  SELECT endpoint, COUNT(*) FROM rest_calls GROUP BY endpoint ORDER BY 2 DESC LIMIT 20;
  SELECT tool_name, percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM mcp_calls GROUP BY tool_name;
  SELECT endpoint, COUNT(*) FROM zero_results GROUP BY endpoint ORDER BY 2 DESC LIMIT 10;
  SELECT status, error_class, COUNT(*) FROM errors GROUP BY status, error_class ORDER BY 3 DESC;
  SELECT DATE_TRUNC('hour', ts::TIMESTAMP) AS hr, COUNT(*) FROM telemetry GROUP BY hr ORDER BY hr;

REGISTERED VIEWS:
  telemetry    — all events
  rest_calls   — channel='rest'
  mcp_calls    — channel='mcp'  (endpoint aliased as tool_name)
  zero_results — result_count=0
  errors       — status not between 200 and 299

Schema fields: ts, channel, endpoint, params_shape, result_count, latency_ms, status, error_class
"""

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive DuckDB REPL for AutonoMath query telemetry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SAMPLE_QUERIES,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--date-range",
        metavar="START:END",
        help="Inclusive date range, e.g. 2026-05-01:2026-05-07",
    )
    group.add_argument(
        "--since",
        metavar="Nd",
        help="Relative range, e.g. 7d or 30d (days back from today)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Skip R2 download; use only files already in cache",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR,
        help=f"Local cache directory (default: {CACHE_DIR})",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------


def _date_range_from_args(args: argparse.Namespace) -> list[datetime.date]:
    """Return list of dates to load."""
    today = datetime.date.today()
    if args.since:
        m = re.fullmatch(r"(\d+)d", args.since.strip())
        if not m:
            print(f"[error] --since must be like '7d' or '30d', got: {args.since!r}")
            sys.exit(1)
        days = int(m.group(1))
        return [today - datetime.timedelta(days=i) for i in range(1, days + 1)]
    # --date-range START:END
    parts = args.date_range.split(":")
    if len(parts) != 2:
        print(f"[error] --date-range must be START:END, got: {args.date_range!r}")
        sys.exit(1)
    try:
        start = datetime.date.fromisoformat(parts[0].strip())
        end = datetime.date.fromisoformat(parts[1].strip())
    except ValueError as exc:
        print(f"[error] invalid date in --date-range: {exc}")
        sys.exit(1)
    if start > end:
        print("[error] --date-range: START must be <= END")
        sys.exit(1)
    delta = (end - start).days + 1
    return [start + datetime.timedelta(days=i) for i in range(delta)]


# ---------------------------------------------------------------------------
# R2 download
# ---------------------------------------------------------------------------


def _download_date(date: datetime.date, cache_dir: Path) -> Path | None:
    """Download a single day's archive from R2. Returns local path or None."""
    key = f"{date.isoformat()}.json.gz"
    dest = cache_dir / key
    if dest.exists():
        print(f"  [cache hit] {key}")
        return dest
    if not shutil.which("wrangler"):
        print(f"  [warn] wrangler not in PATH; cannot download {key}", file=sys.stderr)
        return None
    print(f"  [download] {key} … ", end="", flush=True)
    result = subprocess.run(
        ["wrangler", "r2", "object", "get", f"{R2_BUCKET}/{key}", "--file", str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and dest.exists():
        size_kb = dest.stat().st_size // 1024
        print(f"ok ({size_kb} KB)")
        return dest
    else:
        print(f"not found ({result.stderr.strip()[:80]})")
        return None


def ensure_cached(dates: list[datetime.date], cache_dir: Path, skip_download: bool) -> list[Path]:
    """Download missing archives; return list of local paths that exist."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for date in sorted(dates):
        if skip_download:
            local = cache_dir / f"{date.isoformat()}.json.gz"
            if local.exists():
                paths.append(local)
        else:
            p = _download_date(date, cache_dir)
            if p:
                paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# DuckDB setup
# ---------------------------------------------------------------------------


def _build_db(paths: list[Path]) -> duckdb.DuckDBPyConnection:
    """Load archives into an in-memory DuckDB and register helper views."""
    con = duckdb.connect(database=":memory:")

    if not paths:
        # Register empty views so the REPL still starts cleanly
        _create_empty_views(con)
        return con

    str_paths = [str(p) for p in paths]
    glob_pattern = "{" + ",".join(str_paths) + "}"

    con.execute(f"""
        CREATE OR REPLACE VIEW telemetry AS
        SELECT *
        FROM read_json_auto('{glob_pattern}',
            format='newline_delimited',
            compression='gzip',
            ignore_errors=true)
    """)

    # Helper views
    con.execute("""
        CREATE OR REPLACE VIEW rest_calls AS
        SELECT * FROM telemetry WHERE channel = 'rest'
    """)
    con.execute("""
        CREATE OR REPLACE VIEW mcp_calls AS
        SELECT *, endpoint AS tool_name FROM telemetry WHERE channel = 'mcp'
    """)
    con.execute("""
        CREATE OR REPLACE VIEW zero_results AS
        SELECT * FROM telemetry WHERE result_count = 0
    """)
    con.execute("""
        CREATE OR REPLACE VIEW errors AS
        SELECT * FROM telemetry WHERE status < 200 OR status > 299
    """)
    return con


def _create_empty_views(con: duckdb.DuckDBPyConnection) -> None:
    """Register schema-correct empty views so DESCRIBE works even with no data."""
    ddl = """
        CREATE OR REPLACE VIEW telemetry AS
        SELECT
            NULL::VARCHAR AS ts,
            NULL::VARCHAR AS channel,
            NULL::VARCHAR AS endpoint,
            NULL::VARCHAR AS params_shape,
            NULL::BIGINT  AS result_count,
            NULL::DOUBLE  AS latency_ms,
            NULL::INTEGER AS status,
            NULL::VARCHAR AS error_class
        WHERE false
    """
    con.execute(ddl)
    for view, where in [
        ("rest_calls", "channel = 'rest'"),
        ("mcp_calls", "channel = 'mcp'"),
        ("zero_results", "result_count = 0"),
        ("errors", "status < 200 OR status > 299"),
    ]:
        con.execute(
            f"CREATE OR REPLACE VIEW {view} AS SELECT *, endpoint AS tool_name FROM telemetry WHERE {where}"
        )


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def _repl(con: duckdb.DuckDBPyConnection, row_count: int, date_span: str) -> None:
    """Simple interactive SQL REPL backed by DuckDB."""
    print("\n" + "=" * 60)
    print("AutonoMath Telemetry — DuckDB REPL")
    print(f"  Period:  {date_span}")
    print(f"  Events:  {row_count:,}")
    print(f"  Cache:   {CACHE_DIR}")
    print("=" * 60)
    print()
    print(SAMPLE_QUERIES)
    print("Type SQL queries, or 'quit' / Ctrl-D to exit.\n")

    while True:
        try:
            query = input("duckdb> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in {"quit", "exit", r"\q"}:
            break
        try:
            rel = con.execute(query)
            if rel is not None:
                result = rel.fetchall()
                if result:
                    cols = [d[0] for d in rel.description]  # type: ignore[union-attr]
                    # Simple tabular output
                    widths = [len(c) for c in cols]
                    str_rows = [
                        [str(v) if v is not None else "NULL" for v in row] for row in result
                    ]
                    for row in str_rows:
                        for i, cell in enumerate(row):
                            widths[i] = max(widths[i], len(cell))
                    header = "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
                    sep = "  ".join("-" * w for w in widths)
                    print(header)
                    print(sep)
                    for row in str_rows:
                        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
                    print(f"\n({len(result)} rows)\n")
                else:
                    print("(0 rows)\n")
        except duckdb.Error as exc:
            print(f"Error: {exc}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = _parse_args()
    dates = _date_range_from_args(args)
    cache_dir: Path = args.cache_dir

    start_label = min(dates).isoformat()
    end_label = max(dates).isoformat()
    date_span = f"{start_label} to {end_label} ({len(dates)} days)"

    print(f"[info] date range: {date_span}")
    if not args.no_download:
        print(f"[info] downloading from R2 bucket '{R2_BUCKET}' …")
    paths = ensure_cached(dates, cache_dir, args.no_download)

    if not paths:
        print(
            "[warn] no telemetry archives found. "
            "Check R2 credentials or run archive_telemetry.sh first.",
            file=sys.stderr,
        )

    con = _build_db(paths)
    row_count = 0
    if paths:
        with contextlib.suppress(duckdb.Error):
            row_count = con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]  # type: ignore[index]

    _repl(con, int(row_count), date_span)
    con.close()
    print("[info] session ended")


if __name__ == "__main__":
    main()
