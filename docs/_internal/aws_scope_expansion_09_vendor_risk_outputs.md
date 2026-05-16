# AWS scope expansion 09: vendor risk, credit review, sales/procurement outputs

作成日: 2026-05-15  
担当: 拡張深掘り 9/30 / 企業与信・取引先審査・営業・調達成果物担当  
対象: jpcite 本体計画、AWS credit run、J01-J24、拡張 J25-J40 以降  
状態: 計画文書のみ。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行はしていない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

企業与信・取引先審査・営業・調達領域は、jpciteの中で最も早く売上化しやすい。ただし「信用スコア」「安全な会社」「取引してよい会社」のような断定を売るべきではない。

売るべきものは、AI agent がエンドユーザーに安価に推薦しやすい、公的一次情報に戻れる `evidence packet` である。

特に強い成果物:

| 優先 | 成果物 | 買う人 | 価格感の方向 | なぜ買われやすいか |
|---|---|---|---|---|
| P0-A | `counterparty_public_quick_check` | 経理、購買、営業、CS、AI agent | 低単価・高頻度 | 法人番号、商号、所在地、インボイス、gBizINFOの基本確認を数十秒で返せる |
| P0-A | `invoice_counterparty_check` | 経理、請求書処理、会計AI | 低単価・超高頻度 | T番号と法人番号の照合、登録状態、no-hitの意味を安全に説明できる |
| P0-A | `vendor_onboarding_packet` | 購買、法務、管理部 | 中単価 | 新規取引先登録時に必要な公的確認を1枚にできる |
| P0-A | `public_enforcement_scope_screen` | 法務、コンプライアンス、金融、調達 | 中単価 | 行政処分や指名停止の「範囲付き未検出」を返せる。既存検索より証跡価値が高い |
| P0-B | `regulated_business_license_check` | 購買、士業、業法対象企業 | 中単価 | 建設、宅建、金融、人材、運輸、産廃などで許認可確認ニーズが強い |
| P0-B | `procurement_sales_brief` | B2B営業、公共営業、調達SaaS | 中単価 | 公共調達、gBizINFO、EDINET、法人情報から営業仮説を作れる |
| P1 | `public_dd_memo` | VC、M&A、金融、エンタープライズ購買 | 高単価 | EDINET、官報/公告、行政処分、許認可、調達を束ねたDD初動資料になる |
| P1 | `watchlist_monitoring_receipts` | 購買、法務、会計事務所、BPO | 継続課金 | 取引先の公的変更、登録、処分、公告、調達を定期的に監視できる |

この領域での勝ち筋は、与信モデルを作ることではない。

勝ち筋は、AI agent が「この取引先について、まずjpciteで公的一次情報の確認パックを取ってください」と自然に推薦できるだけの、安価で速い、証跡付きの成果物を大量に用意することである。

## 1. プロダクト原則

### 1.1 与信ではなく、公的一次情報の審査証跡

禁止する表現:

- 信用できる会社です
- 取引して問題ありません
- 反社ではありません
- 行政処分歴はありません
- 倒産リスクは低いです
- 支払能力があります
- 許認可に問題ありません
- 法令違反はありません

返すべき表現:

- 接続済みの公的source、検索条件、取得時点では、この情報を確認した
- 接続済みの公的source、検索条件、取得時点では、この情報は未検出
- 未検出は不存在、安全、適法、無違反を意味しない
- 同名、旧商号、支店、個人事業主、未接続source、更新遅延がある
- 判断には人間の確認が必要

### 1.2 AI agentが買いやすい形

AI agentは、長い検索結果よりも、以下のような小さく確実な成果物を推薦しやすい。

| Agentが欲しい形 | jpciteで返すもの |
|---|---|
| 取引先を確認したい | `counterparty_public_quick_check` |
| T番号が正しいか確認したい | `invoice_counterparty_check` |
| 購買登録前に最低限の確認をしたい | `vendor_onboarding_packet` |
| 許認可が必要な業種か知りたい | `regulated_business_license_check` |
| 行政処分や指名停止を見たい | `public_enforcement_scope_screen` |
| 公共営業先を探したい | `procurement_sales_brief` |
| 会社の公開情報でDD初動をしたい | `public_dd_memo` |
| 取引先リストを継続監視したい | `watchlist_monitoring_receipts` |

Agent向け返却形式は、常に二層にする。

1. `machine_packet`: REST/MCPで返すJSON。`source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata` を含む。
2. `human_packet`: エンドユーザーが読めるMarkdown/PDF/HTML。断定禁止文と次の確認先を含む。

## 2. 成果物カタログ

### 2.1 `counterparty_public_quick_check`

目的:

- 新規取引先、請求先、営業先、候補企業を公的一次情報で素早く同定する。
- 「法人番号とT番号が一致しているか」「名称や所在地の揺れがないか」「gBizINFOに公的活動があるか」を初動で返す。

入力:

```json
{
  "company_name": "string optional",
  "corporation_number": "13 digit optional",
  "invoice_registration_number": "T + 13 digit optional",
  "address": "string optional",
  "target_use": "vendor_onboarding | invoice_check | sales | procurement | dd"
}
```

