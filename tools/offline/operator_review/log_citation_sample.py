#!/usr/bin/env python3
"""log_citation_sample.py — DEEP-43 manual citation sample logger.

Reads operator-filled CSV (4 LLM × 100 query × 1 month = 400 sample),
aggregates monthly + per-LLM citation rate, writes JSON for DEEP-42
evolution dashboard cascade_tipping panel.

NO LLM API calls — read-only stdlib only. The sampling itself is operator
manual (browser web UI, eyes-on judgement); this script does ONLY
aggregation + rollup. Any addition of LLM SDK imports (Anthropic / OpenAI /
Google Generative AI) here is a §43.4 spec violation.

Usage
-----
    python log_citation_sample.py --month 2026-05
    python log_citation_sample.py --month 2026-05 --csv path/to/sample.csv
    python log_citation_sample.py --month 2026-05 --upsert-db
    python log_citation_sample.py --month 2026-05 --json-out custom.json
    python log_citation_sample.py --validate-query-set

Outputs
-------
- citation_rate_<YYYY-MM>.json : monthly aggregate (LLM-level + overall q)
- (optional) UPSERT into autonomath.citation_sample table

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/
       DEEP_43_ai_crawler_citation_sample.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import pathlib
import sqlite3
import sys
from typing import Any

TOOL_VERSION = "log_citation_sample/0.1.0"
HERE = pathlib.Path(__file__).resolve().parent
QUERY_SET_PATH = HERE / "citation_query_set_100.json"
DEFAULT_CSV_TEMPLATE = "citation_samples_{month}.csv"
DEFAULT_JSON_TEMPLATE = "citation_rate_{month}.json"
DEFAULT_DB_PATH = pathlib.Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(pathlib.Path(__file__).resolve().parents[3] / "autonomath.db"),
    )
)

LLM_PROVIDERS = ("claude", "perplexity", "chatgpt", "gemini")
CRITICAL_Q_STAR = 0.10
TIPPING_BANDS = {"pre_tipping": 0.05, "approach": 0.10}
EXPECTED_QUERIES_PER_LLM = 100
EXPECTED_TOTAL_SAMPLES = 400


# ---------------------------------------------------------------------------
# query set validation
# ---------------------------------------------------------------------------


def load_query_set(path: pathlib.Path = QUERY_SET_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"query set missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_query_set(qs: dict[str, Any]) -> dict[str, Any]:
    queries = qs.get("queries") or []
    if len(queries) != 100:
        raise ValueError(f"expected 100 queries, got {len(queries)}")
    sensitive = [q for q in queries if q.get("category") == "sensitive"]
    non_sensitive = [q for q in queries if q.get("category") == "non_sensitive"]
    general = [q for q in queries if q.get("category") == "general"]
    if len(sensitive) != 24:
        raise ValueError(f"sensitive cohort expected 24, got {len(sensitive)}")
    if len(non_sensitive) != 24:
        raise ValueError(f"non_sensitive cohort expected 24, got {len(non_sensitive)}")
    if len(general) != 52:
        raise ValueError(f"general cohort expected 52, got {len(general)}")
    ids = [q.get("query_id") for q in queries]
    if len(set(ids)) != 100:
        raise ValueError(f"query_id collisions: {len(ids) - len(set(ids))} dup")
    if qs.get("ll_api_calls") not in (0, "0"):
        raise ValueError("query set claims non-zero LLM API calls — spec violation")
    return {
        "ok": True,
        "total": 100,
        "sensitive": 24,
        "non_sensitive": 24,
        "general": 52,
    }


# ---------------------------------------------------------------------------
# CSV ingest
# ---------------------------------------------------------------------------


def parse_csv(csv_path: pathlib.Path) -> list[dict[str, Any]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV missing: {csv_path}")
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            try:
                jpcite = int(raw.get("jpcite_cited") or 0)
                competitor = int(raw.get("competitor_cited") or 0)
            except (TypeError, ValueError):
                jpcite = 0
                competitor = 0
            llm = (raw.get("llm_provider") or "").strip().lower()
            if llm not in LLM_PROVIDERS:
                continue  # skip header / malformed
            rows.append(
                {
                    "sample_month": (raw.get("sample_month") or "").strip(),
                    "llm_provider": llm,
                    "query_id": (raw.get("query_id") or "").strip(),
                    "query_text": (raw.get("query_text") or "").strip(),
                    "jpcite_cited": 1 if jpcite else 0,
                    "competitor_cited": 1 if competitor else 0,
                    "citation_url": (raw.get("citation_url") or "").strip() or None,
                    "sampled_at": (raw.get("sampled_at") or "").strip()
                    or _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "sampled_by": (raw.get("sampled_by") or "operator").strip(),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def aggregate(rows: list[dict[str, Any]], month: str) -> dict[str, Any]:
    by_llm: dict[str, dict[str, Any]] = {
        llm: {"sample_count": 0, "jpcite_cited": 0, "competitor_cited": 0} for llm in LLM_PROVIDERS
    }
    total = 0
    total_jpcite = 0
    total_competitor = 0
    for r in rows:
        if r["sample_month"] != month:
            continue
        llm = r["llm_provider"]
        if llm not in by_llm:
            continue
        by_llm[llm]["sample_count"] += 1
        by_llm[llm]["jpcite_cited"] += r["jpcite_cited"]
        by_llm[llm]["competitor_cited"] += r["competitor_cited"]
        total += 1
        total_jpcite += r["jpcite_cited"]
        total_competitor += r["competitor_cited"]

    per_llm: dict[str, dict[str, Any]] = {}
    for llm, agg in by_llm.items():
        n = agg["sample_count"]
        per_llm[llm] = {
            "sample_count": n,
            "jpcite_cited": agg["jpcite_cited"],
            "competitor_cited": agg["competitor_cited"],
            "jpcite_rate": round(agg["jpcite_cited"] / n, 4) if n else 0.0,
            "competitor_rate": round(agg["competitor_cited"] / n, 4) if n else 0.0,
            "missing_rate": round(
                max(0, EXPECTED_QUERIES_PER_LLM - n) / EXPECTED_QUERIES_PER_LLM, 4
            ),
        }

    q_jpcite = round(total_jpcite / total, 4) if total else 0.0
    q_competitor = round(total_competitor / total, 4) if total else 0.0
    if q_jpcite < TIPPING_BANDS["pre_tipping"]:
        cascade_state = "pre_tipping"
    elif q_jpcite < TIPPING_BANDS["approach"]:
        cascade_state = "approach"
    else:
        cascade_state = "tipping_confirmed"

    return {
        "month": month,
        "total_samples": total,
        "expected_total": EXPECTED_TOTAL_SAMPLES,
        "missing_rate": round(max(0, EXPECTED_TOTAL_SAMPLES - total) / EXPECTED_TOTAL_SAMPLES, 4),
        "q_jpcite": q_jpcite,
        "q_competitor": q_competitor,
        "critical_q_star": CRITICAL_Q_STAR,
        "cascade_state": cascade_state,
        "per_llm": per_llm,
        "tool_version": TOOL_VERSION,
        "generated_at": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "llm_api_calls": 0,
    }


def trend_from_db(db_path: pathlib.Path, months: int = 12) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT sample_month,
                   COUNT(*) AS total_samples,
                   SUM(jpcite_cited) AS jpcite_cited,
                   SUM(competitor_cited) AS competitor_cited
              FROM citation_sample
             GROUP BY sample_month
             ORDER BY sample_month DESC
             LIMIT ?
        """,
            (months,),
        )
        out = []
        for row in cur.fetchall():
            n = row["total_samples"] or 0
            out.append(
                {
                    "month": row["sample_month"],
                    "total_samples": n,
                    "q_jpcite": round((row["jpcite_cited"] or 0) / n, 4) if n else 0.0,
                    "q_competitor": round((row["competitor_cited"] or 0) / n, 4) if n else 0.0,
                }
            )
        conn.close()
        return list(reversed(out))
    except sqlite3.Error:
        return []


