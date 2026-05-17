"""jpcite Stage 3 Application products — A1..A4 paid composition packs.

This sub-package surfaces several ¥per-call paid composition products on top
of the moat lane infrastructure (HE-2 + N1..N9). Each product is a single
MCP tool that fans out across the underlying retrieval lanes and returns
a complete deliverable suitable for 士業 review.

Tier-D pricing band (vs the canonical ¥3/req):

* A1 (``product_tax_monthly_closing_pack``) — ¥1,000 / req (税理士 月次決算 pack).
* A2 (``product_audit_workpaper_pack``) — ¥200 / req (会計士 監査調書 pack).
* A3 (``product_subsidy_roadmap_12month``) — ¥500 / req (補助金活用ロードマップ).
* A4 (``product_shuugyou_kisoku_pack``) — ¥300 / req (就業規則生成 pack).
* A5 (``product_kaisha_setsuritsu_pack``) — ¥800 / req (司法書士 会社設立一式).

Hard constraints (CLAUDE.md / memory anchors):

* NO LLM inference — every section / disclaimer / next-action plan is
  composed deterministically by SQLite + dict assembly. The CI guard
  ``tests/test_no_llm_in_production.py`` enforces this — never import
  ``anthropic`` / ``openai`` / ``google.generativeai`` here.
* §52 (税理士法) / §47条の2 (公認会計士法) / §72 (弁護士法) / §1 (行政書士法) /
  §3 (司法書士法) / 監査基準 disclaimer envelope on every payload.
* Scaffold-only output — the wrapper never asserts the draft is a
  finished filing, signed audit opinion, or 労使協定 conclusion. The 士業
  review step is required before submission.
* Read-only SQLite (URI mode ``ro``) via the upstream lane DBs. No
  writes, no network I/O, no cron side-effects.

A1 / A2 are roadmap entries (kept for partial-checkout tolerance); the
silent ``ModuleNotFoundError`` branch below handles their absence. A3 /
A4 are LIVE products landed on top of N2 / N4 / N6 / N7 + HE-2.

The package auto-registers MCP tools on import. ``server.py`` already
imports ``moat_lane_tools`` so we follow the same seam.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger("jpintel.mcp.products")

# Canonical submodule registry. Each entry is a submodule whose import
# side-effect registers one MCP tool via the ``@mcp.tool`` decorator.
_SUBMODULES: tuple[str, ...] = (
    "product_a1_tax_monthly",
    "product_a2_audit_workpaper",
    "product_a3_subsidy_roadmap",
    "product_a4_shuugyou_kisoku",
)

for _name in _SUBMODULES:
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except ModuleNotFoundError:  # pragma: no cover — partial checkout
        logger.debug("products: skipping missing submodule %s", _name)
    except ImportError as exc:  # pragma: no cover — surface real bugs
        logger.warning("products: failed to import %s: %s", _name, exc)
