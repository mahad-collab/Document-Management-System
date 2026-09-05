"""
User management endpoints.

Section 7: Super Admin manages users org-wide; a Department Admin manages
users only within their own department (e.g. "Finance Department Admin can
manage Finance users" — cannot touch HR). Section 8 applies here just as
much as to documents: a Department Admin must not be able to grant a role
in a department they don't administer, even if they guess a valid
department_id.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.roles.models import Role, RoleName
from app.roles.user_role import UserRole
from app.users.models import User
from app.users.schemas import RoleAssignmentCreate, RoleAssignmentOut, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    department_id: uuid.UUID | None = Query(None, description="Required unless the caller is Super Admin"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.is_super_admin:
        if department_id is None:
            result = await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.email))
            return result.scalars().all()
        stmt = select(User).join(UserRole).where(UserRole.department_id == department_id, User.deleted_at.is_(None))
        return (await db.execute(stmt.distinct())).scalars().all()

    if department_id is None or not user_has_department_permission(current_user, department_id, "user:manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(User)
        .join(UserRole)
        .where(UserRole.department_id == department_id, User.deleted_at.is_(None))
        .distinct()
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/role-assignments", response_model=RoleAssignmentOut, status_code=status.HTTP_201_CREATED)
async def assign_role(
    payload: RoleAssignmentCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # --- Authorization: who is allowed to make THIS specific assignment ---
    if payload.role == RoleName.SUPER_ADMIN:
        if not current_user.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Super Admin can grant Super Admin")
        if payload.department_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin is org-wide; department_id must be omitted")
    else:
        if payload.department_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="department_id is required for this role")
        if not current_user.is_super_admin and not user_has_department_permission(
            current_user, payload.department_id, "user:manage"
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    target_user = await db.get(User, payload.user_id)
    if target_user is None or target_user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role_row = (await db.execute(select(Role).where(Role.name == payload.role))).scalar_one_or_none()
    if role_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Role catalog not seeded")

    assignment = UserRole(user_id=target_user.id, role_id=role_row.id, department_id=payload.department_id)
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    await log_audit(
        action=AuditAction.ROLE_CHANGE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=payload.department_id,
        details=f"Granted {payload.role.value} to user {target_user.email}",
    )
    return assignment
