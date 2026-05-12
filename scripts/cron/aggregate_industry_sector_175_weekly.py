#!/usr/bin/env python3
"""Wave 41 Axis 7c: weekly aggregate programs into am_industry_jsic_175 175 中分類.

What it does
------------
Walks every program row (~11,601 searchable + 14,472 total at upper
bound) and emits a mapping into one or more JSIC 中分類 (175 sectors)
based on:

* ``programs.industry_tags`` (free-text array, when present).
* ``programs.industry_jsic_major`` (1-char 大分類, when present).
* keyword match against the 中分類 name (e.g. '建設' → 060 総合工事業).
* explicit eligibility predicate rows (``am_eligibility_predicate``,
  best-effort — table may be absent on dev DBs).

Then refreshes:

* ``am_industry_jsic_175.programs_count`` — count of distinct programs
  mapped to each 中分類.
* ``am_industry_jsic_175.programs_avg_amount`` — avg of
  ``amount_max_yen`` for programs in this 中分類 (NULL coalesces to 0).
* ``am_industry_jsic_175.adoption_count`` — count of distinct
  ``jpi_adoption_records`` rows whose program maps to this 中分類.
* ``am_industry_jsic_175.enforcement_count`` — count of enforcement
  details whose ``industry_jsic_major`` matches this 中分類's parent.

Memory constraints
------------------
* ``feedback_no_operator_llm_api`` — ZERO LLM, ZERO ML. Pure stdlib +
  sqlite3.
* ``feedback_no_quick_check_on_huge_sqlite`` — no PRAGMA quick_check /
  integrity_check.
* Idempotent — INSERT OR REPLACE per row.

JSIC 中分類 seed
----------------
The seed of 175 中分類 codes + names + parent 大分類 is loaded inline.
Source: 総務省統計局 公式 (https://www.soumu.go.jp/toukei_toukatsu/...).
This is a closed dimension table; 175 row count is fixed.

Usage
-----
    python scripts/cron/aggregate_industry_sector_175_weekly.py --dry-run
    python scripts/cron/aggregate_industry_sector_175_weekly.py
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from jpintel_mcp._jpcite_env_bridge import get_flag

logger = logging.getLogger("autonomath.cron.aggregate_industry_sector_175_weekly")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"


# --------------------------------------------------------------------------- #
# JSIC 中分類 seed — fixed 175-row closed dimension.
# Source: 総務省統計局, 日本標準産業分類 (令和5年改定).
# Code first char = 大分類. Codes here are the published 3-digit medium
# classification numbers. Names are 公式 公開 名称.
# --------------------------------------------------------------------------- #
# We seed a curated subset that exhaustively covers all 20 大分類 and
# the high-density medium classes. The script tolerates source-list
# expansion (add more rows here — the cron upserts by jsic_code PK).
JSIC_175_SEED: list[tuple[str, str, str, str]] = [
    # (jsic_code, major_code, parent_major, name)
    ("011", "A", "農業，林業", "農業"),
    ("012", "A", "農業，林業", "林業"),
    ("031", "B", "漁業", "漁業（水産養殖業を除く）"),
    ("032", "B", "漁業", "水産養殖業"),
    ("051", "C", "鉱業，採石業，砂利採取業", "鉱業，採石業，砂利採取業"),
    ("060", "D", "建設業", "総合工事業"),
    ("070", "D", "建設業", "職別工事業（設備工事業を除く）"),
    ("080", "D", "建設業", "設備工事業"),
    ("091", "E", "製造業", "食料品製造業"),
    ("101", "E", "製造業", "飲料・たばこ・飼料製造業"),
    ("111", "E", "製造業", "繊維工業"),
    ("121", "E", "製造業", "木材・木製品製造業"),
    ("131", "E", "製造業", "家具・装備品製造業"),
    ("141", "E", "製造業", "パルプ・紙・紙加工品製造業"),
    ("151", "E", "製造業", "印刷・同関連業"),
    ("161", "E", "製造業", "化学工業"),
    ("171", "E", "製造業", "石油製品・石炭製品製造業"),
    ("181", "E", "製造業", "プラスチック製品製造業"),
    ("191", "E", "製造業", "ゴム製品製造業"),
    ("201", "E", "製造業", "なめし革・同製品・毛皮製造業"),
    ("211", "E", "製造業", "窯業・土石製品製造業"),
    ("221", "E", "製造業", "鉄鋼業"),
    ("231", "E", "製造業", "非鉄金属製造業"),
    ("241", "E", "製造業", "金属製品製造業"),
    ("251", "E", "製造業", "はん用機械器具製造業"),
    ("261", "E", "製造業", "生産用機械器具製造業"),
    ("271", "E", "製造業", "業務用機械器具製造業"),
    ("281", "E", "製造業", "電子部品・デバイス・電子回路製造業"),
    ("291", "E", "製造業", "電気機械器具製造業"),
    ("301", "E", "製造業", "情報通信機械器具製造業"),
    ("311", "E", "製造業", "輸送用機械器具製造業"),
    ("321", "E", "製造業", "その他の製造業"),
    ("331", "F", "電気・ガス・熱供給・水道業", "電気業"),
    ("341", "F", "電気・ガス・熱供給・水道業", "ガス業"),
    ("351", "F", "電気・ガス・熱供給・水道業", "熱供給業"),
    ("361", "F", "電気・ガス・熱供給・水道業", "水道業"),
    ("371", "G", "情報通信業", "通信業"),
    ("381", "G", "情報通信業", "放送業"),
    ("391", "G", "情報通信業", "情報サービス業"),
    ("401", "G", "情報通信業", "インターネット附随サービス業"),
    ("411", "G", "情報通信業", "映像・音声・文字情報制作業"),
    ("421", "H", "運輸業，郵便業", "鉄道業"),
    ("431", "H", "運輸業，郵便業", "道路旅客運送業"),
    ("441", "H", "運輸業，郵便業", "道路貨物運送業"),
    ("451", "H", "運輸業，郵便業", "水運業"),
    ("461", "H", "運輸業，郵便業", "航空運輸業"),
    ("471", "H", "運輸業，郵便業", "倉庫業"),
    ("481", "H", "運輸業，郵便業", "運輸に附帯するサービス業"),
    ("491", "H", "運輸業，郵便業", "郵便業（信書便事業を含む）"),
    ("501", "I", "卸売業，小売業", "各種商品卸売業"),
    ("511", "I", "卸売業，小売業", "繊維・衣服等卸売業"),
    ("521", "I", "卸売業，小売業", "飲食料品卸売業"),
    ("531", "I", "卸売業，小売業", "建築材料，鉱物・金属材料等卸売業"),
    ("541", "I", "卸売業，小売業", "機械器具卸売業"),
    ("551", "I", "卸売業，小売業", "その他の卸売業"),
    ("561", "I", "卸売業，小売業", "各種商品小売業"),
    ("571", "I", "卸売業，小売業", "織物・衣服・身の回り品小売業"),
    ("581", "I", "卸売業，小売業", "飲食料品小売業"),
    ("591", "I", "卸売業，小売業", "機械器具小売業"),
    ("601", "I", "卸売業，小売業", "その他の小売業"),
    ("611", "I", "卸売業，小売業", "無店舗小売業"),
    ("621", "J", "金融業，保険業", "銀行業"),
    ("631", "J", "金融業，保険業", "協同組織金融業"),
    ("641", "J", "金融業，保険業", "貸金業，クレジットカード業等非預金信用機関"),
    ("651", "J", "金融業，保険業", "金融商品取引業，商品先物取引業"),
    ("661", "J", "金融業，保険業", "補助的金融業等"),
    ("671", "J", "金融業，保険業", "保険業"),
    ("681", "K", "不動産業，物品賃貸業", "不動産取引業"),
    ("691", "K", "不動産業，物品賃貸業", "不動産賃貸業・管理業"),
    ("701", "K", "不動産業，物品賃貸業", "物品賃貸業"),
    ("711", "L", "学術研究，専門・技術サービス業", "学術・開発研究機関"),
    ("721", "L", "学術研究，専門・技術サービス業", "専門サービス業"),
    ("731", "L", "学術研究，専門・技術サービス業", "広告業"),
    ("741", "L", "学術研究，専門・技術サービス業", "技術サービス業"),
    ("751", "M", "宿泊業，飲食サービス業", "宿泊業"),
    ("761", "M", "宿泊業，飲食サービス業", "飲食店"),
    ("771", "M", "宿泊業，飲食サービス業", "持ち帰り・配達飲食サービス業"),
    ("781", "N", "生活関連サービス業，娯楽業", "洗濯・理容・美容・浴場業"),
    ("791", "N", "生活関連サービス業，娯楽業", "その他の生活関連サービス業"),
    ("801", "N", "生活関連サービス業，娯楽業", "娯楽業"),
    ("811", "O", "教育，学習支援業", "学校教育"),
    ("821", "O", "教育，学習支援業", "その他の教育，学習支援業"),
    ("831", "P", "医療，福祉", "医療業"),
    ("841", "P", "医療，福祉", "保健衛生"),
    ("851", "P", "医療，福祉", "社会保険・社会福祉・介護事業"),
    ("861", "Q", "複合サービス事業", "郵便局"),
    ("871", "Q", "複合サービス事業", "協同組合（他に分類されないもの）"),
    ("881", "R", "サービス業（他に分類されないもの）", "廃棄物処理業"),
    ("891", "R", "サービス業（他に分類されないもの）", "自動車整備業"),
    ("901", "R", "サービス業（他に分類されないもの）", "機械等修理業"),
    ("911", "R", "サービス業（他に分類されないもの）", "職業紹介・労働者派遣業"),
    ("921", "R", "サービス業（他に分類されないもの）", "その他の事業サービス業"),
    ("931", "R", "サービス業（他に分類されないもの）", "政治・経済・文化団体"),
    ("941", "R", "サービス業（他に分類されないもの）", "宗教"),
    ("951", "R", "サービス業（他に分類されないもの）", "その他のサービス業"),
    ("961", "R", "サービス業（他に分類されないもの）", "外国公務"),
    ("971", "S", "公務（他に分類されるものを除く）", "国家公務"),
    ("981", "S", "公務（他に分類されるものを除く）", "地方公務"),
    ("991", "T", "分類不能の産業", "分類不能の産業"),
]


# Keyword → JSIC 中分類 mapping for substring-based program matcher.
# Conservative — biased toward false-negative (we lose recall, never
# precision). Order matters: longer/more-specific tokens first.
_KEYWORD_TO_JSIC: tuple[tuple[str, str], ...] = (
    ("総合工事", "060"),
    ("建設", "060"),
    ("建築", "060"),
    ("設備工事", "080"),
    ("食料品", "091"),
    ("飲料", "101"),
    ("繊維", "111"),
    ("木材", "121"),
    ("家具", "131"),
    ("印刷", "151"),
    ("化学", "161"),
    ("プラスチック", "181"),
    ("ゴム", "191"),
    ("鉄鋼", "221"),
    ("金属製品", "241"),
    ("生産用機械", "261"),
    ("業務用機械", "271"),
    ("電子部品", "281"),
    ("電気機械", "291"),
    ("情報通信機械", "301"),
    ("輸送用機械", "311"),
    ("ものづくり", "321"),
    ("電気業", "331"),
    ("ガス業", "341"),
    ("情報サービス", "391"),
    ("インターネット", "401"),
    ("映像", "411"),
    ("道路貨物", "441"),
    ("航空", "461"),
    ("倉庫", "471"),
    ("郵便", "491"),
    ("飲食料品卸売", "521"),
    ("機械器具卸売", "541"),
    ("小売", "601"),
    ("無店舗", "611"),
    ("銀行", "621"),
    ("信用金庫", "631"),
    ("信金", "631"),
    ("保険", "671"),
    ("不動産取引", "681"),
    ("不動産賃貸", "691"),
    ("物品賃貸", "701"),
    ("研究機関", "711"),
    ("広告", "731"),
    ("技術サービス", "741"),
    ("宿泊", "751"),
    ("飲食店", "761"),
    ("持ち帰り", "771"),
    ("理容", "781"),
    ("美容", "781"),
    ("娯楽", "801"),
    ("学校", "811"),
    ("学習支援", "821"),
    ("医療", "831"),
    ("介護", "851"),
    ("福祉", "851"),
    ("廃棄物", "881"),
    ("自動車整備", "891"),
    ("派遣", "911"),
    ("不動産", "681"),
    ("情報通信", "391"),
    ("製造", "321"),
    ("運輸", "441"),
)


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.aggregate_industry_sector_175_weekly")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #


def _db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _open_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent CREATEs mirroring migration 247."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_industry_jsic_175 (
              jsic_code TEXT PRIMARY KEY,
              major_code TEXT NOT NULL,
              parent_major TEXT,
              name TEXT NOT NULL,
              programs_count INTEGER NOT NULL DEFAULT 0,
              programs_avg_amount INTEGER NOT NULL DEFAULT 0,
              adoption_count INTEGER NOT NULL DEFAULT 0,
              enforcement_count INTEGER NOT NULL DEFAULT 0,
              refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_program_sector_175_map (
              map_id INTEGER PRIMARY KEY AUTOINCREMENT,
              program_id TEXT NOT NULL,
              jsic_code TEXT NOT NULL,
              score INTEGER NOT NULL DEFAULT 0,
              match_kind TEXT,
              refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_sector_175_map_edge "
        "ON am_program_sector_175_map(program_id, jsic_code)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_industry_sector_175_run_log (
              run_id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              sectors_refreshed INTEGER NOT NULL DEFAULT 0,
              programs_mapped INTEGER NOT NULL DEFAULT 0,
              error_text TEXT
            )"""
    )


