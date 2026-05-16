# AWS smart methods round3 08: CSV / private overlay

作成日: 2026-05-15
担当: Round3 追加スマート化 8/20 / CSV private overlay
対象: 会計CSV、private overlay、derived aggregate facts、公的一次情報との突合、memory-only parsing、AI agent推薦、売上化、正本計画へのマージ
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。出力はこのMarkdownのみ。

---

## 0. 結論

判定: **追加価値あり。既存のCSV private overlay方針は安全側で正しいが、まだ「CSVを解析してaggregate factsにする」段階に寄っている。よりスマートにするなら、CSVを保存対象ではなく `PrivateFactCapsule` へ一時コンパイルし、公的一次情報の証拠グラフとは分離したまま、成果物コンパイラへ接続するべき。**

今回採用すべき追加機能は以下。

1. `Private Overlay Compiler`
2. `PrivateFactCapsule`
3. `Local-First CSV Fact Extractor`
4. `Memory-Only Server Fallback`
5. `Safe Aggregate Fact Algebra`
6. `Suppression Lattice`
7. `Private/Public Join Planner`
8. `Join Relationship Privacy Boundary`
9. `Private Evidence Lens`
10. `CSV Outcome Contract Router`
11. `Agent CSV Purchase Decision`
12. `Privacy Receipt`
13. `Ephemeral Overlay Session`
14. `Anti-Differencing Query Budget`
15. `CSV Fixture Lab`
16. `Private Overlay Release Gate`

最重要の修正はこれである。

```text
CSV parser -> aggregate facts -> packet
```

ではまだ弱い。

```text
CSV/private input
-> local-first or memory-only parse
-> PrivateFactCapsule
-> policy decision
-> private/public join plan
-> public source receipts
-> private evidence lens
-> paid packet / agent_purchase_decision
```

にする。

この変更により、以下を同時に満たせる。

- raw CSVをAWSへ入れない。
- raw CSVを保存しない。
- raw CSVをログしない。
- 公的一次情報の `source_receipts[]` とCSV由来private factsを混ぜない。
- AI agentが「CSVを投げれば便利」と推薦しやすい。
- エンドユーザーは安く成果物を取れる。
- jpciteはCSVを持たずに売上を増やせる。
- AWS credit runは synthetic fixture / parser tests / leak scan / public evidence拡張にだけ使える。

---

## 1. 既存計画との整合

### 1.1 維持する前提

今回の提案は、次の正本前提を変更しない。

- real user CSV はAWS credit runへ送らない。
- raw CSV bytesは保存しない。
- row-level normalized recordsは保存しない。
- memo、摘要、取引先名、伝票番号、請求番号、銀行、カード、給与、個人情報は外部成果物へ出さない。
- CSV由来の情報は公的一次情報ではない。
- `source_receipts[]` は公的一次情報用に維持する。
- CSV由来証跡は `private_overlay_receipts[]` または `receipt_kind=private_csv_derived` として分離する。
- `public_claim_support=false` をCSV由来private factsへ必ず付ける。
- no-hitは常に `no_hit_not_absence`。
- request-time LLMで事実claimを作らない。
- proof page、MCP examples、OpenAPI examples、JSON-LDへ実CSV由来データを出さない。

### 1.2 既存案から深掘りする対象

既存文書で既に決まっているもの:

- `memory-only raw parsing`
- `tenant-private aggregate facts`
- `private_overlay_receipts[]`
- `external k_min=5`
- `counterparty-like facts k_min=10`
- payroll / bank / personal identifier files reject
- AWS credit runは synthetic/header-only/redacted fixture のみ
- freee / Money Forward / Yayoi 形式のvariant対応
- formula injection検出
- raw CSV leak scan

今回の追加は、これらを置き換えない。より上位の仕組みに束ねる。

---

## 2. 追加スマート化の中核

### 2.1 CSVを「データ」ではなく「一時的な私的文脈」として扱う

CSVはjpciteの公的情報基盤へ混ぜるべきではない。

CSVが提供する価値は、公開事実そのものではなく、ユーザーの業務文脈である。

例:

- この会社は今期に広告費が増えているかもしれない。
- この会社はIT投資があるかもしれない。
- この会社は給与・法定福利費があるかもしれない。
- この会社はインボイス番号や法人番号を含む取引先一覧を持っているかもしれない。
- この会社は補助金・助成金・税労務イベントを確認する価値があるかもしれない。

したがって、CSVから作るべきものは「公開claim」ではなく、privateな `demand and context signal` である。

### 2.2 `PrivateFactCapsule`

`PrivateFactCapsule` は、raw CSVを保存せず、成果物生成に必要な最小限のsafe factsだけを一時的に入れる構造である。

