---
title: "HE-3 agent_briefing_pack demo"
date_modified: "2026-05-17"
license: "PDL v1.0 / CC-BY-4.0"
---

# HE-3 `agent_briefing_pack` — 1 call で 5 turn を 1 turn に圧縮するデモ

`agent_briefing_pack` は **Heavy-Output Endpoint HE-3**。1 つの `topic` ×
`target_segment` を入力に、context / current_law (verbatim) / 通達 / 判例 /
実務指針 / 落とし穴 / 次の一手 / N1 テンプレ / N4 filing window / 業法 envelope
の **10 セクション** を **3 つの出力フォーマット** (Claude XML / OpenAI JSON /
Markdown) で返します。

- NO LLM 推論。pure SQLite + Python composition。
- 1 call ¥3 metered (税込 ¥3.30)。
- 5 segment 対応: 税理士 / 会計士 / 中小経営者 / AX_engineer / FDE。

このページは「税理士 agent が顧問先に **役員報酬の損金算入** を説明する 1 turn」
の流れを示します。

## 想定シナリオ

顧客 (中小企業経営者) → 税理士 agent → MCP / Claude:

> 顧問先から「役員報酬を期中で増額したいけれど、損金算入は大丈夫か」と聞かれた。
> 説明資料を作ってほしい。

通常の (HE-3 未使用) flow は **5 turn 必要**:

1. agent: 「定期同額給与の定義 を教えて」
2. tool: `search_tax_incentives("役員報酬")`
3. agent: 「関連通達は?」
4. tool: `get_law_article_am("法人税法第34条")`
5. agent: 顧客説明 draft を出力

HE-3 を 1 call 噛ませると **1 turn** で同等の文脈が手に入ります。

## 1 call workflow

```jsonc
// MCP request (Claude Desktop / Smithery / Cline などの client から)
{
  "tool": "agent_briefing_pack",
  "args": {
    "topic": "役員報酬の損金算入",
    "target_segment": "税理士",
    "output_format": "claude_xml",
    "token_budget": 8000
  }
}
```

レスポンス (抜粋):

```xml
<briefing topic="役員報酬の損金算入" segment="税理士">
  <context>
対象トピック: 役員報酬の損金算入
対象セグメント: 税理士
depth_level: 3 / 5
適用業法: 税理士法 §52・§1 行政書士法・§3 司法書士法
本 briefing pack は agent context window への 1-shot 注入を目的に組成しています。
確定判断は士業へ、primary source 確認必須。
  </context>
  <current_law>
[法人税法 第34条] 内国法人がその役員に対して支給する給与の額のうち...
  </current_law>
  <tsutatsu>
[法人税基本通達 9-2-12] 定期同額給与に該当するものとして取り扱う給与...
  </tsutatsu>
  <judgment_summary>
[東京高裁 2018-XX-XX] 形式的に定期同額給与の要件を満たさない場合でも...
  </judgment_summary>
  <practical_guidance>
(0.78) 定期同額給与 vs 事前確定届出給与: ...
  </practical_guidance>
  <common_pitfalls>
- 通達のみで判断し法令本文を確認しない (topic: 役員報酬の損金算入)
- 改正前後の effective_from を確認せず stale な解釈を流用する
- 判例の射程外まで類推適用する
- 顧客側資料の一次根拠を取らず agent 出力を完結扱いする
- 署名前に税理士法 §52 / §47条の2 の範囲外業務に踏み込む
  </common_pitfalls>
  <next_step_recommendations>
1. jpcite `get_law_article_am` で 役員報酬の損金算入 の関連条文 verbatim を取得
2. jpcite `walk_reasoning_chain` で 三段論法 chain を取得し confidence > 0.6 を採用
3. jpcite `search_acceptance_stats_am` で類似ケースの採択統計を確認
4. jpcite `get_artifact_template` で N1 成果物テンプレートを取得
5. jpcite `list_recipes` で対応する N8 recipe を辿る
6. 顧問先 client_profile に紐付け saved_search を登録
  </next_step_recommendations>
  <applicable_templates>
- 月次顧問業務 報告書 (monthly_review, grade=A)
- 期末税務処理 メモ (year_end_memo, grade=A)
  </applicable_templates>
  <related_filing_windows>
(関連 filing windows は 補助金 / 助成金 系で出る — 役員報酬単体では 0 件)
  </related_filing_windows>
  <disclaimer_envelope>
本 response は moat lane の retrieval / モデル推論結果で、...
税理士法 §52 / §1 行政書士法 / §3 司法書士法
本 pack は agent context injection 用の retrieval 集約で、士業独占業務 / 法的助言 / 税務代理を構成しません。
  </disclaimer_envelope>
</briefing>
```

