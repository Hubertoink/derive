"""Database-backed local accounts and opaque browser sessions for dérive."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import User, UserInvitation, UserSession


COOKIE_NAME = "derive_session"
SESSION_TTL_DAYS = max(1, min(31, int(os.getenv("DERIVE_SESSION_TTL_DAYS", "14"))))
INVITE_TTL_HOURS = max(1, min(24 * 30, int(os.getenv("DERIVE_INVITE_LIFETIME_HOURS", "48"))))
password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,79}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalise_email(value: str) -> str:
    return value.strip().casefold()


def normalise_username(value: str) -> str:
    return value.strip().casefold()


def validate_account_fields(username: str, email: str, password: str) -> tuple[str, str]:
    clean_username = username.strip()
    clean_email = normalise_email(email)
    if not USERNAME_RE.fullmatch(clean_username):
        raise ValueError("Der Benutzername braucht 3–80 Zeichen und darf Buchstaben, Zahlen, Punkt, Bindestrich und Unterstrich enthalten.")
    if "@" not in clean_email or len(clean_email) > 320:
        raise ValueError("Bitte gib eine gültige E-Mail-Adresse an.")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Das Passwort muss mindestens 12 Zeichen lang sein.")
    return clean_username, clean_email


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(session: Session, user: User) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    record = UserSession(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=utcnow() + timedelta(days=SESSION_TTL_DAYS),
        last_seen_at=utcnow(),
    )
    session.add(record)
    user.last_login_at = utcnow()
    session.commit()
    return token, record


def resolve_session(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    record = session.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > utcnow(),
        )
    )
    if record is None:
        return None
    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    record.last_seen_at = utcnow()
    session.commit()
    return user


def revoke_session(session: Session, token: str | None) -> None:
    if not token:
        return
    record = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if record and record.revoked_at is None:
        record.revoked_at = utcnow()
        session.commit()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def session_token_from_request(request: Request) -> str | None:
    # The explicit header is used by Next.js server rendering; browsers use the
    # HttpOnly cookie. Both values are opaque random tokens.
    return request.cookies.get(COOKIE_NAME) or request.headers.get("x-derive-session")


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user = resolve_session(session, session_token_from_request(request))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bitte melde dich an.")
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Diese Aktion ist nur für Administratoren verfügbar.")
    return user


def bootstrap_admin(session: Session) -> User | None:
    """Create the initial admin once; env credentials are never used for login."""
    if session.scalar(select(User.id).limit(1)) is not None:
        return None
    username = os.getenv("DERIVE_BOOTSTRAP_ADMIN_USERNAME") or os.getenv("DERIVE_AUTH_USERNAME") or ""
    email = os.getenv("DERIVE_BOOTSTRAP_ADMIN_EMAIL") or os.getenv("DERIVE_AUTH_EMAIL") or ""
    password = os.getenv("DERIVE_BOOTSTRAP_ADMIN_PASSWORD") or os.getenv("DERIVE_AUTH_PASSWORD") or ""
    if not username or not email or not password:
        return None
    try:
        clean_username, clean_email = validate_account_fields(username, email, password)
    except ValueError:
        return None
    user = User(
        username=clean_username,
        email=clean_email,
        password_hash=password_hasher.hash(password),
        role="admin",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def verify_password(user: User, password: str) -> bool:
    try:
        valid = password_hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    if valid and password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(password)
    return valid


def create_invitation(session: Session, inviter: User, email: str | None = None) -> tuple[str, UserInvitation]:
    token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        token_hash=token_hash(token),
        email=normalise_email(email) if email else None,
        invited_by_user_id=inviter.id,
        expires_at=utcnow() + timedelta(hours=INVITE_TTL_HOURS),
    )
    session.add(invitation)
    session.commit()
    return token, invitation


def redeem_invitation(session: Session, token: str, email: str) -> UserInvitation | None:
    invitation = session.scalar(
        select(UserInvitation).where(
            UserInvitation.token_hash == token_hash(token),
            UserInvitation.used_at.is_(None),
            UserInvitation.expires_at > utcnow(),
        )
    )
    if invitation is None:
        return None
    if invitation.email and invitation.email != normalise_email(email):
        return None
    return invitation
