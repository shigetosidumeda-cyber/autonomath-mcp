# AWS credit review 12/20: CSV privacy pipeline and accounting private overlay

Date: 2026-05-15  
Review lane: CSV privacy / accounting data expansion  
Scope: pre-AWS-execution plan only. No AWS command execution.  
Target account context: jpcite AWS credit run, J14 CSV private overlay safety analysis.

## 0. Executive verdict

CSV import makes jpcite materially more valuable, but only if it is treated as **private operational input**, not as a public source.

The right product shape is:

1. AI agent asks the end user for a freee / MoneyForward / Yayoi CSV only when a CSV-derived artifact is useful.
2. jpcite analyzes the CSV in a preview flow without retaining raw bytes, raw rows, row-level normalized records, memo text, counterparty values, voucher IDs, creator/updater names, payroll/person/bank/card values, or exact sensitive identifiers.
3. jpcite emits only aggregate derived facts, review codes, provider/format profile, k-safe summaries, safe public join candidates, and known gaps.
4. Public/official source facts remain source-backed through `source_receipts[]`.
5. CSV-derived facts stay in a tenant/private namespace and are never promoted into the public claim namespace, public proof pages, JSON-LD, llms files, OpenAPI public examples, or GEO surfaces.

This is stronger than "cache data and use it." The defensible value is a **prebuilt artifact factory** that converts private CSV shape into safe next actions and source-backed public joins.

## 1. Inputs reviewed

Local CSV directory:

- `/Users/shigetoumeda/Desktop/CSV/freee_personal_freelance.csv`
- `/Users/shigetoumeda/Desktop/CSV/freee_personal_rental.csv`
- `/Users/shigetoumeda/Desktop/CSV/freee_sme_agri.csv`
- `/Users/shigetoumeda/Desktop/CSV/freee_sme_welfare.csv`
- `/Users/shigetoumeda/Desktop/CSV/mf_sme_medical.csv`
- `/Users/shigetoumeda/Desktop/CSV/mf_sme_subsidy.csv`
- `/Users/shigetoumeda/Desktop/CSV/yayoi_apple_farm.csv`
- `/Users/shigetoumeda/Desktop/CSV/conglomerate_yayoi.csv`
- `/Users/shigetoumeda/Desktop/CSV/media_conglomerate_yayoi.csv`

Existing planning docs reviewed:

- `consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `csv_accounting_outputs_deepdive_2026-05-15.md`
- `csv_output_catalog_by_user_type_deepdive_2026-05-15.md`
- `csv_provider_fixture_aliases_deepdive_2026-05-15.md`
- `csv_privacy_edge_cases_deepdive_2026-05-15.md`
- `security_privacy_csv_deepdive_2026-05-15.md`
- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_security_privacy_agent.md`
- `aws_credit_outputs_agent.md`
- `aws_credit_data_acquisition_jobs_agent.md`

Official format references checked for this review:

- freee help: `https://support.freee.co.jp/hc/ja/articles/202847920-...freee形式を用いた方法`
- Money Forward support: `https://biz.moneyforward.com/support/account/guide/import-books/ib01.html`
- Yayoi support: `https://support.yayoi-kk.co.jp/subcontents.html?page_id=18545`
- Yayoi online import format reference: `https://support.yayoi-kk.co.jp/subcontents.html?page_id=27184`

## 2. Official-format assessment of the provided CSVs

The supplied CSVs are useful as observed provider fixtures, but they must not all be labeled official-compliant.

| Family | Observed local shape | Official-format decision | Product handling |
|---|---|---|---|
| freee | 4 files, UTF-8 BOM, 21 columns, `取引日`, `伝票番号`, debit/credit account, item, memo tag, counterparty, tax, amount, memo | Not current official freee import template. Current official freee import lane uses the freee-specific template shape such as title/detail row handling and `伝票No.` style. | Classify as `freee_desktop_observed_21_export_like`, `format_class=variant`. Parse via aliases, but never call official-compliant. |
| Money Forward | 2 files, UTF-8 BOM, 25 columns, `取引No`, `取引日`, account, counterparty, tax, amount, memo, tags, MF type, closing flag, created/updated meta | Not current official 27-column import shape because the current official journal import includes invoice-class columns such as debit/credit invoice fields. | Classify as `mf_pre_invoice_25_legacy`, `format_class=old_format`. Parse safely and emit current-diff review code. |
| Yayoi | 3 files, cp932, 25 columns, `識別フラグ`, `取引日付`, debit/credit account, tax category, tax amount, memo, type/source/sticky/adjustment | Matches Yayoi 05+ 25-field positional family, with `伝票No.` vs `伝票No` header variation. | Classify exact-dot version as `yayoi_official_05plus_25_cp932`; no-dot as `yayoi_header_no_dot_variant`. Accept alias to `voucher_id` but keep warning. |

