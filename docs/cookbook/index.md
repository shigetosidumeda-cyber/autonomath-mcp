# Cookbook (12 recipes)

jpcite の REST API / MCP サーバーをすぐ動かせる **5-15 行サンプル集**。各レシピは 1 つの cohort (税理士、M&A、補助金 consultant、信金 / 商工会、AI agent install など) を起点とし、curl / Python / MCP のいずれかで完結する。

各レシピは以下を含む:

- TL;DR
- runnable サンプル (curl + bash / Python / MCP)
- expected output 抜粋
- **代替手段 vs jpcite cost** (¥3/req 税込 ¥3.30 ベース)
- 該当する場合: 行政書士法 §1 / 税理士法 §52 / 弁護士法 §72 disclaimer

> **匿名枠**: anonymous は IP あたり 3 req/日 (JST 翌日 00:00 リセット)。API key 発行は [pricing](../pricing.md) を参照。

## 全 12 レシピ

| ID | タイトル | 主 cohort | コスト | 免責 |
|---|---|---|---|---|
| [R01](r01-weekly-alert-per-client.md) | 顧問先別 補助金 weekly alert | C2 ZEI | ¥3/顧問先/週 | §52 |
| [R02](r02-tax-cliff-digest.md) | 税法改正 cliff-date weekly digest | C2 ZEI | ¥3/週 | §52 |
| [R03](r03-monthly-invoice-verify.md) | 月次申告 適格事業者番号 bulk verify | C2 ZEI | ¥3/T 番号 | PDL v1.0 出典 |
| [R09](r09-corp-360-view.md) | 法人 360 view (1-call evidence packet) | C1 MA | ¥3/法人 | §72 + §52 |
| [R10](r10-case-studies-search.md) | 類似採択事例 検索 (JSIC × 都道府県) | C5 HOJ | ¥3/検索 | — |
| [R11](r11-enforcement-watch.md) | 行政処分 watch (clawback / weekly cron) | C1 MA | ¥3/週 | (M&A 文脈で §72) |
| [R16](r16-claude-desktop-install.md) | Claude Desktop に jpcite を 5 分で組む | All | ¥0 install + ¥3/call | — |
| [R17](r17-cursor-mcp.md) | Cursor IDE に jpcite を組み込む | All | ¥0 install + ¥3/call | — |
| [R18](r18-chatgpt-custom-gpt.md) | ChatGPT Custom GPT に jpcite Action を入れる | All | ¥0 setup + ¥3/call | — |
| [R19](r19-gemini-extension.md) | Gemini に jpcite を function declaration で渡す | All | ¥0 setup + ¥3/call | — |
| [R20](r20-openai-agents.md) | OpenAI Agents SDK で jpcite を MCP サーバーとして使う | All | ¥0 setup + ¥3/call | — |
| [R21](r21-pref-heatmap.md) | 47 都道府県 補助金 heatmap (tier=S/A) | C7 SKK | ¥141/build | — |

## Cohort 早見表

- **C1 MA** (M&A pre-DD): R09, R11
- **C2 ZEI** (税理士): R01, R02, R03
- **C5 HOJ** (補助金 consultant): R10
- **C7 SKK** (信金 / 商工会 organic): R21
- **All** (AI agent install / 全 cohort 共通): R16, R17, R18, R19, R20

## コスト概観

| シナリオ | 月コスト | jpcite 倍率 (vs 手動) |
|---|---|---|
| 税理士 (R01-R03) 顧問先 50 社 / 月 | ¥600-3,000 | 約 800x 削減 |
| M&A pre-DD (R09, R11) target 10 社 / 月 | ¥30-300 | 約 1,000-25,000x 削減 |
| 補助金 consultant (R10) 案件 30 件 / 月 | ¥90-450 | 約 2,500x 削減 |
| 信金 / 商工会 (R21) heatmap weekly | ¥600-1,000 | 約 280x 削減 |
| AI agent install (R16-R20) | ¥0 install + per-call | hallucination 大幅低減 |

> 上記倍率は CLI 巡回 (¥5,000/h 換算) との比較。詳細は各レシピ本文の「代替手段 vs jpcite cost」表を参照。

## 関連

- [API reference](../api-reference.md)
- [MCP tools 一覧](../mcp-tools.md)
- [Pricing](../pricing.md)
