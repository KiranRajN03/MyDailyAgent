"""
SQLAlchemy 2.0 Database Models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All ten entity models for the Engineering Manager Platform.

Entity Relationship (Section 6.1):
    User (1) -< (M) Project (owner)
    User (1) -< (M) TeamMember
    Project (1) -< (M) TeamMember
    Project (1) -< (M) RecurringMeeting
    Project (1) -< (M) Meeting
    Project (1) -< (M) AttendanceRecord
    Project (1) -< (M) SprintAnalytics
    RecurringMeeting (1) -< (M) Meeting
    Meeting (1) -< (M) AttendanceRecord
    Meeting (1) -< (M) MeetingTranscript
    User (1) -< (M) AttendanceRecord
    User (1) -< (M) EmployeeAnalytics

Encrypted Fields (Section 6.3):
    Project.jira_api_token  → Fernet EncryptedString
    Project.sender_password → Fernet EncryptedString
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from daily_agents.database.config import Base
from daily_agents.database.encryption import EncryptedString


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════


class UserRole(str, enum.Enum):
    """User roles for RBAC (Section 2.1)."""
    ADMIN = "admin"
    MANAGER = "manager"
    TEAM_LEAD = "team_lead"
    MEMBER = "member"


class MeetingType(str, enum.Enum):
    """Meeting types (REQ-MTG-001)."""
    STANDUP = "standup"
    SPRINT_PLANNING = "sprint_planning"
    RETROSPECTIVE = "retrospective"


class MeetingStatus(str, enum.Enum):
    """Meeting lifecycle statuses (REQ-MTG-003)."""
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TeamMemberRole(str, enum.Enum):
    """Team member roles within a project (REQ-PROJ-033)."""
    DEVELOPER = "developer"
    QA = "qa"
    DESIGNER = "designer"
    TECH_LEAD = "tech_lead"
    PRODUCT_OWNER = "product_owner"
    SCRUM_MASTER = "scrum_master"
    OTHER = "other"


# ═══════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════


class User(Base):
    """
    User accounts (Section 6.2 — `users` table).

    Covers:
      - REQ-AUTH-001 through REQ-AUTH-006 (registration fields)
      - REQ-AUTH-010 through REQ-AUTH-015 (login / JWT)
      - REQ-AUTH-020 through REQ-AUTH-026 (password reset)
      - REQ-ROLE-001, REQ-ROLE-002 (first-user rule)
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=False, length=20),
        nullable=False,
        default=UserRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Password reset (REQ-AUTH-020 to REQ-AUTH-026)
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    owned_projects: Mapped[List["Project"]] = relationship(
        "Project", back_populates="owner", cascade="all, delete-orphan"
    )
    team_memberships: Mapped[List["TeamMember"]] = relationship(
        "TeamMember", back_populates="user", cascade="all, delete-orphan"
    )
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord", back_populates="user", cascade="all, delete-orphan"
    )
    employee_analytics: Mapped[List["EmployeeAnalytics"]] = relationship(
        "EmployeeAnalytics", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username!r}, role={self.role.value})>"


