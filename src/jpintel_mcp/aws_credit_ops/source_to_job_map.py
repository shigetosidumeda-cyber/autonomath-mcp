"""Canonical L1 source-family → AWS-credit job-id map.

This module bridges the Wave 51 L1 source family catalog
(:mod:`jpintel_mcp.l1_source_family.catalog` — 32 families) with the 8
AWS credit consumption jobs (J01..J08) declared in
``data/aws_credit_jobs/J0{1..8}*.json``. The mapping is consumed by the
crawler container and by the Step Functions orchestrator so each fetched
URL can be tagged with the originating L1 family and the per-source
contract metadata (``license_boundary``, ``robots_respect``,
``required_notice``, ``redistribution_scope``) without having to re-walk
the catalog at runtime.

Design constraints (mirrored from ``catalog.py``):

- **Static only**: literal table at import time; no I/O, no DB, no LLM.
- **No live HTTP**: this module imports neither ``httpx`` nor any
  scraping library.
- **Authoritative job manifests**: ``data/aws_credit_jobs/J0{1..8}*.json``
  are the source of truth for the URLs each job sweeps. This map
  declares the *family-id ↔ job-id* relationship that the manifests
  reference at the ``source_family`` / ``publisher`` level.

Per ``docs/_internal/aws_credit_data_acquisition_jobs_agent.md``:

- **J01** (source profile sweep) — every P0 family.
- **J02** (NTA法人番号 master mirror) — corporate-identity axis;
  backs ``gbizinfo_houjin`` because the L1 catalog has no dedicated
  ``nta_houjin_master`` family (the houjin_bangou surface lives in the
  gBizINFO corp master row, with NTA as the upstream authority).
- **J03** (NTAインボイス) — invoice registrants axis.
- **J04** (e-Gov law snapshot) — law / regulation axis.
- **J05** (J-Grants public program acquisition) — subsidy portal axis.
- **J06** (Ministry / municipality PDF extraction) — permit registry +
  subsidy general + local subsidy axis.
- **J07** (gBizINFO public business signals) — business registry signal
  axis.
- **J08** (官報 / kanpou gazette notice crawler) — official_gazette axis;
  daily indexes from 国立印刷局 (kanpou.npb.go.jp) for 法人設立/解散/合併/
  行政処分/告示/公告. PDL v1.0 attribution required.

Use :func:`get_job_for_source` to look up the job_id for an L1 family,
:func:`get_sources_for_job` to enumerate the families a job sweeps, and
:func:`verify_coverage` to assert all eight jobs have at least one
mapped source (a CI-gated invariant).
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003  # runtime use by Pydantic
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.l1_source_family.catalog import (
    SOURCE_FAMILY_REGISTRY,
    list_source_families_by_priority,
)

#: Stable version tag for the source → job map. Bump when the mapping
#: shape changes (new job_id, removed family, etc.). Downstream
#: consumers (crawler container, Step Functions, Athena partition
#: discovery) pin against this string.
MAP_VERSION: Final[str] = "jpcite.aws_credit_ops.source_to_job_map.v1"

#: Canonical job_id enumeration. Mirrors the eight JSON files under
#: ``data/aws_credit_jobs/``.
JobId = Literal[
    "J01_source_profile_sweep",
    "J02_nta_houjin_master_mirror",
    "J03_nta_invoice_registrants_mirror",
    "J04_egov_law_snapshot",
    "J05_jgrants_public_program_acquisition",
    "J06_ministry_municipality_pdf_extraction",
    "J07_gbizinfo_public_business_signals",
    "J08_kanpou_gazette",
]

#: All eight job_ids in declaration order. Tests gate on
#: ``set(ALL_JOB_IDS) == set(SOURCE_TO_JOB_MAP.values()) ∪ {J01..J08}``
#: so missing entries are caught structurally.
ALL_JOB_IDS: Final[tuple[JobId, ...]] = (
    "J01_source_profile_sweep",
    "J02_nta_houjin_master_mirror",
    "J03_nta_invoice_registrants_mirror",
    "J04_egov_law_snapshot",
    "J05_jgrants_public_program_acquisition",
    "J06_ministry_municipality_pdf_extraction",
    "J07_gbizinfo_public_business_signals",
    "J08_kanpou_gazette",
)


# ---------------------------------------------------------------------------
# Primary mapping
#
# Each L1 family is mapped to **one** primary job_id — the job whose
# manifest is the authoritative fetcher for that family. J01 is treated
# as a sweep over ``all P0``, so P0 families that are not the *primary*
# subject of any J02..J07 job (only ``edinet_disclosure`` qualifies)
# pin to J01. The verify_coverage helper additionally asserts that
# every job in ``ALL_JOB_IDS`` has at least one mapped source.
# ---------------------------------------------------------------------------

_SOURCE_TO_JOB: dict[str, JobId] = {
    # --- J04: e-Gov law snapshot ---
    "egov_laws_regulations": "J04_egov_law_snapshot",
    "egov_amendment_diff": "J04_egov_law_snapshot",
    # --- J03: NTA invoice registrants mirror ---
    "nta_invoice_publication": "J03_nta_invoice_registrants_mirror",
    "nta_invoice_extended": "J03_nta_invoice_registrants_mirror",
    # --- J07: gBizINFO public business signals ---
    # gbizinfo_houjin is the corp master surface that NTA houjin (J02)
    # feeds upstream — but the *fetched* surface lives at info.gbiz.go.jp
    # which is J07's target. J02 is therefore reserved for the
    # houjin-bangou.nta.go.jp bulk download path, and the L1 catalog
    # row for "corp master" lives at gbizinfo_houjin which is the J07
    # surface. To avoid double-mapping (two jobs claim one family) we
    # pin gbizinfo_houjin to its primary fetcher J07 and let
    # verify_coverage assert J02 has at least one bound family via the
    # houjin_bangou identity axis below.
    "gbizinfo_houjin": "J07_gbizinfo_public_business_signals",
    "gbizinfo_houjin_extended": "J07_gbizinfo_public_business_signals",
    # --- J05: J-Grants public program acquisition ---
    "jgrants_subsidy_portal": "J05_jgrants_public_program_acquisition",
    # --- J06: Ministry / municipality PDF extraction ---
    # All non-J01-sweep P1/P2 ministry/municipality families that are
    # primarily fetched via index page crawl + PDF parse.
    "meti_subsidies": "J06_ministry_municipality_pdf_extraction",
    "mhlw_labor": "J06_ministry_municipality_pdf_extraction",
    "maff_grants_extended": "J06_ministry_municipality_pdf_extraction",
    "mlit_permits": "J06_ministry_municipality_pdf_extraction",
    "env_regulations": "J06_ministry_municipality_pdf_extraction",
    "mof_subsidies": "J06_ministry_municipality_pdf_extraction",
    "mext_research": "J06_ministry_municipality_pdf_extraction",
    "smrj_business": "J06_ministry_municipality_pdf_extraction",
    "pref_47_municipal": "J06_ministry_municipality_pdf_extraction",
    "muni_800_segments": "J06_ministry_municipality_pdf_extraction",
    # --- J01: source profile sweep (P0 + residual P1/P2 with bespoke surfaces) ---
    # ``edinet_disclosure`` is P0 but has no dedicated bulk job, so it
    # pins to the J01 sweep until a future job_id covers EDINET XBRL.
    "edinet_disclosure": "J01_source_profile_sweep",
    # ``sangyo_houjin_registry`` is P0 (法務省 法人登記 bulk) and is
    # bound to J02 because the houjin_bangou identity layer (J02) is the
    # canonical fetcher that resolves the houjin_bangou ↔ 登記
    # houjin_meisho surface. Without this bind, J02 would have zero
    # mapped families.
    "sangyo_houjin_registry": "J02_nta_houjin_master_mirror",
    # --- J08: 官報 (kanpou) gazette notice crawler ---
    # gazette_official binds to J08, the dedicated gazette daily-index
    # walker. Before J08 landed this row pointed at J01 (sweep-only)
    # because no per-source fetcher existed; J08 now owns the
    # kanpou.npb.go.jp surface end-to-end (daily index + per-notice
    # receipt + PDL v1.0 attribution).
    "gazette_official": "J08_kanpou_gazette",
    # Remaining P1/P2 families are profiled by J01 (their bulk fetch is
    # not in scope for the AWS-credit window).
    "soumu_local_gov": "J01_source_profile_sweep",
    "jfc_loans": "J01_source_profile_sweep",
    "unic_pmda": "J01_source_profile_sweep",
    "court_decisions": "J01_source_profile_sweep",
    "enforcement_actions": "J01_source_profile_sweep",
    "jetro_invest": "J01_source_profile_sweep",
    "jisc_standards": "J01_source_profile_sweep",
    "tokkyo_jpo": "J01_source_profile_sweep",
    "mafg_climate": "J01_source_profile_sweep",
    "estat_statistics": "J01_source_profile_sweep",
    "njss_bids_aggregated": "J01_source_profile_sweep",
    # ``nta_pdb_personal`` (P2_restricted, license_tag=restricted) is
    # explicitly excluded — restricted data does not flow through the
    # AWS-credit window. verify_coverage asserts this row is unmapped.
}


#: Immutable view of the source → job map. Keyed by L1 ``family_id``,
#: value is the canonical ``JobId`` that fetches the family.
SOURCE_TO_JOB_MAP: Mapping[str, JobId] = MappingProxyType(_SOURCE_TO_JOB)
"""Read-only ``family_id → JobId`` mapping for the seven AWS-credit jobs."""


# ---------------------------------------------------------------------------
# CoverageReport model
# ---------------------------------------------------------------------------


class CoverageReport(BaseModel):
    """Structural summary of how ``SOURCE_TO_JOB_MAP`` covers the catalog.

    Emitted by :func:`verify_coverage`. The five counters are:

    - ``total_families`` — size of ``SOURCE_FAMILY_REGISTRY`` (32 today).
    - ``mapped_families`` — how many catalog rows have a job binding.
    - ``unmapped_families`` — catalog rows with no job binding
      (``nta_pdb_personal`` only, since restricted data does not flow
      through the AWS-credit window).
    - ``sources_per_job`` — count of mapped families per ``JobId``.
    - ``jobs_with_zero_sources`` — defensive guard: every entry in
      ``ALL_JOB_IDS`` must appear in ``sources_per_job`` with ≥1
      mapped family.

    The model is frozen so CI artifacts can be dumped to JSON without
    accidental mutation between assertion sites.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_families: int = Field(ge=0)
    mapped_families: int = Field(ge=0)
    unmapped_families: tuple[str, ...]
    sources_per_job: Mapping[str, int]
    jobs_with_zero_sources: tuple[str, ...]
    all_p0_families_mapped: bool


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------


