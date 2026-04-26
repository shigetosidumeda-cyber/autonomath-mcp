"""Vocabulary normalization at the API boundary.

Why this exists: LLM agents don't know our canonical forms. An agent that
tries ``prefecture="東京"`` or ``prefecture="Tokyo"`` today gets 0 rows, then
has to call ``enum_values`` and retry — 2-3 wasted tool calls per query. At
¥3/req metered, that's customer money being thrown away on retry loops.

The rule is: be generous on input, strict on output. We accept English,
Japanese, with/without suffix, case-insensitive, and map everything to the
single canonical form stored in the DB. Unknown values pass through unchanged
so the caller still gets an empty result set rather than a silent rewrite —
this matters for future values we haven't taught the alias map yet.

Canonical forms (what the DB actually holds):
  - ``authority_level`` → English lowercase: ``national`` / ``prefecture`` /
    ``municipality`` / ``financial``
  - ``prefecture`` → full-suffix kanji: ``東京都`` / ``北海道`` / ``全国``
  - ``industry_jsic`` → single upper-case letter: ``A``..``T`` (日本標準産業分類
    大分類)

Note: the ingest pipeline (src/jpintel_mcp/ingest/canonical.py) imports
_normalize_authority_level + _normalize_prefecture from this module and applies
them at INSERT time, so newly-ingested rows land canonical. The API-boundary
normalization here is the second line of defense for direct-callers and
historical rows that pre-date the ingest fix.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# authority_level
# ---------------------------------------------------------------------------
_AUTHORITY_LEVEL_ALIASES: dict[str, str] = {
    # --- English canonical (idempotent) ---
    "national": "national",
    "prefecture": "prefecture",
    "municipality": "municipality",
    "financial": "financial",
    # --- Japanese vocabulary (what the old docs & SDK examples taught users) ---
    "国": "national",
    "都道府県": "prefecture",
    "県": "prefecture",
    "都": "prefecture",
    "道": "prefecture",
    "府": "prefecture",
    "市区町村": "municipality",
    "市町村": "municipality",
    "市": "municipality",
    "区": "municipality",
    "町": "municipality",
    "村": "municipality",
    # "financial" = public finance corporations (公庫系).
    "公庫": "financial",
    "公的金融機関": "financial",
    "政府系金融機関": "financial",
}


def _normalize_authority_level(value: str | None) -> str | None:
    """Map a user-supplied authority_level to the canonical English form.

    Rules:
    - None / empty string -> None (filter is a no-op).
    - Exact canonical English -> returned unchanged.
    - Known JP alias -> English canonical.
    - Case-insensitive for ASCII (``NATIONAL``, ``National`` -> ``national``).
    - Unknown value -> returned verbatim (caller gets 0 rows, not a rewrite).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped in _AUTHORITY_LEVEL_ALIASES:
        return _AUTHORITY_LEVEL_ALIASES[stripped]
    lowered = stripped.lower()
    if lowered in _AUTHORITY_LEVEL_ALIASES:
        return _AUTHORITY_LEVEL_ALIASES[lowered]
    return stripped


# ---------------------------------------------------------------------------
# prefecture
#
# Canonical = full-suffix kanji ("東京都", not "東京", not "Tokyo"). The DB
# stores exactly this form on 100% of populated rows.
# ---------------------------------------------------------------------------

