# AWS final 12 review 03: Japanese public-primary-source scope and priority

Date: 2026-05-15
Role: final additional verification 3/12, source scope and priority
AWS execution: none
Write target: this file only

## 0. Verdict

結論: 現在の情報範囲は、jpciteのコンセプトである「日本の公的一次情報をもとに、AIエージェントがエンドユーザーへ安く成果物を返す」には十分広い。

ただし、よりスマートにする余地はまだある。ここでいう「スマート」は、単なる実行順の最適化ではない。より重要なのは、以下のような情報取得方法・source選別機能・自動拡張/抑制・成果物逆算source discoveryを本体機能として持つことである。

1. 成果物ごとの `output_gap_map` から、必要sourceを逆算して発見する。
2. source候補を `source_profile` に入れる前に、収益貢献・権利境界・receipt化可能性・cost/yieldで自動採点する。
3. AWS収集中も、accepted artifact率、packet fixture貢献、terms risk、manual review負荷を見て、自動で拡張/抑制する。
4. Playwright/OCRを「広く取りに行く道具」ではなく、「API/HTMLで取れないが成果物gapを埋めるsourceだけに使う観測手段」にする。
5. P0/P1/P2は固定ラベルではなく、成果物需要・品質・risk・costの実測で動的に昇格/降格できるsource operating systemにする。

その上で、優先順位としてはP0をさらに厳密に「売れる成果物に直結し、source_profile gateを通り、短期でaccepted artifactにできるsource」に限定する。

計画全体の方向性は正しい。最終改善は、source lake志向へ戻るリスクを潰し、output-first / GEO-first / production-firstに揃えることである。

## 1. Scope adequacy check

ユーザーが求めている範囲は、少なくとも次を含む。

- 法律
- 制度
- 業法
- 許認可
- 官報
- 告示
- 通達
- 自治体
- 裁判
- 審決
- 統計
- 地理
- 標準
- 認証
- 税労務
- 行政処分
- 調達

既存計画はこの範囲をほぼカバーしている。狭すぎる重大欠落はない。

ただし、以下は名前として明示した方がよい。

| Under-emphasized source | Why it matters | Recommended priority |
| --- | --- | --- |
| `local_reiki_ordinance` | 自治体の条例・規則・要綱は許認可・補助金・営業規制の根拠になる | P1, P0-B selected for permit/grant packets |
| `standard_processing_period_forms` | 許認可packetは必要書類・標準処理期間・窓口があると実務価値が上がる | P0-B selected |
| `suspension_nomination_stop` | 指名停止、入札参加停止、資格停止はvendor/procurement DDで強い | P0-B |
| `public_warning_alert` | 消費者庁、金融庁、PPC、MHLW等の注意喚起は取引先確認に効く | P0-B with strict caveats |
| `recall_product_accident` | 標準・認証・製品安全packetの価値を上げる | P1, P0-B only for exact product/company checks |
| `tax_labor_calendar` | CSV月次レビュー、税理士/社労士向け反復利用に必要 | P0-B |

この追加は「範囲を無制限に広げる」ためではなく、売れる成果物と結びつくsource family名を明示するためである。

## 2. Main risk: P0 is still slightly too broad

現行SOTでは、P0-A / P0-B / P1 / P2の思想はかなり整理されている。

それでも実行時に起きやすい矛盾は次である。

| Risk | Why it matters | Fix |
| --- | --- | --- |
| 官報をP0扱いで広く取りすぎる | full-text / personal notice / redistribution riskがあり、すぐ売れるpacketに直結しない部分が多い | P0-Bはmetadata/deep link/hash/eventだけ。full historical/full textはP1/P2 |
| 自治体を全国crawlし始める | creditを食うがaccepted artifact率が低い | P0-Bは上位自治体allowlist + 補助金/許認可/入札/処分/条例リンクに限定 |
| 裁判・審決をRC1に混ぜる | 法的結論と誤解されやすく、本番化を遅らせる | P1。RC1 blockerにしない |
| 統計・地理を広域lake化する | 大量取得しやすいが初期課金理由が薄い | P0-Aは住所/自治体/業種/基礎統計だけ。site DD等はP1 |
| 標準・認証を広く取りすぎる | terms/search UI/安全保証誤解が強い | exact-ID public lookup / recall / public statusだけP0-B conditional |
| 政策資料・白書・審議会を集めすぎる | 興味深いがpaid output化しにくい | P1/P2。具体packetに紐づくもののみ |

最終ルール:

> P0は「重要な公的情報」ではなく、「短期で売れるpacketに必要な、検証可能で権利境界が明確な公的一次情報」である。

## 3. Final priority model

### 3.1 P0-A: backbone source

P0-Aは、ほぼすべてのpacketの土台になるsourceだけにする。

| Source family | P0-A scope | Enabled outputs | Notes |
| --- | --- | --- | --- |
| `source_profile_terms` | publisher, official domain, terms, robots, license, capture policy, TTL | all | これなしにscaleしない |
| `identity_tax` | 法人番号、インボイス | company baseline, invoice check, vendor DD | exact IDなので最優先 |
| `law_primary` | e-Gov law XML/API, law IDs, article anchors | permit, reg-change, legal-basis packet | commentaryではなく一次法令 |
| `statistics_cohort_basic` | e-Stat core, municipality/industry codes, minimal regional context | grants, market/site context | broad tablesはP1 |
| `geo_address_basic` | address normalization, municipality mapping, basic local linkage | local grants, permits, procurement | hazard/land/PLATEAUはP1 |

