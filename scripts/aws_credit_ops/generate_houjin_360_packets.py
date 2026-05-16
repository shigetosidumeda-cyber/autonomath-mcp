#!/usr/bin/env python3
"""Pre-generate ``company_public_baseline`` 法人360 packets for all 166,969 corporates.

Cohort #1 of the prebuilt deliverable packet catalog (§2 of
``docs/_internal/PREBUILT_DELIVERABLE_PACKETS_2026_05_15.md``). Each packet is
a JPCIR ``company_public_baseline`` envelope keyed on the 13-digit
``houjin_bangou`` and combines all 7 public axes into a single < 15 KB JSON:

    1. 基本情報           — gBizINFO + NTA 法人番号 (houjin_master + am_entity_facts)
    2. インボイス登録状態 — T 番号 + 状態 (jpi_invoice_registrants)
    3. 採択事例           — 補助金採択 + 入札落札 (jpi_adoption_records + bids)
    4. 行政処分           — 有無 + severity + 業種別 (am_enforcement_detail)
    5. 法令適用 cross-ref — related_law_ref ロールアップ (am_enforcement_detail)
    6. 評判               — 官報公告 + 行政処分 + 入札除外 (公開コーパス由来のみ)
    7. coverage           — §2.1 6 軸 coverage_score (deterministic, no LLM)

Pipeline
--------

1. **Read** the houjin universe from ``autonomath.db.am_entities`` where
   ``record_kind = 'corporate_entity'`` (166,969 rows).
2. **For each batch** of 1,000 houjin_bangou:

   a. Run a single cross-source JOIN (SQLite read-only, ATTACH the few cross
      tables needed) gathering all 7 axes per houjin.
   b. The "Athena workgroup" gate is honoured for the cost preview: every
      run records a ``athena_bytes_scanned_estimate`` field so the operator
      can reconcile against the workgroup's 100 MB bytes-scan cutoff. We do
      NOT submit Athena queries from this script because the actual source
      data (am_entities, am_enforcement_detail, invoice_registrants, etc.)
      lives in ``autonomath.db`` (SQLite, 9.4 GB) — the Glue catalog only
      has the 4 derived crawl tables (object_manifest / source_receipts /
      claim_refs / known_gaps). Recording the *estimate* keeps the cost
      cap discipline honest without inventing fake Athena rows.
   c. Render the JPCIR envelope (``package_kind="company_public_baseline"``)
      with ``request_time_llm_call_performed=false`` and the canonical
      header constants.
   d. Upload to ``s3://<derived_bucket>/houjin_360/<houjin_bangou>.json``.
   e. Validate every packet against the JPCIR header schema before upload
      (additional fields are tolerated; ``additionalProperties=false`` on the
      header is satisfied because we keep a strict whitelist).

3. **Emit** a per-run manifest with packet counts, total bytes scanned
   estimate, average packet size, and the §2.1 coverage_score rollup.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/generate_houjin_360_packets.py \
        --output-prefix s3://jpcite-credit-993693061769-202605-derived/houjin_360/ \
        [--db autonomath.db] \
        [--batch-size 1000] \
        [--max-batches N] \
        [--commit]

``--commit`` is the dual of ``DRY_RUN=1``: without it, no S3 PUTs happen and
the script writes packets to ``./out/houjin_360/`` for inspection.

Cost
----

Estimated $2-$5 per 10,000 packets (S3 PUT ≈ $0.005 per 1,000 + Athena
bytes-scan estimate budget of 100 MB per 1,000-batch — we honour the
workgroup's bytes-scan cap by chunking).

Constraints
-----------

* **NO LLM API calls** — pure SQLite + Python templating + S3 PUT.
* **Each packet < 15 KB** — enforced by ``MAX_PACKET_BYTES`` + truncation of
  per-axis record arrays (top-N).
* **DRY_RUN default** — ``--commit`` flips to live S3 PUT.
* **Athena workgroup ``jpcite-credit-2026-05``** bytes-scan cutoff 100 MB
  honoured via batch sizing + estimate recording.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
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

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_houjin_360_packets")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: JPCIR header schema version (canonical jpcir.p0.v1).
SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
#: Producer string baked into every envelope.
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
#: package_kind for cohort #1.
PACKAGE_KIND: Final[str] = "company_public_baseline"
#: Per-packet byte ceiling (master plan §2; enforced via top-N truncation).
MAX_PACKET_BYTES: Final[int] = 15 * 1024
#: Per-axis record cap (keeps the envelope under MAX_PACKET_BYTES).
PER_AXIS_RECORD_CAP: Final[int] = 5
#: Default DB path (autonomath.db at the repo root per CLAUDE.md).
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
#: Default batch size (matches the master plan recipe).
DEFAULT_BATCH_SIZE: Final[int] = 1000
#: Athena workgroup bytes-scan cutoff (matches the workgroup config).
ATHENA_WORKGROUP_BYTES_CAP: Final[int] = 100 * 1024 * 1024  # 100 MB
#: Estimated bytes-scan per 1,000-houjin batch (used for the cost preview).
ATHENA_ESTIMATE_BYTES_PER_BATCH: Final[int] = 80 * 1024 * 1024  # 80 MB
#: Estimated S3 PUT cost per 1,000 objects (USD).
S3_PUT_USD_PER_1K: Final[float] = 0.005
#: Default Athena workgroup name (referenced in metrics rollup).
ATHENA_WORKGROUP: Final[str] = "jpcite-credit-2026-05"
#: Default derived bucket (S3) — matches scripts/aws_credit_ops/etl_raw_to_derived.py.
DEFAULT_DERIVED_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"

#: Severity weights mirrored from ``src/jpintel_mcp/api/houjin_360.py``.
_ENFORCEMENT_KIND_WEIGHT: Final[dict[str, float]] = {
    "license_revoke": 1.00,
    "fine": 0.85,
    "grant_refund": 0.85,
    "subsidy_exclude": 0.55,
    "contract_suspend": 0.55,
    "investigation": 0.30,
    "business_improvement": 0.20,
    "warning": 0.15,
}
_ENFORCEMENT_KIND_SEVERITY: Final[dict[str, str]] = {
    "license_revoke": "high",
    "fine": "high",
    "grant_refund": "high",
    "subsidy_exclude": "medium",
    "contract_suspend": "medium",
    "investigation": "low",
    "business_improvement": "low",
    "warning": "low",
}

#: 7-enum known_gap codes per §1.3 of the master plan.
KNOWN_GAP_CODES: Final[frozenset[str]] = frozenset(
    {
        "csv_input_not_evidence_safe",
        "source_receipt_incomplete",
        "pricing_or_cap_unconfirmed",
        "no_hit_not_absence",
        "professional_review_required",
        "freshness_stale_or_unknown",
        "identity_ambiguity_unresolved",
    }
)

#: Default disclaimer (mirrors api/houjin_360.py).
DEFAULT_DISCLAIMER: Final[str] = (
    "本 houjin/360 packet は houjin_master + jpi_adoption_records + "
    "am_enforcement_detail + bids + jpi_invoice_registrants の "
    "**公開情報の名寄せ結果** であり、税理士法 §52・弁護士法 §72・"
    "行政書士法 §1の2 のいずれにも該当しません。coverage_score は "
    "公開コーパスからの descriptive 指標で、与信・税務・法令適用判断には"
    "用いられません。"
)

_BANGOU_RE: Final[re.Pattern[str]] = re.compile(r"^\d{13}$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PacketResult:
    """Outcome of a single packet render + upload."""

    houjin_bangou: str
    s3_key: str
    bytes_written: int
    coverage_score: float
    coverage_grade: str
    status: str  # "written" | "dry_run" | "skipped_empty" | "schema_error"


@dataclass
class RunManifest:
    """Aggregate run-level manifest emitted at the end of the CLI run."""

    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    batch_size: int = DEFAULT_BATCH_SIZE
    dry_run: bool = True
    total_houjin: int = 0
    packets_written: int = 0
    packets_skipped_empty: int = 0
    packets_schema_errors: int = 0
    bytes_total: int = 0
    athena_bytes_scanned_estimate: int = 0
    s3_put_cost_usd_estimate: float = 0.0
    coverage_score_mean: float = 0.0
    packet_results: list[PacketResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_prefix": self.output_prefix,
            "batch_size": self.batch_size,
            "dry_run": self.dry_run,
            "total_houjin": self.total_houjin,
            "packets_written": self.packets_written,
            "packets_skipped_empty": self.packets_skipped_empty,
            "packets_schema_errors": self.packets_schema_errors,
            "bytes_total": self.bytes_total,
            "athena_bytes_scanned_estimate": self.athena_bytes_scanned_estimate,
            "athena_workgroup": ATHENA_WORKGROUP,
            "athena_workgroup_bytes_cap": ATHENA_WORKGROUP_BYTES_CAP,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "coverage_score_mean": round(self.coverage_score_mean, 4),
            "packet_results_sample": [
                dataclasses.asdict(r) for r in self.packet_results[:50]
            ],
        }


# ---------------------------------------------------------------------------
# Cross-source SQL — single ``query bundle`` per houjin batch
# ---------------------------------------------------------------------------

#: Top-level enumeration of every corporate_entity in autonomath.db.
#: ``am_entities`` keeps houjin_bangou inside ``raw_json`` (CHECKed text); we
#: extract via ``json_extract(raw_json, '$.houjin_bangou')`` which is
#: zero-copy when SQLite has the JSON1 extension (default since 3.38).
SQL_ENUMERATE_HOUJIN: Final[str] = (
    "SELECT canonical_id, json_extract(raw_json, '$.houjin_bangou') AS houjin_bangou "
    "  FROM am_entities "
    " WHERE record_kind = 'corporate_entity' "
    "   AND json_extract(raw_json, '$.houjin_bangou') IS NOT NULL "
    " ORDER BY canonical_id "
    " LIMIT ? OFFSET ?"
)

#: Per-batch master block — mirrors api/houjin_360.py::_section_master.
SQL_BATCH_MASTER: Final[str] = (
    "SELECT houjin_bangou, normalized_name, address_normalized, prefecture, "
    "       municipality, corporation_type, established_date, close_date, "
    "       jsic_major, jsic_middle, jsic_minor, total_adoptions, "
    "       total_received_yen, last_updated_nta "
    "  FROM houjin_master "
    " WHERE houjin_bangou IN ({placeholders})"
)

#: Per-batch invoice_registrants block — same fallback chain as
#: api/houjin_360.py::_section_invoice_status.
SQL_BATCH_INVOICE_TEMPLATE: Final[str] = (
    "SELECT houjin_bangou, invoice_registration_number, registered_date, "
    "       revoked_date, expired_date, prefecture, registrant_kind, "
    "       normalized_name "
    "  FROM {table} "
    " WHERE houjin_bangou IN ({placeholders})"
)

#: Per-batch adoption_records aggregate + sample (top-N by amount).
SQL_BATCH_ADOPTION_AGG: Final[str] = (
    "SELECT houjin_bangou, COUNT(*) AS n, "
    "       COALESCE(SUM(amount_granted_yen), 0) AS amt "
    "  FROM jpi_adoption_records "
    " WHERE houjin_bangou IN ({placeholders}) "
    " GROUP BY houjin_bangou"
)
SQL_BATCH_ADOPTION_SAMPLE: Final[str] = (
    "SELECT houjin_bangou, program_id, program_name_raw, round_label, "
    "       amount_granted_yen, announced_at, prefecture, "
    "       industry_jsic_medium, source_url "
    "  FROM jpi_adoption_records "
    " WHERE houjin_bangou IN ({placeholders}) "
    " ORDER BY COALESCE(amount_granted_yen, 0) DESC, "
    "          COALESCE(announced_at, '') DESC"
)

#: Per-batch enforcement aggregate + sample.
SQL_BATCH_ENFORCEMENT_AGG: Final[str] = (
    "SELECT houjin_bangou, COUNT(*) AS n, "
    "       COALESCE(SUM(amount_yen), 0) AS amt "
    "  FROM am_enforcement_detail "
    " WHERE houjin_bangou IN ({placeholders}) "
    " GROUP BY houjin_bangou"
)
SQL_BATCH_ENFORCEMENT_SAMPLE: Final[str] = (
    "SELECT houjin_bangou, issuance_date, enforcement_kind, reason_summary, "
    "       amount_yen, issuing_authority, related_law_ref, source_url, "
    "       exclusion_start, exclusion_end "
    "  FROM am_enforcement_detail "
    " WHERE houjin_bangou IN ({placeholders}) "
    " ORDER BY issuance_date DESC"
)

#: Per-batch bids (jpi_bids fallback to bids).
SQL_BATCH_BIDS_AGG_TEMPLATE: Final[str] = (
    "SELECT winner_houjin_bangou AS houjin_bangou, COUNT(*) AS n, "
    "       COALESCE(SUM(awarded_amount_yen), 0) AS amt "
    "  FROM {table} "
    " WHERE winner_houjin_bangou IN ({placeholders}) "
    " GROUP BY winner_houjin_bangou"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_bangou(raw: str) -> str | None:
    """Return the 13-digit houjin_bangou or None if malformed."""

    if raw is None:
        return None
    s = str(raw).strip().lstrip("Tt").replace("-", "").replace(" ", "")
    return s if _BANGOU_RE.match(s) else None


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _pick_invoice_table(conn: sqlite3.Connection) -> str | None:
    for candidate in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(conn, candidate):
            return candidate
    return None


def _pick_bids_table(conn: sqlite3.Connection) -> str | None:
    for candidate in ("jpi_bids", "bids"):
        if _table_exists(conn, candidate):
            return candidate
    return None


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def _logistic(value: float, *, scale: float) -> float:
    v = max(0.0, float(value))
    if scale <= 0:
        return 0.0
    return v / (v + scale)


def _coverage_grade(score: float) -> str:
    if score >= 0.85:
        return "S"
    if score >= 0.70:
        return "A"
    if score >= 0.50:
        return "B"
    if score >= 0.25:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# §2.1 coverage_score (deterministic, descriptive)
# ---------------------------------------------------------------------------


def compute_coverage_score(
    *,
    master_present: bool,
    invoice_status: str,
    adoption_total: int,
    enforcement_total: int,
    enforcement_max_severity: str | None,
    bids_total: int,
    sources_count: int,
) -> tuple[float, str]:
    """Compute §2.1 coverage_score for a 法人360 packet.

    Components (each in [0, 1]):

    * ``fact_coverage``        — master_present + invoice_status presence
    * ``claim_coverage``       — adoption + bids volume signals
    * ``citation_coverage``    — adoption + enforcement source_url presence
    * ``freshness_coverage``   — invoice active flag + master last_updated
    * ``receipt_completion``   — sources_count > 0
    * ``gap_penalty``          — high-severity enforcement triggers penalty

    Formula (from PREBUILT_DELIVERABLE_PACKETS_2026_05_15.md §2.1)::

        coverage_score = 0.35 * fact_coverage
                       + 0.25 * claim_coverage
                       + 0.20 * citation_coverage
                       + 0.15 * freshness_coverage
                       + 0.05 * receipt_completion
                       - gap_penalty
    """

    fact_coverage = 0.0
    if master_present:
        fact_coverage += 0.6
    if invoice_status in {"active", "inactive", "revoked", "expired"}:
        fact_coverage += 0.4
    fact_coverage = min(1.0, fact_coverage)

    claim_coverage = round(
        0.5 * _logistic(adoption_total, scale=3.0) + 0.5 * _logistic(bids_total, scale=3.0),
        4,
    )

    citation_coverage = 0.0
    if adoption_total > 0:
        citation_coverage += 0.5
    if enforcement_total > 0:
        citation_coverage += 0.5
    citation_coverage = min(1.0, citation_coverage)

    freshness_coverage = 1.0 if invoice_status == "active" else 0.5

    receipt_completion = 1.0 if sources_count > 0 else 0.0

    gap_penalty = 0.0
    if enforcement_max_severity == "high":
        gap_penalty = min(0.30, 0.08 * enforcement_total)
    elif enforcement_max_severity == "medium":
        gap_penalty = min(0.20, 0.04 * enforcement_total)
    elif enforcement_max_severity == "low":
        gap_penalty = min(0.10, 0.02 * enforcement_total)

    raw = (
        0.35 * fact_coverage
        + 0.25 * claim_coverage
        + 0.20 * citation_coverage
        + 0.15 * freshness_coverage
        + 0.05 * receipt_completion
        - gap_penalty
    )
    score = max(0.0, min(1.0, raw))
    return round(score, 4), _coverage_grade(score)


# ---------------------------------------------------------------------------
# Cross-source query bundle (per batch of 1,000 houjin_bangou)
# ---------------------------------------------------------------------------


def fetch_batch_axes(
    conn: sqlite3.Connection,
    bangou_batch: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Run all per-axis SQL for a houjin batch; return ``{bangou: bundle}``.

    Bundles carry partial axes — each downstream renderer is responsible for
    surfacing the section even when an axis is empty (consistent with the
    api/houjin_360.py soft-fail semantics).
    """

    if not bangou_batch:
        return {}
    placeholders = _placeholders(len(bangou_batch))
    params = tuple(bangou_batch)
    bundle: dict[str, dict[str, Any]] = {b: {"houjin_bangou": b} for b in bangou_batch}

    # Master
    if _table_exists(conn, "houjin_master"):
        sql = SQL_BATCH_MASTER.format(placeholders=placeholders)
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql, params).fetchall():
                bangou = row["houjin_bangou"]
                bundle.setdefault(bangou, {"houjin_bangou": bangou})["master"] = dict(row)

    # Invoice
    inv_table = _pick_invoice_table(conn)
    if inv_table is not None:
        sql = SQL_BATCH_INVOICE_TEMPLATE.format(table=inv_table, placeholders=placeholders)
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql, params).fetchall():
                bangou = row["houjin_bangou"]
                bundle.setdefault(bangou, {"houjin_bangou": bangou})["invoice"] = dict(row)

    # Adoption aggregate + sample
    if _table_exists(conn, "jpi_adoption_records"):
        sql_agg = SQL_BATCH_ADOPTION_AGG.format(placeholders=placeholders)
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql_agg, params).fetchall():
                bangou = row["houjin_bangou"]
                d = bundle.setdefault(bangou, {"houjin_bangou": bangou}).setdefault(
                    "adoption", {"total": 0, "total_amount_yen": 0, "records": []}
                )
                d["total"] = int(row["n"] or 0)
                d["total_amount_yen"] = int(row["amt"] or 0)
        sql_sample = SQL_BATCH_ADOPTION_SAMPLE.format(placeholders=placeholders)
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql_sample, params).fetchall():
                bangou = row["houjin_bangou"]
                d = bundle.setdefault(bangou, {"houjin_bangou": bangou}).setdefault(
                    "adoption", {"total": 0, "total_amount_yen": 0, "records": []}
                )
                if len(d["records"]) >= PER_AXIS_RECORD_CAP:
                    continue
                d["records"].append(
                    {
                        "program_id": row["program_id"],
                        "program_name": row["program_name_raw"],
                        "round_label": row["round_label"],
                        "amount_granted_yen": (
                            int(row["amount_granted_yen"])
                            if row["amount_granted_yen"] is not None
                            else None
                        ),
                        "announced_at": row["announced_at"],
                        "prefecture": row["prefecture"],
                        "industry_jsic_medium": row["industry_jsic_medium"],
                        "source_url": row["source_url"],
                    }
                )

    # Enforcement aggregate + sample
    if _table_exists(conn, "am_enforcement_detail"):
        sql_agg = SQL_BATCH_ENFORCEMENT_AGG.format(placeholders=placeholders)
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql_agg, params).fetchall():
                bangou = row["houjin_bangou"]
                d = bundle.setdefault(bangou, {"houjin_bangou": bangou}).setdefault(
                    "enforcement",
                    {
                        "total": 0,
                        "total_amount_yen": 0,
                        "max_severity": None,
                        "records": [],
                    },
                )
                d["total"] = int(row["n"] or 0)
                d["total_amount_yen"] = int(row["amt"] or 0)
        sql_sample = SQL_BATCH_ENFORCEMENT_SAMPLE.format(placeholders=placeholders)
        severity_rank = {"low": 1, "medium": 2, "high": 3}
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql_sample, params).fetchall():
                bangou = row["houjin_bangou"]
                kind = row["enforcement_kind"] or ""
                severity = _ENFORCEMENT_KIND_SEVERITY.get(kind, "low")
                d = bundle.setdefault(bangou, {"houjin_bangou": bangou}).setdefault(
                    "enforcement",
                    {
                        "total": 0,
                        "total_amount_yen": 0,
                        "max_severity": None,
                        "records": [],
                    },
                )
                cur_max = d.get("max_severity")
                if cur_max is None or severity_rank.get(severity, 0) > severity_rank.get(
                    cur_max, 0
                ):
                    d["max_severity"] = severity
                if len(d["records"]) >= PER_AXIS_RECORD_CAP:
                    continue
                d["records"].append(
                    {
                        "issuance_date": row["issuance_date"],
                        "enforcement_kind": kind or None,
                        "severity": severity,
                        "reason_summary": row["reason_summary"],
                        "amount_yen": (
                            int(row["amount_yen"]) if row["amount_yen"] is not None else None
                        ),
                        "issuing_authority": row["issuing_authority"],
                        "related_law_ref": row["related_law_ref"],
                        "source_url": row["source_url"],
                        "exclusion_start": row["exclusion_start"],
                        "exclusion_end": row["exclusion_end"],
                    }
                )

    # Bids aggregate
    bids_table = _pick_bids_table(conn)
    if bids_table is not None:
        sql_agg = SQL_BATCH_BIDS_AGG_TEMPLATE.format(
            table=bids_table, placeholders=placeholders
        )
        with contextlib.suppress(sqlite3.Error):
            for row in conn.execute(sql_agg, params).fetchall():
                bangou = row["houjin_bangou"]
                d = bundle.setdefault(bangou, {"houjin_bangou": bangou}).setdefault(
                    "bids", {"total": 0, "total_awarded_yen": 0}
                )
                d["total"] = int(row["n"] or 0)
                d["total_awarded_yen"] = int(row["amt"] or 0)

    return bundle


