"""Lane M1 upstream — Japanese government PDF → KG triples extractor.

Pure-Python, deterministic NER + relation harvest over Japanese
government PDF text (Textract OCR output or any other plain-text
source). Zero LLM inference — only regex + dictionary lookups.

Design contract
---------------
The Textract OCR pipeline that drains the 5K-PDF corpus in
``s3://jpcite-credit-textract-apse1-202605/out/`` produces line-block
text whose Japanese-character recall is unreliable (the AnalyzeDocument
TABLES+FORMS API has historically dropped CJK characters on
graphics-heavy slide decks). Empirically the most resilient signals
are:

* 13-digit ``houjin_bangou`` — perfectly preserved in OCR because
  digits do not collide with CJK glyph rendering.
* ISO / 西暦 dates (YYYY/MM/DD / YYYY-MM-DD / YYYY年M月D日 — when 年/月
  /日 survive).
* HTTP / HTTPS URLs.
* Amount-like digit clusters (1,000円 / 100万円 / 5億円 — only when
  the trailing unit char survives).
* 〒-prefixed postal codes (7-digit form).

For CJK-rich blocks (case studies, e-Gov 法令データ exports) we ALSO
fire the dictionary-based program / law / authority extractors used by
the M2 case lane — they are best-effort additions and disabled by
default (``cjk_dict=False``) to keep precision high on noisy input.

Entity output schema
--------------------
Each entity is a dict with::

    {
      "kind": "houjin" | "date" | "url" | "amount" |
              "postal_code" | "program" | "law" | "authority",
      "surface": <verbatim string>,
      "confidence": <0..1>,
      "page": <int | None>,
      "offset": <int>,
    }

Relations follow the canonical ``am_relation`` schema with
``relation_type`` drawn from the
:data:`scripts.etl.harvest_implicit_relations._CANONICAL_RELATIONS`
frozenset to keep them visible to graph_traverse.

Pure & idempotent
-----------------
* No file / network I/O — caller passes text in.
* Same input → identical entity ordering (no random / time-dependent
  sort).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionResult",
    "extract_entities",
    "extract_relations",
    "extract_kg",
]


# ---- Regex catalogue --------------------------------------------------------

# 13-digit houjin_bangou — the canonical jpcite corporate canonical id
# is "houjin:<13>". The regex requires word boundaries (or non-digit
# neighbours) on both sides to avoid grabbing fragments of longer
# numeric strings.
HOUJIN_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(\d{13})(?!\d)")

# ISO date — 2024-05-27, 2024/5/27, 2024.5.27.
ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(20\d{2})[/\-.](0?[1-9]|1[0-2])[/\-.](0?[1-9]|[12]\d|3[01])\b"
)

# Japanese-form date — 2024年5月27日 (年 / 月 / 日 may survive OCR even
# when content kanji do not).
JP_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"(20\d{2})年\s*(0?[1-9]|1[0-2])月\s*(0?[1-9]|[12]\d|3[01])日"
)

# 令和 / 平成 wareki dates — best-effort; many will not OCR.
REIWA_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"令和\s*([\d元]+)\s*年\s*([\d]+)\s*月\s*([\d]+)\s*日"
)

# HTTP(S) URL — bounded to non-whitespace, drop trailing punctuation.
URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s<>\)\]　、。]+")

# Amount regex — copied from the M2 case extractor for cross-lane
# consistency. Re-implemented inline so this module has no dependency
# on the ``scripts/`` package layout.
AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<unit>億円|億|百万円|百万|千万円|千万|万円|万|円)"
)
_UNIT_SCALE: Final[dict[str, int]] = {
    "億円": 100_000_000,
    "億": 100_000_000,
    "百万円": 1_000_000,
    "百万": 1_000_000,
    "千万円": 10_000_000,
    "千万": 10_000_000,
    "万円": 10_000,
    "万": 10_000,
    "円": 1,
}

# 7-digit postal code — must have an explicit 〒 prefix OR an explicit
# 3-4 hyphenated form with a non-digit boundary on the left (so that
# 13-digit houjin_bangou tails do not register as postal codes).
POSTAL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:〒\s*(\d{3})\s*-?\s*(\d{4})|(?<!\d)(\d{3})-(\d{4})(?!\d))"
)

# CJK-dict patterns. These are best-effort — only fire when Japanese
# characters survived OCR. Patterns kept short / specific to keep false-
# positive risk low on garbled input.
PROGRAM_RE: Final[re.Pattern[str]] = re.compile(
    r"[一-鿿゠-ヿA-Za-z0-9・]{2,30}"
    r"(?:補助金|助成金|支援事業|給付金|奨励金|交付金|無利子融資|利子補給)"
)
LAW_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:[一-鿿]{2,20}法|[一-鿿]{2,20}令|[一-鿿]{2,20}省令|[一-鿿]{2,20}条例)"
    r"(?:第[0-9一二三四五六七八九十百千]+条)?"
)
AUTHORITY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:経済産業省|厚生労働省|文部科学省|総務省|農林水産省|国土交通省|"
    r"環境省|法務省|外務省|防衛省|内閣府|金融庁|消費者庁|デジタル庁|"
    r"国税庁|文化庁|気象庁|警察庁|林野庁|水産庁|特許庁|中小企業庁|"
    r"[一-鿿]{2,8}(?:県|府|都|道)|[一-鿿]{2,12}(?:市|区|町|村)役所)"
)

# Canonical relation_types — must match
# scripts/etl/harvest_implicit_relations._CANONICAL_RELATIONS to remain
# visible to graph_traverse.
_RELATION_HAS_AUTHORITY: Final[str] = "has_authority"
_RELATION_REFERENCES_LAW: Final[str] = "references_law"
_RELATION_APPLIES_TO_REGION: Final[str] = "applies_to_region"
_RELATION_RELATED: Final[str] = "related"

# Confidence calibration (regex-based, no model probability available).
_CONF_HOUJIN: Final[float] = 0.95
_CONF_ISO_DATE: Final[float] = 0.95
_CONF_JP_DATE: Final[float] = 0.90
_CONF_REIWA_DATE: Final[float] = 0.85
_CONF_URL: Final[float] = 0.95
_CONF_AMOUNT: Final[float] = 0.85
_CONF_POSTAL: Final[float] = 0.90
_CONF_PROGRAM: Final[float] = 0.70
_CONF_LAW: Final[float] = 0.70
_CONF_AUTHORITY: Final[float] = 0.80

# Surface length sanity bounds.
_PROGRAM_MIN_LEN: Final[int] = 4
_PROGRAM_MAX_LEN: Final[int] = 40
_LAW_MIN_LEN: Final[int] = 3
_LAW_MAX_LEN: Final[int] = 40
_AUTHORITY_MIN_LEN: Final[int] = 2
_AUTHORITY_MAX_LEN: Final[int] = 24

# Yen ceiling — single-document amount above 1 trillion is OCR noise.
_AMOUNT_CEIL_YEN: Final[int] = 1_000_000_000_000


# ---- Result types -----------------------------------------------------------


@dataclass(frozen=True)
class ExtractedEntity:
    """One extracted entity row.

    Attributes
    ----------
    kind:
        One of ``houjin`` / ``date`` / ``url`` / ``amount`` /
        ``postal_code`` / ``program`` / ``law`` / ``authority``.
    surface:
        Verbatim matched substring (post any normalisation).
    confidence:
        Pre-calibrated regex confidence in 0..1.
    page:
        1-indexed page number when known, else None.
    offset:
        0-indexed character offset within the per-page text.
    value:
        Optional normalised value — e.g. amount in yen as int, date as
        ISO ``YYYY-MM-DD`` string, houjin as the 13-digit core. None
        when no normalisation applies.
    """

    kind: str
    surface: str
    confidence: float
    page: int | None
    offset: int
    value: str | int | None = None


@dataclass(frozen=True)
class ExtractedRelation:
    """One extracted relation edge."""

    source_surface: str
    source_kind: str
    target_surface: str
    target_kind: str
    relation_type: str
    confidence: float
    page: int | None


@dataclass(frozen=True)
class ExtractionResult:
    """Aggregate output of :func:`extract_kg`."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    page_count: int = 0
    char_count: int = 0


