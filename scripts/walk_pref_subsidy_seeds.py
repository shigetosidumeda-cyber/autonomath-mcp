#!/usr/bin/env python3
"""walk_pref_subsidy_seeds.py — 47 都道府県 + 政令市 公式 補助金 listing から program rows を抽出して jpintel.db に取り込む。

Source seeds: data/autonomath/pref_subsidy_seed_urls.json (verified 2026-04-29).
Aggregators (jGrants / gBiki / hojokin-portal / minkabu) BANNED.

Method:
  1) Read seed catalog.
  2) For each seed URL:
     a) robots.txt check (respect block, mark walker_status='robots_blocked').
     b) Fetch seed (UA: JpIntelBot/1.0).
     c) Extract child 補助金 link candidates (CSS selector + text 補助金/助成金/交付金/支援金/奨励金).
     d) For each candidate child page:
        - Fetch.
        - Extract program: title + summary + (best-effort) deadline / amount.
        - Build unified_id from sha1(child_url|title)[:10].
        - INSERT OR IGNORE into programs (idempotent on source_checksum).
  3) Append failures to data/autonomath/pref_walker_v2_failures.jsonl with disposition.

Outputs:
  - DB rows in jpintel.db .programs (only when not --dry-run).
  - data/autonomath/pref_walker_v2_failures.jsonl (jsonl, one record per failure).
  - data/autonomath/pref_walker_v2_runlog.json (per-pref counts).

Constraints:
  - NO Anthropic API. urllib + bs4 only.
  - Per-host rate limit: 1.0 req/s.
  - source_url must be on the seed pref/metro/city domain (no aggregators).
  - Honest count — do NOT inflate.

Run:
  .venv/bin/python scripts/walk_pref_subsidy_seeds.py --dry-run
  .venv/bin/python scripts/walk_pref_subsidy_seeds.py
  .venv/bin/python scripts/walk_pref_subsidy_seeds.py --pref 鳥取県 --limit-children 30
  .venv/bin/python scripts/walk_pref_subsidy_seeds.py --max-children-per-seed 25
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

try:
    import certifi  # type: ignore[import-untyped]

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

# pdfplumber is used to extract text from PDF children (e.g.
# 茨城県 / 和歌山県 publish program detail rows as PDFs hosted on the
# same pref.*.lg.jp domain — those are legitimate primary sources, just
# need PDF text extraction). Import is lazy so dry-run smoke tests
# don't fail in environments that haven't installed it yet.
try:
    import pdfplumber  # type: ignore[import-untyped]

    _HAS_PDFPLUMBER = True
except ImportError:  # noqa: BLE001
    _HAS_PDFPLUMBER = False

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "jpintel.db"
SEED_PATH = REPO_ROOT / "data" / "autonomath" / "pref_subsidy_seed_urls.json"
FAILURES_PATH = REPO_ROOT / "data" / "autonomath" / "pref_walker_v2_failures.jsonl"
RUNLOG_PATH = REPO_ROOT / "data" / "autonomath" / "pref_walker_v2_runlog.json"

UA = "JpIntelBot/1.0 (+https://jpcite.com/about)"
RATE_DELAY = 1.0  # per-host
HTTP_TIMEOUT = 30
LICENSE_DEFAULT = "gov_standard_v2.0"

# Words that strongly indicate a program / 補助金 link (not a navigation link).
PROGRAM_KEYWORDS = ("補助金", "助成金", "交付金", "支援金", "奨励金", "応援金", "給付金")

# Substrings that suggest the URL points to a program detail page.
URL_HINTS = (
    "hojokin",
    "hojo",
    "josei",
    "jyosei",
    "joseikin",
    "jyoseikin",
    "shien",
    "sien",
    "kyufukin",
    "kifu",
    "shoreikin",
)

# Minor exclusion to avoid pulling navigation / search / FAQ.
EXCLUDE_TITLES = {
    "補助金一覧",
    "助成金一覧",
    "補助金",
    "助成金",
    "支援制度",
    "支援",
    "詳細",
    "詳細はこちら",
    "こちら",
}

AMOUNT_RE = re.compile(r"(?:上限|限度|最大)[\s:]*([0-9,，]+)\s*(?:万円|百万円|億円|千円|円)")
WAREKI_RE = re.compile(r"令和(\d+)年(\d+)月(\d+)日")
DATE_RE = re.compile(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})")

# Drop these PDF-boilerplate prefix words when scoring a candidate title — they
# are 様式 / 別紙 sheet headers, not the actual program name.
PDF_TITLE_BOILERPLATE_PREFIX = (
    "別紙",
    "別表",
    "様式",
    "別添",
    "参考",
    "参考資料",
    "（参考）",
    "(参考)",
    "資料",
    "目次",
    "概要",
)
# Cap PDF text extraction (don't ingest 100-page books — only need the
# detail-page-equivalent first chunk). 8 pages covers the typical
# program leaflet (1-2 pages) + amendment table.
PDF_MAX_PAGES = 8
PDF_MAX_TEXT_CHARS = 12000
# If first 1KB of extracted text has fewer non-whitespace chars than this, treat
# the PDF as image-only / scanned and skip with walker_status='pdf_unparseable'.
PDF_MIN_TEXT_CHARS_PER_KB = 40


@dataclasses.dataclass
class ProgramCandidate:
    title: str
    url: str
    seed_url: str
    seed_pref: str
    seed_kind: str
    seed_topic: str | None


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Simple per-host rate-limiter (1 req/s default)."""

    def __init__(self, delay: float = RATE_DELAY):
        self.delay = delay
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last[host] = time.monotonic()


