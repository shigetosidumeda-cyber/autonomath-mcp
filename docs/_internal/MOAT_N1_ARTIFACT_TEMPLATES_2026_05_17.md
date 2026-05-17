# Moat N1 — Artifact template bank (2026-05-17 LIVE)

Status: **LIVE** as of 2026-05-17.
Lane: N1 (士業 実務成果物テンプレート bank).
Constraint: scaffold-only, NO LLM, every response carries the §52 / §47条の2 /
§72 / §1 / §3 disclaimer envelope.

## Outcome

50 artifact template scaffolds (5 士業 × 10 種類) hydrated into
`am_artifact_templates` (autonomath.db, migration `wave24_200`) and exposed via 2
MCP tools so an agent (Opus 4.7 等) can fetch a template + placeholder bindings
in a single deterministic call instead of generating boilerplate via LLM. The
agent then fills the placeholders by walking the bound MCP tools (e.g.
`get_houjin_360_am`, `enum_values_am`, `search_certifications`, `get_law_article_am`).

## Catalog: 50 templates (5 segments × 10 each)

### 税理士 (税理士法 §52)
`gessji_shiwake` / `nenmatsu_chosei` / `houjinzei_shinkoku` / `shouhizei_shinkoku`
/ `gensen_choushuubo` / `kyuyo_keisan` / `shoukyaku_shisan_shinkoku` /
`inshi_zei_shinkoku` / `kifukin_koujo_shoumei` / `kaihaigyou_todoke`

### 会計士 (公認会計士法 §47条の2)
`kansa_chosho` / `naibu_tousei_houkoku` / `kansa_iken` / `tanaoroshi_hyouka` /
`taishoku_kyufu_keisan` / `lease_torihiki` / `kinyu_shouhin_hyouka` /
`renketsu_tetsuduki` / `segment_jouhou` / `kaikei_houshin_chuuki`

### 行政書士 (行政書士法 §1)
`hojokin_shinsei` / `kyoninka_shinsei` / `gyoumu_itaku_keiyaku` /
`gyoumu_teikei_keiyaku` / `naiyo_shoumei` / `eigyo_kyoka_shinsei` /
`kobutsu_shou_shinsei` / `kensetsu_kyoka_shinsei` / `sanpai_kyoka_shinsei` /
`nyukan_zairyu_shikaku`

### 司法書士 (司法書士法 §3)
`kaisha_setsuritsu_touki` / `yakuin_henko_touki` / `shougou_henko_touki` /
`honten_iten_touki` / `fudosan_baibai_touki` / `teitouken_settei_touki` /
`souzoku_touki` / `houjin_kaisan_touki` / `shougyo_touki_misc` /
`shurui_kabushiki_touki`

### 社労士 (社労士法 §27)
`shuugyou_kisoku` / `sanroku_kyoutei` / `koyou_keiyaku` / `chingin_kitei` /
`taishokukin_kitei` / `ikuji_kaigo_kyugyou` / `anzen_eisei_kitei` /
`kyuyo_kaitei_tsuchi` / `kaiko_yokoku_tsuchi` / `roudou_jouken_tsuchi`

## Schema

`am_artifact_templates` (target_db: autonomath, migration
`scripts/migrations/wave24_200_am_artifact_templates.sql`):

| column | type | notes |
| --- | --- | --- |
| `template_id` | INTEGER PK | autoincrement |
| `segment` | TEXT | 税理士 / 会計士 / 行政書士 / 司法書士 / 社労士 |
| `artifact_type` | TEXT | slug, e.g. `gessji_shiwake` |
| `artifact_name_ja` | TEXT | display name (e.g. `就業規則`) |
| `version` | TEXT | default `v1` |
| `authority` | TEXT | 根拠法令 (e.g. `労基法 §89`) |
| `sensitive_act` | TEXT | 規制業法 (e.g. `社労士法 §27`) |
| `is_scaffold_only` | INTEGER | always 1 |
| `requires_professional_review` | INTEGER | always 1 |
| `uses_llm` | INTEGER | always 0 |
| `quality_grade` | TEXT | default `draft` |
| `structure_jsonb` | TEXT | JSON: `{sections: [{id, title, paragraphs[]}]}` |
| `placeholders_jsonb` | TEXT | JSON: `[{key, type, required, source, mcp_query_spec}]` |
| `mcp_query_bindings_jsonb` | TEXT | JSON: `{placeholder_key: {tool, args}}` |
| `license` | TEXT | default `jpcite-scaffold-cc0` |
| `notes` | TEXT | disclaimer 文 |
| `updated_at` | TEXT | `datetime('now')` |

