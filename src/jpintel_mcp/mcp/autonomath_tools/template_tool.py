"""MCP tool wrapper for the 36協定 template renderer.

Exposes ``render_36_kyotei_am`` (deterministic, zero LLM) and
``get_36_kyotei_metadata_am`` (lists required fields + aliases + license).
Backed by ``jpintel_mcp.templates.saburoku_kyotei``.

Gating
------
Both tools are gated behind ``settings.saburoku_kyotei_enabled``
(env: ``AUTONOMATH_36_KYOTEI_ENABLED``). 36協定 is a 労基法 §36 +
社労士法 regulated obligation — incorrect generation can expose the
operator to legal liability and brand damage. Default is False; the
operator must complete a legal review before flipping to True. When
disabled, the tools are NOT registered and absolutely disappear from
``mcp.list_tools()``. When enabled, the response still carries a
draft / 要法務確認 disclaimer (option B). See
``docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.templates.saburoku_kyotei import (
    TemplateError,
    get_required_fields,
    get_template_metadata,
    render_36_kyotei,
)

from jpintel_mcp.mcp._error_helpers import safe_internal_message

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.am.templates")

# Disclaimer attached to every render response (option B). Negation context
# ("保証しません") is INV-22-safe: the response_sanitizer affirmative regex
# set targets phrasings like 「保証します」, not 「保証しません」.
_DRAFT_DISCLAIMER = (
    "本テンプレートは draft です。労基署提出前に必ず社労士確認を行ってください。"
    "AutonoMath は generation accuracy について保証しません。"
)


if settings.saburoku_kyotei_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def render_36_kyotei_am(
        fields: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Required field map for the 36協定 template. Accepts canonical "
                    "keys (company_name / address / representative / industry / "
                    "employee_count / agreement_period_start / agreement_period_end / "
                    "max_overtime_hours_per_month / max_overtime_hours_per_year / "
                    "holiday_work_days_per_month) or any Japanese alias listed by "
                    "get_36_kyotei_metadata_am.required_fields."
                )
            ),
        ],
    ) -> dict[str, object]:
        """⚠️ DRAFT ONLY: 36協定 template — output MUST be reviewed by 社労士 before submission. 労基法 §36 + 社労士法 regulated.

        Render the 36協定 (時間外労働・休日労働協定届) template.

        Pure deterministic substitution — no LLM, no DB. All required fields
        must be present; unknown fields raise validation_error. Returned text
        is a DRAFT and MUST be reviewed by a 社労士 before submission to
        労基署 — see ``_disclaimer`` field in the response.
        """
        try:
            text = render_36_kyotei(fields)
            meta = get_template_metadata()
            return {
                "template_id": meta["template_id"],
                "obligation": meta["obligation"],
                "authority": meta["authority"],
                "license": meta["license"],
                "quality_grade": meta["quality_grade"],
                "method": meta["method"],
                "uses_llm": meta["uses_llm"],
                "rendered_text": text,
                "_disclaimer": _DRAFT_DISCLAIMER,
            }
        except TemplateError as exc:
            # TemplateError carries the field name the caller sent (no
            # internal leak). Add hint + retry_with so the LLM knows to
            # call get_36_kyotei_metadata_am for the canonical field
            # list before retrying.
            return make_error(
                "invalid_enum",
                str(exc),
                hint=(
                    "Call get_36_kyotei_metadata_am for the canonical "
                    "required_fields list (canonical names + accepted "
                    "Japanese aliases)."
                ),
                retry_with=["get_36_kyotei_metadata_am"],
            )
        except Exception as exc:
            msg, _ = safe_internal_message(exc, logger=logger, tool_name="render_36_kyotei_am")
            return make_error("internal", msg)

    @mcp.tool(annotations=_READ_ONLY)
    def get_36_kyotei_metadata_am() -> dict[str, object]:
        """⚠️ DRAFT template metadata — render output MUST be reviewed by 社労士 before submission. 労基法 §36 + 社労士法 regulated.

        Return template metadata: required fields, aliases, authority, license.
        """
        try:
            meta = get_template_metadata()
            return {
                "template_id": meta["template_id"],
                "obligation": meta["obligation"],
                "authority": meta["authority"],
                "license": meta["license"],
                "quality_grade": meta["quality_grade"],
                "method": meta["method"],
                "uses_llm": meta["uses_llm"],
                "required_fields": get_required_fields(),
                "_disclaimer": _DRAFT_DISCLAIMER,
            }
        except Exception as exc:
            msg, _ = safe_internal_message(
                exc, logger=logger, tool_name="get_36_kyotei_metadata_am"
            )
            return make_error("internal", msg)

else:
    logger.info(
        "saburoku_kyotei tools disabled (AUTONOMATH_36_KYOTEI_ENABLED=0). "
        "Operator must complete legal review before enabling."
    )
