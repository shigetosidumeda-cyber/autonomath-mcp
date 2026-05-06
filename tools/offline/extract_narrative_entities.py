#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""§10.10 (1) Hallucination Guard — narrative entity extractor + corpus fact-check.

Walks rows in `am_program_narrative` (and the four sibling narrative tables —
`am_houjin_360_narrative`, `am_enforcement_summary`, `am_case_study_narrative`,
`am_law_article_summary`), extracts entity mentions (regex + optional spaCy /
GiNZA NER fallback), and verifies each entity against the canonical corpus
tables in autonomath.db / jpintel.db.

Per `feedback_no_operator_llm_api`, this script:
    * MUST NOT import any LLM SDK (anthropic / openai / google.generativeai /
      claude_agent_sdk).
    * MUST NOT reference any LLM API-key env var.
    * MAY use spaCy / GiNZA for NER fallback (pure-ML, no network).

The script writes:
    * One row per detected entity into `am_narrative_extracted_entities`
      (UNIQUE on narrative_id × narrative_table × span). corpus_match=1 when
      the entity resolved to a canonical corpus row, 0 otherwise.
    * For each narrative whose weighted match_rate ≤ THRESHOLD (default 0.85),
      one row into `am_narrative_quarantine` (reason='low_match_rate') and
      flips the parent narrative's `is_active = 0`.

match_rate formula
------------------
    W = {money:3, law:3, url:2, houjin:2, program:2,
         year:1, percent:1, count:1, jsic:1}
    rate = sum(W[k] * matched_k) / sum(W[k] for all k)

THRESHOLD: 0.85 (rows ≤ THRESHOLD are quarantined).

Usage
-----
    # Smoke check (no DB writes, just import + SQL prepare):
    uv run python tools/offline/extract_narrative_entities.py \\
        --dry-run --narrative-id 1

    # Full weekly extract (operator runs Sun 02:00 JST):
    uv run python tools/offline/extract_narrative_entities.py \\
        --table am_program_narrative

    # All five narrative tables:
    uv run python tools/offline/extract_narrative_entities.py --all-tables

Cron handle
-----------
    .github/workflows/narrative-factcheck-weekly.yml (operator runner)
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("autonomath.offline.extract_narrative_entities")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

THRESHOLD: float = 0.85

# Per-kind weights for the weighted match rate.
WEIGHTS: dict[str, int] = {
    "money": 3,
    "law": 3,
    "url": 2,
    "houjin": 2,
    "program": 2,
    "year": 1,
    "percent": 1,
    "count": 1,
    "jsic": 1,
}

# Narrative tables that this guard operates on. All five share the same
# (narrative_id PRIMARY KEY, body TEXT, is_active INTEGER) shape — we use
# the body column as the source text and key extracted rows by narrative_id.
NARRATIVE_TABLES: tuple[str, ...] = (
    "am_program_narrative",
    "am_houjin_360_narrative",
    "am_enforcement_summary",
    "am_case_study_narrative",
    "am_law_article_summary",
)

# Body column candidates per narrative table. The first one that exists in
# the table schema is used as the source text for entity extraction.
_BODY_COLUMN_CANDIDATES: tuple[str, ...] = (
    "body",
    "body_ja",
    "narrative",
    "summary",
    "text",
    "content",
)

# ---------------------------------------------------------------------------
# Regex patterns (kind → compiled regex). Order is presentation only;
# matches are stored with their (kind, span_start, span_end) coordinates.
# ---------------------------------------------------------------------------

# Money: ¥1,000 / 1000円 / 1,000万円 / 1億円 / 100万円 / $100 (USD pass-through)
RE_MONEY = re.compile(
    r"(?:¥|\\\\)\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:円|万円|億円|百万円|千円)"
    r"|\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
)

# Year: 2020 / 2020年 / 令和5年 / 平成30年 / 昭和60年 (4-digit western OR wareki)
RE_YEAR = re.compile(
    r"(?:19|20)\d{2}\s*年?"
    r"|(?:令和|平成|昭和|大正|明治)\s*\d{1,2}\s*年"
)

# Percent: 50% / 50％ / 50.5%
RE_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*[%％]")

# Count: 100件 / 1,000社 / 50人 / 12箇所 / 5社
RE_COUNT = re.compile(
    r"\d{1,3}(?:,\d{3})*(?:\s*(?:件|社|人|名|箇所|か所|個|拠点|事業者|法人))"
)

# URL: http(s)://...
RE_URL = re.compile(r"https?://[^\s<>「」『』、。\)\]]+")

