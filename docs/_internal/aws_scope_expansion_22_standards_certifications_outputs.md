# AWS scope expansion 22: standards, certifications, and technical regulation outputs

作成日: 2026-05-15  
担当: 拡張深掘り 22/30 / 標準・認証・技術規制  
対象: JIS/JISC、JISマーク、JNLA/IAJapan、技適、PSE/PSC、製品安全4法、NITE事故・リコール、食品表示、JAS/HACCP、医療機器、建築基準、個人情報・セキュリティガイドライン、化学物質/SDS/GHS  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

標準・認証・技術規制は、jpciteのAWSクレジット投入先として優先度を上げるべき領域である。

理由は明確で、エンドユーザーがAIに頼む相談がかなり具体的で、かつ通常のAI回答だけでは危険だからである。

- 「この輸入品を日本で売る前に何を確認すべきか」
- 「この無線機器に技適があるか」
- 「このACアダプターや玩具はPSE/PSC対象っぽいか」
- 「この食品ラベルや機能性表示の確認ポイントは何か」
- 「これは医療機器やプログラム医療機器に該当し得るか」
- 「この建材や構造部材のJIS/建築基準上の根拠を確認したい」
- 「個人情報・セキュリティの公的ガイドラインに沿って、委託先確認シートを作りたい」

これらはAI agentがエンドユーザーへ推薦しやすい。なぜなら、検索結果の要約ではなく、公的一次情報に基づく証跡付きの安い成果物が欲しい場面だからである。

ただし、この領域では「適法」「認証済み」「安全」「販売可能」「医療機器ではない」「表示OK」と断定してはいけない。jpciteが売るべきものは、一次情報のreceipt、該当可能性、確認すべき制度、known gaps、次の質問、専門家確認が必要なポイントである。

AWSでやるべきことは、広域にページを集めるだけではない。次の順番で「売れるpacket」を先に定義し、そこから必要なsource familyを逆算してsource lake化する。

1. 売れる成果物を定義する。
2. それぞれの成果物に必要な公的一次情報を定義する。
3. 取得方式を `API / HTML / PDF / Excel / Playwright / screenshot / OCR` に分ける。
4. `source_receipts[]` と `claim_refs[]` へ落とせる形に正規化する。
5. no-hitを「不存在証明」ではなく「確認範囲内でヒットなし」として出す。
6. AI agentがGEO/MCP/APIで発見し、エンドユーザーへ安く推薦できるpacketにする。

## 1. 売れる成果物から逆算した商品群

### 1.1 最初に作るべき高需要packet

| Rank | Packet | End user question | Buyer | Price hint | 必要source |
|---:|---|---|---|---:|---|
| 1 | `product_import_precheck` | この商品を日本で輸入・販売する前に何を確認すべきか | EC輸入、D2C、商社、士業 | 1,500-6,800円 | PSE/PSC/ガス/LPG、技適、食品/医療/化学物質、税関/JETRO補助 |
| 2 | `wireless_device_giteki_lookup` | 技適番号・型番・メーカーで公的情報を確認したい | EC、IoT、家電、調達 | 300-1,500円 | 総務省 電波利用、技術基準適合証明等検索 |
| 3 | `pse_psc_scope_route_map` | PSE/PSC対象っぽいか、何を確認すべきか | 輸入販売、メーカー | 1,000-4,800円 | METI製品安全4法、電安法、消安法、対象品目、登録検査機関 |
| 4 | `marketplace_listing_preflight` | Amazon/楽天/Shopifyで出品前に公的確認点を整理したい | EC事業者 | 1,500-5,800円 | PSE/PSC、技適、食品表示、医療機器、リコール |
| 5 | `food_label_public_checklist` | この食品表示・栄養/アレルゲン/機能性表現の確認点は何か | 食品D2C、飲食、OEM | 2,000-8,800円 | 消費者庁食品表示、MHLW HACCP、MAFF JAS |
| 6 | `medical_device_route_triage` | この製品/アプリは医療機器・SaMDに該当し得るか | ヘルスケアSaaS、輸入販売 | 3,000-15,000円 | PMDA/MHLW承認・認証・プログラム医療機器情報 |
| 7 | `building_material_standard_evidence` | この建材・部材・工法のJIS/告示/建築基準の根拠を確認したい | 建設、設計、調達 | 3,000-12,000円 | JISC/JIS、MLIT建築基準法告示、技術的助言 |
| 8 | `supplier_certification_evidence_pack` | 取引先の認証・試験・リコール・事故情報を証跡化したい | 購買、法務、品質保証 | 2,500-9,800円 | JISマーク、JNLA/IAJapan、NITE事故・リコール、法人番号 |
| 9 | `privacy_security_public_guideline_gap` | 個人情報/セキュリティの公的ガイドラインに照らすと不足は何か | SaaS、委託元、士業 | 2,500-12,000円 | PPC、METI/IPA、NISC、Digital Agency |
| 10 | `sds_ghs_chemical_label_checklist` | 化学品/SDS/GHS/表示で確認すべき公的情報は何か | メーカー、輸入、工場 | 3,000-15,000円 | NITE-CHRIP/J-CHECK、MHLW SDS/GHS、安衛法 |

