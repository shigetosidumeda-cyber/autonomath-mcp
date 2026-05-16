# AWS scope expansion 02: laws, regulations, industry rules, permits

作成日: 2026-05-15  
担当: 拡張深掘り 2/30 - 法律・制度・業法・許認可の情報基盤  
対象: jpcite の GEO-first / AI agent-first 公的一次情報基盤  
状態: 計画のみ。AWS CLI/API コマンド実行なし。AWSリソース作成なし。出力はこの Markdown のみ。

## 0. 結論

この領域は AWS クレジット活用の中でも最重要に近い。理由は、法律・制度・業法・許認可の情報は、後から作れる成果物の種類が非常に多く、AI agent がエンドユーザーへ推薦しやすい「根拠付きの意思決定前パケット」に直結するためである。

ただし、jpcite が売るべきものは「法的結論」ではない。売るべきものは次の4つである。

1. 公的一次情報から作った、時点・URL・ハッシュ付きの `source_receipts[]`
2. 条文、告示、通達、ガイドライン、許認可一覧、標準処理期間、パブコメ、ノーアクションレターを結ぶ `claim_refs[]`
3. AI agent が誤った断定をしないための `known_gaps[]` と `no_hit_not_absence`
4. 業種・行為・地域・事業フェーズごとの「確認すべき規制論点」「必要な許認可候補」「次に人間専門家へ渡すべき材料」

最初に作るべき情報基盤は、単なる法令検索ではなく、次の「regulatory evidence spine」である。

```text
法令 XML
  -> 条・項・号・別表
  -> 施行令 / 施行規則 / 府省令 / 告示
  -> 通達 / 監督指針 / ガイドライン / Q&A
  -> 許認可 / 届出 / 登録 / 認可 / 承認 / 報告義務
  -> 審査基準 / 標準処理期間 / 処分基準
  -> パブリックコメント / 改正履歴 / 施行日
  -> ノーアクションレター / 法令照会 / 行政解釈
  -> 業種別 packet / proof page / MCP tool example
```

この形にしておけば、後から「補助金」「会計CSV」「会社調査」「新規事業」「業法DD」「許認可申請準備」「制度変更アラート」などへ横展開できる。

## 1. この拡張の位置づけ

既存の AWS 統合計画では、e-Gov 法令は `J04 e-Gov law snapshot` として扱われている。しかし、このままだと「条文データを持っている」状態に留まり、ユーザー価値が弱い。

今回の拡張では、`J04` を次のように広げる。

| 旧ジョブ | 拡張後の扱い |
|---|---|
| J04 e-Gov law snapshot | 法令 XML の全量/差分 snapshot、条文 receipt、施行日/freshness ledger |
| J06 Ministry/local PDF extraction | 所管省庁の告示・通達・ガイドライン・Q&A・監督指針の抽出 |
| J10 Enforcement/sanction/public notice sweep | 業法ごとの行政処分・監督情報を規制要件に接続 |
| J15 Packet/proof fixture materialization | 業法・許認可 packet examples / proof pages へ変換 |
| J16 GEO/no-hit/forbidden-claim evaluation | 法的断定、許認可不要断定、違法性なし断定の禁止スキャン |

本体 P0 計画との関係は次の順に固定する。

1. `jpcite.packet.v1`、`source_receipt`、`claim_ref`、`known_gap`、`no_hit` の schema を先に固定する。
2. e-Gov 法令 API / XML 一括データから法令 backbone を作る。
3. 所管省庁リンク集を起点に、告示・通達・ガイドラインの `source_profile` を作る。
4. 許認可、届出、登録、認可、承認、報告義務を抽出して、行政手続 graph を作る。
5. 業種別・行為別の packet / proof / GEO ページを作る。
6. deploy 前に、法的助言誤認、no-hit誤用、古い法令、出典欠落、再配布境界違反を release blocker として検査する。

## 2. 一次情報ソースの層

### 2.1 L0: e-Gov 法令 API / XML

最優先 source。

使う対象:

- 法律
- 政令
- 府省令・規則
- 条文 XML
- 条・項・別表単位の取得
- 更新法令一覧
- 一括 XML ダウンロード

作る artifact:

- `law_manifest.parquet`
- `law_article_units.jsonl`
- `law_article_source_receipts.jsonl`
- `law_update_events.jsonl`
- `law_effective_date_ledger.jsonl`
- `law_cross_reference_graph.jsonl`
- `law_known_gaps.jsonl`

重要フィールド:

- `law_id`
- `law_no`
- `law_title`
- `law_type`
- `article`
- `paragraph`
- `item`
- `appendix_table`
- `promulgation_date`
- `enforcement_date`
- `amendment_name`
- `amendment_no`
- `source_url`
- `retrieved_at`
- `content_sha256`
- `api_endpoint`
- `corpus_snapshot_id`

注意:

- e-Gov で取れるのは主に法令本体であり、すべての実務運用・行政解釈・審査基準を含むわけではない。
- 現行法令、過去時点、未施行、廃止、条ずれを混同しない。
- `no_hit` は「指定 API / snapshot / 条件で見つからない」だけであり、「法的義務なし」ではない。

