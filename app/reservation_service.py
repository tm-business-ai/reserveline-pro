"""Reservation and menu business logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Any, Callable
import csv
from io import StringIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database import get_connection, init_db
from app.settings import Settings, get_settings

VALID_STATUSES = {"reserved", "confirmed", "pending", "completed", "cancelled", "no_show"}
CONFLICT_STATUSES = {"reserved", "confirmed", "pending"}
STATUS_LABELS = {
    "reserved": "予約中",
    "confirmed": "確定",
    "pending": "仮予約",
    "completed": "完了",
    "cancelled": "キャンセル",
    "no_show": "無断キャンセル",
}
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEMO_RESERVATION_NOTE = "動作確認用サンプル予約"


@dataclass
class ReservationInput:
    customer_name: str
    line_user_id: str
    menu: str
    reservation_datetime: datetime
    notes: str = ""


class ReservationService:
    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = db_path
        self.settings = settings or get_settings()
        self.now_provider = now_provider
        init_db(self.db_path)

    def create_reservation(self, data: ReservationInput) -> dict[str, Any]:
        if not data.customer_name.strip():
            raise ValueError("顧客名が空です。")
        if not data.line_user_id.strip():
            raise ValueError("LINEユーザーIDが空です。")
        if not self.menu_exists(data.menu):
            raise ValueError(f"メニューが見つかりません: {data.menu}")
        self.validate_reservation_datetime(data.reservation_datetime)
        if self.has_conflicting_reservation(data.reservation_datetime):
            raise ValueError("申し訳ありません。その日時はすでに予約が入っています。別の日時をお選びください。")

        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO reservations
                    (customer_name, line_user_id, menu, reservation_datetime, status, notes)
                VALUES (?, ?, ?, ?, 'reserved', ?)
                """,
                (
                    data.customer_name.strip(),
                    data.line_user_id.strip(),
                    data.menu.strip(),
                    data.reservation_datetime.isoformat(timespec="minutes"),
                    data.notes.strip(),
                ),
            )
            reservation_id = cur.lastrowid
        return self.get_reservation(reservation_id)

    def validate_reservation_datetime(self, reservation_dt: datetime) -> None:
        now = self._now()
        target = self._as_business_timezone(reservation_dt)
        if target <= now:
            raise ValueError("過去の日時は予約できません。現在以降の日時を指定してください。")

        weekday = WEEKDAY_KEYS[target.weekday()]
        if weekday not in self.settings.business_days:
            raise ValueError("その曜日は定休日です。別の日付を指定してください。")

        reservation_time = target.time().replace(second=0, microsecond=0)
        if not (self.settings.business_open_time <= reservation_time < self.settings.business_close_time):
            raise ValueError(
                "営業時間外です。予約可能時間は "
                f"{self.settings.business_open_time:%H:%M}〜{self.settings.business_close_time:%H:%M} です。"
            )

    def has_conflicting_reservation(self, reservation_dt: datetime) -> bool:
        with get_connection(self.db_path) as conn:
            placeholders = ",".join("?" for _ in CONFLICT_STATUSES)
            row = conn.execute(
                f"""
                SELECT id FROM reservations
                WHERE reservation_datetime = ?
                  AND status IN ({placeholders})
                LIMIT 1
                """,
                (reservation_dt.isoformat(timespec="minutes"), *sorted(CONFLICT_STATUSES)),
            ).fetchone()
        return row is not None

    def get_reservation(self, reservation_id: int) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if row is None:
            raise ValueError(f"予約が見つかりません: {reservation_id}")
        return dict(row)

    def list_reservations(
        self,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM reservations WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if start_date:
            start_dt = self._date_to_start_datetime(start_date)
            sql += " AND reservation_datetime >= ?"
            params.append(start_dt.isoformat(timespec="minutes"))
        if end_date:
            end_dt = self._date_to_end_datetime(end_date)
            sql += " AND reservation_datetime <= ?"
            params.append(end_dt.isoformat(timespec="minutes"))
        sql += " ORDER BY reservation_datetime ASC, id ASC"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_today(self) -> list[dict[str, Any]]:
        today = date.today()
        return self.list_reservations(start_date=today, end_date=today)

    def list_this_week(self) -> list[dict[str, Any]]:
        today = date.today()
        end = today + timedelta(days=6)
        return self.list_reservations(start_date=today, end_date=end)

    def update_status(self, reservation_id: int, status: str) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError(f"不正なステータスです: {status}")
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE reservations
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, reservation_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"予約が見つかりません: {reservation_id}")
        return self.get_reservation(reservation_id)

    def cancel_latest_reservation(self, line_user_id: str) -> dict[str, Any] | None:
        now = datetime.now().isoformat(timespec="minutes")
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM reservations
                WHERE line_user_id = ?
                  AND status = 'reserved'
                  AND reservation_datetime >= ?
                ORDER BY reservation_datetime ASC
                LIMIT 1
                """,
                (line_user_id, now),
            ).fetchone()
            if row is None:
                return None
            reservation_id = int(row["id"])
            conn.execute(
                """
                UPDATE reservations
                SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (reservation_id,),
            )
        return self.get_reservation(reservation_id)

    def get_latest_upcoming_reservation(self, line_user_id: str) -> dict[str, Any] | None:
        now = datetime.now().isoformat(timespec="minutes")
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM reservations
                WHERE line_user_id = ?
                  AND status = 'reserved'
                  AND reservation_datetime >= ?
                ORDER BY reservation_datetime ASC
                LIMIT 1
                """,
                (line_user_id, now),
            ).fetchone()
        return dict(row) if row else None

    def get_due_reminders(self, now: datetime, hours_before: int = 24) -> list[dict[str, Any]]:
        until = now + timedelta(hours=hours_before)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM reservations
                WHERE status = 'reserved'
                  AND reminder_sent = 0
                  AND reservation_datetime >= ?
                  AND reservation_datetime <= ?
                ORDER BY reservation_datetime ASC
                """,
                (now.isoformat(timespec="minutes"), until.isoformat(timespec="minutes")),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_reminder_sent(self, reservation_id: int) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE reservations
                SET reminder_sent = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (reservation_id,),
            )

    def create_demo_reservations(self) -> dict[str, list[dict[str, Any]]]:
        """Create sample reservations without duplicating existing sample rows."""
        demo_specs = [
            ("サンプル太郎", "sample-user-001", "30分相談", 0),
            ("サンプル花子", "sample-user-002", "60分相談", 1),
            ("サンプル一郎", "sample-user-003", "初回カウンセリング", 2),
        ]
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for customer_name, line_user_id, menu, slot_index in demo_specs:
            existing = self._find_existing_demo_reservation(line_user_id, menu)
            if existing is not None:
                skipped.append(existing)
                continue

            reservation_dt = self._find_available_demo_datetime(slot_index)
            created.append(
                self.create_reservation(
                    ReservationInput(
                        customer_name=customer_name,
                        line_user_id=line_user_id,
                        menu=menu,
                        reservation_datetime=reservation_dt,
                        notes=DEMO_RESERVATION_NOTE,
                    )
                )
            )
        return {"created": created, "skipped": skipped}

    def export_csv(self, reservations: list[dict[str, Any]] | None = None) -> str:
        reservations = reservations if reservations is not None else self.list_reservations()
        output = StringIO()
        fieldnames = [
            "id",
            "customer_name",
            "line_user_id",
            "menu",
            "reservation_datetime",
            "status",
            "notes",
            "reminder_sent",
            "created_at",
            "updated_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reservations)
        return output.getvalue()

    def export_csv_japanese(self, reservations: list[dict[str, Any]] | None = None) -> str:
        reservations = reservations if reservations is not None else self.list_reservations()
        output = StringIO()
        field_map = [
            ("id", "予約ID"),
            ("customer_name", "顧客名"),
            ("line_user_id", "LINEユーザーID"),
            ("menu", "メニュー"),
            ("reservation_datetime", "予約日時"),
            ("status", "予約状態"),
            ("notes", "備考"),
            ("reminder_sent", "予約前のお知らせ済み"),
            ("created_at", "登録日時"),
            ("updated_at", "更新日時"),
        ]
        writer = csv.DictWriter(output, fieldnames=[label for _, label in field_map])
        writer.writeheader()
        for reservation in reservations:
            writer.writerow(
                {
                    label: STATUS_LABELS.get(reservation.get(key), reservation.get(key, ""))
                    if key == "status"
                    else "送信済み"
                    if key == "reminder_sent" and bool(reservation.get(key))
                    else "未送信"
                    if key == "reminder_sent"
                    else reservation.get(key, "")
                    for key, label in field_map
                }
            )
        return output.getvalue()

    def _find_existing_demo_reservation(self, line_user_id: str, menu: str) -> dict[str, Any] | None:
        now = self._now().isoformat(timespec="minutes")
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM reservations
                WHERE line_user_id = ?
                  AND menu = ?
                  AND notes = ?
                  AND status IN ('reserved', 'confirmed', 'pending')
                  AND reservation_datetime >= ?
                ORDER BY reservation_datetime ASC
                LIMIT 1
                """,
                (line_user_id, menu, DEMO_RESERVATION_NOTE, now),
            ).fetchone()
        return dict(row) if row else None

    def _find_available_demo_datetime(self, slot_index: int) -> datetime:
        open_time = self.settings.business_open_time
        candidate_time = time(
            min(open_time.hour + 1 + (slot_index * 2), 23),
            open_time.minute,
        )
        if candidate_time >= self.settings.business_close_time:
            candidate_time = open_time

        start_date = self._now().date()
        for day_offset in range(0, 30):
            candidate_date = start_date + timedelta(days=day_offset)
            if WEEKDAY_KEYS[candidate_date.weekday()] not in self.settings.business_days:
                continue
            candidate_dt = datetime.combine(candidate_date, candidate_time)
            if candidate_dt <= self._now().replace(tzinfo=None):
                continue
            if not self.has_conflicting_reservation(candidate_dt):
                return candidate_dt
        raise ValueError("サンプル予約を作成できる空き日時が見つかりませんでした。")

    def list_menus(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM menus"
        params: list[Any] = []
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY display_order ASC, id ASC"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def menu_exists(self, name: str) -> bool:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM menus WHERE name = ? AND active = 1",
                (name.strip(),),
            ).fetchone()
        return row is not None

    def upsert_menu(
        self,
        name: str,
        duration_minutes: int = 60,
        price: int = 0,
        active: bool = True,
        display_order: int = 0,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("メニュー名が空です。")
        if duration_minutes <= 0:
            raise ValueError("メニュー時間は1分以上で入力してください。")
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO menus (name, duration_minutes, price, active, display_order)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    duration_minutes = excluded.duration_minutes,
                    price = excluded.price,
                    active = excluded.active,
                    display_order = excluded.display_order,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (clean_name, duration_minutes, price, int(active), display_order),
            )
            row = conn.execute("SELECT * FROM menus WHERE name = ?", (clean_name,)).fetchone()
        return dict(row)

    @staticmethod
    def _date_to_start_datetime(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.combine(value, datetime.min.time())

    @staticmethod
    def _date_to_end_datetime(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.combine(value, datetime.max.time()).replace(microsecond=0)

    def _now(self) -> datetime:
        current = self.now_provider() if self.now_provider else datetime.now(self._business_zone())
        return self._as_business_timezone(current)

    def _as_business_timezone(self, value: datetime) -> datetime:
        zone = self._business_zone()
        if value.tzinfo is None:
            return value.replace(tzinfo=zone)
        return value.astimezone(zone)

    def _business_zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.settings.business_timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
