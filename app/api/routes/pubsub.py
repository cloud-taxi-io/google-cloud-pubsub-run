"""Pub/Sub push endpoint: writes queued driver locations to the database.

Response codes drive Pub/Sub: 2xx = ack, anything else = retry with backoff.
Poison messages (invalid payload, unknown driver) are acked and logged, so they do not
block the subscription; transient errors (database down) return 500 and are retried.
"""
import base64
import binascii
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_location_service, get_pubsub_verifier
from app.core.security import InvalidTokenError, PubSubPushVerifier
from app.schemas.location import DriverLocationMessage
from app.services.locations import MESSAGE_TYPE, LocationService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pubsub"], include_in_schema=False)


class PubSubMessage(BaseModel):
    data: str | None = None
    attributes: dict[str, str] = {}
    messageId: str | None = None  # noqa: N815 - Pub/Sub field name


class PushEnvelope(BaseModel):
    message: PubSubMessage
    subscription: str | None = None


def _ack() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pubsub/push")
@router.post("/")  # backward compatible with the existing subscription endpoint
def pubsub_push(
    envelope: PushEnvelope,
    verifier: Annotated[PubSubPushVerifier, Depends(get_pubsub_verifier)],
    service: Annotated[LocationService, Depends(get_location_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    try:
        verifier.verify(authorization)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid push token") from None

    msg = envelope.message
    log: dict[str, Any] = {"message_id": msg.messageId, "type": msg.attributes.get("type")}

    if msg.attributes.get("type") != MESSAGE_TYPE:
        logger.info("ignored pub/sub message", extra=log)
        return _ack()

    try:
        raw = base64.b64decode(msg.data or "", validate=True)
        payload = DriverLocationMessage.model_validate_json(raw)
    except (binascii.Error, ValueError, ValidationError) as exc:
        logger.warning("dropped invalid location message", extra={**log, "error": str(exc)[:500]})
        return _ack()

    try:
        inserted = service.store(payload.driver_id, payload.points)
    except IntegrityError:
        service.db.rollback()
        logger.warning("dropped location message for unknown driver", extra={**log, "driver_id": str(payload.driver_id)})
        return _ack()

    logger.info(
        "locations stored",
        extra={**log, "driver_id": str(payload.driver_id), "points": len(payload.points), "inserted": inserted},
    )
    return _ack()
