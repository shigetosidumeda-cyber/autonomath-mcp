# Distribution Manifest CI Guard — Operator Manual

Source of truth: `scripts/distribution_manifest.yml`.
Origin: `docs/_internal/value_maximization_plan_no_llm_api.md` §28.3 + §28.10
priority 6 — eliminate drift across README / MCP Registry / DXT / Smithery /
SDK / `llms.txt`.

## What it guards

The manifest pins one canonical value per distribution attribute, so every
downstream surface (PyPI metadata, MCP registry manifest, DXT bundle,
Smithery config, SDK, marketing site, README, docs) cannot silently disagree.
Per §28.9 No-Go #6, drift between these surfaces is treated as a launch
blocker — AI crawlers and MCP registries cannot resolve "which value is
canonical?" once they start to see different numbers / domains / package
names per surface.

Pinned attributes:

| field                            | example value                              |
|----------------------------------|--------------------------------------------|
| `product`                        | `jpcite`                                   |
| `canonical_domains.site`         | `https://jpcite.com`                       |
| `canonical_domains.api`          | `https://api.jpcite.com`                   |
| `canonical_mcp_package`          | `autonomath-mcp` (PyPI name)               |
| `canonical_pypi_package`         | `autonomath` (sdk/python name)             |
| `canonical_repo`                 | `shigetosidumeda-cyber/autonomath-mcp`     |
| `canonical_api_env.api_key`      | `JPCITE_API_KEY`                           |
| `canonical_api_env.api_base`     | `JPCITE_API_BASE`                          |
| `tool_count_default_gates`       | runtime `len(mcp._tool_manager.list_tools())` |
| `route_count`                    | runtime `len(app.routes)`                  |
| `pyproject_version`              | `pyproject.toml [project] version`         |
| `tagline_ja`                     | the canonical 1-line Japanese tagline      |
| `forbidden_tokens`               | strings that MUST NOT appear in user-facing files |
| `forbidden_token_exclude_paths`  | paths where the forbidden tokens are intentional historical context |

## Two-tier check

1. **Static drift scan** — `scripts/check_distribution_manifest_drift.py`
   Pure file scan. Runs in <1 s. Verifies every distribution surface in the
   `SURFACES` list either references the canonical values OR (for
   `forbidden_tokens`) does not contain any legacy strings outside the
   excluded paths. Output is a pretty table of `(field, expected, file,
   observed, status)` rows. Exit 1 on any drift.

2. **Runtime probe** — `scripts/probe_runtime_distribution.py`
   Imports `jpintel_mcp.api.main:app` + `jpintel_mcp.mcp.server:mcp` and
   confirms the live tool / route counts match the manifest. Slow (~6 s
   cold) because it boots the FastAPI app and FastMCP server in-process.

The two are paired in CI (`.github/workflows/distribution-manifest-check.yml`)
and run on every push + PR.

## When to update `distribution_manifest.yml`

Update the manifest BEFORE bumping any downstream surface. The downstream
surfaces are then updated to match.

| trigger                             | fields to update                                           |
|-------------------------------------|------------------------------------------------------------|
| Release tag (e.g. `v0.3.2`)         | `pyproject_version`                                        |
| New tool added at default gates     | `tool_count_default_gates` (and `tagline_ja` if mentions tools) |
| New route added                     | `route_count`                                              |
| Domain change                       | `canonical_domains.site` / `canonical_domains.api`         |
| Package rename                      | `canonical_mcp_package` / `canonical_pypi_package`         |
| Repo rename or org claim            | `canonical_repo`                                           |
| Env-var rename                      | `canonical_api_env.api_key` / `canonical_api_env.api_base` |
| Brand rebrand                       | `product` + add the OLD brand to `forbidden_tokens`        |

After bumping the manifest, run:

```bash
.venv/bin/python scripts/check_distribution_manifest_drift.py
```

The output enumerates every downstream surface that needs updating. The
script intentionally does NOT auto-fix — see "Why no auto-apply?" below.

## Local commands

```bash
# Static drift scan (pure file scan; ~0.2 s)
.venv/bin/python scripts/check_distribution_manifest_drift.py

# Drift scan with suggested edits (still does NOT auto-apply)
.venv/bin/python scripts/check_distribution_manifest_drift.py --fix

# Runtime probe (boots the API + MCP server; ~6 s cold)
.venv/bin/python scripts/probe_runtime_distribution.py

# Tests
.venv/bin/pytest tests/test_distribution_manifest.py -v
```

## Why no auto-apply?

Per `docs/_internal/value_maximization_plan_no_llm_api.md` §28.9 + the
operator memory `feedback_dont_extrapolate_principles`, the drift checker
discovers state but does NOT correct it. Fixing drift correctly often
requires rewriting paragraphs (e.g. "139-tool MCP" prose in
`scripts/mcp_registries_submission.json` is more than just changing a number; the
surrounding "38 core + 28 autonomath" breakdown is also stale and needs a
fresh count). A naive replace would corrupt the document.

## Failure mode triage

| symptom                                                  | likely cause                                                  | fix                                                                                                              |
|----------------------------------------------------------|---------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| `manifest not found`                                     | running from outside the repo root                            | run from `$REPO_ROOT` or pass `--manifest /abs/path`                                                             |
| `tool_count_default_gates` drift on every surface        | runtime gained or lost a tool without a manifest bump         | bump the manifest, then update the surfaces                                                                      |
| `tool_count_default_gates` drift on the runtime probe    | `verify_citations` or another gated tool flipped state        | re-verify the gate envs; cold-boot probe in a fresh shell                                                        |
| `route_count` drifts non-deterministically               | import order matters — `api.main` before `mcp.server` adds extra side-effect tools | always probe with MCP-first order (the probe enforces this)               |
| forbidden token in a file you intentionally added        | new file references the legacy brand                          | either rewrite the file with the canonical brand, or add the path prefix to `forbidden_token_exclude_paths`      |
| static check passes but probe fails                      | docs/manifests are consistent with each other but stale       | bump the manifest to the runtime values; re-run the static check; fix the surfaces                              |
| both checks pass locally, fail in CI                     | `.venv` cache stale on the GHA runner                         | bust the cache by editing `pyproject.toml` (any small change) or rerun the workflow                              |

## Files

- `scripts/distribution_manifest.yml` — canonical hand-edited source of truth
- `scripts/check_distribution_manifest_drift.py` — static-file drift scan
- `scripts/probe_runtime_distribution.py` — runtime introspection
- `scripts/distribution_manifest_README.md` — this file
- `tests/test_distribution_manifest.py` — pytest coverage (4 tests)
- `.github/workflows/distribution-manifest-check.yml` — CI gate
- `analysis_wave18/distribution_drift_2026-04-30.md` — first audit run findings