### 2.2 L1: 所管省庁の法令・告示・通達リンク集

e-Gov ポータルには「所管法令・告示・通達」のリンク集があり、各行政機関の法令、告示、通達等への導線になる。ここを `source_profile` の seed として扱う。

対象例:

- 内閣府
- 公正取引委員会
- 金融庁
- 消費者庁
- デジタル庁
- 総務省
- 消防庁
- 法務省
- 財務省 / 国税庁
- 文部科学省
- 厚生労働省
- 農林水産省
- 経済産業省 / 中小企業庁 / 特許庁
- 国土交通省 / 観光庁 / 気象庁
- 環境省
- 原子力規制委員会
- 防衛省

作る artifact:

- `agency_source_profile_seed.jsonl`
- `agency_law_notice_guideline_catalog.jsonl`
- `agency_domain_terms_robots_receipts.jsonl`
- `agency_document_manifest.parquet`
- `agency_document_review_queue.jsonl`

注意:

- 省庁サイトは HTML / PDF / Excel / Word が混在する。
- 告示・通達・ガイドラインは、法令 XML と違って構造が安定しない。
- 公式サイトでも、添付資料や第三者資料の再配布条件が異なる場合がある。
- 初期は raw 全文を公開しない。公開面は URL、タイトル、発行者、日付、ハッシュ、短い根拠抜粋、構造化 claim に限定する。

### 2.3 L2: 施行規則、告示、通達、監督指針、ガイドライン、Q&A

ここが jpcite の価値を大きく上げる。AI agent が欲しいのは条文だけではなく、「実務上なにを確認すべきか」だからである。

対象 document kind:

- `cabinet_order`
- `ministry_ordinance`
- `agency_rule`
- `public_notice`
- `circular`
- `supervisory_guideline`
- `inspection_guideline`
- `administrative_guidance`
- `faq`
- `q_and_a`
- `manual`
- `application_guide`
- `form_instruction`
- `checklist`
- `technical_standard`

抽出する claim kind:

- `regulatory_requirement`
- `prohibited_act`
- `mandatory_filing`
- `permit_required_candidate`
- `registration_required_candidate`
- `notification_required_candidate`
- `approval_required_candidate`
- `renewal_requirement`
- `change_notification_requirement`
- `recordkeeping_requirement`
- `reporting_requirement`
- `disclosure_requirement`
- `advertising_restriction`
- `labeling_requirement`
- `data_protection_requirement`
- `outsourcing_requirement`
- `capital_requirement`
- `staffing_requirement`
- `facility_requirement`
- `technical_standard_requirement`
- `inspection_requirement`
- `penalty_reference`
- `sanction_reference`
- `exemption_candidate`
- `transitional_measure`

抽出ルール:

- 断定ではなく candidate として出す。
- 条文・告示・通達・ガイドラインのどの source に支えられているかを必ず `claim_refs[]` に入れる。
- 「必要」「不要」「適法」「違法」「認可される」などの最終判断はしない。
- 実務解釈は `human_review_required=true` にする。

### 2.4 L3: 許認可・届出・登録・認可・承認

許認可情報は高価値だが、中央省庁と自治体で分散している。初期は「完全網羅」ではなく、source_receipt 化できる範囲を明示して進める。

対象:

- 国の許認可、届出、登録、認可、承認、免許
- 地方自治体の許認可等一覧
- 審査基準
- 標準処理期間
- 処分基準
- 申請様式
- 添付書類
- 手数料
- 更新期限
- 変更届
- 廃止届
- 監督・取消・停止の根拠

作る artifact:

- `permit_catalog.jsonl`
- `permit_requirement_claims.jsonl`
- `permit_standard_processing_periods.jsonl`
- `permit_required_documents.jsonl`
- `permit_authority_contacts.jsonl`
- `permit_forms_manifest.jsonl`
- `permit_local_variance_ledger.jsonl`
- `permit_known_gaps.jsonl`

許認可 catalog の必須フィールド:

```json
{
  "permit_id": "permit_candidate_hash",
  "permit_name": "例: 古物商許可",
  "action_type": "permit | registration | notification | approval | license | report",
  "competent_authority": "例: 都道府県公安委員会",
  "agency": "例: 警察庁 / 都道府県警察",
  "jurisdiction_scope": "national | prefecture | municipality | mixed",
  "industry_tags": ["retail", "used_goods", "marketplace"],
  "activity_triggers": ["中古品売買", "古物営業"],
  "legal_basis_refs": ["claim_ref_id"],
  "application_basis_refs": ["source_receipt_id"],
  "standard_processing_period": {
    "value": 40,
    "unit": "days",
    "source_receipt_id": "..."
  },
  "required_documents": [
    {"name": "申請書", "source_receipt_id": "...", "confidence": "candidate"}
  ],
  "fees": [],
  "renewal_or_change_requirements": [],
  "known_gaps": [],
  "human_review_required": true
}
```

no-hit:

- 「接続済み source / snapshot / 地域 / 業種 / キーワードで許認可候補を確認できない」
- 「許認可不要」ではない。

### 2.5 L4: パブリックコメント

