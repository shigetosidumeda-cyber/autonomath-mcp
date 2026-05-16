# AWS scope expansion 01: Japan public corpus map

作成日: 2026-05-15
担当: 拡張深掘り 1/30 - 日本の公的一次情報コーパス全体設計
対象: jpcite 本体計画、AWS credit run、既存 J01-J24 の scope expansion
状態: 計画のみ。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行はしていない。
書き込み範囲: このMarkdownのみ。

## 0. 結論

既存 J01-J24 は、AWS credit run の最初の骨格としては正しい。ただし、ユーザーが言う「日本の公的な情報、法律、制度、業法、それに関わる一次情報」を後から最大限に成果物化するには、現状の source family はまだ狭い。

狭い理由:

- `NTA / invoice / e-Gov law / J-Grants / gBizINFO / e-Stat / EDINET / JPO / procurement / enforcement / local PDF` までは入っている。
- しかし、官報、告示、通達、パブコメ、行政手続、許認可台帳、業法別登録、標準/認証、地理空間、国土/不動産、裁判/審決、自治体条例/制度、行政事業レビュー、白書/審議会資料、リコール/安全情報、公共調達の正本・補助DBの違いが明示的に足りない。
- APIで取れるsource中心になっており、Playwright/screenshot/OCRでしか取れない検索画面・PDF・JSページの扱いがまだ薄い。

したがって、J01-J24は廃止せず、以下のように位置づける。

```text
J01-J24 = first artifact factory
J25-J40 = Japan public corpus expansion lanes
J41-J48 = Playwright/screenshot/OCR and difficult-source lanes
J49-J52 = source-to-output coverage and productization lanes
```

最重要方針:

1. AWSは「URL収集」ではなく `source_receipt`、`claim_ref`、`known_gaps`、`no_hit_check`、`artifact candidates` を作る。
2. raw PDF/HTML/CSV/スクリーンショットは、利用条件が明確でない限り公開再配布しない。原則は hash、metadata、短い引用、抽出fact、source URL。
3. Playwrightと1600px以下スクリーンショットはAWSで可能。ただし、robots/terms回避、CAPTCHA回避、ログイン突破、IPローテーションは禁止。
4. no-hit は全sourceで `no_hit_not_absence`。不存在、安全、違反なし、登録なし、処分歴なし、適法、適格、採択可能とは言わない。
5. 後から成果物を増やせるよう、source familyごとに `what_can_be_claimed` と `what_must_be_gapped` を先に定義する。

## 1. 既存 J01-J24 の評価

### 1.1 現状で強いところ

| 領域 | 既存job | 評価 |
|---|---|---|
| 法人同定 | J02 | 法人番号spineとして最優先。正しい。 |
| 税/インボイス | J03 | CSV private overlayや取引先確認に効く。正しい。 |
| 法令 | J04 | e-Gov法令は必須。ただし告示/通達/パブコメ/官報が別途必要。 |
| 補助金/制度 | J05/J06 | J-GrantsとPDF抽出は正しいが、自治体・省庁・商工会系が広い。 |
| 法人活動 | J07 | gBizINFOは有効。ただし集約sourceなので上流source receiptも必要。 |
| 開示 | J08 | EDINETは会社baseline/DDに効く。XBRLまでの境界管理が必要。 |
| 調達 | J09 | p-portal/JETRO/官報/各機関正本の関係整理が必要。 |
| 行政処分 | J10 | 価値は高いが、業法別sourceと誤結合対策が必要。 |
| 統計 | J11 | e-Statは重要。ただし地理/国土/不動産/住所BRとの接続が必要。 |
| QA/Product | J12-J24 | receipt、claim graph、packet/proof、GEO、cleanupの考え方は正しい。 |

### 1.2 狭いところ

| 不足領域 | なぜ重要か | 追加すべき方向 |
|---|---|---|
| 官報 / 公布 / 会社公告 | 法令公布、公告、調達、破産/決算公告などの一次情報。 | raw全文ではなく metadata/deep link/hash/derived event を優先。 |
| 告示 / 通達 / 事務連絡 / ガイドライン | 実務では条文より運用文書が効く。 | 府省別document registryと改正watch。 |
| パブリックコメント | 制度変更の予兆、結果公示、規制変更の背景。 | 案件ID、所管、締切、結果、添付hash。 |
| 行政手続 / 申請API / 許認可 | 業法・許認可・必要書類の成果物に直結。 | e-Gov電子申請、マイナポータル、業法別台帳。 |
| 業法別登録/許認可台帳 | 建設、宅建、運送、介護、医療、古物、風営、食品等。 | sector permit registry family として分離。 |
| 標準 / 認証 / 適合性 | JIS、技適、ISMS、Pマーク、JISマーク等はDD/調達/製品確認に効く。 | metadata/証明番号/認証範囲/validityのreceipt化。 |
| 地理 / 住所 / 国土 / 不動産 | 所在地、自治体制度、災害/用途/地価/取引価格、地域統計へ接続。 | address base、GSI、国土数値情報、不動産情報ライブラリ。 |
| 裁判 / 審決 / 裁決 | 法的背景、独禁法、税務裁決、知財審決、労働等。 | 全判決網羅ではない前提でmetadata/hash/quote refs。 |
| 行政事業レビュー / 予算 / 支出先 | 補助金・委託・基金・公共支出の流れに効く。 | 予算事業、支出先、成果指標、年度差分。 |
| 白書 / 審議会 / 研究会資料 | 制度背景や業界規制の文脈。 | 政策根拠、予定、統計補助として扱う。 |
| 自治体条例/制度/処分/入札 | ローカル制度は成果物価値が高い。 | 都道府県/政令市から優先し、terms/robots後に拡大。 |

