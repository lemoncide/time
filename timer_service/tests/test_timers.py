"""
TDD test suite — timer CRUD, fire callbacks, webhook delivery, and SSE push.

The scheduler is DISABLED in testing config. Timer firing is tested by
calling scheduler_service.fire_timer() directly within the app context.
"""
import queue
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import db as _db
from app.models import Timer, TimerEvent
from tests.conftest import auth_headers, register_and_login


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture()
def token2(client, db):
    """A valid JWT token for a second user 'otheruser'."""
    return register_and_login(client, username="otheruser", password="password456")


@pytest.fixture()
def headers2(token2):
    return auth_headers(token2)


# ─────────────────────────────────────────────
# Create Timer
# ─────────────────────────────────────────────

class TestCreateTimer:
    def test_create_one_time_timer(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "My Alert", "timer_type": "one_time", "delay_seconds": 30},
            headers=headers,
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["name"] == "My Alert"
        assert data["timer_type"] == "one_time"
        assert data["delay_seconds"] == 30
        assert data["status"] == "active"
        assert data["next_fire_at"] is not None

    def test_create_daily_timer(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "Daily Reminder", "timer_type": "daily", "trigger_time": "09:30"},
            headers=headers,
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["timer_type"] == "daily"
        assert data["trigger_time"] == "09:30"
        assert data["status"] == "active"

    def test_create_timer_with_webhook(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={
                "name": "Hook Timer",
                "timer_type": "one_time",
                "delay_seconds": 60,
                "webhook_url": "https://example.com/callback",
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.get_json()["webhook_url"] == "https://example.com/callback"

    def test_create_timer_delay_too_short(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "one_time", "delay_seconds": 0},
            headers=headers,
        )
        assert res.status_code == 400
        assert any("1" in d for d in res.get_json()["details"])

    def test_create_timer_delay_too_long(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "one_time", "delay_seconds": 86401},
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_invalid_trigger_time_format(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "daily", "trigger_time": "25:99"},
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_missing_delay_for_one_time(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "one_time"},
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_missing_trigger_time_for_daily(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "daily"},
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_invalid_type(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "monthly"},
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_invalid_webhook_url(self, client, db, headers):
        res = client.post(
            "/api/timers",
            json={
                "name": "X",
                "timer_type": "one_time",
                "delay_seconds": 10,
                "webhook_url": "not-a-url",
            },
            headers=headers,
        )
        assert res.status_code == 400

    def test_create_timer_unauthenticated(self, client, db):
        res = client.post(
            "/api/timers",
            json={"name": "X", "timer_type": "one_time", "delay_seconds": 10},
        )
        assert res.status_code == 401


# ─────────────────────────────────────────────
# List Timers
# ─────────────────────────────────────────────

class TestListTimers:
    def test_list_own_timers(self, client, db, headers):
        client.post(
            "/api/timers",
            json={"name": "T1", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        client.post(
            "/api/timers",
            json={"name": "T2", "timer_type": "one_time", "delay_seconds": 20},
            headers=headers,
        )
        res = client.get("/api/timers", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["timers"]) == 2

    def test_users_cannot_see_each_others_timers(self, client, db, headers, headers2):
        client.post(
            "/api/timers",
            json={"name": "User1 Timer", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        client.post(
            "/api/timers",
            json={"name": "User2 Timer", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers2,
        )
        res1 = client.get("/api/timers", headers=headers)
        res2 = client.get("/api/timers", headers=headers2)

        names1 = [t["name"] for t in res1.get_json()["timers"]]
        names2 = [t["name"] for t in res2.get_json()["timers"]]

        assert "User1 Timer" in names1
        assert "User2 Timer" not in names1
        assert "User2 Timer" in names2
        assert "User1 Timer" not in names2

    def test_list_timers_filter_by_status(self, client, db, headers, app):
        # Create a timer and cancel it directly in DB
        res = client.post(
            "/api/timers",
            json={"name": "Active", "timer_type": "one_time", "delay_seconds": 60},
            headers=headers,
        )
        timer_id = res.get_json()["id"]
        with app.app_context():
            t = Timer.query.get(timer_id)
            t.status = "cancelled"
            _db.session.commit()

        active_res    = client.get("/api/timers?status=active",    headers=headers)
        cancelled_res = client.get("/api/timers?status=cancelled", headers=headers)
        assert len(active_res.get_json()["timers"])    == 0
        assert len(cancelled_res.get_json()["timers"]) == 1


# ─────────────────────────────────────────────
# Get Single Timer
# ─────────────────────────────────────────────

class TestGetTimer:
    def test_get_timer_success(self, client, db, headers):
        create_res = client.post(
            "/api/timers",
            json={"name": "Fetch Me", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        res = client.get(f"/api/timers/{timer_id}", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data["name"] == "Fetch Me"
        assert "events" in data

    def test_get_timer_not_found(self, client, db, headers):
        res = client.get("/api/timers/99999", headers=headers)
        assert res.status_code == 404

    def test_get_timer_wrong_user_returns_404(self, client, db, headers, headers2):
        """Should return 404 (not 403) to avoid timer enumeration."""
        create_res = client.post(
            "/api/timers",
            json={"name": "Private", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        res = client.get(f"/api/timers/{timer_id}", headers=headers2)
        assert res.status_code == 404


# ─────────────────────────────────────────────
# Delete (Cancel) Timer
# ─────────────────────────────────────────────

class TestDeleteTimer:
    def test_delete_timer(self, client, db, headers):
        create_res = client.post(
            "/api/timers",
            json={"name": "To Delete", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        res = client.delete(f"/api/timers/{timer_id}", headers=headers)
        assert res.status_code == 200
        assert res.get_json()["msg"] == "Timer cancelled"

        # Verify status in DB
        detail = client.get(f"/api/timers/{timer_id}", headers=headers).get_json()
        assert detail["status"] == "cancelled"

    def test_delete_timer_wrong_user(self, client, db, headers, headers2):
        create_res = client.post(
            "/api/timers",
            json={"name": "Mine", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        res = client.delete(f"/api/timers/{timer_id}", headers=headers2)
        assert res.status_code == 404

    def test_delete_nonexistent_timer(self, client, db, headers):
        res = client.delete("/api/timers/99999", headers=headers)
        assert res.status_code == 404


# ─────────────────────────────────────────────
# Fire Timer Callback (scheduler disabled; called directly)
# ─────────────────────────────────────────────

class TestFireTimer:
    def test_fire_one_time_timer_creates_event_and_updates_status(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={"name": "Fire Me", "timer_type": "one_time", "delay_seconds": 60},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]

        from app import scheduler_service
        from app import db as _app_db
        with app.app_context():
            scheduler_service.fire_timer(timer_id)
            timer  = _app_db.session.get(Timer, timer_id)
            events = TimerEvent.query.filter_by(timer_id=timer_id).all()

        assert timer.status == "fired"
        assert len(events) == 1
        assert events[0].webhook_status == "skipped"

    def test_fire_daily_timer_stays_active_and_advances_next_fire(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={"name": "Daily", "timer_type": "daily", "trigger_time": "12:00"},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]

        from app import scheduler_service
        from app import db as _app_db
        with app.app_context():
            original_next = _app_db.session.get(Timer, timer_id).next_fire_at
            scheduler_service.fire_timer(timer_id)
            timer = _app_db.session.get(Timer, timer_id)

        assert timer.status == "active"          # still active
        assert timer.next_fire_at > original_next  # advanced by one day

    def test_fire_cancelled_timer_does_nothing(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={"name": "Cancelled", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        client.delete(f"/api/timers/{timer_id}", headers=headers)

        from app import scheduler_service
        with app.app_context():
            scheduler_service.fire_timer(timer_id)
            events = TimerEvent.query.filter_by(timer_id=timer_id).all()

        assert len(events) == 0


# ─────────────────────────────────────────────
# Webhook Delivery
# ─────────────────────────────────────────────

class TestWebhookDelivery:
    def test_webhook_delivered_on_fire(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={
                "name": "Webhook Timer",
                "timer_type": "one_time",
                "delay_seconds": 10,
                "webhook_url": "https://example.com/hook",
            },
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200

        from app import scheduler_service
        with patch("app.scheduler_service.requests.post", return_value=mock_response) as mock_post:
            with app.app_context():
                scheduler_service.fire_timer(timer_id)
                event = TimerEvent.query.filter_by(timer_id=timer_id).first()

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "https://example.com/hook"
        payload = call_kwargs[1]["json"]
        assert payload["timer_id"] == timer_id
        assert "fired_at" in payload

        assert event.webhook_status == "success"
        assert event.webhook_response_code == 200

    def test_webhook_failure_recorded(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={
                "name": "Failing Webhook",
                "timer_type": "one_time",
                "delay_seconds": 10,
                "webhook_url": "https://example.com/hook",
            },
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]

        from app import scheduler_service
        with patch(
            "app.scheduler_service.requests.post",
            side_effect=Exception("Connection refused"),
        ):
            with app.app_context():
                scheduler_service.fire_timer(timer_id)
                event = TimerEvent.query.filter_by(timer_id=timer_id).first()

        assert event.webhook_status == "failed"
        assert event.webhook_response_code is None


# ─────────────────────────────────────────────
# SSE Notification Module
# ─────────────────────────────────────────────

class TestListEvents:
    def test_list_events_empty(self, client, db, headers):
        res = client.get("/api/timers/events", headers=headers)
        assert res.status_code == 200
        assert res.get_json()["count"] == 0

    def test_list_events_after_fire(self, client, db, headers, app):
        create_res = client.post(
            "/api/timers",
            json={"name": "历史测试", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        timer_id = create_res.get_json()["id"]
        from app import scheduler_service
        with app.app_context():
            scheduler_service.fire_timer(timer_id)

        res = client.get("/api/timers/events", headers=headers)
        data = res.get_json()
        assert data["count"] == 1
        assert data["events"][0]["timer_id"] == timer_id

    def test_list_events_filter_by_timer_id(self, client, db, headers, app):
        r1 = client.post(
            "/api/timers",
            json={"name": "T1", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        r2 = client.post(
            "/api/timers",
            json={"name": "T2", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        id1, id2 = r1.get_json()["id"], r2.get_json()["id"]
        from app import scheduler_service
        with app.app_context():
            scheduler_service.fire_timer(id1)
            scheduler_service.fire_timer(id2)

        res = client.get(f"/api/timers/events?timer_id={id1}", headers=headers)
        data = res.get_json()
        assert data["count"] == 1
        assert data["events"][0]["timer_id"] == id1

    def test_list_events_only_own(self, client, db, headers, headers2, app):
        r = client.post(
            "/api/timers",
            json={"name": "User1", "timer_type": "one_time", "delay_seconds": 10},
            headers=headers,
        )
        from app import scheduler_service
        with app.app_context():
            scheduler_service.fire_timer(r.get_json()["id"])

        res = client.get("/api/timers/events", headers=headers2)
        assert res.get_json()["count"] == 0


class TestSSENotifications:
    def test_push_event_reaches_registered_client(self):
        from app.notifications import push_event, register_client, unregister_client

        q = register_client(999)
        event = {"type": "timer_fired", "timer_id": 1}
        push_event(999, event)
        received = q.get_nowait()
        assert received == event
        unregister_client(999, q)

    def test_push_event_to_multiple_clients(self):
        from app.notifications import push_event, register_client, unregister_client

        q1 = register_client(888)
        q2 = register_client(888)
        push_event(888, {"type": "timer_fired"})
        assert not q1.empty()
        assert not q2.empty()
        unregister_client(888, q1)
        unregister_client(888, q2)

    def test_push_event_does_not_cross_users(self):
        from app.notifications import push_event, register_client, unregister_client

        q_user_a = register_client(111)
        push_event(222, {"type": "timer_fired"})  # different user
        assert q_user_a.empty()
        unregister_client(111, q_user_a)

    def test_unregister_removes_client(self):
        from app.notifications import _clients, push_event, register_client, unregister_client

        q = register_client(777)
        unregister_client(777, q)
        assert 777 not in _clients
        # Push should not raise even with no clients
        push_event(777, {"type": "timer_fired"})
