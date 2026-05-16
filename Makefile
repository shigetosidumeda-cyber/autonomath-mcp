# jpcite — developer Makefile (Stream F, Wave 49)
#
# Convenience entry points for the loops the project runs constantly. All
# targets shell out to the existing scripts so behaviour stays identical
# whether developers invoke `make <target>` or run the underlying command
# directly.  No target hides side-effects beyond what the wrapped script
# already does, and no target mutates state that the wrapped script does
# not already mutate.
#
# Honoured environment:
#   PY      — python interpreter (default: .venv/bin/python)
#   PYTEST  — pytest invocation (default: .venv/bin/pytest)
#   RUFF    — ruff binary  (default: .venv/bin/ruff)
#   BLACK   — black binary (default: .venv/bin/black)
#   ISORT   — isort binary (default: .venv/bin/isort)
#   MYPY    — mypy binary  (default: .venv/bin/mypy)
#
# Use `make help` to list the available targets.

PY      ?= .venv/bin/python
PYTEST  ?= .venv/bin/pytest
RUFF    ?= .venv/bin/ruff
BLACK   ?= .venv/bin/black
ISORT   ?= .venv/bin/isort
MYPY    ?= .venv/bin/mypy

# P0 selector — keeps every facade / outcome routing / CSV intake / release
# capsule / agent runtime hot path inside the smallest CI loop. Mirrors the
# pytest `-k` expression that Stream H gates on so the local loop matches
# the production gate.
P0_K = p0 or facade or outcome_routing or csv_intake or release_capsule or agent_runtime

.DEFAULT_GOAL := help

.PHONY: help test test-p0 lint format typecheck typecheck-fast mypy-fast mypy-file mypy-restart typecheck-fast-stop pre-commit-install pre-commit-run safe-commit site api mcp bootstrap gate validate sync-manifest-sha schema-docs e2e emergency-stop teardown docs docs-fast docs-strict ci-budget-check

help:
	@echo "jpcite Makefile targets:"
	@echo "  make test         Run the full pytest suite"
	@echo "  make test-p0      Run the P0 hot-path subset (-k '$(P0_K)')"
	@echo "  make lint         Run ruff check + black --check"
	@echo "  make format       Run ruff format + black + isort (in-place)"
	@echo "  make typecheck    Run mypy on src/ (one-shot, sqlite-cached)"
	@echo "  make typecheck-fast    Run dmypy daemon incremental check on src/jpintel_mcp/"
	@echo "  make mypy-fast            Alias for typecheck-fast (PERF-37)"
	@echo "  make mypy-file FILE=...   dmypy single-file check (<0.1s warm, PERF-37)"
	@echo "  make mypy-restart         Recycle dmypy daemon after pip install -e (PERF-37)"
	@echo "  make typecheck-fast-stop  Stop the dmypy daemon"
	@echo "  make pre-commit-install   Install .git/hooks/pre-commit (one-time per clone)"
	@echo "  make pre-commit-run       Run all pre-commit hooks across the tree"
	@echo "  make safe-commit MSG='...'  Defensive git commit (detects silent pre-commit stash abort)"
	@echo "  make site         Regenerate sitemap + llms metadata"
	@echo "  make api          Re-export OpenAPI v1 spec"
	@echo "  make mcp          Run server.json drift check"
	@echo "  make bootstrap    Run agent runtime bootstrap (--write)"
	@echo "  make gate         Run production deploy readiness gate"
	@echo "  make validate     Validate release capsule"
	@echo "  make sync-manifest-sha  Idempotently sync release manifest sha256 -> well-known"
	@echo "  make schema-docs  Regenerate docs/_internal/JPCIR_SCHEMA_REFERENCE.md from schemas/jpcir/"
	@echo "  make docs         Build mkdocs site (no strict, social plugin honoured)"
	@echo "  make docs-fast    PERF-15 incremental dev build (no strict, --dirty, social OFF)"
	@echo "  make docs-strict  CI-equivalent build (--strict, fails on warnings)"
	@echo "  make e2e          bootstrap -> api -> mcp -> sync-manifest-sha -> validate -> gate"
	@echo "  make emergency-stop"
	@echo "                    PANIC BUTTON. Stream I/E kill switch (AWS + CF rollback)."
	@echo "                    DRY_RUN=true default. Live: DRY_RUN=false + JPCITE_EMERGENCY_TOKEN"
	@echo "                    Usage: make emergency-stop MODE=aws|cf|both [PREV_CAPSULE_ID=...]"
	@echo "  make teardown     Stream E planned-teardown 01..05 sequence."
	@echo "                    DRY_RUN=true default. Live: DRY_RUN=false + JPCITE_TEARDOWN_LIVE_TOKEN"
	@echo "                    Optional step 08 (ECR attacker-repo cleanup, dual-region):"
	@echo "                    JPCITE_INCLUDE_ECR_CLEANUP=true to append 08_ecr_attacker_cleanup.sh"
	@echo "                    (requires Awano-san confirmation on the compromise ticket)."
	@echo "  make ci-budget-check    PERF-42 GHA wall-clock budget gate (local summary mode)"
	@echo "  make help         Show this list"

