"""me/ subpackage for dashboard auth + widgets.

The legacy `api/me.py` module (1461 lines, dashboard endpoints + session
cookie + billing portal + key rotation + CSRF) cannot live next to a
`me/` package — Python's import resolution prefers the package and
silently shadows the .py module. Rather than rename / mv the legacy
file (destruction-free organization rule), we side-load it via
importlib and copy every public symbol into the package namespace so
`jpintel_mcp.api.me.<sym>` keeps resolving for: the FastAPI app
(`api/main.py` includes `me.router`), the conftest autouse fixture
(reads `me._get_email_client`, `me._reset_session_rate_limit_state`,
`me._reset_billing_portal_rate_limit_state`), and any downstream
caller that bound to the module path.

New magic-link auth code lives in `login_request.py` + `login_verify.py`
inside this package and is exported alongside the legacy surface.
"""
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017


from __future__ import annotations

import importlib.util as _ilu
from pathlib import Path as _Path

# Side-load the legacy module from its physical path so its symbols
# survive the package shadowing. The file lives one directory up at
# api/me.py — we resolve relative to this __init__.py.
_legacy_path = _Path(__file__).resolve().parent.parent / "me.py"
_spec = _ilu.spec_from_file_location("jpintel_mcp.api._me_legacy", _legacy_path)
if _spec is None or _spec.loader is None:  # pragma: no cover — would mean me.py disappeared
    raise ImportError(f"Failed to spec-load legacy api/me.py from {_legacy_path}")
_legacy = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)

# Re-export every non-dunder symbol from the legacy module into this
# package namespace. This preserves `me.router`, `me._get_email_client`,
# `me._reset_session_rate_limit_state`, `me._reset_billing_portal_rate_limit_state`,
# `me.SESSION_COOKIE_NAME`, etc.
for _name in dir(_legacy):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_legacy, _name)
del _name, _legacy, _spec, _ilu, _Path, _legacy_path
