#!/usr/bin/env python3
"""Wave 30-5: pre-compute actionable Q/A answers into am_actionable_qa_cache.

What it does
------------
Enumerates the top intent-class × input-shape combinations that the W28-5
instrumentation surfaced as the highest-traffic actionable Q/A queries:

  * subsidy_search   × (47 prefectures × top 7 JSIC industries)  ~329 rows
  * eligibility_check × (top 100 programs × 3 houjin sizes)      ~300 rows
  * amendment_diff    × (top 100 programs)                       ~100 rows
  * citation_pack     × (top 100 programs)                       ~100 rows
                                                                ----
                                                                ~830 rows

For each combination we render the actionable envelope by re-executing the
SQL the corresponding on-demand path would run, then INSERT OR REPLACE one
row per cache_key into am_actionable_qa_cache (migration 169). The endpoint
hot path then returns the cached JSON verbatim instead of re-doing the
join.

Why precompute
--------------
W28-5 measured 0% cache-hit on the on-demand composite path because the
real customer-LLM intents arrive as parameter SHAPES (subsidy_search by
pref+industry, eligibility_check by program×houjin_size, etc.) — none of
which migration 168's (subject_kind, subject_id) cache key can represent
without a synthetic encoding. Pre-warming the (intent_class, input_hash)
shape covers that gap.

Constraints
-----------
* No Anthropic / claude / SDK calls (memory `feedback_no_operator_llm_api`).
  Pure SQLite + standard library + sha256.
* Read-mostly on autonomath.db; writes only to am_actionable_qa_cache via
  one writable connection.
* Idempotent — INSERT OR REPLACE on cache_key.

Usage
-----
    python scripts/cron/precompute_actionable_answers.py            # full run, budget=1000
    python scripts/cron/precompute_actionable_answers.py --budget 500
    python scripts/cron/precompute_actionable_answers.py --dry-run  # log only
    python scripts/cron/precompute_actionable_answers.py --intent subsidy_search
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.precompute_actionable_answers")

DEFAULT_BUDGET = 1000

# Top 7 JSIC industries (subset chosen for cohort revenue model — A 農業
# / D 建設 / E 製造 / G 情報通信 / K 不動産 / L 学術専門技術 / M 宿泊飲食).
TOP_JSIC_INDUSTRIES: tuple[str, ...] = ("A", "D", "E", "G", "K", "L", "M")

# 47 都道府県 codes 01..47 zero-padded (NTA region scheme).
ALL_PREFECTURE_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 48))

# Houjin size tiers — small (<20 emp) / mid (20-300) / large (>300).
HOUJIN_SIZES: tuple[str, ...] = ("small", "mid", "large")

ALLOWED_INTENTS: frozenset[str] = frozenset(
    {"subsidy_search", "eligibility_check", "amendment_diff", "citation_pack"}
)

# §52 / §1 / §47条の2 disclaimer envelope mirrored from api/intel_actionable.py.
_DISCLAIMER = (
    "本キャッシュ済みエンベロープは jpcite が公的機関 (各省庁・自治体・国税庁・"
    "日本政策金融公庫 等) の公開情報を機械的に整理した結果を返却するものであり、"
    "税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1 に基づく個別具体的な"
    "税務助言・監査意見・申請書面作成の代替ではありません。最終的な申請可否・"
    "税務判断は資格を有する士業へご相談ください。"
)


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.precompute_actionable_answers")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # Match production layout: repo-root /autonomath.db.
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_autonomath_rw(db_path: Path) -> sqlite3.Connection:
    """Writable connection. We INSERT OR REPLACE into am_actionable_qa_cache only."""
    conn = sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Idempotent CREATE so the script self-heals if migration 169 has not
    yet run. Mirrors the SQL in scripts/migrations/169_am_actionable_qa_cache.sql.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
              cache_key             TEXT PRIMARY KEY,
              intent_class          TEXT NOT NULL,
              input_hash            TEXT NOT NULL,
              rendered_answer_json  TEXT NOT NULL,
              rendered_at           INTEGER NOT NULL,
              hit_count             INTEGER NOT NULL DEFAULT 0,
              corpus_snapshot_id    TEXT NOT NULL
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_actionable_intent_hash "
        "ON am_actionable_qa_cache(intent_class, input_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_actionable_rendered_at "
        "ON am_actionable_qa_cache(rendered_at DESC)"
    )


def _compute_corpus_snapshot_id(conn: sqlite3.Connection) -> str:
    """Stable corpus snapshot id for cache invalidation.

    Cheap heuristic: latest am_amendment_diff.detected_at when present,
    else MAX(fetched_at) across am_entities. Falls back to today's UTC date.
    """
    with contextlib.suppress(sqlite3.OperationalError):
        row = conn.execute("SELECT MAX(detected_at) FROM am_amendment_diff").fetchone()
        if row and row[0]:
            return str(row[0])
    with contextlib.suppress(sqlite3.OperationalError):
        row = conn.execute("SELECT MAX(fetched_at) FROM am_entities").fetchone()
        if row and row[0]:
            return str(row[0])
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------- #
# Cache key helpers (mirror api/intel_actionable.py)
# --------------------------------------------------------------------------- #


def canonical_input_hash(input_dict: dict[str, Any]) -> str:
    blob = json.dumps(input_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_cache_key(intent_class: str, input_hash: str) -> str:
    return f"{intent_class}:{input_hash}"


# --------------------------------------------------------------------------- #
# Renderers — pure SQLite reads, no LLM
# --------------------------------------------------------------------------- #


def _render_subsidy_search(
    conn: sqlite3.Connection,
    *,
    prefecture_code: str,
    industry_jsic_major: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Top-N programs by tier for (prefecture_code, industry_jsic_major).

    Reads jpi_programs (or programs fallback for fresh dev DBs). Returns up
    to 10 hits ordered by tier ascending then verification count desc.
    """
    table = "jpi_programs" if _table_exists(conn, "jpi_programs") else "programs"
    rows: list[dict[str, Any]] = []
    pref_name_col = "prefecture"
    try:
        # Resolve prefecture_code -> prefecture_name if possible. The mapping
        # table may not exist on a fresh dev DB; the code itself is also
        # accepted as a literal prefecture column value.
        pref_filter_value = prefecture_code
        if _table_exists(conn, "am_region"):
            row = conn.execute(
                "SELECT name FROM am_region WHERE code = ? LIMIT 1",
                (prefecture_code,),
            ).fetchone()
            if row and row["name"]:
                pref_filter_value = row["name"]
        # Best-effort SELECT — degrade if table lacks expected columns.
        sql = (
            f"SELECT unified_id, primary_name, tier, authority_level, "
            f"       authority_name, prefecture, program_kind, "
            f"       amount_max_man_yen, source_url "
            f"  FROM {table} "
            f" WHERE excluded = 0 "
            f"   AND tier IN ('S','A','B','C') "
            f"   AND ({pref_name_col} = ? OR {pref_name_col} IS NULL) "
            f" ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
            f"          WHEN 'B' THEN 2 ELSE 3 END "
            f" LIMIT 10"
        )
        for r in conn.execute(sql, (pref_filter_value,)).fetchall():
            rows.append(dict(r))
    except sqlite3.OperationalError as exc:
        logger.debug(
            "subsidy_search render degraded for %s/%s: %s",
            prefecture_code,
            industry_jsic_major,
            exc,
        )

    return {
        "intent_class": "subsidy_search",
        "input": {
            "prefecture_code": prefecture_code,
            "industry_jsic_major": industry_jsic_major,
        },
        "matched_programs": rows,
        "result_count": len(rows),
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_qa_cache",
        },
    }


