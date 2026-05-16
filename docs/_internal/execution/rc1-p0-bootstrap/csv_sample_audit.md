# CSV sample audit for accounting overlay

Date: 2026-05-15

Scope: local files under `/Users/shigetoumeda/Desktop/CSV`. This is an input-shape audit for the JP agent runtime plan, not a certification that the files will import into each vendor product without vendor-side validation.

## Local Files

| File | Likely profile | Encoding | Rows | Columns | Date column | Period observed |
| --- | --- | --- | ---: | ---: | --- | --- |
| `freee_personal_freelance.csv` | freee-style journal export | UTF-8 BOM | 372 | 21 | `取引日` | 2024/04/01 to 2026/03/31 |
| `freee_personal_rental.csv` | freee-style journal export | UTF-8 BOM | 455 | 21 | `取引日` | 2024/04/05 to 2026/03/31 |
| `freee_sme_agri.csv` | freee-style journal export | UTF-8 BOM | 918 | 21 | `取引日` | 2024/04/01 to 2026/05/28 |
| `freee_sme_welfare.csv` | freee-style journal export | UTF-8 BOM | 797 | 21 | `取引日` | 2024/04/01 to 2026/03/31 |
| `mf_sme_medical.csv` | Money Forward-style journal export | UTF-8 BOM | 1,906 | 25 | `取引日` | 2024/04/01 to 2026/03/31 |
| `mf_sme_subsidy.csv` | Money Forward-style journal export | UTF-8 BOM | 653 | 25 | `取引日` | 2024/04/01 to 2026/03/31 |
| `conglomerate_yayoi.csv` | Yayoi import-style journal | CP932 | 3,768 | 25 | `取引日付` | 2024/04/01 to 2026/05/28 |
| `media_conglomerate_yayoi.csv` | Yayoi import-style journal | CP932 | 4,084 | 25 | `取引日付` | 2024/04/01 to 2026/05/28 |
| `yayoi_apple_farm.csv` | Yayoi import-style journal | CP932 | 1,347 | 25 | `取引日付` | 2023/01/01 to 2025/12/31 |

## Official-Format Alignment Notes

The samples match the broad shape of each vendor family:

- freee-style files expose journal columns such as `取引日`, debit/credit account names, debit/credit tax categories, amounts, counterparties, tags, departments, and summary text. freee's official help describes journal CSV export/import around generic journal data, debit/credit account fields, tax fields, and partner output behavior. Reference: https://support.freee.co.jp/hc/ja/articles/204615564 and https://support.freee.co.jp/hc/ja/articles/204847430
- Money Forward-style files expose `取引No`, `取引日`, debit/credit account, subaccount, department, counterparty, tax category, amount, tax amount, summary, memo, tags, journal type, and update metadata. Money Forward's official support describes journal CSV import and notes that account names must match the configured accounts exactly, with fiscal-year switching needed for out-of-year dates. Reference: https://biz.moneyforward.com/support/account/guide/import-books/ib01.html
- Yayoi-style files expose `識別フラグ`, voucher number, settlement flag, `取引日付`, debit/credit account, subaccount, department, tax category, amount, tax amount, summary, due date/type/source/memo/sticky fields. Yayoi's official support describes import data formats including identification flag, voucher number, transaction date, and account/tax fields. Reference: https://support.yayoi-kk.co.jp/subcontents.html?page_id=27184

## Important Input Differences

- Encoding differs by family. freee/MF samples are readable as UTF-8 BOM; Yayoi samples require CP932.
- Date field names differ: freee/MF use `取引日`; Yayoi uses `取引日付`.
- Amount field names differ: freee uses `借方金額`/`貸方金額`; MF uses `借方金額(円)`/`貸方金額(円)`; Yayoi uses `借方金額`/`貸方金額`.
- Voucher identifiers differ: freee has `伝票番号`; MF has `取引No`; Yayoi has `伝票No` or `伝票No.` depending on sample.
- Fiscal periods differ. Several samples extend beyond a standard single fiscal year, so any import or artifact workflow must detect period coverage instead of assuming one year.
- Account names and tax categories are vendor/tenant dependent. The service should not assert import success unless the target tenant's configured accounts and tax categories have been verified.

## Artifact Implications

These CSVs can support user-private overlay outputs when combined with official/public source receipts:

- Period coverage map: detect usable months, missing months, and future/out-of-year rows.
- Account-category exposure map: summarize major revenue, expense, tax, receivable/payable, cash, loan, payroll, and fixed-asset signals.
- Public counterparty check queue: extract counterparties and match them against public invoice/company sources without exposing raw CSV values publicly.
- Subsidy/regulation triage: map spending/revenue signals to candidate public programs while returning only `candidate_for_review`, never a legal/accounting eligibility verdict.
- Monthly advisor review packet: rank deadlines, large movements, stale receivables/payables, and public-source watch items.

## Fail-Closed Rules

- Raw CSV must remain tenant-private and must not enter public release capsules.
- Missing account/tax/vendor fields produce known gaps, not invented facts.
- No-hit public source matching means observed no hit only; it is not proof that an entity or obligation does not exist.
- Vendor format alignment is heuristic unless tested against the vendor import/export product flow for the exact tenant/accounting year.
