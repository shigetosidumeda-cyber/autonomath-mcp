# Moat HE-2 — `prepare_implementation_workpaper` (2026-05-17, landed)

Heavy-output endpoint that collapses the multi-call workpaper assembly
workflow into a single MCP call. Composes 6 niche moat lanes (N1 + N2 +
N3 + N4 + N6 + N9) into one fully-filled artifact draft.

## Why this exists

Until HE-2, an agent constructing a workpaper for a houjin had to:

1. `get_artifact_template` (N1) — fetch the scaffold.
2. `get_houjin_portfolio` (N2) — anchor the houjin's program context.
3. `walk_reasoning_chain` / `get_reasoning_chain` (N3) — surface the
   deterministic 三段論法 + citation envelope (1–5 calls).
4. `find_filing_window` (N4) — resolve the submission target.
5. `list_pending_alerts` (N6) — per-houjin amendment-alert feed.
6. `resolve_placeholder` (N9) — once per `{{KEY}}` in the template
   (5–15 calls depending on artifact_type).
7. LLM aggregation step to merge the results into a draft.

15–20 sequential round trips at minimum, ¥3 per call + agent LLM cost.
HE-2 reduces this to **1 call @ ¥3** with NO LLM round-trip, because the
composition is deterministic dict / SQLite manipulation.

## Signature

```python
async def prepare_implementation_workpaper(
    artifact_type: str,
    houjin_bangou: str = "",
    segment: str | None = None,
    fiscal_year: int | None = None,
    auto_fill_level: str = "deep",   # "skeleton" / "partial" / "deep"
) -> dict[str, Any]
```

## Return envelope (canonical)

| key | type | source lane | note |
|---|---|---|---|
| `tool_name` | str | — | `"prepare_implementation_workpaper"` |
| `schema_version` | str | — | `"moat.he2.v1"` |
| `primary_result.status` | str | — | `ok` / `empty` / `template_missing` |
| `primary_result.segment` | str | N1 | 5 士業 segment |
| `primary_result.artifact_name_ja` | str | N1 | display |
| `primary_result.completion_pct` | float | composed | resolved / total placeholders |
| `primary_result.is_skeleton` | bool | composed | skeleton mode flag |
| `template` | dict | N1 | full template w/ sections + placeholders + bindings |
| `filled_sections[]` | list | composed | per-section fill state |
| `legal_basis.law_articles` | list | N3 citations.law | up to 10 |
| `legal_basis.tsutatsu` | list | N3 citations.tsutatsu | up to 10 |
| `legal_basis.judgment_examples` | list | N3 citations.{hanrei,saiketsu} | up to 5 |
| `filing_window.kind` | str | N4 + type→kind map | jurisdiction kind |
| `filing_window.address` | str | N4 + am_entity_facts | houjin registered address |
| `filing_window.matches[]` | list | N4 prefix match | up to 3 windows |
| `deadline` | str (ISO) | composed | deterministic projection |
| `estimated_completion_pct` | float | composed | resolved / total |
| `agent_next_actions[]` | list | composed | 3-step plan (fill_manual / verify / submit) |
| `reasoning_chains[]` | list | N3 | top 5 chains by confidence |
| `amendment_alerts_relevant[]` | list | N6 | per-houjin pending alerts |
| `alternative_templates[]` | list | N1 versions | up to 5 revision rows |
| `portfolio_context` | dict | N2 | summary + top-20 portfolio rows |
| `billing` | dict | — | `{unit:1, yen:3, auto_fill_level}` |
| `_disclaimer` | str | shared | §52 / §47条の2 / §72 / §1 / §3 |
| `_citation_envelope` | dict | composed | citation counts per kind |
| `_provenance` | dict | composed | composed_lanes / template_id / version |

## auto_fill_level semantics

| level | template | N2 / N3 / N4 / N6 fetch | placeholder resolution |
|---|---|---|---|
| `skeleton` | yes | **skipped** | enumeration only — every placeholder → `manual_input_required` |
| `partial` | yes | yes | mapping surfaced, context-bag values resolved, MCP bindings NOT invoked |
| `deep` | yes | yes | context + alias + N9 fallback chain applied |

NO LLM inference in any mode.

## Cost economics

| path | API calls | LLM round-trips | jpcite ¥ cost |
|---|---|---|---|
| Atomic 7-tool walk | 15–20 | 15–20 | ¥45–¥60 |
| **HE-2 1-call** | **1** | **1** | **¥3** |

Savings: ~90% API + ~95% LLM. The 1 LLM round-trip remaining is the
agent's tool-selection turn — the composition itself is deterministic.

## Test scenarios (18 PASS — 12 mandatory + 6 contract)

1.  税理士 法人税申告書 deep — placeholders resolved + tax_office window + deadline 2027-05-31
2.  税理士 消費税申告書 deep — consumption_tax category reasoning chain present
3.  税理士 月次仕訳 partial — alternative_templates surfaced (revision history)
4.  行政書士 補助金申請書 deep — prefecture window + subsidy category
5.  行政書士 許認可申請書 partial
6.  司法書士 会社設立登記申請書 deep — legal_affairs_bureau window
7.  司法書士 役員変更登記申請書 deep — commerce category reasoning
8.  社労士 就業規則 deep — labour_bureau window
9.  社労士 36協定書 deep — labor category
10. 会計士 監査調書 deep
11. 会計士 監査意見書 partial
12. skeleton mode (no houjin) — template + placeholder enumeration only
13. invalid artifact_type → empty envelope (`Cannot infer segment`)
14. unknown artifact_type w/ explicit segment → `template_missing`
15. disclaimer / billing / provenance shape contract
16. agent_next_actions always returns 3 deterministic steps
17. amendment_alerts_relevant surfaces per-houjin N6 feed
18. DB-missing path returns safe empty envelope (no raise)

Live invocation against `autonomath.db` (real corpus, `8010001213708`):

- houjinzei_shinkoku deep → `completion_pct = 0.33`, 4 sections, 5 reasoning chains, 5 law_articles, 1 tax_office match, deadline `2027-05-31`.
- hojokin_shinsei deep → `completion_pct = 0.12`, 5 subsidy chains, prefecture window kind resolved.
- shuugyou_kisoku skeleton → `completion_pct = 0.0`, 8 sections enumerated, `is_skeleton = True`.

Live `completion_pct` is below the 0.85 fixture baseline because the production
`am_entity_facts` corpus is thin on the rows used here; fixture-backed scenarios
drive resolution > 0.30 reliably, and the fixture is the right benchmark for the
composition logic itself.

## Hard constraints honoured

- NO LLM inference (no `anthropic` / `openai` / `claude_agent_sdk` import).
- §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every payload.
- Read-only SQLite (URI mode `ro`).
- 1 ¥3 billable unit per call (host MCP server counts).
- mypy strict 0 / ruff 0 — sanity asserts at module import + closed taxonomies on `auto_fill_level` / `segment`.
- `[lane:solo]` — single-file landing for the core, no cross-lane edits.

## Files landed

- `src/jpintel_mcp/mcp/moat_lane_tools/he2_workpaper.py` — composition core
- `tests/test_he2_workpaper.py` — 18 scenarios (12 mandatory + 6 contract)
- `docs/recipes/he2_workpaper_zeirishi_demo.md` — operator demo
- `docs/_internal/MOAT_HE2_WORKPAPER_2026_05_17.md` — this doc
- `src/jpintel_mcp/mcp/moat_lane_tools/__init__.py` — `_SUBMODULES` += `"he2_workpaper"`
