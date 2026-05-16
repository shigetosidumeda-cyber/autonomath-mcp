# AWS credit review 04: official source priority

作成日: 2026-05-15  
担当: official source priority  
状態: 追加20エージェントレビュー 4/20。実装なし。AWS実行なし。  
対象: NTA法人番号、インボイス、e-Gov、J-Grants、gBizINFO、e-Stat、EDINET、JPO、p-portal、JETRO、裁判所、行政処分、自治体PDF等の公的一次情報。

## 0. 結論

AWSクレジットで最優先に処理すべき公的sourceは、価値が高い順ではなく、次の順で決めるべきである。

1. `source_receipt`化しやすく、join keyが強く、規約境界が明確なsource。
2. P0 packetの根拠、会社同定、制度候補、no-hit安全性に直接効くsource。
3. PDF/OCRやHTML解析に計算費を使う価値があり、hash/metadata/抽出factとして残せるsource。
4. 価値は高いが、第三者権利、個人情報、API申請目的、添付PDF再配布、網羅性誤認のリスクが高いsource。

したがって、推奨優先順位は次の通り。

| Priority | Source group | AWS creditでの扱い |
|---|---|---|
| P0-A | NTA法人番号、NTAインボイス、e-Gov法令、e-Stat | 先にsnapshot、profile、receipt、no-hit contractを固める |
| P0-B | J-Grants、gBizINFO、p-portal公開情報 | API/公開メタデータ中心。添付PDFや元データ条件は分離 |
| P0-C | 行政処分、自治体PDF、省庁PDF、裁判所 | receipt価値は高いがno-hit誤用が危険。範囲付きscreenとして処理 |
| P1-A | EDINET、JPO | 公開metadataとID bridgeを優先。本文、XBRL、図面、公報全文はreview gate |
| P1-B | JETRO、その他政府系/準公的サイト | 初期はmetadata/hash_only。本文DB化や商用再配布はしない |

最も重要な設計判断:

- NTA法人番号を company identity spine として先に作る。
- インボイスは「登録状態を断定するsource」ではなく、時点付き登録情報とno-hit receiptのsourceとして扱う。
- e-Gov法令とe-Statは、出典表示と加工表示を満たせばreceipt化しやすい。
- J-Grants/gBizINFO/p-portalは価値が高いが、API規約、出典表示、第三者権利、添付PDF境界を分ける。
- EDINET/JPO/JETRO/裁判所/行政処分/自治体PDFは、本文や添付を売るのではなく、URL、ID、日付、hash、抽出fact、未確認範囲を売る。
- `no_hit`は全sourceで「当該source/snapshot/query/scopeでは未検出」だけを意味する。不在、未登録、処分歴なし、採択なし、リスクなしには変換しない。

## 1. 評価軸

各sourceは以下の5軸で評価する。

| Axis | 見るもの | 高評価の条件 |
|---|---|---|
| Product value | P0 packet、会社baseline、application strategy、DD、agent回答に効くか | 複数packetで再利用でき、ユーザーが支払う理由になる |
| Receipt ease | URL、ID、取得時刻、hash、snapshot、licenseを安定して残せるか | 公式API/bulk、安定ID、明確な更新日、schemaがある |
| No-hit clarity | 0件時に何を言えるかを安全に定義できるか | exact ID lookupや明確なscopeがある |
| License/terms risk | 商用利用、再配布、出典表示、第三者権利、個人情報、API目的のリスク | 出典表示と加工表示で正規化factを出せる |
| AWS fit | 短期Batch/OCR/Athenaで durable artifact に変換できるか | Parquet、JSONL、receipt、QA reportとして残せる |

`source_receipt化しやすさ` の目安:

| Grade | 意味 | 例 |
|---|---|---|
| A | 公式API/bulk、安定ID、規約境界が比較的明確 | NTA法人番号、e-Stat、e-Gov法令 |
| B | API/公開情報は使えるが、申請目的、個人情報、第三者権利、添付資料に注意 | インボイス、J-Grants、gBizINFO、p-portal |
| C | HTML/PDF中心。hash/metadata/抽出factは可能だが、網羅性や本文再配布に注意 | 行政処分、自治体PDF、裁判所 |
| D | 初期はmetadata/hash_only。本文利用や商用再配布はreview_required | JETRO本文/レポート、EDINET本文、JPO図面/公報全文 |

