"""Cohort persona kit MCP resources.

Ships 8 cohort-specific persona kits as MCP `resources/list` entries so that
an AI agent connecting to jpcite-mcp can issue
``read_resource("autonomath://cohort/<slug>.yaml")`` once and obtain the
cohort-tailored system prompt, few-shot queries, tool routing, and the
business-law disclaimer envelope. Resources count moves 28 -> 36.

Key invariants:
  * Pure Python — yaml.safe_load + dict assembly only. No LLM calls.
    The CI guard ``tests/test_no_llm_in_production.py`` enforces this.
  * 8 yaml files live under ``data/autonomath_static/cohorts/`` plus
    ``index.json`` (1 cohort_index).
  * Bilingual JP/EN — each yaml carries ``system_prompt_template`` (JP)
    and optionally ``system_prompt_template_en`` (EN). ``persona_for_cohort
    (cohort_id, lang="ja")`` returns the corresponding string; "en" falls
    back to JP if EN is missing so callers never get an empty prompt.
  * Customer customization — when a ``client_profile`` row carries a
    non-null ``cohort_kit_yaml`` (mig 096 ALTER), ``persona_for_cohort``
    overlays it on top of the SOT kit (deep merge). The personalized kit
    is reachable via ``read_personalized_resource(api_key, cohort_id)``.
  * Tool name "jpcite" is canonical user-facing brand; "jpintel_mcp" is
    the legacy internal package path retained for import-path stability.

Wired into ``register_cohort_resources(mcp)`` — call from server.py
during bootstrap. The function is idempotent (skips on AttributeError if
FastMCP version lacks ``.resource()``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jpintel_mcp._jpcite_env_bridge import get_flag

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]

_STATIC_DIR = Path(
    os.environ.get(
        "AUTONOMATH_STATIC_DIR",
        "/data/autonomath_static"
        if Path("/data/autonomath_static").exists()
        else str(_REPO_ROOT / "data" / "autonomath_static"),
    )
)
_COHORT_DIR = _STATIC_DIR / "cohorts"

_INDEX_FILE = _COHORT_DIR / "index.json"

# Canonical 8 cohorts shipped at v0.3.5. Order matches index.json.
COHORT_SLUGS: tuple[str, ...] = (
    "tax_advisor",
    "kaikeishi",
    "shihoshoshi",
    "subsidy_consultant",
    "ma_dd",
    "foreign_fdi",
    "smb_line",
    "industry_pack",
)

# Required schema keys per cohort yaml.
REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "cohort",
        "cohort_id",
        "business_law",
        "forbidden_phrases",
        "system_prompt_template",
        "few_shot_queries",
        "tool_routing",
        "disclaimer_envelope",
    }
)

# Forbidden tokens that the kit prompt itself must never invite. CI test
# asserts every kit's `forbidden_phrases` lists these (DEEP-23 sync).
GLOBAL_FORBIDDEN_BASE: tuple[str, ...] = ("推測", "予測", "保証")


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a yaml file. PyYAML is a transitive dep (already used in self_improve)."""
    import yaml  # type: ignore[import-untyped,unused-ignore]  # local import keeps top-level import safe

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"yaml at {path} did not parse as a mapping")
    return data


def _slug_to_path(slug: str) -> Path:
    """Resolve a cohort slug to its yaml path. KeyError if unknown."""
    if slug not in COHORT_SLUGS:
        raise KeyError(f"unknown cohort slug: {slug}; available: {sorted(COHORT_SLUGS)}")
    return _COHORT_DIR / f"cohort_{slug}.yaml"


# Cache: file mtime → parsed dict. Reload on mtime change so dev reload works,
# prod is a fixed image so the cache effectively freezes.
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _load_cohort_kit(slug: str) -> dict[str, Any]:
    """Load and cache a single cohort kit, reloading if the file mtime moved."""
    path = _slug_to_path(slug)
    if not path.exists():
        raise KeyError(f"cohort yaml not found: {path}")
    mtime = path.stat().st_mtime
    cached = _CACHE.get(slug)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = _load_yaml(path)
    _CACHE[slug] = (mtime, data)
    return data


def _cohort_id_to_slug() -> dict[str, str]:
    """Build cohort_id → slug map (e.g. 'tax_pro' → 'tax_advisor')."""
    out: dict[str, str] = {}
    for slug in COHORT_SLUGS:
        try:
            kit = _load_cohort_kit(slug)
        except Exception:
            continue
        cid = kit.get("cohort_id")
        if isinstance(cid, str) and cid:
            out[cid] = slug
    return out


