# W32 composite surfaces — planned/private preparation

Status: planned/private preparation note for SDK, docs, and site copy. These
surfaces do not have public REST paths until the routes are mounted and the
central OpenAPI JSON exposes them.

## Positioning

jpcite's published OpenAPI currently exposes 17 `/v1/intel/*` REST endpoints.
W32 prepares seven additional planned/private surface names for future
customer-facing SDK wrappers and documentation:

| Planned/private surface | Intended use |
|---|---|
| `scenario simulation` | Compare a named or structured scenario against programs, houjin facts, and assumptions. |
| `competitor landscape` | Summarize comparable organizations, adoption signals, jurisdiction, and program context. |
| `portfolio heatmap` | Build a matrix across houjin/program/risk axes for triage and prioritization. |
| `news brief` | Return a compact brief over stored corpus updates and source-backed changes. |
| `onboarding brief` | Prepare an evidence bundle for a newly onboarded houjin or customer account. |
| `refund risk` | Surface rules-based refund/clawback risk indicators and gaps. |
| `cross jurisdiction` | Compare jurisdiction-specific requirements, signals, or caveats. |

These are **prepared/planned/private surfaces**, not public REST endpoints or
production-ready claims, until route registration is complete, OpenAPI is
integrated, and endpoint-level tests pass.

## Runtime boundaries

- No LLM call: these surfaces are designed to return structured data and
  rules-based evidence bundles. Customer agents may use those bundles as model
  input, but jpcite composite surfaces do not generate prose via an LLM.
- No live web: these surfaces use the jpcite corpus, cached facts, rules, and
  stored source URLs. They do not browse the web at request time.
- Sensitive outputs: risk, refund, exclusion, jurisdiction, compliance, and
  onboarding surfaces must preserve `_disclaimer`, `known_gaps`, source
  URLs, and corpus timestamps.
- Professional boundary: outputs are evidence and machine signals. They are
  not legal advice, tax advice, credit decisions, administrative filing代行,
  or eligibility guarantees.

## Planned SDK wrapper shape

The planned TypeScript wrappers follow the existing intel style, but should
remain gated until matching public REST paths appear in OpenAPI:

```ts
await jp.intelScenarioSimulate({
  scenario: "open-new-office",
  houjin_id: "8010001213708",
  program_ids: ["PROGRAM-example"],
});

await jp.intelRefundRisk({
  houjin_id: "8010001213708",
  program_id: "PROGRAM-example",
  amount_jpy: 3_000_000,
});
```

The request types are intentionally conservative: required identifiers are
typed where the surface implies one, common knobs such as `program_ids`,
`include_axes`, `since_date`, and `max_items` are named, and an index
signature remains for forward-compatible server fields.

## Known gaps

- REST module behavior is not described here beyond surface names and intended
  use. Server schemas may narrow fields during implementation.
- Public REST path names, OpenAPI JSON, and manifest entries are not part of
  this preparation pass.
- Bench numbers in `composite-bench-results.md` cover existing composite
  and synthesized forward-looking flows; they should not be read as measured
  W32 seven-surface production performance.
- `news_brief` is a corpus update brief, not a live-news product.
