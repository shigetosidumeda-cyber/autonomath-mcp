# R8 — Fly deploy alternative path evaluation (2026-05-07)

> **Internal hypothesis** (read-only audit; deploy operations = 0).
> Live image is still 5/6 (`f3679d6`); 5/7 hardening is **not yet** in production.
> Follow-up debug confirmation (2026-05-07 12:42 JST): `flyctl image show -a
> autonomath-api` still reports `GH_SHA=f3679d6926d8654e106544523283fc04a729ea51`
> on machine `85e273f4e60778`, and `https://api.jpcite.com/healthz` returns
> `{"status":"ok"}`.

## 0. Trigger

`fly deploy --remote-only --strategy rolling` failed with `depot builder deadline_exceeded` after **1431 s** (≈ 23.85 min). The retry was kicked off in a separate background task with `depot=false` (local docker build).

Goal: enumerate **alternative paths** if the depot retry also fails, while changing nothing in production.

---

## 1. Build context audit

### 1.1 Repo size vs Docker context

| Surface | Size | Status |
|---|---|---|
| `/Users/shigetoumeda/jpcite/` (entire) | **17 GB** | uncompressed working tree |
| `autonomath.db` (root) | **12 GB** | excluded by `.dockerignore` |
| `tools/` | 1.2 GB | excluded by `.dockerignore` |
| `data/` (gross) | 513 MB | only `jpintel.db` + `unified_registry.json` + `autonomath_static/` ride |
| `sdk/` | 355 MB | excluded |
| `dist*/` | 919 MB total (`dist` 301 MB + `dist.bak` 319 MB + `dist.bak2` 314 MB + `dist.bak3` 2.9 MB) | excluded |
| `site/` | 300 MB | excluded |
| `analysis_*/` | 150 MB + 228 KB | excluded |
| `autonomath_staging/` | 135 MB | excluded |
| `autonomath_invoice_mirror.db` | 40 MB | excluded by `*.db` glob |
| `graph.sqlite` | 18 MB | excluded by `*.sqlite` glob |
| `.git/` | 103 MB | excluded |
| `research/` | 4.9 MB | excluded |
| `docs/` | 16 MB | excluded by `docs/_internal/` (only canonical mkdocs survives via inclusion in build) |

**Inferred effective Docker context** (what actually gets streamed to the builder):
- `pyproject.toml` + `README.md` + `LICENSE` + `CHANGELOG.md` + `entrypoint.sh` + `Dockerfile` (kilobytes)
- `src/` (13 MB)
- `scripts/` (19 MB) — full tree, not selectively filtered (Dockerfile copies whole `scripts/`)
- `data/jpintel.db` (~352 MB live)
- `data/unified_registry.json` (~54 MB)
- `data/autonomath_static/` (~84 KB)

**Estimated context tarball**: **~440 MB** (dominated by `jpintel.db` + `unified_registry.json`).

This is **not** the cause of the depot timeout. A 440 MB context streams to a depot builder VM in well under 60 s on residential broadband.

### 1.2 `.dockerignore` audit

The current `.dockerignore` is **healthy**. Confirmed exclusions (verified by reading the file at `/Users/shigetoumeda/jpcite/.dockerignore`):

- ✅ `autonomath.db` + WAL/SHM + `*.bak.*` + `*.WAS_*` + `*.CORRUPT_*` snapshots — the 12 GB DB never enters context.
- ✅ `*.db`, `*.sqlite`, `*.sqlite3`, `*.parquet`, `*.jsonl` global excludes (with allowlist re-include for `data/jpintel.db` + `data/unified_registry.json` + `data/autonomath_static/**`).
- ✅ `tools/offline/` — keeps the 1.2 GB inbox/outbox/quarantine/done out.
- ✅ `dist/`, `dist.bak*/` — keeps 919 MB of historical wheels/sdists out.
- ✅ `site/`, `sdk/`, `research/`, `docs/_internal/`, `analysis_*/`, `autonomath_staging/`, `benchmarks/`, `analytics/`, `parts/`, `content/`, `evals/`, `monitoring/` — all excluded.
- ✅ `.git/`, `.github/` — excluded.
- ✅ `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.venv*/` — all excluded.

**No tightening would make a meaningful difference** — context is already minimal.

### 1.3 What is NOT excluded (intentional)

- `scripts/` (19 MB) — Dockerfile needs `migrate.py`, `cron/*`, `etl/*`, `ops/pre_deploy_verify.py` etc. Filtering would require explicit COPY-by-file refactor.
- `data/jpintel.db` (~352 MB) — baked seed (intentional per Dockerfile L113-119; deploy = data refresh model).
- `data/unified_registry.json` (~54 MB) — baked seed for entrypoint copy to `site-packages/data/`.

These are **load-bearing**; cannot be excluded without breaking entrypoint.sh / FastAPI startup.

---

## 2. Local docker daemon state

| Probe | Result |
|---|---|
| `docker version` | Client 29.2.1 (darwin/arm64, Docker Desktop 4.63.0) |
| `docker info` | Server: Docker Desktop 4.63.0 (220185), `desktop-linux` context |
| `docker images python:3.12-slim-bookworm` | **NOT pre-pulled** (will pull on first build, ~50 MB layer download) |
| `df -h /` | 12 GB used / 650 GB available — disk **abundant** |
| `mkdir -p /data /app /models /opt` (Dockerfile L88) | runtime side, not host side; n/a for local build prep |

**Local build feasibility**: ✅ — daemon up, disk space ample, Apple Silicon will pull `linux/amd64` python:3.12-slim-bookworm via Rosetta. Builder layer caches embedding model bake (470 MB safetensors download from HuggingFace), so first-run will take **~10-15 min**, subsequent runs ≤5 min when only `src/` changes.

⚠️ **Note**: Dockerfile pins `--platform=linux/amd64` for both stages. On M1/M2/M3 mac, this means QEMU emulation for the build, which historically takes 2-3× longer than native arm64. Local fallback build will be **slower** than depot's native amd64, not faster.

---

## 3. Alternative paths — recommendation matrix

| Path | What | Risk | Recovery time | Recommendation |
|---|---|---|---|---|
| **A. depot=false local docker** (already retry-running) | `flyctl deploy --local-only` — uses host docker, pushes image directly to Fly registry | M2 emulation slow, but proven; bypasses depot entirely | 10-20 min for first run, 5-10 min on warm cache | **Primary fallback (in flight)** |
| **B. `--build-only` smoke** | `flyctl deploy --build-only` to validate image build without rolling machines | Zero deploy risk; just confirms the build pipeline works | Same as A | Use **if A fails** and you want a no-rollout builder sanity check |
| **C. Tighter `.dockerignore` + remote retry** | Add `scripts/cron/__pycache__/` (already covered) — no actionable additions, ignore is already tight | Won't fix depot; depot timeout is on the **build**, not the **upload** | n/a | **Reject** — context is already 440 MB, not the bottleneck |
| **D. GitHub Actions `deploy.yml`** | `.github/workflows/deploy.yml` already wired; it ALSO uses `flyctl deploy --remote-only` (L174) | Same depot dependency → would hit the same builder; ALSO blocks behind `pre_deploy_verify.py` + `production_deploy_go_gate.py` + 25 s post-deploy smoke | 15-20 min when depot is healthy | **Conditional** — use only after the depot incident clears, or patch deploy.yml to add `--local-only` fallback |
| **E. Wait for depot recovery** | Re-run remote build later | Status-page-dependent; could be hours | n/a | **Last resort** |
| **F. Cancel + investigate fly app status** | `flyctl status -a autonomath-api` to confirm 5/6 image is still serving cleanly while we delay 5/7 hardening | Zero deploy action | Read-only | **Do alongside A** — sanity check live |

### 3.1 Recommended sequence

1. **Wait for path A** (background retry, `depot=false`) to finish. If it pushes successfully → 5/7 hardening lands; STOP.
2. If A fails: run `flyctl status` (path F) to confirm 5/6 is healthy → buys time. Try path B (`--build-only` against depot to see if depot has recovered enough for image build, even if upload is dicey).
3. If B also fails: patch `deploy.yml` (path D) to add `--local-only` fallback so the next CI-driven deploy bypasses depot.
4. Avoid path C entirely — `.dockerignore` is already at the floor.

### 3.2 Why path A (local docker) is the right primary

- The 5/7 hardening is **internal-only** (mypy strict 348→69, acceptance 286/286, 33 DEEP retroactive verify, fingerprint SOT helper). No DB schema change. No manifest bump. Live 5/6 image is **functionally adequate** until the new image lands.
- Local docker on Apple Silicon hits QEMU-amd64 cost but builds **deterministically** — no third-party builder dependency.
- depot timeout (1431 s) is suspicious: typical jpcite depot build takes ~6-8 min. A 23-min stall suggests either (a) depot infra incident, (b) cold cache on their side, (c) network thrash on the model bake step. Local build sidesteps all three.

---

## 4. Open risks (do not action without operator)

- **Embedding model bake step** (Dockerfile L57-66) downloads ~470 MB from HuggingFace at build time. If HuggingFace is rate-limited from the host's IP, the local build will stall here. **Mitigation**: pre-pull the model on host (`huggingface-cli download intfloat/multilingual-e5-small --local-dir /tmp/e5-prep`) and add a build-arg shortcut. NOT recommended without operator approval — would require Dockerfile change.
- **`--platform=linux/amd64` on Apple Silicon** runs the entire builder under QEMU. Slower (2-3×) but functionally identical. No code change recommended.
- **`autonomath.db` lifecycle**: live ~9.4 GB on Fly volume; pulled from R2 on first boot via `AUTONOMATH_DB_URL` + `AUTONOMATH_DB_SHA256`. No deploy-side action needed; the new image inherits the existing volume.

---

## 5. Audit verdict

- ✅ Context size: **healthy** (~440 MB streamed, 17 GB tree).
- ✅ `.dockerignore`: **tight**, no actionable additions.
- ✅ Local docker daemon: **ready** (Docker Desktop 4.63.0 up, 650 GB free).
- ✅ Path A (depot=false retry): **already in flight** in background task.
- ❌ Live 5/7 hardening: **not yet shipped** — `f3679d6` is still serving production.

**Recommended next step**: monitor the existing path-A retry; do not start a parallel deploy. If A fails, escalate to path B/D as outlined.

---

## 6. References

- `/Users/shigetoumeda/jpcite/Dockerfile` (L1-152) — multi-stage builder + runtime, model bake at L57-66.
- `/Users/shigetoumeda/jpcite/.dockerignore` (full file) — exclude allowlist verified.
- `/Users/shigetoumeda/jpcite/.github/workflows/deploy.yml` (L169-174) — current CI deploy command (`--remote-only`).
- `/Users/shigetoumeda/jpcite/fly.toml` — Fly Tokyo app config (release_command intentionally commented per CLAUDE.md guidance).
- Sibling: `R8_FLY_DEPLOY_READINESS_2026-05-07.md` (predeploy gate state).
- Sibling: `R8_FLY_SECRET_SETUP_GUIDE.md` (Fly secrets canonical list).

— end —
