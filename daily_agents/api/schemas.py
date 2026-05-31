"""
Pydantic Request / Response Schemas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Validation models for the API layer.

References:
  - REQ-AUTH-001 to REQ-AUTH-006 (registration validation)
  - REQ-AUTH-010 to REQ-AUTH-015 (login)
  - REQ-AUTH-020 to REQ-AUTH-026 (password reset)
  - REQ-AUTH-030 to REQ-AUTH-033 (admin user management)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from daily_agents.database.models import UserRole


# ═══════════════════════════════════════════════════════════════════
# Auth Schemas
# ═══════════════════════════════════════════════════════════════════


class UserRegisterRequest(BaseModel):
    """
    REQ-AUTH-001: Registration with username, email, password, optional full_name.
    REQ-AUTH-002: Username 3-50 chars, letters/numbers/hyphens/underscores.
    REQ-AUTH-003: Valid email (via EmailStr).
    REQ-AUTH-004: Password ≥12 chars with uppercase, lowercase, digit, special.
    """
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=12)
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Username must contain only letters, numbers, hyphens, and underscores."
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character.")
        return v


class UserLoginRequest(BaseModel):
    """REQ-AUTH-010: Authenticate via username and password."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """REQ-AUTH-011: JWT access token response."""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str


class ForgotPasswordRequest(BaseModel):
    """REQ-AUTH-020: Password reset request via email."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """REQ-AUTH-022 to REQ-AUTH-024: Reset with token."""
    token: str
    new_password: str = Field(..., min_length=12)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character.")
        return v


# ═══════════════════════════════════════════════════════════════════
# User Schemas
# ═══════════════════════════════════════════════════════════════════


class UserResponse(BaseModel):
    """Public user representation."""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreateRequest(BaseModel):
    """REQ-AUTH-030: Admin creates user with specific role."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=12)
    full_name: Optional[str] = Field(None, max_length=255)
    role: UserRole = UserRole.MEMBER

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Username must contain only letters, numbers, hyphens, and underscores."
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character.")
        return v


class UserUpdateRequest(BaseModel):
    """REQ-AUTH-031, REQ-AUTH-032: Admin updates user fields."""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=12)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character.")
        return v


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    detail: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Project Schemas (Section 3.2)
# ═══════════════════════════════════════════════════════════════════


class ProjectCreateRequest(BaseModel):
    """
    REQ-PROJ-001 to REQ-PROJ-009: Create project with config.
    """
    name: str = Field(..., min_length=1, max_length=255)
    key: str = Field(..., min_length=2, max_length=20)

    # Jira config (optional)
    jira_base_url: Optional[str] = None
    jira_email: Optional[EmailStr] = None
    jira_api_token: Optional[str] = Field(None, min_length=10)
    jira_project_key: Optional[str] = Field(None, max_length=50)

    # Email config (optional)
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = Field(None, ge=1, le=65535)
    sender_email: Optional[EmailStr] = None
    sender_password: Optional[str] = None
    recipient_emails: Optional[str] = None  # comma-separated

    # Meeting config (optional)
    meeting_link: Optional[str] = None
    dashboard_url: Optional[str] = None
    standup_time: Optional[str] = None  # HH:MM
    reminder_time: Optional[str] = None  # HH:MM
    timezone: str = "UTC"
    conference_provider: Optional[str] = "manual"

    # Sprint config
    sprint_duration_days: int = Field(14, ge=1, le=90)
    sprint_start_day: str = "Monday"

    @field_validator("conference_provider")
    @classmethod
    def validate_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "manual"
        allowed = {"manual", "teams", "zoom"}
        if v.lower() not in allowed:
            raise ValueError("Conference provider must be one of: manual, teams, zoom")
        return v.lower()

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        """REQ-PROJ-002: 2-20 uppercase chars, numbers, hyphens, underscores."""
        if not re.match(r"^[A-Z0-9_-]+$", v):
            raise ValueError(
                "Project key must contain only uppercase letters, numbers, hyphens, and underscores."
            )
        return v

    @field_validator("jira_base_url")
    @classmethod
    def validate_jira_url(cls, v: Optional[str]) -> Optional[str]:
        """REQ-PROJ-003: Jira URL must match https://*.atlassian.net."""
        if v is None:
            return v
        if not re.match(r"^https://[\w.-]+\.atlassian\.net/?$", v):
            raise ValueError("Jira base URL must match https://*.atlassian.net")
        return v.rstrip("/")

    @field_validator("recipient_emails")
    @classmethod
    def validate_recipients(cls, v: Optional[str]) -> Optional[str]:
        """REQ-PROJ-006: Max 50 recipients, each must be valid."""
        if v is None:
            return v
        emails = [e.strip() for e in v.split(",") if e.strip()]
        if len(emails) > 50:
            raise ValueError("Maximum 50 recipient emails allowed.")
        return v

    @field_validator("standup_time", "reminder_time")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        """REQ-PROJ-008: Must match HH:MM 24-hour format."""
        if v is None:
            return v
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("Time must be in HH:MM 24-hour format.")
        return v

    @field_validator("meeting_link", "dashboard_url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        """REQ-PROJ-007: Must be valid HTTP(S) URL."""
        if v is None:
            return v
        if not re.match(r"^https?://", v):
            raise ValueError("URL must start with http:// or https://")
        return v


class ProjectUpdateRequest(BaseModel):
    """Partial update for project fields."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    jira_base_url: Optional[str] = None
    jira_email: Optional[EmailStr] = None
    jira_api_token: Optional[str] = Field(None, min_length=10)
    jira_project_key: Optional[str] = Field(None, max_length=50)
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = Field(None, ge=1, le=65535)
    sender_email: Optional[EmailStr] = None
    sender_password: Optional[str] = None
    recipient_emails: Optional[str] = None
    meeting_link: Optional[str] = None
    dashboard_url: Optional[str] = None
    standup_time: Optional[str] = None
    reminder_time: Optional[str] = None
    timezone: Optional[str] = None
    sprint_duration_days: Optional[int] = Field(None, ge=1, le=90)
    sprint_start_day: Optional[str] = None
    conference_provider: Optional[str] = None

    @field_validator("conference_provider")
    @classmethod
    def validate_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"manual", "teams", "zoom"}
        if v.lower() not in allowed:
            raise ValueError("Conference provider must be one of: manual, teams, zoom")
        return v.lower()

    @field_validator("standup_time", "reminder_time")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("Time must be in HH:MM 24-hour format.")
        return v