## 2. Source family taxonomy

source family は、sourceの種類ではなく「後からどんなclaimや成果物に変換できるか」で切る。

| Family ID | Family | Priority | 主なsource例 | AWS取得方法 | 代表成果物 |
|---|---|---:|---|---|---|
| `identity_tax` | 法人・税・登録番号 | P0 | 法人番号、インボイス | API/bulk | `company_public_baseline`, `invoice_counterparty_check` |
| `law_primary` | 法律・政省令・規則 | P0 | e-Gov法令API/XML | API/XML/bulk | `legal_basis_packet`, `regulatory_brief` |
| `gazette_notice` | 官報・公布・告示・公告 | P0/P1 | 官報発行サイト、内閣府官報電子化情報 | HTML/PDF metadata, hash, screenshot only if needed | `gazette_event_ledger`, `legal_change_watch` |
| `policy_process` | パブコメ・審議会・通達・ガイドライン | P0/P1 | e-Govパブコメ、省庁資料 | HTML/PDF/Playwright/OCR | `policy_change_watch`, `implementation_guidance_pack` |
| `procedure_permit` | 行政手続・許認可・業登録 | P0/P1 | e-Gov電子申請、MLIT業者検索、自治体台帳 | API/HTML search/Playwright/PDF | `permit_precheck_pack`, `sector_license_radar` |
| `subsidy_program` | 補助金・制度・公的支援 | P0 | J-Grants、府省/自治体PDF | API/HTML/PDF/OCR | `application_strategy`, `application_kit` |
| `public_finance` | 予算・行政事業レビュー・支出先 | P1 | 行政事業レビュー、予算資料、基金資料 | XLSX/CSV/PDF | `public_funding_flow_pack`, `grant_origin_trace` |
| `procurement_contract` | 調達・入札・落札・契約 | P0/P1 | p-portal、JETRO、官報、自治体入札 | API/CSV/HTML/PDF | `procurement_vendor_watch`, `sales_target_dossier` |
| `corporate_activity` | 法人活動集約 | P0/P1 | gBizINFO | API/download | `public_activity_signal`, `company_folder_bootstrap` |
| `filing_disclosure` | 開示・金融・XBRL | P0/P1 | EDINET、金融庁資料 | API/XBRL/PDF | `filing_key_facts`, `audit_public_trail` |
| `enforcement_safety` | 行政処分・命令・リコール・安全情報 | P0/P1 | FSA/JFTC/MHLW/MLIT/CAA等 | HTML/PDF/Playwright/OCR | `public_dd_evidence_table`, `risk_screen_with_gaps` |
| `court_decision` | 裁判例・審決・裁決 | P1 | 裁判例検索、公取委審決、国税不服審判所等 | HTML/PDF/search UI | `case_law_context_pack`, `claim_legal_context` |
| `ip_standard_cert` | 知財・標準・認証・適合性 | P1 | JPO、JIS/JISC、技適、Pマーク、ISMS | API/bulk/HTML search | `ip_certification_evidence_pack`, `product_compliance_brief` |
| `statistics_cohort` | 統計・地域・産業 | P0/P1 | e-Stat、RESAS代替、白書統計表 | API/CSV/XLSX/PDF | `regional_market_context`, `industry_cohort_packet` |
| `geo_land_address` | 住所・地理・国土・不動産 | P0/P1 | アドレスBR、GSI、国土数値情報、不動産情報ライブラリ | CSV/ZIP/tile/API/GeoJSON | `location_context_pack`, `site_due_diligence` |
| `local_government` | 自治体制度・条例・処分・入札 | P1 | 都道府県/市区町村サイト | allowlist crawl/Playwright/PDF/OCR | `local_regulation_digest`, `municipality_program_pack` |
| `official_reports` | 白書・年次報告・審議会/研究会 | P1/P2 | 内閣府/各省白書、会議資料 | HTML/PDF/OCR | `policy_background_brief`, `sector_trend_context` |
| `international_trade_fdi` | 貿易・投資・海外展開 | P1/P2 | JETRO、外為法/FDI資料、省庁ガイド | HTML/PDF/API where available | `fdi_company_entry_brief`, `export_compliance_context` |
| `political_public_integrity` | 政治資金・公告・法人周辺公共情報 | P2 | 総務省/選管/官報等 | PDF/CSV/HTML | `public_integrity_context` only with strict review |

## 3. Priority policy

### 3.1 P0-A: 先に取るべき backbone

P0-A は、他sourceの同定や成果物の正本になる。

| Source family | 先に作る理由 | 必須artifact |
|---|---|---|
| `identity_tax` | 法人番号/T番号が全joinのspine。 | `identity_spine.parquet`, `invoice_no_hit_checks.jsonl` |
| `law_primary` | 法令根拠が制度/許認可/業法成果物の土台。 | `law_article_claim_refs.jsonl` |
| `statistics_cohort` | 会社固有でなく地域/業種の客観文脈を作れる。 | `stat_claim_refs.jsonl` |
| `geo_land_address` | 所在地、自治体制度、地理・不動産・災害・用途をつなぐ。 | `address_normalization_ledger.jsonl` |
| `source_profile_terms` | 全sourceの利用境界がないと量産できない。 | `source_profile_delta.jsonl`, `license_terms_ledger.jsonl` |