# Houjin (法人番号): 13 contiguous digits. Sometimes prefixed with 'T' (適格事業者).
RE_HOUJIN = re.compile(r"\bT?(\d{13})\b")

# JSIC (industry code): "JSIC E" / "JSIC-E" / "産業大分類E"
RE_JSIC = re.compile(r"(?:JSIC|産業(?:大|中|小)?分類)\s*[-:]?\s*([A-T])")

# Law: e.g. "法人税法第22条", "労働基準法第36条", "中小企業等経営強化法"
RE_LAW = re.compile(
    r"([一-鿿]{2,12}(?:法|令|規則|基本法|措置法|促進法|特例法))"
    r"(?:第\s*\d+\s*条(?:の\d+)?)?"
)

# Program: things ending with 補助金 / 助成金 / 給付金 / 交付金 / 支援事業 / 融資 / 制度
RE_PROGRAM = re.compile(
    r"([一-鿿゠-ヿｦ-ﾟaA-Za-z0-9\s・]{2,40}?"
    r"(?:補助金|助成金|給付金|交付金|支援事業|融資|制度))"
)

KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("money", RE_MONEY),
    ("year", RE_YEAR),
    ("percent", RE_PERCENT),
    ("count", RE_COUNT),
    ("url", RE_URL),
    ("houjin", RE_HOUJIN),
    ("jsic", RE_JSIC),
    ("law", RE_LAW),
    ("program", RE_PROGRAM),
]


# ---------------------------------------------------------------------------
# spaCy / GiNZA fallback. Optional — we degrade gracefully if not installed.
# ---------------------------------------------------------------------------

_SPACY_NLP = None
_SPACY_TRIED = False


def _load_spacy():
    """Lazy-load ja_core_news_lg or ja_ginza if available; return None otherwise."""
    global _SPACY_NLP, _SPACY_TRIED
    if _SPACY_TRIED:
        return _SPACY_NLP
    _SPACY_TRIED = True
    try:
        import spacy  # type: ignore[import-not-found]

        for model in ("ja_core_news_lg", "ja_ginza"):
            try:
                _SPACY_NLP = spacy.load(model)
                logger.info("loaded_spacy_model model=%s", model)
                return _SPACY_NLP
            except (OSError, ImportError):
                continue
        logger.info("spacy_installed_no_japanese_model fallback=regex_only")
    except ImportError:
        logger.info("spacy_not_installed fallback=regex_only")
    return None


def _spacy_entities(text: str) -> Iterable[tuple[str, str, int, int]]:
    """Yield (kind, surface, start, end) for spaCy-detected ORG/MONEY/DATE/PERCENT/LAW.

    spaCy ENT_TYPE → our kind:
        ORG     → program (when it ends with one of our suffixes)
        MONEY   → money
        DATE    → year
        PERCENT → percent
        LAW     → law
    """
    nlp = _load_spacy()
    if nlp is None:
        return
    type_map = {
        "MONEY": "money",
        "DATE": "year",
        "PERCENT": "percent",
        "LAW": "law",
        "ORG": "program",
    }
    doc = nlp(text)
    for ent in doc.ents:
        kind = type_map.get(ent.label_)
        if kind is None:
            continue
        if kind == "program" and not re.search(
            r"(補助金|助成金|給付金|交付金|支援事業|融資|制度)$", ent.text
        ):
            continue
        yield kind, ent.text, ent.start_char, ent.end_char


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _normalize(kind: str, surface: str) -> str:
    """Canonicalize an entity surface to its corpus-match key."""
    s = surface.strip()
    if kind == "houjin":
        m = RE_HOUJIN.search(s)
        return m.group(1) if m else re.sub(r"\D", "", s)
    if kind == "url":
        return s.rstrip("/")
    if kind == "jsic":
        m = RE_JSIC.search(s)
        return m.group(1).upper() if m else s.upper()
    if kind == "year":
        # Extract the 4-digit western year if present; otherwise leave wareki.
        wm = re.search(r"(19|20)\d{2}", s)
        if wm:
            return wm.group(0)
        return s
    if kind == "money":
        # Strip currency markers and unit suffixes; preserve unit hint via _suffix.
        return re.sub(r"[¥\\\\,\s円万億百千]", "", s).rstrip(".")
    if kind == "percent":
        return re.sub(r"[%％\s]", "", s)
    return s