## 2. Source Priority Matrix

| Rank | Source | Priority | 主な価値 | Receipt ease | no-hit意味 | License/terms risk | AWS処理対象 |
|---:|---|---|---|---|---|---|---|
| 1 | NTA法人番号 | P0-A | 法人同定、名称/所在地、変更/閉鎖、全source joinの軸 | A | 指定法人番号または検索条件で未検出。法人不存在ではない | API ID、出典表示、保証否認、大量アクセス禁止 | bulk/diff snapshot、identity parquet、change events、positive/no-hit receipts |
| 2 | NTAインボイス | P0-A | T番号照合、取引先確認、会社baseline、CSV安全join | B | 指定T番号等で未検出。未登録確定ではない | 個人事業者情報、API ID、保証否認、時点差 | registrant snapshot、T番号正規化、no-hit ledger、privacy gate |
| 3 | e-Gov法令 | P0-A | 法令根拠、条文参照、制度/規制packetの根拠 | A | 指定法令/条/時点で未検出。法的根拠不存在ではない | ロゴ等除外、別規約コンテンツ、現行/過去時点誤認 | law snapshot、article claim refs、law version/freshness report |
| 4 | e-Stat | P0-A | 地域、産業、人口、統計背景、制度候補の補助根拠 | A | 指定統計表/地域/系列で未検出。統計対象外断定ではない | appId、クレジット表示、個別統計注記、秘匿値 | stats parquet、unit normalization、stat receipts |
| 5 | J-Grants | P0-B | 補助金候補、締切、対象、申請窓口、制度ID | B | 条件に合うAPI record未検出。制度なし/申請不可ではない | 出典/加工表示、添付PDF、自治体/府省資料の別権利 | API snapshot、program rounds、deadline/amount/eligibility candidate receipts |
| 6 | gBizINFO | P0-B | 法人活動情報、認定、表彰、調達、補助金、職場情報 | B | 法人活動情報カテゴリで未検出。活動不存在ではない | 事前申請/API token、申請目的、元データ条件継承 |法人番号join、signal parquet、category receipts、identity mismatch ledger |
| 7 | p-portal/GEPS | P0-B | 調達案件、公告、締切、落札/事業者情報候補 | B/C | 接続済み範囲で未検出。入札参加なし/落札歴なしではない | 利用規約PDF、第三者権利、ログイン後情報、添付資料 | public notice metadata、deadline extraction、hash-only attachment ledger |
| 8 | 行政処分/監督官庁notice | P0-C | DD、購買審査、risk screen、会社baselineの確認範囲 | C | 接続済みsource/期間/同定条件で未検出。処分歴なしではない | 公表期間、同名、PDF、自治体差、個人名 | public notices、entity candidates、multi-source no-hit checks |
| 9 | 自治体PDF/省庁PDF | P0-C | 地域制度、補助金、許認可、締切、必要書類、除外条件 | C | 対象PDF集合で未検出。制度/要件不存在ではない | PDFごとの著作権、古い公募、OCR誤り、第三者資料 | OCR/parse、page hash、extracted fact candidates、review backlog |
| 10 | 裁判所裁判例 | P0-C/P1 | 法令解釈、裁判例参照、legal context | C | 裁判例検索に未掲載。裁判例なし/法的根拠なしではない | 全判決網羅でない、匿名化/置換、画像/図表、省略 | metadata/hash、case ID/date/court receipts、no-hit scope ledger |
| 11 | EDINET | P1-A | 上場/開示metadata、EDINET code bridge、財務fact候補 | B/D | 対象期間/EDINET codeで未検出。開示義務なしではない | API推奨、スクレイピング禁止、提出書類の第三者権利、投資助言誤認 | filing metadata、docID/hash、code bridge、extracted numeric fact review |
| 12 | JPO | P1-A | 特許/商標/意匠metadata、知財signal、法人活動補助 | B/D | 対象API/番号で未検出。権利なしではない | 試行提供、利用登録、ID/password、上限、図面/明細書権利 | bibliographic/status metadata、application number receipts、API lifecycle report |
| 13 | JETRO | P1-B | 海外展開、見本市、調達/商談、国別情報候補 | D | JETRO内で未検出。海外機会なしではない | 事前許可なし複製/販売/頒布/変更不可の範囲が強い | metadata/hash_only、URL/title/date/region catalog、review_required report |
| 14 | その他自治体HTML | P1-B | 地域制度/入札/処分のロングテール | C/D | 接続済み自治体で未検出。自治体全体の不存在ではない | robots、独自規約、PDF/Word添付、更新停止 | allowlist後にlimited crawl、metadata/hash、parse confidence |

