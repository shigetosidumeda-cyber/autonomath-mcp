from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_program_locality_metadata as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            official_url TEXT,
            source_url TEXT
        );
        """
    )
    return conn


def _write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_extract_prefecture_from_url_pref_host() -> None:
    assert backfill.extract_prefecture_from_url("https://www.pref.aichi.jp/soshiki/") == "愛知県"
    assert (
        backfill.extract_prefecture_from_url("https://www.city.akiruno.tokyo.jp/0001.html")
        == "東京都"
    )


def test_backfill_uses_existing_municipality_without_overwrite(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "UNI-1",
            "南相馬市中小企業賃上げ緊急一時支援金",
            "",
            None,
            "南相馬市",
            "",
            "",
        ),
    )
    muni = _write_json(tmp_path / "muni.json", {"福島県": ["南相馬市"]})
    overrides = _write_json(tmp_path / "overrides.json", {})

    result = backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert result["updated_rows"] == 1
    row = conn.execute("SELECT prefecture, municipality FROM programs").fetchone()
    assert row["prefecture"] == "福島県"
    assert row["municipality"] == "南相馬市"


def test_backfill_can_extract_municipality_from_primary_name(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "朝倉市新規就農者営農支援補助金", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {"福岡県": ["朝倉市"]})
    overrides = _write_json(tmp_path / "overrides.json", {})

    backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    row = conn.execute("SELECT prefecture, municipality FROM programs").fetchone()
    assert row["prefecture"] == "福岡県"
    assert row["municipality"] == "朝倉市"


def test_authority_level_override_nationwide_is_skipped(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "全国向け制度", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {})
    overrides = _write_json(
        tmp_path / "overrides.json",
        {
            "UNI-1": {
                "confidence": 1.0,
                "prefecture": "全国",
                "source": "authority_level",
                "evidence": "authority_level=national",
            }
        },
    )

    result = backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert result["updated_rows"] == 0
    assert conn.execute("SELECT prefecture FROM programs").fetchone()[0] is None


def test_non_authority_override_is_allowed(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "地域制度", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {})
    overrides = _write_json(
        tmp_path / "overrides.json",
        {
            "UNI-1": {
                "confidence": 0.95,
                "prefecture": "佐賀県",
                "source": "contact_address",
                "evidence": "contacts.address=佐賀県武雄市",
            }
        },
    )

    backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert conn.execute("SELECT prefecture FROM programs").fetchone()[0] == "佐賀県"


# ---------------------------------------------------------------------------
# R8 GEO REGION API extensions (2026-05-07): URL-path / mined-host muni
# extraction.
# ---------------------------------------------------------------------------


def test_extract_municipality_from_url_path_kanji() -> None:
    """URL path containing a kanji muni name resolves cleanly."""
    names = ["南相馬市", "相馬市"]
    out = backfill.extract_municipality_from_url(
        "https://www.example.jp/南相馬市/sangyo/index.html",
        municipality_names=sorted(names, key=len, reverse=True),
    )
    assert out == "南相馬市"


def test_extract_municipality_from_url_path_percent_encoded() -> None:
    """Percent-encoded paths get decoded before substring matching."""
    names = ["朝倉市"]
    out = backfill.extract_municipality_from_url(
        "https://www.example.jp/%E6%9C%9D%E5%80%89%E5%B8%82/index.html",
        municipality_names=names,
    )
    assert out == "朝倉市"


def test_extract_municipality_from_url_host_via_mined_map() -> None:
    """The mined romaji-host map resolves city.<X>.lg.jp hosts."""
    host_map = {"nasukarasuyama": "那須烏山市", "minamisoma": "南相馬市"}
    out = backfill.extract_municipality_from_url_host(
        "https://www.city.nasukarasuyama.lg.jp/page/page000339.html",
        host_to_municipality=host_map,
    )
    assert out == "那須烏山市"


def test_build_host_to_municipality_dedupes_consistent_pairs(tmp_path: Path) -> None:
    """Mining picks up consistent host→muni pairs and drops collisions."""
    conn = _build_db()
    rows = [
        # 2× rows with the same host → same muni: kept.
        ("UNI-1", "p1", "", "栃木県", "那須烏山市", "https://www.city.nasukarasuyama.lg.jp/a", ""),
        ("UNI-2", "p2", "", "栃木県", "那須烏山市", "https://www.city.nasukarasuyama.lg.jp/b", ""),
        # 1 row → kept.
        ("UNI-3", "p3", "", "福島県", "南相馬市", "https://www.city.minamisoma.lg.jp/x", ""),
        # Conflict on the same host → dropped (would be cross-prefecture).
        ("UNI-4", "p4", "", "A県", "東町", "https://www.town.east.lg.jp/a", ""),
        ("UNI-5", "p5", "", "B県", "西町", "https://www.town.east.lg.jp/b", ""),
    ]
    for r in rows:
        conn.execute("INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)", r)
    out = backfill.build_host_to_municipality(conn)
    assert out["nasukarasuyama"] == "那須烏山市"
    assert out["minamisoma"] == "南相馬市"
    assert "east" not in out


def test_resolve_locality_update_uses_mined_host_map(tmp_path: Path) -> None:
    """End-to-end: mined host map fills both municipality + prefecture."""
    conn = _build_db()
    # Seed one already-canonical row so the mine sees ('nasukarasuyama' →
    # '那須烏山市') with no conflict.
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "UNI-seed",
            "既知制度",
            "",
            "栃木県",
            "那須烏山市",
            "https://www.city.nasukarasuyama.lg.jp/seed",
            "",
        ),
    )
    # Add an unresolved row with the same host but missing pref + muni.
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "UNI-target",
            "対象制度",
            "",
            None,
            None,
            "https://www.city.nasukarasuyama.lg.jp/page/page000339.html",
            "",
        ),
    )
    muni = _write_json(tmp_path / "muni.json", {"栃木県": ["那須烏山市"]})
    overrides = _write_json(tmp_path / "overrides.json", {})

    result = backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )
    assert result["updated_rows"] >= 1
    row = conn.execute(
        "SELECT prefecture, municipality FROM programs WHERE unified_id = ?",
        ("UNI-target",),
    ).fetchone()
    assert row["prefecture"] == "栃木県"
    assert row["municipality"] == "那須烏山市"
