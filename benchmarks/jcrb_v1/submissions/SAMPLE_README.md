# JCRB-v1 submissions inbox

Drop one JSON file per `(model, mode)` submission here. The
`scripts/cron/jcrb_publish_results.py` operator cron picks these up
weekly and publishes `site/benchmark/results.json`.

The operator does NOT execute customer code or call any LLM provider.
This directory is the only ingress channel; submissions are validated
by schema only.

## Required envelope (one file per submission)

```json
{
  "model": "claude-opus-4-7",
  "provider": "claude",
  "mode": "without_jpcite",
  "submitted_at": "2026-05-04T12:00:00Z",
  "submitter": "anon",
  "n": 100,
  "exact_match": 0.18,
  "citation_ok": 0.42,
  "by_domain": {
    "subsidy_eligibility": {"n": 20, "exact_match": 0.10, "citation_ok": 0.30},
    "tax_application":     {"n": 20, "exact_match": 0.20, "citation_ok": 0.45},
    "law_citation":        {"n": 20, "exact_match": 0.25, "citation_ok": 0.50},
    "adoption_statistics": {"n": 20, "exact_match": 0.15, "citation_ok": 0.40},
    "enforcement_risk":    {"n": 20, "exact_match": 0.20, "citation_ok": 0.45}
  },
  "predictions_url": "https://gist.github.com/.../predictions.jsonl",
  "questions_sha256": "abc123..."
}
```

`model` + `mode` is the dedup key. Re-submitting the same pair replaces
the older row. File naming is free-form; suggest
`<model>__<mode>__<yyyymmdd>.json`.

## How customers run

```bash
python benchmarks/jcrb_v1/run.py \
    --provider claude --model claude-opus-4-7 \
    --mode without_jpcite \
    --out predictions/claude_without.jsonl

python benchmarks/jcrb_v1/scoring.py \
    --predictions predictions/claude_without.jsonl \
    --out reports/claude_without

# Then POST reports/claude_without.json to operator (or PR-add into this dir).
```
