#!/usr/bin/env python3
"""build_enforcement_anomaly — populate ``am_enforcement_anomaly``
(migration 161, target_db: autonomath).

Detects (prefecture × JSIC major) cells where 行政処分 incidence is
statistically abnormal relative to the 47×22 grid mean.

NO LLM. Pure SQLite + numpy z-score.

Sources (NO ATTACH; aggregate in-memory per CLAUDE.md no-cross-DB-JOIN rule):
  - data/jpintel.db: programs.jsic_majors / programs.prefecture
                     enforcement_cases (1,185 rows; prefecture present)
                     enforcement_decision_refs (program <-> case_id linkage)
  - autonomath.db:   jpi_enforcement_cases (mirror of above, prefecture present)
                     am_enforcement_detail (22,258 rows; entity_id <-> am_entities)
                     am_entities + am_entity_facts (for prefecture lookup on
                     detail rows that lack a recipient prefecture)

Cell allocation strategy:
  1) Each enforcement case is assigned to its prefecture (recipient_prefecture
     or, for am_enforcement_detail, the prefecture pulled via houjin_bangou
     <-> am_entities <-> am_region/am_entity_facts).
  2) JSIC major is derived by:
     a) joining cases to programs via enforcement_decision_refs / program_name_hint
        and reading programs.jsic_majors (authoritative when present)
     b) falling back to keyword classification on
        recipient_name + program_name_hint + reason_summary using the
        per-major synonym fence (mirrors auto_tag_program_jsic.py).
  3) Each (pref, major) cell tallies enforcement_count and the histogram of
     enforcement_kind values; dominant_violation_kind = argmax of that histogram.

Statistics:
  z = (enforcement_count - μ) / σ over ALL 47×22 = 1,034 cells (zeros included).
  anomaly_flag = 1 iff z > 2.0.

Usage:
    python scripts/etl/build_enforcement_anomaly.py            # full refresh + report
    python scripts/etl/build_enforcement_anomaly.py --dry-run  # in-memory, NO write
    python scripts/etl/build_enforcement_anomaly.py --no-report
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

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
PREF_CODE_TO_NAME: dict[str, str] = dict(PREF_CODE_NAME)

# 22 JSIC majors. A-T are the live JSU taxonomy (2014 revision, 20 codes).
# U / V are reserved-future slots — populated as zero-cells so the matrix
# is 47×22 = 1,034 per the W21 anomaly-detection spec. The schema is
# unconstrained on the JSIC side so re-binding U/V to live taxonomy
# splits (e.g. B->B/U fisheries split) re-populates without DDL.
JSIC_MAJORS: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRSTUV")  # 22 majors

# Per-major synonym fence (mirrors build_geo_industry_density.py).
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
        "土木",
        "塗装",
        "設計",
    ),
    "E": (
        "ものづくり",
        "製造",
        "設備投資",
        "工場",
        "製造業",
        "金属",
        "機械",
        "工業",
        "化学",
        "食品製造",
        "繊維",
    ),
    "F": ("電気事業", "ガス事業", "熱供給", "水道", "電力", "再エネ", "太陽光", "風力", "発電"),
    "G": (
        "情報通信",
        "IT",
        "ICT",
        "DX",
        "ソフトウェア",
        "システム開発",
        "クラウド",
        "AI",
        "IoT",
        "デジタル",
        "通信",
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
        "運送",
    ),
    "I": ("卸売", "小売", "商業", "商店", "商店街", "EC", "通信販売", "店舗", "販路開拓", "販売"),
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
        "コンサル",
    ),
    "M": ("宿泊", "飲食", "ホテル", "旅館", "民泊", "レストラン", "居酒屋", "観光", "カフェ"),
    "N": ("生活関連", "娯楽", "理容", "美容", "クリーニング", "葬祭", "スポーツクラブ", "パチンコ"),
    "O": ("教育", "学習支援", "学校", "塾", "予備校", "保育", "幼稚園", "学習塾"),
    "P": ("医療", "福祉", "病院", "診療所", "介護", "障害者", "保育所", "児童", "高齢者", "看護"),
    "Q": ("複合サービス", "郵便局", "農協", "JA"),
    "R": ("廃棄物", "リサイクル", "労働者派遣", "警備", "ビルメンテナンス", "清掃"),
    "S": ("公務", "官公庁", "市役所", "町役場", "村役場"),
    "T": ("分類不能",),
    "U": (),  # reserved future
    "V": (),  # reserved future
}

ANOMALY_Z_THRESHOLD: float = 2.0


def _parse_jsic_majors_json(raw: str | None) -> list[str]:
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
    if not text:
        return []
    hits: list[str] = []
    for major, kws in SYN.items():
        for kw in kws:
            if kw and kw in text:
                hits.append(major)
                break
    return hits


def load_program_jsic_index(jpintel_path: Path) -> dict[str, list[str]]:
    """Map program_id -> [jsic_majors] for direct enforcement->program join."""
    idx: dict[str, list[str]] = {}
    con = sqlite3.connect(f"file:{jpintel_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT unified_id, jsic_majors FROM programs "
            "WHERE excluded=0 AND tier IN ('S','A','B','C') AND jsic_majors IS NOT NULL"
        )
        for pid, raw in cur:
            majors = _parse_jsic_majors_json(raw)
            if majors:
                idx[pid] = majors
    finally:
        con.close()
    return idx


def load_enforcement_jpintel(
    jpintel_path: Path, program_jsic: dict[str, list[str]]
) -> list[tuple[str, list[str], str]]:
    """Yield (pref_code, [majors], enforcement_kind) for each jpintel case.

    Resolution order for JSIC major:
      1. enforcement_decision_refs.program_id -> programs.jsic_majors
      2. keyword fence on recipient_name + program_name_hint + reason_excerpt
    """
    out: list[tuple[str, list[str], str]] = []
    con = sqlite3.connect(f"file:{jpintel_path}?mode=ro", uri=True)
    try:
        # Pull case -> program_id linkage (may not exist; safe-fallback).
        case_to_programs: dict[str, list[str]] = defaultdict(list)
        try:
            cur = con.execute(
                "SELECT enforcement_case_id, decision_unified_id FROM enforcement_decision_refs"
            )
            for cid, pid in cur:
                if pid:
                    case_to_programs[cid].append(pid)
        except sqlite3.OperationalError:
            pass

        cur = con.execute(
            "SELECT case_id, prefecture, "
            "       COALESCE(recipient_name,'') || ' ' || "
            "       COALESCE(program_name_hint,'') || ' ' || "
            "       COALESCE(reason_excerpt,''), "
            "       COALESCE(event_type,'other') "
            "FROM enforcement_cases "
            "WHERE prefecture IS NOT NULL AND prefecture<>''"
        )
        for case_id, pref_name, text, kind in cur:
            pref_code = PREF_NAME_TO_CODE.get(pref_name)
            if pref_code is None:
                continue
            majors: list[str] = []
            for pid in case_to_programs.get(case_id, []):
                majors.extend(program_jsic.get(pid, []))
            if not majors:
                majors = _classify_text_to_jsic(text)
            majors = sorted(set(majors))
            out.append((pref_code, majors, kind or "other"))
    finally:
        con.close()
    return out


def load_enforcement_am(
    autonomath_path: Path,
) -> list[tuple[str | None, list[str], str]]:
    """Yield (pref_code|None, [majors], enforcement_kind) from am_enforcement_detail.

    Prefecture lookup chain:
      houjin_bangou -> am_entities (by canonical_id pattern + facts)
      Failing that, parse from issuing_authority text.
      Failing that, pref_code=None (case is discarded).

    JSIC: keyword fence on target_name + reason_summary + issuing_authority.
    """
    out: list[tuple[str | None, list[str], str]] = []
    con = sqlite3.connect(f"file:{autonomath_path}?mode=ro", uri=True)
    try:
        # Pre-build houjin -> prefecture map from corporate_entity facts where present.
        houjin_pref: dict[str, str] = {}
        try:
            cur = con.execute(
                "SELECT e.houjin_bangou, f.value_text "
                "FROM am_entities e "
                "JOIN am_entity_facts f ON f.entity_id = e.canonical_id "
                "WHERE e.record_kind='corporate_entity' "
                "  AND e.houjin_bangou IS NOT NULL "
                "  AND f.field_name IN ('corp.prefecture','prefecture') "
                "  AND f.value_text IS NOT NULL"
            )
            for hb, pref_name in cur:
                if hb and pref_name and pref_name in PREF_NAME_TO_CODE:
                    houjin_pref[hb] = PREF_NAME_TO_CODE[pref_name]
        except sqlite3.OperationalError:
            pass

        cur = con.execute(
            "SELECT houjin_bangou, target_name, issuing_authority, "
            "       COALESCE(reason_summary,''), enforcement_kind "
            "FROM am_enforcement_detail"
        )
        for hb, name, auth, reason, kind in cur:
            pref_code: str | None = None
            if hb and hb in houjin_pref:
                pref_code = houjin_pref[hb]
            if pref_code is None and auth:
                # Parse 'XX労働局' / 'XX県' / 'XX都' patterns.
                for nm, code in PREF_NAME_TO_CODE.items():
                    if nm in auth:
                        pref_code = code
                        break
                    # 県/府/都 stripped form (e.g. '千葉労働局' -> '千葉')
                    nm_short = nm.rstrip("県府都道")
                    if nm_short and nm_short in auth:
                        pref_code = code
                        break
            text = " ".join(filter(None, [name, reason, auth]))
            majors = _classify_text_to_jsic(text)
            majors = sorted(set(majors))
            out.append((pref_code, majors, kind or "other"))
    finally:
        con.close()
    return out


def aggregate_cells(
    jpintel_rows: list[tuple[str, list[str], str]],
    am_rows: list[tuple[str | None, list[str], str]],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], Counter]]:
    """Returns (count_map, kind_hist_map) keyed by (pref_code, jsic_major)."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    hists: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for pref_code, majors, kind in jpintel_rows:
        if not pref_code or not majors:
            continue
        for m in majors:
            if m not in JSIC_MAJORS:
                continue
            counts[(pref_code, m)] += 1
            hists[(pref_code, m)][kind] += 1
    for pref_code, majors, kind in am_rows:
        if not pref_code or not majors:
            continue
        for m in majors:
            if m not in JSIC_MAJORS:
                continue
            counts[(pref_code, m)] += 1
            hists[(pref_code, m)][kind] += 1
    return counts, hists


