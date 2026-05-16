#!/usr/bin/env bash
# AWS Batch entrypoint shim for jpcite-credit-ec2-spot-gpu jobs.
#
# Runs inside the ECS_AL2_NVIDIA-AMI-backed instance with nvidia-docker2
# + CUDA runtime exposed to the container. Image is the existing
# jpcite-crawler (python:3.12-slim-bookworm) which does NOT ship torch
# or faiss. We install them at runtime here, then dispatch to the GPU
# FAISS index build workload.
#
# NO LLM API calls. Open-weight sentence-transformers only.
# [lane:solo]
#
set -euo pipefail

log() {
  printf '{"ts":"%s","level":"%s","msg":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" >&2
}

log info "gpu_entrypoint_boot"
log info "uname=$(uname -a)"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L >&2 || true
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv >&2 || true
else
  log warn "nvidia_smi_missing"
fi

log info "pip_install_runtime_deps"
# faiss-cpu is the safe baseline; CUDA torch wheels come from PyPI's
# pytorch index for cu121 — that's the CUDA runtime version baked into
# the ECS_AL2_NVIDIA AMI lineage for g4dn/g5.
python -m pip install --quiet --upgrade pip
python -m pip install --quiet \
  "torch==2.4.1" \
  --extra-index-url https://download.pytorch.org/whl/cu121 \
  || python -m pip install --quiet "torch==2.4.1"

python -m pip install --quiet \
  "sentence-transformers==3.1.1" \
  "faiss-cpu==1.8.0.post1" \
  "numpy<2.0" \
  "boto3>=1.34"

log info "pip_install_done"
python -c "import torch; print('torch.cuda.is_available =', torch.cuda.is_available()); print('torch.version =', torch.__version__)" >&2 || true
python -c "import faiss; print('faiss has GPU =', hasattr(faiss, 'StandardGpuResources'))" >&2 || true
python -c "import sentence_transformers; print('st version =', sentence_transformers.__version__)" >&2 || true

log info "dispatch_workload"
exec python /app/build_faiss_index_gpu.py "$@"
