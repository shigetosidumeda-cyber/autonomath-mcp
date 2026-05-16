# AWS scope expansion 12: vertical high-value outputs

作成日: 2026-05-15  
担当: 拡張深掘り 12/30 / 専門業界別高単価成果物  
対象: 建設、不動産、運輸、人材、産廃、医療/介護、食品、金融、IT/個人情報、輸出入  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

このサービスは「公的一次情報を取っておいたら後から使える」だけでは弱い。売れる順番で考えるなら、最初に設計するべきなのは、エンドユーザーがAIに頼んだときにその場で欲しくなる成果物である。

AI agent側の自然な導線は次の形になる。

1. エンドユーザーがAIに「この会社と取引してよいか」「この業種で必要な許認可は何か」「この申請に足りないものは何か」と聞く。
2. AI agentは、検索結果だけでは断定できないため、公的一次情報の証跡付きpacketを探す。
3. jpciteがGEO/MCP/APIで見つかり、無料previewで「確認できる範囲、使う公的source、known_gaps、価格」を返す。
4. ユーザーが安い単発packetを買う、またはAI agentがAPI/MCP課金導線を推薦する。
5. 有料packetは `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`no_hit_not_absence`、`billing_metadata` を返し、AIが回答に安全に組み込める。

したがってAWSで優先すべき処理は、単なる広域収集ではなく「売れる成果物から逆算したsource lake」である。

優先順位は次でよい。

| Rank | Vertical | 先に作る高単価成果物 | 理由 |
|---:|---|---|---|
| 1 | 建設 | 取引先許可・処分screen、元請/下請確認、公共工事readiness | 許認可/処分/入札の公的情報が多く、AIが推薦しやすい |
| 2 | 不動産 | 宅建業者確認、賃貸住宅管理/マンション管理確認、物件周辺公的context | 取引単価が高く、確認ニーズが顕在 |
| 3 | 人材 | 派遣/職業紹介許可確認、行政処分screen、労務制度brief | 無許可/処分リスクが分かりやすく、B2B購買で売れる |
| 4 | 産廃 | 収集運搬/処分業許可確認、委託先DD、許可範囲確認 | 法令上の確認需要が強く、証跡の価値が高い |
| 5 | 運輸 | 運送事業許可/監査処分/安全関連screen | 荷主、物流委託、EC事業者が使いやすい |
| 6 | 金融 | 登録業者確認、行政処分screen、金融商品/貸金/資金移動の公的確認 | 高単価だが金融助言に見えない境界管理が必要 |
| 7 | 医療/介護 | 施設/事業所公表情報、指定/取消screen、地域サービス比較 | 価値は高いが、個人情報・品質評価禁止・自治体差に注意 |
| 8 | 食品 | 営業許可/リコール/食品表示・衛生制度brief | 自治体分散が大きい。まず公的リコールと制度確認から |
| 9 | IT/個人情報 | 個人情報保護/委託先チェック、認証/ガイドライン対応表 | 高単価だが「適法性保証」禁止。制度根拠packetで売る |
| 10 | 輸出入 | 輸出管理/制裁/関税/原産地/検疫の確認入口 | 高単価だが判断リスクが高い。public source navigationから始める |

価格は「エンドユーザーがAI経由で安く取れる」ことを前提にする。高単価とは、1件の単価を高くするだけではなく、AI agentが何度も呼びやすい、失敗しにくい、証跡付きpacketとして高い粗利を取れるという意味で扱う。

## 1. 共通商品設計

### 1.1 売れるpacketの基本形

| Packet | End user question | Paid value | Free preview |
|---|---|---|---|
| `regulated_counterparty_check` | この会社と取引して大丈夫そうか、公的情報で確認して | 法人同定、業界許認可候補、行政処分screen、source_receipts、known_gaps | source種別、確認できる項目、同定候補数、価格 |
| `license_registry_lookup` | この許可番号/登録番号は公的台帳で見つかるか | exact/fuzzy lookup、登録期間、管轄、表示source、no-hit説明 | exact lookup可否、必要入力、source一覧 |
| `administrative_action_screen` | 行政処分や取消が公表されているか範囲付きで見て | 接続済みsource、検索条件、positive hits、no-hit scope、誤結合警告 | 対象source/期間、positive件数だけの概要 |
| `application_readiness_packet` | 申請や開業のために何を準備するべきか | 法令/手引き/自治体source、必要書類候補、未確認項目、次の質問 | 必要そうな制度カテゴリ、主要source、概算価格 |
| `compliance_change_watch` | この業界の制度変更を追って | 法令、告示、通達、パブコメ、所管資料の時系列 | 直近更新数、source family一覧 |
| `vendor_onboarding_evidence_pack` | 社内稟議や委託先登録に使える証跡を出して | 1枚summary、JSON、receipt ledger、known_gaps、human review note | 生成可能な証跡項目、欠ける可能性 |
| `csv_overlay_review` | 会計CSVの取引先を公的情報で突合したい | raw CSV非保持、集計/候補のみ、インボイス/法人/業界source接続 | provider形式判定、列不足、取引先数の概算 |

### 1.2 価格帯の考え方

これは実装前の価格設計入力であり、最終料金表ではない。

| Tier | 価格目安 | 用途 | 課金しやすい理由 |
|---|---:|---|---|
| Free preview | 0円 | AIがユーザーへ推薦する前の確認 | 何が取れるかを見せ、ハルシネーションしない |
| Micro packet | 100-500円 | exact lookup、source receipt ledger、単一source確認 | AI agentが気軽に呼べる |
| Standard packet | 800-2,500円 | 取引先確認、許可/処分screen、申請readiness | 手作業調査より安い |
| Professional packet | 3,000-9,800円 | 業界別DD、複数source、CSV overlay、稟議用summary | B2Bで十分安く、証跡価値が高い |
| Monitoring | 30-300円/entity/月 | 変更watch、処分watch、期限watch | 継続収益になる |

無料previewは情報を出しすぎない。出すのは「jpciteで確認できる範囲」「使うsource」「known_gapsの種類」「価格」「入力不足」まで。有料部分は、具体的なreceipt、hit詳細、claim refs、export-ready JSON、稟議用summaryに置く。

### 1.3 全packetの安全境界

全業界で次を固定する。

- request-time LLMで一次情報を捏造しない。
- `request_time_llm_call_performed=false` を維持する。
- no-hitは必ず `no_hit_not_absence`。不存在、安全、適法、許可不要、処分歴なし、採択可能、融資可能とは言わない。
- 法律、会計、金融、医療判断そのものはしない。公的一次情報に基づく調査素材と証跡を返す。
- private CSVはAWSへ上げない。raw行、摘要、銀行/給与/個人識別子を保持しない。
- Playwright/screenshotは公開ページ観測の補助。CAPTCHA突破、ログイン突破、アクセス制限回避はしない。

## 2. AWSでの処理順

既存のJ01-J24に、縦割り高単価成果物のためのJ60-J79を追加するイメージで統合する。

### 2.1 実行順の全体像

| Phase | 先にやること | 理由 |
|---|---|---|
| F0 | AWS guardrails、Budgets、stop script、tag、zero-bill cleanup手順 | 使い切りに近く回すが、現金請求を防ぐ |
| F1 | packet contract、price/free preview、known_gaps enumを固定 | 後からデータが来ても商品化できる |
| F2 | source_profile/terms/robots/license ledger | 取得してよい範囲、公開できる範囲を先に決める |
| F3 | identity spine: 法人番号、インボイス、住所、商号正規化 | すべての業界確認のjoin基盤 |
| F4 | vertical P0 source取得: 建設、不動産、人材、産廃、運輸、金融 | 高単価packetに直結する |
| F5 | vertical P1 source取得: 医療/介護、食品、IT/個人情報、輸出入 | 価値は高いが境界管理が難しい |
| F6 | Playwright/screenshot lane | fetch困難な公的検索画面をreceipt化 |
| F7 | extraction、normalization、claim graph、no-hit ledger | 断定禁止とreceipt接続を保証 |
| F8 | packet fixture、proof page、OpenAPI/MCP examples | GEO/MCP/APIでAIが推薦できる形にする |
| F9 | deploy gate: privacy, forbidden claim, billing, discovery, render | 本番デプロイで詰まらないようにする |
| F10 | export、checksum、repo import、AWS zero-bill cleanup | クレジット消費後に請求を残さない |

### 2.2 追加AWS job案

| Job | Name | Input | Output | Priority |
|---|---|---|---|---|
| J60 | Vertical product catalog compiler | この文書、industry regulation map | `vertical_packet_catalog.jsonl` | P0 |
| J61 | Vertical source profile hardening | 公式source候補 | `vertical_source_profiles.jsonl`, terms ledger | P0 |
| J62 | Regulated entity identity resolver | 法人番号、許可番号、商号、住所 | `regulated_entity_candidates.parquet` | P0 |
| J63 | Construction and real estate lane | MLIT source, local source allowlist | permits, licenses, negative-info receipts | P0 |
| J64 | Staffing and labor lane | MHLW/labor bureau source | staffing license/action receipts | P0 |
| J65 | Waste and logistics lane | MOE/local/MLIT source | waste permits, transport action receipts | P0 |
| J66 | Financial registration lane | FSA/source lists | financial registrations/action receipts | P0 |
| J67 | Medical care and food lane | MHLW/local/CAA source | provider/food safety receipts | P1 |
| J68 | IT privacy and trade lane | PPC/METI/MIC/MOF/JETRO source | guideline, certification, export/import receipts | P1 |
| J69 | Playwright vertical capture | dynamic public pages | DOM, screenshot <=1600px, selector receipt | P0/P1 |
| J70 | Vertical no-hit scope generator | all vertical sources | `vertical_no_hit_rules.jsonl` | P0 |
| J71 | Vertical packet fixture factory | normalized facts, receipts | packet examples and proof candidates | P0 |
| J72 | Vertical pricing preview generator | packet catalog, source costs | free preview payloads and price matrix | P0 |
| J73 | Vertical GEO landing/proof generator | packet examples | AI-readable pages, llms, OpenAPI/MCP examples | P0 |
| J74 | Vertical release gate | all artifacts | privacy/forbidden claim/source coverage report | P0 |

## 3. Industry: 建設

### 3.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `construction_partner_check` | 元請、発注者、購買、会計事務所 | 1,500-4,800円 | 100-250円/entity/月 | 許可source、処分source、必要入力、同名候補数 |
| `construction_license_scope_packet` | AIに見積/契約前確認を頼むユーザー | 800-2,500円 | なし | 工事種別に必要そうな確認カテゴリ |
| `public_works_readiness_packet` | 建設会社、行政書士、BPO | 3,000-9,800円 | 200-300円/entity/月 | 経審/入札/指名停止source一覧 |
| `subcontractor_evidence_sheet` | 現場管理、購買 | 800-2,000円 | 100-200円/entity/月 | 法人/許可/処分screenが可能か |

### 3.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 建設業許可の確認 | 国交省/都道府県の建設業者検索、建設業許可制度資料 | HTML, Playwright fallback, PDF | 許可番号、許可行政庁、一般/特定、業種、有効期間 |
| 監督処分/指名停止 | 国交省ネガティブ情報、地方整備局、自治体 | HTML/PDF/OCR | 処分日、公表日、対象、根拠、範囲 |
| 公共工事readiness | 経営事項審査、入札参加資格、自治体入札 | HTML/PDF/Excel | 申請区分、年度、所管、必要資料 |
| 法制度根拠 | e-Gov法令、国交省手引き | API/PDF | 条文、通達、手引きURL、改正日 |

主な公式起点:

- 国土交通省 建設業者・宅建業者等企業情報検索システム: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- 国土交通省 建設業の許可制度: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000080.html
- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html

### 3.3 AWS処理順

1. 許可番号と法人番号/商号/所在地のjoin候補schemaを固定する。
2. 国交省sourceをAPI/HTML優先で取得し、必要ならPlaywrightで表示receiptを取る。
3. 処分/指名停止sourceはpositive event中心に保存する。
4. `construction_license_scope_packet` 用に、工事種別と許可業種の対応候補を法令/手引きに接続する。
5. no-hitは検索条件、許可行政庁、取得時点を必ず残す。

### 3.4 known_gaps

- 軽微工事、個人事業主、JV、支店、旧商号、許可行政庁差は自動断定しない。
- 許可検索0件は無許可の証明ではない。
- 処分検索0件は処分歴なしの証明ではない。
- 工事種別から必要許可を出す場合は、最終判断を行政書士/所管確認に送る。

## 4. Industry: 不動産

### 4.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `real_estate_broker_check` | 売主/買主、管理会社選定、士業 | 1,500-4,800円 | 100-250円/entity/月 | 宅建業者source、処分source、入力不足 |
| `property_area_public_context` | 不動産購入/出店検討 | 2,000-6,800円 | なし | 住所正規化、地価/災害/都市計画source候補 |
| `rental_management_license_check` | オーナー、管理会社選定 | 800-2,500円 | 100-200円/entity/月 | 管理業登録source確認 |
| `real_estate_transaction_evidence_sheet` | AIに契約前調査を頼む個人/法人 | 2,500-9,800円 | なし | 公的に確認できる範囲、known_gaps |

### 4.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 宅建業者/管理業者確認 | 国交省 建設業者・宅建業者等企業情報検索、賃貸住宅管理業者登録 | HTML/Playwright | 免許番号、免許行政庁、登録番号、有効期間 |
| 処分/監督情報 | 国交省ネガティブ情報、都道府県処分情報 | HTML/PDF/OCR | 処分対象、処分日、根拠、source範囲 |
| 物件周辺公的context | 国土数値情報、国土地理院、地価公示、不動産情報ライブラリ、ハザード系公的情報 | API/CSV/GeoJSON/HTML | 住所、緯度経度、行政区域、データ時点 |
| 制度根拠 | 宅建業法、マンション管理、賃貸住宅管理、都市計画/建築系 | e-Gov/PDF | 条文/手引き/所管URL |

主な公式起点:

- 国土交通省 建設業者・宅建業者等企業情報検索システム: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- 国土交通省 不動産情報ライブラリ: https://www.reinfolib.mlit.go.jp/
- 国土数値情報: https://nlftp.mlit.go.jp/ksj/
- 国土地理院: https://www.gsi.go.jp/

### 4.3 AWS処理順

1. 住所正規化、地理ID、行政区域を先に作る。
2. 宅建/管理業者registryをsource_profile化し、許可/免許/登録番号の正規化を行う。
3. 処分sourceをpositive event ledgerとして取得する。
4. 地理/地価/国土数値情報はpacketで使う派生factsだけを作る。
5. 物件に関する断定ではなく「公的context」としてproof page化する。

### 4.4 known_gaps

- 物件の法的適合性、契約リスク、価格妥当性は断定しない。
- 地理データの時点、縮尺、区域境界、住所ジオコーディングの不確実性を残す。
- 宅建業者検索0件は無免許の証明ではない。
- ハザードや都市計画はsourceごとに更新時点が異なる。

## 5. Industry: 運輸

### 5.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `logistics_partner_check` | 荷主、EC、メーカー、3PL | 1,500-4,800円 | 100-250円/entity/月 | 許認可/処分source、確認可能な事業区分 |
| `transport_admin_action_screen` | 購買、法務、コンプラ | 800-2,500円 | 100-200円/entity/月 | 接続済み監査/処分sourceと期間 |
| `fleet_business_permit_readiness` | 新規参入、行政書士 | 3,000-9,800円 | なし | 必要制度カテゴリ、所管source |
| `shipper_compliance_brief` | 荷主企業、物流担当 | 1,500-4,800円 | なし | 法令/ガイドラインsource一覧 |

### 5.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 運送事業の許認可/登録 | 国交省、運輸局、各種事業者情報 | HTML/PDF/Playwright | 事業区分、許可/登録番号、管轄、所在地 |
| 監査/行政処分 | 国交省ネガティブ情報、運輸局公表資料 | HTML/PDF/OCR | 処分日、対象、事業種別、違反概要 |
| 安全/制度根拠 | 貨物自動車運送事業法、旅客、倉庫、通達 | e-Gov/PDF | 条文、通達、所管、更新日 |
| 関連統計 | e-Stat、国交省統計 | API/CSV/PDF | 地域、業種、時点 |

主な公式起点:

- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html
- 国土交通省 自動車関連情報: https://www.mlit.go.jp/jidosha/
- e-Gov法令検索: https://elaws.e-gov.go.jp/

### 5.3 AWS処理順

1. 事業区分ごとのsource_profileを先に分ける。
2. 処分sourceは国交省共通sourceと地方運輸局sourceを分離する。
3. 法人番号/商号/所在地の同定候補を作るが、車両/運転者個人情報は取らない。
4. 荷主向けpacketは「委託前確認素材」として構成する。

### 5.4 known_gaps

- 運行安全性、事故リスク、契約適格性は断定しない。
- 地方運輸局ごとの公表形式差、反映遅延、商号変更を残す。
- 処分未検出は処分歴なしではない。
- 許可の有効性は台帳sourceの公表範囲内に限る。

## 6. Industry: 人材

### 6.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `staffing_agency_license_check` | 採用担当、購買、法務 | 1,500-4,800円 | 100-250円/entity/月 | 派遣/紹介source、許可番号入力要否 |
| `labor_admin_action_screen` | 委託先管理、コンプラ | 800-2,500円 | 100-200円/entity/月 | 処分source、期間、同定条件 |
| `recruiting_vendor_onboarding_pack` | 企業の採用/購買 | 2,500-6,800円 | 100-250円/entity/月 | 法人同定、許可、処分screen、known_gaps |
| `labor_rule_change_brief` | 社労士、管理部 | 1,500-4,800円 | 100-300円/topic/月 | 法令/通達/助成金source一覧 |

### 6.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 労働者派遣/職業紹介許可 | 厚労省、労働局の許可事業者情報 | HTML/PDF/CSV/Playwright | 許可番号、許可区分、有効期間、事業所 |
| 行政処分/指導公表 | 厚労省、労働局、公表資料 | HTML/PDF/OCR | 処分日、対象、根拠、範囲 |
| 労働法令/制度 | e-Gov、厚労省通達、助成金資料 | API/PDF | 条文、手引き、制度要件 |
| 助成金/補助 | 厚労省、J-Grants、自治体 | HTML/PDF/API | 対象、締切、必要書類、問い合わせ |

主な公式起点:

- 厚生労働省: https://www.mhlw.go.jp/
- e-Gov法令検索: https://elaws.e-gov.go.jp/
- e-Govパブリック・コメント: https://public-comment.e-gov.go.jp/

### 6.3 AWS処理順

1. 派遣/職業紹介/請負/業務委託の制度カテゴリを分ける。
2. 許可番号、事業所名、法人名、所在地の同定ルールを作る。
3. 行政処分sourceをsource_receipt化し、同名誤結合をhuman reviewに送る。
4. 助成金や労務制度は申請可否ではなく、制度候補packetにする。

### 6.4 known_gaps

- 適法な雇用形態、偽装請負判断、労務リスク判定はしない。
- 事業所単位と法人単位を混同しない。
- 許可検索0件は無許可の証明ではない。
- 処分未検出は問題なしではない。

## 7. Industry: 産廃

### 7.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `waste_vendor_permit_check` | 排出事業者、建設、メーカー、購買 | 2,500-7,800円 | 150-300円/entity/月 | 許可source、自治体範囲、必要入力 |
| `waste_scope_match_packet` | 委託先選定、現場管理 | 3,000-9,800円 | なし | 廃棄物種類/地域/許可区分の確認可能性 |
| `waste_admin_action_screen` | コンプラ、監査 | 1,500-4,800円 | 150-300円/entity/月 | 処分source、期間、同定条件 |
| `manifest_process_brief` | SMB、AI agent | 800-2,500円 | なし | 制度根拠sourceと未確認事項 |

### 7.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 産廃収集運搬/処分業許可 | 環境省、都道府県/政令市の許可業者情報 | HTML/PDF/Excel/Playwright | 許可番号、許可自治体、許可区分、品目、有効期間 |
| 行政処分 | 環境省、自治体公表資料 | HTML/PDF/OCR | 処分日、対象、処分内容、根拠 |
| 制度根拠 | 廃棄物処理法、環境省通知/手引き | e-Gov/PDF | 条文、手引き、所管 |
| 地域/自治体差 | 自治体source、条例/要綱 | allowlist crawl/Playwright | 自治体、URL、更新日 |

主な公式起点:

- 環境省: https://www.env.go.jp/
- e-Gov法令検索: https://elaws.e-gov.go.jp/
- 都道府県/政令市の産業廃棄物許可業者公表ページ

### 7.3 AWS処理順

1. 都道府県/政令市ごとのsource_profileと利用境界を先に作る。
2. 許可区分、品目、許可期限、自治体をschema化する。
3. Playwrightは検索フォーム型の自治体台帳だけに限定する。
4. 処分sourceはpositive event ledgerとして保存し、名称結合は慎重に扱う。
5. `waste_scope_match_packet` のために、廃棄物種類と許可品目の候補表を作る。

### 7.4 known_gaps

- 産廃委託の適法性や契約適合性は断定しない。
- 許可自治体、許可品目、積替保管有無、有効期間の欠落は致命的gapにする。
- 自治体ごとの公表形式差、更新遅延、PDFの古さを残す。
- 許可検索0件は無許可の証明ではない。

## 8. Industry: 医療 / 介護

### 8.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `medical_provider_public_baseline` | 患者支援AI、地域営業、士業 | 800-2,500円 | 50-150円/entity/月 | 医療機能source、指定source、known_gaps |
| `care_provider_public_baseline` | ケアマネ、自治体営業、介護事業者 | 800-2,500円 | 50-150円/entity/月 | 介護事業所source、サービス種別 |
| `healthcare_designation_check` | B2B購買、M&A下調べ | 1,500-4,800円 | 100-250円/entity/月 | 指定/公表sourceと入力不足 |
| `care_service_area_context` | 出店/営業/地域分析 | 2,500-7,800円 | なし | 地域/サービス/統計source候補 |

### 8.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 医療機関/薬局公表情報 | 医療機能情報提供制度、医療情報ネット | HTML/Playwright | 施設名、所在地、診療科、サービス、公表時点 |
| 保険医療機関/薬局指定 | 地方厚生局 | PDF/Excel/HTML | 医療機関コード、指定日、所在地 |
| 介護事業所情報 | 介護サービス情報公表システム、オープンデータ | CSV/HTML | 介護事業所番号、サービス種別、運営法人 |
| 指定取消/行政処分 | 厚労省、地方厚生局、自治体 | PDF/HTML/OCR | 処分日、対象、根拠 |

主な公式起点:

- 医療情報ネット ナビイ: https://www.iryou.teikyouseido.mhlw.go.jp/
- 厚生労働省 医療機能情報提供制度: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/teikyouseido/index.html
- 介護サービス情報公表システム: https://www.kaigokensaku.mhlw.go.jp/
- 厚生労働省 介護サービス情報の公表制度: https://www.mhlw.go.jp/stf/kaigo-kouhyou.html

### 8.3 AWS処理順

1. 医療機関コード、介護事業所番号、法人番号のjoin方針を分離する。
2. 施設/事業所単位の公表情報を取得するが、個人患者/職員情報は対象外にする。
3. 医療/介護は品質評価ではなく「公表情報の整理」に限定する。
4. 地域分析packetはe-Statや自治体統計と組み合わせる。

### 8.4 known_gaps

- 医療の質、治療成績、施設の安全性、介護サービスの良否は判断しない。
- 公表情報の更新時点、休止/廃止、自治体差を残す。
- 施設検索0件は存在しない証明ではない。
- 指定取消未検出は処分歴なしではない。

## 9. Industry: 食品

### 9.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `food_business_public_check` | 飲食店、EC食品、購買 | 800-2,500円 | 50-150円/entity/月 | 営業許可/自治体sourceの有無、known_gaps |
| `food_recall_and_safety_screen` | EC、メーカー、小売、消費者AI | 1,500-4,800円 | 100-250円/entity/月 | リコール/行政処分source、期間 |
| `food_labeling_rule_brief` | D2C、輸入食品、士業 | 1,500-4,800円 | なし | 表示制度source、未確認項目 |
| `restaurant_opening_readiness` | 開業者、行政書士 | 2,500-6,800円 | なし | 必要手続、自治体確認source |

### 9.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 営業許可/届出 | 自治体食品衛生ページ、食品衛生申請等システム関連情報 | HTML/PDF/Playwright | 業種、自治体、手続、source時点 |
| リコール/自主回収 | 消費者庁、厚労省、自治体 | HTML/API/PDF | 商品名、事業者、公表日、回収理由 |
| 食品表示/衛生制度 | 消費者庁、厚労省、e-Gov | HTML/PDF/API | 条文、ガイドライン、所管 |
| 輸入食品 | 厚労省検疫、税関、植物/動物検疫 | HTML/PDF | 対象品目、手続、所管 |

主な公式起点:

- 消費者庁: https://www.caa.go.jp/
- 厚生労働省 食品: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/
- 食品衛生申請等システム: https://ifas.mhlw.go.jp/
- e-Gov法令検索: https://elaws.e-gov.go.jp/

### 9.3 AWS処理順

1. 全国共通の制度/リコールsourceを先に取る。
2. 自治体営業許可sourceは都道府県/政令市からallowlistで広げる。
3. 商品/店舗名は誤結合しやすいため、positive hitはreview_requiredにする。
4. 食品表示packetは「確認すべき公的資料の整理」に限定する。

### 9.4 known_gaps

- 食品の安全性、表示適法性、販売可否、リコール対象外を断定しない。
- 営業許可は自治体差と公表範囲差が大きい。
- 店舗名/商品名の同名誤結合を警告する。
- リコール未検出は安全の証明ではない。

## 10. Industry: 金融

### 10.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `financial_registration_check` | 投資家、購買、法務、一般ユーザーAI | 1,500-4,800円 | 100-250円/entity/月 | 登録source、業種、入力不足 |
| `financial_admin_action_screen` | 金融機関、法務、コンプラ | 2,500-7,800円 | 150-300円/entity/月 | 処分source、期間、同定条件 |
| `fintech_license_readiness` | スタートアップ、士業 | 3,000-9,800円 | なし | 業種別の制度sourceと確認質問 |
| `financial_warning_source_packet` | 消費者AI、SNS監視補助 | 800-2,500円 | 100-250円/entity/月 | 注意喚起source、known_gaps |

### 10.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 登録業者確認 | 金融庁登録業者一覧、財務局資料 | HTML/Excel/PDF | 登録番号、業種、登録日、所在地 |
| 行政処分/警告 | 金融庁、財務局、証券取引等監視委員会 | HTML/PDF/OCR | 公表日、対象、処分内容、根拠 |
| 業法/制度 | 金商法、貸金、資金移動、暗号資産、保険、銀行等 | e-Gov/PDF | 条文、監督指針、ガイドライン |
| 注意喚起 | 金融庁、国民生活センター等 | HTML/PDF | 注意喚起対象、source時点 |

主な公式起点:

- 金融庁 登録業者一覧: https://www.fsa.go.jp/menkyo/menkyo.html
- 金融庁 行政処分等: https://www.fsa.go.jp/news/
- 証券取引等監視委員会: https://www.fsa.go.jp/sesc/
- e-Gov法令検索: https://elaws.e-gov.go.jp/

### 10.3 AWS処理順

1. 登録業種ごとにsource_profileを分ける。
2. 登録番号exact lookupを優先し、商号fuzzyは候補止まりにする。
3. 行政処分/注意喚起はpositive event ledger化する。
4. financial packetには投資助言、与信判断、詐欺断定を入れない。

### 10.4 known_gaps

- 投資判断、与信判断、詐欺認定、金融商品の安全性は断定しない。
- 登録検索0件は違法業者の証明ではない。
- 同名、旧商号、海外業者、無登録業者の表記揺れを残す。
- 行政処分未検出は問題なしではない。

## 11. Industry: IT / 個人情報

### 11.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `privacy_vendor_checklist_packet` | SaaS導入、情シス、法務 | 1,500-4,800円 | 100-250円/vendor/月 | 確認項目と公的source一覧 |
| `personal_info_rule_brief` | SMB、D2C、AI agent | 800-2,500円 | なし | PPCガイドラインsource、未確認事項 |
| `security_cert_public_evidence_pack` | B2B購買、RFP | 1,500-4,800円 | 100-250円/entity/月 | ISMS/Pマーク等の公開確認可能性 |
| `ai_service_public_compliance_brief` | AI導入企業 | 2,500-7,800円 | 100-300円/topic/月 | AI/個人情報/委託/越境移転source |

### 11.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 個人情報保護制度 | 個人情報保護委員会、e-Gov | HTML/PDF/API | ガイドライン、Q&A、条文、改正日 |
| 認証/登録 | Pマーク、ISMS、ISMAP、技適等の公開情報 | HTML/API/Playwright | 登録番号、組織名、認証範囲、有効期限 |
| 情報通信制度 | 総務省、経産省、デジタル庁 | HTML/PDF | ガイドライン、所管、更新日 |
| 行政処分/注意喚起 | PPC、総務省、経産省、IPA等 | HTML/PDF | 公表日、対象、内容 |

主な公式起点:

- 個人情報保護委員会 法令・ガイドライン: https://www.ppc.go.jp/personalinfo/legal/
- デジタル庁: https://www.digital.go.jp/
- 総務省: https://www.soumu.go.jp/
- 経済産業省: https://www.meti.go.jp/
- IPA: https://www.ipa.go.jp/

### 11.3 AWS処理順

1. 制度/ガイドライン/FAQをsource_receipt化する。
2. 認証系sourceはID exact中心で、認証範囲と有効期限を保存する。
3. vendor checklistは、企業の実態評価ではなく「確認質問」と「公的根拠」にする。
4. AIサービス関連は、法令/ガイドライン/通達の変更watchとして商品化する。

### 11.4 known_gaps

- 個人情報保護法適合、セキュリティ水準、委託先安全性を保証しない。
- 認証情報の公表範囲、有効期限、認証範囲外業務を明示する。
- 事故/漏えい未検出は安全の証明ではない。
- 企業のプライバシーポリシーや契約書は private/public境界を分ける。

## 12. Industry: 輸出入

### 12.1 AI経由で売れる成果物

| Output | Buyer | Packet price | Monitoring | Free preview |
|---|---|---:|---:|---|
| `export_control_source_navigation` | 輸出企業、EC越境、士業 | 1,500-4,800円 | 100-300円/topic/月 | 該当しそうな公的source、入力不足 |
| `import_requirement_public_brief` | 輸入食品/雑貨/機械 | 2,500-7,800円 | なし | 税関/検疫/規制source一覧 |
| `trade_partner_public_screen` | 海外取引前確認 | 1,500-4,800円 | 100-250円/entity/月 | 日本側公的sourceで見られる範囲 |
| `tariff_and_origin_research_packet` | EC、商社、メーカー | 2,500-9,800円 | なし | 税率/原産地/HS候補の確認source |

### 12.2 逆算して取る一次情報

| Need | Public source family | 取得方式 | 必須字段 |
|---|---|---|---|
| 輸出管理 | 経産省、安全保障貿易管理、e-Gov | HTML/PDF/API | 規制リスト、通達、手続、改正日 |
| 関税/輸入手続 | 税関、財務省 | HTML/PDF/CSV | HS候補、税率表、手続、統計品目 |
| 検疫/食品/動植物 | 厚労省、農水省、動物検疫/植物防疫 | HTML/PDF | 品目、手続、検査、source時点 |
| 海外展開支援 | JETRO、中小機構、J-Grants | HTML/PDF/API | 制度、対象、締切 |

主な公式起点:

- 経済産業省 安全保障貿易管理: https://www.meti.go.jp/policy/anpo/
- 税関: https://www.customs.go.jp/
- JETRO: https://www.jetro.go.jp/
- 農林水産省: https://www.maff.go.jp/
- 厚生労働省 食品: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/

### 12.3 AWS処理順

1. HS/品目/国/用途/相手先という入力schemaを先に固定する。
2. 税関、METI、検疫sourceをsource_profile化する。
3. packetは判定ではなく「確認source navigation」と「必要情報の質問」に寄せる。
4. 高リスク領域は `human_review_required=true` を標準にする。

### 12.4 known_gaps

- 該非判定、許可要否、関税額確定、輸入可否、制裁該当性は断定しない。
- 品目分類、用途、相手国、相手先、最終需要者が不足するとpacket品質が落ちる。
- 海外sourceや制裁sourceの取り扱いは別途source_profileが必要。
- no-hitは対象外/安全/輸出可能の証明ではない。

## 13. 横断CSV overlayで売上を増やす設計

会計CSVを使う場合、raw CSVをAWSに上げず、ローカル/ユーザー側/一時処理で次の派生情報だけを使う。

| CSV-derived safe signal | 使えるpacket | 注意 |
|---|---|---|
| 取引先名候補、法人番号候補、インボイス番号候補 | invoice/counterparty/vertical check | raw摘要や銀行情報は残さない |
| 年間支払額のbucket | 優先調査リスト、monitoring提案 | 金額はbucket化し、個別明細を保存しない |
| 勘定科目カテゴリ | 業界source候補の推薦 | 勘定科目はprovider差が大きい |
| 支払頻度bucket | monitoring候補 | 頻度だけ使い、取引日明細は残さない |
| 地域候補 | 自治体/許認可source routing | 住所がなければ推定しない |

CSV overlayで最初に作るべき有料成果物:

| Output | 価格目安 | 内容 |
|---|---:|---|
| `vendor_priority_screen_from_csv` | 2,500-9,800円 | 取引先候補を公的確認の優先順に並べる。raw CSV非保持 |
| `invoice_and_license_gap_report` | 1,500-6,800円 | インボイス/法人/業界許認可の確認可能性と未確認gap |
| `monthly_vendor_monitoring_setup` | 100-300円/entity/月 | 監視候補entityを作り、source watch条件を提示 |

## 14. vertical packet schema

全業界packetは、最低限このshapeへ寄せる。

```json
{
  "packet_type": "regulated_counterparty_check",
  "vertical": "construction",
  "subject": {
    "input_name": "example",
    "corporation_number": "optional",
    "license_number": "optional",
    "address_hint": "optional"
  },
  "preview": false,
  "price_quote": {
    "currency": "JPY",
    "amount": 2500,
    "tier": "standard_packet"
  },
  "public_findings": [
    {
      "claim": "source-backed candidate claim",
      "support_level": "source_backed",
      "claim_refs": ["cr_..."]
    }
  ],
  "source_receipts": ["sr_..."],
  "known_gaps": [
    {
      "gap_type": "source_scope_limited",
      "message": "No-hit is not proof of absence."
    }
  ],
  "no_hit_policy": "no_hit_not_absence",
  "human_review_required": true,
  "request_time_llm_call_performed": false,
  "_disclaimer": "公的一次情報に基づく調査素材であり、法的判断、金融判断、医療判断、適法性保証ではありません。"
}
```

## 15. 本番デプロイに向けたマージ順

この文書の内容は、AWS計画と本体P0計画へ次の順でマージする。

1. 本体P0のpacket catalogへ `vertical_*` packetを追加する。
2. `known_gaps` enumに業界別gapを追加する。
3. pricing/free preview contractに業界別価格帯とpreview出力を追加する。
4. source_profile schemaに `vertical`, `authority`, `license_boundary`, `playwright_allowed`, `screenshot_allowed` を追加する。
5. AWS J60-J74をJ01-J24/J25-J40の後ではなく、P0商品価値順に差し込む。
6. proof pagesは「業界別にAIが呼ぶべきpacket」としてGEO向けに作る。
7. OpenAPI/MCP examplesは、建設、不動産、人材、産廃、運輸、金融を先に公開する。
8. production deploy前に、privacy leak、forbidden claim、no-hit misuse、billing preview mismatch、source receipt missingをrelease blockerにする。

## 16. 最初に作るべき10個の売上直結packet

最短で売上に寄せるなら、以下の順にfixture、proof page、MCP/API exampleを作る。

| Order | Packet | Vertical | Why first |
|---:|---|---|---|
| 1 | `construction_partner_check` | 建設 | 許認可/処分/公共工事が分かりやすく、B2B単価が取れる |
| 2 | `real_estate_broker_check` | 不動産 | 取引単価が高く、個人AIにも説明しやすい |
| 3 | `staffing_agency_license_check` | 人材 | 許可確認ニーズが明確 |
| 4 | `waste_vendor_permit_check` | 産廃 | 証跡価値が高く、professional価格が通りやすい |
| 5 | `logistics_partner_check` | 運輸 | 荷主/EC/メーカーに横展開しやすい |
| 6 | `financial_registration_check` | 金融 | 高単価だが断定禁止を強くする |
| 7 | `food_recall_and_safety_screen` | 食品 | 消費者AI/ECで分かりやすい |
| 8 | `medical_provider_public_baseline` | 医療 | 公表情報整理として売る。品質評価は禁止 |
| 9 | `privacy_vendor_checklist_packet` | IT/個人情報 | SaaS導入とRFPで売れる |
| 10 | `export_control_source_navigation` | 輸出入 | 判定でなくsource navigationに寄せれば安全に価値が出る |

## 17. ここまでの判断

「まずエンドユーザーがAIで欲しがる成果物を想像し、そこから必要な情報を逆算する」という考え方は必須である。既存計画はsource基盤として正しいが、この文書のようなvertical product catalogを先に固定しないと、AWSで大量取得しても売上に接続しにくい。

AWSクレジットで今やるべきことは、広く公的一次情報を集めるだけではない。次の3つを同時に作ることで価値が出る。

1. 高単価packetごとのsource要件。
2. AI agentが無料previewから有料packetへ推薦しやすい導線。
3. no-hit、known_gaps、human review、disclaimerまで含む安全な商品契約。

この順で進めれば、AWSの成果物は本体P0、GEO、MCP/API、課金導線、本番デプロイに直接つながる。
