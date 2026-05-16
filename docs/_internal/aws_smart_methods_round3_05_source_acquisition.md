# AWS smart methods round 3 review 05: source acquisition and public corpus

Date: 2026-05-15
Role: Round3 additional smart-method review 5/20
Topic: Source acquisition, public corpus, Source OS, capture router, Canary Economics, Source Twin Registry
AWS execution: prohibited and not executed
AWS CLI/API/resource operation: not executed
Write scope: this file only

---

## 0. Verdict

判定: **追加価値あり。現行の Source OS は正しいが、さらにスマートにするなら「sourceを増やす」ではなく「source取得を成果物価値へ変換する機能」にするべき。**

既存計画にはすでに以下がある。

- `output_gap_map`
- `source_candidate_registry`
- `capture_method_router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`
- `Source Twin Registry`
- `Canary Economics`
- `Official Evidence Knowledge Graph`
- `Bitemporal Claim Graph`
- `No-Hit Lease Ledger`
- `Policy Decision Firewall`

これらは方向として正しい。

今回さらにスマートにするために追加すべき中核は、次の 8 つである。

1. `Source Capability Contract`: source名ではなく「成果物claimを支える能力」で取得対象を定義する。
2. `Evidence Aperture Router`: sourceごとに、link-only / metadata / hash / section fact / rendered observation / OCR candidate など最小十分な取得深度を選ぶ。
3. `Public Corpus Yield Compiler`: 取得結果を、packet coverage、gap reduction、agent recommendability、reuse valueへ即時変換して評価する。
4. `Delta-First Acquisition`: 全量取得より前に、hash、ETag、更新日、index diff、semantic deltaで差分価値を測る。
5. `Municipality Archetype Engine`: 全国自治体を総当たりせず、サイト構造・制度種別・人口/産業/成果物需要で archetype 化して高価値自治体から展開する。
6. `Gazette/Event Normalizer`: 官報・告示・公告・公示を全文コーパスではなく event stream として扱う。
7. `Regulatory Source Spine`: 法令、通達、ガイドライン、パブコメ、官報、自治体例規を同じ bitemporal regulatory spine に接続する。
8. `Source Replacement Market`: 低yield / high-risk sourceを同じclaim能力を持つ代替sourceへ自動的に置換する。

最重要の設計変更はこれである。

> Source acquisition is not a crawl plan. It is a compiler from sellable output gaps to the cheapest official evidence that can safely support those gaps.

日本語で言うと、jpcite の取得基盤は「公的一次情報を広く集める基盤」ではなく、「売れる成果物で足りない根拠を、最安・安全・再利用可能な公的sourceから埋める基盤」にする。

これにより、AWS credit は URL や PDF を増やすためではなく、販売できる packet、proof page、agent decision object、known gap、no-hit lease、更新watch の密度を上げるために使える。

---

## 1. Existing plan alignment

### 1.1 What is already correct

現行計画で正しい点:

- GEO-first / AI-agent-first である。
- source family は売れる成果物に紐づける方針になっている。
- P0 は「重要source」ではなく「短期で売れる成果物に必要なsource」と定義されている。
- Playwright はアクセス制限突破ではなく public rendered observation として定義されている。
- screenshot は各辺 1600px 以下で、public proof へ raw 露出しない。
- AWS は artifact factory であり、production runtime ではない。
- raw private CSV は AWS に入れない。
- no-hit は `no_hit_not_absence` であり、不存在証明にしない。
- final state は external export 後の zero-bill teardown である。

この土台は維持する。

### 1.2 What is still slightly weak

弱いのは、source取得がまだ次のように見えやすい点である。

- source familyを増やす
- priorityを決める
- capture methodを選ぶ
- accepted artifact率で拡張/停止する

これは正しいが、まだ「取得側」の発想が強い。

さらにスマートにするには、取得対象を最初から成果物関数として扱う。

```text
end_user_task
-> paid packet
-> missing claim
-> required source capability
-> candidate source
-> minimum evidence aperture
-> canary economics
-> accepted artifact
-> packet/proof/API/MCP surface
```

この変換を Source OS の基本単位にする。

---

## 2. Smart method 1: Source Capability Contract

### 2.1 Why source family is not enough

`law_primary`、`gazette_notice`、`local_government` のような source family は必要だが、それだけでは取得判断が粗い。

同じ `local_government` でも、必要な能力はまったく違う。

