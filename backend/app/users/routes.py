"""
User management endpoints.

Section 7: Super Admin manages users org-wide; a Department Admin manages
users only within their own department (e.g. "Finance Department Admin can
manage Finance users" — cannot touch HR). Section 8 applies here just as
much as to documents: a Department Admin must not be able to grant a role
in a department they don't administer, even if they guess a valid
department_id.

Account lifecycle (create/edit/delete) is Super Admin only — provisioning
or removing an org-wide identity is a different kind of action than
assigning a role within a department, so it uses `require_permission`
(effectively Super-Admin-only, see app/auth/rbac.py) rather than the
department-scoped check used for role assignment.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user, require_permission, user_has_department_permission
from app.core.database import get_db
from app.departments.models import Department
from app.roles.models import Role, RoleName
from app.roles.user_role import UserRole
from app.users.models import User
from app.users.schemas import (
    RoleAssignmentCreate,
    RoleAssignmentOut,
    UserCreate,
    UserOut,
    UserRoleDetail,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


async def _roles_for_users(
    db: AsyncSession, user_ids: list[uuid.UUID], department_filter: uuid.UUID | None
) -> dict[uuid.UUID, list[UserRoleDetail]]:
    """Loads role assignments for a batch of users in one query.

    When `department_filter` is set (a department-scoped listing), only
    that department's assignments are returned — a Department Admin
    browsing Finance shouldn't learn that a user also holds a role in HR
    (Section 8's isolation principle applies to *metadata about users*
    too, not just documents). `None` means "no filter" (Super Admin's
    org-wide view), which returns every role the user holds anywhere.
    """
    if not user_ids:
        return {}

    stmt = (
        select(UserRole.id, UserRole.user_id, UserRole.department_id, Role.name, Department.name)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(Department, Department.id == UserRole.department_id)
        .where(UserRole.user_id.in_(user_ids))
    )
    if department_filter is not None:
        stmt = stmt.where(UserRole.department_id == department_filter)

    rows = (await db.execute(stmt)).all()
    roles_by_user: dict[uuid.UUID, list[UserRoleDetail]] = {}
    for assignment_id, user_id, dept_id, role_name, dept_name in rows:
        roles_by_user.setdefault(user_id, []).append(
            UserRoleDetail(id=assignment_id, role=role_name, department_id=dept_id, department_name=dept_name)
        )
    return roles_by_user


def _to_user_out(user: User, roles: list[UserRoleDetail]) -> UserOut:
    out = UserOut.model_validate(user)
    out.roles = roles
    return out


async def _user_holds_super_admin(db: AsyncSession, user_id: uuid.UUID) -> bool:
    stmt = (
        select(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.name == RoleName.SUPER_ADMIN)
    )
    return (await db.execute(stmt)).first() is not None


async def _remaining_super_admin_count(db: AsyncSession, exclude_user_id: uuid.UUID) -> int:
    """How many OTHER active super admins exist — the safety check before
    deleting a user or revoking a super_admin assignment. A soft-deleted or
    deactivated super admin doesn't count as "remaining" since they can't
    actually act."""
    stmt = (
        select(func.count(func.distinct(UserRole.user_id)))
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            Role.name == RoleName.SUPER_ADMIN,
            User.id != exclude_user_id,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
    )
    return (await db.execute(stmt)).scalar_one()


@router.get("", response_model=list[UserOut])
async def list_users(
    department_id: uuid.UUID | None = Query(None, description="Required unless the caller is Super Admin"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.is_super_admin:
        if department_id is None:
            result = await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.email))
            users = result.scalars().all()
            roles_map = await _roles_for_users(db, [u.id for u in users], None)
            return [_to_user_out(u, roles_map.get(u.id, [])) for u in users]
        stmt = select(User).join(UserRole).where(UserRole.department_id == department_id, User.deleted_at.is_(None))
        users = (await db.execute(stmt.distinct())).scalars().all()
        roles_map = await _roles_for_users(db, [u.id for u in users], department_id)
        return [_to_user_out(u, roles_map.get(u.id, [])) for u in users]

    if department_id is None or not user_has_department_permission(current_user, department_id, "user:manage"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(User)
        .join(UserRole)
        .where(UserRole.department_id == department_id, User.deleted_at.is_(None))
        .distinct()
    )
    users = (await db.execute(stmt)).scalars().all()
    roles_map = await _roles_for_users(db, [u.id for u in users], department_id)
    return [_to_user_out(u, roles_map.get(u.id, [])) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Pre-provisions a user record before their first Entra ID login, so a
    Super Admin can create an account and grant roles ahead of time. The
    real Entra object ID is left NULL and gets backfilled automatically the
    first time this person actually signs in via /auth/callback (matched
    by email) — they never need a password here, consistent with Entra ID
    remaining the sole identity source of truth.

    The email column is uniquely constrained regardless of soft-delete
    state, so a previously-deleted account's email would otherwise be
    permanently unusable. Recreating with that same email instead
    resurrects the old row: deleted_at/is_active reset, display name/title
    refreshed from this request, and its old role assignments cleared —
    a resurrected account starts with zero roles for the same reason a
    genuine first-ever login does (Section 7): access is only ever
    re-granted by a deliberate admin action, never implicitly restored.
    """
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    resurrected = existing is not None
    if resurrected:
        stale_roles = (await db.execute(select(UserRole).where(UserRole.user_id == existing.id))).scalars().all()
        for stale_role in stale_roles:
            await db.delete(stale_role)
        existing.deleted_at = None
        existing.is_active = True
        existing.display_name = payload.display_name
        existing.job_title = payload.job_title
        user = existing
    else:
        user = User(
            entra_object_id=None,
            email=payload.email,
            display_name=payload.display_name,
            job_title=payload.job_title,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    await log_audit(
        action=AuditAction.USER_CREATE,
        result=AuditResult.SUCCESS,
        user_id=current_user.id,
        details=(
            f"Restored previously deleted user {user.email} (old role assignments cleared)"
            if resurrected
            else f"Pre-provisioned user {user.email} (no roles assigned yet)"
        ),
    )
    return _to_user_out(user, [])


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.is_active is False and user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.job_title is not None:
        user.job_title = payload.job_title
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await db.commit()
    await db.refresh(user)

    await log_audit(
        action=AuditAction.USER_UPDATE,
        result=AuditResult.SUCCESS,
        user_id=current_user.id,
        details=f"Updated user {user.email}",
    )
    roles_map = await _roles_for_users(db, [user.id], None)
    return _to_user_out(user, roles_map.get(user.id, []))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # In practice this can't fire today: only a Super Admin can reach this
    # endpoint at all (require_permission above), and the self-delete guard
    # already blocks the one case where a caller could remove the sole
    # remaining admin (themselves) — so the caller always remains as a
    # super admin after any OTHER admin is deleted. Kept as defense in
    # depth in case that invariant ever changes. The scenario where a lone
    # admin genuinely can strand the system — revoking their own
    # super_admin *role assignment* rather than deleting the account — is
    # the reachable version of this guard; see remove_role_assignment below.
    if await _user_holds_super_admin(db, user.id):
        remaining = await _remaining_super_admin_count(db, exclude_user_id=user.id)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the last Super Admin — grant Super Admin to someone else first",
            )

    user_email = user.email
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()

    await log_audit(
        action=AuditAction.USER_DELETE,
        result=AuditResult.SUCCESS,
        user_id=current_user.id,
        details=f"Deleted user {user_email}",
    )
    return None


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

    # Idempotency guard: the same user/role/department combination is
    # already covered by a DB unique constraint (uq_user_role_department),
    # but catching it here first gives a clear 409 instead of a raw
    # IntegrityError turning into an unhandled 500.
    duplicate_stmt = select(UserRole).where(
        UserRole.user_id == target_user.id,
        UserRole.role_id == role_row.id,
        UserRole.department_id == payload.department_id,
    )
    if (await db.execute(duplicate_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This user already has this exact role assignment")

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


@router.delete("/role-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role_assignment(
    assignment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revokes a single role assignment — the other half of 'changing
    rights' (assign_role above only ever adds; this is what a UI's remove/×
    button on an existing role chip calls)."""
    assignment = await db.get(UserRole, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")

    role_row = await db.get(Role, assignment.role_id)

    if role_row.name == RoleName.SUPER_ADMIN:
        if not current_user.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Super Admin can revoke Super Admin")
        remaining = await _remaining_super_admin_count(db, exclude_user_id=assignment.user_id)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the last Super Admin — grant Super Admin to someone else first",
            )
    else:
        if not current_user.is_super_admin and not user_has_department_permission(
            current_user, assignment.department_id, "user:manage"
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # Capture what the audit entry needs before delete+commit expires the
    # ORM instance's attributes.
    target_user = await db.get(User, assignment.user_id)
    target_email = target_user.email if target_user else str(assignment.user_id)
    dept_id_for_audit = assignment.department_id
    role_name_for_audit = role_row.name.value

    await db.delete(assignment)
    await db.commit()

    await log_audit(
        action=AuditAction.ROLE_CHANGE,
        result=AuditResult.SUCCESS,
        user_id=current_user.id,
        department_id=dept_id_for_audit,
        details=f"Revoked {role_name_for_audit} from user {target_email}",
    )
    return None