```json
{
  "object_type": "PrivateFactCapsule",
  "schema_id": "jpcite.private_fact_capsule.v1",
  "capsule_id": "pfc_...",
  "tenant_scope": "tenant_private",
  "visibility": {
    "public_proof": "forbidden",
    "json_ld": "forbidden",
    "openapi_examples": "forbidden",
    "mcp_examples": "forbidden",
    "authenticated_packet": "allowed_minimized"
  },
  "raw_csv_retained": false,
  "raw_csv_logged": false,
  "raw_csv_sent_to_aws": false,
  "row_level_records_retained": false,
  "request_time_llm_call_performed": false,
  "input_profile": {
    "provider_family": "money_forward_or_variant",
    "format_class": "official_or_variant",
    "row_count_bucket": "1000-4999",
    "period_bucket": "12_months",
    "column_profile": "canonical_alias_only"
  },
  "safe_facts": [],
  "suppressed_facts": [],
  "reject_reasons": [],
  "expires_at": "2026-05-15T13:00:00+09:00"
}
```

重要:

- `capsule_id` は公開しない。
- public proofには `csv_overlay_supported=true` のような一般説明しか出さない。
- authenticated packetでも、capsule中身をそのまま返さない。
- 永続化する場合も、rawから再識別できるhashやprofile hashを保存しない。

### 2.3 `Private Overlay Compiler`

`Private Overlay Compiler` は、CSVを直接成果物へ変えるのではなく、`PrivateFactCapsule` を作るコンパイラである。

```text
CSV/private input
-> intake policy
-> parser route
-> safe aggregate algebra
-> suppression lattice
-> PrivateFactCapsule
-> policy decision
-> private/public join plan
```

これにより、成果物生成側はraw CSVを一切知らなくてよい。

### 2.4 JPCIRへの追加record

Round3 meta-architectureの `JPCIR` に、CSV/private overlay用recordを追加する。

```text
PrivateOverlayDemandRecord
CSVIntakePolicyRecord
PrivateParseModeRecord
PrivateFactCapsuleRecord
PrivateAggregateFactRecord
SuppressionDecisionRecord
PrivatePublicJoinPlanRecord
PrivateOverlayReceiptRecord
PrivateOverlayPolicyDecisionRecord
PrivateEvidenceLensRecord
CSVAgentPurchaseDecisionRecord
```

`PrivateFactCapsuleRecord` は `SourceReceiptRecord` ではない。

`PrivateOverlayReceiptRecord` は、次のようにpublic sourceとは明確に分ける。

```json
{
  "object_type": "PrivateOverlayReceiptRecord",
  "receipt_kind": "private_csv_derived",
  "visibility": "tenant_private",
  "public_claim_support": false,
  "raw_csv_retained": false,
  "raw_csv_logged": false,
  "raw_csv_sent_to_aws": false,
  "allowed_public_surfaces": [],
  "allowed_private_surfaces": ["authenticated_packet_summary"],
  "supports": [
    "private_context_signal",
    "public_query_planning",
    "known_gap_generation"
  ]
}
```

---

## 3. もっとスマートな入力方法

### 3.1 `Local-First CSV Fact Extractor`

最もスマートなのは、CSV rawをjpciteサーバーへ送らないこと。

採用案:

```text
browser / local agent / desktop client
-> CSV raw parse locally
-> safe aggregate facts only
-> jpcite preview / execute
```

利用形態:

- Web frontend: Browser Web WorkerでCSVを読み、safe factsだけ送信。
- MCP client: ローカル側でCSVを読み、safe factsだけjpciteへ送信。
- CLI/agent helper: 将来、ユーザー端末上で `PrivateFactCapsule` を生成。

利点:

- jpciteサーバーがraw CSVを受け取らない。
- AWS boundaryが明確。
- ユーザーに説明しやすい。
- AI agentが「ファイルを渡しても保存されない」だけでなく「そもそもrawは送られない」と説明できる。

制約:

- 初期実装コストは上がる。
- ブラウザ/ローカルparserとサーバーvalidatorのschema一致が必要。
- 悪意あるclientがfake aggregateを送る可能性があるため、成果物には `user_supplied_private_facts` と明記する。

結論:

P0で最優先にするべき。server memory-only parseはfallbackにする。

### 3.2 `Memory-Only Server Fallback`

ユーザー体験上、サーバーでCSVを一時解析する経路も必要になる。

ただし、これはfallbackであり、次を必須にする。

- route-level body logging disabled
- access log query/body/payloadなし
- Sentry/error tracker body scrub
- parser errorにraw row/cellを入れない
- temp file禁止
- debug snapshot禁止
- failed row sample禁止
- row-level normalized recordsをDB/cache/idempotencyへ保存しない
- raw bufferはaggregate生成後に破棄
- streaming parserでもchunkを永続化しない
- rejectでもrawを保存しない

