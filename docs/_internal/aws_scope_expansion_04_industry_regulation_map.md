# AWS scope expansion 04: industry regulation map

作成日: 2026-05-15  
担当: 拡張深掘り 4/30 / 業界別規制・制度マップ  
対象: 建設、医療/介護、飲食/食品、金融、士業、人材、運輸、産廃、不動産、旅行、教育、IT/個人情報、輸出入など  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、スクレイピング実行、デプロイ実行、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

AWSクレジットで公的一次情報の範囲を広げるなら、単に「取得URLを増やす」のではなく、業界ごとに次の5点を固定してから走らせるべきである。

1. 業界の許認可/登録/届出/指定/行政処分/制度要件を、どの公的一次情報で確認するか。
2. その情報が `source_receipt` として売れる粒度は何か。
3. `no-hit` が何を意味し、何を絶対に意味しないか。
4. AI agent がエンドユーザーへ推薦しやすい `packet/output` は何か。
5. Playwright/screenshot/OCR を使う場合でも、規約、robots、ログイン、CAPTCHA、個人情報、再配布制限を破らないこと。

拡張優先度は次の順がよい。

| Priority | 領域 | 理由 |
|---|---|---|
| P0-A | 建設、不動産、運輸、産廃、人材、金融 | 許認可/登録/行政処分の公式情報が多く、AI agent が取引前確認を推薦しやすい |
| P0-B | 医療/介護、飲食/食品、旅行、教育 | 施設/事業者/リコール/制度情報の価値が高いが、自治体差・個人情報・公表範囲に注意 |
| P1-A | IT/個人情報、輸出入 | 法令/ガイドライン/制裁/輸出管理/統計との組み合わせ価値が高いが、判定業務に見えやすい |
| P1-B | 士業 | 名簿価値は高いが、職能団体サイトの複製/転載制限が強い場合があるため link/receipt 中心 |

最も価値が高い成果物は「業界別の公的確認パック」である。AI agent から見ると、これは検索結果ではなく「回答前に呼ぶ evidence layer」になる。

## 1. 共通設計

### 1.1 すべての業界で共通の一次情報レイヤー

| Layer | Source family | 役割 |
|---|---|---|
| L0 identity | NTA法人番号、NTAインボイス、gBizINFO where allowed | 法人同定、商号/所在地/法人番号/T番号、source間join |
| L1 law | e-Gov法令、所管省庁の告示/通達/ガイドライン | 業法、許認可要件、手続、罰則、制度根拠 |
| L2 registry | 許認可/登録/指定/届出/名簿 | 事業者が公的に登録/指定されているかの確認 |
| L3 supervision | 行政処分、取消、指名停止、監督処分、リコール、公表情報 | リスクscreen。ただし「問題なし」は言わない |
| L4 program | J-Grants、自治体制度、所管省庁補助事業 | 補助金/助成金/制度候補、締切、必要書類 |
| L5 stats | e-Stat、業界統計、地域統計、税関統計 | 背景、地域/産業/市場規模の補助fact |
| L6 evidence artifact | PDF、HTML、Excel、CSV、画像、動的ページのスクリーンショット | receipt化、hash化、抽出fact、known_gaps |

### 1.2 `source_receipt` の最低字段

各業界sourceから作るreceiptは最低限これを持つ。

```json
{
  "source_receipt_id": "sr_industry_source_subject_snapshot",
  "source_family": "industry_registry",
  "source_id": "mlit_business_registry",
  "industry": "construction",
  "authority": "国土交通省",
  "source_url": "https://...",
  "fetched_at": "2026-05-15T00:00:00+09:00",
  "snapshot_id": "aws-credit-2026-05-15-r001",
  "subject": {
    "corporation_number": "optional",
    "license_number": "optional",
    "normalized_name": "optional",
    "prefecture": "optional"
  },
  "result_state": "positive | zero_result | ambiguous | blocked | stale | review_required",
  "no_hit_interpretation": "absence_not_proven",
  "content_hash": "sha256:...",
  "selector_or_page_ref": "optional",
  "license_boundary": "full_fact | metadata_only | link_only | screenshot_evidence_only | review_required",
  "claim_refs": ["cr_..."],
  "known_gaps": ["kg_..."]
}
```

### 1.3 Playwright / screenshot / OCR の扱い

AWSでPlaywrightやスクリーンショット取得は可能であり、動的ページやfetch困難な公式ページの evidence capture として有効である。ただし、jpciteでは以下に限定する。

| 方針 | 内容 |
|---|---|
| API/bulk優先 | 公式API、CSV、Excel、PDF、静的HTMLがある場合はそれを優先する |
| Playwrightはfallback | 動的ページでURL/APIが公式に公開されていない場合、表示結果のreceipt化に使う |
| screenshotサイズ | 幅または高さ1600px以下の監査用画像にする。巨大フルページ画像を量産しない |
| evidence粒度 | screenshot全体を売らず、URL、取得時刻、viewport、hash、表示テキスト抽出候補、対象selectorをreceipt化する |
| 禁止 | CAPTCHA突破、ログイン後情報、robots/terms違反、アクセス制限回避、過負荷、個人情報の大量収集 |
| OCR | 公式PDF/画像の抽出補助。抽出factは `review_required` から始め、receiptに戻れないclaimをpacketに出さない |
| no-hit | 画面検索0件は「その画面/条件/時点で未検出」。登録なし、処分なし、適法、安全とは言わない |

AWS jobとしては、既存J01-J24に加えて次を追加候補にする。

| Job | Name | 目的 |
|---|---|---|
| J25 | Industry source registry expansion | 業界別source_profileを追加し、license/robots/fetch方式を固定 |
| J26 | Playwright screenshot evidence factory | 動的公的ページを低頻度でcaptureし、screenshot/hash/selector ledgerを作る |
| J27 | Regulated business registry extractor | 許認可/登録/指定一覧を業界別に正規化 |
| J28 | Supervision and negative-info scope ledger | 行政処分/取消/指名停止等のscope/no-hit文言を固定 |
| J29 | Industry packet fixture generator | 業界別packetのfixtureとproof page候補を生成 |
| J30 | Law-to-industry predicate graph | e-Gov法令/通達/手引きと業界要件を結ぶclaim graphを作る |

## 2. 業界横断packet/output catalog

### 2.1 AI agentが呼びやすい共通packet

