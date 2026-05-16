# AWS scope expansion 26: data quality and source receipt gates

作成日: 2026-05-15
対象: 拡張深掘り 26/30。データ品質・source_receipt品質ゲート担当。
状態: 計画のみ。AWS CLI/API、AWSリソース作成、収集ジョブ実行、デプロイは行わない。
出力: `/Users/shigetoumeda/jpcite/docs/_internal/aws_scope_expansion_26_data_quality_gates.md` のみ。

## 0. 結論

広げた日本公的一次情報コーパスは、単に大量に集めるだけでは本番投入できない。jpcite の商品価値は「AIエージェントが安く、速く、出典付き成果物を返せること」だが、その根幹は `source_receipt` の品質である。

本番投入可否は、次の順番で fail-closed に判定する。

1. `source_profile` が成立しているか
2. `license_boundary` が claim 利用を許すか
3. `robots/terms` が取得方式を許すか
4. 取得物の `content_hash` と canonical hash が再現可能か
5. Playwright 取得では `screenshot_receipt` が空白・過大・不正画面でないか
6. OCR 取得では confidence と人手確認要否が明示されているか
7. `claim_ref` が最小 fact 単位で、根拠 receipt と N:M で結ばれているか
8. `known_gap` が不足・古さ・規約制約・矛盾を隠していないか
9. `no-hit` が「不存在」や「安全」に変換されていないか
10. staleness が source family ごとの TTL 内か
11. conflict が検出・分類・公開表示されているか
12. packet/proof/API/MCP に出してよい visibility か

このゲートを通らないデータは、AWSで生成済みでも本番へ入れない。公開成果物、MCP/API応答、GEO向け proof page、価格付き packet fixture のいずれにも使わない。

## 1. この文書の位置づけ

### 1.1 接続する既存計画

この文書は以下の既存計画を品質判定に寄せて統合する。

| 既存文書 | この文書で受け取るもの |
|---|---|
| `aws_credit_unified_execution_plan_2026-05-15.md` | AWS credit run の大枠、J01-J24、zero-bill前提 |
| `aws_credit_review_08_artifact_manifest_schema.md` | manifest、checksum、quality gate schema |
| `aws_credit_review_11_source_terms_robots.md` | terms/robots/license/no-hit安全表現 |
| `aws_scope_expansion_06_playwright_capture.md` | Playwright/1600px以下スクリーンショット取得基盤 |
| `source_receipt_claim_graph_deepdive_2026-05-15.md` | `claim_ref`、`source_receipt`、`source_profile` のグラフ契約 |
| `aws_scope_expansion_13_algorithmic_output_engine.md` | LLM自由生成ではない成果物生成エンジン |
| `aws_scope_expansion_17_reg_change_diff_algorithm.md` | 法令・制度差分検出 |
| `aws_scope_expansion_18_csv_overlay_algorithm.md` | private CSV overlay の安全な派生fact化 |
| `aws_scope_expansion_24_agent_api_ux.md` | AI agent向けAPI/MCP/UX契約 |

### 1.2 目的

目的は、AWS credit run で大量生成する public official corpus を、次の4段階で本番利用できる品質に落とし込むことである。

| 段階 | 判定対象 | 出力 |
|---|---|---|
| Source gate | 出典そのもの | `source_profile` / `license_terms_ledger` / `robots_receipt` |
| Capture gate | 取得証跡 | `source_document` / `screenshot_receipt` / `ocr_receipt` / hashes |
| Claim gate | fact化 | `claim_ref` / `claim_source_link` / `known_gap` / no-hit ledger |
| Product gate | 公開成果物 | packet examples / proof pages / API/MCP responses |

### 1.3 最重要方針

- AWSは短期の artifact factory であり、本番の常時依存先ではない。
- request-time LLM は使わない。`request_time_llm_call_performed=false` を維持する。
- private CSV raw data は AWS へ上げない、保存しない、ログしない。
- 公的情報でも、利用条件が不明なものは `metadata_only` または `link_only` に落とす。
- no-hit は必ず `no_hit_not_absence` として扱う。
- 矛盾は多数決で潰さない。`source_conflict` として見せる。
- 本番投入の基本は `pass` ではなく `pass_with_known_gaps_allowed` である。公的情報は完全網羅を保証しないため、gapを隠さない。

## 2. 品質ゲートの状態 enum

### 2.1 Gate status

すべての source、artifact、dataset、claim、packet は `gate_status` を持つ。

| status | 意味 | 本番利用 |
|---|---|---|
| `pass` | 必須項目を満たし、公開利用に阻害なし | 可 |
| `pass_with_warnings` | 軽微な警告あり。表示に注意を付ければ可 | 可 |
| `pass_with_known_gaps` | 不足を `known_gaps[]` で明示すれば可 | 可 |
| `manual_review_required` | 人手確認まで保留 | 不可 |
| `metadata_only` | 本文・claim根拠に使えず、URL/メタ情報のみ可 | 限定可 |
| `link_only` | リンク紹介のみ可 | 限定可 |
| `quarantine` | 取得物は隔離。成果物利用不可 | 不可 |
| `block` | 規約・安全・品質で禁止 | 不可 |

### 2.2 Severity

| severity | 例 | 処理 |
|---|---|---|
| `info` | 取得件数が想定より少ない | レポートのみ |
| `warning` | source更新日が古いがTTL内 | `known_gap` 付与 |
| `major` | OCR confidence不足、license不明 | manual review |
| `critical` | private data leak、規約違反、no-hit誤表現 | block |

### 2.3 Production decision

最終判断は `production_decision` として残す。

```json
{
  "production_decision": "publish_allowed",
  "allowed_surfaces": ["api", "mcp", "proof_page", "packet_example"],
  "requires_human_review": false,
  "must_display_known_gaps": true,
  "must_display_attribution": true,
  "raw_redistribution_allowed": false
}
```

値は以下に固定する。

| decision | 意味 |
|---|---|
| `publish_allowed` | 公開API/MCP/packet/proofへ利用可 |
| `agent_only_allowed` | 機械可読メタ情報のみ。一般公開ページは保留 |
| `internal_fixture_only` | テスト・評価用のみ |
| `metadata_link_only` | URL、タイトル、取得時刻、hash程度のみ |
| `private_packet_only` | tenant private overlay内のみ |
| `do_not_publish` | 公開不可 |

## 3. 必須 schema

### 3.1 `source_profile`

`source_profile` は出典の契約・所有者・更新ポリシーであり、URL単位の取得結果ではない。1つの source family に複数 profile があってよい。

