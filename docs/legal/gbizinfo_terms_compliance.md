# gBizINFO API 6-condition compliance

This document is the operational compliance contract that wires the
Bookyou-issued gBizINFO REST API v2 token into the jpcite production
code-path. It is the single source of truth for the 6 operator-side
conditions extracted verbatim from the gBizINFO 利用規約
(`4795140981406`, 最終更新 2025-12-22) and the API・データダウンロード
利用規約 (`4999421139102`, 最終更新 2026-04-08).

Verbatim ToS source-of-truth lives at:

- `tools/offline/_inbox/public_source_foundation/gbizinfo_tos_verbatim_2026-05-06.md`
- `tools/offline/_inbox/value_growth_dual/A_source_foundation/parts/W1_A04_gbizinfo_rationale.md`

DEEP-01 spec reference: `tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_01_gbizinfo_ingest_activation.md`.

---

## 1. Operator + scope

| 項目 | 値 |
|---|---|
| 法人名 | Bookyou株式会社 |
| 適格事業者番号 | T8010001213708 (登録: 令和7年5月12日) |
| 代表者 | 梅田茂利 |
| 所在地 | 東京都文京区小日向2-22-1 |
| 連絡先 | info@bookyou.net |
| 申請日 | 2026-05-06 |
| 利用目的 | 自社運営の jpcite-api / jpcite-mcp バックエンドデータソース。AI agent / 士業 / BPO 顧客に対し ¥3/req metered API として再配布。エンドユーザーは gBizINFO へ直接アクセスせず、Bookyou 名義 token で集約する。 |
| Token 保管 | `/Users/shigetoumeda/jpcite/.env.local` (chmod 600, git-ignored) + Fly secret `GBIZINFO_API_TOKEN` (`fly secrets set GBIZINFO_API_TOKEN=... -a autonomath-api`) |
| 環境変数名 | `GBIZINFO_API_TOKEN` (この 1 つのみ。alias 禁止) |

**価格**: ¥3/req (税込 ¥3.30)、anonymous tier は IP 単位 3 req/日 (JST 翌日 00:00 リセット)。tier SKU や seat 課金は無し。本ドキュメント内で価格変更は提案しない (`feedback_no_priority_question` + `project_autonomath_business_model` 準拠)。

**運用方針**: Solo + zero-touch。手動 onboarding call、DPA 個別交渉、Slack Connect、phone support は提供しない (`feedback_zero_touch_solo` 準拠)。

---

## 2. 6 条件チェックリスト

各条件は以下のフォーマットで構造化する:

- **条件** (verbatim from ToS — invented clauses は無し)
- **実装場所** (file:line reference)
- **検証方法** (CI gate / pytest pointer)
- **違反時 incident response**

### 条件 1: Bookyou名義申請 (1-法人 1-token 原則の前段)

- **条件 (verbatim 4999421139102 §1)**:

  > 本サービスは、Gビズインフォが提供する法人情報検索・取得機能を対象としたサービスです。利用には事前の申請およびアクセストークンの取得が必要です。申請時には、法人番号、法人名、担当部署、所在地、連絡先、利用目的等の情報提供が求められます。
  >
  > 本サービスの利用は、申請時に申告した目的の範囲内に限られます。

- **実装場所**:
  - 申請フォーム: `https://info.gbiz.go.jp/hojin/various_registration/form` で houjin_bangou=8010001213708 を提出済 (2026-05-06)
  - `.env.local` に Bookyou 名義で発行された token 1 本のみを格納
  - `src/jpintel_mcp/ingest/_gbiz_rate_limiter.py` 冒頭の `_TOKEN = os.environ.get("GBIZINFO_API_TOKEN")` で 1 token をロード
  - 2 つ目以降の token を環境変数として読む実装は禁止 (条件 2 と連動)
  - token を顧客に開示する API は無し (jpcite-api は Bookyou token を内部で保持し、結果のみ顧客に返す)

- **検証方法**:
  - `tests/test_gbizinfo_attribution.py::test_attribution_carries_operator`
    - 全 gbiz_* 由来 response の `_attribution.modification_notice` に `Bookyou 株式会社 (jpcite-api) が編集・加工` の文言が含まれることを assert
  - `tests/test_gbizinfo_attribution.py::test_attribution_houjin_bangou`
    - 申請者 houjin_bangou (T8010001213708) が `_attribution.operator` または同等のフィールドに含まれることを assert
  - CI grep guard: `grep -r "GBIZINFO_API_TOKEN" src/ scripts/cron/ tests/` で 1 環境変数名のみが参照されていることを確認

