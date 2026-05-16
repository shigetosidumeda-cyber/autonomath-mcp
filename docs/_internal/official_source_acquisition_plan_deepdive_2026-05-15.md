# Official Source Acquisition Research Plan Deep Dive

作成日: 2026-05-15  
担当: Official source acquisition research plan  
範囲: 今後追加する公的一次情報の調査計画。実装コードは触らない。  
前提: 最新情報は公式ソースを優先し、API/CSV/PDF/HTMLの取得可否、更新頻度、利用条件、`source_receipt`化、`no_hit`の意味を実装前に固定する。

## 1. 目的

jpciteがAIエージェントや実務者に推薦されるためには、公式ソースを「URL集」ではなく、検証可能な取得契約として扱う必要がある。

この調査計画の目的は次の5つ。

1. P0/P1で優先調査する公式ソース20件を決める。
2. 各ソースで確認すべき項目を同じテンプレートにする。
3. 収集、更新、検証、ライセンスの実装前チェックを漏れなくする。
4. CSV由来成果物と公的sourceを安全につなぐsource拡張を設計する。
5. `no_hit`を「存在しない証明」ではなく「調査時点・調査範囲の非ヒット証跡」として扱う。

Non-goals:

- APIクライアント、スクレイパ、DB migration、ETL実装はしない。
- 非公式ミラー、民間再配布、個人ブログを一次ソースとして採用しない。
- 利用規約が未確認の本文転載、PDF全文保存、private CSV原文保存を前提にしない。
- 法務、税務、会計、採択可否、与信の最終判断を自動化しない。

## 2. P0/P1公式ソース20件

優先度の意味:

- `P0`: 既存のCSV成果物、補助金/法人/税務/法令/証拠パケットに直結し、実装前調査を最優先する。
- `P1`: 価値は高いが、利用条件、提供終了、取得形式、機械処理負荷、対象ドメインの絞り込みを先に確認する。

