#!/usr/bin/env python3
"""Extract machine-readable eligibility predicates from jpi_programs.

Output: one row per program in `am_program_eligibility_predicate_json`
(autonomath.db, migration 164). The `predicate_json` blob lets customer
LLMs evaluate "does program X cover corp Y?" via simple boolean logic
instead of re-reading 公募要領 prose every query.

Inputs (all columns of jpi_programs):
    primary_name, prefecture, municipality, program_kind,
    target_types_json, crop_categories_json, funding_purpose_json,
    enriched_json (deeply nested — extraction.eligibility_structured /
    extraction.application_plan.eligibility_clauses / extraction.basic).

Extraction is **regex + Python only**. No LLM call (LLM-extracted
predicates land in a later wave). Each axis is independently optional;
missing data does NOT mean "no constraint" downstream — the consumer
treats `null` / absent key as `unknown`.

Usage:
    .venv/bin/python scripts/etl/extract_eligibility_predicate.py
        [--limit N]              # process at most N programs (default: all)
        [--db PATH]              # autonomath.db path
        [--no-write]             # dry-run (no INSERT)
        [--report-out PATH]      # write distribution report JSON to PATH
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger("extract_eligibility_predicate")

# ---------------------------------------------------------------------------
# Constants — regex patterns, taxonomies, mappings
# ---------------------------------------------------------------------------

# Prefecture name → JIS 2-digit code (matches am_region.region_code prefix).
PREFECTURE_JIS: dict[str, str] = {
    "北海道": "01",
    "青森県": "02",
    "岩手県": "03",
    "宮城県": "04",
    "秋田県": "05",
    "山形県": "06",
    "福島県": "07",
    "茨城県": "08",
    "栃木県": "09",
    "群馬県": "10",
    "埼玉県": "11",
    "千葉県": "12",
    "東京都": "13",
    "神奈川県": "14",
    "新潟県": "15",
    "富山県": "16",
    "石川県": "17",
    "福井県": "18",
    "山梨県": "19",
    "長野県": "20",
    "岐阜県": "21",
    "静岡県": "22",
    "愛知県": "23",
    "三重県": "24",
    "滋賀県": "25",
    "京都府": "26",
    "大阪府": "27",
    "兵庫県": "28",
    "奈良県": "29",
    "和歌山県": "30",
    "鳥取県": "31",
    "島根県": "32",
    "岡山県": "33",
    "広島県": "34",
    "山口県": "35",
    "徳島県": "36",
    "香川県": "37",
    "愛媛県": "38",
    "高知県": "39",
    "福岡県": "40",
    "佐賀県": "41",
    "長崎県": "42",
    "熊本県": "43",
    "大分県": "44",
    "宮崎県": "45",
    "鹿児島県": "46",
    "沖縄県": "47",
}

# JSIC industry inference from program name + funding purpose.
#   Pattern → JSIC major letter. Order matters (first match wins for the
#   keyword, but multiple keywords can fire for the same row → multi-JSIC).
JSIC_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"農業|林業|農林|新規就農|就農|農作物|担い手|農地|農機"), "A"),
    (re.compile(r"漁業|水産|養殖|沿岸|漁協|漁船"), "B"),
    (re.compile(r"鉱業|採石|砂利|採取"), "C"),
    (re.compile(r"建設|建築|土木|住宅|耐震|改修|工事|下請|空き家"), "D"),
    (re.compile(r"製造|ものづくり|工場|設備投資|生産|加工|事業再構築"), "E"),
    (re.compile(r"電気|ガス|熱供給|水道|エネルギー|発電|再エネ"), "F"),
    (re.compile(r"情報通信|IT|DX|デジタル|ソフトウェア|システム|アプリ|データ"), "G"),
    (re.compile(r"運輸|物流|輸送|郵便|配送|トラック|タクシー|バス|貨物"), "H"),
    (re.compile(r"卸売|小売|商店|ショップ|販売|EC|通販|店舗"), "I"),
    (re.compile(r"金融|保険|信用|融資|貸付|信金|信組"), "J"),
    (re.compile(r"不動産|賃貸|物品レンタル|リース"), "K"),
    (re.compile(r"研究開発|学術|専門サービス|技術サービス|デザイン"), "L"),
    (re.compile(r"宿泊|飲食|レストラン|旅館|ホテル|食堂|カフェ|居酒屋"), "M"),
    (re.compile(r"理美容|美容室|理容|娯楽|エステ|フィットネス|スポーツクラブ|生活関連"), "N"),
    (re.compile(r"教育|学習|学校|塾|スクール|研修"), "O"),
    (re.compile(r"医療|福祉|介護|病院|クリニック|診療|看護|保健|障害者"), "P"),
    (re.compile(r"郵便局|協同組合"), "Q"),
    (re.compile(r"観光|地域活性|まちづくり|文化|芸術|サービス業"), "R"),
]

# Cap regex: 資本金 ≤ N円/万円/億円. Captures the number + the unit suffix.
# Allow up to 40 non-digit chars between 「資本金」 and the number to absorb
# variations like 「資本金の額又は出資の総額が3億円以下」.
CAPITAL_MAX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"資本金(?:の額|額)?(?:[^0-9]{0,40})?([0-9,，]+(?:\.[0-9]+)?)\s*(億円|万円|円)\s*以下"
    ),
    re.compile(
        r"資本金(?:の額|額)?(?:[^0-9]{0,40})?([0-9,，]+(?:\.[0-9]+)?)\s*(億円|万円|円)\s*未満"
    ),
]

# Employee max: 従業員 ≤ N人. (常時雇用する従業員 / 従業員数 / 雇用 etc.)
# Likewise allow short non-digit gaps so 「常時使用する従業員数が300人以下」 fires.
EMPLOYEE_MAX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:常時(?:使用|雇用)する)?従業員(?:数)?(?:[^0-9]{0,15})?([0-9,，]+)\s*人?\s*以下"),
    re.compile(r"(?:常時(?:使用|雇用)する)?従業員(?:数)?(?:[^0-9]{0,15})?([0-9,，]+)\s*人?\s*未満"),
    re.compile(r"従業員\s*([0-9,，]+)\s*名以下"),
]

# Business years min: 業歴 / 創業 N 年以上 / 設立後 N 年以上.
BUSINESS_YEARS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"業歴\s*([0-9]+)\s*年以上"),
    re.compile(r"創業(?:から|後)?\s*([0-9]+)\s*年以上"),
    re.compile(r"設立(?:から|後)?\s*([0-9]+)\s*年以上"),
    re.compile(r"開業(?:から|後)?\s*([0-9]+)\s*年以上"),
]

# Age max: 年齢 N 歳未満 / 就農時 N 歳未満.
AGE_MAX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:就農時|申請時)?\s*([0-9]{2})\s*歳未満"),
    re.compile(r"(?:就農時|申請時)?\s*([0-9]{2})\s*歳以下"),
]

AGE_MIN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"([0-9]{2})\s*歳以上"),
]

# Certification keywords (any-of detection). Stored as raw text matches.
CERTIFICATION_KEYWORDS = (
    "認定新規就農者",
    "認定農業者",
    "中小企業者",
    "小規模事業者",
    "適格請求書発行事業者",
    "経営革新計画",
    "先端設備等導入計画",
    "事業継続力強化計画",
    "経営力向上計画",
    "事業承継計画",
    "認定経営革新等支援機関",
    "BCP策定",
    "M&A支援機関",
)

# Funding purpose keywords (any-of). Coarse — feeds funding_purposes axis.
FUNDING_PURPOSE_KEYWORDS = (
    "新規就農",
    "設備投資",
    "事業再構築",
    "事業承継",
    "創業",
    "起業",
    "DX",
    "GX",
    "脱炭素",
    "省エネ",
    "海外展開",
    "輸出",
    "販路開拓",
    "研究開発",
    "人材育成",
    "賃上げ",
    "省力化",
    "IT導入",
    "改修",
    "耐震",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


def _to_yen(num_str: str, unit: str) -> int | None:
    """Convert (number_string, unit) → integer yen. Returns None on parse fail."""
    cleaned = num_str.replace(",", "").replace("，", "")
    try:
        n = float(cleaned)
    except ValueError:
        return None
    if unit == "億円":
        return int(n * 100_000_000)
    if unit == "万円":
        return int(n * 10_000)
    if unit == "円":
        return int(n)
    return None


def _to_int(num_str: str) -> int | None:
    cleaned = num_str.replace(",", "").replace("，", "")
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _scan_text_for_industries(text: str) -> list[str]:
    """Return JSIC major letters whose keyword fires in `text`. Dedup, sorted."""
    if not text:
        return []
    found: set[str] = set()
    for pat, code in JSIC_KEYWORDS:
        if pat.search(text):
            found.add(code)
    return sorted(found)


def _scan_text_for_certifications(text: str) -> list[str]:
    if not text:
        return []
    return sorted({k for k in CERTIFICATION_KEYWORDS if k in text})


def _scan_text_for_funding_purposes(text: str) -> list[str]:
    if not text:
        return []
    return sorted({k for k in FUNDING_PURPOSE_KEYWORDS if k in text})


def _first_regex_value(text: str, patterns: list[re.Pattern[str]]) -> tuple[str, ...] | None:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.groups()
    return None


def _walk_eligibility_clauses(enriched: dict | None) -> list[str]:
    """Return the raw text of `extraction.application_plan.eligibility_clauses`
    plus _source_quote-like strings under `extraction.eligibility_structured`.
    """
    if not enriched:
        return []
    out: list[str] = []
    extraction = enriched.get("extraction") or {}
    ap = extraction.get("application_plan") or {}
    clauses = ap.get("eligibility_clauses") or []
    if isinstance(clauses, list):
        for c in clauses:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                out.append(c["text"])
            elif isinstance(c, str):
                out.append(c)
    es = extraction.get("eligibility_structured") or {}

    def _collect_quotes(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("_source_quote", "_source_quotes"):
                    if isinstance(v, str):
                        out.append(v)
                    elif isinstance(v, list):
                        for q in v:
                            if isinstance(q, dict) and isinstance(q.get("quote"), str):
                                out.append(q["quote"])
                            elif isinstance(q, str):
                                out.append(q)
                else:
                    _collect_quotes(v)
        elif isinstance(node, list):
            for it in node:
                _collect_quotes(it)

    _collect_quotes(es)
    return out


def _structured_eligibility_axes(enriched: dict | None) -> dict[str, Any]:
    """Pull pre-extracted axes from extraction.eligibility_structured if present.

    The autonomath ingest pipeline sometimes filled these directly; we read
    them as-is rather than re-derive from the prose. Only takes well-formed
    fields; silently skips malformed sub-trees.
    """
    out: dict[str, Any] = {}
    if not enriched:
        return out
    es = (enriched.get("extraction") or {}).get("eligibility_structured") or {}

    person = es.get("person_attributes") or {}
    age = person.get("age") or {}
    if isinstance(age, dict):
        a_min = age.get("min") if isinstance(age.get("min"), int) else None
        a_max = age.get("max") if isinstance(age.get("max"), int) else None
        if a_min is not None or a_max is not None:
            out["age"] = {"min": a_min, "max": a_max}

    entity = es.get("entity") or {}
    employees = entity.get("employees") or {}
    if isinstance(employees, dict):
        e_max = employees.get("max")
        if isinstance(e_max, int):
            out["employee_max"] = e_max

    years = entity.get("years_since_establishment") or {}
    if isinstance(years, dict):
        y_min = years.get("min")
        if isinstance(y_min, int):
            out["min_business_years"] = y_min

    certs = es.get("certifications") or {}
    any_of = certs.get("any_of")
    if isinstance(any_of, list):
        out["certifications_any_of"] = sorted({s for s in any_of if isinstance(s, str)})

    regional = es.get("regional") or {}
    prefs = regional.get("prefectures")
    if isinstance(prefs, list):
        out["prefectures_struct"] = sorted({s for s in prefs if isinstance(s, str)})
    munis = regional.get("municipalities")
    if isinstance(munis, list):
        out["municipalities_struct"] = sorted({s for s in munis if isinstance(s, str)})

    return out


# ---------------------------------------------------------------------------
# Per-row predicate extraction
# ---------------------------------------------------------------------------


def extract_predicate(row: sqlite3.Row) -> tuple[dict[str, Any], float]:
    """Return (predicate_json_dict, confidence) for a single jpi_programs row."""

    name = row["primary_name"] or ""
    prefecture = row["prefecture"] or ""
    municipality = row["municipality"] or ""

    target_types = _safe_json_loads(row["target_types_json"]) or []
    crop_categories = _safe_json_loads(row["crop_categories_json"]) or []
    funding_purpose_raw = _safe_json_loads(row["funding_purpose_json"]) or []
    enriched = _safe_json_loads(row["enriched_json"]) if row["enriched_json"] else None

    # ---------- Pre-structured axes (highest priority) ----------
    struct_axes = _structured_eligibility_axes(enriched)

    # ---------- Clauses + name as the regex haystack ----------
    clauses = _walk_eligibility_clauses(enriched)
    haystack_parts: list[str] = [name, *clauses]
    haystack = "\n".join(p for p in haystack_parts if p)

    # ---------- INDUSTRIES ----------
    industries: list[str] = _scan_text_for_industries(
        name + "\n" + " ".join(funding_purpose_raw if isinstance(funding_purpose_raw, list) else [])
    )
    if not industries and clauses:
        industries = _scan_text_for_industries("\n".join(clauses))

    # ---------- PREFECTURES ----------
    prefectures: list[str] = []
    prefecture_jis: list[str] = []
    if prefecture and prefecture != "全国" and prefecture in PREFECTURE_JIS:
        prefectures = [prefecture]
        prefecture_jis = [PREFECTURE_JIS[prefecture]]
    elif "prefectures_struct" in struct_axes:
        prefectures = struct_axes["prefectures_struct"]
        prefecture_jis = [PREFECTURE_JIS[p] for p in prefectures if p in PREFECTURE_JIS]

    # ---------- MUNICIPALITIES ----------
    municipalities: list[str] = []
    if municipality:
        municipalities = [municipality]
    elif "municipalities_struct" in struct_axes:
        municipalities = struct_axes["municipalities_struct"]

    # ---------- CAPITAL MAX ----------
    capital_max_yen: int | None = None
    cap_match = _first_regex_value(haystack, CAPITAL_MAX_PATTERNS)
    if cap_match:
        capital_max_yen = _to_yen(cap_match[0], cap_match[1])

    # ---------- EMPLOYEE MAX ----------
    employee_max: int | None = struct_axes.get("employee_max")
    if employee_max is None:
        emp_match = _first_regex_value(haystack, EMPLOYEE_MAX_PATTERNS)
        if emp_match:
            employee_max = _to_int(emp_match[0])

    # ---------- BUSINESS YEARS MIN ----------
    min_business_years: int | None = struct_axes.get("min_business_years")
    if min_business_years is None:
        by_match = _first_regex_value(haystack, BUSINESS_YEARS_PATTERNS)
        if by_match:
            min_business_years = _to_int(by_match[0])

    # ---------- AGE ----------
    age_axis: dict[str, int | None] | None = struct_axes.get("age")
    if age_axis is None and haystack:
        a_max_match = _first_regex_value(haystack, AGE_MAX_PATTERNS)
        a_min_match = _first_regex_value(haystack, AGE_MIN_PATTERNS)
        a_min = _to_int(a_min_match[0]) if a_min_match else None
        a_max = _to_int(a_max_match[0]) if a_max_match else None
        if a_min is not None or a_max is not None:
            age_axis = {"min": a_min, "max": a_max}

    # ---------- TARGET ENTITY TYPES ----------
    target_entity_types: list[str] = []
    if isinstance(target_types, list):
        target_entity_types = sorted({str(t) for t in target_types if t})

    # ---------- CROP CATEGORIES ----------
    crop_axis: list[str] = []
    if isinstance(crop_categories, list):
        crop_axis = sorted({str(c) for c in crop_categories if c and c != "_all"})

    # ---------- FUNDING PURPOSES ----------
    funding_purposes: list[str] = []
    if isinstance(funding_purpose_raw, list) and funding_purpose_raw:
        funding_purposes = sorted({str(f) for f in funding_purpose_raw if f})
    if not funding_purposes:
        funding_purposes = _scan_text_for_funding_purposes(name + "\n" + haystack)

    # ---------- CERTIFICATIONS ----------
    certifications_any_of: list[str] = struct_axes.get("certifications_any_of", [])
    if not certifications_any_of:
        certifications_any_of = _scan_text_for_certifications(name + "\n" + haystack)

    # ---------- RAW residue ----------
    raw_constraints = [c for c in clauses if c]

    # ---------- Assemble ----------
    predicate: dict[str, Any] = {}
    if industries:
        predicate["industries_jsic"] = industries
    if prefectures:
        predicate["prefectures"] = prefectures
    if prefecture_jis:
        predicate["prefecture_jis"] = prefecture_jis
    if municipalities:
        predicate["municipalities"] = municipalities
    if capital_max_yen is not None:
        predicate["capital_max_yen"] = capital_max_yen
    if employee_max is not None:
        predicate["employee_max"] = employee_max
    if min_business_years is not None:
        predicate["min_business_years"] = min_business_years
    if age_axis:
        predicate["age"] = age_axis
    if target_entity_types:
        predicate["target_entity_types"] = target_entity_types
    if crop_axis:
        predicate["crop_categories"] = crop_axis
    if funding_purposes:
        predicate["funding_purposes"] = funding_purposes
    if certifications_any_of:
        predicate["certifications_any_of"] = certifications_any_of
    if raw_constraints:
        # cap raw_constraints to keep blob size bounded.
        predicate["raw_constraints"] = raw_constraints[:50]

    # ---------- Confidence heuristic ----------
    # Count how many "structured" axes (non-raw_constraints) populated.
    populated_axes = sum(1 for k in predicate if k != "raw_constraints")
    confidence = min(1.0, populated_axes / 6.0)  # ≥6 axes = full confidence

    return predicate, confidence


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get(
            "AUTONOMATH_DB_PATH",
            str(Path(__file__).resolve().parents[2] / "autonomath.db"),
        ),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--report-out", type=str, default=None)
    parser.add_argument(
        "--snapshot-id",
        type=str,
        default=None,
        help="source_program_corpus_snapshot_id stamped on every row.",
    )
    parser.add_argument(
        "--only-id", type=str, default=None, help="Process a single program by unified_id (debug)."
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    db_path = args.db
    if not Path(db_path).exists():
        logger.error("db not found: %s", db_path)
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-262144")

    where = "excluded = 0"
    params: list[Any] = []
    if args.only_id:
        where += " AND unified_id = ?"
        params.append(args.only_id)

    sql = f"""
        SELECT unified_id, primary_name, prefecture, municipality, program_kind,
               target_types_json, crop_categories_json, funding_purpose_json,
               enriched_json
          FROM jpi_programs
         WHERE {where}
         ORDER BY unified_id
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    logger.info("loading rows from %s", db_path)
    rows = conn.execute(sql, params).fetchall()
    logger.info("loaded %d rows", len(rows))

    snapshot_id = args.snapshot_id or f"corpus@{int(time.time())}"

    # --------- Per-axis populate counters ---------
    total = 0
    raw_only_count = 0
    failures = 0
    axis_pop = Counter()
    axes_per_row = Counter()
    confidence_sum = 0.0

    upsert_sql = """
        INSERT OR REPLACE INTO am_program_eligibility_predicate_json
            (program_id, predicate_json, extraction_method, confidence,
             extracted_at, source_program_corpus_snapshot_id)
        VALUES (?, ?, 'rule_based', ?, datetime('now'), ?)
    """

    batch: list[tuple[str, str, float, str]] = []
    BATCH_SIZE = 500  # noqa: N806  (local CONST sentinel, not loop-mut)

    t0 = time.time()
    for i, row in enumerate(rows, 1):
        try:
            predicate, confidence = extract_predicate(row)
        except Exception:  # extractor must never crash the run
            logger.exception("extract failed for %s", row["unified_id"])
            failures += 1
            continue

        total += 1
        confidence_sum += confidence

        axes_present = [k for k in predicate if k != "raw_constraints"]
        if not axes_present and "raw_constraints" in predicate:
            raw_only_count += 1
        for k in axes_present:
            axis_pop[k] += 1
        axes_per_row[len(axes_present)] += 1

        if not args.no_write:
            batch.append(
                (
                    row["unified_id"],
                    json.dumps(predicate, ensure_ascii=False),
                    round(confidence, 3),
                    snapshot_id,
                )
            )
            if len(batch) >= BATCH_SIZE:
                conn.executemany(upsert_sql, batch)
                conn.commit()
                batch.clear()

        if i % 1000 == 0:
            elapsed = time.time() - t0
            logger.info("processed %d/%d (%.1f rows/s)", i, len(rows), i / max(elapsed, 0.001))

    if batch and not args.no_write:
        conn.executemany(upsert_sql, batch)
        conn.commit()

    elapsed = time.time() - t0

    # --------- Distribution report ---------
    report = {
        "db": db_path,
        "snapshot_id": snapshot_id,
        "total_processed": total,
        "failures": failures,
        "raw_only_count": raw_only_count,
        "raw_only_pct": round(100.0 * raw_only_count / max(total, 1), 2),
        "no_axis_count": axes_per_row.get(0, 0),
        "axes_populated_pct": {
            axis: round(100.0 * cnt / max(total, 1), 2) for axis, cnt in axis_pop.most_common()
        },
        "axis_count_distribution": {str(k): axes_per_row[k] for k in sorted(axes_per_row)},
        "avg_confidence": round(confidence_sum / max(total, 1), 3),
        "elapsed_sec": round(elapsed, 2),
    }

    print("\n=== Eligibility predicate extraction report ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("wrote report to %s", args.report_out)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