# Map: every tolerated input form (short kanji, romaji, with/without suffix) → canonical.
# Populated programmatically below to avoid 188 hand-entered lines.
_PREFECTURES_CANONICAL: tuple[tuple[str, str, str], ...] = (
    # (canonical_jp, short_jp, romaji_lower)
    ("北海道", "北海道", "hokkaido"),
    ("青森県", "青森", "aomori"),
    ("岩手県", "岩手", "iwate"),
    ("宮城県", "宮城", "miyagi"),
    ("秋田県", "秋田", "akita"),
    ("山形県", "山形", "yamagata"),
    ("福島県", "福島", "fukushima"),
    ("茨城県", "茨城", "ibaraki"),
    ("栃木県", "栃木", "tochigi"),
    ("群馬県", "群馬", "gunma"),
    ("埼玉県", "埼玉", "saitama"),
    ("千葉県", "千葉", "chiba"),
    ("東京都", "東京", "tokyo"),
    ("神奈川県", "神奈川", "kanagawa"),
    ("新潟県", "新潟", "niigata"),
    ("富山県", "富山", "toyama"),
    ("石川県", "石川", "ishikawa"),
    ("福井県", "福井", "fukui"),
    ("山梨県", "山梨", "yamanashi"),
    ("長野県", "長野", "nagano"),
    ("岐阜県", "岐阜", "gifu"),
    ("静岡県", "静岡", "shizuoka"),
    ("愛知県", "愛知", "aichi"),
    ("三重県", "三重", "mie"),
    ("滋賀県", "滋賀", "shiga"),
    ("京都府", "京都", "kyoto"),
    ("大阪府", "大阪", "osaka"),
    ("兵庫県", "兵庫", "hyogo"),
    ("奈良県", "奈良", "nara"),
    ("和歌山県", "和歌山", "wakayama"),
    ("鳥取県", "鳥取", "tottori"),
    ("島根県", "島根", "shimane"),
    ("岡山県", "岡山", "okayama"),
    ("広島県", "広島", "hiroshima"),
    ("山口県", "山口", "yamaguchi"),
    ("徳島県", "徳島", "tokushima"),
    ("香川県", "香川", "kagawa"),
    ("愛媛県", "愛媛", "ehime"),
    ("高知県", "高知", "kochi"),
    ("福岡県", "福岡", "fukuoka"),
    ("佐賀県", "佐賀", "saga"),
    ("長崎県", "長崎", "nagasaki"),
    ("熊本県", "熊本", "kumamoto"),
    ("大分県", "大分", "oita"),
    ("宮崎県", "宮崎", "miyazaki"),
    ("鹿児島県", "鹿児島", "kagoshima"),
    ("沖縄県", "沖縄", "okinawa"),
)


def _build_prefecture_aliases() -> dict[str, str]:
    m: dict[str, str] = {}
    for canonical, short, romaji in _PREFECTURES_CANONICAL:
        m[canonical] = canonical  # idempotent
        m[short] = canonical  # short form (drop suffix)
        m[romaji] = canonical  # romaji lower
    # "全国" is also canonical — used for nationwide programs
    m["全国"] = "全国"
    m["national"] = "全国"
    m["all"] = "全国"
    m["japan"] = "全国"
    return m


_PREFECTURE_ALIASES: dict[str, str] = _build_prefecture_aliases()


def _normalize_prefecture(value: str | None) -> str | None:
    """Map a user-supplied prefecture to canonical form ('東京都', not '東京'/'Tokyo').

    Rules:
    - None / empty -> None.
    - Canonical kanji ('東京都', '全国') -> returned unchanged.
    - Short kanji ('東京') -> full ('東京都').
    - Romaji ('tokyo', 'Tokyo', 'TOKYO') -> full kanji ('東京都').
    - Unknown -> returned verbatim (caller gets 0 rows, not a silent rewrite).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped in _PREFECTURE_ALIASES:
        return _PREFECTURE_ALIASES[stripped]
    lowered = stripped.lower()
    if lowered in _PREFECTURE_ALIASES:
        return _PREFECTURE_ALIASES[lowered]
    return stripped


def _is_known_prefecture(value: str | None) -> bool:
    """True iff _normalize_prefecture maps to a canonical '[pref]県/都/府/道' or '全国'.

    Used to surface a hint when the caller typed a typo ('Tokio', '東京府')
    instead of silently returning 0 rows under a no-op filter.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if stripped in _PREFECTURE_ALIASES:
        return True
    return stripped.lower() in _PREFECTURE_ALIASES


