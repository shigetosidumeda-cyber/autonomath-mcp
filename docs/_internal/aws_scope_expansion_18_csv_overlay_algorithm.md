# AWS scope expansion 18: CSV private overlay algorithm

作成日: 2026-05-15  
担当: 拡張深掘り 18/30 / 会計CSV private overlay アルゴリズム  
対象: freee / Money Forward / Yayoi 等の会計CSVを、raw CSV非保存・非ログ・非AWSで一時解析し、公的一次情報と突合して成果物を生成する設計  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、収集ジョブ実行、既存コード変更は行わない。  
書き込み範囲: このMarkdownのみ。

## 0. 結論

会計CSV private overlay は、jpcite の売上を伸ばす上で強い。

理由は単純で、公的一次情報だけでは「制度」「法人」「法令」「許認可」「処分」「補助金」は分かっても、エンドユーザー本人に関係があるかまでは弱い。会計CSVを一時的に読み、保存せず、ログに出さず、AWSへ送らず、月次・科目・税区分・支出カテゴリ・取引先候補数などの aggregate facts だけに変換すると、AIエージェントは次のような成果物を安く推薦できる。

| 成果物 | AIエージェントが推薦する理由 | CSV由来の価値 | 公的一次情報の価値 |
|---|---|---|---|
| `csv_monthly_review_packet` | 「会計CSVを落とすだけで今月の確認事項を根拠付きで見られる」 | 月次推移、急増急減、税区分、費目シグナル | 税/労務/制度/法令/手続の根拠 |
| `csv_grant_candidate_packet` | 「使えそうな補助金・助成金を候補として出せる」 | IT投資、広告、設備、人件費、研修、地域/規模ヒント | J-Grants、自治体、厚労省、中小企業庁等 |
| `csv_tax_labor_event_packet` | 「今月確認すべき税/社保/労務イベント候補を出せる」 | 給与、法定福利費、賞与、源泉、消費税、租税公課の兆候 | 国税庁、日本年金機構、厚労省、e-Gov |
| `csv_counterparty_public_check_packet` | 「取引先候補を公的情報で安く確認できる」 | 取引先列/T番号列/支払先候補の存在と件数 | 法人番号、インボイス、gBizINFO、処分情報 |

ただし、CSVは私的データなので、設計の主語は「データを貯める」ではなく「その場で aggregate facts に落としてすぐ捨てる」である。

最重要の不変条件:

- raw CSVを保存しない。
- raw CSVをログに出さない。
- raw CSVをAWSへ送らない。
- row-level normalized records を保存しない。
- 摘要、取引先名、従業員名、作成者、更新者、伝票番号、請求番号、銀行/カード/給与/個人情報を出力しない。
- small group suppression を必須にする。
- formula injection を intake 時点で検出し、出力時点でも二重に防ぐ。
- 断定ではなく、候補、根拠、未確認範囲、次に確認する情報を返す。

## 1. Product boundary

### 1.1 何を作るか

CSV private overlay は、会計CSVから次のような安全な aggregate facts を作る。

```json
{
  "csv_overlay_facts": {
    "provider_profile": "money_forward_old_or_variant",
    "format_class": "variant",
    "period": {
      "start_month": "2025-04",
      "end_month": "2026-03",
      "months_covered": 12,
      "coverage_quality": "good"
    },
    "row_stats": {
      "row_count_bucket": "1000-4999",
      "invalid_row_count_bucket": "0",
      "duplicate_candidate_count_bucket": "1-10"
    },
    "account_rollups": [
      {
        "taxonomy": "sales",
        "months_present": 12,
        "amount_bucket_by_month": ["1m-3m"],
        "trend_class": "stable_or_mild_growth"
      }
    ],
    "event_flags": [
      "has_payroll_expense",
      "has_social_insurance_expense",
      "has_it_or_software_expense",
      "has_advertising_expense"
    ],
    "public_join_candidates": {
      "invoice_id_present_count_bucket": "10-49",
      "corporate_number_present_count_bucket": "0",
      "name_only_counterparty_count_bucket": "50-99"
    }
  }
}
```

このfactsを使って、jpciteの公的一次情報基盤へ問い合わせる。

```text
CSV aggregate facts
  -> profile and event inference
  -> public source query plan
  -> source_receipts[]
  -> claim_refs[]
  -> known_gaps[]
  -> packet
```

### 1.2 何を作らないか

作らないもの:

- 税額の確定計算。
- 社会保険加入義務の断定。
- 労務手続き義務の断定。
- 補助金の採択可能性の断定。
- 許認可の必要/不要の断定。
- 取引先が安全/危険/違法であるという断定。
- row-level 明細一覧。
- 摘要や取引先名を含むレポート。
- CSVを公的データ基盤へ混ぜた公開証跡。

CSV overlay は「判断」ではなく「候補生成」と「根拠付き確認事項の整理」に使う。

## 2. Immutable privacy contract

### 2.1 raw CSV non-retention

以下は禁止する。

| 対象 | 禁止 |
|---|---|
| raw bytes | 保存、ログ、S3アップロード、DB保存、OpenSearch投入、CloudWatch出力 |
| raw rows | 保存、ログ、debug出力、packet出力、テストfixture化 |
| row-level normalized records | 保存、ログ、idempotency cache化 |
| memo/摘要 | 値の保存、値の返却、LLM prompt投入 |
| counterparty/customer/vendor values | 値の保存、値の返却、public example化 |
| voucher/invoice/transaction IDs | 値の保存、値の返却 |
| employee/person/payroll/bank/card data | 受理しない、または即時拒否 |
| formula-like cell values | 値を返さない。検出件数と拒否理由のみ |

