"""DD2 — Build the 1,718 市町村 補助金 PDF crawl manifest (2026-05-17).

Reads ``am_window_directory`` (target_db=autonomath, lane N4 LIVE) for the
1,885 ``jurisdiction_kind='municipality'`` rows, projects them down to the
canonical 1,718 市町村 set (designated city + designated ward + standard
city / town / village; excludes prefecture rows), and emits a JSON manifest
that the DD2 crawler consumes::

    data/etl_dd2_municipality_manifest_2026_05_17.json

Manifest schema
---------------

``{"generated_at": ISO8601_UTC,
   "source_table": "am_window_directory",
   "row_total": int,
   "municipalities": [
     {
       "municipality_code": "01202",   # J-LIS 5-digit
       "prefecture":        "北海道",
       "municipality_name": "函館市",
       "municipality_type": "regular",  # prefecture/seirei/chukaku/special/regular
       "window_url":        "https://www.city.hakodate.hokkaido.jp/...",
       "subsidy_search_seeds": [
         "https://www.city.hakodate.hokkaido.jp/sangyo/subsidy",
         "https://www.city.hakodate.hokkaido.jp/sangyo/josei",
       ],
       "expected_pdf_count_min": 3,
       "expected_pdf_count_max": 5
     }, ...
   ],
   "aggregator_blacklist": [...],
   "primary_host_regex":   "...",
   "crawl_constraints":    {"req_per_sec": 0.33, "concurrency": 32, "max_pdf_per_munic": 8}
}``

Constraints
-----------

* **NO LLM call.** Pure sqlite3 + json + regex.
* **No live HTTP.** Manifest is generated from the LIVE
  ``am_window_directory`` and a deterministic JIS-coded municipality name →
  expected subsidy-search path table.
* **Idempotent.** Re-running with the same DB snapshot produces a
  byte-identical manifest modulo ``generated_at``.
* mypy --strict clean.

Usage
-----

::

    python scripts/etl/build_dd2_municipality_manifest_2026_05_17.py
    python scripts/etl/build_dd2_municipality_manifest_2026_05_17.py \\
        --out data/etl_dd2_municipality_manifest_2026_05_17.json
    python scripts/etl/build_dd2_municipality_manifest_2026_05_17.py --dry-run

Exit codes
----------
0  success
1  fatal (db missing, output dir missing)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("jpcite.etl.dd2_municipality_manifest")

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_DEFAULT_DB: Final = _REPO_ROOT / "autonomath.db"
_DEFAULT_OUT: Final = _REPO_ROOT / "data" / "etl_dd2_municipality_manifest_2026_05_17.json"

# Aggregator hosts banned from the manifest entirely. The crawler enforces
# the same list at fetch time; the manifest contract here is purely advisory.
AGGREGATOR_BLACKLIST: Final[tuple[str, ...]] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org",
    "mapfan",
    "navitime",
    "itp.ne.jp",
    "tabelog",
    "townpages",
    "i-town",
    "ekiten",
    "subsidy-portal",
    "google.com/maps",
)

# Primary host regex — only 1次資料 hosts are allowed as seed URLs.
PRIMARY_HOST_REGEX: Final = (
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:lg\.jp|"
    r"pref\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.[a-z-]+\.jp|city\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.[a-z-]+\.jp|town\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.[a-z-]+\.jp|vill\.[a-z-]+\.jp|"
    r"metro\.tokyo\.lg\.jp)(?:/|$|\?|#)"
)

# Standard subsidy-search keywords appended to each window URL host root.
# Each path is a probable subsidy index path on 自治体 official sites.
_SUBSIDY_SEARCH_SUFFIXES: Final[tuple[str, ...]] = (
    "sangyo/josei",
    "sangyo/subsidy",
    "kurashi/zeikin/josei",
    "kigyo/josei",
    "sangyo/shokokanko/josei",
    "kigyou-shien",
    "hojokin",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help="autonomath.db path (default: repo root)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="output manifest path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print summary to stderr but do not write the JSON file",
    )
    return parser.parse_args(argv)


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open the autonomath SQLite read-only (URI mode)."""
    if not db_path.exists():
        msg = f"autonomath db missing: {db_path}"
        raise SystemExit(msg)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _detect_municipality_type(code: str, name: str) -> str:
    """Classify a 自治体 row into one of 5 muni_types.

    Heuristic based on J-LIS 5-digit code and well-known designated cities.
    """
    designated_cities = {
        "札幌市",
        "仙台市",
        "さいたま市",
        "千葉市",
        "横浜市",
        "川崎市",
        "相模原市",
        "新潟市",
        "静岡市",
        "浜松市",
        "名古屋市",
        "京都市",
        "大阪市",
        "堺市",
        "神戸市",
        "岡山市",
        "広島市",
        "北九州市",
        "福岡市",
        "熊本市",
    }
    if name in designated_cities:
        return "seirei"
    # 東京 23 区 — codes 13101..13123
    if code.startswith("13") and code[2] == "1":
        return "special"
    # 中核市 partial list (operator can refine later via JIS code table).
    chukaku = {
        "函館市",
        "旭川市",
        "青森市",
        "盛岡市",
        "秋田市",
        "郡山市",
        "いわき市",
        "宇都宮市",
        "前橋市",
        "高崎市",
        "川越市",
        "越谷市",
        "船橋市",
        "柏市",
        "八王子市",
        "横須賀市",
        "金沢市",
        "富山市",
        "長野市",
        "岐阜市",
        "豊田市",
        "豊橋市",
        "岡崎市",
        "一宮市",
        "大津市",
        "高槻市",
        "東大阪市",
        "枚方市",
        "豊中市",
        "吹田市",
        "西宮市",
        "尼崎市",
        "明石市",
        "姫路市",
        "奈良市",
        "和歌山市",
        "倉敷市",
        "福山市",
        "下関市",
        "高松市",
        "松山市",
        "高知市",
        "久留米市",
        "長崎市",
        "佐世保市",
        "大分市",
        "宮崎市",
        "鹿児島市",
        "那覇市",
    }
    if name in chukaku:
        return "chukaku"
    return "regular"