```json
{
  "schema_id": "jpcite.source_profile",
  "schema_version": "2026-05-15",
  "source_profile_id": "sp_egov_law_api_v1",
  "source_family": "law_regulation",
  "publisher": {
    "name": "e-Gov",
    "organization_type": "national_government",
    "country": "JP",
    "official_domain": "laws.e-gov.go.jp"
  },
  "source_kind": "official_api",
  "entrypoints": [
    {
      "entrypoint_id": "ep_egov_law_api",
      "url": "https://laws.e-gov.go.jp/api/1/lawlists/1",
      "method": "GET",
      "access_mode": "api"
    }
  ],
  "license_boundary": "full_fact",
  "terms_status": "verified",
  "robots_status": "api_or_download_preferred",
  "redistribution_policy": {
    "raw_redistribution": "not_required",
    "metadata_redistribution": "allowed_with_attribution",
    "short_quote": "allowed_with_attribution",
    "derived_fact": "allowed_with_attribution",
    "full_text": "review_required"
  },
  "update_policy": {
    "declared_update_frequency": "daily_or_as_published",
    "observed_update_frequency": "unknown_until_run",
    "staleness_ttl_days": 7
  },
  "quality_gate": {
    "status": "pass",
    "checked_at": "2026-05-15T00:00:00+09:00",
    "reviewer": "planning",
    "blocking_issues": []
  }
}
```

### 3.2 `source_receipt`

`source_receipt` は「ある時点で、ある方法により、ある出典状態を観測した証跡」である。claimよりも低レイヤーであり、positive receipt と no-hit receipt を分ける。

```json
{
  "schema_id": "jpcite.source_receipt",
  "schema_version": "2026-05-15",
  "source_receipt_id": "sr_4d2b6d0a6b9c",
  "source_profile_id": "sp_egov_law_api_v1",
  "receipt_kind": "positive_observation",
  "capture_method": "official_api",
  "source_url": "https://laws.e-gov.go.jp/...",
  "canonical_url": "https://laws.e-gov.go.jp/...",
  "http": {
    "status": 200,
    "final_url": "https://laws.e-gov.go.jp/...",
    "retrieved_at": "2026-05-15T00:00:00+09:00"
  },
  "hashes": {
    "raw_content_sha256": "sha256:...",
    "canonical_content_sha256": "sha256:...",
    "visible_text_sha256": "sha256:..."
  },
  "location": {
    "selector": null,
    "text_anchor_hash": "sha256:...",
    "page_number": null,
    "row_key": null
  },
  "support_capability": {
    "can_support_claim": true,
    "support_level": "direct",
    "allowed_claim_fields": ["law.title", "law.article_text", "law.enforcement_date"]
  },
  "quality_gate": {
    "status": "pass",
    "known_gap_ids": [],
    "warning_count": 0,
    "blocking_issue_count": 0
  }
}
```

### 3.3 `claim_ref`

`claim_ref` はAIが成果物内で利用できる最小 fact である。

```json
{
  "schema_id": "jpcite.claim_ref",
  "schema_version": "2026-05-15",
  "claim_id": "claim_6b2f1c5f2a4e",
  "claim_stable_key": "csk_7b91c3c75f96",
  "namespace": "pub",
  "claim_kind": "public_source_fact",
  "subject_kind": "law",
  "subject_id": "law:egov:example",
  "field_name": "article.title",
  "canonical_value_hash": "sha256:...",
  "display_value": "第X条",
  "value_display_policy": "normalized_fact_allowed",
  "valid_time_scope": "as_of:2026-05-15",
  "support_level": "direct",
  "source_receipt_ids": ["sr_4d2b6d0a6b9c"],
  "known_gap_ids": [],
  "visibility": "public",
  "quality_gate": {
    "status": "pass",
    "conflict_status": "none",
    "staleness_status": "fresh"
  }
}
```

### 3.4 `known_gap`

```json
{
  "schema_id": "jpcite.known_gap",
  "schema_version": "2026-05-15",
  "known_gap_id": "kg_9b82c1e3",
  "gap_type": "source_stale",
  "severity": "warning",
  "scope": "claim",
  "message_key": "source_stale_within_ttl",
  "affected_source_receipt_ids": ["sr_..."],
  "affected_claim_ids": ["claim_..."],
  "public_copy_allowed": true,
  "blocks_publish": false,
  "created_at": "2026-05-15T00:00:00+09:00"
}
```

### 3.5 `quality_gate_report`

AWS run 後の export package には必ずこれを含める。

```json
{
  "schema_id": "jpcite.quality_gate_report",
  "schema_version": "2026-05-15",
  "run_id": "aws-credit-2026-05-15-r001",
  "generated_at": "2026-05-15T00:00:00+09:00",
  "summary": {
    "source_profiles_total": 0,
    "source_profiles_pass": 0,
    "source_profiles_block": 0,
    "source_receipts_total": 0,
    "claim_refs_total": 0,
    "known_gaps_total": 0,
    "no_hit_receipts_total": 0,
    "conflict_groups_total": 0,
    "publish_blocking_issue_count": 0,
    "private_leak_count": 0,
    "no_hit_misuse_count": 0
  },
  "production_decision": "do_not_publish",
  "blocking_issues": [],
  "warning_groups": [],
  "recommended_next_action": "run_source_profile_gate_first"
}
```

## 4. Gate 01: `source_profile` quality

### 4.1 何を見るか

`source_profile` は以下を満たさなければならない。

| 項目 | 必須 | block条件 |
|---|---:|---|
| official publisher | 必須 | 出典主体が不明 |
| official domain | 必須 | 第三者転載だけ |
| source kind | 必須 | API/CSV/PDF/HTML/Playwright等が不明 |
| entrypoint | 必須 | URL/API/ダウンロード元がない |
| terms URL or terms basis | 必須 | 利用条件未確認 |
| robots decision | HTML/Playwrightでは必須 | robots不明で大量クロール予定 |
| license boundary | 必須 | claim利用可否不明 |
| update policy | 必須 | staleness判定不能 |
| attribution requirement | 必須 | 出典表示が設計不能 |
| PII risk class | 必須 | 個人情報含有可能性未評価 |
| stable identifier policy | 必須 | subject IDを作れない |

### 4.2 Source profile score

本番投入前の参考スコア。スコアは pass/block の代替ではなく、優先順位付けに使う。

```text
source_profile_score =
  0.18 officiality_score
+ 0.14 license_clarity_score
+ 0.12 robots_clarity_score
+ 0.12 stable_id_score
+ 0.10 update_policy_score
+ 0.10 data_structure_score
+ 0.08 attribution_clarity_score
+ 0.08 pii_safety_score
+ 0.08 reproducibility_score
+ 0.10 product_value_score
```

推奨閾値:

| score | gate |
|---:|---|
| `>= 0.85` | P0本番候補 |
| `0.70-0.84` | P1またはmanual review後 |
| `0.50-0.69` | metadata/link only |
| `< 0.50` | block |

