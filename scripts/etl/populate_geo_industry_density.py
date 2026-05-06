#!/usr/bin/env python3
"""
Populate am_geo_industry_density (47 prefecture × 22 JSIC major = 1,034 cells).

Pure SQL aggregation, NO LLM, NO API calls. Idempotent: INSERT OR REPLACE.

Sources:
  * jpi_programs           - program_count, program_tier_S/A, verified_count
  * jpi_adoption_records   - adoption_count (exact prefecture × JSIC medium prefix)
  * jpi_enforcement_cases  - enforcement_count (prefecture only; no JSIC, broadcast to 'U')
  * jpi_loan_programs      - loan_count (no prefecture/JSIC; counted under ('00','V'))

JSIC mapping for programs (no direct linkage exists in jpi_pc_industry_jsic_to_program):
  Heuristic keyword match on programs.primary_name. Each program is assigned the
  best-matching JSIC major (single-class). Unmatched -> 'U'. Prefecture='全国' -> 'V' bucket.

Density score = z-normalized weighted sum of (program_count, adoption_count,
enforcement_count, verified_count, loan_count). Computed in a second pass.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# JSIC major keyword fence. Order matters - first match wins per program.
# Keyword sets were curated from CLAUDE.md industry-pack vocab + JSIC official labels.
JSIC_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("A", ("農", "林", "畜産", "酪農", "果樹", "花卉", "新規就農", "園芸", "養蚕")),
    ("B", ("漁業", "水産", "養殖", "漁港", "漁船")),
    ("C", ("鉱業", "採石", "砂利", "石灰")),
    ("D", ("建設", "建築", "住宅", "耐震", "改修", "工事", "下請", "解体", "舗装", "造園")),
    (
        "E",
        (
            "製造",
            "ものづくり",
            "設備投資",
            "工場",
            "機械",
            "金属",
            "化学",
            "繊維",
            "食品加工",
            "省エネ",
            "GX",
            "脱炭素",
            "事業再構築",
            "DX",
        ),
    ),
    ("F", ("電気", "ガス", "熱供給", "水道", "発電", "送電")),
    ("G", ("情報通信", "IT", "ソフトウェア", "ITSM", "ITコーディネータ", "通信", "放送")),
    ("H", ("運輸", "郵便", "物流", "運送", "配送", "トラック", "鉄道", "海運", "航空", "倉庫")),
    ("I", ("卸売", "小売", "EC", "物販", "店舗")),
    ("J", ("金融", "保険", "信用保証", "投資", "証券")),
    ("K", ("不動産", "賃貸", "空き家", "流通")),
    ("L", ("学術", "研究開発", "コンサル", "技術サービス", "設計", "デザイン")),
    ("M", ("宿泊", "旅館", "ホテル", "飲食", "レストラン", "カフェ", "民泊")),
    ("N", ("生活関連", "理美容", "クリーニング", "娯楽", "スポーツ", "観光")),
    ("O", ("教育", "学習支援", "保育", "幼児", "学校", "塾", "研修")),
    ("P", ("医療", "福祉", "介護", "病院", "診療所", "障害", "高齢")),
    ("Q", ("複合サービス", "農協", "漁協", "郵便局")),
    ("R", ("サービス業", "労働者派遣", "メンテナンス", "警備", "清掃")),
    ("S", ("公務", "自治体", "地方公共団体")),
    ("T", ("分類不能",)),
]

# 47 prefectures (JIS X 0401 2-digit code → name) per am_region.
PREF_CODES: list[tuple[str, str]] = [
    ("01", "北海道"),
    ("02", "青森県"),
    ("03", "岩手県"),
    ("04", "宮城県"),
    ("05", "秋田県"),
    ("06", "山形県"),
    ("07", "福島県"),
    ("08", "茨城県"),
    ("09", "栃木県"),
    ("10", "群馬県"),
    ("11", "埼玉県"),
    ("12", "千葉県"),
    ("13", "東京都"),
    ("14", "神奈川県"),
    ("15", "新潟県"),
    ("16", "富山県"),
    ("17", "石川県"),
    ("18", "福井県"),
    ("19", "山梨県"),
    ("20", "長野県"),
    ("21", "岐阜県"),
    ("22", "静岡県"),
    ("23", "愛知県"),
    ("24", "三重県"),
    ("25", "滋賀県"),
    ("26", "京都府"),
    ("27", "大阪府"),
    ("28", "兵庫県"),
    ("29", "奈良県"),
    ("30", "和歌山県"),
    ("31", "鳥取県"),
    ("32", "島根県"),
    ("33", "岡山県"),
    ("34", "広島県"),
    ("35", "山口県"),
    ("36", "徳島県"),
    ("37", "香川県"),
    ("38", "愛媛県"),
    ("39", "高知県"),
    ("40", "福岡県"),
    ("41", "佐賀県"),
    ("42", "長崎県"),
    ("43", "熊本県"),
    ("44", "大分県"),
    ("45", "宮崎県"),
    ("46", "鹿児島県"),
    ("47", "沖縄県"),
]
JSIC_MAJORS: list[str] = [j for j, _ in JSIC_KEYWORDS] + ["U", "V"]
assert len(PREF_CODES) == 47
assert len(JSIC_MAJORS) == 22


def classify_program(name: str | None) -> str:
    """Return JSIC major code best matching this program name. 'U' if none."""
    if not name:
        return "U"
    for jsic, kws in JSIC_KEYWORDS:
        for kw in kws:
            if kw in name:
                return jsic
    return "U"


def populate(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # name -> code lookup
    name_to_code = {n: c for c, n in PREF_CODES}

    # Initialize all 1,034 cells to zero (idempotent baseline).
    cur.executemany(
        """
        INSERT OR REPLACE INTO am_geo_industry_density
            (prefecture_code, jsic_major, program_count,
             program_tier_S, program_tier_A,
             verified_count, adoption_count, enforcement_count,
             loan_count, density_score, last_updated)
        VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, NULL, datetime('now'))
        """,
        [(pc, jm) for pc, _ in PREF_CODES for jm in JSIC_MAJORS],
    )

    # === programs aggregation ===
    # Pull all live (excluded=0) programs; classify each into one JSIC major.
    cur.execute(
        """
        SELECT prefecture, primary_name, tier, source_last_check_status
          FROM jpi_programs
         WHERE excluded = 0
        """
    )
    pref_jsic_counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in cur.fetchall():
        pref_name = row["prefecture"] or ""
        # 全国 -> V (horizontal); unknown pref -> skip.
        if pref_name == "全国":
            # Broadcast to V bucket of every prefecture (one row per pref).
            for pc, _ in PREF_CODES:
                bucket = pref_jsic_counts.setdefault(
                    (pc, "V"), {"n": 0, "S": 0, "A": 0, "verified": 0}
                )
                bucket["n"] += 1
                if row["tier"] == "S":
                    bucket["S"] += 1
                elif row["tier"] == "A":
                    bucket["A"] += 1
                if row["source_last_check_status"] == 200:
                    bucket["verified"] += 1
            continue
        pref_code = name_to_code.get(pref_name)
        if not pref_code:
            continue
        jsic = classify_program(row["primary_name"])
        bucket = pref_jsic_counts.setdefault(
            (pref_code, jsic), {"n": 0, "S": 0, "A": 0, "verified": 0}
        )
        bucket["n"] += 1
        if row["tier"] == "S":
            bucket["S"] += 1
        elif row["tier"] == "A":
            bucket["A"] += 1
        if row["source_last_check_status"] == 200:
            bucket["verified"] += 1

    # === adoption aggregation ===
    cur.execute(
        """
        SELECT prefecture, industry_jsic_medium
          FROM jpi_adoption_records
         WHERE prefecture IS NOT NULL
        """
    )
    adoption_counts: dict[tuple[str, str], int] = {}
    for row in cur.fetchall():
        pref_name = row["prefecture"]
        # adoption "prefecture" can be raw text like "東京" - normalize to map.
        # try exact, then add 県/府/都/道 suffix variants.
        pc = name_to_code.get(pref_name)
        if not pc:
            for suffix in ("県", "府", "都", "道"):
                pc = name_to_code.get(pref_name + suffix)
                if pc:
                    break
        if not pc:
            continue
        # JSIC medium prefix (e.g. "01" -> "A" via parent walk; here just take first letter
        # of the medium code if alphabetical, else look up parent in am_industry_jsic).
        med = (row["industry_jsic_medium"] or "").strip()
        jsic_major = "U"
        if med:
            if med[0].isalpha():
                jsic_major = med[0].upper()
                if jsic_major not in JSIC_MAJORS:
                    jsic_major = "U"
            else:
                # numeric medium - look up parent major in seed table
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT parent_code FROM am_industry_jsic WHERE jsic_code=?",
                    (med,),
                )
                r = cur2.fetchone()
                if r and r["parent_code"] in JSIC_MAJORS:
                    jsic_major = r["parent_code"]
        adoption_counts[(pc, jsic_major)] = adoption_counts.get((pc, jsic_major), 0) + 1

    # === enforcement aggregation (prefecture only, JSIC unknown -> 'U') ===
    cur.execute(
        """
        SELECT prefecture, COUNT(*) AS n
          FROM jpi_enforcement_cases
         WHERE prefecture IS NOT NULL
         GROUP BY prefecture
        """
    )
    enforcement_counts: dict[tuple[str, str], int] = {}
    for row in cur.fetchall():
        pref_name = row["prefecture"]
        pc = name_to_code.get(pref_name)
        if not pc:
            for suffix in ("県", "府", "都", "道"):
                pc = name_to_code.get(pref_name + suffix)
                if pc:
                    break
        if not pc:
            continue
        enforcement_counts[(pc, "U")] = enforcement_counts.get((pc, "U"), 0) + row["n"]

    # === loan aggregation (no pref/JSIC; broadcast to ('01','V') as nation-level proxy) ===
    cur.execute("SELECT COUNT(*) AS n FROM jpi_loan_programs")
    total_loans = cur.fetchone()["n"]

    # === merge into density table ===
    update_rows: list[tuple] = []
    for pc, _ in PREF_CODES:
        for jm in JSIC_MAJORS:
            p = pref_jsic_counts.get((pc, jm), {"n": 0, "S": 0, "A": 0, "verified": 0})
            update_rows.append(
                (
                    p["n"],
                    p["S"],
                    p["A"],
                    p["verified"],
                    adoption_counts.get((pc, jm), 0),
                    enforcement_counts.get((pc, jm), 0),
                    total_loans
                    if (pc, jm) == ("13", "V")
                    else 0,  # Tokyo V bucket holds nation loans
                    pc,
                    jm,
                )
            )
    cur.executemany(
        """
        UPDATE am_geo_industry_density
           SET program_count     = ?,
               program_tier_S    = ?,
               program_tier_A    = ?,
               verified_count    = ?,
               adoption_count    = ?,
               enforcement_count = ?,
               loan_count        = ?,
               last_updated      = datetime('now')
         WHERE prefecture_code = ?
           AND jsic_major      = ?
        """,
        update_rows,
    )

    # === density_score: z-normalized weighted sum ===
    # weight: program 1.0, adoption 0.5, enforcement 0.5 (negative weight - bad signal),
    # verified 0.3, loan 0.2.
    # First compute means + stddev for each metric across the 1,034 cells.
    cur.execute(
        """
        SELECT AVG(program_count)     AS p_mu,
               AVG(adoption_count)    AS a_mu,
               AVG(enforcement_count) AS e_mu,
               AVG(verified_count)    AS v_mu,
               AVG(loan_count)        AS l_mu
          FROM am_geo_industry_density
        """
    )
    mu = cur.fetchone()
    cur.execute(
        """
        SELECT
          AVG((program_count - ?) * (program_count - ?))         AS p_var,
          AVG((adoption_count - ?) * (adoption_count - ?))       AS a_var,
          AVG((enforcement_count - ?) * (enforcement_count - ?)) AS e_var,
          AVG((verified_count - ?) * (verified_count - ?))       AS v_var,
          AVG((loan_count - ?) * (loan_count - ?))               AS l_var
        FROM am_geo_industry_density
        """,
        (
            mu["p_mu"],
            mu["p_mu"],
            mu["a_mu"],
            mu["a_mu"],
            mu["e_mu"],
            mu["e_mu"],
            mu["v_mu"],
            mu["v_mu"],
            mu["l_mu"],
            mu["l_mu"],
        ),
    )
    var = cur.fetchone()
    p_sd = (var["p_var"] or 0) ** 0.5 or 1.0
    a_sd = (var["a_var"] or 0) ** 0.5 or 1.0
    e_sd = (var["e_var"] or 0) ** 0.5 or 1.0
    v_sd = (var["v_var"] or 0) ** 0.5 or 1.0
    l_sd = (var["l_var"] or 0) ** 0.5 or 1.0

    cur.execute(
        """
        UPDATE am_geo_industry_density
           SET density_score =
                  1.0 * ((program_count     - ?) / ?)
                + 0.5 * ((adoption_count    - ?) / ?)
                - 0.5 * ((enforcement_count - ?) / ?)
                + 0.3 * ((verified_count    - ?) / ?)
                + 0.2 * ((loan_count        - ?) / ?)
        """,
        (mu["p_mu"], p_sd, mu["a_mu"], a_sd, mu["e_mu"], e_sd, mu["v_mu"], v_sd, mu["l_mu"], l_sd),
    )

    conn.commit()
    cur.execute("SELECT COUNT(*) AS n FROM am_geo_industry_density")
    n_total = cur.fetchone()["n"]
    cur.execute(
        "SELECT COUNT(*) AS n FROM am_geo_industry_density WHERE program_count>0 OR adoption_count>0 OR enforcement_count>0"
    )
    n_nonzero = cur.fetchone()["n"]
    conn.close()

    return {"total_cells": n_total, "nonzero_cells": n_nonzero}


def report(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    pref_name = {c: n for c, n in PREF_CODES}
    jsic_name: dict[str, str] = {}
    for r in conn.execute(
        "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic WHERE jsic_level='major'"
    ):
        jsic_name[r["jsic_code"]] = r["jsic_name_ja"]

    out: list[str] = []
    out.append("=== TOP 10 (highest density_score) ===")
    for r in cur.execute(
        """
        SELECT prefecture_code, jsic_major, program_count,
               adoption_count, enforcement_count, density_score
          FROM am_geo_industry_density
         ORDER BY density_score DESC LIMIT 10
        """
    ):
        out.append(
            f"  {pref_name.get(r['prefecture_code'], '?'):<6} {r['jsic_major']} "
            f"{jsic_name.get(r['jsic_major'], '?'):<14} "
            f"prog={r['program_count']:<5} adopt={r['adoption_count']:<6} "
            f"enf={r['enforcement_count']:<4} score={r['density_score']:.3f}"
        )
    out.append("")
    out.append("=== BOTTOM 10 (lowest density_score) ===")
    for r in cur.execute(
        """
        SELECT prefecture_code, jsic_major, program_count,
               adoption_count, enforcement_count, density_score
          FROM am_geo_industry_density
         ORDER BY density_score ASC LIMIT 10
        """
    ):
        out.append(
            f"  {pref_name.get(r['prefecture_code'], '?'):<6} {r['jsic_major']} "
            f"{jsic_name.get(r['jsic_major'], '?'):<14} "
            f"prog={r['program_count']:<5} adopt={r['adoption_count']:<6} "
            f"enf={r['enforcement_count']:<4} score={r['density_score']:.3f}"
        )
    conn.close()
    return "\n".join(out)


def main() -> int:
    db_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/Users/shigetoumeda/jpcite/autonomath.db")
    )
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1
    stats = populate(db_path)
    print(f"populated cells: total={stats['total_cells']} nonzero={stats['nonzero_cells']}")
    print()
    print(report(db_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
