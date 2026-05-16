# AWS final 12 review 09/12: smarter source discovery and data acquisition

作成日: 2026-05-15  
担当: 最終追加検証 9/12 / smarter source discovery and data acquisition  
対象: jpcite AWS credit run, public official source corpus, packet output factory, GEO-first agent recommendation  
AWS execution: not executed  
AWS CLI/API: not executed  
Output file: `docs/_internal/aws_final_12_review_09_smart_source_discovery.md`

---

## 0. 結論

判定: **条件付きPASS。現行計画は成立しているが、source discovery / data acquisition はさらにスマートにできる。**

よりスマートな方法は、sourceを先に大量列挙して取りに行くことではない。

採用すべき中核は次である。

> `output_gap_map` を中心に、売れるpacketで不足しているclaimからsource候補を発見し、`source_candidate_registry` で仮説管理し、`capture_method_router` で最も安く安全な取得方法を選び、`expand_suppress_controller` がaccepted artifact率・gap削減・terms risk・costを見て自動で拡張/停止する。

これにより、AWS creditを「広く取るため」ではなく、「成果物に変換できる一次情報を高密度に発見するため」に使える。

現行計画に大きな矛盾はない。ただし、以下は本体計画へ明示的にマージすべきである。

1. `source_candidate_registry` を `source_profile` の前段に置く。
2. `source_profile` へ入れる前に、source候補を `output_gap_map` / paid packet / known gap / agent demand と紐づける。
3. `capture_method_router` は API/bulk/RSS/sitemap/static HTML/PDF text/Playwright/OCR の順で、安く・規約が明確で・根拠力が強い方法を優先する。
4. Playwrightは「突破」ではなく `public rendered observation` に限定し、canary passなしで広域実行しない。
5. `failed_source_ledger` を作り、失敗sourceを再試行地獄にしない。
6. `source_freshness_monitor` はAWS終了後も動く前提にせず、productionではTTL/staleness表示と非AWS更新経路を分ける。
7. `source_terms_classifier` は自動分類だけで公開claimを許可せず、confidenceが低いものは `manual_review_required` に落とす。
8. source探索の成果指標は「取得件数」ではなく、`accepted_artifact_count`、`gap_reduction_score`、`cost_per_accepted_artifact`、`packet_fixture_contribution` にする。

---

## 1. 現行計画の評価

現行の正本は、以下の重要制約をすでに正しく置いている。

- AWSは一時的なartifact factoryであり、runtime依存にしない。
- `USD 19,300`を意図的上限にして、credit face valueぴったりは狙わない。
- `source_profile_gate`、`terms_robots_gate`、`known_gaps[]`、`no_hit_not_absence` を必須化している。
- Playwrightは公開ページのrendered observationであり、アクセス制限回避ではない。
- raw CSVはAWS credit runに入れない。
- sourceごとに `accepted_artifact_target` が必要。
- 最後は外部export後にAWS resourcesを削除し、zero-bill postureへ戻す。

これは方向として正しい。

ただし、source discoveryの機能面では、まだ「source familyを広げる」「source優先順位を決める」という発想が残っている。今回の最終検証では、そこを一段抽象化し、**source acquisitionを成果物生成エンジンのフィードバック制御にする**方がスマートだと判断する。

---

## 2. よりスマートな機能像

### 2.1 Source Discovery Control Plane

追加すべき概念は `Source Discovery Control Plane` である。

これはAWSのインフラ制御面ではなく、jpciteのsource探索ロジックである。

役割:

- 売れるpacketで不足しているclaimを把握する。
- そのclaimを支えられそうなsource候補を発見する。
- source候補をすぐ収集せず、まずregistryに仮登録する。
- terms/robots/license/capture policyを分類する。
- 最も安く安全なcapture methodを選ぶ。
- canaryでaccepted artifact化できるか測る。
- 成功sourceだけ拡張し、低価値/高リスクsourceは抑制する。
- 失敗sourceをledger化し、同じ失敗を繰り返さない。
- packet利用・known gaps・GEO閲覧から次のsource候補を逆算する。

この機能により、jpciteは「公的情報をたくさん持つサービス」ではなく、「AIエージェントが欲しい成果物に必要な一次情報を自動的に増やすサービス」になる。

---

## 3. `output_gap_map`

### 3.1 目的

`output_gap_map` は、source探索の起点である。

sourceから出発するのではなく、packetから出発する。

例:

- `company_public_baseline` が「行政処分の有無」を表示したいが、業種別sourceが不足している。
- `grant_candidate_shortlist` が「自治体補助金」を返したいが、地域source coverageが不足している。
- `permit_rule_check` が「自治体条例/申請窓口」を返したいが、local sourceが不足している。
- `tax_labor_event_radar` が「最低賃金/社保/労働保険イベント」を返したいが、更新監視sourceが不足している。

この不足を構造化して、source discoveryへ渡す。

### 3.2 schema案

```json
{
  "schema_id": "jpcite.output_gap_map.v1",
  "gap_id": "ogm_...",
  "packet_id": "company_public_baseline",
  "claim_template_id": "administrative_disposition_presence",
  "end_user_task": "取引先の公的確認",
  "agent_recommendation_value": "AIが追加調査を薦めやすくなる",
  "missing_fact_type": "public_administrative_action",
  "jurisdiction": "JP",
  "industry_scope": ["construction", "real_estate", "transport"],
  "geo_scope": ["national", "prefecture", "municipality"],
  "required_source_capability": [
    "official_publication",
    "query_by_company_or_license",
    "date_or_status_available",
    "stable_citation_possible"
  ],
  "risk_level": "medium",
  "required_freshness_ttl_days": 30,
  "minimum_claim_strength": "direct_or_official_index",
  "allowed_no_hit_policy": "no_hit_not_absence",
  "current_known_gaps": [
    "local_source_missing",
    "industry_specific_source_missing"
  ],
  "revenue_signal": {
    "packet_price_band": "low_mid",
    "preview_to_paid_importance": "high",
    "expected_agent_recommendability": "high"
  },
  "discovery_status": "needs_source_candidates"
}
```

### 3.3 重要な設計

`output_gap_map` には「source名」ではなく「必要なsource能力」を書く。

これにより、未知のsourceも発見対象になる。

悪い例:

- 「国交省ネガティブ情報を取る」

良い例:

- 「建設業者の行政処分を、公的sourceから、法人/許可番号/年月日/処分種別単位でclaim化できるsourceが必要」

この違いにより、公式リンクグラフ、sitemap、API catalog、自治体ODS、官報、告示、所管省庁ページから、より自然にsource候補を発見できる。

---

## 4. `source_candidate_registry`

### 4.1 `source_profile` の前段に置く

現行計画では `source_profile` が重要になっている。これは正しい。

ただし、よりスマートにするには、`source_profile` の前に `source_candidate_registry` を置くべきである。

理由:

- 発見したsource候補の多くは、まだterms/robots/licenseが未確認。
- いきなり `source_profile` にすると、pass/fail対象が増えすぎる。
- 候補sourceと成果物gapの関係を保存しないと、なぜ取るのか分からなくなる。
- 後から「このsourceは売上に効いたか」を測れない。

### 4.2 state model

```text
discovered
  -> candidate_scored
  -> terms_preclassified
  -> canary_ready
  -> source_profile_candidate
  -> source_profile_pass
  -> canary_capture_pass
  -> expanded_collection
  -> accepted_artifact_source
```

blocked系:

```text
blocked_terms
blocked_robots
blocked_access_control
blocked_low_yield
blocked_high_cost
blocked_private_or_sensitive
blocked_no_packet_gap
manual_review_required
metadata_only
link_only
```

### 4.3 schema案

```json
{
  "schema_id": "jpcite.source_candidate.v1",
  "source_candidate_id": "sc_...",
  "discovered_from": [
    "output_gap_map",
    "official_link_graph",
    "sitemap",
    "rss",
    "api_catalog",
    "packet_to_source_backcaster",
    "failed_source_replacement"
  ],
  "candidate_url_or_endpoint": "https://example.go.jp/...",
  "publisher": "official_government_body",
  "official_domain_evidence": {
    "domain": "example.go.jp",
    "confidence": 0.92,
    "receipt_id": "sr_..."
  },
  "linked_output_gap_ids": ["ogm_..."],
  "linked_packet_ids": ["company_public_baseline"],
  "expected_source_capabilities": [
    "query_result_page",
    "public_status",
    "date_field",
    "stable_url"
  ],
  "terms_preclassification": "unknown",
  "robots_preclassification": "unknown",
  "capture_method_candidates": ["api", "bulk_download", "html", "pdf", "playwright", "ocr"],
  "expected_artifact_targets": [
    "source_profile",
    "source_receipt",
    "claim_ref",
    "known_gap",
    "no_hit_check",
    "packet_fixture"
  ],
  "candidate_score": {
    "gap_reduction_estimate": 0.8,
    "revenue_relevance": 0.75,
    "officialness": 0.9,
    "terms_clarity": 0.2,
    "automation_yield_estimate": 0.6,
    "freshness_value": 0.7,
    "cost_to_accept_estimate": 0.4,
    "risk_penalty": 0.3
  },
  "state": "terms_preclassified",
  "next_action": "run_terms_classifier"
}
```