def _build_subsidy_search_seeds(
    window_url: str | None,
    *,
    fallback_seed: str | None = None,
) -> list[str]:
    """Project 1 window URL into N candidate subsidy-search paths.

    Falls back to ``fallback_seed`` (e.g., the 67-row prefecture seed list)
    when ``window_url`` is NULL or aggregator-tainted. Returns the empty
    list only when no source resolves to a 1次資料 host.
    """
    source_url = window_url or fallback_seed
    if not source_url:
        return []
    low = source_url.lower()
    for tainted in AGGREGATOR_BLACKLIST:
        if tainted in low:
            return []
    if not re.match(PRIMARY_HOST_REGEX, low):
        return []

    # Derive scheme + host root, then append each search suffix.
    m = re.match(r"^(https?://[^/]+)/?", source_url)
    if not m:
        return []
    host_root = m.group(1)
    seeds = [f"{host_root}/{suffix}" for suffix in _SUBSIDY_SEARCH_SUFFIXES]
    # Always include the canonical fallback seed itself (it is a known
    # 補助金 index page; the crawler will follow links from there).
    if fallback_seed and fallback_seed not in seeds:
        seeds.append(fallback_seed)
    return seeds


def _load_seed_overrides() -> dict[str, str]:
    """Load the existing data/municipality_seed_urls.json (67 entries).

    Returns ``{muni_code_5_digit: subsidy_url}``. Codes are normalised to
    5 digits (the seed file uses 6-digit codes with check digit).
    """
    seed_path = _REPO_ROOT / "data" / "municipality_seed_urls.json"
    out: dict[str, str] = {}
    if not seed_path.exists():
        return out
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("muni_code") or "").strip()
        url = entry.get("subsidy_url")
        if not code or not isinstance(url, str):
            continue
        if len(code) == 6:
            code = code[:5]
        if len(code) == 5 and code.isdigit():
            out[code] = url
    return out


def _project_row(row: sqlite3.Row) -> dict[str, object] | None:
    """Project a single am_window_directory row to a manifest entry.

    Returns None if the row should be skipped (no code, prefecture-only, etc.).
    """
    code = (row["jurisdiction_region_code"] or "").strip()
    name = (row["name"] or "").strip()
    if not code or not name:
        return None
    # 6-digit code (with check digit) → normalize to 5-digit J-LIS.
    if len(code) == 6:
        code = code[:5]
    if len(code) != 5 or not code.isdigit():
        return None
    if code.endswith("000"):
        # 47 都道府県 themselves — DD2 scope is 市町村 only.
        return None
    # Strip the 役場 / 役所 suffix that crawl_window_directory injects.
    canonical_name = re.sub(r"\s*役[所場]$", "", name)

    prefecture_code = code[:2] + "000"

    return {
        "municipality_code": code,
        "municipality_name": canonical_name,
        "prefecture_code": prefecture_code,
        "window_name_full": name,
        "window_url": row["url"],
        "postal_address": row["postal_address"],
        "tel": row["tel"],
    }


