#!/usr/bin/env python3
"""Backfill missing ``programs.prefecture`` / ``programs.municipality``.

B13 fixes locality metadata gaps using deterministic evidence only:

* existing municipality -> prefecture via ``data/autonomath/muni_to_prefecture.json``;
* full prefecture names in ``authority_name`` / ``primary_name``;
* conservative official/source URL host mapping;
* reviewed ``prefecture_overrides.json`` rows, excluding authority-level
  nationwide inference.

Existing non-empty locality fields are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
MUNI_TO_PREF = REPO_ROOT / "data" / "autonomath" / "muni_to_prefecture.json"
PREF_OVERRIDES = REPO_ROOT / "data" / "autonomath" / "prefecture_overrides.json"

PREFECTURES: tuple[tuple[str, str, str], ...] = (
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
PREF_BY_ROMAJI = {romaji: canonical for canonical, _short, romaji in PREFECTURES}
PREF_CANONICAL = {canonical for canonical, _short, _romaji in PREFECTURES}


@dataclass(frozen=True)
class LocalityUpdate:
    unified_id: str
    prefecture: str | None
    municipality: str | None
    pref_method: str | None
    muni_method: str | None
    evidence: str


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_municipality_maps(path: Path = MUNI_TO_PREF) -> tuple[dict[str, str], list[str]]:
    raw = _load_json(path)
    muni_to_pref: dict[str, str] = {}
    for pref, municipalities in raw.items():
        if pref not in PREF_CANONICAL:
            continue
        for municipality in municipalities:
            name = str(municipality).strip()
            if name:
                muni_to_pref[name] = pref
    muni_names = sorted(muni_to_pref, key=len, reverse=True)
    return muni_to_pref, muni_names


def load_prefecture_overrides(path: Path = PREF_OVERRIDES) -> dict[str, dict[str, Any]]:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    return {str(uid): value for uid, value in raw.items() if isinstance(value, dict)}


def extract_municipality_from_text(
    text: str | None,
    *,
    municipality_names: list[str],
) -> str | None:
    if not text:
        return None
    hits = [name for name in municipality_names if name in text]
    if not hits:
        return None
    top_len = len(hits[0])
    top = [name for name in hits if len(name) == top_len]
    return top[0] if len(top) == 1 else None


def extract_prefecture_from_text(text: str | None) -> str | None:
    if not text:
        return None
    hits = [pref for pref in PREF_CANONICAL if pref in text]
    return hits[0] if len(hits) == 1 else None


def extract_prefecture_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return None
    host = host.lower()
    labels = host.split(".")
    for idx, label in enumerate(labels):
        if label == "pref" and idx + 1 < len(labels):
            pref = PREF_BY_ROMAJI.get(labels[idx + 1])
            if pref:
                return pref
    for romaji, pref in PREF_BY_ROMAJI.items():
        if host.endswith(f".{romaji}.jp") or f".{romaji}." in host:
            return pref
    return None


def _override_prefecture(
    unified_id: str,
    overrides: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    row = overrides.get(unified_id)
    if not row:
        return None, None
    if str(row.get("source") or "") == "authority_level":
        return None, None
    try:
        confidence = float(row.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    pref = str(row.get("prefecture") or "")
    if confidence < 0.9 or pref not in PREF_CANONICAL:
        return None, None
    return pref, str(row.get("evidence") or "prefecture_overrides")


def resolve_locality_update(
    row: sqlite3.Row,
    *,
    muni_to_pref: dict[str, str],
    municipality_names: list[str],
    overrides: dict[str, dict[str, Any]],
) -> LocalityUpdate | None:
    unified_id = str(row["unified_id"])
    primary_name = str(row["primary_name"] or "")
    authority_name = str(row["authority_name"] or "")
    old_pref = None if _blank(row["prefecture"]) else str(row["prefecture"])
    old_muni = None if _blank(row["municipality"]) else str(row["municipality"])
    new_pref = old_pref
    new_muni = old_muni
    pref_method: str | None = None
    muni_method: str | None = None
    evidence_parts: list[str] = []

    if new_muni is None:
        found_muni = extract_municipality_from_text(
            primary_name,
            municipality_names=municipality_names,
        )
        if found_muni:
            new_muni = found_muni
            muni_method = "primary_name_municipality"
            evidence_parts.append(f"municipality={found_muni}")

    if new_pref is None and new_muni in muni_to_pref:
        new_pref = muni_to_pref[new_muni]
        pref_method = "municipality_lookup"
        evidence_parts.append(f"municipality={new_muni}")

    if new_pref is None:
        pref = extract_prefecture_from_text(authority_name)
        if pref:
            new_pref = pref
            pref_method = "authority_name_prefecture"
            evidence_parts.append(f"authority_name={authority_name}")

    if new_pref is None:
        pref = extract_prefecture_from_text(primary_name)
        if pref:
            new_pref = pref
            pref_method = "primary_name_prefecture"
            evidence_parts.append(f"primary_name={primary_name}")

    if new_pref is None:
        for field in ("official_url", "source_url"):
            pref = extract_prefecture_from_url(row[field])
            if pref:
                new_pref = pref
                pref_method = f"{field}_host"
                evidence_parts.append(f"{field}={row[field]}")
                break

    if new_pref is None:
        pref, evidence = _override_prefecture(unified_id, overrides)
        if pref:
            new_pref = pref
            pref_method = "prefecture_override"
            evidence_parts.append(evidence or "prefecture_override")

    if new_pref == old_pref and new_muni == old_muni:
        return None
    return LocalityUpdate(
        unified_id=unified_id,
        prefecture=new_pref if new_pref != old_pref else None,
        municipality=new_muni if new_muni != old_muni else None,
        pref_method=pref_method if new_pref != old_pref else None,
        muni_method=muni_method if new_muni != old_muni else None,
        evidence="; ".join(evidence_parts),
    )


def collect_locality_updates(
    conn: sqlite3.Connection,
    *,
    muni_to_pref: dict[str, str],
    municipality_names: list[str],
    overrides: dict[str, dict[str, Any]],
) -> list[LocalityUpdate]:
    rows = conn.execute(
        """SELECT unified_id, primary_name, authority_name, prefecture, municipality,
                  official_url, source_url
             FROM programs
            WHERE COALESCE(TRIM(prefecture), '') = ''
               OR COALESCE(TRIM(municipality), '') = ''
         ORDER BY unified_id"""
    )
    updates: list[LocalityUpdate] = []
    for row in rows:
        update = resolve_locality_update(
            row,
            muni_to_pref=muni_to_pref,
            municipality_names=municipality_names,
            overrides=overrides,
        )
        if update is not None:
            updates.append(update)
    return updates


def apply_locality_updates(conn: sqlite3.Connection, updates: list[LocalityUpdate]) -> int:
    updated = 0
    for update in updates:
        sets: list[str] = []
        params: list[Any] = []
        if update.prefecture is not None:
            sets.append("prefecture = ?")
            params.append(update.prefecture)
        if update.municipality is not None:
            sets.append("municipality = ?")
            params.append(update.municipality)
        if not sets:
            continue
        params.append(update.unified_id)
        cur = conn.execute(
            f"UPDATE programs SET {', '.join(sets)} WHERE unified_id = ?",
            params,
        )
        updated += cur.rowcount
    return updated


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(COALESCE(TRIM(prefecture), '') = '') AS missing_prefecture,
                  SUM(COALESCE(TRIM(municipality), '') = '') AS missing_municipality
             FROM programs"""
    ).fetchone()
    return {
        "total": int(row["total"]),
        "missing_prefecture": int(row["missing_prefecture"]),
        "missing_municipality": int(row["missing_municipality"]),
    }


