"""
Timer CRUD endpoints + SSE stream.

JWT is required for all routes. Users can only access their own timers.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_jwt_extended import decode_token, get_jwt_identity, jwt_required

from . import db
from .models import Timer, TimerEvent
from .notifications import event_stream

timers_bp = Blueprint("timers", __name__)

MAX_DELAY_SECONDS = 86400  # 24 hours
MIN_DELAY_SECONDS = 1
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────

@timers_bp.route("", methods=["POST"])
@jwt_required()
def create_timer():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    errors = _validate_create(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    timer = Timer(
        user_id=user_id,
        name=data["name"].strip(),
        timer_type=data["timer_type"],
        webhook_url=data.get("webhook_url") or None,
    )

    if data["timer_type"] == "one_time":
        timer.delay_seconds = data["delay_seconds"]
        timer.next_fire_at = datetime.utcnow() + timedelta(seconds=data["delay_seconds"])
    else:
        tz_name = data.get("timezone", "UTC") or "UTC"
        timer.trigger_time = data["trigger_time"]
        timer.timezone = tz_name
        timer.next_fire_at = _next_daily_occurrence(data["trigger_time"], tz_name)

    db.session.add(timer)
    db.session.flush()  # get timer.id before scheduling

    from . import scheduler_service
    from flask import current_app

    if current_app.config.get("SCHEDULER_ENABLED", True):
        job_id = scheduler_service.schedule_timer(timer)
        timer.apscheduler_job_id = job_id

    db.session.commit()
    return jsonify(timer.to_dict()), 201


@timers_bp.route("", methods=["GET"])
@jwt_required()
def list_timers():
    user_id = int(get_jwt_identity())
    status_filter = request.args.get("status")

    query = Timer.query.filter_by(user_id=user_id)
    if status_filter:
        query = query.filter_by(status=status_filter)

    timers = query.order_by(Timer.created_at.desc()).all()
    return jsonify({"timers": [t.to_dict() for t in timers]}), 200


@timers_bp.route("/<int:timer_id>", methods=["GET"])
@jwt_required()
def get_timer(timer_id):
    user_id = int(get_jwt_identity())
    timer = _get_owned_timer(timer_id, user_id)
    if timer is None:
        return jsonify({"error": "Timer not found"}), 404

    data = timer.to_dict()
    data["events"] = [e.to_dict() for e in timer.events]
    return jsonify(data), 200


@timers_bp.route("/<int:timer_id>", methods=["DELETE"])
@jwt_required()
def delete_timer(timer_id):
    user_id = int(get_jwt_identity())
    timer = _get_owned_timer(timer_id, user_id)
    if timer is None:
        return jsonify({"error": "Timer not found"}), 404

    if timer.status == "active":
        from . import scheduler_service
        from flask import current_app

        if current_app.config.get("SCHEDULER_ENABLED", True) and timer.apscheduler_job_id:
            scheduler_service.cancel_timer(timer.apscheduler_job_id)

    timer.status = "cancelled"
    db.session.commit()
    return jsonify({"msg": "Timer cancelled", "timer_id": timer_id}), 200


# ─────────────────────────────────────────────
# 触发历史记录
# ─────────────────────────────────────────────

@timers_bp.route("/events", methods=["GET"])
@jwt_required()
def list_events():
    """查询当前用户所有定时器的触发历史，支持按 timer_id 过滤。"""
    user_id = int(get_jwt_identity())
    timer_id_filter = request.args.get("timer_id", type=int)

    # 只查当前用户的 Timer，再 join TimerEvent
    query = (
        db.session.query(TimerEvent)
        .join(Timer, Timer.id == TimerEvent.timer_id)
        .filter(Timer.user_id == user_id)
    )
    if timer_id_filter:
        query = query.filter(TimerEvent.timer_id == timer_id_filter)

    events = query.order_by(TimerEvent.fired_at.desc()).all()
    return jsonify({"count": len(events), "events": [e.to_dict() for e in events]}), 200


# ─────────────────────────────────────────────
# SSE stream  (JWT passed as ?token= query param
# because EventSource API cannot set custom headers)
# ─────────────────────────────────────────────

@timers_bp.route("/stream", methods=["GET"])
def timer_stream():
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "token query parameter required"}), 401

    try:
        decoded = decode_token(token)
        user_id = int(decoded["sub"])
    except Exception:
        return jsonify({"error": "Invalid or expired token"}), 401

    return Response(
        stream_with_context(event_stream(user_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_owned_timer(timer_id: int, user_id: int):
    return Timer.query.filter_by(id=timer_id, user_id=user_id).first()


def _validate_create(data: dict) -> list[str]:
    errors = []

    name = data.get("name", "").strip()
    if not name:
        errors.append("name is required")
    elif len(name) > 200:
        errors.append("name must be at most 200 characters")

    timer_type = data.get("timer_type", "")
    if timer_type not in ("one_time", "daily"):
        errors.append("timer_type must be 'one_time' or 'daily'")
        return errors  # cannot validate type-specific fields further

    if timer_type == "one_time":
        delay = data.get("delay_seconds")
        if delay is None:
            errors.append("delay_seconds is required for one_time timers")
        elif not isinstance(delay, int):
            errors.append("delay_seconds must be an integer")
        elif delay < MIN_DELAY_SECONDS:
            errors.append(f"delay_seconds must be at least {MIN_DELAY_SECONDS}")
        elif delay > MAX_DELAY_SECONDS:
            errors.append(f"delay_seconds must be at most {MAX_DELAY_SECONDS} (24 hours)")

    if timer_type == "daily":
        trigger_time = data.get("trigger_time", "")
        if not trigger_time:
            errors.append("trigger_time is required for daily timers")
        elif not HHMM_RE.match(str(trigger_time)):
            errors.append("trigger_time must be in HH:MM format (00:00–23:59)")

        tz_name = data.get("timezone", "UTC") or "UTC"
        if tz_name != "UTC":
            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, KeyError):
                errors.append(f"Invalid timezone: {tz_name}")

    webhook_url = data.get("webhook_url")
    if webhook_url and not str(webhook_url).startswith(("http://", "https://")):
        errors.append("webhook_url must start with http:// or https://")

    return errors


def _next_daily_occurrence(trigger_time: str, timezone: str = "UTC") -> datetime:
    """Return the next UTC datetime for the given HH:MM time in the specified timezone."""
    hour, minute = map(int, trigger_time.split(":"))
    tz = ZoneInfo(timezone)
    utc = ZoneInfo("UTC")
    now_utc = datetime.now(tz=utc)
    now_local = now_utc.astimezone(tz)
    candidate_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate_local <= now_local:
        candidate_local += timedelta(days=1)
    # Return naive UTC datetime for storage
    return candidate_local.astimezone(utc).replace(tzinfo=None)
