---
search:
  exclude: true
---

# jpcite Sub-processor Disclosure

**Operator:** Bookyou株式会社 (T8010001213708)
**Contact:** info@bookyou.net
**Last review:** 2026-05-11

This page lists every third-party sub-processor that may handle
Personal Data (as defined in APPI Article 2 and GDPR Article 4) on
behalf of jpcite customers. Additions are announced via
`https://jpcite.com/audit-log.rss` with a **30-day objection window**
before the new sub-processor is activated. Customers who object can
terminate per ToS Section 8 or DPA Section 2 without penalty.

| Entity | Legal Name | Country | Function | Certifications | Personal Data scope |
|---|---|---|---|---|---|
| **Stripe Japan K.K.** | Stripe Japan K.K. | Japan (HQ: USA) | Payments, invoicing, tax receipt issuance | PCI DSS Level 1, SOC 1/2 Type II, ISO 27001, GDPR DPA, APPI | Cardholder data is tokenised at source; jpcite stores only `stripe_customer_id` + last4 digits via `usage_events`. |
| **Fly.io, Inc.** | Fly.io, Inc. | USA (compute region: Tokyo `nrt`) | Application hosting, edge proxy, secrets storage | SOC 2 Type II, ISO 27001 (in progress), GDPR DPA, HIPAA BAA (not used) | API request bodies pass through Fly machines in Tokyo only; no persistence beyond the request lifecycle. Volumes hosting the primary corpus database files (operator-internal, not customer-shipped) are encrypted-at-rest. |
| **Cloudflare, Inc.** | Cloudflare, Inc. | USA (edge: Tokyo `NRT`, Osaka `KIX`) | CDN, WAF, DNS, R2 object storage (backup), Pages hosting | SOC 2 Type II, ISO 27001, ISO 27018, PCI DSS, GDPR DPA, APPI sub-processor registration | TLS termination at edge; request metadata (IP, UA, country) logged for 24 h by default. R2 buckets hold daily backups in Tokyo metro (`apac`). |
| **Postmark / ActiveCampaign LLC** | ActiveCampaign, LLC (Postmark brand) | USA | Transactional email (magic-link login, billing receipts, audit-log digests, security advisories) | SOC 2 Type II, ISO 27001, GDPR DPA, Privacy Shield successor (DPF) | Email address + display name + message body of the transactional template. Bounce and complaint metadata retained 30 days. |
| **Sentry / Functional Software, Inc.** | Functional Software, Inc. (Sentry brand) | USA (EU region available, currently USA) | Error tracking, performance monitoring | SOC 2 Type II, ISO 27001, GDPR DPA, HIPAA BAA (not used) | Stack traces, request URL path, request_id, user_id (account_id, not email). PII scrubber active: `email`, `authorization`, `cookie`, `set-cookie` fields stripped before transmission. |

## Roles and responsibilities

In the language of GDPR Art. 28 and APPI Art. 21:

- **Controller**: the jpcite customer (the entity that submits a query
  via the API or accepts the DPA at `/dpa/issue`).
- **Processor**: Bookyou株式会社 (operator of jpcite).
- **Sub-processor**: the 5 entities listed above.

Each sub-processor is engaged under a written DPA that binds the
sub-processor to materially equivalent obligations as the jpcite DPA
(`site/legal/dpa_template.pdf`), including:

- TLS in transit + AES-256 at rest
- Breach notification within 72 h
- Sub-processor obligations cascading
- Right of audit on reasonable notice
- Return / deletion on termination

## Geographic location of data

| Region | Storage | Compute |
|---|---|---|
| Japan (Tokyo) | Fly volumes, Cloudflare R2 `apac` | Fly machines `nrt` |
| USA | Stripe, Postmark, Sentry (control plane only) | Stripe, Postmark, Sentry (event ingest) |

Per DPA Section 9, no Personal Data is intentionally transferred
outside Japan for normal operation of the jpcite API. Operational
metadata (e.g., Stripe billing webhooks, Sentry error events) may
traverse US-hosted control planes; these flows are limited to the
fields enumerated in the "Personal Data scope" column above and are
covered by the relevant sub-processor's GDPR DPA / APPI compliance
attestation.

## Objection procedure

To object to a sub-processor addition or to request an alternative,
email `info@bookyou.net` within 30 days of the audit-log.rss
announcement, citing:

- Your account_id (`jc_...` API key prefix is sufficient)
- The sub-processor entry you object to
- Whether you wish to terminate or request a substitute

We will respond within 14 calendar days. Substitution is offered on a
best-effort basis; if a substitute is not feasible, termination per
DPA Section 2 is honoured without penalty.

## Change log

| Date | Change | By |
|---|---|---|
| 2026-05-11 | Initial publication | Bookyou株式会社 |
