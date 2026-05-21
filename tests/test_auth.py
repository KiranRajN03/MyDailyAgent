"""
Phase 2 Tests — Authentication & RBAC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for registration, login, JWT, RBAC, password reset,
First-User Rule, and admin user management.
"""

import pytest
from fastapi.testclient import TestClient

from daily_agents.database.models import User, UserRole
from daily_agents.api.dependencies import hash_password
from daily_agents.api.server import app
from tests.conftest import TestSession

client = TestClient(app)

# Valid test password meeting all requirements
VALID_PASSWORD = "SecurePass123!@#"
VALID_PASSWORD_2 = "AnotherPass456!@#"


# ─── Helpers ─────────────────────────────────────────────────────────


def register_user(
    username="testuser",
    email="test@example.com",
    password=VALID_PASSWORD,
    full_name="Test User",
):
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "full_name": full_name,
        },
    )


def get_auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════
# Registration Tests
# ═══════════════════════════════════════════════════════════════════


class TestRegistration:

    def test_first_user_becomes_admin(self):
        resp = register_user()
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "admin"
        assert data["username"] == "testuser"
        assert "access_token" in data

    def test_second_user_becomes_member(self):
        register_user(username="admin1", email="admin@test.com")
        resp = register_user(username="member1", email="member@test.com")
        assert resp.status_code == 201
        assert resp.json()["role"] == "member"

    def test_duplicate_username_rejected(self):
        register_user(username="dup", email="dup1@test.com")
        resp = register_user(username="dup", email="dup2@test.com")
        assert resp.status_code == 409
        assert "Username already exists" in resp.json()["detail"]

    def test_duplicate_email_rejected(self):
        register_user(username="user1", email="same@test.com")
        resp = register_user(username="user2", email="same@test.com")
        assert resp.status_code == 409
        assert "Email already registered" in resp.json()["detail"]

    def test_invalid_username_format(self):
        resp = register_user(username="bad user!")
        assert resp.status_code == 422

    def test_short_username_rejected(self):
        resp = register_user(username="ab")
        assert resp.status_code == 422

    def test_password_missing_uppercase(self):
        resp = register_user(password="nouppercase123!@#")
        assert resp.status_code == 422

    def test_password_missing_lowercase(self):
        resp = register_user(password="NOLOWERCASE123!@#")
        assert resp.status_code == 422

    def test_password_missing_digit(self):
        resp = register_user(password="NoDigitsHere!@#abc")
        assert resp.status_code == 422

    def test_password_missing_special(self):
        resp = register_user(password="NoSpecialChar1234")
        assert resp.status_code == 422

    def test_password_too_short(self):
        resp = register_user(password="Short1!")
        assert resp.status_code == 422

    def test_returns_jwt_on_success(self):
        resp = register_user()
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0


# ═══════════════════════════════════════════════════════════════════
# Login Tests
# ═══════════════════════════════════════════════════════════════════