# ---------------------------------------------------------------------------
# Public API: persona_for_cohort
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemPrompt:
    """Bundle returned by `persona_for_cohort`. Pure data, no LLM calls."""

    cohort: str
    cohort_id: str
    business_law: str
    lang: str
    system_prompt: str
    forbidden_phrases: tuple[str, ...]
    few_shot_queries: tuple[dict[str, Any], ...]
    tool_routing: tuple[dict[str, Any], ...]
    disclaimer_envelope: dict[str, Any]
    source: str  # "common" or "personalized"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort": self.cohort,
            "cohort_id": self.cohort_id,
            "business_law": self.business_law,
            "lang": self.lang,
            "system_prompt": self.system_prompt,
            "forbidden_phrases": list(self.forbidden_phrases),
            "few_shot_queries": list(self.few_shot_queries),
            "tool_routing": list(self.tool_routing),
            "disclaimer_envelope": dict(self.disclaimer_envelope),
            "source": self.source,
        }


def _prompt_for_lang(kit: dict[str, Any], lang: str) -> str:
    """Return ``system_prompt_template[_en]`` based on lang, JP fallback."""
    if lang == "en":
        en = kit.get("system_prompt_template_en")
        if isinstance(en, str) and en.strip():
            return en
    jp = kit.get("system_prompt_template", "")
    return jp if isinstance(jp, str) else ""


def _merge_forbidden(local: list[Any] | tuple[Any, ...] | None) -> tuple[str, ...]:
    """Merge local kit's forbidden_phrases with the global base. De-dup, preserve order."""
    seen: dict[str, None] = {}
    if isinstance(local, (list, tuple)):
        for item in local:
            if isinstance(item, str) and item:
                seen.setdefault(item, None)
    for item in GLOBAL_FORBIDDEN_BASE:
        seen.setdefault(item, None)
    return tuple(seen.keys())


def persona_for_cohort(
    cohort_id: str,
    lang: str = "ja",
    *,
    customization: dict[str, Any] | None = None,
) -> SystemPrompt:
    """Return the SystemPrompt for a cohort_id (e.g. 'tax_pro' / 'cpa').

    Args:
      cohort_id: discriminator value used by DEEP-29 ROUTING (tax_pro / cpa /
        judicial / admin / lawyer / foreign_fdi / smb_line / industry_pack).
      lang: 'ja' or 'en'. EN falls back to JP when ``system_prompt_template_en``
        is missing.
      customization: optional dict overlay (e.g. mig 096 ``cohort_kit_yaml``).
        Top-level keys overwrite the SOT kit; this is intentional so customers
        can patch ``forbidden_phrases`` / ``tool_routing`` / etc. The
        ``disclaimer_envelope`` field is never customer-overridable (server-side
        sensitive-tool branches enforce the original envelope regardless of
        what the kit declares).

    Raises:
      KeyError: if cohort_id is unknown.
    """
    slug_map = _cohort_id_to_slug()
    if cohort_id not in slug_map:
        raise KeyError(f"unknown cohort_id: {cohort_id}; available: {sorted(slug_map.keys())}")
    kit = dict(_load_cohort_kit(slug_map[cohort_id]))
    source = "common"
    if customization:
        # Customer overlay — overwrite top-level keys, but never disclaimer_envelope.
        for k, v in customization.items():
            if k == "disclaimer_envelope":
                continue
            kit[k] = v
        source = "personalized"

    return SystemPrompt(
        cohort=str(kit.get("cohort", "")),
        cohort_id=str(kit.get("cohort_id", cohort_id)),
        business_law=str(kit.get("business_law", "")),
        lang=lang,
        system_prompt=_prompt_for_lang(kit, lang),
        forbidden_phrases=_merge_forbidden(kit.get("forbidden_phrases")),
        few_shot_queries=tuple(kit.get("few_shot_queries") or ()),
        tool_routing=tuple(kit.get("tool_routing") or ()),
        disclaimer_envelope=dict(kit.get("disclaimer_envelope") or {}),
        source=source,
    )


# ---------------------------------------------------------------------------
# Resource registry — list_resources() / read_resource() helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CohortResourceMeta:
    uri: str
    name: str
    description: str
    mime_type: str = "application/yaml"
    update_frequency: str = "static"


def _kit_resource_meta(slug: str) -> CohortResourceMeta:
    try:
        kit = _load_cohort_kit(slug)
    except Exception:
        return CohortResourceMeta(
            uri=f"autonomath://cohort/{slug}.yaml",
            name=f"Cohort: {slug}",
            description="(yaml load failed)",
        )
    cohort = kit.get("cohort", slug)
    fence = kit.get("business_law", "(no fence)")
    return CohortResourceMeta(
        uri=f"autonomath://cohort/{slug}.yaml",
        name=f"Cohort kit: {cohort}",
        description=f"Cohort persona kit for {cohort} ({fence}). System prompt + few-shot + tool_routing + disclaimer envelope.",
    )


def _index_resource_meta() -> CohortResourceMeta:
    return CohortResourceMeta(
        uri="autonomath://cohort/index.json",
        name="Cohort kit index (8 cohorts)",
        description="Cohort kit meta. 8 slugs + 1 line description + version.",
        mime_type="application/json",
    )