P0-Aに入れてはいけないもの:

- 広域whitepaper
- full court corpus
- full gazette text
- all municipality pages
- full XBRL
- standards catalog全量
- private CSV

### 3.2 P0-B: revenue-direct selected source

P0-Bは、直接有料packetを支えるsourceに限定する。

| Source family | P0-B subset | Primary paid outputs | Boundary |
| --- | --- | --- | --- |
| `corporate_activity` | gBizINFO public activity, core public business facts | `company_public_baseline`, `counterparty_public_dd_packet` | unsupported business quality judgementは禁止 |
| `filing_disclosure_subset` | EDINET metadata, issuer/company trail, key document links | vendor DD, auditor evidence binder | XBRL-heavy analysisはP1 |
| `subsidy_program` | J-Grants, MHLW grants, SME/local grants, official requirements | `grant_candidate_shortlist_packet`, `application_readiness_checklist_packet` | eligibility確定表現は禁止 |
| `procedure_permit_selected` | construction, real estate, transport, staffing, waste, finance, food selected | `permit_scope_checklist_packet` | 許可不要/適法断定は禁止 |
| `enforcement_disposition_selected` | FSA, MLIT, MHLW, JFTC, CAA, PPC, selected local dispositions | `administrative_disposition_radar_packet`, vendor DD | no-hit is not absence |
| `procurement_contract_selected` | p-portal, JETRO, central bids, award data, top local bids, nomination stop | `procurement_opportunity_radar_packet`, vendor/procurement DD | 入札可能/落札可能断定は禁止 |
| `gazette_notice_metadata` | issue, date, title, category, page/deep link/hash/event metadata | reg-change, company/gazette event ledger | raw full-text redistributionは避ける |
| `policy_process_practical` | public comments, circulars, guidelines, Q&A tied to law/permit/program packets | `regulation_change_impact_packet`, permit/grant packets | broad councilsはP1 |
| `tax_labor_social` | NTA/eLTAX references, pension, MHLW, labor insurance, minimum wage, deadlines | `tax_labor_event_radar_packet`, CSV monthly review | final tax/labor adviceは禁止 |
| `local_government_selected` | top allowlist: subsidies, permits, bids, dispositions, reiki links, forms | grants, permits, procurement, local DD | nationwide all-page crawlはP1/P2 |
| `standards_certification_exact` | exact public status, recall/product accident, MIC/PSE/NITE/PMDA selected | `standards_certification_check_packet` | compliance/safety guaranteeは禁止 |

P0-B採用条件:

1. `primary_paid_output_ids[]` が空でない。
2. `source_profile` が pass または limited_pass。
3. `accepted_artifact_target` が決まっている。
4. capture methodが許可されている。
5. no-hit文言がsource別に定義されている。
6. public proofに出せる範囲が定義されている。

### 3.3 P1: broad expansion source

P1はAWS creditがある今やる価値はあるが、RC1や初期売上を止めてはいけない。

| Source family | P1 scope | Why useful | Condition |
| --- | --- | --- | --- |
| `local_government_expansion` | broader ordinances, procedures, procurement, permits, local notices | local packet coverage expansion | top allowlistでyield確認後 |
| `court_dispute_decision` | courts, JFTC decisions, tax appeals, labor decisions, admin appeals metadata | context and evidence binder | legal conclusion禁止 |
| `geo_land_real_estate` | GSI, NLNI, hazard, land price, urban planning, PLATEAU | site DD, regional diligence | site suitability guarantee禁止 |
| `standards_certification_broad` | JISC/JPO/Giteki/PSE/NITE/PMDA/PPC broad references | product/compliance expansion | exact-ID packet後 |
| `public_finance` | budgets, admin project review, funds, expenditure trail | grant/procurement context | political inference禁止 |
| `official_reports_policy_background` | whitepapers, councils, study groups, annual reports | reg-change context | standalone lake化禁止 |
| `international_trade_fdi` | JETRO, customs, export-control navigation | niche high-value packets | export-control final judgement禁止 |

### 3.4 P2/P3: caution source

以下は初期AWS高速消費の対象にしない。どうしても扱うならmetadata-only, link-only, review-requiredに落とす。

- political/public-integrity-heavy datasets
- personal-name-heavy gazette/court/enforcement records
- unclear terms / robots / redistribution source
- CAPTCHA/login/paywall/rate-limit-adjacent source
- full-text court/gazette redistribution
- professional association member lists with unclear reuse terms
- source where screenshot/OCR is the only support for a critical claim

## 4. Source-by-source final review

### 4.1 法律 / e-Gov / 法令XML

判定: P0-Aでよい。

理由:

- 全ての制度・許認可・業法・法令変更packetの根拠になる。
- 構造化されておりreceipt化しやすい。
- law ID, article, version, effective dateをclaim_refにしやすい。

改善:

- `law_primary` と `policy_process_practical` を混ぜない。
- 法令本文はP0-A、通達/ガイドライン/Q&AはP0-B selectedまたはP1に分ける。
- packet外部表示では「法的判断」ではなく「公的一次情報に基づく確認候補」にする。

### 4.2 制度 / 補助金 / 助成金

判定: P0-Bで強い。

理由:

- エンドユーザーがAIに頼みやすい。
- 期限、対象、必要書類、申請窓口があり、成果物化しやすい。
- `grant_candidate_shortlist_packet` と `application_readiness_checklist_packet` は課金理由が明確。

改善:

- J-Grants、MHLW、SME系、省庁、上位自治体を先にする。
- broad local program crawlはP1に落とす。
- `eligible` ではなく `candidate_priority`, `needs_review`, `not_enough_public_evidence` を使う。

### 4.3 業法 / 許認可

判定: selected P0-B。

理由:

- 建設、不動産、運輸、人材、産廃、金融、食品などは実務価値が高い。
- 専門家相談前の質問表として売りやすい。

改善:

- P0-Bは業種上位に限定する。
- 全国すべての細かい許認可/届出をP0にしない。
- 必要書類、標準処理期間、担当窓口、申請フォームを `standard_processing_period_forms` としてP0-Bに加える。
- 「許可不要」断定は禁止。

### 4.4 官報 / 告示 / 公告 / 公示

判定: P0-B metadata, P1 broad/full.

理由:

- 法令変更、会社イベント、調達、公示情報に効く。
- ただしfull-text再配布や個人情報/公告の扱いに注意が必要。

改善:

- P0-Bは date, issue, category, title, official URL, page locator, hash, event type に限定。
- raw full-text保存/公開はP1/P2 review後。
- packetでは「官報イベント候補」「公的公告リンク」として使い、断定的な法的/信用判断に使わない。

### 4.5 通達 / ガイドライン / Q&A / パブコメ

判定: practical subset P0-B, broad archive P1。

理由:

- 法令だけでは実務判断に足りない部分を補う。
- `regulation_change_impact_packet` と `permit_scope_checklist_packet` に強く効く。

改善:

- P0-Bはpacketに紐づく省庁/業種だけ。
- 審議会資料、白書、研究会資料の広域OCRはP1。
- 通達やQ&Aはsource authority rankを法令本文と分ける。

### 4.6 自治体

判定: selected P0-B + broad P1/P2。

理由:

- 補助金、許認可、入札、条例、処分は地域ごとに強い。
- ただし全国全ページcrawlはコストに対してaccepted artifact率が低い。

改善:

- P0-B allowlist: 都道府県、政令市、中核市、事業者数/人口/経済規模が大きい自治体。
- P0-B page types: subsidies, permits, procurement, dispositions, reiki links, application forms, processing period, contact.
- その他はmetadata-onlyまたはP1。
- `local_reiki_ordinance` を明示source familyにする。

### 4.7 裁判 / 審決 / 行政不服 / 労働委員会

判定: P1。

理由:

- コンプライアンスや法務packetの品質を上げるが、RC1の売上に直結しにくい。
- 誤って「法律相談」「結論」と見られるリスクが高い。

改善:

- RC1 blockerにしない。
- P1では metadata, official URL, decision date, issue tags, short permitted excerpts, hash を中心にする。
- `case_law_context_pack` や `regulation_context_appendix` として扱い、permit/legal final judgementには使わない。

### 4.8 統計

判定: basic P0-A, broad P1。

理由:

- e-Statや地域/業種コードは補助金、地域DD、market contextの基礎になる。
- ただし統計lake全量は初期売上に直結しない。

改善:

- P0-A: municipality code, industry code, population/basic business density, regional class.
- P1: broad tables, time series, whitepaper-derived statistics.
- 統計は「文脈」「候補優先度」に使い、個社の状態推定に使いすぎない。

### 4.9 地理 / 不動産 / 災害 / 都市計画

判定: address basic P0-A, site DD expansion P1。

理由:

- 住所正規化と自治体リンクは全packetで重要。
- hazard, land price, zoning, PLATEAUは高単価packetを増やせるが初期coreではない。

改善:

- P0-Aは住所/自治体正規化まで。
- P1で `site_due_diligence_pack` 向けに広げる。
- 「適地」「安全」「災害リスクなし」断定は禁止。

### 4.10 標準 / 認証 / 製品安全

判定: exact public checks P0-B conditional, broad P1。

理由:

- 製造、輸入、EC、調達で価値がある。
- ただし標準本文や認証情報はterms/再配布/安全保証誤解が強い。

改善:

- P0-B conditional: exact ID lookup, public certification status, recall/product accident, public warning.
- P1: broad JIS/JISC/NITE/PMDA/PPC/JPO/MIC source expansion.
- 「安全」「適合保証」「認証済み保証」は禁止。

### 4.11 税 / 労務 / 社会保険

判定: P0-Bで強い。

理由:

- CSV月次レビューと相性が良く、反復課金に向く。
- 国税庁、eLTAX、年金機構、厚労省、最低賃金、労働保険、助成金などの一次情報が成果物化しやすい。

改善:

- `tax_labor_calendar` を明示する。
- CSV由来factはprivate overlayとして扱い、public source receiptと混ぜない。
- 「納税義務確定」「労務違反なし」などの断定は禁止。

### 4.12 行政処分 / 注意喚起 / ネガティブ情報

判定: P0-Bだが最も厳格に扱う。

理由:

- vendor DD、購買、監査、金融、M&Aで明確な価値がある。
- 反面、no-hitを安全証明に誤用しやすい。

改善:

- exact identifier searchを優先。
- name fuzzy matchは `candidate_match` としてhuman_review_requiredを付ける。
- `no_hit_not_absence` を必ず表示。
- sourceごとに検索対象、期間、更新日、coverage gapを出す。