_LIMITER = _RateLimiter()


def fetch(url: str, *, retries: int = 2) -> tuple[int, str, str | None, bytes | None]:
    """Fetch a URL.

    Returns ``(status, text, content_type, pdf_bytes)`` where:
      - ``text`` is the decoded HTML body (empty when not HTML / on failure).
      - ``pdf_bytes`` is the raw response body when the URL is a PDF
        (by content-type OR by ``.pdf`` URL suffix). Empty otherwise.

    PDF children are pre-2026-04-29 silently dropped. As of the PDF-walker
    extension we surface the raw bytes so the caller can run pdfplumber.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    _LIMITER.wait(host)
    url_lower = url.lower()
    looks_like_pdf_by_url = url_lower.endswith(".pdf")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                ctype = resp.headers.get("Content-Type", "")
                ctype_lower = ctype.lower()
                is_pdf = "application/pdf" in ctype_lower or (
                    looks_like_pdf_by_url and "html" not in ctype_lower
                )
                if is_pdf:
                    raw = resp.read()
                    return resp.status, "", ctype, raw
                # Non-HTML, non-PDF — skip silently (zip / xls / image already
                # excluded at link-extraction time, this is defence-in-depth).
                if "html" not in ctype_lower:
                    return resp.status, "", ctype, None
                raw = resp.read()
                charset = resp.headers.get_content_charset()
                if not charset:
                    if b"shift_jis" in raw[:2048].lower() or b"x-sjis" in raw[:2048].lower():
                        charset = "cp932"
                    else:
                        charset = "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return resp.status, text, ctype, None
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 410, 451):
                return exc.code, "", None, None
            time.sleep(1.5 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    return 0, "", None, None


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


class RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            return False
        if not parsed.scheme or not parsed.hostname:
            return False
        robots_url = f"{parsed.scheme}://{parsed.hostname}/robots.txt"
        rp = self._cache.get(robots_url)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                _LIMITER.wait(parsed.hostname)
                req = urllib.request.Request(robots_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                    if resp.status == 200:
                        rp.parse(resp.read().decode("utf-8", errors="replace").splitlines())
                    else:
                        rp.parse([])
            except Exception:  # noqa: BLE001
                rp.parse([])
            self._cache[robots_url] = rp
        return rp.can_fetch(UA, url)


# ---------------------------------------------------------------------------
# Seed parsing
# ---------------------------------------------------------------------------


def is_program_link(title: str, href: str) -> bool:
    """Heuristic: link is likely a program detail page."""
    if not title or not href:
        return False
    if title.strip() in EXCLUDE_TITLES:
        return False
    if len(title) < 5:
        return False
    has_kw_in_title = any(kw in title for kw in PROGRAM_KEYWORDS)
    has_hint_in_url = any(hint in href.lower() for hint in URL_HINTS)
    return has_kw_in_title or has_hint_in_url


def extract_program_links(
    html: str,
    seed_url: str,
    seed_pref: str,
    seed_kind: str,
    seed_topic: str | None,
) -> list[ProgramCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    seed_host = urllib.parse.urlparse(seed_url).hostname or ""
    candidates: dict[str, ProgramCandidate] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        if href.lower().endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".zip", ".xls", ".xlsx", ".doc", ".docx", ".pptx")
        ):
            continue
        title = a.get_text(" ", strip=True)
        full = urllib.parse.urljoin(seed_url, href)
        # Stay on prefecture / metro / city domains.
        full_host = urllib.parse.urlparse(full).hostname or ""
        if not full_host:
            continue
        # Allow same-pref subdomains only (e.g. www.pref.* / web.pref.* / sangyo-rodo.metro.tokyo.lg.jp / city.*.lg.jp).
        # Require: hostname endswith pref.X.jp/pref.X.lg.jp OR metro.tokyo.lg.jp OR city.X.lg.jp etc., and
        # MUST share the same lg.jp / pref.X / metro.tokyo / city.X SLD with seed_host.
        seed_root = _root_lg_jp(seed_host)
        full_root = _root_lg_jp(full_host)
        if not seed_root or full_root != seed_root:
            continue
        if not is_program_link(title, href):
            continue
        if full in candidates:
            continue
        candidates[full] = ProgramCandidate(
            title=title,
            url=full,
            seed_url=seed_url,
            seed_pref=seed_pref,
            seed_kind=seed_kind,
            seed_topic=seed_topic,
        )
    return list(candidates.values())


def _root_lg_jp(host: str) -> str | None:
    """Return the host root we treat as same-organization (e.g. 'pref.tokushima.lg.jp', 'metro.tokyo.lg.jp')."""
    if not host:
        return None
    parts = host.lower().split(".")
    # pref.<name>.lg.jp or pref.<name>.jp
    if "pref" in parts:
        idx = parts.index("pref")
        if idx + 2 < len(parts):
            return ".".join(parts[idx : idx + 3])
    # metro.tokyo.lg.jp / sub.metro.tokyo.lg.jp -> 'metro.tokyo.lg.jp'
    if "metro" in parts and "tokyo" in parts:
        idx = parts.index("metro")
        if idx + 2 < len(parts):
            return ".".join(parts[idx : idx + 3])
    # city.<name>.<pref>.lg.jp / city.<name>.lg.jp -> 'city.<name>.lg.jp' (looser; match by first 3)
    if "city" in parts:
        idx = parts.index("city")
        if idx + 2 < len(parts):
            return ".".join(parts[idx : idx + 3])
    if "town" in parts:
        idx = parts.index("town")
        if idx + 2 < len(parts):
            return ".".join(parts[idx : idx + 3])
    # web.pref.hyogo.lg.jp etc are caught by the pref. branch above.
    return None


# ---------------------------------------------------------------------------
# Detail extraction
# ---------------------------------------------------------------------------


def _heuristic_extract_from_text(
    body_text: str, title: str, fallback_title: str
) -> dict[str, object]:
    """Apply amount / deadline heuristics to a body of text. Shared by HTML+PDF paths."""
    if not title:
        title = fallback_title
    summary = body_text[:600]

    # Amount
    amount_max: float | None = None
    m = AMOUNT_RE.search(body_text)
    if m:
        try:
            num = float(m.group(1).replace(",", "").replace("，", ""))
            unit = m.group(0)
            if "億円" in unit:
                amount_max = num * 10000.0
            elif "百万円" in unit:
                amount_max = num * 100.0
            elif "千円" in unit:
                amount_max = num * 0.1
            elif "万円" in unit:
                amount_max = num
            else:  # plain 円
                amount_max = num / 10000.0
        except ValueError:
            amount_max = None

    # Deadline (best-effort)
    deadline_iso: str | None = None
    m = WAREKI_RE.search(body_text)
    if m:
        yy, mm, dd = (int(x) for x in m.groups())
        try:
            deadline_iso = date(2018 + yy, mm, dd).isoformat()
        except ValueError:
            deadline_iso = None
    if not deadline_iso:
        m = DATE_RE.search(body_text)
        if m:
            try:
                deadline_iso = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                deadline_iso = None

    return {
        "title": title[:200],
        "summary": summary,
        "amount_max_man_yen": amount_max,
        "deadline_iso": deadline_iso,
    }


def extract_program(html: str, fallback_title: str) -> dict[str, object]:
    """HTML detail-page extraction (legacy path)."""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    body_text = soup.get_text(" ", strip=True)[:6000]
    return _heuristic_extract_from_text(body_text, title, fallback_title)


def _strip_pdf_boilerplate(line: str) -> str:
    """Strip 様式 / 別紙 / (参考) prefixes that obscure the real program name.

    If only a boilerplate prefix + numeric suffix is present (e.g. '様式 1'),
    return '' so the caller can move on to the next line.
    """
    s = line.strip()
    # Drop the prefix word + immediately-following separator (digit / 第N / -).
    for prefix in PDF_TITLE_BOILERPLATE_PREFIX:
        if s.startswith(prefix):
            tail = s[len(prefix) :].lstrip(" :：・-第")
            # Keep stripping numerics / Japanese ordinal noise after the prefix
            # (covers '別紙第一号' → '号 新市町村...' → '新市町村...').
            tail = re.sub(r"^[0-9０-９一二三四五六七八九十]+号?\s*", "", tail)
            # Even if tail is empty (means line was pure boilerplate like
            # '様式 1'), surface that emptiness so the caller skips this line.
            s = tail
    return s.strip()


# Lines that are clearly NOT program titles: department / division headers,
# "No. N" page numbers, single-character labels, etc.
_PDF_TITLE_REJECT_RE = re.compile(
    r"^("
    r"No\.?\s*\d+|ページ|頁|\d+/\d+"  # page numbers
    r"|.{0,15}[部課室局署]$"  # bare department headers ('総 務 部')
    r"|主管課名|担当課|問合せ先|連絡先"
    r"|目次|表紙"
    r")$"
)
# 制度名 / 事業名 marker — when present, the value AFTER is the program title.
_PDF_TITLE_MARKER_RE = re.compile(
    r"(?:制\s*度\s*名|事\s*業\s*名|補\s*助\s*金\s*名|名\s*称)\s*[:：\s]*\s*(.+)"
)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF byte-string. Returns '' on parse failure or
    when the PDF is image-only (no text layer).

    Caps at PDF_MAX_PAGES pages and PDF_MAX_TEXT_CHARS to avoid 100-page books.
    """
    if not pdf_bytes or pdf_bytes[:4] != b"%PDF":
        return ""
    if not _HAS_PDFPLUMBER:
        return ""
    import io as _io

    try:
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            chunks: list[str] = []
            total = 0
            for page in pdf.pages[:PDF_MAX_PAGES]:
                try:
                    t = page.extract_text() or ""
                except Exception:  # noqa: BLE001 — per-page failures common in malformed PDFs
                    t = ""
                if t:
                    chunks.append(t)
                    total += len(t)
                    if total >= PDF_MAX_TEXT_CHARS:
                        break
            return "\n".join(chunks)[:PDF_MAX_TEXT_CHARS]
    except Exception:  # noqa: BLE001
        return ""


