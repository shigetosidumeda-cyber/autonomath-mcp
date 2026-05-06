"""Shared constants for MCP tool parameter typing.

Why this exists
---------------
MCP tools expose schemas to client LLMs over the wire. When a parameter
is typed as plain ``str | None``, the LLM has no way to know the canonical
value set, and a typo (``"東京"`` vs ``"東京都"``, ``"Tokyo"`` vs ``"とうきょう"``)
silently mismatches the DB and returns 0 rows. At ¥3/req metered, every
typo-driven empty result is customer money wasted on retry loops, plus
a 詐欺 risk if the agent treats ``total=0`` as "no eligible programs".

This module defines a closed-set ``Literal`` for the 47 都道府県 + 全国,
plus a Pydantic-V2 ``BeforeValidator``-wrapped type that normalizes
common aliases (short kanji, romaji, hiragana) to the canonical full-suffix
form *before* the Literal validator runs. The result: agents can pass
``"東京"`` / ``"Tokyo"`` / ``"とうきょう"`` and the schema both:

  1. Advertises the canonical 48 values to the client (Literal).
  2. Accepts well-known aliases at the boundary (BeforeValidator).
  3. Rejects unknown values with ``invalid_enum`` instead of silently
     filtering on a typo.

See ``src/jpintel_mcp/api/vocab.py`` for the alias map; this module
imports the same ``_normalize_prefecture`` so the wire-side and the
DB-side stay in lockstep.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BeforeValidator

from jpintel_mcp.api.vocab import _normalize_prefecture

# ---------------------------------------------------------------------------
# Canonical 47 都道府県 + 全国 sentinel.
#
# Order matches 全国地方公共団体コード (北→南, 沖縄, then 全国 last).
# This is the exact set of values stored in jpintel.db / autonomath.db
# under the `prefecture` column on populated rows.
# ---------------------------------------------------------------------------

PREFECTURES_47 = Literal[
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
    "全国",
]


def _prefecture_before_validator(value: object) -> object:
    """Normalize alias inputs to canonical full-suffix kanji.

    Runs *before* the Literal validator so '東京' / 'Tokyo' / 'とうきょう'
    all collapse to '東京都' (which the Literal accepts). Unknown values
    pass through unchanged so Pydantic's downstream Literal validator
    raises ``invalid_enum`` with a clean error message instead of letting
    a typo silently filter the DB.

    None / non-str inputs pass through unchanged so the Optional-None
    case still works (``prefecture=None`` means 'no filter').
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    normalized = _normalize_prefecture(value)
    return normalized if normalized is not None else value


#: ``Annotated[PREFECTURES_47 | None, BeforeValidator(...)]``.
#:
#: Use this as the parameter type in MCP tools that filter by prefecture::
#:
#:     def search_x(
#:         prefecture: Annotated[
#:             PrefectureParam,
#:             Field(description="..."),
#:         ] = None,
#:     ): ...
#:
#: The ``BeforeValidator`` runs first and normalizes aliases; Pydantic
#: then enforces the closed enum. Aliases ('東京', 'Tokyo') are
#: accepted and converted; unknowns raise ``invalid_enum``.
PrefectureParam = Annotated[
    PREFECTURES_47 | None,
    BeforeValidator(_prefecture_before_validator),
]


__all__ = [
    "PREFECTURES_47",
    "PrefectureParam",
]
