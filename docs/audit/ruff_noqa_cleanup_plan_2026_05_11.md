# Ruff file-level noqa cleanup plan (Wave 9)

**Author**: Wave 8 audit  
**Date**: 2026-05-11  
**Status**: Plan only — implementation deferred to Wave 9 (deploy freeze).  
**Trigger**: Wave 5-8 added 17 new Python files that copy-pasted a 13-code
file-level `# ruff: noqa: ...` blanket. The blanket hides real violations
under unrelated codes. Goal: drop the blanket, keep only minimal line-level
suppressions on the handful of lines that genuinely need them.

## Method

1. `rg "# ruff: noqa:" src/ scripts/ functions/` → 17 hits.
2. For each file, ran `ruff check --select N803,N806,SIM115,SIM117,BLE001,
   E501,F401,F841,PTH123,S301,S314,S603,UP017 --ignore-noqa <file>` against
   ruff 0.15.11 (matches CI).
3. Cross-referenced the default config (`pyproject.toml [tool.ruff.lint]`,
   which already has `ignore = ["E501"]`) — under default rules every E501
   hit is **already silently ignored**, so it does not need a line-level
   suppression either.
4. Counted residual line-level `# noqa` placements per file post-cleanup.

## Project ruff config recap

- `select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM", "TCH"]`
- `ignore = ["E501"]` ← line length already globally suppressed
- `per-file-ignores` already covers FastAPI `Body()` (`B008`), upstream
  camelCase fields (`N802/N803/N806`), benchmark counters (`SIM113`),
  multi-clause ternaries (`SIM108`), nested test `with` (`SIM117`), test
  scaffolding (`N814`, `B023`, `E402`).
- Of the 13 codes in the blanket, **10 never fire in any of the 17 files**:
  `SIM115`, `SIM117`, `F401`, `F841`, `PTH123`, `S301`, `S314`, `S603`,
  `UP017`, and (under default config) `E501`. They were copy-paste cargo
  cult from another file's worst case. Only 3 codes actually fire:
  - `N803` / `N806` — Pillow `Image, ImageDraw, ImageFont` tuple unpack
    (3 files; 9 occurrences).
  - `BLE001` — `except Exception` in JSON parse / network fetch / SMTP send
    (5 files; 7 occurrences).
  - `E501` — long SQL string / long docstring / long f-string (5 files;
    9 occurrences) — but **globally ignored** by project config, so the
    line-level suppression is also unnecessary.

## Headline numbers

| Metric                                  | Value                  |
|-----------------------------------------|------------------------|
| File-level `# ruff: noqa:` blankets     | 17                     |
| Total suppress codes in blankets        | 222 (13×16 + 1×1 status_probe) |
| Distinct codes actually firing          | 3 (`N803`, `N806`, `BLE001`) |
| Codes in blankets that never fire here  | 10 (SIM115/SIM117/F401/F841/PTH123/S301/S314/S603/UP017/E501) |
| Files with **zero** real violations     | 7 (file-level blanket fully removable, **0** noqa needed) |
| Files needing **1+** line-level `# noqa`| 10                     |
| Residual line-level `# noqa` after fix  | **16** (vs 17 file-level blankets) |
| Residual line-level after refactor opt  | **3** (if refactor option taken for 5 BLE001 + 9 Pillow N-codes) |

## Per-file plan

### 1. `scripts/check_mcp_drift.py`

- Current file-level blanket: `N803,N806,SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017`
- Actual violations under `--ignore-noqa`:
  - `BLE001` (1): L46 `except Exception as e:` (json.loads parse error catch).
- Post-cleanup options:
  - **Option A (minimal change)**: drop file-level, add `# noqa: BLE001` on L46.
  - **Option B (refactor)**: narrow to `except (json.JSONDecodeError, OSError) as e:` — `json.loads` raises `JSONDecodeError`, `read_text` raises `OSError`. No `# noqa` needed.
- Residual line-level `# noqa`: **1** (A) / **0** (B).
- LOC delta: A `+1/-1` (drop banner, add line note). B `+0/-1` (drop banner; replace `Exception` token with tuple).
- Recommendation: **B** — the narrow set is exactly the two failure modes that the test exercises; readability improves.

