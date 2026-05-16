"""Dump the FastAPI OpenAPI schema to `docs/openapi/v1.json`.

Mirrors what `.github/workflows/openapi.yml` does, but runnable locally.

By default the preview / roadmap endpoints (legal, accounting, calendar) are
**excluded** — they are gated behind `settings.enable_preview_endpoints` and
the stable public export should not leak unimplemented routes. Pass
`--include-preview` to produce an extended export that advertises them
(useful for "roadmap-as-contract" handouts to prospects / partners).

Usage
-----
    python scripts/export_openapi.py
    python scripts/export_openapi.py --include-preview --out docs/openapi/v1_preview.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_COMPONENT_SCHEMA_NAMES = {
    "jpintel_mcp__api__advisors__SignupRequest": "AdvisorSignupRequest",
    "jpintel_mcp__api__advisors__SignupResponse": "AdvisorSignupResponse",
    "jpintel_mcp__api__alerts__SubscribeRequest": "AlertSubscribeRequest",
    "jpintel_mcp__api__billing__CheckoutRequest": "BillingCheckoutRequest",
    "jpintel_mcp__api__client_profiles__DeleteResponse": "ClientProfileDeleteResponse",
    "jpintel_mcp__api__compliance__CheckoutRequest": "ComplianceCheckoutRequest",
    "jpintel_mcp__api__compliance__CheckoutResponse": "CheckoutResponse",
    "jpintel_mcp__api__compliance__SubscribeRequest": "ComplianceSubscribeRequest",
    "jpintel_mcp__api__compliance__SubscribeResponse": "ComplianceSubscribeResponse",
    "jpintel_mcp__api__customer_webhooks__DeleteResponse": "WebhookDeleteResponse",
    "jpintel_mcp__api__dashboard__UsageDay": "UsageDay",
    "jpintel_mcp__api__invoice_registrants__SearchResponse": ("InvoiceRegistrantSearchResponse"),
    "jpintel_mcp__api__me__UsageDay": "UsageDay",
    "jpintel_mcp__api__saved_searches__DeleteResponse": "SavedSearchDeleteResponse",
    "jpintel_mcp__api__signup__SignupRequest": "TrialSignupRequest",
    "jpintel_mcp__api__signup__SignupResponse": "TrialSignupResponse",
    "jpintel_mcp__api__subscribers__SubscribeRequest": "SubscriberSubscribeRequest",
    "jpintel_mcp__api__subscribers__SubscribeResponse": "SubscriberSubscribeResponse",
    "jpintel_mcp__models__SearchResponse": "ProgramSearchResponse",
}


# -----------------------------------------------------------------------------
# OpenAPI leak sanitizer (A3-style denylist for description/summary text).
#
# OpenAPI specs are auto-generated from FastAPI route docstrings + Pydantic
# field descriptions, so internal table names and runbook references leak into
# the published schema by default. We do NOT edit the source docstrings — there
# are dozens of them and they're more useful with the precise table names. Sanitize
# at export time instead. Pattern denylist parallels
# `scripts/sync_mcp_public_manifests.PUBLIC_DESCRIPTION_REPLACEMENTS`.
# -----------------------------------------------------------------------------

# (regex, replacement). Order matters: longer/specific names first so they win
# before generic `am_*` catch-alls fire on a substring.
OPENAPI_API_KEY_EXAMPLE_RE = re.compile(
    r"(?:X-API-Key\s*:\s*|Authorization\s*:\s*Bearer\s+|Bearer\s+|[?&]key=)"
    r"jc_(?:\.{3}|(?:live|test)_[A-Za-z0-9._-]*)",
    re.IGNORECASE,
)

OPENAPI_LEAK_PATTERN_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ---- am_x+ table names — replace with public-friendly corpus names ----
    (re.compile(r"\bam_compat_matrix\b"), "compatibility-matrix corpus"),
    (re.compile(r"\bam_entity_facts\b"), "entity-fact corpus"),
    (re.compile(r"\bam_entities\b"), "entity corpus"),
    (re.compile(r"\bam_relation\b"), "relationship graph"),
    (re.compile(r"\bam_source\b"), "source catalog"),
    (re.compile(r"\bam_loan_product\b"), "loan-product corpus"),
    (re.compile(r"\bam_law_article\b"), "law-article corpus"),
    (re.compile(r"\bam_enforcement_detail\b"), "enforcement-detail corpus"),
    (re.compile(r"\bam_amount_condition\b"), "amount-condition corpus"),
    (re.compile(r"\bam_tax_treaty\b"), "tax-treaty corpus"),
    (re.compile(r"\bam_industry_jsic\b"), "industry-classification corpus"),
    (re.compile(r"\bam_application_round\b"), "application-round corpus"),
    (re.compile(r"\bam_amendment_snapshot\b"), "historical amendment snapshot"),
    (re.compile(r"\bam_amendment_diff\b"), "public change log"),
    (re.compile(r"\bam_funding_stack_empirical\b"), "funding-stack corpus"),
    (re.compile(r"\bam_program_eligibility_predicate\b"), "eligibility-predicate corpus"),
    (re.compile(r"\bam_entity_annotation\b"), "entity annotations"),
    (re.compile(r"\bam_entity_source\b"), "entity-level source references"),
    (re.compile(r"\bam_validation_rule\b"), "configured validation rules"),
    # Catch-all for remaining am_*, jpi_*, jc_* schema-prefixed names.
    (re.compile(r"\bjpi_[A-Za-z0-9_]+\b"), "public dataset"),
    (re.compile(r"\bjc_[a-z0-9_]+\b"), "public dataset"),
    (re.compile(r"\bam_[A-Za-z0-9_]+\b"), "source-derived dataset"),
    # ---- Internal operational table names ----
    (re.compile(r"\bhoujin_watch\b"), "corporate watch list"),
    (re.compile(r"\busage_events\b"), "usage tagging"),
    (re.compile(r"\bapi_keys\b"), "API keys"),
    (re.compile(r"\bcost_ledger\b"), "cost summary"),
    (re.compile(r"\bidempotency_cache\b"), "idempotency store"),
    (re.compile(r"\bclient_profiles\b"), "client profile dataset"),
    (re.compile(r"\baudit_seal\b"), "audit-seal dataset"),
    (re.compile(r"\btrust_infrastructure\b"), "trust infrastructure"),
    # ---- Internal DB filenames ----
    (re.compile(r"\bjpintel\.db\b", re.IGNORECASE), "primary corpus database"),
    (re.compile(r"\bautonomath\.db\b", re.IGNORECASE), "primary corpus database"),
    # ---- Wave / migration / CLAUDE.md / DEEP markers ----
    (re.compile(r"CLAUDE\.md gotcha", re.IGNORECASE), "known data-quality caveat"),
    (re.compile(r"\bCLAUDE\.md\b"), ""),
    (re.compile(r"\bDEEP-\d+\b"), ""),
    (re.compile(r"\bWave\s+\d+(?:\.\d+)*\b"), ""),
    (re.compile(r"\bwave\s+\d+\b", re.IGNORECASE), ""),
    (re.compile(r"\bmigrations?\s+\d+(?:[-/]\d+)+\b", re.IGNORECASE), "schema update"),
    (re.compile(r"\bmigration\s+\d+\b", re.IGNORECASE), "schema update"),
    (re.compile(r"\bmig\s+\d+\b", re.IGNORECASE), "schema update"),
    # ---- Public scope normalization ----
    (
        re.compile(r"\bEvery tool response carries\b", re.IGNORECASE),
        "Evidence-oriented tool responses include",
    ),
    (re.compile(r"\bevery response carries\b", re.IGNORECASE), "covered responses include"),
    (re.compile(r"\bevery response surfaces\b", re.IGNORECASE), "covered responses surface"),
    (re.compile(r"\benvelope on every response\b", re.IGNORECASE), "envelope on covered responses"),
    (
        re.compile(r"\battribution baked into every response\b", re.IGNORECASE),
        "attribution included in covered responses",
    ),
    # ---- Operator script paths ----
    (re.compile(r"`?scripts/cron/[A-Za-z0-9_./-]+`?"), "scheduled job"),
    (re.compile(r"`?scripts/etl/[A-Za-z0-9_./-]+`?"), "background ETL"),
    (re.compile(r"`?scripts/migrations/[A-Za-z0-9_./-]+`?"), "schema update"),
    (re.compile(r"`?scripts/[A-Za-z0-9_./-]+\.(?:py|sh|sql)`?"), "operator script"),
)

# Belt-and-suspenders post-export gate. Any pattern listed here is treated as a
# hard leak — if it survives the sanitizer pass the export aborts so a stale
# spec is never committed. Keep in sync with `BANNED_PUBLIC_LEAK_PATTERNS` in
# scripts/sync_mcp_public_manifests.py.
BANNED_OPENAPI_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bam_compat_matrix\b"),
    re.compile(r"\bam_entity_facts\b"),
    re.compile(r"\bam_entities\b"),
    re.compile(r"\bam_relation\b"),
    re.compile(r"\bam_loan_product\b"),
    re.compile(r"\bam_law_article\b"),
    re.compile(r"\bam_enforcement_detail\b"),
    re.compile(r"\bam_amount_condition\b"),
    re.compile(r"\bam_tax_treaty\b"),
    re.compile(r"\bam_industry_jsic\b"),
    re.compile(r"\bam_application_round\b"),
    re.compile(r"\bam_amendment_snapshot\b"),
    re.compile(r"\bam_amendment_diff\b"),
    re.compile(r"\bhoujin_watch\b"),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bcost_ledger\b"),
    re.compile(r"\bidempotency_cache\b"),
    re.compile(r"\bjpintel\.db\b", re.IGNORECASE),
    re.compile(r"\bautonomath\.db\b", re.IGNORECASE),
    re.compile(r"CLAUDE\.md"),
    re.compile(r"\bWave\s+\d", re.IGNORECASE),
    re.compile(r"\bmigration\s+\d", re.IGNORECASE),
    re.compile(r"\bscripts/cron/"),
    re.compile(r"\bscripts/etl/"),
)


def _strip_openapi_leak_patterns(text: str) -> str:
    """Apply the A3-style denylist to a single string."""
    protected_api_key_examples: list[str] = []

    def _protect_api_key_example(match: re.Match[str]) -> str:
        protected_api_key_examples.append(match.group(0))
        return f"@@OPENAPI_API_KEY_EXAMPLE_{len(protected_api_key_examples) - 1}@@"

    out = OPENAPI_API_KEY_EXAMPLE_RE.sub(_protect_api_key_example, text)
    for pattern, replacement in OPENAPI_LEAK_PATTERN_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    # Collapse whitespace that the empty-string replacements left behind.
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([,.;:])", r"\1", out)
    for index, value in enumerate(protected_api_key_examples):
        out = out.replace(f"@@OPENAPI_API_KEY_EXAMPLE_{index}@@", value)
    return out


# -----------------------------------------------------------------------------
# JSON-pointer exemption list for the leak sanitizer.
#
# E5 originally walked every string in the OpenAPI schema and applied the
# `am_*` → public-friendly replacement table to all of them. That clobbered
# spec values that MUST stay byte-identical to the runtime response (Pydantic
# `default` literals, response/request `example` payloads, operation IDs).
# E11 audit caught the spec↔runtime drift; per that audit we exempt the
# following JSON-pointer-derived contexts from the leak walk:
#
#   * `paths.*.*.responses.*.content.*.example` and `…examples.*.value`
#   * `paths.*.*.requestBody.content.*.example` and `…examples.*.value`
#   * `components.schemas.*.properties.*.default`
#   * the entire `operationId` field (route-derived identifier)
#
# Implementation: we don't try to match full JSON pointers — we just track the
# parent key while descending, and if the current key matches one of the
# exempt keys we freeze the whole subtree below it (no string rewrites occur
# anywhere inside that subtree). This is conservative but matches the user
# contract: spec must promise X iff runtime returns X.
# -----------------------------------------------------------------------------
EXEMPT_LEAK_WALK_KEYS: frozenset[str] = frozenset(
    {
        "default",
        "example",
        "examples",
        "operationId",
    }
)


def _walk_strings(
    node: Any,
    transform,
    *,
    exempt: bool = False,
    parent_key: str | None = None,
) -> None:
    """Apply ``transform`` to every string value in ``node`` (in place).

    When the recursion descends into a node whose parent key is in
    ``EXEMPT_LEAK_WALK_KEYS`` (or anywhere underneath such a node), the
    ``transform`` is skipped — string values are kept verbatim so spec
    ``default`` / ``example`` literals stay byte-identical to the runtime
    response. We still recurse into children so the tree is fully walked,
    but no rewrites occur on the exempt subtree.
    """
    if isinstance(node, dict):
        for key, value in list(node.items()):
            child_exempt = exempt or key in EXEMPT_LEAK_WALK_KEYS
            if isinstance(value, str):
                if not child_exempt:
                    node[key] = transform(value)
            else:
                _walk_strings(value, transform, exempt=child_exempt, parent_key=key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                if not exempt:
                    node[index] = transform(value)
            else:
                _walk_strings(value, transform, exempt=exempt, parent_key=parent_key)


def sanitize_openapi_schema_leaks(schema: dict[str, Any]) -> None:
    """Walk a full OpenAPI schema and strip internal leak patterns in place.

    Public entry point so `scripts/export_agent_openapi.py` can apply the same
    rules to the agent projection without duplicating the table.
    """
    _walk_strings(schema, _strip_openapi_leak_patterns)


def _redact_exempt_subtrees_for_scan(node: Any, *, exempt: bool = False) -> Any:
    """Return a deep-copied tree with exempt subtree string values blanked.

    The post-export leak gate (`assert_no_openapi_leaks`) scans the rendered
    JSON payload for banned patterns. Once the sanitizer walker exempts
    `default` / `example` / `operationId` values, those literals will legally
    contain `am_*` strings (because the Pydantic source defines them and we
    don't rewrite spec values that the runtime echoes back). The leak gate
    must therefore ignore those exempt slots too — we blank them in a copy
    before scanning so the gate still trips on description/summary leaks but
    accepts byte-identical default/example/operationId payloads.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            child_exempt = exempt or key in EXEMPT_LEAK_WALK_KEYS
            if isinstance(value, str):
                out[key] = "" if child_exempt else value
            else:
                out[key] = _redact_exempt_subtrees_for_scan(value, exempt=child_exempt)
        return out
    if isinstance(node, list):
        result: list[Any] = []
        for item in node:
            if isinstance(item, str):
                result.append("" if exempt else item)
            else:
                result.append(_redact_exempt_subtrees_for_scan(item, exempt=exempt))
        return result
    return node


def assert_no_openapi_leaks(payload: str, *, label: str = "openapi spec") -> None:
    """Hard gate: raise if a banned pattern survived in the rendered string.

    The payload is parsed as JSON so we can blank out exempt JSON-pointer
    subtrees (default / example / examples / operationId) before scanning —
    those slots are spec↔runtime contracts and must stay verbatim even when
    they happen to embed an `am_*` literal. Description / summary leaks
    still trip the gate.
    """
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        redacted = _redact_exempt_subtrees_for_scan(parsed)
        scan_target = json.dumps(redacted, ensure_ascii=False)
    else:
        scan_target = payload
    leaks: list[str] = []
    for pattern in BANNED_OPENAPI_LEAK_PATTERNS:
        match = pattern.search(scan_target)
        if match:
            idx = match.start()
            window = scan_target[max(0, idx - 60) : idx + 80].replace("\n", " ")
            leaks.append(f"{pattern.pattern!r} near …{window}…")
    if leaks:
        raise SystemExit(f"sanitizer would leak banned patterns into {label}: {leaks}")


def _build_app(include_preview: bool):
    # Flip the setting BEFORE importing the API module so `create_app()` sees
    # it. The setting is consulted once at app-construction time.
    if include_preview:
        # Purge any already-imported jpintel_mcp modules so Settings re-reads
        # env vars and the preview routers are included.
        import os

        os.environ["JPINTEL_ENABLE_PREVIEW_ENDPOINTS"] = "true"
        for mod in list(sys.modules):
            if mod.startswith("jpintel_mcp"):
                del sys.modules[mod]

    from jpintel_mcp.api.main import create_app

    return create_app()


def _camelize(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_\W]+", value) if part)


def _public_component_schema_name(name: str) -> str:
    explicit = _COMPONENT_SCHEMA_NAMES.get(name)
    if explicit:
        return explicit
    if not name.startswith("jpintel_mcp__"):
        return name

    parts = name.split("__")
    model_name = parts[-1]
    module_parts = [part for part in parts[1:-1] if part not in {"api", "models", "jpintel_mcp"}]
    prefix = "".join(_camelize(part) for part in module_parts[-2:])
    return f"{prefix}{model_name}" if prefix else model_name


def _rewrite_refs(node: Any, renamed: dict[str, str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            prefix = "#/components/schemas/"
            if ref.startswith(prefix):
                name = ref[len(prefix) :]
                public_name = renamed.get(name)
                if public_name:
                    node["$ref"] = f"{prefix}{public_name}"
        for value in node.values():
            _rewrite_refs(value, renamed)
    elif isinstance(node, list):
        for item in node:
            _rewrite_refs(item, renamed)


def _normalize_component_schema_names(schema: dict[str, Any]) -> None:
    components = schema.get("components")
    if not isinstance(components, dict):
        return
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return

    renamed = {
        name: _public_component_schema_name(name)
        for name in schemas
        if _public_component_schema_name(name) != name
    }
    if not renamed:
        return

    normalized: dict[str, Any] = {}
    for name, component_schema in schemas.items():
        public_name = renamed.get(name, name)
        existing = normalized.get(public_name)
        if existing is not None and existing != component_schema:
            raise RuntimeError(f"OpenAPI component rename collision: {name} -> {public_name}")
        normalized[public_name] = component_schema
    components["schemas"] = normalized
    _rewrite_refs(schema, renamed)


def _sanitize_public_text(text: str) -> str:
    """Remove implementation/runbook wording from the published schema."""
    text = re.sub(
        r"\A(?:Stripe webhook|stripe webhook|billing event) endpoint\..*",
        "Billing event endpoint.",
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\APersist a (?:trial_signups|trial signup) (?:row|record) \+ mail a magic link\. Always 202 Accepted\..*",
        (
            "Accept a trial signup and send a magic link. Accepted signup "
            "attempts return 202.\n\n"
            "The response shape is stable so signups do not disclose whether an "
            "address has already used a trial. Rate-limit failures may return 429. "
            "Trial keys are not connected to paid billing."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AVerify the magic-link token, issue a trial key, redirect to /trial\.html\..*",
        (
            "Verify a magic-link token, issue a trial key, and redirect to the "
            "trial page. Invalid, expired, or already-used links redirect with "
            "a status indicator. Successful verification returns the newly "
            "issued key in the URL fragment for one-time display."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AList the calling key's webhooks .*",
        ("List the calling key's registered outbound webhooks, including disabled webhooks."),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ARegister a new outbound webhook\..*",
        (
            "Register a new outbound webhook. The response includes the "
            "signing secret once; subsequent reads include only a short "
            "signing secret hint."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ARecords the calling key's preference for which inbound parse address to publish\..*",
        (
            "Record the calling key's preferred inbound email parse address. "
            "Final setup may require support assistance."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ACreate an unverified advisor profile \+ return Stripe Connect onboarding URL\..*",
        (
            "Create an advisor profile and return an onboarding URL when "
            "available. Self-serve signup does not require an API key."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AConfirm the advisor's 法人番号 exists in invoice registrant records .*",
        (
            "Confirm an advisor's 法人番号 against invoice registrant records "
            "and mark the advisor profile as verified when it matches."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ACreate a new pending subscription \+ send verification email\..*",
        (
            "Create a pending subscription and send a verification email. "
            "Duplicate requests use the same response shape to avoid email "
            "enumeration."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AMark a subscriber as verified\. Renders a minimal HTML page\..*",
        (
            "Verify a subscriber email token and render a confirmation page. "
            "Repeated valid clicks are idempotent. Paid subscribers are "
            "directed to checkout."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"Set when the tool failed \(DB unavailable / invalid input\)\.",
        "Set when the request cannot be completed.",
        text,
    )
    text = re.sub(r"P0 fixes from audit.*?(?=\n\n\*\*|\Z)", "", text, flags=re.S)
    text = re.sub(r"\*\*Operator\*\*:.*?(?=\n\n|\Z)", "", text, flags=re.S)
    text = re.sub(r"Operator: Bookyou株式会社.*?(?=\.|\n)", "jpcite support", text)
    text = re.sub(r"See `src/[^`]+` module docstring for scope\.\n?", "", text)
    text = re.sub(r"\(memory: [^)]+\)", "", text)
    text = re.sub(r"memory: [A-Za-z0-9_/-]+", "", text)
    text = re.sub(
        r"\*\*404 semantics:\*\*.*?\n\n",
        (
            "**404 semantics:** A miss means the record is not available in "
            "jpcite's current snapshot. The response includes official lookup "
            "guidance when available.\n\n"
        ),
        text,
        flags=re.S,
    )
    replacements = [
        (r"info@bookyou\.net", "support contact"),
        (r"Bookyou株式会社", "support team"),
        (r"Bookyou Inc\.", "support team"),
        (r"T8010001213708", "support contact"),
        (r"usage_events", "usage records"),
        (r"jpintel\.db", "indexed corpus"),
        (r"autonomath\.db", "extended corpus"),
        (r"\bBackgroundTasks\b", "background work"),
        (r"\bSQLite\b", "persistent storage"),
        (r"stripe_webhook_events", "billing event records"),
        (r"\bsecret_hmac\b", "signing secret"),
        (r"\bsecret_last4\b", "signing secret hint"),
        (r"trial_signups", "trial signup"),
        (r"\bUNIQUE\b", "deduplication rule"),
        (r"\bIntegrityError\b", "duplicate signup"),
        (r"deps\._enforce_quota", "quota checks"),
        (r"ApiContext\.metered", "metering checks"),
        (r"issued_api_key_hash", "issued key record"),
        (r"raw-key", "one-time key"),
        (r"raw API key", "one-time API key"),
        (
            r"Returned when STRIPE_SECRET_KEY is set\. Null in dev/offline mode — the signup record is still created so the advisor can retry onboarding\.",
            "Returned when Stripe onboarding is available. Null when onboarding cannot be started immediately; the signup record is still created so the advisor can retry.",
        ),
        (r"\bSTRIPE_SECRET_KEY\b", "Stripe onboarding"),
        (r"\bdev/offline mode\b", "onboarding unavailable"),
        (r"\bWired by L5\.?", ""),
        (r"safe overshoot", "conservative estimate"),
        (
            r"Honeypot\. Real callers MUST leave this null/empty\. The web form hides this field via CSS; only autofilled bots populate it\. Any non-empty value is treated as abuse and rejected\.",
            "Reserved anti-abuse field. Leave it empty.",
        ),
        (r"\(api/programs\.py\)", ""),
        (r"empty-corpus query", "unbounded saved search"),
        (r"free \(dunning\) tiers", "temporary billing-status cases"),
        (
            r"Authentication: intentionally light today.*",
            "Access is limited to the advisor dashboard flow.",
        ),
        (
            r"\s*expected to be reached via the Stripe Connect Express portal return\n"
            r"URL \(or via magic-link email\)\. Adding API-key auth here would block\n"
            r"the simplest flow where the advisor arrives from Stripe's own\n"
            r"dashboard\. If this becomes abused, add a signed HMAC\n"
            r"``\?token=\.\.\.`` in the URL and verify here\.",
            "",
        ),
        (
            r"If this becomes abused, add a signed HMAC\s+``\?token=\.\.\.`` "
            r"in the URL and verify here\.",
            "",
        ),
        (r"runaway-billing", "excess delivery"),
        (r"hammering their downstream", "sending too many test requests"),
        (r"scripts/[^\s`)]+", "scheduled source refresh"),
        (r"seed_advisors\.py", "source refresh"),
        (r"\bDB unavailable\b", "service unavailable"),
        (r"docs/_internal/[^\s`)]+", "support-assisted setup notes"),
        (r"default gates", "standard configuration"),
        (r"legal review pending", "not publicly available"),
        (r"\bbroken\b", "disabled"),
        (r"\bmigration\s+\d+", "schema update"),
        (r"\bcron\b", "scheduled job"),
        (r"\bOperator\b", "Support team"),
        (r"\boperator\b", "support team"),
        (r"\binternal HTTP hop\b", "extra HTTP hop"),
        (r"\binternal-only columns\b", "non-public columns"),
        (r"\binternal-only\b", "non-public"),
        (r"\binternal runbook\b", "support-assisted setup notes"),
        (r"\bsupport runbook\b", "support-assisted setup notes"),
        (r"\binternal write\b", "write"),
        (r"\bInternal error\b", "Server error"),
        (r"\binternal client identifier\b", "client-defined identifier"),
        (r"\binternal billing\b", "billing"),
        (r"\binternal\b", "service"),
        (r"\bV4\b", "current release"),
        (r"\bP3-W\b", "budget control"),
        (r"\brequire_key\b", "API-key authentication"),
        (r"\bapi_keys row\b", "API key"),
        (r"\bapi_keys\b", "API keys"),
        (r"\braw key\b", "newly issued key"),
        (r"\bin-process pickup\b", "one-time retrieval"),
        (r"\bfull table\b", "complete dataset"),
        (r"\bam_relation\b", "relationship graph"),
        (r"\bStripe webhook\b", "billing event"),
        (r"\bstripe webhook\b", "billing event"),
        (r"\bsource records\b", "public records"),
        (r"\bsource record\b", "public record"),
        (r"project_autonomath_business_model", "the published pricing model"),
        (r"feedback_autonomath_no_api_use", "jpcite does not call an LLM API"),
        (r"metadata\.autonomath_product", "metadata.product"),
        (r"autonomath\.intake_consistency_rules", "jpcite validation rules"),
        (r"autonomath\.intake\.", "jpcite.validation."),
        (r"\bAUTONOMATH_SNAPSHOT_ENABLED\b", "snapshot feature flag"),
        (r"\bautonomath public dataset\b", "public adoption dataset"),
        (r"\bautonomath canonical id\b", "stable legacy id"),
        (r"\bautonomath spine\b", "historical snapshot index"),
        (r"\bAutonoMath\b", "jpcite"),
        (r"\bautonomath dataset\b", "jpcite dataset"),
        (r"\bunified autonomath dataset\b", "unified jpcite dataset"),
        (r"\(autonomath\)", ""),
        (r"\(jpintel\)", ""),
        (r"\bjpintel\b", "jpcite"),
        (
            r"jpintel_mcp\.utils\.slug\.program_static_url",
            "jpcite static URL builder",
        ),
        (r"jpintel_mcp\.utils\.slug", "jpcite static URL builder"),
        (r"am_validation_rule", "configured validation rules"),
        (r"jpintel 内", "jpcite で"),
        (r"jpcite でで", "jpcite で"),
        (r"\bapi_key_hash\b", "API key identifier"),
        (
            r"``GOOGLE_OAUTH_CLIENT_ID`` env var must be set on the support team "
            r"side before this works \(503 otherwise\)\.",
            "Google OAuth must be configured before this works (503 otherwise).",
        ),
        (r"\bNO billing\b", "no billing charge"),
        (r"\bFREE\b", "no request charge"),
        (
            r"the two values differ only in the guarantee that full's "
            r"enriched/source_mentions keys are present even when null",
            "the two values differ only in the documented `full` response shape; "
            "enriched/source_mentions keys are included even when null",
        ),
        (r"keys guaranteed present", "keys included in the documented response shape"),
        (r"\bguaranteed present\b", "included in the documented response shape"),
        (
            r"must yield byte-identical\n\s+results, OR",
            "is expected to yield byte-identical results, or",
        ),
        (r"manual review", "support review"),
        (r"manual support team action", "support-assisted setup"),
        (r"data/workpapers/[^\s`)]+", "generated PDF"),
        (r"data/quarterly_pdfs/[^\s`)]+", "generated PDF"),
        (r"benchmark bundles?", "JSON responses"),
        (r"debugging or post-deploy verification", "fresh status checks"),
        (r"post-launch monthly bulk refresh", "scheduled source refresh"),
        (r"launch-week miss frequently means", "miss may mean"),
        (r"X-Zeimu-", "X-Jpcite-"),
        (r"fts5_trigram \+ LIKE fallback", "text search with fallback matching"),
        (r"FTS5 trigram", "text search"),
        (r"FTS5", "text search"),
        (r"fts5_trigram", "text search"),
        (r"\bFTS\b", "text search"),
        (r"trigram tokenizer limitation", "short-query limitation"),
        (r"trigram zero-match", "short-query zero-match"),
        (
            r"quoted-phrase workaround for 2\+ character kanji compounds",
            "Japanese phrase normalization",
        ),
        (r"quality-gate quarantine", "publication review hold"),
        (r"Tier X", "non-public records"),
        (r"tier X", "non-public records"),
        (r"[Rr]eview-held(?:/quarantine)? records?", "non-public records"),
        (r"[Rr]eview-held(?:/quarantine)? rows?", "non-public records"),
        (r"\bquarantine rows?", "non-public records"),
        (r"case_studies_fts", "case study index"),
        (r"corpus dump guard", "broad empty-search guard"),
        (r"\bhandler\b", "API"),
        (r"am_entity_facts\.source_id", "per-fact source reference"),
        (r"am_entity_facts\.id", "fact identifier"),
        (r"am_entities\.canonical_id", "stable entity identifier"),
        (r"am_entity_source", "entity-level source references"),
        (r"am_entity_annotation", "entity annotations"),
        (r"am_entity_facts", "fact records"),
        (r"am_entities", "public records"),
        (r"am_source", "source catalog"),
        (r"am_amendment_diff", "public change log"),
        (r"am_amendment_snapshot", "historical snapshot"),
        (r"entity_id_map", "stable identifier map"),
        (r"jpi_[A-Za-z0-9_]+", "public dataset"),
        (r"programs\.unified_id", "linked program identifier"),
        (r"invoice_registrants", "invoice registrant records"),
        (r"widget_keys row", "widget key"),
        (r"\bLIKE\b", "fallback matching"),
        (r"\brank(ed|ing)?\b", "relevance-ordered"),
        (r"\bcache key\b", "repeat-request matching"),
        (r"\bcached\b", "temporarily reused"),
        (r"\bcache\b", "short-lived response reuse"),
        (r"\btable\b", "dataset"),
        (r"\btables\b", "datasets"),
        (r"\bview\b", "dataset"),
        (r"\bviews\b", "datasets"),
        (r"\bMigration\b", "Schema update"),
        (r"\bmigration\b", "schema update"),
        (r"\bmig(?:ration)?\.?\s*\d+", "schema update"),
        (r"\.sql\b", ""),
        (r"\bwave\s*\d+\b", "current release"),
        (r"\bWave\s*\d+\b", "Current release"),
        (r"\bphase[_ -]?[A-Za-z0-9]+\b", "release track"),
        (r"\bgate(d)?\b", "controlled"),
        (r"not re-metered", "not billed again"),
        (r"read-from-disk", "read from packaged data"),
        (r"\brows\b", "records"),
        (r"\brow\b", "record"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    pricing_replacements = [
        (r"¥3 / リクエスト 完全従量", "¥3/billable unit 完全従量"),
        (r"¥3/request", "¥3/billable unit"),
        (r"¥3/req", "¥3/billable unit"),
        (r"¥3 per request", "¥3 per billable unit"),
        (
            r"One ¥3 charge per request regardless of format\.",
            "One billable unit regardless of format.",
        ),
        (r"Single ¥3 charge per request", "Single billable unit"),
    ]
    for pattern, replacement in pricing_replacements:
        text = re.sub(pattern, replacement, text)
    text = text.replace("¥3/billable unit unit price", "¥3/billable unit price")
    # Keep this aligned with src/jpintel_mcp/api/main.py. The generic
    # row/record rewrite runs late, so re-apply the public source wording after
    # that pass.
    text = re.sub(r"\bsource records\b", "public records", text)
    text = re.sub(r"\bsource record\b", "public record", text)
    # A3-style leak sanitizer: strip am_* table names, internal operational
    # tables, DB filenames, Wave/migration/CLAUDE.md markers, and operator
    # script paths. Runs last so the legacy replacements above can rewrite
    # without colliding with the leak rules.
    text = _strip_openapi_leak_patterns(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sanitize_public_schema(node: Any, *, exempt: bool = False) -> None:
    # `exempt=True` is propagated from a parent dict whose key was in
    # EXEMPT_LEAK_WALK_KEYS (default / example / examples / operationId). In
    # that subtree we skip the text rewrites so spec values stay byte-identical
    # to the runtime response — but we still recurse so non-leak-sensitive
    # normalizations (e.g. tag renames) keep applying where they would have.
    if isinstance(node, dict):
        info = node.get("info")
        if isinstance(info, dict):
            info.pop("contact", None)
        tags = node.get("tags")
        if isinstance(tags, list):
            # Operation-level `tags` is a list of strings; root-level
            # `tags` is a list of `{name, description}` dicts. Apply the
            # legacy autonomath -> jpcite rename to both shapes.
            _legacy_rename = {
                "autonomath": "jpcite",
                "autonomath-health": "jpcite-health",
            }
            new_tags: list[Any] = []
            for item in tags:
                if isinstance(item, str):
                    new_tags.append(_legacy_rename.get(item, item))
                elif isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name in _legacy_rename:
                        item = dict(item)
                        item["name"] = _legacy_rename[name]
                    new_tags.append(item)
                else:
                    new_tags.append(item)
            node["tags"] = new_tags
        if node.get("title") == "WebhookResponse":
            properties = node.get("properties")
            if isinstance(properties, dict):
                secret_schema = properties.pop("secret_hmac", None)
                if isinstance(secret_schema, dict):
                    secret_schema["title"] = "Signing Secret"
                    properties["signing_secret"] = secret_schema
                hint_schema = properties.pop("secret_last4", None)
                if isinstance(hint_schema, dict):
                    hint_schema["title"] = "Signing Secret Hint"
                    properties["signing_secret_hint"] = hint_schema
            required = node.get("required")
            if isinstance(required, list):
                node["required"] = [
                    {
                        "secret_hmac": "signing_secret",
                        "secret_last4": "signing_secret_hint",
                    }.get(item, item)
                    for item in required
                ]
        if node.get("title") == "_DataHealthCheck":
            properties = node.get("properties")
            if isinstance(properties, dict) and "table" in properties:
                properties["dataset"] = properties.pop("table")
                dataset_schema = properties.get("dataset")
                if isinstance(dataset_schema, dict):
                    dataset_schema["title"] = "Dataset"
            required = node.get("required")
            if isinstance(required, list):
                node["required"] = ["dataset" if item == "table" else item for item in required]
        properties = node.get("properties")
        if isinstance(properties, dict):
            contact_schema = properties.get("contact")
            if (
                isinstance(contact_schema, dict)
                and contact_schema.get("default") == "info@bookyou.net"
            ):
                contact_schema.pop("default", None)
                contact_schema.setdefault("description", "Support contact.")
        enum_values = node.get("enum")
        if isinstance(enum_values, list):
            node["enum"] = [item for item in enum_values if item != "internal"]
        parameters = node.get("parameters")
        if isinstance(parameters, list):
            node["parameters"] = [
                parameter
                for parameter in parameters
                if not (isinstance(parameter, dict) and parameter.get("name") == "include_internal")
            ]
        for key, value in list(node.items()):
            child_exempt = exempt or key in EXEMPT_LEAK_WALK_KEYS
            if isinstance(value, str):
                if not child_exempt:
                    node[key] = _sanitize_public_text(value)
            else:
                _sanitize_public_schema(value, exempt=child_exempt)
    elif isinstance(node, list):
        for item in node:
            _sanitize_public_schema(item, exempt=exempt)


# ----- gpt30 profile -----------------------------------------------------
#
# GPT Store Custom Actions cap operations at 30 per Action and only accept
# OpenAPI 3.0.x (not 3.1.x) with a single `servers[]` entry. This profile
# subsets the full v1 schema to a curated 30-path slice that covers the
# evidence-prefetch + company-public-record flow advertised in
# `site/openapi.agent.gpt30.json`, downgrades the schema header to 3.0.3,
# rewrites null-typed schemas to the 3.0 nullable form, and rewrites
# operationIds to camelCase where they were left as the FastAPI default.
#
# Keep this list aligned with the `x-jpcite-agent-call-order-policy` in
# the published `site/openapi.agent.gpt30.json` — agents key off these
# specific operations.
GPT30_PATHS: tuple[str, ...] = (
    # Curated 30-path slice covering the evidence-prefetch + company-public-
    # record flow advertised in site/openapi.agent.gpt30.json. Keep aligned
    # with `x-jpcite-agent-call-order-policy` in the published file.
    "/v1/advisors/match",
    "/v1/am/law_article",
    "/v1/artifacts/company_folder_brief",
    "/v1/artifacts/company_public_audit_pack",
    "/v1/artifacts/company_public_baseline",
    "/v1/bids/search",
    "/v1/bids/{unified_id}",
    "/v1/case-studies/search",
    "/v1/citations/verify",
    "/v1/cost/preview",
    "/v1/court-decisions/search",
    "/v1/court-decisions/{unified_id}",
    "/v1/enforcement-cases/search",
    "/v1/enforcement-cases/{case_id}",
    "/v1/evidence/packets/query",
    "/v1/evidence/packets/{subject_kind}/{subject_id}",
    "/v1/funding_stack/check",
    "/v1/houjin/{bangou}",
    "/v1/intelligence/precomputed/query",
    "/v1/invoice_registrants/search",
    "/v1/invoice_registrants/{invoice_registration_number}",
    "/v1/laws/search",
    "/v1/laws/{unified_id}",
    "/v1/laws/{unified_id}/related-programs",
    "/v1/meta/freshness",
    "/v1/programs/prescreen",
    "/v1/programs/search",
    "/v1/programs/{unified_id}",
    "/v1/tax_rulesets/search",
    "/v1/tax_rulesets/{unified_id}",
)


_GPT30_OPERATION_IDS: dict[tuple[str, str], str] = {
    # (path, method-lowercase) -> stable camelCase operationId.
    # The advisor-match id is kept as the published string because GPT
    # Actions are already bound to it via the agent-call-order policy.
    ("/v1/advisors/match", "get"): "match_advisors_v1_advisors_match_get",
    ("/v1/am/law_article", "get"): "getLawArticle",
    ("/v1/artifacts/company_folder_brief", "post"): "createCompanyFolderBrief",
    ("/v1/artifacts/company_public_audit_pack", "post"): "createCompanyPublicAuditPack",
    ("/v1/artifacts/company_public_baseline", "post"): "createCompanyPublicBaseline",
    ("/v1/bids/search", "get"): "searchBids",
    ("/v1/bids/{unified_id}", "get"): "getBid",
    ("/v1/case-studies/search", "get"): "searchCaseStudies",
    ("/v1/citations/verify", "post"): "verifyCitations",
    ("/v1/cost/preview", "post"): "previewCost",
    ("/v1/court-decisions/search", "get"): "searchCourtDecisions",
    ("/v1/court-decisions/{unified_id}", "get"): "getCourtDecision",
    ("/v1/enforcement-cases/search", "get"): "searchEnforcementCases",
    ("/v1/enforcement-cases/{case_id}", "get"): "getEnforcementCase",
    ("/v1/evidence/packets/query", "post"): "queryEvidencePacket",
    ("/v1/evidence/packets/{subject_kind}/{subject_id}", "get"): "getEvidencePacket",
    ("/v1/funding_stack/check", "post"): "checkFundingStack",
    ("/v1/houjin/{bangou}", "get"): "getHoujin360",
    ("/v1/intelligence/precomputed/query", "get"): "prefetchIntelligence",
    ("/v1/intelligence/precomputed/query", "post"): "prefetchIntelligence",
    ("/v1/invoice_registrants/search", "get"): "searchInvoiceRegistrants",
    ("/v1/invoice_registrants/{invoice_registration_number}", "get"): "getInvoiceRegistrant",
    ("/v1/laws/search", "get"): "searchLaws",
    ("/v1/laws/{unified_id}", "get"): "getLaw",
    ("/v1/laws/{unified_id}/related-programs", "get"): "getLawRelatedPrograms",
    ("/v1/meta/freshness", "get"): "getMetaFreshness",
    ("/v1/programs/prescreen", "post"): "prescreenPrograms",
    ("/v1/programs/search", "get"): "searchPrograms",
    ("/v1/programs/{unified_id}", "get"): "getProgram",
    ("/v1/tax_rulesets/search", "get"): "searchTaxRulesets",
    ("/v1/tax_rulesets/{unified_id}", "get"): "getTaxRuleset",
}


def _camelize_operation_id(value: str) -> str:
    """FastAPI default operationId looks like ``foo_bar_v1_things_get``.

    Strip the noisy ``_v1_..._{method}`` suffix when present and emit a clean
    camelCase identifier for GPT Actions.
    """
    if not value:
        return value
    stem = re.sub(r"_v1_.*?_(get|post|put|patch|delete)$", "", value)
    if not stem:
        stem = value
    parts = [part for part in re.split(r"[_\W]+", stem) if part]
    if not parts:
        return value
    head, *tail = parts
    return head[:1].lower() + head[1:] + "".join(p[:1].upper() + p[1:] for p in tail)


def _downgrade_nullable(node: Any) -> None:
    """Rewrite OpenAPI 3.1 ``type: ["string", "null"]`` and ``anyOf [{type:null}]``
    forms into OpenAPI 3.0 ``nullable: true`` so GPT Actions accepts the spec.
    """
    if isinstance(node, dict):
        # Pattern 1: type is a list including "null"
        if isinstance(node.get("type"), list):
            types = [t for t in node["type"] if t != "null"]
            had_null = len(types) != len(node["type"])
            if had_null:
                if len(types) == 1:
                    node["type"] = types[0]
                elif not types:
                    node.pop("type", None)
                else:
                    node["type"] = types
                node["nullable"] = True
        # Pattern 2: anyOf/oneOf containing {"type": "null"}
        for combinator in ("anyOf", "oneOf"):
            options = node.get(combinator)
            if isinstance(options, list):
                pruned = [
                    opt
                    for opt in options
                    if not (isinstance(opt, dict) and opt.get("type") == "null")
                ]
                if len(pruned) != len(options):
                    node["nullable"] = True
                    if len(pruned) == 1:
                        # Hoist single remainder up while preserving siblings.
                        remainder = pruned[0]
                        node.pop(combinator)
                        if isinstance(remainder, dict):
                            for k, v in remainder.items():
                                node.setdefault(k, v)
                    elif pruned:
                        node[combinator] = pruned
                    else:
                        node.pop(combinator, None)
        # Pattern 3: const must become single-item enum on 3.0
        if "const" in node and "enum" not in node:
            node["enum"] = [node.pop("const")]
        # Pattern 4: examples (array) is 3.1; 3.0 uses example (singular).
        if "examples" in node and "example" not in node:
            ex = node.get("examples")
            if isinstance(ex, list) and ex:
                node["example"] = ex[0]
            node.pop("examples", None)
        for value in node.values():
            _downgrade_nullable(value)
    elif isinstance(node, list):
        for item in node:
            _downgrade_nullable(item)


def _build_gpt30_subset(full_schema: dict[str, Any]) -> dict[str, Any]:
    """Slim ``full_schema`` to the GPT30_PATHS set and downgrade to 3.0.3."""
    paths_in = full_schema.get("paths", {}) or {}
    slim_paths: dict[str, Any] = {}
    referenced_components: set[str] = set()

    for path in GPT30_PATHS:
        operations = paths_in.get(path)
        if not isinstance(operations, dict):
            continue
        cleaned: dict[str, Any] = {}
        for method, op in operations.items():
            if method.startswith("x-") or method == "parameters":
                cleaned[method] = op
                continue
            if not isinstance(op, dict):
                cleaned[method] = op
                continue
            op = dict(op)
            # Override operationId to a stable camelCase value.
            override = _GPT30_OPERATION_IDS.get((path, method.lower()))
            if override:
                op["operationId"] = override
            else:
                existing = op.get("operationId")
                if isinstance(existing, str):
                    op["operationId"] = _camelize_operation_id(existing)
            cleaned[method] = op
        if cleaned:
            slim_paths[path] = cleaned

    # Collect $ref targets within the slimmed paths so we can prune the
    # components/schemas dict to only those referenced (keeps the file small
    # enough that GPT Actions imports it without choking).
    def _collect_refs(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                referenced_components.add(ref[len("#/components/schemas/") :])
            for v in node.values():
                _collect_refs(v)
        elif isinstance(node, list):
            for item in node:
                _collect_refs(item)

    _collect_refs(slim_paths)

    all_components = (full_schema.get("components") or {}).get("schemas") or {}
    # Closure: schemas reference each other; resolve until fixed-point.
    queue = list(referenced_components)
    while queue:
        name = queue.pop()
        component = all_components.get(name)
        if not isinstance(component, dict):
            continue

        def _collect_inner(node: Any) -> None:
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    child = ref[len("#/components/schemas/") :]
                    if child not in referenced_components:
                        referenced_components.add(child)
                        queue.append(child)
                for v in node.values():
                    _collect_inner(v)
            elif isinstance(node, list):
                for item in node:
                    _collect_inner(item)

        _collect_inner(component)

    slim_components_schemas = {
        name: schema for name, schema in all_components.items() if name in referenced_components
    }

    # Preserve security schemes (X-API-Key header) from the full spec.
    security_schemes = (full_schema.get("components") or {}).get("securitySchemes") or {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    }

    slim_schema: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": _gpt30_info_block(full_schema.get("info") or {}),
        "servers": [{"url": "https://api.jpcite.com", "description": "Production"}],
        "paths": slim_paths,
        "components": {
            "schemas": slim_components_schemas,
            "securitySchemes": security_schemes,
        },
        "x-openai-isConsequential": False,
        "x-jpcite-variant": "gpt30-slim",
        "x-jpcite-source": "public OpenAPI export",
    }

    _downgrade_nullable(slim_schema)
    return slim_schema


def _merge_preserved_policy_blocks(slim: dict[str, Any], preserved: dict[str, Any]) -> None:
    """Carry forward hand-curated narrative blocks from a previously-published
    gpt30 file. We regenerate paths + components from the live FastAPI app, but
    the ``x-jpcite-*`` policy blocks (which live under ``info`` per OAS 3.0
    custom-extension rules) and the rich agent-facing ``info.description`` are
    hand-written and must not be clobbered by regen.
    """
    if not isinstance(preserved, dict):
        return
    preserved_info = preserved.get("info")
    if isinstance(preserved_info, dict):
        # Preserve standard info fields (description, etc.) plus any x-*
        # extensions found nested inside info.
        for key, value in preserved_info.items():
            if key in ("description", "version", "termsOfService", "license"):
                if value is not None:
                    slim["info"][key] = value
            elif key.startswith("x-"):
                slim["info"][key] = value
    # Also carry forward any top-level x-* extensions for safety.
    for key, value in preserved.items():
        if (key.startswith("x-jpcite-") and key not in slim) or key == "x-openai-isConsequential":
            slim[key] = value


def _gpt30_info_block(info: dict[str, Any]) -> dict[str, Any]:
    """Build the info block for the GPT30 slim. Use a short, agent-safe
    description and bump the patch version compared to whatever the full spec
    advertises so consumers can tell the slim apart from a full export.
    """
    base_version = info.get("version") or "0.0.0"
    return {
        "title": "jpcite Agent Slim (GPT Actions 30 paths)",
        "description": (
            "Agent-safe OpenAPI subset for evidence prefetch before answer "
            "generation. jpcite returns source-linked facts, source_url, "
            "fetched timestamps, known gaps, and compatibility rules; it does "
            "not call external LLM APIs and does not generate final "
            "legal/tax advice."
        ),
        "version": base_version,
        "termsOfService": "https://jpcite.com/tos.html",
        "license": {"name": "Proprietary - see termsOfService"},
    }


# -------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-preview",
        action="store_true",
        help="Include preview/roadmap endpoints in the output (default: exclude).",
    )
    parser.add_argument(
        "--profile",
        choices=("full", "gpt30"),
        default="full",
        help=(
            "Output profile. 'full' (default) writes the complete 3.1 schema. "
            "'gpt30' writes a 30-path 3.0.3 slim for GPT Custom Actions."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output path. Default depends on --profile: full writes "
            "docs/openapi/v1.json; gpt30 writes site/openapi.agent.gpt30.json."
        ),
    )
    parser.add_argument(
        "--site-out",
        type=Path,
        default=None,
        help=(
            "Static site mirror path. Only applied for --profile full; "
            "default site/docs/openapi/v1.json."
        ),
    )
    args = parser.parse_args()

    app = _build_app(include_preview=args.include_preview)
    schema = app.openapi()
    _normalize_component_schema_names(schema)
    _sanitize_public_schema(schema)
    # Belt-and-suspenders A3-style leak sanitizer pass. `_sanitize_public_schema`
    # only rewrites strings that are direct dict values; this pass catches any
    # string-typed list entries (enum members, example arrays, preserved policy
    # blocks merged from a previously-published gpt30 file).
    sanitize_openapi_schema_leaks(schema)

    if args.profile == "gpt30":
        slim = _build_gpt30_subset(schema)
        out = args.out or Path("site/openapi.agent.gpt30.json")
        # Preserve hand-curated narrative + x-jpcite-* policy blocks if the
        # target file already exists.
        if out.exists():
            try:
                preserved = json.loads(out.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 -- best-effort merge
                print(f"  warn: could not parse existing {out} for merge: {exc}")
            else:
                _merge_preserved_policy_blocks(slim, preserved)
        # Re-scan the merged slim so any leak patterns in the carried-forward
        # policy blocks are stripped before we render the final file.
        sanitize_openapi_schema_leaks(slim)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(slim, indent=2, sort_keys=True) + "\n"
        assert_no_openapi_leaks(payload, label=str(out))
        out.write_text(payload, encoding="utf-8")
        missing = [p for p in GPT30_PATHS if p not in slim["paths"]]
        print(f"wrote {out} (gpt30-slim), {len(slim['paths'])} paths, openapi={slim['openapi']}")
        if missing:
            print(f"  warn: {len(missing)} requested path(s) absent from source schema:")
            for p in missing:
                print(f"    - {p}")
        return 0

    # --- full profile (default) ---
    out = args.out or Path("docs/openapi/v1.json")
    site_out_explicit = args.site_out is not None
    site_out = args.site_out or Path("site/docs/openapi/v1.json")
    site_openapi_mirror = Path("site/openapi/v1.json")
    should_write_site_openapi_mirror = site_out != site_openapi_mirror and (
        not site_out_explicit or site_out == Path("site/docs/openapi/v1.json")
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    assert_no_openapi_leaks(payload, label=str(out))
    out.write_text(payload, encoding="utf-8")
    if site_out:
        site_out.parent.mkdir(parents=True, exist_ok=True)
        site_out.write_text(payload, encoding="utf-8")
    if should_write_site_openapi_mirror:
        site_openapi_mirror.parent.mkdir(parents=True, exist_ok=True)
        site_openapi_mirror.write_text(payload, encoding="utf-8")

    preview_paths = [
        p
        for p in schema.get("paths", {})
        if p.startswith(("/v1/legal", "/v1/accounting", "/v1/calendar"))
    ]
    mode = "with preview" if args.include_preview else "stable"
    print(
        f"wrote {out} ({mode}), {len(schema.get('paths', {}))} paths ({len(preview_paths)} preview)"
    )
    if site_out:
        print(f"wrote {site_out} ({mode})")
    if should_write_site_openapi_mirror:
        print(f"wrote {site_openapi_mirror} ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
