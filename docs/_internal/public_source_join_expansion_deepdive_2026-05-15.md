# Public Source Join / Source Expansion Deep Dive 2026-05-15

担当: 公的データ join / source expansion  
範囲: 実装前計画のみ。実装コード・既存データ・既存ドキュメントは変更しない。  
前提: CSVや会社名/法人番号/制度情報と、公的一次情報を突合して成果物価値を作る。ハルシネーション抜き、一次情報ベース、`no_hit` は absence ではない。

## 0. 結論

最初に接続すべき P0 は、会社同定と成果物の信頼性を支える `NTA法人番号 -> NTAインボイス -> p-portal/JETRO調達 -> EDINET -> gBizINFO conditional` の順にする。P1 は `jGrants/e-Gov/e-Stat/JPO/行政事業レビュー/監督官庁処分` を追加し、会社DD・顧問先月次レビュー・補助金候補・調達/採択/法令リンクの価値を上げる。

設計上の重要点は次の3つ。

1. `法人番号` は最優先の spine だが、会社名CSVだけでは同名異法人を解けない。名称 join は candidate 生成であり、公開 fact ではない。
2. `no_hit` は「接続した source / query / snapshot / filter では該当レコードを返さなかった」だけを意味する。登録なし、処分なし、安全、存在しない、を意味しない。
3. すべての派生 fact は `source_receipt_id` に戻れるようにし、検索条件・snapshot・content hash・ライセンス・no_hit receipt を同じ ledger に残す。

## 1. P0 source list