- 補助金の募集要領を取れる
- 許認可の必要書類を取れる
- 条例本文へ安定リンクできる
- 入札公告の締切を取れる
- 行政処分の法人名と日付を取れる
- 標準処理期間を取れる

したがって、source候補は family ではなく capability で採点する。

### 2.2 Contract schema

```json
{
  "schema_id": "jpcite.source_capability_contract.v1",
  "capability_id": "cap_local_grant_deadline_requirements",
  "required_by": {
    "packet_ids": ["grant_candidate_shortlist_packet", "application_readiness_checklist_packet"],
    "output_gap_ids": ["ogm_..."],
    "end_user_tasks": ["使える補助金を探したい", "申請準備物を知りたい"]
  },
  "claim_capabilities": [
    "program_title",
    "publisher",
    "application_deadline",
    "target_business_type",
    "eligible_expense_category_candidate",
    "required_documents_candidate",
    "official_url",
    "last_observed_at"
  ],
  "minimum_support_state": "official_source_observed",
  "minimum_capture_depth": "metadata_plus_section_fact",
  "allowed_capture_methods": ["api", "rss", "html", "pdf_text", "playwright_observation", "ocr_candidate"],
  "blocked_capture_methods": ["login", "captcha", "stealth_proxy"],
  "no_hit_policy": "no_hit_not_absence",
  "public_visibility": {
    "raw_text": "not_required",
    "source_url": "allowed",
    "short_excerpt": "terms_dependent",
    "screenshot": "internal_receipt_only_by_default"
  },
  "business_value": {
    "packet_value_points": 18,
    "agent_recommendability": "high",
    "repeat_value": "high",
    "reuse_across_packets": ["csv_monthly_public_review_packet", "tax_labor_event_radar_packet"]
  }
}
```

### 2.3 Merge difference

正本計画へ入れる差分:

- `source_family` の必須metadataに `capability_contract_ids[]` を追加する。
- `source_candidate_registry` の scoring を `source family priority` ではなく `capability coverage` 起点にする。
- AWS job の `accepted_artifact_target` に加えて `required_capability_id` を必須にする。

矛盾:

- なし。

注意:

- 既存の `source_family` は廃止しない。family は分類、capability は取得理由である。

---

## 3. Smart method 2: Evidence Aperture Router

### 3.1 Problem

現行の `capture_method_router` は API/bulk/HTML/PDF/Playwright/OCR を選ぶが、さらに重要なのは「どこまで深く取るか」である。

すべてのsourceで本文、PDF、スクリーンショット、OCRまで取ると高コスト・高リスクになる。

逆に link-only で足りるsourceに重い処理を投下すると、AWS credit が成果物価値ではなく画像やログに変わってしまう。

### 3.2 Aperture levels

`Evidence Aperture Router` は、sourceごとに最小十分な取得深度を選ぶ。

| Aperture | 内容 | 使う場面 | 公開可否 |
|---|---|---|---|
| `link_only` | official URL, title, publisher | terms不明、紹介のみ | 限定可 |
| `metadata_only` | title, date, category, hash, deep link | 官報/公告/自治体PDF index | 可 |
| `index_fact` | 一覧ページ上の行情報 | 登録一覧、処分一覧、入札一覧 | 条件付き可 |
| `section_fact` | PDF/HTMLの特定節から抽出 | 補助金要件、申請書類、締切 | 可 |
| `structured_api_fact` | API/CSV/XMLの正規化fact | 法人番号、法令XML、統計 | 可 |
| `rendered_observation` | Playwright DOM/screenshot receipt | JS検索結果、動的一覧 | 内部receipt中心 |
| `ocr_candidate` | 画像PDF/OCR候補 | 古い自治体PDF、表画像 | human_reviewまたは低confidence gap |
| `manual_review_required` | 自動claim化不可 | terms/品質/PII懸念 | 不可 |

### 3.3 Router decision

```json
{
  "schema_id": "jpcite.evidence_aperture_decision.v1",
  "source_candidate_id": "sc_...",
  "capability_id": "cap_permit_required_documents",
  "chosen_aperture": "section_fact",
  "chosen_capture_method": "pdf_text",
  "why_not_deeper": [
    "raw_full_text_not_needed_for_packet",
    "screenshot_not_needed_because_text_layer_available"
  ],
  "why_not_shallower": [
    "metadata_only_cannot_support_required_document_claim"
  ],
  "expected_cost_usd": 0.04,
  "expected_artifact_value_points": 12,
  "requires_policy_review": false
}
```

