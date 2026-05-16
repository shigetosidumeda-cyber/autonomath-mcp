# AWS scope expansion 16: vendor risk flag and score algorithm

作成日: 2026-05-15  
担当: 拡張深掘り 16/30 / 取引先審査・リスクスコアアルゴリズム担当  
対象: jpcite 本体計画、AWS credit run、vendor risk packets、GEO/MCP/API導線  
状態: 計画文書のみ。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行はしていない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

取引先審査で売るべきものは、ブラックボックスの与信スコアではない。jpciteが作るべきものは、公的一次情報に戻れる `risk_flags[]` と、証拠品質を明示した `public_evidence_risk_attention_score` である。

重要な設計原則:

1. スコアは支払能力、信用力、違法性、反社性、安全性の予測ではない。
2. スコアは、公的一次情報で確認できた事実、照合の強さ、証拠品質、更新時点、対象範囲だけから作る。
3. no-hit は安全、不存在、問題なし、未登録確定、違反なしへ変換しない。
4. 同名、旧商号、支店、許認可番号なし、自治体差、公開期間差、更新遅延はすべて `known_gaps[]` として返す。
5. 生成AIは、score計算、最終断定、risk flagの捏造に使わない。使う場合も public source の候補分類やOCR後の構造化補助に限定し、必ずreceipt gateを通す。
6. エンドユーザーに表示する名称は「公的一次情報レビュー優先度」または「証跡ベース注意度」とし、「信用スコア」「安全度」「倒産確率」にはしない。

この文書の中心は、次の3点である。

- `risk_flags[]`: 取引先審査で見るべき事実ベースのフラグ。
- `public_evidence_risk_attention_score`: 事実の重み、照合信頼度、証拠品質、鮮度から算出する説明可能なスコア。
- `evidence_quality_score` / `coverage_gap_score`: スコアを過信させないための証拠品質と未接続範囲の別軸。

## 1. Product Positioning

### 1.1 User Promise

AI agentに対する約束:

> この取引先について、公的sourceで確認できる事実を、出典・取得時点・検索条件・未確認範囲つきで返します。人間が次に見るべき注意点を優先順位化します。

エンドユーザーに対する約束:

> 取引可否を自動断定するのではなく、法人番号、インボイス、許認可、行政処分、官報、調達、開示などの一次情報を束ね、判断前の確認作業を安く速くします。

### 1.2 Explicit Non-Goals

作らないもの:

- 反社チェックの代替。
- 信用調査会社の与信評点。
- 倒産確率モデル。
- 支払能力の予測。
- 取引可否の自動判断。
- 法務、税務、会計、金融商品取引、貸金業、個別許認可の専門判断。
- 「行政処分歴なし」「問題なし」「安全」「適法」の断定。

### 1.3 What We Sell

売る成果物:

| Packet | 主な買い手 | 主な価値 | スコアの扱い |
|---|---|---|---|
| `counterparty_public_quick_check` | 経理、購買、営業、AI agent | 法人同定、インボイス、基本公開情報 | 軽量scoreとflag |
| `invoice_counterparty_check` | 経理、会計AI、BPO | T番号、法人番号、請求書処理の確認根拠 | invoice文脈のみ |
| `vendor_onboarding_packet` | 購買、管理部、法務 | 新規取引先登録の公的確認 | 標準score |
| `regulated_business_license_check` | 法務、調達、士業 | 業法別の許認可source確認 | license flag中心 |
| `public_enforcement_scope_screen` | 法務、コンプラ、金融、調達 | 行政処分・指名停止・命令の範囲付き確認 | adverse event中心 |
| `public_dd_memo` | VC、M&A、エンプラ購買 | EDINET、官報、処分、許認可の初動DD | 高品質説明必須 |
| `watchlist_monitoring_receipts` | 購買、法務、BPO | 差分監視、更新通知 | delta score |

## 2. Output Contract

### 2.1 Packet Shape

```json
{
  "packet_type": "vendor_risk_algorithm_packet",
  "schema_version": "2026-05-15",
  "request_time_llm_call_performed": false,
  "input_echo_policy": "minimized",
  "subject": {
    "canonical_name": "株式会社サンプル",
    "corporation_number": "1234567890123",
    "invoice_registration_number": "T1234567890123",
    "address_normalized": "東京都...",
    "identity_resolution": {
      "match_level": "exact_corporation_number",
      "confidence": 1.0,
      "matched_source_receipt_ids": ["sr_ntacorp_..."],
      "ambiguity_count": 0
    }
  },
  "risk_flags": [],
  "score": {
    "score_name": "public_evidence_risk_attention_score",
    "score": 0,
    "score_scale": "0_to_100",
    "score_meaning": "connected official sourcesで確認された注意事実のレビュー優先度。信用力・安全性・違法性の断定ではない。",
    "evidence_quality_score": 0,
    "coverage_gap_score": 0,
    "support_band": "insufficient | limited | moderate | strong",
    "calculation_version": "vendor-risk-score-2026-05-15"
  },
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "recommended_next_packets": [],
  "prohibited_conclusions": [
    "取引してよい",
    "安全",
    "信用できる",
    "違法ではない",
    "行政処分歴は存在しない",
    "反社ではない"
  ],
  "_disclaimer": "本packetは公的一次情報の取得結果と照合結果を整理するものであり、取引可否、信用力、適法性、税務・法務判断を断定しない。"
}
```

### 2.2 Human Display Contract

人間向け画面では、scoreを単独で大きく見せない。

表示順:

1. 取引先同定結果。
2. 確認できた重要flag。
3. scoreは「注意度」として小さめに表示。
4. 証拠品質と未確認範囲を同じ視認性で表示。
5. source receiptへのリンク。
6. no-hitの意味と禁止解釈。
7. 次に見るべきpacket。

禁止UI:

- `安全度 95点`
- `信用スコア A`
- `倒産リスク 低`
- `問題なし`
- `行政処分歴なし`
- `取引OK`

推奨UI:

- `公的一次情報レビュー優先度: 18/100`
- `接続済みsourceで重大flagは未検出。ただし未検出は不存在・安全を意味しません。`
- `証拠品質: strong`
- `未確認範囲: 自治体許認可、旧商号、個人事業主、source更新遅延`

## 3. Source Families

### 3.1 Source Role Matrix