| No | Priority | Source ID候補 | 公式ソース | 公式URL | 主な形式 | 更新頻度の初期仮説 | 利用条件の初期論点 | receipt化の焦点 | no_hitの意味 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | P0 | `egov_laws` | e-Gov法令API / 法令データ | https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/ | API, XML, PDF仕様 | 法令改正・公布に応じて随時 | 政府サイト利用条件、API仕様、条文本文の転載境界 | 法令番号、条、施行日、取得API URL、XML hash | 指定法令/条がAPI範囲で見つからない。廃止、未施行、表記揺れの可能性を残す |
| 2 | P0 | `egov_public_comment` | e-Govパブリック・コメント | https://public-comment.e-gov.go.jp/servlet/Public | HTML, PDF, CSV相当の画面取得要確認 | 案件公示・結果公表に応じて随時 | API有無、PDF添付の転載可否、意見本文の扱い | 案件ID、所管府省、募集/結果期間、添付PDF hash | 条件内に案件がない。募集前/終了後/キーワード不一致を区別 |
| 3 | P0 | `kanpo` | 官報 / 国立印刷局・内閣府官報電子化情報 | https://www.npb.go.jp/product_service/books/index.html | HTML, PDF, 有料検索サービス | 発行日ごと。電子化後の公開範囲要確認 | 無料公開範囲、90日制限記事、検索サービス利用条件 | 発行日、号外/本紙、ページ、PDF hash、取得範囲 | 公開範囲内で未ヒット。官報非掲載や有料範囲の可能性を残す |
| 4 | P0 | `houjin_bangou` | 国税庁法人番号公表サイト | https://www.houjin-bangou.nta.go.jp/webapi/index.html | API, CSV/XML/JSON download | 日別差分あり | アプリケーションID、出典表示文、国税庁保証否認文 | 法人番号、名称、所在地、更新日、API/appId version | 法人番号/名称で未ヒット。法人番号未指定、閉鎖、表記揺れ、検索条件不足を区別 |
| 5 | P0 | `invoice_registrants` | 国税庁適格請求書発行事業者公表サイト | https://www.invoice-kohyo.nta.go.jp/web-api/index.html | API, CSV/XML/JSON download | 登録・取消・失効に応じて随時/差分要確認 | アプリケーションID、出典表示、登録番号情報の再利用条件 | 登録番号、氏名/名称、公表状態、登録/失効日、取得日 | 登録番号が公表情報にない。未登録、取消、番号誤り、未公表を断定しない |
| 6 | P0 | `gbizinfo` | gBizINFO | https://info.gbiz.go.jp/hojin/APIManual | REST API, SPARQL, JSON, PDF仕様 | 各法人活動情報の元データ更新に依存 | 利用申請/アクセストークン、APIポリシー、利用規約 | 法人番号、法人活動情報種別、出典元、API version | 法人活動情報がない。法人不存在ではなく、当該カテゴリ未収録として扱う |
| 7 | P0 | `jgrants_subsidies` | Jグランツ補助金情報取得API | https://developers.digital.go.jp/documents/jgrants/api/ | REST API, OpenAPI YAML, JSON | 補助金公募の登録/更新に応じて随時 | API利用規約、出典表示、公開項目と申請者情報の境界 | 補助金ID、制度名、公募期間、所管、API version | 条件に合う補助金がAPI上ない。募集終了/未掲載/自治体制度外を区別 |
| 8 | P0 | `edinet_disclosures` | 金融庁 EDINET API | https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf | API, JSON, XBRL, PDF仕様 | 開示書類提出に応じて随時/日次取得 | EDINET利用規約、XBRL再配布、APIキー要否、書類本文保存境界 | 書類管理番号、EDINETコード、提出日、docType、XBRL/PDF hash | 指定会社/期間に開示がない。上場/提出義務/期間条件を区別 |
| 9 | P0 | `estat` | e-Stat API | https://www.e-stat.go.jp/api/api-info | REST API, JSON, XML, CSV | 統計表ごとの公表周期 | ユーザ登録/appId、クレジット表示、統計表更新日の扱い | 統計表ID、調査年月、更新日、系列キー、API version | 統計表/地域/系列がない。集計対象外、秘匿、ID変更を区別 |
| 10 | P0 | `address_base_registry` | アドレス・ベース・レジストリ | https://www.digital.go.jp/policies/base_registry_address/ | CSV ZIP, PDF解説, OSS tool | データ提供サイト更新に応じて随時/版管理要確認 | 政府標準利用規約準拠、出典記載、第三者権利 | 町字ID、所在地表記、版、CSV file hash | 住所正規化で未ヒット。住所不存在ではなく表記揺れ/未整備/履歴差を示す |
| 11 | P0 | `procurement_portal` | 調達ポータル/調達情報等公開機能API | https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html | API, CSV, XML, HTML/PDF | 公示・訂正・落札に応じて随時 | 政府標準利用規約/CC BY 4.0相当、外部DB由来条件 | 案件ID、機関、公告日、資料URL、訂正/取消履歴 | 条件に合う調達がない。公告期間外/検索条件不足/資料未公開を区別 |
| 12 | P0 | `jpo_patent_api` | 特許庁 特許情報取得API | https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html | API, PDF規約/手引き | 試行提供、アクセス上限あり。更新頻度要確認 | 利用登録、ID/password、試行段階、アクセス上限 | 出願番号、権利種別、取得API、取得日時、レスポンスhash | 出願情報が取れない。対象外種別、実用新案除外、権限/上限を区別 |
| 13 | P1 | `jpo_standard_data` | 特許情報標準データ | https://www.jpo.go.jp/system/laws/sesaku/data/keikajoho/index.html | TSV bulk, 仕様書, サンプル | 開庁日発行、週次まとめ提供あり | データ提供申込/利用条件、bulk保存容量、再配布境界 | データ種別、発行日、TSV hash、仕様書version | 該当権利/経過がない。未収録/翌営業日反映待ちを区別 |
| 14 | P1 | `real_estate_library` | 国土交通省 不動産情報ライブラリAPI | https://www.reinfolib.mlit.go.jp/help/apiManual/ | REST API, JSON, GeoJSON, pbf | 地価/取引価格等の公表周期に依存 | API利用規約、無償利用、個別物件特定不可加工 | 価格情報ID相当、期間、地域、データ種別、取得URL | 条件内に価格情報がない。取引なしではなく、加工/期間/粒度不足を示す |
| 15 | P1 | `ksj_national_land` | 国土数値情報ダウンロードサービス | https://nlftp.mlit.go.jp/ksj/ | ZIP, GML, GeoJSON相当, CSV/PDF仕様 | データセットごとに年次/随時 | 旧約款準拠、原著作権者、出典表示、個別データ条件 | データセットID、版、ファイルhash、空間範囲 | 地物がない。未整備/縮尺/年度差/データセット違いを区別 |
| 16 | P1 | `gsi_tiles` | 国土地理院 地理院タイル等 | https://maps.gsi.go.jp/development/siyou.html | Tiles, XML/JSON-like specs, API系 | タイル・基盤データ更新に依存 | 国土地理院コンテンツ利用規約、測量成果利用条件 | タイルURL、z/x/y、取得日時、レイヤID | タイル/座標に情報がない。範囲外、ズーム不足、レイヤ違いを区別 |
| 17 | P1 | `data_go_jp_catalog` | DATA.GO.JP データカタログAPI | https://www.data.go.jp/for-developer/for-developer/ | CKAN API, JSON | 登録メタデータ更新に応じて随時 | カタログメタデータ利用条件、個別データセット条件継承 | dataset_id、resource_id、publisher、resource URL | カタログ未ヒット。データ不存在ではなくメタデータ未登録を示す |
| 18 | P1 | `geospatial_jp` | G空間情報センター | https://front.geospatial.jp/how_to_use/manual8/ | CKAN API, file download, metadata | データ提供者ごとに異なる | センター約款に加え、各データ利用規約が優先/併存 | dataset/resource ID、提供者、個別license、file hash | センター検索で未ヒット。提供元移転/非公開/権限要を区別 |
| 19 | P1 | `courts_hanrei` | 裁判所 裁判例検索 | https://www.courts.go.jp/hanrei/search1/index.html?lang=ja | HTML, PDF | 主要判決掲載に応じて随時 | APIなし想定、PDF取得負荷、全判決網羅でない旨の明示 | 事件番号、裁判年月日、裁判所、PDF hash | 裁判例検索にない。判決不存在ではなく未掲載/非公刊/検索条件不足 |
| 20 | P1 | `resas_api` | RESAS API | https://opendata.resas-portal.go.jp/docs/api/v1/index.html | REST API, JSON | 提供終了/新規申込停止の告知確認が必要 | APIキー、提供終了告知、代替API探索 | API endpoint、地域/年度、取得日時、終了告知receipt | 未ヒット以前に提供終了/キー不可の可能性。代替ソース探索gapへ回す |

