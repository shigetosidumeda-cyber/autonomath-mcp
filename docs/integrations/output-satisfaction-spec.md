# jpcite Output Satisfaction Spec

更新日: 2026-05-06  
目的: 無料3回/日で通常品質のアウトプットを体験してもらい、「候補一覧」ではなく「そのまま次の業務に使える根拠付き完成物」として満足されるための出力標準を定義する。

## 1. Scope

この仕様は価格変更ではない。`deep-paid-output-and-data-foundation-plan.md` の Evidence Packet / artifact / known_gaps / audit-ready output の考え方に合わせ、無料枠と通常利用でユーザーが受け取るアウトプットの品質と見せ方を揃える。

対象は次の出力体験。

| 対象 | 方針 |
|---|---|
| Free 3/day | 1日3回まで、通常品質のアウトプットをそのまま返す |
| 通常利用 | 同じ出力構造・同じ品質ゲートで返す |
| Deep Pack / Monitoring | 本仕様を土台に、対象範囲・保存・差分・監査を厚くする |

非対象は次の通り。

| 非対象 | 理由 |
|---|---|
| unit単価、課金体系、税表示の変更 | 本仕様は価格ではなく満足度を扱う |
| 有料誘導のための一部非表示 | 無料体験の信頼を下げるため禁止 |
| 税務・法律・申請可否の最終判断 | jpciteは公開情報の検索・整理と根拠提示を扱う |

## 2. Core Decision

Free 3/day は「低品質な試供品」ではなく、通常品質の成功体験にする。

| 原則 | 内容 |
|---|---|
| 通常品質 | source_url、source_fetched_at、known_gaps、確認事項、disclaimerを含む |
| 非マスク | 根拠URL、候補名、重要な注意点、known_gapsを隠さない |
| 数量制限 | 無料枠の制限は回数・対象範囲・保存期間で表現し、本文の品質を落とさない |
| 完成物優先 | 検索結果の羅列ではなく、ユーザーが次に使えるメモ・表・チェックリストに変換する |
| 正直な境界 | 「該当なし」ではなく「収録範囲では未検出」「確認不足」を明示する |

無料で隠してはいけないもの。

| 隠してはいけない要素 | 理由 |
|---|---|
| 公式URL・取得日時 | 体験価値の中核が根拠確認だから |
| 候補名・制度名・法人名 | ユーザーが有用性を判断できなくなるから |
| NG条件・不足情報 | 失敗回避が満足度に直結するから |
| known_gaps | jpciteの誠実さと確認範囲を示すから |
| 次に聞くべき質問 | ユーザーの次作業を減らすから |

無料枠で差をつけてよいもの。

| 差をつけてよい要素 | 許容される制限 |
|---|---|
| 回数 | 3 successful outputs/day |
| 対象範囲 | 1テーマ、1法人、1地域、または少数候補に絞る |
| 保存 | 長期保存・監視・再配信は通常利用以上へ寄せる |
| 深掘り | 横断DD、月次差分、private overlayは通常利用以上へ寄せる |
| バッチ | 複数社・複数地域の一括生成は通常利用以上へ寄せる |

## 3. Standard Output Structure

Free 3/day と通常利用の基本アウトプットは、同じ順序・同じ意味で返す。

```text
1. 結論候補
2. decision_insights
3. cross_source_signals
4. ユーザーに使える形の完成物
5. 根拠一覧
6. next_actions
7. known_gaps / 確認範囲
8. 免責と判断境界
```

### 3.1 Section Requirements

| セクション | 必須内容 | 満足条件 |
|---|---|---|
| 結論候補 | 候補、優先順位、対象外候補があれば理由 | 最初の30秒で使えるか判断できる |
| decision_insights | 所在地、業種、時期、金額、法人属性、制度条件、リスク兆候から作った判断材料 | 単なる検索一致ではなく「なぜ今見るべきか/見送るべきか」が見える |
| cross_source_signals | 複数データ基盤を付き合わせた一致、矛盾、未確認、差分 | jpcite内の既存データを結合した価値が見える |
| 完成物 | 顧問先文面、申請前チェック、稟議注記、DD質問など | コピーして次の業務に移れる |
| 根拠一覧 | source_url、source_fetched_at、publisher、verification_status | 一次資料へ戻れる |
| next_actions | 今日確認すること、顧客へ聞くこと、窓口や専門家へ確認すること | 次の作業が具体化される |
| known_gaps | 未確認、低信頼、古い出典、corpus外の可能性 | 確認範囲が透明になる |
| 免責と判断境界 | 公開情報整理であり、最終判断ではない旨 | 過剰断定を避ける |

