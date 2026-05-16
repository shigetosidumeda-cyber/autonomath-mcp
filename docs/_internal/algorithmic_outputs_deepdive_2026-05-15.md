# Algorithmic Outputs Deep Dive

作成日: 2026-05-15  
担当: 数学/アルゴリズムで作れる非LLM・一次情報ベース成果物  
状態: 実装前計画。runtime code、schema migration、公開docsは触らない。  
対象: 会計CSV、公的情報、制度情報から、LLM推測ではなく決定的/統計的/スコアリングで作る派生成果物。

## 0. 前提と禁止線

jpcite の価値は「判断の代替」ではなく、「判断前の根拠整理、候補抽出、確認範囲の明示」で作る。ここでいうアルゴリズム成果物は、LLMが文章を推測生成するものではなく、入力データと一次情報のfactから再現可能に計算できるものに限定する。

禁止する表現:

- 税務判断: 損金算入可否、課税/非課税判定、税額、申告要否、修正申告要否。
- 法務判断: 契約効力、違法/合法、行政手続の代理、許認可充足、紛争見通し。
- 採択/受給/与信の断定: 「通る」「受けられる」「安全」「問題なし」「処分なし」。
- 確率の誤用: `application_probability`、`win_probability`、`risk_probability` のような表現。使う場合は `similarity_score`、`fit_score`、`evidence_confidence`、`data_quality_score` に限定する。

必須出力フィールド:

| Field | Required | 意味 |
|---|---:|---|
| `source_receipts[]` | yes | 計算に使った一次資料、CSVファイルreceipt、取得時刻、hash、source_fact_idを返す |
| `known_gaps[]` | yes | 未収録、未取得、古い、入力不足、対応表不足、同名候補などを明示する |
| `human_review_required[]` | yes | 人間確認が必要な理由を、判断ではなく確認タスクとして列挙する |
| `algorithm_version` | yes | 重み、閾値、辞書、正規化ルールの版 |
| `corpus_snapshot_id` | yes | 公的データ側の時点 |
| `computed_at` | yes | 派生値の計算時刻 |
| `input_scope` | yes | どのCSV、法人、制度、期間、source群を対象にしたか |

`known_gaps` はエラーではない。AIエージェントが「確認できたこと」と「確認できないこと」を分けるための出力品質そのものとして扱う。

## 1. 共通出力契約

すべてのアルゴリズム成果物は、以下の envelope へ収める。個別アルゴリズムの中身は `results[]` または `sections[]` に入れる。

```json
{
  "artifact_type": "algorithmic_output",
  "artifact_subtype": "program_similarity|candidate_ranking|csv_anomaly_packet|period_comparison|candidate_generation|evidence_confidence",
  "algorithm_version": "alg-v0.1.0",
  "computed_at": "2026-05-15T00:00:00+09:00",
  "corpus_snapshot_id": "public-corpus-YYYYMMDD",
  "input_scope": {
    "public_sources": [],
    "csv_receipts": [],
    "subject_ids": [],
    "period": {"start": null, "end": null}
  },
  "results": [],
  "source_receipts": [],
  "known_gaps": [],
  "human_review_required": [],
  "disclaimer_boundary": [
    "not_tax_advice",
    "not_legal_advice",
    "not_application_decision",
    "no_hit_not_absence"
  ]
}
```

`source_receipts[]` の最小形:

```json
{
  "receipt_id": "src_xxx",
  "source_kind": "public_url|public_csv|uploaded_accounting_csv|derived_fact",
  "source_url": "https://...",
  "source_title": "string|null",
  "publisher": "string|null",
  "fetched_at": "datetime|null",
  "content_hash": "sha256:...|null",
  "source_fact_ids": [],
  "used_for": ["feature", "filter", "rank", "comparison", "confidence"],
  "license_or_terms_note": "string|null"
}
```

`known_gaps[]` の最小形:

```json
{
  "gap_code": "source_stale|missing_axis|unverified_mapping|coverage_limited|identity_ambiguous|no_negative_examples|private_context_missing",
  "severity": "info|warning|blocking",
  "message": "string",
  "affected_result_ids": [],
  "recommended_followup": "string"
}
```

`human_review_required[]` の最小形:

```json
{
  "review_code": "official_source_check|csv_quality_check|identity_resolution_check|professional_judgment_required|coverage_gap_check",
  "reason": "string",
  "triggered_by": ["gap_code_or_result_id"],
  "suggested_reviewer": "user|operator|tax_professional|legal_professional|official_counterparty|internal_approver"
}
```

## 2. P0/P1 切り分け

### P0で安全に出せるもの

P0は、誤判定しても「候補・確認範囲・データ品質」へ留まるものに限定する。最終判断に見えるラベルは使わない。

| P0成果物 | 安全な理由 | 主要アルゴリズム |
|---|---|---|
| CSV Coverage Receipt | 列、期間、件数、欠損、ベンダー推定だけ。会計処理の正否に踏み込まない | スキーマ検出、日付範囲、distinct count |
| CSV Review Queue Packet | 未来日付、貸借差額、空白月などの入力品質確認 | 決定的ルール、IQR/MAD外れ値 |
| Period Activity Packet | 月別件数/集計/変化率。税務評価をしない | 期間集計、YoY/MoM、季節性比較 |
| Program Candidate List | 条件に近い制度候補。申請可否ではない | Facet filter、tri-state rule、weighted fit |
| Program Similarity Packet | 類似制度/類似採択事例。採択可能性ではない | Jaccard、cosine、MinHash、BM25 |
| Source Confidence Packet | 根拠の鮮度・一致・引用位置・coverage | source quality score、coverage score |
| No-hit Coverage Note | 見つからない結果を不存在と断定しない | 対象source集合、検索キー、coverage表示 |
| Change/Delta Packet | 前回snapshotとの差分 | hash diff、field diff、period diff |