### 4.13 調達 / 入札 / 指名停止

判定: selected P0-B。

理由:

- opportunity探索はROIを説明しやすい。
- 指名停止や入札参加資格はvendor/procurement DDにも効く。

改善:

- p-portal, JETRO, central agencies, top local governments first.
- `suspension_nomination_stop` を明示subfamilyにする。
- `procurement_opportunity_radar_packet` では「入札可能」ではなく「候補」「要件確認」「known gaps」として出す。

## 5. Smarter scoring model for AWS collection priority

各source family / jobは、実行前に以下のスコアで並べる。

```text
priority_score =
  0.30 * paid_output_fit
  + 0.20 * identifier_or_join_utility
  + 0.15 * terms_receipt_clarity
  + 0.15 * automation_yield
  + 0.10 * freshness_or_monitoring_value
  + 0.10 * proof_page_value
  - 0.20 * legal_privacy_risk
  - 0.15 * redistribution_risk
  - 0.10 * manual_review_load
```

Score fields:

| Field | Meaning |
| --- | --- |
| `paid_output_fit` | 具体的な有料packetに直結するか |
| `identifier_or_join_utility` | 法人番号、住所、自治体、業種などjoin spineになるか |
| `terms_receipt_clarity` | terms/robots/license/capture policyが明確か |
| `automation_yield` | 自動でaccepted artifactになりやすいか |
| `freshness_or_monitoring_value` | 更新監視や差分検出の価値があるか |
| `proof_page_value` | AI agentに見せるproofとして説明しやすいか |
| `legal_privacy_risk` | 誤解、個人情報、法律判断リスク |
| `redistribution_risk` | full textや画像公開が危ないか |
| `manual_review_load` | 人間レビューなしではclaimにしづらいか |

Execution rule:

- `priority_score >= 0.70`: P0-A/P0-B candidate.
- `0.45 <= priority_score < 0.70`: P1 candidate.
- `< 0.45`: P2/P3 or metadata-only.
- `primary_paid_output_ids[]` empty: force P2 regardless of score.
- `source_profile` fail: do not collect beyond metadata needed for audit.

## 6. Smarter source discovery and control design

このレビューで最も重要な改善は、単なる「どのsourceを先に取るか」ではなく、jpcite本体に source discovery / source selection / source suppression の仕組みを持たせることである。

正しい設計は次である。

```text
paid output definition
  -> required claims
  -> output_gap_map
  -> source hypothesis
  -> source candidate discovery
  -> source_profile gate
  -> capture method planning
  -> canary collection
  -> accepted artifact measurement
  -> expand / suppress / review decision
  -> packet fixture and proof sidecar
```

これにより、AWSは「人間が手で決めたsource一覧を大量crawlする場所」ではなく、「売れる成果物のgapを埋めるsourceを発見し、試し、採用/抑制する工場」になる。

### 6.1 Output gap map

各packetは、必要claimと必要source familyを先に宣言する。

例:

```json
{
  "output_id": "grant_candidate_shortlist_packet",
  "required_claims": [
    "program_exists",
    "application_window",
    "target_region",
    "target_industry_or_business_type",
    "required_documents",
    "official_contact_or_application_url"
  ],
  "required_source_families": [
    "subsidy_program",
    "local_government_selected",
    "policy_process_practical",
    "statistics_cohort_basic"
  ],
  "missing_claims": [
    "required_documents",
    "official_contact_or_application_url"
  ],
  "source_discovery_query": [
    "site:go.jp 補助金 必要書類 申請",
    "site:lg.jp 補助金 募集要領 PDF",
    "J-Grants program detail official URL"
  ]
}
```

この `missing_claims` がsource discoveryの起点になる。

重要な点:

- source探索の起点は「公的sourceを集めたい」ではない。
- 起点は「このpacketのこのclaimを支えるsourceが足りない」である。
- sourceが見つかっても、claimに貢献しなければ自動で抑制する。

### 6.2 Source candidate registry

発見したsource候補は、すぐ収集せず、まずregistryに入れる。

```json
{
  "source_candidate_id": "candidate:mlit:negative-info:construction",
  "discovered_from": "output_gap_map | official_link_graph | sitemap | search_result | known_source_seed | packet_failure",
  "candidate_url": "https://example.go.jp/official/path",
  "publisher_candidate": "Ministry or agency name",
  "officiality_signal": {
    "domain_class": "go.jp | lg.jp | agency_domain | public_corporation | unknown",
    "linked_from_known_official_source": true,
    "has_official_contact_or_policy_page": true
  },
  "target_output_ids": [
    "administrative_disposition_radar_packet",
    "counterparty_public_dd_packet"
  ],
  "target_claim_ids": [
    "public_disposition_event",
    "source_no_hit_check"
  ],
  "candidate_capture_methods": [
    "html_fetch",
    "playwright_observation"
  ],
  "pre_gate_decision": "review | canary | reject"
}
```

このregistryにより、source追加が属人的なメモではなく、成果物とclaimに紐づく管理対象になる。

### 6.3 Source selection features

source候補には、最低限以下のfeatureを付ける。