### 3.2 P0-B: 成果物価値がすぐ出る実務source

| Source family | 使いどころ | 注意 |
|---|---|---|
| `subsidy_program` | 補助金・支援制度・必要書類・締切。 | eligibility/採択可能性は断定しない。 |
| `procurement_contract` | 公共営業、調達実績、事業者活動。 | p-portal/JETRO/官報/各機関正本の範囲を分ける。 |
| `corporate_activity` | gBizINFOで法人活動を横断。 | 集約sourceなので上流sourceとlicense継承を保存。 |
| `enforcement_safety` | DD/取引先確認/監査前確認。 | 誤結合・名誉毀損リスク最大。no-hit厳格。 |
| `procedure_permit` | 行政書士・業法DD・許認可前捌き。 | 業種ごとの台帳粒度が異なる。 |

### 3.3 P1: AWS creditがある今、広げる価値が大きいsource

| Source family | 理由 | 初期扱い |
|---|---|---|
| `gazette_notice` | 官報は法律・公告・調達・会社イベントに効く。 | metadata/deep link/hash。全文再配布はしない。 |
| `policy_process` | パブコメ、通達、ガイドラインは制度変更watchに効く。 | 案件/文書metadata、添付hash、短い抽出fact。 |
| `court_decision` | 法律/規制文脈の品質を上げる。 | 収録範囲付きmetadata、判示事項/短い引用、PDF hash。 |
| `ip_standard_cert` | 知財/標準/認証はB2B/DD/調達に効く。 | ID exact中心。名称joinは候補止まり。 |
| `public_finance` | 支援制度/委託/基金/支出先の背景が作れる。 | 年度・事業番号・支出先の範囲付き。 |
| `local_government` | ローカル制度・条例・処分・入札は商用価値が高い。 | 都道府県/政令市から allowlist。 |

## 4. AWS collection modes

AWSではsourceごとに取得方式を固定する。全sourceを同じcrawlerで扱わない。

| Mode | 用途 | AWS構成 | 成果物 | 禁止事項 |
|---|---|---|---|---|
| `api_bulk_mode` | 公式API/一括DL | Batch/Fargate, S3, Glue, Athena | normalized parquet, receipt, schema drift | rate limit無視、secretのログ出力 |
| `static_fetch_mode` | HTML/PDF/CSV/ZIPの静的取得 | Batch EC2 Spot, S3 | object_manifest, content_hash, extracted facts | robots/terms未確認の大量取得 |
| `pdf_text_mode` | text layer PDF | CPU parser, pdfplumber相当, S3 | page text hash, section refs | raw全文公開 |
| `ocr_mode` | 画像PDF/表 | CPU OCR/Textract conditional | bbox/span/confidence, review queue | low confidenceのclaim昇格 |
| `playwright_mode` | JS/検索画面/フォーム結果 | ECS/Batch container with Chromium | DOM snapshot, screenshot <=1600px, selector receipt | CAPTCHA回避、ログイン突破、総当たり |
| `screenshot_mode` | fetch困難ページの視覚証跡 | Playwright, S3, image compression | PNG/WebP screenshot, perceptual hash, viewport metadata | 個人情報ページ、認証ページ、巨大画像無制限保存 |
| `geo_mode` | tiles/GeoJSON/GML | Batch, GDAL tools, S3 | spatial index, bbox, dataset hash | タイル大量取得、出典なし地図表示 |
| `xbrl_mode` | EDINET/XBRL | Batch CPU, S3, Athena | element/context/unit facts | 投資助言/財務判断の断定 |
| `catalog_mode` | data.go.jp/API catalog/source discovery | API/CKAN, Batch | source candidates, resource terms ledger | カタログhitをデータ存在証明にすること |

### 4.1 Playwright and screenshot lane

ユーザーの「1600px以下のスクリーンショットやPlaywrightで、fetchが難しい部分でも突破する」イメージはAWSで実現できる。ただし、ここでいう突破は「レンダリングが必要な公開ページを正しく観測する」ことであり、アクセス制御の回避ではない。

標準設定:

- viewportは `1280x1600` を標準、必要に応じ `390x844` mobile smoke。
- screenshotは最大縦1600px。長大ページは全文スクロール画像ではなく、section単位に分割。
- `page_url`, `final_url`, `viewport`, `user_agent`, `fetched_at`, `dom_sha256`, `screenshot_sha256`, `visible_text_excerpt_hash`, `robots_decision` を保存。
- screenshotは `public_publish_allowed=false` から開始。公開可能性はsourceごとに判定。
- DOM/text抽出で十分な場合はscreenshotを成果物の正本にしない。screenshotは「観測証跡」。

使うべきsource:

- 検索フォーム結果しか出ない許認可台帳。
- JSで結果が描画されるJIS/認証/業者検索ページ。
- HTMLからリンクが見えるがPDF添付が多い自治体ページ。
- PDF viewerや古いサイトで通常fetchが不安定なページ。

使ってはいけないsource:

- CAPTCHA、ログイン、会員/有料検索、API利用条件で自動取得が禁じられるページ。
- 個人情報やセンシティブ情報を含む画面。
- 大量ページを画像で全保存するだけの低密度crawl。

## 5. Expanded source families

### 5.1 Law, gazette, notices, and policy process

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| e-Gov法令API/法令XML | P0 | law_id, law_num, article path, effective date, XML hash | API/XML | 条文参照、施行日、制度根拠 | legal adviceではない、条ずれ/改正未確認 |
| 官報発行サイト/官報電子化情報 | P0/P1 | issue date, 本紙/号外, page, title, PDF hash, deep link | HTML/PDF metadata, screenshot if needed | 公布/公告/eventの存在、官報掲載日 | 全文再配布不可、有料範囲、未掲載証明不可 |
| e-Govパブリックコメント | P0/P1 | 案件ID、所管、省令案、受付締切、結果公示、添付hash | HTML/PDF/Playwright | 政策変更予兆、結果公示、意見募集期間 | 制度確定ではない、結果未反映 |
| 府省告示/通達/事務連絡/ガイドライン | P1 | 文書番号、発出日、所管、PDF/HTML hash | source allowlist, PDF/OCR | 運用根拠、実務上の注意、改正watch | 法令と同格ではない、最新性/適用範囲 |
| 審議会/研究会資料 | P1/P2 | 会議名、回次、資料、議事録、開催日 | HTML/PDF/OCR | 制度背景、今後の方向性 | 決定事項ではない、政策案に留まる |

成果物例:

- `legal_change_watch`: 法令改正、公布、関連パブコメ、通達候補を時系列化。
- `regulatory_brief`: 業界別に「条文」「通達/ガイドライン」「所管」「未確認範囲」を返す。
- `implementation_guidance_pack`: 申請や業務運用で見るべき一次資料URL、文書番号、更新日を整理。
- `public_comment_alert`: AI agentが「この制度は変更途中」と伝えるための案件カード。

### 5.2 Procedures, permits, and sector registries

| Sector | Priority | Source examples | AWS method | Output value | Risk |
|---|---:|---|---|---|---|
| 建設/宅建/マンション/賃貸住宅 | P0/P1 | 国交省 建設業者・宅建業者等企業情報検索 | Playwright/HTML search/screenshot | 許可/免許確認、DD質問 | 表示誤り注意、同名/所在地/許可番号 |
| 運送/自動車/物流 | P1 | 国交省処分/許認可、運輸局資料 | HTML/PDF/OCR | 物流コンプライアンスbrief | 地方運輸局ごとに分散 |
| 労働/派遣/職業紹介 | P1 | 厚労省/労働局の許可・処分情報 | HTML/PDF/Playwright | 人材業DD、許可確認 | 個人名/同名/古い公表 |
| 介護/医療/福祉 | P1 | 厚労省/自治体/介護サービス情報 | API/HTML/PDF | 事業所/指定/処分確認 | 事業所単位で法人番号が薄い |
| 食品/衛生/営業許可 | P1/P2 | 自治体公開台帳/処分情報 | local allowlist/Playwright | 店舗/営業許可確認 | 個人事業者/店舗名 |
| 古物/風営/産廃/警備 | P1/P2 | 警察/自治体/所管庁台帳 | HTML/PDF, manual review | 許認可前捌き | 再配布/個人情報/網羅性 |
| 金融/貸金/資金移動/暗号資産 | P1 | 金融庁登録一覧/行政処分 | HTML/CSV/PDF | financial regulatory status | 投資/与信判断禁止 |
| 電気通信/技適/無線 | P1 | 総務省 技術基準適合証明Web-API | API | 機器/製品適合性確認 | 型番/番号exact以外は弱い |

成果物例:

- `permit_precheck_pack`: 業種、地域、法人番号/許可番号から、必要な一次資料、確認質問、未確認範囲を出す。
- `sector_license_radar`: 既存顧問先や取引先リストに対し、許認可更新/処分/登録変更のwatch条件を作る。
- `administrative_scrivener_intake_kit`: 行政書士向けの受任前ヒアリング表、必要書類候補、根拠URL。
- `sector_compliance_change_digest`: 業法改正、通達、所管資料、許認可台帳更新をまとめる。

### 5.3 Subsidies, public programs, finance, and budgets

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| J-Grants public API | P0 | subsidy_id, title, deadline, target, agency, API version | API | 公募候補、締切、所管 | 採択可能性/ eligibility 断定禁止 |
| 府省/中小機構/自治体制度PDF | P0/P1 | 要件、対象、補助率、必要書類、問い合わせ | PDF/OCR/Playwright | application strategy candidate | PDF古さ、OCR低信頼、自治体外source |
| 行政事業レビュー | P1 | 事業番号、予算、支出先、成果指標 | XLSX/CSV/PDF | 財源/事業背景、支出先public trail | 個別採択/契約と混同しない |
| 政府系金融/保証/信用保証協会 | P1/P2 | 制度名、対象、保証枠、窓口 | HTML/PDF/OCR | loan/subsidy combo候補 | 融資/保証可否の断定禁止 |

成果物例:

- `application_strategy`: 既存P0 packet。さらに、制度根拠/必要資料/未確認範囲を厚くする。
- `subsidy_loan_combo_strategy`: 補助金と制度融資/保証を同時に見るが、融資可否は判断しない。
- `grant_origin_trace`: 予算事業、所管、基金、事業レビュー、J-Grants公募をつなぐ。
- `local_program_pack`: 自治体ごとの制度候補、窓口、締切、必要書類。

