# Codex Plan-Only Stub Audit - AA1/AA2 OCR - 2026-05-17

Scope: read-only inspection in `/Users/shigetoumeda/jpcite-codex-evening` on branch `codex-evening-2026-05-17`.

Constraints honored: no live AWS commands, no implementation, no edits under `scripts/aws_credit_ops/`. This report is the only file intentionally written by this audit.

## Executive Finding

AA1 and AA2 row-count claims are not landed in the local `autonomath.db` checked in this workspace.

AA1's documented `+11,155` target remains plan-only relative to the local DB. The local NTA legacy tables still match the documented baseline (`nta_shitsugi=286`, `nta_bunsho_kaitou=278`, `nta_saiketsu=137`), while the requested new AA1 tables `am_nta_qa` and `am_chihouzei_tsutatsu` do not exist and `am_tax_amendment_history` has `0` rows.

AA2's `4,000` claim is not supported by the requested DB tables. `am_accounting_standard`, `am_audit_standard`, and `am_internal_control_case` total `113` rows, leaving a `3,887` row gap against 4,000.

## Target Script Availability

| Requested path | Present? | Finding |
|---|---:|---|
| `scripts/etl/crawl_nta_corpus_2026_05_17.py` | yes | Plan/runbook orchestrator with placeholders; does not perform DB ingest or S3 staging itself. |
| `scripts/etl/textract_nta_bulk_2026_05_17.py` | no | Exact requested ETL path is absent. A similarly named file exists at `scripts/aws_credit_ops/textract_nta_bulk_2026_05_17.py` and was inspected read-only as adjacent evidence. |
| `scripts/etl/textract_kaikeishi_bulk_2026_05_17.py` | no | Exact requested AA2/kaikeishi OCR path is absent. No exact kaikeishi bulk Textract script was found. |

## `crawl_nta_corpus_2026_05_17.py`

Finding: plan-only stub/orchestrator, not an implementation that lands AA1 rows.

Evidence:

- Default `--dry-run` is true; `--commit` toggles the flag, but the delegated ingest path still only logs a would-execute line and returns stats.
- `_delegate_to_existing_ingest()` explicitly does not call `subprocess`; it records/logs the intended `scripts/ingest/ingest_nta_corpus.py` invocation.
- `_crawl_chihouzei_pref()` contains an explicit real-crawl placeholder. In non-dry-run mode it increments no fetched/inserted counts and only sleeps.
- `g8_tax_amendment_history` has no execution branch. It falls through to an empty `CrawlStats` object.
- `--commit-s3` is parsed but not used by any S3 client or upload path.
- `_check_robots_txt()` and `_fetch_url()` are defined, but this script's `main()` does not call them.
- The only write side effect in this script is optional `--summary-output`, which writes JSON and creates parent directories. Normal execution prints JSON/logs only.

Side-effect summary:

| Mode | Network | DB writes | AWS/S3/Textract | Local writes |
|---|---:|---:|---:|---:|
| default dry-run | no | no | no | only if `--summary-output` is supplied |
| `--commit` | no effective crawl/ingest | no | no | only if `--summary-output` is supplied |

## Adjacent NTA Textract Stub

Inspected read-only: `scripts/aws_credit_ops/textract_nta_bulk_2026_05_17.py`.

Finding: this file is also plan-only. It is not the requested `scripts/etl/...` path, and it does not submit live Textract jobs even when `--commit` is passed.

Evidence:

- `_enumerate_pdf_candidates()` creates synthetic PDF jobs from manifest estimates instead of querying DB rows or discovering real PDFs.
- Dry-run assigns S3 key strings and fake `dry_run_...` job IDs.
- Non-dry-run branch logs `would-submit`, sets status `WOULD_SUBMIT_LIVE`, and does not import `boto3` or call S3/Textract.
- It always writes a ledger through `_write_ledger()` to `data/textract_nta_bulk_2026_05_17_ledger.json` by default, creating parent directories if needed.

Side-effect summary:

| Mode | Network | DB writes | AWS/S3/Textract | Local writes |
|---|---:|---:|---:|---:|
| default dry-run | no | no | no | ledger JSON |
| `--commit` | no | no | no | ledger JSON; sleeps between would-submit rows |

