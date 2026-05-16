"""Canonical L1 source-family → AWS-credit job-id map.

This module bridges the Wave 51 L1 source family catalog
(:mod:`jpintel_mcp.l1_source_family.catalog` — 36 families post 2026-05-16
J12-J15 extensions: 32 original + 4 new P2 families
kokkai_diet_minutes / edinet_xbrl_full / jpo_patent_gazette_full /
env_ministry_data) with the 15 AWS credit consumption jobs (J01..J15)
declared in ``data/aws_credit_jobs/J*.json``.
The mapping is consumed by the crawler container and by the Step
Functions orchestrator so each fetched URL can be tagged with the
originating L1 family and the per-source contract metadata
(``license_boundary``, ``robots_respect``, ``required_notice``,
``redistribution_scope``) without having to re-walk the catalog at
runtime.

Design constraints (mirrored from ``catalog.py``):

- **Static only**: literal table at import time; no I/O, no DB, no LLM.
- **No live HTTP**: this module imports neither ``httpx`` nor any
  scraping library.
- **Authoritative job manifests**: ``data/aws_credit_jobs/J*.json``
  are the source of truth for the URLs each job sweeps. This map
  declares the *family-id ↔ job-id* relationship that the manifests
  reference at the ``source_family`` / ``publisher`` level.

Per ``docs/_internal/aws_credit_data_acquisition_jobs_agent.md``:

- **J01** (source profile sweep) — every P0 family.
- **J02** (NTA法人番号 master mirror) — corporate-identity axis; binds
  ``gbizinfo_houjin_extended`` (the houjin_bangou identity layer is the
  NTA upstream authority that gBizINFO mirrors downstream — see J07).
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
- **J10** (法務局 public registry notices + 民事局 statistics +
  休眠会社みなし解散告示) — canonical 法務省 axis for 商業登記簿 /
  不動産登記 / 法人設立・変更履歴 / 代表者 / 解散 / 合併. **Public
  notice + 統計 only** — per-company registry lookup via the paid
  登記情報提供サービス (touki.or.jp) is structurally excluded
  (``no_per_company_lookup: true`` gate + ``paid_api_excluded`` list
  in the manifest). Binds ``sangyo_houjin_registry`` which previously
  rode J02 before this dedicated 法務省 fetcher landed.

Use :func:`get_job_for_source` to look up the job_id for an L1 family,
:func:`get_sources_for_job` to enumerate the families a job sweeps, and
:func:`verify_coverage` to assert all jobs have at least one
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

#: Canonical job_id enumeration. Mirrors the sixteen JSON files under
#: ``data/aws_credit_jobs/`` (J01..J16). J09 is the dedicated
#: courts / judiciary / tribunal-decision fetcher (最高裁判決 last 5y +
#: 国税不服審判所 公表裁決 + 公取委 排除/課徴金 + 中労委 命令検索 +
#: 行政不服審査会答申 + 人事院 + 公害等調整委員会 + 知財高裁).
#: J11 (added 2026-05-16) is the dedicated e-Stat 政府統計 + 47 都道府県
#: + 20 政令市 + 中央省庁統計 + 国土地理院 ksj fetcher; rebinds the
#: previously-J01-swept ``estat_statistics`` family.
#: J12..J15 (added 2026-05-16 next session) extend the credit-run to:
#: J12 = 国会会議録 (NDL) + 衆参両院 + 47 都道府県議会 + 20 政令市議会 議事録;
#: J13 = EDINET XBRL 有価証券報告書 + 適時開示 (TDnet);
#: J14 = 特許庁 公報 (特許/商標/意匠/実用新案) + J-PlatPat + 審判決定;
#: J15 = 環境省 環境情報 (大気・水質・土壌・廃棄物 + GHG + EIA + PRTR).
#: J16 (added 2026-05-16, post J06 HTML-walk-zero-PDFs incident) is the
#: dedicated canonical 公的 PDF direct-URL fetcher: 中小企業庁 補助金要綱
#: + 各省庁 白書 + 内閣府 経済財政白書 + 47 都道府県商工労働政策 PDF +
#: 中央労働委員会 命令 PDF + 各省庁 行政告示 PDF。J06 が HTML index walk で
#: PDF link follow に失敗 (0 PDFs) した教訓に基づき、direct .pdf URL を
#: hardcode して raw blob acquisition path を独立に確立する。
JobId = Literal[
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
    "J16_canonical_pdf_corpus",
]

#: All sixteen job_ids in declaration order. Tests gate on
#: ``set(ALL_JOB_IDS) == set(SOURCE_TO_JOB_MAP.values()) ∪ {J01..J16}``
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
    "J09_courts_judiciary",
    "J10_houmu_registry_public",
    "J11_estat_statistics",
    "J12_kokkai_minutes",
    "J13_edinet_xbrl_full",
    "J14_jpo_patent_gazette",
    "J15_env_ministry_data",
    "J16_canonical_pdf_corpus",
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
    # which is J07's target. The L1 catalog row for "corp master" lives
    # at gbizinfo_houjin which is the J07 surface, so we pin it to J07.
    "gbizinfo_houjin": "J07_gbizinfo_public_business_signals",
    # --- J02: NTA houjin_bangou master mirror ---
    # ``gbizinfo_houjin_extended`` pins to J02 because the extended
    # surface (history / merge / dissolution / address-change events)
    # is sourced upstream from the NTA houjin_bangou bulk mirror that
    # J02 owns. This also satisfies verify_coverage by giving J02 its
    # canonical L1 family bind, formerly held by sangyo_houjin_registry
    # before J10 (法務省) landed as the dedicated 法務局 fetcher.
    "gbizinfo_houjin_extended": "J02_nta_houjin_master_mirror",
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
    # --- J10: 法務局 public registry notices + 民事局 statistics ---
    # ``sangyo_houjin_registry`` is P0 (法務省 法人登記) and is now
    # canonically bound to J10, the dedicated 法務局 public-notices +
    # 休眠会社みなし解散告示 + 商業登記/不動産登記統計 fetcher. Before
    # J10 landed it rode J02 (NTA houjin_bangou) as a placeholder.
    # **Per-company registry record lookup is NOT in scope** — the
    # J10 manifest carries ``no_per_company_lookup: true`` plus a
    # ``paid_api_excluded`` list so the paid 登記情報提供サービス
    # (touki.or.jp, per-query ¥332-¥500 + auth) cannot be invoked
    # from this AWS-credit window.
    "sangyo_houjin_registry": "J10_houmu_registry_public",
    # --- J08: 官報 (kanpou) gazette notice crawler ---
    # gazette_official binds to J08, the dedicated gazette daily-index
    # walker. Before J08 landed this row pointed at J01 (sweep-only)
    # because no per-source fetcher existed; J08 now owns the
    # kanpou.npb.go.jp surface end-to-end (daily index + per-notice
    # receipt + PDL v1.0 attribution).
    "gazette_official": "J08_kanpou_gazette",
    # --- J09: courts / judiciary / tribunal decisions ---
    # ``court_decisions`` (最高裁判例検索 + 高裁 + 地裁 + 知財高裁) and
    # ``enforcement_actions`` (公取委 排除措置 + 課徴金 + 中労委 命令 +
    # 行政不服審査会答申 + 人事院 + 国税不服審判所 公表裁決) bind to
    # J09, the dedicated courts/judiciary fetcher. Before J09 landed
    # they were swept by J01 only. Court 判決 are public domain; tribunal
    # rulings (KFS / JFTC / 中労委 / 人事院 / 行政不服) are公務著作権 with
    # 出典明記による再配布可.
    "court_decisions": "J09_courts_judiciary",
    "enforcement_actions": "J09_courts_judiciary",
    # Remaining P1/P2 families are profiled by J01 (their bulk fetch is
    # not in scope for the AWS-credit window).
    "soumu_local_gov": "J01_source_profile_sweep",
    "jfc_loans": "J01_source_profile_sweep",
    "unic_pmda": "J01_source_profile_sweep",
    "jetro_invest": "J01_source_profile_sweep",
    "jisc_standards": "J01_source_profile_sweep",
    "tokkyo_jpo": "J01_source_profile_sweep",
    "mafg_climate": "J01_source_profile_sweep",
    # --- J11: e-Stat 政府統計 + 47 都道府県 + 20 政令市 + 国土地理院 ksj ---
    # ``estat_statistics`` (政府統計の総合窓口) is now canonically bound
    # to J11, the dedicated 統計 deep crawler (e-Stat v3 API + 47 都道府県
    # 統計年鑑 + 20 政令市統計 + 中央省庁統計 + 国土地理院 ksj geospatial
    # layers + BoJ tankan + 観光庁 + 中小企業庁 / MAFF census). Before
    # J11 landed this row pointed at J01 (sweep-only). License = 政府
    # 統計 CC-BY 4.0 compatible.
    "estat_statistics": "J11_estat_statistics",
    "njss_bids_aggregated": "J01_source_profile_sweep",
    # --- J12: 国会会議録 (NDL) + 47 都道府県議会 + 20 政令市議会 ---
    # ``kokkai_diet_minutes`` is a NEW P2 family added 2026-05-16
    # alongside J12. It owns 国会会議録検索システム (kokkai.ndl.go.jp)
    # + 衆参両院 議事録索引 + 47 都道府県議会 + 20 政令市議会 + 主要中核市
    # 議事録 index の 1 元目の取得経路。 License = NDL OGL 2.0 +
    # 各議会 per-condition.
    "kokkai_diet_minutes": "J12_kokkai_minutes",
    # --- J13: EDINET XBRL 有価証券報告書 + 適時開示 (TDnet) ---
    # ``edinet_xbrl_full`` is a NEW P2 family added 2026-05-16 alongside
    # J13. It owns disclosure.edinet-fsa.go.jp / TDnet 適時開示 daily
    # index の 1 元目の取得経路。``edinet_disclosure`` (元 P0) は引き続き
    # J01 sweep に残し、J13 は full bulk + XBRL parse の責務を担う。
    "edinet_xbrl_full": "J13_edinet_xbrl_full",
    # --- J14: 特許庁 公報 (特許 + 商標 + 意匠 + 実用新案) + J-PlatPat ---
    # ``jpo_patent_gazette_full`` is a NEW P2 family added 2026-05-16
    # alongside J14. It owns publication.jpo.go.jp + j-platpat.inpit.go.jp
    # の週次公報 index 取得経路。``tokkyo_jpo`` (元 P2) は引き続き J01
    # sweep に残し、J14 は full 公報 + 審判 + PCT/Madrid/Hague 国際出願
    # の責務を担う。
    "jpo_patent_gazette_full": "J14_jpo_patent_gazette",
    # --- J15: 環境省 環境情報 (大気・水質・土壌・廃棄物 + GHG + EIA + PRTR) ---
    # ``env_ministry_data`` is a NEW P2 family added 2026-05-16 alongside
    # J15. It owns env.go.jp + soramame.env.go.jp + ghg-santeikohyo.env.go.jp
    # の取得経路。``env_regulations`` (元 P1) は J06 で省庁 PDF として継続
    # 取得、``mafg_climate`` (元 P2) は J01 sweep に残る。J15 は環境省
    # 全局 (大気 / 水 / 土 / 廃棄物 / 地球 / 化学物質 / 自然 / アセス) の
    # 規制業種 DD 軸を担う。
    "env_ministry_data": "J15_env_ministry_data",
    # --- J16: canonical 公的 PDF corpus (direct .pdf URL acquisition) ---
    # ``canonical_pdf_corpus`` is a NEW P2 family added 2026-05-16 alongside
    # J16. Owns direct fetch of 220+ known canonical 公的 PDF endpoints
    # across 中小企業庁 (補助金要綱) / 経産省 (産業政策白書) / 環境省 +
    # 厚労省 + 文科省 + 国交省 + 農水省 + 内閣府 + 47 都道府県商工労働政策
    # + 中央労働委員会 命令 + 各省庁 白書。J06 が HTML index walk で
    # PDF link follow に失敗 (0 PDFs) した経路独立化のために導入。
    # parser=pdf_fetch (Textract は別 job で後工程適用)。
    "canonical_pdf_corpus": "J16_canonical_pdf_corpus",
    # ``nta_pdb_personal`` (P2_restricted, license_tag=restricted) is
    # explicitly excluded — restricted data does not flow through the
    # AWS-credit window. verify_coverage asserts this row is unmapped.
}


#: Immutable view of the source → job map. Keyed by L1 ``family_id``,
#: value is the canonical ``JobId`` that fetches the family.
SOURCE_TO_JOB_MAP: Mapping[str, JobId] = MappingProxyType(_SOURCE_TO_JOB)
"""Read-only ``family_id → JobId`` mapping for the fifteen AWS-credit jobs."""


# ---------------------------------------------------------------------------
# CoverageReport model
# ---------------------------------------------------------------------------


class CoverageReport(BaseModel):
    """Structural summary of how ``SOURCE_TO_JOB_MAP`` covers the catalog.

    Emitted by :func:`verify_coverage`. The five counters are:

    - ``total_families`` — size of ``SOURCE_FAMILY_REGISTRY`` (37 today, post J12-J16).
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
            f"see jpintel_mcp.l1_source_family.catalog for the 37 valid ids"
        )
    return _SOURCE_TO_JOB.get(source_family_id)


def get_sources_for_job(job_id: str) -> list[str]:
    """Return all L1 family_ids fetched by ``job_id`` in catalog order.

    Raises ``KeyError`` if ``job_id`` is not one of the fifteen canonical
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