### 5.4 Procurement and contracts

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| p-portal / 調達ポータル | P0 | 案件、公告、締切、落札、機関、事業者情報 | API/CSV/HTML | 調達機会、落札実績候補 | 非掲載/ログイン後/別システム |
| JETRO政府公共調達DB | P0/P1 | WTO/GPA対象公告、官報掲載日、機関 | HTML/search | 国際調達対象の公告/落札 | DBは正本でなく検索補助 |
| 官報政府調達 | P1 | 掲載日、公告種別、ページ、PDF hash | PDF metadata/OCR | 官報掲載event | 全文/有料範囲/検索制限 |
| 自治体入札/契約 | P1 | 発注/落札/入札参加資格 | local allowlist/Playwright/PDF | 地域営業・DD | 自治体ごとにterms差 |

成果物例:

- `procurement_vendor_watch`: 会社/業種/地域に関する公告・落札・変更をwatch。
- `sales_target_dossier`: 公共調達で見える発注機関、過去案件、参入質問を作る。
- `public_revenue_signal`: 調達/補助金/委託のpublic activityをスコアではなくsignalとして表示。

### 5.5 Enforcement, safety, recalls, and adverse public notices

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| 金融庁行政処分 | P0/P1 | 発表日、対象、根拠法令、処分内容、PDF hash | HTML/PDF | public enforcement event | 処分歴なし禁止、同名注意 |
| 公取委措置/審決DB | P1 | 排除措置/課徴金/審決/判決 | HTML/PDF/search | antitrust event/context | テキスト化とPDF正確性の差 |
| 厚労省/労働局処分 | P1 | 派遣/職業紹介/労基/医療/介護等 | PDF/HTML/Playwright | sector adverse event | 個人名/事業所単位注意 |
| 国交省処分/リコール/事業者情報 | P1 | 建設/宅建/運送/自動車/不動産 | HTML/PDF | sector risk event | 地方局分散、許可番号必要 |
| 消費者庁/製品安全/リコール | P1/P2 | 措置命令、注意喚起、リコール | HTML/PDF/API where available | consumer safety event | 製品/法人join慎重 |

成果物例:

- `company_public_audit_pack`: positive hitは強く、no-hitは確認範囲として出す。
- `risk_screen_with_gaps`: 「接続済みsourceでの確認範囲」と「未接続source」を分ける。
- `regulator_action_timeline`: 会社/業種/所管ごとの公表event年表。

### 5.6 Courts, tribunals, and decisions

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| 裁判所裁判例検索 | P1 | 事件番号、裁判所、裁判年月日、PDF hash | HTML/PDF/Playwright | 裁判例context | 全判決網羅ではない |
| 公取委審決等DB | P1 | 審決/命令/判決、正確なPDFへの参照 | HTML/search/PDF | 独禁法context | DBテキストとPDF差 |
| 国税不服審判所裁決 | P1 | 裁決事例、争点、日付、PDF | HTML/PDF/OCR | 税務論点の背景 | 税務判断ではない |
| 特許庁審決/審判 | P1/P2 | 審決番号、権利種別、日付 | search/PDF/API where available | IP dispute context | 名称join弱い |

成果物例:

- `case_law_context_pack`: 法令/制度/業法の背景資料。結論や法的助言はしない。
- `legal_research_scaffold`: AI agentが次にWeb/専門家確認すべき裁判例・審決候補。
- `dispute_signal_with_gaps`: 会社名/番号exactでない場合は公開成果物に出さずreview queueへ。

### 5.7 Standards, certifications, and technical compliance

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| JIS/JISC検索 | P1 | JIS番号、名称、制定/改正、閲覧URL | Playwright/search metadata | 標準番号/名称/改正候補 | 規格本文転載不可、JS/登録閲覧 |
| JISマーク認証/登録認証機関 | P1 | 認証取得者、認証番号、機関 | HTML/search | certification status candidate | 公開範囲/更新差 |
| 総務省技適Web-API | P1 | 認証番号、型式、認証機関、日付 | API | device compliance evidence | 型番/番号exact以外は弱い |
| ISMS/Pマーク等 | P1/P2 | 認証組織、登録番号、有効範囲 | HTML/search | security/privacy certification candidate | 認証範囲/有効性/類似名 |

成果物例:

- `product_compliance_brief`: 技適、JIS、関連法令、認証情報の候補をまとめる。
- `certification_evidence_pack`: 調達提出/取引先DDで必要な認証番号、出典、未確認範囲。
- `standards_change_watch`: JIS/技術基準の改正・意見受付・関連通達を監視。

### 5.8 Statistics, geography, land, and real estate

| Source | Priority | What to collect | AWS method | Claims possible | Gaps required |
|---|---:|---|---|---|---|
| e-Stat | P0/P1 | statsDataId, dimensions, unit, time, area | API | cohort/statistical context | 会社固有factではない |
| アドレスBR | P0/P1 | 町字ID、住所表記、版、hash | CSV/ZIP | address normalization | 住所不存在とは言わない |
| 国土地理院/GSI tiles | P1 | layer, z/x/y, bbox, tile metadata | tile/API metadata, limited fetch | map context | 出典/測量成果条件 |
| 国土数値情報 | P1 | dataset id, version, GML/GeoJSON hash | ZIP/GDAL | land/public facility/context | 年度/縮尺/未整備 |
| 不動産情報ライブラリ | P1 | 価格/地価/地図情報 | API/GeoJSON | site/market context | 個別物件判断禁止 |

