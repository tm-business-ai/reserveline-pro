"""Reminder scheduling and delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from app.reservation_service import ReservationService
from app.settings import Settings, get_settings


def build_reminder_message(reservation: dict) -> str:
    return (
        "ご予約日のリマインドです。\n"
        f"メニュー：{reservation['menu']}\n"
        f"日時：{reservation['reservation_datetime'].replace('T', ' ')}\n"
        "ご来店・ご参加をお待ちしております。"
    )


class ReminderService:
    def __init__(
        self,
        reservation_service: ReservationService | None = None,
        settings: Settings | None = None,
        sender: Callable[[dict, str], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.reservation_service = reservation_service or ReservationService()
        self.sender = sender or self.demo_sender

    def send_due_reminders(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        due = self.reservation_service.get_due_reminders(now, self.settings.reminder_hours_before)
        sent: list[dict] = []
        for reservation in due:
            message = build_reminder_message(reservation)
            self.sender(reservation, message)
            self.reservation_service.mark_reminder_sent(int(reservation["id"]))
            sent.append(reservation)
        return sent

    @staticmethod
    def demo_sender(reservation: dict, message: str) -> None:
        print(f"[DEMO REMINDER] user={reservation['line_user_id']}\n{message}")
