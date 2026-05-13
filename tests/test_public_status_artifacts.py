from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_STATUS = REPO_ROOT / "site" / "status"
HEADERS_FILE = REPO_ROOT / "site" / "_headers"
AX_STATUS_FILES = (
    SITE_STATUS / "ax_4pillars.json",
    SITE_STATUS / "ax_5pillars.json",
)

STATUS_JSON_REF_RE = re.compile(r"""["'](/status/[^"']+?\.json)["']""")
PUBLIC_LEAK_PATTERNS = (
    re.compile(r"\bmrr_jpy\b", re.IGNORECASE),
    re.compile(r"\barr_jpy\b", re.IGNORECASE),
    re.compile(r"\bltv_cac\b", re.IGNORECASE),
    re.compile(r"\bchurn_d30\b", re.IGNORECASE),
    re.compile(r"\basr_24h\b", re.IGNORECASE),
    re.compile(r"\bcost_to_serve\b", re.IGNORECASE),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bapi_keys\b"),
    re.compile(r"\bcost_ledger\b"),
    re.compile(r"\baeo_citation_bench\b"),
    re.compile(r"\b(?:jpintel|autonomath)\.db\b", re.IGNORECASE),
    re.compile(r"\bROI\b"),
    re.compile(r"\bARR\b"),
    re.compile(r"\bWave\s+\d", re.IGNORECASE),
    re.compile(r"\bmigration\s+\d", re.IGNORECASE),
    re.compile(r"\bCLAUDE\.md\b"),
    re.compile(r"\bhealthz_http\b"),
    re.compile(r"\bdeep_http\b"),
    re.compile(r"\bdeep_json_valid\b"),
    re.compile(r"\btools_count\b"),
    re.compile(r"\brecurring_workflows\b"),
    re.compile(r"\bscoped[_ -]?api[_ -]?token\b", re.IGNORECASE),
    re.compile(r"\brequire_scope\b"),
    re.compile(r"\bCANONICAL_SCOPES\b"),
    re.compile(r"\bstate-token\b", re.IGNORECASE),
    re.compile(r"\bidempotency_cache\b"),
    re.compile(r"\bmig_\d+\b", re.IGNORECASE),
    re.compile(r"\bdb_present\b"),
    re.compile(r"\bhas_billing_anchor\b"),
    re.compile(r"\blogin_request_http\b"),
    re.compile(r"\bmagic_link_ok\b"),
)


def test_status_html_json_references_exist() -> None:
    missing: list[str] = []
    for html in sorted(SITE_STATUS.glob("*.html")):
        text = html.read_text(encoding="utf-8")
        for ref in sorted(set(STATUS_JSON_REF_RE.findall(text))):
            target = REPO_ROOT / "site" / ref.lstrip("/")
            if not target.exists():
                missing.append(f"{html.relative_to(REPO_ROOT)} -> {ref}")

    assert missing == []


def test_public_status_artifacts_do_not_expose_internal_or_revenue_terms() -> None:
    targets = list(SITE_STATUS.glob("*.html")) + list(SITE_STATUS.glob("*.json"))
    for path in sorted(targets):
        text = path.read_text(encoding="utf-8")
        for pattern in PUBLIC_LEAK_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{path.relative_to(REPO_ROOT)} leaks {pattern.pattern!r}"


def test_status_html_pages_align_with_status_noindex_header() -> None:
    for path in sorted(SITE_STATUS.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert 'name="robots" content="noindex,nofollow"' in text


def test_status_html_canonicals_match_public_files() -> None:
    for path in sorted(SITE_STATUS.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'<link rel="canonical" href="([^"]+)">', text)
        assert match is not None, f"{path.relative_to(REPO_ROOT)} missing canonical"
        expected = (
            "https://jpcite.com/status/"
            if path.name == "index.html"
            else f"https://jpcite.com/status/{path.stem}"
        )
        assert match.group(1) == expected


def test_status_tree_static_header_is_noindex() -> None:
    text = HEADERS_FILE.read_text(encoding="utf-8")
    match = re.search(r"^/status/\*\n(?P<block>(?:[ \t]+[^\n]+\n?)+)", text, re.MULTILINE)

    assert match is not None, "site/_headers must define a /status/* block"
    block = match.group("block")
    assert re.search(r"^\s+X-Robots-Tag:\s*noindex,\s*nofollow\s*$", block, re.MULTILINE)
    assert not re.search(r"^\s+X-Robots-Tag:\s*index\b", block, re.MULTILINE)


def test_status_json_files_are_valid_json() -> None:
    for path in sorted(SITE_STATUS.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))


def test_ax_status_json_files_are_real_public_status_not_placeholders() -> None:
    banned = re.compile(r"\b(?:TODO|placeholder|dummy|fallback[-_ ]?overclaim)\b", re.IGNORECASE)

    for path in AX_STATUS_FILES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(payload, ensure_ascii=False)

        assert banned.search(text) is None, path.relative_to(REPO_ROOT).as_posix()
        assert payload.get("axis") in {"ax_4pillars", "ax_5pillars"}
        assert payload.get("pillars")


def test_ax_status_json_scores_stay_within_declared_bounds() -> None:
    for path in AX_STATUS_FILES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        total = float(payload["total_score"])
        max_score = float(payload["max_score"])
        average_value = payload.get("average_score_10")
        if average_value is None:
            average_value = payload["average_score"]
        average = float(average_value)

        assert 0.0 <= total <= max_score, path.relative_to(REPO_ROOT).as_posix()
        assert 0.0 <= average <= 10.0, path.relative_to(REPO_ROOT).as_posix()
        assert average == round((total / max_score) * 10.0, 2)

        for name, pillar in payload["pillars"].items():
            score = float(pillar["score"])
            pillar_max = float(pillar["max"])
            assert 0.0 <= score <= pillar_max, f"{path.name}:{name}"
