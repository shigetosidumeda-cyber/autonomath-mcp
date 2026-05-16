"""Guard against the Stripe ToS-consent live-mode 500 pitfall.

CLAUDE.md (§Common gotchas) records:

    Stripe checkout pitfall. Do NOT pass
    ``consent_collection={"terms_of_service": "required"}`` — this
    causes a 500 in live mode. Use ``custom_text.submit.message`` for
    the ToS link instead.

The runtime regression for this gotcha already exists in
``tests/test_billing_tax.py::test_checkout_preserves_subscription_mode_and_tos_consent``
(asserts the live ``stripe.checkout.Session.create`` kwargs never contain
``consent_collection``). This file adds a complementary **source-level**
guard so the forbidden literal cannot reappear anywhere in
``src/jpintel_mcp/api/billing*.py`` (or anywhere in the repo's
``src/jpintel_mcp/`` / ``scripts/`` trees) before runtime, and so any
*future* Stripe checkout creation helper that does build a
``consent_collection={...}`` dict literal is forced to either:

  * use ``"terms_of_service": "auto"`` (Stripe's safe value, which does
    not require a Dashboard ToS URL and therefore does not 500), OR
  * pair the dict with ``custom_text.submit.message`` containing a ToS
    link in the **same** ``stripe.checkout.Session.create`` call.

The test scope is intentionally narrow per the task spec:

  * **Source-grep scope** (Test 1 / 2): ``src/jpintel_mcp/`` and
    ``scripts/`` — matches the CLAUDE.md verify-grep command verbatim.
  * **AST scope** (Test 3): ``src/jpintel_mcp/api/billing*.py`` — the
    billing layer is the only place that constructs Stripe checkout
    sessions on the request path; ``scripts/`` only forwards webhook
    payloads, never builds checkout kwargs.

NO LLM imports (CLAUDE.md §What NOT to do). Pure stdlib only.
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Source-grep scope: matches CLAUDE.md's documented verify command
# ``rg -n --pcre2 "consent_collection.*terms_of_service" src/jpintel_mcp/ scripts/``
SOURCE_GREP_DIRS = ("src/jpintel_mcp", "scripts")

# AST scope: any helper that creates a Stripe checkout session lives in
# the request-path billing layer. E6 owns webhook reception side; we
# only audit checkout-creation kwargs here, never modify them.
BILLING_GLOB = "src/jpintel_mcp/api/billing*.py"

# The forbidden literal pattern from CLAUDE.md.
# Match cases:
#   consent_collection={"terms_of_service": "required"}
#   consent_collection = {'terms_of_service': 'required'}
#   consent_collection=dict(terms_of_service="required")
# Use a permissive pcre2/re pattern equivalent to the documented grep.
FORBIDDEN_PATTERN_RE = re.compile(
    r"consent_collection.{0,200}terms_of_service.{0,80}required",
    re.DOTALL,
)

# Files that document the pattern as the content of the rule they
# enforce (this file, plus any meta-docs that quote CLAUDE.md). They
# may legitimately contain the forbidden literal as a string for the
# purposes of asserting against it.
META_FILES = {
    "tests/test_stripe_tos_pitfall_guard.py",
}


def _billing_files() -> list[pathlib.Path]:
    """Return every ``src/jpintel_mcp/api/billing*.py`` file."""
    api_dir = REPO_ROOT / "src" / "jpintel_mcp" / "api"
    files = sorted(api_dir.glob("billing*.py"))
    # Sanity: we expect 4 modules per the 2026-05-13 repo state
    # (billing.py / billing_v2.py / billing_breakdown.py /
    # billing_webhook_idempotency.py). Don't hard-pin the count — new
    # billing*.py files should be auto-covered by this glob.
    assert files, f"expected at least one billing*.py under {api_dir}"
    return files


# ---------------------------------------------------------------------------
# Test 1: ripgrep-based source scan (matches CLAUDE.md verify command)
# ---------------------------------------------------------------------------


def test_no_forbidden_terms_of_service_required_in_source_via_rg() -> None:
    """Source-grep ``src/jpintel_mcp/`` + ``scripts/`` returns 0 matches.

    This replicates the CLAUDE.md documented verify command:

        rg -n --pcre2 "consent_collection.*terms_of_service" \
            src/jpintel_mcp/ scripts/

    Any match outside this test file itself is a regression of the
    live-mode 500 pitfall.
    """
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("ripgrep (rg) not available on PATH; covered by pure-Python fallback")

    cmd = [
        rg,
        "-n",
        "--pcre2",
        "consent_collection.*terms_of_service",
        *(str(REPO_ROOT / d) for d in SOURCE_GREP_DIRS),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # rg exit codes: 0 = matches found, 1 = no matches, 2 = error.
    assert proc.returncode in (0, 1), f"rg failed with rc={proc.returncode}: stderr={proc.stderr!r}"

    matches = [line for line in proc.stdout.splitlines() if line.strip()]

    # Filter out this test file itself if its directory ever gets
    # included in the grep scope (today it isn't — `tests/` is outside
    # SOURCE_GREP_DIRS — but be defensive).
    matches = [m for m in matches if "test_stripe_tos_pitfall_guard.py" not in m]

    assert matches == [], (
        "Forbidden Stripe ToS pattern resurfaced — this caused live-mode 500 "
        "(CLAUDE.md §Common gotchas). Use custom_text.submit.message instead.\n"
        + "\n".join(matches)
    )


# ---------------------------------------------------------------------------
# Test 2: pure-Python text scan (CI fallback when rg is missing)
# ---------------------------------------------------------------------------


def test_no_forbidden_terms_of_service_required_pure_python_fallback() -> None:
    """Pure-Python regex scan equivalent to the ripgrep guard above.

    Some CI shards may not have ``rg`` available. This fallback walks
    every ``*.py`` file under ``src/jpintel_mcp/`` and ``scripts/`` and
    asserts the forbidden pattern is absent, excluding this meta-test
    file itself.
    """
    offenders: list[str] = []
    for d in SOURCE_GREP_DIRS:
        base = REPO_ROOT / d
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel in META_FILES:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in FORBIDDEN_PATTERN_RE.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{rel}:{line_no}: {m.group(0)[:120]!r}")

    assert offenders == [], (
        "Forbidden Stripe ToS pattern detected — caused live-mode 500 "
        "(CLAUDE.md §Common gotchas). Replace with custom_text.submit.message "
        "or terms_of_service='auto'.\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Test 3: AST guard for any future consent_collection={...} helper
# ---------------------------------------------------------------------------


def _is_str_literal(node: ast.AST, value: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _dict_has_key_value(d: ast.Dict, key: str, value: str) -> bool:
    """Return True iff ``d`` contains ``{<key>: <value>}`` as string literals."""
    for k_node, v_node in zip(d.keys, d.values, strict=False):
        if k_node is None:  # ``**kwargs`` unpack — skip
            continue
        if _is_str_literal(k_node, key) and _is_str_literal(v_node, value):
            return True
    return False


def _dict_get_str(d: ast.Dict, key: str) -> str | None:
    """If ``d`` has ``{key: <str literal>}``, return that string; else None."""
    for k_node, v_node in zip(d.keys, d.values, strict=False):
        if k_node is None:
            continue
        if (
            _is_str_literal(k_node, key)
            and isinstance(v_node, ast.Constant)
            and isinstance(v_node.value, str)
        ):
            return v_node.value
    return None


def _custom_text_mentions_tos(custom_text_value: ast.AST) -> bool:
    """Return True iff ``custom_text={"submit": {"message": "...tos..."}}``.

    We accept any case-insensitive substring "tos" or "terms" or "利用規約"
    inside the submit.message string literal — that covers the canonical
    pattern used in ``billing.py`` (which surfaces a
    ``https://jpcite.com/tos.html`` URL inside a Japanese sentence
    containing "利用規約").
    """
    if not isinstance(custom_text_value, ast.Dict):
        return False
    submit = None
    for k, v in zip(custom_text_value.keys, custom_text_value.values, strict=False):
        if _is_str_literal(k, "submit"):
            submit = v
            break
    if not isinstance(submit, ast.Dict):
        return False
    message = _dict_get_str(submit, "message")
    if message is None:
        return False
    lower = message.lower()
    return any(tok in lower for tok in ("tos", "terms", "利用規約"))


def _check_call(node: ast.Call, rel: str) -> list[str]:
    """For a single ``ast.Call``, return a list of violation strings."""
    violations: list[str] = []

    consent_kw: ast.keyword | None = None
    custom_text_kw: ast.keyword | None = None
    for kw in node.keywords:
        if kw.arg == "consent_collection":
            consent_kw = kw
        elif kw.arg == "custom_text":
            custom_text_kw = kw

    if consent_kw is None:
        return violations

    consent_value = consent_kw.value
    if not isinstance(consent_value, ast.Dict):
        # Helper-built (e.g. ``consent_collection=build_cc()``). We
        # cannot statically inspect; fall through to require the
        # paired custom_text.submit.message ToS surface as the
        # belt-and-suspenders guard.
        if custom_text_kw is None or not _custom_text_mentions_tos(custom_text_kw.value):
            violations.append(
                f"{rel}:{node.lineno}: consent_collection=<non-literal> "
                "without paired custom_text.submit.message ToS surface "
                "(use terms_of_service='auto' or add custom_text)."
            )
        return violations

    # Hard-fail: literal {"terms_of_service": "required"} is the
    # canonical 500-causing pattern.
    if _dict_has_key_value(consent_value, "terms_of_service", "required"):
        violations.append(
            f"{rel}:{node.lineno}: consent_collection contains "
            'terms_of_service="required" — causes Stripe live-mode 500. '
            "Use terms_of_service='auto' or custom_text.submit.message."
        )
        return violations

    # Soft-fail: literal dict that does NOT pin terms_of_service='auto'
    # AND is not paired with a custom_text.submit.message ToS surface
    # in the same call.
    has_auto = _dict_has_key_value(consent_value, "terms_of_service", "auto")
    has_paired_custom = custom_text_kw is not None and _custom_text_mentions_tos(
        custom_text_kw.value
    )
    if not has_auto and not has_paired_custom:
        violations.append(
            f"{rel}:{node.lineno}: consent_collection={{...}} dict literal "
            "must include terms_of_service='auto' OR be paired with "
            "custom_text.submit.message referencing the ToS link."
        )

    return violations


def test_consent_collection_helpers_use_auto_or_custom_text_submit() -> None:
    """Any future ``consent_collection={...}`` helper must be safe.

    Walks every ``ast.Call`` in ``src/jpintel_mcp/api/billing*.py``.
    For each call that passes a ``consent_collection=`` keyword, the
    test enforces one of:

      * the dict is a literal with ``{"terms_of_service": "auto"}``, or
      * the same call passes ``custom_text=`` whose nested
        ``submit.message`` string mentions the ToS link (case-insensitive
        ``tos`` / ``terms`` / ``利用規約``).

    Today there are **zero** ``consent_collection`` literals in the
    billing modules — the live ``stripe.checkout.Session.create`` call
    at ``billing.py:935`` uses ``custom_text.submit.message`` exclusively
    per the 2026-04-23 pivot. This test therefore passes vacuously
    today; its purpose is to fail-closed if a future contributor revives
    the forbidden pattern.
    """
    all_violations: list[str] = []
    for path in _billing_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - billing files must parse
            pytest.fail(f"{rel}: failed to parse for AST scan: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                all_violations.extend(_check_call(node, rel))

    assert all_violations == [], (
        "Stripe consent_collection guard tripped (CLAUDE.md §Common gotchas):\n"
        + "\n".join(all_violations)
    )


# ---------------------------------------------------------------------------
# Test 4: positive convention check — ToS link surfaced via custom_text
# ---------------------------------------------------------------------------


def test_billing_modules_surface_tos_via_custom_text_submit_message() -> None:
    """At least one billing module must surface ToS via custom_text.submit.

    The CLAUDE.md remediation is "use ``custom_text.submit.message`` for
    the ToS link instead". This test verifies the positive convention
    is actually present somewhere in ``src/jpintel_mcp/api/billing*.py``
    so a careless refactor cannot strip both the forbidden
    ``consent_collection`` AND its remediation simultaneously, leaving
    no ToS surface at all (which would be a compliance regression even
    if it doesn't 500).

    Concretely: at least one billing module must contain the substring
    ``custom_text=`` and a string literal mentioning ``tos.html`` (the
    canonical jpcite ToS URL) or ``利用規約``.
    """
    found_custom_text = False
    found_tos_link = False
    for path in _billing_files():
        text = path.read_text(encoding="utf-8")
        if "custom_text" in text:
            found_custom_text = True
        if "tos.html" in text or "利用規約" in text:
            found_tos_link = True

    assert found_custom_text, (
        "No billing*.py module references `custom_text=` — the CLAUDE.md "
        "remediation for the Stripe ToS pitfall has been removed. Restore "
        "custom_text.submit.message with a ToS link."
    )
    assert found_tos_link, (
        "No billing*.py module surfaces a ToS link (`tos.html` or `利用規約`) — "
        "the consent path must remain user-visible even without "
        "consent_collection."
    )