## 3. P0-A: Identity And High-Trust Backbone

### 3.1 NTA法人番号

優先理由:

- すべての会社系sourceのjoin keyになる。
- 法人番号、商号/名称、所在地、閉鎖/変更履歴は company baseline の最初の行になる。
- 名称検索だけの行政処分、自治体PDF、採択PDFを扱う前に、同名/旧商号/所在地の曖昧性を下げられる。

source_receipt化:

- `receipt_kind=positive_source`
- `claim_kind=company_identity`
- `source_id=nta_houjin`
- `subject_id=corporation_number`
- 必須: 法人番号、商号又は名称、所在地、変更日、閉鎖状態、取得URL、取得日時、snapshot_id、content_hash、出典/加工表示、API規約確認日時。

no-hit:

- exact法人番号 no-hit は「そのsnapshot/APIでは正規化後法人番号に一致するrecordを確認できない」。
- 名称/所在地検索 no-hit は「十分な候補を確定できない」。
- どちらも法人不存在、登記不存在、営業実態なしを意味しない。

AWS対象:

- bulk/diffをsource lakeへ取得し、Parquet化する。
- 変更履歴、閉鎖、同名衝突、住所正規化失敗をledger化する。
- private CSVと直接joinしない。ユーザー確認済み法人番号だけをjoin keyにする。

### 3.2 NTAインボイス

優先理由:

- 会計CSV、取引先確認、会社folder、BPO/税理士向け価値に直結する。
- T番号 exact lookup は no-hit contract を定義しやすい。

source_receipt化:

- `positive_source`: 登録番号、氏名/名称、所在地、登録年月日、取消/失効日、取得日時。
- `no_hit_check`: 正規化後T番号、query hash、snapshot、result_count=0、`support_level=no_hit_not_absence`。
- 個人事業者の氏名、屋号、住所はpublic packetでは原則抑制またはreview_required。

no-hit:

- T番号が見つからないことは「未登録確定」ではない。
- 入力ミス、時点差、取消/失効、登録予定、snapshot stale、個人事業者の公開範囲を常に残す。

AWS対象:

- registrant snapshot、差分、T番号正規化、no-hit safety audit。
- 法人番号とのbridgeはconfidenceを持たせる。bridge不明は `identity_ambiguity_unresolved`。

### 3.3 e-Gov法令

優先理由:

- 補助金、許認可、税制、労務、申請書類の根拠として複数packetで再利用できる。
- 公式API/bulkがあり、条番号、法令番号、施行日をreceipt化しやすい。

source_receipt化:

- `claim_kind=legal_basis`
- 必須: 法令ID/法令番号、法令名、条番号、項号、施行日、取得API、XML/PDF hash、API spec version、snapshot_id。

no-hit:

- 指定法令/条/時点で見つからないだけ。
- 廃止、未施行、条ずれ、表記揺れ、現行/過去時点違いを区別する。

AWS対象:

- 法令snapshot、条文単位claim、施行日/freshness ledger、古い条文参照のstale report。

### 3.4 e-Stat

優先理由:

- 地域、産業、人口、事業所数などの背景factを低リスクに作れる。
- 統計表ID、地域コード、時点、単位が安定しており、receipt化しやすい。

source_receipt化:

- 必須: 統計表ID、系列、地域コード、時点、単位、値、更新日、取得日時、appId使用、クレジット表示。
- 秘匿値、欠損、速報/確報、改定をclaimに含める。

no-hit:

- 指定統計表/地域/系列/時点で未検出。
- 地域に該当統計が存在しない、産業がない、統計的にゼロという意味ではない。

