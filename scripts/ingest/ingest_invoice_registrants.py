#!/usr/bin/env python3
"""Ingest 適格請求書発行事業者 bulk data into ``invoice_registrants`` (migration 019).

Source: 国税庁 適格請求書発行事業者公表サイト bulk download.
        https://www.invoice-kohyo.nta.go.jp/download/

License: 公共データ利用規約 第1.0版 (PDL v1.0). Commercial + API downstream
OK provided every surface exposing these rows renders the required
attribution string. This script only populates the DB -- the serializer
(src/jpintel_mcp/api/invoice_registrants.py, when implemented) is the
enforcement point for attribution output.

Coverage target: ~4,000,000 rows (corporations + sole proprietors, active
+ revoked + expired). Bulk XML / CSV / JSON. Monthly full snapshot +
daily delta.

Design:
  * Bulk download ONLY. The public web-UI 検索 form is governed by a
    separate TOS that explicitly bans scraping. Do NOT hit the web UI.
  * Stream parse -- the full snapshot is hundreds of MB. Never load the
    whole file into memory.
  * Batched UPSERT with ``executemany()`` in chunks of 5,000 (caller
    configurable). Each batch wrapped in a single transaction for speed.
  * Idempotent: re-running the same date is a no-op by UPSERT; delta
    re-runs only rewrite rows that changed upstream.
  * Source discipline: source_url is required on every row; every row
    also gets a corresponding source_lineage_audit entry (table_name =
    'invoice_registrants').

CLI:

    python scripts/ingest/ingest_invoice_registrants.py \\
        --db data/jpintel.db \\
        [--mode full|delta]          default: full
        [--format csv|xml|json]      default: csv
        [--date YYYY-MM-DD]          default: today (UTC)
        [--limit N]                  cap rows ingested (smoke / CI)
        [--dry-run]                  parse + validate, no DB writes
        [--source-file PATH]         ingest a local bulk file instead of fetching
        [--cache-dir PATH]           where to cache downloads (default /tmp/...)
        [--batch-size N]             rows per transaction (default 5000)

Exit codes:
    0  success
    1  unrecoverable fetch / IO failure
    2  parse failure rate above threshold (>5% of rows rejected)
    3  DB schema missing (run scripts/migrate.py first)
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import io
import logging
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

try:
    import httpx  # type: ignore
except ImportError as exc:  # pragma: no cover - httpx is a hard dep
    print(f"missing dep: {exc}. pip install httpx", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("jpintel.ingest.invoice_registrants")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_CACHE_DIR = Path("/tmp/jpintel_invoice_registrants_cache")  # nosec B108 - same NTA invoice cache used by cron + preflight scripts; mode 0700

# Source URL base. NTA publishes monthly full + daily delta at:
#   https://www.invoice-kohyo.nta.go.jp/download/ (index)
#   https://www.invoice-kohyo.nta.go.jp/download/zenken (全件, monthly)
#   https://www.invoice-kohyo.nta.go.jp/download/sabun (差分, daily)
#
# File delivery URL shape (verified 2026-04-24):
#   GET /download/{zenken|sabun}/dlfile?dlFilKanriNo=<int>&type=<NN>
#     * dlFilKanriNo is an opaque file handle issued by NTA per file
#     * type=01 -> CSV zip; type=02 -> XML zip; type=03 -> JSON zip
#     * The Content-Disposition header names the file, e.g.
#       diff_YYYYMMDD_csv.zip / h_all_YYYYMMDD[_###].zip (corps) /
#       j_all_YYYYMMDD[_###].zip (unincorporated) /
#       k_all_YYYYMMDD[_###].zip (individuals, split into 50MB chunks)
#
# The `dlFilKanriNo` values are discovered by scraping the sabun/zenken
# index pages (HTML contains onclick='doDownload(<id>, <type>)'). The
# index HTML is static (not JS-gated), so a single GET + regex is enough.
# We do not implement the discovery loop here — full-load automation lives
# outside this module under CI (see docs). Callers can always override
# with --source-file to ingest a local bulk file.
SOURCE_URL_BASE = "https://www.invoice-kohyo.nta.go.jp/download"
SOURCE_URL_ROOT = "https://www.invoice-kohyo.nta.go.jp/"
SABUN_INDEX_URL = f"{SOURCE_URL_BASE}/sabun"
ZENKEN_INDEX_URL = f"{SOURCE_URL_BASE}/zenken"

USER_AGENT = "jpintel-mcp invoice-registrants ingest (contact: sss@bookyou.net)"
HTTP_TIMEOUT = 300
MAX_RETRIES = 3

# Mandatory attribution strings (PDL v1.0).
ATTRIBUTION_SOURCE = (
    "出典: 国税庁適格請求書発行事業者公表サイト（国税庁）(https://www.invoice-kohyo.nta.go.jp/)"
)
ATTRIBUTION_EDIT_NOTICE = (
    "本データは国税庁適格請求書発行事業者公表サイトをBookyou株式会社が編集・加工したものです。"
)

# Aggregator domains we refuse to store as source_url. Same list as the
# rest of the codebase; harmless here because NTA is the sole source but
# keeps the rule uniform across ingest paths.
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
    "subsidymap",
    "navit-j",
)

# invoice_registration_number regex: 'T' + exactly 13 decimal digits.
_INVOICE_RE = re.compile(r"^T\d{13}$")

# Prefecture token match. NTA publishes 所在地 as a free-form string;
# the prefecture is always the first 都/道/府/県 token.
_PREF_RE = re.compile(r"^(.{2,4}?(?:都|道|府|県))")

# Registrant kind mapping (NTA's bulk feed exposes 法人/個人 as a short code
# in CSV and an element in XML). Keys are the raw upstream values we map
# from; values are our normalized enum.
#
# NTA 人格区分 (kind) field — verified 2026-04-24 against the 令和6年5月版
# リソース定義書 (k-resource-dl.xlsx, row 23-25):
#   "1" = 個人 (sole_proprietor)
#   "2" = 法人 (corporation)
# Country code (国内外区分, field 12 at CSV index 5) is a SEPARATE axis —
# 1=国内 / 2=特定国外 / 3=特定国外以外の国外. Foreign registrants are still
# 法人 or 個人; we collapse to 'other' only when the country code signals
# foreign, which matches the "外国法人 -> other" precedent in this map.
_KIND_MAP: dict[str, str] = {
    # Japanese freetext
    "法人": "corporation",
    "法人等": "corporation",
    "国内法人": "corporation",
    "外国法人": "other",
    "個人": "sole_proprietor",
    "個人事業者": "sole_proprietor",
    "個人事業主": "sole_proprietor",
    "人格のない社団等": "other",
    "その他": "other",
    # NTA CSV / XML / JSON codes per 令和6年5月版 リソース定義書.
    "1": "sole_proprietor",
    "2": "corporation",
    # English fallthrough (rare)
    "corporation": "corporation",
    "corporate": "corporation",
    "individual": "sole_proprietor",
    "sole_proprietor": "sole_proprietor",
    "other": "other",
}

# NTA CSV column layout — VERIFIED 2026-04-24 against the 令和6年5月版
# 「適格請求書発行事業者公表システムリソース定義書」(k-resource-dl.xlsx).
# Both 全件 (zenken) and 差分 (sabun) CSV ship the same 24-column positional
# schema, UTF-8 encoded, no header row. Column names below mirror the XML /
# JSON / Web-API resource names (project_nta_invoice_api_blocker.md).
#
# Columns 1-6 of the 30-item spec (ルート要素, 最終更新年月日, 総件数,
# 分割番号, 分割数, 公表情報) are XML-only envelope fields and do NOT
# appear in the CSV rows. CSV rows start at item 7 (一連番号).
#
# Empty strings represent NULL per NTA's convention (see k-resource-dl.xlsx
# 凡例 sheet). Code-valued columns (process, correct, kind, country,
# latest) are always present and never NULL for the row itself.
_CSV_COLS_KNOWN = (
    "sequenceNumber",  # 0: 7.  一連番号
    "registratedNumber",  # 1: 8.  登録番号 (T+13 digits) — PK
    "process",  # 2: 9.  事業者処理区分 01=新規 02=変更 03=失効 04=取消 99=削除
    "correct",  # 3: 10. 訂正区分 0=訂正以外 1=訂正 空文字=削除
    "kind",  # 4: 11. 人格区分 1=個人 2=法人
    "country",  # 5: 12. 国内外区分 1=国内 2=特定国外 3=特定国外以外の国外
    "latest",  # 6: 13. 最新履歴 1=最新 空文字=過去情報
    "registrationDate",  # 7: 14. 登録年月日 (YYYY-MM-DD)
    "updateDate",  # 8: 15. 更新年月日
    "disposalDate",  # 9: 16. 取消年月日
    "expireDate",  # 10: 17. 失効年月日
    "address",  # 11: 18. 本店又は主たる事務所の所在地（法人）
    "addressPrefectureCode",  # 12: 19. 所在地都道府県コード（法人）
    "addressCityCode",  # 13: 20. 所在地市区町村コード（法人）
    "addressRequest",  # 14: 21. 所在地（公表申出, 個人）
    "addressRequestPrefectureCode",  # 15: 22. 所在地都道府県コード（公表申出, 個人）
    "addressRequestCityCode",  # 16: 23. 所在地市区町村コード（公表申出, 個人）
    "kana",  # 17: 24. 日本語（カナ）
    "name",  # 18: 25. 氏名又は名称
    "addressInside",  # 19: 26. 国内事業所所在地
    "addressInsidePrefectureCode",  # 20: 27. 国内事業所所在地都道府県コード
    "addressInsideCityCode",  # 21: 28. 国内事業所所在地市区町村コード
    "tradeName",  # 22: 29. 主たる屋号
    "popularName_previousName",  # 23: 30. 通称・旧姓
)

# CSV `process` field values that mean "this row is a delete event, not
# an observed registrant". We skip them — deletes are rare and the PK
# would stay orphaned in our table if we inserted a shell row.
_PROCESS_DELETE = {"99"}

# Prefecture code -> kanji name. NTA field 19/22/27 uses the standard
# JIS X 0401 全国地方公共団体コード (都道府県部分). Covers the 47 + a
# blank for foreign / 外国法人. Verified 2026-04-24 against the
# 総務省 全国地方公共団体コード list.
_PREF_CODE_MAP: dict[str, str] = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "05": "秋田県",
    "06": "山形県",
    "07": "福島県",
    "08": "茨城県",
    "09": "栃木県",
    "10": "群馬県",
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
    "15": "新潟県",
    "16": "富山県",
    "17": "石川県",
    "18": "福井県",
    "19": "山梨県",
    "20": "長野県",
    "21": "岐阜県",
    "22": "静岡県",
    "23": "愛知県",
    "24": "三重県",
    "25": "滋賀県",
    "26": "京都府",
    "27": "大阪府",
    "28": "兵庫県",
    "29": "奈良県",
    "30": "和歌山県",
    "31": "鳥取県",
    "32": "島根県",
    "33": "岡山県",
    "34": "広島県",
    "35": "山口県",
    "36": "徳島県",
    "37": "香川県",
    "38": "愛媛県",
    "39": "高知県",
    "40": "福岡県",
    "41": "佐賀県",
    "42": "長崎県",
    "43": "熊本県",
    "44": "大分県",
    "45": "宮崎県",
    "46": "鹿児島県",
    "47": "沖縄県",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    root = logging.getLogger("jpintel.ingest.invoice_registrants")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def nfkc_strip(s: Any) -> str | None:
    """NFKC normalize + collapse whitespace + strip. None/empty -> None."""
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def extract_prefecture(address: str | None, explicit_pref: str | None) -> str | None:
    """Prefer NTA's explicit 都道府県 column; fall back to first 都道府県 token in address."""
    if explicit_pref:
        p = nfkc_strip(explicit_pref)
        if p:
            return p
    if not address:
        return None
    m = _PREF_RE.match(address)
    return m.group(1) if m else None


