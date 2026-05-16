# Program Matching / Ranking Math Deep Dive 2026-05-15

担当: Program/source matching and ranking math acceptance  
範囲: 実装前の受入設計のみ。実装コード・既存データ・既存ドキュメントは変更しない。  
前提: CSV派生シグナルや会社属性から、補助金/制度/公的情報候補を rank する。ただし採択可否、税務判断、法的判断、信用判断はしない。score は説明可能で `source_receipts` に戻れる必要がある。

## 0. 結論

ランキングは「申請できる/採択される可能性」ではなく、「追加調査する価値が高い制度候補の優先順位」として定義する。最小受入ラインは次の3点。

1. `match_score` は source-backed feature の加重和に、freshness、coverage、known gap、conflict penalty を掛けた説明可能スコアにする。
2. すべての feature は `source_receipt_id[]` と `evidence_state` を持つ。receipt に戻れない feature は ranking に入れず、候補表示の補足にも使わない。
3. `confidence` は「ランキング説明の根拠充足度」であり、採択確率ではない。`known_gaps[]` はスコアを下げるだけでなく、利用者への次アクションに変換する。

推奨する公開文言:

> この順位は、公的情報・入力CSVから確認できる条件に基づく「確認優先度」です。採択見込み、申請可否、税務上の取扱いを判定するものではありません。未確認条件は known gaps として表示します。

## 1. Score formula candidates

### 1.1 Formula A: Explainable weighted linear score

初期実装の候補。説明しやすく、acceptance test を書きやすい。

```
base_match =
  0.18 * geography_fit
+ 0.16 * industry_fit
+ 0.14 * purpose_fit
+ 0.12 * entity_type_fit
+ 0.10 * size_stage_fit
+ 0.10 * investment_fit
+ 0.08 * deadline_fit
+ 0.06 * certification_fit
+ 0.04 * past_public_activity_fit
+ 0.02 * keyword_text_fit

evidence_multiplier =
  0.70 + 0.30 * evidence_coverage

freshness_multiplier =
  min(1.00, 0.65 + 0.35 * freshness_score)

penalty =
  0.22 * hard_mismatch_penalty
+ 0.14 * conflict_penalty
+ 0.10 * stale_penalty
+ 0.08 * missing_critical_penalty
+ 0.06 * ambiguity_penalty

match_score =
  clamp(100 * base_match * evidence_multiplier * freshness_multiplier * (1 - penalty), 0, 100)
```

設計意図:

- geography / industry / purpose を上位に置く。制度探索では「対象地域・対象業種・資金用途」が外れると候補価値が大きく下がる。
- amount や subsidy rate を過大評価しない。上限額が大きい制度を機械的に上位へ寄せると誤誘導になる。
- keyword_text_fit は補助的に留める。名称一致だけで高順位にしない。
- `hard_mismatch_penalty` は上限を強く下げるが、候補を完全削除しない。未確認と不一致を分けるため。

### 1.2 Formula B: Gate-first score

公募要領の構造化が十分に取れた制度で使う候補。明確な必須条件を先に gate として扱う。

```
eligibility_gate =
  min(
    geography_gate,
    entity_type_gate,
    application_window_gate,
    excluded_sector_gate,
    required_certification_gate
  )

opportunity_score =
  0.24 * purpose_fit
+ 0.20 * industry_fit
+ 0.16 * investment_fit
+ 0.12 * size_stage_fit
+ 0.10 * public_activity_fit
+ 0.08 * deadline_fit
+ 0.06 * administrative_readiness_fit
+ 0.04 * keyword_text_fit

match_score =
  clamp(100 * eligibility_gate * opportunity_score * evidence_multiplier - penalty_points, 0, 100)
```

gate 値:

| gate state | value | 表示 |
|---|---:|---|
| `confirmed_match` | 1.00 | 根拠あり一致 |
| `likely_match` | 0.85 | 根拠あり候補一致、人間確認推奨 |
| `unknown` | 0.65 | 条件未抽出または入力不足 |
| `likely_mismatch` | 0.30 | 不一致候補、例外条件が残る |
| `confirmed_mismatch` | 0.05 | 明確な対象外。ただし学習/説明用に低順位表示可 |

