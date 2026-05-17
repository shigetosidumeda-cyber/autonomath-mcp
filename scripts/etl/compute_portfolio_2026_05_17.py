"""compute_portfolio_2026_05_17 — Niche Moat Lane N2 (2026-05-17).

Precompute per-(houjin × program) applicability scores into
``am_houjin_program_portfolio`` so the MCP tools
``get_houjin_portfolio`` / ``find_gap_programs`` are O(index lookup) at
request time instead of O(11K * sparse filter) per call.

Score model (deterministic, NO LLM)
------------------------------------
Five additive axes weighted 30 / 25 / 25 / 20 / (0..10 tie-breaker):

  score_industry   (0-30)  JSIC major overlap between houjin's inferred
                           industry (from past adoption_records OR null)
                           and the program's target industry. Horizontal
                           programs (no industry fence) get a flat 10.
  score_size       (0-25)  size band — heuristic 15 baseline (all houjin
                           in jpi_houjin_master are 'corporation' so we
                           cannot distinguish micro vs small vs medium).
  score_region     (0-25)  prefecture match: national=25, exact=25,
                           prefix-match=12, otherwise 0.
  score_sector     (0-20)  target_types_json: corporation / sole vs
                           houjin's corporation_type. unknown=10.
  score_target_form(0-10)  法人格 final tie-break.

  applicability_score = sum of the five axes (0-110 theoretical max,
  clamped to 100).

Sparse filter (`should_keep`) drops pairs with no signal AND no form
match, bringing the 1.9B pair space down to ~5-10M real rows.

Applied status
--------------
Joined post-scoring from ``jpi_adoption_records`` matched on
(houjin_bangou, program_id). Three states: applied / unapplied / unknown.

Deadline
--------
Parsed from ``jpi_programs.application_window_json`` ``end_date`` field.
``deadline_kind`` ∈ {'end_date', 'start_date', 'rolling', 'none'}.

Priority rank
-------------
Per-houjin dense rank (RANK_CAP=100) with the ORDER BY:
  (applied_status='unapplied') first,
  future-dated first (bucket 0=dated future / 1=rolling / 2=no window /
  3=expired), soonest first, score DESC.

Usage
-----
    .venv/bin/python scripts/etl/compute_portfolio_2026_05_17.py \\
        --db autonomath.db [--limit-houjin N] [--min-score 30] [--dry-run]

Idempotent — re-running upserts via UNIQUE INDEX (houjin, program, method).

NO LLM API. Local Python single-process — per memory
``feedback_packet_local_gen_300x_faster``, sub-5sec-per-unit work runs
faster locally than via SageMaker / Batch (startup overhead exceeds work).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("jpcite.etl.compute_portfolio")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

METHOD = "lane_n2_deterministic_v1"

W_INDUSTRY = 30.0
W_SIZE = 25.0
W_REGION = 25.0
W_SECTOR = 20.0
W_TARGET_FORM = 10.0
SCORE_MAX = 100.0

RANK_CAP = 100


JSIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "A": ("農業", "林業", "農林"),
    "B": ("漁業", "水産"),
    "C": ("鉱業", "採石"),
    "D": ("建設", "土木", "建築", "住宅", "工事"),
    "E": ("製造", "ものづくり", "工場", "設備投資", "生産"),
    "F": ("電気", "ガス", "熱供給", "水道"),
    "G": ("情報通信", "IT", "ソフトウェア", "DX", "デジタル"),
    "H": ("運輸", "輸送", "物流", "倉庫"),
    "I": ("卸売", "小売", "EC", "店舗", "商業"),
    "J": ("金融", "保険"),
    "K": ("不動産", "賃貸", "空き家"),
    "L": ("学術", "研究", "専門", "技術"),
    "M": ("宿泊", "飲食", "旅館", "ホテル", "レストラン"),
    "N": ("生活", "娯楽", "美容", "理容", "エステ"),
    "O": ("教育", "学習", "塾"),
    "P": ("医療", "福祉", "介護", "看護"),
    "Q": ("複合",),
    "R": ("サービス",),
    "S": ("公務",),
    "T": ("分類不能",),
}

SIZE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "micro": ("小規模", "マイクロ", "個人事業", "零細"),
    "small": ("小規模", "中小企業", "小企業"),
    "medium": ("中小企業", "中堅企業", "中規模"),
    "large": ("大企業",),
}

TARGET_TYPE_CORP = {"corporation", "法人", "法人全般", "中小企業", "農業法人", "認定新規就農者"}
TARGET_TYPE_SOLE = {"sole_proprietor", "個人事業主", "個人農業者"}
TARGET_TYPE_OTHER = {"大学・研究機関", "市町村", "団体", "非農家"}


@dataclass(frozen=True)
class Program:
    program_id: str
    primary_name: str
    program_kind: str | None
    prefecture: str | None
    target_types: tuple[str, ...]
    target_jsic: tuple[str, ...]
    target_size: tuple[str, ...]
    deadline: str | None
    deadline_kind: str | None
    is_national: bool


@dataclass(frozen=True)
class Houjin:
    houjin_bangou: str
    prefecture: str | None
    corporation_type: str | None
    inferred_jsic: tuple[str, ...]
    has_any_adoption: bool


@dataclass
class ScoredPair:
    houjin_bangou: str
    program_id: str
    score_industry: float
    score_size: float
    score_region: float
    score_sector: float
    score_target_form: float

    @property
    def total(self) -> float:
        return min(
            SCORE_MAX,
            self.score_industry
            + self.score_size
            + self.score_region
            + self.score_sector
            + self.score_target_form,
        )


@dataclass
class PortfolioRow:
    houjin_bangou: str
    program_id: str
    applicability_score: float
    score_industry: float
    score_size: float
    score_region: float
    score_sector: float
    score_target_form: float
    applied_status: str
    applied_at: str | None
    deadline: str | None
    deadline_kind: str | None
    priority_rank: int | None


_TODAY = datetime.date.today().isoformat()
_PROGRAM_BY_ID: dict[str, Program] = {}


def _open_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        msg = f"DB not found: {db_path}"
        raise FileNotFoundError(msg)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        msg = f"DB not found: {db_path}"
        raise FileNotFoundError(msg)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _parse_json_list(blob: str | None) -> tuple[str, ...]:
    if not blob:
        return ()
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return ()
    if isinstance(data, list):
        return tuple(str(x).strip() for x in data if x is not None and str(x).strip())
    return ()


def _infer_program_jsic(name: str, declared: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = set()
    if not name:
        return ()
    name_lc = name.lower()
    for major, kws in JSIC_KEYWORDS.items():
        for kw in kws:
            if kw in name or kw.lower() in name_lc:
                found.add(major)
                break
    return tuple(sorted(found))


def _infer_program_size(name: str, target_types: tuple[str, ...]) -> tuple[str, ...]:
    bands: set[str] = set()
    combined = (name or "") + " " + " ".join(target_types)
    for band, kws in SIZE_KEYWORDS.items():
        for kw in kws:
            if kw in combined:
                bands.add(band)
                break
    return tuple(sorted(bands))


def _parse_deadline(window_json: str | None) -> tuple[str | None, str | None]:
    if not window_json:
        return (None, "none")
    try:
        data = json.loads(window_json)
    except (json.JSONDecodeError, TypeError):
        return (None, "none")
    if not isinstance(data, dict):
        return (None, "none")
    end_date = data.get("end_date")
    start_date = data.get("start_date")
    cycle = data.get("cycle")
    if end_date and isinstance(end_date, str) and len(end_date) >= 10:
        return (end_date[:10], "end_date")
    if start_date and isinstance(start_date, str) and len(start_date) >= 10:
        return (start_date[:10], "start_date")
    if cycle == "rolling":
        return (None, "rolling")
    return (None, "none")


def load_programs(conn: sqlite3.Connection) -> list[Program]:
    cur = conn.execute(
        """
        SELECT unified_id, primary_name, program_kind, prefecture,
               target_types_json, application_window_json
          FROM jpi_programs
         WHERE COALESCE(excluded, 0) = 0
        """
    )
    programs: list[Program] = []
    for row in cur:
        unified_id = row["unified_id"]
        name = row["primary_name"] or ""
        target_types = _parse_json_list(row["target_types_json"])
        target_jsic = _infer_program_jsic(name, target_types)
        target_size = _infer_program_size(name, target_types)
        deadline, kind = _parse_deadline(row["application_window_json"])
        prefecture = row["prefecture"]
        is_national = not prefecture or prefecture.strip() == ""
        programs.append(
            Program(
                program_id=unified_id,
                primary_name=name,
                program_kind=row["program_kind"],
                prefecture=prefecture,
                target_types=target_types,
                target_jsic=target_jsic,
                target_size=target_size,
                deadline=deadline,
                deadline_kind=kind,
                is_national=is_national,
            )
        )
    return programs


def load_houjin_inferred_jsic(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    cur = conn.execute(
        """
        SELECT houjin_bangou, industry_jsic_medium
          FROM jpi_adoption_records
         WHERE houjin_bangou IS NOT NULL AND houjin_bangou != ''
           AND industry_jsic_medium IS NOT NULL AND industry_jsic_medium != ''
        """
    )
    out: dict[str, set[str]] = defaultdict(set)
    for row in cur:
        hb = row["houjin_bangou"]
        ind = (row["industry_jsic_medium"] or "").strip()
        if ind:
            out[hb].add(ind[0])
    return {k: tuple(sorted(v)) for k, v in out.items()}


def load_houjin_with_any_adoption(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(
        """
        SELECT DISTINCT houjin_bangou
          FROM jpi_adoption_records
         WHERE houjin_bangou IS NOT NULL AND houjin_bangou != ''
        """
    )
    return {row[0] for row in cur}


def load_applied_pairs(conn: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
    cur = conn.execute(
        """
        SELECT houjin_bangou, program_id, MIN(announced_at) AS first_at
          FROM jpi_adoption_records
         WHERE houjin_bangou IS NOT NULL AND houjin_bangou != ''
           AND program_id IS NOT NULL AND program_id != ''
         GROUP BY houjin_bangou, program_id
        """
    )
    out: dict[tuple[str, str], str | None] = {}
    for row in cur:
        out[(row["houjin_bangou"], row["program_id"])] = row["first_at"]
    return out


def load_houjin_master(conn: sqlite3.Connection, limit: int | None = None) -> list[Houjin]:
    sql = """
        SELECT houjin_bangou, prefecture, corporation_type
          FROM jpi_houjin_master
         WHERE houjin_bangou IS NOT NULL AND houjin_bangou != ''
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.execute(sql)
    rows: list[sqlite3.Row] = list(cur)
    return [
        Houjin(
            houjin_bangou=r["houjin_bangou"],
            prefecture=r["prefecture"],
            corporation_type=r["corporation_type"],
            inferred_jsic=(),
            has_any_adoption=False,
        )
        for r in rows
    ]


