-- FTS5 trigram for case_studies search
-- Replaces 4-column LIKE scan
-- audit: a889d3a849074d765 (2026-04-25)

CREATE VIRTUAL TABLE IF NOT EXISTS case_studies_fts USING fts5(
  case_id UNINDEXED,
  company_name,
  case_title,
  case_summary,
  source_excerpt,
  tokenize='trigram'
);

INSERT INTO case_studies_fts (case_id, company_name, case_title, case_summary, source_excerpt)
SELECT case_id, COALESCE(company_name, ''), COALESCE(case_title, ''), COALESCE(case_summary, ''), COALESCE(source_excerpt, '')
FROM case_studies;

-- Trigger: keep FTS in sync (insert / update / delete)
CREATE TRIGGER IF NOT EXISTS case_studies_fts_ai AFTER INSERT ON case_studies BEGIN
  INSERT INTO case_studies_fts (case_id, company_name, case_title, case_summary, source_excerpt)
  VALUES (NEW.case_id, COALESCE(NEW.company_name, ''), COALESCE(NEW.case_title, ''), COALESCE(NEW.case_summary, ''), COALESCE(NEW.source_excerpt, ''));
END;

CREATE TRIGGER IF NOT EXISTS case_studies_fts_au AFTER UPDATE ON case_studies BEGIN
  UPDATE case_studies_fts
    SET company_name=COALESCE(NEW.company_name, ''),
        case_title=COALESCE(NEW.case_title, ''),
        case_summary=COALESCE(NEW.case_summary, ''),
        source_excerpt=COALESCE(NEW.source_excerpt, '')
    WHERE case_id=NEW.case_id;
END;

CREATE TRIGGER IF NOT EXISTS case_studies_fts_ad AFTER DELETE ON case_studies BEGIN
  DELETE FROM case_studies_fts WHERE case_id=OLD.case_id;
END;
