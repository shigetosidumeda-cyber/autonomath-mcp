---
title: Cloudflare Redirect Rules Setup
updated: 2026-05-07
operator_only: true
category: brand
---

# Cloudflare Redirect Rules Setup

Canonical public host is `https://jpcite.com`. The `www.jpcite.com` host and
legacy `zeimu-kaikei.ai` hosts must return HTTP 301 before Cloudflare Pages
serves duplicate HTML.

Source of truth: `cloudflare-rules.yaml` → `redirect_rules`.

## Required API Token

Cloudflare dashboard → Profile → API Tokens で Custom Token を発行。

Required permission:

- **Dynamic URL Redirects:Write** for the target zones

Zones:

- `jpcite.com`
- `zeimu-kaikei.ai`

## Secrets

`~/.jpcite_secrets.env` に以下を置く。値はログに出力しない。

```bash
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ZONE_ID_JPCITE_COM="..."
export CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI="..."
```

`CF_API_TOKEN` / `CF_ZONE_ID` も jpcite.com zone の fallback 名として利用可。

## Apply

```bash
bash scripts/ops/cloudflare_redirect.sh --dry-run
bash scripts/ops/cloudflare_redirect.sh
```

The script uses the Rulesets API phase `http_request_dynamic_redirect`. It
updates only rules whose `ref` matches `cloudflare-rules.yaml` and preserves
unmanaged rules in the same phase.

## Expected Rules

- `www.jpcite.com/*` → `https://jpcite.com/$path` (`301`, query preserved)
- `zeimu-kaikei.ai/*` → `https://jpcite.com/$path` (`301`, query preserved)
- `www.zeimu-kaikei.ai/*` → `https://jpcite.com/$path` (`301`, query preserved)

## Verify

```bash
curl -I https://www.jpcite.com/
# Expected: HTTP/2 301
#           location: https://jpcite.com/

curl -I "https://www.jpcite.com/pricing?utm_source=test"
# Expected: location: https://jpcite.com/pricing?utm_source=test

curl -I https://zeimu-kaikei.ai/test
# Expected: HTTP/2 301
#           location: https://jpcite.com/test

curl -I https://www.zeimu-kaikei.ai/foo/bar
# Expected: HTTP/2 301
#           location: https://jpcite.com/foo/bar
```

`HTTP/2 301` + apex `location` + path/query preservation を確認できれば完了。

## Rollback

Cloudflare dashboard → target zone → Rules → Redirect Rules で対象 rule を
Disable または Delete。反映は通常 30 秒以内。

## Notes

- Do not implement host redirects in `site/_redirects`; Cloudflare Pages
  `_redirects` sources are path-only and cannot match `www.jpcite.com`.
- Single Redirects require the source hostname to be proxied by Cloudflare.
