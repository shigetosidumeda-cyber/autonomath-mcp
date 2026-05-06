---
title: Publish @jpcite/sdk to npm
updated: 2026-05-04
operator_only: true
category: deploy
---

# Runbook: Publish `@jpcite/sdk` to npm

> Operator-only manual procedure. The CI cannot perform this because npm 2FA
> requires a hardware OTP and Bookyou株式会社's npm org owner credentials are
> not — and must not be — committed.

## Pre-conditions

1. npm account `bookyou` (or designated owner) is a member of the `@jpcite`
   npm organization with `Owner` role.
2. The `@jpcite` org exists. If not, create it: <https://www.npmjs.com/org/create>
   (`organization name = jpcite`, `billing = pro`, sign 2 USD/seat invoice).
3. `~/.npmrc` carries an automation token with `publish` scope, OR you are
   logged in interactively (`npm login`) and 2FA OTP is reachable.
4. Working directory is `sdk/typescript/` and `git status` is clean on `main`.
5. Local node version matches `engines.node = ">=20"`.

## Steps

```bash
cd /Users/shigetoumeda/jpcite/sdk/typescript

# 1. Confirm package metadata is correct
node -e 'console.log(JSON.stringify({n:require("./package.json").name, v:require("./package.json").version},null,2))'
# expected: {"n":"@jpcite/sdk","v":"0.3.2"}

# 2. Bump version if shipping a new release (skip if 0.3.2 not yet on npm)
npm version patch --no-git-tag-version  # or minor / major

# 3. Clean install + build + typecheck
npm ci
npm run build
npm run typecheck

# 4. Pack a dry-run tarball, inspect the contents
npm pack --dry-run | tee /tmp/jpcite-sdk-pack.txt
# verify: dist/, README.md, LICENSE present; no .ts source, no node_modules

# 5. Optional smoke test from the tarball
npm pack
mkdir -p /tmp/jpcite-sdk-smoke && cd /tmp/jpcite-sdk-smoke
npm init -y >/dev/null
npm install /Users/shigetoumeda/jpcite/sdk/typescript/jpcite-sdk-*.tgz
node -e 'const { Jpcite } = require("@jpcite/sdk"); console.log(typeof Jpcite)'  # → "function"
cd /Users/shigetoumeda/jpcite/sdk/typescript

# 6. Publish — first publish of new scope must include --access=public
npm publish --access=public
# Enter 2FA OTP from authenticator app when prompted.
```

## Post-publish verification

```bash
npm view @jpcite/sdk version          # matches the version you just shipped
npm view @jpcite/sdk repository.url   # https://github.com/<org>/jpcite-mcp (post-rename target — see docs/runbook/github_rename.md)
npm view @jpcite/sdk homepage         # https://jpcite.com

# End-to-end install in a scratch dir
cd /tmp && rm -rf jpcite-sdk-postcheck && mkdir jpcite-sdk-postcheck && cd jpcite-sdk-postcheck
npm init -y >/dev/null
npm install @jpcite/sdk
node -e 'console.log(Object.keys(require("@jpcite/sdk")))'
```

## Rollback

`npm unpublish @jpcite/sdk@<version>` is allowed only within 72 hours of
publish per npm policy. After 72 h, ship a `0.x.y+1` patch with the fix
instead of unpublishing. Never deprecate the entire `@jpcite/sdk` name —
deprecate only individual versions:

```bash
npm deprecate @jpcite/sdk@<version> "use 0.x.y+1 — fixes issue #NNN"
```

## Legacy `@autonomath/sdk` compat plan

For one quarter (T+90d), publish `@autonomath/sdk` patch releases that
re-export everything from `@jpcite/sdk`:

```json
{
  "name": "@autonomath/sdk",
  "main": "./dist/index.js",
  "dependencies": { "@jpcite/sdk": "^0.3.0" },
  "scripts": { "build": "echo 'export * from \"@jpcite/sdk\"; export * as mcp from \"@jpcite/sdk/mcp\";' > dist/index.js" }
}
```

After T+90d freeze the legacy alias and `npm deprecate @autonomath/sdk@*`
with a pointer to `@jpcite/sdk`.

## Failure modes

- **`E403 Forbidden`** — the npm org `@jpcite` does not exist or your token
  lacks publish scope. Re-run `npm login`, regenerate token at
  <https://www.npmjs.com/settings/_/tokens> with `Automation` type.
- **`EOTP`** — 2FA missing. Use `--otp=<6-digit-code>`.
- **`EPUBLISHCONFLICT`** — version already published. Bump and retry.
- **postpack fails** — `tsc` errored. Run `npm run typecheck` first to surface
  the diagnostic.