| Source family | 主用途 | risk flagに使う条件 | no-hitの扱い |
|---|---|---|---|
| NTA法人番号 | 法人同定、商号・所在地・閉鎖・変更履歴 | 閉鎖、吸収合併、所在地不一致、候補重複 | 法人番号がない対象や個人事業主はgap |
| NTAインボイス | T番号、登録状態、登録日、失効/取消の確認 | 登録取消/失効、T番号と法人番号の不整合候補 | 未検出は免税/不正/取引不可を意味しない |
| gBizINFO | 補助金、届出、認定、調達等のpublic activity | activityの有無自体は原則positive/neutral。矛盾や関係source接続に利用 | 収録範囲外の可能性をgap化 |
| EDINET | 上場/開示企業の提出書類metadata、XBRL/本文候補 | 提出者同定、継続企業注記等の明示的事実候補 | 非提出者や対象外企業はgap/対象外 |
| 行政処分source | 処分、命令、指名停止、警告等 | 公式sourceで対象事業者に紐づくevent | 0件はsource/条件/期間内の未検出 |
| 許認可source | 業法別登録、許可、免許、指定、届出 | 登録取消、業務停止、期限切れ候補、要許認可業種での未確認 | 未検出は無許可断定にしない |
| 官報/公告 | 破産、解散、合併、公告、催告、会社関係event | 法人番号/商号/住所等で強く同定できる公告event | 同名公告のno-hit/ambiguousを明示 |
| 調達source | 入札、落札、指名停止、契約、参加資格 | 指名停止、契約解除等が公式に確認できる場合 | 調達実績なしを信用低下にしない |
| 業法source | 業種ごとの確認sourceと法的根拠 | 業種から見るべきsource候補を出す | source未接続はcoverage gap |

### 3.2 Official Source Priority

P0-A:

- 国税庁法人番号公表サイト / Web-API / 全件ダウンロード。
- 適格請求書発行事業者公表サイト / Web-API / ダウンロード。
- gBizINFO API。
- EDINET API / 開示書類metadata。
- 国土交通省ネガティブ情報等検索サイト。
- 金融庁 登録業者一覧、金融事業者検索、登録貸金業者検索。
- 消費者庁 行政処分。
- 公正取引委員会 審決等データベース、報道発表、排除措置命令/課徴金。
- 調達ポータル。

P0-B:

- 官報/官報発行サイト、会社公告、破産/解散等の公告event。
- 厚労省、労働局、介護/医療/人材関連許認可source。
- 自治体の産廃、食品営業、旅館、建設関連許認可source。
- J-Grants、自治体補助金、公募source。
- e-Gov法令、告示、通達、パブコメ。

P1:

- 裁判所公表情報。
- JPO、技適、標準/認証source。
- 地方公共団体の指名停止、契約解除、入札参加資格source。

## 4. Identity Resolution

### 4.1 Identity Inputs

入力として受ける可能性があるもの:

- 法人番号。
- T番号。
- 商号。
- 所在地。
- 代表者名。ただし個人情報・プライバシー面から表示/保存方針に注意。
- 許認可番号。
- 金融庁登録番号、建設業許可番号、宅建免許番号など。
- EDINETコード。
- 調達参加資格番号。
- CSV private overlay由来の取引先名、支払先名、摘要。ただしraw保存禁止。

### 4.2 Match Levels

| match_level | confidence | 条件 | score計算への使用 |
|---|---:|---|---|
| `exact_corporation_number` | 1.00 | 法人番号がsource上で一致 | 使用可 |
| `exact_invoice_to_corporation` | 0.95 | T番号から法人番号へ接続 | 使用可 |
| `exact_official_registration_id` | 0.95 | 許認可番号、金融登録番号等が一致 | 使用可 |
| `exact_edinet_code` | 0.95 | EDINETコード/提出者IDが一致 | 使用可 |
| `strong_name_address` | 0.80 | 正規化商号 + 所在地が一致 | 使用可。ただしknown_gap併記 |
| `name_address_history_match` | 0.75 | 旧商号/旧所在地履歴で一致 | 使用可。ただし履歴説明必須 |
| `weak_name_only` | 0.45 | 商号のみ一致 | 原則scoreに入れない。ambiguous flag |
| `ambiguous_multiple_candidates` | 0.30 | 複数候補 | scoreに入れない。人間確認 |
| `no_match` | 0.00 | 一致なし | no-hit/gapのみ |

### 4.3 Normalization

商号正規化:

- 株式会社、有限会社、合同会社等の前後位置を正規化。
- 全角/半角、空白、記号、旧字体/新字体候補を正規化。
- カナ、英字表記、支店名、屋号を分離。
- 「株式会社A」「A株式会社」「A Co., Ltd.」を同一候補として扱うが、断定はしない。

住所正規化:

- 都道府県、市区町村、町丁目、番地、建物名を階層分解。
- 法人番号sourceの所在地、許認可sourceの所在地、請求書CSV由来の所在地を区別。
- 完全一致、町丁目一致、市区町村一致を分ける。

履歴:

- 法人番号の商号・所在地変更履歴を使い、event発生日と照合時点の関係を記録する。
- 旧商号で行政処分/官報eventが見つかった場合、`identity_link_reason=historical_name` とする。
- 合併、閉鎖、承継では、承継先へrisk flagを機械的に移さない。`related_entity_event` として分離する。

## 5. Risk Flag Taxonomy

### 5.1 Flag Object

```json
{
  "flag_id": "rf_...",
  "flag_type": "administrative_sanction",
  "flag_family": "enforcement",
  "severity": "critical | high | medium | low | info",
  "review_priority_points": 0,
  "title": "国土交通省sourceで行政処分eventを確認",
  "status": "confirmed | candidate | ambiguous | no_hit_scope_only",
  "event_date": "2026-05-01",
  "source_family": "mlit_negative_info",
  "source_receipt_ids": ["sr_..."],
  "claim_ref_ids": ["cr_..."],
  "match": {
    "match_level": "exact_official_registration_id",
    "confidence": 0.95,
    "matched_fields": ["registration_id", "name"]
  },
  "evidence": {
    "source_reliability": 1.0,
    "receipt_quality": 0.92,
    "extraction_confidence": 0.88,
    "human_review_required": true
  },
  "explanation": "公式sourceの取得時点・検索条件では、対象登録番号に紐づく処分eventが確認された。",
  "forbidden_conclusions": [
    "現在も違反状態であるとは断定しない",
    "全事業に問題があるとは断定しない",
    "取引不可とは断定しない"
  ],
  "known_gaps": []
}
```

