---
title: "AutonoMath: 日本の公的制度データを Claude に渡す MCP サーバー（72 ツール (39 jpintel + 33 autonomath at default gates)、protocol 2025-06-18）"
description: "AutonoMath ローンチ記事 (Article 2 of 2) — MCP サーバーで Claude Desktop に 13,578 件の補助金データを直接渡す。72 ツール (39 jpintel + 33 autonomath at default gates)、protocol 2025-06-18、全件 source_url 付き。"
tags:
  - mcp
  - claude
  - llm
  - python
  - japan
published: false
---

# AutonoMath: 日本の公的制度データを Claude に渡す MCP サーバー（72 ツール (39 jpintel + 33 autonomath at default gates)、protocol 2025-06-18）

## Claude に補助金を聞いても、2020 年のデータが返ってくる問題

Claude Desktop に「東京都で使える農業補助金を教えて」と入力したことがある人は、
同じ体験をしているはずです。

- 制度名が 2~3 年古い
- 金額が一桁違う
- URL を開くと 404
- そもそも実在しない制度を自信満々に答える

これは Claude の性能の問題ではなく、**日本の制度データが LLM の外にしかない**問題です。
補助金は年度改正が当たり前で、学習時点で正確だった情報が申請期に古くなる。

AutonoMath は MCP サーバーとして、
**13,578 件の補助金・融資・税制・認定制度**を Claude に直接渡します。
全件に `source_url` + `fetched_at` を付与しており、
LLM が「このデータは◯年◯月◯日に取得したものです」と自己申告できます。

ツール構成は 72 ツール (39 jpintel + 33 autonomath at default gates: 39 コア [基本 + one-shot + 法令/判例/入札/税務ruleset/適格事業者 + cross-dataset glue] + 33 autonomath: V1 + V4 universal + Phase A absorption: entity-fact DB 503,930 entities + 6.12M facts + 23,805 relations を 税制優遇 / 認定制度 / 法令 / 処分 / 融資 / 共済 / annotations / validation / provenance 横断で検索)。

---

## 30 秒でセットアップ

`~/Library/Application Support/Claude/claude_desktop_config.json` に追加します。

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

`uvx` がなければ `pip install autonomath-mcp` のあと、
`command` を `"autonomath-mcp"` に変えてください。

Claude Desktop を再起動すると、
ハンマーアイコンの下に `autonomath` の 72 ツール (39 jpintel + 33 autonomath at default gates) が並びます。

!!! info "API キーは任意"
    API キーは匿名 50 req/月 per IP（JST 月初 00:00 リセット）まで不要です。
    それ以上利用する場合は `env` に追加してください。
    ```json
    {
      "mcpServers": {
        "autonomath": {
          "command": "uvx",
          "args": ["autonomath-mcp"],
          "env": {
            "AUTONOMATH_API_KEY": "am_xxxxxxxxxxxxxxxx"
          }
        }
      }
    }
    ```
    料金は **¥3/req（税別）、税込 ¥3.30**。Tier なし、完全従量。

---

## 実際の会話ログ

Claude Desktop での実機操作を再現します。

---

**Turn 1（ユーザー）**

> 埼玉県鴻巣市で 100ha の米農家をやっている法人が、
> 設備投資で使える国の補助金を上限金額の大きい順に 5 件教えて。

**Claude（ツール呼び出し）**

```python
search_programs(
    prefecture="埼玉県",
    target_types=["法人"],
    funding_purpose=["設備投資"],
    crop_categories=["米"],
    sort="amount_desc",
    limit=5
)
```

**Claude（回答）**

> 以下の 5 件がヒットしました（金額は上限）。
>
> 1. 農業経営基盤強化準備金制度（全国・税制・上限なし）
> 2. 強い農業・担い手づくり総合支援交付金（全国・補助金・上限 5,000 万円）
> 3. 農業近代化資金（全国・融資・上限 1 億 8,000 万円）
> 4. 埼玉県農業経営改善支援事業（埼玉県・補助金・上限 500 万円）
> 5. 農業経営開始資金（全国・融資・上限 1,500 万円）
>
> 各制度の出典 URL と取得日時を添付します。最終判断は source_url の原文でご確認ください。

---

**Turn 2（ユーザー）**

> この中で、世帯所得 1,200 万円だと除外されるものはある？

**Claude（ツール呼び出し）**

```python
check_exclusions(
    unified_ids=[
        "national_tax_maff_junbiki_xxx",
        "national_subsidy_maff_sousetsu_xxx",
        "national_loan_maff_kinrin_xxx",
        "saitama_subsidy_pref_keiei_xxx",
        "national_loan_jfc_kaikei_xxx"
    ],
    applicant_type="法人",
    household_income=12000000
)
```

**Claude（回答）**

