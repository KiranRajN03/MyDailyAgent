"""
Phase 2 Tests — Authentication & RBAC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for registration, login, JWT, RBAC, password reset,
First-User Rule, and admin user management.
"""

import os

# Set test env vars before importing ANYTHING from the app
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-minimum-64-chars-abcdefghijklmnopq"
os.environ["DB_ENCRYPTION_KEY"] = ""  # Auto-generate
# Force SQLite in-memory for tests via DATABASE_URL
os.environ["DATABASE_URL"] = "sqlite:///file::memory:?cache=shared&uri=true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# Now import app modules — they'll use the env vars above
from daily_agents.database.config import Base, get_db, engine as app_engine
from daily_agents.database.models import User, UserRole
from daily_agents.api.dependencies import hash_password
from daily_agents.api.server import app

# Use the app's own engine (which now points to memory via DATABASE_URL)
# But create a separate test engine for isolation
TEST_DB_URL = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"
TEST_ENGINE = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(TEST_ENGINE, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# Valid test password meeting all requirements
VALID_PASSWORD = "SecurePass123!@#"
VALID_PASSWORD_2 = "AnotherPass456!@#"


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables before each test, drop after."""
    # Import models to ensure they're registered with Base
    import daily_agents.database.models  # noqa: F401
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    # Drop all data by dropping and recreating tables
    Base.metadata.drop_all(bind=TEST_ENGINE)


def register_user(
    username="testuser",
    email="test@example.com",
    password=VALID_PASSWORD,
    full_name="Test User",
):
    """Helper to register a user via API."""
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
    """Build Authorization header."""
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════
# Registration Tests
# ═══════════════════════════════════════════════════════════════════


class TestRegistration:
    """REQ-AUTH-001 to REQ-AUTH-006, REQ-ROLE-001, REQ-ROLE-002."""

    def test_first_user_becomes_admin(self):
        """REQ-ROLE-001: First registered user is Admin."""
        resp = register_user()
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "admin"
        assert data["username"] == "testuser"
        assert "access_token" in data

    def test_second_user_becomes_member(self):
        """REQ-ROLE-002: Subsequent users get Member role."""
        register_user(username="admin1", email="admin@test.com")
        resp = register_user(username="member1", email="member@test.com")
        assert resp.status_code == 201
        assert resp.json()["role"] == "member"

    def test_duplicate_username_rejected(self):
        """REQ-AUTH-006: Reject duplicate usernames."""
        register_user(username="dup", email="dup1@test.com")
        resp = register_user(username="dup", email="dup2@test.com")
        assert resp.status_code == 409
        assert "Username already exists" in resp.json()["detail"]

    def test_duplicate_email_rejected(self):
        """REQ-AUTH-006: Reject duplicate emails."""
        register_user(username="user1", email="same@test.com")
        resp = register_user(username="user2", email="same@test.com")
        assert resp.status_code == 409
        assert "Email already registered" in resp.json()["detail"]

    def test_invalid_username_format(self):
        """REQ-AUTH-002: Username validation."""
        resp = register_user(username="bad user!")
        assert resp.status_code == 422

    def test_short_username_rejected(self):
        """REQ-AUTH-002: Username min 3 chars."""
        resp = register_user(username="ab")
        assert resp.status_code == 422

    def test_password_missing_uppercase(self):
        """REQ-AUTH-004: Password requires uppercase."""
        resp = register_user(password="nouppercase123!@#")
        assert resp.status_code == 422

    def test_password_missing_lowercase(self):
        """REQ-AUTH-004: Password requires lowercase."""
        resp = register_user(password="NOLOWERCASE123!@#")
        assert resp.status_code == 422

    def test_password_missing_digit(self):
        """REQ-AUTH-004: Password requires digit."""
        resp = register_user(password="NoDigitsHere!@#abc")
        assert resp.status_code == 422

    def test_password_missing_special(self):
        """REQ-AUTH-004: Password requires special character."""
        resp = register_user(password="NoSpecialChar1234")
        assert resp.status_code == 422

    def test_password_too_short(self):
        """REQ-AUTH-004: Password min 12 chars."""
        resp = register_user(password="Short1!")
        assert resp.status_code == 422

    def test_returns_jwt_on_success(self):
        """REQ-AUTH-011: Successful registration returns JWT."""
        resp = register_user()
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0


# ═══════════════════════════════════════════════════════════════════
# Login Tests
# ═══════════════════════════════════════════════════════════════════


class TestLogin:
    """REQ-AUTH-010 to REQ-AUTH-015."""

    def test_successful_login(self):
        """REQ-AUTH-010: Valid credentials return JWT."""
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
        """REQ-AUTH-010: Invalid password returns 401."""
        register_user()
        resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "WrongPass123!@#"},
        )
        assert resp.status_code == 401

    def test_nonexistent_user(self):
        """REQ-AUTH-010: Nonexistent user returns 401."""
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": VALID_PASSWORD},
        )
        assert resp.status_code == 401

    def test_deactivated_user_cannot_login(self):
        """Deactivated users get 403."""
        # Register admin + member
        admin_resp = register_user(username="admin", email="admin@test.com")
        admin_token = admin_resp.json()["access_token"]
        member_resp = register_user(username="member", email="member@test.com")
        member_id = member_resp.json()["user_id"]

        # Admin deactivates member
        client.put(
            f"/api/users/{member_id}",
            json={"is_active": False},
            headers=get_auth_header(admin_token),
        )

        # Member tries to login
        resp = client.post(
            "/api/auth/login",
            json={"username": "member", "password": VALID_PASSWORD},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# JWT & Current User Tests
# ═══════════════════════════════════════════════════════════════════


class TestJWTAuth:
    """REQ-SEC-008: All endpoints require JWT."""

    def test_me_endpoint_with_valid_token(self):
        """Authenticated user can access /api/auth/me."""
        resp = register_user()
        token = resp.json()["access_token"]

        me_resp = client.get("/api/auth/me", headers=get_auth_header(token))
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_me_endpoint_without_token(self):
        """No token returns 401."""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_endpoint_with_invalid_token(self):
        """Invalid token returns 401."""
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
# Password Reset Tests
# ═══════════════════════════════════════════════════════════════════


class TestPasswordReset:
    """REQ-AUTH-020 to REQ-AUTH-026."""

    def test_forgot_password_existing_email(self):
        """REQ-AUTH-021: Returns success for existing email."""
        register_user()
        resp = client.post(
            "/api/auth/forgot-password",
            json={"email": "test@example.com"},
        )
        assert resp.status_code == 200

    def test_forgot_password_nonexistent_email(self):
        """REQ-AUTH-021: Returns same success for non-existent email."""
        resp = client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert resp.status_code == 200

    def test_reset_password_with_valid_token(self):
        """REQ-AUTH-022 to REQ-AUTH-024: Reset works with valid token."""
        register_user()

        # Generate reset token
        client.post(
            "/api/auth/forgot-password",
            json={"email": "test@example.com"},
        )

        # Get the reset token from the database
        db = TestSession()
        user = db.query(User).filter(User.username == "testuser").first()
        token = user.reset_token
        db.close()

        assert token is not None

        # Reset password
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD_2},
        )
        assert resp.status_code == 200

        # Login with new password
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": VALID_PASSWORD_2},
        )
        assert login_resp.status_code == 200

        # Old password no longer works
        old_resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": VALID_PASSWORD},
        )
        assert old_resp.status_code == 401

    def test_reset_password_invalid_token(self):
        """Invalid token returns 400."""
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": "fake-token", "new_password": VALID_PASSWORD_2},
        )
        assert resp.status_code == 400

    def test_reset_token_is_single_use(self):
        """REQ-AUTH-024: Token cleared after use."""
        register_user()
        client.post(
            "/api/auth/forgot-password",
            json={"email": "test@example.com"},
        )

        db = TestSession()
        user = db.query(User).filter(User.username == "testuser").first()
        token = user.reset_token
        db.close()

        # First use succeeds
        resp1 = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD_2},
        )
        assert resp1.status_code == 200

        # Second use fails (token cleared)
        resp2 = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": VALID_PASSWORD},
        )
        assert resp2.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# RBAC Tests
# ═══════════════════════════════════════════════════════════════════


class TestRBAC:
    """Section 2.1, 2.2: Role-based access control."""

    def _setup_users(self):
        """Register an admin + a member, return their tokens."""
        admin = register_user(username="admin", email="admin@test.com")
        member = register_user(username="member", email="member@test.com")
        return admin.json()["access_token"], member.json()["access_token"]

    def test_admin_can_list_users(self):
        """Admin (Manager+) can GET /api/users."""
        admin_token, _ = self._setup_users()
        resp = client.get("/api/users", headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_member_cannot_list_users(self):
        """Member cannot GET /api/users (requires Manager+)."""
        _, member_token = self._setup_users()
        resp = client.get("/api/users", headers=get_auth_header(member_token))
        assert resp.status_code == 403

    def test_admin_can_create_user(self):
        """Admin can POST /api/users."""
        admin_token, _ = self._setup_users()
        resp = client.post(
            "/api/users",
            json={
                "username": "newuser",
                "email": "new@test.com",
                "password": VALID_PASSWORD,
                "role": "manager",
            },
            headers=get_auth_header(admin_token),
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "manager"

    def test_member_cannot_create_user(self):
        """Member cannot POST /api/users (requires Admin)."""
        _, member_token = self._setup_users()
        resp = client.post(
            "/api/users",
            json={
                "username": "hack",
                "email": "hack@test.com",
                "password": VALID_PASSWORD,
            },
            headers=get_auth_header(member_token),
        )
        assert resp.status_code == 403

    def test_admin_can_get_user_details(self):
        """Admin can GET /api/users/{id}."""
        admin_token, _ = self._setup_users()
        resp = client.get("/api/users/1", headers=get_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_admin_can_update_user_role(self):
        """Admin can change user role."""
        admin_token, _ = self._setup_users()
        resp = client.put(
            "/api/users/2",
            json={"role": "team_lead"},
            headers=get_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "team_lead"

    def test_admin_can_deactivate_user(self):
        """REQ-AUTH-032: Admin soft-disables user."""
        admin_token, _ = self._setup_users()
        resp = client.put(
            "/api/users/2",
            json={"is_active": False},
            headers=get_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_update_nonexistent_user_returns_404(self):
        """PUT /api/users/999 returns 404."""
        admin_token, _ = self._setup_users()
        resp = client.put(
            "/api/users/999",
            json={"role": "admin"},
            headers=get_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_email_conflict_on_update(self):
        """REQ-AUTH-033: Cannot set duplicate email."""
        admin_token, _ = self._setup_users()
        resp = client.put(
            "/api/users/2",
            json={"email": "admin@test.com"},  # already used by user 1
            headers=get_auth_header(admin_token),
        )
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════
# Security Header Tests
# ═══════════════════════════════════════════════════════════════════


class TestSecurityHeaders:
    """REQ-SEC-004: Security headers on all responses."""

    def test_security_headers_present(self):
        """All required security headers are set."""
        resp = client.get("/api/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert "max-age=" in resp.headers["Strict-Transport-Security"]
        assert resp.headers["Content-Security-Policy"] == "default-src 'self'"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


# ═══════════════════════════════════════════════════════════════════
# Health Check Tests
# ═══════════════════════════════════════════════════════════════════


class TestHealthCheck:
    """REQ-OBS-002: Health check endpoint."""

    def test_health_check_no_auth_required(self):
        """Health check does not require authentication."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "workers" in data
        assert "active_threads" in data
        assert data["version"] == "2.0.0"