### 4.4 矛盾確認

`source_candidate_registry` は現行の `source_profile_gate` と矛盾しない。

むしろ、`source_profile` を汚さないための前段である。

`source_profile` は「本番投入可能なsource契約」に近い。  
`source_candidate_registry` は「探索中のsource仮説」である。

---

## 5. `capture_method_router`

### 5.1 目的

sourceごとに最初からPlaywright/OCRへ行かない。

よりスマートなrouterは、根拠力・コスト・規約明確性・再現性の順で取得手段を選ぶ。

推奨順:

1. official API
2. official bulk download
3. official RSS / sitemap / update feed
4. static HTML / accessible table
5. PDF text layer
6. Playwright visible text / rendered DOM
7. screenshot receipt
8. OCR on bounded tile
9. metadata-only / link-only
10. known_gap

### 5.2 router decision

```json
{
  "schema_id": "jpcite.capture_method_decision.v1",
  "source_candidate_id": "sc_...",
  "source_profile_id": "sp_...",
  "output_gap_ids": ["ogm_..."],
  "selected_method": "playwright_visible_text",
  "fallback_methods": ["screenshot_receipt", "metadata_only"],
  "blocked_methods": [
    {
      "method": "ocr",
      "reason": "text_layer_available"
    },
    {
      "method": "html_crawl",
      "reason": "js_render_required"
    }
  ],
  "terms_decision_id": "terms_...",
  "robots_decision_id": "robots_...",
  "max_screenshot_edge_px": 1600,
  "har_content_mode": "omit",
  "claim_support_level": "direct_if_visible_text_extracted",
  "public_publish_policy": "derived_fact_only",
  "no_hit_policy": "no_hit_not_absence"
}
```

### 5.3 router rules

```text
if source_profile is missing:
  allow only metadata discovery and terms classification

if terms or robots are unknown:
  no broad capture
  no claim support
  output known_gap/manual_review_required

if official API or bulk download exists and terms allow:
  prefer API/bulk

if static HTML has stable visible text:
  prefer HTML extraction over Playwright

if PDF has text layer:
  prefer PDF text extraction over OCR

if page is public, JS-rendered, terms/robots allow, and packet gap requires it:
  allow Playwright canary

if scanned image/PDF requires OCR:
  require OCR confidence policy and no critical field OCR-only assertion

if CAPTCHA/login/403/429/access wall appears:
  no claim support
  write failed_source_ledger and known_gap
```

### 5.4 矛盾確認

このrouterは「AWSでPlaywrightも使う」というユーザー意図と矛盾しない。

ただし、Playwrightを「fetch困難な部分の突破」と表現するのは危険である。  
正しい定義は、**公開ページのrendered observation** である。

CAPTCHA、login、bot challenge、403/429の反復は突破対象ではなく、`known_gap` / `failed_source_ledger` の対象にする。

---

## 6. `Playwright canary router`

### 6.1 目的

Playwrightは強力だが、費用・terms・品質・証跡サイズのリスクがある。

したがって、source familyごとにいきなり広域投入せず、canary ladderを必須にする。

### 6.2 canary ladder

```text
L0: source candidate metadata only
L1: terms/robots fetch and hash
L2: URL pattern validation
L3: 1-5 page rendered observation
L4: screenshot dimension validation <= 1600px
L5: blocked-state detector validation
L6: visible text / DOM extraction validation
L7: source_receipt candidate generation
L8: claim_ref candidate generation
L9: accepted artifact measurement
L10: controlled expansion
```

### 6.3 canary pass条件

- `source_profile` が pass または limited pass。
- terms/robots decisionが存在する。
- stored screenshotが各辺 `<= 1600px`。
- HARはmetadata-onlyで、body/cookie/auth headerがない。
- CAPTCHA/login/403/429がclaim supportに使われていない。
- screenshotがblank/error/overlay状態ではない。
- visible textまたはDOMがclaimを支えられる。
- OCRを使う場合、field-level confidenceがある。
- no-hit画面は `no_hit_not_absence` としてだけ使う。
- accepted artifact率が閾値以上。

### 6.4 canary fail時の扱い

失敗は「無駄」ではない。`failed_source_ledger` に入り、source discoveryの学習材料になる。

例:

- terms不明なら、同じpublisherの他sourceも慎重化。
- 429が多いなら、host-level capture suppress。
- DOMが不安定なら、API/RSS/PDFへfallback探索。
- screenshotがcookie bannerで覆われるなら、manual review or metadata-only。
- OCR confidenceが低いなら、claim化せずknown gap。

---

## 7. `expand_suppress_controller`

### 7.1 目的

AWS creditを速く使うことと、価値のない取得を止めることを両立する。

controllerはsource単位、source family単位、packet gap単位で拡張/抑制を判断する。

### 7.2 control metrics

```json
{
  "schema_id": "jpcite.source_yield_metrics.v1",
  "source_profile_id": "sp_...",
  "window": "last_1h",
  "attempted_captures": 1000,
  "accepted_source_receipts": 760,
  "accepted_claim_refs": 410,
  "packet_fixture_contribution": 82,
  "known_gap_reductions": 35,
  "no_hit_checks_valid": 180,
  "manual_review_required_rate": 0.04,
  "terms_risk_rate": 0.00,
  "blocked_state_rate": 0.01,
  "cost_usd": 62.5,
  "cost_per_accepted_artifact": 0.05,
  "gap_reduction_score": 0.71,
  "artifact_value_density": 0.83,
  "recommended_action": "expand"
}
```

### 7.3 action policy

```text
expand:
  accepted artifact rate high
  gap reduction high
  terms/robots stable
  cost per accepted artifact low
  packet contribution high

hold:
  canary pass but sample too small
  freshness unknown
  conflict rate needs audit

suppress:
  accepted artifact rate low
  manual review rate high
  cost per accepted artifact high
  duplicate receipts high
  source freshness low for packet needs

block:
  terms/robots fail
  access wall/CAPTCHA/login
  private data risk
  no-hit misuse risk
  source conflict hidden
```

### 7.4 スマートなcredit消化

このcontrollerがあると、credit消化は次のように賢くなる。

- 高yield sourceには自動で投入量を増やす。
- 低yield sourceは早く止める。
- 余ったcreditは、無差別crawlではなく、QA、conflict audit、proof fixture、GEO eval、packet sample生成へ回す。
- 終盤は「残額を埋めるための重いjob」ではなく、短時間・低abort cost・高accepted artifact densityのjobに寄せる。

これは `aws_final_12_review_01_cost_autonomy.md` の `budget token market` と矛盾しない。むしろ、`artifact_value_density` の入力としてsource yield metricsを渡すべきである。

---

## 8. `packet_to_source_backcaster`

### 8.1 目的

GEO-firstのjpciteでは、AIエージェントがどのpacketを見たか、どのpreviewで有料化しなかったか、どのknown gapが購買阻害になったかが重要である。

この需要信号をsource discoveryへ戻す。

### 8.2 入力信号

- proof page view
- agent-safe OpenAPI / MCP preview call
- cost preview requested
- approval token generated
- paid packet generated
- packet abandoned because of known gap
- user task category
- agent recommendation card click
- no-hit caveat displayed
- missing jurisdiction / industry / date range
- manual review queue reason

### 8.3 backcast output

```json
{
  "schema_id": "jpcite.packet_to_source_backcast.v1",
  "signal_id": "pbs_...",
  "packet_id": "grant_candidate_shortlist",
  "observed_agent_task": "この会社が使える補助金を探して",
  "purchase_blocker": "local_grant_source_missing",
  "missing_claim_template_ids": [
    "municipal_grant_eligibility_window",
    "application_deadline",
    "eligible_business_type"
  ],
  "suggested_source_capabilities": [
    "municipal_program_index",
    "application_guideline_pdf",
    "deadline_field",
    "area_field"
  ],
  "candidate_discovery_queries": [
    "official municipal grant page",
    "subsidy application guideline PDF",
    "public program RSS or update page"
  ],
  "new_output_gap_ids": ["ogm_..."],
  "priority_reason": "high_agent_recommendation_value"
}
```

### 8.4 注意点

paid usageだけでsource探索を最適化すると、短期売上に偏りすぎる。

そのため、backcasterには2つの枠を持たせる。

- exploitation: 既に売れているpacketのgapを埋める。
- exploration: 将来売れる可能性が高いが未開拓のsource familyを試す。

explorationは無制限にしない。`accepted_artifact_target` と `canary cap` を必須にする。

---

## 9. `source_freshness_monitor`

### 9.1 目的

公的一次情報は、取れた時点では正しくても、時間が経つとstaleになる。

source freshnessは、成果物の品質とAIエージェントの信頼に直結する。

### 9.2 freshness model

source familyごとにTTLを変える。

例:

| source type | 推奨TTL | 理由 |
| --- | ---: | --- |
| 法人番号基本情報 | 7-30 days | 更新頻度があり、企業確認に使う |
| インボイス登録 | 7-30 days | status確認に使う |
| 補助金募集 | 1-7 days | 締切が購買価値に直結 |
| 調達案件 | 1-7 days | 入札期限が短い |
| 行政処分 | 7-30 days | 取引先確認に使う |
| 法令XML | 7-30 days | 改正情報が重要 |
| 官報/告示 | 1-7 days | 新規公告が価値 |
| 自治体制度ページ | 7-30 days | CMS更新・PDF差替えがある |
| 統計/地理 | 90-365 days | 更新頻度が低め |
| 標準/認証 | 30-180 days | status/規格更新確認が中心 |

### 9.3 AWS teardownとの矛盾

注意点: AWSは最後に削除する。  
したがって、AWS上のfreshness monitorをproduction runtimeにしてはいけない。

解決:

- AWS run中: large-scale freshness analysis and source TTL calibration
- export後: production assetに `staleness_ttl` と `last_observed_at` を持たせる
- AWS teardown後: stale時は「更新未確認」known gapを表示する
- 継続更新が必要なら、非AWSの軽量cronまたは手動更新runを別途設計する

つまり、freshness monitorは「常時AWSで監視する機能」ではなく、**成果物にstalenessを正しく表示するためのTTL compiler** として扱うべきである。

---

## 10. `source_terms_classifier`

### 10.1 目的

terms/robots/licenseはsource acquisitionの最大リスクである。

自動分類は必要だが、自動分類だけでpublic claim利用を許可してはいけない。

### 10.2 classifier output

```json
{
  "schema_id": "jpcite.source_terms_classification.v1",
  "source_candidate_id": "sc_...",
  "terms_url": "https://example.go.jp/terms",
  "terms_hash": "sha256:...",
  "robots_url": "https://example.go.jp/robots.txt",
  "robots_hash": "sha256:...",
  "classification": {
    "automated_access": "allowed_limited",
    "api_preferred": true,
    "bulk_download_allowed": true,
    "html_crawl_allowed": "limited",
    "playwright_allowed": "manual_review_required",
    "ocr_allowed": "derived_fact_only",
    "redistribution": "derived_fact_only",
    "screenshot_publication": "not_allowed_by_default",
    "rate_limit_policy": "unknown",
    "commercial_use": "unknown"
  },
  "confidence": 0.72,
  "decision": "manual_review_required",
  "claim_support_allowed": false,
  "allowed_capture_methods": ["api", "bulk_download"],
  "blocked_capture_methods": ["broad_playwright", "raw_screenshot_publication"],
  "known_gap_if_used": "terms_manual_review_required"
}
```

### 10.3 confidence policy

| confidence | action |
| ---: | --- |
| 0.90以上 | reviewerなしでもcanary可。ただしpublic claimはsource_profile gate後 |
| 0.70-0.89 | canaryは限定可。公開claimはmanual reviewか明確なterms receipt後 |
| 0.40-0.69 | metadata-only / link-only |
| 0.40未満 | block or manual review |

### 10.4 矛盾確認

source terms classifierは、現行のfail-closed方針と矛盾しない。

ただし、「AIでtermsを読めるからOK」としてはいけない。  
classifierは推薦器であり、許可器ではない。  
最終的なpublic useは `source_profile_gate` と `license_boundary` が決める。

---

## 11. `failed_source_ledger`

### 11.1 目的

source探索では失敗が必ず出る。

失敗を捨てると、同じsourceへ何度もアクセスし、コストとリスクが増える。

`failed_source_ledger` は失敗を学習資産にする。

### 11.2 ledger categories

- `terms_unknown`
- `robots_blocked`
- `rate_limited`
- `captcha_or_bot_challenge`
- `login_required`
- `not_official_source`
- `private_or_sensitive_risk`
- `unstable_dom`
- `blank_screenshot`
- `ocr_low_confidence`
- `no_stable_identifier`
- `no_packet_gap_link`
- `too_high_cost_per_artifact`
- `duplicate_of_existing_source`
- `manual_review_overload`

### 11.3 schema案

```json
{
  "schema_id": "jpcite.failed_source_ledger.v1",
  "failed_source_id": "fsl_...",
  "source_candidate_id": "sc_...",
  "failure_category": "captcha_or_bot_challenge",
  "failure_stage": "playwright_canary",
  "observed_at": "2026-05-15T00:00:00Z",
  "host": "example.go.jp",
  "capture_method": "playwright_visible_text",
  "http_status_class": "403_or_challenge",
  "raw_content_stored": false,
  "claim_support_allowed": false,
  "known_gap_id": "kg_...",
  "retry_policy": {
    "retry_allowed": false,
    "next_retry_after": null,
    "reason": "access_control_or_bot_challenge"
  },
  "replacement_discovery_hint": {
    "try_official_api": true,
    "try_bulk_download": true,
    "try_sitemap": true,
    "try_parent_ministry_index": true
  }
}
```

