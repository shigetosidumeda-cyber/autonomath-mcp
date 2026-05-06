# Static fallback playbook (Cloudflare Pages)

Goal: if Fly.io (nrt) goes hard-down, visitors see landing + legal + `/status` instead of a generic 503. API calls still fail — that is expected.

## Normal state

- DNS `jpcite.com` A/AAAA → Fly Anycast (TTL = 300).
- Cloudflare Pages project `jpintel-mcp-fallback` is kept warm by `.github/workflows/pages-preview.yml` on every push to `main` / `release/*`.

## Fly outage (activate fallback)

1. Confirm outage: `flyctl status -a autonomath-api` and `flyctl logs -a autonomath-api` — not a local DNS issue.
2. Flip apex A record to Pages:
   - Cloudflare dashboard → `jpcite.com` → **DNS → Records**.
   - Edit `@` → change to CNAME `jpintel-mcp-fallback.pages.dev` (proxied, TTL 300).
   - Save. Propagation < 5 min for fresh resolvers.
3. Edit `site/status.html`: move `active` class from `.state.ok` to `.state.down`, update the `Last updated` line, commit + push. Pages redeploys in <30s.
4. Post status on X / HN thread pointing at `jpcite.com/status`.

## Recovery

1. `flyctl status` shows machine `started` + health check `passing`.
2. Revert DNS record to Fly A/AAAA (or toggle proxy back).
3. Move `active` class in `status.html` back to `.state.ok`, update timestamp, push.

## Key paths

- Cloudflare dashboard → Account → **Workers & Pages → jpintel-mcp-fallback → Deployments**.
- Fly dashboard → https://fly.io/apps/autonomath-api/monitoring
