"""Agent-first runtime contracts for jpcite P0.

This package contains deterministic contract objects used before any live AWS
execution is allowed. It intentionally has no AWS SDK dependency and performs
no network calls.
"""

from jpintel_mcp.agent_runtime.contracts import (
    AcceptedArtifactPricing,
    AgentPurchaseDecision,
    AwsNoopCommandPlan,
    CapabilityMatrix,
    ClaimRef,
    ConsentEnvelope,
    Evidence,
    ExecutionGraph,
    FactMetadata,
    FederatedPartner,
    GapCoverageEntry,
    JpcirHeader,
    KnownGap,
    NoHitLease,
    OutcomeContract,
    PolicyDecision,
    PrivateFactCapsule,
    PrivateFactCapsuleRecord,
    ReleaseCapsuleManifest,
    ScopedCapToken,
    SourceReceipt,
)

__all__ = [
    "AcceptedArtifactPricing",
    "AgentPurchaseDecision",
    "AwsNoopCommandPlan",
    "CapabilityMatrix",
    "ClaimRef",
    "ConsentEnvelope",
    "Evidence",
    "ExecutionGraph",
    "FactMetadata",
    "FederatedPartner",
    "GapCoverageEntry",
    "JpcirHeader",
    "KnownGap",
    "NoHitLease",
    "OutcomeContract",
    "PolicyDecision",
    "PrivateFactCapsule",
    "PrivateFactCapsuleRecord",
    "ReleaseCapsuleManifest",
    "ScopedCapToken",
    "SourceReceipt",
]
