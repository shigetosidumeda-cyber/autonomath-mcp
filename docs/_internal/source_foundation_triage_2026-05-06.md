# Source Foundation Triage 2026-05-06

## 0. 2026-05-06 追加受領した loop 状態

この文書は `tools/offline/_inbox/public_source_foundation/` の実装トリアージ正本として、2026-05-06 に共有された Public Source Foundation Loop サマリを前提にする。

| Metric | Value | 実装判断 |
|---|---:|---|
| iterations | 4 | 追加調査より、正規化/ETL/response反映へ比重を移す |
| parallel agent | 66 | source family は十分に広がった。優先順位を固定する段階 |
| source profile rows | 397 / JSONL全valid | `source_profile` normalizer で本体backlogへ入れる |
| YAML seed | 47都道府県 + 20政令市 + 47中核市 / 1,876 lines | regional/local source の seed として扱う |
| deep dive report | 30 markdown / 約340KB | 個別sourceの実装根拠として参照する |
| rollup | source_matrix / schema_backlog / risk_register / progress | この4つをSOTにし、個別reportは補助証跡にする |

Coverage:

| Priority | Coverage | 代表source |
|---|---|---|
| P0 | 8 family 全カバー | 法人番号、適格事業者、gBizINFO、EDINET、FSA、JFTC、MHLW、MLIT |
| P1 | 10 family 全カバー | 法令、通達、国会、文書回答、KFS、裁判例、p-portal、KKJ |
| P2 | 5 family 全カバー | 官報metadata、e-Stat、47都道府県、JFC、SMRJ |
| P3 / 追加P0-P1 | 多数 | METI認定、業許可、J-PlatPat、信用保証、JETRO、BOJ、中労委、大学産学連携 |

確定 blocker:

| Blocker | Severity | Owner action |
|---|---|---|
| API key 申請 (EDINET / gBizINFO / e-Stat / 法人番号 / J-PlatPat) | medium | 申請完了後にETLを有効化 |
| METI Akamai TLS 全壁 | high | Fly Tokyo egress または Wayback route |
| WARC snapshot 政令市27別ドメイン | high | R2等へ内部archive。外部提供はしない |
| gBizINFO 6条件 | medium | Bookyou名義、1-token、1 rps+24h cache、固定出典文、第三者権利条項、マーク画像除外 |
| BOJ post.rsd17事前連絡 + クレジット文言 | medium | operator draft を作成し送付 |
| MAFF browser UA + Referer cron | medium | source別fetch profile |
| KFS backfill ETL errors=2 | low | root cause調査 |

iter5候補は44件あるが、この文書では以下だけを優先する。

1. WARC自動化とFly egress。
2. e-Gov 95k edge graph。
3. 47信用保証協会の残機関。
4. MLIT super-source横断。
5. 中労委backfill。
6. hub_plan PDF構成団体の法人enrich。
7. METI Wayback ingest。
8. BOJ post.rsd17 draft。
9. エンジェル税制 Fly egress retry。

## 現在取り込めた外部CLI-A成果物

JSONL syntax validation は全件 OK。

注意: `auth` / `redistribution_risk` / `new_tables` の形が source ごとに揺れている。実取り込みでは、まず `source_profile` 正規化 layer を置き、未知フィールドは `metadata_json` に退避する。

入力:

- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_courts.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_edinet.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_egov.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_estat.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_fsa_jftc_enforcement.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_gbizinfo.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_houjin_bangou.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_invoice_registrants.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_kanpou.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_kokkai.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_local_pubfin.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_mhlw_mlit_enforcement.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_nta_kfs.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06_procurement.jsonl`

## 実装トリアージ

| Priority | Source | Join key | 実装判断 | 課金価値 |
|---|---|---|---|---|
| P0 | `houjin_bangou_webapi` | `houjin_bangou` | 先行実装 | 会社名・所在地・変更履歴の名寄せ土台。全アウトプットの entity spine。 |
| P0 | `nta_invoice_kohyo` | `T+13桁`, `houjin_bangou` | 先行実装 | 取引先確認・税務DD・支払先確認で即価値。 |
| P0 | `edinet_api_v2` | `JCN`, `edinetCode`, `secCode`, `docID` | metadata/code master 先行、XBRL fact 後続 | 上場企業・投資先・取引先の財務/リスク文脈を回答に混ぜられる。 |
| P0 | `p_portal_chotatsu` | procurement item no., `houjin_bangou` | 落札ZIPを先行実装 | 官公庁調達実績・入札機会を法人DDに混ぜられる。 |
| P0 | `fsa_enforcement_index` | `houjin_bangou`, normalized name | 先行実装 | 金融処分・登録/監督リスク。DD pack の差別化要素。 |
| P0 | `jftc_enforcement_index` | `houjin_bangou`, normalized name | 先行実装 | 独禁法・下請法・景表法近接リスク。取引先審査に効く。 |
| P0 | `mhlw_enforcement_index` | `houjin_bangou`, authority, date | 先行実装 | 労務・派遣・介護系の行政処分。士業/金融/調達で有用。 |
| P0 | `mlit_enforcement_index` | `houjin_bangou`, permit no., date | 先行実装 | 建設・宅建・運送の許認可リスク。地域事業者DDに強い。 |
| P0-review | `gbizinfo_api_v2` | `corporate_number` | token取得 + 6条件運用で限定実装 | 補助金・調達・認定の横断価値は高い。raw dump ではなく要約/派生fact中心で扱う。 |
| P1 | `nta_shitsugi` / `nta_bunsho_kaitou` / `nta_tsutatsu_body` / `kfs_saiketsu_full` | 税目, 通達番号, 裁決番号 | 税務artifact向けに先行設計 | GPT/Claude単体より深い税務根拠付きメモを作れる。 |
| P1 | `egov_houreiapi` | `law_id`, `law_revision_id`, article | 既存法令DBのrevision補強 | 法令本文154件問題のSOT整理、改正差分、条文引用の深さに効く。 |
| P1 | `egov_pubcom` | `pubcom_id`, ministry, deadline | metadata + URL中心 | 制度変更の予兆・顧客影響memoに効く。添付PDF raw再配布は慎重。 |
| P1 | `courts_hanrei` | case number, date, court | citation metadata 先行 | 税務・行政・契約DDの説得力を上げる。本文利用境界は別レビュー。 |
| P1 | `ndl_kokkai_api` | `issueID`, `speechID` | 後続 | 立法趣旨・制度背景の説明を深くできる。話者著作権/引用量は管理。 |
| P1-review | `kkj_kankouju` | item key, organization, region | metadata/URLのみ | 地方案件の厚みは出るが再配布文言が弱い。 |
| P2 | `estat_api` | region, JSIC, year | 後続 | 地域・業種ベンチマーク。DDや補助金適合理由を強化。 |
| P2 | `prefecture_program_index` / `jfc_loan_index` / `smrj_index` | region, authority, product | 後続 | 地方制度・融資・支援策の穴埋め。品質差が大きいので段階導入。 |
| P2-risk | `kanpou_internet` | issue, page, name/address match | metadata/deep link のみ | 破産/公告/決算公告などは強いが、crawl/権利/PIIリスクが高い。 |
| P3 | `shokokai_jcci_index` / `shinkin_chigin_sample` / `ministry_chotatsu_pages` | authority, bank/product, notice URL | 後続・個別確認 | 情報価値はあるがToSと鮮度管理の負荷が高い。 |

## データ基盤拡張チケット

### P0: 会社 baseline を直接強くする source

P0 は `company_public_baseline` / `company_public_audit_pack` / `company_folder_brief` に即反映する。実装順は「法人 spine → 税務/請求書 → 上場 metadata → 公的売上 → 行政処分 → 条件付き gBizINFO」。全 source で `source_document`、`extracted_fact`、`known_gaps_json`、固定出典文を必須にする。

| Ticket | Source | ETL | Schema / table | Join key | Freshness | known_gaps | 法務/再配布制約 | 効く artifact |
|---|---|---|---|---|---|---|---|---|
| PSF-P0-001 | `houjin_bangou_webapi` | 月次 `zenkoku` ZIP を全置換 ingest、稼働日次 `sabun` ZIP を追記。Web-API は appId 取得後に name/number lookup 補助へ回す。CSV は Unicode を正本、Shift_JIS は fallback。 | `houjin_master` / `jpi_houjin_master` の canonical 化、`houjin_change_history`, `houjin_master_refresh_run`, `source_document` | `houjin_bangou` | 月次全件: 月初稼働日+翌稼働日24:00。差分: 稼働日 16:00 JST、過去40稼働日保持。 | appId 2-4週待ち、API rate 非公開、36 fields に対する既存 schema 差分、encoding 取り違え、署名検証漏れ。 | PDL v1.0。出典明記と加工明記必須。Web-API disclaimer を response/docs に入れる。 | `company_public_baseline`, `company_public_audit_pack`, `company_folder_brief`, `houjin_dd_pack`, `monitoring_digest`, 全 source の entity spine |
| PSF-P0-002 | `nta_invoice_kohyo` | 全件ZIP月次 + 差分ZIP稼働日次。OpenPGP署名検証を ingest gate にし、API `/1/num` は個別照会、`/1/diff` は差分補完。 | `invoice_registrants`, 新規/候補 `invoice_status_history`, `source_document`, `extracted_fact`; 1.5版の新15列は migration backlog へ | `registratedNumber` (`T+13桁`)、下13桁 `houjin_bangou`、個人は no-join | 差分: 翌稼働日 06:00、過去40稼働日。全件: 毎月初稼働日。 | ApplicationID 未取得、PGP公開鍵 URL 固定化、個人/人格なき社団は法人番号なし、1 req 10件/50日上限、`correct/latest/history` の履歴設計。 | PDL v1.0。検索UI scrapeは禁止、Web-API/ZIPは提供経路。Web-API disclaimer 必須。個人名は公表同意・公表申出フィールドに依存。 | `invoice_counterparty_check_pack`, `tax_client_impact_memo`, `company_public_baseline`, `company_public_audit_pack`, `monitoring_digest` |
| PSF-P0-003 | `edinet_api_v2` | 先行はコードリスト ZIP 日次同期。`content-md5`/sha256 で idempotency。API key 後に `documents.json?type=2` metadata を日次取得。XBRL fact は後続。 | `edinet_code_master`, `edinet_documents`, `entity_id_bridge`, 後続 `edinet_xbrl_facts` | `JCN`=`houjin_bangou`, `edinetCode`, `secCode`, `docID` | コードリスト日次 02:30 JST 目安。提出書類 metadata は日次。 | API key + MFA 未取得、投信/外国法人 JCN null、doc/form/type code 正本別紙、`withdrawalStatus` / `disclosureStatus` / `legalStatus=0` 同期必須。 | PDL v1.0。metadata 再配布は low risk。本文/XBRL mirror は status sync と縦覧期間管理が前提。 | `listed_corp_pack`, `company_public_audit_pack`, `houjin_dd_pack`, `monitoring_digest`, `lender_public_risk_sheet` |
| PSF-P0-004 | `p_portal_chotatsu` | `successful_bid_record_info_all_{YYYY}.zip` を FY2017-current で backfill、`diff_{YYYYMMDD}.zip` を日次 upsert。HEAD は使わず GET のみ。 | 既存 `bids` + `procurement_award`; `source_document` に ZIP/file hash、`extracted_fact` に落札 fact | `procurementItemNo`, `corporationNo`=`houjin_bangou`, `ministryCd`, `successfulBidDate` | 全件: 月次。差分: 日次、過去2か月保持。 | 公告本文/予定価格/参加者数は欠損、notice は KKJ/PPI と別 join、1案件複数落札者の 1:N 確認、入札方式コード辞書 ingest。 | 政府標準利用規約2.0 / CC BY 4.0互換。出典: 調達ポータル。加工明記。 | `procurement_vendor_pack`, `public_revenue_signal`, `company_public_audit_pack`, `sales_target_dossier`, `monitoring_digest` |
| PSF-P0-005 | `fsa_enforcement_index` | `s_jirei.xlsx` で FY2002-current seed、FSA本庁/地方財務局 HTML を月次 incremental。Excel は `order_group_id` を LAG 派生。 | canonical は `am_enforcement_detail` + `am_enforcement_source_index`; staging は `fsa_action_index` 相当。`source_document` に HTML/XLSX snapshot。 | `houjin_bangou`, `corp_name_normalized`, `authority`, `publication_date`, `order_group_id` | XLSX: 半期/随時更新確認。HTML: 月次または週次。 | `s_jirei.xlsx` の点線 grouping が cell に出ない、法人番号 fill 58.9%、本庁 HTML は要約のみ、個人事業主/役員氏名。 | PDL v1.0。個人名は public API で mask。処分理由 full text は内部保持、外部は要約+deep link優先。 | `company_public_audit_pack`, `houjin_dd_pack`, `lender_public_risk_sheet`, `monitoring_digest` |
| PSF-P0-006 | `jftc_enforcement_index` | FY2010+ の年度 index walk、press HTML 抽出。多名宛人は `action` と `respondent` を分離。課徴金別表 PDF は後続 parser。 | canonical は `am_enforcement_detail` + `am_enforcement_source_index`; staging は `jftc_action_index`, `jftc_action_respondent` 相当。 | `houjin_bangou`, `corp_name_normalized`, `press_release_no`, `publication_date`; 1:N respondent | 週次。報道発表日当日にも差分検知可。 | 課徴金単独 index 不在、確約/警告/注意の index 散在、1:N 展開漏れ、PDF別表に個社課徴金。 | PDL v1.0。出典明記。マスコット/シンボルは再配布対象外。個人事業主は mask。 | `company_public_audit_pack`, `houjin_dd_pack`, `cartel_bid_rigging_dashboard`, `monitoring_digest` |
| PSF-P0-007 | `mhlw_enforcement_index` | 47労働局 + 8厚生局 RSS fan-out、タイトル regex で行政処分候補抽出、詳細 HTML/PDF を取得。法人番号は NTA 逆引き。 | `am_enforcement_detail`, `am_enforcement_source_index`; staging `mhlw_action_index`; directory は後続 `mhlw_haken_directory` / `mhlw_kaigo_directory` | `corp_name_normalized` + address + `authority`, `action_published_at`; enrich 後 `houjin_bangou` | RSS 4回/日、詳細 backfill は週次。介護/医療法人は月次巡回。 | 原本に法人番号なし、介護取消の中央集約なし、`kaigokensaku` CSV禁止、slug alias (`kochi`/`oita`) 管理、個人事業主。 | 政府標準利用規約2.0。個人名/代表者名は response mask。CSV禁止 source は HTML/URL metadata に限定。 | `company_public_audit_pack`, `labor_grant_prescreen_pack`, `worker_safety_radar`, `monitoring_digest` |
| PSF-P0-008 | `mlit_enforcement_index` | `nega-inf` 13カテゴリ + 自動車処分 CGI を月次/daily巡回。`etsuran2` 業者一覧で許可番号→法人番号 bridge。5年消滅対策で snapshot metadata を保持。 | `am_enforcement_detail`, `am_enforcement_source_index`; staging `mlit_neg_index`, `mlit_action_press`; directory `mlit_business_directory`; `archive_url` / `as_of_date` 必須 | `kyoka_bangou`, `authority`, `action_published_at`, name+address; enrich 後 `houjin_bangou` | nega-inf 月次、自動車処分は週次/日次、業者一覧は大臣許可週次・知事許可四半期。 | nega-inf は直近5年のみ、法人番号なし、CSV/JSONなし、etsuran2 UA gating、トラック/バス/タクシーは別系統。 | 政府標準利用規約2.0。5年超は「自社アーカイブ」「as_of_date」を明示し、要約+deep linkで返す。 | `permit_risk_pack`, `company_public_audit_pack`, `construction_risk_radar`, `logistics_compliance_brief`, `monitoring_digest` |
| PSF-P0-009 | `gbizinfo_api_v2` | Bookyou名義 token 取得後、`updateInfo/*` delta と `/v2/hojin/{corporate_number}/{subsidy,procurement,certification}` を 24h cache + 1 rps で取得。初期は raw dump でなく派生 fact。 | `gbiz_update_log`, `gbiz_certifications`, `gbiz_subsidies`, `gbiz_procurement_awards`; `source_document` は API response hash と attribution、raw artifact は保存しない選択を許可 | `corporate_number`=`houjin_bangou`; domain別 source id | token取得後は日次 delta。上流 dataset cadence は metadata に記録。 | token quota 非公開、上流取込頻度が dataset ごとに差、finance coverage sparse、補助金 detail は jGrants/省庁直 source が正本。 | 政府標準利用規約2.0 / CC BY 4.0互換の条件付き greenlight。6条件: Bookyou名義、1-token、1 rps+24h cache、固定出典文、第三者権利条項、マーク画像除外。 | `subsidy_traceback`, `public_revenue_signal`, `procurement_vendor_pack`, `company_public_baseline`, `monitoring_digest` |

P0共通 ticket:

- PSF-P0-010: `source_profile` normalizer。`auth` / `redistribution_risk` / `new_tables` の揺れを `metadata_json` に退避し、`source_document_backlog.jsonl` / `schema_backlog.jsonl` / `source_review_backlog.jsonl` へ安定変換する。
- PSF-P0-011: `entity_id_bridge` 強化。`houjin:<13桁>` を主軸に、`invoice:T...`, `edinet:E...`, `permit:<authority>:<no>`, `procurement:<item_no>` を `match_confidence` 付きで接続する。
- PSF-P0-012: attribution / disclaimer envelope。source別固定出典文、取得日、加工明記、raw再配布禁止フラグ、個人名 mask 状態を全 artifact の `sources[]` と `known_gaps[]` に露出する。
- PSF-P0-013: freshness ledger。sourceごとの `expected_freshness`, `last_success_at`, `latest_source_date`, `staleness_level`, `blocking_reason` を保持し、artifact が「安全」ではなく「未検出/未確認範囲」を返せるようにする。

### P1: 専門家 artifact を深くする source

| Ticket | Source family | 実装単位 | Schema / join key | Freshness / constraints | 効く artifact |
|---|---|---|---|---|---|
| PSF-P1-001 | NTA 税務 corpus | 通達本文、質疑応答、文書回答、KFS裁決を search UI ではなく index walk で取得。相基通から smoke。 | `nta_tsutatsu_body`, `nta_shitsugi`, `nta_bunsho_kaitou`, 既存 `nta_saiketsu`; `tax_law`, `taikei_no_normalized`, `case_id`, `vol/case` | PDL v1.0。体系番号 NFKC/U+2212 正規化。週次/月次。個別事案は汎用化注記必須。 | `tax_client_impact_memo`, `pre_kessan_impact_pack`, `regulatory_brief` |
| PSF-P1-002 | e-Gov 法令 + パブコメ | 271MB bulk XML + `/revisions`、plain-text cross reference、パブコメ RSS 108本。PDF blob は再配信しない。 | `law_revisions`, `law_attachment`, `law_cross_reference`, `pubcom_meta`; `law_id`, `law_revision_id`, `article`, `pubcom_id` | 法令 bulk は日次再生成、実運用は週次/monthly full。パブコメは日次。政府標準利用規約2.0、添付PDFの第三者著作に注意。 | `regulatory_brief`, `subsidy_fit_and_exclusion_pack`, `monitoring_digest` |
| PSF-P1-003 | 国会会議録 | 30制度→5制度 smoke→月次 incremental。レスポンスは要旨、短い引用、`speechURL`。 | `diet_meeting`, `diet_speech`, `am_alias(kind='diet_program_label')`; `issueID`, `speechID`, program label | full text 返却禁止。内部解析は可、外部は要旨+引用。sleep 3s、月次。 | `legislative_intent_pack`, `tax_client_impact_memo`, `application_strategy_pack` |
| PSF-P1-004 | 裁判例 metadata | キーワード seed + canonical URL + 判決 metadata。UI clone はしない。 | `court_case_index` / 既存 `court_decisions`; case number, date, court | 判決本文は著作権法13条で利用しやすいが大規模 clone は控えめ。週次。 | `tax_dispute_briefing`, `regulatory_brief`, `audit_workpaper_evidence_pack` |
| PSF-P1-005 | 調達 notice / KKJ | KKJ API 47都道府県 walk、`p_portal_chotatsu` 落札と fuzzy bridge。 | `procurement_notice`, `procurement_notice_attachment`, `procurement_award`; `Key`, `procurementItemNo`, organization/date/name | KKJ は CC明示なし、API利用明記+link必須。notice-only。日次。 | `procurement_vendor_pack`, `sales_target_dossier`, `monitoring_digest` |
| PSF-P1-006 | METI/MAFF/JFC/信用保証/地方制度 | 中小企業庁・経産局・MAFF Excel・JFC 73ページ・信用保証51を seed config で段階 ingest。 | `program_local_index`, `loan_programs`, `program_documents`; `program_id`, `authority`, `region_code`, optional `houjin_bangou` | Akamai/Wayback/Fly egress など source別 fetch profile。月次中心。出典文 source別固定。 | `subsidy_fit_and_exclusion_pack`, `regional_advisory_digest`, `subsidy_loan_combo_strategy` |

### P2: 周辺文脈・深掘り source

| Ticket | Source family | 実装単位 | Schema / join key | Freshness / constraints | 効く artifact |
|---|---|---|---|---|---|
| PSF-P2-001 | e-Stat / BOJ | e-Stat は法人企業統計 1表から開始。BOJ は事前連絡後に統計系列 seed。 | `estat_stats_data`, `estat_classification`, `macro_stats_series`; `region_code`, `industry_code_jsic`, `stat_code`, `series_id` | e-Stat appId は1用途1ID、BOJはクレジット必須。月次/年次。 | `market_size_pack`, `subsidy_kpi_normalizer`, `lender_public_risk_sheet` |
| PSF-P2-002 | 官報 metadata | gBizINFO 経由 metadata を優先。自前 full crawl はしない。deep link + 発行日/号/頁/商号程度。 | `kanpou_notice_index`; issue, page, name/address match, inferred `houjin_bangou` | robots/TOS high risk。PDF本文は保持・再配布しない。 | `company_public_audit_pack`, `ma_signal`, `monitoring_digest` |
| PSF-P2-003 | J-PlatPat / IP | 法人名・出願人名から特許/商標メタのみ段階取得。 | `ip_rights_index`; applicant name, application number, `houjin_bangou` via bridge | API/画面規約確認後。更新は月次。 | `innovation_signal_pack`, `company_public_baseline` |
| PSF-P2-004 | 商業登記 on-demand | 登記情報提供を bulk 化せず、顧客明示操作の1件 pull→内部cache→構造化eventのみ返却。 | `registry_event_cache`; `houjin_bangou`, event_date, event_type | 原PDF/原文再配布禁止。約款と過度反復回避。 | `ma_dd_pack`, `company_public_audit_pack` |
| PSF-P2-005 | TDB/TSR/民間倒産情報 | URL、タイトル、発行日、短い要約のみ。倒産の正本は官報 metadata へ寄せる。 | `private_credit_news_pointer`; normalized name, published_at, url | 本文 verbatim NG。契約なし full ingest なし。 | `lender_public_risk_sheet`, `ma_signal` |
| PSF-P2-006 | 自治体 long tail / 政令市・中核市 | 20政令市 + 47中核市 seed YAML、期限切れ別ドメインは WARC snapshot metadata。 | `program_local_index`, `source_document`; `region_code`, `authority`, `program_id` | URL drift/WAFあり。月次。別ドメインは期限前 snapshot。 | `regional_advisory_digest`, `portfolio_screening_csv` |

## 本体schemaへの落とし込み

CLI-A の `SourceProfile` は本番DBへ直接 insert しない。まず `public_source_foundation` inbox tool で `source_document_backlog.jsonl` / `schema_backlog.jsonl` / `source_review_backlog.jsonl` に変換し、review 済みのものだけを migration / fetch job / extractor 実装へ渡す。

### すぐ共通台帳で受ける

172-175 で以下の foundation table を受け皿にする。

- `corpus_snapshot`
- `artifact`
- `source_document`
- `extracted_fact`

`source_document` は URL、publisher、license、fetched_at、content_hash、robots、tos_note を保持する。

`artifact` は raw XLSX / PDF / HTML / JSON / ZIP を保存する場合にだけ使う。gBizINFO、官報、KKJ、銀行/信金ページのように規約・PII・再配布境界が強いものは `retention_class` と `license` を明示し、初期は raw artifact を保存しない選択も許す。

`extracted_fact` は処分日、処分内容、根拠法令、登録状態、財務指標、税務争点、落札者、補助金採択などの抽出事実を保持する。quote / page / span がない初期backfillは `known_gaps_json` に `quote_position_missing` を入れる。

ID寄せは既存の `am_id_bridge` / entity mapping と接続する。法人番号、インボイス登録番号、EDINETコード、許可番号、調達案件番号、裁判例ID、会議録IDを内部 entity へ寄せる。

### 個別table候補

先行候補:

- `houjin_change_history`
- `invoice_status_history`
- `edinet_documents`
- `edinet_code_master`
- `fsa_action_index`
- `jftc_action_index`
- `mhlw_action_index`
- `mlit_neg_index`
- `nta_tax_guidance`
- `tax_case_decision`
- `procurement_notice`
- `procurement_award`

保留候補:

- `edinet_xbrl_facts`
- `gbiz_certifications`
- `gbiz_subsidies`
- `gbiz_procurement_awards`
- `law_revisions`
- `pubcom_calls`
- `court_case_index`
- `diet_meeting`
- `diet_speech`
- `estat_stats_data`
- `kanpou_notice_index`
- `local_program_index`

### 2026-05-06 本体実装済み schema

`scripts/migrations/172_corpus_snapshot.sql` から `176_source_foundation_domain_tables.sql` までを追加済み。いずれも `target_db: autonomath`、schema-only、seedなし、rollback companionあり。

実装済み:

- `corpus_snapshot`
- `artifact`
- `source_document`
- `extracted_fact`
- `houjin_change_history`
- `houjin_master_refresh_run`
- `am_enforcement_source_index`
- `law_revisions`
- `law_attachment`
- `procurement_award`

設計判断:

- `SourceProfile` はDBに直接入れず、backlog JSONLへ正規化する。
- FSA/JFTC/MHLW/MLITは省庁別正本テーブルを作らず、既存 `am_enforcement_detail` に接続する `am_enforcement_source_index` に寄せる。
- p-portal落札は既存 `bids` を canonical とし、複数落札者/明細だけ `procurement_award` 子テーブルで持つ。
- e-Gov revisionは既存 `laws` / `am_law` を直接変えず、`law_revisions` / `law_attachment` に閉じる。
- 法人番号は `houjin_change_history` と `houjin_master_refresh_run` を先に置き、`houjin_master` / `jpi_houjin_master` の揺れはETL側で吸収する。

実装保留:

- `edinet_documents` / `edinet_xbrl_facts`: API key / MFA とタクソノミ確認後。`edinet_code_master` は先に取り込む。
- `gbiz_*`: token取得、6条件運用、固定出典文、raw artifact 非保存方針の確認後。
- `invoice_status_history`: ApplicationID と差分ZIP署名検証の設計後。
- `tax_*` / `kfs_*`: 既存スクリプト/API衝突確認後に separate slice。
- `kanpou_*`: robots / crawler禁止が強いため、当面は metadata/deep link または提携検討。

## 課金ユーザー向けアウトプット

### `houjin_dd_pack`

最優先。単なる会社検索ではなく「この相手と進めてよいか」を返す。

使うデータ:

- 法人番号、法人名、所在地、変更履歴
- インボイス登録状態
- EDINET metadata / 上場コード / 提出書類
- FSA/JFTC/MHLW/MLIT処分
- 調達・補助金・認定は ToU確認後
- 官報は metadata/deep link のみ

返す価値:

- 取引先・投資先・融資先の公的リスク確認
- 処分/登録/提出書類の時系列
- 「確認すべき質問」リスト
- ソース付き known gaps

### `subsidy_fit_and_exclusion_pack`

補助金・融資・支援策の「応募できる/できない/足りない書類」を返す。

使うデータ:

- 既存 program DB
- 法人番号、地域、業種、資本金、従業員規模
- インボイス、処分履歴、許認可
- e-Gov法令/通達/公募要領
- e-Statの地域・産業統計

返す価値:

- 適合度順の制度候補
- 除外理由と解消手段
- 申請前に集めるべき証拠書類
- 併用可否 matrix

### `tax_client_impact_memo`

税理士・会計事務所向け。GPT/Claudeに条文や裁決を探させるより、既に揃えた根拠で短く深く返す。

使うデータ:

- NTA質疑応答
- 文書回答
- 通達本文
- KFS裁決
- e-Gov法令本文/改正
- 裁判例 metadata

返す価値:

- 顧問先への影響
- 根拠条文/通達/裁決
- 判断が割れる論点
- 追加確認質問

### `procurement_vendor_pack`

官公庁調達や自治体案件を取りに行く企業向け。

使うデータ:

- p-portal / KKJ / 各省庁調達 metadata
- 法人番号、許認可、処分
- e-Stat地域/業種
- gBizINFOの認定/補助金/調達はレビュー後

返す価値:

- 取れそうな案件群
- 必要資格・許認可
- 過去落札者/競合候補
- 入札前リスク

### `monitoring_digest`

既存顧客を継続課金へ寄せるアウトプット。

使うデータ:

- 法人番号差分
- インボイス差分
- 処分公表差分
- EDINET提出差分
- 調達/補助金/制度改正差分

返す価値:

- 顧問先/取引先/投資先の「前回から変わった点」
- 重要度順の通知
- その場で送れる確認文面

## 次の本体アクション

1. `public_source_foundation` inbox validation / backlog writer は実装済み。今後の外部CLI成果物も同じ契約で受ける。
2. 172-176 migration の pytest coverage を維持し、idempotency / rollback をCIで見る。
3. 次のAPI実装候補は `houjin_dd_pack` / `monitoring_digest` / `tax_client_impact_memo` の順で、既存データだけで出せる最小 artifact から作る。
4. fetcher / ETL は `houjin_change_history`、`am_enforcement_source_index`、`law_revisions`、`procurement_award` の順で接続する。
5. gBizINFO / 官報 / KKJ / 銀行系は `blocked` or `review_required` のまま raw再配布を避ける。
6. `/about` の「本文収録154件」は、情報収集後に law text SOT を確定してから public count を更新する。
