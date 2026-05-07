# R8 — SBOM Generation (2026-05-07)

**Status:** SHIPPED — local generation verified, monthly cron wired, public index published.
**Operator:** Bookyou株式会社
**Product:** jpcite v0.3.4
**Spec:** CycloneDX 1.4 (JSON)
**Audit cohort:** R8 (post-launch supply-chain transparency)

## What landed

| Artifact                                                                  | Purpose                                                                | Owned by                       |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------ |
| `scripts/cron/generate_sbom.py`                                           | One-shot SBOM regenerator (pip + npm + docker shards + index)          | new                            |
| `.github/workflows/sbom-publish-monthly.yml`                              | Monthly GHA cron (1st of month 02:30 JST) + manual dispatch (`syft`)   | new                            |
| `site/.well-known/sbom.json`                                              | Public aggregated index (`jpcite_sbom_index_v1` schema, CC0-1.0)       | new                            |
| `site/.well-known/sbom/sbom-pip.cyclonedx.json`                           | Main pyproject runtime — 203 components                                | new                            |
| `site/.well-known/sbom/sbom-sdk-freee.cyclonedx.json`                     | freee plugin transitive deps — 11 components                           | new                            |
| `site/.well-known/sbom/sbom-sdk-mf.cyclonedx.json`                        | mf plugin transitive deps — 24 components                              | new                            |
| `site/.well-known/sbom/sbom-npm-typescript.cyclonedx.json`                | `@autonomath/sdk` declared deps — 2 components                         | new                            |
| `site/.well-known/sbom/sbom-npm-agents.cyclonedx.json`                    | `@jpcite/agents` declared deps — 4 components                          | new                            |
| `site/.well-known/sbom/sbom-npm-jpcite.cyclonedx.json`                    | `@bookyou/jpcite` declared deps — 3 components                         | new                            |
| `site/.well-known/sbom/sbom-npm-vscode-extension.cyclonedx.json`          | `jpcite-vscode` declared deps — 4 components                           | new                            |
| `site/.well-known/sbom/sbom-docker-base.cyclonedx.json`                   | `python:3.12-slim-bookworm` declared component (deep scan opt-in)      | new                            |

**Totals at 2026-05-07T09:23:23Z:** 8 shards, **252 components**, CycloneDX 1.4, 0 known vulnerabilities (pip-audit OSV + PyPI advisory DB sweep).

## Decisions

1. **`pip-audit --format=cyclonedx-json` over `cyclonedx-bom`.**
   `pip-audit` is already pinned in `.venv`, supports CycloneDX 1.4 natively, and folds the vulnerability sweep into the same dependency walk. Adding `cyclonedx-bom` would duplicate the graph traversal for no extra signal. Auditors can reproduce verbatim by running the same `pip-audit` invocation logged in the workflow.

2. **Plugin reqs walked transitively, not `--no-deps`.**
   `sdk/freee-plugin` and `sdk/mf-plugin` ship `requirements.txt` (unhashed). Running `pip-audit -r ... --disable-pip` requires `--no-deps` and would emit only the 2/6 declared lines, missing the actual security-critical transitive surface (httpx / starlette / pydantic-core / click / etc.). Letting `pip-audit` invoke pip in a temp venv adds ~10 s per plugin but yields the real graph.

3. **Docker = declared FROM only by default; syft is opt-in.**
   A full `syft python:3.12-slim-bookworm` scan emits ~85 apt packages and takes 7-10 minutes. The default monthly run keeps the Docker shard to one declared component (the base image PURL) so the cron stays under 5 minutes. Auditors who want the apt graph trigger `workflow_dispatch` with `with_syft=true`. The shard is overwritten in place when syft runs.

4. **Public path = `site/.well-known/sbom*` (Cloudflare Pages-served).**
   `.well-known` is the canonical RFC 8615 location for trust artefacts; `security.txt` and `trust.json` already live there. Auditors fetch `https://jpcite.com/.well-known/sbom.json` first to discover the per-surface CycloneDX shards. The site `_headers` rules already serve `application/json` for `*.json` under `.well-known`, so no extra config was needed.