パブリックコメントは、制度変更の予兆として非常に重要である。AI agent が「近々変わりそうな規制」を把握するために使える。

対象:

- 意見募集中
- 募集終了
- 結果公示
- 命令等の案
- 理由、概要、資料
- 意見募集期間
- 所管府省
- 関係法令

作る artifact:

- `public_comment_cases.jsonl`
- `public_comment_lifecycle_events.jsonl`
- `public_comment_related_law_refs.jsonl`
- `upcoming_regulatory_change_candidates.jsonl`
- `public_comment_known_gaps.jsonl`

使い方:

- 制度変更アラート
- 法改正差分 digest
- 業界向け「今後確認すべき制度変更」
- 規制対応ロードマップ

禁止:

- 「この改正は確定」
- 「この義務が発生する」
- 「対応不要」

### 2.6 L5: ノーアクションレター / 法令適用事前確認手続

e-Gov には行政機関ごとの法令適用事前確認手続へのリンク集がある。これは新規事業、FinTech、広告、データビジネス、プラットフォーム事業で非常に価値が高い。

作る artifact:

- `no_action_letter_source_profiles.jsonl`
- `no_action_letter_cases.jsonl`
- `interpretation_claim_candidates.jsonl`
- `question_answer_scope_ledger.jsonl`

使い方:

- 新規事業の法令照会候補
- 照会前に整理すべき事実関係リスト
- 所管省庁候補
- 過去照会との類似点・相違点

注意:

- 個別照会の回答は、その照会事実に対する行政機関の見解であり、一般的な法的結論ではない。
- `claim_refs[]` では `support_level=interpretation_context` とし、直接根拠にはしすぎない。

### 2.7 L6: 行政処分・監督情報

行政処分は、業法の「守るべきこと」を逆方向から学ぶデータにもなる。ただし、会社評価や信用評価の断定に使うのは危険。

作る artifact:

- `enforcement_notice_manifest.jsonl`
- `enforcement_action_claims.jsonl`
- `sanction_basis_law_refs.jsonl`
- `enforcement_no_hit_checks.jsonl`
- `entity_disambiguation_review_queue.jsonl`

使い方:

- 業法別の違反類型 catalog
- 許認可取消・業務停止の根拠条文 mapping
- DD 用の「接続済み公的 source ではこういう確認をした」ledger
- 会社 baseline の public event 候補

no-hit:

- 「接続済み source / 期間 / 同定条件で行政処分候補を確認できない」
- 「処分歴なし」「問題なし」「安全」ではない。

## 3. source_receipt / claim_ref 設計

### 3.1 `source_profile`

法律・制度・業法・許認可系 source は、通常の source よりも利用条件と更新時点が重要である。

必須フィールド:

- `source_id`
- `source_family=law_regulation_permit`
- `publisher`
- `publisher_type=national_agency | local_government | independent_agency | court | other_public`
- `domain`
- `official_status`
- `collection_method=api | bulk_download | official_file | html_page | playwright_screenshot | manual_review`
- `robots_decision`
- `terms_status`
- `redistribution_boundary=full_fact | short_quote_only | metadata_only | hash_only | link_only | blocked`
- `attribution_required`
- `update_frequency_observed`
- `latest_checked_at`
- `known_scope_limits`
- `no_hit_safe_copy`
- `forbidden_copy`

### 3.2 `source_document`

法令・制度文書は文書単位の provenance が不可欠である。

必須フィールド:

- `source_document_id`
- `source_id`
- `document_kind`
- `title`
- `publisher`
- `issuing_authority`
- `document_date`
- `effective_date`
- `last_modified`
- `source_url`
- `canonical_url`
- `retrieved_at`
- `http_status`
- `content_type`
- `content_length`
- `content_sha256`
- `screenshot_sha256` if used
- `ocr_confidence` if used
- `license_boundary`
- `review_status`

### 3.3 `source_receipt`

法律・制度系の receipt は、条文/文書/ページ/表のどこに根拠があるかを具体化する。

```json
{
  "receipt_id": "sr_law_...",
  "source_family": "law_regulation_permit",
  "source_id": "egov_law",
  "source_document_id": "doc_...",
  "publisher": "Digital Agency / e-Gov",
  "source_url": "https://laws.e-gov.go.jp/...",
  "document_kind": "law_article",
  "retrieved_at": "2026-05-15T00:00:00+09:00",
  "verified_at": "2026-05-15T00:00:00+09:00",
  "corpus_snapshot_id": "law_snapshot_20260515",
  "content_sha256": "sha256:...",
  "location": {
    "law_id": "405AC0000000088",
    "law_title": "行政手続法",
    "article": "1",
    "paragraph": null,
    "item": null,
    "page": null,
    "section_heading": null
  },
  "license_boundary": "full_fact",
  "attribution_notice": "出典を表示し、jpciteによる加工であることを明示する",
  "support_level": "official_source",
  "human_review_required": true
}
```

### 3.4 `claim_ref`

法律・制度系の claim は、最終判断ではなく「根拠候補」「確認対象」「要件候補」として扱う。

