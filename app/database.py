"""SQLite database helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from app.settings import get_settings


def get_db_path(db_path: str | None = None) -> str:
    path = db_path or get_settings().database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_db_path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Create tables and default menus if they do not exist."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                line_user_id TEXT NOT NULL,
                menu TEXT NOT NULL,
                reservation_datetime TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'reserved',
                notes TEXT DEFAULT '',
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS menus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                duration_minutes INTEGER NOT NULL DEFAULT 60,
                price INTEGER DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM menus").fetchone()["c"]
        if count == 0:
            default_menus = [
                ("30分相談", 30, 0, 1, 1),
                ("60分相談", 60, 0, 1, 2),
                ("初回カウンセリング", 90, 0, 1, 3),
            ]
            conn.executemany(
                """
                INSERT INTO menus (name, duration_minutes, price, active, display_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                default_menus,
            )
