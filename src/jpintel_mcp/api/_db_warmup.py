"""Boot-time SQLite cold-start warmup.

R8_PERF_BASELINE bottleneck #3: the first ``GET /v1/am/health/deep`` after
a fresh Fly machine boot times out at 30.92s — Fly proxy ceiling — because
``autonomath.db`` (~9.4 GB on disk) has zero pages in the OS page cache.
The same hit a second time returns in <400ms once the pages are cached.
For an AI agent making the day's first call this is launch-UX-fatal.

We can't pre-page the entire 9.4 GB blob (Fly grace is 60s and we'd burn
the whole budget on disk I/O). We CAN issue cheap ``SELECT COUNT(*)`` and
``SELECT ... LIMIT 1`` probes against the hottest tables. Those touch the
b-tree root pages plus the first leaf pages, which is exactly what the
deep-health probes hit on their first run. After warmup the second hit
budget shrinks from ~30s to <1s, well inside Fly's 30s proxy ceiling.

Design constraints:

* **Background fire-and-forget.** Boot grace is 60s; we MUST NOT block
  ``/readyz`` on warmup. The worker is launched as an ``asyncio.create_task``
  inside the lifespan startup hook and runs concurrently with the first
  inbound requests. If the first hit lands before warmup finishes we get
  the legacy slow path; we just don't make it worse.
* **Error tolerant.** If ``autonomath.db`` is missing (dev / CI / a
  partial bootstrap) the warmup logs and exits cleanly. SQLite ``OPEN
  ERROR`` / ``MISSING TABLE`` / ``LOCKED`` are all swallowed — the
  guarantee is "warmup never crashes the app".
* **No LLM, no external calls, no schema mutations.** Read-only URI mode.
* **Configurable.** ``AUTONOMATH_WARMUP_ENABLED=0`` disables the worker
  for local dev where the 9.4 GB DB doesn't exist anyway. Default ON.

Touched tables (chosen for highest first-hit signal):
    am_entities, am_entity_facts, am_relation, am_alias, programs,
    jpi_programs, am_amendment_snapshot, am_amendment_diff.

Each probe is bounded by a 5s sqlite ``timeout`` and the entire warmup
loop is wrapped in a 30s outer guard so a single hung probe can't keep
the worker alive past the boot window.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import time
from typing import TYPE_CHECKING

from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---- module constants -------------------------------------------------------

# Tables we touch on warmup. Order matters: hottest tables first so a
# truncated warmup (e.g. boot interrupted by SIGTERM) still pays the
# biggest first-hit reduction.
_AUTONOMATH_PROBES: tuple[str, ...] = (
    "am_entities",
    "am_entity_facts",
    "am_relation",
    "am_alias",
    "jpi_programs",
    "am_amendment_snapshot",
    "am_amendment_diff",
)

_JPINTEL_PROBES: tuple[str, ...] = (
    "programs",
    "case_studies",
    "loan_programs",
    "enforcement_cases",
)

# Outer time budget. If warmup hasn't finished by 30s we abandon it.
# Fly grace is 60s so even a fully-budgeted warmup leaves headroom.
_WARMUP_OUTER_TIMEOUT_S: float = 30.0

# Per-connection sqlite timeout. Anything above this is almost certainly
# a hang, not page-fault latency.
_PROBE_TIMEOUT_S: float = 5.0


# ---- helpers ----------------------------------------------------------------


def _is_enabled() -> bool:
    """Honor `AUTONOMATH_WARMUP_ENABLED` env var (default ON).

    Set to ``0`` / ``false`` / ``no`` to disable. Useful for local dev
    where the 9.4 GB autonomath.db doesn't exist and the probes would
    just log ``OPEN ERROR`` for every table.
    """
    raw = os.environ.get("AUTONOMATH_WARMUP_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _open_ro(path: Path) -> sqlite3.Connection | None:
    """Open `path` read-only. Return None on any open error (no raise)."""
    try:
        if not path.exists():
            return None
        uri = f"file:{path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=_PROBE_TIMEOUT_S)
    except sqlite3.Error as exc:
        logger.info(
            "db_warmup_open_failed",
            extra={"path": str(path), "error": type(exc).__name__},
        )
        return None


def _probe_table(con: sqlite3.Connection, table: str) -> tuple[bool, float]:
    """Run a `SELECT COUNT(*)` + `LIMIT 1` against `table`.

    Returns (ok, elapsed_seconds). Never raises. A missing table returns
    (False, elapsed) and is logged at INFO — that's a configuration
    signal, not a crash.
    """
    t0 = time.perf_counter()
    try:
        # COUNT(*) touches every page of the row-count cache, but on
        # FTS5 / large tables the optimizer short-circuits to the
        # internal stats. LIMIT 1 forces one b-tree leaf walk, which is
        # what /v1/am/health/deep actually pays on first hit.
        con.execute(f"SELECT COUNT(*) FROM {table} LIMIT 1").fetchone()  # noqa: S608
        con.execute(f"SELECT * FROM {table} LIMIT 1").fetchall()  # noqa: S608
        return True, time.perf_counter() - t0
    except sqlite3.Error:
        return False, time.perf_counter() - t0  # caller logs


def _run_probes_sync(db_path: Path, tables: tuple[str, ...], db_label: str) -> dict[str, float]:
    """Synchronous probe loop for one DB. Called inside `run_in_executor`.

    Returns ``{table_name: elapsed_seconds}`` for tables that
    successfully probed. Missing / errored tables are logged but omitted
    from the return dict so callers can sum the warmed-budget cleanly.
    """
    results: dict[str, float] = {}
    con = _open_ro(db_path)
    if con is None:
        logger.info(
            "db_warmup_skipped",
            extra={"db": db_label, "path": str(db_path), "reason": "open_failed"},
        )
        return results
    try:
        for table in tables:
            ok, elapsed = _probe_table(con, table)
            if ok:
                results[table] = elapsed
            else:
                logger.info(
                    "db_warmup_table_missing",
                    extra={"db": db_label, "table": table},
                )
    finally:
        with contextlib.suppress(sqlite3.Error):
            con.close()
    return results


# ---- public surface ---------------------------------------------------------


async def warmup_databases() -> dict[str, dict[str, float]]:
    """Run cold-start warmup against jpintel.db + autonomath.db.

    Coroutine — schedule with ``asyncio.create_task`` from lifespan
    startup. Bounded by ``_WARMUP_OUTER_TIMEOUT_S``; on timeout we log
    and return whatever finished. Never raises.
    """
    if not _is_enabled():
        logger.info("db_warmup_disabled", extra={"env": "AUTONOMATH_WARMUP_ENABLED=0"})
        return {}

    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()

    async def _both() -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        # Run the two DBs concurrently; each probe block is ~ms-to-seconds
        # and they don't contend (separate files, separate page caches).
        jpintel_fut = loop.run_in_executor(
            None, _run_probes_sync, settings.db_path, _JPINTEL_PROBES, "jpintel"
        )
        autonomath_fut = loop.run_in_executor(
            None,
            _run_probes_sync,
            settings.autonomath_db_path,
            _AUTONOMATH_PROBES,
            "autonomath",
        )
        jpintel_res, autonomath_res = await asyncio.gather(
            jpintel_fut, autonomath_fut, return_exceptions=False
        )
        if jpintel_res:
            out["jpintel"] = jpintel_res
        if autonomath_res:
            out["autonomath"] = autonomath_res
        return out

    try:
        results = await asyncio.wait_for(_both(), timeout=_WARMUP_OUTER_TIMEOUT_S)
    except TimeoutError:
        logger.warning(
            "db_warmup_timeout",
            extra={"budget_s": _WARMUP_OUTER_TIMEOUT_S},
        )
        return {}
    except Exception:  # noqa: BLE001  # pragma: no cover — defensive
        # We promise warmup never crashes the app. Log and bail.
        logger.exception("db_warmup_unhandled_error")
        return {}

    elapsed = time.perf_counter() - t0
    total_tables = sum(len(v) for v in results.values())
    logger.info(
        "db_warmup_complete",
        extra={
            "elapsed_s": round(elapsed, 3),
            "tables_warmed": total_tables,
            "dbs": list(results.keys()),
        },
    )
    return results


def schedule_warmup() -> asyncio.Task[dict[str, dict[str, float]]]:
    """Fire-and-forget scheduler. Call from inside the running event loop.

    Returns the spawned task so callers can hold a reference (avoiding
    the "task was destroyed but it is pending" warning) without waiting
    on it. The lifespan startup hook does NOT await this — that's the
    whole point: boot returns immediately, /readyz flips green, and the
    page cache fills concurrently with the first inbound requests.
    """
    return asyncio.create_task(warmup_databases(), name="db_warmup")


__all__ = [
    "schedule_warmup",
    "warmup_databases",
]
