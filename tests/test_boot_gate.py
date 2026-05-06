"""§S2 production secret boot-gate tests.

Verifies `_assert_production_secrets()` in `api/main.py`:

  * dev / test envs are exempt (no-op)
  * prod env hard-fails on dev-salt / placeholder API_KEY_SALT
  * prod env hard-fails when API_KEY_SALT is < 32 chars
  * prod env hard-fails on missing audit-seal secret
  * prod env hard-fails on missing Cloudflare Turnstile secret when APPI is enabled
  * prod env hard-fails on missing Stripe webhook secret
  * prod env hard-fails on missing or test-mode Stripe secret key
  * prod env passes when every secret is set to a unique 32+ char value
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from importlib import reload
from typing import Any

import pytest

import jpintel_mcp.api.main as main_module
import jpintel_mcp.config as config_module

# A 64-char base64 — comfortably above the 32-char floor.
GOOD_SALT = "k" * 48
GOOD_AUDIT_KEY = "a" * 64
GOOD_TURNSTILE_SECRET = "1x0000000000000000000000000000000AA"
_ENV_KEYS = (
    "JPINTEL_ENV",
    "API_KEY_SALT",
    "AUTONOMATH_API_HASH_PEPPER",
    "INTEGRATION_TOKEN_SECRET",
    "AUDIT_SEAL_SECRET",
    "JPINTEL_AUDIT_SEAL_KEYS",
    "AUTONOMATH_APPI_ENABLED",
    "CLOUDFLARE_TURNSTILE_SECRET",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_SECRET_KEY",
)


def test_main_allows_artifact_backend_to_ship_as_separate_packet() -> None:
    code = textwrap.dedent(
        """
        import builtins

        original_import = builtins.__import__

        def import_without_artifact_packet(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "jpintel_mcp.api.artifacts":
                raise ModuleNotFoundError(
                    "No module named 'jpintel_mcp.api.artifacts'",
                    name="jpintel_mcp.api.artifacts",
                )
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = import_without_artifact_packet

        import jpintel_mcp.api.main as main

        assert main.artifacts_router is None
        app = main.create_app()
        paths = {route.path for route in app.routes}
        assert "/v1/artifacts/compatibility_table" not in paths
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(autouse=True)
def _restore_settings_after_boot_gate() -> None:
    """Keep config reload tests from leaking a new settings singleton.

    Billing and device-flow modules import `settings` directly. Reloading
    `jpintel_mcp.config` during these tests creates a new singleton, so later
    tests that patch `jpintel_mcp.config.settings` would otherwise miss the
    already-imported billing/device modules.
    """
    original_env = {key: os.environ.get(key) for key in _ENV_KEYS}
    yield
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    reload(config_module)
    main_module.settings = config_module.settings
    for module_name, module in tuple(sys.modules.items()):
        if module_name.startswith("jpintel_mcp.") and hasattr(module, "settings"):
            module.settings = config_module.settings


def _reset_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Force settings to re-read env vars by setting + reloading config."""
    # Clear potentially conflicting in-process env first.
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Reload config so Pydantic re-binds env values.
    reload(config_module)
    # Re-bind the symbol on main_module too (it imported `settings` directly).
    monkeypatch.setattr(main_module, "settings", config_module.settings)


# --------------------------------------------------------------------------- #
# Dev / test exemption
# --------------------------------------------------------------------------- #


def test_dev_env_is_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """JPINTEL_ENV unset / dev / test → boot gate is a no-op."""
    _reset_settings(monkeypatch, JPINTEL_ENV="dev", API_KEY_SALT="dev-salt")
    # MUST NOT raise.
    main_module._assert_production_secrets()


def test_test_env_is_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_settings(monkeypatch, JPINTEL_ENV="test", API_KEY_SALT="test-salt")
    main_module._assert_production_secrets()


# --------------------------------------------------------------------------- #
# Prod gate fails closed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_salt", ["dev-salt", "change-this-salt-in-prod", "test-salt", ""])
def test_prod_fails_on_forbidden_salt(monkeypatch: pytest.MonkeyPatch, bad_salt: str) -> None:
    _reset_settings(monkeypatch, JPINTEL_ENV="prod", API_KEY_SALT=bad_salt)
    with pytest.raises(SystemExit, match=r"\[BOOT FAIL\] API_KEY_SALT"):
        main_module._assert_production_secrets()


def test_prod_fails_on_short_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a non-placeholder salt < 32 chars must trip the gate."""
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT="short-salt-123",  # 14 chars
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"≥32 chars"):
        main_module._assert_production_secrets()


def test_prod_fails_on_missing_audit_seal(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET="dev-audit-seal-salt",
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"AUDIT_SEAL"):
        main_module._assert_production_secrets()


