---
wave: 46.D
tick: 5#5
generated_at: 2026-05-12
lane: docs_canonical_autonomath_to_jpcite_alias
branch: feat/jpcite_2026_05_12_wave46_rename_47d_docs_canonical
status: ready_for_pr
---

# Wave 46.D — `autonomath_*` → `jpcite_*` doc alias (banner + sub-rename) PR

## TL;DR

- **2 alias files** added under `docs/_internal/` (banner-only).
- Canonical `autonomath_*` files **unchanged** (rm/mv 禁止 contract).
- **Redirect map** added at `docs/_internal/REDIRECT_MAP_w46_canonical.md` (115 LOC).
- **Test** `tests/test_w47d_docs_canonical_alias.py` — **22 passed in 1.00s**.
- Total new LOC: **495** (79 + 75 + 115 + 226).

## Scope clarification (important)

The task brief targets `docs/canonical/autonomath_*.md`.  A repo-wide
audit on 2026-05-12 (HEAD `3aae4f345`) found:

| Path                                          | `autonomath_*.md` count | Notes                                                       |
| --------------------------------------------- | ----------------------- | ----------------------------------------------------------- |
| `docs/canonical/`                             | **0**                   | Contains only `perf_baseline.md` + `stripe_smoke_runbook.md`. |
| `docs/_internal/`                             | **2**                   | `autonomath_db_sync_runbook.md`, `autonomath_com_dns_runbook.md`. |
| `research/_archive/pre_launch_decisions/`     | 1                       | `autonomath_invalid_enriched.md` — archived, out of scope.  |

Decision: the brand-consolidation **intent** (jpcite surface that
redirects to canonical autonomath content) is fully served by aliasing
the two active operator runbooks in `docs/_internal/`.  The literal
target path `docs/canonical/` yields a no-op set, so we adapt to the
actual file location while preserving every other contract rule
(banner-only, source untouched, redirect map, test coverage).

The redirect map (§1) documents this divergence in full so any future
wave that does add `docs/canonical/autonomath_*.md` files can re-apply
the same alias pattern.

## Files added (495 LOC total)

| Path                                                   | LOC | Purpose                                                                 |
| ------------------------------------------------------ | --: | ----------------------------------------------------------------------- |
| `docs/_internal/jpcite_db_sync_runbook.md`             |  79 | jpcite-branded alias of `autonomath_db_sync_runbook.md` (banner only).  |
| `docs/_internal/jpcite_com_dns_runbook.md`             |  75 | jpcite-branded alias of `autonomath_com_dns_runbook.md` (banner only).  |
| `docs/_internal/REDIRECT_MAP_w46_canonical.md`         | 115 | Wave 46.D alias inventory + contract + scope clarification.             |
| `tests/test_w47d_docs_canonical_alias.py`              | 226 | 22 unit tests covering frontmatter / banner / link / non-migration.     |

## Alias inventory

| #  | Canonical source (untouched)                                | jpcite alias (new, banner-only)                              |
| -: | ----------------------------------------------------------- | ------------------------------------------------------------ |
| 1  | `docs/_internal/autonomath_db_sync_runbook.md`              | `docs/_internal/jpcite_db_sync_runbook.md`                   |
| 2  | `docs/_internal/autonomath_com_dns_runbook.md`              | `docs/_internal/jpcite_com_dns_runbook.md`                   |

**Total: 2 aliases** (banner only; canonical byte-content unchanged).

## Alias file contract (per `test_w47d_docs_canonical_alias.py`)

Every alias file satisfies:

1. **Frontmatter present** — `name`, `alias_of`, `brand_layer: jpcite`,
   `legacy_brand: autonomath`, `wave: 46.D`,
   `status: alias (banner-only; canonical content unchanged)`.
2. **Banner block** — starts with `**Alias notice (Wave 46.D`.
3. **Relative link** to canonical via `(./autonomath_<X>.md)`.
4. **Redirect-map back-link** via `(./REDIRECT_MAP_w46_canonical.md)`.
5. **Edit lock notice** in prose ("aliases are diff-frozen" /
   "edit the canonical source").
6. **No verbatim content migration** — alias paraphrases scope only
   (test enforces no 200-char run from canonical, and `len(alias) <
   1.5 * len(canonical)`).
7. **Canonical untouched** — neither `**Alias notice (Wave 46.D` nor
   `alias_of:` appears in the canonical file.

## Test verdict

```
$ /Users/shigetoumeda/jpcite/.venv/bin/pytest \
    tests/test_w47d_docs_canonical_alias.py -q --no-header
......................                                                   [100%]
22 passed in 1.00s
```

Coverage breakdown (22 tests):

- 1 × redirect map presence + Wave 46.D scope declaration.
- 2 × alias file presence (per pair).
- 2 × canonical file presence + non-zero (per pair).
- 2 × alias frontmatter key contract (per pair).
- 2 × alias banner phrase (per pair).
- 2 × alias links to canonical (per pair).
- 2 × alias links to redirect map (per pair).
- 2 × alias edit-lock notice (per pair).
- 2 × alias does not verbatim-copy canonical (per pair).
- 2 × canonical does not carry Wave 46.D banner / alias_of (per pair).
- 2 × alias minimal markdown validity (per pair).
- 1 × redirect map inventory count matches ALIAS_PAIRS.

## Constraints honored (per memory contract)

- `feedback_destruction_free_organization` — `rm` / `mv` 禁止 — verified
  by `git status` showing only `??` (untracked new) lines for the 4 new
  files; no `M` line for either `autonomath_*.md`.
- `project_autonomath_canonical_docs` — canonical content remains the
  single source of truth; aliases are discovery layer only.
- `feedback_legacy_brand_marker` — AutonoMath / zeimu-kaikei.ai marker
  is intentionally minimal (frontmatter + 1 paragraph mention).
- `feedback_no_user_operation_assumption` — verified by 5 commands
  (`ls docs/canonical/`, `find docs -name "autonomath*.md"`,
  `wc -l`, `git status`, `pytest`) before declaring the path
  divergence; no manual operator step required.
- `feedback_no_quick_check_on_huge_sqlite` — N/A (no DB touched).
- `feedback_loop_never_stop` + `feedback_action_bias` — proceeded
  despite literal-path no-op by adapting scope; no halt waiting for
  user disambiguation.

## Forbidden surfaces (per task brief) — verified absent

- ✗ `rm` / `mv` of `autonomath_*.md` — none performed.
- ✗ Edits to canonical content — `git diff docs/_internal/autonomath_*.md`
  is empty.
- ✗ Main worktree usage — all work in `/tmp/jpcite-w46-rename-47d`.
- ✗ Old brand surfaced prominently — banner is one paragraph,
  frontmatter only.
- ✗ LLM API calls — none (markdown + pytest only).

## PR scope

- **Branch**: `feat/jpcite_2026_05_12_wave46_rename_47d_docs_canonical`
- **Base**: `main` (HEAD `3aae4f345` at branch creation).
- **Diff**: 4 new files, 495 LOC, 0 deletions, 0 modifications to
  existing files.
- **CI surface**: pytest (22 new tests, all green), markdown valid,
  no source-code change.

## Follow-ups (not part of this PR)

- A future Wave 46.E (or later) can extend the alias batch to
  `research/_archive/pre_launch_decisions/autonomath_invalid_enriched.md`
  if internal grep traffic shows demand — currently archived, low
  signal.
- If `docs/canonical/autonomath_*.md` files appear in a future wave,
  the same alias contract (frontmatter + banner + redirect map row)
  applies — add new aliases alongside, never edit the source.
