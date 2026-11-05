from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readiness(db: DbSession) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable") from None
    return {"status": "ready"}