### 2.2 allowed derived outputs

保存またはAPI応答してよいものは、以下に限定する。

| 種別 | 許可される内容 |
|---|---|
| file profile | provider family、format class、encoding、delimiter、row count bucket、column count |
| header profile | normalized header aliases、provider fingerprint、raw_column_profile_hash |
| period | month/quarter/year range。small group条件を満たす場合のみ |
| aggregate amount | bucketed monthly amount、account taxonomy share、trend class |
| counts | k-safe count bucket、presence flag、reject count |
| event flag | `has_payroll_expense` 等の抽象フラグ |
| public join | 法人番号/T番号など明示IDに基づくsource receipt |
| warnings | unsupported format、legacy format、missing column、privacy suppression |
| known gaps | 給与台帳未確認、申告状況未確認、個別取引未確認等 |

### 2.3 AWS boundary

AWS credit run で扱ってよいCSV関連データ:

- synthetic CSV fixtures。
- header-only fixtures。
- redacted fixtures。
- provider alias map。
- suppression/leak scan test corpus。
- aggregate fact schema。
- public source datasets。
- packet examples where private values are synthetic or absent。

AWSへ送ってはいけないもの:

- ユーザーが投入した実CSV。
- 実CSVから生成したrow-level records。
- 実CSVの摘要、取引先名、伝票番号、請求番号。
- 実CSV由来の小セルで個別取引が推定できる値。

## 3. Threat model

### 3.1 主な失敗モード

| ID | 失敗モード | 影響 | 必須対策 |
|---|---|---|---|
| T01 | raw CSVをサーバーログに出す | 重大な漏えい | request body logging disabled、structured safe logger |
| T02 | parse errorにraw rowを含める | 重大な漏えい | error redaction、row value禁止 |
| T03 | small groupで個人/取引先が推定できる | プライバシー侵害 | k-anonymity、dominance suppression |
| T04 | formula injectionがCSV/HTML出力で発火 | セキュリティ事故 | intake検出、export sanitizer、raw value非出力 |
| T05 | 名称照合だけで法人同定を断定 | 誤認 | exact ID優先、name-onlyはcandidate扱い |
| T06 | no-hitを不存在/安全と表現 | 法的/信用リスク | `no_hit_not_absence` |
| T07 | CSVから税務・労務判断を断定 | 専門判断リスク | human_review_required、known_gaps |
| T08 | public packetへprivate factsが混入 | GEO公開事故 | namespace分離、leak scan |
| T09 | idempotency keyにCSV hashを使い外部推測可能 | 再識別 | tenant-scoped HMAC only、public hash禁止 |
| T10 | AI agent向けexampleに実データを混ぜる | 二次漏えい | synthetic-only examples |

### 3.2 安全な失敗

危険があれば、成果物生成ではなく安全なpreviewを返す。

```json
{
  "status": "rejected_or_preview_only",
  "reason_codes": [
    "payroll_personal_data_detected",
    "formula_like_cells_detected",
    "small_group_suppression_blocks_output"
  ],
  "billable": false,
  "raw_csv_retained": false,
  "next_action": "Upload a journal CSV without payroll/person/bank/card detail, or use header-only preview."
}
```

## 4. Intake algorithm

### 4.1 Stages

```text
S0 receive transient file
S1 size/content-type/encoding/dialect check
S2 formula injection scan
S3 provider and file-type detection
S4 sensitive category scan
S5 alias normalization
S6 transient row parse
S7 aggregate fact computation
S8 suppression and bucketing
S9 public source query plan
S10 packet generation
S11 leak scan
S12 raw buffer zero/discard
```

### 4.2 S0: transient receive

Implementation rule:

- API endpoint must set body logging off.
- Access logs must not include query params containing CSV content.
- Error trackers must drop request bodies and response bodies for this route.
- The request object should be consumed into memory or a short-lived stream only.
- The raw buffer must be dereferenced immediately after aggregate computation.
- No debug snapshot.
- No "failed rows sample".

Preferred modes:

1. Browser-side parser generates aggregate facts locally, then sends only facts to jpcite.
2. If server-side parsing is needed, use a dedicated no-store endpoint with body logging disabled and hard memory/time caps.

### 4.3 S1: size, encoding, dialect

Checks:

| Check | Rule |
|---|---|
| file size | hard cap by plan tier, e.g. 10MB/50MB/200MB. Too large returns preview rejection |
| rows | cap and bucket. Exact row count may be returned if not sensitive; otherwise bucket |
| encoding | UTF-8 BOM, UTF-8, CP932, Shift_JIS |
| delimiter | comma or tab |
| quote handling | RFC4180-like with provider exceptions |
| binary content | reject |
| malformed rate | reject if above threshold |

Output:

```json
{
  "encoding_detected": "cp932",
  "delimiter_detected": ",",
  "row_count_bucket": "1000-4999",
  "column_count": 25,
  "parse_quality": "usable"
}
```

### 4.4 S2: formula injection scan

Formula-like cell starts are dangerous even if values are not output, because future exports or debug tools may accidentally preserve them.

Dangerous prefixes after trimming Unicode BOM and leading whitespace:

- `=`
- `+`
- `-`
- `@`
- tab
- carriage return
- line feed
- full-width variants that normalize into those characters

Detection rule:

```text
is_formula_like(value):
  normalized = unicode_nfkc(value)
  stripped = strip_leading_spaces_tabs_crlf(normalized)
  return stripped starts_with one_of("=", "+", "-", "@")
```

Important nuance:

- Negative numeric amounts are common. A cell exactly representing a number such as `-12000` can be treated as numeric only after strict numeric parsing.
- A string such as `-cmd|...`, `+SUM(...)`, `@HYPERLINK(...)`, or `=1+1` is formula-like.
- The raw value is never returned. Only counts and reason codes are returned.

Output:

```json
{
  "formula_scan": {
    "formula_like_cell_count_bucket": "1-10",
    "numeric_negative_amount_cells_allowed": true,
    "action": "continue_with_values_discarded"
  }
}
```

If formula-like values appear in header names, memo fields, counterparty fields, or any text field, mark:

```json
{
  "reason_codes": ["formula_like_text_cells_detected"],
  "human_review_required": true
}
```

### 4.5 S3: provider and file-type detection

Provider detection must be separate from official compliance.

```text
provider_score =
  header_match_score
  + positional_pattern_score
  + encoding_score
  + required_field_score
  + provider_specific_terms_score
  - conflict_penalty
```

Provider families:

| Provider | likely signals | classification |
|---|---|---|
| freee | `取引日`, `伝票番号`, debit/credit account pairs, `品目`, `メモタグ`, `備考` | `freee_variant_or_export_like` |
| Money Forward | `取引No`, `取引日`, amount columns with yen suffix, `MF仕訳タイプ`, `決算整理仕訳`, creator/updater meta | `money_forward_current_or_legacy_variant` |
| Yayoi | CP932, 25-field journal family, `識別フラグ`, `取引日付`, `借方勘定科目`, `貸方勘定科目`, `付箋` | `yayoi_25_item_or_variant` |
| generic | date/account/amount/tax fields exist but no strong provider signature | `generic_journal` |

File-type detection:

| File type | P0 handling |
|---|---|
| journal / 仕訳帳 | supported |
| general ledger / 総勘定元帳 | conditional, if can safely aggregate |
| invoice CSV | P1, strict mode only |
| customer/supplier master | P1 exact-ID lane only |
| bank/card statement | reject or local-only future |
| payroll/personnel | reject |
| transfer file | reject |

### 4.6 S4: sensitive category scan

Sensitive categories:

| Category | Signals | Action |
|---|---|---|
| payroll/person | 従業員名、給与明細、社員番号、マイナンバー、賞与個人別 | reject |
| bank/card | 口座番号、カード番号、支店番号、名義、振込先 | reject |
| medical/patient | 患者、診療、保険者番号、カルテ | reject |
| address/contact | 住所、電話、メール、担当者 | reject or strict exact-ID future |
| memo-heavy | 摘要に個人/取引先/案件名が多い | allow parse but never export values |
| vendor/customer | 取引先名、顧客名、仕入先名 | values discarded; only counts/ID candidates |

Sensitive scan output:

```json
{
  "sensitive_scan": {
    "payroll_personal_data_detected": false,
    "bank_card_data_detected": false,
    "counterparty_values_present": true,
    "memo_values_present": true,
    "action": "aggregate_only"
  }
}
```

## 5. Canonical model

### 5.1 Internal transient row model

This model must never be persisted.

```json
{
  "date": "YYYY-MM-DD",
  "debit_account": "raw_discard_after_mapping",
  "credit_account": "raw_discard_after_mapping",
  "debit_amount": 0,
  "credit_amount": 0,
  "tax_category": "raw_discard_after_mapping",
  "department": "raw_discard_after_mapping",
  "counterparty": "raw_discard_immediately",
  "memo": "raw_discard_immediately",
  "voucher_id": "raw_discard_immediately"
}
```

The transient model is a conceptual parsing stage only. It must not be serialized, logged, cached, or sent to other services.

### 5.2 Persistable file profile

```json
{
  "private_csv_file_profile": {
    "profile_id": "tenant_scoped_hmac",
    "source_kind": "accounting_csv_private_overlay",
    "provider_family": "freee|money_forward|yayoi|generic|unknown",
    "provider_fingerprint": "yayoi_25_item_or_variant",
    "format_class": "official_compliant|variant|old_format|unknown",
    "encoding_detected": "utf-8-sig|utf-8|cp932|shift_jis|unknown",
    "delimiter_detected": "comma|tab|unknown",
    "row_count_bucket": "0|1-9|10-49|50-99|100-999|1000-4999|5000-9999|10000+",
    "column_count": 25,
    "raw_column_profile_hash": "sha256:normalized_header_order_only",
    "header_aliases": {
      "entry_date": "present",
      "debit_account": "present",
      "credit_account": "present",
      "amount": "present",
      "tax_category": "present",
      "counterparty": "present_value_discarded",
      "memo": "present_value_discarded"
    },
    "privacy_flags": {
      "raw_csv_retained": false,
      "row_level_records_retained": false,
      "body_logging_disabled": true,
      "aws_upload_performed": false
    }
  }
}
```

### 5.3 Persistable aggregate facts

```json
{
  "csv_aggregate_facts": {
    "period": {
      "start_month": "2025-04",
      "end_month": "2026-03",
      "months_covered": 12,
      "coverage_gaps": ["2025-08"],
      "coverage_quality": "partial|good|unknown"
    },
    "amount_rollups": [
      {
        "axis": "month_account_taxonomy",
        "month": "2026-03",
        "account_taxonomy": "software_it",
        "amount_bucket": "100k-500k",
        "row_count_bucket": "10-49",
        "suppressed": false
      }
    ],
    "trend_facts": [
      {
        "metric": "sales",
        "trend_class": "up|down|flat|volatile|insufficient_data",
        "method": "robust_median_mad",
        "confidence": "low|medium|high"
      }
    ],
    "event_flags": [
      {
        "flag": "has_payroll_expense",
        "evidence": "account_taxonomy_present",
        "month_count_bucket": "10-12",
        "suppressed": false
      }
    ],
    "public_join_seed_counts": {
      "invoice_registration_number_present_bucket": "10-49",
      "corporate_number_present_bucket": "0",
      "name_only_candidate_bucket": "50-99"
    }
  }
}
```