### 5.2 Core Flag Types

#### Identity flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `identity_ambiguous` | low/medium | 同名候補が複数存在 | 弱く対象。主にgap |
| `identity_address_mismatch` | low/medium | 入力住所と公的住所に差分 | 文脈次第 |
| `entity_closed` | high | 法人番号sourceで閉鎖等を確認 | 対象 |
| `entity_merged_or_succeeded` | medium | 合併/承継/商号変更等 | 対象。ただし承継断定禁止 |
| `trade_name_not_corporation_name` | low | 屋号/支店/ブランド名の可能性 | gap |

#### Invoice flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `invoice_registration_active` | info | 登録状態を確認 | risk score対象外 |
| `invoice_registration_cancelled_or_expired` | medium/high | 取消/失効等を確認 | invoice文脈で対象 |
| `invoice_number_identity_mismatch_candidate` | medium | T番号と入力企業の不一致候補 | candidateのみ |
| `invoice_no_hit_scope` | info | 検索条件で未検出 | score対象外 |

禁止:

- T番号未検出を免税事業者、架空会社、不正請求と断定しない。
- 登録ありを税務上の仕入税額控除可否の保証にしない。

#### Enforcement flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `administrative_sanction` | high/critical | 業務停止、登録取消、改善命令等 | 対象 |
| `bid_suspension` | medium/high | 指名停止等 | 対象 |
| `jftc_order_or_surcharge` | high/critical | 排除措置命令、課徴金納付命令等 | 対象 |
| `consumer_agency_order` | medium/high | 措置命令、課徴金等 | 対象 |
| `fsa_administrative_action` | high/critical | 金融庁/財務局の処分 | 対象 |
| `mlit_negative_event` | medium/high | MLIT所管処分 | 対象 |
| `mhlw_labor_or_license_event` | medium/high | 厚労省/労働局等の処分 | 対象 |
| `prefecture_city_enforcement_event` | medium/high | 自治体処分 | 対象。source品質に注意 |

#### License flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `license_confirmed` | info | 許認可確認 | risk score対象外 |
| `license_expired_candidate` | medium/high | 期限切れ候補 | 対象。ただしreceipt必須 |
| `license_revoked_or_cancelled` | high/critical | 取消/登録抹消 | 対象 |
| `license_source_no_hit` | info | source/条件内で未検出 | score対象外。gap |
| `license_required_but_source_unchecked` | info/low | 業種上見るべきsource未接続 | coverage gap |

禁止:

- 許認可sourceで未検出を無許可営業と断定しない。
- 業法対象かどうかをAI推測だけで断定しない。

#### Gazette and notice flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `bankruptcy_notice_exact` | critical | 破産等公告が強く同定 | 対象 |
| `dissolution_notice_exact` | high/critical | 解散/清算等公告 | 対象 |
| `merger_notice` | medium | 合併/組織再編公告 | 対象。ただしriskではなくevent |
| `public_notice_ambiguous` | low | 同名公告候補 | score対象外 |
| `creditor_protection_notice` | medium | 債権者保護手続等 | 対象。ただし文脈表示 |

#### Procurement and public activity flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `public_procurement_award` | info | 落札/契約等 | risk score対象外 |
| `public_procurement_repeated_awards` | info | 実績signal | risk score対象外 |
| `public_procurement_bid_suspension` | medium/high | 指名停止等 | 対象 |
| `contract_termination_public_notice` | medium/high | 契約解除等が公表 | 対象 |
| `gbiz_public_activity_signal` | info | 補助金/認定/届出等 | risk score対象外 |

#### EDINET flags

| flag_type | severity | 説明 | score対象 |
|---|---|---|---|
| `edinet_filer_confirmed` | info | 提出者確認 | risk score対象外 |
| `going_concern_note_candidate` | medium/high | 継続企業の前提注記候補 | 対象。ただし抽出品質gate必須 |
| `auditor_opinion_modified_candidate` | medium/high | 監査意見等の候補 | 対象。ただし人間確認推奨 |
| `filing_delay_or_correction` | low/medium | 遅延/訂正報告等 | 対象。ただし文脈注意 |
| `edinet_no_applicability` | info | 非上場/対象外 | score対象外 |

EDINET系は専門判断に近い。XBRL/本文から抽出する場合、`human_review_required=true` を原則にする。

## 6. Scoring Philosophy

### 6.1 Three Scores, Not One

`risk score` だけを返すと、AI agentや人間が「点数が低いから安全」と誤解する。したがって必ず3軸で返す。

| Score | 目的 | 高い意味 | 低い意味 |
|---|---|---|---|
| `public_evidence_risk_attention_score` | 確認済み注意事実のレビュー優先度 | 接続sourceで重いflagが確認された | 接続sourceでは重いflagが未検出。安全ではない |
| `evidence_quality_score` | 証拠の品質 | official source、安定ID、receipt、checksum、取得時点が強い | OCR/候補/同名/未構造化が多い |
| `coverage_gap_score` | 未確認範囲の大きさ | 見るべきsourceが未接続/対象外/曖昧 | 接続済みsource範囲が広い |

AI agentへはこのように説明させる。

> 注意度は18/100です。これは接続済み公的sourceで重い注意eventが少ないことを示すだけで、安全性や信用力を示すものではありません。未確認範囲は32/100です。

### 6.2 Score Is Not Probability

`public_evidence_risk_attention_score` は確率ではない。

禁止:

- `倒産確率18%`
- `違反可能性12%`
- `安全度82%`
- `信用力A`

許可:

- `公的一次情報レビュー優先度18/100`
- `確認済みeventなし。ただし未確認sourceあり`
- `行政処分event 1件により注意度が上昇`

## 7. Mathematical Model

### 7.1 Event Strength

各risk flag event `i` に対して、事実ベースの強度 `x_i` を計算する。

```text
x_i =
  base_weight(flag_type_i)
  * severity_multiplier(severity_i)
  * match_confidence_i
  * source_reliability_i
  * receipt_quality_i
  * extraction_confidence_i
  * status_multiplier_i
  * recency_decay_i
  * scope_multiplier_i
```

