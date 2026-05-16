-- program_lineage_join.sql
--
-- Purpose:  Aggregate "lineage coverage" per program across the 6-source
--           chain (programs → law_refs → laws → tsutatsu → saiketsu →
--           court_decisions + amendment_diff). Mirrors the local-SQLite
--           join performed by
--           scripts/aws_credit_ops/generate_program_lineage_packets.py
--           so a downstream Athena scan can confirm packet coverage
--           against the Glue-cataloged Parquet without re-reading the
--           originating SQLite DBs.
--
-- Output:   one row per program with the count of citations surfaced
--           per chain axis + a weighted coverage_score that reuses the
--           same (0.6 * claim + 0.4 * freshness) formula as the Python
--           assembler (see generate_program_lineage_packets.coverage_score).
--
-- Budget:   FULL TABLE SCAN across all partitions of the 6 derived
--           tables. Pin to a single run_id partition where possible.
--           Typical full scan sits at 600 MB - 1.4 GB across all
--           partitions; constrain on `:run_id` (LIKE) to keep within
--           the workgroup ¥budget envelope.
--
-- Param:    optional `:run_id_filter` LIKE expression (default '%' for all).
--           Bind as `'2026-05-%'` to scope to a single month.
--
-- Athena workgroup: jpcite-credit-2026-05
-- target_database:  jpcite_credit_2026_05

WITH
program_rows AS (
  -- programs table: jpcite_credit_2026_05.programs (object_id == program_unified_id)
  SELECT
    o.subject_id        AS program_unified_id,
    o.value             AS primary_name,
    o.run_id
  FROM jpcite_credit_2026_05.claim_refs o
  WHERE o.subject_kind = 'program' AND o.claim_kind = 'primary_name'
),
law_basis AS (
  -- legal_basis_chain — claim_refs subject_kind='program', claim_kind='law_ref'
  SELECT
    c.subject_id        AS program_unified_id,
    COUNT(*)            AS legal_basis_count,
    MAX(c.confidence)   AS max_confidence,
    AVG(c.confidence)   AS avg_confidence,
    c.run_id
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'program' AND c.claim_kind = 'law_ref'
  GROUP BY c.subject_id, c.run_id
),
notice_chain AS (
  -- notice_chain — claim_refs subject_kind='law', claim_kind='tsutatsu'
  SELECT
    c.subject_id        AS law_unified_id,
    COUNT(*)            AS notice_count,
    c.run_id
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'law' AND c.claim_kind = 'tsutatsu'
  GROUP BY c.subject_id, c.run_id
),
saiketsu_chain AS (
  -- saiketsu_chain — claim_refs subject_kind='program', claim_kind='saiketsu'
  SELECT
    c.subject_id        AS program_unified_id,
    COUNT(*)            AS saiketsu_count,
    c.run_id
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'program' AND c.claim_kind = 'saiketsu'
  GROUP BY c.subject_id, c.run_id
),
precedent_chain AS (
  -- precedent_chain — claim_refs subject_kind='program', claim_kind='court_decision'
  SELECT
    c.subject_id        AS program_unified_id,
    COUNT(*)            AS precedent_count,
    c.run_id
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'program' AND c.claim_kind = 'court_decision'
  GROUP BY c.subject_id, c.run_id
),
amendment_timeline AS (
  -- amendment_timeline — claim_refs subject_kind='program', claim_kind='amendment_diff'
  SELECT
    c.subject_id        AS program_unified_id,
    COUNT(*)            AS amendment_count,
    MAX(c.value)        AS latest_detected_at,
    c.run_id
  FROM jpcite_credit_2026_05.claim_refs c
  WHERE c.subject_kind = 'program' AND c.claim_kind = 'amendment_diff'
  GROUP BY c.subject_id, c.run_id
),
freshness_stamps AS (
  -- source_receipts.source_fetched_at — fraction of dated rows recent
  SELECT
    s.source_id,
    s.source_fetched_at,
    s.run_id
  FROM jpcite_credit_2026_05.source_receipts s
)
SELECT
  p.run_id,
  p.program_unified_id,
  p.primary_name,
  COALESCE(lb.legal_basis_count, 0)                  AS legal_basis_count,
  COALESCE(nc.notice_count, 0)                       AS notice_count,
  COALESCE(sc.saiketsu_count, 0)                     AS saiketsu_count,
  COALESCE(pc.precedent_count, 0)                    AS precedent_count,
  COALESCE(at.amendment_count, 0)                    AS amendment_count,
  -- claim_coverage = fraction of {legal_basis, notice, saiketsu, precedent} >= 1
  ( (CASE WHEN COALESCE(lb.legal_basis_count, 0) > 0 THEN 1 ELSE 0 END)
   + (CASE WHEN COALESCE(nc.notice_count,      0) > 0 THEN 1 ELSE 0 END)
   + (CASE WHEN COALESCE(sc.saiketsu_count,    0) > 0 THEN 1 ELSE 0 END)
   + (CASE WHEN COALESCE(pc.precedent_count,   0) > 0 THEN 1 ELSE 0 END)
  ) / 4.0                                            AS claim_coverage,
  -- freshness_coverage proxy = share of source_receipts rows whose stamp
  -- is within 365 days. Same band as the Python assembler.
  COALESCE(
    (SELECT COUNT(*) FROM freshness_stamps f
       WHERE f.run_id = p.run_id
         AND f.source_fetched_at >= date_format(date_add('day', -365, current_date), '%Y-%m-%dT00:00:00Z')
    ) * 1.0 /
    NULLIF((SELECT COUNT(*) FROM freshness_stamps f2 WHERE f2.run_id = p.run_id), 0)
  , 0.0)                                             AS freshness_coverage,
  -- weighted score: 0.6 * claim + 0.4 * freshness (mirrors Python W_CLAIM/W_FRESHNESS)
  ROUND(
    0.6 * (
      ( (CASE WHEN COALESCE(lb.legal_basis_count, 0) > 0 THEN 1 ELSE 0 END)
       + (CASE WHEN COALESCE(nc.notice_count,    0) > 0 THEN 1 ELSE 0 END)
       + (CASE WHEN COALESCE(sc.saiketsu_count,  0) > 0 THEN 1 ELSE 0 END)
       + (CASE WHEN COALESCE(pc.precedent_count, 0) > 0 THEN 1 ELSE 0 END)
      ) / 4.0
    )
    + 0.4 * COALESCE(
        (SELECT COUNT(*) FROM freshness_stamps f
           WHERE f.run_id = p.run_id
             AND f.source_fetched_at >= date_format(date_add('day', -365, current_date), '%Y-%m-%dT00:00:00Z')
        ) * 1.0 /
        NULLIF((SELECT COUNT(*) FROM freshness_stamps f2 WHERE f2.run_id = p.run_id), 0)
      , 0.0)
  , 4)                                               AS coverage_score
FROM program_rows p
LEFT JOIN law_basis           lb ON lb.program_unified_id = p.program_unified_id AND lb.run_id = p.run_id
LEFT JOIN notice_chain        nc ON nc.law_unified_id     = lb.program_unified_id AND nc.run_id = p.run_id
LEFT JOIN saiketsu_chain      sc ON sc.program_unified_id = p.program_unified_id AND sc.run_id = p.run_id
LEFT JOIN precedent_chain     pc ON pc.program_unified_id = p.program_unified_id AND pc.run_id = p.run_id
LEFT JOIN amendment_timeline  at ON at.program_unified_id = p.program_unified_id AND at.run_id = p.run_id
WHERE p.run_id LIKE :run_id_filter
ORDER BY coverage_score DESC, p.program_unified_id ASC;
