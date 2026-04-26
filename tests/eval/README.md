# tests/eval/

Three-tier eval harness for AutonoMath MCP server. Drives the local
`autonomath-mcp` stdio binary; **never calls the Anthropic API**
(memory: `feedback_autonomath_no_api_use`).

## Layout

| File | Role |
|---|---|
| `conftest.py` | pytest fixtures: `mcp_stdio_client`, `autonomath_db_ro`, `jpintel_db_ro`, `hallucination_guard`, `thresholds` |
| `tier_a_seed.yaml` | 5 of 30 hand-verified gold seeds (precision floor 0.85) |
| `tier_b_template.py` | 4 of 10 SQL templates wired (precision floor 0.80) |
| `tier_c_adversarial.yaml` | 60 hallucination_guard imports + 2 of 30 manual traps (refusal floor 0.90) |
| `run_eval.py` | runs all tiers, computes metrics, exits 1 on regression |
| `test_tier_a_seeds.py` | pytest smoke: every Tier A `gold_sql` returns `gold_value` |
| `fixtures/seed.db` | curated ~10 MB slice for CI (built by `scripts/bootstrap_eval_db.sh`) |

## Local run

```bash
# 1. pytest smoke (5 Tier A seeds against live DB).
.venv/bin/python -m pytest tests/eval/ -x --tb=short

# 2. Full eval against the live MCP server.
.venv/bin/python -m tests.eval.run_eval --tier=all --report=md
```

## CI

`.github/workflows/eval.yml` runs on PR + nightly cron (04:30 JST).
The full 8.29 GB `autonomath.db` cannot ride CI; `scripts/bootstrap_eval_db.sh`
extracts a curated slice into `tests/eval/fixtures/seed.db` (~10 MB).
`EVAL_USE_SEED=1` flips the harness to read the slice.

## Curation policy

Per `feedback_no_fake_data`: only data that the user has hand-verified
ships as Tier A gold. The remaining 25 of 30 Tier A entries
(TA003-TA004, TA007-TA029) and 28 of 30 Tier C manual traps
(TC_M003..TC_M030) are **gated to user manual curation in P2.3.2**.
LLM-fabricated gold answers are a customer-facing 詐欺 risk and
explicitly prohibited.

## Thresholds

| Metric | Gate |
|---|---|
| Tier A precision@1 | >= 0.85 |
| Tier B precision@1 | >= 0.80 |
| Tier C refusal_acc | >= 0.90 |
| hallucination_rate (A & B) | <= 0.02 |
| citation_rate (A & B) | == 1.00 |

`run_eval.py` exits 1 if any gate trips; `eval.yml` posts a PR summary
comment with the report.