この式は「制度候補を消しすぎない」ことを重視する場合、`confirmed_mismatch` でも 0 にしない。UI/API 側では `status=likely_out_of_scope` として、通常の top candidates からは除外してもよい。

### 1.3 Formula C: Two-score model

利用者への誤解を最も減らす候補。順位用と根拠信頼用を分けて返す。

```
relevance_score = f(company_profile, csv_signals, program_attributes)
evidence_confidence = g(receipt_quality, feature_coverage, freshness, conflict_state)
display_score = relevance_score * (0.60 + 0.40 * evidence_confidence)
```

返却例:

```json
{
  "program_id": "UNI-...",
  "rank": 1,
  "display_score": 78.4,
  "relevance_score": 86.2,
  "evidence_confidence": 0.74,
  "score_label": "high_priority_for_review",
  "not_a_decision": true
}
```

推奨は Formula C を外部契約に近い形とし、内部の初期計算は Formula A で始めること。`display_score` だけを単独表示せず、`relevance_score` と `evidence_confidence` を分けると採択確率との混同を避けられる。

## 2. Feature list and source_receipts binding

### 2.1 Feature contract

ranking に使う feature は次の構造を必須にする。

```json
{
  "feature_id": "geography_fit",
  "value": 0.92,
  "evidence_state": "source_backed",
  "source_receipt_ids": ["sr_nta_corporate_number_...", "sr_program_detail_..."],
  "derived_from": ["company.prefecture", "program.prefecture"],
  "explanation": "会社所在地と制度対象地域が一致",
  "known_gap_tags": [],
  "review_required": false
}
```

`source_receipt_ids` が空の場合:

- `value` は score 計算に入れない。
- `known_gaps[]` に `feature_unbacked` を追加する。
- 表示文は「未確認」または「入力不足」とし、「一致」と書かない。

### 2.2 Core features

| feature | weight candidate | company/source side | program/source side | receipt binding | 注意 |
|---|---:|---|---|---|---|
| `geography_fit` | 0.18 | 法人番号所在地、CSV入力所在地、事業所所在地 | 対象都道府県、市区町村、全国対象 | NTA法人番号、入力CSV receipt、制度ページ/公募要領 receipt | 本店所在地と実施場所が違う可能性を gap にする |
| `industry_fit` | 0.16 | CSV勘定科目軽分類、業種入力、法人公的属性 | 対象業種、除外業種 | CSV derived receipt、gBizINFO/法人属性、制度要領 receipt | CSV科目は業種断定ではなく signal |
| `purpose_fit` | 0.14 | 設備、IT、採用、販路、研究開発などの支出/計画 signal | 資金用途、補助対象経費 | CSV derived receipt、申告 profile receipt、制度要領 receipt | 税務上の経費該当性は判断しない |
| `entity_type_fit` | 0.12 | 法人/個人、営利/非営利、中小企業 hint | 対象者種別 | NTA、インボイス、入力 profile、制度要領 | 「中小企業者」該当性は未確認なら gap |
| `size_stage_fit` | 0.10 | 従業員/売上/創業年/資本金の入力または公的属性 | 規模、創業年、成長段階要件 | 入力 profile、NTA、EDINET where applicable、制度要領 | EDINET大企業情報を中小判定に直結しない |
| `investment_fit` | 0.10 | 予定投資額、CSV上の設備/ソフトウェア signal | 補助下限/上限、対象経費 | CSV derived receipt、profile、制度要領 | 金額は raw明細でなく集計/派生値のみ |
| `deadline_fit` | 0.08 | 現在日、準備期間、決算期/活動期間 | 公募開始/締切 | jGrants/公式制度ページ receipt | 期限不明は高順位にしすぎない |
| `certification_fit` | 0.06 | 経営革新計画、認定農業者、えるぼし等の入力/公的確認 | 加点/必須認定 | 入力 profile、公的認定 receipt、制度要領 | self-declared は `user_asserted` と表示 |
| `past_public_activity_fit` | 0.04 | 過去採択、調達、認定、公開活動 | 制度分野との近接 | gBizINFO、p-portal、jGrants採択資料 receipt | 採択実績は将来採択を意味しない |
| `keyword_text_fit` | 0.02 | ユーザー query、CSV軽語彙 | 制度名、概要、要領語彙 | query receipt、制度 receipt | BM25/embedding は補助。source-backed説明が必要 |

