# CSV Privacy Edge Cases / Suppression Policy Deep Dive

作成日: 2026-05-15  
担当: CSV privacy edge cases / suppression policy  
状態: pre-implementation planning only  
制約: 実装コードは触らない。CSV raw は保存しない。個人名、給与、銀行、カード、電話、メール、取引先名、摘要、自由記述、行単位明細を packet/debug/log へ出さない。

## 0. Executive Contract

CSV を raw 保存しなくても、出力・debug・ログ・エラー・サポート文面・小さな集計セルから再識別は起きる。P0 の privacy contract は「保存しない」では足りず、「再構成できる形で返さない」「少数セルを出さない」「hash を安易に公開しない」「debug でも raw を見せない」までを含める。

P0 方針:

- CSV raw bytes、raw row、row-level normalized record、摘要、取引先名、個人名、電話、メール、住所、銀行口座、カード番号、給与個人別明細は保存も出力もしない。
- 外部 packet は aggregate-only を既定にし、`entry_count < 3` のセルは抑制する。組み合わせ属性で `k < 5` になりやすいブレークダウンは coarsen または非表示にする。
- hash は匿名化ではなく linkability control として扱う。出力公開は原則禁止。内部 dedupe に使う場合も tenant-scoped HMAC のみ。
- reject は失敗ではなく privacy-preserving outcome として扱う。給与台帳、銀行振込ファイル、カード明細、個人識別子が強く出る CSV は処理継続しない。
- debug/log は shape、counts、reject code、policy decision のみ。payload value、cell value、row sample、raw exception body を禁止する。

## 1. Edge Cases 一覧

### 1.1 直接 PII / 個人識別子

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 個人名が取引先列に入る | 従業員、個人外注、大家、患者、利用者、講師 | high | reject or aggregate-only with value drop | 名前列・取引先列の値は出さない。distinct count も small-cell 対象。 |
| 摘要に個人名が混入 | 立替、返金、面談、治療、送迎、給与メモ | high | redact field; if pervasive reject | 摘要 presence のみ許可。本文由来の要約は禁止。 |
| メールアドレス | 顧客連絡先、社員メール、請求先 | high | reject if value-bearing field | ドメイン集計も小規模企業では再識別しやすい。 |
| 電話番号 | 携帯、固定、FAX | high | reject | 下4桁表示も禁止。 |
| 住所 | 個人住所、施設住所、配送先 | high | reject or coarse area only | 町丁目・番地は出さない。都道府県単位でも k 条件をかける。 |
| 生年月日・年齢 | 扶養、従業員、利用者 | critical | reject | 年齢階級化しても small-cell なら出さない。 |
| 社員番号・会員番号・患者番号 | 内部 ID | critical | reject/hash internal only | 連番・固定長 ID は再照合しやすい。 |
| マイナンバー・基礎年金番号 | 12桁、年金、保険 | critical | reject | 部分 redaction で処理継続しない。 |

### 1.2 給与・人事・労務

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 給与台帳 CSV | 社員名、基本給、残業、控除、住民税 | critical | reject | 会計仕訳 CSV ではなく payroll processor 対象。 |
| 個人別給与仕訳 | `給料手当` + 従業員名 + 金額 | critical | reject | 勘定科目だけなら aggregate-only 可。 |
| 少人数部門別人件費 | 役員1名、部門2名 | high | suppress/coarsen | 部門・役職・月を組み合わせると個人給与になる。 |
| 役員報酬 | 役員名なしでも1名会社 | high | aggregate-only; suppress if small | 代表者や役員が公知の場合、金額が個人に結びつく。 |
| 扶養・社保・源泉 | 扶養人数、社保等級、源泉税額 | high | reject if person-level | 集計でも対象人数が小さい場合は非表示。 |
| 賞与・退職金 | 年数回の大口支給 | high | suppress if cell small | 月別・部門別に出すと個人推定される。 |