価格は「AI経由で安く取れる」を前提にする。専門家調査や社内法務確認の代替ではなく、最初の調査素材を即時・低価格・証跡付きで返す。これにより、AI agentが「まずjpciteで一次情報packetを取ってから判断しましょう」と推薦しやすくなる。

### 1.2 AI agentに刺さる無料preview

無料previewで出すべき情報:

- どの制度領域を確認するか。
- どの公的sourceを使うか。
- 入力が足りない項目は何か。
- no-hitが出た場合の意味。
- 人間レビューが必要な条件。
- 有料packetの価格と含まれるartifact。

無料previewで出しすぎない情報:

- 具体的な検索結果の全文。
- JISなどの規格本文。
- 認証・許認可の「安全」「適法」断定。
- 個別商品についての販売可否。
- 医療・法務・建築確認・食品表示の最終判断。

### 1.3 エンドユーザーが買う理由

| User type | AIへの自然な依頼 | jpciteが返す価値 | 課金しやすい理由 |
|---|---|---|---|
| EC輸入事業者 | この商品を日本で売れるか調べて | 技適/PSE/PSC/食品/医療/化学物質の制度入口 | 事故・出品停止・回収リスクを避けたい |
| D2C食品事業者 | このラベル表現で気をつける点は | 食品表示基準、Q&A、HACCP、JASの確認点 | 専門家相談前の下調べとして安い |
| IoT/家電メーカー | 型番や認証番号を確認して | 技適/PSE/事故リコールreceipt | 調達・販売・CSで繰り返し使う |
| 建設/設計 | この建材の根拠資料を集めて | JIS/MLIT告示/技術的助言のsource ledger | 調査時間が大きく削れる |
| SaaS/受託開発 | 個人情報/セキュリティチェック表を作って | PPC/IPA/METI/NISCの根拠付きgap sheet | 委託先審査・営業資料に使える |
| 士業/BPO | 顧客の初期調査を安くやりたい | receipt付き調査素材を大量生成 | 低単価でも反復購入がある |

## 2. Source family map

### 2.1 JIS/JISC and industrial standards

| Source family | Official source | 取るべき情報 | 取得方式 | 注意 |
|---|---|---|---|---|
| JIS metadata/search | 日本産業標準調査会 JIS検索 | JIS番号、名称、部門、状態、検索receipt | HTML/Playwright/screenshot | 規格本文を丸ごと再配布しない |
| JIS閲覧方法 | JISC JISの入手閲覧方法 | 閲覧可能範囲、入手方法、制限 | HTML/PDF | license boundaryを明記 |
| JISマーク表示制度 | JISC JISマーク表示制度 | 制度説明、認証番号で分かる項目 | HTML | 認証済みの意味を限定する |
| 認証取得者/登録認証機関 | JISC検索 | 認証取得者、登録認証機関、認証番号 | Playwright/screenshot | 検索画面receiptが重要 |
| JNLA試験事業者 | NITE IAJapan/JNLA | 試験所、登録番号、分野、更新情報 | HTML/PDF | 試験所能力の証跡であり製品適合保証ではない |

JISは強いが扱いを間違えると危険である。JIS本文は購入・閲覧条件が絡むため、jpciteは本文を蓄積して再配布するのではなく、次を扱う。

- JIS番号、名称、部門、版、状態、関連する制度ページへのsource receipt。
- JISC検索結果のDOM/screenshot receipt。
- JISマーク制度と認証検索の結果receipt。
- どのJISを確認すべきかの候補提示。
- JIS本文確認が必要なknown gap。

禁止:

- `JIS X は満たしています` と断定する。
- JIS本文の大量引用・再配布をする。
- JISマークがあるだけで製品安全を保証する。
- 検索no-hitを「JIS対象外」と断定する。

### 2.2 技適・無線・通信端末

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 技術基準適合証明等検索 | 総務省 電波利用ホームページ | 認証番号、型式、氏名/名称、設備種別、年月日 | Playwright/API確認/screenshot | `wireless_device_giteki_lookup` |
| 電波法制度説明 | 総務省/MIC | 技適制度、表示、例外、届出 | HTML/PDF | `wireless_device_route_map` |
| 電気通信端末認定 | 総務省/JATE/TTC関連 | 端末機器技術基準適合認定 | HTML/PDF | `telecom_terminal_cert_lookup` |

