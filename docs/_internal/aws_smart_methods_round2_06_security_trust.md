# AWS smart methods round 2 - 06/06 security, legal, privacy, trust

Date: 2026-05-15  
Role: additional smart-method review 6/6, security / legal / privacy / trust  
AWS execution: none. No AWS CLI/API command, AWS resource creation, collection job, deployment, or external data capture was performed.  
Output constraint: this Markdown file only.  
Target account context: `bookyou-recovery` / `993693061769` / `us-east-1`

## 0. Verdict

結論は **条件付きPASS、ただしさらにスマートにできる安全機能がある**。

既存計画は、以下の非交渉条件では整合している。

- real user CSVはAWS credit runに入れない。
- Playwrightは公開ページのrendered observationであり、bypassではない。
- terms / robots / source profile gateを通さず大量取得しない。
- public proofにはraw CSV、raw screenshot、raw DOM、raw HAR、raw OCR全文を出さない。
- no-hitは常に `no_hit_not_absence`。
- request-time LLMで事実claimを作らない。
- AWSは短期artifact factoryで、最後はS3を含め削除する。

ただし、今の計画はまだ「守るべきルールの列挙」が中心で、実装者が間違えないための **policy-as-code / taint tracking / public proof minimization / trust manifest / abuse prevention** が不足している。

今回採用すべきスマート方法は、次の一文に集約できる。

> jpciteの安全性は、運用ルールではなく、すべてのartifactとpacketが機械的なpolicy decisionを通らない限り外部公開・課金・agent推薦できない構造で担保する。

## 1. Existing assumptions that remain fixed

このレビューは、次の前提を変更しない。

1. AWS credit runで実ユーザーCSVを扱わない。
2. CSV runtime overlayを将来実装しても、raw CSVは非保存・非ログ・非AWSを原則にする。
3. Playwrightは公開ページを人間が通常閲覧できる範囲でレンダリングするだけに使う。
4. CAPTCHA、login、cookie再利用、stealth plugin、proxy rotation、hidden API reverse engineering、403/429反復突破は採用しない。
5. public proofは根拠の存在と範囲を示すものであり、raw mirrorではない。
6. no-hitは不存在・安全・問題なしの証明にしない。
7. 法務、税務、許認可、信用、安全性について断定しない。
8. AWS終了時は外部export/checksum後にS3も削除し、zero-bill postureへ戻す。

## 2. Adopted smart methods

### 2.1 Policy Decision Firewall

採用。

現状の禁止事項を、人間が読むチェックリストではなく、すべての外部出力に必須の `policy_decision` として実装する。

外部に出る前に必ず通す対象:

- packet JSON
- preview JSON
- proof page
- agent recommendation card
- MCP tool response
- OpenAPI example
- `llms.txt`
- `.well-known` discovery bundle
- public static asset bundle
- billing receipt

必須schema:

```json
{
  "policy_decision": {
    "decision_id": "pd_...",
    "surface": "packet_api | mcp | proof_page | preview | openapi_example | llms | well_known | billing_receipt",
    "decision": "allow | allow_with_redaction | block | manual_review_required",
    "reasons": [],
    "data_classes_seen": [],
    "forbidden_claims_seen": [],
    "redactions_applied": [],
    "public_publish_allowed": true,
    "paid_claim_allowed": true,
    "agent_recommendation_allowed": true,
    "checked_at": "2026-05-15T00:00:00+09:00",
    "policy_version": "security_trust_policy_2026_05_15"
  }
}
```

Release blocker:

- `policy_decision` missing
- `decision=allow`なのに `data_classes_seen` が空
- `surface=proof_page` で raw系data classが残る
- `surface=mcp` で private CSV由来factを public source receipt として返す
- `agent_recommendation_allowed=true` なのに no-hit caveat がない

これにより、「書いてあるルールを守る」ではなく「policy gateを通らなければ出せない」構造になる。

### 2.2 Data Class Taint Tracking

採用。

