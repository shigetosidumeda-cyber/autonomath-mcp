"""DD2 — Structured ingest of Textract OCR output into am_municipality_subsidy.

Reads the DD2 Textract ledger
(``data/textract_municipality_bulk_2026_05_17_ledger.json``), downloads each
``SUCCEEDED`` job's Textract JSON output from S3 under
``s3://...derived/municipality_ocr/<municipality_code>/<sha>/``, extracts
structured fields (program_name, amount_yen_max/min, deadline,
target_jsic_majors, target_corporate_forms, requirement_text) using:

  * pure regex over the OCR ``LINE`` text concatenation
  * a 国税庁 / 政府用語辞典 (built-in, small) for 法人形態 + 業種 mapping

…and writes the rows into ``am_municipality_subsidy`` (autonomath.db,
migration ``wave24_217``).

Constraints
-----------

* **NO LLM call.** Pure regex + sqlite3 + JSON.
* mypy --strict clean.
* Idempotent: UNIQUE(municipality_code, program_name, source_url) +
  INSERT OR REPLACE on re-run.

Usage
-----

::

    python scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py \\
        --ledger data/textract_municipality_bulk_2026_05_17_ledger.json \\
        --db autonomath.db \\
        --dry-run

    # Wet run pulls OCR JSON from S3.
    python scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py \\
        --ledger data/textract_municipality_bulk_2026_05_17_ledger.json \\
        --db autonomath.db \\
        --commit
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
from typing import Any

logger = logging.getLogger("jpcite.etl.dd2_ingest_municipality_subsidy")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LEDGER = _REPO_ROOT / "data" / "textract_municipality_bulk_2026_05_17_ledger.json"
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_MANIFEST = _REPO_ROOT / "data" / "etl_dd2_municipality_manifest_2026_05_17.json"

# ---------------------------------------------------------------------------
# 国税庁 / 政府用語辞典 (compact, built-in)
# ---------------------------------------------------------------------------

# JSIC major code mapping by Japanese industry keyword (post-2013 revision).
_JSIC_MAJOR_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("農業", "A"),
    ("林業", "A"),
    ("漁業", "B"),
    ("鉱業", "C"),
    ("建設業", "D"),
    ("建設", "D"),
    ("製造業", "E"),
    ("製造", "E"),
    ("電気業", "F"),
    ("ガス業", "F"),
    ("熱供給", "F"),
    ("水道業", "F"),
    ("情報通信業", "G"),
    ("情報通信", "G"),
    ("IT", "G"),
    ("ソフトウェア", "G"),
    ("運輸業", "H"),
    ("郵便業", "H"),
    ("卸売業", "I"),
    ("小売業", "I"),
    ("商業", "I"),
    ("金融業", "J"),
    ("保険業", "J"),
    ("不動産業", "K"),
    ("物品賃貸業", "K"),
    ("学術研究", "L"),
    ("専門・技術", "L"),
    ("宿泊業", "M"),
    ("飲食サービス", "M"),
    ("飲食店", "M"),
    ("生活関連サービス", "N"),
    ("娯楽業", "N"),
    ("教育", "O"),
    ("学習支援", "O"),
    ("医療", "P"),
    ("福祉", "P"),
    ("介護", "P"),
    ("複合サービス", "Q"),
    ("協同組合", "Q"),
    ("サービス業", "R"),
    ("公務", "S"),
)

# 法人形態 mapping
_CORP_FORM_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("株式会社", "kabushiki"),
    ("合同会社", "godo"),
    ("有限会社", "yugen"),
    ("合資会社", "goshi"),
    ("合名会社", "gomei"),
    ("一般社団法人", "ippan_shadan"),
    ("一般財団法人", "ippan_zaidan"),
    ("公益社団法人", "koueki_shadan"),
    ("公益財団法人", "koueki_zaidan"),
    ("特定非営利活動法人", "npo"),
    ("NPO", "npo"),
    ("個人事業主", "kojin_jigyou"),
    ("個人事業", "kojin_jigyou"),
)

# 補助率 patterns
_RATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"補助率[\s::]*([\d０-９]+)\s*[//]\s*([\d０-９]+)"),
    re.compile(r"補助率[\s::]*([\d０-９]+(?:\.[\d０-９]+)?)\s*[%％]"),
    re.compile(r"補助率\s*([\d０-９]+(?:\.[\d０-９]+)?)\s*[%％]"),
    re.compile(r"([\d０-９]+(?:\.[\d０-９]+)?)\s*[%％]\s*以内"),
)

# 金額 patterns
_AMOUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"上限[\s::]*([\d０-９,，]+)\s*円"),
    re.compile(r"最大[\s::]*([\d０-９,，]+)\s*円"),
    re.compile(r"上限額[\s::]*([\d０-９,，]+)\s*円"),
    re.compile(r"補助金額[\s::]*([\d０-９,，]+)\s*円"),
    re.compile(r"補助上限[\s::]*([\d０-９,，]+)\s*円"),
    re.compile(r"([\d０-９,，]+)\s*万円"),
)

# 締切 (deadline) patterns — extract YYYY-MM-DD or 令和 wareki.
_DEADLINE_RE = re.compile(r"(令和|平成|R|H)?\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
_DEADLINE_KEYWORDS = ("締切", "申請期限", "受付期限", "募集期間", "提出期限")

# Program-name detector — pick the first heading-like LINE containing
# 補助金 / 助成金 / 給付金 / 支援金.
_PROGRAM_KEYWORDS = ("補助金", "助成金", "給付金", "支援金", "報奨金")

# Half-width / full-width digit normaliser.
_HW_FW_DIGITS = {chr(0xFF10 + i): chr(0x30 + i) for i in range(10)}
# Fullwidth comma U+FF0C → ASCII comma.
_HW_FW_DIGITS["，"] = ","


def _normalise(text: str) -> str:
    return "".join(_HW_FW_DIGITS.get(c, c) for c in text)


@dataclass(slots=True)
class IngestStats:
    rows_seen: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    s3_fetch_failures: int = 0
    extraction_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "rows_seen": self.rows_seen,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "rows_skipped": self.rows_skipped,
            "s3_fetch_failures": self.s3_fetch_failures,
            "extraction_failures": self.extraction_failures,
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=_DEFAULT_LEDGER)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually fetch OCR JSON from S3 and write to DB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="default — skip S3 + DB writes",
    )
    return parser.parse_args(argv)


def _digits_to_int(s: str) -> int | None:
    """Parse a JP integer string like '1,000,000' or '10万' to int yen."""
    s = _normalise(s).replace(",", "").replace(",", "").strip()
    if not s.isdigit():
        return None
    return int(s)


def _extract_program_name(lines: list[str]) -> str | None:
    """Pick the first LINE that contains one of the program keywords."""
    for line in lines[:80]:  # only top of doc — heading region
        for kw in _PROGRAM_KEYWORDS:
            if kw in line and len(line) <= 80:
                return line.strip()
    return None


def _extract_amount_yen_max(text: str) -> int | None:
    """Match the largest amount pattern in the text."""
    candidates: list[int] = []
    norm = _normalise(text)
    for pat in _AMOUNT_PATTERNS:
        for m in pat.finditer(norm):
            raw = m.group(1)
            val = _digits_to_int(raw)
            if val is None:
                continue
            # 万円 keyword multiplier (pattern[-1])
            if "万円" in m.group(0):
                val *= 10000
            candidates.append(val)
    return max(candidates) if candidates else None


def _extract_subsidy_rate(text: str) -> float | None:
    """Extract subsidy rate as a fraction in 0.0..1.0.

    Recognises:

      * ``補助率 1/2`` (ratio numerator / denominator)
      * ``補助率 50%`` / ``50 %`` / ``50％`` (percentage)
      * ``50% 以内`` (percentage with 以内 qualifier)
    """
    norm = _normalise(text)
    # 1) Ratio form first (more specific).
    m_ratio = re.search(r"補助率[\s::]*([\d]+)\s*[//]\s*([\d]+)", norm)
    if m_ratio:
        num = _digits_to_int(m_ratio.group(1))
        den = _digits_to_int(m_ratio.group(2))
        if num is not None and den is not None and den > 0:
            return min(1.0, num / den)
    # 2) Percentage form.
    for pat in (
        re.compile(r"補助率[\s::]*([\d]+(?:\.[\d]+)?)\s*[%％]"),
        re.compile(r"([\d]+(?:\.[\d]+)?)\s*[%％]\s*以内"),
    ):
        m = pat.search(norm)
        if not m:
            continue
        try:
            return min(1.0, float(m.group(1)) / 100.0)
        except ValueError:
            continue
    return None


def _extract_deadline(text: str) -> str | None:
    """Extract first deadline date (YYYY-MM-DD) from text."""
    norm = _normalise(text)
    # Confine to lines that mention 締切 / 申請期限 keywords for precision.
    candidates: list[str] = []
    for line in norm.splitlines():
        if not any(k in line for k in _DEADLINE_KEYWORDS):
            continue
        m = _DEADLINE_RE.search(line)
        if not m:
            continue
        era = m.group(1) or ""
        yr_raw = _digits_to_int(m.group(2))
        mo_raw = _digits_to_int(m.group(3))
        da_raw = _digits_to_int(m.group(4))
        if yr_raw is None or mo_raw is None or da_raw is None:
            continue
        if era in ("令和", "R"):
            yr = 2018 + yr_raw
        elif era in ("平成", "H"):
            yr = 1988 + yr_raw
        else:
            yr = yr_raw if yr_raw >= 1900 else 2018 + yr_raw  # heuristic
        try:
            candidates.append(f"{yr:04d}-{mo_raw:02d}-{da_raw:02d}")
        except ValueError:
            continue
    return candidates[0] if candidates else None


def _extract_jsic_majors(text: str) -> list[str]:
    """Detect JSIC major codes from keyword presence in the OCR text."""
    found: list[str] = []
    seen: set[str] = set()
    for keyword, major in _JSIC_MAJOR_KEYWORDS:
        if keyword in text and major not in seen:
            found.append(major)
            seen.add(major)
    return found


def _extract_corporate_forms(text: str) -> list[str]:
    """Detect corporate-form codes from keyword presence."""
    found: list[str] = []
    seen: set[str] = set()
    for keyword, code in _CORP_FORM_KEYWORDS:
        if keyword in text and code not in seen:
            found.append(code)
            seen.add(code)
    return found


def _join_lines_from_textract(blocks: list[dict[str, Any]]) -> list[str]:
    """Concatenate Textract LINE blocks in document order."""
    lines: list[str] = []
    for b in blocks:
        if b.get("BlockType") == "LINE":
            txt = b.get("Text", "")
            if isinstance(txt, str) and txt.strip():
                lines.append(txt.strip())
    return lines


def _license_for_url(url: str) -> str:
    """Heuristic license tag from URL host."""
    low = url.lower()
    if "lg.jp" in low or "pref." in low or "city." in low or "town." in low or "vill." in low:
        return "public_domain_jp_gov"
    if "jcci.or.jp" in low:
        return "cc_by_4.0"
    return "gov_standard"


def _lookup_manifest(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Return ``{municipality_code: manifest_entry}``."""
    if not manifest_path.exists():
        return {}
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for entry in raw.get("municipalities", []):
        code = str(entry.get("municipality_code") or "")
        if code:
            out[code] = entry
    return out