test:
	$(PYTEST)

test-p0:
	$(PYTEST) -k "$(P0_K)"

lint:
	$(RUFF) check src tests scripts
	$(BLACK) --check src tests scripts

format:
	$(RUFF) format src tests scripts
	$(BLACK) src tests scripts
	$(ISORT) src tests scripts

typecheck:
	$(MYPY) src/

# PERF-2 (Wave 51, 2026-05-16): dmypy daemon target — keeps the analyzer warm
# in a background process for sub-second incremental checks after touching a
# single file. dmypy reuses the same .mypy_cache/ (sqlite-backed) that the
# one-shot `mypy` target writes, so the first `make typecheck-fast` after a
# wipe takes ~30s (cold) but subsequent invocations are <1s. Use
# `make typecheck-fast-stop` to shut the daemon down (or just let it idle).
#
# PERF-37 (2026-05-17): measured cold start 4.84s vs warm-check 0.087s on
# src/jpintel_mcp/mcp/server.py (≈ 56x speedup). The previous `typecheck-fast`
# target re-checked the entire `src/jpintel_mcp/` package (≈30 s warm on the
# full 60+ kLOC tree) which masked the daemon win for inner-loop edits. Three
# additions land here:
#   1. `mypy-fast`  alias — short canonical name surfaced in the user prompt.
#   2. `mypy-file FILE=…` — single-file daemon check; matches the 0.087 s
#      warm-start measurement and is the recommended save-on-edit loop.
#   3. `mypy-restart` — explicit recycle when the daemon's in-memory state
#      goes stale (post `pip install -e`, post python upgrade, etc.).
# All three reuse the same `.mypy_cache/` SQLite store so cold→warm is a
# one-time tax per shell session, not per file.
typecheck-fast:
	@if ! .venv/bin/dmypy status >/dev/null 2>&1; then \
		echo "[typecheck-fast] starting dmypy daemon (cold start ≈5s)..."; \
		.venv/bin/dmypy start -- --strict; \
	fi
	.venv/bin/dmypy check src/jpintel_mcp/

# PERF-37 alias — short name for the same daemon-backed full-package check.
mypy-fast: typecheck-fast

# PERF-37 single-file daemon check — sub-100ms after warm-up. Usage:
#   make mypy-file FILE=src/jpintel_mcp/mcp/server.py
mypy-file:
	@if [ -z "$(FILE)" ]; then \
		echo "usage: make mypy-file FILE=path/to/foo.py"; exit 2; \
	fi
	@if ! .venv/bin/dmypy status >/dev/null 2>&1; then \
		echo "[mypy-file] starting dmypy daemon (cold start ≈5s)..."; \
		.venv/bin/dmypy start -- --strict; \
	fi
	.venv/bin/dmypy check $(FILE)

# PERF-37 daemon recycle — call after Python interpreter upgrades or
# `pip install -e .` so the in-process module cache reloads cleanly.
mypy-restart:
	-.venv/bin/dmypy stop
	.venv/bin/dmypy start -- --strict

typecheck-fast-stop:
	.venv/bin/dmypy stop || true

# PERF-12 (Wave 51, 2026-05-16): pre-commit install + run targets.
#
# `pre-commit-install` writes .git/hooks/pre-commit so every `git commit` runs
# the .pre-commit-config.yaml hook chain (ruff --fix / ruff-format / mypy /
# bandit / gitleaks / yamllint / distribution drift). One-time setup per clone.
#
# `pre-commit-run` is the manual full-tree sweep used by CI parity checks and
# whenever a developer wants to lint+format the whole repo without committing.
# Ruff hits .ruff_cache (warm ~30ms on src/scripts/tests, cold ~330ms after a
# .ruff_cache wipe — verified 2026-05-16) so the run cost is dominated by mypy
# strict, not ruff.
pre-commit-install:
	.venv/bin/pre-commit install
	@echo "[pre-commit] hook installed at .git/hooks/pre-commit"
	@echo "[pre-commit] run 'make pre-commit-run' to sweep the whole tree"

