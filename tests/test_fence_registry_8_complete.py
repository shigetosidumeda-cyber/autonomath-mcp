"""Wave 46 — fence_registry 8-業法 完備 verify.

Background
----------
`audit_runner_agent_journey.py` step 2 (Evaluation) checks 8 specific
業法 entries inside `data/fence_registry.json`. Until Wave 46 the registry
had 5 substring matches (sharoushi was stored as the short form 社労士法
which does not match 社会保険労務士法), plus 公認会計士法 and 労働基準法
were entirely missing. This test pins the 8-of-8 invariant so future
edits cannot silently regress Journey step 2 below 10.0.

Per `feedback_no_operator_llm_api`: pure stdlib, no network, no LLM. The
test inspects the registry JSON on disk and validates the schema
required by Journey audit (substring presence) plus the schema declared
by the Wave 46 PR (statute_id / jurisdiction / scope_negative / fence_type
/ license_required / surface_text / source_url).

Acceptance
----------
1. registry parses + ≥ 8 entries
2. each of the 8 canonical 業法 strings appears as a substring inside the
   serialized JSON blob (matches the audit runner exactly)
3. each fence has the Wave 46 schema fields (or backwards-compatible
   aliases) — id/law/article/scope_negative/fence_type/license_required/
   surface_text/source_url
4. surface_text is non-empty + ≥ 30 chars (i.e. an actual statute quote,
   not a placeholder)
5. source_url points to e-Gov / METI (no aggregator)
"""

from __future__ import annotations

import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FENCE_PATH = REPO_ROOT / "data" / "fence_registry.json"

EIGHT_BUSINESS_LAW_FENCES = (
    "税理士法",
    "弁護士法",
    "司法書士法",
    "行政書士法",
    "社会保険労務士法",
    "公認会計士法",
    "弁理士法",
    "労働基準法",
)

REQUIRED_FIELDS = (
    "id",
    "law",
    "article",
    "scope_negative",
    "fence_type",
    "license_required",
    "surface_text",
    "source_url",
)

ALLOWED_SOURCE_HOSTS = (
    "elaws.e-gov.go.jp",
    "www.meti.go.jp",
    "meti.go.jp",
)


def _load_registry() -> dict:
    assert FENCE_PATH.exists(), f"fence_registry.json missing at {FENCE_PATH}"
    return json.loads(FENCE_PATH.read_text(encoding="utf-8"))


def test_registry_loads_with_eight_or_more_fences() -> None:
    reg = _load_registry()
    assert "fences" in reg, "registry must have top-level 'fences' array"
    fences = reg["fences"]
    assert isinstance(fences, list), "fences must be a list"
    assert len(fences) >= 8, (
        f"Wave 46 requires ≥ 8 fences (got {len(fences)}). "
        "8 業法 = 税理士法 + 弁護士法 + 司法書士法 + 行政書士法 + "
        "社会保険労務士法 + 公認会計士法 + 弁理士法 + 労働基準法"
    )


def test_all_eight_business_laws_present_as_substring() -> None:
    """Mirrors the audit_runner_agent_journey.py step 2 substring check."""
    reg = _load_registry()
    blob = json.dumps(reg, ensure_ascii=False)
    missing: list[str] = []
    for law in EIGHT_BUSINESS_LAW_FENCES:
        if law not in blob:
            missing.append(law)
    assert not missing, (
        f"fence_registry missing 8業法 substring(s): {missing}. "
        "audit_runner_agent_journey.py step 2 will deduct."
    )


def test_each_fence_has_wave46_schema_fields() -> None:
    reg = _load_registry()
    defects: list[str] = []
    for fence in reg["fences"]:
        fid = fence.get("id", "<no-id>")
        for field in REQUIRED_FIELDS:
            if field not in fence:
                defects.append(f"{fid} missing {field}")
            elif not fence[field]:
                defects.append(f"{fid} empty {field}")
    assert not defects, f"Wave 46 schema requires {REQUIRED_FIELDS}; defects: {defects[:20]}"


