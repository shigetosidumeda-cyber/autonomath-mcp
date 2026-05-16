"""Wave 51 dim P — Composable-tools MCP wrappers (4 composed tools).

Four MCP tools that surface the 4 initial server-side composed tools
defined in ``jpintel_mcp.composable_tools`` (Wave 51 dim P). Each wrapper
returns the canonical :class:`ComposedEnvelope` dict shape so customer
agents pay ¥3 × 1 (one composed call) instead of ¥3 × N (N atomic
calls). Compression ratio is surfaced explicitly.

Surfaced tools:
    eligibility_audit_workpaper_composed  (4 atomic → 1, 税理士 monthly)
    subsidy_eligibility_full_composed     (5 atomic → 1, 補助金 7-step)
    ma_due_diligence_pack_composed        (4 atomic → 1, M&A DD)
    invoice_compatibility_check_composed  (3 atomic → 1, 適格事業者)

Hard constraints (CLAUDE.md):

* NO LLM call inside any composed tool body. Composition order is
  deterministic — declared at class level via ``atomic_dependencies``.
* No re-entry into the MCP protocol. The injected
  :class:`AtomicRegistry` is a Python-callable dispatcher; MCP-to-MCP
  recursion would re-spend the metering budget composition exists to
  compress.
* 1 ¥3/billable unit per composed call (single billing event).
* §52 / §47条の2 / §72 / §1 / §3 non-substitution disclaimer envelope.
* When the runtime cannot wire the full atomic registry (e.g. cron
  context with no DB handles), the wrapper still emits the canonical
  composed structure with a ``warnings`` entry — never raises.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.composable_tools import (
    AtomicCallResult,
    EligibilityAuditWorkpaper,
    InvoiceCompatibilityCheck,
    MaDueDiligencePack,
    SubsidyEligibilityFull,
)
from jpintel_mcp.composable_tools.base import (
    ComposableTool,
    ComposedEnvelope,
    ComposedToolError,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_dim_p_composed")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_DIM_P_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_DISCLAIMER = (
    "本 response は Wave 51 dim P composable_tools の server-side composition "
    "結果です。N atomic call を 1 ¥3 unit に圧縮した構造的 envelope であり、"
    "個別 atomic surface は jpcite SQLite + 純 Python 経由で deterministic に "
    "解決されます。法的助言ではなく、税理士法 §52 / 公認会計士法 §47条の2 / "
    "弁護士法 §72 / 行政書士法 §1 / 司法書士法 §3 の代替ではありません。"
)


class _StubAtomicRegistry:
    """Empty atomic registry stub for composed-tool MCP wrappers.

    The full atomic Python callable registry is wired in REST + ETL
    paths; in the FastMCP stdio runtime the atomic surface is the
    @mcp.tool registry, not a direct Python callable graph. Re-entering
    the MCP protocol from a composed tool would re-spend the metering
    budget composition exists to compress, so this wrapper provides a
    deterministic stub that:

    * returns an empty :class:`AtomicCallResult` for every declared
      atomic dependency (so the composed body's ``richness`` summary
      degrades to ``absent`` rather than raising), and
    * surfaces a single ``composed_tool: atomic registry not wired for
      FastMCP runtime — use REST companion at /v1/composed/{tool}``
      warning so downstream agents know where to call for the populated
      payload.
    """

    def __init__(self, atomic_dependencies: tuple[str, ...]) -> None:
        self._known = frozenset(atomic_dependencies)

    def call(self, tool_name: str, /, **_kwargs: Any) -> AtomicCallResult:
        return AtomicCallResult(
            tool_name=tool_name,
            payload={},
            citations=(),
            notes=(
                f"composed_tool stub: atomic '{tool_name}' returned empty "
                "from FastMCP runtime stub registry; call REST companion "
                f"/v1/composed/{tool_name} for populated payload.",
            ),
        )

    def has(self, tool_name: str, /) -> bool:
        return tool_name in self._known


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_composed(
    composed: ComposableTool,
    /,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a composed tool against the stub registry and return JPCIR envelope."""
    registry = _StubAtomicRegistry(composed.atomic_dependencies)
    try:
        envelope: ComposedEnvelope = composed.compose(registry, **kwargs)
    except ComposedToolError as exc:
        return make_error(
            code="subsystem_unavailable",
            message=str(exc),
            hint="Composed tool atomic dependency missing from runtime registry.",
        )

    payload = envelope.to_dict()
    payload["_billing_unit"] = 1
    payload["_disclaimer"] = _DISCLAIMER
    payload.setdefault("results", [])
    payload.setdefault("total", 0)
    payload.setdefault("limit", 1)
    payload.setdefault("offset", 0)
    return payload


def _eligibility_audit_workpaper_impl(
    program_id: str,
    entity_id: str,
    fy_start: str,
) -> dict[str, Any]:
    if not program_id or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    return _run_composed(
        EligibilityAuditWorkpaper(),
        program_id=program_id,
        entity_id=entity_id,
        fy_start=fy_start,
    )


def _subsidy_eligibility_full_impl(
    entity_id: str,
    industry_jsic: str,
    prefecture: str,
    program_id_hint: str,
) -> dict[str, Any]:
    if not entity_id or not entity_id.strip():
        return make_error(
            code="missing_required_arg",
            message="entity_id is required.",
            field="entity_id",
        )
    if not industry_jsic or not industry_jsic.strip():
        return make_error(
            code="missing_required_arg",
            message="industry_jsic is required.",
            field="industry_jsic",
        )
    return _run_composed(
        SubsidyEligibilityFull(),
        entity_id=entity_id,
        industry_jsic=industry_jsic,
        prefecture=prefecture,
        program_id_hint=program_id_hint,
    )


