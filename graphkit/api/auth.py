"""Firebase ID token verification for the chat endpoints. Nothing else in this app requires sign-in."""
from __future__ import annotations

from fastapi import Header, HTTPException

_initialized = False


def _ensure_initialized():
    global _initialized
    if _initialized:
        return
    import firebase_admin
    from firebase_admin import credentials
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.ApplicationDefault())
    _initialized = True


def require_user(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required: missing bearer token.")
    _ensure_initialized()
    from firebase_admin import auth
    token = authorization.removeprefix("Bearer ").strip()
    try:
        decoded = auth.verify_id_token(token)
    except Exception as e:  # noqa: BLE001 - any verification failure means "not signed in"
        raise HTTPException(401, f"Sign in required: {e}") from e
    return decoded["uid"]
