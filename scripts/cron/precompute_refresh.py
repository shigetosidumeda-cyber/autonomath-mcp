#!/usr/bin/env python3
"""Nightly pre-compute table refresh (v8 P5-ε++ / dd_v8_C3 + dd_v8_D8).

What it does:
  Refreshes the 32 pc_* tables added across migrations 044 (14 tables) and
  045 (18 tables) using a DELETE-then-INSERT pattern inside a single
  transaction per table. Source rows are read from jpintel.db (programs /
  loan_programs / enforcement_cases / laws / ...) and autonomath.db (am_*
  entity-fact schema, opened read-only via a separate connection — no
  ATTACH).

Why DELETE-then-INSERT (not UPSERT or trigger):
  * pc_* tables are pure materialized views over (potentially) two
    databases. The cleanest way to keep them consistent with the
    sources is "wipe + rebuild" inside a single tx, so a partial
    refresh never leaves stale rows visible to readers.
  * Refresh is nightly. The 5-10s downtime per table during the wipe is
    invisible to customers (queries fall through to L0/L1 on miss).
  * Total 32 tables = 14 (mig 044) + 18 (mig 045). Hits the v8 plan
    T+30d target of 33 (33 = 19 launch baseline + 14, then this 18
    expansion drives toward T+90d 47).

What populates each table:
  Implemented refreshers are listed in IMPLEMENTED_PC_TABLES and are rebuilt
  with DELETE-then-INSERT. Placeholder refreshers are visited in dry-run, but
  skipped in real runs so future hand-filled or separately-ingested rows are
  not accidentally wiped.

Cache coupling:
  After all 32 pc_* tables refresh, the cron also calls
  cache.l4.sweep_expired() to drop TTL'd L4 entries — running this
  *after* the pc_* refresh (rather than before) means any L4 hit served
  during the refresh window still reflects the previous nightly state,
  which is the consistent behaviour.

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + standard library.
  * Read-only on autonomath.db (mode=ro URI) — the collection CLI owns
    that file and we must not mutate it from the API repo.

Usage:
    python scripts/cron/precompute_refresh.py            # real run
    python scripts/cron/precompute_refresh.py --dry-run  # log only
    python scripts/cron/precompute_refresh.py --only pc_top_subsidies_by_industry,pc_combo_pairs
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Make sibling cron scripts importable (e.g. refresh_amendment_diff).
_CRON_DIR = Path(__file__).resolve().parent
if str(_CRON_DIR) not in sys.path:
    sys.path.insert(0, str(_CRON_DIR))

from jpintel_mcp.cache.l4 import sweep_expired  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.precompute_refresh")


PC_TABLES_C3 = (
    # 14 tables added in migration 044 (dd_v8_C3).
    "pc_top_subsidies_by_industry",
    "pc_top_subsidies_by_prefecture",
    "pc_law_to_program_index",
    "pc_program_to_amendments",
    "pc_acceptance_stats_by_program",
    "pc_combo_pairs",
    "pc_seasonal_calendar",
    "pc_industry_jsic_aliases",
    "pc_authority_to_programs",
    "pc_law_amendments_recent",
    "pc_enforcement_by_industry",
    "pc_loan_by_collateral_type",
    "pc_certification_by_subject",
    "pc_starter_packs_per_audience",
)

PC_TABLES_D8 = (
    # 18 tables added in migration 045 (dd_v8_D8).
    "pc_amendment_recent_by_law",
    "pc_program_geographic_density",
    "pc_authority_action_frequency",
    "pc_law_to_amendment_chain",
    "pc_industry_jsic_to_program",
    "pc_amount_max_distribution",
    "pc_program_to_loan_combo",
    "pc_program_to_certification_combo",
    "pc_program_to_tax_combo",
    "pc_acceptance_rate_by_authority",
    "pc_application_close_calendar",
    "pc_amount_to_recipient_size",
    "pc_law_text_to_program_count",
    "pc_court_decision_law_chain",
    "pc_enforcement_industry_distribution",
    "pc_loan_collateral_to_program",
    "pc_invoice_registrant_by_pref",
    "pc_amendment_severity_distribution",
)

# E1 wave (migration 048+): tables that physically live in autonomath.db
# (the unified primary DB hosting jpi_* mirrored tables + am_* facts +
# entity_id_map). Their refreshers manage their own connection + tx — the
# outer _refresh_one skips the DELETE step on jpintel write_conn for these,
# because the table doesn't exist there.
#
# `am_amendment_diff` (migration 075) is append-only — its refresher must
# NEVER DELETE. The PC_TABLES_AM short-circuit in _refresh_one is exactly
# what we need: it delegates the entire tx to the refresher, which for the
# diff refresher is "INSERT only when something actually changed."
PC_TABLES_AM = (
    "jpi_pc_program_health",
    "am_amendment_diff",
)

PC_TABLES = PC_TABLES_C3 + PC_TABLES_D8 + PC_TABLES_AM

IMPLEMENTED_PC_TABLES = frozenset(
    {
        "pc_top_subsidies_by_prefecture",
        "pc_program_geographic_density",
        "pc_amount_max_distribution",
        "pc_application_close_calendar",
        "jpi_pc_program_health",
        "am_amendment_diff",
    }
)


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.precompute_refresh")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _open_jpintel(db_path: Path) -> sqlite3.Connection:
    return connect(db_path)


def _open_autonomath_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open autonomath.db read-only. Returns None if file missing / disabled."""
    if not settings.autonomath_enabled:
        logger.info("autonomath_disabled skipping_am_db")
        return None
    if not db_path.is_file():
        logger.warning("autonomath_db_missing path=%s", db_path)
        return None
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _refresh_one(
    name: str,
    refresher: Callable[[sqlite3.Connection, sqlite3.Connection | None], int],
    write_conn: sqlite3.Connection,
    read_conn: sqlite3.Connection | None,
    dry_run: bool,
    am_db_path: Path | None = None,
) -> int:
    """DELETE-then-INSERT one pc_* table inside a transaction. Returns rows.

    Tables in PC_TABLES_AM live in autonomath.db, not jpintel.db. For those
    the outer DELETE/tx is delegated to the refresher itself (it owns its own
    write connection); we short-circuit the jpintel-side ceremony here.

    `am_db_path` is forwarded only to AM-resident refreshers so that tests
    (and callers running against a non-default autonomath.db) can override
    the production path without monkeypatching settings.
    """
    if name in PC_TABLES_AM:
        if dry_run:
            existing = _count_am_table(name, am_db_path=am_db_path)
            logger.info("pc_dry_run table=%s db=autonomath current_rows=%d", name, existing)
            return 0
        try:
            rows = refresher(write_conn, read_conn, am_db_path=am_db_path)  # type: ignore[call-arg]
            logger.info("pc_refreshed table=%s db=autonomath rows=%d", name, rows)
            return rows
        except Exception as e:
            logger.exception("pc_refresh_failed table=%s err=%s", name, e)
            return 0

    if dry_run:
        existing = write_conn.execute(
            f"SELECT COUNT(*) FROM {name}"  # noqa: S608 — name from PC_TABLES whitelist
        ).fetchone()[0]
        logger.info("pc_dry_run table=%s current_rows=%d", name, int(existing))
        return 0

    if name not in IMPLEMENTED_PC_TABLES:
        logger.info("pc_skip_unimplemented table=%s", name)
        return 0

    write_conn.execute("BEGIN")
    try:
        write_conn.execute(
            f"DELETE FROM {name}"  # noqa: S608 — whitelisted name
        )
        rows = refresher(write_conn, read_conn)
        write_conn.execute("COMMIT")
        logger.info("pc_refreshed table=%s rows=%d", name, rows)
        return rows
    except Exception as e:
        write_conn.execute("ROLLBACK")
        logger.exception("pc_refresh_failed table=%s err=%s", name, e)
        return 0


