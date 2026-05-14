"""GET /v1/intel/citation_pack/{program_id} — markdown citation envelope.

Single-call composite that pulls **every primary-source citation surface
that mentions a program** and bundles them into a markdown (or json) pack
the customer LLM can quote directly into a 提案書 / 申請書 scaffold:

  1. **法令根拠** — laws joined via `program_law_refs`.
  2. **通達**       — NTA / ministerial 通達 from `nta_tsutatsu_index`
                       (autonomath.db) keyed by article reference + name match.
  3. **裁決事例**   — 国税不服審判所 裁決 from `nta_saiketsu` (autonomath.db).
  4. **判例**       — `court_decisions` (jpintel.db).
  5. **行政処分**   — `enforcement_cases` (jpintel.db).
  6. **採択事例**   — `am_adopted_company_features` summary + `adoption_records`
                       row for the named program.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call. Pure SQL across two SQLite files + Python markdown render.
* No silent rewriting of `source_url` — every citation surfaces the live
  URL exactly as stored.
* `compact_envelope` wrap delegates to ``attach_corpus_snapshot`` and
  ``attach_seal_to_body`` so the response is auditor-reproducible and the
  customer LLM can cite a single (snapshot_id, checksum) pair across the
  whole pack.
* Sensitive surface — §52 (税理士法) + §47条の2 (公認会計士法) +
  §1 (行政書士法) + §72 (弁護士法) fence injected via
  `_disclaimer` so business-planning use of the pack does not drift into
  regulated 助言 territory.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_citation_pack")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Disclaimers
# ---------------------------------------------------------------------------

# Default §52 / §47条の2 / §1 / §72 fence — injected on EVERY response so a
# downstream LLM cannot accidentally drop the legal envelope by re-rendering
# the markdown body.
_CITATION_PACK_DISCLAIMER = (
    "本 citation_pack は jpcite corpus (programs / program_law_refs / laws / "
    "nta_tsutatsu_index / nta_saiketsu / court_decisions / enforcement_cases / "
    "adoption_records) を一次資料 URL とともに 1 call で束ねた **検索結果** で、"
    "税理士法 §52 (税務代理) ・公認会計士法 §47条の2 (監査・意見表明) ・"
    "行政書士法 §1の2 (申請代理) ・弁護士法 §72 (法律事務) のいずれにも該当しません。"
    "業務判断は必ず一次資料 URL を直接確認のうえ、確定判断は資格を有する士業へ。"
)

# Augmented sensitive-territory addendum — appended when the program lives in
# 業法 (建設業法 / 宅建業法 / 食品衛生法 等) territory because the resulting
# pack is more likely to be re-quoted into a 申請書 directly. Heuristic
# detection: keyword match on the program's primary_name.
_BUSINESS_LAW_DISCLAIMER = (
    "当該 program は 業法 (建設業法 / 宅建業法 / 旅館業法 等) 領域に属する"
    "可能性があり、申請書面の起案・提出は業務独占業務のため、出力 markdown を"
    "そのまま申請書面として使用することは禁止 (行政書士法 §1の2)。"
)

# Trigger words for the augmented sensitive-territory addendum.
_BUSINESS_LAW_KEYWORDS: tuple[str, ...] = (
    "建設業",
    "宅建",
    "宅地建物",
    "旅館業",
    "風営",
    "古物",
    "酒類販売",
    "食品衛生",
    "薬機",
    "貸金業",
    "金融商品取引",
)


# ---------------------------------------------------------------------------
# Output schema metadata
# ---------------------------------------------------------------------------

CitationFormat = Literal["markdown", "json"]
CitationStyle = Literal["footnote", "inline", "harvard"]

_KIND_LABELS_JA: dict[str, str] = {
    "law": "法令根拠",
    "tsutatsu": "通達",
    "kessai": "裁決事例",
    "hanrei": "判例",
    "gyosei_shobun": "行政処分",
    "adoption": "採択事例",
}

# Source license attribution per citation kind.
_KIND_LICENSES: dict[str, str] = {
    "law": "CC-BY-4.0 (e-Gov)",
    "tsutatsu": "PDL-1.0 (NTA)",
    "kessai": "gov_standard (国税不服審判所)",
    "hanrei": "gov_standard (courts.go.jp)",
    "gyosei_shobun": "gov_standard",
    "adoption": "gov_standard",
}


# ---------------------------------------------------------------------------
# Snippet helpers
# ---------------------------------------------------------------------------

# Hard cap per snippet so the markdown body stays inside the customer LLM's
# context budget even when 30 citations stack up.
_SNIPPET_CHAR_CAP = 220


def _snippet(text: Any) -> str:
    """Trim a freeform string to ``_SNIPPET_CHAR_CAP`` chars + ellipsize."""
    if not isinstance(text, str) or not text:
        return ""
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) <= _SNIPPET_CHAR_CAP:
        return s
    return s[: _SNIPPET_CHAR_CAP - 1] + "…"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    for r in rows:
        try:
            if r["name"] == column:
                return True
        except (IndexError, KeyError, TypeError):
            try:
                if r[1] == column:
                    return True
            except (IndexError, KeyError, TypeError):
                continue
    return False


# ---------------------------------------------------------------------------
# Citation pull helpers (jpintel.db side)
# ---------------------------------------------------------------------------


def _resolve_program(conn: sqlite3.Connection, program_id: str) -> dict[str, Any] | None:
    """Return ``{unified_id, primary_name, source_url}`` for the program.

    Returns None when the unified_id is unknown — the caller surfaces a 404.
    """
    if not _table_exists(conn, "programs"):
        return None
    select_cols = ["unified_id", "primary_name"]
    if _column_exists(conn, "programs", "source_url"):
        select_cols.append("source_url")
    else:
        select_cols.append("NULL AS source_url")
    if _column_exists(conn, "programs", "official_url"):
        select_cols.append("official_url")
    else:
        select_cols.append("NULL AS official_url")
    sql = f"SELECT {', '.join(select_cols)} FROM programs WHERE unified_id = ? LIMIT 1"
    try:
        row = conn.execute(sql, (program_id,)).fetchone()
    except sqlite3.Error as exc:
        logger.warning("program lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return {
        "unified_id": row["unified_id"],
        "primary_name": row["primary_name"] or "",
        "source_url": row["source_url"] or row["official_url"],
    }


def _law_citations(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull law citations from ``program_law_refs`` joined to ``laws``."""
    if not _table_exists(conn, "program_law_refs"):
        return []
    if not _table_exists(conn, "laws"):
        return []
    try:
        rows = conn.execute(
            "SELECT plr.law_unified_id AS law_id, "
            "       plr.article_citation AS article_no, "
            "       plr.ref_kind AS ref_kind, "
            "       plr.source_url AS plr_url, "
            "       plr.fetched_at AS plr_fetched, "
            "       l.law_title AS title, "
            "       l.law_short_title AS short_title, "
            "       l.full_text_url AS full_text_url, "
            "       l.summary AS summary, "
            "       l.source_url AS law_source_url, "
            "       l.fetched_at AS law_fetched "
            "FROM program_law_refs plr "
            "JOIN laws l ON l.unified_id = plr.law_unified_id "
            "WHERE plr.program_unified_id = ? "
            "ORDER BY (plr.ref_kind = 'authority') DESC, "
            "         plr.confidence DESC, plr.article_citation ASC "
            "LIMIT ?",
            (program_id, int(limit)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("law citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        article_no = r["article_no"] or ""
        title = r["title"] or ""
        title_with_article = f"{title} {article_no}".strip() if article_no else title
        url = r["full_text_url"] or r["law_source_url"] or r["plr_url"]
        snippet = r["summary"] or article_no or r["ref_kind"] or ""
        out.append(
            {
                "kind": "law",
                "id": r["law_id"],
                "title": title_with_article,
                "url": url,
                "snippet": _snippet(snippet),
                "anchor_id": f"law-{r['law_id']}",
                "last_verified_at": r["law_fetched"] or r["plr_fetched"],
            }
        )
    return out


def _hanrei_citations(
    conn: sqlite3.Connection,
    *,
    program_name: str,
    related_law_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Pull court_decisions citations.

    Two filters OR-ed:
      * `court_decisions.related_law_ids_json` LIKE any of the program's
        applicable law IDs.
      * `key_ruling` / `case_name` LIKE one of the program-name kanji tokens.

    Empty corpus (court_decisions table missing or no rows) returns [].
    """
    if not _table_exists(conn, "court_decisions"):
        return []
    if limit <= 0:
        return []
    parts: list[str] = []
    params: list[Any] = []
    if related_law_ids:
        likes = ["related_law_ids_json LIKE ?" for _ in related_law_ids[:8]]
        parts.append("(" + " OR ".join(likes) + ")")
        params.extend([f"%{lid}%" for lid in related_law_ids[:8]])
    tokens = [t for t in re.findall(r"[一-龯]{2,}", program_name or "") if len(t) >= 2]
    if tokens:
        likes_kw = ["(case_name LIKE ? OR key_ruling LIKE ?)" for _ in tokens[:4]]
        parts.append("(" + " OR ".join(likes_kw) + ")")
        for t in tokens[:4]:
            params.extend([f"%{t}%", f"%{t}%"])
    if not parts:
        return []
    where = " OR ".join(parts)
    sql = (
        "SELECT unified_id AS han_id, case_name, key_ruling, "
        "       court, decision_date, source_url, full_text_url, "
        "       fetched_at, precedent_weight "
        f"FROM court_decisions WHERE {where} "
        "ORDER BY (precedent_weight = 'binding') DESC, "
        "         (precedent_weight = 'persuasive') DESC, "
        "         decision_date DESC "
        "LIMIT ?"
    )
    params.append(int(limit))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("hanrei citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        title_parts = [r["case_name"] or ""]
        if r["court"]:
            title_parts.append(f"({r['court']})")
        if r["decision_date"]:
            title_parts.append(r["decision_date"])
        out.append(
            {
                "kind": "hanrei",
                "id": r["han_id"],
                "title": " ".join(p for p in title_parts if p),
                "url": r["full_text_url"] or r["source_url"],
                "snippet": _snippet(r["key_ruling"]),
                "anchor_id": f"han-{r['han_id']}",
                "last_verified_at": r["fetched_at"],
            }
        )
    return out


def _gyosei_shobun_citations(
    conn: sqlite3.Connection,
    *,
    program_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull enforcement_cases (行政処分) keyed by program_name_hint."""
    if not _table_exists(conn, "enforcement_cases"):
        return []
    if limit <= 0 or not program_name:
        return []
    tokens = [t for t in re.findall(r"[一-龯]{2,}", program_name) if len(t) >= 2]
    name_likes = ["program_name_hint LIKE ?" for _ in tokens[:4]]
    if not name_likes:
        # Fall back to substring on the full primary_name.
        name_likes = ["program_name_hint LIKE ?"]
        tokens = [program_name]
    where = " OR ".join(name_likes)
    sql = (
        "SELECT case_id, event_type, program_name_hint, recipient_name, "
        "       reason_excerpt, legal_basis, source_url, source_title, "
        "       disclosed_date, amount_yen, fetched_at "
        f"FROM enforcement_cases WHERE {where} "
        "ORDER BY disclosed_date DESC LIMIT ?"
    )
    params: list[Any] = [f"%{t}%" for t in tokens[:4]]
    params.append(int(limit))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("gyosei_shobun citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        title_bits = [r["event_type"] or "行政処分"]
        if r["recipient_name"]:
            title_bits.append(r["recipient_name"])
        if r["disclosed_date"]:
            title_bits.append(r["disclosed_date"])
        snippet_src = r["reason_excerpt"] or r["legal_basis"] or r["source_title"]
        out.append(
            {
                "kind": "gyosei_shobun",
                "id": r["case_id"],
                "title": " ".join(b for b in title_bits if b),
                "url": r["source_url"],
                "snippet": _snippet(snippet_src),
                "anchor_id": f"gs-{r['case_id']}",
                "last_verified_at": r["fetched_at"],
                "amount_yen": r["amount_yen"],
            }
        )
    return out


def _adoption_citations(
    conn: sqlite3.Connection,
    *,
    program_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull adoption_records keyed by program_name_raw match.

    The canonical schema column is `program_name_raw` (the raw label as it
    appeared on the 採択 PDF / page); we LIKE-match the program's
    primary_name as a tolerant substring filter.
    """
    if not _table_exists(conn, "adoption_records"):
        return []
    if limit <= 0 or not program_name:
        return []
    name_col = (
        "program_name_raw"
        if _column_exists(conn, "adoption_records", "program_name_raw")
        else "program_name"
        if _column_exists(conn, "adoption_records", "program_name")
        else None
    )
    if name_col is None:
        return []
    sql = (
        "SELECT id, company_name_raw, houjin_bangou, prefecture, "
        "       industry_jsic_medium, amount_granted_yen, announced_at, "
        f"       source_url, {name_col} AS program_name "
        f"FROM adoption_records WHERE {name_col} = ? OR {name_col} LIKE ? "
        "ORDER BY announced_at DESC LIMIT ?"
    )
    try:
        rows = conn.execute(sql, (program_name, f"%{program_name}%", int(limit))).fetchall()
    except sqlite3.Error as exc:
        logger.warning("adoption citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        title_bits = [r["company_name_raw"] or ""]
        if r["prefecture"]:
            title_bits.append(f"({r['prefecture']})")
        if r["announced_at"]:
            title_bits.append(r["announced_at"])
        snippet_bits: list[str] = []
        if r["industry_jsic_medium"]:
            snippet_bits.append(f"JSIC {r['industry_jsic_medium']}")
        if r["amount_granted_yen"] is not None:
            with contextlib.suppress(TypeError, ValueError):
                snippet_bits.append(f"¥{int(r['amount_granted_yen']):,}")
        out.append(
            {
                "kind": "adoption",
                "id": str(r["id"]),
                "title": " ".join(b for b in title_bits if b).strip() or r["program_name"] or "",
                "url": r["source_url"],
                "snippet": " ".join(snippet_bits),
                "anchor_id": f"adp-{r['id']}",
                "last_verified_at": r["announced_at"],
                "houjin_bangou": r["houjin_bangou"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Citation pull helpers (autonomath.db side)
# ---------------------------------------------------------------------------


def _tsutatsu_citations(
    am_conn: sqlite3.Connection,
    *,
    related_law_ids: list[str],
    program_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull 通達 from nta_tsutatsu_index keyed by law canonical id + name."""
    if not _table_exists(am_conn, "nta_tsutatsu_index"):
        return []
    if limit <= 0:
        return []

    # The program_law_refs side gives us ``LAW-...`` ids; nta_tsutatsu_index
    # uses ``law:hojin-zei-tsutatsu`` style canonical ids. Bridge via name
    # tokens drawn from program_name.
    tokens = [t for t in re.findall(r"[一-龯]{2,}", program_name or "") if len(t) >= 2]
    if not tokens:
        return []
    likes = ["title LIKE ?" for _ in tokens[:6]]
    sql = (
        "SELECT id, code, law_canonical_id, article_number, title, "
        "       body_excerpt, source_url, last_amended, refreshed_at "
        "FROM nta_tsutatsu_index "
        f"WHERE {' OR '.join(likes)} "
        "ORDER BY refreshed_at DESC LIMIT ?"
    )
    params: list[Any] = [f"%{t}%" for t in tokens[:6]]
    params.append(int(limit))
    try:
        rows = am_conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("tsutatsu citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        title_bits = [r["code"] or ""]
        if r["title"]:
            title_bits.append(r["title"])
        out.append(
            {
                "kind": "tsutatsu",
                "id": r["code"] or str(r["id"]),
                "title": " — ".join(b for b in title_bits if b),
                "url": r["source_url"],
                "snippet": _snippet(r["body_excerpt"]),
                "anchor_id": f"ts-{r['id']}",
                "last_verified_at": r["last_amended"] or r["refreshed_at"],
            }
        )
    return out


def _kessai_citations(
    am_conn: sqlite3.Connection,
    *,
    program_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull 国税不服審判所 裁決事例 from nta_saiketsu by name token match."""
    if not _table_exists(am_conn, "nta_saiketsu"):
        return []
    if limit <= 0 or not program_name:
        return []
    tokens = [t for t in re.findall(r"[一-龯]{2,}", program_name) if len(t) >= 2]
    if not tokens:
        return []
    likes = ["(title LIKE ? OR decision_summary LIKE ?)" for _ in tokens[:4]]
    sql = (
        "SELECT id, volume_no, case_no, decision_date, tax_type, title, "
        "       decision_summary, source_url, ingested_at "
        "FROM nta_saiketsu "
        f"WHERE {' OR '.join(likes)} "
        "ORDER BY decision_date DESC LIMIT ?"
    )
    params: list[Any] = []
    for t in tokens[:4]:
        params.extend([f"%{t}%", f"%{t}%"])
    params.append(int(limit))
    try:
        rows = am_conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("kessai citations query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        title_bits = [
            f"裁決集 {r['volume_no']}-{r['case_no']}" if r["volume_no"] else "",
            r["title"] or "",
            r["tax_type"] or "",
            r["decision_date"] or "",
        ]
        out.append(
            {
                "kind": "kessai",
                "id": str(r["id"]),
                "title": " ".join(b for b in title_bits if b),
                "url": r["source_url"],
                "snippet": _snippet(r["decision_summary"]),
                "anchor_id": f"ke-{r['id']}",
                "last_verified_at": r["decision_date"] or r["ingested_at"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _render_inline_citation(idx: int, item: dict[str, Any], style: str) -> str:
    """Return the trailing citation marker per `citation_style`."""
    if style == "footnote":
        return f"^[{idx}]"
    if style == "harvard":
        last = item.get("last_verified_at") or ""
        year_m = re.search(r"\d{4}", last or "")
        year = year_m.group(0) if year_m else "n.d."
        title = item.get("title") or item.get("id") or ""
        # Strip trailing parens / dates from title for the inline citation.
        author = re.split(r"[、(（]", title, maxsplit=1)[0].strip() or title
        return f"({author}, {year})"
    # inline = full URL inline
    url = item.get("url") or ""
    if url:
        return f"[{url}]"
    return ""


def _render_markdown(
    *,
    program: dict[str, Any],
    grouped: dict[str, list[dict[str, Any]]],
    section_order: list[str],
    citation_style: str,
    sensitive_disclaimer: str | None,
    corpus_snapshot_id: str,
    license_summary: str,
) -> tuple[str, list[str], int]:
    """Render the markdown body. Returns ``(text, sections_used, citation_count)``."""
    lines: list[str] = []
    program_name = program.get("primary_name") or program.get("unified_id") or ""
    lines.append(f"# {program_name} 出典 pack")
    lines.append("")

    # Allocate stable global footnote indices first so multi-section citations
    # can refer back consistently.
    global_idx: dict[str, int] = {}
    citations_total: list[dict[str, Any]] = []
    for kind in section_order:
        for item in grouped.get(kind, []):
            citations_total.append(item)
            global_idx[item.get("anchor_id") or f"{kind}-{len(global_idx)}"] = len(citations_total)

    section_titles: list[str] = []
    for section_no, kind in enumerate(section_order, 1):
        items = grouped.get(kind) or []
        if not items:
            continue
        label = _KIND_LABELS_JA.get(kind, kind)
        section_titles.append(label)
        lines.append(f"## {section_no}. {label}")
        lines.append("")
        for item in items:
            anchor = item.get("anchor_id") or ""
            idx = global_idx.get(anchor, 0)
            title = item.get("title") or item.get("id") or "(無題)"
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            marker = _render_inline_citation(idx, item, citation_style) if idx else ""
            link_part = f"[{title}]({url})" if url else title
            if snippet:
                lines.append(f"- {link_part} — {snippet}{marker}")
            else:
                lines.append(f"- {link_part}{marker}")
        lines.append("")

    if not section_titles:
        lines.append("> 出典 が登録されていません。今後の corpus 拡充をお待ちください。")
        lines.append("")

    lines.append("---")
    if sensitive_disclaimer:
        lines.append(f"**法的 disclaimer**: {sensitive_disclaimer}")
    lines.append(f"**Generated at**: {corpus_snapshot_id}")
    lines.append(f"**Source license**: {license_summary}")

    # Footnote definition table for footnote style only — keeps the body
    # mountable into citation managers without re-parsing the inline marker.
    if citation_style == "footnote" and citations_total:
        lines.append("")
        lines.append("### 脚注 (footnote definitions)")
        for item in citations_total:
            anchor = item.get("anchor_id") or ""
            idx = global_idx.get(anchor, 0)
            url = item.get("url") or ""
            title = item.get("title") or item.get("id") or ""
            if url:
                lines.append(f"[^{idx}]: {title} {url}")
            else:
                lines.append(f"[^{idx}]: {title}")

    text = "\n".join(lines).rstrip() + "\n"
    return text, section_titles, len(citations_total)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def _is_business_law_program(program_name: str) -> bool:
    if not program_name:
        return False
    return any(kw in program_name for kw in _BUSINESS_LAW_KEYWORDS)


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Best-effort autonomath.db RO connection.

    Returns None when the DB file is missing / empty (e.g. fresh test
    fixture) so the caller can degrade to jpintel-only citations.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except Exception as exc:  # noqa: BLE001 — never let DB open break the call
        logger.debug("autonomath.db unavailable: %s", exc)
        return None


def _aggregate_license_summary(grouped: dict[str, list[dict[str, Any]]]) -> str:
    """Join the unique license labels of every section that has citations."""
    used: list[str] = []
    for kind, items in grouped.items():
        if not items:
            continue
        lic = _KIND_LICENSES.get(kind)
        if lic and lic not in used:
            used.append(lic)
    if not used:
        return "n/a (no citations)"
    return "; ".join(used)


@router.get(
    "/citation_pack/{program_id}",
    summary="Citation pack — 法令+通達+裁決+判例+行政処分+採択 1 call markdown bundle",
    description=(
        "Pulls every primary-source citation surface that mentions a program "
        "and bundles it as markdown (default) or json envelope. NO LLM call. "
        "Sensitive: §52 / §47条の2 / §1 / §72 fence injected on every "
        "response. ¥3 / call (`_billing_unit: 1`) regardless of citation count."
    ),
)
def get_citation_pack(
    program_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description="Program unified id (UNI-...).",
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    format: Annotated[  # noqa: A002 — public wire name for ?format= query param
        CitationFormat,
        Query(description="Output format. Default 'markdown'."),
    ] = "markdown",
    max_citations: Annotated[
        int,
        Query(
            ge=5,
            le=100,
            description="Hard cap on total citations across all sections.",
        ),
    ] = 30,
    include_adoptions: Annotated[
        bool,
        Query(description="Whether to include the 採択事例 section."),
    ] = True,
    citation_style: Annotated[
        CitationStyle,
        Query(description="Citation marker style for the markdown body."),
    ] = "footnote",
) -> JSONResponse:
    _t0 = time.perf_counter()

    pid = (program_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "program_id",
                "message": "program_id must be a non-empty unified_id (UNI-...).",
            },
        )

    program = _resolve_program(conn, pid)
    if program is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "program_not_found",
                "field": "program_id",
                "message": (
                    f"program_id={pid!r} not found in the programs table. "
                    "Verify the unified_id via /v1/programs/search first."
                ),
            },
        )

    program_name = program["primary_name"]

    # Distribute the max_citations budget across the 6 sections so a single
    # noisy section (e.g. 採択 with hundreds of rows) cannot starve law /
    # tsutatsu / kessai / hanrei. Floor each section at 1 hit so a niche
    # surface still surfaces if it has any data.
    sections_active = 6 if include_adoptions else 5
    base = max(1, max_citations // sections_active)
    per_section = {
        "law": base,
        "tsutatsu": base,
        "kessai": base,
        "hanrei": base,
        "gyosei_shobun": base,
        "adoption": base if include_adoptions else 0,
    }
    # Distribute the leftover budget back to law (most load-bearing) so we
    # still hit the requested cap when one section under-yields.
    leftover = max_citations - sum(per_section.values())
    if leftover > 0:
        per_section["law"] += leftover

    # ----- Pull citations ---------------------------------------------------
    laws = _law_citations(conn, program_id=pid, limit=per_section["law"])
    related_law_ids = [c["id"] for c in laws if c.get("id")]

    am_conn = _open_autonomath_ro()
    try:
        tsutatsu = (
            _tsutatsu_citations(
                am_conn,
                related_law_ids=related_law_ids,
                program_name=program_name,
                limit=per_section["tsutatsu"],
            )
            if am_conn is not None
            else []
        )
        kessai = (
            _kessai_citations(am_conn, program_name=program_name, limit=per_section["kessai"])
            if am_conn is not None
            else []
        )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    hanrei = _hanrei_citations(
        conn,
        program_name=program_name,
        related_law_ids=related_law_ids,
        limit=per_section["hanrei"],
    )
    gyosei = _gyosei_shobun_citations(
        conn, program_name=program_name, limit=per_section["gyosei_shobun"]
    )
    adoptions = (
        _adoption_citations(conn, program_name=program_name, limit=per_section["adoption"])
        if include_adoptions
        else []
    )

    grouped: dict[str, list[dict[str, Any]]] = {
        "law": laws,
        "tsutatsu": tsutatsu,
        "kessai": kessai,
        "hanrei": hanrei,
        "gyosei_shobun": gyosei,
        "adoption": adoptions,
    }

    # Hard-cap the total — preserve section ordering when trimming so the
    # markdown ordering never depends on rendering order.
    section_order = [
        "law",
        "tsutatsu",
        "kessai",
        "hanrei",
        "gyosei_shobun",
        "adoption",
    ]
    flat: list[tuple[str, dict[str, Any]]] = []
    for kind in section_order:
        for item in grouped[kind]:
            flat.append((kind, item))
    if len(flat) > max_citations:
        flat = flat[:max_citations]
        grouped = {kind: [] for kind in section_order}
        for kind, item in flat:
            grouped[kind].append(item)

    # ----- Build sensitive disclaimer envelope ------------------------------
    sensitive_disclaimer: str | None = None
    if _is_business_law_program(program_name):
        sensitive_disclaimer = _BUSINESS_LAW_DISCLAIMER

    license_summary = _aggregate_license_summary(grouped)

    # Pre-compute the snapshot id so the markdown body can quote it.
    body: dict[str, Any] = {}
    body = attach_corpus_snapshot(body, conn)
    snapshot_id = body.get("corpus_snapshot_id") or "unknown"

    # ----- Render output ----------------------------------------------------
    if format == "markdown":
        markdown_text, sections_used, citation_count = _render_markdown(
            program=program,
            grouped=grouped,
            section_order=section_order,
            citation_style=citation_style,
            sensitive_disclaimer=sensitive_disclaimer,
            corpus_snapshot_id=snapshot_id,
            license_summary=license_summary,
        )
        body["markdown_text"] = markdown_text
        body["byte_size"] = len(markdown_text.encode("utf-8"))
        body["citation_count"] = citation_count
        body["sections"] = sections_used
    else:
        json_citations: list[dict[str, Any]] = []
        for kind in section_order:
            for item in grouped[kind]:
                json_citations.append(
                    {
                        "kind": kind,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "snippet": item.get("snippet"),
                        "anchor_id": item.get("anchor_id"),
                        "last_verified_at": item.get("last_verified_at"),
                    }
                )
        body["citations"] = json_citations
        body["citation_count"] = len(json_citations)
        body["sections"] = [_KIND_LABELS_JA.get(k, k) for k in section_order if grouped.get(k)]

    body["program"] = {
        "program_id": program["unified_id"],
        "primary_name": program["primary_name"],
        "source_url": program["source_url"],
    }
    body["attribution"] = {
        "license": license_summary,
        "source_disclaimer": (
            "出典 URL は一次資料 (e-Gov 法令検索 / 国税庁 / 国税不服審判所 / "
            "courts.go.jp / 各省庁交付決定公表) を直接指す。再配布時は出典 URL "
            "とライセンス表示を保持してください。"
        ),
        "sensitive_disclaimer": sensitive_disclaimer,
    }
    body["_disclaimer"] = _CITATION_PACK_DISCLAIMER
    body["_billing_unit"] = 1
    body["citation_style"] = citation_style
    body["format"] = format
    body["include_adoptions"] = include_adoptions
    body["max_citations"] = max_citations

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.citation_pack",
        latency_ms=latency_ms,
        result_count=int(body.get("citation_count") or 0),
        params={
            "program_id": pid,
            "format": format,
            "max_citations": max_citations,
            "include_adoptions": include_adoptions,
            "citation_style": citation_style,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.citation_pack",
        request_params={
            "program_id": pid,
            "format": format,
            "max_citations": max_citations,
            "include_adoptions": include_adoptions,
            "citation_style": citation_style,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body)


__all__ = ["router"]
