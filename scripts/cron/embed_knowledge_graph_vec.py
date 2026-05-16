#!/usr/bin/env python3
"""Knowledge-graph 503k entity sqlite-vec embed cron (Wave 34 Axis 4e).

Uses local sentence-transformers inference (no LLM API). When the model
file is not available falls back to a deterministic hash vector so smoke
tests pass without external downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import struct
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("embed_knowledge_graph_vec")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_BATCH = 256

HASH_FALLBACK_DIM = 384
HASH_FALLBACK_MODEL = "hash-fallback-v1"

KIND_TO_VEC_TABLE = {
    "program": "am_entities_vec_S",
    "case_study": "am_entities_vec_C",
    "court_decision": "am_entities_vec_J",
    "adoption": "am_entities_vec_A",
    "corporate_entity": "am_entities_vec_E",
    "statistic": "am_entities_vec_T",
    "tax_measure": "am_entities_vec_T",
    "enforcement": "am_entities_vec_F",
    "invoice_registrant": "am_entities_vec_I",
    "law": "am_entities_vec_L",
    "certification": "am_entities_vec_R",
    "authority": "am_entities_vec_R",
    "document": "am_entities_vec_R",
}


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_tables(conn):
    sql_path = _REPO / "scripts" / "migrations" / "239_am_knowledge_graph_vec_index.sql"
    if sql_path.exists():
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())


def _load_sqlite_vec(conn):
    try:
        conn.enable_load_extension(True)
    except (sqlite3.OperationalError, AttributeError):
        return False
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        sqlite_vec.load(conn)
        return True
    except (ImportError, sqlite3.OperationalError) as exc:
        LOG.debug("sqlite-vec load skipped: %s", exc)
        return False


def _load_embed_model(model_name):
    if model_name == HASH_FALLBACK_MODEL:
        return None, HASH_FALLBACK_DIM, HASH_FALLBACK_MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        model = SentenceTransformer(model_name)
        dim = int(model.get_sentence_embedding_dimension() or HASH_FALLBACK_DIM)
        return model, dim, model_name
    except (ImportError, OSError, RuntimeError) as exc:
        LOG.warning(
            "sentence-transformers '%s' unavailable (%s); using hash fallback", model_name, exc
        )
        return None, HASH_FALLBACK_DIM, HASH_FALLBACK_MODEL


def _hash_vector(text, dim=HASH_FALLBACK_DIM):
    text = (text or "").strip() or " "
    out = []
    seed = text.encode("utf-8")
    h = hashlib.sha256(seed).digest()
    while len(out) < dim:
        out.extend((b - 127.5) / 127.5 for b in h)
        h = hashlib.sha256(h).digest()
    return out[:dim]


def _embed(model, text, dim):
    if model is None:
        return _hash_vector(text, dim=dim)
    try:
        vec = model.encode(text, normalize_embeddings=True)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("embed encode failed (%s); using hash fallback", exc)
        return _hash_vector(text, dim=dim)
    try:
        return [float(x) for x in vec]
    except (TypeError, ValueError):
        return _hash_vector(text, dim=dim)


def _ensure_vec_table(conn, table, dim):
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            f"entity_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
        )
        return True
    except sqlite3.OperationalError as exc:
        LOG.warning("vec0 table %s create failed (%s)", table, exc)
        return False


def _serialize_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _text_for_entity(conn, canonical_id):
    try:
        row = conn.execute(
            "SELECT primary_name, record_kind, raw_json FROM am_entities WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
    except sqlite3.Error:
        return canonical_id
    if row is None:
        return canonical_id
    chunks = [row["primary_name"] or "", row["record_kind"] or ""]
    raw = row["raw_json"]
    if raw:
        try:
            data = json.loads(raw)
            for k in ("description", "summary", "abstract", "title", "name"):
                v = data.get(k) if isinstance(data, dict) else None
                if v and isinstance(v, str):
                    chunks.append(v[:512])
                    break
        except (json.JSONDecodeError, TypeError):
            pass
    return " ".join(c for c in chunks if c).strip()


def _candidate_entities(conn, mode, model_id, max_entities):
    sql = "SELECT canonical_id, record_kind FROM am_entities"
    params = ()
    if mode == "incremental":
        sql = (
            "SELECT e.canonical_id, e.record_kind FROM am_entities e "
            "LEFT JOIN am_entities_vec_embed_log l "
            "  ON l.canonical_id = e.canonical_id AND l.model_name = ? "
            "WHERE l.canonical_id IS NULL "
            "ORDER BY e.canonical_id"
        )
        params = (model_id,)
    else:
        sql += " ORDER BY canonical_id"
    if max_entities is not None:
        sql += f" LIMIT {int(max_entities)}"
    try:
        return [(r[0], r[1]) for r in conn.execute(sql, params)]
    except sqlite3.Error as exc:
        LOG.warning("candidate walk failed (%s)", exc)
        return []


def refresh(
    db_path,
    *,
    mode="incremental",
    dry_run=False,
    max_entities=None,
    model_name="intfloat/multilingual-e5-small",
    batch_size=DEFAULT_BATCH,
):
    if mode not in ("full", "incremental"):
        raise ValueError(f"invalid mode: {mode}")
    refresh_id = f"vec_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info("embed_knowledge_graph_vec start id=%s mode=%s db=%s", refresh_id, mode, db_path)

    conn = _connect(db_path)
    _ensure_tables(conn)
    vec_loaded = _load_sqlite_vec(conn)
    LOG.info("sqlite-vec loaded=%s", vec_loaded)

    model, dim, model_id = _load_embed_model(model_name)
    LOG.info("embed model_id=%s dim=%d", model_id, dim)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_entities_vec_refresh_log "
            "(refresh_id, mode, started_at, model_name, embed_dim) VALUES (?,?,?,?,?)",
            (refresh_id, mode, started_at, model_id, dim),
        )
        conn.commit()

    vec_table_ready = {}
    for table in set(KIND_TO_VEC_TABLE.values()):
        vec_table_ready[table] = vec_loaded and _ensure_vec_table(conn, table, dim)

    candidates = _candidate_entities(conn, mode, model_id, max_entities)
    LOG.info("candidate entities=%d", len(candidates))

    processed = 0
    skipped = 0
    t0 = time.time()
    refreshed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")

    for i, (cid, kind) in enumerate(candidates):
        text = _text_for_entity(conn, cid)
        if not text:
            skipped += 1
            continue
        vec = _embed(model, text, dim)
        table = KIND_TO_VEC_TABLE.get(kind, "am_entities_vec_R")
        text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        if dry_run:
            if i < 5:
                LOG.info("dry-run cid=%s kind=%s table=%s dim=%d", cid, kind, table, len(vec))
            processed += 1
            continue
        if vec_table_ready.get(table, False):
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table}(entity_id, embedding) VALUES (?, ?)",
                    (cid, _serialize_vec(vec)),
                )
            except sqlite3.OperationalError as exc:
                LOG.debug("vec insert failed cid=%s (%s)", cid, exc)
        conn.execute(
            "INSERT OR REPLACE INTO am_entities_vec_embed_log "
            "(canonical_id, record_kind, embed_at, embed_dim, model_name, text_hash) "
            "VALUES (?,?,?,?,?,?)",
            (cid, kind, refreshed_at, dim, model_id, text_hash),
        )
        processed += 1
        if (i + 1) % batch_size == 0:
            conn.commit()
            if (i + 1) % (batch_size * 10) == 0:
                LOG.info("progress %d/%d", i + 1, len(candidates))

    if not dry_run:
        conn.commit()
        conn.execute(
            "UPDATE am_entities_vec_refresh_log SET finished_at = ?, "
            "  entities_processed = ?, entities_skipped = ? WHERE refresh_id = ?",
            (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"), processed, skipped, refresh_id),
        )
        conn.commit()
    conn.close()
    LOG.info("embed_knowledge_graph_vec done processed=%d skipped=%d", processed, skipped)
    return {"processed": processed, "skipped": skipped, "dim": dim, "model": model_id, "mode": mode}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-entities", type=int, default=None)
    p.add_argument("--model", default="intfloat/multilingual-e5-small")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = refresh(
        args.autonomath_db,
        mode=args.mode,
        dry_run=args.dry_run,
        max_entities=args.max_entities,
        model_name=args.model,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
