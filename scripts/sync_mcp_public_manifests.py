#!/usr/bin/env python3
"""Sync public MCP manifests with the runtime FastMCP tool registry."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from jpintel_mcp.mcp.transport_metadata import (
    MCP_PRIMARY_TRANSPORT,
    mcp_transport_manifest_meta,
    mcp_transport_names,
)

FULL_MANIFESTS = [
    REPO_ROOT / "mcp-server.json",
    REPO_ROOT / "mcp-server.full.json",
    REPO_ROOT / "site" / "mcp-server.json",
    REPO_ROOT / "site" / "mcp-server.full.json",
]
SUBSET_MANIFESTS = [
    REPO_ROOT / "mcp-server.core.json",
    REPO_ROOT / "mcp-server.composition.json",
]
SERVER_MANIFESTS = [
    REPO_ROOT / "server.json",
    REPO_ROOT / "site" / "server.json",
]
DOCS = REPO_ROOT / "docs" / "mcp-tools.md"
LLMS_FILES = [
    REPO_ROOT / "site" / "llms.txt",
    REPO_ROOT / "site" / "llms.en.txt",
    REPO_ROOT / "site" / "en" / "llms.txt",
]

TRANSPORTS_NOTE = str(mcp_transport_manifest_meta()["transports_note"])

PUBLIC_DESCRIPTION_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ---- Internal-source citations (CLAUDE.md / waves / migrations / DEEP) ----
    (re.compile(r"CLAUDE\.md gotcha"), "known data-quality caveat"),
    (re.compile(r"\bCLAUDE\.md\b"), "internal handoff doc"),
    (re.compile(r"\bmigration\s+\d+\b", re.IGNORECASE), "data update"),
    (re.compile(r"\bmig\s+\d+\b", re.IGNORECASE), "data update"),
    (re.compile(r"\bmigrations?\s+\d+(?:[-/]\d+)+\b", re.IGNORECASE), "data update"),
    (re.compile(r"\bWave\s+\d+(?:\.\d+)*\b"), "release"),
    (re.compile(r"\bDEEP-\d+\b"), "public dataset"),
    (re.compile(r"\beligibility_hash\b"), "eligibility change marker"),
    # ---- Process / infrastructure detail ----
    (re.compile(r"\bSQL only\b", re.IGNORECASE), "deterministic retrieval"),
    (re.compile(r"\bPure SQLite\b", re.IGNORECASE), "deterministic retrieval"),
    (re.compile(r"\bPure SQL \+ Python\b", re.IGNORECASE), "deterministic retrieval"),
    (re.compile(r"\bSQL \+ Python\b", re.IGNORECASE), "deterministic retrieval"),
    (re.compile(r"\bPure SQL\b", re.IGNORECASE), "deterministic retrieval"),
    (re.compile(r"\bSQLite\b", re.IGNORECASE), "structured public index"),
    (re.compile(r"\bcron\b", re.IGNORECASE), "scheduled update"),
    # ---- Internal DB filenames + legacy brand names ----
    # NOTE: keep the .db rules BEFORE the bare-brand rules so the suffix is
    # consumed in one shot — otherwise the bare brand rule rewrites the stem
    # and the leftover ".db" lands in user-facing copy.
    (re.compile(r"\b(?:jpintel|autonomath)\.db\b", re.IGNORECASE), "public corpus"),
    (re.compile(r"\bjpintel\b", re.IGNORECASE), "public corpus"),
    (re.compile(r"\bautonomath\b", re.IGNORECASE), "public corpus"),
    (re.compile(r"\bAutonoMath\b"), "public corpus"),
    (re.compile(r"\bzeimu-kaikei(?:\.ai)?\b", re.IGNORECASE), "public corpus"),
    (re.compile(r"\bDB\b"), "public index"),
    # ---- Internal table names ----
    (re.compile(r"\busage_events\b"), "usage summary"),
    (re.compile(r"\bapi_keys\b"), "credential records"),
    (re.compile(r"\bcost_ledger(?:\.[a-z0-9_]+)?\b"), "cost summary"),
    (re.compile(r"\baeo_citation_bench\b"), "AI citation benchmark"),
    # ---- Secret-shaped examples (api_key="am_xxxx" / Bearer am_xxxx) ----
    # Run these BEFORE the generic am_* / jpi_* rewrites so the surrounding
    # placeholder text ("<your-api-key>") survives downstream substitution.
    (re.compile(r"Authorization:\s*Bearer\s+am_[A-Za-z0-9_]+", re.IGNORECASE),
     "Authorization: Bearer <your-api-key>"),
    (re.compile(r"\bapi_key=\"[^\"]+\""), 'api_key="<your-api-key>"'),
    (re.compile(r"\bapi_key='[^']+'"), "api_key='<your-api-key>'"),
    (re.compile(r"\bam_x{2,}[A-Za-z0-9_]*\b"), "<your-api-key>"),
    # ---- Internal schema prefixes ----
    (re.compile(r"`?(?<![A-Za-z0-9_])(?:am|v|jpi|jc)_[a-z0-9_]+`?"), "source-derived dataset"),
    (re.compile(r"\bam_[A-Za-z0-9_]+\b"), "source-derived dataset"),
    (re.compile(r"\b(?:program_law_refs|funding_stack_empirical|density_score|exclusion_rules|case_studies|loan_programs|enforcement_cases)\b"), "source-derived dataset"),
    (re.compile(r"\bdata/[A-Za-z0-9_./*-]+\b"), "published artifact"),
    (re.compile(r"\banalytics/[A-Za-z0-9_./*-]+\b"), "published artifact"),
    # ---- RISK → review re-framing ----
    (re.compile(r"\bRISK:"), "SCREENING:"),
    (re.compile(r"PROGRAM-RISK-4D"), "PROGRAM-REVIEW-4D"),
    (re.compile(r"R8-INVOICE-RISK"), "R8-INVOICE-REVIEW"),
    (re.compile(r"\b3-axis risk\b", re.IGNORECASE), "3-axis lending-condition"),
    (re.compile(r"\brisk lookup\b", re.IGNORECASE), "review lookup"),
    (re.compile(r"\brisk envelope\b", re.IGNORECASE), "review envelope"),
    (re.compile(r"\brisk=\{…\}", re.IGNORECASE), "review={…}"),
    (re.compile(r"\brisk filters\b", re.IGNORECASE), "lending-condition filters"),
    (re.compile(r"\bthree-axis risk\b", re.IGNORECASE), "three-axis lending-condition"),
    (re.compile(r"\brisk score\b", re.IGNORECASE), "review score"),
    (re.compile(r"\brisk_band\b"), "review_band"),
    (re.compile(r"\brisk_score\b"), "quality_score"),
    (re.compile(r"\brisk_4d\b"), "quality_4d"),
    (re.compile(r"\btop_risk\b"), "top_review_signal"),
    (re.compile(r"\brisk pairs\b", re.IGNORECASE), "review pairs"),
    (re.compile(r"\bfraud-risk\b", re.IGNORECASE), "fraud-review"),
    (re.compile(r"\b与信 risk\b", re.IGNORECASE), "与信 review"),
    (re.compile(r"\binvoice_risk_lookup\b"), "invoice_review_lookup"),
    (re.compile(r"/ risk\b", re.IGNORECASE), "/ review"),
    # ---- ROI / ARR rewording (per-case cost saving only, never ROI/ARR) ----
    (re.compile(r"\bROI\b"), "value"),
    (re.compile(r"\bARR\b"), "annualized usage"),
    (re.compile(r"\bTOKEN BUDGET\b"), "RESPONSE SIZE"),
    # ---- Cohort → peer-group rewording ----
    (re.compile(r"\[COHORT-MATCH\]"), "[PEER-MATCH]"),
    (re.compile(r"\[COHORT-5D\]"), "[PEER-5D]"),
    (re.compile(r"\bcohort matcher\b", re.IGNORECASE), "peer-group matcher"),
    (re.compile(r"\bcohort\b", re.IGNORECASE), "peer group"),
    (re.compile(r"\bcohort_impact\b"), "peer_group_impact"),
    (re.compile(r"\bcohort_meta\b"), "peer_group_meta"),
    (re.compile(r"\bcohort_share\b"), "peer_group_share"),
    (re.compile(r"\bcohort_summary\b"), "profile_summary"),
    # ---- Pricing marker normalization ----
    (re.compile(r"¥\s*3\s*/\s*(?:req|request|call)\b", re.IGNORECASE), "¥3/billable unit"),
    (re.compile(r"\bJPY\s*3\s*/\s*(?:req|request|call)\b", re.IGNORECASE), "JPY 3/billable unit"),
    # ---- Public scope normalization ----
    (re.compile(r"\bEvery tool response carries\b", re.IGNORECASE), "Evidence-oriented tool responses include"),
    (re.compile(r"\bevery response carries\b", re.IGNORECASE), "covered responses include"),
    (re.compile(r"\bevery response surfaces\b", re.IGNORECASE), "covered responses surface"),
    (re.compile(r"\benvelope on every response\b", re.IGNORECASE), "envelope on covered responses"),
    (re.compile(r"\battribution baked into every response\b", re.IGNORECASE), "attribution included in covered responses"),
)

# Belt-and-suspenders post-sanitize gate.  These patterns MUST NOT remain in
# any string written out by the sync script — if one does, a runtime tool
# author has introduced a new leakage shape and the script should fail hard so
# the manifest is never regenerated with a leak.
BANNED_PUBLIC_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bjpintel\.db\b", re.IGNORECASE),
    re.compile(r"\bautonomath\.db\b", re.IGNORECASE),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bapi_keys\b"),
    re.compile(r"\bcost_ledger\b"),
    re.compile(r"\bam_x{2,}[A-Za-z0-9_]*\b"),
    re.compile(r"Authorization:\s*Bearer\s+am_", re.IGNORECASE),
    re.compile(r"\bARR\b"),
    re.compile(r"\bROI\b"),
    re.compile(r"\bWave\s+\d", re.IGNORECASE),
    re.compile(r"\bmigration\s+\d", re.IGNORECASE),
    re.compile(r"CLAUDE\.md"),
)


def _runtime_tools() -> list[dict[str, str]]:
    from jpintel_mcp.mcp.server import mcp

    async def load() -> list[dict[str, str]]:
        tools = await mcp.list_tools()
        return [
            {
                "name": tool.name,
                "description": _sanitize_public_description((tool.description or "").strip()),
            }
            for tool in tools
        ]

    return asyncio.run(load())


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_public_leaks(path: Path, payload: str) -> None:
    """Fail loudly if the rendered manifest still carries a banned pattern.

    The sanitizer is the first line of defence (regex replace).  This is the
    second line of defence: a hard gate over the *rendered JSON string* so a
    new shape of leak in a runtime tool description cannot slip through into
    the manifest a regen-and-commit lands on disk.
    """
    leaks: list[str] = []
    for pattern in BANNED_PUBLIC_LEAK_PATTERNS:
        match = pattern.search(payload)
        if match:
            idx = match.start()
            window = payload[max(0, idx - 60) : idx + 80].replace("\n", " ")
            leaks.append(f"{pattern.pattern!r} near …{window}…")
    if leaks:
        raise SystemExit(
            f"sanitizer would leak banned patterns into {path}: {leaks}"
        )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _sanitize_public_manifest_object(data)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _assert_no_public_leaks(path, payload)
    path.write_text(payload, encoding="utf-8")


def _replace_tool_count_text(text: str, count: int) -> str:
    # Generalize common public count shapes.  The original implementation
    # hard-coded 139 which silently drifted when later bumps landed.
    out = re.sub(r"\b\d+ tools\b", f"{count} tools", text)
    out = re.sub(r"\b\d+-tool MCP\b", f"{count}-tool MCP", out)
    out = re.sub(r"\bMCP tools\s*\(\d+\)", f"MCP tools ({count})", out)
    out = re.sub(r"\btools\s*\(\d+\)", f"tools ({count})", out)
    out = re.sub(r"\*\*\d+\s+個の MCP ツール\*\*", f"**{count} 個の MCP ツール**", out)
    return out


def _sanitize_public_description(text: str) -> str:
    """Remove public-manifest wording that exposes internal process details."""
    out = text
    for pattern, replacement in PUBLIC_DESCRIPTION_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    out = out.replace("schema-level", "source-linked")
    out = out.replace("row counts", "source coverage")
    out = out.replace("per-source row counts", "source coverage")
    out = out.replace("source tables:", "source coverage:")
    out = out.replace("Source tables:", "Source coverage:")
    out = out.replace("table is", "dataset is")
    out = out.replace("this table", "this dataset")
    out = out.replace("This table", "This dataset")
    out = out.replace("table records", "dataset records")
    out = out.replace("graph store", "relation graph")
    out = out.replace("workflow IDs", "usage-pattern metadata")
    out = out.replace("workflows", "usage patterns")
    out = out.replace("workflow", "usage pattern")
    out = out.replace("daily scheduled update", "regular source refresh")
    out = out.replace("scheduled update", "source refresh")
    out = out.replace("Fast-path", "Optimized flow")
    out = out.replace("private path", "published path")
    out = out.replace("cache", "stored result")
    return out


def _sanitize_public_manifest_object(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == "description" and isinstance(child, str):
                value[key] = _sanitize_public_description(child)
            else:
                _sanitize_public_manifest_object(child)
    elif isinstance(value, list):
        for child in value:
            _sanitize_public_manifest_object(child)


def _publisher_meta(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.setdefault("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["_meta"] = meta
    publisher = meta.setdefault("io.modelcontextprotocol.registry/publisher-provided", {})
    if not isinstance(publisher, dict):
        publisher = {}
        meta["io.modelcontextprotocol.registry/publisher-provided"] = publisher
    return publisher


def _sync_counts_and_transport(data: dict[str, Any], count: int) -> None:
    if isinstance(data.get("description"), str):
        data["description"] = _replace_tool_count_text(data["description"], count)

    transport_meta = mcp_transport_manifest_meta()
    transport_names = mcp_transport_names()

    if "transport" in data:
        data["transport"] = MCP_PRIMARY_TRANSPORT
    if "transports" in data:
        data["transports"] = transport_names

    for package in data.get("packages") or []:
        if isinstance(package, dict):
            transport = package.get("transport")
            if isinstance(transport, dict):
                transport["type"] = MCP_PRIMARY_TRANSPORT

    publisher = _publisher_meta(data)
    publisher["tool_count"] = count
    publisher.update(transport_meta)

    meta = data.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["tool_count"] = count
        meta.update(transport_meta)

    if isinstance(data.get("requirements"), dict):
        requirements = data["requirements"]
        if isinstance(requirements.get("tool_count"), int):
            requirements["tool_count"] = count
        for key in ("api_key", "api_key_doc"):
            if isinstance(requirements.get(key), str):
                requirements[key] = "https://jpcite.com/pricing.html"


def _sync_full_manifests(tools: list[dict[str, str]]) -> None:
    count = len(tools)
    for path in FULL_MANIFESTS:
        data = _read_json(path)
        data["name"] = "autonomath-mcp"
        data["tools"] = tools
        _sync_counts_and_transport(data, count)
        _write_json(path, data)


def _sync_subset_manifests(tool_by_name: dict[str, dict[str, str]], full_count: int) -> None:
    replacements = {
        "intel_risk_score": "program_risk_score_am",
    }
    for path in SUBSET_MANIFESTS:
        data = _read_json(path)
        if isinstance(data.get("description"), str):
            data["description"] = _replace_tool_count_text(data["description"], full_count)
        tools = data.get("tools")
        if isinstance(tools, list):
            synced: list[dict[str, str]] = []
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name")
                if not isinstance(name, str):
                    continue
                name = replacements.get(name, name)
                synced.append(
                    tool_by_name.get(
                        name, {"name": name, "description": tool.get("description", "")}
                    )
                )
            data["tools"] = synced
            _sync_counts_and_transport(data, len(synced))
        _write_json(path, data)


def _sync_server_manifests(count: int) -> None:
    for path in SERVER_MANIFESTS:
        data = _read_json(path)
        _sync_counts_and_transport(data, count)
        data["description"] = _replace_tool_count_text(str(data.get("description", "")), count)
        publisher = _publisher_meta(data)
        agent_routing = publisher.get("agent_routing")
        if isinstance(agent_routing, dict):
            agent_routing.pop("recurring_workflows", None)
            if isinstance(agent_routing.get("paid_activation_rule"), str):
                agent_routing["paid_activation_rule"] = (
                    "Use previewCost before broad paid runs; rerun with X-API-Key "
                    "after the anonymous daily trial."
                )
        equivalents = (
            agent_routing.get("mcp_equivalents")
            if isinstance(agent_routing, dict)
            else None
        )
        if (
            isinstance(equivalents, dict)
            and equivalents.get("company_baseline")
            in {
                "intel_houjin_full or dd_profile_am",
                "get_houjin_360_am or dd_profile_am",
            }
        ):
            equivalents["company_baseline"] = "createCompanyPublicBaseline"
        _write_json(path, data)


def _sync_docs(count: int) -> None:
    text = DOCS.read_text(encoding="utf-8")
    text = _replace_tool_count_text(text, count)
    text = text.replace("`intel_match`", "`match_due_diligence_questions`")
    text = text.replace("`intel_bundle_optimal`", "`portfolio_optimize_am`")
    text = text.replace("`intel_houjin_full`", "`get_houjin_360_am`")
    text = text.replace("## intel/match actionable fields", "## DD actionable fields")
    text = text.replace(
        "REST `/v1/intel/bundle/optimal`", "REST `/v1/intelligence/precomputed/query`"
    )
    text = text.replace("REST `/v1/intel/match`", "REST `/v1/intelligence/precomputed/query`")
    text = text.replace(
        "REST `/v1/intel/houjin/{houjin_id}/full`",
        "REST `/v1/artifacts/company_public_baseline`",
    )
    DOCS.write_text(text, encoding="utf-8")


def _llms_marker(count: int) -> str:
    return (
        f"MCP package: autonomath-mcp. Public MCP tools: {count}. "
        "Pricing: JPY 3 ex-tax per billable unit (about JPY 3.30 tax-included); "
        "anonymous usage is 3 requests/day/IP."
    )


def _upsert_llms_marker(text: str, count: int) -> str:
    marker = _llms_marker(count)
    lines = _replace_tool_count_text(text, count).splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("MCP package:"):
            lines[idx] = marker
            return "\n".join(lines).rstrip() + "\n"

    insert_at = 1 if lines else 0
    for idx, line in enumerate(lines):
        if line.startswith("Brand:") or line.startswith("Brand identity:"):
            insert_at = idx + 1
            break
    lines.insert(insert_at, marker)
    return "\n".join(lines).rstrip() + "\n"


def _sync_llms(count: int) -> None:
    for path in LLMS_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        path.write_text(_upsert_llms_marker(text, count), encoding="utf-8")


def main() -> int:
    tools = _runtime_tools()
    names = [tool["name"] for tool in tools]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise SystemExit(f"runtime tool names are not unique: {duplicates}")
    if any(name.startswith("intel_") for name in names):
        raise SystemExit("runtime still exposes stale intel_* tools")

    tool_by_name = {tool["name"]: tool for tool in tools}
    _sync_full_manifests(tools)
    _sync_subset_manifests(tool_by_name, len(tools))
    _sync_server_manifests(len(tools))
    _sync_docs(len(tools))
    _sync_llms(len(tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
