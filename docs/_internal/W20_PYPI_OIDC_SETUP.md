# W20 — PyPI OIDC Trusted Publishing setup runbook

One-time owner action to wire `.github/workflows/release.yml` to PyPI without
any long-lived API token. After this is registered, every `git tag vX.Y.Z &&
git push --tags` will publish to https://pypi.org/p/autonomath-mcp via OIDC.

## Steps

1. Sign in at PyPI as the project owner of `autonomath-mcp`.
2. Open the trusted-publisher console:
   https://pypi.org/manage/account/publishing/
3. Click **Add a new pending publisher** (if the project is not yet
   registered) or **Add a new publisher** under the existing project.
4. Fill in the form exactly as below — values must match the workflow file
   character-for-character or the OIDC exchange will be rejected:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `autonomath-mcp` |
   | Owner | `shigetosidumeda-cyber` |
   | Repository name | `autonomath-mcp` |
   | Workflow filename | `release.yml` |
   | Environment name | `pypi` |

5. Save. PyPI will now accept OIDC tokens issued by the GitHub Actions run
   identified by (owner, repo, workflow, environment).

## Workflow contract

`release.yml` declares:

- `permissions: id-token: write` — required for GitHub to mint the OIDC token.
- `environment: name: pypi` — must match step 4 above.
- `pypa/gh-action-pypi-publish@release/v1` — performs the OIDC handshake and
  uploads `dist/*`. No token, no password.

## Verify

- Tag pattern `v*.*.*` does NOT collide with the other publish workflows in
  this repo:
  - `sdk-publish.yml`            — `sdk-python-v*`, `sdk-ts-v*`
  - `sdk-publish-agents.yml`     — `agents-v*`
  - `mcp-registry-publish.yml`   — `workflow_dispatch` only
- Smoke (no publish): `gh workflow run release.yml` from `main`. The
  `workflow_dispatch` path runs the same build + twine check but the
  publish step skips when no matching dist exists / when re-published.

## Operator note

This task only wires the workflow + runbook. Live publish runs only when an
operator pushes a tag matching `v*.*.*`. Do NOT push a tag from this task.
