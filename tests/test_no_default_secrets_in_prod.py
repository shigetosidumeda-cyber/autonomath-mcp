"""CI gate — forbidden secret values must not ship in production env files.

Pairs with the §S2 boot-gate (`api/main.py::_assert_production_secrets`).
The boot gate catches misconfigured runtime values; this test catches the
upstream cause: a tracked `.env.production` / `.env.prod` / production fly
secret manifest carrying the placeholder salt, audit-seal dev secret, or any
other forbidden value.

What it scans
-------------

For every file under the repo whose name matches one of the production-env
patterns below, fail the test if any line containing one of the forbidden
salts is non-comment.

  * `.env.production`, `.env.prod`, `.env.production.local`
  * `production.env`, `prod.env`
  * `fly.production.toml`, `fly.prod.toml`

`.env.example` and `.env.staging` are EXEMPT — those files are reference docs
and intentionally hold placeholder values. The pre-commit hook adds this
test to the staged-commit gate via `.pre-commit-config.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jpintel_mcp.api.main import _FORBIDDEN_SALTS

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files inspected. Patterns are exact basenames, not globs — `.env.example`
# (which intentionally holds the placeholder) is NOT in this list.
_PROD_ENV_FILENAMES: frozenset[str] = frozenset(
    {
        ".env.production",
        ".env.production.local",
        ".env.prod",
        "production.env",
        "prod.env",
        "fly.production.toml",
        "fly.prod.toml",
    }
)

# Additional forbidden values beyond _FORBIDDEN_SALTS. The §S2 boot gate
# also rejects these audit-seal / Stripe placeholder values.
_OTHER_FORBIDDEN: frozenset[str] = frozenset(
    {
        "dev-audit-seal-salt",
        "sk_test_xxx",
        "sk_live_xxx",
        "whsec_xxx",
    }
)


def _scan_for_forbidden(path: Path) -> list[str]:
    """Return [(line_number, line)] hits for forbidden values in path."""
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[str] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for needle in (
            *(s for s in _FORBIDDEN_SALTS if s),
            *_OTHER_FORBIDDEN,
        ):
            if needle in line:
                hits.append(f"{path}:{lineno}: {line.rstrip()}")
                break
    return hits


def test_no_default_secrets_in_production_env_files() -> None:
    """Production env files must not carry any forbidden placeholder."""
    offenders: list[str] = []
    for filename in _PROD_ENV_FILENAMES:
        for path in REPO_ROOT.rglob(filename):
            # Skip `.venv/` and `node_modules/`.
            if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
                continue
            offenders.extend(_scan_for_forbidden(path))

    if offenders:
        msg = (
            "Forbidden secret placeholder found in production env file. "
            "Production env files must NOT carry dev/test salts. "
            "Forbidden values: "
            f"{sorted(s for s in _FORBIDDEN_SALTS if s) + sorted(_OTHER_FORBIDDEN)}.\n"
            + "\n".join(offenders)
        )
        pytest.fail(msg)


def test_forbidden_salts_constant_is_complete() -> None:
    """`_FORBIDDEN_SALTS` must include the historical placeholders."""
    expected = {"dev-salt", "change-this-salt-in-prod", "test-salt", ""}
    assert expected.issubset(
        _FORBIDDEN_SALTS
    ), f"_FORBIDDEN_SALTS must cover at least {expected}; got {_FORBIDDEN_SALTS}"


def test_env_example_is_intentionally_excluded() -> None:
    """`.env.example` may carry placeholders — it is a reference doc."""
    example = REPO_ROOT / ".env.example"
    if example.is_file():
        # Sanity: the example still carries the documented placeholder so
        # downstream operators see exactly what to replace.
        text = example.read_text(encoding="utf-8", errors="replace")
        assert "API_KEY_SALT" in text
