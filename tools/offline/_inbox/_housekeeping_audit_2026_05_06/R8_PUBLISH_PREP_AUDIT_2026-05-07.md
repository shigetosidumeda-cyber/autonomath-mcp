# R8 — Publish-Prep Audit (post-launch SDK / DXT / Smithery / MCP-Registry sync)

- **Date**: 2026-05-07
- **Scope**: read-only audit of npm SDK + DXT + Smithery + MCP Registry surfaces ahead of post-launch publish
- **Mode**: read-only (no manifest edits — Option B "manifest hold-at-139" preserved)
- **PyPI v0.3.4 publish path**: handled by a separate agent (release.yml + tag `v0.3.4`)
- **Internal hypothesis framing**: maintained — no claims of a launched / verified state are added beyond what the manifests already declare

---

## 1. Manifest version sync table

| # | Surface                                  | File path                                                                 | Declared version | tool_count                | repo / pkg name                                      | Notes                                                                          |
|---|------------------------------------------|---------------------------------------------------------------------------|------------------|---------------------------|------------------------------------------------------|--------------------------------------------------------------------------------|
| 1 | DXT (.mcpb)                              | `dxt/manifest.json`                                                       | **0.3.4**        | embedded `tools[]` = 139  | name `autonomath-mcp`, repo `shigetosidumeda-cyber/autonomath-mcp` | display_name `jpcite — 日本の制度 API`; description states "139 tools"        |
| 2 | Smithery                                 | `smithery.yaml`                                                           | **0.3.4**        | description text "139 tools" | repo `shigetosidumeda-cyber/autonomath-mcp`         | uvx command `autonomath-mcp`; envs JPCITE_API_* + AUTONOMATH_API_* (legacy aliases) |
| 3 | MCP Registry (FQN, server.json)          | `server.json`                                                             | **0.3.4**        | `_meta.tool_count = 139`  | FQN `io.github.shigetosidumeda-cyber/autonomath-mcp` | pypi pkg `autonomath-mcp` v0.3.4 stdio; auth header `X-API-Key`                |
| 4 | MCP discovery manifest                   | `mcp-server.json`                                                         | **0.3.4**        | description text "139 tools" + tools[] embedded | name `autonomath-mcp`                                | served at `https://jpcite.com/mcp-server.json` per `manifest_url`              |
| 5 | PyPI / api source                        | `pyproject.toml`                                                          | **0.3.4**        | (n/a)                     | distribution `autonomath-mcp`                        | top-level pyproject; PyPI publish = release.yml (separate agent)               |

### Sub-surfaces (npm SDKs + plugins)

| # | Surface                       | File path                                                  | Declared version | npm name                  | publishConfig                       | Notes                                                                  |
|---|-------------------------------|------------------------------------------------------------|------------------|---------------------------|-------------------------------------|------------------------------------------------------------------------|
| A | npm SDK — minimal client      | `sdk/npm-package/package.json`                             | **0.1.0**        | `@bookyou/jpcite`         | `access: public`                    | first-publish; fresh package; deliberate v0.1.0 baseline                |
| B | npm SDK — typed client        | `sdk/typescript/package.json`                              | **0.3.2**        | `@autonomath/sdk`         | `access: public`                    | last-bumped at v0.3.2; **lags** main package by two patches (0.3.2 → 0.3.4) |
| C | npm SDK — Agent SDK starter   | `sdk/agents/package.json`                                  | **0.1.1**        | `@jpcite/agents`          | `access: public`                    | independent semver track; tags `agents-v*`                              |
| D | freee marketplace plugin      | `sdk/freee-plugin/marketplace/package.json`                | **0.2.0**        | `jpcite-freee-plugin` (private) | `private: true`                | not published to npm; submitted to freee marketplace separately         |
| E | freee marketplace submission  | `sdk/freee-plugin/marketplace/submission/manifest.json`    | (no version field — uses `manifest_version: 1`) | freee app `jpcite` | (n/a)                            | submission manifest; brand `jpcite`; OAuth read-only                    |
| F | MF Cloud submission           | `sdk/mf-plugin/submission/manifest.json`                   | `manifest_version: 1` | MF app `jpcite`        | (n/a)                               | submission manifest; brand `jpcite`; OAuth `mfc/ac/data.read` only      |