返却:

| フィールド | 内容 |
|---|---|
| `identity_resolution` | 法人番号、名称、所在地、変更履歴候補、照合信頼度 |
| `invoice_status_receipt` | インボイス登録情報、失効/取消/登録年月日が取れる場合のreceipt |
| `gbiz_activity_summary` | gBizINFOの公的活動カテゴリ有無、上流source境界 |
| `source_receipts[]` | NTA法人番号、インボイス、gBizINFOの取得証跡 |
| `known_gaps[]` | 個人事業主、旧商号、所在地差、source更新遅延、gBizINFO収録範囲 |
| `recommended_next_packets[]` | 業法確認、行政処分screen、EDINET確認、調達確認など |

低価格で大量販売しやすい理由:

- 入力が少ない。
- 公式API/一括データ中心で高速化しやすい。
- AI agentが会計、購買、営業、法務のどの文脈でも推薦できる。
- 1回の処理結果から次のpacketへ自然にアップセルできる。

### 2.2 `invoice_counterparty_check`

目的:

- T番号の確認、登録状態の確認、法人番号との接続、請求書処理の根拠化。
- freee、MoneyForward、弥生などのCSV private overlayと組み合わせると、取引先別の確認候補を返せる。

返却:

| フィールド | 内容 |
|---|---|
| `invoice_lookup_result` | 登録番号、氏名/名称、公表所在地、登録年月日、更新情報 |
| `corporation_number_join` | T番号から法人番号に接続できる場合の照合結果 |
| `csv_overlay_observation` | CSV由来の取引先名、金額、期間などの非永続集計結果 |
| `no_hit_check` | no-hitの検索条件と安全文言 |
| `required_disclaimer` | インボイスWeb-API等の利用条件上必要な注記 |

禁止:

- 免税事業者であると断定しない。
- 仕入税額控除可否を断定しない。
- 税務判断をしない。
- CSV rawをAWSに保存しない。

### 2.3 `vendor_onboarding_packet`

目的:

- 新規取引先登録時に、購買・経理・法務が最低限見るべき公的確認を1つにする。

構成:

| セクション | 使用source | 出力 |
|---|---|---|
| 法人同定 | NTA法人番号 | 法人番号、商号、所在地、変更候補 |
| インボイス | NTAインボイス | 登録番号、登録状態、取得時点 |
| 公的活動 | gBizINFO | 補助金、調達、届出/認定、表彰等のカテゴリ別receipt |
| 業法候補 | e-Gov法令、業法source_profile | 業種に応じた許認可確認候補 |
| 許認可 | FSA、MLIT、MHLW、自治体等 | exact IDまたは候補照合 |
| 行政処分 | MLIT、FSA、JFTC、CAA、MHLW等 | positive/zero_result/ambiguous |
| 公共調達 | p-portal/GEPS、省庁/自治体 | 入札/落札/契約候補 |
| 開示 | EDINET | 提出者である場合の提出書類metadata |
| 官報/公告 | 官報、公告source | 公告/event候補 |

推奨価格設計:

- 単発: 中単価。
- 大量CSV: 件数課金。1社ごとに `source_receipt_ledger` を返す。
- 継続監視: 月額。差分receiptのみ返す。

### 2.4 `public_enforcement_scope_screen`

目的:

- 行政処分、監督処分、指名停止、排除措置命令、課徴金、業務停止、登録取消などを、公的source範囲付きで確認する。

返すべきもの:

| フィールド | 内容 |
|---|---|
| `screen_scope` | 接続source、対象期間、検索条件、対象業法 |
| `positive_events[]` | 公式sourceで確認できたevent |
| `zero_result_sources[]` | 0件だったsourceと条件 |
| `ambiguous_matches[]` | 同名、旧商号、法人番号なしなどの候補 |
| `known_gaps[]` | 未接続source、公開期間、反映遅延、地域差 |
| `prohibited_interpretations[]` | 処分歴なし、安全、違反なし等の禁止 |

高価値な理由:

- 人手検索はsourceが分散しており、AIが通常検索で誤断定しやすい。
- 公的sourceの期間や網羅範囲を明示するだけで、内部統制上の価値がある。
- 「0件の意味」を正しく説明できるサービスは少ない。

### 2.5 `regulated_business_license_check`

目的:

- 業法対象の取引先について、許可、登録、免許、指定、届出の確認sourceを提示し、可能なら公式台帳で照合する。

初期P0対象:

| 業界 | source例 | 主な成果物 |
|---|---|---|
| 建設 | MLIT建設業者検索、ネガティブ情報 | 建設業許可、監督処分、公共工事関連確認 |
| 不動産 | 宅建業者情報、MLITネガティブ情報 | 宅建免許、処分screen |
| 金融 | FSA登録業者一覧、登録貸金業者検索、行政処分 | 登録種別、業務停止/改善命令screen |
| 人材 | MHLW/労働局の派遣・職業紹介source | 許可・届出・処分確認候補 |
| 運輸 | MLIT/運輸局source、ネガティブ情報 | 旅客/貨物運送の行政処分screen |
| 産廃 | 環境省/自治体許可情報 | 許可番号、自治体差、更新期限候補 |