| Feature | Purpose |
| --- | --- |
| `officiality_score` | 公的一次情報らしさ。domain, known official link, publisher identityで評価 |
| `paid_output_fit_score` | どの有料packetのclaim gapを埋めるか |
| `receiptability_score` | URL, timestamp, content hash, span, screenshot, PDF pageでreceipt化できるか |
| `terms_clarity_score` | terms/robots/license/reuse/capture policyが明確か |
| `automation_yield_estimate` | API/HTML/PDF/Playwright/OCRのどれでaccepted artifact化しやすいか |
| `freshness_value_score` | 差分監視や期限更新の価値があるか |
| `claim_specificity_score` | 具体的claimを支えるか、背景情報止まりか |
| `privacy_reputation_risk` | 個人名、処分、政治、裁判などの慎重度 |
| `manual_review_load` | 人間確認が必要になる確率 |
| `cost_to_accept_estimate` | accepted artifact 1件あたりの見込みコスト |

このfeature setで、P0/P1/P2を一度決めて終わりにしない。canary後の実測で更新する。

### 6.4 Dynamic expand / suppress loop

AWS実行中はsourceごとに以下を計測する。

| Metric | Expand condition | Suppress condition |
| --- | --- | --- |
| `accepted_artifact_ratio` | 一定以上で拡張 | 低い場合は停止 |
| `packet_fixture_contribution` | packet例に使われたら拡張 | 使われなければ抑制 |
| `claim_gap_reduction` | missing claimが減れば拡張 | gapが埋まらなければ抑制 |
| `cost_per_accepted_artifact` | 低ければ拡張 | 高騰したら停止 |
| `manual_review_rate` | 低ければ拡張 | 高ければmetadata-only |
| `terms_or_robots_uncertainty` | clearなら拡張 | unknown/failなら停止 |
| `forbidden_claim_risk` | 低ければ拡張 | unsafe wordingを誘発するなら停止 |
| `proof_page_value` | AI agentに説明しやすければ拡張 | proofに出せなければ抑制 |

擬似コード:

```text
for each source_candidate:
  if source_profile is fail:
    suppress_to_audit_metadata()
  else if primary_paid_output_ids is empty:
    demote_to_P2()
  else:
    run_canary()
    measure accepted_artifact_ratio, cost_per_accept, claim_gap_reduction

    if claim_gap_reduction > threshold and cost_per_accept <= budget:
      expand_with_cap()
    elif manual_review_rate is high or terms_uncertain:
      switch_to_metadata_only_or_review()
    else:
      suppress_and_record_known_gap()
```

これがないと、AWS credit runは「取りやすいsourceを取り続ける」方向に流れる。このloopがあると「売れる成果物のgapを埋めるsourceだけを伸ばす」方向に自動補正される。

### 6.5 Source discovery methods

より賢いsource discoveryは、以下の複数経路を組み合わせる。

| Discovery method | Description | Use case | Guardrail |
| --- | --- | --- | --- |
| Official seed expansion | 既知公式sourceのリンク、sitemap、API catalog、RSSから候補を広げる | ministries, local gov, e-Gov, J-Grants | official domain / source_profile required |
| Output gap search | packetのmissing claimから検索queryを作る | forms, deadlines, permit requirements | search result itself is not claim support |
| Entity-driven discovery | 法人番号、許認可ID、T番号、地域、業種からsource候補を探す | vendor DD, permits, enforcement | fuzzy matchはcandidate only |
| Update/diff discovery | 更新履歴、RSS、新着、パブコメ、官報、告示から差分sourceを見つける | reg-change, grants, tax/labor | no legal conclusion |
| Link graph expansion | 公式ページから関連台帳、PDF、Excel、申請フォームへ広げる | local gov, permits, procurement | depth and page-type cap |
| Proof failure discovery | packet fixtureでknown_gapになったclaimから追加sourceを探す | all packets | gapが埋まるまで小さく試す |
| Agent demand discovery | catalog/cost-previewでAI agentがよく見るpacket/region/industryを集計する | prioritization | private query/log privacy gate |

この設計により、source範囲は手動で一気に決めるのではなく、成果物需要とgapから継続的に広がる。

### 6.6 Source suppression is a product feature

収集しない判断も価値である。

jpciteは、sourceを無理に使わず、以下のように `known_gaps[]` に落とせるべきである。

```json
{
  "gap_id": "gap:permit:local-forms:municipality-x",
  "source_family_id": "local_government_selected",
  "reason": "source_profile_terms_unknown",
  "attempted_discovery_methods": [
    "official_seed_expansion",
    "link_graph_expansion"
  ],
  "external_wording": "この自治体の申請フォームは自動確認対象外です。不存在や不要の証明ではありません。",
  "human_review_required": true
}
```

これにより、AIエージェントは「jpciteが何を確認し、何を確認していないか」を説明できる。

### 6.7 Capture method router

sourceごとに最初からPlaywright/OCRへ行かない。最も安く、権利境界が明確で、receipt化しやすい方法から試す。

Capture order:

1. official API
2. official bulk download
3. static HTML fetch
4. PDF text extraction
5. official linked CSV/XLSX
6. Playwright rendered observation
7. OCR candidate extraction
8. manual review / metadata-only

Router rule:

```text
if official API exists:
  use API
elif bulk download exists and terms allow:
  use bulk
elif static HTML has target spans:
  use HTML
elif PDF text is extractable:
  use PDF text
elif public JS-rendered page and source_profile allows:
  use Playwright observation
elif public scan/PDF image and source_profile allows:
  use OCR candidate, not final claim
else:
  metadata_only_known_gap
```

