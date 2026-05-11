# Asset Naming Leak Red-Team Audit — jpcite site/ + functions/

- **Date**: 2026-05-11
- **Scope**: `site/**` HTML / CSS / JS / assets + `functions/**` `.ts`
- **Lens**: SV top-tier (Stripe / Vercel / Anthropic) brand-clean CSS class / id / data-* / asset-filename hygiene
- **Method**: `rg`-based grep of 8 forbidden codename tokens, false-positive sweep, public-API-path carve-out

## Forbidden codename inventory

| Token | Hit files | Hit lines | Status |
|---|---|---|---|
| `autonomath` / `AutonoMath` | **58** | **411** | **HEAVY LEAK** (widget + PyPI link + env var + brand bridge) |
| `jpintel` / `JpIntel` | **2** | **4** | Minimal — `_redirects` 301 + `contribute/scrubber.js` comment |
| `zeimu-kaikei` | 0 | 0 | Clean (brand-history bridge comment only in `llms*.txt`, not class/id) |
| `wave-` / `wave_` | 0 (CSS/JS/HTML) | 0 | Clean |
| `am-` prefix | **2** (CSS) + **2** (JS) | **77** | **CRITICAL LEAK** (feedback FAB widget) |
| `bc666` | 0 | 0 | Clean |
| `unified_registry` / `unified-registry` | 0 | 0 | Clean |
| `subagent` / `agent-dispatch` / `fix-pack` | 0 | 0 | Clean |

Public API path `/v1/am/*` (e.g. `/v1/am/health/deep`, `/v1/am/annotations/*`) is a **shipped contract** — labelled separately as `breaking-change-on-rename` and **excluded from CSS/JS/asset-name severity scoring** per task spec.

## 1. CSS class names with forbidden prefix

**Severity: HIGH** — These ship to every visitor's browser and are visible in DevTools, leaking the legacy "AutonoMath" codename.

### 1a. `am-fb-*` feedback widget (22 unique class names)

| file:line | sample | severity |
|---|---|---|
| `site/styles.src.css:1253-1254` | `.am-feedback-trigger,\n  .am-feedback-close {` | **HIGH** |
| `site/styles.src.css:1618-1619` | duplicate block (print-media) | **HIGH** |
| `site/styles.src.css:1743,1749` | `/* (6) mkdocs Material — feedback FAB (.am-fb-fab) */ ... .am-fb-fab {` | **HIGH** |
| `site/styles.css:1` (minified bundle) | `.am-feedback-trigger,.am-feedback-close` inline | **HIGH** |
| `site/assets/feedback-widget.src.js:19-64` | `STYLE_ID = "am-fb-style"; ".am-fb-fab{...}"...` 22 unique selectors | **HIGH** |
| `site/assets/feedback-widget.js` | minified mirror, identical surface | **HIGH** |

**Unique selectors leaked**: `am-fb-fab`, `am-fb-backdrop`, `am-fb-bd`, `am-fb-btn`, `am-fb-btn-p`, `am-fb-btn-s`, `am-fb-cat`, `am-fb-count`, `am-fb-dialog`, `am-fb-email`, `am-fb-err`, `am-fb-ft`, `am-fb-hd`, `am-fb-kbd`, `am-fb-lbl`, `am-fb-msg`, `am-fb-ok`, `am-fb-root`, `am-fb-style`, `am-fb-text`, `am-fb-title`, `am-fb-x`, `am-feedback-trigger`, `am-feedback-close`.

The `am-` prefix is the legacy AutonoMath shorthand — a Stripe/Vercel/Anthropic-grade audit would flag these as brand-leak.

### 1b. `autonomath-widget` embed-widget BEM ladder (~40 unique class names)