## 3. 各ソースで確認する項目テンプレート

各ソース調査は、このテンプレートを1 sourceごとに埋める。未確認欄を残したまま実装に進めない。

```yaml
source_id:
priority: P0 | P1
official_name:
official_owner:
operating_body:
official_url:
api_catalog_url:
developer_doc_url:
terms_url:
privacy_url:
contact_url:
checked_at: "2026-05-15T00:00:00+09:00"

source_type:
  - rest_api
  - sparql
  - ckan_api
  - csv_download
  - tsv_bulk
  - pdf
  - html_search
  - tile
  - other

auth:
  required: true | false | unknown
  method: app_id | api_key | bearer_token | id_password | none | unknown
  registration_url:
  secret_storage_required: true | false

data_objects:
  - program
  - corporation
  - invoice_registrant
  - law
  - disclosure
  - statistic
  - address
  - procurement
  - patent
  - land
  - case_law

join_keys:
  - corporation_number
  - invoice_registration_number
  - jgrants_subsidy_id
  - law_id
  - article_id
  - edinet_code
  - stats_data_id
  - municipality_code
  - address_code
  - procurement_case_id
  - patent_application_number

formats:
  response_format:
  downloadable_format:
  charset:
  compression:
  schema_or_spec_url:
  sample_url:

freshness:
  publisher_update_frequency:
  observed_update_frequency:
  freshness_window_days:
  stale_after_days:
  change_signal:
    - updated_at_field
    - diff_download
    - news_page
    - etag
    - last_modified
    - file_name_date
    - sitemap
    - none

license:
  terms_name:
  attribution_required: true | false | unknown
  attribution_text:
  commercial_use: allowed | conditional | prohibited | unknown
  redistribution: allowed | derived_only | prohibited | unknown
  excerpt_policy: none | short_excerpt | metadata_only | unknown
  raw_payload_retention: allowed | hash_only | prohibited | unknown
  third_party_rights:

operational_limits:
  rate_limit:
  quota:
  bulk_size:
  downtime_notice_url:
  robots_or_crawl_policy:
  retry_policy_needed:

receipt_contract:
  receipt_kind_supported:
    - positive_source
    - no_hit_check
    - stale_check
    - license_check
    - schema_check
  minimum_receipt_fields:
  content_hash_strategy:
  canonical_url_strategy:
  source_document_retention:
  claim_ref_mapping:

no_hit_semantics:
  no_hit_means:
  no_hit_does_not_mean:
  required_checked_scope:
  recommended_user_message:

implementation_notes:
  parser_risk:
  schema_drift_risk:
  privacy_risk:
  legal_review_required:
  first_test_queries:
```

