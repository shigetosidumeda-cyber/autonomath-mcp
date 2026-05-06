---
title: "jpcite を 5 つの仕事に使う — 税理士・行政書士・SMB・VC・Dev"
description: "jpcite を実務に組み込む 5 つの walkthrough — 税理士 / 行政書士 / SMB 経営者 / VC・M&A / AI 開発者。"
tags:
  - api
  - mcp
  - 税理士
  - 行政書士
  - vc
published: false
date: 2026-05-06
author: Bookyou株式会社
---

# jpcite を 5 つの仕事に使う

> 公開日: 2026-05-06

jpcite は「日本の制度データを 1 query にまとめた API」です。
誰がどう使うかを 5 シナリオで示します。Claude Desktop / Cursor / Cline などの MCP クライアント、または ChatGPT Custom GPT の OpenAPI Actions から呼ぶ前提です。

---

## 1. 税理士 — 法人税 措置法の特例検索 walkthrough

クライアントから「中小企業向けの設備投資特例ってまだあります？」と聞かれた場面。

```
[Claude Desktop with autonomath MCP]

You: 中小企業の設備投資で 2026 年度に使える税額控除を、措置法の根拠条文つきで列挙して

Claude: search_tax_incentives(keyword="設備投資") を呼びます…
       評価期限が来る順に並べたうえで、措置法 X 条 (取得時期 / 控除率 / 適用期限)
       と、関連する経営力向上計画認定 (search_certifications) と、
       対応する補助金 (search_programs) を 1 メッセージにまとめます。

→ list_tax_sunset_alerts で「来期失効する特例」も同時に見える化
→ trace_program_to_law で各補助金の根拠法条文に飛べる
```

実務効果: 国税庁通達 + 措置法 + 関連補助金の横断調査を **1 prompt** に圧縮。
1 件 ¥3 / 匿名 3 req/日 無料。月数千円で運用可能。

---

## 2. 行政書士 — 補助金 + 融資 + 許認可 1 call

「飲食店オープン支援したい、補助金 + 融資 + 食品衛生許可をまとめて出して」

```python
import requests

# Step 1: 補助金候補
progs = requests.get(
    "https://api.jpcite.com/v1/programs/search",
    params={"q": "飲食店 開業", "prefecture": "東京", "limit": 20},
).json()

# Step 2: 排他チェック
excl = requests.post(
    "https://api.jpcite.com/v1/exclusions/check",
    json={"unified_ids": [p["unified_id"] for p in progs["results"]]},
).json()

# Step 3: 融資候補 (3 軸: 担保/個人保証人/第三者保証人)
loans = requests.get(
    "https://api.jpcite.com/v1/loan-programs/search",
    params={"purpose": "開業", "no_personal_guarantor": True, "limit": 10},
).json()

# Step 4: 許認可
auths = requests.get(
    "https://api.jpcite.com/v1/am/certifications",
    params={"q": "食品衛生"},
).json()
```

4 リクエスト ≒ ¥12。クライアント 1 件あたりのリサーチコストが 1 桁分減ります。

---

## 3. SMB 経営者 — LINE で月 10 件まで free

LINE で jpcite のフロントを公開しています (post-launch)。

```
You: 神奈川の製造業 (10人) で使える補助金ある？

Bot (jpcite via LINE):
  ✓ 「ものづくり補助金」(最大 1,000 万円)
  ✓ 「事業再構築補助金 (post-tier)」(最大 1.5 億円)
  ✓ 「神奈川県設備投資促進補助金」(最大 200 万円)
  ⚠ ものづくり + 事業再構築は **同一設備への併給不可** (排他ルール 011)

  詳細 → https://jpcite.com/programs/UNI-xxxxx
```

匿名 3 req/日、API key 不要。経営者本人が直接触れる料金帯にしてあります。

---

## 4. VC / M&A advisor — 法人番号で due diligence

ターゲット企業の法人番号 (`T1234567890123`) を投げると 1 query で全部出ます。

```python
result = requests.post(
    "https://api.jpcite.com/v1/am/dd_batch",
    json={"houjin_bangous": ["1234567890123"], "max_cost_jpy": 3},
).json()

# 含まれる:
# - 適格請求書発行事業者登録 (国税庁 PDL v1.0)
# - 過去採択履歴 (補助金・助成金)
# - 行政処分歴 (1,185 ケース横断)
# - 関連法令 (am_law / e-Gov)
# - 関連訴訟・判例 (court_decisions, post-launch)
```

**主要な公開行に source_url + fetched_at つき** — 引用付きで report に貼れます。
M&A 1 件あたりのデュー期間が短縮できる想定。

---

## 5. AI agent developer — MCP / REST 統合 example

### MCP (Claude Desktop)

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

これだけで 139 ツールが即時アクティブ。`search_programs` `check_exclusions` `prescreen_programs` `subsidy_combo_finder` 等を Claude / Cursor / ChatGPT から自然言語で呼べます。

### REST (Python SDK / TypeScript SDK)

```python
from autonomath import Client
client = Client()  # anon: 3 req/日 free per IP
results = client.programs.search(q="DX 中小企業", prefecture="大阪")
```

```typescript
import { jpcite } from "@autonomath/sdk";
const c = new jpcite();
const r = await c.programs.search({ q: "DX 中小企業", prefecture: "大阪" });
```

### 開発者 向け価格

- ¥3/req tax-excl (¥3.30 incl)
- 匿名 3/日 free per IP
- API key 取得は self-serve: <https://jpcite.com/dashboard.html>

---

## まとめ

| Audience | 主な使い方 | 月額目安 |
|---|---|---|
| 税理士 | 措置法 + 補助金 + 認定の横断 | ¥0–¥3,000 |
| 行政書士 | 補助金 + 融資 + 許認可 1 call | ¥0–¥10,000 |
| SMB 経営者 | LINE で月 10 件相談 | **¥0** |
| VC / M&A | 法人番号で due diligence | 案件単位 ¥30–¥300 |
| Dev | MCP / REST 統合 | 利用量次第 |

質問は [info@bookyou.net](mailto:info@bookyou.net)。

---

© 2026 Bookyou株式会社 · info@bookyou.net · jpcite
