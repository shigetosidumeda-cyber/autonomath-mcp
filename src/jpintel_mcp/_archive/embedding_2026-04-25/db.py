"""sqlite-vec DB bootstrap for AutonoMath embeddings."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from .config import DB_PATH, EMBED_DIM, SCHEMA_PATH





# --- AUTO: SCHEMA_GUARD_BLOCK (Wave 10 infra hardening) ---
import sys as _sg_sys
from pathlib import Path as _sg_Path
_sg_sys.path.insert(0, str(_sg_Path(__file__).resolve().parent.parent))
try:
    from scripts.schema_guard import assert_am_entities_schema as _sg_check
except Exception:  # pragma: no cover - schema_guard must exist in prod
    _sg_check = None
if __name__ == "__main__" and _sg_check is not None:
    _sg_check("/tmp/autonomath_infra_2026-04-24/autonomath.db")
# --- END SCHEMA_GUARD_BLOCK ---

def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a sqlite3 connection with sqlite-vec loaded."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    # PRAGMA tuning for bulk insert safety.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def apply_schema(conn: sqlite3.Connection, embed_dim: int = EMBED_DIM) -> None:
    """Materialise schema.sql with EMBED_DIM template substitution."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8").replace(
        "{EMBED_DIM}", str(embed_dim)
    )
    conn.executescript(sql)
    conn.commit()


def probe_vec_version(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT vec_version()")
    return cur.fetchone()[0]
