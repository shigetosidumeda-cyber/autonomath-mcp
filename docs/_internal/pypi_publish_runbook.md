# PyPI Publish Runbook (autonomath-mcp 0.2.0)

**Status**: PENDING manual upload — `PYPI_TOKEN` env var absent and `~/.pypirc`
not configured at agent run time (2026-04-25). Artifacts ready, twine check
PASSED. Operator must execute the upload manually.

---

## 1. Pre-flight (already done by A9)

- `pyproject.toml` version = `0.2.0`
- `server.json` version = `0.2.0`
- Artifacts built into `dist/`:
  - `autonomath_mcp-0.2.0-py3-none-any.whl` — 611,922 bytes
  - `autonomath_mcp-0.2.0.tar.gz` — 554,323 bytes
- `twine check` PASSED on both files (verified by F4 agent 2026-04-25)

### sha256 (record before upload)

```
9881b179a2358a07a81bc5f4e1552d82dd820149855a2bfd5d2c8bafd999661d  autonomath_mcp-0.2.0-py3-none-any.whl
716f36355ef90ef1387af5785723d93950371f39e1b220b0857e9b8d481adf96  autonomath_mcp-0.2.0.tar.gz
```

---

## 2. Token setup (operator, one-time)

PyPI dropped username/password auth — use API token only.

1. Sign in https://pypi.org/manage/account/ as the project owner
2. Create token scoped to project `autonomath-mcp` (after first upload) or to
   "Entire account" for the very first publish
3. Token format: `pypi-AgEI...` (starts with `pypi-`)

### Option A — env var (preferred, no file leftover)

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD='pypi-AgEI...'
```

### Option B — `~/.pypirc`

```ini
[pypi]
  username = __token__
  password = pypi-AgEI...
```

`chmod 600 ~/.pypirc` after writing. Do NOT commit this file.

---

## 3. Optional — TestPyPI dry run

Requires a separate TestPyPI account + token (https://test.pypi.org/).

```bash
cd /Users/shigetoumeda/jpintel-mcp
.venv/bin/twine upload \
  --repository testpypi \
  dist/autonomath_mcp-0.2.0*
```

Verify:
```bash
python3 -m venv /tmp/venv-test
/tmp/venv-test/bin/pip install --no-deps \
  --index-url https://test.pypi.org/simple/ \
  autonomath-mcp==0.2.0
```

---

## 4. Production PyPI upload

```bash
cd /Users/shigetoumeda/jpintel-mcp
.venv/bin/twine upload dist/autonomath_mcp-0.2.0*
```

Expected output ends with:
```
View at:
https://pypi.org/project/autonomath-mcp/0.2.0/
```

If a name conflict shows up (e.g. `autonomath-mcp` already taken by a
squatter), follow PyPI's "Project name conflicts" form — do NOT rename
locally first.

---

## 5. Install verify (clean venv)

```bash
python3 -m venv /tmp/venv-pypi-verify
/tmp/venv-pypi-verify/bin/pip install --no-deps autonomath-mcp==0.2.0
/tmp/venv-pypi-verify/bin/python -c "from jpintel_mcp.mcp.server import mcp; print('OK')"
```

Should print `OK`. Any ImportError → yank 0.2.0 with `twine` /
pypi.org UI and re-build as 0.2.1.

---

## 6. Post-upload tasks (operator)

1. Append to `docs/_internal/pypi_publish_log.md` (template below):
   - timestamp (UTC + JST)
   - version
   - file sizes
   - sha256
   - uploader (operator handle)
   - install verify result
2. Tag git: `git tag v0.2.0 && git push origin v0.2.0`
3. Update README install snippet if it referenced a pre-release
4. Consider creating a project-scoped token now that `autonomath-mcp` exists,
   and revoke the broader account-scoped token

---

## 7. Yank procedure (if regressions)

```bash
# UI: https://pypi.org/manage/project/autonomath-mcp/release/0.2.0/
# Click "Options" → "Yank"
```

Yank does NOT delete; it hides from default `pip install` resolution.
Bump to 0.2.1 and re-publish — never re-upload the same version (PyPI
forbids it).

---

## Append-only log template

```
## 2026-04-25T??:??Z (JST 2026-04-25 ??:??)
- version: 0.2.0
- whl: autonomath_mcp-0.2.0-py3-none-any.whl (611,922 B, sha256 9881b179...)
- sdist: autonomath_mcp-0.2.0.tar.gz (554,323 B, sha256 716f3635...)
- uploader: <operator handle>
- url: https://pypi.org/project/autonomath-mcp/0.2.0/
- install verify: OK / FAIL (paste output)
- notes: -
```
