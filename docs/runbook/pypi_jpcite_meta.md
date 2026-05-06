---
title: PyPI jpcite meta-package publish
updated: 2026-05-04
operator_only: true
category: brand
---

# PyPI publish runbook — `jpcite` meta-package

> **Operator-only.** Manual publish; not wired into CI by design (see
> `cloudflare-rules.yaml` apply procedure for the same rationale —
> security-adjacent surfaces stay manual).

The `jpcite` distribution on PyPI is a **meta-package** whose only job
is to make `pip install jpcite` resolve to the real `autonomath-mcp`
release. Source lives at `pypi-jpcite-meta/` in the jpcite repo.

## When to bump

Re-publish `jpcite` whenever `autonomath-mcp` ships a release whose
**minor** version changes (0.3.x bug-fix releases are picked up
automatically by the `~=0.3.2` pin in `pypi-jpcite-meta/pyproject.toml`;
no jpcite re-publish needed).

| autonomath-mcp version | jpcite version action |
|---|---|
| 0.3.2 → 0.3.3 (patch) | **No bump** — `~=0.3.2` covers it. |
| 0.3.x → 0.4.0 (minor) | Bump jpcite to 0.4.0, update pin to `~=0.4.0`. |
| 0.x → 1.0.0 (major) | Bump jpcite to 1.0.0, update pin to `~=1.0.0`. |

## Build & publish (manual)

```bash
# 0. Make sure you're on a clean main branch.
cd /path/to/jpcite
git status   # must be clean
git pull --ff-only

# 1. Confirm the autonomath-mcp version you're aliasing.
grep '^version' pyproject.toml
#   version = "0.3.3"

# 2. If a re-pin is needed, edit pypi-jpcite-meta/pyproject.toml:
#    - Bump the meta-package version field
#    - Bump the dependencies pin to match
#    Then commit:
#      git add pypi-jpcite-meta/pyproject.toml
#      git commit -m "chore(jpcite-meta): bump to <new version>"

# 3. Build the sdist + wheel.
cd pypi-jpcite-meta
python -m build
#   dist/jpcite-<version>.tar.gz
#   dist/jpcite-<version>-py3-none-any.whl

# 4. Inspect the artifacts before upload.
python -m twine check dist/*
unzip -l dist/jpcite-*-py3-none-any.whl   # should be METADATA + RECORD only

# 5. Upload to TestPyPI first (one-shot sanity check).
python -m twine upload --repository testpypi dist/*
#   prompts for TestPyPI API token

# 6. Verify in a throwaway venv.
python -m venv /tmp/jpcite-test && source /tmp/jpcite-test/bin/activate
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            jpcite
autonomath-mcp --help    # must work — proves the alias resolved
deactivate && rm -rf /tmp/jpcite-test

# 7. Upload to real PyPI.
python -m twine upload dist/*
#   prompts for the PYPI_TOKEN (Bookyou株式会社 PyPI account)

# 8. Smoke test from a fresh venv against real PyPI.
python -m venv /tmp/jpcite-prod && source /tmp/jpcite-prod/bin/activate
pip install jpcite
autonomath-mcp --help
deactivate && rm -rf /tmp/jpcite-prod
```

## Required credentials

- **PYPI_TOKEN** — Bookyou株式会社 PyPI account API token, scoped to the
  `jpcite` project. Stored in 1Password vault `Bookyou / PyPI`. Do
  **not** put this in `.env` or GitHub Actions secrets — meta-package
  publish is intentionally manual.
- **TESTPYPI_TOKEN** — same account on test.pypi.org for step 5.

## Rollback

There is nothing to roll back. PyPI does not allow re-uploading a
yanked version, so a broken meta-package release is fixed by yanking
the bad version + publishing the next patch.

```bash
python -m twine yank jpcite==<bad-version> \
    --reason "broken pin to autonomath-mcp"
```

The user impact of yanking is small: `pip install jpcite` falls through
to the previous published release (still pinned to a working
autonomath-mcp range), so no install actually fails — only a green-field
`pip install jpcite==<bad-version>` would have hit the broken pin.

## Why not automate?

- The `jpcite` brand is a **trademark-soft** name: if a third party
  challenges the meta-package name we rename rather than litigate
  (memory `feedback_no_trademark_registration`). Manual publish keeps
  the operator in the loop on every release.
- PyPI account 2FA + token rotation is operator-only — wiring it into
  GitHub Actions creates a long-lived secret that we'd rather not
  manage.
- Re-pin frequency is low (only on autonomath-mcp minor bumps). A
  5-minute manual run beats a 60-minute CI debugging session when the
  real autonomath-mcp release pipeline already covers the heavy lifting.

## Cross-references

- `pypi-jpcite-meta/pyproject.toml` — meta-package source.
- `pyproject.toml` (repo root) — real `autonomath-mcp` distribution.
- `docs/runbook/github_rename.md` — companion rename runbook for the
  GitHub repository (`autonomath-mcp` → `jpcite-mcp`).
- memory `project_jpcite_rename` — brand history and 301 redirect plan.
