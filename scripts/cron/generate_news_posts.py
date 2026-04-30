#!/usr/bin/env python3
"""Weekly news/changelog auto-generation cron.

Reads append-only `am_amendment_diff` rows detected in the past 7 days,
groups them by `entity_id`, and emits one customer-facing news post per
program with detected changes. Drives the recurring SEO + GEO citation
flywheel: every fresh change in a real public-program corpus becomes a
crawlable, citable URL on jpcite.com.

Honesty constraints (non-negotiable)
------------------------------------
* Only post about REAL changes recorded in `am_amendment_diff`. The diff
  log is append-only and refreshed by `refresh_amendment_diff.py`. No
  fabrication.
* If the diff table has 0 rows in the window, log "no posts to generate"
  and exit 0. Do NOT write a "no changes detected" placeholder — that is
  engagement bait, not honesty.
* Idempotent: running twice on the same JST date with the same diff
  state must produce byte-identical files. We achieve this by:
    - keying output paths on `detected_at` (JST date) + `entity_id`
    - sorting all enumerable fields deterministically
    - skipping a write when the file already exists with identical bytes

Output layout
-------------
    site/news/{YYYY}/{MM}/{DD}/{entity-slug}.html

Disclaimer footer
-----------------
Every news post carries the §52 税理士法 disclaimer + the auto-detection
caveat — see `site/_templates/news_post.html`.

Usage
-----
    python scripts/cron/generate_news_posts.py                # 7-day window, write posts
    python scripts/cron/generate_news_posts.py --window 14    # 14-day window (catch-up)
    python scripts/cron/generate_news_posts.py --dry-run      # plan only, no write
    python scripts/cron/generate_news_posts.py --since 2026-04-22T00:00:00Z
    python scripts/cron/generate_news_posts.py --output site/news --domain jpcite.com

Exit codes
----------
0 success (possibly with "no posts" log)
1 fatal (db missing, template missing, jinja2 not installed, etc)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "ERROR: jinja2 is required. `uv pip install jinja2` or add to pyproject.\n"
    )
    raise

try:
    import pykakasi  # type: ignore
except ImportError:  # pragma: no cover
    pykakasi = None  # slug falls back to entity_id hash if pykakasi missing

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.generate_news_posts")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# JST = UTC+9. We stamp dates in JST throughout to match every other
# date surfaced on jpcite.com (CLAUDE.md baseline).
_JST = timezone(timedelta(hours=9))
_UTC = timezone.utc

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_DIR = _REPO_ROOT / "site" / "_templates"
_DEFAULT_OUT = _REPO_ROOT / "site" / "news"

# Append-only run log emitted by scripts/cron/incremental_law_fulltext.py.
# When --include-law-loads is set, we read entries within the window and
# stage them for downstream HTML emission. See _detect_law_loads().
_LAW_LOAD_LOG = _REPO_ROOT / "data" / "law_load_log.jsonl"
_LAW_LOAD_PENDING = _REPO_ROOT / "data" / "news_law_loads_pending.json"

# Field-name → human-readable label (Japanese). Mirrors the TRACKED_FIELDS
# set in refresh_amendment_diff.py — keep in sync when that list changes.
FIELD_LABELS_JA: dict[str, str] = {
    "amount_max_yen": "補助上限額",
    "subsidy_rate_max": "補助率上限",
    "program.target_entity": "対象事業者",
    "program.target_business_size": "対象事業規模",
    "program.application_period": "申請期間",
    "program.application_period_r7": "申請期間(令和7年)",
    "program.application_channel": "申請窓口",
    "program.prerequisite": "前提条件",
    "program.subsidy_rate": "補助率本文",
    "eligibility_text": "適格性テキスト (合成)",
}

# Entity record_kind → news category label (Japanese, slug-friendly).
# Programs are grouped under 補助金, tax measures under 税制, etc.
# Today only `program` rows enter the diff log — others may follow.
CATEGORY_FOR_KIND: dict[str, tuple[str, str]] = {
    "program": ("補助金", "subsidy"),
    "tax_measure": ("税制", "tax"),
    "certification": ("認定", "certification"),
    "law": ("法令", "law"),
}
DEFAULT_CATEGORY = ("補助金", "subsidy")

_KKS = pykakasi.kakasi() if pykakasi is not None else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.generate_news_posts")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _slugify(name: str, entity_id: str) -> str:
    """Hepburn-romaji slug + 6-hex suffix from entity_id (collision-free).

    Falls back to `news-{sha1-6}` when pykakasi is unavailable. We do this
    instead of erroring because the news cron should still produce output
    on minimal installs (CI smoke tests) — the slug is purely cosmetic.
    """
    suffix = hashlib.sha1(entity_id.encode("utf-8")).hexdigest()[:6]
    if _KKS is None or not name:
        return f"news-{suffix}"
    try:
        parts = _KKS.convert(name)
        romaji = " ".join(p.get("hepburn", "") for p in parts)
    except Exception:
        romaji = ""
    romaji = romaji.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "-", romaji).strip("-")
    if len(ascii_only) > 50:
        truncated = ascii_only[:50]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        ascii_only = truncated
    if not ascii_only:
        ascii_only = "news"
    return f"{ascii_only}-{suffix}"


def _parse_detected_at(s: str) -> datetime:
    """Parse SQLite TIMESTAMP into an aware UTC datetime.

    SQLite's CURRENT_TIMESTAMP returns 'YYYY-MM-DD HH:MM:SS' (no tz, UTC).
    We also tolerate ISO-8601 with 'T' and trailing 'Z'.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # SQLite's space-separated form lacks tz info — assume UTC.
    if "T" not in s and "+" not in s and "-" not in s[10:]:
        s = s.replace(" ", "T") + "+00:00"
    elif " " in s and "T" not in s:
        s = s.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Final fallback: parse as naive UTC.
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt


def _to_jst(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone(_JST)


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def _truncate(s: str, n: int = 200) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _format_value_display(field_name: str, value: str | None) -> str:
    """Cosmetic formatting for the diff table cell.

    For 'amount_max_yen' we render '1,000,000' as '1,000,000円' (still keep
    the raw number readable). For everything else we just truncate to keep
    the table from blowing out horizontally — the raw value is preserved
    in the JSON-LD payload below for crawlers.
    """
    if value is None:
        return ""
    if field_name == "amount_max_yen":
        v = value.replace(",", "").strip()
        try:
            n = int(float(v))
            return f"{n:,}円"
        except (TypeError, ValueError):
            return _truncate(value, 200)
    return _truncate(value, 200)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffRow:
    diff_id: int
    entity_id: str
    field_name: str
    prev_value: str | None
    new_value: str | None
    detected_at_utc: datetime
    source_url: str | None


@dataclass(frozen=True)
class EntityMeta:
    entity_id: str
    primary_name: str
    record_kind: str
    source_url: str | None


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _ensure_diff_table(conn: sqlite3.Connection) -> bool:
    """Verify am_amendment_diff exists. Log + return False when missing."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_amendment_diff'"
    ).fetchone()
    if row is None:
        logger.error(
            "am_amendment_diff_missing did_you_apply_migration=075_am_amendment_diff.sql"
        )
        return False
    return True


def _fetch_diff_rows(
    conn: sqlite3.Connection,
    since_utc: datetime,
) -> list[DiffRow]:
    """All diff rows with detected_at >= since_utc.

    SQLite stores TIMESTAMP as a string; we compare lexicographically
    against ISO-8601 (which SQLite uses for CURRENT_TIMESTAMP). The
    space-separated form sorts identically to T-separated for this
    purpose because the date+time prefix is fixed-width.
    """
    since_str = since_utc.strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """
        SELECT diff_id, entity_id, field_name, prev_value, new_value,
               detected_at, source_url
          FROM am_amendment_diff
         WHERE detected_at >= ?
         ORDER BY entity_id, detected_at, diff_id
        """,
        (since_str,),
    ).fetchall()
    out: list[DiffRow] = []
    for r in rows:
        try:
            dt = _parse_detected_at(r["detected_at"])
        except Exception as exc:
            logger.warning(
                "skip_diff_unparseable_detected_at diff_id=%s err=%s",
                r["diff_id"],
                exc,
            )
            continue
        out.append(
            DiffRow(
                diff_id=int(r["diff_id"]),
                entity_id=str(r["entity_id"]),
                field_name=str(r["field_name"]),
                prev_value=r["prev_value"],
                new_value=r["new_value"],
                detected_at_utc=dt,
                source_url=r["source_url"],
            )
        )
    return out


def _fetch_entity_meta(
    conn: sqlite3.Connection, entity_ids: list[str]
) -> dict[str, EntityMeta]:
    if not entity_ids:
        return {}
    qmarks = ",".join(["?"] * len(entity_ids))
    rows = conn.execute(
        f"""
        SELECT canonical_id, primary_name, record_kind, source_url
          FROM am_entities
         WHERE canonical_id IN ({qmarks})
        """,
        entity_ids,
    ).fetchall()
    out: dict[str, EntityMeta] = {}
    for r in rows:
        out[str(r["canonical_id"])] = EntityMeta(
            entity_id=str(r["canonical_id"]),
            primary_name=str(r["primary_name"] or ""),
            record_kind=str(r["record_kind"] or ""),
            source_url=r["source_url"],
        )
    return out


# ---------------------------------------------------------------------------
# Grouping + rendering
# ---------------------------------------------------------------------------


def _group_by_entity_and_jst_date(
    rows: list[DiffRow],
) -> dict[tuple[str, str], list[DiffRow]]:
    """Group diff rows by (entity_id, JST detection date).

    A program with changes spanning two JST days produces two posts (one
    per day). This is the natural URL shape — /news/YYYY/MM/DD/{slug} —
    and avoids re-publishing the same date's post when re-running.

    Within each bucket the rows are sorted deterministically by
    (field_name, diff_id) so re-runs produce byte-identical output.
    """
    buckets: dict[tuple[str, str], list[DiffRow]] = {}
    for r in rows:
        jst = _to_jst(r.detected_at_utc).date().isoformat()
        key = (r.entity_id, jst)
        buckets.setdefault(key, []).append(r)
    for key, lst in buckets.items():
        lst.sort(key=lambda x: (x.field_name, x.diff_id))
    return buckets


def _build_news_post_context(
    entity: EntityMeta,
    jst_date_iso: str,
    diffs: list[DiffRow],
    domain: str,
) -> dict[str, Any]:
    """Construct the Jinja2 render context for one news post.

    All sortable fields are sorted deterministically so re-runs against
    the same diff snapshot produce byte-identical HTML.
    """
    # Earliest detected_at within the bucket → the post's pubDate.
    detected_at_utc = min(d.detected_at_utc for d in diffs)
    detected_at_jst = _to_jst(detected_at_utc)

    category_ja, category_slug = CATEGORY_FOR_KIND.get(
        entity.record_kind, DEFAULT_CATEGORY
    )

    # Distinct field labels for the summary line.
    distinct_fields_ja: list[str] = []
    seen: set[str] = set()
    for d in diffs:
        label = FIELD_LABELS_JA.get(d.field_name, d.field_name)
        if label not in seen:
            seen.add(label)
            distinct_fields_ja.append(label)

    summary_paragraph = (
        f"{len(diffs)} 件の変更を検出しました。 "
        f"対象項目: {', '.join(distinct_fields_ja)}。 "
        f"以下の差分テーブルで before/after を確認できます。"
    )

    meta_description = (
        f"{entity.primary_name} の {len(diffs)} 件の変更を {jst_date_iso} に検出。 "
        f"対象: {', '.join(distinct_fields_ja[:5])}。"
    )

    # Per-row payloads for the diff table.
    changes_ctx: list[dict[str, Any]] = []
    for d in diffs:
        d_jst = _to_jst(d.detected_at_utc)
        changes_ctx.append(
            {
                "field_name": d.field_name,
                "field_label_ja": FIELD_LABELS_JA.get(d.field_name, d.field_name),
                "prev_value": d.prev_value,
                "new_value": d.new_value,
                "prev_value_display": _format_value_display(
                    d.field_name, d.prev_value
                ),
                "new_value_display": _format_value_display(d.field_name, d.new_value),
                "source_url": d.source_url,
                "source_domain": _domain_of(d.source_url),
                "detected_at_jst": d_jst.strftime("%Y-%m-%d %H:%M"),
            }
        )

    # JSON-LD: NewsArticle (Article superclass) + GovernmentService for
    # the program. Two top-level @graph nodes, both schema.org. Crawlers
    # can pick either as the page's primary type.
    canonical_url = (
        f"https://{domain}/news/{jst_date_iso.replace('-', '/')}/"
        f"{_slugify(entity.primary_name, entity.entity_id)}.html"
    )
    page_title = f"{entity.primary_name} に変更 ({jst_date_iso}) — お知らせ"
    json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "NewsArticle",
                "@id": canonical_url + "#newsarticle",
                "headline": f"{entity.primary_name} に変更 ({jst_date_iso})",
                "description": meta_description,
                "datePublished": detected_at_utc.isoformat(),
                "dateModified": detected_at_utc.isoformat(),
                "inLanguage": "ja",
                "url": canonical_url,
                "mainEntityOfPage": canonical_url,
                "isAccessibleForFree": True,
                "articleSection": category_ja,
                "author": {
                    "@type": "Organization",
                    "@id": "https://jpcite.com/#publisher",
                    "name": "Bookyou株式会社",
                    "url": f"https://{domain}/about.html",
                },
                "publisher": {
                    "@type": "Organization",
                    "@id": "https://jpcite.com/#publisher",
                    "name": "jpcite",
                    "alternateName": ["AutonoMath", "Bookyou株式会社"],
                    "url": f"https://{domain}/",
                    "logo": {
                        "@type": "ImageObject",
                        "url": f"https://{domain}/assets/logo.png",
                        "width": 600,
                        "height": 60,
                    },
                },
            },
            {
                "@type": "GovernmentService",
                "@id": canonical_url + "#governmentservice",
                "name": entity.primary_name,
                "url": entity.source_url or canonical_url,
                "serviceType": category_ja,
                "areaServed": {"@type": "Country", "name": "Japan"},
                "provider": {
                    "@type": "GovernmentOrganization",
                    "name": _domain_of(entity.source_url) or "Government of Japan",
                },
            },
        ],
    }

    slug = _slugify(entity.primary_name, entity.entity_id)
    year, month, day = jst_date_iso.split("-")
    # `since_iso` is what we feed the API curl example — start of the JST
    # day in UTC, the natural lower bound a customer would pass.
    since_dt = datetime.fromisoformat(jst_date_iso + "T00:00:00").replace(
        tzinfo=_JST
    ).astimezone(_UTC)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "DOMAIN": domain,
        "page_title": page_title,
        "meta_description": meta_description,
        "year": year,
        "month": month,
        "day": day,
        "slug": slug,
        "entity_id": entity.entity_id,
        "program_name": entity.primary_name,
        "category_ja": category_ja,
        "category_slug": category_slug,
        "summary_paragraph": summary_paragraph,
        "change_count": len(diffs),
        "changes": changes_ctx,
        "detected_at_iso": detected_at_utc.isoformat(),
        "detected_at_jst_date": jst_date_iso,
        "detected_at_jst_human": detected_at_jst.strftime("%Y-%m-%d %H:%M JST"),
        "source_url": entity.source_url or "",
        "source_domain": _domain_of(entity.source_url),
        "since_iso": since_iso,
        "json_ld_pretty": json.dumps(
            json_ld, ensure_ascii=False, sort_keys=True, indent=2
        ),
        "canonical_url": canonical_url,
    }


def _render_post(env: Environment, ctx: dict[str, Any]) -> str:
    tpl = env.get_template("news_post.html")
    return tpl.render(**ctx)


def _write_if_changed(path: Path, content: str) -> bool:
    """Write content only if it differs from existing file. Returns True on write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""
        if existing == content:
            return False
    path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Law full-text load detection (incremental_law_fulltext.py side-channel)
# ---------------------------------------------------------------------------


def _detect_law_loads(
    log_path: Path,
    since_utc: datetime,
    am_db_path: Path,
    pending_path: Path,
    dry_run: bool,
) -> dict[str, int]:
    """Detect newly-loaded law full-texts and stage them for emission.

    Why we stage instead of emitting HTML here:
      The existing ``news_post.html`` template is shaped around the
      ``am_amendment_diff`` payload (before/after diff table, change
      counts, etc.). A law full-text load isn't a before/after change —
      it's a one-shot "newly searchable" event that needs a different
      template. Adding ``news_law_post.html`` requires touching
      ``site/_templates/``, which is gated behind a separate review pass.
      Until that template exists, this pass writes a deterministic
      ``data/news_law_loads_pending.json`` index — when the template
      lands, a follow-up cron flushes the pending index into HTML.

    The pending index format (sorted, idempotent):
        {
          "generated_at": "2026-04-29T00:00:00+00:00",
          "since": "<window start ISO>",
          "laws": [
            {
              "canonical_id": "law:yakuji",
              "primary_name": "医薬品、医療機器等の品質、…",
              "loaded_at": "2026-04-29T00:00:00+00:00",
              "articles": 631,
              "egov_url": "https://laws.e-gov.go.jp/law/335AC0000000145",
              "license": "cc_by_4.0",
              "attribution": "出典: e-Gov法令検索 (デジタル庁)"
            },
            ...
          ]
        }

    Honesty contract:
      * Only laws that ACTUALLY have rows in ``am_law_article`` end up in
        the pending list. We cross-check against the DB so a half-failed
        load doesn't surface a phantom "now searchable" entry.
      * License + attribution are inlined per-law so the future template
        renders the CC-BY 4.0 byline correctly. e-Gov is the operator
        and the source is identified explicitly.
    """
    counters = {"log_entries_in_window": 0, "laws_pending": 0}
    if not log_path.is_file():
        logger.info("no_law_load_log path=%s", log_path)
        return counters

    # Pull all run entries from the JSONL file. Tiny log (one line per
    # weekly run), no need for streaming.
    raw_entries: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw_entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("skip_malformed_jsonl line=%d err=%s", ln, exc)

    # Filter by run_at >= since_utc.
    in_window: list[dict[str, Any]] = []
    for e in raw_entries:
        run_at_str = e.get("run_at") or ""
        try:
            run_at = _parse_detected_at(run_at_str)
        except Exception:
            continue
        if run_at >= since_utc:
            in_window.append(e)
    counters["log_entries_in_window"] = len(in_window)
    if not in_window:
        logger.info("law_loads_no_window_hits since=%s", since_utc.isoformat())
        return counters

    # Aggregate canonical_ids across all in-window runs.
    candidate_ids: set[str] = set()
    id_to_run_at: dict[str, str] = {}
    for e in in_window:
        ts = e.get("run_at") or ""
        for cid in e.get("loaded_canonical_ids", []) or []:
            cid = str(cid)
            candidate_ids.add(cid)
            # Keep the FIRST run_at we observed for that law (idempotent).
            id_to_run_at.setdefault(cid, ts)
    if not candidate_ids:
        logger.info("law_loads_no_canonical_ids in_window=%d", len(in_window))
        return counters

    # Cross-check against the DB: only include laws that genuinely have
    # rows in am_law_article right now.
    conn = connect(am_db_path)
    try:
        qmarks = ",".join("?" * len(candidate_ids))
        confirmed_rows = conn.execute(
            f"""
            SELECT l.canonical_id, l.canonical_name, l.e_gov_lawid,
                   COUNT(a.article_id) AS arts,
                   MIN(a.source_fetched_at) AS first_fetched
              FROM am_law l
              JOIN am_law_article a ON l.canonical_id = a.law_canonical_id
             WHERE l.canonical_id IN ({qmarks})
             GROUP BY l.canonical_id, l.canonical_name, l.e_gov_lawid
            """,
            list(candidate_ids),
        ).fetchall()
    finally:
        conn.close()

    laws_pending: list[dict[str, Any]] = []
    for r in confirmed_rows:
        cid = str(r["canonical_id"])
        egov = r["e_gov_lawid"] or ""
        laws_pending.append(
            {
                "canonical_id": cid,
                "primary_name": str(r["canonical_name"] or ""),
                "loaded_at": id_to_run_at.get(cid, ""),
                "articles": int(r["arts"] or 0),
                "egov_url": (
                    f"https://laws.e-gov.go.jp/law/{egov}" if egov else ""
                ),
                "license": "cc_by_4.0",
                "attribution": "出典: e-Gov法令検索 (デジタル庁)",
            }
        )
    laws_pending.sort(key=lambda x: x["canonical_id"])
    counters["laws_pending"] = len(laws_pending)

    pending_payload = {
        "generated_at": datetime.now(_UTC).isoformat(),
        "since": since_utc.isoformat(),
        "laws": laws_pending,
    }

    if dry_run:
        logger.info(
            "law_loads_would_stage laws=%d path=%s",
            len(laws_pending), pending_path,
        )
        return counters

    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(
        json.dumps(pending_payload, ensure_ascii=False,
                   sort_keys=True, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "law_loads_staged laws=%d path=%s",
        len(laws_pending), pending_path,
    )
    return counters


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(
    am_db_path: Path,
    output_dir: Path,
    since_utc: datetime,
    domain: str,
    dry_run: bool,
    include_law_loads: bool = False,
    law_load_log: Path = _LAW_LOAD_LOG,
    law_load_pending: Path = _LAW_LOAD_PENDING,
) -> dict[str, int]:
    """Generate news posts for all (entity, JST-date) buckets in the window."""
    counters = {
        "diff_rows_in_window": 0,
        "buckets": 0,
        "posts_written": 0,
        "posts_skipped_unchanged": 0,
        "missing_entity_meta": 0,
        "law_load_log_entries": 0,
        "law_loads_pending": 0,
    }

    # Side-channel: detect newly-loaded law full-texts emitted by
    # incremental_law_fulltext.py and stage them for downstream HTML
    # emission. This runs first so its log lines precede the diff
    # processing — the two passes are independent and don't share state.
    if include_law_loads:
        ll = _detect_law_loads(
            log_path=law_load_log,
            since_utc=since_utc,
            am_db_path=am_db_path,
            pending_path=law_load_pending,
            dry_run=dry_run,
        )
        counters["law_load_log_entries"] = ll["log_entries_in_window"]
        counters["law_loads_pending"] = ll["laws_pending"]

    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return counters

    if not _TEMPLATE_DIR.is_dir():
        logger.error("template_dir_missing path=%s", _TEMPLATE_DIR)
        return counters

    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )

    conn = connect(am_db_path)
    try:
        if not _ensure_diff_table(conn):
            return counters

        rows = _fetch_diff_rows(conn, since_utc)
        counters["diff_rows_in_window"] = len(rows)
        logger.info(
            "news_window_loaded since=%s rows=%d db=%s",
            since_utc.isoformat(),
            len(rows),
            am_db_path,
        )

        if not rows:
            # Honest no-op: the spec says SKIP with a log message rather
            # than emit an engagement-bait placeholder post.
            logger.info("no_posts_to_generate window_rows=0")
            return counters

        buckets = _group_by_entity_and_jst_date(rows)
        counters["buckets"] = len(buckets)

        entity_ids = sorted({k[0] for k in buckets.keys()})
        meta = _fetch_entity_meta(conn, entity_ids)

        # Process buckets in a stable order so logs / dry-run output are
        # deterministic across re-runs.
        for (entity_id, jst_date_iso) in sorted(buckets.keys()):
            bucket = buckets[(entity_id, jst_date_iso)]
            entity = meta.get(entity_id)
            if entity is None or not entity.primary_name:
                counters["missing_entity_meta"] += 1
                logger.warning(
                    "skip_missing_entity_meta entity_id=%s jst_date=%s",
                    entity_id,
                    jst_date_iso,
                )
                continue
            ctx = _build_news_post_context(entity, jst_date_iso, bucket, domain)
            html = _render_post(env, ctx)

            year, month, day = jst_date_iso.split("-")
            out_path = output_dir / year / month / day / f"{ctx['slug']}.html"

            if dry_run:
                logger.info(
                    "would_write path=%s changes=%d",
                    out_path.relative_to(_REPO_ROOT)
                    if out_path.is_absolute()
                    and str(out_path).startswith(str(_REPO_ROOT))
                    else out_path,
                    len(bucket),
                )
                counters["posts_written"] += 1
                continue

            wrote = _write_if_changed(out_path, html)
            if wrote:
                counters["posts_written"] += 1
                logger.info(
                    "wrote_post entity=%s jst_date=%s changes=%d path=%s",
                    entity_id,
                    jst_date_iso,
                    len(bucket),
                    out_path,
                )
            else:
                counters["posts_skipped_unchanged"] += 1
                logger.info(
                    "skipped_unchanged entity=%s jst_date=%s path=%s",
                    entity_id,
                    jst_date_iso,
                    out_path,
                )

        logger.info(
            "news_run_done buckets=%d written=%d unchanged=%d missing_meta=%d",
            counters["buckets"],
            counters["posts_written"],
            counters["posts_skipped_unchanged"],
            counters["missing_entity_meta"],
        )
        return counters
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Weekly news/changelog generator from am_amendment_diff."
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output directory for site/news/* (default: site/news)",
    )
    p.add_argument(
        "--window",
        type=int,
        default=7,
        help="Lookback window in days (default: 7)",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="Override start of window (ISO-8601 UTC). Trumps --window.",
    )
    p.add_argument(
        "--domain",
        type=str,
        default="jpcite.com",
        help="Canonical domain for URLs (default: jpcite.com)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — log what would be written, do not write files.",
    )
    p.add_argument(
        "--include-law-loads",
        action="store_true",
        help=(
            "Also detect newly-loaded law full-texts from "
            "data/law_load_log.jsonl (emitted by "
            "scripts/cron/incremental_law_fulltext.py) and stage them "
            "as data/news_law_loads_pending.json for downstream HTML "
            "emission. HTML emission requires a future news_law_post.html "
            "template, which is not in this change."
        ),
    )
    p.add_argument(
        "--law-load-log",
        type=Path,
        default=_LAW_LOAD_LOG,
        help=(
            "Path to the JSONL log produced by incremental_law_fulltext.py "
            f"(default: {_LAW_LOAD_LOG.relative_to(_REPO_ROOT)})"
        ),
    )
    p.add_argument(
        "--law-load-pending",
        type=Path,
        default=_LAW_LOAD_PENDING,
        help=(
            "Where to write the staged pending index (default: "
            f"{_LAW_LOAD_PENDING.relative_to(_REPO_ROOT)})"
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    if args.since:
        since_utc = _parse_detected_at(args.since).astimezone(_UTC)
    else:
        since_utc = datetime.now(_UTC) - timedelta(days=int(args.window))

    with heartbeat("generate_news_posts") as hb:
        try:
            counters = run(
                am_db_path=am_db_path,
                output_dir=args.output,
                since_utc=since_utc,
                domain=args.domain,
                dry_run=bool(args.dry_run),
                include_law_loads=bool(args.include_law_loads),
                law_load_log=args.law_load_log,
                law_load_pending=args.law_load_pending,
            )
        except Exception as e:
            logger.exception("news_generation_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("posts_written", 0) or 0)
        hb["rows_skipped"] = int(
            (counters.get("posts_skipped_unchanged", 0) or 0)
            + (counters.get("missing_entity_meta", 0) or 0)
        )
        hb["metadata"] = {
            k: counters.get(k)
            for k in (
                "diff_rows_in_window",
                "buckets",
                "law_load_log_entries",
                "law_loads_pending",
            )
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
