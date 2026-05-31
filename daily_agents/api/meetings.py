"""
Meeting Management Routes
~~~~~~~~~~~~~~~~~~~~~~~~~
CRUD for meetings and recurring meeting configurations,
plus meeting lifecycle (start/stop).

References:
  - Section 5.4: Meeting endpoints
  - Section 5.5: Recurring meeting endpoints
  - REQ-MTG-001 to REQ-MTG-025
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from daily_agents.api.dependencies import get_current_user, require_manager
from daily_agents.api.schemas import (
    MeetingCreateRequest,
    MeetingResponse,
    MessageResponse,
    RecurringMeetingCreateRequest,
    RecurringMeetingResponse,
    RecurringMeetingUpdateRequest,
)
from daily_agents.database.config import get_db
from daily_agents.database.models import (
    AttendanceRecord,
    Meeting,
    MeetingStatus,
    MeetingType,
    Project,
    RecurringMeeting,
    TeamMember,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meetings"])


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

DAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}


def _meeting_to_response(m: Meeting) -> MeetingResponse:
    """Convert a Meeting model to response schema."""
    return MeetingResponse(
        id=m.id,
        project_id=m.project_id,
        recurring_meeting_id=m.recurring_meeting_id,
        meeting_type=m.meeting_type.value if isinstance(m.meeting_type, MeetingType) else m.meeting_type,
        status=m.status.value if isinstance(m.status, MeetingStatus) else m.status,
        scheduled_start=m.scheduled_start,
        scheduled_end=m.scheduled_end,
        actual_start=m.actual_start,
        actual_end=m.actual_end,
        meeting_link=m.meeting_link,
        notes=m.notes,
        started_by=m.started_by,
        stopped_by=m.stopped_by,
        ical_uid=m.ical_uid,
        summary=m.summary,
        created_at=m.created_at,
    )


def _recurring_to_response(rm: RecurringMeeting) -> RecurringMeetingResponse:
    """Convert a RecurringMeeting model to response schema."""
    return RecurringMeetingResponse(
        id=rm.id,
        project_id=rm.project_id,
        meeting_type=rm.meeting_type.value if isinstance(rm.meeting_type, MeetingType) else rm.meeting_type,
        start_time=rm.start_time,
        end_time=rm.end_time,
        days_of_week=rm.days_of_week,
        timezone=rm.timezone,
        meeting_link=rm.meeting_link,
        description=rm.description,
        is_active=rm.is_active,
        created_at=rm.created_at,
    )


def _generate_meetings_for_recurring(
    rm: RecurringMeeting, db: Session, days_ahead: int = 30
) -> List[Meeting]:
    """
    REQ-MTG-011: Generate individual meeting instances for the next N days.
    REQ-MTG-012: Each meeting gets a unique iCal UID.
    REQ-MTG-013: Skip dates in the past.
    REQ-MTG-014: No duplicates for same config + time.
    """
    now = datetime.utcnow()
    today = now.date()
    target_days = [
        DAY_MAP[d.strip().lower()]
        for d in rm.days_of_week.split(",")
        if d.strip().lower() in DAY_MAP
    ]

    # Parse start/end times
    start_h, start_m = map(int, rm.start_time.split(":"))
    end_h, end_m = (None, None)
    if rm.end_time:
        end_h, end_m = map(int, rm.end_time.split(":"))

    generated = []
    for day_offset in range(days_ahead):
        check_date = today + timedelta(days=day_offset)
        if check_date.weekday() not in target_days:
            continue

        scheduled_start = datetime(
            check_date.year, check_date.month, check_date.day,
            start_h, start_m, tzinfo=timezone.utc,
        )

        # REQ-MTG-013: Skip past dates
        if scheduled_start < now.replace(tzinfo=timezone.utc):
            continue

        scheduled_end = None
        if end_h is not None:
            scheduled_end = datetime(
                check_date.year, check_date.month, check_date.day,
                end_h, end_m, tzinfo=timezone.utc,
            )

        # REQ-MTG-014: Check for duplicates
        existing = db.query(Meeting).filter(
            Meeting.recurring_meeting_id == rm.id,
            Meeting.scheduled_start == scheduled_start,
        ).first()
        if existing:
            continue

        meeting = Meeting(
            project_id=rm.project_id,
            recurring_meeting_id=rm.id,
            meeting_type=rm.meeting_type,
            status=MeetingStatus.SCHEDULED,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            meeting_link=rm.meeting_link,
            ical_uid=f"{uuid.uuid4()}@dailyagents",  # REQ-MTG-012
        )
        db.add(meeting)
        generated.append(meeting)

    db.flush()
    return generated


# ═══════════════════════════════════════════════════════════════════
# Meeting Endpoints (Section 5.4)
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/meetings",
    response_model=MeetingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create meeting",
)
def create_meeting(
    request: MeetingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """REQ-MTG-001, REQ-MTG-002: Create a one-off meeting instance."""
    # Verify project exists
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.is_active == True,
    ).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    meeting = Meeting(
        project_id=request.project_id,
        meeting_type=MeetingType(request.meeting_type),
        status=MeetingStatus.SCHEDULED,
        scheduled_start=request.scheduled_start,
        scheduled_end=request.scheduled_end,
        meeting_link=request.meeting_link,
        notes=request.notes,
        ical_uid=f"{uuid.uuid4()}@dailyagents",
    )
    db.add(meeting)
    db.flush()

    logger.info(
        "Meeting created: type=%s, project=%s, by=%s",
        request.meeting_type, project.key, current_user.username,
    )

    return _meeting_to_response(meeting)


@router.post(
    "/meetings/{meeting_id}/start",
    response_model=MeetingResponse,
    summary="Start meeting",
)
def start_meeting(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    REQ-MTG-020: Set status to in_progress, record actual start time.
    REQ-MTG-024: Record who started.
    REQ-MTG-025: Cannot start a completed meeting.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found.",
        )

    if meeting.status == MeetingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a completed meeting.",
        )
    if meeting.status == MeetingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a cancelled meeting.",
        )
    if meeting.status == MeetingStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meeting is already in progress.",
        )

    meeting.status = MeetingStatus.IN_PROGRESS
    meeting.actual_start = datetime.now(timezone.utc)
    meeting.started_by = current_user.id
    db.flush()

    logger.info("Meeting %d started by %s", meeting_id, current_user.username)

    return _meeting_to_response(meeting)


@router.post(
    "/meetings/{meeting_id}/stop",
    response_model=MeetingResponse,
    summary="Stop meeting",
)
def stop_meeting(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    REQ-MTG-022: Set status to completed, record actual end time.
    REQ-MTG-024: Record who stopped.
    REQ-MTG-025: Cannot stop a non-active meeting.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found.",
        )

    if meeting.status != MeetingStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only stop a meeting that is in progress.",
        )

    meeting.status = MeetingStatus.COMPLETED
    meeting.actual_end = datetime.now(timezone.utc)
    meeting.stopped_by = current_user.id
    db.flush()

    logger.info("Meeting %d stopped by %s", meeting_id, current_user.username)

    return _meeting_to_response(meeting)


@router.get(
    "/meetings/{meeting_id}/summary",
    response_model=MeetingResponse,
    summary="Get meeting summary",
)
def get_meeting_summary(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return meeting details including AI summary if available."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found.",
        )
    return _meeting_to_response(meeting)


@router.get(
    "/projects/{project_id}/meetings",
    response_model=List[MeetingResponse],
    summary="List project meetings",
)
def list_project_meetings(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all meetings for a project."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.is_active == True,
    ).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    meetings = db.query(Meeting).filter(
        Meeting.project_id == project_id,
    ).order_by(Meeting.scheduled_start.desc()).all()

    return [_meeting_to_response(m) for m in meetings]


# ═══════════════════════════════════════════════════════════════════
# Recurring Meeting Endpoints (Section 5.5)
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/recurring-meetings",
    response_model=RecurringMeetingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create recurring meeting",
)
def create_recurring_meeting(
    project_id: int,
    request: RecurringMeetingCreateRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-MTG-010: Create recurring meeting config and generate instances."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.is_active == True,
    ).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    rm = RecurringMeeting(
        project_id=project_id,
        meeting_type=MeetingType(request.meeting_type),
        start_time=request.start_time,
        end_time=request.end_time,
        days_of_week=request.days_of_week,
        timezone=request.timezone,
        meeting_link=request.meeting_link,
        description=request.description,
    )
    db.add(rm)
    db.flush()

    # Generate meeting instances (REQ-MTG-011)
    generated = _generate_meetings_for_recurring(rm, db)
    logger.info(
        "Recurring meeting created for project %s: type=%s, days=%s, generated %d meetings",
        project.key, request.meeting_type, request.days_of_week, len(generated),
    )

    return _recurring_to_response(rm)


@router.get(
    "/projects/{project_id}/recurring-meetings",
    response_model=List[RecurringMeetingResponse],
    summary="List recurring meetings",
)
def list_recurring_meetings(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List active recurring meeting configs for a project."""
    configs = db.query(RecurringMeeting).filter(
        RecurringMeeting.project_id == project_id,
        RecurringMeeting.is_active == True,
    ).all()
    return [_recurring_to_response(rm) for rm in configs]


