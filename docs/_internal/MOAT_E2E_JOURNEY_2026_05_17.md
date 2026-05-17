# Moat E2E user-journey audit — D4 (2026-05-17)

Design audit D4 simulates 5 士業 segment user journeys end-to-end across
the jpcite MCP surface. Each journey starts from an agent (Opus 4.7
behaviour profile) requesting an artifact and ends with a fully
rendered, professional-reviewable scaffold. The simulation runs as a
deterministic pytest suite at:

- `tests/e2e/_journey_fixtures.py` — shared DB seeder + JourneyAgent.
- `tests/e2e/test_user_journey_zeirishi.py`
- `tests/e2e/test_user_journey_kaikeishi.py`
- `tests/e2e/test_user_journey_gyouseishoshi.py`
- `tests/e2e/test_user_journey_shihoshoshi.py`
- `tests/e2e/test_user_journey_sharoushi.py`

Constraints honoured: NO LLM call, NO network I/O, mypy strict 0, ruff 0,
NO existing-lane modification (test-only landing).

> Default-skip note: tests live under `tests/e2e/` so pytest's e2e
> conftest auto-skips them unless `--run-e2e` or `JPINTEL_E2E=1` is
> set. This matches the existing Playwright-suite convention; the
> simulation is deliberately opt-in so it does not extend the hot
> local-loop wall clock.

## 1. Scenario flowcharts

### Scenario 1 — 税理士 月次決算

```
agent → list_artifact_templates("税理士")
      → get_artifact_template("税理士", "gessji_shiwake")
      → resolve_placeholder("{{COMPANY_NAME}}")
      → get_houjin_360_am(field=name)
      → [render scaffold] → 4 MCP calls × ¥3 = ¥12
```

Session-source placeholders (HOUJIN_BANGOU / TARGET_MONTH /
PREPARER_NAME / ZEIRISHI_NAME) cost 0 MCP calls.

### Scenario 2 — 会計士 監査調書

```
agent → get_houjin_portfolio(houjin_bangou)
      → get_artifact_template("会計士", "kansa_chosho")
      → walk_reasoning_chain(query="監査調書", category="corporate_tax")
      → resolve_placeholder("{{COMPANY_NAME}}")
      → get_houjin_360_am(field=name)
      → [render scaffold] → 5 MCP calls × ¥3 = ¥15
```

### Scenario 3 — 行政書士 補助金申請

```
agent → list_artifact_templates("行政書士")
      → get_artifact_template("行政書士", "hojokin_shinsei")
      → find_filing_window("prefecture", houjin_bangou)
      → resolve_placeholder × 3 (COMPANY_NAME / ADDRESS / REPRESENTATIVE)
      → get_houjin_360_am × 3
      → [render scaffold] → 9 MCP calls × ¥3 = ¥27
```

### Scenario 4 — 司法書士 会社設立登記

```
agent → find_filing_window("legal_affairs_bureau", houjin_bangou)
      → get_artifact_template("司法書士", "kaisha_setsuritsu_touki")
      → resolve_placeholder("{{COMPANY_NAME}}")
      → [render scaffold] → 3 MCP calls × ¥3 = ¥9
```

### Scenario 5 — 社労士 就業規則

```
agent → get_artifact_template("社労士", "shuugyou_kisoku")
      → resolve_placeholder × 2 (COMPANY_NAME / ADDRESS)
      → get_houjin_360_am × 2
      → [render scaffold] → 5 MCP calls × ¥3 = ¥15
```

## 2. MCP call + expected output schema

| Step | Tool | Args | Expected envelope key | Notes |
| --- | --- | --- | --- | --- |
| listing | `list_artifact_templates` | `{segment, limit}` | `results[].artifact_type` | catalog |
| fetch | `get_artifact_template` | `{segment, artifact_type}` | `primary_result.structure / placeholders` | scaffold |
| portfolio | `get_houjin_portfolio` | `{houjin_bangou}` | `results[]` (rank ASC) | gap analysis |
| reasoning | `walk_reasoning_chain` | `{query, category}` | `results[]` or `primary_result` | deterministic chain |
| window | `find_filing_window` | `{program_id, houjin_bangou}` | `results[]` (5 max) | 法務局/税務署 prefix match |
| placeholder | `resolve_placeholder` | `{placeholder_name, context_dict_json}` | `primary_result.args_substituted / mcp_tool_name` | substitution complete flag |
| value | `get_houjin_360_am` | `{houjin_bangou, field}` | `<field>` | name / address / representative |

Every envelope carries `_disclaimer` (§52 / §47条の2 / §72 / §1 / §3 /
社労士法 / 行政書士法) and `_billing_unit=1` per call (¥3 metered).

## 3. Test pass/fail status (this audit)

| Scenario | Test | Status | MCP calls | Cost |
| --- | --- | --- | --- | --- |
| 1. 税理士 月次決算 | `test_user_journey_zeirishi.py` | PASS | 4 | ¥12 |
| 2. 会計士 監査調書 | `test_user_journey_kaikeishi.py` | PASS | 5 | ¥15 |
| 3. 行政書士 補助金申請 | `test_user_journey_gyouseishoshi.py` | PASS | 9 | ¥27 |
| 4. 司法書士 会社設立登記 | `test_user_journey_shihoshoshi.py` | PASS | 3 | ¥9 |
| 5. 社労士 就業規則 | `test_user_journey_sharoushi.py` | PASS | 5 | ¥15 |
| **Total** | — | 5/5 PASS | 26 | **¥78** |

Average per artifact = 5.2 MCP calls / ¥15.6 — under the ¥300-¥900
outcome-justifiable-cost band (Wave 50 RC1 contract layer).

## 4. Integration gap matrix

| # | Gap | Severity | Location | Mitigation in this audit |
| --- | --- | --- | --- | --- |
| G1 | `search_chunks` (Moat M9) returns PENDING envelope — no real chunk corpus surfaced | medium | `src/jpintel_mcp/mcp/moat_lane_tools/moat_m9_chunks.py` | 行政書士 journey substitutes `find_filing_window` (Moat N4) for the 申請窓口 section so the scaffold remains usable until M9 lands. |
| G2 | `get_law_article_am` is required for 社労士 §89 placeholder but the production tool surface is broader than the e2e fixture seeds | low | `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py` | 社労士 journey uses a 一次URL pointer (`elaws.e-gov.go.jp/.../§89`) so the LEGAL_BASIS placeholder resolves honestly even when the gated 36協定 surface is OFF. |
| G3 | `am_placeholder_mapping` migration not yet applied to live `autonomath.db` (verified 2026-05-17 — table absent) | medium | `scripts/migrations/wave24_206_*` (planned) | Journey fixtures seed the schema in-test; live deployment will require the migration before the production agent can route `resolve_placeholder` through canonical N9. Track under the upcoming wave24_206 follow-up. |
| G4 | `find_filing_window` regex match relies on `am_entities.corp.registered_address` — synthetic 法人 in the fixture matches a single 文京区 window, real 法人 may straddle multiple windows | low | `src/jpintel_mcp/mcp/moat_lane_tools/moat_n4_window.py` | All 5 scaffolds carry the canonical §-aware disclaimer + `requires_professional_review=1` so the operator confirms 管轄 manually. |
| G5 | `walk_reasoning_chain` chain coverage is 160 topics × 5 viewpoint slices = 800 chains — 会計士 監査調書 trail uses topic_id `corporate_tax:kansa_chosho` which is not in the production seed (verified 2026-05-17 against `am_legal_reasoning_chain`) | medium | `scripts/build_reasoning_chains_*` (planned) | The 会計士 journey assertion only requires the envelope shape, not chain content — production rollout needs a 会計士 監査基準 topic_id to be seeded before agents can rely on the trail. |
| G6 | MCP tool name collision risk: `get_houjin_360_am` (autonomath_tools) vs `get_houjin_360` (api/houjin_360.py REST) — the journey fixtures use the `_am` suffix consistently | informational | `src/jpintel_mcp/api/houjin_360.py` + `mcp/autonomath_tools/corporate_layer_tools.py` | No mitigation needed in fixtures; the placeholder mapper canonically writes `get_houjin_360_am` (with suffix) so collisions cannot occur during agent dispatch. |

5 distinct integration gaps identified (G1 medium, G2 low, G3 medium, G4
low, G5 medium, G6 informational). Mitigation for each is in place at
the journey-simulation level; production rollout depends on G3 + G5
seed work landing alongside the next moat-lane wave.

## 5. Provenance + reproducibility

- Test invocation: `JPINTEL_E2E=1 .venv/bin/pytest tests/e2e/test_user_journey_*.py -v`
- 5/5 PASS, 0.97s wall clock on the audit run.
- mypy --strict on the 6 new files: **0 errors**.
- ruff check on the 6 new files: **0 errors**.
- No production lane modified; landing is test-only per D4 constraint.
- Co-Authored-By: Claude Opus 4.7

last_updated: 2026-05-17
