"""FastAPI dependencies: authentication (Firebase) and authorization (PostgreSQL RBAC)."""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import (
    FirebaseTokenVerifier,
    InvalidTokenError,
    PubSubPushVerifier,
    TokenVerifier,
)
from app.db.session import get_db
from app.services.locations import LocationPublisher, LocationService, PubSubLocationPublisher
from app.services.rbac import Principal, RbacService

_bearer = HTTPBearer(auto_error=False, description="Firebase ID token")

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


# --- singletons (overridable in tests through app.dependency_overrides) ----------------
@lru_cache
def _firebase_verifier() -> FirebaseTokenVerifier:
    return FirebaseTokenVerifier(get_settings())


def get_token_verifier() -> TokenVerifier:
    return _firebase_verifier()


@lru_cache
def _pubsub_verifier() -> PubSubPushVerifier:
    return PubSubPushVerifier(get_settings())


def get_pubsub_verifier() -> PubSubPushVerifier:
    return _pubsub_verifier()


@lru_cache
def _publisher() -> PubSubLocationPublisher:
    return PubSubLocationPublisher(get_settings())


def get_location_publisher(settings: AppSettings) -> LocationPublisher | None:
    return _publisher() if settings.locations_topic else None


# --- services -----------------------------------------------------------------------------
def get_rbac_service(db: DbSession, settings: AppSettings) -> RbacService:
    return RbacService(db, default_role=settings.default_role)


def get_location_service(
    db: DbSession,
    settings: AppSettings,
    publisher: Annotated[LocationPublisher | None, Depends(get_location_publisher)],
) -> LocationService:
    return LocationService(db, settings, publisher)


# --- authentication + authorization -------------------------------------------------------
def _unauthorized(detail: str = "invalid or missing token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
) -> Principal:
    """Verify the Firebase JWT, then load roles and permissions from PostgreSQL."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        identity = verifier.verify(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized() from None
    user, principal = rbac.resolve_principal(identity)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account disabled")
    request.state.user_id = str(principal.user_id)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_permissions(*codes: str) -> Callable[[Principal], Principal]:
    """Dependency factory: the caller must hold *all* the given permissions.

    Usage::

        @router.post("/x", dependencies=[Depends(require_permissions(Perm.LOCATION_WRITE))])
        def handler(...): ...

        def handler(principal: Annotated[Principal, Depends(require_permissions("a:b"))]): ...
    """
    required = frozenset(codes)

    def checker(principal: CurrentPrincipal) -> Principal:
        if not principal.has_all(*required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return principal

    checker.__name__ = f"require_{'_'.join(sorted(required)) or 'auth'}".replace(":", "_")
    return checker
