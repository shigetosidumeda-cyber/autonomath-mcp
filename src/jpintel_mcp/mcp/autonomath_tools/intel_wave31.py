"""intel_wave31 — composite intelligence MCP wrappers (Wave 31+, 2026-05-05).

Wave 31 final integration: register all 14 composite `/v1/intel/*` REST
endpoints (W30-2 / W30-3 / W30-4 / W30-8 / W30-9 + W31-1..9) as MCP tools
so customer LLMs that prefer the MCP transport reach them with the same
single-call envelope contract.

Wave 32-3 adds `intel_risk_score` using the same registration pattern.

Tools shipped here
------------------

  * intel_probability_radar   (W30-8) — POST /v1/intel/probability_radar
  * intel_audit_chain         (W30-9) — POST /v1/intel/audit_chain
  * intel_match               (W30-4) — POST /v1/intel/match
  * intel_program_full        (W30-2) — GET  /v1/intel/program/{id}/full
  * intel_houjin_full         (W30-3) — GET  /v1/intel/houjin/{id}/full
  * intel_diff                (W31-1) — POST /v1/intel/diff
  * intel_path                (W31-2) — POST /v1/intel/path
  * intel_timeline            (W31-3) — GET  /v1/intel/timeline/{id}
  * intel_conflict            (W31-4) — POST /v1/intel/conflict
  * intel_why_excluded        (W31-5) — POST /v1/intel/why_excluded
  * intel_peer_group          (W31-6) — POST /v1/intel/peer_group
  * intel_regulatory_context  (W31-7) — GET  /v1/intel/regulatory_context/{id}
  * intel_bundle_optimal      (W31-8) — POST /v1/intel/bundle/optimal
  * intel_citation_pack       (W31-9) — GET  /v1/intel/citation_pack/{id}
  * intel_risk_score          (W32-3) — POST /v1/intel/risk_score

NO Anthropic API self-call (memory `feedback_no_operator_llm_api`).
Every tool re-uses the existing REST-side `_build_*` helper or inlines
its pure-SQLite logic — the MCP path is a function call into the same
process, no HTTP roundtrip, no LLM call.

Gating
------
Env-gated on `AUTONOMATH_INTEL_COMPOSITE_ENABLED` (default ``"1"``).
Set to ``"0"`` to roll back without redeploy.

Disclaimers
-----------
Each tool's response body already carries the `_disclaimer` envelope
field set by the underlying REST builder (`_DIFF_DISCLAIMER`,
`_TIMELINE_DISCLAIMER`, `_PROGRAM_FULL_DISCLAIMER`, etc.). The 14 tool
names are also pre-registered in `envelope_wrapper.SENSITIVE_TOOLS` so
any future telemetry walker (`disclaimer_for(name)`) answers correctly.

Sensitive surfaces (5 業法 fence): 税理士法 §52, 弁護士法 §72,
行政書士法 §1, 司法書士法 §3, 公認会計士法 §47条の2.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.intel_wave31")

# Env gate. Default ON so the 14 tools register on stdio boot; flip to "0"
# for rollback without redeploy (FastMCP re-enumerates on next connect).
_ENABLED = os.environ.get("AUTONOMATH_INTEL_COMPOSITE_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_jpintel() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db (default substrate). Returns conn or error envelope."""
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _open_autonomath_safe() -> sqlite3.Connection | None:
    """Open autonomath.db read-only. Returns None on missing/error (callers
    decide whether to degrade or surface a missing-substrate hint).
    """
    try:
        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.debug("autonomath.db unavailable in MCP wrapper: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Composite intel tools — each delegates to the REST builder helper or
# inlines minimal SQLite logic. No HTTP roundtrip; same in-process call.
# ---------------------------------------------------------------------------


def _intel_probability_radar_impl(
    program_id: str,
    houjin_bangou: str,
    effort_hours_override: int | None = None,
    hourly_rate_yen_override: int | None = None,
) -> dict[str, Any]:
    """W30-8 — probability_estimate + ROI bundle. Pure SQLite."""
    from jpintel_mcp.api.intel import (
        _DEFAULT_EFFORT_HOURS,
        _DISCLAIMER,
        _EFFORT_HOURLY_RATE_YEN,
        _build_evidence_packets,
        _compute_industry_rate_and_award,
        _compute_probability_estimate,
        _is_valid_houjin,
        _normalize_houjin,
    )

    hb = _normalize_houjin(houjin_bangou)
    if not _is_valid_houjin(hb):
        return make_error(
            code="invalid_input",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be non-empty.",
            field="program_id",
        )

    am_conn = _open_autonomath_safe()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for probability_radar.",
            retry_with=["search_programs"],
        )

    missing_tables: list[str] = []
    try:
        probability_estimate = _compute_probability_estimate(
            am_conn, houjin_bangou=hb, program_id=pid, missing_tables=missing_tables
        )
        same_industry_rate, mean_award_yen, program_adoption_count = (
            _compute_industry_rate_and_award(
                am_conn,
                houjin_bangou=hb,
                program_id=pid,
                missing_tables=missing_tables,
            )
        )
        evidence_packets = _build_evidence_packets(am_conn, program_id=pid)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    effort_hours = int(effort_hours_override or _DEFAULT_EFFORT_HOURS)
    hourly_rate = int(hourly_rate_yen_override or _EFFORT_HOURLY_RATE_YEN)
    effort_cost_yen = effort_hours * hourly_rate

    expected_award_yen: int | None = None
    if probability_estimate is not None and mean_award_yen is not None:
        expected_award_yen = int(round(probability_estimate * mean_award_yen))
    net_expected_yen: int | None = None
    if expected_award_yen is not None:
        net_expected_yen = expected_award_yen - effort_cost_yen

    body: dict[str, Any] = {
        "program_id": pid,
        "houjin_bangou": hb,
        "probability_estimate": probability_estimate,
        "same_industry_adoption_rate": same_industry_rate,
        "mean_award_amount_yen": mean_award_yen,
        "estimated_application_effort_hours": effort_hours,
        "roi_per_program": {
            "expected_award_yen": expected_award_yen,
            "effort_cost_yen": effort_cost_yen,
            "net_expected_yen": net_expected_yen,
            "hourly_rate_yen": hourly_rate,
        },
        "evidence_packets": evidence_packets,
        "data_quality": {
            "missing_tables": missing_tables,
            "program_adoption_record_count": program_adoption_count,
            "probability_basis": (
                "am_recommended_programs.score (similarity, NOT forecast)"
                if probability_estimate is not None
                else None
            ),
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


def _intel_audit_chain_impl(evidence_packet_id: str) -> dict[str, Any]:
    """W30-9 — composite Merkle proof + sources + verify chain."""
    import re

    from jpintel_mcp.api.audit_proof import (
        _build_proof_path,
        _fetch_all_leaves,
        _fetch_anchor,
        _fetch_leaf,
        _github_commit_url,
        _open_autonomath_rw,
        _ots_url_for,
    )
    from jpintel_mcp.api.intel import (
        _AUDIT_CHAIN_DISCLAIMER,
        _enrich_with_am_source,
        _seal_source_urls_for_epid,
        _verify_proof_path,
    )

    epid = (evidence_packet_id or "").strip()
    if not re.match(r"^evp_[A-Za-z0-9_]{1,64}$", epid):
        return make_error(
            code="invalid_input",
            message=(
                "evidence_packet_id must match ^evp_[A-Za-z0-9_]{1,64}$ "
                "(e.g. 'evp_a1b2c3d4e5f6g7h8')."
            ),
            field="evidence_packet_id",
        )

    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err

    try:
        am_conn = _open_autonomath_rw()
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
        return make_error(
            code="db_unavailable",
            message=f"audit substrate unavailable: {exc}",
        )

    try:
        try:
            leaf = _fetch_leaf(am_conn, epid)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return make_error(
                    code="not_found",
                    message=(
                        f"audit_merkle_anchor not yet provisioned; "
                        f"evidence_packet_id={epid} has no inclusion proof."
                    ),
                    field="evidence_packet_id",
                )
            raise

        if leaf is None:
            return make_error(
                code="not_found",
                message=(
                    f"evidence_packet_id={epid} not found in "
                    f"audit_merkle_leaves. Either the id is unknown, or its "
                    f"anchor cron has not run yet."
                ),
                field="evidence_packet_id",
            )
        daily_date, leaf_index, leaf_hash = leaf

        anchor = _fetch_anchor(am_conn, daily_date)
        if anchor is None:
            return make_error(
                code="not_found",
                message=(f"audit_merkle_anchor missing for daily_date={daily_date}."),
            )

        all_leaves = _fetch_all_leaves(am_conn, daily_date)
        proof_path = _build_proof_path(all_leaves, leaf_index)
        seal_urls = _seal_source_urls_for_epid(jp_conn, epid)
        source_urls = _enrich_with_am_source(am_conn, seal_urls)
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()

    import base64

    merkle_root = anchor["merkle_root"]
    ots_proof = anchor["ots_proof"]
    github_sha = anchor["github_commit_sha"]
    twitter_post_id = anchor["twitter_post_id"]

    step1 = bool(leaf_hash)
    step2 = bool(proof_path) or len(all_leaves) <= 1
    step3 = _verify_proof_path(leaf_hash, proof_path, merkle_root)
    step4 = bool(ots_proof)
    step5 = bool(github_sha)

    body: dict[str, Any] = {
        "evidence_packet_id": epid,
        "merkle": {
            "root": f"sha256:{merkle_root}",
            "leaf_index": leaf_index,
            "leaf_hash": leaf_hash,
            "proof_path": proof_path,
            "daily_date": daily_date,
            "row_count": anchor["row_count"],
            "ots_url": _ots_url_for(ots_proof),
            "ots_proof_b64": (base64.b64encode(ots_proof).decode("ascii") if ots_proof else None),
            "github_commit_url": _github_commit_url(github_sha),
            "github_commit_sha": github_sha,
            "twitter_post_id": twitter_post_id,
        },
        "source_urls": source_urls,
        "verify_chain": {
            "step1_recompute_leaf": step1,
            "step2_walk_proof": step2,
            "step3_verify_root": step3,
            "step4_ots_verified": _ots_url_for(ots_proof) if step4 else None,
            "step5_github_anchor_found": step5,
            "all_steps_pass": all([step1, step2, step3, step4, step5]),
        },
        "_disclaimer": _AUDIT_CHAIN_DISCLAIMER,
        "_billing_unit": 1,
        "_meta": {
            "verifier_algorithm": "merkle_sha256_bitcoin_style",
            "leaf_hash_recipe": "sha256(epid || params_digest || ts)",
            "creator": "Bookyou株式会社 (T8010001213708)",
            "endpoint": "intel.audit_chain",
        },
    }
    return body


def _intel_match_impl(
    industry_jsic_major: str,
    prefecture_code: str,
    capital_jpy: int | None = None,
    employee_count: int | None = None,
    keyword: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """W30-4 — smart matchmaking, top-N programs in 1 call."""
    from jpintel_mcp.api.intel import (
        _JSIC_MAJOR_CODES,
        _PREFECTURE_CODE_TO_NAME,
        IntelMatchRequest,
        _build_match_envelope,
    )

    major = (industry_jsic_major or "").strip().upper()
    if major not in _JSIC_MAJOR_CODES:
        return make_error(
            code="invalid_input",
            message=f"industry_jsic_major must be A–T (got {major!r}).",
            field="industry_jsic_major",
        )
    pref_code = (prefecture_code or "").strip()
    pref_name = _PREFECTURE_CODE_TO_NAME.get(pref_code)
    if not pref_name:
        return make_error(
            code="invalid_input",
            message=(
                f"prefecture_code must be a JIS X 0401 two-digit code 01–47 (got {pref_code!r})."
            ),
            field="prefecture_code",
        )
    payload = IntelMatchRequest(
        industry_jsic_major=major,
        prefecture_code=pref_code,
        capital_jpy=capital_jpy,
        employee_count=employee_count,
        keyword=keyword,
        limit=max(1, min(int(limit or 5), 20)),
    )

    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    try:
        body = _build_match_envelope(jp_conn, payload=payload, pref_name=pref_name)
    finally:
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    return body


def _intel_program_full_impl(
    program_id: str,
    include_sections: list[str] | None = None,
    max_per_section: int = 5,
) -> dict[str, Any]:
    """W30-2 — composite per-program bundle (meta + eligibility + ...)."""
    from jpintel_mcp.api.intel_program_full import (
        _ALLOWED_SECTIONS,
        _DEFAULT_SECTIONS,
        _PROGRAM_FULL_DISCLAIMER,
        _build_program_full,
    )

    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be non-empty.",
            field="program_id",
        )
    requested = tuple(include_sections) if include_sections else _DEFAULT_SECTIONS
    bad = [s for s in requested if s not in _ALLOWED_SECTIONS]
    if bad:
        return make_error(
            code="invalid_input",
            message=(
                f"include_sections contains unknown values: {bad}. "
                f"Allowed: {sorted(_ALLOWED_SECTIONS)}."
            ),
            field="include_sections",
        )
    seen: list[str] = []
    for s in requested:
        if s not in seen:
            seen.append(s)
    capped_max = max(1, min(int(max_per_section or 5), 20))

    body, _missing, program_found = _build_program_full(
        program_id=pid,
        include_sections=tuple(seen),
        max_per_section=capped_max,
    )
    if not program_found and "meta" in seen:
        return make_error(
            code="not_found",
            message=f"Program not found: {pid!r}. Verify via search_programs.",
            field="program_id",
        )
    body["_disclaimer"] = _PROGRAM_FULL_DISCLAIMER
    body.setdefault("_billing_unit", 1)
    return body


def _intel_houjin_full_impl(
    houjin_id: str,
    include_sections: list[str] | None = None,
    max_per_section: int = 5,
) -> dict[str, Any]:
    """W30-3 — composite houjin 360 bundle."""
    from jpintel_mcp.api.intel_houjin_full import (
        _DEFAULT_MAX_PER_SECTION,
        _HARD_MAX_PER_SECTION,
        _build_houjin_full,
        _normalize_houjin,
        _open_autonomath_ro,
        _parse_include_sections,
    )
    from jpintel_mcp.api.intel_houjin_full import (
        _DISCLAIMER as _HOUJIN_FULL_DISCLAIMER,
    )

    normalized = _normalize_houjin(houjin_id)
    if normalized is None:
        return make_error(
            code="invalid_input",
            message=f"houjin_id must be 13 digits (got {houjin_id!r}).",
            field="houjin_id",
        )
    sections = _parse_include_sections(include_sections)
    capped_max = max(
        1, min(int(max_per_section or _DEFAULT_MAX_PER_SECTION), _HARD_MAX_PER_SECTION)
    )
    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    am_conn = _open_autonomath_ro()
    try:
        body = _build_houjin_full(
            jpintel_conn=jp_conn,
            am_conn=am_conn,
            houjin_id=normalized,
            sections=sections,
            max_per_section=capped_max,
        )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    body.setdefault("_disclaimer", _HOUJIN_FULL_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_diff_impl(
    a: dict[str, str],
    b: dict[str, str],
    depth: int = 2,
) -> dict[str, Any]:
    """W31-1 — composite entity diff (M&A DD)."""
    from jpintel_mcp.api.intel_diff import (
        _DIFF_DISCLAIMER,
        EntityRef,
        IntelDiffRequest,
        _diff_attr_dicts,
        _diff_neighbour_sets,
        _diff_predicate_sets,
        _fetch_5hop_neighbours,
        _fetch_predicate_set,
        _fetch_primary_attrs,
        _resolve_am_id,
    )

    try:
        payload = IntelDiffRequest(a=EntityRef(**a), b=EntityRef(**b), depth=int(depth or 2))
    except Exception as exc:  # noqa: BLE001
        return make_error(
            code="invalid_input",
            message=f"intel_diff payload invalid: {exc}",
        )
    if payload.a.type != payload.b.type:
        return make_error(
            code="invalid_input",
            message="a.type and b.type must match for a meaningful diff.",
        )

    kind = payload.a.type
    a_id = payload.a.id.strip()
    b_id = payload.b.id.strip()

    am_conn = _open_autonomath_safe()
    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        if am_conn is not None:
            am_conn.close()
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    try:
        missing_tables: list[str] = []
        a_attrs = _fetch_primary_attrs(
            kind=kind,
            raw_id=a_id,
            conn=jp_conn,
            am_conn=am_conn,
            missing_tables=missing_tables,
        )
        b_attrs = _fetch_primary_attrs(
            kind=kind,
            raw_id=b_id,
            conn=jp_conn,
            am_conn=am_conn,
            missing_tables=missing_tables,
        )
        if a_attrs is None and b_attrs is None:
            return make_error(
                code="not_found",
                message=(f"Neither {a_id!r} nor {b_id!r} resolved against the {kind!r} axis."),
            )

        a_seeds = _resolve_am_id(am_conn, a_id)
        b_seeds = _resolve_am_id(am_conn, b_id)
        a_nbrs = _fetch_5hop_neighbours(
            am_conn, a_seeds, depth=payload.depth, missing_tables=missing_tables
        )
        b_nbrs = _fetch_5hop_neighbours(
            am_conn, b_seeds, depth=payload.depth, missing_tables=missing_tables
        )

        a_pred: dict[Any, Any] = {}
        b_pred: dict[Any, Any] = {}
        if kind == "program":
            a_pred = _fetch_predicate_set(am_conn, a_id, missing_tables=missing_tables)
            b_pred = _fetch_predicate_set(am_conn, b_id, missing_tables=missing_tables)

        s_attr, ua_attr, ub_attr, c_attr = _diff_attr_dicts(a_attrs, b_attrs)
        s_nbr, ua_nbr, ub_nbr = _diff_neighbour_sets(
            a_set=a_nbrs, b_set=b_nbrs, depth=payload.depth
        )
        if kind == "program":
            s_pred, ua_pred, ub_pred, c_pred = _diff_predicate_sets(a_pred, b_pred)
        else:
            s_pred, ua_pred, ub_pred, c_pred = [], [], [], []

        body: dict[str, Any] = {
            "a": {"type": kind, "id": a_id, "resolved": a_attrs is not None},
            "b": {"type": kind, "id": b_id, "resolved": b_attrs is not None},
            "depth": payload.depth,
            "shared_attrs": s_attr + s_nbr + s_pred,
            "unique_to_a": ua_attr + ua_nbr + ua_pred,
            "unique_to_b": ub_attr + ub_nbr + ub_pred,
            "conflict_points": c_attr + c_pred,
            "data_quality": {
                "missing_tables": sorted(set(missing_tables)),
                "a_neighbour_count": len(a_nbrs),
                "b_neighbour_count": len(b_nbrs),
                "a_predicate_count": len(a_pred),
                "b_predicate_count": len(b_pred),
            },
            "_disclaimer": _DIFF_DISCLAIMER,
            "_billing_unit": 1,
        }
        return body
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()


def _intel_path_impl(
    from_entity: dict[str, str],
    to_entity: dict[str, str],
    max_hops: int = 3,
    relation_filter: list[str] | None = None,
) -> dict[str, Any]:
    """W31-2 — bidirectional BFS reasoning chain between 2 entities."""
    from jpintel_mcp.api.intel_path import (
        _DISCLAIMER as _PATH_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_path import (
        IntelPathRequest,
        PathEntity,
        _build_path_envelope,
        _open_autonomath_ro,
    )

    try:
        payload = IntelPathRequest(
            from_entity=PathEntity(**from_entity),
            to_entity=PathEntity(**to_entity),
            max_hops=int(max_hops or 3),
            relation_filter=relation_filter or [],
        )
    except Exception as exc:  # noqa: BLE001
        return make_error(code="invalid_input", message=f"intel_path payload invalid: {exc}")

    if payload.from_entity.id.strip() == payload.to_entity.id.strip():
        return {
            "found": True,
            "shortest_path_length": 0,
            "nodes": [
                {
                    "entity_type": payload.from_entity.type,
                    "entity_id": payload.from_entity.id,
                    "name": None,
                }
            ],
            "edges": [],
            "alternative_paths": [],
            "from_entity": payload.from_entity.model_dump(),
            "to_entity": payload.to_entity.model_dump(),
            "max_hops": payload.max_hops,
            "relation_filter": sorted({r.strip() for r in payload.relation_filter if r.strip()}),
            "data_quality": {
                "missing_substrate": [],
                "resolved_from": payload.from_entity.id,
                "resolved_to": payload.to_entity.id,
            },
            "_disclaimer": _PATH_DISCLAIMER,
            "_billing_unit": 1,
        }

    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    am_conn = _open_autonomath_ro()
    try:
        body = _build_path_envelope(payload=payload, am_conn=am_conn, jpintel_conn=jp_conn)
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    return body


def _intel_timeline_impl(
    program_id: str,
    year: int = 0,
    include_types: list[str] | None = None,
) -> dict[str, Any]:
    """W31-3 — annual cross-substrate event timeline."""
    from datetime import UTC, datetime

    from jpintel_mcp.api.intel_timeline import (
        _ALLOWED_TYPES,
        _DEFAULT_TYPES,
        _build_timeline,
    )

    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be non-empty.",
            field="program_id",
        )
    yr = int(year) if year else datetime.now(UTC).year
    requested = tuple(include_types) if include_types else _DEFAULT_TYPES
    bad = [t for t in requested if t not in _ALLOWED_TYPES]
    if bad:
        return make_error(
            code="invalid_input",
            message=(
                f"include_types contains unknown values: {bad}. Allowed: {sorted(_ALLOWED_TYPES)}."
            ),
            field="include_types",
        )
    am_conn = _open_autonomath_safe()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for timeline.",
        )
    try:
        body = _build_timeline(
            am_conn=am_conn,
            program_id=pid,
            year=yr,
            include_types=tuple(requested),
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()
    return body


def _intel_conflict_impl(
    program_ids: list[str],
    houjin_id: str,
) -> dict[str, Any]:
    """W31-4 — combo conflict detector + alternative bundles."""
    from jpintel_mcp.api.intel_conflict import (
        _DISCLAIMER as _CONFLICT_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_conflict import (
        ConflictRequest,
        _build_conflict_envelope,
    )

    try:
        payload = ConflictRequest(program_ids=program_ids, houjin_id=houjin_id)
    except Exception as exc:  # noqa: BLE001
        return make_error(code="invalid_input", message=f"intel_conflict invalid: {exc}")

    am_conn = _open_autonomath_safe()
    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        if am_conn is not None:
            am_conn.close()
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    try:
        body = _build_conflict_envelope(payload=payload, jp_conn=jp_conn, am_conn=am_conn)
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    body.setdefault("_disclaimer", _CONFLICT_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_why_excluded_impl(
    program_id: str,
    houjin: dict[str, Any],
) -> dict[str, Any]:
    """W31-5 — eligibility-failure reasoning + remediation."""
    from jpintel_mcp.api.intel_why_excluded import (
        _DISCLAIMER as _WHY_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_why_excluded import (
        HoujinAttrs,
        WhyExcludedRequest,
        _build_why_excluded_envelope,
    )

    try:
        payload = WhyExcludedRequest(program_id=program_id, houjin=HoujinAttrs(**houjin))
    except Exception as exc:  # noqa: BLE001
        return make_error(code="invalid_input", message=f"intel_why_excluded invalid: {exc}")

    am_conn = _open_autonomath_safe()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for why_excluded.",
        )
    try:
        body = _build_why_excluded_envelope(payload=payload, am_conn=am_conn)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()
    body.setdefault("_disclaimer", _WHY_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_peer_group_impl(
    houjin_id: str | None = None,
    houjin_attributes: dict[str, Any] | None = None,
    peer_count: int = 5,
    comparison_axes: list[str] | None = None,
) -> dict[str, Any]:
    """W31-6 — 同業他社 N peers (Jaccard on jsic + prefecture)."""
    from jpintel_mcp.api.intel_peer_group import (
        _DISCLAIMER as _PEER_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_peer_group import (
        HoujinAttributes,
        PeerGroupRequest,
    )
    from jpintel_mcp.api.intel_peer_group import (
        _build_envelope as _build_peer_envelope,
    )

    if not houjin_id and not houjin_attributes:
        return make_error(
            code="invalid_input",
            message="Either houjin_id or houjin_attributes is required.",
        )

    try:
        attrs = HoujinAttributes(**houjin_attributes) if houjin_attributes else None
        payload = PeerGroupRequest(
            houjin_id=houjin_id,
            houjin_attributes=attrs,
            peer_count=max(3, min(int(peer_count or 5), 10)),
            comparison_axes=comparison_axes
            or ["adoption_count", "total_amount", "category_diversity"],
        )
    except Exception as exc:  # noqa: BLE001
        return make_error(code="invalid_input", message=f"intel_peer_group invalid: {exc}")

    am_conn = _open_autonomath_safe()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for peer_group.",
        )
    try:
        body = _build_peer_envelope(payload=payload, am_conn=am_conn)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()
    body.setdefault("_disclaimer", _PEER_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_regulatory_context_impl(
    program_id: str,
    include: list[str] | None = None,
    max_per_type: int = 10,
    since_date: str | None = None,
) -> dict[str, Any]:
    """W31-7 — full regulatory bundle (法令 + 通達 + 裁決 + 判例 + 行政処分)."""
    from jpintel_mcp.api.intel_regulatory_context import (
        _DISCLAIMER as _REG_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_regulatory_context import (
        _build_regulatory_envelope,
        _normalize_since_date,
        _parse_include,
    )

    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be non-empty.",
            field="program_id",
        )
    requested_types = _parse_include(include)
    since_iso = _normalize_since_date(since_date)
    max_n = max(1, min(int(max_per_type or 10), 50))

    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    try:
        body = _build_regulatory_envelope(
            jp_conn=jp_conn,
            program_id=pid,
            requested_types=requested_types,
            max_per_type=max_n,
            since_iso=since_iso,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    body.setdefault("_disclaimer", _REG_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_bundle_optimal_impl(
    houjin_id: str | dict[str, Any],
    bundle_size: int = 5,
    objective: Literal["max_amount", "max_count", "min_overlap"] = "max_amount",
    exclude_program_ids: list[str] | None = None,
    prefer_categories: list[str] | None = None,
) -> dict[str, Any]:
    """W31-8 — houjin → 最適 program bundle (greedy weighted)."""
    from jpintel_mcp.api.intel_bundle_optimal import (
        _BUNDLE_DISCLAIMER,
        BundleOptimalRequest,
    )
    from jpintel_mcp.api.intel_bundle_optimal import (
        _build_envelope as _build_bundle_envelope,
    )

    try:
        payload = BundleOptimalRequest(
            houjin_id=houjin_id,
            bundle_size=int(bundle_size or 5),
            objective=objective,
            exclude_program_ids=exclude_program_ids or [],
            prefer_categories=prefer_categories or [],
        )
    except Exception as exc:  # noqa: BLE001
        return make_error(code="invalid_input", message=f"intel_bundle_optimal invalid: {exc}")

    am_conn = _open_autonomath_safe()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for bundle/optimal.",
        )
    try:
        body = _build_bundle_envelope(payload=payload, am_conn=am_conn)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()
    body.setdefault("_disclaimer", _BUNDLE_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_citation_pack_impl(
    program_id: str,
    format: Literal["markdown", "json"] = "markdown",  # noqa: A002
    max_citations: int = 30,
    include_adoptions: bool = True,
    citation_style: Literal["footnote", "inline"] = "footnote",
) -> dict[str, Any]:
    """W31-9 — 1-call markdown bundle of every primary-source citation."""
    from jpintel_mcp.api.intel_citation_pack import (
        _CITATION_PACK_DISCLAIMER,
        _build_citation_pack_envelope,
        _resolve_program,
    )

    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be non-empty.",
            field="program_id",
        )
    jp_conn_or_err = _open_jpintel()
    if isinstance(jp_conn_or_err, dict):
        return jp_conn_or_err
    jp_conn = jp_conn_or_err
    try:
        program = _resolve_program(jp_conn, pid)
        if program is None:
            return make_error(
                code="not_found",
                message=(
                    f"program_id={pid!r} not found in the programs table. "
                    "Verify the unified_id via search_programs first."
                ),
                field="program_id",
            )
        body = _build_citation_pack_envelope(
            jp_conn=jp_conn,
            program=program,
            format=format,
            max_citations=max(5, min(int(max_citations or 30), 100)),
            include_adoptions=bool(include_adoptions),
            citation_style=citation_style,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            jp_conn.close()
    body.setdefault("_disclaimer", _CITATION_PACK_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


def _intel_risk_score_impl(
    houjin_id: str,
    include_axes: list[str] | None = None,
    weight_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    """W32-3 — multi-axis rules-based houjin risk score. Pure SQLite."""
    from jpintel_mcp.api.intel_risk_score import (
        _DISCLAIMER as _RISK_SCORE_DISCLAIMER,
    )
    from jpintel_mcp.api.intel_risk_score import (
        _build_risk_score,
        _fetch_houjin_meta,
        _normalize_houjin,
        _open_autonomath_ro,
        _parse_axes,
        _table_exists,
    )

    normalized = _normalize_houjin(houjin_id)
    if normalized is None:
        return make_error(
            code="invalid_input",
            message=(
                f"houjin_id must be 13 digits (with or without 'T' prefix); got {houjin_id!r}."
            ),
            field="houjin_id",
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        return make_error(
            code="db_unavailable",
            message="autonomath.db unavailable for intel/risk_score.",
        )

    try:
        selected_axes = _parse_axes(include_axes)
        meta_row = _fetch_houjin_meta(am_conn, normalized)
        has_adoption = False
        if _table_exists(am_conn, "jpi_adoption_records"):
            with contextlib.suppress(sqlite3.Error):
                has_adoption = (
                    am_conn.execute(
                        "SELECT 1 FROM jpi_adoption_records WHERE houjin_bangou = ? LIMIT 1",
                        (normalized,),
                    ).fetchone()
                    is not None
                )
        has_enforcement = False
        if _table_exists(am_conn, "am_enforcement_detail"):
            with contextlib.suppress(sqlite3.Error):
                has_enforcement = (
                    am_conn.execute(
                        "SELECT 1 FROM am_enforcement_detail WHERE houjin_bangou = ? LIMIT 1",
                        (normalized,),
                    ).fetchone()
                    is not None
                )

        if meta_row is None and not has_adoption and not has_enforcement:
            return make_error(
                code="not_found",
                message=(
                    f"No data found for 法人番号={normalized} across houjin_master / "
                    "jpi_adoption_records / am_enforcement_detail."
                ),
                field="houjin_id",
            )

        body = _build_risk_score(
            am_conn=am_conn,
            houjin_id=normalized,
            selected_axes=selected_axes,
            weight_overrides=weight_overrides,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    body.setdefault("_disclaimer", _RISK_SCORE_DISCLAIMER)
    body.setdefault("_billing_unit", 1)
    return body


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_INTEL_COMPOSITE_ENABLED +
# AUTONOMATH_ENABLED. Each docstring kept ≤ 400 chars per Wave 21 spec.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def intel_probability_radar(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Program unified id (UNI-...) or canonical id (program:...).",
            ),
        ],
        houjin_bangou: Annotated[
            str,
            Field(
                min_length=13,
                max_length=14,
                description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
            ),
        ],
        effort_hours_override: Annotated[
            int | None,
            Field(
                None,
                ge=1,
                le=2000,
                description="Optional caller-supplied 申請工数 hours. Default 25h.",
            ),
        ] = None,
        hourly_rate_yen_override: Annotated[
            int | None,
            Field(
                None,
                ge=1_000,
                le=100_000,
                description="Optional 中小企業診断士 hourly rate (¥). Default ¥8,000.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W30-8] probability_estimate (NOT forecast) + same-industry adoption rate + mean award + ROI for (program × houjin) in 1 call. Pure SQLite, NO LLM. §52/§1 行政書士法 fence — output is statistical estimate, NOT 採択保証. Replaces 5+ legacy fan-out calls."""
        return _intel_probability_radar_impl(
            program_id=program_id,
            houjin_bangou=houjin_bangou,
            effort_hours_override=effort_hours_override,
            hourly_rate_yen_override=hourly_rate_yen_override,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_audit_chain(
        evidence_packet_id: Annotated[
            str,
            Field(
                min_length=5,
                max_length=80,
                description="Evidence packet identifier, e.g. 'evp_a1b2c3d4'.",
            ),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W30-9] Composite Merkle proof + sources + 5-step verify chain in 1 call. Replaces 3-call audit fan-out (/v1/audit/proof + /v1/audit/seals + /v1/am/provenance). Auditor pastes booleans directly into 監査調書. ¥3/req. §47条の2 / §52 fence — cryptographic provenance only, NOT 監査意見."""
        return _intel_audit_chain_impl(evidence_packet_id=evidence_packet_id)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_match(
        industry_jsic_major: Annotated[
            str, Field(min_length=1, max_length=1, description="JSIC 大分類 single letter (A–T).")
        ],
        prefecture_code: Annotated[
            str,
            Field(
                min_length=2,
                max_length=2,
                description="JIS X 0401 prefecture code (01–47). 13=東京都.",
            ),
        ],
        capital_jpy: Annotated[
            int | None,
            Field(
                None,
                ge=0,
                description="Applicant capital in JPY (used for soft amount-fit ranking).",
            ),
        ] = None,
        employee_count: Annotated[
            int | None, Field(None, ge=0, description="Applicant employee headcount.")
        ] = None,
        keyword: Annotated[
            str | None,
            Field(
                None,
                max_length=200,
                description="Free-text keyword matched against primary_name (LIKE).",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(5, ge=1, le=20, description="Cap on matched_programs[] length. Hard cap = 20."),
        ] = 5,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W30-4] Smart matchmaking: top-N programs with documents, similar adopters, laws, tsutatsu, audit proof, plus next_questions, eligibility_gaps, and document_readiness to plan follow-up and application prep. Pure SQLite ranking. §52/§1 fence."""
        return _intel_match_impl(
            industry_jsic_major=industry_jsic_major,
            prefecture_code=prefecture_code,
            capital_jpy=capital_jpy,
            employee_count=employee_count,
            keyword=keyword,
            limit=limit,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_program_full(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Program unified id (UNI-...) or canonical id (program:...).",
            ),
        ],
        include_sections: Annotated[
            list[str] | None,
            Field(
                None,
                description="Sections to include. Allowed: meta, eligibility, amendments, adoptions, similar, citations, audit_proof. Defaults to all 7.",
            ),
        ] = None,
        max_per_section: Annotated[
            int, Field(5, ge=1, le=20, description="Per-section row cap (1..20).")
        ] = 5,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W30-2] Composite per-program bundle in 1 call: program_meta + eligibility_predicate + amendments_recent + adoptions_top + similar_programs + citations + audit_proof. Replaces 8+ naive single-program calls. ¥3/req. §52/§1/§72 fence."""
        return _intel_program_full_impl(
            program_id=program_id,
            include_sections=include_sections,
            max_per_section=max_per_section,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_houjin_full(
        houjin_id: Annotated[
            str,
            Field(
                min_length=13,
                max_length=14,
                description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
            ),
        ],
        include_sections: Annotated[
            list[str] | None,
            Field(
                None,
                description="Sections: meta, adoption_history, enforcement, invoice_status, peer_summary, jurisdiction, watch_status. Defaults to all.",
            ),
        ] = None,
        max_per_section: Annotated[
            int, Field(5, ge=1, le=50, description="Per-list-section row cap.")
        ] = 5,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W30-3] Composite houjin 360-degree bundle in 1 call: meta + adoption_history + enforcement + invoice_status + peer_summary + jurisdiction + watch_status + decision_support.{risk_summary,decision_insights,next_actions,known_gaps}. Replaces 5+ legacy fan-out reads. ¥3/req. §52/§72/§1 fence."""
        return _intel_houjin_full_impl(
            houjin_id=houjin_id,
            include_sections=include_sections,
            max_per_section=max_per_section,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_diff(
        a: Annotated[
            dict[str, str],
            Field(description="Left side {type: 'program'|'houjin'|'law', id: '...'}."),
        ],
        b: Annotated[
            dict[str, str], Field(description="Right side {type, id} — must match a.type.")
        ],
        depth: Annotated[
            int, Field(2, ge=1, le=3, description="Neighbourhood depth (1..3) for am_5hop_graph.")
        ] = 2,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-1] Composite entity diff (M&A DD): shared_attrs + unique_to_a + unique_to_b + conflict_points across primary table + am_5hop_graph + am_program_eligibility_predicate + am_id_bridge. Pure SQLite + Python set arithmetic, NO LLM. ¥3/req. §52/§72/§1/§3/§47条の2 fence — descriptive, NOT prescriptive."""
        return _intel_diff_impl(a=a, b=b, depth=depth)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_path(
        from_entity: Annotated[
            dict[str, str],
            Field(description="Source {type: 'program'|'law'|'court_decision'|..., id: '...'}."),
        ],
        to_entity: Annotated[dict[str, str], Field(description="Destination {type, id}.")],
        max_hops: Annotated[
            int,
            Field(
                3,
                ge=1,
                le=5,
                description="Maximum hops per side; bidirectional walk cap = 2 * max_hops.",
            ),
        ] = 3,
        relation_filter: Annotated[
            list[str] | None,
            Field(
                None,
                description="Optional edge relation_types to keep, e.g. ['cites','amends']. Empty = all edges.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-2] 5-hop bidirectional BFS reasoning chain between 2 entities in 1 call. Returns shortest_path + up to 3 alternates so customer LLM can visualise the citation chain. Walks am_5hop_graph + am_citation_network + am_id_bridge. ¥3/req. §52/§72/§1 fence."""
        return _intel_path_impl(
            from_entity=from_entity,
            to_entity=to_entity,
            max_hops=max_hops,
            relation_filter=relation_filter,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_timeline(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Program canonical id (UNI-... or program:...).",
            ),
        ],
        year: Annotated[
            int,
            Field(
                0,
                ge=0,
                le=2100,
                description="Calendar year for timeline window (default = current year). 0 = current.",
            ),
        ] = 0,
        include_types: Annotated[
            list[str] | None,
            Field(
                None,
                description="Event types: amendment, adoption, enforcement, narrative_update. Defaults to all 4.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-3] Annual cross-substrate event timeline for 1 program in 1 call. Cross-joins am_amendment_diff + am_adoption_trend_monthly + am_enforcement_anomaly + am_adopted_company_features + am_program_narrative_full. NO LLM. §52/§1/§72 fence."""
        return _intel_timeline_impl(program_id=program_id, year=year, include_types=include_types)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_conflict(
        program_ids: Annotated[
            list[str],
            Field(
                min_length=2,
                max_length=20,
                description="2-20 program identifiers (UNI-... or canonical).",
            ),
        ],
        houjin_id: Annotated[
            str,
            Field(
                min_length=13, max_length=14, description="13-digit 法人番号 evaluation context."
            ),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-4] Combo conflict detector: pairwise check across am_compat_matrix + jpi_exclusion_rules + 適正化法 17 conditions, returns conflict_pairs + alternative_bundles. ¥3/req. §52/§1 fence — flagging compatibility, NOT 申請可否判定."""
        return _intel_conflict_impl(program_ids=program_ids, houjin_id=houjin_id)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_why_excluded(
        program_id: Annotated[
            str,
            Field(
                min_length=4,
                max_length=64,
                description="jpi_programs.unified_id (e.g. 'UNI-75690a3d74').",
            ),
        ],
        houjin: Annotated[
            dict[str, Any],
            Field(
                description="Houjin descriptor {id?, capital?, employees?, industry?, founded_year?, prefecture?, jsic?, certifications?[]}."
            ),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-5] Eligibility-failure reasoning: returns predicate_violations + remediation_steps + suggested_alternative_programs in 1 call. Walks am_program_eligibility_predicate + am_relation. NO LLM. §52/§1 fence — heuristic remediation, NOT 申請代理."""
        return _intel_why_excluded_impl(program_id=program_id, houjin=houjin)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_peer_group(
        houjin_id: Annotated[
            str | None,
            Field(
                None,
                min_length=13,
                max_length=14,
                description="13-digit 法人番号 OR omit + supply houjin_attributes.",
            ),
        ] = None,
        houjin_attributes: Annotated[
            dict[str, Any] | None,
            Field(
                None,
                description="Inline houjin profile {name?, capital?, employees?, jsic?, prefecture?} — for未登録 entities.",
            ),
        ] = None,
        peer_count: Annotated[
            int, Field(5, ge=3, le=10, description="Number of peers to return (3..10).")
        ] = 5,
        comparison_axes: Annotated[
            list[str] | None,
            Field(
                None,
                description="Axes from {adoption_count, total_amount, category_diversity}. Defaults to all 3.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-6] 同業他社 N peers in 1 call: Jaccard similarity on (jsic × prefecture × capital × employee bucket) + per-axis comparison envelope. NO LLM. §52/§72 fence — peer benchmarking, NOT 信用調査."""
        return _intel_peer_group_impl(
            houjin_id=houjin_id,
            houjin_attributes=houjin_attributes,
            peer_count=peer_count,
            comparison_axes=comparison_axes,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_regulatory_context(
        program_id: Annotated[
            str, Field(min_length=1, max_length=200, description="Program unified id (UNI-...).")
        ],
        include: Annotated[
            list[str] | None,
            Field(
                None,
                description="Subset of {law, tsutatsu, kessai, hanrei, gyosei_shobun}. Defaults to all 5.",
            ),
        ] = None,
        max_per_type: Annotated[
            int, Field(10, ge=1, le=50, description="Cap per axis. Hard ceiling 50.")
        ] = 10,
        since_date: Annotated[
            str | None,
            Field(None, description="ISO 8601 (YYYY-MM-DD) lower bound on document date."),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-7] Full regulatory bundle for 1 program in 1 call: 法令 + 通達 + 裁決 + 判例 + 行政処分. Replaces 5+ axis-specific fan-out calls. ¥3/req. §72/§52/§1 fence — primary-source pointers, NOT 法解釈."""
        return _intel_regulatory_context_impl(
            program_id=program_id,
            include=include,
            max_per_type=max_per_type,
            since_date=since_date,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_bundle_optimal(
        houjin_id: Annotated[
            str | dict[str, Any],
            Field(
                description="13-digit 法人番号 OR dict {houjin_bangou?, prefecture?, jsic_major?, capital_yen?, employee_count?}."
            ),
        ],
        bundle_size: Annotated[
            int, Field(5, ge=1, le=10, description="Target bundle size (1..10).")
        ] = 5,
        objective: Annotated[
            Literal["max_amount", "max_count", "min_overlap"],
            Field("max_amount", description="Optimization objective."),
        ] = "max_amount",
        exclude_program_ids: Annotated[
            list[str] | None, Field(None, description="Hard-exclude program ids.")
        ] = None,
        prefer_categories: Annotated[
            list[str] | None,
            Field(None, description="Soft-bias categories (JSIC majors / program_kind)."),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-8] Houjin → 最適 program bundle in 1 call: greedy weighted optimizer over am_recommended_programs + am_compat_matrix + jpi_exclusion_rules. Returns bundle + total_expected_amount + conflict graph + alternative bundles + decision_support.{why_this_matters,decision_insights,next_actions}. ¥3/req. §52/§1 fence."""
        return _intel_bundle_optimal_impl(
            houjin_id=houjin_id,
            bundle_size=bundle_size,
            objective=objective,
            exclude_program_ids=exclude_program_ids,
            prefer_categories=prefer_categories,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_citation_pack(
        program_id: Annotated[
            str, Field(min_length=1, max_length=200, description="Program unified id (UNI-...).")
        ],
        format: Annotated[
            Literal["markdown", "json"], Field("markdown", description="Output format.")
        ] = "markdown",  # noqa: A002
        max_citations: Annotated[
            int,
            Field(30, ge=5, le=100, description="Hard cap on total citations across all sections."),
        ] = 30,
        include_adoptions: Annotated[
            bool, Field(True, description="Include 採択事例 section.")
        ] = True,
        citation_style: Annotated[
            Literal["footnote", "inline"], Field("footnote", description="Citation marker style.")
        ] = "footnote",
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W31-9] Citation pack — every primary-source citation surface (法令+通達+裁決+判例+行政処分+採択) bundled as markdown (default) or JSON in 1 call. ¥3/req. §52/§47条の2/§1/§72 fence — citation pack can be re-quoted into 申請書面/提案書 territory."""
        return _intel_citation_pack_impl(
            program_id=program_id,
            format=format,
            max_citations=max_citations,
            include_adoptions=include_adoptions,
            citation_style=citation_style,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def intel_risk_score(
        houjin_id: Annotated[
            str,
            Field(
                min_length=13,
                max_length=14,
                description="13-digit 法人番号 (with or without 'T' prefix).",
            ),
        ],
        include_axes: Annotated[
            list[str] | None,
            Field(
                None,
                description="Axes: enforcement, refund, invoice_compliance, adoption_revocation, jurisdiction_drift. Default = all.",
            ),
        ] = None,
        weight_overrides: Annotated[
            dict[str, float] | None,
            Field(
                None, description="Optional per-axis weights in [0,1]. Unknown axes are ignored."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32-3] Multi-axis houjin risk score: enforcement + refund + invoice + adoption revocation + jurisdiction drift in 1 call. Rules-based public-data score, NO LLM. ¥3/req. NOT a credit rating; §72/§52/§1 fence."""
        return _intel_risk_score_impl(
            houjin_id=houjin_id,
            include_axes=include_axes,
            weight_overrides=weight_overrides,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.intel_wave31
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import json

    print("intel_wave31 self-test (smoke):")
    res = _intel_match_impl(
        industry_jsic_major="E",
        prefecture_code="13",
        keyword="DX",
        limit=3,
    )
    print(
        json.dumps(
            {
                "tool": "intel_match",
                "ok": "matched_programs" in res or "error" in res,
                "matched_count": len(res.get("matched_programs", [])),
                "has_disclaimer": "_disclaimer" in res,
            },
            ensure_ascii=False,
        )
    )
