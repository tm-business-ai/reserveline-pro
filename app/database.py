"""SQLite database helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from app.settings import Settings, get_settings


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


def init_db(db_path: str | None = None, settings: Settings | None = None) -> None:
    """Create tables and default menus if they do not exist."""
    settings = settings or get_settings()
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservation_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                business_days TEXT NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                slot_interval_minutes INTEGER NOT NULL DEFAULT 30,
                min_booking_notice_minutes INTEGER NOT NULL DEFAULT 120,
                max_booking_days_ahead INTEGER NOT NULL DEFAULT 30,
                timezone TEXT NOT NULL DEFAULT 'Asia/Tokyo',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS closed_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                closed_date TEXT NOT NULL,
                reason TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        settings_count = conn.execute("SELECT COUNT(*) AS c FROM reservation_settings WHERE id = 1").fetchone()["c"]
        if settings_count == 0:
            conn.execute(
                """
                INSERT INTO reservation_settings (
                    id,
                    business_days,
                    open_time,
                    close_time,
                    slot_interval_minutes,
                    min_booking_notice_minutes,
                    max_booking_days_ahead,
                    timezone
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ",".join(settings.business_days),
                    settings.business_open_time.strftime("%H:%M"),
                    settings.business_close_time.strftime("%H:%M"),
                    settings.slot_interval_minutes,
                    settings.min_booking_notice_minutes,
                    settings.max_booking_days_ahead,
                    settings.business_timezone,
                ),
            )
        default_menus = [
            ("30分相談", 30, 0, 1, 1),
            ("60分相談", 60, 0, 1, 2),
            ("初回カウンセリング", 90, 0, 1, 3),
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO menus (name, duration_minutes, price, active, display_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            default_menus,
        )
