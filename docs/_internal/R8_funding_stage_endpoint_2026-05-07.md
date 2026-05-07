# R8 — Funding stage matcher endpoint (POST /v1/programs/by_funding_stage + GET /v1/funding_stages/catalog)

| field | value |
|---|---|
| date | 2026-05-07 (JST) |
| operator | session_a — 梅田茂利 / Bookyou株式会社 |
| scope | new endpoint pair (REST × MCP) shipping 5-stage funding-stage program matcher |
| LLM calls | 0 (pure SQL + Python over jpintel.programs) |
| migration | none — pure read-only over existing `programs` table |
| billing | catalog FREE; matcher ¥3/req metered (anonymous tier shares 3/日 IP cap) |

---

## 1. Why

Customers asking "私 ステージ X (シード / アーリー / グロース / IPO / 事業承継) で 該当する制度はどれか?" had to do this manually by name-grepping `programs.primary_name`. The 43 `am_target_profile` rows + 5 `example_profiles` (Phase A absorption) carry size / age signals but no stage tag — Japanese 補助金/融資/税制 don't formally tag stages, so we ship a closed-enum fence + a heuristic ranking instead of inventing a new column.

Cohort revenue model (CLAUDE.md §"Cohort revenue model") names #5 補助金 consultant + #1 M&A + #3 会計士 explicitly. Stage matching feeds all three: consultants screen 顧問先 by stage; M&A targets 事業承継 制度; 会計士 matches early/growth-stage clients to ものづくり/IT 導入. Single endpoint covers the discovery axis they all need.

## 2. Surface

### 2.1 GET /v1/funding_stages/catalog (FREE)
Returns the 5 stage definitions + per-stage representative programs pulled live from `programs.primary_name` keyword fence. Constant data — never billed (mirrors `/v1/regions/search` posture). Response carries `_disclaimer` so the heuristic-ness of stage tagging is on the wire.

### 2.2 POST /v1/programs/by_funding_stage (¥3/req)
Body:
```jsonc
{
  "stage": "growth",                  // closed enum
  "annual_revenue_yen": 500000000,    // optional
  "employee_count": 50,               // optional
  "incorporation_year": 2018,         // optional
  "prefecture": "東京都",              // optional
  "limit": 20                         // 1..100
}
```

Response (envelope shape, search-mirror keys for client-LLM compat):
- `input` (echo + `age_years` derived)
- `stage_definition` (id / ja_label / description / age band / capital cap / revenue band / keywords_any / keywords_avoid)
- `matched_programs` (each row: unified_id, primary_name, tier, program_kind, amount_max_man_yen, source_url, prefecture, likelihood [0.1-1.0], score)
- `axes_applied` (which filters were honored)
- `summary` (total_matched, amount_max_man_yen_top)
- `total / limit / offset / results`
- `_disclaimer` (mandatory — heuristic flag)

Sort key: `amount_max_man_yen × likelihood` desc → tier S/A/B/C tiebreak → name asc.

## 3. 5-stage closed enum

| id | ja_label | age_max | capital_max | revenue band | core keywords_any | keywords_avoid |
|---|---|---|---|---|---|---|
| `seed` | シード (創業前後) | 3y | ¥30M | 〜¥50M | 創業/起業/スタートアップ/新創業/シード/アクセラレータ | 事業承継/M&A/上場/IPO |
| `early` | アーリー (3〜5y) | 7y | ¥100M | ¥10M-¥500M | ものづくり/IT導入/事業再構築/ディープテック/成長加速 | 事業承継/M&A/上場/IPO/創業前 |
| `growth` | グロース (5〜10y) | — | ¥300M | ¥100M-¥5B | 成長/海外展開/輸出/設備投資/中堅/DX/GX/省エネ/サプライチェーン | 創業/事業承継/M&A/廃業 |
| `ipo` | IPO (上場準備) | — | — | ¥500M〜 | 上場/IPO/J-Startup/グローバル/ベンチャー/研究開発税制 | 創業前/創業/廃業 |
| `succession` | 事業承継/M&A | — | — | — | 事業承継/M&A/廃業/再チャレンジ/後継者/経営継承 | 創業/起業/新創業 |

Honest gap: 日本の制度は「IPO 専用」が薄い → ipo stage は J-Startup / 研究開発税制 / 中堅企業施策 を集めた coarse band。ipo description にこの honesty を書いた。

## 4. Files shipped