# ---- Public API -------------------------------------------------------------


def _wareki_to_seireki_reiwa(year_token: str) -> int | None:
    """Return 西暦 year for a Reiwa year token, or None on parse failure."""
    s = year_token.replace("元", "1")
    try:
        return 2018 + int(s)
    except ValueError:
        return None


def extract_entities(
    text: str,
    *,
    page: int | None = None,
    cjk_dict: bool = False,
) -> list[ExtractedEntity]:
    """Run all regex extractors against ``text``.

    Parameters
    ----------
    text:
        Source text to scan. May contain ASCII-only OCR fragments or
        full Japanese sentences — the extractor degrades gracefully.
    page:
        Optional 1-indexed page number to stamp onto each result.
    cjk_dict:
        Enable the CJK-dictionary extractors (program / law /
        authority). Default False because the dictionary patterns are
        higher-recall but lower-precision on garbled OCR — the bulk M1
        extractor toggles this on per-page when CJK char density passes
        a floor threshold.

    Returns
    -------
    list[ExtractedEntity]
        Extracted rows in input-offset order (stable across calls).
    """
    if not text:
        return []

    out: list[ExtractedEntity] = []

    for m in HOUJIN_RE.finditer(text):
        h = m.group(1)
        if not _is_plausible_houjin(h):
            continue
        out.append(
            ExtractedEntity(
                kind="houjin",
                surface=h,
                confidence=_CONF_HOUJIN,
                page=page,
                offset=m.start(),
                value=h,
            )
        )

    for m in ISO_DATE_RE.finditer(text):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        iso = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        out.append(
            ExtractedEntity(
                kind="date",
                surface=m.group(0),
                confidence=_CONF_ISO_DATE,
                page=page,
                offset=m.start(),
                value=iso,
            )
        )

    for m in JP_DATE_RE.finditer(text):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        iso = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        out.append(
            ExtractedEntity(
                kind="date",
                surface=m.group(0),
                confidence=_CONF_JP_DATE,
                page=page,
                offset=m.start(),
                value=iso,
            )
        )

    for m in REIWA_DATE_RE.finditer(text):
        year = _wareki_to_seireki_reiwa(m.group(1))
        if year is None:
            continue
        try:
            mo = int(m.group(2))
            d = int(m.group(3))
        except ValueError:
            continue
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        iso = f"{year:04d}-{mo:02d}-{d:02d}"
        out.append(
            ExtractedEntity(
                kind="date",
                surface=m.group(0),
                confidence=_CONF_REIWA_DATE,
                page=page,
                offset=m.start(),
                value=iso,
            )
        )

    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:")
        if len(url) < 12:  # too short to be useful
            continue
        out.append(
            ExtractedEntity(
                kind="url",
                surface=url,
                confidence=_CONF_URL,
                page=page,
                offset=m.start(),
                value=url,
            )
        )

    for m in AMOUNT_RE.finditer(text):
        raw = m.group("num").replace(",", "")
        try:
            num = float(raw)
        except ValueError:
            continue
        unit = m.group("unit")
        scale = _UNIT_SCALE.get(unit, 0)
        if scale == 0:
            continue
        yen = int(num * scale)
        if yen <= 0 or yen > _AMOUNT_CEIL_YEN:
            continue
        out.append(
            ExtractedEntity(
                kind="amount",
                surface=m.group(0),
                confidence=_CONF_AMOUNT,
                page=page,
                offset=m.start(),
                value=yen,
            )
        )

    for m in POSTAL_RE.finditer(text):
        # POSTAL_RE has two alternation arms — pick whichever set fired.
        a = m.group(1) or m.group(3)
        b = m.group(2) or m.group(4)
        if not a or not b:
            continue
        out.append(
            ExtractedEntity(
                kind="postal_code",
                surface=m.group(0),
                confidence=_CONF_POSTAL,
                page=page,
                offset=m.start(),
                value=f"{a}-{b}",
            )
        )

    if cjk_dict:
        for m in PROGRAM_RE.finditer(text):
            s = m.group(0).strip()
            if not _PROGRAM_MIN_LEN <= len(s) <= _PROGRAM_MAX_LEN:
                continue
            out.append(
                ExtractedEntity(
                    kind="program",
                    surface=s,
                    confidence=_CONF_PROGRAM,
                    page=page,
                    offset=m.start(),
                    value=None,
                )
            )
        for m in LAW_RE.finditer(text):
            s = m.group(0).strip()
            if not _LAW_MIN_LEN <= len(s) <= _LAW_MAX_LEN:
                continue
            out.append(
                ExtractedEntity(
                    kind="law",
                    surface=s,
                    confidence=_CONF_LAW,
                    page=page,
                    offset=m.start(),
                    value=None,
                )
            )
        for m in AUTHORITY_RE.finditer(text):
            s = m.group(0).strip()
            if not _AUTHORITY_MIN_LEN <= len(s) <= _AUTHORITY_MAX_LEN:
                continue
            out.append(
                ExtractedEntity(
                    kind="authority",
                    surface=s,
                    confidence=_CONF_AUTHORITY,
                    page=page,
                    offset=m.start(),
                    value=None,
                )
            )

    out.sort(key=lambda e: (e.page or 0, e.offset))
    return out


