"""Record reader + multi-facet text extractor.

The JSONL records under /tmp/autonomath_data_collection_2026-04-23/ are
heterogeneous (per topic).  This module normalises any record into:

    canonical_id, metadata, facet_texts={tier_a, tier_b_*}

Empty facets are not emitted so the Tier B vector tables stay tight.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import (
    BATCH_RECORD_LIMIT,


    DATA_ROOT,
    TIER_A_MAX_CHARS,
    TIER_B_MAX_CHARS,
)


# --- AUTO: SCHEMA_GUARD_BLOCK (Wave 10 infra hardening) ---
import sys as _sg_sys
from pathlib import Path as _sg_Path
_sg_sys.path.insert(0, str(_sg_Path(__file__).resolve().parent.parent))
try:
    from scripts.schema_guard import assert_am_entities_schema as _sg_check
except Exception:  # pragma: no cover - schema_guard must exist in prod
    _sg_check = None
if __name__ == "__main__" and _sg_check is not None:
    _sg_check("/tmp/autonomath_infra_2026-04-24/autonomath.db")
# --- END SCHEMA_GUARD_BLOCK ---

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field name → facet bucket mapping.
# ---------------------------------------------------------------------------
ELIGIBILITY_KEYS = (
    "target_conditions",
    "target_types",
    "eligibility",
    "eligibility_clauses",
    "prerequisite",
    "applicable_businesses",
    "qualified_applicants",
    "eligible_industries",
)

EXCLUSION_KEYS = (
    "excluded_programs",
    "exclusions",
    "incompatible_programs",
    "restrictions",
    "condition",  # 03_exclusion_rules puts the exclusion text here
)

DEALBREAKER_KEYS = (
    "dealbreakers",
    "pitfalls",
    "revocation_conditions",
    "forfeiture",
    "penalty_conditions",
)

OBLIGATION_KEYS = (
    "obligations",
    "required_documents",
    "monitoring",
    "reporting",
    "post_grant_obligations",
    "joint_liability",
    "collateral_requirements",
    "security_required",
)

TIER_A_ID_KEYS = (
    "program_name",
    "program_name_a",
    "primary_name",
    "loan_program_name",
)

AUTHORITY_KEYS = (
    "authority",
    "authority_name",
    "provider",
    "issuing_ministry",
)

PREFECTURE_KEYS = ("prefecture", "region")

ACTIVE_KEYS = (
    "announced_date",
    "fetched_at",
    "valid_from",
    "active_from",
)


# ---------------------------------------------------------------------------
@dataclass
class NormalisedRecord:
    canonical_id: str
    topic_id: str
    primary_name: str
    authority_name: Optional[str]
    prefecture: Optional[str]
    tags: List[str] = field(default_factory=list)
    active_from: Optional[str] = None
    active_to: Optional[str] = None
    source_url: Optional[str] = None
    source_excerpt: Optional[str] = None
    target_entity: Optional[str] = None
    record_json: str = ""
    facet_texts: Dict[str, str] = field(default_factory=dict)
    content_hash: str = ""


def _as_text(value: Any) -> str:
    """Coerce any JSON value into a flat string; None → ''."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_as_text(v) for v in value]
        return "; ".join(p for p in parts if p)
    if isinstance(value, dict):
        # Prefer 'text' / 'name' keys if present (enriched_json style)
        for k in ("text", "name", "label", "value"):
            if k in value:
                return _as_text(value[k])
        return "; ".join(f"{k}={_as_text(v)}" for k, v in value.items() if v)
    return str(value)


