# Wave 49 tick#7 — Dim N (Anonymized network query / PII redact) Phase 1 strict PR

**Date**: 2026-05-12
**Branch**: `feat/jpcite_2026_05_12_wave49_dim_n_phase1_strict`
**Wave**: Wave 49 U5 (Dim N + O 強化) Phase 1
**Memory anchor**: `feedback_anonymized_query_pii_redact` / `feedback_destruction_free_organization` / `feedback_dual_cli_lane_atomic`
**Lane**: `/tmp/jpcite-w49-dim-n-strict.lane` (atomic mkdir gate passed)

## Scope (additive only — destruction-free)

Wave 47 migration 274 landed the Dim N substrate with k=5 floor + 3-pattern
PII redact (`security/pii_redact.py`: houjin / email / phone). Wave 49
Phase 1 hardens the surface with two parallel artefacts that **do not
remove or relax** any Wave 47 capability:

1. **k=10 strict view** parallel to existing k=5 view (migration 274 →
   `v_anon_cohort_outcomes_latest` stays; this PR adds
   `v_anon_cohort_outcomes_k10_strict` on top of the same materialized
   table).
2. **7-pattern PII redact middleware** (`src/jpintel_mcp/api/_pii_redact.py`)
   that extends the existing 3-pattern core with 4 categories (name /
   address / mynumber / account) plus a parity-restated phone / email /
   houjin (houjin gated, default preserve — memory parity).

## Files (3 + 1 rollback + 1 doc)

| Path | LOC | Kind |
|---|---|---|
| `scripts/migrations/288_dim_n_k10_strict.sql` | ~75 | new (additive view) |
| `scripts/migrations/288_dim_n_k10_strict_rollback.sql` | ~15 | new (DROP VIEW only) |
| `src/jpintel_mcp/api/_pii_redact.py` | ~210 | new (extends, not replaces) |
| `tests/test_dim_n_pii_redact_strict.py` | ~245 | new (21 + 3 = 24 tests) |
| `docs/research/wave49/STATE_w49_dim_n_phase1_pr.md` | this file | new |

## 7 PII pattern table

| id | category | regex shape | replacement | gate |
|---|---|---|---|---|
| `pii-houjin` | 法人番号 (T+13) | `T\d{13}` | `[REDACTED:HOUJIN]` | **gated** (default preserve — gbiz PDL v1.0 公開情報) |
| `pii-email` | RFC5322-lite | `[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}` | `[REDACTED:EMAIL]` | — |
| `pii-phone` | JP landline / mobile / +81 | strict boundary lookahead | `[REDACTED:PHONE]` | — |
| `pii-mynumber` | 個人番号 12 桁 | `(?<!\d)(?<!T)\d{12}(?!\d)` | `[REDACTED:MYNUMBER]` | — |
| `pii-account` | 銀行口座 4-7 桁 + 普通/当座/支店 prefix | composite | `[REDACTED:ACCOUNT]` | — |
| `pii-address` | 47都道府県 + 市区町村 + 数字 chōme | composite | `[REDACTED:ADDRESS]` | — |
| `pii-name` (katakana) + `pii-name-kanji` | 個人氏名 (法人 suffix negative-lookahead) | composite | `[REDACTED:NAME]` | — |

**Gate honoring**: existing `settings.pii_redact_houjin_bangou` env knob
(no new env vars introduced; memory `feedback_no_fake_data` parity —
法人番号 は gbiz/国税庁 PDL v1.0 公開情報 で default preserve).

**Negative guards** (regression-blockers from S7 fix 2026-04-25):
- canonical_id substring `program:09_xxx:000000:hexhash` MUST pass through
- bare 13 桁 houjin (no T prefix) MUST pass through when gate OFF
- 13 桁 houjin MUST NOT be eaten by the mynumber 12-digit regex

## k=10 strict migration (288)

- Adds `v_anon_cohort_outcomes_k10_strict` SQL view on top of existing
  `am_aggregated_outcome_view` (migration 274) — no schema changes to
  the underlying table, no ETL changes required, no data
  re-population (nightly aggregator already writes every k>=5 cohort,
  so the strict view is just a `k_value >= 10` filter).
- Existing `v_anon_cohort_outcomes_latest` (k=5) view is **NOT
  touched** — destruction-free per memory.
- Rollback file `288_dim_n_k10_strict_rollback.sql` drops ONLY the new
  view, leaves k=5 view + base table intact.

**SQL verify (in-memory sqlite3, local)**:
- `executescript(274) → executescript(288) → 2 views exist`
  (`v_anon_cohort_outcomes_latest`, `v_anon_cohort_outcomes_k10_strict`).
- `executescript(288_rollback) → only k=5 view remains`.

## Test results (24/24 PASSED, runtime 1.14s)

```
24 passed in 1.14s
```

Coverage breakdown (7 patterns × 3 cases = 21 + 3 surface tests = 24):

- name × 3 (kanji simple / kanji no-space / katakana mid-dot)
- address × 3 (Tokyo Chiyoda / Osaka Chuo / Hokkaido)
- phone × 3 (landline / mobile / +81)
- mynumber × 3 (simple / in-sentence / **must NOT eat 13-houjin**)
- account × 3 (普通 / 当座 / 支店+口座)
- email × 3 (simple / subdomain / multiple)
- houjin × 3 (default preserve / gated-on redacts / bare 13 passes through)
- surface × 3 (PATTERNS table has 7 distinct ids / empty passthrough /
  audit hook emits no raw values)

## Anti-creep guarantees (verified)

- LLM API import = 0 (new files import only `re` / `typing` / `logging`)
- `rm` / `mv` count = 0
- main worktree untouched (lane = `/tmp/jpcite-w49-dim-n-strict` only)
- existing `security/pii_redact.py` (3-pattern core) unmodified
- existing migration 274 unmodified
- no new env vars (gate reuses `pii_redact_houjin_bangou`)
- no ETL touch (nightly aggregator continues to feed k>=5 cohorts)

## Wave 49 placement

U5 Phase 1 of 2. Phase 2 (out of scope here, future tick) wires the
strict view + the 7-pattern middleware into `/v1/network/anonymized_outcomes`
behind a feature flag and registers the middleware on the FastAPI
response cascade so all Dim N responses go through it pre-flight.
