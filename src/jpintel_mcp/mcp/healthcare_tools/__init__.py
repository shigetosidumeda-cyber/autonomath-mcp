"""Healthcare V3 MCP tool package — scaffolding (P6-D W4 prep, 2026-04-25).

Importing this package triggers @mcp.tool registration of 6 healthcare
stub tools backed by ``data/jpintel.db`` (migration 039 schema —
``medical_institutions`` + ``care_subsidies``):

  tools.py
    - search_healthcare_programs   (薬機法/医療法/介護保険法 関連 program)
    - get_medical_institution      (医療法人 / 介護施設 / 薬局 詳細)
    - search_healthcare_compliance (景表法 + 個情法 + 薬機法 横断)
    - check_drug_approval          (PMDA 承認状況)
    - search_care_subsidies        (介護施設向け 補助金)
    - dd_medical_institution_am    (法人番号で due diligence)

Status: **scaffolding only**. Each tool returns the sentinel envelope
``{"status": "not_implemented_until_T+90d", "results": []}``. Real SQL
queries land in W4 (T+90d, 2026-08-04) directly before the V3 cohort
launch — see ``docs/healthcare_v3_plan.md``.

Registration is gated by ``AUTONOMATH_HEALTHCARE_ENABLED`` (default
``False``). At launch (2026-05-06) the env var stays unset, keeping the
public manifest at the canonical 69 tools. Operators who flip it to
``True`` see 75 tools (69 + 6 stubs) and can start testing the contract
shape ahead of the W4 implementation.
"""

from . import tools  # noqa: F401 — decorator side-effect (6 tools)
