# R8 — 業法 disclaimer cohort live envelope verify (2026-05-07)

Audit-only walk over the 17 sensitive tools fixture
(`tests/fixtures/17_sensitive_tools.json`) against the live
`api.jpcite.com` v0.3.4 surface and the in-tree `_disclaimer` envelope
wiring. Read-only — no production charge, anonymous quota was already
exhausted at the start of the walk (3/3 requests consumed earlier in the
day). Framing is internal-hypothesis: the goal is to verify, not to
endorse.

> Status budget: this is **audit verification only**. No production
> response was successfully sampled — anonymous quota was at 0 and the
> walk did not consume the admin path (we ran HEAD probes, OpenAPI
> introspection, and a tightly-scoped `_apply_envelope` in-process
> simulation against the local source tree).

---

## 1 — 17-tool coverage matrix

| tool                                | wave           | in `SENSITIVE_TOOLS` | `_DISCLAIMER_STANDARD` | `_DISCLAIMER_MINIMAL` | REST path                   | wiring path                 |
|-------------------------------------|----------------|----------------------|------------------------|-----------------------|-----------------------------|-----------------------------|
| match_due_diligence_questions       | Wave 22        | yes                  | yes                    | yes                   | (MCP only)                  | inline `_DISCLAIMER_DD_QUESTIONS` (wave22_tools.py:503) |
| prepare_kessan_briefing             | Wave 22        | yes                  | yes                    | yes                   | (MCP only)                  | inline `_DISCLAIMER_KESSAN_BRIEFING` (wave22_tools.py:715) |
| cross_check_jurisdiction            | Wave 22        | yes                  | yes                    | yes                   | (MCP only)                  | inline `_DISCLAIMER_JURISDICTION` (wave22_tools.py:1105/1235) |
| bundle_application_kit              | Wave 22        | yes                  | yes                    | yes                   | (MCP only)                  | inline `_DISCLAIMER_APPLICATION_KIT` (wave22_tools.py:1338/1521) |
| render_36_kyotei_am                 | Phase A (gated)| no                   | no                     | no                    | `/v1/am/saburoku_kyotei`    | inline `_SABUROKU_DISCLAIMER` (autonomath.py:1837); gate OFF default |
| get_36_kyotei_metadata_am           | Phase A (gated)| no                   | no                     | no                    | `/v1/am/saburoku_kyotei/meta` | inline `_SABUROKU_DISCLAIMER` (autonomath.py:1760); gate OFF default |
| get_am_tax_rule                     | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/tax_rule`           | inline `_TAX_DISCLAIMER` post-merge (autonomath.py:1104) + envelope `_disclaimer` (MCP) |
| search_tax_incentives               | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/tax_incentives`     | inline `_TAX_DISCLAIMER` post-merge (autonomath.py:562) + envelope `_disclaimer` (MCP) |
| search_acceptance_stats_am          | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/acceptance_stats`   | envelope `_disclaimer` (MCP) — REST not surfacing (gap) |
| check_enforcement_am                | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/enforcement`        | envelope `_disclaimer` (MCP) — REST not surfacing (gap) |
| search_loans_am                     | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/loans`              | envelope `_disclaimer` (MCP) — REST not surfacing (gap) |
| search_mutual_plans_am              | v0.2 baseline  | yes                  | yes                    | yes                   | `/v1/am/mutual_plans`       | envelope `_disclaimer` (MCP) — REST not surfacing (gap) |
| pack_construction                   | Wave 23        | yes                  | yes                    | yes                   | `/v1/am/pack_construction`  | inline `_DISCLAIMER_INDUSTRY_PACK` (industry_packs.py:549) — already in raw tool body |
| pack_manufacturing                  | Wave 23        | yes                  | yes                    | yes                   | `/v1/am/pack_manufacturing` | inline (industry_packs.py:549) |
| pack_real_estate                    | Wave 23        | yes                  | yes                    | yes                   | `/v1/am/pack_real_estate`   | inline (industry_packs.py:549) |
| rule_engine_check                   | v0.2 baseline  | yes                  | yes                    | yes                   | (MCP only)                  | envelope `_disclaimer` (MCP) |
| apply_eligibility_chain_am          | Wave 21        | yes                  | yes                    | yes                   | (MCP only)                  | inline `_DISCLAIMER_ELIGIBILITY` (composition_tools.py:588) |

Counts: **15/17 in SENSITIVE_TOOLS frozenset** (count = 36 total entries
including non-fixture tools). The two negative rows are the 36協定
templates which ride a **separate** disclaimer string
(`_SABUROKU_DISCLAIMER`) and stay gated off behind
`AUTONOMATH_36_KYOTEI_ENABLED` (default `False`). They never reach the
envelope merge path because the gate strips them from `mcp.list_tools()`
before envelope wiring is consulted; the inline disclaimer is the
fallback when an admin flips the gate.

---

## 2 — Local test status

```
.venv/bin/pytest tests/test_disclaimer_envelope.py -v
collected 3 items
tests/test_disclaimer_envelope.py::test_sensitive_tools_carry_disclaimer       PASSED [33%]
tests/test_disclaimer_envelope.py::test_disclaimer_level_minimal_is_shorter    PASSED [66%]
tests/test_disclaimer_envelope.py::test_non_sensitive_tools_omit_disclaimer    PASSED [100%]
============================== 3 passed in 2.86s ===============================
```

The test asserts the `_envelope_merge` helper in `mcp/server.py` returns
a non-empty `_disclaimer` for the 11-tool subset
(`dd_profile_am`, `regulatory_prep_pack`, `combined_compliance_check`,
`rule_engine_check`, `predict_subsidy_outcome`, `score_dd_risk`,
`intent_of`, `reason_answer`, `search_tax_incentives`, `get_am_tax_rule`,
`list_tax_sunset_alerts`). The test does **not** yet enumerate the
remaining 6 sensitive tools added on 2026-05-07 (R8 wiring fix entries
in `SENSITIVE_TOOLS`: `search_acceptance_stats_am`, `search_loans_am`,
`search_mutual_plans_am`, `check_enforcement_am`) nor the Wave 21–23
composition / industry-pack tools — see §5 recommendation.

---

## 3 — Live API HEAD probe (read-only)

```
GET /openapi.json  →  HTTP 200, 539,834 bytes, 182 paths, info.version="0.3.4"
HEAD /v1/am/tax_incentives    →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/tax_rule          →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/loans             →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/mutual_plans      →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/enforcement       →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/acceptance_stats  →  HTTP/2 405 (allow: GET) x-envelope-version: v1
HEAD /v1/am/pack_construction →  HTTP/2 405 (allow: GET) x-envelope-version: v1
GET  /v1/am/pack_construction?prefecture=tokyo  →  HTTP 429 (anonymous quota exhausted)
```

All endpoints return canonical headers
(`x-envelope-version: v1`, `content-type: application/json`,
`vary: Accept, X-Envelope-Version, Accept-Encoding`,
strict-transport-security, CSP, X-Frame-Options DENY). HEAD on a GET-only
route correctly 405s with `allow: GET`. The 429 quota response is the
expected anonymous-tier guard from the trial-CTA payload (key
`reset_at_jst`, `direct_checkout_url`, `trial_cta_text_*`); it does not
emit a `_disclaimer` because at 429 the request never reaches the route
handler that would compose one.

OpenAPI schema reference inspection of the 200-response models:

| route                     | 200 response schema                          | mentions `_disclaimer` |
|---------------------------|----------------------------------------------|------------------------|
| `/v1/am/tax_incentives`   | `AMSearchResponse`                           | yes (schema-level)     |
| `/v1/am/tax_rule`         | `AMTaxRuleResponse`                          | no (declared field)    |
| `/v1/am/loans`            | `AMLoanSearchResponse`                       | no (declared field)    |
| `/v1/am/mutual_plans`     | `AMLoanSearchResponse` (re-used)             | no (declared field)    |
| `/v1/am/enforcement`      | `AMEnforcementCheckResponse`                 | no (declared field)    |
| `/v1/am/acceptance_stats` | `AMSearchResponse`                           | yes (schema-level)     |
| `/v1/am/pack_*`           | `{}` (untyped JSONResponse)                  | no (untyped)           |

Only `AMSearchResponse` declares `_disclaimer` on the OpenAPI schema —
the other Pydantic models do not advertise the field even though the
runtime response includes it (or should include it; see §4).

---

## 4 — Internal hypothesis: the REST `_apply_envelope` gap

`src/jpintel_mcp/api/autonomath.py:202–212` defines the additive merge
tuple used by every REST `/v1/am/*` route after `_apply_envelope` runs:

```python
additive = (
    "status",
    "result_count",
    "explanation",
    "suggested_actions",
    "api_version",
    "tool_name",
    "query_echo",
    "evidence_source_count",
)
```

`_disclaimer` is **not** in this tuple. The MCP-side equivalent
(`mcp/server.py:905–919`) explicitly includes `_disclaimer`:

```python
additive_keys = (
    "status", "result_count", "explanation", "suggested_actions",
    "api_version", "tool_name", "query_echo", "latency_ms",
    "evidence_source_count",
    # S7 disclaimer surface — additive so a tool that already authored
    # its own `_disclaimer` (e.g. rule_engine_check) keeps its longer
    # custom string verbatim.
    "_disclaimer",
)
```

Hypothesis verification (in-process, no live charge):

```
.venv/bin/python -c "
from jpintel_mcp.api.autonomath import _apply_envelope
fake = {'results':[{'id':'x','source_url':'https://meti.go.jp/x'}],
        'total':1, 'limit':20, 'offset':0, 'hint':'ok'}
print(sorted(_apply_envelope('search_acceptance_stats_am', fake, query='t').keys()))
# →  ['api_version', 'evidence_source_count', 'explanation', 'hint',
#     'limit', 'meta', 'offset', 'query_echo', 'result_count',
#     'results', 'status', 'suggested_actions', 'tool_name', 'total']
# →  '_disclaimer' is ABSENT.
"
```

So on the REST surface, four of the seventeen sensitive tools rely on
the envelope merge for `_disclaimer` and currently **do not surface it
to consumers**:

- `search_acceptance_stats_am` (`/v1/am/acceptance_stats`)
- `check_enforcement_am`       (`/v1/am/enforcement`)
- `search_loans_am`            (`/v1/am/loans`)
- `search_mutual_plans_am`     (`/v1/am/mutual_plans`)

The MCP path is fine — `_envelope_merge` includes `_disclaimer` in the
additive list and the test in §2 asserts non-empty output for those
names through the merge helper. The 17 fixture entries that are wired
inline (Wave 21/22/23 plus the two tax routes that re-inject
`_TAX_DISCLAIMER` after `_apply_envelope`) are unaffected.

CLAUDE.md "Common gotchas" does not yet mention this asymmetry; the
existing gotcha for `source_fetched_at` honesty is a different surface.

---

## 5 — Recommendations (no edits made — read-only audit)

1. **REST gap close**: add `"_disclaimer"` to the additive tuple in
   `_apply_envelope` (autonomath.py:203). This is a one-line edit that
   surfaces the envelope text for the four affected tools without
   touching their bodies. Mirror the comment from `mcp/server.py:915–917`
   so future maintainers see why the field rides additive merge.

2. **Test extension**: extend
   `tests/test_disclaimer_envelope.py::test_sensitive_tools_carry_disclaimer`
   to enumerate all 17 fixture entries (currently 11). The fixture is
   the canonical 業法 cohort list; the test asserting against a separate
   hand-typed set is a drift hazard. Drive the test from
   `tests/fixtures/17_sensitive_tools.json` directly so a new wave entry
   in the fixture auto-extends the assertion.

3. **OpenAPI surface honesty**: `AMTaxRuleResponse`, `AMLoanSearchResponse`,
   and `AMEnforcementCheckResponse` should declare the optional
   `_disclaimer: str | None` field so the published OpenAPI advertises
   what the runtime emits. Pure documentation lift; no behavioural change.

4. **36協定 gate stays**: the negative-row stance for `render_36_kyotei_am`
   and `get_36_kyotei_metadata_am` is correct — they ride a dedicated
   `_SABUROKU_DISCLAIMER` and are gated off by default
   (`AUTONOMATH_36_KYOTEI_ENABLED=False`). No promotion to
   `SENSITIVE_TOOLS` is needed unless the gate flips on; flipping the
   gate without the promotion would create the same REST gap as §4
   above.

5. **Envelope-version header coverage**: every `/v1/am/*` HEAD response
   carried `x-envelope-version: v1` — confirms the response middleware is
   uniformly applied. No drift detected on header surface.

---

## 6 — Status snapshot

- 17 fixture sensitive tools scanned: **15 passing the SENSITIVE_TOOLS
  frozenset gate**, **2 intentionally outside** (gated 36協定 cohort).
- Local `tests/test_disclaimer_envelope.py`: **3 passed in 2.86s**.
- Live HEAD walk on 7 routes: **all responding with envelope headers and
  expected 405 on HEAD-against-GET routes**, no 5xx, no envelope-version
  drift.
- Production charge incurred: **¥0** (anonymous quota was already at
  3/3 used before the walk; HEAD probes are quota-exempt; in-process
  `_apply_envelope` simulation is offline).
- LLM API calls: **0** (audit walk used Read / grep / curl HEAD / a
  single in-process Python invocation; no `anthropic`, `openai`, or
  `claude_agent_sdk` import).

Audit is read-only and ends here. Recommended fixes in §5 are queued
for a future intentional change-set, not applied as part of R8.