def list_cohort_resources() -> list[dict[str, str]]:
    """Resource list payload — 8 kits + 1 cohort_index = 9 entries."""
    out: list[dict[str, str]] = []
    for slug in COHORT_SLUGS:
        m = _kit_resource_meta(slug)
        out.append(
            {
                "uri": m.uri,
                "name": m.name,
                "description": m.description,
                "mimeType": m.mime_type,
                "updateFrequency": m.update_frequency,
            }
        )
    idx = _index_resource_meta()
    out.append(
        {
            "uri": idx.uri,
            "name": idx.name,
            "description": idx.description,
            "mimeType": idx.mime_type,
            "updateFrequency": idx.update_frequency,
        }
    )
    return out


def read_cohort_resource(uri: str) -> dict[str, Any]:
    """Return MCP `resources/read` payload for one URI. Raises KeyError on miss."""
    if uri == "autonomath://cohort/index.json":
        if not _INDEX_FILE.exists():
            raise KeyError(f"cohort index not on disk: {_INDEX_FILE}")
        text = _INDEX_FILE.read_text(encoding="utf-8")
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
    # cohort kit yaml
    prefix = "autonomath://cohort/"
    if not uri.startswith(prefix) or not uri.endswith(".yaml"):
        raise KeyError(f"unknown cohort resource URI: {uri}")
    slug = uri[len(prefix) : -len(".yaml")]
    path = _slug_to_path(slug)
    if not path.exists():
        raise KeyError(f"cohort yaml missing: {path}")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/yaml",
                "text": path.read_text(encoding="utf-8"),
            }
        ]
    }


def get_cohort_index() -> dict[str, Any]:
    """Return the parsed index.json payload (8 cohort meta + version)."""
    if not _INDEX_FILE.exists():
        raise KeyError(f"cohort index not on disk: {_INDEX_FILE}")
    with _INDEX_FILE.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Personalized kit (mig 096 ``cohort_kit_yaml`` overlay)
# ---------------------------------------------------------------------------


def _resolve_personalized_overlay(api_key: str | None) -> dict[str, Any] | None:
    """If the API key resolves to a client_profile row with non-null
    ``cohort_kit_yaml`` (mig 096 ALTER 1 行), return the parsed overlay dict.
    Otherwise None. Pure read; never raises.
    """
    if not api_key:
        return None
    try:
        import sqlite3

        # jpintel.db carries client_profiles per CLAUDE.md (mig 096).
        db_path = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH") or str(_REPO_ROOT / "data" / "jpintel.db")
        if not Path(db_path).exists():
            return None
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0) as conn:
            cur = conn.execute(
                "SELECT cohort_kit_yaml FROM client_profiles WHERE api_key = ? LIMIT 1",
                (api_key,),
            )
            row = cur.fetchone()
        if not row:
            return None
        raw = row[0]
        if not raw:
            return None
        import yaml

        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def read_personalized_resource(
    api_key: str | None, cohort_id: str, lang: str = "ja"
) -> SystemPrompt:
    """Return the personalized SystemPrompt if the API key carries an overlay,
    otherwise the common SOT kit. The disclaimer_envelope is never overlaid.
    """
    overlay = _resolve_personalized_overlay(api_key)
    return persona_for_cohort(cohort_id, lang=lang, customization=overlay)


# ---------------------------------------------------------------------------
# FastMCP wiring (called from server.py at bootstrap)
# ---------------------------------------------------------------------------


def register_cohort_resources(mcp: Any) -> None:
    """Register the 8 cohort kits + cohort_index with a FastMCP instance.

    Idempotent on FastMCP versions that lack `.resource()` (older builds).
    """
    try:
        for slug in COHORT_SLUGS:
            m = _kit_resource_meta(slug)
            uri = m.uri
            path = _slug_to_path(slug)

            def _make_yaml_cb(p: Path) -> Callable[[], str]:
                def _cb() -> str:
                    return p.read_text(encoding="utf-8") if p.exists() else ""

                return _cb

            mcp.resource(
                uri,
                name=m.name,
                description=m.description,
                mime_type=m.mime_type,
            )(_make_yaml_cb(path))

        idx = _index_resource_meta()

        def _index_cb() -> str:
            return _INDEX_FILE.read_text(encoding="utf-8") if _INDEX_FILE.exists() else "{}"

        mcp.resource(
            idx.uri,
            name=idx.name,
            description=idx.description,
            mime_type=idx.mime_type,
        )(_index_cb)
    except AttributeError:
        # FastMCP version without .resource() — skip cleanly.
        pass


__all__ = [
    "COHORT_SLUGS",
    "REQUIRED_KEYS",
    "GLOBAL_FORBIDDEN_BASE",
    "SystemPrompt",
    "CohortResourceMeta",
    "persona_for_cohort",
    "list_cohort_resources",
    "read_cohort_resource",
    "get_cohort_index",
    "read_personalized_resource",
    "register_cohort_resources",
]