| file:line | sample | severity |
|---|---|---|
| `site/widget/autonomath.src.css:24-263` | `.autonomath-widget { ... }` + 40 BEM modifiers (`__form`, `__row`, `__field`, `__label`, `__input`, `__select`, `__submit`, `__status`, `__error`, `__results`, `__item`, `__name`, `__meta`, `__tag`, `__amount`, `__actions`, `__link`, `__footer`, `--dark`) | **HIGH** |
| `site/widget/autonomath.css` | minified mirror | **HIGH** |
| `site/widget/autonomath.src.js:112-156` | `STYLE_ID = "autonomath-widget-style"`; full BEM ladder repeated inline as injected `<style>` | **CRITICAL** |
| `site/widget/autonomath.js` + `site/widget/jpcite.js` | minified + dual-name distributions, byte-identical class strings | **CRITICAL** |

`site/widget/autonomath.src.css:13-17` even **documents the leak inline**: "to override the `.autonomath-widget-*` class names without editing the JS" — i.e. the legacy prefix is a public surface contract for embed customers.

## 2. id attribute leaks (HTML / JS)

No HTML `id="autonomath..."` / `id="am-..."` found. **PASS.**

The JS sets `STYLE_ID = "autonomath-widget-style"` (`site/widget/*.js:115`) and `STYLE_ID = "am-fb-style"` (`site/assets/feedback-widget*.js:19`) — these become `<style id="...">` injected into the host DOM. Severity: **HIGH** (visible in customer DevTools when widget mounts).

## 3. data-* attribute leaks

| file:line | sample | severity |
|---|---|---|
| `site/widget/jpcite.js:277,560,563` | `"data-autonomath-widget-mounted": "true"` set on mounted element + `document.querySelectorAll("[data-jpcite-widget], [data-autonomath-widget]")` accepted as auto-mount selector | **CRITICAL** |
| `site/widget/autonomath.js:277,560,563` | same surface in legacy-named distribution | **CRITICAL** |
| `site/widget/autonomath.src.js:277,560,563` | source mirror | **CRITICAL** |
| `site/integrations/gemini.html:179` | `<div class="code-block" data-code="uvx autonomath-mcp">` (plus 6 other integrations pages: cline / cursor / windsurf / claude-desktop / integrations/index) | **MEDIUM** (it is the PyPI package name, but `data-code` is an arbitrary internal attribute that bakes the legacy string in HTML) |

`data-autonomath-widget` and `data-autonomath-widget-mounted` are the auto-mount contract. New `data-jpcite-widget` was added but the legacy attribute is still queried for backwards compatibility — same leak class as 1b.

## 4. JS variable / function names

No top-level `function autonomathFoo()` / `const Autonomath = ...` / `class Autonomath {...}` declarations were found in `site/**.js`. JS exposes the widget under the **`Jpcite.Widget`** global (clean).

Internal string constants are the leak:
- `STYLE_ID = "autonomath-widget-style"` (`site/widget/{jpcite.js,autonomath.js,autonomath.src.js}:115`) — **HIGH**.
- `STYLE_ID = "am-fb-style"` (`site/assets/feedback-widget{.js,.src.js}:19`) — **HIGH**.
- `if (el.getAttribute("data-autonomath-widget-mounted") === "true")` (`site/widget/*.js:563`) — **HIGH**.

No leak in top-level `analytics.js`, `dashboard.js`, `dashboard_v2.js`, `dashboard_init.js`, `assets/prescreen-demo.js`, `assets/trust-strip.js`, `assets/public-counts.js`, `contribute/scrubber.js` (verified clean).

## 5. Filename / asset-path leaks

| path | severity |
|---|---|
| `site/widget/autonomath.css` | **CRITICAL** — file name is the codename |
| `site/widget/autonomath.src.css` | **CRITICAL** |
| `site/widget/autonomath.js` | **CRITICAL** |
| `site/widget/autonomath.src.js` | **CRITICAL** |
| `site/widget/jpcite.js` | **clean** (dual-name shipped 2026-04-30 rename) |

Widget directory is dual-named: both `autonomath.{js,css}` and `jpcite.js` live side-by-side because customer embed snippets still point at the legacy filename and `_redirects` does **not** rewrite. SV top-tier would deprecate the legacy filename via 301 to `/widget/jpcite.{js,css}` and ship only the new name.

