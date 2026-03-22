from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    timers = db.relationship("Timer", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, plain: str) -> None:
        self.password_hash = generate_password_hash(plain)

    def check_password(self, plain: str) -> bool:
        return check_password_hash(self.password_hash, plain)

    def __repr__(self):
        return f"<User {self.username}>"


class Timer(db.Model):
    __tablename__ = "timer"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    timer_type = db.Column(db.String(20), nullable=False)  # "one_time" or "daily"
    delay_seconds = db.Column(db.Integer, nullable=True)   # one_time only; 1-86400
    trigger_time = db.Column(db.String(5), nullable=True)  # "HH:MM" in user's timezone; daily only
    timezone = db.Column(db.String(50), nullable=True, default="UTC")  # IANA timezone, e.g. "Asia/Shanghai"
    webhook_url = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default="active")    # active, fired, cancelled
    apscheduler_job_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    next_fire_at = db.Column(db.DateTime, nullable=True)
    last_fired_at = db.Column(db.DateTime, nullable=True)

    events = db.relationship(
        "TimerEvent", backref="timer", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "timer_type": self.timer_type,
            "delay_seconds": self.delay_seconds,
            "trigger_time": self.trigger_time,
            "timezone": self.timezone or "UTC",
            "webhook_url": self.webhook_url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "next_fire_at": self.next_fire_at.isoformat() if self.next_fire_at else None,
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
            "trigger_count": len(self.events),
        }

    def __repr__(self):
        return f"<Timer {self.id} {self.name!r} [{self.status}]>"


class TimerEvent(db.Model):
    __tablename__ = "timer_event"

    id = db.Column(db.Integer, primary_key=True)
    timer_id = db.Column(db.Integer, db.ForeignKey("timer.id"), nullable=False, index=True)
    fired_at = db.Column(db.DateTime, default=datetime.utcnow)
    webhook_status = db.Column(db.String(20), nullable=True)   # success, failed, skipped
    webhook_response_code = db.Column(db.Integer, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timer_id": self.timer_id,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "webhook_status": self.webhook_status,
            "webhook_response_code": self.webhook_response_code,
        }
