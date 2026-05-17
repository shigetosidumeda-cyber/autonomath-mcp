# A4 — 就業規則生成 Pack

**Price**: ¥300 / req (= 100 metered units × ¥3)
**Tool**: `product_shuugyou_kisoku_pack(houjin_bangou, employee_count_band, industry=None, fiscal_year=None)`
**MCP envelope**: `_billing_unit = 100`, `_disclaimer` = §52 / §47条の2 / §72 / §1 / §3 + 社労士法 §27
**Composed lanes**: HE-2 (N1 + N2 + N3 + N4 + N6 + N9) × 4 artifact

## 何が出るのか

1 回の MCP 呼び出しで **法人番号 1 件分・社労士 4 artifact bundle** を返します。

| artifact slug | name_ja | authority | sensitive_act |
| --- | --- | --- | --- |
| `shuugyou_kisoku` | 就業規則 | 労基法 §89 | 社労士法 §27 |
| `sanroku_kyoutei` | 36 協定書 | 労基法 §36 | 社労士法 §27 |
| `koyou_keiyaku` | 雇用契約書 | 労基法 §15 | 社労士法 §27 |
| `roudou_jouken` | 労働条件通知書 | 労基法 §15 | 社労士法 §27 |

HE-2 (`prepare_implementation_workpaper`) を 4 並列に展開し、それぞれの artifact について N1 template の placeholders を context (houjin_bangou / FISCAL_YEAR / CURRENT_DATE) + fallback chain で deep fill、不足分は `manual_input_required` として 立てて返します。

## Sample output structure

```json
{
  "tool_name": "product_shuugyou_kisoku_pack",
  "product_id": "A4",
  "schema_version": "products.a4.v1",
  "primary_result": {
    "status": "ok",
    "houjin_bangou": "8010001213708",
    "industry_resolved": "製造業",
    "employee_count_band": "10-29",
    "obligation_label": "labeling_required_kisoku_89",
    "summary": {
      "artifact_count": 4,
      "completed_artifact_count": 4,
      "average_completion_pct": 0.85,
      "total_placeholders": 16,
      "resolved_placeholders": 14
    }
  },
  "bundle": [
    {
      "artifact_type": "shuugyou_kisoku",
      "artifact_name_ja": "就業規則",
      "status": "ok",
      "is_skeleton": false,
      "estimated_completion_pct": 0.85,
      "template": {
        "template_id": 1,
        "segment": "社労士",
        "artifact_type": "shuugyou_kisoku",
        "artifact_name_ja": "就業規則",
        "version": "v1",
        "authority": "労基法 §89",
        "sensitive_act": "社労士法 §27",
        "is_scaffold_only": true,
        "requires_professional_review": true,
        "uses_llm": false,
        "quality_grade": "draft",
        "license": "jpcite-scaffold-cc0"
      },
      "filled_sections": [
        {
          "section_id": "header",
          "section_name": "ヘッダ",
          "content_filled": "サンプル株式会社 / 法人番号 8010001213708 / 会計年度 2026",
          "placeholders_resolved": ["COMPANY_NAME", "HOUJIN_BANGOU", "FISCAL_YEAR"],
          "unresolved_placeholders": [],
          "manual_input_required": []
        },
        {
          "section_id": "body",
          "section_name": "本文",
          "content_filled": "代表者 代表取締役 殿",
          "placeholders_resolved": ["REPRESENTATIVE"],
          "unresolved_placeholders": [],
          "manual_input_required": []
        }
      ],
      "legal_basis": {
        "law_articles": [
          {
            "unified_id": "laws:roukihou:36",
            "source_url": "https://laws.e-gov.go.jp/law/322AC0000000049"
          }
        ],
        "tsutatsu": [],
        "judgment_examples": []
      },
      "filing_window": {
        "matches": [
          {
            "window_id": 1,
            "jurisdiction_kind": "labour_bureau",
            "name": "東京労働局",
            "postal_address": "東京都千代田区",
            "url": "https://example/04",
            "source_url": "https://mhlw.go.jp/04"
          }
        ],
        "kind": "labour_bureau",
        "address": "東京都千代田区"
      },
      "deadline": "2026-08-15",
      "agent_next_actions": [
        {"step": "fill manual_input", "items": []},
        {"step": "verify with 社労士", "items": []},
        {"step": "submit to filing_window", "items": ["東京労働局"], "via": "online"}
      ]
    },
    {
      "artifact_type": "sanroku_kyoutei",
      "artifact_name_ja": "36 協定書 (時間外労働・休日労働協定届)",
      "..."
    },
    {
      "artifact_type": "koyou_keiyaku",
      "artifact_name_ja": "雇用契約書",
      "..."
    },
    {
      "artifact_type": "roudou_jouken",
      "artifact_name_ja": "労働条件通知書",
      "..."
    }
  ],
  "aggregate": {
    "artifact_count": 4,
    "completed_artifact_count": 4,
    "total_placeholders": 16,
    "resolved_placeholders": 14,
    "average_completion_pct": 0.85,
    "statutory_fence": ["社労士法 §27"]
  },
  "industry": "製造業",
  "employee_count_band": "10-29",
  "agent_next_actions": [
    {"step": "fill manual_input across 4 artifacts", "items": ["shuugyou_kisoku", "sanroku_kyoutei", "koyou_keiyaku", "roudou_jouken"]},
    {"step": "verify 労基法 §89 obligation", "items": ["labeling_required_kisoku_89"]},
    {"step": "engage 社労士", "items": ["sanroku_kyoutei", "shuugyou_kisoku"]}
  ],
  "billing": {"unit": 100, "yen": 300, "product_id": "A4"},
  "_billing_unit": 100,
  "_disclaimer": "本 response は moat lane の retrieval ... §52 / §47条の2 / §72 / §1 / §3 ...\n本 pack は 労基法 §89 / §36 / §15 + 社労士法 §27 の業務範囲を含まず、scaffold-only ...",
  "_related_shihou": ["社労士"]
}
```

