-- j06_pdf_extraction_yield.sql
--
-- Purpose:  Per-source-id PDF yield for J06 (PDF/OCR extraction stage).
--           Counts PDF objects in object_manifest joined with the share of
--           those PDFs that produced at least one extracted claim_ref. A
--           low yield ratio signals the OCR pipeline is dropping PDFs.
-- Output:   source_id, pdf_count, total_pdf_mib, pdfs_with_claims,
--           yield_ratio.
-- Budget:   2 partition scans (object_manifest + claim_refs) ~30-80 MB.

WITH pdfs AS (
  SELECT
    source_id,
    content_sha256,
    content_length
  FROM jpcite_credit_2026_05.object_manifest
  WHERE run_id = :run_id
    AND content_type = 'application/pdf'
),
pdf_with_claims AS (
  SELECT DISTINCT
    sr.source_id,
    sr.content_sha256
  FROM jpcite_credit_2026_05.source_receipts sr
  JOIN jpcite_credit_2026_05.claim_refs cr
    ON cr.run_id = sr.run_id
  CROSS JOIN UNNEST(cr.source_receipt_ids) AS t(receipt_id)
  WHERE sr.run_id = :run_id
    AND cr.run_id = :run_id
    AND sr.content_sha256 = receipt_id
)
SELECT
  p.source_id,
  COUNT(*)                                                          AS pdf_count,
  ROUND(SUM(p.content_length) / 1024.0 / 1024.0, 3)                 AS total_pdf_mib,
  COUNT(pwc.content_sha256)                                         AS pdfs_with_claims,
  ROUND(1.0 * COUNT(pwc.content_sha256) / NULLIF(COUNT(*), 0), 4)   AS yield_ratio
FROM pdfs p
LEFT JOIN pdf_with_claims pwc
  ON pwc.content_sha256 = p.content_sha256
GROUP BY p.source_id
ORDER BY pdf_count DESC;
