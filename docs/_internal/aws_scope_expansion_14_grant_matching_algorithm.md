# AWS scope expansion 14/30: grant and subsidy matching algorithm

作成日: 2026-05-15
担当: 拡張深掘り 14/30 - 補助金/助成金マッチングアルゴリズム
対象: jpcite 本体計画、AWS credit run、J-Grants、自治体制度、省庁公募、厚労省助成金、CSV private overlay、AI agent向けpacket
状態: 計画のみ。AWS CLI/APIコマンド、AWSリソース作成、デプロイ、既存コード変更は行っていない。
出力先: `docs/_internal/aws_scope_expansion_14_grant_matching_algorithm.md`

## 0. 結論

補助金/助成金マッチングは、jpciteの「エンドユーザーがAIを使って欲しい成果物を安く取れる」コンセプトに最も合う。

ただし、価値の中心は「この補助金に申請できます」と断定することではない。価値は次の4つを、一次情報だけで、安く、再現可能に返すことである。

1. 公募要件とユーザー条件の照合結果。
2. なぜ候補に上がったかの `claim_refs[]`。
3. 何が不足していて最終判断できないかの `known_gaps[]`。
4. 次に集める書類、確認する窓口、締切、対象経費の注意点。

判定ラベルはユーザー指定どおり次の4つにする。

| Label | 意味 | 禁止される誤解 |
|---|---|---|
| `eligible` | 収集済み一次情報とユーザー提供factの範囲では、明示的な必須要件を満たしている候補 | 採択保証、申請可否の最終判断ではない |
| `likely` | 明確な不一致はなく、重要条件の多くに一致するが、未確認条件が残る候補 | 「申請できる」とは言わない |
| `needs_review` | 関連しそうだが、重要要件、対象経費、地域、業種、期間、必要書類などに人手確認が必要 | 低品質候補ではなく、確認価値がある候補 |
| `not_enough_info` | sourceまたはユーザーfactが足りず、候補性を評価できない | 「対象外」「該当なし」ではない |

`not_eligible` はP0では基本ラベルにしない。明確な除外条件がsource上にあり、かつユーザーfactがそれに該当する場合だけ内部理由として `hard_blockers[]` に記録する。ユーザー表示では「公開資料上、この条件は対象外/除外に該当する可能性が高いため、候補から下げました」とする。

最初に商品化するpacketは次の4つでよい。

| Packet | 価格目安 | 価値 |
|---|---:|---|
| `grant_opportunity_radar` | 300-800円 | 入力条件だけで制度候補、締切、金額、根拠、gapを返す |
| `csv_overlay_grant_match` | 1,200-3,000円 | 会計CSV-derived factsを使って事業実態に近い候補順位にする |
| `application_readiness_checklist` | 500-1,500円 | 必要書類、様式、窓口、事前準備、確認質問を返す |
| `eligibility_gap_packet` | 800-2,000円 | 1制度に対して要件ごとに `satisfied / inferred / missing / conflict / unknown` を返す |

## 1. 設計原則

### 1.1 一次情報だけで作る

このアルゴリズムは、汎用LLMの推測で制度適格性を判断しない。

使ってよい根拠:

| Source | 用途 |
|---|---|
| J-Grants | 制度名、対象、地域、締切、補助上限、補助率、公募要領リンク |
| ミラサポplus/中小企業庁 | 中小企業向け制度説明、主要制度導線 |
| 厚労省/労働局 | 雇用・人材開発・賃上げ・業務改善などの助成金 |
| 所管省庁公式ページ | 公募要領、FAQ、様式、交付規程、改定情報 |
| 自治体公式ページ | 地域補助金、創業支援、商店街、設備、雇用、空き店舗 |
| e-Gov法令/パブコメ | 根拠法令、制度改正、手続、要件の背景 |
| 官報/告示/公示 | 公布、公告、公募、政府調達、制度イベント |
| gBizINFO | 法人活動、補助金/表彰/認定などの公的シグナル |
| 法人番号/インボイス | 事業者同定、所在地、T番号の確認 |
| CSV-derived facts | 売上規模、費目構成、設備投資、人件費、IT支出などの私的派生fact |

使ってはいけない根拠:

| 禁止 | 理由 |
|---|---|
| ブログやまとめサイトの本文 | 一次情報でない |
| SNSや口コミ | 再現性と根拠性が弱い |
| LLMの制度説明だけ | hallucinationの可能性がある |
| raw CSV本文 | プライバシー上、保存・引用・再配布しない |
| 代理店広告の「採択率」 | 公的根拠ではない |

### 1.2 ラベルは最終判断ではなく、作業優先度である

`eligible` は強い言葉なので、API contract上は次のように明記する。

```json
{
  "eligibility_label": "eligible",
  "label_scope": "based_on_available_primary_sources_and_user_provided_facts",
  "not_a_final_application_decision": true,
  "human_review_required": true
}
```

UI上は「一次情報上の候補判定: eligible」と表示してもよいが、説明文は次に固定する。

```text
収集済み一次情報と入力条件の範囲では、主要な明示要件を満たしている候補です。
採択、申請可否、対象経費、必要書類の完全性は保証しません。
```

### 1.3 no-hitは不在証明ではない

検索で制度が見つからない場合の返し方:

```json
{
  "result_state": "no_hit_not_absence",
  "message": "接続済みの一次情報sourceと指定条件では、候補制度を確認できませんでした。制度が存在しない、対象外である、利用できないことの証明ではありません。",
  "known_gaps": [
    {
      "gap_type": "source_coverage",
      "description": "自治体PDFの一部、所管団体ページ、最新FAQは未収集の可能性があります。"
    }
  ]
}
```

禁止表現:

- 「使える補助金はありません」
- 「対象外です」
- 「該当なし」
- 「申請できません」
- 「助成金は存在しません」

## 2. Input model

### 2.1 ユーザー入力

最小入力:

```json
{
  "entity_type": "corporation",
  "prefecture": "東京都",
  "municipality": "渋谷区",
  "industry_text": "Web制作、SaaS開発",
  "purpose_text": "AIツール導入と営業サイト改善",
  "planned_spend_amount_jpy": 1800000,
  "planned_spend_period": {
    "start_date": "2026-06-01",
    "end_date": "2026-09-30"
  }
}
```

推奨入力:

```json
{
  "corporate_number": "1234567890123",
  "invoice_registration_number": "T1234567890123",
  "entity_type": "corporation",
  "prefecture": "東京都",
  "municipality": "渋谷区",
  "industry_code_candidates": ["3911", "4011"],
  "industry_text": "Web制作、SaaS開発",
  "employee_count_bucket": "10-49",
  "capital_jpy_bucket": "10m-50m",
  "revenue_jpy_bucket": "100m-300m",
  "founded_date_bucket": "3y-10y",
  "purpose_tags": ["it_adoption", "ai_adoption", "marketing", "productivity"],
  "planned_spend_categories": ["software_it", "advertising", "professional_fee"],
  "planned_spend_amount_jpy": 1800000,
  "planned_spend_period": {
    "start_date": "2026-06-01",
    "end_date": "2026-09-30"
  },
  "csv_overlay_summary_id": "optional_private_overlay_reference"
}
```

### 2.2 CSV-derived facts

raw CSVは保存しない。補助金マッチングで使えるのは、次のような派生factだけである。

```json
{
  "csv_derived_facts": {
    "detected_period": {
      "start_date": "2025-04-01",
      "end_date": "2026-03-31",
      "months_covered": 12
    },
    "business_scale": {
      "revenue_bucket": "100m-300m",
      "expense_bucket": "50m-100m",
      "payroll_expense_present": true,
      "payroll_expense_bucket": "10m-50m"
    },
    "spend_signals": [
      {
        "signal": "software_it_spend",
        "period": "2025-04..2026-03",
        "amount_bucket": "1m-3m",
        "confidence": 0.82
      },
      {
        "signal": "advertising_spend",
        "period": "2025-04..2026-03",
        "amount_bucket": "3m-10m",
        "confidence": 0.76
      }
    ],
    "vendor_signal_summary": {
      "invoice_id_present_count_bucket": "10-49",
      "name_only_vendor_count_bucket": "50-99"
    }
  }
}
```

CSV由来で使える主なsignal:

| Signal | マッチする制度例 | 注意 |
|---|---|---|
| `software_it_spend` | IT導入、DX、サイバーセキュリティ、AI導入 | 過去支出であり、補助対象の予定経費とは限らない |
| `advertising_spend` | 販路開拓、EC、展示会、海外展開 | 対象経費の範囲は公募要領で確認 |
| `capex_equipment_spend` | ものづくり、省エネ、設備更新 | 交付決定前着手不可に注意 |
| `payroll_expense_present` | 雇用、賃上げ、人材開発 | 労働者数や雇用保険加入はCSVだけでは不明 |
| `training_education_spend` | 人材開発、リスキリング | 対象講座・訓練計画の確認が必要 |
| `rent_store_expense` | 空き店舗、創業、商店街、事業所支援 | 物件所在地や営業実態が必要 |
| `vehicle_fuel_transport_spend` | 運輸、物流、省エネ車両 | 業種・許認可・車両条件が必要 |
| `export_related_spend` | 海外展開、展示会、JETRO系 | 輸出実績はCSVだけでは不明 |

### 2.3 入力不足の扱い

補助金要件は、ユーザー入力だけでは足りない項目が多い。

| 不足しやすい項目 | なぜ必要か | `known_gaps` |
|---|---|---|
| 従業員数 | 中小企業要件、助成金要件 | `employee_count_missing` |
| 資本金 | 中小企業者/小規模事業者判定 | `capital_missing` |
| 事業所所在地 | 自治体制度、地域限定 | `office_location_missing` |
| 業種コード | 対象業種/除外業種 | `industry_classification_uncertain` |
| 予定経費 | 補助対象経費の該当性 | `planned_expense_detail_missing` |
| 支出時期 | 交付決定前着手、対象期間 | `spend_timing_missing` |
| 雇用保険/社会保険 | 助成金要件 | `labor_insurance_status_missing` |
| 直近決算/売上減少率 | コロナ/物価/賃上げ系要件 | `financial_condition_missing` |
| 過去採択/重複申請 | 重複受給・併用制限 | `prior_award_history_missing` |
| GビズID/電子申請可否 | 申請準備 | `application_account_status_missing` |

## 3. Program fact schema

### 3.1 `grant_program_record`

AWS側で収集・抽出した制度は、まずこのrecordに正規化する。

```json
{
  "program_id": "jgrants:xxxx:round-2026-01",
  "program_name": "Example 補助金 2026年度 第1回",
  "source_family": "jgrants_public",
  "admin_body": "Example省",
  "program_type": "subsidy",
  "round_name": "2026年度 第1回",
  "status": "open",
  "acceptance_period": {
    "start_date": "2026-05-01",
    "end_date": "2026-06-30",
    "timezone": "Asia/Tokyo",
    "confidence": 0.94,
    "claim_refs": ["claim:deadline:001"]
  },
  "target_regions": [
    {
      "scope": "nationwide",
      "prefecture": null,
      "municipality": null,
      "confidence": 0.90
    }
  ],
  "target_entity_types": ["corporation", "sole_proprietor"],
  "target_industries": [
    {
      "taxonomy": "jsic",
      "code": "39",
      "label": "情報サービス業",
      "match_type": "explicit_or_mapped",
      "confidence": 0.76
    }
  ],
  "purpose_tags": ["it_adoption", "productivity", "dx"],
  "eligible_expense_categories": ["software_it", "professional_fee"],
  "subsidy_terms": {
    "max_amount_jpy": 3000000,
    "subsidy_rate": "1/2",
    "min_amount_jpy": null,
    "budget_note": "予算到達時終了の可能性",
    "claim_refs": ["claim:amount:001"]
  },
  "eligibility_rules": [],
  "required_documents": [],
  "application_channels": [],
  "supporting_sources": [],
  "known_source_gaps": []
}
```

### 3.2 `eligibility_rule`

制度要件は自然文のままではなく、可能な範囲でruleに変換する。

```json
{
  "rule_id": "rule:program:employee_count:max",
  "rule_type": "employee_count",
  "operator": "lte",
  "value": 300,
  "unit": "employees",
  "criticality": "must",
  "evidence_strength": "explicit",
  "source_receipt_ids": ["sr:guideline:page12"],
  "claim_refs": ["claim:employee_count:001"],
  "extraction_confidence": 0.91,
  "human_review_required": false
}
```

`rule_type`の標準:

| Rule type | 例 | 判定 |
|---|---|---|
| `entity_type` | 法人、個人事業主、NPO | exact / mapped |
| `region` | 東京都内に事業所 | exact / hierarchy |
| `industry` | 製造業、飲食業、情報通信業 | taxonomy mapping |
| `employee_count` | 常時使用する従業員数50人以下 | numeric |
| `capital_amount` | 資本金5,000万円以下 | numeric |
| `revenue_condition` | 売上減少率10%以上 | numeric with period |
| `expense_category` | 設備、広告、ITツール | category mapping |
| `spend_timing` | 交付決定後の経費 | temporal |
| `project_period` | 事業実施期間内 | temporal |
| `application_deadline` | 2026-06-30 17:00 | temporal |
| `prior_award` | 過去採択者除外 | unknown unless user provides |
| `permit_required` | 許認可/登録が必要 | join to permit source |
| `insurance_status` | 雇用保険適用事業所 | user/private fact |
| `document_required` | 決算書、見積書、事業計画 | readiness, not eligibility |
| `excluded_condition` | みなし大企業、風俗営業等 | hard blocker candidate |

### 3.3 `source_receipt`

すべての抽出factはsource receiptに接続する。

```json
{
  "source_receipt_id": "sr:jgrants:program:xxxx:2026-05-15",
  "source_family": "jgrants_public",
  "url": "https://example.go.jp/program",
  "retrieved_at": "2026-05-15T09:30:00+09:00",
  "content_type": "html",
  "capture_method": "api_or_playwright_or_pdf",
  "sha256": "example",
  "screenshot": {
    "available": true,
    "width_px": 1365,
    "height_px": 1600,
    "redaction_applied": false
  },
  "license_boundary": "public_official_receipt_only",
  "claim_refs": ["claim:deadline:001", "claim:amount:001"]
}
```

Playwright screenshotを使う場合も、1600px以下を原則にする。目的は視覚的証跡であり、サイト回避やアクセス制限突破ではない。

## 4. Matching pipeline

### 4.1 全体フロー

```text
1. Normalize user profile
2. Normalize CSV-derived facts
3. Load grant_program_record candidates
4. Filter by source freshness and legal/terms boundary
5. Evaluate hard blockers
6. Evaluate must rules
7. Evaluate should/nice rules
8. Compute evidence coverage
9. Compute match score
10. Assign eligibility label
11. Generate known_gaps
12. Generate no-hit explanation if needed
13. Generate price and billing metadata
14. Build packet with source_receipts and claim_refs
```

### 4.2 Candidate retrieval

最初に広く候補を取る。

候補retrievalの条件:

| Condition | 説明 |
|---|---|
| `status in open/upcoming/recently_closed` | 過去制度も次回予測や準備に使えるため、直近終了も残す |
| `region overlaps` | 全国、都道府県、市区町村、広域圏 |
| `purpose_tags overlaps` | IT、設備、雇用、販路、創業、脱炭素など |
| `industry maybe overlaps` | 明示業種、除外業種、自由文からのtaxonomy |
| `expense_category overlaps` | 予定経費またはCSV-derived spend signal |
| `deadline within horizon` | 30/60/90/180日、または次回watch対象 |

retrievalは広めにし、最終scoreとlabelで絞る。早すぎる除外は機会損失になる。

### 4.3 Hard blockers

明確に候補から下げる条件:

| Blocker | 条件 | 表示 |
|---|---|---|
| `deadline_passed` | 申請締切が過去、かつ延長情報なし | 「現在の公募回は締切済みの可能性」 |
| `region_conflict` | 対象地域が明示され、ユーザー所在地と不一致 | 「対象地域の明示条件に不一致」 |
| `entity_type_conflict` | 法人のみ/個人のみ等に不一致 | 「対象者区分に不一致」 |
| `industry_explicit_exclusion` | 除外業種に該当する明示factがある | 「除外条件に該当する可能性」 |
| `expense_category_conflict` | 対象経費が明示され、予定経費が全く異なる | 「予定経費が対象経費に一致しない可能性」 |
| `project_timing_conflict` | 交付決定前着手不可なのに支出済みfactがある | 「支出時期が対象外となる可能性」 |
| `source_terms_blocked` | source再利用条件が不明/禁止 | 表示せず内部除外 |

hard blockerがあっても、最終表示では `not_eligible` と断定しない。候補一覧から下げるか、`needs_review` で「確認すべき除外条件」として出す。

### 4.4 Rule evaluation state

各ruleは次の状態にする。

| State | 意味 |
|---|---|
| `satisfied` | source上の要件とユーザーfactが明示的に一致 |
| `inferred_satisfied` | taxonomyやCSV-derived factsから一致可能性が高い |
| `unknown` | ユーザーfact不足で判断不能 |
| `source_unclear` | 公募要領側の抽出が曖昧 |
| `conflict` | 要件とユーザーfactが不一致 |
| `not_applicable` | 当該ruleは条件分岐上不要 |

判定例:

```json
{
  "rule_id": "rule:target_region",
  "rule_type": "region",
  "required": "東京都内に主たる事業所を有する中小企業者",
  "user_fact": "東京都渋谷区",
  "evaluation_state": "satisfied",
  "confidence": 0.96,
  "claim_refs": ["claim:region:001"],
  "known_gaps": []
}
```

## 5. Scoring

### 5.1 scoreは3層に分ける

1つの点数だけにすると危険なので、3つのscoreを分ける。

| Score | 意味 |
|---|---|
| `eligibility_score` | 要件照合上の近さ |
| `value_score` | 金額、締切、支出signal、ユーザー価値 |
| `evidence_score` | source品質、claim_refs、抽出信頼度 |

最終順位は次の式でよい。

```text
ranking_score =
  0.52 * eligibility_score
+ 0.28 * value_score
+ 0.20 * evidence_score
- penalties
```

`ranking_score` は表示順であり、適格性そのものではない。

### 5.2 eligibility_score

```text
eligibility_score =
  100 * (
    0.18 * region_match
  + 0.14 * entity_type_match
  + 0.14 * industry_match
  + 0.12 * purpose_match
  + 0.10 * expense_category_match
  + 0.08 * employee_capital_match
  + 0.08 * timing_match
  + 0.06 * business_scale_match
  + 0.05 * permit_prerequisite_match
  + 0.05 * prior_award_or_duplication_check
  )
```

各subscoreは0.0から1.0。

| Subscore | 1.0 | 0.5 | 0.0 |
|---|---|---|---|
| `region_match` | 明示一致/全国 | 都道府県一致だが市区町村不明 | 明示不一致 |
| `entity_type_match` | 法人/個人/NPO等が一致 | source側が曖昧 | 明示不一致 |
| `industry_match` | 明示業種またはtaxonomy一致 | 自由文上は近い | 除外業種/不一致 |
| `purpose_match` | 目的タグ一致 | 目的の一部一致 | 関連なし |
| `expense_category_match` | 予定経費/CSV signalが対象経費に一致 | 類似費目 | 対象外経費 |
| `employee_capital_match` | 従業員/資本金が明示範囲内 | bucket推定 | 不一致/不明 |
| `timing_match` | 公募期間内かつ実施期間内 | 締切近い/一部不明 | 締切済み |
| `business_scale_match` | 売上/規模条件に一致 | bucketが粗い | 不一致/不明 |
| `permit_prerequisite_match` | 必要許認可が確認済み | 未確認 | 必要許認可が不一致 |
| `prior_award_or_duplication_check` | 重複制限に問題なし | 未確認 | 明示的に重複制限抵触 |

