"""
Microsoft Teams Bot Webhook Endpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Processes outgoing webhook messages sent from Microsoft Teams.
Translates message payloads, triggers the agent graph, and returns Teams-formatted markdown messages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from daily_agents.database.config import get_db
from daily_agents.database.models import Project, User, UserRole
from daily_agents.graph import run_agent_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teams", tags=["teams"])


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class TeamsUser(BaseModel):
    id: str
    name: str


class IncomingTeamsMessage(BaseModel):
    """Microsoft Bot Framework / Teams Webhook message payload schema."""
    msg_type: str = Field("message", alias="type")
    text: str
    sender: Optional[TeamsUser] = Field(None, alias="from")
    channel_id: Optional[str] = Field(None, alias="channelId")
    tenant_id: Optional[str] = Field(None, alias="tenantId")


class TeamsMessageResponse(BaseModel):
    """Teams-compatible outgoing message format."""
    type: str = "message"
    text: str


# ═══════════════════════════════════════════════════════════════════
# Outgoing Webhook Endpoint
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/messages",
    response_model=TeamsMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Teams Outgoing Webhook receiver",
)
async def receive_teams_message(
    payload: IncomingTeamsMessage,
    project_id: Optional[int] = Query(None, description="Optional target project ID scope"),
    db: Session = Depends(get_db),
):
    """
    Receives messages from MS Teams channel mentions.
    Processes the request, runs the multi-agent supervisor graph, and returns a markdown response.
    """
    logger.info("Received incoming webhook from Microsoft Teams. Raw Text: '%s'", payload.text)

    # 1. Clean incoming text (strip HTML mention tags e.g., <at>myDailyAgent</at>)
    clean_text = re.sub(r"<at>.*?</at>", "", payload.text)
    clean_text = clean_text.strip()

    # 2. Determine target project scope
    target_project = None
    if project_id:
        target_project = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    
    if not target_project and payload.tenant_id:
        # Resolve project by matched teams_tenant_id config
        target_project = db.query(Project).filter(
            Project.is_active == True
            # In a real environment, we'd query by configured teams_tenant_id or custom settings
        ).first()

    # Fallback to first active project in DB
    if not target_project:
        target_project = db.query(Project).filter(Project.is_active == True).first()

    if not target_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active project configured in the platform database."
        )

    # 3. Resolve user identity
    sender_name = payload.sender.name if payload.sender else "Teams Bot"
    # Find matching user in the system by full name
    user = db.query(User).filter(User.full_name == sender_name, User.is_active == True).first()
    
    # Fallback to project owner or first admin/manager in database
    if not user:
        user = db.query(User).filter(User.id == target_project.owner_id).first()
    if not user:
        user = db.query(User).filter(User.role == UserRole.ADMIN).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not resolve user identity for Teams sender."
        )

    # 4. Trigger LangGraph Multi-Agent execution
    logger.info(
        "Routing Teams prompt to graph workflow for project ID %d as user %s",
        target_project.id, user.username
    )
    final_state = await run_agent_workflow(
        project_id=target_project.id,
        user_id=user.id,
        message=clean_text,
        db=db
    )

    # 5. Format and Return Response to Teams
    response_text = final_state.get("final_response", "Agent processed request with no response text.")
    
    return TeamsMessageResponse(text=response_text)