def _fetch_textract_json(
    s3_client: Any | None,
    *,
    bucket: str,
    prefix: str,
) -> dict[str, Any] | None:
    """Fetch the first ``<prefix>/<some-uuid>.json`` Textract output."""
    if s3_client is None:
        return None
    try:
        resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=10)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return parsed
                return None
    except Exception:  # noqa: BLE001 — boto3 surfaces ClientError
        return None
    return None


def _extract_row(
    *,
    municipality: dict[str, Any],
    blocks: list[dict[str, Any]],
    source_url: str,
    sha: str,
    s3_pdf: str,
    s3_ocr: str,
    ocr_job_id: str,
    ocr_confidence: float,
    ocr_page_count: int,
) -> dict[str, Any] | None:
    """Produce one am_municipality_subsidy row dict from OCR blocks."""
    lines = _join_lines_from_textract(blocks)
    if not lines:
        return None
    full_text = "\n".join(lines)
    program_name = _extract_program_name(lines)
    if not program_name:
        return None

    return {
        "municipality_code": municipality["municipality_code"],
        "prefecture": municipality.get("prefecture", ""),
        "municipality_name": municipality.get("municipality_name", ""),
        "municipality_type": municipality.get("municipality_type", "regular"),
        "program_name": program_name,
        "amount_yen_max": _extract_amount_yen_max(full_text),
        "amount_yen_min": None,
        "subsidy_rate": _extract_subsidy_rate(full_text),
        "deadline": _extract_deadline(full_text),
        "target_jsic_majors": json.dumps(_extract_jsic_majors(full_text), ensure_ascii=False),
        "target_corporate_forms": json.dumps(
            _extract_corporate_forms(full_text), ensure_ascii=False
        ),
        "target_region_codes": json.dumps([municipality["municipality_code"]], ensure_ascii=False),
        "requirement_text": full_text[:8000],
        "contact_window_id": None,
        "source_url": source_url,
        "source_pdf_s3_uri": s3_pdf,
        "ocr_s3_uri": s3_ocr,
        "ocr_job_id": ocr_job_id,
        "ocr_confidence": ocr_confidence,
        "ocr_page_count": ocr_page_count,
        "sha256": sha,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "license": _license_for_url(source_url),
        "license_source": "url_host_heuristic",
    }


