"""
TDD test suite — authentication endpoints.

Tests are written RED-first; implementation in app/auth.py makes them GREEN.
"""
import pytest


class TestRegister:
    def test_register_success(self, client, db):
        res = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "securepass"},
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["msg"] == "User created"
        assert "user_id" in data

    def test_register_duplicate_username(self, client, db):
        payload = {"username": "bob", "password": "password1"}
        client.post("/api/auth/register", json=payload)
        res = client.post("/api/auth/register", json=payload)
        assert res.status_code == 409
        assert "already exists" in res.get_json()["error"].lower()

    def test_register_short_username(self, client, db):
        res = client.post(
            "/api/auth/register",
            json={"username": "ab", "password": "password1"},
        )
        assert res.status_code == 400
        data = res.get_json()
        assert any("3" in d for d in data["details"])

    def test_register_short_password(self, client, db):
        res = client.post(
            "/api/auth/register",
            json={"username": "charlie", "password": "short"},
        )
        assert res.status_code == 400
        data = res.get_json()
        assert any("8" in d for d in data["details"])

    def test_register_missing_username(self, client, db):
        res = client.post("/api/auth/register", json={"password": "password1"})
        assert res.status_code == 400

    def test_register_missing_password(self, client, db):
        res = client.post("/api/auth/register", json={"username": "dave"})
        assert res.status_code == 400

    def test_register_empty_body(self, client, db):
        res = client.post("/api/auth/register", json={})
        assert res.status_code == 400


class TestLogin:
    def test_login_success(self, client, db):
        client.post(
            "/api/auth/register",
            json={"username": "eve", "password": "mypassword"},
        )
        res = client.post(
            "/api/auth/login",
            json={"username": "eve", "password": "mypassword"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert len(data["access_token"]) > 20
        assert len(data["refresh_token"]) > 20

    def test_login_wrong_password(self, client, db):
        client.post(
            "/api/auth/register",
            json={"username": "frank", "password": "correct_pass"},
        )
        res = client.post(
            "/api/auth/login",
            json={"username": "frank", "password": "wrong_pass"},
        )
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client, db):
        res = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "password1"},
        )
        assert res.status_code == 401

    def test_login_missing_fields(self, client, db):
        res = client.post("/api/auth/login", json={"username": "grace"})
        assert res.status_code == 400


class TestRefresh:
    def _get_refresh_token(self, client):
        client.post("/api/auth/register",
                    json={"username": "henry", "password": "password99"})
        res = client.post("/api/auth/login",
                          json={"username": "henry", "password": "password99"})
        return res.get_json()["refresh_token"]

    def test_refresh_returns_new_access_token(self, client, db):
        refresh_token = self._get_refresh_token(client)
        res = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "access_token" in data
        assert len(data["access_token"]) > 20

    def test_refresh_with_access_token_fails(self, client, db):
        client.post("/api/auth/register",
                    json={"username": "ivan", "password": "password99"})
        res = client.post("/api/auth/login",
                          json={"username": "ivan", "password": "password99"})
        access_token = res.get_json()["access_token"]
        # 用 access_token 调刷新接口应该失败
        res = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert res.status_code == 422

    def test_refresh_without_token_fails(self, client, db):
        res = client.post("/api/auth/refresh")
        assert res.status_code == 401
