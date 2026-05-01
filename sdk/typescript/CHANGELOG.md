# Changelog

All notable changes to `@autonomath/sdk` (TypeScript) are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-04-26

### Fixed

- `meta()` now hits `GET /v1/meta` directly (was `/meta`, which 308-redirects
  to `/v1/meta` — wasting a round-trip and breaking strict HTTP clients that
  refuse to follow cross-prefix redirects).
- `package.json` `description` corrected to the current searchable S/A/B/C
  count: `11,684 programs` (full table `14,472`, with tier X quarantine excluded
  from search by default).
- `mcp.ts` header comment updated to the 93 default-on MCP tool surface.
- `searchPrograms()` JSDoc updated to the 11,684-row searchable catalog
  (S/A/B/C only, tier X quarantine excluded).
- Bumped `SDK_VERSION` constant to match package version.

## [0.3.1] - 2026-04-26

### Fixed

- `searchLoans()` now hits `GET /v1/loan-programs/search` (was `/v1/loans/search`,
  which 404s in production).
- `getLoan(id)` now hits `GET /v1/loan-programs/{id}` (was `/v1/loans/{id}`).
  The id parameter accepts `string | number` since the server route uses an
  integer path param.
- `searchEnforcement()` now hits `GET /v1/enforcement-cases/search` (was
  `/v1/enforcement/search`).
- `getEnforcement(caseId)` now hits `GET /v1/enforcement-cases/{case_id}` (was
  `/v1/enforcement/{id}`).
- `getLawArticle(lawNameOrCanonicalId, articleNumber)` now hits
  `GET /v1/am/law_article?law_name_or_canonical_id=...&article_number=...`
  (was `/v1/laws/{id}/articles/{art}`, which never existed server-side).
  The first parameter is now named `lawNameOrCanonicalId` and accepts either a
  unified law id (`LAW-jp-shotokuzeiho`) or a canonical law name (`所得税法`).
- Bumped `SDK_VERSION` constant to match package version.

## [0.2.0] - 2026-04-25

Initial public release.
