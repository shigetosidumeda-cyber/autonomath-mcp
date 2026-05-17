"""DD1 12-partner federated MCP registry (additive over Wave 51 dim R).

This module is the **additive expansion** delivered on 2026-05-17 (DD1).
It does NOT replace the canonical 6-partner registry in
:mod:`jpintel_mcp.federated_mcp.registry` — that contract is preserved
verbatim so existing Wave 51 tests, audit logs, and the migration-278
storage layer remain stable.

What DD1 adds
-------------
* :data:`DD1_PARTNER_IDS_12` — frozen tuple of 12 partner_ids in
  canonical (alphabetical) order. The original 6 (freee / github /
  linear / mf / notion / slack) are augmented by 6 expansion
  partners (aws_bedrock / claude_ai / google_drive / ms_teams /
  salesforce / stripe).
* :data:`DD1_FEDERATED_PARTNERS_JSON` — path to
  ``data/federated_partners_12.json``, the canonical 12-partner JSON.
* :data:`DD1_FEDERATED_PARTNERS_YAML` — path to
  ``data/federated_mcp_partners.yaml``, the human-editable companion.
* :func:`load_dd1_registry_12` — builds a :class:`FederatedRegistry`
  from the 12-partner JSON, cached across calls.
* :data:`DD1_PARTNER_ALIASES_EXPANSION_6` — Japanese / English alias
  tokens for the 6 expansion partners. Mirrors the shape of the
  6-base alias map in :mod:`jpintel_mcp.federated_mcp.recommend`.
* :func:`recommend_handoff_12` — gap-keyword matcher that uses the
  12-partner registry + the merged alias map (base 6 + expansion 6).

Hard rules preserved
--------------------
* No self-reference — ``jpcite`` / ``jpintel`` / ``autonomath`` are
  rejected at load time by :class:`FederatedRegistry`.
* No aggregator MCP endpoints — first-party only. Endpoints verified
  2026-05-17.
* No LLM API import. No HTTP call at runtime. Deterministic match.
* https only for every URL. Pydantic-validated on load.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Final

from jpintel_mcp.federated_mcp.models import PartnerMcp
from jpintel_mcp.federated_mcp.recommend import _PARTNER_ALIASES as _BASE_6_ALIASES
from jpintel_mcp.federated_mcp.registry import FederatedRegistry

#: Path to the DD1 canonical 12-partner JSON.
DD1_FEDERATED_PARTNERS_JSON: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[3] / "data" / "federated_partners_12.json"
)

#: Path to the DD1 human-editable YAML companion.
DD1_FEDERATED_PARTNERS_YAML: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[3] / "data" / "federated_mcp_partners.yaml"
)

#: Frozen tuple of all 12 partner_ids in canonical (alphabetical) order.
#: Pinned for wire-shape regression tests; bumping requires a
#: coordinated update to ``data/federated_partners_12.json`` +
#: ``data/federated_mcp_partners.yaml`` +
#: ``site/.well-known/jpcite-federated-mcp-12-partners.json``.
DD1_PARTNER_IDS_12: Final[tuple[str, ...]] = (
    "aws_bedrock",
    "claude_ai",
    "freee",
    "github",
    "google_drive",
    "linear",
    "mf",
    "ms_teams",
    "notion",
    "salesforce",
    "slack",
    "stripe",
)

#: Subset retained from the Wave 51 dim R base cohort.
DD1_BASE_6: Final[tuple[str, ...]] = (
    "freee",
    "github",
    "linear",
    "mf",
    "notion",
    "slack",
)

#: 6 expansion partners added on 2026-05-17 (DD1). Each surfaces a
#: distinct agent-discovery axis: billing reconciliation (stripe),
#: CRM (salesforce), enterprise messaging (ms_teams), document
#: management (google_drive), MCP federation hub (aws_bedrock), and
#: cross-promotion (claude_ai).
DD1_EXPANSION_6: Final[tuple[str, ...]] = (
    "aws_bedrock",
    "claude_ai",
    "google_drive",
    "ms_teams",
    "salesforce",
    "stripe",
)

#: Japanese / English alias tokens for the 6 expansion partners.
#: Mirrors the shape of the base-6 alias map in
#: :mod:`jpintel_mcp.federated_mcp.recommend`. Aliases are matched as
#: lowercased substrings against the lowercased query gap.
DD1_PARTNER_ALIASES_EXPANSION_6: Final[dict[str, tuple[str, ...]]] = {
    "aws_bedrock": (
        "aws bedrock",
        "bedrock",
        "amazon bedrock",
        "ベッドロック",
        "基盤モデル",
        "foundation model",
    ),
    "claude_ai": (
        "claude.ai",
        "claude ai",
        "claude",
        "anthropic",
        "クロード",
        "アンソロピック",
    ),
    "google_drive": (
        "google drive",
        "googledrive",
        "g drive",
        "drive",
        "グーグルドライブ",
        "google sheets",
        "google docs",
        "スプレッドシート",
    ),
    "ms_teams": (
        "ms teams",
        "msteams",
        "microsoft teams",
        "teams",
        "マイクロソフト teams",
        "チームス",
        "会議",
    ),
    "salesforce": (
        "salesforce",
        "セールスフォース",
        "crm",
        "顧客管理",
        "商談",
        "リード",
        "パイプライン",
    ),
    "stripe": (
        "stripe",
        "ストライプ",
        "決済",
        "サブスクリプション",
        "サブスク",
        "請求",
        "課金",
        "支払い",
    ),
}

#: Merged 12-partner alias map (base 6 + expansion 6). Built lazily at
#: import time from the two source maps so any future edits to the
#: base 6 propagate automatically.
DD1_PARTNER_ALIASES_12: Final[dict[str, tuple[str, ...]]] = {
    **_BASE_6_ALIASES,
    **DD1_PARTNER_ALIASES_EXPANSION_6,
}

_NON_ASCII_WORD = re.compile(r"[A-Za-z0-9_]+")


def _load_partners_from_json(path: pathlib.Path) -> tuple[PartnerMcp, ...]:
    """Load + validate every row from the 12-partner JSON."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    partners_raw = raw["partners"]
    if not isinstance(partners_raw, list):
        raise ValueError(
            f"federated_partners_12.json `partners` must be a list, got {type(partners_raw)!r}"
        )
    return tuple(PartnerMcp.model_validate(row) for row in partners_raw)


