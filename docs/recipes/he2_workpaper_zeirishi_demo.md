# HE-2 Workpaper Demo — 税理士の月次決算 1 call

`prepare_implementation_workpaper` は 1 MCP call で N1 template + N2 portfolio +
N3 reasoning + N4 filing window + N6 alert + N9 placeholder の 6 lanes を内部
で合成し、~85% まで埋まった成果物 draft を返す HE-2 endpoint です。
従来 15–20 round trip + 集約 prompt で組み立てていた月次決算ワークペーパ
が、**¥3 / 1 call** で完成します (NO LLM、pure SQLite + dict composition)。

## 1 call で完成するワークフロー

```jsonc
{
  "tool": "prepare_implementation_workpaper",
  "arguments": {
    "artifact_type": "houjinzei_shinkoku",
    "houjin_bangou": "8010001213708",
    "segment": "税理士",
    "fiscal_year": 2026,
    "auto_fill_level": "deep"
  }
}
```

戻り envelope (代表 fields):

```jsonc
{
  "tool_name": "prepare_implementation_workpaper",
  "schema_version": "moat.he2.v1",
  "primary_result": {
    "status": "ok",
    "segment": "税理士",
    "artifact_name_ja": "法人税申告書",
    "completion_pct": 0.85,
    "is_skeleton": false
  },
  "artifact_type": "houjinzei_shinkoku",
  "template": { /* N1 raw template (structure / placeholders / bindings) */ },
  "filled_sections": [
    {
      "section_id": "cover",
      "section_name": "別表1",
      "content_filled": "Bookyou株式会社 / 法人番号 8010001213708 / 2026-04-01〜2027-03-31",
      "placeholders_resolved": ["COMPANY_NAME","HOUJIN_BANGOU","FISCAL_YEAR"],
      "unresolved_placeholders": [],
      "manual_input_required": []
    }
    /* 別表4 / 別表5 / 税額計算 sections ... */
  ],
  "legal_basis": {
    "law_articles": [ /* up to 10 法令条文 — N3 chain citations.law */ ],
    "tsutatsu": [ /* up to 10 通達 */ ],
    "judgment_examples": [ /* up to 5 hanrei / saiketsu */ ]
  },
  "filing_window": {
    "kind": "tax_office",
    "address": "東京都千代田区",
    "matches": [
      { "name": "麹町税務署", "tel": "03-...", "url": "https://www.nta.go.jp/...", "source_url": "..." }
    ]
  },
  "deadline": "2027-05-31",
  "estimated_completion_pct": 0.85,
  "agent_next_actions": [
    { "step": "fill manual_input", "items": ["TAXABLE_INCOME"], "rationale": "..." },
    { "step": "verify with 税理士",  "items": [], "rationale": "§52 disclaimer ..." },
    { "step": "submit to filing_window", "items": ["麹町税務署"], "via": "online" }
  ],
  "reasoning_chains": [ /* 5 N3 chains, tax_category=corporate_tax */ ],
  "amendment_alerts_relevant": [ /* N6 pending alerts for the houjin */ ],
  "alternative_templates": [ /* up to 5 revision rows */ ],
  "billing": { "unit": 1, "yen": 3, "auto_fill_level": "deep" },
  "_disclaimer": "...",
  "_citation_envelope": { "law_articles": 5, "tsutatsu": 2, "judgment_examples": 1 },
  "_provenance": { "lane_id": "HE-2", "composed_lanes": ["N1","N2","N3","N4","N6","N9"] }
}
```

## 完成率と次アクション

- `estimated_completion_pct` = テンプレート上の placeholder のうち
  自動で埋まった割合 (deep モードで概ね 0.80–0.95、ライブ DB の context
  鮮度に依存して 0.30–0.85 帯で出ます)。
- `agent_next_actions` は **3 step deterministic plan**:
  (1) `manual_input_required` を埋める / (2) §52 disclaimer に従い士業
  レビューを通す / (3) `filing_window.matches` の出力先へ提出。

## コスト比較

| 経路 | API call | LLM round-trip | jpcite ¥ コスト |
|---|---|---|---|
| 従来 (atomic 7-tool walk) | 15–20 | 15–20 | ¥45–¥60 |
| **HE-2 (1 call)** | **1** | **1** | **¥3** |

API 側 90%+ / LLM 側 95%+ の削減。HE-2 自身は NO LLM の deterministic
composition なので追加コスト無し。

## skeleton モード

`houjin_bangou` を空 + `auto_fill_level="skeleton"` で呼ぶと、houjin context
を引かずに template + placeholder 一覧 + window kind / deadline projection
のみを返します (¥3 / 1 call, 同 envelope)。クライアント binding 前の
"このテンプレート、ざっくり中身を見たい" に最適。

## 関連 lane

- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n1_artifact.py` — Artifact Template Bank
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n2_portfolio.py` — Houjin Portfolio
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n3_reasoning.py` — Legal Reasoning Chain
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n4_window.py` — Filing Window
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n6_alert.py` — Amendment Alert Impact
- `src/jpintel_mcp/mcp/moat_lane_tools/moat_n9_placeholder.py` — Placeholder Resolver
