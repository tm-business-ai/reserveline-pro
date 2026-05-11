"""Application settings for ReserveLine Pro.

All secrets are read from environment variables or .env files.
Do not hard-code LINE tokens or other private values in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps tests runnable before installing deps
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_time(value: str | None, default: str) -> time:
    source = value or default
    try:
        hour_text, minute_text = source.split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        fallback_hour, fallback_minute = default.split(":", 1)
        return time(int(fallback_hour), int(fallback_minute))


def _to_business_days(value: str | None) -> tuple[str, ...]:
    source = value or "mon,tue,wed,thu,fri,sat"
    days = tuple(day.strip().lower() for day in source.split(",") if day.strip())
    return days or ("mon", "tue", "wed", "thu", "fri", "sat")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "ReserveLine Pro")
    demo_mode: bool = _to_bool(os.getenv("DEMO_MODE"), True)
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_channel_secret: str = os.getenv("LINE_CHANNEL_SECRET", "")
    database_path: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "reserveline.db"))
    reminder_hours_before: int = int(os.getenv("REMINDER_HOURS_BEFORE", "24"))
    scheduler_enabled: bool = _to_bool(os.getenv("SCHEDULER_ENABLED"), True)
    business_open_time: time = _to_time(os.getenv("BUSINESS_OPEN_TIME"), "09:00")
    business_close_time: time = _to_time(os.getenv("BUSINESS_CLOSE_TIME"), "18:00")
    business_days: tuple[str, ...] = _to_business_days(os.getenv("BUSINESS_DAYS"))
    business_timezone: str = os.getenv("BUSINESS_TIMEZONE", "Asia/Tokyo")
    slot_interval_minutes: int = int(os.getenv("SLOT_INTERVAL_MINUTES", "30"))
    min_booking_notice_minutes: int = int(os.getenv("MIN_BOOKING_NOTICE_MINUTES", "120"))
    max_booking_days_ahead: int = int(os.getenv("MAX_BOOKING_DAYS_AHEAD", "30"))


def get_settings() -> Settings:
    return Settings()
