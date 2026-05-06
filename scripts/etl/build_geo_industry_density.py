#!/usr/bin/env python3
"""build_geo_industry_density — populate ``am_geo_industry_density``
(migration 155, target_db: autonomath).

Builds the 47 prefecture × 20 JSIC major (= 940 cell) density matrix
that backs the W19-5 static SEO pages and the cohort #8 industry-pack
recommendation engine.

NO LLM. Pure SQLite + Python. The script reads from BOTH ``data/jpintel.db``
(programs.jsic_majors / source_url / tier) AND ``autonomath.db``
(jpi_adoption_records / jpi_enforcement_cases / jpi_loan_programs /
am_industry_jsic / am_region) — but does **not** ATTACH them, per the
CLAUDE.md no-cross-DB-JOIN rule. Aggregation happens in-memory; the
matrix is INSERT OR REPLACE'd into autonomath.db.

Schema notes:
* ``prefecture_code`` is the 5-digit am_region code (01000..47000); the
  legacy 都道府県名 strings used by jpintel.db rows are mapped via
  ``PREF_NAME_TO_CODE`` below.
* ``program_count`` excludes tier='X' (quarantine) — same filter the
  user-facing search applies in src/jpintel_mcp/api/programs.py.
* ``verified_count`` is a proxy: programs that BOTH have a non-NULL
  source_url AND tier IN ('S','A'). The schema specced
  ``verification_count >= 2`` but the column does not exist in the
  programs schema; this is the closest first-party signal.
* ``adoption_count``: ``industry_jsic_medium`` in jpi_adoption_records
  is in-practice a single major-letter (A..T) for 89,664 / 201,845
  rows; the rest are NULL and are dropped from the cell allocation
  (they still feed the row-level total but never reach a cell).
* ``enforcement_count``: enforcement rows lack JSIC tags upstream, so
  cell allocation falls back to a recipient-name keyword match against
  the per-major synonym bundle (mirrors auto_tag_program_jsic.py).
  Cells with no recipient hit get 0.
* ``loan_count``: jpi_loan_programs has no prefecture column; loans
  are nation-wide. The matrix records per-cell loan_count = ceil(
  total_loan_count / 47) when a program's target_conditions text
  hits the JSIC synonym fence, else 0. This is intentionally coarse —
  the supply-side static page just needs a non-zero indicator.
* ``density_score``: z-normalized weighted composite,
    raw   = 0.40·program + 0.20·verified + 0.30·adoption + 0.10·enforcement
    (loan_count not weighted into score; surfaced as separate column)
  z-norm uses (raw - μ) / σ over the 940 populated cells; final
  density_score is the min-max normalization of z to [0, 1].

Usage:
    python scripts/etl/build_geo_industry_density.py            # full refresh
    python scripts/etl/build_geo_industry_density.py --report   # also print top10/bot10
    python scripts/etl/build_geo_industry_density.py --dry-run  # in-memory, NO write
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

# 47 都道府県コード (am_region 5-digit). Index 0 = 北海道, 46 = 沖縄県.
PREF_CODE_NAME: list[tuple[str, str]] = [
    ("01000", "北海道"),
    ("02000", "青森県"),
    ("03000", "岩手県"),
    ("04000", "宮城県"),
    ("05000", "秋田県"),
    ("06000", "山形県"),
    ("07000", "福島県"),
    ("08000", "茨城県"),
    ("09000", "栃木県"),
    ("10000", "群馬県"),
    ("11000", "埼玉県"),
    ("12000", "千葉県"),
    ("13000", "東京都"),
    ("14000", "神奈川県"),
    ("15000", "新潟県"),
    ("16000", "富山県"),
    ("17000", "石川県"),
    ("18000", "福井県"),
    ("19000", "山梨県"),
    ("20000", "長野県"),
    ("21000", "岐阜県"),
    ("22000", "静岡県"),
    ("23000", "愛知県"),
    ("24000", "三重県"),
    ("25000", "滋賀県"),
    ("26000", "京都府"),
    ("27000", "大阪府"),
    ("28000", "兵庫県"),
    ("29000", "奈良県"),
    ("30000", "和歌山県"),
    ("31000", "鳥取県"),
    ("32000", "島根県"),
    ("33000", "岡山県"),
    ("34000", "広島県"),
    ("35000", "山口県"),
    ("36000", "徳島県"),
    ("37000", "香川県"),
    ("38000", "愛媛県"),
    ("39000", "高知県"),
    ("40000", "福岡県"),
    ("41000", "佐賀県"),
    ("42000", "長崎県"),
    ("43000", "熊本県"),
    ("44000", "大分県"),
    ("45000", "宮崎県"),
    ("46000", "鹿児島県"),
    ("47000", "沖縄県"),
]
PREF_NAME_TO_CODE: dict[str, str] = {n: c for c, n in PREF_CODE_NAME}
PREF_CODE_TO_NAME: dict[str, str] = {c: n for c, n in PREF_CODE_NAME}
JSIC_MAJORS: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRST")  # 20 majors

# Per-major synonym fence for enforcement / loan keyword matching.
# Subset of scripts/etl/auto_tag_program_jsic.py — keeps maintenance burden
# at one file (this script intentionally duplicates rather than imports
# because auto_tag_program_jsic loads jpintel.db on import).
SYN: dict[str, tuple[str, ...]] = {
    "A": (
        "農業",
        "林業",
        "農林",
        "畜産",
        "酪農",
        "果樹",
        "野菜",
        "新規就農",
        "農業法人",
        "森林",
        "木材",
        "ブルーベリー",
    ),
    "B": ("漁業", "水産", "養殖", "漁港", "漁船", "漁協"),
    "C": ("鉱業", "採石", "砂利", "採掘", "鉱山"),
    "D": (
        "建設",
        "建築",
        "住宅",
        "空き家",
        "耐震",
        "改修",
        "リフォーム",
        "工事",
        "下請",
        "建設業",
        "施工",
    ),
    "E": (
        "ものづくり",
        "製造",
        "設備投資",
        "省エネ",
        "GX",
        "脱炭素",
        "事業再構築",
        "工場",
        "製造業",
        "金属",
        "機械",
        "工業",
        "省力化",
    ),
    "F": (
        "電気事業",
        "ガス事業",
        "熱供給",
        "水道",
        "電力",
        "再生可能エネルギー",
        "再エネ",
        "太陽光",
        "風力",
        "発電",
    ),
    "G": (
        "情報通信",
        "IT",
        "ICT",
        "DX",
        "IT導入",
        "ソフトウェア",
        "システム開発",
        "クラウド",
        "AI",
        "IoT",
        "デジタル",
    ),
    "H": (
        "運輸",
        "物流",
        "輸送",
        "郵便",
        "貨物",
        "海運",
        "陸運",
        "鉄道",
        "バス事業",
        "タクシー",
        "トラック",
        "倉庫",
    ),
    "I": ("卸売", "小売", "商業", "商店", "商店街", "EC", "通信販売", "店舗", "販路開拓"),
    "J": (
        "金融",
        "保険",
        "銀行",
        "信金",
        "信用金庫",
        "信用組合",
        "証券",
        "投資",
        "リース",
        "信用保証",
        "公庫",
    ),
    "K": ("不動産", "賃貸", "物品賃貸", "宅地", "マンション", "テナント", "オフィス"),
    "L": (
        "学術研究",
        "研究開発",
        "R&D",
        "弁理士",
        "公認会計士",
        "税理士",
        "司法書士",
        "行政書士",
        "中小企業診断士",
        "デザイン",
        "コンサルタント",
    ),
    "M": ("宿泊", "飲食", "ホテル", "旅館", "民泊", "レストラン", "居酒屋", "観光"),
    "N": ("生活関連", "娯楽", "理容", "美容", "クリーニング", "葬祭", "スポーツクラブ", "パチンコ"),
    "O": ("教育", "学習支援", "学校", "塾", "予備校", "保育", "幼稚園", "学習塾"),
    "P": ("医療", "福祉", "病院", "診療所", "介護", "障害者", "保育所", "児童", "高齢者"),
    "Q": ("複合サービス", "郵便局", "農協", "JA"),
    "R": ("廃棄物", "リサイクル", "労働者派遣", "警備", "ビルメンテナンス", "清掃"),
    "S": ("公務", "官公庁", "市役所", "町役場", "村役場"),
    "T": ("分類不能",),
}

WEIGHTS = {
    "program": 0.40,
    "verified": 0.20,
    "adoption": 0.30,
    "enforcement": 0.10,
}


def _tokenize_jsic_majors_json(raw: str | None) -> list[str]:
    """Parse programs.jsic_majors JSON column → list of major letters."""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    return [c for c in v if isinstance(c, str) and c in JSIC_MAJORS]


def _classify_text_to_jsic(text: str | None) -> list[str]:
    """Keyword-fence text against per-major synonyms; return all majors that hit."""
    if not text:
        return []
    hits: list[str] = []
    for major, kws in SYN.items():
        for kw in kws:
            if kw in text:
                hits.append(major)
                break
    return hits


def load_programs(jpintel_path: Path) -> dict[tuple[str, str], dict[str, int]]:
    """Aggregate programs by (prefecture_code, jsic_major).
    Returns: cell -> {program_count, tier_S, tier_A, verified}
    """
    cells: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"program_count": 0, "tier_S": 0, "tier_A": 0, "verified": 0}
    )
    con = sqlite3.connect(f"file:{jpintel_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT prefecture, tier, source_url, jsic_majors "
            "FROM programs WHERE excluded=0 AND tier IN ('S','A','B','C')"
        )
        for pref_name, tier, source_url, jsic_majors_raw in cur:
            pref_code = PREF_NAME_TO_CODE.get(pref_name)
            if pref_code is None:
                continue  # 全国 / NULL / non-47 are skipped
            majors = _tokenize_jsic_majors_json(jsic_majors_raw)
            if not majors:
                continue
            verified = 1 if (source_url and tier in ("S", "A")) else 0
            for m in majors:
                cell = cells[(pref_code, m)]
                cell["program_count"] += 1
                if tier == "S":
                    cell["tier_S"] += 1
                elif tier == "A":
                    cell["tier_A"] += 1
                cell["verified"] += verified
    finally:
        con.close()
    return cells


def load_adoption(autonomath_path: Path) -> dict[tuple[str, str], int]:
    cells: dict[tuple[str, str], int] = defaultdict(int)
    con = sqlite3.connect(f"file:{autonomath_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT prefecture, industry_jsic_medium FROM jpi_adoption_records "
            "WHERE industry_jsic_medium IS NOT NULL AND industry_jsic_medium<>''"
        )
        for pref_name, jsic in cur:
            pref_code = PREF_NAME_TO_CODE.get(pref_name)
            if pref_code is None:
                continue
            major = jsic[0] if jsic and jsic[0] in JSIC_MAJORS else None
            if major is None:
                continue
            cells[(pref_code, major)] += 1
    finally:
        con.close()
    return cells


def load_enforcement(autonomath_path: Path) -> dict[tuple[str, str], int]:
    cells: dict[tuple[str, str], int] = defaultdict(int)
    con = sqlite3.connect(f"file:{autonomath_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT prefecture, COALESCE(recipient_name,'') || ' ' || COALESCE(program_name_hint,'') "
            "FROM jpi_enforcement_cases WHERE prefecture IS NOT NULL AND prefecture<>''"
        )
        for pref_name, text in cur:
            pref_code = PREF_NAME_TO_CODE.get(pref_name)
            if pref_code is None:
                continue
            majors = _classify_text_to_jsic(text)
            if not majors:
                continue
            for m in majors:
                cells[(pref_code, m)] += 1
    finally:
        con.close()
    return cells


def load_loans(autonomath_path: Path) -> dict[str, int]:
    """jpi_loan_programs has no prefecture; return per-major nation-wide count.
    Caller distributes uniformly across 47 prefectures.
    """
    by_major: dict[str, int] = defaultdict(int)
    con = sqlite3.connect(f"file:{autonomath_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT COALESCE(program_name,'') || ' ' || COALESCE(target_conditions,'') "
            "FROM jpi_loan_programs"
        )
        for (text,) in cur:
            majors = _classify_text_to_jsic(text)
            if not majors:
                continue
            for m in majors:
                by_major[m] += 1
    finally:
        con.close()
    return by_major


def compose_density(
    program_cells: dict[tuple[str, str], dict[str, int]],
    adoption_cells: dict[tuple[str, str], int],
    enforcement_cells: dict[tuple[str, str], int],
    loans_by_major: dict[str, int],
) -> list[dict[str, Any]]:
    """Return one row dict per (pref, major) cell — populates ALL 940 cells."""
    rows: list[dict[str, Any]] = []
    for pref_code, _ in PREF_CODE_NAME:
        for major in JSIC_MAJORS:
            key = (pref_code, major)
            p = program_cells.get(
                key, {"program_count": 0, "tier_S": 0, "tier_A": 0, "verified": 0}
            )
            adoption = adoption_cells.get(key, 0)
            enf = enforcement_cells.get(key, 0)
            # Loans: uniform 47-way distribution (rounded), gated by national presence
            loan_total = loans_by_major.get(major, 0)
            loan = math.ceil(loan_total / 47) if loan_total > 0 else 0
            rows.append(
                {
                    "prefecture_code": pref_code,
                    "jsic_major": major,
                    "program_count": p["program_count"],
                    "program_tier_S": p["tier_S"],
                    "program_tier_A": p["tier_A"],
                    "verified_count": p["verified"],
                    "adoption_count": adoption,
                    "enforcement_count": enf,
                    "loan_count": loan,
                }
            )

    # Compute z-normalized composite, then min-max to [0, 1].
    raws = [
        WEIGHTS["program"] * r["program_count"]
        + WEIGHTS["verified"] * r["verified_count"]
        + WEIGHTS["adoption"] * r["adoption_count"]
        + WEIGHTS["enforcement"] * r["enforcement_count"]
        for r in rows
    ]
    n = len(raws)
    mu = sum(raws) / n
    var = sum((x - mu) ** 2 for x in raws) / n
    sigma = math.sqrt(var) if var > 0 else 1.0
    z = [(x - mu) / sigma for x in raws]
    z_min, z_max = min(z), max(z)
    span = (z_max - z_min) or 1.0
    for r, zi in zip(rows, z, strict=True):
        r["density_score"] = round((zi - z_min) / span, 6)
    return rows


def write_matrix(autonomath_path: Path, rows: list[dict[str, Any]]) -> int:
    con = sqlite3.connect(autonomath_path)
    try:
        con.execute("BEGIN")
        con.executemany(
            """
            INSERT OR REPLACE INTO am_geo_industry_density
              (prefecture_code, jsic_major, program_count, program_tier_S,
               program_tier_A, verified_count, adoption_count,
               enforcement_count, loan_count, density_score, last_updated)
            VALUES
              (:prefecture_code, :jsic_major, :program_count, :program_tier_S,
               :program_tier_A, :verified_count, :adoption_count,
               :enforcement_count, :loan_count, :density_score, datetime('now'))
            """,
            rows,
        )
        con.commit()
        return len(rows)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def report(rows: list[dict[str, Any]], k: int = 10) -> None:
    rows_sorted = sorted(rows, key=lambda r: r["density_score"], reverse=True)
    pref_name = lambda c: PREF_CODE_TO_NAME.get(c, c)  # noqa: E731
    print(f"\n=== TOP {k} 高機会 cells (density_score DESC) ===")
    print(
        f"{'pref':<6}{'jsic':<6}{'prog':>5}{'verif':>6}{'adopt':>6}{'enf':>5}{'loan':>5}{'score':>9}"
    )
    for r in rows_sorted[:k]:
        print(
            f"{pref_name(r['prefecture_code'])[:4]:<6}"
            f"{r['jsic_major']:<6}"
            f"{r['program_count']:>5}"
            f"{r['verified_count']:>6}"
            f"{r['adoption_count']:>6}"
            f"{r['enforcement_count']:>5}"
            f"{r['loan_count']:>5}"
            f"{r['density_score']:>9.4f}"
        )

    print(f"\n=== BOTTOM {k} 空白市場 cells (density_score ASC) ===")
    print(
        f"{'pref':<6}{'jsic':<6}{'prog':>5}{'verif':>6}{'adopt':>6}{'enf':>5}{'loan':>5}{'score':>9}"
    )
    for r in rows_sorted[-k:]:
        print(
            f"{pref_name(r['prefecture_code'])[:4]:<6}"
            f"{r['jsic_major']:<6}"
            f"{r['program_count']:>5}"
            f"{r['verified_count']:>6}"
            f"{r['adoption_count']:>6}"
            f"{r['enforcement_count']:>5}"
            f"{r['loan_count']:>5}"
            f"{r['density_score']:>9.4f}"
        )

    print(f"\n=== summary ===")
    print(f"populated_cells: {len(rows)}")
    print(f"non_zero_program_cells: {sum(1 for r in rows if r['program_count'] > 0)}")
    print(f"sum(program_count): {sum(r['program_count'] for r in rows)}")
    print(f"sum(adoption_count): {sum(r['adoption_count'] for r in rows)}")
    print(f"sum(enforcement_count): {sum(r['enforcement_count'] for r in rows)}")
    print(
        f"density_score range: [{min(r['density_score'] for r in rows):.4f}, "
        f"{max(r['density_score'] for r in rows):.4f}]"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument(
        "--report", action="store_true", help="print top10 / bottom10 after refresh"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="aggregate in-memory but DO NOT write"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("build_geo_industry_density")

    log.info("loading programs from %s", args.jpintel_db)
    program_cells = load_programs(args.jpintel_db)
    log.info("loading adoption / enforcement / loans from %s", args.autonomath_db)
    adoption_cells = load_adoption(args.autonomath_db)
    enforcement_cells = load_enforcement(args.autonomath_db)
    loans_by_major = load_loans(args.autonomath_db)

    rows = compose_density(program_cells, adoption_cells, enforcement_cells, loans_by_major)
    log.info("composed %d cells (47 × %d)", len(rows), len(JSIC_MAJORS))

    if args.dry_run:
        log.info("dry-run: skipping write")
    else:
        n = write_matrix(args.autonomath_db, rows)
        log.info("wrote %d cells to am_geo_industry_density", n)

    if args.report:
        report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