### 5.3 value_score

```text
value_score =
  100 * (
    0.28 * benefit_amount_score
  + 0.22 * spend_relevance_score
  + 0.18 * urgency_score
  + 0.12 * preparation_actionability_score
  + 0.10 * repeat_or_watch_value
  + 0.10 * user_intent_strength
  )
```

`benefit_amount_score`:

```text
benefit_amount_score =
  min(1.0, log10(max_amount_jpy + 1) / log10(10,000,000 + 1))
```

上限金額が高いほどscoreは上がるが、過度に大規模制度だけが上位にならないようlogを使う。

`urgency_score`:

```text
days_to_deadline = acceptance_end_date - today

if days_to_deadline < 0:
  urgency_score = 0
elif days_to_deadline <= 14:
  urgency_score = 1.0
elif days_to_deadline <= 45:
  urgency_score = 0.85
elif days_to_deadline <= 90:
  urgency_score = 0.65
elif status == "upcoming":
  urgency_score = 0.55
else:
  urgency_score = 0.35
```

`preparation_actionability_score`:

| 条件 | score |
|---|---:|
| 必要書類、様式、締切、窓口、FAQが揃う | 1.0 |
| 必要書類と締切はあるが様式/FAQが不足 | 0.75 |
| 公募要領はあるが必要書類抽出が弱い | 0.50 |
| 一覧情報だけ | 0.25 |

### 5.4 evidence_score

```text
evidence_score =
  100 * (
    0.30 * primary_source_strength
  + 0.20 * source_freshness
  + 0.18 * extraction_confidence
  + 0.14 * claim_ref_coverage
  + 0.10 * screenshot_or_receipt_coverage
  + 0.08 * license_boundary_clear
  )
```

`source_freshness`:

```text
source_age_days = today - retrieved_at

if source_age_days <= 1:
  source_freshness = 1.0
elif source_age_days <= 7:
  source_freshness = 0.9
elif source_age_days <= 30:
  source_freshness = 0.75
elif source_age_days <= 90:
  source_freshness = 0.5
else:
  source_freshness = 0.25
```

締切系は鮮度要求が高い。

```text
if program.status in ["open", "upcoming"] and source_age_days > 7:
  add known_gap: "deadline_freshness_gap"
```

### 5.5 penalties

```text
penalties =
  25 * hard_blocker_count
+ 12 * critical_unknown_count
+ 10 * deadline_uncertainty_flag
+ 8  * source_unclear_rule_count
+ 8  * csv_quality_low_flag
+ 6  * old_source_flag
+ 5  * no_guideline_pdf_flag
```

ペナルティで0未満になる場合は0に丸める。

## 6. Label assignment

### 6.1 label thresholds

```text
if source_terms_blocked:
  exclude from packet

elif hard_blocker_count > 0:
  label = "needs_review"
  display_reason = "除外/不一致となりうる明示条件があります"

elif eligibility_score >= 86
  and evidence_score >= 78
  and critical_unknown_count == 0
  and must_rule_conflict_count == 0
  and deadline_valid == true:
  label = "eligible"

elif eligibility_score >= 68
  and evidence_score >= 60
  and must_rule_conflict_count == 0
  and critical_unknown_count <= 2:
  label = "likely"

elif eligibility_score >= 45
  or value_score >= 65
  or user_intent_strong == true:
  label = "needs_review"

else:
  label = "not_enough_info"
```

### 6.2 `eligible`に必要な最低条件

`eligible`は強く見えるため、最低条件を厳しくする。

必須:

- sourceが公的一次情報である。
- 公募回、締切、対象者、対象地域、対象経費のclaim_refsがある。
- 申請期限が過去でない。
- 明示hard blockerがない。
- ユーザー所在地または事業所所在地が対象地域と整合する。
- entity typeが対象者と整合する。
- 目的/経費が対象事業と整合する。
- `human_review_required=true` が入っている。

`eligible`でも `known_gaps[]` は残る可能性がある。

例:

```json
{
  "eligibility_label": "eligible",
  "known_gaps": [
    {
      "gap_type": "prior_award_history_missing",
      "severity": "medium",
      "description": "過去採択や重複申請制限はユーザー入力がなく確認できません。"
    },
    {
      "gap_type": "quote_documents_missing",
      "severity": "low",
      "description": "見積書や仕様書の有無は未確認です。"
    }
  ]
}
```

### 6.3 `likely`

`likely`は最も多く使うラベルでよい。

条件:

- 地域、目的、経費、対象者の主要条件に概ね合う。
- ただし従業員数、資本金、過去採択、雇用保険、詳細経費などの一部が未確認。
- `source_receipts[]` と `claim_refs[]` はある。

表示:

```text
公開一次情報と入力条件の範囲では、関連性が高い制度候補です。
ただし、次の条件が未確認のため、申請可否の最終判断はできません。
```

### 6.4 `needs_review`

`needs_review`は「人間が見る価値がある」候補。

使う場面:

- 除外条件かもしれない項目がある。
- PDF抽出が曖昧。
- 自治体制度で対象地域や窓口が複雑。
- CSV-derived factsが制度目的と近いが、予定経費の詳細が不足。
- 助成金で雇用保険、賃金台帳、就業規則などの確認が必要。

表示:

```text
関連する可能性はありますが、重要要件が未確認です。
制度窓口、専門家、または公募要領本文での確認が必要です。
```

### 6.5 `not_enough_info`

`not_enough_info`は、ユーザー入力またはsource coverageが不足している状態。

表示:

```text
現時点の入力と接続済みsourceだけでは、制度候補として評価できません。
次の情報があると候補判定を改善できます。
```

このラベルは「候補がない」という意味ではない。

## 7. Known gaps

### 7.1 gap schema

```json
{
  "gap_id": "gap:employee_count_missing",
  "gap_type": "employee_count_missing",
  "severity": "high",
  "blocks_label": "eligible",
  "user_action": "従業員数レンジを入力してください。",
  "why_it_matters": "制度対象者の中小企業/小規模事業者要件に使われます。",
  "related_rules": ["rule:employee_count:max"],
  "claim_refs": ["claim:guideline:employee_requirement"]
}
```