@router.put(
    "/recurring-meetings/{recurring_id}",
    response_model=RecurringMeetingResponse,
    summary="Update recurring meeting schedule",
)
def update_recurring_meeting(
    recurring_id: int,
    request: RecurringMeetingUpdateRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    REQ-MTG-015: Cancel all future meetings, update config, regenerate.
    """
    rm = db.query(RecurringMeeting).filter(
        RecurringMeeting.id == recurring_id,
        RecurringMeeting.is_active == True,
    ).first()
    if rm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring meeting not found.",
        )

    # Cancel all future scheduled meetings
    now = datetime.utcnow()
    future_meetings = db.query(Meeting).filter(
        Meeting.recurring_meeting_id == recurring_id,
        Meeting.status == MeetingStatus.SCHEDULED,
        Meeting.scheduled_start > now,
    ).all()
    for m in future_meetings:
        m.status = MeetingStatus.CANCELLED
    db.flush()

    # Update config fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and hasattr(rm, field):
            setattr(rm, field, value)
    db.flush()

    # Regenerate meetings with new config
    generated = _generate_meetings_for_recurring(rm, db)

    logger.info(
        "Recurring meeting %d updated: cancelled %d future, generated %d new",
        recurring_id, len(future_meetings), len(generated),
    )

    return _recurring_to_response(rm)


@router.delete(
    "/recurring-meetings/{recurring_id}",
    response_model=MessageResponse,
    summary="Delete recurring meeting",
)
def delete_recurring_meeting(
    recurring_id: int,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    REQ-MTG-016: Cancel all future instances, mark config inactive.
    """
    rm = db.query(RecurringMeeting).filter(
        RecurringMeeting.id == recurring_id,
        RecurringMeeting.is_active == True,
    ).first()
    if rm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring meeting not found.",
        )

    # Cancel all future scheduled meetings
    now = datetime.utcnow()
    cancelled_count = 0
    future_meetings = db.query(Meeting).filter(
        Meeting.recurring_meeting_id == recurring_id,
        Meeting.status == MeetingStatus.SCHEDULED,
        Meeting.scheduled_start > now,
    ).all()
    for m in future_meetings:
        m.status = MeetingStatus.CANCELLED
        cancelled_count += 1

    # Mark config inactive
    rm.is_active = False
    db.flush()

    logger.info(
        "Recurring meeting %d deleted: cancelled %d future meetings",
        recurring_id, cancelled_count,
    )

    return MessageResponse(
        message=f"Recurring meeting deleted. {cancelled_count} future meetings cancelled."
    )


