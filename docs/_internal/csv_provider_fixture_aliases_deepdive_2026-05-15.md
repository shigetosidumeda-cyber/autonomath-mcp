# CSV Provider Fixture Aliases Deep Dive

作成日: 2026-05-15  
担当: CSV provider official fixtures / schema aliases  
状態: pre-implementation contract only  
保存先: `docs/_internal/csv_provider_fixture_aliases_deepdive_2026-05-15.md`

## 0. Scope

この文書は、`/Users/shigetoumeda/Desktop/CSV` 配下の9 CSVを実装前fixtureへ落とすためのprovider fingerprint、header alias、判定ルール、fixture test matrixを固定する。実装コード、raw CSV、取引明細、摘要、取引先値、金額明細は扱わない。

対象provider:

| provider | Desktop観測ファイル | 目的 |
|---|---:|---|
| freee | 4 | 現行freee公式インポート形式と、Desktop観測21列variantの差分をfixture化する。 |
| MF | 2 | 現行MF公式27列インボイス対応形式と、Desktop観測25列旧形式の差分をfixture化する。 |
| 弥生 | 3 | 弥生会計05以降の25項目・positional形式と、`伝票No` / `伝票No.` 表記ゆれ、cp932系をfixture化する。 |

非目標:

- 会計・税務判断。
- 勘定科目の正誤判定。
- raw行・cell値の永続保存。
- providerへ実際にインポート可能であることのE2E保証。

## 1. Sources and Baseline Dates

公式仕様は2026-05-15に確認した以下をbaselineとする。各providerページが更新されたら、fixture名に`source_updated_YYYY-MM-DD`を付けて再baselineする。

| Provider | Official source | Checked / updated | Contract impact |
|---|---|---:|---|
| freee | `https://support.freee.co.jp/hc/ja/articles/202847920-...freee形式を用いた方法` | ページ更新日 2025-09-04。添付CSVテンプレートあり。 | 現行公式は`[表題行]`先頭、`日付`列、`伝票No.`、セグメント1-3を含む21列。行頭は`[明細行]`。 |
| MF | `https://biz.moneyforward.com/support/account/guide/import-books/ib01.html` | ページ更新日 2025-11-27。 | 現行公式は`取引No`から`最終更新者`までAA列の27列。`借方/貸方インボイス`列あり。 |
| 弥生 | `https://support.yayoi-kk.co.jp/subcontents.html?page_id=18545` | 2026-05-15確認。 | 弥生会計05以降のpositional 25項目。`識別フラグ`, `取引日付`, `借方税金額`, `貸方税金額`, `調整`まで。 |
| 弥生 import rules | `https://support.yayoi-kk.co.jp/subcontents.html?grade_id=NW&page_id=18586` | 2026-05-15確認。 | カンマ区切り、項目順必須、先頭`#`はコメント行、最後の空項目処理、弥生製品データ対応を検査に反映。 |

## 2. Final Provider Fingerprints

### 2.1 Common header normalization

Provider判定前に、検査専用の正規化headerを作る。raw headerは保存しない。保存可能なのは`raw_column_profile_hash`と`header_alias_report`のみ。

Normalization:

- Strip UTF-8 BOM / UTF-16 BOM marker / leading zero-width marker from the first header cell.
- Trim ASCII and full-width surrounding whitespace.
- Normalize ASCII punctuation variants only for matching: `No` / `No.` / `Ｎｏ` / `Ｎｏ．`, ASCII and full-width parentheses.
- Do not normalize Japanese semantic terms: `税額` and `税金額` remain distinct aliases that map to the same canonical field.
- Preserve original column order in the profile hash after normalized label mapping.

Tie-break order:

1. Exact official fingerprint.
2. Known legacy fingerprint.
3. Known provider variant fingerprint.
4. Alias-compatible provider if provider score is decisive.
5. `unknown`.

### 2.2 freee fingerprints