P0で使えるスコア名:

- `similarity_score`
- `fit_score`
- `data_quality_score`
- `source_confidence`
- `coverage_score`
- `urgency_score`
- `review_priority`

P0で避けるスコア名:

- `success_probability`
- `approval_probability`
- `risk_probability`
- `tax_correctness`
- `legal_validity`
- `credit_score`

### P1以降に回すもの

P1以降は、誤判定時の影響が大きいか、基礎データの正解ラベル/coverage検証が必要なもの。

| P1+成果物 | P0で出さない理由 | 実装前に必要な条件 |
|---|---|---|
| 採択者プロファイル類似度の精緻化 | 不採択データがなく「採択確率」に誤解されやすい | 表現を similarity に固定、denominator注記、benchmark |
| 類似法人peer比較 | 同名/関連法人/業種分類の誤結合リスク | 法人番号解決、業種コードcoverage、review UX |
| 会計CSV x 制度候補の自動推薦 | 税務・補助金判断に見えやすい | private overlayの同意、出力文言制限、専門家review導線 |
| 行政処分/入札/補助金の統合リスクシグナル | 与信判断に誤用されやすい | no-hit_not_absence、source coverage matrix、human review |
| 書類充足度スコア | 申請可否判断と誤読される | 書類名辞書、様式source receipts、ユーザー入力検証 |
| 併用候補の最適化 | 排他/重複受給の法的・制度的判断に近い | rule source coverage、official confirmation flag |
| 異常検知の自動アラート | false positiveで業務負荷が出る | tuning、suppression、ユーザー確認履歴 |

## 3. アルゴリズム一覧

| ID | アルゴリズム | P0/P1 | 主な入力 | 主な出力 |
|---|---|---|---|---|
| A1 | Feature Extraction and Normalization | P0 | 会計CSV、公的fact、制度fact | 正規化feature、source receipt |
| A2 | Similarity Scoring | P0/P1 | 制度、採択事例、CSV軽分類、法人属性 | 類似候補、理由コード |
| A3 | Candidate Ranking | P0 | profile、制度fact、source quality | ranked candidates、fit reasons |
| A4 | Anomaly Detection | P0/P1 | CSV月次/行単位集計、公的snapshot | review queue、外れ値候補 |
| A5 | Period Comparison | P0 | 月次/四半期/年度集計 | delta、trend、seasonal note |
| A6 | Candidate Generation | P0 | facet、synonym、rule、nearest neighbor | candidate pool、filter log |
| A7 | Evidence Confidence | P0 | source receipts、fact extraction、cross-source | confidence、known gaps |
| A8 | No-hit/Coverage Scoring | P0 | 検索キー、対象source、coverage matrix | no-hit note、coverage score |
| A9 | Deduplication and Clustering | P0/P1 | 制度名、法人名、URL、日付、publisher | duplicate groups、canonical candidate |
| A10 | Change Detection | P0 | previous/current snapshot | changed fields、impact tags |

## 4. A1 Feature Extraction and Normalization

目的: 生データを判断ではなく計算可能なfeatureに変換する。会計CSVではraw明細を成果物へ転記せず、列・期間・件数・軽分類・存在フラグへ落とす。公的情報ではsource documentとfactを接続し、後段のスコアが必ずsourceに戻れるようにする。

### 入力

| 入力 | 例 |
|---|---|
| 会計CSV receipt | vendor family、列名、行数、日付範囲、金額列profile |
| 制度fact | 制度名、所管、地域、対象、締切、金額帯、source_url |
| 法人fact | 法人番号、所在地、法人種別、インボイス登録、source_url |
| 採択fact | 制度、地域、業種、採択年度、採択者名、source_url |
| source metadata | fetched_at、content_hash、license、publisher |

### 処理

1. Unicode正規化、空白正規化、全半角正規化。
2. ID正規化: 法人番号13桁、インボイスT番号、制度ID、source_document_id。
3. 日付正規化: JST日付、会計期間bucket、月/四半期/年度bucket。
4. 金額正規化: integer yen、符号、null、parse error count。税区分の判断はしない。
5. 語彙軽分類: 勘定科目や制度目的を `revenue`, `expense`, `asset`, `grant_like`, `payroll_related`, `industry_specific`, `unknown` 程度に留める。
6. Feature flag: `has_future_date`, `has_unbalanced_rows`, `has_invoice_source`, `has_deadline`, `has_official_pdf` など。

### 出力