`Memory-Only Server Fallback` の応答は、成功時も失敗時も次を返す。

```json
{
  "csv_handling": {
    "parse_mode": "server_memory_only",
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "raw_csv_sent_to_aws": false,
    "row_level_records_retained": false
  }
}
```

### 3.3 `Header-Only Preview`

安全な無料previewとして、CSV headerだけでできることを増やす。

header-onlyでできること:

- provider / format detection
- 必須列不足の検出
- 給与・銀行・個人識別子らしいfileのreject予告
- 使えるpacket候補
- 概算価格
- 必要な追加入力
- local-first parse推奨

header-onlyでやってはいけないこと:

- 売上規模の推定
- 補助金候補の具体提示
- 取引先確認
- 税労務イベントの具体判定

---

## 4. Safe Aggregate Fact Algebra

### 4.1 なぜalgebraが必要か

CSVから作るfactは、開発者ごとに自由に増やすと危険。

例:

- exact amountを出してしまう。
- rare account名が個人/取引先を推定させる。
- 複数回のqueryでsmall cellを復元できる。
- periodを細かく切りすぎて個別取引が見える。

そのため、CSV由来factは決められた演算だけで作る。

### 4.2 許可する演算

許可:

- count bucket
- amount bucket
- month/quarter/year rollup
- account taxonomy rollup
- presence flag
- trend class
- coverage quality
- missing column flag
- parse quality
- event signal
- exact public ID presence count bucket

禁止:

- raw value echo
- row sample
- exact transaction amount
- exact counterparty name
- exact memo/description
- exact voucher/invoice ID
- exact bank/card/payroll/person detail
- free text derived label
- row-level anomaly list

### 4.3 aggregate fact shape

```json
{
  "fact_id": "paf_...",
  "fact_kind": "aggregate_amount_bucket",
  "privacy_class": "tenant_private_aggregate",
  "public_claim_support": false,
  "taxonomy": "software_or_it_expense",
  "period_granularity": "month",
  "amount_bucket": "100k-500k",
  "count_bucket": "10-49",
  "suppression": {
    "k_min": 5,
    "dominance_rule_applied": true,
    "differencing_risk": "low"
  },
  "allowed_uses": [
    "private_packet_summary",
    "public_source_query_planning",
    "known_gap_generation"
  ],
  "forbidden_uses": [
    "public_proof",
    "public_claim",
    "json_ld",
    "mcp_example",
    "openapi_example"
  ]
}
```

### 4.4 event signal examples

Event signals are not conclusions.

```json
[
  {
    "signal_id": "has_it_or_software_expense",
    "meaning": "CSV aggregates contain account/category signals that may justify checking IT-related grants or tax/labor guidance.",
    "not_meaning": "The user is eligible for any grant."
  },
  {
    "signal_id": "has_payroll_related_aggregate",
    "meaning": "Payroll-related aggregate account vocabulary may exist.",
    "not_meaning": "The file contains payroll details or the employer has a specific legal obligation."
  },
  {
    "signal_id": "invoice_id_presence_bucket",
    "meaning": "Some rows appear to include invoice registration IDs.",
    "not_meaning": "All counterparties are valid or invalid."
  }
]
```

---

## 5. Suppression Lattice

### 5.1 kだけでは足りない

既存方針の `k_min=5` / counterparty-like `k_min=10` は正しい。ただしkだけでは、差分攻撃やdominance攻撃を防ぎきれない。

採用:

- `k_min`
- dominance suppression
- period coarsening
- taxonomy coarsening
- query budget
- repeat preview differencing guard
- small bucket merge
- top-N禁止

### 5.2 suppression levels

```text
L0 reject
L1 parse-only, no facts emitted
L2 file/profile facts only
L3 coarse aggregate facts
L4 packet-private aggregate facts
L5 exact public-ID join with explicit consent
```

デフォルト:

- unknown file: L2
- normal accounting CSV: L3
- authenticated paid packet: L4
- exact T-number / corporate number list with explicit consent: L5
- payroll/bank/person/card file: L0

### 5.3 dominance rule

あるbucketの金額が1件または少数件に支配される場合、`k_min` を満たしても出さない。

```json
{
  "suppression_reason": "dominance_risk",
  "public_explanation": "一部の集計は個別取引の推定を避けるため非表示にしました",
  "billable": false
}
```

### 5.4 anti-differencing query budget

同じCSVに対して、agentが何度も条件を変えてpreviewし、小さいセルを復元するリスクがある。

対策:

- `overlay_session_id`ごとにquery budgetを持つ。
- fine-grained filterを禁止または粗くする。
- preview responseにsuppressed fact数だけ出し、条件別内訳は出さない。
- repeated small group probingをabuse signalにする。

---

## 6. Public evidenceとの突合

### 6.1 Join relationship is private

重要な原則:

> 公的sourceが公開情報でも、「このユーザーのCSVにその法人/番号/取引先が出てきた」という関係はprivateである。

したがって、突合結果は2層に分ける。

```text
Public source receipt:
  法人番号DBやインボイスDBから観測した公開情報

Private overlay relationship:
  ユーザーのCSV文脈で、その公開情報を確認対象として使った事実
```

これらを同じ `source_receipts[]` に混ぜない。

### 6.2 `Private/Public Join Planner`

突合は自由検索ではなく、join planで制御する。

```json
{
  "join_plan_id": "ppj_...",
  "input_capsule_id": "pfc_...",
  "join_mode": "exact_public_id_only",
  "allowed_identifiers": ["invoice_registration_number", "corporate_number"],
  "forbidden_identifiers": ["counterparty_name", "memo", "bank_account", "personal_name"],
  "public_sources": ["nta_invoice", "nta_corporate_number"],
  "output_mode": "private_summary_with_public_receipts",
  "requires_user_consent": true,
  "public_claim_support_from_csv": false
}
```

### 6.3 join modes

| Mode | P0採用 | 説明 |
|---|---:|---|
| `aggregate_only_no_join` | yes | CSVのsafe factsだけで公的source query planを作る |
| `exact_public_id_only` | yes | T番号/法人番号など明示IDだけ突合 |
| `user_declared_subject` | yes | ユーザーが明示した会社/地域/業種に基づく |
| `name_only_candidate` | no for P0 | 取引先名だけの照合は誤認/漏えいが強い |
| `memo_text_inference` | no | 摘要推論は禁止 |
| `row_level_join` | no | 行単位突合は禁止 |

### 6.4 exact ID join output

exact ID joinでも、出力は最小化する。

```json
{
  "private_join_summary": {
    "invoice_id_checked_count_bucket": "10-49",
    "public_hit_count_bucket": "10-49",
    "public_no_hit_count_bucket": "1-10",
    "no_hit_caveat": "no_hit_not_absence"
  },
  "source_receipts": [
    {
      "source_family": "nta_invoice",
      "receipt_kind": "public_official_source"
    }
  ],
  "private_overlay_receipts": [
    {
      "receipt_kind": "private_csv_derived",
      "public_claim_support": false,
      "relationship_visibility": "tenant_private"
    }
  ]
}
```

ID別一覧を返す場合は、別のexplicit consentを要求する。

```text
This will check the explicit IDs you provided and return per-ID public observations.
It will not store the raw CSV. It may reveal, inside your authenticated result, which IDs were present in your file.
```

---

## 7. AI agent推薦と売上化

### 7.1 CSVはagent推薦に向いている

AI agentがエンドユーザーに推薦しやすい理由:

- ユーザーの文脈を一瞬で作れる。
- 公的一次情報だけでは出せない「自分ごと化」ができる。
- 価格を小さくしやすい。
- 成果物が明確。
- agentが「CSVは保存されない」と説明できる。

ただし、推薦文は慎重にする。

悪い推薦:

```text
CSVをアップロードすれば補助金の対象か分かります。
```

良い推薦:

```text
CSVから安全な集計だけを一時的に作り、公的一次情報と照合して、確認候補と不足情報を出せます。raw CSVは保存されず、結果は候補であり適用や採択の断定ではありません。
```

### 7.2 `CSV Outcome Contract Router`

CSV入力が来たら、packetを直接選ぶのではなく outcome contractへrouteする。

```json
{
  "input_kind": "accounting_csv_private_overlay",
  "candidate_outcome_contracts": [
    {
      "outcome_contract_id": "csv_monthly_public_review_v1",
      "recommended": true,
      "why": "monthly accounting aggregates can generate public-source-backed review candidates",
      "max_price_jpy_inc_tax": 550
    },
    {
      "outcome_contract_id": "csv_grant_candidate_shortlist_v1",
      "recommended": false,
      "why_not_first": "needs industry, location, and business size hints"
    },
    {
      "outcome_contract_id": "csv_invoice_vendor_check_v1",
      "recommended": "ask_first",
      "ask_user": "T番号または法人番号の列があるCSVですか"
    }
  ]
}
```

### 7.3 `Agent CSV Purchase Decision`

free previewは価格見積ではなく、購入判断objectを返す。