## 入力パラメータ

| param | type | default | meaning |
| --- | --- | --- | --- |
| `houjin_bangou` | `str (13桁)` | required | 13桁法人番号 |
| `employee_count_band` | `str` | `"10-29"` | 1-4 / 5-9 / 10-29 / 30-49 / 50-99 / 100-299 / 300-999 / 1000+ |
| `industry` | `str?` | `None` (=auto) | 省略時は N7 segment view (`am_segment_view.jsic_name_ja`) から `jsic_major` 経由で自動判定 |
| `fiscal_year` | `int?` | `None` | 36協定 (4/1 起算) deadline projection に渡される |

## 労基法 §89 obligation_label

| `employee_count_band` upper bound | `obligation_label` |
| --- | --- |
| ≥ 10 (含 1000+) | `labeling_required_kisoku_89` — **就業規則は義務** |
| 5-9 | `kisoku_proactive_recommendation` — 任意だが推奨 |
| 1-4 | `kisoku_optional` — 任意 |

## NO LLM 保証

- A4 は **HE-2 + 4 SQLite query** のみで構築されます。LLM SDK の import は CI guard `tests/test_no_llm_in_production.py` で 機械的に禁止されています。
- placeholder 解決は `am_placeholder_mapping` の決定的 `mcp_tool_name + fallback_value` ロジックです — LLM 推論はゼロ。

## 法律遵守 fence

| § | 対象 | A4 stance |
| --- | --- | --- |
| 社労士法 §27 | 労働社会保険関係手続代行・帳簿書類作成・労務管理コンサル | **scaffold-only**, 監修・提出は社労士が必要 |
| 労基法 §89 | 就業規則 作成・届出義務 (10 人以上) | 義務該当の roadmap を返すだけで届出代行は行いません |
| 労基法 §36 | 時間外労働 36協定 締結・届出 | 36協定書 scaffold を返すだけで 労使協定 + 届出 は別工程 |
| 労基法 §15 | 労働条件 明示義務 | 通知書 scaffold を返すだけで明示行為は雇用主が実施 |

最終的な 提出 / 労使協定 / 監修 は **社労士・雇用主の責任** で行われます。

## 内部設計 — composed lanes

```
HE-2 prepare_implementation_workpaper(segment="社労士", artifact_type=X, houjin_bangou, fiscal_year, auto_fill_level="deep")
  × 4 (asyncio.gather)
  → 各 artifact について N1 template + N2 portfolio + N3 reasoning (tax_category="labor")
                       + N4 filing_window (labour_bureau) + N6 alerts + N9 placeholder map
                       を 1 envelope に composition
  → 4 envelope を bundle に flatten
N7 (am_segment_view) — industry 自動判定 用 (`jsic_name_ja`)
```

## 料金マッピング

- 1 req = ¥300 (税抜) = ¥3.30 × 100 units (税込 ¥330)
- Stripe metered billing の `usage_events` には `tool="product_shuugyou_kisoku_pack"` + `unit=100` で記録されます。
- A3 と同じく anonymous quota の対象外 — paid API key 必須。

## エラーパス

| status | 意味 |
| --- | --- |
| `ok` | 通常の 4-artifact bundle |
| `invalid_argument` | `employee_count_band` が許容 enum 外 |
| `he2_failure` | 上流 HE-2 fan-out 中に例外 (defensive) |

`invalid_argument` でも `_billing_unit = 100` のまま — paid product 呼び出しの料金は kept (HE-2 の preflight 検証コストを反映)。
