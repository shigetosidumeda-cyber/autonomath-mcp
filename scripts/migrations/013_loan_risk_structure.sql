-- 013_loan_risk_structure.sql
-- Splits loan_programs.security_required (a single free-text bucket) into
-- three orthogonal risk axes so consumers can filter by the *kind* of
-- obligation a loan imposes, not just the phrase used on the brochure:
--
--   collateral_required            物的担保 (land / building / deposits)
--   personal_guarantor_required    代表者 / 役員 / 家族 保証
--   third_party_guarantor_required 第三者保証人 (外部連帯保証人)
--
-- Each axis value is one of: 'required' | 'not_required' | 'negotiable' | 'unknown'.
-- `security_notes` keeps the original free text for audit and the rows that
-- need human judgement after automated classification.
--
-- Why three axes: 無担保無保証人融資 (JFC マル経, 新創業融資 etc.) is a
-- materially different risk class than 担保あり保証人あり loans. The prior
-- single `security_required` column collapsed both into "要相談" / "要相談（担保・保証）"
-- for 107 / 108 rows — unusable for risk-aware filtering and the specific
-- signal AutonoMath is built to surface. Classifying on ingest means a
-- consumer checking "give me loans available unsecured and unguaranteed"
-- gets the right 1 row (資本性ローン / マル経 etc.) instead of a list they
-- have to triage themselves.
--
-- Idempotency:
--   * The ALTERs are handled by the duplicate-column fallback in
--     scripts/migrate.py (same pattern as 009, 011). Re-applying this
--     migration on a partially-migrated DB is a no-op.
--   * CREATE INDEX IF NOT EXISTS is natively idempotent.

ALTER TABLE loan_programs ADD COLUMN collateral_required TEXT;
ALTER TABLE loan_programs ADD COLUMN personal_guarantor_required TEXT;
ALTER TABLE loan_programs ADD COLUMN third_party_guarantor_required TEXT;
ALTER TABLE loan_programs ADD COLUMN security_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_loan_programs_collateral
    ON loan_programs(collateral_required);
CREATE INDEX IF NOT EXISTS idx_loan_programs_personal_guarantor
    ON loan_programs(personal_guarantor_required);
CREATE INDEX IF NOT EXISTS idx_loan_programs_third_party_guarantor
    ON loan_programs(third_party_guarantor_required);