このrouterにより、Playwright/OCRのコストとterms riskを抑えつつ、fetch困難な公的ページも成果物gapに必要な範囲で扱える。

### 6.8 Auto source expansion from successful packets

有料packetが成功したら、そこから逆にsourceを増やす。

例:

- `permit_scope_checklist_packet` が建設業でよく使われる。
- known gapsとして「都道府県別様式」「標準処理期間」「変更届」が頻出する。
- source discoveryが、建設業の上位自治体フォームと処理期間ページを候補化する。
- accepted artifact率が高い自治体だけP0-B selectedへ昇格する。
- 低yield自治体はP1 metadata-onlyへ落とす。

この仕組みがあると、AWSで最初から全自治体を取りに行かなくてよい。売れたpacketがsource拡張を指示する。

### 6.9 Auto source suppression from low-value crawl

逆に、以下のsourceは自動抑制する。

- packet fixtureに一度も使われない。
- accepted artifact化できない。
- manual reviewが多すぎる。
- cost per accepted artifactが高い。
- known_gapを埋めない。
- public proofに出せない。
- no-hit誤表現を誘発する。
- terms/robotsが不明確。

抑制結果は消さずに、source registryに残す。

```json
{
  "source_candidate_id": "candidate:local:random-council-minutes",
  "decision": "suppressed",
  "reason": "no_primary_paid_output_id_and_high_manual_review_load",
  "next_review_trigger": "packet_gap_frequency >= 20"
}
```

これにより、後で需要が出たときだけ再評価できる。

### 6.10 Smarter features to build into jpcite

本体機能として、以下を実装計画に入れる価値が高い。

| Feature | What it does | Why it is smarter |
| --- | --- | --- |
| `output_gap_map` | packetごとに不足claim/sourceを管理 | source探索を成果物から逆算できる |
| `source_candidate_registry` | 発見したsource候補をclaim/outputに紐づけて管理 | 手動sourceリスト化を避ける |
| `source_profile_gate` | terms/robots/license/capture/TTLをfail-closed判定 | 本番投入できない収集を抑える |
| `capture_method_router` | API/bulk/HTML/PDF/Playwright/OCRを自動選択 | コストとriskを下げる |
| `artifact_yield_meter` | accepted artifact率、cost/yield、gap reductionを測る | AWS creditを成果物密度で使える |
| `expand_suppress_controller` | sourceごとに拡張/停止/metadata-onlyを決める | 自律的に賢くなる |
| `known_gap_publisher` | 取らない/取れない理由を外部説明に変換 | AI agentが推薦時に説明できる |
| `packet_to_source_backcaster` | 売れた/見られたpacketから次に取るsourceを提案 | GEO需要をsource拡張へ戻せる |
| `proof_value_ranker` | proof pageで説明しやすいsourceを優先 | agent recommendationが強くなる |
| `source_drift_monitor` | source構造/terms/更新頻度の変化を検知 | stale/invalid artifactを防ぐ |

この10機能は、単なる優先順位表より重要である。

### 6.11 AWS run should execute the source operating system

AWS側はsource listをただ処理するのではなく、以下のcontrol loopを回す。

```text
daily or hourly control tick:
  read packet gap map
  read source candidate registry
  score source candidates
  enqueue canaries for highest expected gap reduction
  measure accepted artifacts
  expand high-yield sources
  suppress low-yield or risky sources
  generate packet fixtures
  publish known gaps and proof sidecars
  update next source discovery frontier
```

Codex/Claudeが止まっていても、このloopはAWS側で動ける。ただしBudget Actions、kill switch、source_profile gate、terms/robots gateで必ず止まれるようにする。

### 6.12 Final revised interpretation

したがって、本レビューの修正後の結論は次である。

> よりスマートな計画とは、sourceの順番をさらに細かく並べ替えることではない。売れる成果物のmissing claimsからsource候補を発見し、source_profileとcanaryで試し、accepted artifact率とgap reductionで自動拡張/抑制する仕組みを作ることである。

この仕組みがあれば、最初にすべてのsource範囲を完璧に決め切る必要がない。むしろ、成果物需要、proof価値、known gap、cost/yieldを使って、AWS credit run中にsource対象を賢く変化させられる。

## 7. Revenue-backcast check

最終的にsource優先順位は、次の売れる成果物から逆算するべきである。

| Rank | Paid output | Must-have source | Nice-to-have source | Priority implication |
| ---: | --- | --- | --- | --- |
| 1 | `company_public_baseline` | 法人番号, インボイス, gBizINFO | EDINET metadata, enforcement selected | P0-A/P0-B |
| 2 | `invoice_vendor_public_check` | 法人番号, インボイス | gBizINFO | P0-A |
| 3 | `counterparty_public_dd_packet` | identity, gBizINFO, enforcement, permit selected | EDINET, procurement, gazette event | P0-B |
| 4 | `administrative_disposition_radar_packet` | enforcement selected | local warnings, public alerts | P0-B |
| 5 | `grant_candidate_shortlist_packet` | J-Grants, ministries, MHLW, local selected | statistics, ordinance links | P0-B |
| 6 | `application_readiness_checklist_packet` | grant requirements, forms, deadlines, contact | local procedures, policy process | P0-B |
| 7 | `permit_scope_checklist_packet` | law, permit registry, forms, processing periods | local ordinances, Q&A | P0-B |
| 8 | `regulation_change_impact_packet` | law XML, gazette metadata, public comments, circulars | councils, court context | P0-B/P1 |
| 9 | `tax_labor_event_radar_packet` | NTA, eLTAX, pension, MHLW, min wage, deadlines | CSV private overlay later | P0-B |
| 10 | `procurement_opportunity_radar_packet` | p-portal, JETRO, central/top local bids | award data, nomination stop | P0-B |
| 11 | `site_due_diligence_pack` | address/basic geo | hazard, zoning, land price, PLATEAU | P1 |
| 12 | `standards_certification_check_packet` | exact public certification/recall/status | broad standards/product safety corpus | P0-B conditional/P1 |

