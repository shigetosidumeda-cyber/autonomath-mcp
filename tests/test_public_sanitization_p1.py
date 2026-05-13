from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_STATUS_KEYS = {
    "http",
    "healthz_http",
    "deep_http",
    "deep_json_valid",
    "tools_count",
    "tools_expected",
    "recurring_workflows",
    "recurring_expected",
    "failed_events_24h",
    "rate_5xx",
    "stub",
    "datasets",
    "db_present",
    "has_billing_anchor",
    "login_request_http",
    "magic_link_ok",
    "error",
}
PUBLIC_FACT_BLOCKLIST = {"prod_branch", "prod_git_sha", "fly_app_name"}
PUBLIC_TEXT_SUFFIXES = {".html", ".json", ".md", ".txt"}
PUBLIC_SITE_SKIP_DIRS = {
    "assets",
    "cases",
    "cities",
    "cross",
    "data",
    "enforcement",
    "industries",
    "laws",
    "programs",
}
PUBLIC_SITE_SKIP_PATHS = {
    "site/docs/search/search_index.json",
}
OPERATOR_ONLY_RE = re.compile(
    r"operator[- ]only|public docs excluded|公開(?:docs\s*)?除外|公開 docs build から除外",
    re.IGNORECASE,
)
SAFE_GUARDRAIL_CONTEXT_RE = re.compile(
    "|".join(
        (
            r"estimate_not_guarantee",
            r"savings_claim",
            r"billing_savings_claim",
            r"cost_savings_guaranteed",
            r"external_llm_cost_reduction_guaranteed",
            r"must[_-]not[_-]claim",
            r"x-jpcite-must-not-claim",
            r"\bdo\s+not\s+claim\b",
            r"\bshould\s+not\s+present\b",
            r"\bguardrail\b",
            r"\bSavings Claim\b",
            r"not(?:\s+a)?\s+[^.。]{0,80}guarantee",
            r"not\s+[^.。]{0,80}guaranteed",
            r"does\s+not\s+[^.。]{0,80}guarantee",
            r"no\s+[^.。]{0,80}guarantee",
            r"\bnot\s+[^.。]{0,80}保証",
            r"条件付き",
            r"提供しない",
            r"やらない",
            r"薦めない",
            r"避ける(?:べき)?表現",
            r"型の表現",
            r"断言の禁止",
            r"含めません",
            r"保証ではない",
            r"保証ではなく",
            r"保証ではありません",
            r"保証はありません",
            r"保証しません",
            r"保証しない",
            r"保証するものではありません",
            r"保証とは表現しない",
            r"保証する表現は使わない",
            r"保証.{0,24}(?:禁止|表示しない|含めません|ではない|にはせず|しない|ありません)",
            r"固定保証はしません",
            r"使わないでください",
            r"避け",
            r"❌",
        )
    ),
    re.IGNORECASE,
)
SAFE_ZERO_HALLUCINATION_CONTEXT_RE = re.compile(
    r"not\s+[^.。]{0,80}(?:claim|present)|do\s+not\s+[^.。]{0,80}claim|"
    r"主張しない|表現しない|使わない|禁止|must[_-]not[_-]claim",
    re.IGNORECASE,
)