AWS対象:

- 地域/産業別Parquet、unit normalization、metadata receipts、freshness breach report。

## 4. P0-B: High Value But Conditional Sources

### 4.1 J-Grants

優先理由:

- `application_strategy`、`client_monthly_review`、制度候補提示に直接効く。
- 補助金ID、募集期間、対象地域、制度名、所管などが機械処理しやすい。

receipt化しやすいfact:

- 補助金ID、制度名、タイトル、募集開始/終了、対象地域、補助上限、所管、公式URL、API version。

注意するfact:

- 公募要領PDF全文、自治体/府省の添付資料、申請者情報、採択可能性。
- API上にあることは「申請可能」ではない。募集終了、要件未充足、電子申請不可等を分ける。

AWS対象:

- API snapshot、program_rounds、deadline extraction、amount caveat、requirements candidates。
- 添付PDFはsource別licenseが確認できるまで `hash_only` または `metadata_only`。

### 4.2 gBizINFO

優先理由:

- 法人番号を軸に、法人基本情報、届出/認定、表彰、財務、特許、調達、補助金、職場情報を横断できる。
- 会社baselineやDDで「公開活動signal」を増やせる。

制約:

- REST API v2は事前利用申請とAPIトークンが必要。
- 申請目的、API/ダウンロード規約、元データの条件継承をreceiptに残す必要がある。

no-hit:

- gBizINFOの特定カテゴリにrecordがないだけ。
- 認定なし、補助金なし、調達なし、事業実態なしを意味しない。

AWS対象:

- 法人番号join、category別signal、source owner、元データURL、identity mismatch ledger。
- API tokenや申請情報はpublic artifactに出さない。

### 4.3 p-portal / GEPS

優先理由:

- 調達公告、締切、発注機関、落札実績等は、B2G/営業/行政調達向けに価値が高い。
- 調達ポータルの利用条件は商用利用可能、出典/加工表示、第三者権利確認、CC BY互換が明示されている。

制約:

- 利用規約PDF、少額物品調達規約、ログイン後機能、電子証明書/登録が絡む領域を分ける。
- 添付仕様書や入札説明書は第三者権利や個別条件が残るため、初期はmetadata/hash中心。

no-hit:

- 接続済みsource、期間、機関、案件区分で未検出。
- 入札参加なし、落札歴なし、契約なしを意味しない。

AWS対象:

- 公開検索範囲のnotice metadata、締切、機関、案件URL、添付hash。
- ログイン後、電子証明書、事業者管理、非公開契約情報は対象外。

## 5. P0-C: PDF, Notice, Court, Enforcement Sources

### 5.1 行政処分/監督官庁notice

優先理由:

- DD、購買、金融、BPO、士業の「確認範囲」価値が大きい。
- positive hitは強いが、no-hit誤用リスクが最も高い。

source_receipt化:

- positive: 公表機関、処分日、公表日、対象名、許認可番号、法人番号があれば法人番号、文書URL、PDF/HTML hash、抽出位置。
- no-hit: checked_sources、対象期間、検索語、同定条件、未接続source、検索方式、snapshot。

禁止表現:

- 処分歴なし。
- 違反なし。
- 安全。
- 反社でない。
- 行政上問題なし。

AWS対象:

- allowlist済み省庁/自治体noticeのHTML/PDF取得。
- entity candidate extraction。
- no-hit screen ledger。
- 同名/旧称/所在地曖昧性のreview queue。

### 5.2 自治体PDF/省庁PDF

優先理由:

- J-Grantsに載らない地域制度、締切、必要書類、除外条件、補助対象経費が多い。
- AWS creditをOCR/parseに使う価値がある。

receipt化:

- document-level receipt: URL、自治体、部署、公開日、取得日、content_hash、ページ数、retention class。
- fact-level receipt: page/section、抽出テキストhash、confidence、support_level、review_required。

no-hit:

- 対象PDF集合/検索語/対象期間では見つからない。
- 自治体に制度がない、要件がない、締切がないとは言えない。

AWS対象:

- PDF fetch、OCR、table extraction、deadline/amount/eligibility/exclusion/required_docs candidates。
- 低confidenceや古いPDFは `source_receipt_incomplete` または `freshness_stale_or_unknown`。

