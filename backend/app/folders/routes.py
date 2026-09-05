"""
Folder management endpoints.

Spec Section 22: folders are database-driven and synchronized with
SharePoint. Per our one-way sync decision, creating a folder here is the
ONLY way a folder gets created — we call SharePoint immediately after the
RBAC check passes, then store the mapping.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.departments.models import Department
from app.folders.models import Folder
from app.folders.schemas import FolderCreate, FolderOut
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client
from app.sharepoint.exceptions import SharePointConflictError, SharePointError

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderOut])
async def list_folders(
    department_id: uuid.UUID = Query(...),
    parent_id: uuid.UUID | None = Query(None, description="Omit to list top-level folders for the department"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user_has_department_permission(current_user, department_id, "document:view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = select(Folder).where(Folder.department_id == department_id, Folder.archived_at.is_(None))
    stmt = stmt.where(Folder.parent_id == parent_id) if parent_id else stmt.where(Folder.parent_id.is_(None))
    result = await db.execute(stmt.order_by(Folder.name))
    return result.scalars().all()


@router.post("", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: FolderCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    if not user_has_department_permission(current_user, payload.department_id, "folder:create"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    department = await db.get(Department, payload.department_id)
    if department is None or department.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    # Resolve the SharePoint parent to create this folder under: either a
    # sibling Folder's SharePoint item, or the department's own root folder.
    if payload.parent_id is not None:
        parent_folder = await db.get(Folder, payload.parent_id)
        if (
            parent_folder is None
            or parent_folder.archived_at is not None
            or parent_folder.department_id != payload.department_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent folder not found in this department")
        sp_parent_item_id = parent_folder.sharepoint_item_id
    else:
        if department.sharepoint_item_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This department has no SharePoint root folder yet (it was created before SharePoint "
                    "integration was added). An admin needs to backfill it before folders can be created."
                ),
            )
        sp_parent_item_id = department.sharepoint_item_id

    try:
        sp_folder = await sp_client.create_folder(name=payload.name, parent_item_id=sp_parent_item_id)
    except SharePointConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A folder with this name already exists here")
    except SharePointError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SharePoint folder creation failed: {exc}")

    folder = Folder(
        name=payload.name,
        department_id=payload.department_id,
        parent_id=payload.parent_id,
        sharepoint_item_id=sp_folder["id"],
    )
    db.add(folder)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Database conflict recording the folder (SharePoint item {sp_folder['id']} was created "
                "and was NOT cleaned up — an admin should reconcile manually)."
            ),
        )
    await db.refresh(folder)
    await log_audit(
        action=AuditAction.FOLDER_CREATE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=folder.department_id, details=folder.name,
    )
    return folder


@router.post("/{folder_id}/archive", response_model=FolderOut)
async def archive_folder(
    folder_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    if not user_has_department_permission(current_user, folder.department_id, "folder:archive"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # Archiving is a PostgreSQL-side state change only — per spec Section
    # 18's principle (leverage native capabilities, don't over-engineer),
    # we leave the SharePoint folder in place. It simply stops appearing in
    # the DMS folder browser.
    folder.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(folder)
    await log_audit(
        action=AuditAction.FOLDER_UPDATE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=folder.department_id, details=f"archived: {folder.name}",
    )
    return folder