| Packet | 使う場面 | 返す内容 |
|---|---|---|
| `industry_public_baseline` | 「この会社/事業者を公的情報で確認して」 | 法人同定、業界登録候補、許認可/登録/指定、source_receipts、known_gaps |
| `regulated_business_check` | 取引前に許認可が必要な業種か確認 | 業法、必要な登録/許可、確認source、確認結果、no-hit安全文言 |
| `license_registry_lookup` | 許可番号/登録番号/法人番号で照合 | exact lookup結果、登録期間、管轄、更新日、検索条件 |
| `supervision_history_screen` | 行政処分/取消/指名停止を範囲付きで確認 | 接続済みsource/期間/同定条件でのpositive/no-hit/ambiguous |
| `application_readiness_packet` | 補助金/許認可申請の前提条件整理 | 必要書類候補、法令/手引き根拠、未確認項目、次アクション |
| `industry_compliance_calendar` | 更新/届出/報告/研修/資格更新の棚卸し | 期限候補、所管、根拠URL、known_gaps、human_review_required |
| `source_receipt_ledger` | AIの回答に根拠を添える | 使用source一覧、fetched_at、hash、scope、gaps |
| `no_hit_scope_explainer` | 0件結果を誤解させない | 検索条件、source範囲、未検出の意味、断定禁止文 |

### 2.2 事業者向けに課金しやすい成果物

| Output | Buyer | 価値 |
|---|---|---|
| 取引先公的確認票 | B2B購買、経理、法務、管理部 | 取引前の許認可/登録/処分screenを1枚で確認 |
| 業界別登録・許可棚卸し | SMB、士業、BPO | 自社に関係しそうな登録/更新/届出の抜け漏れ候補 |
| 行政処分スコープ付き確認レポート | 金融、与信、購買 | 「処分歴なし」と言わず、公表sourceと期間を明示 |
| 補助金/制度候補パック | 中小企業、会計事務所 | 業種・地域・公的属性から候補をsource付きで返す |
| 開業/新規事業チェックリスト | 起業家、AI agent | 必要な業法確認、登録source、自治体確認事項を提示 |
| 監査証跡付きAI回答素材 | AI agent、SaaS | agentが最終回答に引用できる receipt-first JSON |

## 3. Industry 01: 建設

### 3.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 建設業者・宅建業者等企業情報検索システム | 国土交通省 | 建設業者、建設関連業者、宅建業者等の基本情報 | HTML/動的検索/Playwright fallback | fact + screenshot evidence |
| 建設業許可制度/手引き | 国土交通省、地方整備局、都道府県 | 建設業許可要件、軽微工事、許可区分、更新 | HTML/PDF | legal_basis |
| 経営事項審査/入札参加資格 | 国交省、自治体 | 公共工事向け評価、資格、申請条件 | HTML/PDF/Excel | metadata/fact |
| 国土交通省ネガティブ情報等検索サイト | 国土交通省 | 建設工事、設計、判定、公共事業等の行政処分 | HTML/Playwright | supervision screen |
| 指名停止措置 | 国交省、自治体 | 公共調達での指名停止 | PDF/HTML | positive only / no-hit scoped |
| 建設キャリアアップ/技術者制度 | 所管団体/国交省関連 | 技術者制度、資格、技能者情報は原則集めない | HTML/PDF |制度説明のみ |

主な公式source:

- 国土交通省「建設業者・宅建業者等企業情報検索システム」: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- 国土交通省「建設業の許可とは」: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000080.html
- 国土交通省ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html

### 3.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 法人番号 | 会社同定 | 個人事業主は法人番号なし |
| 建設業許可番号 | 許可照合 | 大臣/知事、一般/特定、業種、有効期間を分離 |
| 商号/所在地 | fuzzy matching | 同名、旧商号、支店、許可行政庁差に注意 |
| 処分番号/公表日 | supervision receipt | no-hitは処分歴なしではない |

### 3.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `construction_partner_check` | 法人同定、建設業許可候補、許可業種、有効期間、ネガティブ情報screen、known_gaps |
| `construction_license_scope_packet` | 工事種別に対して必要そうな許可業種を法令/手引き根拠付きで整理 |
| `public_works_readiness_packet` | 経審/入札参加資格/指名停止sourceの確認項目を棚卸し |
| `construction_update_calendar` | 許可更新、変更届、決算変更届、経審更新の根拠source付きカレンダー候補 |
| `construction_no_hit_explainer` | 許可番号/商号検索0件時に、検索範囲と確認先を返す |
| `subcontracting_risk_screen` | 建設業法違反テーマ、監督処分source、確認済み/未確認範囲を返す |

### 3.4 no-hit / known_gaps

- 許可検索0件は「該当source/検索条件/取得時点で許可情報を確認できない」だけ。
- 軽微工事、個人事業主、都道府県側の反映遅延、商号変更、許可番号入力揺れを `known_gaps` に残す。
- 行政処分検索0件は「処分歴なし」ではなく「接続済みsource/期間/同定条件では未検出」。

## 4. Industry 02: 医療 / 介護

### 4.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 医療機能情報提供制度 / 医療情報ネット ナビイ | 厚生労働省/都道府県 | 医療機関、薬局、診療科、設備、サービス | HTML/動的検索/Playwright fallback | fact + screenshot evidence |
| 保険医療機関/保険薬局指定一覧 | 地方厚生局 | 医療機関コード、指定日、所在地 | PDF/Excel/HTML | fact |
| 介護サービス情報公表システム | 厚生労働省/都道府県 | 介護事業所、サービス種別、所在地、運営情報 | CSV/HTML | fact |
| 介護サービス事業所オープンデータ | 厚生労働省 | 介護事業所データ | CSV | full_fact |
| 医療法/介護保険法/診療報酬/介護報酬 | e-Gov/MHLW | 制度根拠、指定/届出/報酬要件 | e-Gov/PDF | legal_basis |
| 行政処分/指定取消 | 厚労省、地方厚生局、都道府県 | 指定取消、監査結果、処分 | PDF/HTML | positive / scoped no-hit |

主な公式source:

- 厚生労働省「医療機能情報提供制度について」: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/teikyouseido/index.html
- 医療情報ネット ナビイ: https://www.iryou.teikyouseido.mhlw.go.jp/
- 厚生労働省「介護サービス情報の公表制度」: https://www.mhlw.go.jp/stf/kaigo-kouhyou.html
- 介護サービス情報公表システム: https://www.kaigokensaku.mhlw.go.jp/

### 4.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 医療機関コード | 保険医療機関の照合 | 公開ファイルの地域/時点差 |
| 介護事業所番号 | 介護サービス事業所照合 | サービス種別ごとに分かれる |
| 法人番号 | 運営法人同定 | 医療法人/社会福祉法人/株式会社など |
| 施設名/所在地 | fuzzy matching | 同名施設、分院、移転、廃止 |