## 6. Account taxonomy algorithm

### 6.1 Taxonomy table

Raw account names differ by provider and accounting firm. The system should map raw account labels into a controlled taxonomy and discard raw labels.

| Taxonomy | Typical Japanese account labels | Uses |
|---|---|---|
| `sales` | 売上高、売上、役務収益、受取手数料 | monthly review、grant size hints、consumption-tax context |
| `cogs_purchase` | 仕入高、材料費、商品仕入、外注加工費 | margin review、supply chain hints |
| `outsourcing` | 外注費、業務委託費、支払報酬 | freelance act, withholding, invoice checks |
| `payroll` | 給与手当、役員報酬、賞与、雑給 | labor/social insurance event candidates |
| `social_insurance` | 法定福利費、社会保険料 | labor/social insurance event candidates |
| `rent` | 地代家賃、賃借料 | fixed cost review、location/permit hints |
| `advertising` | 広告宣伝費、販売促進費 | grant matching、sales campaign review |
| `software_it` | ソフトウェア、クラウド利用料、通信費、SaaS | IT grants, DX/security support hints |
| `capex` | 工具器具備品、機械装置、車両運搬具、建物附属設備 | equipment grant candidates |
| `professional_fee` | 支払報酬、顧問料、支払手数料 | withholding/professional support hints |
| `tax_dues` | 租税公課、法人税等、消費税等 | tax event review |
| `travel_transport` | 旅費交通費、車両費、燃料費 | transport/activity profile |
| `loan_finance` | 支払利息、短期借入金、長期借入金 | finance support candidates, not financial advice |
| `utilities` | 水道光熱費、電気代、ガス代 | cost review、energy program candidates |
| `training` | 研修費、教育訓練費、採用教育費 | subsidy/labor development hints |
| `unknown_other` | unmapped | never infer high-stakes events alone |

### 6.2 Mapping method

Use layered mapping:

```text
taxonomy_score(raw_account, side, tax_category, provider):
  score = dictionary_exact_match(raw_account)
        + normalized_token_match(raw_account)
        + provider_alias_match(raw_account, provider)
        + side_context_score(side)
        + tax_category_context_score(tax_category)
        - ambiguity_penalty

if score >= threshold_high:
  assign taxonomy
elif score >= threshold_low:
  assign taxonomy_candidate with low confidence
else:
  unknown_other
```

Rules:

- Raw account labels are not persisted.
- Only taxonomy labels are retained.
- Low-confidence mapping can trigger known gap, but not a strong recommendation.
- A single row can contribute to both debit and credit contexts only after accounting-specific sign rules.

### 6.3 Sign and amount normalization

Journal CSVs can express amounts differently. Normalize to rollups, not rows.

```text
normalized_amount_for_taxonomy(row, taxonomy):
  detect debit/credit amount columns
  parse numeric strictly
  infer account side
  map account to taxonomy
  produce signed contribution for rollup
```

Safety:

- If debit/credit mismatch rate is high, return `balance_integrity_warning`.
- If amount signs cannot be inferred, only count presence flags and reject trend analysis.
- Do not output exact maximum/minimum transaction amounts.

## 7. Small group suppression

### 7.1 Why suppression is mandatory

Even aggregate facts can leak private information.

Example:

```text
2026-03 / 外注費 / 1 row / 980,000円
```

This effectively reveals one transaction. Therefore, every aggregate must pass k and dominance checks.

### 7.2 Core rules

Default parameters:

| Parameter | Default | Meaning |
|---|---:|---|
| `k_min` | 5 | minimum contributing rows |
| `distinct_periods_min` | 2 | avoid one-off disclosure for monthly trend |
| `dominance_max_share` | 0.80 | one row/contributor cannot dominate |
| `counterparty_k_min` | 10 | stricter for vendor/customer-derived facts |
| `payroll_k_min` | reject | payroll/person files are not accepted in P0 |

Suppression decision:

```text
safe_to_release(cell):
  if cell.raw_values_present:
    return false
  if cell.row_count < k_min:
    return false
  if cell.max_contributor_share > dominance_max_share:
    return false
  if cell.axis includes counterparty and cell.distinct_counterparty_count < counterparty_k_min:
    return false
  return true
```

### 7.3 Amount bucketing

Use buckets, not exact values, for output.

| Bucket | Range |
|---|---|
| `0` | zero or not present |
| `1-10k` | 1 to 10,000 yen |
| `10k-50k` | 10,000 to 50,000 yen |
| `50k-100k` | 50,000 to 100,000 yen |
| `100k-500k` | 100,000 to 500,000 yen |
| `500k-1m` | 500,000 to 1,000,000 yen |
| `1m-3m` | 1,000,000 to 3,000,000 yen |
| `3m-10m` | 3,000,000 to 10,000,000 yen |
| `10m+` | 10,000,000 yen or more |

Exact amounts can be used internally during transient computation, but not emitted unless the user explicitly requests local-only client display and no server response stores it. P0 should avoid exact amounts entirely.

## 8. Public source join algorithm

### 8.1 Join principles

Public source joins must be separated by identifier quality.

| Join lane | Input | Output quality | Allowed claims |
|---|---|---|---|
| exact corporate number | 13-digit法人番号 | high | public corporate baseline |
| exact invoice registration number | T + 13 digits | high | invoice registry receipt |
| exact EDINET code | EDINET code | high | disclosure metadata receipt |
| exact permit number | source-specific permit number | medium/high | permit registry receipt if source supports |
| name + address | normalized name and address | candidate only | "candidate match" |
| name only | name string | weak | "public lookup candidate", no identity claim |

