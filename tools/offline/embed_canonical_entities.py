#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, tests/.
"""Local sentence-transformers embedding for canonical (am_entities) corpora.

Operator-only offline script. Not callable from production runtime.

PURPOSE (W28-5 vec coverage gap fix):
    Existing am_entities_vec_<S/L/C/T/K/J/A> (migration 147) are keyed by
    jpintel-side rowids. They have ZERO overlap with am_entities
    canonical_id (TEXT). Real canonical vec coverage = adoption only
    (~100% via jpi_adoption_records.id which happens to be INTEGER and
    shared). Other 6 record_kinds have 0% canonical coverage.

    This populator writes 7 NEW vec tables defined in migration 166:

        +-----------------+-----------------------------------+----------+
        | record_kind     | vec table                         | source   |
        +-----------------+-----------------------------------+----------+
        | program         | am_canonical_vec_program          | facts    |
        | enforcement     | am_canonical_vec_enforcement      | facts    |
        | corporate_entity| am_canonical_vec_corporate        | facts    |
        | statistic       | am_canonical_vec_statistic        | facts    |
        | case_study      | am_canonical_vec_case_study       | facts    |
        | law             | am_canonical_vec_law              | facts    |
        | tax_measure     | am_canonical_vec_tax_measure      | facts    |
        +-----------------+-----------------------------------+----------+

    For each entity, source_text = primary_name + a small set of
    high-signal facts pulled from am_entity_facts. Whitespace-joined.

    All embeddings are computed locally with `intfloat/multilingual-e5-large`
    (1024-dim, normalize_embeddings=True). Same model + dim as migration 147
    so future kNN paths can swap between vec families without re-embedding
    queries.

    `feedback_no_operator_llm_api` の遵守:
      - anthropic / openai / google.generativeai の import 行ゼロ
      - ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY
        の環境変数参照ゼロ
      - 全推論は sentence-transformers + torch ローカル実行

USAGE:
    # 1 kind の候補件数を確認 (model load 不要、高速)
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind program --dry-run

    # 全 kind の候補件数を確認
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind all --dry-run

    # program kind を 11,601 件 embed
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind program

    # resume-safe 実走: map + vec の両方がある canonical_id は skip
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind law --max-rows 5000

    # 既存 canonical vec を意図的に再生成する場合だけ明示
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind law --replace-existing

    # 巨大 kind (corporate_entity 167k) を 5,000 件 sample
    .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind corporate_entity --max-rows 5000

    # 残り全部を background:
    nohup .venv312/bin/python tools/offline/embed_canonical_entities.py \\
        --kind all > /tmp/embed_canonical.log 2>&1 &

OUTPUT:
    am_canonical_vec_<kind> (sqlite-vec virtual table) +
    am_canonical_vec_<kind>_map (sidecar map: synthetic_id ↔ canonical_id).
    デフォルトは map + vec の両方が存在する canonical_id を skip する
    resume-safe mode。既存 vec の再生成は `--replace-existing` を明示。
    書き込み時は map を upsert し、vec0 は DELETE+INSERT (vec0 quirks:
    INSERT OR REPLACE silently fails on duplicate INTEGER PK).
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

LOG = logging.getLogger("embed_canonical_entities")

MODEL_NAME = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024
DEFAULT_BATCH_SIZE = 64

# multilingual-e5 系列は corpus 側に "passage:" prefix を推奨
E5_PASSAGE_PREFIX = "passage: "


# ---------------------------------------------------------------------------
# Per-kind specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KindSpec:
    """One row per record_kind. Encapsulates vec table + key facts."""

    kind: str                       # CLI key (= am_entities.record_kind)
    vec_table: str                  # destination am_canonical_vec_<short>
    map_table: str                  # sidecar mapping table
    # field_names that carry meaningful descriptive text for this kind
    # (subset of am_entity_facts.field_name). NULL/empty values are
    # silently skipped — primary_name from am_entities is always
    # included.
    fact_fields: tuple[str, ...]


# Per-kind text-carrying field selection.
# Truncation cap per fact_value applied at SELECT time (300 chars) so we
# don't pull megabyte fulltexts into the embed buffer.
KIND_SPECS: dict[str, KindSpec] = {
    "program": KindSpec(
        kind="program",
        vec_table="am_canonical_vec_program",
        map_table="am_canonical_vec_program_map",
        fact_fields=(
            "program.authority", "program_kind", "authority_raw",
            "source_excerpt", "doc.form_name", "target_raw",
        ),
    ),
    "enforcement": KindSpec(
        kind="enforcement",
        vec_table="am_canonical_vec_enforcement",
        map_table="am_canonical_vec_enforcement_map",
        fact_fields=(
            "source.title", "source_excerpt", "legal_basis_raw",
            "authority_raw", "company_name",
        ),
    ),
    "corporate_entity": KindSpec(
        kind="corporate_entity",
        vec_table="am_canonical_vec_corporate",
        map_table="am_canonical_vec_corporate_map",
        fact_fields=(
            "corp.legal_name", "corp.legal_name_kana",
            "corp.business_summary", "corp.location",
            "houjin_bangou",
        ),
    ),
    "statistic": KindSpec(
        kind="statistic",
        vec_table="am_canonical_vec_statistic",
        map_table="am_canonical_vec_statistic_map",
        fact_fields=(
            "statistic_source_title", "jsic_name_major",
            "jsic_name_medium", "scale_bucket", "region_level",
        ),
    ),
    "case_study": KindSpec(
        kind="case_study",
        vec_table="am_canonical_vec_case_study",
        map_table="am_canonical_vec_case_study_map",
        fact_fields=(
            "case_title", "case_summary", "company_name",
            "source_excerpt",
        ),
    ),
    "law": KindSpec(
        kind="law",
        vec_table="am_canonical_vec_law",
        map_table="am_canonical_vec_law_map",
        fact_fields=(
            "law.summary", "law.category", "source_excerpt",
            "authority_raw",
        ),
    ),
    "tax_measure": KindSpec(
        kind="tax_measure",
        vec_table="am_canonical_vec_tax_measure",
        map_table="am_canonical_vec_tax_measure_map",
        fact_fields=(
            "tax.subkind", "program_kind", "source_excerpt",
            "authority_raw", "target_raw",
        ),
    ),
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def open_conn(autonomath_db: Path) -> sqlite3.Connection:
    if not autonomath_db.exists():
        raise SystemExit(f"db not found: {autonomath_db}")
    conn = sqlite3.connect(autonomath_db)
    try:
        conn.enable_load_extension(True)
    except AttributeError as exc:
        raise SystemExit(
            "sqlite3 build does not support enable_load_extension; "
            "use a venv whose python links sqlite3 with extension support. "
            f"Original: {exc}"
        )
    try:
        import sqlite_vec  # type: ignore
        sqlite_vec.load(conn)
    except Exception as exc:  # noqa: BLE001
        try:
            conn.load_extension("vec0")
        except sqlite3.OperationalError as exc2:
            raise SystemExit(
                f"sqlite-vec load failed (sqlite_vec={exc}; vec0={exc2}). "
                "pip install sqlite-vec in the active venv."
            )
    finally:
        try:
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError):
            pass
    # Speed up bulk INSERT path; safe for offline operator script.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def count_candidates(conn: sqlite3.Connection, spec: KindSpec) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM am_entities "
        "WHERE record_kind=? AND primary_name IS NOT NULL "
        "AND primary_name != ''",
        (spec.kind,),
    ).fetchone()
    return int(row[0]) if row else 0


def load_existing_canonical_ids(
    conn: sqlite3.Connection, spec: KindSpec, *, required: bool
) -> set[str] | None:
    """Return canonical_id values that already have map + vec rows."""
    try:
        rows = conn.execute(
            f"SELECT m.canonical_id "
            f"FROM {spec.map_table} m "
            f"JOIN {spec.vec_table} v ON v.synthetic_id = m.synthetic_id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if not required:
            LOG.warning(
                "cannot read existing canonical ids from %s during dry-run: %s",
                spec.vec_table, exc,
            )
            return None
        raise SystemExit(
            f"cannot read existing canonical ids from {spec.vec_table}: {exc}. "
            "Run migration 166/create canonical vec tables before non-dry "
            "embedding."
        )
    return {str(row[0]) for row in rows if row and row[0]}


def iter_entities(
    conn: sqlite3.Connection, spec: KindSpec, max_rows: int | None
) -> Iterator[tuple[str, str]]:
    """Yield (canonical_id, source_text) for the kind.

    source_text = primary_name + space-joined high-signal facts (each capped
    at 300 chars, deduplicated, NULL-filtered).
    """
    placeholders = ",".join("?" * len(spec.fact_fields))
    sql = f"""
        SELECT e.canonical_id,
               e.primary_name,
               GROUP_CONCAT(
                 CASE
                   WHEN f.field_value_text IS NOT NULL
                        AND length(f.field_value_text) > 0
                   THEN substr(f.field_value_text, 1, 300)
                   ELSE NULL
                 END,
                 ' | '
               ) AS facts_concat
          FROM am_entities e
          LEFT JOIN am_entity_facts f
                 ON f.entity_id = e.canonical_id
                AND f.field_name IN ({placeholders})
         WHERE e.record_kind = ?
           AND e.primary_name IS NOT NULL
           AND e.primary_name != ''
         GROUP BY e.canonical_id, e.primary_name
         ORDER BY e.canonical_id
    """
    params: tuple = tuple(spec.fact_fields) + (spec.kind,)
    if max_rows is not None and max_rows > 0:
        sql = sql.rstrip() + f"\n         LIMIT {int(max_rows)}"
    cur = conn.execute(sql, params)
    for cid, primary_name, facts_concat in cur:
        if not cid or not primary_name:
            continue
        if facts_concat:
            text = f"{primary_name} {facts_concat}"
        else:
            text = primary_name
        # Strip excess whitespace, cap final length to 2000 chars to
        # keep encode batches predictable.
        text = " ".join(text.split())[:2000]
        if not text:
            continue
        yield cid, text


def upsert_one(
    conn: sqlite3.Connection,
    spec: KindSpec,
    canonical_id: str,
    source_text: str,
    embedding_bytes: bytes,
) -> None:
    """Atomic: ensure map row, then DELETE+INSERT on vec0."""
    # Reuse synthetic_id if canonical_id already mapped, else allocate
    # via AUTOINCREMENT.
    row = conn.execute(
        f"SELECT synthetic_id FROM {spec.map_table} WHERE canonical_id=?",
        (canonical_id,),
    ).fetchone()
    if row is not None:
        sid = int(row[0])
        conn.execute(
            f"UPDATE {spec.map_table} "
            f"SET source_text=?, embedded_at=datetime('now') "
            f"WHERE synthetic_id=?",
            (source_text, sid),
        )
    else:
        cur = conn.execute(
            f"INSERT INTO {spec.map_table} (canonical_id, source_text) "
            f"VALUES (?, ?)",
            (canonical_id, source_text),
        )
        sid = int(cur.lastrowid)

    # vec0 INSERT OR REPLACE quirks → DELETE + INSERT.
    conn.execute(
        f"DELETE FROM {spec.vec_table} WHERE synthetic_id=?",
        (sid,),
    )
    conn.execute(
        f"INSERT INTO {spec.vec_table}(synthetic_id, embedding) "
        f"VALUES (?, ?)",
        (sid, embedding_bytes),
    )


# ---------------------------------------------------------------------------
# Model loader
# ---------------------------------------------------------------------------


def load_model(model_name: str):
    """sentence-transformers local model load. NO API call."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        LOG.error(
            "sentence-transformers (or torch) is not installed in this venv. "
            "Use .venv312 or run: pip install sentence-transformers torch. "
            "Original: %s", exc,
        )
        raise SystemExit(2)
    LOG.info("loading model %s ... (first run downloads ~2.2 GB weights)",
             model_name)
    t0 = time.time()
    model = SentenceTransformer(model_name)
    LOG.info("model loaded in %.1fs", time.time() - t0)
    return model


