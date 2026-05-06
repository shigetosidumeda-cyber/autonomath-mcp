#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Local sentence-transformers embedding for the 7-corpus jpcite pipeline (operator-only).

Operator-only offline script. Not callable from production runtime.

PURPOSE (corpus pre-embedding pipeline 強化):
    The jpcite hybrid retrieval surface (BM25 + cosine) needs ANN over
    the following 7 production corpora. Each corpus has a dedicated
    sqlite-vec virtual table (`am_entities_vec_<tier>`) keyed by an
    integer rowid pulled from the source row's stable PK.

        +-----+---------------------------+----------------------+----------------------+
        | T   | source_table              | source_db            | vec_table            |
        +-----+---------------------------+----------------------+----------------------+
        | S   | programs                  | data/jpintel.db      | am_entities_vec_S    |
        | L   | am_law_article            | autonomath.db        | am_entities_vec_L    |
        | C   | case_studies              | data/jpintel.db      | am_entities_vec_C    |
        | T   | nta_tsutatsu_index        | autonomath.db        | am_entities_vec_T    |
        | K   | nta_saiketsu              | autonomath.db        | am_entities_vec_K    |
        | J   | court_decisions           | data/jpintel.db      | am_entities_vec_J    |
        | A   | jpi_adoption_records      | autonomath.db        | am_entities_vec_A    |
        +-----+---------------------------+----------------------+----------------------+

    All embeddings are computed locally with `intfloat/multilingual-e5-large`
    (1024-dim, normalize_embeddings=True). NO LLM API call — sentence-
    transformers downloads weights from the Hugging Face Hub once and
    runs inference entirely on the operator's machine.

    `feedback_no_operator_llm_api` の遵守:
      - anthropic / openai / google.generativeai の import 行ゼロ
      - ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY 等の
        環境変数参照ゼロ
      - 全推論はローカルマシン上で完結 (sentence-transformers + torch)

VEC TABLES (NEW — see migration TODO below):
    The 7 vec tables `am_entities_vec_<S/L/C/T/K/J/A>` are NOT created
    by this script (per task scope). They must exist before a non-dry
    run is launched. A separate migration agent should land:

        CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_S USING vec0(
            entity_id INTEGER PRIMARY KEY,
            embedding float[1024]
        );
        -- repeat for _L _C _T _K _J _A

    Until those CREATE statements land, INSERT path will raise
    `sqlite3.OperationalError: no such table`. `--dry-run` does NOT
    touch the vec tables and is safe to run anytime.

USAGE:
    # 7 corpus 全部の SELECT count を確認 (model load 不要)
    python tools/offline/embed_corpus_local.py --dry-run

    # 1 corpus だけ count
    python tools/offline/embed_corpus_local.py --dry-run --corpus programs

    # 実走 (programs corpus, 5000 件 cap)
    python tools/offline/embed_corpus_local.py --corpus programs --max-rows 5000

    # resume-safe 実走: 既存 vec entity_id は skip し、未埋め分だけ処理
    python tools/offline/embed_corpus_local.py --corpus laws --max-rows 5000

    # 既存 vec を意図的に再生成する場合だけ明示
    python tools/offline/embed_corpus_local.py --corpus laws --replace-existing

    # 残り 6 corpus を順次走らせる場合 (別 invocation 推奨):
    for c in laws cases tsutatsu saiketsu court adoptions; do
        python tools/offline/embed_corpus_local.py --corpus $c
    done

OUTPUT:
    `am_entities_vec_<tier>` (sqlite-vec virtual table) に
    entity_id (= source row PK as INTEGER) + 1024-dim float32 embedding
    を書き込む。デフォルトは既存 entity_id を skip する resume-safe
    mode。既存 vec の再生成は `--replace-existing` を明示する。
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"

LOG = logging.getLogger("embed_corpus_local")

MODEL_NAME = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024
DEFAULT_BATCH_SIZE = 64

# multilingual-e5 系列は "passage:" prefix を corpus 側に推奨
# (query 側は "query:" prefix。検索 path は別 module で対応)
E5_PASSAGE_PREFIX = "passage: "


