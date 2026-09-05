"""
Dashboard endpoint.

Section 20 (Super Admin: org-wide stats) and Section 21 (department
employees: scoped to their own department only) are the same endpoint here,
branching on `department_id` and the caller's role — consistent with how
every other endpoint in this app decides scope.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    DepartmentDashboard,
    DepartmentDocumentCount,
    OCRStatusBreakdown,
    OrgWideDashboard,
    RecentDocumentSummary,
)
from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.departments.models import Department
from app.documents.models import Document, OCRStatus
from app.folders.models import Folder
from app.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("", response_model=OrgWideDashboard | DepartmentDashboard)
async def get_dashboard(
    department_id: Optional[UUID] = Query(None, description="Omit for the org-wide Super Admin dashboard"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if department_id is not None:
        if not user_has_department_permission(current_user, department_id, "document:view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return await _department_dashboard(db, department_id)

    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="department_id is required unless you are Super Admin",
        )
    return await _org_wide_dashboard(db)


async def _org_wide_dashboard(db: AsyncSession) -> OrgWideDashboard:
    today_start = _today_start()

    total_documents = (await db.execute(select(func.count()).select_from(Document).where(Document.deleted_at.is_(None)))).scalar_one()
    total_users = (await db.execute(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))).scalar_one()
    total_departments = (await db.execute(select(func.count()).select_from(Department).where(Department.deleted_at.is_(None)))).scalar_one()
    documents_today = (
        await db.execute(
            select(func.count()).select_from(Document).where(Document.created_at >= today_start, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    pending_ocr = (
        await db.execute(select(func.count()).select_from(Document).where(Document.ocr_status == OCRStatus.PENDING))
    ).scalar_one()
    ocr_failures = (
        await db.execute(select(func.count()).select_from(Document).where(Document.ocr_status == OCRStatus.FAILED))
    ).scalar_one()
    archived_folders = (
        await db.execute(select(func.count()).select_from(Folder).where(Folder.archived_at.is_not(None)))
    ).scalar_one()
    deleted_documents = (
        await db.execute(select(func.count()).select_from(Document).where(Document.deleted_at.is_not(None)))
    ).scalar_one()
    total_storage = (
        await db.execute(select(func.coalesce(func.sum(Document.file_size), 0)).where(Document.deleted_at.is_(None)))
    ).scalar_one()

    dept_counts_stmt = (
        select(Department.id, Department.name, func.count(Document.id))
        .outerjoin(Document, (Document.department_id == Department.id) & Document.deleted_at.is_(None))
        .where(Department.deleted_at.is_(None))
        .group_by(Department.id, Department.name)
        .order_by(func.count(Document.id).desc())
    )
    dept_counts = [
        DepartmentDocumentCount(department_id=row[0], department_name=row[1], document_count=row[2])
        for row in (await db.execute(dept_counts_stmt)).all()
    ]

    ocr_breakdown_stmt = select(Document.ocr_status, func.count()).group_by(Document.ocr_status)
    ocr_breakdown = [
        OCRStatusBreakdown(status=row[0], count=row[1]) for row in (await db.execute(ocr_breakdown_stmt)).all()
    ]

    recent_uploads_stmt = (
        select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc()).limit(5)
    )
    recent_uploads = [
        RecentDocumentSummary(id=d.id, name=d.name, department_id=d.department_id, created_at=d.created_at)
        for d in (await db.execute(recent_uploads_stmt)).scalars().all()
    ]

    recent_deleted_stmt = (
        select(Document).where(Document.deleted_at.is_not(None)).order_by(Document.deleted_at.desc()).limit(5)
    )
    recent_deleted = [
        RecentDocumentSummary(id=d.id, name=d.name, department_id=d.department_id, created_at=d.created_at)
        for d in (await db.execute(recent_deleted_stmt)).scalars().all()
    ]

    return OrgWideDashboard(
        total_documents=total_documents,
        total_users=total_users,
        total_departments=total_departments,
        documents_uploaded_today=documents_today,
        pending_ocr=pending_ocr,
        ocr_failures=ocr_failures,
        archived_folders=archived_folders,
        deleted_documents=deleted_documents,
        total_storage_bytes=total_storage,
        department_document_counts=dept_counts,
        ocr_status_breakdown=ocr_breakdown,
        recent_uploads=recent_uploads,
        recent_deleted=recent_deleted,
    )


async def _department_dashboard(db: AsyncSession, department_id: UUID) -> DepartmentDashboard:
    today_start = _today_start()

    total_documents = (
        await db.execute(
            select(func.count()).select_from(Document).where(Document.department_id == department_id, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    documents_today = (
        await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.department_id == department_id, Document.created_at >= today_start, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    pending_ocr = (
        await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.department_id == department_id, Document.ocr_status == OCRStatus.PENDING)
        )
    ).scalar_one()

    recent_uploads_stmt = (
        select(Document)
        .where(Document.department_id == department_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .limit(5)
    )
    recent_uploads = [
        RecentDocumentSummary(id=d.id, name=d.name, department_id=d.department_id, created_at=d.created_at)
        for d in (await db.execute(recent_uploads_stmt)).scalars().all()
    ]

    return DepartmentDashboard(
        department_id=department_id,
        total_documents=total_documents,
        documents_uploaded_today=documents_today,
        pending_ocr=pending_ocr,
        recent_uploads=recent_uploads,
    )
