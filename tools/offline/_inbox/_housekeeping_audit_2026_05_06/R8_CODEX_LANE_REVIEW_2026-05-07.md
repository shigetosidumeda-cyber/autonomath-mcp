# R8 — Codex Lane Review (2026-05-07)

**Reviewer:** session A (jpcite v0.3.4 housekeeping operator)
**Scope:** all `[lane:codex]` commits landed on `origin/main` in the last 24h.
**Verdict:** PASS — 7/7 commits clean, no regressions to deploy chain, billing fail-closed, business-law disclaimer envelope, or LLM-0 budget. One micro-tightening noted (advisory only).

---

## 1. Codex commit list (24h, oldest → newest)

| # | SHA | Subject | Files | LoC |
|---|-----|---------|-------|-----|
| 1 | da88049 | ci: commit site openapi mirrors | 2 (site/docs/openapi/{agent,v1}.json) | +46861 |
| 2 | a3bdaaf | test: align acceptance openapi threshold | 1 (tests/fixtures/acceptance_criteria.yaml) | +2/-2 |
| 3 | 0d9e5cb | test: review time machine audit seal calls | 1 (tests/test_audit_seal_static_guard.py) | +1 |
| 4 | f28bb65 | bench: annotate composite result provenance | 4 (benchmarks + scripts/etl + scripts/ops + docs) | +148/-50 |
| 5 | d905426 | test: isolate credit pack admin settings | 1 (tests/test_credit_pack.py) | +15/-5 |
| 6 | 31cbe20 | test: isolate cron admin settings | 1 (tests/test_cron_heartbeat.py) | +6/-2 |
| 7 | 98e8b1d | test: isolate admin auth settings | 2 (test_admin.py, test_testimonials.py) | +12/-4 |

All 7 are surgical single-purpose commits. No drive-by edits.

---

## 2. Per-commit review

### 2.1 da88049 — site openapi mirror (CI)

- **What:** First-time commit of `site/docs/openapi/agent.json` (442 KB, 13327 LoC) and `v1.json` (1.04 MB, 33534 LoC) into the static site tree.
- **Test coverage:** N/A (artifact mirror). Generation script lives upstream (already covered).
- **Disclaimer integrity:** verified — top of `v1.json` carries the verbatim `税理士法 §52 fence` description block including `_disclaimer` envelope hint and PDL v1.0 attribution mention. Agent subset description explicitly states "does not call external LLM APIs".
- **Bug check:** OK. Mirror serves `site.jpcite.com` static docs. No build-time path collision (`site/docs/openapi/` previously empty).
- **Concern:** large binary-ish JSON in git → site bundle size. Already an accepted pattern (jpcite ships docs).
- **Verdict:** clean.

### 2.2 a3bdaaf — acceptance openapi threshold

- **What:** `DEEP-39-1` route count threshold lowered `min_count: 200 → 184`, banner updated `route 240 promo → stable OpenAPI public surface`.
- **Sanity check:** current `docs/openapi/v1.json` route count = **192**. New floor 184 leaves 8-route headroom for trims; old 200 floor would FAIL today (192 < 200). Codex correctly observed acceptance test was red.
- **Threat model:** could mask an unintended route-deletion regression. Mitigation: 184 is still a hard floor — accidental drop below 184 still trips the gate. Recommend tightening back to 188 once route count stabilizes.
- **Verdict:** clean (acceptance fix); advisory note logged.

### 2.3 0d9e5cb — time_machine audit seal allowlist

- **What:** added `src/jpintel_mcp/api/time_machine.py: 2` to `_REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS`.
- **AST verify (independent):** I ran `ast.walk` over `time_machine.py` with codex's exact predicate. **Confirmed = 2 calls** (lines 104, 172). Threshold is exact, not slack.
- **Spec compliance:** matches the `audit_seal_static_guard` policy ("new paid JSON surfaces should issue seals through strict log_usage; allow only after manual review"). Two seals are for `/v1/programs/{id}/timeline` + `/v1/programs/{id}/history` — both are legitimate paid JSON surfaces inherited from earlier `time_machine` route work.
- **Verdict:** clean.

### 2.4 f28bb65 — composite bench provenance annotator

- **What:** added 50-row `result_kind / wall_ms_kind / tokens_kind / cost_kind` quadruple to `benchmarks/composite_vs_naive/results.jsonl`; added `scripts/etl/annotate_composite_result_kind.py` (idempotent ETL); added README block; added `benchmarks/` to lane_policy.json (paths.runtime_code).
- **LLM-0 check:** annotator is pure stdlib (`json`, `pathlib`, `argparse`). No `anthropic`/`openai` import. `tokens_kind` and `cost_kind` are *flagged synth* — the explicit reframe ("token + USD columns are deterministic estimates") prevents false-claim risk in marketing material.
- **Honesty signal (good):** breakdown `real=1 / synth=20 / fallback=29` is published in the docs page. This *strengthens* the "internal hypothesis" framing — readers now know which numbers are live and which are calibrated.
- **lane_policy.json delta:** `benchmarks/` added to two `paths.runtime_code` entries (codex_lane + session_a presumably). Symmetric, non-exclusive.
- **Verdict:** clean. This is the single highest-value commit of the batch — it removes a long-standing audit risk (mixed real/synth bench rows without provenance flags).

