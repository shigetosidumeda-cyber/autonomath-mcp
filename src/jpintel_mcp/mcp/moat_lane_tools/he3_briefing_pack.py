"""Moat Heavy-Output Endpoint HE-3 — agent_briefing_pack.

Returns a single structured "briefing pack" tuned for direct injection into
an agent's context window. Goal: turn a free-form ``topic`` + a 5-segment
``target_segment`` (税理士 / 会計士 / 中小経営者 / AX_engineer / FDE) into a
multi-section bundle that contains the regulated-domain context, current
法令 / 通達 verbatim, judgment summaries (top 3), practical guidance,
common pitfalls, next-step recommendations, applicable N1 templates, the
related N4 filing windows, and the canonical 5-act disclaimer envelope —
all in three parallel output formats (Claude XML / OpenAI JSON / Markdown).

The pack is deliberately heavy because the trade is "1 ¥3/req tool call
inflates the agent context once, then collapses 3-5 turns of follow-up
into 1-2". See ``docs/_internal/MOAT_HE3_BRIEFING_PACK_2026_05_17.md``
for the cost-reduction model.

Hard constraints (CLAUDE.md)
----------------------------

* NO LLM inference. Pure SQLite + filesystem + Python string composition.
* 4 ¥3/billable units per call = ¥12, Pricing V3 Tier C heavy endpoint (2026-05-17).
* Every response carries the canonical §52 / §47条の2 / §72 / §1 / §3 +
  社労士法 disclaimer envelope.
* Read-only access to ``autonomath.db`` (URI ``mode=ro``).
* Pure-Python tokenizer (cl100k-style heuristic) — no external network
  call, no tiktoken dependency (tiktoken is not installed in production).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he3_briefing_pack")

_LANE_ID = "HE3"
_SCHEMA_VERSION = "moat.he3.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.he3_briefing_pack"

# Canonical segments accepted by the pack. Mirrors the 士業 segments used by
# N1 / N8 plus two AX-economy segments (AX_engineer / FDE).
_SEGMENT_PATTERN = r"^(税理士|会計士|中小経営者|AX_engineer|FDE)$"
_SEGMENTS_JA: dict[str, str] = {
    "税理士": "税理士",
    "会計士": "会計士",
    "中小経営者": "中小経営者",
    "AX_engineer": "AX エンジニア",
    "FDE": "FDE (Forward Deployed Engineer)",
}

# Per-segment regulated-act footer. Keeps the disclaimer scoped per segment
# so AX_engineer / FDE responses don't surface the 士業 envelope verbatim
# but still carry the canonical 5-act DISCLAIMER for fail-safe.
_SEGMENT_ACTS: dict[str, tuple[str, ...]] = {
    "税理士": ("税理士法 §52", "§1 行政書士法", "§3 司法書士法"),
    "会計士": ("公認会計士法 §47条の2", "税理士法 §52"),
    "中小経営者": ("税理士法 §52", "弁護士法 §72"),
    "AX_engineer": ("Anthropic Acceptable Use Policy",),
    "FDE": ("Anthropic Acceptable Use Policy", "顧客 SOW"),
}

_FORMAT_PATTERN = r"^(claude_xml|openai_json|markdown_doc)$"

# Token-budget → depth_level mapping. depth_level controls how much of each
# section we surface (e.g. number of judgments, number of N1 templates,
# number of N4 windows).
_DEPTH_TABLE: list[tuple[int, int]] = [
    (1500, 1),
    (3500, 2),
    (8000, 3),
    (14000, 4),
    (24000, 5),
]


# ---------------------------------------------------------------------------
# Token counter (no tiktoken dependency)
# ---------------------------------------------------------------------------


_TOKEN_RX = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Estimate token count for ``text`` without depending on tiktoken.

    Uses an OSS cl100k-style heuristic: ~4 chars / token for ASCII-heavy
    content, ~1.5 chars / token for CJK-heavy content. The estimator picks
    a blended factor based on the CJK ratio so mixed-language strings come
    out in the right ball park (±20% of tiktoken's own count in practice).
    """
    if not text:
        return 0
    n_chars = len(text)
    cjk = sum(1 for ch in text if "　" <= ch <= "鿿" or "＀" <= ch <= "￯")
    cjk_ratio = cjk / max(n_chars, 1)
    # Chars-per-token: 1.5 for full CJK, 4.0 for full ASCII, linear blend.
    chars_per_token = 4.0 - (4.0 - 1.5) * cjk_ratio
    return max(1, int(round(n_chars / chars_per_token)))