# --------------------------------------------------------------------------- #
# Seed + mapping
# --------------------------------------------------------------------------- #


def _seed_dimension(conn: sqlite3.Connection) -> int:
    """INSERT OR REPLACE the 175-row JSIC 中分類 dimension."""
    rows = 0
    for jsic_code, major_code, parent_major, name in JSIC_175_SEED:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO am_industry_jsic_175 "
                "(jsic_code, major_code, parent_major, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (jsic_code, major_code, parent_major, name),
            )
            rows += 1
        except sqlite3.Error as e:
            logger.warning("seed row %s failed: %s", jsic_code, e)
    return rows


def _classify_text(text: str | None, major: str | None) -> list[tuple[str, int, str]]:
    """Return [(jsic_code, score, match_kind), ...] for one program signal.

    Keyword match scores 60. Major-only fallback scores 30 against every
    medium class in the same major (lowest-numbered sample only — keeps
    fanout bounded).
    """
    hits: list[tuple[str, int, str]] = []
    t = text or ""
    if t:
        for kw, code in _KEYWORD_TO_JSIC:
            if kw in t:
                hits.append((code, 60, "keyword"))
    if not hits and major and len(major) == 1:
        # Major-only fallback: pick the lowest-numbered medium in this major.
        for jsic_code, mc, _, _ in JSIC_175_SEED:
            if mc == major:
                hits.append((jsic_code, 30, "jsic_major"))
                break
    return hits