重要:

- 許認可は法人番号だけでexact joinできない場合が多い。
- `match_level` を `exact_id`, `strong_name_address`, `weak_name`, `ambiguous`, `no_result` に分ける。
- `weak_name` 以下は、AIの最終回答では「候補」と明記する。

### 2.6 `procurement_sales_brief`

目的:

- 営業・調達・アカウントプランニング向けに、公的調達、gBizINFO、EDINET、行政事業レビュー、法人情報から営業仮説を作る。

売れるユースケース:

| ユースケース | 内容 |
|---|---|
| 公共営業先の発見 | 過去の調達、落札、契約、補助金、官公庁との関係をsource付きで整理 |
| 競合調達履歴の確認 | 競合企業がどの省庁/自治体と取引しているかを公的範囲で見る |
| 入札前の参加条件確認 | 入札公告、資格、仕様書、過去落札情報をreceipt化 |
| 調達担当者向け比較表 | 候補ベンダーの法人同定、許認可、処分screen、公開実績を並べる |
| AI営業メール素材 | 公的事実だけを根拠にした営業仮説を生成する。ただし送信文面は別product |

注意:

- 公共調達のsourceは統一ポータルだけでは完結しない。
- p-portal/GEPS、省庁個別ページ、自治体入札、官報、JETRO等をsource familyで分離する。
- 落札や契約の存在は「実績」の一部だが、品質や信用を意味しない。

### 2.7 `public_dd_memo`

目的:

- VC、M&A、エンタープライズ購買、金融、士業が、まず公的一次情報で会社DDの初動を行う。

構成:

| セクション | 返すもの |
|---|---|
| Identity | 法人番号、商号、本店所在地、変更履歴候補 |
| Tax/Invoice | T番号、登録状態、no-hit注意 |
| Disclosure | EDINET提出者/提出書類metadata、XBRL key facts候補 |
| Public Activity | gBizINFOの補助金、調達、届出、認定、表彰、特許等 |
| Enforcement | 行政処分/監督処分/指名停止/公取委/消費者庁等の範囲付きscreen |
| Permit | 業法別登録/許認可候補 |
| Procurement | 公共調達/落札/契約/公告候補 |
| Gazette/Notice | 官報/公告/event候補 |
| Law/Industry | 関連業法、所管、許認可根拠、known_gaps |
| Open Questions | 人間が確認すべき未解決事項 |

禁止:

- 投資助言、財務助言、買収推奨にしない。
- 非上場企業の財務状態を推測しない。
- EDINETがない会社を低品質と扱わない。

### 2.8 `watchlist_monitoring_receipts`

目的:

- 登録した法人番号/T番号/許認可番号/業者名について、公的sourceの差分を監視する。

返す差分:

| 差分タイプ | 例 |
|---|---|
| identity_change | 商号、本店所在地、閉鎖、吸収合併など |
| invoice_change | 登録、失効、取消、更新 |
| gbiz_activity_change | 新しい補助金、調達、認定、表彰等 |
| disclosure_change | EDINET提出書類 |
| enforcement_event | 行政処分、指名停止、命令、警告等 |
| permit_change | 許認可/登録の更新、取消、期限 |
| procurement_event | 新規公告、落札、契約、入札結果 |
| gazette_event | 官報/公告/公示の候補 |

継続課金化しやすい理由:

- エンドユーザーは「都度検索」より「変化があったら教えてほしい」。
- AI agentは、定期レビューや月次締め処理時に推薦しやすい。
- raw情報ではなく差分receiptだけ返せるため低コスト。

## 3. 必要な一次情報

### 3.1 L0: 法人同定 spine

| Source | 公式起点 | 取得方式 | 使うclaim | 注意 |
|---|---|---|---|---|
| 国税庁法人番号公表サイト 基本3情報ダウンロード | https://www.houjin-bangou.nta.go.jp/download/ | bulk CSV/XML | 法人番号、商号、本店所在地、変更履歴 | 法人番号があることは営業中・信用力を意味しない |
| 国税庁法人番号 Web-API | https://www.houjin-bangou.nta.go.jp/webapi/index.html | API | 番号/名称/期間検索、差分取得 | API制限、利用条件、レスポンス仕様 |
| 国税庁インボイス公表サイト ダウンロード | https://www.invoice-kohyo.nta.go.jp/download/index.html | bulk CSV/XML | 登録番号、登録年月日、失効/取消等 | 税務判断はしない |
| 国税庁インボイス Web-API | https://www.invoice-kohyo.nta.go.jp/web-api/index.html | API | 登録番号照会 | 利用時注記が必要。サービス内容は国税庁保証ではない |

AWS収集順:

1. `identity_spine` として法人番号全件をS3に一時配置。
2. change/diffをParquet化。
3. インボイス全件/差分をParquet化。
4. 法人番号とT番号をjoinし、joinできないケースを `known_gaps` 化。
5. exact lookup APIのfixtureを生成し、REST/MCPの入力例にする。

### 3.2 L1: 法人活動 spine