### 2.3 Penalty features

| penalty | max impact | source_receipts | 表示 |
|---|---:|---|---|
| `hard_mismatch_penalty` | -22% | 制度要領 + 会社属性 receipt | 「対象地域/対象者の明確な不一致があります」 |
| `conflict_penalty` | -14% | 競合する source receipts | 「入力値と公的情報が一致しません」 |
| `stale_penalty` | -10% | stale receipt | 「根拠取得日が古いため確認が必要です」 |
| `missing_critical_penalty` | -8% | no_hit/blocked receipts | 「必須条件の根拠が未接続です」 |
| `ambiguity_penalty` | -6% | multi_hit receipts | 「同名/複数候補があり会社同定に確認が必要です」 |

penalty は `known_gaps[]` と重複してよい。違いは、penalty が順位計算、known gap が説明と次アクションを担う点。

### 2.4 Receipt quality scoring

`evidence_coverage` は単純な receipt 件数ではなく、重要 feature の根拠充足率として計算する。

```
evidence_coverage =
  weighted_sum(feature_weight * receipt_quality(feature)) / sum(feature_weight)
```

`receipt_quality` 候補:

| state | value | 条件 |
|---|---:|---|
| `official_primary_current` | 1.00 | 公式/一次、公募中または基準日が新しい、parse成功 |
| `official_primary_stale` | 0.75 | 公式/一次だが鮮度期限超過 |
| `official_aggregate_current` | 0.70 | gBizINFO等の公的集約。upstreamあり |
| `user_asserted_with_receipt` | 0.55 | 入力CSV/profile由来で出典は入力に限られる |
| `machine_extracted_needs_review` | 0.45 | PDF/OCR/LLM抽出で validator 未完了 |
| `no_hit_receipt` | 0.35 | zero_result。absence ではない |
| `blocked_or_parse_failed` | 0.20 | API/parse/license/rateで未確認 |
| `unbacked` | 0.00 | receipt なし |

## 3. Confidence and known_gaps

### 3.1 Confidence definition

`confidence` は候補が「説明可能に順位付けできている度合い」であり、次を合成する。

```
confidence =
  clamp(
    0.40 * evidence_coverage
  + 0.25 * identity_confidence
  + 0.20 * program_condition_coverage
  + 0.10 * freshness_score
  + 0.05 * conflict_free_score,
    0,
    1
  )
```

表示ラベル:

| confidence | label | 使い方 |
|---:|---|---|
| 0.85..1.00 | `well_supported` | 上位候補として表示可。未判断disclaimerは維持 |
| 0.70..0.84 | `supported_with_gaps` | 上位表示可。known gaps を同画面に出す |
| 0.50..0.69 | `review_needed` | 候補として表示。人間確認を明示 |
| 0.30..0.49 | `weak_support` | 通常 top からは下げる。検索候補には残す |
| 0.00..0.29 | `insufficient_evidence` | ranking ではなく未確認候補として扱う |

禁止事項:

- `confidence=0.90` を「90%採択見込み」と表現しない。
- `no_hit` を「対象外」「該当なし」「登録なし」と断定しない。
- CSVに現れた勘定科目から、税務上の処理や補助対象経費該当性を断定しない。

### 3.2 Known gap taxonomy

