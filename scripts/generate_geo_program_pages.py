#!/usr/bin/env python3
"""Generate prefecture × program SEO crosspages for AutonoMath (jpcite.com).

Generates 47 都道府県 × top-N programs (default 50) static HTML pages, plus a
matching sitemap. Honest copy: each page declares the actual relevance —
"national" programs are flagged as nationwide, prefecture-locked programs to
non-matching prefectures are flagged honestly ("該当する採択事例なし"), and
adoption counts are pulled directly from `case_studies.programs_used_json`
LIKE matching against the program's primary_name.

Architecture (mirrors scripts/generate_program_pages.py):
- DB:        data/jpintel.db (programs + case_studies)
- Template:  site/_templates/cross.html (Jinja2)
- Output:    site/cross/{pref-slug}/{program-slug}.html
- Sitemap:   site/sitemap-cross.xml (referenced from sitemap-index.xml)

Top-N selection ranking:
  Tier S/A first (S preferred), then sort by max_amount_man_yen DESC,
  then by adoption_count_total DESC (sum of case_studies references),
  then by primary_name (stable tie-break).

Usage:
    uv run python scripts/generate_geo_program_pages.py \
        --db data/jpintel.db \
        --out site/cross \
        --domain jpcite.com \
        --top 50

Sample mode (writes 5 sample pages — 1 prefecture × 5 programs by default):
    uv run python scripts/generate_geo_program_pages.py --samples 5

Constraints
-----------
- Each page LINKS to the API/MCP, never calls them.
- 税理士法 §52 disclaimer in footer (template-level, not touched here).
- Idempotent — `_write_if_changed` skips unchanged outputs.
- Honest copy — no fabrication when adoption_count == 0; the page says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterable

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jinja2 is required.\n")
    raise

try:
    import pykakasi  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: pykakasi is required.\n")
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_TEMPLATE_DIR = REPO_ROOT / "site" / "_templates"
DEFAULT_OUT = REPO_ROOT / "site" / "cross"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-cross.xml"
DEFAULT_DOMAIN = "jpcite.com"
DEFAULT_TOP_N = 50

_JST = timezone(timedelta(hours=9))

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _pref_slugs import PREFECTURES, JA_TO_SLUG as _PREF_JA_TO_SLUG  # type: ignore
except ImportError:  # pragma: no cover
    PREFECTURES = []
    _PREF_JA_TO_SLUG = {}

LOG = logging.getLogger("generate_geo_program_pages")


# Bookyou株式会社 facts
OPERATOR_NAME = "Bookyou株式会社"
OPERATOR_CORPORATE_NUMBER = "T8010001213708"
OPERATOR_REP = "梅田茂利"
OPERATOR_EMAIL = "info@bookyou.net"
OPERATOR_ADDRESS_JP = "東京都文京区小日向2-22-1"

KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


# ---------------------------------------------------------------------------
# Top-N program selection
# ---------------------------------------------------------------------------

# Tier S + A (highest-confidence, indexable, nonempty source_url, non-aggregator).
# Joined with COUNT(*) over case_studies.programs_used_json to rank by
# real-world adoption volume in addition to amount_max_man_yen.
TOP_PROGRAMS_SQL = """
SELECT
    p.unified_id,
    p.primary_name,
    p.aliases_json,
    p.authority_level,
    p.authority_name,
    p.prefecture,
    p.municipality,
    p.program_kind,
    p.official_url,
    p.amount_max_man_yen,
    p.amount_min_man_yen,
    p.subsidy_rate,
    p.tier,
    p.target_types_json,
    p.funding_purpose_json,
    p.source_url,
    p.source_fetched_at,
    p.updated_at
FROM programs p
WHERE p.excluded = 0
  AND p.tier IN ('S','A')
  AND p.source_url IS NOT NULL AND p.source_url <> ''
  AND (p.authority_name IS NULL OR p.authority_name NOT LIKE '%noukaweb%')
