"""AA1-G1 — ingest NTA 質疑応答 / 文書回答 into `am_nta_qa` (2026-05-17).

The DB-level INSERT loader for the G1 NTA QA expansion. Reads raw HTML
or already-parsed JSONL records from one of:

  1. Direct fetch via the manifest endpoints
     (https://www.nta.go.jp/law/shitsugi/{category}/, /law/bunshokaito/).
  2. Pre-staged JSONL produced by the orchestrator
     (`crawl_nta_corpus_2026_05_17.py`) — useful when an operator wants
     a verifiable plan-test/replay loop.

INSERT contract is ``INSERT OR IGNORE`` against UNIQUE(source_url) AND
UNIQUE(qa_kind, tax_category, slug) on table ``am_nta_qa``
(migration wave24_212).

Constraints
-----------
* NO LLM. HTML parsing only.
* Aggregator hosts rejected pre-INSERT (allowlist check).
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

logger = logging.getLogger("jpcite.etl.g1_nta_qa_ingest")

DEFAULT_DB_PATH: Final = Path("autonomath.db")
DEFAULT_CRAWL_RUN_ID: Final = "etl_g1_nta_manifest_2026_05_17"

PRIMARY_HOST_REGEX: Final = re.compile(r"^https?://(?:[a-z0-9-]+\.)*nta\.go\.jp(?:/|$|\?|#)")

AGGREGATOR_HOST_BLACKLIST: Final[tuple[str, ...]] = (
    "zeiken.jp",
    "tabisland.ne.jp",
    "kaikei-station.com",
)

CANONICAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"hojin", "shohi", "sozoku", "hyoka", "inshi", "hotei", "joto", "shotoku", "gensen"}
)


@dataclass(slots=True)
class QaRecord:
    """One row destined for am_nta_qa."""

    qa_kind: str
    tax_category: str
    slug: str
    question: str
    answer: str
    related_law: str | None
    decision_date: str | None
    source_url: str
    license: str = "pdl_v1.0"
    crawl_run_id: str = DEFAULT_CRAWL_RUN_ID


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_primary(url: str) -> bool:
    if PRIMARY_HOST_REGEX.match(url) is None:
        return False
    return all(black not in url for black in AGGREGATOR_HOST_BLACKLIST)


def _normalize_category(raw: str) -> str | None:
    norm = raw.strip().lower()
    if norm in CANONICAL_CATEGORIES:
        return norm
    # legacy slug aliases
    alias_map = {
        "shotoku-zei": "shotoku",
        "hojin-zei": "hojin",
        "shohi-zei": "shohi",
        "sozoku-zei": "sozoku",
    }
    return alias_map.get(norm)


def _load_jsonl_records(path: Path) -> Iterable[QaRecord]:
    """Stream QaRecord rows from a pre-staged JSONL file."""
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
            category = _normalize_category(str(obj.get("tax_category", "")))
            if category is None:
                continue
            qa_kind = str(obj.get("qa_kind", "shitsugi"))
            if qa_kind not in ("shitsugi", "bunsho"):
                continue
            source_url = str(obj.get("source_url", "")).strip()
            if not source_url or not _is_primary(source_url):
                continue
            yield QaRecord(
                qa_kind=qa_kind,
                tax_category=category,
                slug=str(obj.get("slug", "")),
                question=str(obj.get("question", "")),
                answer=str(obj.get("answer", "")),
                related_law=(
                    str(obj["related_law"]) if obj.get("related_law") is not None else None
                ),
                decision_date=(
                    str(obj["decision_date"]) if obj.get("decision_date") is not None else None
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
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_nta_qa'"
    ).fetchone()
    return row is not None


def _insert_batch(
    conn: sqlite3.Connection,
    records: list[QaRecord],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    if dry_run:
        for rec in records:
            if not _is_primary(rec.source_url):
                skipped += 1
                continue
            inserted += 1
        return inserted, skipped
    cur = conn.cursor()
    for rec in records:
        if not _is_primary(rec.source_url):
            skipped += 1
            continue
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO am_nta_qa (
                    qa_kind, tax_category, slug, question, answer,
                    related_law, decision_date, source_url,
                    license, crawl_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.qa_kind,
                    rec.tax_category,
                    rec.slug,
                    rec.question,
                    rec.answer,
                    rec.related_law,
                    rec.decision_date,
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
    parser.add_argument(
        "--jsonl-input",
        type=Path,
        default=None,
        help="Pre-staged JSONL produced by crawl_nta_corpus_2026_05_17.py",
    )
    parser.add_argument(
        "--category",
        default="all",
        help="Filter by tax_category (hojin, shohi, ...) or 'all'",
    )
    parser.add_argument(
        "--crawl-run-id",
        default=DEFAULT_CRAWL_RUN_ID,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--commit",
        action="store_false",
        dest="dry_run",
    )
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
            "no --jsonl-input given; emit-only plan mode. "
            "Run crawl_nta_corpus_2026_05_17.py first to produce JSONL."
        )
        return 0
    conn = _connect(args.db)
    try:
        if not _ensure_table_exists(conn):
            logger.error(
                "am_nta_qa table not present in %s — apply migration "
                "wave24_212_am_nta_qa.sql first",
                args.db,
            )
            return 2
        wanted_category = args.category.strip().lower()
        records: list[QaRecord] = []
        for rec in _load_jsonl_records(args.jsonl_input):
            if wanted_category != "all" and rec.tax_category != wanted_category:
                continue
            rec.crawl_run_id = args.crawl_run_id
            records.append(rec)
        inserted, skipped = _insert_batch(conn, records, dry_run=args.dry_run)
        logger.info(
            "inserted=%d skipped=%d total=%d dry_run=%s",
            inserted,
            skipped,
            len(records),
            args.dry_run,
        )
        summary = {
            "generated_at_utc": _utc_now_iso(),
            "input_jsonl": str(args.jsonl_input),
            "category_filter": wanted_category,
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
