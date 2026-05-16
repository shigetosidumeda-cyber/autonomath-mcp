#!/usr/bin/env python3
"""Generate JPCIR ``program_lineage_v1`` packets across the 11,601-program cohort.

Pre-renders the **制度 lineage packet** — 制度 × 法令 × 通達 × 判例 × 改正履歴
cross-source bundle — for every searchable :class:`programs` row and uploads
each result as a single JSON envelope to
``s3://<derived_bucket>/program_lineage/<program_id>.json``.

The lineage chain assembled per program is::

    program (programs)
       └─ 根拠法令 (laws via program_law_refs)
            └─ 関連条文 (am_law_article)
                 └─ 通達 (nta_tsutatsu_index)
                     └─ 過去解釈裁決 (nta_saiketsu)
                          └─ 関連判例 (court_decisions)
       └─ 改正履歴 (am_amendment_diff entity_id = program unified_id)

This mirrors the runtime ``GET /v1/tax_rules/{rule_id}/full_chain`` endpoint
(see ``src/jpintel_mcp/api/tax_chain.py``) but is keyed on programs and
pre-rendered offline so that customer agents can ``s3:GetObject`` for a
``program_unified_id`` and skip the per-call SQLite join entirely. Each
packet stays under the 25 KB envelope band (deeper than 法人360, but the
chain caps are sized to keep p99 ≤ 25 KB).

Pipeline
--------
1. Open ``data/jpintel.db`` (read-only) + ``autonomath.db`` (read-only). Both
   live SQLite files; CLAUDE.md forbids cross-DB JOIN / ATTACH, so the join
   is Python-side (mirroring tax_chain.py).
2. For each program (paged ``batch_size`` rows at a time):
   * Pull root row + ``program_law_refs`` to collect ``law_unified_id``.
   * For each law: pull ``laws`` row + ``am_law_article`` (cap N=4 articles).
   * For each law canonical id: pull ``nta_tsutatsu_index`` (cap N=4).
   * Saiketsu lookup keyed by program-name kanji tokens (cap N=3).
   * Court decisions keyed by law-id overlap OR program-name tokens
     (cap N=3).
   * Amendment timeline via ``am_amendment_diff`` (cap N=10).
3. Render JPCIR envelope (``package_kind="program_lineage_v1"``) with
   ``legal_basis_chain[]`` / ``notice_chain[]`` / ``precedent_chain[]`` /
   ``amendment_timeline[]`` arrays + ``coverage_score`` (weighted on
   ``claim_coverage`` + ``freshness_coverage``).
4. Upload each packet to S3 (``--output-prefix`` honours
   ``s3://...derived/program_lineage/``). Local-dir prefixes are also
   supported for offline smoke runs.

CLI::

    python scripts/aws_credit_ops/generate_program_lineage_packets.py \\
        --output-prefix s3://jpcite-credit-993693061769-202605-derived/program_lineage/ \\
        [--batch-size 500] \\
        [--limit 100] \\
        [--commit]

``--commit`` lifts the DRY_RUN guard. The default is dry-run (no S3 PUTs,
no local writes) so the smoke matrix can be exercised without billing
S3 traffic.

Athena workgroup hint (informational; the script does not call Athena —
the join is local SQLite for honest ¥0/req packet pre-render). When you
need to verify aggregate coverage from S3-side Parquet later, the
canonical workgroup is ``jpcite-credit-2026-05`` and the matching join
template lives at ``infra/aws/athena/queries/program_lineage_join.sql``.

Constraints
-----------
* **NO LLM API calls.** Pure SQLite + Python templating + boto3 PUT.
* **Each packet < 25 KB.** Caps per chain are sized so a p99 program
  with all 4 chain depths populated still fits well under the budget;
  the assembler also enforces a hard ``MAX_PACKET_BYTES`` check and
  truncates the lowest-priority chain if a packet overshoots.
* **``coverage_score`` weights** the master plan's two honest axes:
  ``claim_coverage`` (do downstream chains have rows?) and
  ``freshness_coverage`` (do ``fetched_at`` / ``refreshed_at`` /
  ``detected_at`` stamps look recent?). Other axes are not synthesised
  to avoid the moat-phantom audit foot-gun.
* **Athena workgroup** referenced ``jpcite-credit-2026-05`` for any
  downstream Parquet rollup queries (no live call in this script).
* **mypy --strict + ruff 0.**
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

# PERF-23: orjson (via ``_dumps_compact``) on the per-packet hot path —
# both the truncation-loop size probes and the final encode. The
# ``upload_packet`` callee here takes ``payload: bytes`` so we encode
# the truncated payload once and pass it in. ``report.to_json`` stdout
# write (indented, one-shot) stays on stdlib ``json``.
from scripts.aws_credit_ops._packet_base import _dumps_compact, _write_bytes_fast

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("generate_program_lineage_packets")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
JPINTEL_DB: Final[Path] = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB: Final[Path] = REPO_ROOT / "autonomath.db"

#: Canonical Athena workgroup for downstream Parquet rollup queries.
#: Surfaced in the envelope's ``athena_workgroup`` field for traceability.
ATHENA_WORKGROUP: Final[str] = "jpcite-credit-2026-05"

#: S3 prefix used for the per-program lineage packet objects. Mirror of the
#: ``--output-prefix`` CLI default for the canonical credit bucket.
DEFAULT_OUTPUT_PREFIX: Final[str] = (
    "s3://jpcite-credit-993693061769-202605-derived/program_lineage/"
)

#: Hard envelope budget — every packet MUST stay under this size after
#: JSON encode (UTF-8 bytes). Exceeding triggers a graceful truncation
#: of the lowest-priority chain (amendment_timeline first, then
#: precedent_chain, then notice_chain), preserving the envelope shape.
MAX_PACKET_BYTES: Final[int] = 25_000

#: Per-chain caps (defensive — keeps payload bounded across the 11,601
#: program cohort).
CAP_LAWS: Final[int] = 4
CAP_ARTICLES_PER_LAW: Final[int] = 4
CAP_NOTICES: Final[int] = 4
CAP_SAIKETSU: Final[int] = 3
CAP_PRECEDENTS: Final[int] = 3
CAP_AMENDMENTS: Final[int] = 10

#: Truncate freeform fields so a single oversized ``key_ruling`` or
#: ``text_summary`` cannot blow the 25 KB envelope.
SNIPPET_CHAR_CAP: Final[int] = 200

#: Default per-batch fetch size (CLI override).
DEFAULT_BATCH_SIZE: Final[int] = 500

#: Coverage score weights (master plan §1: claim + freshness only).
W_CLAIM: Final[float] = 0.6
W_FRESHNESS: Final[float] = 0.4

#: Freshness threshold — anything more than N days old contributes 0
#: to the freshness component, anything ≤ N days contributes 1.
FRESHNESS_FRESH_DAYS: Final[int] = 365

#: Tax-firm review disclaimer fenced under 税理士法 §52 / 弁護士法 §72.
LINEAGE_DISCLAIMER: Final[str] = (
    "本 lineage packet は jpcite corpus (programs / laws / am_law_article / "
    "nta_tsutatsu_index / nta_saiketsu / court_decisions / am_amendment_diff) "
    "を一次資料 URL と共に束ねた検索結果で、税理士法 §52 (税務代理) / "
    "弁護士法 §72 (法令解釈) / 公認会計士法 §47条の2 (監査・意見表明) の "
    "いずれの士業役務にも該当しません。掲載の通達・裁決・判例は公表時点の解釈で "
    "あり、改正により現在の取扱が変更されている可能性があります。"
    "各 row の source_url で原典を確認のうえ、確定判断は資格を有する税理士・"
    "弁護士に必ずご相談ください。"
)

#: JPCIR envelope shape constants.
PACKAGE_KIND: Final[str] = "program_lineage_v1"
SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PacketReport:
    """Per-program lineage assembly result."""

    program_id: str
    status: str  # "written" | "dry_run" | "missing" | "oversize_truncated" | "error"
    output_uri: str | None = None
    bytes_written: int = 0
    coverage_score: float = 0.0
    claim_coverage: float = 0.0
    freshness_coverage: float = 0.0
    chain_counts: dict[str, int] = field(default_factory=dict)
    error_message: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "status": self.status,
            "output_uri": self.output_uri,
            "bytes_written": self.bytes_written,
            "coverage_score": round(self.coverage_score, 4),
            "claim_coverage": round(self.claim_coverage, 4),
            "freshness_coverage": round(self.freshness_coverage, 4),
            "chain_counts": dict(self.chain_counts),
            "error_message": self.error_message,
        }


@dataclass
class RunReport:
    """Aggregate ledger for the script invocation."""

    output_prefix: str
    batch_size: int
    limit: int | None
    dry_run: bool
    athena_workgroup: str
    started_at: str
    finished_at: str | None = None
    packets: list[PacketReport] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for p in self.packets:
            statuses[p.status] = statuses.get(p.status, 0) + 1
        total_bytes = sum(p.bytes_written for p in self.packets)
        return {
            "output_prefix": self.output_prefix,
            "batch_size": self.batch_size,
            "limit": self.limit,
            "dry_run": self.dry_run,
            "athena_workgroup": self.athena_workgroup,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "packet_count": len(self.packets),
            "status_counts": statuses,
            "total_bytes": total_bytes,
            "first_50_packets": [p.to_json() for p in self.packets[:50]],
        }


# ---------------------------------------------------------------------------
# DB helpers (mirror tax_chain.py conventions — never raises on missing table)
# ---------------------------------------------------------------------------


def _open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite DB read-only; ``None`` when missing.

    The autonomath DB is optional on dev / CI machines; missing-table
    branches degrade to ``[]`` rather than 500ing.
    """
    if not db_path.exists():
        logger.warning("DB missing at %s — chains backed by it will degrade to []", db_path)
        return None
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    except sqlite3.Error as exc:
        logger.warning("DB open failed for %s: %s", db_path, exc)
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection | None, name: str) -> bool:
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _truncate(text: Any, limit: int = SNIPPET_CHAR_CAP) -> str | None:
    """Trim freeform text to ``limit`` chars; None for empty."""
    if text is None:
        return None
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return None
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


