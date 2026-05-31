"""
Agent Chat Routes
~~~~~~~~~~~~~~~~~
Exposes the multi-agent orchestration endpoint in the REST API.
Enables authenticated users to prompt the LangGraph agents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from daily_agents.api.dependencies import get_current_user
from daily_agents.api.projects import _check_project_access, _get_project_or_404
from daily_agents.database.config import get_db
from daily_agents.database.models import User
from daily_agents.graph import run_agent_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/agent", tags=["agent"])


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class AgentChatRequest(BaseModel):
    """Payload to prompt the AI agent."""
    message: str


class AgentChatResponse(BaseModel):
    """Summary and complete output returned by the agent workflow."""
    response: str
    status: str
    completed_agents: List[str]
    sprint_data: Optional[Dict[str, Any]] = None
    employee_data: Optional[List[Dict[str, Any]]] = None
    insights: Optional[str] = None
    email_sent: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Chat with the multi-agent Engineering Manager Supervisor",
)
async def chat_with_agent(
    project_id: int,
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Invokes the LangGraph supervisor workflow with the user's prompt.
    Verifies project access before initiating the multi-agent graph run.
    """
    # 1. Access Control Checks
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)

    logger.info(
        "User %s initiating agent workflow chat on project %s (ID=%d)",
        current_user.username, project.key, project_id
    )

    # 2. Run LangGraph Workflow
    final_state = await run_agent_workflow(
        project_id=project_id,
        user_id=current_user.id,
        message=request.message,
        db=db
    )

    # 3. Assemble and Return Response Schema
    return AgentChatResponse(
        response=final_state.get("final_response", ""),
        status=final_state.get("status", "completed"),
        completed_agents=final_state.get("completed_agents", []),
        sprint_data=final_state.get("sprint_data"),
        employee_data=final_state.get("employee_data"),
        insights=final_state.get("insights"),
        email_sent=final_state.get("email_sent"),
    )
