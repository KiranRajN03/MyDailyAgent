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
from fastapi.responses import JSONResponse, RedirectResponse
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle manager."""
    global thread_pool

    # Startup
    logger.info("🚀 Starting Engineering Manager Platform v2.0")
    init_db()  # REQ-REL-001

    thread_pool = ThreadPoolExecutor(
        max_workers=settings.thread_pool_workers,
        thread_name_prefix="em-worker",
    )
    logger.info("Thread pool started with %d workers", settings.thread_pool_workers)

    yield

    # Shutdown (REQ-REL-002)
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
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Register Routers ─────────────────────────────────────────────────

from daily_agents.api.auth import router as auth_router  # noqa: E402
from daily_agents.api.projects import router as projects_router  # noqa: E402
from daily_agents.api.meetings import router as meetings_router  # noqa: E402

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(meetings_router)


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
def root_redirect():
    """Redirect root to API docs."""
    return RedirectResponse(url="/docs")


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