class Project(Base):
    """
    Multi-tenant projects (Section 6.2 — `projects` table).

    Covers:
      - REQ-PROJ-001 through REQ-PROJ-011 (project CRUD)
      - REQ-SEC-001 (encrypted jira_api_token, sender_password)

    Encrypted fields:
      - jira_api_token: Fernet EncryptedString
      - sender_password: Fernet EncryptedString
    """
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Jira Configuration (REQ-PROJ-003, REQ-PROJ-004) ─────────────
    jira_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    jira_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    jira_api_token: Mapped[Optional[str]] = mapped_column(
        EncryptedString(length=1024), nullable=True  # 🔒 Fernet encrypted
    )
    jira_project_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ── Email Configuration (REQ-PROJ-005, REQ-PROJ-006) ─────────────
    smtp_server: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_password: Mapped[Optional[str]] = mapped_column(
        EncryptedString(length=1024), nullable=True  # 🔒 Fernet encrypted
    )
    recipient_emails: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Meeting Configuration (REQ-PROJ-007, REQ-PROJ-008) ───────────
    meeting_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    dashboard_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    standup_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # HH:MM
    reminder_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # HH:MM
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    # ── Sprint Configuration ─────────────────────────────────────────
    sprint_duration_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    sprint_start_day: Mapped[str] = mapped_column(String(10), default="Monday", nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    owner: Mapped["User"] = relationship("User", back_populates="owned_projects")
    team_members: Mapped[List["TeamMember"]] = relationship(
        "TeamMember", back_populates="project", cascade="all, delete-orphan"
    )
    recurring_meetings: Mapped[List["RecurringMeeting"]] = relationship(
        "RecurringMeeting", back_populates="project", cascade="all, delete-orphan"
    )
    meetings: Mapped[List["Meeting"]] = relationship(
        "Meeting", back_populates="project", cascade="all, delete-orphan"
    )
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord", back_populates="project", cascade="all, delete-orphan"
    )
    sprint_analytics: Mapped[List["SprintAnalytics"]] = relationship(
        "SprintAnalytics", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, key={self.key!r}, name={self.name!r})>"


class TeamMember(Base):
    """
    Project membership (Section 6.2 — `team_members` table).

    Covers:
      - REQ-PROJ-030 through REQ-PROJ-033
    """
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_team_user_project"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    jira_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[TeamMemberRole] = mapped_column(
        Enum(TeamMemberRole, name="team_member_role", native_enum=False, length=20),
        nullable=False,
        default=TeamMemberRole.DEVELOPER,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="team_memberships")
    project: Mapped["Project"] = relationship("Project", back_populates="team_members")

    def __repr__(self) -> str:
        return f"<TeamMember(id={self.id}, user_id={self.user_id}, project_id={self.project_id})>"


class RecurringMeeting(Base):
    """
    Recurring meeting configuration (Section 6.2 — `recurring_meetings` table).

    Covers:
      - REQ-MTG-010 through REQ-MTG-016
    """
    __tablename__ = "recurring_meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    meeting_type: Mapped[MeetingType] = mapped_column(
        Enum(MeetingType, name="meeting_type", native_enum=False, length=20),
        nullable=False,
    )

    # Schedule fields
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    end_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # HH:MM
    days_of_week: Mapped[str] = mapped_column(
        String(100), nullable=False  # Comma-separated: "monday,wednesday,friday"
    )
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    # Meeting details
    meeting_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    project: Mapped["Project"] = relationship("Project", back_populates="recurring_meetings")
    meetings: Mapped[List["Meeting"]] = relationship(
        "Meeting", back_populates="recurring_meeting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<RecurringMeeting(id={self.id}, type={self.meeting_type.value}, "
            f"days={self.days_of_week!r})>"
        )


class Meeting(Base):
    """
    Individual meeting instances (Section 6.2 — `meetings` table).

    Covers:
      - REQ-MTG-001 through REQ-MTG-003 (types, fields, statuses)
      - REQ-MTG-020 through REQ-MTG-025 (lifecycle control)
      - REQ-MTG-030 through REQ-MTG-035 (calendar invites)
    """
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    recurring_meeting_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recurring_meetings.id", ondelete="SET NULL"), nullable=True
    )

    # Meeting details
    meeting_type: Mapped[MeetingType] = mapped_column(
        Enum(MeetingType, name="meeting_type", native_enum=False, length=20,
             create_constraint=False),
        nullable=False,
    )
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status", native_enum=False, length=20),
        nullable=False,
        default=MeetingStatus.SCHEDULED,
    )

    # Scheduled times
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Actual times (REQ-MTG-020, REQ-MTG-022)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Meeting link and notes
    meeting_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Who started/stopped (REQ-MTG-024)
    started_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stopped_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Calendar invite (REQ-MTG-012)
    ical_uid: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    ical_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AI Summary (stored as JSON text)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    project: Mapped["Project"] = relationship("Project", back_populates="meetings")
    recurring_meeting: Mapped[Optional["RecurringMeeting"]] = relationship(
        "RecurringMeeting", back_populates="meetings"
    )
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord", back_populates="meeting", cascade="all, delete-orphan"
    )
    transcripts: Mapped[List["MeetingTranscript"]] = relationship(
        "MeetingTranscript", back_populates="meeting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Meeting(id={self.id}, type={self.meeting_type.value}, "
            f"status={self.status.value})>"
        )


