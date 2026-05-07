# R8 — Dynamic Eligibility Check (行政処分 × 排他ルール 連動)

Date: 2026-05-07
Owner: jpcite (v0.3.4)
Author: Session A operator (Claude Code)
Lane: housekeeping-audit-2026-05-06 (R8 follow-up)

## Why this exists

`enforcement_cases` (1,185 行政処分) and `exclusion_rules` (181 排他/前提) lived
on separate read surfaces. The **single most-asked question** by 補助金
consultants and 中小企業 — *"私 (法人) が過去 X 年に受けた 処分 を踏まえて、
今 申請可能な 補助金 list は?"* — required the caller to:

1. `GET /v1/enforcement-cases/details/search?houjin_bangou=...` →
   read each `enforcement_kind` and decide if it's a blocker.
2. `GET /v1/exclusions/rules` → 181 行を全件 fetch、 program_a/b を 自前で
   match。
3. `GET /v1/programs/search` → 候補 program list を 取得して、 自前で
   join/triage する。

Three round-trips, ~600 行の glue logic, 高 token cost。R8 collapses the
walk into 1 POST + 1 GET.

## What landed

### 1. REST surface

File: `src/jpintel_mcp/api/eligibility_check.py` (new, 530 lines).

- **POST `/v1/eligibility/dynamic_check`**
  - body: `{ houjin_bangou, industry_jsic?, exclude_history_years=5,
    program_id_hint? }`
  - response: `{ enforcement_hits[], blocked_programs[],
    borderline_programs[], eligible_programs[], checked_program_count,
    checked_rule_count, _disclaimer }`
  - 単発 ¥3 課金 (`log_usage("eligibility.dynamic_check")`).
- **GET `/v1/eligibility/programs/{program_id}/eligibility_for/{houjin_bangou}`**
  - path params: `program_id` = `programs.unified_id`,
    `houjin_bangou` = 13-digit (T-prefix / hyphen 許容).
  - query: `?exclude_history_years=5`.
  - response: 単一 `SingleProgramVerdict` envelope (verdict ∈ `blocked` |
    `borderline` | `eligible` + reasons + rule_ids + enforcement_hits).
  - 単発 ¥3 課金 (`log_usage("eligibility.for_pair")`).

Wired in `src/jpintel_mcp/api/main.py` next to `exclusions_router`
under `AnonIpLimitDep` (anonymous 3-req/日 IP gate).

### 2. MCP wrappers

File: `src/jpintel_mcp/mcp/autonomath_tools/eligibility_tools.py` (new,
~340 lines).

- `dynamic_eligibility_check_am(houjin_bangou, industry_jsic=None,
  exclude_history_years=5, program_id_hint=None)`
- `program_eligibility_for_houjin_am(program_id, houjin_bangou,
  exclude_history_years=5)`

Both gated behind `AUTONOMATH_ELIGIBILITY_CHECK_ENABLED` (default ON) on
top of the global `AUTONOMATH_ENABLED` env-gate. Pure SQLite walk; both
tools delegate to `_dynamic_check_impl` / `_single_program_impl` so the
tests can exercise the algorithm without spinning the MCP transport.

Registered in `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` between
`discover` and `evidence_packet_tools` (alphabetical convention).

### 3. Algorithm (deterministic, NO LLM)

```
houjin → am_enforcement_detail (within N years)
       ↓ classify each row by enforcement_kind
       ↓   blocking      = subsidy_exclude / grant_refund / license_revoke
       ↓   warning       = contract_suspend / business_improvement / fine
       ↓   informational = investigation / other

candidate set (jpintel.programs WHERE excluded=0 ± industry_jsic)
       ↓ for each program, walk exclusion_rules
       ↓   rule.kind ∈ exclude/absolute/entity_scope_restriction +
       ↓   houjin has ≥1 blocking hit → BLOCKED
       ↓   warning hit + critical-severity rule → BORDERLINE
       ↓   blocking hit but no rule match → BORDERLINE (manual review)
       ↓   else → ELIGIBLE
       ↓
       └─→ return triage buckets + reason strings
```

The classification table is encoded in code (`_BLOCKING_KINDS`,
`_WARNING_KINDS`, `_INFORMATIONAL_KINDS` frozensets) so it's review-able
in code review and never depends on a model call.

### 4. Tests

File: `tests/test_eligibility_check.py` (new, 14 cases, 100% pass).

