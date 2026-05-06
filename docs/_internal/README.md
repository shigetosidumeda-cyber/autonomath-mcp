# Internal Documentation Boundary

`docs/_internal/` is operator-only material. It can contain release notes,
security runbooks, deployment details, legal review notes, research rollups,
dirty-tree inventories, and strategy drafts.

## Rules

- Do not publish this directory to customer docs or static site output.
- Do not quote files from this directory in public copy without a separate
  review pass.
- Treat secret inventories, deployment runbooks, legal notes, WAF/deploy
  gates, incident response, and dirty-tree reports as non-public.
- Promote only distilled, non-sensitive conclusions into `docs/`,
  `docs/integrations/`, `site/`, or `README.md`.
- Keep raw loop output out of this directory unless it is compact, reviewed,
  and useful as a durable operator report.

## Current SOT Entrypoints

For 2026-05-06 work, start from these reviewed pointer files before reading
older internal notes:

- `CURRENT_SOT_2026-05-06.md` — current operator/agent source-of-truth layer
- `REPO_HYGIENE_TRIAGE_2026-05-06.md` — dirty-tree ownership and safe cleanup rules
- `PRODUCTION_DEPLOY_PACKET_2026-05-06.md` — current deploy gate and NO-GO blockers
- `generated_artifacts_map_2026-05-06.md` — generated/release-sensitive artifact map
- `info_collection_cli_latest_implementation_handoff_2026-05-06.md` — latest CLI-to-implementation handoff

Treat `INDEX.md`, `_INDEX.md`, and older dated indexes as historical unless a
current SOT entrypoint explicitly points back to them.

## Publicization Candidates

Some files here may become public after redaction and verification:

- productized artifact catalogs
- company public baseline positioning
- source foundation summaries
- conservative benchmark methodology
- API contracts that match implemented behavior

When promoting any internal file, keep the original internal record and create a
new public document with claims, dates, and caveats reviewed separately.
