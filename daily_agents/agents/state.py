"""
Agent State Definition
~~~~~~~~~~~~~~~~~~~~~~~
Shared state that flows through the LangGraph multi-agent system.

The EM Platform uses a supervisor pattern where the EM Agent routes
requests to specialist agents (Data Analyst, Jira, Automation).
All agents read/write to this shared state.

Architecture:
  User Request → EM Agent (Router/Supervisor)
                  ├── Data Analyst Agent → analytics, insights
                  ├── Jira Agent → sprint data, velocity
                  └── Automation Agent → emails, reports
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict

# pyrefly: ignore [missing-import]
from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    """
    Shared state flowing through the LangGraph agent graph.

    All fields are optional (total=False) so agents can selectively
    read/write only the fields they care about.
    """

    # ── Request Context ──────────────────────────────────────────────
    messages: List[BaseMessage]         # Conversation history
    user_id: int                        # Requesting user's ID
    project_id: Optional[int]           # Target project (if scoped)
    request_type: str                   # What the user wants

    # ── Routing ──────────────────────────────────────────────────────
    next_agent: str                     # Which agent to invoke next
    completed_agents: List[str]         # Agents that have finished

    # ── Data Analyst Output ──────────────────────────────────────────
    sprint_data: Optional[Dict[str, Any]]        # Sprint analytics
    employee_data: Optional[List[Dict[str, Any]]] # Employee metrics
    insights: Optional[str]                       # AI-generated insights
    charts: Optional[List[Dict[str, Any]]]        # Chart specifications

    # ── Jira Agent Output ────────────────────────────────────────────
    jira_issues: Optional[List[Dict[str, Any]]]   # Fetched Jira issues
    jira_velocity: Optional[Dict[str, Any]]       # Sprint velocity data
    jira_sync_status: Optional[str]               # Sync result message

    # ── Automation Agent Output ──────────────────────────────────────
    email_sent: Optional[bool]                    # Email dispatch result
    email_recipients: Optional[List[str]]         # Who received the email
    report_content: Optional[str]                 # Generated report text

    # ── Transcription Agent Output ───────────────────────────────────
    transcription_status: Optional[str]           # Transcription sync status
    transcribed_text: Optional[str]               # Complete parsed transcript text

    # ── Final Output ─────────────────────────────────────────────────
    final_response: Optional[str]       # Aggregated response to user
    error: Optional[str]                # Error message if something failed
    status: Literal["pending", "running", "completed", "failed"]


# ── Request Types ────────────────────────────────────────────────────
# These constants define what the EM Agent can route.

REQUEST_SPRINT_REPORT = "sprint_report"
REQUEST_EMPLOYEE_ANALYTICS = "employee_analytics"
REQUEST_JIRA_SYNC = "jira_sync"
REQUEST_SEND_REPORT = "send_report"
REQUEST_MEETING_SUMMARY = "meeting_summary"
REQUEST_STANDUP_REMINDER = "standup_reminder"
REQUEST_GENERAL = "general"
REQUEST_TRANSCRIPTION = "transcription"

# ── Agent Names ──────────────────────────────────────────────────────

AGENT_EM = "em_agent"
AGENT_DATA_ANALYST = "data_analyst"
AGENT_JIRA = "jira_agent"
AGENT_AUTOMATION = "automation_agent"
AGENT_TRANSCRIPTION = "transcription_agent"
AGENT_END = "end"
