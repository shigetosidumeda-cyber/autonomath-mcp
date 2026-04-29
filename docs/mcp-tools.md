<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "税務会計AI MCP Tools (89 tools)",
  "description": "税務会計AI は MCP (Model Context Protocol) サーバーとして 89 ツール (39 コア + 50 autonomath at default gates) を公開する。Claude Desktop / Cursor / ChatGPT / Gemini から直接呼び出せる。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://zeimu-kaikei.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://zeimu-kaikei.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://zeimu-kaikei.ai/docs/mcp-tools/"
  }
}
</script>

# MCP Tools

> **要約 (summary):** 税務会計AI は MCP (Model Context Protocol) サーバーとして **89 ツール (39 コア + 50 autonomath)** を default gates で公開する。39 コアは制度 / 採択事例 / 融資 / 行政処分 の 4 データセットに対する search/get、排他判定、バッチ取得、メタ情報、canonical filter 値を事前列挙する `enum_values`、クォータ probe `get_usage_status`、申請者プロフィールから一発判定する `prescreen_programs`、締切カレンダー `upcoming_deadlines`、さらに 5-7 call chain を 1 call に畳む 7 つの one-shot 合成ツール (`smb_starter_pack` / `subsidy_combo_finder` / `deadline_calendar` / `dd_profile_am` / `similar_cases` / `regulatory_prep_pack` / `subsidy_roadmap_3yr`) に加え、拡張データセット: 法令 (e-Gov CC-BY, 法令本文 154 件 + 法令メタデータ 9,484 件・本文ロード継続中) / 税務ruleset (35 件 live) / 適格事業者 (PDL v1.0, 13,801 件 delta) / 判例・入札 と cross-dataset glue ツールを含む。50 autonomath は entity-fact DB (503,930 entities / 6.12M facts / 23,805 relations / 335,605 aliases across tax measures / certifications / laws / authorities / loans / mutual insurance) を `search_tax_incentives` / `search_certifications` / `search_by_law` / `list_tax_sunset_alerts` 等で公開、加えてメタデータ tools 4 (`get_annotations` / `validate` / `get_provenance` / `get_provenance_for_fact`)、静的データセット tools 5 (`list_static_resources_am` / `get_static_resource_am` / `list_example_profiles_am` / `get_example_profile_am` / `deep_health_am`)、lifecycle / graph / rule_engine / abstract / prerequisite (`unified_lifecycle_calendar` / `program_lifecycle` / `prerequisite_chain` / `graph_traverse` / `rule_engine_check` / `program_abstract_structured` / `related_programs`) を含む (`AUTONOMATH_ENABLED=false` で無効化可能、`render_36_kyotei_am` 系は `AUTONOMATH_36_KYOTEI_ENABLED=true` で別途 opt-in、enable で 91 tools。`query_at_snapshot` / `intent_of` / `reason_answer` は env-flag gated off pending fix)。Claude Desktop / Cursor / ChatGPT (Plus 以降) / Gemini から直接呼び出せる。

**Protocol:** MCP 2025-06-18 (FastMCP SDK, Python `mcp` package). Transport: stdio JSON-RPC.

## Audience-別 tool 索引

実務ロール別に「最初に見る tool」を一覧化。AI agent / LLM client が profile から tool を絞り込みする際の 1 hop ガイド。詳細は各 tool 章を参照 (`#tool-name` でジャンプ可)。

