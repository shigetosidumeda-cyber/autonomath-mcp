#!/usr/bin/env python3
"""PoC adoption ingest for 事業再構築補助金 (jigyou-saikouchiku.go.jp).

Goal (per docs/POST_DEPLOY_PLAN_W5_W8.md §W5-W6):
    Prove end-to-end that public adoption PDFs can be fetched, parsed into
    uniform dicts, and best-effort matched against our existing programs
    table. Output is JSONL under data/ -- NOT merged into jpintel.db until
    schema is reviewed (stub migration: scripts/migrations/006_adoption.sql.draft).

Scope:
    - Rounds 8-13 of 事業再構築補助金 (whole-country consolidated PDF per round).
    - Source: https://jigyou-saikouchiku.go.jp/result.html (parsed for href).
    - Cache: /tmp/jpintel_adoption_cache/ (never committed).
    - Output: data/adoption_jigyou_saikouchiku.jsonl (idempotent overwrite).

Constraints (session-memory gate flags):
    - 1 req/sec max, single-threaded; retry on 5xx with exponential back-off.
    - Respects robots.txt (ia_archiver etc. only -- generic UA allowed).
    - PDF-text, not scan -- no OCR required for this source.

Usage:
    python3 scripts/ingest/poc_adoption_jigyou_saikouchiku.py
    python3 scripts/ingest/poc_adoption_jigyou_saikouchiku.py --rounds 13
    python3 scripts/ingest/poc_adoption_jigyou_saikouchiku.py --no-match

Exit codes:
    0  success
    1  unrecoverable fetch failure
    2  parse failure on >20% of pages (column drift beyond this parser)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    import httpx  # type: ignore
    import pdfplumber  # type: ignore
except ImportError as exc:
    print(f"missing dep: {exc}. pip install httpx pdfplumber", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = Path("/tmp/jpintel_adoption_cache")
DB_PATH = DATA_DIR / "jpintel.db"
OUT_PATH = DATA_DIR / "adoption_jigyou_saikouchiku.jsonl"

SOURCE_INDEX_URL = "https://jigyou-saikouchiku.go.jp/result.html"
PDF_URL_TEMPLATE = "https://jigyou-saikouchiku.go.jp/pdf/result/tokubetsu_all{pad}.pdf"
USER_AGENT = "jpintel-mcp PoC (contact: sss@bookyou.net)"
RATE_LIMIT_SECONDS = 1.0
HTTP_TIMEOUT = 90
MAX_RETRIES = 3

# 事業再構築補助金 is a nation-wide, cross-industry program; its unified_id is
# not yet in the DB (agri niche only), so the program-level FK can stay null.
# PoC picks a sentinel for the 事業 to allow later bulk UPDATE when the
# program-to-unified_id is registered.
PROGRAM_UNIFIED_ID_SENTINEL = "UNI-PENDING-jigyou-saikouchiku"


@dataclass
class AdoptionRecord:
    """Uniform output shape per requirement spec.

    Extra fields beyond the minimum (industry, corporate_number, frame,
    support_org) are kept because they cost nothing extra to emit but are
    meaningful for find_similar later. source_checksum is per-source-PDF
    (not per-record) so re-runs can skip untouched PDFs.
    """

    program_unified_id: str | None
    fiscal_year: int | None
    round: str
    recipient_name: str
    recipient_prefecture: str | None
    recipient_municipality: str | None
    corporate_number: str | None
    industry_category: str | None
    project_title: str | None
    support_org: str | None
    amount_yen: int | None  # 事業再構築 round PDFs do NOT publish amount
    source_url: str
    source_fetched_at: str
    source_checksum: str
    row_hash: str  # sha1 for idempotency


def polite_get(url: str, tries: int = MAX_RETRIES) -> bytes:
    """Single-threaded, rate-limited GET with back-off. No concurrency."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, tries + 1):
        try:
            with httpx.Client(
                http2=False, follow_redirects=True, timeout=HTTP_TIMEOUT
            ) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.content
                time.sleep(RATE_LIMIT_SECONDS)
                return body
        except Exception as exc:  # noqa: BLE001
            if attempt == tries:
                raise
            wait = 2**attempt
            print(f"   retry {attempt}/{tries} after {wait}s ({exc})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def discover_round_urls() -> dict[str, str]:
    """Parse the index page to find all tokubetsu_all<N>.pdf hrefs.

    Handles zero-pad drift (rounds 8-9 use 08/09; 10+ raw digits).
    """
    html = polite_get(SOURCE_INDEX_URL).decode("utf-8", errors="replace")
    hrefs = re.findall(r'href="(/pdf/result/tokubetsu_all(\d+)\.pdf)"', html)
    seen: dict[str, str] = {}
    for path, pad in hrefs:
        round_num = str(int(pad))  # "08" -> "8"
        if round_num in seen:
            continue  # first hit wins
        seen[round_num] = "https://jigyou-saikouchiku.go.jp" + path
    return seen


def fetch_pdf(url: str) -> tuple[Path, str]:
    """Download (or reuse cache), return (local_path, sha256)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = url.rsplit("/", 1)[-1]
    local = CACHE_DIR / fname
    if local.exists() and local.stat().st_size > 50_000:
        body = local.read_bytes()
    else:
        body = polite_get(url)
        local.write_bytes(body)
    checksum = hashlib.sha256(body).hexdigest()
    return local, checksum


RECO_HEADER_FIRST_COL = "エリア"


def parse_round_pdf(
    pdf_path: Path,
    round_label: str,
    source_url: str,
    checksum: str,
) -> tuple[list[AdoptionRecord], dict[str, int]]:
    """Parse one per-round PDF into records.

    Rounds 8-10 use 9-column layout (no 主たる業種).
    Rounds 11-13 use 10-column layout.
    Header detection is structural (first cell == 'エリア').
    """
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    records: list[AdoptionRecord] = []
    stats = {"pages": 0, "pages_clean": 0, "pages_dirty": 0, "rows_emitted": 0}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            stats["pages"] += 1
            tables = page.extract_tables()
            if not tables:
                stats["pages_dirty"] += 1
                continue
            table = tables[0]
            if not table or not table[0]:
                stats["pages_dirty"] += 1
                continue
            header = [(c or "").strip() for c in table[0]]
            if header[0] != RECO_HEADER_FIRST_COL:
                stats["pages_dirty"] += 1
                continue
            # Map header names to indices.
            idx = {name: i for i, name in enumerate(header)}
            has_industry = "主たる業種（大分類）" in idx

            def g(row: list[str | None], key: str, _idx: dict[str, int] = idx) -> str | None:
                i = _idx.get(key)
                if i is None or i >= len(row):
                    return None
                v = (row[i] or "").strip()
                return v or None

            stats["pages_clean"] += 1
            for row in table[1:]:
                if not row or not any(row):
                    continue
                recipient_name = g(row, "事業者名")
                if not recipient_name:
                    continue  # blank continuation row, skip
                rec = AdoptionRecord(
                    program_unified_id=PROGRAM_UNIFIED_ID_SENTINEL,
                    fiscal_year=None,  # 事業再構築 rounds cross fiscal years -- left null
                    round=round_label,
                    recipient_name=recipient_name,
                    recipient_prefecture=g(row, "都道府県"),
                    recipient_municipality=g(row, "市区町村"),
                    corporate_number=g(row, "法人番号"),
                    industry_category=g(row, "主たる業種（大分類）") if has_industry else None,
                    project_title=g(row, "事業計画名"),
                    support_org=g(row, "認定支援機関名"),
                    amount_yen=None,  # not published in per-round PDF
                    source_url=source_url,
                    source_fetched_at=fetched_at,
                    source_checksum=checksum,
                    row_hash="",  # filled below
                )
                rec.row_hash = hashlib.sha1(
                    (
                        (rec.program_unified_id or "")
                        + "|"
                        + rec.round
                        + "|"
                        + rec.recipient_name
                        + "|"
                        + (rec.project_title or "")
                    ).encode("utf-8")
                ).hexdigest()
                records.append(rec)
                stats["rows_emitted"] += 1
    return records, stats


# ---------------------------------------------------------------------------
# Program name matching
# ---------------------------------------------------------------------------


def load_match_candidates(db_path: Path) -> list[tuple[str, str]]:
    """Return (unified_id, primary_name) rows from programs for ILIKE match."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT unified_id, primary_name FROM programs WHERE excluded = 0"
        )
        return list(cur.fetchall())
    finally:
        conn.close()