Implementation implication:

- Provider detection should be separate from official compliance.
- Alias mapping can unlock aggregation, but aliases must not upgrade a variant or old format into official-compliant.
- The user-facing output can say "freee-like / MF-like / Yayoi-like provider profile detected" and "current official template difference detected"; it should not imply the file is import-valid for that vendor.

## 3. Immutable privacy contract

The following are forbidden in persistent storage, logs, public artifacts, examples, debug output, support output, prompts, OpenSearch, Athena query results, Bedrock/Textract input, public proof pages, MCP examples, and OpenAPI examples:

- CSV raw bytes
- raw rows
- row-level normalized records
- row samples
- memo / 摘要 / 仕訳メモ / 付箋 / tags as values
- counterparty, customer, supplier, employee, patient, user, creator, updater, author values
- voucher IDs / transaction IDs / invoice IDs as raw values
- bank account, card, payroll, personal ID, phone, email, address values
- formula-like cell values beginning with `=`, `+`, `-`, `@`, tab, or CR/LF formula payload
- exact small-cell aggregates that reconstruct a row or person

Allowed persistent/output substitutes:

- `row_count`
- `column_count`
- `encoding_detected`
- `provider_family`
- `provider_fingerprint`
- `format_class`
- normalized header alias map
- `raw_column_profile_hash`
- presence flags
- redacted/suppressed/rejected counts
- month/quarter/year range, if k-safe
- account light classes, if k-safe
- aggregate amount buckets, if k-safe
- review codes
- tenant-scoped internal HMAC only for dedupe/idempotency, never public hash
- source-backed public facts joined from exact public identifiers

## 4. Pipeline design

### 4.1 Three-stage user flow

1. Analyze
   - Free or low-cost.
   - Reads CSV transiently.
   - Returns provider/format profile, row/column count, date range if safe, required/missing fields, rejection status, review codes, and privacy posture.
   - No packet generation, no raw echo, no billing for rejected files.

2. Preview
   - Returns candidate artifacts, estimated billable units, cap requirement, accepted/rejected/duplicate/unresolved counts, and known gaps.
   - Still no row values and no source-backed public claim unless public source lookup is requested with exact IDs.

3. Execute
   - Requires API key, idempotency key, and cost cap for paid/broad work.
   - Generates only aggregate/private-safe artifacts and public source receipt joins.
   - Rejected rows/files, unsupported requests, idempotency conflicts, and cap failures are not billed.

### 4.2 Processing stages

| Stage | Work | Persistable output | Hard stop |
|---|---|---|---|
| Intake | byte size, encoding, dialect, content-type, row/column caps | shape only | invalid encoding, too large, binary, unsupported type |
| Provider profile | fingerprint freee/MF/Yayoi/unknown | provider family, class, alias map, profile hash | conflicting provider signals |
| Sensitive scan | header cluster and transient cell scan | reject codes, redacted counts, sensitive flags | payroll/person/bank/card/ID clusters |
| Alias normalization | map date/account/tax/amount/vendor meta | alias report only | missing date/account/amount essentials |
| Transient row parse | in-memory only | none | parse failure above threshold |
| Aggregation | month/account/class/review facts | k-safe aggregates | small-cell or dominant contributor risk |
| Public join | exact identifier or candidate-only matching | public `source_receipts[]`, join confidence, known gaps | name-only claim presented as identity |
| Packet generation | contract envelope | aggregate/private facts + public receipts | unsupported professional judgment request |
| Leak scan | static and dynamic scan | pass/fail report | private value in output/log/artifact |

## 5. Provider adapters

### 5.1 freee adapter

Observed local shape:

- `entry_date`: `取引日`
- `voucher_id`: `伝票番号`
- debit/credit account, subaccount, department, item, memo tag, counterparty, tax category, tax amount, amount
- memo: `摘要`

Handling:

- Classify local files as `variant`, not official-compliant.
- Treat item, memo tag, counterparty, and memo values as non-exportable.
- Persist only presence flags, distinct counts under k rules, and account vocabulary aggregates.
- Owner-related accounts such as personal business vocabulary should produce `owner_related_present=true`, not tax conclusions.

### 5.2 Money Forward adapter

Observed local shape:

- `entry_date`: `取引日`
- `voucher_id`: `取引No`
- amount columns with `(円)` suffix
- audit metadata: `MF仕訳タイプ`, `決算整理仕訳`, `作成日時`, `作成者`, `最終更新日時`, `最終更新者`
- no current invoice-class columns in the observed two files

Handling:

- Classify as `old_format` / `mf_pre_invoice_25_legacy`.
- Emit `mf_pre_invoice_legacy_columns` review code.
- Creator/updater values are redacted; only `audit_meta_present=true` and coarse counts are allowed.
- Closing-entry flags become review conditions, not accounting correctness claims.

### 5.3 Yayoi adapter

Observed local shape:

- cp932
- 25-column Yayoi family
- `entry_date`: `取引日付`
- tax amount labels use `税金額`
- metadata includes `識別フラグ`, `決算`, `番号`, `期日`, `タイプ`, `生成元`, `仕訳メモ`, `付箋1`, `付箋2`, `調整`

Handling:

- Exact `伝票No.` can be official-compliant if the rest of the positional contract matches.
- `伝票No` without dot is a known variant and aliases to `voucher_id` with warning.
- `付箋`, `調整`, `生成元`, `タイプ` become review metadata presence counts only.
- Headerless positional Yayoi fixtures should be supported later with strict row-width and identifier checks.

## 6. CSV type differences that must be modeled

Not every CSV from freee/MF/Yayoi is a journal CSV. The intake layer must route by file type, not only provider brand.

| CSV type | Examples | P0 support | Reason |
|---|---|---|---|
| Journal /仕訳帳 | debit/credit account, date, amount pairs | Supported | Core private overlay source for aggregate artifacts. |
| Account ledger /総勘定元帳 | account-focused with counterpart fields | Conditional | Can map to aggregates if raw counterparties are dropped. |
| Bank/card statement | bank/card transaction lines, merchant/payee details | Reject or future local-only | High private leakage and payment identifiers. |
| Bank transfer file | bank, branch, account, account holder, transfer amount | Reject | Critical banking data. |
| Payroll/personnel | employee names, salary, withholding, social insurance | Reject | Critical personal data. |
| Invoice/billing CSV | invoice no, customer, billing line items | P1 only with strict schema | Customer relationship and invoice IDs are high risk. |
| Customer/supplier master | names, addresses, emails, T numbers | P1 only with explicit exact identifier lane | Useful for public joins, but raw names/contact info are sensitive. |
| Generic accounting export | date/account/amount only | Supported as unknown/generic if required fields map | Provider-specific claims disabled. |

## 7. Derived fact schemas

### 7.1 `private_csv_file_profile`

```json
{
  "profile_id": "tenant_scoped_hmac",
  "source_kind": "accounting_csv_private_overlay",
  "provider_family": "freee|money_forward|yayoi|generic|unknown",
  "provider_fingerprint": "freee_desktop_observed_21_export_like",
  "format_class": "official_compliant|old_format|variant|unknown",
  "encoding_detected": "utf-8-sig|utf-8|cp932|shift_jis|unknown",
  "row_count": 0,
  "column_count": 0,
  "raw_column_profile_hash": "sha256:normalized_header_order",
  "date_range_bucket": "month|quarter|year|unknown",
  "first_period": "YYYY-MM|null",
  "last_period": "YYYY-MM|null",
  "raw_retention": "none",
  "row_level_retention": "none",
  "human_review_required": true,
  "review_codes": []
}
```

### 7.2 `private_csv_aggregate_fact`

```json
{
  "profile_id": "tenant_scoped_hmac",
  "aggregation_level": "file|quarter|month|account_class|account_class_period|provider_meta",
  "period_bucket": "YYYY-MM|YYYY-Qn|YYYY|null",
  "account_light_class": "revenue|expense|asset|liability|equity_or_owner|grant_or_subsidy_like|payroll_related|industry_specific|unknown|null",
  "entry_count": 0,
  "amount_bucket": "rounded_or_suppressed",
  "tax_amount_bucket": "rounded_or_suppressed",
  "distinct_account_count_bucket": "bucketed",
  "department_presence": true,
  "counterparty_field_present": true,
  "memo_field_present": true,
  "suppressed": false,
  "suppression_reasons": []
}
```

