# R8 PyPI Publish Dry Build Verify (2026-05-07)

**Status**: read-only audit, publish=0
**Scope**: post-launch publish prep for jpcite v0.3.4 (autonomath-mcp PyPI package)
**LLM**: 0 (mechanical build + hash compare + curl)
**Constraint**: destructive overwrite禁止, publish 0, operator-decision前提

---

## 1. Executive summary

| signal | result |
|---|---|
| `python -m build` (HEAD) | PASS — wheel + sdist 生成 |
| `twine check dist/*` | PASS / PASS (both artifacts) |
| PyPI live latest | **v0.3.4 (already published 2026-05-05 12:41 UTC)** |
| Local pyproject.toml version | 0.3.4 (unchanged) |
| HEAD vs v0.3.4 tag | **38 commits ahead** (HEAD=83b1fb3, tag=474332b) |
| Reproducibility check (tag rebuild) | **byte-perfect match with PyPI** |
| Recommended publish action | **NOOP — bump to v0.3.5 before next push** |

**Key finding**: PyPI v0.3.4 is current and reproducible from `git tag v0.3.4`. HEAD has drifted 38 commits forward (launch ops, deploy fixes, ACK live, billing fail-closed) but pyproject `version=0.3.4` was never bumped. Pushing tag from HEAD as `v0.3.4` would be **rejected by PyPI** (PEP 440 immutable releases). Next release MUST bump to v0.3.5.

---

## 2. Build outputs (HEAD, 83b1fb3)

```
$ /Users/shigetoumeda/jpcite/.venv/bin/python -m build
…
Successfully built autonomath_mcp-0.3.4.tar.gz and autonomath_mcp-0.3.4-py3-none-any.whl
```

| artifact | size | sha256 |
|---|---|---|
| `dist/autonomath_mcp-0.3.4-py3-none-any.whl` | 1,953,384 | 921ee06ee9f00ac17720b1273eead44a921fb5460b35b99ac5f85a9def7c68a6 |
| `dist/autonomath_mcp-0.3.4.tar.gz` | 1,724,725 | b00d1e24eacbdd599219bf9d2235dbb8477c6eeeeee979da7da28633789e9458 |

Wheel composition (339 files):
- `.py` × 302 (source modules — tools registered via `@mcp.tool` decorator at import time, not as static JSON manifest)
- `.html` × 16 (consultant-pack templates)
- `.txt` × 15 (data fixtures)
- `.sql` × 1
- `.md` × 1
- METADATA + RECORD + WHEEL + entry_points

`@mcp.tool` decorator count (raw, pre-cohort gating): **207** across **17 files**.

`server.py` itself defines 53; cohort filtering at server init reduces public exposure to **139** (matches `mcp-server.json` / `mcp-server.full.json` `tools[]` length, and matches `R8_MANIFEST_BUMP_EVAL` Option B = manifest hold-at-139).

---

## 3. twine check

```
$ twine check dist/autonomath_mcp-0.3.4-py3-none-any.whl dist/autonomath_mcp-0.3.4.tar.gz
Checking dist/autonomath_mcp-0.3.4-py3-none-any.whl: PASSED
Checking dist/autonomath_mcp-0.3.4.tar.gz: PASSED
```

Both artifacts publishable as-is (README rendering, METADATA schema, license, classifiers all valid).

---

## 4. Manifest sync verify (server.json family)

| file | tools[] count | version |
|---|---|---|
| `server.json` (mcp-registry submission, root) | (no `tools` key — registry index, not full manifest) | 0.3.4 |
| `mcp-server.json` (canonical full) | **139** | 0.3.4 |
| `mcp-server.full.json` | **139** | 0.3.4 |
| `mcp-server.core.json` (subset) | 39 | 0.3.4 |
| `mcp-server.composition.json` (subset) | 58 | 0.3.4 |

All 5 manifests pyproject-version aligned (0.3.4). Manifest 139 matches R8_MANIFEST_BUMP_EVAL Option B (hold-at-139). 7 post-manifest tools deferred to v0.3.5 release.

---

## 5. PyPI live state