CSV-derived raw names are not persisted. For name-only matching, P0 should avoid returning the raw name and instead return counts and ask the user for explicit exact identifiers.

### 8.2 Corporate and invoice join

If CSV includes T-number or corporate number columns:

```text
for each exact_id in transient parsed identifiers:
  validate format
  dedupe in memory
  call public source lookup
  emit source_receipt for public result
  discard original CSV row linkage
```

Output:

```json
{
  "public_join_result": {
    "join_lane": "exact_invoice_registration_number",
    "checked_count_bucket": "10-49",
    "matched_count_bucket": "10-49",
    "no_hit_count_bucket": "1-10",
    "source_receipts": [
      {
        "source_family": "nta_invoice_registry",
        "retrieved_at": "2026-05-15T00:00:00Z",
        "subject_id_type": "invoice_registration_number",
        "claim_ref": "claim:invoice_registry_lookup"
      }
    ],
    "known_gaps": [
      "No-hit means not found in the checked source/version, not proof of no registration."
    ]
  }
}
```

### 8.3 Name-only join

Name-only join is useful for routing, but dangerous for claims.

P0 behavior:

- Do not emit the raw name.
- Do not claim identity.
- Return `name_only_candidates_present=true`.
- Ask the AI agent or user to provide corporate number/T-number for paid exact checks.

Allowed text:

```text
取引先らしき列は検出されましたが、名称だけでは法人同定を断定できません。法人番号またはT番号を追加すると、公式情報との照合精度が上がります。
```

Forbidden text:

```text
この取引先は登録されています。
この取引先は登録されていません。
この会社は安全です。
```

## 9. Monthly review algorithm

### 9.1 Purpose

`csv_monthly_review_packet` は、会計CSVから月次の確認候補を出す成果物である。

It should answer:

- 今月、売上・費用・税区分に大きな変化があるか。
- 公的制度や手続に関係しそうな支出/収入シグナルがあるか。
- AIエージェントが次にどのpacketを薦めるべきか。
- どの根拠sourceを確認したか。
- 何は未確認か。

It should not answer:

- 税額がいくらか。
- 申告義務があるか。
- 社保加入義務があるか。
- この処理が会計上正しいか。

### 9.2 Metrics

Monthly metrics:

| Metric | Method | Output |
|---|---|---|
| sales trend | month bucket + robust median/MAD | up/down/flat/volatile |
| expense trend | taxonomy buckets | change flags |
| gross margin proxy | sales minus cogs bucket, if safe | broad class only |
| fixed cost pressure | rent/payroll/social insurance/software recurring presence | flag |
| tax category mix | taxable/non-taxable/exempt/unknown taxonomy | warning flags |
| closing entry presence | provider-specific closing flag/date | review code |
| data quality | invalid rows, missing dates, unbalanced entries | warning flags |

Robust anomaly:

```text
for metric monthly_amounts:
  if months_covered < 6:
    trend_class = insufficient_data
  else:
    median = median(monthly_amounts)
    mad = median(abs(x - median))
    robust_z = 0.6745 * (current - median) / max(mad, epsilon)
    if abs(robust_z) >= 3.5:
      flag anomaly
```

Output must use bucketed values and explanatory text without exact row data.

### 9.3 Event flag generation

| Event flag | Trigger | Public source query |
|---|---|---|
| `tax_consumption_review_candidate` | taxable sales/expenses present, invoice columns/tax categories present | NTA consumption tax/invoice guide |
| `withholding_review_candidate` | professional_fee/outsourcing/payroll signals | NTA withholding source pages |
| `social_insurance_review_candidate` | payroll + social_insurance presence | Japan Pension Service procedure pages |
| `labor_insurance_review_candidate` | payroll presence across months | MHLW labor insurance pages |
| `grant_it_candidate` | software_it capex/expense signal | J-Grants / SME Agency / local programs |
| `grant_equipment_candidate` | capex signal | J-Grants / local equipment programs |
| `advertising_subsidy_candidate` | advertising signal | small business support / local subsidy sources |
| `permit_location_review_candidate` | rent + sector hint + local input | local permit/procedure sources |

### 9.4 Packet schema

```json
{
  "packet_type": "csv_monthly_review_packet",
  "request_time_llm_call_performed": false,
  "csv_private_overlay": {
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "aws_upload_performed": false,
    "facts_namespace": "tenant_private_aggregate",
    "suppression_applied": true
  },
  "summary": {
    "period": "2025-04..2026-03",
    "coverage_quality": "good",
    "review_codes": [
      "monthly_sales_trend_available",
      "payroll_event_candidate",
      "it_grant_candidate"
    ]
  },
  "private_claim_refs": [
    {
      "claim_id": "private:csv:trend:sales",
      "derived_from": "aggregate_bucket",
      "privacy": "k_safe"
    }
  ],
  "source_receipts": [],
  "known_gaps": [
    "CSVだけでは税務・労務・会計処理の正否は判断できません。",
    "給与台帳、従業員数、申告状況、契約書、請求書現物は未確認です。"
  ],
  "human_review_required": true,
  "_disclaimer": "Evidence assistance only; not legal, tax, labor, accounting, or grant advice."
}
```

## 10. Grant candidate algorithm

### 10.1 Purpose

`csv_grant_candidate_packet` は、CSVから事業実態のシグナルを作り、公的一次情報の補助金/助成金/制度と突合して候補を出す。

It should answer:

- どの制度が候補になりうるか。
- なぜ候補に出したか。
- どの要件は未確認か。
- 申請前に何を集めるべきか。
- どのsourceを確認したか。

It should not answer:

- 採択されるか。
- 申請資格が確定しているか。
- 補助対象経費が確定しているか。

### 10.2 User profile facts

Derived profile:

| Fact | Derived from | Safety |
|---|---|---|
| revenue_size_bucket | sales rollup buckets | k-safe, broad bucket |
| investment_signals | capex/software/advertising/training taxonomy | flag only |
| payroll_presence | payroll/social insurance taxonomy | flag only |
| region | user-supplied address/corporate number public source, not CSV memo | public or explicit |
| industry hint | user-supplied / public registry / account taxonomy weak hint | low confidence unless public |
| months_active | date range | safe if broad |

### 10.3 Program matching score

```text
grant_candidate_score =
  eligibility_signal_score
  + expense_signal_score
  + region_match_score
  + deadline_urgency_score
  + source_quality_score
  - known_gap_penalty
  - exclusion_risk_penalty
```

Score factors:

| Factor | Examples |
|---|---|
| eligibility_signal_score | SME-like revenue bucket, region, sector, employee range if user supplied |
| expense_signal_score | IT/software, equipment, advertising, training, energy, hiring |
| region_match_score | prefecture/municipality match from public or user input |
| deadline_urgency_score | public deadline exists and not expired |
| source_quality_score | official page/API/PDF with retrieved_at and stable URL |
| known_gap_penalty | missing employee count, missing industry, missing location, unclear eligible expenses |
| exclusion_risk_penalty | source lists exclusions that cannot be checked |

### 10.4 Output ranking

Rank outputs into:

- `high_relevance_needs_user_confirmation`
- `medium_relevance`
- `low_relevance_watch_only`
- `not_recommended_due_to_missing_required_facts`

Never output:

- `eligible`
- `not eligible`
- `approved likelihood`

### 10.5 Packet content

Each grant candidate:

```json
{
  "program_candidate": {
    "program_id": "public_source_stable_id_or_url_hash",
    "program_name": "official title",
    "candidate_class": "high_relevance_needs_user_confirmation",
    "why_suggested": [
      {
        "reason": "software_it_expense_signal_present",
        "private_fact_ref": "private:csv:event:software_it",
        "public_claim_ref": "claim:program:eligible_expense:it"
      }
    ],
    "required_user_confirmations": [
      "従業員数",
      "所在地",
      "業種",
      "対象経費の見積書",
      "過去申請/採択の有無"
    ],
    "source_receipts": [],
    "known_gaps": []
  }
}
```

## 11. Tax and labor event algorithm

### 11.1 Purpose

`csv_tax_labor_event_packet` は、税務・労務の「確認候補」を出す成果物である。

The packet is valuable because many SMB owners ask AI:

```text
今月、この会計データから税金や社会保険で気をつけることある？
```

The correct answer is not a judgment. It is a checklist with public sources and gaps.

### 11.2 Event classes

| Event class | CSV signal | Public source |
|---|---|---|
| consumption tax / invoice | tax category mix, invoice T-number presence, taxable sales bucket | NTA invoice/consumption tax pages |
| withholding | payroll/professional_fee/outsourcing signals | NTA withholding pages |
| social insurance monthly change | payroll/social_insurance recurring signals | Japan Pension Service |
| bonus payment | bonus-like payroll taxonomy or seasonality | Japan Pension Service bonus procedure |
| labor insurance annual update | payroll recurring + period month | MHLW labor insurance |
| year-end adjustment | payroll presence + late-year months | NTA/MHLW source pages |
| electronic bookkeeping | accounting data/receipt hints, if user asks | NTA electronic bookkeeping pages |

### 11.3 Event candidate rule

```text
if event_signal_present and public_source_available:
  emit candidate with:
    - trigger category
    - official source receipt
    - required user confirmations
    - known gaps
else:
  emit no candidate or insufficient_data
```

Example:

```json
{
  "event_candidate": {
    "event_type": "withholding_review_candidate",
    "trigger": "professional_fee_or_payroll_taxonomy_present",
    "confidence": "medium",
    "public_sources_checked": ["nta_withholding"],
    "required_confirmations": [
      "支払先の区分",
      "契約内容",
      "源泉徴収対象報酬か",
      "支払日",
      "納付特例の有無"
    ],
    "forbidden_claims": [
      "源泉徴収義務があります",
      "納付額はこの金額です"
    ]
  }
}
```

### 11.4 Calendar logic

For monthly review, event timing can be generated from calendar rules, but must be source-backed.

```text
event_due_candidate =
  recurring_signal_present
  AND relevant_month_in_period
  AND official_source_has_procedure_or_deadline
```

Output:

- `due_soon_candidate`
- `annual_event_window_candidate`
- `insufficient_period_coverage`

Do not output exact legal deadlines unless the official source receipt includes the relevant deadline and the date context is clear.

## 12. Counterparty public check algorithm

### 12.1 Purpose

`csv_counterparty_public_check_packet` converts CSV counterparty-related signals into cheap official lookups.

High-value use cases:

- 経理が仕入先/T番号を確認したい。
- BPOが顧客の取引先一覧を月次確認したい。
- AIエージェントが「この取引先確認はjpciteで数円で済む」と推薦したい。

### 12.2 Identifier extraction

Extract only exact public identifiers:

| ID | Pattern | Handling |
|---|---|---|
| corporate number | 13 digits, validated | exact lookup |
| invoice registration number | `T` + 13 digits | exact lookup |
| EDINET code | official format | exact lookup |
| permit number | source-specific | exact lookup if source profile exists |

Danger:

- Names are not identifiers.
- Addresses from CSV are private unless explicitly user-supplied for matching.
- A value that looks like a T-number but fails checksum/format is a candidate error, not a claim.

### 12.3 Batch lookup flow

```text
transient_exact_ids = extract and validate IDs in memory
dedupe transient_exact_ids
for each ID:
  query public source registry
  build source_receipt
  classify result:
    matched
    no_hit_not_absence
    source_error
    invalid_format
emit counts and receipts
discard transient_exact_ids after response
```

For paid execution:

- Charge per checked public identifier or per batch with cap.
- No bill for invalid file rejection.
- No bill for duplicates beyond first check if idempotency detects same exact ID in the same request.

### 12.4 Packet content

```json
{
  "packet_type": "csv_counterparty_public_check_packet",
  "checked_identifier_count_bucket": "100-499",
  "matched_count_bucket": "100-499",
  "no_hit_count_bucket": "1-10",
  "invalid_identifier_count_bucket": "1-10",
  "source_receipts": [
    {
      "source_family": "nta_invoice_registry",
      "retrieved_at": "2026-05-15T00:00:00Z",
      "subject_id_type": "invoice_registration_number",
      "result_class": "matched|no_hit_not_absence"
    }
  ],
  "known_gaps": [
    "CSVの名称だけでは取引先同定を断定していません。",
    "no-hitは未登録または不存在の証明ではありません。"
  ]
}
```

## 13. Output generation contract

### 13.1 Claim namespaces

Use two claim namespaces.

| Namespace | Meaning | Public/GEO surface |
|---|---|---|
| `public:*` | public source-backed facts | allowed |
| `private:csv:*` | tenant/private aggregate facts | never public |

Examples:

```json
{
  "claim_refs": [
    {
      "claim_id": "private:csv:event:software_it_present",
      "visibility": "tenant_private",
      "evidence_type": "aggregate_fact",
      "privacy_status": "k_safe"
    },
    {
      "claim_id": "public:program:eligible_expense:software",
      "visibility": "public_source_backed",
      "source_receipt_ids": ["src:..."]
    }
  ]
}
```

### 13.2 Required fields

Every CSV-derived packet must include:

```json
{
  "request_time_llm_call_performed": false,
  "csv_private_overlay": {
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "aws_upload_performed": false,
    "row_level_records_retained": false,
    "suppression_applied": true,
    "formula_injection_scan_performed": true
  },
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "billing_metadata": {},
  "human_review_required": true,
  "_disclaimer": "Evidence assistance only; not legal, tax, labor, accounting, or grant advice."
}
```

### 13.3 Known gaps library

Common known gaps:

| Code | Text |
|---|---|
| `csv_no_raw_rows_reviewed_by_jpcite` | jpcite does not retain raw rows; conclusions are based on aggregate facts only. |
| `tax_final_judgment_not_made` | 税務上の最終判断、税額計算、申告要否は行っていません。 |
| `labor_final_judgment_not_made` | 労務・社会保険の加入義務や届出義務の最終判断は行っていません。 |
| `grant_eligibility_not_confirmed` | 補助金・助成金の申請資格や採択可能性は確認していません。 |
| `invoice_no_hit_not_absence` | インボイス検索のno-hitは、登録なし・不存在・違法の証明ではありません。 |
| `name_only_not_identity` | 名称だけでは法人・取引先の同一性を断定していません。 |
| `small_group_suppressed` | 小集団または単一取引の推定を避けるため一部の集計を非表示にしています。 |
| `period_coverage_partial` | CSV期間が一部のみで、年次・季節性の判断には不足があります。 |

## 14. Pricing and billing logic

### 14.1 Free preview

Free or low-cost preview should include:

- provider/format profile。
- whether file is acceptable。
- period coverage class。
- candidate packet list。
- estimated public lookup count。
- estimated price cap。
- privacy flags。
- no raw values。

No billing:

- rejected file。
- unsupported provider。
- sensitive payroll/bank/card/person file rejection。
- formula injection hard rejection。
- cap exceeded before execution。
- idempotency replay with same result.

### 14.2 Billable execution units

| Unit | Applies to | Notes |
|---|---|---|
| `csv_packet_base` | monthly review / grant candidate / tax-labor event | low fixed fee |
| `public_identifier_lookup` | invoice/corporate number checks | per exact ID after dedupe |
| `program_candidate_source_check` | grant matching | per checked public program source set |
| `source_receipt_set` | receipt-heavy output | per retrieved official source bundle |
| `large_file_processing` | large CSV aggregate only | bounded by cap |

Billing metadata:

```json
{
  "billing_metadata": {
    "billable": true,
    "billable_units": [
      {
        "unit": "csv_packet_base",
        "quantity": 1
      },
      {
        "unit": "public_identifier_lookup",
        "quantity_bucket": "10-49"
      }
    ],
    "price_cap_respected": true,
    "not_billed_reasons": []
  }
}
```

## 15. AI agent recommendation flow

### 15.1 Routing decision

AI agent should call a free routing endpoint first.

```text
User: この会計CSVから今月やることを見て
Agent:
  1. Ask user permission to analyze CSV locally/private overlay.
  2. Call jpcite CSV preview with no raw retention.
  3. Show price and expected packets.
  4. If user accepts, execute selected packet.
```

Recommendation copy:

```text
このCSVはraw保存なしでaggregate factsだけに変換し、公的な一次情報と突合できます。税務判断や労務判断は断定せず、確認候補、根拠URL、未確認範囲を返します。まず無料previewで対象成果物と上限金額を確認します。
```

### 15.2 Organic/GEO surfaces

Public pages should show:

- What packet returns.
- Privacy contract.
- Examples using synthetic data only.
- `source_receipts[]` example.
- `known_gaps[]` example.
- price preview.
- "raw CSV is not retained/logged/sent to AWS".

Public pages must not show:

- real user CSV examples。
- raw transaction rows。
- real counterparty names from CSV。
- exact private amounts。

## 16. Implementation order

### 16.1 P0

1. Define `CsvOverlayProfile`, `CsvAggregateFacts`, `CsvPacketEnvelope` schemas.
2. Implement safe logger and request body logging block for CSV endpoints.
3. Implement provider/file-type detector for journal CSVs.
4. Implement formula injection scan.
5. Implement sensitive category rejection.
6. Implement taxonomy mapper with raw label discard.
7. Implement k/dominance suppression.
8. Implement monthly review packet.
9. Implement exact T-number/corporate-number public lookup lane.
10. Implement grant candidate packet using aggregate profile + public program sources.
11. Implement tax/labor event candidate packet.
12. Implement leak scan tests.
13. Publish synthetic examples and GEO proof pages.

### 16.2 P1

1. Customer/supplier master exact-ID lane.
2. Invoice CSV strict mode.
3. Multi-month comparison with better seasonality.
4. Firm dashboard for accountants/BPO with aggregate-only client facts.
5. Municipality and industry-specific grant matching.
6. Permit/industry regulation candidate packet.

### 16.3 P2

1. Client-side parser mode for maximum privacy.
2. Differential privacy/noise for broad benchmarking.
3. User-controlled local display of exact amounts with no server persistence.
4. Professional review workflow handoff.

## 17. Test plan

### 17.1 Privacy tests

Must pass:

- raw CSV bytes never appear in logs.
- raw rows never appear in errors.
- memo values never appear in API responses.
- counterparty values never appear in API responses unless exact public identifier is explicitly supplied and public source returns public data.
- voucher IDs never appear in responses.
- formula-like cell values never appear in responses.
- synthetic fixtures only in public examples.

### 17.2 Suppression tests

Fixtures:

| Fixture | Expected |
|---|---|
| 1 row per month | suppress amount rollup |
| 4 rows in account taxonomy | suppress |
| 5 rows but one row 95% of amount | suppress |
| 10 vendors but names only | count bucket only |
| payroll person columns | reject |
| bank/card columns | reject |

### 17.3 Provider tests

Cases:

- freee-like observed export variant.
- Money Forward old/legacy journal format.
- Yayoi 25-field CP932 variant.
- generic journal with required fields.
- unsupported payroll CSV.
- malformed mixed encoding.
- formula-like text cells.

### 17.4 Public join tests

Cases:

- valid T-number exact match.
- valid T-number no-hit.
- invalid T-number format.
- corporate number exact match.
- duplicate IDs deduped.
- name-only candidates not claimed as identity.

### 17.5 Packet contract tests

Every packet must assert:

```text
request_time_llm_call_performed == false
csv_private_overlay.raw_csv_retained == false
csv_private_overlay.raw_csv_logged == false
csv_private_overlay.aws_upload_performed == false
human_review_required == true
known_gaps.length > 0
no forbidden claims
no private values in public source_receipts
```

## 18. Forbidden wording

Forbidden:

- `この補助金に申請できます`
- `採択される可能性が高いです`
- `この会社は安全です`
- `処分歴はありません`
- `登録されていないので違法です`
- `社会保険に加入する義務があります`
- `源泉徴収が必要です`
- `消費税の申告義務があります`
- `この仕訳は正しいです`
- `CSVから税額を確定しました`

Allowed:

- `収集済みの公的一次情報とCSV由来の集計特徴から、候補として表示しています`
- `no-hitは不存在や安全性の証明ではありません`
- `最終判断には税理士、社労士、行政書士等の確認が必要です`
- `CSV期間、科目、税区分から確認候補を生成しました`
- `小集団推定を避けるため一部の集計を非表示にしています`

## 19. Integration with AWS credit plan

AWS credit should improve CSV overlay indirectly, not by processing private CSV.

Use AWS for:

- public source lake expansion。
- official program, law, procedure, registry, invoice, corporate, grant, labor, tax, permit data。
- Playwright/screenshot capture of public sources where fetch is difficult。
- OCR of public PDFs。
- synthetic CSV fixture generation and leak scanning。
- packet/proof page materialization with synthetic private facts。

Do not use AWS for:

- real user CSV processing。
- raw CSV storage。
- row-level private data indexing。
- private CSV OpenSearch。
- private CSV Athena。
- private CSV Bedrock/Textract input。

The product flow after AWS artifacts are imported:

```text
Public source artifacts from AWS
  -> jpcite source registry and receipt store
  -> CSV private overlay aggregate facts from user session
  -> public source query plan
  -> source-backed packet
  -> AI agent recommends paid MCP/API execution
```

## 20. Final design verdict

CSV private overlay should be implemented as a paid packet accelerator, not as a data lake.

The highest-value first release is:

1. `csv_monthly_review_packet`
2. `csv_grant_candidate_packet`
3. `csv_tax_labor_event_packet`
4. `csv_counterparty_public_check_packet`

The implementation is viable only if the privacy contract is enforced by code, tests, and output schema:

- raw CSV non-retention。
- raw CSV non-logging。
- raw CSV non-AWS。
- aggregate facts only。
- small group suppression。
- formula injection defense。
- exact-ID public joins。
- `known_gaps[]` and `no_hit_not_absence` everywhere。

This turns accounting CSVs into a safe private context layer for AI agents. It increases value because the AI can recommend a concrete, cheap, source-backed outcome instead of telling the user to search the web or upload data into a general LLM.