ただし、license/robots/private leak/no-hit misuse の critical issue がある場合、scoreに関係なく block する。

### 4.3 Source familyごとの初期評価

| source family | 優先 | source_profile gate の焦点 |
|---|---:|---|
| 法人番号 | P0 | API/ダウンロード、法人番号を stable ID、出典表示 |
| インボイス | P0 | 個人事業者情報の扱い、登録状態の時点管理 |
| e-Gov法令 | P0 | 法令ID、施行日、改正履歴、条文XML |
| J-Grants | P0 | APIベータ性、募集要領PDFの再配布境界 |
| gBizINFO | P0 | token/利用目的、元データ由来の制約 |
| e-Stat | P0 | 統計表ID、地域コード、単位、時点 |
| 官報/告示/公告 | P1 | raw再配布境界、PDF/OCR、公告期間 |
| 自治体 | P1 | ドメイン揺れ、CMS、更新頻度、PDF主体 |
| 裁判所/審決/処分 | P1 | 匿名化、事件番号、処分と勧告の区別 |
| 業法/許認可 | P0/P1 | 所管省庁と自治体の二層、標準処理期間 |
| 標準/認証 | P1 | 規格本文の再配布制限、メタデータ中心 |
| 税/労務/社保 | P0/P1 | 期限・様式・料率の鮮度、制度変更 |

## 5. Gate 02: `license_boundary`

### 5.1 Boundary enum

| boundary | 意味 | claim support | public publish |
|---|---|---|---|
| `full_fact` | 構造化factと短い引用を出典表示付きで利用可 | direct可 | 可 |
| `derived_fact_only` | raw再配布不可。正規化値・分類・差分のみ可 | direct/derived可 | 可 |
| `metadata_only` | タイトル、URL、日付、hash等のみ可 | substantive claim不可 | 限定 |
| `link_only` | リンク紹介のみ | 不可 | 限定 |
| `internal_eval_only` | 評価用のみ | 不可 | 不可 |
| `blocked` | 利用不可 | 不可 | 不可 |
| `unknown` | 未判定 | 不可 | 不可 |

### 5.2 判定ルール

`license_boundary` は source単位ではなく、field単位で細分化できるようにする。

例:

```json
{
  "source_profile_id": "sp_example",
  "license_boundary": "derived_fact_only",
  "field_boundaries": {
    "title": "metadata_only",
    "deadline": "derived_fact_only",
    "eligibility_summary": "derived_fact_only",
    "full_pdf_text": "blocked",
    "short_quote": "review_required"
  }
}
```

### 5.3 Blocking conditions

以下は即 block または manual review。

- 利用条件が未確認なのに raw/全文再配布を予定している
- robots/terms が automated access を禁じるのに Playwright/クロールを予定している
- 第三者権利が明示されている添付ファイルを全文抽出して公開しようとしている
- 個人情報や匿名化済み事件情報をランキング・信用評価に転用している
- source側が保証していない分析を、所管機関保証のように表示している

### 5.4 Product conversion

| boundary | packetで返せるもの | 返してはいけないもの |
|---|---|---|
| `full_fact` | fact、短い引用、出典、hash、差分 | 所管機関が分析を保証する表現 |
| `derived_fact_only` | 正規化fact、スコア、分類、gap | raw本文、全文表、画像全文 |
| `metadata_only` | URL、タイトル、日付、取得状態 | substantive factの根拠 |
| `link_only` | 公式ページへのリンク | jpcite独自の断定 |
| `blocked` | なし | すべて |

## 6. Gate 03: `robots/terms`

### 6.1 `robots_receipt`

HTML/Playwright/PDFクロールでは `robots_receipt` が必須。

```json
{
  "schema_id": "jpcite.robots_receipt",
  "schema_version": "2026-05-15",
  "robots_receipt_id": "rr_example",
  "domain": "example.go.jp",
  "robots_url": "https://example.go.jp/robots.txt",
  "fetched_at": "2026-05-15T00:00:00+09:00",
  "http_status": 200,
  "content_sha256": "sha256:...",
  "matched_user_agent": "jpcitebot",
  "decision": "allow",
  "allowed_paths": ["/public/"],
  "blocked_paths": ["/search/private"],
  "crawl_delay_seconds": 3,
  "operator_contact_in_user_agent": true
}
```

### 6.2 Decision enum

| decision | 処理 |
|---|---|
| `api_only` | APIのみ。HTML/Playwright禁止 |
| `download_only` | 公式一括DLのみ |
| `allow_low_rate` | 低並列クロール可 |
| `allow_playwright_low_rate` | Playwright可。ただし低並列 |
| `metadata_only` | URL/タイトル等のみ |
| `manual_review` | 実行保留 |
| `blocked` | 実行禁止 |

### 6.3 取得方式の優先順位

1. 公式API
2. 公式一括ダウンロード
3. 公式CSV/JSON/XML/PDF
4. 公開HTML fetch
5. Playwright rendered capture
6. OCR

Playwright/OCR は「fetchが難しいから何でも突破する」ためではなく、公式公開ページの可視状態を証跡化するために使う。

禁止:

- CAPTCHA突破
- ログイン突破
- proxy rotationによる回避
- stealth pluginでの偽装
- 検索フォーム総当たり
- 429/403後の高頻度retry
- user dataやprivate CSVのスクリーンショット化

### 6.4 Terms drift

terms/robotsは変わる。以下のいずれかで source_profile は stale になる。

- terms URL の `content_hash` が変わった
- robots.txt の `content_hash` が変わった
- 取得時に 403/429 が急増した
- サイト上に大量取得禁止やAPI移行案内が出た
- source familyの運用者・ドメインが変わった

terms drift が起きた source は `manual_review_required` へ戻す。

## 7. Gate 04: `content_hash`

### 7.1 Hashの種類

1つの取得物には複数のhashを持たせる。

| hash | 対象 | 用途 |
|---|---|---|
| `raw_content_sha256` | 取得バイト列 | 再現性・改ざん検知 |
| `canonical_content_sha256` | 正規化後本文 | 差分検出 |
| `visible_text_sha256` | 表示テキスト | Playwright/OCR比較 |
| `table_canonical_sha256` | 表正規化 | 統計・補助金・許認可表 |
| `screenshot_sha256` | PNG/JPEG画像 | 可視証跡 |
| `ocr_text_sha256` | OCR出力 | OCR再現性 |
| `claim_value_hash` | claimのcanonical value | claim dedupe |

### 7.2 Canonicalization

正規化では以下を統一する。

