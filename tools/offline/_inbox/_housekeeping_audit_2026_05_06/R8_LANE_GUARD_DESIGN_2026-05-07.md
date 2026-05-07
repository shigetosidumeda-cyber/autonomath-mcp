# R8 — lane policy CI guard activation design (1-CLI solo vs 2-CLI resume)

| field | value |
|---|---|
| date | 2026-05-07 (JST) |
| auditor | session_a (1-CLI solo) — 梅田茂利 / Bookyou株式会社 |
| HEAD | `2953db1` (main) |
| upstream context | R8_LANE_LEDGER_AUDIT_2026-05-07.md (1-CLI solo confirmed; codex dormant since 2026-04-29) |
| scope | read-only audit + 1 doc write (this file). 0 file edits, 0 LLM calls, 0 destructive ops |
| framing | 1-CLI lane override is **legitimate operator flexibility**, not a policy bug. Goal = preserve 2-CLI guard fidelity for future codex resume while not blocking solo session A from touching codex-lane paths today. |

---

## 1. Existing enforcer state (DEEP-60, as of HEAD 2953db1)

| artifact | path | state |
|---|---|---|
| enforcer | `scripts/ops/lane_policy_enforcer.py` (331 lines, stdlib + subprocess + git only) | live, LLM-import-free |
| policy SOT | `scripts/ops/lane_policy.json` (62 lines, $schema_version 1.0.0) | live, defines 2 lanes (session_a / codex) + shared (AGENT_LEDGER.csv only) |
| pre-commit hook | `tools/offline/operator_review/pre-commit-hook.sh` (66 lines) | reads `JPCITE_LANE` env / `git config jpcite.lane`, supports `JPCITE_LANE_OVERRIDE` + `JPCITE_LANE_SIGNOFF` env passthrough to `--bypass-with-reason` / `--operator-signoff` |
| CI workflow | `.github/workflows/lane-enforcer-ci.yml` (131 lines) | resolves lane from `session-a/*` branch prefix or `[lane:session_a]` / `[lane:codex]` commit-msg tag; defaults to `codex`. Comments on PR with rendered stdout/stderr on violation. |
| test suite | `tests/test_lane_policy_enforcer.py` (221 lines, 8 cases, stdlib unittest) | 1=allowed_ok / 2=forbidden_blocks / 3=bypass_with_reason / 4=policy_parses / 5=GHA_syntax / 6=hook_bash_syntax / 7=no_LLM_imports / 8=ledger_appended |
| ledger | `tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv` (6 rows: 1 hdr + 5 data, append-only intact) | live; last row = R8_lane_ledger_audit at 2026-05-07T00:53:48Z |

**Override mechanism today**: every commit that crosses lane uses `--bypass-with-reason "<>=24 chars>" --operator-signoff <name>` and gets a row in AGENT_LEDGER.csv. **`reason_min_chars=24` is the only ergonomic friction in 1-CLI mode** — operator must write a 24+ char justification per offending commit batch.

**Last-25-commit reality**: 49/51 files at HEAD~0 are codex-lane; identical pattern across HEAD~1..HEAD~24 (R8_LANE_LEDGER_AUDIT §3). All 25 commits would either need `--bypass-with-reason` or be classified as `--lane codex` directly. Today operator picks the latter — `git config jpcite.lane codex` likely set, or hook un-installed.

---

## 2. 1-CLI / 2-CLI mode-switch design (no file edit; spec only)

### 2.1 Goals

1. While 1-CLI solo: session A may write to codex lane paths without per-commit `--bypass-with-reason` friction.
2. While 2-CLI active: strict mode resumes — session A blocked from `src/`/`scripts/`/`.github/workflows/`/`site/`, codex blocked from `tools/offline/_inbox/`.
3. Mode switch is **operator-explicit**, not auto-detected from process tables (avoids false-positive switches when codex is just idle on another tty).
4. Audit trail preserved on **both** sides — every cross-lane write still appends a ledger row.

### 2.2 Single-source-of-truth mechanism

Add an optional top-level key `solo_mode` to `lane_policy.json` (NOT yet edited; spec only). Two equivalent shapes:

```jsonc
// shape A — boolean flag
{
  "$schema_version": "1.1.0",
  "solo_mode": {
    "enabled": true,
    "operator": "umeda",
    "since_utc": "2026-04-29T00:00:00Z",
    "reason": "codex CLI dormant; session A acting as both lanes",
    "auto_log_to_ledger": true
  },
  "lanes": { /* unchanged */ }
}
```

```jsonc
// shape B — additive lane (recommended; backward-compatible)
{
  "$schema_version": "1.1.0",
  "lanes": {
    "session_a": { /* unchanged 2-CLI strict */ },
    "codex": { /* unchanged 2-CLI strict */ },
    "solo": {
      "owner_role": "1-CLI operator (session A merged with codex)",
      "allowed_paths": ["**"],
      "forbidden_paths": [],
      "violation_severity": "log_only",
      "requires_operator_signoff": true,
      "ledger_prefix": "[solo]"
    }
  }
}
```

**Recommendation = shape B** (additive). Reasons:
- No conditional branch in `lane_policy_enforcer.py`'s `detect_violations()` — the existing classify/forbidden/allowed walk works as-is when lane=`solo`.
- `argparse` `choices=("session_a", "codex")` becomes `choices=("session_a", "codex", "solo")` — 1-line change, future PR.
- Schema version bump (1.0.0 → 1.1.0) signals additive change; tests #4 (parses) + #5 (GHA syntax) need 1 assert each.
- 2-CLI strict mode is preserved verbatim — when codex resumes, just stop using `--lane solo`.

### 2.3 Pre-commit hook resolution order (no file edit; spec only)

Replace step 3 in `pre-commit-hook.sh` § "resolve LANE" with:

```bash
# 1. explicit env override
LANE="${JPCITE_LANE:-}"

# 2. fall back to git config
if [[ -z "${LANE}" ]]; then
  LANE="$(git config --get jpcite.lane 2>/dev/null || true)"
fi

# 3. fall back to policy.solo_mode (NEW — 1-CLI default)
if [[ -z "${LANE}" ]]; then
  if python3 -c "import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if d.get('lanes',{}).get('solo') else 1)" \
       "${REPO_ROOT}/scripts/ops/lane_policy.json" 2>/dev/null; then
    LANE="solo"
    echo "[lane-hook] solo_mode lane in policy; defaulting to LANE=solo (1-CLI mode)" >&2
  fi
fi

# 4. final fail
if [[ -z "${LANE}" ]]; then
  echo "[lane-hook] FAIL: JPCITE_LANE / git config jpcite.lane / policy.solo unset" >&2
  exit 1
fi
```

This means: when policy.lanes.solo exists, **default behaviour = 1-CLI solo**; explicit env/config still wins for strict-lane manual checks. Removing the `solo` lane from policy.json on codex resume reverts the hook to its current require-explicit-lane behaviour.

### 2.4 GHA workflow resolution (no file edit; spec only)

Today `lane-enforcer-ci.yml` step "Resolve lane from PR / commit metadata" defaults to `codex`. For 1-CLI mode, prepend a 4th rule:

```yaml
- name: Resolve lane (4-rung ladder)
  id: lane
  run: |
    set -euo pipefail
    BRANCH=...
    LANE="codex"
    # rung 1: branch prefix
    if [[ "${BRANCH}" == session-a/* ]]; then LANE="session_a"; fi
    # rung 2: commit msg [lane:session_a] / [lane:codex]
    MSG="$(git log -1 --pretty=%B)"
    if echo "${MSG}" | grep -q '\[lane:session_a\]'; then LANE="session_a"; fi
    if echo "${MSG}" | grep -q '\[lane:codex\]'; then LANE="codex"; fi
    # rung 3: NEW — [lane:solo] explicit solo override
    if echo "${MSG}" | grep -q '\[lane:solo\]'; then LANE="solo"; fi
    # rung 4: NEW — implicit solo if policy.lanes.solo exists AND no rung 1-3 hit
    if [[ "${LANE}" == "codex" ]] && python3 -c "import json,sys;d=json.load(open('scripts/ops/lane_policy.json'));sys.exit(0 if d.get('lanes',{}).get('solo') else 1)"; then
      # only flip when ladder hadn't been hit explicitly above
      if ! echo "${MSG}" | grep -qE '\[lane:(session_a|codex|solo)\]'; then
        LANE="solo"
      fi
    fi
    echo "lane=${LANE}" >> "$GITHUB_OUTPUT"
```

### 2.5 2-CLI resume protocol (operator-explicit, not auto-detect)

When operator wants to bring codex back online:

1. **Append ledger row first** (before any code change, atomic mkdir-style claim):
   ```
   <hex16>,<utc>,resume_2cli/<date>,coordination,scripts/ops/lane_policy.json,0,resume_2cli_disable_solo_mode_codex_attaching,umeda
   ```
2. **Edit `lane_policy.json`**: remove the `solo` lane entry (and bump schema version 1.1.0 → 1.2.0 for clarity).
3. From this moment forward both pre-commit hook (§2.3 rung 3 fails fast) and GHA (§2.4 rung 4 fails) revert to strict 2-CLI behaviour. Existing tests #1 + #2 + #3 stay green; no new test required.
4. Codex CLI sets `git config jpcite.lane codex` once on its workstation; session A keeps `git config jpcite.lane session_a`.

**Auto-detection of codex liveness via `ps aux | grep codex` is explicitly rejected**: per R8_LANE_LEDGER_AUDIT §1, codex node processes attach to other ttys without writing files for hours/days. False-positive flips would break either side mid-commit. Operator-explicit toggling is the safer protocol.

---

## 3. Verification matrix (existing CI guard runs through 1-CLI override OK?)

| scenario | enforcer outcome today | enforcer outcome with `solo` lane | passes? |
|---|---|---|---|
| session A writes `tools/offline/_inbox/...` | OK (lane=session_a) | OK (lane=solo, all paths allowed) | yes |
| session A writes `src/jpintel_mcp/...` | FAIL unless `--bypass-with-reason` | OK (lane=solo) | yes |
| codex writes `src/jpintel_mcp/...` | OK (lane=codex) | OK (lane=codex; solo lane not selected) | yes — strict mode preserved |
| codex writes `tools/offline/_inbox/...` | FAIL (lane=codex forbidden) | FAIL (lane=codex; solo not selected since codex sets explicit lane) | yes — strict mode preserved |
| commit msg has `[lane:codex]` while solo policy live | classified codex strict | classified codex strict (msg tag wins § GHA rung 2-3 before rung 4) | yes |
| empty commit (zero staged paths) | "nothing to check" rc=0 | "nothing to check" rc=0 | yes (enforcer line 200-202 short-circuits) |

**Conclusion**: existing CI guard behaves correctly under proposed solo-mode addition without code changes to `detect_violations()` or test refactor. The 8 unit tests stay green; only #5 (GHA YAML parse) needs +1 line per added rung — and that change is on the workflow file, not the enforcer.

---

## 4. R8 doc deliverables + git-add status

- this file: `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_LANE_GUARD_DESIGN_2026-05-07.md`
- 0 source edits (read-only audit constraint honored)
- 0 LLM calls (constraint honored)
- staged via `git add -f` (path is under tools/offline/_inbox/, lane=session_a, no override needed)

## 5. Honest limitations

- This is **design only**. No `lane_policy.json` `solo` lane added yet, no `pre-commit-hook.sh` rung 3 added yet, no `lane-enforcer-ci.yml` rung 3-4 added yet, no schema-version bump committed. Activation requires explicit operator decision + a future PR touching codex-lane files (which itself would need `[lane:solo]` commit tag or an active solo policy entry — chicken-and-egg, so first PR must use `--bypass-with-reason "bootstrap solo_mode lane addition"` with `--operator-signoff umeda`).
- 1-CLI mode is not free of accidental drift. Operator can still type `git add` against a wrong path; the pre-commit hook + ledger remain the only guard. Solo-mode reduces friction but does not add safety.
- Auto-rollback when codex returns is operator-driven; no daemon watches for codex liveness. R8_LANE_LEDGER_AUDIT confirmed this is the right tradeoff for solo ops with zero infra.

---

EOF
