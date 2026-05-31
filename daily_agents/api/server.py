"""
FastAPI Application Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Main entry point for the Engineering Manager Platform API.

Configures:
  - CORS (REQ-SEC-005, REQ-SEC-006)
  - Security headers (REQ-SEC-004)
  - Rate limiting (REQ-AUTH-005, REQ-AUTH-012)
  - Database auto-init on startup (REQ-REL-001)
  - Health check endpoint (REQ-OBS-002)
  - Thread pool lifecycle (REQ-PERF-001, REQ-REL-002)

Run:
  python -m daily_agents.api.server
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import active_count

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from daily_agents.config.settings import get_settings
from daily_agents.database.config import init_db

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Rate Limiter ─────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ── Thread Pool ──────────────────────────────────────────────────────

settings = get_settings()
thread_pool: ThreadPoolExecutor | None = None


# ── Lifespan ─────────────────────────────────────────────────────────

async def meeting_scheduler_daemon():
    """
    Background scheduler daemon.
    Every 30 seconds:
    - Finds scheduled meetings starting in the next 10 minutes (where reminder_sent is False),
      sends a pre-meeting email reminder to all project recipients, and updates reminder_sent=True.
    - Finds scheduled meetings whose scheduled start time has arrived or passed,
      automatically transitions their status to IN_PROGRESS, and updates actual_start.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta
    from daily_agents.database.config import SessionLocal
    from daily_agents.database.models import Meeting, MeetingStatus, Project, TeamMember, User
    from daily_agents.tools.agent_tools import send_email_report

    logger.info("📅 Background Meeting Scheduler Daemon started.")
    
    while True:
        try:
            await asyncio.sleep(30.0) # Check every 30 seconds
            
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                # 1. Check for Pre-Meeting Reminders (starts in <= 10 mins, reminder_sent is False)
                ten_mins_from_now = now + timedelta(minutes=10)
                upcoming_meetings = db.query(Meeting).filter(
                    Meeting.status == MeetingStatus.SCHEDULED,
                    Meeting.reminder_sent == False,
                    Meeting.scheduled_start <= ten_mins_from_now,
                    Meeting.scheduled_start > now # Make sure it's in the future
                ).all()

                for meeting in upcoming_meetings:
                    meeting.reminder_sent = True
                    db.flush()
                    
                    project = db.query(Project).filter(Project.id == meeting.project_id).first()
                    if project:
                        # Compile premium HTML email reminder content
                        local_time_str = meeting.scheduled_start.strftime("%Y-%m-%d %H:%M:%S UTC")
                        meeting_url = project.meeting_link or "N/A"
                        
                        email_html = f"""
                        <html>
                        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                                <h2 style="color: #4F46E5; margin-top: 0;">📅 Standup Meeting Reminder (10 Minutes Prior)</h2>
                                <p>Hi Team,</p>
                                <p>This is a quick reminder that a scheduled <strong>{meeting.meeting_type.value.capitalize()}</strong> meeting is starting in 10 minutes!</p>
                                
                                <div style="background-color: #f9fafb; padding: 15px; border-radius: 6px; margin: 20px 0;">
                                    <table style="width: 100%; border-collapse: collapse;">
                                        <tr>
                                            <td style="padding: 5px 0; font-weight: bold; width: 120px;">Meeting Type:</td>
                                            <td style="padding: 5px 0; color: #4F46E5; text-transform: capitalize;">{meeting.meeting_type.value}</td>
                                        </tr>
                                        <tr>
                                            <td style="padding: 5px 0; font-weight: bold;">Scheduled Start:</td>
                                            <td style="padding: 5px 0;">{local_time_str}</td>
                                        </tr>
                                        <tr>
                                            <td style="padding: 5px 0; font-weight: bold;">Meeting Link:</td>
                                            <td style="padding: 5px 0;"><a href="{meeting_url}" style="color: #4F46E5; text-decoration: none; font-weight: bold;">{meeting_url}</a></td>
                                        </tr>
                                    </table>
                                </div>
                                
                                <p>Please prepare your sprint status updates (completed Jiras, stalled blockers, and daily tasks) and be ready to join on time.</p>
                                <hr style="border: 0; border-top: 1px solid #e0e0e0; margin: 20px 0;" />
                                <p style="font-size: 11px; color: #777;">This is an automated notification dispatched by the Engineering Manager Platform.</p>
                            </div>
                        </body>
                        </html>
                        """
                        try:
                            send_email_report(project.id, email_html, db=db)
                            logger.info("Sent pre-meeting email reminder to team for meeting %d", meeting.id)
                        except Exception as e:
                            logger.error("Failed to send pre-meeting email reminder for meeting %d: %s", meeting.id, e)

                # 2. Check for Auto-Start/Auto-Join (scheduled, scheduled_start <= now)
                matures = db.query(Meeting).filter(
                    Meeting.status == MeetingStatus.SCHEDULED,
                    Meeting.scheduled_start <= now
                ).all()

                for meeting in matures:
                    meeting.status = MeetingStatus.IN_PROGRESS
                    meeting.actual_start = now
                    db.flush()
                    logger.info("Auto-started scheduled meeting %d: status changed to in_progress", meeting.id)

                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Error occurred in background meeting scheduler iteration: %s", e)
            finally:
                db.close()

        except asyncio.CancelledError:
            logger.info("Background Meeting Scheduler Daemon stopping...")
            break
        except Exception as e:
            logger.error("Unexpected error in background meeting scheduler: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle manager."""
    global thread_pool
    import asyncio

    # Startup
    logger.info("🚀 Starting Engineering Manager Platform v2.0")
    init_db()  # REQ-REL-001

    thread_pool = ThreadPoolExecutor(
        max_workers=settings.thread_pool_workers,
        thread_name_prefix="em-worker",
    )
    logger.info("Thread pool started with %d workers", settings.thread_pool_workers)

    # Spawn meeting scheduler daemon task
    scheduler_task = asyncio.create_task(meeting_scheduler_daemon())

    yield

    # Shutdown (REQ-REL-002)
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    if thread_pool:
        thread_pool.shutdown(wait=True)
        logger.info("Thread pool shut down gracefully.")
    logger.info("🛑 Server stopped.")


# ── FastAPI App ──────────────────────────────────────────────────────

app = FastAPI(
    title="Engineering Manager Platform",
    description="AI-powered engineering management with multi-agent orchestration",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="daily_agents/api/static"), name="static")