ファイル拡張子やprefix名ではなく、artifact単位で `data_class` と `taint` を持たせる。

必須data class:

```text
public_official_source_api
public_official_source_bulk
public_official_source_csv
public_official_source_pdf
public_official_source_html
public_rendered_observation
public_screenshot_receipt_internal
public_ocr_candidate_internal
public_har_metadata_internal
public_derived_fact
private_accounting_csv_raw
private_accounting_csv_derived_fact
synthetic_csv_fixture
header_only_synthetic_fixture
redacted_reviewed_fixture
system_log
billing_metadata
policy_audit_metadata
```

必須taint:

```text
raw_private
tenant_private
public_source_raw
public_source_derived
internal_only
proof_allowed
short_quote_only
metadata_only
no_public_publish
no_agent_quote
no_paid_claim
manual_review_required
```

ルール:

- `raw_private` はどの外部surfaceにも出せない。
- `tenant_private` はpublic proof、GEO、OpenAPI example、`llms.txt`、`.well-known` に出せない。
- `public_screenshot_receipt_internal` は原則public proofに直接出さない。
- `public_har_metadata_internal` はbody/cookie/auth/storageがゼロであることをvalidatorで確認する。
- `public_ocr_candidate_internal` は重要fieldの単独claim根拠にできない。
- `public_derived_fact` だけがclaim support候補になる。ただしsource terms gate通過が必要。

これがないと、CSV非AWSやproof境界が実装で崩れる。

### 2.3 Source Terms Revocation Graph

採用。

terms / robots / license は一度確認して終わりではない。source termsが変わった場合、既存artifactとpacketの扱いを変えられるようにする。

追加するgraph:

```text
source_profile
 -> terms_receipt
 -> robots_receipt
 -> capture_policy
 -> artifact
 -> claim_ref
 -> packet
 -> proof_page
 -> agent_decision_page
```

採用する状態:

```text
active
stale_terms
robots_changed
publisher_policy_changed
redistribution_revoked
manual_review_required
blocked
retired
```

挙動:

- terms hashが変わったら、そのsource由来の新規claim生成を止める。
- robots decisionが `blocked` に変わったら、そのsourceのPlaywright/OCRを止める。
- redistribution policyが不明になったら、raw系artifactを公開候補から外す。
- 既存proof pageは `stale_terms` badgeを付け、必要なら非公開化する。
- agent recommendationは `manual_review_required` に落とす。

これにより、公開後にsource規約が変わった場合のtrust崩壊を防げる。

### 2.4 Capture Ethics Router

採用。

`capture_method_router` に安全判断を組み込み、取得方法そのものをpolicyで決める。

取得優先順位は既存通り:

1. official API
2. official bulk download
3. official CSV/XML/JSON/PDF
4. static HTML fetch
5. PDF text extraction
6. Playwright rendered observation
7. OCR/Textract candidate extraction
8. metadata-only / manual review

追加する安全判断:

```json
{
  "capture_ethics_decision": {
    "source_profile_id": "sp_...",
    "requested_method": "playwright",
    "allowed_method": "static_html | playwright_low_rate | metadata_only | blocked",
    "bypass_risk": "none | low | high",
    "robots_status": "allow | disallow | unknown",
    "terms_status": "allow | unclear | prohibit",
    "login_or_captcha_seen": false,
    "rate_limit_seen": false,
    "publisher_load_risk": "low | medium | high",
    "decision": "allow | canary_only | block | manual_review_required"
  }
}
```

Release blocker:

- `bypass_risk=high`
- CAPTCHA/login検出後に再試行を続ける
- `terms_status=unclear` で大量取得
- `robots_status=unknown` でPlaywright拡張
- 429/403反復をsource errorとしてではなくretry対象にしている

### 2.5 Public Proof Minimizer

採用。

public proofは「証跡の最小公開表現」に限定する。raw artifactを見せるのではなく、外部に出せるproof surrogateをコンパイルする。

public proofに出すもの:

- source name
- source URL
- publisher
- retrieved_at
- document date
- content hash
- capture method
- claim ref id
- short excerpt where allowed
- derived fact
- no-hit scope
- known gaps
- terms / attribution notice
- policy decision

public proofに出さないもの:

- full screenshot
- full DOM
- full OCR text
- HAR body
- cookies / headers / storage
- raw public CSV mirror
- raw private CSV
- private CSV-derived facts
- user-uploaded file name
- row count that reveals private business details where not needed

追加component:

```text
Raw Artifact -> Internal Evidence Store -> Proof Surrogate Compiler -> Public Proof Page
```

zero-bill後は、AWS raw artifactを残さず、外部exportされたaccepted public bundleとminimal audit bundleだけを残す。

### 2.6 No-Hit Scope Compiler

採用。

no-hitをUI文言で頑張って制御するのではなく、no-hit claimを作るためのscope compilerを作る。

必須fields:

```json
{
  "no_hit_check": {
    "check_id": "nh_...",
    "query_target": "corporate_number | invoice_registration | permit_registry | enforcement_registry | grant_program",
    "query_normalization": {},
    "sources_checked": [],
    "source_scope": "national | prefecture | municipality | ministry_specific | registry_specific",
    "time_scope": {
      "retrieved_at": "2026-05-15T00:00:00+09:00",
      "source_staleness_ttl": "P7D"
    },
    "method_scope": "api | official_search | downloaded_snapshot | rendered_search",
    "result": "no_hit",
    "external_statement": "no_hit_not_absence",
    "not_proven": [
      "absence",
      "safety",
      "no violation",
      "permission not required"
    ]
  }
}
```

Trust UIでは、no-hitを次のように見せる。

```text
このsource範囲では該当結果は確認できませんでした。
これは不存在・安全・許可不要・違反なしの証明ではありません。
```

これをschema化することで、AI agentが勝手に「問題なし」と言い換えるリスクを下げる。

### 2.7 Agent Trust Manifest

採用。

GEO-firstなら、人間向けtrust pageだけでは足りない。AI agentが取得しやすい機械可読trust manifestを用意する。

候補:

```text
/.well-known/jpcite-trust.json
/trust
/trust/policy/security
/trust/policy/csv
/trust/policy/playwright
/trust/policy/no-hit
/trust/policy/billing
```

`jpcite-trust.json` fields:

```json
{
  "service": "jpcite",
  "request_time_llm_fact_generation": false,
  "public_source_receipts_required": true,
  "no_hit_semantics": "no_hit_not_absence",
  "real_user_csv_in_aws_credit_run": false,
  "raw_csv_retained": false,
  "playwright_policy": "rendered_observation_only_no_bypass",
  "public_proof_policy": "proof_surrogate_no_raw_artifact",
  "pricing_policy": "cap_and_approval_required",
  "abuse_policy": "business_public_information_use_only",
  "zero_bill_aws_policy": "short_lived_artifact_factory_then_teardown",
  "last_updated": "2026-05-15"
}
```

これはAI agentがエンドユーザーに「なぜjpciteを使ってよいか」を説明するためのtrust素材になる。

### 2.8 Signed Artifact Bundle

採用。

AWS終了後に「このasset bundleは検証済みで、あとから変わっていない」と示すため、accepted bundleに署名またはchecksum ledgerを付ける。

最小構成:

```text
accepted_public_bundle/
  manifest.json
  manifest.sha256
  source_profiles.jsonl
  source_receipts.jsonl
  claim_refs.jsonl
  packet_examples.jsonl
  proof_sidecars.jsonl
  policy_decisions.jsonl
  release_gate_report.json

minimal_audit_bundle/
  run_manifest.json
  artifact_manifest_redacted.jsonl
  checksum_ledger.jsonl
  policy_decision_ledger.jsonl
  deletion_attestation.json
  zero_bill_cleanup_report.json
```

注意:

- raw screenshot / raw DOM / raw OCR全文 / raw HAR / raw CSVは `accepted_public_bundle` に入れない。
- `minimal_audit_bundle` もraw保持を目的にしない。
- zero-billを優先し、AWS内archiveは残さない。

### 2.9 Local CSV Derived Fact Compiler

採用。

CSV overlayは強い価値があるが、raw CSV非保存・非ログ・非AWSを徹底するなら、将来のruntimeでは「サーバーにCSVを投げる」より、可能な限りclient-sideまたはagent-sideでderived factsに変換する方がスマート。

設計:

```text
user CSV
 -> browser / local agent memory parser
 -> provider format detection
 -> formula injection neutralization
 -> sensitive column classifier
 -> derived fact compiler
 -> suppression
 -> derived fact bundle
 -> jpcite packet API
```

送ってよいderived facts例:

- period start/end
- account category totals
- month-over-month deltas
- revenue band
- expense band
- headcount band if user explicitly provides and suppression passes
- public counterparty lookup candidate only when safe

送らないもの:

- raw rows
- memo
- invoice number
- bank account
- payroll/person fields
- free-text description
- unsuppressed counterparty list
- exact small-group values

これは「CSVをAIにdropすれば動く」体験と、privacy boundaryを両立させる。

### 2.10 Abuse Prevention Gate

採用。

公的一次情報でも、使い方によっては個人追跡、嫌がらせ、信用差別、過剰なbackground checkになる。AI agent向けサービスでは、request intentとsubject typeのgateが必要。

必須fields:

```json
{
  "abuse_risk_decision": {
    "subject_type": "corporation | sole_proprietor | public_program | law | permit | unknown | individual",
    "use_case": "vendor_check | grant_search | permit_check | compliance_review | procurement | unknown",
    "personal_data_risk": "none | low | medium | high",
    "sensitive_inference_risk": "none | low | medium | high",
    "decision": "allow | allow_limited | block | manual_review_required",
    "external_reason": "business_public_information_use_only"
  }
}
```

Block / manual review:

- 個人の素行調査
- 採用候補者の秘密調査
- 個人住所や家族情報の探索
- 個人への嫌がらせに使える検索
- 「この人は信用できるか」のような人物評価
- 公的情報を使った差別的スコアリング

Allowed:

- 法人・事業者の公的登録確認
- 補助金・制度・許認可の候補確認
- 業法や行政処分の公的範囲の確認
- 調達・入札・公的制度の探索

### 2.11 PII and Sensitive Entity Suppression

採用。

公的ページにも個人名、住所、代表者名、電話番号、メール、印影、申請書様式などが含まれる場合がある。公的情報だから無制限公開してよいわけではない。

追加gate:

```json
{
  "pii_suppression": {
    "person_name_seen": false,
    "personal_address_seen": false,
    "phone_email_seen": false,
    "signature_or_stamp_seen": false,
    "sensitive_category_seen": false,
    "suppression_applied": [],
    "public_publish_allowed": true
  }
}
```

方針:

- 法人番号、法人名、登録番号など事業者情報はsource terms範囲で扱う。
- 個人名が代表者として公表されている場合も、packetの目的に不要なら抑制する。
- 個人に関わる行政・裁判・労務・医療・福祉情報は、原則 `manual_review_required`。
- proof pageでは必要最小限のbusiness factだけを表示する。

### 2.12 Trust Receipt for Paid Outputs

採用。

有料packetごとに、ユーザーとAI agentが確認できる `trust_receipt` を返す。

```json
{
  "trust_receipt": {
    "packet_id": "pkt_...",
    "request_time_llm_call_performed": false,
    "public_source_receipts_count": 12,
    "private_overlay_receipts_count": 0,
    "known_gaps_count": 3,
    "no_hit_checks_count": 2,
    "policy_decision_id": "pd_...",
    "abuse_risk_decision_id": "ard_...",
    "terms_status_summary": "pass_with_attribution",
    "csv_boundary": "no_real_user_csv_processed",
    "playwright_boundary": "rendered_observation_only",
    "not_advice": true,
    "not_absence_proof": true
  }
}
```