### 11.4 privacy/terms注意

failed ledgerにraw HTML、raw screenshot、HAR body、cookie、auth header、OCR全文を入れてはいけない。

保存するのはmetadata、hash、分類、known gap、retry policyだけでよい。

---

## 12. `source freshness monitor` と `failed source ledger` の組み合わせ

sourceは、一度passしても後で失敗sourceに変わる。

例:

- terms page hashが変わる。
- robots.txtが変わる。
- API仕様が変わる。
- CMSが変わりDOM抽出が壊れる。
- PDF構造が変わる。
- 429が増える。
- 公式サイトが移転する。

そのため、freshness monitorはsource contentだけでなく、取得可能性も監視対象にする。

推奨field:

```json
{
  "source_profile_id": "sp_...",
  "last_successful_capture_at": "2026-05-15T00:00:00Z",
  "last_terms_hash": "sha256:...",
  "last_robots_hash": "sha256:...",
  "last_structure_hash": "sha256:...",
  "last_capture_method": "api",
  "freshness_status": "fresh",
  "capture_health": "healthy",
  "degradation_reason": null,
  "staleness_known_gap_id": null
}
```

---

## 13. よりスマートなsource discovery algorithm

### 13.1 Overall loop

```text
packet catalog
  -> claim templates
  -> output_gap_map
  -> source candidate discovery
  -> source_candidate_registry
  -> terms classifier
  -> source_profile gate
  -> capture_method_router
  -> canary capture
  -> accepted artifact measurement
  -> expand_suppress_controller
  -> source_receipts / claim_refs / known_gaps / no_hit_checks
  -> packet fixtures / proof pages / agent recommendation cards
  -> packet_to_source_backcaster
  -> output_gap_map
```

### 13.2 Candidate score

```text
candidate_score =
  0.20 * gap_reduction_estimate
+ 0.18 * paid_packet_relevance
+ 0.15 * officialness_confidence
+ 0.12 * terms_clarity
+ 0.10 * automation_yield_estimate
+ 0.10 * freshness_value
+ 0.08 * capture_method_strength
+ 0.07 * source_identifier_stability
- 0.15 * legal_terms_risk
- 0.10 * privacy_or_sensitive_risk
- 0.08 * expected_manual_review_load
- 0.07 * expected_cost_to_accept
```

このscoreは公開しない。内部のsource discovery用である。

### 13.3 Accepted artifact density

```text
artifact_value_density =
  weighted_accepted_artifacts
  / max(cost_usd, minimum_cost_floor)

weighted_accepted_artifacts =
  1.0 * source_receipt_count
+ 1.5 * claim_ref_count
+ 1.2 * valid_no_hit_check_count
+ 2.0 * packet_fixture_contribution
+ 2.5 * gap_reduction_count
- 1.5 * manual_review_required_count
- 2.0 * conflict_unresolved_count
- 3.0 * terms_uncertain_count
```

この値を `budget token market` に渡すと、AWS creditを高価値sourceへ自動配分できる。

---

## 14. source discovery inputs

### 14.1 公式リンクグラフ

source候補は、検索エンジンよりも公式リンクグラフを優先する。

起点:

- e-Gov法令/API catalog
- 官報
- 各府省庁サイト
- 政策所管ページ
- 申請/許認可ページ
- J-Grants / 補助金
- 調達ポータル
- gBizINFO
- e-Stat
- EDINET
- 自治体標準オープンデータ
- 裁判所/審決/行政処分公表ページ
- JISC/認証/標準系公式ページ

### 14.2 sitemap/RSS/API catalog

発見方法は、本文crawlより先に以下を試す。

- `robots.txt` 参照
- sitemap
- RSS/Atom
- API catalog
- bulk download page
- official update page
- public dataset catalog
- public search endpoint documentation

### 14.3 officialness verification

source候補は、公式性を検証する。

検証材料:

- `.go.jp` / LG domain / official institution domain
- official directoryからのリンク
- agency pageからのリンク
- API catalog記載
- published terms
- publisher identity
- contact/department info
- stable dataset identifier

公式性が曖昧なsourceは、claim supportではなくnavigation/known gap候補に留める。