- Unicode正規化: NFKC。ただし法令条文の記号は元表記も保持
- 空白: 連続空白・改行を比較用に正規化
- 全角/半角: 数字・英字・記号は比較用正規化
- 日付: 和暦/西暦を両方保持し、canonicalはISO日付
- 金額: 円単位に正規化し、単位元表記を保持
- 地名: 公式コードがあればコード優先
- 法令: 法令ID、条番号、項号、施行日を保持
- 企業: 法人番号を優先し、商号だけで同一視しない

### 7.3 Hash gate

| 条件 | gate |
|---|---|
| raw hashなし | block |
| canonical hashなし | manual_review_required |
| hash mismatch | quarantine |
| non-deterministic canonicalization | manual_review_required |
| screenshot hashあり、visible textなし | warning or manual review |
| OCR hashあり、confidenceなし | manual_review_required |

### 7.4 差分検出

差分は3層で扱う。

| 差分 | 意味 | product impact |
|---|---|---|
| byte diff | HTML広告・日時なども含む | すぐにはclaim変更にしない |
| canonical diff | 本文・表・主要メタの変化 | claim再評価 |
| claim diff | fact値が変わった | packet更新・stale解除 |

claim diff のみが成果物更新の主トリガーである。ただし terms/robots diff は取得停止トリガーになりうる。

## 8. Gate 05: `screenshot_receipt`

### 8.1 目的

スクリーンショットは「fetchで取りにくい公式公開ページの可視状態」を補強する証跡である。画像そのものを主要商品にするのではなく、DOM/visible text/OCR/claim_ref の根拠補助として使う。

### 8.2 必須項目

```json
{
  "schema_id": "jpcite.screenshot_receipt",
  "schema_version": "2026-05-15",
  "screenshot_receipt_id": "ssr_example",
  "source_receipt_id": "sr_...",
  "capture_method": "playwright_chromium",
  "viewport": {
    "width": 1280,
    "height": 900,
    "device_scale_factor": 1,
    "stored_image_width": 1280,
    "stored_image_height": 900
  },
  "limits": {
    "max_side_px": 1600,
    "full_page": false,
    "tile_index": null
  },
  "browser": {
    "engine": "chromium",
    "version": "recorded_at_run",
    "locale": "ja-JP",
    "timezone": "Asia/Tokyo"
  },
  "page_state": {
    "http_status": 200,
    "final_url": "https://...",
    "loaded_at": "2026-05-15T00:00:00+09:00",
    "network_idle_observed": true,
    "console_error_count": 0,
    "modal_or_cookie_banner_detected": false,
    "captcha_detected": false,
    "login_wall_detected": false
  },
  "quality": {
    "blankness_ratio": 0.03,
    "text_coverage_ratio": 0.82,
    "image_sha256": "sha256:...",
    "visible_text_sha256": "sha256:...",
    "gate_status": "pass"
  }
}
```

### 8.3 1600px以下ルール

保存画像は各辺 `<= 1600px` に制限する。長大ページは full-page 1枚ではなく tile化する。

| ページ | 推奨 |
|---|---|
| 通常HTML | viewport 1280x900 |
| スマホ専用表示 | viewport 390x844 |
| 表が横長 | 1600x900まで |
| 長いPDF/HTML | 1600px以下のtile |
| OCR用 | 1600x1600以下のtile |

### 8.4 Screenshot gate

| 条件 | gate |
|---|---|
| stored image side > 1600px | block |
| blankness_ratio > 0.85 | quarantine |
| captcha/login wall | block for capture; known_gap |
| 403/429 page screenshot | no claim support |
| cookie bannerが本文を覆う | manual_review_required |
| source_url/final_url不一致かつredirect未記録 | manual_review_required |
| screenshot hashなし | block |
| visible_textなし | warning。画像のみclaim根拠にはしない |
| PII/secretが映り込み | block/private leak |

### 8.5 Screenshotとclaimの関係

スクリーンショット単独で substantive claim を支えるのは原則避ける。

推奨 support:

| evidence | support |
|---|---|
| API/CSV/XML + screenshot | direct + visual corroboration |
| DOM visible text + screenshot | direct if terms allowed |
| screenshot + OCR only | weak or manual_review_required |
| screenshot of no-result page | no_hit_not_absence |
| screenshot of 403/login | known_gap only |

## 9. Gate 06: OCR confidence

### 9.1 OCRの位置づけ

OCRは scanned PDF、画像表、官報/自治体PDF、古い告示などを機械可読化するための補助である。OCR出力は誤りを含むため、confidenceとfield重要度に応じて claim support を変える。

### 9.2 必須項目

```json
{
  "schema_id": "jpcite.ocr_receipt",
  "schema_version": "2026-05-15",
  "ocr_receipt_id": "ocr_example",
  "source_receipt_id": "sr_...",
  "input_artifact_id": "art_screenshot_or_pdf_tile",
  "engine": "textract_or_local_ocr",
  "language_hint": "ja",
  "page_or_tile": {
    "page_number": 3,
    "tile_index": 1,
    "bbox": [0, 0, 1600, 1600]
  },
  "confidence": {
    "page_mean": 0.94,
    "page_min": 0.71,
    "token_p05": 0.82,
    "numeric_token_mean": 0.96,
    "date_token_mean": 0.95
  },
  "quality": {
    "layout_detected": true,
    "table_detected": true,
    "manual_review_required": false,
    "gate_status": "pass_with_warnings"
  }
}
```

### 9.3 Confidence threshold

| field type | direct support minimum | lower threshold action |
|---|---:|---|
| URL/title/source metadata | 0.85 | warning |
| deadline/date | 0.95 | manual review |
| amount/subsidy rate | 0.97 | manual review |
| legal article number | 0.97 | manual review |
| company identifier | 0.98 | manual review |
| free text summary | 0.90 | derived/weak only |
| table cell | 0.95 + table structure pass | manual review |

重要fieldはOCRだけで断定しない。API/HTML/XML/PDF text layer と照合できる場合は照合結果を優先する。

### 9.4 OCR blocking conditions

- confidenceなし
- ページ・tile座標なし
- OCR出力と画像hashのlinkなし
- 日付/金額/法人番号/条番号が低confidence
- 文字化け率が高い
- 表セルの行列対応が不明
- OCR結果がsource textとして公開再配布される設計

### 9.5 OCR known_gaps

OCR関連の `known_gap`:

| gap_type | 条件 |
|---|---|
| `ocr_low_confidence` | 閾値未満 |
| `ocr_table_structure_uncertain` | 行列対応不明 |
| `ocr_visual_only_source` | text layerなし |
| `ocr_manual_review_required` | 重要field要確認 |
| `ocr_partial_page` | tile欠落 |

## 10. Gate 07: `claim_ref` quality

### 10.1 Claim granularity

`claim_ref` は以下の単位で作る。

良い単位:

- 補助金Aの公募締切は `2026-06-30`
- 法人番号Xの商号は `株式会社...`
- インボイス登録番号T...は取得時点で `registered`
- 法令Yの第Z条の見出しは `...`
- 自治体制度Pの対象地域は `東京都...`
- 行政処分Dの処分日は `2026-...`
- CSV derived fact の月次売上合計は bucketed/aggregate で `...`

悪い単位:

- この会社は安全
- この補助金は必ず使える
- 申請すべき
- 違法ではない
- 問題なし
- 信用できる/できない
- 調査済みなので大丈夫

### 10.2 Claim support levels

| support_level | 意味 | 使い方 |
|---|---|---|
| `direct` | 出典内に明示されたfact | substantive claim可 |
| `derived` | 出典factから deterministic に計算 | 計算式必須 |
| `weak` | OCR/視認/不完全抽出 | warning/manual review |
| `metadata_only` | URL/タイトル等のみ | substantive claim不可 |
| `no_hit_not_absence` | 見つからなかった検査結果 | absence/safety不可 |
| `unsupported` | 根拠なし | 公開不可 |

### 10.3 Claim quality checks

| check | block条件 |
|---|---|
| deterministic ID | IDが再生成不能 |
| source_receipt link | receiptなし |
| source_profile link | receiptからprofileへ辿れない |
| value canonicalization | 値hashなし |
| time scope | as_of/valid_from不明 |
| visibility | public/private混線 |
| support allowed | licenseがclaim supportを許さない |
| no-hit misuse | no-hitで安全/不存在を断定 |
| conflict hidden | conflicting claimがあるのに隠す |
| private leak | CSV raw row/摘要/個人名がclaim化 |

### 10.4 Derived claim rule

`derived` claim は `algorithm_trace` を必須にする。

```json
{
  "algorithm_trace": {
    "algorithm_id": "grant_match_score_v1",
    "input_claim_ids": ["claim_...", "claim_..."],
    "formula_version": "2026-05-15",
    "parameters_hash": "sha256:...",
    "output_interpretation": "screening_support_only",
    "not_allowed_interpretations": ["eligibility_guarantee", "approval_prediction"]
  }
}
```

derived claim は「推薦」「可能性」「注意点」の表示に使えるが、出典が直接述べていない法律・制度上の断定にしてはいけない。

## 11. Gate 08: `known_gap`

### 11.1 Gapは価値を下げるものではなく、信頼性の一部

jpcite は「完全な真実」を売るのではなく、「一次情報に基づく、限界が明示された成果物」を売る。`known_gap` を正しく出すことでAIエージェントがエンドユーザーに説明しやすくなる。

### 11.2 Gap enum

| gap_type | severity default | 例 |
|---|---|---|
| `source_stale` | warning | TTL超過または更新日古い |
| `source_update_unknown` | warning | 更新頻度不明 |
| `license_metadata_only` | major | substantive claim不可 |
| `terms_manual_review_required` | major | 規約未確認 |
| `robots_manual_review_required` | major | robots不明 |
| `no_hit_not_absence` | info/warning | 検索結果なし |
| `coverage_partial` | warning | 自治体/業界の一部のみ |
| `ocr_low_confidence` | major | OCR confidence不足 |
| `screenshot_visual_uncertain` | major | 可視状態不明 |
| `source_conflict` | major | source間で値が違う |
| `identity_match_uncertain` | major | 法人同定が弱い |
| `date_parse_uncertain` | warning/major | 日付解釈が曖昧 |
| `unit_uncertain` | major | 金額/率/面積の単位不明 |
| `law_effective_date_uncertain` | major | 施行日/未施行が曖昧 |
| `private_overlay_suppressed` | info | CSV安全抑制で詳細非表示 |
| `human_review_required` | major | 人手確認前提 |
| `source_blocked` | critical | 利用不可 |

### 11.3 Gap display

`known_gap` は内部だけでなく、packetやproof pageに短く表示できるコピーを持つ。

```json
{
  "message_key": "no_hit_not_absence",
  "public_message_ja": "この結果は、指定したデータ源・条件・取得時点で一致を確認できなかったことを示すもので、対象が存在しないことや安全であることの証明ではありません。",
  "agent_message_ja": "AIエージェントはこのno-hitを不存在・安全・問題なしへ変換してはいけません。"
}
```

### 11.4 Blocking gap

以下の gap は、解消まで本番公開不可。

- `source_blocked`
- `private_data_leak`
- `terms_manual_review_required` with substantive claim
- `robots_manual_review_required` with crawl-derived claim
- `ocr_low_confidence` on critical field
- `source_conflict` hidden from packet
- `no_hit_misuse`
- `license_unknown`

## 12. Gate 09: no-hit

### 12.1 no-hitの定義

no-hit は「指定した source、snapshot、query、正規化条件で一致が見つからなかった検査結果」である。存在しない、安全、対象外、違法でない、登録不要、申請不可を意味しない。

### 12.2 `no_hit_receipt`

```json
{
  "schema_id": "jpcite.no_hit_receipt",
  "schema_version": "2026-05-15",
  "source_receipt_id": "sr_nohit_example",
  "receipt_kind": "no_hit_check",
  "support_level": "no_hit_not_absence",
  "source_profile_id": "sp_invoice_publication",
  "snapshot_id": "snapshot_2026_05_15",
  "query": {
    "query_kind": "invoice_number_lookup",
    "normalized_query_hash": "sha256:...",
    "raw_query_stored": false,
    "normalization_steps": ["nfkc", "trim", "invoice_number_format"]
  },
  "searched_scope": {
    "dataset": "invoice_public_registry_snapshot",
    "snapshot_at": "2026-05-15T00:00:00+09:00",
    "filters": ["exact_invoice_number"]
  },
  "result": {
    "match_count": 0,
    "meaning": "no_hit_not_absence"
  },
  "forbidden_interpretations": [
    "does_not_exist",
    "safe",
    "not_registered_definitively",
    "no_tax_issue",
    "do_not_transact"
  ]
}
```

### 12.3 no-hit gate

| condition | gate |
|---|---|
| searched_scope不明 | block |
| query normalization不明 | manual_review_required |
| snapshot時点不明 | block |
| no-hitをabsence/safetyへ変換 | critical block |
| no-hitがpositive claimを上書き | block |
| no-hitの結果ページが403/429 | known_gap only |
| fuzzy queryのno-hit | warning/manual review |

### 12.4 Safe copy

許可:

- 「取得時点の指定スナップショットでは一致を確認できませんでした」
- 「この結果は調査範囲内のno-hitであり、不存在を証明しません」
- 「追加確認が必要です」

禁止:

- 「存在しません」
- 「登録されていません」と断定
- 「問題ありません」
- 「安全です」
- 「法的義務はありません」
- 「取引して大丈夫です」

