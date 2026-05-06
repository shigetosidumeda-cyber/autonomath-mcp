"""autonomath - Python SDK for the AutonoMath REST API.

Quick start:

    from autonomath import Client

    c = Client(api_key="am_...")
    meta = c.meta()
    results = c.search_programs(tier=["S", "A"], prefecture="東京都")

Async variant:

    from autonomath import AsyncClient

    async with AsyncClient(api_key="am_...") as c:
        meta = await c.meta()
"""

from autonomath.client import Client
from autonomath.client_async import AsyncClient
from autonomath.exceptions import (
    AuthError,
    AutonoMathError,
    JpintelError,  # deprecated alias, retained for backwards compatibility
    NotFoundError,
    RateLimitError,
    ServerError,
)
from autonomath.types import (
    EvidencePacketCompression,
    EvidencePacketDecisionInsights,
    EvidencePacketEnvelope,
    EvidencePacketEvidenceValue,
    EvidencePacketInsightItem,
    EvidencePacketProfile,
    EvidencePacketQuality,
    EvidencePacketQueryBody,
    EvidencePacketRecord,
    EvidencePacketSourceTokensBasis,
    EvidencePacketSubjectKind,
    EvidencePacketVerification,
    ExclusionCheckResponse,
    ExclusionHit,
    ExclusionRule,
    FundingStackCheckRequest,
    FundingStackCheckResponse,
    FundingStackNextAction,
    FundingStackPair,
    FundingStackVerdict,
    IntelBundleDecisionSupport,
    IntelBundleObjective,
    IntelBundleOptimalRequest,
    IntelBundleOptimalResponse,
    IntelDecisionSupportItem,
    IntelDocumentReadiness,
    IntelEligibilityGap,
    IntelEnvelope,
    IntelHoujinDecisionSupport,
    IntelHoujinFullResponse,
    IntelMatchedProgram,
    IntelMatchRequest,
    IntelMatchResponse,
    IntelQuestion,
    Meta,
    Program,
    ProgramDetail,
    SearchResponse,
)

__version__ = "0.1.0"

__all__ = [
    "Client",
    "AsyncClient",
    "AutonoMathError",
    "JpintelError",  # deprecated alias
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "Program",
    "ProgramDetail",
    "SearchResponse",
    "ExclusionRule",
    "ExclusionHit",
    "ExclusionCheckResponse",
    "EvidencePacketCompression",
    "EvidencePacketDecisionInsights",
    "EvidencePacketEnvelope",
    "EvidencePacketEvidenceValue",
    "EvidencePacketInsightItem",
    "EvidencePacketProfile",
    "EvidencePacketQuality",
    "EvidencePacketQueryBody",
    "EvidencePacketRecord",
    "EvidencePacketSourceTokensBasis",
    "EvidencePacketSubjectKind",
    "EvidencePacketVerification",
    "IntelEnvelope",
    "IntelBundleObjective",
    "IntelMatchRequest",
    "IntelMatchResponse",
    "IntelMatchedProgram",
    "IntelQuestion",
    "IntelEligibilityGap",
    "IntelDocumentReadiness",
    "IntelDecisionSupportItem",
    "IntelBundleDecisionSupport",
    "IntelBundleOptimalRequest",
    "IntelBundleOptimalResponse",
    "IntelHoujinDecisionSupport",
    "IntelHoujinFullResponse",
    "FundingStackCheckRequest",
    "FundingStackCheckResponse",
    "FundingStackNextAction",
    "FundingStackPair",
    "FundingStackVerdict",
    "Meta",
    "__version__",
]