### 1.3 銀行・カード・決済

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 銀行振込ファイル | 銀行名、支店名、口座番号、口座名義、振込額 | critical | reject | 振込先・給与振込・支払先を含むため処理しない。 |
| 口座番号混入 | 摘要、取引先、メモ | critical | reject | 部分 masking しても処理継続しない。 |
| カード番号・加盟店番号 | 13-19桁、カード文脈 | critical | reject | Luhn-like 判定だけに依存しない。 |
| 銀行科目だけ | 普通預金、支払利息、借入金 | medium | aggregate-only | 口座番号・金融機関名・名義がなければ科目語彙として許可。 |
| クレカ明細 | 利用日、加盟店名、金額、利用者 | high | reject or strict aggregate-only | 加盟店名は取引先名として扱う。 |
| 決済 ID / 請求書番号 | 決済トランザクション、請求書ID | medium-high | redact/hash internal only | 顧客側システムで再照合可能。 |

### 1.4 取引先・摘要・自由記述

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 取引先名ランキング | 上位取引先、仕入先、顧客名 | high | reject for external packet | 法人名でも営業関係を暴露する。 |
| 取引先 distinct count | 取引先数、顧客数 | medium | allow if count-only and k-safe | 小さい業種・地域・月別では抑制。 |
| 摘要の要約 | LLM が摘要を短くまとめる | high | forbidden | raw を保存しなくても prompt/output 経由で漏れる。 |
| 摘要 keyword extraction | 「A病院」「B氏返金」等 | high | forbidden by default | sensitive classifier の内部判定だけに使う。 |
| 自由記述タグ | メモタグ、付箋、仕訳メモ | high | presence only | タグ名自体が固有名詞の場合がある。 |
| 一意な大口取引 | 1件だけの高額購入・売上 | high | suppress/coarsen | 金額・月・科目だけでも相手が推定される。 |
| ファイル名由来の主体名 | `ACME_2025_payroll.csv` | medium-high | redact in packet/log | ファイル名は private metadata として扱う。 |

### 1.5 業種固有の sensitive context

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 医療 | 患者名、診療科、自由診療、窓口負担 | critical | reject if patient/person values | 科目語彙だけなら aggregate-only。 |
| 福祉・介護 | 利用者名、送迎、施設、介護保険 | critical | reject if beneficiary values | 少人数セルは個人利用状況になる。 |
| 教育・保育 | 児童名、保護者名、教材費 | critical | reject if child/person values | 子ども関連は保守的に reject。 |
| 士業・相談 | 相談者名、事件名、案件名 | critical | reject if matter/person values | 依頼関係の存在自体が sensitive。 |
| 宗教・政治・労組 | 会費、寄付、団体名 | high | suppress/reject depending context | 取引先名や摘要由来の分類は禁止。 |
| 個人事業主 | 家賃、医療費、家族名、生活費 | high | aggregate-only with strict suppression | 家計情報と事業情報が混ざりやすい。 |

### 1.6 Derived / joined re-identification

| Edge case | 例 | 再識別リスク | P0 decision | Notes |
|---|---|---:|---|---|
| 小セルの月次推移 | 月 x 科目 x 部門で1件 | high | suppress/coarsen | `entry_count`, `distinct_subject_count` の閾値を両方見る。 |
| 複数 packet の差分攻撃 | A packet と B packet の差で1行を推定 | high | complementary suppression | 抑制セルの親・兄弟セルにも注意する。 |
| public source join | 取引先名を法人番号へ join | high | no raw name join output | CSV側名称は外部 packet に出さない。exact ID がユーザー入力で別途ある場合のみ。 |
| hash の辞書攻撃 | 取引先候補を総当たり | high | no public hash; tenant HMAC internal | unsalted SHA は禁止。 |
| unique amount | 端数金額・高額金額 | medium-high | bucket or suppress | 金額 exact value は aggregate 合計でも小セルなら危険。 |
| rare account vocabulary | 固有名詞入り補助科目 | medium-high | redact label or suppress | 勘定科目は許可、補助科目・タグは保守的に扱う。 |
| timestamp correlation | 作成日時、更新者、更新時刻 | medium-high | redact or aggregate coarse | 作成者名・操作時刻で従業員が推定される。 |

## 2. Decision Table: Redaction / Hash / Aggregate-only / Reject

### 2.1 Policy actions

