<!--
Thanks for the PR. AutonoMath is solo-operated, so a clean, single-purpose
PR is much easier to review than a sprawling one. Please fill in the
sections below.
-->

## Summary

<!-- 1-3 bullets on the "why" of this change. -->

## Changes

<!-- Bulleted "what" — files / modules touched. Group by area (api/, mcp/, ingest/, db/, docs/, etc.). -->

## Type of change

<!-- Check all that apply. -->

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (API / schema / CLI)
- [ ] Data correction (programs / laws / cases / enforcement / etc.)
- [ ] Documentation only
- [ ] Refactor / internal cleanup
- [ ] Tests only
- [ ] CI / tooling

## Checklist

- [ ] Tests added or updated (`.venv/bin/pytest tests/ -v`)
- [ ] `ruff check src/ tests/ scripts/` passes locally
- [ ] `ruff format --check` passes locally
- [ ] `mypy src/` passes (best-effort — call out new errors below)
- [ ] OpenAPI schema regenerated if `/v1/*` routes changed (`scripts/export_openapi.py`)
- [ ] `CHANGELOG.md` updated under `[Unreleased]` if user-facing
- [ ] Docs (`README.md`, `docs/`, docstrings) updated where relevant
- [ ] No new aggregator URLs (noukaweb / hojyokin-portal / etc.) introduced into `source_url` data
- [ ] No tier-based pricing UI / "Pro plan" / seat counters re-introduced
- [ ] Pre-commit hooks pass without `--no-verify`

## Breaking changes / migration notes

<!-- Leave "None." if N/A. If breaking, include before/after request shape and a one-paragraph migration note. -->

None.

## Related issues

<!-- Closes #123, Refs #456 -->

## Screenshots / curl output (optional)

<!-- For UI / API response changes. -->
