import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# A permissive "looks like an email" check rather than pydantic's EmailStr:
# EmailStr (via the email-validator package) rejects the entire .test/
# .example/.invalid/.localhost TLD family as "special-use or reserved"
# per RFC 2606 — which is exactly the convention this project's own local
# test/demo accounts use (e.g. finance.admin@pumapakistan.test). Real Entra
# ID logins always go through /auth/callback, not this schema, so there's
# no correctness reason to be stricter than "has an @ and a domain".
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

from app.roles.models import RoleName


class UserRoleDetail(BaseModel):
    """One role assignment, with the department name resolved for display —
    avoids a round trip to /departments just to label a row in the UI."""

    id: uuid.UUID
    role: RoleName
    department_id: Optional[uuid.UUID]
    department_name: Optional[str]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    job_title: Optional[str]
    is_active: bool
    # Populated by the endpoint (not a plain ORM attribute — see
    # app/users/routes.py's _attach_roles), defaults to empty so
    # constructing a UserOut right after create/update doesn't require it.
    roles: list[UserRoleDetail] = []


class UserCreate(BaseModel):
    """Pre-provisions a user record before their first Entra ID login (Super
    Admin only — see create_user). entra_object_id is intentionally not
    settable here: it's only ever populated by the real OAuth callback, so
    an admin can never impersonate someone else's Entra identity."""

    email: str = Field(..., max_length=320, pattern=_EMAIL_PATTERN)
    display_name: str = Field(..., min_length=1, max_length=200)
    job_title: Optional[str] = Field(None, max_length=200)


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    job_title: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


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
