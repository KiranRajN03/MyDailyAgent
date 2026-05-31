"""
Phase 3 Tests — Project CRUD & Team Members
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import pytest
from fastapi.testclient import TestClient

from daily_agents.database.models import User, Project, TeamMember, UserRole
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
    return data["access_token"], data["user_id"], data["role"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_project(token, name="Test Project", key="TEST"):
    return client.post("/api/projects", json={
        "name": name, "key": key,
        "timezone": "UTC", "sprint_duration_days": 14,
    }, headers=auth(token))


# ═══════════════════════════════════════════════════════════════════
# Project CRUD Tests
# ═══════════════════════════════════════════════════════════════════


class TestProjectCreate:

    def test_manager_can_create_project(self):
        admin_token, admin_id, _ = register_user()
        resp = create_project(admin_token)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Project"
        assert data["key"] == "TEST"
        assert data["owner_id"] == admin_id
        assert data["is_active"] is True

    def test_member_cannot_create_project(self):
        register_user("admin", "admin@test.com")
        member_token, _, _ = register_user("member", "member@test.com")
        resp = create_project(member_token)
        assert resp.status_code == 403

    def test_duplicate_key_rejected(self):
        admin_token, _, _ = register_user()
        create_project(admin_token, "Project 1", "DUPE")
        resp = create_project(admin_token, "Project 2", "DUPE")
        assert resp.status_code == 409

    def test_invalid_key_format(self):
        admin_token, _, _ = register_user()
        resp = client.post("/api/projects", json={
            "name": "Bad Key", "key": "lowercase",
        }, headers=auth(admin_token))
        assert resp.status_code == 422

    def test_project_with_jira_config(self):
        admin_token, _, _ = register_user()
        resp = client.post("/api/projects", json={
            "name": "Jira Project", "key": "JIRA",
            "jira_base_url": "https://myteam.atlassian.net",
            "jira_email": "user@company.com",
            "jira_api_token": "abcdefghij1234567890",
            "jira_project_key": "JP",
        }, headers=auth(admin_token))
        assert resp.status_code == 201
        assert resp.json()["jira_base_url"] == "https://myteam.atlassian.net"

    def test_invalid_jira_url_rejected(self):
        admin_token, _, _ = register_user()
        resp = client.post("/api/projects", json={
            "name": "Bad Jira", "key": "BJIRA",
            "jira_base_url": "https://example.com",
        }, headers=auth(admin_token))
        assert resp.status_code == 422

    def test_project_with_meeting_config(self):
        admin_token, _, _ = register_user()
        resp = client.post("/api/projects", json={
            "name": "Meeting Project", "key": "MEET",
            "meeting_link": "https://meet.google.com/abc",
            "standup_time": "09:30",
            "reminder_time": "09:15",
        }, headers=auth(admin_token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["standup_time"] == "09:30"
        assert data["reminder_time"] == "09:15"

    def test_invalid_time_format_rejected(self):
        admin_token, _, _ = register_user()
        resp = client.post("/api/projects", json={
            "name": "Bad Time", "key": "BTIME",
            "standup_time": "9:30",
        }, headers=auth(admin_token))
        assert resp.status_code == 422


class TestProjectList:

    def test_admin_sees_all_projects(self):
        admin_token, _, _ = register_user()
        create_project(admin_token, "P1", "PRJ1")
        create_project(admin_token, "P2", "PRJ2")
        resp = client.get("/api/projects", headers=auth(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_member_sees_only_own_projects(self):
        admin_token, admin_id, _ = register_user("admin", "admin@test.com")
        member_token, member_id, _ = register_user("member", "member@test.com")

        p1 = create_project(admin_token, "Admin Project", "ADMN").json()
        p2 = create_project(admin_token, "Shared Project", "SHRD").json()

        client.post(f"/api/projects/{p2['id']}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(admin_token))

        resp = client.get("/api/projects", headers=auth(member_token))
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["key"] == "SHRD"

    def test_unauthenticated_cannot_list(self):
        resp = client.get("/api/projects")
        assert resp.status_code == 401


class TestProjectGetUpdateDelete:

    def test_get_project_by_id(self):
        admin_token, _, _ = register_user()
        p = create_project(admin_token).json()
        resp = client.get(f"/api/projects/{p['id']}", headers=auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["key"] == "TEST"

    def test_get_nonexistent_project(self):
        admin_token, _, _ = register_user()
        resp = client.get("/api/projects/999", headers=auth(admin_token))
        assert resp.status_code == 404

    def test_non_member_cannot_access_project(self):
        admin_token, _, _ = register_user("admin", "admin@test.com")
        member_token, _, _ = register_user("member", "member@test.com")
        p = create_project(admin_token).json()
        resp = client.get(f"/api/projects/{p['id']}", headers=auth(member_token))
        assert resp.status_code == 403

    def test_owner_can_update_project(self):
        admin_token, _, _ = register_user()
        p = create_project(admin_token).json()
        resp = client.put(f"/api/projects/{p['id']}", json={
            "name": "Updated Name", "standup_time": "10:00",
        }, headers=auth(admin_token))
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["standup_time"] == "10:00"

    def test_non_owner_cannot_update(self):
        admin_token, _, _ = register_user("admin", "admin@test.com")
        mgr_token, mgr_id, _ = register_user("manager", "mgr@test.com")
        client.put(f"/api/users/{mgr_id}", json={"role": "manager"},
                    headers=auth(admin_token))
        p = create_project(admin_token).json()
        resp = client.put(f"/api/projects/{p['id']}", json={"name": "Hacked"},
                          headers=auth(mgr_token))
        assert resp.status_code == 403

    def test_soft_delete_project(self):
        admin_token, _, _ = register_user()
        p = create_project(admin_token).json()
        resp = client.delete(f"/api/projects/{p['id']}", headers=auth(admin_token))
        assert resp.status_code == 200
        listing = client.get("/api/projects", headers=auth(admin_token))
        assert len(listing.json()) == 0

    def test_delete_nonexistent_project(self):
        admin_token, _, _ = register_user()
        resp = client.delete("/api/projects/999", headers=auth(admin_token))
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Team Member Tests
# ═══════════════════════════════════════════════════════════════════


class TestTeamMembers:

    def _setup(self):
        admin_token, admin_id, _ = register_user("admin", "admin@test.com")
        member_token, member_id, _ = register_user("member", "member@test.com")
        p = create_project(admin_token).json()
        return admin_token, admin_id, member_token, member_id, p["id"]

    def test_add_team_member(self):
        admin_token, _, _, member_id, project_id = self._setup()
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(admin_token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == member_id
        assert data["role"] == "developer"
        assert data["username"] == "member"

    def test_add_member_with_jira_username(self):
        admin_token, _, _, member_id, project_id = self._setup()
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "tech_lead",
            "jira_username": "member.jira",
        }, headers=auth(admin_token))
        assert resp.status_code == 201
        assert resp.json()["jira_username"] == "member.jira"

    def test_duplicate_member_rejected(self):
        admin_token, _, _, member_id, project_id = self._setup()
        client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(admin_token))
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "qa",
        }, headers=auth(admin_token))
        assert resp.status_code == 409

    def test_add_nonexistent_user(self):
        admin_token, _, _, _, project_id = self._setup()
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": 999, "role": "developer",
        }, headers=auth(admin_token))
        assert resp.status_code == 404

    def test_invalid_role_rejected(self):
        admin_token, _, _, member_id, project_id = self._setup()
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "ceo",
        }, headers=auth(admin_token))
        assert resp.status_code == 422

    def test_remove_team_member(self):
        admin_token, _, _, member_id, project_id = self._setup()
        add_resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(admin_token))
        tm_id = add_resp.json()["id"]
        resp = client.delete(f"/api/projects/{project_id}/team/{tm_id}",
                             headers=auth(admin_token))
        assert resp.status_code == 200

    def test_remove_nonexistent_member(self):
        admin_token, _, _, _, project_id = self._setup()
        resp = client.delete(f"/api/projects/{project_id}/team/999",
                             headers=auth(admin_token))
        assert resp.status_code == 404

    def test_member_cannot_manage_team(self):
        _, _, member_token, member_id, project_id = self._setup()
        resp = client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(member_token))
        assert resp.status_code == 403

    def test_list_team_members(self):
        admin_token, _, _, member_id, project_id = self._setup()
        client.post(f"/api/projects/{project_id}/team", json={
            "user_id": member_id, "role": "developer",
        }, headers=auth(admin_token))
        resp = client.get(f"/api/projects/{project_id}/team", headers=auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == member_id
        assert data[0]["role"] == "developer"

    def test_pm_dashboard_endpoint(self):
        admin_token, _, _, _, project_id = self._setup()
        resp = client.get(f"/api/projects/{project_id}/pm-dashboard", headers=auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "completed_jira" in data
        assert "total_active_issues" in data
        assert "stalled_count" in data
        assert "sprint_health" in data
        assert "stalled_issues" in data
        assert "assigned_per_person" in data
        assert "leaderboard" in data
