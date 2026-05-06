"""Publish JCRB-v1 leaderboard.

Operator-side cron. **Does NOT call any LLM provider.** This script
exists only to:

1. Read customer-submitted result envelopes from
   ``benchmarks/jcrb_v1/submissions/*.json``
   (customers run ``benchmarks/jcrb_v1/run.py`` on their hardware,
   pay their own provider costs, then HTTP-POST the resulting
   summary JSON to the operator OR drop a file in this directory).
2. Validate the envelope schema (no LLM call).
3. Aggregate by ``(model, mode)`` -> latest-result dedup.
4. Write ``site/benchmark/results.json`` (read by the static landing
   page) and ``site/benchmark/results.csv`` (auditor download).

The envelope contract (one per submission):

    {
      "model": "claude-opus-4-7",
      "provider": "claude",
      "mode": "without_jpcite" | "with_jpcite",
      "submitted_at": "2026-05-04T12:00:00Z",
      "submitter": "anon | github_handle | bookyou (self)",
      "n": 100,
      "exact_match": 0.18,
      "citation_ok": 0.42,
      "by_domain": {"subsidy_eligibility": {...}, ...},
      "predictions_url": "https://... (optional, raw predictions.jsonl)",
      "questions_sha256": "abc123..."  # of questions.jsonl this was run on
    }

Schema is intentionally additive — new fields are passed through. The
operator NEVER mutates a submission's score; it only deduplicates by
(model, mode) keeping the most recent ``submitted_at``.

This script complies with the No-LLM invariant:
* No ``import anthropic|openai|google.generativeai|claude_agent_sdk``
* No reference to ``ANTHROPIC_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY``
* All inputs come from disk; all outputs go to disk.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
import time
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBMISSIONS_DIR = REPO_ROOT / "benchmarks" / "jcrb_v1" / "submissions"
SITE_OUT_DIR = REPO_ROOT / "site" / "benchmark"
QUESTIONS_PATH = REPO_ROOT / "benchmarks" / "jcrb_v1" / "questions.jsonl"

DOMAINS = (
    "subsidy_eligibility",
    "tax_application",
    "law_citation",
    "adoption_statistics",
    "enforcement_risk",
)
EXPECTED_QUESTIONS_SHA256 = hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()
REQUIRED_FIELDS = {
    "model",
    "mode",
    "submitted_at",
    "submitter",
    "n",
    "exact_match",
    "citation_ok",
    "by_domain",
    "questions_sha256",
}
ALLOWED_MODES = {"without_jpcite", "with_jpcite"}
SEED_MARKERS = ("seed estimate", "not validated", "seed-not-validated")


def _is_number_in_unit_interval(value: object) -> bool:
    return isinstance(value, int | float) and 0 <= float(value) <= 1


def _is_iso_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo == UTC


def _is_seed_submission(row: dict, source_file: str) -> bool:
    haystack = " ".join(
        [
            source_file,
            str(row.get("submitter", "")),
            str(row.get("questions_sha256", "")),
        ]
    ).lower()
    return any(marker in haystack for marker in SEED_MARKERS) or source_file.startswith("SEED_")


def _validation_error(row: dict) -> str | None:
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        return f"missing fields {sorted(missing)}"
    if row["mode"] not in ALLOWED_MODES:
        return f"bad mode {row['mode']!r}"
    if row["questions_sha256"] != EXPECTED_QUESTIONS_SHA256:
        return "questions_sha256 mismatch"
    if row["n"] != 100:
        return "n must be 100"
    if not _is_number_in_unit_interval(row["exact_match"]):
        return "exact_match must be between 0 and 1"
    if not _is_number_in_unit_interval(row["citation_ok"]):
        return "citation_ok must be between 0 and 1"
    if not _is_iso_utc(row["submitted_at"]):
        return "submitted_at must be ISO UTC ending with Z"
    by_domain = row["by_domain"]
    if not isinstance(by_domain, dict) or set(by_domain) != set(DOMAINS):
        return "by_domain must contain exactly the five JCRB domains"
    for domain in DOMAINS:
        metrics = by_domain[domain]
        if not isinstance(metrics, dict):
            return f"by_domain.{domain} must be an object"
        if metrics.get("n") != 20:
            return f"by_domain.{domain}.n must be 20"
        if not _is_number_in_unit_interval(metrics.get("exact_match")):
            return f"by_domain.{domain}.exact_match must be between 0 and 1"
        if not _is_number_in_unit_interval(metrics.get("citation_ok")):
            return f"by_domain.{domain}.citation_ok must be between 0 and 1"
    return None


def _load_submissions(directory: pathlib.Path) -> tuple[list[dict], list[dict]]:
    verified: list[dict] = []
    seed_examples: list[dict] = []
    if not directory.exists():
        return verified, seed_examples
    for p in sorted(directory.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[skip] {p.name}: bad JSON ({e})", file=sys.stderr)
            continue
        d["_source_file"] = p.name
        if _is_seed_submission(d, p.name):
            seed_examples.append(d)
            continue
        error = _validation_error(d)
        if error:
            print(f"[skip] {p.name}: {error}", file=sys.stderr)
            continue
        verified.append(d)
    return verified, seed_examples


def _dedup_latest(rows: list[dict]) -> list[dict]:
    """Keep the most recent submission per (model, mode)."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (r["model"], r["mode"])
        prev = by_key.get(key)
        if prev is None or r.get("submitted_at", "") > prev.get("submitted_at", ""):
            by_key[key] = r
    return list(by_key.values())