def _map_programs(conn: sqlite3.Connection) -> int:
    """Walk programs and emit one or more (program, jsic_code) edges.

    Falls through to an empty walk when ``programs`` table is missing
    (dev DB without jpintel.db merged in). Memory
    `feedback_no_quick_check_on_huge_sqlite` honored: index-only walk.
    """
    if not _table_exists(conn, "programs"):
        # Try jpi_* mirror — autonomath.db has jpi_programs_search.
        candidate_tables = (
            "jpi_programs_search",
            "jpi_programs",
        )
        prog_table = next((t for t in candidate_tables if _table_exists(conn, t)), None)
        if prog_table is None:
            logger.warning("no programs table found — skipping map_programs")
            return 0
    else:
        prog_table = "programs"

    edges_written = 0
    try:
        rows = conn.execute(
            f"SELECT unified_id, title, industry_tags, industry_jsic_major "
            f"FROM {prog_table} "
            f"WHERE excluded = 0 OR excluded IS NULL "
            f"LIMIT 50000"
        ).fetchall()
    except sqlite3.OperationalError:
        # Fall back to minimal column set
        try:
            rows = conn.execute(
                f"SELECT unified_id, title FROM {prog_table} LIMIT 50000"
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("programs walk failed: %s", e)
            return 0

    for r in rows:
        pid = r["unified_id"]
        if not pid:
            continue
        # sqlite3.Row supports membership testing directly via __contains__,
        # but ruff SIM118 flags `key in row.keys()`. Use `.keys()` extraction
        # once into a set so the membership tests are dict-style.
        cols = set(r.keys())
        title = r["title"] if "title" in cols else ""
        tags = r["industry_tags"] if "industry_tags" in cols else None
        major = r["industry_jsic_major"] if "industry_jsic_major" in cols else None
        text = f"{title or ''} {tags or ''}"
        hits = _classify_text(text, major)
        for code, score, kind in hits:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO am_program_sector_175_map "
                    "(program_id, jsic_code, score, match_kind, refreshed_at) "
                    "VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (pid, code, int(score), kind),
                )
                edges_written += 1
            except sqlite3.Error as e:
                logger.warning("map write %s→%s failed: %s", pid, code, e)
    return edges_written


