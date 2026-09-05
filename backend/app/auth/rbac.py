"""
Server-side RBAC enforcement.

Spec Section 8 is unambiguous: "Never rely only on hiding HR from the
Finance user's sidebar. The API must enforce the restriction." Every one of
these dependencies runs on the backend, independent of anything the
frontend does.

Usage in an endpoint:

    @router.get("/documents/{document_id}")
    async def get_document(
        document_id: UUID,
        current_user: CurrentUser = Depends(require_department_access("document:view")),
    ):
        ...

`require_department_access` resolves the document's department from the
path/query/body (via a resolver you provide) and checks the current user
actually holds a role — with the needed permission — in that department,
OR holds org-wide Super Admin.
"""
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.roles.models import Permission, Role, RoleName
from app.roles.user_role import UserRole
from app.users.models import User


@dataclass
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str
    is_super_admin: bool
    # department_id -> set of permission codes the user holds in that department
    department_permissions: dict


async def _load_current_user(request: Request, db: AsyncSession) -> CurrentUser:
    """
    Resolves the authenticated user from the session (set during the Entra ID
    OAuth callback — see app/auth/routes.py) and eagerly loads every role
    assignment with its permissions, so a single DB round-trip covers all
    authorization checks for the request.
    """
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    stmt = (
        select(User)
        .where(User.id == uuid.UUID(user_id), User.deleted_at.is_(None), User.is_active.is_(True))
        .options(
            selectinload(User.user_roles).selectinload(UserRole.role).selectinload(Role.permissions),
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    is_super_admin = False
    department_permissions: dict = {}

    for ur in user.user_roles:
        perm_codes = {p.code for p in ur.role.permissions}
        if ur.role.name == RoleName.SUPER_ADMIN:
            is_super_admin = True
            continue
        dept_key = ur.department_id
        department_permissions.setdefault(dept_key, set()).update(perm_codes)

    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_super_admin=is_super_admin,
        department_permissions=department_permissions,
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> CurrentUser:
    return await _load_current_user(request, db)


def require_permission(permission_code: str) -> Callable:
    """
    Org-wide permission check — use for endpoints that aren't department-
    scoped (e.g. creating a department, managing global system settings).
    Only Super Admin passes unless the permission is explicitly granted
    org-wide (rare; most non-super roles are department-scoped by design).
    """
    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.is_super_admin:
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return _dependency


def require_department_access(permission_code: str, department_id_param: str = "department_id") -> Callable:
    """
    Department-scoped permission check.

    `department_id_param` names the path/query parameter FastAPI should read
    the target department_id from. For document/folder endpoints where the
    department must be looked up from the resource itself (not the URL),
    resolve the department first in the endpoint body and call
    `user_has_department_permission()` directly instead of this dependency.
    """
    async def _dependency(
        request: Request,
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.is_super_admin:
            return current_user

        department_id_raw = request.path_params.get(department_id_param) or request.query_params.get(
            department_id_param
        )
        if not department_id_raw:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="department_id is required")

        department_id = uuid.UUID(department_id_raw)
        if not user_has_department_permission(current_user, department_id, permission_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        return current_user

    return _dependency


def user_has_department_permission(
    current_user: CurrentUser, department_id: Optional[uuid.UUID], permission_code: str
) -> bool:
    """
    The single source of truth for "can this user do X in this department".
    Called directly from services/endpoints when the department can't be
    read straight off the URL (e.g. resolved from a document row first).
    """
    if current_user.is_super_admin:
        return True
    perms = current_user.department_permissions.get(department_id)
    return bool(perms and permission_code in perms)
