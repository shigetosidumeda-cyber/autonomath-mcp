# Codex Hook Reverify - 2026-05-17

Agent: Codex Agent A
Worktree: `/Users/shigetoumeda/jpcite-codex-evening`
Branch: `codex-evening-2026-05-17`
Verified HEAD: `0f463d4991841680264e021dd6c66025e4a51b27` (`origin/main`)

## Scope

Prompt scope was limited to hook-escape investigation and this report. No live
AWS command was run. No protected source areas were edited. This report is the
only file intentionally written by this agent.

Read before verification:

- `docs/_internal/CODEX_CLI_HANDOFF_2026_05_17.md`
- User evening update in the prompt
- `docs/_internal/REPLAY_AFTER_UNBLOCK_2026_05_17.md`
- `docs/_internal/UNBLOCK_MANIFEST_DRIFT_2026_05_17.md`
- `docs/_internal/UNBLOCK_2_DRIFT_2026_05_17.md`

## Repo State

- `git fetch origin main --prune` completed.
- Local branch fast-forward check: already at `origin/main`.
- HEAD equals `origin/main`: `0f463d4991841680264e021dd6c66025e4a51b27`.
- Existing unrelated untracked docs were present during this lane:
  - `docs/_internal/CODEX_AA5_NARRATIVE_VERIFY_2026_05_17.md`
  - `docs/_internal/CODEX_PLAN_ONLY_STUB_AUDIT_2026_05_17.md`

## Safe Commit Dry-Run Limitation

`scripts/safe_commit.sh` has no native dry-run mode. It is a wrapper around:

```bash
git commit "$@"
```

Passing `--dry-run` would delegate to `git commit --dry-run`; that does not
prove the pre-commit hook set, does not advance HEAD, and would make
`safe_commit.sh` report its normal "HEAD did not advance" abort diagnostic.
Therefore I did not treat `bash scripts/safe_commit.sh --dry-run` as a valid
hook reverify. I ran non-mutating underlying checks instead.

## Per-Commit Replay / Escape Status

| Commit | Current main status | Escape evidence | Replay conclusion |
|---|---|---|---|
| `8076edaf9` | Ancestor of `origin/main` | No `--no-verify`, `--no-gpg-sign`, or `SKIP=` in subject/body/diff. | Replayed as itself; clean for hook-escape review. |
| `04d48b429` | Ancestor of `origin/main` | No `--no-verify`, `--no-gpg-sign`, or `SKIP=` in subject/body/diff. | Replayed as itself; clean for hook-escape review. |
| `ee5f61bab` | Ancestor of `origin/main` | Contains policy text banning `--no-verify` / `--no-gpg-sign`; no bypass command or `SKIP=` usage. | Replayed as itself; policy-text-only hits are not escape evidence. |
| `9296b226d` | Not an ancestor of `origin/main` | Commit body contains explicit `--no-verify rationale`, stating the bypass was used because concurrent agents and manifest drift blocked hooks. | Patch replayed into `origin/main` as `75ad67718` with identical stable patch-id (`3b7febadeff8c9f0c503ca5d911b23763f24186d`), but the replayed commit body still carries the `--no-verify rationale`. This is confirmed historical escape evidence. |
| `076f466f0` | Ancestor of `origin/main` | No `--no-verify`, `--no-gpg-sign`, or `SKIP=` in subject/body/diff. | Replayed as itself; clean for hook-escape review. |

Additional history note: `git log --all --grep='SKIP='` still finds older
commit messages documenting hook skips outside the five requested SHAs
(`02adbcde9`, `c31e2e003`, `a8bfee085`, `f125c60ac`) plus the UNBLOCK-2
commit message saying no skip was used. I did not rewrite history.

## Current Hook-Escape Search

Search for executable bypass patterns in scripts/workflows/config:

```text
git (commit|push|rebase|merge) ... (--no-verify|--no-gpg-sign|--no-edit)
SKIP=...(pre-commit|distribution-manifest-drift|ruff|mypy|bandit|gitleaks)
```

Result: one hit only:

```text
scripts/safe_commit.sh:17: comment documenting "NO --no-verify, NO --no-gpg-sign"
```

I found no active script or workflow command that invokes a git/pre-commit
escape. The remaining hit is a defensive policy comment, not an escape path.

## Non-Mutating Hook / Check Results

Passed:

- `python3 scripts/check_distribution_manifest_drift.py`
  - `[check_distribution_manifest_drift] OK - distribution manifest matches static surfaces.`
- `.venv/bin/pre-commit run distribution-manifest-drift --all-files`
- `.venv/bin/pre-commit run check-yaml --all-files`
- `.venv/bin/pre-commit run check-json --all-files`
- `.venv/bin/pre-commit run check-toml --all-files`
- `.venv/bin/pre-commit run check-merge-conflict --all-files`
- `.venv/bin/pre-commit run yamllint --all-files`
- `.venv/bin/pre-commit run check-added-large-files --all-files`
- `.venv/bin/pre-commit run check-executables-have-shebangs --all-files`
- `.venv/bin/pre-commit run gitleaks --all-files`
- `.venv/bin/ruff check src scripts tests`
  - Passed with a warning about an invalid `# noqa` directive in
    `tests/test_no_llm_in_production.py:172`.

Failed / blocked:

- `.venv/bin/python -m pytest tests/test_no_hook_bypass_in_scripts.py tests/test_distribution_manifest.py -q`
  - `tests/test_distribution_manifest.py`: passed/slow-skipped.
  - `tests/test_no_hook_bypass_in_scripts.py`: 2 failures.
  - Failure 1: flags `scripts/safe_commit.sh:17`, a policy comment, as a
    forbidden bypass line.
  - Failure 2: expects `CLAUDE.md` to contain `--no-verify` and
    `--no-gpg-sign`; H3 moved canonical policy into `AGENTS.md`, leaving the
    test stale.
- `.venv/bin/mypy src/jpintel_mcp/ --strict`
  - 5 errors:
    - missing `jpintel_mcp.billing.pricing_v2`
    - missing stubs for `botocore.auth`
    - missing stubs for `botocore.awsrequest`
    - missing `jpintel_mcp.mcp.moat_lane_tools.moat_n6_alert`
    - missing `jpintel_mcp.mcp.moat_lane_tools.moat_n7_segment`
- `.venv/bin/ruff format --check src scripts tests`
  - 291 files would be reformatted; many are in protected
    `scripts/aws_credit_ops/`, so I did not touch them.
- `.venv/bin/pre-commit run check-shebang-scripts-are-executable --all-files`
  - Failed. Independent count found 421 tracked files with shebangs but without
    executable mode; 274 are under protected `scripts/aws_credit_ops/`.
- `.venv/bin/pre-commit run bandit --all-files`
  - Failed with 78 total issues: 12 low, 66 medium, 0 high.

## Conclusion

UNBLOCK / UNBLOCK-2 fixed the distribution-manifest drift path: the drift hook
is currently clean on `origin/main`, and no `SKIP=distribution-manifest-drift`
is needed for that hook.

However, current `origin/main` is not fully clean under a repo-wide hook
posture. The remaining blockers are not distribution drift: stale hook-bypass
tests, mypy import/stub errors, repo-wide ruff-format drift, shebang executable
mode drift, and bandit findings. Several blockers are in protected AWS scope,
so they remain documented only in this lane.

Historical escape status is not fully clean either: `9296b226d` was not kept as
an ancestor, but its patch is present as `75ad67718`, and the replayed commit
body still records an explicit `--no-verify rationale`.
