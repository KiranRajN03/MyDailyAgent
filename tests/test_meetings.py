"""
Phase 3 Tests — Meetings & Recurring Meetings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from daily_agents.database.models import Meeting, MeetingStatus
from daily_agents.api.server import app

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


def create_project(token, name="Test Project", key="TEST"):
    resp = client.post("/api/projects", json={
        "name": name, "key": key,
    }, headers=auth(token))
    return resp.json()


def future_time(hours=1):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def future_time_2h():
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Meeting CRUD Tests
# ═══════════════════════════════════════════════════════════════════


class TestMeetingCRUD:

    def test_create_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post("/api/meetings", json={
            "project_id": project["id"],
            "meeting_type": "standup",
            "scheduled_start": future_time(),
            "meeting_link": "https://meet.google.com/abc",
            "notes": "Daily standup",
        }, headers=auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["meeting_type"] == "standup"
        assert data["status"] == "scheduled"
        assert data["ical_uid"] is not None

    def test_create_sprint_planning(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post("/api/meetings", json={
            "project_id": project["id"],
            "meeting_type": "sprint_planning",
            "scheduled_start": future_time(),
            "scheduled_end": future_time_2h(),
        }, headers=auth(token))
        assert resp.status_code == 201
        assert resp.json()["meeting_type"] == "sprint_planning"

    def test_invalid_meeting_type_rejected(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post("/api/meetings", json={
            "project_id": project["id"],
            "meeting_type": "workshop",
            "scheduled_start": future_time(),
        }, headers=auth(token))
        assert resp.status_code == 422

    def test_create_meeting_nonexistent_project(self):
        token, _ = register_user()
        resp = client.post("/api/meetings", json={
            "project_id": 999,
            "meeting_type": "standup",
            "scheduled_start": future_time(),
        }, headers=auth(token))
        assert resp.status_code == 404

    def test_list_project_meetings(self):
        token, _ = register_user()
        project = create_project(token)
        for i in range(3):
            client.post("/api/meetings", json={
                "project_id": project["id"],
                "meeting_type": "standup",
                "scheduled_start": future_time(i + 1),
            }, headers=auth(token))
        resp = client.get(f"/api/projects/{project['id']}/meetings",
                          headers=auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_meeting_summary(self):
        token, _ = register_user()
        project = create_project(token)
        m = client.post("/api/meetings", json={
            "project_id": project["id"],
            "meeting_type": "standup",
            "scheduled_start": future_time(),
        }, headers=auth(token)).json()
        resp = client.get(f"/api/meetings/{m['id']}/summary",
                          headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["id"] == m["id"]

    def test_get_nonexistent_meeting(self):
        token, _ = register_user()
        resp = client.get("/api/meetings/999/summary", headers=auth(token))
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Meeting Lifecycle Tests
# ═══════════════════════════════════════════════════════════════════


class TestMeetingLifecycle:

    def _create_meeting(self, token, project_id):
        resp = client.post("/api/meetings", json={
            "project_id": project_id,
            "meeting_type": "standup",
            "scheduled_start": future_time(),
        }, headers=auth(token))
        return resp.json()

    def test_start_meeting(self):
        token, user_id = register_user()
        project = create_project(token)
        m = self._create_meeting(token, project["id"])
        resp = client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "in_progress"
        assert data["actual_start"] is not None
        assert data["started_by"] == user_id

    def test_stop_meeting(self):
        token, user_id = register_user()
        project = create_project(token)
        m = self._create_meeting(token, project["id"])
        client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        resp = client.post(f"/api/meetings/{m['id']}/stop", headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["actual_end"] is not None
        assert data["stopped_by"] == user_id

    def test_cannot_start_completed_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        m = self._create_meeting(token, project["id"])
        client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        client.post(f"/api/meetings/{m['id']}/stop", headers=auth(token))
        resp = client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        assert resp.status_code == 400

    def test_cannot_stop_scheduled_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        m = self._create_meeting(token, project["id"])
        resp = client.post(f"/api/meetings/{m['id']}/stop", headers=auth(token))
        assert resp.status_code == 400

    def test_cannot_start_already_running(self):
        token, _ = register_user()
        project = create_project(token)
        m = self._create_meeting(token, project["id"])
        client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        resp = client.post(f"/api/meetings/{m['id']}/start", headers=auth(token))
        assert resp.status_code == 400

    def test_start_nonexistent_meeting(self):
        token, _ = register_user()
        resp = client.post("/api/meetings/999/start", headers=auth(token))
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Recurring Meeting Tests
# ═══════════════════════════════════════════════════════════════════


class TestRecurringMeetings:

    def test_create_recurring_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post(
            f"/api/projects/{project['id']}/recurring-meetings",
            json={
                "meeting_type": "standup",
                "start_time": "09:00",
                "end_time": "09:15",
                "days_of_week": "monday,wednesday,friday",
                "timezone": "UTC",
                "meeting_link": "https://meet.google.com/daily",
                "description": "Daily standup",
            },
            headers=auth(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["meeting_type"] == "standup"
        assert data["start_time"] == "09:00"
        assert data["is_active"] is True

    def test_recurring_generates_meetings(self):
        token, _ = register_user()
        project = create_project(token)
        client.post(
            f"/api/projects/{project['id']}/recurring-meetings",
            json={
                "meeting_type": "standup",
                "start_time": "09:00",
                "days_of_week": "monday,tuesday,wednesday,thursday,friday",
            },
            headers=auth(token),
        )
        meetings = client.get(
            f"/api/projects/{project['id']}/meetings",
            headers=auth(token),
        ).json()
        assert len(meetings) > 0
        for m in meetings:
            assert m["status"] == "scheduled"
            assert m["ical_uid"] is not None

    def test_list_recurring_meetings(self):
        token, _ = register_user()
        project = create_project(token)
        client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "09:00",
            "days_of_week": "monday,wednesday,friday",
        }, headers=auth(token))
        client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "retrospective", "start_time": "14:00",
            "days_of_week": "friday",
        }, headers=auth(token))
        resp = client.get(f"/api/projects/{project['id']}/recurring-meetings",
                          headers=auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_update_recurring_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        rm = client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "09:00",
            "days_of_week": "monday,wednesday,friday",
        }, headers=auth(token)).json()
        resp = client.put(f"/api/recurring-meetings/{rm['id']}", json={
            "start_time": "10:00", "days_of_week": "tuesday,thursday",
        }, headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "10:00"
        assert data["days_of_week"] == "tuesday,thursday"

    def test_delete_recurring_meeting(self):
        token, _ = register_user()
        project = create_project(token)
        rm = client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "09:00",
            "days_of_week": "monday,wednesday,friday",
        }, headers=auth(token)).json()
        resp = client.delete(f"/api/recurring-meetings/{rm['id']}",
                             headers=auth(token))
        assert resp.status_code == 200
        configs = client.get(f"/api/projects/{project['id']}/recurring-meetings",
                             headers=auth(token)).json()
        assert len(configs) == 0

    def test_delete_nonexistent_recurring(self):
        token, _ = register_user()
        resp = client.delete("/api/recurring-meetings/999", headers=auth(token))
        assert resp.status_code == 404

    def test_invalid_days_rejected(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "09:00",
            "days_of_week": "funday,partyday",
        }, headers=auth(token))
        assert resp.status_code == 422

    def test_invalid_time_format_rejected(self):
        token, _ = register_user()
        project = create_project(token)
        resp = client.post(f"/api/projects/{project['id']}/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "9am",
            "days_of_week": "monday",
        }, headers=auth(token))
        assert resp.status_code == 422

    def test_member_cannot_create_recurring(self):
        register_user("admin", "admin@test.com")
        member_token, _ = register_user("member", "member@test.com")
        resp = client.post("/api/projects", json={
            "name": "P", "key": "PP",
        }, headers=auth(member_token))
        assert resp.status_code == 403

    def test_nonexistent_project_rejected(self):
        token, _ = register_user()
        resp = client.post("/api/projects/999/recurring-meetings", json={
            "meeting_type": "standup", "start_time": "09:00",
            "days_of_week": "monday",
        }, headers=auth(token))
        assert resp.status_code == 404


class TestMeetingAttendance:

    def _setup_meeting(self):
        token, user_id = register_user("adm", "adm@test.com")
        project = create_project(token, "Proj", "PRJ")
        # Allocate user as team member to project
        client.post(f"/api/projects/{project['id']}/team", json={
            "user_id": user_id, "role": "developer",
        }, headers=auth(token))
        
        m = client.post("/api/meetings", json={
            "project_id": project["id"],
            "meeting_type": "standup",
            "scheduled_start": future_time(),
        }, headers=auth(token)).json()
        return token, user_id, m["id"]

    def test_get_default_attendance(self):
        token, user_id, meeting_id = self._setup_meeting()
        resp = client.get(f"/api/meetings/{meeting_id}/attendance", headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == user_id
        assert data[0]["attended"] is False

    def test_save_and_retrieve_attendance(self):
        token, user_id, meeting_id = self._setup_meeting()
        # Save attendance
        save_resp = client.post(
            f"/api/meetings/{meeting_id}/attendance",
            json=[{"user_id": user_id, "attended": True, "late_by_minutes": 5}],
            headers=auth(token)
        )
        assert save_resp.status_code == 200
        
        # Get updated attendance
        resp = client.get(f"/api/meetings/{meeting_id}/attendance", headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["attended"] is True
        assert data[0]["late_by_minutes"] == 5
