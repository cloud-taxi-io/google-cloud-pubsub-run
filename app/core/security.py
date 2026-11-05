"""Token verification.

* Firebase ID tokens (end users): authentication only. No custom claims are read
  for authorization; roles and permissions come from PostgreSQL.
* Google OIDC tokens (Pub/Sub push subscription calling this service).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import firebase_admin
from firebase_admin import auth as firebase_auth
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import Settings

logger = logging.getLogger(__name__)


class InvalidTokenError(Exception):
    """The token is missing, malformed, expired, revoked or not for us."""


@dataclass(frozen=True, slots=True)
class FirebaseIdentity:
    uid: str
    email: str | None
    email_verified: bool
    phone_number: str | None
    name: str | None
    sign_in_provider: str | None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> FirebaseIdentity: ...


class FirebaseTokenVerifier:
    """Verifies Firebase ID tokens with the Firebase Admin SDK."""

    def __init__(self, settings: Settings) -> None:
        self._check_revoked = settings.firebase_check_revoked
        options = {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
        try:
            self._app = firebase_admin.get_app()
        except ValueError:
            # Application Default Credentials: the Cloud Run service account.
            self._app = firebase_admin.initialize_app(options=options)

    def verify(self, token: str) -> FirebaseIdentity:
        try:
            claims = firebase_auth.verify_id_token(token, app=self._app, check_revoked=self._check_revoked)
        except (
            firebase_auth.InvalidIdTokenError,
            firebase_auth.ExpiredIdTokenError,
            firebase_auth.RevokedIdTokenError,
            firebase_auth.UserDisabledError,
            ValueError,
        ) as exc:
            raise InvalidTokenError(type(exc).__name__) from exc
        firebase_info = claims.get("firebase") or {}
        return FirebaseIdentity(
            uid=claims["uid"],
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            phone_number=claims.get("phone_number"),
            name=claims.get("name"),
            sign_in_provider=firebase_info.get("sign_in_provider"),
        )


class PubSubPushVerifier:
    """Verifies the OIDC token that a Pub/Sub push subscription attaches to each request."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.pubsub_verify_oidc
        self._audience = settings.pubsub_audience
        self._service_account = settings.pubsub_service_account
        if self._enabled and not (self._audience and self._service_account):
            raise RuntimeError(
                "PUBSUB_AUDIENCE and PUBSUB_SERVICE_ACCOUNT are required when PUBSUB_VERIFY_OIDC is true"
            )
        self._request = google_requests.Request()  # type: ignore[no-untyped-call]

    def verify(self, authorization_header: str | None) -> None:
        if not self._enabled:
            return
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise InvalidTokenError("missing bearer token")
        token = authorization_header.removeprefix("Bearer ")
        try:
            claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                token, self._request, audience=self._audience
            )
        except ValueError as exc:
            raise InvalidTokenError("invalid OIDC token") from exc
        if claims.get("email") != self._service_account or not claims.get("email_verified"):
            raise InvalidTokenError("unexpected service account")