# ---------------------------------------------------------------------------
# industry_jsic (日本標準産業分類 大分類)
#
# Canonical = single uppercase letter A..T. Each letter is the 大分類 code
# from Japan Standard Industrial Classification (総務省). The DB stores the
# 大分類 code prefix, and longer forms (2-digit 中分類, 3-digit 小分類) are
# left-matched via LIKE in case_studies.py.
# ---------------------------------------------------------------------------

_JSIC_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    # (code, jp_name, en_name)
    ("A", "農業林業", "agriculture_forestry"),
    ("B", "漁業", "fisheries"),
    ("C", "鉱業採石業砂利採取業", "mining_quarrying"),
    ("D", "建設業", "construction"),
    ("E", "製造業", "manufacturing"),
    ("F", "電気ガス熱供給水道業", "utilities"),
    ("G", "情報通信業", "information_communications"),
    ("H", "運輸業郵便業", "transport_postal"),
    ("I", "卸売業小売業", "wholesale_retail"),
    ("J", "金融業保険業", "finance_insurance"),
    ("K", "不動産業物品賃貸業", "real_estate_leasing"),
    ("L", "学術研究専門技術サービス業", "research_professional"),
    ("M", "宿泊業飲食サービス業", "hospitality_food"),
    ("N", "生活関連サービス業娯楽業", "lifestyle_entertainment"),
    ("O", "教育学習支援業", "education"),
    ("P", "医療福祉", "healthcare_welfare"),
    ("Q", "複合サービス事業", "compound_services"),
    ("R", "サービス業他に分類されないもの", "other_services"),
    ("S", "公務", "public_service"),
    ("T", "分類不能の産業", "unclassified"),
)


def _build_jsic_aliases() -> dict[str, str]:
    m: dict[str, str] = {}
    # Common short Japanese aliases that users actually type.
    short_jp: dict[str, str] = {
        "農業": "A",
        "林業": "A",
        "漁業": "B",
        "鉱業": "C",
        "建設": "D",
        "建設業": "D",
        "製造": "E",
        "製造業": "E",
        "情報通信": "G",
        "IT": "G",
        "情報": "G",
        "ソフトウェア": "G",
        "運輸": "H",
        "卸売": "I",
        "小売": "I",
        "卸売業": "I",
        "小売業": "I",
        "金融": "J",
        "保険": "J",
        "不動産": "K",
        "学術": "L",
        "宿泊": "M",
        "飲食": "M",
        "飲食店": "M",
        "生活関連": "N",
        "娯楽": "N",
        "教育": "O",
        "医療": "P",
        "福祉": "P",
        "公務": "S",
    }
    for code, jp_name, en_name in _JSIC_CATEGORIES:
        m[code] = code  # idempotent upper
        m[jp_name] = code  # full JP name (no punctuation)
        m[en_name] = code  # English slug
    for k, v in short_jp.items():
        m[k] = v
    return m


_JSIC_ALIASES: dict[str, str] = _build_jsic_aliases()


def _normalize_industry_jsic(value: str | None) -> str | None:
    """Map a user-supplied industry_jsic to canonical single-letter code A..T.

    Rules:
    - None / empty -> None.
    - Already canonical letter ('E', 'a') -> uppercase letter ('E', 'A').
    - JP name ('製造業', '農業') -> letter code ('E', 'A').
    - EN slug ('manufacturing') -> letter code.
    - 2+ digit codes ('E29', '29') -> returned verbatim so LIKE-prefix in
      case_studies.py still works on 中分類 / 小分類 codes.
    - Unknown -> returned verbatim.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    # Single uppercase letter fast-path (already canonical).
    if len(stripped) == 1 and stripped.isalpha():
        return stripped.upper()
    # Case-sensitive lookup first (JP names have no case).
    if stripped in _JSIC_ALIASES:
        return _JSIC_ALIASES[stripped]
    lowered = stripped.lower()
    if lowered in _JSIC_ALIASES:
        return _JSIC_ALIASES[lowered]
    return stripped


__all__ = [
    "_normalize_authority_level",
    "_normalize_industry_jsic",
    "_normalize_prefecture",
]
