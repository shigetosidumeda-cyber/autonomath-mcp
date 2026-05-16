"""Tests for the canonical L1 source-family → AWS-credit job-id map.

Asserts structural integrity of ``SOURCE_TO_JOB_MAP``:

- every entry references a known L1 family_id (no orphan keys);
- every value is one of the fifteen canonical job_ids;
- every P0 family is mapped to some job (launch-critical surface);
- every job has at least one mapped source (no empty jobs);
- the only intentionally-unmapped family is ``nta_pdb_personal``
  (P2_restricted, license_tag=restricted — out of AWS-credit scope).

These tests are pure metadata — no I/O, no DB, no LLM.
"""

from __future__ import annotations

import importlib
from typing import get_args

import pytest
from pydantic import ValidationError

from jpintel_mcp.aws_credit_ops import (
    ALL_JOB_IDS,
    MAP_VERSION,
    SOURCE_TO_JOB_MAP,
    CoverageReport,
    JobId,
    get_job_for_source,
    get_sources_for_job,
    verify_coverage,
)
from jpintel_mcp.l1_source_family import (
    SOURCE_FAMILY_REGISTRY,
    list_source_families_by_priority,
)

# ---------------------------------------------------------------------------
# Mapping integrity — keys + values
# ---------------------------------------------------------------------------


def test_map_version_is_stable_constant() -> None:
    assert MAP_VERSION == "jpcite.aws_credit_ops.source_to_job_map.v1"


def test_all_job_ids_has_fifteen_entries() -> None:
    """The fifteen AWS-credit jobs J01..J15 must all appear in ALL_JOB_IDS.

    J09 is the courts / judiciary / tribunal-decision crawler; J10 is
    the 法務局 public registry notices + 民事局 statistics +
    休眠会社みなし解散告示 fetcher; J11 is the dedicated e-Stat 政府統計
    + 47 都道府県 + 20 政令市 + 国土地理院 ksj fetcher (added 2026-05-16,
    rebound the previously-J01-swept ``estat_statistics`` family).
    J12-J15 (added 2026-05-16 next session) extend the credit-run to:
    J12 = 国会会議録 (NDL) + 衆参両院 + 47 都道府県議会 + 20 政令市議会
    議事録 (binds new P2 family ``kokkai_diet_minutes``); J13 = EDINET XBRL
    有価証券報告書 + 適時開示 (TDnet) (binds new P2 family ``edinet_xbrl_full``);
    J14 = 特許庁 公報 (特許/商標/意匠/実用新案) + J-PlatPat + 審判決定
    (binds new P2 family ``jpo_patent_gazette_full``); J15 = 環境省 環境情報
    (大気・水質・土壌・廃棄物 + GHG + EIA + PRTR) (binds new P2 family
    ``env_ministry_data``).
    """
    assert len(ALL_JOB_IDS) == 15
    assert set(ALL_JOB_IDS) == {
        "J01_source_profile_sweep",
        "J02_nta_houjin_master_mirror",
        "J03_nta_invoice_registrants_mirror",
        "J04_egov_law_snapshot",
        "J05_jgrants_public_program_acquisition",
        "J06_ministry_municipality_pdf_extraction",
        "J07_gbizinfo_public_business_signals",
        "J08_kanpou_gazette",
        "J09_courts_judiciary",
        "J10_houmu_registry_public",
        "J11_estat_statistics",
        "J12_kokkai_minutes",
        "J13_edinet_xbrl_full",
        "J14_jpo_patent_gazette",
        "J15_env_ministry_data",
    }


def test_every_map_key_is_a_known_l1_family() -> None:
    """No orphan keys — every key must exist in SOURCE_FAMILY_REGISTRY."""
    catalog_ids = set(SOURCE_FAMILY_REGISTRY)
    for family_id in SOURCE_TO_JOB_MAP:
        assert family_id in catalog_ids, (
            f"orphan key {family_id!r} not in L1 catalog"
        )