---

## 2. Drift findings (read-only — flagged, not patched)

1. **Top 5 manifests fully synced at v0.3.4 with tool_count = 139.** No drift on the canonical surfaces (DXT / Smithery / server.json / mcp-server.json / pyproject.toml). This matches the "Option B manifest hold-at-139" plan — runtime cohort 146 is intentionally not surfaced in manifests.
2. **`@autonomath/sdk` (sdk/typescript/package.json) trails main version by 2 patches (0.3.2 vs 0.3.4).** Description text still cites legacy "11,684 searchable programs" rather than the canonical 11,601. Mitigation choice (out of scope for this audit): bump sdk-ts to 0.3.4 in a follow-up commit + cut tag `sdk-ts-v0.3.4`, OR keep on 0.3.2 because npm publish has not happened yet (tagging strategy decides — see §5).
3. **`@bookyou/jpcite` and `@autonomath/sdk` share semantic role but have different scope + version**, which is intentional but worth recording: `@bookyou/jpcite` is the new canonical npm SDK (v0.1.0, never published); `@autonomath/sdk` is the legacy track at v0.3.2 (also never published — `npm view` 404 per workflow comment in `sdk-publish.yml`).
4. **DXT manifest description string and Smithery description string both claim "139 tools".** Confirmed against `len(dxt/manifest.json.tools[])` = 139. No drift.
5. **`server.json` `_meta.tool_count = 139` matches the description.** Pricing block (`unit_price_jpy_ex_tax: 3` + `billing_unit: "billable_unit"`) reflects the codex handoff billable-unit fix (no `request` literal anywhere in the metered descriptors).
6. **No Smithery publish workflow exists.** Smithery pulls from GitHub on push to `main` per Smithery convention; `smithery.yaml` is the SOT. No GitHub Action is required (and none is missing).

---

## 3. Publish-workflow inventory

| Surface                    | Workflow file                                          | Triggers                                                   | Notes                                                                                                            |
|----------------------------|--------------------------------------------------------|------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| PyPI (main package)        | `.github/workflows/release.yml`                        | tag push `v*` / `workflow_dispatch`                        | Trusted Publishing via OIDC (no PyPI token); test gate uses pinned `PYTEST_TARGETS`; followed by GitHub Release  |
| npm — Python+TS SDKs       | `.github/workflows/sdk-publish.yml`                    | tag push `sdk-python-v*` / `sdk-ts-v*` / `workflow_dispatch` (target=python\|ts\|both) | Publishes `@autonomath/sdk` (TS) and Python SDK from `sdk/python/`; uses `NPM_TOKEN` + `--access public --provenance`; OIDC fallback |
| npm — `@jpcite/agents`     | `.github/workflows/sdk-publish-agents.yml`             | tag push `agents-v*` / `workflow_dispatch`                 | Has an explicit auth-preflight step distinguishing token vs OIDC trusted-publishing; chicken-and-egg seed step documented |
| MCP Registry               | `.github/workflows/mcp-registry-publish.yml`           | `workflow_dispatch` only (incl. `validate_only` flag)      | Uses `mcp-publisher` CLI + `github-oidc` login; namespace `io.github.shigetosidumeda-cyber/autonomath-mcp`        |
| Smithery                   | (none — git-pull from main)                            | (none)                                                     | Smithery convention; smithery.yaml is the SOT and is read on cadence by Smithery itself                          |
| DXT (.mcpb upload)         | (no workflow — operator builds locally + uploads)      | (none)                                                     | dxt/manifest.json is consumed by `claude-desktop` install path; bundle hosted at `https://jpcite.com/downloads/autonomath-mcp.mcpb` (per mcp-server.json `install.alt.claude_desktop`) |
| trust-center / others      | `trust-center-publish.yml`, `practitioner-eval-publish.yml` | (out of scope for this audit)                          | Not part of the npm/DXT/Smithery/MCP-Registry post-launch path                                                   |

