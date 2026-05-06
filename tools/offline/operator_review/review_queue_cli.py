"""
jpcite contribution review CLI

Usage:
  python review_queue_cli.py --month 2026-06
  python review_queue_cli.py --interactive          # one-by-one approve/reject
  python review_queue_cli.py --auto-approve-trust-above 0.95  # batch auto
  python review_queue_cli.py --dry-run dry_run_data.csv       # CSV smoke

Reads contribution_queue table (autonomath.db, DEEP-28 mig 既適用),
displays pending observations with cohort + DEEP-33 trust score,
allows approve/reject with reason templates (R1-R5).

NO LLM calls. Pure SQLite + argparse + regex + stdout tables.
APPI: houjin_bangou is hashed-on-arrival, individual PII scrubbed.
aggregator URL (noukaweb 等) は client-side で reject 済、
本 CLI は server-side double-check として再検証。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DB_PATH_DEFAULT = os.environ.get(
    "JPCITE_AUTONOMATH_DB",
    "/Users/shigetoumeda/jpcite/data/autonomath.db",
)
LOG_DIR = Path(os.environ.get("JPCITE_REVIEW_LOG_DIR", "/var/log/jpcite"))

REJECT_TEMPLATES: dict[str, str] = {
    "R1": (
        "ご寄稿ありがとうございます。 1 次資料 (官公署 site) の URL を 1 つ以上 "
        "ご提示頂けますか? aggregator (noukaweb 等) は受付不可です。"
    ),
    "R2": (
        "『採択保証』『確実な税額』 等の phrase は §52 / §72 業法 fence で受付不可です。 "
        "観察事実のみ ご寄稿頂けますか?"
    ),
    "R3": (
        "個人 PII (マイナンバー / 電話番号 / email) が含まれています。 削除した上で "
        "再寄稿頂けますか? 法人番号は OK です。"
    ),
    "R4": (
        "ご寄稿の program_id が autonomath corpus に見つかりません。 "
        "autocomplete から 選択し直して頂けますか?"
    ),
    "R5": (
        "ご寄稿の値が同 cluster 寄稿と 2σ 以上離れています。 一次資料 cross-walk で "
        "再確認頂けますか?"
    ),
}

AGGREGATOR_HOSTS = (
    "noukaweb.com",
    "noukanavi",
    "matome",
    "nta-",
    "j-grants-aggregate",
)

# §52 / §72 業法 fence forbidden phrases (DEEP-38 detector mirror).
FENCE_PHRASES = (
    "採択保証",
    "確実な税額",
    "確実に採択",
    "100%採択",
    "節税保証",
    "必ず受給",
    "絶対採択",
)

# Individual PII patterns (法人番号 13 桁は OK、個人 PII のみ reject).
PII_PATTERNS = (
    re.compile(r"\b\d{12}\b"),                    # マイナンバー (12 桁)
    re.compile(r"0\d{1,4}-?\d{1,4}-?\d{4}"),      # 電話番号
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),      # email
)

COHORT_DEFAULT_TRUST = {
    "税理士": 0.92,
    "公認会計士": 0.90,
    "司法書士": 0.85,
    "補助金consultant": 0.70,
    "anonymous": 0.40,
}


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def setup_logger() -> logging.Logger:
    if LOG_DIR.parent.exists():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback below still gives stderr logging on read-only hosts.
            pass
    log_path = LOG_DIR / f"review_{datetime.now().strftime('%Y%m')}.log"
    logger = logging.getLogger("jpcite.review")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(fh)
        except (PermissionError, FileNotFoundError):
            # Fallback: stderr only when /var/log/jpcite is unavailable.
            pass
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


LOG = setup_logger()


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------

@contextmanager
def open_db(path: str) -> Iterator[sqlite3.Connection]:
    if not Path(path).exists():
        raise FileNotFoundError(
            f"autonomath.db not found at {path}. "
            f"Set JPCITE_AUTONOMATH_DB env or check DEEP-28 migration."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def fetch_pending(conn: sqlite3.Connection, month: str | None) -> list[sqlite3.Row]:
    """Pull pending contributions for the given YYYY-MM (UTC ingest date).

    Joins DEEP-33 contributor_trust to surface cohort + trust_score per row.
    """
    sql = """
        SELECT
            cq.contribution_id,
            cq.contributor_id,
            ct.cohort                          AS cohort,
            ct.trust_score                     AS trust_score,
            cq.program_id,
            cq.observed_year,
            cq.observed_eligibility_text,
            cq.source_urls,
            cq.houjin_bangou_hash,
            cq.created_at,
            cq.outlier_sigma,
            cq.status
        FROM contribution_queue cq
        LEFT JOIN contributor_trust ct ON ct.contributor_id = cq.contributor_id
        WHERE cq.status = 'pending'
    """
    params: list[Any] = []
    if month:
        sql += " AND substr(cq.created_at, 1, 7) = ?"
        params.append(month)
    sql += " ORDER BY ct.trust_score DESC NULLS LAST, cq.created_at ASC"
    return list(conn.execute(sql, params))


def update_status(
    conn: sqlite3.Connection,
    contribution_id: str,
    new_status: str,
    reviewer_notes: str | None = None,
    quality_flag: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE contribution_queue
           SET status = ?,
               reviewer_notes = COALESCE(?, reviewer_notes),
               reviewed_at = ?
         WHERE contribution_id = ?
        """,
        (new_status, reviewer_notes, datetime.utcnow().isoformat(timespec="seconds"), contribution_id),
    )
    if quality_flag and new_status == "approved":
        # Promote linked am_amount_condition row(s) to community_verified.
        conn.execute(
            """
            UPDATE am_amount_condition
               SET quality_flag = ?
             WHERE source_contribution_id = ?
            """,
            (quality_flag, contribution_id),
        )
    conn.commit()


