# AWS final consistency 08/10: Playwright, screenshot, OCR, terms, and source receipt review

作成日: 2026-05-15  
担当: 最終矛盾チェック 8/10 / Playwright・screenshot・OCR・terms  
対象AWS profile: `bookyou-recovery`  
対象AWS account: `993693061769`  
対象region: `us-east-1`  
状態: 計画精査のみ。AWS CLI/APIコマンド、AWSリソース作成、収集ジョブ実行、デプロイは行っていない。  
出力制約: このMarkdownのみを作成する。

## 0. 結論

Playwright / screenshot / OCR をAWSで使う設計は、jpciteの価値をかなり上げられる。特に、APIやCSVだけでは取りにくい「公的制度ページの可視状態」「自治体ページの表」「官報・告示・PDFの見た目」「検索結果なし画面の時点証跡」を `source_receipt` にできるため、AIエージェント向けのGEO価値は上がる。

ただし、現行計画のままでは「fetchが難しい部分を突破する」という言葉が、アクセス制御回避、robots/terms回避、CAPTCHA回避、ログイン突破、再配布権限のないスクリーンショット公開に読める余地がある。ここは本番前に明確に修正する。

最終採用ルールは次の通り。

1. Playwrightは「公開ページを正しくレンダリングして観測する手段」であり、アクセス制限を突破する手段ではない。
2. API、公式一括DL、公式CSV/XML/JSON/PDFがあるsourceでは、Playwrightは主取得ではなく補助証跡にする。
3. `source_profile`、`terms_receipt`、`robots_receipt` が `pass` または `allow_playwright_low_rate` になるまで大量Playwrightを走らせない。
4. robots.txt取得不能、terms不明、CAPTCHA、login wall、403/429反復、bot challengeは `manual_review_required` または `block` にする。
5. 保存スクリーンショットは各辺 `<= 1600px`。長大ページはtile化し、full-page巨大画像は保存しない。
6. HARはmetadata-only。body、cookie、authorization header、token、local/session storageは保存しない。
7. OCRは補助。日付、金額、法人番号、条番号、許認可番号などの重要fieldはOCR単独で断定しない。
8. スクリーンショットやOCR全文は原則公開再配布しない。公開packet/proof/API/MCPでは、URL、取得時刻、hash、短い引用、派生fact、出典表示、known_gapsを返す。
9. AWSは短期artifact factory。本番runtimeはAWS S3/Batch/OpenSearch/Glue/Athenaに依存しない。
10. zero-bill要件を優先し、外部exportとchecksum確認後、Playwright raw artifacts、S3、CloudWatch logs、ECR、Batch、EC2/EBS、OpenSearch等を削除する。

この修正を入れれば、Playwright広域取得、1週間以内の高速クレジット消化、本番デプロイ、zero-bill cleanup、source receipt契約は両立する。

## 1. 精査対象

主に以下を確認した。

- `aws_scope_expansion_06_playwright_capture.md`
- `aws_credit_review_11_source_terms_robots.md`
- `aws_scope_expansion_26_data_quality_gates.md`
- `aws_final_consistency_01_global.md`
- `aws_final_consistency_02_aws_autonomous_billing.md`
- `aws_final_consistency_06_release_train.md`
- `aws_scope_expansion_25_fast_spend_scheduler.md`
- `aws_scope_expansion_28_production_release_train.md`
- `aws_scope_expansion_29_post_aws_assetization.md`

公式確認した前提:

- AWS Batchは追加サービス料金ではなく、実際に作るEC2/Fargate/Lambda等の基盤リソースに課金される。
- FargateはvCPU秒、GB秒、OS/architecture、ephemeral storage等で課金される。
- S3はstorage、request、data retrieval、data transfer等の要素で課金される。
- CloudWatchはログ取り込み、保存、検索等が費用化する。
- NAT Gatewayは稼働時間と処理GBで課金される。
- Playwrightはscreenshot取得やfull-page screenshotを提供するが、jpciteでは保存画像を1600px以下tileに制限する。
- 公共データ利用規約やe-Gov系利用規約では、出典表示、加工表示、国や府省がjpciteの加工結果を保証しているように見せないことが重要になる。

## 2. 最終判定

