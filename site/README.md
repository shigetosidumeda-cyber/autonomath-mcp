# Site Directory

`site/` is the deployed public web surface for jpcite.

Some files are hand-authored public pages and some are deployment artifacts
produced from the documentation, API description, or data publishing process.
When changing this directory, keep public copy edits small and review the
rendered result before publishing.

Public entry points include:

- `index.html`
- `pricing.html`
- `trial.html`
- `integrations/`
- `qa/`
- `.well-known/`
- `assets/`
- `docs/`
- `openapi*.json`
- `sitemap-*.xml`

Large data, API, sitemap, and documentation artifacts may be refreshed by the
release process. Prefer changing the public source content where available, then
review the deployed artifact for user-facing accuracy.
