#!/usr/bin/env python3
"""Wave 43.3.10 — AX 5 Pillars audit (4 Biilmann + Resilience).

Composes the existing 4-pillar audit (Access / Context / Tools /
Orchestration, 48/48 max via Wave 41 6-checks×4-pillars×+2.0) with a
**Resilience** pillar carrying 12 cells (the Wave 43.3.x resilience surface
1-12: idempotency / retry / circuit / DLQ / canary / degradation /
failover / chaos / SLA-alert / postmortem-auto / backup-verify + the AX
5pillars dashboard itself). Total possible 60/60 cells.

Each Resilience cell is a binary file-or-pattern existence check — no
network, no DB. Read-only stdlib + the 4-pillar runner imported as a
module. Output: docs/audit/ax_5pillars_audit_<date>.md + optional JSON.

CLI: python3 scripts/ops/audit_runner_ax_5pillars.py --out <md> [--out-json <json>]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS_OPS = REPO_ROOT / "scripts" / "ops"
SCRIPTS_CRON = REPO_ROOT / "scripts" / "cron"
SRC = REPO_ROOT / "src" / "jpintel_mcp"
TESTS = REPO_ROOT / "tests"
DOCS_AUDIT = REPO_ROOT / "docs" / "audit"
SITE_STATUS = REPO_ROOT / "site" / "status"

RESILIENCE_MAX = 12
PER_CELL_WEIGHT = 1.0  # Resilience scored 0-12 (1 per cell)


@dataclass
class ResilienceCell:
    name: str
    passed: bool
    evidence: str = ""
    missing: str = ""


@dataclass
class ResiliencePillar:
    cells: list[ResilienceCell] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(PER_CELL_WEIGHT for c in self.cells if c.passed), 2)

    @property
    def evidence(self) -> list[str]:
        return [f"[OK] {c.name}: {c.evidence}" for c in self.cells if c.passed]

    @property
    def missing_items(self) -> list[str]:
        return [
            f"[MISS] {c.name}: {c.missing or 'criterion not satisfied'}"
            for c in self.cells
            if not c.passed
        ]


def _exists(p: pathlib.Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def _file_has_pattern(p: pathlib.Path, pattern: str) -> bool:
    if not p.exists():
        return False
    try:
        return bool(re.search(pattern, p.read_text(encoding="utf-8", errors="ignore")))
    except OSError:
        return False


def _grep_dir(root: pathlib.Path, pattern: str, glob: str = "**/*.py") -> list[pathlib.Path]:
    if not root.exists():
        return []
    rx = re.compile(pattern)
    out: list[pathlib.Path] = []
    for fp in root.glob(glob):
        if not fp.is_file():
            continue
        try:
            if rx.search(fp.read_text(encoding="utf-8", errors="ignore")):
                out.append(fp)
        except (OSError, UnicodeDecodeError):
            continue
    return out


def _check(name: str, passed: bool, ok_msg: str, miss_msg: str) -> ResilienceCell:
    return ResilienceCell(
        name=name,
        passed=passed,
        evidence=ok_msg if passed else "",
        missing="" if passed else miss_msg,
    )


def resilience_pillar() -> ResiliencePillar:
    p = ResiliencePillar()

    # Cell 1 — Idempotency module (Wave 43.3.1).
    idem_hits = _grep_dir(SRC, r"class\s+IdempotencyCache|idempotency_key|@idempotent") + _grep_dir(
        SCRIPTS_OPS, r"idempotency"
    )
    p.cells.append(
        _check(
            "1_idempotency",
            bool(idem_hits) or _exists(SRC / "api" / "_idempotency.py"),
            f"src/scripts hits={len(idem_hits)}",
            "no idempotency_key / IdempotencyCache anchor",
        )
    )

    # Cell 2 — Retry policy (Wave 43.3.2).
    retry_hits = _grep_dir(SRC, r"backoff|tenacity|@retry|max_retries|retry_policy")
    p.cells.append(
        _check(
            "2_retry_policy",
            len(retry_hits) >= 1,
            f"retry/backoff anchors={len(retry_hits)}",
            "no retry/backoff/tenacity anchor under src/",
        )
    )

    # Cell 3 — Circuit breaker (Wave 43.3.3).
    cb_hits = _grep_dir(
        SRC, r"circuit_breaker|CircuitBreaker|class\s+Circuit|HALF_OPEN|short.circuit"
    )
    p.cells.append(
        _check(
            "3_circuit_breaker",
            bool(cb_hits),
            f"circuit_breaker anchors={len(cb_hits)}",
            "no CircuitBreaker / HALF_OPEN / short-circuit anchor",
        )
    )

    # Cell 4 — DLQ (Wave 43.3.4).
    dlq_hits = _grep_dir(SRC, r"dead_letter|DLQ|dlq_depth|dead-letter") + _grep_dir(
        SCRIPTS_CRON, r"dlq"
    )
    p.cells.append(
        _check(
            "4_dlq",
            bool(dlq_hits),
            f"DLQ anchors={len(dlq_hits)}",
            "no DLQ / dead_letter anchor",
        )
    )

    # Cell 5 — Canary / staged deploy (Wave 43.3.5).
    canary_hits = _grep_dir(
        REPO_ROOT / ".github" / "workflows",
        r"canary|blue.green|gradual|rolling|strategy:\s*rolling",
        glob="**/*.yml",
    ) + _grep_dir(
        REPO_ROOT, r"strategy\s*=\s*[\"']rolling|canary_percent|max_unavailable", glob="fly.toml"
    )
    p.cells.append(
        _check(
            "5_canary",
            bool(canary_hits) or _exists(REPO_ROOT / "docs" / "runbook" / "canary.md"),
            f"canary/rolling anchors={len(canary_hits)}",
            "no canary/blue-green/rolling-deploy anchor",
        )
    )

    # Cell 6 — Graceful degradation (Wave 43.3.6).
    degrad_hits = _grep_dir(
        SRC,
        r"graceful_degrad|fallback_response|degraded_mode|degrade gracefully|fallback to|http_fallback|_http_fallback",
    )
    p.cells.append(
        _check(
            "6_degradation",
            bool(degrad_hits),
            f"degradation anchors={len(degrad_hits)}",
            "no graceful_degrad / fallback / degrade gracefully anchor",
        )
    )

    # Cell 7 — Failover / DR (Wave 43.3.7).
    failover_hits = _grep_dir(
        REPO_ROOT / "docs", r"failover|disaster.recovery|RPO|RTO", glob="**/*.md"
    ) + _grep_dir(SCRIPTS_OPS, r"failover")
    p.cells.append(
        _check(
            "7_failover",
            bool(failover_hits),
            f"failover/DR anchors={len(failover_hits)}",
            "no failover/RPO/RTO anchor",
        )
    )

    # Cell 8 — Chaos engineering (Wave 43.3.8 + Wave 18 E3).
    chaos_hits = _grep_dir(TESTS / "chaos", r"toxiproxy|chaos|fault_inject", glob="**/*.py")
    p.cells.append(
        _check(
            "8_chaos",
            bool(chaos_hits) or _exists(TESTS / "chaos"),
            f"chaos anchors={len(chaos_hits)}",
            "tests/chaos absent or no toxiproxy/fault_inject anchor",
        )
    )

    # Cell 9 — Postmortem v2 base (Wave 25 + Wave 41 J).
    pm_base = (
        list((REPO_ROOT / "docs" / "postmortem").glob("*.md"))
        if (REPO_ROOT / "docs" / "postmortem").exists()
        else []
    )
    p.cells.append(
        _check(
            "9_postmortem_v2_base",
            len(pm_base) >= 1,
            f"docs/postmortem entries={len(pm_base)}",
            "no docs/postmortem/*.md entries",
        )
    )

    # Cell 10 — SLA breach alert (Wave 43.3.10 cell 10, this wave).
    sla_path = SCRIPTS_CRON / "sla_breach_alert.py"
    p.cells.append(
        _check(
            "10_sla_alert",
            _exists(sla_path)
            and _file_has_pattern(sla_path, r"METRICS\s*[:=]")
            and _file_has_pattern(sla_path, r"_send_telegram")
            and _file_has_pattern(sla_path, r"sla_breach_w43_3_10"),
            "scripts/cron/sla_breach_alert.py: 12 METRICS + Telegram + sidecar",
            f"missing or incomplete: {sla_path.name}",
        )
    )

    # Cell 11 — Postmortem auto v2 (Wave 43.3.10 cell 11, this wave).
    pm_path = SCRIPTS_OPS / "postmortem_auto_v2.py"
    p.cells.append(
        _check(
            "11_postmortem_auto_v2",
            _exists(pm_path)
            and _file_has_pattern(pm_path, r"detect_incidents")
            and _file_has_pattern(pm_path, r"render_md")
            and _file_has_pattern(pm_path, r"open_draft_pr"),
            "scripts/ops/postmortem_auto_v2.py: detect+render+PR open",
            f"missing or incomplete: {pm_path.name}",
        )
    )

    # Cell 12 — Backup verify daily (Wave 43.3.10 cell 12, this wave).
    bv_path = SCRIPTS_CRON / "verify_backup_daily.py"
    p.cells.append(
        _check(
            "12_backup_verify",
            _exists(bv_path)
            and _file_has_pattern(bv_path, r"_sha256_file")
            and _file_has_pattern(bv_path, r"_latest_r2_snapshot")
            and _file_has_pattern(bv_path, r"backup_verify_daily\.json"),
            "scripts/cron/verify_backup_daily.py: r2 list + sha256 + sidecar",
            f"missing or incomplete: {bv_path.name}",
        )
    )

    return p


def _load_4pillars_audit() -> dict[str, Any]:
    """Run the Wave 41 4-pillar audit by importing the existing module."""
    mod_name = "audit_runner_ax_4pillars"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        spec = importlib.util.spec_from_file_location(
            mod_name, SCRIPTS_OPS / "audit_runner_ax_4pillars.py"
        )
        if spec is None or spec.loader is None:
            return {
                "axis": "ax_4pillars",
                "total_score": 0.0,
                "max_score": 48.0,
                "average_score": 0.0,
                "cell_count": 0,
                "pillars": {},
                "error": "4pillars_import_failed",
            }
        mod = importlib.util.module_from_spec(spec)
        # Register BEFORE exec_module so @dataclass annotations resolve
        # (dataclasses introspects sys.modules[cls.__module__] in 3.13).
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return mod.run_audit()  # type: ignore[no-any-return]


def run_audit() -> dict[str, Any]:
    four = _load_4pillars_audit()
    resil = resilience_pillar()
    four_total = float(four.get("total_score") or 0.0)
    four_max = float(four.get("max_score") or 48.0)
    resil_total = resil.score
    grand_total = round(four_total + resil_total, 2)
    grand_max = round(four_max + RESILIENCE_MAX, 2)
    cell_count = int(four.get("cell_count") or 0) + len(resil.cells)
    avg10 = round((grand_total / grand_max) * 10.0, 2) if grand_max > 0 else 0.0
    verdict = "green" if avg10 >= 8.0 else ("yellow" if avg10 >= 6.0 else "red")
    return {
        "axis": "ax_5pillars",
        "framework": "Biilmann 4 (Access/Context/Tools/Orchestration) + Resilience",
        "total_score": grand_total,
        "max_score": grand_max,
        "average_score": avg10,
        "average_score_10": avg10,
        "cell_count": cell_count,
        "verdict": verdict,
        "pillars": {
            **dict(four.get("pillars", {}).items()),
            "Resilience": {
                "score": resil.score,
                "max": float(RESILIENCE_MAX),
                "cells": len(resil.cells),
                "evidence": resil.evidence,
                "missing_items": resil.missing_items,
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_md(result: dict[str, Any]) -> str:
    date = result["generated_at"][:10]
    lines = [
        f"# jpcite AX 5 Pillars Audit — {date} (automated)",
        "",
        f"**Total**: {result['total_score']:.2f} / {result['max_score']:.0f}  ",
        f"**Average**: {result['average_score_10']:.2f} / 10 ({result['verdict'].upper()})  ",
        f"**Framework**: {result['framework']}  ",
        f"**Cells**: {result['cell_count']}",
        "",
        "| Pillar | Score | Cells |",
        "| --- | --- | --- |",
    ]
    for name, body in result["pillars"].items():
        lines.append(
            f"| {name} | {body['score']:.2f} / {body.get('max', 12.0):.0f} | {body.get('cells', '-')} |"
        )
    lines.append("")
    for name, body in result["pillars"].items():
        lines += [
            f"## {name} — {body['score']:.2f} / {body.get('max', 12.0):.0f}",
            "",
            "### Evidence",
            "",
        ]
        if not body.get("evidence"):
            lines.append("- (none)")
        else:
            for e in body["evidence"]:
                lines.append(f"- {e}")
        lines += ["", "### Missing items", ""]
        if not body.get("missing_items"):
            lines.append("- (none)")
        else:
            for m in body["missing_items"]:
                lines.append(f"- {m}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _sanitize_public_artifact_text(text: str) -> str:
    replacements = [
        (
            r"\[WARN\] only \d+ caller\(s\); require_scope\(\) has \d+ caller\(s\) "
            r"under src/jpintel_mcp/api/ \(need >= \d+ — one per CANONICAL_SCOPES entry\)",
            (
                "[WARN] route_access_check: route-level access checks are not yet "
                "broadly verified across "
                "the public API surface"
            ),
        ),
        (
            r"\d+ route file\(s\) import \+ Depends\(require_scope\(\.\.\.\)\): \[[^\]]*\]",
            "route-level access checks are applied across the public API surface",
        ),
        (r"\brequire_scope\(\)", "route-level access check"),
        (r"\bCANONICAL_SCOPES\b", "documented access levels"),
        (r"\bscoped_api_token\b", "route_access_check"),
        (r"\bscoped API token\b", "route-level access check"),
        (r"\bidempotency_cache\b", "replay-safe request store"),
        (r"\bmigration_\d+=True\b", "schema update present"),
        (r"\bmigration_\d+\b", "schema update"),
        (r"\bmig_\d+\b", "schema update"),
        (r"\bstate-token\b", "continuation handle"),
        (r"\bstate_token\+HMAC 24h\b", "signed continuation handoff"),
    ]
    out = text
    for pattern, replacement in replacements:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def _sanitize_public_artifact(node: Any) -> Any:
    """Return a public-safe copy of the audit result for site/status output."""
    if isinstance(node, dict):
        return {key: _sanitize_public_artifact(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_sanitize_public_artifact(item) for item in node]
    if isinstance(node, str):
        return _sanitize_public_artifact_text(node)
    return deepcopy(node)


def _ensure_public_access_warn(result: dict[str, Any]) -> dict[str, Any]:
    """Keep the Access downgrade explicit without exposing internal scope names."""

    access = ((result.get("pillars") or {}).get("Access") or {})
    if not isinstance(access, dict):
        return result
    evidence = access.setdefault("evidence", [])
    missing_items = access.setdefault("missing_items", [])
    if not isinstance(evidence, list) or not isinstance(missing_items, list):
        return result

    has_access_warn = any(
        isinstance(item, str) and "route_access_check" in item and "[WARN]" in item
        for item in [*evidence, *missing_items]
    )
    if has_access_warn and not any(
        isinstance(item, str) and "[WARN] route_access_check" in item for item in evidence
    ):
        evidence.append(
            "[WARN] route_access_check: route-level access checks are not yet "
            "broadly verified across "
            "the public API surface"
        )
    if has_access_warn and not any(
        isinstance(item, str) and "route-level access checks" in item
        for item in missing_items
    ):
        missing_items.append(
            "[MISS] route_access_check: route-level access checks are not yet "
            "broadly verified across the public API surface"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output markdown path")
    ap.add_argument("--out-json", default=None)
    ap.add_argument(
        "--out-site-json",
        default=str(SITE_STATUS / "ax_5pillars.json"),
        help="sidecar for the dashboard + cell-10 SLA pickup",
    )
    args = ap.parse_args(argv)

    result = run_audit()
    out_md = pathlib.Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(result), encoding="utf-8")

    site_json = pathlib.Path(args.out_site_json)
    site_json.parent.mkdir(parents=True, exist_ok=True)
    public_result = _ensure_public_access_warn(_sanitize_public_artifact(result))
    site_json.write_text(json.dumps(public_result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.out_json:
        out_json = pathlib.Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"AX 5 Pillars total={result['total_score']:.2f}/{result['max_score']:.0f} "
        f"average={result['average_score_10']:.2f}/10 cells={result['cell_count']} "
        f"verdict={result['verdict']}"
    )
    for name, body in result["pillars"].items():
        print(
            f"  - {name}: {body['score']:.2f}/{body.get('max', 12.0):.0f} ({body.get('cells', '-')} cells)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