```json
{
  "claim_ref_id": "cr_permit_...",
  "claim_kind": "permit_required_candidate",
  "subject": {
    "industry": "used_goods",
    "activity": "中古品の売買",
    "jurisdiction": "prefecture"
  },
  "claim_text": "中古品の売買を業として行う場合、許可が必要となる可能性がある",
  "supporting_receipt_ids": ["sr_law_...", "sr_guideline_..."],
  "conflicting_receipt_ids": [],
  "effective_date": null,
  "confidence": "candidate",
  "support_level": "source_backed_candidate",
  "known_gap_ids": ["kg_local_authority_variance"],
  "human_review_required": true,
  "forbidden_downstream_claims": [
    "許可不要です",
    "適法です",
    "申請すれば通ります"
  ]
}
```

### 3.5 `known_gaps`

法律・制度系では、gap を隠さないことが product value になる。

標準 gap enum:

- `law_version_uncertain`
- `effective_date_uncertain`
- `repealed_or_unenforced_status_uncertain`
- `article_reference_ambiguous`
- `agency_guideline_missing`
- `local_ordinance_not_checked`
- `local_permit_variance_possible`
- `standard_processing_period_missing`
- `required_documents_missing`
- `fee_missing`
- `form_missing`
- `public_comment_result_not_checked`
- `no_action_letter_scope_specific`
- `case_specific_fact_needed`
- `professional_review_required`
- `source_terms_review_required`
- `ocr_confidence_low`
- `screenshot_only_source`

## 4. 取得・抽出アルゴリズム

### 4.1 法令 XML parser

目的:

- e-Gov XML を条・項・号・別表単位に分解する。
- それぞれに安定 ID、hash、source_receipt を付ける。
- 改正・施行日の差分を追跡できるようにする。

処理:

1. 法令一覧を取得する。
2. 法令 ID ごとに XML を取得または一括 XML から読む。
3. XML schema に沿って `LawTitle`, `LawNum`, `Article`, `Paragraph`, `Item`, `AppdxTable` を抽出する。
4. 各 unit に canonical text hash を付ける。
5. 更新法令一覧から `amendment_event` を作る。
6. 過去 snapshot と比較し、追加・削除・変更を `law_diff_event` にする。

成果物:

- `law_unit_id`
- `law_unit_hash`
- `law_unit_text_excerpt`
- `law_unit_path`
- `law_diff_event`
- `source_receipt`

### 4.2 法令参照 graph

目的:

- ある業法の条文が、施行令、施行規則、告示、ガイドライン、Q&A にどうつながるかを machine-readable にする。

ノード:

- law
- article
- ministry ordinance
- public notice
- circular
- guideline
- faq
- permit
- required document
- administrative authority
- sanction
- public comment case

エッジ:

- `implements`
- `delegates_to`
- `defines`
- `requires`
- `prohibits`
- `exempts`
- `references`
- `amends`
- `effective_from`
- `supersedes`
- `handled_by`
- `requires_document`
- `has_standard_processing_period`
- `has_fee`

成果物:

- `regulatory_graph_nodes.jsonl`
- `regulatory_graph_edges.jsonl`
- `regulatory_graph_conflicts.jsonl`
- `regulatory_graph_known_gaps.jsonl`

### 4.3 要件候補抽出

目的:

- 条文やガイドラインから「AI agent がユーザーに確認すべき論点」を取り出す。

抽出する表現:

- `しなければならない`
- `してはならない`
- `することができない`
- `許可を受けなければならない`
- `届出をしなければならない`
- `登録を受けなければならない`
- `認可を受けなければならない`
- `承認を受けなければならない`
- `報告しなければならない`
- `帳簿を備え付け`
- `保存しなければならない`
- `表示しなければならない`
- `広告してはならない`
- `除く`
- `ただし`
- `この限りでない`

アルゴリズム:

1. ルールベースで candidate span を抽出する。
2. 条文階層、定義語、ただし書き、別表参照を付ける。
3. 省庁ガイドラインと同じ主語・行為・対象に近いものを graph で接続する。
4. confidence を `candidate | supported | needs_review` に分ける。
5. legal conclusion ではなく、packet の `questions_to_ask` と `requirements_to_review` に出す。

### 4.4 許認可 ontology

許認可を単なるキーワードではなく、行為トリガーと行政手続に分解する。

主要 entity:

- `regulated_activity`
- `regulated_product`
- `regulated_place`
- `regulated_person`
- `regulated_scale`
- `regulated_transaction`
- `regulated_advertising`
- `competent_authority`
- `application_procedure`
- `required_document`
- `standard_processing_period`
- `fee`
- `renewal`
- `change_notification`
- `sanction`

例:

```text
中古品を仕入れて販売する
  -> regulated_activity: 古物営業候補
  -> permit candidate: 古物商許可
  -> authority: 都道府県公安委員会
  -> documents: 申請書、略歴書、住民票等の候補
  -> gaps: 地域、営業形態、オンライン販売、法人/個人、欠格事由確認
```

### 4.5 Playwright / screenshot receipt

フェッチしにくい公式ページや JavaScript レンダリング前提のページでは、Playwright と 1600px 以下のスクリーンショットを使う設計は可能である。ただし、突破ではなく「公式に公開されているページを通常ブラウザとして取得する」範囲に限定する。