def score_pair(houjin: Houjin, program: Program) -> ScoredPair:
    if not program.target_jsic:
        score_industry = 10.0
    elif houjin.inferred_jsic:
        overlap = set(houjin.inferred_jsic) & set(program.target_jsic)
        score_industry = 30.0 if overlap else 0.0
    else:
        score_industry = 5.0

    if program.is_national or (
        houjin.prefecture and program.prefecture and houjin.prefecture == program.prefecture
    ):
        score_region = 25.0
    elif (
        houjin.prefecture
        and program.prefecture
        and houjin.prefecture.replace("府", "")
        .replace("県", "")
        .replace("都", "")
        .replace("道", "")
        in program.prefecture
    ):
        score_region = 12.0
    else:
        score_region = 0.0

    if not program.target_types:
        score_sector = 10.0
    else:
        tt_lower = {t.lower() for t in program.target_types}
        ht = (houjin.corporation_type or "corporation").lower()
        if (
            ht == "corporation"
            and tt_lower & {t.lower() for t in TARGET_TYPE_CORP}
            or ht == "sole_proprietor"
            and tt_lower & {t.lower() for t in TARGET_TYPE_SOLE}
        ):
            score_sector = 20.0
        elif tt_lower & {t.lower() for t in TARGET_TYPE_OTHER}:
            score_sector = 3.0
        else:
            score_sector = 5.0

    if not program.target_size:
        score_size = 15.0
    else:
        sme_bands = {"micro", "small", "medium"}
        if set(program.target_size) & sme_bands:
            score_size = 20.0
        elif "large" in program.target_size:
            score_size = 5.0
        else:
            score_size = 12.0

    ht = (houjin.corporation_type or "corporation").lower()
    if not program.target_types:
        score_target_form = 5.0
    else:
        tt_lower2 = {t.lower() for t in program.target_types}
        if (
            ht == "corporation"
            and ("corporation" in tt_lower2 or "法人全般" in program.target_types)
            or ht == "sole_proprietor"
            and "sole_proprietor" in tt_lower2
        ):
            score_target_form = 10.0
        else:
            score_target_form = 0.0

    return ScoredPair(
        houjin_bangou=houjin.houjin_bangou,
        program_id=program.program_id,
        score_industry=score_industry,
        score_size=score_size,
        score_region=score_region,
        score_sector=score_sector,
        score_target_form=score_target_form,
    )