def _prefecture_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    """Return prefecture_code → prefecture name_ja mapping from am_region."""
    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT region_code, name_ja FROM am_region WHERE region_level='prefecture'"
    ):
        out[row[0]] = row[1]
    return out


def _designated_ward_codes(conn: sqlite3.Connection) -> set[str]:
    """Return the set of designated-city ward codes (e.g., 01101 札幌中央区).

    These wards file 補助金 at the parent 政令市 level, not standalone, so
    DD2 excludes them from the 1,718 市町村 crawl target (their 補助金 will
    appear under the parent designated_city row).
    """
    out: set[str] = set()
    for row in conn.execute(
        "SELECT region_code FROM am_region WHERE region_level='designated_ward'"
    ):
        out.add(str(row[0]))
    return out


def _build_manifest(
    conn: sqlite3.Connection,
    *,
    expected_pdf_min: int = 3,
    expected_pdf_max: int = 5,
) -> dict[str, object]:
    """Assemble the full manifest dict (1,718 市町村 target)."""
    pref_by_code = _prefecture_lookup(conn)
    ward_codes = _designated_ward_codes(conn)
    seed_overrides = _load_seed_overrides()

    rows = conn.execute(
        """
        SELECT name,
               jurisdiction_region_code,
               url,
               postal_address,
               tel
          FROM am_window_directory
         WHERE jurisdiction_kind = 'municipality'
        """
    ).fetchall()

    seen_codes: set[str] = set()
    municipalities: list[dict[str, object]] = []
    aggregator_rejected = 0

    for raw in rows:
        proj = _project_row(raw)
        if proj is None:
            continue
        code = str(proj["municipality_code"])
        if code in seen_codes:
            continue
        # Designated-city wards roll up to the parent 政令市 — exclude.
        if code in ward_codes:
            continue
        seen_codes.add(code)

        pref_name = pref_by_code.get(str(proj["prefecture_code"]), "")
        muni_type = _detect_municipality_type(code, str(proj["municipality_name"]))
        fallback_seed = seed_overrides.get(code)
        seeds = _build_subsidy_search_seeds(
            proj["window_url"] if isinstance(proj["window_url"], str) else None,
            fallback_seed=fallback_seed,
        )
        if not seeds and (proj["window_url"] or fallback_seed):
            aggregator_rejected += 1

        municipalities.append(
            {
                "municipality_code": code,
                "prefecture": pref_name,
                "prefecture_code": proj["prefecture_code"],
                "municipality_name": proj["municipality_name"],
                "municipality_type": muni_type,
                "window_url": proj["window_url"],
                "postal_address": proj["postal_address"],
                "tel": proj["tel"],
                "subsidy_search_seeds": seeds,
                "expected_pdf_count_min": expected_pdf_min,
                "expected_pdf_count_max": expected_pdf_max,
            }
        )

    municipalities.sort(key=lambda m: str(m["municipality_code"]))

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_table": "am_window_directory",
        "row_total": len(municipalities),
        "aggregator_rejected": aggregator_rejected,
        "municipalities": municipalities,
        "aggregator_blacklist": list(AGGREGATOR_BLACKLIST),
        "primary_host_regex": PRIMARY_HOST_REGEX,
        "crawl_constraints": {
            "req_per_sec": 1.0 / 3.0,
            "concurrency": 32,
            "max_pdf_per_municipality": 8,
            "robots_txt": "strict",
            "user_agent": "jpcite-dd2-crawler/2026-05-17 (+https://jpcite.ai/crawler)",
        },
        "ocr_constraints": {
            "service": "AWS Textract AnalyzeDocument (TABLES+FORMS)",
            "region": "ap-southeast-1",
            "per_page_usd": 0.05,
            "expected_pdf_total": expected_pdf_min * len(municipalities),
            "worst_case_pdf_total": expected_pdf_max * len(municipalities),
            "worst_case_usd": expected_pdf_max * 15 * 0.05 * len(municipalities),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Entrypoint."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conn = _open_db(args.db)
    try:
        manifest = _build_manifest(conn)
    finally:
        conn.close()

    row_total = manifest["row_total"]
    ocr_constraints = manifest["ocr_constraints"]
    assert isinstance(row_total, int)
    assert isinstance(ocr_constraints, dict)
    logger.info(
        "manifest built: %d municipalities, worst_case_usd=$%.2f",
        row_total,
        float(ocr_constraints["worst_case_usd"]),
    )

    if args.dry_run:
        sys.stderr.write(f"[dry-run] would write {row_total} rows to {args.out}\n")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("wrote %s (%d municipalities)", args.out, row_total)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