def extract_relations(entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
    """Harvest co-occurrence relations within the same page.

    Heuristic — for every page bucket, emit:

    * (program × authority) → has_authority
    * (program × law)       → references_law
    * (program × houjin)    → related
    * (law × authority)     → has_authority
    * (houjin × authority)  → related (low conf — for filing-recipient
      surfaces in 認定申請 PDFs).

    Confidence is the min of the two surface confidences scaled by
    0.75 (loose co-occurrence) and floored at 0.4.

    Returns
    -------
    list[ExtractedRelation]
        Stable input-order relations.
    """
    rels: list[ExtractedRelation] = []
    by_page: dict[int | None, dict[str, list[ExtractedEntity]]] = {}
    for e in entities:
        by_page.setdefault(e.page, {}).setdefault(e.kind, []).append(e)

    for page, kinds in by_page.items():
        progs = kinds.get("program", [])
        auths = kinds.get("authority", [])
        laws = kinds.get("law", [])
        houjins = kinds.get("houjin", [])

        rels.extend(_pair_relations(progs, auths, _RELATION_HAS_AUTHORITY, page, 0.75))
        rels.extend(_pair_relations(progs, laws, _RELATION_REFERENCES_LAW, page, 0.75))
        rels.extend(_pair_relations(progs, houjins, _RELATION_RELATED, page, 0.70))
        rels.extend(_pair_relations(laws, auths, _RELATION_HAS_AUTHORITY, page, 0.70))
        rels.extend(_pair_relations(houjins, auths, _RELATION_RELATED, page, 0.55))

    return rels


def extract_kg(
    text: str,
    *,
    page: int | None = None,
    cjk_dict: bool = False,
) -> ExtractionResult:
    """Run :func:`extract_entities` then :func:`extract_relations`.

    Parameters
    ----------
    text:
        Source text.
    page:
        Optional 1-indexed page number.
    cjk_dict:
        Enable CJK dictionary patterns (default False — see
        :func:`extract_entities`).

    Returns
    -------
    ExtractionResult
        Aggregate result; entity / relation lists are stable across
        identical input.
    """
    entities = extract_entities(text, page=page, cjk_dict=cjk_dict)
    relations = extract_relations(entities)
    return ExtractionResult(
        entities=entities,
        relations=relations,
        page_count=1 if page is not None else 0,
        char_count=len(text),
    )


# ---- Helpers ---------------------------------------------------------------


def _is_plausible_houjin(h: str) -> bool:
    """Reject obvious noise (all-zero / all-same-digit / phone-like)."""
    if not h or len(h) != 13 or not h.isdigit():
        return False
    if len(set(h)) <= 2:
        return False
    # 9xxxxx phone-like leading; allow only valid prefixes 1..9 — Japanese
    # houjin_bangou always start with 1-9 (check digit can be 0..9). The
    # National Tax Agency spec dedicates leading digit to check-digit
    # parity but the practical sanity check is non-zero leading digit.
    return h[0] != "0"


_MAX_PAIR_FANOUT: Final[int] = 5


def _pair_relations(
    sources: list[ExtractedEntity],
    targets: list[ExtractedEntity],
    relation_type: str,
    page: int | None,
    factor: float,
) -> list[ExtractedRelation]:
    """Emit cartesian-product relations capped at MAX_PAIR_FANOUT each side."""
    if not sources or not targets:
        return []
    src_t = sources[:_MAX_PAIR_FANOUT]
    tgt_t = targets[:_MAX_PAIR_FANOUT]
    out: list[ExtractedRelation] = []
    for s in src_t:
        for t in tgt_t:
            conf = max(0.4, min(s.confidence, t.confidence) * factor)
            out.append(
                ExtractedRelation(
                    source_surface=s.surface,
                    source_kind=s.kind,
                    target_surface=t.surface,
                    target_kind=t.kind,
                    relation_type=relation_type,
                    confidence=round(conf, 3),
                    page=page,
                )
            )
    return out


def cjk_char_ratio(text: str) -> float:
    """Return the ratio of CJK / kana characters in ``text``.

    Used by the bulk extractor to decide whether to enable the
    :func:`extract_entities` ``cjk_dict`` toggle on a given Textract
    output: garbled OCR with <0.05 CJK density is regex-only.
    """
    if not text:
        return 0.0
    cjk = 0
    for c in text:
        if "぀" <= c <= "ヿ" or "一" <= c <= "鿿":
            cjk += 1
    return cjk / len(text)


def total_entities(result: ExtractionResult) -> dict[str, int]:
    """Return per-kind entity counts for telemetry / unit tests."""
    counts: dict[str, int] = {}
    for e in result.entities:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    return counts


def total_relations(result: ExtractionResult) -> dict[str, int]:
    """Return per-type relation counts for telemetry / unit tests."""
    counts: dict[str, int] = {}
    for r in result.relations:
        counts[r.relation_type] = counts.get(r.relation_type, 0) + 1
    return counts
