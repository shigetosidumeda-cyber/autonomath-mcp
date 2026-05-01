"""Static resource access for curated jpcite taxonomies."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STATIC_DIR = REPO_ROOT / "data" / "autonomath_static"
EXAMPLE_DIR = STATIC_DIR / "example_profiles"

_STATIC_RESOURCES = {
    "seido": "seido.json",
    "glossary": "glossary.json",
    "money_types": "money_types.json",
    "obligations": "obligations.json",
    "dealbreakers": "dealbreakers.json",
    "sector_combos": "sector_combos.json",
    "crop_library": "agri/crop_library.json",
    "exclusion_rules": "agri/exclusion_rules.json",
}

_EXAMPLE_PROFILES = {
    "ichigo_20a": "A_ichigo_20a.json",
    "rice_200a": "D_rice_200a.json",
    "new_corp": "J_new_corp.json",
    "dairy_100head": "Q_dairy_100head.json",
    "minimal": "N_minimal.json",
}

class ResourceNotFoundError(KeyError):
    pass

@lru_cache(maxsize=16)
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

def list_static_resources() -> list[dict[str, object]]:
    """Return manifest of all available static resources."""
    return [
        {
            "id": rid,
            "filename": Path(fname).name,
            "path_relative": f"jpcite/static/{rid}",
            "size_bytes": (STATIC_DIR / fname).stat().st_size,
        }
        for rid, fname in _STATIC_RESOURCES.items()
        if (STATIC_DIR / fname).exists()
    ]

def get_static_resource(resource_id: str) -> dict[str, object]:
    """Load a static taxonomy/lookup file by id. Returns full JSON content + metadata."""
    if resource_id not in _STATIC_RESOURCES:
        raise ResourceNotFoundError(f"unknown resource: {resource_id}; available: {sorted(_STATIC_RESOURCES)}")
    path = STATIC_DIR / _STATIC_RESOURCES[resource_id]
    if not path.exists():
        raise ResourceNotFoundError(f"resource file missing on disk: {path}")
    return {
        "id": resource_id,
        "data": _load_json(path),
        "license": "Available as part of jpcite API responses; verify primary-source terms for downstream redistribution.",
        "source_origin": "jpcite reference data",
    }

def list_example_profiles() -> list[dict[str, object]]:
    """Return list of canonical example client profiles for documentation purposes."""
    return [
        {
            "id": pid,
            "filename": fname,
            "size_bytes": (EXAMPLE_DIR / fname).stat().st_size,
        }
        for pid, fname in _EXAMPLE_PROFILES.items()
        if (EXAMPLE_DIR / fname).exists()
    ]

def get_example_profile(profile_id: str) -> dict[str, object]:
    """Return one canonical client profile JSON as a complete-payload example."""
    if profile_id not in _EXAMPLE_PROFILES:
        raise ResourceNotFoundError(f"unknown profile: {profile_id}; available: {sorted(_EXAMPLE_PROFILES)}")
    path = EXAMPLE_DIR / _EXAMPLE_PROFILES[profile_id]
    if not path.exists():
        raise ResourceNotFoundError(f"profile file missing: {path}")
    return {
        "id": profile_id,
        "profile": _load_json(path),
        "license": "Public example data for jpcite. No real PII.",
        "purpose": "Reference shape for a complete client intake payload.",
    }