def compose_rows(
    counts: dict[tuple[str, str], int],
    hists: dict[tuple[str, str], Counter],
) -> list[dict[str, Any]]:
    """Compose all 47×22 = 1,034 cells (zeros included) with z + anomaly_flag."""
    raw: list[dict[str, Any]] = []
    for pref_code, _ in PREF_CODE_NAME:
        for major in JSIC_MAJORS:
            key = (pref_code, major)
            cnt = counts.get(key, 0)
            hist = hists.get(key)
            dominant = hist.most_common(1)[0][0] if hist else None
            raw.append(
                {
                    "prefecture_code": pref_code,
                    "jsic_major": major,
                    "enforcement_count": cnt,
                    "dominant_violation_kind": dominant,
                }
            )

    arr = np.array([r["enforcement_count"] for r in raw], dtype=float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=0))
    if sigma == 0:
        sigma = 1.0
    z = (arr - mu) / sigma
    for r, zi in zip(raw, z, strict=True):
        r["z_score"] = round(float(zi), 6)
        r["anomaly_flag"] = 1 if zi > ANOMALY_Z_THRESHOLD else 0
    return raw


def write_rows(autonomath_path: Path, rows: list[dict[str, Any]]) -> int:
    con = sqlite3.connect(autonomath_path)
    try:
        con.execute("BEGIN")
        con.executemany(
            """
            INSERT OR REPLACE INTO am_enforcement_anomaly
              (prefecture_code, jsic_major, enforcement_count, z_score,
               anomaly_flag, dominant_violation_kind, last_updated)
            VALUES
              (:prefecture_code, :jsic_major, :enforcement_count, :z_score,
               :anomaly_flag, :dominant_violation_kind, datetime('now'))
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


def report(rows: list[dict[str, Any]]) -> None:
    anomalies = [r for r in rows if r["anomaly_flag"] == 1]
    anomalies.sort(key=lambda r: r["z_score"], reverse=True)
    arr = np.array([r["enforcement_count"] for r in rows], dtype=float)
    print("\n=== summary ===")
    print(f"populated_cells: {len(rows)}")
    print(f"non_zero_cells:  {sum(1 for r in rows if r['enforcement_count'] > 0)}")
    print(f"sum(enforcement_count): {int(arr.sum())}")
    print(f"mean: {arr.mean():.4f}  std: {arr.std(ddof=0):.4f}")
    print(f"z-threshold: {ANOMALY_Z_THRESHOLD}  -> anomaly_cells: {len(anomalies)}")

    print(f"\n=== ANOMALIES (anomaly_flag=1, z > {ANOMALY_Z_THRESHOLD}) ===")
    print(f"{'pref':<10}{'jsic':<6}{'count':>7}{'z':>9}  dominant_kind")
    for r in anomalies:
        pref_name = PREF_CODE_TO_NAME.get(r["prefecture_code"], r["prefecture_code"])
        print(
            f"{pref_name:<10}"
            f"{r['jsic_major']:<6}"
            f"{r['enforcement_count']:>7}"
            f"{r['z_score']:>9.3f}  "
            f"{r['dominant_violation_kind'] or '-'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument(
        "--dry-run", action="store_true", help="aggregate in-memory but DO NOT write"
    )
    parser.add_argument(
        "--no-report", action="store_true", help="skip the anomaly + summary report"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("build_enforcement_anomaly")

    log.info("loading program JSIC index from %s", args.jpintel_db)
    program_jsic = load_program_jsic_index(args.jpintel_db)
    log.info("indexed %d programs with jsic_majors", len(program_jsic))

    log.info("loading enforcement_cases (jpintel)")
    jpi_rows = load_enforcement_jpintel(args.jpintel_db, program_jsic)
    log.info("  loaded %d jpintel enforcement rows", len(jpi_rows))

    log.info("loading am_enforcement_detail (autonomath)")
    am_rows = load_enforcement_am(args.autonomath_db)
    log.info("  loaded %d am_enforcement_detail rows", len(am_rows))

    counts, hists = aggregate_cells(jpi_rows, am_rows)
    log.info("aggregated into %d non-zero cells", len(counts))

    rows = compose_rows(counts, hists)
    log.info("composed %d cells (47 × %d)", len(rows), len(JSIC_MAJORS))

    if args.dry_run:
        log.info("dry-run: skipping write")
    else:
        n = write_rows(args.autonomath_db, rows)
        log.info("wrote %d cells to am_enforcement_anomaly", n)

    if not args.no_report:
        report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