| Fingerprint id | Class | Encoding fixture | Header/order fingerprint | Required evidence |
|---|---|---|---|---|
| `freee_official_import_2025_09_04_utf8` | official_compliant | UTF-8 no BOM or UTF-8 BOM tolerated | `[表題行]`, `日付`, `伝票No.`, `借方勘定科目`, `借方補助科目`, `借方部門`, `借方セグメント1`, `借方セグメント2`, `借方セグメント3`, `借方税区分`, `借方金額`, `借方税額`, `貸方勘定科目`, `貸方補助科目`, `貸方部門`, `貸方セグメント1`, `貸方セグメント2`, `貸方セグメント3`, `貸方税区分`, `貸方金額`, `貸方税額`, `摘要` | Header is exact after punctuation/whitespace normalization. First data row starts with `[明細行]` or fixture has an empty synthetic body row with same first column. |
| `freee_desktop_observed_21_export_like` | variant | UTF-8 / UTF-8 BOM / cp932 tolerated | `取引日`, `伝票番号`, `借方勘定科目`, `借方補助科目`, `借方部門`, `借方品目`, `借方メモタグ`, `借方取引先`, `借方税区分`, `借方税額`, `借方金額`, `貸方勘定科目`, `貸方補助科目`, `貸方部門`, `貸方品目`, `貸方メモタグ`, `貸方取引先`, `貸方税区分`, `貸方税額`, `貸方金額`, `摘要` | Matches Desktop 4-file shape. Must not be labeled official because current freee template uses `日付`, `[表題行]`, `伝票No.`, and segments. |
| `freee_minimal_renderer_legacy` | legacy | UTF-8 no BOM | `取引日`, `借方勘定科目`, `借方税区分`, `借方金額`, `貸方勘定科目`, `貸方税区分`, `貸方金額`, `摘要`, optional `備考` | Existing renderer compatibility only. Accept as legacy output fixture, not as official freee import fixture. |

Final decision: freee provider fingerprint is based on `freee_` scoring only if at least one freee-exclusive signal exists: `[表題行]`, `[明細行]`, `借方セグメント1`, `貸方セグメント1`, `借方品目`, `借方メモタグ`, or `伝票番号` with both `借方取引先` and `貸方取引先`.

### 2.3 MF fingerprints

| Fingerprint id | Class | Encoding fixture | Header/order fingerprint | Required evidence |
|---|---|---|---|---|
| `mf_official_journal_2025_11_27_utf8_sig` | official_compliant | UTF-8 BOM preferred, UTF-8 no BOM tolerated | `取引No`, `取引日`, `借方勘定科目`, `借方補助科目`, `借方部門`, `借方取引先`, `借方税区分`, `借方インボイス`, `借方金額(円)`, `借方税額`, `貸方勘定科目`, `貸方補助科目`, `貸方部門`, `貸方取引先`, `貸方税区分`, `貸方インボイス`, `貸方金額(円)`, `貸方税額`, `摘要`, `仕訳メモ`, `タグ`, `MF仕訳タイプ`, `決算整理仕訳`, `作成日時`, `作成者`, `最終更新日時`, `最終更新者` | Exact order and 27 columns after punctuation normalization. |
| `mf_pre_invoice_25_legacy` | legacy | UTF-8 BOM preferred, UTF-8 no BOM tolerated | Same as official but missing `借方インボイス` and `貸方インボイス`; otherwise `作成日時`, `作成者`, `最終更新日時`, `最終更新者` present | Matches Desktop 2-file shape. Label as old/current-diff because current official page includes invoice columns. |
| `mf_minimal_renderer_legacy` | legacy | UTF-8 BOM | `取引No`, `取引日`, `借方勘定科目`, `借方補助科目`, `借方部門`, `借方税区分`, `借方金額`, `貸方勘定科目`, `貸方補助科目`, `貸方部門`, `貸方税区分`, `貸方金額`, `摘要`, optional `備考` | Existing renderer compatibility only. Accept as legacy output fixture, not as current official fixture. |

Final decision: MF provider fingerprint requires `MF仕訳タイプ` or `決算整理仕訳`, or the pair `借方金額(円)` / `貸方金額(円)`. `取引No` alone is not sufficient because it can collide with generic journals.

### 2.4 弥生 fingerprints

