"""FactMetadata — the 4-axis explainable layer for dim O.

Every fact returned by jpcite carries a metadata envelope so the consuming
agent can answer "なぜそう言えるか" (why can you claim that) with **zero
LLM inference**. The four mandatory axes are derived from the dim O memory
(`feedback_explainable_fact_design`):

1. ``source_doc`` — primary-source citation identifier (法令番号 / 公報号 /
   first-party URL). Aggregator URLs (noukaweb, hojyokin-portal, biz.stayway)
   are banned by `CLAUDE.md` data-hygiene contract; this model only enforces
   *non-empty string*, the aggregator-ban check lives in the ingest layer.
2. ``extracted_at`` — ISO 8601 timestamp of the ETL extraction (e.g. when
   the e-Gov XML row was last parsed into am_facts). Used by staleness
   detection in dim Q time-machine queries.
3. ``verified_by`` — one of three enum values:
       * ``manual``       — human operator hand-curated the fact
       * ``cron_etl_v3``  — current-gen ETL extraction job (deterministic)
       * ``ed25519_sig``  — fact is Ed25519-signed by the operator key,
                            verifiable via :func:`verify_fact` in this
                            package without external HTTP
4. ``confidence`` — float in ``[0.0, 1.0]``, typically driven by cross-source
   agreement (dim I). 1.0 = single authoritative primary source agrees with
   itself; <1.0 = disagreement / partial-extraction / inference confidence.

This module deliberately stays small and router-agnostic so it can be
imported from REST handlers, MCP tools, ETL composition scripts, and
offline operator tooling without dragging FastAPI / SQLite handles. The
JSON Schema mirror lives at ``schemas/jpcir/fact_metadata.schema.json`` and
must stay in lockstep with this Pydantic model (round-trip parity is
checked by ``scripts/check_schema_contract_parity.py``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Allowed enum values for :attr:`FactMetadata.verified_by`. Hard-coded here so
#: downstream code can ``from jpintel_mcp.explainable_fact import VerifiedBy``
#: and pattern-match without re-deriving from Pydantic introspection.
VerifiedBy = Literal["manual", "cron_etl_v3", "ed25519_sig"]


class FactMetadata(BaseModel):
    """The 4-axis explainable envelope attached to every fact.

    The model is intentionally **frozen + extra='forbid'** so a typo in a
    field name fails loudly at the API boundary rather than silently
    dropping provenance data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_doc: str = Field(
        min_length=1,
        description=(
            "Primary-source citation identifier. Examples: 法令番号 "
            "(令和七年法律第三十八号) / 公報号 (官報第二〇二六〇五一六号) / "
            "first-party URL (https://www.maff.go.jp/...). Aggregator URLs "
            "are banned at the ingest layer; this model only enforces "
            "non-empty."
        ),
    )
    extracted_at: str = Field(
        min_length=1,
        description=(
            "ISO 8601 timestamp of the ETL extraction. Used for staleness "
            "detection in dim Q time-machine queries."
        ),
    )
    verified_by: VerifiedBy = Field(
        description=(
            "How the fact has been verified. 'manual' = human operator, "
            "'cron_etl_v3' = current-gen ETL job, 'ed25519_sig' = signed "
            "by operator key and verifiable via verify_fact()."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score in [0.0, 1.0]. Typically driven by "
            "cross-source agreement (dim I); 1.0 = single authoritative "
            "primary source, <1.0 = disagreement or partial extraction."
        ),
    )


__all__ = ["FactMetadata", "VerifiedBy"]
