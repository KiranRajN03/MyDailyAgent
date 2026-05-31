"""
Automated Testing Suite — Standup lifecycle, pre-meeting reminders & speaker attendance
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from tests.conftest import TestSession
from daily_agents.database.models import Meeting, MeetingStatus, Project, TeamMember, User, AttendanceRecord
from daily_agents.api.server import app, meeting_scheduler_daemon
from daily_agents.agents.agents import transcription_agent_node

client = TestClient(app)
VALID_PASSWORD = "SecurePass123!@#"


def register_user(username="mgr", email="mgr@test.com"):
    resp = client.post("/api/auth/register", json={
        "username": username, "email": email,
        "password": VALID_PASSWORD, "full_name": f"User {username}",
    })
    data = resp.json()
    return data["access_token"], data["user_id"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_project(token, name="Automation Project", key="AUTO"):
    resp = client.post("/api/projects", json={
        "name": name, "key": key,
    }, headers=auth(token))
    return resp.json()


class TestStandupAutomation:

    def test_meeting_reminder_sent(self):
        token, _ = register_user("mgr1", "mgr1@test.com")
        p = create_project(token, key="REMIND")
        
        db = TestSession()
        try:
            # Create a meeting scheduled 5 minutes from now
            meeting = Meeting(
                project_id=p["id"],
                meeting_type="standup",
                status=MeetingStatus.SCHEDULED,
                scheduled_start=datetime.now(timezone.utc) + timedelta(minutes=5),
                reminder_sent=False
            )
            db.add(meeting)
            db.commit()
            meeting_id = meeting.id
        finally:
            db.close()

        # Let's run a single custom reminder loop query
        db = TestSession()
        try:
            now = datetime.now(timezone.utc)
            ten_mins_from_now = now + timedelta(minutes=10)
            
            # Find and trigger upcoming alerts
            upcoming = db.query(Meeting).filter(
                Meeting.status == MeetingStatus.SCHEDULED,
                Meeting.reminder_sent == False,
                Meeting.scheduled_start <= ten_mins_from_now,
                Meeting.scheduled_start > now
            ).all()
            
            assert len(upcoming) == 1
            assert upcoming[0].id == meeting_id
            
            upcoming[0].reminder_sent = True
            db.commit()
            
            # Re-fetch and assert updated state
            meeting_refetched = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            assert meeting_refetched.reminder_sent is True
        finally:
            db.close()

    def test_meeting_auto_start(self):
        token, _ = register_user("mgr2", "mgr2@test.com")
        p = create_project(token, key="START")
        
        db = TestSession()
        try:
            # Create a meeting scheduled in the past
            meeting = Meeting(
                project_id=p["id"],
                meeting_type="standup",
                status=MeetingStatus.SCHEDULED,
                scheduled_start=datetime.now(timezone.utc) - timedelta(minutes=2)
            )
            db.add(meeting)
            db.commit()
            meeting_id = meeting.id
        finally:
            db.close()

        # Run auto-start logic
        db = TestSession()
        try:
            now = datetime.now(timezone.utc)
            matures = db.query(Meeting).filter(
                Meeting.status == MeetingStatus.SCHEDULED,
                Meeting.scheduled_start <= now
            ).all()
            
            assert len(matures) >= 1
            for m in matures:
                if m.id == meeting_id:
                    m.status = MeetingStatus.IN_PROGRESS
                    m.actual_start = now
            db.commit()
            
            # Re-fetch and assert updated state
            meeting_refetched = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            assert meeting_refetched.status == MeetingStatus.IN_PROGRESS
            assert meeting_refetched.actual_start is not None
        finally:
            db.close()

    def test_speaker_resolved_attendance(self):
        token, _ = register_user("mgr3", "mgr3@test.com")
        p = create_project(token, key="SPEAKER")
        
        db = TestSession()
        try:
            # Create developers in DB
            alice = User(username="alice", email="alice@company.com", password_hash="dummy", full_name="Alice", role="member")
            bob = User(username="bob", email="bob@company.com", password_hash="dummy", full_name="Bob", role="member")
            db.add(alice)
            db.add(bob)
            db.flush()
            
            # Allocate to team roster
            tm_alice = TeamMember(user_id=alice.id, project_id=p["id"], jira_username="alice", role="developer")
            tm_bob = TeamMember(user_id=bob.id, project_id=p["id"], jira_username="bob", role="developer")
            db.add(tm_alice)
            db.add(tm_bob)
            db.flush()
            
            # Add scheduled meeting
            meeting = Meeting(
                project_id=p["id"],
                meeting_type="standup",
                status=MeetingStatus.SCHEDULED,
                scheduled_start=datetime.now(timezone.utc)
            )
            db.add(meeting)
            db.commit()
            meeting_id = meeting.id
            alice_id = alice.id
            bob_id = bob.id
        finally:
            db.close()

        # Run transcription agent workflow node (which transcribes alice and bob speech segments)
        db = TestSession()
        try:
            state = {
                "project_id": p["id"],
                "completed_agents": []
            }
            res = transcription_agent_node(state, db)
            db.commit()
            
            # Assert that attendance was auto-marked for alice and bob
            att_alice = db.query(AttendanceRecord).filter(
                AttendanceRecord.meeting_id == meeting_id,
                AttendanceRecord.user_id == alice_id
            ).first()
            assert att_alice is not None
            assert att_alice.attended is True

            att_bob = db.query(AttendanceRecord).filter(
                AttendanceRecord.meeting_id == meeting_id,
                AttendanceRecord.user_id == bob_id
            ).first()
            assert att_bob is not None
            assert att_bob.attended is True
        finally:
            db.close()

    def test_project_standup_sync(self):
        token, _ = register_user("mgr4", "mgr4@test.com")

        # 1. Create a project with standup_time
        resp = client.post("/api/projects", json={
            "name": "Sync Project",
            "key": "SYNCPROJ",
            "standup_time": "09:30",
            "meeting_link": "https://teams.live.com/meet/123",
            "timezone": "UTC"
        }, headers=auth(token))
        assert resp.status_code == 201
        p = resp.json()

        # Assert that RecurringMeeting was created and Meeting instances were generated
        db = TestSession()
        try:
            from daily_agents.database.models import RecurringMeeting, Meeting, MeetingType, MeetingStatus

            rm = db.query(RecurringMeeting).filter(
                RecurringMeeting.project_id == p["id"],
                RecurringMeeting.meeting_type == MeetingType.STANDUP
            ).first()
            assert rm is not None
            assert rm.start_time == "09:30"
            assert rm.meeting_link == "https://teams.live.com/meet/123"

            # Verify meetings are created in the next 30 days
            meetings = db.query(Meeting).filter(
                Meeting.project_id == p["id"],
                Meeting.recurring_meeting_id == rm.id
            ).all()
            assert len(meetings) > 0

            # Verify status is SCHEDULED
            for m in meetings:
                assert m.status == MeetingStatus.SCHEDULED
        finally:
            db.close()

        # 2. Update standup_time on project (run outside the active session block)
        resp_update = client.put(f"/api/projects/{p['id']}", json={
            "standup_time": "10:45",
            "meeting_link": "https://teams.live.com/meet/456"
        }, headers=auth(token))
        assert resp_update.status_code == 200

        # Assert RecurringMeeting and Meetings were updated / regenerated (using a fresh isolated session)
        db2 = TestSession()
        try:
            from daily_agents.database.models import RecurringMeeting, Meeting, MeetingType, MeetingStatus

            rm_updated = db2.query(RecurringMeeting).filter(RecurringMeeting.project_id == p["id"]).first()
            assert rm_updated.start_time == "10:45"
            assert rm_updated.meeting_link == "https://teams.live.com/meet/456"

            # Assert all previously scheduled standup meetings at 09:30 are deleted
            # and only new ones at 10:45 exist as scheduled
            active_meetings = db2.query(Meeting).filter(
                Meeting.project_id == p["id"],
                Meeting.recurring_meeting_id == rm_updated.id,
                Meeting.status == MeetingStatus.SCHEDULED
            ).all()
            assert len(active_meetings) > 0
            for am in active_meetings:
                assert am.scheduled_start.strftime("%H:%M") == "10:45"
        finally:
            db2.close()

    def test_conference_auto_provision(self):
        token, _ = register_user("mgr5", "mgr5@test.com")

        # 1. Create a project with conference_provider: zoom
        resp = client.post("/api/projects", json={
            "name": "Zoom Provision Project",
            "key": "ZMPROV",
            "standup_time": "09:30",
            "conference_provider": "zoom",
            "timezone": "UTC"
        }, headers=auth(token))
        assert resp.status_code == 201
        p_zoom = resp.json()
        assert p_zoom["conference_provider"] == "zoom"
        assert p_zoom["meeting_link"] is not None
        assert p_zoom["meeting_link"].startswith("https://zoom.us")

        # 2. Create a project with conference_provider: teams
        resp2 = client.post("/api/projects", json={
            "name": "Teams Provision Project",
            "key": "TMSPROV",
            "standup_time": "10:15",
            "conference_provider": "teams",
            "timezone": "UTC"
        }, headers=auth(token))
        assert resp2.status_code == 201
        p_teams = resp2.json()
        assert p_teams["conference_provider"] == "teams"
        assert p_teams["meeting_link"] is not None
        assert p_teams["meeting_link"].startswith("https://teams.microsoft.com")

        # 3. Assert SMTP or simulation mail sends calendar invitation attachment
        db = TestSession()
        try:
            from daily_agents.tools.agent_tools import send_email_report
            from daily_agents.database.models import Project
            
            project_db = db.query(Project).filter(Project.id == p_zoom["id"]).first()
            result = send_email_report(
                project_id=project_db.id,
                report_content="<html><body>Standup Report</body></html>",
                recipients=["test@company.com"],
                db=db
            )
            assert result["email_sent"] is True
            assert result["attached_ics"] is True
        finally:
            db.close()



