"""Wave 51 L1 source family catalog — static registry (no I/O, no LLM).

This module is the canonical Python representation of the 32 public-program
source families listed in ``docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md``.
It exposes a Pydantic model (:class:`SourceFamily`) plus an immutable
``SOURCE_FAMILY_REGISTRY`` keyed by ``family_id``.

Design constraints (enforced):

- **Static only**: instantiation happens at import time from a literal table;
  no network, no DB, no filesystem read.
- **Pydantic for validation**: ``family_id`` uniqueness, segmented_dimension
  pairing, and enum-style fields are validated structurally.
- **No LLM imports**: see :mod:`jpintel_mcp.l1_source_family` docstring.

The registry is consumed by Wave 51 L1 ETL stubs (``scripts/etl/ingest_*.py``)
and by ``outcome_source_crosswalk_v2.json`` builders, but those are
out-of-scope for this module — this file *only* declares the catalog.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from collections.abc import Mapping

CATALOG_VERSION = "jpcite.l1_source_family.wave51.v1"

# 6 axes from WAVE51_L1_SOURCE_FAMILY_CATALOG.md § 1.

Ministry = Literal[
    "e_gov",
    "nta",
    "meti",
    "fsa",
    "digital_agency",
    "moj",
    "mlit",
    "mhlw",
    "maff",
    "env",
    "soumu",
    "mof",
    "mext",
    "jfc",
    "smrj",
    "pmda",
    "courts",
    "multi_ministry",
    "kanpou",
    "pref_47_wrapper",
    "muni_800_wrapper",
    "jetro",
    "jisc",
    "jpo",
    "njss_plus_local",
]

Category = Literal[
    "laws_regulations",
    "invoice_registrants",
    "corp_master",
    "disclosure",
    "subsidy_portal",
    "corporate_registry",
    "subsidy_general",
    "construction_permit",
    "labor_health",
    "subsidy_agriculture",
    "environment_regulation",
    "local_government",
    "tax_budget_customs",
    "research_grant",
    "invoice_extended",
    "amendment_diff",
    "public_finance",
    "smb_support",
    "medical_regulation",
    "judicial",
    "enforcement_actions",
    "official_gazette",
    "corporate_deep",
    "local_subsidy",
    "trade_invest",
    "standards",
    "patent_trademark",
    "climate",
    "statistics",
    "bids",
    "tax_personal",
]

LicenseTag = Literal[
    "cc_by_4_0",
    "ogl_2_0",
    "ogl_2_0_pdl_v1_0",
    "tos_only",
    "per_municipality",
    "restricted",
]

AccessMode = Literal[
    "api",
    "api_plus_bulk",
    "api_plus_pdf",
    "api_plus_website",
    "bulk_csv",
    "bulk_excel",
    "bulk_xbrl",
    "bulk_plus_website",
    "website",
    "website_plus_api",
    "website_plus_bulk",
    "website_plus_pdf",
    "website_plus_playwright",
    "private_api",
]

RefreshFrequency = Literal[
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "private",
]

Priority = Literal[
    "P0",
    "P1",
    "P2",
    "P2_restricted",
]


class SourceFamily(BaseModel):
    """One row in the L1 source family catalog.

    Each row describes a public-program data source family with its
    ministry, category, license posture, access mode, refresh frequency,
    and priority tier. The model is frozen (immutable) to keep the
    registry safe to share across threads / async tasks without copying.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    family_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]+$")
    ministry: Ministry
    category: Category
    license_tag: LicenseTag
    access_mode: AccessMode
    refresh_frequency: RefreshFrequency
    priority: Priority
    is_segmented: bool = False
    segment_dimension: Literal["prefecture_code", "municipality_code"] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_segmented_pairing(self) -> SourceFamily:
        """Ensure segment_dimension is set iff is_segmented is True."""
        if self.is_segmented and self.segment_dimension is None:
            raise ValueError(
                f"family_id={self.family_id!r}: is_segmented=True requires "
                "segment_dimension to be set"
            )
        if not self.is_segmented and self.segment_dimension is not None:
            raise ValueError(
                f"family_id={self.family_id!r}: segment_dimension must be None "
                "when is_segmented=False"
            )
        return self

    @model_validator(mode="after")
    def _validate_restricted_priority(self) -> SourceFamily:
        """P2_restricted families must declare `restricted` license."""
        if self.priority == "P2_restricted" and self.license_tag != "restricted":
            raise ValueError(
                f"family_id={self.family_id!r}: priority=P2_restricted requires "
                "license_tag=restricted"
            )
        if self.priority != "P2_restricted" and self.license_tag == "restricted":
            raise ValueError(
                f"family_id={self.family_id!r}: license_tag=restricted requires "
                "priority=P2_restricted"
            )
        return self