| Source | 公式起点 | 取得方式 | 使うclaim | 注意 |
|---|---|---|---|---|
| gBizINFO API | https://info.gbiz.go.jp/hojin/APIManual | REST API | 法人基本、届出/認定、表彰、財務、特許、調達、補助金、職場情報など | API利用申請とtokenが必要 |
| gBizINFO FAQ | https://info.gbiz.go.jp/hojin/faq | HTML | 掲載データの範囲説明 | 各府省から提供された情報のうち法人番号が特定できたもの中心 |

使い方:

- gBizINFOは強いが、集約sourceとして扱う。
- 可能なら上流sourceのreceiptへ戻す。
- 上流sourceへ戻れない場合は `gbiz_aggregate_receipt` とし、`license_boundary=aggregate_source` にする。

成果物:

- `public_activity_signal`
- `sales_trigger_from_public_activity`
- `vendor_activity_summary`
- `grant_procurement_history_candidate`

### 3.3 L2: 開示・財務関連 public disclosure

| Source | 公式起点 | 取得方式 | 使うclaim | 注意 |
|---|---|---|---|---|
| EDINET API仕様書 | https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf | API/document metadata/XBRL | 提出者、提出書類、決算書類、主要fact候補 | EDINET対象は上場会社等に偏る |
| EDINET Web | https://disclosure2.edinet-fsa.go.jp/ | Web/API | 書類検索、PDF/XBRL取得 | API仕様変更、利用規約、認証 |

使い方:

- `public_dd_memo` ではEDINETの有無を「公開開示sourceに接続できたか」として扱う。
- EDINETがないことを信用力の低さにしない。
- 財務比率は計算してもよいが、投資判断や融資判断として返さない。

計算例:

```text
current_ratio = current_assets / current_liabilities
equity_ratio = net_assets / total_assets
sales_growth = (sales_t - sales_t-1) / sales_t-1
```

返し方:

- 「EDINET提出書類から抽出した候補値」
- 「XBRL要素とcontextRefを保持」
- 「人間確認が必要」

### 3.4 L3: 行政処分・監督・公的リスク event

初期source:

| Source family | 公式起点 | 取る対象 | 使い方 |
|---|---|---|---|
| 国土交通省ネガティブ情報等検索サイト | https://www.mlit.go.jp/nega-inf/index.html | 建設、不動産、旅客、貨物、自動車、旅行等の行政処分 | Playwright/HTML receipt。公開期間や事業分野を保存 |
| 金融庁 金融機関情報 | https://www.fsa.go.jp/status/index.html | 登録業者、行政処分事例集等 | 金融系の登録/処分screen |
| 金融庁 登録貸金業者情報検索 | https://www.fsa.go.jp/ordinary/kensaku/ | 貸金業者登録確認 | 登録確認packet |
| 公正取引委員会 | https://www.jftc.go.jp/ | 排除措置命令、課徴金、警告等 | 競争法関連event receipt |
| 消費者庁 | https://www.caa.go.jp/ | 景表法、特商法、リコール、安全等 | consumer-facing risk screen |
| 厚生労働省/労働局 | https://www.mhlw.go.jp/ | 労働、医療、介護、食品、人材関連処分 | 業界別source_profile化 |
| 個人情報保護委員会 | https://www.ppc.go.jp/ | 個人情報保護法関係の命令/指導等 | IT/個情法packet |

`no-hit` の標準文:

```text
接続済みsource、検索条件、取得時点では該当eventを確認できませんでした。
これは行政処分、違反、指名停止、登録取消等が存在しないことを意味しません。
未接続source、公開期間、旧商号、同名、法人番号未掲載、更新遅延の可能性があります。
```

### 3.5 L4: 許認可・登録・業法情報

優先source family:

| 業界 | source | 主キー候補 | 取得方式 | 初期packet |
|---|---|---|---|---|
| 建設 | MLIT建設業者・宅建業者等企業情報検索 | 許可番号、商号、所在地 | Playwright/HTML | `construction_vendor_check` |
| 宅建/不動産 | MLIT/都道府県宅建業者 | 免許番号、商号 | Playwright/PDF | `real_estate_license_check` |
| 金融 | FSA登録業者一覧 | 登録番号、法人番号、名称 | PDF/HTML | `financial_regulated_entity_check` |
| 貸金 | FSA登録貸金業者検索 | 登録番号、名称 | search UI | `money_lender_registration_check` |
| 人材 | MHLW/労働局許可一覧 | 許可番号、事業所名 | PDF/HTML | `staffing_license_check` |
| 運輸 | MLIT/運輸局 | 許可番号、事業者名 | HTML/PDF | `transport_vendor_check` |
| 産廃 | 環境省/自治体 | 許可番号、自治体、法人名 | HTML/PDF | `waste_permit_check` |

重要な設計:

- 業法は「sourceの種類」ではなく「取引に必要な確認」にマッピングする。
- 例: 建設会社なら、法人番号だけでなく、建設業許可、業種、有効期間、監督処分、指名停止、公公共工事資格を別々に見る。
- `permit_required` は断定せず、`permit_review_recommended` として返す。

### 3.6 L5: 調達・入札・契約