| Action | Meaning | Allowed output | Forbidden output | Default use |
|---|---|---|---|---|
| `redact` | 値を出さず、存在や件数だけ残す | `field_present`, `redacted_count`, `sensitive_pattern_present` | 元値、部分値、例示値、LLM要約 | 摘要、自由記述、作成者、ファイル名 |
| `hash` | 内部 dedupe・idempotency 用に tenant-scoped HMAC を作る | internal-only hash id, not public | unsalted hash, public hash, cross-tenant stable hash | voucher id, row fingerprint, duplicate detection |
| `aggregate-only` | 行・個別値を捨て、十分大きい集計だけ出す | counts/sums/buckets with k rules | row list, exact counterparties, small cells | 勘定科目、月次、業種シグナル |
| `reject` | privacy risk が高く、処理継続しない | reject code, safe explanation, next safe step | cell sample, offending value, row number with value | 給与台帳、銀行振込、カード、個人ID |

### 2.2 Field decision matrix

| Input field / pattern | Example normalized field | Baseline decision | Escalate to reject when | Safe packet substitute |
|---|---|---|---|---|
| 個人名 | `counterparty`, `memo`, `creator` | redact | name-like values appear in person-context headers or sensitive industry | `person_like_value_present=true`, `redacted_count` |
| 法人取引先名 | `counterparty` | redact | sole proprietor/person-like, sensitive relationship, small file | `counterparty_field_present=true`, `distinct_counterparty_count` if k-safe |
| 摘要 / 仕訳メモ | `memo` | redact | PII, bank/card, medical/legal, payroll terms appear | `memo_present=true`, `memo_redacted=true` |
| 勘定科目 | `debit_account`, `credit_account` | aggregate-only | account label contains PII or free-text spillover | account class bucket, count if k-safe |
| 補助科目 | `subaccount` | aggregate-only with label review | person/vendor/project specific or `entry_count < 3` | `subaccount_present=true`, category bucket |
| 部門 | `department` | aggregate-only | small department/person-like department | coarser org bucket or `department_present=true` |
| 金額 | `amount` | aggregate-only | cell count below k or unique amount identifies person/transaction | rounded bucket, suppressed marker |
| 日付 | `entry_date` | aggregate-only | exact date + small cell | month or quarter bucket |
| 伝票番号 / 取引No | `voucher_id` | hash internal only | contains external invoice/customer/person ID | `voucher_id_present=true` |
| 作成者 / 更新者 | `creator`, `updater` | redact | any person-like value | `audit_meta_present=true` |
| メール | any | reject | always when value-bearing | `csv_pii_value_detected` |
| 電話 | any | reject | always when value-bearing | `csv_pii_value_detected` |
| 住所 | any | reject/coarse-only | person address, exact address, small area | `address_like_value_present=true` |
| 銀行口座 | any | reject | bank/branch/account/name cluster or account number pattern | `csv_bank_identifier_rejected` |
| カード番号 | any | reject | card-like sequence in payment context | `csv_card_identifier_rejected` |
| 給与個人別 | payroll headers/values | reject | employee + compensation/tax/social insurance cluster | `csv_payroll_file_rejected` |
| 税額列 | `tax_amount` | aggregate-only | row-level tax output requested | `tax_amount_column_present=true`, k-safe aggregate |
| ファイル名 | upload metadata | redact | contains person/company/payroll/bank identifiers | `file_profile_id`, vendor guess |

### 2.3 Pattern cluster decision matrix

| Detected cluster | Required action | Rationale | User-facing safe message |
|---|---|---|---|
| `payroll_identity` + `payroll_amount` | reject | 個人別給与・控除・税額が含まれる可能性が高い | `給与・人事系の個人別情報を含む可能性があるため、このCSVは集計packet化できません。` |
| `bank_transfer` + `account_identifier` | reject | 口座・名義・振込額の組み合わせは critical | `銀行口座または振込指示情報を含む可能性があるため処理を停止しました。` |
| `card_context` + `long_digit_sequence` | reject | PAN/決済識別子漏えい | `カードまたは決済識別子らしき情報を検出したため処理を停止しました。` |
| `person_context` + `contact_info` | reject | 個人連絡先が含まれる | `個人連絡先らしき情報を検出したため、raw値を扱わず停止しました。` |
| `memo_or_counterparty` + `sensitive_industry` | reject or local-only future mode | 医療・福祉・教育等は関係性自体が sensitive | `摘要・取引先に機微な個人関連情報が含まれる可能性があります。` |
| `account_only_payroll_or_bank_terms` | aggregate-only + review | 科目名だけなら会計語彙として扱える | `給与・銀行関連の科目が集計語彙として存在します。個別情報は出力していません。` |
| `formula_like_cell` | redact/reject depending field | 出力面の spreadsheet injection | `数式として解釈され得るセルを検出したため、その値は出力対象外です。` |
| `small_cell_after_grouping` | suppress/coarsen | 1-2件セルは取引・個人推定につながる | `少数セルのため、この内訳は抑制しました。` |