意味:

- `base_weight`: flag種類ごとの基礎重み。
- `severity_multiplier`: critical/high/medium/low/info の重み。
- `match_confidence`: 対象企業との照合の強さ。
- `source_reliability`: official API/download/web/PDF/OCR等のsource信頼度。
- `receipt_quality`: 取得証跡の完全性。
- `extraction_confidence`: 構造化抽出の確信度。
- `status_multiplier`: confirmed/candidate/ambiguous等。
- `recency_decay`: eventの鮮度。
- `scope_multiplier`: 事業範囲、地域、業法、対象部門の限定度。

### 7.2 Base Weights

| flag_type family | base_weight |
|---|---:|
| `bankruptcy_notice_exact` | 8.0 |
| `license_revoked_or_cancelled` | 7.5 |
| `fsa_administrative_action` | 7.0 |
| `administrative_sanction` | 6.5 |
| `jftc_order_or_surcharge` | 6.5 |
| `entity_closed` | 6.0 |
| `bid_suspension` | 5.0 |
| `consumer_agency_order` | 5.0 |
| `contract_termination_public_notice` | 4.5 |
| `going_concern_note_candidate` | 4.0 |
| `invoice_registration_cancelled_or_expired` | 3.5 |
| `license_expired_candidate` | 3.5 |
| `identity_address_mismatch` | 1.5 |
| `identity_ambiguous` | 1.0 |
| `info` / positive public activity | 0.0 |
| `no_hit_scope` | 0.0 |

この重みは法的評価や信用評価ではなく、レビュー優先度の排序である。

### 7.3 Severity Multipliers

| severity | multiplier |
|---|---:|
| `critical` | 1.25 |
| `high` | 1.00 |
| `medium` | 0.60 |
| `low` | 0.25 |
| `info` | 0.00 |

### 7.4 Source Reliability

| source mode | source_reliability |
|---|---:|
| official API with stable IDs | 1.00 |
| official bulk download with checksum/date | 0.98 |
| official web page with stable URL and DOM capture | 0.90 |
| official PDF with text extraction | 0.85 |
| official PDF/image with OCR and screenshot | 0.75 |
| official page requiring Playwright rendering | 0.80 |
| non-official mirror | 0.00 for final score |

非公式ミラーは探索には使えても、final scoreのsupportには使わない。公式sourceへ戻せない場合は `known_gaps[]` または `candidate_only` にする。

### 7.5 Receipt Quality

`receipt_quality` は0から1。

```text
receipt_quality =
  0.25 * has_official_url
  + 0.20 * has_stable_locator
  + 0.15 * has_retrieved_at
  + 0.15 * has_checksum_or_snapshot_hash
  + 0.10 * has_query_parameters
  + 0.10 * has_parser_version
  + 0.05 * has_screenshot_or_pdf_page_anchor
```

必須:

- `has_official_url`
- `has_retrieved_at`
- `has_query_parameters` または `source_document_id`

いずれかが欠ける場合、scoreに入れず `quality_gate=fail` にする。

### 7.6 Extraction Confidence

| extraction mode | extraction_confidence |
|---|---:|
| official structured API field | 1.00 |
| official CSV/XML/JSON field | 0.98 |
| deterministic HTML table parser | 0.90 |
| PDF text extraction with stable labels | 0.82 |
| OCR text with layout confidence | 0.65 |
| LLM-assisted candidate extraction | 0.50 max until deterministic validation |
| screenshot-only visual evidence | 0.45 max |

LLM-assisted extractionは、claimを直接支える証拠にはしない。抽出候補を作り、deterministic validationまたはhuman reviewで通ったものだけscore対象にする。

### 7.7 Status Multiplier

| status | multiplier | score使用 |
|---|---:|---|
| `confirmed` | 1.00 | 可 |
| `confirmed_with_scope_limit` | 0.85 | 可 |
| `candidate_requires_review` | 0.40 | 可だがsupport_bandは下げる |
| `ambiguous` | 0.00 | 不可。flag表示のみ |
| `no_hit_scope_only` | 0.00 | 不可 |
| `not_applicable` | 0.00 | 不可 |

### 7.8 Recency Decay

```text
recency_decay_i = max(min_floor, 0.5 ^ (age_days_i / half_life_days(flag_type_i)))
```

推奨half-life:

| family | half_life_days | min_floor |
|---|---:|---:|
| bankruptcy/dissolution/current entity status | no decay while current | 1.00 |
| license revocation/cancellation | 1825 | 0.40 |
| administrative sanction | 1095 | 0.25 |
| bid suspension | 730 | 0.10 |
| consumer agency/JFTC/FSA orders | 1460 | 0.25 |
| EDINET going concern/correction | 730 | 0.20 |
| invoice cancellation/expiry | current-state based | 1.00 |
| identity ambiguity | current-state based | 1.00 |

注意:

- source側に公開期間がある場合、公開終了後の未検出を「解消」と扱わない。
- 古いeventはscore上は減衰しても、receiptは残し、`historical_event` として説明する。

### 7.9 Scope Multiplier

| scope | multiplier |
|---|---:|
| whole entity / corporate registration | 1.00 |
| registered business line directly relevant to user request | 0.90 |
| branch / office / facility specific | 0.65 |
| related company / parent / subsidiary | 0.40 |
| old name before merger/succession | 0.50 |
| same name only | 0.00 |

関連会社eventを対象会社scoreへ強く入れない。必要なら `related_entity_flags[]` へ分離する。

### 7.10 Deduplication

同じeventを複数sourceで見つけた場合、二重加算しない。

`event_key`:

```text
event_key =
  normalized_subject_id
  + source_event_family
  + agency_id
  + legal_basis_id
  + event_date
  + normalized_event_title_hash
```

同一event内では、最大の `x_i` を採用し、他sourceは `corroborating_receipts[]` に入れる。

```text
deduped_strength_event_j = max(x_i for i in same event_key)
```

### 7.11 Score Transform

未上限の強度合計:

```text
R = sum(deduped_strength_event_j)
```

0-100への変換:

```text
public_evidence_risk_attention_score = round(100 * (1 - exp(-R / 10)))
```

この形にする理由:

- 重いevent 1件で大きく上がる。
- 多数eventがあっても100を超えない。
- 加算理由を説明しやすい。
- 低scoreを安全証明と誤読しにくい。