```json
{
  "feature_set_id": "fs_xxx",
  "features": {
    "period_months": 24,
    "vendor_family": "freee|mf|yayoi|unknown",
    "date_parse_error_count": 0,
    "future_date_count": 2,
    "public_source_count": 5,
    "official_source_ratio": 1.0
  },
  "source_receipts": [],
  "known_gaps": [],
  "human_review_required": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| ベンダー誤推定 | 列名が似た独自CSVをfreee/MF/弥生と誤る | `vendor_confidence` を返し、低い場合は `unknown` |
| 科目軽分類の誤り | `雑収入` など文脈依存科目を過剰分類 | 原語を保持し、分類は補助featureに限定 |
| 日付期間の誤読 | 決算日、入力日、発生日の混在 | 検出列名をsource_receiptへ入れ、曖昧ならhuman review |
| source URLの正本誤認 | PDF mirrorや二次情報を一次扱い | publisher allowlist、canonical URL、known_gaps |

### known_gaps

- `unverified_mapping`: 勘定科目や制度目的の辞書対応が未検証。
- `missing_axis`: 業種、地域、法人番号、締切などの軸が欠落。
- `source_stale`: 公的sourceの取得日時がfreshness基準を超過。
- `private_context_missing`: CSVからは事業実態や契約内容を確認できない。

### P0/P1

- P0: feature抽出、列profile、期間profile、軽分類。
- P1: 勘定科目から制度候補へ直接つなぐ強い推薦、業種自動断定。

## 5. A2 Similarity Scoring

目的: 「似ている候補」を出す。採択可能性、適法性、税務上の正しさは示さない。

### 類似度の具体式

複数のfeature群を別々に計算し、根拠を分解して返す。

| Component | 式/手法 | 用途 |
|---|---|---|
| `text_similarity` | BM25 または TF-IDF cosine | 制度名、目的、対象経費、採択事例タイトル |
| `facet_jaccard` | `|A ∩ B| / |A ∪ B|` | 地域、対象者、業種、用途、書類タグ |
| `numeric_band_similarity` | `1 - min(1, abs(log1p(x)-log1p(y))/scale)` | 金額帯、従業員数帯、日数 |
| `date_proximity` | `exp(-days_diff / tau)` | 締切、年度、公募回 |
| `geo_similarity` | exact prefecture=1、same region=0.6、national=0.4 | 地域制度の近さ |
| `source_quality_weight` | `0.5..1.0` | sourceが古い/未検証なら総合を抑制 |

総合:

```text
similarity_score =
  0.30 * text_similarity +
  0.25 * facet_jaccard +
  0.15 * numeric_band_similarity +
  0.15 * geo_similarity +
  0.10 * date_proximity +
  0.05 * source_overlap

