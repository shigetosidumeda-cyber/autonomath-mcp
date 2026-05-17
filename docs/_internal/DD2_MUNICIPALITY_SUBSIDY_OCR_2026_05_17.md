# DD2 — Geo expansion: 1,714 市町村 補助金 PDF + Textract OCR (2026-05-17)

## TL;DR

DD2 closes the **G3 / G4 / G5 audit fan-out gap** (18 / 30 自治体 differential
fan-out required) by landing the structured 1,714 市町村 補助金 corpus on top
of the existing N4 ``am_window_directory`` (1,885 municipality rows) and the
DEEP-44 ``municipality_subsidy`` page-diff cron (67 自治体 1st pass).

| Item | Value |
| --- | --- |
| Target municipalities | **1,714** city / town / village / 東京 23区 (excludes designated city wards which roll up to parent 政令市) |
| Expected PDF total (avg) | 3 PDF / 自治体 → **5,142** |
| Worst-case PDF total | 5 PDF / 自治体 → **8,570** |
| Worst-case Textract spend (15 pg / PDF × $0.05) | **$6,427.50** (≪ $19,490 hard-stop) |
| Operator-stated cap | **$4,500** (set as ``--budget-usd`` default) |
| Crawl wall (1 req / 3 sec / host, 32 concurrent hosts) | 5-6 h |
| MCP tool | ``find_municipality_subsidies`` (4-axis cohort filter) |
| AWS regions | crawl/storage `ap-northeast-1`; Textract `ap-southeast-1` |

## Components landed (this PR)

1. **Migration** ``scripts/migrations/wave24_217_am_municipality_subsidy.sql``
   (+ rollback). Creates ``am_municipality_subsidy`` table (target_db=
   autonomath, 5 indexes, 2 views).
2. **Manifest builder**
   ``scripts/etl/build_dd2_municipality_manifest_2026_05_17.py``.
   Reads ``am_window_directory`` (1,885 munic rows), filters out designated-
   city wards (171), produces ``data/etl_dd2_municipality_manifest_2026_05_17
   .json`` (1,714 municipalities × 8 candidate subsidy-search seeds).
3. **Crawler**
   ``scripts/etl/crawl_municipality_subsidy_2026_05_17.py``. Async (httpx +
   asyncio), robots.txt-aware, 1 req / 3 sec per host throttle, aggregator
   banlist, primary-host regex. Stages PDFs to
   ``s3://jpcite-credit-993693061769-202605-derived/municipality_pdf_raw/<municipality_code>/<sha16>.pdf``.
   Idempotent SQLite ledger at ``data/dd2_crawl_ledger.sqlite``.
4. **Textract bulk runner**
   ``scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py``.
   Cross-region copy (Tokyo → Singapore staging) → Textract
   ``start_document_analysis`` (TABLES + FORMS) → outputs to
   ``s3://...-derived/municipality_ocr/<sha[:2]>/<sha>/``. Hard ``--budget-usd
   4500`` cap, warns at 80%. DRY_RUN default.
5. **Structured ingest**
   ``scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py``. Pure regex
   + 国税庁用語辞典 (built-in compact table). Extracts ``amount_yen_max`` /
   ``subsidy_rate`` / ``deadline`` (令和 wareki aware) / ``target_jsic_majors``
   / ``target_corporate_forms`` from Textract LINE blocks. Idempotent
   UNIQUE(``municipality_code``, ``program_name``, ``source_url``).
6. **MCP tool**
   ``src/jpintel_mcp/mcp/autonomath_tools/dd2_municipality_tools.py``.
   ``find_municipality_subsidies(prefecture, municipality_code, jsic_major,
   target_size)`` with 4-axis cohort filter. Returns top 20 rows with 5-axis
   citation (``subsidy_url`` + ``source_pdf_s3_uri`` + ``ocr_s3_uri`` +
   ``ocr_job_id`` + ``sha256``) + ``source_attribution`` envelope (政府著作物
   §13).