- **違反時 incident response**:
  1. 即時 token revoke (gBizINFO 運営に申告 + Fly secret 削除)
  2. `_gbiz_rate_limiter.py:_TOKEN` の missing-token guard が `RuntimeError` を raise → cron は fail-fast で停止
  3. `gh workflow disable gbiz-ingest-monthly.yml` で workflow 全停止
  4. operator (梅田) が運営に書面で経緯と再発防止策を提出 (本書 §6 テンプレ)

### 条件 2: 1-token 原則

- **条件 (verbatim 4999421139102 §3 禁止事項)**:

  > 利用者は、以下の行為を行ってはなりません。
  >
  > 利用制限を回避または無効化する目的で、複数のアクセストークンを取得・利用する行為、不正な手段により過剰なアクセスを行う行為

- **実装場所**:
  - `GBIZINFO_API_TOKEN` 環境変数は 1 本のみ。子 API key fan-out (migration 086 `api_keys` parent/child) は jpcite-api の顧客側 fan-out であり、上流 gBizINFO への発呼には適用しない
  - `src/jpintel_mcp/ingest/_gbiz_rate_limiter.py:_TOKEN` で module-level singleton にロード、複数 client から同じ token で発呼
  - 顧客に gBizINFO token を取らせて jpcite に持ち込ませる構成は禁止 (顧客は jpcite-api のみを叩き、Bookyou token で集約発呼される)
  - api_keys.parent_id / child_id (migration 086) は jpcite-api 側の sub-key 発行のみで、gBizINFO へは常に Bookyou 名義 1 token

- **検証方法**:
  - `tests/test_gbizinfo_one_token.py::test_no_alternate_token_env`
    - `os.environ` から `GBIZ_TOKEN_*`, `GBIZINFO_TOKEN_*`, `BIZ_API_TOKEN_*` 等の alias env が読まれていないことを assert
  - CI grep guard:
    ```
    grep -rn "X-hojinInfo-api-token" src/ scripts/cron/ \
      | grep -v "_gbiz_rate_limiter.py" \
      && exit 1 || exit 0
    ```
    上流ヘッダーの組立を rate_limiter モジュールに集約していることを確認
  - `tests/test_gbizinfo_one_token.py::test_single_token_module_singleton`
    - import を 5 回繰り返しても `_TOKEN` instance が同一であることを assert

- **違反時 incident response**:
  1. 検知方法: gBizINFO 運営からの通知 / 自社 audit_log_section52 (mig 101) の `gbiz_token_loaded` event で複数 token id が観測された場合
  2. 即時 sub-issuance を停止 (該当 module を rollback)
  3. operator から gBizINFO 運営に経緯 + 是正策を書面提出 (本書 §6)
  4. 30 日間 self-imposed cron 停止 (信頼回復期間)

### 条件 3: 1 rps + 24h cache TTL

- **条件 (verbatim 4999421139102 §2 利用制限)**:

  > 本サービスの安定的な提供および公平な利用を確保するため、APIおよびデータダウンロードに関して、利用者ごとにアクセス頻度、リクエスト数、通信量等について一定の上限（以下「利用制限」）を設けることがあります。
  >
  > 利用制限の内容および条件は、サービスの特性、システム負荷、利用状況等を踏まえて設定または変更される場合があります。
  >
  > 短時間における過度なアクセス、通常の利用範囲を著しく超えるアクセス、または本サービスの運営に支障を与えるおそれのある利用が確認された場合には、事前の通知なく、アクセス制限、通信遮断、アクセストークンの一時停止または取消し等の措置を講じることがあります。

  注: 具体的な数値 (req/sec、req/day、QPS 等) は規約上 **非開示**。Swagger UI / 利用申請マニュアル側にも明示数値の記載なし (運営裁量で都度設定・変更)。

