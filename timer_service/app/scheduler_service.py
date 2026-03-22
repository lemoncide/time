"""
APScheduler integration for TimerService.

All timer callbacks run in APScheduler's thread pool, outside Flask's
request context. Every callback must push its own app context.
"""
import logging
from datetime import datetime, timedelta

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError

logger = logging.getLogger(__name__)

# Module-level scheduler instance shared across the app
scheduler = BackgroundScheduler(timezone="UTC")
_app = None  # set by init_scheduler; used inside thread callbacks


def init_scheduler(app) -> None:
    """Start the scheduler and attach it to the Flask app."""
    global _app
    _app = app
    scheduler.start()
    app.extensions["scheduler"] = scheduler
    logger.info("APScheduler started")


def restore_timers(app) -> None:
    """
    Re-schedule all active timers from the DB after a server restart.

    One-time timers whose next_fire_at is in the past fire immediately
    (run_date set to now + 1s to avoid APScheduler edge-case with past dates).
    """
    from .models import Timer

    with app.app_context():
        active_timers = Timer.query.filter_by(status="active").all()
        now = datetime.utcnow()
        for timer in active_timers:
            try:
                if timer.timer_type == "one_time":
                    fire_at = timer.next_fire_at
                    if fire_at is None or fire_at <= now:
                        fire_at = now + timedelta(seconds=1)
                    _add_one_time_job(timer.id, fire_at)
                else:
                    _add_daily_job(timer.id, timer.trigger_time, timer.timezone or "UTC")
            except Exception as e:
                logger.error("Failed to restore timer %s: %s", timer.id, e)

    logger.info("Restored %d active timer(s)", len(active_timers))


def schedule_timer(timer) -> str:
    """
    Add an APScheduler job for the timer.

    Returns the job_id string so it can be stored on the Timer model.
    """
    job_id = f"timer_{timer.id}"
    if timer.timer_type == "one_time":
        _add_one_time_job(timer.id, timer.next_fire_at, job_id)
    else:
        _add_daily_job(timer.id, timer.trigger_time, timer.timezone or "UTC", job_id)
    return job_id


def cancel_timer(job_id: str) -> None:
    """Remove an APScheduler job; silently ignore missing jobs."""
    try:
        scheduler.remove_job(job_id)
    except JobLookupError:
        logger.debug("Job %s not found when cancelling (already fired?)", job_id)


def fire_timer(timer_id: int) -> None:
    """
    Timer callback — runs in APScheduler's thread pool OR called directly in tests.

    Detects whether an app context already exists (test scenario) and avoids
    double-pushing one, so the same function works both in production (where
    APScheduler threads have no context) and in tests (where we call it inside
    ``with app.app_context()``).
    """
    from flask import has_app_context

    if has_app_context():
        _do_fire(timer_id)
    elif _app is not None:
        with _app.app_context():
            _do_fire(timer_id)
    else:
        logger.error("fire_timer called before init_scheduler; skipping timer %d", timer_id)


def _do_fire(timer_id: int) -> None:
    """Core fire logic — must be called within an active Flask app context."""
    from . import db
    from .models import Timer, TimerEvent
    from .notifications import push_event

    timer = db.session.get(Timer, timer_id)
    if timer is None or timer.status == "cancelled":
        return

    now = datetime.utcnow()
    timer.last_fired_at = now

    if timer.timer_type == "one_time":
        timer.status = "fired"
        timer.next_fire_at = None
    else:
        # Advance next_fire_at by one day
        if timer.next_fire_at:
            timer.next_fire_at = timer.next_fire_at + timedelta(days=1)

    # Create audit event
    event = TimerEvent(timer_id=timer_id)

    # Deliver webhook if configured
    if timer.webhook_url:
        webhook_status, response_code = _deliver_webhook(
            timer.webhook_url,
            {
                "timer_id": timer.id,
                "timer_name": timer.name,
                "fired_at": now.isoformat(),
                "timer_type": timer.timer_type,
            },
        )
        event.webhook_status = webhook_status
        event.webhook_response_code = response_code
    else:
        event.webhook_status = "skipped"

    db.session.add(event)
    db.session.commit()

    # Push SSE event to connected clients (after commit so IDs are stable)
    push_event(
        timer.user_id,
        {
            "type": "timer_fired",
            "timer_id": timer.id,
            "timer_name": timer.name,
            "fired_at": now.isoformat(),
            "timer_type": timer.timer_type,
            "status": timer.status,
        },
    )


# ──────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────

def _add_one_time_job(timer_id: int, run_date: datetime, job_id: str = None) -> None:
    if job_id is None:
        job_id = f"timer_{timer_id}"
    scheduler.add_job(
        fire_timer,
        trigger="date",
        run_date=run_date,
        args=[timer_id],
        id=job_id,
        replace_existing=True,
    )


def _add_daily_job(timer_id: int, trigger_time: str, timezone: str = "UTC", job_id: str = None) -> None:
    """trigger_time is 'HH:MM' in the given IANA timezone."""
    from zoneinfo import ZoneInfo
    if job_id is None:
        job_id = f"timer_{timer_id}"
    hour, minute = map(int, trigger_time.split(":"))
    tz = ZoneInfo(timezone)
    scheduler.add_job(
        fire_timer,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=tz,
        args=[timer_id],
        id=job_id,
        replace_existing=True,
    )


def _deliver_webhook(url: str, payload: dict) -> tuple[str, int | None]:
    """POST payload to url; returns (status_string, http_code_or_None)."""
    try:
        resp = requests.post(url, json=payload, timeout=5)
        return "success" if resp.ok else "failed", resp.status_code
    except Exception as e:
        logger.warning("Webhook delivery failed for %s: %s", url, e)
        return "failed", None
