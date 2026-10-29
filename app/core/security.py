import secrets

import bcrypt


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage. Never store the raw password."""
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password attempt against a stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_qr_token() -> str:
    """Opaque random token encoded in a ticket's QR code. Looked up server-side."""
    return secrets.token_urlsafe(32)
