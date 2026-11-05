"""Dynamic RBAC management: roles, permissions and assignments change without redeploying."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_rbac_service, require_permissions
from app.core.permissions import Perm
from app.schemas.rbac import PermissionCreate, PermissionOut, RoleCreate, RoleOut, UserOut, UserUpdate
from app.services.rbac import Principal, RbacService

router = APIRouter(prefix="/v1/admin", tags=["admin"])

Rbac = Annotated[RbacService, Depends(get_rbac_service)]
RbacAdmin = Annotated[Principal, Depends(require_permissions(Perm.RBAC_MANAGE))]
UsersReader = Annotated[Principal, Depends(require_permissions(Perm.USERS_READ))]


# --- permissions -------------------------------------------------------------------------
@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(_: RbacAdmin, rbac: Rbac) -> list[PermissionOut]:
    return [PermissionOut.model_validate(p) for p in rbac.list_permissions()]


@router.post("/permissions", response_model=PermissionOut, status_code=status.HTTP_201_CREATED)
def create_permission(body: PermissionCreate, actor: RbacAdmin, rbac: Rbac) -> PermissionOut:
    return PermissionOut.model_validate(rbac.create_permission(actor, body.code, body.description))


# --- roles -------------------------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleOut])
def list_roles(_: RbacAdmin, rbac: Rbac) -> list[RoleOut]:
    return [RoleOut.model_validate(r) for r in rbac.list_roles()]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(body: RoleCreate, actor: RbacAdmin, rbac: Rbac) -> RoleOut:
    return RoleOut.model_validate(rbac.create_role(actor, body.name, body.description, body.permissions))


@router.delete("/roles/{role_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_name: str, actor: RbacAdmin, rbac: Rbac) -> Response:
    rbac.delete_role(actor, role_name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/roles/{role_name}/permissions/{code}", response_model=RoleOut)
def grant_permission(role_name: str, code: str, actor: RbacAdmin, rbac: Rbac) -> RoleOut:
    return RoleOut.model_validate(rbac.grant_permission(actor, role_name, code))


@router.delete("/roles/{role_name}/permissions/{code}", response_model=RoleOut)
def revoke_permission(role_name: str, code: str, actor: RbacAdmin, rbac: Rbac) -> RoleOut:
    return RoleOut.model_validate(rbac.revoke_permission(actor, role_name, code))


# --- users ---------------------------------------------------------------------------------------
@router.get("/users", response_model=list[UserOut])
def list_users(
    _: UsersReader,
    rbac: Rbac,
    firebase_uid: str | None = None,
    limit: Annotated[int, Query(gt=0, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in rbac.list_users(limit, offset, firebase_uid)]


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, _: UsersReader, rbac: Rbac) -> UserOut:
    return UserOut.model_validate(rbac.get_user(user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, actor: RbacAdmin, rbac: Rbac) -> UserOut:
    return UserOut.model_validate(rbac.update_user(actor, user_id, body.is_active, body.display_name))


@router.put("/users/{user_id}/roles/{role_name}", response_model=UserOut)
def assign_role(user_id: uuid.UUID, role_name: str, actor: RbacAdmin, rbac: Rbac) -> UserOut:
    return UserOut.model_validate(rbac.assign_role(actor, user_id, role_name))


@router.delete("/users/{user_id}/roles/{role_name}", response_model=UserOut)
def revoke_role(user_id: uuid.UUID, role_name: str, actor: RbacAdmin, rbac: Rbac) -> UserOut:
    return UserOut.model_validate(rbac.revoke_role(actor, user_id, role_name))