# ---------------------------------------------------------------------------
# Catalog rows — must match docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md.
# 32 families total: P0=6, P1=17, P2=8, P2_restricted=1.
# ---------------------------------------------------------------------------

_RAW_CATALOG: tuple[SourceFamily, ...] = (
    # --- P0 (6) ---
    SourceFamily(
        family_id="egov_laws_regulations",
        ministry="e_gov",
        category="laws_regulations",
        license_tag="cc_by_4_0",
        access_mode="api",
        refresh_frequency="daily",
        priority="P0",
        notes="e-Gov 法令本文 SoT, AX Trustability core",
    ),
    SourceFamily(
        family_id="nta_invoice_publication",
        ministry="nta",
        category="invoice_registrants",
        license_tag="ogl_2_0_pdl_v1_0",
        access_mode="bulk_csv",
        refresh_frequency="monthly",
        priority="P0",
        notes="PDL v1.0 で API 再配信可、agent justifiability core",
    ),
    SourceFamily(
        family_id="gbizinfo_houjin",
        ministry="meti",
        category="corp_master",
        license_tag="cc_by_4_0",
        access_mode="api",
        refresh_frequency="daily",
        priority="P0",
        notes="gBizINFO 法人 master, houjin_bangou ↔ 制度 join 起点",
    ),
    SourceFamily(
        family_id="edinet_disclosure",
        ministry="fsa",
        category="disclosure",
        license_tag="tos_only",
        access_mode="bulk_xbrl",
        refresh_frequency="quarterly",
        priority="P0",
        notes="上場・大企業 cohort の disclosure 軸",
    ),
    SourceFamily(
        family_id="jgrants_subsidy_portal",
        ministry="digital_agency",
        category="subsidy_portal",
        license_tag="cc_by_4_0",
        access_mode="api_plus_bulk",
        refresh_frequency="daily",
        priority="P0",
        notes="jGrants — 補助金 portal canonical surface",
    ),
    SourceFamily(
        family_id="sangyo_houjin_registry",
        ministry="moj",
        category="corporate_registry",
        license_tag="tos_only",
        access_mode="bulk_plus_website",
        refresh_frequency="weekly",
        priority="P0",
        notes="法人登記 bulk, houjin_bangou SoT 法務省側 bind",
    ),
    # --- P1 (17) ---
    SourceFamily(
        family_id="meti_subsidies",
        ministry="meti",
        category="subsidy_general",
        license_tag="ogl_2_0",
        access_mode="website",
        refresh_frequency="weekly",
        priority="P1",
        notes="経産省 補助金 (一般・経営支援)",
    ),
    SourceFamily(
        family_id="mlit_permits",
        ministry="mlit",
        category="construction_permit",
        license_tag="tos_only",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P1",
        notes="建設業許可・宅建業",
    ),
    SourceFamily(
        family_id="mhlw_labor",
        ministry="mhlw",
        category="labor_health",
        license_tag="ogl_2_0",
        access_mode="website_plus_pdf",
        refresh_frequency="monthly",
        priority="P1",
        notes="厚労省 労働基準・労災・社保",
    ),
    SourceFamily(
        family_id="maff_grants_extended",
        ministry="maff",
        category="subsidy_agriculture",
        license_tag="ogl_2_0",
        access_mode="bulk_excel",
        refresh_frequency="quarterly",
        priority="P1",
        notes="農水省 農業補助金 (交付決定)",
    ),
    SourceFamily(
        family_id="env_regulations",
        ministry="env",
        category="environment_regulation",
        license_tag="ogl_2_0",
        access_mode="api",
        refresh_frequency="weekly",
        priority="P1",
        notes="環境省 環境規制・廃棄物・CO2",
    ),
    SourceFamily(
        family_id="soumu_local_gov",
        ministry="soumu",
        category="local_government",
        license_tag="tos_only",
        access_mode="website",
        refresh_frequency="quarterly",
        priority="P1",
        notes="総務省 自治体財政・地方税",
    ),
    SourceFamily(
        family_id="mof_subsidies",
        ministry="mof",
        category="tax_budget_customs",
        license_tag="ogl_2_0",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P1",
        notes="財務省 税制・予算・関税",
    ),
    SourceFamily(
        family_id="mext_research",
        ministry="mext",
        category="research_grant",
        license_tag="ogl_2_0",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P1",
        notes="文科省 研究助成・科研費",
    ),
    SourceFamily(
        family_id="nta_invoice_extended",
        ministry="nta",
        category="invoice_extended",
        license_tag="ogl_2_0_pdl_v1_0",
        access_mode="bulk_csv",
        refresh_frequency="monthly",
        priority="P1",
        notes="NTA invoice 拡張 (zenken bulk)",
    ),
    SourceFamily(
        family_id="egov_amendment_diff",
        ministry="e_gov",
        category="amendment_diff",
        license_tag="cc_by_4_0",
        access_mode="api",
        refresh_frequency="daily",
        priority="P1",
        notes="e-Gov 法令改正 diff",
    ),
    SourceFamily(
        family_id="jfc_loans",
        ministry="jfc",
        category="public_finance",
        license_tag="tos_only",
        access_mode="website_plus_playwright",
        refresh_frequency="weekly",
        priority="P1",
        notes="日本政策金融公庫 融資制度",
    ),
    SourceFamily(
        family_id="smrj_business",
        ministry="smrj",
        category="smb_support",
        license_tag="ogl_2_0",
        access_mode="api_plus_website",
        refresh_frequency="monthly",
        priority="P1",
        notes="中小機構 中小企業支援",
    ),
    SourceFamily(
        family_id="unic_pmda",
        ministry="pmda",
        category="medical_regulation",
        license_tag="tos_only",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P1",
        notes="PMDA 医療規制・GMP",
    ),
    SourceFamily(
        family_id="court_decisions",
        ministry="courts",
        category="judicial",
        license_tag="tos_only",
        access_mode="website_plus_bulk",
        refresh_frequency="monthly",
        priority="P1",
        notes="裁判所 判例・裁判例",
    ),
    SourceFamily(
        family_id="enforcement_actions",
        ministry="multi_ministry",
        category="enforcement_actions",
        license_tag="tos_only",
        access_mode="website",
        refresh_frequency="weekly",
        priority="P1",
        notes="各省庁 行政処分公表",
    ),
    SourceFamily(
        family_id="gazette_official",
        ministry="kanpou",
        category="official_gazette",
        license_tag="tos_only",
        access_mode="bulk_plus_website",
        refresh_frequency="daily",
        priority="P1",
        notes="官報 公示・公告",
    ),
    SourceFamily(
        family_id="gbizinfo_houjin_extended",
        ministry="meti",
        category="corporate_deep",
        license_tag="cc_by_4_0",
        access_mode="api",
        refresh_frequency="daily",
        priority="P1",
        notes="gBizINFO 法人 deep (届出・許認可)",
    ),
    # --- P2 (8) ---
    SourceFamily(
        family_id="pref_47_municipal",
        ministry="pref_47_wrapper",
        category="local_subsidy",
        license_tag="per_municipality",
        access_mode="website_plus_api",
        refresh_frequency="weekly",
        priority="P2",
        is_segmented=True,
        segment_dimension="prefecture_code",
        notes="47 都道府県 wrapper, family_subkey で展開",
    ),
    SourceFamily(
        family_id="muni_800_segments",
        ministry="muni_800_wrapper",
        category="local_subsidy",
        license_tag="per_municipality",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P2",
        is_segmented=True,
        segment_dimension="municipality_code",
        notes="800 主要市町村 wrapper",
    ),
    SourceFamily(
        family_id="jetro_invest",
        ministry="jetro",
        category="trade_invest",
        license_tag="ogl_2_0",
        access_mode="website",
        refresh_frequency="monthly",
        priority="P2",
        notes="JETRO 外国投資・海外展開",
    ),
    SourceFamily(
        family_id="jisc_standards",
        ministry="jisc",
        category="standards",
        license_tag="tos_only",
        access_mode="api_plus_pdf",
        refresh_frequency="quarterly",
        priority="P2",
        notes="JISC JIS 規格・認証",
    ),
    SourceFamily(
        family_id="tokkyo_jpo",
        ministry="jpo",
        category="patent_trademark",
        license_tag="tos_only",
        access_mode="api",
        refresh_frequency="weekly",
        priority="P2",
        notes="特許庁 特許・商標公報",
    ),
    SourceFamily(
        family_id="mafg_climate",
        ministry="env",
        category="climate",
        license_tag="ogl_2_0",
        access_mode="api",
        refresh_frequency="weekly",
        priority="P2",
        notes="環境省 気候変動枠 気候統計・GHG 排出",
    ),
    SourceFamily(
        family_id="estat_statistics",
        ministry="soumu",
        category="statistics",
        license_tag="ogl_2_0",
        access_mode="api",
        refresh_frequency="weekly",
        priority="P2",
        notes="e-Stat 政府統計",
    ),
    SourceFamily(
        family_id="njss_bids_aggregated",
        ministry="njss_plus_local",
        category="bids",
        license_tag="tos_only",
        access_mode="website_plus_api",
        refresh_frequency="weekly",
        priority="P2",
        notes="NJSS + 各自治体 入札公示 (中央+地方)",
    ),
    # --- P2_restricted (1) ---
    SourceFamily(
        family_id="nta_pdb_personal",
        ministry="nta",
        category="tax_personal",
        license_tag="restricted",
        access_mode="private_api",
        refresh_frequency="private",
        priority="P2_restricted",
        notes="個人税務 (取扱注意), cross product 420 entry の対象外",
    ),
)


