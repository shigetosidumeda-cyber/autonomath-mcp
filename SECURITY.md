# Security Policy

AutonoMath publishes a machine-readable disclosure record per
[RFC 9116](https://www.rfc-editor.org/rfc/rfc9116) at
<https://zeimu-kaikei.ai/.well-known/security.txt>. The contact channel
below is the canonical route for vulnerability reports.

## Supported versions

AutonoMath ships a single supported release line. Only the latest minor
release on PyPI (`autonomath-mcp`) receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.3.x   | Supported |
| 0.2.x   | Best effort (1 minor cycle) |
| < 0.2   | Not supported |

Once 1.0 ships, security backports will be limited to the latest two
minor lines. The policy will be updated here at that time.

## Reporting a vulnerability

Email **info@bookyou.net** with:

- A description of the issue.
- A proof-of-concept or reproduction steps.
- The version or commit you observed it on.
- Your preferred name or handle for public attribution (optional).

Please do **not** open a public GitHub issue for security-sensitive
reports.

We aim to acknowledge reports within **72 hours** (JST business days)
on a best-effort basis (solo operator) and to issue a fix within
**14 days** for server-side vulnerabilities or in the next PyPI release
for client-side issues.

If the report qualifies as material and you would like public credit,
we will list you in the release notes and in this file (unless you ask
us not to).

## Scope

**In scope**

- `autonomath-mcp` Python package (the PyPI distribution).
- The MCP server (`autonomath-mcp` console script, stdio transport).
- The hosted REST API at `https://api.zeimu-kaikei.ai`.
- The static site at `https://zeimu-kaikei.ai`.
- The data ingestion pipeline (`src/jpintel_mcp/ingest/**`).
- Infrastructure that we operate directly (Fly.io app config,
  Cloudflare Pages build config, GitHub Actions workflows).

**Out of scope**

- Vulnerabilities in third-party services we consume (Stripe, Postmark,
  Sentry, Cloudflare, Fly.io) — please report those directly to the
  vendor. We are happy to coordinate if the issue touches our
  integration surface.
- Vulnerabilities in Japanese government primary-source sites (METI,
  MAFF, JFC, prefectures, e-Gov, NTA). These are upstream and public;
  we cannot patch them.
- Denial-of-service reports that require unrealistic traffic volumes.
- Missing security headers on static marketing pages where exploitation
  is not demonstrated.
- Self-XSS without a clear privilege-escalation path.
- Reports based purely on automated scanner output without a working
  PoC.

## Safe harbour / responsible disclosure

We will not pursue legal action against researchers who:

- Act in good faith to identify and report issues.
- Do not access, modify, or delete data beyond what is strictly
  necessary to demonstrate the issue.
- Give us a reasonable window (at least 14 days from our acknowledgement)
  to fix the issue before public disclosure.
- Do not degrade the service for other users during testing.

If you are unsure whether an action is in scope, email us **before**
you do it. We would much rather coordinate than have to clean up.

## Acknowledgements

Security researchers who have reported issues to us will be listed
here (by name or handle, with consent) once we have begun triaging
reports. This list is currently empty.

---

Maintainer: **Bookyou株式会社** (T8010001213708) — info@bookyou.net
RFC 9116 record: <https://zeimu-kaikei.ai/.well-known/security.txt>