- **実装場所**:
  - `src/jpintel_mcp/ingest/_gbiz_rate_limiter.py`
    - `@sleep_and_retry @limits(calls=1, period=1)` で 1 call/秒の hard floor
    - `time.sleep` fallback も実装 (ratelimit パッケージ未導入環境用)
    - 環境変数 `GBIZ_RATE_LIMIT_RPS` (default `1`) で operator 経由の調整可、デプロイには別途承認必要
  - `diskcache.Cache` で 24h TTL
    - `_CACHE_TTL_SECONDS = 86400`
    - `cache_dir = /data/.cache/jpintel/gbiz/` (Fly volume 永続)
    - cache key = `path + "?" + sorted(params)`
  - 同一 houjin_bangou への重複呼出は cache hit でショートサーキット (debounce)
  - 顧客 ¥3/req は jpcite 内部 cache hit でも課金 (gBizINFO 側 0 req)

- **検証方法**:
  - `tests/test_gbizinfo_rate_limit.py::test_rate_limit_enforced`
    - 連続 2 回の `gbiz_get()` 呼出の elapsed time が ≥ 1.0s であることを assert
    - mock 環境で 10 連続呼出が ≥ 9.0s かかることを assert
  - `tests/test_gbizinfo_rate_limit.py::test_cache_ttl_24h`
    - cache に書き込んだ entry の expire_time が `now + 86400 ± 60s` 以内であることを assert
  - `tests/test_gbizinfo_rate_limit.py::test_cache_hit_skip_upstream`
    - 同一 path + params で 2 回呼出した場合、httpx mock が 1 回のみ called であることを assert

- **違反時 incident response**:
  1. 429 spike 検知: `_gbiz_rate_limiter.py` が 429 を `RuntimeError("gbiz_rate_limit_exceeded")` で raise → cron fail-fast
  2. 自動 exponential backoff は **付けない**: 429 後に再発呼すると abuse 認定リスク。fail-fast で operator 経由 manual review
  3. 持続的 429: operator が gBizINFO 運営に問い合わせ、token 状態確認 + 利用上限の公式数値開示交渉
  4. 4 時間以上の継続 429: cron 全停止 + Slack alert (`gbiz_token_at_risk`)
  5. token 取消し通知: 本書 §5 撤退条件に従って NTA bulk + p-portal + jGrants の fallback ingest path に切替

### 条件 4: 出典固定文 (verbatim)

- **条件 (verbatim 4795140981406 「出典の記載について」)**:

  > コンテンツを利用する際は出典を記載してください。出典の記載方法は以下のとおりです。
  >
  > （出典記載例）
  > 出典： Gビズインフォ ウェブサイト（当該ページのURL）
  > 出典： 「 Gビズインフォ 」（経済産業省）（当該ページのURL）（○年○月○日に利用）など
  >
  > コンテンツを編集・加工等して利用する場合は、上記出典とは別に、編集・加工等を行ったことを記載してください。なお、編集・加工した情報を、あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません。

- **実装場所**:
  - `src/jpintel_mcp/ingest/_gbiz_attribution.py`
    - `build_attribution(source_url, fetched_at, upstream_source=None) -> dict`: 機械可読 envelope を返す
    - `attribution_disclaimer_short() -> str`: 短形固定文を返す
    - `inject_attribution_into_response(envelope: dict) -> dict`: 既存 response に idempotent merge
  - `src/jpintel_mcp/api/middleware/gbiz_attribution.py`: BaseHTTPMiddleware として全 gbiz 由来 response に automatic injection
  - 短形固定文 (response header / footer / per-row meta) — verbatim:
    ```
    出典：「Gビズインフォ」（経済産業省）（https://info.gbiz.go.jp/）を加工して作成
    ```
  - 長形固定文 (docs / landing pages / MCP tool description) — verbatim:
    ```
    本データは経済産業省「Gビズインフォ」（https://info.gbiz.go.jp/ ）が提供する公開
    法人情報を、Bookyou 株式会社（jpcite-api）が編集・加工して作成したものです。
    ライセンスは政府標準利用規約 第2.0版（CC BY 4.0 互換）に準拠します。
    原典：https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406
    最新参照日：2026-05-06
    ```
  - 機械可読 (per-request `_attribution` field) — verbatim:
    ```json
    {
      "_attribution": {
        "source": "Gビズインフォ",
        "publisher": "経済産業省",
        "source_url": "https://info.gbiz.go.jp/",
        "license": "政府標準利用規約 第2.0版 (CC BY 4.0 互換)",
        "license_url": "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        "modification_notice": "Bookyou 株式会社 (jpcite-api) が編集・加工",
        "fetched_via": "gBizINFO REST API v2",
        "snapshot_date": "<ISO8601 fetched_at>"
      }
    }
    ```