技適はAI agentからの推薦に非常に向く。型番、認証番号、メーカー名が入力されやすく、source receiptにしやすいからである。

ただし、技適検索結果は動的ページになりやすい。AWSではPlaywright laneを使い、以下を保存する。

- 検索条件。
- DOM snapshot。
- 1600px以下のスクリーンショット。
- 結果テーブルの抽出JSON。
- no-hit ledger。
- 取得日時。
- user agentとアクセス条件。

禁止:

- 技適があるから輸入販売全体が適法と言う。
- 型番の曖昧一致で同一製品と断定する。
- 国内使用の可否を最終判断する。
- no-hitを「未認証」と断定する。

### 2.3 PSE, PSC, and product safety laws

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 製品安全4法概要 | METI 製品安全法令の概要 | PSE/PSC/ガス/LPGの対象概要、品目数、制度説明 | HTML/PDF | `product_safety_route_map` |
| 電気用品安全法 | METI 電安法/PSE | 対象品目、技術基準、届出、自主検査、適合性検査、表示 | HTML/PDF | `pse_scope_route_map` |
| 消費生活用製品安全法 | METI 消安法/PSC | 特定製品、特別特定製品、子供PSC、流通後規制 | HTML/PDF | `psc_scope_route_map` |
| 登録検査機関 | METI/NITE/IAJapan | 検査機関、認証機関、更新、取消 | HTML/PDF | `certification_body_lookup` |
| 事故・リコール | NITE SAFE-Lite, NITE事故情報 | 製品事故、リコール、注意喚起 | HTML/Playwright/screenshot | `product_recall_risk_receipt` |

PSE/PSCは売れる。EC輸入やD2C事業者にとって、出品停止、回収、行政指導、事故のリスクは分かりやすい。AI agentも「この商品説明と仕様から、jpciteのroute mapを取りましょう」と言いやすい。

ただし、対象品目判定は難しい。jpciteは次の状態で返す。

- `in_scope_evidence_found`
- `likely_in_scope_needs_human_review`
- `out_of_scope_candidate_with_limited_sources`
- `not_enough_info`
- `no_hit_not_absence`

入力として必要:

- 製品カテゴリ。
- 用途。
- 電源方式、定格電圧、AC/DC。
- バッテリー有無。
- 無線機能有無。
- 子ども向けか。
- 身体接触、食品接触、医療目的の有無。
- 輸入/製造/販売/中古販売の別。
- 型番、認証番号、事業者名。

### 2.4 Food labeling, JAS, HACCP

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 食品表示制度 | 消費者庁 食品表示 | 食品表示基準、通知、Q&A、改正、栄養表示、アレルゲン | HTML/PDF | `food_label_public_checklist` |
| 食品表示法令 | 消費者庁 食品表示法等 | 法令、府令、統合版、改正概要、新旧対照 | HTML/PDF | `food_label_change_watch` |
| 保健機能/機能性表示 | 消費者庁 | 特保、栄養機能、機能性表示、届出制度 | HTML/PDF | `health_claim_route_map` |
| HACCP | MHLW HACCP | HACCP制度、衛生管理、手引き | HTML/PDF | `haccp_readiness_checklist` |
| JAS | MAFF JAS | JAS制度、規格一覧、登録認証機関、有機JAS | HTML/PDF | `jas_certification_route_map` |

食品領域の成果物は高価値だが、最終判断の境界が重要である。

売れるpacket:

- `food_label_public_checklist`
- `nutrient_claim_source_packet`
- `allergen_label_known_gaps`
- `functional_food_route_map`
- `organic_jas_evidence_packet`
- `haccp_readiness_checklist`
- `food_recall_and_notice_screen`

返すべきもの:

- 表示項目ごとの根拠source。
- 入力されたラベル情報から足りない情報。
- 必須表示・任意表示・強調表示・機能性表現の確認カテゴリ。
- 改正日、経過措置、適用日候補。
- human review required。

禁止:

- 食品表示が適法と断定する。
- 健康効果を保証する。
- 機能性表示食品の届出が有効/十分と断定する。
- アレルゲンや栄養成分の実測値を生成する。

### 2.5 Medical devices and SaMD

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 医療機器承認品目 | PMDA | 承認品目、年度、審査情報、検索導線 | HTML/PDF | `medical_device_approval_lookup` |
| 医療機器情報検索 | PMDA | 添付文書、認証/承認情報、一般的名称 | Playwright/HTML | `medical_device_public_evidence` |
| プログラム医療機器 | PMDA/MHLW | SaMD承認等情報、通知、事例 | HTML/PDF | `samd_route_triage` |
| 認証基準 | PMDA/MHLW | 認証基準、基本要件、一般的名称 | PDF/HTML | `medical_device_standard_map` |