| priority | source_id | 公的ソース | 主なID | 取得対象 | 更新頻度・鮮度 | no_hit の意味 | 利用制約 / 注意 | source_receipt 要点 |
|---|---|---|---|---|---|---|---|---|
| P0 | `nta_corporate_number` | 国税庁 法人番号公表サイト / 法人番号システム Web-API | `corporate_number` / `houjin_bangou` 13桁、商号、所在地、変更履歴 | 法人基本3情報、商号・所在地変更、閉鎖等、フリガナ、検索対象除外法人 | APIは法人番号指定、期間指定、法人名指定。期間指定は最大50日。全件はAPIでなく基本3情報ダウンロードを使う。 | exact法人番号 no_hit は「そのAPI条件で公表対象が返らない」。未公表団体、閉鎖、検索対象除外、ID誤り、snapshot遅延を含む可能性。名称 no_hit は同定失敗にすぎない。 | app ID 必須。Web-API利用規約同意。公開サービスでは国税庁Web-API由来だが国税庁保証ではない旨の明示が必要。 | `source_url`, `api_version`, `request_params`, `response_status`, `fetched_at`, `content_hash`, `app_id_hash`, `license_notice`, `result_count`, `no_hit_reason=query_returned_zero` |
| P0 | `nta_invoice_registrants` | 国税庁 適格請求書発行事業者公表サイト / Web-API / 公表情報DL | `registration_number` T+13桁、法人は `houjin_bangou` に正規化可、登録年月日、失効年月日 | インボイス登録状態、氏名/名称、所在地、登録/変更/失効差分 | 公表情報DLは前月末時点の全件と変更・追加・失効等の差分。Web-APIは登録番号指定・期間指定等。 | no_hit は「指定T番号/期間条件で返らない」。免税事業者、個人事業者非公開範囲、登録取消/失効、T番号誤り、snapshot遅延を区別できない場合がある。 | app ID / 承認が必要。Web-API利用規約に同意。サービス提供時は国税庁保証ではない旨の明示が必要。法人番号APIのIDだけではインボイスAPI不可の場合がある。 | `registration_number`, `normalized_houjin_bangou`, `snapshot_month_end`, `delta_range`, `record_status`, `source_file_url`, `pgp_signature_present`, `resource_definition_version`, `no_hit_scope` |
| P0 | `p_portal_procurement_awards` | 調達ポータル | `buyer_org_code`, `buyer_houjin_bangou` where present, `winner_houjin_bangou` where present, 案件ID/落札実績ID | 事業者情報、落札実績オープンデータ、調達案件 | 調達ポータル上で調達情報検索、事業者情報検索、落札実績情報オープンデータDLを提供。更新は公開・落札実績の掲載に追随。 | no_hit は「調達ポータル掲載対象・検索条件・期間では該当なし」。調達が無い、他システム掲載、名称揺れ、非対象調達、掲載遅延を区別しない。 | 画面/API/CSVの利用条件を source profile で固定。法人番号がない落札者名は fuzzy join 扱い。 | `dataset_name`, `published_at_or_downloaded_at`, `period`, `query_filters`, `buyer_id`, `winner_id`, `award_id`, `amount`, `hash`, `terms_url`, `join_confidence` |
| P0 | `jetro_gov_procurement_db` | JETRO 政府公共調達データベース | 官報掲載日、調達機関コード、公告種別、案件名、落札者名 | WTO政府調達協定・日EU/日英EPA対象の公告/公示、落札者等公示 | 国・独法は原則官報掲載日当日15時以降から翌営業日中、地方等は原則翌営業日12時以降同日中。中央省庁/独法は過去5年度分検索。 | no_hit は「同DB収録対象・公告種別・期間では該当なし」。小額調達、対象外機関、官報未掲載、別システム掲載は否定できない。 | 各案件詳細は各調達機関が正本。DBは単一窓口・検索補助として扱う。 | `kanpo_date`, `notice_type`, `procurement_agency_code`, `search_filters`, `database_url`, `detail_url_if_available`, `retrieved_at`, `coverage_note` |
| P0 | `edinet_filings` | 金融庁 EDINET API v2 | `docID`, `edinetCode`, `secCode`, `JCN`, `filerName`, `docTypeCode`, `submitDateTime` | 有価証券報告書、訂正報告書、四半期、半期、大量保有等の提出書類一覧と書類取得 | 日付指定の書類一覧。提出・取下げ・訂正により過去日付の一覧も更新される。 | JCN no_hit は「EDINET提出者一覧/提出書類にJCNがない」。非上場、開示義務なし、JCN未設定、上場持株/子会社違いを含む。docID no_hit は取得期間・保存期間・API条件の問題もある。 | Subscription-Key 必須。書類取得形式ごとの利用条件とレート配慮が必要。XBRL/CSV派生値は原本要素・contextを receipt に残す。 | `docID`, `edinetCode`, `JCN`, `docTypeCode`, `period`, `submitDateTime`, `api_endpoint`, `api_params`, `xbrl_file_hash`, `taxonomy_version`, `element_id`, `context_id` |
| P0 | `gbizinfo_corporate_activity_conditional` | Gビズインフォ REST API / DL | `corporate_number`, 法人名、所在地、活動種別ID | 法人基本、届出・認定、表彰、財務、特許、調達、補助金、職場情報 | source別の更新頻度を持つ集約。API利用は事前申請・APIトークン。 | no_hit は「gBizINFOの保有・更新済み範囲で該当なし」。上流 source に存在しない、未連携、更新遅延、トークン/条件エラーを区別しない。 | 集約系なので upstream_source と license を record ごとに保存。gBizINFOを正本にしすぎず、可能なら上流直 receipt を canonical にする。 | `gbiz_endpoint`, `api_token_hash`, `corporate_number`, `activity_kind`, `upstream_source`, `upstream_record_id`, `gbiz_updated_at`, `cache_age`, `terms_url`, `redistribution_note` |

## 2. P1 source list

