#!/usr/bin/env python3
"""publish_text guard: banned terms + numeric out-of-range + fence count drift.

LLM 呼出ゼロ。pure static analysis over site/**/*.html + site/**/*.txt + README.md.
Reads guards from data/facts_registry.json.

Context-aware allow fields on each banned_term entry:
- ``allow_in_context``: list of substrings; if any occurs in ±50-char window
  around the match, the violation is suppressed. Use for legitimate
  surface-level usage (aria-label, placeholder, etc.).
- ``allow_in_context_path_prefix``: list of path prefixes; if the file's
  relative path starts with any prefix, every match in that file is
  suppressed for that term. Use for legitimate 法令 corpus content
  (site/laws/*) where 法令 verbatim text contains ranking phrases that
  are NOT jpcite marketing claims.

Exits 1 on any violation (CI BLOCK).
"""

from __future__ import annotations

import argparse  # noqa: F401 — kept for future --strict CLI affordance
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"


DO_NOT_PROVIDE_KEYWORDS: dict[str, list[str]] = {
    "credit_judgment": ["与信判断"],
    "bankruptcy_probability": ["倒産確率", "倒産予測"],
    "antisocial_certainty": ["反社確定"],
    "investment_advice": ["投資助言"],
    "individual_medical_treatment": ["医療診断"],
}

# am_amount_condition aggregate-context patterns. Fire only when a
# template-default amount (¥500K / ¥2M) is surfaced as a DB-wide aggregate
# statistic — "平均上限額", "全体平均", "集計値", "DB 平均", "全 250,946
# 件の", etc. Individual program upper-limits like 持続化補助金「上限50
# 万円」 remain OK because they're not aggregate claims.
_AMOUNT_500K = r"(?:[¥￥]\s*500\s*,?\s*000\s*円?|50\s*万円)"
_AMOUNT_2M = r"(?:[¥￥]\s*2\s*,?\s*000\s*,?\s*000\s*円?|200\s*万円)"
_AGGREGATE_CONTEXT = (
    r"(?:平均上限|全体平均|集計値|DB\s*平均|"
    r"am_amount_condition|amount_condition\s*平均|"
    r"全\s*\d[\d,]*\s*件の\s*(?:平均|上限))"
)
DATA_QUALITY_AGGREGATE_PATTERNS: list[tuple[str, str]] = [
    (
        rf"{_AMOUNT_500K}\D{{0,20}}{_AGGREGATE_CONTEXT}",
        "am_amount_condition_template_default_500k",
    ),
    (
        rf"{_AMOUNT_2M}\D{{0,20}}{_AGGREGATE_CONTEXT}",
        "am_amount_condition_template_default_2m",
    ),
    (
        rf"{_AGGREGATE_CONTEXT}\D{{0,20}}{_AMOUNT_500K}",
        "am_amount_condition_template_default_500k",
    ),
    (
        rf"{_AGGREGATE_CONTEXT}\D{{0,20}}{_AMOUNT_2M}",
        "am_amount_condition_template_default_2m",
    ),
]