**No images, no SVG icons, no favicons carry forbidden codenames.** `site/assets/brand/*.png`, `mark.svg`, `logo.svg`, `og.png`, favicon variants are all brand-clean. **PASS.**

## 6. Internal path exposure in HTML attributes

| file:line | sample | severity |
|---|---|---|
| `site/index.html:112` | `"https://pypi.org/project/autonomath-mcp/"` in JSON-LD `sameAs` | **MEDIUM** (this is the canonical PyPI URL — public contract; downgrade to `breaking-change-on-rename` not "leak") |
| `site/dashboard.html:295,309,322` + `site/trial.html:261,549` + `site/success.html:392,596,609` | `"command": "autonomath-mcp"` + `pip install autonomath-mcp` in setup snippets, **always accompanied by `(互換のため旧配布名を維持、ブランドは jpcite)` legacy-marker copy** | **LOW** (existing memory note `feedback_legacy_brand_marker.md` — controlled exposure with bridge text) |
| `site/llms.txt:68-117` + `site/llms.en.txt:148` | `uvx autonomath-mcp`, `https://jpcite.com/downloads/autonomath-mcp.mcpb?src=...` | **LOW** (same: bridge contract, customer copy-paste path) |
| `site/mcp-server.json:13,20,23,32` + `site/mcp-server.full.json:13,20,23,32` + `site/server.json:3,7,15` | registry manifests with `identifier: "autonomath-mcp"`, GitHub URL `shigetosidumeda-cyber/autonomath-mcp` | **CRITICAL on rename, LOW today** (npm/PyPI/GitHub identifiers are immutable contracts) |
| `site/mcp-server.json:339,403` + `.full.json` | tool description **prose** includes `policy: feedback_autonomath_no_api_use` and `autonomath.intake.<known>` python_dispatch namespace | **HIGH** — these are **internal memory keys / Python module paths** leaking into customer-readable JSON, not just the legacy PyPI name |
| `site/connect/cursor.html:173`, `connect/claude-code.html:173`, `connect/codex.html:124`, `legal-fence.html:359,365` | `AUTONOMATH_36_KYOTEI_ENABLED` env-var flag name surfaced to end users | **MEDIUM** — env-var name leaks legacy codename in customer docs |
| `site/_redirects:124-126` | `/jpintel /` 301 redirects — **public-friendly** (this is the cleanup, not the leak) | **PASS** |
| `site/contribute/scrubber.js:3` | comment `// Mirrors src/jpintel_mcp/api/contribute.py` — exposes internal Python package path | **LOW** (comment, but visible in source-view) |

## SV top-tier comparison

| operator | CSS prefix style | leak hygiene |
|---|---|---|
| **Stripe** (`stripe.com` / Stripe.js) | `.PaymentInputContainer`, `.AppLoaderShell`, BEM never includes codenames | Internal codenames (`Atlas`, `Connect`, project-X) never appear in customer-loaded CSS. |
| **Vercel** | `[data-geist-...]`, `.next-...` — design-system or framework prefixes only | Internal Edge/Turbopack experiment names are stripped at bundling. |
| **Anthropic** (`claude.ai` / API console) | `.claude-...`, `.anthropic-...` brand-prefixed | Internal project codenames (`Sonnet`, `Opus` model IDs) appear only in public model strings, never CSS / data-attrs. |

jpcite's current state — `.autonomath-widget-*`, `.am-fb-*`, `data-autonomath-widget-mounted`, `STYLE_ID="autonomath-widget-style"` — is **2 brand-eras behind**: legacy codename leaks into 40+ unique CSS class names + 22 unique `am-fb-*` selectors + 2 widget JS auto-mount attributes. A red-team observer landing on `view-source:jpcite.com/dashboard.html` would conclude "this product used to be called AutonoMath" within 5 seconds of opening DevTools.

## Top-5 immediate-fix CSS class renames

(rename proposals; per memory **"破壊なき整理整頓"** do **NOT** apply destructively — ship as additive aliases first, deprecate legacy in 6-month follow-on)

