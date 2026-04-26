"""AutonoMath embedding configuration.

Model + dimension + DB paths are centralised here so schema.sql and
generate.py/search.py agree on the vector width.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
# Spec asked for cl-nagoya/ruri-v3-310m (768d) but its safetensors weights are
# ~1.26 GB, well above the 500 MB hard cap in the task.  Fallback path picked:
#
#   intfloat/multilingual-e5-small -- 471 MB safetensors, 384d, JA-capable
#
# `EMBED_DIM` is therefore 384, not 768.  If a larger model is later wired in,
# change MODEL + EMBED_DIM together and re-run schema.sql on a fresh DB.



PRIMARY_MODEL = "cl-nagoya/ruri-v3-310m"  # 768d, too large (1258 MB)
FALLBACK_MODEL = "intfloat/multilingual-e5-small"  # 384d, 471 MB
STUB_MODEL = "stub-random-384"  # deterministic random if no network

DEFAULT_MODEL = os.environ.get("AUTONOMATH_EMBED_MODEL", FALLBACK_MODEL)
EMBED_DIM = int(os.environ.get("AUTONOMATH_EMBED_DIM", "384"))

# e5-family models expect 'query: ' / 'passage: ' prefixes.
MODEL_PREFIX_QUERY = "query: " if "e5" in DEFAULT_MODEL.lower() else ""
MODEL_PREFIX_PASSAGE = "passage: " if "e5" in DEFAULT_MODEL.lower() else ""

# ---------------------------------------------------------------------------
# DB paths
# ---------------------------------------------------------------------------
# autonomath.db lives at the repo root alongside data/jpintel.db.
PACKAGE_ROOT = Path(__file__).resolve().parent
# src/jpintel_mcp/embedding/ -> repo root is 3 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(os.environ.get(
    "AUTONOMATH_DB_PATH",
    os.environ.get("AUTONOMATH_DB", str(_REPO_ROOT / "autonomath.db")),
))
SCHEMA_PATH = PACKAGE_ROOT / "schema.sql"

# ---------------------------------------------------------------------------
# Tier definition (drives generate.py + schema.sql + search.py)
# ---------------------------------------------------------------------------
# Tier A = record-level (primary_name + source_excerpt + target/entity).
# Tier B = 4 facets.  Each facet is skipped if its source fields are empty.
TIERS: dict[str, dict] = {
    "tier_a": {
        "table": "am_vec_tier_a",
        "description": "record-level: primary_name + source_excerpt + target_entity",
    },
    "tier_b_eligibility": {
        "table": "am_vec_tier_b_eligibility",
        "description": "facet: target / conditions / prerequisite",
    },
    "tier_b_exclusions": {
        "table": "am_vec_tier_b_exclusions",
        "description": "facet: incompatible / restrictions",
    },
    "tier_b_dealbreakers": {
        "table": "am_vec_tier_b_dealbreakers",
        "description": "facet: dealbreakers / 事後失効条件",
    },
    "tier_b_obligations": {
        "table": "am_vec_tier_b_obligations",
        "description": "facet: 報告義務 / 連帯保証 / monitoring",
    },
}

# ---------------------------------------------------------------------------
# Input data
# ---------------------------------------------------------------------------
DATA_ROOT = Path(
    os.environ.get(
        "AUTONOMATH_DATA_ROOT",
        "/tmp/autonomath_data_collection_2026-04-23",
    )
)

# Hard cap per task spec: first 1,000 records for batch smoke run.
BATCH_RECORD_LIMIT = int(os.environ.get("AUTONOMATH_BATCH_LIMIT", "1000"))

# Tier A excerpt truncation (design doc §2.2 Tier A: 1,500 chars).
TIER_A_MAX_CHARS = 1_500
TIER_B_MAX_CHARS = 1_000