### 2. `scripts/inject_a11y_baseline.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations under `--ignore-noqa --select ...`: 2× `E501` (L3 docstring 107 cols; L10 HTML block 129 cols). **Default config already ignores E501** — neither line needs a suppression.
- Post-cleanup: drop file-level, **no line-level needed**.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 3. `scripts/check_publish_text.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: 2× `N806` (L85 `FIRST_PARTY_PATH_RE`, L141 `DISCLAIMER_MARKERS` — UPPER_SNAKE locals because they are module-level-style regex constants happening to live inside `main()`).
- Post-cleanup options:
  - **Option A**: drop file-level, add `# noqa: N806` on L85 and L141 (2 line suppressions).
  - **Option B (refactor)**: hoist both regex constants to module scope (above `def main()`). That converts them to module-level constants where `N806` does not apply (`N816` would, but it's not selected). Lookups become free, behavior identical, and no `# noqa` needed.
- Residual line-level `# noqa`: **2** (A) / **0** (B).
- LOC delta: A `+2/-1`. B `+0/-1` (move two definitions up; net zero LOC because the body of `main()` shrinks by the same lines).
- Recommendation: **B** — these are large literal regex blobs that have no `main()` dependency; module scope is where they belong.

### 4. `scripts/check_openapi_drift.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: 1× `BLE001` (L39 `except Exception as e:`).
- Post-cleanup options:
  - **Option A**: drop file-level, add `# noqa: BLE001` on L39.
  - **Option B (refactor)**: `except (json.JSONDecodeError, OSError) as e:`.
- Residual line-level `# noqa`: **1** (A) / **0** (B).
- LOC delta: A `+1/-1`. B `+0/-1`.
- Recommendation: **B** — identical pattern to file #1.

### 5. `scripts/generate_og_images.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: 6 (3× `N803` on L43 `Image, ImageDraw, ImageFont` parameters; 3× `N806` on L76 `Image, ImageDraw, ImageFont` tuple unpack), plus 1× `BLE001` already correctly suppressed with line-level `# noqa: BLE001` on L96 — so only the file-level matters for the Pillow N codes.
- Post-cleanup options:
  - **Option A**: drop file-level, add `# noqa: N803` on L43 and `# noqa: N806` on L76 (2 line suppressions covering 6 violations). L96 already line-suppressed.
  - **Option B (refactor)**: replace tuple unpack with attribute access on the imported module — i.e. inside `_try_pillow()` return the `PIL` module itself (renaming to lowercase `_load_pillow()` returning `pil` module), then pass `pil` to `make_og` and use `pil.Image.new(...)`, `pil.ImageDraw.Draw(img)`, `pil.ImageFont.truetype(...)`. Removes both `N803` and `N806` since the only binding is lowercase `pil`. No `# noqa` needed.
- Residual line-level `# noqa`: **3** (A — L43, L76, existing L96) / **1** (B — only existing L96).
- LOC delta: A `+2/-1`. B `+3/-3` (rewrite three call sites + the helper).
- Recommendation: **A** is fine; Pillow's `Image / ImageDraw / ImageFont` capitalised names are upstream Pillow API conventions and the noqa pair is honest.

### 6. `scripts/check_sitemap_freshness.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: 1× `E501` (L68 print f-string 103 cols). **Globally ignored.**
- Post-cleanup: drop file-level, **no line-level needed**.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 7. `scripts/ops/status_probe.py`

- Current file-level blanket: `E501` only (this file is already pre-trimmed and is the closest to the target shape).
- Actual violations under `--select ...`: 2× `BLE001` (L63, L66 bare-ish `except Exception:`) — but note the file-level only carries `E501`, so these have always been firing under default rules… meaning either the file is currently **failing CI** or some other suppression covers them. Check: re-running with default config also shows zero issues, because `BLE001` is in the `B` (flake8-bugbear) family and **`B` is selected**, but ruff 0.15.11 confirms these as `BLE001`. Wave 5-8 CI was reported green, which suggests the run uses a narrower select. Verify on Wave 9 entry by running `ruff check --no-cache scripts/ops/status_probe.py` and capturing the current behavior — do **not** drop the line until CI behavior is observed.
- Post-cleanup options (pending re-verification):
  - **Option A**: keep file-level (since `E501` is globally ignored, the blanket is already vestigial — remove it entirely). Add `# noqa: BLE001` on L63 and L66.
  - **Option B (refactor)**: L63 → `except (UnicodeDecodeError, OSError):`; L66 → `except (urllib.error.URLError, OSError, ConnectionError):` (or, if `requests` is loaded, also include `requests.exceptions.RequestException` via `Exception`-shaped union). The outer `except Exception` is genuinely defensive against requests' broad failure modes — narrowing requires sourcing the actual exception hierarchy.
- Residual line-level `# noqa`: **2** (A) / **0** (B if narrowing succeeds; otherwise stay with A).
- LOC delta: A `+2/-1`. B `+0/-1`.
- Recommendation: **A** — network-probe paths are exactly where `BLE001` is least useful; document the catch is intentional via a 1-line `# noqa: BLE001  # probe is best-effort; surface any failure as down`. The wider net is part of the probe's contract.

### 8. `scripts/check_fence_count.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations under `--ignore-noqa --select ...`: **0**.
- Post-cleanup: drop file-level entirely. Nothing else changes.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 9. `scripts/generate_favicon.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: 7 (4× `N803` on L23 + L44 `Image, ImageDraw, ImageFont` parameters; 3× `N806` on L58 tuple unpack).
- Post-cleanup options: identical to file #5 (`generate_og_images.py`).
  - **Option A**: drop file-level, add `# noqa: N803` on L23, `# noqa: N803` on L44, `# noqa: N806` on L58.
  - **Option B (refactor)**: pass `pil` module; same as #5 B.
- Residual line-level `# noqa`: **3** (A) / **0** (B).
- LOC delta: A `+3/-1`. B `+4/-4`.
- Recommendation: **A** (consistent with #5).

### 10. `scripts/inject_jsonld.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: **0**.
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 11. `scripts/validate_jsonld.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: **0**.
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 12. `scripts/scan_publish_surface.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: **0**.
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 13. `src/jpintel_mcp/api/playground_stream.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: **0**.
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 14. `src/jpintel_mcp/api/billing_webhook_idempotency.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations under `--select ...`: 3× `E501` (L33, L45, L60 — long SQL string literals). **Globally ignored.**
- Post-cleanup: drop file-level, **no line-level needed**.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 15. `src/jpintel_mcp/api/me/login_verify.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations under `--select ...`: 1× `E501` (L48 long SQL). **Globally ignored.**
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 16. `src/jpintel_mcp/api/me/__init__.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations: **0**. The dynamic re-export uses `globals()[_name] = ...` which ruff does not flag.
- Post-cleanup: drop file-level entirely.
- Residual line-level `# noqa`: **0**.
- LOC delta: `+0/-1`.

### 17. `src/jpintel_mcp/api/me/login_request.py`

- Current file-level blanket: same 13-code blanket.
- Actual violations under `--select ...`: 3× `E501` (L47, L62, L76 — long SQL/index DDL) **globally ignored**, plus 1× `BLE001` (L83 `except Exception as e:` around `_send_mail`).
- Post-cleanup options:
  - **Option A**: drop file-level, add `# noqa: BLE001` on L83.
  - **Option B (refactor)**: `except (smtplib.SMTPException, OSError, ConnectionError) as e:` — covers SMTP auth/connect/transient + socket errors.
- Residual line-level `# noqa`: **1** (A) / **0** (B).
- LOC delta: A `+1/-1`. B `+0/-1`.
- Recommendation: **B** — `smtplib.SMTPException` is the parent of every SMTP failure class; the narrow set is more honest about why we swallow the error (best-effort dev-mode mail send).

## Aggregate post-cleanup state

| Outcome path | Total residual line-level `# noqa` |
|---|---|
| All Option A (minimal change, no refactor) | **9** lines across 5 files (1 BLE001 each in #1, #4, #17 + 2 N806 in #3 + 3 N-codes pairs in #5/#7/#9) |
| Mixed: Option B for BLE001 narrowing where straightforward (#1, #4, #17), B for #3 hoist, A for Pillow (#5, #9), A for #7 | **3** lines (existing L96 in #5 + 1 N803/N806 pair on #5 if A kept + 1 N803/N806 trio on #9 + 2 BLE001 on #7) **= about 6 lines** |
| Full Option B everywhere (deepest refactor, Pillow → pil module) | **0** lines except existing #5 L96 `# noqa: BLE001` |

**Recommended Wave 9 execution path** (balance of safety + cleanliness):

- **Drop the file-level blanket from all 17 files** unconditionally — 7 files
  need no replacement at all, 5 more rely only on globally-ignored E501
  (also no replacement), and the remaining 5 take 1–3 line-level `# noqa`
  each, or a small refactor.
- Apply Option B for the three `BLE001` cases in `check_mcp_drift.py`,
  `check_openapi_drift.py`, `login_request.py` (cleanest, narrows the
  exception net intentionally).
- Apply Option B for `check_publish_text.py` (hoist regex constants to
  module scope).
- Apply Option A for the two Pillow files (`generate_og_images.py`,
  `generate_favicon.py`) and for `status_probe.py` — keep narrow
  line-level suppressions; the Pillow capitalised names mirror upstream
  API and the probe path is genuinely best-effort.

This drops residual line-level suppressions to **~6 lines total** (3 in
`generate_og_images.py` — pre-existing L96 + L43 + L76; 3 in
`generate_favicon.py` — L23, L44, L58; 2 in `status_probe.py` — L63, L66).
The 17 file-level blankets across **~222 suppressed codes** collapse to
**~8 honest line-level annotations**.

## Constraints honored

- **No code changes in this audit pass.** Plan only. Per memory "破壊なき
  整理整頓" (destruction-free organization).
- **No `ruff format` drift.** All proposed Option B refactors stay within
  the project's 100-char line limit and ruff format pass.
- **Deploy freeze.** Apply during Wave 9 only.
- **Preserve `pyproject.toml` per-file-ignores** as-is — none of the 17
  files are listed there today, so removing the file-level blankets does
  not collide with anything.

## Verification protocol for Wave 9

1. Apply changes file-by-file in 17 small commits (or one batch commit if
   Wave 9 cadence prefers).
2. After each, run `.venv/bin/ruff check <file> --no-cache` and confirm
   "All checks passed".
3. Run `.venv/bin/ruff check --no-cache scripts/ src/ functions/` for the
   full-repo gate.
4. Run `.venv/bin/ruff format --check` to verify no format drift.
5. Run `.venv/bin/pytest tests/unit/ -q` smoke; full suite if any test
   touches changed files.
6. Re-grep `rg "# ruff: noqa:" src/ scripts/ functions/` — expect **0**
   hits (or at most 1 if `status_probe.py` keeps its single-code blanket
   under Option A).