def _count_am_table(name: str, am_db_path: Path | None = None) -> int:
    """Read-only row count from autonomath.db for dry-run reporting.

    When `am_db_path` is None we fall through to settings.autonomath_db_path
    (production behaviour). Tests pass a hermetic path; if the file or the
    target table doesn't exist there, return 0 rather than raise.
    """
    am_path = am_db_path if am_db_path is not None else settings.autonomath_db_path
    if not am_path.is_file():
        return 0
    uri = f"file:{am_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        if exists is None:
            return 0
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {name}"  # noqa: S608 — PC_TABLES_AM whitelist
            ).fetchone()[0]
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-table refreshers (pre-launch stubs).
#
# Each function:
#   * Receives an already-open write_conn (jpintel.db) inside a BEGIN tx.
#   * Receives read_conn (autonomath.db, read-only) — may be None when
#     AUTONOMATH_ENABLED=0 or the file is missing.
#   * Returns the number of rows it inserted into the pc_ table.
#
# The first wave is intentionally no-op: the table has just been wiped by
# _refresh_one, so the function returning 0 leaves the table empty —
# matching the launch-day expected state. Replace each body with the real
# projection SELECT once the per-tool ticket is ready.
# ---------------------------------------------------------------------------


def _refresh_pc_top_subsidies_by_industry(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_top_subsidies_by_prefecture(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    """Top 20 (rank 1..20) programs per ISO 3166-2:JP prefecture code.

    Source: programs (excluded=0, tier IN ('S','A','B','C')). Ranking is
    (tier_rank ASC, amount_max_man_yen DESC NULLS LAST, primary_name ASC)
    so S/A bubble up and large-amount programs win ties. We project
    Japanese prefecture name → ISO 3166-2:JP via the static map below;
    rows with prefecture='全国' or any non-47 value are skipped (the
    table's PK is (prefecture_code, rank) and 全国 has no ISO code in
    3166-2:JP).
    """
    iso = {
        "北海道": "JP-01",
        "青森県": "JP-02",
        "岩手県": "JP-03",
        "宮城県": "JP-04",
        "秋田県": "JP-05",
        "山形県": "JP-06",
        "福島県": "JP-07",
        "茨城県": "JP-08",
        "栃木県": "JP-09",
        "群馬県": "JP-10",
        "埼玉県": "JP-11",
        "千葉県": "JP-12",
        "東京都": "JP-13",
        "神奈川県": "JP-14",
        "新潟県": "JP-15",
        "富山県": "JP-16",
        "石川県": "JP-17",
        "福井県": "JP-18",
        "山梨県": "JP-19",
        "長野県": "JP-20",
        "岐阜県": "JP-21",
        "静岡県": "JP-22",
        "愛知県": "JP-23",
        "三重県": "JP-24",
        "滋賀県": "JP-25",
        "京都府": "JP-26",
        "大阪府": "JP-27",
        "兵庫県": "JP-28",
        "奈良県": "JP-29",
        "和歌山県": "JP-30",
        "鳥取県": "JP-31",
        "島根県": "JP-32",
        "岡山県": "JP-33",
        "広島県": "JP-34",
        "山口県": "JP-35",
        "徳島県": "JP-36",
        "香川県": "JP-37",
        "愛媛県": "JP-38",
        "高知県": "JP-39",
        "福岡県": "JP-40",
        "佐賀県": "JP-41",
        "長崎県": "JP-42",
        "熊本県": "JP-43",
        "大分県": "JP-44",
        "宮崎県": "JP-45",
        "鹿児島県": "JP-46",
        "沖縄県": "JP-47",
    }
    rows = w.execute(
        """
        SELECT prefecture, unified_id, tier, amount_max_man_yen, primary_name
        FROM programs
        WHERE excluded = 0
          AND tier IN ('S','A','B','C')
          AND prefecture IS NOT NULL
          AND prefecture != ''
        """
    ).fetchall()
    tier_rank = {"S": 0, "A": 1, "B": 2, "C": 3}
    by_pref: dict[str, list] = {}
    for pref, uid, tier, amt, name in rows:
        code = iso.get(pref)
        if code is None:
            continue
        # Sort key: tier asc, amount desc (NULLS LAST), name asc.
        amt_sort = -(amt or 0.0)
        by_pref.setdefault(code, []).append(
            (tier_rank.get(tier, 99), amt_sort, name or "", uid, tier, amt)
        )
    inserted = 0
    for code, items in by_pref.items():
        items.sort(key=lambda x: (x[0], x[1], x[2]))
        for rank, (tr, _amt_sort, _nm, uid, _tier, amt) in enumerate(items[:20], start=1):
            # relevance_score: tier weight (S=1.0, A=0.7, B=0.4, C=0.2)
            # plus log10(amount) tiebreaker normalised to ≤ 0.2.
            tier_weight = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.2}.get(tr, 0.0)
            amt_bonus = 0.0
            if amt and amt > 0:
                import math  # noqa: PLC0415

                amt_bonus = min(0.2, math.log10(max(1.0, amt)) / 25.0)
            score = round(tier_weight + amt_bonus, 4)
            w.execute(
                """
                INSERT INTO pc_top_subsidies_by_prefecture (
                    prefecture_code, rank, program_id,
                    relevance_score, cached_payload
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (code, rank, uid, score),
            )
            inserted += 1
    return inserted


def _refresh_pc_law_to_program_index(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_program_to_amendments(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_acceptance_stats_by_program(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_combo_pairs(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_seasonal_calendar(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_industry_jsic_aliases(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_authority_to_programs(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_law_amendments_recent(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_enforcement_by_industry(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_loan_by_collateral_type(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_certification_by_subject(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_starter_packs_per_audience(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


# ---------------------------------------------------------------------------
# Per-table refreshers — D8 wave (migration 045, 18 tables).
#
# Same contract as the C3 wave above: returns rows inserted, accepts the
# already-open write_conn (jpintel.db, inside a BEGIN tx) plus an optional
# read_conn (autonomath.db, read-only). All bodies are stubs returning 0
# pre-launch; population SELECTs land in follow-up tickets.
# ---------------------------------------------------------------------------


def _refresh_pc_amendment_recent_by_law(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_program_geographic_density(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    """Program count per (prefecture_code, tier).

    Same prefecture-name → ISO mapping as
    _refresh_pc_top_subsidies_by_prefecture. Skip 全国 / unknown names.
    Rows where the (prefecture, tier) combo is empty are simply not
    inserted (no zero-rows guarantee — the consumer must coalesce).
    """
    iso = {
        "北海道": "JP-01",
        "青森県": "JP-02",
        "岩手県": "JP-03",
        "宮城県": "JP-04",
        "秋田県": "JP-05",
        "山形県": "JP-06",
        "福島県": "JP-07",
        "茨城県": "JP-08",
        "栃木県": "JP-09",
        "群馬県": "JP-10",
        "埼玉県": "JP-11",
        "千葉県": "JP-12",
        "東京都": "JP-13",
        "神奈川県": "JP-14",
        "新潟県": "JP-15",
        "富山県": "JP-16",
        "石川県": "JP-17",
        "福井県": "JP-18",
        "山梨県": "JP-19",
        "長野県": "JP-20",
        "岐阜県": "JP-21",
        "静岡県": "JP-22",
        "愛知県": "JP-23",
        "三重県": "JP-24",
        "滋賀県": "JP-25",
        "京都府": "JP-26",
        "大阪府": "JP-27",
        "兵庫県": "JP-28",
        "奈良県": "JP-29",
        "和歌山県": "JP-30",
        "鳥取県": "JP-31",
        "島根県": "JP-32",
        "岡山県": "JP-33",
        "広島県": "JP-34",
        "山口県": "JP-35",
        "徳島県": "JP-36",
        "香川県": "JP-37",
        "愛媛県": "JP-38",
        "高知県": "JP-39",
        "福岡県": "JP-40",
        "佐賀県": "JP-41",
        "長崎県": "JP-42",
        "熊本県": "JP-43",
        "大分県": "JP-44",
        "宮崎県": "JP-45",
        "鹿児島県": "JP-46",
        "沖縄県": "JP-47",
    }
    rows = w.execute(
        """
        SELECT prefecture, tier, COUNT(*) AS n
        FROM programs
        WHERE excluded = 0
          AND tier IN ('S','A','B','C')
          AND prefecture IS NOT NULL
          AND prefecture != ''
        GROUP BY prefecture, tier
        """
    ).fetchall()
    inserted = 0
    for pref, tier, n in rows:
        code = iso.get(pref)
        if code is None or not n:
            continue
        w.execute(
            """
            INSERT INTO pc_program_geographic_density (
                prefecture_code, tier, program_count
            ) VALUES (?, ?, ?)
            """,
            (code, tier, int(n)),
        )
        inserted += 1
    return inserted


def _refresh_pc_authority_action_frequency(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_law_to_amendment_chain(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_industry_jsic_to_program(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_amount_max_distribution(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    """Histogram of programs.amount_max_man_yen across schema's 9 buckets.

    Buckets are in JPY (not 万円), matching the schema CHECK constraint
    enum: <1M, 1M-5M, 5M-10M, 10M-50M, 50M-100M, 100M-500M, 500M-1B, >1B,
    unknown. amount_max_man_yen is in 万円 — multiply by 1e4 to get JPY
    before bucketing. NULL or non-positive → 'unknown'.
    """
    rows = w.execute(
        """
        SELECT amount_max_man_yen
        FROM programs
        WHERE excluded = 0
          AND tier IN ('S','A','B','C')
        """
    ).fetchall()

    def _bucket(amt_man: float | None) -> str:
        if amt_man is None or amt_man <= 0:
            return "unknown"
        jpy = amt_man * 10_000.0
        if jpy < 1_000_000:
            return "<1M"
        if jpy < 5_000_000:
            return "1M-5M"
        if jpy < 10_000_000:
            return "5M-10M"
        if jpy < 50_000_000:
            return "10M-50M"
        if jpy < 100_000_000:
            return "50M-100M"
        if jpy < 500_000_000:
            return "100M-500M"
        if jpy < 1_000_000_000:
            return "500M-1B"
        return ">1B"

    counts: dict[str, int] = {}
    for (amt,) in rows:
        b = _bucket(amt)
        counts[b] = counts.get(b, 0) + 1
    inserted = 0
    for bucket, n in counts.items():
        w.execute(
            """
            INSERT INTO pc_amount_max_distribution (bucket, program_count)
            VALUES (?, ?)
            """,
            (bucket, int(n)),
        )
        inserted += 1
    return inserted


def _refresh_pc_program_to_loan_combo(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_program_to_certification_combo(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_program_to_tax_combo(w: sqlite3.Connection, r: sqlite3.Connection | None) -> int:
    return 0


def _refresh_pc_acceptance_rate_by_authority(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_application_close_calendar(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    """Per-month index of program close dates parsed from
    application_window_json.

    Source: programs.application_window_json (JSON dict). We pull
    end_date (top-level) and end_date inside each windows[] entry. Dates
    are kept as ISO 8601 strings; days_until is computed from the SQLite
    'now' the row is inserted with (matches refreshed_at semantics).
    Skip rows whose end_date doesn't parse to YYYY-MM-DD.
    """
    import json  # noqa: PLC0415
    from datetime import date  # noqa: PLC0415

    rows = w.execute(
        """
        SELECT unified_id, application_window_json
        FROM programs
        WHERE excluded = 0
          AND tier IN ('S','A','B','C')
          AND application_window_json IS NOT NULL
          AND application_window_json != ''
          AND application_window_json != 'null'
        """
    ).fetchall()
    today = date.today()
    seen: set[tuple[int, str, str]] = set()
    inserted = 0
    for uid, raw in rows:
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        # Collect all candidate close dates: top-level end_date plus each
        # windows[i].end_date (if windows[] is a list of dicts).
        candidates: list[str] = []
        top_end = obj.get("end_date")
        if isinstance(top_end, str) and top_end.strip():
            candidates.append(top_end.strip())
        windows = obj.get("windows")
        if isinstance(windows, list):
            for win in windows:
                if not isinstance(win, dict):
                    continue
                we = win.get("end_date")
                if isinstance(we, str) and we.strip():
                    candidates.append(we.strip())
        for cd in candidates:
            try:
                parsed = date.fromisoformat(cd[:10])
            except (TypeError, ValueError):
                continue
            month = parsed.month
            iso_str = parsed.isoformat()
            key = (month, uid, iso_str)
            if key in seen:
                continue
            seen.add(key)
            days_until = (parsed - today).days
            w.execute(
                """
                INSERT INTO pc_application_close_calendar (
                    month_of_year, program_id, close_date, days_until
                ) VALUES (?, ?, ?, ?)
                """,
                (month, uid, iso_str, days_until),
            )
            inserted += 1
    return inserted


def _refresh_pc_amount_to_recipient_size(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_law_text_to_program_count(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_court_decision_law_chain(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_enforcement_industry_distribution(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_loan_collateral_to_program(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_invoice_registrant_by_pref(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


def _refresh_pc_amendment_severity_distribution(
    w: sqlite3.Connection, r: sqlite3.Connection | None
) -> int:
    return 0


# ---------------------------------------------------------------------------
# Per-table refreshers — E1 wave (migration 048+, autonomath.db resident).
#
# These refreshers IGNORE the passed-in (jpintel) write_conn and read_conn,
# and open their own rw connection to autonomath.db, because the target
# table physically lives there alongside its source tables (am_entity_*,
# entity_id_map, jpi_*). _refresh_one short-circuits its own DELETE/tx for
# these — the refresher manages everything.
# ---------------------------------------------------------------------------


def _refresh_pc_program_health(
    w: sqlite3.Connection,
    r: sqlite3.Connection | None,
    am_db_path: Path | None = None,
) -> int:
    """Aggregate am_entity_annotation -> per-program health snapshot.

    Source: am_entity_annotation joined to jpi_programs via entity_id_map.
    Window: last 90 days, excluding superseded rows.
    Per program (jpi_programs.unified_id) we compute:
      * quality_score          AVG of kind='quality_score'.score
      * warning_count_recent   COUNT of kind='examiner_warning' AND
                               severity IN ('warning','critical')
      * critical_count_recent  COUNT of kind IN ('examiner_warning',
                               'validation_failure') AND severity='critical'
      * last_validated_at      MAX(observed_at)
      * refreshed_at           datetime('now')

    The whole DELETE+INSERT runs inside a single tx on autonomath.db so
    readers never see a partially-rebuilt snapshot.

    The optional `am_db_path` param overrides settings.autonomath_db_path
    so tests (and `run(am_db_path=...)` callers) can target a hermetic DB
    instead of the production one. Production callers pass nothing and
    fall through to the configured default.
    """
    am_path = am_db_path if am_db_path is not None else settings.autonomath_db_path
    if not am_path.is_file():
        logger.warning("am_db_missing path=%s skipping_program_health", am_path)
        return 0
    conn = connect(am_path)
    try:
        # If the target table doesn't exist (e.g. test fixture's am_db
        # didn't apply migration 048), there's nothing to refresh — bail
        # out cleanly with 0 rows rather than crashing the whole nightly.
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jpi_pc_program_health'"
        ).fetchone()
        if exists is None:
            logger.warning("am_table_missing table=jpi_pc_program_health path=%s", am_path)
            return 0
        conn.execute("BEGIN")
        conn.execute("DELETE FROM jpi_pc_program_health")
        conn.execute(
            """
            WITH program_annot AS (
              SELECT jp.unified_id AS program_id,
                     ea.kind, ea.severity, ea.score, ea.observed_at
              FROM am_entity_annotation ea
              JOIN entity_id_map eim ON eim.am_canonical_id = ea.entity_id
              JOIN jpi_programs   jp  ON jp.unified_id = eim.jpi_unified_id
              WHERE ea.observed_at > datetime('now', '-90 days')
                AND ea.superseded_at IS NULL
            )
            INSERT INTO jpi_pc_program_health (
              program_id, quality_score, warning_count_recent,
              critical_count_recent, last_validated_at, refreshed_at
            )
            SELECT
              program_id,
              AVG(CASE WHEN kind='quality_score' THEN score END),
              SUM(CASE WHEN kind='examiner_warning'
                        AND severity IN ('warning','critical') THEN 1 ELSE 0 END),
              SUM(CASE WHEN kind IN ('examiner_warning','validation_failure')
                        AND severity='critical' THEN 1 ELSE 0 END),
              MAX(observed_at),
              datetime('now')
            FROM program_annot
            GROUP BY program_id
            """
        )
        rows = int(conn.execute("SELECT COUNT(*) FROM jpi_pc_program_health").fetchone()[0])
        conn.execute("COMMIT")
        return rows
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _refresh_am_amendment_diff(
    w: sqlite3.Connection,
    r: sqlite3.Connection | None,
    am_db_path: Path | None = None,
) -> int:
    """Append-only amendment diff log (Z3 phantom-moat fix, migration 075).

    Delegates to scripts/cron/refresh_amendment_diff.run() so the cron
    body lives next to the table it owns. Returns the number of diff rows
    appended in this run (0 when nothing changed — the idempotent path).

    The wrapped function manages its own connection + tx. _refresh_one's
    PC_TABLES_AM short-circuit means we never DELETE here; that is the
    point of an append-only log.
    """
    am_path = am_db_path if am_db_path is not None else settings.autonomath_db_path
    # Local import to avoid loading the cron module unless this refresher
    # actually fires (matches the pattern used elsewhere in this file).
    from refresh_amendment_diff import run as _refresh_diff  # noqa: PLC0415

    counters = _refresh_diff(am_db_path=am_path, limit=None, dry_run=False)
    return int(counters.get("diff_rows_inserted", 0))


REFRESHERS: dict[str, Callable[[sqlite3.Connection, sqlite3.Connection | None], int]] = {
    # C3 wave (migration 044).
    "pc_top_subsidies_by_industry": _refresh_pc_top_subsidies_by_industry,
    "pc_top_subsidies_by_prefecture": _refresh_pc_top_subsidies_by_prefecture,
    "pc_law_to_program_index": _refresh_pc_law_to_program_index,
    "pc_program_to_amendments": _refresh_pc_program_to_amendments,
    "pc_acceptance_stats_by_program": _refresh_pc_acceptance_stats_by_program,
    "pc_combo_pairs": _refresh_pc_combo_pairs,
    "pc_seasonal_calendar": _refresh_pc_seasonal_calendar,
    "pc_industry_jsic_aliases": _refresh_pc_industry_jsic_aliases,
    "pc_authority_to_programs": _refresh_pc_authority_to_programs,
    "pc_law_amendments_recent": _refresh_pc_law_amendments_recent,
    "pc_enforcement_by_industry": _refresh_pc_enforcement_by_industry,
    "pc_loan_by_collateral_type": _refresh_pc_loan_by_collateral_type,
    "pc_certification_by_subject": _refresh_pc_certification_by_subject,
    "pc_starter_packs_per_audience": _refresh_pc_starter_packs_per_audience,
    # D8 wave (migration 045).
    "pc_amendment_recent_by_law": _refresh_pc_amendment_recent_by_law,
    "pc_program_geographic_density": _refresh_pc_program_geographic_density,
    "pc_authority_action_frequency": _refresh_pc_authority_action_frequency,
    "pc_law_to_amendment_chain": _refresh_pc_law_to_amendment_chain,
    "pc_industry_jsic_to_program": _refresh_pc_industry_jsic_to_program,
    "pc_amount_max_distribution": _refresh_pc_amount_max_distribution,
    "pc_program_to_loan_combo": _refresh_pc_program_to_loan_combo,
    "pc_program_to_certification_combo": _refresh_pc_program_to_certification_combo,
    "pc_program_to_tax_combo": _refresh_pc_program_to_tax_combo,
    "pc_acceptance_rate_by_authority": _refresh_pc_acceptance_rate_by_authority,
    "pc_application_close_calendar": _refresh_pc_application_close_calendar,
    "pc_amount_to_recipient_size": _refresh_pc_amount_to_recipient_size,
    "pc_law_text_to_program_count": _refresh_pc_law_text_to_program_count,
    "pc_court_decision_law_chain": _refresh_pc_court_decision_law_chain,
    "pc_enforcement_industry_distribution": _refresh_pc_enforcement_industry_distribution,
    "pc_loan_collateral_to_program": _refresh_pc_loan_collateral_to_program,
    "pc_invoice_registrant_by_pref": _refresh_pc_invoice_registrant_by_pref,
    "pc_amendment_severity_distribution": _refresh_pc_amendment_severity_distribution,
    # E1 wave (migration 048+, autonomath.db resident).
    "jpi_pc_program_health": _refresh_pc_program_health,
    # Z3 wave (migration 075, autonomath.db resident, append-only).
    "am_amendment_diff": _refresh_am_amendment_diff,
}


def run(
    db_path: Path,
    am_db_path: Path,
    only: list[str] | None,
    dry_run: bool,
) -> dict[str, int]:
    counters: dict[str, int] = {}
    targets = list(only) if only else list(PC_TABLES)
    bad = [t for t in targets if t not in REFRESHERS]
    if bad:
        logger.error("unknown_pc_tables names=%s", bad)
        return counters

    logger.info(
        "pc_refresh_start db=%s am_db=%s targets=%d dry_run=%s",
        db_path,
        am_db_path,
        len(targets),
        dry_run,
    )

    write_conn = _open_jpintel(db_path)
    read_conn = _open_autonomath_ro(am_db_path)
    try:
        for name in targets:
            counters[name] = _refresh_one(
                name=name,
                refresher=REFRESHERS[name],
                write_conn=write_conn,
                read_conn=read_conn,
                dry_run=dry_run,
                am_db_path=am_db_path,
            )

        if not dry_run:
            swept = sweep_expired(db_path)
            counters["__l4_swept__"] = swept

        total = sum(v for k, v in counters.items() if not k.startswith("__"))
        logger.info(
            "pc_refresh_done tables=%d total_rows=%d l4_swept=%d",
            len(targets),
            total,
            counters.get("__l4_swept__", 0),
        )
        return counters
    finally:
        if read_conn is not None:
            read_conn.close()
        write_conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh pc_* materialized tables")
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to jpintel.db (default: settings.db_path)",
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated subset of pc_* table names",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log targets only; no DELETE/INSERT/sweep",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    db_path = args.db if args.db else settings.db_path
    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None

    with heartbeat("precompute_refresh") as hb:
        try:
            counters = run(
                db_path=db_path,
                am_db_path=am_db_path,
                only=only,
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("pc_refresh_failed err=%s", e)
            return 1
        if isinstance(counters, dict):
            hb["rows_processed"] = int(
                counters.get("rows_inserted", counters.get("refreshed", 0)) or 0
            )
            hb["metadata"] = {
                k: counters.get(k)
                for k in ("targets", "swept", "skipped", "dry_run")
                if k in counters
            }
        else:
            hb["metadata"] = {"only": only, "dry_run": bool(args.dry_run)}
    return 0


if __name__ == "__main__":
    sys.exit(main())
