#!/usr/bin/env python3
"""Generate the 税理士事務所 月次「丸投げパック」 PDF for each 顧問先 row.

Reads a small CSV of 顧問先 (per-tax-firm client list) and produces one A4
PDF per row covering:

    1. 当月の制度改正 (am_amendment_diff filtered by record_kind=program)
    2. 顧問先が利用できる可能性のある制度 (programs JSIC × prefecture filter)
    3. 同業同地域の採択事例 (jpi_adoption_records)
    4. 同業の行政処分 (am_enforcement_detail issuing_authority keyword match)
    5. 出典 URL 全件

Operator: Bookyou株式会社 (T8010001213708) / info@bookyou.net
Brand:    jpcite (https://jpcite.com / https://api.jpcite.com)

Pricing model
-------------
The script does **not** call any external billable API. It only reads
local SQLite (jpintel.db + autonomath.db). The "¥3/req" cost model is
expressed via the ``--rate-yen`` arg + ``req_count`` accounted per
顧問先 — the count corresponds to the 50-100 endpoint calls a paying
税理士法人 customer would issue against api.jpcite.com to assemble the
same content. Solo + zero-touch posture (CLAUDE.md non-negotiable):
no LLM, no tier SKU, no DPA, ¥3/req only, organic only.

CSV format (UTF-8, header required)
-----------------------------------
    client_id,client_label,houjin_bangou,jsic_medium,prefecture
    cl_001,顧問先A,1234567890123,E,東京都
    cl_002,顧問先B,2345678901234,D,大阪府

* ``client_id``: tax-firm internal id (ASCII, 1..128 chars). NOT the 法人番号.
* ``client_label``: free-text display label rendered on the cover page.
* ``houjin_bangou``: 13-digit corp number — used only to derive the last-4
  digits redacted token; the full number is NOT printed in the PDF.
* ``jsic_medium``: JSIC major/medium code (e.g. ``E``, ``D``, ``E29``).
* ``prefecture``: 都道府県 string matching ``programs.prefecture`` /
  ``jpi_adoption_records.prefecture`` value.

Usage
-----
    python scripts/etl/generate_consultant_monthly_pack.py \
        --month 2026-04 \
        --csv data/sample_consultant_clients.csv \
        --out dist/consultant_packs

Constraints
-----------
* read-only against autonomath.db + jpintel.db
* NO LLM call
* PII fence: ``houjin_bangou`` → last-4 only; no 個人氏名 surface
* §52 / §47条の2 disclaimer rendered into every PDF
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
TEMPLATE_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "templates" / "consultant_monthly_pack.html"
DEFAULT_OUT_DIR = REPO_ROOT / "dist" / "consultant_packs"
DEFAULT_RATE_YEN = 3

_JST = timezone(timedelta(hours=9))

# Per-client request count in the ¥3/req model. Section breakdown:
#   - Section 1 amendments: 1 list call + N entity-detail probes  (~ 10..30)
#   - Section 2 eligible programs: 1 search + N citation lookups   (~ 15..30)
#   - Section 3 adoptions: 1 search + N program-resolution probes  (~ 10..20)
#   - Section 4 enforcement: 1 search + N detail probes            (~ 5..15)
#   - Section 5 citations: cached (free)
# Total realistic envelope: 50..100 req → 平均 75 req → ¥225/PDF.
DEFAULT_REQ_COUNT_PER_CLIENT = 75

FIELD_LABEL_JA: dict[str, str] = {
    "amount_max_yen": "上限金額",
    "subsidy_rate_max": "補助率上限",
    "target_set_json": "対象セット",
    "source_url": "出典 URL",
    "source_fetched_at": "出典取得時刻",
    "projection_regression_candidate": "再投影候補",
    "deadline": "申請締切",
    "eligibility_text": "対象要件",
}

# JSIC major code → 日本語ラベル (subset; falls back to raw code).
_JSIC_MAJOR_LABEL: dict[str, str] = {
    "A": "農業・林業",
    "B": "漁業",
    "C": "鉱業・採石業・砂利採取業",
    "D": "建設業",
    "E": "製造業",
    "F": "電気・ガス・熱供給・水道業",
    "G": "情報通信業",
    "H": "運輸業・郵便業",
    "I": "卸売業・小売業",
    "J": "金融業・保険業",
    "K": "不動産業・物品賃貸業",
    "L": "学術研究・専門・技術サービス業",
    "M": "宿泊業・飲食サービス業",
    "N": "生活関連サービス業・娯楽業",
    "O": "教育・学習支援業",
    "P": "医療・福祉",
    "Q": "複合サービス事業",
    "R": "サービス業",
    "S": "公務",
    "T": "分類不能の産業",
}

# Issuing-authority keyword set used in section 4. We map JSIC major to the
# overlapping authority substrings that historically file enforcement.
_AUTHORITY_KEYWORDS_BY_JSIC: dict[str, tuple[str, ...]] = {
    "A": ("農林水産省", "農政局", "林野庁"),
    "D": ("国土交通省", "地方整備局", "建設業"),
    "E": ("経済産業省", "厚生労働省", "PMDA", "医薬品医療機器総合機構"),
    "G": ("総務省", "経済産業省", "個人情報保護委員会"),
    "H": ("国土交通省", "運輸局", "海上保安庁"),
    "I": ("経済産業省", "公正取引委員会", "消費者庁"),
    "J": ("金融庁", "財務省"),
    "K": ("国土交通省", "東京地方整備局"),
    "L": ("経済産業省", "金融庁"),
    "M": ("厚生労働省", "観光庁"),
    "P": ("厚生労働省", "PMDA", "医薬品医療機器総合機構"),
}


# ---------------------------------------------------------------------------
# CSV input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClientRow:
    client_id: str
    client_label: str
    houjin_bangou: str
    jsic_medium: str
    prefecture: str


_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_HOUJIN_RE = re.compile(r"^\d{13}$")


def parse_clients_csv(path: Path) -> list[ClientRow]:
    if not path.exists():
        raise SystemExit(f"clients CSV not found: {path}")
    out: list[ClientRow] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"client_id", "client_label", "houjin_bangou", "jsic_medium", "prefecture"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"clients CSV missing columns: {sorted(missing)} (got {reader.fieldnames})"
            )
        for i, row in enumerate(reader, start=2):
            client_id = (row.get("client_id") or "").strip()
            label = (row.get("client_label") or "").strip()
            houjin = (row.get("houjin_bangou") or "").strip()
            jsic = (row.get("jsic_medium") or "").strip().upper()
            pref = (row.get("prefecture") or "").strip()
            if not _CLIENT_ID_RE.match(client_id):
                raise SystemExit(f"row {i}: invalid client_id {client_id!r}")
            if not _HOUJIN_RE.match(houjin):
                raise SystemExit(f"row {i}: houjin_bangou must be 13 digits, got {houjin!r}")
            if not jsic or not pref or not label:
                raise SystemExit(f"row {i}: jsic_medium / prefecture / label must be non-empty")
            out.append(
                ClientRow(
                    client_id=client_id,
                    client_label=label,
                    houjin_bangou=houjin,
                    jsic_medium=jsic,
                    prefecture=pref,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Month parsing
# ---------------------------------------------------------------------------


def parse_month(arg: str | None) -> tuple[str, date, date]:
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
# DB helpers
# ---------------------------------------------------------------------------


def open_ro(path: Path) -> sqlite3.Connection:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"DB not available: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Section 1: amendments
# ---------------------------------------------------------------------------


def _amount_yen_display(value: str | None) -> str:
    if not value:
        return "(未設定)"
    try:
        n = int(float(value))
        return f"{n:,} 円"
    except (TypeError, ValueError):
        return value if len(value) <= 60 else value[:60] + "…"


def _rate_display(value: str | None) -> str:
    if not value:
        return "(未設定)"
    try:
        f = float(value)
        if f > 1.0:  # raw percent already
            return f"{f:.1f}%"
        return f"{f * 100:.1f}%"
    except (TypeError, ValueError):
        return value


def _truncate(value: str | None, *, limit: int = 80) -> str:
    if value is None or value == "":
        return "(未設定)"
    s = str(value).replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def fetch_amendments(
    conn: sqlite3.Connection,
    *,
    start: date,
    end: date,
    jsic_medium: str,
    prefecture: str,
    limit: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return (rendered_rows, citation_rows).

    Filters program-kind amendments whose entity raw_json prefecture
    matches OR whose authority_level is 'national' (i.e. nationwide
    programs are surfaced for all prefectures).
    """
    rows = conn.execute(
        """
        SELECT d.diff_id, d.entity_id, d.field_name, d.prev_value, d.new_value,
               d.detected_at, d.source_url, e.primary_name, e.record_kind,
               e.confidence, e.raw_json, e.source_url AS entity_source_url
          FROM am_amendment_diff AS d
          LEFT JOIN am_entities AS e ON d.entity_id = e.canonical_id
         WHERE d.detected_at >= ? AND d.detected_at < ?
           AND COALESCE(e.record_kind, '') IN ('program', 'tax_measure', 'law')
         ORDER BY d.detected_at DESC
         LIMIT ?
        """,
        (start.isoformat(), end.isoformat(), limit * 6),
    ).fetchall()
    out_rows: list[dict[str, Any]] = []
    cites: list[dict[str, str]] = []
    for r in rows:
        if len(out_rows) >= limit:
            break
        try:
            raw = json.loads(r["raw_json"]) if r["raw_json"] else {}
        except (json.JSONDecodeError, TypeError):
            raw = {}
        ent_pref = (raw.get("prefecture") or "").strip()
        authority_level = (raw.get("authority_level") or "").strip()
        # Nationwide programs always pass; prefectural passes only on match.
        if ent_pref and ent_pref != prefecture and authority_level != "national":
            continue
        field_name = r["field_name"]
        label = FIELD_LABEL_JA.get(field_name, field_name)
        if field_name == "amount_max_yen":
            prev_d = _amount_yen_display(r["prev_value"])
            new_d = _amount_yen_display(r["new_value"])
        elif field_name == "subsidy_rate_max":
            prev_d = _rate_display(r["prev_value"])
            new_d = _rate_display(r["new_value"])
        else:
            prev_d = _truncate(r["prev_value"], limit=40)
            new_d = _truncate(r["new_value"], limit=40)
        confidence = r["confidence"] or 0.0
        if confidence >= 0.93:
            tier = "S"
        elif confidence >= 0.88:
            tier = "A"
        elif confidence >= 0.80:
            tier = "B"
        else:
            tier = "C"
        out_rows.append(
            {
                "entity_name": r["primary_name"] or r["entity_id"],
                "field_label": label,
                "prev_display": prev_d,
                "new_display": new_d,
                "detected_date": (r["detected_at"] or "")[:10] or "—",
                "tier": tier,
            }
        )
        url = r["source_url"] or r["entity_source_url"]
        if url:
            cites.append({"section": "1", "label": r["primary_name"] or r["entity_id"], "url": url})
    return out_rows, cites