### 3.2 Minimum JSON Shape

UI向けでもAPI向けでも、内部表現は以下のキーを落とさない。値がない場合は `null` と `known_gaps` で説明する。

```json
{
  "output_id": "out_...",
  "generated_at": "2026-05-06T00:00:00Z",
  "query_summary": "...",
  "quality_tier": "A",
  "free_trial_applied": true,
  "artifact_type": "application_kit",
  "answer": {
    "headline": "...",
    "candidate_summary": [],
    "decision_insights": [
      {
        "insight_id": "di_...",
        "verdict": "propose_now",
        "summary": "...",
        "reason_codes": ["deadline_near", "strong_region_industry_fit"],
        "evidence_item_ids": ["epi_..."],
        "source_fact_ids": ["fact_..."],
        "confidence": "medium",
        "known_gaps": []
      }
    ],
    "cross_source_signals": [
      {
        "signal_id": "css_...",
        "signal_type": "deadline_plus_eligibility",
        "summary": "...",
        "agreement": "agree",
        "effect": "raise_priority",
        "source_refs": ["src_..."],
        "known_gaps": []
      }
    ],
    "usable_artifact": [],
    "next_actions": [
      {
        "action_id": "act_...",
        "action_type": "ask_customer",
        "priority": "today",
        "owner_hint": "advisor",
        "text": "...",
        "reason": "...",
        "depends_on": ["di_..."],
        "source_refs": ["src_..."]
      }
    ]
  },
  "sources": [
    {
      "source_id": "src_...",
      "title": "...",
      "publisher": "...",
      "source_url": "https://...",
      "source_fetched_at": "2026-05-06T00:00:00Z",
      "verification_status": "verified"
    }
  ],
  "known_gaps": [
    {
      "gap_code": "source_stale",
      "scope": "deadline",
      "user_message": "...",
      "impact": "deadline claims require human review",
      "blocks_claims": ["application_deadline_is_current"],
      "suggested_resolution": "公式ページまたは窓口で締切を確認する",
      "source_refs": ["src_..."]
    }
  ],
  "_disclaimer": {
    "information_only": true,
    "not_tax_or_legal_advice": true,
    "not_application_agency": true
  }
}
```

### 3.3 Actionable Intelligence Blocks

Evidence Packet と AI 向け回答は、同じ意味のブロックを持つ。UI 表示名は日本語にしてよいが、API/agent 連携では次のキーを落とさない。

| Block | 目的 | Evidence Packetでの位置 | AI向け回答での表示 |
|---|---|---|---|
| `decision_insights` | 候補の提案、見送り、要確認を理由コードと根拠factで説明する | `answer.decision_insights[]` または packet の `answer_intelligence.decision_insights[]` | 「判断材料」として結論直後に3件まで表示 |
| `cross_source_signals` | 制度、法人、締切、採択、処分、インボイス、様式、source freshnessを付き合わせた一致/矛盾/差分を出す | `answer.cross_source_signals[]` または packet の `answer_intelligence.cross_source_signals[]` | 「複数データの手掛かり」として、根拠sourceと一緒に表示 |
| `next_actions` | 追加入力、顧客質問、窓口確認、書類収集、監視、artifact生成を行動単位にする | `answer.next_actions[]` または packet の `answer_intelligence.next_actions[]` | 「次にやること」として、今日/今週/後でに分けて表示 |
| `known_gaps` | 未確認、古い、矛盾、corpus外、引用未検証を確認範囲として見せる | top-level `known_gaps[]` と `quality.known_gaps[]` | 「確認できていない範囲」として必ず表示 |

実レスポンスの Evidence Packet は、JSON 出力時に top-level `decision_insights` を返す。これは最終回答ではなく、AI agent が回答前に見るべき根拠、次の確認、根拠不足を短く説明する補助ブロックである。