def match_program_for(
    recipient_name: str, candidates: list[tuple[str, str]]
) -> str | None:
    """Best-effort: 事業再構築補助金 has no unified_id yet in the registry.

    Left as a stub that always returns None. Kept so the pipeline shape is
    validated; when real per-authority data arrives we will ILIKE against
    primary_name / aliases. Emitting None here is intentional: it means the
    FK stays null and the sentinel unified_id propagates.
    """
    _ = (recipient_name, candidates)
    return None


# ---------------------------------------------------------------------------
# Output (idempotent)
# ---------------------------------------------------------------------------


def write_jsonl(records: list[AdoptionRecord], out_path: Path) -> None:
    """Idempotent write: de-dupe by row_hash and replace output atomically.

    Re-runs are safe because (a) PDFs are cached, (b) row_hash is deterministic,
    (c) output is rewritten from scratch rather than appended.
    """
    seen: set[str] = set()
    unique: list[AdoptionRecord] = []
    for r in records:
        if r.row_hash in seen:
            continue
        seen.add(r.row_hash)
        unique.append(r)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in unique:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    tmp.replace(out_path)
    print(f"   wrote {len(unique)} records to {out_path} (deduped {len(records) - len(unique)})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rounds",
        type=str,
        default="all",
        help="comma-separated round numbers (e.g. '8,13'); default 'all'",
    )
    ap.add_argument(
        "--no-match",
        action="store_true",
        help="skip program-name match step (kept for parity; match is stubbed)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help=f"output JSONL path (default {OUT_PATH})",
    )
    args = ap.parse_args()

    t0 = time.monotonic()
    print(f"[1/4] discovering round URLs from {SOURCE_INDEX_URL}")
    round_urls = discover_round_urls()
    print(f"   found {len(round_urls)} rounds: {sorted(round_urls, key=int)}")

    if args.rounds != "all":
        wanted = {r.strip() for r in args.rounds.split(",")}
        round_urls = {k: v for k, v in round_urls.items() if k in wanted}
        print(f"   filter: {sorted(round_urls, key=int)}")

    if not args.no_match:
        print(f"[2/4] loading match candidates from {DB_PATH}")
        candidates = load_match_candidates(DB_PATH)
        print(f"   {len(candidates)} program candidates")
    else:
        candidates = []

    all_records: list[AdoptionRecord] = []
    all_stats = {"pages": 0, "pages_clean": 0, "pages_dirty": 0, "rows_emitted": 0}
    for round_num in sorted(round_urls, key=int):
        url = round_urls[round_num]
        label = f"第{round_num}回公募"
        print(f"[3/4] round {round_num}: fetching {url}")
        try:
            pdf_path, checksum = fetch_pdf(url)
        except Exception as exc:  # noqa: BLE001
            print(f"   FETCH FAIL: {exc}", file=sys.stderr)
            return 1
        print(f"   cached {pdf_path} ({pdf_path.stat().st_size:,} bytes) sha256={checksum[:12]}")
        records, stats = parse_round_pdf(pdf_path, label, url, checksum)
        # Best-effort name match.
        if candidates:
            for r in records:
                uid = match_program_for(r.recipient_name, candidates)
                if uid:
                    r.program_unified_id = uid
        print(
            f"   parsed: {stats['rows_emitted']} rows from "
            f"{stats['pages_clean']}/{stats['pages']} clean pages"
        )
        all_records.extend(records)
        for k in all_stats:
            all_stats[k] += stats[k]

    print(f"[4/4] writing {args.out}")
    write_jsonl(all_records, args.out)

    elapsed = time.monotonic() - t0
    print(
        f"done: {all_stats['rows_emitted']} rows / "
        f"{all_stats['pages_clean']} clean / "
        f"{all_stats['pages_dirty']} dirty / "
        f"{elapsed:.1f}s wall"
    )
    if all_stats["pages"] and all_stats["pages_dirty"] / all_stats["pages"] > 0.20:
        print("PARSE QUALITY FAILURE (>20% dirty pages)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
