# Official source license / terms verification checklist

作成日: 2026-05-15  
担当: Official source license / terms verification checklist  
Status: internal deep dive only. 実装コードは触らない。  
Scope: NTA法人番号、インボイス、e-Gov、J-Grants、gBizINFO、e-Stat、EDINET、JPO、p-portal、JETRO等を `source_receipt` として公開する前の公式URL、API、利用規約、ライセンス、商用利用、再配布境界の確認手順。

## 1. 結論

公的ソースは「公式に公開されている」だけでは `source_receipt` として公開できない。公開前に、少なくとも次を source 単位で固定する。

1. 公式URL、API仕様URL、利用規約URL、更新/停止告知URL、問い合わせ先。
2. 利用規約の適用単位。サイト全体、API、ダウンロード、PDF、個別データで規約が分かれる場合は別々に扱う。
3. 商用利用、出典表示、加工表示、第三者権利、個人情報、API認証、アクセス制限。
4. `license_boundary`。raw payload まで出せるのか、正規化factだけ出せるのか、URL/hashだけに止めるのか。
5. `review_required` の条件。少しでも不明な場合は `source_receipt` を公開せず、`known_gap=license_terms_unverified` に落とす。

Default policy:

- `allow_source_url`: true unless terms prohibit linking.
- `allow_normalized_facts`: true only when terms and privacy/third-party checks pass.
- `allow_short_excerpt`: false by default. 必要な場合だけsourceごとに明示許可。
- `allow_raw_payload_redistribution`: false by default. PDL/政府標準利用規約等で可能でも、第三者権利・個人情報・API規約を別途確認する。
- `no_hit`: 不存在証明ではなく「確認範囲で見つからなかった検査結果」だけ。

## 2. Source registration preflight

各sourceの `source_profile` 登録前に、このチェックを全て埋める。

```yaml
source_id:
official_name:
official_owner:
operating_body:
official_home_url:
api_or_download_url:
developer_doc_url:
terms_url:
api_terms_url:
privacy_url:
contact_url:
checked_at: "2026-05-15T00:00:00+09:00"

officiality:
  official_domain_checked: true | false
  official_domain:
  non_go_jp_operator_explained: true | false | not_applicable
  official_api_catalog_url:
  mirror_or_secondary_source_used: false

access:
  method: rest_api | bulk_download | html | pdf | search_ui | other
  auth_required: true | false | unknown
  credential_type: app_id | api_key | bearer_token | id_password | none | unknown
  registration_required: true | false | unknown
  rate_limit:
  terms_acceptance_required: true | false | unknown

license_terms:
  terms_name:
  terms_version_or_last_updated:
  attribution_required: true | false | unknown
  required_attribution_text:
  modification_notice_required: true | false | unknown
  commercial_use: allowed | conditional | prohibited | unknown
  redistribution: raw_allowed | derived_allowed | prohibited | unknown
  third_party_rights: none_known | possible | confirmed | unknown
  personal_data_risk: none | low | medium | high | unknown
  external_database_terms_inherit: true | false | unknown
  government_standard_terms: pdl_1_0 | gsl_2_0 | cc_by_compatible | other | unknown

receipt_exposure:
  license_boundary: public_domain_like | attribution_open | derived_fact | metadata_only | hash_only | no_public_receipt | review_required
  allowed_fact_classes:
  prohibited_outputs:
  source_document_retention: raw_allowed | normalized_only | hash_only | prohibited | unknown
  public_receipt_allowed: true | false
  review_required_reason:
```

## 3. Verification checklist by official source

### 3.1 NTA法人番号公表サイト / 法人番号システムWeb-API

Official anchors:

- Site / guide: https://www.houjin-bangou.nta.go.jp/website/index.html
- API: https://www.houjin-bangou.nta.go.jp/webapi/
- API terms: https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html
- Site terms: https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html
- Diff download: https://www.houjin-bangou.nta.go.jp/download/sabun/index.html

Checks:

- [ ] API利用規約に同意し、アプリケーションIDの取得経路を確認する。
- [ ] APIを使ったサービス表示に必要な国税庁保証否認文をUI/API attributionへ入れる。
- [ ] サイトコンテンツは公共データ利用規約（第1.0版）準拠であることを確認する。
- [ ] 出典例「国税庁法人番号公表サイト（国税庁）（当該ページのURL）」を保存する。
- [ ] 加工した場合は加工表示を必須にする。
- [ ] 差分ファイルの日次作成、過去40日分、OpenPGP署名、文字コード/形式を確認する。
- [ ] 「検索対象除外」「人格のない社団等」「閉鎖」「履歴要否」をno-hit scopeに含める。

Initial boundary:

- `license_boundary`: `attribution_open`
- Public facts: 法人番号、商号又は名称、本店所在地、変更/閉鎖等の公式提供項目、取得日時、API/version、ファイルhash。
- Do not output without review: API raw responseの大量再配布、国税庁保証と誤認させる文言、検索対象除外情報の断定的説明、第三者権利が明示された添付物。

### 3.2 NTA適格請求書発行事業者公表サイト / インボイスWeb-API

Official anchors:

- Site guide: https://www.invoice-kohyo.nta.go.jp/aboutweb/index.html
- API: https://www.invoice-kohyo.nta.go.jp/web-api/index.html
- API terms: https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html
- Site terms: https://www.invoice-kohyo.nta.go.jp/terms-of-use.html
- Download: https://www.invoice-kohyo.nta.go.jp/download/index.html

Checks:

- [ ] API利用にはアプリケーションIDが必要で、利用規約同意と申請/届出手続が必要であることを確認する。
- [ ] APIを使ったサービス表示に必要な国税庁保証否認文を保存する。
- [ ] サイトコンテンツは公共データ利用規約（第1.0版）準拠、出典表示と加工表示が必要であることを確認する。
- [ ] 利用規約上、氏名・登録番号等が個人情報に該当し得る旨の注意をprivacy gateへ反映する。
- [ ] 全件/差分ダウンロード、前月末全件、稼働日差分、過去40稼働日、OpenPGP署名を確認する。
- [ ] 個人事業者の屋号/所在地など「希望する場合に限り公開」される項目を別扱いにする。

Initial boundary:

- `license_boundary`: `derived_fact` for public-facing packets; `attribution_open` only for non-personal法人項目 and after privacy review.
- Public facts: 登録番号、法人の名称/所在地、登録年月日、登録取消/失効年月日、取得日、source URL/hash。
- Do not output without review: 個人事業者の氏名・屋号・住所を含むraw行、登録番号がないことによる「未登録」断定、本人同意なく個人情報に該当し得る情報を公開面へ再掲すること。

### 3.3 e-Gov法令検索 / 法令API / e-Govパブリック・コメント

Official anchors:

- e-Gov terms: https://www.e-gov.go.jp/terms
- Law API catalog: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44
- Law bulk download: https://laws.e-gov.go.jp/bulkdownload/
- Law API spec: https://laws.e-gov.go.jp/file/houreiapi_shiyosyo.pdf
- Public comment service policy: https://public-comment.e-gov.go.jp/contents/service-policy

Checks:

- [ ] e-Gov利用規約が商用利用可、出典表示/加工表示必須、第三者権利確認、CC BY 4.0互換であることを保存する。
- [ ] 法令APIのversionを確認する。2026-05時点ではVersion 2関連告知と仕様差分を確認対象にする。
- [ ] 法令本文、条、別表、様式、画像/PDFを分ける。画像や様式はbulk/APIで扱いが異なる可能性がある。
- [ ] パブコメは案件本文、添付PDF、提出意見、結果資料を別コンテンツとしてterms/third-partyチェックする。
- [ ] 「現行法令」「過去時点」「未施行」「廃止」「条ずれ」をno-hit scopeに含める。

Initial boundary:

- `license_boundary`: `attribution_open` for law metadata/text from official API after terms confirmation; `derived_fact` or `hash_only` for attached PDFs/images until checked.
- Public facts: 法令番号、法令名、条番号、施行/公布/改正日、API URL、取得時点、content hash、パブコメ案件ID/期間/府省。
- Do not output without review: PDF全文転載、添付資料の大規模再配布、第三者権利が混じる図表/画像、現行条文ではないものを現行法として出すこと。

### 3.4 J-Grants 補助金情報取得API

Official anchors:

- API docs: https://developers.digital.go.jp/documents/jgrants/api/
- API overview PDF: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf
- API terms PDF: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf

Checks:

- [ ] 公式API仕様とYAMLを保存し、v1/v2/追加項目の差分告知を確認する。
- [ ] 利用申請なし、認証なし、10回/秒上限を operational limit に保存する。
- [ ] API利用規約の出典表示「出典：Jグランツ」と、加工時の保証否認文を保存する。
- [ ] 第三者権利、自治体/府省等の原資料リンク、添付公募要領PDFの規約を個別確認する。
- [ ] J-Grantsの補助金情報は申請可否・採択可能性の根拠ではないことをユーザー表示へ残す。

Initial boundary:

- `license_boundary`: `derived_fact`
- Public facts: 補助金ID、タイトル、制度名、対象地域、募集開始/終了日時、補助上限、業種/従業員条件、API取得日時、出典/加工表示。
- Do not output without review: 公募要領PDF全文、申請者情報、採択予測、自治体等の添付資料をJ-Grants規約だけで再配布すること。

### 3.5 gBizINFO

Official anchors:

- API guide: https://content.info.gbiz.go.jp/api/index.html
- Legacy/API manual anchor: https://info.gbiz.go.jp/hojin/APIManual
- Site terms: https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406-%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84
- API/data download terms: https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102-API-%E3%83%87%E3%83%BC%E3%82%BF%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84

Checks:

- [ ] REST API v2/v1の現行公開状態を確認する。
- [ ] API/ダウンロード利用は事前申請とアクセストークンが必要で、申請目的の範囲内に限られることを保存する。
- [ ] サイト利用規約上、商用利用可、出典表示、加工表示、第三者権利、外部DB連携元条件の継承を確認する。
- [ ] API制限、通信量制限、トークン停止条件を運用制限へ入れる。
- [ ] gBizINFOは各省庁等から取得した法人活動情報の集約であるため、情報カテゴリごとの元データ/出典を receipt に保持する。

Initial boundary:

- `license_boundary`: `derived_fact`
- Public facts: 法人番号に紐づく法人基本情報、届出/認定/表彰/財務/特許/調達/補助金/職場情報の存在、各項目の公表組織、取得日時、API version。
- Do not output without review: 申請目的外のAPI利用、元データ規約未確認カテゴリのraw再配布、gBizINFOにないことを法人活動不存在として断定すること。

### 3.6 e-Stat

Official anchors:

- Site terms: https://www.e-stat.go.jp/terms-of-use
- API guide: https://www.e-stat.go.jp/api/api-info/api-guide
- API terms: https://www.e-stat.go.jp/api/terms-of-use

Checks:

- [ ] e-Stat利用規約が商用利用可、出典表示/加工表示、第三者権利、外部DB条件継承、CC BY 4.0互換であることを保存する。
- [ ] API利用にはユーザ登録とアプリケーションIDが必要であることを確認する。
- [ ] API公開サービスではクレジット表示が必要であることを確認する。
- [ ] 統計表ID、調査年月、系列、地域コード、単位、秘匿値、改定日をfactに含める。
- [ ] 統計表ごとに個別注記、推計/速報/確報、欠損/秘匿の意味を確認する。

Initial boundary:

- `license_boundary`: `attribution_open`
- Public facts: 統計表ID、系列名、地域/時点/単位付き数値、更新日、取得日時、API endpoint、加工表示。
- Do not output without review: ミクロデータ、調査票情報、個票再識別につながる加工、小地域での秘匿値補完、個別統計で別利用ルールがあるコンテンツ。