| Fingerprint id | Class | Encoding fixture | Header/order fingerprint | Required evidence |
|---|---|---|---|---|
| `yayoi_official_05plus_25_cp932` | official_compliant | cp932 / Shift_JIS preferred; UTF-8 tolerated for synthetic fixtures | Positional 25 fields: `識別フラグ`, `伝票No.`, `決算`, `取引日付`, `借方勘定科目`, `借方補助科目`, `借方部門`, `借方税区分`, `借方金額`, `借方税金額`, `貸方勘定科目`, `貸方補助科目`, `貸方部門`, `貸方税区分`, `貸方金額`, `貸方税金額`, `摘要`, `番号`, `期日`, `タイプ`, `生成元`, `仕訳メモ`, `付箋1`, `付箋2`, `調整` | Header is optional. If no header, first cell must be a valid `識別フラグ` value such as `2000`, `2111`, `2110`, `2100`, `2101` and row width is 25. |
| `yayoi_header_no_dot_variant` | variant | cp932 / Shift_JIS / UTF-8 tolerated | Same as official but `伝票No` without trailing dot | Matches Desktop column shaking. Alias to `voucher_id`, but record `header_alias_report.warning=period_missing_on_denpyo_no`. |
| `yayoi_comment_prefixed_fixture` | official_compliant | cp932 / Shift_JIS preferred | One or more `#` comment rows before positional data | Official import rules say rows whose first character is `#` are comments. Fixture verifies parser skips them for detection. |

Final decision: 弥生 provider fingerprint is strongest when `識別フラグ`, `取引日付`, `借方税金額`, `貸方税金額`, `タイプ`, `生成元`, `付箋1`, `付箋2`, `調整` all appear in the expected order, or when no header exists and 25 positional fields satisfy the valid flag/date/type pattern.

## 3. Canonical Alias Map

Canonical fields are internal inspection names. They are not provider output schemas.

### 3.1 Date / voucher

| Canonical field | freee official | freee Desktop variant | MF official / legacy | 弥生 official / variant | Notes |
|---|---|---|---|---|---|
| `entry_date` | `日付` | `取引日` | `取引日` | `取引日付` | Accept `YYYY/MM/DD`, `YYYY/M/D`, `YYYY-MM-DD`; 弥生日付 also accepts official Japanese era forms at parse layer. |
| `voucher_id` | `伝票No.` | `伝票番号` | `取引No` | `伝票No.`, `伝票No` | Do not export raw value. Persist only presence/hash. |
| `line_kind` | `[表題行]` / `[明細行]` | none | none | none | freee official-only signal. |
| `closing_flag` | none | none | `決算整理仕訳` | `決算` | Boolean-like for MF; string enum for 弥生. Review flag only. |

### 3.2 Amount

| Canonical field | freee official | freee Desktop variant | MF official | MF legacy | 弥生 | Parse rule |
|---|---|---|---|---|---|---|
| `debit_amount` | `借方金額` | `借方金額` | `借方金額(円)` | `借方金額(円)` or `借方金額` | `借方金額` | Integer yen. Remove thousands separators only when CSV parser kept quoted field intact. |
| `credit_amount` | `貸方金額` | `貸方金額` | `貸方金額(円)` | `貸方金額(円)` or `貸方金額` | `貸方金額` | Integer yen. Negative values are parseable but produce `amount_negative_review`. |
| `amount_currency` | implicit JPY | implicit JPY | `(円)` signal | implicit or `(円)` | implicit JPY | Never infer foreign currency from memo/摘要. |

### 3.3 Tax

| Canonical field | freee official | freee Desktop variant | MF official / legacy | 弥生 | Notes |
|---|---|---|---|---|---|
| `debit_tax_category` | `借方税区分` | `借方税区分` | `借方税区分` | `借方税区分` | Category label is provider vocabulary; do not normalize to legal conclusion. |
| `credit_tax_category` | `貸方税区分` | `貸方税区分` | `貸方税区分` | `貸方税区分` | Same. |
| `debit_tax_amount` | `借方税額` | `借方税額` | `借方税額` | `借方税金額` | `税額` and `税金額` map to same canonical field. |
| `credit_tax_amount` | `貸方税額` | `貸方税額` | `貸方税額` | `貸方税金額` | Empty is `tax_amount_present=false`; not an error by itself. |
| `debit_invoice_class` | none | none | `借方インボイス` | embedded in tax category when present | MF current-only explicit field. |
| `credit_invoice_class` | none | none | `貸方インボイス` | embedded in tax category when present | Missing MF invoice columns classify as `mf_pre_invoice_25_legacy`. |