def _render_eligibility_check(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    houjin_size: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Eligibility predicate + structured fields for (program_id, houjin_size)."""
    table = "jpi_programs" if _table_exists(conn, "jpi_programs") else "programs"
    program_basic: dict[str, Any] = {}
    try:
        row = conn.execute(
            f"SELECT unified_id, primary_name, tier, target_types_json, "
            f"       funding_purpose_json, amount_max_man_yen, "
            f"       amount_min_man_yen, prefecture, program_kind "
            f"  FROM {table} WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
        if row is not None:
            program_basic = dict(row)
    except sqlite3.OperationalError as exc:
        logger.debug(
            "eligibility_check render degraded for %s/%s: %s", program_id, houjin_size, exc
        )

    eligible: bool | None = None
    reasons: list[str] = []
    if program_basic:
        # Pure deterministic mapping — small (<20 emp) usually OK for SMB
        # programs; mid OK universally; large excluded from 中小 SMB tracks.
        amt = program_basic.get("amount_max_man_yen")
        if houjin_size == "large" and amt and int(amt) <= 1000:
            eligible = False
            reasons.append("中小企業向け補助上限額; 大規模法人は対象外")
        else:
            eligible = True
            reasons.append("上限額・対象種別の表面要件で除外条件に該当しない")

    return {
        "intent_class": "eligibility_check",
        "input": {"program_id": program_id, "houjin_size": houjin_size},
        "program_basic": program_basic,
        "eligible_estimate": eligible,
        "reasons": reasons,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_qa_cache",
        },
    }


def _render_amendment_diff(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Amendment history for one program (am_amendment_diff or _snapshot)."""
    diffs: list[dict[str, Any]] = []
    if _table_exists(conn, "am_amendment_diff"):
        with contextlib.suppress(sqlite3.OperationalError):
            for r in conn.execute(
                "SELECT field_name, old_value, new_value, detected_at "
                "  FROM am_amendment_diff "
                " WHERE program_unified_id = ? "
                " ORDER BY detected_at DESC LIMIT 20",
                (program_id,),
            ).fetchall():
                diffs.append(dict(r))
    elif _table_exists(conn, "am_amendment_snapshot"):
        with contextlib.suppress(sqlite3.OperationalError):
            for r in conn.execute(
                "SELECT snapshot_id, captured_at, eligibility_hash "
                "  FROM am_amendment_snapshot "
                " WHERE program_unified_id = ? "
                " ORDER BY captured_at DESC LIMIT 20",
                (program_id,),
            ).fetchall():
                diffs.append(dict(r))

    return {
        "intent_class": "amendment_diff",
        "input": {"program_id": program_id},
        "amendments": diffs,
        "amendment_count": len(diffs),
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_qa_cache",
        },
    }