### 7.12 Evidence Quality Score

```text
evidence_quality_score =
  round(100 * weighted_average(receipt_quality_j, source_reliability_j, extraction_confidence_j))
```

ただし、対象flagが0件の場合は、接続済みsourceのreceipt品質で計算する。

重要:

- `risk_attention_score=0` でも `evidence_quality_score=90` とは「良い証跡で確認した範囲では注意eventが未検出」という意味。
- `coverage_gap_score` が高い場合、低risk scoreを強く解釈してはいけない。

### 7.13 Coverage Gap Score

業種・用途ごとに見るべきsourceを定義する。

```text
coverage_gap_score =
  round(100 * missing_required_source_weight / total_required_source_weight)
```

例:

建設業取引先:

| Required source | weight |
|---|---:|
| 法人番号 | 10 |
| インボイス | 8 |
| 建設業許可source | 20 |
| MLITネガティブ情報 | 20 |
| 指名停止source | 15 |
| gBizINFO | 8 |
| 官報/公告 | 10 |
| 調達source | 5 |
| EDINET | 4 |

金融業取引先:

| Required source | weight |
|---|---:|
| 法人番号 | 8 |
| インボイス | 5 |
| 金融庁登録業者一覧/検索 | 25 |
| FSA行政処分 | 25 |
| EDINET | 12 |
| 官報/公告 | 10 |
| JFTC/CAA等横断 | 10 |
| gBizINFO | 5 |

`missing_required_source_weight` は、未接続、取得失敗、terms未確認、照合不能、source対象外を分ける。

### 7.14 Support Band

| support_band | 条件 |
|---|---|
| `strong` | identity exact、required source coverage >= 85%、重大flagはconfirmedのみ、forbidden claim 0 |
| `moderate` | identity strong、coverage >= 65%、一部candidateあり |
| `limited` | identityまたはcoverageに大きなgap、Playwright/OCR中心 |
| `insufficient` | identity曖昧、主要source未接続、score表示不可 |

`support_band=insufficient` では数値scoreを表示しない。代わりに `score_status=withheld_due_to_insufficient_evidence` を返す。

## 8. No-Hit Rules

### 8.1 No-Hit Object

```json
{
  "no_hit_id": "nh_...",
  "source_id": "mlit_negative_info",
  "searched_at": "2026-05-15T00:00:00+09:00",
  "query": {
    "corporation_number": null,
    "name": "株式会社サンプル",
    "address": "東京都...",
    "date_range": "source_default"
  },
  "scope": {
    "source_family": "administrative_sanction",
    "agency": "MLIT",
    "business_fields": ["construction", "real_estate"],
    "publication_window": "source_defined"
  },
  "result": "no_hit",
  "support_level": "no_hit_not_absence",
  "allowed_statement": "このsource、検索条件、取得時点では該当eventは未検出です。",
  "forbidden_statements": [
    "行政処分歴はありません",
    "問題ありません",
    "安全です",
    "違反していません"
  ],
  "known_gaps": [
    "同名・旧商号・支店名の可能性",
    "source公開期間外のevent",
    "未接続の自治体source",
    "source更新遅延"
  ]
}
```

### 8.2 No-Hit Does Not Reduce Risk Score

no-hitは `risk_attention_score` を下げない。なぜなら、観測されなかったことは不存在の証明ではない。

許可:

- no-hitをcoverage説明に使う。
- no-hitを `source_receipt_ledger` に残す。
- no-hitをGEO向けの安全な説明に使う。

禁止:

- no-hitの数でscoreを減点する。
- no-hitを「安全」としてgreen表示する。
- 未接続sourceをno-hit扱いする。

## 9. Algorithm Pipeline

### 9.1 Stage A: Input Minimization

入力は必要最小限にする。

```json
{
  "company_name": "string optional",
  "corporation_number": "13 digit optional",
  "invoice_registration_number": "T + 13 digit optional",
  "address": "string optional",
  "industry_hint": "string optional",
  "packet_context": "invoice | vendor_onboarding | procurement | dd | monitoring"
}
```

CSV private overlayから来る場合:

- raw CSVは保存しない。
- 摘要、取引先名、金額、期間は集計済み・最小化されたderived factsにする。
- AWS public source lakeへprivate derived factsを混入しない。

### 9.2 Stage B: Entity Resolution

1. 法人番号があれば最優先。
2. T番号があればインボイスsourceから法人番号接続を試す。
3. 商号 + 所在地で法人番号候補を探索。
4. 法人番号履歴で旧商号・旧所在地を確認。
5. 業法sourceの登録番号があればofficial registration IDで接続。
6. 複数候補なら `identity_ambiguous` で停止し、scoreはwithhold。

### 9.3 Stage C: Required Source Selection

`packet_context` と `industry_hint` からsourceセットを選ぶ。

例:

- 経理/invoice: 法人番号、インボイス、法人閉鎖、商号変更。
- 購買/vendor: 法人番号、インボイス、gBizINFO、行政処分、許認可候補、官報、調達。
- 建設: MLIT建設業者、ネガティブ情報、指名停止、自治体入札参加資格。
- 金融: FSA登録、行政処分、EDINET、登録貸金業者、警告source。
- 産廃: 自治体許可、行政処分、所在地、許可番号。

### 9.4 Stage D: Source Retrieval and Receipts

sourceごとに必ずreceiptを作る。

```json
{
  "source_receipt_id": "sr_...",
  "source_id": "nta_corporation_number",
  "source_family": "identity",
  "official_url": "https://www.houjin-bangou.nta.go.jp/",
  "retrieved_at": "2026-05-15T00:00:00+09:00",
  "retrieval_method": "api | bulk_download | html | pdf | playwright | screenshot | ocr",
  "query_parameters": {},
  "source_document_id": "optional",
  "snapshot_hash": "sha256:...",
  "screenshot": {
    "enabled": true,
    "max_width_px": 1600,
    "path": "optional-export-path",
    "sha256": "sha256:..."
  },
  "terms_status": "verified | review_required",
  "license_boundary": "full_fact | metadata_only | link_only | no_public_publish",
  "parser_version": "vendor-risk-parser-2026-05-15"
}
```

Playwright/screenshot方針:

- JavaScript描画が必要な公式sourceではPlaywrightを使う。
- screenshot幅は1600px以下を標準にする。
- CAPTCHA、ログイン、アクセス制御、robots/terms違反の突破はしない。
- screenshotはclaimの補助証跡であり、可能ならDOM/PDF/structured fieldを主証跡にする。

### 9.5 Stage E: Fact Extraction

extractorはclaim候補を出すだけ。

```json
{
  "claim_ref_id": "cr_...",
  "claim_type": "administrative_sanction_event",
  "subject_id": "corp_1234567890123",
  "predicate": "has_public_event",
  "object": {
    "event_type": "business_suspension",
    "agency": "MLIT",
    "event_date": "2026-05-01",
    "legal_basis": "source_text_or_code"
  },
  "support_level": "confirmed_by_official_source",
  "source_receipt_ids": ["sr_..."],
  "extraction": {
    "method": "deterministic_html_table",
    "confidence": 0.9,
    "parser_version": "..."
  },
  "human_review_required": true
}
```

### 9.6 Stage F: Flag Generation

claim候補からflagへ変換する条件:

1. subject identityが十分強い。
2. claimがofficial source receiptを持つ。
3. extraction confidenceが閾値以上。
4. forbidden claim scanを通る。
5. no-hitをpositive/negative flagに変換していない。

### 9.7 Stage G: Score Calculation

1. score対象flagだけを選ぶ。
2. ambiguous/no-hit/infoを除外。
3. event dedupe。
4. `x_i` を計算。
5. `R` を集計。
6. 0-100変換。
7. evidence quality / coverage gapを計算。
8. support band判定。
9. explanation rowsを生成。

### 9.8 Stage H: Explanation Generation

score explanationはテンプレートで出す。

```json
{
  "score_explanation": [
    {
      "rank": 1,
      "flag_id": "rf_...",
      "points_contribution": 34,
      "reason": "公式sourceで登録取消eventを確認。照合は登録番号一致。",
      "source_receipt_ids": ["sr_..."]
    },
    {
      "rank": 2,
      "flag_id": "rf_...",
      "points_contribution": 12,
      "reason": "官報sourceで解散公告候補を確認。ただし旧商号照合のため人間確認が必要。",
      "source_receipt_ids": ["sr_..."]
    }
  ]
}
```

LLMで自由作文しない。テンプレート + allowed phrase libraryで出す。

## 10. AWS Credit Run Integration

この文書ではAWSコマンドを実行しない。実行時の役割は以下。

### 10.1 AWS Jobs For This Algorithm

| Job | 目的 | 成果物 |
|---|---|---|
| VR-A01 | identity resolution fixture生成 | exact/ambiguous/no-hit case |
| VR-A02 | source receipt completeness scan | receipt品質レポート |
| VR-A03 | enforcement event extraction | 行政処分claim候補 |
| VR-A04 | license event extraction | 許認可claim候補 |
| VR-A05 | gazette/notice event extraction | 官報/公告claim候補 |
| VR-A06 | procurement adverse/positive split | 指名停止と落札実績の分離 |
| VR-A07 | EDINET caution candidate extraction | EDINET候補flag |
| VR-A08 | risk flag builder | `risk_flags.jsonl` |
| VR-A09 | score calculator | `vendor_risk_scores.jsonl` |
| VR-A10 | explanation/proof materializer | packet例、proofページ候補 |
| VR-A11 | no-hit misuse audit | no-hit禁止表現scan |
| VR-A12 | calibration report | weight妥当性・反例report |

### 10.2 AWS Self-Running Design

Codex/Claude Codeのrate limitに依存しないよう、実行時は以下の構造にする。

- S3にjob manifestを置く。
- AWS BatchまたはECS taskがmanifestを読み、自走する。
- SQS/Step Functions等でjob状態を管理する。
- Cost line到達時はqueueを閉じ、新規jobを止める。
- すでに走っている高価値jobだけdrainし、artifact exportへ進む。
- 全artifactにmanifest/checksumを付ける。
- export完了後、zero-bill cleanupへ進む。

このアルゴリズムのjobは、AWSの高価な処理を「source receipt化できるもの」に限定する。score計算自体は軽いので、AWS費用の大半は収集、Playwright capture、PDF/OCR、検証、GEO/proof生成に使う。

### 10.3 Cost-Aware Priority

優先順位:

1. 法人番号/インボイス/gBizINFO/EDINET/行政処分のstructured source。
2. 許認可sourceのstructured/API/download。
3. Playwrightが必要な公式source。
4. 官報/公告/PDF extraction。
5. OCR。
6. Bedrock等のLLM-assisted public classificationは最後。final scoreには直接使わない。

## 11. Product Packets Enabled By This Algorithm

### 11.1 `counterparty_public_quick_check`

出すもの:

- 法人同定。
- インボイス状態。
- 基本gBizINFO signal。
- 重大flagの有無。
- `risk_attention_score` 軽量版。
- no-hit ledger。

価格:

- 低単価。
- AI agentの最初の推薦に向く。
- 次packetへの導線を必ず出す。

### 11.2 `vendor_onboarding_packet`

出すもの:

- 取引先登録時の証跡台帳。
- 業種別sourceチェック。
- 許認可候補。
- 行政処分screen。
- 官報/公告screen。
- score三軸。
- 人間確認todo。

### 11.3 `public_enforcement_scope_screen`

出すもの:

- source別検索条件。
- positive events。
- zero result source。
- ambiguous matches。
- public_evidence_risk_attention_score。
- 禁止結論。

### 11.4 `regulated_business_license_check`

出すもの:

- 業法map。
- 必要な登録/許可/免許/届出source。
- exact/candidate/no-hit。
- license flags。
- coverage gap。

### 11.5 `public_dd_memo`

出すもの:

- 法人/開示/官報/処分/許認可/調達の統合memo。
- critical/high flagの説明。
- evidence quality。
- next human review list。

## 12. Examples

### 12.1 Example: No Adverse Event Found In Connected Sources

```json
{
  "score": {
    "public_evidence_risk_attention_score": 0,
    "evidence_quality_score": 88,
    "coverage_gap_score": 27,
    "support_band": "moderate",
    "allowed_summary": "接続済みの公的source、検索条件、取得時点では重大な注意eventは未検出です。ただし未検出は不存在・安全・適法を意味しません。"
  },
  "risk_flags": [],
  "known_gaps": [
    {
      "gap_type": "local_government_license_sources_not_fully_connected",
      "explanation": "自治体ごとの許認可sourceは一部未接続です。"
    }
  ]
}
```