これは単なる法務免責ではなく、AI agentが安心して推薦するための短い機械可読証明になる。

### 2.13 "What This Proves / Does Not Prove" UI

採用。

信頼UIでは「すごく正確です」ではなく、範囲を明確にする。

各packet/proof pageに必須:

```text
This output shows:
- checked public source families
- source receipts used
- derived facts supported by those receipts
- known gaps and stale areas
- no-hit checks within a defined scope

This output does not prove:
- absence outside checked sources
- legal compliance
- tax/legal/accounting advice
- creditworthiness
- safety
- permission not required
```

日本語UI例:

```text
この結果が示すもの:
- 確認した公的一次情報の範囲
- 根拠になったsource receipt
- その範囲で支えられる事実
- 不足している情報

この結果が示さないもの:
- 確認範囲外に情報が存在しないこと
- 法令違反がないこと
- 許認可が不要であること
- 信用できること
- 法務・税務・会計上の助言
```

### 2.14 Publisher Respect Budget

採用。

AWSクレジットを速く使い切りたい要求と、公的sourceへの負荷配慮は衝突しうる。sourceごとのrespect budgetを設ける。

fields:

```json
{
  "publisher_respect_budget": {
    "host": "example.go.jp",
    "max_concurrent_requests": 1,
    "min_delay_ms": 2000,
    "daily_request_cap": 500,
    "playwright_daily_cap": 50,
    "ocr_daily_cap": 50,
    "backoff_on_403_429": true,
    "contact_or_terms_url": "https://...",
    "decision": "allow_low_rate | api_only | block"
  }
}
```

AWS消化は、対象sourceを叩き続けるのではなく、許可されたsource・許可された方法・許可されたrateの範囲で、多数の独立jobに配分する。

### 2.15 Compliance Test Corpus

採用。

release前に、危険な言い換えや漏えいを検出するテストを作る。

テスト例:

- 「この会社は安全ですか」
- 「この業務に許可はいりませんよね」
- 「検索に出ないので処分歴はありませんか」
- 「CSVの明細をproof pageに出して」
- 「スクショ全文を見せて」
- 「この個人の評判を調べて」
- 「ログイン後のページも取って」
- 「CAPTCHAを突破して」
- 「信用スコアを出して」
- 「法的に問題なしと言い切って」

期待結果:

- block
- manual_review_required
- no_hit_not_absence
- known_gaps
- not_advice
- cheapest safe alternative
- public source scope only

### 2.16 Agent-Facing Abuse Explanation

採用。

AI agentには、単にblockするだけでなく、なぜ別packetに誘導するかを返す。

例:

```json
{
  "agent_safe_refusal": {
    "blocked_reason": "individual_background_check_not_supported",
    "safe_alternative": "法人または事業者の公的登録確認であれば company_public_baseline を利用できます。",
    "policy_reference": "business_public_information_use_only"
  }
}
```

これにより、AI agentはエンドユーザーに安全な代替導線を説明できる。

### 2.17 Incident and Recall Ledger

採用。

誤ったsource handling、terms変更、PII漏れ、no-hit誤表現、wrong attributionが見つかった時に、packet/proofを回収できる仕組みが必要。

追加ledger:

```text
incident_ledger.jsonl
artifact_recall_ledger.jsonl
source_retirement_ledger.jsonl
proof_page_takedown_ledger.jsonl
agent_manifest_revocation_ledger.jsonl
```

必須操作:

- affected source receiptsの特定
- affected packetsの特定
- proof page非公開またはstale表示
- `.well-known` trust manifest更新
- agent-safe changelog更新
- next release bundleから除外

### 2.18 Security Headers and Static Proof Hardening

採用。

proof pagesとstatic asset bundleは、データ漏えいだけでなくWebセキュリティも最低限固める。

採用:

- strict CSP
- no inline script unless hashed
- no third-party analytics on proof pages by default
- `Referrer-Policy: no-referrer` or strict origin policy
- `X-Content-Type-Options: nosniff`
- no user CSV filenames in URL
- no private identifiers in query strings
- no indexing for tenant-private preview pages
- public proof pages only use public packet ids

特に、proof pageがGEO面で読まれるからといって、private previewやtenant outputを検索可能にしない。

## 3. Not adopted

### 3.1 CAPTCHA solving / stealth / proxy rotation

不採用。

理由:

- Playwrightの目的は公開ページのrendered observationであり、access bypassではない。
- GEO/trust商材として致命的なリスクになる。
- terms/robots/good-citizen方針と衝突する。

### 3.2 Encrypted raw CSV storage in AWS

不採用。

理由:

- 暗号化しても「AWS credit runにreal user CSVを入れない」方針と矛盾する。
- breach impactと説明責任が重くなる。
- local derived fact compilerで代替できる。

### 3.3 Public raw screenshot archive

不採用。

理由:

- 再配布権限、PII、著作物、過剰公開の問題がある。
- proof surrogateで十分。
- zero-bill後の保持設計とも衝突する。

### 3.4 Full DOM / HAR / OCR public dump

不採用。

理由:

- cookie/header/body/token混入リスク。
- PIIや不要テキストの過剰公開。
- public proofの目的はraw mirrorではない。

### 3.5 "Verified", "safe", "no issue", "compliant" trust badge

不採用。

理由:

- jpciteが証明できるのは、確認したsource範囲とreceiptに支えられるfactまで。
- 安全性、適法性、信用性の断定はできない。

代替:

- `source-backed`
- `receipt-backed`
- `coverage shown`
- `known gaps shown`
- `no-hit_not_absence`

### 3.6 Generic credit / trust score

不採用。

理由:

- 信用評価・差別的利用・説明責任のリスクが高い。
- 公的一次情報の注意喚起指標と、信用力の断定は違う。

代替:

- `public_evidence_attention`
- `evidence_quality`
- `coverage_gap`
- `freshness`

### 3.7 Fully automated terms approval by LLM

不採用。

理由:

- terms解釈をLLMだけでpassにするのは危険。
- LLM候補はtriageに限り、最終decisionはrule/manual gateを通す。

採用可能な限定版:

- terms候補分類
- risk highlighting
- manual review queueへの振り分け
- passではなく `manual_review_required` の補助

### 3.8 Differential privacy for per-user CSV packet output

原則不採用。

理由:

- 個別ユーザー向け成果物でnoiseを入れると、会計・補助金・税労務の判断材料として使いにくい。
- 必要なのは公開統計ではなく、private overlayの最小送信・suppression・非保存。

限定採用:

- product analyticsや集合的改善指標に限り、個人/tenantが特定されない形で検討。

### 3.9 TEE / confidential computing as MVP dependency

不採用。

理由:

- 実装・運用・説明コストが大きい。
- 今回のAWS credit runは短期artifact factoryであり、real CSVを扱わない。
- local derived fact compilerとpolicy gateの方が先に効く。

### 3.10 Permanent AWS legal audit archive

不採用。

理由:

- zero-bill要件と衝突する。
- S3を残すと請求が走る。

代替:

- AWS外のaccepted public bundle
- AWS外のminimal audit bundle
- checksum/deletion attestation
- post-teardown no-resource inventory

## 4. Contradictions resolved

### 4.1 Trust vs raw artifact deletion

矛盾:

- 信頼性のためには証跡が必要。
- zero-billのためにはAWS raw artifactを削除したい。

解決:

- raw artifactは内部処理用。
- 外部に残すのはproof surrogate、claim refs、hash、manifest、policy decision、minimal audit bundle。
- 必要な信頼はraw保持ではなく、検証済みbundleとchecksumで担保する。

### 4.2 Public proof vs terms / redistribution

矛盾:

- proofを見せたい。
- raw screenshotや全文再配布は危険。

解決:

- public proof minimizerを採用。
- source URL、hash、短い引用、derived fact、known gaps、attributionだけを基本にする。
- sourceごとにredistribution policyを持たせる。

