from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.database import get_connection
from app.reservation_service import ReservationInput, ReservationService
from app.reminder_service import ReminderService
from app.settings import Settings


FIXED_NOW = datetime(2026, 5, 11, 9, 0)


def build_test_settings(db_path, min_notice: int = 0, max_days: int = 60) -> Settings:
    return Settings(
        database_path=str(db_path),
        business_open_time=time(9, 0),
        business_close_time=time(18, 0),
        business_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        min_booking_notice_minutes=min_notice,
        max_booking_days_ahead=max_days,
        slot_interval_minutes=30,
    )


def make_service(tmp_path, min_notice: int = 0, max_days: int = 60) -> ReservationService:
    db_path = tmp_path / "test.db"
    return ReservationService(
        str(db_path),
        settings=build_test_settings(db_path, min_notice=min_notice, max_days=max_days),
        now_provider=lambda: FIXED_NOW,
    )


def test_reservation_rule_defaults_are_created(tmp_path):
    service = make_service(tmp_path, min_notice=120, max_days=30)
    rules = service.get_reservation_rules()

    assert rules.business_days == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert rules.open_time == time(9, 0)
    assert rules.close_time == time(18, 0)
    assert rules.slot_interval_minutes == 30
    assert rules.min_booking_notice_minutes == 120
    assert rules.max_booking_days_ahead == 30

    with get_connection(str(tmp_path / "test.db")) as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM reservation_settings").fetchone()["c"] == 1


def test_create_and_cancel_reservation(tmp_path):
    service = make_service(tmp_path)

    reservation = service.create_reservation(
        ReservationInput(
            customer_name="山田太郎",
            line_user_id="user-001",
            menu="30分相談",
            reservation_datetime=FIXED_NOW + timedelta(hours=2),
            notes="初回相談",
        )
    )

    assert reservation["id"] >= 1
    assert reservation["status"] == "reserved"
    assert reservation["customer_name"] == "山田太郎"

    cancelled = service.cancel_latest_reservation("user-001")
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"


def test_list_today_and_csv_export(tmp_path):
    service = make_service(tmp_path)

    service.create_reservation(
        ReservationInput(
            customer_name="佐藤花子",
            line_user_id="user-002",
            menu="60分相談",
            reservation_datetime=FIXED_NOW + timedelta(hours=2),
        )
    )

    today = service.list_today()
    assert len(today) == 1

    csv_text = service.export_csv(today)
    assert "customer_name" in csv_text
    assert "佐藤花子" in csv_text

    japanese_csv = service.export_csv_japanese(today)
    assert "予約ID" in japanese_csv
    assert "顧客名" in japanese_csv


def test_menu_upsert(tmp_path):
    service = make_service(tmp_path)

    menu = service.upsert_menu("90分相談", duration_minutes=90, price=5000, active=True, display_order=4)
    assert menu["name"] == "90分相談"
    assert service.menu_exists("90分相談") is True


def test_business_day_reservation_is_allowed(tmp_path):
    service = make_service(tmp_path)

    reservation = service.create_reservation(
        ReservationInput("山田太郎", "user-001", "30分相談", FIXED_NOW + timedelta(days=1, hours=1))
    )

    assert reservation["status"] == "reserved"


def test_closed_weekday_is_rejected(tmp_path):
    db_path = tmp_path / "test.db"
    settings = Settings(
        database_path=str(db_path),
        business_open_time=time(9, 0),
        business_close_time=time(18, 0),
        business_days=("mon",),
        min_booking_notice_minutes=0,
        max_booking_days_ahead=60,
    )
    service = ReservationService(str(db_path), settings=settings, now_provider=lambda: FIXED_NOW)
    closed_day = datetime(2026, 5, 12, 10, 0)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", closed_day))
    except ValueError as exc:
        assert "営業日ではありません" in str(exc)
    else:
        raise AssertionError("定休日の予約が拒否されませんでした。")


def test_temporary_closed_date_is_rejected(tmp_path):
    service = make_service(tmp_path)
    closed_day = date(2026, 5, 13)
    service.add_closed_date(closed_day, "研修", active=True)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", datetime(2026, 5, 13, 10, 0)))
    except ValueError as exc:
        assert "臨時休業日" in str(exc)
    else:
        raise AssertionError("臨時休業日の予約が拒否されませんでした。")


def test_outside_business_hours_is_rejected(tmp_path):
    service = make_service(tmp_path)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", datetime(2026, 5, 13, 18, 0)))
    except ValueError as exc:
        assert "営業時間外です" in str(exc)
    else:
        raise AssertionError("営業時間外の予約が拒否されませんでした。")


def test_menu_duration_must_fit_within_business_hours(tmp_path):
    service = make_service(tmp_path)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "60分相談", datetime(2026, 5, 13, 17, 30)))
    except ValueError as exc:
        assert "所要時間が営業時間内に収まりません" in str(exc)
    else:
        raise AssertionError("営業時間を超える予約が拒否されませんでした。")


