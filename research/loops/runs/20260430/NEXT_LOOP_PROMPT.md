# NEXT LOOP after 20260430

Use the same OTHER CLI constraints. Retry missing/empty outputs first, then deepen.

## Review

- expected_outputs: 44
- present_outputs: 0
- missing_outputs: 44
- empty_outputs: 0
- next_action: retry_missing_or_empty

## Missing Or Empty

- `analysis_wave18/am_diff_design_2026-04-30.md`
- `analysis_wave18/consultant_firms_2026-04-30.csv`
- `analysis_wave18/pdf_extraction_research_2026-04-30.md`
- `analysis_wave18/url_liveness_2026-04-30.json`
- `analysis_wave18/loops/20260430/url_liveness_shard01.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard01.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard01.json`
- `data/snapshots/am_diff_20260430_shard01.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard01.md`
- `analysis_wave18/loops/20260430/url_liveness_shard02.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard02.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard02.json`
- `data/snapshots/am_diff_20260430_shard02.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard02.md`
- `analysis_wave18/loops/20260430/url_liveness_shard03.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard03.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard03.json`
- `data/snapshots/am_diff_20260430_shard03.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard03.md`
- `analysis_wave18/loops/20260430/url_liveness_shard04.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard04.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard04.json`
- `data/snapshots/am_diff_20260430_shard04.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard04.md`
- `analysis_wave18/loops/20260430/url_liveness_shard05.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard05.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard05.json`
- `data/snapshots/am_diff_20260430_shard05.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard05.md`
- `analysis_wave18/loops/20260430/url_liveness_shard06.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard06.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard06.json`
- `data/snapshots/am_diff_20260430_shard06.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard06.md`
- `analysis_wave18/loops/20260430/url_liveness_shard07.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard07.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard07.json`
- `data/snapshots/am_diff_20260430_shard07.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard07.md`
- `analysis_wave18/loops/20260430/url_liveness_shard08.json`
- `analysis_wave18/loops/20260430/consultant_firms_shard08.csv`
- `data/structured_facts/research_20260430/pdf_structure_shard08.json`
- `data/snapshots/am_diff_20260430_shard08.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard08.md`

## Next Command

```bash
./.venv/bin/python research/loops/research_collection_loop.py next --previous-run 20260430 --max-agents 32
```
