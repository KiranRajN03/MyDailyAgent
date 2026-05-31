"""
Zoom Webhooks Integration Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Covers URL challenge handshakes, chatbot commands, and autonomous meeting summarization dispatches.
"""

import pytest
import hmac
import hashlib
from fastapi.testclient import TestClient

from daily_agents.api.server import app
from daily_agents.database.models import User, MeetingTranscript
from tests.conftest import TestSession

client = TestClient(app)

VALID_PASSWORD = "SecurePass123!@#"


# ─── Helpers ─────────────────────────────────────────────────────────

def register_user(username="admin", email="admin@test.com"):
    resp = client.post("/api/auth/register", json={
        "username": username, "email": email,
        "password": VALID_PASSWORD, "full_name": f"User {username}",
    })
    data = resp.json()
    return data["access_token"], data["user_id"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_project(token, name="Zoom Project", key="ZOM"):
    resp = client.post("/api/projects", json={
        "name": name, "key": key,
    }, headers=auth(token))
    return resp.json()


# ═══════════════════════════════════════════════════════════════════
# Zoom Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestZoomIntegrations:

    def test_zoom_url_validation_handshake(self):
        """Option B Handshake: Asserts challenge signature encryption works correctly."""
        plain_token = "challenge-token-xyz-12345"
        
        # In a real environment, we'd pull secret key from settings
        # We can compute the signature locally to verify parity
        secret = "zoom-secret-key-signature" # default fallback
        expected_encrypted = hmac.new(
            secret.encode("utf-8"),
            plain_token.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        resp = client.post(
            "/api/zoom/recordings",
            json={
                "event": "endpoint.url_validation",
                "payload": {
                    "plainToken": plain_token
                }
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plainToken"] == plain_token
        assert data["encryptedToken"] == expected_encrypted

    def test_zoom_chatbot_message_routing_option_a(self):
        """Option A: Chat App chatbot command dispatches graph routing correctly."""
        token, user_id = register_user("zoomuser", "zoom@test.com")
        p = create_project(token)

        # Allocate user as team member to project
        client.post(f"/api/projects/{p['id']}/team", json={
            "user_id": user_id, "role": "developer"
        }, headers=auth(token))

        payload = {
            "event": "bot_notification",
            "payload": {
                "cmd": "Sync sprint issues",
                "userId": "zoomuser",
                "userName": "User zoomuser",
                "robotJid": "zoom-robot-jid-xyz"
            }
        }

        resp = client.post(
            f"/api/zoom/messages?project_id={p['id']}",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["robotJid"] == "zoom-robot-jid-xyz"
        assert "content" in data
        assert "body" in data["content"]
        assert "sync complete" in data["content"]["body"][0]["text"].lower()

    def test_zoom_recording_completed_autonomous_pipeline_option_b(self):
        """Option B: Recording completed event automatically executes transcription & emails report."""
        token, user_id = register_user("zoomowner", "zoomowner@test.com")
        p = create_project(token)

        # Allocate user as team member to project
        client.post(f"/api/projects/{p['id']}/team", json={
            "user_id": user_id, "role": "tech_lead"
        }, headers=auth(token))

        payload = {
            "event": "recording.completed",
            "payload": {
                "object": {
                    "id": "meeting-12345",
                    "uuid": "meeting-uuid-xyz",
                    "topic": "Daily Sprint Standup Meeting",
                    "recording_files": [
                        {
                            "file_type": "M4A",
                            "download_url": "https://zoom.us/rec/download/xyz"
                        }
                    ]
                }
            }
        }

        resp = client.post(
            f"/api/zoom/recordings?project_id={p['id']}",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["meeting_topic"] == "Daily Sprint Standup Meeting"
        assert data["transcription_status"] == "Success"
        assert data["email_sent"] is True
        
        # Verify database logging of transcripts
        db = TestSession()
        transcripts = db.query(MeetingTranscript).all()
        assert len(transcripts) > 0
        assert any(t.speaker == "alice" for t in transcripts)
        db.close()