5. **No cosign / sigstore signing yet.**
   The launch context ("LLM 0", solo + zero-touch) and the fact that all shards are committed to the main branch (which is itself signed by repo policy: GitHub commit-signing + tag protection) makes a separate sigstore attestation chain redundant. If the cron migrates off-runner (e.g. to a dedicated build node) and the commit-signing chain weakens, this decision should be revisited.

6. **Index file licensed CC0-1.0.**
   The aggregated index is metadata about metadata; restricting it would defeat its purpose. Per-shard licensing follows each upstream package's declared license, surfaced inside the CycloneDX `licenses` field where the upstream populates it.

## Verification (local 2026-05-07)

```text
$ .venv/bin/python scripts/cron/generate_sbom.py
jpcite SBOM generator v1.0.0
  repo_root = /Users/shigetoumeda/jpcite
  out_dir   = site/.well-known/sbom
  dry_run   = False
  ...
Done. 8 shards, 252 total components.
```

CycloneDX shape spot-check on the main pip shard:

```json
{
  "$schema": "http://cyclonedx.org/schema/bom-1.4.schema.json",
  "bomFormat": "CycloneDX",
  "specVersion": "1.4",
  "components": [ /* 203 entries */ ]
}
```

No `pip-audit` vulnerability findings on the live `.venv` snapshot (post Wave 23 starlette CVE-2025-62727 + python-multipart CVE-2026-42561 fixes).

## Failure modes & mitigations

| Risk                                                              | Mitigation                                                              |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `pip-audit` exits 1 because of a fresh CVE                        | Script tolerates rc∈{0,1} and still emits the SBOM; CI logs WARN line   |
| pyproject relaxes a cap and a transitive disappears               | `Verify shape` step asserts `component_count >= 100`; fails the run     |
| Cloudflare Pages mis-routes `.well-known/sbom/*` MIME             | `site/_headers` already pins `application/json` to `*.json` under root  |
| Aggregator (e.g. dependency-track) caches a stale shard           | Index `generated_at` + per-shard `sha256` make staleness detectable     |
| Syft slow path times out the 20-min job                           | `with_syft` is opt-in only; default monthly path stays declared-only    |
| Pre-commit hook rejects new SBOM JSON for being too large         | `check-added-large-files` cap is 500 KB; largest shard is 35 KB         |
| Future LLM-touched edit drifts the schema                         | This script imports zero LLM SDKs — covered by `tests/test_no_llm_*`    |

## Cadence

- **Default:** monthly, 1st of month 17:30 UTC (= 02:30 JST 2nd of month).
- **Manual:** `workflow_dispatch` with `with_syft=true` for deep apt scan, or `dry_run=true` to preview without committing.
- **Triggered regen:** none — schedule + manual only. Hooking PR push into SBOM regen produces excessive churn for tree changes that don't touch dependencies.

## Out of scope (R8 closed; future R9+ candidates)

- **sigstore / cosign attestation chain** (deferred — see decision 5).
- **`syft` always-on** (deferred — see decision 3).
- **SLSA Level 3 build provenance** (orthogonal — would require runner pinning + ephemeral key).
- **Dependency-Track / OWASP DT integration** (auditor-side; the public shards already ingest cleanly).
- **SPDX 2.3 secondary export** (CycloneDX 1.4 is the only spec we publish; SPDX consumers can convert externally).

## Files (absolute paths)

- `/Users/shigetoumeda/jpcite/scripts/cron/generate_sbom.py`
- `/Users/shigetoumeda/jpcite/.github/workflows/sbom-publish-monthly.yml`
- `/Users/shigetoumeda/jpcite/site/.well-known/sbom.json`
- `/Users/shigetoumeda/jpcite/site/.well-known/sbom/` (8 CycloneDX shards)
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_SBOM_GENERATION_2026-05-07.md` (this file)

## Closure

R8 SBOM generation lane is closed. Public supply-chain transparency surface is live; downstream auditors can fetch a single index and pull the per-surface CycloneDX 1.4 shards verbatim. Monthly cron will keep the index fresh without operator touch.