これを agent system prompt に inject すれば、税理士 agent は **以後の turn で
再質問せず** 顧客向け説明 draft を 1 turn で組み立てられます。

## 出力フォーマットの選び方

| format | 想定 client | 主な用途 |
| --- | --- | --- |
| `claude_xml` | Claude Desktop / Cline / 自作 Claude 経由 agent | system prompt 末尾に `<briefing>` を直接埋める |
| `openai_json` | OpenAI Assistants / function-calling pipeline | `sections[].content` を `tool_result` として返す |
| `markdown_doc` | Slack / 顧問先共有 / mkdocs 取込 | 人間が読む / レビューする |

## token_budget と depth_level

```
budget 500-1500   → depth 1 (verbatim 法令 2-3 article、判例 3、その他要約)
budget 1501-3500  → depth 2
budget 3501-8000  → depth 3 (default)
budget 8001-14000 → depth 4 (Wave 51 dim Q / dim O ステップを追加)
budget 14001-30000→ depth 5 (maximum)
```

`token_count_estimated` は (tiktoken なしの) 軽量 OSS 推定値です。
ASCII は 4 chars/token、CJK は 1.5 chars/token を blend した cl100k 互換ヒューリ
スティック (実測 ±20% 以内)。

## コスト圧縮の試算

|  | HE-3 未使用 | HE-3 1 call inject |
| --- | --- | --- |
| turn 数 | 3-5 | 1-2 |
| 1 turn の prompt | ~5,000 token | ~13,000 token (briefing 8K + 入力 5K) |
| 1 turn の completion | ~1,500 token | ~1,500 token |
| 1 turn の Claude Opus コスト | $0.0625 | $0.1025 |
| 合計 (3-5 vs 1-2) | $0.1875 - $0.3125 | $0.1025 - $0.2050 |
| 削減率 | -- | **~45-65%** |

`docs/_internal/MOAT_HE3_BRIEFING_PACK_2026_05_17.md` に詳細モデル。

## 5 segment 出力差分

`target_segment` を変えると `disclaimer_envelope` セクションの **業法 footer** と
`common_pitfalls` の最終行 (segment-specific) が切り替わります:

- `税理士` → 税理士法 §52 / §1 行政書士法 / §3 司法書士法
- `会計士` → 公認会計士法 §47条の2 / 税理士法 §52
- `中小経営者` → 税理士法 §52 / 弁護士法 §72
- `AX_engineer` → Anthropic Acceptable Use Policy
- `FDE` → Anthropic Acceptable Use Policy / 顧客 SOW

## 関連

- HE-1 `evidence_packet`: 評議用 evidence の 1-shot 集約 (sister tool, lane HE-1)。
- HE-2 `audit_workpaper`: 監査調書の 1-shot 集約 (sister tool, lane HE-2)。
- HE-4 `orchestrate`: 複数 tool の bundle 実行 (sister tool, lane HE-4)。
- 一次資料は `agent_briefing_pack` レスポンスの `structured_payload`
  (`current_law.source_url` / `judgment_summary.source_url` 等) を辿ってください。
