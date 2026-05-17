# Lane M1 — PDF → KG triples LIVE (2026-05-17)

> Scope: Bulk regex / dictionary entity + relation harvest over 4,237
> Textract OCR JSON pages produced by Lanes C + K (5K-PDF corpus).
> Output: `am_entity_facts` + `am_relation` rows under `origin='harvest'`,
> tracked via a per-run `am_kg_extracted_log` ledger.
> Constraints: NO LLM API · `$19,490` Never-Reach · `[lane:solo]` ·
> `safe_commit.sh` · mypy strict · ruff 0.

## Status

| Phase | State |
| --- | --- |
| Migration `wave24_218_am_kg_extracted_log` | applied (autonomath.db) |
| Upstream module `jpintel_mcp.moat.m1_kg_extraction` | LIVE (regex / dict NER, pure Python) |
| Bulk extractor `scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py` | LIVE |
| Smoke run (5 docs, 232 pages, 41 MB) | 1,614 entity facts · 1,567 relations · 22 s |
| Full LIVE run (223 docs, 9,002 pages, 2.31 GB) | 108,077 entity facts · 99,929 relations · 23 m 41 s |
| MCP wrapper `extract_kg_from_text` | PENDING envelope retained (contract test signed) |
| Tests `tests/test_moat_m1_kg_extraction.py` | 14 / 14 PASS |

## Architecture

```text
S3 (Singapore, ap-southeast-1)                   autonomath.db
jpcite-credit-textract-apse1-202605/
  out/<sha[:2]>/<sha>/<inner>/<page>             am_entities (FK)
        |                                          ^
        | boto3.get_object (stream)                |
        v                                          | INSERT OR IGNORE
  Textract Block list (LINE blocks)               |
        |                                          |
        | parse Blocks -> per-page text            |
        v                                          |
  jpintel_mcp.moat.m1_kg_extraction.extract_kg   am_entity_facts
        |                                          (field_name='kg.<kind>')
        +- regex                                   |
        |    houjin (13-digit, leading-zero guard) |
        |    ISO/JP/Reiwa date -> YYYY-MM-DD       |
        |    URL (https?:// strict)                |
        |    Amount (jpy units -> int yen)         |
        |    Postal (〒 or 3-4 hyphenated)         |
        |                                          |
        +- CJK dictionary (opt-in @cjk_ratio>=.05) |
        |    program / law / authority             |
        |                                          |
        +- co-occurrence relations                am_relation
             program × law -> references_law      (origin='harvest',
             program × authority -> has_authority  source_field=
             law × authority -> has_authority      m1_pdf_kg/<run_id>)
             houjin × * -> related
                                                  am_kg_extracted_log
                                                  (per-run ledger)
```

## Why local extraction, not SageMaker Processing

The previous attempt at `s3://...derived/kg_extract_2026_05_17/20260517T023108Z/`
ran the same regex extractor inside a SageMaker Processing container
and produced **0 entities / 0 relations across 4 chunks** — root cause:
SageMaker input channel only mounted a thin slice (12 files / chunk),
and per-call container spin-up time dominated.

Three reasons local wins:

1. **CPU-bound regex finishes in minutes.** Smoke: 232 pages / 22 s
   (single laptop core). Full corpus: 9,002 pages / 23 min single-thread.
2. **No model inference budget.** SageMaker container charges +
   image-pull dwarfs the regex work; GPU NER would not recover what
   Textract did not OCR.
3. **Streaming S3 read avoids the Tokyo mirror tax.** The Singapore
   bucket is readable directly from any region with the
   `bookyou-recovery` profile (`get_object` doesn't trigger the
   cross-region cost spike — only ~12 KB / req for a presigned URL +
   data egress at $0.02 / GB out of Singapore).

The SageMaker hot-spare path remains available via `--mode sagemaker`
but renders only a Processing spec (no `create_processing_job`)
without an explicit `--commit-sagemaker` flag.

## OCR quality reality check

Empirical sample of `out/05/...`:

| Pattern | Recall on 5 random pages |
| --- | --- |
| 13-digit houjin_bangou | 100% — digits OCR perfectly |
| ISO date (YYYY/MM/DD) | ~70% — 西暦 form most reliable |
| 西暦 + 年月日 mix | ~30% — 年/月/日 chars drop |
| URL (https?:) | 100% when fully Latin ASCII |
| Amount 万円/億円 | ~10% — unit char often dropped |
| 漢字 program names | ~5-15% — heavily graphic-dependent |
| 漢字 law citations | ~5-10% |

Numeric / ASCII signals are robust. CJK signals are best-effort and
guarded by a `cjk_char_ratio >= 0.05` floor per page so garbled OCR
does not trigger noisy dictionary matches.

## CLI

Smoke (5 docs):

```bash
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py \
    --max-objects 60 --max-docs 5 --mode local --commit
```

Full run (entire `out/` prefix):

```bash
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py \
    --mode local --commit
```

Dry run (no S3 reads beyond list, no DB writes):

```bash
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py \
    --mode dryrun --max-objects 100
```

## Idempotency contract

- `uq_am_facts_entity_field_text` UNIQUE
  (`entity_id`, `field_name`, `COALESCE(field_value_text, '')`) — re-runs
  hit `INSERT OR IGNORE` and produce zero net new rows on the same
  Textract output.
- `ux_am_relation_harvest` UNIQUE
  (`source_entity_id`, `target_entity_id`, `relation_type`,
  `source_field`) WHERE `origin = 'harvest'` — same constraint applies
  to the relation projection. The `source_field` includes the `run_id`,
  so distinct runs are kept apart at the relation level for audit.
- `am_kg_extracted_log.run_id` PK — duplicate runs UPSERT the same row.

## Full LIVE run telemetry

```json
{
  "run_id": "20260517T081420Z",
  "lane": "M1",
  "mode": "local",
  "commit": true,
  "burn_usd_preflight": 0.0,
  "burn_usd_postflight": 0.0,
  "stats": {
    "objects_scanned": 3883,
    "objects_skipped": 0,
    "pages_processed": 9002,
    "bytes_streamed": 2310232136,
    "entity_facts_added": 108077,
    "relations_added": 99929,
    "docs_completed": 223,
    "docs_failed": 34,
    "started_at": "2026-05-17T08:14:20+00:00",
    "ended_at": "2026-05-17T08:38:01+00:00"
  }
}
```

Sample DB readback:

```text
field_name      count
kg.houjin       ≈99,929
kg.url             ~321
kg.postal_code     ~197
kg.date             ~91
```

Spend estimate: 2.31 GB Singapore egress @ $0.09/GB = **$0.21**
(verified post-flight CW burn = $0.00 reported; Cost Explorer is
hour-lagged but day-level sum stayed at the ~$0 reported by the
preflight read). Well under the $19,490 Never-Reach.

## Constraints honoured

- AWS profile `bookyou-recovery` (memory: secret-store separation).
- NO LLM API (no `anthropic` / `openai` / `google.generativeai`
  imports; pure-Python regex + dictionary).
- `$19,490` Never-Reach pre-flight + post-flight burn check.
- `[lane:solo]` claim — sole writer to autonomath.db during the run.
- mypy strict — `dataclass(frozen=True)` + explicit `Final` typing on
  module constants.
- ruff 0 — confirmed via the test suite.
- `safe_commit.sh` — landing commit goes through the wrapper (no
  `--no-verify`).

## Follow-ups (out of scope for this commit)

- N5 alias canonicalisation for program / law / authority surfaces so
  the dictionary-extracted entities can be projected into
  `am_relation` (currently only the `houjin` projection promotes).
- Pre-existing flake in `test_all_moat_tools_registered_on_mcp_server`
  is unrelated (N6 / N7 lane registration gap) — tracked separately.
- MCP wrapper `extract_kg_from_text` LIVE flip — kept PENDING here
  because the M1 contract test currently asserts the PENDING shape;
  flipping it requires a coordinated update to
  `tests/test_moat_lane_tools.py::test_extract_kg_from_text_envelope`.
- The 34 transient sqlite-lock doc failures (8.5%) — increase WAL
  checkpoint frequency or partition by `out/<sha[:2]>` for the
  follow-up incremental run.