# ---------------------------------------------------------------------------
# Corpus dispatch table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorpusSpec:
    """One row per corpus. Encapsulates SELECT + dest vec table."""

    key: str  # CLI key (programs / laws / ...)
    tier: str  # vec table tier letter (S / L / C / ...)
    source_db: str  # 'jpintel' or 'autonomath'
    source_table: str  # source SQL table name
    vec_table: str  # destination am_entities_vec_<tier>
    select_sql: str  # SELECT id_int, text_for_embed FROM ...
    count_sql: str  # SELECT COUNT(*) FROM ... matching select_sql WHERE


def _programs_select() -> tuple[str, str]:
    # programs.unified_id is TEXT; vec0 needs INTEGER PK so we use rowid.
    # text_for_embed = primary_name + authority_name + program_kind +
    #                  prefecture + municipality (sparse but high-signal).
    sql = """
        SELECT p.rowid AS id_int,
               TRIM(
                 COALESCE(p.primary_name,'') || '\n' ||
                 COALESCE(p.authority_name,'') || ' ' ||
                 COALESCE(p.program_kind,'') || ' ' ||
                 COALESCE(p.prefecture,'') || ' ' ||
                 COALESCE(p.municipality,'')
               ) AS text_for_embed
          FROM programs p
         WHERE p.excluded = 0
           AND p.tier IN ('S','A','B','C')
           AND p.primary_name IS NOT NULL
           AND p.primary_name != ''
         ORDER BY p.rowid ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM programs "
        "WHERE excluded=0 AND tier IN ('S','A','B','C') "
        "AND primary_name IS NOT NULL AND primary_name != ''"
    )
    return sql, cnt


def _laws_select() -> tuple[str, str]:
    # am_law_article.article_id is INTEGER PK — perfect for vec0 entity_id.
    # text_for_embed = title + text_summary + first 1000 chars of text_full.
    sql = """
        SELECT a.article_id AS id_int,
               TRIM(
                 COALESCE(a.title,'') || '\n' ||
                 COALESCE(a.text_summary,'') || '\n' ||
                 COALESCE(SUBSTR(a.text_full, 1, 1000),'')
               ) AS text_for_embed
          FROM am_law_article a
         WHERE COALESCE(a.title,'') || COALESCE(a.text_summary,'') ||
               COALESCE(a.text_full,'') != ''
         ORDER BY a.article_id ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM am_law_article "
        "WHERE COALESCE(title,'') || COALESCE(text_summary,'') "
        "|| COALESCE(text_full,'') != ''"
    )
    return sql, cnt


def _cases_select() -> tuple[str, str]:
    # case_studies.case_id is TEXT — use rowid for vec PK.
    sql = """
        SELECT c.rowid AS id_int,
               TRIM(
                 COALESCE(c.case_title,'') || '\n' ||
                 COALESCE(c.case_summary,'') || '\n' ||
                 COALESCE(c.source_excerpt,'')
               ) AS text_for_embed
          FROM case_studies c
         WHERE COALESCE(c.case_title,'') || COALESCE(c.case_summary,'')
               || COALESCE(c.source_excerpt,'') != ''
         ORDER BY c.rowid ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM case_studies "
        "WHERE COALESCE(case_title,'') || COALESCE(case_summary,'') "
        "|| COALESCE(source_excerpt,'') != ''"
    )
    return sql, cnt


def _tsutatsu_select() -> tuple[str, str]:
    # nta_tsutatsu_index.id is INTEGER PK.
    sql = """
        SELECT t.id AS id_int,
               TRIM(
                 COALESCE(t.code,'') || ' ' ||
                 COALESCE(t.title,'') || '\n' ||
                 COALESCE(t.body_excerpt,'')
               ) AS text_for_embed
          FROM nta_tsutatsu_index t
         WHERE COALESCE(t.title,'') || COALESCE(t.body_excerpt,'') != ''
         ORDER BY t.id ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM nta_tsutatsu_index "
        "WHERE COALESCE(title,'') || COALESCE(body_excerpt,'') != ''"
    )
    return sql, cnt