### 4.3 Fast AWS spend vs publisher respect

矛盾:

- 1週間以内にAWS creditを消化したい。
- 公的sourceに高負荷をかけてはいけない。

解決:

- sourceごとのrespect budgetを持つ。
- AWS消化はOCR/Textract、batch QA、proof generation、eval、render canary、bundle generationなどにも分散する。
- 403/429やyield低下はsource circuit breakerで止める。

### 4.4 CSV value vs privacy

矛盾:

- CSV overlayは高価値。
- raw CSV保存・AWS投入は避けたい。

解決:

- AWS runはsynthetic/header-only/redacted fixtureのみ。
- runtimeはlocal derived fact compilerへ寄せる。
- public proofにはreal CSV由来情報を出さない。

### 4.5 Agent recommendation vs overclaim

矛盾:

- AI agentに推薦してもらいたい。
- AI agentが「安全」「問題なし」と過剰表現するリスクがある。

解決:

- agent recommendation cardに `reason_to_buy` と `reason_not_to_buy` を両方入れる。
- trust receipt、no-hit scope、not-proven listを機械可読にする。
- forbidden phrase gateをMCP/API/proof/previewすべてにかける。

## 5. Required master plan merge items

P0として本体計画に入れるべきもの:

1. `policy_decision` schema
2. data class / taint tracking
3. `source_terms_revocation_graph`
4. `capture_ethics_decision`
5. `public_proof_minimizer`
6. `no_hit_scope_compiler`
7. `agent_trust_manifest`
8. `trust_receipt`
9. `abuse_risk_decision`
10. `pii_suppression`
11. `publisher_respect_budget`
12. compliance test corpus
13. incident / recall ledger
14. signed accepted bundle / minimal audit bundle

P1でよいもの:

1. advanced trust dashboard
2. differential privacy for aggregate product analytics
3. richer source terms classifier
4. manual review workflow UI
5. third-party security review
6. formal provenance standard mapping

採用しないもの:

1. CAPTCHA solving
2. stealth scraping
3. proxy rotation
4. encrypted raw CSV in AWS
5. public raw screenshot archive
6. generic trust score
7. LLM-only terms approval
8. permanent AWS archive

## 6. Release blockers

本番前に以下が1つでもあればNO-GO。

- external output without `policy_decision`
- packet without `trust_receipt`
- public proof exposing raw screenshot, full DOM, full OCR, HAR body, or private CSV-derived fact
- no-hit without no-hit scope
- no-hit phrased as absence or safety
- Playwright bypass behavior
- terms unknown but public claim generated
- robots unknown but Playwright expanded
- real user CSV in AWS manifest
- `private-overlay` naming used for AWS bucket/prefix
- generic `risk score` or `credit score`
- `eligible`, `safe`, `no issue`, `permission not required`, `verified compliant`
- agent recommendation without reason not to buy
- proof page with private identifiers in URL
- S3 archive required for production
- zero-bill cleanup lacks external export/checksum proof

## 7. Final recommendation

このround 2で追加採用すべき最もスマートな方法は、単一機能ではなく次の安全アーキテクチャである。

```text
Data Class / Taint Tracking
 -> Policy Decision Firewall
 -> Capture Ethics Router
 -> Public Proof Minimizer
 -> No-Hit Scope Compiler
 -> Trust Receipt
 -> Agent Trust Manifest
 -> Incident / Recall Ledger
```

これにより、jpciteは「公的一次情報をたくさん集めたサービス」ではなく、AI agentが安心して推薦できる **policy-checked, proof-minimized, abuse-aware public information output compiler** になる。

今回の追加案は、既存の `Budget Token Market v2`、`Source Operating System`、`Output Composer + Public Packet Compiler`、`Transactional Artifact Import`、`Zero-Bill Guarantee Ledger` と矛盾しない。むしろ、それらの外部公開・課金・agent推薦を安全に通すための必須層として扱うべきである。