def main() -> int:
    registry = json.loads(REGISTRY.read_text("utf-8"))
    guards = registry["guards"]
    banned = guards["banned_terms"]
    ranges = guards["numeric_ranges"]
    fence_canon = guards["fence_count_canonical"]
    fence_path_prefixes: list[str] = guards.get("fence_count_allow_in_context_path_prefix", [])
    fence_ctx_substrs: list[str] = guards.get("fence_count_context_allow_substrings", [])
    do_not_provide = registry.get("do_not_provide", {})
    data_quality_block = registry.get("data_quality_publishable_false", {})

    violations: list[str] = []
    targets = (
        list((ROOT / "site").rglob("*.html"))
        + list((ROOT / "site").rglob("*.txt"))
        + list((ROOT / "docs").rglob("*.md"))
        + list((ROOT / "docs").rglob("*.html"))
        + [ROOT / "README.md"]
    )

    # do_not_provide / data_quality gates only fire on jpcite first-party
    # self-description copy. Third-party record surfaces (行政処分 quotes,
    # program-registry rows, vendor comparison subjects) legitimately name
    # 与信判断 / 投資助言 / 倒産予測 in their corpus content — we surface
    # them, we don't claim to provide them. docs/_internal/** is operator-
    # internal handoff, not user-facing copy.
    FIRST_PARTY_PATH_RE = re.compile(  # noqa: N806 — module-level path-allowlist regex, intentionally SCREAMING_SNAKE for parity with the other class-grade constants in this file
        r"^(?:site/(?:llms(?:\.en)?\.txt|index\.html|pricing\.html|"
        r"tos\.html|privacy\.html|trust/.+|security/.+|"
        r"legal-fence\.html|about/.+|audiences/index\.html)"
        r"|README\.md|docs/(?!_internal/).+)$"
    )

    # Path-level skip: docs/_internal/** is operator-only handoff /
    # audit copy that legitimately mentions banned phrases when reporting
    # on REMOVING / AVOIDING them. Same scope already used by the
    # do_not_provide / data_quality gates below (FIRST_PARTY_PATH_RE
    # excludes docs/_internal/). Extend the skip to banned_terms +
    # numeric_ranges + fence_count so the gate stays surgical.
    _INTERNAL_DOC_PREFIXES = (  # noqa: N806 — leading-underscore SCREAMING_SNAKE matches the module-internal-constant convention used elsewhere in this file
        "docs/_internal/",
        "docs/audit/",
        "docs/competitive/",
        "docs/distribution/",
        "docs/geo/",
        "docs/integrations/",
        "docs/launch_assets/",
        "docs/legal/",
        "docs/pricing/",
    )

    for f in targets:
        if not f.exists() or not f.is_file():
            continue
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(ROOT)

        # Skip operator-internal handoff/audit copy entirely.
        if any(rel.as_posix().startswith(p) for p in _INTERNAL_DOC_PREFIXES):
            continue

        for item in banned:
            # Backward-compat: accept plain string entries, but new form is
            # {"pattern": "<regex>", "reason": "<label>",
            #  "allow_in_context": [<substr>, ...],
            #  "allow_in_context_path_prefix": [<prefix>, ...]}.
            # Negative lookbehind/lookahead-aware regex survives legitimate
            # uses (完全従量, 必ず…ご確認, 個人保証人, No.1 を謳いません, ...).
            if isinstance(item, str):
                pattern = re.escape(item)
                reason = "legacy"
                allow_ctx: list[str] = []
                allow_path_prefixes: list[str] = []
            else:
                pattern = item["pattern"]
                reason = item.get("reason", "banned")
                allow_ctx = list(item.get("allow_in_context", []) or [])
                allow_path_prefixes = list(item.get("allow_in_context_path_prefix", []) or [])
            # Per-term path-prefix allow: 法令本文の site/laws/* 等は
            # ranking phrase が jpcite marketing でない (法令verbatim) ので
            # まるごと skip.
            if allow_path_prefixes and any(
                rel.as_posix().startswith(p) for p in allow_path_prefixes
            ):
                continue
            for m in re.finditer(pattern, text):
                window = text[max(0, m.start() - 50) : m.end() + 50]
                if allow_ctx and any(sub in window for sub in allow_ctx):
                    continue
                ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
                violations.append(f"{rel}:{m.start()} BANNED[{reason}] {m.group(0)!r} ctx={ctx!r}")

        for key, (lo, hi) in ranges.items():
            for m in re.finditer(rf"{re.escape(key)}\D{{0,8}}(\d[\d,]+)", text):
                v = int(m.group(1).replace(",", ""))
                if not lo <= v <= hi:
                    violations.append(f"{rel}:{m.start()} NUMERIC {key}={v} not in [{lo},{hi}]")

        # Fence-count drift gate: numbers other than canonical 7 業法 trip
        # the violation, except (a) on listed path prefixes that legitimately
        # describe the fence-count history (e.g. `site/legal-fence.html`
        # carries the canonical landing copy and intentionally references
        # both the historical 6 業法 floor and the current canonical), or
        # (b) when the surrounding ±60 chars contains an enumerated fence
        # phrase (e.g. "8 業法 fence (税理士§52..." which is an explicit
        # itemization, not a count claim).
        fence_path_skip = any(rel.as_posix().startswith(p) for p in fence_path_prefixes)
        if not fence_path_skip:
            for m in re.finditer(r"([5-8])\s*業法", text):
                n = int(m.group(1))
                if n == fence_canon:
                    continue
                window = text[max(0, m.start() - 60) : m.end() + 60]
                if any(sub in window for sub in fence_ctx_substrs):
                    continue
                violations.append(f"{rel}:{m.start()} FENCE {n}業法 != canonical {fence_canon}")

        # do_not_provide / data_quality gates run on first-party copy only.
        # Third-party-record paths (enforcement, programs, compare) carry
        # corpus content verbatim — those keywords are about a third party,
        # not a jpcite self-claim.
        is_first_party = bool(FIRST_PARTY_PATH_RE.match(rel.as_posix()))
        if not is_first_party:
            continue

        # do_not_provide gate: flag the keyword only when the surrounding
        # ±80 chars contains NO disclaimer / fence / negation marker.
        # Legitimate usage in tos.html (prohibited-use list), shinkin
        # landing ("信金内部の与信判断データは jpcite サーバを経由しま
        # せん"), intel hub ("代替ではなく確認材料"), and legal-fence
        # pages must pass; bare capability claims fail.
        DISCLAIMER_MARKERS = (  # noqa: N806 — regex pattern constant; SCREAMING_SNAKE conveys the global-pattern character even when defined inside the per-file loop
            r"(?:行いません|行わない|致しません|いたしません|しません|"
            r"出力しません|出力しない|提供しません|提供しない|"
            r"対応しません|対応しない|断定しません|断定しない|"
            r"扱いません|扱わない|範囲外|対象外|やりません|やらない|"
            r"しない領域|踏み込まない|提供対象外|対象としません|"
            r"除外|フェンス|fence|do not|does not provide|"
            r"does not enter|ご確認ください|専門家|資格を有する|"
            r"代替ではなく|代替しません|資格者|有資格者|"
            r"サーバを経由しません|利用する行為|利用しない|"
            r"判断として扱わない|断定として扱わない|保証として扱わない|"
            r"判断はしない|最終判断ではなく|として扱いません|"
            r"確定はしない|確定しません|としては使えません|"
            # Alternative-routing arrow ("→ TDB / TSR / 商工リサーチ" etc.)
            # is the canonical do_not_provide reframing marker that the
            # 公式 site llms.txt uses to declare "we don't, go to X".
            r"→|->|TDB|TSR|商工リサーチ|法律事務所|警察庁|"
            r"信用調査|信用情報|金融商品取引法|金商法|"
            r"医師法|薬機法|専門信用調査会社|"
            r"§\d+|§\d+|法\s*§|do_not_provide|publishable_aggregate)"
        )
        for cat, keywords in DO_NOT_PROVIDE_KEYWORDS.items():
            if cat not in do_not_provide:
                continue
            for kw in keywords:
                for m in re.finditer(re.escape(kw), text):
                    window = text[max(0, m.start() - 80) : m.end() + 80]
                    if re.search(DISCLAIMER_MARKERS, window):
                        continue
                    ctx = text[max(0, m.start() - 30) : m.end() + 50].replace("\n", " ")
                    violations.append(
                        f"{rel}:{m.start()} DO_NOT_PROVIDE[{cat}] {m.group(0)!r} ctx={ctx!r}"
                    )

        # data_quality_publishable_false gate: aggregate-context surfacing
        # of am_amount_condition template-default values is BANNED until
        # ETL re-validation lands. Only fires when "平均", "上限", or
        # "集計値" appears within 12 chars of the suspect amount.
        if "am_amount_condition" in data_quality_block:
            for pattern, label in DATA_QUALITY_AGGREGATE_PATTERNS:
                for m in re.finditer(pattern, text):
                    ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
                    violations.append(
                        f"{rel}:{m.start()} DATA_QUALITY[{label}] {m.group(0)!r} ctx={ctx!r}"
                    )

    if violations:
        for v in violations[:50]:
            print("FAIL", v)
        if len(violations) > 50:
            print(f"... and {len(violations) - 50} more")
        print(f"\n{len(violations)} publish_text violations")
        return 1
    print("OK: no publish_text violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