### 2.5 d905426 — credit_pack settings monkeypatch isolation

- **What:** `monkeypatch.setattr(settings, ...)` → loop over `(settings, billing_mod.settings, admin_mod.settings)` for `stripe_secret_key`, `stripe_webhook_secret`, `stripe_price_per_request`, `admin_api_key`.
- **Root cause it solves:** `jpintel_mcp.api.admin` and `jpintel_mcp.api.billing` each `from jpintel_mcp.config import settings` at module top — that creates a *separate name binding* in each module's globals. Patching only `config.settings` left the two re-exported references stale, so handler code reading `settings.admin_api_key` got the un-patched value. This was a real test-pollution / fail-closed-bypass bug class.
- **Billing fail-closed regression check:** `test_create_invoice_503_when_admin_key_disabled` *asserts* Stripe is NOT hit when admin key is empty (`_should_not_be_called` raises). The fix MAKES this assertion meaningful — previously it could have silently passed because the handler still saw the un-patched key. **Net = stronger fail-closed coverage.**
- **Verdict:** clean and load-bearing. This is the second-highest-value commit.

### 2.6 31cbe20 — cron_heartbeat settings isolation

- **What:** identical pattern to 2.5, applied to `tests/test_cron_heartbeat.py` (`admin_enabled` fixture + `test_admin_cron_runs_503_when_admin_key_disabled`).
- **Verdict:** clean. Same root cause class.

### 2.7 98e8b1d — admin + testimonials settings isolation

- **What:** identical pattern, applied to `tests/test_admin.py` and `tests/test_testimonials.py`.
- **Verdict:** clean. Closes the test-pollution class across all four admin-touching test modules (admin, testimonials, cron, credit_pack).

---

## 3. Lane integrity vs. session A

| Surface | Codex touched? | Session A touched? | Conflict? |
|---------|----------------|---------------------|-----------|
| `.github/workflows/deploy.yml` | NO | YES (4 fixes 6e3307c→07986f9) | NONE — deploy fixes intact |
| `tools/offline/` | NO | YES | NONE |
| `tests/test_*` | YES (4 files) | NO | NONE |
| `src/jpintel_mcp/api/*` | NO (only allowlist) | NO this round | NONE |
| `site/docs/openapi/` | YES (mirror) | NO | NONE |
| `benchmarks/`, `scripts/etl/`, `scripts/ops/` | YES | NO | NONE |
| `docs/openapi/v1.json` | NO (only threshold yaml) | NO | NONE |

**Result:** zero overlap, zero overwrite. Codex stayed in `tests + benchmarks + ci-mirror + scripts/etl` as its lane policy declares.

---

## 4. Bug detections

**No bugs introduced.** Three mild advisories:

1. **a3bdaaf openapi floor.** 184 is permissive vs. current 192. If session A or codex removes a non-trivial cluster of routes (e.g. legacy `/v1/am/*` deprecation), the gate will not catch it until -8 routes accumulate. *Action:* consider raising back to 188 in next stabilization sweep — NOT blocking.

2. **f28bb65 lane_policy.json `benchmarks/` add.** Both the codex_lane block AND the session_a block now claim `benchmarks/`. This is symmetric so neither lane is locked out, but a future writer that *reads* `lane_policy.json` for exclusive routing may treat `benchmarks/` as ambiguous. *Action:* note for next lane-policy revision — NOT blocking.

3. **d905426/31cbe20/98e8b1d pattern.** The "loop over `(settings, billing_mod.settings, admin_mod.settings)`" pattern is repeated in 4 test files. Consider extracting into a `conftest.py` fixture `set_isolated_setting(name, value)` to prevent drift. *Action:* refactor candidate — NOT blocking.

---

## 5. LLM-0 + business-law disclaimer + billing fail-closed

| Invariant | Status | Evidence |
|-----------|--------|----------|
| LLM-0 (no `anthropic`/`openai` import in landed code) | OK | grep across all 7 commits returned 0 matches; bench annotator is stdlib only |
| `_disclaimer` envelope (税理士法 §52 fence) | OK | mirrored verbatim in `site/docs/openapi/v1.json`; description block intact |
| Billing fail-closed (`admin_api_key=""` → 503) | STRONGER | d905426 fixes silent-pass risk; `_should_not_be_called` Stripe assertions now meaningful |
| Daily budget/quota gates | UNTOUCHED | no codex commit modifies `billing/delivery.py`, `quota.py`, `db_quota.py` |
| Deploy chain (4 session A fixes) | INTACT | `git log -- .github/workflows/deploy.yml` shows zero codex touches |

---

## 6. Recommendation

ACCEPT all 7 commits as-landed. No revert/cherry-pick required. File the 3 advisories above into the next housekeeping wave.

---

*Reviewer signed: session A, 2026-05-07 JST.*
*Read-only review. No source/test/script files were modified during this audit.*