結論:

- P0-A/P0-BだけでRC1/RC2の売上検証はできる。
- P1は「AWS creditがある今、後から高単価packetを増やすため」にやる。
- P2/P3は初回高速消費の主対象にしない。
- さらに、実行中の `output_gap_map` と `artifact_yield_meter` によって、P0-B/P1の中身を動的に昇格/降格する。

## 8. Over-broad collections to cut or delay

以下はsourceとしては魅力があるが、今回の高速AWS runでP0化すると本番デプロイや売上検証を遅らせる。

| Collection | Decision | Reason |
| --- | --- | --- |
| 全国自治体全ページcrawl | Delay to P1/P2 | accepted artifact率が低く、noiseが多い |
| 官報full text/history | P1/P2 | metadata/eventだけで初期価値は出る |
| court full text corpus | P1 | 法的結論誤解と個人情報リスク |
| standards full catalog | P1 | exact-ID packet後でよい |
| broad whitepaper/council OCR | P1/P2 | paid outputへの接続が弱い |
| political/public integrity broad corpus | P2/P3 | reputational/privacy riskが高い |
| full EDINET XBRL extraction | P1 | launch blockerにしない |
| all geospatial/PLATEAU/hazard full lake | P1 | site DD packet後に拡張 |

## 9. Missing acceptance rules

各AWS jobには以下を必須にする。

```json
{
  "source_family_id": "string",
  "source_profile_id": "string",
  "priority_tier": "P0-A | P0-B | P1 | P2 | P3",
  "primary_paid_output_ids": ["string"],
  "accepted_artifact_target": "source_profile | source_receipt | claim_ref | known_gap | no_hit_check | packet_fixture | proof_sidecar",
  "allowed_capture_methods": ["api | bulk_download | html_fetch | playwright_observation | pdf_text | ocr_candidate"],
  "blocked_capture_methods": ["login | captcha | paywall | prohibited_redistribution"],
  "public_publish_policy": "metadata_only | short_excerpt | link_only | no_public_publish",
  "no_hit_policy_id": "no_hit_not_absence",
  "manual_review_required": true
}
```

Fail-closed rules:

- `primary_paid_output_ids[]` empty -> P2.
- `accepted_artifact_target` empty -> do not run.
- `source_profile` missing -> canary only.
- terms/robots unknown -> manual_review_required, no scale.
- personal-name-heavy -> metadata-only unless reviewed.
- screenshot/OCR-only critical claim -> no external claim support.

## 10. Recommended merged execution order

既存SOTの順番は概ね正しい。source priority観点で、最終的には以下に固定する。

1. Freeze packet contract, source receipt contract, no-hit wording, pricing/cap metadata.
2. Freeze source family taxonomy with P0-A / P0-B selected / P1 broad / P2 caution.
3. Build `output_gap_map`, `source_candidate_registry`, `capture_method_router`, and `expand_suppress_controller`.
4. Add `primary_paid_output_ids[]`, `accepted_artifact_target`, and `priority_score` to all planned AWS jobs.
5. Run P0-A source_profile and canary: identity, invoice, law XML, core statistics, address/municipality.
6. Run P0-B selected source_profile and canary: grants, permit selected, enforcement selected, procurement selected, gBizINFO, EDINET metadata, tax/labor, gazette metadata, policy process practical, selected local gov.
7. Measure accepted artifact ratio, cost per accepted artifact, and claim gap reduction.
8. Expand high-yield sources and suppress low-yield/risky sources automatically.
9. Generate packet fixtures for company baseline, invoice check, vendor DD, grant shortlist, permit checklist, admin disposition radar, reg-change, tax-labor, procurement.
10. Deploy RC1 without waiting for broad P1.
11. Use AWS high-speed credit burn on P0-B accepted sources first, then P1 expansion in ROI order.
12. Run P1 expansion only through the same source operating system: local gov broader allowlist, site/geospatial, standards/certification, courts/decisions, public finance, official reports.
13. Keep P2/P3 metadata-only unless a specific high-value packet and review policy exists.
14. Export accepted artifacts, validate checksums, import into non-AWS production assets.
15. Delete AWS run resources for zero-bill posture.

## 11. Final normalized source table

