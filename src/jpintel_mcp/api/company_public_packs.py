"""Company public packs router (jpcite v0.3.4).

Surfaces the three "public-source corporate diligence" artifact endpoints that
must always be reachable on the live API surface (not gated behind
``AUTONOMATH_EXPERIMENTAL_API_ENABLED``):

- ``POST /v1/artifacts/company_public_baseline``
- ``POST /v1/artifacts/company_folder_brief``
- ``POST /v1/artifacts/company_public_audit_pack``

Each handler delegates to the existing pure-SQLite + Python builders defined in
``jpintel_mcp.api.artifacts``. NO LLM is called inside this router — the
artifact bodies are 100 % source-backed (法人番号 corpus + 公開行政処分 +
インボイス公表 + 採択 corpus).

Sensitive content fence (the 3 endpoints surface 公認会計士法 §47条の2 / 税理士法
§52 / 司法書士法 §3 / 行政書士法 §1 territory): the ``_disclaimer`` envelope
inherited from ``/v1/intel/houjin/{id}/full`` already lists those statutes, and
``_attach_common_artifact_envelope`` wires it into the artifact response. The
local fallback below preserves that fence even when the upstream
``houjin_body`` happens to ship an empty disclaimer (defensive — should not
happen in practice but the §52 / §47条の2 line must never be missing).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from jpintel_mcp.api.artifacts import (
    ArtifactResponse,
    CompanyPublicArtifactRequest,
    _build_company_folder_brief_artifact,
    _build_company_public_audit_pack_artifact,
    _build_company_public_baseline_artifact,
    _create_company_public_artifact,
)
from jpintel_mcp.api.deps import (  # noqa: TC001 — Annotated runtime deps
    ApiContextDep,
    DbDep,
)

# §47条の2 (公認会計士法) + §52 (税理士法) + §72 (弁護士法) + §3 (司法書士法) +
# §1 (行政書士法). 既存 _disclaimer がブランクで届くケースに備えた最小フェンス。
_SENSITIVE_BUSINESS_LAW_DISCLAIMER = (
    "本 artifact は公開情報のみで構成された下書きです。"
    "公認会計士法 §47条の2、税理士法 §52、弁護士法 §72、"
    "司法書士法 §3、行政書士法 §1 の業務独占範囲に該当する助言・代理・書面作成は"
    "含まれません。最終判断は資格者によるレビューを前提としてください。"
)


router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


def _ensure_business_law_disclaimer(body: dict[str, Any]) -> None:
    """Guarantee the §52 / §47条の2 fence is present on the artifact response."""
    existing = body.get("_disclaimer")
    if not isinstance(existing, str) or not existing.strip():
        body["_disclaimer"] = _SENSITIVE_BUSINESS_LAW_DISCLAIMER


@router.post(
    "/company_public_baseline",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="会社 public baseline artifact (法人番号公開情報ベースライン — no LLM)",
    description=(
        "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
        "会社の公開情報ベースライン、根拠URL、known gaps、次アクションを "
        "artifact envelope として返す。NO LLM。"
    ),
)
def create_company_public_baseline(
    payload: CompanyPublicArtifactRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    body = _create_company_public_artifact(
        payload=payload,
        conn=conn,
        ctx=ctx,
        artifact_type="company_public_baseline",
        builder=_build_company_public_baseline_artifact,
    )
    _ensure_business_law_disclaimer(body)
    return body


@router.post(
    "/company_folder_brief",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="会社 folder brief artifact (社内フォルダ用公開情報ブリーフ — no LLM)",
    description=(
        "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
        "社内フォルダへ貼れる会社概要、DD snapshot、確認チェックリストを "
        "artifact envelope として返す。NO LLM。"
    ),
)
def create_company_folder_brief(
    payload: CompanyPublicArtifactRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    body = _create_company_public_artifact(
        payload=payload,
        conn=conn,
        ctx=ctx,
        artifact_type="company_folder_brief",
        builder=_build_company_folder_brief_artifact,
    )
    _ensure_business_law_disclaimer(body)
    return body


@router.post(
    "/company_public_audit_pack",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="会社 public audit pack artifact (公開根拠監査パック — no LLM)",
    description=(
        "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
        "監査・レビュー向けの対象、根拠台帳、risk/gap register、review controls を "
        "artifact envelope として返す。NO LLM。"
    ),
)
def create_company_public_audit_pack(
    payload: CompanyPublicArtifactRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    body = _create_company_public_artifact(
        payload=payload,
        conn=conn,
        ctx=ctx,
        artifact_type="company_public_audit_pack",
        builder=_build_company_public_audit_pack_artifact,
    )
    _ensure_business_law_disclaimer(body)
    return body


__all__ = ["router"]
