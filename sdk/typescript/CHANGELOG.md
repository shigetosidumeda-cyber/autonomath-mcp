# Changelog

All notable changes to `@autonomath/sdk` (TypeScript) are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-04-26

### Fixed

- `meta()` now hits `GET /v1/meta` directly (was `/meta`, which 308-redirects
  to `/v1/meta` — wasting a round-trip and breaking strict HTTP clients that
  refuse to follow cross-prefix redirects).
- `package.json` `description` corrected from `11,547 programs` to the
  dedup'd S/A/B/C count `10,972 programs` (verified via
  `SELECT tier, COUNT(*) FROM programs WHERE excluded=0 GROUP BY tier`:
  S=116 + A=1,366 + B=3,321 + C=6,169 = 10,972).
- `mcp.ts` header comment updated from `55-tool surface` to `67-tool surface`
  to match `server.json` (`tool_count: 67` = 39 core + 28 autonomath).
- `searchPrograms()` JSDoc updated from `11,547-row` to `10,972-row`
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