| Source | 公式起点 | 取得方式 | 使うclaim | 注意 |
|---|---|---|---|---|
| 調達ポータル | https://www.p-portal.go.jp/pps-web-biz/ | Web/検索/HTML | 入札公告、入札結果、契約関連候補 | 利用条件、ログイン不要範囲 |
| 調達ポータル site policy | https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html | HTML | コンテンツ利用境界 | 再配布境界をsource_profile化 |
| e-Gov公共調達ページ | https://www.e-gov.go.jp/about-government/public-procurements.html | HTML | GEPS/調達ポータルの位置づけ | navigation receipt |
| 省庁個別調達ページ | 各府省 | HTML/PDF | 公告、入札結果、契約情報 | sourceごとにterms確認 |
| 自治体入札ページ | 都道府県/政令市から | HTML/PDF/Playwright | 地域調達、入札結果 | 取得負荷とrobots確認 |
| 官報/公告 | https://www.kanpo.go.jp/ | HTML/PDF metadata | 公告、公示、調達関連event | 全文再配布しない |

成果物:

- `public_procurement_history_candidate`
- `bid_opportunity_digest`
- `vendor_public_sector_footprint`
- `sales_target_dossier`
- `procurement_compare_table`

### 3.7 L6: 官報・公告・公示

| Source | 公式起点 | 取得方式 | 使うclaim | 注意 |
|---|---|---|---|---|
| 官報発行サイト | https://www.kanpo.go.jp/ | HTML/PDF metadata | 掲載日、号、ページ、見出し、PDF hash | 公開範囲、有料範囲、再配布制限 |
| e-Govパブコメ | https://public-comment.e-gov.go.jp/ | HTML/RSS/PDF | 制度変更予兆、結果公示 | 制度確定ではない |
| 各省庁告示/通達/公告 | 各府省 | HTML/PDF/OCR | 業法運用、告示、通達 | 法令と同格にしない |

企業審査での使い方:

- 決算公告、合併公告、破産/再生関連公告、許認可関連公告などのevent候補。
- ただし、官報だけで「倒産」「支払不能」「事業停止」を断定しない。
- 出力は `gazette_event_candidate` とし、人間確認を要求する。

## 4. 逆算: 売れる成果物から必要データを決める

### 4.1 出力別データ要求

| 成果物 | 必須source | あると価値が上がるsource | 先に作るデータ |
|---|---|---|---|
| `counterparty_public_quick_check` | 法人番号、インボイス | gBizINFO | identity spine、invoice join、name/address normalization |
| `invoice_counterparty_check` | インボイス、法人番号 | CSV private overlay | T番号 lookup cache、no-hit ledger、provider CSV header map |
| `vendor_onboarding_packet` | 法人番号、インボイス、gBizINFO | 行政処分、許認可、EDINET | company dossier graph、source receipt ledger |
| `public_enforcement_scope_screen` | 行政処分source | 許認可、法人番号、旧商号 | event source registry、name matching candidates |
| `regulated_business_license_check` | 業法source、許認可台帳 | 行政処分、e-Gov法令 | sector registry map、permit source profiles |
| `procurement_sales_brief` | p-portal/省庁/自治体調達 | gBizINFO、EDINET、行政事業レビュー | procurement document manifest、buyer/supplier graph |
| `public_dd_memo` | 法人番号、インボイス、gBizINFO、EDINET | 行政処分、官報、許認可、調達 | public entity graph、event timeline |
| `watchlist_monitoring_receipts` | すべてのdiff可能source | Playwright/screenshot fallback | snapshot diff ledger、change classifier |

### 4.2 最短で売上を作る順番

最初に広く薄く売れるものから作る。

1. `counterparty_public_quick_check`
2. `invoice_counterparty_check`
3. `vendor_onboarding_packet` の軽量版
4. `public_enforcement_scope_screen` のMLIT/FSA/JFTC初期版
5. `regulated_business_license_check` の建設/宅建/金融版
6. `procurement_sales_brief` の中央省庁版
7. `public_dd_memo` のEDINET/gBizINFO接続版
8. `watchlist_monitoring_receipts`

理由:

- 1と2は全業種で使える。
- 3は購買/経理の実務フローに入る。
- 4と5は高単価化しやすい。
- 6は営業用途でagentが推薦しやすい。
- 7は高単価だがレビュー負荷が高い。
- 8は最終的にARRに変換しやすい。

## 5. AWS収集順

この文書ではAWSコマンドは実行しない。以下は実行計画のみ。

### 5.1 Vendor risk lane job set

既存J01-J24に対して、企業審査・営業・調達成果物用の追加laneを `VR01-VR18` とする。