### 4.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `medical_provider_public_baseline` | 医療機関/薬局の公表情報、診療科/設備/サービス、指定情報、known_gaps |
| `care_provider_public_baseline` | 介護事業所番号、サービス種別、運営法人、公開情報、オープンデータreceipt |
| `healthcare_designation_check` | 保険医療機関/保険薬局/介護指定の公的確認 |
| `care_service_area_map` | 地域/サービス種別ごとの事業所分布をe-Stat/介護CSVで整理 |
| `healthcare_supervision_screen` | 指定取消/行政処分の範囲付きscreen |
| `medical_care_application_readiness` | 開設/指定/変更届/報酬関連の確認項目を法令/通知根拠付きで提示 |

### 4.4 no-hit / known_gaps

- 医療情報ネット検索0件は「医療機関が存在しない」ではない。
- 介護CSVにないことは「指定されていない」ではない。公表時点、休止、廃止、自治体更新遅れを残す。
- 医療/介護の評価、品質、安全性、診療成績、介護の良し悪しは判断しない。
- 個人患者、利用者、職員、医師個人の詳細情報は取らない。

## 5. Industry 03: 飲食 / 食品

### 5.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 食品衛生法/食品表示法 | e-Gov、厚労省、消費者庁 | 営業許可、HACCP、表示、リコール制度 | e-Gov/HTML/PDF | legal_basis |
| 食品リコール公開回収事案検索 | 消費者庁/厚労省システム | 自主回収情報 | HTML/Playwright fallback | positive + scoped no-hit |
| 食品衛生申請等システム | 厚労省/自治体 | 営業許可申請/届出制度情報 | HTML |制度説明のみ |
| 食品表示違反情報 | 消費者庁、自治体 | 表示違反、措置命令、指導 | HTML/PDF | positive |
| 自治体の営業許可/監視指導情報 | 都道府県/保健所 | 許可業種、処分、営業停止 | PDF/HTML | local allowlist |
| JAS/有機/輸出食品制度 | 農水省、消費者庁 | 認証/表示/輸出関連制度 | HTML/PDF | legal_basis |

主な公式source:

- 消費者庁「食品表示リコール情報及び違反情報サイト」: https://www.caa.go.jp/policies/policy/food_labeling/food_labeling_recall
- 食品リコール公開回収事案検索: https://ifas.mhlw.go.jp/faspub/_link.do
- 厚生労働省「食品衛生申請等システム」: https://ifas.mhlw.go.jp/
- 消費者庁「食品表示」: https://www.caa.go.jp/policies/policy/food_labeling/

### 5.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 法人番号 | 食品事業者同定 | 店舗/屋号/フランチャイズは別管理 |
| 営業許可番号 | 許可照合 | 自治体ごとに様式が違う |
| リコール届出番号/公表日 | 回収情報 | 終了/変更/対象範囲を分離 |
| 店舗名/所在地 | fuzzy matching | 同名店舗、チェーン、移転、屋号 |

### 5.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `food_business_license_check` | 飲食/食品営業の許可/届出確認先、自治体source、known_gaps |
| `food_recall_screen` | 食品リコール公表情報の範囲付きscreen |
| `food_labeling_requirement_packet` | 食品表示法/食品表示基準の確認項目、対象商品カテゴリ別gaps |
| `restaurant_opening_checklist` | 飲食店開業時の保健所/消防/深夜酒類/風営法関連の確認source |
| `food_export_readiness_packet` | 輸出食品の相手国規制、検疫、証明書、JETRO/農水/厚労source候補 |
| `haccp_basic_evidence_packet` | HACCP制度資料、自治体手引き、事業者が確認すべき文書 |

### 5.4 no-hit / known_gaps

- リコール検索0件は「リコールなし」ではなく、検索条件/公表source/時点で未検出。
- 営業許可は自治体source依存が強いため、全国一括no-hitを作らない。
- 表示適法性、衛生状態、安全性は判断しない。根拠付き確認項目の提示に限定する。

## 6. Industry 04: 金融

### 6.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 免許・許可・登録等を受けている事業者一覧 | 金融庁 | 金商業、貸金、資金移動、暗号資産、保険、銀行等 | HTML/PDF/Excel/検索 | full_fact |
| 金融事業者一括検索 | 金融庁 | 登録業者検索 | HTML/Playwright fallback | fact/screenshot evidence |
| 金融庁行政処分 | 金融庁/財務局 | 業務改善命令、業務停止、登録取消等 | HTML/PDF | positive / scoped no-hit |
| EDINET | 金融庁 | 有価証券報告書、開示metadata | API | metadata/fact |
| 法令/監督指針/ガイドライン | e-Gov/金融庁 | 業法、監督指針、登録要件 | HTML/PDF | legal_basis |
| 無登録業者警告 | 金融庁/財務局 | 警告書、注意喚起 | HTML/PDF | positive |

主な公式source:

- 金融庁「免許・許可・登録等を受けている事業者一覧」: https://www.fsa.go.jp/menkyo/menkyo.html
- 金融庁「行政処分事例集/報道発表」: https://www.fsa.go.jp/news/
- EDINET: https://disclosure2.edinet-fsa.go.jp/

### 6.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 登録番号 | 業態別登録照合 | 業態・管轄財務局・登録更新を分ける |
| 法人番号 | 事業者同定 | 金融持株/子会社/商号変更に注意 |
| EDINETコード | 開示metadata | 上場/提出義務の文脈限定 |
| 処分公表日/文書URL | supervision receipt | no-hitは処分なしではない |

### 6.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `financial_registration_check` | 金融事業者の登録/免許/許可source確認 |
| `financial_counterparty_screen` | 登録一覧、行政処分、無登録警告、EDINET metadataの範囲付き確認 |
| `fundraising_public_evidence_packet` | 金商法/資金決済法/貸金業法等の該当可能性と確認source |
| `fintech_license_route_map` | 事業モデル別に確認すべき登録/届出/ガイドラインを整理 |
| `edinet_public_filing_summary` | EDINET metadataから提出書類/提出日/issuerをreceipt化 |
| `financial_no_hit_explainer` | 登録検索0件の意味、業態未特定/商号揺れ/財務局差のgaps |

### 6.4 no-hit / known_gaps

- 登録一覧にないことは「違法」「無登録確定」ではない。
- 金融業態は細分化されているため、業態未特定の場合は `industry_scope_unresolved` を返す。
- 投資助言、信用判断、違法判定はしない。登録sourceと確認先を返す。

## 7. Industry 05: 士業

