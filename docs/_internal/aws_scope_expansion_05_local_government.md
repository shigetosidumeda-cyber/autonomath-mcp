# AWS scope expansion 05/30: local government, local systems, grants, permits, procurement, ordinances, and notices

作成日: 2026-05-15  
担当: 拡張深掘り 5/30 自治体・地方制度・地域補助金/許認可  
対象: 都道府県、市区町村、特別区、政令指定都市、中核市等の公式サイト、自治体オープンデータ、例規集、補助金、入札、許認可、届出、行政処分、公表資料。  
状態: 計画のみ。AWS CLI/APIコマンド、AWSリソース作成、デプロイ、既存コード変更は行っていない。  
出力先: `docs/_internal/aws_scope_expansion_05_local_government.md`

## 0. 結論

既存のAWS統合計画にある `J06 Ministry/local PDF extraction` と `J17 Local government PDF OCR expansion` だけでは、日本の公的一次情報を広く押さえる構想としては不足している。自治体領域は「PDFを少しOCRする」ではなく、独立した `LGX Local Government Artifact Factory` として本体計画へ昇格させるべきである。

理由は明確である。

- 補助金、給付金、許認可、届出、入札、条例、行政処分は、国の制度よりも自治体差分が大きい。
- エンドユーザーは「自分の地域・業種・状況で何ができるか」を聞くため、地域制度を持たないとAIエージェントが推薦しづらい。
- 自治体サイトはAPI/CSV/HTML/PDF/Word/Excel/JS画面/例規集が混在し、人力では広く継続収集しづらい。
- AWSクレジットを短期に使う価値が出るのは、まさにPlaywright、PDF/OCR、DOM抽出、重複排除、差分検知、receipt生成を大量に回す部分である。
- 取得しておけば、成果物の企画は後から増やせる。自治体一次情報は「後から組み合わせられる原材料」として価値が高い。

したがって本担当の推奨は次の通り。

1. `J06/J17` を単なるstretchではなく、`LG01-LG20` の自治体サブ計画として分解する。
2. まず全国自治体の公式URL、地方公共団体コード、自治体種別、公式オープンデータ導線、robots/termsを `local_government_profile` として作る。
3. 公式API/一括ダウンロード/自治体標準オープンデータセットを優先し、足りない高価値ページだけPlaywright/DOM/PDF/OCRで取りに行く。
4. Playwright screenshotはAWSで実行できる。幅は1600px以下に固定し、DOM/PDF抽出が難しいページの証跡、レイアウト復元、OCR補助に使う。
5. no-hitは自治体領域でも必ず `no_hit_not_absence` とする。「該当制度なし」「許可不要」「処分歴なし」「安全」は言わない。
6. 公開API/MCPで売るのはraw mirrorではなく、`source_receipts[]`、`claim_refs[]`、`known_gaps[]`、抽出fact、期限、必要書類、根拠URL、取得時点、未確認範囲である。
7. クレジット消化後は、artifactをエクスポートし、AWS側のS3/Batch/ECR/Logs/Textract/OpenSearch等を削除できる形にする。

この領域は、jpciteのGEO-first戦略と相性が非常に良い。AIエージェントが「この地域・業種・手続きなら、jpciteのMCP/APIで一次情報receipt付きに確認できる」と推薦する理由を作れる。

## 1. 本体計画との位置づけ

### 1.1 既存計画での扱い

現行のAWS統合計画では、自治体は主に次の場所に入っている。

| 既存job | 現在の意味 | 問題 |
|---|---|---|
| `J05 J-Grants/public program acquisition` | 国・一部自治体の補助金候補 | 地域独自制度や自治体サイト掲載制度が漏れる |
| `J06 Ministry/local PDF extraction` | 省庁/自治体PDF抽出 | 範囲が広すぎ、自治体固有の収集設計が薄い |
| `J09 Procurement/tender acquisition` | 調達・入札 | 国系p-portal寄りで自治体調達サイトの多様性に弱い |
| `J10 Enforcement/sanction/public notice sweep` | 行政処分/公表情報 | 所管別・自治体別の公表期間や表記差分が未分解 |
| `J17 Local government PDF OCR expansion` | 良ければ自治体PDF OCR | stretch扱いだと、価値の中心なのに後回しになる |

### 1.2 本担当の修正提案

`J06/J17` を以下のように再定義する。

```text
J06  -> LGX-A: 自治体source profile / official URL / robots / terms / open data catalog
J17  -> LGX-B: 自治体Playwright/PDF/OCR/例規集/補助金/許認可/入札/行政処分の広域収集
J15  -> LGX-C: 自治体成果物packet/proof fixture
J16  -> LGX-D: GEO/no-hit/forbidden-claim評価
J24  -> LGX-E: export/checksum/zero-bill cleanup
```

本体P0計画への接続は次の通り。

| P0 epic | 自治体LGXが渡すもの |
|---|---|
| P0-E1 Packet contract/catalog | 地域制度、許認可、入札、条例、行政処分のpacket type候補 |
| P0-E2 Source receipts/claims/gaps | 自治体ごとのsource_receipt、claim_refs、known_gaps、no-hit ledgers |
| P0-E3 Pricing/cost preview | 地域制度packet、自治体横断調査packetの課金単位 |
| P0-E4 CSV privacy/intake | CSVの所在地/業種/支出傾向から、地域制度候補へ安全に接続する候補 |
| P0-E5 Packet composers | `local_program_opportunity` などのfixture inputs/outputs |
| P0-E6 REST facade | `/packets/local-*` 系のexample payload |
| P0-E7 MCP tools | AIエージェント向け `find_local_programs`, `build_permit_checklist` 等 |
| P0-E8 Proof/discovery | 地域別 proof page、source ledger、llms/.well-known examples |
| P0-E9 Release gates | no-hit誤用、法的助言誤認、個人情報、古い募集要領のgate |

## 2. 収集対象の全体像

自治体領域は、収集対象を次の7群に分ける。