### 7.2 gap taxonomy

| Gap type | Severity | 影響 |
|---|---|---|
| `source_coverage_gap` | high | 接続sourceが不足しno-hitを断定できない |
| `deadline_freshness_gap` | high | 締切変更/予算到達/延長の可能性 |
| `guideline_pdf_missing` | high | 詳細要件、必要書類、対象外経費が不明 |
| `faq_missing` | medium | 運用解釈が不明 |
| `employee_count_missing` | high | 中小企業/助成金要件に影響 |
| `capital_missing` | medium | 中小企業者要件に影響 |
| `industry_classification_uncertain` | high | 対象/除外業種に影響 |
| `office_location_missing` | high | 自治体制度に影響 |
| `planned_expense_detail_missing` | high | 対象経費判断に影響 |
| `spend_timing_missing` | high | 交付決定前着手不可に影響 |
| `prior_award_history_missing` | medium | 重複受給/過去採択制限に影響 |
| `labor_insurance_status_missing` | high | 助成金要件に影響 |
| `wage_increase_plan_missing` | high | 賃上げ/業務改善助成金に影響 |
| `required_documents_unknown` | medium | 申請準備に影響 |
| `application_channel_unknown` | low | GビズID、電子申請、郵送等 |
| `license_boundary_unclear` | high | 出力利用/再配布の安全性に影響 |

### 7.3 gapを売上につなげる

`known_gaps[]` は弱点ではなく、次の有料packetへの導線である。

| Gap | 次のpacket | 価格 |
|---|---|---:|
| `planned_expense_detail_missing` | `application_readiness_checklist` | 500-1,500円 |
| `employee_count_missing` | `eligibility_gap_packet` | 800-2,000円 |
| `guideline_pdf_missing` | `source_receipt_ledger` / 再取得依頼 | 100-500円 |
| `office_location_missing` | `local_program_pack` | 500-2,000円 |
| `industry_classification_uncertain` | `sector_regulation_brief` | 1,000-5,000円 |
| `labor_insurance_status_missing` | `labor_grant_match_pack` | 1,000-3,000円 |

AIエージェント向けの推薦文:

```text
この結果は候補リストです。申請前に必要条件を詰めるには、追加で eligibility_gap_packet を実行すると、未確認条件と必要書類を制度別に整理できます。
```

## 8. Required documents algorithm

### 8.1 抽出対象

公募要領、申請ページ、FAQ、様式ページから次を抽出する。

| Document fact | 例 |
|---|---|
| `application_form` | 申請書、交付申請書 |
| `business_plan` | 事業計画書、補助事業計画 |
| `estimate_quote` | 見積書、相見積 |
| `financial_statement` | 決算書、確定申告書 |
| `tax_payment_certificate` | 納税証明書 |
| `corporate_registry` | 履歴事項全部証明書 |
| `identity_document` | 本人確認書類 |
| `permit_license` | 許可証、登録証 |
| `employment_document` | 雇用契約書、就業規則、賃金台帳 |
| `vendor_document` | カタログ、仕様書、導入計画 |
| `account_id` | GビズID、電子申請アカウント |

### 8.2 document readiness score

```text
document_readiness_score =
  required_document_known_ratio * 0.45
+ user_document_available_ratio * 0.35
+ deadline_margin_score * 0.20
```

ただし、ユーザーが実際に書類を持っているかは入力がなければ分からない。CSVから推定しない。

出力:

```json
{
  "required_documents": [
    {
      "document_type": "estimate_quote",
      "label": "見積書",
      "requiredness": "required_or_likely_required",
      "source_claim_refs": ["claim:docs:quote"],
      "user_status": "unknown",
      "action": "対象経費ごとの見積書が必要か、公募要領で確認してください。"
    }
  ]
}
```

## 9. Temporal algorithm

### 9.1 日付の種類を分ける

| Date type | 重要性 |
|---|---|
| `application_start` | 受付開始 |
| `application_end` | 締切 |
| `project_start_allowed` | 交付決定後か、事前着手可か |
| `project_end` | 補助事業完了期限 |
| `report_deadline` | 実績報告期限 |
| `payment_expected` | 入金時期の目安。公的sourceにある場合のみ |
| `next_round_expected` | 過去回からの推測。低信頼でwatch扱い |

### 9.2 時間判定

```text
deadline_valid =
  application_end is not null
  and application_end >= today
  and source_freshness <= 7 days

timing_match =
  if deadline_valid and planned_spend_not_before_allowed_start:
    1.0
  elif deadline_valid and spend_timing_unknown:
    0.55
  elif application_end is null:
    0.35
  else:
    0.0
```

締切済みでも削除しない理由:

- 次回公募の準備資料になる。
- 同一制度の次回watchに使える。
- 公募要領や必要書類の構造が再利用できる。

ただし表示ラベルは `closed_reference` として区別する。

## 10. Region algorithm

### 10.1 地域階層

```text
nationwide
  -> region_block
    -> prefecture
      -> municipality
        -> ward/town/village
```

判定:

| Program target | User location | Score |
|---|---|---:|
| 全国 | どこでも | 1.0 |
| 東京都 | 東京都渋谷区 | 1.0 |
| 渋谷区 | 渋谷区 | 1.0 |
| 渋谷区 | 東京都のみ入力 | 0.55 |
| 東京都 | 神奈川県 | 0.0 |
| 対象地域不明 | 東京都 | 0.35 |

複数拠点がある場合:

```json
{
  "locations": [
    {"type": "head_office", "prefecture": "東京都", "municipality": "渋谷区"},
    {"type": "project_site", "prefecture": "大阪府", "municipality": "大阪市"}
  ]
}
```

自治体制度では、本店所在地、事業所所在地、実施場所、納税地が異なることがある。必ず `known_gaps` にどの所在地が必要かを書く。

## 11. Industry algorithm

### 11.1 業種taxonomy

業種は次の順で扱う。

1. ユーザー指定の日本標準産業分類コード。
2. 法人番号/gBizINFO等から得られる公的活動情報。
3. ユーザー自由文のcontrolled mapping。
4. CSV-derived factsによる補助signal。

CSVだけで業種を断定しない。

### 11.2 industry_match

```text
industry_match =
  1.0 if explicit JSIC/code match
  0.85 if parent category match
  0.65 if controlled synonym match
  0.45 if CSV/spend signal suggests relevance
  0.20 if source industry is broad/unclear
  0.00 if explicit exclusion match
```

例:

| User | Program | Score | gap |
|---|---|---:|---|
| JSIC 3911 情報サービス業 | 情報通信業 | 0.85 | なし |
| Web制作 | IT/DX導入 | 0.65 | `industry_classification_uncertain` |
| 飲食店 | 製造業限定 | 0.0 | `industry_conflict` |

## 12. Expense algorithm

### 12.1 対象経費taxonomy

| Expense taxonomy | 例 | CSV signal |
|---|---|---|
| `software_it` | ソフトウェア、クラウド、ITツール | software_it_spend |
| `equipment_capex` | 機械装置、工具器具備品 | capex_equipment_spend |
| `advertising_marketing` | 広告、Webサイト、展示会 | advertising_spend |
| `professional_fee` | 専門家、診断士、設計 | professional_fee_spend |
| `training` | 研修、講座、人材育成 | training_education_spend |
| `employment_wage` | 賃上げ、雇用、賃金 | payroll_expense_present |
| `energy_efficiency` | 省エネ設備、空調、照明 | capex + utility signals |
| `rent_renovation` | 家賃、改装、空き店舗 | rent_store_expense |
| `export_exhibition` | 海外展示会、翻訳、輸送 | export_related_spend |

### 12.2 CSV signalとの接続

```text
expense_category_match =
  max(
    planned_expense_match,
    csv_spend_signal_match * 0.75
  )
```

planned expenseの方が強い。CSVは過去実績なので、補助対象の予定経費とは限らない。

`known_gaps`:

- `planned_expense_detail_missing`
- `expense_timing_missing`
- `eligible_expense_scope_unclear`
- `pre_approval_spend_risk`

### 12.3 交付決定前着手リスク

補助金では、交付決定前の発注・契約・支払いが対象外になることが多い。一次情報に明示がある場合は最重要gapにする。

```json
{
  "gap_type": "pre_approval_spend_risk",
  "severity": "high",
  "description": "公募要領上、交付決定前の契約・発注・支払が対象外となる可能性があります。予定支出日を確認してください。",
  "blocks_label": "eligible"
}
```

## 13. CSV overlay algorithm

### 13.1 raw CSV禁止

補助金マッチングにおけるCSVは、次の流れに限定する。

```text
User CSV
  -> local/client or private transient parser
  -> derived facts
  -> matching engine
  -> packet
  -> discard raw CSV
```

禁止:

- AWS source lakeへのraw CSV投入。
- raw摘要、取引先名、明細金額の保存。
- screenshot化。
- packet本文での行データ引用。

### 13.2 CSV quality score

```text
csv_quality_score =
  0.25 * header_confidence
+ 0.20 * date_parse_quality
+ 0.20 * amount_parse_quality
+ 0.15 * account_mapping_coverage
+ 0.10 * period_coverage
+ 0.10 * duplicate_or_balance_quality
```

`csv_quality_score < 0.65` の場合:

- CSV-derived factsをrankingには弱く使う。
- `known_gaps` に `csv_quality_low` を追加。
- `eligible` にはしない。

### 13.3 期間の扱い

CSV期間が不足すると、制度要件と照合しづらい。

| CSV period | 扱い |
|---|---|
| 12か月以上 | 売上/費目の傾向に使える |
| 6-11か月 | 傾向は参考、季節性gap |
| 1-5か月 | 支出signal中心、売上規模判定は弱い |
| 期間不明 | `not_enough_info`寄り |

### 13.4 事業実態signal

```text
business_signal_confidence =
  account_mapping_confidence
  * period_coverage_factor
  * amount_consistency_factor
```

例:

```json
{
  "signal": "software_it_spend",
  "confidence": 0.82,
  "evidence": {
    "source": "csv_derived_fact",
    "raw_rows_exposed": false,
    "account_taxonomy": "software_it",
    "period_months": 12,
    "amount_bucket": "1m-3m"
  }
}
```

## 14. Output packet

### 14.1 `grant_opportunity_radar`

```json
{
  "packet_type": "grant_opportunity_radar",
  "request_time_llm_call_performed": false,
  "query": {
    "region": "東京都渋谷区",
    "purpose_tags": ["it_adoption", "ai_adoption"],
    "planned_spend_amount_jpy": 1800000
  },
  "results": [
    {
      "program_id": "jgrants:example",
      "program_name": "Example IT導入補助",
      "eligibility_label": "likely",
      "ranking_score": 78.4,
      "eligibility_score": 74.0,
      "value_score": 86.0,
      "evidence_score": 72.0,
      "why_matched": [
        "対象地域が全国です。",
        "対象経費にITツール/ソフトウェアが含まれる可能性があります。",
        "予定支出カテゴリと制度目的が一致しています。"
      ],
      "known_gaps": [],
      "source_receipts": [],
      "claim_refs": [],
      "billing_metadata": {
        "unit": "grant_program_candidate",
        "estimated_price_jpy": 600
      },
      "human_review_required": true
    }
  ],
  "_disclaimer": "This packet is evidence assistance, not grant application, legal, tax, labor, or accounting advice."
}
```

### 14.2 `eligibility_gap_packet`

1制度を深く見るpacket。

```json
{
  "packet_type": "eligibility_gap_packet",
  "program_id": "jgrants:example",
  "overall_label": "likely",
  "rule_evaluations": [
    {
      "rule_type": "region",
      "state": "satisfied",
      "confidence": 0.96,
      "claim_refs": ["claim:region:001"]
    },
    {
      "rule_type": "employee_count",
      "state": "unknown",
      "confidence": 0.0,
      "known_gap": "employee_count_missing"
    }
  ],
  "next_questions": [
    "常時使用する従業員数は何人ですか。",
    "予定しているITツールの見積書はありますか。",
    "発注・契約・支払は交付決定後に行う予定ですか。"
  ],
  "required_documents": [],
  "source_receipts": [],
  "claim_refs": [],
  "human_review_required": true
}
```

### 14.3 `csv_overlay_grant_match`

```json
{
  "packet_type": "csv_overlay_grant_match",
  "csv_overlay_policy": {
    "raw_csv_persisted": false,
    "raw_csv_logged": false,
    "raw_csv_sent_to_aws_source_lake": false,
    "derived_facts_only": true
  },
  "derived_fact_summary": {
    "period_months": 12,
    "csv_quality_score": 0.84,
    "signals_used": ["software_it_spend", "advertising_spend", "payroll_expense_present"]
  },
  "results": [],
  "known_gaps": [
    {
      "gap_type": "employee_count_missing",
      "severity": "high"
    }
  ]
}
```

## 15. no-hit design

### 15.1 no-hit categories

