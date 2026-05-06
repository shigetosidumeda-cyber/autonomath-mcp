# Artifact Catalog

更新日: 2026-05-06

このカタログは `deep-paid-output-and-data-foundation-plan.md` のArtifact構想を、内容仕様に落としたものです。価格変更やunit変更ではなく、各artifactが「何を出せばユーザーが満足するか」に集中します。

## 共通方針

有料/無料を問わず、artifactは検索結果の列挙ではなく、業務でそのまま使える完成物にする。

共通して必ず含めるもの:

| 項目 | 内容 |
|---|---|
| 結論サマリ | 最初の30秒で、候補・優先順位・次に見るべき点が分かる |
| なぜ今か | 締切、決算月、投資時期、法改正、様式改定、処分検知などの行動理由 |
| 次にやること | 今日確認すること、顧客へ聞くこと、窓口や専門家へ確認すること |
| 根拠カード | `source_url`, `source_fetched_at`, 引用候補、該当ページ、確認ステータス |
| NG/不明条件 | blocking rule、missing fact、unknown rule、coverage不足 |
| 顧客向け文面 | 顧問先、相談者、稟議、IC、記事メモに貼れる短文 |
| 確認範囲 | 確認済み、未確認、追加確認先、known_gaps |
| 監視提案 | 次に差分監視すべき制度、法人、日付、source |

共通品質ゲート:

| Gate | 内容 |
|---|---|
| Schema Gate | `source_url`, `source_fetched_at`, `known_gaps`, `_disclaimer`, `quality_tier`, `audit_seal`相当の情報を欠落させない |
| Source Gate | aggregator、license_blocked、出典不明、非HTTP根拠を結論の主根拠にしない |
| Freshness Gate | 税制、法令、締切、金額、採択率、様式が古い場合は `human_review_required` を出す |
| Judgment Boundary Gate | 税務判断、法律判断、申請可否、融資可否、併用安全保証を断定しない |
| Citation Gate | 主張ごとに根拠カードを持たせ、引用未検証のexact claimを出さない |
| Empty Result Gate | 0件を「該当なし」と断定せず、確認範囲、retry条件、coverage不足を示す |
| Audit Gate | 深い完成物は `corpus_snapshot_id`, `packet_id`, `audit_seal`相当の再検証情報を持つ |

## 共通実装ブロック

各artifactは、Evidence Packetの根拠カードを本文へ写すだけで終わらせない。既存データ基盤を付き合わせ、次の4ブロックを必ず生成対象にする。

| Block | 出力内容 | 主な生成元 | 品質ゲート |
|---|---|---|---|
| `decision_insights` | 提案、見送り、要確認、監視などの判断材料。`verdict`, `reason_codes`, `source_fact_ids`, `known_gaps`を持つ | `program_decision_layer`, `corporate_risk_layer`, `document_requirement_layer`, eligibility/exclusion rules | 根拠factなしの断定禁止。採択、申請、税務、融資の成功保証にしない |
| `cross_source_signals` | 複数source/テーブルの一致、矛盾、差分、単一source依存を説明するsignal | `source_quality_layer`, `monitoring_delta_layer`, `compat_matrix`, `am_data_quality_snapshot`, `evidence_packet_item` | `conflict`や`single_source`を隠さない。矛盾時はhuman reviewへ落とす |
| `next_actions` | 顧客へ聞く、書類を集める、窓口確認する、監視に入れる、artifact化するなどの行動 | funding stack/compat `next_actions`, `next_questions`, required documents, deadline/calendar, DD questions, routing context | 「もっと見る」だけにしない。行動、期限感、担当ヒント、依存する根拠を持たせる |
| `known_gaps` | 未確認、古い、corpus外、引用未検証、license不明、source間矛盾 | `quality.known_gaps`, `known_gaps_inventory`, source freshness, citation verification | 無料/通常利用を問わず表示。gapがあるclaimは断定しない |

### Evidence Packetでの配置

Evidence Packet は source-linked records に加え、AI がそのまま回答へ変換できる `answer_intelligence` を持てる形にする。

```json
{
  "packet_id": "evp_...",
  "records": [],
  "answer_intelligence": {
    "decision_insights": [],
    "cross_source_signals": [],
    "next_actions": []
  },
  "sources": [],
  "quality": {
    "known_gaps": [],
    "known_gaps_inventory": []
  },
  "_disclaimer": {}
}
```

`answer_intelligence` は本文生成の補助であり、根拠そのものではない。各itemは `evidence_item_ids`、`source_fact_ids`、`source_refs` のいずれかで根拠へ戻れる必要がある。

### 実レスポンスでの追加配置

公開APIの実レスポンスでは、用途に応じて top-level または候補item内の補助ブロックを返す。

| Endpoint | Response block | 役割 | 生成元 | 境界 |
|---|---|---|---|---|
| Evidence Packet | `decision_insights` | AI agent が回答前に見るべき根拠、次の確認、根拠不足を短く示す | `records`, `quality`, `verification`, `evidence_value`, `corpus_snapshot_id` | 最終回答ではない。根拠URL・取得日時・known_gapsを隠さない |
| `/v1/intel/match` | `matched_programs[].next_questions`, `matched_programs[].eligibility_gaps`, `matched_programs[].document_readiness` | 候補ごとに顧客ヒアリング、要件gap、書類準備状態をそのまま申請前チェックへ変換する | `eligibility_predicate`, `required_documents`, input profile, deadline/source freshness | 採択保証、申請可否保証、書類完備保証にしない |
| `/v1/intel/bundle/optimal` | `decision_support` | primary bundle の説明、runner-up との tradeoff、次アクション、known gaps を提示する | `bundle`, `bundle_total`, `conflict_avoidance`, `optimization_log`, `runner_up_bundles`, `data_quality` | 採択保証、受給保証、併用安全保証にしない |
| `/v1/intel/houjin/{houjin_id}/full` | `decision_support` | 法人DD、与信前確認、監視提案向けに、公的リスクの見るべき点、追加確認、監視対象を短く示す | `houjin_master`, `entity_id_bridge`, invoice, enforcement/procurement/adoption/disclosure records, source freshness, `known_gaps` | 公的リスクなし、与信可否、取引安全、監視検知を保証しない |
| `/v1/funding_stack/check` / compat outputs | `next_actions` | pair verdict を併用/排他表、申請前チェック、代替bundle比較の確認行動へ変換する | `all_pairs_status`, `pairs[].verdict`, `rule_chain`, `blockers`, `warnings`, `am_compat_matrix`, `exclusion_rules` | 併用可能、安全、採択、受給を保証しない |

Evidence Packet の `decision_insights` は、現行JSONでは次の形を返す。

```json
{
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
        "message_ja": "出典URLと取得・確認日時付きのレコードがあります。",
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

bundle/optimal の `decision_support` は、選ばれた bundle を説明するための補助であり、artifact本文の「判断材料」「次にやること」「確認範囲」に変換できる形にする。

houjin/full の `decision_support` は、法人360を法人DD質問、与信前確認メモ、監視提案へ変換する補助である。AI agent は公的リスクの見るべき点、追加確認、監視対象として短く表示し、融資可否や取引安全の保証として扱わない。

intel/match の `next_questions`、`eligibility_gaps`、`document_readiness` は、候補一覧を顧客ヒアリング票と申請前チェックに変換するための補助である。AI agent は `next_questions` を顧客へ聞く質問、`eligibility_gaps` を未解消要件、`document_readiness` を書類依頼と最新版確認の状態として短く表示する。

funding stack/compat の `next_actions` は、併用/排他表では pair ごとの確認先・同一経費切り分け・unknown 解消、申請前チェックでは既申請制度・対象経費・前提認定の確認、代替bundle提案では `runner_up_bundles[]` 比較と再実行条件として短く表示する。

```json
{
  "decision_support": {
    "schema_version": "v1",
    "recommended_position": "primary_bundle",
    "why_this_bundle": [
      {
        "reason_code": "conflict_avoided",
        "message_ja": "bundle内の衝突候補を避けて選定しています。",
        "basis": ["conflict_avoidance.conflict_pairs_avoided"]
      }
    ],
    "tradeoffs": [
      {
        "reason_code": "runner_up_available",
        "message_ja": "runner-up は代替案として比較できます。",
        "basis": ["runner_up_bundles[]"]
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
    "known_gaps": []
  }
}
```

### AI向け回答での配置

AI 向け回答は次の順に短く出す。

| 表示順 | 表示名 | 対応キー | 表示ルール |
|---|---|---|---|
| 1 | 結論 | `answer.headline`, `candidate_summary` | 30秒で判断できる長さにする |
| 2 | 判断材料 | `decision_insights[]` | `verdict` と理由を出し、根拠URL/取得日へ戻せるようにする |
| 3 | 複数データの手掛かり | `cross_source_signals[]` | 一致、矛盾、差分、単一source依存をラベル化する |
| 4 | 完成物 | `usable_artifact[]` | 顧問先文面、チェック表、稟議注記、DD質問などにする |
| 5 | 次にやること | `next_actions[]` | 今日/今週/後で、顧客/窓口/専門家のように行動可能にする |
| 6 | 確認範囲 | `known_gaps[]`, `quality.known_gaps[]` | できた確認と未確認を分ける |
| 7 | 判断境界 | `_disclaimer` | 公開情報整理であり最終判断ではないことを明示する |

### Artifact別の生成例

| Artifact | `decision_insights` | `cross_source_signals` | `next_actions` |
|---|---|---|---|
| `tax_client_impact_memo` | 決算月、投資予定、制度条件から `propose_now` / `defer` / `exclude` を出す | 税制/補助金/融資候補、締切、source freshness、法人属性の一致を見る | 顧問先へ聞く質問、資格者確認点、今月送る文面作成 |
| `application_kit` | 要件充足、対象外経費、書類不足、様式未確認を判断材料にする | 公募要領、様式URL、FAQ、締切、窓口情報を付き合わせる | 必要書類収集、最新版様式確認、窓口質問文 |
| `subsidy_strategy_report` | fit、urgency、win signal、blocking ruleから提案順を出す | 類似採択、地域/業種密度、併用/排他、採択回を照合する | 証憑準備、提案順の確定、併用確認 |
| `houjin_dd_pack` | インボイス、処分、採択、調達、商号変更からDD質問を出す | 法人番号、ID bridge、処分、官報/EDINET、invoice履歴を照合する | 追加DD質問、同名法人確認、未収録source確認 |
| `lender_public_risk_sheet` | 資金使途適合、公的支援候補、確認書類、リスク注記を出す | 融資/保証制度、補助金、法人照合、invoice/処分を照合する | 借り手ヒアリング、確認書類依頼、稟議注記化 |
| `executive_funding_roadmap` | 四半期ごとの決裁、認定取得、申請順を出す | 12か月calendar、締切、compat、社内前提を付き合わせる | 今四半期の決裁、認定準備、監視対象追加 |
| `compatibility_table` | `allow` / `block` / `defer` / `unknown` を理由つきで出す | exclusion rule、compat matrix、同一経費、制度文書を照合する | funding stack/compat `next_actions` で窓口確認、同一経費の切り分け、unknown解消 |
| `monitoring_digest` | 重要差分、再生成すべきartifact、変化なしの確認範囲を出す | 前回packet、source hash、締切、処分、invoice、法改正を比較する | 再生成、顧問先連絡、監視条件更新 |
| `media_research_memo` | 記事で言えるfact、まだ言えないfact、反対事実を分ける | 統計、制度、処分、時系列、引用候補を照合する | 追加取材先、引用確認、数字定義の確認 |
| `agent_routing_eval_pack` | use/skip、fallback、schema assertionを出す | OpenAPI/MCP metadata、known_gaps taxonomy、eval結果を照合する | eval query追加、schema test、routing rule更新 |

## 1. 顧問先メモ `tax_client_impact_memo`

税理士/会計士が、顧問先へ今月送れる提案メモとして使えることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 法人番号または法人名<br>所在地、業種、資本金、従業員数<br>決算月、投資予定、投資時期<br>青色申告、認定、過去採択、申請中制度<br>顧問先固有メモまたはprivate overlay | 30秒サマリ<br>今月提案すべき制度、税制、融資候補<br>決算月・投資時期への影響<br>顧問先へ聞く質問<br>NG/不明条件<br>顧問先向け一言説明文<br>根拠カード、確認範囲、監視提案 | `houjin_master`, `entity_id_bridge`<br>`programs`, `loan_programs`, `tax_rulesets`, `laws`, NTA/通達/質疑/裁決<br>`program_documents`, deadlines, eligibility/exclusion rules<br>`adoption_records`, `case_studies`<br>`source_document`, `extracted_fact.quote/page/span`<br>`evidence_packet`, `corpus_snapshot`, `audit_seal` | 「今声をかける理由」を決算月、締切、投資予定から1文で出す<br>最初に提案すべき3件と、見送り候補を分ける<br>顧問先にそのまま送れる柔らかい文面を付ける<br>不足情報を「質問リスト」に変換する | 税務上の適用可否を断定しない<br>税制・締切・金額がstaleならhuman review<br>各候補に一次sourceの根拠カードを付ける<br>tier Cだけの根拠を結論に使わない<br>0件時は条件拡張案とcoverage不足を出す |

## 2. 申請キット `application_kit`

行政書士や補助金実務者が、申請前面談で不備を潰せる準備表として使えることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 地域、業種、事業内容<br>投資内容、対象経費、投資額、発注予定日<br>提出希望時期、許認可、企業規模<br>対象制度IDまたは候補条件 | 要件チェック表<br>必要書類一覧<br>様式URL、様式名、提出順<br>対象経費/対象外経費<br>期限、窓口、提出方法<br>受任前ヒアリング項目<br>顧客への依頼文<br>根拠カード、確認範囲 | `programs`, `program_documents`<br>公募要領PDF、様式PDF/XLSX/DOCX<br>deadlines, eligibility_rules, exclusion_rules<br>窓口、提出先、申請方法、source freshness<br>`extracted_fact.quote/page/span` | 「PDFを読まなくて済む」状態にする<br>必要書類ごとに該当ページと様式名を出す<br>顧客に聞く質問と、窓口に確認する質問を分ける<br>未取得書類をチェックリスト化する | 申請可能と断定しない<br>最新様式が未確認なら明示する<br>期限・様式・対象経費は公式sourceで裏付ける<br>不明条件はunknownとして残す<br>窓口確認が必要な項目を隠さない |

## 3. 補助金戦略 `subsidy_strategy_report`

補助金コンサルが、候補一覧ではなく「勝ち筋」と提案順を初回提案に使えることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 法人番号または法人名<br>投資目的、投資額、事業テーマ<br>所在地、業種、従業員数<br>過去採択、申請中制度、併用予定制度<br>申請希望時期、事業計画の要点 | 候補順位Top3-5<br>制度別の勝ち筋<br>類似採択、採択回、競争度<br>審査で強調する論点<br>落ちる理由、足りない証憑<br>提案順、次アクション<br>併用/排他の注意<br>根拠カード、known_gaps | `programs`, `adoption_round`, `adoption_records`<br>`case_studies`, 地域/業種密度<br>`program_decision_layer`<br>審査項目、対象経費、deadlines<br>`exclusion_rules`, `compat_matrix`<br>`program_documents`, quote/page/span | 「この会社には最初にこれを提案する」を明確にする<br>採択可能性を数字だけでなく理由コードで説明する<br>類似採択から、用意すべき証憑を逆算する<br>非推奨制度も理由つきで出す | 採択可能性を保証しない<br>採択率・採択件数は期間とsourceを明示する<br>採択データ欠落時はgapとして表示する<br>併用不明をallow扱いにしない<br>tier C情報で勝ち筋を断定しない |

## 4. 法人DD `houjin_dd_pack`

M&A、VC、金融機関が、法人番号から公的リスクと追加DD質問を会議資料に貼れることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 法人番号または法人名<br>対象期間、関連会社、代表者名の任意情報<br>投資、融資、取引、買収などの利用文脈<br>注目リスク、既知の別名や旧商号 | 会社概況<br>公的イベント時系列<br>インボイス登録状態<br>採択、補助金、調達履歴<br>行政処分、返還、取消リスク候補<br>EDINET、官報、法人変更<br>追加DD質問<br>出典表、確認範囲 | `houjin_master`, `entity_id_bridge`<br>`invoice_registration_history`<br>`enforcement_event`, adoption/procurement records<br>EDINET, 官報, court/procurement data<br>`corporate_risk_layer`<br>商号変更、所在地変更、関連entity link<br>`source_document`, citation verification | 赤黄緑の公的リスクサマリを1画面で出す<br>イベントを時系列にして「いつ何が起きたか」を見せる<br>投資委員会や稟議に貼れる追加DD質問を出す<br>同名法人・旧商号の照合不確実性も見える化する | 同名法人の誤結合を避け、entity match confidenceを出す<br>「公的リスクなし」と断定しない<br>処分・インボイス情報がstaleならhuman review<br>source間矛盾はconflictとして止める<br>未検出は確認範囲として表示する |

## 5. 稟議シート `lender_public_risk_sheet`

金融機関や経営管理が、融資稟議・社内稟議に貼れる公的支援候補と確認注記として使えることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 法人番号または法人名<br>資金使途、借入希望額、投資内容<br>設備投資・運転資金の内訳<br>実行希望時期、補助金入金予定<br>既存借入、申請中制度の任意情報 | 稟議用サマリ<br>資金使途に合う公的支援候補<br>補助金入金前のつなぎ論点<br>確認書類一覧<br>処分、インボイス、法人照合メモ<br>稟議注記案<br>確認前提とknown_gaps | `loan_programs`, 保証制度、自治体融資<br>`programs`, tax measures, certification requirements<br>`houjin_master`, invoice, enforcement<br>funding stack/compatibility rules<br>deadlines, required documents<br>`source_document`, quote/page/span | 稟議本文に貼れる短い注記文を出す<br>「資金使途に合う/合わない」を制度条件から説明する<br>補助金入金時期と資金繰りのズレを可視化する<br>借り手に聞く追加質問を出す | 融資可否や与信判断を断定しない<br>金額、期限、利率、保証条件がstaleならhuman review<br>制度候補は公式sourceに紐付ける<br>公的リスク未検出を安全保証にしない<br>稟議注記は情報整理として表示する |

## 6. 資金調達ロードマップ `executive_funding_roadmap`

経営企画/CFOが、12か月の補助金・税制・融資アクションを会議で意思決定できることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 事業計画、投資テーマ、投資額<br>拠点、雇用計画、賃上げ計画<br>決算月、予算化時期、社内決裁日<br>認定取得状況、資金繰り制約<br>申請済み/検討中制度 | 12か月または四半期ロードマップ<br>決裁事項、予算反映事項<br>認定取得、事前準備、申請順<br>補助金・融資・税制のstack案<br>締切と逆算スケジュール<br>役割分担、今四半期のToDo<br>監視提案 | `programs`, tax measures, loan/guarantee products<br>certification requirements<br>deadlines, amendment_diff, source freshness<br>`compat_matrix`, eligibility/exclusion rules<br>`program_decision_layer`<br>private overlayの事業計画・決裁情報 | 締切順ではなく、社内決裁・認定取得・予算化の順で並べる<br>「今四半期に決めること」を明確にする<br>先に動かないと間に合わない長期リード項目を警告する<br>役員会資料に貼れる短文を付ける | 資金調達成功を保証しない<br>日付の前提と依存関係を明示する<br>併用不明はunknownのまま残す<br>古い締切、改定未確認sourceはhuman review<br>内部前提が足りない場合は質問として出す |

## 7. 併用/排他表 `compatibility_table`

補助金、融資、税制を組み合わせる前に、allow/block/defer/unknownを理由と確認先つきで判断候補化することをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 複数の制度ID、税制ID、融資制度ID<br>法人属性、対象経費、申請時期<br>既に申請済みまたは採択済みの制度<br>同一経費の有無、資金繰り順序 | 併用/排他マトリクス<br>`allow`, `block`, `defer`, `unknown`判定<br>理由、source quote、該当ページ<br>同一経費・二重計上リスク<br>推奨stack順<br>確認先、窓口質問文<br>未解決リスト | `compat_matrix`, `exclusion_rules`<br>`program_documents`, tax rules, finance product terms<br>`rule.verdict`, `derived_from_fact_ids_json`<br>`extracted_fact.quote/page/span`<br>公式窓口、問い合わせ先、source freshness | 「併用できるか」を雑に断定せず、未確認点まで行動可能にする<br>同一経費、時期、前提認定ごとの論点を分ける<br>窓口へそのまま送れる確認文を付ける<br>blockだけでなくdeferの条件も出す | 「併用可能です」と保証しない<br>allow/blockはsource付きの場合だけ出す<br>根拠不足はunknownにする<br>source間矛盾はhuman review<br>判定ごとに理由、確認先、known_gapsを持たせる |

## 8. 月次監視 `monitoring_digest`

士業、金融、VCが、顧問先・投資先・制度の差分を毎月見る意味がある1枚にすることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| watchlistまたはsaved_search<br>法人番号、制度ID、法令ID、税制ID<br>前回packet ID、前回生成日<br>重要度しきい値、受信者ロール<br>監視対象の地域、業種、顧問先グループ | 前回からの差分<br>締切接近、様式改定、法令/税制改正<br>採択発表、行政処分、インボイス変化<br>重要度と理由<br>今月やるべきこと<br>変化なしの確認範囲<br>再生成すべきartifact提案 | `watchlist`, `saved_searches`<br>`amendment_diff`, `source_freshness`<br>program deadlines/forms/doc hashes<br>laws, tax, enforcement, adoption, invoice<br>`source_document.content_hash`<br>previous `evidence_packet` and `corpus_snapshot` | 「今月見るべきものだけ」を重要度つきで出す<br>変化なしでも、どの範囲を確認したかを示す<br>差分から顧問先メモ、申請キット、DDの再生成へつなげる<br>締切接近を行動単位に変換する | 必ず前回snapshotとの差分として計算する<br>source unreachableやhash変化は明示する<br>重要差分を根拠なしで隠さない<br>変化なしを「リスクなし」と言わない<br>audit sealとknown_gapsを付ける |

## 9. 取材メモ `media_research_memo`

メディア・調査担当が、記事作成前のファクトチェック可能なsource-linked research memoとして使えることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| 調査テーマ、対象企業、制度、地域<br>対象期間、切り口、必要な数字<br>掲載締切、想定読者、既知の仮説<br>引用したいclaimまたは確認したい論点 | リードに使えるファクト候補<br>時系列<br>主要数字と定義<br>引用候補、該当ページ<br>反対事実、矛盾、未確認点<br>追加取材先、確認質問<br>source list、claim-to-source表 | laws, programs, enforcement, adoption<br>court cases, procurement, statistics<br>`source_document`, `extracted_fact.quote/page/span`<br>citation verification<br>source license/freshness<br>entity_id_bridge for companies/orgs | 記者が「何が言えるか/まだ言えないか」を区別できる<br>数字の定義、期間、母数を並べる<br>時系列で政策・処分・採択を追える<br>短い引用候補と追加取材質問を出す | factual claimごとにcitationを要求する<br>未検証の疑惑や評価を断定しない<br>統計の期間、母数、定義を明示する<br>licenseや引用制限に注意する<br>推論は推論としてラベルする |

## 10. AI routing/eval pack `agent_routing_eval_pack`

AI Agent開発者が、jpciteをいつ呼び、いつ呼ばないかを迷わず実装・評価できることをゴールにする。

| inputs | output sections | required data | delight details | quality gates |
|---|---|---|---|---|
| agent環境、利用可能tool、対象ユーザー<br>query mix、必要artifact、許容レスポンス時間<br>根拠必須/任意の境界<br>既存prompt、失敗ログ、評価したいケース | use/skip routing rule<br>when-not-to-use条件<br>tool subsetとoperation選択<br>artifact別expected output<br>sample prompt、fallback文<br>eval query、golden expectations<br>failure case、schema assertion<br>trace logの見方 | OpenAPI/MCP metadata<br>Actions safe subset<br>artifact schema and envelope<br>routing contract, skip reasons<br>known_gaps taxonomy, quality gates<br>benchmark/eval results<br>usage and failure logs | agentが無駄なweb検索やtool連鎖を減らせる<br>0件、stale、conflict、根拠不要のskip例を含める<br>期待するartifactのキーと品質条件をテスト化する<br>開発者がroutingをそのままCIに入れられる | OpenAPIやMCP metadataのdriftをfailにする<br>use/skipの両方を評価queryに含める<br>法律・税務・申請可否の最終判断へroutingしない<br>schema必須キー欠落をfailにする<br>citation_rate、unsupported_claim_count、known_gaps表示を評価する |