## 13. Gate 10: staleness

### 13.1 Stalenessはsource familyで変える

すべての情報に同じTTLを置くと商品が壊れる。更新頻度とユーザーリスクに応じて TTL を分ける。

| source family | default TTL | stale impact |
|---|---:|---|
| インボイス登録 | 1-3日 | 取引判断に影響 |
| 法人番号基本情報 | 1-7日 | 商号/所在地変更 |
| 補助金/助成金 | 1日 | 締切・公募終了 |
| 調達公告 | 1日 | 応札期限 |
| 法令改正/施行 | 1-7日 | 法的判断に影響 |
| 官報/告示/公告 | 1-7日 | 新規公告 |
| 行政処分 | 1-7日 | DD/審査に影響 |
| 許認可/登録 | 7-30日 | 業界により変動 |
| e-Stat統計 | 30-365日 | 統計表に依存 |
| 地理/区域 | 30-180日 | 都市計画・災害系は短め |
| 標準/認証 | 30-180日 | 改正頻度に依存 |
| 税/社保/最低賃金 | 7-30日 | 施行日・年度で変動 |
| 自治体制度ページ | 1-14日 | 締切・年度更新 |

### 13.2 Staleness status

| status | 意味 | 本番利用 |
|---|---|---|
| `fresh` | TTL内 | 可 |
| `near_stale` | TTLの80%超 | 可、warning |
| `stale_within_display` | TTL超過だが表示すれば低リスク | 一部可 |
| `stale_blocking` | TTL超過で高リスク | 不可 |
| `unknown_freshness` | 更新時点不明 | manual review |

### 13.3 判定式

```text
age_hours = now - max(retrieved_at, source_document_date if reliable)
ttl_hours = source_profile.update_policy.staleness_ttl_days * 24

if age_hours <= ttl_hours * 0.8:
  fresh
elif age_hours <= ttl_hours:
  near_stale
elif source_family_low_risk:
  stale_within_display
else:
  stale_blocking
```

### 13.4 Product display

stale系のgapがある場合、packetには必ず以下を入れる。

- `retrieved_at`
- `source_document_date`
- `staleness_status`
- `refresh_recommended`
- `known_gaps[]`

AIエージェント向けには「このpacketは最新確認ではなく、追加更新確認が必要」と明示する。

## 14. Gate 11: conflict

### 14.1 Conflictの考え方

公的一次情報でも矛盾は発生する。

- 法令本文と所管省庁Q&Aの更新タイミング差
- J-Grants APIと募集要領PDFの締切差
- 自治体ページとPDF添付の年度差
- 法人番号とgBizINFOの所在地差
- 行政処分一覧と個別PDFの表記差
- OCR誤読による日付/金額差

矛盾は多数決で消さず、conflict groupとして残す。

### 14.2 `conflict_group`

```json
{
  "schema_id": "jpcite.conflict_group",
  "schema_version": "2026-05-15",
  "conflict_group_id": "cg_example",
  "subject_kind": "program",
  "subject_id": "program:jgrants:abc",
  "field_name": "deadline",
  "conflict_type": "different_values_same_field",
  "claims": [
    {
      "claim_id": "claim_a",
      "value": "2026-06-30",
      "source_receipt_id": "sr_api",
      "source_authority_rank": 1
    },
    {
      "claim_id": "claim_b",
      "value": "2026-07-05",
      "source_receipt_id": "sr_pdf",
      "source_authority_rank": 1
    }
  ],
  "resolution": {
    "status": "unresolved",
    "selected_claim_id": null,
    "reason": "official_sources_conflict",
    "requires_human_review": true
  },
  "known_gap_id": "kg_source_conflict"
}
```

### 14.3 Conflict types

| conflict_type | 例 | default action |
|---|---|---|
| `different_values_same_field` | 締切が違う | known_gap + manual review |
| `date_effective_conflict` | 施行日/公布日混同 | block high-risk claim |
| `identity_conflict` | 同名企業の法人番号違い | block identity merge |
| `unit_conflict` | 千円/円/万円 | block amount claim |
| `status_conflict` | 登録中/取消 | manual review |
| `source_version_conflict` | PDF年度違い | latest source selection with gap |
| `ocr_conflict` | OCR値とtext layer値違い | prefer text layer, gap |
| `license_conflict` | field利用条件不一致 | stricter boundary |

### 14.4 Authority ranking

source authority rank は source family ごとに定義する。

例: 補助金

1. 公式API/公式募集要領
2. 所管省庁・自治体の公式ページ
3. 公式PDF添付
4. 関連団体ページ
5. 第三者紹介ページ

ただし、rankが高いからといって矛盾を非表示にしない。高rank sourceを暫定表示する場合も `known_gap=source_conflict` を残す。

## 15. Gate 12: privacy and CSV boundary

### 15.1 Public corpusとprivate overlayの分離

AWSで扱う広域 public corpus と、ユーザーの会計CSV private overlay は混ぜない。

| データ | AWS public corpus | private overlay |
|---|---:|---:|
| 法人番号 | 可 | 参照可 |
| インボイス公表 | 可 | 参照可 |
| e-Gov法令 | 可 | 参照可 |
| 補助金制度 | 可 | 参照可 |
| ユーザーCSV raw row | 不可 | 一時処理のみ |
| 摘要 | 不可 | 保存禁止 |
| 取引先名 | 不可 | 原則保存禁止。safe hash/aggregateのみ |
| 給与/銀行明細 | 不可 | 保存禁止 |
| aggregate derived fact | 条件付き不可/公開不可 | tenant scopedのみ |

### 15.2 CSV-derived claim

CSV-derived claim は `namespace=private` であり、public proof pageに出さない。

```json
{
  "namespace": "private",
  "tenant_scope": "packet_runtime_only",
  "raw_csv_stored": false,
  "claim_kind": "csv_derived_aggregate",
  "visibility": "private_packet_only",
  "suppression": {
    "small_group_suppression_applied": true,
    "min_group_size": 5,
    "raw_row_reconstruction_risk": "low"
  }
}
```

### 15.3 Blocking privacy issues

- raw CSVのS3保存
- raw CSVのCloudWatch Logs出力
- 摘要・個人名・銀行口座・給与明細のclaim化
- public claim namespaceへのprivate fact混入
- screenshotにprivate画面が映る
- proof pageにprivate aggregateが出る

## 16. 本番投入可否の4段階 gate

### 16.1 Dataset gate

dataset単位で確認する。

| check | pass条件 |
|---|---|
| manifest登録 | `dataset_manifest.jsonl` にある |
| source_profile | 全sourceがpassまたは限定可 |
| license | substantive claimに必要なboundaryあり |
| robots/terms | 取得方式と整合 |
| hashes | artifact全件sha256あり |
| privacy | private leak 0 |
| no-hit | misuse 0 |
| conflict | conflict group作成済み |
| staleness | high-risk stale 0 |