- **検証方法**:
  - `tests/test_gbizinfo_attribution.py::test_every_response_carries_attribution`
    - gbiz_* table 由来の任意 sample 100 response について、`_attribution` と `_disclaimer` フィールドが両方存在することを assert
  - `tests/test_gbizinfo_attribution.py::test_attribution_short_form_verbatim`
    - 短形固定文が `attribution_disclaimer_short()` から取得され、verbatim 文字列と完全一致することを assert
  - `tests/test_gbizinfo_attribution.py::test_no_state_org_imitation`
    - response 中に "経済産業省作成" / "国が作成" / "府省作成" 等の偽帰属文言が無いことを grep assert
    - 「編集・加工した情報を、あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません」を厳格遵守
  - middleware level: `GbizAttributionMiddleware` が `X-Source-Cluster: gbizinfo` header に応じて自動 inject

- **違反時 incident response**:
  1. surface without attribution 検知 (e2e test または customer report):
     - 即時該当 endpoint を hotfix で attribution 付きに修正 (24h 以内)
     - audit_log_section52 (mig 101) に `gbiz_attribution_missing_warning` event 記録
  2. 偽帰属検知 (国/府省作成と誤認させる copy):
     - 該当文を即削除、apology メールを gBizINFO 運営に送付 (本書 §6)
     - 全 site / docs / API の grep 走査を 24h 以内に完了

### 条件 5: 第三者権利転嫁回避 (上流外部 DB 由来 license の継承)

- **条件 (verbatim 4795140981406)**:

  > コンテンツの中には、第三者（国以外の者をいいます。以下同じ。）が著作権その他の権利を有している場合があります。第三者が著作権を有しているコンテンツや、第三者が著作権以外の権利（例：写真における肖像権、パブリシティ権等）を有しているコンテンツについては、特に権利処理済であることが明示されているものを除き、利用者の責任で当該第三者から利用の許諾を得てください。
  >
  > 外部データベース等とのAPI（Application Programming Interface）連携等により取得しているコンテンツについては、その提供元の利用条件に従ってください。

- **実装場所**:
  - `src/jpintel_mcp/ingest/_gbiz_attribution.py:build_attribution()` に `upstream_source` 引数を必須で受ける
  - 各 ingest スクリプト (`scripts/cron/ingest_gbiz_*.py`) は record kind ごとに上流 source を hard-coded で指定:
    - corporate_activity_v2 → 国税庁 法人番号公表サイト (PDL v1.0) + 法務省 商業登記 (公示)
    - subsidy_v2 → 経産省 ものづくり / 中小企業庁 IT導入 / JGrants (各 program ToS)
    - certification_v2 → 各省庁 認定制度 (制度別 ToS)
    - commendation_v2 → 各省庁・地方自治体 表彰制度
    - procurement_v2 → 調達ポータル (政府標準利用規約 2.0) + KKJ 官公需 (中企庁)
    - bulk_jsonl_monthly → 上記 5 系統 + 厚生労働省 職場情報総合サイト (しょくばらぼ)
  - jpcite-api 利用規約 (`docs/legal/jpcite_terms.md` 別途) に「gBizINFO 由来データに関する第三者権利クレームは、原典 (各省庁/独立行政法人/民間 DB) の利用条件に従い、利用顧客の責任で確認・処理する」旨を明記
  - raw ZIP / mark base64 の再配布は禁止 (条件 6 と連動)、derived facts の編集加工 + ¥3/req metered のみ

- **検証方法**:
  - `tests/test_gbizinfo_upstream_source.py::test_every_record_has_upstream`
    - gbiz_corp_activity / gbiz_subsidy_award / gbiz_certification / gbiz_commendation / gbiz_procurement の各 sample について `_attribution.upstream_source` が non-null であることを assert
  - `tests/test_gbizinfo_upstream_source.py::test_upstream_source_in_known_set`
    - upstream_source の値が下記 §3 mapping に列挙された既知集合に含まれることを assert (typo / 未登録防止)
  - `tests/test_jpcite_terms_third_party_clause.py`
    - jpcite-api 利用規約に「第三者権利クレームは利用顧客の責任」条項が含まれることを文字列 grep assert

