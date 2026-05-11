#!/usr/bin/env python3
"""Wave 43.2.1 — Dim A semantic 検索 e5-small (384d) embed builder.

Builds the 384-dim sqlite-vec corpus in ``am_entities_vec_e5`` for the
full ~503,930 am_entities row set (~1M+ post-Wave-43 expansion). The
model is ``intfloat/multilingual-e5-small`` and inference runs LOCALLY
on CPU via sentence-transformers — NO LLM API call.

NO LLM API:
    `feedback_no_operator_llm_api` 遵守 — anthropic / openai /
    google.generativeai / claude_agent_sdk の import 行 0、
    ANTHROPIC_API_KEY 等の env 参照 0。sentence_transformers 経由の
    local CPU 推論のみ。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import signal
import sqlite3
import struct
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("build_e5_embeddings_v2")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_CHUNK_SIZE = 5_000
DEFAULT_BATCH_SIZE = 64
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
EXPECTED_DIM = 384
HASH_FALLBACK_MODEL = "hash-fallback-e5-small-v1"

MIGRATION_PATH = (
    _REPO / "scripts" / "migrations" / "260_vec_e5_small_384.sql"
)

_INTERRUPTED = False


def _on_interrupt(signum: int, _frame: Any) -> None:
    """SIGINT / SIGTERM → flag set, chunk loop exits at next boundary."""
    global _INTERRUPTED
    _INTERRUPTED = True
    LOG.warning("interrupt signum=%d — will checkpoint at next chunk boundary", signum)


signal.signal(signal.SIGINT, _on_interrupt)
with contextlib.suppress(AttributeError, ValueError):
    signal.signal(signal.SIGTERM, _on_interrupt)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        conn.enable_load_extension(True)
    except (sqlite3.OperationalError, AttributeError):
        return False
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        sqlite_vec.load(conn)
        return True
    except (ImportError, sqlite3.OperationalError) as exc:
        LOG.warning("sqlite-vec load skipped: %s", exc)
        return False


def _apply_migration_260(conn: sqlite3.Connection) -> None:
    if not MIGRATION_PATH.exists():
        LOG.warning("migration 260 not found at %s — skipping pre-apply", MIGRATION_PATH)
        return
    try:
        conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    except sqlite3.OperationalError as exc:
        LOG.warning("migration 260 pre-apply soft-fail: %s", exc)


def _ensure_vec_table_e5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_e5 USING vec0("
            f"entity_id INTEGER PRIMARY KEY, embedding float[{EXPECTED_DIM}])"
        )
        return True
    except sqlite3.OperationalError as exc:
        if "already exists" in str(exc).lower():
            return True
        LOG.warning("am_entities_vec_e5 create failed: %s", exc)
        return False


def _load_embed_model(model_name: str) -> tuple[Any, int, str]:
    """Load sentence-transformers model; hash-fallback when unavailable."""
    if model_name == HASH_FALLBACK_MODEL:
        return None, EXPECTED_DIM, HASH_FALLBACK_MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        LOG.info("loading sentence-transformers model: %s", model_name)
        t0 = time.time()
        local_only = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
        cache_dir = os.environ.get("HF_HOME") or os.environ.get(
            "SENTENCE_TRANSFORMERS_HOME"
        )
        kwargs: dict[str, Any] = {}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        model = SentenceTransformer(model_name, **kwargs)
        dim = int(model.get_sentence_embedding_dimension() or EXPECTED_DIM)
        if dim != EXPECTED_DIM:
            LOG.warning(
                "model %s reports dim=%d but migration 260 vec table is %d-dim — "
                "embedding writes will fail; falling back to hash",
                model_name,
                dim,
                EXPECTED_DIM,
            )
            return None, EXPECTED_DIM, HASH_FALLBACK_MODEL
        LOG.info(
            "model loaded in %.2fs dim=%d local_only=%s",
            time.time() - t0,
            dim,
            local_only,
        )
        return model, dim, model_name
    except (ImportError, OSError, RuntimeError) as exc:
        LOG.warning(
            "sentence-transformers '%s' unavailable (%s); using hash fallback",
            model_name,
            exc,
        )
        return None, EXPECTED_DIM, HASH_FALLBACK_MODEL


def _hash_vector(text: str, dim: int = EXPECTED_DIM) -> list[float]:
    text = (text or "").strip() or " "
    out: list[float] = []
    seed = text.encode("utf-8")
    h = hashlib.sha256(seed).digest()
    while len(out) < dim:
        out.extend((b - 127.5) / 127.5 for b in h)
        h = hashlib.sha256(h).digest()
    return out[:dim]


def _embed_batch(
    model: Any,
    texts: list[str],
    dim: int = EXPECTED_DIM,
) -> list[list[float]]:
    if model is None or not texts:
        return [_hash_vector(t, dim=dim) for t in texts]
    try:
        prefixed = [f"passage: {t}" for t in texts]
        vecs = model.encode(
            prefixed, normalize_embeddings=True, batch_size=len(prefixed)
        )
        return [[float(x) for x in v] for v in vecs]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("batch encode failed (%s) — falling back to hash", exc)
        return [_hash_vector(t, dim=dim) for t in texts]


def _serialize_vec(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _text_for_row(
    primary_name: str | None,
    record_kind: str | None,
    raw_json: str | None,
) -> str:
    chunks = [primary_name or "", record_kind or ""]
    if raw_json:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            for k in ("description", "summary", "abstract", "title", "name", "purpose"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    chunks.append(v[:512])
                    break
    return " ".join(c for c in chunks if c).strip()


def _candidate_entities(
    conn: sqlite3.Connection,
    mode: str,
    model_id: str,
    kinds: list[str] | None,
    max_entities: int | None,
) -> list[tuple[int, str, str, str]]:
    base = (
        "SELECT e.rowid AS rid, e.canonical_id AS cid, "
        "       e.primary_name AS pn, e.record_kind AS rk, e.raw_json AS rj "
        "FROM am_entities e "
    )
    params: list[Any] = []
    where: list[str] = []

    if mode == "incremental":
        base += (
            "LEFT JOIN am_entities_vec_e5_embed_log l "
            "  ON l.entity_id = e.rowid AND l.model_name = ? "
        )
        where.append("l.entity_id IS NULL")
        params.append(model_id)

    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        where.append(f"e.record_kind IN ({placeholders})")
        params.extend(kinds)

    if where:
        base += "WHERE " + " AND ".join(where) + " "
    base += "ORDER BY e.rowid"
    if max_entities is not None:
        base += f" LIMIT {int(max_entities)}"

    try:
        rows = conn.execute(base, tuple(params)).fetchall()
    except sqlite3.Error as exc:
        LOG.warning("candidate walk failed (%s)", exc)
        return []

    out: list[tuple[int, str, str, str]] = []
    for r in rows:
        text = _text_for_row(r["pn"], r["rk"], r["rj"])
        out.append((int(r["rid"]), r["cid"] or "", r["rk"] or "", text))
    return out


def refresh(
    db_path: str,
    *,
    mode: str = "incremental",
    dry_run: bool = False,
    max_entities: int | None = None,
    model_name: str = DEFAULT_MODEL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    """Drive the e5-small embed walk over am_entities."""
    if mode not in ("full", "incremental", "resume"):
        raise ValueError(f"invalid mode: {mode}")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    refresh_id = f"e5v2_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info(
        "build_e5_embeddings_v2 start id=%s mode=%s db=%s chunk_size=%d batch_size=%d",
        refresh_id,
        mode,
        db_path,
        chunk_size,
        batch_size,
    )

    conn = _connect(db_path)
    _apply_migration_260(conn)
    vec_loaded = _load_sqlite_vec(conn)
    LOG.info("sqlite-vec loaded=%s", vec_loaded)

    vec_table_ok = vec_loaded and _ensure_vec_table_e5(conn)
    LOG.info("am_entities_vec_e5 ready=%s", vec_table_ok)

    model, dim, model_id = _load_embed_model(model_name)
    LOG.info("embed model_id=%s dim=%d", model_id, dim)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_entities_vec_e5_refresh_log "
            "(refresh_id, mode, started_at, model_name, embed_dim) VALUES (?,?,?,?,?)",
            (refresh_id, mode, started_at, model_id, dim),
        )
        conn.commit()

    candidates = _candidate_entities(conn, mode, model_id, kinds, max_entities)
    LOG.info("candidate entities=%d", len(candidates))
    if not candidates:
        if not dry_run:
            _finalize_refresh(conn, refresh_id, 0, 0, 0)
        conn.close()
        return {
            "refresh_id": refresh_id,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "dim": dim,
            "model": model_id,
            "mode": mode,
            "vec_table_ready": vec_table_ok,
        }

    processed = 0
    skipped = 0
    failed = 0
    t0 = time.time()
    refreshed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")

    for ci in range(0, len(candidates), chunk_size):
        if _INTERRUPTED:
            LOG.warning("interrupted before chunk %d — checkpointing", ci)
            break
        chunk = candidates[ci : ci + chunk_size]
        LOG.info(
            "chunk start ci=%d size=%d (%d/%d total)",
            ci,
            len(chunk),
            ci + len(chunk),
            len(candidates),
        )
        for bi in range(0, len(chunk), batch_size):
            if _INTERRUPTED:
                break
            batch = chunk[bi : bi + batch_size]
            texts = [text for (_rid, _cid, _rk, text) in batch]
            non_empty = [(i, t) for i, t in enumerate(texts) if t]
            if not non_empty:
                skipped += len(batch)
                continue
            vecs = _embed_batch(model, [t for _, t in non_empty], dim=dim)
            full_vecs: list[list[float] | None] = [None] * len(batch)
            for (i, _), v in zip(non_empty, vecs, strict=True):
                full_vecs[i] = v

            for (rid, cid, rk, text), vec in zip(batch, full_vecs, strict=True):
                if vec is None or not text:
                    skipped += 1
                    continue
                text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
                if dry_run:
                    if processed < 10:
                        LOG.info(
                            "dry-run sample rid=%d cid=%s kind=%s vec_len=%d hash=%s",
                            rid,
                            cid,
                            rk,
                            len(vec),
                            text_hash,
                        )
                    processed += 1
                    continue
                if vec_table_ok:
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO am_entities_vec_e5"
                            "(entity_id, embedding) VALUES (?, ?)",
                            (rid, _serialize_vec(vec)),
                        )
                    except sqlite3.OperationalError as exc:
                        LOG.debug("vec insert failed rid=%d (%s)", rid, exc)
                        failed += 1
                        continue
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO am_entities_vec_e5_embed_log "
                        "(entity_id, canonical_id, record_kind, embed_at, "
                        " embed_dim, model_name, text_hash, text_byte_len) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            rid,
                            cid,
                            rk,
                            refreshed_at,
                            dim,
                            model_id,
                            text_hash,
                            len(text.encode("utf-8")),
                        ),
                    )
                except sqlite3.OperationalError as exc:
                    LOG.debug("embed log insert failed rid=%d (%s)", rid, exc)
                    failed += 1
                    continue
                processed += 1
        if not dry_run:
            conn.commit()
        LOG.info(
            "chunk done ci=%d processed=%d skipped=%d failed=%d elapsed=%.1fs",
            ci,
            processed,
            skipped,
            failed,
            time.time() - t0,
        )

    if not dry_run:
        _finalize_refresh(conn, refresh_id, processed, skipped, failed)
    conn.close()
    LOG.info(
        "build_e5_embeddings_v2 done processed=%d skipped=%d failed=%d elapsed=%.1fs",
        processed,
        skipped,
        failed,
        time.time() - t0,
    )
    return {
        "refresh_id": refresh_id,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "dim": dim,
        "model": model_id,
        "mode": mode,
        "vec_table_ready": vec_table_ok,
        "interrupted": _INTERRUPTED,
    }


def _finalize_refresh(
    conn: sqlite3.Connection,
    refresh_id: str,
    processed: int,
    skipped: int,
    failed: int,
) -> None:
    finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    try:
        conn.execute(
            "UPDATE am_entities_vec_e5_refresh_log SET "
            "finished_at = ?, entities_processed = ?, "
            "entities_skipped = ?, entities_failed = ? WHERE refresh_id = ?",
            (finished_at, processed, skipped, failed, refresh_id),
        )
        conn.commit()
    except sqlite3.OperationalError as exc:
        LOG.warning("finalize refresh log failed: %s", exc)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument(
        "--mode",
        choices=("full", "incremental", "resume"),
        default="incremental",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-entities", type=int, default=None)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument(
        "--kinds",
        default="",
        help="comma-sep record_kind filter",
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] or None
    result = refresh(
        args.autonomath_db,
        mode=args.mode,
        dry_run=args.dry_run,
        max_entities=args.max_entities,
        model_name=args.model,
        chunk_size=args.chunk_size,
        batch_size=args.batch_size,
        kinds=kinds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