def _build_leaderboard(rows: list[dict]) -> list[dict]:
    """Pivot to one row per model with both modes side-by-side."""
    by_model: dict[str, dict] = {}
    for r in rows:
        m = by_model.setdefault(r["model"], {"model": r["model"]})
        if r["mode"] == "without_jpcite":
            m["without_exact_match"] = r["exact_match"]
            m["without_citation_ok"] = r["citation_ok"]
            m["without_submitted_at"] = r["submitted_at"]
            m["without_n"] = r["n"]
            m["without_submitter"] = r.get("submitter", "")
        elif r["mode"] == "with_jpcite":
            m["with_exact_match"] = r["exact_match"]
            m["with_citation_ok"] = r["citation_ok"]
            m["with_submitted_at"] = r["submitted_at"]
            m["with_n"] = r["n"]
            m["with_submitter"] = r.get("submitter", "")

    # compute lift = with - without (only when both exist)
    leaderboard = []
    for m in by_model.values():
        if "without_exact_match" in m and "with_exact_match" in m:
            m["lift_exact_match"] = round(m["with_exact_match"] - m["without_exact_match"], 4)
        if "without_citation_ok" in m and "with_citation_ok" in m:
            m["lift_citation_ok"] = round(m["with_citation_ok"] - m["without_citation_ok"], 4)
        leaderboard.append(m)
    leaderboard.sort(
        key=lambda x: x.get("with_exact_match", x.get("without_exact_match", 0)), reverse=True
    )
    return leaderboard


def _write_outputs(
    leaderboard: list[dict],
    raw_rows: list[dict],
    seed_examples: list[dict],
) -> None:
    SITE_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON for the landing page
    out_json = {
        "schema_version": "jcrb-v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_questions": 100,
        "domains": [
            *DOMAINS,
        ],
        "questions_sha256": EXPECTED_QUESTIONS_SHA256,
        "leaderboard_verified": leaderboard,
        "leaderboard": leaderboard,
        "raw_submissions": raw_rows,
        "seed_examples": seed_examples,
        "notes": [
            "leaderboard contains verified external/customer submissions only",
            "seed_examples are illustrative estimates, not leaderboard evidence",
        ],
    }
    (SITE_OUT_DIR / "results.json").write_text(
        json.dumps(out_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # CSV for auditor download
    with (SITE_OUT_DIR / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "model",
                "without_exact_match",
                "with_exact_match",
                "lift_exact_match",
                "without_citation_ok",
                "with_citation_ok",
                "lift_citation_ok",
                "without_submitted_at",
                "with_submitted_at",
            ],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(leaderboard)


def main() -> int:
    rows, seed_examples = _load_submissions(SUBMISSIONS_DIR)
    print(
        f"loaded {len(rows)} verified submissions and {len(seed_examples)} seed examples "
        f"from {SUBMISSIONS_DIR}",
        file=sys.stderr,
    )
    rows = _dedup_latest(rows)
    print(f"after dedup: {len(rows)} (model, mode) rows", file=sys.stderr)
    leaderboard = _build_leaderboard(rows)
    _write_outputs(leaderboard, rows, seed_examples)
    print(f"wrote {SITE_OUT_DIR / 'results.json'}", file=sys.stderr)
    print(f"wrote {SITE_OUT_DIR / 'results.csv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
