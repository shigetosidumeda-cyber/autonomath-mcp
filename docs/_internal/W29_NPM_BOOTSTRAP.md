# W29 npm Publish Bootstrap — `@jpcite/agents`

Operator-only one-shot to break the chicken-and-egg between npm OIDC trusted
publishing and the package not existing yet. ~5 min wall-clock.

Internal-only — do not link from the public site.

## Why this exists

The CI workflow `.github/workflows/sdk-publish-agents.yml` tried to publish
`@jpcite/agents@0.1.1` and failed with:

```
npm error code ENEEDAUTH
npm error need auth This command requires you to be logged in to https://registry.npmjs.org/
```

Two unrelated facts collide:

1. The repo has no `NPM_TOKEN` secret, so the CLI cannot use classic token auth.
2. npm OIDC "trusted publishing" requires a `Trusted Publisher` row to be
   configured at `https://www.npmjs.com/package/@jpcite/agents/access` —
   but that page does not exist until at least one version of the package
   has been published. Hence the chicken-and-egg.

The CI workflow's preflight step (added W29) detects this state and fails
fast with a pointer back here instead of running the full build pipeline.

## Pick ONE path — A is preferred (no long-lived secrets)

### Path A — Local seed publish, then OIDC for all future tags (recommended)

```bash
# 1. Log in to npm with publish rights for the @jpcite scope
cd /Users/shigetoumeda/jpcite/sdk/agents
npm login --scope=@jpcite --registry=https://registry.npmjs.org/
# Browser opens for OAuth + 2FA. Verify:
npm whoami

# 2. Build + dry-run pack to confirm tarball matches what CI would emit
rm -rf dist node_modules
npm ci
npm run build
npm pack --dry-run 2>&1 | tail -10
# Expected: name @jpcite/agents, version 0.1.1, ~36 files, ~31 kB

# 3. Live publish (one-shot — agents-v0.1.1 tag is already pushed,
#    so CI will not re-publish this version; Path A only seeds it once)
npm publish --provenance --access public
# 2FA OTP prompt if your account is in auth-and-writes mode.

# 4. Verify within ~30 s
curl -sS https://registry.npmjs.org/@jpcite/agents | python3 -m json.tool | head -20
open https://www.npmjs.com/package/@jpcite/agents

# 5. Configure Trusted Publisher on the npm package page
#    https://www.npmjs.com/package/@jpcite/agents/access
#    -> "Trusted Publishers" -> "Add trusted publisher" -> GitHub Actions
#    Repository owner: <github-org-or-user that owns this repo>
#    Repository name:  <repo-name>
#    Workflow filename: sdk-publish-agents.yml
#    Environment name:  npm   (matches `environment: npm` in the workflow)
#    Save.

# 6. Bump version and tag the next release; CI will publish via OIDC, no token.
#    cd sdk/agents && npm version patch   # 0.1.1 -> 0.1.2
#    git add package.json package-lock.json && git commit -m "chore(sdk/agents): v0.1.2"
#    git tag agents-v0.1.2 && git push --tags
```

After step 5 the workflow is fully self-serve forever. No npm token is ever
stored in GitHub secrets.

### Path B — Add `NPM_TOKEN` secret (no Trusted Publisher dance)

Use this only if you would rather not leave the browser to configure trust.
The trade-off: a long-lived secret in the repo that needs rotation.

```bash
# 1. Create a granular access token
#    https://www.npmjs.com/settings/<USER>/tokens/granular-access-tokens/new
#    Permissions:  Packages and scopes -> Read and write -> @jpcite (scope)
#    Expiration:   recommended <= 365 days
#    Copy the token (shown once).

# 2. Add as repo secret
gh secret set NPM_TOKEN --repo <OWNER>/<REPO>
# Paste the token at the prompt.

# 3. Re-run the failed workflow on the existing tag
gh workflow run sdk-publish-agents.yml --ref agents-v0.1.1
# Or push a new tag — both go through the token path now.
```

If you later want to switch to Path A, delete the secret after configuring
Trusted Publisher; the workflow's preflight prefers `NPM_TOKEN` when present,
so removing it transparently flips to OIDC.

## Verification (both paths)

```bash
# Registry has the version
curl -sS https://registry.npmjs.org/@jpcite/agents/0.1.1 | python3 -m json.tool | head -20

# Install smoke test
cd /tmp && rm -rf jpcite-agents-verify && mkdir jpcite-agents-verify && cd jpcite-agents-verify
npm init -y > /dev/null
npm install @jpcite/agents@0.1.1
node -e "import('@jpcite/agents').then(m => console.log(Object.keys(m)))"
```

## Rollback

- Within 72 h of publish: `npm unpublish @jpcite/agents@0.1.1` (registry-side).
- After 72 h: `npm deprecate @jpcite/agents@0.1.1 "<reason>"` and ship 0.1.2.

## Logging

Append to `docs/_internal/npm_publish_log.md` after the publish completes:
timestamp, version, sha-256, publisher, path used (A or B).
