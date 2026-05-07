---
title: R8 — Brand consistency deep audit (jpcite vs autonomath / jpintel-mcp drift)
date: 2026-05-07
session: R8
predecessor: docs/_internal/W24_BRAND_AUDIT.md (2026-05-05)
operator_only: true
category: brand
---

# R8 — Brand consistency deep audit (2026-05-07)

Re-verification of brand drift after the 2026-04-30 `AutonoMath → jpcite` user-facing rename. This audit walks every user-visible surface (`site/`, `docs/`, `README`, `CHANGELOG`, manifests, well-known) plus internal stable paths and confirms which `autonomath` / `jpintel` / `AutonoMath` strings are intentional retention vs actual drift.

W24 audit (2026-05-05) had already classified the surface set; this R8 pass confirms current state and lands a small set of trivial clarifying fixes.

## 1. Convention table (carried from W24, unchanged)

| Surface                                        | Allowed brand                          | Note                                                        |
| ---------------------------------------------- | -------------------------------------- | ----------------------------------------------------------- |
| `site/**` user-visible HTML                    | **jpcite** only                        | except PyPI install lines (`autonomath-mcp` legacy retain)  |
| `README.md` / `CHANGELOG.md` body              | **jpcite** only                        | CHANGELOG keeps historical brand strings in pre-rename rows |
| `docs/**` non-`_internal/` md (mkdocs source)  | **jpcite** only                        | renders into `site/docs/`                                   |
| `pyproject.toml` `[project.name]` / `dist/`    | **autonomath-mcp** retain              | PyPI distribution name (legacy, never rename)               |
| Python `import` paths (`src/jpintel_mcp/`)     | **jpintel_mcp** retain                 | every external consumer breaks if renamed; never touch      |
| GitHub repo slug                               | **autonomath-mcp** (W19 rename pending)| separate W19 track                                          |
| `widget/autonomath.{css,js,src.*}`             | retain                                 | legacy embedder backward-compat assets — keep alongside     |
| `Autonomath` global (`window.Autonomath`)      | retain (alias)                         | embedder backward-compat alongside `window.Jpcite`          |
| `AUTONOMATH_*` env vars / settings names       | retain                                 | internal stable (env API contract; CLAUDE.md gate names)    |
| `autonomath.db` filename + `am_*` SQL tables   | retain                                 | physical infrastructure name; can't rename                  |
| `scripts/cron/backup_autonomath.py` etc.       | retain                                 | internal stable; CLAUDE.md script-name freeze applies       |
| `autonomath_router`, `autonomath_tools/`       | retain                                 | source path stable                                          |

## 2. Surface walk results

### 2.1 site/ user-facing HTML — AutonoMath drift

```
grep -rn 'AutonoMath\|Autonomath' site/ | filter -v <legitimate> => 0 hits
```

The 3 remaining `AutonoMath` strings under `site/` are intentional:

| File:line                              | String                                                        | Status                                                  |
| -------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------- |
| `site/llms-full.txt:2`                 | `Brand history: ... (旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai)` | Intentional brand-history disclosure for LLM consumers |
| `site/llms-full.en.txt:2`              | same (English)                                                | Intentional                                             |
| `site/.well-known/trust.json:20`       | `"previous_brands": ["AutonoMath", "jpintel-mcp", ...]`       | Intentional `well-known` trust registry                 |
| `site/widget/autonomath.{js,src.js}`   | `root.Autonomath = root.Autonomath \|\| {};` (alias)          | Backward-compat global for legacy embedders            |

### 2.2 site/ user-facing HTML — `autonomath` (lowercase) drift

```
grep -rn -i 'autonomath' site/ | filter -v 'autonomath-mcp\|widget\|env\|file' => trace below
```

All hits classified:

| Pattern                                    | Count (approx) | Class                              |
| ------------------------------------------ | -------------- | ---------------------------------- |
| `autonomath-mcp` (PyPI / uvx / GitHub URL) | ~70            | Legitimate package name retain     |
| `AUTONOMATH_*` env var names               | a few          | Legitimate env-var stable          |
| `autonomath.css` / `.js` / widget asset    | a few          | Legitimate backward-compat asset   |
| `backup_autonomath.py` / `weekly-backup-`  | ~2             | Legitimate internal script name    |
| `autonomath.db` / `am_*` table mention     | a few          | Legitimate DB filename / SQL ref   |
| `autonomath_router`, `autonomath canonical id` | a few      | Internal source path / ID space    |
| `autonomath.citation_sample`               | 1              | Internal log table                  |
| `["db", "autonomath", "reachable"]`         | 1 (status/index.html:619) | Backward-compat fallback key for /v1/status payload (line 634-636 falls back to legacy key shape if API returns the old name) |
| Soft prose `autonomath 拡張`                | 0              | W24 fix already landed              |

### 2.3 README.md / CHANGELOG.md

- README: every `autonomath-mcp` mention is annotated as "package name kept for client compatibility" (line 198). 0 brand drift.
- CHANGELOG: 9 historical AutonoMath strings + 3 historical autonomath.ai mentions, all in pre-2026-04-30 release notes. Acceptable per convention.

### 2.4 docs/ (mkdocs source) — AutonoMath drift

```
grep -rn 'AutonoMath\|Autonomath' docs/*.md docs/api-reference docs/cookbook docs/blog => 0 hits
```

Internal-only `docs/_internal/` documents may reference AutonoMath (history); not rendered to users.

`docs/improvement_loop.md`, `docs/registries.md`, `docs/long_term_strategy.md`, `docs/launch_announcement_calendar.md` mention `autonomath-mcp` (PyPI), `autonomath.db` (file), `@autonomath/sdk` (npm) — all legitimate.

### 2.5 External manifests (server.json / mcp-server.json / smithery.yaml / dxt/manifest.json)

| File                          | Brand value                                              | Status                                  |
| ----------------------------- | -------------------------------------------------------- | --------------------------------------- |
| `server.json`                 | `"name": "io.github.shigetosidumeda-cyber/autonomath-mcp"` | Legitimate (PyPI / GitHub slug)         |
| `mcp-server.json`             | `"name": "autonomath-mcp"` + `"homepage": "https://jpcite.com"` | Legitimate; jpcite as the brand surface |
| `dxt/manifest.json`           | `"name": "autonomath-mcp"`                               | Legitimate (PyPI bundle)                |
| `smithery.yaml`               | dual `jpciteApiKey` (canonical) + `autonomathApiKey` (legacy alias) | Clean dual-name pattern             |
| `site/.well-known/mcp.json`   | `"name": "autonomath-mcp"` + `"install": "uvx autonomath-mcp"` | Legitimate                              |
| `site/.well-known/trust.json` | `"previous_brands": ["AutonoMath", ...]`                 | Intentional brand-history registry      |

### 2.6 Internal stable paths confirmed (do NOT rename)

Per CLAUDE.md "Never rename `src/jpintel_mcp/`":

```
src/jpintel_mcp/                 retain (Python import path; PyPI consumers depend on it)
pyproject.toml [project.name]    retain (autonomath-mcp = PyPI distribution name)
console_scripts                   autonomath-api / autonomath-mcp (entry points)
autonomath.db (root + data/)      retain (SQLite file path)
am_* table prefix                 retain (DB schema)
AUTONOMATH_* env vars             retain (operator contract; gate names)
scripts/cron/backup_autonomath.py retain (script-name freeze)
.github/workflows/weekly-backup-autonomath.yml retain
```

## 3. Drift found and classification