## 3. Small Cell Suppression / k-anonymity 風ルール

### 3.1 Core thresholds

P0 default thresholds:

| Metric | Default | Applies to | Notes |
|---|---:|---|---|
| `min_entry_count` | 3 | any numeric/text aggregate cell | `entry_count < 3` は suppress。 |
| `min_distinct_subject_count` | 3 | counterparty/person/vendor-like dimensions | 同じ主体の複数行だけで k を満たした扱いにしない。 |
| `min_distinct_periods` | 2 | period trend when exact month is shown | 1か月だけの rare activity は四半期/年へ coarsen。 |
| `min_group_k_for_sensitive_context` | 5 | payroll/bank/medical/welfare/education/person-heavy context | sensitive context は `k=5` を推奨。 |
| `max_single_contributor_share` | 0.80 | amount aggregates | 1主体・1行が合計の80%以上なら suppress or coarsen。 |
| `min_parent_count_for_breakdown` | 10 | enabling child breakdown | 親集合が小さい場合は子内訳を出さない。 |

P0 では統計的匿名化の厳密な保証を主張しない。`k-anonymity風` は product rule name ではなく、再識別抑制の実務ルールとして使う。

### 3.2 Suppression order

1. Reject-level cluster を先に判定する。reject 対象 CSV は aggregate 生成へ進まない。
2. Export allowlist にないフィールドを drop/redact する。
3. Grouping dimensions を coarse-first で選ぶ。既定は `year_or_quarter`, `account_class`, `vendor_family`, `presence flags`。
4. Candidate cell の `entry_count`, `distinct_subject_count`, `single_contributor_share` を計算する。
5. 閾値未満セルを primary suppression する。
6. 差分推定を防ぐため complementary suppression をかける。
7. 抑制理由は code と件数だけ出す。抑制セルの値、金額、ラベルは出さない。

### 3.3 Allowed and forbidden breakdowns

| Breakdown | Default | Why |
|---|---|---|
| Year x account class | allow if k-safe | 粗い会計活動を見るには十分。 |
| Month x account class | allow if k-safe; otherwise quarter | 月次は一意取引になりやすい。 |
| Month x exact account name | conditional | rare account は個別取引を示す。 |
| Month x department x account | suppress by default | 部門が少人数の場合、給与・案件が推定される。 |
| Exact date x amount | forbidden | 行明細に近い。 |
| Counterparty x amount | forbidden | 取引関係を直接出す。 |
| Memo keyword x amount | forbidden | 摘要本文の露出に近い。 |
| Creator/updater x period | forbidden | 従業員の作業・担当が推定される。 |
| Sensitive industry x beneficiary-like field | reject | 個人利用状況の推定につながる。 |

### 3.4 Complementary suppression

単に `entry_count < 3` のセルだけを隠すと、親合計と兄弟セルから抑制セルを引き算できる。

Required rules:

- 親合計を出す場合、子セルのうち1つだけ suppress しない。最低2セルを suppress するか、親合計を coarse/rounded にする。
- `total - visible_children = suppressed_child` が成立する内訳は出さない。
- 同じ dataset から複数 packet を作る場合、packet 間で同じ grouping policy と suppression state を共有する。
- suppress したセルの `count`, `sum`, `label`, `period`, `exact account` を debug/log にも出さない。
- Public example packet では synthetic counts を使い、実データの suppression pattern を再現しない。

### 3.5 Amount handling

| Amount output | P0 decision | Rule |
|---|---|---|
| Exact row amount | forbidden | 明細再構成になる。 |
| Exact aggregate sum | allow only if k-safe and not single-contributor dominated | `entry_count >= 3`, sensitive context は `>=5`。 |
| Rounded aggregate sum | preferred | 例: 千円/万円単位。small-cell には rounding だけでは不十分。 |
| Min/max amount | suppress by default | 外れ値は個別取引に近い。 |
| Median/percentile | conditional | 十分な n がある場合のみ。 |
| Top-N amount/category | suppress by default | ranking は一意性を強める。 |
| Variance/anomaly amount | review only | 「異常」ラベルが専門判断・個別推定につながる。 |