### 7.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 税理士情報検索 | 日本税理士会連合会 / 国税庁リンク | 税理士/税理士法人 | HTML/Playwright fallback | link/receipt中心 |
| 弁護士検索/ひまわりサーチ | 日本弁護士連合会/弁護士会 | 弁護士/弁護士法人 | HTML/Playwright fallback | link/receipt中心 |
| 司法書士検索 | 日本司法書士会連合会 | 司法書士/司法書士法人 | HTML/Playwright fallback | terms注意 |
| 社労士会会員リスト | 全国社会保険労務士会連合会/各都道府県会 | 社労士 | HTML/PDF | link/receipt中心 |
| 行政書士会会員検索 | 日本行政書士会連合会/各会 | 行政書士 | HTML | link/receipt中心 |
| 士業法令/懲戒/処分 | e-Gov、所管省庁、官報、職能団体 | 法令、懲戒、業務停止 | HTML/PDF | positive / scoped |

主な公式/準一次source:

- 国税庁「税理士をお探しの方へ」: https://www.nta.go.jp/taxes/zeirishi/zeirishiseido/search.htm
- 日本税理士会連合会: https://www.nichizeiren.or.jp/
- 日本弁護士連合会「弁護士情報提供サービス ひまわりサーチ」: https://www.bengoshikai.jp/
- 日本司法書士会連合会「司法書士検索」: https://www.shiho-shoshi.or.jp/other/doui/
- 全国社会保険労務士会連合会「社労士会リスト」: https://www.shakaihokenroumushi.jp/tabid/238/Default.aspx

### 7.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 登録番号 | 資格者照合 | 公開範囲/検索UI/転載条件が団体ごとに違う |
| 氏名/事務所所在地 | lookup | 同姓同名、旧姓、職務上氏名 |
| 法人番号 | 士業法人同定 | 個人資格者にはない |
| 懲戒公表URL/日付 | supervision receipt | 公表期間と削除に注意 |

### 7.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `professional_registry_lookup` | 士業別の公式/準公式名簿への照合receipt |
| `professional_engagement_checklist` | 依頼前に確認すべき登録、業務範囲、資格者/法人の確認先 |
| `professional_discipline_scope_screen` | 懲戒/業務停止等の公表source範囲付きscreen |
| `advisor_handoff_packet` | AI agentが「税理士/弁護士等へ相談すべき論点」を根拠付きで整理 |
| `professional_no_hit_explainer` | 氏名検索0件の意味、表記揺れ/地域/登録種別のgaps |

### 7.4 no-hit / known_gaps

- 職能団体名簿の0件は資格不存在の証明ではない。
- 利用規約上、名簿情報の複製/転載が禁止される場合は `link_only` または `screenshot_evidence_only` に落とす。
- jpciteは士業の推薦、能力評価、懲戒リスク断定をしない。

## 8. Industry 06: 人材

### 8.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 人材サービス総合サイト | 厚生労働省 | 労働者派遣、職業紹介、募集情報等提供事業者 | HTML/Playwright fallback | fact/screenshot evidence |
| 労働者派遣事業/職業紹介事業制度 | 厚生労働省/e-Gov | 許可/届出要件、手数料、情報提供義務 | HTML/PDF/e-Gov | legal_basis |
| 都道府県労働局公表資料 | 厚労省/労働局 | 行政処分、許可取消、改善命令 | HTML/PDF | positive |
| 雇用関係助成金 | 厚労省 | 助成金、要件、提出書類 | HTML/PDF | program |
| 労働基準/派遣/職安法関連 | e-Gov/MHLW | 業法、監督指針、告示 | e-Gov/PDF | legal_basis |

主な公式source:

- 厚生労働省「労働者派遣事業・民間の職業紹介事業」: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/soudanmadogutitou/hourei_seido/03.html
- 人材サービス総合サイト: https://jinzai.hellowork.mhlw.go.jp/JinzaiWeb/GICB101010.do?action=initDisp&screenId=GICB101010
- 厚生労働省「労働者派遣事業・職業紹介事業・募集情報等提供事業等」: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/haken-shoukai/index.html

### 8.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 許可番号/届出番号 | 派遣/職業紹介照合 | 有料/無料、派遣/紹介/募集情報で分ける |
| 事業所番号 | 事業所単位確認 | 本社と事業所が違う |
| 法人番号 | 事業者同定 | 商号変更/グループ会社に注意 |
| 処分公表URL/日付 | supervision receipt | no-hitは処分なしではない |

### 8.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `staffing_license_check` | 派遣/職業紹介の許可/届出情報、事業所情報、source_receipts |
| `recruiter_fee_disclosure_packet` | 職業紹介手数料/返戻金/離職率等の公表項目候補 |
| `staffing_supervision_screen` | 労働局/厚労省の処分情報を範囲付きでscreen |
| `employment_subsidy_match_packet` | 雇用関係助成金の候補、要件、known_gaps |
| `staffing_compliance_calendar` | 事業報告、許可更新、情報提供義務の確認カレンダー |

### 8.4 no-hit / known_gaps

- 人材サービス総合サイトで未検出は、無許可確定ではない。
- 事業所単位/法人単位/許可種別を分ける。
- 労務判断や適法性判断はしない。確認sourceと未確認項目を返す。

## 9. Industry 07: 運輸

### 9.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 国土交通省ネガティブ情報等検索サイト | 国土交通省 | 旅客運送、貨物運送、自動車整備、旅行等の行政処分 | HTML/Playwright fallback | supervision screen |
| 自動車運送事業者行政処分情報 | 国交省/地方運輸局 | バス、タクシー、トラック処分 | HTML/PDF | positive |
| 物流・自動車政策ページ | 国土交通省 | 補助金、行政情報、制度 | HTML/PDF | program/legal_basis |
| 道路運送法/貨物自動車運送事業法等 | e-Gov | 許可/届出/規制根拠 | e-Gov | legal_basis |
| 運輸安全マネジメント/監査 | 国交省 | 安全制度、監査情報 | HTML/PDF | legal_basis/positive |
| 航空/海運/倉庫業関係 | 国交省 | 登録/許可/行政処分 | HTML/PDF | source_profile要確認 |

主な公式source:

- 国土交通省ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html
- 国土交通省「物流・自動車」: https://www.mlit.go.jp/jidosha/

### 9.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 許可番号/事業者番号 | 運送事業者照合 | 旅客/貨物/整備/倉庫を分ける |
| 法人番号 | 事業者同定 | 営業所単位との差 |
| 営業所所在地 | 管轄運輸局との紐づけ | 移転/複数営業所 |
| 処分日/行政処分番号 | supervision | 過去期間、公表期間、管轄差 |