| audience | 主要 tool | jump-to |
|---|---|---|
| 税理士 / 認定支援機関 | `search_tax_incentives` / `get_am_tax_rule` / `search_by_law` / `list_tax_sunset_alerts` / `search_certifications` / `search_acceptance_stats_am` | [#税理士-認定支援機関-向け](#税理士--認定支援機関-向け) |
| 行政書士 (建設業) | `search_programs` / `check_exclusions` / `search_loans_am` / `search_certifications` / `get_law_article_am` | [#行政書士-建設業-向け](#行政書士-建設業-向け) |
| SMB 経営者 (LINE bot) | `smb_starter_pack` / `deadline_calendar` / `subsidy_combo_finder` / `list_open_programs` | [#smb-経営者向け](#smb-経営者向け) |
| VC / M&A advisor | `dd_profile_am` / `check_enforcement_am` / `search_acceptance_stats_am` / `similar_cases` | [#vc--ma-advisor-向け](#vc--ma-advisor-向け) |
| AI agent developer | (全 89 tools) / `enum_values_am` / `validate` / `get_provenance` / `graph_traverse` / `get_usage_status` | [#ai-agent-developer-向け](#ai-agent-developer-向け) |

audience 別の章は本ファイル末尾「Audience 別ガイド」に展開。

## 前提 (Setup)

インストール・クライアント設定は [getting-started.md](./getting-started.md#6-mcp-claude-desktop-設定) を参照。

MCP server は stdio 転送で動作する。`autonomath-mcp` バイナリ (`pip install autonomath-mcp` または `uvx autonomath-mcp`) または `python -m jpintel_mcp.mcp.server` で起動可能。

---

## `search_programs`

**目的:** 制度 (補助金 / 融資 / 税制 / 共済) の横断検索。

**引数 (Arguments):**

| name | type | default | description |
|------|------|---------|-------------|
| `q` | string \| null | null | 自由記述。3 文字以上で 全文検索インデックス (3-gram)、2 文字以下は substring 一致 |
| `tier` | string[] \| null | null | `S` / `A` / `B` / `C` / `X` の OR 集合 |
| `prefecture` | string \| null | null | 都道府県名 (完全一致) |
| `authority_level` | string \| null | null | 正本 (英語): `national` / `prefecture` / `municipality` / `financial`。日本語別名 (`国` / `都道府県` / `市区町村` / `公庫`) も受け付け、サーバ側で英語に正規化 |
| `funding_purpose` | string[] \| null | null | 資金用途のフィルタ |
| `target_type` | string[] \| null | null | 対象者種別のフィルタ |
| `amount_min_man_yen` | number \| null | null | 助成上限の下限 (万円) |
| `amount_max_man_yen` | number \| null | null | 助成上限の上限 (万円) |
| `include_excluded` | bool | false | `true` で公開保留中の制度も含める |
| `limit` | int | 20 | 1〜100 |
| `offset` | int | 0 | ページング |
| `fields` | string | `"default"` | `"minimal"` / `"default"` / `"full"`。レスポンスサイズ切替 |

**`fields` 選択肢:**

| 値 | `results[]` の中身 | 目安 |
|----|-------------------|------|
| `minimal` | `unified_id` / `primary_name` / `tier` / `prefecture` / `authority_name` / `amount_max_man_yen` / `official_url` | ~150-300 B/row。list rendering / quick filter |
| `default` (省略時) | 従来の `Program` 全フィールド | 通常の tool chain |
| `full` | `Program` + `enriched` (A-J) + `source_mentions` + lineage (`source_url` / `source_fetched_at` / `source_checksum`) | 深い分析。REST `?fields=full` と shape 同一 |

**戻り値 (Return):**

```json
{
  "total": 153,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "unified_id": "...",
      "primary_name": "...",
      "tier": "A",
      "prefecture": "青森県",
      "amount_max_man_yen": 500,
      "funding_purpose": ["設備投資"],
      "target_types": ["認定新規就農者"],
      "official_url": "https://...",
      "...": "..."
    }
  ]
}
```

結果構造は REST `/v1/programs/search` と同じ ([api-reference.md](./api-reference.md#programs))。

**Claude が呼ぶタイミング:**

- ユーザーが「青森県で使える設備投資補助金を教えて」のような検索系質問をしたとき
- 「IT 導入補助金の一覧」「中小企業向けの補助金」等の条件絞り込み

**Example (Python via FastMCP client):**

```python
await client.call_tool("search_programs", {
    "q": "設備投資",
    "prefecture": "東京都",
    "tier": ["S", "A"],
    "limit": 5,
})
# → {"total": 42, "limit": 5, "offset": 0, "results": [
#     {"unified_id": "...", "primary_name": "ものづくり補助金", "tier": "A",
#      "prefecture": "全国", "amount_max_man_yen": 1000, "official_url": "..."}, ...]}
```

---

## `get_program`

**目的:** 特定制度の完全な詳細を取得 (enriched JSON + source_mentions 付き)。

**引数:**

| name | type | default | description |
|------|------|---------|-------------|
| `unified_id` | string | (required) | 制度の一意 ID (`search_programs` の結果や他ツールで返る) |
| `fields` | string | `"default"` | `"minimal"` / `"default"` / `"full"`。REST `/v1/programs/{unified_id}?fields=...` と parity |

**`fields` 選択肢 (`get_program`):**

| 値 | 中身 |
|----|------|
| `minimal` | 7-key whitelist — UI の最初の表示に十分な見出しだけ |
| `default` | 従来通りの `ProgramDetail` (Program + enriched + source_mentions + lineage)。互換性維持 |
| `full` | 同上。`enriched` / `source_mentions` / lineage は null でも key が必ず存在する契約に揃う |

**戻り値:**

`search_programs` の 1 件分の構造 + `enriched` (A-J 次元の詳細) + `source_mentions` (一次資料 URL + fetched_at) + 取得時点の lineage (`source_url` / `source_fetched_at` / `source_checksum`)。REST `/v1/programs/{unified_id}` と同じ構造 (MCP parity)。

```json
{
  "unified_id": "keiei-kaishi-shikin",
  "primary_name": "経営開始資金",
  "tier": "S",
  "enriched": {
    "A_basics": {"...": "..."},
    "B_target": {"...": "..."},
    "J_statistics": null
  },
  "source_mentions": [
    {"url": "https://www.maff.go.jp/...", "fetched_at": "2026-04-15T..."}
  ],
  "source_url": "https://www.maff.go.jp/...",
  "source_fetched_at": "2026-04-22T13:20:57.045412+00:00",
  "source_checksum": "638865704e10041c",
  "...": "..."
}
```

`source_url` / `source_fetched_at` / `source_checksum` は migration 001 前の旧 DB 行では `null` になる (移行後は必ず埋まる)。

**Claude が呼ぶタイミング:**

- `search_programs` で候補が絞り込まれた後、ユーザーが 1 件の詳細を求めたとき
- 「この制度の申請窓口の締切は？」「必要書類は？」のような掘り下げ質問

**EMPTY 時の挙動:** 該当 `unified_id` が DB に存在しない場合は 404 相当の structured 注記 `{"error": {"code": "not_found", "message": "program not found", "hint": "snapshot_size=N, alternative=search_programs", "retry_with": ["search_programs"]}}` を返す (MCP over JSON-RPC では raise は -32603 Internal Error に畳まれて情報落ちするため、常に dict 返却)。AI agent は `search_programs` で stale id か絶対 not-found か判別可。

**エラー:** 存在しない ID は例外を投げず、上記 EMPTY 注記 と同形で返す。

**Example (Python via FastMCP client):**

```python
await client.call_tool("get_program", {
    "unified_id": "keiei-kaishi-shikin",
    "fields": "full",
})
# → {"unified_id": "keiei-kaishi-shikin", "primary_name": "経営開始資金",
#    "tier": "S", "enriched": {"A_basics": {...}, ...},
#    "source_mentions": [{"url": "https://www.maff.go.jp/...", ...}],
#    "source_url": "https://www.maff.go.jp/...", "source_fetched_at": "2026-04-22T..."}
```

---

## `batch_get_programs`

**目的:** `get_program` を最大 50 件まで一度に叩く。`search_programs` の結果 20 件について全件 enriched を取りたい場合に、20 回 `get_program` を叩くのではなく 1 回で済ませる。

**引数:**

| name | type | default | description |
|------|------|---------|-------------|
| `unified_ids` | string[] | (required) | 1〜50 件の制度 ID。重複は自動 dedupe (最初の出現順で一意化)。空配列 / 50 超は構造化エラー注記 (`error.code="empty_input"` / `"too_many"`) |

**戻り値:**

```json
{
  "results": [
    {
      "unified_id": "keiei-kaishi-shikin",
      "primary_name": "経営開始資金",
      "tier": "S",
      "enriched": {"A_basics": {"...": "..."}},
      "source_mentions": [],
      "source_url": "https://...",
      "source_fetched_at": "2026-04-22T...",
      "source_checksum": "638865...",
      "...": "..."
    }
  ],
  "not_found": ["UNI-typo-1"]
}
```

| field | type | description |
|-------|------|-------------|
| `results` | object[] | 各要素は `get_program(fields="full")` と同じ shape。dedupe 後の入力順を保存 |
| `not_found` | string[] | DB で解決できなかった ID (例外ではなく部分成功扱い。空でない batch は 404 にしない) |

`enriched` / `source_mentions` / lineage 3 キーは `null` でも必ず存在する (`fields="full"` の契約と同じ)。

**Claude が呼ぶタイミング:**

- `search_programs` で絞り込まれた 20 件候補について、全件の詳細を一気に取得したいとき
- 比較 UI で候補リストの各行に enriched 情報を展開したいとき
- 「この 10 件全部について必要書類を横並びで教えて」のような比較系指示

**エラー:**

- `ValueError: unified_ids required` — 空配列
- `ValueError: unified_ids cap is 50, got N` — 50 件超
- 個別 ID の解決失敗は**例外にしない** (`not_found` に入る)

**Rate limit:** 現状は batch 全体で 1 リクエスト扱い (TODO: 将来 N 件 × N 単位の credits 会計に移行予定。`src/jpintel_mcp/api/programs.py` の `batch_get_programs` docstring 参照)。

---

## `list_exclusion_rules`

**目的:** 排他ルール全件の列挙。

**引数:** なし。

**戻り値:**

```json
[
  {
    "rule_id": "agri-001",
    "kind": "mutex",
    "severity": "absolute",
    "program_a": "keiei-kaishi-shikin",
    "program_b": "koyo-shuno-shikin",
    "program_b_group": [],
    "description": "同時受給不可",
    "source_notes": "MAFF 要綱第3条",
    "source_urls": ["https://..."],
    "extra": {}
  }
]
```

**Claude が呼ぶタイミング:**

- ユーザーが「どの補助金を併用すると失格になる？」と聞いたとき
- 農業制度の全体像 (新規就農 / 認定農業者 / スーパー L の依存関係) を表示するとき

**注:** 現在 181 件 (hand-seeded 35 = 農業核心 22 + 非農業 13 + 要綱 PDF からの heuristic 抽出 146)。kind 内訳 `exclude` 125 / `prerequisite` 17 / `absolute` 15 / その他 24。 146 件の heuristic 抽出は人手レビュー済みだが取りこぼしの可能性が残る。 [exclusions.md](./exclusions.md) 参照。

---

## `check_exclusions`

**目的:** 候補制度セットを渡して、併用した場合に triggered する排他ルールを列挙。

**引数:**

| name | type | default | description |
|------|------|---------|-------------|
| `program_ids` | string[] | (required) | 制度 ID の配列 (unified_id または農業 canonical 名) |

**戻り値:**

```json
{
  "program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"],
  "hits": [
    {
      "rule_id": "agri-001",
      "kind": "mutex",
      "severity": "absolute",
      "programs_involved": ["keiei-kaishi-shikin", "koyo-shuno-shikin"],
      "description": "同時受給不可",
      "source_urls": ["https://..."]
    }
  ],
  "checked_rules": 35
}
```

**Claude が呼ぶタイミング:**

- ユーザーが複数の候補制度をリストアップして「これ全部併用できる？」と聞いたとき
- `search_programs` で複数候補を提示した後、自動的に安全性チェックをかけたいとき

> **限界:** ルール母集団は 181 件 (hand-seeded 35 + 要綱 PDF heuristic 抽出 146)。 `hits: []` は「未登録の組合せ」を含むため安全保証ではない。 実申請前に `source_urls` の一次資料を人手で確認することを caller (LLM client) は user に明示すること。

**エラー:** 空配列は例外 (`ValueError: program_ids required`)。

---

## `get_meta`

**目的:** データセット概況 (制度数 / tier 分布 / 都道府県分布 / ルール数 / ingest 時刻)。

**引数:** なし。

**戻り値:**

```json
{
  "total_programs": 13578,
  "tier_counts": {"S": 46, "A": 468, "B": 3174, "C": 6310, "X": 1213},
  "prefecture_counts": {"青森県": 42, "_none": 4311},
  "exclusion_rules_count": 181,
  "case_studies_count": 2286,
  "loan_programs_count": 108,
  "enforcement_cases_count": 1185,
  "last_ingested_at": "2026-04-22T09:00:00Z",
  "data_as_of": "2026-04-23"
}
```

**Claude が呼ぶタイミング:**

- ユーザーが「データベースの網羅範囲は？」「最新いつ？」と聞いたとき
- デバッグ用に dataset の生存確認

---

## 採択事例 / 融資 / 行政処分 ツール

制度 (programs) と並ぶ 3 つのデータセットそれぞれに `search` / `get` ツールが用意されている。全て同一の検索モデル (全文検索インデックス (3-gram) + 構造化フィルタ) で、primary-source lineage (`source_url` + `fetched_at`) を全行に含む。REST 相当エンドポイントの詳細引数は [OpenAPI spec](./api-reference.md#openapi-spec) を参照 (`/v1/case-studies/*`, `/v1/enforcement/*`, `/v1/loans/*` は OpenAPI JSON のみで定義、`api-reference.md` への個別章は未掲載)。

### `search_case_studies` / `get_case_study`

**目的:** 2,286 件の採択事例 (Jグランツ公開済み) を検索・取得。

**代表引数 (search):** `q`, `program_ids[]`, `company_size`, `prefecture`, `year`, `limit`, `offset`。
**取得:** `get_case_study(case_id)` で詳細。
**EMPTY 時の挙動 (get_case_study):** `case_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=2286, alternative=search_case_studies"}}`。

### `search_loan_programs` / `get_loan_program`

**目的:** 108 件の融資プログラム (日本政策金融公庫 + 民間協調など) を検索・取得。**担保 / 個人保証人 / 第三者保証人の三軸で独立に条件指定できる**のが主な差別化点。

**代表引数 (search):** `q`, `collateral_required`, `personal_guarantor_required`, `third_party_guarantor_required`, `target_type[]`, `amount_min_man_yen`, `amount_max_man_yen`, `rate_max`, `limit`, `offset`。
**取得:** `get_loan_program(loan_id)` で詳細。
**EMPTY 時の挙動 (get_loan_program):** `loan_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=108, alternative=search_loan_programs"}}`。

### `search_enforcement_cases` / `get_enforcement_case`

**目的:** 1,185 件の行政処分 (補助金適正化法・景表法・特商法等) を検索・取得。取引先や委託業者の過去処分を確認する実コンプライアンスユースケース向け。

**代表引数 (search):** `q`, `agency`, `year`, `company_name`, `action_type`, `limit`, `offset`。
**取得:** `get_enforcement_case(case_id)` で詳細。
**EMPTY 時の挙動 (get_enforcement_case):** `case_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=1185, alternative=search_enforcement_cases"}}`。

これら 3 セットを `search_programs` と組み合わせると、「この補助金に採択された同業者の事例は?」「この融資は無担保・無保証で通せるか?」「検討中の業者に処分歴はないか?」を 1 セッションで解決できる。

---

## `prescreen_programs`

**目的:** 申請者プロフィールから「いま応募できる制度はどれか」をランク付きで一発判定。`search_programs` + `check_exclusions` + amount 適合判定を 1 コールに束ねる。

**引数:**

| name | type | default | description |
|------|------|---------|-------------|
| `prefecture` | string \| null | null | 曖昧入力可 (`Tokyo` / `東京` / `東京都`)。サーバ側で canonical に正規化 |
| `industry_jsic` | string \| null | null | JSIC 業種 (例: `A-011`) |
| `is_sole_proprietor` | bool \| null | null | `true` で `sole_proprietor` / `個人事業主` 系 target_type に match |
| `is_corporation` | bool \| null | null | `true` で `corporation` / `法人` 系 target_type に match |
| `employees` | int \| null | null | 従業員数 |
| `planned_investment_man_yen` | number \| null | null | 想定投資額 (万円)。`amount_max_man_yen` との比較で caveat 生成 |
| `declared_certifications` | string[] \| null | null | 保有する認定 (例: `認定新規就農者`)。prerequisite caveat の抑止に使う |
| `limit` | int | 20 | 1〜100 |

**戻り値 (抜粋):**

```json
{
  "total_considered": 1203,
  "profile_echo": {"prefecture": "東京都", "is_sole_proprietor": true},
  "results": [
    {
      "unified_id": "...",
      "primary_name": "...",
      "fit_score": 4,
      "match_reasons": ["prefecture一致: 東京都", "個人事業主 OK", "amount_max 十分"],
      "caveats": []
    }
  ]
}
```

**特徴:**

- rows は caveat で「隠さず」、理由を添えて残す (「足りない可能性」「認定新規就農者 未申告」等)
- 公開保留中 / excluded 行は常に除外
- `profile_echo` に入力の正規化結果を返すので、UI は canonical 表示で echo できる

**Example (Python via FastMCP client):**

```python
await client.call_tool("prescreen_programs", {
    "prefecture": "東京都",
    "industry_jsic": "E",
    "is_sole_proprietor": False,
    "employee_count": 15,
    "planned_investment_man_yen": 500,
    "limit": 10,
})
# → {"total_considered": 1203, "profile_echo": {"prefecture": "東京都", ...},
#    "results": [{"unified_id": "...", "primary_name": "...",
#                 "fit_score": 4, "match_reasons": [...], "caveats": []}, ...]}
```

---

## `upcoming_deadlines`

**目的:** 今日から `within_days` 以内に締切 (`application_window.end_date`) を迎える制度を昇順で返すカレンダー。

**引数:**

| name | type | default | description |
|------|------|---------|-------------|
| `within_days` | int | 30 | 1〜180。今日〜今日+N 日 の範囲でフィルタ |
| `prefecture` | string \| null | null | Tokyo/東京/東京都 いずれも OK。**nationwide と prefecture 未設定行は常に含める** |
| `authority_level` | string \| null | null | `national` / `prefecture` / `municipality` / `financial` (JP 別名可) |
| `tier` | string[] \| null | null | tier フィルタ (OR 集合) |
| `limit` | int | 50 | 1〜100 |

**戻り値:**

```json
{
  "as_of": "2026-04-24",
  "within_days": 30,
  "total": 12,
  "results": [
    {
      "unified_id": "...",
      "primary_name": "...",
      "end_date": "2026-05-04",
      "days_remaining": 10,
      "tier": "A",
      "prefecture": "東京都",
      "authority_level": "prefecture",
      "amount_max_man_yen": 500,
      "application_url": "https://..."
    }
  ]
}
```

**Claude が呼ぶタイミング:**

- 「今月・来月の締切教えて」「30 日以内に出せる東京の補助金は?」
- 各行の `end_date` と `application_url` は actionable row 契約 (`next_deadline` / `application_url`) と同じ値

---

---

## 4-dataset 拡張ツール (2026-04-24 追加)

既存 15 ツールに加え、法令 (e-Gov法令, CC-BY) / 判例 (裁判所) / 入札 (GEPS + 自治体) / 税務ruleset (インボイス+電帳法) / 国税庁適格事業者 (PDL v1.0) の 4 データセットに対応した 16 ツールを公開する。制度横断の `trace_program_to_law` / `find_cases_by_law` / `combined_compliance_check` によって「この補助金の根拠法は？」「この条文が争点になった判例は？」「新規事業で抵触する法令・税務・入札資格は？」を 1 セッションで解決できる。

### `search_laws`

**目的:** 日本の法令 (e-Gov法令) を横断検索。法令名・条文本文に対して 全文検索インデックス (3-gram) + 構造化フィルタ (法令種別 / 所管省庁 / 施行日) を適用。全件 CC-BY ライセンスで一次資料 URL + fetched_at 付き。

### `get_law`

**目的:** 特定の法令 ID から完全な法令本文 (目次 + 全条文 + 附則) を取得。`search_laws` / `find_precedents_by_statute` / `trace_program_to_law` の結果で返る law_id を渡して詳細展開に使う。
**EMPTY 時の挙動:** `law_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=9484, alternative=search_laws"}}`。AI agent は `search_laws` で stale id か絶対 not-found か判別可。

### `list_law_revisions`

**目的:** 1 法令の改正履歴をタイムライン化。各 revision の施行日・改正理由・全文 diff へのリンクを返す。「この補助金の根拠法が過去 5 年でどう変わったか」を追うときに呼ぶ。

### `search_court_decisions`

**目的:** 裁判所公開の判例を横断検索 (最高裁 / 高裁 / 地裁 / 簡裁)。事件番号・争点キーワード・判決年月日・審級でフィルタ、主文・判示事項・参照条文を一次資料 URL 付きで返す。

### `get_court_decision`

**目的:** 判例 1 件の完全詳細 (当事者・事実関係・争点・判示事項・主文・参照条文・下級審履歴) を取得。`search_court_decisions` / `find_precedents_by_statute` / `find_cases_by_law` の候補を深堀する用途。
**EMPTY 時の挙動:** `decision_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=2065, alternative=search_court_decisions"}}`。

### `find_precedents_by_statute`

**目的:** 条文指定 (法令ID + 条番号) から「この条文を直接引用した判例」を抽出。`search_laws` → 該当条文 → `find_precedents_by_statute` の chain で、制度の運用実態 (執行の厳格さ / 解釈揺れ) を確認するための横断検索。

### `search_bids`

**目的:** 国・自治体の入札案件 (GEPS + 47 都道府県) を横断検索。発注機関・品目・発注予定金額・入札方式 (一般競争 / 指名 / 随意契約) でフィルタ。入札公告 URL + 仕様書リンク + 公示日時を lineage として返す。

### `get_bid`

**目的:** 入札案件 1 件の完全詳細 (発注機関 / 品目 / 仕様書 / 参加資格 / 入札方式 / 予定価格 / 落札結果) を取得。`bid_eligible_for_profile` の結果や `search_bids` ヒット行から深堀するときに呼ぶ。
**EMPTY 時の挙動:** `bid_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=362, alternative=search_bids"}}`。

### `bid_eligible_for_profile`

**目的:** 申請者プロフィール (等級・地域・業種・実績) を渡して参加可能な入札案件をランク付きで返す一発判定。`prescreen_programs` の入札版: 等級不足 / 地域外 / 指名実績不足 は hide せず caveat として surface。

### `search_tax_rules`

**目的:** インボイス制度・電子帳簿保存法の施行ルール (ruleset) を横断検索。適用対象取引・経過措置期間・適格要件・罰則でフィルタ。国税庁告示・通達・FAQ への一次資料 lineage 付き。

### `get_tax_rule`

**目的:** 税務 ruleset 1 件の完全詳細 (適用要件 / 経過措置 / 帳簿要件 / 例外規定 / 関連 Q&A) を取得。具体的な取引パターンが現行の経過措置でどう扱われるか、の確定情報を得るのに使う。
**EMPTY 時の挙動:** `rule_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=35, alternative=search_tax_rules"}}`。

### `evaluate_tax_applicability`

**目的:** 取引プロフィール (取引額 / 登録事業者フラグ / 取引日付 / 書類形式) を渡して、インボイス + 電帳法の適用判定と必要な対応を返す。「この仕入は仕入税額控除できる？」「このメール請求書は保存要件を満たす？」を rules engine で判定。

### `search_invoice_registrants`

**目的:** 国税庁 適格請求書発行事業者 公表システム (PDL v1.0 で再配布可) を横断検索。法人番号 / 事業者名 / 登録日 / 登録取消日でフィルタ。取引先の登録状況確認 + 失効監視の実務用途向け。出典明記 + 編集注記の下流提供対応。

### `trace_program_to_law`

**目的:** 補助金・融資制度の根拠法・根拠告示を辿る (`unified_id` → `law_id` + 条番号)。`program_law_refs` 結合テーブルを索引し、「この制度の交付要綱は何法の何条を根拠にしているか」を一次資料付きで返す。制度廃止リスク評価や法改正トラッキングに使う。

### `find_cases_by_law`

**目的:** 法令 (law_id + 条番号) から「その条文を直接引用した行政処分事例」を検索。`enforcement_decision_refs` 経由で `search_enforcement_cases` と連携し、「この条文違反でどのような処分が何件出ているか」を実証的に把握。

### `combined_compliance_check`

**目的:** 事業プロフィール + 予定取引を渡して、関連する法令 / 判例傾向 / 税務要件 / 入札資格制限を横断評価。cross-dataset glue の最上位ツール: 複数データセットの検索結果を 1 レスポンスに束ねて、「新規事業で抵触する制度・判例・税務・入札資格」を 1 セッションで棚卸しできる。

---

## One-shot 合成ツール (7 件)

5-7 call の chain を 1 call に畳む synth tool 群。`smb_starter_pack` / `subsidy_combo_finder` / `deadline_calendar` 等は profile 1 個渡すだけで section 構成済みの bundle が返るため LINE bot / Slack bot / DD report 等で UI 後処理ゼロで使える。precision/recall ではなく shape gate (sections non-empty + profile echo) で評価。

### `smb_starter_pack`

**目的**: SMB 経営者プロフィール (prefecture / industry_jsic / employees) から「最初に見るべき補助金 + 融資 + 税優遇 + 同業処分件数」を 1 レスポンスで返す入口 bundle。
**引数**: `prefecture` (str, required) / `industry_jsic` (str, optional) / `employees` (int, optional, default=10) / `is_sole_proprietor` (bool, optional)
**戻り値**: `{"profile_echo": {...}, "top_subsidies": [...], "top_loans": [...], "tax_hints": [...], "same_industry_enforcement_count": N, "meta": {...}}`
**呼ぶタイミング**: LINE bot / Slack bot で SMB ユーザーが最初に投げる「うち何使える？」一発質問への返答時。
**EMPTY 時の挙動**: 該当 prefecture が canonical 解決不能の場合 `meta.suggestions[]` に近隣都道府県候補 + `input_warnings: ["unknown_prefecture"]` を返す (空配列の section は空のまま、404 にはしない)。
**Audience**: SMB 経営者 / Dev

```python
smb_starter_pack(prefecture="東京都", industry_jsic="A-011", employees=15)
# → {"profile_echo": {...}, "top_subsidies": [10 件], "top_loans": [5 件], ...}
```

### `subsidy_combo_finder`

**目的**: profile + budget から併用可能な「補助金 + 融資 + 税制」3-tuple combo を排他ルールチェック付きで列挙。
**引数**: `prefecture` (str, required) / `industry_jsic` (str, optional) / `planned_investment_man_yen` (number, optional) / `limit` (int, default=10)
**戻り値**: `{"combos": [{"subsidy": {...}, "loan": {...}, "tax_rule": {...}, "conflict_rule_id": null}, ...], "profile_echo": {...}}`
**呼ぶタイミング**: ユーザーが「○万円投資する、補助金 + 融資 + 税制全部使った最大セット教えて」と言った時。
**EMPTY 時の挙動**: 0 combo の場合 `combos: []` + `meta.suggestions: ["budget を下げる", "industry_jsic を外す"]` を返す。
**Audience**: SMB 経営者 / 行政書士

> **限界:** combo 候補は editorial template (手動作成 56 件) と排他ルール 181 件 (hand-seeded 35 + 要綱 PDF heuristic 抽出 146) を組み合わせて生成する。 一般的な組合せパターンの参考としては有用だが、 `conflict_rule_id: null` (= ルール未登録) は「併用安全」を保証しない。 実申請前に必ず一次資料を確認すること。

```python
await client.call_tool("subsidy_combo_finder", {
    "keyword": "ものづくり",
    "prefecture": "東京都",
    "limit": 3,
})
# → {"combos": [{"subsidy": {...}, "loan": {...}, "tax_rule": {...},
#                "conflict_rule_id": null}, ...], "profile_echo": {...}}
```

### `deadline_calendar`

**目的**: profile から今日〜horizon (default 3 ヶ月) 以内の締切を月別 bucket + 7 日以内 urgent カウントで返すカレンダー。
**引数**: `months_ahead` (int, 1..6, default=3) / `prefecture` (str, optional) / `tier` (str[], optional, default=S/A/B/C)
**戻り値**: `{"months_ahead": 3, "total": N, "by_month": {"2026-05": [...], "2026-06": [...]}, "urgent_next_7_days": N, "empty_months": ["2026-08"], "source": {...}}`
**呼ぶタイミング**: 「今月・来月の締切」「3 ヶ月先まで予定立てたい」一発取得。
**EMPTY 時の挙動**: 0 件の場合 `by_month: {}` + `empty_months: [...]` で「該当月に締切なし」を明示 (404 にしない)。
**Audience**: SMB 経営者 / 行政書士

```python
await client.call_tool("deadline_calendar", {
    "months_ahead": 3,
    "prefecture": "東京都",
})
# → {"months_ahead": 3, "total": 18, "by_month": {
#     "2026-05": [{"unified_id": "...", "name": "...", "end_date": "2026-05-15",
#                  "days_left": 19, "amount_max_man_yen": 500, "tier": "A"}],
#     "2026-06": [...]}, "urgent_next_7_days": 2, "empty_months": []}
```

### `dd_profile_am`

**目的**: 法人番号 (houjin_bangou) 1 個から DD 用 dossier (採択履歴 / 適格事業者状態 / 行政処分 / 法人基本情報) を 1 call で構築。
**引数**: `houjin_bangou` (str, required, 13桁) / `include_facts` (bool, default=True)
**戻り値**: `{"entity": {...}, "adoptions": [...], "invoice_registrant": {...}, "enforcement": [...], "facts": {...}, "audit_log": [...]}`
**呼ぶタイミング**: VC / M&A advisor が DD 中、対象法人を 13 桁番号で 1 発 dossier 化したい時。
**EMPTY 時の挙動**: 該当 houjin_bangou が DB に無い場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=87093 corporate entities, alternative=search_invoice_registrants"}}`。
**Audience**: VC / M&A advisor

```python
await client.call_tool("dd_profile_am", {
    "houjin_bangou": "3040001101014",
    "include_adoptions": True,
    "adoption_limit": 20,
})
# → {"entity": {"houjin_bangou": "3040001101014", "name": "...", ...},
#    "adoptions": [{"program": "...", "year": 2024, "amount_yen": 5000000}, ...],
#    "invoice_registrant": {"registered_at": "2023-10-01", ...},
#    "enforcement": [], "facts": {...}}
```

### `similar_cases`

**目的**: seed case_id (or seed description) から Jaccard similarity + program_used boost で類似採択事例を返す。
**引数**: `case_id` (str, optional) / `description` (str, optional) / `industry_jsic` (str, optional) / `prefecture` (str, optional) / `limit` (int, default=10)
**戻り値**: `{"seed": {...}, "similar": [{"case_id": "...", "similarity": 0.62, "program_used": [...]}, ...]}`
**呼ぶタイミング**: 「この事例に似た他社採択例は？」 — 申請書ドラフト時の類似事例参照。
**EMPTY 時の挙動**: seed 不在 → 404、similar=0 件 → `similar: []` + `meta.suggestions: ["industry_jsic で広げる"]`。
**Audience**: SMB 経営者 / 行政書士

```python
await client.call_tool("similar_cases", {
    "case_id": "mirasapo_case_120",
    "limit": 5,
})
# → {"seed": {"case_id": "mirasapo_case_120", "company_name": "...", ...},
#    "similar": [{"case_id": "mirasapo_case_543", "similarity": 0.62,
#                 "program_used": ["ものづくり補助金"]}, ...]}
```

### `regulatory_prep_pack`

**目的**: profile から「適用される法令 + 必要認定 + 税務 ruleset + 直近行政処分」4 sections を bundle。新規事業立ち上げ前の compliance 棚卸し用。
**引数**: `industry` (str, required, JSIC letter / 和名 / EN slug) / `prefecture` (str, optional) / `company_size` (literal "sole"|"small"|"medium"|"large", optional) / `include_expired` (bool, default=False) / `limit_per_section` (int, optional)
**戻り値**: `{"laws": [...], "certifications": [...], "tax_rulesets": [...], "recent_enforcement": [...], "profile_echo": {...}}`
**呼ぶタイミング**: 新規事業 launch 前 compliance check / 行政書士の業種開業 due-diligence。
**EMPTY 時の挙動**: 各 section 独立に空配列で返す (どこかが空でも 404 にしない)。
**Audience**: 行政書士 / VC

```python
await client.call_tool("regulatory_prep_pack", {
    "industry": "建設業",
    "prefecture": "東京都",
    "company_size": "small",
})
# → {"laws": [{"law_id": "...", "name": "建設業法", ...}, ...],
#    "certifications": [{"name": "建設業許可", ...}, ...],
#    "tax_rulesets": [{"rule_id": "invoice-001", ...}, ...],
#    "recent_enforcement": [...], "profile_echo": {...}}
```

### `subsidy_roadmap_3yr`

**目的**: 24-36 ヶ月先までの application_round を JST 会計年度 quarter bucket で並べ、申請計画の roadmap を返す。
**引数**: `prefecture` (str, optional) / `industry_jsic` (str, optional) / `horizon_months` (int, default=36)
**戻り値**: `{"by_quarter": {"2026Q2": [...], "2026Q3": [...]}, "total_rounds": N, "as_of": "..."}`
**呼ぶタイミング**: 中長期で「次の補助金 cycle どこか」資金調達計画を立てる時。
**EMPTY 時の挙動**: `by_quarter: {}` + `total_rounds: 0` で空返却 (404 にしない)。
**Audience**: SMB 経営者 / VC

---

## Autonomath ツール (28 件、`AUTONOMATH_ENABLED=true` で有効)

`autonomath.db` (503,930 entities / 6.12M facts / 23,805 relations / 335,605 aliases) を expose する 28 tools。entity-fact EAV schema 上で「税優遇 / 認定 / 法令 / 採択統計 / 融資 / 共済 / 行政処分」を横断検索。V1 17 + メタデータ tools 4 + 静的データセット tools 7 (本ツール群は環境変数 `AUTONOMATH_ENABLED=false` で全無効化可能)。

### `search_tax_incentives`

**目的**: 税優遇制度 (中小企業税制 / 特別償却 / 税額控除等) を期間 / 業種 / 適用条件で横断検索。
**引数**: `query` (str, optional) / `authority` (str, optional, e.g. '国税庁') / `industry` (str, optional) / `target_year` (int, optional) / `target_entity` (str, optional) / `limit` (int, default=20)
**戻り値**: `SearchResponse[TaxIncentive]` = `{"results": [...], "total": N, "meta": {...}}`
**呼ぶタイミング**: 税理士が「2026-04 時点で使える特別償却」を抽出する時。
**EMPTY 時の挙動**: 0 件返却 + `meta.suggestions[]` で alternative_intents (例: `[{"intent": "search_certifications", "rationale": "..."}]`)。
**Audience**: 税理士 / 認定支援機関

```python
await client.call_tool("search_tax_incentives", {
    "query": "特別償却",
    "industry": "製造業",
    "target_year": 2026,
    "limit": 10,
})
# → {"total": 23, "results": [{"canonical_id": "tax_measure:...",
#     "primary_name": "中小企業経営強化税制", "rule_type": "special_depreciation",
#     "rate": 1.0, "target_taxpayer": "...", "effective_until": "2027-03-31"}, ...]}
```

### `search_certifications`

**目的**: 認定制度 (経営革新計画 / 先端設備等導入計画 / 認定新規就農者等) を要件 / 認定機関 / 期限で横断検索。
**引数**: `query` (str, optional) / `authority` (str, optional, e.g. '経済産業省') / `size` (literal "sole"|"small"|"sme"|"mid"|"large", optional) / `industry` (str, optional) / `as_of` (str, default="today") / `limit` (int, default=20)
**戻り値**: `SearchResponse[Certification]`
**呼ぶタイミング**: 行政書士が建設業の業務に必要な認定を抽出する時 / 税理士が補助金申請の前提認定を確認する時。
**EMPTY 時の挙動**: 0 件返却 + `meta.suggestions[]` で別 record_kind の検索を提案。
**Audience**: 税理士 / 行政書士

```python
await client.call_tool("search_certifications", {
    "query": "経営革新",
    "size": "sme",
    "industry": "建設業",
})
# → {"total": 8, "results": [{"canonical_id": "certification:...",
#     "primary_name": "経営革新計画承認", "authority": "都道府県",
#     "requirements": "...", "benefits_after_certification": "..."}, ...]}
```

### `list_open_programs`

**目的**: 現時点で application_round が open している制度を時系列に列挙。
**引数**: `as_of` (date, optional, default=today) / `prefecture` (str, optional) / `limit` (int, default=50)
**戻り値**: `SearchResponse[Program]` (sort: end_date ASC)
**呼ぶタイミング**: 「今出せるやつ全部」一発取得 / SMB starter 判断。
**EMPTY 時の挙動**: 0 件返却 + `meta.suggestions: [{"intent": "list_open_programs", "args": {"prefecture": null}}]`。
**Audience**: SMB 経営者 / Dev

### `enum_values_am`

**目的**: autonomath.db 側の canonical enum (record_kind / relation_type / industry_jsic / target_profile 等) を事前に列挙。AI agent が search 引数を組み立てる前の正規化用。
**引数**: `field` (str, required) / `prefix` (str, optional)
**戻り値**: `{"field": "...", "values": [{"value": "...", "label": "...", "count": N}, ...]}`
**呼ぶタイミング**: agent が search 前に「使える industry_jsic ってどれ？」と聞く時。
**EMPTY 時の挙動**: field 名が unknown → 404 + structured 注記 `{"error": {"code": "unknown_field", "hint": "valid fields: record_kind|relation_type|..."}}`。
**Audience**: Dev

### `search_by_law`

**目的**: 法令名 (canonical or 口語) + 条番号から「その法令に紐づく制度 / 税制 / 認定 / 法令行」を 4 kind 横断で列挙。
**引数**: `law_name` (str, required, e.g. '租税特別措置法' / '大店立地法') / `article` (str, optional, e.g. '第42条の12の4') / `amendment_date` (str, optional, ISO YYYY-MM-DD) / `limit` (int, default=20) / `offset` (int, default=0)
**戻り値**: `{"total": N, "limit": ..., "offset": ..., "results": [{"item_kind": "program|tax_incentive|certification|law", "item_id": "...", "item_name": "...", "root_law": "...", "article": "...", ...}], "law_aliases_tried": [...]}`
**呼ぶタイミング**: 税理士が「租税特別措置法第42条の6 で動いてる制度全部」一発取得時。
**EMPTY 時の挙動**: law_name 不在 → 404、結果 0 → 各セクション空配列。
**Audience**: 税理士 / 行政書士

```python
await client.call_tool("search_by_law", {
    "law_name": "租税特別措置法",
    "article": "第42条の12の4",
    "limit": 20,
})
# → {"total": 7, "results": [{"item_kind": "tax_incentive", "item_id": "...",
#     "item_name": "中小企業経営強化税制", "root_law": "租税特別措置法",
#     "article": "第42条の12の4"}, ...], "law_aliases_tried": ["租特法", "租税特別措置法"]}
```

### `active_programs_at`

**目的**: 任意の日付 `t` で「その日に active な制度」を返す time-travel query。
**引数**: `as_of` (date, required) / `prefecture` (str, optional) / `limit` (int, default=50)
**戻り値**: `SearchResponse[Program]`
**呼ぶタイミング**: 過去事案の DD で「2024-09 時点で開いてた補助金」を再現する時。
**EMPTY 時の挙動**: 0 件返却 + `meta.suggestions: ["horizon を広げる", "prefecture を外す"]`。
**Audience**: VC / Dev

### `related_programs`

**目的**: seed program_id から「同根拠法 / 同 authority / 同 target_type」で関連制度を返す。
**引数**: `seed_program_id` (str, required) / `top_k` (int, default=10)
**戻り値**: `{"seed": {...}, "related": [{"unified_id": "...", "score": 0.7, "reason": "..."}, ...]}`
**呼ぶタイミング**: 「これ落ちたら次に出せるやつは？」 fallback 探索。
**EMPTY 時の挙動**: seed 不在 → 404、related=0 → `related: []`。
**Audience**: SMB 経営者 / 行政書士

### `search_acceptance_stats_am`

**目的**: 採択率 / 件数 / 平均交付額の統計を制度 × 年度 × 都道府県の cross で取得。
**引数**: `program_name` (str, optional, LIKE %name%) / `year` (int, optional, 2010-2099) / `region` (str, optional, '全国' / 47 都道府県 / 8 region) / `industry` (str, optional) / `as_of` (str, default="today")
**戻り値**: `{"buckets": [{"program_id": "...", "year": 2025, "acceptance_rate": 0.42, "n_apply": 1200, "n_grant": 504}, ...]}`
**呼ぶタイミング**: VC が「ものづくり補助金の採択率推移」を投資判断材料に取得時 / 税理士が顧客提案の精度判断時。
**EMPTY 時の挙動**: 0 bucket → `buckets: []` + `meta.suggestions: ["year 範囲を広げる"]`。
**Audience**: VC / 税理士

```python
await client.call_tool("search_acceptance_stats_am", {
    "program_name": "ものづくり",
    "year": 2024,
    "region": "全国",
})
# → {"buckets": [{"program_id": "...", "primary_name": "ものづくり補助金",
#     "year": 2024, "round": "17次", "acceptance_rate": 0.42,
#     "n_apply": 7234, "n_grant": 3038}, ...], "meta": {...}}
```

### `intent_of`

**目的**: 自然言語クエリから「これは search_programs / search_tax_incentives / dd_profile_am のどれを呼ぶべきか」を分類。AI agent の routing 用 LLM-free intent classifier。
**引数**: `query` (str, required)
**戻り値**: `{"intent": "search_programs", "confidence": 0.83, "alternatives": [...]}`
**呼ぶタイミング**: agent が tool 選択前に決定木分岐する時。
**EMPTY 時の挙動**: confidence < 0.3 の場合 `intent: "ambiguous"` + `alternatives` で複数候補返却 (404 にしない)。
**Audience**: Dev

### `reason_answer`

**目的**: 質問 + 候補 entity リストから「この candidate がなぜ答えに該当するか」の根拠を facts/relations 経由で構造化説明。
**引数**: `question` (str, required) / `candidate_ids` (str[], required, max=10)
**戻り値**: `{"explanations": [{"id": "...", "facts": [...], "relations": [...], "score": 0.7}, ...]}`
**呼ぶタイミング**: agent が「これが答えな根拠は？」を user に説明する時。
**EMPTY 時の挙動**: candidate_ids 全件 not_found → `explanations: []` + `meta.warnings: ["all_candidates_missing"]`。
**Audience**: Dev / VC (DD レポート用)

### `get_am_tax_rule`

**目的**: am_tax_rule 1 件の完全詳細 (適用要件 / 経過措置 / 関連条文) を取得。canonical_id か primary_name 部分一致で解決。
**引数**: `measure_name_or_id` (str, required, e.g. 'DX投資促進税制' / 'tax_measure:12_tax_incentives:000013:...') / `rule_type` (literal "credit"|"deduction"|"reduction"|"special_depreciation"|"immediate_writeoff"|"exemption", optional)
**戻り値**: `DetailResponse[TaxRule]`
**呼ぶタイミング**: 税理士が ruleset の適用パターンを精査する時。
**EMPTY 時の挙動**: `rule_id` が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=35, alternative=search_tax_rules"}}`。
**Audience**: 税理士

```python
await client.call_tool("get_am_tax_rule", {
    "measure_name_or_id": "DX投資促進税制",
    "rule_type": "credit",
})
# → {"results": [{"measure_name": "DX投資促進税制", "rule_type": "credit",
#     "rate": 0.03, "rate_preferred": 0.05, "cap_yen": null,
#     "effective_from": "2021-08-02", "effective_until": "2025-03-31",
#     "eligibility": "...", "source_url": "..."}]}
```

### `search_gx_programs_am`

**目的**: GX (グリーン・トランスフォーメーション) 系制度 (脱炭素 / 省エネ / 再エネ) を横断検索。
**引数**: `q` (str, optional) / `prefecture` (str, optional) / `limit` (int, default=20)
**戻り値**: `SearchResponse[Program]`
**呼ぶタイミング**: 製造業 / 建設業の脱炭素投資 financing 探索。
**EMPTY 時の挙動**: 0 件 → `results: []` + `meta.suggestions: [{"intent": "search_programs", "args": {"q": "脱炭素"}}]`。
**Audience**: 行政書士 / SMB 経営者

### `search_loans_am`

**目的**: autonomath.db 側の融資 (am_loan_product) を 担保 / 個人保証 / 第三者保証 三軸 + 業種 + 金利上限で検索。
**引数**: `loan_kind` (str, optional, e.g. 'ippan'|'sogyo'|'saigai'|'kiki') / `no_collateral` (bool, default=False) / `no_personal_guarantor` (bool, default=False) / `no_third_party_guarantor` (bool, default=False) / `max_amount_yen` (int, optional) / `min_amount_yen` (int, optional) / `lender_entity_id` (str, optional, e.g. 'authority:jfc') / `name_query` (str, optional) / `limit` (int, default=10)
**戻り値**: `SearchResponse[LoanProduct]`
**呼ぶタイミング**: 行政書士が建設業者の無担保融資ルートを抽出する時。
**EMPTY 時の挙動**: 0 件 → `results: []` + `meta.suggestions: ["rate_max を上げる", "三軸条件を緩める"]`。
**Audience**: 行政書士 / SMB 経営者

```python
await client.call_tool("search_loans_am", {
    "no_collateral": True,
    "no_personal_guarantor": True,
    "lender_entity_id": "authority:jfc",
    "limit": 5,
})
# → {"total": 12, "results": [{"canonical_id": "loan_product:jfc:...",
#     "primary_name": "新規開業資金 (無担保・無保証人)",
#     "limit_yen": 30000000, "rate_min": 0.014, "rate_max": 0.024,
#     "flags": {"no_collateral": true, "no_personal_guarantor": true,
#               "no_third_party_guarantor": false}}, ...]}
```

### `check_enforcement_am`

**目的**: 法人番号 / 名称から行政処分歴 (am_enforcement_detail) を確認。grant_refund / subsidy_exclude / fine の type 別。
**引数**: `houjin_bangou` (str, optional) / `name` (str, optional) / `since` (date, optional)
**戻り値**: `{"hits": [{"detail_id": "...", "type": "grant_refund", "amount_yen": 1500000, "law_ref": "..."}], "total": N}`
**呼ぶタイミング**: VC / M&A advisor が DD で取引先の処分歴を chunk 確認する時。
**EMPTY 時の挙動**: 0 件 → `hits: [], total: 0` (処分歴なしを示す。404 にしない)。
**Audience**: VC / M&A advisor

### `search_mutual_plans_am`

**目的**: 共済プラン (中小機構小規模企業共済 / 経営セーフティ共済 等) を取得対象 / 月額 / 課税扱いで検索。
**引数**: `q` (str, optional) / `target_type` (str, optional) / `limit` (int, default=20)
**戻り値**: `SearchResponse[MutualPlan]`
**呼ぶタイミング**: 税理士が個人事業主向け節税共済を提案する時。
**EMPTY 時の挙動**: 0 件 → `results: []` + `meta.suggestions: [{"intent": "search_certifications"}]`。
**Audience**: 税理士

### `get_law_article_am`

**目的**: am_law_article 1 件 (法令 ID + 条番号) の本文 + 関連改正履歴を取得。28,048 条文収録。
**引数**: `law_id` (str, required) / `article` (str, required)
**戻り値**: `DetailResponse[LawArticle]`
**呼ぶタイミング**: 行政書士 / 税理士が条文の現行 wording を確認する時。
**EMPTY 時の挙動**: 該当条文が DB に存在しない場合 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=28048 articles, alternative=search_by_law"}}`。
**Audience**: 行政書士 / 税理士

### `list_tax_sunset_alerts`

**目的**: 期限切れ間近 (sunset) の税優遇 / 経過措置を horizon 内で列挙。「2026-09 の 2 割特例終了」のような cliff event を一覧化。
**引数**: `days_until` (int, 1-1825, default=365) / `only_critical` (bool, default=False, 大綱-driven 年度末/年末 cliff のみ) / `limit` (int, 1-500, default=100)
**戻り値**: `{"alerts": [{"rule_id": "...", "sunset_date": "2026-09-30", "days_remaining": 158, "rationale": "..."}, ...]}`
**呼ぶタイミング**: 税理士が「半年以内に消える優遇」を顧問先に通知する時。
**EMPTY 時の挙動**: 0 件 → `alerts: []` + `meta.next_horizon_with_data: 365`。
**Audience**: 税理士 / 認定支援機関

```python
await client.call_tool("list_tax_sunset_alerts", {
    "days_until": 180,
    "only_critical": True,
    "limit": 50,
})
# → {"alerts": [{"rule_id": "...", "measure_name": "DX投資促進税制",
#     "rule_type": "credit", "effective_until": "2025-03-31",
#     "days_remaining": -390, "is_cliff": true,
#     "rationale": "年度末 (3/31) 期限・後継未定"}, ...]}
```

### メタデータ tools (4 件)

#### `get_annotations`

**目的**: entity_id から annotation_kind 別の注釈 (examiner_feedback / glossary / disclosure 等) を取得。16,474 行収録。
**引数**: `entity_id` (str, required, am_entities.canonical_id) / `kinds` (str[], optional, e.g. ["examiner_warning","quality_score"]) / `include_internal` (bool, default=False) / `include_superseded` (bool, default=False)
**戻り値**: `{"entity_id": "...", "annotations": [{"kind": "examiner_feedback", "text": "...", "source": "..."}]}`
**呼ぶタイミング**: agent が「この entity に審査委員のコメントある？」と確認する時。
**EMPTY 時の挙動**: entity_id 不在 → 404、annotation 0 件 → `annotations: []`。
**Audience**: Dev / 行政書士

```python
await client.call_tool("get_annotations", {
    "entity_id": "program:provisional:35be300914",
    "include_internal": True,
})
# → {"entity_id": "program:provisional:35be300914", "total": 3,
#    "annotations": [{"kind": "examiner_warning",
#                     "text": "応募集中ピーク時の競争激化に注意", "visibility": "internal",
#                     "source": "examiner_feedback_2024", "created_at": "2024-...."}, ...]}
```

#### `validate`

**目的**: 6 generic predicate (training_hours / work_days / weekly_hours / start_year / birth_age / desired_amount sanity) を applicant_data に適用、rule 単位の passed/failed/deferred を返す。
**引数**: `applicant_data` (dict, required, nested intake dict) / `entity_id` (str, optional, am_entities.canonical_id for scope) / `scope` (str, default="intake")
**戻り値**: `{"results": [{"rule_id": "...", "passed": true|false|null, "severity": "error|warn", "message_ja": "..."}], "passed": true}`
**呼ぶタイミング**: agent が user 入力を検索投入前に sanity check する時。
**EMPTY 時の挙動**: predicates 全部不在 → `meta.warnings: ["no_predicates_registered"]`、predicates 全 pass → `passed: true`。
**Audience**: Dev

```python
await client.call_tool("validate", {
    "applicant_data": {
        "plan": {"training_hours": 120, "work_days": 240},
        "behavioral": {"weekly_hours": 40, "start_year": 2025},
    },
    "scope": "intake",
})
# → {"passed": true, "results": [
#     {"rule_id": "intake.training_hours.gte_60", "passed": true, "severity": "error"},
#     {"rule_id": "intake.weekly_hours.lte_80", "passed": true, "severity": "warn"}, ...]}
```

#### `get_provenance`

**目的**: entity_id の lineage (source / fetched_at / license / checksum) を一括取得。
**引数**: `entity_id` (str, required, am_entities.canonical_id) / `include_facts` (bool, default=False, per-fact source も返す) / `fact_limit` (int, 1-1000, default=200)
**戻り値**: `{"entity_id": "...", "sources": [{"source_id": "...", "url": "...", "fetched_at": "...", "license": "cc_by_4.0"}]}`
**呼ぶタイミング**: VC / DD で「この情報の出典は？」を 1 hop で確認する時。
**EMPTY 時の挙動**: entity_id 不在 → 404、source 0 → `sources: []`。
**Audience**: VC / Dev

```python
await client.call_tool("get_provenance", {
    "entity_id": "corporate_entity:houjin:3040001101014",
    "include_facts": True,
    "fact_limit": 50,
})
# → {"entity_id": "corporate_entity:houjin:3040001101014",
#    "sources": [{"source_id": "gbiz_2026_q1", "url": "https://info.gbiz.go.jp/...",
#                 "fetched_at": "2026-04-25T...", "license": "gov_standard"}],
#    "facts": [{"fact_id": "...", "field_name": "corp.address", "value": "...",
#               "source_id": "gbiz_2026_q1"}, ...]}
```

#### `get_provenance_for_fact`

**目的**: 単一 fact_id の lineage を取得 (entity 全体ではなく fact 1 行ピンポイント)。
**引数**: `fact_id` (int, required, `am_entity_facts.id` の AUTOINCREMENT integer)
**戻り値**: `{"fact_id": ..., "entity_id": "...", "field_name": "...", "field_value_text": "...", "source": {"source_id": ..., "source_url": "...", "license": "..."}, "fallback": false, "license_summary": {...}}`
**呼ぶタイミング**: 「この値だけの出典」を取りに行く時 (entity 全体じゃなく行単位)。
**EMPTY 時の挙動**: fact_id 不在 → 404 + structured 注記。`source_id` が NULL の legacy fact は entity-level `am_entity_source` の候補 list を `fallback_sources` に返し `fallback: true` を立てる。
**Audience**: VC / Dev

```python
await client.call_tool("get_provenance_for_fact", {
    "fact_id": 12345,
})
# → {"fact_id": 12345, "entity_id": "program:provisional:35be300914",
#    "field_name": "amount_max_yen", "field_value_text": "5000000",
#    "source": {"source_id": 42, "source_url": "https://www.maff.go.jp/...",
#               "license": "pdl_v1.0", "fetched_at": "2026-04-25T..."},
#    "fallback": false}
```

### Lifecycle / Graph / Snapshot / Quota (8 件)

`unified_lifecycle_calendar` / `program_lifecycle` / `prerequisite_chain` / `graph_traverse` / `query_at_snapshot` / `rule_engine_check` / `program_abstract_structured` の 7 つは複合検索の合成ツール、`get_usage_status` は META 系のクォータ probe。すべて `AUTONOMATH_ENABLED=1` 既定で有効 (`get_usage_status` は jpintel 側、それ以外は autonomath 側)。 lifecycle / snapshot 系 (`program_lifecycle` / `query_at_snapshot` / `unified_lifecycle_calendar`) は `am_amendment_snapshot` を参照するため、 改正の日付別追跡には利用できない (各 tool 章の限界注記を参照)。

#### `get_usage_status`

**目的**: META — 1 リクエストを消費せずに API クォータ残量を確認する probe。`anonymous` / `paid` / `free` の tier 別に `limit` / `remaining` / `used` / `reset_at` / `reset_timezone` を返す。
**引数**: `api_key` (str, optional, 省略=anonymous)
**戻り値**: `{"tier": "anonymous", "limit": 50, "remaining": ..., "used": ..., "reset_at": "2026-05-01T00:00:00+09:00", "reset_timezone": "JST", "upgrade_url": "https://zeimu-kaikei.ai/pricing.html", "note": "..."}`
**呼ぶタイミング**: agent が長い batch (例: 60 件 search) を流す前に消費可能数を見積もる時。MCP stdio 経由ではクライアント IP が無いため anonymous 残数は ceiling のみ。`api_key` を渡せば月次の正確な used 数を返す。
**EMPTY 時の挙動**: paid tier は `limit` / `remaining` が `null` (metered, no cap) になる。
**Audience**: Dev / AI agent developer

```python
# anonymous probe (MCP stdio から)
await client.call_tool("get_usage_status", {})
# → {"tier": "anonymous", "limit": 50, "remaining": null, "used": null,
#    "reset_at": "2026-05-01T00:00:00+09:00", "reset_timezone": "JST",
#    "note": "MCP stdio cannot resolve per-IP bucket; HTTP /v1/usage で正確値"}

# api_key 付き probe
await client.call_tool("get_usage_status", {"api_key": "sk_live_..."})
# → {"tier": "paid", "limit": null, "remaining": null, "used": 1742,
#    "reset_at": "2026-05-01T00:00:00+00:00", "reset_timezone": "UTC",
#    "note": "metered billing, no monthly cap"}
```

#### `unified_lifecycle_calendar`

**目的**: tax sunset + program sunset + application close + law cliff + amendment_snapshot を月別/半期別 1 コールに merge。事業計画 / 監査 / 投資判断のための「いつ何が切れるか」カレンダー。
**引数**: `start_date` (str, required, ISO YYYY-MM-DD) / `end_date` (str, required, ISO YYYY-MM-DD, `end - start ≤ 366 日`) / `granularity` (str, default="month", `"month"` | `"half_year"`)
**戻り値**: `{"calendar": [{"period": "2026-05", "events": [{"kind": "tax_sunset", "entity_id": "...", "title": "DX投資促進税制", "date": "2026-03-31", "severity": "critical", ...}]}], "total_events": ..., "severity_counts": {"critical": ..., "warning": ..., "info": ...}, "window": {...}, "data_as_of": "...", "data_quality": {...}}`
**呼ぶタイミング**: 「2026 年下半期に切れる税制 + 補助金 申請窓口を 1 画面で」「半期 (H1/H2) 単位で何が cliff か」のような複合 sunset 確認。1 年超は `out_of_range` で 422 相当。
**EMPTY 時の挙動**: 対象期間にイベント 0 → `total_events: 0` + `calendar: []` + `data_quality.amendment_snapshot_caveat` をそのまま返す。
**Audience**: 税理士 / VC / SMB 経営者

> **限界:** `kind: "amendment"` の event は `am_amendment_snapshot` (14,596 行) から生成されるが、 82.3% の行は historical diff hash が空で、 改正の日付別追跡には利用できない。 確定的に時間軸が引けるのは `effective_from` / `effective_until` を持つ 144 行のみ。 `tax_sunset` / `application_close` / `law_cliff` は別ソース (`am_tax_rule` / `am_application_round` / `laws.effective_until`) なので影響なし。 response の `data_quality.amendment_snapshot_caveat` を必ず読むこと。

```python
await client.call_tool("unified_lifecycle_calendar", {
    "start_date": "2026-05-01",
    "end_date": "2026-10-31",
    "granularity": "month",
})
# → {"total_events": 47, "severity_counts": {"critical": 8, "warning": 12, "info": 27},
#    "calendar": [
#      {"period": "2026-05", "events": [
#        {"kind": "application_close", "title": "ものづくり補助金 第18次",
#         "date": "2026-05-29", "severity": "warning", "entity_id": "..."}, ...]},
#      {"period": "2026-09", "events": [
#        {"kind": "tax_sunset", "title": "中小企業経営強化税制",
#         "date": "2026-09-30", "severity": "critical", "entity_id": "..."}]}],
#    "data_as_of": "2026-04-26", "window": {"start_date": "2026-05-01", ...}}
```

#### `program_lifecycle`

**目的**: 制度 1 件のライフサイクル 8 段階判定 — `abolished` / `superseded` / `sunset_imminent` / `sunset_scheduled` / `amended` / `active` / `not_yet` / `unknown` を 1 コールで決定論的に返す。
**引数**: `unified_id` (str, required, 例: `program:base:3435b5b27e`、`search_programs` / `enum_values_am` で解決) / `as_of` (str, optional, ISO YYYY-MM-DD, 既定=今日 JST)
**戻り値**: `{"unified_id": "...", "status": "active", "as_of": "2026-04-26", "evidence": {"effective_from": "...", "sunset_at": "...", "amendment_snapshots": [...]}, "next_event": {...}}`
**呼ぶタイミング**: 1 件の制度について「今使えるか」「いつ切れるか」を 1 hop で判定したい時。`prescreen_programs` の前段、`get_program` の補助。
**EMPTY 時の挙動**: `unified_id` 不在 → 404 + `error.code="not_found"`。判定材料が不足する場合は `status: "unknown"` + `evidence.gaps: [...]` を返す。
**Audience**: 税理士 / 行政書士 / SMB

> **限界:** この tool は `am_amendment_snapshot` から schema-level snapshot を返す。 14,596 行のうち 82.3% は historical diff hash が空で、 改正の日付別追跡には利用できない。 `effective_from` / `effective_until` が NULL でない 144 行のみ時間軸として確定済み。 `evidence.amendment_snapshots` が `[]` でも「改正なし」を意味しない。 `status` は `effective_from` / `sunset_at` のみで決まり、 中間版 (v1 → v2 → v3) の追跡はできない。

```python
await client.call_tool("program_lifecycle", {
    "unified_id": "program:base:3435b5b27e",
    "as_of": "2026-04-26",
})
# → {"unified_id": "program:base:3435b5b27e", "status": "sunset_scheduled",
#    "as_of": "2026-04-26",
#    "evidence": {"effective_from": "2024-04-01", "sunset_at": "2027-03-31",
#                 "days_until_sunset": 339, "amendment_snapshots": []},
#    "next_event": {"kind": "sunset", "date": "2027-03-31", "severity": "info"}}
```

#### `prerequisite_chain`

**目的**: 制度 1 件の前提条件 chain (認定 → 計画 → 認可 → 補助金本体) を再帰的に展開。`depth=1` で直接前提のみ、`depth>5` は `現実的でない` warning。
**引数**: `target_program_id` (str, required, `program:…` canonical ID, `search_programs` で先に解決) / `depth` (int, 1-10, 既定=3)
**戻り値**: `{"target_program_id": "...", "depth": 3, "chain": [{"node": "...", "depth": 0, "prerequisites": [{"node": "...", "rule_id": "...", "kind": "prerequisite"}, ...]}], "warnings": [...]}`
**呼ぶタイミング**: 「ものづくり補助金を取るには事前に何が要る？」「事業再構築補助金の入口の入口は？」のような階層辿り。
**EMPTY 時の挙動**: target が存在 + 前提ルール 0 → `chain: [{"node": "...", "prerequisites": []}]` + `meta.note: "no_prerequisites_registered"`。target 不在 → 404。
**Audience**: 行政書士 / SMB

```python
await client.call_tool("prerequisite_chain", {
    "target_program_id": "program:04_program_documents:000000:23_25d25bdfe8",
    "depth": 3,
})
# → {"target_program_id": "program:04_program_documents:000000:23_25d25bdfe8",
#    "depth": 3,
#    "chain": [
#      {"node": "program:04_program_documents:000000:23_25d25bdfe8",
#       "depth": 0,
#       "prerequisites": [
#         {"node": "certification:keiei_kakushin", "rule_id": "agri-prereq-007",
#          "kind": "prerequisite", "description": "経営革新計画の承認が前提"}]},
#      {"node": "certification:keiei_kakushin", "depth": 1, "prerequisites": []}],
#    "warnings": []}
```

#### `graph_traverse`

**目的**: 知識グラフの 1-3 hop 探索。`am_relation` の 24,004 edges / 15 relation types 上で BFS。「制度 → 根拠法 → 関連判例 → 過去採択」を 1 SQL で辿る。同種 program 間 hop は `related_programs` を優先。
**引数**: `start_entity_id` (str, required, 例: `program:04_program_documents:000016:IT2026_b030eaea36` / `law:rouki` / `authority:meti`) / `max_depth` (int, 0-3, 既定=2) / `edge_types` (str[], optional, default whitelist は 'related' 以外の 14 種) / `max_results` (int, 1-500, 既定=20) / `min_confidence` (float, 0.0-1.0, 既定=0.0)
**戻り値**: `{"paths": [{"nodes": [...], "edges": [{"source_id": "...", "target_id": "...", "relation_type": "...", "confidence": 0.9}], "total_distance": 2}], "total_paths": ..., "capped": false}`
**呼ぶタイミング**: 異種 entity (program ↔ law ↔ judgment ↔ adoption) を横断したい時。同種 hop なら `related_programs`。
**EMPTY 時の挙動**: start_entity_id 不在または到達 0 → `paths: []` + `meta.note: "seed_isolated"`。
**Audience**: Dev / AI agent developer

```python
await client.call_tool("graph_traverse", {
    "start_entity_id": "program:04_program_documents:000016:IT2026_b030eaea36",
    "max_depth": 2,
    "edge_types": ["governs", "supersedes", "references_law"],
    "max_results": 20,
    "min_confidence": 0.5,
})
# → {"total_paths": 12, "capped": false,
#    "paths": [
#      {"nodes": [
#         {"entity_id": "program:04_program_documents:000016:IT2026_b030eaea36",
#          "kind": "program", "label": "IT導入補助金2026"},
#         {"entity_id": "law:johoshori", "kind": "law", "label": "情報処理促進法"}],
#       "edges": [{"source_id": "program:...", "target_id": "law:johoshori",
#                  "relation_type": "references_law", "confidence": 0.95}],
#       "total_distance": 1}, ...]}
```

#### `query_at_snapshot`

**目的**: programs query を「過去のある日付」の状態に pin する時間軸検索。`valid_from <= as_of_date AND (valid_until IS NULL OR valid_until > as_of_date)` で bitemporal に再現。返却 row + `audit_trail` 3 軸 (`source_url` + `fetched_at` + `valid_from`) を付与。
**引数**: `query_payload` (object, required, `q` / `tier` / `prefecture` / `authority_level` / `program_kind` / `limit` を持つ。`/v1/programs/search` と同形) / `as_of_date` (str, required, ISO YYYY-MM-DD)
**戻り値**: `{"results": [{"unified_id": "...", "primary_name": "...", "tier": "A", ...}], "as_of_date": "2025-10-01", "audit_trail": {"source_url": "...", "fetched_at": "...", "valid_from": "..."}, "total": ...}`
**呼ぶタイミング**: 「2025年4月時点で使えた青森県の補助金は？」のような過去断面で参照したい時。
**EMPTY 時の挙動**: 該当 0 → `results: []` + `audit_trail: null`。`as_of_date` 不正 → `error.code="invalid_date_format"`。
**Audience**: VC / 監査 / 行政書士

> **限界:** この tool は `am_amendment_snapshot` の schema-level snapshot を参照する。 14,596 行のうち 82.3% は historical diff hash が空で、 任意日付における中間版 (v1 → v2) の差分は再現できない。 `valid_from` / `valid_until` が NULL でない 144 行のみ時間軸が確定済み。 法的監査・証拠用途では本 tool 単独に依拠せず、 `source_url` の一次資料 (法令施行日 / 要綱改訂版) を必ず別途確認すること。

```python
await client.call_tool("query_at_snapshot", {
    "query_payload": {
        "q": "DX投資促進税制",
        "tier": ["S", "A"],
        "prefecture": "東京都",
        "limit": 10,
    },
    "as_of_date": "2025-10-01",
})
# → {"total": 3, "as_of_date": "2025-10-01",
#    "results": [{"unified_id": "...", "primary_name": "DX投資促進税制",
#                 "tier": "A", "valid_from": "2024-04-01", "valid_until": "2026-03-31"}],
#    "audit_trail": {"source_url": "https://www.meti.go.jp/...",
#                    "fetched_at": "2025-09-15T...", "valid_from": "2024-04-01"}}
```

#### `rule_engine_check`

**目的**: 1 件の制度 / 認定 / 税制について exclusion / prerequisite / absolute / その他のルールを評価し pass/fail/defer 判定。`alongside_programs` を渡せば併用判定 (`check_exclusions` の単体版 + 出典付き)。
**引数**: `program_id` (str, required, `program:…` / `certification:…` / `loan:…` / `tax_measure_…` / `keiei-kaishi-shikin` 等の human-name token) / `applicant_profile` (object, optional, 将来の predicate 評価用、現状は filter なし) / `alongside_programs` (str[], optional, 同時申請する他制度 ID)
**戻り値**: `{"program_id": "...", "verdict": "pass" | "fail" | "defer", "rules_evaluated": [{"rule_id": "...", "kind": "exclude" | "prerequisite" | "absolute", "verdict": "...", "evidence": {"source_url": "...", "source_notes": "..."}}], "coverage_pct": 0.74}`
**呼ぶタイミング**: 1 件の制度について「いま申請したら失格になる組み合わせは？」を出典付きで返したい時。`check_exclusions` よりも審査寄り (verdict 単一化 + coverage_pct 付き)。
**EMPTY 時の挙動**: program_id に rule 0 件 → `verdict: "pass"` + `rules_evaluated: []` + `meta.note: "no_rules_registered"`。
**Audience**: 行政書士 / SMB / Dev

```python
await client.call_tool("rule_engine_check", {
    "program_id": "keiei-kaishi-shikin",
    "alongside_programs": ["koyo-shuno-shikin"],
})
# → {"program_id": "keiei-kaishi-shikin", "verdict": "fail", "coverage_pct": 0.85,
#    "rules_evaluated": [
#      {"rule_id": "agri-001", "kind": "exclude", "verdict": "fail",
#       "evidence": {"source_url": "https://www.maff.go.jp/...",
#                    "source_notes": "MAFF 要綱第3条 同時受給不可"}}]}
```

#### `program_abstract_structured`

**目的**: I18N — 1 件の program について「閉じた語彙」の構造化日本語抄録を返す。翻訳は呼び出し側 LLM の責務、`official_name_ja` + `legal_id` は verbatim 必須 (`i18n_hints.official_name_must_keep_ja=true`)。launch audience は `foreign_employer` (在日外国人雇用主向け制度 ~191 件)。
**引数**: `program_id` (str, required, `programs.unified_id`、例 `UNI-16b8d86302`) / `audience` (str, default=`"foreign_employer"`, enum: `foreign_employer` / `smb` / `tax_advisor` / `admin_scrivener` / `vc`)
**戻り値**: `{"program_id": "...", "audience": "foreign_employer", "abstract": {"official_name_ja": "...", "legal_id": "...", "summary_ja": "...", "eligibility_ja": [...], "amount_band_ja": "...", "audience_specific_flags": {...}}, "i18n_hints": {"official_name_must_keep_ja": true, "translatable_fields": [...]}}`
**呼ぶタイミング**: 多言語 LLM client が ja → en / vi / zh 等に翻訳する直前の素材取得。LLM に raw `enriched` を流すより token 効率が良い。
**EMPTY 時の挙動**: program_id が `excluded=1` / 公開保留 → `error.code="not_found"`。audience が 5 enum 外 → `error.code="invalid_enum"`。
**Audience**: AI agent developer / 多言語 SaaS

```python
await client.call_tool("program_abstract_structured", {
    "program_id": "UNI-16b8d86302",
    "audience": "foreign_employer",
})
# → {"program_id": "UNI-16b8d86302", "audience": "foreign_employer",
#    "abstract": {
#      "official_name_ja": "外国人材受入れ・定着支援事業",
#      "legal_id": "厚労省告示第123号",
#      "summary_ja": "在日外国人の雇用主が研修・定着支援にかかる費用の一部を補助",
#      "eligibility_ja": ["在日外国人を3名以上雇用する事業主", "研修計画の事前認定が必要"],
#      "amount_band_ja": "上限 500万円 / 補助率 1/2",
#      "audience_specific_flags": {"requires_zairyu_card_check": true}},
#    "i18n_hints": {"official_name_must_keep_ja": true,
#                   "translatable_fields": ["summary_ja", "eligibility_ja", "amount_band_ja"]}}
```

### 静的データセット tools (7 件)

#### `list_static_resources_am`

**目的**: data/autonomath_static/ 配下の 8 静的 taxonomy (seido / glossary / money_types / obligations / dealbreakers / sector_combos / crop_library / exclusion_rules) を一覧。
**引数**: なし
**戻り値**: `{"total": 8, "results": [{"id": "seido", "filename": "seido.json", "size_bytes": ...}, ...]}`
**呼ぶタイミング**: agent 起動時に taxonomy id を index する。
**EMPTY 時の挙動**: 内部 fixture のため通常空にはならない。0 件は internal error。
**Audience**: Dev

```python
await client.call_tool("list_static_resources_am", {})
# → {"total": 8, "results": [
#     {"id": "seido", "filename": "seido.json", "size_bytes": 12453},
#     {"id": "glossary", "filename": "glossary.json", "size_bytes": 8921},
#     {"id": "money_types", ...}, {"id": "obligations", ...},
#     {"id": "dealbreakers", ...}, {"id": "sector_combos", ...},
#     {"id": "crop_library", ...}, {"id": "exclusion_rules", ...}]}
```

#### `get_static_resource_am`

**目的**: static taxonomy 1 個の中身 (rows + schema) を取得。
**引数**: `resource_id` (str, required)
**戻り値**: `DetailResponse[StaticResource]`
**呼ぶタイミング**: agent が JSIC 階層を bulk 取得して enum 化する時。
**EMPTY 時の挙動**: resource_id 不在 → 404 + structured 注記 `{"error": {"code": "not_found", "hint": "alternative=list_static_resources_am"}}`。
**Audience**: Dev

#### `list_example_profiles_am`

**目的**: 5 件の example profile (税理士 / 行政書士 / SMB / VC / Dev) を一覧。Onboarding / demo 用 fixture。
**引数**: なし
**戻り値**: `{"profiles": [{"id": "tax_advisor", "label": "税理士", "industry_jsic": "..."}, ...]}`
**呼ぶタイミング**: 初回 demo / docs example 生成時。
**EMPTY 時の挙動**: 内部 fixture のため通常空にはならない。
**Audience**: Dev

#### `get_example_profile_am`

**目的**: example profile 1 個の完全詳細を取得。
**引数**: `profile_id` (str, required)
**戻り値**: `DetailResponse[ExampleProfile]`
**呼ぶタイミング**: demo 環境で profile を 1 個 inject する時。
**EMPTY 時の挙動**: profile_id 不在 → 404 + structured 注記 `{"error": {"code": "not_found", "hint": "snapshot_size=5, alternative=list_example_profiles_am"}}`。
**Audience**: Dev

#### `render_36_kyotei_am`

**目的**: 36 協定 (時間外労働協定) の届出書テンプレートを profile から render。和暦 (令和) + jp_money 形式準拠。
**引数**: `profile` (object, required) / `format` (str, default="markdown")
**戻り値**: `{"rendered": "...", "metadata": {...}, "warnings": [...]}`
**呼ぶタイミング**: 行政書士が建設業 36 協定の下書きを生成する時。
**EMPTY 時の挙動**: profile 不足項目 → `warnings: ["missing: employer_address"]`、render は best-effort。
**Audience**: 行政書士

#### `get_36_kyotei_metadata_am`

**目的**: 36 協定テンプレート metadata (項目 schema / 必須 / 任意 / バリデーションルール) を取得。
**引数**: なし
**戻り値**: `{"schema": {...}, "required_fields": [...], "validation_rules": [...]}`
**呼ぶタイミング**: render 前に form を組み立てる時 / agent が bind する前に schema を確認する時。
**EMPTY 時の挙動**: 内部 fixture のため通常空にはならない。空 → `{"error": {"code": "internal_error"}}` 扱い。
**Audience**: 行政書士 / Dev

#### `deep_health_am`

**目的**: autonomath.db / jpintel.db / FTS index / vec index の latency + row count + last_ingested_at を 1 call で診断。`/v1/am/health/deep` REST と parity。
**引数**: なし
**戻り値**: `{"status": "ok", "checks": [{"name": "autonomath.db", "row_count": 503930, "latency_ms": 12, "ok": true}, ...]}`
**呼ぶタイミング**: ops が deploy 後 / ingest 後の health check 時。
**EMPTY 時の挙動**: いずれかの check が fail → `status: "degraded"` + `checks[i].ok=false` (200 で返す。500 にしない、operator が degraded を可視化するため)。
**Audience**: Dev / Ops

---

## Audience 別ガイド

### 税理士 / 認定支援機関 向け

主要 5 tool: `search_tax_incentives` / `get_am_tax_rule` / `search_by_law` / `list_tax_sunset_alerts` / `search_certifications`。代表 chain:

1. `list_tax_sunset_alerts(horizon_days=180)` で半年以内の cliff を全取得 → 顧問先通知の素材化
2. `search_tax_incentives(industry_jsic="<顧客業種>", effective_at="2026-04-01")` で現行使える優遇を抽出
3. `search_by_law(law_id="...", article="42-6")` で根拠法から派生制度を横断
4. `search_acceptance_stats_am(program_id="...")` で採択率を提案精度判断材料に

### 行政書士 (建設業) 向け

主要 5 tool: `search_programs` / `check_exclusions` / `search_loans_am` / `search_certifications` / `get_law_article_am`。代表 chain:

1. `search_certifications(target_type=["建設業"])` で必要認定を列挙
2. `search_programs(prefecture="...", target_type=["建設業"])` で補助金 candidate
3. `check_exclusions(program_ids=[...])` で併用可否
4. `search_loans_am(industry_jsic="D-...", collateral_required=false)` で資金調達 plan B

### SMB 経営者向け

主要 4 tool (LINE bot 想定): `smb_starter_pack` / `deadline_calendar` / `subsidy_combo_finder` / `list_open_programs`。代表 1-shot:

1. `smb_starter_pack(prefecture="東京都", industry_jsic="...", employees=15)` で入口 bundle
2. `deadline_calendar(horizon_days=90)` で締切を月別 bucket に
3. `subsidy_combo_finder(planned_investment_man_yen=500)` で補助金 + 融資 + 税制 combo

### VC / M&A advisor 向け

主要 4 tool: `dd_profile_am` / `check_enforcement_am` / `search_acceptance_stats_am` / `similar_cases`。代表 chain:

1. `dd_profile_am(houjin_bangou="...")` で対象法人 dossier
2. `check_enforcement_am(houjin_bangou="...")` で処分歴 cross check
3. `search_acceptance_stats_am(program_id="...")` で投資判断の根拠データ
4. `get_provenance(entity_id="...")` で出典 chain を確認

### AI agent developer 向け

全 89 tools 利用可。導線設計のキー tool: `enum_values_am` (引数の正規化先列挙) / `validate` (入力 sanity check) / `get_provenance` (出典 chain) / `graph_traverse` (異種 entity 横断) / `get_usage_status` (batch 前のクォータ probe)。

- 起動時: `enum_values_am(field="record_kind")` で agent の system prompt に注入
- 受信時: `intent_of(query=...)` で routing
- 検索後: `reason_answer(question=..., candidate_ids=[...])` で根拠生成
- レスポンス前: `validate(payload=...)` で sanity check
- 監査時: `get_provenance(entity_id=...)` で出典 chain

---

## 関連

- [api-reference.md](./api-reference.md) — 同機能を REST で叩く場合の仕様
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [getting-started.md](./getting-started.md) — Claude Desktop 連携設定
