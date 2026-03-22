"""
Shared pytest fixtures for TimerService tests.

The SCHEDULER_ENABLED=False config means no background jobs run during
tests. Timer fire logic is tested by calling fire_timer() directly.
"""
import pytest

from app import create_app, db as _db


@pytest.fixture(scope="session")
def app():
    """Application configured for testing (in-memory SQLite, no scheduler)."""
    application = create_app("testing")
    yield application


@pytest.fixture()
def client(app):
    """Flask test client."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def db(app):
    """Fresh database tables for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


def register_and_login(client, username="testuser", password="password123"):
    """Helper: register a user and return the JWT access token."""
    client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    return res.get_json()["access_token"]


def auth_headers(token: str) -> dict:
    """Build Authorization header dict from a JWT token."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def token(client, db):
    """A valid JWT token for 'testuser'."""
    return register_and_login(client)


@pytest.fixture()
def headers(token):
    """Authorization headers for 'testuser'."""
    return auth_headers(token)