---

## 15. source capability model

sourceはURLではなく、capabilityとして扱う。

### 15.1 capability例

| capability | 説明 | packet例 |
| --- | --- | --- |
| `identity_lookup` | 法人番号/名称/所在地等の確認 | company baseline |
| `registration_status` | 登録/許可/取消/有効期間 | permit check |
| `public_disposition` | 行政処分/勧告/公表 | vendor risk |
| `law_text_version` | 法令条文・改正履歴 | regulation impact |
| `program_opportunity` | 補助金/助成金/制度募集 | grant shortlist |
| `deadline_window` | 申請/入札/提出期限 | grant/procurement |
| `eligibility_rule` | 対象者/要件/地域/業種 | grant/permit |
| `procurement_notice` | 入札公告/落札/仕様 | procurement radar |
| `statistics_context` | 地域/産業統計 | market/regional packet |
| `standard_or_certification_status` | 規格/認証/安全情報 | compliance packet |

### 15.2 なぜ重要か

capability modelがないと、sourceを増やしても何に使えるか分からない。

capabilityがあれば、packet composerは次のように判断できる。

- このsourceはpositive claimに使える。
- このsourceはno-hit checkにだけ使える。
- このsourceはknown gap説明に使える。
- このsourceはpublic proofではhash/citationだけ出す。
- このsourceはmetadata-onlyで、claim support不可。

---

## 16. 矛盾チェック

### 16.1 「AWS creditを速く使い切る」 vs 「高価値sourceだけ取る」

矛盾しやすい。

解決:

- source discoveryは高value densityを優先する。
- 余ったcreditは無差別source crawlではなく、QA、conflict audit、freshness simulation、GEO eval、packet/proof fixture生成へ回す。
- 終盤stretchは低abort costのjobだけにする。

したがって、「sourceを広げれば使い切れる」という考えは採用しない。  
「accepted artifactに変換できる範囲で広げ、残りは品質・評価・販売素材へ回す」が正しい。

### 16.2 「Playwrightで突破」 vs 「terms/robots/fail closed」

矛盾する表現が出やすい。

解決:

- `突破` という言葉は計画本文では避ける。
- `public rendered observation` と定義する。
- CAPTCHA/login/403/429はclaim support不可。
- screenshotは公開商品ではなく内部証跡が原則。

### 16.3 「source_freshness_monitor」 vs 「AWS teardown」

矛盾しやすい。

解決:

- AWS上のmonitorを継続runtimeにしない。
- AWS run中にTTLを学習/設定する。
- production assetには `last_observed_at` / `staleness_ttl` / `staleness_status` を持たせる。
- stale時はknown gapを表示する。
- 継続更新はAWS外の軽量更新経路として別設計にする。

### 16.4 「terms classifier」 vs 「自動で公開利用許可」

矛盾しやすい。

解決:

- classifierは推薦/分類であり、許可器ではない。
- public claimは `source_profile_gate` と `license_boundary` が許可する。
- confidence低いものは `manual_review_required`。

### 16.5 「failed source ledger」 vs 「機密/規約リスク」

矛盾しうる。

解決:

- failed ledgerにはraw page body、raw screenshot、HAR body、cookie、auth header、OCR全文を入れない。
- metadata、hash、分類、retry policyだけ保存する。

### 16.6 「packet_to_source_backcaster」 vs 「短期売上偏重」

矛盾しうる。

解決:

- exploitation枠とexploration枠を分ける。
- explorationにも `accepted_artifact_target`、canary cap、terms gateを必須にする。

### 16.7 「sourceを増やす」 vs 「AIエージェントに分かりやすい」

sourceが多いほどAIに価値が伝わるわけではない。

解決:

- publicにはsource数よりpacket/proof/known gapsを出す。
- AI agent向けには `agent_recommendation_card` で「このpacketで何が安く得られるか」を出す。
- source discoveryの複雑さは内部に閉じる。

---

## 17. 本体計画へマージすべき機能変更

### 17.1 Must add

- `output_gap_map`
- `source_candidate_registry`
- `source_terms_classifier`
- `capture_method_router`
- `Playwright canary router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`
- `source_freshness_monitor`
- `failed_source_ledger`

### 17.2 Must change

- `source_profile` は候補sourceの置き場ではなく、gate通過後のsource contractにする。
- source収集jobには必ず `linked_output_gap_ids[]` と `accepted_artifact_target[]` を持たせる。
- Playwright jobには必ず `source_profile_id`、`terms_decision_id`、`robots_decision_id`、`max_screenshot_edge_px=1600` を持たせる。
- source拡張は人間の優先順位だけでなく、accepted artifact yieldで自動制御する。
- failed sourceは再試行せず、ledgerとreplacement discoveryへ回す。

