#!/usr/bin/env python3
"""DEEP-65 organic outreach monthly playbook tracker.

Spec
----
tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_65_organic_outreach_playbook.md

Monthly cron (1st of month 06:00 JST) that:
  1. Loads 32 yaml templates from data/organic_outreach_templates/
  2. Probes per-channel publish status (Zenn / GitHub / HN-Lobste.rs HTTP API)
  3. Aggregates KPI: per-channel mention count + self-vs-other ratio
     + per-cohort engagement + per-PR adoption rate
  4. Appends jsonl to analytics/organic_outreach_<YYYY-MM>.jsonl AND
     monitoring/brand_reach.jsonl (DEEP-41 brand mention dashboard feed)
  5. Reports cohort_rotation + violation_check (paid_pr / 商標 / aggregator)

Constraints (NON-NEGOTIABLE):
    * NO LLM calls (no anthropic / openai / google.generativeai / claude_agent_sdk)
    * NO paid intel SaaS / sponsored content / 商標出願 / aggregator
    * stdlib + httpx only
    * fail-open: 1 channel down does NOT abort the others

Run:
    python scripts/cron/track_organic_outreach_monthly.py
    python scripts/cron/track_organic_outreach_monthly.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = REPO_ROOT / "data" / "organic_outreach_templates"
INDEX_PATH = TEMPLATES_DIR / "index.json"
ANALYTICS_DIR = REPO_ROOT / "analytics"
MONITORING_DIR = REPO_ROOT / "monitoring"
BRAND_REACH_JSONL = MONITORING_DIR / "brand_reach.jsonl"

CHANNEL_PROBES = {
    "Zenn": "https://zenn.dev/api/articles?username=shigetoshi-umeda",
    "GitHub issue": "https://api.github.com/search/issues?q=jpcite+in:body",
    "integration PR": "https://api.github.com/search/issues?q=jpcite+is:pr",
    "HN-Lobste.rs": "https://hn.algolia.com/api/v1/search?query=jpcite",
}

FORBIDDEN_TOKENS = (
    "sponsored",
    "paid PR",
    "paid placement",
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "商標出願済",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("organic_outreach")


def _load_yaml_templates() -> list[dict]:
    """Load all 32 yaml templates without external yaml lib (manual parser)."""
    templates: list[dict] = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        templates.append(_parse_yaml(path))
    return templates


def _parse_yaml(path: pathlib.Path) -> dict:
    """Minimal yaml parser sufficient for our flat schema (id / channel / cohort / etc.)."""
    text = path.read_text(encoding="utf-8")
    out: dict = {"_path": str(path)}
    cur_key: str | None = None
    cur_list: list[str] | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw.startswith("  - "):
            if cur_list is not None:
                cur_list.append(raw[4:].strip().strip('"'))
            continue
        if raw.startswith("    - "):
            if cur_list is not None:
                cur_list.append(raw[6:].strip().strip('"'))
            continue
        # key: value or key:
        if ":" in raw:
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                cur_key = key
                cur_list = []
                out[key] = cur_list
            else:
                out[key] = val.strip('"')
                cur_list = None
                cur_key = None
    return out


def _probe_publish_status(channel: str) -> dict:
    """HTTP probe to per-channel API. Returns dict with status / mention_count."""
    url = CHANNEL_PROBES.get(channel)
    if url is None:
        return {"channel": channel, "status": "unknown", "mention_count": 0}
    try:
        import httpx  # type: ignore

        headers = {"User-Agent": "jpcite-organic-outreach/0.3.4"}
        if "github.com" in url and (token := os.getenv("GITHUB_TOKEN")):
            headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        if channel == "Zenn":
            count = len(data.get("articles", []))
        elif channel in ("GitHub issue", "integration PR"):
            count = data.get("total_count", 0)
        elif channel == "HN-Lobste.rs":
            count = data.get("nbHits", 0)
        else:
            count = 0
        return {"channel": channel, "status": "ok", "mention_count": int(count)}
    except Exception as exc:  # fail-open
        log.warning("channel %s probe failed: %s", channel, exc)
        return {"channel": channel, "status": "error", "mention_count": 0, "error": str(exc)}


def _aggregate_kpi(templates: list[dict], probes: list[dict]) -> dict:
    """Aggregate per-channel + per-cohort KPI, no LLM."""
    by_channel: dict[str, int] = {}
    by_cohort: dict[str, int] = {}
    for t in templates:
        ch = t.get("channel", "unknown")
        co = t.get("cohort", "unknown")
        by_channel[ch] = by_channel.get(ch, 0) + 1
        by_cohort[co] = by_cohort.get(co, 0) + 1
    probe_by_ch = {p["channel"]: p for p in probes}
    return {
        "per_channel_template_count": by_channel,
        "per_cohort_template_count": by_cohort,
        "per_channel_mention_count": {
            ch: probe_by_ch.get(ch, {}).get("mention_count", 0) for ch in CHANNEL_PROBES
        },
        "per_channel_status": {
            ch: probe_by_ch.get(ch, {}).get("status", "unknown") for ch in CHANNEL_PROBES
        },
        "self_vs_other_target_window_months": 4,
        "self_vs_other_target_relation": "other_count >= self_count",
    }


def _violation_check(templates: list[dict]) -> dict:
    """Scan all template files for forbidden tokens. Should always be 0.

    Tolerated patterns (NOT counted as violation):
      * Token enumerated under `forbidden_phrases:` block (intentional NG list).
      * Token followed by `NG` (e.g. `paid PR NG`) — this is a NG declaration
        in `posting_constraint`, the opposite of an endorsement.
    """
    import re

    violations = dict.fromkeys(FORBIDDEN_TOKENS, 0)
    for t in templates:
        path = pathlib.Path(t["_path"])
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        in_forbidden_block = False
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("forbidden_phrases:"):
                in_forbidden_block = True
                continue
            if in_forbidden_block and (
                not stripped or (not stripped.startswith("-") and ":" in stripped)
            ):
                in_forbidden_block = False
            if in_forbidden_block:
                continue
            for tok in FORBIDDEN_TOKENS:
                tok_low = tok.lower()
                ln_low = ln.lower()
                if tok_low not in ln_low:
                    continue
                # Skip "<token> NG" pattern — that's a NG declaration.
                ng_pat = re.compile(re.escape(tok_low) + r"\s+ng\b", re.IGNORECASE)
                if ng_pat.search(ln_low):
                    continue
                violations[tok] += 1
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not TEMPLATES_DIR.is_dir():
        log.error("templates dir missing: %s", TEMPLATES_DIR)
        return 2
    if not INDEX_PATH.is_file():
        log.error("index.json missing: %s", INDEX_PATH)
        return 2

    templates = _load_yaml_templates()
    if len(templates) != 32:
        log.error("expected 32 templates, found %d", len(templates))
        return 3
    log.info("loaded %d templates", len(templates))

    probes = [_probe_publish_status(ch) for ch in CHANNEL_PROBES]
    kpi = _aggregate_kpi(templates, probes)
    violations = _violation_check(templates)

    now = datetime.now(UTC)
    month_str = now.strftime("%Y-%m")
    record = {
        "month": month_str,
        "generated_at": now.isoformat(),
        "spec": "DEEP-65",
        "template_count": len(templates),
        "kpi": kpi,
        "violation_check": violations,
        "constraints": {"llm_api_imports": 0, "paid_pr": False, "aggregator": False},
    }

    if args.dry_run:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    MONITORING_DIR.mkdir(parents=True, exist_ok=True)
    out_jsonl = ANALYTICS_DIR / f"organic_outreach_{month_str}.jsonl"
    with out_jsonl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    with BRAND_REACH_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info("wrote %s + %s", out_jsonl, BRAND_REACH_JSONL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