pre-commit-run:
	.venv/bin/pre-commit run --all-files

# safe-commit (2026-05-17): defensive wrapper around `git commit` that
# surfaces silent pre-commit stash aborts (root cause analysis +
# remediation in docs/_internal/PRE_COMMIT_STASH_CONFLICT_2026_05_17.md).
# Never bypasses hooks. Usage: make safe-commit MSG="subject [lane:solo]"
safe-commit:
	@if [ -z "$(MSG)" ]; then echo "[safe-commit] usage: make safe-commit MSG=\"subject [lane:solo]\""; exit 2; fi
	scripts/safe_commit.sh -m "$(MSG)"

site:
	$(PY) scripts/regen_structured_sitemap_and_llms_meta.py

api:
	$(PY) scripts/export_openapi.py

mcp:
	$(PY) scripts/check_distribution_manifest_drift.py

bootstrap:
	$(PY) scripts/agent_runtime_bootstrap.py --write

gate:
	$(PY) scripts/ops/production_deploy_readiness_gate.py

validate:
	$(PY) scripts/ops/validate_release_capsule.py

sync-manifest-sha:
	$(PY) scripts/ops/sync_release_manifest_sha.py

schema-docs:
	$(PY) scripts/ops/generate_schema_docs.py

e2e: bootstrap api mcp sync-manifest-sha validate gate

# WARNING: emergency-stop is the panic-button entry point for the Stream I
# live AWS canary phase. Wraps scripts/ops/emergency_kill_switch.sh. Defaults
# to DRY_RUN=true; flip explicitly with DRY_RUN=false + JPCITE_EMERGENCY_TOKEN
# in the environment for live execution.
# MODE selects: aws (teardown only) / cf (CF Pages rollback only) / both.
MODE ?= both
PREV_CAPSULE_ID ?=
emergency-stop:
	@echo "[emergency-stop] DRY_RUN=$${DRY_RUN:-true} MODE=$(MODE) PREV_CAPSULE_ID=$(PREV_CAPSULE_ID)"
	bash scripts/ops/emergency_kill_switch.sh $(MODE) $(PREV_CAPSULE_ID)

# Stream E planned-teardown orchestrator. Runs scripts/teardown/run_all.sh
# which sequences 01_identity_budget_inventory.sh through 05_teardown_attestation.sh.
# Defaults to DRY_RUN=true; live execution requires DRY_RUN=false +
# JPCITE_TEARDOWN_LIVE_TOKEN.
#
# Optional Wave 50 post-launch step 08 (ECR attacker-repo cleanup) is appended
# when JPCITE_INCLUDE_ECR_CLEANUP=true is set — only after Awano-san (AWS Japan)
# confirms the BookYou account-compromise ticket can be closed.
teardown:
	@echo "[teardown] DRY_RUN=$${DRY_RUN:-true} JPCITE_INCLUDE_ECR_CLEANUP=$${JPCITE_INCLUDE_ECR_CLEANUP:-false}"
	bash scripts/teardown/run_all.sh

# PERF-15 (Wave 51, 2026-05-16): mkdocs build performance targets.
#
# Baseline: full build of ~1,074 source .md → ~250 published pages = 2.74s
# (social plugin OFF, no --strict). CI continues to run --strict via the
# pages-preview.yml workflow; the dev-loop targets below trade strictness
# for iteration speed.
#
# - `make docs`        clean build, no strict (warnings non-fatal)
# - `make docs-fast`   incremental --dirty build (only rebuilds changed pages,
#                      skips social plugin which needs cairo arm64 on macOS).
#                      Typical: <1s on hot cache, ~2.5s cold.
# - `make docs-strict` mirrors the CI gate (--strict + social plugin on).
#                      Use before merging doc changes that touch nav/links.
#
# All three honour the MKDOCS_SOCIAL_ENABLED env var (default true). Set to
# false locally to skip the cairo-dependent social card generation that is
# broken under macOS Rosetta. CI sets it to true (via Linux runner) so OG
# images are still emitted for every published page.
MKDOCS ?= .venv/bin/mkdocs

docs:
	$(MKDOCS) build

docs-fast:
	@echo "[docs-fast] incremental build (--dirty); social plugin OFF for arm64-mac compat"
	MKDOCS_SOCIAL_ENABLED=false $(MKDOCS) build --dirty

docs-strict:
	$(MKDOCS) build --strict