def test_surface_text_is_real_statute_quote() -> None:
    """surface_text must be a non-trivial quotation (≥ 30 chars)."""
    reg = _load_registry()
    defects: list[str] = []
    for fence in reg["fences"]:
        fid = fence.get("id", "<no-id>")
        st = fence.get("surface_text", "")
        if len(st) < 30:
            defects.append(f"{fid} surface_text too short ({len(st)} chars)")
        # placeholder smell
        if any(tok in st.lower() for tok in ("todo", "placeholder", "tbd", "xxx")):
            defects.append(f"{fid} surface_text has placeholder token")
    assert not defects, f"surface_text defects: {defects}"


def test_source_url_points_to_primary_source() -> None:
    reg = _load_registry()
    defects: list[str] = []
    host_pat = re.compile(r"https?://([^/]+)/")
    for fence in reg["fences"]:
        fid = fence.get("id", "<no-id>")
        url = fence.get("source_url", "")
        m = host_pat.match(url + "/")
        host = m.group(1) if m else ""
        if host not in ALLOWED_SOURCE_HOSTS:
            defects.append(f"{fid} source_url host={host!r} not in allow-list")
    assert not defects, f"source_url must be primary source (e-Gov / METI): {defects}"


def test_three_new_wave46_fences_added() -> None:
    """The Wave 46 deliverable: sharoushi + cpa + labor_standards."""
    reg = _load_registry()
    ids = {f.get("id") for f in reg["fences"]}
    assert "sharoushi" in ids, "sharoushi (社会保険労務士法 §27) must be present"
    assert "cpa" in ids, "cpa (公認会計士法 §47条の2) must be present"
    assert "labor_standards" in ids, "labor_standards (労働基準法 §12+§32+§36) must be present"

    # sharoushi.law must be the canonical full form
    sharoushi = next(f for f in reg["fences"] if f["id"] == "sharoushi")
    assert sharoushi["law"] == "社会保険労務士法", (
        "sharoushi.law must be the canonical full form 社会保険労務士法 "
        f"(got {sharoushi['law']!r}). Short form 社労士法 fails Journey audit substring."
    )

    cpa = next(f for f in reg["fences"] if f["id"] == "cpa")
    assert cpa["law"] == "公認会計士法"
    assert "§47条の2" in cpa["article"]

    rouki = next(f for f in reg["fences"] if f["id"] == "labor_standards")
    assert rouki["law"] == "労働基準法"
    # §32 (40h/week) + §36 (kyoutei) surfaces must appear in surface_text
    assert (
        "三十六" in rouki["surface_text"]
        or "36" in rouki["surface_text"]
        or "三十二" in rouki["surface_text"]
    )


def test_no_existing_five_fences_were_deleted() -> None:
    """Wave 46 禁止: 既存 5 fence 削除. Sanity check the legacy ids still ship."""
    reg = _load_registry()
    ids = {f.get("id") for f in reg["fences"]}
    legacy = {
        "tax_accountant",
        "lawyer",
        "judicial_scrivener",
        "administrative_scrivener",
        "patent_attorney",
    }
    missing = legacy - ids
    assert not missing, f"Legacy fences were deleted (禁止): {missing}"


def test_journey_audit_step2_score_is_full() -> None:
    """Integration: run the journey audit and assert step 2 ≥ 9.5 / 10.

    Invoked as a subprocess so dataclass module registration works correctly
    (importlib.util.spec_from_file_location leaves __module__ unregistered,
    which dataclasses chokes on under Python 3.13).
    """
    import subprocess
    import sys
    import tempfile

    audit_path = REPO_ROOT / "scripts" / "ops" / "audit_runner_agent_journey.py"
    if not audit_path.exists():
        # Audit script not in repo — skip gracefully (not all checkouts ship scripts/)
        return

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_json = tf.name
    result = subprocess.run(
        [sys.executable, str(audit_path), "--out-json", out_json],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"audit_runner_agent_journey.py exited {result.returncode}: stderr={result.stderr[-500:]}"
    )
    data = json.loads(pathlib.Path(out_json).read_text(encoding="utf-8"))
    step2 = next(s for s in data["steps"] if s["step"] == 2)
    assert step2["score"] >= 9.5, (
        f"Wave 46 target: Journey step 2 ≥ 9.5 (got {step2['score']}). "
        f"findings={step2['findings']}, failure={step2.get('failure_patterns', [])}"
    )
