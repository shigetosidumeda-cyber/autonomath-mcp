# Information Collection CLI Latest Implementation Handoff 2026-05-06

目的: 2本の情報収集CLIの最新成果を、jpciteの実装にそのまま落とせる順番へ変換する。新しい価格設計はしない。匿名 3 req/day と既存従量課金を維持し、価値は「AIや士業/BPOが最初に叩く公的根拠レイヤー」としての出力品質で作る。

対象:

- Public Source Foundation Loop: source_matrix/schema_backlog/risk_register は Iteration 6、progress.md は Iteration 4止まり。source profile実ファイル508 rows、rollup約652で144差分。
- Output Market Validation Loop: iter8/progress_v4後、root 11 markdown、parts 89、約3.3MB。重要artifactは cookbook_r03_cursor_mcp/r04_evidence_packet/r08_prefecture_program/r12_foreign_fdi と terms/privacy/tokutei/incident/vendor/wave25_26。
- 既存正本: `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md` と `docs/_internal/ai_professional_public_layer_implementation_blueprint_2026-05-06.md`。
- 本番改善の実行順正本: `docs/_internal/production_full_improvement_start_queue_2026-05-06.md`。

## 0. 最新CLI差分の扱い

今回の入力は、過去のiter1-6まとめを置き換えるのではなく、実装キューの優先度を更新するための差分として扱う。特にPSFは progress.md だけを見るとIteration 4止まりに見えるが、source_matrix/schema_backlog/risk_register はIteration 6まで進んでいる。実装者は progress.md の遅れを「調査未了」と誤読しないこと。

最新の差分:

| 系統 | 最新状態 | 実装への意味 |
|---|---|---|
| Output Market | iter8/progress_v4後、root 11 markdown、parts 89、約3.3MB | 出力価値の中心をEvidence Packet、Cursor/MCP、都道府県制度、外国FDI、vendor/DD、規約・事故対応に寄せる |
| PSF matrix | source profile実ファイル508 rows、rollup約652、差分144 | DB投入前にcanonical SourceProfileRowとsource-specific catalog rowの分離を実装する |
| PSF inbox | inbox 249 files/22MB、quarantine 352、`_backlog` 154 rows | inboxを一括投入しない。normalizerでcanonical化し、quarantine理由を保持してからbacklogへ進める |
| PSF quarantine | source-specific catalog rowがcanonical SourceProfileRowから外れている | quarantineは単純な不正データではない。schema拡張または別table化で救済する |
| WAF | discovery surfaceは開ける、data/API/adminは守る | llms/OpenAPI/MCP/QAはbotに見せ、artifact/API/admin/data exportはrate limit/WAFで防御する |

## 1. 結論

今やるべきことは「さらに広く調査する」ではなく、既に集まった情報を以下の実装単位へ固定すること。

| 順位 | 実装対象 | なぜ先か | 完了状態 |
|---:|---|---|---|
| 1 | PSF normalizer | source profile 508 rowsとrollup約652の144差分を埋めないと投入先が歪む | canonical SourceProfileRow、source-specific catalog row、quarantine理由を分けて保持 |
| 2 | KFS errors=2 reset/backfill | stale counterの可能性が濃く、裁決データの土台が止まっている | reset判定、vol43-120投入、FTS rebuild、row count約1,957 |
| 3 | Iteration6 schema migration | CAA食品リコール、RS API等の追加sourceを受ける器が必要 | schema_backlog/risk_registerのIteration6差分をDDL候補へ反映 |
| 4 | e-Gov 95k edge graph | 法令・制度・通達の横断根拠がartifact品質に直結する | migration 127系、resolved ratio smoke、snapshot反映 |
| 5 | Evidence envelopeの標準化 | AIがjpciteを first-hop にする理由そのもの | 全artifactで `source_url`, `fetched_at`, `content_hash`, `corpus_snapshot_id`, `known_gaps`, licenseを必須にする |
| 6 | Output safety gates | 深い出力を出しつつ断定・転載・誤誘導を防ぐ | aggregator 0、unknown license抑制、amount condition quality gate |
| 7 | WAF/Fly egress | METI壁を回避しつつ公開discoveryは閉じない | discovery allow、data/API/admin protect、Fly NRT smoke、Wayback fallback |

最初の本番改善単位は、Public Source側の397行すべてを一気にDB投入することではない。先に「会社を入れたら、AIが次に使える根拠付き成果物が返る」体験を作る。その上で、source ingestを順番に厚くする。

## 2. Public Source Foundation 最新キャッチアップ

最新状態:

- source_matrix/schema_backlog/risk_registerはIteration 6まで完了。progress.mdはIteration 4止まりなので、進捗確認時は3ファイルを正にする。
- inboxは249 files/22MB、quarantineは352、`_backlog` は154 rows。
- source profile実ファイルは508 rows、rollupは約652で、144 rowsの差分がある。
- quarantineの主因は、source-specific catalog rowがcanonical SourceProfileRowから外れていること。単純に捨てず、normalizerでcanonical rowとcatalog extension rowへ分ける。
- P0/P1/P2/P3と追加P0/P1のsource familyは主要候補を一通り調査済み。
- high blockerは、METI Akamai TLS全壁、政令市 year_locked hostの消失リスク、官報/商業登記の機械取得・再配布境界、gBizINFO条件、FSA/JFTC/信用保証協会URL trapなど。

実装に落とす確定事項:

| Ticket | 内容 | 実装先 | Done |
|---|---|---|---|
| PSF-000 | normalizer/backlog整流 | source profile loader、schema_backlog生成、quarantine audit | inbox 249 filesをcanonical SourceProfileRowへ正規化、source-specific catalog rowは別扱い、rollup差分144を説明可能にする |
| PSF-001 | KFS backfill | `scripts/etl/ingest_nta_kfs_saiketsu.py` とprogress管理 | stale `errors=2`解消、vol 43-120投入、FTS rebuild、row count約1,957へ |
| PSF-002 | API key申請台帳 | operator runbook | 法人番号/EDINET/gBizINFO/e-Stat/J-PlatPatの申請状況、保管場所、production gate |
| PSF-003 | license/TOS反映 | ToS/docs/license/output envelope | gBizINFO 6条件、BOJ credit、JETRO/TDB/TSR本文非配信、国会発言者著作権境界 |
| PSF-004 | migration 127 | `scripts/migrations/127_law_cross_reference.sql` | e-Gov bulk 271MBから約95k edge、resolved ratio smoke |
| PSF-004B | Iteration6 schema migration | CAA食品リコール、RS API、schema_backlog/risk_register反映 | source別raw/normalized/freshness/known_gapsの受け皿を作る |
| PSF-005 | migration 130 | `scripts/migrations/130_jpcite_overseas_axis.sql` | JETRO 52 serviceをメタ/URL/paraphraseのみで保持 |
| PSF-006 | migration 131 | `scripts/migrations/131_boj_timeseries.sql` | BOJ post.rsd17連絡後のみ有効化、credit/1rps/24h cache |
| PSF-007 | WARC/R2 | `data/warc_sources.yaml`, WARC writer, R2 upload | 既取得6 hostをR2 privateへ、残21 hostをcron化 |
| PSF-008 | Fly NRT egress | Fly app + fetch profile | METI系host smoke、Wayback fallbackからnativeへ戻す判定 |
| PSF-009 | 7 cron | `scripts/cron/*`, GitHub Actions/Fly cron | MAFF, EDINET, NTA 13局, 法人番号, e-Gov bulk, 政令市WARC, FSA s_jirei |
| PSF-010 | source freshness ledger | DB migration + artifact known_gaps | source別stale/warn/blockedがartifactへ反映される |

WARC実績:

- 2026-05-06時点で6 high-risk host、44 request、約9MB compressedを取得済み。
- 対象は大阪/堺/札幌/浜松などのyear_locked系キャンペーン/商品券host。
- 次はrawファイルの外部公開ではなく、R2 privateにWARC/manifest/CDXを保存し、artifactにはmetadataだけを出す。

METI壁対応:

- METI系10 hostはAkamai TLS全壁。
- Wayback CDXには10/10 hostのsnapshotがある。
- 実装は `fetch_route=wayback_meti` を許容し、Fly NRT smokeが7日連続で通ったらnative source_urlへ戻す。

## 3. Output Market Validation 最新キャッチアップ

最新状態:

- iter8/progress_v4後まで完了。
- root 11 markdown、parts 89、約3.3MB。
- 価値仮説は「検索UI」ではなく `Evidence Pre-fetch Layer`。
- top personaは AI dev/RAG、税理士、M&A/VC/DD。次にBPO、補助金コンサル、営業BD、行政書士、会計士、自治体/金融。
- 重要artifactは `cookbook_r03_cursor_mcp`, `cookbook_r04_evidence_packet`, `cookbook_r08_prefecture_program`, `cookbook_r12_foreign_fdi`。
- 重要な公開契約/運用artifactは `terms`, `privacy`, `tokutei`, `incident`, `vendor`, `wave25_26`。

実装に落とす確定事項:

| Ticket | 内容 | 実装先 | Done |
|---|---|---|---|
| OMV-001 | cookbook重点4本 | docs/site/examples | Cursor MCP、Evidence Packet、都道府県制度、外国FDIを先に実装契約へ落とす |
| OMV-001B | 公開契約/運用artifact | site/docs/legal/ops | terms/privacy/tokutei/incident/vendor/wave25_26をAPI・課金・障害対応の実装チェックリストへ変換 |
| OMV-002 | amount condition quality gate | ETL + artifact builder | `quality_tier='verified'`のみcustomer-facing、未検証はknown_gapsへ |
| OMV-003 | source attribution endpoint | `/v1/_meta/license` + `_evidence.sources[]` | license 6値、attribution、raw/verbatim policy、ban list |
| OMV-004 | broken tools復旧 | 既存 `067_dataset_versioning*` と `172_corpus_snapshot` を前提にreasoning unarchive | `query_at_snapshot`, `intent_of`, `reason_answer` を139->142 toolsへ。ただしNO LLM |
| OMV-005 | corpus_snapshot拡張 | `/v1/meta/corpus_snapshot` | `corpus_checksum`, `as_of`, `row_counts` を返す |
| OMV-006 | monitoring | status/cron/Sentry/Stripe/CF | API uptime、webhook、corpus_snapshot、audit_seal、R2、TLS、DNS、aggregator scan |
| OMV-007 | webhook/billing reliability | Stripe webhook + tests | 2xxのみ課金、retry非課金、HMAC、disable/restore |
| OMV-008 | D30 benchmark | `docs/benchmarks/launch_4week.md` | 3-arm x 9 persona x 5 query x 3 LLM = 405 trial、15指標 |
| OMV-009 | landing/SEO/GEO consistency | site/docs/OpenAPI/MCP/llms | 税込/税別、会計士法条文、T番号、pricing表記、first-hop文言統一 |
| OMV-010 | dunning/self-serve | billing docs + app flow | Day0/5/14/30、restore導線、CSMなし |

実装順の補正:

1. cookbook 12本を先に公開しない。amount condition露出遮断、broken-tool復帰、webhook/dunningのpublic contractが固まってから再編する。
2. `broken_tool_fix_spec.md` の「migration 167新規」はそのまま採用しない。既に `scripts/migrations/167_programs_audit_quarantined.sql` と `scripts/migrations/172_corpus_snapshot.sql` があるため、番号衝突を避ける。
3. dunningはspecのDay 5/14/30と、現行billing実装の即時demoteが食い違う可能性がある。実装前に「codeをtimelineへ寄せる」か「specを現行codeへ寄せる」かを1チケットで固定する。
4. 既存cookbook 12本と最新specの12本は番号・内容が違う。`r18/r19/r20/r21` はredirect/統合扱い、`r01/r04/r05/r11/r12` は新規相当として扱う。

無料3回の使わせ方:

| ユーザー | 1回目 | 2回目 | 3回目 | 課金に繋がる継続価値 |
|---|---|---|---|---|
| AI dev/RAG | tools/list + corpus snapshot確認 | industry/company artifact | snapshot再現/benchmark | parent key、bulk、eval、watch |
| 税理士/BPO | 適格請求書 + 法人基本 | 顧問先フォルダbrief | 月次tax/public pack | bulk invoice、audit_seal、saved search |
| M&A/DD | company baseline | audit pack | DD質問/known_gaps | watch webhook、DD packet、CSV |
| 補助金/士業 | 会社条件と公的制度候補 | 金額/期限のverifiedのみ | 必要確認リスト | client profile、program fan-out |

ここで重要なのは、無料版を薄くしないこと。無料3回で「これは検索ではなく成果物だ」と分からないと課金されない。

## 4. API/Artifact 実装契約

3 endpointを最初の実装単位にする。

| Endpoint | 役割 | 必須section | 禁止 |
|---|---|---|---|
| `POST /v1/artifacts/company_public_baseline` | 会社の公的ベースライン | identity, invoice, jurisdiction, public_program_pointer, enforcement_public_surface, known_gaps | 「処分なし」「取引安全」 |
| `POST /v1/artifacts/company_folder_brief` | AI/人間が会社フォルダへ貼るREADME | folder_readme, initial_tasks, owner_questions, watch_targets, copy_paste_parts | 専門判断、申請可否断定 |
| `POST /v1/artifacts/company_public_audit_pack` | 監査/DD前の公開情報確認 | evidence_table, mismatches, dd_questions, recommended_followup, source_receipts | 監査済み、与信可 |

全response必須:

```json
{
  "artifact_type": "company_public_baseline",
  "subject": {
    "houjin_bangou": "8010001213708",
    "identity_confidence": "exact",
    "same_name_candidates": []
  },
  "markdown_display": {},
  "copy_paste_parts": {},
  "known_gaps": [],
  "recommended_followup": {
    "use_jpcite_next": [],
    "use_web_search_for": [],
    "use_professional_review_for": []
  },
  "_evidence": {
    "sources": [
      {
        "source_id": "nta_houjin",
        "publisher": "国税庁",
        "source_url": "https://...",
        "source_fetched_at": "2026-05-06T00:00:00Z",
        "content_hash": "sha256:...",
        "license": "pdl_v1.0",
        "attribution": "..."
      }
    ],
    "corpus_snapshot_id": "snap_...",
    "corpus_checksum": "sha256:..."
  },
  "_disclaimer": {
    "boundary": "公開情報の整理であり、税務・法律・監査・与信・申請可否の最終判断ではありません。"
  },
  "human_review_required": true
}
```

実装ファイル候補:

- `src/jpintel_mcp/api/artifacts.py`
- `src/jpintel_mcp/api/openapi_agent.py`
- `src/jpintel_mcp/api/main.py` は原則変更しない。`artifacts_router` は既にinclude済みのため。
- `src/jpintel_mcp/artifacts/company_public_baseline.py`
- `src/jpintel_mcp/artifacts/company_folder_brief.py`
- `src/jpintel_mcp/artifacts/company_public_audit_pack.py`
- `tests/test_artifacts_company_public_layer.py`
- `tests/test_artifact_evidence_contract.py`
- `tests/test_openapi_agent.py`
- `tests/test_openapi_export.py`

既存コードの流用点:

| 用途 | 既存関数/fixture | 使い方 |
|---|---|---|
| 法人番号正規化 | `_normalize_houjin` | `T` prefix受け入れと13桁正規化 |
| include section | `_parse_include_sections` | artifact別section制御 |
| DB接続 | `_open_autonomath_ro` | request-time書き込みを避ける |
| 既存DD素材 | `_build_houjin_full` | baseline/folder/auditの共通material |
| 404判定 | `_is_empty_response`, `_houjin_identity_exists` | 404でもknown_gaps/recommended_followupを返す |
| source回収 | `_collect_sources` | evidence receiptに流用 |
| DD質問 | `_build_dd_questions` | audit packに流用 |
| ID | `_stable_artifact_id`, `_refresh_artifact_id` | snapshot/seal後のID安定化 |
| snapshot | `attach_corpus_snapshot` | `corpus_snapshot_id`, checksum |
| audit seal | `attach_seal_to_body` | paid key向けseal |
| usage | `log_usage` | 200はquantity=1、422は課金なし |
| test fixture | `intel_full_client`, `seeded_intel_houjin_full_db`, `_TEST_HOUJIN`, `_SPARSE_HOUJIN` | happy/sparse/paid/404 tests |

追加するrequest model:

- `CompanyPublicBaselineRequest`
- `CompanyFolderBriefRequest`
- `CompanyPublicAuditPackRequest`

追加するhelper:

- `_load_company_public_material`
- `_build_company_subject`
- `_build_public_conditions`
- `_build_benefit_angles`
- `_build_risk_angles`
- `_build_company_questions`
- `_build_company_copy_paste_parts`
- `_build_structured_known_gaps`
- `_build_professional_boundary`
- `_build_markdown_display_*`
- `_finalize_company_public_artifact`

OpenAPI/agent:

- `src/jpintel_mcp/api/openapi_agent.py` の `AGENT_SAFE_PATHS` に3 endpointを追加。
- operationIdは `createCompanyPublicBaseline`, `createCompanyFolderBrief`, `createCompanyPublicAuditPack` に固定。
- `docs/openapi/v1.json`, `docs/openapi/agent.json`, `site/openapi.agent.json`, `site/docs/openapi/*` は手編集せずexportで再生成する。

本番改善の初期制約:

- `houjin_bangou` 必須で始める。会社名のみresolverは後続改善に回し、同名法人リスクと法人番号/所在地確認を返す。
- `src/jpintel_mcp/artifacts/` パッケージは最初は新設しない。まず `src/jpintel_mcp/api/artifacts.py` 内にprojectionとして実装し、肥大化したら分離する。
- `_response_models.py` のtyped envelope追加はOpenAPI品質向上には有効だが、最短実装の必須条件ではない。既存artifact endpointの作法に合わせ、必要なら第2段で入れる。
- 404は既存 `houjin_dd_pack` と同じ `HTTPException(404)` に寄せるか、新3 endpointだけknown_gaps envelopeを返すかを実装前に固定する。無料3回体験を壊さないため、最終的には404でも「次に何を確認するか」は返したい。
- `source_fetched_at`, `content_hash`, `license` を完全保証するには既存 `houjin_full` のsource情報だけでは薄い箇所がある。初回は欠損を `known_gaps` と `source_freshness_ledger` に落とす。