# ---------------------------------------------------------------------------
# Section 2: eligible programs
# ---------------------------------------------------------------------------


def fetch_eligible_programs(
    conn: sqlite3.Connection,
    *,
    prefecture: str,
    jsic_medium: str,
    limit: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = conn.execute(
        """
        SELECT unified_id, primary_name, authority_name, authority_level,
               prefecture, program_kind, amount_max_man_yen, subsidy_rate,
               tier, official_url, source_url
          FROM programs
         WHERE excluded = 0
           AND tier IN ('S', 'A', 'B')
           AND (prefecture = ? OR prefecture IS NULL OR prefecture = ''
                OR authority_level = 'national')
         ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1
                            WHEN 'B' THEN 2 ELSE 3 END,
                  COALESCE(amount_max_man_yen, 0) DESC
         LIMIT ?
        """,
        (prefecture, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    cites: list[dict[str, str]] = []
    for r in rows:
        amount = r["amount_max_man_yen"]
        if amount is None:
            amount_fmt = "—"
        else:
            try:
                amount_fmt = f"{int(amount):,}"
            except (TypeError, ValueError):
                amount_fmt = "—"
        out.append(
            {
                "primary_name": r["primary_name"],
                "authority_name": r["authority_name"],
                "program_kind": r["program_kind"] or "—",
                "amount_max_man_yen_fmt": amount_fmt,
                "tier": r["tier"] or "—",
            }
        )
        url = r["official_url"] or r["source_url"]
        if url:
            cites.append({"section": "2", "label": r["primary_name"], "url": url})
    return out, cites


# ---------------------------------------------------------------------------
# Section 3: same-industry same-region adoptions
# ---------------------------------------------------------------------------


def fetch_adoptions(
    conn: sqlite3.Connection,
    *,
    jsic_medium: str,
    prefecture: str,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = conn.execute(
        """
        SELECT id, program_name_raw, project_title, announced_at, round_label,
               amount_granted_yen, source_url, prefecture, industry_jsic_medium
          FROM jpi_adoption_records
         WHERE prefecture = ?
           AND (industry_jsic_medium = ? OR industry_jsic_medium LIKE ?)
         ORDER BY COALESCE(announced_at, '') DESC,
                  COALESCE(amount_granted_yen, 0) DESC
         LIMIT ?
        """,
        (prefecture, jsic_medium, f"{jsic_medium}%", limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    cites: list[dict[str, str]] = []
    for r in rows:
        amount = r["amount_granted_yen"]
        if amount is None or amount == 0:
            amount_fmt = "—"
        else:
            try:
                amount_fmt = f"{int(amount) // 10000:,}"
            except (TypeError, ValueError):
                amount_fmt = "—"
        out.append(
            {
                "project_title": _truncate(r["project_title"], limit=80),
                "program_name_raw": _truncate(r["program_name_raw"], limit=40),
                "announced_at": (r["announced_at"] or "")[:10] or "—",
                "amount_granted_man_yen_fmt": amount_fmt,
                "round_label": r["round_label"],
            }
        )
        url = r["source_url"]
        if url:
            cites.append(
                {
                    "section": "3",
                    "label": _truncate(
                        (r["program_name_raw"] or "(制度名未掲載)")
                        + " — "
                        + (r["project_title"] or ""),
                        limit=80,
                    ),
                    "url": url,
                }
            )
    return out, cites


# ---------------------------------------------------------------------------
# Section 4: enforcement (industry filter via authority keyword set)
# ---------------------------------------------------------------------------


def fetch_enforcement(
    conn: sqlite3.Connection,
    *,
    jsic_medium: str,
    start: date,
    limit: int = 3,
    lookback_days: int = 90,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    keywords = _AUTHORITY_KEYWORDS_BY_JSIC.get(jsic_medium[:1], ())
    if not keywords:
        return [], []
    # We look back up to 90 days from the start of the target month so even
    # months without a fresh enforcement still surface relevant context.
    cutoff = (start - timedelta(days=lookback_days)).isoformat()
    placeholders = " OR ".join(["issuing_authority LIKE ?"] * len(keywords))
    params: list[Any] = [cutoff]
    params.extend(f"%{kw}%" for kw in keywords)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT enforcement_id, issuing_authority, enforcement_kind,
               issuance_date, reason_summary, source_url
          FROM am_enforcement_detail
         WHERE issuance_date >= ?
           AND ({placeholders})
         ORDER BY issuance_date DESC
         LIMIT ?
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    cites: list[dict[str, str]] = []
    for r in rows:
        out.append(
            {
                "issuing_authority": r["issuing_authority"],
                "enforcement_kind": r["enforcement_kind"] or "other",
                "issuance_date": r["issuance_date"],
                "reason_truncated": _truncate(r["reason_summary"], limit=140),
            }
        )
        url = r["source_url"]
        if url:
            cites.append(
                {
                    "section": "4",
                    "label": f"{r['issuing_authority']} — {r['enforcement_kind']} {r['issuance_date']}",
                    "url": url,
                }
            )
    return out, cites


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _client_id_token(client_id: str, houjin: str) -> str:
    return hashlib.sha256(f"{client_id}|{houjin}".encode()).hexdigest()[:16]


def _redact_houjin(houjin: str) -> str:
    return f"****{houjin[-4:]}" if len(houjin) >= 4 else "****"


def _jsic_label(jsic_medium: str) -> str:
    major = (jsic_medium or "")[:1].upper()
    label = _JSIC_MAJOR_LABEL.get(major)
    return f"{jsic_medium} ({label})" if label else jsic_medium


def _corpus_snapshot_id(am_conn: sqlite3.Connection) -> str:
    today_jst = datetime.now(_JST).strftime("corpus-%Y-%m-%d")
    try:
        row = am_conn.execute("SELECT MAX(last_verified) FROM am_source").fetchone()
    except sqlite3.Error:
        return today_jst
    if not row or not row[0]:
        return today_jst
    raw = str(row[0])
    parsed: datetime | None = None
    candidates = [raw, raw.replace(" ", "T")]
    if "+" not in raw and "Z" not in raw:
        candidates.append(raw.replace(" ", "T") + "+00:00")
    for cand in candidates:
        try:
            parsed = datetime.fromisoformat(cand)
            break
        except ValueError:
            continue
    if parsed is None:
        return today_jst
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(_JST).strftime("corpus-%Y-%m-%d")


def _render_template(template: str, ctx: dict[str, Any]) -> str:
    """Render the template using Jinja2 (no fallback — Jinja is a hard dep).

    We import here so a missing optional dep surfaces a single clear error
    rather than at module import.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:
        raise SystemExit(
            "jinja2 is required to render the consultant pack template; "
            "install via `pip install -e '.[dev]'`"
        ) from exc
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_PATH.parent)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template(TEMPLATE_PATH.name).render(**ctx)


def _render_pdf_bytes(html_str: str) -> bytes:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "weasyprint is required to render the consultant pack PDF; "
            "install via `pip install -e '.[dev,site]'` (and ensure system "
            "libs cairo/pango/gdk-pixbuf are present)"
        ) from exc
    return HTML(string=html_str).write_pdf()


@dataclass
class PackResult:
    client: ClientRow
    pdf_path: Path | None
    html_path: Path | None
    page_count: int  # heuristic: counted via PDF /Type/Page in bytes
    req_count: int
    yen: int
    section_counts: dict[str, int] = field(default_factory=dict)


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return the number of pages in the PDF.

    Uses ``pypdf.PdfReader`` when available (production path) and falls
    back to a coarse byte-count heuristic that works on uncompressed PDFs.
    WeasyPrint produces compressed PDFs so the heuristic typically
    under-counts — we treat the heuristic as a last-resort lower bound
    rather than ground truth.
    """
    try:
        import io

        from pypdf import PdfReader  # type: ignore[import-not-found]

        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:  # noqa: BLE001 — best-effort page probe
        return max(1, pdf_bytes.count(b"/Type /Page") - pdf_bytes.count(b"/Type /Pages"))


def _build_context(
    *,
    client: ClientRow,
    month_label: str,
    am_conn: sqlite3.Connection,
    jp_conn: sqlite3.Connection,
    start: date,
    end: date,
    req_count: int,
    rate_yen: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    amendments, c1 = fetch_amendments(
        am_conn,
        start=start,
        end=end,
        jsic_medium=client.jsic_medium,
        prefecture=client.prefecture,
    )
    eligible, c2 = fetch_eligible_programs(
        jp_conn, prefecture=client.prefecture, jsic_medium=client.jsic_medium
    )
    adoptions, c3 = fetch_adoptions(
        am_conn, jsic_medium=client.jsic_medium, prefecture=client.prefecture
    )
    enforcements, c4 = fetch_enforcement(am_conn, jsic_medium=client.jsic_medium, start=start)

    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in c1 + c2 + c3 + c4:
        key = c["url"]
        if key in seen:
            continue
        seen.add(key)
        citations.append(c)

    rendered_at = datetime.now(_JST).strftime("%Y-%m-%d %H:%M")
    snapshot = _corpus_snapshot_id(am_conn)

    ctx = {
        "month_label": month_label,
        "client_label": client.client_label,
        "houjin_bangou_redacted": _redact_houjin(client.houjin_bangou),
        "client_id_token": _client_id_token(client.client_id, client.houjin_bangou),
        "jsic_label": _jsic_label(client.jsic_medium),
        "jsic_medium": client.jsic_medium,
        "prefecture": client.prefecture,
        "rendered_at": rendered_at,
        "corpus_snapshot_id": snapshot,
        "req_count": req_count,
        "req_yen": req_count * rate_yen,
        "amendments": amendments,
        "eligible_programs": eligible,
        "adoptions": adoptions,
        "enforcements": enforcements,
        "citations": citations,
    }
    counts = {
        "amendments": len(amendments),
        "eligible_programs": len(eligible),
        "adoptions": len(adoptions),
        "enforcements": len(enforcements),
        "citations": len(citations),
    }
    return ctx, counts


def generate_pack_for_client(
    *,
    client: ClientRow,
    month_label: str,
    am_conn: sqlite3.Connection,
    jp_conn: sqlite3.Connection,
    start: date,
    end: date,
    out_dir: Path,
    req_count: int = DEFAULT_REQ_COUNT_PER_CLIENT,
    rate_yen: int = DEFAULT_RATE_YEN,
    write_html: bool = True,
    write_pdf: bool = True,
) -> PackResult:
    ctx, counts = _build_context(
        client=client,
        month_label=month_label,
        am_conn=am_conn,
        jp_conn=jp_conn,
        start=start,
        end=end,
        req_count=req_count,
        rate_yen=rate_yen,
    )
    html_str = _render_template(str(TEMPLATE_PATH), ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9._:-]", "_", client.client_id)
    base = f"{month_label}_{safe_id}"
    pdf_path: Path | None = None
    html_path: Path | None = None
    page_count = 0
    if write_html:
        html_path = out_dir / f"{base}.html"
        html_path.write_text(html_str, encoding="utf-8")
    if write_pdf:
        pdf_bytes = _render_pdf_bytes(html_str)
        pdf_path = out_dir / f"{base}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        page_count = _count_pdf_pages(pdf_bytes)
    return PackResult(
        client=client,
        pdf_path=pdf_path,
        html_path=html_path,
        page_count=page_count,
        req_count=req_count,
        yen=req_count * rate_yen,
        section_counts=counts,
    )


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def run(
    *,
    csv_path: Path,
    month_arg: str | None,
    out_dir: Path,
    autonomath_db: Path,
    jpintel_db: Path,
    req_count: int,
    rate_yen: int,
    dry_run: bool,
) -> int:
    clients = parse_clients_csv(csv_path)
    month_label, start, end = parse_month(month_arg)
    am_conn = open_ro(autonomath_db)
    jp_conn = open_ro(jpintel_db)
    try:
        results: list[PackResult] = []
        for client in clients:
            res = generate_pack_for_client(
                client=client,
                month_label=month_label,
                am_conn=am_conn,
                jp_conn=jp_conn,
                start=start,
                end=end,
                out_dir=out_dir,
                req_count=req_count,
                rate_yen=rate_yen,
                write_html=True,
                write_pdf=not dry_run,
            )
            results.append(res)
            if dry_run:
                print(
                    f"[dry-run] {client.client_id}: "
                    f"sections={json.dumps(res.section_counts, ensure_ascii=False)}"
                )
            else:
                print(
                    f"{client.client_id}: pdf={res.pdf_path} "
                    f"pages={res.page_count} req={res.req_count} "
                    f"yen={res.yen} "
                    f"sections={json.dumps(res.section_counts, ensure_ascii=False)}"
                )
    finally:
        am_conn.close()
        jp_conn.close()

    if not results:
        return 0
    total_yen = sum(r.yen for r in results)
    total_pages = sum(r.page_count for r in results) if not dry_run else 0
    print(
        f"---\nclients={len(results)} total_pages={total_pages} "
        f"total_req={sum(r.req_count for r in results)} "
        f"total_yen={total_yen}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=textwrap.dedent(__doc__))
    parser.add_argument("--csv", type=Path, required=True, help="顧問先 CSV path")
    parser.add_argument("--month", type=str, default=None, help="YYYY-MM (default: 前月)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument(
        "--req-count",
        type=int,
        default=DEFAULT_REQ_COUNT_PER_CLIENT,
        help="¥3-rate metered request count to attribute per client (default 75)",
    )
    parser.add_argument("--rate-yen", type=int, default=DEFAULT_RATE_YEN)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="HTML だけ書いて PDF render は省略 (高速 audit 用)",
    )
    args = parser.parse_args()
    return run(
        csv_path=args.csv,
        month_arg=args.month,
        out_dir=args.out,
        autonomath_db=args.autonomath_db,
        jpintel_db=args.jpintel_db,
        req_count=args.req_count,
        rate_yen=args.rate_yen,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