### 3.4 Merge difference

正本計画へ入れる差分:

- `capture_method_router` を `capture_method + evidence_aperture` の二段判定へ拡張する。
- Playwright/OCR は method ではなく high aperture cost として扱う。
- `source_profile.allowed_capture_methods[]` に加えて `allowed_apertures[]` を持たせる。

矛盾:

- なし。

注意:

- screenshot lane は維持するが、スクリーンショット量産を成果物価値と誤認しない。

---

## 4. Smart method 3: Public Corpus Yield Compiler

### 4.1 Purpose

`Canary Economics` は accepted artifact per dollar を見る。これは正しい。

ただし accepted artifact だけだと、成果物価値への変換が少し弱い。

追加すべきは `Public Corpus Yield Compiler` である。

これは source canary の結果を次のような product metric へコンパイルする。

- どの packet の coverage が増えたか
- どの known gap が消えたか
- agent が推薦しやすくなったか
- free preview の説得力が増えたか
- no-hit lease が改善したか
- proof page に載せられる証跡が増えたか
- 何回再利用できる source_receipt か

### 4.2 Yield object

```json
{
  "schema_id": "jpcite.public_corpus_yield.v1",
  "source_candidate_id": "sc_...",
  "source_profile_id": "sp_...",
  "canary_run_id": "canary_...",
  "cost_usd": 4.18,
  "accepted_artifacts": {
    "source_receipts": 128,
    "claim_refs": 311,
    "known_gaps_reduced": 27,
    "no_hit_leases_created": 43
  },
  "packet_impact": [
    {
      "packet_id": "grant_candidate_shortlist_packet",
      "coverage_before": 0.42,
      "coverage_after": 0.58,
      "agent_recommendability_delta": "medium_to_high",
      "paid_preview_quality_delta": 0.16
    }
  ],
  "reuse_value": {
    "reusable_across_packets": 4,
    "expected_refresh_frequency": "weekly",
    "receipt_reuse_score": 0.71
  },
  "decision": "expand",
  "decision_reason": [
    "cost_per_gap_reduction_below_threshold",
    "high_packet_reuse",
    "terms_passed",
    "manual_review_load_acceptable"
  ]
}
```

### 4.3 Merge difference

正本計画へ入れる差分:

- `artifact_yield_meter` を `Public Corpus Yield Compiler` に拡張する。
- scale判断は `accepted_artifact_count` だけでなく `packet_impact` を必須にする。
- `AWS Artifact Factory Kernel` の scheduler は `artifact_value_density` に `packet_impact` を含める。

矛盾:

- なし。

注意:

- revenueだけでsourceを選ばない。`Policy Decision Firewall` と `known_gaps` が上位gateである。

---

## 5. Smart method 4: Delta-First Acquisition

### 5.1 Why

公的一次情報は広い。毎回全量取得するとコストも時間も大きい。

しかし jpcite の成果物価値は、多くの場合「何が変わったか」にある。

- 法令改正
- 公募開始/締切変更
- 申請要件変更
- 登録/許認可の更新
- 行政処分の追加
- 入札公告の追加
- 官報イベントの追加
- 自治体ページの更新

したがって、AWS credit run でも future runtime でも、差分を先に見る。

### 5.2 Delta layers

| Layer | 方法 | 用途 | Cost |
|---|---|---|---|
| `endpoint_liveness` | HEAD/GET minimal, status, content length | source alive | very low |
| `declared_update` | updated_at, last-modified, RSS date | quick freshness | low |
| `index_hash` | 一覧ページ/CSV/XML index hash | add/remove detection | low |
| `schema_hash` | columns/XML structure/selector hash | breakage detection | low |
| `section_hash` | article/section/table hash | meaningful delta | medium |
| `semantic_delta` | normalized claim diff | packet impact | medium |
| `rendered_delta` | DOM/screenshot diff | JS pages | high |
| `ocr_delta` | OCR text/span diff | image/PDF only | high |

### 5.3 Rule

高いdelta layerへ進む条件:

```text
lower_layer_delta_detected
OR source_twin predicts high value
OR output_gap_map marks freshness critical
OR no_hit_lease expired for paid packet
OR release capsule needs exact refresh
```

### 5.4 Merge difference

正本計画へ入れる差分:

- source acquisition jobs は `full_fetch` から始めず、`delta_probe` を先行させる。
- `Source Twin Registry` に `last_delta_layer_success`, `delta_cost_curve`, `semantic_delta_yield` を追加する。
- `No-Hit Lease Ledger` の expiry は delta scheduler に接続する。

矛盾:

- なし。

注意:

- 初回だけは baseline snapshot が必要なsourceもある。初回baselineと更新deltaを混ぜない。

---

## 6. Smart method 5: Municipality Archetype Engine

### 6.1 Problem

自治体sourceは商用価値が高いが、最も危険な広がり方をする。

危険:

- 全国自治体サイトを総当たりする
- PDFやページ構造が自治体ごとに違う
- robots/termsが揺れる
- 補助金、条例、入札、許認可、処分が同一サイト内に混在する
- personal / small business / local names が混じりやすい
- accepted artifact率が低いままAWS creditを消費しやすい

### 6.2 Smarter approach

自治体を URL 単位で総当たりせず、`Municipality Archetype Engine` で分類する。

分類軸:

- 都道府県 / 政令市 / 中核市 / 市区町村
- 産業構造
- 人口規模
- 補助金・入札・許認可・条例の公開形式
- 例規集の提供形態
- RSS/sitemap有無
- PDF中心 / HTML中心 / CMS中心
- search form あり/なし
- previous canary yield
- packet demand signal

### 6.3 Archetype examples

| Archetype | Capture strategy | Good outputs |
|---|---|---|
| `prefecture_program_portal` | HTML/RSS/API/index hash | grants, permits, public notices |
| `ordinance_vendor_portal` | link-only / metadata / law ref | permit checklist, regulation change |
| `pdf_notice_municipality` | PDF index + section hash, limited OCR | local grants, bidding |
| `search_form_registry` | Playwright canary only | permits, license, processing forms |
| `procurement_cms` | date/category/index fact | procurement radar |
| `low_yield_static_site` | metadata only or suppress | known gap only |

### 6.4 Selection policy

P0-B自治体は以下の条件を満たすものだけ。

1. 対応する paid packet がある。
2. `source_capability_contract` がある。
3. canaryで accepted artifact が出る。
4. terms/robots が pass または limited_pass。
5. PII/public proof minimizer が通る。
6. source twin が更新/構造を学習できる。

### 6.5 Merge difference

正本計画へ入れる差分:

- `local_government_selected` の取得前に `municipality_archetype` を必須にする。
- 全国crawlは禁止。archetype別の canary -> expand/suppress にする。
- 自治体sourceは `packet_to_source_backcaster` の結果で昇格する。

矛盾:

- 「公的情報を広く取る」と「自治体を抑制する」が一見衝突する。
- 解決: 広さは archetype coverage と capability coverage で測る。URL件数で測らない。

---

## 7. Smart method 6: Gazette/Event Normalizer

### 7.1 Problem

官報・告示・公告・公示は価値が高いが、全文コーパス化はリスクが高い。

リスク:

- 個人名やセンシティブな公告が混ざる。
- full-text redistribution の境界が難しい。
- 取得量が大きい。
- すぐ売れる成果物に効く部分と効かない部分が混在する。

### 7.2 Smarter approach

官報/告示/公告は、まず `event stream` として扱う。

取得する最小単位:

- issue date
- issue number
- category
- title
- publisher / ministry / local body
- page locator
- official URL
- content hash / PDF hash
- event type candidate
- entity mention candidate, if safe
- law / regulation / procurement / corporate / notice linkage candidate

公開するのは原則:

- metadata
- deep link
- hash
- derived event label
- short fact where terms and privacy allow

公開しない:

- raw full text by default
- raw screenshot by default
- personal notice body
- broad name search results without context

### 7.3 Event types

```text
law_promulgation
regulation_notice
public_notice
procurement_notice
company_notice_candidate
administrative_notice
public_comment_related_notice
permit_related_notice
unknown_notice_metadata_only
```

### 7.4 Merge difference

正本計画へ入れる差分:

- `gazette_notice` family を `Gazette/Event Normalizer` 経由にする。
- P0-B は metadata/event/hash/deep link まで。full text は P1/P2 review。
- 官報由来claimは `event_candidate` から始め、強いclaimへ昇格するには別sourceまたは明確anchorを要求する。

矛盾:

- なし。

注意:

- 官報を「信用リスク」「破産有無」「法的状態」の断定に直結させない。

