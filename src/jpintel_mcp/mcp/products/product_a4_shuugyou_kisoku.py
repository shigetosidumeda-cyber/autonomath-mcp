"""A4 — 就業規則生成 Pack (Pricing V3: ¥30 Tier D workflow).

One MCP call assembles the canonical 4-artifact 社労士 bundle for a houjin
by composing four artifact templates via the upstream HE-2 lane (which
itself composes N1 template + N2 portfolio + N3 reasoning + N4 filing
window + N6 amendment alerts + N9 placeholder map):

  1. ``shuugyou_kisoku`` — 就業規則 (本則 + 賃金規程 + 退職金規程 stub).
  2. ``sanroku_kyoutei`` — 36 協定書 (時間外労働・休日労働協定届).
  3. ``koyou_keiyaku`` — 雇用契約書 (期間の定めなし labour contract).
  4. ``roudou_jouken`` — 労働条件通知書 (労基法 §15 mandated notice).

Output is a flat list of four scaffold artifacts plus an aggregate
summary. NO LLM — pure SQLite + dict composition. The 36協定 artifact is
gated by the same ``AUTONOMATH_36_KYOTEI_ENABLED`` flag the standalone
HE-2 surface uses.

Hard constraints
----------------

* §52 / §47条の2 / §72 / §1 / §3 + 社労士法 §27 disclaimer envelope on
  every response.
* Scaffold-only — every artifact requires 社労士 supervision before
  submission. 労基法 §89 / §36 / §15 obligations remain unchanged.
* Read-only SQLite (URI ``ro``).
* ``_BILLING_UNITS = 10`` so the host MCP server bills ``10 × ¥3 =
  ¥30`` (A4 V3 Tier D = workflow; V2 was 100 units / ¥300).

Tool
----

* ``product_shuugyou_kisoku_pack(houjin_bangou, employee_count_band,
  industry=None)`` — single bundle composition. ``industry`` defaults to
  the N7 segment view inference based on the houjin's JSIC major.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.moat_lane_tools.he2_workpaper import (
    prepare_implementation_workpaper,
)
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ..moat_lane_tools._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.products.a4_shuugyou_kisoku")

_PRODUCT_ID = "A4"
_SCHEMA_VERSION = "products.a4.v1"
_UPSTREAM_MODULE = "jpintel_mcp.mcp.products.product_a4_shuugyou_kisoku"
_SEGMENT = "社労士"

# A4 Pricing V3 — Agent-Economy First (2026-05-17). V2 used 100 units / ¥300;
# V3 collapses to 10 units / ¥30 (Tier D = workflow). Unit price stays ¥3.
_PRICING_VERSION = "v3"
_TIER_LETTER = "D"
_BILLING_UNITS = 10
_PRICE_PER_REQ_JPY = _BILLING_UNITS * 3
# value_proxy vs 3 model baseline (Sonnet 8-turn ¥30 parity / Opus ¥75 save 60%).
_VALUE_PROXY_OPUS_JPY = 75
_VALUE_PROXY_SONNET_JPY = 30
_VALUE_PROXY_HAIKU_JPY = 12

_ARTIFACT_TYPES: tuple[str, ...] = (
    "shuugyou_kisoku",
    "sanroku_kyoutei",
    "koyou_keiyaku",
    "roudou_jouken",
)
_ARTIFACT_NAMES_JA: dict[str, str] = {
    "shuugyou_kisoku": "就業規則",
    "sanroku_kyoutei": "36 協定書 (時間外労働・休日労働協定届)",
    "koyou_keiyaku": "雇用契約書",
    "roudou_jouken": "労働条件通知書",
}

_EMPLOYEE_COUNT_BANDS: tuple[str, ...] = (
    "1-4",
    "5-9",
    "10-29",
    "30-49",
    "50-99",
    "100-299",
    "300-999",
    "1000+",
)

_A4_DISCLAIMER_SUFFIX = (
    "本 pack は 労基法 §89 / §36 / §15 + 社労士法 §27 の業務範囲を含まず、"
    "scaffold-only の起案テンプレートに留まります。確定は 社労士 監修のうえ、"
    "労基署 / 労働局への提出は必ず 1 次資料を確認してください。"
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _lookup_industry_from_houjin(conn: sqlite3.Connection, houjin_bangou: str) -> str | None:
    if not _table_present(conn, "am_entity_facts"):
        return None
    try:
        row = conn.execute(
            """
            SELECT value_text
              FROM am_entity_facts
             WHERE entity_id = ?
               AND field_name = 'corp.jsic_major'
             LIMIT 1
            """,
            (f"houjin:{houjin_bangou}",),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or not row["value_text"]:
        return None
    jsic_major = str(row["value_text"]).strip().upper()
    if not jsic_major:
        return None
    if not _table_present(conn, "am_segment_view"):
        return jsic_major
    try:
        label_row = conn.execute(
            """
            SELECT jsic_name_ja
              FROM am_segment_view
             WHERE jsic_major = ?
             LIMIT 1
            """,
            (jsic_major,),
        ).fetchone()
    except sqlite3.OperationalError:
        return jsic_major
    if label_row is None or not label_row["jsic_name_ja"]:
        return jsic_major
    return str(label_row["jsic_name_ja"])


def _unwrap_tool(tool: Any) -> Any:
    """Unwrap an mcp.tool-decorated coroutine for direct call.

    FastMCP wraps the bare ``async def`` behind a Tool object that
    exposes the callable via ``.fn`` (newer FastMCP) / ``.func`` / ``._fn``
    depending on version. Mirrors the unwrap helper in
    ``tests/test_he2_workpaper.py``.
    """
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


async def _fan_out_artifacts(houjin_bangou: str, fiscal_year: int | None) -> list[dict[str, Any]]:
    impl = _unwrap_tool(prepare_implementation_workpaper)
    tasks = []
    for artifact_type in _ARTIFACT_TYPES:
        tasks.append(
            impl(
                artifact_type=artifact_type,
                houjin_bangou=houjin_bangou,
                segment=_SEGMENT,
                fiscal_year=fiscal_year,
                auto_fill_level="deep",
            )
        )
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return [dict(r) for r in results]


def _band_to_max_employees(band: str) -> int | None:
    if band == "1000+":
        return None
    if "-" not in band:
        return None
    try:
        return int(band.split("-")[1])
    except ValueError:
        return None


def _kisoku_obligation_label(band: str) -> str:
    upper = _band_to_max_employees(band)
    if upper is None or upper >= 10:
        return "labeling_required_kisoku_89"
    if upper >= 5:
        return "kisoku_proactive_recommendation"
    return "kisoku_optional"


def _strip_template_jsonb(template: dict[str, Any] | None) -> dict[str, Any] | None:
    if template is None:
        return None
    out = dict(template)
    out.pop("structure", None)
    out.pop("structure_jsonb", None)
    out.pop("placeholders", None)
    return out


def _compose_bundle(
    artifacts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bundle: list[dict[str, Any]] = []
    total_placeholders = 0
    total_resolved = 0
    completion_sum = 0.0
    completed_artifacts = 0
    statutory_fence: set[str] = set()
    for artifact_type, response in zip(_ARTIFACT_TYPES, artifacts, strict=True):
        provenance = response.get("provenance") or {}
        per_total = int(provenance.get("total_placeholders") or 0)
        per_resolved = int(provenance.get("resolved_placeholders") or 0)
        completion = float(response.get("estimated_completion_pct") or 0.0)
        total_placeholders += per_total
        total_resolved += per_resolved
        completion_sum += completion
        if response.get("primary_result", {}).get("status") == "ok":
            completed_artifacts += 1
        sensitive_act = (response.get("template") or {}).get("sensitive_act")
        if sensitive_act:
            statutory_fence.add(str(sensitive_act))
        bundle.append(
            {
                "artifact_type": artifact_type,
                "artifact_name_ja": _ARTIFACT_NAMES_JA[artifact_type],
                "status": response.get("primary_result", {}).get("status"),
                "is_skeleton": response.get("primary_result", {}).get("is_skeleton"),
                "estimated_completion_pct": completion,
                "template": _strip_template_jsonb(response.get("template")),
                "filled_sections": response.get("filled_sections") or [],
                "legal_basis": response.get("legal_basis") or {},
                "filing_window": response.get("filing_window") or {},
                "deadline": response.get("deadline"),
                "agent_next_actions": response.get("agent_next_actions") or [],
                "reasoning_chains": response.get("reasoning_chains") or [],
                "amendment_alerts_relevant": response.get("amendment_alerts_relevant") or [],
                "rationale": response.get("primary_result", {}).get("rationale"),
            }
        )
    avg_completion = round(completion_sum / max(1, len(artifacts)), 2)
    aggregate = {
        "artifact_count": len(bundle),
        "completed_artifact_count": completed_artifacts,
        "total_placeholders": total_placeholders,
        "resolved_placeholders": total_resolved,
        "average_completion_pct": avg_completion,
        "statutory_fence": sorted(statutory_fence),
    }
    return bundle, aggregate


def _agent_next_actions(
    bundle: list[dict[str, Any]],
    employee_count_band: str,
) -> list[dict[str, Any]]:
    obligation = _kisoku_obligation_label(employee_count_band)
    return [
        {
            "step": "fill manual_input across 4 artifacts",
            "items": [b["artifact_type"] for b in bundle],
            "rationale": (
                "Each artifact carries its own unresolved_placeholders / "
                "manual_input_required list under filled_sections[*]. "
                "Iterate and resolve before 社労士 review."
            ),
        },
        {
            "step": "verify 労基法 §89 obligation",
            "items": [obligation],
            "rationale": (
                "労基法 §89 mandates 就業規則 at ≥10 employees. Current "
                f"employee_count_band={employee_count_band!r} → status="
                f"{obligation}."
            ),
        },
        {
            "step": "engage 社労士",
            "items": ["sanroku_kyoutei", "shuugyou_kisoku"],
            "rationale": (
                "社労士法 §27 / 労基法 §36 — 36協定届 + 就業規則 提出は "
                "社労士 監修必須。労基署 / 労働局 への提出は scaffold-only "
                "outputs を 1 次資料で確認のうえ。"
            ),
        },
    ]


def _empty_envelope(
    *, primary_input: dict[str, Any], rationale: str, status: str = "empty"
) -> dict[str, Any]:
    return {
        "tool_name": "product_shuugyou_kisoku_pack",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "bundle": [],
        "aggregate": {
            "artifact_count": 0,
            "completed_artifact_count": 0,
            "total_placeholders": 0,
            "resolved_placeholders": 0,
            "average_completion_pct": 0.0,
            "statutory_fence": [],
        },
        "industry": primary_input.get("industry"),
        "employee_count_band": primary_input.get("employee_count_band"),
        "agent_next_actions": [],
        "billing": {
            "unit": _BILLING_UNITS,
            "yen": _BILLING_UNITS * 3,
            "product_id": _PRODUCT_ID,
            "tier": _TIER_LETTER,
            "pricing_version": _PRICING_VERSION,
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a4_shuugyou_kisoku",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N1", "N2", "N3", "N4", "N6", "N7", "N9"],
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": f"{DISCLAIMER}\n{_A4_DISCLAIMER_SUFFIX}",
        "_related_shihou": [_SEGMENT],
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N1", "N2", "N3", "N4", "N6", "N7", "N9"],
            "observed_at": today_iso_utc(),
        },
    }


@mcp.tool(annotations=_READ_ONLY)
async def product_shuugyou_kisoku_pack(
    houjin_bangou: Annotated[
        str,
        Field(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 (houjin_bangou).",
        ),
    ],
    employee_count_band: Annotated[
        str,
        Field(
            description=(
                "Employee count band (one of 1-4 / 5-9 / 10-29 / 30-49 / "
                "50-99 / 100-299 / 300-999 / 1000+). Drives 労基法 §89 "
                "obligation surfacing + 36協定 cap selection."
            ),
        ),
    ] = "10-29",
    industry: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional industry label override (e.g. '建設業' / '製造業'). "
                "When omitted the value is inferred from N7 segment view via "
                "the houjin's JSIC major fact."
            ),
        ),
    ] = None,
    fiscal_year: Annotated[
        int | None,
        Field(
            default=None,
            ge=2000,
            le=2100,
            description=(
                "Optional fiscal year (e.g. 2026). Forwarded to HE-2 for "
                "deadline projection on 36協定 (1y starting 4/1)."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1/§3/社労士法 §27] A4 - 就業規則生成 Pack.

    Composes the canonical 4-artifact 社労士 bundle:
    就業規則 + 36 協定書 + 雇用契約書 + 労働条件通知書. Each artifact is
    HE-2-composed (N1 template + N2 portfolio + N3 reasoning + N4 filing
    window + N6 amendment alerts + N9 placeholder map) and returned in
    scaffold-only form. Industry defaults to N7 segment view inference.

    Output is scaffold-only — 労基署 / 労働局 への提出 / 社労士 監修 are
    out of scope; 1 billable call counts as 10 units (10 × ¥3 = ¥30, Tier D under Pricing V3).
    NO LLM inference — pure SQLite + dict composition.
    """
    primary_input = {
        "houjin_bangou": houjin_bangou,
        "employee_count_band": employee_count_band,
        "industry": industry,
        "fiscal_year": fiscal_year,
    }

    if employee_count_band not in _EMPLOYEE_COUNT_BANDS:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=(
                f"employee_count_band={employee_count_band!r} not in {list(_EMPLOYEE_COUNT_BANDS)}."
            ),
            status="invalid_argument",
        )

    resolved_industry = industry
    if resolved_industry is None:
        conn = _open_ro()
        if conn is not None:
            try:
                inferred = _lookup_industry_from_houjin(conn, houjin_bangou)
            finally:
                conn.close()
            if inferred:
                resolved_industry = inferred
    if resolved_industry is None:
        resolved_industry = "汎用 (industry 不明)"

    try:
        artifacts = await _fan_out_artifacts(houjin_bangou, fiscal_year)
    except Exception as exc:  # pragma: no cover — defensive net for HE-2 fan-out
        logger.exception("A4 HE-2 fan-out failed")
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"HE-2 fan-out failed: {exc}",
            status="he2_failure",
        )

    bundle, aggregate = _compose_bundle(artifacts)
    next_actions = _agent_next_actions(bundle, employee_count_band)
    obligation = _kisoku_obligation_label(employee_count_band)

    return {
        "tool_name": "product_shuugyou_kisoku_pack",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "houjin_bangou": houjin_bangou,
            "industry_resolved": resolved_industry,
            "employee_count_band": employee_count_band,
            "obligation_label": obligation,
            "summary": {
                "artifact_count": aggregate["artifact_count"],
                "completed_artifact_count": aggregate["completed_artifact_count"],
                "average_completion_pct": aggregate["average_completion_pct"],
                "total_placeholders": aggregate["total_placeholders"],
                "resolved_placeholders": aggregate["resolved_placeholders"],
            },
        },
        "bundle": bundle,
        "aggregate": aggregate,
        "industry": resolved_industry,
        "employee_count_band": employee_count_band,
        "agent_next_actions": next_actions,
        "billing": {
            "unit": _BILLING_UNITS,
            "yen": _BILLING_UNITS * 3,
            "product_id": _PRODUCT_ID,
            "tier": _TIER_LETTER,
            "pricing_version": _PRICING_VERSION,
        },
        "results": bundle,
        "total": len(bundle),
        "limit": len(bundle),
        "offset": 0,
        "citations": [
            cit for b in bundle for cit in (b.get("legal_basis", {}).get("law_articles") or [])[:2]
        ][:10],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a4_shuugyou_kisoku",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N1", "N2", "N3", "N4", "N6", "N7", "N9"],
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": f"{DISCLAIMER}\n{_A4_DISCLAIMER_SUFFIX}",
        "_related_shihou": [_SEGMENT],
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N1", "N2", "N3", "N4", "N6", "N7", "N9"],
            "observed_at": today_iso_utc(),
        },
    }


__all__ = ["product_shuugyou_kisoku_pack"]
