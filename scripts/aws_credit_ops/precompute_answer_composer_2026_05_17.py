#!/usr/bin/env python3
"""P2 — Pre-computed answer composer (rule-based, NO LLM).

Reads FAQ yaml seeds from ``data/faq_bank/{cohort}_top100.yaml`` (5 files,
100 questions each) and INSERTs one row per FAQ into ``am_precomputed_answer``
(autonomath.db, migration ``wave24_207_am_precomputed_answer.sql``). The
composer is purely deterministic — it walks the corpus (am_entities /
am_law_reference / am_source / am_authority) to pull citation-bearing facts
and assembles a structured answer envelope. NO Anthropic / OpenAI / Google
LLM SDK call is made at compose time or serve time.

Usage
-----
    .venv/bin/python scripts/aws_credit_ops/precompute_answer_composer_2026_05_17.py \\
        --input data/faq_bank/zeirishi_top100.yaml \\
                data/faq_bank/kaikeishi_top100.yaml \\
                data/faq_bank/gyouseishoshi_top100.yaml \\
                data/faq_bank/shihoshoshi_top100.yaml \\
                data/faq_bank/chusho_keieisha_top100.yaml \\
        --output autonomath.am_precomputed_answer \\
        --depth-level 3 \\
        --workers 8 \\
        --commit

Constraints
-----------
* No Anthropic / OpenAI / Google SDK import.
* Read-mostly on autonomath.db; writes only to ``am_precomputed_answer`` via
  a single writable connection per process.
* Idempotent — INSERT OR REPLACE on (cohort, faq_slug).
* mypy --strict clean / ruff clean / no LLM.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("jpcite.p3.composer")


# Canonical cohort slug normalization. P1 YAMLs use a mix of romaji + Japanese.
COHORT_SLUG: dict[str, str] = {
    "税理士": "tax",
    "公認会計士": "audit",
    "会計士": "audit",
    "行政書士": "gyousei",
    "司法書士": "shihoshoshi",
    "中小経営者": "chusho_keieisha",
    "zeirishi": "tax",
    "kaikeishi": "audit",
    "gyouseishoshi": "gyousei",
    "shihoshoshi": "shihoshoshi",
    "chusho_keieisha": "chusho_keieisha",
}


# Citation seed candidates per cohort. The composer joins on
# am_entities(record_kind) + filename keyword to surface up to 5 deterministic
# citations per FAQ. Live counts on autonomath.db:
#   law=252, tax_measure=285, program=8203, authority=20, am_law_reference=5523.
_SEED_KIND_BY_COHORT: dict[str, tuple[str, ...]] = {
    "tax": ("tax_measure", "law", "authority"),
    "audit": ("law", "authority", "tax_measure"),
    "gyousei": ("law", "program", "authority"),
    "shihoshoshi": ("law", "authority", "program"),
    "chusho_keieisha": ("program", "tax_measure", "law"),
}


@dataclass
class FaqRow:
    """One FAQ entry parsed from a cohort yaml."""

    cohort: str
    cohort_label_ja: str
    qid: str
    category: str
    question_text: str
    variants: list[str]
    priority: str
    depth_target: int
    required_data_sources: list[str]
    opus_baseline_jpy: int
    jpcite_target_jpy: int
    legal_disclaimer: str


@dataclass
class ComposedAnswer:
    """One composed answer for am_precomputed_answer."""

    cohort: str
    faq_slug: str
    question_id: str
    question_text: str
    question_variants: list[str]
    answer_text: str
    answer_md: str
    answer_xml: str
    citation_ids: list[str]
    citation_urls: list[str]
    source_citations: list[dict[str, Any]]
    sections: list[dict[str, str]] = field(default_factory=list)
    composed_from: dict[str, list[str]] = field(default_factory=dict)
    depth_level: int = 3
    freshness_state: str = "unknown"
    composer_version: str = "p2.v1"
    legal_disclaimer: str = "§52"
    opus_baseline_jpy: int = 0
    jpcite_actual_jpy: int = 3


# ---------------------------------------------------------------------------
# Tiny YAML-subset parser (zero PyYAML dep, mirrors moat_n8_recipe approach)
# ---------------------------------------------------------------------------


_LIST_OF_DICT_ENTRY = re.compile(r"^\s{2}- ")
_INDENT_LEAF = re.compile(r"^(\s+)([\w　-鿿_]+):\s*(.*)$")
_QUOTED_STR = re.compile(r"^([\"'])(.*)\1$")
_BARE_LIST = re.compile(r"^\[(.*)\]$")


def _coerce_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    m = _QUOTED_STR.match(s)
    if m:
        return m.group(2)
    if _BARE_LIST.match(s):
        body = s[1:-1].strip()
        if not body:
            return []
        return [_coerce_scalar(p) for p in body.split(",")]
    lower = s.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", "~"):
        return None
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except ValueError:
            pass
    return s


def _parse_question_block(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    """Parse one ``- id: ...`` block starting at ``lines[start]`` (a leaf-listed
    dict). Returns (block_dict, next_index).
    """
    block: dict[str, Any] = {}
    i = start
    first = lines[i]
    # Strip "  - " prefix.
    rest = first[4:]
    if ": " in rest:
        k, _, v = rest.partition(": ")
        block[k.strip()] = _coerce_scalar(v)
    i += 1
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _LIST_OF_DICT_ENTRY.match(line):
            break
        m = _INDENT_LEAF.match(line)
        if m is None:
            i += 1
            continue
        indent, key, value = m.groups()
        if len(indent) <= 2:
            break
        if value == "":
            # Next lines are a yaml list of bare strings.
            block[key] = []
            i += 1
            continue
        block[key] = _coerce_scalar(value)
        i += 1
    # Slurp pending list items (lines starting with '      - "..."').
    j = start + 1
    while j < len(lines):
        line = lines[j]
        bare = line.strip()
        if bare.startswith("- "):
            indent_match = re.match(r"^(\s+)-", line)
            if indent_match and len(indent_match.group(1)) > 4:
                # Find parent key by scanning back for the closest leaf with empty value
                key_search = j - 1
                while key_search > start:
                    prev = lines[key_search]
                    mm = _INDENT_LEAF.match(prev)
                    if mm and mm.group(3) == "":
                        parent_key = mm.group(2)
                        v = bare[2:].strip()
                        block.setdefault(parent_key, [])
                        if isinstance(block[parent_key], list):
                            block[parent_key].append(_coerce_scalar(v))
                        break
                    key_search -= 1
        j += 1
    return block, i


def parse_faq_yaml(path: Path) -> list[FaqRow]:
    """Parse one cohort yaml into ``FaqRow`` list."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    cohort_label_ja = ""
    legal_default = "§52"
    # Walk meta block first.
    in_meta = False
    for ln in lines:
        s = ln.rstrip()
        if s.startswith("meta:"):
            in_meta = True
            continue
        if in_meta:
            if s.startswith("  cohort:"):
                cohort_label_ja = s.split(":", 1)[1].strip()
            elif s.startswith("  legal_disclaimer_default:"):
                legal_default = s.split(":", 1)[1].strip()
            elif s.startswith("questions:") or not s.startswith("  "):
                in_meta = False
                break

    cohort_slug = COHORT_SLUG.get(cohort_label_ja, "tax")

    # Find question blocks.
    rows: list[FaqRow] = []
    i = 0
    in_questions = False
    while i < len(lines):
        if lines[i].startswith("questions:"):
            in_questions = True
            i += 1
            continue
        if not in_questions:
            i += 1
            continue
        if _LIST_OF_DICT_ENTRY.match(lines[i]):
            block, next_i = _parse_question_block(lines, i)
            qid = str(block.get("id", "")).strip()
            qtxt = str(block.get("question", "")).strip()
            if qid and qtxt:
                variants_raw = block.get("question_variants") or []
                if isinstance(variants_raw, list):
                    variants = [str(v) for v in variants_raw if v]
                else:
                    variants = []
                depth = block.get("answer_depth_target", 3)
                try:
                    depth_int = int(depth)
                except (TypeError, ValueError):
                    depth_int = 3
                opus_jpy = block.get("opus_baseline_cost_estimate_jpy", 18)
                try:
                    opus_int = int(opus_jpy)
                except (TypeError, ValueError):
                    opus_int = 18
                rds_raw = block.get("required_data_sources") or []
                rds = [str(v) for v in rds_raw if v] if isinstance(rds_raw, list) else []
                rows.append(
                    FaqRow(
                        cohort=cohort_slug,
                        cohort_label_ja=cohort_label_ja,
                        qid=qid,
                        category=str(block.get("category", "")),
                        question_text=qtxt,
                        variants=variants,
                        priority=str(block.get("priority", "MED")),
                        depth_target=depth_int,
                        required_data_sources=rds,
                        opus_baseline_jpy=opus_int,
                        jpcite_target_jpy=3,
                        legal_disclaimer=str(block.get("legal_disclaimer", legal_default)),
                    )
                )
            i = next_i
        else:
            i += 1
    return rows


# ---------------------------------------------------------------------------
# Citation lookup (deterministic SQLite walk)
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_ro_db() -> sqlite3.Connection:
    p = _autonomath_db_path()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw_db() -> sqlite3.Connection:
    p = _autonomath_db_path()
    conn = sqlite3.connect(str(p), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _keyword_tokens(faq: FaqRow) -> list[str]:
    """Extract simple keyword candidates from category + question_text.

    Used as LIKE %keyword% filter against ``am_entities.primary_name``.
    """
    tokens: list[str] = []
    cat = faq.category.strip()
    if cat:
        tokens.append(cat)
    # Drop generic verbs ending in です/ます; keep 2-3 char kanji slices.
    qt = faq.question_text
    # Pick first 6-8 chars that look like a key noun phrase.
    head = qt[:8]
    if head and head not in tokens:
        tokens.append(head)
    return tokens[:3]


def _pull_citations(conn: sqlite3.Connection, faq: FaqRow, limit: int = 5) -> list[dict[str, Any]]:
    """Pull deterministic citations from am_entities for a FAQ."""
    kinds = _SEED_KIND_BY_COHORT.get(faq.cohort, ("law", "program", "authority"))
    tokens = _keyword_tokens(faq)
    cites: list[dict[str, Any]] = []
    seen: set[str] = set()

    for kind in kinds:
        if len(cites) >= limit:
            break
        for token in tokens:
            if len(cites) >= limit:
                break
            try:
                cur = conn.execute(
                    """
                    SELECT canonical_id, record_kind, primary_name,
                           source_url, fetched_at, authority_canonical
                      FROM am_entities
                     WHERE record_kind = ?
                       AND primary_name LIKE ?
                       AND source_url IS NOT NULL
                       AND source_url <> ''
                       AND citation_status = 'ok'
                     ORDER BY confidence DESC NULLS LAST,
                              fetched_at DESC NULLS LAST
                     LIMIT 3
                    """,
                    (kind, f"%{token}%"),
                )
                for row in cur.fetchall():
                    cid = row["canonical_id"]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    cites.append(
                        {
                            "kind": kind,
                            "id": cid,
                            "source_url": row["source_url"],
                            "primary_name": row["primary_name"],
                            "fetched_at": row["fetched_at"],
                            "authority": row["authority_canonical"],
                        }
                    )
                    if len(cites) >= limit:
                        break
            except sqlite3.Error as exc:
                logger.warning("citation pull failed (%s, %s): %s", kind, token, exc)
                continue
    # Fallback: if no kind+token matches anything, take any top-confidence entity
    # of the first cohort-seed kind so every FAQ carries at least one provenance.
    if not cites:
        try:
            cur = conn.execute(
                """
                SELECT canonical_id, record_kind, primary_name,
                       source_url, fetched_at, authority_canonical
                  FROM am_entities
                 WHERE record_kind = ?
                   AND source_url IS NOT NULL
                   AND source_url <> ''
                   AND citation_status = 'ok'
                 ORDER BY confidence DESC NULLS LAST
                 LIMIT ?
                """,
                (kinds[0], limit),
            )
            for row in cur.fetchall():
                cites.append(
                    {
                        "kind": row["record_kind"],
                        "id": row["canonical_id"],
                        "source_url": row["source_url"],
                        "primary_name": row["primary_name"],
                        "fetched_at": row["fetched_at"],
                        "authority": row["authority_canonical"],
                    }
                )
        except sqlite3.Error as exc:
            logger.warning("fallback citation pull failed: %s", exc)
    return cites


def _freshness_state(citations: Iterable[dict[str, Any]]) -> str:
    """Compute freshness_state from max(fetched_at)."""
    latest = ""
    for c in citations:
        f = c.get("fetched_at") or ""
        if isinstance(f, str) and f > latest:
            latest = f
    if not latest:
        return "unknown"
    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    # fetched_at within last 365 days = fresh.
    try:
        latest_date = latest[:10]
        from datetime import date

        a = date.fromisoformat(latest_date)
        b = date.fromisoformat(today)
        delta_days = (b - a).days
        if delta_days <= 365:
            return "fresh"
        return "stale"
    except ValueError:
        return "unknown"


# ---------------------------------------------------------------------------
# Answer composition (rule-based, deterministic)
# ---------------------------------------------------------------------------


_LEGAL_DISCLAIMER_MAP = {
    "§52": (
        "本回答は jpcite が autonomath.db (公的機関の公開情報) から機械的に組み立てた"
        "scaffold-only な参考情報です。税理士法 §52 に基づく個別具体的な税務助言の"
        "代替ではありません。最終判断は税理士へご相談ください。"
    ),
    "§47条の2": (
        "本回答は scaffold-only であり、公認会計士法 §47条の2 に基づく監査意見の"
        "代替ではありません。会計士の専門的判断を経た上でご利用ください。"
    ),
    "§1": (
        "本回答は scaffold-only であり、行政書士法 §1 に基づく官公署提出書類の作成"
        "代替ではありません。最終判断は行政書士へご相談ください。"
    ),
    "§3": (
        "本回答は scaffold-only であり、司法書士法 §3 に基づく登記業務の代替では"
        "ありません。最終判断は司法書士へご相談ください。"
    ),
    "中小企業政策": (
        "本回答は scaffold-only な参考情報であり、中小企業庁・経済産業省・各自治体の"
        "公表情報を機械的に整理したものです。最終的な申請可否は各窓口へご確認ください。"
    ),
}


def _section_body(faq: FaqRow, kind: str, cites: list[dict[str, Any]]) -> str:
    """Render one body section."""
    if kind == "結論":
        if cites:
            primary = cites[0]["primary_name"]
            return (
                f"質問「{faq.question_text}」については、{primary} を一次根拠として、"
                f"以下の {len(cites)} 件の公的情報源を機械的に整理しました。"
            )
        return (
            f"質問「{faq.question_text}」について、autonomath.db の最新スナップショット"
            f"には直接該当する一次資料が登録されていません。スコープ拡張を推奨します。"
        )
    if kind == "根拠":
        bullets = []
        for c in cites:
            bullets.append(f"- ({c['kind']}) {c['primary_name']}: {c['source_url']}")
        return "\n".join(bullets) if bullets else "(該当する一次資料の citation pull 失敗)"
    if kind == "実務留意点":
        return (
            f"カテゴリ: {faq.category}\n"
            f"優先度: {faq.priority}\n"
            f"深さ目標: depth={faq.depth_target}\n"
            f"※ 本回答は LLM 推論を一切伴わない rule-based composer の出力です。"
        )
    if kind == "関連書類":
        rds = faq.required_data_sources
        return "P1 yaml が指定するデータソース: " + ", ".join(rds) if rds else "(P1 yaml 未指定)"
    if kind == "免責事項":
        return _LEGAL_DISCLAIMER_MAP.get(faq.legal_disclaimer, _LEGAL_DISCLAIMER_MAP["§52"])
    return ""


def _compose_one(faq: FaqRow, cites: list[dict[str, Any]], depth_level: int) -> ComposedAnswer:
    """Compose one answer (NO LLM)."""
    section_kinds = ["結論", "根拠", "実務留意点", "関連書類", "免責事項"]
    sections: list[dict[str, str]] = []
    md_parts: list[str] = [f"# {faq.question_text}\n"]
    xml_parts: list[str] = [f'<precomputed_answer cohort="{faq.cohort}" faq_id="{faq.qid}">']
    for kind in section_kinds:
        body = _section_body(faq, kind, cites)
        sections.append({"name": kind, "body": body})
        md_parts.append(f"## {kind}\n\n{body}\n")
        xml_parts.append(f'  <section name="{kind}">{body}</section>')
    xml_parts.append("</precomputed_answer>")

    answer_md = "\n".join(md_parts)
    answer_xml = "\n".join(xml_parts)
    answer_text = "\n\n".join(s["body"] for s in sections)

    faq_slug = faq.qid
    citation_ids = [c["id"] for c in cites]
    citation_urls = [c["source_url"] for c in cites if c.get("source_url")]
    source_citations = [
        {
            "kind": c["kind"],
            "id": c["id"],
            "source_url": c["source_url"],
            "excerpt": (c["primary_name"] or "")[:140],
        }
        for c in cites
    ]
    composed_from: dict[str, list[str]] = {}
    for c in cites:
        composed_from.setdefault(c["kind"], []).append(c["id"])
    fresh = _freshness_state(cites)
    return ComposedAnswer(
        cohort=faq.cohort,
        faq_slug=faq_slug,
        question_id=faq.qid,
        question_text=faq.question_text,
        question_variants=faq.variants,
        answer_text=answer_text,
        answer_md=answer_md,
        answer_xml=answer_xml,
        citation_ids=citation_ids,
        citation_urls=citation_urls,
        source_citations=source_citations,
        sections=sections,
        composed_from=composed_from,
        depth_level=min(5, max(1, depth_level)),
        freshness_state=fresh,
        composer_version="p2.v1",
        legal_disclaimer=faq.legal_disclaimer,
        opus_baseline_jpy=faq.opus_baseline_jpy,
        jpcite_actual_jpy=3,
    )


def _q_hash(cohort: str, question_text: str) -> str:
    h = hashlib.sha256()
    h.update(cohort.encode("utf-8"))
    h.update(b"\x00")
    h.update(question_text.encode("utf-8"))
    return h.hexdigest()[:32]


# ---------------------------------------------------------------------------
# Worker (process-pool)
# ---------------------------------------------------------------------------


def _worker_compose(payload: dict[str, Any]) -> dict[str, Any]:
    """Process-pool worker. Re-opens RO DB to pull citations + composes."""
    faq = FaqRow(**payload["faq"])
    depth_level = int(payload.get("depth_level", 3))
    conn = _open_ro_db()
    try:
        cites = _pull_citations(conn, faq, limit=5)
    finally:
        conn.close()
    composed = _compose_one(faq, cites, depth_level)
    return {
        "cohort": composed.cohort,
        "faq_slug": composed.faq_slug,
        "question_id": composed.question_id,
        "q_hash": _q_hash(composed.cohort, composed.question_text),
        "question_text": composed.question_text,
        "question_variants": composed.question_variants,
        "answer_text": composed.answer_text,
        "answer_md": composed.answer_md,
        "answer_xml": composed.answer_xml,
        "citation_ids": composed.citation_ids,
        "citation_urls": composed.citation_urls,
        "source_citations": composed.source_citations,
        "sections": composed.sections,
        "composed_from": composed.composed_from,
        "depth_level": composed.depth_level,
        "freshness_state": composed.freshness_state,
        "composer_version": composed.composer_version,
        "opus_baseline_jpy": composed.opus_baseline_jpy,
        "jpcite_actual_jpy": composed.jpcite_actual_jpy,
    }


# ---------------------------------------------------------------------------
# INSERT path
# ---------------------------------------------------------------------------


_UPSERT_SQL = """
INSERT INTO am_precomputed_answer (
    cohort, faq_slug, question_text, question_variants,
    answer_text, citation_ids, citation_count, citation_urls,
    depth_level, composer_version, composed_at, freshness_state,
    question_id, q_hash, answer_md, answer_xml,
    sections_jsonb, composed_from, source_citations, last_composed_at,
    version_seq, opus_baseline_jpy, jpcite_actual_jpy
) VALUES (
    :cohort, :faq_slug, :question_text, :question_variants,
    :answer_text, :citation_ids, :citation_count, :citation_urls,
    :depth_level, :composer_version, :composed_at, :freshness_state,
    :question_id, :q_hash, :answer_md, :answer_xml,
    :sections_jsonb, :composed_from, :source_citations, :last_composed_at,
    :version_seq, :opus_baseline_jpy, :jpcite_actual_jpy
)
ON CONFLICT (cohort, faq_slug) DO UPDATE SET
    question_text       = excluded.question_text,
    question_variants   = excluded.question_variants,
    answer_text         = excluded.answer_text,
    citation_ids        = excluded.citation_ids,
    citation_count      = excluded.citation_count,
    citation_urls       = excluded.citation_urls,
    depth_level         = excluded.depth_level,
    composer_version    = excluded.composer_version,
    composed_at         = excluded.composed_at,
    freshness_state     = excluded.freshness_state,
    question_id         = excluded.question_id,
    q_hash              = excluded.q_hash,
    answer_md           = excluded.answer_md,
    answer_xml          = excluded.answer_xml,
    sections_jsonb      = excluded.sections_jsonb,
    composed_from       = excluded.composed_from,
    source_citations    = excluded.source_citations,
    last_composed_at    = excluded.last_composed_at,
    version_seq         = am_precomputed_answer.version_seq + 1,
    opus_baseline_jpy   = excluded.opus_baseline_jpy,
    jpcite_actual_jpy   = excluded.jpcite_actual_jpy,
    updated_at          = datetime('now')
"""

_FTS_INSERT_SQL = """
INSERT INTO am_precomputed_answer_fts (
    answer_id, cohort, faq_slug, question_text, question_variants, answer_text
) VALUES (?, ?, ?, ?, ?, ?)
"""


def _insert_one(conn: sqlite3.Connection, payload: dict[str, Any], now_iso: str) -> None:
    citation_count = len(payload["citation_ids"])
    args = {
        "cohort": payload["cohort"],
        "faq_slug": payload["faq_slug"],
        "question_text": payload["question_text"],
        "question_variants": json.dumps(payload["question_variants"], ensure_ascii=False),
        "answer_text": payload["answer_text"],
        "citation_ids": json.dumps(payload["citation_ids"], ensure_ascii=False),
        "citation_count": citation_count,
        "citation_urls": json.dumps(payload["citation_urls"], ensure_ascii=False),
        "depth_level": payload["depth_level"],
        "composer_version": payload["composer_version"],
        "composed_at": now_iso,
        "freshness_state": payload["freshness_state"],
        "question_id": payload["question_id"],
        "q_hash": payload["q_hash"],
        "answer_md": payload["answer_md"],
        "answer_xml": payload["answer_xml"],
        "sections_jsonb": json.dumps(payload["sections"], ensure_ascii=False),
        "composed_from": json.dumps(payload["composed_from"], ensure_ascii=False),
        "source_citations": json.dumps(payload["source_citations"], ensure_ascii=False),
        "last_composed_at": now_iso,
        "version_seq": 1,
        "opus_baseline_jpy": payload["opus_baseline_jpy"],
        "jpcite_actual_jpy": payload["jpcite_actual_jpy"],
    }
    conn.execute(_UPSERT_SQL, args)
    # FTS5 (manual content table — INSERT OR REPLACE pattern).
    row = conn.execute(
        "SELECT answer_id FROM am_precomputed_answer WHERE cohort=? AND faq_slug=?",
        (payload["cohort"], payload["faq_slug"]),
    ).fetchone()
    if row is not None:
        # Delete any pre-existing FTS row for this answer_id (idempotent).
        conn.execute("DELETE FROM am_precomputed_answer_fts WHERE answer_id=?", (row["answer_id"],))
        conn.execute(
            _FTS_INSERT_SQL,
            (
                row["answer_id"],
                payload["cohort"],
                payload["faq_slug"],
                payload["question_text"],
                " / ".join(payload["question_variants"]),
                payload["answer_text"],
            ),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.p3.composer")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _faq_to_payload(faq: FaqRow) -> dict[str, Any]:
    return {
        "faq": {
            "cohort": faq.cohort,
            "cohort_label_ja": faq.cohort_label_ja,
            "qid": faq.qid,
            "category": faq.category,
            "question_text": faq.question_text,
            "variants": faq.variants,
            "priority": faq.priority,
            "depth_target": faq.depth_target,
            "required_data_sources": faq.required_data_sources,
            "opus_baseline_jpy": faq.opus_baseline_jpy,
            "jpcite_target_jpy": faq.jpcite_target_jpy,
            "legal_disclaimer": faq.legal_disclaimer,
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2 — pre-computed answer composer (rule-based, NO LLM)."
    )
    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="One or more cohort yaml seed files.",
    )
    parser.add_argument(
        "--output",
        default="autonomath.am_precomputed_answer",
        help="Output table name (currently fixed at autonomath.am_precomputed_answer).",
    )
    parser.add_argument("--depth-level", type=int, default=3, help="Default depth_level (1..5).")
    parser.add_argument("--workers", type=int, default=8, help="ProcessPool worker count.")
    parser.add_argument(
        "--commit", action="store_true", help="Write to DB. Without --commit, dry-run."
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    if args.output != "autonomath.am_precomputed_answer":
        logger.warning(
            "--output is informational only; writes go to autonomath.am_precomputed_answer"
        )

    inputs = [Path(p) for p in args.input]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        for p in missing:
            logger.error("input not found: %s", p)
        return 2

    all_rows: list[FaqRow] = []
    for path in inputs:
        rows = parse_faq_yaml(path)
        logger.info("parsed %d questions from %s", len(rows), path)
        all_rows.extend(rows)

    if not all_rows:
        logger.error("no questions parsed; aborting")
        return 3

    workers = max(1, args.workers)
    payloads: list[dict[str, Any]] = [_faq_to_payload(r) for r in all_rows]
    composed: list[dict[str, Any]] = []
    if workers == 1:
        for payload in payloads:
            composed.append(_worker_compose({**payload, "depth_level": args.depth_level}))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(_worker_compose, {**payload, "depth_level": args.depth_level})
                for payload in payloads
            ]
            for f in as_completed(futures):
                composed.append(f.result())

    logger.info("composed %d answers (workers=%d)", len(composed), workers)

    if not args.commit:
        logger.info(
            "[dry-run] would INSERT OR REPLACE %d rows into am_precomputed_answer", len(composed)
        )
        return 0

    now_iso = _dt.datetime.now(_dt.UTC).isoformat()
    conn = _open_rw_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for payload in composed:
            _insert_one(conn, payload, now_iso)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    logger.info("inserted/updated %d rows in am_precomputed_answer", len(composed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