- **違反時 incident response**:
  1. TDB / TSR 系民間 DB から cease-and-desist 通知:
     - 即時 該当 record 取下げ (gbiz_* mirror table の DELETE + 関連 cache evict)
     - 24h 以内に該当 derived fact が API response に含まれないことを e2e で確認
     - operator から書面回答 + 同等取扱の他 record の audit
  2. 各省庁・地方自治体からの申立:
     - 同上の取下げ + 出典記載の即時修正
     - upstream_source mapping を更新
  3. 顧客から第三者権利クレームの転嫁要求:
     - jpcite-api 利用規約 §第三者権利の条項を提示し、顧客側責任を明示
     - 該当 record の出典 URL を顧客に提示し、原典確認を促す

### 条件 6: 個別法令マーク・画像・ロゴ除外

- **条件 (verbatim 4795140981406 「適用除外」)**:

  個別法令マーク表示の利用は法定制限あり: JIS / PSE / PSC / PSLPG / PSTG / 高圧ガス保安 / 液化石油ガス / ガス事業 / 計量法 / 経済連携協定特定原産地証明 等。

  ロゴ / シンボルマーク / キャラクターデザイン、別利用ルールが明示されているコンテンツも適用除外。

- **実装場所**:
  - `scripts/cron/ingest_gbiz_bulk_jsonl_monthly.py` の冒頭に明示 skip list:
    ```python
    SKIP_FIELDS = {
        "image_base64", "logo_base64", "mark_base64",
        "qr_base64", "certificate_image", "shop_image",
        "logo_image", "symbol_mark", "character_image",
        "jis_mark_image", "pse_mark_image", "psc_mark_image",
        "pslpg_mark_image", "pstg_mark_image",
        "kpga_mark_image", "lpga_mark_image", "gas_mark_image",
        "keiryo_mark_image", "epa_origin_mark_image",
    }
    ```
  - 5 つの delta スクリプト (`ingest_gbiz_corporate_v2.py`, `ingest_gbiz_subsidy_v2.py`, `ingest_gbiz_certification_v2.py`, `ingest_gbiz_commendation_v2.py`, `ingest_gbiz_procurement_v2.py`) も同じ SKIP_FIELDS を import して使用
  - migration `105_gbiz_v2_mirror_tables.sql` (実際の番号は次空き番、`-- target_db: autonomath` 必須) では image / logo / mark カラム自体を作成しない (schema-level 除外)
  - REST API v2 の応答にも元来画像 base64 は含まれていない (確認済み)。bulk ZIP 内の余剰フィールドのみ skip 対象
  - audit_log_section52 (mig 101) で `gbiz_image_field_dropped` event を記録 (drop 件数の dashboarding 用)

- **検証方法**:
  - `tests/test_gbizinfo_no_image.py::test_no_image_columns_in_mirror`
    - PRAGMA table_info で gbiz_corp_activity / gbiz_corporation_branch / gbiz_workplace / gbiz_subsidy_award / gbiz_certification / gbiz_commendation / gbiz_procurement の全カラムを取得
    - カラム名が `image*` / `logo*` / `mark*` / `*_image` / `*_logo` / `*_mark` の正規表現に該当しないことを assert
  - `tests/test_gbizinfo_no_image.py::test_no_base64_blob_in_facts`
    - am_entity_facts (corp.* namespace) の value 列で 1024 文字以上の base64 文字列 (`^[A-Za-z0-9+/]+=*$`) が無いことを assert
    - 過去の bulk ingest mishap 検出用 retroactive guard
  - `tests/test_gbizinfo_no_image.py::test_skip_fields_imported`
    - 6 つの ingest スクリプトすべてが共通 `SKIP_FIELDS` 集合を参照していることを assert (DRY 確認)

- **違反時 incident response**:
  1. 画像 / ロゴデータが mirror table に leak した場合:
     - 即時 migration で該当 record を NULL out (rollback companion `*_rollback.sql` を新規作成)
     - 該当 ingest スクリプトの SKIP_FIELDS を強化
     - 過去 30 日分の audit_log を rescan して影響範囲を特定
  2. 個別法令マーク (PSE / JIS 等) が leak した場合:
     - 上記対応に加えて、関連法令所管官庁 (経産省 / 厚労省 / 計量法管轄) に書面で誤掲載と是正を報告
     - 24h 以内に該当データが API response に含まれないことを e2e 確認