def test_prod_audit_seal_keys_overrides_audit_seal_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JPINTEL_AUDIT_SEAL_KEYS present → AUDIT_SEAL_SECRET placeholder OK."""
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET="dev-audit-seal-salt",
        JPINTEL_AUDIT_SEAL_KEYS=GOOD_AUDIT_KEY,
        CLOUDFLARE_TURNSTILE_SECRET=GOOD_TURNSTILE_SECRET,
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    main_module._assert_production_secrets()


@pytest.mark.parametrize(
    "bad_audit_keys",
    [
        "short",
        "dev-audit-seal-salt",
        f"{GOOD_AUDIT_KEY},dev-audit-seal-salt",
        "",
    ],
)
def test_prod_fails_on_invalid_audit_seal_rotation_keys(
    monkeypatch: pytest.MonkeyPatch, bad_audit_keys: str
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET="dev-audit-seal-salt",
        JPINTEL_AUDIT_SEAL_KEYS=bad_audit_keys,
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"AUDIT_SEAL"):
        main_module._assert_production_secrets()


def test_prod_fails_on_empty_audit_seal_rotation_keys_even_with_legacy_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        JPINTEL_AUDIT_SEAL_KEYS="",
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"JPINTEL_AUDIT_SEAL_KEYS"):
        main_module._assert_production_secrets()


def test_prod_fails_on_missing_turnstile_secret_when_appi_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"CLOUDFLARE_TURNSTILE_SECRET"):
        main_module._assert_production_secrets()


def test_prod_allows_missing_turnstile_secret_when_appi_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        AUTONOMATH_APPI_ENABLED="0",
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    main_module._assert_production_secrets()


def test_prod_fails_on_missing_stripe_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        CLOUDFLARE_TURNSTILE_SECRET=GOOD_TURNSTILE_SECRET,
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    with pytest.raises(SystemExit, match=r"STRIPE_WEBHOOK_SECRET"):
        main_module._assert_production_secrets()


def test_prod_fails_on_missing_stripe_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        CLOUDFLARE_TURNSTILE_SECRET=GOOD_TURNSTILE_SECRET,
        STRIPE_WEBHOOK_SECRET="whsec_live",
    )
    with pytest.raises(SystemExit, match=r"STRIPE_SECRET_KEY"):
        main_module._assert_production_secrets()


def test_prod_fails_on_test_mode_stripe_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        CLOUDFLARE_TURNSTILE_SECRET=GOOD_TURNSTILE_SECRET,
        STRIPE_WEBHOOK_SECRET="whsec_live",
        STRIPE_SECRET_KEY="sk_test_xxx",
    )
    with pytest.raises(SystemExit, match=r"live-mode Stripe key"):
        main_module._assert_production_secrets()


# --------------------------------------------------------------------------- #
# Prod gate passes when fully configured
# --------------------------------------------------------------------------- #


def test_prod_passes_when_all_secrets_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="prod",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        CLOUDFLARE_TURNSTILE_SECRET=GOOD_TURNSTILE_SECRET,
        STRIPE_WEBHOOK_SECRET="whsec_live_xxx",
        STRIPE_SECRET_KEY="sk_live_xxx",
    )
    # MUST NOT raise.
    main_module._assert_production_secrets()


def test_production_alias_for_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`production` is accepted as an alias for `prod`."""
    _reset_settings(monkeypatch, JPINTEL_ENV="production", API_KEY_SALT="dev-salt")
    with pytest.raises(SystemExit, match=r"API_KEY_SALT"):
        main_module._assert_production_secrets()


async def test_production_alias_triggers_lifespan_pepper_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_settings(
        monkeypatch,
        JPINTEL_ENV="production",
        API_KEY_SALT=GOOD_SALT,
        AUDIT_SEAL_SECRET=GOOD_AUDIT_KEY,
        AUTONOMATH_APPI_ENABLED="0",
        STRIPE_WEBHOOK_SECRET="whsec_live_xxx",
        STRIPE_SECRET_KEY="sk_live_xxx",
        AUTONOMATH_API_HASH_PEPPER="dev-pepper-change-me",
    )
    monkeypatch.setattr(main_module, "_init_sentry", lambda: None)
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    with pytest.raises(SystemExit):
        async with main_module._lifespan(main_module.create_app()):
            pass


async def test_lifespan_calls_production_secret_gate_before_init_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fail_boot_gate() -> None:
        calls.append("production_secret_gate")
        raise SystemExit("[BOOT FAIL] test gate")

    def unexpected_init_db() -> None:
        calls.append("init_db")

    monkeypatch.setattr(main_module, "_init_sentry", lambda: calls.append("sentry"))
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda *args, **kwargs: calls.append("logging"),
    )
    monkeypatch.setattr(main_module, "_assert_production_secrets", fail_boot_gate)
    monkeypatch.setattr(main_module, "init_db", unexpected_init_db)

    with pytest.raises(SystemExit, match=r"\[BOOT FAIL\] test gate"):
        async with main_module._lifespan(main_module.create_app()):
            pass

    assert calls == ["sentry", "logging", "production_secret_gate"]


# --------------------------------------------------------------------------- #
# Module-level constant
# --------------------------------------------------------------------------- #


def test_forbidden_salts_set_complete() -> None:
    forbidden: Any = main_module._FORBIDDEN_SALTS
    assert "dev-salt" in forbidden
    assert "change-this-salt-in-prod" in forbidden
    assert "test-salt" in forbidden
    assert "" in forbidden