| Group | 対象 | 価値 | 主な取得方法 | risk |
|---|---|---|---|---|
| LG-G1 | 自治体ID・公式URL・管轄・コード | 全joinの背骨 | e-Gov地方公共団体ページ、地方公共団体コード、公式リンク | 低 |
| LG-G2 | 自治体オープンデータ | 構造化データ、標準ODS | 公式カタログ、CKAN、CSV/Excel/JSON | 低〜中 |
| LG-G3 | 補助金・給付金・支援制度 | 直接課金しやすい | J-Grants + 自治体ページ/PDF/Excel | 中 |
| LG-G4 | 許認可・届出・手数料・必要書類 | 事業開始/運営に直結 | 自治体ページ、所管課PDF、申請様式 | 中 |
| LG-G5 | 入札・調達・落札・公募 | B2G/営業/調達に直結 | 自治体入札サイト、公告PDF、結果CSV/PDF | 中 |
| LG-G6 | 条例・規則・要綱・例規集 | 法制度の地域差分 | 公式例規集、自治体ページ、HTML/PDF | 中〜高 |
| LG-G7 | 行政処分・公表・監督・違反・回収 | DD/risk screenに直結 | 省庁/都道府県/保健所/所管課公表 | 高 |

重要なのは、すべての情報を同じ粒度で取ろうとしないことである。`source_receipt` として堅いもの、`candidate_fact` に留めるもの、`metadata_only` に落とすものを分ける。

## 3. 公式起点と優先source

### 3.1 自治体公式URL・自治体コード

最初に作るべき背骨は `local_government_profile` である。

主な起点:

- e-Govポータル「地方公共団体」: 都道府県、政令指定都市、東京都区部等の公式Webサイト導線。
- 全国地方公共団体コード: 都道府県コード、市区町村コード、改正履歴、廃置分合の処理。
- 統計局/地域コード関連: e-Stat、地域統計、メッシュ、自治体境界との接続。
- 各自治体の公式サイト、公式オープンデータサイト、公式SNS/RSSがある場合は補助的に保持。

出力:

```json
{
  "schema_id": "jpcite.local_government.profile",
  "schema_version": "2026-05-15",
  "local_government_id": "lg_131016",
  "local_government_code": "131016",
  "name": "千代田区",
  "prefecture_code": "13",
  "government_type": "special_ward",
  "official_home_url": "https://example.local-government/",
  "official_url_source_receipt_id": "sr_...",
  "open_data_catalog_urls": [],
  "ordinance_repository_urls": [],
  "procurement_urls": [],
  "permit_urls": [],
  "sanction_notice_urls": [],
  "profile_confidence": "source_backed",
  "known_gaps": [
    {
      "gap_type": "not_all_department_urls_discovered",
      "support_level": "known_gap"
    }
  ]
}
```

このprofileがない自治体は、後続の補助金・条例・入札・許認可のclaimに使わない。

### 3.2 自治体標準オープンデータセット

デジタル庁の自治体標準オープンデータセットは、自治体領域の最初の構造化収集に向いている。定義されている項目には、食品等営業許可・届出、調達情報、支援制度（給付金）情報、公共施設、子育て施設、医療機関、介護サービス事業所、地域・年齢別人口などがある。

優先度:

| ODS item | jpcite価値 | 使い方 |
|---|---|---|
| 食品等営業許可・届出一覧 | 飲食店/食品事業者の許認可確認 | `permit_public_record`、ただし個人情報抑制 |
| 調達情報 | 自治体入札・案件候補 | `local_procurement_notice` |
| 支援制度（給付金）情報 | 地域補助金/給付金の候補 | `local_program_round` |
| 地域・年齢別人口 | 地域市場背景 | `regional_stat_claim` |
| 子育て施設/介護/医療 | 事業計画・地域需要 | `regional_facility_claim` |
| 公共施設/避難場所/観光 | 地域context | P1以降 |

注意:

- ODSに準拠している自治体だけを「網羅」と見なさない。
- ODSデータでも更新日、自治体名、ファイルURL、content_hash、項目定義版をreceiptに残す。
- データ項目が標準定義に合わない場合は `ods_mapping_confidence` を下げる。

### 3.3 補助金・給付金・支援制度

自治体独自の補助金は、ユーザー価値が最も高い領域の一つである。

取得対象:

- 事業者向け補助金
- 創業支援
- 設備投資
- 省エネ/脱炭素/再エネ
- IT/DX
- 商店街/観光/地域活性
- 雇用/人材育成
- 子育て/介護/福祉事業者向け支援
- 災害復旧/感染症/物価高騰対策
- 農林水産/食品加工/6次産業化
- 空き店舗/移住/定住

抽出するfact:

| fact | 必須receipt | 注意 |
|---|---|---|
| 制度名 | 公式URL/PDF | 古い年度との混同を防ぐ |
| 募集期間 | ページ/PDF該当箇所 | 延長/早期終了/予算到達に注意 |
| 補助上限/補助率 | 公募要領 | 税抜/税込、千円未満切捨等を保持 |
| 対象者 | 要領/FAQ | 法人/個人/市内事業者/本店所在地 |
| 対象経費 | 要領 | 対象外経費も別claim |
| 必要書類 | 要領/申請ページ | 様式PDF/Word/Excelはmetadata |
| 申請方法 | 公式ページ | 電子/郵送/窓口 |
| 問い合わせ先 | 公式ページ | 公開課名・電話・フォーム |
| 予算枠/採択数 | 公表資料 | 採択確率とは言わない |

禁止表現:

- 「この補助金を使えます」
- 「採択されます」
- 「対象外です」
- 「他に補助金はありません」

安全表現:

- 「取得時点の接続済み自治体sourceでは、この条件に近い制度候補を確認しました」
- 「申請可否は公募要領、予算残、自治体窓口確認が必要です」
- 「このpacketは制度候補と根拠箇所の整理であり、採択可能性を保証しません」

### 3.4 許認可・届出・手数料・必要書類

許認可はAIエージェント推薦に強い。ユーザーは「何を出せばいいか」「どの窓口か」「費用と期限は何か」を聞く。

優先業種:

- 飲食店/食品製造/食品販売
- 美容所/理容所/クリーニング
- 旅館/民泊/住宅宿泊
- 古物商、酒類、風俗営業等は都道府県警察・国税等も絡むためP1で慎重に扱う
- 建設業、産廃、解体、屋外広告物、道路占用、都市計画/建築確認
- 保育、介護、障害福祉、医療、薬局
- イベント、露店、火気、消防、騒音、道路使用