class ProjectResponse(BaseModel):
    """Public project representation (sensitive fields excluded)."""
    id: int
    name: str
    key: str
    owner_id: int
    is_active: bool
    jira_base_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_project_key: Optional[str] = None
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    sender_email: Optional[str] = None
    recipient_emails: Optional[str] = None
    meeting_link: Optional[str] = None
    dashboard_url: Optional[str] = None
    standup_time: Optional[str] = None
    reminder_time: Optional[str] = None
    timezone: str = "UTC"
    conference_provider: Optional[str] = "manual"
    sprint_duration_days: int = 14
    sprint_start_day: str = "Monday"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════
# Team Member Schemas (Section 3.2.3)
# ═══════════════════════════════════════════════════════════════════


class TeamMemberAddRequest(BaseModel):
    """REQ-PROJ-030: Add team member with Jira username and role."""
    user_id: int
    jira_username: Optional[str] = None
    role: str = "developer"  # TeamMemberRole value

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"developer", "qa", "designer", "tech_lead", "product_owner", "scrum_master", "other"}
        if v.lower() not in allowed:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
        return v.lower()


class TeamMemberResponse(BaseModel):
    """Team member representation."""
    id: int
    user_id: int
    project_id: int
    jira_username: Optional[str] = None
    role: str
    username: Optional[str] = None  # Joined from User
    email: Optional[str] = None     # Joined from User
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════
# Meeting Schemas (Section 3.3)
# ═══════════════════════════════════════════════════════════════════


class MeetingCreateRequest(BaseModel):
    """REQ-MTG-001, REQ-MTG-002: Create a meeting instance."""
    project_id: int
    meeting_type: str  # standup, sprint_planning, retrospective
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    meeting_link: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("meeting_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"standup", "sprint_planning", "retrospective"}
        if v.lower() not in allowed:
            raise ValueError(f"Meeting type must be one of: {', '.join(sorted(allowed))}")
        return v.lower()


class MeetingResponse(BaseModel):
    """Meeting representation."""
    id: int
    project_id: int
    recurring_meeting_id: Optional[int] = None
    meeting_type: str
    status: str
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    meeting_link: Optional[str] = None
    notes: Optional[str] = None
    started_by: Optional[int] = None
    stopped_by: Optional[int] = None
    ical_uid: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════
# Recurring Meeting Schemas (Section 3.3.2)
# ═══════════════════════════════════════════════════════════════════


class RecurringMeetingCreateRequest(BaseModel):
    """REQ-MTG-010: Create recurring meeting config."""
    meeting_type: str
    start_time: str  # HH:MM
    end_time: Optional[str] = None  # HH:MM
    days_of_week: str  # comma-separated: "monday,wednesday,friday"
    timezone: str = "UTC"
    meeting_link: Optional[str] = None
    description: Optional[str] = None

    @field_validator("meeting_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"standup", "sprint_planning", "retrospective"}
        if v.lower() not in allowed:
            raise ValueError(f"Meeting type must be one of: {', '.join(sorted(allowed))}")
        return v.lower()

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("Time must be in HH:MM 24-hour format.")
        return v

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: str) -> str:
        allowed_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        days = [d.strip().lower() for d in v.split(",") if d.strip()]
        if not days:
            raise ValueError("At least one day of week is required.")
        for d in days:
            if d not in allowed_days:
                raise ValueError(f"Invalid day: {d}. Must be one of: {', '.join(sorted(allowed_days))}")
        return ",".join(days)


class RecurringMeetingUpdateRequest(BaseModel):
    """Update recurring meeting schedule."""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    days_of_week: Optional[str] = None
    timezone: Optional[str] = None
    meeting_link: Optional[str] = None
    description: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("Time must be in HH:MM 24-hour format.")
        return v

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        days = [d.strip().lower() for d in v.split(",") if d.strip()]
        for d in days:
            if d not in allowed_days:
                raise ValueError(f"Invalid day: {d}")
        return ",".join(days)


class RecurringMeetingResponse(BaseModel):
    """Recurring meeting configuration representation."""
    id: int
    project_id: int
    meeting_type: str
    start_time: str
    end_time: Optional[str] = None
    days_of_week: str
    timezone: str
    meeting_link: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
