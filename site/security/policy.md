# Security Policy

jpcite is operated by **Bookyou株式会社** (info@bookyou.net). We take security reports seriously and prefer to be told than to find out from the news.

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

This safe-harbour statement applies to jpcite itself: the API at `api.jpcite.com`, the static site at `jpcite.com`, and the official MCP server package on PyPI. It does not extend to third-party services we depend on; please report those directly to the vendor. We are happy to coordinate when an issue spans both sides.

## No bug bounty

jpcite does **not** run a paid bug bounty program. We are happy to credit researchers in release notes and on this page (with consent) but cannot offer monetary rewards.

If you would prefer not to be credited, say so in your report — the default is no credit unless you ask for it.

## Scope

**In scope**

- The hosted REST API at `https://api.jpcite.com`
- The static site at `https://jpcite.com`
- The official jpcite MCP Python package on PyPI (and its MCP server entry point)
- The data ingestion pipeline where it affects public API output
- Infrastructure we operate directly for the hosted API and static site

**Out of scope**

- Vulnerabilities in third-party services we consume (report to the vendor)
- Issues in upstream Japanese government primary-source sites (METI, MAFF, JFC, prefectures)
- Denial-of-service requiring unrealistic traffic volumes
- Missing security headers on static marketing pages absent a demonstrated exploit
- Self-XSS without a clear privilege-escalation path
- Social engineering
- Physical attacks

## Past incidents

We publish redacted writeups of confirmed incidents at <https://jpcite.com/security/incidents/>. The list is currently empty.

## Contact

Bookyou株式会社 — info@bookyou.net

For non-security questions, the same address works; please prefix the subject line with `[security]` if your report is security-relevant so it gets routed correctly.
