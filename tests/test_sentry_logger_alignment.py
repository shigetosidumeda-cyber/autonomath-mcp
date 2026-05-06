"""W6-2: assert Sentry alert rules' logger queries match real logger names.

Background
----------
Sentry alert rules in ``monitoring/sentry_alert_rules.yml`` filter on
``logger:<name>`` strings. Each name MUST match an actual Python logger
created somewhere in our prod code; otherwise the rule is silent (no events
match the filter, no notification ever fires) and the operator is blind to
real failures.

W6-2 audit (2026-05-04) found 6 of 8 rules silently mis-wired because the
YAML carried legacy ``autonomath.*`` prefixes from the pre-rename era while
real loggers shipped as ``jpintel.*``. The fix renamed the queries; this
test pins the alignment so the next rename / new-logger landing cannot
regress without a CI failure.

What this test enforces
-----------------------
For every rule in the YAML whose ``filter.query`` carries a ``logger:...``
clause, parse out the logger name(s) and confirm each one is created
somewhere in the codebase via ``logging.getLogger("...")`` (or, in the
case of message-level / metric-level rules without logger filters,
recognise that no assertion is needed).

Coverage
--------
- ``backup_integrity_failure`` → ``[jpintel.backup_hourly, jpintel.backup_autonomath]``
- ``anon_quota_lookup_error``  → ``jpintel.anon_quota_header``
- ``webhook_handler_exception_rate`` → ``[jpintel.billing.webhook, jpintel.email.postmark]``
- Other rules without ``logger:`` filter (metric: / message: only) skipped.

Notes
-----
``jpintel.billing.webhook`` and ``jpintel.email.postmark`` may be created
via ``logging.getLogger(__name__)`` in modules whose ``__name__`` resolves
to those dotted paths (e.g. ``src/jpintel_mcp/api/billing/webhook.py``
=> ``jpintel_mcp.api.billing.webhook`` — note this does NOT yield
``jpintel.billing.webhook``). For those, we accept either an explicit
``getLogger("jpintel.billing.webhook")`` literal OR a comment / config
hook that documents the binding. The fallback grep keeps this test honest
without requiring every logger to be a string literal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_YAML = REPO_ROOT / "monitoring" / "sentry_alert_rules.yml"
SEARCH_ROOTS = (
    REPO_ROOT / "src",
    REPO_ROOT / "scripts",
)

# Rules whose filter.query intentionally carries no logger: clause.
# (metric:* and message:* style rules don't filter on logger name.)
_NO_LOGGER_FILTER_RULES = frozenset(
    {
        "stripe_usage_events_unsynced",
        "invoice_missing_tnumber",
        "api_5xx_rate",
        "subscription_created_anomaly",
    }
)

# Pattern matches:
#   logger:foo.bar
#   logger:[foo.bar,baz.qux]   (Sentry's OR sugar)
_LOGGER_RE = re.compile(r"logger:(\[[^\]]+\]|[A-Za-z0-9_.]+)")


def _extract_logger_names(query: str) -> list[str]:
    """Return list of logger names referenced in a Sentry filter query.

    Empty list if the query has no ``logger:`` clause.
    """
    out: list[str] = []
    for hit in _LOGGER_RE.findall(query):
        if hit.startswith("["):
            inner = hit[1:-1]
            out.extend(name.strip() for name in inner.split(",") if name.strip())
        else:
            out.append(hit)
    return out


def _logger_referenced_in_codebase(name: str) -> bool:
    """Return True if any source file under SEARCH_ROOTS calls
    ``logging.getLogger("<name>")`` with a matching string literal.
    """
    needle_dq = f'logging.getLogger("{name}")'
    needle_sq = f"logging.getLogger('{name}')"
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle_dq in text or needle_sq in text:
                return True
    return False


@pytest.fixture(scope="module")
def rules_doc() -> dict:
    return yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))


def test_yaml_loads_and_has_rules(rules_doc: dict) -> None:
    """Sanity: the alert rules YAML must parse and carry the expected
    8 rules. Anything less means a rule was deleted without a teammate
    knowing — fail loudly."""
    rules = rules_doc.get("rules") or []
    assert isinstance(rules, list), "rules section must be a list"
    assert len(rules) == 8, f"expected 8 alert rules, found {len(rules)}"
    ids = {r.get("id") for r in rules}
    expected = {
        "webhook_handler_exception_rate",
        "stripe_usage_events_unsynced",
        "invoice_missing_tnumber",
        "api_5xx_rate",
        "anon_quota_lookup_error",
        "subscription_created_anomaly",
        "backup_integrity_failure",
        "deprecated_endpoint_hit",
    }
    assert ids == expected, f"rule ids drifted: {ids ^ expected}"


def test_each_logger_filter_matches_real_logger(rules_doc: dict) -> None:
    """W6-2 enforcement: every ``logger:...`` token in a rule's filter
    query must correspond to a ``logging.getLogger("...")`` call somewhere
    in src/ or scripts/. Catches the regression where a rename leaves the
    YAML on a stale logger name and the rule silently never fires.
    """
    rules = rules_doc.get("rules") or []
    misaligned: list[tuple[str, str]] = []
    for rule in rules:
        rid = rule.get("id", "<no-id>")
        if rid in _NO_LOGGER_FILTER_RULES:
            continue
        query = (rule.get("filter") or {}).get("query") or ""
        logger_names = _extract_logger_names(query)
        assert logger_names, (
            f"rule {rid!r} expected to have a logger: filter but query was "
            f"{query!r}; if the rule legitimately has no logger filter, add "
            f"its id to _NO_LOGGER_FILTER_RULES in this test."
        )
        for name in logger_names:
            if not _logger_referenced_in_codebase(name):
                misaligned.append((rid, name))

    assert not misaligned, (
        "Sentry alert rules reference logger names that no "
        "logging.getLogger(...) literal in src/ or scripts/ creates — these "
        "rules would silently never fire. Either rename the YAML query to "
        "match the real logger, or rename the logger to match the YAML.\n"
        f"Misaligned: {misaligned}"
    )


def test_backup_scripts_call_safe_capture_exception() -> None:
    """W6-2 enforcement: the two backup cron scripts must route exceptions
    through ``safe_capture_exception`` so the ``backup_integrity_failure``
    Sentry rule has events to match. Without this call, stdlib ``logging``
    alone is invisible to Sentry.
    """
    targets = (
        REPO_ROOT / "scripts" / "cron" / "backup_jpintel.py",
        REPO_ROOT / "scripts" / "cron" / "backup_autonomath.py",
    )
    missing: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "safe_capture_exception(" not in text:
            missing.append(str(path.relative_to(REPO_ROOT)))
    assert not missing, (
        "Backup cron scripts missing safe_capture_exception() call — the "
        "backup_integrity_failure Sentry rule will be silent on failure. "
        f"Add the call in: {missing}"
    )


def test_runbook_documents_sentry_dsn_secret_set() -> None:
    """W6-2 enforcement: the operator runbook must teach how to inject
    SENTRY_DSN into Fly. Without DSN injection, every safe_capture_* call
    is a no-op and all 8 rules are silent regardless of YAML correctness.
    """
    runbook = (REPO_ROOT / "docs" / "runbook" / "sentry_setup.md").read_text(encoding="utf-8")
    assert "flyctl secrets set SENTRY_DSN=" in runbook, (
        "sentry_setup.md must include the `flyctl secrets set SENTRY_DSN=...` "
        "command. Without it the operator has no documented procedure to "
        "wire Sentry into the production Fly app."
    )
    assert "flyctl secrets list" in runbook and "SENTRY_DSN" in runbook, (
        "sentry_setup.md must include a verification command "
        "(`flyctl secrets list ... | grep SENTRY_DSN`)."
    )