## 4. 収集の実装前チェックリスト

Source registration:

- [ ] `source_id`を固定し、既存source registryと衝突しない。
- [ ] 公式URL、developer doc、terms、contactを1回の調査で保存する。
- [ ] APIカタログ掲載ソースはAPIカタログURLと実体URLを両方保存する。
- [ ] 公式ドメインを確認する。`.go.jp`以外は運営主体と委託/外部運営の説明をreceiptへ残す。
- [ ] 非公式ラッパー、民間DB、検索エンジンキャッシュを一次ソースにしない。

Acquisition method:

- [ ] API認証の要否、申請手順、秘密情報の保存方法を確認する。
- [ ] APIがないHTML/PDFソースは、取得頻度、負荷、robots/利用規約、PDF hash保存だけで足りるかを確認する。
- [ ] CSV/TSV/ZIP bulkは、ファイル名日付、公開日、内容hash、schema versionを取得単位にする。
- [ ] PDFは全文保存可否を確認し、不可または不明なら`hash_only`または短いメタデータだけにする。
- [ ] 差分取得があるソースは初回bulkと日次diffの役割を分ける。

Data mapping:

- [ ] source側の主キーを特定する。なければ、公式ID + 公開日 + URL + content_hashで擬似キーを設計する。
- [ ] jpcite側のjoin keyを明示する。例: 法人番号、登録番号、住所コード、統計表ID、補助金ID。
- [ ] 名称検索だけに依存するsourceは、表記揺れ・同名・旧称・地域条件をno-hit scopeに含める。
- [ ] CSV由来のprivate subjectとpublic source subjectを直接結合しない。必ずハッシュ化/正規化/ユーザー確認を挟む。

Failure handling:

- [ ] HTTP error、auth error、rate limit、schema drift、empty resultを別々のreceipt/gapにする。
- [ ] `no_hit`を`verification_status=checked_no_hit`にし、`support_level=no_hit_not_absence`を付ける。
- [ ] 検索条件、検索範囲、検索日時、API versionをno-hit receiptに保存する。
- [ ] no-hitをユーザー向けに出すときは「見つからなかった」で止め、「存在しない」と言わない。

