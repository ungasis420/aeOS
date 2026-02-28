"""aeOS Core — auth.py
API key helpers + lightweight in-memory session management.
This module is intentionally dependency-free (stdlib-only) so it can run
very early in the stack (e.g., imported by FastAPI middleware) without
pulling in DB or third-party libraries.
Security notes:
- API keys are generated with `secrets.token_urlsafe(32)`.
- API keys are stored/compared by SHA-256 hash (hex). In production you
  would typically prefer a slow hash (bcrypt/argon2) + per-key salt, but
  aeOS Phase 3 constraints keep this stdlib-only.
- Session tokens are stored in-memory only. Restarting the process
  invalidates all sessions. Multiple workers will not share sessions.
"""
import datetime
import hashlib
import secrets
import uuid

# -----------------------------
# Module configuration
# -----------------------------

# Fixed session TTL: 24 hours from creation.
_SESSION_TTL_HOURS = 24

# In-memory session store:
#   token -> {
#       "user_id": str,
#       "created_at": datetime,
#       "expires_at": datetime,
#       "revoked": bool,
#   }
_SESSIONS = {}


# -----------------------------
# API key helpers
# -----------------------------

def generate_api_key() -> str:
    """Generate a new API key.

    Returns:
        str: A URL-safe API key suitable for use in headers.

    Implementation detail:
        Uses `secrets.token_urlsafe(32)` as required.
    """
    return secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """Hash an API key using SHA-256.

    Args:
        key (str): Raw API key.

    Returns:
        str: SHA-256 hex digest of the API key.

    Raises:
        TypeError: If key is not a string.
    """
    if not isinstance(key, str):
        raise TypeError("key must be a str")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def validate_api_key(key: str, stored_hash: str) -> bool:
    """Validate a raw API key against a stored SHA-256 hash.

    Args:
        key (str): Raw API key presented by the caller.
        stored_hash (str): Previously stored SHA-256 hex digest.

    Returns:
        bool: True if the key hashes to the stored hash; else False.
    """
    if not isinstance(key, str) or not isinstance(stored_hash, str):
        return False
    try:
        computed = hash_key(key)
    except TypeError:
        return False
    # Timing-safe compare to reduce side-channel leakage.
    return secrets.compare_digest(computed, stored_hash)


# -----------------------------
# Session management (in-memory)
# -----------------------------

def _utcnow() -> datetime.datetime:
    """Return current UTC time as an aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def _to_iso(dt: datetime.datetime) -> str:
    """Convert an aware datetime to ISO 8601 string."""
    # Use ISO 8601 with timezone offset; stable for logs and JSON.
    return dt.isoformat()


def _cleanup_expired_sessions(now=None) -> None:
    """Remove expired and revoked sessions from the in-memory store.

    This keeps memory bounded for long-running processes.

    Args:
        now: Optional injected current time (UTC, timezone-aware). If
            omitted, uses current time.
    """
    now = now or _utcnow()
    # Iterate over a copy of keys so we can delete safely.
    for token in list(_SESSIONS.keys()):
        sess = _SESSIONS.get(token)
        if not sess:
            continue
        # Drop revoked sessions immediately.
        if sess.get("revoked") is True:
            _SESSIONS.pop(token, None)
            continue
        expires_at = sess.get("expires_at")
        if isinstance(expires_at, datetime.datetime) and now >= expires_at:
            _SESSIONS.pop(token, None)


def create_session(user_id: str) -> dict:
    """Create a new session for a user.

    Args:
        user_id (str): Stable identifier for the user/client.

    Returns:
        dict: Session payload with:
            - session_token (str)
            - created_at (str, ISO 8601 UTC)
            - expires_at (str, ISO 8601 UTC)

    Notes:
        Sessions are stored in-memory only (no DB). They expire after
        exactly 24 hours as required.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")

    now = _utcnow()
    expires_at = now + datetime.timedelta(hours=_SESSION_TTL_HOURS)

    # UUID4 is already cryptographically strong, but we add extra entropy
    # and URL-safety for nicer header transport.
    session_token = f"{uuid.uuid4().hex}.{secrets.token_urlsafe(16)}"

    _SESSIONS[session_token] = {
        "user_id": user_id,
        "created_at": now,
        "expires_at": expires_at,
        "revoked": False,
    }

    return {
        "session_token": session_token,
        "created_at": _to_iso(now),
        "expires_at": _to_iso(expires_at),
    }


def validate_session(token: str) -> bool:
    """Validate a session token.

    A token is valid if it exists, is not revoked, and has not expired.

    Args:
        token (str): Session token.

    Returns:
        bool: True if valid; else False.
    """
    if not isinstance(token, str) or not token:
        return False

    now = _utcnow()
    _cleanup_expired_sessions(now=now)

    sess = _SESSIONS.get(token)
    if not sess:
        return False
    if sess.get("revoked") is True:
        return False

    expires_at = sess.get("expires_at")
    if not isinstance(expires_at, datetime.datetime):
        # Corrupt entry; treat as invalid and drop it.
        _SESSIONS.pop(token, None)
        return False
    if now >= expires_at:
        _SESSIONS.pop(token, None)
        return False
    return True


def revoke_session(token: str) -> bool:
    """Revoke (invalidate) an existing session token.

    Args:
        token (str): Session token.

    Returns:
        bool: True if a session existed and was revoked; else False.
    """
    if not isinstance(token, str) or not token:
        return False

    now = _utcnow()
    _cleanup_expired_sessions(now=now)

    sess = _SESSIONS.get(token)
    if not sess:
        return False

    # Mark revoked and remove from store to prevent any future validation.
    sess["revoked"] = True
    _SESSIONS.pop(token, None)
    return True
