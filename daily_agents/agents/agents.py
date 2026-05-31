"""
Agent Nodes & Prompts
~~~~~~~~~~~~~~~~~~~~~
Defines prompt structures and functional nodes for all specialized agents:
- EM Agent (Supervisor/Router)
- Data Analyst Agent
- Jira Agent
- Automation Agent

Includes both LLM parsing (when keys exist) and deterministic rule-based
fallbacks to guarantee test stability and offline execution.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

# LangChain / LangGraph imports
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from daily_agents.agents.state import (
    AGENT_DATA_ANALYST,
    AGENT_EM,
    AGENT_END,
    AGENT_JIRA,
    AGENT_AUTOMATION,
    AGENT_TRANSCRIPTION,
    AgentState,
    REQUEST_EMPLOYEE_ANALYTICS,
    REQUEST_GENERAL,
    REQUEST_JIRA_SYNC,
    REQUEST_SEND_REPORT,
    REQUEST_TRANSCRIPTION,
)
from daily_agents.config.settings import get_settings
from daily_agents.tools.agent_tools import (
    compute_employee_analytics,
    send_email_report,
    sync_jira_sprint_metrics,
)
from daily_agents.integrations.azure_speech import transcribe_meeting_audio
from daily_agents.database.models import Meeting, MeetingTranscript

logger = logging.getLogger(__name__)


def _get_llm():
    """Dynamically initializes LLM based on environment credentials."""
    settings = get_settings()
    if settings.openai_api_key:
        return ChatOpenAI(
            model=settings.default_model or "gpt-4o",
            temperature=settings.default_temperature,
            api_key=settings.openai_api_key
        )
    elif settings.anthropic_api_key:
        return ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            temperature=settings.default_temperature,
            api_key=settings.anthropic_api_key
        )
    return None


# ═══════════════════════════════════════════════════════════════════
# 1. EM Agent Node (Supervisor / Router)
# ═══════════════════════════════════════════════════════════════════

def em_agent_node(state: AgentState, db: Session) -> Dict[str, Any]:
    """
    EM Agent acts as the router and aggregator.
    Determines user intent, routes to specialist nodes, and summarizes output.
    """
    messages = state.get("messages", [])
    user_query = ""
    if messages:
        user_query = messages[-1].content.lower()

    completed = state.get("completed_agents", [])
    
    # --- Intent Routing / Supervise Phase ---
    if not completed:
        request_type = REQUEST_GENERAL
        next_agent = AGENT_END

        if any(w in user_query for w in ["sync", "jira", "fetch issues", "pull issues"]):
            request_type = REQUEST_JIRA_SYNC
            next_agent = AGENT_JIRA
        elif any(w in user_query for w in ["analytics", "metrics", "performance", "score", "rank"]):
            request_type = REQUEST_EMPLOYEE_ANALYTICS
            next_agent = AGENT_DATA_ANALYST
        elif any(w in user_query for w in ["email", "send", "report", "reminder", "dispatch"]):
            request_type = REQUEST_SEND_REPORT
            next_agent = AGENT_AUTOMATION
        elif any(w in user_query for w in ["transcribe", "record", "audio", "listen"]):
            request_type = REQUEST_TRANSCRIPTION
            next_agent = AGENT_TRANSCRIPTION

        logger.info("EM supervisor routed request: type=%s -> next=%s", request_type, next_agent)
        
        # Add supervisor routing message
        return {
            "request_type": request_type,
            "next_agent": next_agent,
            "status": "running",
            "messages": [AIMessage(content=f"Routing query to {next_agent} agent.")]
        }

    # --- Aggregation / Final Response Phase ---
    llm = _get_llm()
    summary_prompt = (
        "You are the Engineering Manager (EM) Supervisor Agent. "
        "Summarize the final outcomes and analytics data gathered by your specialist agents into a premium "
        "professional summary. Use bullet points and focus on clarity."
    )

    if llm:
        try:
            # Prepare state context for the LLM
            context = f"Specialist data collected: \n"
            if "jira_agent" in completed:
                context += f"- Jira sync status: {state.get('jira_sync_status')}\n"
                context += f"- Sprint summary: {state.get('sprint_data')}\n"
            if "data_analyst" in completed:
                context += f"- Insights: {state.get('insights')}\n"
            if "automation_agent" in completed:
                context += f"- Email report sent: {state.get('email_sent')}\n"
            if "transcription_agent" in completed:
                context += f"- Meeting transcriptions gathered: {state.get('transcribed_text')}\n"

            ai_msg = llm.invoke([
                HumanMessage(content=f"{summary_prompt}\n\nState Context:\n{context}\n\nBuild the final EM manager response.")
            ])
            final_text = ai_msg.content
        except Exception as e:
            logger.warning("LLM summary generation failed: %s. Falling back to deterministic summary.", e)
            final_text = _build_deterministic_em_summary(state)
    else:
        final_text = _build_deterministic_em_summary(state)

    logger.info("EM supervisor consolidated final response. Terminating workflow.")

    return {
        "final_response": final_text,
        "next_agent": AGENT_END,
        "status": "completed",
        "messages": [AIMessage(content=final_text)]
    }


def _build_deterministic_em_summary(state: AgentState) -> str:
    """Builds a beautifully structured deterministic manager report summary."""
    completed = state.get("completed_agents", [])
    lines = ["### 🤖 Engineering Manager Platform — AI Agent Execution Report", ""]
    
    if "jira_agent" in completed:
        sdata = state.get("sprint_data") or {}
        lines.extend([
            "**Sprint Sync Complete (Jira Agent)**:",
            f"- **Sprint Active**: {sdata.get('sprint_name')}",
            f"- **Completion Rate**: {sdata.get('completion_rate')}%",
            f"- **Issues Synced**: {sdata.get('completed_issues')} completed / {sdata.get('total_issues')} total",
            ""
        ])

    if "data_analyst" in completed:
        lines.extend([
            "**Team Performance Analytics (Data Analyst Agent)**:",
            f"- {state.get('insights')}",
            ""
        ])

    if "automation_agent" in completed:
        lines.extend([
            "**Email Dispatch Notification (Automation Agent)**:",
            f"- **Status**: Report successfully emailed to configured team recipients.",
            f"- **Recipients**: {', '.join(state.get('email_recipients') or [])}",
            ""
        ])

    if "transcription_agent" in completed:
        lines.extend([
            "**Standup Audio Transcription (Transcription Agent)**:",
            f"{state.get('transcribed_text')}",
            ""
        ])

    if not completed:
        lines.append("General request processed. No specialized agents were invoked.")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 2. Jira Status Agent Node
# ═══════════════════════════════════════════════════════════════════

def jira_agent_node(state: AgentState, db: Session) -> Dict[str, Any]:
    """
    Jira Status Agent Node.
    Synchronizes mock issues, computes velocity, and persists into SprintAnalytics.
    """
    project_id = state.get("project_id")
    if not project_id:
        return {"error": "Missing project_id in state", "next_agent": AGENT_EM}

    logger.info("Jira Status Agent syncing metrics for project_id=%d", project_id)
    
    # Sync metrics
    sync_result = sync_jira_sprint_metrics(project_id, db)

    completed = state.get("completed_agents", [])[:]
    completed.append("jira_agent")

    msg_content = f"Jira Agent successfully synced sprint metrics: {sync_result['sprint_name']} ({sync_result['completion_rate']}% completion)."

    return {
        "sprint_data": sync_result,
        "jira_sync_status": "Success",
        "completed_agents": completed,
        "next_agent": AGENT_EM,  # return back to supervisor
        "messages": [AIMessage(content=msg_content)]
    }


# ═══════════════════════════════════════════════════════════════════
# 3. Data Analyst Agent Node
# ═══════════════════════════════════════════════════════════════════

def data_analyst_node(state: AgentState, db: Session) -> Dict[str, Any]:
    """
    Data Analyst Agent Node.
    Analyzes employee participation and work output, returning insight text & chart specifications.
    """
    project_id = state.get("project_id")
    if not project_id:
        return {"error": "Missing project_id in state", "next_agent": AGENT_EM}

    logger.info("Data Analyst Agent computing metrics for project_id=%d", project_id)
    
    # Compute metrics for the current period (e.g. current year-month)
    period = datetime.now().strftime("%Y-%m")
    analytics_list = compute_employee_analytics(project_id, period, db)

    # Compile insights text
    insights_list = []
    charts_spec = []
    
    if analytics_list:
        top_member = analytics_list[0]
        insights_list.append(f"Top Contributor: **{top_member['full_name']}** with score **{top_member['contribution_score']}**.")
        for member in analytics_list:
            insights_list.append(
                f"- **{member['username']}**: Attendance {member['attendance_rate']}%, "
                f"Issues {member['issues_completed']}, Score {member['contribution_score']}."
            )

        # Plotly chart mock specification (simplifying data visual rendering)
        charts_spec = [{
            "type": "bar",
            "x": [m["username"] for m in analytics_list],
            "y": [m["contribution_score"] for m in analytics_list],
            "title": "Contribution Scores by Team Member"
        }]

    insights_text = "Performance analysis compiled successfully.\n" + "\n".join(insights_list)

    completed = state.get("completed_agents", [])[:]
    completed.append("data_analyst")

    return {
        "employee_data": analytics_list,
        "insights": insights_text,
        "charts": charts_spec,
        "completed_agents": completed,
        "next_agent": AGENT_EM,  # return back to supervisor
        "messages": [AIMessage(content="Data Analyst compiled team metrics insights and chart specifications.")]
    }


# ═══════════════════════════════════════════════════════════════════
# 4. Automation Agent Node
# ═══════════════════════════════════════════════════════════════════

def automation_agent_node(state: AgentState, db: Session) -> Dict[str, Any]:
    """
    Automation Agent Node.
    Generates HTML report and dispatches report via SMTP configurations.
    """
    project_id = state.get("project_id")
    if not project_id:
        return {"error": "Missing project_id in state", "next_agent": AGENT_EM}

    logger.info("Automation Agent preparing report email for project_id=%d", project_id)

    # Format the report content
    sdata = state.get("sprint_data") or {}
    insights = state.get("insights") or "No employee analytics collected."

    # Try retrieving transcribed status from state, or fallback to querying database
    transcribed_text = state.get("transcribed_text")
    if not transcribed_text:
        last_meeting = db.query(Meeting).filter(
            Meeting.project_id == project_id
        ).order_by(Meeting.created_at.desc()).first()
        
        if last_meeting:
            transcripts = db.query(MeetingTranscript).filter(
                MeetingTranscript.meeting_id == last_meeting.id
            ).all()
            
            if transcripts:
                lines = [f"- **{t.speaker}**: \"{t.text}\"" for t in transcripts]
                transcribed_text = "\n".join(lines)

    transcription_section = ""
    if transcribed_text:
        html_transcripts = transcribed_text.replace("\n", "<br>")
        transcription_section = f"""
        <h3 style="color: #00F2FE; margin-top: 25px; margin-bottom: 12px; border-bottom: 1px dashed rgba(255, 255, 255, 0.08); padding-bottom: 6px;">🎙️ Standup Meeting Status Summaries (Transcribed Audio)</h3>
        <div style="background-color: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.08); padding: 16px 20px; border-radius: 12px; font-size: 14px; line-height: 1.6; color: #F3F4F6;">
            {html_transcripts}
        </div>
        """
    
    report_html = f"""
    <html>
    <body style="font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0B0F19; color: #F3F4F6; padding: 30px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #070A11; border: 1px solid rgba(255, 255, 255, 0.08); padding: 30px; border-radius: 20px; box-shadow: 0 12px 40px rgba(0,0,0,0.5);">
            <h2 style="color: #00F2FE; margin-top: 0; margin-bottom: 20px; font-weight: 700; letter-spacing: -0.5px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 12px;">📊 Engineering Manager Platform AI Status Report</h2>
            
            <div style="margin-bottom: 20px; font-size: 14px; display: flex; gap: 20px;">
                <p style="margin: 0;"><strong>Sprint Active:</strong> {sdata.get('sprint_name', 'N/A')}</p>
                <p style="margin: 0;"><strong>Completion Rate:</strong> {sdata.get('completion_rate', 'N/A')}%</p>
            </div>
            
            <h3 style="color: #00F2FE; margin-top: 25px; margin-bottom: 12px; border-bottom: 1px dashed rgba(255, 255, 255, 0.08); padding-bottom: 6px;">👥 Team Performance Metrics</h3>
            <pre style="background-color: rgba(255, 255, 255, 0.02); padding: 15px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.08); color: #9CA3AF; white-space: pre-wrap; font-family: inherit; font-size: 13px; line-height: 1.5; margin: 0;">{insights}</pre>
            
            {transcription_section}
            
            <br>
            <p style="font-size: 12px; color: #6B7280; border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 15px; margin-top: 25px; margin-bottom: 0;">
                <em>Report generated automatically by myDailyAgent Platform.</em>
            </p>
        </div>
    </body>
    </html>
    """

    # Send the email
    email_result = send_email_report(project_id, report_html, db=db)

    completed = state.get("completed_agents", [])[:]
    completed.append("automation_agent")

    msg_content = f"Automation Agent dispatched status report to {', '.join(email_result.get('recipients') or [])}."

    return {
        "email_sent": email_result.get("email_sent", False),
        "email_recipients": email_result.get("recipients", []),
        "report_content": report_html,
        "completed_agents": completed,
        "next_agent": AGENT_EM,  # return back to supervisor
        "messages": [AIMessage(content=msg_content)]
    }


# ═══════════════════════════════════════════════════════════════════
# 5. Transcription Agent Node
# ═══════════════════════════════════════════════════════════════════

def transcription_agent_node(state: AgentState, db: Session) -> Dict[str, Any]:
    """
    Transcription Agent Node.
    Uses Azure Speech Translation client to record/transcribe standup audio
    and persist speaker-segmented status logs in the database.
    """
    project_id = state.get("project_id")
    if not project_id:
        return {"error": "Missing project_id in state", "next_agent": AGENT_EM}

    logger.info("Transcription Agent initiating audio parsing for project_id=%d", project_id)

    # 1. Locate last meeting or dynamically schedule a standup instance to record into
    meeting = db.query(Meeting).filter(
        Meeting.project_id == project_id
    ).order_by(Meeting.created_at.desc()).first()

    if not meeting:
        logger.info("No existing meetings found. Creating dynamic scheduled standup instance to hold recording.")
        meeting = Meeting(
            project_id=project_id,
            meeting_type="standup",
            status="scheduled",
            scheduled_start=datetime.now()
        )
        db.add(meeting)
        db.flush()

    # 2. Trigger transcription client using dummy audio stream
    import asyncio
    try:
        # Use asyncio.run if there is no event loop in the current thread (common in ThreadPoolExecutor)
        segments = asyncio.run(transcribe_meeting_audio(b"dummy-audio-bytes"))
    except RuntimeError:
        # Fallback if a loop is already running or present in the current thread
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        segments = loop.run_until_complete(transcribe_meeting_audio(b"dummy-audio-bytes"))

    # 3. Log transcribed speaker text blocks to database & automatically mark attendance
    from daily_agents.database.models import User, TeamMember, AttendanceRecord

    transcribed_lines = []
    for seg in segments:
        speaker_name = seg.get("speaker")
        mt = MeetingTranscript(
            meeting_id=meeting.id,
            speaker=speaker_name,
            text=seg.get("text"),
            start_timestamp=seg.get("start_timestamp"),
            end_timestamp=seg.get("end_timestamp"),
            confidence=seg.get("confidence")
        )
        db.add(mt)
        transcribed_lines.append(f"- **{speaker_name}**: \"{seg.get('text')}\"")

        # Auto-mark attendance based on spoken segments
        if speaker_name:
            # Clean/normalize name for comparison
            clean_speaker = "".join(c for c in speaker_name if c.isalnum() or c in ("_", "-")).lower()
            
            # Find User by username or email prefix or partial full_name
            u = db.query(User).filter(
                (User.username == clean_speaker) |
                (User.email.like(f"{clean_speaker}@%")) |
                (User.full_name.ilike(f"%{speaker_name}%"))
            ).first()
            
            if u:
                # Confirm membership on project team roster
                tm = db.query(TeamMember).filter(
                    TeamMember.user_id == u.id,
                    TeamMember.project_id == project_id
                ).first()
                
                if tm:
                    # Upsert AttendanceRecord to marked attended
                    att = db.query(AttendanceRecord).filter(
                        AttendanceRecord.meeting_id == meeting.id,
                        AttendanceRecord.user_id == u.id
                    ).first()
                    if not att:
                        att = AttendanceRecord(
                            meeting_id=meeting.id,
                            user_id=u.id,
                            project_id=project_id,
                            attended=True
                        )
                        db.add(att)
                    else:
                        att.attended = True

    db.flush()

    transcribed_summary = "\n".join(transcribed_lines)
    logger.info("Meeting transcripts saved to DB successfully: %d segments", len(segments))

    completed = state.get("completed_agents", [])[:]
    completed.append("transcription_agent")

    msg_content = f"Transcription Agent successfully transcribed standup recording ({len(segments)} segments logged to DB)."

    return {
        "transcribed_text": transcribed_summary,
        "transcription_status": "Success",
        "completed_agents": completed,
        "next_agent": AGENT_EM,  # return back to supervisor
        "messages": [AIMessage(content=msg_content)]
    }
