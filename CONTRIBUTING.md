# Contributing to AutonoMath

AutonoMath is solo-operated by **Bookyou株式会社** (T8010001213708).
Product direction (pricing, features, UI) is out of scope for external
contributors. **Bug reports, data corrections (dead URL, wrong amount,
missing program), SDK improvements, doc fixes, and test additions are
welcome.**

## Local development

```bash
# Editable install with dev extras (uses uv or pip)
pip install -e ".[dev,site]"
playwright install chromium       # only if touching tests/e2e/

# Run the REST API
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080

# Run the MCP stdio server
.venv/bin/autonomath-mcp

# Run tests
.venv/bin/pytest                  # unit + integration
.venv/bin/pytest tests/e2e/       # Playwright (needs [e2e] extra)

# Lint / type-check
ruff check src/ tests/ scripts/
mypy src/
```

## Branches & commits

- Branch from `main`: `feat/<short-slug>`, `fix/<short-slug>`,
  `docs/<short-slug>`, `data/<short-slug>`.
- Use [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`,
  `ci:`, `data:`. Example: `fix(api): respect tier priority in FTS
  rank path`.
- Keep the subject line ≤72 chars; details go in the body.

## Pull requests

- **One purpose per PR.** Splitting unrelated changes makes review
  tractable for a solo maintainer.
- **Tests required for `src/` changes.** Unit tests at minimum; add
  integration tests where behaviour crosses module boundaries.
- Update `CHANGELOG.md` (`[Unreleased]` section) with user-visible
  changes.
- Pre-commit hooks must pass — do not bypass with `--no-verify`.
- Re-run `ruff`, `mypy`, and `pytest` locally before pushing.

## Reporting data errors

File an issue with:

1. The `unified_id` (e.g. `agri-maff-keiei-anteika-201`).
2. The field you believe is wrong (e.g. `amount_max`, `source_url`,
   `target_types`).
3. A **primary-source URL** — government ministry, prefecture, 公庫,
   or equivalent. Aggregators (noukaweb, hojyokin-portal,
   biz.stayway, etc.) will be rejected; past incidents created
   consumer-protection (詐欺) risk.

## Security

See [`SECURITY.md`](SECURITY.md). Responsible disclosure to
<info@bookyou.net>. Do not open public issues for security problems.

## License

Code is MIT-licensed (see [`LICENSE`](LICENSE)). Data licensing and
attribution for the `programs` catalog is described in the README —
contributions to the catalog are governed by the same terms.