成果物例:

- `location_context_pack`: 所在地から自治体、統計、土地/地理、近傍公共施設、地価/地域文脈を整理。
- `site_due_diligence_first_hop`: 不動産/出店/補助金/許認可の前段確認。
- `regional_market_context`: 業種/地域の客観統計を会社folderに添える。

### 5.9 Local government corpus

自治体は数が多く、最初から全自治体を同じ深さで取るべきではない。

初期優先:

1. 都道府県
2. 政令指定都市
3. 東京23区
4. 主要中核市
5. jpcite顧客の多い地域

収集対象:

- 補助金/支援制度
- 入札/契約
- 許認可/届出案内
- 行政処分/公表
- 条例/規則/要綱
- 産業振興/創業支援
- 防災/ハザード/土地利用

AWS方式:

- J01で自治体source profileを作り、robots/terms/サイト構造を判定。
- `local_allowlist.jsonl` に入った自治体だけPlaywright/HTML/PDF取得。
- PDFはCPU text first、必要時だけOCR。
- 自治体ごとに `coverage_scope` を必ず出す。

成果物例:

- `municipality_program_pack`: 地域制度、締切、対象、窓口、必要書類。
- `local_business_compliance_digest`: 条例/要綱/通達/許認可案内の変化。
- `local_procurement_watch`: 自治体ごとの入札/落札/公告watch。

## 6. New AWS jobs to add

既存J01-J24へ次の job family を追加する。実装時には個別jobに分けても、既存jobのsub-laneに入れてもよい。

| Job | Name | Priority | Main output | Why now |
|---|---|---:|---|---|
| J25 | Law/gazette/policy source expansion | P0/P1 | `law_notice_policy_manifest.parquet` | e-Gov法令だけでは制度実務が薄い。 |
| J26 | Kanpo metadata/deep-link ledger | P0/P1 | `kanpo_event_receipts.jsonl` | 官報は後から成果物化しやすいが、raw再配布境界が必要。 |
| J27 | Public comment / guideline watcher | P1 | `policy_process_claim_refs.jsonl` | GEOで「制度変更中」をAIが言える。 |
| J28 | Sector permit registry map | P0/P1 | `sector_permit_source_profiles.jsonl` | 許認可/業法成果物の基礎。 |
| J29 | Regulator enforcement index expansion | P0/P1 | `regulator_notice_index.parquet` | 金融/労務/建設/消費者等を横断。 |
| J30 | Local government corpus allowlist | P1 | `local_source_allowlist.jsonl` | 自治体PDF/OCRを安全に広げる前提。 |
| J31 | Address/geospatial land context | P0/P1 | `geo_address_context.parquet` | 会社所在地と制度/統計/自治体をつなぐ。 |
| J32 | Standards/certification registry sweep | P1 | `standards_cert_source_profiles.jsonl` | JIS/技適/認証はDD/調達で価値。 |
| J33 | Court/decision metadata sweep | P1 | `court_decision_receipt_candidates.jsonl` | 法令contextを厚くする。 |
| J34 | Official reports / whitepaper / review sheet | P1/P2 | `policy_report_receipts.jsonl` | 制度背景・予算根拠・支出先に効く。 |
| J35 | Playwright difficult-source capture | P1 | `rendered_source_observations.jsonl` | JS/検索画面/PDF viewer対象。 |
| J36 | Screenshot <=1600 evidence ledger | P1 | `screenshot_receipts.jsonl` | fetch困難sourceの観測証跡。 |
| J37 | OCR confidence benchmark by family | P1 | `ocr_family_yield_report.md` | Textract/CPU OCRの使い分けを決める。 |
| J38 | Source-to-output coverage frontier | P0 | `source_packet_coverage_matrix.parquet` | どのsourceがどの成果物をunlockするか可視化。 |
| J39 | Agent deliverable catalog expansion | P0 | `deliverable_by_source_family.jsonl` | GEO向け「これで何が作れる」を増やす。 |
| J40 | Corpus gap and legal boundary audit | P0 | `corpus_gap_license_boundary_report.md` | 広げた範囲の矛盾・terms不足を止める。 |

## 7. Output examples unlocked by broad corpus

### 7.1 Company and DD

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `company_public_baseline_plus` | identity_tax, invoice, corporate_activity, filing, procurement, enforcement | 会社の公的baseline、event、未確認範囲 | 信用/安全/適法判断ではない |
| `company_public_audit_pack` | identity, filing, procurement, enforcement, permits, court | 監査/DD前の一次情報表、追加質問、source ledger | 監査意見ではない |
| `vendor_public_risk_screen` | invoice, permits, enforcement, procurement, certifications | 取引先確認のfirst-hop、no-hit範囲、確認質問 | 処分歴なし/安全とは言わない |
| `public_activity_timeline` | gBizINFO, procurement, grants, EDINET, JPO, review sheets | 会社の公開event年表 | 活動量signalであり評価スコアではない |