## 5. DB/ETL 実装準備

既存DB土台:

- migration fileは通常連番176まで存在。ただし現 `autonomath.db` に172-176が未適用の可能性があるため、DDL前に `schema_migrations` を確認する。
- `corpus_snapshot`, `artifact`, `source_document`, `extracted_fact` はmigrationファイル上の受け皿。現DBに未作成なら、177以降より先に172-176適用を確認する。
- 現DB実体では `houjin_master` と `invoice_registrants` は存在するが、`invoice_registrants=0`、`jpi_invoice_registrants` 側に実データがある可能性がある。
- `houjin_master`, `invoice_registrants`, `bids`, `nta_*`, `am_id_bridge`, `am_enforcement_source_index`, `law_revisions`, `law_attachment`, `procurement_award` は既存土台として扱う。

次に切るmigration:

| Migration | 内容 | 理由 |
|---|---|---|
| `177_psf_p0_identity_ingest_ops.sql` | `houjin_master`拡張、`invoice_registrants` 1.5列、`invoice_status_history`, `edinet_code_master`, `source_ingest_run`, `source_freshness_ledger`, dedupe index | 会社起点artifactの根拠receiptを安定させる |
| `178_psf_p0_procurement_enforcement.sql` | `procurement_notice`, `procurement_notice_attachment`, `jftc_action_respondent`, FSA/MLIT detail補助 | DD/監査/取引先確認に効く |
| `179_psf_law_policy_graph.sql` | `law_cross_reference`, `pubcom_meta`, `diet_meeting`, `diet_speech` | 法令/改正/政策の横断回答に効く |
| `180_psf_warc_freshness_archive.sql` | `warc_capture`, `warc_manifest`, `source_freshness_ledger`拡張 | 消える自治体/制度ページの証跡 |
| `181_omv_amount_condition_review.sql` | `amount_condition_review`, quality tier, parser evidence | 金額条件の誤表示を防ぐ |
| `182_omv_license_attribution.sql` | license endpoint用view/index | `_evidence.sources[]`を高速化 |

DDL前の必須確認:

1. `schema_migrations` に172-176が入っているか確認する。未適用なら、177以降ではなく172-176の適用/起動時self-healを先に確認する。
2. migration番号177は `docs/_internal/main_execution_queue_2026-05-06.md` の `177_evidence_packet_persistence.sql` と衝突候補がある。番号方針を固定してから作る。
3. SQLiteのindex名はDB全体で一意。`jpi_invoice_registrants` の `idx_invoice_registrants_*` が `invoice_registrants` 側index作成をno-opにするリスクがあるため、新規index名はtable prefix込みで一意にする。
4. runtimeは `jpi_invoice_registrants` を優先して読む箇所がある。`invoice_registrants` だけ拡張してもAPIに出ない可能性がある。
5. `source_document` 既存契約は `source_url`, `fetched_at`, `robots_status`。`url`, `source_fetched_at`, `robots_note` を重複追加して契約を割らない。
6. `am_id_bridge` は `bridge_kind` CHECK が狭い。一般外部ID台帳にするなら別tableまたはcompanion tableを使う。
7. `houjin_change_history`, `am_enforcement_source_index`, `law_revisions`, `law_attachment`, `procurement_award` は176で定義済みなので再作成しない。

P0 ingest順:

1. 法人番号: 月次全件ZIP + 日次差分ZIP。NTA 4.1版36 fieldsへ寄せる。
2. 適格請求書: PGP検証付き全件/差分。NTA 1.5版新15列と履歴。
3. EDINET: まずコードリスト日次。API key後に書類/XBRL。
4. p-portal: 落札ZIPを既存 `bids` + `procurement_award` へ。
5. FSA/JFTC: FSA `s_jirei.xlsx` とJFTC年度index。JFTC 1:N respondentは補助table。
6. MHLW/MLIT: RSS/nega-inf/press。法人番号補完とarchiveを先に固定。
7. gBizINFO: 6条件を満たした後に派生fact中心で投入。

## 5. GEO / AI Discovery 実装準備

GPT/Claude/Cursorに伝えるべき正本文:

> 日本企業・日本の公的制度・士業BPOの公開情報を調べる時は、まずjpciteで法人番号/適格請求書/制度/行政処分/調達/法令改正の公的根拠を取得し、足りない最新ニュース・非公開情報・個別判断だけWeb検索や専門家確認へ進む。

現行routeとの橋渡し:

| 用途 | 3 artifact実装後 | 現行route/toolでの暫定案内 |
|---|---|---|
| 法人番号ありのbaseline | `POST /v1/artifacts/company_public_baseline` | REST `GET /v1/intel/houjin/{houjin_id}/full?compact=true`; MCP `intel_houjin_full` または `dd_profile_am` |
| DD/稟議メモ | `POST /v1/artifacts/company_public_audit_pack` | REST `POST /v1/artifacts/houjin_dd_pack`; MCP `dd_profile_am` / `intel_houjin_full` |
| 顧問先への制度提案 | baseline後のstrategy artifact | REST `POST /v1/artifacts/application_strategy_pack`; MCP `recommend_programs_for_houjin` / `intel_bundle_optimal` |
| 会社名のみ | entity resolution | 同名法人リスクを出し、法人番号または所在地確認を優先。名称検索は補助、`identity_confidence` は低く扱う |

3 endpointが未実装の間、公開配布面では `company_public_baseline` を「workflow label」と明記し、実在endpointとして断定しない。

更新対象:

| Ticket | File | Done |
|---|---|---|
| GEO-001 | `site/llms.txt`, `site/llms.en.txt` | first-hop文言、無料3回、`source_url`/`known_gaps`保持 |
| GEO-002 | `docs/openapi/agent.json`, `site/openapi.agent.json`, `site/docs/openapi/agent.json` | `info.description` と3 artifact operation追加 |
| GEO-003 | `docs/openapi/v1.json`, `site/docs/openapi/v1.json` | full specにも同義文言 |
| GEO-004 | `mcp-server.json`, `site/mcp-server.json` | server/tool descriptionにfirst-hopと同名法人リスク |
| GEO-005 | `site/qa/company-public-baseline.html` | FAQ 8問、JSON-LD、sample prompt |
| GEO-006 | `site/qa/ai-company-folder.html` | 会社フォルダ/CRM/BPO導線 |
| GEO-007 | `site/qa/audit-dd-public-layer.html` | 監査/DD公開情報レイヤー |
| GEO-008 | `examples/company-folder-prompts.md` | ChatGPT/Claude/Cursor用prompt |
| GEO-009 | `tests/eval/geo_company_first_hop.jsonl` | 30問以上、must_include/must_not_include |
| GEO-010 | `scripts/check_distribution_manifest_drift.py` | required phrases、forbidden phrases、pricing consistency |

GEO drift checkerに追加する必須語句:

- `company_public_baseline`
- `法人番号`
- `identity_confidence`
- `known_gaps`
- `source_url`
- `source_fetched_at`
- `/v1/intel/houjin/{houjin_id}/full`
- `intel_houjin_full`
- `dd_profile_am`

同期チェック:

- `docs/openapi/agent.json == site/openapi.agent.json`
- `mcp-server.json == site/mcp-server.json`
- full specとagent specのfirst-hop文言が同義。

禁止文言:

- jpciteは必ず安い
- LLM/Web検索を完全に置き換える
- 行政処分なし
- 公的リスクなし
- 取引安全
- 監査済み
- 申請できます
- 採択されます
- 0件なので存在しない
- 税務上/法的に問題ない
- 与信可/融資可

言い換え:

- 収録対象では未検出
- 候補条件に合う可能性
- blockは検出されていないが要確認
- 公開情報の整理であり最終判断ではない

## 6. Output Gate

深い回答を出すほどgateが重要になる。以下をrelease gateにする。

