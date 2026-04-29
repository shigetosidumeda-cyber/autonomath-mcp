from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_path: Path = Field(default=Path("./data/jpintel.db"), alias="JPINTEL_DB_PATH")
    autonomath_path: Path = Field(
        default=Path("/Users/shigetoumeda/Autonomath"), alias="JPINTEL_AUTONOMATH_PATH"
    )
    # autonomath.db (7.3 GB, 402,768 entities + 5.26M facts). Distinct from
    # autonomath_path above (legacy /Users/shigetoumeda/Autonomath project).
    # Dev: ./autonomath.db at repo root. Prod: /data/autonomath.db on Fly volume.
    autonomath_db_path: Path = Field(
        default=Path("./autonomath.db"), alias="AUTONOMATH_DB_PATH"
    )
    # Feature flag gating the 16 am_* MCP tools. Flip False for rollback to
    # 31-tool mode (if autonomath.db becomes unavailable or misbehaves).
    autonomath_enabled: bool = Field(default=True, alias="AUTONOMATH_ENABLED")
    # R9 unified rule_engine_check tool (consolidates 6 rule corpora across
    # 49,247 rows: jpi_exclusion_rules + am_compat_matrix + am_combo_calculator
    # + am_subsidy_rule + am_tax_rule + am_validation_rule). Reads from view
    # `am_unified_rule` (migration 064). Default True. Flip "0"/"false" to
    # disable in case of regression — the legacy `combined_compliance_check`
    # / `check_exclusions` tools remain registered for compatibility.
    rule_engine_enabled: bool = Field(
        default=True, alias="AUTONOMATH_RULE_ENGINE_ENABLED"
    )
    # Feature flag gating the 6 healthcare_* MCP tool stubs (P6-D W4 prep).
    # Default False — keeps the public manifest at 66 tools through the
    # 2026-05-06 launch. Operators flip to True to preview the contract
    # surface ahead of T+90d real-query land. See
    # docs/healthcare_v3_plan.md and src/jpintel_mcp/mcp/healthcare_tools/.
    healthcare_enabled: bool = Field(default=False, alias="AUTONOMATH_HEALTHCARE_ENABLED")
    # Feature flag gating the 5 real_estate_* MCP tool stubs (P6-F W4 prep).
    # Default False — keeps the public manifest at 66 tools through the
    # 2026-05-06 launch. Operators flip to True to preview the contract
    # surface ahead of T+200d (target 2026-11-22) real-query land. Migration
    # 042 (real_estate_programs + zoning_overlays) is already applied so the
    # SQL implementation can land body-only at T+200d. See
    # docs/real_estate_v5_plan.md and src/jpintel_mcp/mcp/real_estate_tools/.
    real_estate_enabled: bool = Field(
        default=False, alias="AUTONOMATH_REAL_ESTATE_ENABLED"
    )
    # Feature flag gating the 36協定 (時間外労働協定届) template renderer pair
    # (`render_36_kyotei_am` + `get_36_kyotei_metadata_am`). 36協定 is a
    # 社労士 (labor & social security attorney) regulated obligation under
    # 労基法 §36 — incorrect generation can expose the operator to 社労士法
    # liability and brand damage. Default False — operator must complete a
    # legal review (社労士 supervision arrangement + customer-facing
    # disclaimer alignment) before flipping to True. Even when enabled, the
    # response carries a draft / 要法務確認 disclaimer (option B). See
    # docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md.
    saburoku_kyotei_enabled: bool = Field(
        default=False,
        alias="AUTONOMATH_36_KYOTEI_ENABLED",
        description="法務 review 完了後に true に設定。デフォルト disabled。",
    )
    # R8 dataset versioning — bitemporal `valid_from` / `valid_until`
    # columns on the 8 core jpintel.db tables + 2 core autonomath.db EAV
    # tables (migration 067). When True, the API search/get endpoints
    # accept an optional `as_of_date` (ISO-8601 YYYY-MM-DD) that pins the
    # result set to the dataset state at that timestamp; the new MCP tool
    # `query_at_snapshot` exposes the same. Default True; flip to "0" /
    # "false" via env to short-circuit the predicate in case of
    # regression. See analysis_wave18/_r8_dataset_versioning_2026-04-25.md
    # and docs/compliance/data_governance.md (法廷証拠 reproducibility).
    r8_versioning_enabled: bool = Field(
        default=True, alias="AUTONOMATH_R8_VERSIONING_ENABLED"
    )
    # Snapshot tool registration gate (`query_at_snapshot`). Migration 067
    # was REFERENCED by snapshot_tool but never actually written — the
    # tool errors with "no such column: valid_from" on every invocation
    # (smoke test 2026-04-29). Default False so the broken tool stays out
    # of `tools/list`. Flip to "1" / "true" once migration 067 lands and
    # adds `valid_from` / `valid_until` to programs / laws / tax_rulesets.
    autonomath_snapshot_enabled: bool = Field(
        default=False, alias="AUTONOMATH_SNAPSHOT_ENABLED"
    )
    # Reasoning subsystem gate (`intent_of` + `reason_answer`). Both tools
    # depend on a `reasoning` package (lazy-imported via _reasoning_import)
    # which is NOT present in the current install — every invocation returns
    # `subsystem_unavailable` (smoke test 2026-04-29). Default False so the
    # broken pair stays out of `tools/list`. Flip to "1" / "true" once the
    # `reasoning` package is bundled into the install (or relocated to a
    # path on sys.path).
    autonomath_reasoning_enabled: bool = Field(
        default=False, alias="AUTONOMATH_REASONING_ENABLED"
    )
    # Graph-walk tool gate (`related_programs`). 2026-04-29 rewritten to
    # read `am_relation` + `am_entities` directly from autonomath.db (same
    # store ``graph_traverse_tool.py`` already uses). The legacy
    # ``am_node`` / graph.sqlite path is gone. Default flipped to True so
    # the tool is registered out of the box; the env var is retained as a
    # one-flag rollback in case a regression surfaces. Distinct from
    # `graph_traverse` (which has its own AUTONOMATH_GRAPH_TRAVERSE_ENABLED
    # gate and walks v_am_relation_all multi-kind).
    autonomath_graph_enabled: bool = Field(
        default=True, alias="AUTONOMATH_GRAPH_ENABLED"
    )
    # R5 prerequisite_chain — surfaces the multi-step certification / 計画
    # / agency-relation prerequisites that gate a target program. Reads
    # from `am_prerequisite_bundle` (795 rows / 135 programs / 1.6%
    # coverage of the 8,203-program corpus). The 1.6% number is honestly
    # surfaced in `data_quality.coverage_pct` so callers see the partial
    # recall transparently — silent miss is fraud-risk under the
    # 景表法 / 消費者契約法 fence (see feedback_no_fake_data /
    # feedback_autonomath_fraud_risk). Default True; flip "0" / "false"
    # via env to short-circuit if a regression surfaces. See
    # analysis_wave18/_r5_prerequisite_chain_2026-04-25.md.
    prerequisite_chain_enabled: bool = Field(
        default=True, alias="AUTONOMATH_PREREQUISITE_CHAIN_ENABLED"
    )
    # Migration 103: NTA primary-source corpus tools (find_saiketsu /
    # cite_tsutatsu / find_shitsugi / find_bunsho_kaitou) reading from
    # nta_saiketsu / nta_tsutatsu_index / nta_shitsugi / nta_bunsho_kaitou.
    # Sources: 国税不服審判所 (kfs.go.jp) + 国税庁 (nta.go.jp). All rows are
    # PUBLIC government documents under government-standard 利用規約 (PDL
    # v1.0 / ministry standard). Every result envelope carries a 税理士法
    # §52 _disclaimer declaring the output citation-only retrieval.
    # Default True; flip to "0" / "false" via env for one-flag rollback.
    autonomath_nta_corpus_enabled: bool = Field(
        default=True, alias="AUTONOMATH_NTA_CORPUS_ENABLED"
    )
    # Wave 22 composition tools (5 MCP surfaces): match_due_diligence_questions /
    # prepare_kessan_briefing / forecast_program_renewal / cross_check_jurisdiction /
    # bundle_application_kit. Pure SQLite + Python, NO LLM, every response carries
    # `_next_calls` + `corpus_snapshot_id` + `corpus_checksum`; the §52 / §72 / §1
    # surfaces also emit a `_disclaimer`. Default True. Flip to "0" / "false" via env
    # for a one-flag rollback (the tool module reads via os.environ.get for fast
    # short-circuit at import time — this Settings field mirrors the value for
    # discoverability / typed-access in code paths that already hold a Settings).
    autonomath_wave22_enabled: bool = Field(
        default=True, alias="AUTONOMATH_WAVE22_ENABLED"
    )
    # Wave 23 industry pack wrappers (3 MCP surfaces): pack_construction (JSIC D) /
    # pack_manufacturing (JSIC E) / pack_real_estate (JSIC K). Bundle programs +
    # nta_saiketsu citations + 通達 references in 1 req. NO LLM, single ¥3/req.
    # Sensitive (§52 / §47条の2): every response carries `_disclaimer` + `_next_calls`.
    # Default True. Same rollback semantics as wave22 above.
    autonomath_industry_packs_enabled: bool = Field(
        default=True, alias="AUTONOMATH_INDUSTRY_PACKS_ENABLED"
    )
    # Prompt-injection guard layered on top of INV-22 (景表法) sanitizer.
    # Strips override directives ("ignore previous instructions",
    # `<|im_start|>`, "DAN mode", etc.) from every JSON str leaf on the
    # REST middleware path AND the MCP envelope path. Default True; flip
    # to False for a no-touch rollback if a false positive surfaces in
    # production (override goes to "0" / "false" via env). See
    # `src/jpintel_mcp/security/prompt_injection_sanitizer.py`.
    prompt_injection_guard_enabled: bool = Field(
        default=True, alias="AUTONOMATH_PROMPT_INJECTION_GUARD"
    )
    # Hallucination_guard layer (Loop A surface-form detection) layered on
    # top of INV-22 + prompt-injection. Substring-scans every JSON str leaf
    # against the 60-phrase YAML at `data/hallucination_guard.yaml` and
    # appends `loop_a-{severity}` to the `_sanitize_hits` envelope so
    # operators can grep production logs for repeat false-claim attempts.
    # Non-rewriting: corrections are operator-reviewed, never auto-emitted.
    # Default True; flip to "0" / "false" via env for one-flag rollback.
    # See `src/jpintel_mcp/self_improve/loop_a_hallucination_guard.py`.
    hallucination_guard_enabled: bool = Field(
        default=True, alias="AUTONOMATH_HALLUCINATION_GUARD_ENABLED"
    )
    # PII response-body redactor (S7 critical fix). Layer 0 of the response
    # sanitizer cascade — runs BEFORE INV-22 / prompt-injection / loop_a so
    # downstream layers never see raw 13桁法人番号 / personal email / 電話
    # numbers in JSON str leaves. Closes INV-21 redact_pii() telemetry-only
    # gap that left ~5,904 corp.representative + 121k location strings APPI
    # exposed. Default True; flip to "0" via env for one-flag rollback. See
    # `src/jpintel_mcp/security/pii_redact.py`.
    pii_redact_response_enabled: bool = Field(
        default=True, alias="AUTONOMATH_PII_REDACT_RESPONSE_ENABLED"
    )
    # O8 per-fact Bayesian uncertainty (additive `_uncertainty` envelope on
    # fact-returning responses + `/v1/stats/data_quality` rollup). Wired
    # through `envelope_wrapper.build_envelope` (default-injected machine
    # readable confidence band) and `api.stats`. Default True so launch
    # surfaces transparency; flip to "0" via env for one-flag rollback if
    # the per-fact join becomes a hot spot. See
    # `src/jpintel_mcp/api/uncertainty.py` and migration
    # `069_uncertainty_view.sql`.
    uncertainty_enabled: bool = Field(
        default=True, alias="AUTONOMATH_UNCERTAINTY_ENABLED"
    )
    # S7 disclaimer envelope level (see envelope_wrapper.SENSITIVE_TOOLS).
    # Sensitive tools (dd_profile_am / regulatory_prep_pack /
    # combined_compliance_check / rule_engine_check / predict_subsidy_outcome /
    # score_dd_risk) emit a `_disclaimer` string on every response. Three
    # levels:
    #   "strict"   — long form (standard text + 業法 boundary + AI 生成 warning)
    #   "standard" — single paragraph, default; mirrors S7 spec verbatim
    #   "minimal"  — single short line for token-sensitive surfaces
    # Default "standard". Override via env to tighten or loosen at runtime.
    autonomath_disclaimer_level: str = Field(
        default="standard", alias="AUTONOMATH_DISCLAIMER_LEVEL"
    )
    # Personal information sub-flags (APPI § 31 / § 33 fence). Default 0=off:
    # `corp.representative` (代表者名) is gbiz info公開情報 source, so removing
    # it would break legitimate due-diligence queries — but the field is also
    # the one APPI 個人情報 directly attaches to. We gate it pending legal
    # opinion (社労士 / 弁護士 review). Flip to "1" once legal review confirms
    # redaction (or removes that requirement). 郵便番号 (postal_code) is also
    # 公開情報 in gbiz → default 0=preserve. Personal email / 電話 stay redacted
    # (default behaviour; not gated — those are unambiguous APPI risk).
    pii_redact_representative: bool = Field(
        default=False, alias="AUTONOMATH_PII_REDACT_REPRESENTATIVE"
    )
    pii_redact_postal_code: bool = Field(
        default=False, alias="AUTONOMATH_PII_REDACT_POSTAL_CODE"
    )
    # 法人番号 (13桁) は 国税庁 法人番号公表サイト + gbiz PDL v1.0 で 公開情報。
    # gbiz / 法人番号 lookup を 1st-class surface に持つ check_enforcement_am /
    # search_corp 等は queried.houjin_bangou を verbatim echo する必要があり、
    # 過剰 mask は accuracy / DD UX を毀損する (`feedback_no_fake_data`)。
    # default=False で preserve、 True で T*************マスク (legacy 挙動)。
    pii_redact_houjin_bangou: bool = Field(
        default=False, alias="AUTONOMATH_PII_REDACT_HOUJIN_BANGOU"
    )
    log_level: str = Field(default="INFO", alias="JPINTEL_LOG_LEVEL")
    # CORS_ORIGINS whitelist (Wave 16 P1). Comma-separated origins. The
    # OriginEnforcementMiddleware short-circuits any cross-origin request
    # whose `Origin` header is set and not on the list with 403 (covers
    # both regular and OPTIONS preflight). Same-origin requests (no
    # `Origin` header) and server-to-server callers (curl, Stripe webhook)
    # are unaffected. Default whitelists production marketing surfaces +
    # API host. Apex AND www MUST both be listed — the homepage prescreen,
    # saved searches, customer webhooks dashboard, and audit log all run
    # browser-side fetch() against api.zeimu-kaikei.ai and inherit the
    # rendering origin (apex or www depending on canonical redirect).
    # Local dev callers must override JPINTEL_CORS_ORIGINS explicitly
    # (e.g. `JPINTEL_CORS_ORIGINS="http://localhost:3000,http://localhost:8080"`).
    cors_origins: str = Field(
        default=(
            "https://zeimu-kaikei.ai,"
            "https://www.zeimu-kaikei.ai,"
            "https://api.zeimu-kaikei.ai,"
            "https://autonomath.ai,"
            "https://www.autonomath.ai"
        ),
        alias="JPINTEL_CORS_ORIGINS",
    )

    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    # Pure metered billing: one Price (¥3/req 外税, 税込 ¥3.30),
    # lookup_key=per_request_v3. Revised 2026-04-23 from ¥0.5 → ¥1 on same day
    # (see memory project_autonomath_business_model.md).
    # Pinned to Stripe-Version 2024-11-20.acacia — legacy metered (usage_records)
    # cannot be created under 2025-03-31.basil+ without a Meter object, which
    # requires rak_billing_meter_write permission we do not currently hold.
    stripe_price_per_request: str = Field(default="", alias="STRIPE_PRICE_PER_REQUEST")
    stripe_api_version: str = Field(default="2024-11-20.acacia", alias="STRIPE_API_VERSION")

    # JCT / インボイス制度 (see research/stripe_jct_setup.md)
    stripe_tax_enabled: bool = Field(default=False, alias="STRIPE_TAX_ENABLED")
    invoice_registration_number: str = Field(default="", alias="INVOICE_REGISTRATION_NUMBER")
    invoice_footer_ja: str = Field(default="", alias="INVOICE_FOOTER_JA")
    stripe_billing_portal_config_id: str = Field(
        default="", alias="STRIPE_BILLING_PORTAL_CONFIG_ID"
    )

    api_key_salt: str = Field(default="dev-salt", alias="API_KEY_SALT")
    # HMAC secret for the audit_seal envelope (税理士事務所 bundle, 2026-04-29).
    # Distinct from api_key_salt on purpose: a leaked api_key_salt only
    # affects key-lookup integrity, but the audit_seal is the customer-facing
    # tamper-evident receipt embedded in every metered response — rotating
    # the audit-seal secret invalidates every previously issued seal, so it
    # must be kept stable across deploys for the 7-year tax-record retention
    # window. Default 'dev-audit-seal-salt' is sentinel-only; production sets
    # AUDIT_SEAL_SECRET on Fly via `fly secrets set`.
    audit_seal_secret: str = Field(
        default="dev-audit-seal-salt", alias="AUDIT_SEAL_SECRET"
    )
    # Hard daily cap for authenticated keys whose `tier="free"`. This is the
    # dunning-demote state (a paid customer whose card is failing) — NOT the
    # public Free tier, which is anonymous and governed by anon_rate_limit
    # below. Kept daily because the dunning window is short (days, not weeks).
    rate_limit_free_per_day: int = Field(default=100, alias="RATE_LIMIT_FREE_PER_DAY")

    # Per-IP MONTHLY quota for anonymous (no X-API-Key) callers. Lives in
    # table `anon_rate_limit` (migration 007; `date` column stores the
    # first-of-month JST, YYYY-MM-01, as the bucket key). Resets on JST
    # calendar month boundary. Revised 2026-04-23 from daily 100 → monthly
    # 50 to align Free tier with "sample, not product" positioning.
    # Authenticated calls bypass — their tier quota still applies via
    # deps._enforce_quota().
    anon_rate_limit_per_month: int = Field(default=50, alias="ANON_RATE_LIMIT_PER_MONTH")
    anon_rate_limit_enabled: bool = Field(default=True, alias="ANON_RATE_LIMIT_ENABLED")

    # Admin (internal) endpoints under /v1/admin/*. Empty → endpoints return
    # 503 "admin endpoints disabled" (safer default than trusting an
    # uninitialised value). Kept out-of-band from customer API keys on
    # purpose — never reuse a customer key here.
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")

    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_environment: str = Field(default="dev", alias="SENTRY_ENVIRONMENT")
    # 0.1 = 10% trace sampling. At launch volumes (≤1k req/day) this keeps
    # Sentry inside the free tier; revisit when traffic crosses ~5k req/day
    # (see docs/observability.md "Cost monitoring").
    sentry_traces_sample_rate: float = Field(default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE")
    sentry_profiles_sample_rate: float = Field(default=0.1, alias="SENTRY_PROFILES_SAMPLE_RATE")
    sentry_release: str = Field(default="", alias="SENTRY_RELEASE")

    log_format: str = Field(default="json", alias="JPINTEL_LOG_FORMAT")
    ingest_staleness_threshold_days: int = Field(default=30, alias="JPINTEL_INGEST_STALENESS_DAYS")

    # Environment label used by the email / Postmark plumbing to short-circuit
    # sends in CI / pytest. Distinct from `sentry_environment` on purpose:
    # Sentry can be off even in prod (no DSN configured), but email test-mode
    # must be explicit. Values: "dev" | "test" | "staging" | "prod".
    env: str = Field(default="dev", alias="JPINTEL_ENV")

    # --- Postmark (transactional email) -------------------------------------
    # Token unset OR env=="test" → the email layer no-ops and logs the
    # would-send. See `src/jpintel_mcp/email/postmark.py` and
    # `docs/email_setup.md`.
    postmark_api_token: str = Field(default="", alias="POSTMARK_API_TOKEN")
    postmark_webhook_secret: str = Field(default="", alias="POSTMARK_WEBHOOK_SECRET")
    # `transactional` is the From: we actually send from
    # (no-reply@[DOMAIN]). `reply` is the Reply-To we set so humans answering
    # hit a monitored mailbox (hello@[DOMAIN]).
    postmark_from_transactional: str = Field(
        default="noreply@zeimu-kaikei.ai", alias="POSTMARK_FROM_TRANSACTIONAL"
    )
    postmark_from_reply: str = Field(
        default="info@bookyou.net", alias="POSTMARK_FROM_REPLY"
    )

    # Preview/roadmap endpoints (legal / accounting / calendar). Default False
    # so the stable OpenAPI export (docs/openapi/v1.json) does NOT advertise
    # unimplemented routes. Flip to True in an env where we want partners to
    # see the contract early — mounted routes return HTTP 501 with a roadmap
    # body, never real data. See `docs/preview_endpoints.md`.
    enable_preview_endpoints: bool = Field(default=False, alias="JPINTEL_ENABLE_PREVIEW_ENDPOINTS")

    @property
    def autonomath_registry(self) -> Path:
        return self.autonomath_path / "data" / "unified_registry.json"

    @property
    def autonomath_enriched_dir(self) -> Path:
        return (
            self.autonomath_path / "backend" / "knowledge_base" / "data" / "canonical" / "enriched"
        )

    @property
    def autonomath_exclusion_rules(self) -> Path:
        return (
            self.autonomath_path
            / "backend"
            / "knowledge_base"
            / "data"
            / "agri"
            / "exclusion_rules.json"
        )


settings = Settings()