| # | Surface                                  | Drift                                                                  | Severity | Decision        |
| - | ---------------------------------------- | ---------------------------------------------------------------------- | -------- | --------------- |
| 1 | `site/widget/jpcite.js:14`               | DOM ID prefix `autonomath-f-` lingers in canonical jpcite widget       | low      | **fix → `jpcite-f-`** (legacy `autonomath.js` retains `autonomath-f-` for backward compat) |
| 2 | `site/audiences/dev.html:145`            | `(PyPI: autonomath-mcp)` lacks brand-clarification footnote           | low      | **fix → add inline "互換のため旧配布名を維持、ブランドは jpcite"** |
| 3 | `site/dashboard.html:216`                | quickstart prose has bare `pip install autonomath-mcp` with no jpcite-context inline | low | **fix → add "互換のため旧配布名を維持..." footnote** |
| 4 | `site/trial.html:192`                    | install prose lacks brand clarifier                                    | low      | **fix → add same clarifier**                                |
| 5 | `site/success.html:317`                  | install prose lacks brand clarifier                                    | low      | **fix → add same clarifier**                                |

W24 jpintel-leak items (`site/stats.html:453`, `site/en/stats.html:232`, `site/status/index.html:382/617/624/677`, `site/security/index.html:211`) — **out of scope for this R8 jpcite-drift audit**, tracked separately on the W24 follow-up packet (those are jpintel-axis, not jpcite-axis).

`site/audiences/shokokai.html:228` (`50 が autonomath 拡張`) — **already fixed** between W24 (2026-05-05) and R8 (2026-05-07). Current line reads `50 が jpcite 拡張`. Confirmed via grep.

## 4. Fixes landed (5 files)

```
M site/widget/jpcite.js                  # DOM ID `autonomath-f-` → `jpcite-f-`
M site/audiences/dev.html                # add brand-clarification on PyPI mention
M site/dashboard.html                    # add brand-clarification on pip-install line
M site/trial.html                        # add brand-clarification on install prose
M site/success.html                      # add brand-clarification on install prose
```

All edits are additive Japanese clarifications adjacent to legitimate `autonomath-mcp` package-name mentions. No legitimate package name, env var, file path, or backward-compat alias was changed. The legacy `widget/autonomath.js` and its `autonomath-f-` IDs are intentionally untouched (different file, embedder backward compat).

### 4.1 Pre-commit / regression risk

- `site/widget/jpcite.js`: DOM ID `autonomath-f-` is referenced ONLY inside this same file (label `for=...` ↔ input `id=...`). No CSS selector, test, or external embedder snippet targets it. Safe rename. Verified via `grep -rn 'autonomath-f-' site/ tests/` — only 3 hits, all inside the widget src/min variants of the same logic.
- HTML clarifier insertions: pure prose append. No JS / CSS / test depends on the inserted Japanese phrase.

## 5. Out-of-scope (deferred / separate track)

- **W19 GitHub slug rename** — `shigetosidumeda-cyber/autonomath-mcp` → `shigetosidumeda-cyber/jpcite-mcp` is a single-shot sed migration gated on the GitHub repo rename event itself. 13 occurrences across 9 files. Not touched in R8.
- **jpintel DOM/key leaks** in `site/stats.html`, `site/status/index.html`, `site/security/index.html` — separate brand axis (jpintel, not jpcite). Tracked on W24 follow-up packet items 1-3.
- **CHANGELOG historical entries** — preserved as-is per convention (history is not drift).

## 6. Final compliance picture (R8 close)

| Axis                                             | Baseline (W24, 2026-05-05) | R8 (2026-05-07) |
| ------------------------------------------------ | -------------------------- | --------------- |
| `site/**` user-visible AutonoMath drift          | 0                          | 0 (re-verified) |
| `site/**` user-visible `autonomath` non-package  | 1 (shokokai prose)         | 0 (fixed)       |
| `site/**` widget DOM-ID consistency              | drift (`autonomath-f-` in canonical widget) | 0 (renamed to `jpcite-f-`) |
| `site/**` install-prose brand clarifier coverage | partial (1/4 audience pages had it) | 4/4 covered (dev / dashboard / trial / success) |
| Internal stable path / package name retention    | 100%                       | 100% (untouched) |
| External manifest brand alignment                | aligned                    | aligned (re-verified) |

**Verdict**: jpcite vs AutonoMath user-facing brand consistency is now at functional 100%. Remaining `autonomath` strings under `site/` are exclusively legitimate retain (PyPI / env / file / backward-compat asset / DB schema). No actions required before next manifest bump.
