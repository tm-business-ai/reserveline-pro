from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json

from app.line_webhook import extract_line_events, handle_user_message, verify_line_signature
from app.reservation_service import ReservationService
from app.settings import Settings


FIXED_NOW = datetime.combine(date.today(), time(9, 0))


def make_service(tmp_path) -> ReservationService:
    db_path = tmp_path / "test.db"
    settings = Settings(
        database_path=str(db_path),
        business_open_time=time(9, 0),
        business_close_time=time(18, 0),
        business_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    )
    return ReservationService(str(db_path), settings=settings, now_provider=lambda: FIXED_NOW)


def test_handle_show_menu(tmp_path):
    service = make_service(tmp_path)
    result = handle_user_message("user-001", "予約", "山田", service)

    assert result["action"] == "show_menu"
    assert "30分相談" in result["reply_text"]


def test_handle_create_confirm_cancel(tmp_path):
    service = make_service(tmp_path)
    target = FIXED_NOW + timedelta(days=1, hours=1)
    message = f"予約 30分相談 {target:%Y-%m-%d} {target:%H:%M}"

    created = handle_user_message("user-001", message, "山田", service)
    assert created["action"] == "create"
    assert "ご予約を受け付けました" in created["reply_text"]

    confirmed = handle_user_message("user-001", "確認", "山田", service)
    assert confirmed["action"] == "confirm"

    cancelled = handle_user_message("user-001", "キャンセル", "山田", service)
    assert cancelled["action"] == "cancel"
    assert cancelled["reservation"]["status"] == "cancelled"


def test_line_reservation_source_is_line(tmp_path):
    service = make_service(tmp_path)
    target = FIXED_NOW + timedelta(days=1, hours=1)
    message = f"予約 30分相談 {target:%Y-%m-%d} {target:%H:%M}"

    created = handle_user_message("user-001", message, "山田", service)

    assert created["action"] == "create"
    assert created["reservation"]["reservation_source"] == "line"


def test_invalid_reservation_format(tmp_path):
    service = make_service(tmp_path)
    result = handle_user_message("user-001", "予約 30分相談", "山田", service)

    assert result["action"] == "create_failed"
    assert "入力例" in result["reply_text"]


def test_invalid_datetime_format_returns_japanese_message(tmp_path):
    service = make_service(tmp_path)
    result = handle_user_message("user-001", "予約 30分相談 2026/05/10 10時", "山田", service)

    assert result["action"] == "create_failed"
    assert "日時の形式が正しくありません" in result["reply_text"]


def test_duplicate_reservation_message(tmp_path):
    service = make_service(tmp_path)
    target = FIXED_NOW + timedelta(days=1, hours=1)
    message = f"予約 30分相談 {target:%Y-%m-%d} {target:%H:%M}"

    first = handle_user_message("user-001", message, "山田", service)
    duplicate = handle_user_message("user-002", message, "佐藤", service)

    assert first["action"] == "create"
    assert duplicate["action"] == "create_failed"
    assert "すでに予約が入っています" in duplicate["reply_text"]


def test_extract_line_events():
    payload = {
        "events": [
            {
                "type": "message",
                "replyToken": "reply-token",
                "source": {"userId": "line-user"},
                "message": {"type": "text", "text": "予約"},
            }
        ]
    }

    events = extract_line_events(payload)
    assert events == [{"reply_token": "reply-token", "user_id": "line-user", "text": "予約"}]


def test_verify_line_signature():
    secret = "secret"
    body = json.dumps({"events": []}).encode("utf-8")

    import base64
    import hashlib
    import hmac

    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_line_signature(body, signature, secret) is True
    assert verify_line_signature(body, "bad", secret) is False