_KANJI_TOKEN_RE = re.compile(r"[一-鿿]{2,}")


def _kanji_tokens(text: str | None, *, max_tokens: int = 4) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(_KANJI_TOKEN_RE.findall(text)))[:max_tokens]


# ---------------------------------------------------------------------------
# Chain fetchers
# ---------------------------------------------------------------------------


def _fetch_program_root(
    jpintel: sqlite3.Connection,
    program_id: str,
) -> sqlite3.Row | None:
    try:
        row = jpintel.execute(
            "SELECT unified_id, primary_name, authority_name, authority_level, "
            "       prefecture, municipality, program_kind, tier, coverage_score, "
            "       official_url "
            "FROM programs WHERE unified_id = ? AND excluded = 0",
            (program_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("program root lookup failed for %s: %s", program_id, exc)
        return None
    if row is None:
        return None
    assert isinstance(row, sqlite3.Row)
    return row


def _fetch_legal_basis_chain(
    jpintel: sqlite3.Connection,
    autonomath: sqlite3.Connection | None,
    program_id: str,
) -> list[dict[str, Any]]:
    """Build ``legal_basis_chain[]`` — laws + articles for a program.

    Joins ``program_law_refs`` to ``laws`` on jpintel, and to
    ``am_law_article`` on autonomath (when present) for article-level
    text. NEVER cross-DB JOINs.
    """
    if not _table_exists(jpintel, "program_law_refs") or not _table_exists(jpintel, "laws"):
        return []
    try:
        rows = jpintel.execute(
            "SELECT plr.law_unified_id, plr.ref_kind, plr.article_citation, "
            "       plr.source_url AS ref_source_url, plr.fetched_at AS ref_fetched_at, "
            "       plr.confidence, "
            "       l.law_title, l.law_short_title, l.law_number, l.law_type, "
            "       l.ministry, l.last_amended_date, l.revision_status "
            "FROM program_law_refs plr "
            "LEFT JOIN laws l ON l.unified_id = plr.law_unified_id "
            "WHERE plr.program_unified_id = ? "
            "ORDER BY plr.confidence DESC, plr.law_unified_id ASC "
            "LIMIT ?",
            (program_id, CAP_LAWS),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("legal_basis_chain fetch failed for %s: %s", program_id, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        articles: list[dict[str, Any]] = []
        if autonomath is not None and _table_exists(autonomath, "am_law_article"):
            try:
                art_rows = autonomath.execute(
                    "SELECT article_id, article_number, title, text_summary, "
                    "       effective_from, last_amended "
                    "FROM am_law_article "
                    "WHERE law_canonical_id = ? "
                    "ORDER BY article_number_sort ASC NULLS LAST, article_id ASC "
                    "LIMIT ?",
                    (row["law_unified_id"], CAP_ARTICLES_PER_LAW),
                ).fetchall()
            except sqlite3.Error as exc:
                logger.warning(
                    "am_law_article fetch failed for law=%s: %s",
                    row["law_unified_id"],
                    exc,
                )
                art_rows = []
            for art in art_rows:
                articles.append(
                    {
                        "article_number": art["article_number"],
                        "title": _truncate(art["title"]),
                        "summary": _truncate(art["text_summary"]),
                        "effective_from": art["effective_from"],
                        "last_amended": art["last_amended"],
                    }
                )
        out.append(
            {
                "law_unified_id": row["law_unified_id"],
                "law_title": row["law_title"],
                "law_short_title": row["law_short_title"],
                "law_number": row["law_number"],
                "law_type": row["law_type"],
                "ministry": row["ministry"],
                "last_amended_date": row["last_amended_date"],
                "revision_status": row["revision_status"],
                "ref_kind": row["ref_kind"],
                "article_citation": row["article_citation"],
                "ref_source_url": row["ref_source_url"],
                "ref_fetched_at": row["ref_fetched_at"],
                "confidence": row["confidence"],
                "articles": articles,
            }
        )
    return out


def _fetch_notice_chain(
    autonomath: sqlite3.Connection | None,
    legal_basis_chain: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build ``notice_chain[]`` — 通達 keyed by law canonical id overlap.

    Looks up ``nta_tsutatsu_index`` for every distinct ``law_unified_id``
    surfaced by ``legal_basis_chain``. Each tsutatsu row carries
    ``law_canonical_id`` so the join is honest (no name LIKE).
    """
    if autonomath is None or not _table_exists(autonomath, "nta_tsutatsu_index"):
        return []
    law_ids = [item["law_unified_id"] for item in legal_basis_chain if item.get("law_unified_id")]
    if not law_ids:
        return []
    placeholders = ",".join("?" * len(law_ids))
    try:
        rows = autonomath.execute(
            "SELECT id, code, law_canonical_id, article_number, title, "
            "       body_excerpt, source_url, last_amended, refreshed_at "
            f"FROM nta_tsutatsu_index WHERE law_canonical_id IN ({placeholders}) "
            "ORDER BY refreshed_at DESC NULLS LAST, id ASC LIMIT ?",
            [*law_ids, CAP_NOTICES],
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("notice_chain fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "code": row["code"],
                "law_canonical_id": row["law_canonical_id"],
                "article_number": row["article_number"],
                "title": _truncate(row["title"]),
                "body_excerpt": _truncate(row["body_excerpt"]),
                "source_url": row["source_url"],
                "last_amended": row["last_amended"],
                "refreshed_at": row["refreshed_at"],
            }
        )
    return out


def _fetch_saiketsu_chain(
    autonomath: sqlite3.Connection | None,
    program_name: str | None,
) -> list[dict[str, Any]]:
    """Build saiketsu rows — keyed by name kanji tokens.

    The ``nta_saiketsu`` corpus is small (~140 rows) and is not joinable
    on law_canonical_id, so name-token LIKE is the honest probe (mirrors
    tax_chain.py's heuristic).
    """
    if autonomath is None or not _table_exists(autonomath, "nta_saiketsu"):
        return []
    tokens = _kanji_tokens(program_name, max_tokens=3)
    if not tokens:
        return []
    likes = ["(title LIKE ? OR decision_summary LIKE ?)" for _ in tokens]
    params: list[Any] = []
    for t in tokens:
        params.extend([f"%{t}%", f"%{t}%"])
    params.append(CAP_SAIKETSU)
    try:
        rows = autonomath.execute(
            "SELECT id, case_no, decision_date, tax_type, title, "
            "       decision_summary, source_url, ingested_at "
            "FROM nta_saiketsu "
            f"WHERE {' OR '.join(likes)} "
            "ORDER BY decision_date DESC NULLS LAST, id ASC LIMIT ?",
            params,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("saiketsu_chain fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "case_no": row["case_no"],
                "decision_date": row["decision_date"],
                "tax_type": row["tax_type"],
                "title": _truncate(row["title"]),
                "decision_summary": _truncate(row["decision_summary"]),
                "source_url": row["source_url"],
                "ingested_at": row["ingested_at"],
            }
        )
    return out


def _fetch_precedent_chain(
    jpintel: sqlite3.Connection,
    legal_basis_chain: list[dict[str, Any]],
    program_name: str | None,
) -> list[dict[str, Any]]:
    """Build ``precedent_chain[]`` — court_decisions joined on law id OR name."""
    if not _table_exists(jpintel, "court_decisions"):
        return []
    law_ids = [item["law_unified_id"] for item in legal_basis_chain if item.get("law_unified_id")]
    where: list[str] = []
    params: list[Any] = []
    if law_ids:
        likes = ["related_law_ids_json LIKE ?" for _ in law_ids]
        where.append("(" + " OR ".join(likes) + ")")
        params.extend([f'%"{lid}"%' for lid in law_ids])
    tokens = _kanji_tokens(program_name, max_tokens=2)
    if tokens:
        likes_kw = ["(case_name LIKE ? OR key_ruling LIKE ?)" for _ in tokens]
        where.append("(" + " OR ".join(likes_kw) + ")")
        for t in tokens:
            params.extend([f"%{t}%", f"%{t}%"])
    if not where:
        return []
    params.append(CAP_PRECEDENTS)
    sql = (
        "SELECT unified_id, case_name, case_number, court, court_level, "
        "       decision_date, decision_type, key_ruling, precedent_weight, "
        "       full_text_url, source_url, fetched_at "
        "FROM court_decisions "
        f"WHERE {' OR '.join(where)} "
        "ORDER BY (precedent_weight = 'binding') DESC, "
        "         (precedent_weight = 'persuasive') DESC, "
        "         decision_date DESC NULLS LAST, unified_id ASC "
        "LIMIT ?"
    )
    try:
        rows = jpintel.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("precedent_chain fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "unified_id": row["unified_id"],
                "case_name": _truncate(row["case_name"]),
                "case_number": row["case_number"],
                "court": row["court"],
                "court_level": row["court_level"],
                "decision_date": row["decision_date"],
                "decision_type": row["decision_type"],
                "precedent_weight": row["precedent_weight"],
                "key_ruling_snippet": _truncate(row["key_ruling"]),
                "source_url": row["full_text_url"] or row["source_url"],
                "fetched_at": row["fetched_at"],
            }
        )
    return out


def _fetch_amendment_timeline(
    autonomath: sqlite3.Connection | None,
    program_id: str,
) -> list[dict[str, Any]]:
    if autonomath is None or not _table_exists(autonomath, "am_amendment_diff"):
        return []
    try:
        rows = autonomath.execute(
            "SELECT diff_id, field_name, prev_value, new_value, detected_at, source_url "
            "FROM am_amendment_diff WHERE entity_id = ? "
            "ORDER BY detected_at DESC LIMIT ?",
            (program_id, CAP_AMENDMENTS),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("amendment_timeline fetch failed for %s: %s", program_id, exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "diff_id": row["diff_id"],
                "field_name": row["field_name"],
                "prev_value": _truncate(row["prev_value"], limit=120),
                "new_value": _truncate(row["new_value"], limit=120),
                "detected_at": row["detected_at"],
                "source_url": row["source_url"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Coverage score (claim + freshness only — phantom-moat audit safe)
# ---------------------------------------------------------------------------


def _compute_claim_coverage(
    *,
    has_legal_basis: bool,
    has_notices: bool,
    has_saiketsu: bool,
    has_precedents: bool,
) -> float:
    """Fraction of the 4 evidence chains that surface ≥ 1 row.

    legal_basis_chain anchors the lineage; the other three are
    interpretive layers. Equal-weight average yields the master plan's
    "claim coverage" axis.
    """
    flags = [has_legal_basis, has_notices, has_saiketsu, has_precedents]
    if not flags:
        return 0.0
    return sum(1 for f in flags if f) / float(len(flags))


def _is_fresh(stamp: str | None, *, now_utc: datetime) -> bool:
    """True when ``stamp`` (ISO-8601 or YYYY-MM-DD) is within fresh band."""
    if not stamp:
        return False
    try:
        if len(stamp) == 10:
            dt = datetime.strptime(stamp, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            cleaned = stamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return False
    delta_days = (now_utc - dt).days
    return 0 <= delta_days <= FRESHNESS_FRESH_DAYS


def _compute_freshness_coverage(
    *,
    legal_basis_chain: list[dict[str, Any]],
    notice_chain: list[dict[str, Any]],
    precedent_chain: list[dict[str, Any]],
    amendment_timeline: list[dict[str, Any]],
    now_utc: datetime,
) -> float:
    """Share of dated chain rows whose source stamp is within the fresh band."""
    stamps: list[bool] = []
    for item in legal_basis_chain:
        stamps.append(_is_fresh(item.get("ref_fetched_at"), now_utc=now_utc))
    for item in notice_chain:
        stamps.append(_is_fresh(item.get("refreshed_at"), now_utc=now_utc))
    for item in precedent_chain:
        stamps.append(_is_fresh(item.get("fetched_at"), now_utc=now_utc))
    for item in amendment_timeline:
        stamps.append(_is_fresh(item.get("detected_at"), now_utc=now_utc))
    if not stamps:
        return 0.0
    return sum(1 for f in stamps if f) / float(len(stamps))


def _coverage_score(*, claim: float, freshness: float) -> float:
    return round(W_CLAIM * claim + W_FRESHNESS * freshness, 4)


# ---------------------------------------------------------------------------
# Envelope assembly
# ---------------------------------------------------------------------------


def _assemble_packet(
    *,
    program_row: sqlite3.Row,
    legal_basis_chain: list[dict[str, Any]],
    notice_chain: list[dict[str, Any]],
    saiketsu_chain: list[dict[str, Any]],
    precedent_chain: list[dict[str, Any]],
    amendment_timeline: list[dict[str, Any]],
    now_utc: datetime,
) -> dict[str, Any]:
    """Render the JPCIR envelope for one program."""
    program_id = str(program_row["unified_id"])
    claim_coverage = _compute_claim_coverage(
        has_legal_basis=bool(legal_basis_chain),
        has_notices=bool(notice_chain),
        has_saiketsu=bool(saiketsu_chain),
        has_precedents=bool(precedent_chain),
    )
    freshness_coverage = _compute_freshness_coverage(
        legal_basis_chain=legal_basis_chain,
        notice_chain=notice_chain,
        precedent_chain=precedent_chain,
        amendment_timeline=amendment_timeline,
        now_utc=now_utc,
    )
    coverage_score = _coverage_score(claim=claim_coverage, freshness=freshness_coverage)
    created_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "header": {
            "object_id": program_id,
            "object_type": "program_lineage",
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "request_time_llm_call_performed": False,
            "created_at": created_at,
        },
        "package_kind": PACKAGE_KIND,
        "athena_workgroup": ATHENA_WORKGROUP,
        "program": {
            "unified_id": program_id,
            "primary_name": program_row["primary_name"],
            "authority_name": program_row["authority_name"],
            "authority_level": program_row["authority_level"],
            "prefecture": program_row["prefecture"],
            "municipality": program_row["municipality"],
            "program_kind": program_row["program_kind"],
            "tier": program_row["tier"],
            "official_url": program_row["official_url"],
        },
        "legal_basis_chain": legal_basis_chain,
        "notice_chain": notice_chain,
        "saiketsu_chain": saiketsu_chain,
        "precedent_chain": precedent_chain,
        "amendment_timeline": amendment_timeline,
        "coverage_score": {
            "score": coverage_score,
            "claim_coverage": round(claim_coverage, 4),
            "freshness_coverage": round(freshness_coverage, 4),
            "weights": {"claim": W_CLAIM, "freshness": W_FRESHNESS},
        },
        "chain_counts": {
            "legal_basis": len(legal_basis_chain),
            "notice": len(notice_chain),
            "saiketsu": len(saiketsu_chain),
            "precedent": len(precedent_chain),
            "amendment": len(amendment_timeline),
        },
        "_billing_unit": 0,  # pre-rendered, ¥0 lookup
        "_disclaimer": LINEAGE_DISCLAIMER,
    }


def _enforce_size_budget(packet: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Drop low-priority chains until ``MAX_PACKET_BYTES`` is satisfied.

    Drop order (lowest priority first):
        1. amendment_timeline
        2. precedent_chain (last 1 item at a time)
        3. notice_chain (last 1 item at a time)
        4. saiketsu_chain (last 1 item at a time)

    legal_basis_chain is preserved — it is the lineage's anchor.
    Returns ``(packet, truncated_flag)``.
    """
    # PERF-23: orjson size probes via ``_dumps_compact``. ``_dumps_compact``
    # already returns ``bytes`` so the ``.encode("utf-8")`` step is gone.
    truncated = False
    if len(_dumps_compact(packet)) <= MAX_PACKET_BYTES:
        return packet, truncated
    if packet.get("amendment_timeline"):
        packet["amendment_timeline"] = []
        truncated = True
    for chain_key in ("precedent_chain", "notice_chain", "saiketsu_chain"):
        while True:
            if len(_dumps_compact(packet)) <= MAX_PACKET_BYTES:
                break
            chain = packet.get(chain_key)
            if not chain:
                break
            chain.pop()
            truncated = True
        if len(_dumps_compact(packet)) <= MAX_PACKET_BYTES:
            break
    # refresh chain_counts after any truncation
    packet["chain_counts"] = {
        "legal_basis": len(packet.get("legal_basis_chain", [])),
        "notice": len(packet.get("notice_chain", [])),
        "saiketsu": len(packet.get("saiketsu_chain", [])),
        "precedent": len(packet.get("precedent_chain", [])),
        "amendment": len(packet.get("amendment_timeline", [])),
    }
    return packet, truncated


# ---------------------------------------------------------------------------
# Iterators + uploader
# ---------------------------------------------------------------------------


def iter_program_ids(
    jpintel: sqlite3.Connection,
    *,
    batch_size: int,
    limit: int | None,
    batch_start: int | None = None,
    batch_end: int | None = None,
) -> Iterator[list[str]]:
    """Yield batches of program unified_ids; honour ``--limit`` cap.

    ``batch_start`` / ``batch_end`` shard the canonical 11,601-program
    cohort across N AWS Batch shards. The contract: the canonical full
    sweep ordered by ``unified_id ASC`` is sliced by ``LIMIT (end-start)
    OFFSET start``. So the 24-shard plan submits the same script with
    ``--batch-start 0 --batch-end 500`` … ``--batch-start 11500
    --batch-end 12100`` (the last shard runs 11,000-11,601 == 601 rows,
    so caller passes ``--batch-end 11601`` or a sentinel ≥ 11,601).
    Shard bounds are program-row positions, not SQL ``LIMIT``-style
    counts, so the math is the same for every shard.
    """
    sql = (
        "SELECT unified_id FROM programs "
        "WHERE excluded = 0 AND tier IN ('S','A','B','C') "
        "ORDER BY unified_id ASC"
    )
    shard_limit: int | None = None
    shard_offset = 0
    if batch_start is not None or batch_end is not None:
        start = int(batch_start) if batch_start is not None else 0
        end = int(batch_end) if batch_end is not None else 10**9
        if start < 0 or end < start:
            logger.error("invalid shard bounds: start=%d end=%d", start, end)
            return
        shard_offset = start
        shard_limit = end - start
        sql += f" LIMIT {shard_limit} OFFSET {shard_offset}"
    elif limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    try:
        cursor = jpintel.execute(sql)
    except sqlite3.Error as exc:
        logger.error("program id sweep failed: %s", exc)
        return
    batch: list[str] = []
    cap = shard_limit if shard_limit is not None else limit
    emitted_rows = 0
    for row in cursor:
        if cap is not None and emitted_rows >= cap:
            break
        batch.append(str(row["unified_id"]))
        emitted_rows += 1  # noqa: SIM113 - cap-guarded early break; enumerate cannot replace
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _is_s3_prefix(prefix: str) -> bool:
    return prefix.startswith("s3://")


def _parse_s3_prefix(prefix: str) -> tuple[str, str]:
    if not prefix.startswith("s3://"):
        msg = f"not an s3 prefix: {prefix!r}"
        raise ValueError(msg)
    rest = prefix[len("s3://") :]
    bucket, _slash, key_prefix = rest.partition("/")
    if not bucket:
        msg = f"s3 prefix missing bucket: {prefix!r}"
        raise ValueError(msg)
    return bucket, key_prefix


def _import_boto3() -> Any:  # pragma: no cover - trivial shim
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before passing an s3:// prefix."
        )
        raise RuntimeError(msg) from exc
    return boto3


def upload_packet(
    payload: bytes,
    *,
    output_prefix: str,
    program_id: str,
    s3_client: Any | None = None,
) -> str:
    """Write the packet body to ``<output_prefix><program_id>.json``.

    Returns the canonical URI string. Local paths are created on demand;
    s3 URIs route through boto3 (``PutObject``).
    """
    object_name = f"{program_id}.json"
    if _is_s3_prefix(output_prefix):
        bucket, key_prefix = _parse_s3_prefix(output_prefix)
        norm_prefix = key_prefix if key_prefix.endswith("/") or not key_prefix else key_prefix + "/"
        key = f"{norm_prefix}{object_name}"
        if s3_client is None:
            # PERF-35: prefer the shared client pool so the 200-500 ms
            # boto3 cold-start tax is paid once per ``(service, region)``
            # per process across the per-program upload loop. Falls back
            # to the legacy ``_import_boto3`` path when the pool module
            # is unavailable.
            try:
                from scripts.aws_credit_ops._aws import get_client
            except ImportError:
                boto3 = _import_boto3()
                s3_client = boto3.client("s3")
            else:
                s3_client = get_client("s3")
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
        )
        return f"s3://{bucket}/{key}"
    out_dir = Path(output_prefix).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / object_name
    # PERF-23: single-syscall ``os.open`` + ``os.write`` + ``os.close``.
    _write_bytes_fast(out_path, payload)
    return str(out_path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def assemble_one(
    *,
    jpintel: sqlite3.Connection,
    autonomath: sqlite3.Connection | None,
    program_id: str,
    now_utc: datetime,
) -> tuple[dict[str, Any] | None, bool]:
    """Build the JPCIR packet for one program; ``(packet, truncated_flag)``.

    Returns ``(None, False)`` when the program row is missing.
    """
    root = _fetch_program_root(jpintel, program_id)
    if root is None:
        return None, False
    legal_basis = _fetch_legal_basis_chain(jpintel, autonomath, program_id)
    notices = _fetch_notice_chain(autonomath, legal_basis)
    saiketsu = _fetch_saiketsu_chain(autonomath, root["primary_name"])
    precedents = _fetch_precedent_chain(jpintel, legal_basis, root["primary_name"])
    amendments = _fetch_amendment_timeline(autonomath, program_id)
    packet = _assemble_packet(
        program_row=root,
        legal_basis_chain=legal_basis,
        notice_chain=notices,
        saiketsu_chain=saiketsu,
        precedent_chain=precedents,
        amendment_timeline=amendments,
        now_utc=now_utc,
    )
    packet, truncated = _enforce_size_budget(packet)
    return packet, truncated


def run(
    *,
    output_prefix: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    dry_run: bool = True,
    jpintel_db: Path = JPINTEL_DB,
    autonomath_db: Path = AUTONOMATH_DB,
    s3_client: Any | None = None,
    now_utc: datetime | None = None,
    batch_start: int | None = None,
    batch_end: int | None = None,
) -> RunReport:
    """Sweep every program and emit a lineage packet."""
    now = now_utc or datetime.now(UTC)
    report = RunReport(
        output_prefix=output_prefix,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
        athena_workgroup=ATHENA_WORKGROUP,
        started_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    jpintel = _open_ro(jpintel_db)
    if jpintel is None:
        msg = f"jpintel.db missing or unreadable at {jpintel_db}"
        raise FileNotFoundError(msg)
    autonomath = _open_ro(autonomath_db)
    try:
        for batch in iter_program_ids(
            jpintel,
            batch_size=batch_size,
            limit=limit,
            batch_start=batch_start,
            batch_end=batch_end,
        ):
            for program_id in batch:
                pr = PacketReport(program_id=program_id, status="written")
                try:
                    packet, truncated = assemble_one(
                        jpintel=jpintel,
                        autonomath=autonomath,
                        program_id=program_id,
                        now_utc=now,
                    )
                    if packet is None:
                        pr.status = "missing"
                        report.packets.append(pr)
                        continue
                    cov = packet["coverage_score"]
                    pr.coverage_score = float(cov["score"])
                    pr.claim_coverage = float(cov["claim_coverage"])
                    pr.freshness_coverage = float(cov["freshness_coverage"])
                    pr.chain_counts = dict(packet["chain_counts"])
                    # PERF-23: orjson + bytes-out path; 1 packet/file Athena
                    # contract preserved.
                    payload = _dumps_compact(packet)
                    pr.bytes_written = len(payload)
                    if truncated:
                        pr.status = "oversize_truncated"
                    if dry_run:
                        pr.output_uri = f"{output_prefix.rstrip('/')}/{program_id}.json [dry_run]"
                        if pr.status == "written":
                            pr.status = "dry_run"
                    else:
                        pr.output_uri = upload_packet(
                            payload,
                            output_prefix=output_prefix,
                            program_id=program_id,
                            s3_client=s3_client,
                        )
                except Exception as exc:  # noqa: BLE001 — surface every failure
                    pr.status = "error"
                    pr.error_message = str(exc)
                    logger.warning("packet build failed for %s: %s", program_id, exc)
                report.packets.append(pr)
    finally:
        jpintel.close()
        if autonomath is not None:
            autonomath.close()
    report.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate program × law × tsutatsu × saiketsu × court × amendment "
            "lineage packets (JPCIR program_lineage_v1). DRY_RUN default — "
            "pass --commit to actually write."
        )
    )
    parser.add_argument(
        "--output-prefix",
        default=DEFAULT_OUTPUT_PREFIX,
        help=(
            "S3 or local directory prefix for per-program JSON envelopes "
            f"(default: {DEFAULT_OUTPUT_PREFIX})"
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Programs per fetch batch (default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Optional cap on programs processed — useful for smoke runs "
            "(e.g. --limit 100). Default: process every searchable program. "
            "Ignored when --batch-start / --batch-end shard bounds are set."
        ),
    )
    parser.add_argument(
        "--batch-start",
        type=int,
        default=None,
        help=(
            "Shard start offset (row position in the canonical "
            "unified_id-ordered sweep). Pair with --batch-end to slice "
            "the 11,601-program cohort across AWS Batch shards. "
            "Example: --batch-start 0 --batch-end 500 (first shard)."
        ),
    )
    parser.add_argument(
        "--batch-end",
        type=int,
        default=None,
        help=(
            "Shard end offset (exclusive — half-open [start, end) slice). "
            "Pair with --batch-start. Example: 24 shards of 500 programs "
            "with the last shard ending at 11601 (= 601 programs)."
        ),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write packets. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the run report as JSON to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    t0 = time.perf_counter()
    report = run(
        output_prefix=args.output_prefix,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=dry_run,
        batch_start=args.batch_start,
        batch_end=args.batch_end,
    )
    elapsed = time.perf_counter() - t0
    if args.json:
        sys.stdout.write(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        statuses: dict[str, int] = {}
        total_bytes = 0
        oversize = 0
        for p in report.packets:
            statuses[p.status] = statuses.get(p.status, 0) + 1
            total_bytes += p.bytes_written
            if p.bytes_written > MAX_PACKET_BYTES:
                oversize += 1
        sys.stdout.write(
            f"[lineage] output_prefix={report.output_prefix} dry_run={report.dry_run}\n"
        )
        sys.stdout.write(
            f"[lineage] packets={len(report.packets)} elapsed={elapsed:.1f}s "
            f"total_bytes={total_bytes} oversize={oversize}\n"
        )
        for status, count in sorted(statuses.items()):
            sys.stdout.write(f"[lineage]   status={status:<20} count={count}\n")
    # Exit non-zero when no packets were assembled — operational signal.
    if not report.packets:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