### 3.7 EDINET / EDINET API

Official anchors:

- EDINET terms: https://disclosure2dl.edinet-fsa.go.jp/guide/static/submit/WZEK0030.html
- API terms PDF: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140191.pdf
- API spec PDF: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf
- API catalog: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/33
- EDINET taxonomy legal statement: https://www.fsa.go.jp/search/EDINET_Taxonomy_Legal_Statement.html

Checks:

- [ ] EDINET利用規約とEDINET API機能利用規約の両方を確認する。
- [ ] Webサイトの機械取得は原則APIを使うべきであることを運用制限に入れる。
- [ ] API仕様書の版を確認する。2026-05確認時点では「EDINET API 仕様書 Version 2, 2026年4月」が対象。
- [ ] 提出書類本文、XBRL、PDF、タクソノミ、企業提出資料を別コンテンツとして扱う。
- [ ] 提出会社/第三者が作成した内容の著作権・商標・監査報告書等の権利境界を確認する。
- [ ] 投資助言、信用格付、与信判断と誤認される出力を禁止する。

Initial boundary:

- `license_boundary`: `metadata_only` by default; `derived_fact` only for normalized filing metadata and extracted numeric facts after legal review.
- Public facts: 書類管理番号、EDINETコード、提出者名、提出日、docType、API取得URL、XBRL/PDF hash、抽出した正規化財務数値と単位。
- Do not output without review: 有報/四半期報告書PDFの全文再配布、XBRL一括再配布、監査報告書等の長文転載、投資助言/格付風の判断。

### 3.8 JPO 特許情報取得API / 特許情報標準データ

Official anchors:

- Patent information API: https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html
- API terms PDF: https://www.jpo.go.jp/system/laws/sesaku/data/document/api-provision/api-provision-kiyaku.pdf
- API information site: https://ip-data.jpo.go.jp/
- Standardized data: https://www.jpo.go.jp/system/laws/sesaku/data/keikajoho/index.html
- Bulk download service: https://www.jpo.go.jp/system/laws/sesaku/data/download.html

Checks:

- [ ] 特許情報取得APIは試行提供で、利用規約同意、利用の手引き遵守、利用登録、ID/password管理が必要であることを保存する。
- [ ] 国内APIの対象は日本国特許庁の特許・意匠・商標出願情報等で、実用新案は除外される旨をscopeに入れる。
- [ ] OPD-APIは新規申込終了など募集状態を確認する。
- [ ] API情報提供サイトの仕様、コード定義、アクセス方法を保存する。
- [ ] 標準データ/一括ダウンロードは別規約・別申込・別更新単位として扱う。
- [ ] 公報本文、図面、引用文献、審査書類、第三者商標/意匠画像の権利を個別確認する。

Initial boundary:

- `license_boundary`: `metadata_only` until terms review; `derived_fact` for bibliographic/status facts after review.
- Public facts: 出願番号、公開/登録番号、権利種別、出願日、公開日、ステータス、取得API、取得日時、response hash。
- Do not output without review: 図面/全文明細書/審査書類の再配布、ID/password共有、試行提供の上限回避、対象外の実用新案やOPD未承認利用。

### 3.9 p-portal / 調達ポータル・政府電子調達（GEPS）

Official anchors:

- Site policy / terms links: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html
- Privacy: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/privacy.html
- System outline: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/outline.html

Checks:

- [ ] 調達ポータル・GEPS利用規約PDFを確認する。
- [ ] サイトポリシー上の利用時間、メンテナンス、緊急停止を保存する。
- [ ] コンテンツの第三者権利、外部DB/API連携元条件の継承を確認する。
- [ ] 未ログインで利用可能な「調達情報検索」「事業者情報検索」と、ログイン/電子証明書等が必要な機能を分ける。
- [ ] 添付公告、仕様書、入札説明書、契約書式、PDFは案件ごとに再配布可否を確認する。
- [ ] 「p-portal公式の公開API」は確認できない場合、HTML検索/手動receiptを `review_required` とする。官公需情報ポータル等の別APIを混同しない。