def _insert_row(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Insert / replace one row into am_municipality_subsidy.

    Returns 'INSERT' or 'UPDATE' for stats.
    """
    cur = conn.execute(
        """
        SELECT subsidy_id FROM am_municipality_subsidy
         WHERE municipality_code = ? AND program_name = ? AND source_url = ?
        """,
        (row["municipality_code"], row["program_name"], row["source_url"]),
    )
    existing = cur.fetchone()
    action = "UPDATE" if existing else "INSERT"

    conn.execute(
        """
        INSERT OR REPLACE INTO am_municipality_subsidy
            (subsidy_id, municipality_code, prefecture, municipality_name,
             municipality_type, program_name, amount_yen_max, amount_yen_min,
             subsidy_rate, deadline, target_jsic_majors, target_corporate_forms,
             target_region_codes, requirement_text, contact_window_id,
             source_url, source_pdf_s3_uri, ocr_s3_uri, ocr_job_id,
             ocr_confidence, ocr_page_count, sha256, fetched_at, license,
             license_source, updated_at)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            existing[0] if existing else None,
            row["municipality_code"],
            row["prefecture"],
            row["municipality_name"],
            row["municipality_type"],
            row["program_name"],
            row["amount_yen_max"],
            row["amount_yen_min"],
            row["subsidy_rate"],
            row["deadline"],
            row["target_jsic_majors"],
            row["target_corporate_forms"],
            row["target_region_codes"],
            row["requirement_text"],
            row["contact_window_id"],
            row["source_url"],
            row["source_pdf_s3_uri"],
            row["ocr_s3_uri"],
            row["ocr_job_id"],
            row["ocr_confidence"],
            row["ocr_page_count"],
            row["sha256"],
            row["fetched_at"],
            row["license"],
            row["license_source"],
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    return action


def _run(args: argparse.Namespace) -> int:
    """Drive the structured ingest."""
    commit = bool(args.commit) and not bool(args.dry_run)

    if not args.ledger.exists():
        sys.stderr.write(f"FATAL: ledger missing: {args.ledger}\n")
        return 1
    if not args.db.exists():
        sys.stderr.write(f"FATAL: db missing: {args.db}\n")
        return 1

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = list(ledger.get("rows", []))
    manifest_lookup = _lookup_manifest(args.manifest)
    stats = IngestStats()

    s3_client: Any | None = None
    if commit:
        from scripts.aws_credit_ops._aws import s3_client as _s3_factory

        s3_client = _s3_factory()

    conn = sqlite3.connect(str(args.db), timeout=30.0)
    try:
        # Confirm the table exists — fail loud if migration didn't apply.
        conn.execute("SELECT 1 FROM am_municipality_subsidy LIMIT 0")

        for row in rows:
            stats.rows_seen += 1
            if row.get("status") not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
                stats.rows_skipped += 1
                continue

            municipality = manifest_lookup.get(row.get("municipality_code", ""))
            if not municipality:
                stats.rows_skipped += 1
                continue

            ocr_prefix = f"municipality_ocr/{row['sha_prefix']}/"  # default flat layout
            # If row carries an explicit output prefix, prefer it.
            ocr_prefix = row.get("ocr_prefix", ocr_prefix)

            ocr_json = _fetch_textract_json(
                s3_client,
                bucket="jpcite-credit-993693061769-202605-derived",
                prefix=ocr_prefix,
            )
            if ocr_json is None and commit:
                stats.s3_fetch_failures += 1
                continue
            blocks = (ocr_json or {}).get("Blocks", [])
            if not isinstance(blocks, list):
                blocks = []

            row_dict = _extract_row(
                municipality=municipality,
                blocks=blocks,
                source_url=row.get("source_url", ""),
                sha=row["sha_prefix"],
                s3_pdf=f"s3://{row.get('raw_bucket', 'jpcite-credit-993693061769-202605-derived')}/{row.get('raw_key', '')}",
                s3_ocr=f"s3://jpcite-credit-993693061769-202605-derived/{ocr_prefix}",
                ocr_job_id=row.get("job_id", ""),
                ocr_confidence=float(row.get("mean_confidence") or 0.0),
                ocr_page_count=int(row.get("page_count") or 0),
            )
            if row_dict is None:
                stats.extraction_failures += 1
                continue

            if commit:
                action = _insert_row(conn, row_dict)
                if action == "INSERT":
                    stats.rows_inserted += 1
                else:
                    stats.rows_updated += 1
                conn.commit()
            else:
                stats.rows_inserted += 1  # dry-run pretends success
    finally:
        conn.close()

    logger.info("DD2 ingest summary %s", stats.to_dict())
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entrypoint."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