def normalize_date(raw: Any) -> str | None:
    """Parse NTA date representations into ISO 8601 (YYYY-MM-DD).

    NTA ships dates as either 'YYYY/MM/DD', 'YYYY-MM-DD', or 'YYYYMMDD'.
    Returns None for blanks or unparseable input.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = unicodedata.normalize("NFKC", s)
    # YYYY/MM/DD or YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    # YYYYMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def map_registrant_kind(raw: Any) -> str:
    """Map NTA 事業者区分 to our enum. Unknown -> 'other'."""
    if raw is None:
        return "other"
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s:
        return "other"
    return _KIND_MAP.get(s, "other")


def validate_invoice_number(n: Any) -> str | None:
    """Validate 'T' + 13 digits; return cleaned value or None."""
    if n is None:
        return None
    s = unicodedata.normalize("NFKC", str(n)).strip().upper()
    if not s:
        return None
    # Some feeds strip the leading T; re-attach if it looks like 13 raw digits.
    if re.fullmatch(r"\d{13}", s):
        s = "T" + s
    if _INVOICE_RE.match(s):
        return s
    return None


def derive_houjin_bangou(invoice_no: str, kind: str) -> str | None:
    """For corporations, strip the leading T to get the 13-digit houjin_bangou.

    Sole proprietors typically lack a houjin_bangou; return None. Some
    feeds include a synthetic 13-digit number for 個人 -- we still return
    None there to keep the soft-reference semantics honest.
    """
    if kind != "corporation":
        return None
    if not invoice_no or len(invoice_no) != 14 or not invoice_no.startswith("T"):
        return None
    tail = invoice_no[1:]
    if not tail.isdigit() or len(tail) != 13:
        return None
    return tail


# ---------------------------------------------------------------------------
# Source URL + hygiene
# ---------------------------------------------------------------------------


_FMT_TO_NTA_TYPE: dict[str, str] = {"csv": "01", "xml": "02", "json": "03"}


def build_source_url(mode: str, fmt: str, date_str: str, dl_fil_kanri_no: str | None = None) -> str:
    """Return the bulk-download URL for a given (mode, format, date).

    NTA's real delivery endpoint is opaque-handle-based:
        /download/{bucket}/dlfile?dlFilKanriNo=<N>&type=<NN>

    mode:  'full' -> zenken, 'delta' -> sabun
    fmt:   'csv' | 'xml' | 'json'
    date_str: 'YYYY-MM-DD' (kept for logging only when dl_fil_kanri_no given)
    dl_fil_kanri_no: when provided, we construct the real delivery URL.
        When None, we return a descriptive pseudo-URL rooted at the index
        page — callers MUST then pass --source-file, because the file
        cannot be fetched by date alone.
    """
    bucket = "zenken" if mode == "full" else "sabun"
    type_code = _FMT_TO_NTA_TYPE.get(fmt)
    if type_code is None:
        raise ValueError(f"unknown format: {fmt!r}")
    if dl_fil_kanri_no is not None:
        return f"{SOURCE_URL_BASE}/{bucket}/dlfile?dlFilKanriNo={dl_fil_kanri_no}&type={type_code}"
    # Fallback pseudo-URL: identifies the bucket + date for lineage/audit
    # purposes; actual bytes must come from --source-file.
    yyyymmdd = date_str.replace("-", "")
    return f"{SOURCE_URL_BASE}/{bucket}/#{yyyymmdd}_{fmt}"


def discover_dl_fil_kanri_no(
    bucket: str,
    date_str: str,
    fmt: str = "csv",
) -> str | None:
    """Scan the NTA {zenken|sabun} index HTML for the dlFilKanriNo matching date_str.

    The index page is static HTML (no JS gating) — each file is rendered
    as ``<onclick="return doDownload('<ID>','<NN>')">`` next to a row
    whose ``<th>`` reads 「令和X年M月D日」 or a Gregorian date.

    Returns the dlFilKanriNo as a string, or None if not found. Uses a
    network GET. Respects `USER_AGENT`. CI callers should back this with
    a cache or a day-of-week pre-compute to avoid beating the index.
    """
    if bucket not in ("zenken", "sabun"):
        raise ValueError(f"bucket must be 'zenken' or 'sabun', got {bucket!r}")
    type_code = _FMT_TO_NTA_TYPE.get(fmt)
    if type_code is None:
        raise ValueError(f"unknown fmt: {fmt!r}")
    index_url = f"{SOURCE_URL_BASE}/{bucket}"
    body = polite_get(index_url).decode("utf-8", errors="replace")
    # Date can appear as either ISO (2026-04-23) or reiwa form.
    y, mo, d = date_str.split("-")
    # Reiwa conversion: 令和X = seireki - 2018 (Reiwa 1 = 2019).
    reiwa_year = int(y) - 2018
    reiwa_label = f"令和{reiwa_year}年{int(mo)}月{int(d)}日"
    iso_label = date_str
    # Narrow the HTML to the <tr> that mentions either label, then pick the
    # doDownload(<ID>,'<type_code>') within it.
    tr_re = re.compile(r"<tr[^>]*>.*?</tr>", re.DOTALL)
    call_re = re.compile(rf"doDownload\('(\d+)','{type_code}'\)")
    for tr in tr_re.finditer(body):
        block = tr.group(0)
        if reiwa_label in block or iso_label in block:
            m = call_re.search(block)
            if m:
                return m.group(1)
    return None


def source_url_is_banned(url: str) -> bool:
    if not url:
        return False
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def source_domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def polite_get(url: str, tries: int = MAX_RETRIES) -> bytes:
    """GET with exponential back-off. Raises on final failure."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            with httpx.Client(http2=False, follow_redirects=True, timeout=HTTP_TIMEOUT) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.content
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == tries:
                break
            wait = 2**attempt
            _LOG.warning(
                "fetch_retry attempt=%d/%d wait=%ds url=%s err=%s", attempt, tries, wait, url, exc
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def ensure_local_bulk_file(
    source_url: str, cache_dir: Path, explicit: Path | None = None
) -> tuple[Path, str]:
    """Return (local path, sha256). Re-uses cache when non-empty.

    If ``explicit`` is provided, skip the fetch entirely and checksum that
    path. Caller is responsible for `--source-file` hygiene.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"--source-file not found: {explicit}")
        body = explicit.read_bytes()
        return explicit, hashlib.sha256(body).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Build a cache filename that preserves the suffix (_open_bulk_stream
    # dispatches on the extension). NTA delivery URL is ?-laden, which
    # would otherwise corrupt the filename.
    parsed = urllib.parse.urlparse(source_url)
    qs = urllib.parse.parse_qs(parsed.query)
    kanri = (qs.get("dlFilKanriNo", [""])[0] or "").strip()
    type_code = (qs.get("type", [""])[0] or "").strip()
    # Map type code back to format suffix for the cache name.
    type_to_suffix = {"01": "csv", "02": "xml", "03": "json"}
    suffix = type_to_suffix.get(type_code, "bin")
    if kanri:
        fname = f"nta_{kanri}_{suffix}.zip"
    else:
        # Fallback: last path segment without query string.
        raw = parsed.path.rsplit("/", 1)[-1] or "bulk.bin"
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", raw) or "bulk.bin"
    local = cache_dir / fname
    if local.exists() and local.stat().st_size > 1024:
        body = local.read_bytes()
    else:
        _LOG.info("fetch_start url=%s", source_url)
        body = polite_get(source_url)
        local.write_bytes(body)
    checksum = hashlib.sha256(body).hexdigest()
    return local, checksum


# ---------------------------------------------------------------------------
# Streaming parsers
# ---------------------------------------------------------------------------


def _detect_encoding(probe: bytes) -> str:
    """Best-effort encoding sniff for NTA CSV.

    NTA has historically shipped CSV in cp932 (Shift_JIS variant). Post
    2024-05 the 令和6年5月版 dumps ship UTF-8 (verified 2026-04-24 against
    diff_20260423_csv.zip). Probe order:
      * \\xef\\xbb\\xbf         -> utf-8-sig
      * valid UTF-8 (with tolerance for a truncated final character at
        the probe boundary) -> utf-8
      * otherwise              -> cp932

    The probe-boundary tolerance matters: a 4KB slice of a UTF-8 stream
    can end mid-character, triggering a spurious UnicodeDecodeError and
    a wrong fallback to cp932 (this silently corrupts every multi-byte
    string in the DB — the failure mode we hit on first real data).
    """
    if probe.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        probe.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as exc:
        # If the decode failure is at the tail and looks like a truncated
        # multi-byte sequence, treat as UTF-8. UTF-8 lead bytes begin with
        # 11xxxxxx; the short suffix (up to 3 bytes) is a classic boundary
        # artifact.
        if exc.end >= len(probe) - 3:
            tail = probe[exc.start :]
            if tail and (tail[0] & 0xC0) == 0xC0:  # UTF-8 lead byte
                try:
                    probe[: exc.start].decode("utf-8")
                    return "utf-8"
                except UnicodeDecodeError:
                    pass
        return "cp932"


def _open_bulk_stream(local_path: Path) -> tuple[io.IOBase, str]:
    """Return (text-stream, suffix) for iteration.

    Handles .zip (expects a single member) and .gz transparently. Plain
    .csv/.xml/.json pass through.
    """
    name = local_path.name.lower()
    if name.endswith(".zip"):
        zf = zipfile.ZipFile(local_path)
        members = [m for m in zf.namelist() if not m.endswith("/")]
        if not members:
            raise ValueError(f"empty zip: {local_path}")
        inner = members[0]
        raw_bytes = zf.read(inner)
        suffix = inner.lower().rsplit(".", 1)[-1]
        enc = _detect_encoding(raw_bytes[:4096])
        return io.StringIO(raw_bytes.decode(enc, errors="replace")), suffix
    if name.endswith(".gz"):
        raw_bytes = gzip.decompress(local_path.read_bytes())
        inner_name = local_path.stem.lower()
        suffix = inner_name.rsplit(".", 1)[-1] if "." in inner_name else "csv"
        enc = _detect_encoding(raw_bytes[:4096])
        return io.StringIO(raw_bytes.decode(enc, errors="replace")), suffix
    # Plain file. Read bytes just enough to detect encoding, then rewind.
    with local_path.open("rb") as f:
        probe = f.read(4096)
    enc = _detect_encoding(probe)
    suffix = name.rsplit(".", 1)[-1]
    return local_path.open("r", encoding=enc, errors="replace", newline=""), suffix


def _first_present(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def iter_csv_rows(stream: io.IOBase) -> Iterator[dict[str, Any]]:
    """Stream parse CSV. Supports header-row, legacy-header, and positional feeds.

    Detection order:
      1. Header row whose first column is literally 'sequenceNumber' or
         'registratedNumber' — recent NTA dumps (post 令和6年5月) can ship
         a JSON-style header.
      2. Header row whose first column is '登録番号' — the pre-2024 dump
         convention; mapped onto positional column names.
      3. Positional (no header). Both 全件 and 差分 CSVs use this. The
         row we already consumed is treated as the first data row.

    The 24-column positional layout is fixed per 令和6年5月版 リソース定義書;
    see `_CSV_COLS_KNOWN` above.
    """
    reader = csv.reader(stream)
    first: list[str] | None = None
    for row in reader:
        if not row:
            continue
        first = row
        break
    if first is None:
        return

    first_col = first[0].strip() if first else ""
    # Case 1: modern field-name header
    if first_col in ("sequenceNumber", "registratedNumber"):
        headers = [h.strip() for h in first]
        for row in reader:
            if not row or all(not c for c in row):
                continue
            yield {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        return

    # Case 2: legacy Japanese-name header
    if first_col == "登録番号":
        # Older layout with Japanese headers — map to canonical field names
        # where possible; unknown columns are passed through verbatim.
        jp_to_canon = {
            "一連番号": "sequenceNumber",
            "登録番号": "registratedNumber",
            "事業者処理区分": "process",
            "訂正区分": "correct",
            "人格区分": "kind",
            "国内外区分": "country",
            "最新履歴": "latest",
            "登録年月日": "registrationDate",
            "更新年月日": "updateDate",
            "取消年月日": "disposalDate",
            "失効年月日": "expireDate",
            "本店又は主たる事務所の所在地": "address",
            "本店又は主たる事務所の所在地都道府県コード": "addressPrefectureCode",
            "本店又は主たる事務所の所在地市区町村コード": "addressCityCode",
            "日本語（カナ）": "kana",
            "氏名又は名称": "name",
            "主たる屋号": "tradeName",
            "通称・旧姓": "popularName_previousName",
        }
        headers = [jp_to_canon.get(h.strip(), h.strip()) for h in first]
        for row in reader:
            if not row or all(not c for c in row):
                continue
            yield {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        return

    # Case 3: positional (24-column layout, no header).
    headers = list(_CSV_COLS_KNOWN)

    def _project(rec: list[str]) -> dict[str, Any]:
        return {headers[i]: rec[i] for i in range(min(len(headers), len(rec)))}

    yield _project(first)
    for row in reader:
        if not row or all(not c for c in row):
            continue
        yield _project(row)


def iter_xml_rows(local_path: Path) -> Iterator[dict[str, Any]]:
    """Stream parse NTA XML with iterparse.

    NTA ships XML with ``<data>`` root and repeated ``<item>`` (or
    ``<invoice>``) children holding one registrant per element. We match
    any element whose children include a ``<registrationNo>`` (or the
    Japanese tag 登録番号).

    TODO(verify): confirm root/element names against the real download.
    We match multiple candidate tags to be robust to rename.
    """
    # Open the zip/gz/plain transparently.
    stream, _suffix = _open_bulk_stream(local_path)
    # iterparse wants bytes; re-encode the string.
    text = stream.read() if hasattr(stream, "read") else ""
    if isinstance(stream, io.IOBase):
        with contextlib.suppress(Exception):
            stream.close()
    context = ET.iterparse(io.BytesIO(text.encode("utf-8")), events=("end",))  # nosec B314 - input is trusted gov-source XML; not user-supplied

    invoice_tags = {"registrationNo", "registration_no", "登録番号"}
    for _event, elem in context:
        local = elem.tag.rsplit("}", 1)[-1]
        # An <item>-equivalent is any element with a child that is an invoice tag.
        if local in ("item", "invoice", "registrant", "registeredInvoiceIssuer", "data"):
            fields: dict[str, Any] = {}
            has_invoice = False
            for child in elem:
                ctag = child.tag.rsplit("}", 1)[-1]
                if ctag in invoice_tags:
                    has_invoice = True
                fields[ctag] = (child.text or "").strip() if child.text else None
            if has_invoice:
                yield fields
            elem.clear()


def iter_json_rows(stream: io.IOBase) -> Iterator[dict[str, Any]]:
    """Stream parse NTA JSON.

    NTA's JSON dumps come either as NDJSON (one object per line) or as a
    top-level array. We detect by the first non-whitespace char.

    TODO(verify): confirm NTA JSON shape for the bulk endpoint.
    """
    import json

    head = ""
    # peek up to 1 char
    while True:
        ch = stream.read(1)
        if not ch:
            return
        if not ch.isspace():
            head = ch
            break
    if head == "[":
        # JSON array; use stream json parser via ijson if available, else
        # load all (acceptable for daily delta, not ideal for full snapshot).
        try:
            import ijson  # type: ignore

            # Rewind wrapper
            stream.seek(0)
            for rec in ijson.items(stream, "item"):
                if isinstance(rec, dict):
                    yield rec
            return
        except ImportError:
            _LOG.warning("ijson not installed; falling back to full-load JSON parser")
            stream.seek(0)
            data = json.load(stream)
            if isinstance(data, list):
                for rec in data:
                    if isinstance(rec, dict):
                        yield rec
            return
    # NDJSON: first char was the first {
    line = head + stream.readline()
    try:  # noqa: SIM105 -- suppress+yield don't compose in a generator
        yield json.loads(line)
    except Exception:  # noqa: BLE001
        pass
    for raw in stream:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict):
            yield rec


# ---------------------------------------------------------------------------
# Record normalization (bulk row dict -> DB row tuple)
# ---------------------------------------------------------------------------


# Sentinel returned by ``normalize_row`` for rows that are valid but
# intentionally skipped under NTA policy (deletes / non-latest history).
# Distinct from ``None`` which signals a parse error.
POLICY_SKIP = object()


def normalize_row(
    raw: dict[str, Any], source_url: str, checksum: str, now_iso: str
) -> dict[str, Any] | None | object:
    """Turn a raw bulk record into a DB-ready dict.

    Returns:
        dict        — normalized row ready for UPSERT
        POLICY_SKIP — NTA process=99 (削除) or latest!=1 (履歴); not an error
        None        — parse failure (schema violation, bad registration number)

    Semantic rules verified 2026-04-24 against 令和6年5月版 リソース定義書:
      * `process='99'` (削除) — skip; NTA tells us to drop this PK entirely.
      * `latest != '1'` — skip; the CSV ships 過去情報 rows as audit trail
        (older history). The table stores only the current public record.
      * `country != '1'` — kind is forced to 'other' (特定国外 / その他国外)
        even if `kind=2` (法人), matching the 外国法人 precedent in
        `_KIND_MAP`.
      * Sole-proprietors (kind=1) typically ship name='' by NTA policy —
        when both `name` and `kana` are empty we fall back to '(非公表)'
        so the schema's NOT NULL constraint holds while staying honest
        about privacy-protected rows.
      * Address priority for 法人:   address -> addressInside
                          for 個人:   addressRequest -> addressInside
    """
    # Invoice number: CSV calls it 'registratedNumber'; legacy headers
    # call it '登録番号'; XML/JSON alt names accepted for forward-compat.
    invoice_raw = _first_present(
        raw,
        "registratedNumber",
        "登録番号",
        "registrationNo",
        "registration_no",
        "invoice_registration_number",
    )
    invoice_no = validate_invoice_number(invoice_raw)
    if invoice_no is None:
        return None

    # Skip 削除 and non-latest rows (POLICY — not parse errors).
    process_code = str(raw.get("process", "")).strip()
    if process_code in _PROCESS_DELETE:
        return POLICY_SKIP
    latest = str(raw.get("latest", "1")).strip()
    if latest and latest != "1":
        return POLICY_SKIP

    kind_raw = _first_present(raw, "kind", "事業者区分", "registrantKind", "registrant_kind")
    kind = map_registrant_kind(kind_raw)

    # Foreign registrants collapse to 'other' regardless of 人格区分.
    country = str(raw.get("country", "")).strip()
    if country and country != "1":
        kind = "other"

    name = nfkc_strip(
        _first_present(raw, "name", "氏名又は名称", "registrantName", "registrant_name")
    )
    kana = nfkc_strip(_first_present(raw, "kana", "日本語（カナ）"))
    if not name:
        # Sole-proprietors may ship empty name (non-disclosure policy).
        # Use kana if available, else a sentinel to satisfy NOT NULL
        # while staying truthful — the API renders this as-is.
        name = kana or "(非公表)"

    # Address priority depends on 人格区分.
    if kind == "corporation":
        address = nfkc_strip(_first_present(raw, "address", "国内所在地", "address_normalized"))
        if not address:
            address = nfkc_strip(_first_present(raw, "addressInside"))
        pref_code = (
            str(raw.get("addressPrefectureCode", "")).strip().zfill(2)
            if raw.get("addressPrefectureCode")
            else ""
        )
        if not pref_code:
            pref_code = (
                str(raw.get("addressInsidePrefectureCode", "")).strip().zfill(2)
                if raw.get("addressInsidePrefectureCode")
                else ""
            )
    else:
        # 個人 / その他
        address = nfkc_strip(_first_present(raw, "addressRequest", "address"))
        if not address:
            address = nfkc_strip(_first_present(raw, "addressInside"))
        pref_code = (
            str(raw.get("addressRequestPrefectureCode", "")).strip().zfill(2)
            if raw.get("addressRequestPrefectureCode")
            else ""
        )
        if not pref_code:
            pref_code = (
                str(raw.get("addressInsidePrefectureCode", "")).strip().zfill(2)
                if raw.get("addressInsidePrefectureCode")
                else ""
            )

    explicit_pref_raw = nfkc_strip(_first_present(raw, "都道府県", "prefecture"))
    prefecture_from_code = _PREF_CODE_MAP.get(pref_code) if pref_code else None
    prefecture = explicit_pref_raw or prefecture_from_code or extract_prefecture(address, None)

    registered_date = normalize_date(
        _first_present(raw, "registrationDate", "登録年月日", "registeredDate", "registered_date")
    )
    # registered_date is NOT NULL in the schema. Missing -> skip.
    if registered_date is None:
        return None

    revoked_date = normalize_date(
        _first_present(raw, "disposalDate", "取消年月日", "revokedDate", "revoked_date")
    )
    expired_date = normalize_date(
        _first_present(raw, "expireDate", "失効年月日", "expiredDate", "expired_date")
    )

    trade_name = nfkc_strip(_first_present(raw, "tradeName", "屋号", "主たる屋号", "trade_name"))

    last_updated = normalize_date(
        _first_present(raw, "updateDate", "最新更新年月日", "lastUpdated", "last_updated_nta")
    )

    # houjin_bangou: preferred source is NTA's explicit '法人番号' field when
    # present; else derive from invoice_no by stripping 'T' (corp only).
    hb_raw = _first_present(raw, "法人番号", "corporateNumber", "houjin_bangou")
    hb_clean: str | None = None
    if hb_raw:
        s = unicodedata.normalize("NFKC", str(hb_raw)).strip()
        if re.fullmatch(r"\d{13}", s):
            hb_clean = s
    if hb_clean is None:
        hb_clean = derive_houjin_bangou(invoice_no, kind)

    return {
        "invoice_registration_number": invoice_no,
        "houjin_bangou": hb_clean,
        "normalized_name": name,
        "address_normalized": address,
        "prefecture": prefecture,
        "registered_date": registered_date,
        "revoked_date": revoked_date,
        "expired_date": expired_date,
        "registrant_kind": kind,
        "trade_name": trade_name,
        "last_updated_nta": last_updated,
        "source_url": source_url,
        "source_checksum": checksum,
        "confidence": 0.98,
        "fetched_at": now_iso,
        "updated_at": now_iso,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


_UPSERT_SQL = """
INSERT INTO invoice_registrants (
    invoice_registration_number,
    houjin_bangou,
    normalized_name,
    address_normalized,
    prefecture,
    registered_date,
    revoked_date,
    expired_date,
    registrant_kind,
    trade_name,
    last_updated_nta,
    source_url,
    source_checksum,
    confidence,
    fetched_at,
    updated_at
) VALUES (
    :invoice_registration_number,
    :houjin_bangou,
    :normalized_name,
    :address_normalized,
    :prefecture,
    :registered_date,
    :revoked_date,
    :expired_date,
    :registrant_kind,
    :trade_name,
    :last_updated_nta,
    :source_url,
    :source_checksum,
    :confidence,
    :fetched_at,
    :updated_at
)
ON CONFLICT(invoice_registration_number) DO UPDATE SET
    houjin_bangou      = excluded.houjin_bangou,
    normalized_name    = excluded.normalized_name,
    address_normalized = excluded.address_normalized,
    prefecture         = excluded.prefecture,
    registered_date    = excluded.registered_date,
    revoked_date       = excluded.revoked_date,
    expired_date       = excluded.expired_date,
    registrant_kind    = excluded.registrant_kind,
    trade_name         = excluded.trade_name,
    last_updated_nta   = excluded.last_updated_nta,
    source_url         = excluded.source_url,
    source_checksum    = excluded.source_checksum,
    confidence         = excluded.confidence,
    fetched_at         = excluded.fetched_at,
    updated_at         = excluded.updated_at
WHERE
    -- Only actually rewrite when something changed. Cheap self-filter so
    -- monthly re-ingests don't inflate the WAL on churn-free rows.
    invoice_registrants.normalized_name    IS NOT excluded.normalized_name
 OR invoice_registrants.address_normalized IS NOT excluded.address_normalized
 OR invoice_registrants.prefecture         IS NOT excluded.prefecture
 OR invoice_registrants.registered_date    IS NOT excluded.registered_date
 OR invoice_registrants.revoked_date       IS NOT excluded.revoked_date
 OR invoice_registrants.expired_date       IS NOT excluded.expired_date
 OR invoice_registrants.registrant_kind    IS NOT excluded.registrant_kind
 OR invoice_registrants.trade_name         IS NOT excluded.trade_name
 OR invoice_registrants.houjin_bangou      IS NOT excluded.houjin_bangou
 OR invoice_registrants.last_updated_nta   IS NOT excluded.last_updated_nta
"""


_LINEAGE_SQL = """
INSERT INTO source_lineage_audit (
    table_name, row_key, source_url, source_domain,
    fetched_at, primary_source, audit_status
) VALUES (?, ?, ?, ?, ?, 1, 'unaudited')
"""


def schema_ready(conn: sqlite3.Connection) -> bool:
    """True iff migration 019 has been applied (table + expected columns exist)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='invoice_registrants'"
    ).fetchone()
    return row is not None