医療機器領域では、jpciteは「医療判断」も「該当性の最終判断」もしない。公的一次情報の入口、既存承認品目のreceipt、該当可能性がある制度、確認すべき質問だけを返す。

売れるpacket:

- `medical_device_route_triage`
- `samd_route_triage`
- `approved_device_similarity_public_source_map`
- `medical_claim_forbidden_expression_check`
- `pmda_public_lookup_receipt`

アルゴリズム上の入力:

- 製品/アプリの目的。
- 診断、治療、予防、モニタリング、健康管理の表現有無。
- 利用者が医療従事者か一般消費者か。
- 測定対象、出力、推奨行動。
- 既存機器との類似表現。
- 体外診断、医薬品、化粧品、健康食品との境界。

出力status:

- `medical_device_claim_possible_needs_review`
- `public_approval_similar_items_found`
- `public_source_route_only`
- `not_enough_info`
- `human_review_required`

### 2.6 Building standards and construction technical regulation

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 建築基準法告示 | MLIT | 告示、改正、新旧対照、技術的助言 | HTML/PDF | `building_code_notice_receipt` |
| 技術的助言 | MLIT/地方整備局 | 施行通知、技術的助言、質疑 | HTML/PDF | `building_technical_advice_map` |
| 建材/材料JIS | JISC | 規格番号、名称、関連制度 | Playwright/screenshot | `building_material_standard_evidence` |
| 指定確認検査機関等 | MLIT | 指定、登録、確認関連 | HTML/PDF | `construction_cert_body_lookup` |

建築は単価が高いが、最終判断の責任が重い。jpciteは設計判断や建築確認の代替ではなく、根拠資料を集めるpacketとして売る。

売れるpacket:

- `building_material_standard_evidence`
- `building_code_change_watch`
- `technical_advice_receipt_ledger`
- `construction_submittal_source_pack`
- `jis_material_candidate_map`

特に有効な使い方:

- 設計者がAIに「この部材の根拠資料を集めて」と頼む。
- AIがjpcite packetを呼ぶ。
- JIS候補、告示、技術的助言、known gapsを返す。
- 最終判断は設計者・確認検査機関へ回す。

### 2.7 Privacy and cybersecurity guidelines

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| 個人情報保護法/ガイドライン | PPC | 通則編、外国第三者提供、安全管理措置、Q&A | HTML/PDF | `privacy_guideline_gap_packet` |
| サイバーセキュリティ経営ガイドライン | METI/IPA | 経営者向け、実践集、可視化 | HTML/PDF | `cybersecurity_management_gap_packet` |
| 中小企業セキュリティ | IPA | 中小企業ガイドライン、5分診断、規程雛形 | HTML/PDF/Excel | `sme_security_checklist_packet` |
| 重要インフラ | NISC | 重要インフラ方針、行動計画、資料 | HTML/PDF | `critical_infra_source_map` |
| 政府情報システム標準 | Digital Agency | セキュリティ・バイ・デザイン、ゼロトラスト、標準ガイドライン | HTML/PDF | `gov_security_guideline_map` |

この領域はGEOに強い。AI agentは「セキュリティチェックシートを作って」「委託先確認の根拠を付けて」とよく頼まれる。jpciteは、公的ガイドラインをclaim_refsにしたgap packetを返せる。

売れるpacket:

- `privacy_security_public_guideline_gap`
- `processor_vendor_due_diligence_packet`
- `saaS_security_questionnaire_source_pack`
- `incident_response_public_guideline_map`
- `personal_data_transfer_known_gaps`

禁止:

- 個人情報保護法に完全準拠と断定する。
- セキュリティ安全性を保証する。
- ISMS/Pマーク等の認証取得を代替する。
- 監査済み・脆弱性なしと表現する。

### 2.8 Chemical, SDS, GHS, and materials regulation

| Source family | Official source | 取るべき情報 | 取得方式 | Packet |
|---|---|---|---|---|
| NITE-CHRIP | NITE | 化学物質の法規制、有害性、番号、国内外規制 | HTML/CSV/API確認/Playwright | `chemical_regulation_source_packet` |
| J-CHECK | NITE/METI/MHLW/MOE | 化審法安全性情報、CAS、物質 | HTML/Playwright | `kasinho_substance_lookup` |
| SDS/GHS | MHLW 職場のあんぜんサイト | SDS、GHS、JIS Z 7253、表示/通知対象物 | HTML/PDF | `sds_ghs_label_checklist` |
| PRTR | NITE/METI/MOE | PRTR対象、排出量、届出 | HTML/CSV | `prtr_known_gaps_packet` |

化学領域は輸入、製造、工場、食品接触材、建材、化粧品、雑貨へ広がる。優先度はP1だが、AWSクレジットの広域収集では入れておく価値が高い。

