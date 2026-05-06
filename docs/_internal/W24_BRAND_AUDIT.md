---
title: W24 — Brand audit (jpcite / autonomath-mcp / jpintel)
updated: 2026-05-05
operator_only: true
category: brand
companion: docs/_internal/W19_github_rename_diff.md
---

# W24 — Brand audit

Non-destructive grep audit of the 3 brand names. No edits made.

## Convention table

| Surface                         | Allowed brand                          | Note                                       |
| ------------------------------- | -------------------------------------- | ------------------------------------------ |
| `site/**` user-visible HTML     | **jpcite** only                        | except PyPI install lines (`autonomath-mcp`) |
| `README.md` / `CHANGELOG.md`    | **jpcite** only (history excepted)     | CHANGELOG retains historical brand names  |
| `docs/**` non-`_internal/` md   | **jpcite** only (mkdocs-rendered)      | renders into `site/docs/` (currently clean) |
| `pyproject.toml` / `dist/` / twine | **autonomath-mcp** retain           | PyPI distribution name (legacy)            |
| Python `import` paths           | **jpintel_mcp** retain                 | breakage risk; never rename                |
| GitHub slug (`shigetosidumeda-cyber/...`) | **jpcite-mcp** target (W19 pending) | repo rename not yet executed              |

## User-visible jpintel violations (7)

`site/` HTML — must rename to jpcite-equivalent surface labels.

| File:line | String | Severity | Suggested fix |
| --- | --- | --- | --- |
| `site/stats.html:453` | `["laws_jpintel", "laws (法令)"]` (metric key) | low (data-key) | rename key to `laws_jpcite` or `laws_core` (also update producer JSON) |
| `site/en/stats.html:232` | `["laws_jpintel", "laws"]` | low | same as above |
| `site/status/index.html:382` | `<tr id="row-db-jpintel" ...>` | low (DOM id) | rename id to `row-db-programs` |
| `site/status/index.html:617` | `var programsKey = "db_" + "jpintel_reachable";` | medium (status payload key) | coordinate with `/v1/status` producer; rename to `programs_reachable` |
| `site/status/index.html:624` | `rowMap[programsKey] = "row-db-jpintel";` | low | follow the row-id rename |
| `site/status/index.html:677` | `paintRow("row-db-jpintel", ...)` | low | follow the row-id rename |
| `site/security/index.html:211` | `<code>scripts/cron/backup_jpintel.py</code>` (visible to user reading /security) | medium (filename leak) | rename script + reference, or relabel as `backup_programs.py` (CLAUDE.md script name freeze applies) |

## User-visible AutonoMath / Autonomath / autonomath.ai violations (0)

- `site/**` AutonoMath count: **0**
- `README.md` AutonoMath count: **0**
- `CHANGELOG.md` AutonoMath: 9 hits — **all historical changelog entries** (acceptable per convention)
- `autonomath.ai` legacy domain: 3 hits in CHANGELOG.md only (historical, acceptable)
- `zeimu-kaikei.ai` legacy: 0 hits in `site/`, README

## User-visible autonomath (lowercase) hits

All `autonomath-mcp` hits in `site/` (~70 occurrences across `dashboard.html`, `trial.html`, `success.html`, `integrations/*.html`, `docs/cookbook/*`, `compare/*`) are PyPI package install / `uvx` / GitHub URL slug strings — **retained per convention** (PyPI distribution name).

One soft hit:

| File:line | String | Severity | Suggested fix |
| --- | --- | --- | --- |
| `site/audiences/shokokai.html:228` | `50 が autonomath 拡張` (Japanese prose using "autonomath" as brand label) | medium | rephrase to `50 が拡張ツール群` or `50 が jpcite 拡張ツール` |

## Internal: incorrect `jpcite` Python imports (0)

`grep -rn "from jpcite\." src/` and `grep -rn "import jpcite$" src/` returned **0 actual import violations**. Two `src/` matches were copy strings inside HTML email bodies (English sentence "from jpcite") in `subscribers.py:165` and `email_unsubscribe.py:90` — **correct user-facing brand usage**, not Python imports.

## W19 GitHub slug rename (pending, separate from brand audit)

13 canonical `shigetosidumeda-cyber/autonomath-mcp` occurrences across 9 files (pyproject.toml, server.json, README.md, mcp-server*.json, smithery.yaml, dxt/manifest.json) **all still bear the old slug**. Per W19_github_rename_diff.md, this is the single sed migration awaiting the GitHub repo rename event. Not a brand-audit failure (separate W19 track).

## Migration progress (delta vs W19 brand rename)

| Axis | Baseline (W19, 2026-04-30 capture) | Now (W24, 2026-05-05) | % done |
| --- | --- | --- | --- |
| User-visible AutonoMath strings (site + README) | non-zero | 0 | **100%** |
| User-visible jpintel leakage (site only) | unknown ≥7 | 7 | unchanged (estimated **0–10%**) |
| `zeimu-kaikei.ai` legacy in user-visible | non-zero | 0 | **100%** |
| `autonomath.ai` legacy in user-visible | non-zero | 0 (CHANGELOG only) | **100%** |
| GitHub slug rename (W19 canonical 13) | 13 | 13 | **0%** (gated on repo rename) |
| Python `from jpcite.X` mis-imports | 0 (assumed) | 0 | **n/a (clean)** |

Aggregate: brand convention compliance is **strong on the AutonoMath / domain axes (100%)**, **weak on residual jpintel DOM/key leaks (7 hits)**, and **untouched on the W19 GitHub slug** (separate track).

## Recommended next-step packets (non-blocking)

1. `site/status/index.html` + `site/stats.html` + `site/en/stats.html` — rename `jpintel` data-keys / DOM ids to `programs` / `core`. Coordinate with the JSON producer if `programs_reachable` payload key changes.
2. `site/security/index.html` — relabel cron script identifier, OR keep filename and add a footnote mapping `backup_jpintel.py = programs DB backup`.
3. `site/audiences/shokokai.html:228` — soft rephrase of `autonomath 拡張` to `jpcite 拡張ツール`.
4. W19 sed (1-shot) once GitHub repo rename is executed.
