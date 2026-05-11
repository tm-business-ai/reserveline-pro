"""FastAPI entry point for ReserveLine Pro."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:  # pragma: no cover
    BackgroundScheduler = None  # type: ignore

from app.database import init_db
from app.line_webhook import (
    extract_line_events,
    handle_user_message,
    send_line_reply,
    verify_line_signature,
)
from app.reminder_service import ReminderService
from app.settings import get_settings

settings = get_settings()
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db(settings.database_path, settings)
    if settings.scheduler_enabled and BackgroundScheduler is not None:
        reminder_service = ReminderService()
        scheduler = BackgroundScheduler()
        scheduler.add_job(reminder_service.send_due_reminders, "interval", minutes=10, id="send_reminders")
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ReserveLine Pro", version="0.1.0", lifespan=lifespan)


@app.get("/")
def root() -> dict:
    return {
        "app": "ReserveLine Pro",
        "message": "LINE予約受付・リマインドBot API",
        "demo_mode": settings.demo_mode,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
async def line_webhook(request: Request, x_line_signature: str | None = Header(default=None)) -> dict:
    body = await request.body()

    if not settings.demo_mode:
        if not verify_line_signature(body, x_line_signature or "", settings.line_channel_secret):
            raise HTTPException(status_code=401, detail="LINE署名の検証に失敗しました。")

    payload = await request.json()

    # Payload for checking the reservation flow without LINE API credentials.
    if "message" in payload:
        result = handle_user_message(
            user_id=payload.get("user_id", "sample-user"),
            text=payload.get("message", ""),
            display_name=payload.get("display_name", "サンプルユーザー"),
        )
        return {"mode": "demo", "result": result}

    results = []
    for event in extract_line_events(payload):
        result = handle_user_message(event["user_id"], event["text"])
        send_line_reply(event["reply_token"], result["reply_text"], settings)
        results.append(result)
    return {"mode": "line", "results": results}


@app.post("/demo/reminders/run")
def run_demo_reminders() -> dict:
    sent = ReminderService().send_due_reminders()
    return {"sent_count": len(sent), "sent": sent}
