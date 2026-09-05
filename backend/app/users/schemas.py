import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.roles.models import RoleName


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool


class RoleAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    role: RoleName
    # Required for every role except super_admin (validated in the endpoint,
    # not here, since a Pydantic-level conditional-required field is messier
    # than a one-line check against the parsed enum value).
    department_id: Optional[uuid.UUID] = None


class RoleAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    department_id: Optional[uuid.UUID]