# ── CORS Middleware (REQ-SEC-005, REQ-SEC-006) ───────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


# ── Security Headers Middleware (REQ-SEC-004) ────────────────────────


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Inject security headers on every response."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    # Conditional CSP: Allow jsdelivr CDNs ONLY on Swagger / ReDoc pages, keep 'self' strict on operational API paths
    path = request.url.path
    if path in ("/docs", "/redoc", "/openapi.json"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "img-src 'self' data: fastly.jsdelivr.net cdn.jsdelivr.net;"
        )
    elif path == "/" or path.startswith("/static"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com fonts.googleapis.com; "
            "font-src 'self' cdnjs.cloudflare.com fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Register Routers ─────────────────────────────────────────────────

from daily_agents.api.auth import router as auth_router  # noqa: E402
from daily_agents.api.projects import router as projects_router  # noqa: E402
from daily_agents.api.meetings import router as meetings_router  # noqa: E402
from daily_agents.api.agent_routes import router as agent_router  # noqa: E402
from daily_agents.api.teams_routes import router as teams_router  # noqa: E402
from daily_agents.api.zoom_routes import router as zoom_router  # noqa: E402

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(meetings_router)
app.include_router(agent_router)
app.include_router(teams_router)
app.include_router(zoom_router)


# ── Apply Rate Limits to Auth Endpoints ──────────────────────────────
# We decorate the route functions after they're registered.
# slowapi requires decorating the actual endpoint functions.


# Find and decorate auth routes with rate limits
for route in app.routes:
    if hasattr(route, "path") and hasattr(route, "endpoint"):
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue

        # REQ-AUTH-005: Registration — 3/hour
        if path == "/api/auth/register":
            route.endpoint = limiter.limit("3/hour")(endpoint)

        # REQ-AUTH-012: Login — 5/minute
        elif path == "/api/auth/login":
            route.endpoint = limiter.limit("5/minute")(endpoint)

        # REQ-AUTH-026: Forgot password — 3/hour
        elif path == "/api/auth/forgot-password":
            route.endpoint = limiter.limit("3/hour")(endpoint)

        # REQ-AUTH-026: Reset password — 5/hour
        elif path == "/api/auth/reset-password":
            route.endpoint = limiter.limit("5/hour")(endpoint)


# ── System Endpoints (Section 5.7) ───────────────────────────────────


@app.get("/api/health", tags=["system"], summary="Health check")
def health_check():
    """
    REQ-OBS-002: Health check returning status, timestamp,
    worker count, active thread count.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workers": settings.thread_pool_workers,
        "active_threads": active_count(),
        "version": "2.0.0",
    }


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve single page web app at root."""
    return FileResponse("daily_agents/api/static/index.html")


# ── CLI Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "daily_agents.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        workers=1 if settings.debug else settings.uvicorn_workers,
    )