### 17.3 Must not add

- CAPTCHA solver
- proxy rotation for evasion
- login-based collection
- HAR body storage
- raw screenshot public bulk
- OCR full text public redistribution
- real user CSV-derived source discovery in AWS
- source countをKPIにすること

---

## 18. 推奨する最小実装surface

このレビューは順番ではなく機能改善が主眼だが、実装負荷を抑えるため、最小surfaceは次で足りる。

### 18.1 Local schemas

- `output_gap_map.jsonl`
- `source_candidates.jsonl`
- `capture_method_decisions.jsonl`
- `source_yield_metrics.jsonl`
- `failed_source_ledger.jsonl`
- `source_freshness_status.jsonl`

### 18.2 Validators

- source candidate must link to packet gap
- source candidate cannot become source profile without terms/robots basis
- capture method cannot choose Playwright without canary policy
- screenshot dimension must be <= 1600px
- no-hit must remain `no_hit_not_absence`
- failed ledger cannot contain raw content
- accepted artifact must link back to source candidate and output gap

### 18.3 Public/API impact

公開APIにsource discovery内部を全部出す必要はない。

出すべきもの:

- source receipts
- claim refs
- known gaps
- freshness status
- coverage gap
- no-hit caveat
- proof metadata

出さないもの:

- raw source candidate scoring
- terms classifier internal text
- failed source raw details
- raw screenshots/HAR/OCR full text
- internal budget/yield scoring

---

## 19. Smart source discoveryが増やす成果物

この機能により、単にsourceが増えるだけでなく、売れるpacketが増える。

### 19.1 取引先確認

増える成果物:

- `company_public_baseline`
- `vendor_public_attention_packet`
- `administrative_disposition_check`
- `invoice_vendor_public_check`

必要sourceをgapから発見:

- 業種別登録/許可
- 行政処分公表
- 調達/落札
- 官報公告
- gBizINFO / EDINET metadata

### 19.2 補助金/制度

増える成果物:

- `grant_candidate_shortlist`
- `application_readiness_checklist`
- `local_grant_opportunity_radar`
- `csv_overlay_grant_match`

必要sourceをgapから発見:

- J-Grants
- 自治体補助金ページ
- 募集要領PDF
- 申請期限
- 対象業種/地域/金額/必要書類

### 19.3 許認可/業法

増える成果物:

- `permit_rule_check`
- `regulated_activity_question_set`
- `license_application_pathway`
- `local_ordinance_gap_packet`

必要sourceをgapから発見:

- e-Gov法令
- 所管省庁ガイドライン
- 自治体条例/申請ページ
- 標準処理期間
- 申請様式/窓口

### 19.4 法令/制度変更

増える成果物:

- `reg_change_impact_brief`
- `compliance_update_packet`
- `industry_rule_change_watch`

必要sourceをgapから発見:

- 法令XML
- パブコメ
- 官報/告示
- 通達/ガイドライン
- 改正履歴/施行日

### 19.5 税労務

増える成果物:

- `monthly_tax_labor_event_radar`
- `csv_tax_labor_event_packet`
- `payroll_withholding_calendar_packet`
- `social_insurance_event_packet`

必要sourceをgapから発見:

- 国税庁
- eLTAX関連情報
- 日本年金機構
- 厚労省
- 最低賃金
- 労働保険/社会保険手続

---

## 20. 最終採用判断

採用すべきである。

理由:

1. GEO-firstの本質に合っている。AIエージェントが欲しい成果物からsourceを逆算できる。
2. AWS creditを高密度に使える。無差別取得ではなくaccepted artifactへ寄せられる。
3. zero-bill teardownと矛盾しない。AWSは学習/生成/検証工場であり、runtimeではない。
4. Playwright/OCRを安全に使える。公開可視状態の証跡化に限定し、canaryとterms gateで制御できる。
5. failed sourceを資産化できる。同じ失敗でcreditを溶かさない。
6. sourceの多さではなく、packet価値・known gap削減・agent推薦しやすさに直結する。

最終メッセージ:

> よりスマートなsource acquisitionとは、sourceをさらに多く列挙することではない。売れる成果物の不足claimを起点にsource候補を発見し、terms・capture method・canary・accepted artifact yieldで自動的に拡張/抑制することである。この方法なら、AWS creditを短期に使いながら、後に残る資産は「大量の未整理データ」ではなく、AIエージェントが推薦できる証跡付きpacket生成能力になる。