### 7.3 `private_csv_review_fact`

```json
{
  "profile_id": "tenant_scoped_hmac",
  "severity": "info|warning|blocker",
  "condition_code": "future_date_present|missing_required_column|debit_credit_total_mismatch|provider_current_diff|small_cell_suppressed",
  "observed_count_bucket": "0|1-2|3-9|10-49|50+",
  "observed_scope": "file|period|account_class|column",
  "human_message_ja": "CSVの入力条件として確認が必要です。",
  "not_a_tax_or_accounting_opinion": true
}
```

### 7.4 `public_join_candidate`

```json
{
  "candidate_id": "uuid",
  "input_basis": "houjin_bangou|invoice_registration_number|edinet_code|company_name_address_candidate|industry_hint|program_name_hint",
  "private_input_exposed": false,
  "join_type": "exact|candidate|hint_only",
  "public_source_targets": ["nta_houjin", "nta_invoice", "jgrants", "gbizinfo", "estat", "edinet"],
  "confidence": "high|medium|low",
  "source_receipt_ids": [],
  "known_gaps": []
}
```

### 7.5 `private_overlay_receipt`

This is not a public source receipt. It is an internal evidence marker that a packet used private aggregate facts.

```json
{
  "receipt_id": "priv_csv_...",
  "receipt_type": "private_csv_derived_aggregate",
  "profile_id": "tenant_scoped_hmac",
  "raw_retention": "none",
  "row_level_retention": "none",
  "allowed_surface": "tenant_packet_only",
  "public_promotion_allowed": false,
  "derived_fact_ids": [],
  "suppression_policy_version": "2026-05-15",
  "human_review_required": true
}
```

## 8. Public-source join design

### 8.1 Allowed joins

| Input | Join posture | Output |
|---|---|---|
| 法人番号 | Exact | NTA法人番号 receipt, company identity baseline, gBizINFO/EDINET bridge when available. |
| T番号 | Exact for invoice registry | NTAインボイス positive/no-hit receipt. Individual proprietor T numbers are not converted to法人番号. |
| EDINET code / JCN | Exact where available | EDINET metadata and public filing bridge. |
| Company name + address from explicit profile | Candidate | Candidate list with tie-breakers and `name_only_or_address_candidate` gap. |
| CSV account vocabulary industry hint | Hint only | jGrants/e-Stat/public program candidate reasons, never eligibility. |
| Program name from user input | Candidate/exact depending source | Public program receipts and stale/deadline gaps. |
| Counterparty name inside CSV | Not P0 public join | Output only `counterparty_field_present`; do not join raw names to public records. |

### 8.2 Source families useful for CSV overlay

| Public source | CSV-derived use | Safe claim |
|---|---|---|
| NTA法人番号 | Confirm company identity when exact法人番号 is supplied | "Official registry has a matching corporation record as of snapshot." |
| NTAインボイス | Confirm invoice registration when T number supplied | "This lookup found/not found a registration in the checked snapshot." |
| J-Grants / public programs | Map industry/investment hints to candidate programs | "Candidate program to review; eligibility not determined." |
| gBizINFO | Public certifications/subsidy/procurement signals | "Public business signal exists in source; not a performance or credit conclusion." |
| e-Stat | Regional/industry context | "Regional statistical context; not company-specific performance." |
| EDINET | Public filer metadata for listed/filing entities | "Public filing metadata exists; not audited by jpcite." |
| p-portal / JETRO procurement | Procurement candidate context | "Public tender/procurement source candidate." |
| e-Gov law | Legal basis references | "Relevant law/source passage for human review; not legal advice." |
| Local government PDFs | Local program/tender candidates | "Extracted candidate requiring freshness and terms review." |

### 8.3 Join confidence rules

Use this scoring only for routing and explanation. Do not present it as correctness probability.

```text
base = 0
if exact_houjin_bangou: base += 80
if exact_invoice_registration_number: base += 70
if exact_edinet_code_or_jcn: base += 70
if company_name_normalized_match: base += 25
if address_prefecture_city_match: base += 20
if source_snapshot_fresh: base += 10
if multiple_same_name_candidates: base -= 30
if name_only: cap at 45
if CSV-only counterparty value: reject P0 public join
```

Confidence classes:

- `high`: exact official identifier and source receipt present.
- `medium`: candidate with enough tie-breakers but still human review.
- `low`: hint-only or name-only; route to known gaps and recommended follow-up.

No-hit rule:

- `no_hit` means "not found in this source/snapshot/query", never "does not exist", "safe", "not registered anywhere", "no risk", or "eligible/ineligible".

## 9. Algorithms to implement before/around AWS J14

### 9.1 Provider fingerprint classifier

Inputs:

- normalized header sequence
- encoding
- delimiter/quote style
- provider-exclusive tokens
- required date/account/amount aliases

Outputs:

- `provider_family`
- `provider_fingerprint`
- `format_class`
- `review_codes`
- `canonical_aliases`
- `raw_column_profile_hash`

Key invariant:

```text
provider detected != official compliant
alias compatible != import valid
unknown provider != unusable CSV
```

### 9.2 Account light classification

Purpose:

- Convert raw account labels into broad routing classes without tax/accounting judgment.

Classes:

- `revenue`
- `expense`
- `asset`
- `liability`
- `equity_or_owner`
- `grant_or_subsidy_like`
- `payroll_related`
- `bank_or_financing_related`
- `fixed_asset_or_investment_like`
- `industry_specific`
- `unknown`

Rules:

- Preserve original account labels only inside tenant-private aggregate views when k-safe.
- Public examples should use synthetic labels or coarse classes.
- Do not say the account is correct, deductible, taxable, capitalized, eligible, or compliant.

### 9.3 Period coverage quality

Useful metrics:

- first/last period
- number of months covered
- empty month count
- future-date count bucket
- out-of-range period count bucket
- closing/adjustment metadata presence
- parse-failure bucket

Score:

```text
period_quality = 100
- 25 if required date column missing
- 20 if parse failure affects aggregation
- 15 if future-date bucket > 0
- 10 if empty months exist inside range
- 10 if accounting period crosses expected fiscal year and no fiscal year profile
floor at 0
```

Use only for review priority, not accounting quality.

### 9.4 Suppression and reconstruction control

Default rules:

- suppress `entry_count < 3`
- use `k=5` for sensitive contexts such as payroll-like, medical, welfare, education, person-heavy, or individual proprietor data
- suppress if a single contributor dominates more than 80% of a visible aggregate
- suppress exact date x amount
- suppress counterparty x amount
- suppress memo keyword x amount
- apply complementary suppression when parent/child totals could reveal hidden cells

### 9.5 Review priority score

```text
priority = 0
+ 50 for blocker required-column failure
+ 50 for payroll/bank/person hard reject
+ 30 for parse failure affecting aggregates
+ 20 for future dates
+ 20 for debit/credit total mismatch
+ 15 for current official format diff
+ 10 for closing/adjustment/sticky/meta presence
+ 10 for high unknown account-class share
cap at 100
```

Labels:

- `blocker`: cannot safely produce aggregate artifact
- `warning`: can produce aggregate artifact with human review
- `info`: safe metadata note

## 10. Product artifacts to produce

### 10.1 P0 artifacts

| Artifact | Purpose | CSV input | Public source join | Billing unit |
|---|---|---|---|---|
| `csv_coverage_receipt` | Show what the CSV can safely support | provider profile, rows, columns, date/amount/account aliases | none | `packet` |
| `csv_review_queue_packet` | Show input conditions needing human review | review facts | none | `packet` |
| `account_vocabulary_map` | Show broad account vocabulary and industry hints | k-safe account aggregates | optional jGrants/e-Stat hints | `packet` |
| `evidence_safe_advisor_brief` | Brief for accountant/advisor/support staff | coverage + review + vocabulary | exact public identity if supplied | `packet` |
| `public_join_candidate_sheet` | Show exact/candidate public-source joins | explicit IDs/profile/hints | NTA, invoice, gBizINFO, EDINET, J-Grants, e-Stat | `source_receipt_set` |
| `csv_to_agent_route_card` | Tell the AI agent what to do next | user goal + preview | candidate joins only | `free_control` |
| `client_monthly_review` | Existing P0 packet using private aggregates plus public receipts | monthly/account aggregate facts only | exact public source changes/receipts | `packet` |

### 10.2 User-type bundles