自治体ごとに取る情報:

```json
{
  "schema_id": "jpcite.local_government.permit_requirement",
  "permit_id": "permit_food_restaurant_131016",
  "jurisdiction": {
    "local_government_code": "131016",
    "department": "保健所等",
    "scope_note": "管轄は施設所在地により異なる"
  },
  "business_activity": "飲食店営業",
  "legal_basis_refs": [
    {
      "source_family": "egov_law",
      "law_name": "食品衛生法",
      "article": "source-backed when available"
    }
  ],
  "local_basis_refs": [
    {
      "source_family": "local_ordinance",
      "title": "条例/規則/要綱候補",
      "receipt_id": "sr_..."
    }
  ],
  "required_documents": [],
  "fee_claims": [],
  "deadline_claims": [],
  "application_channel": "online_or_counter_or_mail_candidate",
  "human_review_required": true,
  "support_level": "candidate_fact"
}
```

注意:

- 国法、政省令、条例、規則、要綱、窓口運用を分ける。
- 「許可不要」と断定しない。`permit_may_be_required` / `consult_jurisdiction` を基本にする。
- 申請様式ファイルは、再配布せずmetadata、URL、hash、ファイル名、更新日を保持する。
- 個人事業者や営業施設情報は `public_sensitive` とし、公開packetでは抑制する。

### 3.5 入札・調達・落札

自治体入札はフォーマット差分が大きいが、B2G営業・調達機会・競合調査で価値が高い。

対象:

- 一般競争入札
- 指名競争入札
- 公募型プロポーザル
- 企画提案
- 見積合わせ
- 物品/役務/工事/委託
- 入札結果、落札者、落札金額、予定価格、参加資格
- 仕様書、質問回答、公告訂正

成果物:

- `local_procurement_notice`
- `local_procurement_award`
- `local_procurement_deadline_calendar`
- `local_procurement_document_manifest`
- `local_procurement_gap_report`

抽出するfact:

| fact | 用途 |
|---|---|
| 公告日 | 期限計算、freshness |
| 件名 | 検索、分類 |
| 発注機関/部署 | 管轄 |
| 種別 | 物品/役務/工事/委託 |
| 参加資格 | 申請戦略 |
| 提出期限/開札日 | calendar |
| 仕様書URL/hash | proof |
| 質問締切/回答日 | action item |
| 落札者/金額 | 市場分析、ただし公表範囲に限定 |

禁止:

- 「この入札に参加できます」
- 「落札できます」
- 「競合は存在しません」

安全:

- 「接続済み自治体sourceの公開公告では、該当しそうな案件候補を確認しました」
- 「参加資格、地域要件、業種登録、提出書類は公式公告で確認が必要です」

### 3.6 条例・規則・要綱・例規集

条例は地域差分の根拠になるが、収集難度と権利境界が高い。多くの自治体は例規集システムを使い、HTML構造やURLが自治体ごとに異なる。

初期方針:

- 公式自治体ページまたは自治体からリンクされた例規集だけを対象にする。
- 例規集ベンダーの規約・robotsを必ず確認する。
- raw全文ミラーを公開しない。
- 条例名、番号、公布/施行/改正日、条番号、短い該当箇所、URL、hash、取得日時をreceipt化する。
- 条文解釈はしない。根拠候補と参照箇所を示す。

優先条例/例規テーマ:

- 中小企業振興
- 産業振興
- 企業立地
- 空き店舗/商店街
- 創業支援
- 補助金交付要綱
- 手数料条例
- 食品衛生法施行条例/規則
- 旅館業法施行条例
- 建築/都市計画/景観/屋外広告物
- 環境/廃棄物/騒音/悪臭
- 入札参加資格/契約規則

条例sourceのsupport level:

| support_level | 使い方 |
|---|---|
| `source_backed` | 公式URL、条番号、施行日、hashが揃い、人手または自動gateを通過 |
| `candidate_fact` | 条例名/条番号候補はあるが、版/施行日/構造が不確か |
| `metadata_only` | タイトル、URL、更新日、hashだけ |
| `link_only` | 規約上または技術上、本文抽出しない |
| `blocked` | robots/規約/アクセス制限で使わない |

### 3.7 行政処分・公表・監督・違反・回収

最も慎重に扱う。DDやrisk screen価値は高いが、同名誤爆、公表期間、個人名、処分取消、更新漏れがある。

対象:

- 建設業者等の行政処分
- 産廃処理業者の処分
- 食品衛生法違反/回収情報
- 旅館/美容/理容/クリーニング等の処分
- 障害福祉/介護/保育/医療の指定取消等
- 入札参加停止
- 消費生活関連の公表
- 自治体の監査/住民監査/不当利得等の公表

設計:

- 会社同定は法人番号、正式名称、所在地、代表者、許可番号、管轄を分けてconfidenceを出す。
- 名称一致だけで「この会社の処分」と断定しない。
- no-hitは「接続済みsource/期間/同定条件で未検出」だけ。
- 公表期間が限定されるsourceは `publication_window_known=true` とする。
- 公表が古い/消えている場合は `source_stale_or_removed` known_gapへ移す。

出力:

```json
{
  "schema_id": "jpcite.local_government.public_notice",
  "notice_kind": "administrative_sanction_candidate",
  "source_receipt_id": "sr_...",
  "publisher": "自治体または所管庁",
  "document_date": "YYYY-MM-DD",
  "publication_window": {
    "known": true,
    "note": "source profileに従う"
  },
  "subject_candidates": [
    {
      "name": "公表名",
      "corporation_number": null,
      "identity_confidence": "name_only_low"
    }
  ],
  "claim_refs": [],
  "human_review_required": true,
  "no_adverse_inference_allowed": true
}
```

## 4. Playwright screenshot / DOM / PDF / OCR 設計

### 4.1 AWSで実行できるか

できる。推奨はPlaywright/Chromium入りのコンテナをECRに置き、AWS BatchまたはECS/Fargate Spot/EC2 Spotで実行する方式である。

ただし方針は「アクセス制限を突破する」ではない。公開されている公式ページのうち、通常のHTTP fetchでは本文が取りにくいJSレンダリング、検索結果、PDF viewer、表組み、フォーム型検索を、公開範囲・robots・規約の範囲でブラウザ取得する。

禁止:

- ログイン突破
- CAPTCHA回避
- robots/規約回避
- IPローテーションでの制限回避
- 検索フォームの無制限総当たり
- 個人情報を大量に収集してランキング化

許容:

- 公式ページの通常閲覧
- 低頻度の検索条件実行
- DOM snapshot取得
- 1600px以下のスクリーンショット
- PDF/Excel/Wordリンクのmetadata/hash取得
- 公開PDFの抽出/OCR
- 429/403/5xxで自動停止

### 4.2 screenshot仕様

ユーザー要望に合わせ、スクリーンショット幅は必ず1600px以下に固定する。

推奨viewport:

| mode | width | height | 用途 |
|---|---:|---:|---|
| `desktop_standard` | 1366 | 768 | 通常ページ証跡 |
| `desktop_wide_safe` | 1440 | 900 | 表/入札ページ |
| `narrow_document` | 1280 | 1600 | 縦長PDF viewer/条例ページ |
| `mobile_check` | 390 | 844 | 重要ページのモバイル崩れ確認 |

保存ルール:

- `screenshot_width_px <= 1600` をmanifest gateにする。
- full-page screenshotが縦長になる場合は、横幅1600以下のままtile分割し、tileごとにhashを持つ。
- screenshotは根拠の補助であり、claimの主根拠はDOM/PDF text、公式URL、content_hash、取得日時とする。
- screenshotに個人名・電話番号・住所等が含まれる可能性があるため、公開packetでは原則サムネイルも出さない。
- proof pageで出す場合は、該当箇所の短い引用とsource linkに留める。

`screenshot_receipt`:

```json
{
  "schema_id": "jpcite.local_government.screenshot_receipt",
  "source_document_id": "sd_...",
  "source_url": "https://example.lg.jp/...",
  "captured_at": "2026-05-15T00:00:00+09:00",
  "viewport": {
    "width_px": 1440,
    "height_px": 900,
    "device_scale_factor": 1
  },
  "full_page": false,
  "tile_index": null,
  "image_sha256": "sha256:...",
  "dom_sha256": "sha256:...",
  "text_sha256": "sha256:...",
  "robots_decision": "allow",
  "terms_status": "verified_or_review_required",
  "public_publish_allowed": false,
  "used_for_claim_support": false
}
```

### 4.3 DOM snapshot

Playwrightでは、スクリーンショットだけでなくDOMとアクセシビリティツリーを保存する。

保存対象:

- normalized HTML
- visible text
- link graph
- table extraction candidate
- form labels/search controls
- PDF/Excel/Word links
- breadcrumb
- title/h1/h2
- meta updated date
- structured data if present

DOMは raw HTML 公開ではなく、抽出とreceiptのための一時artifactとする。公開・repo import時は構造化factへ変換する。

### 4.4 PDF / Office extraction

自治体はPDF、Word、Excelが多い。AWSでは次の順に処理する。

1. HTTP HEAD/GETでmetadata、content-type、size、ETag、Last-Modifiedを取得。
2. hash、URL、ファイル名、リンク元ページを `source_document_manifest` に保存。
3. PDF text layerがある場合は `pdftotext` / `pdfplumber` 系で抽出。
4. scanned PDFや画像PDFは、費用対効果があるものだけTextractまたはTesseractでOCR。
5. Excel/WordはLibreOffice headless等でtext/table抽出し、元ファイル再配布はしない。
6. layout confidence、OCR confidence、table confidenceを出し、閾値未満は `candidate_fact` に落とす。

OCR優先順位:

| priority | 文書 |
|---|---|
| A | 募集中の補助金要領、入札公告、許認可手続き、手数料表 |
| B | 条例/規則/要綱、行政処分一覧、入札結果 |
| C | 過年度実績、説明会資料、参考資料 |
| D | チラシ、ポスター、画像のみ、第三者資料 |

OCRを広げるほどAWSクレジットは使えるが、accepted artifact率が低い文書は止める。費用を使うことが目的ではなく、将来のGEO/MCP課金に使えるreceiptを増やすことが目的である。

## 5. LGX job plan

### 5.1 全体順

本体計画とマージした実行順は次に固定する。

```text
P0 contract freeze
  -> LG01 municipality universe
  -> LG02 source profile / robots / terms
  -> LG03 open data/API/bulk first
  -> LG04 high-value URL discovery
  -> LG05 Playwright smoke
  -> LG06 PDF/OCR smoke
  -> LG07 accepted-yield review
  -> LG08-LG14 broad run
  -> LG15 normalization / claim graph
  -> LG16 no-hit / forbidden claim / privacy gates
  -> LG17 packet/proof fixture materialization
  -> LG18 GEO eval
  -> LG19 repo import candidates
  -> LG20 export / checksum / zero-bill cleanup
```

### 5.2 Job details