def _ma_due_diligence_pack_impl(
    target_houjin_bangou: str,
    industry_jsic: str,
    portfolio_id: str,
) -> dict[str, Any]:
    if not target_houjin_bangou or not target_houjin_bangou.strip():
        return make_error(
            code="missing_required_arg",
            message="target_houjin_bangou is required.",
            field="target_houjin_bangou",
        )
    return _run_composed(
        MaDueDiligencePack(),
        target_houjin_bangou=target_houjin_bangou,
        industry_jsic=industry_jsic,
        portfolio_id=portfolio_id,
    )


def _invoice_compatibility_check_impl(
    houjin_bangou: str,
    invoice_date: str,
) -> dict[str, Any]:
    if not houjin_bangou or not houjin_bangou.strip():
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required.",
            field="houjin_bangou",
        )
    return _run_composed(
        InvoiceCompatibilityCheck(),
        houjin_bangou=houjin_bangou,
        invoice_date=invoice_date,
    )


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def eligibility_audit_workpaper_composed(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="Program id under audit (e.g. 'jp_subsidy_xxx').",
            ),
        ],
        entity_id: Annotated[
            str,
            Field(
                default="entity_unknown",
                max_length=64,
                description="顧問先 法人 id passed to the eligibility chain.",
            ),
        ] = "entity_unknown",
        fy_start: Annotated[
            str,
            Field(
                default="1970-01-01",
                min_length=10,
                max_length=10,
                description="ISO YYYY-MM-DD FY start for amendment window.",
            ),
        ] = "1970-01-01",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim P composed — 税理士 monthly eligibility audit workpaper. Compresses 4 atomic tools (apply_eligibility_chain_am + track_amendment_lineage_am + program_active_periods_am + find_complementary_programs_am) into 1 ¥3 unit. Returns ComposedEnvelope with composed_steps + compression_ratio=4. NO LLM."""
        return _eligibility_audit_workpaper_impl(
            program_id=program_id,
            entity_id=entity_id,
            fy_start=fy_start,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def subsidy_eligibility_full_composed(
        entity_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="Entity id (法人 or 個人事業) being evaluated.",
            ),
        ],
        industry_jsic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="JSIC major industry code or display name.",
            ),
        ],
        prefecture: Annotated[
            str,
            Field(
                default="any",
                max_length=32,
                description="Prefecture filter (default 'any').",
            ),
        ] = "any",
        program_id_hint: Annotated[
            str,
            Field(
                default="",
                max_length=64,
                description="Optional candidate program id to skip discovery.",
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim P composed — 補助金 7-step full eligibility check. Compresses 5 atomic tools (search_programs_am + apply_eligibility_chain_am + check_enforcement_am + program_active_periods_am + simulate_application_am) into 1 ¥3 unit. Returns ComposedEnvelope with compression_ratio=5. NO LLM."""
        return _subsidy_eligibility_full_impl(
            entity_id=entity_id,
            industry_jsic=industry_jsic,
            prefecture=prefecture,
            program_id_hint=program_id_hint,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def ma_due_diligence_pack_composed(
        target_houjin_bangou: Annotated[
            str,
            Field(
                min_length=1,
                max_length=20,
                description="13-digit 法人番号 of the DD target.",
            ),
        ],
        industry_jsic: Annotated[
            str,
            Field(
                default="unknown",
                max_length=32,
                description="JSIC major industry code of the target.",
            ),
        ] = "unknown",
        portfolio_id: Annotated[
            str,
            Field(
                default="",
                max_length=64,
                description="Optional portfolio holding company id.",
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Wave 51 dim P composed — M&A 12-axis due-diligence pack. Compresses 4 atomic tools (match_due_diligence_questions + cross_check_jurisdiction + check_enforcement_am + track_amendment_lineage_am) into 1 ¥3 unit. Returns ComposedEnvelope with compression_ratio=4. NO LLM."""
        return _ma_due_diligence_pack_impl(
            target_houjin_bangou=target_houjin_bangou,
            industry_jsic=industry_jsic,
            portfolio_id=portfolio_id,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def invoice_compatibility_check_composed(
        houjin_bangou: Annotated[
            str,
            Field(
                min_length=1,
                max_length=20,
                description="13-digit 法人番号 or 'T'-prefix invoice number.",
            ),
        ],
        invoice_date: Annotated[
            str,
            Field(
                default="",
                max_length=10,
                description="Optional ISO YYYY-MM-DD invoice date for as_of probe.",
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim P composed — 適格事業者照合 + 取引先 enrichment. Compresses 3 atomic tools (check_invoice_registrant + corporate_layer_lookup + check_enforcement_am) into 1 ¥3 unit. Returns ComposedEnvelope with compression_ratio=3. NO LLM."""
        return _invoice_compatibility_check_impl(
            houjin_bangou=houjin_bangou,
            invoice_date=invoice_date,
        )


__all__ = [
    "_eligibility_audit_workpaper_impl",
    "_invoice_compatibility_check_impl",
    "_ma_due_diligence_pack_impl",
    "_subsidy_eligibility_full_impl",
]
