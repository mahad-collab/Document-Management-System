"""
Department management endpoints.

Spec Section 3: only the Super Admin creates/renames/disables/reactivates
departments — no application code change is ever required to add one. Every
endpoint here uses `require_permission`, which (per app/auth/rbac.py) only
Super Admin satisfies, since department management is inherently org-wide.

Listing departments (GET /departments) is open to any authenticated user —
everyone needs to know which departments exist to navigate the UI — but
Section 21 requires a normal employee only ever *see* their own department's
data elsewhere; that's enforced at the document/folder layer, not here.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user, require_permission
from app.core.database import get_db
from app.departments.models import Department
from app.departments.schemas import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client
from app.sharepoint.exceptions import SharePointError

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentOut])
async def list_departments(
    include_inactive: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Department).where(Department.deleted_at.is_(None))
    if not include_inactive:
        stmt = stmt.where(Department.is_active.is_(True))
    result = await db.execute(stmt.order_by(Department.name))
    return result.scalars().all()


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    current_user: CurrentUser = Depends(require_permission("department:manage")),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    # Create the SharePoint folder FIRST. If Graph fails, we never create a
    # PostgreSQL row that claims a department exists but has nowhere to
    # actually store its documents — that would violate Section 5 (every
    # document must have a reliable relationship to a SharePoint location).
    try:
        sp_folder = await sp_client.create_folder(name=payload.code.upper())
    except SharePointError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not create the department's SharePoint folder: {exc}",
        )

    department = Department(
        name=payload.name,
        code=payload.code.upper(),
        description=payload.description,
        sharepoint_item_id=sp_folder["id"],
    )
    db.add(department)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # The SharePoint folder now exists without a matching DB row. We
        # don't try to auto-delete it here — a partial-failure cleanup that
        # silently deletes a SharePoint folder is its own risk. Surface it
        # clearly so an admin can reconcile (this is exactly the kind of
        # drift the Phase 1 reconciliation job design is meant to catch).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A department with this name or code already exists. Note: a SharePoint folder "
                f"(item id {sp_folder['id']}) was already created and was NOT cleaned up — "
                "an admin should remove it manually if this was a genuine duplicate."
            ),
        )
    await db.refresh(department)
    await log_audit(
        action=AuditAction.DEPARTMENT_CREATE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=department.id, details=department.name,
    )
    return department


@router.patch("/{department_id}", response_model=DepartmentOut)
async def rename_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdate,
    current_user: CurrentUser = Depends(require_permission("department:manage")),
    db: AsyncSession = Depends(get_db),
):
    department = await db.get(Department, department_id)
    if department is None or department.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    if payload.name is not None:
        department.name = payload.name
    if payload.description is not None:
        department.description = payload.description

    await db.commit()
    await db.refresh(department)
    return department


@router.post("/{department_id}/disable", response_model=DepartmentOut)
async def disable_department(
    department_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("department:manage")),
    db: AsyncSession = Depends(get_db),
):
    department = await db.get(Department, department_id)
    if department is None or department.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    department.is_active = False
    await db.commit()
    await db.refresh(department)
    return department


@router.post("/{department_id}/reactivate", response_model=DepartmentOut)
async def reactivate_department(
    department_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("department:manage")),
    db: AsyncSession = Depends(get_db),
):
    department = await db.get(Department, department_id)
    if department is None or department.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    department.is_active = True
    await db.commit()
    await db.refresh(department)
    return department