### 3.6 k-anonymity style pseudo-policy

```text
if reject_cluster_detected:
  return safe_reject_packet

drop all non-allowlisted fields
replace raw text dimensions with presence/count flags

for each requested aggregate:
  if grouping includes forbidden dimension:
    deny_breakdown
  if sensitive_context:
    min_k = 5
  else:
    min_k = 3
  if parent_count < 10 and child_breakdown_requested:
    coarsen_or_suppress
  for cell in aggregate.cells:
    if cell.entry_count < min_k:
      suppress(cell, reason="small_cell")
    if cell.distinct_subject_count is known and cell.distinct_subject_count < min_k:
      suppress(cell, reason="small_subject_count")
    if cell.single_contributor_share > 0.80:
      suppress(cell, reason="dominant_contributor")
  apply_complementary_suppression()
  emit only visible coarse cells and suppression summary
```

## 4. Packet Output Policy

### 4.1 Packet-level allowlist

Allowed fields:

- `packet_id`
- `created_at`
- `policy_version`
- `input_profile_id`
- `vendor_family_guess`
- `row_count`
- `column_count`
- `date_range` as month/quarter/year where k-safe
- `column_presence` flags
- `account_class_counts` with suppression
- `account_name_counts` only when labels are known safe and cells meet k thresholds
- `amount_aggregate` only when k-safe and not dominated by one row/subject
- `redacted_field_counts`
- `suppressed_cell_count`
- `suppression_reasons`
- `reject_code`
- `human_review_required`
- `known_gaps`

Forbidden packet fields:

- raw row, row sample, row index with value context
- 摘要本文、仕訳メモ、付箋、タグ名、自由記述
- 取引先名、顧客名、仕入先名、従業員名、作成者名、更新者名
- 電話、メール、住所、生年月日、個人ID、社員番号、会員番号
- 銀行名 + 支店 + 口座、口座名義、カード番号、決済ID
- 請求書番号、注文番号、伝票番号そのもの
- exact date + exact amount の組み合わせ
- top customer/vendor ranking
- suppressed cell values or labels
- public hash of private values

### 4.2 Packet examples by outcome

Safe allow packet shape:

```json
{
  "artifact": "csv_coverage_receipt",
  "policy_version": "csv_privacy_p0_2026-05-15",
  "row_count": 918,
  "column_count": 21,
  "date_range": {"from_month": "2024-04", "to_month": "2026-03"},
  "column_presence": {
    "memo": true,
    "counterparty": true,
    "tax_amount": true,
    "creator_meta": false
  },
  "privacy": {
    "raw_saved": false,
    "raw_values_output": false,
    "redacted_field_count": 4,
    "suppressed_cell_count": 7,
    "suppression_reasons": ["small_cell", "dominant_contributor"]
  },
  "known_gaps": ["raw_memo_not_available_in_packet", "small_cells_suppressed"],
  "human_review_required": true
}
```

Safe reject packet shape:

```json
{
  "artifact": "csv_privacy_reject",
  "policy_version": "csv_privacy_p0_2026-05-15",
  "decision": "reject",
  "reject_code": "csv_payroll_file_rejected",
  "safe_reason": "給与・人事系の個人別情報を含む可能性があるため、CSVの値を出力せず処理を停止しました。",
  "raw_saved": false,
  "raw_values_output": false,
  "next_safe_step": "個人別の列を含まない会計仕訳CSV、または合成・マスク済みサンプルで再実行してください。"
}
```

### 4.3 Packet copy rules

- 「何を検出したか」は value ではなく category で説明する。
- 「どの行か」は外部 packet では出さない。行番号も、ユーザーが raw CSV と突合できるため row-level pointer として扱う。
- 「何件あったか」は k-safe な範囲で出す。reject 時の offending count は出してもよいが、value・行・列の exact context は出さない。
- `human_review_required=true` は privacy issue と data quality issue を混同しない。理由 code を分ける。
- `known_gaps` は no-hit や専門判断境界を表す場所であり、raw 値の代替表示に使わない。