def test_every_map_value_is_a_canonical_job_id() -> None:
    """Every JobId in the map must be one of the fifteen canonical jobs."""
    allowed = set(get_args(JobId))
    for family_id, job_id in SOURCE_TO_JOB_MAP.items():
        assert job_id in allowed, (
            f"family {family_id!r} maps to non-canonical job {job_id!r}"
        )


def test_map_is_immutable_mapping_proxy() -> None:
    """SOURCE_TO_JOB_MAP is a MappingProxyType — assignment must fail."""
    with pytest.raises(TypeError):
        SOURCE_TO_JOB_MAP["new_family"] = "J01_source_profile_sweep"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Coverage — P0, all jobs ≥ 1 source, no orphan sources
# ---------------------------------------------------------------------------


def test_all_p0_families_have_a_job_binding() -> None:
    """P0 families are launch-critical — every one must be mapped."""
    p0_ids = {row.family_id for row in list_source_families_by_priority("P0")}
    assert len(p0_ids) == 6
    for family_id in p0_ids:
        assert family_id in SOURCE_TO_JOB_MAP, (
            f"P0 family {family_id!r} has no job binding"
        )


def test_every_job_has_at_least_one_mapped_source() -> None:
    """No job in ALL_JOB_IDS may be empty — would break the orchestrator."""
    for job_id in ALL_JOB_IDS:
        sources = get_sources_for_job(job_id)
        assert len(sources) >= 1, f"job {job_id!r} has zero mapped sources"


def test_j08_kanpou_gazette_is_bound_to_gazette_official() -> None:
    """J08 (官報) crawler must own the ``gazette_official`` L1 family.

    Before J08 landed this row was pinned to the J01 sweep because no
    per-source fetcher existed. J08 now owns the kanpou.npb.go.jp
    surface end-to-end (daily index walk + per-notice receipt + PDL
    v1.0 attribution).
    """
    assert get_job_for_source("gazette_official") == "J08_kanpou_gazette"
    sources = set(get_sources_for_job("J08_kanpou_gazette"))
    assert sources == {"gazette_official"}


def test_j11_estat_statistics_is_bound_to_estat_statistics() -> None:
    """J11 (e-Stat 政府統計 deep crawler) must own ``estat_statistics``.

    Before J11 landed this row pinned to J01 (sweep-only). J11 now owns
    the e-Stat v3 API + 47 都道府県統計年鑑 + 20 政令市統計 + 中央省庁
    統計 + 国土地理院 ksj geospatial 10-yr archive surface end-to-end.
    License = 政府統計 CC-BY 4.0 compatible.
    """
    assert (
        get_job_for_source("estat_statistics") == "J11_estat_statistics"
    )
    sources = set(get_sources_for_job("J11_estat_statistics"))
    assert sources == {"estat_statistics"}


def test_j12_kokkai_minutes_is_bound_to_kokkai_diet_minutes() -> None:
    """J12 (国会会議録 + 47 都道府県議会 + 20 政令市議会) must own
    ``kokkai_diet_minutes`` (new P2 family added 2026-05-16).

    J12 owns kokkai.ndl.go.jp 公式 API + 衆参両院 議事録索引 + 47 都道府県
    議会 + 20 政令市議会 + 主要中核市議会 の議事録 index sweep. License =
    NDL OGL 2.0 + 各議会 per-condition.
    """
    assert (
        get_job_for_source("kokkai_diet_minutes") == "J12_kokkai_minutes"
    )
    sources = set(get_sources_for_job("J12_kokkai_minutes"))
    assert sources == {"kokkai_diet_minutes"}


def test_j13_edinet_xbrl_is_bound_to_edinet_xbrl_full() -> None:
    """J13 (EDINET XBRL + 適時開示 TDnet) must own ``edinet_xbrl_full``
    (new P2 family added 2026-05-16).

    J13 owns disclosure.edinet-fsa.go.jp API v2 + TDnet 適時開示 daily
    index. ``edinet_disclosure`` (元 P0) は引き続き J01 sweep に残し、
    J13 は full bulk + XBRL parse の責務を担う。
    """
    assert (
        get_job_for_source("edinet_xbrl_full") == "J13_edinet_xbrl_full"
    )
    sources = set(get_sources_for_job("J13_edinet_xbrl_full"))
    assert sources == {"edinet_xbrl_full"}