| # | Current class | Proposed rename | Why |
|---|---|---|---|
| 1 | `.autonomath-widget` + 39 BEM children (`__form`, `__row`, …, `--dark`) in `site/widget/autonomath.src.css` + injected by `widget/{jpcite,autonomath}.js` | `.jpcite-widget` + same BEM ladder | Most-visible leak — every embed customer's HTML shows `class="autonomath-widget"`. Ship `.jpcite-widget` as additive class on the same element, document both for 1 release, deprecate legacy. |
| 2 | `.am-fb-fab`, `.am-fb-dialog`, `.am-fb-backdrop`, `.am-feedback-trigger`, `.am-feedback-close` (22 unique `am-fb-*` selectors) | `.jp-fb-*` / `.jpcite-feedback-*` | `am-` prefix exists across `styles.{src.,}css` + `assets/feedback-widget{.,src.}js`. Single-source rename in feedback-widget.src.js + styles.src.css; rebuild minified bundles. |
| 3 | `STYLE_ID = "autonomath-widget-style"` (`widget/*.js:115`) | `STYLE_ID = "jpcite-widget-style"` | Visible as `<style id="...">` injected into customer DOM. One-line change × 3 files; backward-compat via dual-injection. |
| 4 | `data-autonomath-widget-mounted` + `[data-autonomath-widget]` auto-mount attribute (`widget/*.js:277,560,563`) | `data-jpcite-widget-mounted` + accept both selectors in the auto-mount querySelector | New attribute is already in querySelector — finish the rename by setting only the new attribute on mount; keep legacy in querySelector for 6 months. |
| 5 | `site/widget/autonomath.{js,css,src.js,src.css}` filenames | Keep `site/widget/jpcite.{js,css}` as canonical; add `_redirects`: `/widget/autonomath.js /widget/jpcite.js 301` | Filenames in URL path leak codename to every CDN log + customer `<script src="...">` snippet. Dual-shipped today; finish the cutover via `_redirects`. |

## Additional CRITICAL-on-rename items (not in top-5, listed for completeness)

- `site/mcp-server.json:339,403` + `.full.json` — tool description JSON contains literal text `policy: feedback_autonomath_no_api_use` and `autonomath.intake.<known>`. **These are internal memory keys and Python module paths bleeding into customer-readable registry manifests.** Strip from description copy before next manifest bump (independent of brand rename — these are pure hygiene defects).
- `AUTONOMATH_36_KYOTEI_ENABLED` env-var name appearing in 4 customer-facing HTML pages (`connect/{cursor,claude-code,codex}.html`, `legal-fence.html`) — env-var contract leak. Either rename env var (`JPCITE_36_KYOTEI_ENABLED`) and ship dual-read in Python, or stop quoting the env-var name in customer docs.
- PyPI package name `autonomath-mcp` + GitHub URL `shigetosidumeda-cyber/autonomath-mcp` + `.mcpb` filename — **rename = breaking change** for every existing customer's `claude_desktop_config.json`. Defer to a future major-version rev; today these are correctly accompanied by `(互換のため旧配布名を維持、ブランドは jpcite)` legacy-marker copy per `feedback_legacy_brand_marker.md`.

## Public-API-path carve-out (NOT scored as leak)

Routes under `/v1/am/*` (`/v1/am/health/deep`, `/v1/am/annotations/{id}`, `/v1/am/validate`, `/v1/am/provenance/*`, `/v1/am/static/*`, `/v1/am/example_profiles/*`, `/v1/am/templates/saburoku_kyotei`) are **shipped public contract** with OpenAPI / MCP-registry manifests pointing at them. Renaming = breaking change × every API/MCP customer. Excluded from severity rollup; flagged for a future v0.4.0 path-deprecation cycle if user wants it.

## Constraint compliance

- **"破壊なき整理整頓"**: All renames above are proposals; this audit writes only this single new file at `docs/audit/asset_naming_leak_redteam_2026_05_11.md`. No `site/` mutations, no `rm`, no `mv`.
- **Public API contract**: `/v1/am/*` paths labelled `breaking-change-on-rename` and excluded from internal-CSS-class severity scoring per spec.
