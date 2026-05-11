"""Wave 16 A3 — operator review pipeline for sampling drafts.

OPERATOR ONLY. NOT PART OF PRODUCTION. NOT IMPORTED BY src/ OR scripts/.

Pairs with ``sampling_runner.py``: where ``sampling_runner.py`` writes
draft completions to ``tools/offline/_inbox/sampling/``, this script
audits the drafts before any operator-approval merge into the database.

Steps:

1. Walk ``tools/offline/_inbox/sampling/*.json`` for drafts produced by
   the sampling runner.
2. For each draft, run a deterministic local check (length / required
   fields / disallowed phrases) — no LLM call here.
3. Optionally, if ``--re-grade`` is passed AND ``ANTHROPIC_API_KEY`` is
   available, request a *second* sampling-style completion that grades
   the draft (Anthropic SDK import). Output the grade alongside the
   original draft in ``tools/offline/_inbox/sampling/reviewed/``.

Usage:

    cd jpcite/
    .venv/bin/python tools/offline/sampling_review.py
    .venv/bin/python tools/offline/sampling_review.py --re-grade

The re-grade path imports ``anthropic`` and reads ``ANTHROPIC_API_KEY``;
both are tolerated under ``tools/offline/`` per the CI guard at
``tests/test_no_llm_in_production.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INBOX_DIR = Path(__file__).resolve().parent / "_inbox" / "sampling"
REVIEW_DIR = INBOX_DIR / "reviewed"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


DISALLOWED_PHRASES = (
    "jpintel",  # legacy brand collision (Intel 著名商標)
    "AutonoMath",  # legacy product name; jpcite is the current brand
    "Free tier",  # ¥3/req metered — no Free tier copy
    "Pro plan",  # no tiered SKU
)


def _local_review(draft: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, LLM-free review of a single draft entry."""
    findings: list[str] = []
    text = json.dumps(draft, ensure_ascii=False)
    for phrase in DISALLOWED_PHRASES:
        if phrase.lower() in text.lower():
            findings.append(f"forbidden_phrase:{phrase}")
    if not draft.get("ts"):
        findings.append("missing_ts")
    if "note" in draft and len(draft["note"]) > 4000:
        findings.append("note_too_long")
    return {
        "ts_reviewed": utc_now_iso(),
        "findings": findings,
        "pass": not findings,
    }


def _llm_re_grade(draft: dict[str, Any]) -> dict[str, Any]:
    """Optional sampling-style second pass for narrative quality grading.

    Imports the anthropic SDK at call time (lazy). The CI guard at
    ``tests/test_no_llm_in_production.py`` excludes ``tools/offline/``
    from the import scan, so this is the legitimate operator path.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "skipped": True,
            "reason": "ANTHROPIC_API_KEY unset; pass --re-grade only after sourcing .env.local",
        }
    import anthropic  # noqa: F401  # LLM_IMPORT_TOLERATED

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "Grade the following jpcite narrative draft on 3 axes (clarity, "
        "factual hedge, brand compliance). Return JSON with keys "
        "{clarity: 1-5, factual_hedge: 1-5, brand_compliance: 1-5, "
        "verdict: 'approve'|'revise'|'reject'}. Draft:\n\n"
        + json.dumps(draft, ensure_ascii=False, indent=2)
    )
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return {"grader_text": text, "model": resp.model}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--re-grade",
        action="store_true",
        help="Run a second sampling-style completion to grade each draft (uses operator's Anthropic key)",
    )
    args = parser.parse_args()

    drafts = sorted(INBOX_DIR.glob("drafts-*.json")) + sorted(INBOX_DIR.glob("dryrun-*.json"))
    if not drafts:
        sys.stdout.write("no drafts found under tools/offline/_inbox/sampling/\n")
        return 0

    summary = {"ts": utc_now_iso(), "files": []}
    for path in drafts:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover — defensive
            summary["files"].append({"path": str(path), "error": str(e)})
            continue
        entries = payload if isinstance(payload, list) else [payload]
        reviews = [_local_review(d) for d in entries]
        out: dict[str, Any] = {
            "source": str(path),
            "n_entries": len(entries),
            "reviews": reviews,
            "n_pass": sum(1 for r in reviews if r["pass"]),
            "n_fail": sum(1 for r in reviews if not r["pass"]),
        }
        if args.re_grade:
            out["grading"] = [_llm_re_grade(d) for d in entries]
        out_path = REVIEW_DIR / f"reviewed-{path.stem}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["files"].append(
            {"path": str(path), "reviewed_to": str(out_path), "n_fail": out["n_fail"]}
        )

    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0 if all(f.get("n_fail", 0) == 0 for f in summary["files"]) else 1


if __name__ == "__main__":
    sys.exit(main())