| Job | Name | 内容 | 主成果物 | go/no-go |
|---|---|---|---|---|
| LG01 | Municipality universe | 自治体コード、公式URL、種別、都道府県、管轄階層 | `local_government_profile.jsonl` | code/URL confidence |
| LG02 | Source profile/robots/terms | 各公式ドメイン、例規集、入札サイト、ODサイトのrobots/規約 | `local_source_profile.jsonl` | blockedは収集しない |
| LG03 | Open data catalog harvest | ODS、CKAN、自治体カタログ、data.go.jp系探索 | `local_open_data_catalog.jsonl` | license_boundary |
| LG04 | High-value URL discovery | 補助金、許認可、入札、条例、行政処分URL候補発見 | `local_url_candidates.jsonl` | spam/old/duplicate除外 |
| LG05 | Playwright smoke | 20-50自治体でDOM/screenshot実験 | `playwright_smoke_report.md` | 429/403/terms問題 |
| LG06 | PDF/OCR smoke | 100-300文書でtext/OCR精度確認 | `ocr_yield_report.md` | accepted fact率 |
| LG07 | Prioritization rerank | accepted yield、source value、costで順位再計算 | `local_collection_priority.md` | 低yieldを停止 |
| LG08 | Grant/support crawl | 補助金/給付金/支援制度の広域収集 | `local_program_rounds.jsonl` | 募集年度/期限gate |
| LG09 | Permit/procedure crawl | 許認可/届出/手数料/必要書類 | `local_permit_requirements.jsonl` | 法的助言禁止gate |
| LG10 | Procurement crawl | 入札/公募/落札/仕様書metadata | `local_procurement_notices.jsonl` | 参加可否断定禁止 |
| LG11 | Ordinance/reiki crawl | 条例/規則/要綱のmetadata/条番号候補 | `local_ordinance_refs.jsonl` | raw全文公開禁止 |
| LG12 | Public notice/sanction crawl | 行政処分/公表/監督/違反/回収 | `local_public_notices.jsonl` | identity confidence gate |
| LG13 | Form/document manifest | 申請様式、要領、FAQ、添付資料manifest | `local_form_document_manifest.jsonl` | 再配布境界 |
| LG14 | Screenshot/OCR expansion | 高価値・難取得ページにPlaywright/OCRを拡大 | `screenshot_receipts.jsonl` | width <=1600 |
| LG15 | Normalize/join/claim graph | 地域、業種、期限、金額、法令、自治体コードjoin | `local_claim_refs.jsonl` | claim has receipt |
| LG16 | QA/no-hit/privacy | no-hit、個人情報、古い制度、誤表現scan | `local_quality_gate_report.md` | blocker 0 |
| LG17 | Packet fixture factory | 成果物例JSONを生成 | `local_packet_examples_manifest.jsonl` | public-safe only |
| LG18 | GEO eval | AIエージェント想定queryの評価 | `local_geo_eval_report.md` | agent can cite route |
| LG19 | Repo import plan | 本体repoに入れる候補と除外理由 | `local_repo_import_plan.jsonl` | manifest complete |
| LG20 | Export/cleanup | checksum、export、AWS削除準備 | `local_cleanup_ledger.jsonl` | zero-bill posture |

## 6. 収集範囲と優先順位

### 6.1 Coverage tiers

全自治体をいきなり深くクロールしない。階層化する。

| Tier | 対象 | やること | 目的 |
|---|---|---|---|
| T0 | 全自治体 | code、公式URL、robots、主要リンク、open data導線 | 全国profile |
| T1 | 47都道府県、政令指定都市、特別区、中核的都市 | 補助金/許認可/入札/条例/処分を深く | 高価値coverage |
| T2 | 人口・事業所数・産業集積が大きい市区町村 | T1に準じる | 事業者需要coverage |
| T3 | ODS/CKAN/公開APIがある自治体 | 構造化データ優先 | 低コスト高品質 |
| T4 | ロングテール自治体 | shallow discovery + high-value keywords | known_gaps込み |

`T0` は全国で必須。`T1/T2/T3` はAWSクレジットで重点実行。`T4` は「見つからない」ことを価値に変えるのではなく、`known_gaps` を明示する。

### 6.2 Keyword discovery

高価値URL候補は、自治体公式サイト内で次の語を使って発見する。

補助金:

- 補助金
- 助成金
- 給付金
- 支援金
- 奨励金
- 利子補給
- 創業
- 起業
- 設備投資
- 省エネ
- DX
- 商店街
- 空き店舗
- 雇用
- 人材育成

許認可:

- 許可
- 届出
- 申請
- 手数料
- 必要書類
- 様式
- 保健所
- 営業許可
- 道路占用
- 屋外広告物
- 産業廃棄物
- 旅館業
- 美容所
- 理容所

入札:

- 入札
- 調達
- 公告
- 公募
- プロポーザル
- 契約
- 落札
- 仕様書
- 質問回答
- 入札参加資格

条例/例規:

- 例規集
- 条例
- 規則
- 要綱
- 告示
- 手数料条例
- 補助金交付要綱

行政処分:

- 行政処分
- 監督処分
- 指定取消
- 入札参加停止
- 違反
- 公表
- 回収
- 改善命令
- 業務停止

### 6.3 Domain politeness

標準設定:

- 1自治体ドメインあたり低並列から開始。
- 429/403/5xx増加時はドメイン単位で停止。
- 夜間集中で相手に負荷をかけない。自治体ごとのbusiness hoursも避ける方針を持つ。
- PDF/Officeはサイズ上限を設ける。
- 同一URL/content_hashは再取得しない。
- RSS/sitemap/サイト内検索APIがあれば優先。
- 検索結果ページのページネーションは深さ上限を設ける。
- User-Agentにjpcite識別子と連絡先を含める。

## 7. データモデル

### 7.1 Local source profile

```json
{
  "schema_id": "jpcite.local_government.source_profile",
  "schema_version": "2026-05-15",
  "source_id": "lg_131016_main_site",
  "local_government_code": "131016",
  "source_family": "local_government_official_site",
  "base_url": "https://example.lg.jp/",
  "publisher": "自治体名",
  "robots": {
    "robots_url": "https://example.lg.jp/robots.txt",
    "fetched_at": "2026-05-15T00:00:00+09:00",
    "decision": "allow_or_manual_review_or_blocked",
    "content_sha256": "sha256:..."
  },
  "terms": {
    "terms_url": "https://example.lg.jp/...",
    "terms_status": "verified_or_review_required",
    "license_boundary": "full_fact_or_metadata_only_or_link_only"
  },
  "allowed_fetch_modes": ["api", "download", "html", "playwright", "pdf"],
  "blocked_paths": [],
  "rate_limit_policy": {
    "max_concurrency_per_domain": 1,
    "min_delay_ms": 3000,
    "stop_on_status": [403, 429]
  },
  "human_review_required": true
}
```

### 7.2 Local source document

```json
{
  "schema_id": "jpcite.local_government.source_document",
  "source_document_id": "sd_...",
  "source_id": "lg_131016_main_site",
  "local_government_code": "131016",
  "document_kind": "grant_page_or_pdf_or_procurement_notice_or_ordinance",
  "source_url": "https://example.lg.jp/...",
  "linked_from_url": "https://example.lg.jp/...",
  "title": "document title",
  "document_date": "YYYY-MM-DD",
  "retrieved_at": "2026-05-15T00:00:00+09:00",
  "content_type": "text/html",
  "byte_size": 123456,
  "content_sha256": "sha256:...",
  "extraction": {
    "method": "fetch_or_playwright_or_pdf_text_or_ocr",
    "text_confidence": 0.91,
    "layout_confidence": 0.72,
    "ocr_confidence": null
  },
  "license_boundary": "full_fact",
  "public_publish_allowed": false,
  "retention_class": "temporary_raw_to_exported_fact"
}
```