### 16.2 Receipt gate

receipt単位で確認する。

| check | pass条件 |
|---|---|
| receipt_kind | positive/no_hit/metadata等が明確 |
| capture_method | API/DL/HTML/Playwright/OCR等 |
| source_profile link | N:1で辿れる |
| timestamp | `retrieved_at`あり |
| hash | raw/canonical/visible等あり |
| location | selector/page/row/key等あり |
| support_capability | allowed fieldsあり |
| known_gaps | gapがある場合link済み |

### 16.3 Claim gate

claim単位で確認する。

| check | pass条件 |
|---|---|
| minimal fact | 複合判断でない |
| deterministic ID | 再生成可能 |
| support link | receiptあり |
| support allowed | license/field boundaryと整合 |
| time scope | as_of/valid期間あり |
| visibility | public/private正しい |
| no-hit | absenceへ変換なし |
| conflict | conflict groupに参加済み |

### 16.4 Product gate

packet/proof/API/MCPに出す前の確認。

| check | pass条件 |
|---|---|
| claim_refs | 全claimに根拠あり |
| source_receipts | 表示可能な出典情報あり |
| known_gaps | packetに出る |
| attribution | 出典・加工主体・非保証表示あり |
| billing | cost preview/課金metadataあり |
| no request-time LLM | false |
| no private leak | 0 |
| stale/conflict | 表示・ブロック方針済み |
| agent copy | no-hit誤変換なし |

## 17. Source family別の本番投入基準

### 17.1 法人番号

本番投入可:

- 法人番号がstable ID
- 基本3情報の取得時点あり
- 商号/所在地/閉鎖等の履歴区分あり
- 出典表示あり

不可:

- 商号だけで法人同定
- no-hitから「存在しない会社」
- 住所変更を現住所として断定

### 17.2 インボイス

本番投入可:

- 登録番号 exact match
- 取得時点、登録/取消/失効等のstatus
- 個人事業者への配慮

不可:

- no-hitから「免税事業者」
- 取引可否の断定
- 税務上問題あり/なしの断定

### 17.3 法令・制度・業法

本番投入可:

- 法令ID、条番号、施行日、改正履歴
- 未施行/廃止/経過措置のgap
- Q&Aやガイドラインを法令本文と区別

不可:

- 「違法ではない」
- 「許可不要」
- 「法的義務なし」
- 施行日不明の断定

### 17.4 補助金・助成金

本番投入可:

- 公募名、実施主体、締切、対象者、対象経費
- J-Grants/API/募集要領のconflict表示
- eligibilityは `candidate/needs_review` に留める

不可:

- 「採択される」
- 「必ず使える」
- no-hitから「使える補助金はない」

### 17.5 調達・入札

本番投入可:

- 公告ID、調達機関、期限、資格条件、URL
- award/落札情報は時点付き

不可:

- 入札勝率予測
- 競合評価の断定
- stale公告を最新案件として表示

### 17.6 行政処分・裁判・紛争

本番投入可:

- 処分主体、処分日、根拠ページ、対象法人番号がある場合
- 勧告/命令/行政指導/処分の区別
- 匿名裁判例は個人同定しない

不可:

- 「危険企業」
- 「信用できない」
- no-hitから「処分歴なし」と断定

### 17.7 自治体

本番投入可:

- 自治体公式ドメイン
- 制度ページ/要領PDF/申請ページの時点
- 地域コード・自治体コード

不可:

- 全国制度として表示
- 年度違いPDFの混在
- CMS検索結果のno-hitを制度不存在に変換

### 17.8 統計・地理・区域

本番投入可:

- 統計表ID、調査年、単位、地域コード
- 地理データの座標系・版
- 推計/実測/集計の区別

不可:

- 異なる単位の単純比較
- 古い区域を現在区域として断定
- 統計相関を因果として表示

### 17.9 標準・認証・製品安全

本番投入可:

- メタデータ、制度ページ、適用範囲、公式リンク
- 規格本文はlink/metadata中心

不可:

- 規格本文の全文再配布
- 「適合している」の断定
- リコールno-hitから「安全」

### 17.10 税・労務・社会保険

本番投入可:

- 期限、料率、様式、届出イベント候補
- CSV-derived factsはprivate only
- 追加確認と専門家確認を明示

不可:

- 税務判断の断定
- 労務違反なしの断定
- 給与/個人情報の公開

## 18. Quality scoring

### 18.1 Dataset quality score

```text
dataset_quality_score =
  0.16 source_profile_pass_rate
+ 0.12 license_support_rate
+ 0.10 robots_terms_pass_rate
+ 0.10 hash_completeness_rate
+ 0.10 receipt_completeness_rate
+ 0.10 claim_support_rate
+ 0.08 staleness_fresh_rate
+ 0.08 conflict_handled_rate
+ 0.08 known_gap_completeness_rate
+ 0.08 privacy_safety_rate
+ 0.10 product_value_weighted_coverage
```

### 18.2 Publish thresholds

| score | publish |
|---:|---|
| `>= 0.90` | P0 publish allowed |
| `0.80-0.89` | publish with known gaps |
| `0.70-0.79` | internal fixture/proof candidate |
| `< 0.70` | no publish |

Critical blockers override score.

### 18.3 Critical blockers

以下が1件でもあれば `do_not_publish`。

- private leak
- no-hit misuse
- blocked source used
- terms/robots violation
- raw redistribution beyond license
- high-risk stale claim
- unresolved conflict hidden
- unsupported legal/tax/medical/financial claim
- request-time LLM claim generation

## 19. AWS runへの接続

この文書はAWSコマンドを実行しない。ただし、後続AWS runでは次の順番で gate を組み込む。

1. `J01` source profile sweep
2. `J01-QA` source_profile quality gate
3. `J25` Playwright canary only after profile pass
4. direct fetch/API/download jobs
5. OCR jobs only for approved visual/PDF sources
6. `J12` receipt completeness audit
7. `J13` claim graph/conflict audit
8. `J16` no-hit/forbidden-claim/GEO eval
9. `J15` packet/proof fixture generation
10. product import dry-run
11. staging deploy gate
12. production deploy gate
13. export/checksum/zero-bill cleanup

### 19.1 Fast credit useとの整合

ユーザー要件では、クレジット消化速度を上げ、本番デプロイを早めたい。ただし品質ゲートを後回しにすると、生成成果物が本番に入らず無駄になる。

したがって速く使う順序は以下にする。

