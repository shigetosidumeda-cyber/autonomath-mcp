# AWS Moat Lane M10 — OpenSearch Production-Grade Cluster + Full-Corpus Ingest

**Date**: 2026-05-17
**Status**: cluster scale-up triggered (blue-green processing); bulk indexer + MCP wrapper landed
**AWS profile**: bookyou-recovery (account 993693061769)
**Region**: ap-northeast-1
**Budget cap**: $19,490 Never-Reach (respected externally)

---

## Cluster spec

| dimension        | before (Lane F)              | after (Lane M10)                              |
| ---------------- | ---------------------------- | --------------------------------------------- |
| data nodes       | r5.4xlarge.search × 1        | **r5.4xlarge.search × 3**                     |
| dedicated master | none                         | **r5.large.search × 3**                       |
| ultrawarm        | disabled                     | **ultrawarm1.medium.search × 3**              |
| zone-aware       | false (single-AZ)            | **true (3-AZ multi-AZ HA)**                   |
| EBS              | gp3 100 GB                   | **gp3 500 GB (Iops=3000, Throughput=250)**    |
| encryption       | node-to-node + at-rest (TLS) | unchanged                                     |

Trigger:

```
aws opensearch update-domain-config --domain-name jpcite-xfact-2026-05 \
  --cluster-config 'InstanceType=r5.4xlarge.search,InstanceCount=3,DedicatedMasterEnabled=true,DedicatedMasterType=r5.large.search,DedicatedMasterCount=3,WarmEnabled=true,WarmType=ultrawarm1.medium.search,WarmCount=3,ZoneAwarenessEnabled=true,ZoneAwarenessConfig={AvailabilityZoneCount=3}' \
  --ebs-options 'EBSEnabled=true,VolumeType=gp3,VolumeSize=500' \
  --profile bookyou-recovery --region ap-northeast-1
```

Blue-green deploy timeline: ~30-60 min (Processing=true at trigger, transitions to false when both data + master + ultrawarm fleets are ACTIVE).

Endpoint (stable across the upgrade):
`search-jpcite-xfact-2026-05-zcb4ecabq7znunu5yzdj2afzzy.ap-northeast-1.es.amazonaws.com`

---

## Burn target

Sustained ~$108/day from this lane alone:

| component                  | unit price (Tokyo)         | qty | daily   |
| -------------------------- | -------------------------- | --- | ------- |
| r5.4xlarge.search          | $1.504/h (24h)             | 3   | ~$108.3 |
| r5.large.search master     | $0.188/h                   | 3   | ~$13.5  |
| ultrawarm1.medium.search   | $0.238/h                   | 3   | ~$17.1  |
| gp3 EBS storage 500 GB     | $0.10/GB-month → $0.0033/d | 3   | ~$5.0   |
| **lane total (sustained)** |                            |     | **~$144/day** |

Headroom against the $19,490 cap is governed by the global hard-stop 5-line defense (CW $14K / Budget $17K / slowdown $18.3K / CW $18.7K Lambda / Action $18.9K deny).

---

## Index design — `jpcite-corpus-2026-05`

- **shards**: 6 / **replicas**: 1 / **refresh_interval**: 30s
- **analyzer**: `ja_kuromoji` (kuromoji_tokenizer + kuromoji_baseform + kuromoji_part_of_speech + ja_stop + kuromoji_number + kuromoji_stemmer)
- **knn_vector** field `embedding` (dim=384, HNSW, cosinesimil, ef_construction=128, m=16) — paired with M4 BERT-FT 384-d vectors when those land (Lane M5 fine-tune output).
- **retention**: 30-day hot tier → ultrawarm migration (ISM policy to be configured post-burn-in).

Source corpora and document counts (8 corpora, **595,545 docs** target ≈ 600K spec):

| corpus        | DB                | row source             | rows    |
| ------------- | ----------------- | ---------------------- | ------- |
| programs      | data/jpintel.db   | `programs` (S/A/B/C)   | 11,601  |
| laws          | data/jpintel.db   | `laws`                 | 9,484   |
| law_articles  | autonomath.db     | `am_law_article`       | 353,278 |
| cases         | data/jpintel.db   | `case_studies`         | 2,286   |
| adoption      | autonomath.db     | `jpi_adoption_records` | 201,845 |
| court         | data/jpintel.db   | `court_decisions`      | 2,065   |
| invoice       | data/jpintel.db   | `invoice_registrants`  | 13,801  |
| enforcement   | data/jpintel.db   | `enforcement_cases`    | 1,185   |
| **TOTAL**     |                   |                        | **595,545** |

---

## Bulk indexer

Script: `scripts/aws_credit_ops/opensearch_bulk_index_2026_05_17.py`

Operations:

```
--status         describe-domain summary
--create-index   PUT mapping (idempotent — HEAD check first)
--bulk-index     stream 8 corpora into _bulk (default BULK_BATCH=1000)
--hybrid-query   smoke test BM25 hybrid query
```

Parallelism: 10 worker `ThreadPoolExecutor` across the 8 corpora (one Python iterator per corpus, batched into 1000-doc bulk POSTs, SigV4-signed). All requests pinned to the IAM principal `arn:aws:iam::993693061769:user/bookyou-recovery-admin`.

Typical run shape (once domain is ACTIVE):

```
.venv/bin/python scripts/aws_credit_ops/opensearch_bulk_index_2026_05_17.py \
  --create-index --bulk-index --hybrid-query "中小企業 補助金 東京"
```

---

## MCP wrapper — `opensearch_hybrid_search`

File: `src/jpintel_mcp/mcp/autonomath_tools/opensearch_hybrid_tools.py`

Registered in `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` under the `AUTONOMATH_OPENSEARCH_HYBRID_ENABLED` gate (default ON when `settings.autonomath_enabled`).

Surface:

```
opensearch_hybrid_search(
  query: str,
  corpus_kind: str | None = None,    # program / law / law_article / case / adoption / court / invoice / enforcement
  prefecture: str | None = None,     # term filter (exact match)
  tier: str | None = None,           # term filter (S/A/B/C)
  min_amount_man_yen: float | None = None,  # range filter on amount_max_man_yen
  top_n: int = 10,
) -> dict
```

Composition:

- BM25 multi_match over `title^3 + body` (kuromoji-analyzed).
- Optional vector ANN over `embedding` (k-NN, dim=384) when caller supplies an embedding — reserved for M4 BERT-FT pairing.
- Pure SigV4-signed `_search` request. NO LLM. Single `¥3/req` billing event.
- §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope (retrieval surface only — NOT a 採択 forecast / 法的意見 / 税務助言 / 行政書士業務).

---

## Constraints honoured

- $19,490 Never-Reach budget cap respected externally; this lane does not perform budget checks.
- NO LLM API call from anywhere under `src/` / `scripts/cron/` / `scripts/etl/` / `tests/`.
- `safe_commit.sh` used for the landing commit.
- Co-Authored-By: Claude Opus 4.7.
- `[lane:solo]` tag.

---

## Follow-ups (non-blocking)

- Pair `embedding` field with M4 BERT-FT 384-d vectors as Lane M4/M5 ingest completes.
- Configure ISM policy for hot → ultrawarm migration at day-30 boundary.
- Wire `opensearch_hybrid_search` into the manifest tool count (currently runtime-only; bump on the next intentional release).