def should_keep(pair: ScoredPair) -> bool:
    if pair.score_industry >= 30.0:
        return True
    if pair.score_region >= 25.0 and pair.score_target_form >= 10.0:
        return True
    return bool(pair.score_industry >= 10.0 and pair.score_target_form >= 10.0)


def rank_houjin_rows(rows: list[PortfolioRow]) -> list[PortfolioRow]:
    def sort_key(r: PortfolioRow) -> tuple[int, int, str, float]:
        unapplied_bit = 0 if r.applied_status == "unapplied" else 1
        if r.deadline and r.deadline >= _TODAY:
            bucket = 0
            deadline_key = r.deadline
        elif r.deadline_kind == "rolling":
            bucket = 1
            deadline_key = "9999-01-01"
        elif r.deadline is None:
            bucket = 2
            deadline_key = "9999-06-01"
        else:
            bucket = 3
            deadline_key = "9999-12-31"
        return (unapplied_bit, bucket, deadline_key, -r.applicability_score)

    rows.sort(key=sort_key)
    out: list[PortfolioRow] = []
    for i, r in enumerate(rows[:RANK_CAP], start=1):
        r.priority_rank = i
        out.append(r)
    return out


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[PortfolioRow]) -> int:
    sql = """
        INSERT INTO am_houjin_program_portfolio (
            houjin_bangou, program_id, applicability_score,
            score_industry, score_size, score_region, score_sector, score_target_form,
            applied_status, applied_at, deadline, deadline_kind, priority_rank,
            method
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(houjin_bangou, program_id, method) DO UPDATE SET
            applicability_score = excluded.applicability_score,
            score_industry = excluded.score_industry,
            score_size = excluded.score_size,
            score_region = excluded.score_region,
            score_sector = excluded.score_sector,
            score_target_form = excluded.score_target_form,
            applied_status = excluded.applied_status,
            applied_at = excluded.applied_at,
            deadline = excluded.deadline,
            deadline_kind = excluded.deadline_kind,
            priority_rank = excluded.priority_rank,
            computed_at = datetime('now')
    """
    batch: list[tuple[Any, ...]] = []
    count = 0
    batch_size = 5000
    for r in rows:
        batch.append(
            (
                r.houjin_bangou,
                r.program_id,
                r.applicability_score,
                r.score_industry,
                r.score_size,
                r.score_region,
                r.score_sector,
                r.score_target_form,
                r.applied_status,
                r.applied_at,
                r.deadline,
                r.deadline_kind,
                r.priority_rank,
                METHOD,
            )
        )
        if len(batch) >= batch_size:
            conn.executemany(sql, batch)
            conn.commit()
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)
        conn.commit()
        count += len(batch)
    return count