class AttendanceRecord(Base):
    """
    Meeting attendance records (Section 6.2 — `attendance_records` table).

    Covers:
      - REQ-BOT-030 through REQ-BOT-032
    """
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_attendance_meeting_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Attendance data (REQ-BOT-031)
    attended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    late_by_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Join/leave tracking (REQ-BOT-004)
    join_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    leave_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="attendance_records")
    user: Mapped["User"] = relationship("User", back_populates="attendance_records")
    project: Mapped["Project"] = relationship("Project", back_populates="attendance_records")

    def __repr__(self) -> str:
        return (
            f"<AttendanceRecord(id={self.id}, meeting={self.meeting_id}, "
            f"user={self.user_id}, attended={self.attended})>"
        )


class MeetingTranscript(Base):
    """
    Transcript segments (Section 6.2 — `meeting_transcripts` table).

    Covers:
      - REQ-BOT-010 through REQ-BOT-014
    """
    __tablename__ = "meeting_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )

    # Transcript data (REQ-BOT-014)
    speaker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    end_timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="transcripts")

    def __repr__(self) -> str:
        return f"<MeetingTranscript(id={self.id}, meeting={self.meeting_id}, speaker={self.speaker!r})>"


class SprintAnalytics(Base):
    """
    Sprint performance metrics (Section 6.2 — `sprint_analytics` table).

    Covers:
      - REQ-SPRINT-001 through REQ-SPRINT-005
    """
    __tablename__ = "sprint_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Sprint dates
    sprint_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sprint_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sprint_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Completion metrics (REQ-SPRINT-001, REQ-SPRINT-002)
    total_issues: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_issues: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    carried_over_issues: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    added_mid_sprint: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Health indicators (REQ-SPRINT-003, REQ-SPRINT-004) — stored as JSON text
    top_contributors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issues_by_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issues_by_priority: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issues_by_assignee: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    health_indicators: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    project: Mapped["Project"] = relationship("Project", back_populates="sprint_analytics")

    def __repr__(self) -> str:
        return f"<SprintAnalytics(id={self.id}, sprint={self.sprint_name!r}, rate={self.completion_rate})>"


class EmployeeAnalytics(Base):
    """
    Employee performance tracking (Section 6.2 — `employee_analytics` table).

    Covers:
      - REQ-EMP-001 through REQ-EMP-006
    """
    __tablename__ = "employee_analytics"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", "period", name="uq_emp_analytics_user_project_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "2026-W20", "2026-05"

    # Attendance metrics (REQ-EMP-002)
    standups_attended: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_standups: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attendance_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Work metrics from Jira (REQ-EMP-003)
    issues_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bugs_fixed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    features_delivered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_priority_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Score and ranking (REQ-EMP-004)
    contribution_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    team_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Achievement badges as JSON (REQ-EMP-005)
    badges: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="employee_analytics")

    def __repr__(self) -> str:
        return (
            f"<EmployeeAnalytics(id={self.id}, user={self.user_id}, "
            f"period={self.period!r}, score={self.contribution_score})>"
        )


class SystemConfig(Base):
    """
    System key-value configuration (Section 6.2 — `system_config` table).

    Covers:
      - REQ-CFG-004: System config storable in database
    """
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key!r})>"
