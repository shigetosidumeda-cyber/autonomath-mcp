#!/usr/bin/env python3
"""Generate the monthly amendment digest newsletter (markdown + HTML).

Reads ``autonomath.db.am_amendment_diff`` (read-only) and renders a
month-scoped digest of detected amendment events to ``dist/digest/<YYYY-MM>/``.
The digest is the substrate for a monthly mailchimp / buttondown send — this
script only produces the static markdown + HTML; mailing is a manual paste
step downstream.

Operator: Bookyou株式会社 (T8010001213708) / info@bookyou.net
Brand: jpcite (https://jpcite.com / https://api.jpcite.com)
Frequency: 月 1 回 (毎月 5 日 09:00 JST)

Constraints (CLAUDE.md):
- read-only against autonomath.db
- NO LLM calls (this script is pure SQL + string formatting)
- am_amendment_diff content is fact summary only — no editorial interpretation
- newsletter contains program-level facts only (no houjin / 個人 surface)

Usage:
    python scripts/etl/generate_monthly_amendment_digest.py \\
        --month 2026-04 --limit 20 [--dry-run]

When --month is omitted the script defaults to "the previous month" based on
the system clock (i.e. running on 5/5 produces a digest for 4/1..4/30).
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DIST_DIR = REPO_ROOT / "dist" / "digest"

# Importance keyword ranking (higher score = more newsworthy).
# We do NOT interpret content semantically beyond lexical match — the digest
# stays factual.
IMPORTANCE_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("金額", 30),
    ("amount", 30),
    ("補助率", 25),
    ("subsidy_rate", 25),
    ("対象拡大", 20),
    ("対象", 15),
    ("期限延長", 20),
    ("延長", 15),
    ("期限", 10),
    ("公募", 10),
    ("締切", 10),
)

FIELD_LABEL_JA: dict[str, str] = {
    "amount_max_yen": "上限金額",
    "subsidy_rate_max": "補助率上限",
    "target_set_json": "対象セット",
    "source_url": "出典 URL",
    "source_fetched_at": "出典取得時刻",
    "projection_regression_candidate": "再投影候補(複数フィールド差分)",
}


# Tier mapping fallbacks. raw_json.tier is mostly empty in autonomath.db, so
# we derive an effective tier from confidence as a stable rank proxy.
# Confidence buckets are aligned with the distribution observed 2026-04-30:
# >=0.93 → S (~110), >=0.88 → A (~1.4k), >=0.80 → B, else C.
def _tier_from_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "C"
    if confidence >= 0.93:
        return "S"
    if confidence >= 0.88:
        return "A"
    if confidence >= 0.80:
        return "B"
    return "C"


TIER_RANK: dict[str, int] = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4, "?": 9}


@dataclass(frozen=True)
class DiffRow:
    diff_id: int
    entity_id: str
    field_name: str
    prev_value: str | None
    new_value: str | None
    detected_at: str
    source_url: str | None


@dataclass(frozen=True)
class EntityMeta:
    canonical_id: str
    primary_name: str
    record_kind: str
    confidence: float | None
    tier: str
    source_url: str | None
    authority_name: str | None
    prefecture: str | None
    program_kind: str | None


@dataclass
class DigestItem:
    entity: EntityMeta
    diffs: list[DiffRow] = field(default_factory=list)
    score: int = 0

    @property
    def importance_score(self) -> int:
        # Tier weight (S=300 .. C=0) + per-diff lexical score + count.
        tier_weight = max(0, 300 - TIER_RANK.get(self.entity.tier, 9) * 75)
        return tier_weight + self.score + len(self.diffs)


# ---------------------------------------------------------------------------
# Month parsing + filter
# ---------------------------------------------------------------------------


def _parse_month(arg: str | None) -> tuple[str, date, date]:
    """Resolve ``YYYY-MM`` to (label, start_date, end_date_exclusive).

    When ``arg`` is None we default to "previous calendar month" from today.
    """
    if arg is None:
        today = datetime.now(UTC).date()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        target = last_prev.replace(day=1)
    else:
        try:
            target = datetime.strptime(arg, "%Y-%m").date().replace(day=1)
        except ValueError as exc:
            raise SystemExit(f"--month must be YYYY-MM, got {arg!r}") from exc
    if target.month == 12:
        end = target.replace(year=target.year + 1, month=1, day=1)
    else:
        end = target.replace(month=target.month + 1, day=1)
    return target.strftime("%Y-%m"), target, end


# ---------------------------------------------------------------------------
# DB I/O (read-only)
# ---------------------------------------------------------------------------


def _open_db_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_diffs(
    conn: sqlite3.Connection,
    *,
    start: date,
    end: date,
) -> list[DiffRow]:
    rows = conn.execute(
        """SELECT diff_id, entity_id, field_name, prev_value, new_value,
                  detected_at, source_url
             FROM am_amendment_diff
            WHERE detected_at >= ? AND detected_at < ?
         ORDER BY entity_id, field_name, diff_id""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return [
        DiffRow(
            diff_id=r["diff_id"],
            entity_id=r["entity_id"],
            field_name=r["field_name"],
            prev_value=r["prev_value"],
            new_value=r["new_value"],
            detected_at=r["detected_at"],
            source_url=r["source_url"],
        )
        for r in rows
    ]


