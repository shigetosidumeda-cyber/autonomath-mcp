#!/usr/bin/env python3
"""Guard public frontend copy against stale positioning and overclaims.

This is a small, deterministic gate for the hand-written marketing pages,
audience pages, generated MkDocs frontend, and public docs source. It catches
phrases that have repeatedly survived manual release loops, such as old RAG
labels, BPO-first wording, all-response claims, and stale Company Folder unit
copy.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = (
    "site",
    "docs",
)

TEXT_SUFFIXES = {".html", ".md", ".txt", ".json", ".js", ".css"}

SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "_internal",
    "_archive",
    "cases",
    "cities",
    "cross",
    "data",
    "industries",
    "laws",
    "prefectures",
    "programs",
    "assets",
}

PUBLIC_DOC_ALLOW_PARTS = {
    "docs/recipes",
    "docs/api-reference.md",
    "docs/getting-started.md",
    "docs/mcp-tools.md",
    "docs/pricing.md",
    "docs/legal",
    "docs/for-agent-devs",
    "docs/runbook/social_profile_setup.md",
    "docs/research/wave48/STATE_w48_cost_saving_v2_pr.md",
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    replacement_hint: str


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str
    line: int
    text: str
    replacement_hint: str


RULES = (
    Rule(
        "old_rag_nav_label",
        re.compile(
            r"LangChain\s*/\s*LlamaIndex\s*/\s*RAG|RAG\s*前の\s*Evidence Packet|"
            r"LangChain\s*/\s*LlamaIndex\s*RAG|長い\s*RAG\s*文脈|long\s+RAG\s+context|"
            r"自前\s*RAG|汎用\s*RAG|generic\s+RAG|RAG\s+answer\s+generation",
            re.IGNORECASE,
        ),
        "Use `LangChain / LlamaIndex Evidence Packet` or another evidence-prefetch label.",
    ),
    Rule(
        "old_ai_vs_jpcite_calculator_title",
        re.compile(r"普通\s*AI\s*vs\s*jpcite|API fee delta calculator", re.IGNORECASE),
        "Use `Evidence cost calculator`; keep API fee delta as a stated-baseline metric, not the page identity.",
    ),
    Rule(
        "bpo_first_positioning",
        re.compile(r"BPO\s*(?:の補助金|補助金|トリアージ)|優先架電"),
        "Use `補助金問い合わせトリアージ`, `業務支援チーム`, and `人間レビュー優先`.",
    ),
    Rule(
        "adoption_probability_band",
        re.compile(r"採択確率帯|include_adoption_probability|adoption_prob"),
        "Use `review_band` / `include_review_band` and state that adoption/receipt is not guaranteed.",
    ),
    Rule(
        "all_response_claim",
        re.compile(r"全\s*response|every\s+response|all\s+responses", re.IGNORECASE),
        "Scope the claim to `対象 response` / `対応 response`.",
    ),
    Rule(
        "hundred_percent_attribution_claim",
        re.compile(r"100%\s*付与|100\s*%\s*attribution", re.IGNORECASE),
        "Avoid 100% public attribution claims unless enforced across every route.",
    ),
    Rule(
        "old_company_folder_pack_unit",
        re.compile(
            r"会社フォルダ(?:作成)?(?:パック|Pack).*¥59\.40|¥59\.40.*会社フォルダ|"
            r"1社フォルダ作成パック|100\s*社\s*[×x]\s*18\s*req",
            re.IGNORECASE,
        ),
        "Say `Company Folder Brief: 1 unit preview`; describe Pack workflows as pre-run estimated units.",
    ),
    Rule(
        "old_application_strategy_pack",
        re.compile(r"申請戦略パック"),
        "Use `申請前 Evidence Packet` and make clear it is not filing/advice work.",
    ),
    Rule(
        "old_dd_deck_label",
        re.compile(r"DD\s+deck", re.IGNORECASE),
        "Use `公開情報 DD Evidence Packet` or `DD question checklist`.",
    ),
    Rule(
        "old_model_search_baseline",
        re.compile(r"model[-/\s]*search API fee baseline|search API fee baseline"),
        "Use `external review-cost delta reference` or `external API fee baseline`.",
    ),
    Rule(
        "old_review_cost_delta_push",
        re.compile(r"加重平均\s*external review-cost delta reference", re.IGNORECASE),
        "Frame audience pages around output artifacts and req pricing, not weighted savings claims.",
    ),
    Rule(
        "old_token_savings_overclaim",
        re.compile(r"OpenAI\s*側\s*token\s*もむしろ減る|latency\s*と\s*token\s*両方が落ちる"),
        "State that token/search fees are workload-dependent.",
    ),
    Rule(
        "old_month_savings_claim",
        re.compile(r"月節約|年\s*\*\*"),
        "Use `API fee delta reference`; avoid savings as a guaranteed outcome.",
    ),
    Rule(
        "audience_dark_inline_code_bg",
        re.compile(r"background:\s*var\(--bg-code,#f5f5f5\)|background:\s*#f6f6f6"),
        "Use theme variables such as `var(--bg-alt)`, `var(--code-bg)`, `var(--code-text)`, and `var(--border)`.",
    ),
    Rule(
        "audience_noncanonical_index_link",
        re.compile(r"/(?:en/)?audiences/index\b"),
        "Use canonical `/audiences/` or `/en/audiences/`.",
    ),
)


def _is_public_doc(rel: str) -> bool:
    if not rel.startswith("docs/"):
        return True
    return any(rel == part or rel.startswith(f"{part}/") for part in PUBLIC_DOC_ALLOW_PARTS)


def _should_scan(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if path.suffix not in TEXT_SUFFIXES:
        return False
    if any(
        part in SKIP_DIR_PARTS for part in path.relative_to(REPO_ROOT).parts
    ) and not rel.startswith("site/docs/"):
        return False
    return _is_public_doc(rel)


def iter_scan_files() -> list[Path]:
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and _should_scan(path):
                paths.append(path)
    return sorted(paths)


def scan() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_scan_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for rule in RULES:
                if not rule.pattern.search(line):
                    continue
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        path=rel,
                        line=line_no,
                        text=line.strip()[:220],
                        replacement_hint=rule.replacement_hint,
                    )
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    findings = scan()
    payload = {
        "ok": not findings,
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif findings:
        print(f"public copy freshness failed: {len(findings)} finding(s)")
        for finding in findings:
            print(
                f"{finding.path}:{finding.line}: {finding.rule_id}: "
                f"{finding.text}\n  -> {finding.replacement_hint}"
            )
    else:
        print("public copy freshness: PASS")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