### 3.4 Counterparty / auxiliary dimensions

| Canonical field | freee official | freee Desktop variant | MF official / legacy | 弥生 | Storage posture |
|---|---|---|---|---|---|
| `debit_counterparty` | selected from `借方補助科目` at import UI, not explicit | `借方取引先` | `借方取引先` | none | Presence/count only. Values forbidden in output. |
| `credit_counterparty` | selected from `貸方補助科目` at import UI, not explicit | `貸方取引先` | `貸方取引先` | none | Presence/count only. Values forbidden in output. |
| `debit_subaccount` | `借方補助科目` | `借方補助科目` | `借方補助科目` | `借方補助科目` | Presence/count only unless aggregate account vocabulary. |
| `credit_subaccount` | `貸方補助科目` | `貸方補助科目` | `貸方補助科目` | `貸方補助科目` | Same. |
| `debit_department` | `借方部門` | `借方部門` | `借方部門` | `借方部門` | Presence/count only. |
| `credit_department` | `貸方部門` | `貸方部門` | `貸方部門` | `貸方部門` | Same. |
| `item_or_tag_presence` | none | `借方品目`, `借方メモタグ`, `貸方品目`, `貸方メモタグ` | `タグ` | none | Presence/distinct count only; values are not exportable. |

## 4. Classification Rules

### 4.1 Classes

| Class | Meaning | Output posture |
|---|---|---|
| `official_compliant` | Header/order and required provider signals match current official format, or 弥生 positional row matches official 25項目 without a header. | May say official fixture matched. |
| `old_format` | Provider is decisive but current official columns differ because of known old format, such as MF pre-invoice 25 columns or existing renderer minimal columns. | May say provider detected with current-diff. |
| `variant` | Provider is decisive, but observed columns represent export-like/Desktop/synthetic shape rather than official import template. | May normalize via aliases, but do not call official. |
| `unknown` | Provider score is not decisive, required date/amount fields are missing, or multiple providers tie after alias normalization. | Reject for provider-specific fixture; allow generic CSV shape report only. |

### 4.2 Scoring gates

Provider score is additive, but class assignment is rule-based.

| Signal | freee | MF | 弥生 |
|---|---:|---:|---:|
| Exact current official header/order | +100 | +100 | +100 |
| Known legacy/variant exact order | +80 | +80 | +80 |
| Provider-exclusive token | +20 each: `[表題行]`, `[明細行]`, `借方セグメント1`, `借方品目`, `借方メモタグ` | +20 each: `MF仕訳タイプ`, `決算整理仕訳`, `借方金額(円)`, `貸方金額(円)`, `借方インボイス` | +20 each: `識別フラグ`, `取引日付`, `税金額`, `生成元`, `付箋1`, `調整` |
| Required date + debit/credit amount pair | +20 | +20 | +20 |
| Counter-signal from another provider | -30 | -30 | -30 |

Decision thresholds:

- `official_compliant`: exact current official fingerprint, or 弥生 no-header positional official row.
- `old_format`: known legacy exact order and provider score >= 80.
- `variant`: provider score >= 70 and no other provider within 20 points.
- `unknown`: otherwise.

### 4.3 Current-diff rules

| Provider | Current-diff condition | Classification | Review code |
|---|---|---|---|
| freee | Uses `取引日` instead of `日付`, lacks `[表題行]`, lacks `借方セグメント1-3`, has explicit `借方取引先` / `借方品目` / `借方メモタグ` | `variant` | `freee_export_like_desktop_variant` |
| freee | Minimal renderer columns only, includes optional `備考` | `old_format` | `freee_renderer_legacy_minimal` |
| MF | 25 columns and missing `借方インボイス`, `貸方インボイス`; has `MF仕訳タイプ` and audit meta | `old_format` | `mf_pre_invoice_legacy_columns` |
| MF | `借方金額` / `貸方金額` without `(円)` but has `MF仕訳タイプ` | `variant` | `mf_amount_header_without_currency_suffix` |
| 弥生 | `伝票No` without dot | `variant` | `yayoi_denpyo_no_dot_alias` |
| 弥生 | Headerless 25-field rows with valid `識別フラグ` | `official_compliant` | `yayoi_positional_no_header` |