PUBLIC_CLAIM_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "roi_arr_or_profit_projection": (
        re.compile(r"\bROI\b"),
        re.compile(r"\bARR\b"),
        re.compile(r"\bprofit\s+projections?\b", re.IGNORECASE),
        re.compile(r"(?:利益|収益|売上)予測"),
    ),
    "guarantee_or_no_miss": (
        re.compile(r"\bno[- ]miss\b|\bnever\s+miss(?:es)?\b", re.IGNORECASE),
        re.compile(r"取りこぼしゼロ|見逃しゼロ|漏れなく検知|全(?:件|変更).{0,16}(?:検出|検知|検出済み)"),
        re.compile(
            r"(?:approval|accepted|eligibility|result|saving|savings|cost reduction)"
            r".{0,32}\bguarantee(?:d|s)?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bguarantee(?:d|s)?\b.{0,32}"
            r"(?:approval|accepted|eligibility|result|saving|savings|cost reduction)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:採択(?!事例|額|件数|履歴)|承認|審査通過|合格|削減|節約).{0,24}保証(?!人)|"
            r"保証(?!人).{0,24}(?:採択(?!事例|額|件数|履歴)|承認|審査通過|合格|削減|節約)"
        ),
    ),
    "zero_hallucination": (
        re.compile(
            r"\bhallucination[- ]?0\b|\b0\s*%\s*hallucination\b|"
            r"\bhallucination\s*0\s*%\b|\bhallucination[- ]free\b",
            re.IGNORECASE,
        ),
        re.compile(r"幻覚(?:率)?(?:を)?\s*0\s*%|幻覚ゼロ|0\s*%\s*(?:まで)?(?:落とす|削減).*幻覚"),
    ),
    "risky_savings_claim": (
        re.compile(
            r"(?:saving|savings|cost reduction|token reduction).{0,48}"
            r"(?:guarantee(?:d|s)?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:guarantee(?:d|s)?|always.{0,24}(?:save|saves|saving|reduce|lower|goes down)).{0,48}"
            r"(?:saving|savings|cost reduction|token reduction)",
            re.IGNORECASE,
        ),
        re.compile(r"必ず.{0,32}(?:節約|削減|下がる)|(?:節約|削減).{0,32}必ず"),
        re.compile(r"(?:節約|削減|費用対効果|料金削減|token 削減|トークン削減).{0,48}(?:保証|断定|確約|必ず|固定保証)"),
        re.compile(r"(?:保証|断定|確約|必ず|固定保証).{0,48}(?:節約|削減|費用対効果|料金削減|token 削減|トークン削減)"),
    ),
}


def _load_module(name: str, path: Path) -> ModuleType:
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys |= _walk_keys(child)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys |= _walk_keys(child)
        return keys
    return set()