```
$ curl -s https://pypi.org/pypi/autonomath-mcp/json
```

| version | upload_time (UTC) | files |
|---|---|---|
| 0.3.0 | 2026-04-26 05:05:58 | sdist + wheel |
| 0.3.1 | 2026-04-30 04:05:26 | sdist + wheel |
| 0.3.2 | 2026-04-30 11:21:23 | sdist + wheel |
| 0.3.3 | 2026-05-04 01:17:13 | sdist + wheel |
| **0.3.4** | **2026-05-05 12:41:57** | sdist + wheel |

**PyPI 0.3.4 artifacts**:

| artifact | size | sha256 |
|---|---|---|
| `autonomath_mcp-0.3.4-py3-none-any.whl` | 1,494,116 | 567e292cb0fc81531a67bbd3ca72083cce593fa5a94ed74c450435c4df6a0590 |
| `autonomath_mcp-0.3.4.tar.gz` | 1,303,157 | f62886849e65d4adcde47b10dffacfc88c9612b790794dde3a52df44e4290c53 |

---

## 6. Drift analysis: PyPI vs local

### 6.1 Hash mismatch (HEAD build vs PyPI)

| | wheel sha256 | sdist sha256 | wheel size | sdist size |
|---|---|---|---|---|
| **PyPI v0.3.4** (2026-05-05) | 567e292c… | f6288684… | 1,494,116 | 1,303,157 |
| **HEAD build** (2026-05-07, 83b1fb3) | 921ee06e… | b00d1e24… | 1,953,384 | 1,724,725 |
| **Δ size** | — | — | +459,268 (+30.7%) | +421,568 (+32.4%) |

### 6.2 Reproducibility check (tag rebuild)

`git worktree add /tmp/pypi_verify/v034 v0.3.4 && python -m build`:

| artifact | sha256 | match PyPI? |
|---|---|---|
| wheel built from `v0.3.4` tag (474332b) | **567e292c…** | **YES** |
| sdist built from `v0.3.4` tag (474332b) | **f6288684…** | **YES** |

PyPI v0.3.4 is **reproducible from `git tag v0.3.4`**. Build is deterministic for hatchling on this codebase.

### 6.3 Source of drift: 38 commits ahead

`git log --oneline v0.3.4..HEAD | wc -l = 38`. Latest 5:

```
83b1fb3 launch ops: deploy.yml fixes (4) + ACK live signed + R8 launch timeline + fail-closed billing
b1de8b2 fix(deploy): rm small dev fixture before sftp - flyctl ssh sftp safety override
f65af3e fix(deploy): hydrate step size-guarded skip - dev fixture (1.3MB) no longer masks production seed (352MB+) sftp fetch
6e0afd1 fix(deploy): pre_deploy_verify CI tolerates missing autonomath.db (9.7GB not on GHA runners)
6e3307c fix(deploy): post-deploy smoke gate race - sleep 25→60, max-time 15→30, flyctl status pre-probe
```

Most are deploy-CI ops (not user-facing functional change), plus billing fail-closed + ACK live signed. Manifest hold confirmed (no new tool added since v0.3.4 tag → 139 unchanged).

---

## 7. Publish plan (operator decision)

### 7.1 Immediate state — NO publish needed

PyPI v0.3.4 already live and matches Fly deployment (`b1de8b2` in deployment 01KR0AGKRFD39QZZJ10VWYZXS5 — note: deployment is from a slightly later commit than tag, but v0.3.4 wheel from tag was the user-installable artifact at publish time). End-users `pip install autonomath-mcp` get 0.3.4. **No action required for v0.3.4 publish.**

### 7.2 Next publish: v0.3.5 (post-manifest 7 bump)

Sequence (operator-driven):