```json
{
  "packet_id": "evp_example",
  "records": [],
  "quality": {
    "freshness_bucket": "current",
    "known_gaps": []
  },
  "verification": {
    "freshness_endpoint": "/v1/meta/freshness"
  },
  "evidence_value": {
    "source_linked_records": 1,
    "fact_provenance_coverage_pct_avg": 0.86
  },
  "decision_insights": {
    "schema_version": "v1",
    "generated_from": [
      "records",
      "quality",
      "verification",
      "evidence_value",
      "corpus_snapshot_id"
    ],
    "why_review": [
      {
        "signal": "source_traceability",
        "message_ja": "出典URLと取得・確認日時付きのレコードがあります。回答では制度名、出典URL、取得日を併記できます。",
        "basis": ["records[].source_url", "records[].source_fetched_at"]
      }
    ],
    "next_checks": [
      {
        "signal": "source_recheck",
        "message_ja": "回答前に records[].source_url と取得・確認日時で最新の公式情報を確認してください。",
        "basis": ["records[].source_url", "records[].source_fetched_at"]
      }
    ],
    "evidence_gaps": []
  }
}
```

Artifact/AI回答用の `decision_insights[]` は、`program_decision_layer`、`corporate_risk_layer`、`source_quality_layer`、`document_requirement_layer`、`monitoring_delta_layer` など既存データ基盤の結合結果から作る。LLMの推測だけで `verdict` を作らない。Evidence Packet の top-level `decision_insights` は同じ判断支援の系統だが、`verdict` 配列ではなく `why_review` / `next_checks` / `evidence_gaps` の実レスポンス形状を優先する。

`cross_source_signals` は、単一レコードの表示ではなく、少なくとも「何と何を付き合わせたか」を `signal_type` と `source_refs` で説明する。例: 締切と決算月、対象経費と様式、法人番号とインボイス状態、行政処分と制度推薦、採択事例と地域/業種密度。

`next_actions` は有料誘導ではなく、ユーザーの業務を進める具体行動にする。例: 「発注予定日を顧客に確認する」「様式URLの最新版を窓口で確認する」「同一経費の併用可否を問い合わせる」「この根拠で申請前チェックリストを作る」。

funding stack/compat の `next_actions` は、pair verdict や conflict edge を AI が行動へ変換するための補助フィールドとして扱う。併用/排他表では確認先・同一経費切り分け・unknown 解消、申請前チェックでは既申請制度・対象経費・前提認定の確認、代替 bundle 提案では `runner_up_bundles[]` 比較と `exclude_program_ids` 再実行条件に使う。`allow` / `block` の安全保証や採択・受給保証として表示しない。

`known_gaps` は無料枠でも通常利用でも隠さない。`conflict`、`source_stale`、`citation_unverified`、`human_review_required` がある場合、対応する artifact/AI回答用の `decision_insights[].verdict` は断定形にせず、`defer`、`watch`、`ask_human`、`needs_confirmation` のいずれかに落とす。Evidence Packet の top-level `decision_insights` では、同じ条件を `evidence_gaps[]` と `next_checks[]` に出す。

### 3.4 AI Answer Rendering Contract

AI agent が jpcite の結果をユーザーへ説明するときは、Evidence Packet の機械可読キーを次の短い順序に変換する。

```text
結論:
- ...

判断材料:
- [propose_now] ... (根拠: source_url / source_fetched_at)

複数データの手掛かり:
- ... と ... が一致。source_refs: ...
- ... は矛盾または未確認。known_gaps: ...

次にやること:
- 今日: ...
- 今週: ...

確認できていない範囲:
- known_gaps: ...

判断境界:
- 公開情報の整理であり、申請可否、税務、法律、融資可否の最終判断ではありません。
```

AI 向け回答では、根拠の一部非表示、無料枠だから低品質にする表現、外部LLM料金の保証を主訴求にする表現を使わない。価値は「既存データ基盤を付き合わせた判断材料」「根拠確認のしやすさ」「次の業務に移れる完成物」で示す。

### 3.5 bundle/optimal Decision Support Contract

`/v1/intel/bundle/optimal` は、候補 bundle、金額rollup、conflict回避、runner-up を返す最適化エンドポイントである。AI agent がそのまま提案文に変換できるよう、レスポンスへ top-level `decision_support` を追加する場合は、既存の `bundle`、`bundle_total`、`conflict_avoidance`、`optimization_log`、`runner_up_bundles`、`data_quality` から決定論的に生成する。request-time LLM の推測で採択可否、受給可否、併用安全性を断定しない。

`decision_support` は次の用途に限定する。