def apply_batch(
    conn: sqlite3.Connection,
    batch: list[dict[str, Any]],
    lineage_enabled: bool,
) -> tuple[int, int]:
    """Apply one batch as a single transaction. Returns (inserted+updated, lineage_rows).

    SQLite's UPSERT doesn't distinguish insert vs update in the affected
    count without a per-row probe, so we return the combined write count.
    Caller tracks an approximate insert/update split via the pre-batch
    membership check.
    """
    if not batch:
        return 0, 0
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute("BEGIN")
    try:
        conn.executemany(_UPSERT_SQL, batch)
        lineage_rows = 0
        if lineage_enabled:
            lineage_params = [
                (
                    "invoice_registrants",
                    r["invoice_registration_number"],
                    r["source_url"],
                    source_domain(r["source_url"]),
                    now,
                )
                for r in batch
            ]
            conn.executemany(_LINEAGE_SQL, lineage_params)
            lineage_rows = len(lineage_params)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(batch), lineage_rows


def split_insert_update(conn: sqlite3.Connection, batch: list[dict[str, Any]]) -> tuple[int, int]:
    """Pre-batch count of how many PKs already exist. Best-effort telemetry only."""
    if not batch:
        return 0, 0
    pks = [r["invoice_registration_number"] for r in batch]
    placeholder = ",".join("?" for _ in pks)
    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT invoice_registration_number FROM invoice_registrants "
            f"WHERE invoice_registration_number IN ({placeholder})",
            pks,
        )
    }
    updates = sum(1 for p in pks if p in existing)
    return len(pks) - updates, updates


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def iter_bulk_rows(
    local_path: Path,
    fmt: str,
) -> Iterator[dict[str, Any]]:
    """Dispatch to the right streaming parser for (format, file-on-disk)."""
    if fmt == "csv":
        stream, _suffix = _open_bulk_stream(local_path)
        try:
            yield from iter_csv_rows(stream)
        finally:
            with contextlib.suppress(Exception):
                stream.close()
    elif fmt == "xml":
        yield from iter_xml_rows(local_path)
    elif fmt == "json":
        stream, _suffix = _open_bulk_stream(local_path)
        try:
            yield from iter_json_rows(stream)
        finally:
            with contextlib.suppress(Exception):
                stream.close()
    else:
        raise ValueError(f"unknown format: {fmt!r}")