def _first_nonempty(rec: dict, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k in rec:
            t = _as_text(rec[k])
            if t:
                return t
    return None


def _collect_texts(rec: dict, keys: tuple[str, ...]) -> List[str]:
    out: List[str] = []
    for k in keys:
        if k in rec:
            t = _as_text(rec[k])
            if t:
                out.append(t)
    return out


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_canonical_id(topic_id: str, rec: dict, idx: int) -> str:
    """Stable ID per (topic, record).  Prefers program_name + round_label."""
    name = _first_nonempty(rec, TIER_A_ID_KEYS) or ""
    round_lbl = _as_text(rec.get("round_label") or rec.get("sub_type") or "")
    basis = f"{topic_id}|{name}|{round_lbl}|{idx}"
    h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"{topic_id}::{h}"


def normalise(topic_id: str, rec: dict, idx: int) -> NormalisedRecord:
    """Convert a raw record dict to a NormalisedRecord with facet texts."""
    primary_name = _first_nonempty(rec, TIER_A_ID_KEYS) or "(unnamed)"
    authority = _first_nonempty(rec, AUTHORITY_KEYS)
    prefecture = _first_nonempty(rec, PREFECTURE_KEYS)
    source_url = _as_text(
        rec.get("source_url") or rec.get("official_url") or rec.get("form_url_direct")
    ) or None
    source_excerpt = _as_text(rec.get("source_excerpt")) or None
    target_entity = _first_nonempty(
        rec,
        ("target_entity", "target_types", "applicable_businesses"),
    )

    # --- Tier A: full-record text -------------------------------------
    tier_a_parts = [primary_name]
    if authority:
        tier_a_parts.append(f"実施機関: {authority}")
    if prefecture:
        tier_a_parts.append(f"地域: {prefecture}")
    if source_excerpt:
        tier_a_parts.append(source_excerpt)
    if target_entity and target_entity not in tier_a_parts:
        tier_a_parts.append(f"対象: {target_entity}")
    # Also append any obvious money / rate fields for signal.
    for k in (
        "amount_max_man_yen",
        "amount_max_yen",
        "amount_daily_max_yen",
        "subsidy_rate",
        "interest_rate_base_annual",
    ):
        if rec.get(k):
            tier_a_parts.append(f"{k}={_as_text(rec[k])}")

    tier_a_text = _truncate("\n".join(p for p in tier_a_parts if p), TIER_A_MAX_CHARS)

    # --- Tier B facets -------------------------------------------------
    eligibility_parts = _collect_texts(rec, ELIGIBILITY_KEYS)
    exclusion_parts = _collect_texts(rec, EXCLUSION_KEYS)
    dealbreaker_parts = _collect_texts(rec, DEALBREAKER_KEYS)
    obligation_parts = _collect_texts(rec, OBLIGATION_KEYS)

    facet_texts: Dict[str, str] = {"tier_a": tier_a_text}
    if eligibility_parts:
        facet_texts["tier_b_eligibility"] = _truncate(
            " / ".join(eligibility_parts), TIER_B_MAX_CHARS
        )
    if exclusion_parts:
        facet_texts["tier_b_exclusions"] = _truncate(
            " / ".join(exclusion_parts), TIER_B_MAX_CHARS
        )
    if dealbreaker_parts:
        facet_texts["tier_b_dealbreakers"] = _truncate(
            " / ".join(dealbreaker_parts), TIER_B_MAX_CHARS
        )
    if obligation_parts:
        facet_texts["tier_b_obligations"] = _truncate(
            " / ".join(obligation_parts), TIER_B_MAX_CHARS
        )

    # --- misc metadata -------------------------------------------------
    tags: List[str] = [topic_id]
    for k in ("category", "program_kind", "authority_level", "loan_type"):
        v = _as_text(rec.get(k))
        if v:
            tags.append(v)

    active_from = _first_nonempty(rec, ACTIVE_KEYS)

    record_json = json.dumps(rec, ensure_ascii=False)
    content_hash = hashlib.sha256(tier_a_text.encode("utf-8")).hexdigest()
    canonical_id = build_canonical_id(topic_id, rec, idx)

    return NormalisedRecord(
        canonical_id=canonical_id,
        topic_id=topic_id,
        primary_name=primary_name,
        authority_name=authority,
        prefecture=prefecture,
        tags=tags,
        active_from=active_from,
        active_to=None,
        source_url=source_url,
        source_excerpt=source_excerpt,
        target_entity=target_entity,
        record_json=record_json,
        facet_texts=facet_texts,
        content_hash=content_hash,
    )


# ---------------------------------------------------------------------------
def iter_topic_records(
    topic_dir: Path, *, limit: Optional[int] = None
) -> Iterator[NormalisedRecord]:
    topic_id = topic_dir.name
    jsonl = topic_dir / "records.jsonl"
    if not jsonl.exists():
        return
    seen = 0
    with jsonl.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("bad JSON in %s line %d: %s", jsonl, idx + 1, exc)
                continue
            yield normalise(topic_id, rec, idx)
            seen += 1
            if limit is not None and seen >= limit:
                return


def iter_all_records(
    *,
    data_root: Path = DATA_ROOT,
    total_limit: int = BATCH_RECORD_LIMIT,
    per_topic_cap: Optional[int] = None,
) -> Iterator[NormalisedRecord]:
    """Yield up to `total_limit` normalised records, round-robin-ish by topic.

    We walk topic dirs in lexical order and take up to `per_topic_cap` from
    each (or their full content if None), short-circuiting once total_limit
    is reached.
    """
    topics = sorted(p for p in data_root.iterdir() if p.is_dir())
    emitted = 0
    for topic_dir in topics:
        if emitted >= total_limit:
            return
        remaining = total_limit - emitted
        cap = min(per_topic_cap or remaining, remaining)
        for rec in iter_topic_records(topic_dir, limit=cap):
            yield rec
            emitted += 1
            if emitted >= total_limit:
                return