---

## 8. Smart method 7: Regulatory Source Spine

### 8.1 Why

法律、政省令、告示、通達、ガイドライン、Q&A、パブコメ、官報、自治体例規は、それぞれ別sourceだが、成果物では同じ問いに出てくる。

例:

「この事業に必要な許認可は何か」

には、少なくとも次が関係する。

- 法律/施行令/施行規則
- 所管省庁の通達/ガイドライン
- 申請手続/様式/標準処理期間
- 自治体条例/要綱
- 改正予定/パブコメ
- 官報/告示

これをsource別にバラバラに取ると、packetが使いづらい。

### 8.2 Spine model

`Regulatory Source Spine` は次を接続する。

```text
regulated_activity
-> jurisdiction
-> law_article
-> delegated_regulation
-> notice_guideline
-> procedure_form
-> local_ordinance
-> public_comment
-> gazette_event
-> valid_time
-> source_receipts
```

### 8.3 Required objects

```json
{
  "schema_id": "jpcite.regulatory_source_spine.v1",
  "regulated_activity_id": "activity_food_business_opening",
  "jurisdiction": {
    "country": "JP",
    "prefecture": "Tokyo",
    "municipality": "example"
  },
  "source_links": [
    {
      "source_family": "law_primary",
      "claim_ref_id": "claim_..."
    },
    {
      "source_family": "procedure_permit_selected",
      "claim_ref_id": "claim_..."
    },
    {
      "source_family": "local_government_selected",
      "claim_ref_id": "claim_..."
    }
  ],
  "coverage_state": "partial",
  "known_gaps": [
    "local_form_not_confirmed",
    "standard_processing_period_missing"
  ],
  "external_wording": "needs_review"
}
```

### 8.4 Merge difference

正本計画へ入れる差分:

- `permit_scope_checklist_packet`、`regulation_change_impact_packet`、`application_readiness_checklist_packet` は `Regulatory Source Spine` を経由して作る。
- 法令source、通達source、自治体source、官報sourceの claim を同じ packet で表示する際は bitemporal validity を必須にする。

矛盾:

- なし。

注意:

- spine は法的判断エンジンではない。確認候補と根拠接続である。

---

## 9. Smart method 8: Source Replacement Market

### 9.1 Problem

あるsourceが取れない、規約が不明、yieldが低い、OCRが弱い、Playwrightが高い、ということは頻繁に起きる。

現行計画では suppress はあるが、代替source探索をもう少し明示した方がよい。

### 9.2 Method

`Source Replacement Market` は同じ capability を満たす代替sourceを探す。

```text
source suppressed
-> capability still required
-> candidate registry searches replacement
-> official link graph / publisher hierarchy / API catalog / sitemap / related agency
-> canary economics
-> replace or mark durable gap
```

### 9.3 Replacement reasons

| Reason | Action |
|---|---|
| `blocked_terms` | link-onlyに落とすか別sourceへ |
| `high_cost_low_yield` | apertureを下げるか代替sourceへ |
| `schema_drift_unstable` | Source Twinで隔離し、stable indexを探す |
| `playwright_only_expensive` | RSS/sitemap/PDF indexを探す |
| `ocr_low_confidence` | text-layer PDF/HTML sourceを探す |
| `manual_review_overload` | metadata-onlyに落とす |
| `private_or_pii_heavy` | public proof minimizerで遮断し代替sourceへ |

### 9.4 Merge difference

正本計画へ入れる差分:

- `failed_source_ledger` に `replacement_capability_search_required` を追加する。
- `expand_suppress_controller` は suppress だけでなく replacement request を発行する。
- sourceが取れないこと自体を `known_gap` として成果物化し、同時に代替探索へ回す。

矛盾:

- なし。

---

## 10. Source-family specific smart handling

### 10.1 Laws / e-Gov / primary law

Smart handling:

- XML/API/bulk が取れる場合、Playwrightを使わない。
- law ID、article path、version、promulgation/effective time を anchor 化する。
- article anchor drift を `Schema Evolution Firewall` で検出する。
- `Bitemporal Claim Graph` で observed_time と valid_time を分ける。

Output conversion:

- `regulation_change_impact_packet`
- `permit_scope_checklist_packet`
- `legal_basis_evidence_pack`
- `application_readiness_checklist_packet`

Merge note:

- `law_primary` は P0-A のまま。
- 通達/ガイドライン/パブコメは `Regulatory Source Spine` 経由で接続する。