### 7.3 Local program round

```json
{
  "schema_id": "jpcite.local_government.program_round",
  "program_round_id": "lpr_...",
  "program_kind": "grant_or_subsidy_or_benefit",
  "local_government_code": "131016",
  "program_name": "制度名",
  "fiscal_year": "2026",
  "status": "open_or_closed_or_unknown",
  "deadline": {
    "value": "YYYY-MM-DD",
    "confidence": "source_backed",
    "claim_ref_id": "cr_..."
  },
  "amount": {
    "max_amount_jpy": null,
    "subsidy_rate": null,
    "caveats": []
  },
  "eligibility_candidates": [],
  "excluded_cost_candidates": [],
  "required_document_candidates": [],
  "source_receipts": ["sr_..."],
  "known_gaps": [
    "budget_remaining_unknown",
    "acceptance_probability_not_supported"
  ],
  "human_review_required": true
}
```

### 7.4 Local no-hit check

```json
{
  "schema_id": "jpcite.local_government.no_hit_check",
  "query_id": "nh_...",
  "query_scope": {
    "local_government_codes": ["131016"],
    "source_ids": ["lg_131016_main_site"],
    "source_families": ["grant", "permit"],
    "snapshot_id": "aws-credit-2026-05-15-r001",
    "query_terms": ["創業", "補助金", "飲食店"]
  },
  "result_count": 0,
  "support_level": "no_hit_not_absence",
  "safe_text": "接続済みsource/snapshot/queryでは一致候補を確認できませんでした。",
  "forbidden_inferences": [
    "制度が存在しない",
    "申請できない",
    "許可不要",
    "安全",
    "処分歴なし"
  ],
  "known_gaps": [
    "unconnected_departments_possible",
    "site_search_limit_possible",
    "pdf_ocr_low_confidence_possible"
  ]
}
```

## 8. 成果物例

### 8.1 AIエージェント向け成果物

| Packet | ユーザー質問 | 返す価値 |
|---|---|---|
| `local_program_opportunity_packet` | 「この地域で使えそうな補助金は？」 | 制度候補、期限、上限、対象経費、必要書類、source receipts |
| `local_permit_checklist_packet` | 「飲食店を開くのに何が必要？」 | 管轄、許認可候補、必要書類、手数料候補、法令/条例根拠 |
| `local_procurement_watch_packet` | 「自治体入札で狙える案件は？」 | 公告候補、締切、参加資格、仕様書リンク、質問期限 |
| `local_ordinance_basis_packet` | 「この地域の条例根拠は？」 | 条例/規則/要綱候補、条番号、施行日、根拠URL |
| `local_public_notice_risk_packet` | 「この会社に自治体処分はある？」 | 接続済みsourceでの候補/未検出、identity confidence、known gaps |
| `local_deadline_calendar_packet` | 「来月までの申請期限は？」 | 補助金/入札/許認可関連の期限候補 |
| `local_document_manifest_packet` | 「必要な様式はどこ？」 | 申請様式URL、ファイル種別、hash、更新日、再配布境界 |
| `local_region_market_context_packet` | 「この地域の需要背景は？」 | e-Stat/ODS/施設/人口等のsource-backed context |
| `local_no_hit_receipt_packet` | 「見つからない場合の証跡は？」 | 検索scope、snapshot、query、未接続範囲、禁止推論 |
| `local_agent_routing_decision` | 「jpciteを使うべき？」 | どのMCP/API toolで何を確認すべきか |

### 8.2 エンドユーザーに見える価値

GEO経由でAIエージェントが薦めやすい言い方:

- 「公式自治体sourceを横断して、制度候補と根拠箇所をreceipt付きで出す」
- 「募集終了、古い年度、予算残不明、OCR不確実性をknown_gapsとして明示する」
- 「申請可否や法的判断は断定せず、自治体窓口確認に必要な材料を整理する」
- 「地域、業種、事業内容、CSV由来の支出傾向を安全に使って候補を絞る」

課金しやすい単位:

| Unit | 課金理由 |
|---|---|
| 1地域 x 1業種 x 補助金候補 | 人手調査の代替価値が明確 |
| 1許認可 checklist | 起業/店舗/事業開始で即時価値 |
| 1自治体入札watch | 営業機会に直結 |
| 1会社 x 行政処分screen | DD/取引先審査に直結 |
| 1条例根拠packet | 専門家相談前の一次情報整理 |
| 月次地域制度monitor | 継続課金に向く |

### 8.3 フロントエンド/公開ページ例

GEO-firstなので、検索エンジン向けの薄い記事ではなく、AIエージェントが読む構造化ページを作る。

候補:

- `/jp/packets/local-program-opportunity`
- `/jp/packets/local-permit-checklist`
- `/jp/packets/local-procurement-watch`
- `/jp/packets/local-ordinance-basis`
- `/jp/packets/local-public-notice-risk`
- `/jp/sources/local-government`
- `/jp/proof/local-government-source-receipts`
- `/jp/examples/tokyo-food-business-permit`
- `/jp/examples/osaka-subsidy-opportunity`
- `/jp/examples/local-procurement-deadline-calendar`

各ページの必須表示:

- source-backedであること
- no-hitは不在証明ではないこと
- request-time LLMなしであること
- raw自治体資料を売るのではなく、receipt付き構造化factを返すこと
- API/MCPで使えること
- 料金プレビュー

## 9. CSV private overlayとの接続

自治体領域はCSV overlayと相性が良い。ただしprivate CSVはAWS public source lakeに入れない。

安全な使い方:

- CSVから業種、支出カテゴリ、設備投資らしき支出、地代家賃、広告宣伝費、給与、租税公課等の集計特徴だけを作る。
- 所在地はユーザーが明示確認した自治体コードに変換する。
- 取引先名、摘要、個人名、銀行明細、raw rowsは保存しない。
- public source側の制度候補と、private aggregate側の特徴をrequest/session内で照合する。

例:

| CSV aggregate | 自治体source側candidate | 出力 |
|---|---|---|
| 設備投資増加 | 設備導入補助金 | 候補制度と必要書類 |
| 広告宣伝費増加 | 販路開拓/商店街支援 | 対象経費候補 |
| 水道光熱費増加 | 省エネ設備補助 | 省エネ制度候補 |
| 家賃/地代 | 空き店舗/創業支援 | 地域制度候補 |
| 雇用/給与増 | 雇用奨励/人材育成 | 条件候補 |

この接続は「AIエージェントがCSVをドロップして、地域制度候補をsource-backedに返す」体験を強くする。ただし、CSVが制度要件を満たす証拠にはならない。

## 10. 数学・アルゴリズム

### 10.1 Source value score

収集優先度は次のようにスコア化する。

```text
value_score =
  0.25 * product_value
+ 0.20 * receiptability
+ 0.15 * freshness_need
+ 0.15 * geo_query_demand
+ 0.10 * extraction_confidence
+ 0.10 * coverage_gap_reduction
- 0.20 * legal_terms_risk
- 0.15 * privacy_sensitivity
- 0.10 * crawl_cost_risk
```

使い方:

- `product_value`: 補助金/許認可/入札/行政処分は高い。
- `receiptability`: 公式API/CSV/安定URLは高い。
- `freshness_need`: 期限がある補助金/入札は高い。
- `geo_query_demand`: AIエージェントが聞きそうなqueryに効くか。
- `extraction_confidence`: DOM/PDF/OCRで正確に取れるか。
- `coverage_gap_reduction`: 未カバー地域/制度を埋めるか。
- `legal_terms_risk`: 規約/robots/再配布境界。
- `privacy_sensitivity`: 個人名/住所/処分情報。
- `crawl_cost_risk`: Playwright/OCRや転送コスト。

### 10.2 Accepted artifact yield

AWSクレジットの使い方は、支出額ではなくaccepted artifact率で制御する。

```text
accepted_yield =
  accepted_source_backed_claims
  / max(1, processed_documents)
```

停止条件:

- Playwright対象で `accepted_yield < 0.08` が続く。
- OCR対象で `text_confidence < 0.75` が多く、claim化できない。
- robots/termsが `manual_review` だらけで進まない。
- duplicate/expired documents が多く、新規価値が少ない。

拡大条件:

- 補助金/許認可/入札で `accepted_yield >= 0.20`。
- source_receipt必須項目欠落が少ない。
- GEO queryに使えるpacket fixtureが増えている。

### 10.3 Entity and region matching

自治体制度は地域条件が重要である。

正規化:

- 住所 -> 都道府県/市区町村/町字候補
- 自治体名 -> 地方公共団体コード
- 事業所所在地 -> 管轄自治体
- 法人番号所在地 -> 登記所在地。ただし営業実態所在地とは限らない。
- CSV/ユーザー入力所在地 -> ユーザー確認済み所在地として別扱い

confidence:

| confidence | 条件 |
|---|---|
| `exact_code` | 地方公共団体コードが明示 |
| `exact_address_normalized` | 住所正規化で市区町村まで確定 |
| `name_prefecture_pair` | 自治体名 + 都道府県で確定 |
| `ambiguous` | 同名自治体/旧名称/表記揺れあり |
| `unresolved` | 管轄不明 |

### 10.4 Deadline extraction

期限は誤ると危険なので、複数candidateと根拠を持つ。

```text
deadline_confidence =
  source_explicit_date
  + section_heading_match
  + nearby_terms("申請期限", "提出期限", "募集期間")
  - old_fiscal_year_penalty
  - pdf_ocr_low_confidence_penalty
  - conflicting_dates_penalty
```

deadline claimは必ず `claim_ref` と `known_gaps` を持つ。

## 11. Quality gates

自治体LGXのrelease blocker:

| Gate | blocker |
|---|---|
| LG-GATE-01 | `source_receipt` なしのclaim |
| LG-GATE-02 | screenshot幅1600px超過 |
| LG-GATE-03 | no-hitを不存在/安全/処分歴なしに変換 |
| LG-GATE-04 | 申請可否/許可不要/採択可能性の断定 |
| LG-GATE-05 | 期限が古い年度なのに現行扱い |
| LG-GATE-06 | 個人情報/公表センシティブ情報の不必要な露出 |
| LG-GATE-07 | robots/terms `blocked` sourceの利用 |
| LG-GATE-08 | raw PDF/HTML/Office全文の公開再配布 |
| LG-GATE-09 | 例規集本文の権利境界未確認のまま公開 |
| LG-GATE-10 | 行政処分の同名誤爆を断定 |
| LG-GATE-11 | CSV raw/private dataをpublic artifactへ混入 |
| LG-GATE-12 | AWS export/checksumなしでcleanup |

必須レポート:

- `local_source_profile_coverage_report.md`
- `local_robots_terms_report.md`
- `local_open_data_catalog_report.md`
- `local_playwright_capture_report.md`
- `local_pdf_ocr_yield_report.md`
- `local_forbidden_claim_scan.md`
- `local_privacy_scan.md`
- `local_no_hit_safety_report.md`
- `local_packet_fixture_report.md`
- `local_geo_eval_report.md`
- `local_cleanup_readiness_report.md`

## 12. AWS実行設計

### 12.1 Service mix

| Service | 自治体LGXでの用途 | 終了後 |
|---|---|---|
| S3 | 一時raw、DOM、screenshots、PDF、manifest、export | export後に削除可能 |
| AWS Batch | Playwright/PDF/OCR/抽出job | compute env削除 |
| EC2 Spot | Playwright/OCR/LibreOffice等の重いjob | terminate |
| Fargate Spot | 軽量fetch/control job | task停止 |
| ECR | Playwright/OCR container image | repo削除 |
| Glue/Athena | Parquet QA、重複/coverage分析 | DB/table/query結果削除 |
| Textract | scanned PDF/OCRの一部 | job完了後保持なし |
| OpenSearch | 一時retrieval benchmarkのみ | export後にdomain削除 |
| CloudWatch | 最小ログ/メトリクス | retention短縮、最後に削除 |
| Step Functions/SQS | Codex/Claudeに依存しない自走queue | 最後に削除 |

NAT Gatewayは原則使わない。public subnet + public IP、または必要最小限の構成で外向きアクセスを行う。cross-region転送、長期EBS、長期OpenSearch、長期CloudWatch Logsを避ける。