def backfill_program_locality(
    conn: sqlite3.Connection,
    *,
    apply: bool,
    muni_to_pref_path: Path = MUNI_TO_PREF,
    overrides_path: Path = PREF_OVERRIDES,
) -> dict[str, Any]:
    before = _counts(conn)
    muni_to_pref, municipality_names = load_municipality_maps(muni_to_pref_path)
    overrides = load_prefecture_overrides(overrides_path)
    updates = collect_locality_updates(
        conn,
        muni_to_pref=muni_to_pref,
        municipality_names=municipality_names,
        overrides=overrides,
    )
    pref_methods = Counter(update.pref_method for update in updates if update.pref_method)
    muni_methods = Counter(update.muni_method for update in updates if update.muni_method)
    updated_rows = 0
    if apply:
        with conn:
            updated_rows = apply_locality_updates(conn, updates)
    after = _counts(conn)
    return {
        "mode": "apply" if apply else "dry_run",
        "before": before,
        "candidate_updates": len(updates),
        "updated_rows": updated_rows,
        "after": after,
        "prefecture_method_counts": dict(sorted(pref_methods.items())),
        "municipality_method_counts": dict(sorted(muni_methods.items())),
        "sample_updates": [asdict(update) for update in updates[:10]],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--muni-to-pref", type=Path, default=MUNI_TO_PREF)
    parser.add_argument("--prefecture-overrides", type=Path, default=PREF_OVERRIDES)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_program_locality(
            conn,
            apply=args.apply,
            muni_to_pref_path=args.muni_to_pref,
            overrides_path=args.prefecture_overrides,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"missing_prefecture: {result['before']['missing_prefecture']} -> {result['after']['missing_prefecture']}"
        )
        print(
            f"missing_municipality: {result['before']['missing_municipality']} -> {result['after']['missing_municipality']}"
        )
        print(f"candidate_updates={result['candidate_updates']}")
        print(f"updated_rows={result['updated_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