---

## 3. 上流外部 DB 提供元 mapping

gBizINFO は集約系 API であり、各 record の license clause は上流提供元の体系を継承する。jpcite-api は per-record `_attribution.upstream_source` を保持し、再配布合法性を上流側に委譲する。

| record kind | 上流 source | license / 体系 | 再配布扱い |
|---|---|---|---|
| 法人活動 (corporate_activity_v2) | 国税庁 法人番号公表サイト | PDL v1.0 (商用再配布可、出典明記) | 個別 attribution + 加工注記で OK |
| 法人活動 (商号変更履歴) | 法務省 商業登記 | 公示制度 (再配布制限あり) | 商号現在値のみ surface、履歴の継続 mirror は不可 |
| 補助金 (subsidy_v2) | 経産省 ものづくり / 中小企業庁 IT導入 / JGrants | 各 program 公表 ToS (大半は政府標準利用規約 2.0) | 個別 attribution + 加工注記で OK |
| 補助金 (各府省採択結果 ZIP) | 各府省 (MAFF / METI / 厚労省 etc) | program 別 ToS (基本は政府標準利用規約 2.0) | 出典明記必須 |
| 認定 (certification_v2) | 各省庁 認定制度 (経営力向上計画 = 中企庁 / 健康経営優良法人 = MHLW / 事業継続力強化計画 = 経産局 / 等) | 制度別 ToS (認定基準・有効期限の正確性は各認定機関に依拠) | 認定状態 fact のみ surface、認定基準書原本の再配布は不可 |
| 表彰 (commendation_v2) | 各省庁 (経産大臣表彰 等) ・地方自治体 (知事表彰 等) | 表彰制度別 ToS、受賞名義の使用範囲は授与機関の規定に依拠 | 受賞 fact + 授与機関 + 年度のみ surface |
| 調達 (procurement_v2) | 財務省 調達ポータル (p-portal) + 中企庁 KKJ官公需 | 政府標準利用規約 2.0 | jpcite では p-portal 直 ZIP を canonical、gBizINFO は法人側逆引き mirror として dedupe (procurement_resource_id) |
| 職場 (workplace) | 厚生労働省 職場情報総合サイト (しょくばらぼ) | 政府標準利用規約 2.0 | 個別 attribution + 加工注記で OK |
| 法人活動 (企業財務) | EDINET (金融庁) / 各社開示 | 金融庁 EDINET 利用規約 | XBRL 派生は別途 EDINET ToS を遵守、本 endpoint では surface しない |

### 3.1 jpcite per-record attribution の実装上の rule

- 全 ingest スクリプトは `build_attribution(upstream_source=...)` を **必須引数** で呼ぶ
- `upstream_source` を省略 / None にした場合、`build_attribution` は `ValueError("upstream_source required for §条件5")` を raise
- 上記 mapping に列挙された既知 source 値以外を渡すと、`tests/test_gbizinfo_upstream_source.py::test_upstream_source_in_known_set` が CI で fail
- 新規 source 追加時は本書 §3 と上記 test の既知集合を同時に更新 (PR review で 1 commit 単位で対応)

---

## 4. Cache TTL ポリシー

### 4.1 24h hard floor の根拠

API ToS §2 (4999421139102) は具体的な利用上限値を **規約上 非開示** としつつ、「短時間における過度なアクセス」「通常の利用範囲を著しく超えるアクセス」を通知なく取消し可能としている。これを upper bound 解釈として、最低 24h cache TTL を defensive default とする:

- diskcache `expire = 86400` 秒
- 同一 path + sorted(querystring) を cache key に採用
- Fly volume `/data/.cache/jpintel/gbiz/` に永続化 (machine restart 後も TTL 継続)

### 4.2 上限超過 cache scrub

- weekly cron (`gbiz-cache-scrub-weekly.yml` を operator が新設、本書改訂時に schedule 確定):
  - 7 日以上 access が無い entry を削除
  - 30 日以上 stale な entry を強制削除
  - cache size > 1 GB で LRU 自動 evict (diskcache の `size_limit` で実装)
- 失敗時は audit_log_section52 に `gbiz_cache_scrub_failed` event を記録、operator に Slack alert

### 4.3 Local cache disk usage

