"""Reservation, menu, and availability business logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from io import StringIO
from typing import Any, Callable
import csv
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database import get_connection, init_db
from app.settings import Settings, get_settings

VALID_STATUSES = {"reserved", "confirmed", "pending", "completed", "cancelled", "no_show"}
CONFLICT_STATUSES = {"reserved", "confirmed", "pending"}
RESERVATION_SOURCE_LABELS = {
    "line": "LINE",
    "phone": "電話",
    "walk_in": "店頭",
    "admin": "管理画面",
    "other": "その他",
    "": "未設定",
    None: "未設定",
}
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
    customer_phone: str = ""
    reservation_source: str = "admin"
    notes: str = ""


@dataclass(frozen=True)
class ReservationRules:
    business_days: tuple[str, ...]
    open_time: time
    close_time: time
    slot_interval_minutes: int
    min_booking_notice_minutes: int
    max_booking_days_ahead: int
    timezone: str


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
        init_db(self.db_path, self.settings)

    def create_reservation(self, data: ReservationInput) -> dict[str, Any]:
        if not data.customer_name.strip():
            raise ValueError("顧客名が空です。")
        if not self.menu_exists(data.menu):
            raise ValueError(f"メニューが見つかりません: {data.menu}")

        duration_minutes = self.get_menu_duration(data.menu)
        self.validate_reservation_datetime(data.reservation_datetime, duration_minutes)
        if self.has_conflicting_reservation(data.reservation_datetime, duration_minutes):
            raise ValueError("その時間はすでに予約が入っています。別の時間を選んでください。")

        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO reservations
                    (
                        customer_name,
                        line_user_id,
                        customer_phone,
                        reservation_source,
                        menu,
                        reservation_datetime,
                        status,
                        notes
                    )
                VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?)
                """,
                (
                    data.customer_name.strip(),
                    data.line_user_id.strip(),
                    data.customer_phone.strip(),
                    self.normalize_reservation_source(data.reservation_source),
                    data.menu.strip(),
                    data.reservation_datetime.replace(tzinfo=None).isoformat(timespec="minutes"),
                    data.notes.strip(),
                ),
            )
            reservation_id = cur.lastrowid
        return self.get_reservation(reservation_id)

    def validate_reservation_datetime(self, reservation_dt: datetime, duration_minutes: int | None = None) -> None:
        rules = self.get_reservation_rules()
        duration = duration_minutes or 0
        now = self._now_for_rules(rules)
        target = self._as_timezone(reservation_dt, rules.timezone)
        target_naive = target.replace(tzinfo=None)

        if target <= now:
            raise ValueError("過去の日時は予約できません。現在以降の日時を選んでください。")
        if target < now + timedelta(minutes=rules.min_booking_notice_minutes):
            raise ValueError("直前すぎる予約は受け付けできません。別の時間を選んでください。")
        if target.date() > now.date() + timedelta(days=rules.max_booking_days_ahead):
            raise ValueError("予約できる期間を過ぎています。別の日付を選んでください。")
        if not self.is_business_day(target.date(), rules):
            raise ValueError("その日は営業日ではありません。別の日付を選んでください。")
        if self.is_closed_date(target.date()):
            raise ValueError("その日は臨時休業日のため予約できません。")
        if not self.is_within_business_hours(target_naive, duration, rules):
            start_time = target_naive.time().replace(second=0, microsecond=0)
            if start_time < rules.open_time or start_time >= rules.close_time:
                raise ValueError("営業時間外です。別の時間を選んでください。")
            raise ValueError("選択したメニューの所要時間が営業時間内に収まりません。別の時間を選んでください。")

    def has_conflicting_reservation(
        self,
        reservation_dt: datetime,
        duration_minutes: int | None = None,
        exclude_reservation_id: int | None = None,
    ) -> bool:
        start = reservation_dt.replace(tzinfo=None)
        duration = duration_minutes or 0
        end = start + timedelta(minutes=duration)
        with get_connection(self.db_path) as conn:
            placeholders = ",".join("?" for _ in CONFLICT_STATUSES)
            rows = conn.execute(
                f"""
                SELECT id, menu, reservation_datetime FROM reservations
                WHERE status IN ({placeholders})
                  AND (? IS NULL OR id != ?)
                """,
                (*sorted(CONFLICT_STATUSES), exclude_reservation_id, exclude_reservation_id),
            ).fetchall()
        for row in rows:
            existing_start = datetime.fromisoformat(row["reservation_datetime"]).replace(tzinfo=None)
            existing_end = existing_start + timedelta(minutes=self.get_menu_duration(row["menu"]))
            if existing_start < end and start < existing_end:
                return True
        return False

    def get_reservation_rules(self) -> ReservationRules:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM reservation_settings WHERE id = 1").fetchone()
        if row is None:
            init_db(self.db_path, self.settings)
            return self.get_reservation_rules()
        return ReservationRules(
            business_days=tuple(day.strip() for day in row["business_days"].split(",") if day.strip()),
            open_time=self._parse_time(row["open_time"], self.settings.business_open_time),
            close_time=self._parse_time(row["close_time"], self.settings.business_close_time),
            slot_interval_minutes=int(row["slot_interval_minutes"]),
            min_booking_notice_minutes=int(row["min_booking_notice_minutes"]),
            max_booking_days_ahead=int(row["max_booking_days_ahead"]),
            timezone=row["timezone"] or self.settings.business_timezone,
        )

    def update_reservation_rules(
        self,
        business_days: tuple[str, ...] | list[str],
        open_time: time,
        close_time: time,
        slot_interval_minutes: int,
        min_booking_notice_minutes: int,
        max_booking_days_ahead: int,
        timezone: str,
    ) -> ReservationRules:
        clean_days = tuple(day for day in business_days if day in WEEKDAY_KEYS)
        if not clean_days:
            raise ValueError("営業曜日を1つ以上選んでください。")
        if open_time >= close_time:
            raise ValueError("営業終了時刻は営業開始時刻より後にしてください。")
        if slot_interval_minutes <= 0:
            raise ValueError("予約間隔は1分以上で入力してください。")
        if min_booking_notice_minutes < 0:
            raise ValueError("予約受付の締切時間は0分以上で入力してください。")
        if max_booking_days_ahead <= 0:
            raise ValueError("予約可能期間は1日以上で入力してください。")

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE reservation_settings
                SET business_days = ?,
                    open_time = ?,
                    close_time = ?,
                    slot_interval_minutes = ?,
                    min_booking_notice_minutes = ?,
                    max_booking_days_ahead = ?,
                    timezone = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (
                    ",".join(clean_days),
                    open_time.strftime("%H:%M"),
                    close_time.strftime("%H:%M"),
                    int(slot_interval_minutes),
                    int(min_booking_notice_minutes),
                    int(max_booking_days_ahead),
                    timezone.strip() or "Asia/Tokyo",
                ),
            )
        return self.get_reservation_rules()

    def add_closed_date(self, closed_date: date, reason: str = "", active: bool = True) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO closed_dates (closed_date, reason, active)
                VALUES (?, ?, ?)
                """,
                (closed_date.isoformat(), reason.strip(), int(active)),
            )
            row = conn.execute("SELECT * FROM closed_dates WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def delete_closed_date(self, closed_date_id: int) -> None:
        with get_connection(self.db_path) as conn:
            cur = conn.execute("DELETE FROM closed_dates WHERE id = ?", (closed_date_id,))
            if cur.rowcount == 0:
                raise ValueError(f"臨時休業日が見つかりません: {closed_date_id}")

    def list_closed_dates(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM closed_dates"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY closed_date ASC, id ASC"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def update_closed_date_status(self, closed_date_id: int, active: bool) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE closed_dates
                SET active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(active), closed_date_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"臨時休業日が見つかりません: {closed_date_id}")
            row = conn.execute("SELECT * FROM closed_dates WHERE id = ?", (closed_date_id,)).fetchone()
        return dict(row)

    def is_business_day(self, target_date: date, rules: ReservationRules | None = None) -> bool:
        rules = rules or self.get_reservation_rules()
        return WEEKDAY_KEYS[target_date.weekday()] in rules.business_days

    def is_closed_date(self, target_date: date) -> bool:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id FROM closed_dates
                WHERE closed_date = ? AND active = 1
                LIMIT 1
                """,
                (target_date.isoformat(),),
            ).fetchone()
        return row is not None

    def is_within_business_hours(
        self,
        reservation_dt: datetime,
        duration_minutes: int,
        rules: ReservationRules | None = None,
    ) -> bool:
        rules = rules or self.get_reservation_rules()
        start_time = reservation_dt.time().replace(second=0, microsecond=0)
        end_dt = reservation_dt + timedelta(minutes=duration_minutes)
        if end_dt.date() != reservation_dt.date():
            return False
        end_time = end_dt.time().replace(second=0, microsecond=0)
        return rules.open_time <= start_time and end_time <= rules.close_time

    def list_available_slots(self, target_date: date, menu_name: str) -> list[str]:
        if not self.menu_exists(menu_name):
            raise ValueError(f"メニューが見つかりません: {menu_name}")
        rules = self.get_reservation_rules()
        if not self.is_business_day(target_date, rules) or self.is_closed_date(target_date):
            return []

        duration = self.get_menu_duration(menu_name)
        now = self._now_for_rules(rules)
        if target_date > now.date() + timedelta(days=rules.max_booking_days_ahead):
            return []

        slots: list[str] = []
        current = datetime.combine(target_date, rules.open_time)
        close_dt = datetime.combine(target_date, rules.close_time)
        while current + timedelta(minutes=duration) <= close_dt:
            aware_current = self._as_timezone(current, rules.timezone)
            earliest = now + timedelta(minutes=rules.min_booking_notice_minutes)
            starts_after_notice = aware_current > earliest if rules.min_booking_notice_minutes == 0 else aware_current >= earliest
            if starts_after_notice and not self.has_conflicting_reservation(current, duration):
                slots.append(current.strftime("%H:%M"))
            current += timedelta(minutes=rules.slot_interval_minutes)
        return slots

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

    def find_future_reservations_for_customer(
        self,
        *,
        line_user_id: str = "",
        customer_phone: str = "",
        customer_name: str = "",
        exclude_reservation_id: int | None = None,
    ) -> list[dict[str, Any]]:
        key_column = ""
        key_value = ""
        if line_user_id.strip():
            key_column = "line_user_id"
            key_value = line_user_id.strip()
        elif customer_phone.strip():
            key_column = "customer_phone"
            key_value = customer_phone.strip()
        elif customer_name.strip():
            key_column = "customer_name"
            key_value = customer_name.strip()
        else:
            return []

        now = self._now().replace(tzinfo=None).isoformat(timespec="minutes")
        placeholders = ",".join("?" for _ in CONFLICT_STATUSES)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM reservations
                WHERE {key_column} = ?
                  AND status IN ({placeholders})
                  AND reservation_datetime >= ?
                  AND (? IS NULL OR id != ?)
                ORDER BY reservation_datetime ASC, id ASC
                """,
                (
                    key_value,
                    *sorted(CONFLICT_STATUSES),
                    now,
                    exclude_reservation_id,
                    exclude_reservation_id,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_today(self) -> list[dict[str, Any]]:
        today = self._now().date()
        return self.list_reservations(start_date=today, end_date=today)

    def list_this_week(self) -> list[dict[str, Any]]:
        today = self._now().date()
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
        now = self._now().replace(tzinfo=None).isoformat(timespec="minutes")
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
        now = self._now().replace(tzinfo=None).isoformat(timespec="minutes")
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

            reservation_dt = self._find_available_demo_datetime(menu, slot_index)
            created.append(
                self.create_reservation(
                    ReservationInput(
                        customer_name=customer_name,
                        line_user_id=line_user_id,
                        menu=menu,
                        reservation_datetime=reservation_dt,
                        reservation_source="line",
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
            "customer_phone",
            "reservation_source",
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
            ("customer_phone", "電話番号"),
            ("reservation_source", "予約経路"),
            ("menu", "メニュー"),
            ("reservation_datetime", "予約日時"),
            ("status", "予約状態"),
            ("notes", "備考"),
            ("reminder_sent", "予約前のお知らせ送信済み"),
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
                    else self.format_reservation_source(reservation.get(key))
                    if key == "reservation_source"
                    else "送信済み"
                    if key == "reminder_sent" and bool(reservation.get(key))
                    else "未送信"
                    if key == "reminder_sent"
                    else reservation.get(key, "")
                    for key, label in field_map
                }
            )
        return output.getvalue()

    def format_reservation_source(self, source: object) -> str:
        return RESERVATION_SOURCE_LABELS.get(source, str(source) if source else "未設定")

    def normalize_reservation_source(self, source: str) -> str:
        clean_source = (source or "").strip()
        return clean_source if clean_source in RESERVATION_SOURCE_LABELS and clean_source else "admin"

    def format_reservation_option(self, reservation: dict[str, Any]) -> str:
        status = STATUS_LABELS.get(reservation.get("status"), str(reservation.get("status", "")))
        source = self.format_reservation_source(reservation.get("reservation_source"))
        reservation_dt = str(reservation.get("reservation_datetime", "")).replace("T", " ")
        return (
            f"#{reservation.get('id')}｜{reservation_dt}｜{reservation.get('customer_name', '')}"
            f"｜{reservation.get('menu', '')}｜{status}｜{source}"
        )

    def list_menus(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM menus"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY display_order ASC, id ASC"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def get_menu(self, name: str) -> dict[str, Any]:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM menus WHERE name = ? AND active = 1",
                (name.strip(),),
            ).fetchone()
        if row is None:
            raise ValueError(f"メニューが見つかりません: {name}")
        return dict(row)

    def get_menu_duration(self, name: str) -> int:
        return int(self.get_menu(name)["duration_minutes"])

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

    def _find_existing_demo_reservation(self, line_user_id: str, menu: str) -> dict[str, Any] | None:
        now = self._now().replace(tzinfo=None).isoformat(timespec="minutes")
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

    def _find_available_demo_datetime(self, menu: str, slot_index: int) -> datetime:
        rules = self.get_reservation_rules()
        start_date = self._now_for_rules(rules).date()
        for day_offset in range(0, min(rules.max_booking_days_ahead, 30) + 1):
            candidate_date = start_date + timedelta(days=day_offset)
            slots = self.list_available_slots(candidate_date, menu)
            if len(slots) > slot_index:
                return datetime.combine(candidate_date, datetime.strptime(slots[slot_index], "%H:%M").time())
            if slots:
                return datetime.combine(candidate_date, datetime.strptime(slots[0], "%H:%M").time())
        raise ValueError("サンプル予約を作成できる空き日時が見つかりませんでした。")

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

    @staticmethod
    def _parse_time(value: str, default: time) -> time:
        try:
            hour_text, minute_text = value.split(":", 1)
            return time(int(hour_text), int(minute_text))
        except (AttributeError, TypeError, ValueError):
            return default

    def _now(self) -> datetime:
        current = self.now_provider() if self.now_provider else datetime.now(self._business_zone())
        return self._as_business_timezone(current)

    def _now_for_rules(self, rules: ReservationRules) -> datetime:
        current = self.now_provider() if self.now_provider else datetime.now(self._zone_for_name(rules.timezone))
        return self._as_timezone(current, rules.timezone)

    def _as_business_timezone(self, value: datetime) -> datetime:
        return self._as_timezone(value, self.settings.business_timezone)

    def _as_timezone(self, value: datetime, timezone: str) -> datetime:
        zone = self._zone_for_name(timezone)
        if value.tzinfo is None:
            return value.replace(tzinfo=zone)
        return value.astimezone(zone)

    def _business_zone(self) -> ZoneInfo:
        return self._zone_for_name(self.settings.business_timezone)

    @staticmethod
    def _zone_for_name(timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