### 4.4 Unknown rules

Classify as `unknown` when any of the following is true:

- No parseable date alias from section 3.1.
- Missing either debit or credit amount alias.
- Header has only generic accounting labels and no provider-exclusive signal.
- Header count differs from all known fingerprints and alias mapping leaves more than 20% of columns unmapped.
- Encoding cannot be decoded as UTF-8, UTF-8 BOM, cp932, or Shift_JIS.
- Multiple provider scores tie within 20 points and neither has exact known order.

Unknown output is limited to:

- `column_count`
- normalized header hash
- missing canonical field list
- `provider_family=unknown`
- `human_review_required=true`

## 5. Encoding Fixture Contract

| Fixture id | Provider | Bytes | Expected detection | Expected class |
|---|---|---|---|---|
| `enc_freee_official_utf8_no_bom` | freee | UTF-8 no BOM official template header | `utf-8` | `official_compliant` |
| `enc_freee_official_utf8_bom` | freee | UTF-8 BOM official template header | `utf-8-sig` | `official_compliant` |
| `enc_freee_excel_cp932` | freee | Excel-oriented official template encoded cp932 | `cp932` | `official_compliant` if header exact |
| `enc_mf_utf8_bom` | MF | UTF-8 BOM official 27-column header | `utf-8-sig` | `official_compliant` |
| `enc_mf_utf8_no_bom` | MF | UTF-8 no BOM official 27-column header | `utf-8` | `official_compliant` with `encoding_warning=utf8_no_bom_for_excel` |
| `enc_yayoi_cp932` | 弥生 | cp932 25-column header or positional row | `cp932` | `official_compliant` |
| `enc_yayoi_utf8_synthetic` | 弥生 | UTF-8 25-column synthetic fixture | `utf-8` | `official_compliant` with `encoding_warning=utf8_synthetic_not_desktop_default` |
| `enc_unknown_binary` | unknown | invalid mixed bytes | `unknown` | `unknown` |

Encoding detection order:

1. `utf-8-sig`.
2. `utf-8`.
3. `cp932`.
4. `shift_jis`.
5. `unknown`.

If more than one decoder succeeds, prefer the decoder that preserves expected Japanese header tokens exactly.

## 6. Fixture Test Matrix

Fixture files should be synthetic and header-only or contain at most one redacted synthetic row. No Desktop raw rows should be copied.

### 6.1 Provider official fixtures

| Test id | Fixture | Input shape | Expected |
|---|---|---|---|
| `test_freee_official_template_exact` | `fixtures/csv_provider/freee_official_import_2025_09_04_utf8.csv` | Official freee header with `[表題行]` and one `[明細行]` row with synthetic empty values | `provider=freee`, `class=official_compliant`, date alias `日付`, voucher alias `伝票No.` |
| `test_mf_official_27_exact` | `fixtures/csv_provider/mf_official_journal_2025_11_27_utf8_sig.csv` | Official MF 27-column header | `provider=mf`, `class=official_compliant`, invoice aliases detected |
| `test_yayoi_official_header_25_exact` | `fixtures/csv_provider/yayoi_official_05plus_header_cp932.csv` | 弥生25-column header using `伝票No.` | `provider=yayoi`, `class=official_compliant`, tax amount alias `税金額` |
| `test_yayoi_official_positional_no_header` | `fixtures/csv_provider/yayoi_official_05plus_no_header_cp932.csv` | One synthetic row starting `2000` with 25 fields | `provider=yayoi`, `class=official_compliant`, `header_present=false` |

### 6.2 Desktop-observed / old / variant fixtures

