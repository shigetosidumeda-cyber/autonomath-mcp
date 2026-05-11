# syntax=docker/dockerfile:1.6
# ------------------------------------------------------------------
# AutonoMath API — Fly.io production image
# Package name: autonomath-mcp / Operator: Bookyou株式会社
# ------------------------------------------------------------------
# Build with:  docker build --platform linux/amd64 -t autonomath-api .
# Fly.io Tokyo region runs on x86_64; pin the platform explicitly so
# Apple Silicon dev boxes don't pull the broken arm64 sqlite-vec wheel
# (0.1.6 aarch64 ships a mis-targeted 32-bit ARM binary — upstream bug).
# ------------------------------------------------------------------
# Design goals:
#   * Multi-stage: builder isolates wheel cache + model download; runtime is slim.
#   * jpintel.db (~352 MB, FTS5 trigram) IS baked into /seed/jpintel.db at
#     build time (Wave 22, 2026-05-11). Two paths populate the build context:
#       1. data/jpintel.db hydrated by deploy.yml from `flyctl ssh sftp get`
#          (preferred — freshest production snapshot).
#       2. Build-arg `JPINTEL_DB_R2_URL` lets the remote builder pull the
#          R2 canonical mirror (`autonomath-api/jpintel.db.gz`) when the CI
#          hydrate path has not seeded the build context. Independent of
#          GHA runner network and the 200+ MB sftp tunnel that collapses on
#          large transfers. Build cache is keyed on the upstream object so
#          subsequent rebuilds skip the download.
#     Production runtime never re-fetches jpintel.db — entrypoint copies the
#     baked seed into the /data Fly volume only when the volume copy is
#     missing or sub-threshold (size-guarded). Removes the 60min sftp
#     timeout pattern that took prod down 2026-05-11 12:00-13:30.
#   * /data/autonomath.db (9.4 GB, EAV + sqlite-vec, gated by
#     AUTONOMATH_ENABLED) stays on the Fly volume. Entrypoint §2 size-based
#     gate trusts a production-sized volume copy; bootstraps from
#     AUTONOMATH_DB_URL only on a truly empty volume (DR drill / new region).
#   * Embedding model (~470 MB safetensors, multilingual-e5-small) IS baked.
#     Cold-start determinism + no runtime HuggingFace dependency (outage /
#     rate-limit risk).  HF_HUB_OFFLINE=1 locks runtime to the baked copy.
#   * sqlite-vec native vec0.so extracted from the python package.
#   * Layer order: system deps → python deps → model bake → app code,
#     so code-only churn rebuilds only the last layer.
#   * Final image size: ~1.1 GB (slim base ~90 MB + venv ~160 MB + model
#     ~470 MB + jpintel seed ~352 MB + vec0.so 100 KB + app code ~5 MB).
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Stage 0 — seed-stager: stages /seed/jpintel.db at build time.
#
# Strategy (Wave 22, 2026-05-11):
#   1. Copy data/jpintel.db from build context. CI hydrate step
#      (deploy.yml) sftp-pulls the freshest /data/jpintel.db snapshot
#      from the live Fly machine. Local dev builds carry a 1.3 MB
#      fixture which fails the size gate below.
#   2. Size-gate: if the copied file is >= 100 MB we trust it as the
#      production seed and finalize /seed/jpintel.db.
#   3. R2 fallback: build-arg `JPINTEL_DB_R2_URL` (a curl-fetchable
#      pre-signed URL or public-readable mirror) lets the remote
#      builder pull `autonomath-api/jpintel.db.gz` directly. Verifies
#      with `gunzip -t` + `sqlite3 PRAGMA quick_check`. Cache layer is
#      keyed on the URL string so identical builds reuse the layer.
#
# This stage is intentionally tiny (curl + sqlite3 only) so the
# 350 MB download invalidates only this seed layer, not the python
# venv or model layers above.
# ------------------------------------------------------------------
FROM --platform=linux/amd64 debian:bookworm-slim AS seed-stager
ARG JPINTEL_DB_R2_URL=""
ARG JPINTEL_DB_MIN_BYTES=100000000

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates sqlite3 gzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /seed

# Copy any build-context jpintel.db. The deploy.yml hydrate step
# overwrites the 1.3 MB dev fixture with a 352+ MB live snapshot
# before `flyctl deploy`; local dev keeps the small fixture.
COPY data/jpintel.db /seed/jpintel.db.candidate