| Tier | Source family | Include now | Do not include now |
| --- | --- | --- | --- |
| P0-A | `source_profile_terms` | terms, robots, license, capture policy, TTL | none |
| P0-A | `identity_tax` | corporation number, invoice | private CSV |
| P0-A | `law_primary` | e-Gov law XML/API | commentary, unofficial summaries |
| P0-A | `statistics_cohort_basic` | codes, minimal region/industry context | broad statistical lake |
| P0-A | `geo_address_basic` | address/municipality normalization | hazard/PLATEAU/full real-estate lake |
| P0-B | `corporate_activity` | gBizINFO public facts | private aggregators |
| P0-B | `filing_disclosure_subset` | EDINET metadata/key public trail | full XBRL launch dependency |
| P0-B | `subsidy_program` | J-Grants, ministries, MHLW, local selected | unverified blogs/listings |
| P0-B | `procedure_permit_selected` | selected high-value regulated industries | every niche permit nationwide |
| P0-B | `enforcement_disposition_selected` | FSA/MLIT/MHLW/JFTC/CAA/PPC/local selected | personal-name-heavy records without review |
| P0-B | `procurement_contract_selected` | p-portal, JETRO, central/top local, nomination stop | all local procurement pages |
| P0-B | `gazette_notice_metadata` | title/date/category/link/hash/event metadata | raw full-text redistribution |
| P0-B | `policy_process_practical` | public comments, circulars, Q&A tied to packets | broad councils/whitepapers |
| P0-B | `tax_labor_social` | NTA/eLTAX/pension/MHLW/min wage/deadlines | final tax/labor advice |
| P0-B | `local_government_selected` | top local subsidies/permits/bids/dispositions/reiki links/forms | nationwide all-page crawl |
| P0-B conditional | `standards_certification_exact` | exact status, recall, public certification lookup | compliance/safety guarantee |
| P1 | `local_government_expansion` | broader ordinances/procedures/bids/notices | unbounded crawl |
| P1 | `court_dispute_decision` | metadata/context/official links | legal conclusion service |
| P1 | `geo_land_real_estate` | hazard, land price, zoning, PLATEAU | site suitability guarantee |
| P1 | `standards_certification_broad` | broader standard/product safety corpus | safety guarantee |
| P1 | `public_finance` | budgets, funds, project review | political inference |
| P1/P2 | `official_reports_policy_background` | context tied to packet | standalone report lake |
| P1/P2 | `international_trade_fdi` | source navigation and candidate checks | export-control final judgement |
| P2/P3 | `political_public_integrity` | strict review/link-only | RC1/RC2 dependency |

## 12. Specific improvements to merge back into the master plan

1. Replace broad wording like "collect local government" with "P0-B selected local government pages; P1 broad local expansion."
2. Replace broad wording like "gazette" with "P0-B gazette metadata/event ledger; P1/P2 full text/history."
3. Replace broad wording like "standards/certifications" with "P0-B conditional exact public checks; P1 broad corpus."
4. Keep `court_dispute_decision` P1 and remove it from any RC1 blocker.
5. Add `tax_labor_calendar`, `standard_processing_period_forms`, `suspension_nomination_stop`, and `local_reiki_ordinance` as explicit subfamilies.
6. Require `primary_paid_output_ids[]` on every source family and AWS job.
7. Require `accepted_artifact_target` before any job can consume significant AWS spend.
8. Add the `priority_score` model to the AWS scheduler so credit burn remains output-first.
9. Make P1 expansion start only after at least three P0 paid packet fixtures have proof sidecars.
10. For Playwright/OCR, require `source_profile` limited/pass and `public_publish_policy` before scaling.
11. Add `output_gap_map` as the primary source discovery input.
12. Add `source_candidate_registry` so discovered sources are tied to claim gaps and paid outputs before collection.
13. Add `capture_method_router` so API/bulk/HTML/PDF are tried before Playwright/OCR.
14. Add `artifact_yield_meter` and `expand_suppress_controller` so AWS automatically shifts spend toward high-yield sources.
15. Add `packet_to_source_backcaster` so GEO/agent demand and paid packet usage generate new source discovery tasks.

## 13. Final answer for this review

The source universe is not too narrow. It is broad enough for the business.

The smarter plan is not to add more categories blindly, and it is not merely to reorder the same categories. The smarter plan is to make source acquisition itself product-aware and adaptive.

Core rule:

> No source should get meaningful AWS budget unless it is tied to a packet claim gap, has a source_profile boundary, has an accepted artifact target, and can be expanded or suppressed based on measured artifact yield.

With that rule, the corrected priority is:

1. P0-A: source_profile, identity, invoice, law XML, basic stats, address/municipality.
2. P0-B: grants, permits, enforcement, procurement, gBizINFO, EDINET metadata, tax/labor, gazette metadata, practical policy process, selected local government, exact standards/certification checks.
3. P1: broad local gov, courts/decisions, broad geospatial, broad standards, public finance, official reports.
4. P2/P3: personal-sensitive, political/integrity-heavy, unclear terms, access-control-adjacent, full-text redistribution-heavy sources.

But the real improvement is the source operating system:

1. `output_gap_map` discovers what source is missing from sellable packets.
2. `source_candidate_registry` records source hypotheses before collection.
3. `source_profile_gate` blocks unsafe or unclear sources.
4. `capture_method_router` picks the cheapest compliant method.
5. `artifact_yield_meter` measures whether a source actually creates accepted artifacts.
6. `expand_suppress_controller` automatically scales useful sources and suppresses low-yield/risky ones.
7. `packet_to_source_backcaster` uses packet demand and known gaps to discover the next source frontier.

This preserves the large AWS assetization opportunity while preventing the plan from becoming an expensive public-data crawl that does not quickly improve production, GEO recommendation, or paid packet sales.
