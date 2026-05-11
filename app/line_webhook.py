"""LINE webhook and demo message handling.

The core function `handle_user_message` is intentionally independent from FastAPI
so it can be tested without a real LINE account.
"""

from __future__ import annotations

from datetime import datetime
import base64
import hashlib
import hmac
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

from app.reservation_service import ReservationInput, ReservationService, STATUS_LABELS
from app.settings import Settings, get_settings


HELP_TEXT = """使い方：
・予約 → メニュー一覧を表示
・予約 30分相談 2026-05-10 10:00 → 予約登録
・確認 → 直近の予約を確認
・キャンセル → 直近の予約をキャンセル
"""


def handle_user_message(
    user_id: str,
    text: str,
    display_name: str = "LINEユーザー",
    service: ReservationService | None = None,
) -> dict[str, Any]:
    """Return a bot-style response for a user message."""
    service = service or ReservationService()
    normalized = (text or "").strip()

    if not normalized:
        return {"reply_text": HELP_TEXT, "action": "help"}

    if normalized in {"ヘルプ", "help", "HELP", "使い方"}:
        return {"reply_text": HELP_TEXT, "action": "help"}

    if normalized in {"予約", "メニュー", "menu"}:
        return {"reply_text": build_menu_message(service), "action": "show_menu"}

    if normalized.startswith("予約 "):
        return create_reservation_from_message(user_id, normalized, display_name, service)

    if normalized == "確認":
        reservation = service.get_latest_upcoming_reservation(user_id)
        if reservation is None:
            return {"reply_text": "現在、確認できる予約はありません。", "action": "confirm_empty"}
        return {
            "reply_text": "直近のご予約はこちらです。\n" + format_reservation(reservation),
            "action": "confirm",
            "reservation": reservation,
        }

    if normalized == "キャンセル":
        reservation = service.cancel_latest_reservation(user_id)
        if reservation is None:
            return {"reply_text": "キャンセルできる予約が見つかりませんでした。", "action": "cancel_empty"}
        return {
            "reply_text": "直近のご予約をキャンセルしました。\n" + format_reservation(reservation),
            "action": "cancel",
            "reservation": reservation,
        }

    return {
        "reply_text": "内容を確認できませんでした。\n" + HELP_TEXT,
        "action": "unknown",
    }


def build_menu_message(service: ReservationService) -> str:
    menus = service.list_menus(active_only=True)
    lines = ["ご予約メニューを選択してください。"]
    for menu in menus:
        price = f" / {menu['price']}円" if menu.get("price") else ""
        lines.append(f"・{menu['name']}（{menu['duration_minutes']}分{price}）")
    lines.append("")
    lines.append("入力例：予約 30分相談 2026-05-10 10:00")
    return "\n".join(lines)


def create_reservation_from_message(
    user_id: str,
    text: str,
    display_name: str,
    service: ReservationService,
) -> dict[str, Any]:
    # Format: 予約 30分相談 2026-05-10 10:00
    parts = text.split()
    if len(parts) < 4:
        return {
            "reply_text": "予約内容が足りません。\n入力例：予約 30分相談 2026-05-10 10:00",
            "action": "create_failed",
        }

    menu = parts[1]
    date_text = parts[2]
    time_text = parts[3]
    notes = " ".join(parts[4:]) if len(parts) > 4 else ""

    try:
        reservation_dt = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError:
        return {
            "reply_text": "日時の形式が正しくありません。例：予約 30分相談 2026-05-10 10:00",
            "action": "create_failed",
        }

    try:
        existing_reservations = service.find_future_reservations_for_customer(line_user_id=user_id)
        reservation = service.create_reservation(
            ReservationInput(
                customer_name=display_name or "LINEユーザー",
                line_user_id=user_id,
                menu=menu,
                reservation_datetime=reservation_dt,
                reservation_source="line",
                notes=notes,
            )
        )
    except ValueError as exc:
        return {
            "reply_text": f"予約を作成できませんでした。\n理由：{exc}\n入力例：予約 30分相談 2026-05-10 10:00",
            "action": "create_failed",
        }

    duplicate_notice = ""
    if existing_reservations:
        duplicate_notice = "すでに別の予約があります。重複登録でないかご確認ください。\n"

    return {
        "reply_text": duplicate_notice + "ご予約を受け付けました。\n" + format_reservation(reservation),
        "action": "create",
        "reservation": reservation,
    }


def format_reservation(reservation: dict[str, Any]) -> str:
    status = STATUS_LABELS.get(reservation.get("status"), reservation.get("status", ""))
    return (
        f"メニュー：{reservation['menu']}\n"
        f"日時：{reservation['reservation_datetime'].replace('T', ' ')}\n"
        f"お名前：{reservation['customer_name']}\n"
        f"状態：{status}"
    )


def verify_line_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    if not channel_secret or not signature:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def extract_line_events(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Extract text events from a LINE webhook payload."""
    events: list[dict[str, str]] = []
    for event in payload.get("events", []):
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue
        events.append(
            {
                "reply_token": event.get("replyToken", ""),
                "user_id": event.get("source", {}).get("userId", "unknown-user"),
                "text": message.get("text", ""),
            }
        )
    return events


def send_line_reply(reply_token: str, text: str, settings: Settings | None = None) -> None:
    """Send a LINE reply when real credentials are configured.

    In demo mode this prints to the console instead of calling LINE.
    """
    settings = settings or get_settings()
    if settings.demo_mode or not settings.line_channel_access_token:
        print(f"[DEMO LINE REPLY] token={reply_token} text={text}")
        return

    if requests is None:
        raise RuntimeError("requests がインストールされていません。requirements.txt を確認してください。")

    response = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )
    response.raise_for_status()