def is_pdf_text_meaningful(text: str) -> bool:
    """Return True if the first ~1KB of extracted text looks like real text
    rather than gibberish from a scanned/image PDF.

    We don't OCR (out-of-scope per cron-cost constraint). The gate is: at
    least PDF_MIN_TEXT_CHARS_PER_KB non-whitespace chars in the first 1024
    characters.
    """
    if not text:
        return False
    sample = text[:1024]
    non_ws = sum(1 for c in sample if not c.isspace())
    return non_ws >= PDF_MIN_TEXT_CHARS_PER_KB


def extract_program_pdf(pdf_text: str, fallback_title: str) -> dict[str, object]:
    """PDF detail-page extraction. Mirrors the HTML path semantically.

    Title heuristic (in order):
      1. If a '制度名 / 事業名 / 補助金名 / 名称' marker line exists, use the
         value that follows. This is the structured-form path used by 茨城県 /
         福井県 PDF templates.
      2. Otherwise, take the first non-empty line that is longer than 4 chars,
         is not a 様式 / 別紙 boilerplate prefix, is not a department header
         ('総 務 部'), and is not a page number ('No. 1').
      3. Falls back to fallback_title if no suitable line exists.
    """
    title = ""
    if pdf_text:
        # Pass 1: structured marker.
        for raw_line in pdf_text.splitlines():
            line = re.sub(r"\s+", " ", raw_line.strip())
            if not line:
                continue
            m = _PDF_TITLE_MARKER_RE.search(line)
            if m:
                cand = m.group(1).strip()
                # Trim trailing 行政G / 担当 group hints that follow the title.
                cand = re.sub(r"\s+(行政G|担当G|担当課|主管.*)$", "", cand).strip()
                if cand and len(cand) >= 3:
                    title = cand
                    break
        # Pass 1b: 茨城県 form has 制度名 in column 2 with the value in
        # column 1 of the same line: '共生の地域づくり助成事業 主管課名 ...'.
        # If the marker pass missed and we see 主管課名 / 制 度 名 trailing
        # markers, treat the leading text as the title.
        if not title:
            for raw_line in pdf_text.splitlines():
                line = re.sub(r"\s+", " ", raw_line.strip())
                if not line:
                    continue
                m = re.match(r"(.+?)\s+(主管課名|制\s*度\s*名|担当課)\b", line)
                if m:
                    cand = m.group(1).strip()
                    if cand and len(cand) >= 3 and not _PDF_TITLE_REJECT_RE.match(cand):
                        title = cand
                        break
        # Pass 2: first plausible non-boilerplate line (only if no marker hit).
        if not title:
            for raw_line in pdf_text.splitlines():
                line = re.sub(r"\s+", " ", raw_line.strip())
                if not line:
                    continue
                stripped = _strip_pdf_boilerplate(line)
                if not stripped or len(stripped) < 4:
                    continue
                if _PDF_TITLE_REJECT_RE.match(stripped):
                    continue
                title = stripped
                break
    body_text = pdf_text[:6000] if pdf_text else ""
    return _heuristic_extract_from_text(body_text, title, fallback_title)


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO programs (
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
    excluded, exclusion_reason,
    crop_categories_json, equipment_category,
    target_types_json, funding_purpose_json, amount_band, application_window_json,
    enriched_json, source_mentions_json,
    source_url, source_fetched_at, source_checksum, updated_at
) VALUES (
    :unified_id, :primary_name, :aliases_json, :authority_level, :authority_name,
    :prefecture, :municipality, :program_kind, :official_url,
    :amount_max_man_yen, :amount_min_man_yen, :subsidy_rate,
    :trust_level, :tier, :coverage_score, :gap_to_tier_s_json, :a_to_j_coverage_json,
    :excluded, :exclusion_reason,
    :crop_categories_json, :equipment_category,
    :target_types_json, :funding_purpose_json, :amount_band, :application_window_json,
    :enriched_json, :source_mentions_json,
    :source_url, :source_fetched_at, :source_checksum, :updated_at
)
ON CONFLICT(unified_id) DO NOTHING
"""

FTS_INSERT_SQL = (
    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)"
)


def build_unified_id(child_url: str, title: str) -> str:
    h = hashlib.sha1(f"{child_url}|{title}".encode()).hexdigest()[:10]
    return f"UNI-pref-{h}"


def build_row(
    cand: ProgramCandidate,
    extract: dict[str, object],
    fetched_at: str,
) -> dict[str, object]:
    title = str(extract["title"])
    uid = build_unified_id(cand.url, title)
    enriched = {
        "summary": extract["summary"],
        "deadline_iso": extract["deadline_iso"],
        "license": LICENSE_DEFAULT,
        "license_attribution": (
            f"© {cand.seed_pref} / 政府標準利用規約 2.0 (gov_standard) — 出典明示で再配布可"
        ),
        "walker": "walk_pref_subsidy_seeds_v2",
        "walker_seed_url": cand.seed_url,
        "walker_seed_kind": cand.seed_kind,
        "walker_seed_topic": cand.seed_topic,
        "walker_source_kind": extract.get("_source_kind", "html"),
    }
    return {
        "unified_id": uid,
        "primary_name": title,
        "aliases_json": None,
        "authority_level": "prefectural",
        "authority_name": cand.seed_pref,
        "prefecture": cand.seed_pref,
        "municipality": None,
        "program_kind": "subsidy",
        "official_url": cand.url,
        "amount_max_man_yen": extract.get("amount_max_man_yen"),
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "official",
        "tier": "B",
        "coverage_score": None,
        "gap_to_tier_s_json": None,
        "a_to_j_coverage_json": None,
        "excluded": 0,
        "exclusion_reason": None,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": None,
        "funding_purpose_json": None,
        "amount_band": None,
        "application_window_json": (
            json.dumps({"deadline": extract["deadline_iso"]}, ensure_ascii=False)
            if extract.get("deadline_iso")
            else None
        ),
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"seed": cand.seed_url}, ensure_ascii=False),
        "source_url": cand.url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{cand.url}|{title}|{extract.get('deadline_iso')}|{extract.get('amount_max_man_yen')}".encode()
        ).hexdigest()[:16],
        "updated_at": fetched_at,
    }


def upsert(conn: sqlite3.Connection, row: dict[str, object]) -> str:
    prev = conn.execute(
        "SELECT source_checksum FROM programs WHERE unified_id = ?",
        (row["unified_id"],),
    ).fetchone()
    if prev is not None:
        return "skip"
    conn.execute(UPSERT_SQL, row)
    conn.execute(
        FTS_INSERT_SQL,
        (
            row["unified_id"],
            row["primary_name"],
            "",
            row["primary_name"],
        ),
    )
    return "insert"


# ---------------------------------------------------------------------------
# Failure logger
# ---------------------------------------------------------------------------


def append_failure(rec: dict[str, object]) -> None:
    FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FAILURES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_seeds(only_pref: str | None = None) -> list[tuple[str, str, dict[str, object]]]:
    seeds_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out: list[tuple[str, str, dict[str, object]]] = []
    for pref, lst in (seeds_data.get("prefectures") or {}).items():
        if only_pref and pref != only_pref:
            continue
        for s in lst:
            out.append((pref, "prefecture", s))
    for city, lst in (seeds_data.get("designated_cities") or {}).items():
        if only_pref and city != only_pref:
            continue
        for s in lst:
            out.append((city, "designated_city", s))
    return out


def reparse_pdf_failures(args: argparse.Namespace) -> int:
    """Re-walk only the PDF children that previously failed with disposition='http_200'.

    Reads `pref_walker_v2_failures.jsonl`, filters to rows whose URL ends in
    `.pdf` AND disposition='http_200', then for each: re-checks robots.txt,
    re-fetches as bytes, parses via pdfplumber, and INSERT-OR-IGNOREs into
    programs.

    HTML pages already ingested are NOT re-fetched.
    """
    if not FAILURES_PATH.exists():
        print(f"[ERROR] failures file not found: {FAILURES_PATH}", file=sys.stderr)
        return 2
    if not args.dry_run and not DB_PATH.exists():
        print(f"[ERROR] DB not found: {DB_PATH}", file=sys.stderr)
        return 2
    if not _HAS_PDFPLUMBER:
        print("[ERROR] pdfplumber not installed — cannot reparse PDFs.", file=sys.stderr)
        return 2

    # Load seed catalog so we can recover seed_url / seed_kind / seed_topic
    # for the PDF child (needed for the enriched_json provenance fields).
    seed_lookup: dict[str, tuple[str, str, dict[str, object]]] = {}
    seeds_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for pref, lst in (seeds_data.get("prefectures") or {}).items():
        for s in lst:
            seed_lookup.setdefault(pref, []).append(("prefecture", s))  # type: ignore[arg-type]
    for city, lst in (seeds_data.get("designated_cities") or {}).items():
        for s in lst:
            seed_lookup.setdefault(city, []).append(("designated_city", s))  # type: ignore[arg-type]

    # Load failures and filter to PDF http_200.
    pdf_failures: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    with FAILURES_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("stage") != "child":
                continue
            if rec.get("disposition") != "http_200":
                continue
            url = str(rec.get("url", ""))
            if not url.lower().endswith(".pdf"):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            if args.pref and rec.get("pref") != args.pref:
                continue
            pdf_failures.append(rec)

    print(f"PDF http_200 failures to re-parse: {len(pdf_failures)}")

    if args.dry_run:
        conn = None
    else:
        conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=300.0)
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

    fetched_at = datetime.now(UTC).isoformat()
    robots = RobotsCache()
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "attempted": 0,
            "parsed": 0,
            "unparseable": 0,
            "robots_blocked": 0,
            "fetch_failed": 0,
            "inserted": 0,
            "skipped": 0,
        }
    )

    try:
        for rec in pdf_failures:
            pref = str(rec.get("pref", ""))
            url = str(rec["url"])
            stats[pref]["attempted"] += 1

            # robots check (re-checked because some servers Disallow: /*.pdf).
            if not robots.allowed(url):
                stats[pref]["robots_blocked"] += 1
                continue

            # Recover seed metadata from catalog (best-effort: pick first seed
            # for this pref). The unified_id is keyed on (child_url|title), so
            # this only affects the enriched_json provenance fields, not idempotency.
            seed_url, seed_kind, seed_topic = "", "subsidy_listing", None
            entries = seed_lookup.get(pref) or []
            if entries:
                seed_kind = entries[0][0]
                first_seed = entries[0][1]
                seed_url = first_seed.get("url", "")
                seed_topic = first_seed.get("topic")

            cstatus, _chtml, _cctype, cpdf = fetch(url)
            if cstatus != 200 or cpdf is None:
                stats[pref]["fetch_failed"] += 1
                continue

            pdf_text = extract_pdf_text(cpdf)
            if not is_pdf_text_meaningful(pdf_text):
                stats[pref]["unparseable"] += 1
                # Re-log the honest skip-tag.
                append_failure(
                    {
                        "pref": pref,
                        "stage": "child",
                        "url": url,
                        "disposition": "pdf_unparseable",
                    }
                )
                continue
            stats[pref]["parsed"] += 1

            # Pull a candidate fallback title from the URL (last path segment
            # without .pdf) since failures.jsonl doesn't carry the original
            # link text.
            url_tail = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
            fallback_title = url_tail.removesuffix(".pdf") or pref + "_pdf"

            extract = extract_program_pdf(pdf_text, fallback_title)
            extract["_source_kind"] = "pdf"
            cand = ProgramCandidate(
                title=fallback_title,
                url=url,
                seed_url=seed_url,
                seed_pref=pref,
                seed_kind=seed_kind,
                seed_topic=seed_topic,
            )
            row = build_row(cand, extract, fetched_at)

            if args.dry_run:
                stats[pref]["inserted"] += 1
                continue
            try:
                action = upsert(conn, row)  # type: ignore[arg-type]
                if action == "insert":
                    stats[pref]["inserted"] += 1
                else:
                    stats[pref]["skipped"] += 1
            except sqlite3.IntegrityError:
                stats[pref]["skipped"] += 1
    finally:
        if conn is not None:
            conn.close()

    # Summary (uses the runlog file path with a `.pdf_reparse` suffix so it
    # doesn't overwrite the main runlog).
    reparse_log = RUNLOG_PATH.with_suffix(".pdf_reparse.json")
    reparse_log.write_text(
        json.dumps(
            {pref: dict(s) for pref, s in stats.items()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    total_attempt = sum(s["attempted"] for s in stats.values())
    total_parsed = sum(s["parsed"] for s in stats.values())
    total_skipped = sum(s["unparseable"] for s in stats.values())
    total_inserted = sum(s["inserted"] for s in stats.values())
    print()
    print("=== reparse_pdf_failures summary ===")
    print(f"PDFs attempted:      {total_attempt}")
    print(f"PDFs parsed:         {total_parsed}")
    print(f"PDFs unparseable:    {total_skipped}  (image-only / scanned)")
    print(f"new rows inserted:   {total_inserted}")
    print(f"reparse runlog:      {reparse_log}")
    print()
    print("top 10 prefectures by new rows:")
    ranked = sorted(stats.items(), key=lambda kv: kv[1]["inserted"], reverse=True)
    for pref, s in ranked[:10]:
        print(
            f"  {pref:8}  inserted={s['inserted']:>3}  parsed={s['parsed']:>3}  "
            f"unparseable={s['unparseable']}  attempt={s['attempted']}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No DB writes")
    ap.add_argument(
        "--pref", type=str, default=None, help="Run only one prefecture (e.g. '鳥取県')"
    )
    ap.add_argument(
        "--max-children-per-seed",
        type=int,
        default=40,
        help="Max child links to fetch per seed (default 40)",
    )
    ap.add_argument(
        "--limit-seeds", type=int, default=None, help="Only process N seeds total (smoke test)"
    )
    ap.add_argument(
        "--reparse-pdf-failures",
        action="store_true",
        help="Re-walk only the previously-failed PDF children "
        "(disposition='http_200' AND URL ending '.pdf'). Don't re-fetch HTML.",
    )
    args = ap.parse_args()
    if args.reparse_pdf_failures:
        return reparse_pdf_failures(args)

    if not args.dry_run and not DB_PATH.exists():
        print(f"[ERROR] DB not found: {DB_PATH}", file=sys.stderr)
        return 2
    if not SEED_PATH.exists():
        print(f"[ERROR] seed file not found: {SEED_PATH}", file=sys.stderr)
        return 2

    fetched_at = datetime.now(UTC).isoformat()
    seeds = load_seeds(args.pref)
    if args.limit_seeds:
        seeds = seeds[: args.limit_seeds]
    print(f"seeds total: {len(seeds)}")

    robots = RobotsCache()
    runlog: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "seeds": 0,
            "seed_ok": 0,
            "seed_dead": 0,
            "robots_blocked": 0,
            "candidates": 0,
            "child_ok": 0,
            "child_failed": 0,
            "inserted": 0,
            "skipped": 0,
            # PDF-walker counters (added 2026-04-29).
            "pdf_attempted": 0,
            "pdf_parsed": 0,
            "pdf_unparseable": 0,
        }
    )

    if args.dry_run:
        conn = None
    else:
        # Use autocommit (isolation_level=None, no explicit BEGIN) so each row
        # is durable on its own — avoids losing all progress to SIGPIPE / kill.
        conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=300.0)
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

    try:
        for pref, kind, seed in seeds:
            seed_url = seed["url"]
            log = runlog[pref]
            log["seeds"] = int(log["seeds"]) + 1

            # robots
            if not robots.allowed(seed_url):
                log["robots_blocked"] = int(log["robots_blocked"]) + 1
                append_failure(
                    {
                        "pref": pref,
                        "stage": "seed",
                        "url": seed_url,
                        "disposition": "robots_blocked",
                    }
                )
                print(f"  [SKIP robots] {pref}: {seed_url}")
                continue

            status, html, _ctype, _seed_pdf = fetch(seed_url)
            if status != 200 or not html:
                # Seeds are listing pages — they are HTML-only by design (a PDF
                # seed wouldn't yield child links). PDF seeds are treated as
                # dead at the seed stage.
                log["seed_dead"] = int(log["seed_dead"]) + 1
                append_failure(
                    {
                        "pref": pref,
                        "stage": "seed",
                        "url": seed_url,
                        "disposition": f"http_{status}" if status else "fetch_failed",
                    }
                )
                print(f"  [DEAD seed] {pref}: HTTP {status} {seed_url}")
                continue
            log["seed_ok"] = int(log["seed_ok"]) + 1

            cands = extract_program_links(
                html,
                seed_url,
                pref,
                seed.get("kind", "subsidy_listing"),
                seed.get("topic"),
            )
            if args.max_children_per_seed:
                cands = cands[: args.max_children_per_seed]
            log["candidates"] = int(log["candidates"]) + len(cands)
            print(f"  [seed OK] {pref}: {len(cands)} candidates from {seed_url}", flush=True)

            for cand in cands:
                # robots per child url (re-checked for PDF children — some servers
                # disallow `.pdf` paths via Disallow: /*.pdf even when the parent
                # listing is allowed).
                if not robots.allowed(cand.url):
                    append_failure(
                        {
                            "pref": pref,
                            "stage": "child",
                            "url": cand.url,
                            "disposition": "robots_blocked",
                        }
                    )
                    continue
                cstatus, chtml, cctype, cpdf = fetch(cand.url)
                if cstatus != 200:
                    log["child_failed"] = int(log["child_failed"]) + 1
                    append_failure(
                        {
                            "pref": pref,
                            "stage": "child",
                            "url": cand.url,
                            "disposition": f"http_{cstatus}" if cstatus else "fetch_failed",
                        }
                    )
                    continue

                # PDF path — extract text via pdfplumber, run same heuristics.
                if cpdf is not None:
                    log["pdf_attempted"] = int(log["pdf_attempted"]) + 1
                    pdf_text = extract_pdf_text(cpdf)
                    if not is_pdf_text_meaningful(pdf_text):
                        log["pdf_unparseable"] = int(log["pdf_unparseable"]) + 1
                        log["child_failed"] = int(log["child_failed"]) + 1
                        append_failure(
                            {
                                "pref": pref,
                                "stage": "child",
                                "url": cand.url,
                                "disposition": "pdf_unparseable",
                            }
                        )
                        continue
                    log["pdf_parsed"] = int(log["pdf_parsed"]) + 1
                    log["child_ok"] = int(log["child_ok"]) + 1
                    extract = extract_program_pdf(pdf_text, cand.title)
                    extract["_source_kind"] = "pdf"
                    row = build_row(cand, extract, fetched_at)
                # HTML path
                elif chtml:
                    log["child_ok"] = int(log["child_ok"]) + 1
                    extract = extract_program(chtml, cand.title)
                    row = build_row(cand, extract, fetched_at)
                else:
                    log["child_failed"] = int(log["child_failed"]) + 1
                    append_failure(
                        {
                            "pref": pref,
                            "stage": "child",
                            "url": cand.url,
                            "disposition": f"http_{cstatus}_no_body",
                        }
                    )
                    continue

                if args.dry_run:
                    log["inserted"] = int(log["inserted"]) + 1
                    continue
                try:
                    action = upsert(conn, row)  # type: ignore[arg-type]
                    if action == "insert":
                        log["inserted"] = int(log["inserted"]) + 1
                    else:
                        log["skipped"] = int(log["skipped"]) + 1
                except sqlite3.IntegrityError as exc:
                    log["child_failed"] = int(log["child_failed"]) + 1
                    append_failure(
                        {
                            "pref": pref,
                            "stage": "upsert",
                            "url": cand.url,
                            "disposition": f"integrity_error:{exc}",
                        }
                    )

            # Persist runlog after each seed's children are processed.
            RUNLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            RUNLOG_PATH.write_text(
                json.dumps(
                    {p: dict(s) for p, s in runlog.items()},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

        # autocommit — nothing to do here.
    except Exception:
        raise
    finally:
        if conn is not None:
            conn.close()

    # Write runlog
    RUNLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    runlog_serializable = {pref: dict(stats) for pref, stats in runlog.items()}
    RUNLOG_PATH.write_text(
        json.dumps(runlog_serializable, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Summary
    total_inserted = sum(int(s["inserted"]) for s in runlog.values())
    total_skipped = sum(int(s["skipped"]) for s in runlog.values())
    total_seed_dead = sum(int(s["seed_dead"]) for s in runlog.values())
    total_robots = sum(int(s["robots_blocked"]) for s in runlog.values())
    total_child_failed = sum(int(s["child_failed"]) for s in runlog.values())
    total_candidates = sum(int(s["candidates"]) for s in runlog.values())
    print()
    print("=== walk_pref_subsidy_seeds_v2 summary ===")
    print(f"seeds:               {len(seeds)}")
    print(f"seed_dead:           {total_seed_dead}")
    print(f"robots_blocked:      {total_robots}")
    print(f"candidates:          {total_candidates}")
    print(f"child_failed:        {total_child_failed}")
    print(f"inserted:            {total_inserted}")
    print(f"skipped(idempotent): {total_skipped}")
    print(f"runlog: {RUNLOG_PATH}")
    print(f"failures: {FAILURES_PATH}")
    print()
    print("top 15 by inserted:")
    ranked = sorted(runlog.items(), key=lambda kv: int(kv[1]["inserted"]), reverse=True)
    for pref, stats in ranked[:15]:
        print(
            f"  {pref:8}  inserted={stats['inserted']:>4}  cand={stats['candidates']:>4}  "
            f"child_fail={stats['child_failed']:>3}  seed_dead={stats['seed_dead']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