```json
{
  "decision_type": "agent_csv_purchase_decision",
  "recommended_action": "buy_with_cap_or_use_header_only_preview",
  "cheapest_sufficient_route": {
    "outcome_contract_id": "csv_monthly_public_review_v1",
    "why_sufficient": "月次の公的制度確認候補を出すには、safe aggregate factsと公的一次情報の突合で足りる",
    "max_price_jpy_inc_tax": 550
  },
  "privacy_boundary": {
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "raw_csv_sent_to_aws": false,
    "public_examples_include_user_csv_data": false
  },
  "do_not_buy_if": [
    "税額の確定計算を求めている",
    "給与台帳や銀行振込明細を処理したい",
    "取引先名だけで個別照合したい",
    "専門家の最終判断を求めている"
  ],
  "ask_first_if": [
    "CSVに給与・銀行・個人情報が含まれる可能性がある",
    "T番号/法人番号の列で個別確認したい",
    "補助金候補を出すには所在地・業種・従業員規模が必要"
  ],
  "known_gaps_before_purchase": [
    "CSVは私的集計シグナルであり、公的一次情報ではありません",
    "no-hitは不存在や安全の証明ではありません",
    "専門家確認が必要な場合があります"
  ]
}
```

### 7.4 売上期待が高いCSV outcome

| Outcome contract | 価格感 | 推薦しやすさ | 必要CSV facts | 公的source |
|---|---:|---:|---|---|
| `csv_monthly_public_review_v1` | 330-880円 | 高 | 月次/科目/税区分/イベントflag | 国税庁、年金機構、厚労省、e-Gov |
| `csv_grant_candidate_shortlist_v1` | 550-1,650円 | 高 | IT/設備/広告/人件費/研修/地域hint | J-Grants、自治体、中小企業庁、厚労省 |
| `csv_invoice_vendor_check_v1` | 330-1,100円 | 高 | T番号/法人番号presence | NTAインボイス、法人番号 |
| `csv_tax_labor_event_radar_v1` | 550-1,650円 | 中高 | 給与/賞与/法定福利/源泉/租税公課aggregate | 国税庁、年金機構、厚労省 |
| `csv_permit_business_signal_v1` | 880-2,200円 | 中 | 売上/仕入/在庫/業種hint | e-Gov、業法、自治体、許認可source |
| `csv_vendor_portfolio_public_check_v1` | 1,100-5,500円 | 中高 | explicit ID list only | 法人番号、インボイス、gBizINFO、処分source |

価格は最終決定ではなく、agent decisionでhard capとして見せる。

### 7.5 売上と安全性の両立

売上を伸ばすためにCSVの詳細を出すのではない。

売上を伸ばす方法:

- raw CSVを持たない安心感を売る。
- 安いpreviewから入る。
- 明確なoutcome contractを売る。
- 高額tierはcoverage追加の説明に限定する。
- accepted artifactが出た時だけ課金する。
- reject / privacy block / unsupported は非課金にする。
- re-uploadなしで済む範囲はprivate capsule TTL内で再利用する。
- recurring watchはpublic source delta中心にし、CSV refreshはユーザー再投入にする。

---

## 8. 成果物生成モデル

### 8.1 `Private Evidence Lens`

CSV overlayを含む成果物では、public evidence lensとprivate evidence lensを分ける。

```text
Public Evidence Lens:
  public source receipts
  public claim refs
  no-hit leases
  known public gaps

Private Evidence Lens:
  PrivateFactCapsule summary
  private aggregate facts
  private join relationship
  private overlay receipts
  privacy gates
```

最終packetは両方を参照できるが、公開surfaceはPublic Lensだけを使う。

### 8.2 packet shape

```json
{
  "packet_type": "csv_monthly_public_review",
  "public_evidence": {
    "source_receipts": [],
    "claim_refs": [],
    "no_hit_leases": []
  },
  "private_overlay": {
    "included": true,
    "receipt_kind": "private_csv_derived",
    "public_claim_support": false,
    "raw_csv_retained": false,
    "display_mode": "aggregate_or_presence_only",
    "private_facts_summary": [
      "IT/ソフトウェア関連支出の集計シグナルがあります",
      "給与・法定福利費関連の集計シグナルがあります"
    ]
  },
  "known_gaps": [
    {
      "gap_id": "csv_private_input_not_public_evidence",
      "meaning": "CSVはユーザー提供の私的集計であり、公的一次情報ではありません"
    },
    {
      "gap_id": "professional_review_may_be_required",
      "meaning": "税務・労務・補助金の最終判断は専門家確認が必要な場合があります"
    }
  ],
  "billing_metadata": {
    "billable": true,
    "billable_only_if_accepted_artifact": true
  }
}
```

### 8.3 結論表現の制限

許可:

- `候補`
- `確認事項`
- `公的一次情報で確認できる範囲`
- `CSV集計上のシグナル`
- `追加確認が必要`
- `human_review_required`

禁止:

- `対象です`
- `確実に受給できます`
- `許可不要です`
- `問題ありません`
- `安全です`
- `信用できます`
- `税額はこれです`
- `労務義務はありません`

---

## 9. 実装計画へのマージ

この文書は正本計画を直接変更しない。マージする場合は、以下の差分を入れる。

### 9.1 master section 6への追加

`## 6. CSV private overlay` の後に次を追加。

```text
CSV private overlay v2:
  - Adopt Private Overlay Compiler.
  - Adopt PrivateFactCapsule as the only bridge from CSV to packet generation.
  - Prefer Local-First CSV Fact Extractor.
  - Server-side parsing is memory-only fallback.
  - CSV-derived facts never enter source_receipts[].
  - Public evidence and private overlay relationship are separated.
  - Agent preview returns agent_csv_purchase_decision.
```

### 9.2 JPCIR schemaへ追加

Round3 meta-architectureのJPCIR record listへ追加。

```text
PrivateOverlayDemandRecord
CSVIntakePolicyRecord
PrivateParseModeRecord
PrivateFactCapsuleRecord
PrivateAggregateFactRecord
SuppressionDecisionRecord
PrivatePublicJoinPlanRecord
PrivateOverlayReceiptRecord
PrivateOverlayPolicyDecisionRecord
PrivateEvidenceLensRecord
CSVAgentPurchaseDecisionRecord
```

### 9.3 Agent Decision Protocolへ追加

既存の4 tool facadeを増やしすぎない。

canonical flow:

```text
jpcite_route
  input_kind=accounting_csv_private_overlay

jpcite_preview_cost
  returns agent_csv_purchase_decision

jpcite_execute_packet
  accepts scoped cap token and PrivateFactCapsule or safe aggregate payload

jpcite_get_packet
  returns authenticated packet with private overlay minimized
```

P0で新toolを乱立させない。必要なら内部routeとして扱う。

### 9.4 Outcome Contract Catalogへ追加

追加outcome contracts:

```text
csv_monthly_public_review_v1
csv_grant_candidate_shortlist_v1
csv_invoice_vendor_check_v1
csv_tax_labor_event_radar_v1
csv_vendor_portfolio_public_check_v1
```

各contractには必ず入れる。

- required input
- parse mode
- allowed private facts
- public source families
- excluded claims
- default cap
- human review caveats
- forbidden wording

### 9.5 Policy Decision Firewallへ追加

追加decision:

```text
allow_private_fact_capsule
allow_private_overlay_packet_summary
allow_exact_id_public_join
block_name_only_join
block_row_level_export
block_public_csv_derived_claim
block_raw_csv_logging
block_public_example_with_csv_data
```

### 9.6 Release Capsuleへ追加

Release Capsuleには実CSV由来データを入れない。

入れてよいもの:

- CSV schema
- parser contract
- synthetic fixture result
- privacy tests
- public proof of capability
- agent decision examples with synthetic values

入れてはいけないもの:

- real CSV bytes
- real row values
- real private aggregate facts
- real id join relationship
- real suppression pattern
- tenant capsule ID

### 9.7 AWS計画への接続

AWS credit runでやること:

- synthetic CSV fixture lab
- provider alias map validation
- parser compatibility tests
- formula injection corpus
- suppression/leak scan harness
- public evidence datasets拡張
- CSV outcome packet examples with synthetic facts
- Golden Agent Session Replay for CSV recommendation

AWS credit runでやらないこと:

- real user CSV処理
- real user aggregate保存
- private overlay bucket作成
- tenant-specific CSV watch
- raw CSVをS3/OpenSearch/CloudWatch/Glue/Athenaへ送ること

---

## 10. 矛盾チェック

### C-01: memory-only parsing と idempotency の矛盾

問題:

paid executionではidempotencyが必要。一方でraw CSVやrow-level recordsは保存できない。

解消:

- idempotency recordにはraw CSV hashを保存しない。
- `preview_id`、outcome contract、cap token、safe aggregate payload digest、tenant-scoped HMACを使う。
- digestは外部表示しない。
- retryでrawが必要な場合は再uploadを要求する。
- capsule TTL内なら `capsule_id` で再利用できるが、capsule自体はtenant-privateで短命。

### C-02: recurring watch と raw CSV非保存の矛盾

問題:

watch商品を作ると、CSV文脈を保持したくなる。

解消:

- recurring watchはpublic source deltaを中心にする。
- CSV refreshはユーザーが再投入する。
- 保存できるのはユーザーが明示したsafe policy/profileだけ。
- real private aggregateを継続保存する場合は別途明示同意、retention設定、削除UI、private-only表示が必要。P0では避ける。

