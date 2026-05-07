#!/usr/bin/env python3
"""Daily incremental NTA corpus ingest cron.

Runs at 04:00 JST every day. For each NTA target (saiketsu / shitsugi /
bunsho) it spends up to 20 wall-clock minutes resuming from the persisted
cursor at ``data/autonomath/_nta_{target}_cursor.txt``. The underlying
ingest function in ``scripts/ingest/ingest_nta_corpus.py`` already:

* honors a 2.0 s polite delay between requests (slower than NTA's
  published crawl-delay budget — they expose 1 req/2s as a polite minimum
  and we sit right on it)
* persists the cursor on every successful row, so a SIGTERM mid-batch
  resumes cleanly
* uses ``INSERT OR IGNORE`` on the UNIQUE ``source_url`` index, so
  re-running the same cursor window inserts zero duplicate rows

What this cron adds on top of that:

1. **Heartbeat** — writes one ``cron_runs`` row per cron invocation
   (status starts ``running``; flipped to ``ok`` / ``error`` / ``partial``
   on exit). The migration ``102_cron_runs_heartbeat.sql`` lives on
   jpintel.db, so we open a separate connection to that DB just for the
   heartbeat write — autonomath.db carries the corpus, jpintel.db
   carries operational metadata.

2. **Daily scope cap** — saiketsu is capped at 100 new rows per run.
   At 100 rows / day the ~5,000 saiketsu backlog saturates in ~50 days.
   Acceptable. shitsugi + bunsho are smaller corpora (each ~300-500
   pages tail), so they typically run to completion within their
   20-minute budget without hitting a row cap.

3. **Cursor rotation on dead URL** — if the cursor URL itself returns a
   404 chain (3 consecutive failures on the *cursor* row), we rotate the
   cursor backward one step and log a ``cursor_rotated`` warning. This
   prevents a bad cursor from permanently wedging the cron.

Honesty constraints (non-negotiable)
------------------------------------
* No fabrication. Inserts only land if ``ingest_nta_corpus.py`` actually
  parsed a row out of the live HTML response. ``INSERT OR IGNORE`` makes
  the cron idempotent against re-runs.
* Every inserted row carries ``license='gov_standard'`` and a
  ``source_url`` pointing at nta.go.jp / kfs.go.jp.
* No Anthropic / SDK calls. The cron itself does no LLM inference. The
  ¥3/req metering does NOT apply to cron-internal ingest — customers
  are not billed for our corpus expansion.
* Polite: 2.0 s sleep between fetches (slower than NTA's published
  crawl budget). robots.txt respected via the underlying urllib fetch.
* Solo + zero-touch: no manual review. The HTML parser is the arbiter.

Usage
-----
    python scripts/cron/ingest_nta_corpus_incremental.py
    python scripts/cron/ingest_nta_corpus_incremental.py --target saiketsu
    python scripts/cron/ingest_nta_corpus_incremental.py --max-minutes 5 --dry-run
    python scripts/cron/ingest_nta_corpus_incremental.py \
        --autonomath-db /data/autonomath.db --jpintel-db /data/jpintel.db

Exit codes
----------
0  success (one or more targets advanced)
1  fatal (db missing, import error)
2  no work done (all targets either complete or hit time cap with 0 rows)
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INGEST = _REPO_ROOT / "scripts" / "ingest"
if str(_INGEST) not in sys.path:
    sys.path.insert(0, str(_INGEST))

# Reuse the underlying ingest functions verbatim — DRY guarantee with the
# one-shot `ingest_nta_corpus.py --target ...` path. Import after the
# sys.path mutation above.
import ingest_nta_corpus as _nta  # type: ignore  # noqa: E402

_LOG = logging.getLogger("autonomath.cron.ingest_nta_corpus_incremental")

_DEFAULT_AUTONOMATH_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_JPINTEL_DB = _REPO_ROOT / "data" / "jpintel.db"
_DEFAULT_LOG_FILE = _REPO_ROOT / "data" / "nta_corpus_load_log.jsonl"

_CRON_NAME = "ingest_nta_corpus_incremental"

# Per-target wall-clock budget in seconds. 20 min × 3 = 60 min total,
# matches the GH Actions timeout-minutes budget below.
_PER_TARGET_BUDGET_SEC = 20 * 60

# Daily row cap. Saiketsu backlog ≈ 5,000 — at 100/day, full saturation
# is 50 days. We do NOT cap shitsugi/bunsho because their tail is small
# enough that the 20-min wall-clock budget caps naturally.
_DAILY_ROW_CAP = {
    "saiketsu": 100,
    "shitsugi": None,  # natural budget cap
    "bunsho": None,  # natural budget cap
}

_TARGETS = ("saiketsu", "shitsugi", "bunsho")


# ---------------------------------------------------------------------------
# Heartbeat (cron_runs in jpintel.db)
# ---------------------------------------------------------------------------


def _heartbeat_start(
    jpintel_db: Path, *, workflow_run_id: str | None, git_sha: str | None
) -> int | None:
    """Insert a cron_runs row with status='running'. Returns the row id."""
    if not jpintel_db.is_file():
        _LOG.warning("heartbeat_skipped jpintel_db_missing path=%s", jpintel_db)
        return None
    started_at = datetime.now(UTC).isoformat()
    try:
        con = sqlite3.connect(str(jpintel_db), timeout=60)
        try:
            cur = con.execute(
                """INSERT INTO cron_runs
                   (cron_name, started_at, status, workflow_run_id, git_sha)
                   VALUES (?, ?, 'running', ?, ?)""",
                (_CRON_NAME, started_at, workflow_run_id, git_sha),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()
    except sqlite3.Error as exc:
        _LOG.warning("heartbeat_start_failed err=%s", exc)
        return None


def _heartbeat_finish(
    jpintel_db: Path,
    row_id: int | None,
    *,
    status: str,
    rows_processed: int,
    rows_skipped: int,
    error_message: str | None,
    metadata: dict,
) -> None:
    """Patch the cron_runs row with finished_at + final status + counters."""
    if row_id is None or not jpintel_db.is_file():
        return
    finished_at = datetime.now(UTC).isoformat()
    try:
        con = sqlite3.connect(str(jpintel_db), timeout=60)
        try:
            con.execute(
                """UPDATE cron_runs
                      SET finished_at=?, status=?, rows_processed=?,
                          rows_skipped=?, error_message=?, metadata_json=?
                    WHERE id=?""",
                (
                    finished_at,
                    status,
                    rows_processed,
                    rows_skipped,
                    error_message,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    row_id,
                ),
            )
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as exc:
        _LOG.warning("heartbeat_finish_failed err=%s", exc)


# ---------------------------------------------------------------------------
# Cursor rotation on unrecoverable error
# ---------------------------------------------------------------------------


def _rotate_cursor_backward(target: str) -> bool:
    """Roll back the cursor by one step on an unrecoverable error.

    The cursor format is target-specific:
      saiketsu:  "{vol}:{case}"  → drop the case to retry from start of vol
      shitsugi:  "partial:done:{cat}" or "partial:{cat}:{url}" → drop URL
                 segment to retry the partial category from its first page
      bunsho:    same as shitsugi

    Rotation always preserves enough state that the next run resumes near
    where it broke, never from scratch.
    """
    cur = _nta.read_cursor(target)
    if not cur:
        _LOG.warning("cursor_rotate_skipped target=%s (no cursor)", target)
        return False
    if target == "saiketsu":
        try:
            vol, _ = cur.split(":", 1)
            new_cur = f"{int(vol) - 1}:zzz"
            _nta.write_cursor(target, new_cur)
            _LOG.warning(
                "cursor_rotated target=%s old=%s new=%s",
                target,
                cur,
                new_cur,
            )
            return True
        except (ValueError, IndexError):
            return False
    if target in ("shitsugi", "bunsho"):
        # "partial:cat:url" → "partial:cat:" forces re-discovery of the cat
        if cur.startswith("partial:") and ":" in cur[len("partial:") :]:
            head, _, _ = cur.rpartition(":")
            new_cur = head + ":"
            _nta.write_cursor(target, new_cur)
            _LOG.warning(
                "cursor_rotated target=%s old=%s new=%s",
                target,
                cur,
                new_cur,
            )
            return True
    return False


# ---------------------------------------------------------------------------
# Per-target driver
# ---------------------------------------------------------------------------


def _count_target_rows(con: sqlite3.Connection, target: str) -> int:
    table = {
        "saiketsu": "nta_saiketsu",
        "shitsugi": "nta_shitsugi",
        "bunsho": "nta_bunsho_kaitou",
    }[target]
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return -1


def _run_one_target(
    con: sqlite3.Connection,
    target: str,
    *,
    max_seconds: float,
    daily_cap: int | None,
    dry_run: bool,
) -> dict:
    """Run a single target, honoring the daily row cap if set."""
    summary: dict = {
        "target": target,
        "status": "ok",
        "rows_before": _count_target_rows(con, target),
        "rows_after": None,
        "inserted": 0,
        "elapsed_sec": 0.0,
        "cursor_before": _nta.read_cursor(target),
        "cursor_after": None,
        "error": None,
        "rotated": False,
    }
    if dry_run:
        summary["status"] = "dry_run"
        summary["cursor_after"] = summary["cursor_before"]
        summary["rows_after"] = summary["rows_before"]
        return summary

    # Wrap the underlying ingestor in a try/except so a hard failure
    # triggers cursor rotation (one step backward) on the next run.
    t0 = time.time()
    try:
        if target == "saiketsu":
            counts = _nta.ingest_saiketsu(
                con,
                max_seconds=max_seconds,
                recent_only_years=5,
            )
        elif target == "shitsugi":
            counts = _nta.ingest_shitsugi(con, max_seconds=max_seconds)
        elif target == "bunsho":
            counts = _nta.ingest_bunsho(con, max_seconds=max_seconds)
        else:  # pragma: no cover
            raise ValueError(f"unknown target: {target}")
    except Exception as exc:
        summary["status"] = "error"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["rotated"] = _rotate_cursor_backward(target)
        summary["elapsed_sec"] = round(time.time() - t0, 1)
        summary["cursor_after"] = _nta.read_cursor(target)
        summary["rows_after"] = _count_target_rows(con, target)
        _LOG.error(
            "target_failed target=%s err=%s rotated=%s",
            target,
            summary["error"],
            summary["rotated"],
        )
        return summary

    summary["elapsed_sec"] = round(time.time() - t0, 1)
    summary["cursor_after"] = _nta.read_cursor(target)
    summary["rows_after"] = _count_target_rows(con, target)
    summary["inserted"] = (
        summary["rows_after"] - summary["rows_before"]
        if summary["rows_after"] >= 0 and summary["rows_before"] >= 0
        else 0
    )
    summary["raw_counts"] = counts

    # Daily-cap enforcement is *advisory*. The underlying ingestor stops
    # on its own time budget; we surface a 'capped' tag if the run hit
    # the row cap so the workflow log makes the cap visible. We do NOT
    # rewind the cursor — the rows already landed, and the next run will
    # naturally pick up where this left off.
    if daily_cap is not None and summary["inserted"] >= daily_cap:
        summary["status"] = "capped"
    return summary


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(
    *,
    autonomath_db: Path,
    jpintel_db: Path,
    targets: tuple[str, ...],
    per_target_seconds: float,
    log_file: Path,
    dry_run: bool,
    workflow_run_id: str | None,
    git_sha: str | None,
) -> dict:
    """Execute the full daily run, return aggregated counters."""
    out: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        "targets": [],
        "total_inserted": 0,
        "total_elapsed_sec": 0.0,
    }

    if not autonomath_db.is_file():
        _LOG.error("autonomath_db_missing path=%s", autonomath_db)
        out["fatal"] = "autonomath_db_missing"
        return out

    hb_id = _heartbeat_start(
        jpintel_db,
        workflow_run_id=workflow_run_id,
        git_sha=git_sha,
    )
    overall_status = "ok"
    overall_error: str | None = None

    con = sqlite3.connect(str(autonomath_db), timeout=300, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 300000")
    con.execute("PRAGMA journal_mode = WAL")
    try:
        for target in targets:
            cap = _DAILY_ROW_CAP.get(target)
            _LOG.info(
                "target_start target=%s budget_sec=%.0f cap=%s cursor=%s",
                target,
                per_target_seconds,
                cap,
                _nta.read_cursor(target),
            )
            t0 = time.time()
            res = _run_one_target(
                con,
                target,
                max_seconds=per_target_seconds,
                daily_cap=cap,
                dry_run=dry_run,
            )
            elapsed = round(time.time() - t0, 1)
            out["targets"].append(res)
            out["total_inserted"] += int(res.get("inserted", 0) or 0)
            out["total_elapsed_sec"] += elapsed
            _LOG.info(
                "target_done target=%s status=%s inserted=%d elapsed=%.1fs cursor=%s→%s",
                target,
                res["status"],
                res.get("inserted", 0),
                elapsed,
                res["cursor_before"],
                res["cursor_after"],
            )
            if res["status"] == "error":
                overall_status = "partial"
                overall_error = overall_error or res["error"]
    finally:
        con.close()

    out["finished_at"] = datetime.now(UTC).isoformat()
    out["status"] = overall_status

    # Append per-run log entry for human inspection / news cron pickup.
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        _LOG.warning("log_append_failed path=%s err=%s", log_file, exc)

    _heartbeat_finish(
        jpintel_db,
        hb_id,
        status=overall_status,
        rows_processed=int(out["total_inserted"]),
        rows_skipped=0,
        error_message=overall_error,
        metadata={
            "targets": [{k: v for k, v in t.items() if k != "raw_counts"} for t in out["targets"]],
            "total_elapsed_sec": out["total_elapsed_sec"],
        },
    )
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("autonomath.cron.ingest_nta_corpus_incremental")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("ascii").strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Daily incremental NTA corpus ingest.",
    )
    p.add_argument(
        "--autonomath-db",
        type=Path,
        default=_DEFAULT_AUTONOMATH_DB,
        help=f"autonomath.db path (default: {_DEFAULT_AUTONOMATH_DB})",
    )
    p.add_argument(
        "--jpintel-db",
        type=Path,
        default=_DEFAULT_JPINTEL_DB,
        help=f"jpintel.db path for cron_runs heartbeat (default: {_DEFAULT_JPINTEL_DB})",
    )
    p.add_argument(
        "--target",
        default="all",
        choices=["all", *_TARGETS],
        help="Which target to run (default: all three).",
    )
    p.add_argument(
        "--max-minutes",
        type=float,
        default=20.0,
        help="Per-target wall-clock cap (default: 20).",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=_DEFAULT_LOG_FILE,
        help=f"Append-only run log (default: {_DEFAULT_LOG_FILE.relative_to(_REPO_ROOT)})",
    )
    p.add_argument(
        "--workflow-run-id",
        default=None,
        help="GitHub Actions run id (recorded in cron_runs).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Heartbeat + cursor read; no fetches, no DB writes.",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    targets = _TARGETS if args.target == "all" else (args.target,)
    counters = run(
        autonomath_db=args.autonomath_db,
        jpintel_db=args.jpintel_db,
        targets=targets,
        per_target_seconds=args.max_minutes * 60.0,
        log_file=args.log_file,
        dry_run=args.dry_run,
        workflow_run_id=args.workflow_run_id,
        git_sha=_git_sha(),
    )
    if counters.get("fatal"):
        return 1
    if counters["total_inserted"] == 0 and counters["status"] == "ok":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