| Field | 目的 |
|---|---|
| `recommended_position` | agentが最初にどう説明するか。例: `primary_bundle`, `compare_runner_ups`, `needs_human_review` |
| `why_this_bundle` | 選定理由。金額、件数、衝突回避、predicate filter、prefer_categories など、既存レスポンスから説明できる理由だけを書く |
| `tradeoffs` | runner-up や除外候補との違い。金額差、件数差、conflict edge、未確認predicateを隠さない |
| `next_actions` | 顧客確認、窓口確認、同一経費確認、書類収集、専門家確認、runner-up比較、`exclude_program_ids` 再実行などの行動 |
| `known_gaps` | missing axis、stale source、candidate pool不足、predicate未評価、conflict table不足など |

レスポンス例:

```json
{
  "houjin_id": "1234567890123",
  "bundle": [
    {
      "program_id": "UNI-bundle-A",
      "name": "Example Program A",
      "eligibility_score": 0.91,
      "expected_amount_min": 1000000,
      "expected_amount_max": 5000000,
      "conflict_with_others_in_bundle": []
    }
  ],
  "bundle_total": {
    "expected_amount_min": 1000000,
    "expected_amount_max": 5000000,
    "eligibility_avg": 0.91
  },
  "conflict_avoidance": {
    "conflict_pairs_avoided": 1,
    "alternative_considered": 8
  },
  "runner_up_bundles": [
    {
      "bundle": ["UNI-bundle-B", "UNI-bundle-C"],
      "total_amount": 4200000,
      "why_not_chosen": "primary bundle keeps higher expected_amount_max while avoiding the seeded conflict edge"
    }
  ],
  "data_quality": {
    "candidate_pool_size": 8,
    "eligible_after_predicate_filter": 7,
    "predicate_dropped": 1
  },
  "decision_support": {
    "schema_version": "v1",
    "recommended_position": "primary_bundle",
    "why_this_bundle": [
      {
        "reason_code": "highest_objective_score",
        "message_ja": "指定objectiveで最上位の互換bundleです。",
        "basis": ["bundle_total.expected_amount_max", "optimization_log.algorithm"]
      },
      {
        "reason_code": "conflict_avoided",
        "message_ja": "bundle内の衝突候補を避けて選定しています。",
        "basis": ["conflict_avoidance.conflict_pairs_avoided", "bundle[].conflict_with_others_in_bundle"]
      }
    ],
    "tradeoffs": [
      {
        "reason_code": "runner_up_lower_total",
        "message_ja": "runner-up は代替案として提示できますが、primary より expected_amount_max が低い可能性があります。",
        "basis": ["runner_up_bundles[].total_amount", "bundle_total.expected_amount_max"]
      }
    ],
    "next_actions": [
      {
        "action_type": "confirm_same_expense",
        "priority": "today",
        "message_ja": "同一経費の併用可否を公式窓口または専門家へ確認してください。",
        "basis": ["conflict_avoidance", "_disclaimer"]
      }
    ],
    "known_gaps": [
      {
        "gap_code": "missing_axis_unknown",
        "message_ja": "predicate評価に使う法人属性が不足する場合、unknown axis は候補から自動除外していません。",
        "basis": ["data_quality.houjin_profile_used"]
      }
    ]
  },
  "_disclaimer": "statistical proposal, not an approval or benefit guarantee"
}
```

### 3.6 intel/match Interview and Readiness Fields

`/v1/intel/match` の各 `matched_programs[]` は、AI agent が候補説明の直後に顧客ヒアリングと申請前チェックへ移れるよう、次の補助フィールドを持つ。

| Field | AIがそのまま使う用途 | 表示境界 |
|---|---|---|
| `next_questions` | 顧客へ聞く不足情報。発注予定日、投資内容、従業員数、既申請制度、許認可、対象経費などを質問文にする | 「次に顧客へ確認すること」として出す |
| `eligibility_gaps` | `eligibility_predicate` と入力profileを比べた不足、不一致、unknown条件。申請前チェックの未解消項目にする | 不採択や対象外を断定せず、確認が必要なgapとして出す |
| `document_readiness` | `required_documents` を、準備済み、要収集、最新版確認、窓口確認に分ける書類準備状態 | 書類完備、申請受理、採択を保証するものではありません |