## 5. Debug / Log 禁止項目

### 5.1 Structured log allowlist

Allowed log attributes:

- `request_id`
- `tenant_hash` or `tenant_id_internal`
- `route`
- `artifact_type`
- `policy_version`
- `decision`
- `reject_code`
- `row_count_bucket` e.g. `1-99`, `100-999`, `1000-9999`
- `column_count`
- `file_size_bucket`
- `parse_duration_ms`
- `suppressed_cell_count`
- `redacted_field_count`
- `error_class`
- `retryable`

### 5.2 Absolute log/debug bans

Never log or show in debug:

- CSV raw bytes or decoded text
- row sample, first row, last row, random row
- raw headers when headers include PII-like names; use header category profile instead
- cell value, offending value, quoted excerpt
- 摘要、取引先、顧客、仕入先、従業員、作成者、更新者
- phone, email, address, ID, bank, card, invoice/customer identifiers
- exact file name if user supplied and not sanitized
- exact amount in parse errors
- exact date + amount + account in the same log line
- LLM prompt containing CSV-derived text
- LLM completion that quoted CSV-derived text
- raw exception message from CSV/parser/LLM/provider when it may include values
- API keys, env vars, secrets, request body, response body
- hashes of private values if those hashes are cross-tenant stable or user-visible

### 5.3 Debug UI / operator console rules

| Surface | Allowed | Forbidden |
|---|---|---|
| Admin request trace | request id, policy decision, counts, timings | raw payload, row samples, cell values |
| Sentry/error tracker | sanitized error class, stack without locals, route | local variables containing rows/cells, raw exception body |
| Support dashboard | safe packet, reject code, user-facing next step | uploaded filename if sensitive, raw CSV, flagged values |
| CLI verbose mode | schema profile, counts, suppression summary | `--print-rows`, `--show-offending-cell`, raw prompt |
| Test snapshots | synthetic data only | fixtures copied from real user CSV |
| Analytics | aggregate adoption and reject rates | customer-specific field values or filenames |

### 5.4 Error message policy

Bad:

```text
Line 42 contains invalid phone number "090-...." in column "社員携帯".
```

Good:

```text
個人連絡先らしき値を含む列が検出されたため、CSVの値を出力せず処理を停止しました。
code=csv_pii_value_detected
```

Bad:

```text
Suppressed account "A社 役員報酬" because count=1 and amount=...
```

Good:

```text
少数セルに該当する内訳があるため、一部の内訳を抑制しました。
code=csv_small_cell_suppressed
```

## 6. Hashing Policy

### 6.1 Hash is not anonymization

Private value hash を出力すると、取引先候補・氏名候補・メール候補を辞書攻撃で照合できる。特に日本語の取引先名、金融機関名、従業員名、メールドメインは候補空間が狭い。したがって hash は「内部の重複検知・idempotency・同一ファイル内 linkability」だけに限定する。

Rules:

- Public packet に private value hash を出さない。
- SHA-256(value) のような unsalted hash を禁止する。
- tenant-scoped HMAC を使い、pepper/secret は secret manager 管理にする。
- HMAC input は canonicalized value + field namespace + tenant namespace にする。
- cross-tenant matching を目的にした stable hash は P0 禁止。
- hash collision や normalizer bug があっても raw 値で debug しない。synthetic fixture で再現する。

### 6.2 Internal hash uses

| Use | Allowed? | Conditions |
|---|---:|---|
| Idempotency for same upload | yes | payload hash is internal only; not logged with payload metadata that identifies user data. |
| Duplicate row detection | yes | row fingerprint internal only, raw components dropped. |
| Distinct count estimation | yes | HMAC/set cardinality internal; only count output if k-safe. |
| Cross-file linkage within same tenant | conditional | explicit user intent, no public hash, no raw values. |
| Cross-tenant dedupe | no in P0 | high privacy risk. |
| User-visible "anonymous vendor id" | no in P0 | still linkable and dictionary-attackable. |

## 7. Reject Codes / Review Codes

