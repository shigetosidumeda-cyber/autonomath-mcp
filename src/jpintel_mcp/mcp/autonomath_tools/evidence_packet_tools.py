"""get_evidence_packet — Evidence Packet composer MCP tool.

Plan reference: ``docs/_internal/llm_resilient_business_plan_2026-04-30.md`` §6.

Mirrors the REST surface at ``GET /v1/evidence/packets/{subject_kind}/{subject_id}``
+ ``POST /v1/evidence/packets/query`` so MCP clients can pull the same
envelope without round-tripping through HTTP. SAME composer is invoked
on both sides — never a parallel implementation.

Pure SQLite + Python. NO LLM call.

Billing: 1 ¥3 unit per call (mirrors REST). Anonymous IPs share the 3/day
cap via the standard MCP gate.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.services.evidence_packet import (
    MAX_RECORDS_PER_PACKET,
    EvidencePacketComposer,
)

logger = logging.getLogger("jpintel.mcp.am.evidence_packet")

#: Env-gate. Default ON; flip "0" to disable without redeploy. Pairs with
#: the global AUTONOMATH_ENABLED gate at the package boundary.
_ENABLED = os.environ.get("AUTONOMATH_EVIDENCE_PACKET_ENABLED", "1") == "1"


# Module-level composer singleton. Built lazily on first call so import
# is cheap (no DB open). Tests use ``_reset_composer`` after monkeypatching
# the DB paths.
_composer: EvidencePacketComposer | None = None
_composer_paths: tuple[str, str] | None = None


def _current_composer_paths() -> tuple[str, str]:
    jpintel_db = Path(os.environ.get("JPINTEL_DB_PATH") or settings.db_path)
    autonomath_db = Path(os.environ.get("AUTONOMATH_DB_PATH") or settings.autonomath_db_path)
    return (str(jpintel_db), str(autonomath_db))


def _get_composer() -> EvidencePacketComposer | None:
    global _composer, _composer_paths
    paths = _current_composer_paths()
    if _composer is None or _composer_paths != paths:
        jpintel_db, autonomath_db = (Path(p) for p in paths)
        try:
            _composer = EvidencePacketComposer(
                jpintel_db=jpintel_db,
                autonomath_db=autonomath_db,
            )
            _composer_paths = paths
        except FileNotFoundError as exc:
            logger.warning(
                "evidence_packet composer init failed: %s (jpintel=%s, autonomath=%s)",
                exc,
                jpintel_db,
                autonomath_db,
            )
            return None
    return _composer


def _reset_composer() -> None:
    """Drop the cached composer. Tests call this after monkeypatching paths."""
    global _composer, _composer_paths
    _composer = None
    _composer_paths = None


def _impl_get_evidence_packet(
    subject_kind: str,
    subject_id: str,
    *,
    include_facts: bool = True,
    include_rules: bool = True,
    include_compression: bool = False,
    fields: str = "default",
    input_token_price_jpy_per_1m: float | None = None,
    packet_profile: str = "full",
) -> dict[str, Any]:
    """Pure-Python core. Split out so tests bypass the @mcp.tool wrapper."""
    sk = (subject_kind or "").strip().lower()
    sid = (subject_id or "").strip()
    if not sid:
        return make_error(
            code="missing_required_arg",
            message="subject_id is required.",
            field="subject_id",
        )
    if sk not in ("program", "houjin"):
        return make_error(
            code="invalid_enum",
            message=(
                "subject_kind must be 'program' or 'houjin'. For "
                "multi-record query packets use the REST POST /v1/evidence"
                "/packets/query endpoint."
            ),
            field="subject_kind",
        )
    composer = _get_composer()
    if composer is None:
        return make_error(
            code="db_unavailable",
            message=(
                "evidence_packet composer のデータソースが見つかりません。"
                "autonomath.db / data/jpintel.db のいずれかが欠落しています。"
            ),
            hint="AUTONOMATH_DB_PATH / JPINTEL_DB_PATH 環境変数を確認してください。",
        )
    if sk == "program":
        envelope = composer.compose_for_program(
            sid,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            profile=packet_profile,
        )
    else:
        envelope = composer.compose_for_houjin(
            sid,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            profile=packet_profile,
        )
    if envelope is None:
        return make_error(
            code="seed_not_found",
            message=f"unknown {sk}_id: {sid!r}",
            hint=(
                "Pass a unified_id (UNI-...) or canonical_id (program:...) "
                "for programs, or a 13-digit 法人番号 for houjin."
            ),
            field="subject_id",
        )
    from jpintel_mcp.api.evidence import _gate_evidence_envelope

    gated, _summary = _gate_evidence_envelope(envelope)
    return gated


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_EVIDENCE_PACKET_ENABLED + the
# global AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def get_evidence_packet(
        subject_kind: Annotated[
            str,
            Field(
                description=(
                    "Subject kind. Closed enum: `program` / `houjin`. For "
                    "multi-record query packets the REST surface POST "
                    "/v1/evidence/packets/query is preferred."
                ),
            ),
        ],
        subject_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "For `program`: a unified_id (UNI-...) or canonical_id "
                    "(program:...). For `houjin`: a 13-digit 法人番号."
                ),
            ),
        ],
        include_facts: Annotated[
            bool,
            Field(description="Include records[].facts[]. Default True."),
        ] = True,
        include_rules: Annotated[
            bool,
            Field(description="Include records[].rules[]. Default True."),
        ] = True,
        include_compression: Annotated[
            bool,
            Field(
                description="Surface compression hints. Default False.",
            ),
        ] = False,
        fields: Annotated[
            str,
            Field(description="Field projection level. `default` / `full`."),
        ] = "default",
        input_token_price_jpy_per_1m: Annotated[
            float | None,
            Field(
                description=("Optional caller's input-token price (JPY per 1M tokens)."),
            ),
        ] = None,
        packet_profile: Annotated[
            str,
            Field(
                description=(
                    "Packet projection: full / brief / verified_only / changes_only. "
                    "Unknown values fall back to full."
                ),
            ),
        ] = "full",
    ) -> dict[str, Any]:
        """[EVIDENCE-PACKET] Returns a single Evidence Packet envelope: primary metadata + per-fact provenance + compat-matrix rule verdicts (program only). NO LLM. 1 ¥3 unit per call. SAME composer as REST /v1/evidence/packets/{subject_kind}/{subject_id}.

        WHAT: Bundles four already-shipped substrates into one envelope —
        ``api.source_manifest._resolve_program`` (resolution + primary
        metadata), ``api.source_manifest._build_manifest`` (per-fact
        provenance), ``services.funding_stack_checker`` (rule verdicts via
        am_compat_matrix + exclusion_rules), and ``am_amendment_diff``
        (corpus_snapshot_id derivation). Fail-open: any upstream failure
        appends a code to ``quality.known_gaps[]`` and the packet still
        renders.

        WHEN:
          - 「この補助金 / 法人について jpcite が知っている全部を一発で
             一次資料 URL 付きで返してほしい」 (LLM への入力前処理)
          - Customer LLM が「答え + 出典」を出すための context bundle
          - 監査再現用の corpus_snapshot_id 付きスナップショット

        WHEN NOT:
          - 単発の制度検索 / 制度詳細 → search_programs / get_program
          - 単発の per-fact provenance → get_provenance_for_fact
          - 単発の併用可否 → check_funding_stack_am
          - 法人 360 だけ欲しい → houjin 360 endpoint

        RETURNS (envelope, spec §6):
          {
            packet_id: "evp_...",
            generated_at: "2026-04-30T00:00:00+09:00",
            api_version: "v1",
            corpus_snapshot_id: "corpus-2026-04-29",
            query: { user_intent, normalized_filters },
            answer_not_included: True,
            records: [
              {
                entity_id, primary_name, record_kind,
                source_url, tier?, prefecture?,
                facts: [ { fact_id, field, value, confidence,
                           source: { url, publisher, fetched_at,
                                     checksum, license } } ],
                rules: [ { rule_id, verdict, evidence_url, note } ],
                fact_provenance_coverage_pct: 0.0..1.0
              }
            ],
            quality: {
              freshness_bucket, coverage_score,
              known_gaps: [...], human_review_required
            },
            verification: {
              replay_endpoint, provenance_endpoint, freshness_endpoint
            },
            _disclaimer: { type, not_legal_or_tax_advice, note }
          }

        DATA QUALITY HONESTY: This composer never invents data. When
        upstream services are unavailable, codes appear in
        ``quality.known_gaps[]`` (`provenance_unavailable`,
        `compat_matrix_unavailable`, `amendment_diff_unavailable`,
        `compat_matrix_no_partner`, `funding_stack_unavailable`). The
        ``_disclaimer`` envelope is mandatory — verify primary source
        before any decision; this is not legal or tax advice.
        """
        return _impl_get_evidence_packet(
            subject_kind=subject_kind,
            subject_id=subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            packet_profile=packet_profile,
        )


__all__ = [
    "MAX_RECORDS_PER_PACKET",
    "_impl_get_evidence_packet",
    "_reset_composer",
]
