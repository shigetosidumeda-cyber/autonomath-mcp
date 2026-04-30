# SDK Republish After jpcite Rename (2026-04-30)

The brand rename from `AutonoMath` / `税務会計AI` to `jpcite` (domain: `jpcite.com`)
touched the SDK package metadata (`description`, `homepage`, `repository`,
`bugs.url`). Package names (`autonomath` on PyPI, `@autonomath/sdk` on npm)
were intentionally left unchanged so existing consumers do not have to rewrite
their `import` / `pip install` lines.

End users see the homepage URL on `pypi.org/project/autonomath/` and on
`npmjs.com/package/@autonomath/sdk` — the rendered URL there comes from the
metadata baked into the published artifact, **not** from the GitHub repo. So a
repo-only edit is invisible to them. To surface the new `jpcite.com` URL on
the registry pages, the artifacts must be re-uploaded.

## Files updated locally

| File | Changes |
| --- | --- |
| `sdk/python/pyproject.toml` | `description` (jpcite brand), `[project.urls].Homepage` -> `https://jpcite.com`, added `Bug Tracker` URL |
| `sdk/typescript/package.json` | `description` (jpcite brand), `homepage`, `author.url` -> `https://jpcite.com` |
| `sdk/freee-plugin/marketplace/package.json` | `description` (jpcite brand), added `homepage` / `repository` / `bugs` blocks |

The freee marketplace plugin is `"private": true` and is not published to npm,
so its metadata is informational only — no republish step.

## Republish required (end-user discoverability)

Both public SDKs ship the homepage URL inside the published artifact metadata
that registry pages render. They both need a fresh upload so the rename is
visible.

### PyPI: `autonomath`
- Source: `sdk/python/pyproject.toml`
- Where users see it: <https://pypi.org/project/autonomath/> (Homepage link in
  the sidebar, plus the project description).
- Republish command (run from `sdk/python/`):
  ```bash
  python -m build && twine upload dist/*
  ```

### npm: `@autonomath/sdk`
- Source: `sdk/typescript/package.json`
- Where users see it: <https://www.npmjs.com/package/@autonomath/sdk>
  (Homepage / Repository / Bugs links in the right rail, plus the rendered
  description).
- Republish command (run from `sdk/typescript/`):
  ```bash
  npm publish
  ```

## Do NOT bump version

The only payload here is metadata — no behavior, no API surface, no type
shapes change. Bumping the version would falsely imply a code change and
churn every consumer's lockfile. Republish on the **same** version
(`autonomath==0.1.0`, `@autonomath/sdk@0.3.2`).

PyPI silently allows replacing files at the same version only if `twine
upload` is run with `--skip-existing` against unchanged files; the new
sdist + wheel hashes will differ, so they will be accepted as new uploads
under the same version. npm allows republishing the same `version` only if
no client has installed it yet (24h unpublish window) — if the v0.3.2 tarball
has already been pulled, a `0.3.3` patch bump becomes necessary purely as a
re-upload vehicle (still no code change). Check the registry first:

```bash
# PyPI
curl -s https://pypi.org/pypi/autonomath/json | jq '.urls[].upload_time'

# npm
npm view @autonomath/sdk time
```

If the registry rejects same-version replace, bump only the patch digit and
note "metadata-only republish for jpcite rename" in `CHANGELOG.md`.

## Out of scope

- The main `autonomath-mcp` package at the repo root — separate release
  pipeline (`release.yml`, tag `v*`), bumped via the manifest-bump CLI on
  schedule. Its `pyproject.toml` lives at `/Users/shigetoumeda/jpcite/pyproject.toml`
  and is handled by the launch / manifest-bump workflow, not this rename pass.
- The freee marketplace plugin — `private: true`, no registry presence.
- `sdk/mf-plugin/` — Fly app, not an npm/PyPI package.