### 10.2 Gazette / notices / public announcements

Smart handling:

- full-text corpus ではなく event stream。
- metadata、deep link、page locator、hash、event type candidateを優先。
- personal-heavy notice は public proof から除外。
- 法令・調達・法人・制度と接続できるものだけ P0-B。

Output conversion:

- `gazette_event_ledger`
- `regulation_change_watch`
- `procurement_notice_context`
- `company_public_event_candidate`

Merge note:

- P0-B は `metadata/event/hash/deep_link` まで。
- full text は P1/P2 and review-required。

### 10.3 Ministries / guidelines / circulars / Q&A

Smart handling:

- law articleへの接続可能性で価値判定する。
- broad PDF collection を避ける。
- document number, issue date, ministry, related law, section hash を重視する。
- semantic delta を action candidate に変換する。

Output conversion:

- `implementation_guidance_pack`
- `regulation_change_impact_packet`
- `permit_scope_checklist_packet`

Merge note:

- `policy_process_practical` として P0-B selected。
- whitepaper / council material は P1 unless packet-linked。

### 10.4 Industry permits / business registries

Smart handling:

- sector x activity x jurisdiction x entity identifier で capability を定義する。
- exact ID / license number を優先し、name-only join は candidate に留める。
- Playwright search result は screenshot receipt だけで断定しない。
- no-hit lease は source scope と query parameters を必須にする。

Output conversion:

- `permit_scope_checklist_packet`
- `counterparty_public_dd_packet`
- `administrative_disposition_radar_packet`
- `sector_license_radar`

Merge note:

- P0-B sector は建設、不動産、運輸、人材、産廃、金融、食品など selected。
- 「許可不要」「登録なし」断定は禁止。

### 10.5 Local government

Smart handling:

- `Municipality Archetype Engine` を必須にする。
- top allowlist から始めるが、allowlist理由は packet demand / capability gap / canary yield で保存する。
- 補助金、許認可、入札、条例、行政処分を同じ crawl として扱わない。
- CMS別 template を Source Twin に保存する。

Output conversion:

- `local_grant_candidate_packet`
- `permit_local_procedure_pack`
- `procurement_opportunity_radar_packet`
- `local_regulation_digest`

Merge note:

- 全国 all-page crawl は禁止。
- 広さは自治体数ではなく capability coverage で測る。

### 10.6 Standards / certifications

Smart handling:

- exact identifier first: standard number, certification number, product/model number.
- broad search は候補止まり。
- public proof では compliance guarantee を出さない。
- status, scope, issuer, valid time を分ける。

Output conversion:

- `standards_certification_check_packet`
- `product_public_safety_context_packet`
- `procurement_requirement_match_packet`

Merge note:

- P0-B は exact-ID / recall / public status のみ。
- broad standards corpus は P1。

### 10.7 Statistics / geospatial

Smart handling:

- huge lake を作らず、cohort lens と location context に限定する。
- geography は address normalization / municipality mapping / hazard or zoning where packet-linked。
- statistical claim は company-specific claim と混ぜない。

Output conversion:

- `regional_market_context_packet`
- `grant_context_packet`
- `site_due_diligence_context_packet`
- `industry_cohort_packet`

Merge note:

- P0-A は basic codes and mapping。
- PLATEAU / full geospatial expansion は P1。

### 10.8 Procurement / public finance

Smart handling:

- notice、award、qualification、nomination stop、budget origin を別capabilityにする。
- bid eligibility / win probability は出さない。
- date, agency, category, official link, deadline, award entity を typed claim 化する。

Output conversion:

- `procurement_opportunity_radar_packet`
- `award_competitor_ledger`
- `vendor_public_activity_packet`
- `public_funding_flow_context`

Merge note:

- P0-B selected。
- local procurement は Municipality Archetype Engine 経由。

---

## 11. Product-value conversion map

以下は、source取得を「成果物価値」に変換するための対応表である。