## 5. 更新の実装前チェックリスト

Freshness:

- [ ] sourceごとに`freshness_window_days`と`stale_after_days`を設定する。
- [ ] `publisher_update_frequency`と実測の`observed_update_frequency`を分ける。
- [ ] 毎日更新が必要なsourceと、月次/年次でよいsourceを分ける。
- [ ] 更新検知は`Last-Modified`/`ETag`/更新日フィールド/ファイル名日付/ニュースページを優先する。
- [ ] 公式に提供終了/新規停止が告知されているsourceは`source_lifecycle=deprecated|ending`を持たせる。

Snapshots:

- [ ] 取得単位ごとに`corpus_snapshot_id`を発行する。
- [ ] 差分更新でも、AI-facing packetはどのsnapshotから作られたかを返す。
- [ ] 古いsnapshot由来のclaimには`freshness_bucket`を出す。
- [ ] 期限・公募・登録状態など時間依存のclaimは、生成時点と検証時点を分ける。

Schema drift:

- [ ] API仕様書やOpenAPI/YAML/PDFのhashを監視対象にする。
- [ ] 必須項目の追加/削除、enum変更、日付形式変更をschema receiptにする。
- [ ] CSV header hashを保存し、未知列は捨てずに列プロファイルへ残す。
- [ ] 文字コード、改行、JIS水準外文字、住所表記の正規化ルールをsource別に記録する。

## 6. 検証の実装前チェックリスト

Positive receipts:

- [ ] 1 claimに最低1つの`positive_source` receiptを付ける。
- [ ] 支持が直接でない場合は`support_level=derived|weak`を明示する。
- [ ] 同じclaimを複数sourceで確認できる場合は、公式度の高い順にreceiptを並べる。
- [ ] 公式source間で値が矛盾する場合は、片方を捨てず`conflict_receipt`として扱う。

No-hit receipts:

- [ ] no-hitには`checked_sources[]`、`query_normalized`、`query_raw_hash`、`checked_at`、`scope`を必須にする。
- [ ] APIが404を返す場合と、200 empty resultを返す場合を分ける。
- [ ] auth/rate limit/schema errorで検索できなかった場合はno-hitにしない。`source_unchecked`にする。
- [ ] no-hitを根拠に否定的な断定をしない。出力文は「当該公式ソースの当該条件では確認できませんでした」に寄せる。

Cross-source validation:

- [ ] 法人番号とgBizINFO、インボイス、公的補助金情報は法人番号をjoin keyにする。
- [ ] 住所はアドレス・ベース・レジストリで正規化し、正規化失敗は別gapにする。
- [ ] 統計/地域/国土数値情報は自治体コード、町字コード、緯度経度の精度を分ける。
- [ ] 補助金/調達/特許/EDINETは対象期間を必ずclaimに含める。

## 7. ライセンスの実装前チェックリスト

Terms capture:

- [ ] terms URL、terms title、version/date、取得日、terms hashを保存する。
- [ ] APIポリシーとサイト利用規約が別の場合は両方を保存する。
- [ ] third-party rightsが明記されるsourceは、個別dataset/resourceのtermsを優先する。
- [ ] 出典表示文が指定されるsourceは、`attribution_text`としてsource_profileに入れる。

Retention boundary:

- [ ] `raw_payload_retention=allowed|hash_only|prohibited|unknown`をsource別に決める。
- [ ] PDF/HTML本文の長期保存が不明なsourceは、`content_hash`と抽出メタデータだけにする。
- [ ] private CSV由来のraw行、摘要、取引先、金額明細はpublic source ledgerに保存しない。
- [ ] AI-facing出力は、本文転載ではなく正規化事実、短い引用、公式URLへの誘導を基本にする。

Commercial and redistribution:

- [ ] 商用利用可能でも、保証否認文や出典表示が必要なsourceを分ける。
- [ ] 再配布可能、派生事実のみ可能、転載禁止、未確認を区別する。
- [ ] 利用条件が変わった場合に既存receiptの`license_checked_at`を再評価する。
- [ ] 利用条件未確認のsourceは`geo_exposure_allowed=false`で開始する。

## 8. CSV由来成果物とつながるsource拡張案

CSV成果物はprivate入力から作るため、public sourceと同じledgerへraw内容を混ぜない。接続は「private CSV receipt」と「official source receipt」をclaim単位で合流させる。

### 8.1 追加するsource概念

```json
{
  "source_id": "private_csv_upload",
  "source_family": "private_user_file",
  "official_owner": null,
  "source_type": "private_csv",
  "license_boundary": "private_derived_fact_only",
  "raw_payload_retention": "prohibited",
  "geo_exposure_allowed": false,
  "allowed_outputs": [
    "coverage_metrics",
    "column_profile",
    "period_activity_summary",
    "account_vocabulary_counts",
    "review_queue_flags"
  ]
}
```

Public sourceとは別に、CSV由来receiptは次の制限を持つ。

- raw CSV行、摘要、取引先名、金額明細を保存しない。
- `source_file_id`はファイル名ではなくhash化IDにする。
- 期間、列profile、件数、distinct count、分類候補だけを保持する。
- official sourceへ照合する場合は、ユーザー確認済みの法人番号、登録番号、所在地正規化候補などに限定する。

### 8.2 `source_receipt`拡張フィールド

```json
{
  "source_receipt_id": "sr_...",
  "receipt_kind": "positive_source | no_hit_check | private_csv_derived | cross_source_join | stale_check | license_check",
  "source_confidentiality": "public | private | mixed",
  "raw_payload_retention": "allowed | hash_only | prohibited | unknown",
  "license_boundary": "verbatim_allowed | short_excerpt | derived_fact | metadata_only | private_derived_fact_only | review_required",
  "join_basis": {
    "join_key": "corporation_number | invoice_registration_number | address_code | user_confirmed_alias | none",
    "join_confidence": "exact | normalized | fuzzy | user_confirmed | not_joined",
    "join_review_required": true
  },
  "negative_evidence_policy": "no_hit_not_absence",
  "user_visible_caveat": "当該公式ソースの当該条件では確認できませんでした。不存在を証明するものではありません。"
}
```

### 8.3 CSV成果物別のofficial source接続

| CSV由来成果物 | private receipt | 接続するofficial source | join key | 出せるclaim | 出してはいけないclaim |
|---|---|---|---|---|---|
| CSV Coverage Receipt | `private_csv_derived` | なし、またはvendor doc将来追加 | なし | 列、期間、行数、ベンダー推定 | 取引内容、相手先、税務判断 |
| Period Activity Packet | `private_csv_derived` | e-Stat/国税庁資料は参考source候補 | 期間のみ | 月別件数、未来日付flag | 売上/利益の良否、申告要否 |
| Account Vocabulary Map | `private_csv_derived` | 法令/e-Stat/業種統計は補助source | 科目語彙はjoinしない | 科目出現と軽分類候補 | 勘定科目の正誤断定 |
| Industry Signal Packet | `private_csv_derived` + `positive_source` | Jグランツ、J-Net代替調査、e-Stat、RESAS代替 | 業種候補、地域、法人番号はユーザー確認後 | 業種らしさと関連公的制度候補 | 採択可能性、対象要件充足の断定 |
| Review Queue Packet | `private_csv_derived` | 公式source不要 | なし | データ品質の要確認項目 | 会計処理の誤り断定 |
| Evidence-safe Advisor Brief | `private_csv_derived` + selected public receipts | ユーザー確認済みの法人/登録/補助金source | 法人番号、登録番号、所在地 | 支援者に渡せる構造summary | raw明細、秘匿情報、結論 |

### 8.4 cross-source joinの安全ルール

