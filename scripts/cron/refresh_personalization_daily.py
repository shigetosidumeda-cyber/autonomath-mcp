#!/usr/bin/env python3
"""Daily personalization score refresh (Wave 43.2.8 Dim H).

Recomputes `am_personalization_score` for every active
(api_key_hash × client_id) pair. NO LLM call — pure SQLite + Python.

Score = client_fit (0..30) + industry_pack_fit (0..30) + saved_search (0..40),
clamped 0..100.

Constraints:
  * No anthropic / openai / google.generativeai imports.
  * No ATTACH across DBs.

Usage:
    python scripts/cron/refresh_personalization_daily.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.refresh_personalization")


_INDUSTRY_PACKS: dict[str, dict[str, Any]] = {
    "pack_construction": {
        "jsic_major_prefix": ("D",),
        "keywords": {
            "建設",
            "建築",
            "住宅",
            "耐震",
            "改修",
            "空き家",
            "工事",
            "下請",
            "リフォーム",
            "解体",
            "リノベーション",
        },
    },
    "pack_manufacturing": {
        "jsic_major_prefix": ("E",),
        "keywords": {
            "ものづくり",
            "製造",
            "設備投資",
            "省エネ",
            "GX",
            "脱炭素",
            "事業再構築",
            "IT導入",
            "DX",
            "工場",
            "生産性",
        },
    },
    "pack_real_estate": {
        "jsic_major_prefix": ("K",),
        "keywords": {
            "不動産",
            "空き家",
            "住宅",
            "賃貸",
            "改修",
            "流通",
            "店舗",
        },
    },
    "pack_information": {
        "jsic_major_prefix": ("G",),
        "keywords": {
            "IT導入",
            "DX",
            "デジタル",
            "ソフトウェア",
            "AI",
            "セキュリティ",
            "クラウド",
            "サイバー",
        },
    },
    "pack_health_welfare": {
        "jsic_major_prefix": ("P",),
        "keywords": {
            "医療",
            "介護",
            "福祉",
            "保育",
            "看護",
            "薬局",
            "在宅医療",
        },
    },
}


_TOKEN_SPLIT = re.compile(r"[\s,、，・/]+")


def _resolve_industry_pack(jsic_major: str | None) -> str | None:
    if not jsic_major:
        return None
    prefix = jsic_major.strip().upper()[:1]
    for pack_key, meta in _INDUSTRY_PACKS.items():
        if prefix in meta["jsic_major_prefix"]:
            return pack_key
    return None


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {tok.strip() for tok in _TOKEN_SPLIT.split(text) if tok.strip()}


def _client_fit_score(profile: sqlite3.Row, program: sqlite3.Row) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    target_text = program["target_types_json"] or ""
    if profile["jsic_major"] and profile["jsic_major"][:1] in (target_text or ""):
        score += 15
        reasons.append(f"JSIC {profile['jsic_major']} match")

    pref = profile["prefecture"]
    prog_pref = program["prefecture"]
    if pref and (not prog_pref or prog_pref == pref or prog_pref == "全国"):
        score += 10
        reasons.append(f"地域 {pref} 適合")

    if profile["employee_count"] is not None and profile["employee_count"] <= 300:
        score += 5
        reasons.append("中小企業要件適合")

    if not reasons:
        reasons.append("基本条件のみ")
    return score, " / ".join(reasons)


def _industry_pack_score(pack_key: str | None, program: sqlite3.Row) -> int:
    if not pack_key:
        return 0
    meta = _INDUSTRY_PACKS.get(pack_key)
    if not meta:
        return 0
    keywords = meta["keywords"]
    haystack = " ".join((program["primary_name"] or "", program["target_types_json"] or ""))
    hits = sum(1 for kw in keywords if kw in haystack)
    if hits == 0:
        return 0
    return min(30, hits * 6)


def _saved_search_score(
    saved_search_tokens: list[dict[str, Any]], program: sqlite3.Row
) -> tuple[int, list[str]]:
    if not saved_search_tokens:
        return 0, []
    program_tokens = _tokenize(program["primary_name"]) | _tokenize(program["target_types_json"])
    matched_names: list[str] = []
    hits = 0
    for ss in saved_search_tokens:
        toks, name = ss["tokens"], ss["name"]
        if toks & program_tokens:
            hits += 1
            matched_names.append(name)
            if hits >= 4:
                break
    return min(40, hits * 10), matched_names


def _open_am_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.autonomath_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_am_tables(am_conn: sqlite3.Connection) -> bool:
    row = am_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_personalization_score'"
    ).fetchone()
    return row is not None


def _load_saved_search_tokens(jp_conn: sqlite3.Connection, key_hash: str) -> list[dict[str, Any]]:
    try:
        rows = jp_conn.execute(
            """SELECT name, canonical_query FROM saved_searches
                WHERE api_key_hash = ? AND status = 'active'""",
            (key_hash,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        toks = _tokenize(r["canonical_query"]) | _tokenize(r["name"])
        if toks:
            out.append({"name": r["name"], "tokens": toks})
    return out


def _candidate_programs(
    jp_conn: sqlite3.Connection, profile: sqlite3.Row, limit: int = 200
) -> list[sqlite3.Row]:
    pref = profile["prefecture"]
    if pref:
        return jp_conn.execute(
            """SELECT unified_id, primary_name, tier, prefecture, program_kind,
                      source_url, target_types_json
                 FROM programs
                WHERE excluded = 0
                  AND tier IN ('S','A','B','C')
                  AND (prefecture = ? OR prefecture IS NULL OR prefecture = '全国')
             ORDER BY tier ASC, updated_at DESC
                LIMIT ?""",
            (pref, limit),
        ).fetchall()
    return jp_conn.execute(
        """SELECT unified_id, primary_name, tier, prefecture, program_kind,
                  source_url, target_types_json
             FROM programs
            WHERE excluded = 0
              AND tier IN ('S','A','B','C')
         ORDER BY tier ASC, updated_at DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()