| priority | source_id | 公的ソース | 主なID | 取得対象 | 更新頻度・鮮度 | no_hit の意味 | 利用制約 / 注意 | source_receipt 要点 |
|---|---|---|---|---|---|---|---|---|
| P1 | `jgrants_public_subsidies` | デジタル庁 Jグランツ public API | `subsidy_id`, `name`, `title`, `application_deadline`, 添付資料URL | 公募中/公開補助金、制度詳細、添付公募要領 | API v1/v2で補助金一覧・詳細。公開/募集状態に追随。 | no_hit は「公開API条件で補助金が返らない」。過去公募、自治体独自サイト、Jグランツ非掲載、キーワード不一致は否定しない。 | 補助金本文の要件判定は添付PDF等の一次資料 receipt が必要。API summary だけで適合断定しない。 | `subsidy_id`, `api_version`, `endpoint`, `query`, `result_count`, `attachment_urls`, `deadline`, `fetched_at`, `source_doc_hash` |
| P1 | `egov_laws_api_xml` | e-Gov 法令API / 法令XML | `law_id`, `law_num`, `law_revision_id`, article/paragraph/item | 法令メタ、条文、改正履歴、条文構造 | 法令データはAPI/XML。ドキュメントはα版で常時最新保証なし。 | no_hit は「法令ID/検索語/時点で解決不能」。廃止法令、未施行改正、名称略称、条文移動を否定しない。 | 法律判断ではなく根拠条文へのリンク。条文抽出は revision と施行日を明示。 | `law_id`, `law_revision_id`, `effective_date`, `article_path`, `xml_hash`, `api_url`, `selector`, `retrieved_at`, `cc_by_notice` |
| P1 | `estat_api` | e-Stat API | `statsDataId`, `statsCode`, `area_code`, `cat01...`, `time_code` | 政府統計、地域・産業・人口・小地域/メッシュ統計 | APIは統計表情報、メタ情報、統計データ、データカタログ等。`updatedDate` で更新日指定可。 | no_hit は「統計表/メタ/地域/分類条件でセルが無い」。0値、秘匿、未公表、分類違いを区別する必要。 | appId 必須。統計値は単位、時点、秘匿記号、推計/実測を保持。CSV会社factとは直接同一 entity ではなく cohort 付与。 | `statsDataId`, `statsCode`, `dimension_codes`, `unit`, `time`, `area_code`, `cell_value_raw`, `special_symbol`, `updatedDate`, `api_params` |
| P1 | `jpo_patent_info_api_or_bulk` | 特許庁 特許情報取得API / 特許情報標準データ | 出願番号、公開番号、登録番号、商標登録番号、出願人/権利者名 | 特許・意匠・商標の出願/登録/経過/書誌 | 特許情報標準データは更新日単位のバルクで、開庁日に発行、原則翌営業日反映。APIは試行提供・利用者登録・アクセス上限あり。 | no_hit は「対象範囲/番号/名義検索で返らない」。権利移転、表記揺れ、共同出願、実用新案除外、未公開期間を否定しない。 | APIは試行段階で登録必須。会社名 join は法人番号がないため高リスク。公開成果物は番号 exact または高信頼名寄せのみ。 | `application_number`, `publication_number`, `registration_number`, `right_type`, `applicant_name_raw`, `owner_name_raw`, `api_or_bulk`, `data_date`, `hash`, `join_confidence` |
| P1 | `rs_review_sheet` | 行政事業レビュー見える化サイト / RS | `project_number`, `budget_project_id`, `lineage_id`, 府省庁、年度、支出先名/法人番号 where present | 予算事業、支出先、資金の流れ、成果指標 | 行政事業レビューは毎年度点検・公表。令和6年度から見える化サイトで一元公表。 | no_hit は「RS対象事業/年度/検索条件で見つからない」。補助金採択、委託契約、基金事業の全支出先 absence ではない。 | 予算事業と個別採択/契約を混同しない。支出先名だけの法人 join は candidate。 | `project_number`, `fiscal_year`, `ministry`, `sheet_url`, `csv_url`, `recipient_raw`, `recipient_houjin_bangou`, `amount`, `lineage_id`, `fetched_at` |
| P1 | `supervisory_actions_indexes` | 金融庁/公取委/厚労省/国交省/消費者庁等の処分・命令・公表ページ | 公表番号/発表日、対象者名、許認可番号、法人番号 where present | 行政処分、排除措置命令、課徴金、業務停止、許可取消、リコール等 | 各所管庁の公表単位。更新頻度は source別。 | no_hit は「接続済み所管庁・期間・索引で該当なし」。未接続自治体、過去削除、PDF内のみ、氏名非公表を否定しない。 | 誤結合が名誉毀損・信用毀損リスク。法人番号/許可番号 exact 以外は公開 threshold を高くする。 | `authority`, `action_id`, `published_date`, `target_name_raw`, `target_id`, `action_type`, `document_url`, `pdf_hash`, `join_method`, `public_surface_allowed` |
| P1 | `workplace_shokuba_labo` | 厚労省 職場情報総合サイト等 | 法人番号 where present、企業名、認定ID | 職場情報、認定、女性活躍/くるみん等 | 所管サイト・制度別更新。gBizINFO経由でも取得可能。 | no_hit は「当該制度/サイトで登録・公開なし」。未申請、非公開、別法人名、更新遅延は区別不可。 | 認定ロゴ・画像は取り込まない。fact と出典URLのみ。 | `program_or_cert_id`, `corporate_number`, `cert_name`, `valid_from_to`, `source_url`, `upstream_source`, `retrieved_at`, `image_excluded=true` |

## 3. source_receipt common design

`source_receipt` は hit と no_hit を同じ構造で扱う。`no_hit_receipt` を別物にすると、artifact 側が absence と誤読しやすい。

必須フィールド案:

| field | 意味 |
|---|---|
| `source_receipt_id` | `sr_{source_id}_{sha256(canonical_query + snapshot + selector)[0:16]}` |
| `source_id` | 上記 source list の安定ID |
| `source_family` | `identity`, `tax_registration`, `procurement`, `filing`, `grant`, `law`, `statistics`, `ip`, `enforcement` |
| `source_owner` | 省庁/独法/公的運営主体 |
| `source_url` | API endpoint、DLファイル、HTML/PDF単票、または検索ページ |
| `canonical_query` | 正規化済み検索条件。法人番号/T番号/EDINET/JCN/期間/キーワード等 |
| `request_method` | `api`, `bulk_download`, `html_index`, `pdf`, `csv`, `manual_seed` |
| `snapshot_as_of` | データ基準日。例: `2026-04-30 month_end` |
| `fetched_at` | jpcite取得日時 |
| `response_status` | HTTP/API status、DL成功、parse成功 |
| `result_state` | `hit`, `multi_hit`, `zero_result`, `blocked`, `parse_failed`, `out_of_scope`, `rate_limited`, `license_blocked` |
| `result_count` | raw result件数 |
| `content_hash` | raw body/file hash。API no_hit もレスポンス hash を保存 |
| `record_selector` | JSON path / CSV row key / PDF page / HTML selector / XBRL element+context |
| `license_terms_url` | 利用規約、政府標準利用規約、API規約等 |
| `attribution_text` | artifact に表示する短い出典文 |
| `upstream_source` | gBizINFO等の集約sourceで必須 |
| `derived_fact_ids` | この receipt から作った fact/event/edge |
| `known_gap_tags` | `source_not_connected`, `identifier_missing`, `name_only_match`, `coverage_limited`, `snapshot_lag`, `api_key_pending` 等 |
| `no_hit_interpretation` | zero_result時の機械可読説明。`absence_not_proven` を必ず含める |

`no_hit` の表示文テンプレート:

> `{source_label}` を `{query_summary}` で `{fetched_at}` に確認した範囲では、該当レコードは返りませんでした。これは当該事実が存在しないことの証明ではありません。未接続source、公開対象外、名称揺れ、更新遅延、検索条件外の可能性があります。

## 4. CSV派生事実との join algorithm

### 4.1 入力CSVの標準化

入力列を次の entity hint に分解する。

| hint | 例 | 扱い |
|---|---|---|
| `houjin_bangou` | 13桁数字 | checksum/桁検証後、P0 exact join |
| `invoice_registration_number` | `T1234567890123` | T除去して法人番号候補。ただし個人事業者T番号は法人番号にならない |
| `company_name` | 株式会社サンプル | NFKC、全半角、空白、旧字体、法人格位置、括弧、英数記号を正規化 |
| `address` | 都道府県/市区町村/町丁目 | JIS X 0401/0402、郵便番号、丁目番地正規化。完全住所でなく municipality までを重視 |
| `representative` | 代表者名 | 原則 tie-breaker。公開成果物では過剰利用しない |
| `industry` | JSIC/自由記述 | e-Stat cohort / 補助金適合候補に使う。法人同定には弱い |
| `license_number` | 建設業許可番号等 | source別 exact join が可能なら強い |
| `program_name` | 補助金名/制度名 | jGrants/e-Gov/省庁ページとの制度ID候補 |

### 4.2 join stage

1. Exact ID stage
   - `houjin_bangou` が有効なら NTA法人番号 exact。
   - `T番号` があり法人型ならインボイス exact -> `houjin_bangou` derivation -> NTA exact。
   - `edinetCode`, `JCN`, `secCode`, `docID`, `license_number`, `patent_registration_number` があれば source別 exact。
   - exact hit は `identity_assertion.confidence=1.0` ただし「そのIDの正当性」であり、CSV行と同一主体かは入力列の所有者文脈も見る。

2. Candidate generation stage
   - NTA法人番号API/基本3情報DLで `company_name` + prefecture/city から候補生成。
   - gBizINFO法人番号検索を fallback 候補生成に使う。
   - EDINETは `filerName` / `JCN` / `secCode`、p-portal/JETROは落札者名、JPOは出願人/権利者名で候補を作るが、公開 fact にはしない。