| path | purpose |
|---|---|
| `src/jpintel_mcp/api/funding_stage.py` | REST router (catalog GET + matcher POST) + 5-stage SOT (`_STAGES` / `_STAGE_BY_ID`) + matcher impl |
| `src/jpintel_mcp/mcp/autonomath_tools/funding_stage_tools.py` | MCP tool `match_programs_by_funding_stage_am` (reuses REST module's stage SOT — no duplication) |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | + 1 import line registering `funding_stage_tools` |
| `src/jpintel_mcp/api/main.py` | + 1 import + 1 `app.include_router(funding_stage_router, dependencies=[AnonIpLimitDep])` mount |
| `tests/test_funding_stage.py` | 20 tests (unit + impl + REST), all passing |
| `docs/openapi/v1.json` | regenerated; 218 paths total (was 216) |

## 5. Verification

| check | result |
|---|---|
| `.venv/bin/pytest tests/test_funding_stage.py -q` | **20 passed** |
| `.venv/bin/pytest tests/test_funding_stage.py tests/test_funding_stack_checker.py tests/test_case_cohort_match.py -q` | **64 passed** (siblings unaffected) |
| `.venv/bin/ruff check` (new files) | **All checks passed** |
| `.venv/bin/ruff format` (new files) | clean |
| `.venv/bin/mypy --config-file pyproject.toml` (new files) | **Success: no issues found in 2 source files** |
| `.venv/bin/pytest tests/test_no_llm_in_production.py -q` | **3 passed** (no LLM imports introduced) |
| `len(await mcp.list_tools())` (default gates) | 136 → +1 = 137 (verified `match_programs_by_funding_stage_am` present) |
| `docs/openapi/v1.json` regen | 218 paths (2 preview), `by_funding_stage` + `funding_stages/catalog` present |

## 6. Honest design choices

- **No new migration.** Stage SOT lives in Python (`_STAGES`). Adding a column would force every existing `programs` row to carry a stage tag → cleanup and back-fill burden for zero new value (heuristic anyway).
- **Avoid-keyword fence is a hard drop, not a soft penalty.** `seed × 事業承継` is too contradictory to allow even at low score — a row matching both `創業` and `事業承継` is almost always a false-positive (test fixture has `STG-NOISE-001` exercising this).
- **Age / revenue / capital bands are ranking-only inputs.** They don't hard-exclude rows because most jpintel programs don't carry full eligibility data — using them as filters would silently zero the result list. This honesty is reflected in `axes_applied` so the client LLM knows which axis was actually applied.
- **No keyword fence on aliases_json or enriched_json.** FTS5 trigram tokenizer's single-kanji false-positive (CLAUDE.md gotcha §1) makes name-only OR ladder safer than full-text match. The catalog `representative_program_keys` is intentionally short (5 keys per stage) so the GET path stays fast.

## 7. Compounding hooks (`_next_calls`)

Every matcher response carries `_next_calls` so a customer LLM agent can compose deeper:
1. `check_funding_stack_am` with the top-3 matched program_ids (1 call → C(3,2) = 3 pair = ¥9 = 併用可否 verdict).
2. `case_cohort_match_am` with the same prefecture (1 call → 同 stage 同地域 採択事例 補強).

Density model: 1 stage call surfaces ~20 programs, 2 follow-ups land within the same agent turn. Per the cohort revenue model this is the "compound multiplier" pattern Wave 22 tools already use.

## 8. NOT in scope (intentionally deferred)

- Manifest bump (139 → 140). CLAUDE.md "Wave hardening 2026-05-07" says **"Do not bump manifest tool_count without intentional release."** This new tool registers at runtime (`len(await mcp.list_tools())` reflects it) but stays at the manifest-hold cohort until the next intentional bump. No `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json` edits.
- DB column / migration. Stage tag stays in Python.
- Site copy / `site/audiences/*.html`. Catalog endpoint is enough for the agent surface; landing pages can come later in a content batch.
- Stage by JSIC (`am_industry_jsic`) cross-axis. Adding a JSIC-stage matrix would need a real corpus signal — current cohort has no labeled training data, so we'd be inventing.

## 9. Git posture

- Files are untracked at HEAD; commit happens after this audit doc + caller approval. Commit msg will tag `[lane:session_a]` per the lane policy enforcer (CLAUDE.md "lane policy").
- No `--no-verify`, no `--no-gpg-sign`. Pre-commit pre-existing failures (`site/facts.html` manifest drift + `auth_github.py` / `invoice_risk.py` mypy) belong to other concurrent agents' WIP, not this change.

---

End of R8_FUNDING_STAGE_ENDPOINT_2026-05-07.md.
