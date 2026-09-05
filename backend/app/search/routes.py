"""
Search endpoint.

Section 14: "Search must respect RBAC. A Finance user must never receive HR
documents in search results." This is enforced the same way as every other
document endpoint — required `department_id` param, checked against the
caller's actual permissions before the query runs, never after.

Uses real PostgreSQL full-text search (to_tsvector/plainto_tsquery) across
filename, document number, description, and OCR-extracted text — this is
the "Initially use PostgreSQL full-text search" from spec Section 14,
implemented as an inline tsvector expression rather than a stored/generated
column, so no extra migration was needed to add it. Section 14 also notes
the search layer should be designed so OpenSearch/Elasticsearch could
replace this later — that swap would happen entirely inside this one
function; nothing about the API contract would need to change.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.documents.models import Document, OCRStatus, Tag, document_tags
from app.documents.schemas import DocumentOut

router = APIRouter(prefix="/search", tags=["search"])


def _search_vector():
    return func.to_tsvector(
        "english",
        func.coalesce(Document.name, "")
        + " "
        + func.coalesce(Document.document_number, "")
        + " "
        + func.coalesce(Document.description, "")
        + " "
        + func.coalesce(Document.ocr_text, ""),
    )


@router.get("", response_model=list[DocumentOut])
async def search_documents(
    department_id: uuid.UUID = Query(...),
    q: Optional[str] = Query(None, description="Full-text query across filename, metadata, and OCR text"),
    folder_id: Optional[uuid.UUID] = Query(None),
    document_type: Optional[str] = Query(None),
    document_date_from: Optional[datetime] = Query(None),
    document_date_to: Optional[datetime] = Query(None),
    uploader_id: Optional[uuid.UUID] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tag names, ANY match"),
    ocr_status: Optional[OCRStatus] = Query(None),
    include_deleted: bool = Query(False, description="Super Admin / Department Admin recycle-bin search"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user_has_department_permission(current_user, department_id, "search:query"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = select(Document).where(Document.department_id == department_id)
    if not include_deleted:
        stmt = stmt.where(Document.deleted_at.is_(None))
    elif not user_has_department_permission(current_user, department_id, "document:restore"):
        # Only someone who could restore/manage the recycle bin gets to
        # search inside it — an ordinary Department User cannot use
        # include_deleted=true to peek at deleted documents.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to search deleted documents")

    if q:
        stmt = stmt.where(_search_vector().op("@@")(func.plainto_tsquery("english", q)))
    if folder_id is not None:
        stmt = stmt.where(Document.folder_id == folder_id)
    if document_type:
        stmt = stmt.where(Document.document_type.ilike(f"%{document_type}%"))
    if document_date_from is not None:
        stmt = stmt.where(Document.document_date >= document_date_from)
    if document_date_to is not None:
        stmt = stmt.where(Document.document_date <= document_date_to)
    if uploader_id is not None:
        stmt = stmt.where(Document.uploaded_by == uploader_id)
    if ocr_status is not None:
        stmt = stmt.where(Document.ocr_status == ocr_status)
    if tags:
        tag_names = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_names:
            stmt = (
                stmt.join(document_tags, Document.id == document_tags.c.document_id)
                .join(Tag, Tag.id == document_tags.c.tag_id)
                .where(Tag.name.in_(tag_names))
                .distinct()
            )

    result = await db.execute(stmt.order_by(Document.created_at.desc()).options(selectinload(Document.tags)))
    return result.scalars().all()