| Test id | Fixture | Input shape | Expected |
|---|---|---|---|
| `test_freee_desktop_observed_21_variant` | `fixtures/csv_provider/freee_desktop_observed_21_header_only.csv` | 21 columns observed in four Desktop freee files | `provider=freee`, `class=variant`, review `freee_export_like_desktop_variant` |
| `test_mf_pre_invoice_25_old_format` | `fixtures/csv_provider/mf_pre_invoice_25_header_only.csv` | 25 columns observed in two Desktop MF files, no invoice columns | `provider=mf`, `class=old_format`, review `mf_pre_invoice_legacy_columns` |
| `test_yayoi_denpyo_no_dot_variant` | `fixtures/csv_provider/yayoi_25_header_denpyo_no_no_dot.csv` | 25 columns using `伝票No` | `provider=yayoi`, `class=variant`, voucher alias accepted |
| `test_renderer_freee_minimal_legacy` | `fixtures/csv_provider/freee_renderer_minimal_header_only.csv` | Existing renderer minimal freee columns | `provider=freee`, `class=old_format` |
| `test_renderer_mf_minimal_legacy` | `fixtures/csv_provider/mf_renderer_minimal_header_only.csv` | Existing renderer minimal MF columns | `provider=mf`, `class=old_format` |

### 6.3 Alias and column-shaking fixtures

| Test id | Fixture | Input shape | Expected |
|---|---|---|---|
| `test_alias_amount_parentheses_full_width` | `fixtures/csv_provider/mf_amount_fullwidth_parentheses.csv` | `借方金額（円）`, `貸方金額（円）` | Maps to `debit_amount`, `credit_amount`; warning `header_punctuation_normalized` |
| `test_alias_yayoi_tax_money_amount` | `fixtures/csv_provider/yayoi_tax_money_amount.csv` | `借方税金額`, `貸方税金額` | Maps to tax amount; provider score includes 弥生 tax signal |
| `test_alias_freee_date_torihiki_variant` | `fixtures/csv_provider/freee_date_torihiki_variant.csv` | freee Desktop `取引日` | Maps to `entry_date`; class remains `variant`, not official |
| `test_alias_mf_amount_without_yen_suffix` | `fixtures/csv_provider/mf_amount_without_yen_suffix.csv` | MF signals plus `借方金額`, `貸方金額` | `provider=mf`, `class=variant`, review `mf_amount_header_without_currency_suffix` |
| `test_alias_yayoi_denpyo_no_period` | `fixtures/csv_provider/yayoi_denpyo_no_period.csv` | `伝票No.` | Maps to `voucher_id`; no warning |
| `test_alias_yayoi_denpyo_no_no_period` | `fixtures/csv_provider/yayoi_denpyo_no_no_period.csv` | `伝票No` | Maps to `voucher_id`; warning retained |

### 6.4 Unknown / rejection fixtures

| Test id | Fixture | Input shape | Expected |
|---|---|---|---|
| `test_unknown_generic_journal_no_provider_signal` | `fixtures/csv_provider/unknown_generic_journal.csv` | `日付`, `借方`, `貸方`, `金額`, `摘要` only | `provider=unknown`, `class=unknown`, missing canonical aliases reported |
| `test_unknown_missing_credit_amount` | `fixtures/csv_provider/unknown_missing_credit_amount.csv` | Provider-like date and debit amount but no credit amount | `provider=unknown`, `class=unknown`, `missing=credit_amount` |
| `test_unknown_conflicting_provider_signals` | `fixtures/csv_provider/unknown_freee_mf_mixed.csv` | freee `[表題行]` plus `MF仕訳タイプ` | `provider=unknown`, `class=unknown`, `reason=provider_signal_conflict` |
| `test_unknown_invalid_encoding` | `fixtures/csv_provider/unknown_invalid_encoding.bin` | undecodable bytes | `provider=unknown`, `encoding=unknown` |
| `test_unknown_sensitive_bank_payroll_header` | `fixtures/csv_provider/reject_payroll_bank_header.csv` | Payroll/bank transfer headers | Reject before provider detection with security rule from CSV handling contract |

### 6.5 Privacy regression fixtures

