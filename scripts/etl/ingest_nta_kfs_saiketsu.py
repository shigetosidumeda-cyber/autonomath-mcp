"""Ingest 国税不服審判所 公表裁決事例 (kfs.go.jp) into nta_saiketsu.

Backfill-focused expansion of the existing
`scripts/ingest/ingest_nta_corpus.py --target saiketsu` flow.
That script defaults to `recent_only_years=5` (~20 newest volumes); this one
sweeps **older volumes (43..120 by default)** to lift the construction cohort
out of the 137-row floor toward 1000+.

Spec: jpcite agent task 2026-05-05 (construction cohort薄さ解消).

  * source: https://www.kfs.go.jp/service/JP/idx/{volume_no}.html
  * volume index → cases under /service/JP/{vol}/{case_no}/index.html
  * tax types harvested from h2 headers on the volume index
  * INSERT OR IGNORE into autonomath.db nta_saiketsu (UNIQUE source_url)
  * 3 sec sleep / req (kinder than the existing 2 sec)
  * progress JSON: tools/offline/_inbox/nta_kfs_saiketsu/_progress.json
  * smoke mode (--smoke) restricts to 1 volume × 法人税 only

Usage:
  python scripts/etl/ingest_nta_kfs_saiketsu.py --smoke
  python scripts/etl/ingest_nta_kfs_saiketsu.py --vol-from 43 --vol-to 120 \
    --max-minutes 180

Encoding: kfs.go.jp older pages are shift_jis; we sniff from <meta charset>.

NO LLM. HTML+regex only. License: 'gov_standard' (KFS 公表 / PDL v1.0 ministry).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"
PROGRESS_DIR = REPO_ROOT / "tools" / "offline" / "_inbox" / "nta_kfs_saiketsu"
PROGRESS_PATH = PROGRESS_DIR / "_progress.json"

KFS_BASE = "https://www.kfs.go.jp"
UA = "AutonoMath/0.3.2 jpcite-etl (+https://bookyou.net; info@bookyou.net)"
DELAY_SEC = 3.0  # spec

# 元号→西暦
ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}
KANJI_DIGITS = {
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "元": 1,
    "十": 10,
}

_ERA_DATE_RE = re.compile(
    r"(令和|平成|昭和)\s*([元一二三四五六七八九十〇\d]+)\s*年\s*"
    r"([元一二三四五六七八九十〇\d]+)\s*月\s*"
    r"([元一二三四五六七八九十〇\d]+)\s*日"
)
# Catch e-Gov style law refs: 法第123条, 法施行令第45条 etc — kept loose intentionally
_LAW_REF_RE = re.compile(
    r"(国税通則法|所得税法|法人税法|消費税法|相続税法|印紙税法|登録免許税法|"
    r"租税特別措置法|国税徴収法|たばこ税法|酒税法|地方税法)"
    r"(?:施行令|施行規則)?第\s*(\d+)\s*条"
)


def _kanji_to_int(s: str) -> int | None:
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if "元" in s:
        return 1
    if "十" in s:
        before, _, after = s.partition("十")
        b = KANJI_DIGITS.get(before, 1) if before else 1
        a = KANJI_DIGITS.get(after, 0) if after else 0
        return b * 10 + a
    if all(c in KANJI_DIGITS for c in s):
        return int("".join(str(KANJI_DIGITS[c]) for c in s))
    try:
        return int(s)
    except ValueError:
        return None


def parse_japanese_date(text: str) -> str | None:
    if not text:
        return None
    m = _ERA_DATE_RE.search(text)
    if not m:
        return None
    era, y_raw, mo_raw, d_raw = m.groups()
    y = _kanji_to_int(y_raw)
    mo = _kanji_to_int(mo_raw)
    d = _kanji_to_int(d_raw)
    if y is None or mo is None or d is None:
        return None
    base = ERA_BASE.get(era)
    if base is None:
        return None
    return f"{base + y:04d}-{mo:02d}-{d:02d}"


def fetch(url: str, *, retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
                raw = resp.read()
                head = raw[:512].lower()
                if b"charset=utf-8" in head or b'charset="utf-8"' in head:
                    return raw.decode("utf-8", errors="replace")
                if b"charset=shift_jis" in head or b'charset="shift_jis"' in head:
                    return raw.decode("shift_jis", errors="replace")
                try:
                    return raw.decode("shift_jis")
                except UnicodeDecodeError:
                    return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
        except Exception as exc:
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_err}")


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=300.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 300000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_progress() -> dict[str, Any]:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "started_at": None,
        "last_volume": None,
        "last_case_no": None,
        "volumes_seen": 0,
        "decisions_seen": 0,
        "decisions_inserted": 0,
        "errors": 0,
        "updated_at": None,
    }


def save_progress(p: dict[str, Any]) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    p["updated_at"] = now_iso()
    PROGRESS_PATH.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_volume_index(volume_no: int) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (fiscal_period, [(case_no, tax_type, decision_url), ...])."""
    url = f"{KFS_BASE}/service/JP/idx/{volume_no}.html"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    fiscal_period = h1.get_text(" ", strip=True) if h1 else ""
    content = soup.find("div", id="contents") or soup
    out: list[tuple[str, str, str]] = []
    current_tax_type = ""
    for el in content.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue
        if el.name == "h2":
            current_tax_type = el.get_text(" ", strip=True).rstrip("関係").rstrip("法")
            continue
        if el.name == "a" and isinstance(el.get("href"), str):
            href = el["href"]
            m = re.match(r"^\.\./(\d+)/(\d+)/index\.html$", href)
            if m and int(m.group(1)) == volume_no:
                case_no = m.group(2)
                full_url = f"{KFS_BASE}/service/JP/{volume_no}/{case_no}/index.html"
                out.append((case_no, current_tax_type, full_url))
    return fiscal_period, out