def _install_raw_probe_stubs(status_probe: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(
        status_probe,
        "probe_api",
        lambda _base: {
            "status": "down",
            "latency_ms": 10073,
            "http": 0,
            "healthz_http": 0,
            "deep_http": 0,
            "deep_json_valid": False,
            "error": "TimeoutError: timed out",
        },
    )
    monkeypatch.setattr(
        status_probe,
        "probe_mcp",
        lambda _base: {
            "status": "degraded",
            "latency_ms": 42,
            "http": 200,
            "tools_count": 120,
            "tools_expected": 139,
            "recurring_workflows": 1,
            "recurring_expected": 3,
            "error": None,
        },
    )
    monkeypatch.setattr(
        status_probe,
        "probe_billing",
        lambda: {
            "status": "ok",
            "latency_ms": 0,
            "http": 0,
            "failed_events_24h": 0,
            "rate_5xx": 0.0,
            "stub": True,
            "error": "STRIPE_SECRET_KEY not configured",
        },
    )
    monkeypatch.setattr(
        status_probe,
        "probe_data_freshness",
        lambda: {
            "status": "degraded",
            "latency_ms": 3,
            "http": 0,
            "last_updated_at": "2026-05-12",
            "max_age_days": 2,
            "datasets": {"programs": {"db_present": False}},
            "error": None,
        },
    )
    monkeypatch.setattr(
        status_probe,
        "probe_dashboard",
        lambda _site_base, _api_base: {
            "status": "down",
            "latency_ms": 99,
            "http": 503,
            "has_billing_anchor": False,
            "login_request_http": 0,
            "magic_link_ok": False,
            "error": "HTTPError 503",
        },
    )


def _mkdocs_exclude_patterns() -> tuple[list[str], list[str]]:
    text = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    excludes: list[str] = []
    includes: list[str] = []
    in_exclude_block = False
    for raw_line in text.splitlines():
        if raw_line.startswith("exclude_docs:"):
            in_exclude_block = True
            continue
        if in_exclude_block and raw_line and not raw_line.startswith("  "):
            break
        if not in_exclude_block:
            continue
        item = raw_line.strip()
        if not item or item.startswith("#"):
            continue
        target = includes if item.startswith("!") else excludes
        target.append(item[1:] if item.startswith("!") else item)
    return excludes, includes


def _matches_mkdocs_pattern(rel: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return rel.startswith(pattern)
    return rel == pattern or Path(rel).match(pattern)


def _is_mkdocs_excluded(doc_path: Path) -> bool:
    rel = doc_path.relative_to(REPO_ROOT / "docs").as_posix()
    excludes, includes = _mkdocs_exclude_patterns()
    if any(_matches_mkdocs_pattern(rel, pattern) for pattern in includes):
        return False
    return any(_matches_mkdocs_pattern(rel, pattern) for pattern in excludes)


def _is_operator_only_doc(path: Path, text: str) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel.startswith("docs/_internal/"):
        return True
    return OPERATOR_ONLY_RE.search(text[:4096]) is not None


def _iter_public_doc_sources() -> list[Path]:
    paths = [REPO_ROOT / "README.md"]
    for path in (REPO_ROOT / "docs").rglob("*"):
        if path.suffix not in PUBLIC_TEXT_SUFFIXES or not path.is_file():
            continue
        if path.relative_to(REPO_ROOT).as_posix().startswith("docs/_internal/"):
            continue
        text = path.read_text(encoding="utf-8")
        if _is_operator_only_doc(path, text):
            continue
        if _is_mkdocs_excluded(path):
            continue
        paths.append(path)
    return sorted(paths)


def _iter_public_site_artifacts() -> list[Path]:
    paths: list[Path] = []
    site_root = REPO_ROOT / "site"
    for path in site_root.rglob("*"):
        if path.suffix not in PUBLIC_TEXT_SUFFIXES or not path.is_file():
            continue
        rel_parts = path.relative_to(site_root).parts
        if rel_parts and rel_parts[0] in PUBLIC_SITE_SKIP_DIRS:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in PUBLIC_SITE_SKIP_PATHS:
            continue
        paths.append(path)
    for name in (
        "mcp-server.core.json",
        "mcp-server.composition.json",
        "mcp-server.full.json",
        "mcp-server.json",
        "server.json",
    ):
        paths.append(REPO_ROOT / name)
    return sorted(set(paths))


def _is_safe_claim_context(category: str, line: str) -> bool:
    if category in {"guarantee_or_no_miss", "risky_savings_claim"}:
        return SAFE_GUARDRAIL_CONTEXT_RE.search(line) is not None
    if category == "zero_hallucination":
        return SAFE_ZERO_HALLUCINATION_CONTEXT_RE.search(line) is not None
    return False


def _find_public_claim_hits(paths: list[Path]) -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if _is_operator_only_doc(path, text):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        lines = text.splitlines()
        for index, line in enumerate(lines):
            for category, patterns in PUBLIC_CLAIM_PATTERNS.items():
                if not any(pattern.search(line) for pattern in patterns):
                    continue
                context = "\n".join(lines[max(0, index - 8) : min(len(lines), index + 3)])
                if _is_safe_claim_context(category, context):
                    continue
                hits.append((rel, index + 1, category, line.strip()[:220]))
    return hits


def _assert_public_status_schema(snapshot: dict) -> None:
    assert set(snapshot) == {"snapshot_at", "components", "overall"}
    assert set(snapshot["components"]) == {"api", "mcp", "billing", "data-freshness", "dashboard"}
    assert _walk_keys(snapshot).isdisjoint(FORBIDDEN_STATUS_KEYS)

    base_keys = {"status", "latency_ms", "error_category"}
    for component_id, component in snapshot["components"].items():
        expected = base_keys | (
            {"last_updated_at", "max_age_days"} if component_id == "data-freshness" else set()
        )
        assert set(component) == expected
        if component["error_category"] is not None:
            assert re.fullmatch(r"[a-z0-9_]+", component["error_category"])


def test_public_doc_sources_do_not_make_risky_legal_or_savings_claims() -> None:
    """Published docs must avoid ROI/ARR, zero-miss, zero-hallucination, and savings guarantees.

    `docs/_internal/`, mkdocs-excluded sources, and files explicitly marked
    operator-only are not public surfaces for this guard.
    """

    hits = _find_public_claim_hits(_iter_public_doc_sources())
    assert hits == [], (
        "Public doc source claim guard failed. Move planning/projection copy to "
        "docs/_internal or mark true operator-only docs explicitly. Hits: "
        f"{hits[:30]}"
    )


def test_public_static_artifacts_do_not_make_risky_legal_or_savings_claims() -> None:
    """Customer-facing static artifacts must not advertise risky legal claims.

    Raw corpus exports such as laws/cases/enforcement/data are skipped because
    they contain source-derived product names and statutory text, not jpcite
    marketing or agent-instruction claims.
    """

    hits = _find_public_claim_hits(_iter_public_site_artifacts())
    assert hits == [], f"Public static artifact claim guard failed: {hits[:30]}"


def test_status_probe_build_snapshot_is_public_redacted(monkeypatch) -> None:
    status_probe = _load_module(
        "status_probe_public_contract", REPO_ROOT / "scripts" / "ops" / "status_probe.py"
    )
    _install_raw_probe_stubs(status_probe, monkeypatch)

    snapshot = status_probe.build_snapshot("https://api.example", "https://site.example")

    _assert_public_status_schema(snapshot)
    assert snapshot["components"]["api"]["error_category"] == "timeout"
    assert snapshot["components"]["billing"]["error_category"] == "external_dependency_unavailable"
    assert snapshot["components"]["data-freshness"]["error_category"] is None
    assert snapshot["components"]["data-freshness"]["last_updated_at"] == "2026-05-12"
    assert snapshot["components"]["data-freshness"]["max_age_days"] == 2


def test_status_probe_main_writes_public_redacted_files(monkeypatch, tmp_path: Path) -> None:
    status_probe = _load_module(
        "status_probe_public_main_contract", REPO_ROOT / "scripts" / "ops" / "status_probe.py"
    )
    _install_raw_probe_stubs(status_probe, monkeypatch)

    out = tmp_path / "status.json"
    ax_out = tmp_path / "status_components.json"
    assert status_probe.main(["--out", str(out), "--ax-dashboard-out", str(ax_out), "--quiet"]) == 0

    _assert_public_status_schema(json.loads(out.read_text(encoding="utf-8")))
    derived = json.loads(ax_out.read_text(encoding="utf-8"))
    assert set(derived) == {"snapshot_at", "components", "overall"}
    assert all(
        set(item) == {"id", "label", "status", "last_check", "latency_ms"}
        for item in derived["components"]
    )


def test_regen_facts_registry_light_filters_non_public_facts() -> None:
    regen = _load_module(
        "regen_facts_registry_public_contract",
        REPO_ROOT / "scripts" / "regen_facts_registry.py",
    )
    payload = regen.emit_light(
        [{"entity_id": "p1", "kind": "program", "primary_name": "Public Program"}],
        {
            "schema_version": "1.0",
            "facts": [
                {"key": "public_metric", "category": "product", "publishable": True},
                {"key": "backup_rpo_minutes", "category": "sla", "publishable": False},
                {"key": "prod_branch", "category": "internal", "publishable": False},
                {"key": "operator_note", "category": "Internal", "publishable": True},
                {"key": "fly_app_name", "category": "internal", "publishable": True},
            ],
        },
        "2026-05-13T00:00:00Z",
    )

    assert [fact["key"] for fact in payload["facts"]] == ["public_metric"]
    assert payload["index"] == [
        {"entity_id": "p1", "kind": "program", "primary_name": "Public Program"}
    ]


def test_public_facts_registry_artifacts_do_not_include_private_facts() -> None:
    offenders: list[str] = []
    registry_paths = (
        REPO_ROOT / "data" / "facts_registry.json",
        REPO_ROOT / "site" / "data" / "facts_registry.json",
    )
    for path in registry_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for fact in payload.get("facts", []):
            if (
                fact.get("publishable") is False
                or fact.get("category") == "internal"
                or fact.get("key") in PUBLIC_FACT_BLOCKLIST
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{fact.get('key')}")

    assert offenders == []
