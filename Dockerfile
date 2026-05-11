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
#   * Two DBs coexist on /data (Fly volume) — neither is baked:
#       - /data/jpintel.db (188 MB, FTS5 trigram, core programs + invoice + laws)
#       - /data/autonomath.db (7.36 GB, EAV + sqlite-vec, gated by AUTONOMATH_ENABLED)
#     Entrypoint pulls autonomath.db snapshot from R2 on first boot
#     (AUTONOMATH_DB_URL + AUTONOMATH_DB_SHA256 supplied by Fly secrets).
#   * Embedding model (~470 MB safetensors, multilingual-e5-small) IS baked.
#     Cold-start determinism + no runtime HuggingFace dependency (outage /
#     rate-limit risk).  HF_HUB_OFFLINE=1 locks runtime to the baked copy.
#   * sqlite-vec native vec0.so extracted from the python package.
#   * Layer order: system deps → python deps → model bake → app code,
#     so code-only churn rebuilds only the last layer.
#   * Final image size: ~775 MB (slim base ~90 MB + venv ~160 MB + model ~470 MB
#     + vec0.so 100 KB + app code / scripts ~5 MB).
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
# /seed/jpintel.db (~330 MB) and /seed/unified_registry.json (~54 MB) are
# baked into the image. entrypoint.sh copies them to /data/jpintel.db and
# /opt/venv/lib/python3.12/site-packages/data/unified_registry.json on
# first boot (or whenever DATA_SEED_VERSION changes vs the file in /data).
# Keeps deploys = data refresh; no R2 round-trip for jpintel.db.
COPY data/jpintel.db /seed/jpintel.db
COPY data/unified_registry.json /seed/unified_registry.json
# Phase A static taxonomies + example profiles + 36協定 templates (~84KB tarred).
# entrypoint.sh copies /seed/autonomath_static/ → /data/autonomath_static/ if MANIFEST.md missing.
COPY data/autonomath_static/ /seed/autonomath_static/
# Update this when the baked seed changes, so entrypoint.sh re-copies on next boot.
ENV DATA_SEED_VERSION=2026-05-08-v1

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