def _money_to_man_yen(surface: str) -> float | None:
    """Convert a money surface like '1,000万円' or '¥10,000,000' to 万円 units.

    Returns None when the value cannot be parsed.
    """
    s = surface.replace(",", "").replace(" ", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    if "億円" in s:
        return n * 10_000  # 1億 = 1万万
    if "万円" in s:
        return n
    if "百万円" in s:
        return n * 100
    if "千円" in s:
        return n / 10
    if "円" in s or s.startswith("¥") or s.startswith("\\"):
        return n / 10_000
    return None


def extract_entities(text: str) -> list[dict]:
    """Return a deduplicated list of entity dicts found in `text`.

    Each dict carries: {kind, surface, norm, start, end}.
    Overlapping spans of the same kind are merged (longest match wins).
    """
    hits: dict[tuple[int, int, str], dict] = {}

    for kind, pat in KIND_PATTERNS:
        for m in pat.finditer(text):
            start, end = m.span()
            surface = text[start:end]
            key = (start, end, kind)
            hits[key] = {
                "kind": kind,
                "surface": surface,
                "norm": _normalize(kind, surface),
                "start": start,
                "end": end,
            }

    for kind, surface, start, end in _spacy_entities(text):
        key = (start, end, kind)
        if key not in hits:
            hits[key] = {
                "kind": kind,
                "surface": surface,
                "norm": _normalize(kind, surface),
                "start": start,
                "end": end,
            }

    return sorted(hits.values(), key=lambda h: (h["start"], h["end"], h["kind"]))


# ---------------------------------------------------------------------------
# Corpus matching
# ---------------------------------------------------------------------------


def _match_url(conn: sqlite3.Connection, norm: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT 'am_source' AS t, source_id FROM am_source WHERE url LIKE ? LIMIT 1",
        (f"%{norm[:200]}%",),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_houjin(conn: sqlite3.Connection, norm: str) -> tuple[str, str] | None:
    if len(norm) != 13 or not norm.isdigit():
        return None
    row = conn.execute(
        "SELECT 'am_entities' AS t, canonical_id FROM am_entities "
        "WHERE record_kind='corporate_entity' AND canonical_id = ? LIMIT 1",
        (f"HOUJIN-{norm}",),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_jsic(conn: sqlite3.Connection, norm: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT 'am_industry_jsic' AS t, jsic_code FROM am_industry_jsic "
        "WHERE jsic_code LIKE ? LIMIT 1",
        (f"{norm}%",),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_law(conn: sqlite3.Connection, norm: str) -> tuple[str, str] | None:
    name = re.sub(r"第\d+条(?:の\d+)?$", "", norm).strip()
    if not name:
        return None
    row = conn.execute(
        "SELECT 'laws' AS t, law_id FROM laws WHERE name_ja LIKE ? LIMIT 1",
        (f"%{name}%",),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_program(conn: sqlite3.Connection, norm: str) -> tuple[str, str] | None:
    if not norm:
        return None
    row = conn.execute(
        "SELECT 'am_alias' AS t, entity_id FROM am_alias WHERE alias_text LIKE ? LIMIT 1",
        (f"%{norm}%",),
    ).fetchone()
    if row:
        return (row[0], str(row[1]))
    row = conn.execute(
        "SELECT 'programs' AS t, unified_id FROM programs WHERE primary_name LIKE ? LIMIT 1",
        (f"%{norm}%",),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_money(
    conn: sqlite3.Connection, norm_man_yen: float | None, parent_program_id: int | None
) -> tuple[str, str] | None:
    """Money matches against the parent program's amount_max_man_yen ±20%."""
    if norm_man_yen is None or parent_program_id is None:
        return None
    row = conn.execute(
        "SELECT 'programs' AS t, id FROM programs "
        "WHERE id = ? AND amount_max_man_yen IS NOT NULL "
        "  AND amount_max_man_yen BETWEEN ? AND ? LIMIT 1",
        (parent_program_id, norm_man_yen * 0.8, norm_man_yen * 1.2),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def _match_year(
    conn: sqlite3.Connection, norm: str, parent_entity_id: str | None
) -> tuple[str, str] | None:
    """Year matches against am_amendment_snapshot.effective_from year."""
    m = re.search(r"(19|20)\d{2}", norm)
    if not m or parent_entity_id is None:
        return None
    year_prefix = f"{m.group(0)}-"
    row = conn.execute(
        "SELECT 'am_amendment_snapshot' AS t, snapshot_id FROM am_amendment_snapshot "
        "WHERE entity_id = ? AND effective_from LIKE ? LIMIT 1",
        (parent_entity_id, f"{year_prefix}%"),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def match_against_corpus(
    conn: sqlite3.Connection,
    entity: dict,
    parent_program_id: int | None,
    parent_entity_id: str | None,
) -> tuple[bool, str | None, str | None]:
    """Return (matched, corpus_table, corpus_pk) for the entity."""
    kind = entity["kind"]
    norm = entity["norm"]
    try:
        if kind == "url":
            r = _match_url(conn, norm)
        elif kind == "houjin":
            r = _match_houjin(conn, norm)
        elif kind == "jsic":
            r = _match_jsic(conn, norm)
        elif kind == "law":
            r = _match_law(conn, entity["surface"])
        elif kind == "program":
            r = _match_program(conn, entity["surface"])
        elif kind == "money":
            man_yen = _money_to_man_yen(entity["surface"])
            r = _match_money(conn, man_yen, parent_program_id)
        elif kind == "year":
            r = _match_year(conn, norm, parent_entity_id)
        else:
            # percent / count fallback: any non-empty norm counts as a soft match
            # (we cannot disprove "30%" without the calling-context).
            return (bool(norm), None, None)
    except sqlite3.OperationalError as exc:
        logger.warning(
            "corpus_match_query_failed kind=%s err=%s", kind, str(exc)[:160]
        )
        return (False, None, None)
    if r:
        return (True, r[0], r[1])
    return (False, None, None)


# ---------------------------------------------------------------------------
# match_rate computation
# ---------------------------------------------------------------------------


def evaluate_match_rate(
    conn: sqlite3.Connection, narrative_id: int, narrative_table: str
) -> float:
    rows = conn.execute(
        "SELECT entity_kind, corpus_match FROM am_narrative_extracted_entities "
        "WHERE narrative_id=? AND narrative_table=?",
        (narrative_id, narrative_table),
    ).fetchall()
    if not rows:
        return 1.0
    num = 0
    den = 0
    for kind, matched in rows:
        w = WEIGHTS.get(kind, 1)
        den += w
        num += w * (1 if matched else 0)
    if den == 0:
        return 1.0
    return num / den


# ---------------------------------------------------------------------------
# Body / parent resolver
# ---------------------------------------------------------------------------


def _resolve_body_column(conn: sqlite3.Connection, table: str) -> str:
    cols = {
        r[1]
        for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for cand in _BODY_COLUMN_CANDIDATES:
        if cand in cols:
            return cand
    raise RuntimeError(
        f"no body column found in {table}; tried {_BODY_COLUMN_CANDIDATES}"
    )


def _resolve_parent_program(
    conn: sqlite3.Connection, table: str, narrative_id: int
) -> tuple[int | None, str | None]:
    """Return (parent program.id, parent program canonical_id / entity_id) for a narrative row."""
    if table != "am_program_narrative":
        return (None, None)
    row = conn.execute(
        "SELECT program_id FROM am_program_narrative WHERE narrative_id=?",
        (narrative_id,),
    ).fetchone()
    if row is None:
        return (None, None)
    pid = row[0]
    canon_row = conn.execute(
        "SELECT canonical_id FROM programs WHERE id=?", (pid,)
    ).fetchone()
    return (pid, canon_row[0] if canon_row else None)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def process_narrative(
    conn: sqlite3.Connection,
    narrative_table: str,
    narrative_id: int,
    body_col: str,
    *,
    dry_run: bool,
) -> dict:
    """Extract entities from one narrative row, write them, evaluate match_rate."""
    row = conn.execute(
        f"SELECT {body_col} FROM {narrative_table} WHERE narrative_id=?",
        (narrative_id,),
    ).fetchone()
    if row is None or not row[0]:
        return {
            "narrative_id": narrative_id,
            "table": narrative_table,
            "entities": 0,
            "match_rate": 1.0,
            "quarantined": False,
        }

    body = str(row[0])
    entities = extract_entities(body)

    parent_pid, parent_entity = _resolve_parent_program(
        conn, narrative_table, narrative_id
    )

    now = datetime.now(UTC).isoformat()
    matched_count = 0
    for ent in entities:
        ok, corpus_table, corpus_pk = match_against_corpus(
            conn, ent, parent_pid, parent_entity
        )
        if ok:
            matched_count += 1
        if dry_run:
            continue
        try:
            conn.execute(
                "INSERT OR IGNORE INTO am_narrative_extracted_entities("
                "  narrative_id, narrative_table, entity_kind, entity_text,"
                "  entity_norm, span_start, span_end, corpus_match,"
                "  corpus_table, corpus_pk, extracted_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    narrative_id,
                    narrative_table,
                    ent["kind"],
                    ent["surface"],
                    ent["norm"],
                    ent["start"],
                    ent["end"],
                    1 if ok else 0,
                    corpus_table,
                    corpus_pk,
                    now,
                ),
            )
        except sqlite3.OperationalError as exc:
            logger.warning(
                "narrative_extract_insert_failed err=%s", str(exc)[:160]
            )

    if dry_run:
        return {
            "narrative_id": narrative_id,
            "table": narrative_table,
            "entities": len(entities),
            "matched": matched_count,
            "match_rate": None,
            "quarantined": False,
        }

    rate = evaluate_match_rate(conn, narrative_id, narrative_table)
    quarantined = False
    if rate <= THRESHOLD:
        quarantined = True
        try:
            conn.execute(
                "INSERT OR IGNORE INTO am_narrative_quarantine("
                "  narrative_id, narrative_table, reason, match_rate, detected_at"
                ") VALUES (?,?,?,?,?)",
                (narrative_id, narrative_table, "low_match_rate", rate, now),
            )
            conn.execute(
                f"UPDATE {narrative_table} SET is_active=0 "
                "WHERE narrative_id=?",
                (narrative_id,),
            )
        except sqlite3.OperationalError as exc:
            logger.warning(
                "quarantine_write_failed table=%s id=%d err=%s",
                narrative_table,
                narrative_id,
                str(exc)[:160],
            )
    return {
        "narrative_id": narrative_id,
        "table": narrative_table,
        "entities": len(entities),
        "matched": matched_count,
        "match_rate": rate,
        "quarantined": quarantined,
    }


def run(
    *,
    db_path: Path,
    table: str | None,
    narrative_id: int | None,
    all_tables: bool,
    limit: int | None,
    dry_run: bool,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables: list[str]
        if narrative_id is not None and table:
            tables = [table]
        elif all_tables:
            tables = list(NARRATIVE_TABLES)
        elif table:
            tables = [table]
        else:
            tables = ["am_program_narrative"]

        summary = {
            "started_at": datetime.now(UTC).isoformat(),
            "dry_run": dry_run,
            "tables_processed": [],
            "narratives_processed": 0,
            "quarantined": 0,
        }
        for tbl in tables:
            try:
                body_col = _resolve_body_column(conn, tbl)
            except (RuntimeError, sqlite3.OperationalError) as exc:
                logger.warning(
                    "skip_table_no_body table=%s err=%s", tbl, str(exc)[:160]
                )
                continue

            if narrative_id is not None:
                ids: list[int] = [narrative_id]
            else:
                q = f"SELECT narrative_id FROM {tbl} WHERE is_active=1"
                if limit:
                    q += f" LIMIT {int(limit)}"
                try:
                    ids = [r[0] for r in conn.execute(q).fetchall()]
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "skip_table_no_active_col table=%s err=%s",
                        tbl,
                        str(exc)[:160],
                    )
                    continue

            for nid in ids:
                result = process_narrative(
                    conn, tbl, int(nid), body_col, dry_run=dry_run
                )
                summary["narratives_processed"] += 1
                if result.get("quarantined"):
                    summary["quarantined"] += 1
            summary["tables_processed"].append(tbl)

        if not dry_run:
            conn.commit()
        summary["finished_at"] = datetime.now(UTC).isoformat()
        return summary
    finally:
        conn.close()


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.offline.extract_narrative_entities")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="§10.10 narrative entity extractor (operator side, no LLM)"
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: $AUTONOMATH_DB_PATH or ./autonomath.db)",
    )
    p.add_argument("--table", type=str, default=None, choices=NARRATIVE_TABLES)
    p.add_argument("--narrative-id", type=int, default=None)
    p.add_argument("--all-tables", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def _resolve_db_path(arg_path: Path | None) -> Path:
    if arg_path:
        return arg_path
    import os

    env = os.environ.get("AUTONOMATH_DB_PATH")
    if env:
        return Path(env)
    return Path("./autonomath.db")


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = _resolve_db_path(args.db)
    if args.dry_run and not db_path.exists():
        # Smoke / completion mode: just verify module load + SQL prepare path.
        logger.info(
            "dry_run_module_smoke db_missing=%s entities_extracted=%d",
            db_path,
            len(extract_entities("テスト 1,000万円 令和5年 https://example.go.jp")),
        )
        return 0
    summary = run(
        db_path=db_path,
        table=args.table,
        narrative_id=args.narrative_id,
        all_tables=args.all_tables,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    logger.info(
        "extract_done processed=%d quarantined=%d dry_run=%s",
        summary.get("narratives_processed", 0),
        summary.get("quarantined", 0),
        bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