| tag | 意味 | score handling | user-facing next action |
|---|---|---|---|
| `identifier_missing` | 法人番号/T番号等の強IDなし | identity confidence を下げる | 法人番号または正確な所在地を確認 |
| `name_only_match` | 会社名のみで候補生成 | ambiguity penalty | 同名法人候補の確認 |
| `implementation_location_unknown` | 本店所在地と実施場所が不明 | geography_fit を capped | 事業実施場所を入力 |
| `program_deadline_unknown` | 締切未抽出/未接続 | deadline_fit を低め固定 | 公式ページで公募期間を確認 |
| `eligibility_clause_missing` | 対象者/対象経費条項未抽出 | confidence を下げる | 公募要領の該当条項を確認 |
| `required_certification_unverified` | 必須/加点認定が未確認 | certification_fit を capped | 認定番号・承認日・通知書を確認 |
| `company_size_unknown` | 資本金/従業員等が不明 | size_stage_fit を capped | 中小企業者要件に必要な情報を確認 |
| `csv_signal_only` | CSV由来の弱い業種/目的 signalのみ | receipt_quality 0.55 上限 | 実際の事業計画・投資内容を確認 |
| `source_stale` | receipt が鮮度期限超過 | stale penalty | 最新公募ページを再取得 |
| `source_blocked` | API/ライセンス/parse失敗 | blocked quality | source 接続または手動確認 |
| `conflicting_sources` | 入力値と公的情報が矛盾 | conflict penalty | どちらが最新か確認 |
| `adoption_not_predicted` | 採択確率対象外 | score計算には入れない | 採択審査は所管窓口/専門家へ確認 |
| `tax_treatment_not_assessed` | 税務処理対象外 | score計算には入れない | 税理士等へ確認 |

### 3.3 Score caps by gap

強い known gap がある場合は、feature 単位だけでなく candidate 全体に cap をかける。

| condition | max `display_score` | 理由 |
|---|---:|---|
| program official source missing | 55 | 制度側の一次根拠がない |
| identity ambiguous and company-specific program | 60 | 同名別法人リスク |
| confirmed geography mismatch | 35 | 対象地域外の可能性が高い |
| deadline expired confirmed | 30 | 直近申請候補としては低い |
| source blocked for eligibility clauses | 65 | 主要要件未確認 |
| only keyword_text_fit available | 25 | 名称一致だけでは推薦不可 |

cap は説明に必ず出す。

例:

```json
{
  "score_cap_applied": {
    "cap": 60,
    "reason": "identity_ambiguous",
    "source_receipt_ids": ["sr_nta_corporate_number_..."],
    "message": "会社名のみの複数候補があるため、会社固有制度の順位を上限60に制限しました。"
  }
}
```

## 4. Ranking output contract

`application_strategy_pack.sections[].ranked_candidates[]` の候補形。

```json
{
  "rank": 1,
  "program_id": "UNI-...",
  "program_name": "制度名",
  "display_score": 78.4,
  "relevance_score": 86.2,
  "evidence_confidence": 0.74,
  "confidence_label": "supported_with_gaps",
  "score_label": "high_priority_for_review",
  "not_a_decision": true,
  "top_reasons": [
    {
      "feature_id": "geography_fit",
      "impact": "+high",
      "message": "対象地域と会社所在地が一致",
      "source_receipt_ids": ["sr_nta_corporate_number_...", "sr_program_detail_..."]
    }
  ],
  "risk_or_gap_reasons": [
    {
      "gap_tag": "required_certification_unverified",
      "message": "加点/必須認定の有無が未確認",
      "source_receipt_ids": ["sr_program_detail_..."]
    }
  ],
  "source_receipts": ["sr_...", "sr_..."],
  "known_gaps": ["required_certification_unverified"],
  "human_review_required": true
}
```

受入上の必須条件:

- `top_reasons[]` と `risk_or_gap_reasons[]` の全項目に receipt がある。
- `not_a_decision=true` が常に入る。
- `score_label` は順位説明ラベルであり、採択ラベルではない。
- `known_gaps[]` が空でない場合、次アクションが少なくとも1つある。