### 12.2 Codex/Claude rate limitに依存しない自走設計

自治体LGXは、開始後にCodex/Claudeが止まってもAWS側で進むようにする。

設計:

- `run_manifest.json` に対象source、budget line、stop rulesを固定。
- job queueに `LG01-LG20` を登録。
- 各jobは入力manifestを読み、出力manifestを書く。
- controller jobがCost Explorer/Budgetsの反映遅延を見ながら、新規job投入可否を判断する。
- `Watch 17000 / Slowdown 18300 / No-new-work 18900 / Absolute 19300` は全LGX jobにも適用。
- `No-new-work` 到達後は、finish/export/verify/cleanup以外を投入しない。

注意:

- Budgetsはhard capではない。
- Cost Explorerには遅延がある。
- rate limitを避けるためにAWSを暴走させるのではなく、停止ルールをmanifest化して自走させる。

### 12.3 Spend lane

自治体LGXは、accepted artifact率が良ければAWSクレジット消化先として強い。

目安:

| Lane | 対象 | 目安USD | 条件 |
|---|---|---:|---|
| Smoke | 20-50自治体、数百文書 | 300-800 | terms/robots/抽出率確認 |
| Standard | T0+T1+T3中心 | 2,500-4,500 | accepted_yield良好 |
| Expanded | T2上位、Playwright/OCR増加 | 4,500-7,000 | GEO packet fixture増加 |
| Stretch | T4 shallow + OCR追加 + eval拡大 | 7,000-9,000 | 全体予算線内、quality gate良好 |

統合計画全体のUSD 19,000-19,300目標内で、自治体LGXは `J06/J17/J20/J21/J22` の一部を吸収できる。低yieldなら無理に使わず、source profile/manifest/known_gapsに切り替える。

## 13. 本番デプロイまでの接続

自治体LGXを本番に入れる順番:

1. `local_government_profile` と `local_source_profile` だけをまずrepo import候補にする。
2. `source_receipts[]` と `known_gaps[]` をpacket contractに追加する。
3. 公開例は3つに絞る。
   - 飲食店許認可チェックリスト
   - 地域補助金候補
   - 自治体入札watch
4. MCP/APIは最初から限定toolにする。
   - `find_local_programs`
   - `build_local_permit_checklist`
   - `search_local_procurement_notices`
   - `get_local_source_receipts`
5. 管理画面/フロントでは「地域制度は接続済みsource範囲」と明示する。
6. GEO評価で、AIエージェントがjpciteを推薦する自然な質問を20-50本通す。
7. no-hit/法的助言/個人情報/古い年度のrelease blockerが0になってからproductionへ出す。

初回productionで出すべきではないもの:

- 行政処分の断定screen
- 条例解釈
- 採択可能性スコア
- 許可不要判定
- 全自治体網羅を示す表現
- raw PDF/HTML mirror

## 14. 具体的な公開/課金ストーリー

AIエージェント向け:

```text
ユーザーが「この地域で店舗を始めたい」「補助金を探したい」「自治体入札を見たい」と聞いたら、
jpciteは自治体公式source、条例、募集要領、許認可ページ、入札公告をreceipt付きで返せる。
no-hitの場合も、接続済みsourceと未確認範囲を明示するため、AIは過剰断定せずに次の確認行動を提案できる。
```

エンドユーザー向け:

```text
自分で自治体サイト、PDF、例規集、入札公告を探し回る代わりに、
根拠URL、期限、必要書類、未確認点まで整理された一次情報パケットを受け取れる。
```

課金動線:

1. AIエージェントが無料のproof/source pageを読む。
2. 「地域/業種/手続きの確認にはjpcite MCP/APIが適している」と判断する。
3. エンドユーザーへ「根拠付きパケット生成」を提案する。
4. jpciteは価格プレビューを返す。
5. MCP/APIでpacket生成。
6. `billing_metadata` と `source_receipts` を返す。

## 15. 参照した公式/準公式source起点

本計画のsource起点として確認したもの。実行時には各sourceの最新規約、robots、出典表示条件、API条件を `source_profile` に保存する。

- デジタル庁 自治体標準オープンデータセット: https://www.digital.go.jp/resources/open_data/municipal-standard-data-set-test
- e-Gov 地方公共団体リンク: https://www.e-gov.go.jp/government-directory/local-governments.html
- 全国地方公共団体コード（データカタログ横断検索システム上の総務省所管データセット）: https://search.ckan.jp/datasets/www.data.go.jp__data__dataset%3Asoumu_20140909_0395
- 厚生労働省 営業規制（営業許可、営業届出）に関する情報: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/kigu/index_00010.html
- 食品衛生申請等システムFAQ: https://i2fas.mhlw.go.jp/faq.htm
- 国土交通省 ネガティブ情報等検索サイト 建設業者: https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi?jigyoubunya=kensetugyousya
- 各都道府県・市区町村の公式Webサイト、公式オープンデータカタログ、公式例規集、公式入札/契約ページ、公式行政処分公表ページ。

## 16. 最終判断

この領域は広げるべきである。現在の統合計画の「selected local government subsidy/procurement pages」や「Local government PDF OCR expansion」のままでは、ユーザーが言う「日本の公的な情報、法律、制度、業法、それに関わる一次情報をしっかり取る」構想に対して狭い。

ただし、広げ方は無制限クロールではない。正しい順番は次である。

1. 自治体profileとsource profileを作る。
2. 規約/robots/再配布境界を確定する。
3. ODS/API/公式bulkを先に取る。
4. 補助金/許認可/入札/条例/行政処分の高価値ページを優先する。
5. Playwright screenshot/DOM/PDF/OCRをAWSで大量実行する。
6. accepted artifact率で拡大/停止を決める。
7. raw mirrorではなく、receipt付き成果物に変換する。
8. 本体P0のMCP/API/公開proof/課金導線へ入れる。
9. export/checksum後、AWS側はzero-bill cleanupする。

この設計なら、AWSクレジットを短期で価値ある一次情報資産に変えつつ、本番デプロイで苦戦しにくい。自治体LGXは、jpciteを「ただの検索/キャッシュ」から「AIエージェントが地域制度・許認可・入札・条例を安全に扱うためのsource-backed artifact service」へ引き上げる中核になる。