# Import BaseModel for schema declaration
from pydantic import BaseModel

# ── Attendance Endpoints (REQ-BOT-030 to 032) ─────────────────────────

class AttendanceRecordRequest(BaseModel):
    user_id: int
    attended: bool
    late_by_minutes: Optional[int] = None

class AttendanceRecordResponse(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str] = None
    attended: bool
    late_by_minutes: Optional[int] = None

@router.get(
    "/meetings/{meeting_id}/attendance",
    response_model=List[AttendanceRecordResponse],
    summary="Get attendance records for a meeting",
)
def get_meeting_attendance(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get meeting attendance records. 
    If no records exist, return default records for all project team members.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found.",
        )
    
    records = db.query(AttendanceRecord).filter(AttendanceRecord.meeting_id == meeting_id).all()
    records_dict = {r.user_id: r for r in records}
    
    team_members = db.query(TeamMember).filter(TeamMember.project_id == meeting.project_id).all()
    
    response = []
    for tm in team_members:
        u = db.query(User).filter(User.id == tm.user_id).first()
        if not u:
            continue
        
        record = records_dict.get(tm.user_id)
        response.append(
            AttendanceRecordResponse(
                user_id=tm.user_id,
                username=u.username,
                full_name=u.full_name,
                attended=record.attended if record else False,
                late_by_minutes=record.late_by_minutes if record else None,
            )
        )
    return response

@router.post(
    "/meetings/{meeting_id}/attendance",
    response_model=MessageResponse,
    summary="Save/update attendance records for a meeting",
)
def save_meeting_attendance(
    meeting_id: int,
    request: List[AttendanceRecordRequest],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save or update attendance records for a meeting."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found.",
        )
    
    for item in request:
        record = db.query(AttendanceRecord).filter(
            AttendanceRecord.meeting_id == meeting_id,
            AttendanceRecord.user_id == item.user_id,
        ).first()
        
        if record:
            record.attended = item.attended
            record.late_by_minutes = item.late_by_minutes
        else:
            record = AttendanceRecord(
                meeting_id=meeting_id,
                user_id=item.user_id,
                project_id=meeting.project_id,
                attended=item.attended,
                late_by_minutes=item.late_by_minutes,
            )
            db.add(record)
            
    db.flush()
    return MessageResponse(message="Attendance records updated successfully.")
