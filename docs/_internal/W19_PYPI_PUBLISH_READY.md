# W19 PyPI Publish Ready

Build state confirmed 2026-05-05. Both sdist + wheel built from `pyproject.toml` version `0.3.3`, twine metadata check passed.

## Artifacts

- `dist/autonomath_mcp-0.3.3-py3-none-any.whl`
- `dist/autonomath_mcp-0.3.3.tar.gz`

Backup of prior dist contents (v0.2.0 - v0.3.2 wheels/tarballs/.mcpb + side dirs):

- `dist.bak/` (pre-existing)
- `dist.bak2/` (snapshot of v0.3.3 dist before clean rebuild)

## Build commands used

```bash
.venv/bin/python -m build         # sdist + wheel
.venv/bin/twine check dist/*      # both PASSED
```

## PyPI publish (run when PYPI_TOKEN arrives)

One-liner, glob covers exactly the 0.3.3 sdist + wheel since `dist/` was rebuilt clean:

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=$PYPI_TOKEN .venv/bin/twine upload dist/*
```

## Notes

- Distribution name on PyPI: `autonomath-mcp` (legacy, retained per CLAUDE.md "do not rename" rule). Source dir is `src/jpintel_mcp/`.
- `pyproject.toml` version (0.3.3) must match `server.json` and any future tag — verify before tagging.
- After PyPI publish, follow the §"Release checklist" in `CLAUDE.md` (MCP registry publish via `mcp publish server.json`, Cloudflare Pages auto-deploys, Fly.io `fly deploy`).