def depth_from_budget(token_budget: int) -> int:
    """Map a token budget to an integer depth level in [1, 5]."""
    if token_budget <= 0:
        return 1
    for ceiling, depth in _DEPTH_TABLE:
        if token_budget <= ceiling:
            return depth
    return 5


# ---------------------------------------------------------------------------
# DB plumbing
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # moat_lane_tools/ -> mcp/ -> jpintel_mcp/ -> src/ -> repo root
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.debug("HE3 autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Section builders — pure SQLite / static composition, no LLM inference
# ---------------------------------------------------------------------------


def _safe_like_token(topic: str) -> str:
    """Sanitize a topic string for a LIKE query (escape % and _)."""
    return topic.replace("%", "\\%").replace("_", "\\_")


def _build_context(topic: str, target_segment: str, depth: int) -> str:
    label = _SEGMENTS_JA.get(target_segment, target_segment)
    acts = "・".join(_SEGMENT_ACTS.get(target_segment, ()))
    body = (
        f"対象トピック: {topic}\n"
        f"対象セグメント: {label}\n"
        f"depth_level: {depth} / 5\n"
        f"適用業法: {acts}\n"
        "本 briefing pack は agent context window への 1-shot 注入を目的に組成しています。"
        "確定判断は士業へ、primary source 確認必須。"
    )
    return body


def _build_current_law(
    conn: sqlite3.Connection | None,
    topic: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Pull verbatim 法令 articles for ``topic`` via FTS or LIKE."""
    if conn is None or not _table_present(conn, "am_law_article"):
        return ("(autonomath.db / am_law_article unavailable)", [])
    rows: list[sqlite3.Row] = []
    like = f"%{_safe_like_token(topic)}%"
    limit = min(2 + depth, 10)
    try:
        cur = conn.execute(
            (
                "SELECT law_canonical_id, article_id, article_number, article_title, "
                "       body, source_url "
                "  FROM am_law_article "
                " WHERE (article_title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') "
                "   AND body IS NOT NULL AND length(body) >= 16 "
                " ORDER BY length(body) DESC "
                " LIMIT ?"
            ),
            (like, like, limit),
        )
        rows = list(cur.fetchall())
    except sqlite3.Error as exc:
        logger.debug("HE3 current_law query failed: %s", exc)
        return (f"(law lookup failed: {exc})", [])
    if not rows:
        return ("(関連 法令 verbatim 一致 0 件)", [])
    chunks: list[str] = []
    structured: list[dict[str, Any]] = []
    body_cap = 280 if depth <= 2 else 600
    for row in rows:
        body = (row["body"] or "")[:body_cap]
        title = row["article_title"] or row["law_canonical_id"]
        article_no = row["article_number"] or ""
        url = row["source_url"] or ""
        chunks.append(f"[{title} {article_no}] {body}")
        structured.append(
            {
                "law_canonical_id": row["law_canonical_id"],
                "article_id": row["article_id"],
                "article_number": article_no,
                "article_title": title,
                "body_excerpt": body,
                "source_url": url,
            }
        )
    return ("\n\n".join(chunks), structured)


def _build_tsutatsu(
    conn: sqlite3.Connection | None,
    topic: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Pull verbatim 通達 entries via am_law_article on -tsutatsu canonical ids."""
    if conn is None or not _table_present(conn, "am_law_article"):
        return ("(autonomath.db / 通達 corpus unavailable)", [])
    like = f"%{_safe_like_token(topic)}%"
    limit = min(1 + depth, 8)
    try:
        cur = conn.execute(
            (
                "SELECT law_canonical_id, article_number, article_title, body, source_url "
                "  FROM am_law_article "
                " WHERE law_canonical_id LIKE '%-tsutatsu%' "
                "   AND (article_title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') "
                "   AND body IS NOT NULL "
                " ORDER BY length(body) DESC "
                " LIMIT ?"
            ),
            (like, like, limit),
        )
        rows = list(cur.fetchall())
    except sqlite3.Error as exc:
        logger.debug("HE3 tsutatsu query failed: %s", exc)
        return (f"(tsutatsu lookup failed: {exc})", [])
    if not rows:
        return ("(関連 通達 一致 0 件)", [])
    chunks: list[str] = []
    structured: list[dict[str, Any]] = []
    body_cap = 240 if depth <= 2 else 480
    for row in rows:
        body = (row["body"] or "")[:body_cap]
        title = row["article_title"] or row["law_canonical_id"]
        chunks.append(f"[{title}] {body}")
        structured.append(
            {
                "law_canonical_id": row["law_canonical_id"],
                "article_number": row["article_number"],
                "title": title,
                "body_excerpt": body,
                "source_url": row["source_url"],
            }
        )
    return ("\n\n".join(chunks), structured)


def _build_judgment(
    conn: sqlite3.Connection | None,
    topic: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Top-3 (or depth-tuned) court_decisions / nta_saiketsu summaries."""
    structured: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    if conn is None:
        return ("(autonomath.db unavailable — judgment summaries empty)", [])
    like = f"%{_safe_like_token(topic)}%"
    limit = min(3 + (depth - 1), 8) if depth >= 2 else 3
    if _table_present(conn, "court_decisions"):
        try:
            cur = conn.execute(
                (
                    "SELECT decision_id, case_name, court_name, decision_date, "
                    "       key_ruling, source_url "
                    "  FROM court_decisions "
                    " WHERE (case_name LIKE ? ESCAPE '\\' "
                    "        OR key_ruling LIKE ? ESCAPE '\\') "
                    " ORDER BY decision_date DESC "
                    " LIMIT ?"
                ),
                (like, like, limit),
            )
            for row in cur.fetchall():
                ruling = (row["key_ruling"] or "")[:240]
                text_blocks.append(
                    f"[{row['court_name'] or '裁判所'} {row['decision_date'] or ''}] "
                    f"{row['case_name'] or row['decision_id']}: {ruling}"
                )
                structured.append(
                    {
                        "kind": "judgment",
                        "decision_id": row["decision_id"],
                        "court_name": row["court_name"],
                        "decision_date": row["decision_date"],
                        "case_name": row["case_name"],
                        "key_ruling_excerpt": ruling,
                        "source_url": row["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.debug("HE3 court_decisions query failed: %s", exc)
    if _table_present(conn, "nta_saiketsu") and len(structured) < limit:
        try:
            cur = conn.execute(
                (
                    "SELECT saiketsu_id, title, decision_date, decision_summary, source_url "
                    "  FROM nta_saiketsu "
                    " WHERE (title LIKE ? ESCAPE '\\' "
                    "        OR decision_summary LIKE ? ESCAPE '\\') "
                    " ORDER BY decision_date DESC "
                    " LIMIT ?"
                ),
                (like, like, limit - len(structured)),
            )
            for row in cur.fetchall():
                summary = (row["decision_summary"] or "")[:240]
                text_blocks.append(
                    f"[国税不服審判所 裁決 {row['decision_date'] or ''}] "
                    f"{row['title'] or row['saiketsu_id']}: {summary}"
                )
                structured.append(
                    {
                        "kind": "saiketsu",
                        "saiketsu_id": row["saiketsu_id"],
                        "decision_date": row["decision_date"],
                        "title": row["title"],
                        "summary_excerpt": summary,
                        "source_url": row["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.debug("HE3 nta_saiketsu query failed: %s", exc)
    if not text_blocks:
        return ("(関連 判例 / 採決 0 件)", [])
    return ("\n\n".join(text_blocks), structured)


def _build_practical_guidance(
    conn: sqlite3.Connection | None,
    topic: str,
    target_segment: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Pull reasoning_chain conclusion text where present, else static guidance."""
    chains: list[dict[str, Any]] = []
    if conn is not None and _table_present(conn, "am_legal_reasoning_chain"):
        like = f"%{_safe_like_token(topic)}%"
        limit = min(2 + depth, 6)
        try:
            cur = conn.execute(
                (
                    "SELECT chain_id, topic_label, conclusion_text, confidence, "
                    "       opposing_view_text "
                    "  FROM am_legal_reasoning_chain "
                    " WHERE (topic_label LIKE ? ESCAPE '\\' "
                    "        OR conclusion_text LIKE ? ESCAPE '\\') "
                    "   AND confidence >= 0.55 "
                    " ORDER BY confidence DESC "
                    " LIMIT ?"
                ),
                (like, like, limit),
            )
            for row in cur.fetchall():
                chains.append(
                    {
                        "chain_id": row["chain_id"],
                        "topic_label": row["topic_label"],
                        "conclusion": (row["conclusion_text"] or "")[:480],
                        "confidence": float(row["confidence"] or 0.0),
                        "opposing_view": (row["opposing_view_text"] or "")[:320],
                    }
                )
        except sqlite3.Error as exc:
            logger.debug("HE3 reasoning_chain query failed: %s", exc)
    if chains:
        blocks = [f"({c['confidence']:.2f}) {c['topic_label']}: {c['conclusion']}" for c in chains]
        return ("\n\n".join(blocks), chains)
    # Static fallback — per-segment generic guidance.
    static = (
        f"{_SEGMENTS_JA.get(target_segment, target_segment)} 向け実務指針: "
        f"{topic} に該当する処理は (1) 法令 verbatim を顧客に開示、"
        "(2) 関連 通達 / 採決 を併示、(3) 自社 判断は士業の supervision 下で確定、"
        "(4) primary source URL を成果物に添付、の 4 段で進める。"
    )
    return (static, [])


def _build_common_pitfalls(topic: str, target_segment: str) -> str:
    """Static common-pitfalls list — segment-aware, deterministic."""
    base = [
        f"通達のみで判断し法令本文を確認しない (topic: {topic})",
        "改正前後の effective_from を確認せず stale な解釈を流用する",
        "判例の射程外まで類推適用する",
        "顧客側資料の一次根拠を取らず agent 出力を完結扱いする",
    ]
    seg_specific = {
        "税理士": "署名前に税理士法 §52 / §47条の2 の範囲外業務に踏み込む",
        "会計士": "監査調書に判例 / 採決の出典 URL を残さず draft で確定する",
        "中小経営者": "弁護士法 §72 / 税理士法 §52 を越えた助言を agent から鵜呑みにする",
        "AX_engineer": "agent 出力の disclaimer envelope を strip して endpoint を出す",
        "FDE": "SOW 範囲外の業務範囲を agent に丸投げしクライアント審査を skip する",
    }.get(target_segment)
    if seg_specific:
        base.append(seg_specific)
    return "\n".join(f"- {item}" for item in base)


def _build_next_steps(topic: str, target_segment: str, depth: int) -> str:
    """Deterministic next-step recommendations keyed to segment + depth."""
    base_steps = [
        f"jpcite `get_law_article_am` で {topic} の関連条文 verbatim を取得",
        "jpcite `walk_reasoning_chain` で 三段論法 chain を取得し confidence > 0.6 を採用",
        "jpcite `search_acceptance_stats_am` で類似ケースの採択統計を確認",
    ]
    if depth >= 3:
        base_steps.append("jpcite `get_artifact_template` で N1 成果物テンプレートを取得")
        base_steps.append("jpcite `list_recipes` で対応する N8 recipe を辿る")
    if depth >= 4:
        base_steps.append("Wave 51 dim Q `query_at_snapshot` で as_of=過去日 の状態を比較")
        base_steps.append("Wave 51 dim O `get_explainable_fact` で出典の verify_signature を確認")
    seg_steps = {
        "税理士": "顧問先 client_profile に紐付け saved_search を登録",
        "会計士": "audit_seal monthly pack の corpus snapshot id を採取",
        "中小経営者": "信頼できる税理士・社労士に必ず照会",
        "AX_engineer": "agent system prompt の disclaimer envelope に組み込み",
        "FDE": "クライアントの SOW に成果物の primary source 添付を bind",
    }.get(target_segment)
    if seg_steps:
        base_steps.append(seg_steps)
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(base_steps))


def _build_applicable_templates(
    conn: sqlite3.Connection | None,
    target_segment: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """N1 artifact template suggestions from am_artifact_templates."""
    structured: list[dict[str, Any]] = []
    if conn is None or not _table_present(conn, "am_artifact_templates"):
        return ("(N1 template table unavailable)", [])
    # _SEGMENTS_JA happens to be the canonical N1 segment label set; only
    # forward when the segment matches a 士業 surface.
    if target_segment not in ("税理士", "会計士"):
        return (
            "(N1 templates are 士業 surface only — current segment uses recipe-only flow)",
            [],
        )
    limit = min(3 + depth, 8)
    try:
        cur = conn.execute(
            (
                "SELECT artifact_type, artifact_name_ja, authority, "
                "       quality_grade, requires_professional_review "
                "  FROM am_artifact_templates "
                " WHERE segment = ? "
                " ORDER BY quality_grade ASC, artifact_type "
                " LIMIT ?"
            ),
            (target_segment, limit),
        )
        for row in cur.fetchall():
            structured.append(
                {
                    "artifact_type": row["artifact_type"],
                    "artifact_name_ja": row["artifact_name_ja"],
                    "authority": row["authority"],
                    "quality_grade": row["quality_grade"],
                    "requires_professional_review": bool(row["requires_professional_review"]),
                }
            )
    except sqlite3.Error as exc:
        logger.debug("HE3 artifact_templates query failed: %s", exc)
        return (f"(template lookup failed: {exc})", [])
    if not structured:
        return ("(N1 templates 0 件)", [])
    text = "\n".join(
        f"- {t['artifact_name_ja']} ({t['artifact_type']}, grade={t['quality_grade']})"
        for t in structured
    )
    return (text, structured)


def _build_filing_windows(
    conn: sqlite3.Connection | None,
    topic: str,
    depth: int,
) -> tuple[str, list[dict[str, Any]]]:
    """N4 filing windows from am_application_round, sorted by deadline ASC."""
    if conn is None or not _table_present(conn, "am_application_round"):
        return ("(N4 application_round table unavailable)", [])
    like = f"%{_safe_like_token(topic)}%"
    limit = min(3 + depth, 8)
    structured: list[dict[str, Any]] = []
    try:
        cur = conn.execute(
            (
                "SELECT round_id, program_canonical_id, round_label, "
                "       apply_window_start, apply_window_end, "
                "       deadline, status "
                "  FROM am_application_round "
                " WHERE (round_label LIKE ? ESCAPE '\\' "
                "        OR program_canonical_id LIKE ? ESCAPE '\\') "
                "   AND deadline IS NOT NULL "
                " ORDER BY deadline ASC "
                " LIMIT ?"
            ),
            (like, like, limit),
        )
        for row in cur.fetchall():
            structured.append(
                {
                    "round_id": row["round_id"],
                    "program_canonical_id": row["program_canonical_id"],
                    "round_label": row["round_label"],
                    "apply_window_start": row["apply_window_start"],
                    "apply_window_end": row["apply_window_end"],
                    "deadline": row["deadline"],
                    "status": row["status"],
                }
            )
    except sqlite3.Error as exc:
        logger.debug("HE3 filing_windows query failed: %s", exc)
        return (f"(window lookup failed: {exc})", [])
    if not structured:
        return ("(関連 filing windows 0 件)", [])
    text = "\n".join(
        f"- {w['round_label'] or w['program_canonical_id']}: 締切 {w['deadline']} ({w['status']})"
        for w in structured
    )
    return (text, structured)


def _disclaimer_envelope_text(target_segment: str) -> str:
    acts = " / ".join(_SEGMENT_ACTS.get(target_segment, ()))
    return (
        f"{DISCLAIMER}\n"
        f"対象セグメント業法: {acts}\n"
        "本 pack は agent context injection 用の retrieval 集約で、"
        "士業独占業務 / 法的助言 / 税務代理を構成しません。"
    )


# ---------------------------------------------------------------------------
# Format encoders — claude_xml / openai_json / markdown_doc
# ---------------------------------------------------------------------------


_XML_ESCAPE = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&apos;",
}


def _xml_escape(value: str) -> str:
    return "".join(_XML_ESCAPE.get(ch, ch) for ch in value)


def _claude_xml(sections: list[dict[str, str]], topic: str, target_segment: str) -> str:
    parts: list[str] = []
    parts.append(f'<briefing topic="{_xml_escape(topic)}" segment="{_xml_escape(target_segment)}">')
    for sec in sections:
        name = _xml_escape(sec["section"])
        content = _xml_escape(sec["content"])
        parts.append(f"  <{name}>\n{content}\n  </{name}>")
    parts.append("</briefing>")
    return "\n".join(parts)


def _openai_json(
    sections: list[dict[str, str]],
    topic: str,
    target_segment: str,
) -> dict[str, Any]:
    return {
        "topic": topic,
        "segment": target_segment,
        "schema": "agent_briefing_pack.v1",
        "sections": [{"section": s["section"], "content": s["content"]} for s in sections],
    }


def _markdown_doc(sections: list[dict[str, str]], topic: str, target_segment: str) -> str:
    parts = [f"# Briefing Pack — {topic}", f"\n_Segment: {target_segment}_\n"]
    pretty_names: dict[str, str] = {
        "context": "コンテキスト",
        "current_law": "現行法令 (verbatim)",
        "tsutatsu": "通達 (verbatim)",
        "judgment_summary": "判例 / 採決 要約",
        "practical_guidance": "実務指針",
        "common_pitfalls": "よくある間違い",
        "next_step_recommendations": "次に何をすべきか",
        "applicable_templates": "適用可能 N1 テンプレート",
        "related_filing_windows": "関連 filing windows (N4)",
        "disclaimer_envelope": "免責 / 業法 envelope",
    }
    for sec in sections:
        heading = pretty_names.get(sec["section"], sec["section"])
        parts.append(f"\n## {heading}\n\n{sec['content']}")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Recipe text
# ---------------------------------------------------------------------------


def _agent_usage_recipe(target_segment: str, token_count_estimated: int) -> str:
    label = _SEGMENTS_JA.get(target_segment, target_segment)
    return (
        f"# Usage recipe — {label} agent system prompt injection\n"
        "1. agent system prompt の末尾に `briefing_pack_xml` (Claude) または "
        "`briefing_pack_json.sections` (OpenAI) を inject\n"
        "2. agent は context 内で current_law / tsutatsu / judgment_summary を "
        "再質問せず直接引用\n"
        "3. `next_step_recommendations` を agent の plan/act loop の初期 step として固定\n"
        "4. `disclaimer_envelope` を ユーザー応答 末尾に attach (士業独占範囲の自動回避)\n"
        "5. 1 HE-3 call (¥12, Tier C) で agent turn 数 を 3-5 → 1-2 に圧縮、"
        "   入出力 token は本 pack 約 "
        f"{token_count_estimated:,} tokens × 1 turn 注入のみ"
    )


# ---------------------------------------------------------------------------
# Public MCP tool surface
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
def agent_briefing_pack(
    topic: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description=(
                "Free-form briefing topic (e.g. '役員報酬の損金算入', '消費税の "
                "仕入税額控除', 'M&A デューデリ'). Used to filter 法令 / 通達 / "
                "判例 / 採決 corpora via LIKE + reasoning_chain match."
            ),
        ),
    ],
    target_segment: Annotated[
        str,
        Field(
            pattern=_SEGMENT_PATTERN,
            description=("Audience segment: 税理士 / 会計士 / 中小経営者 / AX_engineer / FDE."),
        ),
    ],
    output_format: Annotated[
        str,
        Field(
            pattern=_FORMAT_PATTERN,
            description=(
                "Default 'claude_xml'. Choose 'openai_json' for OpenAI-style "
                "structured prompts, 'markdown_doc' for human review."
            ),
        ),
    ] = "claude_xml",
    token_budget: Annotated[
        int,
        Field(
            ge=500,
            le=30000,
            description=(
                "Soft target for total pack tokens (estimated). Budget controls "
                "depth_level: 500-1500 → depth 1, 1501-3500 → depth 2, "
                "3501-8000 → depth 3, 8001-14000 → depth 4, 14001-30000 → depth 5."
            ),
        ),
    ] = 8000,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat HE-3 agent briefing pack.

    Returns a 10-section structured pack tuned for direct injection into an
    agent's context window. Sections: context / current_law / tsutatsu /
    judgment_summary / practical_guidance / common_pitfalls /
    next_step_recommendations / applicable_templates / related_filing_windows /
    disclaimer_envelope. Three parallel output encodings (Claude XML, OpenAI
    JSON, Markdown). NO LLM inference — pure SQLite + Python composition.
    """
    primary_input = {
        "topic": topic,
        "target_segment": target_segment,
        "output_format": output_format,
        "token_budget": token_budget,
    }
    depth = depth_from_budget(token_budget)

    conn = _open_ro()
    try:
        ctx_text = _build_context(topic, target_segment, depth)
        law_text, law_struct = _build_current_law(conn, topic, depth)
        tsu_text, tsu_struct = _build_tsutatsu(conn, topic, depth)
        jud_text, jud_struct = _build_judgment(conn, topic, depth)
        guide_text, guide_struct = _build_practical_guidance(conn, topic, target_segment, depth)
        pitfalls_text = _build_common_pitfalls(topic, target_segment)
        next_text = _build_next_steps(topic, target_segment, depth)
        tmpl_text, tmpl_struct = _build_applicable_templates(conn, target_segment, depth)
        win_text, win_struct = _build_filing_windows(conn, topic, depth)
        disclaimer_text = _disclaimer_envelope_text(target_segment)
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    sections: list[dict[str, str]] = [
        {"section": "context", "content": ctx_text},
        {"section": "current_law", "content": law_text},
        {"section": "tsutatsu", "content": tsu_text},
        {"section": "judgment_summary", "content": jud_text},
        {"section": "practical_guidance", "content": guide_text},
        {"section": "common_pitfalls", "content": pitfalls_text},
        {"section": "next_step_recommendations", "content": next_text},
        {"section": "applicable_templates", "content": tmpl_text},
        {"section": "related_filing_windows", "content": win_text},
        {"section": "disclaimer_envelope", "content": disclaimer_text},
    ]

    xml_text = _claude_xml(sections, topic, target_segment)
    json_obj = _openai_json(sections, topic, target_segment)
    md_text = _markdown_doc(sections, topic, target_segment)

    # Pick the "primary" format for token-count estimation per the request.
    fmt_primary: str = (
        xml_text
        if output_format == "claude_xml"
        else (
            json.dumps(json_obj, ensure_ascii=False) if output_format == "openai_json" else md_text
        )
    )
    token_count_estimated = estimate_tokens(fmt_primary)

    structured_payload = {
        "current_law": law_struct,
        "tsutatsu": tsu_struct,
        "judgment_summary": jud_struct,
        "practical_guidance": guide_struct,
        "applicable_templates": tmpl_struct,
        "related_filing_windows": win_struct,
    }

    return {
        "tool_name": "agent_briefing_pack",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "depth_level": depth,
            "token_count_estimated": token_count_estimated,
        },
        "briefing_pack_xml": xml_text,
        "briefing_pack_json": json_obj,
        "briefing_pack_markdown": md_text,
        "token_count_estimated": token_count_estimated,
        "sections": sections,
        "structured_payload": structured_payload,
        "agent_usage_recipe": _agent_usage_recipe(target_segment, token_count_estimated),
        "billing": {
            "billable_units": 4,
            "unit_price_jpy_taxed": 3.30,
            "unit_price_jpy": 3,
            "tier": "C",
            "pricing_version": "v3",
            "total_jpy": 12,
            "model": "per_call",
        },
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_he3_briefing_pack",
            "observed_at": today_iso_utc(),
            "depth_level": depth,
            "output_format": output_format,
        },
        "_billing_unit": 4,
        "_disclaimer": DISCLAIMER,
        "_provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "observed_at": today_iso_utc(),
            "schema_version": _SCHEMA_VERSION,
            "depth_level": depth,
            "law_rows_n": len(law_struct),
            "tsutatsu_rows_n": len(tsu_struct),
            "judgment_rows_n": len(jud_struct),
            "chain_rows_n": len(guide_struct),
            "template_rows_n": len(tmpl_struct),
            "window_rows_n": len(win_struct),
        },
    }


__all__ = [
    "agent_briefing_pack",
    "depth_from_budget",
    "estimate_tokens",
]