ORDER BY
    CASE p.tier WHEN 'S' THEN 0 ELSE 1 END,
    COALESCE(p.amount_max_man_yen, 0) DESC,
    p.primary_name
"""


def _adoption_total(conn: sqlite3.Connection, primary_name: str) -> int:
    """Total case_studies referencing a program by primary_name substring.

    Uses LIKE because programs_used_json is a JSON list of free-form strings
    (per docs: case_studies.programs_used_json -> list[str]).
    """
    if not primary_name:
        return 0
    pattern = f"%{primary_name}%"
    cur = conn.execute(
        "SELECT COUNT(*) FROM case_studies WHERE programs_used_json LIKE ?",
        (pattern,),
    )
    return int(cur.fetchone()[0] or 0)


def _adoption_in_pref(
    conn: sqlite3.Connection, primary_name: str, pref_ja: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Return up to `limit` case_studies in the given prefecture that reference
    the program primary_name in programs_used_json.

    Output dicts contain: case_id, company_name, case_title, case_summary,
    industry_name, total_subsidy_received_yen, source_url.
    """
    if not primary_name or not pref_ja:
        return []
    pattern = f"%{primary_name}%"
    sql = """
    SELECT case_id, company_name, case_title, case_summary, industry_name,
           total_subsidy_received_yen, source_url, publication_date
    FROM case_studies
    WHERE programs_used_json LIKE ?
      AND prefecture = ?
    ORDER BY publication_date DESC, case_id
    LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, (pattern, pref_ja, limit))]


def _adoption_count_in_pref(
    conn: sqlite3.Connection, primary_name: str, pref_ja: str
) -> int:
    if not primary_name or not pref_ja:
        return 0
    pattern = f"%{primary_name}%"
    cur = conn.execute(
        """
        SELECT COUNT(*) FROM case_studies
        WHERE programs_used_json LIKE ? AND prefecture = ?
        """,
        (pattern, pref_ja),
    )
    return int(cur.fetchone()[0] or 0)


def select_top_programs(
    conn: sqlite3.Connection, top_n: int
) -> list[dict[str, Any]]:
    """Return top-N programs ranked by tier S>A, max_amount DESC, adoption_total DESC.

    Pulls all tier S + A rows then re-ranks in Python because adoption_total
    requires a per-row LIKE query that is too expensive to push into the SQL
    ORDER BY when the result is bounded to ~1,500 rows.
    """
    rows = [dict(r) for r in conn.execute(TOP_PROGRAMS_SQL)]
    LOG.info("tier S+A pool size: %d", len(rows))
    # Annotate adoption_total in-memory.
    for r in rows:
        r["_adoption_total"] = _adoption_total(conn, r.get("primary_name") or "")

    def rank_key(r: dict[str, Any]) -> tuple[int, float, int, str]:
        tier_rank = 0 if r.get("tier") == "S" else 1
        amt = -float(r.get("amount_max_man_yen") or 0)  # DESC via negation
        adopt = -int(r.get("_adoption_total") or 0)
        return (tier_rank, amt, adopt, r.get("primary_name") or "")

    rows.sort(key=rank_key)
    return rows[:top_n]


# ---------------------------------------------------------------------------
# Slug — reused from generate_program_pages.py (keeps slug parity)
# ---------------------------------------------------------------------------

_KKS = pykakasi.kakasi()


def slugify(name: str, unified_id: str) -> str:
    """Same algorithm as scripts/generate_program_pages.py:slugify.

    `{hepburn-romaji}-{sha1-6}` so internal links to /programs/{slug}.html
    resolve identically.
    """
    try:
        parts = _KKS.convert(name or "")
        romaji = " ".join(p.get("hepburn", "") for p in parts)
    except Exception:
        romaji = ""
    romaji = romaji.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "-", romaji).strip("-")
    if len(ascii_only) > 60:
        truncated = ascii_only[:60]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        ascii_only = truncated
    if not ascii_only:
        ascii_only = "program"
    suffix = hashlib.sha1(unified_id.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_only}-{suffix}"


# ---------------------------------------------------------------------------
# Helpers (compact subset of generate_program_pages.py)
# ---------------------------------------------------------------------------


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


def _normalize_iso_date(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, str):
        if "T" in raw:
            return raw.split("T", 1)[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return raw[:10]
    return str(raw)


def _last_updated_ja(row: dict[str, Any]) -> str:
    upd = row.get("source_fetched_at") or row.get("updated_at")
    iso = _normalize_iso_date(upd)
    if iso and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        y, m, d = iso.split("-")
        return f"{int(y)}年{int(m)}月{int(d)}日"
    return datetime.now(_JST).date().strftime("%Y年%m月%d日")


def _amount_line(max_man: float | None, min_man: float | None) -> str | None:
    if max_man is None and min_man is None:
        return None
    if max_man is not None and min_man is not None and min_man > 0:
        return f"{int(min_man):,}万円 〜 {int(max_man):,}万円"
    if max_man is not None:
        return f"最大 {int(max_man):,}万円"
    if min_man is not None:
        return f"{int(min_man):,}万円〜"
    return None


def _source_domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


_PREF_HOST_JA = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県", "ibaraki": "茨城県",
    "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県", "chiba": "千葉県",
    "tokyo": "東京都", "kanagawa": "神奈川県", "niigata": "新潟県", "toyama": "富山県",
    "ishikawa": "石川県", "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県", "tottori": "鳥取県", "shimane": "島根県",
    "okayama": "岡山県", "hiroshima": "広島県", "yamaguchi": "山口県", "tokushima": "徳島県",
    "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県", "fukuoka": "福岡県",
    "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県", "oita": "大分県",
    "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}


def _source_org_guess(domain: str) -> str | None:
    if not domain:
        return None
    mapping = [
        ("chusho.meti.go.jp", "中小企業庁"),
        ("maff.go.jp", "農林水産省"),
        ("meti.go.jp", "経済産業省"),
        ("mhlw.go.jp", "厚生労働省"),
        ("mlit.go.jp", "国土交通省"),
        ("env.go.jp", "環境省"),
        ("mext.go.jp", "文部科学省"),
        ("mof.go.jp", "財務省"),
        ("soumu.go.jp", "総務省"),
        ("jfc.go.jp", "日本政策金融公庫"),
        ("smrj.go.jp", "中小機構"),
        ("jeed.go.jp", "高齢・障害・求職者雇用支援機構"),
        ("nta.go.jp", "国税庁"),
    ]
    for key, name in mapping:
        if domain.endswith(key):
            return name
    if domain.endswith("metro.tokyo.lg.jp") or domain.endswith("metro.tokyo.jp"):
        return "東京都"
    m = re.search(r"(?:^|\.)pref\.([a-z]+)\.(?:lg\.jp|jp)$", domain)
    if m:
        pref_key = m.group(1)
        pref_ja = _PREF_HOST_JA.get(pref_key)
        if pref_ja:
            return pref_ja
    m = re.search(r"(?:^|\.)city\.[a-z0-9-]+\.([a-z]+)\.(?:lg\.jp|jp)$", domain)
    if m:
        pref_key = m.group(1)
        pref_ja = _PREF_HOST_JA.get(pref_key)
        if pref_ja:
            return f"地方自治体 ({pref_ja})"
    if domain.endswith(".lg.jp"):
        return "地方自治体"
    return None


def _resolve_agency(row: dict[str, Any]) -> str | None:
    auth = row.get("authority_name")
    if auth:
        auth_s = str(auth).strip()
        if auth_s and auth_s not in {"所管官公庁", "公開元", "不明"} and "noukaweb" not in auth_s:
            return auth_s
    src = row.get("source_url") or row.get("official_url") or ""
    host = _source_domain(src)
    return _source_org_guess(host)


# ---------------------------------------------------------------------------
# Applicability classification (pref × program)
# ---------------------------------------------------------------------------


def classify_applicability(row: dict[str, Any], pref_ja: str) -> str:
    """Return one of: national / matched_prefecture / other_prefecture / municipality / unknown.

    - national               -> authority_level == 'national' OR no prefecture set
    - matched_prefecture     -> authority_level == 'prefecture' AND prefecture == pref_ja
    - other_prefecture       -> authority_level == 'prefecture' AND prefecture != pref_ja
    - municipality           -> authority_level == 'municipality' (locked to one city/town)
    - unknown                -> anything else (financial, etc.)
    """
    auth = (row.get("authority_level") or "").lower()
    program_pref = row.get("prefecture") or ""
    if auth == "national" or auth == "国":
        return "national"
    if auth == "prefecture":
        if program_pref == pref_ja:
            return "matched_prefecture"
        return "other_prefecture"
    if auth == "municipality":
        if program_pref == pref_ja:
            return "municipality"
        return "other_prefecture"
    if not program_pref:
        return "national"
    return "unknown"


def applicability_label(status: str, pref_ja: str, program_pref: str) -> str:
    if status == "national":
        return f"全国対応 (中央省庁所管) — {pref_ja} の事業者も対象になり得る"
    if status == "matched_prefecture":
        return f"{pref_ja} が所管 (地域限定)"
    if status == "other_prefecture":
        return f"所管は {program_pref} — {pref_ja} は対象外の可能性が高い"
    if status == "municipality":
        return "基礎自治体限定の制度"
    return "適用範囲は公募要領を参照"


def applicability_paragraph(status: str, pref_ja: str, program_pref: str, name: str) -> str:
    if status == "national":
        return (
            f"「{name}」は中央省庁が所管する全国対応の制度です。{pref_ja} に所在する事業者・個人も、"
            "他都道府県と同条件で申請対象に含まれ得ます。実際の対象判定は公募要領の事業所所在地・"
            "業種・規模要件などの個別要件に依ります。"
        )
    if status == "matched_prefecture":
        return (
            f"「{name}」は {pref_ja} が所管する地域限定の制度であり、{pref_ja} に事業所登記がある"
            "事業者が主たる対象です。申請に際しては所在要件・業種要件・対象設備・対象経費など"
            "公募要領の個別要件をご確認ください。"
        )
    if status == "other_prefecture":
        return (
            f"「{name}」の所管は {program_pref} です。{pref_ja} 所在の事業者は、原則として本制度の"
            f"直接申請対象になりません。{pref_ja} で利用できる類似制度は本ページ末尾の "
            f"「{pref_ja} で利用できる他の制度」セクションからご確認ください。"
        )
    if status == "municipality":
        return (
            f"「{name}」は特定の基礎自治体が運営する自治体限定の制度です。{pref_ja} 内の他自治体"
            "に所在する場合、所属自治体の類似制度を別途ご確認ください。"
        )
    return f"「{name}」の地理的適用範囲は公募要領をご確認ください。"


# ---------------------------------------------------------------------------
# Meta + JSON-LD
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def page_title(pref_ja: str, name: str) -> str:
    raw = f"{pref_ja} {name} | 申請方法・採択事例 | jpcite"
    return _truncate(raw, 60)


def meta_description(
    pref_ja: str,
    row: dict[str, Any],
    adoption_count: int,
    status: str,
    program_pref: str,
) -> str:
    name = row.get("primary_name") or ""
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    amt = _amount_line(
        row.get("amount_max_man_yen"), row.get("amount_min_man_yen")
    ) or "公募要領参照"
    if status == "other_prefecture":
        applicability = f"所管は{program_pref}のため{pref_ja}は対象外"
    elif status == "national":
        applicability = f"{pref_ja}も対象になり得る全国制度"
    elif status == "matched_prefecture":
        applicability = f"{pref_ja}が所管"
    elif status == "municipality":
        applicability = "基礎自治体限定"
    else:
        applicability = "適用範囲は公募要領参照"
    adoption_clause = (
        f"{pref_ja}の採択事例 {adoption_count} 件確認"
        if adoption_count > 0
        else f"{pref_ja}の採択事例は未確認"
    )
    parts = [
        f"{pref_ja}における{name}の申請方法・採択事例。",
        f"{kind}・{applicability}。",
        f"{adoption_clause}。",
        f"金額目安: {amt}。",
        "出典は中央省庁・自治体の一次資料に限定。AutonoMath 集約。",
    ]
    text = "".join(parts)
    return _truncate(text, 160)


ORG_NODE_ID = "#autonomath-org"


def _org_node(domain: str) -> dict[str, Any]:
    return {
        "@type": "Organization",
        "@id": ORG_NODE_ID,
        "name": "AutonoMath",
        "url": f"https://{domain}/",
        "legalName": OPERATOR_NAME,
        "taxID": OPERATOR_CORPORATE_NUMBER,
        "founder": {"@type": "Person", "name": OPERATOR_REP},
        "address": {
            "@type": "PostalAddress",
            "addressCountry": "JP",
            "addressLocality": OPERATOR_ADDRESS_JP,
        },
        "contactPoint": {
            "@type": "ContactPoint",
            "email": OPERATOR_EMAIL,
            "contactType": "customer support",
        },
    }


def _place_node(pref_ja: str, pref_slug: str, domain: str) -> dict[str, Any]:
    return {
        "@type": "AdministrativeArea",
        "@id": f"#place-{pref_slug}",
        "name": pref_ja,
        "url": f"https://{domain}/prefectures/{pref_slug}.html",
        "addressCountry": "JP",
    }


def _service_node(
    row: dict[str, Any],
    domain: str,
    pref_ja: str,
    pref_slug: str,
    program_slug: str,
    program_slug_full: str,
    status: str,
    adoption_count: int,
) -> dict[str, Any]:
    kind = row.get("program_kind") or "subsidy"
    typ = "GovernmentService"
    if kind.startswith("loan"):
        typ = ["FinancialProduct", "LoanOrCredit"]
    elif "certif" in kind or kind.startswith("training"):
        typ = "EducationalOccupationalProgram"
    elif kind.startswith("tax"):
        typ = "GovernmentService"

    node: dict[str, Any] = {
        "@type": typ,
        "@id": f"#service-{program_slug}-in-{pref_slug}",
        "identifier": row.get("unified_id"),
        "name": row.get("primary_name"),
        "inLanguage": "ja",
        "url": f"https://{domain}/cross/{pref_slug}/{program_slug}.html",
        "publisher": {"@id": ORG_NODE_ID},
        "isBasedOn": {"@type": "CreativeWork", "url": row.get("source_url")},
        "areaServed": {"@id": f"#place-{pref_slug}"},
    }
    resolved_agency = _resolve_agency(row)
    if resolved_agency:
        node["provider"] = {
            "@type": "GovernmentOrganization",
            "name": resolved_agency,
        }
    amt_max = row.get("amount_max_man_yen")
    if amt_max is not None:
        node["amount"] = {
            "@type": "MonetaryAmount",
            "currency": "JPY",
            "value": int(amt_max * 10_000),
        }
    add_props = []
    add_props.append(
        {"@type": "PropertyValue", "name": "applicability_status", "value": status}
    )
    add_props.append(
        {
            "@type": "PropertyValue",
            "name": "adoption_count_in_prefecture",
            "value": adoption_count,
        }
    )
    if row.get("tier"):
        add_props.append(
            {"@type": "PropertyValue", "name": "tier", "value": row["tier"]}
        )
    node["additionalProperty"] = add_props
    # Cross-link to the canonical full program page.
    node["sameAs"] = f"https://{domain}/programs/{program_slug_full}"
    return node


def _breadcrumb_node(
    pref_ja: str, pref_slug: str, name: str, domain: str, slug: str
) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "ホーム",
                "item": f"https://{domain}/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": "都道府県別",
                "item": f"https://{domain}/prefectures/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": pref_ja,
                "item": f"https://{domain}/prefectures/{pref_slug}.html",
            },
            {
                "@type": "ListItem",
                "position": 4,
                "name": name,
                "item": f"https://{domain}/cross/{pref_slug}/{slug}.html",
            },
        ],
    }


def build_json_ld(
    row: dict[str, Any],
    domain: str,
    pref_ja: str,
    pref_slug: str,
    program_slug: str,
    program_slug_full: str,
    status: str,
    adoption_count: int,
) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@graph": [
            _org_node(domain),
            _place_node(pref_ja, pref_slug, domain),
            _breadcrumb_node(
                pref_ja, pref_slug, row.get("primary_name") or "", domain, program_slug
            ),
            _service_node(
                row,
                domain,
                pref_ja,
                pref_slug,
                program_slug,
                program_slug_full,
                status,
                adoption_count,
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@dataclass
class RenderContext:
    env: Environment
    template_name: str = "cross.html"

    def render(self, **ctx: Any) -> str:
        tmpl = self.env.get_template(self.template_name)
        return tmpl.render(**ctx)


def _build_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _yen_label(yen: int | None) -> str | None:
    if yen is None:
        return None
    try:
        v = int(yen)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 100_000_000:
        return f"{v / 100_000_000:.1f}億円"
    if v >= 10_000:
        return f"{v // 10_000:,}万円"
    return f"{v:,}円"


def render_pair(
    row: dict[str, Any],
    pref_ja: str,
    pref_slug: str,
    ctx: RenderContext,
    domain: str,
    conn: sqlite3.Connection,
    related_in_pref: list[dict[str, Any]],
) -> tuple[str, str]:
    """Return (program_slug, html)."""
    program_slug = slugify(row["primary_name"] or "", row["unified_id"])
    program_slug_full = program_slug  # full per-program URL uses the same slug.
    name = row.get("primary_name") or ""
    program_pref = row.get("prefecture") or ""
    status = classify_applicability(row, pref_ja)
    adoption_count = _adoption_count_in_pref(conn, name, pref_ja)
    adoption_samples_raw = _adoption_in_pref(conn, name, pref_ja, limit=5)

    adoption_samples = []
    for c in adoption_samples_raw:
        adoption_samples.append(
            {
                "case_id": c.get("case_id"),
                "company_name": c.get("company_name"),
                "case_title": c.get("case_title"),
                "summary": (c.get("case_summary") or "")[:200] or None,
                "industry_name": c.get("industry_name"),
                "subsidy_label": _yen_label(c.get("total_subsidy_received_yen")),
                "source_url": c.get("source_url"),
            }
        )

    source_url = row.get("source_url") or row.get("official_url") or ""
    source_dom = _source_domain(source_url)
    resolved_agency = _resolve_agency(row)

    amt_line = _amount_line(
        row.get("amount_max_man_yen"), row.get("amount_min_man_yen")
    )
    amount_label = amt_line or "公募要領参照"
    amount_paragraph = (
        f"「{name}」の支援金額の目安は{amt_line}です。"
        if amt_line
        else f"「{name}」の支援金額は公募要領に記載されています。"
    ) + "金額・補助率は年度や採択類型により変動するため、必ず公式の最新公募要領をご確認ください。"

    provider_label = resolved_agency or "公募要領記載の所管機関"
    if resolved_agency and program_pref:
        provider_label = f"{resolved_agency} ({program_pref})"

    if adoption_count == 0:
        adoption_label = f"{pref_ja}の事例は AutonoMath 上では未確認"
    else:
        adoption_label = f"{pref_ja}で {adoption_count} 件確認"

    json_ld = build_json_ld(
        row,
        domain,
        pref_ja,
        pref_slug,
        program_slug,
        program_slug_full,
        status,
        adoption_count,
    )

    html = ctx.render(
        DOMAIN=domain,
        unified_id=row["unified_id"],
        primary_name=name,
        page_title=page_title(pref_ja, name),
        meta_description=meta_description(
            pref_ja, row, adoption_count, status, program_pref
        ),
        pref_ja=pref_ja,
        pref_slug=pref_slug,
        program_slug=program_slug,
        program_slug_full=program_slug_full,
        program_pref=program_pref,
        applicability_status=status,
        applicability_label=applicability_label(status, pref_ja, program_pref),
        applicability_paragraph=applicability_paragraph(
            status, pref_ja, program_pref, name
        ),
        kind_ja=KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度"),
        amount_label=amount_label,
        amount_paragraph=amount_paragraph,
        provider_label=provider_label,
        adoption_count=adoption_count,
        adoption_label=adoption_label,
        adoption_samples=adoption_samples,
        source_url=source_url,
        source_domain=source_dom,
        source_org=resolved_agency,
        fetched_at=_normalize_iso_date(row.get("source_fetched_at")),
        fetched_at_ja=_last_updated_ja(row),
        related_in_pref=related_in_pref,
        json_ld_pretty=json.dumps(json_ld, ensure_ascii=False, indent=2).replace(
            "</", "<\\/"
        ),
    )
    return program_slug, html


# ---------------------------------------------------------------------------
# Idempotent write
# ---------------------------------------------------------------------------


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def write_sitemap(
    entries: list[tuple[str, str, str, str]],
    path: Path,
    domain: str,
) -> None:
    """Each entry: (pref_slug, program_slug, lastmod_iso, tier).

    `tier` drives priority (S=0.7, A=0.6) and changefreq (S=weekly, A=monthly).
    Note: cross pages are derivative; their priority is intentionally lower
    than the canonical /programs/{slug}.html or /prefectures/{slug}.html.
    """
    if not entries:
        return
    cf_map = {"S": "weekly", "A": "monthly"}
    pr_map = {"S": "0.7", "A": "0.6"}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- auto-generated by scripts/generate_geo_program_pages.py -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for pref_slug, program_slug, lastmod, tier in entries:
        cf = cf_map.get(tier, "monthly")
        pr = pr_map.get(tier, "0.5")
        lines.append("  <url>")
        lines.append(
            f"    <loc>https://{domain}/cross/{pref_slug}/{program_slug}.html</loc>"
        )
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{cf}</changefreq>")
        lines.append(f"    <priority>{pr}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    _write_if_changed(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Top-level generation
# ---------------------------------------------------------------------------


def generate(
    db_path: Path,
    out_dir: Path,
    template_dir: Path,
    domain: str,
    top_n: int,
    sitemap_path: Path | None,
    samples_only: int | None,
) -> tuple[int, int, int, list[tuple[str, str]]]:
    """Returns (written, skipped, errors, no_data_combos).

    no_data_combos lists (pref_ja, program_name) pairs where adoption_count == 0
    AND status is matched_prefecture or other_prefecture (i.e. plausibly should
    have data but does not — useful for honesty audit).
    """
    if not db_path.exists():
        LOG.error("database not found: %s", db_path)
        raise SystemExit(1)
    if not (template_dir / "cross.html").exists():
        LOG.error("template not found: %s/cross.html", template_dir)
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    env = _build_env(template_dir)
    ctx = RenderContext(env=env)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    LOG.info("selecting top %d programs...", top_n)
    top_programs = select_top_programs(conn, top_n)
    LOG.info("selected %d programs", len(top_programs))

    written = 0
    skipped = 0
    errors = 0
    sitemap_entries: list[tuple[str, str, str, str]] = []
    no_data_combos: list[tuple[str, str]] = []

    pref_list = PREFECTURES
    if samples_only is not None:
        # Sample mode: 1 prefecture × samples_only programs (top of the list).
        pref_list = pref_list[:1]
        top_programs = top_programs[:samples_only]

    for pref_slug, pref_ja in pref_list:
        # Pre-build a small "related_in_pref" list so each page can recommend
        # other top-N crosspages within the same prefecture for internal
        # linking (max 6 items, exclude self).
        for row in top_programs:
            try:
                related = []
                for other in top_programs:
                    if other["unified_id"] == row["unified_id"]:
                        continue
                    other_status = classify_applicability(other, pref_ja)
                    # Only link to OTHER programs that ARE applicable in this pref
                    # (national, matched_prefecture, or municipality_in_pref).
                    # Skip other_prefecture so we never internally link to a page
                    # that says "対象外". Prefer matched + national mix.
                    if other_status == "other_prefecture":
                        continue
                    other_slug = slugify(
                        other["primary_name"] or "", other["unified_id"]
                    )
                    related.append(
                        {
                            "program_slug": other_slug,
                            "name": other["primary_name"],
                            "kind_ja": KIND_JA.get(
                                other.get("program_kind") or "subsidy", "公的支援制度"
                            ),
                            "amount_line": _amount_line(
                                other.get("amount_max_man_yen"),
                                other.get("amount_min_man_yen"),
                            ),
                        }
                    )
                    if len(related) >= 6:
                        break

                slug, html = render_pair(
                    row, pref_ja, pref_slug, ctx, domain, conn, related
                )

                # Honesty audit hook: track combos where pref-prog is plausible
                # but adoption_count is 0.
                status = classify_applicability(row, pref_ja)
                adoption_n = _adoption_count_in_pref(
                    conn, row["primary_name"] or "", pref_ja
                )
                if adoption_n == 0 and status == "matched_prefecture":
                    no_data_combos.append((pref_ja, row["primary_name"]))

                out_path = out_dir / pref_slug / f"{slug}.html"
                changed = _write_if_changed(out_path, html)
                if changed:
                    written += 1
                else:
                    skipped += 1

                lastmod = (
                    _normalize_iso_date(row.get("source_fetched_at"))
                    or _normalize_iso_date(row.get("updated_at"))
                    or _today_jst_iso()
                )
                tier = (row.get("tier") or "A").upper()
                sitemap_entries.append((pref_slug, slug, lastmod, tier))
            except Exception as exc:  # noqa: BLE001
                LOG.exception(
                    "render failed for pref=%s program=%s: %s",
                    pref_slug,
                    row.get("unified_id"),
                    exc,
                )
                errors += 1

    if sitemap_path is not None and sitemap_entries and samples_only is None:
        write_sitemap(sitemap_entries, sitemap_path, domain)

    return written, skipped, errors, no_data_combos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR), type=Path)
    p.add_argument(
        "--domain",
        default=os.environ.get("JPINTEL_DOMAIN", DEFAULT_DOMAIN),
    )
    p.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    p.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_SITEMAP,
        help="sitemap to (over)write; pass empty string to skip",
    )
    p.add_argument(
        "--samples",
        type=int,
        default=None,
        help="if set, generate first prefecture × N programs only",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sitemap_path = (
        args.sitemap if (args.sitemap and str(args.sitemap) != "") else None
    )
    written, skipped, errors, no_data = generate(
        db_path=args.db,
        out_dir=args.out,
        template_dir=args.template_dir,
        domain=args.domain,
        top_n=args.top,
        sitemap_path=sitemap_path,
        samples_only=args.samples,
    )
    LOG.info(
        "written=%d skipped=%d errors=%d no_data_matched_pref=%d",
        written,
        skipped,
        errors,
        len(no_data),
    )
    if no_data and args.verbose:
        for pref, name in no_data[:30]:
            LOG.debug("no-data combo: pref=%s program=%s", pref, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