- 5 cases for `POST /v1/eligibility/dynamic_check`:
  - blocked path (subsidy_exclude in window),
  - warning-only path,
  - 5-year window cuts a 2010 row,
  - 20-year window pulls it back,
  - invalid 法人番号 → 422,
  - clean houjin → all eligible,
  - `program_id_hint` narrows candidates.
- 4 cases for the GET pair surface:
  - blocked verdict,
  - clean houjin → eligible,
  - unknown program → 404,
  - invalid bangou → 422.
- 3 MCP impl smokes:
  - happy-path dynamic check,
  - happy-path single program,
  - invalid bangou → error envelope (`code=out_of_range`).

Sanity-walked `tests/test_enforcement.py` (25 cases) +
`tests/test_exclusion_rules_pagination.py` (8 cases) — no regression.

### 5. OpenAPI + manifest impact

- `scripts/export_openapi.py --out docs/openapi/v1.json` re-ran cleanly:
  198 paths, 2 preview, both new routes appear under `/v1/eligibility/*`.
- 2 MCP tool count delta. Manifest tool_count not bumped this session
  (per CLAUDE.md "manifest hold-at-139 until intentional release"). Run
  `len(await mcp.list_tools())` post-deploy to confirm runtime cohort
  goes 146 → 148.

## Constraint compliance

| Constraint | Status |
|------------|--------|
| LLM 0 (no anthropic/openai/google import) | OK — pure SQLite + classification table |
| Destructive 上書き 禁止 | OK — only new files + 2 additive edits in main.py / autonomath_tools/__init__.py |
| Pre-commit hook 通る | OK — `ruff check` green, `pytest` 47/47 green |
| ¥3/req metered (single billing event) | OK — single `log_usage` per request |
| Anonymous IP cap inherits | OK — `AnonIpLimitDep` wired |
| `_disclaimer` envelope | OK — top-level field on both REST + MCP responses |

## Honest limitations

- `am_enforcement_detail` carries 22,258 rows; only **6,455 have
  houjin_bangou populated**. Houjin without 法人番号 in the corpus
  return zero hits (false negative possible).
- Rule corpus is 181 行 — many programs reference enforcement only in
  公募要領 prose (not yet structured in `exclusion_rules`). Borderline
  catch-all (blocking hit + no rule match → borderline) is the honest
  fence here.
- Sole proprietors are out-of-scope (no 法人番号). The MCP tool
  description states this; future work could add a personal-id branch
  off `am_enforcement_detail.target_name`.
- `program_id_hint` is capped at 200 ids; UX limit, not a billing limit.
- Look-back window default = 5 yr. Most 補助金 公募要領 say "過去5年に
  補助金の不正受給等がない者" — matches the field. Some programs
  (例: 経済産業省 ものづくり補助金) use 3-year, some (例: 公庫融資)
  use 7-year; caller supplies the window.

## Files touched

```
src/jpintel_mcp/api/eligibility_check.py                          (new)
src/jpintel_mcp/api/main.py                                       (+6 lines, router include)
src/jpintel_mcp/mcp/autonomath_tools/eligibility_tools.py         (new)
src/jpintel_mcp/mcp/autonomath_tools/__init__.py                  (+1 line, registration)
tests/test_eligibility_check.py                                   (new)
docs/openapi/v1.json                                              (regenerated, +2 paths)
site/docs/openapi/v1.json                                         (regenerated)
tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_ELIGIBILITY_DYNAMIC_CHECK_2026-05-07.md  (this doc)
```

## Verification commands

```
.venv/bin/python -m pytest tests/test_eligibility_check.py -v          # 14/14
.venv/bin/python -m pytest tests/test_enforcement.py tests/test_exclusion_rules_pagination.py
.venv/bin/python -m pytest tests/test_no_llm_in_production.py          # 3/3
.venv/bin/ruff check src/jpintel_mcp/api/eligibility_check.py \
                     src/jpintel_mcp/mcp/autonomath_tools/eligibility_tools.py \
                     tests/test_eligibility_check.py
.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json
grep -c '/v1/eligibility' docs/openapi/v1.json                          # 2
```

## Next steps (deferred, not in this commit)

- Bump manifest `tool_count` 139 → 141 next intentional release.
- Wire `am_id_bridge` so `target_name` resolves to a houjin even when
  the 法人番号 column is null (covers the 16,000+ rows without bangou).
- Add `am_amendment_diff` cross-check so a recently-amended exclusion
  rule shows up as a "rule changed since your last check" warning in
  the response.
- Static page (`site/eligibility-check.html`) for organic SEO — same
  pattern as `/site/enforcement.html`.