| Test id | Fixture | Input shape | Expected |
|---|---|---|---|
| `test_no_raw_counterparty_output` | any provider fixture with synthetic counterparty cells | Output contains presence/count only, no cell value |
| `test_no_raw_voucher_output` | any provider fixture with synthetic voucher id | Output contains hash/presence only, no id value |
| `test_formula_like_cell_not_echoed` | synthetic cell beginning `=`, `+`, `-`, `@` in memo/counterparty | Review code `csv_formula_like_cell_detected`; no raw echo |
| `test_small_cell_suppression_keeps_provider_detection` | one-row synthetic fixture | Provider detection succeeds; aggregate output suppresses small buckets separately |

## 7. Implementation-facing Contract

The future implementation should expose the following derived shape from fixture detection:

```json
{
  "provider_family": "freee|mf|yayoi|unknown",
  "provider_fingerprint": "freee_official_import_2025_09_04_utf8",
  "format_class": "official_compliant|old_format|variant|unknown",
  "encoding_detected": "utf-8|utf-8-sig|cp932|shift_jis|unknown",
  "header_present": true,
  "column_count": 0,
  "canonical_aliases": {
    "entry_date": "取引日",
    "voucher_id": "伝票番号",
    "debit_amount": "借方金額",
    "credit_amount": "貸方金額",
    "debit_tax_category": "借方税区分",
    "credit_tax_category": "貸方税区分",
    "debit_tax_amount": "借方税額",
    "credit_tax_amount": "貸方税額",
    "debit_counterparty": "借方取引先",
    "credit_counterparty": "貸方取引先"
  },
  "review_codes": ["freee_export_like_desktop_variant"],
  "raw_column_profile_hash": "sha256:...",
  "human_review_required": true
}
```

Required invariants:

- `provider_family=unknown` when `format_class=unknown`.
- `format_class=official_compliant` only for exact current official fingerprints or 弥生 official positional no-header rows.
- Header aliases can unlock parsing, but aliases do not upgrade `variant` or `old_format` to `official_compliant`.
- `raw_column_profile_hash` must be computed from normalized column labels and order, not raw cells.
- Counterparty, memo, voucher, author/updater values are never output as values.

## 8. Desktop 9-file Expected Classification

Based on the already documented Desktop header profiles, expected classification is:

| File | Provider | Expected fingerprint | Class | Reason |
|---|---|---|---|---|
| `freee_personal_freelance.csv` | freee | `freee_desktop_observed_21_export_like` | `variant` | 21-column Desktop freee shape with explicit item/tag/counterparty columns, not current official template. |
| `freee_personal_rental.csv` | freee | `freee_desktop_observed_21_export_like` | `variant` | Same. |
| `freee_sme_agri.csv` | freee | `freee_desktop_observed_21_export_like` | `variant` | Same. |
| `freee_sme_welfare.csv` | freee | `freee_desktop_observed_21_export_like` | `variant` | Same. |
| `mf_sme_medical.csv` | MF | `mf_pre_invoice_25_legacy` | `old_format` | Desktop MF profile has 25 columns and audit metadata but lacks current official invoice columns. |
| `mf_sme_subsidy.csv` | MF | `mf_pre_invoice_25_legacy` | `old_format` | Same. |
| `yayoi_apple_farm.csv` | 弥生 | `yayoi_official_05plus_25_cp932` or `yayoi_header_no_dot_variant` | `official_compliant` or `variant` | Depends on exact `伝票No.` vs `伝票No` header; both alias to voucher. |
| `conglomerate_yayoi.csv` | 弥生 | `yayoi_header_no_dot_variant` likely | `variant` | Existing observation reports `伝票No` / `伝票No.` shaking. |
| `media_conglomerate_yayoi.csv` | 弥生 | `yayoi_header_no_dot_variant` likely | `variant` | Same. |

## 9. Open Follow-ups Before Code

- Re-download official freee templates into synthetic fixture generation input only; do not commit provider-downloaded files if license/redistribution is unclear. Commit hand-authored header-only fixtures instead.
- Verify Desktop headers via a header-only inspection script and store only `column_profile_hash` plus class, not raw headers if privacy posture tightens.
- Decide whether `official_compliant` should require provider-preferred encoding or whether exact header order is sufficient. This document currently allows UTF-8 variants for synthetic tests but emits encoding warnings.
- Keep existing renderer fixtures separate from provider import fixtures so current implementation compatibility does not masquerade as official provider compliance.