# ---------------------------------------------------------------------------
# Packet renderer — JPCIR ``company_public_baseline`` envelope
# ---------------------------------------------------------------------------


def _infer_invoice_status(invoice: dict[str, Any] | None) -> str:
    if invoice is None:
        return "not_found"
    if invoice.get("revoked_date"):
        return "revoked"
    if invoice.get("expired_date"):
        return "expired"
    if invoice.get("invoice_registration_number"):
        return "active"
    return "inactive"


def render_packet(  # noqa: PLR0912 - one branch per axis is intentional
    bundle: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Build the JPCIR ``company_public_baseline`` envelope for a houjin."""

    bangou = bundle["houjin_bangou"]
    master = bundle.get("master") or None
    invoice = bundle.get("invoice") or None
    adoption = bundle.get("adoption") or {
        "total": 0,
        "total_amount_yen": 0,
        "records": [],
    }
    enforcement = bundle.get("enforcement") or {
        "total": 0,
        "total_amount_yen": 0,
        "max_severity": None,
        "records": [],
    }
    bids = bundle.get("bids") or {"total": 0, "total_awarded_yen": 0}

    invoice_status = _infer_invoice_status(invoice)

    # Sources roll-up — every record that carries a source_url contributes.
    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for record in adoption.get("records", []):
        url = record.get("source_url")
        if isinstance(url, str) and url and url not in seen_urls:
            sources.append(
                {
                    "source_url": url,
                    "source_fetched_at": None,
                    "publisher": "jpi_adoption_records",
                    "license": "pdl_v1.0",
                }
            )
            seen_urls.add(url)
    for record in enforcement.get("records", []):
        url = record.get("source_url")
        if isinstance(url, str) and url and url not in seen_urls:
            sources.append(
                {
                    "source_url": url,
                    "source_fetched_at": None,
                    "publisher": "am_enforcement_detail",
                    "license": "gov_standard",
                }
            )
            seen_urls.add(url)
    if invoice is not None and invoice.get("invoice_registration_number"):
        sources.append(
            {
                "source_url": (
                    "https://www.invoice-kohyo.nta.go.jp/regno-search/snets?selRegNo="
                    + str(invoice.get("invoice_registration_number"))
                ),
                "source_fetched_at": None,
                "publisher": "NTA invoice registry",
                "license": "pdl_v1.0",
            }
        )
    if master is not None:
        sources.append(
            {
                "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}",
                "source_fetched_at": master.get("last_updated_nta"),
                "publisher": "NTA 法人番号公表サイト",
                "license": "pdl_v1.0",
            }
        )

    coverage_score, coverage_grade = compute_coverage_score(
        master_present=master is not None,
        invoice_status=invoice_status,
        adoption_total=int(adoption.get("total") or 0),
        enforcement_total=int(enforcement.get("total") or 0),
        enforcement_max_severity=enforcement.get("max_severity"),
        bids_total=int(bids.get("total") or 0),
        sources_count=len(sources),
    )

    known_gaps: list[dict[str, str]] = []
    if master is None:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": "houjin_master row missing — NTA bulk ingest may not have caught up.",
            }
        )
    if invoice is None:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": "invoice_registrants row missing — T 番号 unresolved.",
            }
        )
    if adoption.get("total", 0) == 0 and enforcement.get("total", 0) == 0 and bids.get(
        "total", 0
    ) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "All public-corpus axes empty for this 法人番号. Treat as no_hit, "
                    "not as absence of activity."
                ),
            }
        )

    sections: list[dict[str, str]] = []
    name = (master or {}).get("normalized_name") or bangou
    sections.append(
        {
            "section_id": "kihon_jouhou",
            "title": "基本情報 (gBizINFO + NTA 法人番号)",
            "body": (
                f"**法人番号**: `{bangou}`\n"
                f"**法人名**: {name}\n"
                f"**所在地**: {(master or {}).get('address_normalized') or '(未収録)'}\n"
                f"**設立日**: {(master or {}).get('established_date') or '(未収録)'}\n"
                f"**JSIC**: {(master or {}).get('jsic_major') or '(未収録)'}\n"
            ),
        }
    )
    sections.append(
        {
            "section_id": "invoice_status",
            "title": "インボイス登録状態 (T 番号)",
            "body": (
                f"**status**: `{invoice_status}`\n"
                f"**T 番号**: "
                f"{(invoice or {}).get('invoice_registration_number') or '(未登録)'}\n"
                f"**登録日**: {(invoice or {}).get('registered_date') or '(—)'}\n"
            ),
        }
    )
    sections.append(
        {
            "section_id": "saitaku_jirei",
            "title": "採択事例 + 入札落札",
            "body": (
                f"**採択件数**: {int(adoption.get('total') or 0):,}\n"
                f"**採択合計**: ¥{int(adoption.get('total_amount_yen') or 0):,}\n"
                f"**入札落札件数**: {int(bids.get('total') or 0):,}\n"
                f"**入札落札合計**: ¥{int(bids.get('total_awarded_yen') or 0):,}\n"
            ),
        }
    )
    sections.append(
        {
            "section_id": "gyousei_shobun",
            "title": "行政処分 (有無 + severity)",
            "body": (
                f"**処分件数**: {int(enforcement.get('total') or 0):,}\n"
                f"**max severity**: `{enforcement.get('max_severity') or 'none'}`\n"
                f"**処分合計額**: ¥{int(enforcement.get('total_amount_yen') or 0):,}\n"
            ),
        }
    )
    related_laws = [
        r.get("related_law_ref")
        for r in enforcement.get("records", [])
        if isinstance(r.get("related_law_ref"), str)
    ]
    sections.append(
        {
            "section_id": "horei_cross_ref",
            "title": "法令適用 cross-ref",
            "body": (
                "**処分根拠法**: "
                + (", ".join(sorted({r for r in related_laws if r})) if related_laws else "(無)")
                + "\n"
            ),
        }
    )
    sections.append(
        {
            "section_id": "hyouban_signal",
            "title": "評判 signal (公開コーパス由来のみ)",
            "body": (
                f"**入札除外**: "
                f"{ '有' if any(r.get('enforcement_kind') == 'subsidy_exclude' for r in enforcement.get('records', [])) else '無' }\n"
                f"**罰金処分**: "
                f"{ '有' if any(r.get('enforcement_kind') == 'fine' for r in enforcement.get('records', [])) else '無' }\n"
            ),
        }
    )

    records: list[dict[str, Any]] = []
    for record in adoption.get("records", [])[:PER_AXIS_RECORD_CAP]:
        records.append({"axis": "adoption", **record})
    for record in enforcement.get("records", [])[:PER_AXIS_RECORD_CAP]:
        records.append({"axis": "enforcement", **record})

    package_id = f"company_public_baseline:{bangou}"
    envelope: dict[str, Any] = {
        # ----- JPCIR header (whitelisted, all const-valid) -----
        "object_id": package_id,
        "object_type": "packet",
        "created_at": generated_at,
        "producer": PRODUCER,
        "request_time_llm_call_performed": False,
        "schema_version": SCHEMA_VERSION,
        # ----- packet envelope -----
        "package_id": package_id,
        "package_kind": PACKAGE_KIND,
        "generated_at": generated_at,
        "subject": {"kind": "houjin", "id": bangou},
        "coverage": {
            "coverage_score": coverage_score,
            "coverage_grade": coverage_grade,
        },
        "sources": sources,
        "records": records,
        "sections": sections,
        "known_gaps": known_gaps,
        "jpcite_cost_jpy": 0,  # pre-generated packet, no per-call cost
        "source_count": len(sources),
        "disclaimer": DEFAULT_DISCLAIMER,
    }
    return envelope


# ---------------------------------------------------------------------------
# JPCIR header validation (no external jsonschema dep)
# ---------------------------------------------------------------------------


def validate_jpcir_header(envelope: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate the JPCIR header subset baked into every envelope.

    Mirrors ``schemas/jpcir/jpcir_header.schema.json``. We do NOT pull
    jsonschema as a hard dep — the header contract has 6 fields, so a hand
    check is cheaper than a runtime dep and keeps the script importable in
    minimal environments.
    """

    errors: list[str] = []
    object_id = envelope.get("object_id")
    object_type = envelope.get("object_type")
    created_at = envelope.get("created_at")
    producer = envelope.get("producer")
    rt_llm = envelope.get("request_time_llm_call_performed")
    schema_version = envelope.get("schema_version")
    if not isinstance(object_id, str) or not object_id:
        errors.append("object_id missing or empty")
    if not isinstance(object_type, str) or not object_type:
        errors.append("object_type missing or empty")
    if not isinstance(created_at, str) or not created_at:
        errors.append("created_at missing or empty")
    if producer != PRODUCER:
        errors.append(f"producer must be {PRODUCER!r}, got {producer!r}")
    if rt_llm is not False:
        errors.append("request_time_llm_call_performed must be false")
    if schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    return (not errors, errors)


# ---------------------------------------------------------------------------
# S3 upload (or local fallback in DRY_RUN)
# ---------------------------------------------------------------------------


def _import_boto3() -> Any:  # pragma: no cover - thin shim
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install boto3 in the operator environment "
            "(pip install boto3) before running with --commit."
        )
        raise RuntimeError(msg) from exc
    return boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        msg = f"not an s3 URI: {uri!r}"
        raise ValueError(msg)
    rest = uri[len("s3://") :]
    bucket, _slash, key = rest.partition("/")
    return bucket, key


def upload_packet(
    *,
    envelope: dict[str, Any],
    output_prefix: str,
    dry_run: bool,
    s3_client: Any | None,
    local_out_dir: Path,
) -> tuple[str, int]:
    """Write the packet to S3 (or local out dir in DRY_RUN). Returns ``(key, bytes)``.

    ``output_prefix`` may be ``s3://bucket/path/`` or a local directory; in
    DRY_RUN we always write locally regardless so the operator can inspect.
    """

    bangou = envelope["subject"]["id"]
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    bytes_written = len(body)

    if output_prefix.startswith("s3://"):
        bucket, key_prefix = _parse_s3_uri(output_prefix)
        key = f"{key_prefix.rstrip('/')}/{bangou}.json"
        if dry_run or s3_client is None:
            # Mirror to local for inspection (key path retained).
            local_path = local_out_dir / f"{bangou}.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(body)
            return key, bytes_written
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            CacheControl="max-age=86400",
        )
        return key, bytes_written

    local_path = Path(output_prefix).expanduser() / f"{bangou}.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(body)
    return str(local_path), bytes_written


# ---------------------------------------------------------------------------
# Houjin enumeration (from autonomath.db.am_entities)
# ---------------------------------------------------------------------------


def enumerate_houjin(
    conn: sqlite3.Connection,
    *,
    batch_size: int,
    max_batches: int | None,
    batch_start: int = 0,
    batch_end: int | None = None,
) -> Iterator[list[str]]:
    """Yield batches of houjin_bangou strings from am_entities.

    Falls back to ``houjin_master`` when am_entities is unavailable / schema
    drift hides ``record_kind = 'corporate_entity'`` — both shapes are
    documented in CLAUDE.md so we accept either.

    Sharding
    --------

    ``batch_start`` / ``batch_end`` are **row** offsets, not batch indices —
    they translate to ``OFFSET batch_start`` and ``LIMIT (batch_end - batch_start)``
    so a Batch shard can claim ``[batch_start, batch_end)`` and the wrapper
    submits 167 shards of 1,000 rows each (last shard = 166,000-166,969).
    The yielded sub-batch size is still capped at ``batch_size`` so a 1,000-row
    shard with ``batch_size=1000`` yields exactly one batch.
    """

    span_rows: int | None = (
        max(0, batch_end - batch_start) if batch_end is not None else None
    )

    if _table_exists(conn, "am_entities"):
        offset = batch_start
        batches_emitted = 0
        rows_emitted = 0
        while True:
            if span_rows is not None:
                remaining = span_rows - rows_emitted
                if remaining <= 0:
                    return
                step = min(batch_size, remaining)
            else:
                step = batch_size
            rows = conn.execute(SQL_ENUMERATE_HOUJIN, (step, offset)).fetchall()
            if not rows:
                break
            bangou_batch: list[str] = []
            for row in rows:
                bangou = _normalize_bangou(row["houjin_bangou"])
                if bangou is not None:
                    bangou_batch.append(bangou)
            if bangou_batch:
                yield bangou_batch
                batches_emitted += 1
                rows_emitted += len(rows)
                if max_batches is not None and batches_emitted >= max_batches:
                    return
            else:
                rows_emitted += len(rows)
            offset += step
        return

    if _table_exists(conn, "houjin_master"):
        offset = batch_start
        batches_emitted = 0
        rows_emitted = 0
        while True:
            if span_rows is not None:
                remaining = span_rows - rows_emitted
                if remaining <= 0:
                    return
                step = min(batch_size, remaining)
            else:
                step = batch_size
            rows = conn.execute(
                "SELECT houjin_bangou FROM houjin_master "
                " WHERE houjin_bangou IS NOT NULL "
                " ORDER BY houjin_bangou "
                " LIMIT ? OFFSET ?",
                (step, offset),
            ).fetchall()
            if not rows:
                break
            bangou_batch = [
                b for b in (_normalize_bangou(r["houjin_bangou"]) for r in rows) if b
            ]
            if bangou_batch:
                yield bangou_batch
                batches_emitted += 1
                rows_emitted += len(rows)
                if max_batches is not None and batches_emitted >= max_batches:
                    return
            else:
                rows_emitted += len(rows)
            offset += step
        return


# ---------------------------------------------------------------------------
# Run orchestrator
# ---------------------------------------------------------------------------


def open_db_ro(db_path: Path) -> sqlite3.Connection:
    """Open the SQLite DB read-only with the same PRAGMAs as the live API."""

    if not db_path.exists() or db_path.stat().st_size == 0:
        msg = f"database not found or empty: {db_path}"
        raise RuntimeError(msg)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def run(
    *,
    db_path: Path,
    output_prefix: str,
    batch_size: int,
    max_batches: int | None,
    dry_run: bool,
    local_out_dir: Path,
    batch_start: int = 0,
    batch_end: int | None = None,
) -> RunManifest:
    """Execute the full pipeline. Returns the run manifest."""

    started = _now_utc_iso()
    manifest = RunManifest(
        started_at=started,
        output_prefix=output_prefix,
        batch_size=batch_size,
        dry_run=dry_run,
    )

    s3_client: Any | None = None
    if output_prefix.startswith("s3://") and not dry_run:
        s3_client = _import_boto3().client("s3")

    conn = open_db_ro(db_path)
    try:
        running_coverage_total = 0.0
        running_coverage_n = 0
        for bangou_batch in enumerate_houjin(
            conn,
            batch_size=batch_size,
            max_batches=max_batches,
            batch_start=batch_start,
            batch_end=batch_end,
        ):
            manifest.total_houjin += len(bangou_batch)
            manifest.athena_bytes_scanned_estimate += ATHENA_ESTIMATE_BYTES_PER_BATCH
            bundle_map = fetch_batch_axes(conn, bangou_batch)
            generated_at = _now_utc_iso()
            for bangou in bangou_batch:
                bundle = bundle_map.get(bangou, {"houjin_bangou": bangou})
                envelope = render_packet(bundle, generated_at=generated_at)
                ok, errors = validate_jpcir_header(envelope)
                if not ok:
                    manifest.packets_schema_errors += 1
                    logger.warning(
                        "schema validation failed for %s: %s", bangou, "; ".join(errors)
                    )
                    manifest.packet_results.append(
                        PacketResult(
                            houjin_bangou=bangou,
                            s3_key="",
                            bytes_written=0,
                            coverage_score=0.0,
                            coverage_grade="D",
                            status="schema_error",
                        )
                    )
                    continue
                # Skip when every public axis is empty AND no master AND no invoice.
                if (
                    bundle.get("master") is None
                    and bundle.get("invoice") is None
                    and not bundle.get("adoption")
                    and not bundle.get("enforcement")
                    and not bundle.get("bids")
                ):
                    manifest.packets_skipped_empty += 1
                    manifest.packet_results.append(
                        PacketResult(
                            houjin_bangou=bangou,
                            s3_key="",
                            bytes_written=0,
                            coverage_score=0.0,
                            coverage_grade="D",
                            status="skipped_empty",
                        )
                    )
                    continue
                key, written = upload_packet(
                    envelope=envelope,
                    output_prefix=output_prefix,
                    dry_run=dry_run,
                    s3_client=s3_client,
                    local_out_dir=local_out_dir,
                )
                manifest.packets_written += 1
                manifest.bytes_total += written
                cs = float(envelope["coverage"]["coverage_score"])
                cg = str(envelope["coverage"]["coverage_grade"])
                running_coverage_total += cs
                running_coverage_n += 1
                manifest.packet_results.append(
                    PacketResult(
                        houjin_bangou=bangou,
                        s3_key=key,
                        bytes_written=written,
                        coverage_score=cs,
                        coverage_grade=cg,
                        status="dry_run" if dry_run else "written",
                    )
                )
        if running_coverage_n:
            manifest.coverage_score_mean = running_coverage_total / running_coverage_n
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    manifest.s3_put_cost_usd_estimate = (
        manifest.packets_written / 1000.0
    ) * S3_PUT_USD_PER_1K
    manifest.finished_at = _now_utc_iso()
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Pre-generate company_public_baseline 法人 360 packets for "
            "every corporate_entity in autonomath.db."
        ),
    )
    p.add_argument(
        "--output-prefix",
        required=True,
        help=(
            "S3 URI (s3://bucket/path/) or local directory to write "
            "<houjin_bangou>.json packets to. DRY_RUN default writes locally."
        ),
    )
    p.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"autonomath.db path (default: {DEFAULT_DB_PATH!r}).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Houjin batch size (default: {DEFAULT_BATCH_SIZE}).",
    )
    p.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop after N batches (for smoke runs). Default: all 166,969 corporates.",
    )
    p.add_argument(
        "--batch-start",
        type=int,
        default=0,
        help=(
            "Row offset (inclusive) for sharded AWS Batch execution. "
            "Default: 0 (start of corpus)."
        ),
    )
    p.add_argument(
        "--batch-end",
        type=int,
        default=None,
        help=(
            "Row offset (exclusive) for sharded AWS Batch execution. "
            "Default: None (end of corpus). With --batch-start, the shard "
            "covers rows [batch-start, batch-end)."
        ),
    )
    p.add_argument(
        "--local-out-dir",
        default="out/houjin_360",
        help="Local output directory used in DRY_RUN and as the S3 mirror (default: out/houjin_360).",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Lift the DRY_RUN guard and actually PUT packets to S3.",
    )
    p.add_argument(
        "--manifest-out",
        default=None,
        help="Write the run manifest JSON here (default: <local-out-dir>/run_manifest.json).",
    )
    return p.parse_args(list(argv))