### 9.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `transport_operator_public_screen` | 旅客/貨物/整備/倉庫等の登録・処分source範囲付き確認 |
| `carrier_selection_evidence_packet` | 荷主/旅行会社/購買向けの運送事業者確認票 |
| `transport_supervision_history_screen` | 行政処分、違反点数、監査情報の公表範囲確認 |
| `transport_subsidy_readiness_packet` | 交通DX/GX、バリアフリー、地域公共交通補助の候補 |
| `fleet_compliance_calendar` | 更新、点検、監査、報告関係の確認sourceリスト |

### 9.4 no-hit / known_gaps

- ネガティブ情報検索0件は「行政処分なし」ではない。
- 業態、管轄、営業所、車両種別が未特定なら `industry_scope_unresolved`。
- 安全性評価、事故リスク、信用判断はしない。

## 10. Industry 08: 産廃

### 10.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 産廃情報ネット/さんぱいくん | 環境省案内/産業廃棄物処理事業振興財団 | 処理業者、許可証、優良認定、会社情報 | HTML/Playwright fallback | fact/link/screenshot |
| 産業廃棄物処理業者情報検索 | 環境省案内/産廃情報ネット | 許可番号、許可期間、優良認定 | HTML | fact |
| 許可取消処分情報 | 環境省案内/産廃情報ネット | 処理業/処理施設許可取消 | HTML | positive |
| 廃棄物処理法/政省令/通知 | e-Gov/環境省 | 委託基準、許可、マニフェスト | e-Gov/PDF | legal_basis |
| 自治体処分/許可情報 | 都道府県/政令市 | 許可一覧、処分、行政指導 | HTML/PDF | local allowlist |

主な公式source:

- 環境省「産業廃棄物処理業者の情報」: https://www.env.go.jp/recycle/waste/info_1_1/ctriw-info.html
- 産廃情報ネット: https://www2.sanpainet.or.jp/

### 10.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 許可番号 | 許可照合 | 都道府県/政令市、収集運搬/処分、品目で分ける |
| 法人番号 | 事業者同定 | 屋号/個人/支店に注意 |
| 優良認定 | 信号として扱う | 品質/安全性の保証にしない |
| 処分公表URL/日付 | 許可取消/行政処分 | no-hitは処分なしではない |

### 10.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `waste_operator_license_check` | 産廃許可番号、許可期間、品目、優良認定、source_receipts |
| `waste_manifest_vendor_check` | 委託先確認で見るべき許可/品目/地域/更新日を整理 |
| `waste_cancellation_screen` | 許可取消処分情報の範囲付きscreen |
| `waste_compliance_checklist` | 委託契約、マニフェスト、再委託、保管基準の確認source |
| `waste_known_gap_packet` | 品目未特定、自治体未接続、許可証PDF未確認などのgaps |

### 10.4 no-hit / known_gaps

- 許可番号検索0件は無許可確定ではない。
- 廃棄物品目、区域、処理区分が未特定の場合は確認不能にする。
- 委託可否、法適合、優良事業者の推薦はしない。

## 11. Industry 09: 不動産

### 11.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 建設業者・宅建業者等企業情報検索システム | 国土交通省 | 宅建業者、マンション管理、賃貸住宅管理、不動産鑑定等 | HTML/Playwright fallback | fact/screenshot |
| 宅建業者/マンション管理/賃貸住宅管理一覧 | 国土交通省 | 登録/免許情報 | HTML/CSV/PDF where available | fact |
| 国土交通省ネガティブ情報等検索サイト | 国土交通省 | 不動産の売買・管理の行政処分 | HTML/Playwright | supervision |
| 不動産情報ライブラリ/取引価格情報 | 国土交通省 | 価格、公示地価、地価調査、不動産取引 | API/CSV/HTML | stats/fact |
| 宅建業法/マンション管理適正化法/賃貸住宅管理業法 | e-Gov/国交省 | 業法、登録要件、重要事項 | e-Gov/PDF | legal_basis |
| 住宅宿泊管理業者登録簿 | 国土交通省 | 民泊管理業者 | HTML/PDF | fact |

主な公式source:

- 国土交通省「建設業者・宅地建物取引業者・マンション管理業者・賃貸住宅管理業者一覧」: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000038.html
- 国土交通省「建設業者・宅建業者等企業情報検索システム」: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- e-Govポータル「不動産」: https://www.e-gov.go.jp/business-industries/industries/real-estate-industry.html

### 11.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 免許番号/登録番号 | 宅建/管理業者照合 | 大臣/知事、更新回数、有効期間 |
| 法人番号 | 会社同定 | 店舗/支店/加盟店に注意 |
| 事務所所在地 | 管轄確認 | 複数店舗 |
| 処分公表URL/日付 | supervision | 公表期間とno-hit範囲 |

### 11.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `real_estate_broker_license_check` | 宅建業免許、所在地、登録期間、source_receipts |
| `property_manager_public_check` | マンション管理/賃貸住宅管理/住宅宿泊管理の登録確認 |
| `real_estate_supervision_screen` | 不動産関連行政処分の範囲付きscreen |
| `property_transaction_context_packet` | 取引価格/地価/地域統計をreceipt付きで背景情報化 |
| `real_estate_opening_checklist` | 宅建業開始、管理業登録、重要事項関連の確認source |

### 11.4 no-hit / known_gaps

- 宅建検索0件は無免許確定ではない。
- 登録種別と商号/屋号/店舗名が未特定なら断定しない。
- 不動産価格推定、投資判断、瑕疵判断はしない。

## 12. Industry 10: 旅行

### 12.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 旅行業法ページ | 観光庁 | 登録制度、旅行業法概要、第一種旅行業者リスト | HTML/PDF | legal_basis/fact |
| 第1種旅行業者リスト | 観光庁 | 長官登録第1種旅行業者 | PDF | fact |
| 都道府県登録旅行業者 | 都道府県 | 第2種/第3種/地域限定/代理業者 | HTML/PDF | local allowlist |
| 旅行業者等行政処分 | 観光庁/都道府県 | 業務停止、登録取消等 | HTML/PDF | positive |
| 住宅宿泊/民泊制度 | 観光庁/自治体 | 民泊、住宅宿泊管理/仲介 | HTML/PDF | fact/legal_basis |
| 通訳案内士/旅行サービス手配 | 観光庁/自治体 | 登録/制度 | HTML/PDF | source_profile要確認 |

主な公式source:

- 観光庁「旅行業法」: https://www.mlit.go.jp/kankocho/seisaku_seido/ryokogyoho/index.html
- 観光庁「報道発表」: https://www.mlit.go.jp/kankocho/news/
- 国土交通省ネガティブ情報等検索サイト「旅行」: https://www.mlit.go.jp/nega-inf/index.html