| Source capability | Packet impact | Agent-facing value |
|---|---|---|
| official entity identity | `company_public_baseline` | この会社かどうかを安く確認できる |
| invoice/tax registration observation | `invoice_vendor_public_check` | 請求・取引先確認の入口になる |
| administrative disposition event | `counterparty_public_dd_packet` | 追加確認が必要な公的シグナルを示せる |
| grant deadline and requirements | `grant_candidate_shortlist_packet` | AIが候補制度を安く絞れる |
| required documents / application forms | `application_readiness_checklist_packet` | 検索ではなく準備リストに変換できる |
| law article and effective time | `regulation_change_impact_packet` | 変更影響を証跡付きで説明できる |
| permit procedure and local office | `permit_scope_checklist_packet` | 行政書士/専門家相談前の質問表になる |
| local procurement notice | `procurement_opportunity_radar_packet` | 営業機会として推薦しやすい |
| standard/certification exact status | `standards_certification_check_packet` | 調達・製品確認で使いやすい |
| tax/labor deadline source | `tax_labor_event_radar_packet` | 毎月使う成果物にできる |
| geospatial/statistical cohort | `regional_context_packet` | 補助金・出店・市場文脈を安く補強できる |

重要:

- sourceの価値は `packet_count` ではなく、agent が「買う理由」を説明できるかで測る。
- `agent_recommendation_card` に使えないsourceは、P0では価値が低い。

---

## 12. AWS execution merge plan

この文書はAWSコマンドを実行しない。ここでは正本計画にマージすべき計画差分だけを書く。

### 12.1 New control objects

正本計画へ追加する object:

```text
source_capability_contract
evidence_aperture_decision
public_corpus_yield
municipality_archetype
gazette_event
regulatory_source_spine
source_replacement_request
```

### 12.2 New gates

追加する gates:

| Gate | Purpose | Blocks |
|---|---|---|
| `capability_contract_gate` | source candidateに成果物理由があるか | no packet gap linked |
| `aperture_minimality_gate` | 必要以上に深く取っていないか | wasteful screenshot/OCR/full text |
| `canary_product_yield_gate` | canaryがpacket価値へ変換されたか | low product impact |
| `municipality_archetype_gate` | 自治体を総当たりしていないか | broad local crawl |
| `gazette_event_safety_gate` | 官報/公告を危険に全文化していないか | raw full text, personal-heavy public proof |
| `regulatory_spine_temporality_gate` | observed/valid timeが分かれているか | legal/regulatory time confusion |
| `source_replacement_gate` | suppress後に代替探索またはdurable gap化したか | repeated failed retries |

### 12.3 New job lane names

既存 J01-J52 を壊さず、内部laneとして追加する。

| Lane | Purpose |
|---|---|
| `SC-01 capability_contract_build` | paid packet gapsからsource capabilityを定義 |
| `SC-02 candidate_discovery` | official link graph / sitemap / API catalog / packet backcastから候補発見 |
| `SC-03 aperture_routing_canary` | 最小取得深度を選びcanary実行 |
| `SC-04 source_twin_update` | sourceごとの構造/更新/失敗/費用/品質を学習 |
| `SC-05 public_corpus_yield_compile` | canary結果をpacket価値へ変換 |
| `SC-06 delta_frontier_plan` | 差分取得 frontier を作る |
| `SC-07 municipality_archetype_expand` | selected自治体を archetype ごとに拡張/抑制 |
| `SC-08 gazette_event_normalize` | 官報/告示/公告をevent化 |
| `SC-09 regulatory_spine_link` | 法令/通達/自治体/官報/パブコメを接続 |
| `SC-10 replacement_market` | suppressed sourceの代替探索 |

### 12.4 Scheduler impact

`AWS Artifact Factory Kernel` の job scoring に追加する。

```text
job_value =
  artifact_value_density
  + packet_impact_score
  + gap_reduction_score
  + receipt_reuse_score
  + agent_recommendability_delta
  - policy_risk_penalty
  - manual_review_load_penalty
  - high_aperture_cost_penalty
```

この式は外部表示しない。内部schedulerの近似式である。

---

## 13. Contradiction check

### 13.1 "広く集める" vs "成果物から逆算する"

潜在矛盾:

- AWS creditを使い切るために広く取りたい。
- しかし成果物価値が低いsourceは取りたくない。

解決:

- 広さは URL数やPDF数ではなく `capability coverage` と `packet gap reduction` で測る。
- P1/P2探索はしてよいが、P0本番投入は capability contract を通ったものだけ。

判定: 解決済み。

### 13.2 Playwright/screenshot "突破" vs terms/safety

潜在矛盾:

- fetch困難ページをPlaywrightで観測したい。
- しかしアクセス制限回避は禁止。

解決:

- `rendered_observation` は公開ページの通常表示を記録するだけ。
- CAPTCHA/login/403/429/robots blocked は claim support 不可。
- screenshot は internal receipt default。public proof には minimizer 経由。

判定: 解決済み。

### 13.3 官報/公告 full corpus vs privacy/redistribution

潜在矛盾:

- 官報は重要な一次情報。
- full text化は privacy/redistribution risk がある。

解決:

- P0-B は event metadata/hash/deep link。
- raw full text は P1/P2 review。
- personal-heavy event は public proof不可または metadata/link only。

判定: 解決済み。

### 13.4 自治体全国coverage vs cost/yield

潜在矛盾:

- ローカル制度を広く取りたい。
- 全国総当たりは低yieldになりやすい。

解決:

- `Municipality Archetype Engine` で archetype coverage を先に作る。
- allowlist + canary + expand/suppress。
- 失敗は durable known gap と replacement request にする。

判定: 解決済み。

### 13.5 Source Twin learning vs zero-bill teardown

潜在矛盾:

- Source Twin を学習する。
- AWSは最後に全部消す。

解決:

- Source Twin Registry は Rolling External Exit Bundle に含めてAWS外へexportする。
- productionはAWSを参照しない。
- S3/ECR/Batch/CloudWatch等は削除する。

判定: 解決済み。

### 13.6 Delta-first vs first baseline

潜在矛盾:

- delta-first acquisitionを採用する。
- 初回は baseline がない。

解決:

- 初回は `baseline_snapshot` として最小十分 aperture で作る。
- 2回目以降は delta-first。
- source twin に baseline availability を保存する。

判定: 解決済み。

### 13.7 Product value optimization vs anti-upsell

潜在矛盾:

- packet価値や売上を最大化したい。
- 高いpacketへ誘導しすぎると信頼を失う。

解決:

- `coverage_ladder_quote` と `cheapest_sufficient_option` を使う。
- source acquisitionの価値指標にも `anti_upsell_gate` を入れる。
- 高価なsourceは「追加coverageが本当に増える場合」だけ。

判定: 解決済み。

---

## 14. Concrete master-plan patch text

正本計画へ反映するなら、以下の文言を追加する。

```text
Source acquisition must be controlled by Source Capability Contracts.
A source is not scaled because it belongs to an important family.
It is scaled only when it can satisfy a missing capability for a sellable packet,
passes policy and terms gates, and produces accepted artifacts at a measured product yield.

The capture router must choose both method and evidence aperture.
API/bulk/HTML/PDF/Playwright/OCR are methods; link-only, metadata-only,
section fact, rendered observation, and OCR candidate are aperture levels.
The system must choose the shallowest aperture sufficient for the packet claim.

Local government acquisition must use municipality archetypes and canary economics.
Nationwide all-page crawling is not allowed.

Gazette and public notice acquisition must normalize into event metadata first.
Full-text corpus expansion is P1/P2 review, not P0.

Regulatory outputs must compile through a Regulatory Source Spine that separates
observed time and valid time across laws, notices, guidelines, procedures,
public comments, and local ordinances.

Suppressed sources must create either a source replacement request or a durable known gap.
Repeated failed retries are not allowed.
```

---

## 15. Final recommendation

Round3 5/20 の結論:

現行計画は成立している。さらにスマートにするなら、source acquisition を次の形に寄せるべきである。

```text
Source Capability Contract
-> Evidence Aperture Router
-> Canary Economics
-> Public Corpus Yield Compiler
-> Source Twin Registry
-> Delta Frontier Planner
-> Source Replacement Market
-> Official Evidence Knowledge Graph
-> Public Packet Compiler
```

これにより、次が実現できる。

- AWS creditを速く使いながら、無駄な全量crawlを避ける。
- 公的一次情報の範囲を広げつつ、成果物価値に変換できるsourceだけを伸ばせる。
- 自治体、官報、法令、業法、標準、統計を同じ取得思想で扱える。
- Playwright/OCRを「突破」ではなく「高コストな観測手段」として制御できる。
- 取得失敗や規約不明も、known gap / replacement request として価値化できる。
- 本番には、sourceそのものではなく、検証済みのreceipt、claim、gap、packet assetだけを渡せる。

最終判定:

**PASS with recommended merge.**

この差分は既存の正本計画と矛盾しない。むしろ `Source OS`、`Canary Economics`、`Official Evidence Knowledge Graph`、`Release Capsule` を実装可能な粒度へ落とす補強である。
