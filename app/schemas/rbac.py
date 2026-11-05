from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

ROLE_NAME_PATTERN = r"^[a-z][a-z0-9-]{1,63}$"
PERMISSION_CODE_PATTERN = r"^[a-z][a-z0-9_-]*(:[a-z][a-z0-9_-]*){1,3}$"


class PermissionCreate(BaseModel):
    code: str = Field(pattern=PERMISSION_CODE_PATTERN, max_length=100, examples=["ride:create"])
    description: str | None = Field(default=None, max_length=500)


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str | None


class RoleCreate(BaseModel):
    name: str = Field(pattern=ROLE_NAME_PATTERN, examples=["chauffeur-vtc"])
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=100)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    is_system: bool
    permissions: list[PermissionOut]


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    firebase_uid: str
    email: str | None
    phone_number: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime
    roles: list[RoleSummary]


class UserUpdate(BaseModel):
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)


class MeOut(BaseModel):
    id: uuid.UUID
    firebase_uid: str
    email: str | None
    phone_number: str | None
    display_name: str | None
    roles: list[str]
    permissions: list[str]