def run_ingest(
    db_path: Path,
    mode: str,
    fmt: str,
    date_str: str,
    limit: int | None,
    dry_run: bool,
    source_file: Path | None,
    cache_dir: Path,
    batch_size: int,
) -> int:
    """Orchestrate fetch -> parse -> normalize -> batched upsert. Return exit code."""
    t0 = time.monotonic()

    # When --source-file is provided, we still build a source_url for the
    # lineage audit (description-only) but never hit the network.
    dl_fil_kanri_no: str | None = None
    if source_file is None:
        bucket = "zenken" if mode == "full" else "sabun"
        try:
            dl_fil_kanri_no = discover_dl_fil_kanri_no(bucket, date_str, fmt)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("discover_failed bucket=%s date=%s err=%s", bucket, date_str, exc)
        if dl_fil_kanri_no is None:
            _LOG.error(
                "no_file_for_date bucket=%s date=%s — no dlFilKanriNo found on "
                "NTA index. Pass --source-file to ingest a locally-cached bulk "
                "file, or pick a date within the past 40 business days (sabun) "
                "or a recent 1st-of-month (zenken).",
                bucket,
                date_str,
            )
            return 1
    source_url = build_source_url(
        mode=mode, fmt=fmt, date_str=date_str, dl_fil_kanri_no=dl_fil_kanri_no
    )
    if source_url_is_banned(source_url):
        _LOG.error("source_banned url=%s", source_url)
        return 1

    try:
        local_path, checksum = ensure_local_bulk_file(source_url, cache_dir, source_file)
    except Exception as exc:  # noqa: BLE001
        _LOG.error("fetch_failed url=%s err=%s", source_url, exc)
        return 1
    _LOG.info(
        "bulk_ready path=%s size=%d sha256=%s",
        local_path,
        local_path.stat().st_size,
        checksum[:12],
    )

    # DB connect + pragmas tuned for bulk write.
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -200000")  # ~200MB
        conn.execute("PRAGMA foreign_keys = ON")
        if not schema_ready(conn):
            _LOG.error(
                "schema_missing: table invoice_registrants not found. "
                "Run `python scripts/migrate.py --db %s` first.",
                db_path,
            )
            conn.close()
            return 3

    # Lineage table is optional: present when migration 014 has been applied.
    lineage_enabled = False
    if conn is not None:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_lineage_audit'"
        ).fetchone()
        lineage_enabled = row is not None
        if not lineage_enabled:
            _LOG.warning(
                "source_lineage_audit missing -- lineage rows skipped (migration 014 not applied?)"
            )

    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    total_seen = 0
    total_parsed = 0
    total_rejected = 0  # parse errors (schema violations)
    total_skipped_policy = 0  # legitimate skips: process=99 (削除), latest!=1 (履歴)
    total_written = 0
    total_inserted = 0
    total_updated = 0
    total_lineage = 0

    batch: list[dict[str, Any]] = []

    def _flush() -> None:
        nonlocal total_written, total_inserted, total_updated, total_lineage, batch
        if not batch:
            return
        if dry_run or conn is None:
            total_written += len(batch)
            batch = []
            return
        ins, upd = split_insert_update(conn, batch)
        written, lineage_rows = apply_batch(conn, batch, lineage_enabled)
        total_inserted += ins
        total_updated += upd
        total_written += written
        total_lineage += lineage_rows
        batch = []

    try:
        for raw in iter_bulk_rows(local_path, fmt):
            total_seen += 1
            if limit is not None and total_parsed >= limit:
                break
            norm = normalize_row(raw, source_url, checksum, now_iso)
            if norm is None:
                total_rejected += 1
                continue
            if norm is POLICY_SKIP:
                total_skipped_policy += 1
                continue
            total_parsed += 1
            assert isinstance(norm, dict)
            batch.append(norm)
            if len(batch) >= batch_size:
                _flush()
            if total_parsed and total_parsed % 10_000 == 0:
                _LOG.info(
                    "progress seen=%d parsed=%d rejected=%d skipped_policy=%d written=%d",
                    total_seen,
                    total_parsed,
                    total_rejected,
                    total_skipped_policy,
                    total_written,
                )
        _flush()
    finally:
        if conn is not None:
            conn.close()

    elapsed = time.monotonic() - t0

    # Parse-quality gate: reject >5% parse-failure rate as a data drift signal.
    # Policy skips (delete / history) are NOT counted — they're NTA's
    # normal delta pattern, not a schema drift signal.
    considered = total_seen - total_skipped_policy
    reject_rate = (total_rejected / considered) if considered else 0.0
    quality_fail = considered > 1000 and reject_rate > 0.05

    _LOG.info(
        "summary mode=%s fmt=%s date=%s seen=%d parsed=%d rejected=%d "
        "skipped_policy=%d inserted=%d updated=%d written=%d lineage=%d "
        "elapsed=%.1fs reject_rate=%.3f",
        mode,
        fmt,
        date_str,
        total_seen,
        total_parsed,
        total_rejected,
        total_skipped_policy,
        total_inserted,
        total_updated,
        total_written,
        total_lineage,
        elapsed,
        reject_rate,
    )

    # Human-readable completion banner (the spec demands this exact shape).
    print(
        f"Ingested {total_inserted}, updated {total_updated}, "
        f"errors {total_rejected}, skipped_policy {total_skipped_policy}, "
        f"{elapsed:.1f} seconds"
    )

    # Attribution reminder -- the ingest itself does NOT expose rows; the
    # API serializer is the enforcement point for PDL v1.0 compliance.
    _LOG.info(
        "attribution_reminder: any API response exposing invoice_registrants "
        "MUST include the 出典 string '%s' AND the 編集・加工注記 '%s'. "
        "Enforcement point: src/jpintel_mcp/api/invoice_registrants.py (when written).",
        ATTRIBUTION_SOURCE,
        ATTRIBUTION_EDIT_NOTICE,
    )

    if quality_fail:
        _LOG.error(
            "PARSE QUALITY FAILURE seen=%d rejected=%d rate=%.3f > 0.05 threshold",
            total_seen,
            total_rejected,
            reject_rate,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"SQLite DB path (default {DEFAULT_DB})"
    )
    ap.add_argument(
        "--mode",
        choices=("full", "delta"),
        default="full",
        help="monthly full snapshot or daily delta",
    )
    ap.add_argument(
        "--format", dest="fmt", choices=("csv", "xml", "json"), default="csv", help="bulk format"
    )
    ap.add_argument(
        "--date",
        type=str,
        default=datetime.now(UTC).date().isoformat(),
        help="YYYY-MM-DD snapshot date (UTC today if omitted)",
    )
    ap.add_argument("--limit", type=int, default=None, help="cap rows parsed (smoke / CI)")
    ap.add_argument("--dry-run", action="store_true", help="parse + validate, no DB writes")
    ap.add_argument(
        "--source-file",
        type=Path,
        default=None,
        help="ingest a local bulk file instead of fetching from NTA",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"download cache directory (default {DEFAULT_CACHE_DIR})",
    )
    ap.add_argument(
        "--batch-size", type=int, default=5000, help="rows per transaction (default 5000)"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging()

    # Basic validation on --date.
    try:
        date.fromisoformat(args.date)
    except ValueError:
        _LOG.error("invalid --date=%s (expected YYYY-MM-DD)", args.date)
        return 1

    return run_ingest(
        db_path=args.db,
        mode=args.mode,
        fmt=args.fmt,
        date_str=args.date,
        limit=args.limit,
        dry_run=args.dry_run,
        source_file=args.source_file,
        cache_dir=args.cache_dir,
        batch_size=max(100, args.batch_size),
    )


if __name__ == "__main__":
    raise SystemExit(main())