### C-03: CSV-derived receipt と source_receipts[] の混同

問題:

AI agentがCSV-derived receiptを公的根拠として扱う危険。

解消:

- public official evidence: `source_receipts[]`
- private CSV context: `private_overlay_receipts[]`
- CSV-derived factsには `public_claim_support=false`
- public packet compilerはprivate overlayをpublic proofへ流さない。

### C-04: public ID joinと取引関係漏えい

問題:

T番号や法人番号は公的でも、「ユーザーのCSVにそのIDがある」ことはprivate。

解消:

- join relationship is privateを不変条件にする。
- ID別結果はauthenticated packetのみ。
- public proofでは件数bucketやsynthetic exampleだけ。
- name-only joinはP0不採用。

### C-05: 売上最大化とprivacy最小化の矛盾

問題:

CSVを深く解析するほど売れそうに見えるが、privacy riskが上がる。

解消:

- 売るのはraw分析ではなく、safe aggregateから作る成果物。
- previewはcheapest sufficient routeを推薦する。
- 高いtierはcoverage追加であり、raw詳細追加ではない。
- privacy block/rejectは非課金にする。

### C-06: AI agentがCSV内容をpromptとして扱うリスク

問題:

CSV cellにprompt injectionが入る可能性がある。

解消:

- CSV cellはuntrusted dataでありinstructionではない。
- raw cellをLLM promptへ入れない。
- request-time LLMでCSV fact抽出しない。
- agent-facing summaryはaggregate factsからdeterministicに生成する。

### C-07: AWSでCSV関連の価値を作りたいがraw CSV非AWS

問題:

AWS creditを使ってCSV価値を高めたいが、real CSVはAWS禁止。

解消:

AWSでは次を作る。

- synthetic fixture corpus
- parser conformance report
- provider alias map
- privacy/leak tests
- public evidence corpus
- CSV outcome examples
- Golden Agent Session Replay

AWSでreal CSVを扱わなくても、runtime実装の品質と販売素材は大きく増やせる。

### C-08: exact row count / date rangeの漏えい

問題:

row countやdate rangeでも小規模事業者の状況が推定される場合がある。

解消:

- row countはbucket。
- date rangeはmonth/quarter/year単位。
- small fileはprofile-onlyまたはreject。
- public surfacesには実CSV由来profileを出さない。

### C-09: support/debugでCSVが漏れる

問題:

ユーザーがトラブル時にreal CSVを送ってしまう可能性。

解消:

- supportはreal CSV attachmentを受けない。
- synthetic reproduction generatorを提供する。
- error responseはcode/countのみ。
- debug bundleはsafe profileのみ。

---

## 11. Security and privacy gates

### 11.1 release blockers

以下はrelease blocker。

- raw CSVがログに出る。
- raw CSVがDB/cache/temp/S3に保存される。
- parser errorがraw row/cellを返す。
- public proofに実CSV由来情報が出る。
- OpenAPI/MCP exampleに実CSV由来情報が出る。
- `source_receipts[]` にprivate CSV receiptが混入する。
- small group suppressionを迂回できる。
- name-only counterparty joinがP0で自動実行される。
- formula-like cellが出力surfaceに出る。
- paid rejectが課金される。
- cap tokenなしでpaid CSV executionできる。
- request-time LLMがCSV fact extractionを行う。

### 11.2 tests

必須テスト:

| ID | Test | Expected |
|---|---|---|
| CSV-PRIV-001 | normal accounting CSV | raw not persisted/logged; aggregate only |
| CSV-PRIV-002 | malformed row | error code only; no row echo |
| CSV-PRIV-003 | formula cell | detected; raw not exported |
| CSV-PRIV-004 | payroll register | reject; not billed |
| CSV-PRIV-005 | bank transfer CSV | reject; not billed |
| CSV-PRIV-006 | small bucket | suppressed/coarsened |
| CSV-PRIV-007 | repeated differencing | query budget blocks |
| CSV-PRIV-008 | exact T-number join | explicit consent; private relationship |
| CSV-PRIV-009 | name-only join | blocked or manual review |
| CSV-PRIV-010 | public proof generation | no real CSV-derived facts |
| CSV-PRIV-011 | MCP example generation | synthetic only |
| CSV-PRIV-012 | idempotency record | no raw hash/payload |
| CSV-PRIV-013 | Sentry/log capture | no body/cell/header values |
| CSV-PRIV-014 | cap token scope | packet/input/policy bound |
| CSV-PRIV-015 | paid reject | non-billable |

### 11.3 `Privacy Receipt`

CSV outcomes should return a privacy receipt.