def test_j14_jpo_gazette_is_bound_to_jpo_patent_gazette_full() -> None:
    """J14 (JPO 公報 + J-PlatPat + 審判決定 + PCT/Madrid/Hague) must own
    ``jpo_patent_gazette_full`` (new P2 family added 2026-05-16).

    J14 owns publication.jpo.go.jp + j-platpat.inpit.go.jp の週次公報
    index 取得経路. ``tokkyo_jpo`` (元 P2) は引き続き J01 sweep に残り、
    J14 は full 公報 + 審判 + 国際出願 の責務を担う。
    """
    assert (
        get_job_for_source("jpo_patent_gazette_full") == "J14_jpo_patent_gazette"
    )
    sources = set(get_sources_for_job("J14_jpo_patent_gazette"))
    assert sources == {"jpo_patent_gazette_full"}


def test_j15_env_ministry_is_bound_to_env_ministry_data() -> None:
    """J15 (環境省 大気・水質・土壌・廃棄物 + GHG + EIA + PRTR) must own
    ``env_ministry_data`` (new P2 family added 2026-05-16).

    J15 owns env.go.jp + soramame.env.go.jp + ghg-santeikohyo.env.go.jp
    の取得経路。``env_regulations`` (元 P1) は J06 で省庁 PDF として継続
    取得、``mafg_climate`` (元 P2) は J01 sweep に残る。J15 は環境省
    全局 の規制業種 DD 軸を担う。
    """
    assert (
        get_job_for_source("env_ministry_data") == "J15_env_ministry_data"
    )
    sources = set(get_sources_for_job("J15_env_ministry_data"))
    assert sources == {"env_ministry_data"}


def test_only_nta_pdb_personal_is_unmapped() -> None:
    """Restricted data is the only catalog row excluded from the AWS jobs."""
    unmapped = [
        family_id
        for family_id in SOURCE_FAMILY_REGISTRY
        if family_id not in SOURCE_TO_JOB_MAP
    ]
    assert unmapped == ["nta_pdb_personal"]


def test_mapped_count_equals_catalog_minus_restricted() -> None:
    """36 catalog rows − 1 restricted = 35 mapped families (32 original + 4 J12-J15)."""
    assert len(SOURCE_TO_JOB_MAP) == len(SOURCE_FAMILY_REGISTRY) - 1
    assert len(SOURCE_TO_JOB_MAP) == 35


# ---------------------------------------------------------------------------
# get_job_for_source — happy + unhappy paths
# ---------------------------------------------------------------------------


def test_get_job_for_source_returns_canonical_job() -> None:
    """Known happy paths from the J04 / J05 / J07 manifests."""
    assert (
        get_job_for_source("egov_laws_regulations") == "J04_egov_law_snapshot"
    )
    assert (
        get_job_for_source("jgrants_subsidy_portal")
        == "J05_jgrants_public_program_acquisition"
    )
    assert (
        get_job_for_source("gbizinfo_houjin")
        == "J07_gbizinfo_public_business_signals"
    )
    assert (
        get_job_for_source("nta_invoice_publication")
        == "J03_nta_invoice_registrants_mirror"
    )


def test_get_job_for_source_returns_none_for_restricted() -> None:
    """``nta_pdb_personal`` is unmapped — returns None, not KeyError."""
    assert get_job_for_source("nta_pdb_personal") is None


def test_get_job_for_source_raises_keyerror_for_unknown_id() -> None:
    """Unknown family_ids are programming errors — must raise."""
    with pytest.raises(KeyError, match="unknown L1 source family_id"):
        get_job_for_source("not_a_real_family")


# ---------------------------------------------------------------------------
# get_sources_for_job — happy + unhappy paths
# ---------------------------------------------------------------------------