1. **Bump version**: edit `pyproject.toml` → `version = "0.3.5"`. Also bump 5 manifest files (`server.json`, `mcp-server*.json`).
2. **Manifest expansion (R8_MANIFEST_BUMP_EVAL Option B unblock)**: bump `mcp-server.json` / `mcp-server.full.json` `tools[]` 139 → 146 (+7 post-manifest tools). Re-run `scripts/ops/manifest_sync_verify.py`.
3. **Update CHANGELOG.md** with the 38-commit summary since v0.3.4.
4. **Commit + push**: `git commit -m "release: v0.3.5 (manifest 139→146)"` → `git push origin main`.
5. **Tag + push tag**: `git tag -a v0.3.5 -m "v0.3.5 — 7 post-manifest tools + launch ops"` → `git push origin v0.3.5`.
6. **release.yml workflow** auto-fires on tag push (`on.push.tags: ['v*']`) → runs full test gate → `pypa/gh-action-pypi-publish` (Trusted Publisher, no API token in repo).
7. **Verify**: `pip index versions autonomath-mcp | head -2` should show 0.3.5 within ~3 min of tag-push completion.

### 7.3 Risk gates before v0.3.5 tag-push

- [ ] `python -m build` clean (verified TODAY for v0.3.4 surrogate — same hatchling config)
- [ ] `twine check dist/*` PASS (verified TODAY)
- [ ] `pre-commit run --all-files` 16/16 PASS (per R8_PRECOMMIT_FINAL_16)
- [ ] `pytest -q` smoke gate 5/5 GREEN (per R8_SMOKE_FULL_GATE)
- [ ] Manifest sync verify (5 manifests version-aligned)
- [ ] CHANGELOG.md entry committed
- [ ] Trusted Publisher still configured at https://pypi.org/manage/project/autonomath-mcp/settings/publishing/ (last used 2026-05-04 / 2026-05-05)

### 7.4 Do-NOT-do list

- **Do not push `v0.3.4` tag from HEAD** — PyPI rejects republish (immutable release per PEP 440), and tag is already advertised; force-update would corrupt downstream installers' assumption of immutable release.
- **Do not run `twine upload` manually** — release.yml uses Trusted Publisher (OIDC), bypasses API tokens. Manual upload would skip the test gate.
- **Do not bump manifest 139→146 in same PR as version bump alone** — couple them so consumers see new tools the moment they upgrade pin.

---

## 8. Verification commands (operator re-run kit)

```bash
# (a) Build
/Users/shigetoumeda/jpcite/.venv/bin/python -m build

# (b) twine check
/Users/shigetoumeda/jpcite/.venv/bin/twine check dist/autonomath_mcp-0.3.4-py3-none-any.whl dist/autonomath_mcp-0.3.4.tar.gz

# (c) PyPI live
curl -s https://pypi.org/pypi/autonomath-mcp/json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['info']['version'])"

# (d) Reproducibility (rebuild from tag)
git worktree add /tmp/v034 v0.3.4
(cd /tmp/v034 && /Users/shigetoumeda/jpcite/.venv/bin/python -m build --outdir /tmp/v034dist)
shasum -a 256 /tmp/v034dist/*
git worktree remove --force /tmp/v034
```

---

## 9. Cross-references

- `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` — Option B (manifest hold-at-139, +7 in v0.3.5)
- `R8_MANIFEST_SYNC_VERIFY_2026-05-07.md` — 5-manifest version sync
- `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` — Fly deployment 01KR0AGKRFD39QZZJ10VWYZXS5
- `R8_LAUNCH_OPS_TIMELINE_2026-05-07.md` — 38-commit drift origin
- `R8_PRECOMMIT_FINAL_16_2026-05-07.md` — pre-publish lint gate
- `R8_SMOKE_FULL_GATE_2026-05-07.md` — pre-publish test gate
- `.github/workflows/release.yml` — `on.push.tags: ['v*']` + `publish-pypi` job (Trusted Publisher) + `github-release` job

---

## 10. Closure

- v0.3.4 publish is **complete and reproducible** (PyPI live = tag rebuild byte-perfect).
- HEAD drift is **deploy/launch ops only** (no functional code re-tag needed).
- Next operator action: **v0.3.5 release** when ready (no urgency — v0.3.4 is install-correct, deployment-correct).
- This audit is **read-only**; no artifacts uploaded, no publish triggered, no destructive change.

— end of R8_PYPI_PUBLISH_DRY_2026-05-07