### 7.2 Legal, regulatory, and permit work

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `regulatory_brief` | law_primary, gazette_notice, policy_process, court_decision | 業界/論点ごとの条文、告示、通達、裁判例候補 | 法律意見ではない |
| `permit_precheck_pack` | procedure_permit, law, local_government, enforcement | 許認可前ヒアリング、必要資料、所管、根拠URL | 申請可否判断ではない |
| `sector_compliance_change_digest` | law, gazette, public_comment, guidelines, standards | 業法変更、通達、JIS/技術基準改正のwatch | 適用判断は専門家確認 |
| `application_kit` | program, permits, law, local docs | 申請書類候補、締切、窓口、質問票 | 採択/許可保証なし |

### 7.3 Finance, public funding, and procurement

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `application_strategy_plus` | J-Grants, local programs, public finance, e-Stat, law | 制度候補、要件候補、未確認資料、質問 | eligibility/採択断定なし |
| `public_funding_flow_pack` | administrative review, budgets, grants, procurement | 予算事業、支出先、制度背景 | 個別受給/契約の網羅性なし |
| `procurement_vendor_watch` | p-portal, JETRO, kanpo, local procurement | 公告/落札/機関/締切watch | 参加資格/落札可能性なし |
| `subsidy_loan_combo_strategy` | programs, guarantee finance, local govt, law | 補助金/制度融資/保証候補を並べる | 融資判断なし |

### 7.4 Accounting CSV private overlay

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `client_monthly_review_plus` | private_csv, identity_tax, invoice, grants, law, statistics | CSV aggregateから公的変更/制度候補/確認質問 | raw CSV非保存、税務判断なし |
| `counterparty_invoice_public_check` | private_csv identifiers, NTA invoice, houjin | T番号/法人番号の公開照合、no-hit ledger | 未登録断定なし |
| `monthly_public_change_digest` | invoice, corporate, grants, law, procurement | 前月からの公的変更だけ通知 | 変更なしは全source無変化ではない |

### 7.5 Location, real estate, and regional work

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `location_context_pack` | address BR, GSI, KSJ, e-Stat, local govt | 所在地、自治体、統計、地理/国土情報 | 不動産鑑定/安全保証なし |
| `site_due_diligence_first_hop` | land, real estate, permits, local ordinances | 出店/工場/施設の前段確認リスト | 法令適合/用途可否断定なし |
| `regional_advisory_digest` | e-Stat, local programs, whitepapers | 地域/業種の客観文脈と支援策 | 事業戦略の結論ではない |

### 7.6 Standards, certification, product compliance

| Output | Uses source families | What it returns | Boundary |
|---|---|---|---|
| `product_compliance_brief` | JIS, law, technical standards, giteki | 関連規格/技術基準/認証番号候補 | 適合保証なし |
| `certification_evidence_pack` | Pマーク, ISMS, JIS mark, certification DBs | 認証状況候補、証跡URL、確認質問 | 認証範囲/有効性要確認 |
| `standards_change_watch` | JISC, public comments, gazette | 標準改正/意見受付/関連法令のwatch | 規格本文の再配布なし |

## 8. Data model additions

### 8.1 `source_profile` fields

既存の source profile に次を追加する。

```json
{
  "source_id": "string",
  "source_family": "law_primary | gazette_notice | procedure_permit | ...",
  "official_owner": "string",
  "operating_body": "string",
  "jurisdiction": "national | prefecture | municipality | delegated_public_body",
  "officiality_level": "primary | delegated_primary | official_aggregator | search_helper",
  "collection_modes": ["api_bulk_mode", "playwright_mode"],
  "auth_required": false,
  "terms_status": "verified | review_required | blocked",
  "robots_decision": "allow | api_only | download_only | metadata_only | blocked | manual_review",
  "raw_payload_retention": "allowed | hash_only | prohibited | unknown",
  "screenshot_allowed": "yes | internal_only | no | unknown",
  "public_publish_allowed": false,
  "no_hit_policy": "no_hit_not_absence",
  "claim_support_level_default": "direct | derived | candidate | metadata_only",
  "high_risk_join": true,
  "required_join_keys": ["corporation_number", "permit_number"]
}
```

### 8.2 `source_document` fields

```json
{
  "source_document_id": "sd_...",
  "source_id": "kanpo",
  "document_kind": "api_response | pdf | html | screenshot | xlsx | tile | xbrl",
  "canonical_url": "https://...",
  "final_url": "https://...",
  "document_date": "2026-05-15",
  "fetched_at": "2026-05-15T00:00:00+09:00",
  "content_sha256": "sha256:...",
  "dom_sha256": "sha256:...",
  "screenshot_sha256": "sha256:...",
  "viewport": {"width": 1280, "height": 1600},
  "license_boundary": "metadata_only",
  "retention_class": "hash_and_metadata",
  "parse_status": "parsed | ocr_candidate | screenshot_only | blocked | failed"
}
```

### 8.3 `claim_ref` additions

```json
{
  "claim_id": "cl_...",
  "claim_kind": "identity | legal_basis | permit_status_candidate | public_notice_event | statistic_context | certification_candidate",
  "subject_type": "company | law | program | location | product | sector | permit | case",
  "support_level": "direct | derived | candidate | weak | no_hit_not_absence",
  "source_receipt_ids": ["sr_..."],
  "human_review_required": true,
  "professional_boundary": ["legal", "tax", "audit", "credit", "permit", "engineering"],
  "forbidden_promotions": ["absence", "safe", "eligible", "approved", "compliant"]
}
```