| 項目 | 判定 | 必須修正 |
|---|---|---|
| Playwright on AWS | 条件付きPASS | source gate後にcanary、通過sourceだけ拡張 |
| 1600px screenshot | PASS | full-page巨大画像禁止、tile化必須 |
| DOM capture | PASS | sanitized DOMのみ、storage/cookie/tokenなし |
| HAR capture | 条件付きPASS | metadata-only、body/cookie/auth header禁止 |
| OCR | 条件付きPASS | confidence、bbox、hash link、重要field review必須 |
| robots/terms | 条件付きPASS | 不明時allow禁止、manual reviewへ |
| CAPTCHA/login | PASS with blocker | 検出したら停止、known_gapのみ |
| 再配布 | 条件付きPASS | screenshot/raw textは原則非公開、派生fact中心 |
| source_receipt連携 | PASS | screenshot/ocrはsource_receipt補助として接続 |
| cost | 条件付きPASS | Playwright単独で全額消化しない。yield悪化時は停止 |
| zero-bill | 条件付きPASS | export/checksum後、raw artifactとAWS資源を削除 |
| 本番デプロイ | PASS | AWS全量完了を待たず、accepted bundleのみimport |

## 3. 本体計画へマージする最終順序

Playwright/OCRを含むAWS計画は、本体P0計画と次の順番でマージする。

```text
1. contract freeze
2. packet/source_receipt/claim_ref/known_gaps schema freeze
3. source_profile schema freeze
4. terms_receipt / robots_receipt schema freeze
5. AWS guardrails / cost stopline / kill switch / external export gate
6. J01 source profile sweep
7. API / official download / public bulk data first
8. Playwright canary for approved sources only
9. screenshot_receipt / DOM / HAR metadata / OCR input generation
10. OCR only for approved visual/PDF sources
11. claim_ref generation and evidence graph
12. packet/proof fixture generation
13. import validator and release gates
14. RC1a static proof / RC1b minimal MCP/API / RC1c limited paid
15. broader AWS autonomous run continues behind release train
16. final export outside AWS
17. zero-bill teardown
```

実行上の重要点:

- AWSの自走は早めに始めてよいが、`J01 source profile sweep` とguardrailsなしにPlaywright大量起動はしない。
- Codex/Claudeがrate limitになってもAWS Batch/Step Functions/EventBridge/SQSで動き続ける設計にする。
- ただし、`allow_new_work=false`、terms drift、robots block、CAPTCHA増加、accepted artifact yield悪化、cost stopline到達ではAWS内部で自動的に新規投入を止める。
- 本番デプロイはAWS全量完了待ちにしない。accepted canary bundleだけでRC1を出す。

## 4. 矛盾チェック

### C08-01: 「fetch困難を突破」と「アクセス制限回避禁止」

判定: 表現上の矛盾あり。修正必須。

問題:

- 「突破」と書くと、CAPTCHA、bot challenge、login wall、rate limit、robots、termsを回避するように読める。
- jpciteの信頼性は公的一次情報の正当な利用に依存するため、ここを曖昧にすると本番投入できない。

採用修正:

```text
Playwrightは、公開一次情報ページを公式に閲覧可能な範囲でレンダリングし、
その可視状態・DOM・リンク・テキスト・PDF参照を証跡化するために使う。
アクセス制限、認証、CAPTCHA、robots/terms、rate limitを回避するためには使わない。
```

Release blocker:

- `stealth plugin`
- CAPTCHA solver
- proxy rotation
- residential proxy
- login credential
- cookie reuse
- hidden API reverse engineering
- request header spoofing for evasion
- robots disallow path capture
- terms-prohibited capture

### C08-02: API優先とPlaywright大量取得

判定: 両立可能。ただし優先順位を固定する。

取得優先順位:

1. 公式API
2. 公式一括ダウンロード
3. 公式CSV/XML/JSON/PDF
4. HTML direct fetch
5. Playwright rendered capture
6. OCR

修正:

- e-Gov法令API、法人番号、インボイス、e-Stat、J-Grants、gBizINFO、EDINET等で公式API/DLがある場合、Playwrightは主経路にしない。
- Playwrightは、公式ページの可視状態、リンク確認、検索結果画面、自治体ページ、画像PDF、JavaScript表示表など、renderが必要なsourceに限定する。
- Playwrightで同じ事実を大量に取るより、API/DLでfact化し、必要箇所だけscreenshot corroborationを追加する方が安く、正確で、本番投入しやすい。

