from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_rbac_service, require_permissions
from app.core.permissions import Perm
from app.schemas.rbac import MeOut
from app.services.rbac import Principal, RbacService

router = APIRouter(prefix="/v1", tags=["me"])


@router.get("/me", response_model=MeOut)
def read_me(
    principal: Annotated[Principal, Depends(require_permissions(Perm.PROFILE_READ))],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
) -> MeOut:
    user = rbac.get_user(principal.user_id)
    return MeOut(
        id=user.id,
        firebase_uid=user.firebase_uid,
        email=user.email,
        phone_number=user.phone_number,
        display_name=user.display_name,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
    )