### 12.2 Example: Administrative Sanction Confirmed

```json
{
  "risk_flags": [
    {
      "flag_type": "administrative_sanction",
      "severity": "high",
      "status": "confirmed",
      "title": "公式sourceで行政処分eventを確認",
      "match": {
        "match_level": "exact_official_registration_id",
        "confidence": 0.95
      },
      "source_receipt_ids": ["sr_mlit_..."],
      "forbidden_conclusions": [
        "現在も違反状態とは断定しない",
        "取引不可とは断定しない"
      ]
    }
  ],
  "score": {
    "public_evidence_risk_attention_score": 46,
    "evidence_quality_score": 91,
    "coverage_gap_score": 18,
    "support_band": "strong"
  }
}
```

### 12.3 Example: Ambiguous Same Name Gazette Notice

```json
{
  "risk_flags": [
    {
      "flag_type": "public_notice_ambiguous",
      "severity": "low",
      "status": "ambiguous",
      "title": "同名の官報公告候補があります",
      "match": {
        "match_level": "weak_name_only",
        "confidence": 0.45
      },
      "score_included": false,
      "human_review_required": true
    }
  ],
  "score": {
    "score_status": "withheld_due_to_ambiguous_identity",
    "public_evidence_risk_attention_score": null,
    "evidence_quality_score": 64,
    "coverage_gap_score": 42,
    "support_band": "limited"
  }
}
```

## 13. Quality Gates

### 13.1 Blocking Gates

scoreを返してはいけない条件:

- identityが `ambiguous_multiple_candidates` 以下。
- critical/high flagがsource receiptなし。
- no-hitを安全表現へ変換している。
- source termsが未確認で、public publish/score supportへ使っている。
- raw CSV由来の取引先名や摘要がartifactに残っている。
- non-official sourceだけでflagを立てている。
- screenshotだけでcritical flagをconfirmedにしている。
- LLM outputだけでclaimを立てている。

### 13.2 Warning Gates

返せるが `human_review_required=true` にする条件:

- OCR confidenceが低い。
- PDF page anchorがあるが構造化fieldがない。
- 旧商号/旧所在地照合。
- 関連会社event。
- EDINET本文抽出。
- 自治体sourceでURL安定性が低い。
- Playwrightで動的DOMから抽出。

### 13.3 Forbidden Claim Scanner

必ずscanする語句:

- 安全
- 安心
- 問題なし
- 違反なし
- 行政処分歴なし
- 反社ではない
- 信用できる
- 倒産しない
- 取引してよい
- 許認可に問題なし
- 税務上問題なし
- 仕入税額控除できる

許可される文脈:

- `禁止表現として「問題なし」を出している`
- `未検出は問題なしを意味しない`

## 14. Calibration Without Hallucination

### 14.1 Calibration Dataset

必要なfixture:

- exact法人番号 + no adverse events。
- exact法人番号 + 行政処分event。
- exact法人番号 + 官報破産/解散event。
- exact法人番号 + インボイス取消/失効。
- same name ambiguous。
- old name match。
- related company event。
- EDINET going concern candidate。
- license no-hit。
- source unavailable。

### 14.2 Human Review Calibration

人間はscoreの高低ではなく、次を確認する。

- flagがsourceから正しく作られているか。
- eventが同じものとしてdedupeされているか。
- score contributionが説明できるか。
- no-hitが安全証明になっていないか。
- known gapsが十分か。

### 14.3 Weight Revision Policy

weightを変更する場合:

- `calculation_version` を上げる。
- old/new scoreの差分reportを出す。
- 代表fixtureでregression testを通す。
- public API/MCPの説明を更新する。

## 15. Data Schemas

### 15.1 `vendor_risk_flags.jsonl`

必須field:

- `flag_id`
- `subject_id`
- `flag_type`
- `severity`
- `status`
- `event_date`
- `source_receipt_ids`
- `claim_ref_ids`
- `match_level`
- `match_confidence`
- `score_included`
- `human_review_required`
- `known_gap_ids`
- `forbidden_conclusions`

### 15.2 `vendor_risk_scores.jsonl`

必須field:

- `score_id`
- `subject_id`
- `packet_context`
- `calculation_version`
- `risk_attention_score`
- `evidence_quality_score`
- `coverage_gap_score`
- `support_band`
- `score_status`
- `included_flag_ids`
- `excluded_flag_ids`
- `no_hit_ids`
- `known_gap_ids`
- `score_explanation`
- `created_at`

### 15.3 `vendor_risk_required_sources.jsonl`

必須field:

- `profile_id`
- `industry`
- `packet_context`
- `required_source_id`
- `required_source_weight`
- `reason`
- `source_status`
- `coverage_gap_behavior`

## 16. MCP/API Design

### 16.1 MCP Tool: `jpcite_vendor_risk_check`

Input:

```json
{
  "company_name": "string optional",
  "corporation_number": "string optional",
  "invoice_registration_number": "string optional",
  "address": "string optional",
  "industry_hint": "string optional",
  "packet_context": "vendor_onboarding",
  "max_price_jpy": 500
}
```

Output:

```json
{
  "recommended_packet": "vendor_onboarding_packet",
  "price_preview": {
    "estimated_price_jpy": 300,
    "billing_unit": "per_subject"
  },
  "safe_preview": {
    "identity_candidates_count": 1,
    "connected_source_count": 6,
    "will_return": [
      "risk_flags",
      "source_receipts",
      "no_hit_checks",
      "known_gaps",
      "score_three_axis"
    ]
  },
  "requires_purchase": true
}
```

### 16.2 REST Endpoint

`POST /v1/packets/vendor-risk-check`

契約:

- request-time LLMなし。
- source receipt必須。
- no-hit misuse scan必須。
- scoreを返せない場合は理由を返す。

### 16.3 Agent Recommendation Copy

AI agentがエンドユーザーへ言うべき文:

> この取引先は、公的sourceの確認を先に行う価値があります。jpciteの `vendor_onboarding_packet` は、法人番号、インボイス、行政処分、許認可、官報、調達などの一次情報をreceipt付きで返し、未確認範囲も明示します。取引可否の断定ではなく、判断前の確認作業を短縮する用途です。