def fetch_entities(
    conn: sqlite3.Connection,
    canonical_ids: list[str],
) -> dict[str, EntityMeta]:
    if not canonical_ids:
        return {}
    out: dict[str, EntityMeta] = {}
    # SQLite has a parameter cap (~999); chunk to be safe.
    chunk = 800
    for i in range(0, len(canonical_ids), chunk):
        batch = canonical_ids[i : i + chunk]
        placeholders = ",".join(["?"] * len(batch))
        rows = conn.execute(
            f"""SELECT canonical_id, primary_name, record_kind, confidence,
                       source_url, raw_json
                  FROM am_entities
                 WHERE canonical_id IN ({placeholders})""",  # noqa: S608 (placeholders only)
            batch,
        ).fetchall()
        for r in rows:
            raw: dict[str, Any] = {}
            try:
                raw = json.loads(r["raw_json"]) if r["raw_json"] else {}
            except (json.JSONDecodeError, TypeError):
                raw = {}
            tier_raw = (raw.get("tier") or "").strip().upper()
            tier = tier_raw if tier_raw in TIER_RANK else _tier_from_confidence(r["confidence"])
            out[r["canonical_id"]] = EntityMeta(
                canonical_id=r["canonical_id"],
                primary_name=r["primary_name"] or "(無題)",
                record_kind=r["record_kind"],
                confidence=r["confidence"],
                tier=tier,
                source_url=r["source_url"],
                authority_name=raw.get("authority_name"),
                prefecture=raw.get("prefecture"),
                program_kind=raw.get("program_kind"),
            )
    return out


# ---------------------------------------------------------------------------
# Scoring + bucketing
# ---------------------------------------------------------------------------


def _diff_text(diff: DiffRow) -> str:
    """Return a flattened string used for keyword-importance matching."""
    parts = [
        diff.field_name,
        diff.prev_value or "",
        diff.new_value or "",
    ]
    return "\n".join(parts)


def _score_diff(diff: DiffRow) -> int:
    text = _diff_text(diff).lower()
    score = 0
    for keyword, weight in IMPORTANCE_KEYWORDS:
        if keyword.lower() in text:
            score += weight
    # amount_max_yen / subsidy_rate_max are inherently amount-class — boost.
    if diff.field_name in ("amount_max_yen", "subsidy_rate_max"):
        score += 25
    return score