Initial boundary:

- `license_boundary`: `metadata_only` by default; `derived_fact` after terms/PDF review.
- Public facts: 案件名、機関、公告日、締切、調達種別、案件URL、取得日時、添付資料hash。
- Do not output without review: 仕様書/PDF全文、ログイン後情報、入札参加者/契約関連の非公開情報、別システムAPIをp-portal由来として表示すること。

### 3.10 JETRO

Official anchors:

- Site terms: https://www.jetro.go.jp/legal.html
- Logo terms: https://www.jetro.go.jp/legal/logo.html

Checks:

- [ ] JETRO一般サイト利用規約では、コンテンツの知的財産権がJETROまたは表示された所有者に帰属することを確認する。
- [ ] ダウンロード/印刷はサイトの意図した目的範囲に限られ、事前許可なく複製・販売・出版・頒布・変更・表示できないことを確認する。
- [ ] 各サービス別規約を確認する。例: ビジネス短信購読、J-messe、e-Venue、会員サービス、動画等。
- [ ] JETROは政府系機関だが、政府標準利用規約やPDLとは限らないため、sourceごとに `review_required` を初期値にする。
- [ ] 調査レポート、海外ニュース、統計表、見本市DB、動画、PDFを別コンテンツとして扱う。

Initial boundary:

- `license_boundary`: `hash_only` or `metadata_only`; public facts only after page/service-specific terms review.
- Public facts: 記事/レポート/イベントのタイトル、公式URL、公開日、国/地域、取得日時、hash、短い機械要約の有無は法務レビュー後。
- Do not output without review: 記事本文転載、調査レポートPDF再配布、動画/画像、会員/購読コンテンツ、商用プロダクトでの全文DB化。

## 4. `license_boundary` judgment table

| `license_boundary` | Use when | Public receipt allowed | Public output allowed | Raw retention | Examples / initial mapping |
|---|---|---:|---|---|---|
| `public_domain_like` | 著作権対象外の数値・簡単な表、または明確に制約がない公知ID。ただし出典表示は残す | yes | ID、数値、短いラベル、URL、hash | normalized or raw if terms permit | e-Statの単純数値、法人番号そのもの。ただしsource termsはなお保存 |
| `attribution_open` | PDL/GSL/CC BY互換など、商用利用・複製・翻案が条件付きで可能 | yes | 正規化fact、短い説明、出典表示、加工表示 | raw may be retained internally if terms/privacy pass | NTA法人番号、e-Gov、e-Stat |
| `derived_fact` | API/サイト規約は利用可能だが、第三者権利・個人情報・申請目的・PDF境界がある | yes, with limits | 正規化fact、メタデータ、source URL、hash、取得日時 | normalized only; raw internal review | インボイス、J-Grants、gBizINFO |
| `metadata_only` | 本文/添付/提出資料の再配布が不明、または第三者権利が強い | yes, metadata only | タイトル、ID、日付、URL、hash、no-hit scope | hash only or restricted raw | EDINET、JPO、p-portal、JETRO初期値 |
| `hash_only` | 内容自体を公開できないが、取得・照合証跡は必要 | limited | URL、取得日時、content hash、terms URL、review_required reason | hash only | JETROレポートPDF、p-portal添付資料、EDINET PDF before review |
| `no_public_receipt` | 規約が公開出力を禁じる、ログイン後/契約/個人情報/秘密情報 | no | none; known_gap only | prohibited or tenant-scoped only | 会員/購読/ログイン後データ、private CSV raw |
| `review_required` | 公式性、terms、商用利用、再配布、第三者権利、個人情報のどれかが未確認 | no | 「未確認」のknown_gapだけ | prohibited until reviewed | 新規source、URL変更後、規約改定後 |

Decision rules:

1. 迷ったら `review_required`。
2. 公式URLとterms URLが保存できないsourceは `no_public_receipt`。
3. API規約とサイト規約が両方ある場合、厳しい方を採用する。
4. 第三者権利が「可能性あり」の場合、本文/画像/PDFは `metadata_only` 以下に落とす。
5. 個人情報に該当し得る情報は、公式公開情報でも public packet では `derived_fact` 以下に落とす。
6. 申請/アクセストークン/ID/passwordが必要なAPIは、credential利用範囲と申請目的を receipt に出さず、公開できるのは取得結果の許可済みfactだけ。
7. 出典表示と加工表示は `source_receipt` に機械可読で必ず残す。

## 5. Output classification

### 5.1 出力可能なfact

出力可能にするには、`source_profile.public_receipt_allowed=true` かつ `license_boundary` が `review_required` でないこと。

Allowed fact classes:

| Fact class | Allowed output | Required qualifiers |
|---|---|---|
| Official ID | 法人番号、登録番号、補助金ID、統計表ID、書類管理番号、出願番号 | source_id、official URL、取得日時、ID形式、no guarantee disclaimer if required |
| Official metadata | 名称、所在地、機関名、公開日、締切、法令番号、条番号、docType | as-of date、source URL、加工表示、同名/旧称リスク |
| Numeric/statistical fact | 統計値、補助上限額、財務数値、件数 | 単位、時点、表/系列ID、速報/確報、秘匿/欠損処理 |
| Status fact | 登録状態、失効/取消、閉鎖、募集状態、提出状態 | valid_from/valid_until、取得時点、状態語彙のsource由来 |
| Derived normalized fact | 住所正規化、カテゴリ正規化、期限計算、金額単位変換 | 「加工して作成」、変換ルールversion、元値hash |
| Source receipt metadata | source_url、canonical_url、terms_url、content_hash、fetched_at、freshness_bucket | license_boundary、support_level、known_gaps |
| No-hit check | 検索条件内で該当なし | checked_scope、query、time、no_hit_not_absence、未収録/表記揺れの可能性 |

### 5.2 出力禁止または要確認

| Class | Default | Reason |
|---|---|---|
| Raw API payload bulk | 要確認 | API規約、再配布、申請目的、アクセス制限に抵触し得る |
| PDF/HTML本文全文 | 禁止/要確認 | 著作権、第三者権利、添付資料ごとの別規約 |
| 画像、ロゴ、図面、動画 | 禁止/要確認 | ロゴ/商標/肖像/図面/第三者権利 |
| 個人事業者の氏名・住所・屋号 | 原則禁止/要確認 | 公式公開でも個人情報保護法リスクがある |
| ログイン後/会員/購読データ | 禁止 | 公開source_receiptの対象外 |
| API key、app ID、token、ID/password | 禁止 | credential secret |
| 申請目的外のAPI取得結果 | 禁止 | API利用条件違反 |
| 「存在しない」「未登録確定」「違法なし」などの断定 | 禁止 | no-hitは不存在証明ではない |
| 投資助言、信用格付、採択可能性、与信判断 | 禁止 | source factを意思決定助言へ変換している |
| 出典元の保証/承認を示唆する文言 | 禁止 | 多くの規約で保証否認・誤認防止が必要 |
| 古いsnapshotを最新として提示 | 禁止 | freshness falsification |

## 6. Source receipt publish gate

`source_receipt` を公開する直前のgate:

- [ ] `source_id` が固定され、source registry内で一意。
- [ ] `official_home_url`, `api_or_download_url`, `terms_url`, `checked_at` がある。
- [ ] API規約とサイト規約が両方ある場合、両方のURLと適用範囲を保存した。
- [ ] `commercial_use`, `redistribution`, `attribution_required`, `modification_notice_required`, `third_party_rights`, `personal_data_risk` が `unknown` ではない。
- [ ] `license_boundary` が `review_required` ではない。
- [ ] 出典表示・加工表示・保証否認文のテンプレートを `citation_policy` に保存した。
- [ ] raw retention 方針が `raw_allowed`, `normalized_only`, `hash_only`, `prohibited` のどれかに決まっている。
- [ ] no-hit receipt には `checked_scope`, `query`, `source_version`, `checked_at`, `support_level=no_hit_not_absence` がある。
- [ ] `freshness_bucket` と stale 条件がある。
- [ ] 規約改定/URL変更/仕様変更を検知したら自動で `license_terms_stale` gap に落とす。