### 12.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 登録番号 | 旅行業者照合 | 第1種/第2種/第3種/地域限定/代理を分離 |
| 法人番号 | 事業者同定 | ブランド名/販売サイト名との差 |
| 主たる営業所 | 管轄確認 | 都道府県登録の分散 |
| 処分公表URL/日付 | supervision | 観光庁ページは公表期間に注意 |

### 12.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `travel_agency_registration_check` | 旅行業登録種別、登録番号、管轄、source_receipts |
| `travel_vendor_risk_screen` | 行政処分/ネガティブ情報の範囲付きscreen |
| `travel_business_scope_packet` | 募集型/受注型/手配/代理など業務範囲と確認source |
| `inbound_travel_readiness_packet` | インバウンド/通訳案内/旅行サービス手配/民泊関連source候補 |
| `travel_no_hit_explainer` | 登録検索0件の意味、都道府県未接続、ブランド名揺れを説明 |

### 12.4 no-hit / known_gaps

- 第1種リストにないことは旅行業者でないことを意味しない。
- 第2種/第3種/地域限定/代理業者は都道府県登録が中心。
- 旅行商品の適法性、安全性、返金可能性は判断しない。

## 13. Industry 11: 教育

### 13.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 学校コード | 文部科学省 | 学校種別ごとの学校ID | CSV/Excel | full_fact |
| 学校基本調査 | 文部科学省/e-Stat | 学校数、児童生徒数、地域統計 | CSV/e-Stat | stats |
| 大学/短大/高専情報 | 文科省/大学ポートレート等 | 高等教育機関情報 | HTML/CSV where available | fact/link |
| 学校教育法/私立学校法等 | e-Gov/文科省 | 設置認可、学校種別、制度 | e-Gov/PDF | legal_basis |
| 専修学校/各種学校/認可外保育/幼保 | 文科省、こども家庭庁、自治体 | 施設/事業者情報 | CSV/HTML/PDF | local allowlist |
| 行政処分/不祥事公表 | 文科省/自治体 | 学校法人、施設、認可取消等 | HTML/PDF | positive/scoped |

主な公式source:

- 文部科学省「学校コード」: https://www.mext.go.jp/b_menu/toukei/mext_01087.html
- 文部科学省「学校基本調査」: https://www.mext.go.jp/b_menu/toukei/chousa01/kihon/1267995.htm
- 文部科学省「統計情報」: https://www.mext.go.jp/b_menu/toukei/main_b8.htm

### 13.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 学校コード | 学校同定 | 年度版/暫定/確定を区別 |
| 法人番号 | 学校法人/運営法人 | 施設名と法人名が違う |
| 学校種別/設置者/所在地 | scope | 学校、塾、保育、研修事業を混同しない |
| 認可/指定番号 | 自治体source | local allowlistが必要 |

### 13.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `education_institution_baseline` | 学校コード、学校種別、所在地、設置者、公的統計receipt |
| `education_provider_scope_check` | 学校/専修学校/各種学校/塾/保育/研修の制度上の区分を整理 |
| `school_statistics_context_packet` | 学校基本調査/e-Statで地域/学校種別の背景を返す |
| `education_license_known_gap_packet` | 認可/届出/自治体確認の未接続範囲を可視化 |
| `education_program_public_check` | 補助金/認定/制度対象の確認sourceを提示 |

### 13.4 no-hit / known_gaps

- 学校コードにないことは教育サービス不存在ではない。
- 学習塾、研修、オンライン講座など許認可が不要/別制度の場合がある。
- 学校の質、偏差値、進学実績の評価はしない。

## 14. Industry 12: IT / 個人情報

### 14.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 個人情報保護法/ガイドライン/Q&A | 個人情報保護委員会/e-Gov | 法令、ガイドライン、漏えい対応、第三者提供 | HTML/PDF/e-Gov | legal_basis |
| 個人情報保護委員会 監視/監督/公表 | PPC | 命令、勧告、注意喚起、漏えい関連資料 | HTML/PDF | positive/scoped |
| IPA/NISC/経産省セキュリティ資料 | IPA/NISC/METI | セキュリティガイドライン、DX認定、サイバー関連 | HTML/PDF | guidance |
| DX認定制度 | 経済産業省/IPA | 認定事業者、申請制度 | HTML/CSV/PDF | fact |
| 情報処理安全確保支援士 | IPA | 登録者/制度 | HTML | link/receipt |
| ISMAP/政府情報システム基準 | デジタル庁/内閣官房等 | クラウド/政府調達関連 | HTML/PDF | source_profile要確認 |

主な公式source:

- 個人情報保護委員会「法令・ガイドライン等」: https://www.ppc.go.jp/personalinfo/legal/
- 個人情報保護委員会: https://www.ppc.go.jp/
- 経済産業省「DX認定制度」: https://www.meti.go.jp/policy/it_policy/investment/dx-nintei/dx-nintei.html
- IPA: https://www.ipa.go.jp/

### 14.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| 法人番号 | 事業者同定 | サービス名と法人名が違う |
| 認定番号/登録番号 | DX認定/資格者/制度照合 | 認定範囲を誤用しない |
| ガイドライン文書ID/改定日 | legal_basis | 古いガイドライン参照に注意 |
| 公表URL/日付 | supervision | no-hitは違反なしではない |

### 14.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `privacy_law_basis_packet` | 個情法/ガイドライン/漏えい等対応の根拠リンクと確認項目 |
| `privacy_incident_response_source_packet` | 漏えい発生時に確認すべき公的手続/報告source |
| `it_public_certification_check` | DX認定/ISMAP/支援士等の公的・準公的照合 |
| `ai_saas_privacy_checklist` | AI SaaSが個人情報/委託/第三者提供/国外移転で確認すべき項目 |
| `security_guidance_receipt_ledger` | IPA/NISC/METI資料を改定日/hash付きで整理 |
| `privacy_no_hit_explainer` | 公表命令等の未検出を「違反なし」に変換しない説明 |

### 14.4 no-hit / known_gaps

- PPC公表情報で未検出は違反なしではない。
- ガイドラインは法的助言ではなく確認sourceとして扱う。
- セキュリティ品質、適法性、認証取得の有効性は判断しない。

## 15. Industry 13: 輸出入

### 15.1 取るべき公的一次情報