### 5.3 裁判所裁判例

優先理由:

- legal context、裁判例参照、条文解釈の補助として価値がある。
- 裁判所自身が、掲載判例は全判決等ではないこと、匿名化/記号置換/文字変換/画像省略等があることを明示している。

receipt化:

- 事件番号、裁判年月日、裁判所、事件種別、URL、PDF/HTML hash、取得日時、検索条件。

no-hit:

- 裁判例検索で未掲載または検索条件に一致しない。
- 判決が存在しない、同種事件がない、法的根拠がないという意味ではない。

AWS対象:

- metadata/hash、case reference extraction、search scope ledger。
- 判決本文の大規模再配布や長文引用は避ける。

## 6. P1-A: Specialized Official Metadata

### 6.1 EDINET

優先理由:

- 上場/開示会社のmetadata、EDINET code、提出書類、公開財務factの橋渡しに有用。
- 会社baselineや監査前段資料で価値がある。

制約:

- EDINETはAPI利用を優先し、Webスクレイピングは原則避ける。
- ウェブサイト規約はPDL1.0準拠の要素がある一方、EDINETタクソノミ、作成ツール、提出書類、XBRL、監査報告書等は別権利/第三者権利を分ける。
- 投資助言、格付、与信判断に見える出力は禁止。

receipt化:

- 初期は `metadata_only`。
- 書類管理番号、EDINETコード、提出者名、提出日、docType、API URL、XBRL/PDF hashを対象にする。

AWS対象:

- 書類metadata snapshot、EDINET code bridge、法人番号候補、hash ledger。
- XBRL/本文抽出はreview gate後に `derived_fact` として扱う。

### 6.2 JPO

優先理由:

- 特許、意匠、商標の公開metadataは、企業活動signalや知財DDに有用。

制約:

- 特許情報取得APIは試行提供で、利用登録、利用規約、利用の手引き遵守、アクセス上限がある。
- 国内APIは特許、意匠、商標出願情報が対象で、実用新案は除外される。
- OPD-APIは新規申込終了状態を確認して扱う。
- 図面、明細書全文、公報本文、審査書類、商標/意匠画像はreview_required。

receipt化:

- 初期は `metadata_only` またはreview後 `derived_fact`。
- 出願番号、公開/登録番号、権利種別、出願日、公開日、ステータス、API取得日時、response hash。

AWS対象:

- bibliographic/status metadata、application number receipts、法人名/法人番号bridge候補。
- API資格情報やID/passwordはpublic artifactに出さない。

## 7. P1-B: JETRO And Similar Semi-Open Public Sites

JETROは政府系機関として価値は高いが、初期source priorityでは上位にしない。

理由:

- JETRO利用規約は、コンテンツの知的財産権がJETROまたは表示された所有者に帰属し、事前許可なく複製、販売、出版、頒布、変更、表示できない範囲が強い。
- 調査レポート、記事、動画、画像、会員/購読サービス、見本市DBなどで利用条件が分かれる。
- AWSで本文DB化すると、短期価値より法務リスクが勝ちやすい。

初期方針:

- `license_boundary=hash_only|metadata_only|review_required`
- title、official URL、公開日、地域、source owner、取得日時、hashだけを残す。
- 本文要約、レポートPDF解析、長期保存、商用プロダクトへの組み込みは個別review後。

no-hit:

- JETRO内または特定サービス内で見つからないだけ。
- 海外展開機会なし、規制情報なし、展示会なしを意味しない。

AWS対象:

- metadata catalog、URL/hash ledger、review backlog。
- 本文/画像/動画/PDFのbulk保存は対象外。

## 8. `source_receipt` Contract By Source Type

### 8.1 Common fields

全sourceで必須:

```json
{
  "source_receipt_id": "sr_...",
  "receipt_kind": "positive_source | no_hit_check | stale_check | license_check | schema_check",
  "source_id": "stable_source_id",
  "source_family": "corporation | invoice | law | program | procurement | enforcement | court | filing | patent | statistics",
  "source_url": "official_url",
  "canonical_source_url": "canonical_official_url",
  "publisher": "official_owner",
  "retrieval_method": "api | bulk | html | pdf | manual_review",
  "source_fetched_at": "2026-05-15T00:00:00+09:00",
  "last_verified_at": "2026-05-15T00:00:00+09:00",
  "corpus_snapshot_id": "corpus-...",
  "content_hash": "sha256:...",
  "license_boundary": "attribution_open | derived_fact | metadata_only | hash_only | review_required",
  "support_level": "direct | derived | weak | no_hit_not_absence",
  "claim_refs": [],
  "used_in": [],
  "known_gaps": []
}
```

### 8.2 Positive receipt minimums

| Source family | Minimum identifier | Minimum evidence locator | Required caveat |
|---|---|---|---|
| corporation | 法人番号 | API/bulk snapshot, update date | 国税庁保証ではない、加工表示 |
| invoice | T番号 | API/bulk snapshot, status date | 未検出は未登録確定ではない、個人情報注意 |
| law | 法令ID/条番号 | API URL, XML hash, effective date | 現行/過去時点を分ける |
| program | 補助金ID/制度URL | API/doc URL, deadline field/page | 申請可否/採択可能性ではない |
| statistics | 統計表ID/系列/地域 | API endpoint, table update date | 単位、速報/確報、秘匿 |
| procurement | 案件ID/公告URL | HTML/PDF URL, agency, deadline | 参加可否/落札歴判断ではない |
| enforcement | 公表URL/処分ID相当 | public notice URL, date, entity locator | 処分歴なし判断ではない |
| court | 事件番号/裁判年月日 | court page/PDF hash | 全判決網羅ではない |
| filing | 書類管理番号/EDINET code | API URL, docType, submit date | 投資/与信判断ではない |
| patent | 出願番号 | API response hash, status date | 権利有効性の最終判断ではない |

### 8.3 No-hit receipt minimums

`no_hit`は必ず専用receiptにする。

```json
{
  "receipt_kind": "no_hit_check",
  "support_level": "no_hit_not_absence",
  "source_id": "source_id",
  "query_kind": "exact_identifier | fuzzy_name | bridge_lookup | multi_source_screen",
  "query_hash": "sha256:...",
  "query_summary_public": "masked_or_safe_summary",
  "checked_scope": {
    "source_urls": [],
    "date_range": "scope_or_null",
    "jurisdiction": "JP_or_local",
    "filters": []
  },
  "matched_record_count": 0,
  "status": "no_hit",
  "no_hit_means": "対象source/snapshot/query/scopeでは該当recordを確認できなかった",
  "no_hit_does_not_mean": "不存在、登録なし、処分歴なし、採択なし、安全、リスクなし",
  "known_gaps": [
    {"code": "no_hit_not_absence"}
  ]
}
```

## 9. License And Terms Risk Sorting

| Boundary | 初期source | Public receipt | Public output | Raw retention | Review rule |
|---|---|---:|---|---|---|
| `attribution_open` | NTA法人番号、e-Gov法令、e-Stat、p-portalの規約適用範囲 | 可 | 正規化fact、短いmetadata、出典/加工表示 | 条件付き可 | 出典表示/加工表示/保証否認を機械可読化 |
| `derived_fact` | インボイス、J-Grants、gBizINFO | 可 | 正規化fact、URL、hash、時点 | normalized中心 | 個人情報、申請目的、添付資料を分ける |
| `metadata_only` | EDINET、JPO、p-portal添付、裁判所本文 | 限定可 | ID、タイトル、日付、URL、hash | hashまたはrestricted | 本文/図面/XBRL/PDFは個別review |
| `hash_only` | JETROレポート、権利不明PDF、自治体添付の一部 | 限定可 | URL、取得日時、hash、review_required reason | rawなしまたは短期 | 本文要約や再配布はしない |
| `review_required` | 規約未確認、新規自治体、会員/ログイン後 | 不可 | known_gapのみ | 禁止 | source_profile完了までAWS fetchしない |

Fail closed rules:

- 公式URLとterms URLがないsourceは `review_required`。
- API規約とサイト規約が別の場合は両方保存し、厳しい方を採用する。
- 第三者権利があるPDF/画像/図表は `metadata_only` 以下に落とす。
- 個人事業者、個人名、住所、屋号は公式公開でもpublic packetでは抑制する。
- raw payload bulk再配布は初期禁止。
- sourceの保証/承認を示唆する文言は禁止。

