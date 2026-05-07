# R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07)

Round-2 follow-up to `R8_DISCLAIMER_LIVE_VERIFY` (which fixed REST `_apply_envelope` drop on the `/v1/am/{acceptance_stats, enforcement, loans, mutual_plans}` route).
This round audits the **22-axis grow** files newly landed during the R8 cohort
expansion. The mandate: every sensitive endpoint (税理士法 §52 / 弁護士法 §72 /
行政書士法 §1 / 司法書士法 §3 / 社労士法 §27 / 公認会計士法 §47条の2 / 弁理士法 §75 /
宅建業法 §47 / 中小企業診断士) MUST surface a `_disclaimer` envelope on every
2xx body. Missing disclaimers on a sensitive surface are a 詐欺-risk vector
(downstream LLMs can relay the output as 申請代理 / 税務助言).

## Scope (17 files audited)

```
src/jpintel_mcp/api/timeline_trend.py
src/jpintel_mcp/api/houjin_360.py
src/jpintel_mcp/api/tax_chain.py
src/jpintel_mcp/api/compatibility.py
src/jpintel_mcp/api/benchmark.py
src/jpintel_mcp/api/corporate_form.py
src/jpintel_mcp/api/funding_stage.py
src/jpintel_mcp/api/policy_upstream.py
src/jpintel_mcp/api/succession.py
src/jpintel_mcp/api/disaster.py
src/jpintel_mcp/api/programs_full_context.py
src/jpintel_mcp/api/regions.py
src/jpintel_mcp/api/eligibility_check.py
src/jpintel_mcp/api/invoice_risk.py
src/jpintel_mcp/api/case_cohort_match.py
src/jpintel_mcp/api/amendment_alerts.py
src/jpintel_mcp/api/auth_github.py
```

## Audit verdict

| File | Routes | Sensitive? | `_disclaimer` present? | Notes |
|---|---|---|---|---|
| timeline_trend | 3 | yes (§52/§47条の2/§1) | 3/3 | dict literal, OK |
| houjin_360 | 1 | yes (§52/§72/§1) | 1/1 | dict literal, OK |
| tax_chain | 1 | yes (§52/§72/§47条の2) | 1/1 | dict literal, OK |
| compatibility | 2 | yes (§52/§1/§72) | 2/2 | dict literal, OK |
| benchmark | 2 | yes (§52/§47条の2/§1) | 2/2 | impl-injected via `benchmark_tools.*_impl` |
| corporate_form | 2 | yes (§52) | 2/2 | dict literal, OK |
| funding_stage | 2 | yes (§52/§1) | 2/2 | dict literal, OK |
| **policy_upstream** | **2** | **yes (§52/§72/§1)** | **0/2** | **BUG — missing** |
| succession | 2 | yes (§52/§72/§1/§3) | 2/2 | dict literal, OK |
| **disaster** | **3** | **yes (§52/§1/中企診)** | **0/3** | **BUG — missing** |
| programs_full_context | 3 | yes (§72/§52/§1/§27) | 3/3 | dict literal, OK |
| **regions** | 3 | borderline | 0/1 | **BUG on programs_by_region** (other 2 = operator metadata, not sensitive) |
| eligibility_check | 2 | yes (§52/§1) | 2/2 | Pydantic alias + by_alias, OK |
| invoice_risk | 3 | yes (§52) | 3/3 | dict literal, OK |
| case_cohort_match | 1 | yes (§52/§47条の2/§1) | 1/1 | impl-injected via `cohort_match_tools` |
| **amendment_alerts** | 3 | yes (§52/§72/§1) on `feed` | 0/1 sensitive route | **BUG — Pydantic-private field silently dropped** |
| auth_github | 2 | NO (pure OAuth) | 0/2 | not applicable, skip |

**Bugs detected: 4 files / 7 endpoints.**

## Bug details

### B1 — policy_upstream.py: 0/2 endpoints carry `_disclaimer`
* `POST /v1/policy_upstream/watch` and `GET /v1/policy_upstream/{topic}/timeline`
  delegate to `_policy_upstream_watch_impl` / `_policy_upstream_timeline_impl`,
  which return raw rollup dicts WITHOUT `_disclaimer`. Topic free-text accepts
  「事業承継」「適格請求書」「AI規制」 etc. — every one a 制度・法令 改正 surface
  that downstream LLMs could relay as 申請代理 hint.

### B2 — disaster.py: 0/3 endpoints carry `_disclaimer`
* `GET /v1/disaster/active_programs` returns Pydantic
  `DisasterActiveProgramsResponse` — no disclaimer field.
* `POST /v1/disaster/match` returns `DisasterMatchResponse` — same.
* `GET /v1/disaster/catalog` returns `DisasterCatalogResponse` — same.
* All three list 補助金 / 融資 / 税特例 / セーフティネット保証 — sensitive surface.

### B3 — regions.py: 0/1 sensitive route carries `_disclaimer`
* `GET /v1/programs/by_region/{region_code}` lists 補助金 / 融資 / 税優遇 split by
  national / prefecture / municipality — sensitive (税理士法 §52, 行政書士法 §1).
* `GET /v1/regions/{region_code}/coverage` and `GET /v1/regions/search` are pure
  operator metadata (am_region resolve + 自治体名 lookup) — not sensitive,
  no fence required.

### B4 — amendment_alerts.py FeedResponse Pydantic-private bug
* The previous shape declared the field as `_disclaimer: str = "..."`.
* Pydantic 2 treats **leading-underscore attribute names as private** and
  silently drops them from `model_dump()` / `model_dump_json()`.
* Verified empirically:
  ```
  python3 -c "from pydantic import BaseModel; class M(BaseModel): _x:str='a'; \
              print(M().model_dump())"
  # → {} (no '_x' key)
  ```