_CACHED_DD1_REGISTRY_12: FederatedRegistry | None = None


def load_dd1_registry_12() -> FederatedRegistry:
    """Return the cached 12-partner registry built from the DD1 JSON.

    The registry is loaded on first call and cached. Subsequent calls
    return the same instance — partner rows are immutable and the JSON
    is a shipped fixture, so re-reading is wasted I/O.
    """
    global _CACHED_DD1_REGISTRY_12
    if _CACHED_DD1_REGISTRY_12 is None:
        partners = _load_partners_from_json(DD1_FEDERATED_PARTNERS_JSON)
        _CACHED_DD1_REGISTRY_12 = FederatedRegistry(partners)
    return _CACHED_DD1_REGISTRY_12


def _normalise_gap(query_gap: str) -> str:
    """Lowercase + collapse whitespace."""
    return " ".join(query_gap.lower().split())


def _ascii_tokens(normalised_gap: str) -> set[str]:
    """Extract ascii word tokens for capability-tag substring match."""
    return set(_NON_ASCII_WORD.findall(normalised_gap))


def _score_partner_12(partner: PartnerMcp, normalised_gap: str) -> int:
    """Return the unweighted hit count for ``partner`` against the gap.

    Mirrors :func:`jpintel_mcp.federated_mcp.recommend._score_partner`
    but consults the merged 12-partner alias map so the 6 expansion
    partners get the same high-signal natural-language coverage as
    the 6 base partners.
    """
    score = 0
    ascii_tokens = _ascii_tokens(normalised_gap)
    for tag in partner.capabilities:
        if tag in ascii_tokens:
            score += 1
            continue
        if "_" in tag and tag.replace("_", " ") in normalised_gap:
            score += 1
    for alias in DD1_PARTNER_ALIASES_12.get(partner.partner_id, ()):
        if alias.lower() in normalised_gap:
            score += 1
    return score


def recommend_handoff_12(
    query_gap: str,
    *,
    registry: FederatedRegistry | None = None,
    max_results: int = 3,
) -> tuple[PartnerMcp, ...]:
    """Recommend up to ``max_results`` partners against the 12-partner roster.

    Mirrors :func:`jpintel_mcp.federated_mcp.recommend.recommend_handoff`
    but defaults to :func:`load_dd1_registry_12` and uses the merged
    12-partner alias map. Tests can inject a custom shortlist via the
    ``registry`` keyword argument.

    Parameters
    ----------
    query_gap:
        Free-form natural-language description of what jpcite cannot
        answer. May be Japanese or English.
    registry:
        Defaults to the cached 12-partner registry. Pass a custom
        :class:`FederatedRegistry` for tests.
    max_results:
        Maximum number of partners to return. Score-tied partners are
        ordered by canonical ``partner_id`` ascending for stable output.

    Raises
    ------
    ValueError
        If ``query_gap`` is empty / whitespace-only, or ``max_results``
        is < 1.
    """
    if not query_gap or not query_gap.strip():
        raise ValueError("query_gap must be non-empty")
    if max_results < 1:
        raise ValueError("max_results must be >= 1")

    reg = registry if registry is not None else load_dd1_registry_12()
    normalised = _normalise_gap(query_gap)

    scored: list[tuple[int, str, PartnerMcp]] = []
    for partner in reg.partners:
        score = _score_partner_12(partner, normalised)
        if score > 0:
            scored.append((score, partner.partner_id, partner))

    scored.sort(key=lambda triple: (-triple[0], triple[1]))
    return tuple(p for _, _, p in scored[:max_results])


__all__ = [
    "DD1_BASE_6",
    "DD1_EXPANSION_6",
    "DD1_FEDERATED_PARTNERS_JSON",
    "DD1_FEDERATED_PARTNERS_YAML",
    "DD1_PARTNER_ALIASES_12",
    "DD1_PARTNER_ALIASES_EXPANSION_6",
    "DD1_PARTNER_IDS_12",
    "load_dd1_registry_12",
    "recommend_handoff_12",
]
