# AutonoMath Pre-Launch Smoke Test — 2026-04-24

**Generated**: 2026-04-24T08:37:49.985606+00:00  
**DB**: `/Users/shigetoumeda/jpintel-mcp/data/jpintel.db`  
**Summary verdict**: **GREEN**  
**REST**: 15/15 | **MCP**: 31/31 | **Telemetry**: 3/3  

---

## REST Pass/Fail Table

| Endpoint | Expected | Actual | Latency (ms) | Verdict |
| --- | --- | --- | --- | --- |
| `GET /healthz` | 200 | 200 | 16 | **PASS** |
| `GET /readyz` | 200 | 200 body=ready | 0 | **PASS** |
| `GET /v1/meta` | 200 | 200 | 47 | **PASS** |
| `GET /v1/ping` | 200 | 200 | 0 | **PASS** |
| `GET /v1/programs/search` | 200 | 200 | 70 | **PASS** |
| `GET /v1/programs/UNI-00550acb43` | 200 | 200 | 9 | **PASS** |
| `GET /v1/case-studies/search` | 200 | 200 | 63 | **PASS** |
| `GET /v1/loan-programs/search` | 200 | 200 | 14 | **PASS** |
| `GET /v1/enforcement-cases/search` | 200 | 200 | 17 | **PASS** |
| `GET /v1/exclusions/rules` | 200 | 200 | 15 | **PASS** |
| `POST /v1/programs/prescreen` | 200 | 200 | 47 | **PASS** |
| `GET /v1/programs/search?q=` | 200 or 422 | 200 | 0 | **PASS** |
| `GET /v1/programs/NONEXISTENT-XYZ` | 404 | 404 | 8 | **PASS** |
| `GET /v1/programs/search?tier=INVALID` | 422 | 422 | 0 | **PASS** |
| `GET /v1/programs/search (51st from same IP)` | 429 | 429 | 0 | **PASS** |

---

## MCP Pass/Fail Matrix (31 tools)

| Tool | Sample Args | Response Type | Latency (ms) | Verdict | Note |
| --- | --- | --- | --- | --- | --- |
| `search_programs` | `{'q': '補助金', 'limit': 5}` | dict | 174 | **PASS** |  |
| `get_program` | `{'unified_id': 'UNI-00550acb43'}` | dict | 2 | **PASS** |  |
| `batch_get_programs` | `{'unified_ids': ['UNI-00550acb43']}` | dict | 2 | **PASS** |  |
| `list_exclusion_rules` | `{}` | list | 6 | **PASS** |  |
| `check_exclusions` | `{'program_ids': ['keiei-kaishi-shikin', 'koyo-shun` | dict | 3 | **PASS** |  |
| `get_meta` | `{}` | dict | 55 | **PASS** |  |
| `enum_values` | `{'field': 'target_type', 'limit': 10}` | dict | 45 | **PASS** |  |
| `search_enforcement_cases` | `{'limit': 5}` | dict | 7 | **PASS** |  |
| `get_enforcement_case` | `{'case_id': 'jbaudit_r03_2021-r03-0046-0_1'}` | dict | 2 | **PASS** |  |
| `search_case_studies` | `{'q': '農業', 'limit': 5}` | dict | 50 | **PASS** |  |
| `get_case_study` | `{'case_id': 'mirasapo_case_118'}` | dict | 2 | **PASS** |  |
| `search_loan_programs` | `{'limit': 5}` | dict | 5 | **PASS** |  |
| `get_loan_program` | `{'loan_id': 1}` | dict | 2 | **PASS** |  |
| `prescreen_programs` | `{'prefecture': '東京都', 'is_sole_proprietor': True, ` | dict | 30 | **PASS** |  |
| `upcoming_deadlines` | `{'within_days': 60, 'limit': 10}` | dict | 34 | **PASS** |  |
| `search_laws` | `{'q': '農業', 'limit': 5}` | dict | 44 | **PASS** |  |
| `get_law` | `{'unified_id': 'LAW-000632044c'}` | dict | 1 | **PASS** |  |
| `list_law_revisions` | `{'unified_id': 'LAW-000632044c'}` | dict | 4 | **PASS** |  |
| `search_court_decisions` | `{'limit': 5}` | dict | 4 | **PASS** |  |
| `get_court_decision` | `{'unified_id': 'HAN-000000ffff'}` | dict | 2 | **PASS** | structured error (allowed): court decision not found: HAN-000000ffff |
| `find_precedents_by_statute` | `{'law_unified_id': 'LAW-000632044c', 'limit': 5}` | dict | 2 | **PASS** |  |
| `search_bids` | `{'limit': 5}` | dict | 2 | **PASS** |  |
| `get_bid` | `{'unified_id': 'BID-000000ffff'}` | dict | 2 | **PASS** | structured error (allowed): bid not found: BID-000000ffff |
| `bid_eligible_for_profile` | `{'bid_unified_id': 'BID-000000ffff', 'business_pro` | dict | 2 | **PASS** | structured error (allowed): bid not found: BID-000000ffff |
| `search_tax_rules` | `{'limit': 5}` | dict | 3 | **PASS** |  |
| `get_tax_rule` | `{'unified_id': 'TAX-121a946f9e'}` | dict | 2 | **PASS** |  |
| `evaluate_tax_applicability` | `{'business_profile': {'annual_revenue_yen': 100000` | dict | 3 | **PASS** |  |
| `search_invoice_registrants` | `{'limit': 5}` | dict | 3 | **PASS** |  |
| `trace_program_to_law` | `{'program_unified_id': 'UNI-00550acb43'}` | dict | 4 | **PASS** |  |
| `find_cases_by_law` | `{'law_unified_id': 'LAW-000632044c', 'limit': 5}` | dict | 2 | **PASS** |  |
| `combined_compliance_check` | `{'business_profile': {'prefecture': '東京都', 'annual` | dict | 8 | **PASS** |  |

---

## Telemetry Verification (3 endpoints)

| Endpoint | Captured | Valid JSON | Fields Present | Channel | Status | Latency | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/v1/programs/search` | YES | PASS | PASS | rest | 200 | 206 | **PASS** |
| `/v1/meta` | YES | PASS | PASS | rest | 200 | 42 | **PASS** |
| `/v1/enforcement/search` | YES | PASS | PASS | rest | 404 | 0 | **PASS** |

Required fields: `ts`, `channel`, `endpoint`, `params_shape`, `result_count`, `latency_ms`, `status`, `error_class`

---

## Summary

- REST: **15/15** passed
- MCP: **31/31** passed
- Telemetry: **3/3** passed
- Total failures: **0**
- Verdict: **GREEN**