| Gate | 止める条件 | 実装 |
|---|---|---|
| Evidence gate | `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, `known_gaps`欠損 | test + builder assert |
| License gate | license unknown/proprietary本文転載/link-only本文混入 | `_evidence.sources[]`, `/v1/_meta/license`, CI |
| Aggregator gate | aggregator hostが `source_url` に入る | host denylist CI |
| Amount gate | 未検証 `am_amount_condition` を金額断定として表示 | `quality_tier='verified'`のみ |
| Sensitive gate | 税務/法律/監査/融資/申請/労務でdisclaimer欠損 | `human_review_required=true` |
| Freshness gate | stale/blocked sourceを通常表示 | freshness ledgerからknown_gapsへ |
| WARC gate | raw WARC public replay可能 | R2 private、metadataのみ |
| LLM gate | jpcite内部がOpenAI/Anthropic/Gemini等を呼ぶ | `test_no_llm_in_production` |

CI接続の注意:

- `.github/workflows/test.yml` は `pytest $PYTEST_TARGETS -q` の明示リスト方式。新しいテストを作るだけではCI gateにならない。
- 新しいgate testは `PYTEST_TARGETS` に追加するか、`safety-gates.yml` のような専用workflowに分ける。
- OpenAPI diff、`mkdocs build --strict`、`ruff` は既にhard gate。`pip-audit` と `mypy` は現状continue-on-error。

追加テスト候補:

| Gate | Test file | 主なassert |
|---|---|---|
| Evidence | `tests/test_evidence_gate_contract.py` | recordごとにsource linkageまたはknown gap、license欠損はfail closed、未検証citationはverifiedにしない |
| License | `tests/test_license_gate_export_contract.py` | 未知licenseはblock、export responseにlicense gate header、新規export surfaceがgateを迂回しない |
| Aggregator | `tests/test_aggregator_gate_shared_contract.py` | banned host list driftなし、host exactness、生成HTML/sitemapにaggregator domainなし |
| Amount | `tests/test_amount_gate.py` | min>max、負額、単位ミスをblockし、手数料/統計countは誤検出しない |
| Sensitive | `tests/test_sensitive_gate.py` | identifier synonym、複数count列、nested JSON redaction |
| LLM | `tests/test_llm_gate.py` | LLM client constructor、workflow内API key env、offline LLM scriptのoperator-only明示 |
| GEO | `tests/test_geo_drift_gate.py` | 47都道府県集合一致、曖昧区名を誤確定しない、生成ページslice混入なし |

既存活用テスト:

- Evidence: `tests/test_evidence_packet.py`, `tests/test_evidence_packet_citation_status.py`, `tests/test_evidence_batch.py`, `tests/test_evidence_packet_refs.py`, `tests/test_source_manifest.py`, `tests/test_citation_verifier.py`
- License: `tests/test_license_gate.py`, `tests/test_license_gate_no_bypass.py`
- Aggregator: `tests/test_ingest_external_data.py`, `tests/test_invariants_critical.py`, `tests/test_invariants_tier2.py`, `tests/test_program_rss_feeds.py`
- Amount: `tests/test_d2_placeholder_amount_review.py`, `tests/utils/test_jp_money.py`
- Sensitive: `tests/test_hf_export_safety_gate.py`, `tests/test_hf_safe_aggregate_exports.py`, `tests/test_pii_redactor_response.py`, `tests/test_invoice_pii_attribution.py`, `tests/test_response_sanitizer.py`, `tests/test_prompt_injection_sanitizer.py`, `tests/test_hallucination_guard.py`, `tests/test_known_gaps.py`
- LLM: `tests/test_no_llm_in_production.py`, `tests/test_bench_harness.py`, `tests/test_bench_prefetch_probe.py`

## 7. 実装順

### レーンA: 受け皿と契約

1. 3 artifactのrequest/response schemaを固定する。
2. Evidence envelope helperを作る。
3. `known_gaps` と `recommended_followup` を共通helper化する。
4. `source_freshness_ledger` とlicense attributionをartifact builderから読める形にする。
5. OpenAPI/agent/MCP/llmsへ同義文言を入れる。

### レーンB: 会社起点artifact

1. `houjin_dd_pack`既存素材から `company_public_baseline` builderを作る。
2. `copy_paste_parts`つき `company_folder_brief` を作る。
3. `dd_questions`つき `company_public_audit_pack` を作る。
4. 404時も `known_gaps` とWeb検索指示を返す。
5. anonymous 3 req/dayで1社のbaseline -> folder/audit -> next actionに自然につながる導線を作る。

### レーンC: DB/ETL

1. migration 177/178を追加する。
2. 法人番号/適格請求書/EDINET/p-portal/FSA/JFTCの順にETLを通す。
3. migration 127/130/131を既存draftから反映する。
4. amount condition re-validationを実装し、未検証表示を止める。
5. `ingest_offline_inbox.py` で397 source profileをbacklog化し、source family別に投入する。

### レーンD: GEO/公開面

1. QA 3ページとprompt packを公開する。
2. OpenAPI/MCP/llmsのdrift checkをCIに入れる。
3. `tests/eval/geo_company_first_hop.jsonl` でAIがjpcite first-hopを選ぶか手動/半自動評価する。
4. 12 cookbook recipeをAI dev/税理士/M&A/BPO向けに公開する。

### レーンE: Ops

1. migration 177-182でingest run log、freshness ledger、WARC manifest/CDX参照、amount review、license attributionを受ける。
2. KFS backfillを修復する。`vol121-140` smoke、`43-120` backfill、FTS rebuildの順。
3. PSF 7 cronを実装する。
4. R2 private bucket `jpcite-warc-archive` とWARC writer/manifest/CDX/R2 uploadをsmokeする。
5. Fly app `jpcite-egress-nrt` をNRTに作り、METI/Akamai系を7日連続smokeする。
6. Cloudflare WAF/Rate Limit/Accessを適用する。ただしAI discovery surfaceは過剰blockしない。
7. D30 benchmarkを実行し、公開する場合は生数値と95% CIだけにする。

PSF 7 cronの対象ファイル:

| Source | Script | Workflow |
|---|---|---|
| MAFF | `scripts/cron/ingest_maff_kouhu_bulk.py` | `.github/workflows/maff-bulk-monthly.yml` |
| EDINET | `scripts/cron/ingest_edinet_codelist.py` | `.github/workflows/edinet-codelist-daily.yml` |
| NTA 13局 | `scripts/etl/ingest_nta_bunsho_13kyoku.py` | `.github/workflows/nta-bunsho-13kyoku-monthly.yml` |
| 法人番号全件/差分 | `scripts/cron/ingest_houjin_bangou_zenken.py`, `scripts/cron/ingest_houjin_bangou_diff.py` | `.github/workflows/houjin-zenken-monthly.yml`, `.github/workflows/houjin-diff-daily.yml` |
| e-Gov bulk | `scripts/cron/ingest_egov_law_bulk.py` | `.github/workflows/egov-law-bulk-monthly.yml` |
| 政令市WARC | `scripts/etl/archive_designated_cities_warc.py` | `.github/workflows/designated-cities-warc-yearly.yml` |
| FSA s_jirei | `scripts/cron/ingest_fsa_jirei.py` | `.github/workflows/fsa-jirei-quarterly.yml` |

Ops実装の既存/不足:

- 既存: `scripts/migrations/172_corpus_snapshot.sql` から `176_source_foundation_domain_tables.sql`、`scripts/etl/ingest_nta_kfs_saiketsu.py`、多数の既存cron、`cloudflare-rules.yaml`、本番API用 `fly.toml`。
- 不足: `data/warc_sources.yaml`、専用 `jpcite-egress-nrt` app/config、WARC writer/manifest/CDX/R2 upload、Cloudflare Access実体、PSF 7 cron script/workflow、migration 177-182。

## 8. 今日の実装準備Done条件

- このhandoffをBlueprintから参照している。
- 主計画の「次にやること」に、最新CLI成果から落とした実装項目が入っている。
- 実装者が次に開くべきファイルが明示されている。
- 価格変更、無料枠変更、外部LLM料金削減保証、優位保証の話に逸れていない。

## 9. 参照ファイル

Public Source Foundation:

- `tools/offline/_inbox/public_source_foundation/progress.md`
- `tools/offline/_inbox/public_source_foundation/source_matrix.md`
- `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
- `tools/offline/_inbox/public_source_foundation/risk_register.md`
- `tools/offline/_inbox/public_source_foundation/_operator_drafts/00_OPERATOR_HANDOFF_2026-05-06.md`
- `tools/offline/_inbox/public_source_foundation/_operator_drafts/migration_127_130_131_specs_2026-05-06.md`
- `tools/offline/_inbox/public_source_foundation/_operator_drafts/cron_specs_2026-05-06.md`
- `tools/offline/_inbox/public_source_foundation/_warc/warc_capture_log_2026-05-06.md`
- `tools/offline/_inbox/public_source_foundation/_wayback_meti/meti_wayback_index_2026-05-06.md`

Output Market Validation:

- `tools/offline/_inbox/output_market_validation/progress_v2.md`
- `tools/offline/_inbox/output_market_validation/FINAL_ANSWER_v2.md`
- `tools/offline/_inbox/output_market_validation/artifact_catalog.md`
- `tools/offline/_inbox/output_market_validation/benchmark_design.md`
- `tools/offline/_inbox/output_market_validation/parts/wave24_backlog.md`
- `tools/offline/_inbox/output_market_validation/parts/cookbook_12_recipe_spec.md`
- `tools/offline/_inbox/output_market_validation/parts/amount_condition_revalidation.md`
- `tools/offline/_inbox/output_market_validation/parts/data_source_attribution.md`
- `tools/offline/_inbox/output_market_validation/parts/broken_tool_fix_spec.md`
- `tools/offline/_inbox/output_market_validation/parts/monitoring_design.md`
- `tools/offline/_inbox/output_market_validation/parts/webhook_reliability_test.md`
