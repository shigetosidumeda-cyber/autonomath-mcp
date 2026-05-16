# AWS final consistency 07/10: CSV / privacy / security review

作成日: 2026-05-15  
担当: 最終矛盾チェック 7/10 / CSV・privacy・security  
対象: AWS credit run、本体P0計画、公的一次情報拡張計画、CSV private overlay、成果物表示、GEO proof/API/MCP surface  
AWS実行: なし。AWS CLI/API、AWSリソース作成、ジョブ投入、デプロイは行っていない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

判定は **条件付きPASS**。

全体方針はほぼ整合している。特に次の中核は複数文書で一貫している。

- raw CSVは保存しない。
- raw CSVはログしない。
- raw CSVはAWS credit runへ送らない。
- AWSで扱うCSV関連物は synthetic / header-only / redacted fixture、provider alias、suppression/leak scan corpus、aggregate fact schema に限定する。
- CSVは公的一次情報ではなく private overlay として扱う。
- 成果物は private aggregate fact と public source receipt を分離する。
- `no_hit` は常に `no_hit_not_absence`。
- request-time LLMは使わない。
- 税務、会計、労務、許認可、与信、安全性、採択可否を断定しない。

ただし、このまま実装すると事故りやすい矛盾が残っている。最重要修正は以下。

1. AWS計画内の `private-overlay bucket` 表現は、実CSV由来aggregateをAWSへ置けるように読める。AWS credit runでは **実ユーザーCSV由来データを一切扱わない** と明記し、名前も `csv-fixture-lab` または `synthetic-csv-fixtures` に寄せる。
2. small group suppression の閾値が `k=3` と `k=5` で揺れている。P0外部成果物は `k_min=5`、counterparty/vendor-like は `k_min=10`、payroll/person/bank は reject に統一する。
3. `source_receipts[]` に CSV-derived receipt を同居させる設計は、AI agentが「CSVも公開根拠」と誤読しうる。外部表示では `private_overlay_receipts[]` または `receipt_kind=private_csv_derived` + `visibility=tenant_private` + `public_claim_support=false` を必須にする。
4. header-only / redacted fixture は、実CSVヘッダや実suppression patternをそのまま使うと漏えいしうる。AWSで使うfixtureは原則 synthetic generated fixture とし、実CSV由来なら headerもcanonical化・PII scan・review済みに限定する。
5. 成果物表示のallowlistをさらに狭める。公開GEO/proof/JSON-LD/OpenAPI/MCP examplesには、実CSV由来の row count、date range、suppression pattern、profile hash、取引先countすら出さない。

この5点を本体計画へマージすれば、CSV/privacy/security面の大きな矛盾は潰せる。

## 1. 精査対象

重点確認した文書:

- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_security_privacy_agent.md`
- `aws_credit_review_12_csv_privacy_pipeline.md`
- `aws_scope_expansion_08_smb_professional_outputs.md`
- `aws_scope_expansion_18_csv_overlay_algorithm.md`
- `aws_scope_expansion_24_agent_api_ux.md`
- `aws_scope_expansion_26_data_quality_gates.md`
- `aws_scope_expansion_28_production_release_train.md`
- `aws_scope_expansion_29_post_aws_assetization.md`
- `aws_final_consistency_01_global.md`
- `aws_final_consistency_02_aws_autonomous_billing.md`
- `aws_final_consistency_04_revenue_packets_pricing.md`
- `aws_final_consistency_05_algorithm_safety.md`
- `aws_final_consistency_06_release_train.md`
- `data_model_schema_deepdive_2026-05-15.md`
- `security_privacy_csv_deepdive_2026-05-15.md`
- `csv_privacy_edge_cases_deepdive_2026-05-15.md`
- `csv_provider_fixture_aliases_deepdive_2026-05-15.md`
- `public_packet_page_generator_deepdive_2026-05-15.md`

## 2. Final source-of-truth decisions

### 2.1 Data classes

以下を最終SOTにする。

| Data class | 例 | AWS credit run | 本体runtime | Public/GEO/proof |
|---|---|---:|---:|---:|
| `public_official_source_raw` | 官公庁HTML/PDF/API/CSV | allowed | allowed if needed | raw再配布はterms次第 |
| `public_official_source_normalized` | source receipt候補、claim候補 | allowed | allowed | gate通過後のみ |
| `synthetic_csv_fixture` | 公式形式に沿った合成CSV/header | allowed | tests only | synthetic明記で可 |
| `redacted_csv_fixture` | 実値を含まないreview済みfixture | conditional | tests only | 原則不可、必要ならsynthetic扱いに変換 |
| `private_accounting_csv_raw` | ユーザー投入CSV bytes/rows | forbidden | transient only | forbidden |
| `private_accounting_csv_row` | 正規化行、摘要、取引先、伝票No | forbidden | memory only | forbidden |
| `private_csv_aggregate_fact` | 月次/科目/期間/件数bucket | forbidden in AWS credit run | tenant private only | real dataは不可 |
| `private_csv_profile_fact` | provider, row bucket, column profile | forbidden in AWS credit run if real | tenant private only | real dataは不可 |
| `secrets` | API key, env, AWS credential | Secrets/runtime only | Secrets/runtime only | forbidden |
| `logs` | request id, status, counts | shape-only | shape-only | forbidden |

重要な区別:

- AWSで公的一次情報として取得するCSV、例えば法人番号やインボイスなどの公開CSVは `public_official_source_raw` であり、禁止対象の「private accounting CSV」とは別物。
- ユーザー投入の会計CSV、freee/Money Forward/弥生の仕訳CSV等は `private_accounting_csv_*` であり、AWS credit runへ送らない。

### 2.2 Immutable CSV privacy contract

実ユーザーCSVについて、以下は全surfaceで禁止する。

- raw bytes
- raw rows
- row-level normalized records
- row samples
- parse errorに含まれるcell値
- 摘要、仕訳メモ、付箋、タグの値
- 取引先、顧客、仕入先、従業員、作成者、更新者の値
- 伝票番号、取引No、請求書番号、口座番号、カード番号、社員番号、患者番号等の値
- unsalted hash、public hash、cross-tenant stable hash
- small cellから再構成できる金額、日付、科目、部門、取引先count
- 実データ由来のsuppression patternをpublic exampleへ載せること

許可されるのは、tenant privateでの以下だけ。

- provider family / format class / encoding
- row count bucket
- column count
- canonical header alias presence
- period bucketまたはmonth range。ただし小規模・機微文脈ではcoarsen
- account taxonomy bucket
- aggregate amount bucket
- presence flags
- review/reject codes
- `human_review_required`
- `known_gaps`
- public sourceとのexact-ID lookup結果。ただしtenant private responseに限定

## 3. 矛盾・弱点と修正契約

### C07-01. `private-overlay bucket` が実CSV AWS投入に読める

判定: critical

問題:

`aws_credit_security_privacy_agent.md` などに `private-overlay` bucket/prefix の設計がある。境界設計としては正しいが、AWS credit runの最終方針「raw CSV非AWS、synthetic/header-only/redacted fixtureのみ」と合わせると、実CSV由来aggregateをAWSへ置けるようにも読める。

採用修正:

AWS credit runでは、実ユーザーCSV由来のraw、row、aggregate、profile、hash、suppression patternをすべて禁止する。

```text
AWS_CREDIT_RUN_REAL_USER_CSV_ALLOWED=false
AWS_CREDIT_RUN_REAL_USER_CSV_AGGREGATES_ALLOWED=false
AWS_CREDIT_RUN_ALLOWED_CSV_CLASSES=synthetic_csv_fixture,header_only_synthetic_fixture,redacted_reviewed_fixture,public_official_source_csv
```

命名修正:

| 既存表現 | 採用表現 |
|---|---|
| `private-overlay bucket` | `csv-fixture-lab bucket` |
| `private-overlay-derived` | `synthetic-csv-derived` |
| `CSV-derived aggregate in AWS` | `synthetic CSV aggregate fixture in AWS` |

本当にprivate overlayを本体runtimeで扱う場合も、AWS credit runとは別の設計審査に分ける。今回のUSD 19,493.94消化計画では、実CSV private overlayをAWSへ入れない。

### C07-02. public official CSV と private accounting CSV が混同されやすい

判定: major

問題:

日本の公的一次情報にはCSV配布が多い。法人番号、インボイス、統計、調達、補助金、EDINET系メタデータなどはCSV/TSV/Excelで来る可能性がある。一方で、freee/MF/弥生のユーザー投入CSVはprivate accounting CSVである。

単に「CSV禁止」と書くと公的CSV収集を止めてしまい、「CSV許可」と書くと私的CSV流入を許してしまう。

採用修正:

`data_class` を必須にする。

```json
{
  "data_class": "public_official_source_csv",
  "source_family": "nta_invoice",
  "private_user_data_present": false,
  "allowed_in_aws_credit_run": true
}
```

```json
{
  "data_class": "private_accounting_csv_raw",
  "source_family": "user_uploaded_accounting_csv",
  "private_user_data_present": true,
  "allowed_in_aws_credit_run": false
}
```

AWS import validatorは、拡張子ではなく `data_class` と `source_profile` で判定する。

### C07-03. suppression閾値が `k=3` と `k=5` で揺れている

判定: major

問題:

複数文書に `entry_count < 3` の抑制ルールがある。一方、CSV overlay algorithmでは `k_min=5` や counterparty `k_min=10` も出てくる。P0外部成果物で `k=3` を使うと、少数事業者・個人事業主・給与/役員報酬・取引先関係が推定されやすい。

採用修正:

P0外部成果物の既定値を次に統一する。

| Context | `k_min` | 追加条件 |
|---|---:|---|
| 通常account/month aggregate | 5 | exact amount禁止、bucket表示 |
| counterparty/vendor/customer-like dimension | 10 | raw name禁止、IDもtenant privateのみ |
| department/person-heavy context | 10 | 部門名は原則出さない |
| payroll/person/bank/card/medical/student | reject | aggregate処理へ進まない |
| public synthetic fixture | synthetic only | 実suppression patternを再現しない |

`k=3` は内部実験・旧文書の下限としては残せるが、production public/API/MCPの外部成果物では使わない。

補完抑制も必須:

```text
visible_parent_total - visible_children != suppressed_child
```

この条件を満たせない場合、親合計をcoarsenするか、兄弟セルも追加で抑制する。

### C07-04. CSV-derived receipt と public source receipt が混ざる

判定: major

問題:

`data_model_schema_deepdive` では `source_receipts[]` に `private_csv_derived` を入れられる設計になっている。JSON shapeを共通化する意図は理解できるが、AI agentが `source_receipts[]` を「公開一次情報の根拠」として扱うと、CSV-derived private factが外部引用される危険がある。

採用修正:

外部payloadでは次のどちらかに統一する。

Option A, 推奨:

```json
{
  "source_receipts": [],
  "private_overlay_receipts": [
    {
      "receipt_kind": "private_csv_derived",
      "visibility": "tenant_private",
      "public_claim_support": false,
      "raw_csv_retained": false,
      "raw_csv_logged": false,
      "aws_upload_performed": false
    }
  ]
}
```

Option B, 互換維持:

```json
{
  "source_receipts": [
    {
      "receipt_kind": "private_csv_derived",
      "source_kind": "accounting_csv",
      "fact_visibility": "private_aggregate_only",
      "visibility": "tenant_private",
      "public_claim_support": false,
      "agent_quote_allowed": false,
      "source_url": null
    }
  ]
}
```

禁止:

- `private_csv_derived` を public proof page の根拠URL欄に出す。
- CSV-derived factを `public_source_fact` として `claim_refs[]` に載せる。
- AI向けanswer boxでCSV-derived factを一般化して引用させる。

### C07-05. header-only / redacted fixture の安全性が過信されている

判定: major

問題:

header-only fixtureでも、実企業独自の補助科目、部門名、担当者名、案件名、医療/福祉/教育の機微ヘッダが混ざる可能性がある。redacted fixtureでも、列順、行数、suppression pattern、異常値分布から実データの性質が漏れる可能性がある。

採用修正:

AWSで使うCSV fixtureは優先順を固定する。

1. 公式仕様から生成した synthetic header fixture
2. provider alias検証用に手作りした synthetic variant fixture
3. redaction済みかつreview済みのfixture
4. 実CSV由来headerは原則不採用。採用する場合もcanonical alias mapへ変換し、raw headerを捨てる

fixture manifestに必須:

```json
{
  "fixture_id": "csvfix_mf_official_27_synthetic",
  "fixture_origin": "synthetic_from_official_spec",
  "real_customer_data_used": false,
  "raw_header_from_real_csv_used": false,
  "raw_row_from_real_csv_used": false,
  "suppression_pattern_from_real_csv_used": false,
  "public_example_allowed": true
}
```

### C07-06. exact ID join が取引関係漏えいになる

判定: major

問題:

CSVにT番号や法人番号が含まれる場合、公式照合自体は高精度にできる。しかし「このユーザーのCSVにそのIDが含まれる」ことは取引関係の私的情報である。公式情報そのものはpublicでも、join関係はprivateである。

採用修正:

CSV由来ID joinは2モードに分ける。

| Mode | 入力 | 出力 |
|---|---|---|
| `csv_overlay_summary` | CSV内のID候補をtransient検出 | 件数bucket、match/no-hit bucket、known gapsのみ |
| `explicit_id_batch_check` | ユーザーが別途明示した法人番号/T番号リスト | tenant privateでID別のpublic source receiptを返せる |

CSVから抽出したIDを自動でID別一覧表示しない。ID別結果を返す場合は、ユーザーが明示的に「このIDリストを照合する」と承認したpayloadに分ける。

name-only joinはP0外部成果物では identity claim にしない。

許可文:

```text
取引先らしき列は検出されましたが、名称だけでは法人同定を断定できません。法人番号またはT番号を追加すると、公式情報との照合精度が上がります。
```

禁止文:

```text
この取引先は登録されています。
この会社は安全です。
登録がないため問題があります。
```

### C07-07. 成果物表示allowlistがまだ広い

判定: major

問題:

一部schemaでは `row_count`, `date_min`, `date_max`, `account_original`, `debit_amount_sum`, `credit_amount_sum` などが保存可能に見える。tenant private内部では必要な場合があるが、agent-facing payloadやpublic exampleでは広すぎる。

採用修正:

surface別allowlistを固定する。

| Surface | 実CSV由来表示 | 許可 |
|---|---|---|
| public proof page | 不可 | synthetic only |
| JSON-LD | 不可 | product metadata only |
| OpenAPI example | 不可 | synthetic only |
| MCP catalog/example | 不可 | synthetic only |
| llms.txt / well-known | 不可 | tool description only |
| unauthenticated preview | 原則不可 | file未投入の価格/必要項目説明のみ |
| authenticated CSV analyze response | 可 | bucket/profile/reject codeのみ |
| authenticated paid packet | 可 | k-safe aggregate、known gaps、private overlay receipt |
| logs/telemetry | 不可 | counts/status/reject code only |
| AWS credit run artifact | 不可 | synthetic fixture/schema/test result only |

実CSV由来の公開禁止フィールド:

- exact `row_count`
- exact `date_min` / `date_max`
- exact amount sums
- exact account labels
- exact department labels
- raw header labels
- suppression pattern
- ID別join結果
- profile hash
- tenant-scoped HMAC

tenant private responseでも原則bucket化する。

### C07-08. formula injection対策が出力面まで固定されていない

判定: major

問題:

複数文書でformula-like cell検出は書かれている。しかし、将来CSV/XLSX/Sheets export、Markdown table、HTML、JSON example、support toolで再露出する可能性がある。raw値禁止だけでは、header値やderived labelに混入した数式文字列を防ぎきれない。

採用修正:

入力時と出力時の二重防御にする。

```text
is_formula_like(value):
  normalized = unicode_nfkc(value)
  stripped = strip_leading_spaces_tabs_crlf(normalized)
  if strict_numeric_parse(stripped):
    return false
  return stripped starts_with one_of("=", "+", "-", "@")