Indexes: `ix_am_artifact_templates_segment`, `ix_am_artifact_templates_type`,
`ix_am_artifact_templates_segment_type`. UNIQUE on
`(segment, artifact_type, version)`.

Convenience view: `v_am_artifact_templates_latest` (latest version per
`(segment, artifact_type)`).

## MCP tools (2)

Both gated by the lane N10 master `JPCITE_MOAT_LANES_ENABLED` (default ON).

### `get_artifact_template(segment, artifact_type)`

Fetch the latest version of one scaffold by `segment` + `artifact_type`. Returns:

```
{
  "tool_name": "get_artifact_template",
  "schema_version": "moat.n1.v1",
  "primary_result": {
    "template_id": int, "segment": str, "artifact_type": str,
    "artifact_name_ja": str, "version": str, "authority": str,
    "sensitive_act": str, "is_scaffold_only": bool,
    "requires_professional_review": bool, "uses_llm": bool,
    "quality_grade": str,
    "structure": {"sections": [...]},
    "placeholders": [...],
    "mcp_query_bindings": {...},
    "license": str, "notes": str, "updated_at": str
  },
  "results": [<same as primary_result>],
  "total": 1, "limit": 1, "offset": 0,
  "citations": [
    {"kind": "authority", "text": "<根拠法令>"},
    {"kind": "sensitive_act", "text": "<規制業法>"}
  ],
  "provenance": {"source_module": "jpintel_mcp.moat.n1_artifact",
                  "lane_id": "N1", "wrap_kind": "moat_lane_n1_artifact_db",
                  "observed_at": "<UTC ISO-8601>", "row_count": 1},
  "_billing_unit": 1,
  "_disclaimer": "<canonical 5-act disclaimer>"
}
```

Unknown `(segment, artifact_type)` → empty envelope (not raise).
`segment="all"` → empty envelope (use `list_artifact_templates`).

### `list_artifact_templates(segment="all", limit=50)`

Enumerate template summaries. Filter by 士業 segment or pass `"all"` for the
full catalog. Returns lightweight rows (no `structure` / `placeholders` /
`mcp_query_bindings` to keep payload small — fetch those via
`get_artifact_template`).

## Files

- Templates SOT: `data/artifact_templates/{segment}/{artifact_type}.yaml`
  (50 files; JSON-as-YAML so `json.loads` round-trips).
- Migration: `scripts/migrations/wave24_200_am_artifact_templates.sql`
  + `scripts/migrations/wave24_200_am_artifact_templates_rollback.sql`.
- Bulk loader: `scripts/cron/load_artifact_templates_2026_05_17.py`
  (idempotent INSERT OR REPLACE, run on boot or as cron).
- MCP tools: `src/jpintel_mcp/mcp/moat_lane_tools/moat_n1_artifact.py`
  (2 tools, real DB-backed, 12 tests).
- Tests: `tests/test_moat_n1_artifact.py` (12 tests PASS, isolated fixture DB,
  no live autonomath.db dependency).

## Quality gates

- mypy strict: 0 errors on the new module.
- ruff: 0 errors on the new module + new test file.
- pytest: 12/12 PASS on `tests/test_moat_n1_artifact.py`.
- Bulk load smoke: 50 rows loaded into autonomath.db on 2026-05-17 via
  `python3 scripts/cron/load_artifact_templates_2026_05_17.py`.

## Honest gaps

- The 50 scaffolds are intentionally minimal (header / body / footer sections;
  3-5 placeholders per template). The structural contract is what matters for
  the agent-side compose loop — the section text is meant to be replaced /
  reviewed by a 士業 before submission.
- Each placeholder declares `mcp_query_spec` so an agent can mechanically
  resolve `{{COMPANY_NAME}}` via `get_houjin_360_am`, but the binding is a
  suggestion, not a requirement — the agent or operator can override per call.
- `quality_grade` is `draft` for all 50 rows. Promotion to `reviewed` requires
  human 士業 sign-off; promotion to `certified` requires the operator to bind a
  named professional reviewer (out of scope for the bank itself).
- This is **not** a 申請書面 generator. The output is a deterministic skeleton.
  行政書士法 §1 / 司法書士法 §3 / 税理士法 §52 / 公認会計士法 §47条の2 /
  社労士法 §27 fences are preserved by `is_scaffold_only=1` +
  `requires_professional_review=1` + the disclaimer envelope.

last_updated: 2026-05-17