### C08-03: 「広く取る」とsource_profile gate

判定: 両立可能。ただしgate順を逆にしない。

問題:

- 広域にPlaywrightを先に走らせると、terms不明、robots不明、再配布不可、品質不明のraw artifactが大量に残る。
- これはAWSクレジット消化にはなるが、商品資産化しにくい。

採用修正:

- `source_profile` がないsourceは `metadata_only` まで。
- `terms_receipt` がないsourceは Playwright大量取得禁止。
- `robots_receipt` がないHTML/Playwright sourceは `manual_review_required`。
- `license_boundary` が `link_only` のsourceは screenshot/DOM/OCRをclaim根拠にしない。

必須source_profile fields:

```json
{
  "source_profile_id": "sp_example",
  "source_family": "law_regulation | local_government | gazette_notice | permit_registry | enforcement | grants | procurement | statistics | standards",
  "publisher": "official publisher",
  "official_domain": "example.go.jp",
  "source_kind": "official_api | official_download | official_html | official_pdf | official_registry",
  "terms_url": "https://...",
  "terms_hash": "sha256:...",
  "terms_checked_at": "2026-05-15T00:00:00+09:00",
  "robots_url": "https://example.go.jp/robots.txt",
  "robots_hash": "sha256:...",
  "robots_decision": "allow | api_only | download_only | allow_playwright_low_rate | metadata_only | link_only | blocked | manual_review",
  "redistribution_policy": {
    "raw_html": "forbidden | internal_only | allowed",
    "screenshot": "forbidden | internal_only | proof_allowed | allowed",
    "ocr_text": "forbidden | internal_only | short_quote_only | allowed",
    "derived_fact": "allowed_with_attribution",
    "metadata": "allowed_with_attribution"
  },
  "allowed_capture_methods": ["api", "download", "html", "playwright", "ocr"],
  "rate_limit_policy_id": "rlp_example",
  "attribution_required": true,
  "public_publish_default": false
}
```

### C08-04: robots.txt不明時の扱い

判定: 既存計画は概ね正しいが、本体SOTへ明示マージが必要。

採用ルール:

| 状態 | 判断 |
|---|---|
| robots fetch成功、Allow | terms確認後に低レート可 |
| robots fetch成功、Disallow | block |
| robots fetch失敗 | manual_review_required |
| robotsなし相当だがtermsでAPI/DL推奨 | API/DLのみ |
| robotsはAllowだがtermsが大量取得禁止 | blockまたはmanual_review |
| robotsはAllowだが429/403反復 | stop host |

重要:

- robots.txtがない、または取れないことを「自由に大量取得してよい」と解釈しない。
- robotsは最低条件であり、terms、API規約、アクセス制限、過負荷回避と併用する。

### C08-05: CAPTCHA/login/error page screenshotの扱い

判定: 明確化すればPASS。

採用ルール:

| 状態 | 保存可否 | claim support | output |
|---|---:|---:|---|
| CAPTCHA | error evidenceのみ | 不可 | known_gap |
| bot challenge | error evidenceのみ | 不可 | known_gap |
| login wall | error evidenceのみ | 不可 | known_gap |
| 401/403 | error metadataのみ | 不可 | known_gap |
| repeated 429 | error metadataのみ | 不可 | rate_limit_gap |
| terms wall | error metadataのみ | 不可 | manual_review |
| cookie bannerが本文を覆う | conditional | 原則不可 | manual_review |

禁止:

- CAPTCHAを解く
- CAPTCHA solverを使う
- loginする
- private accountを作る
- cookie/sessionを再利用する
- bot challengeを避けるためにUAやproxyを偽装する
- hidden endpointを推測して大量アクセスする

### C08-06: 1600px以下スクリーンショット

判定: PASS。ただし実装条件を固定する。

採用ルール:

- 保存される画像は、width/heightともに `<= 1600px`。
- device scale factorは原則 `1`。
- full-page screenshotを1枚で保存しない。
- 長いページは `clip` またはtile sequenceにする。
- tileが上限に達した場合は `capture_truncated=true` と `known_gaps[]` を付ける。
- OCR用tileも `<= 1600x1600`。
- screenshotは証跡であり、商品本体ではない。

必須validator:

```text
if stored_image_width > 1600: block
if stored_image_height > 1600: block
if image_sha256 missing: block
if blankness_ratio > 0.85: quarantine
if captcha/login detected: block_for_claim_support
if visible_text missing and no explained reason: manual_review_required
if screenshot_public_publish_allowed is true without terms proof: block
```

### C08-07: HARとconsole log

判定: 条件付きPASS。

問題:

- HAR full bodyを保存すると、HTML全文、third-party payload、cookie、token、個人情報、analytics情報が混入しやすい。
- CloudWatch Logsへconsole全文を流すと費用と漏洩リスクが増える。

採用修正:

- `HAR_CONTENT_MODE=omit` を固定。
- 保存するのはmetadata-only。
- request/response body保存は禁止。
- Cookie、Authorization、Set-Cookie、token-like query params、session id、local storage、session storageは保存禁止。
- console logはcount、level、message hash、短いredacted sampleだけ。
- CloudWatch Logsはmetadata中心、本文・DOM・OCR全文を出さない。

HAR allowed fields:

```json
{
  "request_url_redacted": "https://example.go.jp/path?...",
  "method": "GET",
  "status": 200,
  "resource_type": "document",
  "content_type": "text/html",
  "domain": "example.go.jp",
  "redirect_chain": ["..."],
  "timing_ms": 1234,
  "transfer_size_bytes": 123456,
  "blocked_reason": null
}
```

### C08-08: OCRの根拠力

判定: 条件付きPASS。

OCRは強力だが、誤読がある。したがって、OCR単独で高リスクclaimを出さない。

Field別ルール:

| field | OCRのみの直接support | 必須条件 |
|---|---:|---|
| source title | 条件付き可 | confidence >= 0.85 |
| deadline/date | 原則不可 | confidence >= 0.95 + manual review or cross-check |
| amount/rate | 原則不可 | confidence >= 0.97 + table structure pass |
| legal article number | 原則不可 | confidence >= 0.97 + e-Gov/API照合優先 |
| corporation number | 不可に近い | confidence >= 0.98 + official registry照合 |
| permit number | 原則不可 | official registry照合 |
| free text summary | weak only | template/ruleで要約、claim_ref必須 |

OCR receipt必須fields:

```json
{
  "ocr_receipt_id": "ocr_...",
  "source_receipt_id": "sr_...",
  "input_artifact_id": "ssr_or_pdf_tile_...",
  "engine": "textract_or_local_ocr",
  "language_hint": "ja",
  "bbox": [0, 0, 1600, 900],
  "confidence": {
    "page_mean": 0.0,
    "token_p05": 0.0,
    "numeric_token_mean": 0.0,
    "date_token_mean": 0.0
  },
  "text_sha256": "sha256:...",
  "manual_review_required": true,
  "public_redistribution_allowed": false
}
```

### C08-09: screenshot再配布とproof page

判定: 既存計画はやや危険。修正必須。

問題:

- 公的サイトでも、すべての画面画像をjpciteが自由に公開再配布できるとは限らない。
- 公的ページ内に第三者著作物、地図、写真、ロゴ、添付資料、個人名、公告、PDFスキャンが含まれる可能性がある。
- screenshotをproof pageに直接大量表示すると、terms/著作権/個人情報/再配布リスクが増える。

採用修正:

- `screenshot_public_publish_allowed=false` をdefaultにする。
- proof pageで標準表示するのは、source URL、publisher、retrieved_at、document_date、hash、短い引用、claim_refs、known_gaps、attribution。
- screenshotは内部証跡または人手確認用を基本にする。
- public screenshot/cropは、source_profileで `screenshot: proof_allowed | allowed` が明示された場合だけ。
- OCR全文の公開再配布も原則禁止。短い引用または派生factに限定する。

Public proof pageに出してよいもの:

- `source_url`
- `publisher`
- `retrieved_at`
- `document_date`
- `content_sha256`
- `visible_text_sha256`
- `screenshot_sha256`
- `claim_refs[]`
- `known_gaps[]`
- 短い引用
- jpciteが生成した構造化fact
- 出典表示と加工表示

出してはいけないもの:

- raw HTML
- raw PDF full copy
- raw screenshot bulk
- raw HAR
- cookies / headers
- OCR full text
- CloudWatch logs
- S3 URLs
- unreviewed screenshot
- CAPTCHA/login/error page images