def bucket_by_entity(
    diffs: list[DiffRow],
    entities: dict[str, EntityMeta],
) -> list[DigestItem]:
    by_id: dict[str, DigestItem] = {}
    for d in diffs:
        meta = entities.get(d.entity_id)
        if meta is None:
            # entity vanished from am_entities; synthesize a stub so we still
            # surface the diff (rare but observed when entities purge).
            meta = EntityMeta(
                canonical_id=d.entity_id,
                primary_name=d.entity_id,
                record_kind="?",
                confidence=None,
                tier="?",
                source_url=d.source_url,
                authority_name=None,
                prefecture=None,
                program_kind=None,
            )
        item = by_id.get(d.entity_id)
        if item is None:
            item = DigestItem(entity=meta)
            by_id[d.entity_id] = item
        item.diffs.append(d)
        item.score += _score_diff(d)
    return list(by_id.values())


def rank_items(items: list[DigestItem]) -> list[DigestItem]:
    return sorted(
        items,
        key=lambda x: (
            -x.importance_score,
            TIER_RANK.get(x.entity.tier, 9),
            x.entity.primary_name,
        ),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _format_value(field_name: str, value: str | None) -> str:
    if value is None or value == "":
        return "(未設定)"
    if field_name == "amount_max_yen":
        try:
            n = int(float(value))
            return f"{n:,} 円"
        except (TypeError, ValueError):
            return value
    if field_name == "subsidy_rate_max":
        try:
            f = float(value)
            return f"{f * 100:.1f}%"
        except (TypeError, ValueError):
            return value
    if field_name == "projection_regression_candidate":
        # Keep the JSON compact; truncate long content.
        return value if len(value) <= 200 else value[:200] + "…"
    return value if len(value) <= 200 else value[:200] + "…"


def _search_url_for(entity: EntityMeta) -> str:
    q = urllib.parse.quote(entity.primary_name, safe="")
    return f"https://api.jpcite.com/v1/programs/search?q={q}"


def _change_lines_md(diffs: list[DiffRow]) -> list[str]:
    lines: list[str] = []
    for d in diffs:
        label = FIELD_LABEL_JA.get(d.field_name, d.field_name)
        prev = _format_value(d.field_name, d.prev_value)
        new = _format_value(d.field_name, d.new_value)
        lines.append(f"  - {label}: {prev} → {new}")
    return lines


def render_markdown(
    *,
    month_label: str,
    items: list[DigestItem],
    total_diff_count: int,
    total_entity_count: int,
) -> str:
    year, month = month_label.split("-")
    subject_count = len(items)
    issue_date = datetime.now(UTC).date().isoformat()

    lines: list[str] = []
    lines.append(f"# 日本の制度 改正 digest ({year} 年 {int(month)} 月)")
    lines.append("")
    lines.append(
        f"> jpcite が {month_label} に検出した制度改正の摘要 — "
        f"{total_entity_count:,} 制度 / {total_diff_count:,} 件の差分から"
        f" {subject_count} 件を重要度順に抜粋しました。"
    )
    lines.append("")
    lines.append(
        "事実の摘要のみを記載しています(解釈・助言は含みません)。"
        " 各制度の現行内容は必ず一次出典でご確認ください。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    if not items:
        lines.append("対象期間内の検出差分はありませんでした。")
        lines.append("")
    else:
        for idx, item in enumerate(items, start=1):
            e = item.entity
            lines.append(f"## {idx}. {e.primary_name} [tier {e.tier}]")
            authority = e.authority_name or "(主管未確定)"
            location = e.prefecture or "—"
            kind = e.program_kind or e.record_kind
            lines.append(f"- 主管: {authority} / 区分: {kind} / 所在: {location}")
            detected_iso = item.diffs[0].detected_at[:10] if item.diffs else "—"
            lines.append(f"- 改正検出日: {detected_iso}")
            lines.append("- 変更点:")
            lines.extend(_change_lines_md(item.diffs))
            primary_url = e.source_url or (item.diffs[0].source_url if item.diffs else None)
            if primary_url:
                lines.append(f"- 一次出典: {primary_url}")
            lines.append(f"- jpcite で検索: {_search_url_for(e)}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"全件 ({total_diff_count:,} 差分) を確認するには:"
        f" https://api.jpcite.com/v1/am/amendment_diff?month={month_label}"
    )
    lines.append("")
    lines.append("## 配信について")
    lines.append("")
    lines.append("- 件名 template: 「[jpcite] N 件の制度改正 ({month_label}-XX)」")
    lines.append("- 配信頻度: 月 1 回(毎月 5 日 09:00 JST)")
    lines.append(
        "- 配信停止: info@bookyou.net 宛に "
        "本文 `unsubscribe` のメールをお送りください。次回配信から停止します。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"発行: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) /"
        f" 発行日 {issue_date} / お問い合わせ info@bookyou.net"
    )
    lines.append("")
    return "\n".join(lines)


def _change_lines_html(diffs: list[DiffRow]) -> list[str]:
    out: list[str] = ["<ul>"]
    for d in diffs:
        label = html.escape(FIELD_LABEL_JA.get(d.field_name, d.field_name))
        prev = html.escape(_format_value(d.field_name, d.prev_value))
        new = html.escape(_format_value(d.field_name, d.new_value))
        out.append(f"<li><strong>{label}</strong>: {prev} → {new}</li>")
    out.append("</ul>")
    return out


def render_html(
    *,
    month_label: str,
    items: list[DigestItem],
    total_diff_count: int,
    total_entity_count: int,
) -> str:
    year, month = month_label.split("-")
    subject_count = len(items)
    issue_date = datetime.now(UTC).date().isoformat()
    title = f"日本の制度 改正 digest ({year} 年 {int(month)} 月)"

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="ja"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append(f"<title>{html.escape(title)}</title>")
    parts.append(
        "<style>body{font-family:-apple-system,Segoe UI,Helvetica,Arial,"
        "sans-serif;max-width:680px;margin:1.5em auto;color:#222;line-height:"
        "1.7;padding:0 1em}h1{font-size:1.5em}h2{font-size:1.1em;margin-top:"
        "1.6em;border-bottom:1px solid #eee;padding-bottom:0.2em}.tier{color:"
        "#666;font-weight:normal;font-size:0.9em}ul{margin:0.4em 0 0.4em 1.2em"
        ";padding:0}li{margin:0.15em 0}.meta{color:#666;font-size:0.92em}"
        ".cta{background:#f3f6fb;padding:0.7em 1em;border-radius:6px;margin:"
        "1em 0}.foot{color:#888;font-size:0.85em;margin-top:2em;border-top:"
        "1px solid #eee;padding-top:1em}</style>"
    )
    parts.append("</head><body>")
    parts.append(f"<h1>{html.escape(title)}</h1>")
    parts.append(
        f"<p>jpcite が <strong>{month_label}</strong> に検出した制度改正の摘要 — "
        f"{total_entity_count:,} 制度 / {total_diff_count:,} 件の差分から"
        f" {subject_count} 件を重要度順に抜粋しました。</p>"
    )
    parts.append(
        "<p class='meta'>事実の摘要のみを記載しています(解釈・助言は含みません)。"
        "各制度の現行内容は必ず一次出典でご確認ください。</p>"
    )

    if not items:
        parts.append("<p>対象期間内の検出差分はありませんでした。</p>")
    else:
        for idx, item in enumerate(items, start=1):
            e = item.entity
            parts.append(
                f"<h2>{idx}. {html.escape(e.primary_name)} "
                f"<span class='tier'>[tier {html.escape(e.tier)}]</span></h2>"
            )
            authority = html.escape(e.authority_name or "(主管未確定)")
            location = html.escape(e.prefecture or "—")
            kind = html.escape(e.program_kind or e.record_kind)
            detected_iso = item.diffs[0].detected_at[:10] if item.diffs else "—"
            parts.append(
                f"<p class='meta'>主管: {authority} / 区分: {kind} / "
                f"所在: {location} / 改正検出日: {html.escape(detected_iso)}</p>"
            )
            parts.append("<p>変更点:</p>")
            parts.extend(_change_lines_html(item.diffs))
            primary_url = e.source_url or (item.diffs[0].source_url if item.diffs else None)
            if primary_url:
                esc = html.escape(primary_url)
                parts.append(f"<p class='meta'>一次出典: <a href='{esc}'>{esc}</a></p>")
            search_url = _search_url_for(e)
            parts.append(
                f"<p class='meta'>jpcite で検索: "
                f"<a href='{html.escape(search_url)}'>{html.escape(search_url)}</a></p>"
            )

    full_url = f"https://api.jpcite.com/v1/am/amendment_diff?month={month_label}"
    parts.append(
        f"<div class='cta'>全件 ({total_diff_count:,} 差分) を確認: "
        f"<a href='{html.escape(full_url)}'>{html.escape(full_url)}</a></div>"
    )
    parts.append(
        "<div class='foot'>"
        "件名 template: <code>[jpcite] N 件の制度改正 ({month_label}-XX)</code><br>"
        "配信頻度: 月 1 回(毎月 5 日 09:00 JST)<br>"
        "配信停止: info@bookyou.net 宛に本文 <code>unsubscribe</code> のメールを"
        "送信してください。次回配信から停止します。<br>"
        f"発行: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) / "
        f"発行日 {issue_date} / お問い合わせ "
        "<a href='mailto:info@bookyou.net'>info@bookyou.net</a>"
        "</div>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


@dataclass
class DigestRunResult:
    month: str
    total_diff_count: int
    total_entity_count: int
    selected_count: int
    markdown_path: Path | None
    html_path: Path | None
    markdown_text: str
    html_text: str
    items: list[DigestItem]


def build_digest(
    *,
    db_path: Path,
    month_arg: str | None,
    limit: int,
) -> DigestRunResult:
    month_label, start, end = _parse_month(month_arg)
    conn = _open_db_readonly(db_path)
    try:
        diffs = fetch_diffs(conn, start=start, end=end)
        entity_ids = sorted({d.entity_id for d in diffs})
        entities = fetch_entities(conn, entity_ids)
    finally:
        conn.close()
    items = bucket_by_entity(diffs, entities)
    ranked = rank_items(items)
    selected = ranked[: max(0, limit)]
    md = render_markdown(
        month_label=month_label,
        items=selected,
        total_diff_count=len(diffs),
        total_entity_count=len(entity_ids),
    )
    htm = render_html(
        month_label=month_label,
        items=selected,
        total_diff_count=len(diffs),
        total_entity_count=len(entity_ids),
    )
    return DigestRunResult(
        month=month_label,
        total_diff_count=len(diffs),
        total_entity_count=len(entity_ids),
        selected_count=len(selected),
        markdown_path=None,
        html_path=None,
        markdown_text=md,
        html_text=htm,
        items=selected,
    )


def write_outputs(result: DigestRunResult, out_root: Path) -> DigestRunResult:
    target_dir = out_root / result.month
    target_dir.mkdir(parents=True, exist_ok=True)
    md_path = target_dir / "digest.md"
    html_path = target_dir / "digest.html"
    md_path.write_text(result.markdown_text, encoding="utf-8")
    html_path.write_text(result.html_text, encoding="utf-8")
    result.markdown_path = md_path
    result.html_path = html_path
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=AUTONOMATH_DB,
        help="Path to autonomath.db (read-only).",
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        help="Target month YYYY-MM. Defaults to previous calendar month.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of subject programs to render in the digest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary + first lines without writing files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DIST_DIR,
        help="Output root (default: dist/digest).",
    )
    args = parser.parse_args()

    result = build_digest(
        db_path=args.db,
        month_arg=args.month,
        limit=args.limit,
    )
    if args.dry_run:
        print(
            f"[dry-run] month={result.month} "
            f"diffs={result.total_diff_count} "
            f"entities={result.total_entity_count} "
            f"selected={result.selected_count}"
        )
        head = "\n".join(result.markdown_text.splitlines()[:40])
        print("--- markdown preview (first 40 lines) ---")
        print(head)
        return 0

    write_outputs(result, args.out)
    print(
        f"month={result.month} "
        f"diffs={result.total_diff_count} "
        f"entities={result.total_entity_count} "
        f"selected={result.selected_count} "
        f"md={result.markdown_path} "
        f"html={result.html_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