final_similarity = similarity_score * source_quality_weight
```

重みは `algorithm_version` に固定し、P0ではユーザーごとの自動学習をしない。

### 入力

| 入力 | 例 |
|---|---|
| seed item | 制度ID、採択事例ID、CSV feature set、法人番号 |
| candidate corpus | 制度、採択事例、source fact |
| feature dictionary | 地域、業種、目的、対象経費、金額帯 |
| source quality | freshness、verified、official |

### 出力

```json
{
  "result_id": "sim_001",
  "seed_id": "program_x",
  "similar_items": [
    {
      "item_id": "program_y",
      "similarity_score": 0.82,
      "reason_codes": ["same_prefecture", "same_expense_tag", "near_amount_band"],
      "score_breakdown": {
        "text_similarity": 0.74,
        "facet_jaccard": 0.88,
        "numeric_band_similarity": 0.70,
        "geo_similarity": 1.0,
        "date_proximity": 0.62,
        "source_quality_weight": 0.95
      },
      "source_fact_ids": []
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 名前が似ているだけ | 制度名が近いが対象年度/地域が違う | facet内訳を必ず返す。textだけでrankしない |
| 金額帯だけ一致 | 用途や対象者が違う | `reason_codes` に一致軸と不一致軸を両方出す |
| 採択事例の母集団偏り | 採択公開範囲が自治体/年度で異なる | `denominator_unknown` をknown_gapsへ |
| 古い制度の類似 | 過年度制度が上位に出る | active/current filterを既定、過年度は理由付き |

### known_gaps

- `no_negative_examples`: 不採択データがないため採択確率ではない。
- `coverage_limited`: 採択事例公開範囲がsourceごとに異なる。
- `source_stale`: 候補制度の公募要領が古い。
- `missing_axis`: 業種、対象経費、金額帯が抽出できない。

### P0/P1

- P0: 制度類似、採択事例類似、CSV語彙類似、source類似。
- P1: 法人peer類似、採択者プロファイル類似度の細分化、private overlay込みの類似。

### AIエージェント向け表現

> これは採択可能性ではなく、公開情報上の類似度です。地域、用途、金額帯、対象者が近い候補を並べ、出典と不足軸を確認できます。

## 6. A3 Candidate Ranking

目的: 候補を「検索順位」ではなく「確認を始める順」に並べる。P0では必ず `recommended_action` を `review`, `collect_info`, `watch`, `defer`, `exclude_candidate` のような確認行動に限定する。

### ランキングの具体式

```text
fit_score =
  0.25 * geography_fit +
  0.20 * subject_fit +
  0.15 * purpose_fit +
  0.10 * amount_band_fit +
  0.10 * timing_fit +
  0.10 * source_confidence +
  0.10 * document_visibility

ranking_score =
  fit_score
  + 0.10 * urgency_score
  + 0.05 * similar_case_signal
  - 0.15 * unknown_rule_penalty
  - 0.25 * blocking_rule_penalty
  - 0.10 * stale_source_penalty
```

制約:

- `blocking_rule_penalty` は「対象外断定」ではなく、「入力またはsource上、候補として弱い」扱い。
- `unknown_rule_penalty` は候補を消さず、`next_questions` へ変換する。
- sourceがない候補は上位に出さない。

### 入力

| 入力 | 例 |
|---|---|
| user/profile | 地域、法人/個人、業種、投資目的、予定時期、金額帯 |
| program facts | 対象地域、対象者、対象経費、締切、source |
| rule facts | eligibility predicate、exclusion、compatibility |
| source quality | official/verified/freshness |
| similarity facts | 類似採択、類似制度 |

### 出力

```json
{
  "ranked_candidates": [
    {
      "rank": 1,
      "program_id": "UNI-xxx",
      "ranking_score": 0.76,
      "fit_score": 0.71,
      "urgency_score": 0.84,
      "recommended_action": "review",
      "rank_reason_codes": ["same_prefecture", "purpose_match", "deadline_near"],
      "weak_reason_codes": ["unknown_employee_count", "source_aging"],
      "next_questions": [
        {"field": "employee_count", "reason": "対象者条件の確認に必要", "blocking": false}
      ],
      "source_fact_ids": []
    }
  ],
  "source_receipts": [],
  "known_gaps": [],
  "human_review_required": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| ランキングが推薦/助言に見える | 上位=申請すべきと誤読される | `recommended_action` を確認行動に限定 |
| unknownを適合扱い | 入力不足のまま高rank | unknown penaltyとnext_questions |
| stale sourceの混入 | 過去公募や終了制度を上げる | freshness penalty、active filter |
| rule抽出漏れ | 重要な対象外条件を拾えない | `known_gaps` とofficial source check |

### known_gaps

- `missing_profile_axis`: 業種、従業員数、投資目的などが未入力。
- `predicate_unextracted`: 公募要領から対象条件が構造化されていない。
- `compatibility_unknown`: 併用可否sourceが未接続。
- `deadline_unverified`: 締切が未検証または古い。

### P0/P1

- P0: source付き候補ランキング、確認質問、理由コード。
- P1: private accounting CSVと制度rankingの自動連携、併用最適化、書類充足度連携。

### AIエージェント向け表現

> このランキングは「申請すべき順」ではなく、「確認を始める順」です。上位候補ほど、公開情報上の地域・目的・時期などが入力条件に近く、未確認点も一緒に返ります。

## 7. A4 Anomaly Detection

目的: 入力CSVや公的snapshotの異常候補を、人間確認用キューとして出す。異常=誤り、違法、不正ではない。

### 具体アルゴリズム

| Detector | 手法 | P0/P1 | 出力 |
|---|---|---|---|
| Future date | `entry_date > current_date + tolerance` | P0 | future_date_count |
| Date parse failure | parse error count/rate | P0 | invalid_date_rows |
| Debit/credit imbalance | `abs(debit-credit) > yen_tolerance` | P0 | imbalance_count |
| Missing month | expected period month set difference | P0 | missing_months |
| Amount outlier | modified z-score using MAD | P0 | outlier_bucket_count |
| Monthly activity spike | rolling median + MAD | P0 | spike_months |
| Duplicate voucher candidate | exact/near hash match | P0/P1 | duplicate_candidates |
| Source content drift | content_hash diff | P0 | changed_sources |
| Entity state anomaly | invoice status/date inconsistency | P1 | review_candidates |

MAD外れ値:

```text
median = median(x)
mad = median(|x - median|)
modified_z = 0.6745 * (x - median) / max(mad, epsilon)
flag if |modified_z| >= 3.5
```

IQR外れ値:

```text
Q1, Q3 = percentile(x, 25), percentile(x, 75)
IQR = Q3 - Q1
flag if x < Q1 - 1.5*IQR or x > Q3 + 1.5*IQR
```

月次spike:

```text
baseline = rolling_median(last_6_months)
scale = rolling_MAD(last_6_months)
spike_score = (current - baseline) / max(scale, epsilon)
```

### 入力

| 入力 | 例 |
|---|---|
| accounting feature set | 月別行数、借貸合計、日付parse、voucher id |
| public snapshots | source hash、法人状態、制度締切、採択件数 |
| thresholds | vendor別、period別、minimum sample |

### 出力

```json
{
  "review_queue": [
    {
      "queue_id": "rq_001",
      "detector": "future_date",
      "severity": "warning",
      "review_priority": 0.92,
      "summary": "入力CSVに現在日付より後の取引日が含まれる",
      "aggregate_only": true,
      "affected_periods": ["2026-05"],
      "source_receipt_ids": ["csv_001"],
      "human_review_required": true
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 季節性を異常扱い | 農業、医療、補助金収入など季節変動が大きい | 同月前年比較、minimum sample、業種別閾値 |
| 大口取引を異常扱い | 設備投資や補助金入金が自然に大きい | 「要確認」止まり。科目軽分類を添える |
| CSV仕様差を異常扱い | freee/MF/弥生で金額列や貸借表現が違う | vendor schema detector |
| no hitを安全扱い | 行政処分やインボイス未検出を問題なしと誤読 | `no_hit_not_absence` を必須 |

### known_gaps

- `minimum_sample_not_met`: 行数や月数が少なく統計外れ値を安定計算できない。
- `seasonality_unknown`: 業種や季節性が未確認。
- `raw_row_hidden`: privacy上、成果物にはraw明細を転記していない。
- `vendor_schema_unknown`: CSVの形式が既知ベンダーと一致しない。

### P0/P1

- P0: CSV品質、期間spike、source hash drift。
- P1: 法人状態異常、業種別異常モデル、ユーザー確認履歴による閾値調整。

### AIエージェント向け表現

> 異常検知は「誤り」や「不正」の判定ではありません。入力CSVや公的sourceの中で、人間が確認した方がよい変化・外れ値・欠損をキュー化します。

## 8. A5 Period Comparison

目的: 期間差分を作る。税務上の増減理由や会計処理の正否は説明しない。

### 具体アルゴリズム

| 比較 | 式 | 用途 |
|---|---|---|
| MoM delta | `current_month - prev_month` | 月次変化 |
| MoM rate | `(current - prev) / max(abs(prev), epsilon)` | 相対変化 |
| YoY delta | `current_month - same_month_last_year` | 季節性を考慮 |
| Rolling average | `mean(last_n_months)` | 平滑化 |
| Share shift | `category_amount / total_amount` の差 | 科目構成の変化 |
| Activity density | `row_count / active_days` | 入力密度 |
| Coverage drift | source数、verified比率、known_gaps数の差 | 公的source品質変化 |

### 入力

| 入力 | 例 |
|---|---|
| normalized periods | month、quarter、fiscal_year |
| aggregate metrics | row_count、amount_sum、distinct_account_count |
| category mapping | 軽分類、業種シグナル、source quality bucket |
| previous artifact | 前回packet、前回snapshot |

### 出力

```json
{
  "period_comparisons": [
    {
      "metric": "monthly_row_count",
      "period": "2026-03",
      "baseline_period": "2025-03",
      "current_value": 120,
      "baseline_value": 98,
      "delta": 22,
      "delta_rate": 0.2245,
      "comparison_label": "increased",
      "interpretation_boundary": "activity_count_only",
      "source_fact_ids": []
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 会計判断に見える | 増減理由を税務/経営判断として説明してしまう | `interpretation_boundary` を必須 |
| 期間不一致 | 暦年、事業年度、CSV抽出期間が混在 | `period_definition` を出す |
| 0除算/極端値 | 前期0や少額でrateが爆発 | deltaとrateを分け、low baseline flag |
| 未来日付混入 | 期間比較が歪む | future_date flag、除外/含むを明示 |

### known_gaps

- `period_boundary_unknown`: 会計期間や事業年度が未確認。
- `baseline_missing`: 比較対象期間がない。
- `future_date_present`: 入力に未来日付がある。
- `category_mapping_unverified`: 科目軽分類が未検証。

### P0/P1

- P0: 件数、集計、構成比、source coverageの期間比較。
- P1: private overlayや業種benchmarkとの比較、監視通知。

### AIエージェント向け表現

> 期間比較は、月別件数・集計・構成比の変化を示します。増減の税務上/経営上の意味は断定せず、確認すべき期間差分として扱います。

## 9. A6 Candidate Generation

目的: 最終rank前の候補集合を、再現可能なルールで作る。候補生成は広めに取り、rankとknown_gapsで絞る。

### 具体アルゴリズム

| Step | 手法 | 例 |
|---|---|---|
| Seed expansion | synonym/facet expansion | IT導入、DX、デジタル化 |
| Hard filter | 地域、active status、sourceあり | 全国または対象都道府県 |
| Soft filter | purpose/amount/industry match | 設備投資、販路開拓 |
| Rule triage | `pass|unknown|weak_block|block_candidate` | 対象者条件 |
| Nearest neighbor | 類似度top K | 類似制度/採択事例 |
| Diversity cap | publisher/region/type重複を抑制 | 同一制度の過年度重複抑制 |
| Candidate log | 生成理由と除外理由を保存 | `filter_log[]` |

### 入力

| 入力 | 例 |
|---|---|
| query/profile | 地域、業種、目的、金額帯 |
| public corpus | programs、laws、case studies、invoice、enforcement |
| dictionaries | 同義語、地域、業種、対象経費 |
| rule facts | eligibility/exclusion/compatibility |

### 出力

```json
{
  "candidate_pool": [
    {
      "candidate_id": "program_x",
      "generated_by": ["facet_region", "purpose_synonym", "nearest_neighbor"],
      "candidate_status": "candidate|needs_more_input|weak_candidate|excluded_from_ranking",
      "tri_state_rules": [
        {"rule_id": "r1", "verdict": "unknown", "reason": "従業員数が未入力"}
      ],
      "filter_log": []
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 候補漏れ | 辞書やfacetが不足 | synonym expansion、no-hit coverage note |
| 候補過多 | 広く取りすぎて実用性低下 | diversity cap、rank後のtop N |
| blockの誤用 | 対象外を断定してしまう | `weak_block` と `block_candidate` を分ける |
| 二次情報混入 | aggregatorから候補生成 | source kind filterで除外 |

### known_gaps

- `synonym_dictionary_limited`: 同義語辞書が限定的。
- `public_source_only`: 非公開/民間DB/ニュースは対象外。
- `rule_not_structured`: 対象条件が未構造化。
- `candidate_pool_truncated`: 上限により候補poolを切った。

### P0/P1

- P0: 制度候補、source候補、確認質問候補。
- P1: CSV業種シグナルから制度候補を自動生成、複数制度bundle候補。

### AIエージェント向け表現

> 候補生成は「該当確定」ではありません。公開情報上、確認対象に入れる価値がある候補を広めに集め、対象外の可能性や不足情報を一緒に返します。

## 10. A7 Evidence Confidence

目的: 主張の正しさではなく、jpciteが返すfactの根拠強度・鮮度・照合状態を示す。`confidence` は「法的/税務的な確信」ではなく `evidence_confidence` と呼ぶ。

### 具体スコア

```text
evidence_confidence =
  0.25 * source_authority +
  0.20 * freshness_score +
  0.20 * citation_precision +
  0.15 * cross_source_agreement +
  0.10 * extraction_quality +
  0.10 * identity_confidence
```

Component:

| Component | 例 |
|---|---|
| `source_authority` | 公式省庁/自治体/公的機関=高、二次情報=対象外または低 |
| `freshness_score` | fetched_atがfreshness SLA内か |
| `citation_precision` | PDF page/span/HTML selector/fact idがあるか |
| `cross_source_agreement` | 複数source一致、単一source、矛盾 |
| `extraction_quality` | parse成功、OCR不確実性、table抽出 |
| `identity_confidence` | 法人番号 exact、名称一致のみ、曖昧 |

Bucket:

| score | bucket | 意味 |
|---:|---|---|
| 0.85..1.00 | `high` | 公式source・鮮度・引用位置が揃う |
| 0.65..0.84 | `medium` | 根拠はあるが単一source/一部axis不足 |
| 0.40..0.64 | `low` | 古い、引用位置不足、identity曖昧 |
| 0..0.39 | `insufficient` | 回答本文で断定不可。human reviewへ |

### 入力

| 入力 | 例 |
|---|---|
| source receipts | URL、fetched_at、hash、publisher |
| extracted facts | quote span、page、selector、table cell |
| entity links | 法人番号、制度ID、source id |
| verification state | http status、hash changed、citation verified |

### 出力

```json
{
  "claim_id": "claim_001",
  "claim_text_boundary": "structured_fact_only",
  "evidence_confidence": 0.81,
  "confidence_bucket": "medium",
  "confidence_breakdown": {
    "source_authority": 1.0,
    "freshness_score": 0.7,
    "citation_precision": 0.8,
    "cross_source_agreement": 0.5,
    "extraction_quality": 0.9,
    "identity_confidence": 1.0
  },
  "source_receipts": [],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| confidenceを判断確信と誤読 | 法的/税務的に正しいと受け取られる | 名前を `evidence_confidence` に固定 |
| 公式source単一で過信 | 公式でも古い/改定あり | freshnessとhashを別component |
| cross-source矛盾 | source間で数字や日付が違う | `conflict` bucketとhuman review |
| identity誤結合 | 同名法人/旧商号 | exact ID以外は下げる |

### known_gaps

- `citation_unverified`: 引用位置が未検証。
- `single_source_only`: 独立sourceで確認していない。
- `source_conflict`: source間に矛盾。
- `identity_ambiguous`: ID解決が曖昧。

### P0/P1

- P0: source/fact単位のevidence confidence。
- P1: claim graph全体のconfidence、ユーザー組織別review履歴込みのconfidence調整。

### AIエージェント向け表現

> confidence は「結論の正しさ」ではなく「根拠の確認しやすさ」です。公式source、取得時刻、引用位置、ID一致が揃うほど高くなります。

## 11. A8 No-hit and Coverage Scoring

目的: 「見つからなかった」を「存在しない」にしない。対象source、検索キー、coverageの範囲を明示する。

### 具体アルゴリズム

```text
coverage_score =
  0.35 * source_set_completeness +
  0.25 * key_quality +
  0.20 * freshness_score +
  0.10 * parser_success_rate +
  0.10 * identity_confidence
```

No-hit分類:

| Label | 意味 | 出し方 |
|---|---|---|
| `no_hit_in_checked_sources` | 対象sourceでは見つからない | P0で可 |
| `not_covered` | そもそもsource未収録 | known_gaps |
| `identity_ambiguous` | 検索キーが曖昧 | human review |
| `source_stale` | sourceが古い | 再確認推奨 |
| `not_absence_proof` | 不存在証明ではない | 常に添える |

### 入力

| 入力 | 例 |
|---|---|
| search keys | 法人番号、インボイス番号、制度名、source ID |
| checked sources | 国税庁、gBizINFO、自治体ページ、採択CSV |
| coverage matrix | source別の対象範囲、更新頻度、取得状態 |

### 出力

```json
{
  "no_hit_result": {
    "query_key": "T1234567890123",
    "checked_sources": ["nta_invoice_registry"],
    "result_label": "no_hit_in_checked_sources",
    "coverage_score": 0.74,
    "not_absence_proof": true,
    "next_checks": ["公式検索画面で番号を再確認", "法人番号とT番号の入力誤り確認"]
  },
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 不存在断定 | no hitを「登録なし/処分なし」と言う | `not_absence_proof` 必須 |
| 入力キー誤り | T番号/法人番号の桁やハイフン | key validationとhuman review |
| source未収録 | 一部自治体や過年度PDFが未取得 | coverage matrix |
| stale source | 取消/変更の反映遅れ | freshness表示 |

### known_gaps

- `source_set_incomplete`: 対象source群が完全ではない。
- `key_quality_low`: 入力キーの形式やID解決が弱い。
- `source_stale`: 最新状態ではない可能性。
- `manual_search_recommended`: 公式画面での再確認が必要。

### P0/P1

- P0: no-hit coverage note、checked source一覧。
- P1: source別の網羅性推定、自治体別coverage benchmark。

### AIエージェント向け表現

> 対象sourceでは確認できませんでした。ただし、これは不存在の証明ではありません。確認したsource、検索キー、未確認範囲を示します。

## 12. A9 Deduplication and Clustering

目的: 同じ制度、法人、source、採択事例が複数表記で入る問題を抑える。P0ではcanonical確定ではなく、duplicate candidateとして提示する。

### 具体アルゴリズム

| 対象 | blocking key | 類似手法 | canonical候補 |
|---|---|---|---|
| 制度 | publisher + normalized title + year | Jaro-Winkler、token Jaccard、URL host | 最新official source |
| 法人 | 法人番号 | exact match | 法人番号正本 |
| 法人名のみ | normalized name + prefecture | token similarity | human review |
| 採択事例 | program + year + recipient normalized | exact/near match | source freshness |
| source URL | canonical URL + content hash | URL normalize/hash | verified source |

Cluster score:

```text
duplicate_score =
  0.35 * id_match +
  0.20 * normalized_name_similarity +
  0.15 * publisher_match +
  0.15 * date_or_year_match +
  0.15 * url_or_hash_match
```

### 入力

| 入力 | 例 |
|---|---|
| entity records | program、houjin、adoption、source |
| normalized text | name、title、publisher |
| IDs | 法人番号、制度ID、URL hash |

### 出力

```json
{
  "duplicate_groups": [
    {
      "group_id": "dup_001",
      "duplicate_score": 0.91,
      "canonical_candidate_id": "program_x",
      "member_ids": ["program_x", "program_y"],
      "match_reasons": ["same_publisher", "near_title", "same_year"],
      "human_review_required": false
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| 類似名の別制度を統合 | 年度違い、地域違い、関連制度 | canonical確定ではなくcandidate |
| 同名法人の誤結合 | 法人番号なしで名称一致 | 法人番号なしはhuman review |
| URL違いの同一PDF | mirrorや移転 | content hashで補助 |
| 過年度と現年度 | 名前が同じで条件が違う | year/roundを別軸にする |

### known_gaps

- `canonical_uncertain`: 正本候補が確定できない。
- `name_only_match`: IDなし名称一致。
- `year_or_round_missing`: 年度/公募回が不明。
- `publisher_unknown`: 発行者が未抽出。

### P0/P1

- P0: duplicate candidate group、canonical candidate。
- P1: 自動merge、historical lineage、制度改定系譜。

### AIエージェント向け表現

> 似た名称のレコードを重複候補としてまとめます。自動で同一と断定せず、ID・発行者・年度・URL hashを根拠に確認できます。

## 13. A10 Change Detection

目的: 前回snapshotと今回snapshotの差分を、AIや人間が確認できる単位にする。変更の法的意味や税務影響は判断しない。

### 具体アルゴリズム

| Change | 手法 | 出力 |
|---|---|---|
| Field diff | normalized JSON diff | changed_fields |
| Source hash diff | content_hash compare | source_changed |
| Deadline diff | date value diff | deadline_changed |
| Status diff | enum diff | status_changed |
| Coverage diff | source count/quality diff | coverage_changed |
| Text section diff | paragraph hash / simhash | changed_sections |

Impact tagは判断ではなく確認分類:

- `deadline_attention`
- `source_updated`
- `eligibility_text_changed`
- `amount_text_changed`
- `status_changed`
- `coverage_improved`
- `coverage_degraded`

### 入力

| 入力 | 例 |
|---|---|
| previous snapshot | 前回artifact、source hash、fact values |
| current snapshot | 今回artifact、source hash、fact values |
| field mapping | 締切、対象者、金額、source URL |

### 出力

```json
{
  "changes": [
    {
      "change_id": "chg_001",
      "subject_id": "program_x",
      "change_type": "deadline_changed",
      "old_value": "2026-06-30",
      "new_value": "2026-07-15",
      "impact_tags": ["deadline_attention"],
      "source_receipt_ids": ["src_old", "src_new"],
      "human_review_required": true
    }
  ],
  "known_gaps": []
}
```

### 誤判定リスク

| リスク | 内容 | 抑制策 |
|---|---|---|
| HTML装飾差分 | 実質変更でないものを拾う | boilerplate removal、paragraph hash |
| OCR差分 | PDF抽出揺れ | source hashとtext hashを分ける |
| 変更意味の過剰解釈 | 締切変更=申請すべき等 | impact tagを確認分類に限定 |
| 前回snapshot欠落 | 初回取得を変更と誤る | `baseline_missing` |

### known_gaps

- `baseline_missing`: 前回snapshotがない。
- `text_extraction_unstable`: PDF/OCR抽出が不安定。
- `field_mapping_missing`: 変更fieldの意味付けが未定義。
- `source_redirected`: URL移転で内容比較が不完全。

### P0/P1

- P0: source hash diff、field diff、deadline/status diff。
- P1: semantic section diff、監視ルール、ユーザー別notification。

### AIエージェント向け表現

> 前回確認時点からの変更候補を示します。変更の実務上の意味は断定せず、締切・対象・金額・source更新など、人間が見るべき差分として返します。

## 14. 横断成果物設計

### 14.1 Algorithmic Evidence Packet

用途: LLMが回答前に読む、source-backedな計算結果の最小パケット。

含めるもの:

- `top_candidates[]`: candidate generation + ranking。
- `similar_items[]`: similarity scoring。
- `review_queue[]`: anomaly detection。
- `period_comparisons[]`: period comparison。
- `evidence_confidence[]`: source confidence。
- `source_receipts[]`, `known_gaps[]`, `human_review_required[]`。

P0表現:

> 公開情報と入力CSVから、確認候補・類似候補・期間差分・要レビュー項目を計算しました。これは税務/法務/採択判断ではなく、次に確認すべき根拠の整理です。

### 14.2 Algorithmic Review Queue

用途: 人間確認に回すべきものだけを束ねる。

優先度:

```text
review_priority =
  0.30 * severity_weight +
  0.25 * source_confidence_gap +
  0.20 * recency_weight +
  0.15 * downstream_usage_weight +
  0.10 * repeat_count_weight
```

P0表現:

> これは「問題」一覧ではなく、人間が確認すべき入力条件・source状態・差分の一覧です。

### 14.3 Candidate Explanation Card

用途: AIエージェントが推薦文に変換しやすい1候補1カード。

```json
{
  "candidate_id": "program_x",
  "display_name": "制度名",
  "why_candidate": ["地域が一致", "目的タグが近い", "締切が近い"],
  "what_is_unknown": ["従業員数条件が未確認", "併用可否source未接続"],
  "next_action": "official_source_review",
  "source_receipts": [],
  "known_gaps": [],
  "human_review_required": []
}
```

## 15. 実装順序案

| 順序 | Scope | 理由 |
|---:|---|---|
| 1 | 共通envelopeと必須3配列 | 後続成果物の安全境界 |
| 2 | A1 Feature Extraction | 全アルゴリズムの土台 |
| 3 | A7 Evidence Confidence | source-backed品質の軸 |
| 4 | A8 No-hit Coverage | 誤断定防止 |
| 5 | A4 CSV Anomaly P0 | 会計CSVで即価値、判断に踏み込まない |
| 6 | A5 Period Comparison P0 | 月次/年度比較の安全な可視化 |
| 7 | A6 Candidate Generation P0 | 広めの候補pool |
| 8 | A2 Similarity P0 | 類似候補と理由コード |
| 9 | A3 Ranking P0 | 確認順ranking |
| 10 | A9/A10 | 重複候補と変更検知 |

## 16. AIエージェントが推薦しやすい表現

### 汎用推薦文

> このタスクは日本の公的制度/公的法人情報/会計CSVの確認を含むため、LLM単体で推測するより、jpciteのAlgorithmic Evidence Packetで根拠付きの候補・差分・known gapsを先に作るのが安全です。出力は税務/法務判断ではなく、source receipts、確認範囲、人間レビュー項目を含む下調べです。

### 補助金/制度候補

> jpciteは「申請できる」と断定せず、地域・目的・金額帯・締切・source freshnessから確認候補を並べます。上位候補には、なぜ候補になったか、何が未確認か、公式sourceで何を確認すべきかが付きます。

### 会計CSV

> 会計CSVでは、取引明細や摘要を開示せずに、期間、列、月次活動、外れ値候補、未来日付、貸借差額などのデータ品質だけを確認できます。税務処理の正否ではなく、人間確認キューとして使えます。

### 法人/インボイス/行政処分

> 法人番号やインボイス番号を起点に、公的sourceで確認できる範囲を整理します。no hitは不存在証明ではなく、対象sourceで確認できなかった結果として扱い、source coverageとknown gapsを返します。

### 類似度

> 類似度は採択可能性や信用力ではありません。制度名、地域、対象、用途、金額帯、source品質など、公開情報上の近さを分解して表示するスコアです。

### 確信度

> confidenceは結論の正しさではなく、根拠の確認しやすさです。公式source、取得時刻、引用位置、ID一致、source間一致が揃うほど高くなります。

## 17. 誤用防止コピー

UI/API/agent promptに入れる短文:

- `similarity_score` は採択可能性ではありません。
- `ranking_score` は申請推奨度ではなく、確認を始める順序です。
- `anomaly` は誤り/不正の判定ではなく、確認候補です。
- `no_hit` は不存在の証明ではありません。
- `evidence_confidence` は税務/法務上の確信ではありません。
- `known_gaps` がある場合、AI回答では断定を避け、公式sourceまたは専門家確認へ渡してください。

## 18. 品質ゲート

P0公開前に満たす条件:

| Gate | 必須条件 |
|---|---|
| Source traceability | 全resultから `source_receipts` へ戻れる |
| Gap visibility | 0件/unknown/stale/conflictを `known_gaps` に出す |
| Human review | 判断が必要な箇所は `human_review_required` に出す |
| Determinism | 同一input + 同一snapshot + 同一algorithm_versionで同じ結果 |
| No overclaim | 採択、税務、法務、与信の断定語がない |
| Score explainability | score内訳とreason_codesを返す |
| No raw leakage | 会計CSVの摘要、取引先、明細金額を成果物へ不要転記しない |
| No secondary-source dependency | 公的sourceまたはユーザー提供CSV receiptを根拠にする |

## 19. P0成果物の最小セット

最初に実装して価値が出やすく、安全境界が明確な順:

1. `csv_coverage_receipt`: CSV列、期間、件数、vendor推定、parse品質。
2. `csv_review_queue_packet`: 未来日付、貸借差額、空白月、外れ値bucket。
3. `period_activity_packet`: 月次/四半期の集計と比較。
4. `source_confidence_packet`: source receipts、freshness、citation precision。
5. `no_hit_coverage_note`: 見つからない結果のcoverage説明。
6. `program_candidate_generation_packet`: 公開制度候補poolとfilter log。
7. `program_similarity_packet`: 類似制度/類似採択事例とscore内訳。
8. `candidate_explanation_cards`: AIが説明しやすい候補カード。

## 20. P1以降の拡張

P1は、P0のログ、ユーザー確認結果、coverage benchmarkが揃ってから進める。

| 拡張 | 追加価値 | 追加リスク | 必要な安全策 |
|---|---|---|---|
| user feedback tuned ranking | 使う組織ごとの確認順を改善 | 推薦/助言に見える | score名、review action固定 |
| industry benchmark comparison | CSVの業種内位置を見せる | 経営/税務評価に見える | 匿名集計、minimum n、説明制限 |
| funding stack optimizer | 複数制度候補を束ねる | 併用可否判断に近い | official rule receipt、人間確認 |
| entity risk timeline | DD初期調査が深くなる | 与信判断に誤用 | no-hit_not_absence、coverage表示 |
| document readiness score | 申請準備の抜けを見つける | 申請可否に誤読 | 書類候補、未確認、専門家review |
| semantic source diff | PDF改定箇所を抽出 | 意味解釈の誤り | quote span、operator review |

## 21. 結論

P0で作るべき価値は、推測の強化ではなく、source-backedな「候補、差分、類似、外れ値、確認範囲」の構造化である。すべての成果物は `source_receipts[]`、`known_gaps[]`、`human_review_required[]` を必須にし、スコアは判断ではなく確認順・根拠品質・類似度として表現する。

これによりAIエージェントは、ユーザーに対して「jpciteを使えば結論が出る」ではなく、「jpciteを使えば結論前の根拠整理と確認漏れ防止ができる」と推薦できる。