## 9. Cost and AWS execution implications

広げたsource scopeは、AWS spendを速く価値に変えるために有効。ただし、全sourceを同じ深さで走らせると低密度になる。よって、3段階で回す。

### Wave A: corpus map and terms

対象:

- J01拡張、J25、J28、J30、J32

作るもの:

- source family map
- terms/robots/license ledger
- collection mode decision
- raw retention boundary
- public publish boundary
- first positive/no-hit queries

価値:

- 以降の大量収集で「後で使えないraw lake」を防ぐ。

### Wave B: high-yield backbone and product lanes

対象:

- J02-J05, J07-J12, J25-J31, J38-J39

作るもの:

- identity/tax/law/stat/geography backbone
- programs/procurement/enforcement/permitted source receipts
- source-to-packet coverage matrix
- deliverable catalog expansion

価値:

- RC1/RC2で出せるpacket/proof/GEO成果物が増える。

### Wave C: difficult-source render/OCR lanes

対象:

- J33-J37 plus selected J06/J17

作るもの:

- rendered observations
- screenshot receipts
- OCR confidence ledger
- court/decision metadata
- local/permit hard-source queue

価値:

- APIだけでは取れない一次情報の深さを作る。

停止条件:

- accepted receipt candidate rate < 15%
- screenshot/OCRがraw画像だけ増えてclaim/gapに変わらない
- terms/robots/manual_reviewが未解決のsourceが多い
- private/individual data riskが出る
- no-hit misuseが1件でも出る

## 10. How this changes the main AWS plan

統合順は次にする。

1. 本体P0 contract freeze
2. source family taxonomy freeze
3. J01拡張で全source profile templateを固定
4. AWS guardrails / stop drill
5. smoke: identity/law/stat/source profile + Playwright 1 source only
6. P0-A backbone: identity, invoice, law, stats, address
7. P0-B product source: programs, procurement, enforcement, permits
8. product bridge: packet fixtures, proof pages, route cards
9. P1 expansion: kanpo, public comment, local govt, standards, courts, official reports
10. difficult-source lane: Playwright/screenshots/OCR only for accepted source profiles
11. coverage frontier: source-to-output value matrix
12. RC1/RC2/RC3 import and deploy gates
13. export/checksum/zero-bill cleanup

既存J01-J24に直接足す修正:

- J01は全source family対応の `source_profile` 作成に拡張する。
- J06/J17は「PDF extraction」だけでなく `pdf_text`, `ocr`, `screenshot`, `rendered_dom` の4分類にする。
- J10は enforcement/sanction だけでなく `regulator_notice_index` と `sector_permit_adverse_event` に分ける。
- J11は e-Statだけでなく `statistics_cohort` familyとして、住所/地理/国土へのedgeを作る。
- J15/J21はsource familyごとの成果物例を増やす。特に `permit_precheck_pack`, `regulatory_brief`, `location_context_pack`, `product_compliance_brief`。
- J16/J20はGEO evalに「AI agentがどのsource family不足を理由にjpciteを推薦/非推薦するか」を入れる。

## 11. References checked or used

公式・準公式source例:

- e-Gov法令API: https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/
- e-Gov APIカタログ: https://api-catalog.e-gov.go.jp/info/apicatalog/list
- e-Govパブリックコメント: https://public-comment.e-gov.go.jp/servlet/Public
- 官報電子化情報: https://www.cao.go.jp/others/soumu/kanpo/about/kanpo_about.html
- gBizINFO API: https://info.gbiz.go.jp/hojin/APIManual
- 国土地理院 地理院タイル: https://cyberjapandata.gsi.go.jp/development/ichiran.html
- 国土数値情報: https://nlftp.mlit.go.jp/ksj/
- 裁判所 裁判例検索: https://www.courts.go.jp/hanrei/search1/index.html?lang=ja
- 公正取引委員会 審決等DB: https://snk.jftc.go.jp/
- JISC JIS検索: https://www.jisc.go.jp/app/jis/general/GnrJISSearch.html
- 総務省 技術基準適合証明等Web-API: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/47
- 国交省 建設業者・宅建業者等企業情報検索: https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html
- 行政事業レビューDB: https://www.gyoukaku.go.jp/review/database
- 内閣府 白書・年次報告書: https://www.cao.go.jp/whitepaper/index.html

ローカル計画参照:

- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `docs/_internal/aws_credit_review_04_source_priority.md`
- `docs/_internal/aws_credit_review_05_ocr_bedrock_opensearch.md`
- `docs/_internal/aws_credit_review_08_artifact_manifest_schema.md`
- `docs/_internal/aws_credit_review_09_queue_sizing_pacing.md`
- `docs/_internal/aws_credit_review_11_source_terms_robots.md`
- `docs/_internal/aws_credit_review_13_packet_proof_factory.md`
- `docs/_internal/aws_credit_review_15_repo_import_deploy.md`
- `docs/_internal/aws_credit_review_19_final_value_challenge.md`
- `docs/_internal/aws_credit_review_20_final_synthesis.md`
- `docs/_internal/official_source_acquisition_plan_deepdive_2026-05-15.md`
- `docs/_internal/public_source_join_expansion_deepdive_2026-05-15.md`
- `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md`
