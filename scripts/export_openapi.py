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
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sanitize_public_schema(node: Any) -> None:
    if isinstance(node, dict):
        tags = node.get("tags")
        if isinstance(tags, list):
            node["tags"] = [
                {
                    "autonomath": "jpcite",
                    "autonomath-health": "jpcite-health",
                }.get(item, item)
                for item in tags
            ]
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
            if isinstance(value, str):
                node[key] = _sanitize_public_text(value)
            else:
                _sanitize_public_schema(value)
    elif isinstance(node, list):
        for item in node:
            _sanitize_public_schema(item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-preview",
        action="store_true",
        help="Include preview/roadmap endpoints in the output (default: exclude).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/openapi/v1.json"),
        help="Output path (default: docs/openapi/v1.json).",
    )
    parser.add_argument(
        "--site-out",
        type=Path,
        default=Path("site/docs/openapi/v1.json"),
        help="Static site mirror path (default: site/docs/openapi/v1.json).",
    )
    args = parser.parse_args()

    app = _build_app(include_preview=args.include_preview)
    schema = app.openapi()
    _normalize_component_schema_names(schema)
    _sanitize_public_schema(schema)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.site_out:
        args.site_out.parent.mkdir(parents=True, exist_ok=True)
        args.site_out.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    preview_paths = [
        p
        for p in schema.get("paths", {})
        if p.startswith(("/v1/legal", "/v1/accounting", "/v1/calendar"))
    ]
    mode = "with preview" if args.include_preview else "stable"
    print(
        f"wrote {args.out} ({mode}), "
        f"{len(schema.get('paths', {}))} paths "
        f"({len(preview_paths)} preview)"
    )
    if args.site_out:
        print(f"wrote {args.site_out} ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