## 10. AWS Processing Targets

### 10.1 AWSで処理すべきもの

| Workload | 対象source | 成果物 |
|---|---|---|
| Official source profile sweep | 全source | `source_profile_delta.jsonl`, `license_boundary_report.md` |
| Bulk/API snapshot | NTA法人番号、インボイス、e-Gov、e-Stat、J-Grants、gBizINFO、EDINET metadata | `normalized/*.parquet`, `source_document_manifest.parquet` |
| Receipt generation | 全P0/P1 | `source_receipts.jsonl`, `claim_refs.jsonl`, `claim_source_link.parquet` |
| No-hit ledger | インボイス、法人番号、行政処分、調達、裁判所、採択履歴 | `no_hit_checks.jsonl`, `no_hit_safety_audit.md` |
| PDF/OCR extraction | 自治体PDF、省庁PDF、調達添付、処分PDF | `pdf_extracted_facts.parquet`, `review_backlog.jsonl` |
| Identity join | NTA法人番号、gBizINFO、EDINET、JPO、J-Grants採択候補 | `identity_edges.parquet`, `identity_mismatch_ledger.jsonl` |
| Freshness and schema audit | 全source | `freshness_report.md`, `schema_drift_report.md` |
| License exposure scan | 全source | `license_boundary_exposure.md`, `quarantine.jsonl` |
| Packet fixture materialization | P0 packet inputs | `company_public_baseline`, `application_strategy`, `source_receipt_ledger` fixtures |

### 10.2 AWSで処理しないもの

- AWSアカウント操作、CLI実行、Batch投入、Terraform/CDK作成。今回レビューの範囲外。
- API申請、appId/API key/token/ID/passwordの取得や保存。
- 規約未確認sourceのbulk fetch。
- JETRO、EDINET、JPO、裁判所、自治体PDFの本文大量再配布。
- ログイン後、会員、購読、電子証明書、private tenant data。
- private CSV raw行、摘要、取引先名、金額明細。
- no-hitを使った「問題なし」「未登録」「処分歴なし」判定。
- 採択可能性、税務判断、法的判断、投資判断、与信判断。

## 11. Recommended AWS Job Order

### Phase 1: profile and safe backbone

1. J01 Official source profile sweep。
2. J02 NTA法人番号 snapshot。
3. J03 NTAインボイス snapshot/no-hit。
4. J04 e-Gov法令 snapshot。
5. J11 e-Stat statistics enrichment。
6. J12 source receipt completeness audit。

理由:

- `source_profile`とidentity spineがないままPDF/OCRへ進むと、claimがreceiptに接続できない。
- P0-Aはreceipt化しやすく、早期にpacket fixtureへ使える。

### Phase 2: program, business signal, procurement

1. J05 J-Grants/public program acquisition。
2. J07 gBizINFO public business signals join。
3. J09 procurement/public tender acquisition。
4. J13 claim graph dedupe/conflict analysis。

理由:

- P0-Bは価値が高いが、source別licenseとjoin confidenceを前提にする。
- program/procurementはdeadlineが時間依存なのでfreshness ledgerが必要。

### Phase 3: notice, PDFs, court, specialized metadata

1. J06 Ministry/municipality PDF extraction。
2. J10 Enforcement/sanction/court-public notice sweep。
3. J08 EDINET metadata snapshot。
4. JPO metadata probeをJ08相当または別jobに分離。

理由:

- 計算費を使う価値は高いが、low-confidence factが増えやすい。
- no-hitとpositive hitを厳密に分ける必要がある。

### Phase 4: output QA

1. no-hit safety audit。
2. license boundary exposure scan。
3. private leak scan。
4. packet/proof fixture materialization。
5. final export/checksum。

## 12. Source-Specific No-Hit Copy

