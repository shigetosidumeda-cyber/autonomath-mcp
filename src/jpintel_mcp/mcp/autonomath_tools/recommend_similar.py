"""recommend_similar — vector kNN recommendation MCP tools.

Three new tools that expose sqlite-vec k-NN search over the three
production embedding corpora that completed Wave 30 backfill (91% — 2026-05-04):

  * ``recommend_similar_program``         (vec_S — programs,         11,601 rows)
  * ``recommend_similar_case``            (vec_C — case_studies,      2,286 rows)
  * ``recommend_similar_court_decision``  (vec_J — court_decisions,   2,065 rows)

Hard constraints (memory feedback_no_operator_llm_api / feedback_autonomath_no_api_use)
--------------------------------------------------------------------------------
  * NO LLM call inside the tool body. Pure SQLite + Python.
  * Both seed retrieval and kNN search reuse the pre-computed embedding
    for ``seed_entity_id`` from the vec table itself — no encoding step,
    no model load, no Anthropic / OpenAI / sentence-transformers import.

Architecture
------------
  - vec_S / vec_C / vec_J live in ``autonomath.db`` (migration 147,
    ``-- target_db: autonomath``).
  - vec_S/C/J ``entity_id`` is the **rowid** from the source row in
    ``data/jpintel.db`` (programs / case_studies / court_decisions).
  - sqlite-vec extension is loaded by ``connect_autonomath`` via the
    ``AUTONOMATH_VEC0_PATH`` env var (Dockerfile bakes ``/opt/vec0.so``).
  - Workflow per query:
        1. Resolve seed input → (rowid).
        2. SELECT embedding from vec table at entity_id = rowid.
        3. kNN: ``WHERE embedding MATCH ? AND k = ?`` against vec table.
        4. Drop the seed itself (distance 0.0) from the result set.
        5. Resolve top-k rowids back to source rows on jpintel.db.
        6. Re-rank with ``verification_count`` (programs only) and
           ``density_score`` (W22-9 — am_entity_density_score), keeping
           cosine distance as the primary ordering and applying density
           as a tie-aware boost.

Sensitive disclaimer (S7 / 行政書士法 §1)
----------------------------------------
All three tools are pre-registered in ``envelope_wrapper.SENSITIVE_TOOLS``
so the response decorator (``_envelope_merge`` in mcp/server.py)
auto-injects ``_disclaimer`` at envelope-merge time. The tool body
itself also surfaces an inline ``_disclaimer`` field as a defence-
in-depth so even pre-envelope-merge consumers see the warning.

NO LLM call inside any tool — pure SQLite + Python.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.db.id_translator import normalize_program_id
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.recommend_similar")

_ENABLED = os.environ.get("AUTONOMATH_RECOMMEND_SIMILAR_ENABLED", "1") == "1"

# ---------------------------------------------------------------------------
# Disclaimer text (also auto-injected by envelope_wrapper.SENSITIVE_TOOLS).
# 行政書士法 §1 + 税理士法 §52 + 公認会計士法 §47条の2 fence — vector
# similarity is a retrieval signal, NOT an 採択 forecast or 申請可否 judgment.
# ---------------------------------------------------------------------------
_DISCLAIMER_RECOMMEND_SIMILAR = (
    "本 response は sqlite-vec による pre-computed embedding 上の k-NN "
    "検索結果で、採択を担保するものではありません。類似度は意味類似性の "
    "近似で、申請可否判断 (行政書士法 §1) ・税務助言 (税理士法 §52) ・"
    "監査意見 (公認会計士法 §47条の2) の代替ではありません。"
    "検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。"
)


# ---------------------------------------------------------------------------
# Vec / source table dispatch
# ---------------------------------------------------------------------------


class _CorpusSpec:
    """Per-corpus wiring for the three vector recommendation tools."""

    def __init__(
        self,
        *,
        tier: str,
        vec_table: str,
        source_table: str,
        source_pk_col: str,  # 'rowid' for vec_S/C/J
        select_cols: str,
        density_kind: str,  # record_kind in am_entity_density_score
    ) -> None:
        self.tier = tier
        self.vec_table = vec_table
        self.source_table = source_table
        self.source_pk_col = source_pk_col
        self.select_cols = select_cols
        self.density_kind = density_kind


_S_SPEC = _CorpusSpec(
    tier="S",
    vec_table="am_entities_vec_S",
    source_table="programs",
    source_pk_col="rowid",
    select_cols=(
        "rowid AS rowid_int, unified_id, primary_name, tier, prefecture, "
        "authority_name, program_kind, source_url, "
        "COALESCE(verification_count, 0) AS verification_count"
    ),
    density_kind="program",
)

_C_SPEC = _CorpusSpec(
    tier="C",
    vec_table="am_entities_vec_C",
    source_table="case_studies",
    source_pk_col="rowid",
    select_cols=(
        "rowid AS rowid_int, case_id, case_title, case_summary, "
        "company_name, prefecture, industry_jsic, source_url"
    ),
    density_kind="case_study",
)

_J_SPEC = _CorpusSpec(
    tier="J",
    vec_table="am_entities_vec_J",
    source_table="court_decisions",
    source_pk_col="rowid",
    select_cols=(
        "rowid AS rowid_int, unified_id, case_name, court, decision_date, key_ruling, source_url"
    ),
    density_kind="court_decision",
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _ensure_vec_loaded(conn: sqlite3.Connection) -> bool:
    """Best-effort load sqlite-vec extension on `conn`.

    `connect_autonomath()` already attempts a load via the
    ``AUTONOMATH_VEC0_PATH`` env var (Dockerfile bakes ``/opt/vec0.so``),
    but on a developer macOS box that var is usually unset. We retry via
    the ``sqlite_vec`` Python helper before giving up so unit tests and
    local smoke runs do not silently fall through to "vec0 missing".

    Returns True on success, False if the extension cannot be loaded.
    Failure must NOT be fatal — the caller surfaces a graceful empty
    envelope keyed by ``vec_table_missing`` instead.
    """
    try:
        # Probe for vec0 module.
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'am_entities_vec_S' LIMIT 1"
        ).fetchone()
        # Trivial vec0-using SELECT to detect "no such module: vec0".
        conn.execute("SELECT entity_id FROM am_entities_vec_S LIMIT 0").fetchone()
        return True
    except sqlite3.OperationalError as exc:
        if "vec0" not in str(exc).lower():
            return False
    # Try sqlite_vec.load() as a fallback (dev machines without
    # /opt/vec0.so baked in).
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (ImportError, AttributeError, sqlite3.OperationalError) as exc:
        logger.debug("sqlite_vec.load fallback failed: %s", exc)
        return False


def _open_autonomath() -> sqlite3.Connection | dict[str, Any]:
    try:
        conn = connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root.",
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )
    # Best-effort vec0 load — failure is non-fatal; downstream code
    # detects via _table_exists / kNN OperationalError.
    _ensure_vec_loaded(conn)
    return conn


def _open_jpintel() -> sqlite3.Connection | dict[str, Any]:
    """Open ``data/jpintel.db`` read-only for source-row resolution."""
    try:
        path = Path(settings.db_path)
    except Exception as exc:  # pragma: no cover - settings always loadable
        return make_error(code="db_unavailable", message=f"settings.db_path missing: {exc}")
    if not path.exists():
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db not found at {path}",
        )
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type IN ('table','view','virtual') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _serialize_f32(blob: bytes) -> bytes:
    """Pass-through helper — vec0 stores embeddings as raw float32 bytes."""
    return blob


# ---------------------------------------------------------------------------
# Seed resolution
# ---------------------------------------------------------------------------


def _resolve_program_seed(seed: str | int) -> int | None:
    """Resolve a program identifier (UNI-... / canonical_id / rowid) to rowid.

    Accepts:
      - bare integer rowid
      - ``UNI-...`` unified_id
      - ``program:...`` canonical_id (mapped via id_translator → unified_id)
    """
    if isinstance(seed, int) or (isinstance(seed, str) and seed.isdigit()):
        return int(seed)
    s = str(seed).strip()
    if not s:
        return None
    uni, _ = normalize_program_id(s)
    if not uni:
        uni = s  # last-chance: treat the input as a unified_id directly
    db = _open_jpintel()
    if isinstance(db, dict):
        return None
    try:
        row = db.execute(
            "SELECT rowid FROM programs WHERE unified_id = ? LIMIT 1",
            (uni,),
        ).fetchone()
        return int(row["rowid"]) if row else None
    except sqlite3.Error:
        return None
    finally:
        with contextlib.suppress(Exception):
            db.close()


def _resolve_case_seed(seed: str | int) -> int | None:
    """Resolve a case_studies identifier (case_id TEXT or rowid INT) to rowid."""
    if isinstance(seed, int) or (isinstance(seed, str) and str(seed).isdigit()):
        return int(seed)
    s = str(seed).strip()
    if not s:
        return None
    db = _open_jpintel()
    if isinstance(db, dict):
        return None
    try:
        row = db.execute(
            "SELECT rowid FROM case_studies WHERE case_id = ? LIMIT 1",
            (s,),
        ).fetchone()
        return int(row["rowid"]) if row else None
    except sqlite3.Error:
        return None
    finally:
        with contextlib.suppress(Exception):
            db.close()


def _resolve_court_seed(seed: str | int) -> int | None:
    """Resolve a court_decisions identifier (unified_id TEXT or rowid INT) to rowid."""
    if isinstance(seed, int) or (isinstance(seed, str) and str(seed).isdigit()):
        return int(seed)
    s = str(seed).strip()
    if not s:
        return None
    db = _open_jpintel()
    if isinstance(db, dict):
        return None
    try:
        row = db.execute(
            "SELECT rowid FROM court_decisions WHERE unified_id = ? LIMIT 1",
            (s,),
        ).fetchone()
        return int(row["rowid"]) if row else None
    except sqlite3.Error:
        return None
    finally:
        with contextlib.suppress(Exception):
            db.close()


# ---------------------------------------------------------------------------
# kNN core
# ---------------------------------------------------------------------------


def _fetch_seed_embedding(
    conn: sqlite3.Connection,
    vec_table: str,
    entity_id: int,
) -> bytes | None:
    """Read the seed embedding from vec_<tier> by entity_id (= jpintel rowid)."""
    try:
        row = conn.execute(
            f"SELECT embedding FROM {vec_table} WHERE entity_id = ? LIMIT 1",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        emb = row["embedding"]
        if isinstance(emb, (bytes, bytearray)):
            return bytes(emb)
        # vec0 returns the raw float32 byte buffer; defensive only.
        return None
    except sqlite3.Error as exc:
        logger.debug("seed embedding fetch failed (%s): %s", vec_table, exc)
        return None


def _knn(
    conn: sqlite3.Connection,
    vec_table: str,
    seed_embedding: bytes,
    k: int,
) -> list[tuple[int, float]]:
    """Return [(entity_id, distance), ...] for top-k neighbours including seed.

    sqlite-vec MATCH yields ``distance`` ascending (cosine distance, lower
    = closer). We over-fetch by 1 since the seed itself is always the
    nearest (distance ~0.0) and we drop it downstream.
    """
    over_k = max(1, int(k)) + 1
    sql = (
        f"SELECT entity_id, distance FROM {vec_table} "
        f"WHERE embedding MATCH ? AND k = ? ORDER BY distance"
    )
    try:
        cur = conn.execute(sql, (_serialize_f32(seed_embedding), over_k))
        return [(int(r["entity_id"]), float(r["distance"])) for r in cur.fetchall()]
    except sqlite3.Error as exc:
        logger.debug("knn query failed (%s): %s", vec_table, exc)
        raise


# ---------------------------------------------------------------------------
# Density-score lookup (W22-9)
# ---------------------------------------------------------------------------


def _density_for_program_unified_ids(
    am_conn: sqlite3.Connection,
    unified_ids: list[str],
) -> dict[str, float]:
    """Return {unified_id: density_score} from am_entity_density_score.

    am_entity_density_score is keyed by ``entity_id TEXT`` (canonical_id).
    Programs sit in ``entity_id_map(unified_id, canonical_id)``; for
    case_studies / court_decisions the table is empty in production today,
    so this helper is currently used only by the program path.
    Resilient: missing table or empty result yields an empty dict.
    """
    if not unified_ids:
        return {}
    if not _table_exists(am_conn, "am_entity_density_score"):
        return {}
    if not _table_exists(am_conn, "entity_id_map"):
        # Fallback: density unavailable without the join.
        return {}
    placeholders = ",".join("?" * len(unified_ids))
    sql = (
        "SELECT m.unified_id AS unified_id, d.density_score AS density_score "
        "FROM entity_id_map m "
        "JOIN am_entity_density_score d ON d.entity_id = m.canonical_id "
        f"WHERE m.unified_id IN ({placeholders})"
    )
    try:
        cur = am_conn.execute(sql, tuple(unified_ids))
        return {
            r["unified_id"]: float(r["density_score"])
            for r in cur.fetchall()
            if r["density_score"] is not None
        }
    except sqlite3.Error as exc:
        logger.debug("density lookup failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Source-row resolution
# ---------------------------------------------------------------------------


def _resolve_rows(
    jp_conn: sqlite3.Connection,
    spec: _CorpusSpec,
    rowids: list[int],
) -> dict[int, dict[str, Any]]:
    """Fetch source rows from jpintel.db keyed by rowid."""
    if not rowids:
        return {}
    placeholders = ",".join("?" * len(rowids))
    sql = f"SELECT {spec.select_cols} FROM {spec.source_table} WHERE rowid IN ({placeholders})"
    try:
        cur = jp_conn.execute(sql, tuple(rowids))
        return {int(r["rowid_int"]): dict(r) for r in cur.fetchall()}
    except sqlite3.Error as exc:
        logger.debug("source row fetch failed (%s): %s", spec.source_table, exc)
        return {}


# ---------------------------------------------------------------------------
# Composite ranking
# ---------------------------------------------------------------------------


def _compose_score(distance: float, verification_count: int, density_score: float) -> float:
    """Composite re-rank score (higher = better).

    Cosine distance is in [0, 2]; 0 = identical, 1 = orthogonal. We invert
    to ``similarity = 1 - distance`` so the term reads "higher is better"
    alongside the two density signals.

    Weights chosen so cosine dominates (vector similarity is the primary
    signal we trust); verification_count and density_score act as
    tie-breakers for near-equal cosines.

        score = (1 - distance) * 1.00
              + min(verification_count, 5) / 5 * 0.10
              + density_score                  * 0.05
    """
    sim = 1.0 - max(0.0, min(2.0, float(distance)))
    vc_norm = min(int(verification_count or 0), 5) / 5.0
    return sim + vc_norm * 0.10 + float(density_score or 0.0) * 0.05


# ---------------------------------------------------------------------------
# Impl: recommend_similar_program
# ---------------------------------------------------------------------------


def _recommend_similar_program_impl(
    program_id: str | int,
    k: int = 10,
) -> dict[str, Any]:
    """k-NN over vec_S, rerank by verification_count + density_score."""
    if program_id is None or program_id == "":
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    k = max(1, min(int(k or 10), 50))

    rowid = _resolve_program_seed(program_id)
    if rowid is None:
        return _empty_envelope(
            seed_id=program_id,
            k=k,
            reason="seed_program_not_found",
        )

    am = _open_autonomath()
    if isinstance(am, dict):
        return am

    if not _table_exists(am, _S_SPEC.vec_table):
        return _empty_envelope(
            seed_id=program_id,
            k=k,
            reason="vec_table_missing",
            extra={"vec_table": _S_SPEC.vec_table},
        )

    seed_emb = _fetch_seed_embedding(am, _S_SPEC.vec_table, rowid)
    if seed_emb is None:
        return _empty_envelope(
            seed_id=program_id,
            k=k,
            reason="seed_embedding_missing",
            extra={"rowid": rowid},
        )

    try:
        neighbours = _knn(am, _S_SPEC.vec_table, seed_emb, k)
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"vec kNN query failed: {exc}",
        )
    # Drop the seed (distance ~0.0).
    neighbours = [(eid, d) for eid, d in neighbours if eid != rowid][:k]
    rowids = [eid for eid, _ in neighbours]

    jp = _open_jpintel()
    if isinstance(jp, dict):
        return jp
    try:
        rows = _resolve_rows(jp, _S_SPEC, rowids)
    finally:
        with contextlib.suppress(Exception):
            jp.close()

    unified_ids = [
        rows[eid]["unified_id"] for eid in rowids if eid in rows and rows[eid].get("unified_id")
    ]
    density = _density_for_program_unified_ids(am, unified_ids)

    ranked: list[dict[str, Any]] = []
    for eid, dist in neighbours:
        row = rows.get(eid)
        if not row:
            continue
        uni = row.get("unified_id")
        ds = density.get(uni, 0.0) if uni else 0.0
        vc = int(row.get("verification_count") or 0)
        score = _compose_score(dist, vc, ds)
        ranked.append(
            {
                "program_id": uni,
                "primary_name": row.get("primary_name"),
                "tier": row.get("tier"),
                "prefecture": row.get("prefecture"),
                "authority_name": row.get("authority_name"),
                "program_kind": row.get("program_kind"),
                "source_url": row.get("source_url"),
                "distance": round(dist, 6),
                "similarity": round(1.0 - dist, 6),
                "verification_count": vc,
                "density_score": round(ds, 6),
                "score": round(score, 6),
            }
        )
    # Final ordering: composite score descending.
    ranked.sort(key=lambda r: r["score"], reverse=True)

    return _finalize(
        {
            "seed_program_id": program_id,
            "seed_rowid": rowid,
            "k": k,
            "results": ranked,
            "total": len(ranked),
            "limit": k,
            "offset": 0,
            "_billing_unit": 1,
            "_disclaimer": _DISCLAIMER_RECOMMEND_SIMILAR,
        }
    )


# ---------------------------------------------------------------------------
# Impl: recommend_similar_case
# ---------------------------------------------------------------------------


def _recommend_similar_case_impl(
    case_id: str | int,
    k: int = 10,
) -> dict[str, Any]:
    """k-NN over vec_C (case_studies). No verification_count column —
    case_studies don't carry one — density_score still applied via
    ``am_entity_density_score`` if any rows have been populated for
    record_kind='case_study'.
    """
    if case_id is None or case_id == "":
        return make_error(
            code="missing_required_arg",
            message="case_id is required.",
            field="case_id",
        )
    k = max(1, min(int(k or 10), 50))

    rowid = _resolve_case_seed(case_id)
    if rowid is None:
        return _empty_envelope(seed_id=case_id, k=k, reason="seed_case_not_found")

    am = _open_autonomath()
    if isinstance(am, dict):
        return am

    if not _table_exists(am, _C_SPEC.vec_table):
        return _empty_envelope(
            seed_id=case_id,
            k=k,
            reason="vec_table_missing",
            extra={"vec_table": _C_SPEC.vec_table},
        )

    seed_emb = _fetch_seed_embedding(am, _C_SPEC.vec_table, rowid)
    if seed_emb is None:
        return _empty_envelope(
            seed_id=case_id,
            k=k,
            reason="seed_embedding_missing",
            extra={"rowid": rowid},
        )

    try:
        neighbours = _knn(am, _C_SPEC.vec_table, seed_emb, k)
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"vec kNN query failed: {exc}",
        )
    neighbours = [(eid, d) for eid, d in neighbours if eid != rowid][:k]
    rowids = [eid for eid, _ in neighbours]

    jp = _open_jpintel()
    if isinstance(jp, dict):
        return jp
    try:
        rows = _resolve_rows(jp, _C_SPEC, rowids)
    finally:
        with contextlib.suppress(Exception):
            jp.close()

    ranked: list[dict[str, Any]] = []
    for eid, dist in neighbours:
        row = rows.get(eid)
        if not row:
            continue
        # Density not currently keyed for case_study record_kind; default 0.
        score = _compose_score(dist, 0, 0.0)
        ranked.append(
            {
                "case_id": row.get("case_id"),
                "case_title": row.get("case_title"),
                "case_summary": row.get("case_summary"),
                "company_name": row.get("company_name"),
                "prefecture": row.get("prefecture"),
                "industry_jsic": row.get("industry_jsic"),
                "source_url": row.get("source_url"),
                "distance": round(dist, 6),
                "similarity": round(1.0 - dist, 6),
                "verification_count": 0,
                "density_score": 0.0,
                "score": round(score, 6),
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)

    return _finalize(
        {
            "seed_case_id": case_id,
            "seed_rowid": rowid,
            "k": k,
            "results": ranked,
            "total": len(ranked),
            "limit": k,
            "offset": 0,
            "_billing_unit": 1,
            "_disclaimer": _DISCLAIMER_RECOMMEND_SIMILAR,
        }
    )


# ---------------------------------------------------------------------------
# Impl: recommend_similar_court_decision
# ---------------------------------------------------------------------------


def _recommend_similar_court_decision_impl(
    case_id: str | int,
    k: int = 10,
) -> dict[str, Any]:
    """k-NN over vec_J (court_decisions)."""
    if case_id is None or case_id == "":
        return make_error(
            code="missing_required_arg",
            message="case_id is required.",
            field="case_id",
        )
    k = max(1, min(int(k or 10), 50))

    rowid = _resolve_court_seed(case_id)
    if rowid is None:
        return _empty_envelope(seed_id=case_id, k=k, reason="seed_court_decision_not_found")

    am = _open_autonomath()
    if isinstance(am, dict):
        return am

    if not _table_exists(am, _J_SPEC.vec_table):
        return _empty_envelope(
            seed_id=case_id,
            k=k,
            reason="vec_table_missing",
            extra={"vec_table": _J_SPEC.vec_table},
        )

    seed_emb = _fetch_seed_embedding(am, _J_SPEC.vec_table, rowid)
    if seed_emb is None:
        return _empty_envelope(
            seed_id=case_id,
            k=k,
            reason="seed_embedding_missing",
            extra={"rowid": rowid},
        )

    try:
        neighbours = _knn(am, _J_SPEC.vec_table, seed_emb, k)
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"vec kNN query failed: {exc}",
        )
    neighbours = [(eid, d) for eid, d in neighbours if eid != rowid][:k]
    rowids = [eid for eid, _ in neighbours]

    jp = _open_jpintel()
    if isinstance(jp, dict):
        return jp
    try:
        rows = _resolve_rows(jp, _J_SPEC, rowids)
    finally:
        with contextlib.suppress(Exception):
            jp.close()

    ranked: list[dict[str, Any]] = []
    for eid, dist in neighbours:
        row = rows.get(eid)
        if not row:
            continue
        score = _compose_score(dist, 0, 0.0)
        ranked.append(
            {
                "case_id": row.get("unified_id"),
                "case_name": row.get("case_name"),
                "court_name": row.get("court"),
                "decision_date": row.get("decision_date"),
                "key_ruling": row.get("key_ruling"),
                "source_url": row.get("source_url"),
                "distance": round(dist, 6),
                "similarity": round(1.0 - dist, 6),
                "verification_count": 0,
                "density_score": 0.0,
                "score": round(score, 6),
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)

    return _finalize(
        {
            "seed_case_id": case_id,
            "seed_rowid": rowid,
            "k": k,
            "results": ranked,
            "total": len(ranked),
            "limit": k,
            "offset": 0,
            "_billing_unit": 1,
            "_disclaimer": _DISCLAIMER_RECOMMEND_SIMILAR,
        }
    )


# ---------------------------------------------------------------------------
# Empty / finalize helpers
# ---------------------------------------------------------------------------


def _empty_envelope(
    *,
    seed_id: Any,
    k: int,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "seed_id": seed_id,
        "k": k,
        "results": [],
        "total": 0,
        "limit": k,
        "offset": 0,
        "data_quality": {"reason": reason},
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER_RECOMMEND_SIMILAR,
    }
    if extra:
        for key, val in extra.items():
            body.setdefault(key, val)
    return attach_corpus_snapshot(body)


def _finalize(body: dict[str, Any]) -> dict[str, Any]:
    return attach_corpus_snapshot(body)


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_RECOMMEND_SIMILAR_ENABLED +
# AUTONOMATH_ENABLED. ≤ 400 char docstrings per Wave 21/22 convention.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def recommend_similar_program(
        program_id: Annotated[
            str,
            Field(
                description="Seed program id — accepts UNI-... unified_id, program:... canonical_id, or rowid."
            ),
        ],
        k: Annotated[
            int,
            Field(ge=1, le=50, description="Top-k neighbours (1..50). Default 10."),
        ] = 10,
    ) -> dict[str, Any]:
        """Vector k-NN over am_entities_vec_S (programs). Re-ranked by cosine + verification_count + density_score (W22-9). NOT an 採択 forecast — 行政書士法 §1 / 税理士法 §52 fence; the LLM must surface the disclaimer envelope."""
        return _recommend_similar_program_impl(program_id=program_id, k=k)

    @mcp.tool(annotations=_READ_ONLY)
    def recommend_similar_case(
        case_id: Annotated[
            str,
            Field(description="Seed case_studies id — accepts case_id TEXT or rowid."),
        ],
        k: Annotated[
            int,
            Field(ge=1, le=50, description="Top-k neighbours (1..50). Default 10."),
        ] = 10,
    ) -> dict[str, Any]:
        """Vector k-NN over am_entities_vec_C (case_studies). Cosine distance with optional density boost. NOT an 採択 forecast — 行政書士法 §1 / 税理士法 §52 fence; the LLM must surface the disclaimer envelope."""
        return _recommend_similar_case_impl(case_id=case_id, k=k)

    @mcp.tool(annotations=_READ_ONLY)
    def recommend_similar_court_decision(
        case_id: Annotated[
            str,
            Field(description="Seed court_decisions id — accepts unified_id (HAN-...) or rowid."),
        ],
        k: Annotated[
            int,
            Field(ge=1, le=50, description="Top-k neighbours (1..50). Default 10."),
        ] = 10,
    ) -> dict[str, Any]:
        """Vector k-NN over am_entities_vec_J (court_decisions). Cosine distance with optional density boost. NOT a legal opinion — 弁護士法 §72 / 行政書士法 §1 fence; the LLM must surface the disclaimer envelope."""
        return _recommend_similar_court_decision_impl(case_id=case_id, k=k)


__all__ = [
    "_recommend_similar_program_impl",
    "_recommend_similar_case_impl",
    "_recommend_similar_court_decision_impl",
    "_compose_score",
    "_DISCLAIMER_RECOMMEND_SIMILAR",
]