```

出力ルール:

- raw cell valueは出さない。
- raw header labelもpublicには出さない。
- derived labelにformula-like文字列が混ざる場合は `redacted_label` に置換する。
- CSV/XLSX exportを追加する場合、aggregate-only allowlistを通し、文字列はsingle quote escapeを追加する。
- testsに `=`, `+`, `-`, `@`, tab, CR/LF, 全角変換後prefixを入れる。

### C07-09. public official source内の個人情報が別リスクとして残る

判定: major

問題:

AWS拡張計画は公的一次情報を広く集める。官報、行政処分、許認可、インボイス、裁判例、自治体資料には、個人事業主名、代表者名、住所、処分対象個人、事件関係情報が含まれる場合がある。公表情報であっても、GEO proofやAI agent向けpacketで過度に集約すると、人物プロファイリングや不必要な再拡散になる。

採用修正:

public source PII gateを追加する。

```json
{
  "public_personal_info_policy": {
    "personal_info_present": true,
    "source_published_by_official_body": true,
    "display_policy": "minimum_necessary",
    "geo_example_allowed": false,
    "bulk_profile_allowed": false,
    "human_review_required": true
  }
}
```

原則:

- public source receiptとして取得事実は保持できる。
- proof pageには実個人名を出さない。必要なら架空/synthetic例にする。
- 個人名を軸にしたrisk score、ranking、watchlistはP0禁止。
- 公的に公開されている個人情報でも、CSV private overlayとjoinしない。

### C07-10. Playwright screenshotがprivate/PIIを固定化しうる

判定: major

問題:

Playwright/1600px以下screenshotは、fetch困難な公的ページの証跡として有効。ただし、スクリーンショットは本文よりも広くPIIや不要情報を含みやすい。ログイン画面、検索条件、cookie banner、個人名入り一覧、CAPTCHA等も固定化しうる。

採用修正:

Playwright laneに以下を必須化する。

```json
{
  "screenshot_receipt": {
    "max_edge_px": 1600,
    "public_page_only": true,
    "login_required": false,
    "captcha_or_access_control_bypassed": false,
    "user_private_input_present": false,
    "personal_info_visible": "none|public_official_minimized|present_review_required",
    "public_publication_allowed": false,
    "claim_support_requires_text_span": true
  }
}
```

スクリーンショット単体でclaimを支えない。必ずDOM/text/OCR span、URL、timestamp、hash、source_profile gateに紐づける。

### C07-11. logs/telemetry/errorが最大の漏えい経路になる

判定: critical

問題:

「raw CSVを保存しない」と言っても、parse error、validation error、debug log、Sentry breadcrumb、CloudWatch log、Batch stdout、Athena result、OpenSearch debug indexに値が出れば同じ事故になる。AWS自走設計では、Codex/Claude不在時にログが膨らむため特に危険。

採用修正:

CSV関連endpoint/jobのログallowlist:

```json
{
  "request_id": "req_...",
  "tenant_hash": "tenant_hmac:...",
  "route": "csv_analyze",
  "data_class": "private_accounting_csv_raw",
  "file_size_bucket": "1-10MB",
  "row_count_bucket": "1000-4999",
  "column_count": 25,
  "provider_family": "money_forward",
  "format_class": "old_format",
  "reject_codes": [],
  "suppressed_cell_count_bucket": "10-49",
  "duration_ms_bucket": "1s-5s"
}
```

ログ禁止:

- request body
- response body
- raw header
- raw row
- offending value
- row number + value context
- file name
- S3 object keyに顧客名/ファイル名
- API key
- stack trace内のpayload

AWS credit runのjob definitionsにも `NO_PAYLOAD_LOGGING=true`、`REAL_USER_CSV_ALLOWED=false`、`LOG_LEVEL=INFO`、`DEBUG_DUMP_ALLOWED=false` を入れる。

### C07-12. idempotency/hashが匿名化として誤用されうる

判定: major

問題:

CSVのraw file hash、memo/counterparty hash、voucher hashを公開またはcross-tenantで安定化すると、辞書攻撃や再識別に使える。`column_profile_hash` も実headerが固有なら漏えいになる。

採用修正:

Hashの扱い:

| Field | Public | Tenant private | Internal only |
|---|---:|---:|---:|
| raw CSV byte hash | forbidden | forbidden | avoid |
| memo/counterparty hash | forbidden | forbidden | avoid |
| voucher_id HMAC | forbidden | forbidden | transient/internal only |
| column_profile_hash | forbidden for real CSV | allowed only if canonicalized | internal |
| intake_profile_id | forbidden public | allowed | tenant HMAC |
| response_body_hash | allowed if no private data | allowed | allowed |

`hash` は匿名化ではなくlinkability controlである、と文書に明記する。

### C07-13. RC3 CSV overlay paid化が早すぎると本番事故になる

判定: major

問題:

CSV overlayは売上価値が高いが、初期デプロイで同時に出すとprivacy/security gateが追いつかない。`aws_final_consistency_06_release_train.md` はRC3に遅らせる方針で整合しているが、売上文書ではP0-Aのように見える箇所がある。

採用修正:

商品優先度とrelease順を分ける。

| 観点 | CSV overlay |
|---|---|
| 事業価値 | P0-A |
| 本番release順 | RC3 |
| AWS credit runでやること | synthetic fixture、schema、leak scan、suppression tests |
| 実ユーザーCSV処理 | production privacy gate後 |
| paid化 | preview/local-only/analyzeが安定後 |

RC1/RC2では、実CSVを使わない `company_public_baseline`、`invoice_vendor_public_check`、`source_receipt_ledger`、`evidence_answer` を先に売る。

## 4. 修正後のmerged execution order

CSV/privacy/security観点で、本体計画とAWS計画の順序は次に固定する。

### Phase 0: Contract freeze

本体実装前に固定する。

- `data_class` enum
- `private_overlay_receipts[]` または `private_csv_derived` visibility contract
- CSV surface別allowlist
- `k_min=5/10/reject` suppression policy
- formula injection policy
- public source PII gate
- Playwright screenshot privacy gate
- log/telemetry allowlist
- hash/idempotency policy
- fixture manifest schema

### Phase 1: AWS guardrails

AWS credit run開始前に入れる。

- `REAL_USER_CSV_ALLOWED=false`
- `REAL_USER_CSV_AGGREGATES_ALLOWED=false`
- bucket/prefix `data_class` enforcement
- public official CSV と private accounting CSV の分類テスト
- CloudWatch payload logging禁止
- Batch job stdout/stderr sanitizer
- S3 object key sanitizer
- Athena/OpenSearch/Glue scopeでprivate CSV禁止
- promotion roleは `public-safe/manifest` のみ読める

### Phase 2: AWS public corpus and synthetic CSV lab

AWSで動かす。

- 公的一次情報のsource lake
- public official CSV ingestion
- source receipts / claim refs / known gaps
- Playwright public source capture
- synthetic/header-only/redacted reviewed CSV fixture
- provider alias map
- suppression/leak scan test corpus
- public proof fixture generation

AWSで動かさない。

- 実ユーザーCSV upload
- 実ユーザーCSV aggregate generation
- 実ユーザーCSV profile hashing
- 実CSV由来counterparty join
- 実CSV由来ID別receipt

### Phase 3: RC1 static/free/limited paid

CSV関連は公開説明とsynthetic exampleだけ。

- proof pagesはsynthetic CSV exampleのみ
- OpenAPI/MCP exampleもsyntheticのみ
- route/cost previewは無料
- paid packetはCSVなしの3本から開始
- `agent_routing_decision` は無料control

推奨RC1 paid:

```text
evidence_answer
source_receipt_ledger
company_public_baseline
```

### Phase 4: RC2 public-source verticals

CSVなしでも売れる公的一次情報packetを優先する。

- invoice vendor public check
- counterparty public DD
- grant candidate shortlist without CSV
- permit scope checklist without CSV
- reg change impact
- administrative disposition radar

### Phase 5: RC3 CSV preview

実ユーザーCSVはここで初めて扱う。

条件:

- no-store endpoint
- request/response body log disabled
- formula scan
- PII/payroll/bank reject
- aggregate-only
- suppression/coarsening
- leak scan
- no public examples from real data
- no AWS dependency

### Phase 6: RC3 limited paid CSV overlay

previewが安定した後に低capでpaid化。

有効化候補:

- `csv_monthly_public_review_packet`
- `csv_grant_candidate_packet`
- `csv_tax_labor_event_packet`
- `csv_counterparty_public_check_packet`

必須:

- cap token
- idempotency key
- no-charge for reject/validation/cap failure
- tenant-private only
- human_review_required=true
- professional fence

### Phase 7: AWS final export and zero-bill teardown

AWS側に実CSVがないことをexport manifestで検査してから削除する。

cleanup前の必須証跡:

- `real_user_csv_artifact_count=0`
- `private_accounting_csv_raw_count=0`
- `private_csv_aggregate_fact_count=0`
- `synthetic_csv_fixture_count>0`
- `public_official_source_csv_count>=0`
- leak scan pass
- manifest/checksum outside AWS

## 5. Required gates

### 5.1 AWS CSV/privacy gate

AWS run全体のGO条件。

```json
{
  "gate_id": "aws_csv_privacy_gate",
  "required": true,
  "real_user_csv_allowed": false,
  "private_accounting_csv_raw_count": 0,
  "private_accounting_csv_aggregate_count": 0,
  "synthetic_fixture_manifest_required": true,
  "public_official_csv_classification_required": true,
  "payload_logging_disabled": true,
  "promotion_manifest_public_safe_only": true
}
```

NO-GO:

- `private-overlay` prefixへ実ユーザー由来objectが1件でもある。
- CloudWatchにCSV cell値が出ている。
- failed/debug prefixにraw parse dumpがある。
- OpenSearch/Athena/Glueがprivate CSVを読める。

### 5.2 Public proof gate

公開ページのGO条件。

- sample fixtureは `sample_fixture=true`
- `real_customer_data_used=false`
- raw CSVなし
- raw headerなし
- row sampleなし
- exact amountなし
- exact row countなし
-実suppression patternなし
- `request_time_llm_call_performed=false`
- no-hit caveatあり
- professional fenceあり
- JSON-LDにprivate valueなし

### 5.3 API/MCP CSV gate

実CSV endpointのGO条件。

- anonymous CSV upload不可
- paid broad workはcap token必須
- `Idempotency-Key` 必須
- request body logging disabled
- response body logging disabled
- rejectはno-charge
- validation/cap/idempotency conflictはno-charge
- raw CSV retained=falseをresponseに返す
- `aws_upload_performed=false` をresponseに返す
- leak scan pass

### 5.4 Packet output gate

CSV overlay packetのGO条件。

```json
{
  "csv_private_overlay": {
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "aws_upload_performed": false,
    "row_level_records_retained": false,
    "free_text_values_retained": false,
    "counterparty_values_retained": false,
    "suppression_policy": "p0_k5_k10_reject_sensitive",
    "formula_injection_scan_performed": true
  },
  "quality": {
    "human_review_required": true,
    "not_tax_or_legal_or_accounting_opinion": true
  }
}
```

## 6. Mandatory test matrix

実装前に以下をP0 test backlogへ入れる。

| Test | Expected |
|---|---|
| freee/MF/Yayoi synthetic official headers | provider detected、official/variant/old_formatが正しい |
| Desktop observed variant headers converted to synthetic | raw valuesなしでalias map生成 |
| payroll headers | reject、no bill、rawなし |
| bank transfer headers | reject、no bill、rawなし |
| card/payment identifier | reject、rawなし |
| email/phone/address in free text | reject or local-only future、rawなし |
| formula-like cell in memo | value not emitted、reason code only |
| formula-like header | header redacted、canonical alias only |
| negative numeric amount | strict numericならformula扱いしない |
| k<5 monthly account cell | suppressed |
| counterparty-like k<10 | suppressed |
| dominant contributor >80% | suppressed |
| complementary suppression | parent/child差分で復元不能 |
| exact ID from CSV | count bucket by default、ID別表示なし |
| explicit ID batch | tenant privateのみ、public proof不可 |
| name-only join | candidate only、identity claimなし |
| public proof generation | syntheticのみ、real CSV漏えいゼロ |
| OpenAPI/MCP examples | syntheticのみ |
| JSON-LD | product metadataのみ |
| log scan | CSV cell/header/raw row/API keyなし |
| error path | offending valueなし |
| AWS artifact manifest | real_user_csv_artifact_count=0 |
| Playwright screenshot with public PII | publication_allowed=false |

## 7. Implementation backlog to merge

CSV/privacy/securityで本体計画へ追加すべきP0 tasks。

| ID | Task | Blocks |
|---|---|---|
| CSV-P0-01 | `data_class` enumとvalidator | AWS run、import |
| CSV-P0-02 | synthetic fixture manifest schema | AWS synthetic lab |
| CSV-P0-03 | no-store CSV analyze endpoint contract | RC3 preview |
| CSV-P0-04 | request/response/log scrubber for CSV routes | RC3 preview |
| CSV-P0-05 | formula injection scanner + output sanitizer | all exports |
| CSV-P0-06 | PII/payroll/bank/card reject classifier | RC3 preview |
| CSV-P0-07 | suppression engine `k5/k10/reject` | RC3 packet |
| CSV-P0-08 | complementary suppression state sharing | multi-packet CSV |
| CSV-P0-09 | private overlay receipt schema | packet contract |
| CSV-P0-10 | public proof leak scanner | RC1 pages |
| CSV-P0-11 | OpenAPI/MCP synthetic example gate | RC1/RC3 |
| CSV-P0-12 | AWS artifact manifest CSV counters | AWS run |
| CSV-P0-13 | public source PII gate | broad corpus |
| CSV-P0-14 | Playwright screenshot privacy gate | screenshot lane |
| CSV-P0-15 | idempotency/HMAC no raw hash policy | paid CSV |

## 8. Final decision

CSVは、jpciteの売上を伸ばす強い入力になる。ただし、AWS credit runで実CSVを扱うべきではない。

今回のAWS creditは、公的一次情報の拡張、source receipts、claim refs、known gaps、no-hit ledger、proof pages、GEO eval、そしてCSV overlayを安全に実装するための synthetic fixture/test corpus に使う。

実ユーザーCSVは、本体productionで no-store / no-log / non-AWS / aggregate-only / suppressed / tenant-private として後段に入れる。

この順番なら、次の3つを同時に満たせる。

1. AWSクレジットを公的一次情報と安全なテスト基盤へ高速に変換できる。
2. 実CSV漏えい・ログ漏えい・公開例漏えいを避けられる。
3. AIエージェントが安く推薦できるCSV overlay成果物を、RC3で安全に売り物にできる。