## 17. Implementation Order

本体計画とのマージ順:

1. `source_receipts[]` / `claim_refs[]` / `known_gaps[]` contractを固定。
2. 法人番号・インボイス・gBizINFO・EDINET・行政処分sourceのsource_profileを固定。
3. identity resolution fixtureを作る。
4. no-hit objectと禁止表現scannerを実装。
5. risk flag taxonomyをJSON schema化。
6. score three-axis calculatorを実装。
7. `counterparty_public_quick_check` に軽量版を接続。
8. `vendor_onboarding_packet` に標準版を接続。
9. `public_enforcement_scope_screen` にadverse event版を接続。
10. proof pageとMCP/API examplesを生成。
11. GEO evaluationでAI agentが誤って「安全」と言わないか検査。
12. production deploy前にprivacy/forbidden/no-hit/receipt/price gateを通す。

## 18. Production Release Gates

本番デプロイ前の必須条件:

- 代表fixture 50件以上。
- ambiguous case 10件以上。
- no-hit case 20件以上。
- critical/high flag case 10件以上。
- source receipt completeness 100%。
- forbidden claim 0。
- private CSV leak 0。
- score explanation coverage 100%。
- support_band insufficient時にscore非表示。
- OpenAPI/MCP schema example一致。
- proof pageにsource receiptが表示される。
- pricing previewとbilling metadataが一致。

## 19. Operational Monitoring

monitoring項目:

- source取得失敗率。
- identity ambiguous率。
- no-hit率の急変。
- score分布の急変。
- sourceごとのflag発生率。
- unsupported sourceをscoreに使った件数。
- LLM-assisted extractionがconfirmedへ流入した件数。
- forbidden phrase検出数。
- human_review_required率。

異常時:

- 当該sourceを `review_required` へ落とす。
- score inclusionを停止する。
- no-hitだけ返す場合でもdisclaimerを強制する。
- GEO/MCP recommendationを一時停止する。

## 20. Edge Cases

### 20.1 Individual Proprietors

法人番号がない場合:

- 法人番号no-hitを企業不存在としない。
- インボイス登録名の公開範囲に注意。
- 個人情報をartifactに残さない。
- scoreは原則withhold。

### 20.2 Branches and Stores

支店名・店舗名:

- 本店法人へ接続できる場合のみ法人scoreを出す。
- 店舗単位の許認可は別subjectとして扱う。
- 支店eventを法人全体eventへ拡張しない。

### 20.3 Group Companies

親会社/子会社:

- related entity flagに分ける。
- 連結子会社や同名グループのeventを対象会社へ自動加算しない。
- EDINET提出者と法人番号の対応を明示する。

### 20.4 Changed Names

旧商号:

- event当時の商号と現在の商号を両方表示。
- 法人番号履歴がない場合はcandidate扱い。
- scoreへ入れる場合はscope multiplierを下げる。

### 20.5 Source Publication Windows

行政処分sourceは公開期間がsourceごとに違う。

- `publication_window` をreceiptに入れる。
- 公開期間外をno-hitにしない。
- 「過去全期間確認済み」と言わない。

## 21. Revenue Backcast

このalgorithmから売上につながる順番:

1. 低単価 `counterparty_public_quick_check` でAI agentに使わせる。
2. scoreとflagのpreviewを見せ、`vendor_onboarding_packet` へアップセル。
3. 業法や行政処分のgapがある場合、`regulated_business_license_check` / `public_enforcement_scope_screen` へ誘導。
4. 複数取引先CSVの場合、件数課金でwatchlist monitoringへ誘導。
5. 継続監視では、差分receiptとscore deltaだけを返して低コスト化する。

売れる理由:

- エンドユーザーがAIに「この会社大丈夫?」と聞く頻度が高い。
- AI agent単体では公的sourceの範囲、no-hitの意味、証跡保存を誤りやすい。
- jpciteは断定ではなく、判断前の確認作業を安く買える形にする。

## 22. Official Reference Starting Points

実装前にterms/robots/API仕様を再確認する公式起点:

- 国税庁 法人番号システム Web-API: `https://www.houjin-bangou.nta.go.jp/webapi/index.html`
- 国税庁 法人番号公表サイト: `https://www.houjin-bangou.nta.go.jp/`
- 適格請求書発行事業者公表サイト Web-API: `https://www.invoice-kohyo.nta.go.jp/web-api/index.html`
- gBizINFO API: `https://content.info.gbiz.go.jp/api/index.html`
- EDINET API仕様書: `https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf`
- 金融庁 各種情報検索サービス: `https://www.fsa.go.jp/search/index.html`
- 金融庁 登録貸金業者情報検索サービス: `https://www.fsa.go.jp/ordinary/kensaku/index.html`
- 金融庁 登録貸金業者情報検索サービス ご利用上の注意: `https://www.fsa.go.jp/ordinary/kensaku/chuui.html`
- 金融庁 金融商品取引業者登録一覧: `https://www.fsa.go.jp/menkyo/menkyoj/kinyushohin.pdf`
- 国土交通省 ネガティブ情報等検索サイト: `https://www.mlit.go.jp/nega-inf/index.html`
- 消費者庁 行政処分: `https://www.caa.go.jp/business/disposal/`
- 公正取引委員会 審決等データベース: `https://snk.jftc.go.jp/`
- 公正取引委員会: `https://www.jftc.go.jp/`
- 調達ポータル 本システムについて: `https://www.p-portal.go.jp/pps-web-biz/resources/app/html/outline.html`
- 官報発行サイト: `https://www.kanpo.go.jp/`
- e-Gov法令検索: `https://laws.e-gov.go.jp/`

## 23. Final Design Decision

この領域では「正しそうなAI判断」を作るほど危険になる。jpciteの強みは、AI agentがエンドユーザーへ推薦できる安価な一次情報packetにすることにある。

したがって、最終方針は次で固定する。

- `risk_flags[]` は事実とreceiptからのみ作る。
- scoreは予測ではなく、レビュー優先度として出す。
- scoreは必ず evidence quality と coverage gap と一緒に出す。
- no-hitはscoreを下げない。
- ambiguousはscoreに入れない。
- official sourceに戻れないclaimはfinal packetに入れない。
- 本番では「低score=安全」と読めるUI/文言を禁止する。