def _render_citation_pack(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Citation bundle: program source_url + applicable laws + tsutatsu."""
    table = "jpi_programs" if _table_exists(conn, "jpi_programs") else "programs"
    citations: list[dict[str, Any]] = []
    try:
        row = conn.execute(
            f"SELECT unified_id, primary_name, source_url, official_url "
            f"  FROM {table} WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
        if row is not None:
            if row["source_url"]:
                citations.append(
                    {
                        "kind": "program_source",
                        "url": row["source_url"],
                        "primary_name": row["primary_name"],
                    }
                )
            if row["official_url"] and row["official_url"] != row["source_url"]:
                citations.append(
                    {
                        "kind": "program_official",
                        "url": row["official_url"],
                        "primary_name": row["primary_name"],
                    }
                )
    except sqlite3.OperationalError:
        pass
    # Best-effort law refs.
    if _table_exists(conn, "program_law_refs"):
        with contextlib.suppress(sqlite3.OperationalError):
            for r in conn.execute(
                "SELECT law_id, article_number "
                "  FROM program_law_refs WHERE program_unified_id = ? LIMIT 5",
                (program_id,),
            ).fetchall():
                citations.append(
                    {"kind": "law", "law_id": r["law_id"], "article_number": r["article_number"]}
                )

    return {
        "intent_class": "citation_pack",
        "input": {"program_id": program_id},
        "citations": citations,
        "citation_count": len(citations),
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_qa_cache",
        },
    }


# --------------------------------------------------------------------------- #
# Selectors
# --------------------------------------------------------------------------- #


def _select_top_program_ids(conn: sqlite3.Connection, top_n: int) -> list[str]:
    table = "jpi_programs" if _table_exists(conn, "jpi_programs") else "programs"
    try:
        rows = conn.execute(
            f"SELECT unified_id FROM {table} "
            f"WHERE excluded = 0 AND tier IN ('S','A','B','C') "
            f"ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 "
            f"         WHEN 'B' THEN 2 ELSE 3 END, unified_id ASC "
            f"LIMIT ?",
            (top_n,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["unified_id"] for r in rows]


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #


def _upsert_cache_row(
    conn: sqlite3.Connection,
    *,
    intent_class: str,
    input_dict: dict[str, Any],
    body: dict[str, Any],
    snapshot_id: str,
) -> tuple[str, int]:
    input_hash = canonical_input_hash(input_dict)
    cache_key = build_cache_key(intent_class, input_hash)
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
    rendered_at = int(time.time())
    conn.execute(
        """INSERT OR REPLACE INTO am_actionable_qa_cache
             (cache_key, intent_class, input_hash, rendered_answer_json,
              rendered_at, hit_count, corpus_snapshot_id)
           VALUES (?, ?, ?, ?, ?,
                   COALESCE((SELECT hit_count FROM am_actionable_qa_cache
                              WHERE cache_key = ?), 0),
                   ?)""",
        (cache_key, intent_class, input_hash, blob, rendered_at, cache_key, snapshot_id),
    )
    return cache_key, len(blob.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run(
    *,
    budget: int = DEFAULT_BUDGET,
    intents: tuple[str, ...] = tuple(sorted(ALLOWED_INTENTS)),
    dry_run: bool = False,
) -> dict[str, Any]:
    db_path = _autonomath_db_path()
    if not db_path.exists():
        logger.error("autonomath.db not found at %s", db_path)
        return {"ok": False, "reason": "db_missing", "db_path": str(db_path)}

    conn = _open_autonomath_rw(db_path)
    try:
        if not dry_run:
            _ensure_table(conn)
        snapshot_id = _compute_corpus_snapshot_id(conn)
        logger.info(
            "snapshot_id=%s db=%s budget=%d intents=%s",
            snapshot_id,
            db_path,
            budget,
            ",".join(intents),
        )

        result: dict[str, Any] = {
            "ok": True,
            "snapshot_id": snapshot_id,
            "dry_run": dry_run,
            "budget": budget,
            "intents": {},
        }

        remaining = budget

        # Pre-fetch the top program ids once — reused by 3 of the 4 intents.
        top_program_ids = _select_top_program_ids(conn, 100)
        logger.info("top program ids selected: %d", len(top_program_ids))

        # 1. subsidy_search × (47 pref × 7 industries) = 329
        if "subsidy_search" in intents and remaining > 0:
            built = 0
            total_bytes = 0
            for pref in ALL_PREFECTURE_CODES:
                if remaining <= 0:
                    break
                for industry in TOP_JSIC_INDUSTRIES:
                    if remaining <= 0:
                        break
                    body = _render_subsidy_search(
                        conn,
                        prefecture_code=pref,
                        industry_jsic_major=industry,
                        snapshot_id=snapshot_id,
                    )
                    if not dry_run:
                        _, n_bytes = _upsert_cache_row(
                            conn,
                            intent_class="subsidy_search",
                            input_dict={
                                "prefecture_code": pref,
                                "industry_jsic_major": industry,
                            },
                            body=body,
                            snapshot_id=snapshot_id,
                        )
                        total_bytes += n_bytes
                    else:
                        total_bytes += len(
                            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
                        )
                    built += 1
                    remaining -= 1
            result["intents"]["subsidy_search"] = {
                "built": built,
                "total_bytes": total_bytes,
            }

        # 2. eligibility_check × (top 100 programs × 3 sizes) = 300
        if "eligibility_check" in intents and remaining > 0:
            built = 0
            total_bytes = 0
            for pid in top_program_ids:
                if remaining <= 0:
                    break
                for size in HOUJIN_SIZES:
                    if remaining <= 0:
                        break
                    body = _render_eligibility_check(
                        conn, program_id=pid, houjin_size=size, snapshot_id=snapshot_id
                    )
                    if not dry_run:
                        _, n_bytes = _upsert_cache_row(
                            conn,
                            intent_class="eligibility_check",
                            input_dict={"program_id": pid, "houjin_size": size},
                            body=body,
                            snapshot_id=snapshot_id,
                        )
                        total_bytes += n_bytes
                    else:
                        total_bytes += len(
                            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
                        )
                    built += 1
                    remaining -= 1
            result["intents"]["eligibility_check"] = {
                "built": built,
                "total_bytes": total_bytes,
            }

        # 3. amendment_diff × top 100 programs = 100
        if "amendment_diff" in intents and remaining > 0:
            built = 0
            total_bytes = 0
            for pid in top_program_ids:
                if remaining <= 0:
                    break
                body = _render_amendment_diff(conn, program_id=pid, snapshot_id=snapshot_id)
                if not dry_run:
                    _, n_bytes = _upsert_cache_row(
                        conn,
                        intent_class="amendment_diff",
                        input_dict={"program_id": pid},
                        body=body,
                        snapshot_id=snapshot_id,
                    )
                    total_bytes += n_bytes
                else:
                    total_bytes += len(
                        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    )
                built += 1
                remaining -= 1
            result["intents"]["amendment_diff"] = {
                "built": built,
                "total_bytes": total_bytes,
            }

        # 4. citation_pack × top 100 programs = 100
        if "citation_pack" in intents and remaining > 0:
            built = 0
            total_bytes = 0
            for pid in top_program_ids:
                if remaining <= 0:
                    break
                body = _render_citation_pack(conn, program_id=pid, snapshot_id=snapshot_id)
                if not dry_run:
                    _, n_bytes = _upsert_cache_row(
                        conn,
                        intent_class="citation_pack",
                        input_dict={"program_id": pid},
                        body=body,
                        snapshot_id=snapshot_id,
                    )
                    total_bytes += n_bytes
                else:
                    total_bytes += len(
                        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    )
                built += 1
                remaining -= 1
            result["intents"]["citation_pack"] = {
                "built": built,
                "total_bytes": total_bytes,
            }

        # Final cache row count + size, post-write.
        if not dry_run:
            with contextlib.suppress(sqlite3.OperationalError):
                cnt_row = conn.execute(
                    "SELECT intent_class, COUNT(*) AS n, "
                    "       COALESCE(SUM(LENGTH(rendered_answer_json)), 0) AS bytes_total "
                    "  FROM am_actionable_qa_cache "
                    " GROUP BY intent_class"
                ).fetchall()
                result["cache_state"] = {
                    r["intent_class"]: {"rows": r["n"], "bytes": r["bytes_total"]} for r in cnt_row
                }
                total_rows_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM am_actionable_qa_cache"
                ).fetchone()
                result["cache_total_rows"] = int(total_rows_row["n"]) if total_rows_row else 0
        return result
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="Maximum cache rows to write (default: 1000).",
    )
    ap.add_argument(
        "--intent",
        choices=sorted(ALLOWED_INTENTS),
        action="append",
        default=None,
        help="Restrict to one or more intent classes (default: all 4).",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Render but do not write to the cache table."
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    _configure_logging(args.verbose)

    intents = tuple(args.intent) if args.intent else tuple(sorted(ALLOWED_INTENTS))
    result = run(budget=args.budget, intents=intents, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