1. Source profile gate を小さく速く回す
2. pass sourceだけに大量 compute を投下する
3. 失敗sourceは早期に `metadata_only/link_only/block` へ落とす
4. Playwright/OCRは canary pass 後に並列化する
5. 毎日 `quality_gate_report` を出し、本番投入可能な artifact から順にrepoへimportする

## 20. Production deployment gates

### 20.1 Staging gate

stagingへ進める条件:

- source_profile P0-A が pass
- public packet example が最低3系統で pass
- no-hit misuse 0
- private leak 0
- OpenAPI/MCP sample が `claim_refs/source_receipts/known_gaps` を返す
- proof page が出典・加工表示・非保証を出す
- stale/conflictがUI/APIに表示される

### 20.2 Production gate

productionへ進める条件:

- staging smoke pass
- GEO/agent discovery smoke pass
- billing/cost preview pass
- release blocker 0
- `quality_gate_report.production_decision != do_not_publish`
- AWS artifactに依存せず、repo/imported static assetsだけで本番が動く
- AWS zero-bill cleanup前でも後でもproductionが動く

### 20.3 Rollback gate

本番後に以下を検出したら、該当 packet/source family を非公開化する。

- no-hit誤表現
- source terms変更
- stale_blocking
- conflict hidden
- private leak疑い
- wrong source attribution
- unsupported legal/tax/financial conclusion

## 21. Agent-facing copy gate

AIエージェントがエンドユーザーへ推薦するため、copyも品質対象にする。

### 21.1 必ず含める表現

- 「取得時点」
- 「指定データ源」
- 「出典付き」
- 「known gaps」
- 「専門判断や最終確認の代替ではない」
- 「no-hitは不存在の証明ではない」

### 21.2 禁止表現

- 「完全」
- 「保証」
- 「問題なし」
- 「違法ではない」
- 「安全」
- 「必ず採択」
- 「許可不要」
- 「信用できる/できない」
- 「最新を保証」

### 21.3 MCP/API response requirement

MCP/APIは人間向け説明文だけでなく、機械的に安全に扱えるfieldを返す。

```json
{
  "safety_contract": {
    "no_hit_semantics": "no_hit_not_absence",
    "request_time_llm_call_performed": false,
    "unsupported_conclusions_forbidden": true,
    "known_gaps_must_be_displayed": true
  }
}
```

## 22. Gate test cases

### 22.1 no-hit misuse test

入力:

- インボイス登録番号 lookup no-hit

期待:

- `support_level=no_hit_not_absence`
- 「登録されていません」と断定しない
- `known_gap`あり

block:

- 「免税事業者です」
- 「取引不可」

### 22.2 stale subsidy test

入力:

- 取得から3日経過した補助金締切claim
- TTL 1日

期待:

- `stale_blocking`
- packet publish不可
- refresh required

### 22.3 OCR amount test

入力:

- OCR confidence 0.91 の補助上限額

期待:

- substantive amount claim は manual review
- proof pageには low confidence gap

### 22.4 conflict deadline test

入力:

- J-Grants API 締切 6/30
- PDF 募集要領 締切 7/5

期待:

- conflict group
- packetに矛盾表示
- single deadline断定不可

### 22.5 screenshot blank test

入力:

- Playwright screenshot blankness_ratio 0.92

期待:

- quarantine
- claim support不可
- capture retry or known_gap

### 22.6 metadata-only license test

入力:

- 規格本文がmetadata_only

期待:

- URL/title/規格番号のみ
- 本文要約claim不可

### 22.7 private CSV leak test

入力:

- 摘要文字列がclaim_ref display_valueに混入

期待:

- critical block
- artifact quarantine
- product publish不可

## 23. Implementation backlog mapping

本体P0へマージする順番。

1. `source_profile` schemaに quality fields を追加
2. `source_receipt` schemaに hash/capture/support fields を追加
3. `known_gap` enumを固定
4. `no_hit_receipt` schemaを positive receipt と分離
5. `quality_gate_report` generatorを追加
6. Playwright screenshot receipt validatorを追加
7. OCR confidence validatorを追加
8. conflict group builderを追加
9. staleness evaluatorを追加
10. packet composerで known_gaps/conflicts/staleness を必須表示
11. MCP/API responseに safety contract を追加
12. release gateに private leak/no-hit/stale/conflict tests を追加

## 24. Open questions

### 24.1 人手確認のUI

`manual_review_required` をどう消すかは別途UI/CLIが必要。

最低限必要:

- source profile review
- OCR critical field review
- source conflict review
- license boundary review
- stale override review

### 24.2 Legal review

この計画は技術品質ゲートであり、法的助言ではない。利用規約・著作権・個人情報・行政情報の扱いは、必要に応じて専門家確認を入れる。

### 24.3 Full corpusよりP0-A優先

全領域を同時に本番投入しない。まず売上に近いP0-Aを通す。

P0-A:

- 法人番号
- インボイス
- e-Gov法令
- 補助金/助成金
- 調達
- 建設/不動産/運輸/人材/産廃/金融の業法・許認可
- 税/労務/社保の期限・制度

## 25. Final checklist

本番投入前の最終チェック。

- [ ] source_profileが全sourceにある
- [ ] license_boundaryがfield単位である
- [ ] robots/terms receiptがHTML/Playwright対象にある
- [ ] content_hashが全artifactにある
- [ ] screenshotは1600px以下
- [ ] screenshot blank/captcha/login検出済み
- [ ] OCR confidenceがfield単位である
- [ ] claim_refが最小fact単位
- [ ] claim_refからsource_receipt/source_profileへ辿れる
- [ ] known_gapsがpacket/API/MCPに出る
- [ ] no-hit misuseが0
- [ ] staleness TTLがsource family別
- [ ] conflict groupが隠されていない
- [ ] private CSV raw dataがAWS/ログ/公開面にない
- [ ] request-time LLMがない
- [ ] attributionと非保証表示がある
- [ ] quality_gate_reportがexport packageにある
- [ ] production_decisionが `publish_allowed` または限定可である

## 26. まとめ

この品質ゲートの中心は、「大量取得したデータ」ではなく「本番でAIエージェントが安全に再利用できる claim と receipt の関係」を作ることである。

AWSクレジットは広い日本公的一次情報を集める好機だが、品質ゲートなしに広げると、本番に入らないデータが増える。したがって、AWS実行時は source_profile gate を先に通し、passしたsourceだけに取得・Playwright・OCR・claim生成の計算資源を投下する。

本番投入の基準は以下に固定する。

- 出典契約が明確
- 取得証跡が再現可能
- claimが最小fact単位
- gapを隠さない
- no-hitを誤用しない
- stale/conflictを表示する
- private dataを混ぜない
- AIエージェントが誤解しないAPI/MCP応答にする

これを満たしたものから順に、packet examples、proof pages、MCP/API、GEO discovery surfaceへ投入する。
