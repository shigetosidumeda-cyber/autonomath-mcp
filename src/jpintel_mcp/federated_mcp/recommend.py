"""Gap-keyword → partner-capability matcher for Wave 51 dim R.

The matcher is intentionally **deterministic**:

    1. Lowercase + tokenise the query gap string on ascii word boundaries
       (and Japanese full/half-width punctuation), keeping kanji /
       hiragana / katakana runs intact.
    2. For each partner, count how many capability tags appear as
       substrings of the lowercased gap, plus an additional set of
       partner-specific Japanese/English keyword aliases.
    3. Rank partners by score descending, then by canonical partner_id
       ascending for stable ordering. Score-0 partners are dropped.

There is **no LLM call**, **no HTTP call**, and **no embedding lookup**.
The full match pipeline runs in pure-Python in microseconds — exactly
what the ``feedback_federated_mcp_recommendation`` "LLM API禁止" rule
requires.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from jpintel_mcp.federated_mcp.registry import (
    FederatedRegistry,
    load_default_registry,
)

if TYPE_CHECKING:
    from jpintel_mcp.federated_mcp.models import PartnerMcp

#: Partner-specific Japanese / English alias tokens. Mapped against the
#: lowercased gap as substrings. Aliases are intentionally narrow —
#: capability tags should carry the bulk of the matching weight; the
#: alias map is for high-signal natural-language phrases the capability
#: tag itself cannot express in ascii.
_PARTNER_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "freee": (
        "freee",
        "freee会計",
        "会計freee",
        "確定申告",
        "請求書",
        "経費",
        "経理",
        "会計ソフト",
        "会計データ",
        "会計帳簿",
    ),
    "github": (
        "github",
        "git hub",
        "リポジトリ",
        "プルリクエスト",
        "プルリク",
        "pull req",
        "コードレビュー",
    ),
    "linear": (
        "linear",
        "プロダクト管理",
        "イシュー",
        "サイクル",
        "ロードマップ",
    ),
    "mf": (
        "moneyforward",
        "money forward",
        "マネーフォワード",
        "mfクラウド",
        "確定申告",
        "請求書",
        "給与計算",
        "経理",
        "会計データ",
        "会計帳簿",
    ),
    "notion": (
        "notion",
        "ノーション",
        "ナレッジベース",
        "社内wiki",
        "wiki",
        "ドキュメント",
        "知識ベース",
    ),
    "slack": (
        "slack",
        "スラック",
        "チャット",
        "チャンネル",
        "通知",
        "メッセージ送信",
    ),
}


_NON_ASCII_WORD = re.compile(r"[A-Za-z0-9_]+")


def _normalise_gap(query_gap: str) -> str:
    """Lowercase + collapse whitespace + strip leading/trailing punct."""
    return " ".join(query_gap.lower().split())


def _ascii_tokens(normalised_gap: str) -> set[str]:
    """Extract the ascii word tokens for capability-tag substring match."""
    return set(_NON_ASCII_WORD.findall(normalised_gap))


def _score_partner(partner: PartnerMcp, normalised_gap: str) -> int:
    """Return the unweighted hit count for ``partner`` against the gap.

    Each capability tag hit counts as 1; each partner-alias hit counts
    as 1. A capability tag matches either as a whole ascii token or as
    a substring with underscores converted to spaces, so e.g. the tag
    ``pull_request`` matches the gap text ``"pull request"`` and the
    gap text ``"pull_request"`` equally.
    """
    score = 0
    ascii_tokens = _ascii_tokens(normalised_gap)
    for tag in partner.capabilities:
        if tag in ascii_tokens:
            score += 1
            continue
        # underscore→space alias (e.g. "pull_request" → "pull request")
        if "_" in tag and tag.replace("_", " ") in normalised_gap:
            score += 1
    for alias in _PARTNER_ALIASES.get(partner.partner_id, ()):
        if alias.lower() in normalised_gap:
            score += 1
    return score


def recommend_handoff(
    query_gap: str,
    *,
    registry: FederatedRegistry | None = None,
    max_results: int = 3,
) -> tuple[PartnerMcp, ...]:
    """Recommend up to ``max_results`` partners for ``query_gap``.

    Parameters
    ----------
    query_gap:
        Free-form natural-language description of what jpcite cannot
        answer (e.g. "freee の請求書 #1234 が必要" or "look up the
        pull request title on github"). May be Japanese or English.
    registry:
        Defaults to the cached :func:`load_default_registry` instance.
        Tests can inject a custom shortlist via
        :meth:`FederatedRegistry.from_partners`.
    max_results:
        Maximum number of partners to return. Score-tied partners are
        ordered by canonical ``partner_id`` ascending for stable output.

    Returns
    -------
    tuple[PartnerMcp, ...]
        Recommendations in descending score order. Empty tuple if no
        partner matches. NEVER includes a self-reference (jpcite /
        jpintel) — the registry constructor rejects those slugs at
        load time.

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

    reg = registry if registry is not None else load_default_registry()
    normalised = _normalise_gap(query_gap)

    scored: list[tuple[int, str, PartnerMcp]] = []
    for partner in reg.partners:
        score = _score_partner(partner, normalised)
        if score > 0:
            scored.append((score, partner.partner_id, partner))

    # Sort: score DESC, partner_id ASC (stable secondary key).
    scored.sort(key=lambda triple: (-triple[0], triple[1]))
    return tuple(p for _, _, p in scored[:max_results])


__all__ = ["recommend_handoff"]