def _upsert_score(
    am_conn: sqlite3.Connection,
    *,
    api_key_hash: str,
    client_id: int,
    program_id: str,
    score: int,
    breakdown: dict[str, int],
    reasoning: dict[str, Any],
    industry_pack: str | None,
    refreshed_at: str,
) -> None:
    try:
        am_conn.execute(
            """INSERT INTO am_personalization_score(
                    api_key_hash, client_id, program_id, score,
                    score_breakdown_json, reasoning_json, industry_pack, refreshed_at
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                api_key_hash,
                client_id,
                program_id,
                score,
                json.dumps(breakdown, ensure_ascii=False),
                json.dumps(reasoning, ensure_ascii=False),
                industry_pack,
                refreshed_at,
            ),
        )
    except sqlite3.IntegrityError:
        am_conn.execute(
            """UPDATE am_personalization_score
                  SET score = ?, score_breakdown_json = ?, reasoning_json = ?,
                      industry_pack = ?, refreshed_at = ?
                WHERE api_key_hash = ? AND client_id = ? AND program_id = ?""",
            (
                score,
                json.dumps(breakdown, ensure_ascii=False),
                json.dumps(reasoning, ensure_ascii=False),
                industry_pack,
                refreshed_at,
                api_key_hash,
                client_id,
                program_id,
            ),
        )


def run(
    *,
    max_age_days: int = 14,
    limit_keys: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    summary: dict[str, Any] = {
        "started_at": started,
        "profiles_scored": 0,
        "rows_upserted": 0,
        "rows_purged": 0,
        "errors_count": 0,
        "dry_run": dry_run,
    }

    jp_conn = connect()
    am_conn = _open_am_conn()
    try:
        if not _ensure_am_tables(am_conn):
            summary["error_text"] = "am_personalization_score not found (mig 264 not applied)"
            summary["finished_at"] = datetime.now(UTC).isoformat()
            return summary

        try:
            key_rows = jp_conn.execute(
                """SELECT DISTINCT api_key_hash FROM client_profiles
                    ORDER BY api_key_hash ASC"""
            ).fetchall()
        except sqlite3.OperationalError:
            summary["error_text"] = "client_profiles not found (mig 096 not applied)"
            summary["finished_at"] = datetime.now(UTC).isoformat()
            return summary

        key_hashes = [r["api_key_hash"] for r in key_rows]
        if limit_keys is not None:
            key_hashes = key_hashes[: int(limit_keys)]

        cutoff = (datetime.now(UTC) - timedelta(days=int(max_age_days))).isoformat()

        for key_hash in key_hashes:
            saved_search_tokens = _load_saved_search_tokens(jp_conn, key_hash)
            profiles = jp_conn.execute(
                """SELECT profile_id, name_label, jsic_major, prefecture,
                          employee_count, capital_yen
                     FROM client_profiles
                    WHERE api_key_hash = ?""",
                (key_hash,),
            ).fetchall()

            for profile in profiles:
                pack_key = _resolve_industry_pack(profile["jsic_major"])
                candidates = _candidate_programs(jp_conn, profile)
                refreshed_at = datetime.now(UTC).isoformat()

                for program in candidates:
                    s_client, client_reason = _client_fit_score(profile, program)
                    s_ind = _industry_pack_score(pack_key, program)
                    s_ss, matched_names = _saved_search_score(saved_search_tokens, program)
                    total = max(0, min(100, s_client + s_ind + s_ss))
                    if total <= 0:
                        continue
                    breakdown = {
                        "client_fit": s_client,
                        "industry_fit": s_ind,
                        "saved_search_fit": s_ss,
                    }
                    reasoning = {
                        "client_fit_reason": client_reason,
                        "saved_searches_matched": matched_names,
                    }
                    if not dry_run:
                        _upsert_score(
                            am_conn,
                            api_key_hash=key_hash,
                            client_id=int(profile["profile_id"]),
                            program_id=program["unified_id"],
                            score=total,
                            breakdown=breakdown,
                            reasoning=reasoning,
                            industry_pack=pack_key,
                            refreshed_at=refreshed_at,
                        )
                    summary["rows_upserted"] += 1
                summary["profiles_scored"] += 1

                if not dry_run:
                    cur = am_conn.execute(
                        """DELETE FROM am_personalization_score
                            WHERE api_key_hash = ? AND client_id = ?
                              AND refreshed_at < ?""",
                        (key_hash, int(profile["profile_id"]), cutoff),
                    )
                    summary["rows_purged"] += int(cur.rowcount or 0)

            if not dry_run:
                am_conn.commit()

        if not dry_run:
            am_conn.execute(
                """INSERT INTO am_personalization_refresh_log(
                        started_at, finished_at, profiles_scored,
                        rows_upserted, rows_purged, errors_count
                   ) VALUES (?,?,?,?,?,?)""",
                (
                    started,
                    datetime.now(UTC).isoformat(),
                    int(summary["profiles_scored"]),
                    int(summary["rows_upserted"]),
                    int(summary["rows_purged"]),
                    int(summary["errors_count"]),
                ),
            )
            am_conn.commit()

        summary["finished_at"] = datetime.now(UTC).isoformat()
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["errors_count"] += 1
        summary["error_text"] = str(exc)[:512]
        logger.exception("refresh_personalization_daily failure")
        summary["finished_at"] = datetime.now(UTC).isoformat()
        return summary
    finally:
        am_conn.close()
        jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily personalization score refresh")
    parser.add_argument("--max-age-days", type=int, default=14)
    parser.add_argument("--limit-keys", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("refresh_personalization_daily") as hb:
        summary = run(
            max_age_days=args.max_age_days,
            limit_keys=args.limit_keys,
            dry_run=args.dry_run,
        )
        hb["rows_processed"] = int(summary.get("rows_upserted") or 0)
        hb["rows_skipped"] = int(summary.get("rows_purged") or 0)
        hb["metadata"] = {
            k: summary[k]
            for k in (
                "profiles_scored",
                "rows_upserted",
                "rows_purged",
                "errors_count",
                "dry_run",
            )
            if k in summary
        }
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if int(summary.get("errors_count") or 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
