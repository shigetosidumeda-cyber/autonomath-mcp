"""Shared envelope constants + helpers for moat_lane_tools/* submodules.

Each moat lane (M1-M11 + N1-N9) attaches the same canonical disclaimer
envelope and the same ISO-UTC timestamp helper. Centralising both here
keeps every lane's MCP tool response shape strictly identical.

Two response envelopes are kept side-by-side:

* :func:`pending_envelope` — emitted by a PENDING wrapper whose upstream
  lane has not yet landed (or is in DRY_RUN). The envelope still carries
  the §52 / §47条の2 / §72 / §1 / §3 disclaimer and a stable provenance
  pointer so agent code can integrate against the contract today.
* :data:`DISCLAIMER` — the canonical disclaimer string used by both
  the PENDING envelope and any LIVE db-backed wrapper.

The helpers are intentionally pure-Python + zero-cost. No LLM inference
is performed in either path.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

__all__ = ["DISCLAIMER", "today_iso_utc", "pending_envelope"]


# Canonical disclaimer for moat-lane tool responses. Mirrors the wording
# used by other autonomath_tools/* responses to keep the §52 / §47条の2 /
# §72 / §1 / §3 footer uniform across the MCP surface.
DISCLAIMER = (
    "本 response は moat lane の retrieval / モデル推論結果で、採択 / 法的判断 / "
    "税務助言を担保するものではありません。corpus snapshot 上の類似度・スコア順位で、"
    "行政書士法 §1 / 税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / "
    "司法書士法 §3 の業務範囲は含みません。確定判断は士業へ、primary source 確認必須。"
)


def today_iso_utc() -> str:
    """Return today's date (UTC) as an ISO-8601 ``YYYY-MM-DD`` string.

    Returns
    -------
    str
        UTC calendar date, e.g. ``"2026-05-17"``.
    """
    return _dt.datetime.now(_dt.UTC).date().isoformat()


def pending_envelope(
    *,
    tool_name: str,
    lane_id: str,
    upstream_module: str,
    schema_version: str,
    primary_input: dict[str, Any],
) -> dict[str, Any]:
    """Return the canonical PENDING envelope for a moat lane wrapper.

    Used while the upstream lane is still in flight (or in DRY_RUN). The
    envelope keeps the contract stable so agent code can probe the tool
    today and surface the populated payload once the upstream lane lands.

    Parameters
    ----------
    tool_name:
        Public MCP tool name (must match the ``@mcp.tool``-decorated
        function name).
    lane_id:
        Lane label, e.g. ``"M1"`` / ``"N4"``. Surfaces in the
        ``_pending_marker`` field as ``"PENDING <lane_id>"`` so downstream
        agents can branch on PENDING vs LIVE.
    upstream_module:
        Dotted module path of the upstream lane implementation (even if
        the module is not yet importable).
    schema_version:
        Wrapper schema version (e.g. ``"moat.m1.v1"``). Bumped on
        breaking changes.
    primary_input:
        Sanitized input dict echoed back to the caller for round-trip
        debugging. Trim long fields before passing — this dict is
        included verbatim in the envelope.

    Returns
    -------
    dict[str, Any]
        Canonical PENDING envelope.
    """
    return {
        "tool_name": tool_name,
        "schema_version": schema_version,
        "primary_result": {
            "status": "pending_upstream_lane",
            "lane_id": lane_id,
            "upstream_module": upstream_module,
            "primary_input": primary_input,
            "rationale": (
                f"Niche Moat Lane {lane_id} wrap is registered as a contract scaffold. "
                "Upstream lane module is not yet wired in this build — wrapper "
                "returns a structured PENDING envelope until the underlying lane "
                "lands. NO LLM inference is performed here."
            ),
        },
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": upstream_module,
            "lane_id": lane_id,
            "wrap_kind": "moat_lane_n10_wrap",
            "observed_at": today_iso_utc(),
        },
        "_billing_unit": 1,
        "_disclaimer": DISCLAIMER,
        "_pending_marker": f"PENDING {lane_id}",
    }
