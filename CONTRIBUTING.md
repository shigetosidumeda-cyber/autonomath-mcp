# Contributing to AutonoMath

AutonoMath is solo-operated by **Bookyou株式会社** (T8010001213708).
Product direction (pricing, packaging, brand, UI) is out of scope for
external contributors. **Bug reports, data corrections (dead URL, wrong
amount, missing program), SDK improvements, doc fixes, and test
additions are welcome.**

> **税理士法 §52 disclaimer.** Contributions must not add tax, legal,
> or 行政書士 advice content — only data, code, and documentation.
> AutonoMath indexes primary-source records; it does not interpret them
> for individual taxpayers.

## Local development

The package source lives at `src/jpintel_mcp/` (legacy import path —
the PyPI distribution is named `autonomath-mcp`, but renaming the
import would break every consumer; do **not** rename).

```bash
# Editable install with dev + site extras (uv or pip)
pip install -e ".[dev,site]"
playwright install chromium       # only if touching tests/e2e/

# Run the REST API locally (port 8080, --reload)
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080

# Run the MCP stdio server
.venv/bin/autonomath-mcp

# Run the full test suite
.venv/bin/pytest                  # unit + integration
.venv/bin/pytest tests/e2e/       # Playwright (needs [e2e] extra)

# Lint / format / type-check
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
mypy src/

# Regenerate OpenAPI spec after API route changes
.venv/bin/python scripts/export_openapi.py > docs/openapi/v1.json

# Regenerate per-program SEO pages
.venv/bin/python scripts/generate_program_pages.py
```

The pre-commit hooks in `.pre-commit-config.yaml` run ruff + yamllint +
gitleaks + bandit. **Do not bypass with `--no-verify`** — fix the
underlying failure.

## Code style

- **Python**: ruff + ruff format (config in `pyproject.toml`). Line
  length 100. No `from x import *`. Type hints required on public
  functions.
- **YAML**: yamllint (config in `.yamllint.yaml`).
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`,
  `ci:`, `data:`. Subject ≤72 chars; details in the body.
- **Branches**: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`,
  `data/<slug>`. Branch from `main`.

## Pull requests

- **One purpose per PR.** Splitting unrelated changes makes review
  tractable for a solo maintainer.
- **Tests required for `src/` changes.** Unit tests at minimum; add
  integration tests where behaviour crosses a module boundary.
- **Update `CHANGELOG.md`** under `[Unreleased]` for user-visible
  changes.
- **Re-run** `ruff`, `mypy`, and `pytest` locally before pushing.
- **Pre-commit hooks must pass** — do not bypass with `--no-verify`.
- **No mocked DB in integration tests.** Mocked tests previously hid a
  production migration failure; integration paths must hit a real
  SQLite file.

## Adding new programs / laws / cases (data work)

1. Identify the **primary source** — government ministry, prefecture,
   日本政策金融公庫, or equivalent. Aggregators (noukaweb, hojyokin-portal,
   biz.stayway, nikkei.com, wikipedia, prtimes) are **banned** from
   `source_url` — past incidents created consumer-protection (詐欺) risk.
2. Add ingestion code under `src/jpintel_mcp/ingest/` — one file per
   source type. Follow the existing canonical-tier scoring rules.
3. Run the ingest with `--dry-run` first; commit the output JSON snapshot
   under `data/staging/` for review.
4. Confirm tier assignment via:
   ```bash
   sqlite3 data/jpintel.db "SELECT tier, COUNT(*) FROM programs WHERE excluded=0 GROUP BY tier;"
   ```
5. Open a PR labelled `data:` with the source URL, ingest run command,
   and a row-count delta in the description.

## Reporting data errors (without a code change)

Use the **Data quality report** issue template. Include:

1. The record ID (`unified_id`, `canonical_id`, `law_id`, `case_id`).
2. The dataset and field that's wrong.
3. A **primary-source URL** with the correct value. Aggregators are
   rejected.

## Security

See [`SECURITY.md`](SECURITY.md). Responsible disclosure to
<info@bookyou.net>. **Do not** open public issues for security
problems.

## Code of Conduct

By participating you agree to abide by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1).

## License

Code is MIT-licensed (see [`LICENSE`](LICENSE)). Data licensing and
attribution for the `programs` catalog is described in the README —
contributions to the catalog are governed by the same terms (e-Gov
CC-BY for laws, PDL v1.0 for the invoice registrant delta, primary
source attribution for everything else).