def test_duplicate_start_time_is_rejected(tmp_path):
    service = make_service(tmp_path)
    target = datetime(2026, 5, 13, 10, 0)
    service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", target))

    try:
        service.create_reservation(ReservationInput("佐藤花子", "user-002", "60分相談", target))
    except ValueError as exc:
        assert "すでに予約が入っています" in str(exc)
    else:
        raise AssertionError("同じ開始時刻の重複予約が拒否されませんでした。")


def test_overlapping_time_range_is_rejected(tmp_path):
    service = make_service(tmp_path)
    service.create_reservation(ReservationInput("山田太郎", "user-001", "60分相談", datetime(2026, 5, 13, 10, 0)))

    try:
        service.create_reservation(ReservationInput("佐藤花子", "user-002", "30分相談", datetime(2026, 5, 13, 10, 30)))
    except ValueError as exc:
        assert "すでに予約が入っています" in str(exc)
    else:
        raise AssertionError("時間帯が重なる予約が拒否されませんでした。")


def test_cancelled_reservation_does_not_block_same_datetime(tmp_path):
    service = make_service(tmp_path)
    target = datetime(2026, 5, 13, 10, 0)
    first = service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", target))
    service.update_status(first["id"], "cancelled")

    second = service.create_reservation(ReservationInput("佐藤花子", "user-002", "60分相談", target))
    assert second["status"] == "reserved"


def test_min_booking_notice_is_rejected(tmp_path):
    service = make_service(tmp_path, min_notice=120)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", FIXED_NOW + timedelta(hours=1)))
    except ValueError as exc:
        assert "直前すぎる予約" in str(exc)
    else:
        raise AssertionError("受付締切時間以内の予約が拒否されませんでした。")


def test_max_booking_days_ahead_is_rejected(tmp_path):
    service = make_service(tmp_path, max_days=10)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", FIXED_NOW + timedelta(days=11)))
    except ValueError as exc:
        assert "予約できる期間を過ぎています" in str(exc)
    else:
        raise AssertionError("予約可能期間を超える予約が拒否されませんでした。")


def test_available_slots_are_generated_for_date_and_menu(tmp_path):
    service = make_service(tmp_path)
    service.update_reservation_rules(
        business_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        open_time=time(9, 0),
        close_time=time(11, 0),
        slot_interval_minutes=30,
        min_booking_notice_minutes=0,
        max_booking_days_ahead=30,
        timezone="Asia/Tokyo",
    )
    service.create_reservation(ReservationInput("山田太郎", "user-001", "60分相談", datetime(2026, 5, 12, 9, 30)))

    slots = service.list_available_slots(date(2026, 5, 12), "60分相談")

    assert slots == []


def test_available_slots_include_open_slots_when_no_conflict(tmp_path):
    service = make_service(tmp_path)
    service.update_reservation_rules(
        business_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        open_time=time(9, 0),
        close_time=time(11, 0),
        slot_interval_minutes=30,
        min_booking_notice_minutes=0,
        max_booking_days_ahead=30,
        timezone="Asia/Tokyo",
    )

    slots = service.list_available_slots(date(2026, 5, 12), "60分相談")

    assert slots == ["09:00", "09:30", "10:00"]


def test_create_demo_reservations_is_idempotent(tmp_path):
    service = make_service(tmp_path)

    first = service.create_demo_reservations()
    second = service.create_demo_reservations()

    assert len(first["created"]) == 3
    assert len(first["skipped"]) == 0
    assert len(second["created"]) == 0
    assert len(second["skipped"]) == 3
    assert len(service.list_reservations()) == 3


def test_past_reservation_is_rejected(tmp_path):
    service = make_service(tmp_path)

    try:
        service.create_reservation(ReservationInput("山田太郎", "user-001", "30分相談", FIXED_NOW - timedelta(minutes=1)))
    except ValueError as exc:
        assert "過去の日時は予約できません" in str(exc)
    else:
        raise AssertionError("過去日時の予約が拒否されませんでした。")


def test_reminder_service_marks_sent(tmp_path):
    db_path = tmp_path / "test.db"
    settings = build_test_settings(db_path)
    service = ReservationService(str(db_path), settings=settings, now_provider=lambda: FIXED_NOW)

    reservation = service.create_reservation(
        ReservationInput(
            customer_name="リマインド太郎",
            line_user_id="user-reminder",
            menu="30分相談",
            reservation_datetime=FIXED_NOW + timedelta(hours=2),
        )
    )

    sent_messages = []

    def fake_sender(reservation_dict, message):
        sent_messages.append((reservation_dict, message))

    reminder = ReminderService(
        reservation_service=service,
        settings=Settings(database_path=str(db_path), reminder_hours_before=24),
        sender=fake_sender,
    )
    sent = reminder.send_due_reminders(FIXED_NOW)

    assert len(sent) == 1
    assert sent[0]["id"] == reservation["id"]
    assert len(sent_messages) == 1
    assert service.get_reservation(reservation["id"])["reminder_sent"] == 1