# --------------------------------------------------------------------------
# Validators (LLM-free, regex + rule)
# --------------------------------------------------------------------------

def detect_aggregator(urls: str | None) -> bool:
    if not urls:
        return False
    blob = urls.lower()
    return any(host in blob for host in AGGREGATOR_HOSTS)


def detect_fence_violation(text: str | None) -> str | None:
    if not text:
        return None
    for phrase in FENCE_PHRASES:
        if phrase in text:
            return phrase
    return None


def detect_individual_pii(text: str | None) -> str | None:
    if not text:
        return None
    for pat in PII_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def auto_decision(row: dict[str, Any], auto_threshold: float) -> tuple[str | None, str | None]:
    """Return (decision, reason_code) for fully-mechanical rules.

    decision in {"approve", "reject", None}; None = needs human review.
    """
    # Reject: aggregator URL (server-side double check after DEEP-31 client-side).
    if detect_aggregator(row.get("source_urls")):
        return "reject", "R1"
    # Reject: §52 / §72 fence violation.
    if detect_fence_violation(row.get("observed_eligibility_text")):
        return "reject", "R2"
    # Reject: individual PII detected.
    if detect_individual_pii(row.get("observed_eligibility_text")):
        return "reject", "R3"
    # Reject: outlier (DEEP-33 sigma already populated upstream).
    sigma = row.get("outlier_sigma")
    if sigma is not None and float(sigma) > 2.0:
        return "reject", "R5"
    # Approve: high-trust 税理士 cohort over auto threshold.
    cohort = (row.get("cohort") or "").strip()
    trust = row.get("trust_score")
    if (
        cohort == "税理士"
        and trust is not None
        and float(trust) >= auto_threshold
    ):
        return "approve", None
    return None, None


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------

def _ascii_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    widths = {c: max(len(c), max((len(str(r.get(c, ""))) for r in rows), default=0)) for c in cols}
    sep = "+" + "+".join("-" * (widths[c] + 2) for c in cols) + "+"
    lines = [sep]
    lines.append("| " + " | ".join(c.ljust(widths[c]) for c in cols) + " |")
    lines.append(sep)
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols) + " |")
    lines.append(sep)
    return "\n".join(lines)


