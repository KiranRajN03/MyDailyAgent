"""
API Dependencies
~~~~~~~~~~~~~~~~
JWT authentication, current-user extraction, and Role-Based
Access Control (RBAC) guard dependencies for FastAPI.

References:
  - REQ-AUTH-011: JWT with user_id, username, role
  - REQ-AUTH-014: Configurable JWT expiry
  - REQ-AUTH-015: bcrypt password hashing
  - REQ-SEC-008: All endpoints (except health) require JWT
  - Section 2.1 / 2.2: Role definitions and permission matrix
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import List, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from daily_agents.config.settings import get_settings
from daily_agents.database.config import get_db
from daily_agents.database.models import User, UserRole

logger = logging.getLogger(__name__)

# Bearer token extraction
security_scheme = HTTPBearer(auto_error=False)


# ═══════════════════════════════════════════════════════════════════
# Password Hashing (REQ-AUTH-015, REQ-SEC-009)
# ═══════════════════════════════════════════════════════════════════


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with auto-generated salt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ═══════════════════════════════════════════════════════════════════
# JWT Token Management (REQ-AUTH-011, REQ-AUTH-014)
# ═══════════════════════════════════════════════════════════════════


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token containing user_id, username, and role.

    Args:
        user_id: The user's database ID.
        username: The user's username.
        role: The user's role string.
        expires_delta: Custom expiry. Defaults to settings.jwt_expire_minutes.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT access token.

    Returns:
        The decoded payload dict.

    Raises:
        HTTPException 401 on invalid/expired token.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ═══════════════════════════════════════════════════════════════════
# Current User Dependency (REQ-SEC-008)
# ═══════════════════════════════════════════════════════════════════


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: extract and validate the current user from JWT.
    Raises 401 if no token, invalid token, or user not found/inactive.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


# ═══════════════════════════════════════════════════════════════════
# RBAC Guards (Section 2.1, 2.2)
# ═══════════════════════════════════════════════════════════════════

# Role hierarchy: admin > manager > team_lead > member
ROLE_HIERARCHY = {
    UserRole.ADMIN: 4,
    UserRole.MANAGER: 3,
    UserRole.TEAM_LEAD: 2,
    UserRole.MEMBER: 1,
}


def require_role(minimum_role: UserRole):
    """
    FastAPI dependency factory: require the user to have at least
    the specified role level.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role(UserRole.ADMIN))])
        async def admin_endpoint(): ...

    Or as a parameter dependency:
        current_user: User = Depends(require_role(UserRole.MANAGER))
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_level = ROLE_HIERARCHY.get(current_user.role, 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {minimum_role.value} or higher.",
            )
        return current_user
    return role_checker


# Convenience dependencies for common role checks
require_admin = require_role(UserRole.ADMIN)
require_manager = require_role(UserRole.MANAGER)
require_team_lead = require_role(UserRole.TEAM_LEAD)
require_member = require_role(UserRole.MEMBER)
