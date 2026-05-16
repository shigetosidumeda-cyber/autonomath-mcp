"""Schema-level profiles for tenant-supplied accounting CSV enrichment.

The profiles in this module are compatibility hints for private CSV overlays.
They are not certified import/export specifications for any vendor product,
and they never make public-source claims from tenant CSV content.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SCHEMA_VERSION = "jpcite.accounting_csv_profiles.p0.v1"
CERTIFICATION_NOTICE = (
    "Schema-level compatibility profile only; no official certification, "
    "endorsement, or vendor import guarantee is asserted."
)
ALLOWED_PRIVATE_OUTPUTS = (
    "tenant_private_fact_capsule",
    "tenant_private_enrichment_summary",
    "redacted_internal_gap_report",
    "tenant_private_program_match_prefill",
)
BLOCKED_PUBLIC_OUTPUTS = (
    "public_packet_claim",
    "public_source_receipt",
    "absence_or_completeness_claim",
    "certified_accounting_import_file",
    "row_level_export_without_consent",
)
GROUNDING_RULES = (
    "emit_only_observed_normalized_fields",
    "mark_missing_fields_as_limitations",
    "do_not_infer_full_period_coverage",
    "do_not_infer_account_categories",
    "do_not_create_public_source_receipts_from_private_csv",
)

ProviderFamily = Literal["freee", "money_forward", "yayoi", "tkc", "unknown"]
DetectionConfidence = Literal["none", "low", "medium", "high"]
PeriodCoverageMode = Literal["unknown", "observed_row_date_range", "explicit_period_columns"]
AccountCategoryMode = Literal["explicit_category_field", "account_label_only", "unknown"]
FieldValueKind = Literal[
    "date",
    "identifier",
    "amount",
    "account_label",
    "account_category",
    "tax_code",
    "tax_amount",
    "text",
    "dimension",
]
LimitationSeverity = Literal["warning", "blocking"]


@dataclass(frozen=True)
class DetectionSignal:
    """Column-level evidence used for conservative profile detection."""

    signal_key: str
    description: str
    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    required: bool = False

    def matches(self, normalized_headers: frozenset[str]) -> bool:
        if self.all_of and not all(
            _normalize_header(header) in normalized_headers for header in self.all_of
        ):
            return False
        if self.any_of and not any(
            _normalize_header(header) in normalized_headers for header in self.any_of
        ):
            return False
        return bool(self.all_of or self.any_of)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedField:
    """Canonical field that may be populated from one or more CSV columns."""

    field_key: str
    aliases: tuple[str, ...]
    value_kind: FieldValueKind
    required_for_minimal_enrichment: bool
    limitation_if_missing: str

    def is_present(self, normalized_headers: frozenset[str]) -> bool:
        return any(_normalize_header(alias) in normalized_headers for alias in self.aliases)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PeriodCoveragePolicy:
    """How period coverage may be stated without overclaiming completeness."""

    date_field_keys: tuple[str, ...]
    explicit_period_start_aliases: tuple[str, ...] = (
        "期間開始",
        "対象期間開始",
        "開始日",
    )
    explicit_period_end_aliases: tuple[str, ...] = (
        "期間終了",
        "対象期間終了",
        "終了日",
    )
    header_only_limitation: str = (
        "Headers alone can identify date columns, but cannot prove full fiscal "
        "or monthly period coverage."
    )
    row_range_limitation: str = (
        "Observed row date min/max are coverage evidence for supplied rows only; "
        "they are not a completeness claim."
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountCategoryPolicy:
    """Rules for account categories and labels."""

    category_field_key: str = "account_category"
    account_label_field_keys: tuple[str, ...] = (
        "account",
        "debit_account",
        "credit_account",
    )
    derived_category_allowed: bool = False
    missing_category_limitation: str = (
        "Account category remains unknown unless the CSV supplies an explicit "
        "category/classification column."
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountingCsvProfile:
    """Static profile definition for a family of accounting CSV shapes."""

    profile_key: str
    provider_family: ProviderFamily
    display_name: str
    profile_scope: str
    detection_signals: tuple[DetectionSignal, ...]
    minimum_matched_signals: int
    normalized_fields: tuple[NormalizedField, ...]
    period_coverage_policy: PeriodCoveragePolicy
    account_category_policy: AccountCategoryPolicy
    allowed_downstream_outputs: tuple[str, ...] = ALLOWED_PRIVATE_OUTPUTS
    blocked_downstream_outputs: tuple[str, ...] = BLOCKED_PUBLIC_OUTPUTS
    grounding_rules: tuple[str, ...] = GROUNDING_RULES
    official_certification_claimed: bool = False
    certification_notice: str = CERTIFICATION_NOTICE

    def __post_init__(self) -> None:
        if self.official_certification_claimed:
            raise ValueError("accounting CSV profiles cannot claim official certification")
        if any(output.startswith("public_") for output in self.allowed_downstream_outputs):
            raise ValueError("private CSV profile cannot allow public downstream outputs")

    def field(self, field_key: str) -> NormalizedField | None:
        for normalized_field in self.normalized_fields:
            if normalized_field.field_key == field_key:
                return normalized_field
        return None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MissingFieldLimitation:
    """A missing normalized field and the downstream limitation it creates."""

    field_key: str
    severity: LimitationSeverity
    limitation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountCategoryCoverage:
    """Evidence state for account category handling."""

    mode: AccountCategoryMode
    category_field_key: str | None
    derived_category_allowed: bool
    limitation: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountingCsvDetection:
    """Result of conservative header-only profile detection."""

    provider_family: ProviderFamily
    profile_key: str | None
    confidence: DetectionConfidence
    matched_signals: tuple[str, ...]
    missing_required_signals: tuple[str, ...]
    candidate_profile_keys: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountingCsvHeaderEvaluation:
    """Observed and missing normalized fields for a chosen profile."""

    profile_key: str
    provider_family: ProviderFamily
    observed_normalized_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...]
    missing_optional_fields: tuple[str, ...]
    missing_field_limitations: tuple[MissingFieldLimitation, ...]
    account_category_coverage: AccountCategoryCoverage
    allowed_downstream_outputs: tuple[str, ...]
    blocked_downstream_outputs: tuple[str, ...]
    official_certification_claimed: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["missing_field_limitations"] = [
            limitation.to_dict() for limitation in self.missing_field_limitations
        ]
        data["account_category_coverage"] = self.account_category_coverage.to_dict()
        return data


@dataclass(frozen=True)
class PeriodCoverageSummary:
    """Period coverage that can be evidenced from supplied inline rows."""

    mode: PeriodCoverageMode
    period_start: str | None
    period_end: str | None
    evidence_fields: tuple[str, ...]
    limitation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AccountingCsvDownstreamContract:
    """Evidence-grounded outputs allowed for a private CSV overlay."""

    profile_key: str
    provider_family: ProviderFamily
    observed_normalized_fields: tuple[str, ...]
    missing_field_limitations: tuple[MissingFieldLimitation, ...]
    allowed_downstream_outputs: tuple[str, ...]
    blocked_downstream_outputs: tuple[str, ...]
    grounding_rules: tuple[str, ...]
    public_claim_support: bool = False
    source_receipt_compatible: bool = False
    row_level_export_allowed_without_consent: bool = False
    official_certification_claimed: bool = False

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["missing_field_limitations"] = [
            limitation.to_dict() for limitation in self.missing_field_limitations
        ]
        return data


def build_accounting_csv_profiles() -> tuple[AccountingCsvProfile, ...]:
    """Return deterministic accounting CSV profile definitions."""

    return _PROFILES


def build_accounting_csv_profile_catalog_shape() -> dict[str, object]:
    """Return a JSON-ready profile catalog shape for release artifacts/tests."""

    return {
        "schema_version": SCHEMA_VERSION,
        "certification_notice": CERTIFICATION_NOTICE,
        "allowed_downstream_outputs": ALLOWED_PRIVATE_OUTPUTS,
        "blocked_downstream_outputs": BLOCKED_PUBLIC_OUTPUTS,
        "grounding_rules": GROUNDING_RULES,
        "profiles": [profile.to_dict() for profile in _PROFILES],
    }


def get_accounting_csv_profile(profile_key: str) -> AccountingCsvProfile:
    """Return one profile by key."""

    for profile in _PROFILES:
        if profile.profile_key == profile_key:
            return profile
    raise KeyError(f"unknown accounting CSV profile: {profile_key}")


def detect_accounting_csv_profile(headers: Iterable[str]) -> AccountingCsvDetection:
    """Detect a profile from headers, failing closed for generic or ambiguous shapes."""

    normalized_headers = _normalized_header_set(headers)
    candidates: list[tuple[AccountingCsvProfile, tuple[str, ...], tuple[str, ...]]] = []
    partial_candidates: list[str] = []

    for profile in _PROFILES:
        matched_signals = tuple(
            signal.signal_key
            for signal in profile.detection_signals
            if signal.matches(normalized_headers)
        )
        missing_required = tuple(
            signal.signal_key
            for signal in profile.detection_signals
            if signal.required and not signal.matches(normalized_headers)
        )
        if matched_signals:
            partial_candidates.append(profile.profile_key)
        if not missing_required and len(matched_signals) >= profile.minimum_matched_signals:
            candidates.append((profile, matched_signals, missing_required))

    if len(candidates) == 1:
        profile, matched_signals, missing_required = candidates[0]
        confidence: DetectionConfidence = (
            "high" if len(matched_signals) > profile.minimum_matched_signals else "medium"
        )
        return AccountingCsvDetection(
            provider_family=profile.provider_family,
            profile_key=profile.profile_key,
            confidence=confidence,
            matched_signals=matched_signals,
            missing_required_signals=missing_required,
            candidate_profile_keys=(profile.profile_key,),
            reason="Exactly one profile matched all required provider-specific signals.",
        )

    if len(candidates) > 1:
        candidate_profile_keys = tuple(profile.profile_key for profile, _, _ in candidates)
        return AccountingCsvDetection(
            provider_family="unknown",
            profile_key=None,
            confidence="low",
            matched_signals=(),
            missing_required_signals=(),
            candidate_profile_keys=candidate_profile_keys,
            reason="Multiple profiles matched; refusing to guess a provider family.",
        )

    return AccountingCsvDetection(
        provider_family="unknown",
        profile_key=None,
        confidence="none",
        matched_signals=(),
        missing_required_signals=(),
        candidate_profile_keys=tuple(partial_candidates),
        reason="No profile matched all required provider-specific detection signals.",
    )


def evaluate_accounting_csv_headers(
    profile_key: str,
    headers: Iterable[str],
) -> AccountingCsvHeaderEvaluation:
    """Evaluate observed and missing normalized fields for a chosen profile."""

    profile = get_accounting_csv_profile(profile_key)
    normalized_headers = _normalized_header_set(headers)
    observed_fields = tuple(
        field.field_key
        for field in profile.normalized_fields
        if field.is_present(normalized_headers)
    )
    missing_required_fields = tuple(
        field.field_key
        for field in profile.normalized_fields
        if field.required_for_minimal_enrichment and not field.is_present(normalized_headers)
    )
    missing_optional_fields = tuple(
        field.field_key
        for field in profile.normalized_fields
        if not field.required_for_minimal_enrichment and not field.is_present(normalized_headers)
    )
    missing_field_limitations = tuple(
        MissingFieldLimitation(
            field_key=field.field_key,
            severity="blocking" if field.required_for_minimal_enrichment else "warning",
            limitation=field.limitation_if_missing,
        )
        for field in profile.normalized_fields
        if not field.is_present(normalized_headers)
    )

    return AccountingCsvHeaderEvaluation(
        profile_key=profile.profile_key,
        provider_family=profile.provider_family,
        observed_normalized_fields=observed_fields,
        missing_required_fields=missing_required_fields,
        missing_optional_fields=missing_optional_fields,
        missing_field_limitations=missing_field_limitations,
        account_category_coverage=_account_category_coverage(profile, observed_fields),
        allowed_downstream_outputs=profile.allowed_downstream_outputs,
        blocked_downstream_outputs=profile.blocked_downstream_outputs,
        official_certification_claimed=profile.official_certification_claimed,
    )


def summarize_period_coverage(
    profile_key: str,
    rows: Iterable[Mapping[str, object]],
) -> PeriodCoverageSummary:
    """Summarize period coverage from supplied row dictionaries only."""

    profile = get_accounting_csv_profile(profile_key)
    policy = profile.period_coverage_policy
    date_fields = tuple(
        field for field in profile.normalized_fields if field.field_key in policy.date_field_keys
    )
    row_dates: list[dt.date] = []
    explicit_starts: list[dt.date] = []
    explicit_ends: list[dt.date] = []

    for row in rows:
        normalized_row = {_normalize_header(key): value for key, value in row.items()}
        explicit_starts.extend(
            cast("dt.date", _parse_date(normalized_row.get(_normalize_header(alias))))
            for alias in policy.explicit_period_start_aliases
            if _parse_date(normalized_row.get(_normalize_header(alias))) is not None
        )
        explicit_ends.extend(
            cast("dt.date", _parse_date(normalized_row.get(_normalize_header(alias))))
            for alias in policy.explicit_period_end_aliases
            if _parse_date(normalized_row.get(_normalize_header(alias))) is not None
        )

        for field in date_fields:
            for alias in field.aliases:
                parsed = _parse_date(normalized_row.get(_normalize_header(alias)))
                if parsed is not None:
                    row_dates.append(parsed)
                    break

    if explicit_starts and explicit_ends:
        return PeriodCoverageSummary(
            mode="explicit_period_columns",
            period_start=min(explicit_starts).isoformat(),
            period_end=max(explicit_ends).isoformat(),
            evidence_fields=("period_start", "period_end"),
            limitation=policy.row_range_limitation,
        )

    if row_dates:
        return PeriodCoverageSummary(
            mode="observed_row_date_range",
            period_start=min(row_dates).isoformat(),
            period_end=max(row_dates).isoformat(),
            evidence_fields=policy.date_field_keys,
            limitation=policy.row_range_limitation,
        )

    return PeriodCoverageSummary(
        mode="unknown",
        period_start=None,
        period_end=None,
        evidence_fields=(),
        limitation=policy.header_only_limitation,
    )


def build_downstream_output_contract(
    profile_key: str,
    headers: Iterable[str],
) -> AccountingCsvDownstreamContract:
    """Return the allowed private outputs for observed CSV columns."""

    profile = get_accounting_csv_profile(profile_key)
    evaluation = evaluate_accounting_csv_headers(profile_key, headers)
    return AccountingCsvDownstreamContract(
        profile_key=profile.profile_key,
        provider_family=profile.provider_family,
        observed_normalized_fields=evaluation.observed_normalized_fields,
        missing_field_limitations=evaluation.missing_field_limitations,
        allowed_downstream_outputs=profile.allowed_downstream_outputs,
        blocked_downstream_outputs=profile.blocked_downstream_outputs,
        grounding_rules=profile.grounding_rules,
        official_certification_claimed=profile.official_certification_claimed,
    )


def _account_category_coverage(
    profile: AccountingCsvProfile,
    observed_fields: tuple[str, ...],
) -> AccountCategoryCoverage:
    policy = profile.account_category_policy
    if policy.category_field_key in observed_fields:
        return AccountCategoryCoverage(
            mode="explicit_category_field",
            category_field_key=policy.category_field_key,
            derived_category_allowed=policy.derived_category_allowed,
            limitation=None,
        )
    if any(field_key in observed_fields for field_key in policy.account_label_field_keys):
        return AccountCategoryCoverage(
            mode="account_label_only",
            category_field_key=None,
            derived_category_allowed=policy.derived_category_allowed,
            limitation=policy.missing_category_limitation,
        )
    return AccountCategoryCoverage(
        mode="unknown",
        category_field_key=None,
        derived_category_allowed=policy.derived_category_allowed,
        limitation="No account label or category field is available.",
    )


def _normalized_header_set(headers: Iterable[str]) -> frozenset[str]:
    return frozenset(_normalize_header(header) for header in headers)


def _normalize_header(header: object) -> str:
    text = unicodedata.normalize("NFKC", str(header)).strip().lower()
    return "".join(text.split())


def _parse_date(value: object | None) -> dt.date | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    parts = normalized.split()
    candidate = parts[0] if parts else normalized
    try:
        return dt.date.fromisoformat(candidate)
    except ValueError:
        return None


def _field(
    field_key: str,
    aliases: tuple[str, ...],
    value_kind: FieldValueKind,
    *,
    required: bool,
    limitation: str,
) -> NormalizedField:
    return NormalizedField(
        field_key=field_key,
        aliases=aliases,
        value_kind=value_kind,
        required_for_minimal_enrichment=required,
        limitation_if_missing=limitation,
    )


COMMON_ACCOUNT_CATEGORY_FIELD = _field(
    "account_category",
    ("勘定科目分類", "科目区分", "決算書科目", "account_category"),
    "account_category",
    required=False,
    limitation=(
        "Account category cannot be populated or inferred; downstream outputs must "
        "use account labels only."
    ),
)

_FREEE_TRANSACTION_FIELDS = (
    _field(
        "transaction_date",
        ("発生日",),
        "date",
        required=True,
        limitation="Transaction date is unavailable, so period coverage cannot be observed.",
    ),
    _field(
        "entry_id",
        ("管理番号", "取引ID", "取引番号"),
        "identifier",
        required=False,
        limitation="Stable row identity is unavailable; deduplication must remain best effort.",
    ),
    _field(
        "account",
        ("勘定科目",),
        "account_label",
        required=True,
        limitation="Account label is unavailable, so account-based enrichment is blocked.",
    ),
    COMMON_ACCOUNT_CATEGORY_FIELD,
    _field(
        "amount",
        ("金額",),
        "amount",
        required=True,
        limitation="Amount is unavailable, so financial magnitude cannot be summarized.",
    ),
    _field(
        "tax_code",
        ("税区分",),
        "tax_code",
        required=False,
        limitation="Tax code is unavailable; tax treatment must not be inferred.",
    ),
    _field(
        "tax_amount",
        ("税額",),
        "tax_amount",
        required=False,
        limitation="Tax amount is unavailable; gross/net/tax splits must not be inferred.",
    ),
    _field(
        "counterparty",
        ("取引先",),
        "text",
        required=False,
        limitation="Counterparty is unavailable; vendor/customer enrichment must be omitted.",
    ),
    _field(
        "department",
        ("部門",),
        "dimension",
        required=False,
        limitation="Department is unavailable; department-level summaries must be omitted.",
    ),
    _field(
        "item",
        ("品目",),
        "dimension",
        required=False,
        limitation="Item/project dimension is unavailable; item-level summaries must be omitted.",
    ),
    _field(
        "description",
        ("備考", "メモタグ", "摘要"),
        "text",
        required=False,
        limitation="Description is unavailable; narrative enrichment must stay blank.",
    ),
)

_TKC_JOURNAL_FIELDS = (
    _field(
        "transaction_date",
        ("伝票日付", "取引日", "取引日付", "日付"),
        "date",
        required=True,
        limitation="Transaction date is unavailable, so period coverage cannot be observed.",
    ),
    _field(
        "entry_id",
        ("仕訳No", "仕訳番号", "伝票番号", "伝票No"),
        "identifier",
        required=False,
        limitation="Stable journal identity is unavailable; deduplication must remain best effort.",
    ),
    _field(
        "debit_account",
        ("借方科目", "借方勘定科目", "借方科目コード"),
        "account_label",
        required=True,
        limitation="Debit account is unavailable, so double-entry enrichment is blocked.",
    ),
    _field(
        "credit_account",
        ("貸方科目", "貸方勘定科目", "貸方科目コード"),
        "account_label",
        required=True,
        limitation="Credit account is unavailable, so double-entry enrichment is blocked.",
    ),
    COMMON_ACCOUNT_CATEGORY_FIELD,
    _field(
        "debit_amount",
        ("借方金額",),
        "amount",
        required=True,
        limitation="Debit amount is unavailable, so balanced journal summaries are blocked.",
    ),
    _field(
        "credit_amount",
        ("貸方金額",),
        "amount",
        required=True,
        limitation="Credit amount is unavailable, so balanced journal summaries are blocked.",
    ),
    _field(
        "tax_code",
        ("借方消費税区分", "貸方消費税区分", "消費税区分", "税区分"),
        "tax_code",
        required=False,
        limitation="Tax code is unavailable; tax treatment must not be inferred.",
    ),
    _field(
        "tax_amount",
        ("借方消費税額", "貸方消費税額", "消費税額", "税額"),
        "tax_amount",
        required=False,
        limitation="Tax amount is unavailable; gross/net/tax splits must not be inferred.",
    ),
    _field(
        "department",
        ("部門", "部門コード", "借方部門", "貸方部門"),
        "dimension",
        required=False,
        limitation="Department is unavailable; department-level summaries must be omitted.",
    ),
    _field(
        "fiscal_year",
        ("会計年度", "会計期間", "事業年度"),
        "dimension",
        required=False,
        limitation="Fiscal year is unavailable; period-anchored summaries must be omitted.",
    ),
    _field(
        "description",
        ("摘要", "摘要文", "メモ", "備考"),
        "text",
        required=False,
        limitation="Description is unavailable; narrative enrichment must stay blank.",
    ),
)

_DOUBLE_ENTRY_FIELDS = (
    _field(
        "transaction_date",
        ("取引日", "取引日付", "発生日", "日付"),
        "date",
        required=True,
        limitation="Transaction date is unavailable, so period coverage cannot be observed.",
    ),
    _field(
        "entry_id",
        ("取引No", "伝票No.", "伝票No", "伝票番号", "仕訳番号", "管理番号", "取引番号"),
        "identifier",
        required=False,
        limitation="Stable journal identity is unavailable; deduplication must remain best effort.",
    ),
    _field(
        "debit_account",
        ("借方勘定科目",),
        "account_label",
        required=True,
        limitation="Debit account is unavailable, so double-entry enrichment is blocked.",
    ),
    _field(
        "credit_account",
        ("貸方勘定科目",),
        "account_label",
        required=True,
        limitation="Credit account is unavailable, so double-entry enrichment is blocked.",
    ),
    COMMON_ACCOUNT_CATEGORY_FIELD,
    _field(
        "debit_amount",
        ("借方金額", "借方金額(円)"),
        "amount",
        required=True,
        limitation="Debit amount is unavailable, so balanced journal summaries are blocked.",
    ),
    _field(
        "credit_amount",
        ("貸方金額", "貸方金額(円)"),
        "amount",
        required=True,
        limitation="Credit amount is unavailable, so balanced journal summaries are blocked.",
    ),
    _field(
        "tax_code",
        ("借方税区分", "貸方税区分", "税区分"),
        "tax_code",
        required=False,
        limitation="Tax code is unavailable; tax treatment must not be inferred.",
    ),
    _field(
        "tax_amount",
        ("借方税額", "貸方税額", "税額"),
        "tax_amount",
        required=False,
        limitation="Tax amount is unavailable; gross/net/tax splits must not be inferred.",
    ),
    _field(
        "department",
        ("借方部門", "貸方部門", "部門"),
        "dimension",
        required=False,
        limitation="Department is unavailable; department-level summaries must be omitted.",
    ),
    _field(
        "item",
        ("借方品目", "貸方品目", "品目"),
        "dimension",
        required=False,
        limitation="Item/project dimension is unavailable; item-level summaries must be omitted.",
    ),
    _field(
        "counterparty",
        ("取引先", "相手先", "借方取引先", "貸方取引先"),
        "text",
        required=False,
        limitation="Counterparty is unavailable; vendor/customer enrichment must be omitted.",
    ),
    _field(
        "description",
        ("摘要", "仕訳メモ", "メモタグ", "備考"),
        "text",
        required=False,
        limitation="Description is unavailable; narrative enrichment must stay blank.",
    ),
)

_PROFILES = (
    AccountingCsvProfile(
        profile_key="freee_transaction_rows",
        provider_family="freee",
        display_name="freee-compatible transaction layout",
        profile_scope=(
            "Schema-level private-overlay profile for freee-compatible transaction/detail layouts; "
            "not an official freee specification."
        ),
        detection_signals=(
            DetectionSignal(
                "freee_transaction_date",
                "freee-compatible layouts commonly use 発生日 for the transaction date.",
                any_of=("発生日",),
                required=True,
            ),
            DetectionSignal(
                "freee_provider_hint",
                "Provider-specific shape hints avoid classifying generic ledgers as freee.",
                any_of=("管理番号", "メモタグ", "決済期日", "収支区分", "セグメント1"),
                required=True,
            ),
            DetectionSignal(
                "freee_single_amount_shape",
                "Single-entry/detail shape has account plus amount columns.",
                all_of=("勘定科目", "金額"),
                required=True,
            ),
            DetectionSignal(
                "freee_tax_detail",
                "Tax-detail columns strengthen the match.",
                any_of=("税区分", "税額"),
            ),
            DetectionSignal(
                "freee_dimension_detail",
                "Dimension columns strengthen the match.",
                any_of=("取引先", "品目", "部門"),
            ),
        ),
        minimum_matched_signals=4,
        normalized_fields=_FREEE_TRANSACTION_FIELDS,
        period_coverage_policy=PeriodCoveragePolicy(date_field_keys=("transaction_date",)),
        account_category_policy=AccountCategoryPolicy(),
    ),
    AccountingCsvProfile(
        profile_key="freee_journal_rows",
        provider_family="freee",
        display_name="freee-compatible journal layout",
        profile_scope=(
            "Schema-level private-overlay profile for freee-compatible debit/credit journal layouts; "
            "not an official freee specification."
        ),
        detection_signals=(
            DetectionSignal(
                "freee_journal_date",
                "freee-compatible journal layouts may use 発生日 or 取引日 for journal dates.",
                any_of=("発生日", "取引日"),
                required=True,
            ),
            DetectionSignal(
                "freee_journal_provider_hint",
                "Provider-specific shape hints avoid classifying generic journals as freee.",
                any_of=(
                    "管理番号",
                    "メモタグ",
                    "借方メモタグ",
                    "貸方メモタグ",
                    "freee取引ID",
                    "セグメント1",
                    "借方品目",
                    "貸方品目",
                    "伝票番号",
                ),
                required=True,
            ),
            DetectionSignal(
                "double_entry_accounts",
                "Debit and credit account columns are present.",
                all_of=("借方勘定科目", "貸方勘定科目"),
                required=True,
            ),
            DetectionSignal(
                "double_entry_amounts",
                "Debit and credit amount columns are present.",
                all_of=("借方金額", "貸方金額"),
                required=True,
            ),
            DetectionSignal(
                "journal_tax_detail",
                "Debit/credit tax columns strengthen the match.",
                any_of=("借方税区分", "貸方税区分"),
            ),
        ),
        minimum_matched_signals=4,
        normalized_fields=_DOUBLE_ENTRY_FIELDS,
        period_coverage_policy=PeriodCoveragePolicy(date_field_keys=("transaction_date",)),
        account_category_policy=AccountCategoryPolicy(),
    ),
    AccountingCsvProfile(
        profile_key="money_forward_journal_rows",
        provider_family="money_forward",
        display_name="Money Forward-compatible journal layout",
        profile_scope=(
            "Schema-level private-overlay profile for Money Forward-compatible debit/credit "
            "journal layouts; not an official Money Forward specification."
        ),
        detection_signals=(
            DetectionSignal(
                "money_forward_date",
                "Money Forward-compatible journal layouts commonly use 取引日.",
                any_of=("取引日",),
                required=True,
            ),
            DetectionSignal(
                "money_forward_provider_hint",
                "MF-specific columns are required before assigning this profile.",
                any_of=("MF仕訳タイプ", "MF仕訳ID", "マネーフォワード仕訳ID"),
                required=True,
            ),
            DetectionSignal(
                "money_forward_transaction_number",
                "Transaction number is a common journal export identifier.",
                any_of=("取引No", "取引番号"),
                required=True,
            ),
            DetectionSignal(
                "money_forward_accounts",
                "Debit and credit account columns are present.",
                all_of=("借方勘定科目", "貸方勘定科目"),
                required=True,
            ),
            DetectionSignal(
                "money_forward_yen_amounts",
                "Yen-denominated debit and credit amount columns are present.",
                all_of=("借方金額(円)", "貸方金額(円)"),
                required=True,
            ),
            DetectionSignal(
                "money_forward_tax_detail",
                "Debit/credit tax columns strengthen the match.",
                any_of=("借方税区分", "貸方税区分"),
            ),
        ),
        minimum_matched_signals=5,
        normalized_fields=_DOUBLE_ENTRY_FIELDS,
        period_coverage_policy=PeriodCoveragePolicy(date_field_keys=("transaction_date",)),
        account_category_policy=AccountCategoryPolicy(),
    ),
    AccountingCsvProfile(
        profile_key="yayoi_journal_rows",
        provider_family="yayoi",
        display_name="Yayoi-compatible journal layout",
        profile_scope=(
            "Schema-level private-overlay profile for Yayoi-compatible journal layouts; "
            "not an official Yayoi specification."
        ),
        detection_signals=(
            DetectionSignal(
                "yayoi_identification_flag",
                "Yayoi-compatible layouts commonly include an import identification flag.",
                all_of=("識別フラグ",),
                required=True,
            ),
            DetectionSignal(
                "yayoi_voucher_number",
                "Yayoi-compatible layouts commonly include a voucher number column.",
                any_of=("伝票No.", "伝票No"),
                required=True,
            ),
            DetectionSignal(
                "yayoi_date",
                "Yayoi-compatible journal layouts commonly use 取引日付.",
                any_of=("取引日付",),
                required=True,
            ),
            DetectionSignal(
                "yayoi_accounts",
                "Debit and credit account columns are present.",
                all_of=("借方勘定科目", "貸方勘定科目"),
                required=True,
            ),
            DetectionSignal(
                "yayoi_amounts",
                "Debit and credit amount columns are present.",
                all_of=("借方金額", "貸方金額"),
                required=True,
            ),
            DetectionSignal(
                "yayoi_tax_detail",
                "Debit/credit tax columns strengthen the match.",
                any_of=("借方税区分", "貸方税区分"),
            ),
            DetectionSignal(
                "yayoi_memo_columns",
                "Memo/control columns strengthen the match.",
                any_of=("付箋1", "付箋2", "調整"),
            ),
        ),
        minimum_matched_signals=5,
        normalized_fields=_DOUBLE_ENTRY_FIELDS,
        period_coverage_policy=PeriodCoveragePolicy(date_field_keys=("transaction_date",)),
        account_category_policy=AccountCategoryPolicy(),
    ),
    AccountingCsvProfile(
        profile_key="tkc_general_journal_layout_v1",
        provider_family="tkc",
        display_name="TKC FX-compatible general journal layout",
        profile_scope=(
            "Schema-level private-overlay profile for TKC FX-series general-journal layouts; "
            "not an official TKC specification and not a TKC certified import format."
        ),
        detection_signals=(
            DetectionSignal(
                "tkc_voucher_date",
                "TKC FX general-journal layouts commonly use 伝票日付 for the journal date.",
                any_of=("伝票日付",),
                required=True,
            ),
            DetectionSignal(
                "tkc_entry_number",
                "TKC FX layouts commonly include a 仕訳No / 伝票番号 entry identifier.",
                any_of=("仕訳No", "仕訳番号", "伝票番号", "伝票No"),
                required=True,
            ),
            DetectionSignal(
                "tkc_double_entry_accounts",
                "TKC FX layouts use 借方科目 / 貸方科目 debit/credit account columns.",
                all_of=("借方科目", "貸方科目"),
                required=True,
            ),
            DetectionSignal(
                "tkc_double_entry_amounts",
                "TKC FX layouts use 借方金額 / 貸方金額 debit/credit amount columns.",
                all_of=("借方金額", "貸方金額"),
                required=True,
            ),
            DetectionSignal(
                "tkc_description",
                "TKC FX layouts include 摘要 as the narrative column.",
                any_of=("摘要", "摘要文"),
                required=True,
            ),
            DetectionSignal(
                "tkc_consumption_tax_detail",
                "TKC FX 消費税 columns strengthen the match.",
                any_of=("借方消費税区分", "貸方消費税区分", "借方消費税額", "貸方消費税額"),
            ),
            DetectionSignal(
                "tkc_fiscal_dimension",
                "TKC FX 部門 / 会計年度 dimension columns strengthen the match.",
                any_of=("部門", "部門コード", "会計年度", "会計期間"),
            ),
        ),
        minimum_matched_signals=5,
        normalized_fields=_TKC_JOURNAL_FIELDS,
        period_coverage_policy=PeriodCoveragePolicy(date_field_keys=("transaction_date",)),
        account_category_policy=AccountCategoryPolicy(),
    ),
)