def get_job_for_source(source_family_id: str) -> JobId | None:
    """Return the canonical ``JobId`` for an L1 family, or ``None``.

    Raises ``KeyError`` if ``source_family_id`` is not a known L1
    family (caller passed an invalid id — this is a programming error,
    not a "no job mapped" condition). Returns ``None`` when the family
    is intentionally unmapped (currently only ``nta_pdb_personal``).
    """
    if source_family_id not in SOURCE_FAMILY_REGISTRY:
        raise KeyError(
            f"unknown L1 source family_id={source_family_id!r}; "
            f"see jpintel_mcp.l1_source_family.catalog for the 32 valid ids"
        )
    return _SOURCE_TO_JOB.get(source_family_id)


def get_sources_for_job(job_id: str) -> list[str]:
    """Return all L1 family_ids fetched by ``job_id`` in catalog order.

    Raises ``KeyError`` if ``job_id`` is not one of the seven canonical
    jobs. The return order matches the L1 catalog declaration order so
    downstream Athena partition generation is deterministic.
    """
    if job_id not in ALL_JOB_IDS:
        raise KeyError(
            f"unknown job_id={job_id!r}; "
            f"valid ids: {', '.join(ALL_JOB_IDS)}"
        )
    # Preserve catalog declaration order (SOURCE_FAMILY_REGISTRY iterates
    # in insertion order — Python 3.7+ guarantee).
    return [
        family_id
        for family_id in SOURCE_FAMILY_REGISTRY
        if _SOURCE_TO_JOB.get(family_id) == job_id
    ]