| Source | Safe copy | Forbidden copy |
|---|---|---|
| NTA法人番号 | 指定条件では法人番号recordを確認できませんでした | 法人は存在しません |
| インボイス | 指定T番号は対象snapshotで確認できませんでした | 未登録です、請求書は不適格です |
| e-Gov法令 | 指定法令/条/時点では確認できませんでした | 法的根拠はありません |
| J-Grants | 条件に合うAPI recordを確認できませんでした | 利用可能な補助金はありません |
| gBizINFO | 対象カテゴリの法人活動recordを確認できませんでした | 活動実績はありません |
| e-Stat | 指定統計表/地域/系列では確認できませんでした | 統計上ゼロです |
| EDINET | 対象期間/識別子では開示metadataを確認できませんでした | 開示義務はありません、財務情報はありません |
| JPO | 対象API/番号ではrecordを確認できませんでした | 権利はありません |
| p-portal | 接続済み範囲では案件recordを確認できませんでした | 入札参加/落札歴はありません |
| 裁判所 | 裁判例検索では該当掲載を確認できませんでした | 裁判例はありません |
| 行政処分 | 接続済みsource/期間/同定条件では処分recordを確認できませんでした | 処分歴なし、違反なし、安全です |
| 自治体PDF | 対象PDF集合では該当記載を確認できませんでした | 自治体制度はありません |

## 13. Main Risks And Controls

| Risk | Impact | Control |
|---|---|---|
| no-hitを不存在に変換 | DD、税務、取引判断で重大事故 | `support_level=no_hit_not_absence` mandatory、forbidden-claim scan |
| 規約未確認sourceのraw保存 | 商用利用/再配布違反 | `license_boundary=review_required` はfetchしない |
| PDF本文/画像/図面の再配布 | 著作権/第三者権利リスク | hash/metadata/short extracted factのみ |
| 個人事業者インボイス情報の露出 | 個人情報保護/信頼毀損 | public packet抑制、tenant-scoped handling |
| EDINET/JPO/JETRO本文の過剰利用 | 第三者権利/投資助言/規約違反 | metadata_only default、legal review gate |
| 行政処分の同名誤結合 | 名誉毀損/誤判定 | 法人番号、所在地、許認可番号、confidence、review queue |
| 自治体PDFの古さ | 期限切れ制度を最新として提示 | `freshness_stale_or_unknown`、published_at/deadline抽出 |
| API tokenやappId露出 | credential incident | secretsはAWS artifactへ出さない |
| AWS費用がdurable artifactに変換されない | クレジット浪費 | Parquet/JSONL/MD/checksum exportをjob success条件にする |

## 14. Acceptance Criteria For This Lane

このreview laneの完了条件:

- P0-A/P0-B/P0-C/P1の優先順位がsource単位で説明できる。
- 各sourceで、価値、receipt化しやすさ、no-hit意味、license/terms risk、AWS処理対象が整理されている。
- AWSで処理すべきものと処理しないものが明確。
- source_receipt contractに必要なfieldが定義されている。
- no-hitのsafe copyとforbidden copyがsource別にある。
- 実装、AWS CLI/API実行、ジョブ投入を行っていない。

## 15. References

Local planning documents used:

- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/aws_credit_data_foundation_agent.md`
- `docs/_internal/aws_credit_data_acquisition_jobs_agent.md`
- `docs/_internal/official_source_acquisition_plan_deepdive_2026-05-15.md`
- `docs/_internal/official_source_license_terms_deepdive_2026-05-15.md`
- `docs/_internal/no_hit_semantics_edge_cases_deepdive_2026-05-15.md`

Official anchors checked on 2026-05-15:

- NTA法人番号 Web-API利用規約: https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html
- NTAインボイス Web-API利用規約: https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html
- e-Gov利用規約: https://www.e-gov.go.jp/terms
- J-Grants API docs: https://developers.digital.go.jp/documents/jgrants/api/
- gBizINFO API: https://content.info.gbiz.go.jp/api/index.html
- e-Stat API利用規約: https://www.e-stat.go.jp/api/terms-of-use
- EDINET利用規約: https://disclosure2dl.edinet-fsa.go.jp/guide/static/submit/WZEK0030.html
- JPO 特許情報取得API: https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html
- p-portal ご利用にあたって: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html
- JETRO利用規約: https://www.jetro.go.jp/legal.html
- 裁判所 裁判例検索: https://www.courts.go.jp/hanrei/search1/index.html?lang=ja