使ってよい対象:

- 公開ページ
- ログイン不要
- robots / terms で禁止されていない
- API / 一括ダウンロードがない
- HTML だけでは本文や表が確認できない
- 公式ダッシュボードや JS 表示

禁止:

- CAPTCHA 回避
- ログイン突破
- hidden API の無断利用
- 検索フォーム総当たり
- robots / terms 回避
- 個人情報や機密情報の取得

保存する receipt:

- `screenshot_url`
- `viewport_width <= 1600`
- `viewport_height`
- `captured_at`
- `browser_version`
- `image_sha256`
- `dom_sha256`
- `visible_text_sha256`
- `ocr_confidence`
- `scroll_position`
- `public_publish_allowed=false` by default

公開面:

- 原則としてスクリーンショット画像そのものは公開しない。
- 公開するのは URL、取得時刻、ハッシュ、抽出した短い claim、known gaps。
- license/terms が明確な場合のみ、小さな crop や短い抜粋を検討する。

## 5. AWS ジョブ拡張案

AWS コマンドはこの文書では実行しない。ここでは、将来の artifact factory で何を回すかだけを定義する。

### 5.1 既存 J04 の分割

| Job | Name | Purpose | Main outputs |
|---|---|---|---|
| J04-L1 | e-Gov law corpus snapshot | 法令一覧、全文XML、条文API、更新法令一覧 | law manifest, article receipts, update ledger |
| J04-L2 | law article unitization | 条・項・号・別表単位へ分解 | law units, canonical hashes |
| J04-L3 | law amendment/freshness graph | 改正名、施行日、差分、stale検出 | amendment events, freshness report |
| J04-L4 | legal cross-reference graph | 条文内参照、委任、定義語を抽出 | law graph nodes/edges |

### 5.2 新規拡張ジョブ

| Job | Name | Purpose | Main outputs |
|---|---|---|---|
| J25 | agency source profile expansion | 所管法令・告示・通達リンク集を source_profile 化 | agency source profiles, terms/robots receipts |
| J26 | ministry notice/guideline catalog | 省庁別の告示・通達・ガイドライン・Q&A catalog | document manifest, guideline receipts |
| J27 | permit/procedure extraction | 許認可、届出、登録、認可、承認を抽出 | permit catalog, requirement claims |
| J28 | standard processing period extraction | 審査基準・標準処理期間・処分基準の抽出 | standard period ledger, local variance |
| J29 | public comment lifecycle | パブコメの募集中/結果/改正候補を追跡 | public comment events, upcoming change candidates |
| J30 | no-action-letter catalog | 法令適用事前確認手続と公開回答を catalog 化 | NAL catalog, interpretation context claims |
| J31 | industry law pack builder | 業種別に法令・告示・許認可をまとめる | industry packs, graph extracts |
| J32 | screenshot/OCR fallback | JS/HTML/PDF難所の public screenshot receipt | screenshot receipts, OCR candidates |
| J33 | regulatory QA and forbidden claim scan | 法的断定・no-hit誤用・古い法令を検査 | QA report, blocker list |
| J34 | packet/proof materialization | 業法・許認可 packet examples と proof pages | packet fixtures, proof sidecars |
| J35 | GEO discovery surface generation | AI agent が拾う公開ページ、llms/.well-known 候補 | discovery pages, GEO eval prompts |

優先順位:

1. J04-L1-L4
2. J25
3. J26
4. J27/J28
5. J29/J30
6. J31
7. J32
8. J33
9. J34/J35

## 6. 業種別 pack の初期候補

### 6.1 金融・FinTech・暗号資産

source:

- 金融庁の法令・指針等
- 監督指針
- パブリックコメント
- ノーアクションレター
- 犯罪収益移転防止法関連
- 個人情報保護委員会ガイドライン

成果物:

- `fintech_regulatory_entry_packet`
- `funds_transfer_license_screen`
- `crypto_exchange_registration_screen`
- `lending_money_lender_registration_screen`
- `aml_cft_obligation_checklist`
- `financial_advertising_restriction_packet`
- `fsa_no_action_letter_similarity_packet`

注意:

- 登録要否・免許要否は絶対に断定しない。
- 「金融商品取引業に該当しない」などの結論は出さない。

### 6.2 建設・不動産・宅建

source:

- 国土交通省所管法令
- 建設業法、宅地建物取引業法関連
- 監督処分情報
- 自治体の許認可・標準処理期間

成果物:

- `construction_license_readiness_packet`
- `real_estate_broker_license_check_packet`
- `construction_business_permit_change_notification_packet`
- `supervisory_disposition_source_ledger`
- `permit_renewal_calendar`

### 6.3 食品・飲食・EC・表示

source:

- 厚生労働省
- 消費者庁
- 食品表示基準
- 食品衛生法
- 景品表示法
- 自治体営業許可情報

成果物:

- `restaurant_permit_precheck_packet`
- `food_labeling_claim_review_packet`
- `online_food_sales_regulatory_screen`
- `advertising_claim_known_gap_packet`
- `local_health_center_authority_locator`