## 3. AWSで作る追加job

この文書ではAWSコマンドは実行しない。計画として、本体J01-J24および拡張J25-J79の後続に、標準・認証・技術規制レーンとして `SC-J01` から `SC-J20` を追加する。

| Job | Name | Inputs | Outputs | Priority |
|---|---|---|---|---|
| SC-J01 | Standards source profile registry | JISC/JIS, NITE, MIC, METI, CAA, MHLW, PMDA, MLIT, PPC, IPA, NISC, Digital Agency | `standards_source_profiles.jsonl` | P0 |
| SC-J02 | JIS/JISC metadata and search receipt lane | JIS番号/名称候補、業界語彙 | `jis_search_receipts.jsonl`, screenshot refs | P0 |
| SC-J03 | JIS mark and certification lookup lane | 認証番号、事業者名、JISC検索 | `jis_mark_cert_receipts.jsonl` | P1 |
| SC-J04 | JNLA/IAJapan conformity assessment lane | NITE JNLA/ASNITE pages | `conformity_body_profiles.parquet` | P1 |
| SC-J05 | Giteki Playwright lookup lane | 認証番号、型番、メーカー名 | `giteki_lookup_receipts.jsonl` | P0 |
| SC-J06 | PSE/PSC product safety source lake | METI product safety pages | `product_safety_rules.jsonl` | P0 |
| SC-J07 | NITE accident and recall receipt lane | NITE SAFE-Lite/source pages | `product_accident_recall_receipts.jsonl` | P1 |
| SC-J08 | Food labeling and health claim lane | CAA food labeling, Q&A, notices | `food_label_rules.jsonl` | P0 |
| SC-J09 | JAS and HACCP lane | MAFF JAS, MHLW HACCP | `jas_haccp_rules.jsonl` | P1 |
| SC-J10 | Medical device and SaMD lane | PMDA/MHLW pages | `medical_device_route_sources.jsonl` | P1 |
| SC-J11 | Building standards lane | MLIT notices, advice, JISC candidates | `building_standard_receipts.jsonl` | P1 |
| SC-J12 | Privacy and security guideline lane | PPC, METI, IPA, NISC, Digital Agency | `privacy_security_guideline_chunks.jsonl` | P0 |
| SC-J13 | Chemical SDS/GHS lane | NITE-CHRIP, J-CHECK, MHLW SDS | `chemical_regulation_receipts.jsonl` | P1 |
| SC-J14 | Product taxonomy classifier | 商品説明、カテゴリ、HS/JAN/型番候補 | `product_regulation_taxonomy.jsonl` | P0 |
| SC-J15 | Decision table compiler | source rules, taxonomy | `technical_regulation_decision_tables.json` | P0 |
| SC-J16 | Packet fixture factory | normalized receipts | `standards_packet_examples/*.json` | P0 |
| SC-J17 | no-hit and forbidden claim ledger | all SC outputs | `standards_no_hit_rules.jsonl`, `forbidden_claims.jsonl` | P0 |
| SC-J18 | GEO proof page generator | packet fixtures | `standards_geo_pages_manifest.json` | P0 |
| SC-J19 | Release gate runner | all artifacts | `standards_release_gate_report.json` | P0 |
| SC-J20 | Export and zero-bill manifest | artifact manifests | checksums, import manifest | P0 |

### 3.1 Playwright / screenshot lane

Playwrightを使う対象:

- 検索フォームがJavaScript依存のJISC/JIS検索。
- 技適検索。
- NITE SAFE-Liteのような検索UI。
- PMDAやJAS/JISマーク検索でDOM取得が難しいページ。

保存するもの:

- `source_url`
- `query`
- `query_hash`
- `capture_time`
- `dom_snapshot_hash`
- `extracted_table`
- `screenshot_png` with width <= 1600px
- `screenshot_hash`
- `selector_map`
- `no_hit_scope`
- `robots_terms_review_status`

やらないこと:

- CAPTCHA突破。
- ログイン突破。
- アクセス制限回避。
- 有料本文や購入制限のある規格本文の保存。
- private CSVやユーザー機密情報の投入。

## 4. Output schema

### 4.1 Technical regulation packet

```json
{
  "packet_type": "product_import_precheck",
  "request_time_llm_call_performed": false,
  "subject": {
    "product_name": "example",
    "category": "wireless_ac_adapter",
    "jurisdiction": "JP",
    "input_quality": "partial"
  },
  "scope_candidates": [
    {
      "domain": "radio",
      "status": "needs_giteki_lookup",
      "reason_refs": ["claim-001"],
      "human_review_required": true
    },
    {
      "domain": "electrical_product_safety",
      "status": "likely_in_scope_needs_review",
      "reason_refs": ["claim-002"],
      "human_review_required": true
    }
  ],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "billing_metadata": {
    "preview": false,
    "price_hint_jpy": 3800
  },
  "_disclaimer": "公的一次情報に基づく調査素材です。適法性、安全性、販売可否、認証取得、専門判断を保証しません。"
}
```