3. Scoring stage
   - `name_score`: 正規化商号完全一致 > 法人格除去一致 > 読み/フリガナ一致 > 部分一致。
   - `address_score`: 都道府県+市区町村一致、町域一致、郵便番号一致、旧住所履歴一致。
   - `id_score`: T番号派生、JCN、EDINET JCN、許可番号。
   - `context_score`: 業種、制度対象地域、調達機関/所在地、URLドメイン、CSV内グループ文脈。
   - `negative_evidence`: 複数候補、所在地不一致、閉鎖法人、商号変更時点不整合、同一名称の別法人。

4. Decision stage
   - `exact_verified`: 法人番号/T番号/JCN等で同一主体を確認。成果物に fact を出せる。
   - `high_confidence_candidate`: score >= source別閾値、かつ競合候補なし。成果物では「候補」として出すか、人間確認待ち。
   - `ambiguous`: 候補複数。会社フォルダには owner question として出す。
   - `no_candidate`: no_hit receipt と known gap を出す。
   - `blocked`: API key / license / rate / parse で未確認。absence 表現禁止。

### 4.3 CSV fact projection

CSV由来は必ず `csv_asserted_fact` として保存し、公的sourceで確認した `public_verified_fact` と分ける。

| projection | 例 | 出し方 |
|---|---|---|
| `csv_asserted_fact` | CSVに「法人番号=...」とある | 「入力CSV上の値」 |
| `public_verified_fact` | NTAで商号・所在地 hit | 「国税庁法人番号公表サイトで確認」 |
| `public_event` | 落札/採択/処分/開示 | source receipt 付き event |
| `inferred_edge` | CSV会社 -> p-portal落札者候補 | `candidate`, confidence, human review required |
| `cohort_fact` | 所在地の統計、業種統計 | 会社固有 fact ではなく地域/業種の周辺情報 |

### 4.4 Confidence thresholds

| family | public exact threshold | candidate表示 | 備考 |
|---|---:|---:|---|
| identity spine | 1.00 | 0.90+ | 法人番号なし名称同定は原則 candidate |
| invoice | 1.00 | なし | T番号 exact のみ |
| EDINET | 1.00 for JCN/docID | 0.95+ for name+secCode | 上場親会社/子会社違いに注意 |
| procurement | 1.00 if winner_houjin_bangou | 0.97+ | 金額・落札者名は信用影響が大きい |
| enforcement | 1.00 if法人番号/許可番号 | 原則非公開 | 誤結合リスク最大 |
| grants/adoption | 1.00 if法人番号 | 0.95+ | 採択PDFは社名のみが多い |
| laws | `law_id + revision + article` | なし | 条文と制度の接続は別 edge |
| statistics | `statsDataId + dimension` | なし | 会社固有factにしない |

## 5. 成果物別に増える価値

| artifact | P0だけで作れるもの | P1追加で作れるもの |
|---|---|---|
| `company_public_baseline` | 法人同定、所在地、商号、インボイス登録状態、EDINET有無、調達/落札の一部、known gaps | 統計 cohort、知財候補、制度/法令接続、職場/認定、行政事業レビュー資金フロー |
| `company_public_audit_pack` | 法人番号 spine、インボイス、EDINET提出、調達実績、gBizINFO活動サマリ | 所管庁処分横断、JPO権利、e-Gov根拠条文、e-Stat地域/業種文脈 |
| `houjin_dd_pack` | 公開情報DDの first-hop。ID・登録・開示・調達・補助金/認定の存在確認 | 処分/許認可/知財/法令/予算事業までの public trail |
| `application_strategy_pack` | 会社属性と既存採択/調達から候補制度を絞る | jGrants詳細、公募要領、e-Gov根拠、e-Stat地域課題で適合理由を説明 |
| `monthly_client_opportunity_digest` | 顧問先CSVを法人番号/T番号で更新確認、登録失効/商号変更/開示/調達の変化 | 募集開始補助金、法改正、統計変化、認定・職場情報の更新を月次で通知 |
| `procurement_vendor_watch` | 落札実績、事業者情報、同名候補の確認 | 官報/JETRO対象公告、RS予算事業、過去支出先との接続 |

## 6. 追加データ基盤があると作れる成果物

### 6.1 Durable identity graph

必要基盤:

- `identifier_assertion`: 法人番号、T番号、EDINET code、JCN、secCode、許可番号、JPO番号。
- `identity_candidate`: 名称/住所 fuzzy の候補、score、競合候補、review状態。
- `entity_alias`: 商号変更、英語名、フリガナ、旧所在地、source別 raw name。

作れる成果物:

- CSV 1000社の `resolve_company_batch`。
- 会社名だけのCRMを法人番号候補付きで整備する `company_folder_bootstrap`。
- 同名法人・閉鎖法人・T番号不整合の `identity_risk_queue`。

### 6.2 Source receipt ledger + no_hit ledger

必要基盤:

- hit/no_hit/blocked を同一 table に保存。
- source別 coverage、snapshot、staleness、license state を持つ。
- artifact claim から receipt へ逆引き。

作れる成果物:

- `public_dd_evidence_table`: 監査/稟議に貼れる証跡表。
- `known_gaps_summary`: 「未確認範囲」を機械的に説明。
- `refresh_due_queue`: stale source の再取得計画。

### 6.3 Event graph

必要基盤:

- `entity_event`: 採択、落札、処分、登録変更、開示提出、認定、特許出願。
- `event_source_receipt`: event と source receipt の many-to-many。
- `event_temporal_index`: 発生日、公開日、取得日、効力開始/終了日。

作れる成果物:

- `company_timeline`: 公的イベント年表。
- `supplier_public_activity_score`: 調達・採択・認定の公開活動量。ただし信用スコアではなく活動シグナル。
- `watch_delta_digest`: 先月からの変更だけを通知。

### 6.4 Document extraction layer

必要基盤:

- PDF/HTML/CSV/XBRL raw保存、hash、selector、抽出ルールversion。
- OCR/LLM抽出は必ず `machine_extracted` として confidence/validator を保存。
- XBRLは `element_id`, `context_id`, `unit`, `decimals` を保存。

作れる成果物:

- EDINET `filing_key_facts`。
- 補助金公募要領から `eligibility_clause_pack`。
- 行政処分PDFの `action_summary_with_quote_refs`。

### 6.5 Cohort/statistics layer

必要基盤:

- e-Stat dimension catalog、地域コード、産業分類、時系列。
- 会社所在地/業種との cohort edge。

作れる成果物:

- `regional_market_context`: 地域・業種の客観統計を会社フォルダに添付。
- `grant_fit_context`: 補助金の政策目的と地域統計の接続。
- `portfolio_geography_digest`: 顧問先/取引先CSVの地域分布と公的統計。

## 7. Implementation order proposal

実装前の計画として、source接続は次の順に review gate を通す。

1. `source_profile` 固定: source_id、owner、URL、利用規約、auth、更新頻度、coverage、no_hit meaning。
2. `receipt_schema` 固定: hit/no_hit/blocked の共通表現。
3. `identity normalizer` dry-run: 法人番号/T番号/会社名/所在地の標準化 fixture。
4. `NTA法人番号` bulk/API dry-run: 10件 exact + 10件名称候補 + no_hit 3件。
5. `NTAインボイス` DL/API dry-run: 法人T番号、個人T番号、失効、no_hit。
6. `p-portal/JETRO`: 法人番号あり落札、名称のみ落札、対象外 no_hit。
7. `EDINET`: JCNあり、JCNなし、docID取得、訂正/取下げ receipt。
8. `gBizINFO conditional`: upstream_source を保存できる範囲だけ staged expose。
9. P1 source は artifact coverage delta が大きい順に接続。

## 8. Official references checked

- 国税庁 法人番号システム Web-API: https://www.houjin-bangou.nta.go.jp/webapi/
- 国税庁 適格請求書発行事業者公表システム Web-API: https://www.invoice-kohyo.nta.go.jp/web-api/index.html
- 国税庁 インボイス 公表情報ダウンロード: https://www.invoice-kohyo.nta.go.jp/download/index.html
- Gビズインフォ API: https://content.info.gbiz.go.jp/api/index.html
- Gビズインフォについて: https://content.info.gbiz.go.jp/about/index.html
- 金融庁 EDINET API仕様書 Version 2: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf
- デジタル庁 Jグランツ APIドキュメント: https://developers.digital.go.jp/documents/jgrants/api/
- e-Stat API仕様: https://www.e-stat.go.jp/api/api-info/e-stat-manual
- e-Gov 法令データ ドキュメンテーション: https://laws.e-gov.go.jp/docs/
- 調達ポータル: https://www.p-portal.go.jp/
- JETRO 政府公共調達データベース: https://www.jetro.go.jp/gov_procurement/
- 行政事業レビュー: https://www.gyoukaku.go.jp/review/review.html
- 特許庁 特許情報取得API: https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html
- 特許庁 特許情報標準データ: https://www.jpo.go.jp/system/laws/sesaku/data/keikajoho/index.html