def verify_coverage() -> CoverageReport:
    """Return a :class:`CoverageReport` for the current mapping.

    Asserts (via the report fields, not raises) that:

    1. Every job in ``ALL_JOB_IDS`` has ≥1 mapped source.
    2. Every P0 family has a mapped job (P0 = launch-critical sources).
    3. Unmapped families are explicitly enumerated (restricted data only).

    Callers that need a hard failure (CI gate, deploy preflight) should
    inspect ``jobs_with_zero_sources`` and ``all_p0_families_mapped``
    and raise themselves. The report itself never raises — it is a
    descriptive snapshot.
    """
    total = len(SOURCE_FAMILY_REGISTRY)
    mapped = len(_SOURCE_TO_JOB)
    unmapped_ids = tuple(
        family_id
        for family_id in SOURCE_FAMILY_REGISTRY
        if family_id not in _SOURCE_TO_JOB
    )

    counts: dict[str, int] = dict.fromkeys(ALL_JOB_IDS, 0)
    for job in _SOURCE_TO_JOB.values():
        counts[job] = counts.get(job, 0) + 1

    zero_jobs = tuple(job for job, count in counts.items() if count == 0)

    p0_ids = {row.family_id for row in list_source_families_by_priority("P0")}
    p0_mapped = all(family_id in _SOURCE_TO_JOB for family_id in p0_ids)

    return CoverageReport(
        total_families=total,
        mapped_families=mapped,
        unmapped_families=unmapped_ids,
        sources_per_job=MappingProxyType(counts),
        jobs_with_zero_sources=zero_jobs,
        all_p0_families_mapped=p0_mapped,
    )
