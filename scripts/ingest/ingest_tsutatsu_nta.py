"""Ingest 国税庁 基本通達 (tsutatsu) into autonomath.db am_law_article.

Supports: 所得税 / 法人税 / 消費税 / 相続税・財産評価 基本通達.
Primary target (2026-04-25 wave18): 所得税基本通達 (law:shotoku-zei-tsutatsu).

Usage:
  python scripts/ingest/ingest_tsutatsu_nta.py --law shotoku
  python scripts/ingest/ingest_tsutatsu_nta.py --law hojin
  python scripts/ingest/ingest_tsutatsu_nta.py --law shohi
  python scripts/ingest/ingest_tsutatsu_nta.py --law zaisan

Rules:
- Entry HTML is Shift_JIS; decode via response.read().decode('shift_jis', errors='replace').
- Normalize article number separator U+2212 / U+FF0D / U+FF65 / ASCII hyphen to '-'.
- Preserve 「の」 eda-ban (例 36-8の2).
- article_kind = 'tsutatsu'.
- Delete existing placeholder rows before insert (law_canonical_id + article_kind IN
  ('notice','tsutatsu')) so re-runs are idempotent and old stale placeholders are purged.
- SQLite BEGIN IMMEDIATE with busy_timeout=300000.
- 1 req / 0.8s polite delay.
- No Anthropic API, no aggregators.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"

NTA_BASE = "https://www.nta.go.jp"
UA = "AutonoMath/0.1.0 (+https://bookyou.net; sss@bookyou.net)"

# law key -> (canonical_id, entry path)
LAW_CONFIG: dict[str, tuple[str, str]] = {
    "shotoku": ("law:shotoku-zei-tsutatsu", "/law/tsutatsu/kihon/shotoku/01.htm"),
    "hojin": ("law:hojin-zei-tsutatsu", "/law/tsutatsu/kihon/hojin/01.htm"),
    "shohi": ("law:shohi-zei-tsutatsu", "/law/tsutatsu/kihon/shohi/01.htm"),
    "zaisan": ("law:zaisan-hyoka-tsutatsu", "/law/tsutatsu/kihon/sisan/hyoka/01.htm"),
    "sozoku": ("law:sozoku-zei-tsutatsu", "/law/tsutatsu/kihon/sisan/sozoku2/01.htm"),
}

# separators to normalize to ASCII hyphen (article number delimiter)
SEP_RE = re.compile(r"[−－ー‐\-―]")
# article number grammar supporting all NTA tsutatsu shapes observed:
#   36-1           -> 所得税 通則通達 (簡単形)
#   36-8の2        -> 枝番 after main
#   137の2-1       -> 枝番 on 法条 then 通達番号
#   48の2-3        -> 同上
#   36・37共-1     -> 法条共通通達 (中点 connecting laws + 共 marker)
#   23〜35共-1     -> 連続法条の共通通達
#   181〜223共-1   -> 同上
#   2-4の3         -> 枝番深化
#   9-2-1          -> 3 階層 (法人税でもよく出る)
#   1              -> 附則通達 (single digit)
#
# We capture (law_part, eda_law, second, eda_second, third, eda_third, kyou_marker)
# where law_part is either a single int or a composite like "36・37" / "23〜35" /
# "181〜223" / "74・75". kyou_marker is "共" if present.

# high-level: "<law>(共)? SEP <seq>(?:の<eda>)?(?: SEP <sub>(?:の<eda2>)?)?
# law is: digit(s)(の\d+)?  optionally concatenated via ・ or 〜 with another digit(s)(の\d+)?
LAW_TOKEN = r"\d+(?:の\d+)?(?:[・〜]\d+(?:の\d+)?)*"
ART_NUM_RE = re.compile(
    rf"^(?P<law>{LAW_TOKEN})"
    r"(?P<kyou>共)?"
    r"(?:[−－ー‐\-―]"
    r"(?P<seq>\d+)"
    r"(?:の(?P<eda1>\d+))?"
    r"(?:[−－ー‐\-―](?P<sub>\d+)(?:の(?P<eda2>\d+))?)?"
    r")?"
)
# "suppl-only" form: a bare integer at start (附則通達 40/01).
SUPPL_RE = re.compile(r"^(\d+)(?!\d)")
# revision history bracket at body tail
REV_RE = re.compile(r"[（(]([^（）()]*?(?:改正|追加|削除)[^（）()]*?)[)）]\s*$")


@dataclasses.dataclass
class Notice:
    article_number: str  # e.g. 36-1 / 36-8の2 / 161-1-2
    article_number_sort: float
    title: str
    text_full: str
    source_url: str


def fetch(url: str, *, retries: int = 3, delay: float = 0.8) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
                raw = resp.read()
            return raw.decode("shift_jis", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_err}")


def enumerate_subpages(entry_html: str, law_key: str) -> list[str]:
    """Return absolute URLs of content sub-pages (deduped, no fragments)."""
    soup = BeautifulSoup(entry_html, "html.parser")
    body = soup.find("div", class_="imp-cnt-tsutatsu") or soup
    prefix = f"/law/tsutatsu/kihon/{law_key}/"
    seen: set[str] = set()
    out: list[str] = []
    for a in body.find_all("a", href=True):
        href = a["href"]
        if not href.startswith(prefix):
            continue
        # drop fragment, keep path
        path = href.split("#", 1)[0]
        # skip entry page itself / menu pages
        last = path.rsplit("/", 1)[-1]
        # top-level entry itself. 00/01.htm (前文) is fine: path contains "/00/"
        if last in ("01.htm",) and path == prefix + "01.htm":
            continue
        if path in seen:
            continue
        seen.add(path)
        out.append(urllib.parse.urljoin(NTA_BASE, path))
    return out


def normalize_separators(s: str) -> str:
    return SEP_RE.sub("-", s)


def parse_article_number(head: str) -> tuple[str, float] | None:
    """Parse leading tokens of a <p class=indent1><strong> element.

    Returns (normalized_number, sort_float) or None.
    head example: "36−1", "36-8の2", "161-1-2", "9-2-1", "22-1-1の2", "9-6の2".
    """
    text = head.strip().replace("　", " ").strip()
    # strip any leading non-digit (rare)
    m = ART_NUM_RE.match(text)
    if not m:
        return None
    gd = m.groupdict()
    a = gd["law"]  # law part: "1" / "12の2" / "36・37"
    b = gd["seq"]  # 2nd level
    c1 = gd["eda1"]  # eda after seq -> "Bの<eda1>"
    c2 = gd["sub"]  # 3rd level
    d1 = gd["eda2"]  # eda after sub -> "B-Cの<eda2>"
    if not b:
        # bare integer (附則通達 etc.) — treat law part as full number
        try:
            sort = float(int(a.split("・")[0].split("〜")[0].split("の")[0]))
        except ValueError:
            sort = 0.0
        return a, sort
    # build normalized: a-b[-c2] then possibly のN
    parts_main: list[str] = [a, b]
    if c2:  # a-b-c2[のd1]
        parts_main.append(c2)
        main = "-".join(parts_main)
        if d1:
            main = f"{main}の{d1}"
    else:
        main = "-".join(parts_main)
        if c1:
            main = f"{main}の{c1}"
    # sort float: a + b/1000 + c/1e6 + eda/1e9
    # composite law (e.g. "36・37" / "23〜35") -> use first int
    a_first = a.split("・")[0].split("〜")[0]
    a_main = a_first.split("の")[0]
    a_eda = a_first.split("の")[1] if "の" in a_first else "0"
    try:
        ai = int(a_main)
        ai_eda = int(a_eda)
        bi = int(b)
        ci = int(c2) if c2 else 0
        ei = int(c1 if c1 and not c2 else d1 or 0)
        sort = ai + ai_eda / 100.0 + bi / 1000.0 + ci / 1_000_000.0 + ei / 1_000_000_000.0
    except ValueError:
        sort = 0.0
    return main, sort


def extract_notices(sub_url: str, html: str) -> list[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="imp-cnt-tsutatsu") or soup
    out: list[Notice] = []
    # walk children in document order; track current <h2> title and current fragment id
    current_title: str = ""
    current_frag: str = ""
    for el in body.descendants:
        if not isinstance(el, Tag):
            continue
        # track fragment anchors
        if el.name in {"h1", "p"} and el.get("id"):
            fid = el.get("id", "")
            if isinstance(fid, str) and fid.startswith("a"):
                current_frag = fid
        if el.name == "h2":
            t = el.get_text(" ", strip=True)
            # strip outer brackets full/half
            t = t.strip().strip("（）()").strip("〔〕").strip()
            current_title = t
            # h2 may carry id too
            hid = el.get("id")
            if isinstance(hid, str) and hid:
                current_frag = hid
        elif el.name == "p" and "indent1" in (el.get("class") or []):
            strongs = el.find_all("strong")
            if not strongs:
                continue
            # some pages split the number across multiple <strong>, e.g.
            # "<strong>2</strong><strong>−1　</strong>...". Concatenate consecutive
            # leading strongs that sit at the start of the <p>.
            head_parts: list[str] = []
            for s in strongs:
                t = s.get_text("", strip=False)
                if t:
                    head_parts.append(t)
                # stop if first non-number char after we already have a number
                if len(head_parts) >= 2 and re.search(r"\d+[−－ー‐-―-]\d+", "".join(head_parts)):
                    break
            head = "".join(head_parts)
            parsed = parse_article_number(head)
            if not parsed:
                continue
            art_num, sort_val = parsed
            chunks: list[str] = []
            # full paragraph text, strip leading number/spacing
            p_text = el.get_text(" ", strip=True)
            # strip any combination of digits + separators + の + digits at the start
            p_text = re.sub(
                r"^\s*\d+\s*[−－ー‐\-―]\s*\d+(?:\s*の\s*\d+)?"
                r"(?:\s*[−－ー‐\-―]\s*\d+(?:\s*の\s*\d+)?)?\s*",
                "",
                p_text,
            )
            chunks.append(p_text)

            # walk next siblings
            sib = el.next_sibling
            while sib is not None:
                if isinstance(sib, NavigableString):
                    sib = sib.next_sibling
                    continue
                if not isinstance(sib, Tag):
                    break
                if sib.name == "hr":
                    break
                if sib.name == "h1":
                    break
                if sib.name == "h2":
                    break
                if sib.name == "p":
                    cls = sib.get("class") or []
                    if "indent1" in cls:
                        break
                    if any(c in cls for c in ("center", "txt-big")):
                        break
                    txt = sib.get_text(" ", strip=True)
                    if txt:
                        chunks.append(txt)
                elif sib.name == "div":
                    cls = sib.get("class") or []
                    if "page-header" in cls:
                        break
                    txt = sib.get_text(" ", strip=True)
                    if txt:
                        chunks.append(txt)
                elif sib.name == "ul":
                    txt = sib.get_text(" ", strip=True)
                    if txt:
                        chunks.append(txt)
                sib = sib.next_sibling
            body_text = "\n".join(c for c in chunks if c).strip()
            if not body_text:
                continue

            frag = f"#{current_frag}" if current_frag else ""
            # Store article_number as pure 'X-Y-Z' (no prefix). article_kind
            # disambiguates tsutatsu vs main/shikoryo.
            notice = Notice(
                article_number=art_num,
                article_number_sort=sort_val,
                title=current_title,
                text_full=body_text,
                source_url=f"{sub_url}{frag}",
            )
            out.append(notice)
    return out


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=300.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 300000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def upsert(
    conn: sqlite3.Connection, law_id: str, notices: Sequence[Notice], *, fetched_at: str
) -> int:
    # dedupe within batch on article_number (keep first)
    seen: set[str] = set()
    uniq: list[Notice] = []
    for n in notices:
        if n.article_number in seen:
            continue
        seen.add(n.article_number)
        uniq.append(n)

    # Use per-row BEGIN IMMEDIATE to keep lock-hold short while coexisting with
    # parallel autonomath.db writers. Pre-purge in one transaction first.
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """DELETE FROM am_law_article
               WHERE law_canonical_id=?
                 AND article_kind IN ('notice','tsutatsu');""",
            (law_id,),
        )
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise

    inserted = 0
    for n in uniq:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute(
                """INSERT INTO am_law_article
                   (law_canonical_id, article_number, article_number_sort, title,
                    text_summary, text_full, effective_from, effective_until, last_amended,
                    source_url, source_fetched_at, article_kind)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'tsutatsu')
                   ON CONFLICT(law_canonical_id, article_number) DO UPDATE SET
                       article_number_sort = excluded.article_number_sort,
                       title               = excluded.title,
                       text_summary        = excluded.text_summary,
                       text_full           = excluded.text_full,
                       source_url          = excluded.source_url,
                       source_fetched_at   = excluded.source_fetched_at,
                       article_kind        = 'tsutatsu';""",
                (
                    law_id,
                    n.article_number,
                    n.article_number_sort,
                    n.title[:500] if n.title else None,
                    (n.text_full or "")[:500],
                    n.text_full,
                    None,
                    None,
                    None,
                    n.source_url,
                    fetched_at,
                ),
            )
            conn.execute("COMMIT;")
            inserted += 1
        except Exception:
            conn.execute("ROLLBACK;")
            raise
    return inserted


def integrity_check(conn: sqlite3.Connection, law_id: str) -> dict:
    row_count = conn.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=? AND article_kind='tsutatsu';",
        (law_id,),
    ).fetchone()[0]
    dupes = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT article_number FROM am_law_article
             WHERE law_canonical_id=? AND article_kind='tsutatsu'
             GROUP BY article_number HAVING COUNT(*)>1)""",
        (law_id,),
    ).fetchone()[0]
    null_body = conn.execute(
        """SELECT COUNT(*) FROM am_law_article
           WHERE law_canonical_id=? AND article_kind='tsutatsu'
             AND (text_full IS NULL OR text_full='')""",
        (law_id,),
    ).fetchone()[0]
    parent = conn.execute(
        "SELECT 1 FROM am_law WHERE canonical_id=?;",
        (law_id,),
    ).fetchone()
    pragma = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    return {
        "rows": row_count,
        "duplicates": dupes,
        "empty_body": null_body,
        "parent_exists": bool(parent),
        "integrity_check": pragma,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law", required=True, choices=sorted(LAW_CONFIG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-pages", type=int, default=0, help="debug: cap sub-pages")
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    law_id, entry_path = LAW_CONFIG[args.law]
    entry_url = urllib.parse.urljoin(NTA_BASE, entry_path)
    print(f"[tsutatsu/{args.law}] entry={entry_url}", flush=True)
    entry_html = fetch(entry_url)
    subs = enumerate_subpages(entry_html, args.law)
    print(f"[tsutatsu/{args.law}] sub-pages discovered: {len(subs)}", flush=True)
    if args.limit_pages > 0:
        subs = subs[: args.limit_pages]

    all_notices: list[Notice] = []
    t0 = time.time()
    for i, sub in enumerate(subs, 1):
        try:
            html = fetch(sub)
            notes = extract_notices(sub, html)
            all_notices.extend(notes)
            print(
                f"  [{i}/{len(subs)}] {sub.rsplit('/', 2)[-2]}/{sub.rsplit('/', 1)[-1]} -> {len(notes)} notices",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERR {i}/{len(subs)}] {sub}: {exc}", file=sys.stderr, flush=True)
        time.sleep(args.delay)
    dt = time.time() - t0
    print(f"[tsutatsu/{args.law}] parsed {len(all_notices)} notices in {dt:.1f}s", flush=True)

    if args.dry_run:
        for n in all_notices[:5]:
            print(n)
        return 0

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = connect(Path(args.db))
    try:
        inserted = upsert(conn, law_id, all_notices, fetched_at=fetched_at)
        report = integrity_check(conn, law_id)
    finally:
        conn.close()
    print(f"[tsutatsu/{args.law}] inserted={inserted}", flush=True)
    print(f"[tsutatsu/{args.law}] integrity={report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
