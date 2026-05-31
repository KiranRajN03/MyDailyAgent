"""
Zoom Bot & Webhook Receiver Endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Option A: Receives slash commands/notifications from Zoom Chat Apps.
Option B: Listens for completed meeting cloud recordings to auto-transcribe and email summaries.
"""

from __future__ import annotations

import hmac
import hashlib
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from daily_agents.database.config import get_db
from daily_agents.database.models import Project, User, UserRole
from daily_agents.graph import run_agent_workflow
from daily_agents.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zoom", tags=["zoom"])


# ── Option A: Chatbot Schemas ────────────────────────────────────────

class ZoomChatPayload(BaseModel):
    cmd: str
    userId: str
    userName: str
    robotJid: str


class IncomingZoomChatMessage(BaseModel):
    event: str
    payload: ZoomChatPayload


# ── Option B: Webhook/Handshake Schemas ──────────────────────────────

class ZoomWebhookRequest(BaseModel):
    event: str
    payload: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════
# Option A: Zoom Chat App Receiver
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/messages",
    status_code=status.HTTP_200_OK,
    summary="Zoom Chatbot Outgoing Webhook receiver",
)
async def receive_zoom_chat_message(
    request: IncomingZoomChatMessage,
    project_id: Optional[int] = Query(None, description="Optional target project scope"),
    db: Session = Depends(get_db),
):
    """
    Receives incoming queries/commands entered inside Zoom Chat channels.
    Routes prompts to the LangGraph supervisor workflow, and returns a Zoom-compatible card/text response.
    """
    logger.info("Received incoming chatbot query from Zoom. Cmd: '%s'", request.payload.cmd)

    # 1. Clean query string
    clean_text = request.payload.cmd.strip()

    # 2. Resolve target project scope
    target_project = None
    if project_id:
        target_project = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    
    if not target_project:
        # Fallback to first active project in database
        target_project = db.query(Project).filter(Project.is_active == True).first()

    if not target_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active project configured in the platform database."
        )

    # 3. Resolve user identity
    sender_name = request.payload.userName
    user = db.query(User).filter(User.full_name == sender_name, User.is_active == True).first()
    
    if not user:
        user = db.query(User).filter(User.username == request.payload.userId, User.is_active == True).first()
    if not user:
        user = db.query(User).filter(User.id == target_project.owner_id).first()
    if not user:
        user = db.query(User).filter(User.role == UserRole.ADMIN).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not resolve user identity for Zoom sender."
        )

    # 4. Trigger Supervisor workflow
    logger.info(
        "Routing Zoom chat prompt to graph workflow for project ID %d as user %s",
        target_project.id, user.username
    )
    final_state = await run_agent_workflow(
        project_id=target_project.id,
        user_id=user.id,
        message=clean_text,
        db=db
    )

    # 5. Format Zoom chatbot card body response
    response_text = final_state.get("final_response", "Agent processed request with no response text.")
    
    return {
        "robotJid": request.payload.robotJid,
        "toJid": request.payload.robotJid,
        "accountId": "zoom-platform-account",
        "content": {
            "head": {
                "text": "myDailyAgent Response summary"
            },
            "body": [
                {
                    "type": "message",
                    "text": response_text
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════
# Option B: Zoom Cloud Recording Completed / URL Verification
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/recordings",
    status_code=status.HTTP_200_OK,
    summary="Zoom Cloud Recording Webhook Event Receiver",
)
async def receive_zoom_recording_webhook(
    request: ZoomWebhookRequest,
    project_id: Optional[int] = Query(None, description="Optional target project scope"),
    db: Session = Depends(get_db),
):
    """
    Handles Zoom webhook events:
    1. endpoint.url_validation handshake challenge (hashes token using HMAC-SHA256 signature).
    2. recording.completed event (downloads audio file and executes autonomous transcription -> email summary flow).
    """
    event_type = request.event
    logger.info("Received Zoom recording webhook event: %s", event_type)

    # 1. URL Handshake Challenge Verification Handshake
    if event_type == "endpoint.url_validation":
        payload = request.payload or {}
        plain_token = payload.get("plainToken")
        if not plain_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing plainToken inside URL validation challenge payload."
            )
        
        # Hash plainToken using Zoom Webhook Secret Token key
        settings = get_settings()
        zoom_secret = settings.sender_password or "zoom-secret-key-signature" # fallback key
        
        encrypted_token = hmac.new(
            zoom_secret.encode("utf-8"),
            plain_token.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        logger.info("Endpoint url validation completed successfully.")
        return {
            "plainToken": plain_token,
            "encryptedToken": encrypted_token
        }

    # 2. Recording Completed Automated Flow
    if event_type == "recording.completed":
        payload = request.payload or {}
        meeting_object = payload.get("object") or {}
        topic = meeting_object.get("topic", "Zoom Audio Meeting")
        
        logger.info("Zoom recording completed for meeting: '%s'", topic)

        # Retrieve target project scope
        target_project = None
        if project_id:
            target_project = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
        if not target_project:
            target_project = db.query(Project).filter(Project.is_active == True).first()

        if not target_project:
            logger.warning("No active project found. Skipping automatic recording summary dispatch.")
            return {"status": "skipped", "reason": "No active project configured in DB."}

        # Resolve requesting user (defaults to project owner)
        user = db.query(User).filter(User.id == target_project.owner_id).first()
        if not user:
            user = db.query(User).filter(User.role == UserRole.ADMIN).first()

        if not user:
            logger.warning("No active users found. Skipping automatic recording summary dispatch.")
            return {"status": "skipped", "reason": "No active users in DB."}

        # Extract audio recording download url
        files = meeting_object.get("recording_files") or []
        audio_url = None
        for f in files:
            if f.get("file_type") in ("M4A", "MP4", "WAV", "MP3"):
                audio_url = f.get("download_url")
                break

        if not audio_url:
            logger.warning("No audio files found inside the Zoom recording completed webhook.")
            return {"status": "skipped", "reason": "No valid M4A/audio files inside payload."}

        # Autonomous Flow Trigger (Sequential multi-agent execution):
        # 1. Transcribe the meeting audio
        logger.info(
            "Step 1: Kicking off Transcription Specialist Agent for Zoom recording topic '%s'", topic
        )
        transcribe_state = await run_agent_workflow(
            project_id=target_project.id,
            user_id=user.id,
            message="Please transcribe our meeting recording audio",
            db=db
        )

        # 2. Compile metrics and email report with transcripts
        logger.info(
            "Step 2: Kicking off Automation Agent to compile report and send email for Zoom topic '%s'", topic
        )
        final_state = await run_agent_workflow(
            project_id=target_project.id,
            user_id=user.id,
            message="Send the email report summary of our sprint now",
            db=db
        )

        return {
            "status": "success",
            "meeting_topic": topic,
            "transcription_status": transcribe_state.get("transcription_status"),
            "email_sent": final_state.get("email_sent"),
            "completed_agents": final_state.get("completed_agents") or []
        }

    return {"status": "ignored", "event": event_type}