def _saiketsu_select() -> tuple[str, str]:
    # nta_saiketsu.id is INTEGER PK.
    sql = """
        SELECT s.id AS id_int,
               TRIM(
                 COALESCE(s.title,'') || '\n' ||
                 COALESCE(s.decision_summary,'') || '\n' ||
                 COALESCE(SUBSTR(s.fulltext, 1, 1000),'')
               ) AS text_for_embed
          FROM nta_saiketsu s
         WHERE COALESCE(s.title,'') || COALESCE(s.decision_summary,'')
               || COALESCE(s.fulltext,'') != ''
         ORDER BY s.id ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM nta_saiketsu "
        "WHERE COALESCE(title,'') || COALESCE(decision_summary,'') "
        "|| COALESCE(fulltext,'') != ''"
    )
    return sql, cnt


def _court_select() -> tuple[str, str]:
    # court_decisions.unified_id is TEXT (HAN-...) — use rowid.
    sql = """
        SELECT j.rowid AS id_int,
               TRIM(
                 COALESCE(j.case_name,'') || '\n' ||
                 COALESCE(j.key_ruling,'') || '\n' ||
                 COALESCE(j.impact_on_business,'') || '\n' ||
                 COALESCE(j.source_excerpt,'')
               ) AS text_for_embed
          FROM court_decisions j
         WHERE COALESCE(j.case_name,'') || COALESCE(j.key_ruling,'')
               || COALESCE(j.impact_on_business,'')
               || COALESCE(j.source_excerpt,'') != ''
         ORDER BY j.rowid ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM court_decisions "
        "WHERE COALESCE(case_name,'') || COALESCE(key_ruling,'') "
        "|| COALESCE(impact_on_business,'') "
        "|| COALESCE(source_excerpt,'') != ''"
    )
    return sql, cnt


def _adoptions_select() -> tuple[str, str]:
    # jpi_adoption_records.id is INTEGER PK.
    sql = """
        SELECT a.id AS id_int,
               TRIM(
                 COALESCE(a.program_name_raw,'') || ' ' ||
                 COALESCE(a.company_name_raw,'') || ' ' ||
                 COALESCE(a.project_title,'') || ' ' ||
                 COALESCE(a.industry_raw,'') || ' ' ||
                 COALESCE(a.prefecture,'') || ' ' ||
                 COALESCE(a.municipality,'')
               ) AS text_for_embed
          FROM jpi_adoption_records a
         WHERE COALESCE(a.program_name_raw,'') || COALESCE(a.project_title,'')
               || COALESCE(a.company_name_raw,'') != ''
         ORDER BY a.id ASC
    """
    cnt = (
        "SELECT COUNT(*) FROM jpi_adoption_records "
        "WHERE COALESCE(program_name_raw,'') || COALESCE(project_title,'') "
        "|| COALESCE(company_name_raw,'') != ''"
    )
    return sql, cnt


def _build_corpus_specs() -> dict[str, CorpusSpec]:
    rows: list[tuple[str, str, str, str, Callable[[], tuple[str, str]]]] = [
        ("programs", "S", "jpintel", "programs", _programs_select),
        ("laws", "L", "autonomath", "am_law_article", _laws_select),
        ("cases", "C", "jpintel", "case_studies", _cases_select),
        ("tsutatsu", "T", "autonomath", "nta_tsutatsu_index", _tsutatsu_select),
        ("saiketsu", "K", "autonomath", "nta_saiketsu", _saiketsu_select),
        ("court", "J", "jpintel", "court_decisions", _court_select),
        ("adoptions", "A", "autonomath", "jpi_adoption_records", _adoptions_select),
    ]
    out: dict[str, CorpusSpec] = {}
    for key, tier, source_db, source_table, fn in rows:
        sel, cnt = fn()
        out[key] = CorpusSpec(
            key=key,
            tier=tier,
            source_db=source_db,
            source_table=source_table,
            vec_table=f"am_entities_vec_{tier}",
            select_sql=sel,
            count_sql=cnt,
        )
    return out


