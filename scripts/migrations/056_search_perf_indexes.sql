-- Search performance indexes
-- audit: a889d3a849074d765 (2026-04-25)

-- P0: enforcement.search ministry path
CREATE INDEX IF NOT EXISTS idx_enforcement_ministry
  ON enforcement_cases(ministry);

-- P1: composite sort indexes (eliminates USE TEMP B-TREE FOR ORDER BY)
CREATE INDEX IF NOT EXISTS idx_enforcement_disclosed_desc
  ON enforcement_cases(disclosed_date DESC, case_id);

CREATE INDEX IF NOT EXISTS idx_case_studies_pubdate
  ON case_studies(publication_date DESC, case_id);

CREATE INDEX IF NOT EXISTS idx_loan_programs_amount_desc
  ON loan_programs(amount_max_yen DESC, id);

-- P1: programs FTS post-dedup ORDER BY
CREATE INDEX IF NOT EXISTS idx_programs_tier_name
  ON programs(tier, primary_name);

ANALYZE enforcement_cases;
ANALYZE case_studies;
ANALYZE loan_programs;
ANALYZE programs;