| Category | Trigger | Message |
|---|---|---|
| `no_candidate_after_filter` | 条件に合う候補が0 | 接続済みsourceでは候補未確認 |
| `source_unavailable` | source取得失敗 | source取得に失敗したため候補判定不能 |
| `coverage_insufficient` | 地方/業種source未収集 | 対象範囲が不足しているため判定不能 |
| `input_insufficient` | 入力不足 | 追加情報が必要 |
| `closed_only` | 締切済みのみ | 現在受付中は未確認。次回watch可能 |

### 15.2 no-hit packet

```json
{
  "packet_type": "grant_opportunity_radar",
  "result_state": "no_hit_not_absence",
  "connected_sources": [
    "jgrants_public",
    "mhlw_grants",
    "selected_local_government_programs"
  ],
  "message": "接続済みの一次情報sourceと指定条件では、受付中の候補制度を確認できませんでした。",
  "not_claimed": [
    "制度が存在しないとは言っていません。",
    "申請できないとは言っていません。",
    "対象外とは言っていません。"
  ],
  "known_gaps": [
    {
      "gap_type": "source_coverage_gap",
      "severity": "high",
      "description": "自治体PDF、外郭団体、商工会議所等の一部sourceは未接続です。"
    }
  ],
  "next_actions": [
    "所在地の市区町村を追加してください。",
    "予定経費の種類を追加してください。",
    "次回公募watchを設定してください。"
  ]
}
```

## 16. Pricing

### 16.1 価格設計の原則

AIエージェントがエンドユーザーに推薦しやすい価格にする。

価格の考え方:

```text
packet_price =
  base_price
+ source_count_price
+ pdf_ocr_price
+ csv_overlay_price
+ freshness_price
+ depth_price
```

ただし、価格説明は簡潔にする。

| Packet | Free preview | Paid price | 課金単位 |
|---|---|---:|---|
| `grant_opportunity_radar` | 上位3件の制度名と締切だけ | 300-800円 | 1条件検索 |
| `csv_overlay_grant_match` | signal数と候補件数だけ | 1,200-3,000円 | 1 CSV-derived overlay |
| `application_readiness_checklist` | 必要書類の件数だけ | 500-1,500円 | 1制度 |
| `eligibility_gap_packet` | unknown gap件数だけ | 800-2,000円 | 1制度 |
| `deadline_action_calendar` | 直近締切件数だけ | 300-1,000円 | 1条件検索 |
| `grant_watch_monthly` | 新着件数だけ | 980-4,980円/月 | 1 profile watch |

### 16.2 cost preview

AI agent向けには、実行前に必ずcost previewを返す。

```json
{
  "tool": "match_grants",
  "estimated_price_jpy": 1200,
  "billing_unit": "profile_packet",
  "expected_outputs": [
    "up_to_20_program_candidates",
    "eligibility_label",
    "source_receipts",
    "known_gaps",
    "next_questions"
  ],
  "free_preview_available": true
}
```

### 16.3 高単価化のポイント

高くできるのは「検索」ではなく「作業が進む成果物」。

| 高単価要素 | 理由 |
|---|---|
| CSV-derived facts | ユーザー実態に近い順位付けになる |
| 必要書類チェック | 申請準備の実務に直結 |
| 制度別gap表 | 専門家/窓口相談にそのまま渡せる |
| deadline calendar | 緊急性がある |
| watch | 継続課金になる |
| source receipt ledger | AI/士業/BPOが説明責任を果たせる |

## 17. AWS credit runで作るべきもの

AWSコマンドはこの文書では実行しない。計画上、AWSで作るべき成果物は次である。

### 17.1 Public source corpus

| Job | 内容 | 優先 |
|---|---|---:|
| `GMA-J01` | J-Grants制度record正規化 | P0 |
| `GMA-J02` | 厚労省助成金/労働局source profile | P0 |
| `GMA-J03` | 自治体制度ページ/PDF allowlist取得 | P0 |
| `GMA-J04` | 省庁公募/FAQ/様式ページ取得 | P0 |
| `GMA-J05` | 公募要領PDFから要件/対象経費/書類抽出 | P0 |
| `GMA-J06` | 締切/受付期間/実施期間の日時抽出 | P0 |
| `GMA-J07` | source_receipt / screenshot / checksum生成 | P0 |
| `GMA-J08` | rule extraction confidence audit | P0 |
| `GMA-J09` | no-hit coverage ledger | P0 |
| `GMA-J10` | public proof packet examples生成 | P0 |

### 17.2 Algorithm fixture

| Fixture | 内容 |
|---|---|
| `program_records.jsonl` | 正規化済み制度record |
| `eligibility_rules.jsonl` | rule化した要件 |
| `required_documents.jsonl` | 必要書類候補 |
| `deadline_events.jsonl` | 締切/実施/報告期限 |
| `source_receipts.jsonl` | 証跡 |
| `claim_refs.jsonl` | claimとsourceの対応 |
| `known_gap_patterns.jsonl` | gap taxonomy |
| `synthetic_csv_overlay_cases.jsonl` | raw CSVを含まないテストケース |
| `golden_match_cases.jsonl` | expected labelつき回帰テスト |

### 17.3 Playwright/screenshot利用

fetchだけで取れない公式ページはPlaywrightで取得する。

制約:

- CAPTCHA突破やアクセス制限回避はしない。
- スクリーンショットは1600px以下。
- 個人情報やprivate CSVは撮らない。
- HAR/consoleはtokenやcookieを保存しない設定にする。
- screenshotはsource receiptの補助証跡であり、全文再配布商品にしない。

## 18. Quality gates

### 18.1 Release blockers

次のどれかがあれば本番に出さない。

| Blocker | 理由 |
|---|---|
| `eligible` にsource_receiptsがない | 根拠なし判定になる |
| `eligible` にdeadline claimがない | 締切誤案内リスク |
| `eligible` にhuman_review_requiredがない | 最終判断に見える |
| raw CSVがpacket/logに残る | プライバシー違反 |
| no-hitを該当なしと表現 | 危険な断定 |
| 採択保証/申請可否断定文がある | liability risk |
| source freshnessが古いのに受付中扱い | 締切誤案内 |
| 公募要領なしで対象経費を断定 | 根拠不足 |
| pricing previewなしで有料実行 | agent推薦に不向き |

### 18.2 Regression tests

最低限のテスト:

| Test | 内容 |
|---|---|
| `test_no_raw_csv_leak` | raw CSV文字列、摘要、取引先名が出力にない |
| `test_no_hit_not_absence` | no-hit文言が不在証明にならない |
| `test_eligible_requires_receipts` | eligibleにはsource_receipts必須 |
| `test_deadline_freshness` | 受付中制度はfresh source必須 |
| `test_hard_blocker_downgrades` | hard blockerがあればeligibleにならない |
| `test_known_gaps_for_missing_employee` | 従業員数不足がgap化される |
| `test_csv_quality_downweights` | 低品質CSVはeligible禁止 |
| `test_cost_preview` | 有料packetには事前価格がある |

### 18.3 Human review queue

`needs_review`が多すぎる場合は、ユーザー価値が落ちる。しかし少なすぎると危険な断定になる。

運用品質KPI:

| KPI | 目標 |
|---|---:|
| `eligible` のsource_receipt coverage | 100% |
| `likely` のknown_gaps平均件数 | 1-4 |
| `needs_review` の次質問生成率 | 95%以上 |
| no-hitのsafe wording率 | 100% |
| raw CSV leak | 0 |
| expired deadline surfaced as open | 0 |

## 19. GEO and AI agent story

### 19.1 Agentが推薦する理由

AI agentに見せるべき説明:

```text
jpcite can return a source-backed grant matching packet for Japanese public grants and subsidies.
It does not claim final eligibility or award probability.
It returns official source receipts, claim references, known gaps, deadlines, required documents, and next questions.
It can optionally use private CSV-derived facts without storing raw CSV.
```

日本語:

```text
jpciteは、日本の補助金・助成金について、一次情報ベースの候補判定packetを返します。
採択や申請可否は保証せず、根拠、未確認条件、締切、必要書類、次に聞く質問を返します。
CSVを使う場合も、raw CSVは保存せず、派生した集計factだけで照合します。
```

### 19.2 Public proof examples

公開ページに置く例:

| Example | 内容 |
|---|---|
| `東京都 IT導入 50人未満` | likely/needs_reviewの違いを見せる |
| `飲食店 空き店舗 補助金` | 地域gapを見せる |
| `設備投資 交付決定前支出` | timing riskを見せる |
| `雇用助成金 CSV給与signal` | labor insurance gapを見せる |
| `no-hit example` | no_hit_not_absenceを明示する |

## 20. Implementation order

本体計画とマージする順番:

```text
1. Packet contractに `grant_opportunity_radar`, `csv_overlay_grant_match`, `eligibility_gap_packet` を追加
2. `grant_program_record` / `eligibility_rule` / `required_document` schemaを固定
3. J-Grants + 厚労省 + 省庁 + 自治体source profileを作る
4. AWS credit runでpublic source corpusとsource_receiptsを生成
5. synthetic CSV overlay casesを作る
6. deterministic matching engineを実装
7. golden match casesでlabel regression test
8. REST/MCP toolにcost previewを追加
9. public proof examplesを生成
10. stagingでno-hit/CSV leak/eligible receipt gateを確認
11. production deploy
12. AWS成果物をexport
13. zero-bill cleanup
```

早く本番を出す場合の最小slice:

```text
P0-min:
  - J-Grants + 厚労省 + 主要省庁だけ
  - CSVなし
  - grant_opportunity_radar
  - eligibility_gap_packet
  - no-hit safe wording
  - cost preview
  - source_receipts必須

P0.5:
  - synthetic CSV overlay
  - 自治体上位100
  - required document extraction

P1:
  - raw CSV非保存のprivate overlay本番化
  - watch
  - 業種別pack
```

## 21. Example end-to-end

### 21.1 User request

```text
東京都渋谷区のWeb制作会社です。AIツール導入と営業サイト改善に使える補助金を探してください。
```

### 21.2 Internal facts

```json
{
  "prefecture": "東京都",
  "municipality": "渋谷区",
  "industry_text": "Web制作",
  "purpose_tags": ["ai_adoption", "it_adoption", "marketing"],
  "planned_spend_categories": ["software_it", "advertising"],
  "employee_count_bucket": "unknown",
  "capital_jpy_bucket": "unknown"
}
```

### 21.3 Candidate result

```json
{
  "program_name": "Example IT/DX補助金",
  "eligibility_label": "likely",
  "ranking_score": 81.2,
  "eligibility_score": 72.0,
  "value_score": 88.0,
  "evidence_score": 78.0,
  "why_matched": [
    "対象地域が全国または東京都を含みます。",
    "制度目的がIT導入/DX/生産性向上に関係します。",
    "予定経費がソフトウェア/広告/専門家費に近い可能性があります。"
  ],
  "known_gaps": [
    {
      "gap_type": "employee_count_missing",
      "severity": "high",
      "blocks_label": "eligible"
    },
    {
      "gap_type": "planned_expense_detail_missing",
      "severity": "high",
      "blocks_label": "eligible"
    }
  ],
  "next_questions": [
    "常時使用する従業員数は何人ですか。",
    "予定している支出は、ソフトウェア利用料、制作費、広告費、専門家費のどれですか。",
    "契約・発注・支払は交付決定後に行う予定ですか。"
  ]
}
```

## 22. What not to build

P0で作らないもの:

| 作らないもの | 理由 |
|---|---|
| 採択確率予測 | 一次情報だけでは根拠が弱く、危険 |
| 申請可否の断定 | 専門家/窓口確認が必要 |
| 自動申請代行 | 法務/実務範囲が重い |
| raw CSV保存型の顧客DB | プライバシーと信頼を損ねる |
| 非公式サイト込みの広域クローラ | hallucination/terms/品質リスク |
| 自治体制度の完全網羅宣言 | coverage gapが必ず残る |

## 23. Final recommendation

補助金/助成金マッチングは、jpciteのP0-Aに入れるべきである。

理由:

- エンドユーザーの支払い意思が強い。
- AIエージェントが「安い根拠付きpacket」として推薦しやすい。
- 一次情報、source receipt、known gapの価値が明確。
- CSV private overlayで「検索」から「自社向け候補」へ価値が上がる。
- `eligible / likely / needs_review / not_enough_info` の4ラベルで、断定を避けながら実務に使える。

最初の実装は、`eligible`を乱発せず、`likely`と`needs_review`を中心にするのが安全である。ユーザー価値は「候補を当てる」だけでなく、「なぜ候補か」「何が足りないか」「次に何を聞くか」を返すことで十分に出る。

AWS credit runでは、公的制度データを広く集めるだけでなく、このアルゴリズムが必要とする `program_record`, `eligibility_rule`, `required_document`, `deadline_event`, `source_receipt`, `claim_ref`, `known_gap_pattern`, `golden_match_case` を量産する。これにより、クレジット消化後も本体サービスで低コストにpacketを売り続けられる。
