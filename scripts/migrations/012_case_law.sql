-- 012_case_law.sql
-- Adds `case_law` table for the 49_case_law_judgments drop
-- (courts.go.jp hanrei). These are judicial rulings, not programs —
-- consumers use them to check legal precedent before advising clients.
--
-- Natural uniqueness: (case_number, court). 最高裁 + 下級裁 share the
-- case_number space only when re-heard on appeal, so pinning both
-- dimensions keeps us idempotent without forcing a synthetic PK on
-- upstream. We still carry a surrogate id for consumer-side pagination.
--
-- `confidence` here is TEXT ("high"/"medium"/...) not a REAL —
-- courts.go.jp doesn't expose a numeric confidence. Other tables in
-- 011 use REAL because their upstream (agent-generated) does.

CREATE TABLE IF NOT EXISTS case_law (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_name TEXT NOT NULL,
    court TEXT,
    decision_date TEXT,
    case_number TEXT,
    subject_area TEXT,
    key_ruling TEXT,
    parties_involved TEXT,
    impact_on_business TEXT,
    source_url TEXT,
    source_excerpt TEXT,
    confidence TEXT,
    pdf_url TEXT,
    category TEXT,
    fetched_at TEXT,
    UNIQUE(case_number, court)
);

CREATE INDEX IF NOT EXISTS idx_case_law_court ON case_law(court);
CREATE INDEX IF NOT EXISTS idx_case_law_subject_area ON case_law(subject_area);
CREATE INDEX IF NOT EXISTS idx_case_law_decision_date ON case_law(decision_date);
CREATE INDEX IF NOT EXISTS idx_case_law_category ON case_law(category);
