"""
OCR administration endpoints.

Section 13: "Administrators must be able to: View OCR failures, Retry OCR,
Monitor OCR processing, See documents waiting for OCR." Scoped per
department for Department Admins, org-wide for Super Admin — same pattern
as every other admin surface in this app.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.documents.models import Document, OCRStatus
from app.documents.schemas import DocumentOut
from app.ocr.tasks import process_document_ocr
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.get("/status", response_model=list[DocumentOut])
async def list_ocr_status(
    department_id: uuid.UUID = Query(...),
    status_filter: OCRStatus | None = Query(None, alias="status"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user_has_department_permission(current_user, department_id, "document:view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = select(Document).where(Document.department_id == department_id, Document.deleted_at.is_(None))
    if status_filter is not None:
        stmt = stmt.where(Document.ocr_status == status_filter)
    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.post("/{document_id}/retry", response_model=DocumentOut)
async def retry_ocr(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    document = (
        await db.execute(select(Document).where(Document.id == document_id, Document.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not user_has_department_permission(current_user, document.department_id, "user:manage"):
        # OCR retry is an admin action (spec Section 13 lists it under
        # "Administrators"), so gated on the same permission as user
        # management rather than the everyday document:view/upload set.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    document.ocr_status = OCRStatus.PENDING
    await db.commit()
    await db.refresh(document)

    background_tasks.add_task(process_document_ocr, document.id, sp_client)
    return document