AI向け回答では、`match_score` だけで推薦を終えない。候補ごとに `next_questions`、`eligibility_gaps`、`document_readiness` を短く添え、顧客面談、申請前チェックリスト、書類依頼文へ変換する。これらは公開情報と入力profileから作る実務補助であり、申請可否、税務、法律、採択結果の最終判断ではない。

### 3.7 houjin/full Decision Support Contract

`/v1/intel/houjin/{houjin_id}/full` の `decision_support` は、法人360レスポンスを AI agent が法人DD、与信前確認、監視提案へ変換するための補助フィールドである。`houjin_master`、ID bridge、インボイス登録、行政処分、採択/調達履歴、EDINET/官報、source freshness、`known_gaps` など既存レスポンスから説明できる公的リスクの見るべき点、追加確認、監視対象だけを書く。

| Field | AIがそのまま使う用途 | 表示境界 |
|---|---|---|
| `dd_questions` | 投資、融資、取引前に確認する追加DD質問にする | 公的情報の確認事項であり、リスクなしとは断定しない |
| `credit_precheck_notes` | 与信前の照合メモ、稟議注記、要確認sourceにする | 融資可否、返済能力、与信判断を保証しない |
| `monitoring_suggestions` | 監視すべき法人イベント、source、再確認タイミングにする | 変化検知や将来リスクの予測を保証しない |
| `known_gaps` | 同名法人、旧商号、未収録source、stale情報を確認範囲として出す | 未検出を安全保証にしない |

AI向け回答では、法人360 `decision_support` を法人DD質問、与信前確認メモ、監視提案として短く添える。最終的な投資判断、取引可否、融資可否、法務・税務判断の代替にはしない。

## 4. Persona Satisfaction Conditions

ペルソナごとに「何が出ると喜ぶか」を先に固定し、検索結果をその形へ変換する。

| Persona | 満足するアウトプット | 必須で見せる確認範囲 |
|---|---|---|
| 税理士/会計士 | 顧問先に渡せる短い説明文、決算月や投資予定に対する候補、NG条件、資格者確認点 | 税制・補助金・融資候補、条文/制度URL、個別税務判断ではない範囲 |
| 行政書士 | 申請前チェックリスト、必要書類、窓口、期限、ヒアリング項目 | 公募要領・様式URL、提出先、未取得様式、要窓口確認 |
| 補助金コンサル | 候補順位、上限額/補助率、類似採択、併用/排他の確認点、提案順 | 採択事例の範囲、採択率未取得、排他条件の未確認 |
| M&A / VC DD | 法人概況、公的履歴、行政処分/返還リスク、インボイス確認、追加DD質問 | 法人名ゆれ、対象期間、EDINET/官報など未収録範囲 |
| 金融機関 | 融資前の公的制度活用メモ、資金使途適合、稟議注記、確認書類 | 保証制度・処分情報・インボイス状態、最終与信判断ではない範囲 |
| 自治体・商工会 | 相談者向け案内文、職員向け詳細、該当候補が薄い時の説明文 | 国/県/市町村の収録差、締切鮮度、窓口確認点 |
| 事業会社経営企画 | 四半期ロードマップ、決裁事項、制度比較、社内説明文 | 予算時点、制度改定、併用/排他、社内判断が必要な事項 |
| メディア・調査 | source-linked research memo、時系列、数字、引用候補、未確認点 | 引用未検証、一次統計の取得範囲、記事で断定できない点 |
| AI Agent開発者 | when/when-not、期待artifact、短いユーザー説明、評価query | route decisionの条件、skip理由、known_gapsの扱い |

## 5. Copy Standards

AIが出す文は短く、正直で、次の行動が分かるものにする。

### 5.1 Use jpcite

```text
この依頼は日本の公的制度・法人情報の根拠確認が必要です。
jpciteで公式URL、取得日時、known_gaps付きのアウトプットを作ります。
```

### 5.2 Free 3/day Applied

```text
無料枠で通常品質のアウトプットを作成しました。
根拠URL、取得日時、確認不足の範囲は隠していません。
```

### 5.3 Complete Artifact Prompt

```text
この結果は、顧問先向けメモ、申請前チェックリスト、併用/排他確認表、DD質問票に整形できます。
```

### 5.4 Zero Result

```text
jpciteの収録範囲では該当候補を検出できませんでした。
制度が存在しないという意味ではありません。
地域、業種、目的、時期を広げるか、一次資料を確認してください。
```

### 5.5 Human Review