def upsert_to_db(rows: list[dict[str, Any]], db_path: pathlib.Path) -> int:
    if not db_path.exists():
        return 0
    inserted = 0
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS citation_sample (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              sample_month TEXT NOT NULL,
              llm_provider TEXT NOT NULL,
              query_id TEXT NOT NULL,
              query_text TEXT NOT NULL,
              jpcite_cited INTEGER NOT NULL DEFAULT 0,
              competitor_cited INTEGER NOT NULL DEFAULT 0,
              citation_url TEXT,
              sampled_at TEXT NOT NULL,
              sampled_by TEXT NOT NULL DEFAULT 'operator'
            )
        """)
        for r in rows:
            conn.execute(
                """
                INSERT INTO citation_sample
                  (sample_month, llm_provider, query_id, query_text,
                   jpcite_cited, competitor_cited, citation_url,
                   sampled_at, sampled_by)
                VALUES (?,?,?,?,?,?,?,?,?)
            """,
                (
                    r["sample_month"],
                    r["llm_provider"],
                    r["query_id"],
                    r["query_text"],
                    r["jpcite_cited"],
                    r["competitor_cited"],
                    r["citation_url"],
                    r["sampled_at"],
                    r["sampled_by"],
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="log_citation_sample", description=__doc__.splitlines()[0])
    p.add_argument("--month", help="YYYY-MM (e.g. 2026-05)")
    p.add_argument("--csv", help="CSV input path (default = ./citation_samples_<month>.csv)")
    p.add_argument("--json-out", help="JSON output path")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="autonomath.db path")
    p.add_argument(
        "--upsert-db", action="store_true", help="UPSERT rows to autonomath.citation_sample"
    )
    p.add_argument(
        "--validate-query-set",
        action="store_true",
        help="Validate citation_query_set_100.json shape and exit",
    )
    args = p.parse_args(argv)

    if args.validate_query_set:
        qs = load_query_set()
        result = validate_query_set(qs)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0

    if not args.month:
        p.error("--month required (YYYY-MM)")

    csv_path = (
        pathlib.Path(args.csv)
        if args.csv
        else (HERE / DEFAULT_CSV_TEMPLATE.format(month=args.month))
    )
    rows = []
    if csv_path.exists():
        rows = parse_csv(csv_path)
    else:
        sys.stderr.write(f"warn: CSV not found at {csv_path}, aggregating empty.\n")

    summary = aggregate(rows, args.month)
    db_path = pathlib.Path(args.db)
    summary["trend_12mo"] = trend_from_db(db_path, months=12)

    if args.upsert_db:
        summary["db_inserted"] = upsert_to_db(rows, db_path)

    json_path = (
        pathlib.Path(args.json_out)
        if args.json_out
        else (HERE / DEFAULT_JSON_TEMPLATE.format(month=args.month))
    )
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(f"wrote {json_path}\n")
    sys.stdout.write(
        json.dumps(
            {
                "month": summary["month"],
                "q_jpcite": summary["q_jpcite"],
                "cascade_state": summary["cascade_state"],
                "total_samples": summary["total_samples"],
                "missing_rate": summary["missing_rate"],
                "llm_api_calls": summary["llm_api_calls"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
