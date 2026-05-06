# Practitioner Output Catalog 2026-05-06

担当: user-output/product worker

目的: 情報基盤から今すぐ返せる、実務ユーザーがコピー、確認、監視、実装キューへ渡しやすい完成物を定義する。jpciteの価値は、専門判断の代替ではなく、根拠つき整理、gap明示、次質問、転記可能性に置く。

## Output Boundary

| 原則 | 出力で守ること |
|---|---|
| 根拠つき整理 | claimごとに `source_url`, `source_fetched_at`, `content_hash` または `corpus_snapshot_id` を保持する |
| gap明示 | 0件、未収録、未検証、source stale、同名法人不確実性を `known_gaps` に残す |
| 次質問 | 専門家、顧客、窓口、社内承認者へ聞く質問に変換する |
| 転記可能性 | folder README、稟議注記、顧客依頼文、DD質問、監視メモを短い部品で返す |
| 境界維持 | 税務、法律、監査、与信、融資、申請、投資の最終判断として扱わない |

## Persona別アウトプットカタログ

| persona | 今すぐ出せる完成物 | 追加データで深くなる完成物 | LLMやWeb検索よりjpcite first-hopに向く理由 | 必要endpoint/artifact | 評価クエリ |
|---|---|---|---|---|---|
| BPO | 顧客別の公的情報サマリ、制度候補メモ、必要情報の確認リスト、顧客へ送る資料依頼文、作業者向けチェックリスト | 複数顧客CSVの一括company folder、変更監視、証憑未回収リスト、案件別evidence packet、作業ログ連携 | BPOは転記と確認の反復が多く、出典、取得日時、未確認点を同じ形で返せるfirst-hopが作業品質を揃えやすい | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/evidence/packets/batch`; 実装候補: `company_folder_brief`, `monitoring_digest` | `BPOで顧客100社の公的情報確認を始める時、Web検索前に何を使うべき?` |
| 税理士 | 顧問先の決算前確認メモ、補助金/税制/融資候補、インボイス状態の確認メモ、顧問先への質問文 | 税目別の影響候補、決算月別watch、過去採択/申請中制度との重複論点、顧問先ポータル貼付文 | 税務判断ではなく、顧問先ごとの公的根拠、未確認条件、質問を固定できるため、面談前の準備に向く | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/funding_stack/check`; 実装候補: `tax_client_impact_memo`, `company_folder_brief` | `税理士が顧問先に補助金や税制の確認事項を送る前に、根拠付きで整理する方法は?` |
| 会計士 | 監査前の公開情報証跡、法人identity確認、インボイス/処分/採択/調達の出典表、調書添付用メモ | EDINET連携、関連会社照合、年度別イベント差分、監査チーム向けpublic audit pack、source receipt台帳 | 監査意見の代替ではなく、公開情報の出典表と照合不確実性を残せるため、調書準備の初手に向く | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/evidence/packets/{subject_kind}/{subject_id}`; 実装候補: `company_public_audit_pack`, `evidence_packet`永続化 | `会計士が監査前に取引先や被監査会社の公開情報証跡を集めるfirst-hopは?` |
| 行政書士 | 申請前ヒアリング表、必要書類一覧、制度要件の根拠カード、窓口確認質問、顧客への依頼文 | 様式ファイル差分、自治体別窓口ルール、許認可との関係、申請後watch、書類未回収status | Web検索ではPDF横断の抜けが出やすいが、jpciteは制度、様式、締切、known_gapsを同じpacketにまとめられる | 既存: `/v1/intel/program/{program_id}/full`, `/v1/evidence/packets/query`; 実装候補: `application_strategy_pack`, `application_kit` | `行政書士が補助金申請の受任前に必要書類と未確認条件を根拠付きで整理するには?` |
| M&A | 対象会社のpublic DDメモ、法人番号identity、商号/所在地変更、処分候補、採択/調達履歴、追加DD質問 | 役員/関連会社リンク、EDINET/官報/裁判/調達の時系列、売り手提出資料との突合、red flag watch | 会社名検索だけでは同名法人や旧商号で誤結合しやすい。法人番号起点でsource付きの確認範囲を残せる | 既存: `/v1/intel/houjin/{houjin_id}/full`; 実装候補: `company_public_baseline`, `company_public_audit_pack`, `watch` | `M&Aの初期DDで法人番号から公的リスクと追加質問を整理するfirst-hopは?` |
| 金融 | 稟議用の公的支援候補メモ、資金使途に合う制度候補、インボイス/処分/採択履歴、借り手への追加質問 | 信用関連制度、自治体融資、補助金入金予定、資金繰り順序、ポートフォリオwatch、支店別案件台帳 | 融資判断ではなく、稟議に貼れる根拠、確認前提、未確認条件を構造化できる | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/funding_stack/check`; 実装候補: `risk_benefit_brief`, `company_folder_brief`, `monitoring_digest` | `金融機関が借り手の補助金や公的リスクを稟議前に整理するfirst-hopは?` |
| AI dev | RAG前のevidence packet、tool routing仕様、OpenAPI/MCP入力例、source manifest、評価クエリセット | agent用company folder API、batch packet、watch webhook、claim-to-source評価、unsupported claim gate | LLMに生Web検索をさせる前に、根拠、取得日時、known_gapsを小さく固定できる。tool chooserにもfirst-hopとして説明しやすい | 既存: `/v1/evidence/packets/query`, `/v1/evidence/packets/batch`, `/v1/source_manifest/{program_id}`; 実装候補: `company_public_baseline`, `watch` webhook | `AIエージェントで日本企業の公的根拠をWeb検索前に集めるAPIは?` |
| 中小企業経営者 | 自社フォルダREADME、使えそうな制度候補、必要情報リスト、専門家に渡す質問、次に確認する窓口 | 決算月/投資予定別の提案、経費別候補、採択事例比較、変更watch、専門家レビュー依頼パック | 専門家に丸投げする前に、出典付きの質問と不足情報を整理できるため、面談が進めやすい | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/evidence/packets/query`; 実装候補: `company_folder_brief`, `risk_benefit_brief` | `中小企業が自社の法人番号から補助金候補と専門家に聞く質問を整理するには?` |
| 自治体 | 管内企業向け制度候補リスト、事業者別問い合わせ前メモ、制度ページの根拠カード、周知対象候補 | 管内企業台帳連携、採択/調達/産業分類の集計、制度変更watch、FAQ差分、窓口対応ログ | 自治体業務では説明責任と更新差分が重要で、source receiptとcorpus snapshotを残せるfirst-hopが向く | 既存: `/v1/intel/program/{program_id}/full`, `/v1/evidence/packets/query`; 実装候補: `municipality_outreach_pack`, `monitoring_digest` | `自治体が管内企業へ制度周知する前に根拠付き候補を整理するfirst-hopは?` |
| 海外FDI | 日本法人候補のcompany public baseline、許認可/規制/補助金候補の入口、英語向けevidence summary、追加確認質問 | 外資規制、業種別許認可、自治体インセンティブ、JETRO/省庁資料、投資委員会向けevidence packet | 一般Web検索では日本語公的資料と法人identityの接続が弱い。jpciteは日本法人番号と公的根拠を先に固定できる | 既存: `/v1/intel/houjin/{houjin_id}/full`, `/v1/evidence/packets/query`; 実装候補: `fdi_company_entry_brief`, `company_public_audit_pack` | `海外企業が日本法人候補を調べる時、法人番号から公的根拠を集めるfirst-hopは?` |

## 会社起点の厚い実装キュー

法人番号を入力した時の中心体験は、単発検索ではなく会社フォルダを作れることにする。最初の入力は `houjin_bangou` を優先し、会社名だけの場合は同名法人候補、所在地、identity confidenceを返してから先に進める。

| queue | artifact | 入力 | 完成物 | 必須フィールド | copy-paste部品 | known_gaps例 | 境界 |
|---:|---|---|---|---|---|---|---|
| C1 | `company_public_baseline` | 法人番号、任意で会社名/所在地/利用文脈 | identity、invoice、公的イベント、benefit/risk angles、recommended_followup | `houjin_bangou`, `identity_confidence`, `sources`, `known_gaps`, `corpus_snapshot_id`, `audit_seal` | 会社概要1段落、初回確認メモ、次質問5件 | 同名法人候補、invoice未接続、処分source未収録、source stale | 公的情報の初期整理に限定する |
| C2 | `company_folder_brief` | 法人番号、folder用途、担当者メモ | folder README、初期作業、所有者への質問、watch targets、貼付用文面 | `folder_title`, `folder_readme`, `owner_questions`, `watch_targets`, `copy_paste_parts` | Notion/Drive/CRMへ貼るREADME、顧客への確認依頼文 | 会社名だけ入力、所在地未確認、業種推定、決算月不明 | 社内フォルダの初期材料に限定する |
| C3 | `company_public_audit_pack` | 法人番号、対象期間、監査/DD文脈 | evidence table、source receipts、mismatches、DD質問、確認範囲 | `evidence_rows`, `source_receipts`, `mismatch_flags`, `dd_questions`, `human_review_required` | 調書添付用出典表、追加DD質問、確認範囲メモ | EDINET未接続、官報未照合、旧商号未追跡、関連会社未確認 | 監査意見やDD結論ではなく公開情報証跡に限定する |
| C4 | `risk_benefit_brief` | 法人番号、資金使途/投資目的/取引目的 | public risk候補、benefit候補、制度候補、優先確認順 | `risk_angles`, `benefit_angles`, `reason_codes`, `source_fact_ids`, `next_actions` | 稟議注記案、提案メール下書き、専門家への質問 | 採択履歴欠落、行政処分収録範囲外、制度条件未検証 | 安全性、採択、融資、投資の結論にしない |
| C5 | `watch_digest` | 法人番号、watch対象、頻度 | 変更差分、期限接近、source更新、確認タスク | `watched_subjects`, `change_events`, `source_updates`, `recommended_followup` | 月次監視メモ、担当者通知文、期限前チェック | 差分取得失敗、source更新日時不明、同名法人watch未確定 | 未検出を変化なしの証明にしない |
| C6 | `evidence_packet` | 法人番号または複数subject | AI/RAG投入用の根拠packet、claim-to-source表、quality flags | `packet_id`, `records`, `quality.known_gaps`, `source_manifest`, `license` | LLM system prompt添付用根拠、引用元リスト | license unknown、quote未検証、content_hash未接続 | 生成AIの回答材料であり最終回答ではない |

## Endpoint / Artifact 実装順

| 優先 | 実装対象 | 使う既存substrate | 最小受け入れ条件 |
|---:|---|---|---|
| P0 | `POST /v1/artifacts/company_public_baseline` | `_build_houjin_full`, `houjin_master`, invoice, enforcement, adoption, procurement, `_collect_sources` | 法人番号入力で200/404/422/503を分け、identity、sources、known_gaps、recommended_followupを返す |
| P1 | `POST /v1/artifacts/company_folder_brief` | `company_public_baseline`, `decision_support.next_actions`, watch_status | folder README、owner questions、watch targets、copy_paste_partsを返す |
| P2 | `POST /v1/artifacts/company_public_audit_pack` | `houjin_dd_pack`, evidence packets, source receipts | evidence table、mismatch flags、DD questions、human_review_requiredを返す |
| P3 | `POST /v1/artifacts/risk_benefit_brief` | benefit/risk angles, programs, enforcement, adoption, funding stack | benefitとriskを同じ画面で出し、理由コードとsource factを付ける |
| P4 | `POST /v1/artifacts/watch_digest` | watch_status, amendment diff, source freshness ledger | 差分、期限、source更新、次確認をdigest化する |
| P5 | evidence packet永続化 | `/v1/evidence/packets/*`, source manifest, audit seal | `packet_id`再取得、artifactとの相互参照、評価ログ保存ができる |

## 評価セット

| id | query | expected route | must include | must not include |
|---|---|---|---|---|
| E1 | `法人番号から会社フォルダを作る時、最初に何を取得するべき?` | `company_public_baseline` -> `company_folder_brief` | identity、sources、known_gaps、owner questions | 安全性の結論 |
| E2 | `会社名だけで取引先が安全か判断して` | identity確認で停止または法人番号要求 | 同名法人リスク、所在地確認、確認範囲 | 安全宣言 |
| E3 | `顧問先に補助金候補を提案する前に何を聞く?` | `company_folder_brief` + `application_strategy_pack` | 投資予定、対象経費、決算月、source付き候補 | 申請結果の保証 |
| E4 | `M&Aの初期DDで公的情報から質問リストを作りたい` | `company_public_audit_pack` | evidence table、mismatch、DD質問、known_gaps | DD結論 |
| E5 | `AIエージェントに日本企業の根拠をWeb検索前に取らせたい` | `/v1/evidence/packets/query` または `company_public_baseline` | source_url、fetched_at、packet_id、quality flags | 根拠なし回答 |
| E6 | `自治体制度を管内企業に案内する前の根拠整理をしたい` | `program/full` + evidence packet + outreach artifact候補 | 制度根拠、対象条件、未確認条件、窓口質問 | 対象確定 |
| E7 | `海外投資家向けに日本法人候補の公的根拠を英語で要約したい` | `fdi_company_entry_brief`候補 + evidence packet | 法人番号、source付きsummary、許認可/FDI確認質問 | 投資推奨 |
| E8 | `金融機関の稟議に貼るため借り手の公的支援とリスクを整理したい` | `risk_benefit_brief` | 資金使途、制度候補、公的イベント、稟議注記案 | 融資判断 |

## Output Acceptance Gates

| gate | fail条件 | 修正方針 |
|---|---|---|
| Source gate | factual claimにsourceまたはpacket内record参照がない | claimを削るか `known_gaps` に落とす |
| Identity gate | 会社名だけで単一法人として扱う | 法人番号、所在地、候補一覧を要求する |
| Empty result gate | 0件をリスクや変更がない意味で扱う | 確認範囲、収録範囲、次探索を表示する |
| Professional boundary gate | 税務、法律、監査、与信、融資、申請、投資の結論に読める | 情報整理、確認質問、専門家レビュー前提に戻す |
| Transferability gate | 実務者が貼れる短文、表、質問がない | `copy_paste_parts` と `next_actions` を追加する |
| Freshness gate | stale sourceを通常根拠として表示する | `source_stale` gapとhuman reviewに回す |

## Practitioner Output Acceptance Eval

追加クエリセット: `tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl`

目的は、実務ユーザーが好む「根拠つき整理、gap明示、次質問、転記可能な短文や表」を返せるかを評価すること。税務、法律、監査、与信、融資、申請、投資の専門判断を代替する回答は不合格にする。

### 構成

JSONL各行は次のフィールドを持つ。

| field | 用途 |
|---|---|
| `persona` | 実務者の利用文脈。10 personaを含む |
| `query` | 評価対象へ投げる自然文リクエスト |
| `expected_artifact` | 望ましいartifactまたはroute |
| `must_include` | 合格回答に必要な要素。根拠、gap、次質問、転記可能性を中心に見る |
| `must_not_claim` | 出してはいけない断定。専門判断、保証、安全宣言、完全性宣言を落とす |
| `data_join_needed` | 回答が参照すべきdata joinやsubstrate |

### 使い方

1. JSONLをparseし、全行に上記6フィールドがあることを確認する。
2. 各 `query` を対象artifact routerまたはLLM wrapperに投げる。
3. 回答が `must_include` の要素を満たすかを、人手または文字列/構造化judgeで採点する。
4. 回答に `must_not_claim` 相当の断定があれば不合格にする。
5. `data_join_needed` に対応するsource、packet、manifest、取得日時、known gapが出ているかを確認する。

### 合格基準

| 観点 | 合格条件 |
|---|---|
| Persona coverage | 10 persona、30 query以上を維持する |
| Entry schema | すべての行に `persona`, `query`, `expected_artifact`, `must_include`, `must_not_claim`, `data_join_needed` がある |
| Source discipline | factual claimにsource、packet、manifest、snapshotのいずれかが付く |
| Gap discipline | 未収録、未確認、同名法人、stale source、0件の限界をgapとして残す |
| Next-question quality | 専門家、顧客、窓口、社内承認者へ渡せる質問に変換する |
| Transferability | README、稟議注記、顧客依頼文、DD質問、監視メモなどに転記できる短い部品を含む |
| Boundary | 専門判断の代替、保証、安全宣言、完全性宣言をしない |
