-- target_db: autonomath
-- migration 092_foreign_capital_eligibility (Foreign FDI cohort capture, feature 6)
--
-- Adds a structured foreign-capital eligibility flag to am_subsidy_rule
-- so that program_abstract_structured (and the new foreign-investor
-- audience page) can answer "is a foreign-owned KK eligible?" without
-- a free-text scan of eligibility_cond_json on every call.
--
-- The flag is heuristic-extracted from the existing eligibility text by
-- scripts/ingest_inward_fdi.py (and a one-shot backfill on first boot
-- after this migration lands). The default for *unknown* is `'silent'`
-- because the Japanese statutory default is permissive — most programs
-- do NOT exclude foreign-owned KKs unless they explicitly say so. (The
-- exclusion-by-default heuristic would generate false negatives at
-- scale and route foreign founders away from genuinely-eligible
-- programs, which is the opposite of what this whole bundle exists for.)

ALTER TABLE am_subsidy_rule ADD COLUMN foreign_capital_eligibility TEXT
    NOT NULL DEFAULT 'silent';

-- We cannot add a CHECK constraint to an existing column in SQLite
-- without a table rebuild; soft-enforce via ingest script + REST/MCP
-- input validation. Allowed values:
--   'eligible'             — text explicitly says foreign-capital OK
--   'eligible_with_caveat' — eligible but extra docs / J-visa needed
--   'excluded'             — text explicitly excludes 外資系
--   'silent'               — text does not address the question (default)
--   'case_by_case'         — explicit "事務局判断" / "個別協議" wording

CREATE INDEX IF NOT EXISTS ix_am_subsidy_rule_foreign_capital
    ON am_subsidy_rule(foreign_capital_eligibility, program_entity_id);

-- ---------------------------------------------------------------------------
-- Heuristic backfill on first boot.
-- Idempotent because the WHERE clause guards on the default value
-- 'silent' — re-runs after the operator has manually corrected a row
-- to 'eligible' will NOT clobber the manual correction.
-- ---------------------------------------------------------------------------

-- Excluded: the eligibility text contains 「外資系除く」「外国法人除く」等
UPDATE am_subsidy_rule
   SET foreign_capital_eligibility = 'excluded'
 WHERE foreign_capital_eligibility = 'silent'
   AND (
        eligibility_cond_json LIKE '%外資系を除く%'
     OR eligibility_cond_json LIKE '%外資系の事業者を除く%'
     OR eligibility_cond_json LIKE '%外資系企業を除く%'
     OR eligibility_cond_json LIKE '%外国法人を除く%'
     OR eligibility_cond_json LIKE '%外国の支配下にある%'
     OR eligibility_cond_json LIKE '%外国会社を除く%'
   );

-- Eligible-with-caveat: the text addresses foreign capital BUT requires
-- a 経営管理 visa, J-visa attestation, or 事業所登記 supporting docs.
UPDATE am_subsidy_rule
   SET foreign_capital_eligibility = 'eligible_with_caveat'
 WHERE foreign_capital_eligibility = 'silent'
   AND (
        eligibility_cond_json LIKE '%在留資格%'
     OR eligibility_cond_json LIKE '%経営管理ビザ%'
     OR eligibility_cond_json LIKE '%日本国内に事業所%'
     OR eligibility_cond_json LIKE '%日本国内で登記%'
     OR eligibility_cond_json LIKE '%本店所在地が日本%'
   );

-- Case-by-case: explicit 「個別協議」「事務局判断」 wording
UPDATE am_subsidy_rule
   SET foreign_capital_eligibility = 'case_by_case'
 WHERE foreign_capital_eligibility = 'silent'
   AND (
        eligibility_cond_json LIKE '%個別協議%'
     OR eligibility_cond_json LIKE '%事務局判断%'
     OR eligibility_cond_json LIKE '%別途協議%'
   );

-- Eligible: the text explicitly confirms foreign capital OK (e.g.
-- JETRO Invest Japan, METI 対日直接投資 promotion programs).
UPDATE am_subsidy_rule
   SET foreign_capital_eligibility = 'eligible'
 WHERE foreign_capital_eligibility = 'silent'
   AND (
        eligibility_cond_json LIKE '%外資系も対象%'
     OR eligibility_cond_json LIKE '%外国資本も%'
     OR eligibility_cond_json LIKE '%対日直接投資%'
     OR eligibility_cond_json LIKE '%inward FDI%'
     OR eligibility_cond_json LIKE '%foreign capital%'
   );

-- All other rows remain 'silent' (default), which is the correct
-- Japanese statutory presumption: silence in the eligibility text
-- about foreign capital means the program does NOT discriminate, and
-- a foreign-owned KK with proper 経営管理 visa + 事業所 registration
-- can apply on the same footing as a domestic KK.
