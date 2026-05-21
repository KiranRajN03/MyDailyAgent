"""
Authentication & User Management Routes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI router for registration, login, password reset,
and admin user management.

References:
  - Section 5.1: Auth endpoints
  - Section 5.2: User management endpoints
  - REQ-ROLE-001: First user is Admin
  - REQ-ROLE-002: Subsequent users get Member role
  - REQ-AUTH-005/012/026: Rate limiting
  - REQ-AUTH-013/REQ-SEC-010: Failed login logging with IP
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from daily_agents.api.dependencies import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    require_manager,
    verify_password,
)
from daily_agents.api.schemas import (
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserCreateRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    UserUpdateRequest,
)
from daily_agents.database.config import get_db
from daily_agents.database.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])


# ═══════════════════════════════════════════════════════════════════
# Auth Endpoints (Section 5.1)
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """
    REQ-AUTH-001 to REQ-AUTH-006: User self-registration.
    REQ-ROLE-001: First user becomes Admin.
    REQ-ROLE-002: All others get Member role.
    """
    # Check for duplicate username (REQ-AUTH-006)
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        )

    # Check for duplicate email (REQ-AUTH-006)
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    # First-User Rule (REQ-ROLE-001)
    user_count = db.query(User).count()
    role = UserRole.ADMIN if user_count == 0 else UserRole.MEMBER

    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        role=role,
    )
    db.add(user)
    db.flush()

    logger.info(
        "User registered: %s (id=%d, role=%s)", user.username, user.id, role.value
    )

    token = create_access_token(user.id, user.username, role.value)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=role.value,
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Login and get JWT",
)
def login(
    request: UserLoginRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """
    REQ-AUTH-010 to REQ-AUTH-015: Authenticate via username/password, return JWT.
    REQ-AUTH-013 / REQ-SEC-010: Log failed attempts with IP.
    """
    user = db.query(User).filter(User.username == request.username).first()

    if user is None or not verify_password(request.password, user.password_hash):
        # Log failed attempt with IP (REQ-AUTH-013)
        client_ip = http_request.client.host if http_request.client else "unknown"
        logger.warning(
            "Failed login attempt for username=%s from IP=%s",
            request.username,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact an administrator.",
        )

    logger.info("User logged in: %s (id=%d)", user.username, user.id)

    token = create_access_token(user.id, user.username, user.role.value)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )


@router.post(
    "/auth/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    REQ-AUTH-020 to REQ-AUTH-022: Generate reset token.
    REQ-AUTH-021: Always return success to prevent email enumeration.
    """
    # Always return success (REQ-AUTH-021)
    success_msg = MessageResponse(
        message="If the email exists, a password reset link has been sent."
    )

    user = db.query(User).filter(User.email == request.email).first()
    if user is None:
        return success_msg

    # Generate reset token (REQ-AUTH-022)
    reset_token = secrets.token_urlsafe(32)
    user.reset_token = reset_token
    user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)  # REQ-AUTH-023
    db.flush()

    logger.info("Password reset requested for user: %s", user.username)

    # TODO: Phase 5 — Send email with reset link (REQ-AUTH-025)
    # For now, log the token for development
    logger.debug("Reset token for %s: %s", user.username, reset_token)

    return success_msg


@router.post(
    "/auth/reset-password",
    response_model=MessageResponse,
    summary="Reset password with token",
)
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    REQ-AUTH-022 to REQ-AUTH-024: Validate token, reset password, clear token.
    """
    user = db.query(User).filter(User.reset_token == request.token).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    # Check expiry (REQ-AUTH-023)
    # Note: SQLite may return timezone-naive datetimes, so normalize both sides
    now_utc = datetime.utcnow()
    expiry = user.reset_token_expiry
    if expiry is not None and expiry.tzinfo is not None:
        expiry = expiry.replace(tzinfo=None)
    if expiry is None or expiry < now_utc:
        # Clear expired token
        user.reset_token = None
        user.reset_token_expiry = None
        db.flush()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired. Please request a new one.",
        )

    # Update password and clear token (REQ-AUTH-024)
    user.password_hash = hash_password(request.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.flush()

    logger.info("Password reset completed for user: %s", user.username)

    return MessageResponse(message="Password has been reset successfully.")


@router.get(
    "/auth/me",
    response_model=UserResponse,
    summary="Get current user info",
)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


# ═══════════════════════════════════════════════════════════════════
# User Management Endpoints (Section 5.2)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="List all active users",
)
def list_users(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """REQ-PROJ-021 / Permission Matrix: Manager+ can view all users."""
    users = db.query(User).filter(User.is_active == True).all()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create user with role (Admin only)",
)
def create_user(
    request: UserCreateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """REQ-AUTH-030: Admin creates user with specific role."""
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        )
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        role=request.role,
    )
    db.add(user)
    db.flush()

    logger.info(
        "Admin %s created user: %s (role=%s)",
        current_user.username,
        user.username,
        user.role.value,
    )

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Get user details (Admin only)",
)
def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """REQ-AUTH-031: Admin views user details."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user (Admin only)",
)
def update_user(
    user_id: int,
    request: UserUpdateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """REQ-AUTH-031 to REQ-AUTH-033: Admin updates user fields."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Check email conflict (REQ-AUTH-033)
    if request.email is not None and request.email != user.email:
        if db.query(User).filter(User.email == request.email).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use by another user.",
            )
        user.email = request.email

    if request.full_name is not None:
        user.full_name = request.full_name
    if request.role is not None:
        user.role = request.role
    if request.is_active is not None:
        user.is_active = request.is_active
    if request.password is not None:
        user.password_hash = hash_password(request.password)

    db.flush()

    logger.info("Admin %s updated user %d", current_user.username, user_id)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )
