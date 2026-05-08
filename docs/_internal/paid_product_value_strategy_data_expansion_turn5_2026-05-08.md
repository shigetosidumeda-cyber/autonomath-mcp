# jpcite paid product value strategy - data expansion turn 5

Date: 2026-05-08
Scope: 追加情報収集で、jpcite の有料アウトプットをどこまで深くできるか

## 0. 結論

もっと情報収集すれば、価値はかなり上がる。

ただし、価値が上がるのは「件数が増えたとき」ではない。価値が上がるのは、次の4つが起きたときだけ。

1. 会社、制度、法令、処分、調達、採択、許認可を同じ案件IDや法人番号で結べる
2. その結合に根拠URL、取得日時、hash、license、confidence、known_gaps が付く
3. ユーザーの業務に近い完成物、つまり DD、月次レビュー、申請戦略、融資前確認、相談前パックに変換できる
4. 一度きりの検索ではなく、差分監視、月次digest、顧客フォルダ更新として何度も使われる

なので、次の段階の jpcite は「公的情報検索」では弱い。目指すべきは、**AI や士業/BPO が会社・顧客・案件について最初に叩く、公的根拠付き判断準備レイヤー**。

ユーザーが払う理由は、「検索できるから」ではなく、以下が一発で返るから。

- この会社について公的に確認できたこと
- この会社で使えそうな制度、税制、融資、補助金
- この会社で注意すべき処分、許認可、インボイス、調達、開示上の論点
- 公式根拠URL
- まだ確認できていない範囲
- 次に聞くべき質問
- 士業・BPO・AI agent がそのまま作業に入れるタスク分解

## 1. 今回の全エージェント統合結果

6エージェントの結論はかなり一致している。

| 観点 | 結論 |
|---|---|
| ペルソナ別価値 | 税理士、行政書士、社労士、補助金BPO、金融、M&A、AI agent は「検索結果」ではなく「確認票・戦略パック・DDパック・月次レビュー」を欲しがる |
| 追加 source | P0 は法人番号、インボイス、EDINET、gBizINFO、調達、行政処分、地方制度、税務/法令、融資/保証 |
| データ構造 | 現在値 table ではなく entity / identifier / fact / event / edge / receipt / watch_delta で持つべき |
| ROI | 法人spine、インボイス履歴、行政処分、地方制度/融資、調達、EDINET が最短で売上に効く |
| 画面 | Home / Products / Playground / Pricing / Widget / Advisors は機能名より「完成物サンプル」を主役にするべき |
| 収集運用 | 1000エージェント規模でも、source_profile -> license gate -> artifact coverage delta -> ETL backlog -> QA -> staged release の工場にする |

## 2. 追加情報収集で価値が跳ねる領域

### 2.1 会社の公的ベースライン

入力:

- 法人番号
- T番号
- 会社名
- 所在地
- EDINETコード
- gBizINFO identifier
- 証券コード
- 顧客タグ

突き合わせ:

- 法人番号公表情報
- インボイス登録状態と履歴
- EDINET提出者情報と提出書類
- gBizINFO の法人活動情報
- 調達落札
- 補助金採択
- 行政処分
- 許認可

出せるもの:

- `company_public_baseline`
- `company_public_audit_pack`
- `houjin_dd_pack`
- `counterparty_public_check_memo`
- `monthly_company_watch_digest`

課金される理由:

- 会社フォルダを作るたびに必要
- M&A、融資、取引先確認、顧問先管理、BPO受付で横断して使える
- 1回だけでなく毎月差分監視にできる

### 2.2 決算前・月次レビュー

入力:

- 顧問先CSV
- 法人番号
- 業種
- 都道府県
- 決算月
- 従業員数
- 設備投資予定
- 賃上げ予定
- 研究開発/海外展開/採用予定

突き合わせ:

- 税制
- NTA通達
- KFS
- e-Gov法令改正
- 補助金
- 融資
- 信用保証
- 地方制度
- 厚労省助成金

出せるもの:

- `pre_kessan_tax_and_subsidy_calendar`
- `tax_client_impact_memo`
- `monthly_client_opportunity_digest`
- `wage_increase_check_sheet`
- `equipment_investment_support_pack`

課金される理由:

- 税理士やBPOは顧問先単位で繰り返し使う
- 「見落とし防止」に近い価値なので継続しやすい
- 1社3円ではなく、50社、200社、1000社のバッチで自然に利用が増える

### 2.3 補助金・融資・保証の申請戦略

入力:

- 法人番号
- 地域
- 業種
- 投資額
- 資金使途
- 既存借入
- 自己資金
- 予定時期
- 事業課題

突き合わせ:

- 国の補助金
- 自治体制度
- JFC
- 信用保証協会
- SMRJ
- METI/MAFF制度
- 採択事例
- 法令/通達
- 除外条件

出せるもの:

- `application_strategy_pack`
- `subsidy_fit_and_exclusion_pack`
- `loan_public_support_note`
- `required_document_checklist`
- `application_interview_sheet`

課金される理由:

- 補助金BPOが初回ヒアリングの前に使う
- 行政書士や診断士が、制度候補だけでなく「なぜ候補か」「何を聞くべきか」を欲しがる
- 中小企業にも「この条件なら何から試すか」が伝わりやすい

### 2.4 行政処分・許認可・労務リスク

入力:

- 法人番号
- 会社名
- 所在地
- 業種
- 許可番号
- 建設業/運送/介護/飲食/金融/不動産などの業種軸

突き合わせ:

- FSA
- JFTC
- MHLW
- MLIT
- PPC
- CAA
- 地方自治体の処分情報
- 許認可台帳
- 労働局情報

出せるもの:

- `permit_and_enforcement_check`
- `vendor_public_risk_sheet`
- `ma_dd_public_risk_pack`
- `lender_public_risk_sheet`
- `monthly_risk_watch_digest`

課金される理由:

- 士業、金融、M&A、BPOの「怖い見落とし」に直結する
- ただし「安全」「問題なし」と断定してはいけない
- `確認できた範囲` と `未確認範囲` を明示すると、むしろ信頼が上がる

### 2.5 調達・公費収入・公的実績

入力:

- 法人番号
- 会社名
- 業種
- 地域
- 発注機関
- 案件種別

突き合わせ:

- 調達ポータル落札実績
- KKJ
- 行政事業レビュー
- gBizINFO調達情報
- 補助金採択
- 認定/表彰

出せるもの:

- `public_revenue_signal`
- `procurement_vendor_pack`
- `sales_target_dossier`
- `public_sector_track_record_pack`

課金される理由:

- 営業、与信、M&A、金融で「公的取引実績」は強いシグナルになる
- BPOやコンサルが営業リストを作る用途にも使える
- 既存検索より「法人単位でまとまる」ことに価値がある

## 3. 公式 source の現在確認

2026-05-08 時点で、以下の公的 source は追加収集・強化候補として現実的。

| Source | 確認できたこと | jpciteでの使い方 |
|---|---|---|
| 国税庁 法人番号 Web-API | REST方式で法人番号や法人名、差分情報を取得できる。利用サービスでは取得元明示が必要 | entity spine、商号/所在地/閉鎖/差分watch |
| 国税庁 インボイス Web-API | 登録番号指定、期間差分、履歴情報の取得系がある。取得元明示が必要 | T番号、登録/取消/失効、取引先確認 |
| gBizINFO REST API v2 | 法人基本、届出/認定、表彰、財務、特許、調達、補助金、職場情報を法人番号で取得できる。利用申請とAPIトークンが前提 | company baseline、採択/認定/調達/職場情報の補強 |
| e-Stat API | REST方式で統計表、メタ情報、統計データ、一括取得などが可能 | 業界/地域比較、理由書、DDの市場背景 |
| 調達ポータル | 落札実績オープンデータをCSV zipで提供。全件と差分がある | 調達実績、公費収入、営業/与信/DD |
| e-Gov法令検索 | XML一括ダウンロードと法令APIがある。法令APIは一覧、法令取得、条文内容取得、更新法令一覧などを提供 | 法令根拠、改正watch、税務/許認可/制度の根拠 |

参照:

- https://www.houjin-bangou.nta.go.jp/webapi/index.html
- https://www.invoice-kohyo.nta.go.jp/web-api/index.html
- https://content.info.gbiz.go.jp/api/index.html
- https://www.e-stat.go.jp/api/index.php/api-info
- https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201
- https://laws.e-gov.go.jp/bulkdownload/
- https://laws.e-gov.go.jp/file/houreiapi_shiyosyo.pdf

## 4. データ構造はこう持つ

追加情報収集を本当に価値にするには、source別tableを増やすだけでは足りない。

中核は次のモデル。

```text
Entity      会社、制度、法令、許認可、調達案件、専門家
Identifier  法人番号、T番号、EDINETコード、証券コード、gBiz ID、許可番号
Fact        source上で観測された属性
Event       採択、処分、登録、取消、提出、落札、改正などの出来事
Edge        Entity / Fact / Event 間の関係
Receipt     どのsourceをいつ取得し、どう根拠化したか
WatchDelta  前回から何が変わったか
```

### 4.1 必須 table / view

```sql
entity
identifier_assertion
source_document
source_receipt
fact_assertion
entity_event
entity_edge
known_gap
watch_delta
artifact_materialized_view
artifact_coverage_delta
```

現状の repo には近い部品が既にある。

- `entity_resolution_bridge_v2`
- `source_document`
- `extracted_fact`
- `cross_source_signal_layer`
- `invoice_status_history`
- `public_funding_ledger`
- `source_freshness_ledger`
- `customer_watches`
- `saved_searches`

次にやるべきは、新規思想を入れるより、これらを **paid artifact の sections と明示的に接続する**こと。

## 5. P0/P1/P2 の収集優先度

### P0 - すぐ有料価値になる

| Source family | 主キー | 価値化される成果物 |
|---|---|---|
| 法人番号 / インボイス | 法人番号、T番号 | 会社ベースライン、取引先確認、月次watch |
| EDINET | EDINETコード、法人番号 | DD、金融、上場企業確認 |
| gBizINFO | 法人番号 | 認定、補助金、調達、職場情報の横断補強 |
| 調達ポータル / KKJ | 法人番号、契約番号、発注機関 | 調達実績、公費収入、営業リスト |
| 行政処分 | 法人番号、名称住所、処分日、機関 | DD、金融、許認可確認、risk watch |
| 地方制度 / 信用保証 / JFC | 自治体コード、制度ID、業種 | 補助金BPO、融資前確認、月次提案 |
| NTA / KFS / e-Gov | 法令ID、条文、通達ID、裁決番号 | 税務メモ、根拠付き回答、改正watch |

### P1 - 高単価化に効く

| Source family | 価値 |
|---|---|
| 許認可台帳 | 建設、運送、介護、不動産、飲食など業界別DD |
| 認定/表彰/健康経営/BCP | 信用シグナル、営業、DD |
| AMED/NEDO/JST/SBIR | R&D企業、大学発VB、技術DD |
| J-PlatPat/IP | 知財DD、競合調査 |
| e-Stat/BOJ | 業界/地域比較、理由書の背景 |
| 専門家registry | 相談前パック、専門家レビュー導線 |

### P2 - link-only / metadata-only から

| Source family | 方針 |
|---|---|
| 官報 | metadata / deep link / derived event に限定 |
| 商業登記 | on-demand 派生event中心、bulk raw再配布はしない |
| TDB/TSR等 | pointer / link-only |
| 民間有料DB | 本文取得しない |
| SNS/個人プロフィール | 原則収集しない |

## 6. 1000エージェント規模の情報収集設計

1000エージェントを「それぞれ好きに調べる」にすると、ノイズと権利リスクが増える。

使い方は工場型にする。

| Wave | エージェント数目安 | 目的 | 成果物 |
|---|---:|---|---|
| Wave 0 | 20 | 受け入れ契約固定 | schema、JSONL contract、quarantine理由 |
| Wave 1 | 220 | 会社spine | source_profile、identifier_bridge、history mapping |
| Wave 2 | 200 | 税務/法令/調達 | law/tax/procurement mapping |
| Wave 3 | 240 | 地方制度/許認可/保証 | local_program、permit_registry、credit_program |
| Wave 4 | 100 | link-only/metadata-only | no_collect / link_only / metadata_only 判定 |
| Wave 5 | 100 | license/red-team | license_gate_findings |
| Wave 6 | 80 | entity/event graph | entity_bridge_edges、event_mapping |
| Wave 7 | 40 | artifact coverage | artifact_coverage_delta |

### 6.1 エージェント提出物の標準

すべての調査成果物は、最低でもこれを出す。

```json
{
  "source_id": "...",
  "official_owner": "...",
  "source_url": "...",
  "source_type": "api|csv|html|pdf|zip|rss|manual",
  "data_objects": ["..."],
  "join_keys": ["houjin_bangou", "invoice_no", "edinet_code"],
  "license_or_terms": "...",
  "redistribution_risk": "low|medium|high",
  "acquisition_method": "...",
  "update_frequency": "...",
  "target_artifacts": ["company_public_baseline"],
  "artifact_sections_filled": ["identity", "risk_events"],
  "known_gaps_reduced": ["identifier_bridge_missing"],
  "new_known_gaps_created": ["license_unknown"],
  "sample_fields": ["..."],
  "checked_at": "2026-05-08"
}
```

## 7. ユーザーに刺さるアウトプットへ変換する

### 7.1 税理士

より深い出力:

- 顧問先50社の決算月別チェック
- 設備投資、賃上げ、研究開発、交際費、インボイス、電子帳簿保存、税制改正の影響
- 「この会社は何を聞くべきか」まで出す

画面名:

- `決算前 公的根拠チェック`
- `顧問先 月次制度レビュー`
- `税制・補助金・助成金 取りこぼし確認`

### 7.2 行政書士 / 補助金BPO

より深い出力:

- 申請可否の一次確認
- 公式URL付き候補制度
- 除外条件
- 必要書類
- 相談前質問
- 採択/類似事例
- 期限順の作業キュー

画面名:

- `申請戦略パック`
- `補助金BPO 受付キュー`
- `制度候補から必要書類まで`

### 7.3 社労士

より深い出力:

- 賃上げ、採用、研修、育休、雇用形態、労務リスクの確認票
- 厚労省助成金と地方制度の突合
- 行政処分/労働局情報は「確認範囲」として慎重に表示

画面名:

- `人件費・助成金 確認票`
- `労務制度 月次watch`

### 7.4 M&A / 金融 / 与信

より深い出力:

- 法人番号/T番号/EDINET/gBiz/調達/処分/許認可/採択の一括パック
- 何が確認済みで何が未確認か
- 前回DDからの差分

画面名:

- `公開情報DDパック`
- `取引先 公的リスク確認`
- `融資面談前 公的支援・注意点シート`

### 7.5 AI agent / BPO platform

より深い出力:

- API/MCPから会社フォルダを作る
- 顧客IDや案件IDで成果物を保存
- 実行前に unit 見積り
- confidence floor と known_gaps で自動処理/人間確認を分岐

画面名:

- `会社フォルダ自動作成`
- `公的根拠付き agent precheck`
- `BPO intake automation`

## 8. フロントで見せるべき「すごさ」

今後、画面は機能名ではなく成果物名を主役にする。

弱い見せ方:

- LINE bot
- Widget
- API
- 士業紹介
- 検索できます

強い見せ方:

- `会社公開ベースライン`
- `公開情報DDパック`
- `申請戦略パック`
- `顧問先月次レビュー`
- `相談前パック`
- `取引先公的リスク確認`

各ページでは、以下の形式で見せる。

```text
入力:
  法人番号、地域、業種、投資予定、決算月

出力:
  公式根拠URL付きの確認済み事実
  使えそうな制度
  注意点
  未確認範囲
  次に聞く質問
  そのまま送れる確認票

費用:
  この成果物は N units / 税込 ¥X 目安
```

## 9. 実装キュー

### Queue A - データ受け皿

1. `artifact_coverage_delta` のJSONL schemaを固定
2. `source_profile` に `target_artifacts` と `artifact_sections_filled` を追加
3. `known_gap` enumを整理
4. `source_receipt` completion scoreを artifact response に出す
5. `entity_event` と `entity_edge` を artifact で参照可能にする

### Queue B - P0収集

1. 法人番号差分
2. インボイス状態履歴
3. EDINET metadata
4. 調達ポータル全件/差分
5. FSA/JFTC/MHLW/MLIT 行政処分
6. 地方制度/JFC/信用保証
7. NTA/e-Gov/KFS

### Queue C - 有料成果物

1. `company_public_baseline` を見せ場化
2. `company_public_audit_pack` をDD向けに強化
3. `application_strategy_pack` に除外条件と必要書類を出す
4. `monthly_client_opportunity_digest` を顧問先CSV向けに作る
5. `expert_handoff_pack` を「相談前パック」に寄せる

### Queue D - 画面

1. Home hero直下に成果物サンプルを置く
2. Productsを機能一覧から成果物一覧へ寄せる
3. Playgroundにartifact endpointsを追加
4. Pricingを成果物別コスト目安にする
5. Widgetを「補助金診断リード」または「相談前パック」に変える
6. Advisorsを「専門家一覧」ではなく「根拠付き相談前パック」へ寄せる

## 10. やらないこと

情報収集を増やすほど、やらないことを明確にする必要がある。

- 件数自慢をフロントでしない
- 内部の saturation や未完成の収録状態をそのまま出さない
- 「問題なし」「安全」「採択される」と断定しない
- 官報PDFや商業登記をbulk raw再配布しない
- 民間信用DBの本文を持たない
- 個人事業主や個人名を雑に法人番号joinしない
- fuzzy match の低confidence結果をDDや処分系artifactで公開しない
- sourceが古いのに最新確認済みのように見せない

## 11. 次の一手

最短で価値が上がる順番はこれ。

1. `source_profile -> artifact_coverage_delta` を接続する
2. 追加sourceごとに「どの成果物のどのsectionが埋まるか」を自動集計する
3. 法人番号/T番号/EDINET/gBiz/調達/処分の company spine を優先する
4. `company_public_baseline` と `application_strategy_pack` をトップの見せ場にする
5. 顧問先CSV/会社フォルダ/案件タグを入力にして、単発検索から月次レビューへ寄せる
6. 1000エージェント収集は、P0 sourceのsource_profile、license、event mapping、artifact coverage deltaに集中する

この方向なら、jpcite は「検索API」ではなくなる。AIや士業/BPOが、会社や案件について最初に叩く公的根拠レイヤーになる。
