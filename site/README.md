# Site Directory Contract

`site/` is the Cloudflare Pages public surface. It intentionally contains both
hand-authored public files and generated output. Do not assume every file here
has the same source of truth.

## Hand-Authored Or Curated

These may be edited directly when the change is public copy or static surface
work.

- `site/index.html`
- `site/pricing.html`
- `site/trial.html`
- `site/integrations/*.html`
- `site/qa/**/*.html`
- `site/llms.txt`
- `site/llms.en.txt`
- `site/en/llms.txt`
- `site/.well-known/*.json`
- `site/_templates/`
- `site/assets/`

## Generated Or Mirrored

Do not hand-edit these unless you are deliberately repairing a generated
artifact and will follow up by fixing the generator.

- `site/docs/`
- `site/docs/openapi/*.json`
- `site/openapi.agent.json`
- `site/programs/*`
- `site/prefectures/`
- `site/structured/`
- `site/llms-full.txt`
- `site/llms-full.en.txt`
- `site/sitemap-*.xml`
- `site/_data/public_counts.json`

## Main Generators

- OpenAPI full: `uv run python scripts/export_openapi.py`
- OpenAPI agent: `uv run python scripts/export_agent_openapi.py`
- Public counts: `uv run python scripts/generate_public_counts.py`
- Full LLM dump: `uv run python scripts/regen_llms_full.py`
- Full English LLM dump: `uv run python scripts/regen_llms_full_en.py`
- MkDocs output: `mkdocs build` writes to `site/docs/`

## Review Rule

Separate hand-authored site copy from generated output when possible. If they
must land together, state the generator command and why the public artifact
changed.