| User type | Recommended packet bundle | Must not say |
|---|---|---|
| 税理士 | `tax_client_csv_intake_brief`, `month_end_question_list`, `invoice_registration_check_candidates` | tax correctness, filing answer, deduction/tax credit conclusion |
| 会計士 | `audit_pbc_csv_evidence_index`, `public_identity_reconciliation_sheet`, `audit_review_queue_packet` | audit opinion, fraud/misstatement conclusion |
| 補助金コンサル | `subsidy_readiness_question_list`, `eligible_expense_vocabulary_map`, `grant_public_join_candidate_sheet` | eligibility, adoption probability, target-expense conclusion |
| 信金 | `borrower_csv_onboarding_brief`, `funding_use_signal_brief`, `portfolio_public_join_candidates` | creditworthiness, loan approval, repayment ability |
| 商工会 | `member_support_triage_sheet`, `program_outreach_candidate_list`, `bookkeeping_hygiene_report` | management diagnosis, tax or grant final decision |
| 中小企業 | `owner_action_checklist`, `advisor_handoff_brief`, `public_opportunity_candidate_sheet` | tax saving, financing recommendation, risk-free claim |
| 業務SaaS | `csv_health_api_packet`, `agent_ready_csv_artifact_bundle`, `integration_gap_telemetry` | embedded professional judgment |

## 11. AWS J14 scope

J14 should not upload the supplied local raw CSVs to AWS.

Use AWS credit for:

- synthetic/header-only provider fixture matrix
- redacted one-row synthetic fixtures where necessary
- freee official / observed variant / legacy / unknown collision cases
- MF official 27 / pre-invoice 25 / amount suffix variants
- Yayoi cp932 / headerless positional / `伝票No` no-dot / comment-prefixed variants
- payroll/bank/card/person rejection fixtures
- formula-injection fixtures
- k-suppression and complementary suppression tests
- leak scanners over generated packet examples, OpenAPI examples, MCP examples, proof pages, logs, Athena outputs, and reports
- public join candidate test sets using exact synthetic identifiers and public source receipts
- cost and billing preview fixtures for CSV analyze/preview/execute flow

Do not use AWS for:

- raw private CSV storage
- Bedrock/Textract/OpenSearch input containing private CSV values
- Athena/Glue tables with raw rows
- S3 failed-object buckets containing raw uploads
- public examples based on private customer values
- long-lived private overlay indexes

J14 output paths should be treated as internal until leak scans pass:

- `csv_provider_fixture_matrix.jsonl`
- `csv_privacy_rejection_cases.jsonl`
- `csv_alias_mapping_report.md`
- `csv_private_overlay_schema.json`
- `csv_suppression_policy_report.md`
- `csv_public_join_candidate_report.md`
- `csv_packet_expected_outputs/*.json`
- `csv_leak_scan_report.md`
- `csv_billing_preview_cases.jsonl`

## 12. Integration order with the main jpcite plan

The merged order should be:

1. P0-E1 Packet contract and catalog
   - Freeze packet envelope, packet IDs, pricing metadata, `source_receipts`, `known_gaps`, `billing_metadata`, `request_time_llm_call_performed=false`.

2. P0-E2 Source receipts / claims / known gaps
   - Freeze public source receipt contract and private overlay receipt distinction.
   - Add `no_hit_not_absence` and private/public namespace split.

3. P0-E3 Pricing and cost preview
   - CSV analyze/preview/execute must fit the same free preview, cap, idempotency, no-bill rejection model.

4. P0-E4 CSV privacy and intake preview
   - Implement provider fingerprinting, alias mapping, sensitive rejection, aggregation, suppression, derived fact schema, and packet preview.

5. AWS F0-F2 guardrails and smoke run
   - No private CSV work yet. Verify account, budgets, stop scripts, small public receipt smoke tests.

6. AWS J01-J05/J07/J11 public source foundation
   - Build source profiles and public receipts needed for later join candidates.

7. AWS J14 CSV private overlay safety analysis
   - Run synthetic/header-only fixture matrix, suppression tests, leak scans, and exact-ID public join tests.

8. P0-E5 packet composers
   - Implement `client_monthly_review`, `public_join_candidate_sheet`, and agent route cards using J14 fixture outputs and public receipts.

9. AWS J15 packet/proof fixture materialization
   - Generate expected packet examples only after private overlay leak scans pass.

10. P0-E6/P0-E7 REST and MCP surfaces
    - Expose CSV analyze/preview/execute and route cards through REST/MCP with identical contract.

11. P0-E8 public proof/discovery surfaces
    - Publish only synthetic or public-source-backed examples; private overlay stays excluded.

