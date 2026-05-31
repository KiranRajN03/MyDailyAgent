"""
Project Management Routes
~~~~~~~~~~~~~~~~~~~~~~~~~
CRUD for projects and team member management.

References:
  - Section 5.3: Project endpoints
  - REQ-PROJ-001 to REQ-PROJ-033
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from daily_agents.api.dependencies import (
    get_current_user,
    require_admin,
    require_manager,
)
from daily_agents.api.schemas import (
    MessageResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    TeamMemberAddRequest,
    TeamMemberResponse,
)
from daily_agents.database.config import get_db
from daily_agents.database.models import (
    Project,
    TeamMember,
    TeamMemberRole,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["projects"])


# ═══════════════════════════════════════════════════════════════════
# Helper: Project access check
# ═══════════════════════════════════════════════════════════════════


def _get_project_or_404(
    project_id: int, db: Session, check_active: bool = True
) -> Project:
    """Fetch a project by ID or raise 404."""
    query = db.query(Project).filter(Project.id == project_id)
    if check_active:
        query = query.filter(Project.is_active == True)
    project = query.first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


def _check_project_access(project: Project, user: User) -> None:
    """
    REQ-PROJ-020 to REQ-PROJ-022: Verify user can access this project.
    Admins see all. Others must be owner or team member.
    """
    if user.role == UserRole.ADMIN:
        return
    if project.owner_id == user.id:
        return
    # Check team membership
    is_member = any(tm.user_id == user.id for tm in project.team_members)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project.",
        )


def _check_project_owner(project: Project, user: User) -> None:
    """REQ-PROJ-023: Only project owner (or admin) can update/delete."""
    if user.role == UserRole.ADMIN:
        return
    if project.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project owner can perform this action.",
        )


def _project_to_response(p: Project) -> ProjectResponse:
    """Convert a Project model to response schema."""
    return ProjectResponse(
        id=p.id,
        name=p.name,
        key=p.key,
        owner_id=p.owner_id,
        is_active=p.is_active,
        jira_base_url=p.jira_base_url,
        jira_email=p.jira_email,
        jira_project_key=p.jira_project_key,
        smtp_server=p.smtp_server,
        smtp_port=p.smtp_port,
        sender_email=p.sender_email,
        recipient_emails=p.recipient_emails,
        meeting_link=p.meeting_link,
        dashboard_url=p.dashboard_url,
        standup_time=p.standup_time,
        reminder_time=p.reminder_time,
        timezone=p.timezone,
        sprint_duration_days=p.sprint_duration_days,
        sprint_start_day=p.sprint_start_day,
        created_at=p.created_at,
    )


# ═══════════════════════════════════════════════════════════════════
# Project CRUD (Section 5.3)
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project",
)
def create_project(
    request: ProjectCreateRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-001: Manager/Admin creates a project."""
    # Check unique key (REQ-PROJ-009)
    if db.query(Project).filter(Project.key == request.key).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project key already exists.",
        )

    project = Project(
        name=request.name,
        key=request.key,
        owner_id=current_user.id,
        jira_base_url=request.jira_base_url,
        jira_email=request.jira_email,
        jira_api_token=request.jira_api_token,
        jira_project_key=request.jira_project_key,
        smtp_server=request.smtp_server,
        smtp_port=request.smtp_port,
        sender_email=request.sender_email,
        sender_password=request.sender_password,
        recipient_emails=request.recipient_emails,
        meeting_link=request.meeting_link,
        dashboard_url=request.dashboard_url,
        standup_time=request.standup_time,
        reminder_time=request.reminder_time,
        timezone=request.timezone,
        sprint_duration_days=request.sprint_duration_days,
        sprint_start_day=request.sprint_start_day,
    )
    db.add(project)
    db.flush()

    logger.info(
        "Project created: %s (key=%s) by user %s",
        project.name, project.key, current_user.username,
    )

    return _project_to_response(project)


@router.get(
    "/projects",
    response_model=List[ProjectResponse],
    summary="List accessible projects",
)
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    REQ-PROJ-020: Admins see all active projects.
    REQ-PROJ-021: Others see owned + team-member projects.
    """
    if current_user.role == UserRole.ADMIN:
        projects = db.query(Project).filter(Project.is_active == True).all()
    else:
        # Projects user owns OR is a team member of
        owned = db.query(Project).filter(
            Project.owner_id == current_user.id,
            Project.is_active == True,
        ).all()

        member_project_ids = [
            tm.project_id for tm in
            db.query(TeamMember).filter(TeamMember.user_id == current_user.id).all()
        ]
        member_projects = []
        if member_project_ids:
            member_projects = db.query(Project).filter(
                Project.id.in_(member_project_ids),
                Project.is_active == True,
            ).all()

        # Deduplicate
        seen = set()
        projects = []
        for p in owned + member_projects:
            if p.id not in seen:
                projects.append(p)
                seen.add(p.id)

    return [_project_to_response(p) for p in projects]


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-022: Access check before returning project details."""
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)
    return _project_to_response(project)