def _build_registry(rows: tuple[SourceFamily, ...]) -> Mapping[str, SourceFamily]:
    """Build the immutable registry dict, asserting family_id uniqueness."""
    seen: dict[str, SourceFamily] = {}
    for row in rows:
        if row.family_id in seen:
            raise ValueError(
                f"duplicate family_id={row.family_id!r} in L1 source family catalog"
            )
        seen[row.family_id] = row
    return MappingProxyType(seen)


SOURCE_FAMILY_REGISTRY: Mapping[str, SourceFamily] = _build_registry(_RAW_CATALOG)
"""Immutable registry of all 32 Wave 51 L1 source families, keyed by family_id."""


def list_source_families() -> tuple[SourceFamily, ...]:
    """Return all registered source families in catalog declaration order."""
    return _RAW_CATALOG


def list_source_families_by_priority(priority: Priority) -> tuple[SourceFamily, ...]:
    """Return all source families with the given priority tier."""
    return tuple(row for row in _RAW_CATALOG if row.priority == priority)


def get_source_family(family_id: str) -> SourceFamily:
    """Look up a source family by id. Raises KeyError if not registered."""
    try:
        return SOURCE_FAMILY_REGISTRY[family_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown L1 source family_id={family_id!r}; "
            f"see docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md"
        ) from exc
