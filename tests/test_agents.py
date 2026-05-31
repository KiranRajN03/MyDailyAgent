"""
Phase 4 Tests — AI Agents & LangGraph Orchestration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TestSession
from daily_agents.database.models import User, Project, TeamMember, UserRole, SprintAnalytics, EmployeeAnalytics
from daily_agents.api.server import app
from daily_agents.tools.agent_tools import (
    sync_jira_sprint_metrics,
    compute_employee_analytics,
    send_email_report,
)
from daily_agents.graph import run_agent_workflow

client = TestClient(app)

VALID_PASSWORD = "SecurePass123!@#"


# ─── Helpers ─────────────────────────────────────────────────────────

def register_user(username="mgr", email="mgr@test.com", role=UserRole.MANAGER):
    resp = client.post("/api/auth/register", json={
        "username": username, "email": email,
        "password": VALID_PASSWORD, "full_name": f"User {username}",
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
# 1. Agent Tools Unit Tests
# ═══════════════════════════════════════════════════════════════════

class TestAgentTools:

    def test_sync_jira_sprint_metrics(self):
        token, _, _ = register_user()
        p = create_project(token)
        
        with TestSession() as db:
            # Sync sprint metrics
            res = sync_jira_sprint_metrics(p["id"], db)
            assert res["sprint_name"] == "AGNT Sprint 1"
            assert res["completion_rate"] == 50.0
            assert res["jira_sync_status"] == "Success"

            # Assert DB entry was created
            sprint = db.query(SprintAnalytics).filter(SprintAnalytics.project_id == p["id"]).first()
            assert sprint is not None
            assert sprint.sprint_name == "AGNT Sprint 1"
            assert sprint.completed_issues == 2
            assert sprint.total_issues == 4

    def test_compute_employee_analytics(self):
        token, mgr_id, _ = register_user("mgr", "mgr@test.com", UserRole.MANAGER)
        _, dev_id, _ = register_user("developer1", "dev1@test.com", UserRole.MEMBER)
        p = create_project(token)

        # Add team member
        client.post(f"/api/projects/{p['id']}/team", json={
            "user_id": dev_id, "role": "developer",
        }, headers=auth(token))

        with TestSession() as db:
            res_list = compute_employee_analytics(p["id"], "2026-05", db)
            assert len(res_list) > 0
            
            # Verify calculation correctness
            dev_stat = [r for r in res_list if r["username"] == "developer1"][0]
            assert dev_stat["role"] == "developer"
            assert dev_stat["issues_completed"] == 12
            assert dev_stat["attendance_rate"] == 80.0
            assert dev_stat["contribution_score"] == 92.0  # (80 * 0.4) + (100 * 0.6)
            assert "Standup Star" in dev_stat["badges"]
            assert "Bug Squasher" in dev_stat["badges"]

            # Assert DB entry was saved
            db_anal = db.query(EmployeeAnalytics).filter(
                EmployeeAnalytics.project_id == p["id"],
                EmployeeAnalytics.user_id == dev_id
            ).first()
            assert db_anal is not None
            assert db_anal.contribution_score == 92.0

    def test_send_email_report(self):
        token, _, _ = register_user()
        p = create_project(token)

        with TestSession() as db:
            # Send report content
            report_res = send_email_report(p["id"], "<p>Test report</p>", db=db)
            assert report_res["email_sent"] is True
            assert "Simulation" in report_res["mode"]


# ═══════════════════════════════════════════════════════════════════
# 2. LangGraph Execution Workflow Integration Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_agent_graph_state_routing():
    token, user_id, _ = register_user()
    p = create_project(token)

    # Mock dynamic dev user in the project
    _, dev_id, _ = register_user("developer1", "dev1@test.com", UserRole.MEMBER)
    client.post(f"/api/projects/{p['id']}/team", json={
        "user_id": dev_id, "role": "developer",
    }, headers=auth(token))

    with TestSession() as db:
        # Trigger workflow for Jira Sync
        state = await run_agent_workflow(p["id"], user_id, "Please sync our sprint issues from Jira status.", db)
        assert state["status"] == "completed"
        assert "jira_agent" in state["completed_agents"]
        assert state["sprint_data"]["sprint_name"] == "AGNT Sprint 1"
        assert "sync complete" in state["final_response"].lower() or "sprint sync complete" in state["final_response"].lower()

        # Trigger workflow for Employee Analytics
        state_da = await run_agent_workflow(p["id"], user_id, "Compute team performance metrics analytics scores.", db)
        assert state_da["status"] == "completed"
        assert "data_analyst" in state_da["completed_agents"]
        assert len(state_da["employee_data"]) > 0
        assert "team performance analytics" in state_da["final_response"].lower()

        # Trigger workflow for Transcription
        state_tr = await run_agent_workflow(p["id"], user_id, "Transcribe standup recording audio.", db)
        assert state_tr["status"] == "completed"
        assert "transcription_agent" in state_tr["completed_agents"]

        # Trigger workflow for Email automation
        state_email = await run_agent_workflow(p["id"], user_id, "Send an email report summary of our sprint now.", db)
        assert state_email["status"] == "completed"
        assert "automation_agent" in state_email["completed_agents"]
        assert state_email["email_sent"] is True
        # Assert transcription section is successfully compiled inside the HTML report body!
        assert "Standup Meeting Status Summaries" in state_email["report_content"]
        assert "alice" in state_email["report_content"]


# ═══════════════════════════════════════════════════════════════════
# 3. FastAPI Route Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestAgentFastAPIRoutes:

    def test_authenticated_owner_can_chat(self):
        token, _, _ = register_user()
        p = create_project(token)

        # Trigger Jira sync endpoint chat
        resp = client.post(
            f"/api/projects/{p['id']}/agent/chat",
            json={"message": "Pull sprint issues from Jira"},
            headers=auth(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "jira_agent" in data["completed_agents"]
        assert "Sprint 1" in data["response"]

    def test_non_member_access_rejected(self):
        token, _, _ = register_user("owner", "owner@test.com")
        other_token, _, _ = register_user("hacker", "hacker@test.com")
        p = create_project(token)

        resp = client.post(
            f"/api/projects/{p['id']}/agent/chat",
            json={"message": "Pull sprint issues"},
            headers=auth(other_token)
        )
        assert resp.status_code == 403
        assert "access" in resp.json()["detail"].lower()

    def test_unauthenticated_chat_rejected(self):
        token, _, _ = register_user()
        p = create_project(token)

        resp = client.post(
            f"/api/projects/{p['id']}/agent/chat",
            json={"message": "Pull sprint issues"}
        )
        assert resp.status_code == 401

    def test_transcription_agent_routing_and_db_persistence(self):
        token, user_id, _ = register_user("owner", "owner@test.com")
        p = create_project(token)

        # Allocate user as team member to project
        client.post(f"/api/projects/{p['id']}/team", json={
            "user_id": user_id, "role": "developer"
        }, headers=auth(token))

        # Invoke chat with a transcription query
        resp = client.post(
            f"/api/projects/{p['id']}/agent/chat",
            json={"message": "Please transcribe our meeting recording audio"},
            headers=auth(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "transcription_agent" in data["completed_agents"]
        assert "alice" in data["response"]
        
        # Verify that transcripts were persisted inside the database!
        db = TestSession()
        from daily_agents.database.models import MeetingTranscript
        transcripts = db.query(MeetingTranscript).all()
        assert len(transcripts) > 0
        assert any(t.speaker == "alice" for t in transcripts)
        db.close()
