#!/usr/bin/env python3
"""ingest_egov_law_translation.py — JLT (日本法令外国語訳) → am_law_article.body_en.

Purpose
-------
Populate the ``am_law_article.body_en`` column (added by migration
``090_law_article_body_en.sql``) by harvesting hand-translated English
article bodies from the Ministry of Justice's "日本法令外国語訳DBシステム"
(https://www.japaneselawtranslation.go.jp, CC-BY 4.0). Walks the JLT
catalog, fetches each bilingual detail page, parses the alternating
JP/EN article paragraphs out of the static HTML, and writes the EN body
to autonomath.db using ``INSERT OR REPLACE`` matched on
``(law_canonical_id, article_number)``.

The Japanese (``text_full``) side is **not** modified — that column is
fed by ``scripts/ingest/ingest_law_articles_egov.py`` from the e-Gov
法令 API v2 XML and remains the legally authoritative text. ``body_en``
is courtesy translation only and the disclaimer string burned into
migration 090 is reproduced verbatim by every API/MCP response that
exposes it (see ``src/jpintel_mcp/api/laws.py``).

Design
------
* **HTML parse only.** Pure ``urllib`` + ``html.parser`` + regex. NO
  ``anthropic`` / ``openai`` / ``claude_agent_sdk`` import — the CI
  guard ``tests/test_no_llm_in_production.py`` enforces this and the
  CLAUDE.md "no LLM under scripts/etl/" rule covers it. The translation
  itself is the JLT-supplied human translation; we only extract it.
* **Primary source.** Every row lands with ``body_en_source_url`` set
  to the canonical ``/ja/laws/view/<view_id>`` URL and
  ``body_en_license = 'cc_by_4.0'`` (the migration default). We do
  **not** rewrite via aggregator URLs — that would violate the
  primary-source data hygiene rule.
* **Polite walk.** 3 second sleep between requests (per the offline
  inbox convention), ``User-Agent: jpcite-research/1.0
  (+https://jpcite.com/about)``, 30s timeout, 2 retries on 5xx.
* **Resumable.** ``tools/offline/_inbox/egov_law_translation/_progress.json``
  records ``next_view_id`` / ``completed_view_ids`` / per-view stats so
  re-running picks up where the last run stopped.
* **Catalog walk strategy.** The JLT search SPA requires a CSRF token
  for POST queries to ``/ja/laws/result/`` — we deliberately avoid
  scraping the search UI. Instead we enumerate detail pages directly
  by ``view_id`` (1..N). View IDs are stable integers; deprecated IDs
  302-redirect to current ones, gaps return 404, and the live range
  empirically caps around 5,500 (verified 2026-05-05). Resolved
  redirect URLs are recorded so the same canonical ``view_id`` is not
  re-fetched on the next run.
* **Match key.** Each parsed article ships with ``article_number`` in
  the ``am_law_article`` shape ('1', '13_2', '42_4_3'). We resolve the
  target ``law_canonical_id`` via either:
    - ``--canonical-id LAW`` CLI override (smoke test), OR
    - ``--auto-resolve``: lookup ``am_law.canonical_id`` by JLT page
      title (Japanese, exact match against ``canonical_name``).
  Articles whose ``(law_canonical_id, article_number)`` row does not
  exist in ``am_law_article`` are **skipped** (we do not synthesize
  new rows from translation alone — JP-side text is the canonical
  parent and must precede EN backfill).

Smoke test
----------
::

    .venv/bin/python scripts/etl/ingest_egov_law_translation.py \\
        --view-id 4241 \\
        --canonical-id law:koju-ho \\
        --egov-law-id 415AC1000000086

(415AC1000000086 = Act on the Protection of Personal Information; JLT
view_id 4241. The DB-side ``law:koju-ho`` row exists in ``am_law``
but has zero articles in ``am_law_article`` as of 2026-05-05, so the
smoke insert lands fresh rows scoped to body_en + provenance only.)

After run:

    sqlite3 autonomath.db \\
      "SELECT COUNT(*) FROM am_law_article WHERE body_en IS NOT NULL;"

CLI
---
::

    --view-id N                Single JLT view to fetch (smoke)
    --canonical-id law:foo     Override canonical_id mapping (smoke)
    --egov-law-id 415AC...     Override e-Gov law_id (smoke; provenance)
    --walk                     Catalog walk view_id 1..--max-view-id
    --max-view-id 6000         Upper bound for --walk
    --resume                   Resume from _progress.json next_view_id
    --auto-resolve             Resolve canonical_id from JLT page title
    --db PATH                  Override autonomath.db path
    --sleep 3.0                Per-request sleep seconds
    --dry-run                  Parse + print, no DB write

Exit codes
----------
0  success
1  fatal (db missing, network down, parse failure on smoke)
2  no rows written (empty body or no matching am_law_article row)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_LOG = logging.getLogger("jpcite.etl.ingest_egov_law_translation")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_PROGRESS_DIR = _REPO_ROOT / "tools" / "offline" / "_inbox" / "egov_law_translation"
_PROGRESS_PATH = _PROGRESS_DIR / "_progress.json"

_BASE = "https://www.japaneselawtranslation.go.jp"
_VIEW_URL_TEMPLATE = "https://www.japaneselawtranslation.go.jp/ja/laws/view/{view_id}"

_USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
_HTTP_TIMEOUT = 30.0
_DEFAULT_SLEEP = 3.0  # per spec
_RETRIES = 2  # 2 retries on 5xx / network error (= 3 attempts)

_LICENSE = "cc_by_4.0"

# JLT detail pages embed each article as
#   <div ... id="je_chXatY[scZ]"> ... </div>
# carrying alternating Japanese + English ParagraphSentence / ItemSentence.
# We capture the article_number suffix (the part after "at"), e.g.
#   je_ch1at1        -> "1"
#   je_ch4sc2at13    -> "13"
#   je_ch10at13_2    -> "13_2"
_ANCHOR_ID_RE = re.compile(r"^je_ch[\w]+?at(?P<num>\d+(?:_\d+)*)$")

# 漢数字 → arabic mapping for "第一条" / "第十三条の二" parsing.
# JLT sometimes uses 漢数字 in <span class="ArticleTitle">第N条</span>; we
# convert defensively so the canonical article_number ('1', '13_2') matches
# the am_law_article shape regardless of the JP-side renderer.
_KANSUJI = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_KANSUJI_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _kansuji_to_int(s: str) -> int | None:
    """Convert a kansuji string ('一', '十三', '二百四十二') to int.

    Returns None on parse failure so callers can fall back to other
    extractors. Restricted to the small range needed for article numbers
    (≤ 数千) — we don't need to handle 億/兆 here.
    """
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    current = 0
    for ch in s:
        if ch in _KANSUJI:
            current = _KANSUJI[ch]
        elif ch in _KANSUJI_UNITS:
            unit = _KANSUJI_UNITS[ch]
            section += (current or 1) * unit
            current = 0
        else:
            return None
    return total + section + current


_DAI_NO_RE = re.compile(
    r"^第([〇零一二三四五六七八九十百千]+)条(?:の([〇零一二三四五六七八九十百千]+))?"
)


def _parse_jp_article_title(jp_title: str) -> str | None:
    """Extract '13_2' from '第十三条の二' or '1' from '第一条'."""
    if not jp_title:
        return None
    m = _DAI_NO_RE.match(jp_title.strip())
    if not m:
        return None
    main = _kansuji_to_int(m.group(1))
    if main is None:
        return None
    sub = _kansuji_to_int(m.group(2)) if m.group(2) else None
    return f"{main}_{sub}" if sub is not None else f"{main}"


# ---------------------------------------------------------------------------
# HTML parser — extracts (article_number, jp_text, en_text) tuples
# ---------------------------------------------------------------------------


class _LawDetailParser(HTMLParser):
    """Stream-parse a JLT detail page into a list of bilingual articles.

    The page structure is:
        <div class="Article anchor" id="je_chXatY">
          <div class="ArticleCaption">（目的）</div>     <- JP caption
          <div class="ArticleCaption">(Purpose)</div>    <- EN caption
          <div class="Paragraph">
            <div class="ParagraphSentence">
              <span class="ArticleTitle">第一条</span>本文…       <- JP body
            </div>
            <div class="ParagraphSentence">
              <span class="ArticleTitle">Article 1</span>...      <- EN body
            </div>
            <div class="Item">
              <div class="ItemSentence"><span class="ItemTitle">一</span>...</div>  <- JP item
              <div class="ItemSentence"><span class="ItemTitle">(i)</span>...</div> <- EN item
            </div>
            ...
          </div>
        </div>

    We collect ``ParagraphSentence`` and ``ItemSentence`` blocks in
    document order, alternating JP/EN. Page metadata (titles) is also
    captured for downstream auto-resolve.
    """

    _ARTICLE_CLASS_RE = re.compile(r"\bArticle\b")
    # Sentence-level blocks we capture as alternating JP/EN.
    _SENTENCE_CLASSES = ("ParagraphSentence", "ItemSentence", "SubitemSentence")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.articles: list[dict[str, Any]] = []
        self.page_title_jp: str = ""
        self.page_title_en: str = ""

        # Stack of (tag, classes, capture_buf_index_or_None)
        self._tag_stack: list[tuple[str, str, int | None]] = []
        # Currently-open article data (None if not inside an Article block)
        self._cur_article: dict[str, Any] | None = None
        # When inside a sentence block, this is the index in self._buffers
        self._cur_sentence_idx: int | None = None
        self._buffers: list[list[str]] = []
        # Title scrape (the first <title>...</title> in head)
        self._in_title = False
        self._title_buf: list[str] = []

    # ------- HTML callbacks -------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        cls = attr_dict.get("class", "")
        elem_id = attr_dict.get("id", "")

        if tag == "title":
            self._in_title = True

        # Article block boundary
        if tag == "div" and "Article" in cls.split() and elem_id.startswith("je_"):
            m = _ANCHOR_ID_RE.match(elem_id)
            if m:
                self._cur_article = {
                    "anchor_id": elem_id,
                    "article_number_anchor": m.group("num"),
                    "jp_caption": "",
                    "en_caption": "",
                    "jp_sentences": [],
                    "en_sentences": [],
                }

        # Sentence block boundary
        sentence_idx: int | None = None
        if (
            self._cur_article is not None
            and tag == "div"
            and any(c in cls.split() for c in self._SENTENCE_CLASSES)
        ):
            self._buffers.append([])
            self._cur_sentence_idx = len(self._buffers) - 1
            sentence_idx = self._cur_sentence_idx

        # ArticleCaption (alternating JP/EN within an Article)
        if self._cur_article is not None and tag == "div" and "ArticleCaption" in cls.split():
            self._buffers.append([])
            self._cur_sentence_idx = len(self._buffers) - 1
            sentence_idx = self._cur_sentence_idx
            # Mark for caption disposition on close
            self._cur_article.setdefault("_caption_buf_idxs", []).append(self._cur_sentence_idx)

        self._tag_stack.append((tag, cls, sentence_idx))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            full = "".join(self._title_buf).strip()
            self._title_buf = []
            # The page <title> is "<JP title> - 日本語／英語 - 日本法令外国語訳DBシステム"
            # We split off the trailing site name and use the leading part.
            if full:
                head = full.split(" - ", 1)[0]
                self.page_title_jp = head.strip()
                # English title is rendered in the body; we capture it later.

        if not self._tag_stack:
            return
        # Pop the matching open tag.
        for i in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[i][0] == tag:
                opened_tag, cls, sentence_idx = self._tag_stack.pop(i)
                break
        else:
            return

        # Close-out behavior for sentence/caption blocks.
        if sentence_idx is not None and self._cur_article is not None:
            text = "".join(self._buffers[sentence_idx])
            text = re.sub(r"[ \t 　]+", " ", text)
            text = re.sub(r"\s*\n+\s*", "\n", text).strip()
            cap_idxs = self._cur_article.get("_caption_buf_idxs", [])
            if sentence_idx in cap_idxs:
                # First caption = JP, second caption = EN.
                if not self._cur_article["jp_caption"]:
                    self._cur_article["jp_caption"] = text
                elif not self._cur_article["en_caption"]:
                    self._cur_article["en_caption"] = text
            else:
                # Sentence: alternating JP/EN by document order.
                jp = self._cur_article["jp_sentences"]
                en = self._cur_article["en_sentences"]
                if len(jp) <= len(en):
                    jp.append(text)
                else:
                    en.append(text)
            self._cur_sentence_idx = None

        # Close out the Article block when its outer <div> ends.
        if self._cur_article is not None and opened_tag == "div" and "Article" in cls.split():
            self._cur_article.pop("_caption_buf_idxs", None)
            self.articles.append(self._cur_article)
            self._cur_article = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
        if self._cur_sentence_idx is not None:
            self._buffers[self._cur_sentence_idx].append(data)


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


def _fetch_html(
    view_id: int, *, sleep_sec: float, timeout: float = _HTTP_TIMEOUT
) -> tuple[str, str, int]:
    """Fetch a JLT detail page. Returns (resolved_url, body_text, status_code).

    Old/deprecated view_ids 302-redirect to the current view_id; we let
    urllib follow redirects and return the resolved URL so the caller
    can record provenance. 404 is returned with empty body and the
    caller should skip.
    """
    url = _VIEW_URL_TEMPLATE.format(view_id=view_id)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ja,en;q=0.5",
        },
    )
    last_err: str | None = None
    for attempt in range(1, _RETRIES + 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                resolved = resp.geturl()
                body = resp.read().decode("utf-8", errors="replace")
                # Polite per-request sleep on success too.
                time.sleep(sleep_sec)
                return resolved, body, status
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                time.sleep(sleep_sec)
                return url, "", 404
            if 500 <= exc.code < 600 and attempt <= _RETRIES:
                _LOG.warning("fetch_5xx view_id=%d attempt=%d code=%d", view_id, attempt, exc.code)
                last_err = f"HTTP {exc.code}"
                time.sleep(2**attempt)
                continue
            time.sleep(sleep_sec)
            return url, "", exc.code
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt <= _RETRIES:
                _LOG.warning("fetch_error view_id=%d attempt=%d err=%s", view_id, attempt, last_err)
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError(f"fetch loop exhausted view_id={view_id}: {last_err}")


# ---------------------------------------------------------------------------
# Article extraction + canonical_id resolution
# ---------------------------------------------------------------------------


def parse_detail_html(html: str) -> dict[str, Any]:
    """Parse a JLT detail page into structured articles + page metadata."""
    p = _LawDetailParser()
    p.feed(html)
    p.close()

    # Article number: prefer the JP "第N条" parse (handles の枝番), fall back
    # to the anchor id captured group (always digits-and-underscores).
    out_articles: list[dict[str, Any]] = []
    for a in p.articles:
        # The first JP sentence usually starts with "第N条" inside the
        # ArticleTitle <span> — handle_data merged it into the sentence
        # text, so we re-extract here.
        jp_first = a["jp_sentences"][0] if a["jp_sentences"] else ""
        article_number_jp = _parse_jp_article_title(jp_first)
        article_number = article_number_jp or a["article_number_anchor"]

        en_body = "\n".join(s for s in a["en_sentences"] if s).strip()
        jp_body = "\n".join(s for s in a["jp_sentences"] if s).strip()
        if a["en_caption"]:
            en_body = a["en_caption"] + "\n" + en_body
        if a["jp_caption"]:
            jp_body = a["jp_caption"] + "\n" + jp_body

        if not en_body:
            continue  # skip articles with no English side
        out_articles.append(
            {
                "article_number": article_number,
                "anchor_id": a["anchor_id"],
                "body_en": en_body,
                "body_jp": jp_body,
            }
        )
    return {
        "page_title_jp": p.page_title_jp,
        "articles": out_articles,
    }


def resolve_canonical_id_by_title(con: sqlite3.Connection, jp_title: str) -> str | None:
    """Look up am_law.canonical_id by exact Japanese title match.

    Returns None on miss — caller should skip the law rather than guess.
    The JLT page title is the official Japanese law name, so an exact
    match against ``am_law.canonical_name`` is the safest resolver.
    """
    if not jp_title:
        return None
    row = con.execute(
        "SELECT canonical_id FROM am_law WHERE canonical_name = ? LIMIT 1",
        (jp_title,),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# DB writer
# ---------------------------------------------------------------------------


def write_body_en(
    con: sqlite3.Connection,
    *,
    canonical_id: str,
    articles: list[dict[str, Any]],
    source_url: str,
    fetched_at: str,
) -> dict[str, int]:
    """INSERT OR REPLACE body_en for matching am_law_article rows.

    Match key is (law_canonical_id, article_number). Articles whose row
    does not exist are skipped (we do not synthesize new rows from a
    translation alone — the JP-side text must precede EN backfill).

    Returns a dict with counts: written / skipped_missing / skipped_empty.
    """
    written = 0
    skipped_missing = 0
    skipped_empty = 0
    for art in articles:
        body_en = (art.get("body_en") or "").strip()
        article_number = art["article_number"]
        if not body_en:
            skipped_empty += 1
            continue
        row = con.execute(
            "SELECT article_id FROM am_law_article "
            "WHERE law_canonical_id=? AND article_number=? LIMIT 1",
            (canonical_id, article_number),
        ).fetchone()
        if row is None:
            skipped_missing += 1
            continue
        con.execute(
            "UPDATE am_law_article "
            "SET body_en=?, body_en_source_url=?, body_en_fetched_at=?, "
            "    body_en_license=? "
            "WHERE article_id=?",
            (body_en, source_url, fetched_at, _LICENSE, row[0]),
        )
        written += 1
    con.commit()
    return {
        "written": written,
        "skipped_missing": skipped_missing,
        "skipped_empty": skipped_empty,
    }


# ---------------------------------------------------------------------------
# Progress journal
# ---------------------------------------------------------------------------


def _load_progress() -> dict[str, Any]:
    if _PROGRESS_PATH.is_file():
        try:
            with _PROGRESS_PATH.open() as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "started_at": datetime.now(UTC).isoformat(),
        "last_updated": None,
        "next_view_id": 1,
        "completed_view_ids": [],
        "stats": {
            "fetched": 0,
            "rows_written": 0,
            "rows_skipped_missing": 0,
            "view_404": 0,
            "view_no_canonical": 0,
            "view_parse_error": 0,
        },
        "per_view": {},
    }


def _save_progress(progress: dict[str, Any]) -> None:
    _PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    progress["last_updated"] = datetime.now(UTC).isoformat()
    tmp = _PROGRESS_PATH.with_suffix(".json.tmp")
    with tmp.open("w") as fh:
        json.dump(progress, fh, ensure_ascii=False, indent=2)
    tmp.replace(_PROGRESS_PATH)


# ---------------------------------------------------------------------------
# Per-view processor
# ---------------------------------------------------------------------------


def process_view(
    *,
    view_id: int,
    canonical_id_override: str | None,
    egov_law_id_override: str | None,
    auto_resolve: bool,
    con: sqlite3.Connection | None,
    sleep_sec: float,
    dry_run: bool,
    from_file: Path | None = None,
) -> dict[str, Any]:
    """Fetch + parse + write one view. Returns a stats dict for the journal."""
    out: dict[str, Any] = {
        "view_id": view_id,
        "status": "pending",
        "page_title_jp": "",
        "canonical_id": "",
        "articles_parsed": 0,
        "rows_written": 0,
        "rows_skipped_missing": 0,
        "resolved_url": _VIEW_URL_TEMPLATE.format(view_id=view_id),
        "error": "",
    }

    if from_file is not None:
        # Local-file smoke path: skip network + sleep entirely.
        try:
            html = from_file.read_text(encoding="utf-8")
        except Exception as exc:
            out["status"] = "fetch_error"
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out
        # Provenance points at the live JLT URL; the local file is just
        # a cached copy. The caller-supplied view_id must be > 0 in
        # from-file mode for the URL to be meaningful (smoke contract).
        if view_id > 0:
            resolved_url = f"{_BASE}/ja/laws/view/{view_id}"
        else:
            resolved_url = f"file://{from_file.resolve()}"
        status = 200
    else:
        try:
            resolved_url, html, status = _fetch_html(view_id, sleep_sec=sleep_sec)
        except Exception as exc:
            out["status"] = "fetch_error"
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out

    out["resolved_url"] = resolved_url
    if status == 404:
        out["status"] = "view_404"
        return out
    if status != 200:
        out["status"] = "fetch_error"
        out["error"] = f"HTTP {status}"
        return out

    try:
        parsed = parse_detail_html(html)
    except Exception as exc:  # parser bugs surface here; bail loudly
        out["status"] = "parse_error"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["page_title_jp"] = parsed["page_title_jp"]
    out["articles_parsed"] = len(parsed["articles"])

    # Canonical ID resolution.
    canonical_id = canonical_id_override
    if canonical_id is None and auto_resolve and con is not None:
        canonical_id = resolve_canonical_id_by_title(con, parsed["page_title_jp"])
    if canonical_id is None:
        out["status"] = "no_canonical"
        return out
    out["canonical_id"] = canonical_id

    # Provenance: use the resolved /ja/laws/view/N URL (CC-BY 4.0 source).
    fetched_at = datetime.now(UTC).isoformat()
    source_url = resolved_url

    if dry_run or con is None:
        out["status"] = "dry_run"
        # Print first article preview for visual sanity.
        if parsed["articles"]:
            sample = parsed["articles"][0]
            preview = (sample["body_en"] or "")[:160].replace("\n", " ")
            print(
                f"[dry-run] view_id={view_id} canonical_id={canonical_id} "
                f"articles={len(parsed['articles'])} "
                f"sample art={sample['article_number']} preview={preview!r}"
            )
        return out

    counts = write_body_en(
        con,
        canonical_id=canonical_id,
        articles=parsed["articles"],
        source_url=source_url,
        fetched_at=fetched_at,
    )
    out["rows_written"] = counts["written"]
    out["rows_skipped_missing"] = counts["skipped_missing"]
    out["status"] = "ok" if counts["written"] > 0 else "no_match"
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    root = logging.getLogger("jpcite.etl.ingest_egov_law_translation")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Harvest JLT (日本法令外国語訳) bilingual law detail pages and "
            "populate am_law_article.body_en. CC-BY 4.0 source."
        )
    )
    p.add_argument(
        "--view-id",
        type=int,
        default=None,
        help=(
            "Single JLT view_id to fetch (smoke test). With --from-file, "
            "specifies the view_id that the cached HTML originated from "
            "so body_en_source_url records honest provenance."
        ),
    )
    target = p.add_mutually_exclusive_group(required=False)
    target.add_argument(
        "--walk",
        action="store_true",
        help="Catalog walk view_id 1..--max-view-id.",
    )
    target.add_argument(
        "--resume",
        action="store_true",
        help="Resume catalog walk from _progress.json next_view_id.",
    )
    target.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help=(
            "Parse a local cached JLT HTML file (smoke without network). "
            "Requires --view-id to record source URL provenance."
        ),
    )
    p.add_argument(
        "--max-view-id",
        type=int,
        default=6000,
        help="Upper bound for --walk / --resume (default: 6000).",
    )
    p.add_argument(
        "--canonical-id",
        default=None,
        help="Override am_law.canonical_id (e.g. law:koju-ho). Smoke only.",
    )
    p.add_argument(
        "--egov-law-id",
        default=None,
        help="Override e-Gov law_id (e.g. 415AC1000000086). Provenance only.",
    )
    p.add_argument(
        "--auto-resolve",
        action="store_true",
        help="Resolve canonical_id from JLT page title (am_law.canonical_name).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"autonomath.db path (default: {_DEFAULT_DB.relative_to(_REPO_ROOT)})",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=_DEFAULT_SLEEP,
        help=f"Per-request sleep seconds (default: {_DEFAULT_SLEEP}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + print preview, no DB write.",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if not args.dry_run and not args.db.is_file():
        _LOG.error("db_missing path=%s", args.db)
        return 1

    # Validate target selection.
    if args.from_file is None and args.view_id is None and not (args.walk or args.resume):
        _LOG.error("must specify exactly one of --view-id N, --from-file PATH, --walk, or --resume")
        return 1
    if args.from_file is not None and args.view_id is None:
        _LOG.error("--from-file requires --view-id N for honest source_url")
        return 1

    # Determine view_id range to process.
    progress = _load_progress()
    view_ids: list[int]
    if args.from_file is not None:
        view_ids = [args.view_id]  # validated non-None above
    elif args.view_id is not None:
        view_ids = [args.view_id]
    elif args.resume:
        start = int(progress.get("next_view_id", 1))
        view_ids = list(range(start, args.max_view_id + 1))
        _LOG.info("resume_from view_id=%d max=%d", start, args.max_view_id)
    else:
        view_ids = list(range(1, args.max_view_id + 1))

    if args.canonical_id and len(view_ids) > 1:
        _LOG.warning(
            "canonical_id_override set with %d view_ids; all will be written "
            "to canonical_id=%s. Use --auto-resolve for catalog walks.",
            len(view_ids),
            args.canonical_id,
        )

    con: sqlite3.Connection | None = None
    if not args.dry_run:
        con = sqlite3.connect(str(args.db), timeout=60)
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA journal_mode=WAL")

    try:
        for vid in view_ids:
            _LOG.info("view_start view_id=%d", vid)
            stats = process_view(
                view_id=vid,
                canonical_id_override=args.canonical_id,
                egov_law_id_override=args.egov_law_id,
                auto_resolve=args.auto_resolve,
                con=con,
                sleep_sec=args.sleep,
                dry_run=args.dry_run,
                from_file=args.from_file,
            )
            _LOG.info(
                "view_done view_id=%d status=%s articles=%d written=%d skipped_missing=%d title=%s",
                vid,
                stats["status"],
                stats["articles_parsed"],
                stats["rows_written"],
                stats["rows_skipped_missing"],
                stats["page_title_jp"][:40],
            )
            # Update progress journal.
            progress["per_view"][str(vid)] = stats
            progress["next_view_id"] = vid + 1
            if vid not in progress["completed_view_ids"]:
                progress["completed_view_ids"].append(vid)
            sums = progress["stats"]
            sums["fetched"] += 1
            sums["rows_written"] += stats["rows_written"]
            sums["rows_skipped_missing"] += stats["rows_skipped_missing"]
            if stats["status"] == "view_404":
                sums["view_404"] += 1
            elif stats["status"] == "no_canonical":
                sums["view_no_canonical"] += 1
            elif stats["status"] == "parse_error":
                sums["view_parse_error"] += 1
            _save_progress(progress)
    finally:
        if con is not None:
            con.close()

    total_written = progress["stats"]["rows_written"]
    _LOG.info("run_done total_rows_written=%d", total_written)
    if args.view_id is not None:
        # Smoke mode: exit 2 if no rows landed, so CI can gate.
        last = progress["per_view"].get(str(args.view_id), {})
        if last.get("rows_written", 0) == 0 and not args.dry_run:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