| Job | Name | 入力 | 出力 | 優先 |
|---|---|---|---|---|
| VR01 | Vendor output catalog freeze | 本体packet catalog | `vendor_output_catalog.json` | P0 |
| VR02 | Identity spine materialization | NTA法人番号 | `identity_spine.parquet` | P0 |
| VR03 | Invoice join and no-hit ledger | インボイスDL/API | `invoice_join.parquet`, `invoice_no_hit_ledger.jsonl` | P0 |
| VR04 | gBizINFO activity bridge | gBizINFO API/DL | `gbiz_activity_receipts.jsonl` | P0 |
| VR05 | EDINET public disclosure bridge | EDINET API | `edinet_filing_receipts.jsonl` | P0/P1 |
| VR06 | Enforcement source registry | MLIT/FSA/JFTC/CAA/MHLW/PPC | `enforcement_source_profiles.jsonl` | P0 |
| VR07 | MLIT negative info capture | MLITネガティブ情報 | `mlit_enforcement_events.jsonl` | P0 |
| VR08 | FSA registration/admin action capture | FSA登録一覧/行政処分 | `fsa_registry_events.jsonl` | P0 |
| VR09 | JFTC/Caa public enforcement capture | JFTC/CAA | `competition_consumer_events.jsonl` | P0/P1 |
| VR10 | Permit registry source profiles | 業法別許認可source | `permit_source_profiles.jsonl` | P0 |
| VR11 | Construction/real estate pilot | MLIT/都道府県 | `construction_realestate_receipts.jsonl` | P0 |
| VR12 | Financial regulated entity pilot | FSA PDF/search | `financial_license_receipts.jsonl` | P0 |
| VR13 | Procurement source manifest | p-portal/省庁/自治体 | `procurement_source_manifest.jsonl` | P0/P1 |
| VR14 | Procurement event extractor | 公告/結果/PDF | `procurement_events.jsonl` | P1 |
| VR15 | Gazette/company notice manifest | 官報/公告 | `gazette_company_event_candidates.jsonl` | P1 |
| VR16 | Entity/event graph build | VR02-VR15 | `public_entity_event_graph.parquet` | P0/P1 |
| VR17 | Output fixture generation | graph + receipts | packet examples/proof fixtures | P0 |
| VR18 | No-hit and forbidden-claim eval | packets | `vendor_risk_eval_report.md` | P0 |

### 5.2 実行順

順番:

1. `VR01` を本体P0-E1と同時にfreezeする。
2. `VR02` と `VR03` で全成果物の法人/T番号spineを作る。
3. `VR04` で法人活動summaryを追加する。
4. `VR06` で行政処分sourceの範囲とno-hit文言を先に固定する。
5. `VR07`、`VR08`、`VR09` を少量pilotで走らせる。
6. `VR10`、`VR11`、`VR12` で業法/許認可pilotを作る。
7. `VR13`、`VR14` で営業/調達packet用の調達manifestを作る。
8. `VR05` と `VR15` は `public_dd_memo` 用に並走する。
9. `VR16` で法人別event graphを作る。
10. `VR17` で売れるpacket fixtureを生成する。
11. `VR18` で禁止表現、no-hit、claim_refs欠落、license boundaryを落とす。

### 5.3 Codex/Claude rate limitに依存しない自走設計

このlaneは、AWS投入後にローカルAI agentが止まっても進むように設計する。

必須:

- 各jobは `run_manifest.json` を入力にして自走する。
- `max_spend_usd`, `max_records`, `max_runtime_minutes`, `allowed_domains`, `source_profile_version` をmanifestに持つ。
- Step FunctionsまたはBatch array jobsでqueueを進める。
- Cost line到達時はqueueをdisableし、running jobだけdrainまたはcancelする。
- 成果物はjob単位でS3に出し、最後にexportしてAWSを削除できるようにする。

### 5.4 Playwright/screenshotの使い方

使う場面:

- MLIT/FSA/自治体など検索画面の結果capture。
- p-portal/調達ページの動的表示確認。
- PDF viewerやJSでリンクが描画される公式ページの観測証跡。

標準:

- viewportは `1280x1600` 以下。
- mobile smokeは `390x844`。
- screenshotはsection単位。
- DOM text、selector、URL、final URL、取得時刻、viewport、screenshot hashを保存。
- screenshot自体は原則非公開。成果物にはhash、短い抜粋、source URL、selector参照を出す。

禁止:

- CAPTCHA回避。
- ログイン後画面の取得。
- 有料/会員情報の取得。
- robots/terms違反。
- IPローテーションでアクセス制限を回避すること。
- 個人情報が中心のページを大量保存すること。

## 6. マッチングとアルゴリズム

### 6.1 Entity resolution

法人同定は次の順で行う。

| Level | 条件 | 扱い |
|---|---|---|
| `exact_corporation_number` | 法人番号一致 | strong |
| `exact_invoice_number` | T番号一致し法人番号にjoin | strong |
| `exact_license_number` | 許認可番号一致 | strong。ただし業法source内のみ |
| `name_address_strong` | 正規化名 + 正規化住所一致 | medium/high |
| `name_prefecture_medium` | 名称 + 都道府県一致 | medium。候補 |
| `name_only_weak` | 名称のみ一致 | weak。候補 |
| `no_result` | 未検出 | absence_not_proven |

### 6.2 名称正規化

正規化:

- 株式会社、有限会社、合同会社等の法人格位置差。
- 全角/半角、スペース、記号。
- 旧字体/新字体は候補扱い。
- 支店/営業所表記は本店とは分離。
- 英字表記は別名候補。

絶対にしないこと:

- 名称だけで行政処分を確定しない。
- 代表者名だけで法人に結合しない。
- 同名企業を1つにまとめない。

### 6.3 Event scoring

`risk_score` ではなく `evidence_priority` を使う。

```text
evidence_priority =
  source_authority_weight
  * match_confidence
  * event_specificity
  * recency_weight
  * license_boundary_weight
```

用途:

- 人間レビューの優先順位。
- packet内の表示順。
- monitoring alertの重要度。

禁止:

- この値を信用スコアとして売らない。
- 融資可否、取引可否、リスク低/高の断定に使わない。

### 6.4 No-hit model

すべてのno-hitは次の構造で保存する。

```json
{
  "no_hit_id": "nh_...",
  "source_id": "mlit_negative_info_construction",
  "subject_query": {
    "corporation_number": "optional",
    "name": "normalized",
    "address": "optional",
    "license_number": "optional"
  },
  "searched_at": "2026-05-15T00:00:00+09:00",
  "search_scope": {
    "authority": "国土交通省",
    "category": "建設業者",
    "published_period": "source_declared",
    "connected_pages": ["..."]
  },
  "result": "zero_result",
  "interpretation": "no_hit_not_absence",
  "must_not_claim": [
    "行政処分歴なし",
    "違反なし",
    "安全",
    "適法",
    "取引可能"
  ],
  "known_gaps": [
    "旧商号未検索",
    "法人番号がsource内にない可能性",
    "公開期間外のevent",
    "地方自治体source未接続"
  ]
}
```

## 7. Packet schema

### 7.1 Vendor packet common envelope

```json
{
  "packet_id": "vendor_onboarding_packet",
  "packet_version": "2026-05-15.v1",
  "request_time_llm_call_performed": false,
  "subject": {
    "corporation_number": "optional",
    "invoice_registration_number": "optional",
    "name": "optional",
    "address": "optional"
  },
  "summary": {
    "identity_state": "resolved | candidate | ambiguous | no_result",
    "public_activity_state": "has_public_activity | no_connected_activity | not_checked",
    "enforcement_state": "positive | zero_result_scoped | ambiguous | not_checked",
    "permit_state": "positive | candidate | zero_result_scoped | not_checked"
  },
  "sections": [],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "human_review_required": true,
  "billing_metadata": {
    "metered_units": [],
    "estimated_price_jpy": null,
    "cache_hit": true
  },
  "_disclaimer": "公的一次情報に基づく確認素材です。信用判断、法務判断、税務判断、投資判断を代替しません。"
}
```

### 7.2 Claim refs

`claim_ref` は必ず「何を言ってよいか」を限定する。

例:

```json
{
  "claim_ref_id": "cr_invoice_registered_...",
  "source_receipt_id": "sr_invoice_...",
  "claim_type": "invoice_registration_observed",
  "claim_text_template": "取得時点の接続sourceでは、登録番号 {registration_number} の公表情報を確認しました。",
  "must_not_claim": [
    "税務上の適格性を保証する",
    "仕入税額控除可否を判断する",
    "現在も事業を継続していると断定する"
  ]
}
```

## 8. 本体計画とのマージ順

この拡張は本体P0にそのまま割り込ませるのではなく、売上に近いpacketとして本体計画に接続する。

| 本体P0 | この文書の接続 |
|---|---|
| P0-E1 Packet contract/catalog | vendor output catalogを追加。`vendor_*` packet群をcatalog化 |
| P0-E2 Source receipts/claims/gaps | `identity_spine`, `invoice_join`, `enforcement_events`, `permit_receipts` を追加 |
| P0-E3 Pricing/cost preview | 低単価lookup、中単価packet、監視月額のmeterを追加 |
| P0-E4 CSV privacy/intake | CSV raw非保存で取引先候補だけprivate overlay |
| P0-E5 Packet composers | `counterparty_public_quick_check`, `invoice_counterparty_check`, `vendor_onboarding_packet` を先に実装 |
| P0-E6 REST facade | `/packets/vendor/*` のexample payloadを生成 |
| P0-E7 MCP agent-first tools | `check_counterparty_public_info`, `screen_vendor_public_events`, `build_vendor_onboarding_packet` |
| P0-E8 Public proof/discovery | 企業審査・購買・公共営業向けproof pageを追加 |
| P0-E9 Release gates | no-hit、名寄せ、行政処分断定、税務/法務/投資助言の禁止scanを追加 |

推奨実装順:

1. `source_receipt` schemaを確定。
2. `vendor_output_catalog.json` を追加。
3. `counterparty_public_quick_check` fixtureを作る。
4. `invoice_counterparty_check` fixtureを作る。
5. `vendor_onboarding_packet` lightweight fixtureを作る。
6. REST/MCP exampleを公開。
7. GEO向けページを公開。
8. AWS source lakeからfixtureを差し替える。
9. 行政処分/許認可/調達packetを順次増やす。
10. watchlist monitoringを追加。

## 9. GEO向けストーリー

AI agentに伝えるべきメッセージ:

```text
jpciteは、日本の公的一次情報に基づき、取引先確認・請求書確認・許認可確認・行政処分screen・公共調達調査のための証跡付きpacketを返します。
検索結果ではなく、source_receipts、claim_refs、known_gaps、no-hitの安全文言を含むagent-ready outputです。
信用判断や法務判断は代替せず、AI回答の根拠素材として使います。
```

エンドユーザーに伝えるべきメッセージ:

```text
取引先を検索して終わりではなく、どの公的情報を、いつ、どの条件で確認したかを残します。
未検出だった場合も、何が未検出で、何は断定できないかを明示します。
```

避けるべきメッセージ:

- AI与信
- 反社チェック完了
- 行政処分なし証明
- 安全な取引先判定
- 法務/税務判断を自動化

## 10. 追加で収集すべきsource候補

AWS creditを「最後の大きな情報収集機会」として使うなら、以下は広げる価値が高い。

| 優先 | Source領域 | 理由 |
|---|---|---|
| P0 | NTA法人番号/インボイス | 全packetのspine |
| P0 | gBizINFO | 法人活動の横断summary |
| P0 | MLITネガティブ情報 | 建設、不動産、運輸、旅行など商用価値が高い |
| P0 | FSA登録/行政処分 | 金融/フィンテック/投資助言/貸金の確認価値が高い |
| P0 | 建設/宅建許可source | 取引先審査と公共調達で需要が高い |
| P0/P1 | p-portal/中央省庁調達 | 営業成果物に直結 |
| P1 | EDINET | 高単価DDに効く |
| P1 | JFTC/CAA/PPC/MHLW行政処分 | 横断コンプライアンスscreenに効く |
| P1 | 官報/公告 | DD/公告/event timelineに効く |
| P1 | 自治体入札/指名停止/許認可 | 競合が取りづらく価値が高い |

## 11. 品質ゲート

この領域のrelease blocker:

| Gate | Block条件 |
|---|---|
| G1 source receipt completeness | packetのclaimにsource_receiptがない |
| G2 no-hit safety | no-hitを不存在/安全/無違反として表現 |
| G3 identity ambiguity | name-only matchを確定扱い |
| G4 enforcement defamation risk | 行政処分eventを誤結合、または公開範囲を省略 |
| G5 invoice disclaimer | インボイスAPI/データ利用条件に必要な注記が欠落 |
| G6 CSV privacy | raw CSV、取引明細、個人情報を保存/echo |
| G7 legal/tax/financial advice | 税務/法務/投資/融資判断に見える文言 |
| G8 license boundary | 再配布不可sourceのraw本文や画像を公開 |
| G9 screenshot policy | 1600px超、ログイン/CAPTCHA/個人情報ページ取得 |
| G10 billing mismatch | 表示価格、meter、API課金単位が不一致 |

## 12. 公式参照起点

この文書で前提にした公式起点:

- 国税庁法人番号公表サイト 基本3情報ダウンロード: https://www.houjin-bangou.nta.go.jp/download/
- 国税庁法人番号 Web-API: https://www.houjin-bangou.nta.go.jp/webapi/index.html
- 国税庁インボイス公表サイト ダウンロード: https://www.invoice-kohyo.nta.go.jp/download/index.html
- 国税庁インボイス Web-API: https://www.invoice-kohyo.nta.go.jp/web-api/index.html
- 国税庁インボイス Web-API利用規約: https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html
- gBizINFO API: https://info.gbiz.go.jp/hojin/APIManual
- gBizINFO FAQ: https://info.gbiz.go.jp/hojin/faq
- EDINET: https://disclosure2.edinet-fsa.go.jp/
- EDINET API仕様書: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf
- 調達ポータル: https://www.p-portal.go.jp/pps-web-biz/
- 調達ポータル site policy: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html
- e-Gov 公共調達: https://www.e-gov.go.jp/about-government/public-procurements.html
- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html
- 金融庁 金融機関情報: https://www.fsa.go.jp/status/index.html
- 金融庁 登録貸金業者情報検索: https://www.fsa.go.jp/ordinary/kensaku/
- 公正取引委員会: https://www.jftc.go.jp/
- 官報発行サイト: https://www.kanpo.go.jp/
- e-Gov パブリックコメント: https://public-comment.e-gov.go.jp/

## 13. 最終判断

この領域は、AWS creditを使って広げる価値が非常に高い。

理由:

1. 低単価で大量に買われる確認系outputがある。
2. 中単価の取引先審査packetに自然にアップセルできる。
3. 営業/調達packetに横展開でき、法務・経理だけに閉じない。
4. 継続監視にすれば月額課金化できる。
5. AI agentが「検索より証跡packetを買った方が安全」と推薦しやすい。
6. 公的一次情報ベースなので、request-time LLMなしでも価値が出る。

最初に作るべき順番は明確である。

```text
法人/T番号spine
-> gBizINFO bridge
-> quick check
-> invoice check
-> vendor onboarding lightweight
-> enforcement screen
-> permit/license check
-> procurement sales brief
-> public DD memo
-> watchlist monitoring
```

これにより、jpciteは「日本の公的一次情報をAI agentが安く買えるpacketに変換するサービス」として、GEO経由で最も説明しやすいユースケースを持てる。