## 5. Acceptance tests

### 5.1 Formula invariants

| test id | 入力 | 期待 |
|---|---|---|
| `rank_no_unbacked_feature` | receipt なし feature が value を持つ | score 計算から除外され、`feature_unbacked` gap が出る |
| `rank_primary_source_beats_keyword` | Aは公式根拠あり中程度一致、Bは名称一致のみ | A が B より上位 |
| `rank_hard_mismatch_caps` | 対象地域が confirmed mismatch | `display_score <= 35` |
| `rank_deadline_expired_caps` | 締切超過が公式 receipt で確認済み | `display_score <= 30`、または通常候補から除外 |
| `rank_no_hit_not_absence` | no_hit receipt のみ | 「存在しない」と表示しない。`absence_not_proven` を含む |
| `rank_confidence_not_probability` | confidence 0.9 | 文言に「採択確率」「合格可能性」等が出ない |
| `rank_score_monotonic_evidence` | 同じ relevance で公式根拠が追加 | `evidence_confidence` が下がらない |
| `rank_score_monotonic_conflict` | 競合 source を追加 | `conflict_penalty` が増え、confidence が上がらない |
| `rank_explain_top_n` | top 5 を返す | 各候補に正/負理由が最低1件ずつ、または gap 理由がある |
| `rank_stable_tiebreak` | 同一 score | `program_id` 等の安定キーで順序が再現する |

### 5.2 Receipt binding tests

| test id | 条件 | 期待 |
|---|---|---|
| `receipt_all_features_traceable` | candidate features を列挙 | ranking に入った feature は全て `source_receipt_ids.length > 0` |
| `receipt_no_hit_surface` | zero_result source | `result_state=zero_result` と `no_hit_interpretation=absence_not_proven` が説明に反映 |
| `receipt_user_asserted_labeled` | profile 入力のみ | `evidence_state=user_asserted` と表示し、公式確認と混同しない |
| `receipt_machine_extracted_review` | PDF抽出 validator 未実行 | `machine_extracted_needs_review` と `human_review_required=true` |
| `receipt_stale_penalty` | source freshness SLA 超過 | `source_stale` gap と stale penalty が出る |
| `receipt_conflict_reason` | 入力所在地とNTA所在地が異なる | `conflicting_sources` gap、両方の receipt ids が入る |

### 5.3 Safety and language tests

禁止語の例:

- 「採択されます」
- 「申請可能です」単独表現
- 「対象外です」ただし confirmed mismatch の根拠付き低順位説明は可
- 「税務上有利です」
- 「補助対象経費です」ただし「公募要領上の対象経費候補に該当する可能性があり確認が必要」は可
- 「公的情報にないので問題ありません」

期待文言の例:

- 「確認優先度が高い候補」
- 「公式資料上の条件と一致している項目があります」
- 「未確認条件があります」
- 「採択可否・税務判断ではありません」
- 「no_hit は不存在の証明ではありません」

### 5.4 API/artifact acceptance

| test id | 期待 |
|---|---|
| `artifact_ranked_candidates_shape` | `rank`, `program_id`, `display_score`, `relevance_score`, `evidence_confidence`, `known_gaps`, `source_receipts`, `not_a_decision` がある |
| `artifact_known_gap_next_action` | `known_gaps.length > 0` なら `next_actions[]` に対応項目がある |
| `artifact_source_receipt_dedup` | candidate 内 receipt ids は重複しない |
| `artifact_corpus_snapshot_present` | artifact top level に `corpus_snapshot_id` / `corpus_checksum` がある |
| `artifact_no_raw_csv_leak` | CSV由来 feature は派生値だけで、取引明細・摘要・取引先名を出さない |
| `artifact_human_review_required` | confidence < 0.70 または critical gap ありなら true |

## 6. Calibration examples

### 6.1 Example A: 製造業CSV + 設備投資制度

入力 signal:

- CSV派生: `機械装置`, `外注加工費`, `国庫補助金受贈益` 等の軽分類 signal。
- 会社属性: 法人番号 exact、所在地は対象都道府県内。
- 制度: 設備投資、製造業、中小企業者、締切あり。

期待:

| feature | value | note |
|---|---:|---|
| `geography_fit` | 1.00 | NTA所在地 + 制度対象地域 |
| `industry_fit` | 0.85 | CSV signal は強いが業種断定ではない |
| `purpose_fit` | 0.90 | 設備投資 signal と制度目的が近い |
| `entity_type_fit` | 0.80 | 法人確認済み。中小要件は一部未確認 |
| `deadline_fit` | 0.75 | 締切あり、準備期間は短め |

期待 rank:

- `display_score`: 70..85
- `confidence_label`: `supported_with_gaps`
- known gaps: `company_size_unknown`, `tax_treatment_not_assessed`
- 表示: 「設備投資・製造業 signal に基づく確認優先度が高い候補。中小企業者要件と補助対象経費は要確認。」

### 6.2 Example B: 農業CSV + 全国農業制度

入力 signal:

- CSV派生: `肥料費`, `種苗費`, `農薬費`, `経営所得安定対策交付金`。
- 会社属性: 個人/法人が未確定。所在地は都道府県のみ。
- 制度: 農業者向け、全国対象、認定新規就農者または認定農業者要件あり。

期待:

- `industry_fit` は高いが、`certification_fit` は未確認。
- `entity_type_fit` は `unknown` 寄り。
- `display_score` は 60..78 程度に留める。
- known gaps: `required_certification_unverified`, `company_size_unknown`, `implementation_location_unknown`
- `human_review_required=true`

不適切な出力:

- 「認定農業者なので申請できます」
- 「交付金収入があるため採択されやすい」

適切な出力:

- 「農業関連 signal と制度分野は近いが、認定要件と実施場所の確認が必要。」

### 6.3 Example C: 医療CSV + IT導入制度

入力 signal:

- CSV派生: `社会保険診療収入`, `自由診療収入`, `医療材料費`。
- profile: IT投資予定額 300万円。
- 制度: IT導入/業務効率化、対象業種広め、医療法人の扱いに条件あり。

期待:

- `purpose_fit` は profile により高め。
- `industry_fit` は制度側が広いなら中程度。
- `entity_type_fit` は医療法人/個人クリニック条件が未確認なら cap。
- known gaps: `eligibility_clause_missing`, `entity_type_unverified` 相当。
- `display_score`: 55..72

### 6.4 Example D: 会社名のみ + 自治体限定制度

入力 signal:

- 会社名のみ。同名法人が複数。
- 制度: 市区町村限定、事業所所在地が必須。

期待:

- `identity_confidence < 0.60`
- `geography_fit` は capped。
- `display_score <= 60`
- known gaps: `identifier_missing`, `name_only_match`, `implementation_location_unknown`
- next action: 法人番号または所在地の確認。

### 6.5 Example E: 締切超過の高一致制度

入力 signal:

- 地域、業種、目的はすべて高一致。
- 公式 receipt で公募締切が過去日付。

期待:

- relevance は高いが `deadline_fit` と cap で `display_score <= 30`。
- `score_label=not_currently_actionable`
- 表示: 「内容は近いが、確認済み公募期間は終了。次回公募確認または類似制度探索へ回す。」

### 6.6 Example F: no_hit source

入力 signal:

- jGrants query no_hit。
- 自治体公式ページは未接続。

期待:

- 「Jグランツで見つからないため制度なし」と言わない。
- `known_gaps`: `source_not_connected` or `source_blocked`, `program_deadline_unknown`
- `no_hit_interpretation=absence_not_proven`
- next action: 自治体公式サイト/公募要領の接続。

## 7. Calibration process

### 7.1 Golden set

初期 calibration には、採択可否ではなく「人間レビュー時の候補順位妥当性」を使う。

golden set の単位:

- `profile_fixture`: 会社属性、CSV派生 signal、入力 query。
- `program_fixture`: 制度属性、source receipts、known gaps。
- `expected_order_constraints`: A は B より上、C は top から外す、などの相対制約。
- `expected_explanations`: 主要理由/gap の有無。

採択結果を教師ラベルにしない理由:

- 採択は予算、審査、申請品質、競争率、時期、政策裁量に依存する。
- jpcite の役割は公的情報の根拠付き候補提示であり、審査結果予測ではない。

### 7.2 Minimum calibration fixtures

| fixture | must cover |
|---|---|
| `manufacturing_equipment_tokyo` | 製造業、設備投資、地域一致、中小要件 gap |
| `agri_cert_required_national` | 農業 signal、認定要件 gap、全国制度 |
| `medical_it_broad_program` | 業種広め、IT投資 profile、法人種別 gap |
| `name_only_municipality_program` | 同名法人、所在地不明、市区町村限定 |
| `expired_but_relevant_program` | relevance 高、deadline cap |
| `keyword_only_false_positive` | 名称一致のみで下位に落ちる |
| `official_source_missing` | program source missing cap |
| `conflicting_address_sources` | 入力住所とNTA住所の conflict |
| `no_hit_not_absence` | no_hit receipt の安全表示 |
| `stale_official_source` | stale penalty |

### 7.3 Metrics

数値精度より、説明と安全性を優先する。

| metric | target |
|---|---|
| `traceable_feature_rate` | 100% |
| `unsafe_language_count` | 0 |
| `known_gap_action_rate` | 100% for critical gaps |
| `top3_reason_coverage` | 100% |
| `relative_order_pass_rate` | 95%+ on golden constraints |
| `stability_under_irrelevant_feature` | irrelevant feature 追加で top3 不変 |
| `cap_rule_pass_rate` | 100% |

## 8. Implementation acceptance checklist

実装時に満たすべき条件。

- [ ] ranking に使う feature は全て `source_receipt_ids[]` を持つ。
- [ ] receipt がない feature は score に入らない。
- [ ] `display_score`, `relevance_score`, `evidence_confidence` を分離する。
- [ ] `confidence` は採択確率として表示されない。
- [ ] `known_gaps[]` は `next_actions[]` に変換される。
- [ ] `no_hit` は `absence_not_proven` として表示される。
- [ ] 締切超過、地域不一致、公式source欠落の cap が効く。
- [ ] CSV由来 signal は raw明細・摘要・取引先名を露出しない。
- [ ] user asserted、公的確認、機械抽出、no_hit、blocked を区別する。
- [ ] top candidates は正の理由と gap/リスク理由を source-backed に返す。
- [ ] 同点時の stable sort がある。
- [ ] corpus snapshot と checksum を artifact へ含める。
- [ ] 禁止語チェックを artifact text にかける。

## 9. Open design choices

1. Formula A と Formula C のどちらを外部契約にするか。
   - 推奨: 外部は Formula C、内部は Formula A で開始。
2. confirmed mismatch を通常候補から除外するか、低スコアで表示するか。
   - 推奨: `include_out_of_scope=false` では除外、debug/audit では低スコア表示。
3. CSV signal の影響上限。
   - 推奨: CSVだけで `display_score` 70 を超えない。公式制度 source と会社属性 source が揃って初めて 70+。
4. 会社同定の閾値。
   - 推奨: 法人番号/T番号/JCN exact 以外は candidate 扱い。会社固有イベントを強く使う場合は 0.90+ かつ競合なし。
5. 期限不明制度の扱い。
   - 推奨: evergreen 制度なら gap なし。公募型で期限不明なら `program_deadline_unknown`。

## 10. Non-goals

- 採択確率の予測。
- 申請可否の最終判断。
- 税務上の補助金処理、圧縮記帳、課税関係の判断。
- 会計CSVの取引明細レビュー。
- 行政処分や no_hit を使った信用評価。
- 公募要領の法的解釈。

