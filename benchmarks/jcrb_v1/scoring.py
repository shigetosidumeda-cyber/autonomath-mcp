"""JCRB-v1 scorer.

Pure-Python deterministic scoring. NO LLM calls in this module — the
runner is what calls a customer-side LLM. The scoring layer must remain
budget-zero so submitters can re-grade their own outputs without paying
for API access.

Two scores are emitted per question:

* ``exact_match``   — registrable-domain match on ``expected_source_host`` AND
                       substring match on ``expected_value`` (after light
                       normalization: full-width ↔ half-width, 和暦 → ISO,
                       ¥ ↔ 万円 unification).
* ``citation_ok``   — model output contains a URL whose host matches
                       ``expected_source_host`` (registrable-domain match).

A separate ``factual_correctness`` score is reserved as an OPTIONAL
LLM-judge field. The reference implementation here returns ``None`` —
operators MUST provide their own judge prompt + grader binary if they
want it. The benchmark explicitly does NOT prescribe an LLM judge so
that scoring stays reproducible offline.

Scoring contract:

    score(question, model_output) -> {
        "exact_match": 0 | 1,
        "citation_ok": 0 | 1,
        "factual_correctness": 0 | 1 | None,
    }

The aggregator computes per-domain and overall accuracy from these
fields and writes a CSV + JSON report to ``--out``.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import pathlib
import re
import sys
import unicodedata
from collections import defaultdict
from typing import Iterable

# ---------------------------------------------------------------------------
# Normalizers — kept tiny on purpose so reviewers can audit behaviour.
# ---------------------------------------------------------------------------

_WAREKI_PREFIX = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
}


def _normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace(",", "").replace(" ", "").replace("　", "")
    s = s.replace("円", "").replace("¥", "")
    return s.lower()


def _wareki_to_iso(s: str) -> str:
    """Best-effort 和暦→ISO. Returns input unchanged if no match."""
    pattern = re.compile(r"(令和|平成|昭和)\s*(\d{1,2})年(\d{1,2})月(\d{1,2})日")
    m = pattern.search(s)
    if not m:
        return s
    era, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    base = _WAREKI_PREFIX.get(era)
    if base is None:
        return s
    return s.replace(m.group(0), f"{base + y:04d}-{mo:02d}-{d:02d}")


def _man_yen_to_yen(s: str) -> str:
    """1500万円 → 15000000. Used only for amount comparison."""
    return re.sub(r"(\d+)万", lambda m: str(int(m.group(1)) * 10000), s)


# ---------------------------------------------------------------------------
# Host extraction
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://([^/\s)\"'<>]+)")


def _hosts_in(text: str) -> set[str]:
    return {h.lower() for h in _URL_RE.findall(text or "")}


def _registrable(host: str) -> str:
    """Reduce 'www.maff.go.jp' → 'maff.go.jp'. Naive: drop leading 'www.'."""
    h = host.lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return h


def _host_match(expected: str, observed_hosts: Iterable[str]) -> bool:
    exp = _registrable(expected)
    for h in observed_hosts:
        if _registrable(h).endswith(exp):
            return True
    return False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Question:
    id: str
    domain: str
    question: str
    expected_value: str
    expected_source_host: str
    expected_law_ids: list
    expected_program_ids: list
    scoring_rubric: str

    @classmethod
    def from_jsonl(cls, line: str) -> "Question":
        d = json.loads(line)
        return cls(
            id=d["id"],
            domain=d["domain"],
            question=d["question"],
            expected_value=d.get("expected_value", ""),
            expected_source_host=d.get("expected_source_host", ""),
            expected_law_ids=d.get("expected_law_ids", []),
            expected_program_ids=d.get("expected_program_ids", []),
            scoring_rubric=d.get("scoring_rubric", "string_with_source"),
        )


def score_one(q: Question, output: str, factual_judge=None) -> dict:
    """Return per-question score dict.

    ``factual_judge`` is an OPTIONAL callable ``(question, output) -> 0|1``
    a customer can wire to their own LLM. Default = None (no judge call).
    """
    out = output or ""

    # citation
    hosts = _hosts_in(out)
    citation_ok = 1 if (q.expected_source_host and _host_match(q.expected_source_host, hosts)) else 0

    # exact_match: substring match on normalized expected_value
    exp_norm = _normalize_text(_man_yen_to_yen(_wareki_to_iso(q.expected_value)))
    out_norm = _normalize_text(_man_yen_to_yen(_wareki_to_iso(out)))
    em_value = 1 if (exp_norm and exp_norm in out_norm) else 0

    # exact_match counts only if BOTH the value and the citation host land.
    em = 1 if (em_value == 1 and citation_ok == 1) else 0

    fc = None
    if factual_judge is not None:
        try:
            fc = int(bool(factual_judge(dataclasses.asdict(q), out)))
        except Exception:  # noqa: BLE001 — judge is opaque, never crash scoring
            fc = None

    return {
        "id": q.id,
        "domain": q.domain,
        "exact_match": em,
        "exact_match_value_only": em_value,
        "citation_ok": citation_ok,
        "factual_correctness": fc,
    }


def aggregate(rows: list[dict]) -> dict:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_domain[r["domain"]].append(r)

    def _avg(vals: list[int]) -> float:
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "n": len(rows),
        "exact_match": _avg([r["exact_match"] for r in rows]),
        "citation_ok": _avg([r["citation_ok"] for r in rows]),
        "by_domain": {
            d: {
                "n": len(rs),
                "exact_match": _avg([r["exact_match"] for r in rs]),
                "citation_ok": _avg([r["citation_ok"] for r in rs]),
            }
            for d, rs in by_domain.items()
        },
    }
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score JCRB-v1 model outputs.")
    p.add_argument("--questions", type=pathlib.Path, default=pathlib.Path(__file__).parent / "questions.jsonl")
    p.add_argument("--predictions", type=pathlib.Path, required=True,
                   help="JSONL of {id, output} rows produced by run.py")
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("jcrb_v1_results"),
                   help="Output prefix (writes <out>.csv and <out>.json)")
    args = p.parse_args(argv)

    qs = {q.id: q for q in (Question.from_jsonl(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip())}
    preds = {}
    for line in args.predictions.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        preds[d["id"]] = d.get("output", "")

    rows = []
    for qid, q in qs.items():
        out = preds.get(qid, "")
        rows.append(score_one(q, out))

    summary = aggregate(rows)

    # CSV per-question
    csv_path = args.out.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "domain", "exact_match", "exact_match_value_only", "citation_ok", "factual_correctness"])
        w.writeheader()
        w.writerows(rows)

    # JSON summary
    json_path = args.out.with_suffix(".json")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
