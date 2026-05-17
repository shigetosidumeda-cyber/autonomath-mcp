"""AA1-G1 — ingest 地方税 個別通達 across 47 都道府県 (2026-05-17).

INSERT-side loader for ``am_chihouzei_tsutatsu`` (migration wave24_213).

Source pattern
--------------
Each prefecture publishes 通達 / 取扱基準 / 告示 on its official
``pref.{romaji}.lg.jp`` (or ``metro.tokyo.lg.jp`` for Tokyo) website
under a 税務 / 都税 directory. The orchestrator
``crawl_nta_corpus_2026_05_17.py --gap g10_chihouzei_47pref`` walks the
allowlist; this loader does the DB-side INSERT OR IGNORE on the JSONL it
emits.

Constraints
-----------
* NO LLM. Pure HTML parsing.
* Allowlist enforced pre-INSERT (pref.*.lg.jp + metro.tokyo.lg.jp +
  city.*.lg.jp only).
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

logger = logging.getLogger("jpcite.etl.g1_chihouzei_ingest")

DEFAULT_DB_PATH: Final = Path("autonomath.db")
DEFAULT_CRAWL_RUN_ID: Final = "etl_g1_nta_manifest_2026_05_17"

PRIMARY_HOST_REGEX: Final = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:pref\.[a-z-]+\.lg\.jp|"
    r"pref\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.jp|"
    r"metro\.tokyo\.lg\.jp)(?:/|$|\?|#)"
)

CANONICAL_TAX_KINDS: Final[frozenset[str]] = frozenset(
    {
        "kojin_juminzei",
        "hojin_juminzei",
        "jigyozei",
        "kotei_shisanzei",
        "fudosan_shutokuzei",
        "jidoshazei",
        "kei_jidoshazei",
        "kenmin_zei",
        "shimin_zei",
        "tabako_zei",
        "gorufujozei",
        "kankyo_zei",
        "sonota_chihouzei",
    }
)

CANONICAL_PREFECTURES: Final[dict[str, str]] = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "05": "秋田県",
    "06": "山形県",
    "07": "福島県",
    "08": "茨城県",
    "09": "栃木県",
    "10": "群馬県",
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
    "15": "新潟県",
    "16": "富山県",
    "17": "石川県",
    "18": "福井県",
    "19": "山梨県",
    "20": "長野県",
    "21": "岐阜県",
    "22": "静岡県",
    "23": "愛知県",
    "24": "三重県",
    "25": "滋賀県",
    "26": "京都府",
    "27": "大阪府",
    "28": "兵庫県",
    "29": "奈良県",
    "30": "和歌山県",
    "31": "鳥取県",
    "32": "島根県",
    "33": "岡山県",
    "34": "広島県",
    "35": "山口県",
    "36": "徳島県",
    "37": "香川県",
    "38": "愛媛県",
    "39": "高知県",
    "40": "福岡県",
    "41": "佐賀県",
    "42": "長崎県",
    "43": "熊本県",
    "44": "大分県",
    "45": "宮崎県",
    "46": "鹿児島県",
    "47": "沖縄県",
}


@dataclass(slots=True)
class ChihouzeiRecord:
    prefecture_code: str
    prefecture_name: str
    tax_kind: str
    tsutatsu_no: str | None
    title: str
    body_excerpt: str | None
    effective_from: str | None
    effective_to: str | None
    source_url: str
    license: str = "gov_standard"
    crawl_run_id: str = DEFAULT_CRAWL_RUN_ID


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_primary(url: str) -> bool:
    return PRIMARY_HOST_REGEX.match(url) is not None


def _load_jsonl(path: Path) -> Iterable[ChihouzeiRecord]:
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
            pref_code = str(obj.get("prefecture_code", "")).strip().zfill(2)
            if pref_code not in CANONICAL_PREFECTURES:
                continue
            tax_kind = str(obj.get("tax_kind", "")).strip().lower()
            if tax_kind not in CANONICAL_TAX_KINDS:
                continue
            source_url = str(obj.get("source_url", "")).strip()
            if not source_url or not _is_primary(source_url):
                continue
            title = str(obj.get("title", "")).strip()
            if not title:
                continue
            yield ChihouzeiRecord(
                prefecture_code=pref_code,
                prefecture_name=CANONICAL_PREFECTURES[pref_code],
                tax_kind=tax_kind,
                tsutatsu_no=(
                    str(obj["tsutatsu_no"]) if obj.get("tsutatsu_no") is not None else None
                ),
                title=title,
                body_excerpt=(
                    str(obj["body_excerpt"]) if obj.get("body_excerpt") is not None else None
                ),
                effective_from=(
                    str(obj["effective_from"]) if obj.get("effective_from") is not None else None
                ),
                effective_to=(
                    str(obj["effective_to"]) if obj.get("effective_to") is not None else None
                ),
                source_url=source_url,
                license=str(obj.get("license", "gov_standard")),
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
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_chihouzei_tsutatsu'"
    ).fetchone()
    return row is not None


def _insert_batch(
    conn: sqlite3.Connection,
    records: list[ChihouzeiRecord],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    if dry_run:
        return len(records), 0
    cur = conn.cursor()
    for rec in records:
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO am_chihouzei_tsutatsu (
                    prefecture_code, prefecture_name, tax_kind,
                    tsutatsu_no, title, body_excerpt,
                    effective_from, effective_to,
                    source_url, license, crawl_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.prefecture_code,
                    rec.prefecture_name,
                    rec.tax_kind,
                    rec.tsutatsu_no,
                    rec.title,
                    rec.body_excerpt,
                    rec.effective_from,
                    rec.effective_to,
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
        "--prefecture-code",
        default="all",
        help="JIS X 0401 2-digit code (01..47) or 'all'",
    )
    parser.add_argument(
        "--all-prefectures",
        action="store_true",
        help="Convenience flag = --prefecture-code all",
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
    pref_filter = "all" if args.all_prefectures else args.prefecture_code
    if args.jsonl_input is None:
        logger.info(
            "no --jsonl-input given; plan-only. Run "
            "crawl_nta_corpus_2026_05_17.py --gap g10_chihouzei_47pref first."
        )
        return 0
    conn = _connect(args.db)
    try:
        if not _ensure_table_exists(conn):
            logger.error("am_chihouzei_tsutatsu not present — apply migration wave24_213 first")
            return 2
        records: list[ChihouzeiRecord] = []
        for rec in _load_jsonl(args.jsonl_input):
            if pref_filter != "all" and rec.prefecture_code != pref_filter:
                continue
            rec.crawl_run_id = args.crawl_run_id
            records.append(rec)
        inserted, skipped = _insert_batch(conn, records, dry_run=args.dry_run)
        summary = {
            "generated_at_utc": _utc_now_iso(),
            "input_jsonl": str(args.jsonl_input),
            "prefecture_filter": pref_filter,
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