CORPUS_SPECS: dict[str, CorpusSpec] = _build_corpus_specs()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def open_conn(
    spec: CorpusSpec, jpintel_db: Path, autonomath_db: Path
) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Return (src_conn, vec_conn).

    - src_conn: where SELECT runs (jpintel.db or autonomath.db per spec).
    - vec_conn: always autonomath.db (where am_entities_vec_<tier> live),
      with sqlite-vec extension loaded.
    When source_db == 'autonomath', src_conn IS vec_conn (single connection).
    """
    if not autonomath_db.exists():
        raise SystemExit(f"db not found: {autonomath_db}")
    vec_conn = sqlite3.connect(autonomath_db, timeout=120.0)
    # WAL is already enabled on autonomath.db; bump per-statement
    # busy_timeout so commits wait through sibling writers (precompute /
    # pytest / etl) instead of crashing on `database is locked`.
    vec_conn.execute("PRAGMA busy_timeout = 120000")
    # MANDATORY: sqlite-vec must be loaded on every per-corpus connection.
    # Without this, INSERTs into am_entities_vec_<tier> raise
    # `no such table` even though the virtual tables exist on disk —
    # vec0 vtables are only visible to connections that have loaded
    # the extension. Failure is fatal (no silent fallback).
    try:
        vec_conn.enable_load_extension(True)
    except AttributeError as exc:
        raise SystemExit(
            "sqlite3 build does not support enable_load_extension; "
            "rebuild Python with --enable-loadable-sqlite-extensions "
            "or use a venv whose python links sqlite3 with extension "
            f"support. Original: {exc}"
        ) from exc
    try:
        import sqlite_vec  # type: ignore

        sqlite_vec.load(vec_conn)
    except Exception as exc:  # noqa: BLE001
        try:
            vec_conn.load_extension("vec0")
        except sqlite3.OperationalError as exc2:
            raise SystemExit(
                f"sqlite-vec load failed (sqlite_vec={exc}; vec0={exc2}); "
                "non-dry run cannot proceed. pip install sqlite-vec in "
                "the active venv."
            ) from exc2
    finally:
        with contextlib.suppress(AttributeError, sqlite3.OperationalError):
            vec_conn.enable_load_extension(False)

    if spec.source_db == "autonomath":
        return vec_conn, vec_conn

    if not jpintel_db.exists():
        raise SystemExit(f"db not found: {jpintel_db}")
    src_conn = sqlite3.connect(jpintel_db, timeout=120.0)
    src_conn.execute("PRAGMA busy_timeout = 120000")
    return src_conn, vec_conn


def count_rows(conn: sqlite3.Connection, spec: CorpusSpec) -> int:
    try:
        row = conn.execute(spec.count_sql).fetchone()
    except sqlite3.OperationalError as exc:
        LOG.error("count failed for %s (%s): %s", spec.key, spec.source_table, exc)
        return -1
    return int(row[0]) if row else 0


def load_existing_entity_ids(
    conn: sqlite3.Connection, vec_table: str, *, required: bool
) -> set[int] | None:
    """Return already embedded entity_id values from a vec0 table."""
    try:
        rows = conn.execute(f"SELECT entity_id FROM {vec_table}").fetchall()
    except sqlite3.OperationalError as exc:
        if not required:
            LOG.warning(
                "cannot read existing ids from %s during dry-run: %s",
                vec_table,
                exc,
            )
            return None
        raise SystemExit(
            f"cannot read existing ids from {vec_table}: {exc}. "
            "Run migrations/create vec tables before non-dry embedding."
        ) from exc
    return {int(row[0]) for row in rows if row and row[0] is not None}


def iter_rows(
    conn: sqlite3.Connection, spec: CorpusSpec, max_rows: int | None
) -> Iterator[tuple[int, str]]:
    sql = spec.select_sql
    if max_rows is not None and max_rows > 0:
        sql = sql.rstrip() + f"\n         LIMIT {int(max_rows)}"
    cur = conn.execute(sql)
    for row in cur:
        rid, txt = row
        if rid is None or not txt:
            continue
        try:
            rid_int = int(rid)
        except (TypeError, ValueError):
            continue
        yield rid_int, txt.strip()


def upsert_embedding(
    conn: sqlite3.Connection, vec_table: str, rowid: int, embedding_bytes: bytes
) -> None:
    # sqlite-vec vec0 vtables do NOT honor INSERT OR REPLACE — the
    # `entity_id INTEGER PRIMARY KEY` declaration triggers a UNIQUE
    # constraint failure on duplicate entity_id even with OR REPLACE.
    # Resume-safe path is explicit DELETE + INSERT.
    conn.execute(f"DELETE FROM {vec_table} WHERE entity_id = ?", (rowid,))
    conn.execute(
        f"INSERT INTO {vec_table}(entity_id, embedding) VALUES (?, ?)",
        (rowid, embedding_bytes),
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def load_model(model_name: str):
    """sentence-transformers の SentenceTransformer をロード.

    Anthropic / OpenAI / Google の SDK は一切 import しない。
    sentence-transformers は Hugging Face Hub からモデルを download
    するだけで、外部 API call は発生しない。
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        LOG.error(
            "sentence-transformers (or torch) is not installed. "
            "Run: pip install sentence-transformers torch (in .venv). "
            "Original error: %s",
            exc,
        )
        raise SystemExit(2) from exc
    LOG.info("loading model %s ... (first run downloads ~2.2 GB)", model_name)
    t0 = time.time()
    model = SentenceTransformer(model_name)
    LOG.info("model loaded in %.1fs", time.time() - t0)
    return model