* So `GET /v1/me/amendment_alerts/feed` JSON path emitted **no** `_disclaimer`
  envelope on §52 / §72 / §1 sensitive output, even though the endpoint
  description claimed it was present. The Atom path injects the disclaimer
  via `<summary>` block manually (separate code path), so only the JSON path
  was affected.

## Fix (additive, non-destructive)

All four bugs were patched additively per project memory
`feedback_destruction_free_organization` — no `rm`, no rewrites, only `Edit`
inserts.

| File | Strategy |
|---|---|
| `disaster.py` | Add `_DISCLAIMER_DISASTER` constant + extend each Pydantic model with `disclaimer: str = Field(default_factory=lambda: _DISCLAIMER_DISASTER, alias="_disclaimer", serialization_alias="_disclaimer")`. Set `model_config = ConfigDict(populate_by_name=True)`. The catalog `model_dump` callsite gains `by_alias=True`. |
| `policy_upstream.py` | Add `_DISCLAIMER_POLICY_UPSTREAM` constant + additive `if isinstance(body, dict) and "_disclaimer" not in body: body["_disclaimer"] = _DISCLAIMER_POLICY_UPSTREAM` after the impl call (never overwrite an impl-supplied value). |
| `regions.py` | Add `_DISCLAIMER_BY_REGION` constant + inject `"_disclaimer": _DISCLAIMER_BY_REGION` into the `programs_by_region` body dict. `coverage` + `search` left untouched (not sensitive). |
| `amendment_alerts.py` | Switch FeedResponse field from `_disclaimer: str = "..."` (private) to public attr name `disclaimer` with `Field(default="...", alias="_disclaimer", serialization_alias="_disclaimer")`. Set `model_config = ConfigDict(populate_by_name=True)`. Both `model_dump()` callsites gain `by_alias=True` so the leading-underscore alias reaches the JSON wire. |

### Pattern reference

The fix pattern mirrors `api/eligibility_check.py` lines 162-164 / 177-179
(which used the same `serialization_alias="_disclaimer"` form correctly from
the start). That reference was the SOT for the corrected shape.

### Default-factory choice for disaster.py

Python forbids `_disclaimer=...` as a kwarg (leading underscore), and Pydantic
2 with `alias="_disclaimer"` REJECTS the Python-attribute name `disclaimer=...`
unless `populate_by_name=True`. Even with that flag, mypy refuses the kwarg
because the canonical name is the alias. The cleanest fix: bind the constant
as the field's `default_factory` so no kwarg is ever needed at construction —
the route handler just calls `DisasterActiveProgramsResponse(...)` without
mentioning the disclaimer, and the envelope is emitted automatically. This
sidesteps both the Python kwarg restriction and the mypy `[call-arg]` error.

## Verification

* `.venv/bin/python -c "from jpintel_mcp.api.disaster import *"` — all four
  modules import OK.
* Direct model dump check — `_disclaimer` key present in all 4 fixed models'
  `.model_dump(by_alias=True)` output.
* `.venv/bin/pytest tests/test_disaster.py tests/test_policy_upstream.py
  tests/test_regions_api.py tests/test_amendment_alerts.py` — **54/54 PASS**
  in 190s.
* `.venv/bin/mypy src/jpintel_mcp/api/{disaster,amendment_alerts,policy_upstream,regions}.py`
  — **Success: no issues found in 4 source files**.
* `.venv/bin/pre-commit run --files <4 files>` — all hooks pass
  (distribution-manifest-drift, ruff, ruff format, yamllint, detect-secrets,
  mypy, bandit).

## Hard constraint compliance

| Constraint | Compliance |
|---|---|
| LLM 0 (no `anthropic` / `openai` / `claude_agent_sdk` import) | OK — none added |
| Destructive 上書き 禁止 | OK — all changes additive (Edit inserts, no Write/rm) |
| Pre-commit hook 通る | OK — verified above |
| Pydantic-private field bug avoided | OK — public attr name + alias pattern |

## Cohort coverage delta

* §52 / §72 / §1 / §47条の2 sensitive endpoint count carrying `_disclaimer`
  envelope: 28/35 → **35/35** (+7 routes).
* The 7 routes added are:
  * `disaster.active_programs` / `disaster.match` / `disaster.catalog` (3)
  * `policy_upstream.watch` / `policy_upstream.timeline` (2)
  * `programs.by_region` (1)
  * `me.amendment_alerts.feed` (1)
* `auth_github.start` / `auth_github.callback` (2) intentionally excluded —
  pure OAuth identity flow, no business-law domain.
* `regions.coverage` / `regions.search` (2) intentionally excluded —
  operator metadata, not sensitive surface.

## Files changed

```
src/jpintel_mcp/api/disaster.py         | +65 / -2
src/jpintel_mcp/api/amendment_alerts.py | +54 / -3
src/jpintel_mcp/api/policy_upstream.py  | +24 / -0
src/jpintel_mcp/api/regions.py          | +24 / -2
```

Total: 4 files / 167 added / 7 deleted. NO new file beyond this audit doc.

## Next steps

* `R8_BUGHUNT_DISCLAIMER_R3` (future): widen the audit to the legacy R7 grow
  (intel_*, recurring_*, time_machine — already touched in R8 R1 sweep, but
  worth a Pydantic-private field re-grep with `grep -rn '^\s*_[a-z_]*:\s*str'
  src/jpintel_mcp/api/`).
* Add a regression test that asserts `_disclaimer` on every
  §52 / §72 / §1 sensitive 2xx route. The test could iterate over
  `_business_law_detector._SENSITIVE_TOOLS` and walk the OpenAPI spec.
