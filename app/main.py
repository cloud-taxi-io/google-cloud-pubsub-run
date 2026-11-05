"""FastAPI application: VTC API with Firebase authentication and PostgreSQL RBAC."""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes import admin, health, locations, me, pubsub
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.errors import ConflictError, DomainError, ForbiddenOperationError, NotFoundError

_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ForbiddenOperationError: status.HTTP_403_FORBIDDEN,
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )

    @application.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        code = _STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    for router in (health.router, me.router, locations.router, admin.router, pubsub.router):
        application.include_router(router)
    return application


app = create_app()