def embed_batch(model, texts: list[str]):
    """encode 1 batch, normalize_embeddings=True (cosine 比較用)."""
    inputs = [E5_PASSAGE_PREFIX + t for t in texts]
    return model.encode(
        inputs,
        batch_size=len(inputs),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )


# ---------------------------------------------------------------------------
# Per-corpus driver
# ---------------------------------------------------------------------------


def run_corpus(
    spec: CorpusSpec,
    jpintel_db: Path,
    autonomath_db: Path,
    batch_size: int,
    max_rows: int | None,
    model_name: str,
    dry_run: bool,
    replace_existing: bool,
) -> dict:
    """Returns dict report for the corpus (stable shape for caller)."""
    LOG.info(
        "---- corpus=%s tier=%s source=%s.%s vec=%s ----",
        spec.key,
        spec.tier,
        spec.source_db,
        spec.source_table,
        spec.vec_table,
    )
    src_conn, vec_conn = open_conn(spec, jpintel_db, autonomath_db)
    try:
        total = count_rows(src_conn, spec)
        LOG.info("[%s] candidate row count: %d", spec.key, total)
        existing_ids = load_existing_entity_ids(vec_conn, spec.vec_table, required=not dry_run)
        existing_count = len(existing_ids) if existing_ids is not None else -1
        resume_mode = not replace_existing
        LOG.info(
            "[%s] existing vec rows: %s resume_skip_existing=%s",
            spec.key,
            existing_count if existing_count >= 0 else "unknown",
            resume_mode,
        )

        if dry_run:
            return {
                "corpus": spec.key,
                "tier": spec.tier,
                "vec_table": spec.vec_table,
                "candidate_rows": total,
                "existing_rows": existing_count,
                "remaining_rows": (
                    max(total - existing_count, 0)
                    if resume_mode and existing_count >= 0
                    else total
                    if not resume_mode
                    else -1
                ),
                "embedded": 0,
                "skipped_existing": 0,
                "skipped_empty": 0,
                "dry_run": True,
                "replace_existing": replace_existing,
            }

        # non-dry: load model lazily (so dry-run never needs torch)
        model = load_model(model_name)
        smoke = embed_batch(model, ["smoke"])
        actual_dim = int(smoke.shape[-1])
        if actual_dim != EMBEDDING_DIM:
            LOG.error("model output dim %d != expected %d.", actual_dim, EMBEDDING_DIM)
            raise SystemExit(3)
        LOG.info("[%s] smoke encode ok, dim=%d", spec.key, actual_dim)

        # tqdm progress (optional; degrade gracefully if unavailable)
        try:
            from tqdm import tqdm
        except ImportError:

            def tqdm(it, **_kw):  # type: ignore
                return it

        embedded = 0
        skipped_existing = 0
        skipped_empty = 0
        batch_rids: list[int] = []
        batch_texts: list[str] = []

        # In resume mode, max_rows caps newly embedded rows, not source rows.
        # This avoids a no-op run when the first N source rows are already
        # present in the vec table.
        source_limit = max_rows if replace_existing else None
        bar_total = min(total, max_rows) if replace_existing and max_rows else total
        rows_iter = iter_rows(src_conn, spec, source_limit)
        bar = tqdm(rows_iter, total=bar_total, desc=f"embed:{spec.key}", unit="row")

        def flush() -> None:
            nonlocal embedded, batch_rids, batch_texts
            if not batch_rids:
                return
            vecs = embed_batch(model, batch_texts)
            for rid, vec in zip(batch_rids, vecs, strict=True):
                upsert_embedding(vec_conn, spec.vec_table, rid, vec.tobytes())
                embedded += 1
            vec_conn.commit()
            batch_rids = []
            batch_texts = []

        for rid, text in bar:
            if resume_mode and existing_ids is not None and rid in existing_ids:
                skipped_existing += 1
                continue
            if not text:
                skipped_empty += 1
                continue
            batch_rids.append(rid)
            batch_texts.append(text)
            if len(batch_rids) >= batch_size:
                flush()
            if resume_mode and max_rows is not None and embedded + len(batch_rids) >= max_rows:
                break
        flush()

        LOG.info(
            "[%s] done. embedded=%d skipped_existing=%d skipped_empty=%d "
            "candidate=%d existing_before=%d",
            spec.key,
            embedded,
            skipped_existing,
            skipped_empty,
            total,
            existing_count,
        )
        return {
            "corpus": spec.key,
            "tier": spec.tier,
            "vec_table": spec.vec_table,
            "candidate_rows": total,
            "existing_rows": existing_count,
            "remaining_rows": max(total - existing_count - embedded, 0) if resume_mode else 0,
            "embedded": embedded,
            "skipped_existing": skipped_existing,
            "skipped_empty": skipped_empty,
            "dry_run": False,
            "replace_existing": replace_existing,
        }
    finally:
        with contextlib.suppress(Exception):
            src_conn.close()
        if vec_conn is not src_conn:
            with contextlib.suppress(Exception):
                vec_conn.close()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    p.add_argument(
        "--corpus",
        default="all",
        choices=["all", *CORPUS_SPECS.keys()],
        help="どの corpus を embed するか (default 'all')",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="本 invocation で 1 corpus あたり embed する row 上限. 0 = 無制限 (default 0)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"encode 1 batch あたりの text 数 (default {DEFAULT_BATCH_SIZE})",
    )
    p.add_argument(
        "--model", default=MODEL_NAME, help=f"sentence-transformers model id (default {MODEL_NAME})"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="各 corpus の SELECT count を報告して終了 (model load + DB 書込みなし、torch 不要)",
    )
    p.add_argument(
        "--replace-existing",
        action="store_true",
        help="既存 vec entity_id も DELETE+INSERT で再生成する。"
        "未指定時は既存 vec を skip して resume する",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    targets: list[CorpusSpec] = (
        list(CORPUS_SPECS.values()) if args.corpus == "all" else [CORPUS_SPECS[args.corpus]]
    )

    max_rows = None if args.max_rows == 0 else args.max_rows

    reports: list[dict] = []
    for spec in targets:
        rep = run_corpus(
            spec=spec,
            jpintel_db=args.jpintel_db,
            autonomath_db=args.autonomath_db,
            batch_size=args.batch_size,
            max_rows=max_rows,
            model_name=args.model,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
        )
        reports.append(rep)

    # Summary: stable 1-line-per-corpus rollup that the caller can grep.
    LOG.info("==== summary ====")
    grand_candidate = 0
    grand_embedded = 0
    for r in reports:
        LOG.info(
            "  %-9s tier=%s vec=%-22s candidate=%6d existing=%6d "
            "remaining=%6d embedded=%6d skipped_existing=%6d "
            "skipped_empty=%5d dry_run=%s replace_existing=%s",
            r["corpus"],
            r["tier"],
            r["vec_table"],
            max(r["candidate_rows"], 0),
            r["existing_rows"],
            r["remaining_rows"],
            r["embedded"],
            r["skipped_existing"],
            r["skipped_empty"],
            r["dry_run"],
            r["replace_existing"],
        )
        grand_candidate += max(r["candidate_rows"], 0)
        grand_embedded += r["embedded"]
    LOG.info("  TOTAL candidate=%d embedded=%d", grand_candidate, grand_embedded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
