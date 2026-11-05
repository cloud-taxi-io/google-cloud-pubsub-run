"""Driver GPS endpoints."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_location_service, require_permissions
from app.core.permissions import Perm
from app.schemas.location import LocationAccepted, LocationBatch, LocationOut, NearbyDriver
from app.services.locations import LocationService
from app.services.rbac import Principal

router = APIRouter(prefix="/v1/drivers", tags=["locations"])

LocationSvc = Annotated[LocationService, Depends(get_location_service)]


@router.post("/me/locations", response_model=LocationAccepted, status_code=status.HTTP_202_ACCEPTED)
def send_my_locations(
    batch: LocationBatch,
    principal: Annotated[Principal, Depends(require_permissions(Perm.LOCATION_WRITE))],
    service: LocationSvc,
) -> LocationAccepted:
    """A driver sends its GPS positions. The driver id always comes from the verified token."""
    mode = service.ingest(principal.user_id, batch.points)
    return LocationAccepted(accepted=len(batch.points), mode=mode)


@router.get(
    "/nearby",
    response_model=list[NearbyDriver],
    dependencies=[Depends(require_permissions(Perm.LOCATION_READ_NEARBY))],
)
def nearby_drivers(
    service: LocationSvc,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[int, Query(gt=0, le=50_000)] = 3000,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
) -> list[NearbyDriver]:
    """Drivers seen recently around a point, closest first."""
    return service.nearby(lat, lon, radius_m, limit)


@router.get(
    "/{driver_id}/locations",
    response_model=list[LocationOut],
    dependencies=[Depends(require_permissions(Perm.LOCATION_READ))],
)
def driver_history(
    driver_id: uuid.UUID,
    service: LocationSvc,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(gt=0, le=5000)] = 500,
) -> list[LocationOut]:
    """Position history of one driver (newest first)."""
    until = until or datetime.now(UTC)
    since = since or until - timedelta(hours=1)
    if since >= until:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="since must be before until")
    if until - since > timedelta(days=7):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="range is limited to 7 days")
    return service.history(driver_id, since, until, limit)
