# Security Policy

AutonoMath is operated by **Bookyou株式会社** (Corporate Number T8010001213708, info@bookyou.net) as a solo, zero-touch operation. We take security reports seriously and prefer to be told than to find out from the news.

## Reporting a vulnerability

Email **info@bookyou.net** with:

- A short description of the issue
- Reproduction steps or proof of concept
- The version, commit, or URL where you observed it
- Your preferred name or handle for attribution (optional)

PGP is **optional**. If you would like to encrypt your report, ask in your first email and we will send a current key. Reports sent in cleartext are accepted and acknowledged the same way.

Please do **not** open a public GitHub issue, tweet, or post the issue elsewhere before we have had a chance to respond.

## Acknowledgement and disclosure window

- We acknowledge reports within **72 hours** (JST business days).
- We aim to issue a fix within **14 days** for server-side issues, or in the next PyPI release for client-side issues.
- We ask researchers to give us **90 days** from acknowledgement before public disclosure. If we have not fixed the issue in 90 days and have not asked for an extension, you are free to disclose.
- If exploitation is observed in the wild, we may disclose proactively before the 90-day window closes; we will coordinate with you on attribution.

## Safe harbour

We will not pursue legal action, file a complaint, or otherwise interfere with researchers who:

- Act in good faith to identify and report security issues
- Avoid privacy violations, data destruction, and service disruption
- Access only the minimum data necessary to demonstrate the issue
- Do **not** retain, use, or disclose data accessed during testing
- Give us a reasonable window (at least 14 days from acknowledgement) to remediate before any public discussion

This safe-harbour statement applies to AutonoMath itself (the API at `api.autonomath.ai`, the static site at `autonomath.ai`, the MCP server distributed as `autonomath-mcp` on PyPI). It does not extend to third-party services we depend on (Stripe, Postmark, Cloudflare, Fly.io) — please report those directly to the vendor. We are happy to coordinate when an issue spans both sides.

## No bug bounty

AutonoMath does **not** run a paid bug bounty program. The product is operated 100% organically with no advertising or paid acquisition spend, and we extend that posture to security as well. We are happy to credit researchers in release notes and on this page (with consent) but cannot offer monetary rewards.

If you would prefer not to be credited, say so in your report — the default is no credit unless you ask for it.

## Scope

**In scope**

- The hosted REST API at `https://api.autonomath.ai`
- The static site at `https://autonomath.ai`
- The `autonomath-mcp` Python package on PyPI (and its MCP server entry point)
- Our data ingestion pipeline (`src/jpintel_mcp/ingest/**` in the public repo)
- Infrastructure we operate directly (Fly.io app, Cloudflare Pages build, GitHub Actions workflows)

**Out of scope**

- Vulnerabilities in third-party services we consume (report to the vendor)
- Issues in upstream Japanese government primary-source sites (METI, MAFF, JFC, prefectures)
- Denial-of-service requiring unrealistic traffic volumes
- Missing security headers on static marketing pages absent a demonstrated exploit
- Self-XSS without a clear privilege-escalation path
- Social engineering of the operator
- Physical attacks against operator infrastructure

## Past incidents

We publish redacted writeups of confirmed incidents at <https://autonomath.ai/security/incidents/>. The list is currently empty.

## Contact

Bookyou株式会社 (T8010001213708) — info@bookyou.net

For non-security questions, the same address works; please prefix the subject line with `[security]` if your report is security-relevant so it gets routed correctly.