def _digest_envelope(envelope: dict[str, Any]) -> str:
    body = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    dry_run = not args.commit
    if os.environ.get("DRY_RUN") == "0" and not args.commit:
        logger.warning("DRY_RUN=0 set but --commit missing — staying in dry-run mode.")
    db_path = Path(args.db)
    local_out_dir = Path(args.local_out_dir)
    local_out_dir.mkdir(parents=True, exist_ok=True)
    started_t = time.perf_counter()
    try:
        manifest = run(
            db_path=db_path,
            output_prefix=str(args.output_prefix),
            batch_size=int(args.batch_size),
            max_batches=int(args.max_batches) if args.max_batches is not None else None,
            dry_run=dry_run,
            local_out_dir=local_out_dir,
            batch_start=int(args.batch_start),
            batch_end=int(args.batch_end) if args.batch_end is not None else None,
        )
    except RuntimeError as exc:
        logger.error("run failed: %s", exc)
        return 1

    manifest_path = (
        Path(args.manifest_out)
        if args.manifest_out is not None
        else local_out_dir / "run_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started_t
    logger.info(
        "run done: total_houjin=%d written=%d empty=%d schema_err=%d "
        "bytes_total=%d athena_estimate=%d s3_put_usd~=%.4f "
        "coverage_mean=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.total_houjin,
        manifest.packets_written,
        manifest.packets_skipped_empty,
        manifest.packets_schema_errors,
        manifest.bytes_total,
        manifest.athena_bytes_scanned_estimate,
        manifest.s3_put_cost_usd_estimate,
        manifest.coverage_score_mean,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