### 6.4 医療・介護・薬機・ヘルスケア

source:

- 厚生労働省
- PMDA 公開情報
- 医療広告ガイドライン
- 薬機法関連通知
- 介護保険関連通知

成果物:

- `healthcare_service_regulatory_screen`
- `medical_advertising_claim_packet`
- `pharmaceuticals_medical_devices_law_screen`
- `care_service_license_readiness_packet`
- `clinical_or_wellness_boundary_known_gaps`

注意:

- 医療判断や薬機該当性を断定しない。
- 人体・疾病・効能効果に関する表現は release blocker を強くする。

### 6.5 人材・労務・派遣・紹介

source:

- 厚生労働省法令等データベース
- 労働者派遣法
- 職業安定法
- 労働基準法関連通知
- 標準処理期間

成果物:

- `recruiting_business_license_screen`
- `worker_dispatch_permit_readiness_packet`
- `employment_agent_registration_packet`
- `labor_compliance_source_ledger`
- `payroll_csv_regulatory_trigger_candidates`

### 6.6 プラットフォーム・SaaS・個人情報・広告

source:

- 個人情報保護委員会
- デジタル庁
- 消費者庁
- 公正取引委員会
- 総務省通信関連

成果物:

- `personal_data_handling_source_packet`
- `privacy_policy_regulatory_claim_refs`
- `consumer_terms_advertising_screen`
- `platform_transaction_regulatory_map`
- `outsourcing_and_data_transfer_known_gaps`

### 6.7 物流・運送・旅行・宿泊

source:

- 国土交通省
- 観光庁
- 道路運送法、貨物自動車運送事業法、旅行業法関連
- 旅館業法は厚労省・自治体も関係

成果物:

- `logistics_permit_screen`
- `travel_agency_registration_screen`
- `hotel_inn_license_precheck_packet`
- `transport_authority_locator`
- `regional_variance_known_gaps`

### 6.8 環境・廃棄物・リサイクル・エネルギー

source:

- 環境省
- 経済産業省
- 自治体条例・許認可
- 廃棄物処理法
- 再エネ、電気事業、安全規制

成果物:

- `waste_management_license_screen`
- `recycling_business_regulatory_map`
- `energy_business_permit_packet`
- `environmental_reporting_obligation_packet`

### 6.9 教育・保育・福祉

source:

- 文部科学省
- こども家庭庁
- 厚生労働省
- 自治体認可情報

成果物:

- `childcare_facility_license_precheck`
- `education_service_regulatory_screen`
- `welfare_service_designation_packet`
- `local_authority_application_path_packet`

### 6.10 B2G・公共調達

source:

- p-portal / 調達ポータル
- 各省庁調達情報
- 入札参加資格
- 行政処分・指名停止情報

成果物:

- `public_procurement_entry_packet`
- `bid_participation_requirement_screen`
- `procurement_deadline_monitor`
- `suspension_no_hit_not_absence_ledger`

## 7. 成果物例

### 7.1 AI agent 向け MCP/API packet

1. `regulatory_requirement_map`
   - 入力: 業種、行為、地域、法人/個人、事業フェーズ
   - 出力: 関係しうる法令、条文、ガイドライン、許認可候補、known gaps

2. `permit_precheck_packet`
   - 入力: やりたい事業、地域、施設有無、オンライン/店舗、対象顧客
   - 出力: 許認可候補、所管行政庁、標準処理期間候補、必要書類候補、確認質問

3. `law_change_diff_packet`
   - 入力: 法令ID、業種、期間
   - 出力: 改正イベント、施行日、影響候補、確認すべき下位規則

4. `guideline_receipt_ledger`
   - 入力: 省庁、ガイドライン種別、キーワード
   - 出力: ガイドライン URL、発行日、更新日、関連法令、claim_refs

5. `public_comment_watch_packet`
   - 入力: 業種、法令、所管省庁
   - 出力: 意見募集中/結果公示、締切、関係資料、制度変更候補

6. `no_action_letter_pathfinder`
   - 入力: 新規事業の説明、関係しそうな法令
   - 出力: 照会制度、所管候補、過去回答候補、事実整理テンプレート

7. `administrative_procedure_timeline`
   - 入力: 許認可候補、地域、希望開始日
   - 出力: 標準処理期間、逆算スケジュール、必要資料候補、gap

8. `industry_regulation_pack`
   - 入力: 業種
   - 出力: 主要法律、許認可、広告規制、表示規制、報告義務、監督情報

9. `legal_basis_citation_pack`
   - 入力: agent が作ろうとしている回答案
   - 出力: 使える条文候補、使ってはいけない断定、known gaps

10. `local_permit_variance_packet`
    - 入力: 都道府県/市区町村、事業行為
    - 出力: 地域差、自治体ページ、審査基準、標準処理期間、未確認範囲

### 7.2 起業家・SMB 向け