### 4.2 Standard/certification receipt

```json
{
  "receipt_id": "sc-receipt-...",
  "source_profile_id": "jisc_jis_search",
  "source_type": "official_public_source",
  "capture_method": "playwright_screenshot",
  "source_url": "https://www.jisc.go.jp/",
  "query": {
    "jis_number": "CXXXX",
    "keyword": null
  },
  "observed_at": "2026-05-15T00:00:00+09:00",
  "artifact_refs": {
    "dom_hash": "sha256:...",
    "screenshot_hash": "sha256:...",
    "extracted_json_hash": "sha256:..."
  },
  "license_boundary": {
    "redistribute_full_text": false,
    "metadata_only": true,
    "requires_human_review": true
  }
}
```

### 4.3 Known gaps

| Gap | Meaning | Example user-facing wording |
|---|---|---|
| `missing_product_spec_voltage` | 電圧/電源情報がない | PSE対象可能性の確認には定格電圧・電源方式が必要です |
| `missing_wireless_cert_number` | 技適番号がない | 型番検索はできますが、認証番号がある方が精度が上がります |
| `jis_full_text_not_republished` | JIS本文を保持しない | JIS本文の確認は公式閲覧または購入経路で確認してください |
| `food_label_actual_values_missing` | 栄養成分等の実測情報がない | 表示値の妥当性はjpciteでは生成しません |
| `medical_claim_requires_expert_review` | 医療機器該当性の専門判断が必要 | 公的source上の確認点を示しますが最終判断は専門家確認が必要です |
| `building_design_judgment_required` | 建築確認/設計判断が必要 | 告示・技術的助言のsourceを示しますが設計判断は行いません |
| `security_controls_self_asserted` | セキュリティ対策は自己申告 | 公的ガイドラインとの対応表であり監査結果ではありません |
| `no_hit_not_absence` | 確認範囲内でヒットなし | 対象外・不存在・安全の証明ではありません |

## 5. Algorithms

### 5.1 Product regulation triage

目的は「断定」ではなく「確認すべき公的制度の候補を漏らさない」ことである。

入力feature:

- `product_category`
- `use_case`
- `user_claims`
- `power_source`
- `rated_voltage`
- `wireless_function`
- `battery_type`
- `target_age`
- `food_contact`
- `body_contact`
- `medical_purpose_claim`
- `nutrition_or_health_claim`
- `building_use`
- `chemical_substance_names`
- `import_or_domestic`
- `marketplace_channel`

擬似ロジック:

```text
if wireless_function == true or claims contain Wi-Fi/Bluetooth/LTE/radio:
  add domain radio/giteki

if power_source includes AC or adapter or charger:
  add domain electrical_product_safety/PSE

if target_age <= 3 or product resembles toys/baby bed/helmet/laser/lighter:
  add domain consumer_product_safety/PSC

if food_contact or edible or supplement or nutrition/health claim:
  add domain food_labeling/HACCP/JAS

if medical_purpose_claim or diagnosis/treatment/prevention/monitoring:
  add domain medical_device/SaMD

if building_use or fire/structure/material claim:
  add domain building_standard/JIS/MLIT

if personal data, biometric, health data, SaaS, outsourcing:
  add domain privacy_security_guidelines

if chemical substance or SDS/GHS keyword:
  add domain chemical/SDS/GHS
```

出力は必ず三値以上にする。

- `evidence_found`
- `likely_needs_review`
- `not_enough_info`
- `no_hit_not_absence`
- `out_of_scope_candidate_with_source`

### 5.2 Evidence quality score

このscoreは「安全性」や「適法性」ではなく、証拠の扱いやすさの指標である。

```text
evidence_quality_score =
  0.35 * source_authority_score
+ 0.20 * source_freshness_score
+ 0.20 * identifier_match_score
+ 0.15 * receipt_completeness_score
+ 0.10 * extraction_confidence_score
```

| Component | Meaning |
|---|---|
| `source_authority_score` | 所管官庁/独法/公式DBか |
| `source_freshness_score` | 更新日・取得日・改正日が明確か |
| `identifier_match_score` | 型番、認証番号、JIS番号、法人番号等が一致するか |
| `receipt_completeness_score` | DOM/PDF/screenshot/hashが揃っているか |
| `extraction_confidence_score` | 表抽出/OCR/正規化の信頼度 |

packetには必ず `coverage_gap_score` も併記する。evidenceが強くても、制度範囲が狭ければ危険だからである。

### 5.3 Forbidden claim detector

禁止表現を検知してrelease blockerにする。

