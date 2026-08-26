"""SQLite database setup for deterministic incident replays."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "var" / "replays.sqlite"
SEED_PATH = ROOT / "data" / "seeds" / "checkout_db_pool_exhaustion.sql"


def get_engine(db_path: Path | None = None) -> Engine:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def init_db(db_path: Path | None = None, seed_path: Path | None = None) -> Path:
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


if __name__ == "__main__":
    created = init_db()
    print(created)