def render_summary(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> str:
    items = [dict(r) for r in rows]
    if not items:
        return "(no pending contributions)"
    cols = ["contribution_id", "cohort", "trust_score", "program_id", "observed_year"]
    short = [{c: r.get(c) for c in cols} for r in items]
    return _ascii_table(short, cols)


def render_one(row: dict[str, Any]) -> str:
    fields = [
        "contribution_id",
        "contributor_id",
        "cohort",
        "trust_score",
        "program_id",
        "observed_year",
        "observed_eligibility_text",
        "source_urls",
        "houjin_bangou_hash",
        "outlier_sigma",
    ]
    lines = ["-" * 60]
    for f in fields:
        lines.append(f"  {f:30s}: {row.get(f)}")
    lines.append("-" * 60)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Interactive loop
# --------------------------------------------------------------------------

def interactive(conn: sqlite3.Connection, rows: list[dict[str, Any]], auto_threshold: float) -> dict[str, int]:
    counts = {"approved": 0, "rejected": 0, "skipped": 0, "auto_approved": 0, "auto_rejected": 0}
    for idx, row in enumerate(rows, 1):
        decision, code = auto_decision(row, auto_threshold)
        if decision == "approve":
            update_status(conn, row["contribution_id"], "approved", reviewer_notes="auto:trust>=threshold",
                          quality_flag="community_verified")
            LOG.info("auto_approved %s cohort=%s trust=%s", row["contribution_id"], row.get("cohort"), row.get("trust_score"))
            counts["auto_approved"] += 1
            continue
        if decision == "reject":
            note = f"auto_reject:{code}:{REJECT_TEMPLATES[code]}"
            update_status(conn, row["contribution_id"], "rejected", reviewer_notes=note)
            LOG.info("auto_rejected %s code=%s", row["contribution_id"], code)
            counts["auto_rejected"] += 1
            continue

        print(f"\n[{idx}/{len(rows)}]")
        print(render_one(row))
        choice = input("  [a]pprove / [r]eject / [s]kip / [q]uit > ").strip().lower()
        if choice == "q":
            print("quit requested; remaining items left as pending.")
            break
        if choice == "s":
            counts["skipped"] += 1
            continue
        if choice == "a":
            update_status(conn, row["contribution_id"], "approved",
                          reviewer_notes="manual:approved",
                          quality_flag="community_verified")
            LOG.info("approved %s", row["contribution_id"])
            counts["approved"] += 1
            continue
        if choice == "r":
            print("  reject reason templates:")
            for k, v in REJECT_TEMPLATES.items():
                print(f"    {k}: {v[:60]}{'...' if len(v) > 60 else ''}")
            code = input("  pick R1-R5 > ").strip().upper()
            if code not in REJECT_TEMPLATES:
                print("  invalid code; skipping.")
                counts["skipped"] += 1
                continue
            update_status(conn, row["contribution_id"], "rejected",
                          reviewer_notes=f"manual:{code}:{REJECT_TEMPLATES[code]}")
            LOG.info("rejected %s code=%s", row["contribution_id"], code)
            counts["rejected"] += 1
            continue
        print("  unrecognized; skipping.")
        counts["skipped"] += 1
    return counts


# --------------------------------------------------------------------------
# Dry-run from CSV (no DB writes)
# --------------------------------------------------------------------------

def dry_run(csv_path: str, auto_threshold: float) -> None:
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
    print(f"loaded {len(rows)} rows from {csv_path} (no DB writes)")
    print(render_summary(rows))
    auto_a = auto_r = manual = 0
    for r in rows:
        # Coerce numeric fields parsed from CSV strings.
        if r.get("trust_score") not in (None, ""):
            try:
                r["trust_score"] = float(r["trust_score"])
            except ValueError:
                pass
        if r.get("outlier_sigma") not in (None, ""):
            try:
                r["outlier_sigma"] = float(r["outlier_sigma"])
            except ValueError:
                pass
        decision, code = auto_decision(r, auto_threshold)
        if decision == "approve":
            auto_a += 1
        elif decision == "reject":
            auto_r += 1
            print(f"  would reject {r.get('contribution_id')} code={code}")
        else:
            manual += 1
    print(f"dry-run summary: auto_approve={auto_a} auto_reject={auto_r} needs_manual={manual}")


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="jpcite contribution review CLI (LLM-free)")
    p.add_argument("--month", help="filter by created_at YYYY-MM (default: all pending)")
    p.add_argument("--interactive", action="store_true", help="one-by-one prompt mode")
    p.add_argument(
        "--auto-approve-trust-above",
        type=float,
        default=0.95,
        help="cohort=税理士 with trust_score >= this is auto-approved (default 0.95)",
    )
    p.add_argument("--db", default=DB_PATH_DEFAULT, help="autonomath.db path")
    p.add_argument("--dry-run", help="path to mock CSV; reads only, no DB writes")
    p.add_argument("--summary-only", action="store_true", help="print pending summary then exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        dry_run(args.dry_run, args.auto_approve_trust_above)
        return 0
    try:
        with open_db(args.db) as conn:
            rows = [dict(r) for r in fetch_pending(conn, args.month)]
            print(f"pending: {len(rows)} rows (month={args.month or 'all'})")
            print(render_summary(rows))
            if args.summary_only or not rows:
                return 0
            if args.interactive:
                counts = interactive(conn, rows, args.auto_approve_trust_above)
            else:
                # batch mode: only auto rules fire; rest stay pending.
                counts = {"approved": 0, "rejected": 0, "skipped": 0, "auto_approved": 0, "auto_rejected": 0}
                for row in rows:
                    decision, code = auto_decision(row, args.auto_approve_trust_above)
                    if decision == "approve":
                        update_status(conn, row["contribution_id"], "approved",
                                      reviewer_notes="auto:trust>=threshold",
                                      quality_flag="community_verified")
                        counts["auto_approved"] += 1
                    elif decision == "reject":
                        note = f"auto_reject:{code}:{REJECT_TEMPLATES[code]}"
                        update_status(conn, row["contribution_id"], "rejected", reviewer_notes=note)
                        counts["auto_rejected"] += 1
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            LOG.info("session counts %s", counts)
        return 0
    except FileNotFoundError as e:
        LOG.error("%s", e)
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as e:
        LOG.error("sqlite error: %s", e)
        print(
            "ERROR: contribution_queue / contributor_trust テーブル未確認。 "
            "DEEP-28 migration (mig_028_contribution_queue.sql) と "
            "DEEP-33 migration (mig_033_contributor_trust.sql) の適用を確認してください。",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
