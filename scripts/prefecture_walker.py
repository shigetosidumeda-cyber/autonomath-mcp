"""Prefecture attach walker for jpintel-mcp unified_registry.

Goal: drive prefecture-null rate from 64% down to under 10% so the
service can claim nationwide coverage. Writes proposed overrides to
data/autonomath/prefecture_overrides.json for review; does NOT touch DB.

Strategy (3-pass, in order):
  1. structured-fields pass (zero network)
       - program.eligibility_structured.regional.prefectures
       - program.eligibility.location.prefectures
       - contacts[].address prefix (47 prefectures)
       - authority_name containing a prefecture
       - primary_name containing a prefecture
       - municipality -> prefecture (bundled lookup table)
       - url subdomain (pref.xxx.jp / city.xxx.yyy.lg.jp)
  2. authority_level pass (zero network)
       - authority_level == 'national' or authority_name matches ministry
         list -> prefecture = '全国'
  3. http-fetch pass (network)
       - GET official_url, scan body for prefecture mentions near
         problem keywords (問い合わせ / 所在地 / 連絡先 / 本社 / 所管)

Re-runnable: skips programs already in the override file with
confidence >= 0.9. Partial progress saved every 500 programs.

Run: python scripts/prefecture_walker.py --limit 100
     python scripts/prefecture_walker.py --limit 6771
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import signal
import sys
import urllib.parse
import urllib.robotparser
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

REGISTRY_PATH = Path("/Users/shigetoumeda/Autonomath/data/unified_registry.json")
OUTPUT_DIR = Path("/Users/shigetoumeda/jpintel-mcp/data/autonomath")
OVERRIDES_PATH = OUTPUT_DIR / "prefecture_overrides.json"
FAILURES_PATH = OUTPUT_DIR / "prefecture_walker_failures.jsonl"
MUNI_CACHE_PATH = OUTPUT_DIR / "muni_to_prefecture.json"

USER_AGENT = "jpintel-mcp-walker/0.1 (https://autonomath.ai)"
MUNI_DATA_URL = "https://geolonia.github.io/japanese-addresses/api/ja.json"

MAX_CONCURRENT_FETCHES = 20
FETCH_TIMEOUT_SEC = 10.0
FETCH_RETRIES = 2
BODY_MAX_BYTES = 1_500_000  # 1.5 MB cap

SAVE_EVERY = 500

logger = logging.getLogger("prefecture_walker")

PREFECTURES: list[str] = [
    "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
    "沖縄県",
]
PREF_SET = set(PREFECTURES)
PREF_RE = re.compile("|".join(PREFECTURES))

# Hiragana forms that reliably stand for a prefecture when used as a
# program/brand prefix ('みやざきの持続可能な農山村づくり支援事業' -> 宮崎県).
# Conservative list: only stems with >=4 kana to reduce false positives.
HIRAGANA_PREF_STEMS: dict[str, str] = {
    "みやざき": "宮崎県",
    "ほっかいどう": "北海道",
    "あおもり": "青森県",
    "やまがた": "山形県",
    "ふくしま": "福島県",
    "いばらき": "茨城県",
    "さいたま": "埼玉県",
    "とうきょう": "東京都",
    "かながわ": "神奈川県",
    "にいがた": "新潟県",
    "いしかわ": "石川県",
    "やまなし": "山梨県",
    "しずおか": "静岡県",
    "きょうと": "京都府",
    "わかやま": "和歌山県",
    "とっとり": "鳥取県",
    "おかやま": "岡山県",
    "ひろしま": "広島県",
    "やまぐち": "山口県",
    "とくしま": "徳島県",
    "ふくおか": "福岡県",
    "ながさき": "長崎県",
    "くまもと": "熊本県",
    "おおいた": "大分県",
    "かごしま": "鹿児島県",
    "おきなわ": "沖縄県",
}
# Anchor: stem must be at the start OR preceded by a particle like 'の'
# so we don't pick up coincidental kana runs inside descriptions.
HIRAGANA_PREF_RE = re.compile(
    r"(?:^|[のをは　 ])(" + "|".join(HIRAGANA_PREF_STEMS.keys()) + r")"
)

# Short names (県/府/都 省略) used only when strongly anchored in url/host
# (避: 普通名詞と衝突).
URL_HOST_TO_PREF: dict[str, str] = {
    "hokkaido": "北海道",
    "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県", "akita": "秋田県",
    "yamagata": "山形県", "fukushima": "福島県",
    "ibaraki": "茨城県", "tochigi": "栃木県", "gunma": "群馬県",
    "saitama": "埼玉県", "chiba": "千葉県", "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県", "toyama": "富山県", "ishikawa": "石川県",
    "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県",
    "tottori": "鳥取県", "shimane": "島根県", "okayama": "岡山県",
    "hiroshima": "広島県", "yamaguchi": "山口県",
    "tokushima": "徳島県", "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県",
    "fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県",
    "kumamoto": "熊本県", "oita": "大分県", "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県", "okinawa": "沖縄県",
    "metro": "東京都",  # www.metro.tokyo.lg.jp 系
}

NATIONAL_AUTHORITY_PATTERNS = re.compile(
    "|".join([
        r"農林水産省", r"経済産業省", r"厚生労働省", r"文部科学省",
        r"国土交通省", r"環境省", r"内閣府", r"財務省", r"総務省",
        r"金融庁", r"中小企業庁", r"国税庁", r"気象庁", r"復興庁",
        r"デジタル庁", r"こども家庭庁",
        r"日本政策金融公庫", r"政策金融公庫", r"中小機構", r"NEDO",
        r"JST", r"IPA", r"JETRO",
        r"独立行政法人", r"国立研究開発法人",
    ])
)

# Keywords anchored near a prefecture mention when scraping HTML pass-3
PASS3_ANCHOR = re.compile(
    r"(?:問い合わせ|お問い合わせ|所在地|連絡先|本社所在地|所管|住所|〒\d{3}-?\d{4})"
)


@dataclass
class Override:
    prefecture: str
    source: str
    confidence: float
    evidence: str

    def to_json(self) -> dict[str, Any]:
        return {
            "prefecture": self.prefecture,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence[:240],
        }


# ---------------------------------------------------------------------------
# Data loading


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        raise FileNotFoundError(f"unified_registry not found at {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_existing_overrides() -> dict[str, dict[str, Any]]:
    if not OVERRIDES_PATH.is_file():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("overrides file corrupt, starting fresh")
        return {}


def save_overrides(overrides: dict[str, dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OVERRIDES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(OVERRIDES_PATH)


def append_failure(entry: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with FAILURES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Municipality -> prefecture lookup


def build_muni_to_prefecture(registry: dict[str, Any]) -> dict[str, str]:
    """Unambiguous muni -> pref lookup.

    Source 1: geolonia ja.json (all prefectures -> all munis, authoritative).
    Source 2: existing set-prefecture programs in registry (fills edge cases
              like '農村' but only when unambiguous).
    Ambiguous munis are omitted (caller falls back to other passes).
    """
    lookup: dict[str, set[str]] = {}

    # Source 1: geolonia (cached on disk, single fetch)
    raw = _fetch_or_cache_muni_data()
    for pref, munis in raw.items():
        if pref not in PREF_SET:
            continue
        for full in munis:
            # geolonia 'full' values look like '札幌市中央区' or
            # '石狩郡当別町'. We also register the tail token (e.g. '当別町')
            # because registry.municipality may just be the city part.
            lookup.setdefault(full, set()).add(pref)
            tail = _muni_tail(full)
            if tail:
                lookup.setdefault(tail, set()).add(pref)

    # Source 2: existing set-pref programs
    for entry in (registry.get("programs") or {}).values():
        if not isinstance(entry, dict):
            continue
        muni = entry.get("municipality")
        pref = entry.get("prefecture")
        if muni and pref and pref in PREF_SET:
            lookup.setdefault(muni, set()).add(pref)

    return {k: next(iter(v)) for k, v in lookup.items() if len(v) == 1}


def _muni_tail(full: str) -> str | None:
    """Extract the trailing city/town/village/ward name from e.g. '石狩郡当別町'.

    Returns None when we cannot isolate a clean tail.
    """
    m = re.search(r"([^郡支庁]+[市区町村])$", full)
    if not m:
        return None
    tail = m.group(1)
    # Skip e.g. '札幌市中央区' -> tail '中央区' which is ambiguous across cities
    if tail.endswith("区") and tail not in {"大田区", "世田谷区", "新宿区", "渋谷区"}:
        # 23 special wards of 東京 are handled via geolonia 'full' entries
        return None
    return tail


def _fetch_or_cache_muni_data() -> dict[str, list[str]]:
    if MUNI_CACHE_PATH.is_file():
        try:
            return json.loads(MUNI_CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    logger.info("fetching muni table from %s", MUNI_DATA_URL)
    with httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(MUNI_DATA_URL)
        r.raise_for_status()
        data = r.json()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MUNI_CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return data


# ---------------------------------------------------------------------------
# Pass 1: structured fields


def infer_from_structured(
    entry: dict[str, Any],
    muni_to_pref: dict[str, str],
) -> Override | None:
    # 1a. eligibility_structured.regional.prefectures
    es = (entry.get("eligibility_structured") or {}).get("regional") or {}
    prefs = [p for p in (es.get("prefectures") or []) if p in PREF_SET]
    if len(prefs) == 1:
        return Override(
            prefecture=prefs[0],
            source="eligibility_structured",
            confidence=0.95,
            evidence=f"eligibility_structured.regional.prefectures={prefs}",
        )

    # 1b. eligibility.location.prefectures
    loc = (entry.get("eligibility") or {}).get("location") or {}
    prefs = [p for p in (loc.get("prefectures") or []) if p in PREF_SET]
    if len(prefs) == 1:
        return Override(
            prefecture=prefs[0],
            source="eligibility_location",
            confidence=0.9,
            evidence=f"eligibility.location.prefectures={prefs}",
        )

    # 1c. contacts[].address
    for c in entry.get("contacts") or []:
        if not isinstance(c, dict):
            continue
        addr = c.get("address") or ""
        if not addr:
            continue
        m = PREF_RE.search(addr)
        if m:
            return Override(
                prefecture=m.group(0),
                source="contact_address",
                confidence=0.95,
                evidence=f"contacts.address={addr[:120]}",
            )

    # 1d. authority_name
    auth = entry.get("authority_name") or ""
    m = PREF_RE.search(auth)
    if m:
        return Override(
            prefecture=m.group(0),
            source="authority_name",
            confidence=0.9,
            evidence=f"authority_name={auth[:120]}",
        )

    # 1e. primary_name (kanji form)
    name = entry.get("primary_name") or ""
    m = PREF_RE.search(name)
    if m:
        return Override(
            prefecture=m.group(0),
            source="primary_name",
            confidence=0.85,
            evidence=f"primary_name={name[:120]}",
        )

    # 1e2. primary_name (hiragana stem, e.g. 'みやざき...')
    m = HIRAGANA_PREF_RE.search(name)
    if m:
        stem = m.group(1)
        return Override(
            prefecture=HIRAGANA_PREF_STEMS[stem],
            source="primary_name_hiragana",
            confidence=0.75,
            evidence=f"primary_name_stem={stem} name={name[:100]}",
        )

    # 1f. municipality -> prefecture lookup (unambiguous only)
    muni = entry.get("municipality")
    if muni and muni in muni_to_pref:
        return Override(
            prefecture=muni_to_pref[muni],
            source="municipality_lookup",
            confidence=0.9,
            evidence=f"municipality={muni}",
        )

    # 1g. URL host / path hints (pref.aichi.jp or city.isesaki.gunma.jp)
    url = entry.get("official_url") or ""
    pref = infer_from_url(url)
    if pref:
        return Override(
            prefecture=pref,
            source="url_host",
            confidence=0.8,
            evidence=f"official_url={url[:120]}",
        )

    return None


def infer_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return None
    if not host:
        return None
    parts = host.lower().split(".")
    # pref.aichi.jp -> parts = ['pref','aichi','jp']
    # www.city.isesaki.gunma.jp -> parts = ['www','city','isesaki','gunma','jp']
    for token in parts:
        if token in URL_HOST_TO_PREF and (
            # Guard: generic tokens like 'kyoto' may appear in non-pref hosts.
            # Require surrounding .lg.jp OR pref./metro. prefix.
            "lg" in parts or "pref" in parts or "metro" in parts
        ):
            return URL_HOST_TO_PREF[token]
    return None


# ---------------------------------------------------------------------------
# Pass 2: authority-level


def infer_from_authority_level(entry: dict[str, Any]) -> Override | None:
    al = entry.get("authority_level")
    auth = entry.get("authority_name") or ""
    name = entry.get("primary_name") or ""
    if al == "national":
        m = NATIONAL_AUTHORITY_PATTERNS.search(auth) or NATIONAL_AUTHORITY_PATTERNS.search(name)
        evidence = m.group(0) if m else f"authority_level=national authority_name={auth[:80]}"
        return Override(
            prefecture="全国",
            source="authority_level",
            confidence=1.0 if m else 0.9,
            evidence=evidence,
        )
    if al == "financial" and NATIONAL_AUTHORITY_PATTERNS.search(auth):
        # 日本政策金融公庫 is nationwide
        return Override(
            prefecture="全国",
            source="authority_level",
            confidence=0.95,
            evidence=f"authority_level=financial authority_name={auth[:80]}",
        )
    if NATIONAL_AUTHORITY_PATTERNS.search(auth) or NATIONAL_AUTHORITY_PATTERNS.search(name):
        return Override(
            prefecture="全国",
            source="authority_ministry_hint",
            confidence=0.85,
            evidence=f"ministry_hint authority_name={auth[:80]} primary_name={name[:80]}",
        )
    return None


# ---------------------------------------------------------------------------
# Pass 3: http fetch


class RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._lock = asyncio.Lock()

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            return False
        if not parsed.scheme or not parsed.hostname:
            return False
        robots_url = f"{parsed.scheme}://{parsed.hostname}/robots.txt"
        async with self._lock:
            rp = self._cache.get(robots_url)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                r = await client.get(robots_url, timeout=FETCH_TIMEOUT_SEC)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    # 404 or 403 on robots.txt: treat as allow-all
                    rp.parse([])
            except Exception:
                rp.parse([])
            async with self._lock:
                self._cache[robots_url] = rp
        return rp.can_fetch(USER_AGENT, url)


async def fetch_and_scan(
    uid: str,
    url: str,
    client: httpx.AsyncClient,
    robots: RobotsCache,
    sem: asyncio.Semaphore,
) -> Override | None:
    if not url:
        return None
    async with sem:
        try:
            allowed = await robots.allowed(client, url)
        except Exception:
            allowed = True
        if not allowed:
            append_failure({"uid": uid, "url": url, "reason": "robots_blocked"})
            return Override(
                prefecture="",
                source="blocked",
                confidence=0.0,
                evidence="robots.txt disallow",
            )
        last_err = None
        for attempt in range(FETCH_RETRIES + 1):
            try:
                r = await client.get(
                    url,
                    timeout=FETCH_TIMEOUT_SEC,
                    follow_redirects=True,
                )
                if r.status_code >= 400:
                    last_err = f"http_{r.status_code}"
                    if r.status_code in (429, 503):
                        await asyncio.sleep(1.0 + attempt)
                        continue
                    break
                body = r.text[:BODY_MAX_BYTES]
                override = scan_body_for_prefecture(body)
                if override:
                    return override
                append_failure({"uid": uid, "url": url, "reason": "no_prefecture_in_body"})
                return None
            except httpx.HTTPError as e:
                last_err = f"{type(e).__name__}:{e}"
                await asyncio.sleep(0.5 + attempt)
        append_failure({"uid": uid, "url": url, "reason": last_err or "fetch_failed"})
        return None


def scan_body_for_prefecture(body: str) -> Override | None:
    """Search body for 都道府県 near 問い合わせ/所在地/連絡先 keywords."""
    # Strip tags cheaply (we don't need structure)
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text)
    # Find anchor keywords, look at +/-150 chars
    anchors = list(PASS3_ANCHOR.finditer(text))
    for a in anchors:
        window = text[max(0, a.start() - 20): a.end() + 180]
        m = PREF_RE.search(window)
        if m:
            return Override(
                prefecture=m.group(0),
                source="http_scrape",
                confidence=0.75,
                evidence=f"anchor={a.group(0)} window={window[:160]}",
            )
    # Fallback: first prefecture mention anywhere (weaker)
    m = PREF_RE.search(text)
    if m:
        snippet = text[max(0, m.start() - 40): m.end() + 80]
        return Override(
            prefecture=m.group(0),
            source="http_scrape_weak",
            confidence=0.55,
            evidence=f"body_snippet={snippet[:160]}",
        )
    return None


# ---------------------------------------------------------------------------
# Runner


async def run_pass3_ordered(
    targets: list[tuple[str, str]],
    overrides: dict[str, dict[str, Any]],
    progress_cb,
) -> int:
    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    robots = RobotsCache()
    limits = httpx.Limits(max_connections=MAX_CONCURRENT_FETCHES * 2)
    attached = 0
    saved_counter = [0]

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        limits=limits,
        http2=False,
    ) as client:

        async def worker(uid: str, url: str) -> tuple[str, Override | None]:
            ov = await fetch_and_scan(uid, url, client, robots, sem)
            return uid, ov

        tasks = [asyncio.create_task(worker(uid, url)) for uid, url in targets]
        for fut in asyncio.as_completed(tasks):
            uid, ov = await fut
            progress_cb()
            if ov and ov.prefecture:
                overrides[uid] = ov.to_json()
                attached += 1
            elif ov and ov.source == "blocked":
                overrides[uid] = ov.to_json()  # record blocked so we skip later
            saved_counter[0] += 1
            if saved_counter[0] % SAVE_EVERY == 0:
                save_overrides(overrides)
    return attached


# ---------------------------------------------------------------------------
# Reporting


def print_report(
    overrides: dict[str, dict[str, Any]],
    touched_uids: list[str],
    registry: dict[str, Any],
) -> None:
    touched = [overrides[u] for u in touched_uids if u in overrides]
    attached = [r for r in touched if r.get("prefecture") and r.get("source") != "blocked"]
    source_counts = Counter(r["source"] for r in attached)
    conf_bins = Counter()
    for r in attached:
        c = r.get("confidence", 0)
        if c >= 0.95:
            conf_bins[">=0.95"] += 1
        elif c >= 0.9:
            conf_bins["0.90-0.94"] += 1
        elif c >= 0.8:
            conf_bins["0.80-0.89"] += 1
        elif c >= 0.7:
            conf_bins["0.70-0.79"] += 1
        else:
            conf_bins["<0.70"] += 1

    print("\n=== prefecture_walker report ===")
    print(f"programs processed : {len(touched_uids)}")
    print(f"attached           : {len(attached)} ({len(attached)/max(1,len(touched_uids))*100:.1f}%)")
    print(f"skipped/failed     : {len(touched_uids) - len(attached)}")
    print("\nby source:")
    for src, n in source_counts.most_common():
        print(f"  {src:26} {n}")
    print("\nconfidence histogram:")
    for bin_ in [">=0.95", "0.90-0.94", "0.80-0.89", "0.70-0.79", "<0.70"]:
        print(f"  {bin_:12} {conf_bins[bin_]}")
    # 10 random samples
    sample = random.sample(
        [(u, overrides[u]) for u in touched_uids if u in overrides and overrides[u].get("prefecture")],
        k=min(10, len([u for u in touched_uids if u in overrides])),
    )
    print("\n10 random samples:")
    progs = registry.get("programs") or {}
    for uid, rec in sample:
        name = (progs.get(uid) or {}).get("primary_name") or "?"
        print(
            f"  {uid}  pref={rec.get('prefecture')}  src={rec.get('source')}  "
            f"conf={rec.get('confidence')}  name={name[:40]}"
        )
        print(f"    evidence: {rec.get('evidence')[:160]}")


# ---------------------------------------------------------------------------
# Main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="max null-pref programs to process")
    parser.add_argument("--skip-pass3", action="store_true", help="skip HTTP fetch pass")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    registry = load_registry()
    programs: dict[str, dict[str, Any]] = registry.get("programs") or {}
    overrides = load_existing_overrides()
    logger.info(
        "loaded registry: %d programs, %d existing overrides",
        len(programs), len(overrides),
    )

    muni_to_pref = build_muni_to_prefecture(registry)
    logger.info("muni_to_pref table size: %d", len(muni_to_pref))

    # Select target programs: prefecture is null AND not already confidently
    # covered in overrides.
    candidates: list[tuple[str, dict[str, Any]]] = []
    for uid, entry in programs.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("prefecture"):
            continue
        ex = overrides.get(uid)
        if ex and ex.get("confidence", 0.0) >= 0.9:
            continue
        candidates.append((uid, entry))

    if args.limit > 0:
        candidates = candidates[: args.limit]
    logger.info("candidates: %d", len(candidates))

    touched_uids: list[str] = []
    pass3_targets: list[tuple[str, str]] = []

    pb = tqdm(total=len(candidates), desc="pass1+2", unit="prog") if tqdm else None
    for processed, (uid, entry) in enumerate(candidates, 1):
        touched_uids.append(uid)
        # Pass 1
        ov = infer_from_structured(entry, muni_to_pref)
        # Pass 2 (only if pass 1 missed)
        if ov is None:
            ov = infer_from_authority_level(entry)
        if ov is not None:
            overrides[uid] = ov.to_json()
        else:
            # queue for pass 3 if url exists
            url = entry.get("official_url")
            if url and not args.skip_pass3:
                pass3_targets.append((uid, url))
            else:
                append_failure({"uid": uid, "reason": "no_url_for_pass3"})
        if pb is not None:
            pb.update(1)
        elif processed % 100 == 0:
            logger.info("pass1+2 %d/%d", processed, len(candidates))
        if processed % SAVE_EVERY == 0:
            save_overrides(overrides)
    if pb is not None:
        pb.close()
    save_overrides(overrides)

    logger.info(
        "pass1+2 done: %d programs attached; %d queued for pass3",
        sum(1 for u in touched_uids if u in overrides and overrides[u].get("prefecture")),
        len(pass3_targets),
    )

    if pass3_targets and not args.skip_pass3:
        pb3 = tqdm(total=len(pass3_targets), desc="pass3", unit="fetch") if tqdm else None
        p3_progress = pb3.update if pb3 is not None else (lambda *_a, **_k: None)
        try:
            asyncio.run(run_pass3_ordered(pass3_targets, overrides, lambda: p3_progress(1)))
        finally:
            if pb3 is not None:
                pb3.close()
        save_overrides(overrides)

    print_report(overrides, touched_uids, registry)
    return 0


if __name__ == "__main__":
    # graceful SIGINT: save what we have
    def _sigint(signum, frame):  # noqa: ARG001
        print("\ninterrupted — partial state already saved every 500 programs", file=sys.stderr)
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint)
    sys.exit(main())