class TestLogin:

    def test_successful_login(self):
        register_user()
        resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": VALID_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "testuser"

    def test_wrong_password(self):
        register_user()
        resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "WrongPass123!@#"},
        )
        assert resp.status_code == 401

    def test_nonexistent_user(self):
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": VALID_PASSWORD},
        )
        assert resp.status_code == 401

    def test_deactivated_user_cannot_login(self):
        admin_resp = register_user(username="admin", email="admin@test.com")
        admin_token = admin_resp.json()["access_token"]
        member_resp = register_user(username="member", email="member@test.com")
        member_id = member_resp.json()["user_id"]

        client.put(
            f"/api/users/{member_id}",
            json={"is_active": False},
            headers=get_auth_header(admin_token),
        )

        resp = client.post(
            "/api/auth/login",
            json={"username": "member", "password": VALID_PASSWORD},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# JWT & Current User Tests
# ═══════════════════════════════════════════════════════════════════


class TestJWTAuth:

    def test_me_endpoint_with_valid_token(self):
        resp = register_user()
        token = resp.json()["access_token"]
        me_resp = client.get("/api/auth/me", headers=get_auth_header(token))
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_me_endpoint_without_token(self):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_endpoint_with_invalid_token(self):
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
# Password Reset Tests
# ═══════════════════════════════════════════════════════════════════


class TestPasswordReset:

    def test_forgot_password_existing_email(self):
        register_user()
        resp = client.post(
            "/api/auth/forgot-password",
            json={"email": "test@example.com"},
        )
        assert resp.status_code == 200

    def test_forgot_password_nonexistent_email(self):
        resp = client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert resp.status_code == 200

    def test_reset_password_with_valid_token(self):
        register_user()
        client.post("/api/auth/forgot-password", json={"email": "test@example.com"})

        db = TestSession()
        user = db.query(User).filter(User.username == "testuser").first()
        token = user.reset_token
        db.close()
        assert token is not None

        resp = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD_2},
        )
        assert resp.status_code == 200

        login_resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": VALID_PASSWORD_2},
        )
        assert login_resp.status_code == 200

        old_resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": VALID_PASSWORD},
        )
        assert old_resp.status_code == 401

    def test_reset_password_invalid_token(self):
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": "fake-token", "new_password": VALID_PASSWORD_2},
        )
        assert resp.status_code == 400

    def test_reset_token_is_single_use(self):
        register_user()
        client.post("/api/auth/forgot-password", json={"email": "test@example.com"})

        db = TestSession()
        user = db.query(User).filter(User.username == "testuser").first()
        token = user.reset_token
        db.close()

        resp1 = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD_2},
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD},
        )
        assert resp2.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# RBAC Tests
# ═══════════════════════════════════════════════════════════════════


class TestRBAC:

    def _setup_users(self):
        admin = register_user(username="admin", email="admin@test.com")
        member = register_user(username="member", email="member@test.com")
        return admin.json()["access_token"], member.json()["access_token"]

    def test_admin_can_list_users(self):
        admin_token, _ = self._setup_users()
        resp = client.get("/api/users", headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_member_cannot_list_users(self):
        _, member_token = self._setup_users()
        resp = client.get("/api/users", headers=get_auth_header(member_token))
        assert resp.status_code == 403

    def test_admin_can_create_user(self):
        admin_token, _ = self._setup_users()
        resp = client.post("/api/users", json={
            "username": "newuser", "email": "new@test.com",
            "password": VALID_PASSWORD, "role": "manager",
        }, headers=get_auth_header(admin_token))
        assert resp.status_code == 201
        assert resp.json()["role"] == "manager"

    def test_member_cannot_create_user(self):
        _, member_token = self._setup_users()
        resp = client.post("/api/users", json={
            "username": "hack", "email": "hack@test.com",
            "password": VALID_PASSWORD,
        }, headers=get_auth_header(member_token))
        assert resp.status_code == 403

    def test_admin_can_get_user_details(self):
        admin_token, _ = self._setup_users()
        resp = client.get("/api/users/1", headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_admin_can_update_user_role(self):
        admin_token, _ = self._setup_users()
        resp = client.put("/api/users/2", json={"role": "team_lead"},
                          headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "team_lead"

    def test_admin_can_deactivate_user(self):
        admin_token, _ = self._setup_users()
        resp = client.put("/api/users/2", json={"is_active": False},
                          headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_update_nonexistent_user_returns_404(self):
        admin_token, _ = self._setup_users()
        resp = client.put("/api/users/999", json={"role": "admin"},
                          headers=get_auth_header(admin_token))
        assert resp.status_code == 404

    def test_email_conflict_on_update(self):
        admin_token, _ = self._setup_users()
        resp = client.put("/api/users/2", json={"email": "admin@test.com"},
                          headers=get_auth_header(admin_token))
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════
# Security Headers & Health Check Tests
# ═══════════════════════════════════════════════════════════════════


class TestSecurityHeaders:

    def test_security_headers_present(self):
        resp = client.get("/api/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert "max-age=" in resp.headers["Strict-Transport-Security"]
        assert resp.headers["Content-Security-Policy"] == "default-src 'self'"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestHealthCheck:

    def test_health_check_no_auth_required(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "2.0.0"