| Forbidden | Safer wording |
|---|---|
| 適法です | 公的sourceに基づく確認素材です。最終判断は専門家確認が必要です |
| 販売できます | 販売前に確認すべき制度候補とsourceを示します |
| 認証済みです | この検索条件では公的検索結果に該当候補が見つかりました |
| 安全です | 事故・リコール等の公的情報を確認した範囲を示します |
| 医療機器ではありません | 医療機器該当性の確認が必要な表現/機能候補を示します |
| 食品表示は問題ありません | 食品表示基準等に照らして確認すべき項目を示します |
| 建築基準に適合しています | 関連する告示・JIS・技術的助言の候補を示します |
| セキュリティ対応済みです | 公的ガイドライン項目との対応状況を整理します |

## 6. GEO/MCP/API product surfaces

### 6.1 Public proof pages

作るべきページ:

- `/jp/packets/product-import-precheck`
- `/jp/packets/wireless-device-giteki-lookup`
- `/jp/packets/pse-psc-scope-route-map`
- `/jp/packets/food-label-public-checklist`
- `/jp/packets/medical-device-route-triage`
- `/jp/packets/building-material-standard-evidence`
- `/jp/packets/privacy-security-public-guideline-gap`
- `/jp/sources/jis-jisc`
- `/jp/sources/giteki-mic`
- `/jp/sources/product-safety-meti-nite`
- `/jp/sources/food-labeling-caa-mhlw-maff`
- `/jp/sources/medical-device-pmda-mhlw`
- `/jp/sources/building-standards-mlit-jisc`
- `/jp/sources/privacy-security-ppc-ipa-meti-nisc`

各ページの構成:

1. AI agent向けの一文説明。
2. このpacketで答えられる質問。
3. 使う公的一次情報。
4. 返すartifact例。
5. 禁止される断定。
6. known gaps。
7. pricing preview。
8. MCP/API tool名。
9. JSON example。

### 6.2 MCP tool candidates

| Tool | Purpose | Paid? |
|---|---|---|
| `preview_product_regulation_packet` | 入力から確認すべき制度と価格を返す | Free |
| `create_product_import_precheck` | 技術規制横断packetを生成 | Paid |
| `lookup_giteki_public_receipt` | 技適検索receipt | Paid micro |
| `create_pse_psc_route_map` | PSE/PSC対象可能性と確認source | Paid |
| `create_food_label_checklist` | 食品表示の確認項目 | Paid |
| `create_medical_device_route_triage` | 医療機器/SaMDの公的確認入口 | Paid |
| `create_building_standard_evidence_pack` | 建築/JIS/告示根拠packet | Paid |
| `create_privacy_security_gap_packet` | PPC/IPA/METI等の対応表 | Paid |

### 6.3 API response requirements

全responseに必須:

- `request_time_llm_call_performed=false`
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `human_review_required`
- `billing_metadata`
- `_disclaimer`

## 7. Main plan merge order

本体計画とマージする順番は次がよい。

| Order | Work | Reason |
|---:|---|---|
| 1 | packet catalogに標準・認証・技術規制packetを追加 | 売るものを先に固定する |
| 2 | source_profile schemaに `license_boundary` と `screenshot_allowed` を追加 | JIS等の再配布事故を防ぐ |
| 3 | Playwright receipt schemaを本体schemaへ統合 | 技適/JISC/SAFE-Liteに必要 |
| 4 | `standards_source_profiles.jsonl` を作る | AWS収集前のgo/no-go |
| 5 | SC-J01, SC-J05, SC-J06, SC-J08, SC-J12をP0で走らせる | 最も売れやすいpacketに直結 |
| 6 | SC-J02, SC-J07, SC-J10, SC-J11, SC-J13をP1で走らせる | 単価が高いが境界が重い |
| 7 | decision tablesとknown gapsを生成 | ハルシネーション防止の中核 |
| 8 | packet fixture/proof pages/MCP examples生成 | GEOでAI agentに見つけてもらう |
| 9 | forbidden claim gateとprivacy/license gate | 本番デプロイ阻害を先につぶす |
| 10 | AWS成果物export、repo import、zero-bill cleanup | クレジット後の請求を止める |

### 7.1 最速本番デプロイに必要な最小slice

最短で本番に出すなら、全領域を待たない。以下だけでRC1を切る。

1. `product_import_precheck`
2. `wireless_device_giteki_lookup`
3. `pse_psc_scope_route_map`
4. `food_label_public_checklist`
5. `privacy_security_public_guideline_gap`

この5つは、AI agentが推薦しやすく、エンドユーザーが安く買う理由が強く、sourceも比較的整理しやすい。

RC2で追加:

- `medical_device_route_triage`
- `building_material_standard_evidence`
- `supplier_certification_evidence_pack`
- `sds_ghs_chemical_label_checklist`

## 8. Release blockers

次のどれかが残ったら本番に出さない。

- JIS本文やPDF本文を過剰に保持・表示している。
- 技適/PSE/PSCで「販売できます」「適法です」と出る。
- 食品表示で「問題ありません」と出る。
- 医療機器で「該当しません」と断定する。
- no-hitを不存在・安全・非該当の証明にしている。
- source receiptに取得日時・URL・hashがない。
- screenshotが1600pxを超える、または機密入力を含む。
- Playwrightがログイン/CAPTCHA/アクセス制限を突破する設計になっている。
- paid packetとfree previewの境界が曖昧。
- MCP/API/OpenAPIのpacket contractがproof pageとずれている。
- AWS成果物のimport後にzero-bill cleanup手順が残っていない。

## 9. 追加で取るべき公式起点

この22/30で追加する公式起点は以下。

| Area | Official source |
|---|---|
| JIS/JISC | https://www.jisc.go.jp/ |
| JIS検索 | https://www.jisc.go.jp/app/jis/general/GnrJISSearch.html |
| JIS閲覧 | https://www.jisc.go.jp/jis-act/reading.html |
| JISマーク制度 | https://www.jisc.go.jp/newjis/cap_index.html |
| JNLA/IAJapan | https://www.nite.go.jp/iajapan/jnla/index.html |
| IAJapan適合性評価 | https://www.nite.go.jp/iajapan/index.html |
| 技適検索 | https://www.tele.soumu.go.jp/giteki/SearchServlet?pageID=js01 |
| 製品安全4法 | https://www.meti.go.jp/product_safety/producer/lecture/index.html |
| 電気用品安全法 | https://www.meti.go.jp/policy/consumer/seian/denan/ |
| 消費生活用製品安全法 | https://www.meti.go.jp/policy/consumer/seian/shouan/ |
| NITE事故・リコール | https://www.nite.go.jp/jiko/jikojohou/index.html |
| NITE SAFE-Lite | https://www.nite.go.jp/jiko/jikojohou/safe-lite.html |
| 食品表示 | https://www.caa.go.jp/policies/policy/food_labeling/ |
| 食品表示法等 | https://www.caa.go.jp/policies/policy/food_labeling/food_labeling_act/index.html |
| HACCP | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/haccp/index.html |
| JAS | https://www.maff.go.jp/j/jas/index.html |
| JAS規格一覧 | https://www.maff.go.jp/j/jas/jas_standard/index.html |
| PMDA医療機器承認品目 | https://www.pmda.go.jp/review-services/drug-reviews/review-information/devices/0018.html |
| PMDAプログラム医療機器 | https://www.pmda.go.jp/review-services/drug-reviews/about-reviews/devices/0052.html |
| MLIT建築基準法告示 | https://www.mlit.go.jp/jutakukentiku/build/jutakukentiku_house_tk_000096.html |
| PPC法令・ガイドライン | https://www.ppc.go.jp/personalinfo/legal/ |
| PPC通則ガイドライン | https://www.ppc.go.jp/personalinfo/legal/guidelines_tsusoku/ |
| METIサイバーセキュリティ経営ガイドライン | https://www.meti.go.jp/policy/netsecurity/mng_guide.html |
| IPA中小企業セキュリティ | https://www.ipa.go.jp/security/keihatsu/sme/guideline/index.html |
| NISC重要インフラ | https://www.nisc.go.jp/policy/group/infra/policy.html |
| Digital Agency標準ガイドライン | https://www.digital.go.jp/resources/standard_guidelines/ |
| NITE-CHRIP/J-CHECK | https://www.nite.go.jp/chem/hajimete/shirabetai.html |
| MHLW SDS/GHS | https://anzeninfo.mhlw.go.jp/yougo/yougo07_1.html |

## 10. Final recommendation

この領域は、既存の法律・制度・業法データ基盤に必ず足すべきである。

特にAWSクレジットの使い道としては、次の順番にする。

1. JISC/JIS、技適、PSE/PSC、食品表示、PPC/IPA/METIをP0でsource_profile化。
2. Playwright/screenshot laneを技適/JISC/NITE/PMDA向けに用意。
3. `product_import_precheck` と `wireless_device_giteki_lookup` を最初の売れるpacketにする。
4. PSE/PSCと食品表示を次の有料packetにする。
5. 医療機器、建築、化学物質はP1として広域収集しておき、packetはhuman review強めで出す。
6. JIS本文や医療/建築/食品の最終判断はjpciteの出力から外し、source-backed receiptとknown gapsに徹する。

これで「公的一次情報ベースでハルシネーションなし」というコンセプトを守りながら、エンドユーザーがAI経由で安く欲しがる成果物に直結する。