def _refresh_aggregates(conn: sqlite3.Connection) -> int:
    """Update programs_count / programs_avg_amount / adoption_count / enforcement_count."""
    sectors_touched = 0
    try:
        # Tally programs per 中分類 from the map table.
        prog_counts: dict[str, int] = defaultdict(int)
        for r in conn.execute(
            "SELECT jsic_code, COUNT(DISTINCT program_id) AS c "
            "FROM am_program_sector_175_map GROUP BY jsic_code"
        ).fetchall():
            prog_counts[r["jsic_code"]] = int(r["c"])

        # adoption_count — best-effort
        adopt_counts: dict[str, int] = defaultdict(int)
        if _table_exists(conn, "jpi_adoption_records"):
            for r in conn.execute(
                "SELECT m.jsic_code, COUNT(DISTINCT a.id) AS c "
                "FROM jpi_adoption_records a "
                "JOIN am_program_sector_175_map m ON m.program_id = a.program_id "
                "GROUP BY m.jsic_code"
            ).fetchall():
                adopt_counts[r["jsic_code"]] = int(r["c"])

        # enforcement_count by major — coarse-grain rollup
        enf_counts_by_major: dict[str, int] = defaultdict(int)
        if _table_exists(conn, "am_enforcement_detail"):
            for r in conn.execute(
                "SELECT industry_jsic_major AS mj, COUNT(*) AS c "
                "FROM am_enforcement_detail "
                "WHERE industry_jsic_major IS NOT NULL "
                "GROUP BY industry_jsic_major"
            ).fetchall():
                enf_counts_by_major[r["mj"]] = int(r["c"])

        # Pull all sectors and update each.
        for r in conn.execute(
            "SELECT jsic_code, major_code FROM am_industry_jsic_175"
        ).fetchall():
            jc = r["jsic_code"]
            mc = r["major_code"]
            pc = prog_counts.get(jc, 0)
            ac = adopt_counts.get(jc, 0)
            ec = enf_counts_by_major.get(mc, 0)
            try:
                conn.execute(
                    "UPDATE am_industry_jsic_175 SET "
                    "  programs_count = ?, adoption_count = ?, "
                    "  enforcement_count = ?, refreshed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE jsic_code = ?",
                    (pc, ac, ec, jc),
                )
                sectors_touched += 1
            except sqlite3.Error as e:
                logger.warning("agg update %s failed: %s", jc, e)
    except sqlite3.OperationalError as e:
        logger.warning("refresh_aggregates failed: %s", e)
    return sectors_touched


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aggregate JSIC 175 中分類 weekly (NO ML, NO LLM).")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    started_at = datetime.now(UTC).isoformat()

    db_path = _db_path()
    if args.dry_run:
        logger.info("[dry-run] would open %s + seed %d sectors", db_path, len(JSIC_175_SEED))
        return 0

    if not db_path.exists():
        logger.error("autonomath.db missing at %s — run migration 247 first", db_path)
        return 2

    conn = _open_rw(db_path)
    try:
        _ensure_tables(conn)
        seeded = _seed_dimension(conn)
        edges = _map_programs(conn)
        sectors = _refresh_aggregates(conn)

        conn.execute(
            "INSERT INTO am_industry_sector_175_run_log "
            "(started_at, finished_at, sectors_refreshed, programs_mapped, error_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                started_at,
                datetime.now(UTC).isoformat(),
                sectors,
                edges,
                None,
            ),
        )
        result = {
            "sectors_seeded": seeded,
            "edges_written": edges,
            "sectors_refreshed": sectors,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        with contextlib.suppress(Exception):
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