1. private CSVだけから法人名や取引先名を抽出して公的sourceへ自動照合しない。
2. ユーザーが法人番号または登録番号を明示した場合のみ、国税庁/gBizINFO/Jグランツ等へ照合する。
3. 住所照合はアドレス・ベース・レジストリで正規化候補を出し、`join_confidence=normalized`に留める。
4. fuzzy joinはagent-facingで「候補」と表示し、supported claimに昇格しない。
5. official sourceのno-hitはCSV内容の否定に使わない。

## 9. `no_hit`標準意味

`no_hit`は次の意味だけを持つ。

- 指定した公式sourceで、
- 指定した日時に、
- 指定した検索条件と範囲で、
- 正常に検索または取得を実行し、
- 条件に一致する公開情報が返らなかった。

`no_hit`が意味しないこと:

- 対象が存在しない。
- 登録、許認可、補助金、判例、開示、公告が一切ない。
- 公式に否定された。
- 他の公式sourceでも存在しない。
- 将来も存在しない。

AI-facing推奨文:

> 2026-05-15時点で、指定条件により当該公式ソースを確認しましたが、一致する公開情報は取得できませんでした。これは不存在の証明ではありません。表記揺れ、公開範囲、更新タイミング、別ソース掲載の可能性があります。

no-hit receipt最小形:

```json
{
  "receipt_kind": "no_hit_check",
  "support_level": "no_hit_not_absence",
  "source_id": "invoice_registrants",
  "checked_at": "2026-05-15T00:00:00+09:00",
  "checked_sources": ["invoice_registrants"],
  "query_raw_hash": "sha256:...",
  "query_normalized": {
    "registration_number": "T0000000000000"
  },
  "checked_scope": {
    "endpoint": "official_api",
    "date_range": null,
    "jurisdiction": "JP",
    "filters": ["registration_number"]
  },
  "http_status": 200,
  "result_count": 0,
  "does_not_prove_absence": true,
  "known_gaps": [
    {
      "gap_id": "no_hit_not_absence",
      "severity": "info",
      "message": "当該条件では公式ソース上の公開情報を確認できなかった。不存在証明ではない。"
    }
  ]
}
```

## 10. 実装前の順序

1. P0 12件のterms/API仕様/source_profileテンプレートを埋める。
2. 各P0で最小positive queryと最小no-hit queryを1件ずつ決める。
3. `source_profile`に`auth`, `raw_payload_retention`, `license_boundary`, `no_hit_semantics`を追加する設計を確定する。
4. CSV成果物のprivate receiptとpublic receiptを同じpacketに並べるが、raw private dataをpublic ledgerに入れない契約を確定する。
5. P1 8件は、提供終了/利用規約/機械取得可否の調査結果でP0昇格または代替source探索に分ける。

## 11. 直近の調査TODO

- [ ] e-Gov法令API: 最新仕様PDFとAPI v1 docsの差異を確認する。
- [ ] 国税庁法人番号/インボイス: アプリケーションID発行条件、出典表示、差分download仕様を確認する。
- [ ] gBizINFO: REST API v2移行状況、SPARQLとの役割分担、APIポリシーの最新versionを確認する。
- [ ] Jグランツ: 2026-03-27項目追加後のOpenAPI YAMLを保存し、制度名の後方互換を確認する。
- [ ] EDINET: API version、APIキー要否、書類一覧と書類取得のrate/termsを確認する。
- [ ] e-Stat: appId、クレジット表示、CSV形式、更新日指定の使い方を確認する。
- [ ] アドレスBR: データダウンロードサイトの安定性、町字データ留意事項、利用規約を確認する。
- [ ] 調達ポータル: e-Gov APIカタログのAPI公開URLから実際のAPI仕様とCSV/XML仕様を確認する。
- [ ] 特許庁: 特許情報取得APIの登録条件、試行提供制約、標準データとの使い分けを確認する。
- [ ] P1: RESAS API提供終了/新規停止の正確な日付と代替sourceを確認する。