def test_get_sources_for_job_returns_known_families() -> None:
    """J04 (e-Gov) sweeps both laws + amendment diff."""
    sources = set(get_sources_for_job("J04_egov_law_snapshot"))
    assert sources == {"egov_laws_regulations", "egov_amendment_diff"}


def test_get_sources_for_job_j03_invoice_covers_both_publication_and_extended() -> None:
    """J03 NTA invoice mirror sweeps the P0 publication + P1 extended row."""
    sources = set(
        get_sources_for_job("J03_nta_invoice_registrants_mirror")
    )
    assert sources == {"nta_invoice_publication", "nta_invoice_extended"}


def test_get_sources_for_job_j06_pdf_extraction_includes_municipal_wrappers() -> None:
    """J06 sweeps ministry index pages + the 47/800 segmented wrappers."""
    sources = set(
        get_sources_for_job("J06_ministry_municipality_pdf_extraction")
    )
    # Must include the two segmented wrappers + at least 3 ministry rows.
    assert "pref_47_municipal" in sources
    assert "muni_800_segments" in sources
    assert "meti_subsidies" in sources
    assert "mhlw_labor" in sources
    assert "maff_grants_extended" in sources


def test_get_sources_for_job_raises_keyerror_for_unknown_job() -> None:
    with pytest.raises(KeyError, match="unknown job_id"):
        get_sources_for_job("J99_nonexistent")


def test_get_sources_for_job_preserves_catalog_order() -> None:
    """Return order must match L1 catalog declaration order."""
    catalog_order = list(SOURCE_FAMILY_REGISTRY)
    j06_sources = get_sources_for_job(
        "J06_ministry_municipality_pdf_extraction"
    )
    # Each consecutive pair must respect catalog order.
    indices = [catalog_order.index(family_id) for family_id in j06_sources]
    assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# verify_coverage — structural CoverageReport
# ---------------------------------------------------------------------------


def test_verify_coverage_returns_frozen_coverage_report() -> None:
    report = verify_coverage()
    assert isinstance(report, CoverageReport)
    # Frozen — model_config sets frozen=True, so field mutation raises.
    with pytest.raises(ValidationError):
        report.total_families = 99  # type: ignore[misc]


def test_verify_coverage_reports_no_empty_jobs() -> None:
    """``jobs_with_zero_sources`` must be empty (CI gate)."""
    report = verify_coverage()
    assert report.jobs_with_zero_sources == ()


def test_verify_coverage_flags_all_p0_mapped() -> None:
    report = verify_coverage()
    assert report.all_p0_families_mapped is True


def test_verify_coverage_counts_match_catalog_and_map() -> None:
    report = verify_coverage()
    assert report.total_families == 36
    assert report.mapped_families == 35
    assert report.unmapped_families == ("nta_pdb_personal",)
    # All fifteen jobs must appear in sources_per_job with ≥ 1 count.
    assert set(report.sources_per_job.keys()) == set(ALL_JOB_IDS)
    for job_id, count in report.sources_per_job.items():
        assert count >= 1, f"{job_id!r} has zero mapped families"


def test_verify_coverage_sources_per_job_sum_equals_mapped() -> None:
    """Sum of per-job counts must equal total mapped families."""
    report = verify_coverage()
    assert sum(report.sources_per_job.values()) == report.mapped_families


# ---------------------------------------------------------------------------
# Anti-pattern enforcement — no live I/O, no LLM imports
# ---------------------------------------------------------------------------


def test_module_does_not_import_http_or_llm_clients() -> None:
    """source_to_job_map must stay pure metadata (no httpx, no SDKs)."""
    mod = importlib.import_module(
        "jpintel_mcp.aws_credit_ops.source_to_job_map"
    )
    forbidden = {
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "httpx",
        "requests",
        "urllib3",
        "playwright",
        "selenium",
        "boto3",
    }
    for name in forbidden:
        top = name.split(".")[0]
        assert top not in mod.__dict__, (
            f"{name} must not be imported by aws_credit_ops.source_to_job_map"
        )