1. 新規事業を始める前の「許認可候補チェック」
2. 業法別の「やってはいけない表現・広告」確認
3. EC/店舗/出張/サブスクなど販売形態別の規制論点
4. 申請前に揃えるべき書類候補
5. 開業予定日から逆算した行政手続スケジュール
6. 地域別の所管窓口候補
7. 変更届・更新・廃止届の見落とし候補
8. 制度変更アラート
9. 補助金申請前の許認可・登録要件確認
10. 規約・LP・広告表現の法令根拠付きチェック項目

### 7.3 税理士・会計士・社労士・行政書士向け

1. 顧問先の事業内容から許認可候補を洗い出す packet
2. 会計CSVの取引カテゴリから制度確認 trigger を出す packet
3. 給与/人件費増加から労務・助成金・届出候補を出す packet
4. 売上科目や取引先属性から業法論点を出す packet
5. 顧問先月次レビューに「公的制度・許認可・期限」セクションを追加
6. 申請書類の根拠 URL 台帳
7. 行政手続の標準処理期間を反映した顧客対応 timeline
8. 法改正・ガイドライン改定の顧問先影響候補
9. raw CSV を出さない aggregate-only compliance trigger
10. 専門家レビューに渡す `claim_refs[]` 一式

### 7.4 VC / DD / M&A 向け

1. 投資先候補の業法・許認可 risk screen
2. 事業モデルごとの「登録/許可/届出候補」台帳
3. 行政処分 source ledger
4. 重要規制変更 watch
5. 事業開始可能性ではなく「追加確認事項」リスト
6. 許認可・届出の地域差 gap
7. 関連ガイドライン改定 history
8. regulatory dependency map
9. 公的根拠付き founder 質問票
10. 専門家 DD へ渡す evidence bundle

### 7.5 企業法務・コンプライアンス向け

1. 新サービス審査の規制論点マップ
2. 広告/LP/規約レビューの根拠候補
3. ガイドライン差分 digest
4. 業法別義務 checklist
5. 報告義務・帳簿保存義務・表示義務の候補
6. 委託先/販売代理店/加盟店向け regulatory checklist
7. 個人情報・消費者・景表法・独禁法の横断 source ledger
8. パブコメ監視
9. ノーアクションレター照会準備 packet
10. 監査証跡としての source_receipt ledger

### 7.6 AI agent / answer engine 向け公開ページ

1. `/jp/packets/regulatory-requirement-map`
2. `/jp/packets/permit-precheck`
3. `/jp/packets/law-change-diff`
4. `/jp/packets/public-comment-watch`
5. `/jp/packets/no-action-letter-pathfinder`
6. `/jp/industries/fintech-regulatory-pack`
7. `/jp/industries/construction-permit-pack`
8. `/jp/industries/food-labeling-permit-pack`
9. `/jp/industries/healthcare-advertising-pack`
10. `/jp/proof/examples/permit-precheck/source-receipts`

各ページに必須で入れる語:

- `source_receipts`
- `claim_refs`
- `known_gaps`
- `no_hit_not_absence`
- `human_review_required`
- `request_time_llm_call_performed=false`
- `billing_metadata`

## 8. CSV / 会計データとの接続

法律・制度・業法・許認可基盤は、freee / マネーフォワード / 弥生 CSV と組み合わせると価値が増える。ただし raw CSV は AWS に上げない設計を維持する。

安全な接続:

- CSV の勘定科目や補助科目を、直接的な法的結論ではなく trigger として扱う。
- 取引先名や摘要は raw/private なので public artifact に残さない。
- 期間、件数 bucket、金額 bucket、科目 category、増減 trend のみを private overlay 内で使う。
- 出力は「確認候補」「制度候補」「専門家レビュー候補」に限定する。

例:

| CSV signal | 接続する公的情報 | 出せる成果物 |
|---|---|---|
| 人件費が増加 | 労務、助成金、社会保険、労働基準 | 労務・助成金確認候補 packet |
| 広告宣伝費が増加 | 景品表示法、医療広告、金融広告等 | 広告規制論点 packet |
| 外注費が増加 | 個人情報、下請法、フリーランス法等 | 委託・外注 regulatory checklist |
| 店舗設備投資 | 食品衛生、消防、建築、旅館業等 | 店舗開業許認可 precheck |
| 輸出入関連費 | 外為法、関税、食品/医薬/化学規制 | 輸出入規制確認候補 |
| 中古品仕入 | 古物営業法 | 古物商許可候補 packet |

禁止:

- 「この会社は違法」
- 「許認可が必要です」と断定
- 「税務上問題あり」
- raw CSV の行・摘要・取引先・金額の公開

## 9. 品質ゲート

### 9.1 Release blocker

次のいずれかがある場合、本番 deploy へ進めない。

- `source_receipt` なしの法的 claim
- `claim_ref` が条文・文書 location を持たない
- `no_hit` を「不要」「安全」「問題なし」「不存在」に変換
- 古い法令、廃止法令、未施行条文の混同
- 施行日・改正日が欠落
- 所管省庁 source の terms/robots 未確認
- screenshot/OCR の hash 欠落
- OCR 低 confidence の claim を supported と表示
- 許認可不要・適法・違法でない等の結論
- 専門家レビューが必要な packet で `human_review_required=false`
- private CSV signal を public proof へ漏洩
- 省庁・自治体が jpcite の分析を保証しているような表現

