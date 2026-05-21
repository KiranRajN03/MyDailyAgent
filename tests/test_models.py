"""
Phase 1 Smoke Tests
~~~~~~~~~~~~~~~~~~~
Verify that all models create tables successfully and that
Fernet encryption round-trips correctly.
"""

import os
import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

# Set test encryption keys before importing app modules
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-minimum-64-chars-abcdefghijklmnopq"
os.environ["DB_ENCRYPTION_KEY"] = ""  # Will auto-generate

from daily_agents.database.config import Base
from daily_agents.database.encryption import encrypt_value, decrypt_value, EncryptedString
from daily_agents.database.models import (
    User,
    Project,
    TeamMember,
    RecurringMeeting,
    Meeting,
    AttendanceRecord,
    MeetingTranscript,
    SprintAnalytics,
    EmployeeAnalytics,
    SystemConfig,
    UserRole,
    MeetingType,
    MeetingStatus,
    TeamMemberRole,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite engine for testing."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Provide a fresh session per test with rollback."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = sessionmaker(bind=connection)()
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()


# ─── Table Creation Tests ────────────────────────────────────────────


EXPECTED_TABLES = [
    "users",
    "projects",
    "team_members",
    "recurring_meetings",
    "meetings",
    "attendance_records",
    "meeting_transcripts",
    "sprint_analytics",
    "employee_analytics",
    "system_config",
]


class TestTableCreation:
    """Verify all 10 tables are created in the database."""

    def test_all_tables_exist(self, engine):
        """All expected tables should be present in the schema."""
        inspector = inspect(engine)
        actual_tables = inspector.get_table_names()
        for table in EXPECTED_TABLES:
            assert table in actual_tables, f"Missing table: {table}"

    def test_table_count(self, engine):
        """Should have exactly 10 tables."""
        inspector = inspect(engine)
        actual_tables = inspector.get_table_names()
        assert len(actual_tables) == 10, f"Expected 10 tables, got {len(actual_tables)}: {actual_tables}"


# ─── Model CRUD Tests ───────────────────────────────────────────────


class TestUserModel:
    """Verify the User model works correctly."""

    def test_create_user(self, session: Session):
        user = User(
            username="testuser",
            email="test@example.com",
            password_hash="$2b$12$fakehash",
            full_name="Test User",
            role=UserRole.ADMIN,
        )
        session.add(user)
        session.flush()

        assert user.id is not None
        assert user.username == "testuser"
        assert user.role == UserRole.ADMIN
        assert user.is_active is True
        assert user.created_at is not None

    def test_default_role_is_member(self, session: Session):
        user = User(
            username="newuser",
            email="new@example.com",
            password_hash="$2b$12$fakehash",
        )
        session.add(user)
        session.flush()

        assert user.role == UserRole.MEMBER

    def test_unique_username(self, session: Session):
        user1 = User(username="unique", email="a@example.com", password_hash="hash1")
        user2 = User(username="unique", email="b@example.com", password_hash="hash2")
        session.add(user1)
        session.flush()
        session.add(user2)
        with pytest.raises(Exception):  # IntegrityError
            session.flush()

    def test_repr(self, session: Session):
        user = User(username="reprtest", email="repr@test.com", password_hash="hash")
        session.add(user)
        session.flush()
        assert "reprtest" in repr(user)


class TestProjectModel:
    """Verify the Project model with encrypted fields."""

    def test_create_project_with_encryption(self, session: Session):
        # Create owner first
        owner = User(username="owner", email="owner@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(
            name="Test Project",
            key="TEST",
            owner_id=owner.id,
            jira_base_url="https://test.atlassian.net",
            jira_email="jira@test.com",
            jira_api_token="super-secret-token-12345",
            sender_password="email-password-secret",
        )
        session.add(project)
        session.flush()

        assert project.id is not None
        assert project.key == "TEST"
        assert project.is_active is True
        assert project.sprint_duration_days == 14

    def test_project_owner_relationship(self, session: Session):
        owner = User(username="projowner", email="projowner@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="Rel Test", key="REL", owner_id=owner.id)
        session.add(project)
        session.flush()

        assert project.owner.username == "projowner"
        assert len(owner.owned_projects) == 1

    def test_unique_project_key(self, session: Session):
        owner = User(username="keyowner", email="keyowner@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        p1 = Project(name="P1", key="UNIQUE", owner_id=owner.id)
        p2 = Project(name="P2", key="UNIQUE", owner_id=owner.id)
        session.add(p1)
        session.flush()
        session.add(p2)
        with pytest.raises(Exception):
            session.flush()


class TestTeamMemberModel:
    """Verify team membership with unique constraints."""

    def test_create_team_member(self, session: Session):
        user = User(username="tmuser", email="tm@test.com", password_hash="hash")
        session.add(user)
        session.flush()

        owner = User(username="tmowner", email="tmo@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="TM Project", key="TMP", owner_id=owner.id)
        session.add(project)
        session.flush()

        member = TeamMember(
            user_id=user.id,
            project_id=project.id,
            jira_username="tm-jira",
            role=TeamMemberRole.DEVELOPER,
        )
        session.add(member)
        session.flush()

        assert member.id is not None
        assert member.role == TeamMemberRole.DEVELOPER

    def test_duplicate_membership_rejected(self, session: Session):
        user = User(username="dupuser", email="dup@test.com", password_hash="hash")
        owner = User(username="dupowner", email="dupo@test.com", password_hash="hash")
        session.add_all([user, owner])
        session.flush()

        project = Project(name="Dup Project", key="DUP", owner_id=owner.id)
        session.add(project)
        session.flush()

        m1 = TeamMember(user_id=user.id, project_id=project.id)
        m2 = TeamMember(user_id=user.id, project_id=project.id)
        session.add(m1)
        session.flush()
        session.add(m2)
        with pytest.raises(Exception):
            session.flush()


class TestMeetingModels:
    """Verify meetings, recurring meetings, and related models."""

    def test_create_recurring_meeting(self, session: Session):
        owner = User(username="rmowner", email="rm@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="RM Project", key="RMP", owner_id=owner.id)
        session.add(project)
        session.flush()

        rm = RecurringMeeting(
            project_id=project.id,
            meeting_type=MeetingType.STANDUP,
            start_time="10:30",
            days_of_week="monday,tuesday,wednesday,thursday,friday",
            timezone="Asia/Kolkata",
        )
        session.add(rm)
        session.flush()

        assert rm.id is not None
        assert rm.is_active is True
        assert rm.meeting_type == MeetingType.STANDUP

    def test_create_meeting(self, session: Session):
        owner = User(username="mtgowner", email="mtg@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="Mtg Project", key="MTG", owner_id=owner.id)
        session.add(project)
        session.flush()

        meeting = Meeting(
            project_id=project.id,
            meeting_type=MeetingType.SPRINT_PLANNING,
            status=MeetingStatus.SCHEDULED,
            scheduled_start=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
            scheduled_end=datetime(2026, 5, 20, 11, 0, tzinfo=timezone.utc),
            meeting_link="https://teams.microsoft.com/meet/123",
        )
        session.add(meeting)
        session.flush()

        assert meeting.id is not None
        assert meeting.status == MeetingStatus.SCHEDULED
        assert meeting.ical_sequence == 0

    def test_create_attendance_record(self, session: Session):
        user = User(username="attuser", email="att@test.com", password_hash="hash")
        owner = User(username="attowner", email="atto@test.com", password_hash="hash")
        session.add_all([user, owner])
        session.flush()

        project = Project(name="Att Project", key="ATT", owner_id=owner.id)
        session.add(project)
        session.flush()

        meeting = Meeting(
            project_id=project.id,
            meeting_type=MeetingType.STANDUP,
            scheduled_start=datetime(2026, 5, 20, 10, 30, tzinfo=timezone.utc),
        )
        session.add(meeting)
        session.flush()

        record = AttendanceRecord(
            meeting_id=meeting.id,
            user_id=user.id,
            project_id=project.id,
            attended=True,
            late_by_minutes=5,
        )
        session.add(record)
        session.flush()

        assert record.attended is True
        assert record.late_by_minutes == 5

    def test_create_meeting_transcript(self, session: Session):
        owner = User(username="trowner", email="tr@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="Tr Project", key="TRP", owner_id=owner.id)
        session.add(project)
        session.flush()

        meeting = Meeting(
            project_id=project.id,
            meeting_type=MeetingType.STANDUP,
            scheduled_start=datetime(2026, 5, 20, 10, 30, tzinfo=timezone.utc),
        )
        session.add(meeting)
        session.flush()

        transcript = MeetingTranscript(
            meeting_id=meeting.id,
            speaker="John Doe",
            text="I completed the feature yesterday.",
            start_timestamp=0.0,
            end_timestamp=3.5,
            confidence=0.95,
            language="en",
        )
        session.add(transcript)
        session.flush()

        assert transcript.confidence == 0.95
        assert transcript.language == "en"


class TestAnalyticsModels:
    """Verify sprint and employee analytics models."""

    def test_create_sprint_analytics(self, session: Session):
        owner = User(username="saowner", email="sa@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(name="SA Project", key="SAP", owner_id=owner.id)
        session.add(project)
        session.flush()

        sprint = SprintAnalytics(
            project_id=project.id,
            sprint_name="Sprint 1",
            sprint_start=datetime(2026, 5, 5, tzinfo=timezone.utc),
            sprint_end=datetime(2026, 5, 19, tzinfo=timezone.utc),
            total_issues=30,
            completed_issues=25,
            carried_over_issues=3,
            added_mid_sprint=2,
            completion_rate=83.3,
        )
        session.add(sprint)
        session.flush()

        assert sprint.completion_rate == 83.3
        assert sprint.total_issues == 30

    def test_create_employee_analytics(self, session: Session):
        user = User(username="eauser", email="ea@test.com", password_hash="hash")
        owner = User(username="eaowner", email="eao@test.com", password_hash="hash")
        session.add_all([user, owner])
        session.flush()

        project = Project(name="EA Project", key="EAP", owner_id=owner.id)
        session.add(project)
        session.flush()

        analytics = EmployeeAnalytics(
            user_id=user.id,
            project_id=project.id,
            period="2026-W20",
            standups_attended=4,
            total_standups=5,
            attendance_rate=80.0,
            issues_completed=8,
            bugs_fixed=3,
            features_delivered=2,
            high_priority_completed=1,
            contribution_score=85.5,
            team_rank=2,
            badges='["fast_resolver", "attendance_star"]',
        )
        session.add(analytics)
        session.flush()

        assert analytics.attendance_rate == 80.0
        assert analytics.contribution_score == 85.5


class TestSystemConfig:
    """Verify system config key-value model."""

    def test_create_config(self, session: Session):
        config = SystemConfig(
            key="app.version",
            value="2.0.0",
            description="Application version",
        )
        session.add(config)
        session.flush()

        assert config.key == "app.version"
        assert config.value == "2.0.0"

    def test_unique_config_key(self, session: Session):
        c1 = SystemConfig(key="unique.key", value="v1")
        c2 = SystemConfig(key="unique.key", value="v2")
        session.add(c1)
        session.flush()
        session.add(c2)
        with pytest.raises(Exception):
            session.flush()


# ─── Encryption Tests ────────────────────────────────────────────────


class TestEncryption:
    """Verify Fernet encryption round-trips correctly."""

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "my-super-secret-api-token"
        encrypted = encrypt_value(plaintext)

        assert encrypted != plaintext
        assert len(encrypted) > len(plaintext)

        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_encrypt_empty_string(self):
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_encrypt_different_values_produce_different_ciphertext(self):
        e1 = encrypt_value("token-1")
        e2 = encrypt_value("token-2")
        assert e1 != e2

    def test_encrypt_unicode(self):
        plaintext = "密码是安全的 🔒"
        encrypted = encrypt_value(plaintext)
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_encrypted_string_type_decorator(self, session: Session):
        """Verify EncryptedString works transparently in a model."""
        owner = User(username="encowner", email="enc@test.com", password_hash="hash")
        session.add(owner)
        session.flush()

        project = Project(
            name="Enc Project",
            key="ENC",
            owner_id=owner.id,
            jira_api_token="secret-jira-token-12345",
            sender_password="secret-smtp-password",
        )
        session.add(project)
        session.flush()

        # When read from session, values should be decrypted
        assert project.jira_api_token == "secret-jira-token-12345"
        assert project.sender_password == "secret-smtp-password"
