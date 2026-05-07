# R8: tax_rule_full_chain endpoint (2026-05-07)

Status: shipped to source on 2026-05-07.

## Summary

`tax_rulesets` (50 rows) was previously exposed only via
`/v1/tax_rulesets/{search,get,evaluate}` — a 3-axis search + predicate
matcher that surfaces the rule itself but leaves the customer LLM to
fan out into 4 follow-up calls (laws / 通達 / 裁決 / 判例) before it can
draft any 「この税制を巡る解釈一式」 narrative. Each fan-out is a
separate ¥3 metered call.

This packet promotes the cross-corpus chain to a single first-class
endpoint:

- **GET `/v1/tax_rules/{rule_id}/full_chain`**
  Returns 6 axes for one `TAX-<10 hex>` ruleset in 1 call:
  - `rule` — the canonical `tax_rulesets` row (規定本文 + 計算式 + 提出要件)
  - `laws` — `laws` joined via the row's `related_law_ids_json`
    (LAW-* IN-list path, or name-LIKE fallback for free-text law refs)
  - `tsutatsu` — `nta_tsutatsu_index` rows whose `title` matches
    ruleset name kanji tokens (autonomath.db, ~3,221 rows)
  - `saiketsu` — `nta_saiketsu` 公表裁決事例 rows whose `title` /
    `decision_summary` matches name tokens, optionally narrowed by
    `tax_type` derived from `tax_category` (autonomath.db, ~140 rows)
  - `hanrei` — `court_decisions` whose `related_law_ids_json` overlaps
    the ruleset's law refs OR whose `case_name` / `key_ruling` matches
    name tokens; ordered by precedent_weight then date
  - `history` — sibling `tax_rulesets` rows with the same `ruleset_name`
    (sibling rows differ only in `effective_from` / `effective_until`,
    so they are the only honest "predecessor" surface absent an explicit
    predecessor_id column on the table)

A single MCP tool `tax_rule_full_chain` mirrors the REST contract via
the same in-process helpers; both surfaces register at default gates
(`AUTONOMATH_TAX_CHAIN_ENABLED`, default ON).

NO LLM call inside the endpoint. Pure SQLite SELECT + Python dict
shaping. CLAUDE.md forbids ATTACH / cross-DB JOIN — the implementation
opens jpintel.db (DbDep) and autonomath.db (RO connect helper)
separately, pulls each axis with bounded SQL, and merges in Python.
Single `_billing_unit: 1` (¥3) regardless of how many citations
surface.

## File map

| Path | Purpose |
| --- | --- |
| `src/jpintel_mcp/api/tax_chain.py` | REST router + per-axis fetchers |
| `src/jpintel_mcp/mcp/autonomath_tools/tax_chain_tools.py` | MCP tool wrapper (delegates to the same helpers) |
| `src/jpintel_mcp/api/main.py` (≈line 1933) | Router wiring under `tax_rulesets_router` neighbourhood |
| `src/jpintel_mcp/api/deps.py` | `_PARAMS_DIGEST_WHITELIST` += `tax_rules.full_chain` |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | MCP package import side-effect |
| `tests/test_tax_chain.py` | 8 tests — happy path, include filter, 404, 422, MCP wrapper, error envelopes |
| `docs/openapi/v1.json` | regenerated, new path lands in the `tax_rules` tag |
| `scripts/distribution_manifest.yml` | `openapi_path_count` bumped to 198 |

## Sensitive surface

The endpoint surfaces 規定 / 法令 / 通達 / 裁決 / 判例 verbatim
across 5 primary-source corpora. The injected `_disclaimer` covers
three regulated 士業 boundaries:

- **税理士法 §52** (税務代理) — chain output is a citation index, not
  individualised tax advice.
- **弁護士法 §72** (法令解釈) — 通達 / 裁決 / 判例 quotations are not
  legal interpretation.
- **公認会計士法 §47条の2** (監査・意見表明) — the bundle is a
  retrieval surface, not an audit work-paper.

LLM agents MUST relay the disclaimer verbatim when surfacing the
chain to end users. The same fence is applied at the MCP wrapper.

## Coverage summary

`coverage_summary.missing_types` lists axes whose backing table is
absent (autonomath.db missing on dev / CI). An empty list with 0 rows
on an axis is an honest empty (table existed, no rows matched the
ruleset). `axis_counts` is a stable dict keyed by canonical axis name
so callers always see all 5 axes regardless of which were requested
via `include`.

## Caps

| Knob | Default | Hard ceiling |
| --- | --- | --- |
| `max_per_axis` | 10 | 50 |
| `include` | all 5 axes | comma-separated subset |

`autonomath.db` reads use the shared 256 MB cache + 2 GB mmap
connect helper; 50 × 5 axes × 220-char snippet fits well under any
context budget the customer LLM is likely to enforce.

## Acceptance

8 tests in `tests/test_tax_chain.py`:

1. Happy path — all 6 axes populated, history excludes self,
   tsutatsu / saiketsu surface from the tmp autonomath slice.
2. `include=laws,hanrei` filter — other 3 axes empty,
   `missing_types=[]`.
3. 404 on a well-formed but missing TAX-* id.
4. 422 on a malformed unified_id (length / regex).
5. 422 on `max_per_axis` above hard ceiling.
6. MCP wrapper happy path — same envelope contract, `_billing_unit=1`.
7. MCP wrapper invalid `rule_id` → `invalid_input` error envelope.
8. MCP wrapper invalid `include` → `invalid_enum` error envelope.

All 8 PASS as of 2026-05-07. Pre-commit `mypy --strict` clean on the
two new source files.