- 上限 1 GB (diskcache `size_limit=1 * 1024 * 1024 * 1024`)
  - 注: DEEP-01 spec §3.1 では 10 GB 上限を提案している (5M corps × 2KB = ~10GB)。1 GB は本書の保守上限であり、bulk cold-start 時のみ一時的に 10 GB へ昇格 (`GBIZ_CACHE_SIZE_LIMIT_BYTES` env で operator が override 可)
- LRU 自動 evict
- Fly volume `/data` 全体で 50 GB 以上の余裕を維持 (現在の autonomath.db 9.4 GB + jpintel.db 352 MB と合算)

### 4.4 Cache 透明性の顧客向け開示

- 全 response に `_cache_meta.cache_age_hours` を埋め込み (`_gbiz_rate_limiter.py:get()` で実装)
- API docs (`docs/api-reference.md`) で「gBizINFO 由来 fact は最大 24h stale」を明記
- webhook 配信時は `gbiz_cache_age_hours` を payload に同梱 (W1_A04 rationale §10 準拠)

---

## 5. 撤退条件

下記いずれかが発生した場合、jpcite-api から gBizINFO 由来 endpoint を切り離す:

1. gBizINFO ToS 改定で「再配布禁止」「1 IP 1 用途限定」「商用 metered API 禁止」等の制限が追加された場合
2. 6 条件のうち 1 つでも遵守不能になった場合 (token 取消し / 1-token 原則の運用上の不備 / 出典固定文の維持困難 等)
3. gBizINFO 運営から申請取消通知 / 利用停止通知が届いた場合

### 5.1 撤退手順

1. **cron 全停止**:
   ```
   gh workflow disable gbiz-ingest-monthly.yml
   ```
2. **Fly secret 削除**:
   ```
   fly secrets unset GBIZINFO_API_TOKEN -a autonomath-api
   ```
3. **既存 mirror data の status review**:
   - すでに加工配信済の fact は法的 license に従って継続保持 (CC BY 4.0 準拠の場合は撤退後も derived 利用は維持可能)
   - 強制削除指示の場合は `scripts/migrations/<NNN>_gbiz_purge.sql` で全 gbiz_* table を DROP + cache scrub
4. **fallback ingest path に切替**:
   - 法人活動: NTA 法人番号公表サイト bulk (PDL v1.0、`scripts/cron/ingest_nta_invoice_bulk.py` 既存)
   - 補助金: jGrants 直接 ingest + 各府省採択 ZIP 直接 (`docs/canonical/` 配下に既設定)
   - 調達: p-portal 直 ZIP (canonical 既存)
   - 認定: 各認定機関の公開 list 直接 ingest (制度別)
   - 表彰: 各省庁公開 page の WARC walk
   - cold-start 用 bulk: 喪失 (差分 ingest のみで運用)
5. **顧客向け開示**:
   - 切替の事実と影響範囲を `docs/api-reference.md` + status page に告知
   - 該当 endpoint を `_disclaimer` で 「データ source 切替中、覆面 stale あり」と明示
   - 顧客 SLA は ¥3/req metered のため、refund 義務は無し (anonymous 3 req/日無料 tier も維持)

### 5.2 撤退前の事前準備 (継続的な運用)

- NTA bulk は既に monthly 自動 (mig 081 + nta-bulk-monthly.yml) で回っており、撤退時は欠損なく fallback 可能
- p-portal は既に canonical として運用中 (gBizINFO は mirror)
- jGrants 直接 ingest は事前に dry-run スクリプトを準備 (`scripts/cron/ingest_jgrants_dry_run.py` 案、本書改訂時に operator が実装)

---

## 6. Rollback comm template (operator → gBizINFO 運営)

```
件名: 【Bookyou株式会社】gBizINFO API 利用一時停止のご連絡

経済産業省 経済産業政策局
gBizINFO 運営事務局 御中

平素より gBizINFO API をご提供いただき誠にありがとうございます。

弊社 Bookyou株式会社 (法人番号 8010001213708) が運営するサービス
jpcite (https://jpcite.com) において、API ご利用条件の見直しが
必要と判断し、本日 YYYY-MM-DD HH:MM (JST) をもって 全 cron ingest
を一時停止いたしました。

【現在の利用状況】
- 1 token (Bookyou株式会社 名義、2026-05-06 申請)
- 平均アクセス頻度: X req/sec (ToS §2 利用上限を defensive に
  1 rps 以下で運用)
- キャッシュ TTL: 24時間 (ToS §2 趣旨に整合する defensive default)
- 出典固定文: 全 response に短形 + 機械可読 _attribution を 100% 付与
- 上流提供元 attribution: per-record で保持
- 個別法令マーク画像: ingest 時に skip (PSE/JIS/PSC 等)

【一時停止の理由】
[該当する事由を記載: ToS 改定 / 6 条件遵守上の懸念 / 自社 audit
で問題検出 / 等]

【今後の対応】
- 1 週間以内に問題箇所の特定と是正策を確定
- 是正完了後、ご運営宛に再開連絡を差し上げます
- 万一 6 条件のいずれかが恒久的に不可となる場合、ご運営の
  ご判断に従って token 返上を実施いたします

ご懸念事項・ご指示等がございましたら下記までご連絡ください。

弊社連絡先:
  Bookyou 株式会社
  代表 梅田茂利
  Email: info@bookyou.net
  所在地: 東京都文京区小日向2-22-1

何卒よろしくお願い申し上げます。

Bookyou株式会社 代表
梅田茂利
```

---

## 7. 監査ログ

`audit_log_section52` (migration 101 `trust_infrastructure`, target_db: autonomath) に以下の event 種別を記録する。Slack digest + RSS feed (`scripts/cron/regenerate_audit_log_rss.py`) で operator 経由 daily 確認:

| event_kind | 発火条件 | severity |
|---|---|---|
| `gbiz_token_loaded` | `_gbiz_rate_limiter.py` module 初期 import | info |
| `gbiz_request_429_fail_fast` | 上流 429 を受信し、自動再発呼せず停止 | error |
| `gbiz_attribution_missing_warning` | response 出力直前で `_attribution` 欠損を検出 | error |
| `gbiz_image_field_dropped` | bulk ingest 時に SKIP_FIELDS に該当する field を drop | info (drop 件数を payload に) |
| `gbiz_cache_hit` | get() で cache hit | debug |
| `gbiz_cache_miss` | get() で cache miss + upstream 発呼 | debug |
| `gbiz_token_at_risk` | 4 時間以上 429 が継続 | critical (Slack alert + 即時 cron 停止) |
| `gbiz_cache_scrub_failed` | weekly cache scrub cron が失敗 | warning |
| `gbiz_upstream_source_unknown` | `build_attribution` に未登録の upstream_source が渡された | error |

### 7.1 監査ログの retention

- audit_log_section52 は無期限保持 (mig 101 で TTL 列なし)
- weekly RSS dump で `audit/section52.rss` (Cloudflare Pages) に publish
- 操作の trace 性確保 (¥3/req metered API の信頼基盤として、5 年以上の retention を solo ops 範囲で維持)

---

## 8. 改訂履歴

| 日付 | 改訂内容 | 改訂者 |
|---|---|---|
| 2026-05-06 | 初版 (DEEP-01 M01 ship 時)。6 条件 + 上流 mapping + cache policy + 撤退条件 + comm template + audit log を確定 | 梅田茂利 (Bookyou株式会社) |

---

## 9. 関連ドキュメント

- `tools/offline/_inbox/public_source_foundation/gbizinfo_tos_verbatim_2026-05-06.md` — ToS verbatim + 6 条件 greenlight 判定
- `tools/offline/_inbox/value_growth_dual/A_source_foundation/parts/W1_A04_gbizinfo_rationale.md` — SourceProfile rationale
- `tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_01_gbizinfo_ingest_activation.md` — 本書親 spec (cron / migration / middleware / test の implementation 計画)
- `docs/_internal/source_foundation_triage_2026-05-06.md` — gbizinfo P0-review (6 条件 launch-blocking) triage
- `docs/legal/jpcite_terms.md` (operator 別途維持) — jpcite-api 顧客向け利用規約 (第三者権利転嫁条項を含む)
- `CLAUDE.md` — V4 absorption gbiz section (79,876 corporate_entity + 861,137 corp.* facts、21 new field_names)
- `scripts/ingest_gbiz_facts.py` — 既存 legacy bulk JSONL ingestor (V4 absorption 時実装)
- `tests/test_gbiz_ingest_integrity.py` — 既存 integrity guard

---

**END of gbizinfo_terms_compliance.md** (本書はバージョン管理の対象。改定時は §8 に必ず追記)