def compute_portfolio(
    db_path: Path,
    limit_houjin: int | None = None,
    min_score: float = 30.0,
    dry_run: bool = False,
) -> dict[str, int]:
    t0 = time.time()
    ro = _open_ro(db_path)

    logger.info("loading programs ...")
    programs = load_programs(ro)
    logger.info("loaded %d programs", len(programs))
    _PROGRAM_BY_ID.clear()
    for p in programs:
        _PROGRAM_BY_ID[p.program_id] = p

    logger.info("loading houjin master ...")
    houjin_rows = load_houjin_master(ro, limit=limit_houjin)
    logger.info("loaded %d houjin master rows", len(houjin_rows))

    logger.info("loading houjin inferred JSIC ...")
    inferred = load_houjin_inferred_jsic(ro)
    logger.info("inferred JSIC for %d houjin", len(inferred))

    logger.info("loading houjin with any adoption ...")
    any_adoption = load_houjin_with_any_adoption(ro)
    logger.info("%d houjin have at least one adoption row", len(any_adoption))

    logger.info("loading applied pairs ...")
    applied_pairs = load_applied_pairs(ro)
    logger.info("loaded %d applied pairs", len(applied_pairs))

    ro.close()

    houjin_list: list[Houjin] = [
        Houjin(
            houjin_bangou=h.houjin_bangou,
            prefecture=h.prefecture,
            corporation_type=h.corporation_type,
            inferred_jsic=inferred.get(h.houjin_bangou, ()),
            has_any_adoption=h.houjin_bangou in any_adoption,
        )
        for h in houjin_rows
    ]

    rw: sqlite3.Connection | None = _open_rw(db_path) if not dry_run else None

    total_pairs_scored = 0
    total_pairs_kept = 0
    total_rows_written = 0
    applied_count = 0
    unapplied_count = 0
    unknown_count = 0

    for idx, h in enumerate(houjin_list, start=1):
        scored: list[ScoredPair] = []
        for p in programs:
            sp = score_pair(h, p)
            total_pairs_scored += 1
            if not should_keep(sp):
                continue
            if sp.total < min_score:
                continue
            scored.append(sp)
        total_pairs_kept += len(scored)

        rows: list[PortfolioRow] = []
        for sp in scored:
            applied_at = applied_pairs.get((h.houjin_bangou, sp.program_id))
            if applied_at is not None:
                status = "applied"
                applied_count += 1
            elif h.has_any_adoption:
                status = "unapplied"
                unapplied_count += 1
            else:
                status = "unknown"
                unknown_count += 1
            prog = _PROGRAM_BY_ID[sp.program_id]
            rows.append(
                PortfolioRow(
                    houjin_bangou=h.houjin_bangou,
                    program_id=sp.program_id,
                    applicability_score=sp.total,
                    score_industry=sp.score_industry,
                    score_size=sp.score_size,
                    score_region=sp.score_region,
                    score_sector=sp.score_sector,
                    score_target_form=sp.score_target_form,
                    applied_status=status,
                    applied_at=applied_at,
                    deadline=prog.deadline,
                    deadline_kind=prog.deadline_kind,
                    priority_rank=None,
                )
            )

        ranked = rank_houjin_rows(rows)
        if not dry_run and ranked and rw is not None:
            total_rows_written += upsert_rows(rw, ranked)

        if idx % 500 == 0:
            elapsed = time.time() - t0
            logger.info(
                "houjin %d/%d scored=%d kept=%d written=%d elapsed=%.1fs",
                idx,
                len(houjin_list),
                total_pairs_scored,
                total_pairs_kept,
                total_rows_written,
                elapsed,
            )

    if not dry_run and rw is not None:
        rw.close()

    elapsed = time.time() - t0
    summary = {
        "houjin_processed": len(houjin_list),
        "programs": len(programs),
        "pairs_scored": total_pairs_scored,
        "pairs_kept_post_filter": total_pairs_kept,
        "rows_written": total_rows_written,
        "applied": applied_count,
        "unapplied": unapplied_count,
        "unknown": unknown_count,
        "elapsed_sec": int(elapsed),
    }
    logger.info("DONE %s", json.dumps(summary, ensure_ascii=False))
    return summary


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="autonomath.db path")
    p.add_argument("--limit-houjin", type=int, default=None, help="cap houjin count")
    p.add_argument("--min-score", type=float, default=30.0, help="drop floor")
    p.add_argument("--dry-run", action="store_true", help="score but do not persist")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    summary = compute_portfolio(
        db_path=args.db,
        limit_houjin=args.limit_houjin,
        min_score=args.min_score,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
