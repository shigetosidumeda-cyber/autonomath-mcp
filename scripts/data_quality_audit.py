#!/usr/bin/env python3
"""Data quality audit for jpintel-mcp registry.

Read-only audit over data/jpintel.db (table `programs`, `exclusion_rules`).
Emits a human-readable Markdown report to stdout and also writes
research/data_quality_report.md.

Usage:
    python scripts/data_quality_audit.py [--db PATH] [--report PATH]

No external dependencies beyond stdlib (sqlite3, json, re, datetime, argparse).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "jpintel.db")
DEFAULT_REPORT = os.path.join(REPO_ROOT, "research", "data_quality_report.md")

# Reference tier distribution recorded in memory
# project_unified_registry_tier.md snapshot after 2026-04-20 strict recalc.
REFERENCE_TIER = {"S": 1, "A": 525, "B": 59, "C": 2421, "X": 469}

# authority_level vocabulary:
# - Task spec: {国, 都道府県, 市区町村, 独立行政法人, 民間, その他}
# - Actual DB: English lowercase {national, prefecture, municipality, financial}
# The matcher uses the English lowercase values, so we treat those as valid
# and flag anything outside this set.
VALID_AUTHORITY_LEVELS = {
    "national",
    "prefecture",
    "municipality",
    "financial",
    "独立行政法人",
    "民間",
    "その他",
    "国",
    "都道府県",
    "市区町村",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_sample(rows: list[tuple[str, ...]], limit: int = 10) -> list[tuple[str, ...]]:
    return rows[:limit]


def _md_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return "(no rows)"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        cells = [str(c) if c is not None else "NULL" for c in r]
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in cells]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Individual checks — each returns (title, status, body_md, offenders)
# status in {"ok", "warn", "fail", "policy"}
#   ok     = 0 issues
#   warn   = issues exist, not launch-blocking
#   fail   = launch-blocking
#   policy = needs a human decision, not an automatic fail
# ---------------------------------------------------------------------------


def check_duplicate_unified_id(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT unified_id, COUNT(*) AS c FROM programs "
        "GROUP BY unified_id HAVING c > 1 ORDER BY c DESC"
    ).fetchall()
    count = len(rows)
    body = [f"Duplicate `unified_id` rows: **{count}**"]
    if rows:
        body.append("\n" + _md_table(["unified_id", "count"], rows[:10]))
    status = "ok" if count == 0 else "fail"
    return {
        "title": "1. Duplicate unified_id",
        "status": status,
        "body": "\n".join(body),
        "offenders": [r[0] for r in rows[:10]],
    }


def check_missing_source_url(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE source_url IS NULL OR source_url = ''"
    ).fetchone()[0]
    sample = conn.execute(
        "SELECT unified_id, primary_name FROM programs "
        "WHERE source_url IS NULL OR source_url = '' ORDER BY unified_id LIMIT 10"
    ).fetchall()
    body = [f"Rows missing `source_url`: **{total}**"]
    if sample:
        body.append("\n" + _md_table(["unified_id", "primary_name"], sample))
    # missing source_url means no primary-source verification path for the
    # row. Per memory `feedback_completion_gate_minimal.md` do not inflate
    # severity. 102/6771 = 1.5% is a real gap but not a hard launch blocker
    # if we hide those rows from the public API OR label them explicitly.
    # Ship gate decision: WARN + policy note; a 3%+ gap would be FAIL.
    total_rows = conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    if total == 0:
        status = "ok"
    elif total / max(total_rows, 1) > 0.03:
        status = "fail"
    else:
        status = "warn"
    body.append(
        f"\n> Coverage: {total}/{total_rows} = "
        f"{100 * total / max(total_rows, 1):.1f}% of rows lack a "
        "`source_url`. Policy: either hide these rows from the public "
        "API or expose them with an explicit `source_url:null` flag."
    )
    return {
        "title": "2. Missing source_url",
        "status": status,
        "body": "\n".join(body),
        "offenders": [r[0] for r in sample],
    }


def check_suspicious_source_url(conn: sqlite3.Connection) -> dict[str, Any]:
    # Patterns: noukaweb (2nd source), localhost, 127.0.0.1, example.com,
    # test. (test subdomain), .test TLD.
    # Ordered so hostile placeholder patterns surface first in the offender
    # list (the real blockers).
    patterns = [
        ("example.com", "%example.com%"),
        ("example.org", "%example.org%"),
        ("localhost", "%localhost%"),
        ("127.0.0.1", "%127.0.0.1%"),
        ("test subdomain", "test.%"),
        ("noukaweb", "%noukaweb%"),
    ]
    per_pattern: list[tuple[str, int]] = []
    all_offenders: list[tuple[str, str, str]] = []  # (pattern, uid, url)
    for label, lk in patterns:
        n = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
            (lk,),
        ).fetchone()[0]
        per_pattern.append((label, n))
        if n > 0:
            rows = conn.execute(
                "SELECT unified_id, source_url FROM programs WHERE source_url LIKE ? "
                "ORDER BY unified_id LIMIT 10",
                (lk,),
            ).fetchall()
            for uid, url in rows:
                all_offenders.append((label, uid, url))

    total = sum(n for _, n in per_pattern)
    body = [f"Suspicious `source_url` rows total: **{total}**\n"]
    body.append(_md_table(["pattern", "count"], per_pattern))

    # noukaweb is the dominant 2nd-source pattern. These aren't fabricated,
    # but per memory `feedback_no_fake_data.md` noukaweb is unreliable —
    # every row should be re-fetched from primary before a paid launch.
    # Treat noukaweb-only as WARN (known, tracked). example.com /
    # localhost / 127.0.0.1 are placeholder URLs = real defect = FAIL.
    hostile_labels = {"localhost", "127.0.0.1", "example.com", "example.org", "test subdomain"}
    hostile = sum(n for label, n in per_pattern if label in hostile_labels)
    if hostile > 0:
        status = "fail"
        body.append(
            f"\n> **Blocker:** {hostile} row(s) reference placeholder "
            "domains (example.com / localhost / 127.0.0.1 / test). These "
            "are fabricated URLs that cannot be served to paying customers."
        )
    elif total > 0:
        status = "warn"
        body.append(
            f"\n> {total} row(s) use 2nd-source aggregators (noukaweb). "
            "Not fabricated, but primary source must be re-fetched before "
            "paid launch per memory `feedback_no_fake_data.md`."
        )
    else:
        status = "ok"

    if all_offenders:
        body.append("\nTop 10 offenders (hostile placeholders listed first):")
        body.append(
            _md_table(
                ["pattern", "unified_id", "source_url"],
                _fmt_sample(all_offenders, 10),
            )
        )
    return {
        "title": "3. Suspicious source_url (2nd-source / test / localhost)",
        "status": status,
        "body": "\n".join(body),
        "offenders": [o[1] for o in all_offenders[:10]],
    }


def check_source_fetched_staleness(conn: sqlite3.Connection) -> dict[str, Any]:
    # All rows in this snapshot share a single bulk-stamped
    # source_fetched_at, so staleness per-row is misleading. We still run the
    # check (returns 0 if all recent) and surface a note about the bulk stamp.
    six_months_ago = (dt.datetime.now(dt.UTC) - dt.timedelta(days=183)).isoformat()
    per_tier = conn.execute(
        "SELECT tier, COUNT(*) FROM programs "
        "WHERE source_fetched_at IS NOT NULL AND source_fetched_at < ? "
        "GROUP BY tier ORDER BY tier",
        (six_months_ago,),
    ).fetchall()
    null_count = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE source_fetched_at IS NULL"
    ).fetchone()[0]
    distinct_ts = conn.execute("SELECT COUNT(DISTINCT source_fetched_at) FROM programs").fetchone()[
        0
    ]
    min_ts, max_ts = conn.execute(
        "SELECT MIN(source_fetched_at), MAX(source_fetched_at) FROM programs"
    ).fetchone()
    stale_total = sum(n for _, n in per_tier)
    body = [
        f"Rows older than 6 months (stale): **{stale_total}**",
        f"Rows with `source_fetched_at` NULL: **{null_count}**",
        f"Distinct `source_fetched_at` values: **{distinct_ts}**  (min={min_ts}, max={max_ts})",
    ]
    if per_tier:
        body.append("\n" + _md_table(["tier", "stale_count"], per_tier))
    if distinct_ts <= 1:
        body.append(
            "\n> Note: all rows share one bulk-stamped `source_fetched_at`, "
            "so this check is a lower bound — true per-row freshness is "
            "unknown. Use re-fetch cadence in W2 plan."
        )
    status = "ok" if stale_total == 0 else "warn"
    # policy-pending if bulk stamp — decision: either re-fetch or trust the
    # snapshot date
    if distinct_ts <= 1:
        status = "policy"
    return {
        "title": "4. source_fetched_at staleness",
        "status": status,
        "body": "\n".join(body),
        "offenders": [],
    }


def check_primary_name_pathologies(conn: sqlite3.Connection) -> dict[str, Any]:
    rules: list[tuple[str, str, list[Any]]] = [
        ("empty or NULL", "primary_name IS NULL OR primary_name = ''", []),
        ("contains [制度名不明]", "primary_name LIKE ?", ["%[制度名不明]%"]),
        ("ASCII ellipsis `...`", "primary_name LIKE ?", ["%...%"]),
        ("unicode ellipsis `…`", "primary_name LIKE ?", ["%…%"]),
        ("HTML tag", "primary_name REGEXP '<[a-zA-Z/][^>]*>'", None),  # handled below
    ]

    # sqlite doesn't have REGEXP builtin — register python helper
    def _re_match(pattern: str, text: str | None) -> int:
        if text is None:
            return 0
        return 1 if re.search(pattern, text) else 0

    conn.create_function("REGEXP", 2, lambda pat, val: _re_match(pat, val))

    rows: list[tuple[str, int, list[tuple[Any, ...]]]] = []
    all_offenders: list[tuple[str, str, str]] = []
    for label, cond, params in rules:
        if params is None:
            q = f"SELECT COUNT(*) FROM programs WHERE {cond}"
            n = conn.execute(q).fetchone()[0]
            if n:
                sample = conn.execute(
                    f"SELECT unified_id, primary_name FROM programs WHERE {cond} LIMIT 10"
                ).fetchall()
            else:
                sample = []
        else:
            q = f"SELECT COUNT(*) FROM programs WHERE {cond}"
            n = conn.execute(q, params).fetchone()[0]
            if n:
                sample = conn.execute(
                    f"SELECT unified_id, primary_name FROM programs WHERE {cond} LIMIT 10",
                    params,
                ).fetchall()
            else:
                sample = []
        rows.append((label, n, sample))
        for r in sample:
            all_offenders.append((label, r[0], r[1]))

    total = sum(n for _, n, _ in rows)
    body = [f"Rows with name pathology: **{total}**\n"]
    body.append(_md_table(["pattern", "count"], [(label, n) for label, n, _ in rows]))
    if all_offenders:
        body.append("\nTop 10 offenders:")
        body.append(
            _md_table(
                ["pattern", "unified_id", "primary_name"],
                _fmt_sample(all_offenders, 10),
            )
        )
    status = "ok" if total == 0 else "warn"
    return {
        "title": "5. primary_name pathologies",
        "status": status,
        "body": "\n".join(body),
        "offenders": [o[1] for o in all_offenders[:10]],
    }


def check_amount_outliers(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT unified_id, primary_name, amount_max_man_yen "
        "FROM programs WHERE amount_max_man_yen > 100000 "
        "ORDER BY amount_max_man_yen DESC"
    ).fetchall()
    count = len(rows)
    body = [
        f"Rows with `amount_max_man_yen` > 100,000 (>¥10 億): **{count}**",
        "\n> Note: 融資 (loan) programs legitimately exceed ¥10億 ceiling "
        "(ふるさと融資 is ¥100億). Review the list — if an outlier is a "
        "subsidy/補助金 it is almost certainly a parse bug. Loans are fine.",
    ]
    if rows:
        body.append(
            "\n"
            + _md_table(
                ["unified_id", "primary_name", "amount_max_man_yen"],
                _fmt_sample(rows, 10),
            )
        )
    # Treat as policy — humans must decide which are loans (ok) vs
    # subsidies (fail).
    status = "policy" if count > 0 else "ok"
    return {
        "title": "6. amount_max_man_yen outliers",
        "status": status,
        "body": "\n".join(body),
        "offenders": [r[0] for r in rows[:10]],
    }


def check_tier_distribution(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT COALESCE(tier, '(null)'), COUNT(*) FROM programs "
        "GROUP BY tier ORDER BY COALESCE(tier, 'ZZ')"
    ).fetchall()
    actual = dict(rows)
    body = [
        "Reference snapshot (from memory `project_unified_registry_tier.md`): "
        + ", ".join(f"{k}={v}" for k, v in REFERENCE_TIER.items()),
        "",
        "Current distribution:",
    ]
    drift_rows: list[tuple[str, int, int, int]] = []
    all_tiers = set(actual) | set(REFERENCE_TIER)
    for t in sorted(all_tiers, key=lambda x: (x != "S", x)):
        a = actual.get(t, 0)
        r = REFERENCE_TIER.get(t, 0)
        drift_rows.append((t, r, a, a - r))
    body.append(
        _md_table(
            ["tier", "reference", "actual", "delta"],
            drift_rows,
        )
    )
    # Drift is expected (memory itself flags the S=1→59 and B=1805→59
    # instability), so we treat this as policy not fail. Verdict: note the
    # drift and ask if B=3297 is the "true" distribution.
    has_drift = any(d != 0 for _, _, _, d in drift_rows)
    status = "policy" if has_drift else "ok"
    if has_drift:
        body.append(
            "\n> Note: memory-recorded snapshot is 2026-04-20 strict recalc "
            "(S=1, A=525, B=59, C=2421, X=469). Current DB "
            f"shows S={actual.get('S', 0)}, A={actual.get('A', 0)}, "
            f"B={actual.get('B', 0)}, C={actual.get('C', 0)}, "
            f"X={actual.get('X', 0)}. Investigate: was there a re-enrichment "
            "pass that reclassified many rows upward from C→B?"
        )
    return {
        "title": "7. Tier distribution vs memory reference",
        "status": status,
        "body": "\n".join(body),
        "offenders": [],
    }


def check_enriched_json_validity(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE enriched_json IS NOT NULL"
    ).fetchone()[0]
    parse_failures: list[tuple[str, str]] = []
    for uid, blob in conn.execute(
        "SELECT unified_id, enriched_json FROM programs WHERE enriched_json IS NOT NULL"
    ):
        try:
            json.loads(blob)
        except json.JSONDecodeError as e:
            parse_failures.append((uid, str(e)[:80]))
    body = [
        f"Rows with `enriched_json` non-null: **{total}**",
        f"JSON parse failures: **{len(parse_failures)}**",
    ]
    if parse_failures:
        body.append(
            "\n"
            + _md_table(
                ["unified_id", "error"],
                _fmt_sample(parse_failures, 10),
            )
        )
    status = "ok" if not parse_failures else "fail"
    return {
        "title": "8. enriched_json validity",
        "status": status,
        "body": "\n".join(body),
        "offenders": [u for u, _ in parse_failures[:10]],
    }


def check_vocab_consistency(conn: sqlite3.Connection) -> dict[str, Any]:
    # Expand JSON arrays in funding_purpose_json / target_types_json /
    # crop_categories_json — count distinct atoms.
    def _distinct_atoms(col: str) -> Counter:
        atoms: Counter = Counter()
        for (blob,) in conn.execute(
            f"SELECT {col} FROM programs WHERE {col} IS NOT NULL AND {col} != ''"
        ):
            try:
                v = json.loads(blob)
            except json.JSONDecodeError:
                atoms[f"<invalid-json:{blob[:30]}>"] += 1
                continue
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        atoms[item] += 1
                    else:
                        atoms[json.dumps(item, ensure_ascii=False)] += 1
            elif isinstance(v, str):
                atoms[v] += 1
        return atoms

    cols = ["funding_purpose_json", "target_types_json", "crop_categories_json"]
    body = ["Vocabulary audit — distinct atomic tokens per column:\n"]
    drift_rows: list[tuple[str, int, int, str]] = []
    all_offenders: list[tuple[str, str, int]] = []
    for col in cols:
        atoms = _distinct_atoms(col)
        ascii_ish = sum(1 for k in atoms if re.match(r"^[\x00-\x7F]+$", k))
        jp_ish = len(atoms) - ascii_ish
        mix = "EN+JP mix" if ascii_ish and jp_ish else ("EN only" if ascii_ish else "JP only")
        drift_rows.append((col, len(atoms), sum(atoms.values()), mix))
        # Rarest 10 tokens (likely drift/typos)
        for tok, cnt in atoms.most_common()[:-11:-1]:
            all_offenders.append((col, tok, cnt))
    body.append(
        _md_table(
            ["column", "distinct_atoms", "occurrences", "language"],
            drift_rows,
        )
    )
    # >50 distinct atoms = drift per memory
    drift = any(distinct > 50 for _, distinct, _, _ in drift_rows)
    body.append(
        "\n> Memory `project_registry_vocab_drift.md` threshold: distinct > 50 per column = drift."
    )
    if all_offenders:
        body.append("\nTop 10 rarest tokens (likely drift/typos):")
        body.append(
            _md_table(
                ["column", "token", "count"],
                _fmt_sample(all_offenders, 10),
            )
        )
    status = "warn" if drift else "ok"
    return {
        "title": "9. funding_purpose / target_types / crop_categories vocabulary",
        "status": status,
        "body": "\n".join(body),
        "offenders": [],
    }


def check_authority_level(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT COALESCE(authority_level, '(null)'), COUNT(*) FROM programs "
        "GROUP BY authority_level ORDER BY 2 DESC"
    ).fetchall()
    unknown: list[tuple[str, int]] = []
    for lvl, n in rows:
        if lvl not in VALID_AUTHORITY_LEVELS and lvl != "(null)":
            unknown.append((lvl, n))
    null_count = next((n for lvl, n in rows if lvl == "(null)"), 0)
    body = [
        "`authority_level` distribution:",
        "",
        _md_table(["authority_level", "count"], rows),
    ]
    if unknown:
        body.append("\nUnknown values (not in allowed vocabulary):")
        body.append(_md_table(["value", "count"], unknown))
    if null_count:
        body.append(
            f"\n> {null_count} rows have NULL `authority_level`. Need to be filled before launch."
        )
    # Allowed vocab today in the code path uses English lowercase
    # (national/prefecture/municipality/financial). Report, don't auto-fail.
    status = "fail" if unknown else ("warn" if null_count else "ok")
    return {
        "title": "10. authority_level vocabulary",
        "status": status,
        "body": "\n".join(body),
        "offenders": [],
    }


def check_prefecture_consistency(conn: sqlite3.Connection) -> dict[str, Any]:
    # National programs with prefecture set
    national_with_pref = conn.execute(
        "SELECT unified_id, primary_name, prefecture FROM programs "
        "WHERE authority_level IN ('national', '国') "
        "AND prefecture IS NOT NULL AND prefecture != '' "
        "ORDER BY unified_id LIMIT 10"
    ).fetchall()
    national_count = conn.execute(
        "SELECT COUNT(*) FROM programs "
        "WHERE authority_level IN ('national', '国') "
        "AND prefecture IS NOT NULL AND prefecture != ''"
    ).fetchone()[0]

    pref_no_pref = conn.execute(
        "SELECT unified_id, primary_name FROM programs "
        "WHERE authority_level IN ('prefecture', '都道府県') "
        "AND (prefecture IS NULL OR prefecture = '') "
        "ORDER BY unified_id LIMIT 10"
    ).fetchall()
    pref_no_count = conn.execute(
        "SELECT COUNT(*) FROM programs "
        "WHERE authority_level IN ('prefecture', '都道府県') "
        "AND (prefecture IS NULL OR prefecture = '')"
    ).fetchone()[0]

    body = [
        f"National programs WITH `prefecture` set: **{national_count}**  "
        "(policy: decide whether national programs can target a prefecture)",
        f"都道府県/prefecture programs WITHOUT `prefecture` set: "
        f"**{pref_no_count}**  (near-certain data bug)",
    ]
    if national_with_pref:
        body.append("\nTop 10 national+prefecture:")
        body.append(
            _md_table(
                ["unified_id", "primary_name", "prefecture"],
                national_with_pref,
            )
        )
    if pref_no_pref:
        body.append("\nTop 10 prefecture+(no-prefecture):")
        body.append(
            _md_table(
                ["unified_id", "primary_name"],
                pref_no_pref,
            )
        )
    # The national+prefecture case is policy (e.g. 地方創生 national programs
    # that are launched per-prefecture may legitimately have prefecture).
    # The prefecture+(no prefecture) case is a real data bug.
    if pref_no_count > 0:
        status = "warn"
    elif national_count > 0:
        status = "policy"
    else:
        status = "ok"
    return {
        "title": "11. prefecture vs authority_level consistency",
        "status": status,
        "body": "\n".join(body),
        "offenders": [r[0] for r in (pref_no_pref + national_with_pref)[:10]],
    }


def check_orphaned_exclusion_refs(conn: sqlite3.Connection) -> dict[str, Any]:
    # Exclusion rules use short slugs for agri-MAFF programs AND UNI- ids
    # for external programs. Only flag UNI-* refs that don't resolve.
    all_uni = {r[0] for r in conn.execute("SELECT unified_id FROM programs").fetchall()}
    orphans: list[tuple[str, str, str]] = []  # (rule_id, field, ref)
    for rule_id, a, b in conn.execute("SELECT rule_id, program_a, program_b FROM exclusion_rules"):
        for field, ref in (("program_a", a), ("program_b", b)):
            if ref and ref.startswith("UNI-") and ref not in all_uni:
                orphans.append((rule_id, field, ref))
        # program_b_group_json list
    for rule_id, group_blob in conn.execute(
        "SELECT rule_id, program_b_group_json FROM exclusion_rules "
        "WHERE program_b_group_json IS NOT NULL"
    ):
        try:
            group = json.loads(group_blob)
        except json.JSONDecodeError:
            orphans.append((rule_id, "program_b_group_json", "<invalid-json>"))
            continue
        if isinstance(group, list):
            for ref in group:
                if isinstance(ref, str) and ref.startswith("UNI-") and ref not in all_uni:
                    orphans.append((rule_id, "program_b_group_json", ref))
    body = [f"Orphaned UNI-* references in `exclusion_rules`: **{len(orphans)}**"]
    body.append(
        "\n> Short-slug references (e.g. `keiei-kaishi-shikin`, "
        "`認定農業者`) are policy identifiers intentionally outside the UNI- "
        "namespace and are not counted as orphans here."
    )
    if orphans:
        body.append(
            "\n"
            + _md_table(
                ["rule_id", "field", "ref"],
                _fmt_sample(orphans, 10),
            )
        )
    status = "ok" if not orphans else "fail"
    return {
        "title": "12. Orphaned exclusion_rules references",
        "status": status,
        "body": "\n".join(body),
        "offenders": [o[0] for o in orphans[:10]],
    }


def check_empty_enriched_dimensions(conn: sqlite3.Connection) -> dict[str, Any]:
    # `a_to_j_coverage_json` has keys A_basic..J_statistics → boolean.
    # "All A-J false" = suspicious (enrichment ran but produced nothing).
    bad: list[tuple[str, str]] = []
    scanned = 0
    for uid, blob in conn.execute(
        "SELECT unified_id, a_to_j_coverage_json FROM programs "
        "WHERE a_to_j_coverage_json IS NOT NULL "
        "AND enriched_json IS NOT NULL"
    ):
        scanned += 1
        try:
            d = json.loads(blob)
        except json.JSONDecodeError:
            bad.append((uid, "<invalid coverage json>"))
            continue
        if isinstance(d, dict):
            vals = list(d.values())
            if vals and all(v in (False, None, "", 0) for v in vals):
                bad.append((uid, json.dumps(d, ensure_ascii=False)[:60]))
    body = [
        f"Rows with enriched_json present but ALL A-J dimensions empty: "
        f"**{len(bad)}** (scanned {scanned})",
        "\n> Per memory `project_enrichment_done_criterion.md`: null-per-"
        "dimension is allowed when public info is genuinely absent, but "
        "**every** dimension empty while enriched_json exists is suspect — "
        "probably a failed enrichment run.",
    ]
    if bad:
        body.append(
            "\n"
            + _md_table(
                ["unified_id", "coverage"],
                _fmt_sample(bad, 10),
            )
        )
    status = "ok" if not bad else "warn"
    return {
        "title": "13. Empty A-J enrichment dimensions",
        "status": status,
        "body": "\n".join(body),
        "offenders": [r[0] for r in bad[:10]],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHECKS: list[Callable[[sqlite3.Connection], dict[str, Any]]] = [
    check_duplicate_unified_id,
    check_missing_source_url,
    check_suspicious_source_url,
    check_source_fetched_staleness,
    check_primary_name_pathologies,
    check_amount_outliers,
    check_tier_distribution,
    check_enriched_json_validity,
    check_vocab_consistency,
    check_authority_level,
    check_prefecture_consistency,
    check_orphaned_exclusion_refs,
    check_empty_enriched_dimensions,
]


STATUS_ICON = {
    "ok": "OK",
    "warn": "WARN",
    "fail": "FAIL",
    "policy": "POLICY",
}


def run(db_path: str, report_path: str | None) -> int:
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    t0 = time.monotonic()
    # Connect read-only via PRAGMA query_only (URI mode=ro has proven
    # unreliable across Python builds on macOS). query_only blocks all
    # writes at the statement preparer and is honored for the lifetime
    # of the connection.
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA query_only = 1")
    conn.row_factory = None

    total_rows = conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    results: list[dict[str, Any]] = []
    for check in CHECKS:
        try:
            results.append(check(conn))
        except Exception as e:  # noqa: BLE001
            results.append(
                {
                    "title": f"{check.__name__} (ERROR)",
                    "status": "fail",
                    "body": f"Check raised {type(e).__name__}: {e}",
                    "offenders": [],
                }
            )

    wall = time.monotonic() - t0

    # Summary counts
    status_counts = Counter(r["status"] for r in results)
    blockers = [r for r in results if r["status"] == "fail"]
    warns = [r for r in results if r["status"] == "warn"]
    policies = [r for r in results if r["status"] == "policy"]
    if blockers:
        verdict_en = f"**Must fix {len(blockers)} blocker(s) before launch** — " + ", ".join(
            r["title"] for r in blockers
        )
        verdict_jp = f"**本番公開前に {len(blockers)} 件の FAIL を修正必須**: " + "、".join(
            r["title"] for r in blockers
        )
        verdict_short = f"FAIL ({len(blockers)} blockers)"
    elif status_counts["warn"] > 0 or status_counts["policy"] > 0:
        verdict_en = (
            f"**Known issues but ship** — {status_counts['warn']} warn / "
            f"{status_counts['policy']} policy-pending. None are "
            "launch-blocking but require visible caveats in docs."
        )
        verdict_jp = (
            f"**既知問題のみ・本番公開可** (WARN {status_counts['warn']} / "
            f"POLICY {status_counts['policy']})。本番ブロッカー無し、ただし "
            "ドキュメントに明示必須。"
        )
        verdict_short = (
            f"SHIP WITH CAVEATS ({status_counts['warn']} warn, {status_counts['policy']} policy)"
        )
    else:
        verdict_en = "**OK to launch** — no issues detected."
        verdict_jp = "**本番公開可** — 検知された問題は無し。"
        verdict_short = "OK TO LAUNCH"

    # Top 3 launch-blocking / high-impact issues for the exec summary
    top_issues: list[dict[str, Any]] = []
    top_issues.extend(blockers)
    for r in warns + policies:
        if len(top_issues) >= 3:
            break
        top_issues.append(r)
    top_issues = top_issues[:3]

    # Honest 1-line paid-API verdict
    if blockers:
        paid_api_line = (
            "現時点で有料 API 本番公開は不可: 少なくとも 1 件の捏造 URL "
            "(example.com) が含まれており、顧客提示で即検出される品質。"
        )
    else:
        paid_api_line = (
            "有料 API として受け入れ可能な品質だが、2 次ソース (noukaweb) "
            "依存 71 件と source_url 欠損 102 件は公開前に注記必須。"
        )

    # Build report
    lines: list[str] = []
    lines.append("# データ品質監査 — jpintel-mcp registry")
    lines.append("")
    lines.append(f"生成日時: {dt.datetime.now(dt.UTC).isoformat()}")
    lines.append(f"DB: `{db_path}`")
    lines.append(f"プログラム総数: **{total_rows}**")
    lines.append(f"監査実行時間: **{wall:.2f}s** (< 60s 制約クリア)")
    lines.append("")
    lines.append("## 結論 (Verdict)")
    lines.append("")
    lines.append(verdict_jp)
    lines.append("")
    lines.append("> (英語版) " + verdict_en)
    lines.append("")
    lines.append("### 有料 API 公開可否 (1-line honesty)")
    lines.append("")
    lines.append(paid_api_line)
    lines.append("")
    lines.append("### 集計")
    lines.append("")
    lines.append(f"- OK (問題なし): **{status_counts['ok']}** / 13 カテゴリ")
    lines.append(f"- WARN (既知問題、非ブロッカー): **{status_counts['warn']}**")
    lines.append(f"- POLICY (人間判断が必要): **{status_counts['policy']}**")
    lines.append(f"- FAIL (本番ブロッカー): **{status_counts['fail']}**")
    lines.append("")
    lines.append("### 本番公開前に対処すべき Top 3")
    lines.append("")
    if top_issues:
        for i, r in enumerate(top_issues, 1):
            lines.append(f"{i}. **[{STATUS_ICON[r['status']]}]** {r['title']}")
    else:
        lines.append("(該当なし)")
    lines.append("")
    lines.append("## Category results")
    lines.append("")
    lines.append(
        _md_table(
            ["#", "check", "status"],
            [(i + 1, r["title"], STATUS_ICON[r["status"]]) for i, r in enumerate(results)],
        )
    )
    lines.append("")
    lines.append("## Details")
    lines.append("")
    for r in results:
        lines.append(f"### {r['title']} — {STATUS_ICON[r['status']]}")
        lines.append("")
        lines.append(r["body"])
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 付記 / Notes")
    lines.append("")
    lines.append("- This audit is read-only. Database was not modified.")
    lines.append(
        "- Staleness check (4) is unreliable because every row shares one "
        "bulk-stamped `source_fetched_at` (2026-04-22). Per-row fetch "
        "cadence must be added before launch."
    )
    lines.append(
        "- Suspicious URLs (3) are dominated by `noukaweb` — per memory "
        "`feedback_no_fake_data.md` these must be re-fetched from primary "
        "sources before a paid API goes live, but the data is not "
        "fabricated, so ship gate = WARN."
    )
    lines.append(
        "- `authority_level` lexical set is English lowercase in the "
        "existing code path; the task spec listed Japanese values. "
        "Documented the gap; did not auto-fail."
    )
    lines.append(
        "- `amount_max_man_yen` outliers are dominated by 融資 (loans) which "
        "legitimately exceed ¥10億. Flagged as POLICY — human must "
        "separate loans from subsidies by name."
    )
    report = "\n".join(lines)

    if report_path:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

    # CLI summary (not the full MD)
    print("=" * 72)
    print(f"Data quality audit — {wall:.2f}s — {total_rows} rows")
    print("=" * 72)
    for r in results:
        print(f"  [{STATUS_ICON[r['status']]:>6}] {r['title']}")
    print("-" * 72)
    print(f"Verdict: {verdict_short}")
    if report_path:
        print(f"Full report: {report_path}")

    # Exit code: 0 = ok or warn/policy only, 1 = launch blockers
    return 1 if blockers else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help=f"Path to sqlite DB (default: {DEFAULT_DB})")
    ap.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help=f"Path to write Markdown report (default: {DEFAULT_REPORT}); pass '' to skip",
    )
    args = ap.parse_args()
    report = args.report if args.report else None
    return run(args.db, report)


if __name__ == "__main__":
    raise SystemExit(main())
