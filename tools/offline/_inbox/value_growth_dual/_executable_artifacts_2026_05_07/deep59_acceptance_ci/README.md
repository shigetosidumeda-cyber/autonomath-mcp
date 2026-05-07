# DEEP-59: Acceptance Criteria CI Guard

`jpcite v0.3.4`, session A lane (Wave 17 draft).

This artifact implements the CI-side enforcement of the **258 acceptance
criteria** distilled from the 33 DEEP specs, derived from
`R8_ACCEPTANCE_CRITERIA_CI_GUARD.md`. Every criterion is verified
mechanically through one of **12 core check kinds** (plus 3 auxiliaries),
driven by `pytest --parametrize` against a single YAML source-of-truth.

The target automation ratio is **79.5%**: at least 205 of 258 criteria
must run unattended on PR / weekly cron, with the remaining surface
classified as `semi` (deferred network / DB calls) or `manual` (human
sign-off only).

## Files

| File | Purpose |
| --- | --- |
| `test_acceptance_criteria.py` | Pytest module with 12 verifier functions + parametrized driver. |
| `acceptance_criteria.yaml` | Source-of-truth (sample of 30+ rows; full 258 land per-spec). |
| `aggregate_acceptance.py` | Per-spec rollup, emits `aggregate_acceptance.json`. |
| `acceptance_criteria_ci.yml` | GitHub Actions workflow (PR + weekly schedule). |
| `test_test_acceptance_criteria.py` | Meta-tests (8) covering verifiers + dispatch + ratios. |
| `README.md` | This file. |

## 12 core check kinds

| # | `check_kind` | Inputs | Verifies |
| --- | --- | --- | --- |
| 1 | `file_existence` | `path` | path exists, non-empty if file |
| 2 | `jsonschema` | `file`, `schema` | JSON file validates against inline schema |
| 3 | `sql_syntax` | `file` | `sqlglot.parse(read="sqlite")` succeeds |
| 4 | `python_compile` | `file` | `py_compile.compile(doraise=True)` succeeds |
| 5 | `llm_api_import_zero` | `file` | no `anthropic` / `openai` import in source |
| 6 | `pytest_collect` | `file` | `pytest --collect-only` returns rc 0 |
| 7 | `gha_yaml_syntax` | `file` | YAML parses + has `on:` and `jobs:` |
| 8 | `html5_doctype_meta` | `file` | `<!doctype html>`, UTF-8 meta, viewport meta |
| 9 | `schema_org_jsonld` | `file` | >=1 `<script type="application/ld+json">` with `schema.org` `@context` |
| 10 | `regex_pattern_count` | `file`, `pattern`, `min_count` | regex matches at least `min_count` times |
| 11 | `migration_first_line_marker` | `file` | first line matches `-- migration: NNN_<slug>` |
| 12 | `business_law_forbidden_phrases` | `file` | DEEP-38 phrase list does NOT appear |

Auxiliary kinds (counted as `semi` automation): `sql_count` (real DB),
`gh_api` (network), `disclaimer_marker_present` (DEEP-38 sibling).

## DEEP-59 spec linkage

```
R8_ACCEPTANCE_CRITERIA_CI_GUARD.md
   |
   +- 33 DEEP specs (DEEP-22 ... DEEP-54)
   |     |
   |     +- 258 acceptance criteria (id = "DEEP-NN-K")
   |
   +- acceptance_criteria.yaml          <-- source of truth
   |
   +- test_acceptance_criteria.py        <-- 12 verifier dispatch
   |
   +- pytest --junitxml=acceptance_junit.xml
   |
   +- aggregate_acceptance.py            <-- per-spec rollup JSON
   |
   +- acceptance_criteria_ci.yml         <-- GHA gate
```

The pytest parametrize id is always `<DEEP-NN-K>-<check_kind>`, which
preserves spec traceability through JUnit XML and the aggregate JSON.

## Running locally

```sh
# 1. install deps (no LLM SDKs)
python -m pip install pytest sqlglot jsonschema PyYAML

# 2. set repo root (defaults to parent of this file)
export JPCITE_REPO_ROOT=$PWD

# 3. run only the meta-tests for fast feedback
python -m pytest tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep59_acceptance_ci/test_test_acceptance_criteria.py -v

# 4. run the full acceptance guard
python -m pytest tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep59_acceptance_ci/test_acceptance_criteria.py -v \
    --junitxml=acceptance_junit.xml

# 5. roll up
python tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep59_acceptance_ci/aggregate_acceptance.py \
    --junit acceptance_junit.xml \
    --out aggregate_acceptance.json
```

## CI behaviour

- **Trigger**: `pull_request` against `main` plus `schedule` Mon 03:17 UTC.
- **Hermetic**: `JPCITE_OFFLINE=1` forces `gh_api` / `sql_count` to skip
  with `automated=False`, which the meta-driver converts to pytest
  `skip` rather than fail.
- **Artifact**: `aggregate-acceptance-<run_id>` containing
  `aggregate_acceptance.json` and `acceptance_junit.xml` (30 day
  retention).
- **Gate**: workflow fails the PR check when:
  - any criterion outcome is `failed`, **or**
  - automation ratio drops below 79.5%.

## Automation ratio trajectory

| Wave | Rows in YAML | Automated | Ratio | Notes |
| --- | --- | --- | --- | --- |
| seed (this draft) | 49 | 39 | ~0.80 | sample covering each DEEP spec primary criterion |
| Wave 18 | ~120 | ~95 | 0.79 | DEEP-22 .. DEEP-38 fully expanded |
| Wave 19 | ~200 | ~159 | 0.79 | DEEP-39 .. DEEP-50 expanded |
| Wave 20 | 258 | >=206 | >=0.7984 | full matrix, clears 0.795 gate, goes red on regression |

The 79.5% target intentionally leaves room for `semi` rows that only run
when the SQLite snapshot is mounted (CI builders) or when the public spec
repo is reachable (smoke runs).

## Constraints honoured

- `LLM API 呼出 0` - no `anthropic` / `openai` imports anywhere in this
  artifact, enforced by `check_llm_api_import_zero` against the guard
  module itself plus the CI step `Verify zero LLM SDK in guard module`.
- `Solo + zero-touch` - no paid SaaS, no third-party lint plan; only
  `pytest`, `sqlglot`, `jsonschema`, `PyYAML`.
- `業法 disclaimer` - `check_business_law_forbidden_phrases` reuses the
  DEEP-38 forbidden phrase list; the guard module is the canonical
  enforcement surface.
- jpcite scope only.
