"""AA1-G1 — ingest 税制改正履歴 into `am_tax_amendment_history` (2026-05-17).

INSERT-side loader for ``am_tax_amendment_history`` (migration wave24_214).

Source pattern
--------------
* 国税庁 "税制改正の概要" : https://www.nta.go.jp/law/joho-zeikaishaku/
* 財務省 公表 大綱        : https://www.mof.go.jp/tax_policy/tax_reform/
* 政令 + 省令 chain       : (linked from 国税庁 大綱 page)

Constraints
-----------
* NO LLM. Pure HTML parsing.
* Allowlist: nta.go.jp + mof.go.jp.
* DRY_RUN default. ``--commit`` lifts.
* mypy --strict clean.
* ``[lane:solo]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("jpcite.etl.g1_amendment_ingest")

DEFAULT_DB_PATH: Final = Path("autonomath.db")
DEFAULT_CRAWL_RUN_ID: Final = "etl_g1_nta_manifest_2026_05_17"

PRIMARY_HOST_REGEX: Final = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*(?:nta\.go\.jp|mof\.go\.jp)(?:/|$|\?|#)"
)

CANONICAL_TAX_KINDS: Final[frozenset[str]] = frozenset(
    {"hojin", "shotoku", "shohi", "sozoku", "gensen", "hyoka", "inshi", "hotei", "joto", "sonota"}
)
CANONICAL_STATUTE_KINDS: Final[frozenset[str]] = frozenset(
    {"tax_law", "enforcement_order", "enforcement_regulation", "tsutatsu", "gaiyou"}
)


@dataclass(slots=True)
class AmendmentRecord:
    fiscal_year: int
    tax_kind: str
    amendment_title: str
    amendment_summary: str
    effective_from: str | None
    effective_to: str | None
    statute_kind: str
    statute_ref: str | None
    gazette_ref: str | None
    source_url: str
    license: str = "pdl_v1.0"
    crawl_run_id: str = DEFAULT_CRAWL_RUN_ID


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_primary(url: str) -> bool:
    return PRIMARY_HOST_REGEX.match(url) is not None


def _load_jsonl(path: Path) -> Iterable[AmendmentRecord]:
    if not path.exists():
        raise SystemExit(f"jsonl input not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("jsonl parse error line %d: %s", line_no, exc)
                continue
            if not isinstance(obj, dict):
                continue
            try:
                fiscal_year = int(obj.get("fiscal_year", 0))
            except (TypeError, ValueError):
                continue
            if not 1989 <= fiscal_year <= 2100:
                continue
            tax_kind = str(obj.get("tax_kind", "")).strip().lower()
            if tax_kind not in CANONICAL_TAX_KINDS:
                continue
            statute_kind = str(obj.get("statute_kind", "")).strip().lower()
            if statute_kind not in CANONICAL_STATUTE_KINDS:
                continue
            source_url = str(obj.get("source_url", "")).strip()
            if not source_url or not _is_primary(source_url):
                continue
            title = str(obj.get("amendment_title", "")).strip()
            summary = str(obj.get("amendment_summary", "")).strip()
            if not title or not summary:
                continue
            yield AmendmentRecord(
                fiscal_year=fiscal_year,
                tax_kind=tax_kind,
                amendment_title=title,
                amendment_summary=summary,
                effective_from=(
                    str(obj["effective_from"]) if obj.get("effective_from") is not None else None
                ),
                effective_to=(
                    str(obj["effective_to"]) if obj.get("effective_to") is not None else None
                ),
                statute_kind=statute_kind,
                statute_ref=(
                    str(obj["statute_ref"]) if obj.get("statute_ref") is not None else None
                ),
                gazette_ref=(
                    str(obj["gazette_ref"]) if obj.get("gazette_ref") is not None else None
                ),
                source_url=source_url,
                license=str(obj.get("license", "pdl_v1.0")),
                crawl_run_id=str(obj.get("crawl_run_id", DEFAULT_CRAWL_RUN_ID)),
            )


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_tax_amendment_history'"
    ).fetchone()
    return row is not None


def _insert_batch(
    conn: sqlite3.Connection,
    records: list[AmendmentRecord],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    if dry_run:
        return len(records), 0
    inserted = 0
    skipped = 0
    cur = conn.cursor()
    for rec in records:
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO am_tax_amendment_history (
                    fiscal_year, tax_kind, amendment_title, amendment_summary,
                    effective_from, effective_to,
                    statute_kind, statute_ref, gazette_ref,
                    source_url, license, crawl_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.fiscal_year,
                    rec.tax_kind,
                    rec.amendment_title,
                    rec.amendment_summary,
                    rec.effective_from,
                    rec.effective_to,
                    rec.statute_kind,
                    rec.statute_ref,
                    rec.gazette_ref,
                    rec.source_url,
                    rec.license,
                    rec.crawl_run_id,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.IntegrityError as exc:
            logger.warning("integrity error on %s: %s", rec.source_url, exc)
            skipped += 1
    conn.commit()
    return inserted, skipped


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--jsonl-input", type=Path, default=None)
    parser.add_argument(
        "--fy-from",
        type=int,
        default=1995,
        help="Earliest fiscal year to ingest (inclusive)",
    )
    parser.add_argument(
        "--fy-to",
        type=int,
        default=2026,
        help="Latest fiscal year (inclusive)",
    )
    parser.add_argument("--crawl-run-id", default=DEFAULT_CRAWL_RUN_ID)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--commit", action="store_false", dest="dry_run")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s :: %(message)s",
    )
    if args.jsonl_input is None:
        logger.info(
            "no --jsonl-input given; plan-only. Run "
            "crawl_nta_corpus_2026_05_17.py --gap g8_tax_amendment_history first."
        )
        return 0
    if args.fy_from > args.fy_to:
        logger.error("fy_from > fy_to")
        return 2
    conn = _connect(args.db)
    try:
        if not _ensure_table_exists(conn):
            logger.error("am_tax_amendment_history not present — apply migration wave24_214 first")
            return 2
        records: list[AmendmentRecord] = []
        for rec in _load_jsonl(args.jsonl_input):
            if not args.fy_from <= rec.fiscal_year <= args.fy_to:
                continue
            rec.crawl_run_id = args.crawl_run_id
            records.append(rec)
        inserted, skipped = _insert_batch(conn, records, dry_run=args.dry_run)
        summary = {
            "generated_at_utc": _utc_now_iso(),
            "input_jsonl": str(args.jsonl_input),
            "fy_window": [args.fy_from, args.fy_to],
            "inserted": inserted,
            "skipped": skipped,
            "total_candidates": len(records),
            "dry_run": args.dry_run,
            "crawl_run_id": args.crawl_run_id,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