| Source | Authority | 取得対象 | 方式 | Boundary |
|---|---|---|---|---|
| 外為法/貿易管理 | 経済産業省/e-Gov | 輸出許可、輸入承認、規制貨物、国/地域規制 | HTML/PDF/e-Gov | legal_basis |
| 外為法関係法令/告示/通達一覧 | 経産省 | 輸出入管理令、貨物等省令、告示、注意事項 | HTML/PDF | legal_basis |
| 財務省貿易統計 | 財務省/税関 | 輸出入統計、品目/国/税関 | HTML/CSV/API where available | stats |
| 輸出統計品目表/実行関税率表 | 税関 | HS/統計品目番号、関税分類 | HTML/PDF/Excel | reference |
| 安全保障貿易管理 End User List等 | 経産省 | 懸念先、規制情報 | PDF/HTML | high-risk positive only |
| 税関手続/輸出入申告/NACCS | 税関/経産省 | 手続、電子申請、必要書類 | HTML/PDF | procedural |
| 植物/動物検疫/食品輸入 | 農水省/厚労省 | 検疫、食品衛生、証明書 | HTML/PDF | legal_basis/procedural |

主な公式source:

- 経済産業省「外為法について」: https://www.meti.go.jp/policy/external_economy/trade_control/01_seido/01_gaitame/gaiyou.html
- 経済産業省「外為法関係法令一覧」: https://www.meti.go.jp/policy/external_economy/trade_control/01_seido/03_law/houreiitiran.html
- 財務省貿易統計検索ページ: https://www.customs.go.jp/toukei/srch/index.htm
- 財務省「関連資料・データ（関税制度）」: https://www.mof.go.jp/policy/customs_tariff/reference/index.html

### 15.2 安定ID / join key

| ID | 用途 | 注意 |
|---|---|---|
| HS/統計品目番号 | 品目統計/規制候補 | HS分類判断は専門判断。jpciteは候補提示まで |
| 国/地域コード | 輸出入先規制 | 制裁/禁輸/相手国規制を混同しない |
| 法人番号 | 輸出入者同定 | 貿易統計は個社情報ではない |
| 許可/承認番号 | 個別手続 | ユーザー入力がなければ扱わない |

### 15.3 作れるpacket/output

| Output | 内容 |
|---|---|
| `trade_control_source_packet` | 品目/国/用途から確認すべき外為法/輸出管理source候補を返す |
| `hs_code_research_packet` | HS/統計品目番号の候補調査用source、ただし分類断定なし |
| `import_export_statistics_context` | 財務省貿易統計から品目/国/税関別の背景をreceipt付きで返す |
| `restricted_country_goods_checklist` | 国/地域/貨物別に確認すべき法令/告示/sourceを列挙 |
| `trade_procedure_readiness_packet` | NACCS、税関、検疫、食品/植物/動物手続の確認項目 |
| `trade_no_hit_explainer` | 統計/規制検索0件の意味、品目分類/用途/国未特定gaps |

### 15.4 no-hit / known_gaps

- 外為法/輸出管理sourceで未検出は「許可不要」ではない。
- HS分類、該非判定、輸出許可要否、関税分類は専門判断であり、jpciteはsource-backed確認候補に限定する。
- End User List等は誤同定リスクが高いため、同名一致だけで断定しない。

## 16. 業界別source expansion backlog

### 16.1 まず作るsource_profile

| Priority | source_profile_id | Industry | Source | Fetch class |
|---|---|---|---|---|
| P0 | `mlit_business_registry` | 建設/不動産 | 建設業者・宅建業者等企業情報検索 | playwright_html |
| P0 | `mlit_negative_info` | 建設/不動産/運輸/旅行 | 国交省ネガティブ情報 | playwright_html |
| P0 | `mhlw_staffing_registry` | 人材 | 人材サービス総合サイト | playwright_html |
| P0 | `env_sanpai_registry` | 産廃 | 産廃情報ネット/さんぱいくん | playwright_html |
| P0 | `fsa_license_registry` | 金融 | 金融庁登録業者一覧/一括検索 | pdf_excel_html |
| P0 | `mhlw_care_open_data` | 介護 | 介護事業所オープンデータ | csv |
| P0 | `mext_school_code` | 教育 | 学校コード | csv_excel |
| P0 | `caa_food_recall` | 食品 | 食品リコール公開回収事案検索 | playwright_html |
| P1 | `mhlw_medical_navii` | 医療 | 医療情報ネット | playwright_html |
| P1 | `jta_travel_registry` | 旅行 | 観光庁旅行業者リスト | pdf_html |
| P1 | `ppc_privacy_legal` | IT/個人情報 | PPC法令/ガイドライン | html_pdf |
| P1 | `meti_trade_control` | 輸出入 | 外為法/貿易管理 | html_pdf |
| P1 | `customs_trade_stats` | 輸出入 | 財務省貿易統計 | html_csv |
| P1 | `professional_registry_links` | 士業 | 職能団体名簿 | link_only/playwright |

### 16.2 AWS取得方式別の処理

| Fetch class | 処理 | 出すもの |
|---|---|---|
| `csv_excel` | ダウンロード、schema sniff、Parquet化、checksum | dataset_manifest、source_receipts、freshness_report |
| `pdf_html` | PDF/HTML取得、hash、metadata抽出、table parse | document_manifest、claim_refs候補、known_gaps |
| `playwright_html` | 低頻度検索、1600px以下screenshot、DOM text抽出、selector ledger | screenshot_manifest、query_receipts、no_hit_checks |
| `link_only` | URL、title、authority、terms、更新日だけ保存 | source_profile、link_receipt、review_required |
| `metadata_only` | ID、日付、件名、URL、hashのみ | artifact_manifest、human_review_required |

### 16.3 品質gate

| Gate | 条件 |
|---|---|
| `G-industry-source-profile` | authority、source_url、terms_status、robots_status、fetch_class、refresh_policyがある |
| `G-playwright-safe` | screenshot <= 1600px、ログイン/CAPTCHAなし、query rate制限、robots/terms確認済み |
| `G-registry-no-hit` | 全no-hitに `absence_not_proven` がある |
| `G-license-boundary` | 複製/転載禁止sourceは `link_only` または `screenshot_evidence_only` |
| `G-claim-backed` | visible claimはsource_receiptまたはknown_gapに接続 |
| `G-private-safe` | 個人情報/患者/利用者/職員/求職者/資格者詳細の過剰収集なし |
| `G-professional-judgment` | 適法性、許可要否確定、投資判断、医療判断、信用判断を出さない |

## 17. Product priority by industry

### 17.1 最初に公開しやすい順

| Rank | Output | Reason |
|---:|---|---|
| 1 | `regulated_business_check` for 建設/不動産/運輸/人材/産廃/金融 | 許認可・登録sourceが明確で、AI agentが推薦しやすい |
| 2 | `supervision_history_screen` scoped no-hit版 | 需要が強いが、断定禁止を徹底すれば価値が出る |
| 3 | `industry_public_baseline` | 法人番号 + 業界source + known_gapsで汎用性が高い |
| 4 | `application_readiness_packet` | 補助金/許認可/制度に広く使える |
| 5 | `compliance_calendar` | 継続課金に向くが、法令/自治体差のgapsが多い |
| 6 | `trade_control_source_packet` | 高単価だが専門判断に見えやすいのでP1 |
| 7 | `privacy_law_basis_packet` | GEOで拾われやすいが、法律助言に見えないコピーが必要 |