Fail closed:

```json
{
  "gap_id": "license_terms_unverified",
  "severity": "review",
  "source_id": "example_source",
  "agent_instruction": "Do not present this claim as audit-grade. Terms, commercial use, or redistribution boundary is not verified."
}
```

## 7. Recommended initial source boundaries

| Source | Initial boundary | Publish readiness | Notes |
|---|---|---|---|
| `houjin_bangou` | `attribution_open` | ready after appId/attribution setup | PDL 1.0, API disclaimer, daily diff |
| `invoice_registrants` | `derived_fact` | privacy review required | PDL 1.0 but personal data caution |
| `egov_laws` | `attribution_open` | ready after API v2 spec pin | CC BY compatible terms, law versioning needed |
| `egov_public_comment` | `derived_fact` | attachment review required |案件/PDF/意見本文を分ける |
| `jgrants_subsidies` | `derived_fact` | ready for API facts; PDFs review | 出典/加工/保証否認、10 req/sec |
| `gbizinfo` | `derived_fact` | token purpose review required | API申請目的、元データ条件継承 |
| `estat` | `attribution_open` | ready after appId/credit setup | 商用可、CC BY互換、個別別紙に注意 |
| `edinet_disclosures` | `metadata_only` | legal review required for extracted facts | filings are third-party submitted documents |
| `jpo_patent_api` | `metadata_only` | terms and registration review required | trial API, ID/password, OPD new applications closed |
| `procurement_portal` | `metadata_only` | terms/PDF review required | no confirmed public API in this pass |
| `jetro` | `hash_only` | review required | no broad open-government license; permission often required |

## 8. References checked on 2026-05-15

- 国税庁法人番号公表サイト 利用規約: https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html
- 国税庁法人番号システムWeb-API 利用規約: https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html
- 国税庁法人番号公表サイト 差分データ: https://www.houjin-bangou.nta.go.jp/download/sabun/index.html
- 国税庁インボイス公表サイト 利用規約: https://www.invoice-kohyo.nta.go.jp/terms-of-use.html
- 国税庁インボイスWeb-API 利用規約: https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html
- 国税庁インボイス公表情報ダウンロード: https://www.invoice-kohyo.nta.go.jp/download/index.html
- e-Gov 利用規約: https://www.e-gov.go.jp/terms
- e-Gov APIカタログ 法令API: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44
- e-Gov法令検索 XML一括ダウンロード: https://laws.e-gov.go.jp/bulkdownload/
- J-Grants API docs: https://developers.digital.go.jp/documents/jgrants/api/
- J-Grants API利用概要: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf
- J-Grants API利用規約: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf
- gBizINFO API guide: https://content.info.gbiz.go.jp/api/index.html
- gBizINFO 利用規約: https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406-%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84
- gBizINFO API・データダウンロード利用規約: https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102-API-%E3%83%87%E3%83%BC%E3%82%BF%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84
- e-Stat 利用規約: https://www.e-stat.go.jp/terms-of-use
- e-Stat API利用規約: https://www.e-stat.go.jp/api/terms-of-use
- EDINET利用規約: https://disclosure2dl.edinet-fsa.go.jp/guide/static/submit/WZEK0030.html
- EDINET API機能利用規約: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140191.pdf
- EDINET API仕様書: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf
- JPO 特許情報取得API: https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html
- JPO 特許情報取得API利用規約: https://www.jpo.go.jp/system/laws/sesaku/data/document/api-provision/api-provision-kiyaku.pdf
- JPO API情報提供サイト: https://ip-data.jpo.go.jp/
- 調達ポータル ご利用にあたって: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html
- 調達ポータル 本システムについて: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/outline.html
- JETRO 利用規約・免責事項: https://www.jetro.go.jp/legal.html