def extract_law_refs(text: str) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in _LAW_REF_RE.finditer(text):
        ref = f"{m.group(1)}第{m.group(2)}条"
        if ref not in seen_set:
            seen_set.add(ref)
            seen.append(ref)
    return seen


def parse_saiketsu_decision(
    volume_no: int,
    case_no: str,
    tax_type: str,
    url: str,
    html: str,
    fiscal_period: str,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    decision_date = parse_japanese_date(title)
    content = soup.find("div", id="contents") or soup
    for sel in ["nav", "header", "footer"]:
        for tag in content.find_all(sel):
            tag.decompose()
    fulltext = content.get_text("\n", strip=True)
    summary = ""
    for p in content.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 30 and "ホーム" not in t and ">>" not in t:
            summary = t
            break
    # law_refs as JSON array — schema currently has no column; we stash into
    # decision_summary tail prefix-tagged so a future migration can reproject.
    law_refs = extract_law_refs(fulltext)
    return {
        "volume_no": volume_no,
        "case_no": case_no,
        "decision_date": decision_date,
        "fiscal_period": fiscal_period,
        "tax_type": tax_type,
        "title": title,
        "decision_summary": (summary[:2000] if summary else None),
        "fulltext": fulltext,
        "source_url": url,
        "_law_refs": law_refs,
    }


# ---------------------------------------------------------------------------
# Ingest loop
# ---------------------------------------------------------------------------


def ingest(
    conn: sqlite3.Connection,
    *,
    vol_from: int,
    vol_to: int,
    max_seconds: float,
    smoke: bool,
    tax_filter: list[str] | None,
) -> dict[str, Any]:
    t_start = time.time()
    progress = load_progress()
    progress["started_at"] = progress.get("started_at") or now_iso()

    volumes = sorted(range(vol_from, vol_to + 1), reverse=True)
    print(
        f"[kfs-saiketsu] sweeping volumes {vol_from}..{vol_to} "
        f"({len(volumes)} total), tax_filter={tax_filter or 'ALL'}, "
        f"smoke={smoke}",
        flush=True,
    )

    for volume_no in volumes:
        if time.time() - t_start > max_seconds:
            print(f"[kfs-saiketsu] time cap hit at vol={volume_no}", flush=True)
            break
        try:
            fiscal_period, cases = parse_volume_index(volume_no)
            time.sleep(DELAY_SEC)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"[kfs-saiketsu] vol={volume_no} 404 (skip)", flush=True)
                continue
            print(f"[kfs-saiketsu] vol={volume_no} HTTPError: {exc}", flush=True)
            progress["errors"] += 1
            continue
        except Exception as exc:
            print(f"[kfs-saiketsu] vol={volume_no} index failed: {exc}", flush=True)
            progress["errors"] += 1
            time.sleep(DELAY_SEC)
            continue

        progress["volumes_seen"] += 1
        if tax_filter:
            cases = [c for c in cases if c[1] in tax_filter]
        print(
            f"[kfs-saiketsu] vol={volume_no} period={fiscal_period!r} cases={len(cases)}",
            flush=True,
        )

        for case_no, tax_type, dec_url in cases:
            if time.time() - t_start > max_seconds:
                print(
                    f"[kfs-saiketsu] time cap hit at vol={volume_no} case={case_no}",
                    flush=True,
                )
                progress["last_volume"] = volume_no
                progress["last_case_no"] = case_no
                save_progress(progress)
                return progress
            progress["decisions_seen"] += 1
            existing = conn.execute(
                "SELECT 1 FROM nta_saiketsu WHERE source_url=?", (dec_url,)
            ).fetchone()
            if existing:
                progress["last_volume"] = volume_no
                progress["last_case_no"] = case_no
                continue
            try:
                page_html = fetch(dec_url)
            except urllib.error.HTTPError as exc:
                print(
                    f"[kfs-saiketsu] vol={volume_no}/{case_no} HTTPError: {exc}",
                    flush=True,
                )
                progress["errors"] += 1
                time.sleep(DELAY_SEC)
                continue
            except Exception as exc:
                print(
                    f"[kfs-saiketsu] vol={volume_no}/{case_no} fetch failed: {exc}",
                    flush=True,
                )
                progress["errors"] += 1
                time.sleep(DELAY_SEC)
                continue
            try:
                row = parse_saiketsu_decision(
                    volume_no, case_no, tax_type, dec_url, page_html, fiscal_period
                )
                pre_count = conn.total_changes
                conn.execute(
                    """INSERT OR IGNORE INTO nta_saiketsu
                       (volume_no, case_no, decision_date, fiscal_period, tax_type,
                        title, decision_summary, fulltext, source_url, license,
                        ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,'gov_standard',?)""",
                    (
                        row["volume_no"],
                        row["case_no"],
                        row["decision_date"],
                        row["fiscal_period"],
                        row["tax_type"],
                        row["title"],
                        row["decision_summary"],
                        row["fulltext"],
                        row["source_url"],
                        now_iso(),
                    ),
                )
                if conn.total_changes > pre_count:
                    progress["decisions_inserted"] += 1
                progress["last_volume"] = volume_no
                progress["last_case_no"] = case_no
            except Exception as exc:
                print(
                    f"[kfs-saiketsu] vol={volume_no}/{case_no} parse/insert failed: {exc}",
                    flush=True,
                )
                progress["errors"] += 1
            if progress["decisions_seen"] % 5 == 0:
                save_progress(progress)
            time.sleep(DELAY_SEC)
            if smoke and progress["decisions_inserted"] >= 30:
                print(
                    f"[kfs-saiketsu] smoke cap hit at {progress['decisions_inserted']} insertions",
                    flush=True,
                )
                save_progress(progress)
                return progress
    save_progress(progress)
    return progress


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument(
        "--vol-from",
        type=int,
        default=43,
        help="oldest volume to sweep (inclusive); default 43",
    )
    ap.add_argument(
        "--vol-to",
        type=int,
        default=120,
        help="newest volume to sweep (inclusive); default 120 "
        "(volumes 121..140 already covered by ingest_nta_corpus.py)",
    )
    ap.add_argument("--max-minutes", type=float, default=180.0, help="wall-clock cap")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="stop after 30 inserts; restrict to --tax-filter 法人税 if not given",
    )
    ap.add_argument(
        "--tax-filter",
        action="append",
        help="filter to specific tax_type (repeatable). e.g. --tax-filter 法人税",
    )
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    conn = connect(db)
    try:
        before = conn.execute("SELECT COUNT(*) FROM nta_saiketsu").fetchone()[0]
        print(f"[kfs-saiketsu] nta_saiketsu rows BEFORE: {before}", flush=True)
        tax_filter = args.tax_filter
        if args.smoke and not tax_filter:
            tax_filter = ["法人税"]
        result = ingest(
            conn,
            vol_from=args.vol_from,
            vol_to=args.vol_to,
            max_seconds=args.max_minutes * 60.0,
            smoke=args.smoke,
            tax_filter=tax_filter,
        )
        after = conn.execute("SELECT COUNT(*) FROM nta_saiketsu").fetchone()[0]
        print(f"[kfs-saiketsu] nta_saiketsu rows AFTER:  {after}", flush=True)
        print(f"[kfs-saiketsu] delta: +{after - before}", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
