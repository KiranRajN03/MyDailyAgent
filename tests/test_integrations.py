"""
Phase 5 Tests — External Integrations & Bot Logic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TestSession
from daily_agents.database.models import User, Project, UserRole
from daily_agents.api.server import app
from daily_agents.integrations.jira_client import fetch_jira_sprint_issues
from daily_agents.integrations.azure_speech import transcribe_meeting_audio

client = TestClient(app)

VALID_PASSWORD = "SecurePass123!@#"


# ─── Helpers ─────────────────────────────────────────────────────────

def register_user(username="mgr", email="mgr@test.com", role=UserRole.MANAGER):
    # Scrub spaces from username to pass Pydantic schema validation constraints
    scrubbed_username = username.replace(" ", "_").lower()
    full_name = f"User {username}"
    resp = client.post("/api/auth/register", json={
        "username": scrubbed_username, "email": email,
        "password": VALID_PASSWORD, "full_name": full_name,
    })
    data = resp.json()
    token = data["access_token"]
    user_id = data["user_id"]

    # If role needs to be explicitly MANAGER / ADMIN, update in DB
    with TestSession() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.role = role
            db.commit()

    return token, user_id, role


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_project(token, name="Agent Project", key="AGNT"):
    resp = client.post("/api/projects", json={
        "name": name, "key": key,
        "timezone": "UTC", "sprint_duration_days": 14,
    }, headers=auth(token))
    return resp.json()


# ═══════════════════════════════════════════════════════════════════
# 1. Jira & Azure Speech Integrations Tests
# ═══════════════════════════════════════════════════════════════════

class TestExternalIntegrationsClients:

    @pytest.mark.asyncio
    async def test_jira_sprint_fetch_fallback(self):
        token, _, _ = register_user()
        p_data = create_project(token)
        
        with TestSession() as db:
            project = db.query(Project).filter(Project.id == p_data["id"]).first()
            assert project is not None
            
            # Invoke real JIRA client with no keys (trigger mock fallback)
            issues = await fetch_jira_sprint_issues(project)
            assert len(issues) == 4
            assert issues[0]["key"] == "AGNT-101"
            assert issues[1]["status"] == "Done"

    @pytest.mark.asyncio
    async def test_azure_speech_transcribe_fallback(self):
        # Invoke transcription log with blank WAV bytes
        audio_data = b"RIFF....WAVEfmt..."
        segments = await transcribe_meeting_audio(audio_data)
        assert len(segments) == 3
        assert segments[0]["speaker"] == "alice"
        assert "password reset flow" in segments[0]["text"]
        assert segments[1]["confidence"] == 0.94


# ═══════════════════════════════════════════════════════════════════
# 2. Teams Webhook Route Tests
# ═══════════════════════════════════════════════════════════════════

class TestTeamsBotWebhookRouter:

    def test_teams_webhook_sync_sprint(self):
        token, user_id, _ = register_user("Yashika Kiran", "yashika@test.com", UserRole.MANAGER)
        p = create_project(token)

        # Trigger Outgoing Webhook for Jira sync
        resp = client.post(
            "/api/teams/messages",
            json={
                "type": "message",
                "text": "<at>myDailyAgent</at> Please sync sprint issues",
                "from": {"id": "29:abc", "name": "User Yashika Kiran"},
                "channelId": "chan-123",
                "tenantId": "tenant-123"
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "message"
        assert "Sprint Sync Complete" in data["text"]
        assert "AGNT Sprint 1" in data["text"]

    def test_teams_webhook_employee_analytics(self):
        token, _, _ = register_user("Yashika Kiran", "yashika@test.com", UserRole.MANAGER)
        p = create_project(token)

        # Trigger Outgoing Webhook for analytics
        resp = client.post(
            "/api/teams/messages",
            json={
                "type": "message",
                "text": "<at>myDailyAgent</at> Compute employee performance metrics",
                "from": {"id": "29:abc", "name": "User Yashika Kiran"},
            }
        )
        assert resp.status_code == 200
        assert "Team Performance Analytics" in resp.json()["text"]


# ═══════════════════════════════════════════════════════════════════
# 3. Forgot Password SMTP Dispatch Route Tests
# ═══════════════════════════════════════════════════════════════════

class TestForgotPasswordSMTPTrigger:

    def test_forgot_password_triggers_email(self):
        register_user("resetuser", "reset@test.com")

        # Post to forgot password route
        resp = client.post(
            "/api/auth/forgot-password",
            json={"email": "reset@test.com"}
        )
        assert resp.status_code == 200
        assert "reset link has been sent" in resp.json()["message"]

        # Assert token and expiry were saved to DB
        with TestSession() as db:
            user = db.query(User).filter(User.email == "reset@test.com").first()
            assert user.reset_token is not None
            assert user.reset_token_expiry is not None
