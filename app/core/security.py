import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
EMAIL_VERIFICATION_PURPOSE = "verify_email"
PASSWORD_RESET_PURPOSE = "password_reset"
REFRESH_PURPOSE = "refresh"


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage. Never store the raw password."""
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password attempt against a stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# A real bcrypt hash of a random value, checked when the account does not exist
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode()


def dummy_password_check(password: str) -> None:
    """Spend the same time as verify_password for an unknown account."""
    verify_password(password, _DUMMY_HASH)


def generate_qr_token() -> str:
    """Opaque random token encoded in a ticket's QR code. Looked up server-side."""
    return secrets.token_urlsafe(32)


def fingerprint(value: str) -> str:
    """Short, non-reversible digest used to bind a token to a stored value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _encode(payload: dict[str, Any], expires_in: timedelta) -> str:
    payload = {**payload, "exp": datetime.now(UTC) + expires_in}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None


def create_access_token(subject: str, token_version: int = 0) -> str:
    """Create a sign-in JWT for a user id.

    ``token_version`` is copied from the user row. Bumping it on the user
    (sign-out, password change) invalidates every token issued before.
    """
    return _encode(
        {"sub": subject, "typ": ACCESS_TOKEN_TYPE, "ver": token_version},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def decode_access_payload(token: str) -> dict[str, Any] | None:
    """Return the payload of a valid access token, or None."""
    payload = _decode(token)
    if payload is None or payload.get("typ", ACCESS_TOKEN_TYPE) != ACCESS_TOKEN_TYPE:
        return None
    if not isinstance(payload.get("sub"), str):
        return None
    return payload


def decode_access_token(token: str) -> str | None:
    """Return the subject (user id) from a valid token, or None if invalid/expired."""
    payload = decode_access_payload(token)
    return payload["sub"] if payload else None


def create_purpose_token(
    subject: str, purpose: str, expires_in: timedelta, binding: str
) -> str:
    """Create a single-purpose token (email verification, password reset).

    ``binding`` is fingerprinted into the token; the token stops working as
    soon as the bound value changes (e.g. the password hash after a reset).
    """
    return _encode(
        {
            "sub": subject,
            "typ": purpose,
            "bnd": fingerprint(binding),
            # Unique per token, so signing out one session never matches another
            "jti": secrets.token_urlsafe(12),
        },
        expires_in,
    )


def token_digest(token: str) -> str:
    """SHA-256 of a whole token, for storing revoked tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_purpose_token(token: str, purpose: str) -> tuple[str, str] | None:
    """Return ``(subject, binding_fingerprint)`` for a valid token, or None."""
    payload = _decode(token)
    if payload is None or payload.get("typ") != purpose:
        return None
    subject, binding = payload.get("sub"), payload.get("bnd")
    if not isinstance(subject, str) or not isinstance(binding, str):
        return None
    return subject, binding


# --- Ticket QR payloads -------------------------------------------------------
# Admission QR codes carry "BFT1.<opaque id>.<signature>". The signature lets
# the scanner reject forged or altered codes before touching the database;
# the opaque id is then looked up server-side (never the ticket's own id).
# Campaign QR codes are https links and can never match this format.
TICKET_QR_PREFIX = "BFT1"


def _ticket_signature(qr_secret: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), f"ticket:{qr_secret}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:22]


def make_ticket_qr_payload(qr_secret: str) -> str:
    return f"{TICKET_QR_PREFIX}.{qr_secret}.{_ticket_signature(qr_secret)}"


def parse_ticket_qr_payload(payload: str) -> str | None:
    """The ticket's opaque id if the payload is a genuine admission code."""
    parts = payload.strip().split(".")
    if len(parts) != 3 or parts[0] != TICKET_QR_PREFIX or not parts[1]:
        return None
    if not hmac.compare_digest(parts[2], _ticket_signature(parts[1])):
        return None
    return parts[1]