> 5 件中 1 件に除外ルールが該当しました。
>
> - **4 番「埼玉県農業経営改善支援事業」**
>   ルール PREF_SAI_INCOME_CAP: 世帯所得 1,000 万円以下の申請者が対象。
>   出典: https://www.pref.saitama.lg.jp/...
>
> 残り 4 件は世帯所得による除外なし。

---

このやり取りで、Claude は `search_programs` と `check_exclusions` を**自律的に選んでいます**。
ユーザーは「検索して」「ルール判定して」と一度も言っていません。

---

## 72 ツール (39 jpintel + 33 autonomath at default gates) の構成（protocol 2025-06-18）

### 38 コア (jpintel.db: programs + case_studies + loan_programs + enforcement + expansion + 7 one-shot)

| カテゴリ | 主なツール |
|----------|-----------|
| 制度検索・詳細 | `search_programs` / `get_program` |
| 採択事例 2,286 件 | `search_case_studies` |
| 融資 108 件（三軸担保） | `search_loan_programs` |
| 行政処分 1,185 件 | `search_enforcement_cases` |
| 排他チェック 181 本 | `list_exclusion_rules` / `check_exclusions` |
| 4-dataset 拡張 | `search_laws` / `search_bids` / `search_tax_rulesets` 他 |
| インボイス・メタ | `lookup_invoice_registrant` / `get_meta` |

38 コアの内訳は 15 基本 + 16 拡張（法令 / 判例 / 入札 / 税務ruleset / 適格事業者 + cross-dataset glue）+ 7 one-shot discovery (smb_starter_pack / subsidy_combo_finder / deadline_calendar / dd_profile_am / similar_cases / regulatory_prep_pack / subsidy_roadmap_3yr) です。

### 28 autonomath (entity-fact DB)

autonomath.db（8.29 GB, 読み取り専用、unified primary）上の entity-fact lookup layer。
**503,930 entities + 6.12M facts + 23,805 relations + 335,605 aliases** を
税制優遇 / 認定制度 / 法令 / 処分 / 融資 / 共済 / 法人 / 採択 / 統計 の 12 record_kind 横断で検索できます。
FTS5 trigram + unicode61 + sqlite-vec の tiered index でベクトル近傍も同居。
v0.3.0 で V4 universal (annotations / validate / provenance) + Phase A absorption (静的 taxonomy / example profile / 36協定 template / deep health) を追加。

| カテゴリ | ツール |
|----------|--------|
| 税制・認定検索 | `search_tax_incentives` / `search_certifications` / `get_am_tax_rule` |
| 開催制度・履歴 | `list_open_programs` / `active_programs_at` / `search_acceptance_stats_am` |
| 法令・横断 | `search_by_law` / `get_law_article_am` / `related_programs` |
| enum・意図解釈 | `enum_values_am` / `intent_of` / `reason_answer` |
| GX・融資・処分・共済 | `search_gx_programs_am` / `search_loans_am` / `check_enforcement_am` / `search_mutual_plans_am` |

---

## 設計上のこだわり（ひとつだけ）

### 全ツール返り値に source_url + fetched_at をインラインで付与

メタデータエンドポイントに分離しない。
全 72 ツールの返り値、13,578 件中 99%以上に
`source_url`（一次資料 URL）と `fetched_at`（当社取得日時）が入っています（12件は小規模自治体 CMS 不在のため URL 未取得）。

`fetched_at` は「当社が最後に取得した日時」です。
「制度が最終更新された日時」ではありません。
この区別は景品表示法・消費者契約法上の誠実さとして守っています。

---

## Claude Desktop 以外の利用方法

Python SDK から MCP クライアントとして直接接続できます。

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(
    command="uvx",
    args=["autonomath-mcp"],
    env={"AUTONOMATH_API_KEY": "am_xxxxxxxxxxxxxxxx"},
)

async def main():
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_programs",
                {"prefecture": "東京都", "limit": 5},
            )
            print(result)

asyncio.run(main())
```

---

## 注意点: 制度は年度ごとに改正される

API は毎週更新しますが、制度本体は年度改正で
内容・金額・期限が変わります。

!!! warning "LLM の最終確認"
    LLM が最終的に金額や申請期限をユーザーに伝える前に、
    **必ず source_url の原文を参照**してください。
    AutonoMath は「データを出す」API であり、「採択確率を予測する」API ではありません。

---

## まとめ

- 30 秒で Claude Desktop に 13,578 件の補助金データを組み込める
- 72 ツール (39 jpintel + 33 autonomath at default gates)（protocol 2025-06-18）で検索・排他判定・融資・事例・法令・entity-fact lookup layer (503,930 entities / 6.12M facts / 23,805 relations) をカバー
- ¥3/req 税別（税込 ¥3.30）、匿名 50 req/月 per IP 無料
- `source_url` + `fetched_at` を 99%以上の行に付与、一次資料のみ参照

**AutonoMath: https://autonomath.ai**

MCP レジストリ:

- PyPI: https://pypi.org/project/autonomath-mcp/

---

*Bookyou株式会社 / info@bookyou.net*