```text
この結果は公開情報の整理です。
申請可否、税務処理、法的判断は、資格者または所管窓口で確認してください。
```

### 5.6 Known Gaps

```text
確認できた範囲と、確認できていない範囲を分けて表示します。
known_gapsにある項目は、追加確認なしに断定しません。
```

## 6. known_gaps as Visible Confirmation Scope

known_gaps は内部エラーではなく、ユーザーに見せる「確認範囲」の一部にする。これにより、0件・低信頼・古い出典でも不信感ではなく次アクションにつながる。

### 6.1 Display Rule

| known_gaps | ユーザー向け表示 | 出力制御 |
|---|---|---|
| `no_records_returned` | 収録範囲では候補を検出できませんでした | 存在しないと断定しない |
| `source_url_missing` | 根拠URLが未取得の情報があります | 結論候補に使わない |
| `source_fetched_at_missing` | 取得日時を確認できない出典があります | 鮮度が必要な主張に使わない |
| `source_stale` | 出典が古い可能性があります | 締切・金額・法改正は要確認 |
| `license_unknown` | 出力可否の確認が必要な資料があります | 引用・転載を控える |
| `low_confidence` | 抽出信頼度が低い項目があります | 補足扱いにする |
| `citation_unverified` | 引用位置を検証できていません | exact claimを避ける |
| `structured_miss` | 構造化できない項目があります | 手動確認の候補にする |
| `conflict` | 出典間で矛盾があります | human_review_requiredにする |
| `human_review_required` | 人間確認が必要です | 最終判断を出さない |
| `audit_seal_not_issued` | 監査sealが未発行です | deep outputでは完了扱いにしない |

### 6.2 Confirmation Scope Block

すべてのユーザー向け出力に、短い確認範囲ブロックを入れる。

```text
確認できた範囲:
- 公式URLと取得日時を確認できた候補
- jpcite収録corpus内で照合できた法人/制度/文書

確認できていない範囲:
- known_gapsに記載の項目
- corpus外の制度、未取得PDF、窓口運用、個別の税務・法務判断
```

## 7. Quality Rules

Free 3/day でも通常利用でも、品質ルールは同じにする。

| Rule | 必須動作 |
|---|---|
| Source-first | 主張には根拠URLまたは known_gap を対応させる |
| No hiding | 無料枠でも根拠・不足・注意点を隠さない |
| No overclaim | 「適用できます」「安全です」「専門家確認は不要です」と断定しない |
| Actionable | 次の質問、確認書類、窓口確認、追加入力を出す |
| Persona-fit | 出力形式をペルソナの業務に合わせる |
| Empty-safe | 0件時は検索条件と収録範囲を説明する |
| Same schema | 無料枠と通常利用で構造を変えない |

## 8. Acceptance Criteria

この仕様を満たすアウトプットの受け入れ条件。

| 条件 | 合格基準 |
|---|---|
| Free 3/day通常品質 | 無料枠でも source_url、source_fetched_at、known_gaps、次アクションが出る |
| 一部非表示なし | 「有料なら根拠を表示」のようなマスク文言がない |
| 完成物化 | 候補一覧だけで終わらず、メモ・表・チェックリスト・質問票のいずれかに変換される |
| ペルソナ適合 | 対象ペルソナの業務文脈に合う言葉と項目で出る |
| known_gaps表示 | 欠落が確認範囲としてユーザーに見える |
| 判断境界 | 税務・法律・申請可否の最終判断を避ける |
| 短文AIコピー | route、無料枠、0件、人間確認の文が短く表示できる |

## 9. Implementation Notes

既存計画との接続点は次の通り。

| 既存計画の要素 | 本仕様での扱い |
|---|---|
| Completion | Free 3/dayでも完成物形式を返す |
| Evidence | 根拠URL・取得日時・検証状態を隠さない |
| Judgment Boundary | 断定禁止と確認事項で表現する |
| Auditability | known_gapsと確認範囲を常に見せる |
| Artifact Envelope | 最低JSON shapeの必須キーとして残す |
| Quality Gates | 無料枠にも同じゲートを適用する |

Free 3/day は `L0 Free Discovery` の存在確認とは別に、通常品質を試せる満足体験として扱う。深い横断調査、長期保存、監視、private overlay、監査付きDeep Packは通常利用以上で厚くするが、無料枠の本文を削ったり根拠を隠したりしない。