7. **Tests** ``tests/test_dd2_municipality_subsidy.py`` — 14 tests, all PASS
   (18 parametrised). Includes idempotent-migration, rollback, manifest
   integrity, crawler primary-host regex, Textract defaults, regex extractor
   self-tests, MCP envelope, invalid-arg envelopes, **NO LLM imports** guard
   over all 5 Python files, both views.

## Data flow (G3/G4/G5 unblock)

```
am_window_directory (N4, 1,885 munic)
        │
        ├─→ manifest builder ──→ data/etl_dd2_municipality_manifest_2026_05_17.json (1,714 munic)
        │                                  │
        │                                  ├─→ crawler ──→ s3://...derived/municipality_pdf_raw/
        │                                  │                       │
        │                                  │                       ├─→ Textract apse1 ──→ s3://...derived/municipality_ocr/
        │                                  │                       │                            │
        │                                  │                       │                            └─→ ingest ──→ am_municipality_subsidy (1,714+ rows)
        │                                  │                       │                                                    │
        │                                  │                       │                                                    ├─→ v_municipality_subsidy_by_prefecture
        │                                  │                       │                                                    └─→ v_municipality_subsidy_by_jsic_major
        │                                  │                       │                                                                          │
        │                                  │                       │                                                                          └─→ MCP find_municipality_subsidies
        │                                  │                       │                                                                                 (4-axis filter, 5-axis citation, 1×¥3/req)
```

## License posture

* Municipality 補助金 PDFs are 政府著作物 §13 — 編集 / 翻案 / 再配信 原則自由.
* Default ``license`` column value = ``public_domain_jp_gov``; the ingest
  step refines per row by URL host heuristic (jcci.or.jp → ``cc_by_4.0``;
  unknown 1次資料 fallback → ``gov_standard``).
* Aggregator hosts (noukaweb / hojyokin-portal / biz.stayway / stayway.jp /
  subsidies-japan / jgrant-aggregator / nikkei.com / prtimes.jp /
  wikipedia.org) are **banned** at both the manifest builder and the
  crawler runtime — CLAUDE.md データ衛生規約 §1.

## Cost envelope

The Textract bulk runner enforces three concentric guards:

1. **--budget-usd** hard cap (default $4,500). Stops cleanly when the
   *projected* next-job cost would exceed it.
2. **--warn-threshold** soft warning at 80% of cap.
3. The four AWS-side hard-stop tripwires (CW $14K / Budget $17K / slowdown
   $18.3K / Lambda kill $18.7K + Action deny $18.9K) remain primary
   defence — DD2 burn is a tiny fraction of the $19,490 Never-Reach line.

## Operating notes

* **Live AWS authorised** (operator UNLOCK). Wet run command:

      .venv/bin/python scripts/etl/crawl_municipality_subsidy_2026_05_17.py --commit
      .venv/bin/python scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py --commit
      .venv/bin/python scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py --commit

* **Rollback**: ``scripts/migrations/wave24_217_am_municipality_subsidy_rollback.sql``
  drops the table + views (idempotent).
* **MCP env-gate**: ``AUTONOMATH_DD2_MUNICIPALITY_ENABLED=0`` disables
  registration with one flag flip.
* **No LLM**: the constraint is enforced by
  ``test_no_llm_imports_in_dd2_files`` (parametrised over the 5 Python
  files); CI catches accidental re-introduction.

## Why this unblocks G3 / G4 / G5

Before DD2, the audit fan-out for ``programs_by_region_am`` /
``find_filing_window`` was bounded by ~67 自治体 (DEEP-44 1st pass) and the
window directory only carried address+phone+url, not structured subsidy
fields. DD2's ``am_municipality_subsidy`` adds the **structured (amount,
deadline, jsic_major, corporate_form, target_region) fan-out per
municipality** that the cohort cross-checks (G3 / G4 / G5) require.
