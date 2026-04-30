# OTHER CLI Max-Agent Research Loop 20260430

Use the maximum safe number of agents. Assign one work order per agent.
This is research-only. Do not edit production code or deployment files.

## Hard Constraints

- Do not call any LLM API or hosted model API. Use regex, rules, difflib, sqlite, pdfplumber, csv/json tooling only.
- Do not use aggregator sites as evidence: noukaweb, hojyokin-portal, biz.stayway, or similar portals are discovery hints only.
- Respect robots.txt, crawl-delay, rate limits, and public-source terms.
- Do not propose tier SKUs, subscription tiers, or changes to the ¥3/request metered model.
- Do not write to src/, scripts/, .github/, docs/_internal/, fly.toml, server.json, smithery.yaml, or deployment files.
- Write job definitions and run logs only under research/loops/.
- Write research outputs only to analysis_wave18/, data/snapshots/, or data/structured_facts/.
- Do not estimate work-hours or calendar schedules. Return evidence and next concrete questions only.

## Expected Final Deliverables

- `analysis_wave18/am_diff_design_2026-04-30.md`
- `analysis_wave18/consultant_firms_2026-04-30.csv`
- `analysis_wave18/pdf_extraction_research_2026-04-30.md`
- `analysis_wave18/url_liveness_2026-04-30.json`

## Work Orders

- Agent 01: `research/loops/runs/20260430/work_orders/01_url_liveness_shard01.md` -> url_liveness shard 01
- Agent 02: `research/loops/runs/20260430/work_orders/02_consultant_firms_shard01.md` -> consultant_firms shard 01
- Agent 03: `research/loops/runs/20260430/work_orders/03_pdf_structure_shard01.md` -> pdf_structure shard 01
- Agent 04: `research/loops/runs/20260430/work_orders/04_am_diff_design_shard01.md` -> am_diff_design shard 01
- Agent 05: `research/loops/runs/20260430/work_orders/05_url_liveness_shard02.md` -> url_liveness shard 02
- Agent 06: `research/loops/runs/20260430/work_orders/06_consultant_firms_shard02.md` -> consultant_firms shard 02
- Agent 07: `research/loops/runs/20260430/work_orders/07_pdf_structure_shard02.md` -> pdf_structure shard 02
- Agent 08: `research/loops/runs/20260430/work_orders/08_am_diff_design_shard02.md` -> am_diff_design shard 02
- Agent 09: `research/loops/runs/20260430/work_orders/09_url_liveness_shard03.md` -> url_liveness shard 03
- Agent 10: `research/loops/runs/20260430/work_orders/10_consultant_firms_shard03.md` -> consultant_firms shard 03
- Agent 11: `research/loops/runs/20260430/work_orders/11_pdf_structure_shard03.md` -> pdf_structure shard 03
- Agent 12: `research/loops/runs/20260430/work_orders/12_am_diff_design_shard03.md` -> am_diff_design shard 03
- Agent 13: `research/loops/runs/20260430/work_orders/13_url_liveness_shard04.md` -> url_liveness shard 04
- Agent 14: `research/loops/runs/20260430/work_orders/14_consultant_firms_shard04.md` -> consultant_firms shard 04
- Agent 15: `research/loops/runs/20260430/work_orders/15_pdf_structure_shard04.md` -> pdf_structure shard 04
- Agent 16: `research/loops/runs/20260430/work_orders/16_am_diff_design_shard04.md` -> am_diff_design shard 04
- Agent 17: `research/loops/runs/20260430/work_orders/17_url_liveness_shard05.md` -> url_liveness shard 05
- Agent 18: `research/loops/runs/20260430/work_orders/18_consultant_firms_shard05.md` -> consultant_firms shard 05
- Agent 19: `research/loops/runs/20260430/work_orders/19_pdf_structure_shard05.md` -> pdf_structure shard 05
- Agent 20: `research/loops/runs/20260430/work_orders/20_am_diff_design_shard05.md` -> am_diff_design shard 05
- Agent 21: `research/loops/runs/20260430/work_orders/21_url_liveness_shard06.md` -> url_liveness shard 06
- Agent 22: `research/loops/runs/20260430/work_orders/22_consultant_firms_shard06.md` -> consultant_firms shard 06
- Agent 23: `research/loops/runs/20260430/work_orders/23_pdf_structure_shard06.md` -> pdf_structure shard 06
- Agent 24: `research/loops/runs/20260430/work_orders/24_am_diff_design_shard06.md` -> am_diff_design shard 06
- Agent 25: `research/loops/runs/20260430/work_orders/25_url_liveness_shard07.md` -> url_liveness shard 07
- Agent 26: `research/loops/runs/20260430/work_orders/26_consultant_firms_shard07.md` -> consultant_firms shard 07
- Agent 27: `research/loops/runs/20260430/work_orders/27_pdf_structure_shard07.md` -> pdf_structure shard 07
- Agent 28: `research/loops/runs/20260430/work_orders/28_am_diff_design_shard07.md` -> am_diff_design shard 07
- Agent 29: `research/loops/runs/20260430/work_orders/29_url_liveness_shard08.md` -> url_liveness shard 08
- Agent 30: `research/loops/runs/20260430/work_orders/30_consultant_firms_shard08.md` -> consultant_firms shard 08
- Agent 31: `research/loops/runs/20260430/work_orders/31_pdf_structure_shard08.md` -> pdf_structure shard 08
- Agent 32: `research/loops/runs/20260430/work_orders/32_am_diff_design_shard08.md` -> am_diff_design shard 08

## Close The Loop

After agents finish, run:

```bash
./.venv/bin/python research/loops/research_collection_loop.py review --run-id 20260430
```