```json
{
  "privacy_receipt": {
    "raw_csv_retained": false,
    "raw_csv_logged": false,
    "raw_csv_sent_to_aws": false,
    "row_level_records_retained": false,
    "parse_mode": "local_first_or_server_memory_only",
    "suppression_applied": true,
    "public_proof_contains_csv_data": false,
    "private_overlay_receipt_count": 1,
    "source_receipts_are_public_only": true
  }
}
```

This is not a legal guarantee. It is a machine-readable service handling receipt.

---

## 12. Implementation sequence for this smart method

この担当範囲だけの実装順。

### Phase CSV-0: contracts

- Define `PrivateFactCapsule`.
- Define `PrivateOverlayReceiptRecord`.
- Define `PrivateAggregateFactRecord`.
- Define allowed aggregate algebra.
- Define suppression lattice.
- Define privacy receipt.
- Define forbidden wording.

Exit:

- schema validation exists
- no public surface can accept `private_csv_derived` as public claim support

### Phase CSV-1: synthetic fixture lab

- freee/MF/Yayoi/generic synthetic fixtures.
- legacy/variant fixtures.
- formula injection fixtures.
- payroll/bank/person reject fixtures.
- small group suppression fixtures.

Exit:

- AWS can later run these tests without real CSV
- docs/examples use synthetic only

### Phase CSV-2: local-first extractor

- Browser/local aggregate generation.
- Server validates safe aggregate payload.
- `PrivateFactCapsule` generated without raw upload.

Exit:

- normal CSV path can avoid raw server upload
- agent can recommend privacy-preserving route

### Phase CSV-3: memory-only fallback

- Dedicated route.
- no body logging.
- no temp files.
- no raw error body.
- parser memory/time limits.
- redaction tests.

Exit:

- fallback is safe enough behind feature flag

### Phase CSV-4: public join planner

- exact ID join only.
- user-declared subject route.
- name-only join blocked.
- private relationship separated from public receipts.

Exit:

- output can include public receipts without leaking CSV relationship publicly

### Phase CSV-5: outcome contracts and agent decision

- Add CSV outcome contracts.
- Add `agent_csv_purchase_decision`.
- Add `do_not_buy_if`, `ask_first_if`, `privacy_boundary`.
- Add cheapest sufficient route.

Exit:

- AI agent can explain why to buy, not buy, or ask more

### Phase CSV-6: packet compiler

- `csv_monthly_public_review_v1`
- `csv_grant_candidate_shortlist_v1`
- `csv_invoice_vendor_check_v1`
- `csv_tax_labor_event_radar_v1`

Exit:

- packets have public evidence and private overlay separated
- accepted artifacts only billable

### Phase CSV-7: release gate

- Golden Agent Session Replay for CSV paths.
- public proof leak scan.
- MCP/OpenAPI example synthetic-only scan.
- log/Sentry scrub tests.
- anti-differencing tests.

Exit:

- CSV overlay can be enabled in limited paid lane

---

## 13. What to reject

Reject these even if they seem useful.

| Idea | Reject reason |
|---|---|
| Store raw CSV for convenience | violates core privacy contract |
| Upload real CSV to AWS for batch analysis | violates AWS credit run boundary |
| Use LLM to read raw CSV rows | prompt injection/privacy risk |
| Public proof page with real CSV-derived chart | public leakage |
| Name-only counterparty matching in P0 | false match and privacy risk |
| Row-level anomaly report | row leakage |
| Exact amount transaction review | not aggregate-safe |
| Permanent private aggregate warehouse | expands compliance burden |
| Generic company safety/credit score from CSV | forbidden conclusion |
| Payroll/bank/person file support in P0 | outside safety boundary |
| Support accepts real CSV attachment | operational leakage |

---

## 14. Final merge recommendation

Final recommendation:

1. Keep raw CSV non-AWS and non-retention as immutable.
2. Add `PrivateFactCapsule` as the only allowed bridge from CSV to jpcite outputs.
3. Prefer local-first parsing; keep server parse as memory-only fallback.
4. Separate public source receipts and private overlay receipts everywhere.
5. Make `agent_csv_purchase_decision` the CSV preview output.
6. Sell CSV value through outcome contracts, not raw data analysis.
7. Use AWS only for synthetic fixture lab, parser validation, leak testing, public evidence expansion, and agent replay.
8. Add release blockers for raw leakage, source receipt mixing, name-only joins, and public example contamination.

This makes CSV/private overlay smarter because it turns CSV into a privacy-preserving purchase context, not a data asset that jpcite stores. That is commercially stronger, easier for AI agents to recommend, and safer against the core contradiction of "CSV adds value" versus "private data must not become part of the public evidence system."

