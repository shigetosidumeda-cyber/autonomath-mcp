"""Persona slug -> label + boundary-phrase index.

Single source of truth for both run_practitioner_eval.py and
assemble_trust_matrix.py. Adding a persona here automatically widens the
eval surface; do NOT inline this anywhere else.

Memory: feedback_bounded_text_to_select — slugs are bounded enums.
"""

from __future__ import annotations

PERSONA_INDEX: dict[str, str] = {
    # slug                       : canonical label as it appears in eval JSONL
    "ma_analyst": "M&Aアナリスト",
    "ma_valuation": "M&Aバリュエーション",
    "monitoring_pic": "投資先モニタリング担当",
    "zeirishi": "税理士",
    "zeirishi_kessan": "税理士 (決算前レビュー)",
    "kaikeishi": "公認会計士",
    "kaikeishi_audit": "公認会計士 (内部統制 / 監査リスク)",
    "foreign_fdi_investor": "Foreign FDI investor",
    "kokusai_zeimu": "国際税務",
    "foreign_fdi_compliance": "Foreign FDI compliance",
    "subsidy_consultant": "補助金コンサル",
    "shinkin_shokokai": "信金渉外/商工会経営支援員",
    "industry_pack_construction": "建設業owner+行政書士",
    "industry_pack_real_estate": "不動産業+司法書士",
    "ai_dev": "agent-builder engineer",
}

# Per-persona boundary phrases — at least one must appear in artifact output.
# Empty list = boundary not applicable for this persona (e.g. AI dev wrapper).
BOUNDARY_PHRASES_BY_PERSONA: dict[str, list[str]] = {
    "ma_analyst": ["§52", "§72", "顧問先確認境界", "専門家確認境界"],
    "ma_valuation": ["§52", "統計的推定", "専門家確認境界"],
    "monitoring_pic": ["§52", "監視通知", "専門家確認境界"],
    "zeirishi": ["§52", "税理士確認境界", "顧問先確認境界"],
    "zeirishi_kessan": ["§52", "税理士確認境界"],
    "kaikeishi": ["§47条の2", "会計士確認境界"],
    "kaikeishi_audit": ["§47条の2", "監査要点候補"],
    "foreign_fdi_investor": ["professional confirmation boundary", "§52"],
    "kokusai_zeimu": ["§52", "国際税務専門家"],
    "foreign_fdi_compliance": ["professional confirmation boundary", "司法書士法 §3", "§3"],
    "subsidy_consultant": ["§1", "行政書士法"],
    "shinkin_shokokai": ["§52", "§72", "§1"],
    "industry_pack_construction": ["§1", "行政書士法"],
    "industry_pack_real_estate": ["§3", "司法書士法"],
    "ai_dev": [],  # passthrough wrapper has no boundary
}

# Cohort lookup for matrix display.
PERSONA_COHORT: dict[str, str] = {
    "ma_analyst": "#1 M&A",
    "ma_valuation": "#1 M&A",
    "monitoring_pic": "#1 M&A",
    "zeirishi": "#2 税理士",
    "zeirishi_kessan": "#2 税理士",
    "kaikeishi": "#3 会計士",
    "kaikeishi_audit": "#3 会計士",
    "foreign_fdi_investor": "#4 Foreign FDI",
    "kokusai_zeimu": "#4 Foreign FDI",
    "foreign_fdi_compliance": "#4 Foreign FDI",
    "subsidy_consultant": "#5 補助金 consultant",
    "shinkin_shokokai": "#7 信金商工会",
    "industry_pack_construction": "#8 Industry packs",
    "industry_pack_real_estate": "#8 Industry packs",
    "ai_dev": "#6 AI dev",
}