# Decide source: build-context if it meets the size threshold;
# otherwise R2 fallback. Fail the build if neither is usable so we
# never bake a tiny dev fixture into a production image.
RUN set -eu; \
    cand_size=$(stat -c%s /seed/jpintel.db.candidate 2>/dev/null || echo 0); \
    echo "build-context jpintel.db.candidate = ${cand_size} bytes"; \
    if [ "${cand_size}" -ge "${JPINTEL_DB_MIN_BYTES}" ]; then \
        echo "using build-context seed (>= ${JPINTEL_DB_MIN_BYTES} bytes)"; \
        mv /seed/jpintel.db.candidate /seed/jpintel.db; \
    elif [ -n "${JPINTEL_DB_R2_URL}" ]; then \
        echo "build-context seed below threshold (${cand_size} < ${JPINTEL_DB_MIN_BYTES}); pulling R2"; \
        curl -fL --retry 5 --retry-delay 10 --retry-all-errors \
             -o /tmp/jpintel.db.gz "${JPINTEL_DB_R2_URL}"; \
        gunzip -t /tmp/jpintel.db.gz; \
        gunzip -c /tmp/jpintel.db.gz > /seed/jpintel.db; \
        rm -f /tmp/jpintel.db.gz /seed/jpintel.db.candidate; \
        r2_size=$(stat -c%s /seed/jpintel.db); \
        echo "R2 seed landed = ${r2_size} bytes"; \
        if [ "${r2_size}" -lt "${JPINTEL_DB_MIN_BYTES}" ]; then \
            echo "ERROR: R2-fetched seed below threshold (${r2_size})"; exit 1; \
        fi; \
    else \
        echo "ERROR: build-context jpintel.db is ${cand_size} bytes and JPINTEL_DB_R2_URL is unset."; \
        echo "Either run deploy.yml hydrate step before flyctl deploy, or pass --build-arg JPINTEL_DB_R2_URL=<presigned-or-public-url>."; \
        exit 1; \
    fi; \
    quick=$(sqlite3 /seed/jpintel.db 'PRAGMA quick_check;' 2>&1 | head -1); \
    if [ "${quick}" != "ok" ]; then \
        echo "ERROR: seed quick_check failed: ${quick}"; exit 1; \
    fi; \
    programs=$(sqlite3 /seed/jpintel.db 'SELECT COUNT(*) FROM programs;' 2>/dev/null || echo 0); \
    echo "seed quick_check=ok programs=${programs}"; \
    if [ "${programs}" -lt 10000 ]; then \
        echo "ERROR: seed programs count below 10000 floor (${programs})"; exit 1; \
    fi

# ------------------------------------------------------------------
FROM --platform=linux/amd64 python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build deps only — not copied into final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*

# -- Resolve project deps into an isolated venv (cacheable layer) --
# README.md / LICENSE / CHANGELOG.md required by hatchling metadata validation.
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src/ ./src/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[site]" \
    && /opt/venv/bin/pip install "sqlite-vec==0.1.6" "huggingface_hub>=0.26"

# -- Extract vec0.so from sqlite-vec package to a stable path --
# sqlite_vec ships the platform native lib at sqlite_vec/vec0.{so,dylib,dll}.
# We only need the linux-x86_64 .so for runtime.
RUN cp "$(/opt/venv/bin/python -c 'import sqlite_vec, os; print(os.path.join(os.path.dirname(sqlite_vec.__file__), "vec0.so"))')" /opt/vec0.so \
    && ls -lah /opt/vec0.so

# -- Bake e5-small embedding model (~470 MB safetensors) --
# Downloaded once at build time; runtime sets HF_HUB_OFFLINE=1.
# Aggressive ignore list: drop onnx/openvino/pytorch_bin/tf/flax/eval duplicates
# (cuts repo from ~1.4 GB to ~470 MB — sentence-transformers loads safetensors only).
RUN /opt/venv/bin/python -c "from huggingface_hub import snapshot_download; \
snapshot_download(repo_id='intfloat/multilingual-e5-small', \
local_dir='/models/e5-small', \
ignore_patterns=['*.onnx', '*.msgpack', 'flax_model.*', 'tf_model.*', 'rust_model.*', '*.h5', 'pytorch_model.bin', 'onnx/*', 'openvino/*', '.eval_results/*', '.cache/*', '*.md'])" \
    && rm -rf /models/e5-small/.cache /models/e5-small/.eval_results /models/e5-small/onnx /models/e5-small/openvino \
    && du -sh /models/e5-small

# ------------------------------------------------------------------
FROM --platform=linux/amd64 python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="AutonoMath API"
LABEL org.opencontainers.image.vendor="Bookyou株式会社"
LABEL org.opencontainers.image.licenses="MIT"
# TODO(org-claim): switch back to github.com/AutonoMath/autonomath-mcp once the AutonoMath GitHub org is claimed.
LABEL org.opencontainers.image.source="https://github.com/shigetosidumeda-cyber/jpintel-mcp"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv

# Runtime system deps. sqlite3 CLI kept for on-box debugging / backup.py.
# curl kept for entrypoint R2 bootstrap; rclone is used by restore_db.py and
# the shared Cloudflare R2 helper for operator restores.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates sqlite3 rclone \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data /app /models /opt

WORKDIR /app

# -- venv from builder (largest layer, cached unless deps change) --
COPY --from=builder /opt/venv /opt/venv

# -- sqlite-vec native extension --
COPY --from=builder /opt/vec0.so /opt/vec0.so
ENV AUTONOMATH_VEC0_PATH=/opt/vec0.so

# -- baked embedding model + offline-only HF cache --
COPY --from=builder /models/e5-small /models/e5-small
ENV TRANSFORMERS_CACHE=/models \
    HF_HOME=/models \
    AUTONOMATH_EMBEDDING_MODEL_PATH=/models/e5-small \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# -- app code + operational scripts --
# scripts/ included so release_command (migrate.py) and on-box backup.py
# are available to the entrypoint.
COPY src/ /app/src/
COPY scripts/ /app/scripts/
# API discovery endpoint `/v1/mcp-server.json` reads this root manifest at
# runtime so AI/MCP importers can discover jpcite from api.jpcite.com too.
COPY mcp-server.json /app/mcp-server.json

# -- baked seed data (jpintel.db + unified_registry.json) --
# /seed/jpintel.db (~352 MB) and /seed/unified_registry.json (~54 MB) are
# baked into the image. jpintel.db is staged by the `seed-stager` stage
# at the top of this Dockerfile, which size-gates the build-context copy
# and falls back to the R2 mirror (build-arg JPINTEL_DB_R2_URL) when the
# build context only has the 1.3 MB dev fixture. entrypoint.sh copies
# both seeds onto the /data Fly volume on first boot or whenever
# DATA_SEED_VERSION drifts. Production runtime never re-fetches
# jpintel.db over sftp — the 60min sftp tunnel failure mode is gone.
COPY --from=seed-stager /seed/jpintel.db /seed/jpintel.db
COPY data/unified_registry.json /seed/unified_registry.json
# Phase A static taxonomies + example profiles + 36協定 templates (~84KB tarred).
# entrypoint.sh copies /seed/autonomath_static/ → /data/autonomath_static/ if MANIFEST.md missing.
COPY data/autonomath_static/ /seed/autonomath_static/
# Update this when the baked seed changes, so entrypoint.sh re-copies on next boot.
# Wave 22 bump (2026-05-11): seed-stager now bakes a production-sized jpintel.db
# into /seed/, so the existing volume copy stays authoritative unless the
# operator opts into JPINTEL_FORCE_SEED_OVERWRITE=1.
ENV DATA_SEED_VERSION=2026-05-11-w22

# -- entrypoint: created by separate agent. Performs (post 2026-05-11):
#       1. /data/autonomath.db size-based gate. If volume DB is already at
#          production scale (>= 5 GB by default), it is trusted as-is and
#          SHA256 + R2 are skipped. Cron ETL mutates autonomath.db in place,
#          so a baked-image SHA256 drifts immediately; hashing it on every
#          boot is a false signal that previously triggered 30+ min outages
#          while a 9 GB DB looped on R2 re-download.
#       2. If the DB is missing or sub-threshold, fall back to either the
#          legacy SHA256 verification path (BOOT_ENFORCE_DB_SHA=1) or the
#          R2 bootstrap (AUTONOMATH_DB_URL).
#       3. schema_guard + migrate.py
#       4. exec uvicorn (CMD)
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# -- runtime env --
# Two DBs coexist on /data Fly volume. Distinct paths, no ATTACH.
ENV JPINTEL_DB_PATH=/data/jpintel.db \
    AUTONOMATH_DB_PATH=/data/autonomath.db \
    AUTONOMATH_ENABLED=true \
    SENTRY_ENVIRONMENT=production \
    JPINTEL_LOG_FORMAT=json \
    JPINTEL_LOG_LEVEL=INFO
# AUTONOMATH_DB_URL + AUTONOMATH_DB_SHA256 supplied at runtime via Fly secrets.
# Note (2026-05-11): AUTONOMATH_DB_SHA256 is now OPTIONAL at boot. The default
# §2 entrypoint gate accepts any production-sized volume DB (cron-mutated SHA
# drift is expected); set BOOT_ENFORCE_DB_SHA=1 + AUTONOMATH_DB_SHA256 in DR
# drills / snapshot-restore flows to re-enable the strict verification path.

EXPOSE 8080

# HEALTHCHECK intentionally omitted — Fly handles it via fly.toml
# (grace_period 120s covers R2 download on first boot).

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "jpintel_mcp.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--loop", "uvloop", "--http", "httptools"]
