# npm Publish Runbook (Operator Only)

This runbook covers the operator workflow for publishing the AutonoMath
TypeScript SDK to the public npm registry. Internal-only: do not link
from public docs. Subagents are blocked from publishing because the
required token is not in the harness env (verified 2026-04-25, F5).

## Package facts (as of 2026-04-25)

- Source: `sdk/typescript/`
- Name: `@autonomath/sdk`
- Version: `0.2.0`
- License: MIT
- Tarball: `dist/npm-sdk/autonomath-sdk-0.2.0.tgz` (built via `npm pack`)
- Tarball size: 19.8 kB (19,753 bytes)
- Unpacked size: 76.3 kB
- Files in tarball: 19
- shasum (sha-1): `2ce98c820fe1dc5d75e35fa44b7a990ba36b5053`
- shasum (sha-256): `3b0ff64cb9f5c67eb49a8c4a877b21d4d97a2a2679467ad6f0e43e139c324e0f`
- md5: `8a74e7ea5b7b1be38460979b30f181c8`
- integrity: `sha512-W6cnaZ5nz+wSF[...]MPw1BbxdMCZTg==` (full value emitted by `npm pack`)

## Why subagents cannot publish

`npm whoami` returns `ENEEDAUTH`; `~/.npmrc` does not exist; `$NPM_TOKEN`
is unset in the harness. Publishing is therefore an operator-only step.
Subagents must not write npm tokens to disk or to docs.

## Prerequisites

- npm account: https://www.npmjs.com/ (the human operator's account)
- npm 2FA enabled (recommended; required for "Automation" tokens too)
- Granular access token with `Publish` scope:
  https://www.npmjs.com/settings/<USER>/tokens
- The `autonomath` org must exist on npm (see § Scope check below)

## Scope check (one-time, before first publish)

`@autonomath/sdk` is a scoped package. The scope must be reachable by
the operator's account. Two valid paths:

1. **Org-owned scope (preferred).** Create the npm org `autonomath`
   (https://www.npmjs.com/org/create), then add the operator as Owner.
   The org name `autonomath` must be available; if taken, fall back to
   path 2.
2. **User-owned scope (fallback).** Rename the package to `autonomath-sdk`
   (no scope) by editing `sdk/typescript/package.json`:

   ```diff
   -  "name": "@autonomath/sdk",
   +  "name": "autonomath-sdk",
   ```

   Then rebuild: `npm run build && npm pack`. Update `README.md` install
   instructions and any inline references in `docs/` accordingly. The
   public install path becomes `npm install autonomath-sdk`.

Decide path before publishing — once `0.2.0` is published under either
name, that name is permanently consumed and cannot be reclaimed.

## One-time login

```bash
# Option A: interactive login (writes ~/.npmrc)
npm login --scope=@autonomath --registry=https://registry.npmjs.org/
# Browser will open for OAuth + 2FA

# Option B: token in ~/.npmrc (CI / non-interactive)
echo "//registry.npmjs.org/:_authToken=$NPM_TOKEN" > ~/.npmrc
chmod 600 ~/.npmrc
```

Verify:

```bash
npm whoami    # should print your npm username
```

## Smoke test (no publish)

Always rebuild and dry-run pack first.

```bash
cd sdk/typescript
rm -rf dist/
npm run build
npm pack --dry-run 2>&1 | tail -20
```

Expected tail:

```
npm notice name: @autonomath/sdk
npm notice version: 0.2.0
npm notice filename: autonomath-sdk-0.2.0.tgz
npm notice package size: 19.8 kB
npm notice unpacked size: 76.3 kB
npm notice total files: 19
```

If size or file count drifts unexpectedly, stop — investigate before
publishing. The published tarball is immutable.

## Publish (LIVE)

```bash
cd sdk/typescript
npm publish --access public
# 2FA OTP prompt will appear if account is in "auth-and-writes" mode
```

Successful output ends with:

```
+ @autonomath/sdk@0.2.0
```

## Manual tarball upload (alternative)

If `npm publish` fails repeatedly, the prebuilt tarball at
`dist/npm-sdk/autonomath-sdk-0.2.0.tgz` can be uploaded by passing the
file path directly:

```bash
npm publish --access public dist/npm-sdk/autonomath-sdk-0.2.0.tgz
```

Web upload via the npm UI is not supported — npm only accepts CLI
publishes. There is no operator workaround for missing CLI auth.

## Verify publish

```bash
# 1. Listing should be live within ~30s
curl -sS https://registry.npmjs.org/@autonomath/sdk | python3 -m json.tool | head -30

# 2. Page renders
open https://www.npmjs.com/package/@autonomath/sdk

# 3. Install smoke test in a clean dir
cd /tmp && rm -rf autonomath-sdk-verify && mkdir autonomath-sdk-verify && cd autonomath-sdk-verify
npm init -y > /dev/null
npm install @autonomath/sdk@0.2.0
node -e "import('@autonomath/sdk').then(m => console.log(Object.keys(m)))"
```

If the package was renamed to `autonomath-sdk` (no scope), substitute
that name everywhere above.

## Post-publish

1. Append a row to `docs/_internal/npm_publish_log.md` (timestamp, sha,
   publisher).
2. Update `README.md` install section if name changed.
3. Tag the release in git: `git tag npm-sdk-v0.2.0 && git push --tags`.
4. Bump `sdk/typescript/package.json` version for the next release —
   the current `0.2.0` is now permanent.

## Deprecate / unpublish

- Within 72 h of publish: `npm unpublish @autonomath/sdk@0.2.0` (rare,
  registry-side).
- After 72 h: `npm deprecate @autonomath/sdk@0.2.0 "<reason>"` and ship
  `0.2.1`. Unpublish is no longer permitted.

## Security notes

- Never paste the npm token into docs, chat, or commit messages.
- Rotate the token via https://www.npmjs.com/settings/<USER>/tokens after
  each launch milestone.
- The `bugs.email` field in `package.json` is `info@bookyou.net` — that
  is the public contact and is intentional.