12. P0-E9 release gates
    - Block release if any raw CSV, row value, memo, counterparty, small cell, private hash, or professional judgment leaks.

## 13. Acceptance gates

CSV pipeline cannot ship until all gates pass:

- [ ] Desktop-observed 9-file profile is represented by synthetic/header-only fixtures.
- [ ] freee observed files classify as variant, not official-compliant.
- [ ] MF observed files classify as old format / pre-invoice legacy, not current official.
- [ ] Yayoi cp932 official/variant cases classify correctly.
- [ ] Unknown/generic CSV falls back to shape report without provider-specific claim.
- [ ] Payroll, bank transfer, card, personal identifier, phone, email, address, and person-heavy files reject safely.
- [ ] Formula-like cells never appear in output/log/error/example.
- [ ] Raw CSV bytes/rows/row-level normalized records are not persisted.
- [ ] Memo/counterparty/voucher/creator/updater values are not output.
- [ ] Small-cell and complementary suppression tests pass.
- [ ] Public join with exact法人番号/T番号 produces source receipts.
- [ ] Name-only joins produce candidate/gap, not identity claim.
- [ ] no-hit output uses `no_hit_not_absence`.
- [ ] CSV rejection and cap/idempotency conflicts are not billed.
- [ ] Packet examples include `known_gaps`, `human_review_required`, `billing_metadata`, and `_disclaimer`.
- [ ] Public proof/GEO/OpenAPI/MCP examples contain no private overlay values or hashes.

## 14. Tests to create

Provider:

- `test_csv_provider_freee_desktop_variant`
- `test_csv_provider_mf_pre_invoice_legacy`
- `test_csv_provider_yayoi_cp932_official`
- `test_csv_provider_yayoi_denpyo_no_dot_variant`
- `test_csv_provider_unknown_conflict`

Privacy:

- `test_csv_no_raw_row_persistence`
- `test_csv_no_memo_counterparty_output`
- `test_csv_no_voucher_creator_output`
- `test_csv_formula_cell_not_echoed`
- `test_csv_payroll_bank_person_reject`
- `test_csv_small_cell_suppression`
- `test_csv_complementary_suppression`

Public join:

- `test_csv_exact_houjin_bangou_public_receipt`
- `test_csv_exact_invoice_number_public_receipt`
- `test_csv_name_only_returns_candidate_gap`
- `test_csv_no_hit_not_absence`

Billing/API/MCP:

- `test_csv_analyze_free_no_metering`
- `test_csv_reject_not_billed`
- `test_csv_execute_requires_cap_and_idempotency`
- `test_csv_rest_mcp_contract_drift`
- `test_csv_packet_public_private_namespace_split`

## 15. Weaknesses and mitigations

| Weakness | Why it matters | Mitigation |
|---|---|---|
| Users expect accounting advice | CSV has tax/accounting-looking data | Output only review conditions, questions, and source-backed public joins. Fence every packet. |
| Provider formats change | freee/MF/Yayoi update templates | Store source date, provider fingerprint version, and `provider_current_diff` review code. Re-check before release. |
| Aggregate leakage | small cells can reveal a transaction | k thresholds, complementary suppression, no exact dates/counterparties/memo keywords. |
| Public/private namespace mixing | GEO/proof pages could leak private facts | Separate receipt types, artifact promotion gate, leak scan before public generation. |
| Name-only public joins | Same-name companies and private relationships | Exact ID for high confidence; name-only capped to candidate/gap. |
| AWS cost run accidentally stores private CSV | S3/Athena/CloudWatch can persist values | J14 uses synthetic/header-only/redacted fixtures only; raw local CSV never uploaded. |
| Agent loops generate paid CSV runs | MCP agents can retry | Preview, cap, idempotency, no-bill reject, usage ledger. |

## 16. Bottom line

CSV support should be adopted.

The value is not "we read accounting data." The value is:

- AI agents can ask for a CSV only when useful.
- End users can drag-and-drop a CSV and receive safe, source-backed next actions.
- jpcite can produce artifacts that combine private aggregate signals with public official receipts.
- The output remains defensible because raw private facts never become public claims, and professional conclusions are fenced off.

AWS credit should strengthen this by generating the synthetic fixture matrix, suppression/leak tests, public join candidate reports, and packet examples that prove the design works. It should not process or retain real private CSV rows.