| Code | Decision | Trigger | Safe output |
|---|---|---|---|
| `csv_payroll_file_rejected` | reject | payroll identity + compensation/tax/social insurance cluster | safe reject packet only |
| `csv_bank_identifier_rejected` | reject | bank transfer/account identifier cluster | safe reject packet only |
| `csv_card_identifier_rejected` | reject | card-like sequence in payment/card context | safe reject packet only |
| `csv_sensitive_identifier_rejected` | reject | マイナンバー, patient/student/employee ID, high-risk identifier | safe reject packet only |
| `csv_pii_value_detected` | reject | email/phone/address/person value in value-bearing field | safe reject packet only |
| `csv_sensitive_industry_person_context` | reject | medical/welfare/education/legal person-like values | safe reject packet only |
| `csv_formula_like_cell_detected` | redact/reject | formula-like cell in exportable field | redacted count or reject |
| `csv_free_text_redacted` | redact | memo/free text present | presence/count only |
| `csv_counterparty_redacted` | redact | counterparty/customer/vendor fields present | presence/distinct count only if k-safe |
| `csv_small_cell_suppressed` | aggregate-only | aggregate cell below threshold | suppression summary |
| `csv_dominant_contributor_suppressed` | aggregate-only | one contributor dominates aggregate | suppression summary |
| `csv_breakdown_denied` | aggregate-only | requested dimensions are too granular | coarser packet |
| `csv_hash_internal_only` | hash | dedupe/idempotency needed | no public hash |
| `csv_payroll_related_aggregate_only` | aggregate-only + review | account names only, no person values | review flag |
| `csv_bank_related_aggregate_only` | aggregate-only + review | bank account vocabulary only | review flag |

## 8. Testing / Acceptance Checklist

P0 acceptance tests should use synthetic fixtures only.

Required fixture cases:

- Payroll headers with employee name, base salary, tax, social insurance -> reject.
- Bank transfer headers with bank, branch, account number, account holder, amount -> reject.
- Card-like number in payment context -> reject.
- Email/phone/address in memo/counterparty -> reject.
- Person names in medical/welfare/education CSV -> reject.
- Accounting CSV with `給料手当`, `普通預金`, `支払利息` as account names only -> aggregate-only with review.
- Memo/counterparty fields present but not output -> `field_present` and `redacted_count`.
- Aggregate bucket with `entry_count=1` or `2` -> suppress.
- Sensitive context aggregate with `entry_count=3` but `min_k=5` -> suppress.
- Parent/child complementary suppression case -> at least two cells suppressed or parent total coarsened.
- Dominant contributor >80% -> suppress/coarsen.
- Formula-like cell beginning with `=`, `+`, `-`, `@`, tab, CR/LF -> no raw output.
- Parser error containing raw cell in exception -> scrubbed log/error.
- Debug mode on -> no raw row, header sample, cell value, prompt text, or completion text.
- Hash output check -> no user-visible private-value hash.

Acceptance conditions:

- No packet snapshot contains real/synthetic raw PII values except synthetic labels explicitly marked safe and not resembling real identities.
- No log snapshot contains CSV values, row samples, offending values, exact file names, exact row pointers, or raw exception bodies.
- Rejection responses are useful enough to tell the user which safe alternative to provide, without revealing the detected value.
- Suppression summaries explain that information was withheld for privacy without exposing the suppressed label or amount.

## 9. Implementation Guardrails for Future Work

- Build packet schemas as positive allowlists, not negative filters.
- Add privacy policy version to every CSV-derived packet so old packets can be audited.
- Treat LLM prompts/completions as output surfaces. Do not pass raw cell text to an LLM for summarization.
- Keep reject decisions before aggregation. Do not compute derived artifacts for reject-level files.
- Share suppression state across packet types for the same input profile to reduce differencing attacks.
- Keep operator tooling synthetic-first. Real user CSV debugging should use policy metadata, never raw samples.
- Document any future exception as a separate privacy review, not a silent schema change.

## 10. Open Questions

- Whether P1 should support a local-only mode that can process sensitive CSVs without server persistence or external packet generation.
- Whether exact account names should be allowlisted per vendor/account taxonomy, with unknown labels defaulting to category buckets.
- Whether `k=3` is sufficient for non-sensitive B2B accounting aggregates, or all CSV-derived public outputs should standardize on `k=5`.
- Whether rounded parent totals should be default whenever any child suppression occurs.
- Whether support workflows need an explicit raw attachment purge SLA and customer-facing no-raw-samples policy.
