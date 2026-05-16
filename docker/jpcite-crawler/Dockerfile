# syntax=docker/dockerfile:1.6
# ------------------------------------------------------------------
# jpcite-crawler — Generic Python crawler for AWS Batch credit run
# Operator: Bookyou株式会社 (T8010001213708)
# Project: jpcite / CreditRun: 2026-05
#
# Purpose:
#   AWS Batch job container that ingests a manifest JSON from S3,
#   fetches public source URLs respecting robots.txt + per-source
#   terms, and emits jpcite contract artifacts (run_manifest.json,
#   object_manifest.jsonl, source_receipts.jsonl, known_gaps.jsonl,
#   source_profile_delta.jsonl) back to S3 under a run-specific
#   prefix.
#
# Constraints:
#   * NO LLM API calls. NO outbound traffic beyond manifest targets.
#   * Respects robots.txt + per-source license boundary policy.
#   * Rate-limit + retry + gzip + ETag/Last-Modified support.
#   * SHA-256 content hash for every artifact.
#   * Linux/amd64 baseline (AWS Batch Fargate Spot + EC2 Spot).
#   * Layer order: system deps -> python deps -> source code so
#     code-only churn rebuilds only the final layer.
# ------------------------------------------------------------------
FROM --platform=linux/amd64 python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="jpcite-crawler"
LABEL org.opencontainers.image.vendor="Bookyou株式会社"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/shigetosidumeda-cyber/autonomath-mcp"
LABEL org.opencontainers.image.description="Generic public-source crawler for AWS Batch credit run (J01-J07). Respects robots.txt + per-source license boundary, emits jpcite contract manifests to S3."
LABEL com.bookyou.jpcite.project="jpcite"
LABEL com.bookyou.jpcite.credit-run="2026-05"
LABEL com.bookyou.jpcite.image="jpcite-crawler"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime system deps. ca-certificates required for httpx TLS; curl kept
# for boot-time S3 manifest probe; tini for proper PID1 + signal handling
# in AWS Batch (SIGTERM at attemptDurationSeconds / Spot interruption).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app /work

WORKDIR /app

# Pinned versions (Wave 50 launch baseline). httpx + lxml + beautifulsoup4
# for fetch + parse; boto3 + pyarrow for S3 + parquet emit; cryptography
# kept available even though hashlib SHA-256 covers content_hash, because
# downstream signing (Ed25519) lives in the same image lineage.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Source code (last layer so iteration on crawl.py / manifest.py /
# entrypoint.py only rebuilds this layer).
COPY entrypoint.py /app/entrypoint.py
COPY crawl.py /app/crawl.py
COPY manifest.py /app/manifest.py

# /work is the per-job scratch dir. AWS Batch ephemeral volume by default.
ENV JPCITE_WORK_DIR=/work \
    JPCITE_USER_AGENT="jpcite-crawler/0.1.0 (+https://jpcite.com; ops@bookyou.net)" \
    JPCITE_DEFAULT_DELAY_SECONDS=1.0 \
    JPCITE_DEFAULT_TIMEOUT_SECONDS=30 \
    JPCITE_MAX_RETRIES=3 \
    JPCITE_RUN_ID="" \
    JPCITE_JOB_ID="" \
    JOB_MANIFEST_S3_URI=""

# tini handles SIGTERM cleanly so AWS Batch attemptDurationSeconds and
# Spot interruption hand off gracefully to entrypoint.py (which flushes
# the partial run_manifest + object_manifest before exit).
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/entrypoint.py"]