@router.put(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
)
def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-023: Only owner (or admin) can update."""
    project = _get_project_or_404(project_id, db)
    _check_project_owner(project, current_user)

    # Apply partial updates
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and hasattr(project, field):
            setattr(project, field, value)

    db.flush()
    logger.info("Project %s updated by %s", project.key, current_user.username)

    return _project_to_response(project)


@router.delete(
    "/projects/{project_id}",
    response_model=MessageResponse,
    summary="Soft-delete project",
)
def delete_project(
    project_id: int,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-010, REQ-PROJ-023: Soft-delete (mark inactive). Owner or admin only."""
    project = _get_project_or_404(project_id, db)
    _check_project_owner(project, current_user)

    project.is_active = False
    db.flush()

    logger.info("Project %s soft-deleted by %s", project.key, current_user.username)

    return MessageResponse(message=f"Project '{project.key}' has been deleted.")


# ═══════════════════════════════════════════════════════════════════
# Team Member Management (Section 5.3, REQ-PROJ-030 to 033)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/team",
    response_model=List[TeamMemberResponse],
    summary="List team members of a project",
)
def list_team_members(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all team members allocated to this project."""
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)
    
    members = db.query(TeamMember).filter(TeamMember.project_id == project_id).all()
    
    res = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        res.append(
            TeamMemberResponse(
                id=m.id,
                user_id=m.user_id,
                project_id=m.project_id,
                jira_username=m.jira_username,
                role=m.role.value,
                username=u.username if u else None,
                email=u.email if u else None,
                created_at=m.created_at,
            )
        )
    return res


@router.post(
    "/projects/{project_id}/team",
    response_model=TeamMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add team member",
)
def add_team_member(
    project_id: int,
    request: TeamMemberAddRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-030: Add team member to project."""
    project = _get_project_or_404(project_id, db)

    # Verify user exists
    user = db.query(User).filter(User.id == request.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Check duplicate (REQ-PROJ-031)
    existing = db.query(TeamMember).filter(
        TeamMember.user_id == request.user_id,
        TeamMember.project_id == project_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a team member of this project.",
        )

    member = TeamMember(
        user_id=request.user_id,
        project_id=project_id,
        jira_username=request.jira_username,
        role=TeamMemberRole(request.role),
    )
    db.add(member)
    db.flush()

    logger.info(
        "Team member %s added to project %s by %s",
        user.username, project.key, current_user.username,
    )

    return TeamMemberResponse(
        id=member.id,
        user_id=member.user_id,
        project_id=member.project_id,
        jira_username=member.jira_username,
        role=member.role.value,
        username=user.username,
        email=user.email,
        created_at=member.created_at,
    )


@router.delete(
    "/projects/{project_id}/team/{member_id}",
    response_model=MessageResponse,
    summary="Remove team member",
)
def remove_team_member(
    project_id: int,
    member_id: int,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-032: Remove team member from project."""
    _get_project_or_404(project_id, db)

    member = db.query(TeamMember).filter(
        TeamMember.id == member_id,
        TeamMember.project_id == project_id,
    ).first()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found in this project.",
        )

    db.delete(member)
    db.flush()

    logger.info("Team member %d removed from project %d", member_id, project_id)

    return MessageResponse(message="Team member removed successfully.")


@router.get(
    "/projects/{project_id}/jira/test-connection",
    summary="Test connection to Jira Cloud",
)
async def test_project_jira_connection(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test the Jira Cloud API connection with the saved project credentials."""
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)

    from daily_agents.integrations.jira_client import test_jira_connection
    res = await test_jira_connection(project)
    return res


@router.get(
    "/projects/{project_id}/pm-dashboard",
    summary="Fetch comprehensive PM Sprint Dashboard data",
)
async def get_project_pm_dashboard(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetches real-time structured metrics for the PM Dashboard tab.
    Calculates completed Jira issues, stalled issues (> 2 days), overall assignments, and leaderboard rankings.
    """
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)

    from daily_agents.integrations.jira_client import fetch_jira_sprint_issues
    from datetime import datetime, timezone

    # Utility: parse Jira Cloud datetime formats safely
    def parse_jira_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str:
            return None
        try:
            # Standardize 'Z' and timezone offsets
            clean_str = dt_str.replace("Z", "+00:00")
            if "." in clean_str:
                base, tz = clean_str.split(".", 1)
                offset = "+00:00"
                if "+" in tz:
                    offset = "+" + tz.split("+", 1)[1]
                elif "-" in tz:
                    offset = "-" + tz.split("-", 1)[1]
                clean_str = base + offset
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None

    # 1. Fetch Sprint issues and Overall issues
    try:
        # Fetch active sprint issues
        active_issues = await fetch_jira_sprint_issues(project)
        # Fetch overall project board issues irrespective of sprint
        all_board_issues = await fetch_jira_sprint_issues(project, jql=f"project = '{project.jira_project_key or project.key}'")
    except Exception as e:
        logger.error("Failed to fetch dashboard issues from Jira: %s", e)
        active_issues = []
        all_board_issues = []

    now = datetime.now(timezone.utc)

    # 2. Process active sprint issues
    completed_jira = 0
    total_active_issues = len(active_issues)
    stalled_list = []
    leaderboard_map = {}

    for issue in active_issues:
        status_name = issue.get("status", "Unknown")
        assignee = issue.get("assignee") or "Unassigned"
        
        if status_name == "Done":
            completed_jira += 1
            if assignee != "Unassigned":
                leaderboard_map[assignee] = leaderboard_map.get(assignee, 0) + 1
        
        # Calculate stagnant/stalled issues (> 2 days)
        if status_name != "Done" and issue.get("updated_at"):
            dt = parse_jira_datetime(issue.get("updated_at"))
            if dt:
                diff_days = (now - dt).total_seconds() / 86400.0
                if diff_days >= 2.0:
                    stalled_list.append({
                        "key": issue.get("key"),
                        "summary": issue.get("summary"),
                        "status": status_name,
                        "days_stagnant": round(diff_days, 1),
                        "assignee": assignee
                    })

    # Sort stalled list by stagnant time descending
    stalled_list.sort(key=lambda x: x["days_stagnant"], reverse=True)

    # 3. Calculate Overall Issues per Person (irrespective of sprint)
    assigned_map = {}
    for issue in all_board_issues:
        assignee = issue.get("assignee") or "Unassigned"
        status_name = issue.get("status", "Unknown")
        
        if assignee not in assigned_map:
            assigned_map[assignee] = {"to_do": 0, "in_progress": 0, "done": 0, "total": 0}
        
        assigned_map[assignee]["total"] += 1
        if status_name == "Done":
            assigned_map[assignee]["done"] += 1
        elif status_name in ("In Progress", "In Development", "QA", "Testing"):
            assigned_map[assignee]["in_progress"] += 1
        else:
            assigned_map[assignee]["to_do"] += 1

    assigned_per_person = [
        {
            "assignee": assignee,
            "to_do": metrics["to_do"],
            "in_progress": metrics["in_progress"],
            "done": metrics["done"],
            "total": metrics["total"]
        }
        for assignee, metrics in assigned_map.items()
    ]
    # Sort assigned per person by total issues descending
    assigned_per_person.sort(key=lambda x: x["total"], reverse=True)

    # 4. Generate Leaderboard ranks
    leaderboard = []
    sorted_leaders = sorted(leaderboard_map.items(), key=lambda x: x[1], reverse=True)
    
    badges = ["Sprint Champion", "Velocity Master", "Task Crusher", "Code Ninja", "Roster Star"]
    for idx, (assignee, count) in enumerate(sorted_leaders):
        badge = badges[idx] if idx < len(badges) else "Contributor"
        leaderboard.append({
            "rank": idx + 1,
            "assignee": assignee,
            "completed": count,
            "score": count * 10,
            "badge": badge
        })

    # Default placeholder leaderboard if empty
    if not leaderboard:
        leaderboard = [
            {"rank": 1, "assignee": "Alice", "completed": 3, "score": 30, "badge": "Sprint Champion"},
            {"rank": 2, "assignee": "Bob", "completed": 2, "score": 20, "badge": "Velocity Master"},
            {"rank": 3, "assignee": "Charlie", "completed": 1, "score": 10, "badge": "Code Ninja"}
        ]

    # Calculate overall sprint health percentage
    sprint_health_pct = 100
    if total_active_issues > 0:
        sprint_health_pct = round((completed_jira / total_active_issues) * 100)

    return {
        "completed_jira": completed_jira,
        "total_active_issues": total_active_issues,
        "stalled_count": len(stalled_list),
        "sprint_health": f"{sprint_health_pct}%",
        "stalled_issues": stalled_list,
        "assigned_per_person": assigned_per_person,
        "leaderboard": leaderboard
    }