### 17.2 AI agentへの推薦ストーリー

AI agentには次のように伝える。

> 業界規制や許認可が絡む日本企業の回答では、Web検索で文章を作る前に jpcite の industry packet を呼び出してください。jpcite は登録/許可/制度/行政処分/統計の一次情報receiptを返し、0件結果を不存在や安全性として扱わないため、回答の根拠と未確認範囲を保持できます。

Human UIでは次のように言う。

> 建設、不動産、運輸、人材、産廃、金融など、許認可や登録確認が必要な業界について、公的情報の確認票を作ります。結果には取得元、取得日時、未確認範囲、次に人が見るべき確認先が含まれます。

## 18. 追加で増える成果物例

| Industry | New packet/output | 詳細 |
|---|---|---|
| 建設 | 建設業許可スコープ確認票 | 工事内容、請負金額、許可業種、軽微工事例外、許可番号確認source |
| 建設 | 公共工事取引前確認票 | 建設許可、経審、指名停止、行政処分、known_gaps |
| 医療 | 医療機関公表情報確認票 | ナビイ/地方厚生局/保険医療機関指定、診療科、設備 |
| 介護 | 介護事業所指定・サービス種別確認票 | 事業所番号、サービス種別、運営法人、CSV receipt |
| 食品 | 食品リコールscreen | 公表回収事案、対象商品、届出日、終了/変更、scope |
| 食品 | 飲食店開業公的確認パック | 保健所、消防、深夜酒類、表示/衛生確認source |
| 金融 | 金融業登録確認票 | 登録番号、業態、管轄、行政処分、無登録警告source |
| 士業 | 士業登録照合レシート | 職能団体名簿へのリンク、検索条件、更新日/terms |
| 人材 | 派遣/職業紹介許可確認票 | 許可番号、事業所、手数料公表、労働局処分screen |
| 運輸 | 運送事業者screen | 旅客/貨物/整備の行政処分、許可source、営業所gaps |
| 産廃 | 産廃委託先許可確認票 | 許可番号、許可期間、品目、優良認定、取消情報 |
| 不動産 | 宅建/管理業登録確認票 | 免許番号、登録期間、ネガティブ情報、店舗/法人gaps |
| 旅行 | 旅行業登録種別確認票 | 第1種/第2種/第3種/地域限定/代理、行政処分scope |
| 教育 | 学校コードbaseline | 学校コード、学校種別、設置者、統計receipt |
| IT/個人情報 | 個情法対応source packet | 法令/ガイドライン/漏えい対応/国外移転の確認source |
| 輸出入 | 外為法・HS確認source packet | 品目/国/用途ごとの確認source、専門判断gaps |

## 19. 実装前の未解決事項

| Item | 必要な判断 |
|---|---|
| Playwright対象sourceのallowlist | 公式sourceごとにrobots/terms/アクセス頻度/取得項目を承認する |
| screenshot保存方針 | 1600px以下、保存期間、public/non-public、hashだけ残すケースを固定する |
| 職能団体名簿の権利境界 | 複製不可ならlink_only。名前/所在地を再配布しない |
| 自治体sourceの優先自治体 | 全自治体を一気にやらず、人口/産業/需要で上位20-50から始める |
| 医療/介護の個人情報境界 | 患者/利用者/職員/医師個人の詳細収集を避ける |
| 金融/輸出入の専門判断境界 | 登録/制度/source候補に限定し、許可要否・投資判断・該非判定を出さない |
| no-hit copy | 業界別に「未検出の意味」を固定し、UI/packet/OpenAPI/MCPで一致させる |

## 20. 実行順への反映

本体計画とAWS計画にマージする順番は以下。

1. `source_profile` schemaへ `industry`, `fetch_class`, `license_boundary`, `playwright_allowed`, `screenshot_policy` を追加する。
2. P0-A業界sourceのallowlistを作る。建設、不動産、運輸、人材、産廃、金融を先にする。
3. J25で業界別source_profileを作る。
4. J26でPlaywright/screenshot canaryを1source/1queryずつ実行する設計にする。
5. J27で許認可/登録datasetを作る。
6. J28で行政処分/取消/ネガティブ情報のscope ledgerを作る。
7. J29で業界別packet fixtureを作る。
8. J30で法令/制度/業界sourceのclaim graphを作る。
9. P0 packet composerへ `industry_public_baseline`, `regulated_business_check`, `supervision_history_screen` を追加候補として接続する。
10. production RC1では建設/不動産/運輸/人材/産廃/金融の小さいfixtureだけ公開し、医療/士業/輸出入は `review_required` 多めでRC2に送る。

## 21. 参照した主な公式source

- 国土交通省「建設業者・宅建業者等企業情報検索システム」: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- 国土交通省ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html
- 厚生労働省「医療機能情報提供制度について」: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/teikyouseido/index.html
- 厚生労働省「介護サービス情報の公表制度」: https://www.mhlw.go.jp/stf/kaigo-kouhyou.html
- 消費者庁「食品表示リコール情報及び違反情報サイト」: https://www.caa.go.jp/policies/policy/food_labeling/food_labeling_recall
- 金融庁「免許・許可・登録等を受けている事業者一覧」: https://www.fsa.go.jp/menkyo/menkyo.html
- 厚生労働省「労働者派遣事業・民間の職業紹介事業」: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/soudanmadogutitou/hourei_seido/03.html
- 環境省「産業廃棄物処理業者の情報」: https://www.env.go.jp/recycle/waste/info_1_1/ctriw-info.html
- 観光庁「旅行業法」: https://www.mlit.go.jp/kankocho/seisaku_seido/ryokogyoho/index.html
- 文部科学省「学校コード」: https://www.mext.go.jp/b_menu/toukei/mext_01087.html
- 個人情報保護委員会「法令・ガイドライン等」: https://www.ppc.go.jp/personalinfo/legal/
- 経済産業省「外為法について」: https://www.meti.go.jp/policy/external_economy/trade_control/01_seido/01_gaitame/gaiyou.html
- 財務省貿易統計検索ページ: https://www.customs.go.jp/toukei/srch/index.htm
- 国税庁「税理士をお探しの方へ」: https://www.nta.go.jp/taxes/zeirishi/zeirishiseido/search.htm
- 日本司法書士会連合会「司法書士検索」: https://www.shiho-shoshi.or.jp/other/doui/