def embed_batch(model, texts: list[str]):
    """encode 1 batch, normalize_embeddings=True (cosine ready)."""
    inputs = [E5_PASSAGE_PREFIX + t for t in texts]
    return model.encode(
        inputs,
        batch_size=len(inputs),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )


# ---------------------------------------------------------------------------
# Per-kind driver
# ---------------------------------------------------------------------------


def run_kind(
    spec: KindSpec,
    autonomath_db: Path,
    batch_size: int,
    max_rows: int | None,
    model_name: str,
    dry_run: bool,
    replace_existing: bool,
) -> dict:
    LOG.info("---- kind=%s vec=%s ----", spec.kind, spec.vec_table)
    conn = open_conn(autonomath_db)
    try:
        total = count_candidates(conn, spec)
        LOG.info("[%s] candidate row count: %d", spec.kind, total)
        existing_ids = load_existing_canonical_ids(
            conn, spec, required=not dry_run
        )
        existing_count = len(existing_ids) if existing_ids is not None else -1
        resume_mode = not replace_existing
        LOG.info(
            "[%s] existing canonical vec rows: %s resume_skip_existing=%s",
            spec.kind,
            existing_count if existing_count >= 0 else "unknown",
            resume_mode,
        )

        if dry_run:
            return {
                "kind": spec.kind,
                "vec_table": spec.vec_table,
                "candidate_rows": total,
                "existing_rows": existing_count,
                "remaining_rows": (
                    max(total - existing_count, 0)
                    if resume_mode and existing_count >= 0
                    else total if not resume_mode else -1
                ),
                "embedded": 0,
                "skipped_existing": 0,
                "skipped_empty": 0,
                "dry_run": True,
                "replace_existing": replace_existing,
            }

        model = load_model(model_name)
        smoke = embed_batch(model, ["smoke"])
        actual_dim = int(smoke.shape[-1])
        if actual_dim != EMBEDDING_DIM:
            LOG.error("model output dim %d != expected %d.",
                      actual_dim, EMBEDDING_DIM)
            raise SystemExit(3)
        LOG.info("[%s] smoke encode ok, dim=%d", spec.kind, actual_dim)

        try:
            from tqdm import tqdm
        except ImportError:
            def tqdm(it, **_kw):  # type: ignore
                return it

        embedded = 0
        skipped_existing = 0
        skipped_empty = 0
        batch_cids: list[str] = []
        batch_texts: list[str] = []

        # In resume mode, max_rows caps newly embedded rows, not source rows.
        source_limit = max_rows if replace_existing else None
        cap = (
            min(total, max_rows) if replace_existing and max_rows else total
        )
        rows_iter = iter_entities(conn, spec, source_limit)
        bar = tqdm(rows_iter, total=cap,
                   desc=f"embed:{spec.kind}", unit="row")

        def flush() -> None:
            nonlocal embedded, batch_cids, batch_texts
            if not batch_cids:
                return
            vecs = embed_batch(model, batch_texts)
            for cid, txt, vec in zip(batch_cids, batch_texts, vecs,
                                     strict=True):
                upsert_one(conn, spec, cid, txt, vec.tobytes())
                embedded += 1
            conn.commit()
            batch_cids = []
            batch_texts = []

        for cid, text in bar:
            if resume_mode and existing_ids is not None and cid in existing_ids:
                skipped_existing += 1
                continue
            if not text:
                skipped_empty += 1
                continue
            batch_cids.append(cid)
            batch_texts.append(text)
            if len(batch_cids) >= batch_size:
                flush()
            if (
                resume_mode
                and max_rows is not None
                and embedded + len(batch_cids) >= max_rows
            ):
                break
        flush()

        LOG.info(
            "[%s] done. embedded=%d skipped_existing=%d skipped_empty=%d "
            "candidate=%d existing_before=%d",
            spec.kind, embedded, skipped_existing, skipped_empty, total,
            existing_count,
        )
        return {
            "kind": spec.kind,
            "vec_table": spec.vec_table,
            "candidate_rows": total,
            "existing_rows": existing_count,
            "remaining_rows": max(total - existing_count - embedded, 0)
                              if resume_mode else 0,
            "embedded": embedded,
            "skipped_existing": skipped_existing,
            "skipped_empty": skipped_empty,
            "dry_run": False,
            "replace_existing": replace_existing,
        }
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument(
        "--kind", default="all",
        choices=["all", *KIND_SPECS.keys()],
        help="どの am_entities.record_kind を embed するか (default 'all')",
    )
    p.add_argument(
        "--max-rows", type=int, default=0,
        help="本 invocation で 1 kind あたり embed する row 上限. "
             "0 = 無制限 (default 0)",
    )
    p.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"encode 1 batch あたり text 数 (default {DEFAULT_BATCH_SIZE})",
    )
    p.add_argument(
        "--model", default=MODEL_NAME,
        help=f"sentence-transformers model id (default {MODEL_NAME})",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="各 kind の SELECT count を報告して終了 "
             "(model load + DB 書込みなし、torch 不要)",
    )
    p.add_argument(
        "--replace-existing", action="store_true",
        help="既存 canonical vec も DELETE+INSERT で再生成する。未指定時は "
             "map + vec が揃った canonical_id を skip して resume する",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    targets: list[KindSpec] = (
        list(KIND_SPECS.values())
        if args.kind == "all"
        else [KIND_SPECS[args.kind]]
    )
    max_rows = None if args.max_rows == 0 else args.max_rows

    reports: list[dict] = []
    for spec in targets:
        rep = run_kind(
            spec=spec,
            autonomath_db=args.autonomath_db,
            batch_size=args.batch_size,
            max_rows=max_rows,
            model_name=args.model,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
        )
        reports.append(rep)

    LOG.info("==== summary ====")
    grand_candidate = 0
    grand_embedded = 0
    for r in reports:
        LOG.info(
            "  %-18s vec=%-32s candidate=%7d existing=%7d "
            "remaining=%7d embedded=%7d skipped_existing=%7d "
            "skipped_empty=%5d dry_run=%s replace_existing=%s",
            r["kind"], r["vec_table"],
            max(r["candidate_rows"], 0), r["existing_rows"],
            r["remaining_rows"], r["embedded"], r["skipped_existing"],
            r["skipped_empty"], r["dry_run"], r["replace_existing"],
        )
        grand_candidate += max(r["candidate_rows"], 0)
        grand_embedded += r["embedded"]
    LOG.info("  TOTAL candidate=%d embedded=%d",
             grand_candidate, grand_embedded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
