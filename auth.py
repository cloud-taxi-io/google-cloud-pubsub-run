"""Firebase / Identity Platform helpers: ID token verification and role management."""
import functools

import firebase_admin
from firebase_admin import auth as fb_auth
from flask import g, jsonify, request

import roles

_app = None


def _ensure_app():
    # Uses Application Default Credentials (the Cloud Run service account).
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app()


def verify_request_token():
    """Return the decoded ID token from `Authorization: Bearer <token>`, or None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    _ensure_app()
    try:
        return fb_auth.verify_id_token(header[len("Bearer "):], check_revoked=True)
    except Exception:  # invalid, expired or revoked token
        return None


def require_role(*allowed):
    """Decorator: 401 without a valid token, 403 if the role is not allowed."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            token = verify_request_token()
            if token is None:
                return jsonify(error="unauthorized"), 401
            # A user without a role claim is treated as the default role.
            role = token.get(roles.CLAIM_NAME, roles.DEFAULT_ROLE)
            if allowed and role not in allowed:
                return jsonify(error="forbidden", role=role), 403
            g.token = token
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def set_user_role(uid, role):
    """Set the role claim, keeping the user's other custom claims. Takes effect at the next token refresh."""
    if not roles.is_valid_role(role):
        raise ValueError(f"invalid role: {role!r}")
    _ensure_app()
    user = fb_auth.get_user(uid)
    claims = dict(user.custom_claims or {})
    claims[roles.CLAIM_NAME] = role
    fb_auth.set_custom_user_claims(uid, claims)
    # Force clients to sign in again so old tokens (with the old role) stop working.
    fb_auth.revoke_refresh_tokens(uid)
    return claims
