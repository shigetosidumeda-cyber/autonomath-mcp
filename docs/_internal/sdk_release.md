# SDK Release Guide

This document describes how to publish the Python and TypeScript SDKs to PyPI
and npm via the `sdk-publish` GitHub Actions workflow
(`.github/workflows/sdk-publish.yml`).

The main API package (`jpintel-mcp` at the repo root) has its own release
pipeline (`release.yml`, tag `v*`). The SDK pipeline is completely separate and
uses namespaced tags so the two never collide.

---

## Release flow (per SDK)

1. **Bump version** in the SDK manifest:
   - Python: `sdk/python/pyproject.toml` -> `[project].version`
   - TypeScript: `sdk/typescript/package.json` -> `version`
2. **Update `CHANGELOG.md`** at repo root under a new `## [<version>]` header
   (moving entries out of `## [Unreleased]`).
3. **Commit** the bump: `git commit -am "chore(sdk): bump python SDK to 0.2.0"`.
4. **Tag** with the namespaced format:
   - Python: `git tag sdk-python-v0.2.0`
   - TypeScript: `git tag sdk-ts-v0.2.0`
5. **Push** commit + tag: `git push origin main --follow-tags`.
6. GitHub Actions picks up the tag, runs tests, builds, publishes to the
   registry, and creates a GitHub release.

**Manual dispatch** (for re-running a failed publish or dry-running):
Actions -> `sdk-publish` -> Run workflow -> pick `python`, `ts`, or `both`.

---

## Versioning scheme

- **SDK major = API major.** When the API bumps from `v1` -> `v2`, both SDKs
  bump to `2.0.0` on the same day.
- **SDK minor / patch are independent** of the API. A bug fix in the Python SDK
  that doesn't touch the API bumps `0.1.0` -> `0.1.1` for Python only.
- **Pre-v1:** while the API is pre-launch (before 2026-05-06), SDKs stay on
  `0.x.y`. First stable release is `1.0.0` on API GA.
- **Pre-releases** use `-alpha.N`, `-beta.N`, `-rc.N`. The workflow auto-marks
  the GitHub release as a pre-release whenever the tag contains `-`.

---

## GitHub secrets required

Add these under **Settings -> Secrets and variables -> Actions** (or to the
`pypi` / `npm` environments if you want approval gates).

| Secret           | Used by           | Notes                                          |
|------------------|-------------------|------------------------------------------------|
| `PYPI_API_TOKEN` | `publish-python`  | Scoped to the `jpintel` PyPI project.          |
| `NPM_TOKEN`      | `publish-ts`      | Automation token with publish rights.          |

### PyPI: prefer OIDC trusted publishing

The workflow already requests `id-token: write`. To eliminate the long-lived
API token:

1. Go to <https://pypi.org/manage/account/publishing/>.
2. Add a new **pending publisher** with:
   - Owner: your GitHub org/user
   - Repo: `jpintel-mcp`
   - Workflow: `sdk-publish.yml`
   - Environment: `pypi`
3. After the first trusted publish succeeds, delete `PYPI_API_TOKEN` from
   Actions secrets and remove the `password:` line from the
   `pypa/gh-action-pypi-publish` step.

### Rotating tokens

- **PyPI:** <https://pypi.org/manage/account/token/> -> Revoke old, create new
  scoped token, update `PYPI_API_TOKEN` secret. Rotate every 90 days minimum.
- **npm:** <https://www.npmjs.com/settings/~/tokens> -> Revoke old, create new
  Automation token (CI/CD, read+publish), update `NPM_TOKEN`. npm tokens do
  not expire by default; set a calendar reminder.

If a token is ever leaked (public commit, CI log, screenshot), revoke
immediately and rotate. The workflow will fail fast on the next publish until
the secret is replaced.

---

## First-time publish setup

Before the very first tag push, you need to **claim the package names** on
each registry. Otherwise the publish step will 403.

### Name availability (checked 2026-04-23)

| Candidate         | PyPI       | npm                  |
|-------------------|------------|----------------------|
| `jpintel`         | available  | available            |
| `@autonomath/client` | n/a     | available (scoped)   |
| `jpinst`          | available  | available            |
| `@jpinst/client`  | n/a        | available (scoped)   |
| `jpi-data`        | available  | not checked          |

All candidates are currently unclaimed on both registries, so first-mover
wins. **Update (2026-04-24):** The TypeScript SDK was renamed from `@jpintel/client`
to `@autonomath/client` before any npm publish, eliminating the Intel trademark
overlap risk (`project_jpintel_trademark_intel_risk`). The npm name
`@autonomath/client` is available (404 on registry as of 2026-04-24). The Python
SDK PyPI name should similarly target `autonomath-client` rather than `jpintel`.

### Claiming names

- **PyPI:** first `twine upload` (or trusted publish) with an unused name
  auto-claims it. No web step required.
- **npm:** first `npm publish --access public` on a scoped package
  (`@autonomath/*`) auto-creates the scope under your user/org. For unscoped
  names, the name is claimed on first publish; if squatted later, recovery
  requires an npm support ticket.

### Checklist before the first tag push

- [x] Trademark decision locked in: `@autonomath/client` (renamed 2026-04-24, no jpintel brand).
- [x] SDK manifests updated to final name (`@autonomath/client`).
- [ ] `PYPI_API_TOKEN` secret set (or OIDC trusted publisher configured).
- [ ] `NPM_TOKEN` secret set, Automation token type, with publish scope.
- [ ] `pypi` and `npm` GitHub environments created (optional: add manual
      approval requirement as a final guardrail).
- [ ] `CHANGELOG.md` has a filled-in section for the target version.
- [ ] Main API `/health` and OpenAPI already live (SDK should not ship against
      a URL that 404s).

---

## Troubleshooting

- **403 on PyPI upload:** token scope doesn't cover the project name, or the
  name was claimed by someone else between now and publish. Check
  <https://pypi.org/project/jpintel/>.
- **403 on npm publish:** scope not created yet, or `NPM_TOKEN` is read-only
  instead of Automation. Re-run after `npm access ls-packages` from a shell
  with the same token.
- **Tests fail in CI but pass locally:** the workflow runs Python 3.13 and
  Node 20. Reproduce locally with the exact versions.
- **Workflow runs twice on one tag:** make sure you only push the tag once
  (`git push --tags` without `--follow-tags` can desync).