All four canonical publish workflows are wired with the expected dual triggers (tag push + `workflow_dispatch`). MCP Registry is `workflow_dispatch`-only, by design (no namespace-tag-bot pattern).

---

## 4. Publish plan (sequence — read-only proposal, not executed)

Assumed order, with the PyPI track owned by a separate agent:

1. **PyPI v0.3.4** (separate agent): tag `v0.3.4` → release.yml (test → build → publish-pypi → github-release).
2. **MCP Registry v0.3.4**: `gh workflow run mcp-registry-publish.yml -f validate_only=false` after PyPI 0.3.4 is `pip install`-able (the registry validates that the pypi pkg + version exist).
3. **npm `@bookyou/jpcite` v0.1.0** (first-publish): manual one-shot `npm publish --access public` from `sdk/npm-package/`. No tag-driven workflow exists for this scope yet; pattern matches the `@jpcite/agents` chicken-and-egg seed step. Then configure trusted-publisher and switch subsequent bumps to a tag-driven path.
4. **npm `@autonomath/sdk` v0.3.4 (or v0.3.2)**: decide between (a) bump to 0.3.4 to match main, then `git tag sdk-ts-v0.3.4 && git push --tags` (sdk-publish.yml runs), or (b) keep v0.3.2, since the package has never been published (per `sdk-publish.yml` operator-runbook header). Either is internally consistent — flagging the choice rather than forcing it.
5. **npm `@jpcite/agents` v0.1.1**: `git tag agents-v0.1.1 && git push --tags` (sdk-publish-agents.yml runs). Auth-preflight will detect the chicken-and-egg if no NPM_TOKEN secret is present.
6. **Smithery**: passive — push to `main` (no tag, no workflow). Smithery picks up the new commit + reads `smithery.yaml` on its next pull.
7. **DXT**: operator-side — `python -m build` + bundle `dxt/manifest.json + icon.png + README.md` into `.mcpb`, upload to `https://jpcite.com/downloads/autonomath-mcp.mcpb`. No CI step.

No surface needs a manifest patch before publish at v0.3.4. The single open decision is the `@autonomath/sdk` bump-or-skip in step 4, which is a tagging-strategy call, not a sync-drift call.

---

## 5. Hypothesis framing — what this audit does NOT prove

- This audit does NOT prove that the publish workflows succeed end-to-end. It proves that: (a) the five canonical manifests declare matching v0.3.4 + 139 tools, (b) the four canonical publish workflows exist with the expected triggers, (c) no Smithery workflow is needed.
- This audit does NOT prove the runtime cohort. CLAUDE.md asserts runtime = 146 with manifest hold-at-139 — verified by `len(await mcp.list_tools())` per CLAUDE.md instructions, not by this audit.
- This audit does NOT cover trademark / brand-rename surface drift beyond what's in the manifests. The repo / pypi / DXT package names remain `autonomath-mcp` (legacy), with user-facing display names already on `jpcite`. That's intentional and matches CLAUDE.md guidance ("never rename `src/jpintel_mcp/`"; PyPI distribution stays `autonomath-mcp`).
- The codex handoff billable-unit fix is reflected in `server.json._meta.pricing` and Smithery `configSchema.properties.jpciteApiKey.description` — both use `billable_unit` / `課金単位`, not `request`. Verified visually; no programmatic linter run in this audit.

---

## 6. Next-action gates

- [ ] Decide tagging strategy for `@autonomath/sdk`: bump to v0.3.4 to match, or keep v0.3.2 (never-published track).
- [ ] Configure `NPM_TOKEN` repo secret OR operator one-shot seed publish for both `@bookyou/jpcite` and `@autonomath/sdk` (chicken-and-egg same as `@jpcite/agents`).
- [ ] Confirm PyPI 0.3.4 lands before triggering `mcp-registry-publish.yml` (registry validates pypi pkg+version exist).
- [ ] After PyPI lands: `gh workflow run mcp-registry-publish.yml`.
- [ ] After all npm + MCP Registry land: build + upload `.mcpb` for DXT.

End of R8 publish-prep audit.
