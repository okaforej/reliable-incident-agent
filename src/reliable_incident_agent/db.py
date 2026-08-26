"""SQLite database setup for deterministic incident replays."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "var" / "replays.sqlite"
SEED_PATH = ROOT / "data" / "seeds" / "checkout_db_pool_exhaustion.sql"


def get_engine(db_path: Optional[Path] = None) -> Engine:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def init_db(db_path: Optional[Path] = None, seed_path: Optional[Path] = None) -> Path:
    path = db_path or DB_PATH
    seed = seed_path or SEED_PATH
    engine = get_engine(path)
    sql = seed.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        raw.executescript(sql)
        raw.commit()
    finally:
        raw.close()
    return path


def init_db_if_missing(
    db_path: Optional[Path] = None,
    seed_path: Optional[Path] = None,
) -> Path:
    """Seed a new local database while preserving any existing run history."""

    path = db_path or DB_PATH
    if path.exists():
        return path
    return init_db(path, seed_path)


if __name__ == "__main__":
    created = init_db()
    print(created)