### C08-10: source_receiptとの整合

判定: PASS。ただしreceiptの階層を固定する。

Playwright artifactは、直接商品ではなく `source_receipt` と `claim_ref` を支える下位証跡にする。

階層:

```text
source_profile
  -> terms_receipt
  -> robots_receipt
  -> capture_request
  -> source_receipt
      -> screenshot_receipt
      -> dom_receipt
      -> visible_text_receipt
      -> har_metadata_receipt
      -> ocr_receipt
  -> claim_ref
  -> packet
  -> proof page / API / MCP
```

`source_receipt.support_capability`:

```json
{
  "can_support_claim": true,
  "support_level": "direct | corroborating | weak | no_claim_support",
  "support_reason": "official_api | rendered_visible_text | ocr_with_review | blocked_state_known_gap",
  "allowed_claim_fields": ["deadline", "program_name"],
  "requires_human_review": false
}
```

support rules:

| evidence | support level |
|---|---|
| official API/DL | direct |
| DOM visible text + terms pass | direct |
| screenshot + visible text | corroborating/direct depending source |
| screenshot + OCR only | weak/manual_review |
| screenshot of no-result page | no_hit_not_absence only |
| screenshot of CAPTCHA/login/403/429 | no_claim_support |
| OCR low confidence | weak or no_claim_support |
| terms unknown | no_claim_support |

### C08-11: no-hit semantics

判定: PASS。Playwrightでも同じ制約を適用する。

Playwrightで検索結果なし画面や該当なし表示を取得しても、結論は必ず `no_hit_not_absence`。

許可表現:

```text
取得時点の当該公式ページ/検索条件/スナップショットでは、一致する公開レコードを確認できませんでした。
これは不存在、安全、適法、許可不要、問題なしを意味しません。
```

禁止表現:

- 存在しません
- 問題ありません
- 安全です
- 許認可は不要です
- 違法ではありません
- 行政処分は一切ありません
- 取引してよいです

### C08-12: costと高速消化

判定: 条件付きPASS。

PlaywrightはAWS credit消化には向くが、無差別に走らせると価値の低い費用になりやすい。最終方針は「早く広く、ただしaccepted artifact yieldで止める」。

Playwright/OCR budget bands:

| band | 目的 | 目安 |
|---|---|---:|
| canary | schema/terms/quality検証 | USD 50-200 |
| standard | 高価値render source | USD 800-2,500 |
| broad | 自治体/制度/告示/調達の広域補完 | USD 2,500-6,000 |
| stretch | accepted yieldが高いsourceだけ増強 | USD 6,000-9,000 |

ただし、Playwright単独でUSD 19,300を使い切らない。残りはAPI/DL source lake、OCR、claim graph、proof fixture、GEO eval、packet生成、quality gatesに配分する。

コスト停止条件:

- accepted capture rateが規定未満
- CAPTCHA/login/403/429比率が上昇
- screenshot blankness ratioが高い
- `metadata_only` sourceが多すぎる
- logsまたはS3 artifact sizeが予算を圧迫
- terms/robots manual review待ちが増える
- CloudWatch Logsが想定以上に増える
- NAT Gateway/Public IPv4/EIPなどの周辺費用が出る

### C08-13: zero-bill cleanup

判定: 条件付きPASS。外部export gateが必須。

zero-bill要件:

- AWS credit run終了後、AWS上に課金資源を残さない。
- S3 final bucketを残す案は、ユーザー要件「これ以上請求が走らない」に反するため不採用。
- 成果物を失わないため、export/checksum確認後に削除する。

Playwright系削除対象:

- raw screenshot bucket/prefix
- DOM snapshot prefix
- HAR metadata prefix
- OCR input/output prefix
- temporary PDFs
- ECR browser image repository
- Batch job queues and compute environments
- ECS/Fargate tasks
- EC2 Spot instances
- EBS volumes and snapshots
- CloudWatch log groups/alarms/dashboards
- Step Functions state machines/executions
- EventBridge schedules
- SQS queues
- DynamoDB control table
- OpenSearch, Glue, Athena outputs if used
- NAT Gateway, EIP, ENI, security groups if created

外部exportに必須:

```text
export_manifest.json
checksum_manifest.json
artifact_manifest.json
source_profile_registry.json
terms_robots_ledger.parquet/json
accepted_source_receipts.jsonl
accepted_claim_refs.jsonl
known_gaps.jsonl
packet_fixtures.jsonl
proof_page_inputs.jsonl
quality_gate_report.md
cost_artifact_ledger.csv
```

## 5. 最終Playwright実行方式

### 5.1 capture_request

```json
{
  "schema_id": "jpcite.capture_request",
  "run_id": "aws_2026_05_credit_run",
  "source_profile_id": "sp_...",
  "url": "https://example.go.jp/page",
  "capture_method": "playwright_chromium",
  "reason": "rendered_public_page_needed_for_receipt",
  "allowed_by_terms_receipt_id": "tr_...",
  "allowed_by_robots_receipt_id": "rr_...",
  "viewport": {
    "width": 1280,
    "height": 900,
    "device_scale_factor": 1
  },
  "limits": {
    "max_capture_seconds": 45,
    "max_tiles_per_page": 5,
    "max_screenshot_edge_px": 1600,
    "max_attempts": 2
  },
  "har_policy": "metadata_only",
  "console_policy": "redacted_summary_only",
  "pdf_print_allowed": false,
  "request_time_llm_call_performed": false
}
```

### 5.2 worker flow

```text
1. Read capture_request from immutable shard.
2. Load source_profile.
3. Verify terms_receipt and robots_receipt.
4. Verify host/path allowlist.
5. Enforce per-host rate limit.
6. Create fresh non-persistent Chromium context.
7. No cookies, no saved profile, no login, no local/session storage reuse.
8. Set viewport <= 1600 width and deviceScaleFactor=1.
9. Navigate with strict timeout.
10. Detect CAPTCHA/login/bot challenge/403/429/terms wall.
11. If blocked, emit blocked_receipt and stop.
12. Extract canonical URL, title, headings, visible text, selected tables, links.
13. Store sanitized DOM and visible text hashes.
14. Capture 1600px-bounded screenshot tile(s).
15. Save HAR metadata without body/cookie/auth.
16. Redact and cap console metadata.
17. Generate OCR input tile manifest if needed.
18. Write source_receipt + artifact manifests + cost ledger.
19. Run validators before marking accepted.
20. Close context and delete local temp files.
```

### 5.3 per-host policy

Default:

- max 1 concurrent capture per host
- minimum 3 seconds between navigations per host
- max attempts 1-2
- exponential backoff on 429/503
- stop host on CAPTCHA/login/bot challenge
- stop host on repeated 403/429
- do not submit public search forms in bulk unless source_profile explicitly allows it

Large official source exception:

- only if official API/DL is unavailable or insufficient
- only if source_profile explicitly permits higher rate
- only if accepted artifact yield remains high
- only if error/rate-limit ratio remains low

## 6. Quality gates

### 6.1 source gate

Block if:

- source_profile missing
- terms URL/basis missing
- terms hash missing
- robots decision missing for HTML/Playwright
- license boundary unknown
- redistribution policy unknown
- publisher not official or not validated
- source family not mapped to paid packet/proof use

### 6.2 capture gate

Block if:

- CAPTCHA/login/bot challenge/access wall
- response path outside allowlist
- screenshot > 1600px on any side
- raw HAR body stored
- cookies/auth headers stored
- DOM includes storage/session data
- artifact hash missing
- private CSV/user data detected
- `request_time_llm_call_performed != false`
- Playwright used for source with `api_only` or `download_only`

### 6.3 OCR gate

Block or manual review if:

- OCR confidence missing
- bbox/page/tile link missing
- source_receipt link missing
- image/text hash link missing
- important field is OCR-only
- table structure uncertain for money/date/rate fields
- OCR text would be publicly redistributed as full source text

### 6.4 product gate

Block publication if:

- claim lacks source_receipt
- claim depends only on unreviewed screenshot
- no-hit is rewritten as absence/safety
- screenshot_public_publish_allowed missing but screenshot is public
- raw HTML/PDF/HAR/OCR text appears in API/MCP/proof page
- source attribution missing
-加工表示 missing
- known_gaps hidden
- AWS S3 URL appears in product output

## 7. Terms/robots drift

terms/robotsは変わる。したがって、AWS run中も本番import時もdriftを検出する。

drift triggers:

- terms page hash changed
- robots.txt hash changed
- official API terms changed
- source returns new access wall
- publisher changes domain or canonical URLs
- source adds login/CAPTCHA
- 403/429 ratio changes materially
- public data license changes

drift action:

```text
source_profile.gate_status = manual_review_required
allow_new_work_for_source = false
new claim generation = false
existing accepted claims = stale_review_required
proof pages = keep with stale warning or hide if terms risk
```

## 8. Production import decision

Accepted Playwright/OCR artifacts can enter production only after compacting into validated bundle.

Allowed into repo/static/db:

- accepted `source_profile`
- accepted `terms_receipt`
- accepted `robots_receipt`
- accepted `source_receipt`
- accepted `claim_ref`
- accepted `known_gap`
- packet fixtures
- proof page input JSON
- cost/artifact ledger summary
- checksum manifest

Not allowed into repo/static/db:

- raw screenshots unless explicitly public-approved and small sample only
- raw DOM full dumps
- raw HAR
- raw OCR text full dumps
- raw PDFs mirrored without terms approval
- CloudWatch logs
- S3 URL references
- private CSV or real customer-derived data

## 9. Release train impact

This review changes release train as follows.

RC1a:

- static proof pages can show source receipt structure and accepted sample metadata.
- public screenshots are disabled by default.
- screenshot hash and short citation are enough for proof.

RC1b:

- minimal MCP/API returns `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata`.
- `capture_method` may include `playwright_chromium`, but output must not expose raw artifacts.

RC1c:

- limited paid packets can use Playwright-backed claims only if product gate passes.
- no-hit pages from Playwright must include no-hit caveat.

RC2/RC3:

- broader vertical packets can use Playwright/OCR after canary pass and source family gates.
- local government, permits, public notices, standards/certifications, enforcement, grants/procurement are good candidates.

## 10. Final action items for main SOT

Merge these items into the main AWS + product plan before execution.

1. Rename "fetch困難を突破" to "公開ページのrendered observation".
2. Add `terms_receipt` and `robots_receipt` as hard prerequisites for Playwright.
3. Set `screenshot_public_publish_allowed=false` by default.
4. Add screenshot dimension validator: each side `<= 1600px`.
5. Add HAR body/cookie/auth-header blocker.
6. Add OCR field-level confidence and critical-field review rules.
7. Add blocked state handling for CAPTCHA/login/403/429.
8. Add source-level Playwright canary before broad capture.
9. Add accepted artifact yield stop condition.
10. Add public proof policy: metadata/hash/short quote/derived fact first, screenshot only if explicitly allowed.
11. Add source terms drift stop condition.
12. Add external export gate before zero-bill teardown.
13. Add production import ban for raw screenshot/DOM/HAR/OCR full text.
14. Keep AWS autonomous run independent from Codex/Claude sessions, but tied to AWS-internal kill switch.

## 11. Final verdict

Playwright/screenshot/OCRのAWS投入は採用でよい。日本の公的一次情報を広く資産化するうえで、API/DLだけでは取りきれない証跡を補完できる。

ただし、Playwrightは「回避」ではなく「公開可視状態の証跡化」に限定する。source_profile、terms、robots、rate limit、再配布、OCR confidence、1600px制限、zero-bill cleanupをすべてgateに入れる。この形なら、AWSクレジットを高速に価値化しつつ、jpciteの「一次情報ベース・ハルシネーションなし・AIエージェントが推薦しやすい成果物」という本体コンセプトと矛盾しない。

## 12. References checked

- AWS Batch pricing: https://aws.amazon.com/batch/pricing/
- AWS Fargate pricing: https://aws.amazon.com/jp/fargate/pricing/
- Amazon S3 pricing: https://aws.amazon.com/s3/pricing/
- Amazon CloudWatch pricing: https://aws.amazon.com/cloudwatch/pricing/
- NAT Gateway pricing: https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-pricing.html
- Playwright screenshots: https://playwright.dev/docs/next/screenshots
- Digital Agency open data / 公共データ利用規約: https://www.digital.go.jp/resources/open_data
- e-Gov API catalog terms: https://api-catalog.e-gov.go.jp/info/terms
- e-Gov 法令API仕様書: https://laws.e-gov.go.jp/file/houreiapi_shiyosyo.pdf