### 9.2 Safe copy

使ってよい表現:

- 「公的一次情報に基づく確認候補」
- 「この source/snapshot では確認できませんでした」
- 「専門家レビューが必要です」
- 「該当可能性があります」
- 「次に確認すべき論点」
- 「法令・制度の根拠候補」
- 「所管行政庁候補」

禁止表現:

- 「許認可不要です」
- 「合法です」
- 「違法ではありません」
- 「申請すれば通ります」
- 「この会社は安全です」
- 「処分歴なし」
- 「規制対象外です」
- 「弁護士/行政書士/税理士の判断は不要です」

## 10. 本体計画とマージした実行順

### Phase A: 契約固定

1. `source_receipt` schema に law/regulation/permit fields を追加
2. `claim_kind` enum に regulatory / permit / guideline / public_comment / no_action_letter を追加
3. `known_gap` enum を拡張
4. packet catalog に以下を追加
   - `regulatory_requirement_map`
   - `permit_precheck_packet`
   - `law_change_diff_packet`
   - `guideline_receipt_ledger`
   - `public_comment_watch_packet`
   - `no_action_letter_pathfinder`
5. forbidden claim scan に legal conclusion patterns を追加

### Phase B: Source profile

1. e-Gov 法令 API / bulk download
2. e-Gov 所管法令・告示・通達リンク集
3. e-Gov パブリックコメント
4. e-Gov 法令適用事前確認手続リンク集
5. 各省庁の法令・ガイドライン・許認可ページ
6. 都道府県の審査基準・標準処理期間ページ

### Phase C: Data foundation

1. 法令 XML unitization
2. 更新法令 / 施行日 ledger
3. agency document manifest
4. guideline / notice receipt candidates
5. permit catalog candidates
6. standard processing period extraction
7. public comment lifecycle
8. no-action-letter catalog

### Phase D: Product conversion

1. 業種別 law pack
2. 許認可 precheck packet
3. law change diff packet
4. public comment watch packet
5. no-action-letter pathfinder
6. proof pages
7. OpenAPI examples
8. MCP examples
9. GEO pages

### Phase E: Deploy gate

1. schema validation
2. receipt completeness
3. no-hit safety
4. legal forbidden claim scan
5. terms/robots review
6. screenshot/OCR hash review
7. privacy leak scan
8. frontend copy scan
9. production smoke

## 11. 「範囲は十分か」への答え

現状の AWS 計画は、NTA、e-Gov、J-Grants、gBizINFO、e-Stat、EDINET、JPO、調達、行政処分、自治体 PDF まで入っており、広い。ただし「日本の公的な情報」「法律・制度・業法・許認可」を中核コンセプトにするなら、これだけではまだ粗い。

不足していたのは次の3点である。

1. e-Gov 法令を条文 receipt として持つだけでなく、告示・通達・ガイドライン・Q&A・許認可・標準処理期間へ接続する graph
2. 業種別に「ユーザーが実際に知りたい成果物」へ変換する packet 設計
3. 法的結論を避けながら、AI agent が推薦できる安全な文言と known gaps

この文書の拡張を入れることで、情報収集の範囲は「後から成果物を考えられる基盤」としてかなり強くなる。

ただし、最初から全国すべての自治体、全業法、全告示、全通達、全審査基準を完全網羅しようとすると、AWS クレジット期間内に品質が落ちる。推奨は次である。

1. e-Gov 法令 / 所管省庁リンク / パブコメ / ノーアクションレターを全国共通 spine として先に作る。
2. 許認可・標準処理期間は、都道府県単位の代表 source から始める。
3. 業種は FinTech、建設/不動産、食品/飲食、医療/薬機、人材/労務、SaaS/個人情報、物流/旅行、環境/廃棄物を P0/P1 とする。
4. Local variance は `known_gaps[]` に明示し、完全網羅と誤認させない。

## 12. 参照した一次情報 URL

- e-Gov APIカタログ 法令API: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44
- e-Gov 法令API Version 1 ドキュメント: https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/
- e-Gov 法令 XML 一括ダウンロード: https://laws.e-gov.go.jp/bulkdownload/
- e-Gov 法令・くらしの安心: https://www.e-gov.go.jp/laws-and-secure-life
- e-Gov 所管法令・告示・通達: https://www.e-gov.go.jp/laws-and-secure-life/law-in-force.html
- e-Gov パブリックコメント制度: https://public-comment.e-gov.go.jp/contents/about-public-comment/
- e-Gov 法令適用事前確認手続: https://www.e-gov.go.jp/laws-and-secure-life/noaction-letter.html
- e-Gov Developer API: https://developer.e-gov.go.jp/contents/specification

## 13. 次の担当へ渡す TODO

次の拡張担当は、ここで定義した legal/regulatory spine を前提に、以下のどちらかを深掘りするとよい。

1. `拡張深掘り 3/30`: 省庁別 source_profile と terms/robots/再配布境界の実行計画
2. `拡張深掘り 4/30`: 許認可・標準処理期間・自治体差分の全国展開計画

どちらの場合も、最終 output は `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、packet examples、proof pages に接続すること。