## AA2/Kaikeishi OCR Stub

Finding: no requested `scripts/etl/textract_kaikeishi_bulk_2026_05_17.py` exists in this repo checkout. Therefore there is no AA2 OCR stub at the requested path to execute, audit for live side effects, or credit toward the AA2 `4,000` row claim.

The repo does contain AA2/G2 planning docs and data references, but not the requested OCR submitter.

## Reference Executors - Read-Only

### `scripts/ingest/ingest_nta_corpus.py`

This is a real executor, not a plan-only stub.

If run directly, it can:

- Fetch NTA/KFS URLs over the network.
- Open and mutate `autonomath.db`.
- Set SQLite pragmas including WAL mode.
- `INSERT OR IGNORE` into `nta_saiketsu`, `nta_shitsugi`, `nta_bunsho_kaitou`, and `nta_tsutatsu_index`.
- Write cursor files under `data/autonomath/`.

The audited crawler does not invoke it; it only prints/logs the canonical commands.

### `scripts/aws_credit_ops/textract_bulk_submit_2026_05_17.py`

This is the live bulk Textract executor, separate from the NTA plan-only stub.

Default behavior without `--commit`:

- Does not download PDFs.
- Does not create AWS clients.
- Does not call S3 or Textract.
- Writes a ledger JSON.

With `--commit`, it can:

- Import `boto3`.
- Create S3 and Textract clients.
- Download public PDFs over HTTP.
- Call `head_object` and `put_object` on S3.
- Call Textract `start_document_analysis`.
- Write/update a local ledger JSON every 10 PDFs and at completion.

No live AWS path was run during this audit.

## DB Count Audit

Read-only SQLite queries were run with `sqlite3 -readonly autonomath.db`.

Requested tables:

| Table | `SELECT COUNT(*)` result |
|---|---:|
| `am_nta_qa` | table missing (`no such table`) |
| `am_chihouzei_tsutatsu` | table missing (`no such table`) |
| `am_tax_amendment_history` | 0 |
| `am_accounting_standard` | 31 |
| `am_audit_standard` | 61 |
| `am_internal_control_case` | 21 |

Additional legacy/context counts:

| Table | Count |
|---|---:|
| `nta_shitsugi` | 286 |
| `nta_bunsho_kaitou` | 278 |
| `nta_saiketsu` | 137 |
| `am_nta_tsutatsu_extended` | 0 |

## Claim Comparison

### AA1 claim: `+11,155` rows

Source claim appears in `docs/_internal/AA1_G1_NTA_ETL_2026_05_17.md` as total new rows `+11,155`, with targets including:

- `nta_bunsho_kaitou`: `+322`
- `nta_saiketsu`: `+3,163`
- `am_nta_qa`: `+2,150`
- `am_chihouzei_tsutatsu`: `+4,800`
- `am_tax_amendment_history`: `+720`

Actual local DB evidence:

- `am_nta_qa` table is absent.
- `am_chihouzei_tsutatsu` table is absent.
- `am_tax_amendment_history` exists but has `0` rows.
- Legacy counts are still the documented baseline: `286 + 278 + 137 = 701`.

Conclusion: AA1's `+11,155` is not landed in this local DB. Actual landed rows against the requested new AA1 tables are `0`.

### AA2 claim: `4,000` rows

Using the requested AA2 tables as the comparison surface:

| Table | Count |
|---|---:|
| `am_accounting_standard` | 31 |
| `am_audit_standard` | 61 |
| `am_internal_control_case` | 21 |
| **Actual AA2 total** | **113** |

Conclusion: AA2's `4,000` claim is not supported by the local DB. Actual requested-table total is `113`, a deficit of `3,887`.

## Final Assessment

The audited AA1 crawl/OCR surfaces are plan-only and ledger/runbook oriented. They do not land the claimed rows in `autonomath.db` and do not submit live OCR jobs by themselves. The true side-effecting executors are separate (`scripts/ingest/ingest_nta_corpus.py` and `scripts/aws_credit_ops/textract_bulk_submit_2026_05_17.py`) and were only inspected read-only.
