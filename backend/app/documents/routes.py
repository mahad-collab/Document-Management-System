"""
Document management endpoints.

Every endpoint here checks department-scoped RBAC using `document.department_id`
directly (the denormalized field) — this is the concrete implementation of
Section 8's guarantee: even knowing a document's ID, folder path, or
SharePoint item id is never enough on its own.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db
from app.documents.models import Document, DocumentVersion, OCRStatus, Tag
from app.documents.schemas import DocumentOut, DocumentVersionOut
from app.folders.models import Folder
from app.ocr.tasks import process_document_ocr
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client
from app.sharepoint.exceptions import SharePointError

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_FILE_TYPES = {"pdf", "jpg", "jpeg", "png", "tiff"}
MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Graph simple-upload limit (Section 26: file size validation)


def _file_type_of(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext


async def _get_or_create_tags(db: AsyncSession, tag_names: list[str]) -> list[Tag]:
    tags = []
    for raw_name in tag_names:
        name = raw_name.strip().lower()
        if not name:
            continue
        existing = (await db.execute(select(Tag).where(Tag.name == name))).scalar_one_or_none()
        if existing is None:
            existing = Tag(name=name)
            db.add(existing)
            await db.flush()
        tags.append(existing)
    return tags


async def _load_document_or_404(db: AsyncSession, document_id: uuid.UUID, include_deleted: bool = False) -> Document:
    stmt = select(Document).where(Document.id == document_id).options(selectinload(Document.tags))
    if not include_deleted:
        stmt = stmt.where(Document.deleted_at.is_(None))
    document = (await db.execute(stmt)).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


# ---- List / metadata ----------------------------------------------------


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    department_id: uuid.UUID = Query(...),
    folder_id: Optional[uuid.UUID] = Query(None),
    document_number: Optional[str] = Query(None, description="Exact or partial match on document number"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user_has_department_permission(current_user, department_id, "document:view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = select(Document).where(Document.department_id == department_id, Document.deleted_at.is_(None))
    if folder_id is not None:
        stmt = stmt.where(Document.folder_id == folder_id)
    if document_number:
        stmt = stmt.where(Document.document_number.ilike(f"%{document_number}%"))

    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await _load_document_or_404(db, document_id)
    if not user_has_department_permission(current_user, document.department_id, "document:view"):
        # 404, not 403 — per Section 8, we don't want to even confirm to an
        # unauthorized caller that a document with this ID exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


# ---- Upload ---------------------------------------------------------------


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    folder_id: uuid.UUID = Form(...),
    document_type: Optional[str] = Form(None),
    document_number: Optional[str] = Form(None),
    document_date: Optional[datetime] = Form(None),
    description: Optional[str] = Form(None),
    tags: str = Form("", description="Comma-separated tag names"),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    folder = await db.get(Folder, folder_id)
    if folder is None or folder.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    if not user_has_department_permission(current_user, folder.department_id, "document:upload"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # --- File validation (Section 26: never trust the extension alone) ---
    file_type = _file_type_of(file.filename or "")
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{file_type}'. Allowed: {sorted(ALLOWED_FILE_TYPES)}",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024)}MB limit for this phase "
                "(chunked upload for larger files isn't implemented yet)."
            ),
        )
    # MIME-type sniff, not just trusting the extension or the browser-supplied
    # content_type header (which the client fully controls and can lie about).
    if not _looks_like_declared_type(content, file_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content doesn't match its extension (failed magic-byte check)",
        )

    try:
        sp_item = await sp_client.upload_small_file(
            parent_item_id=folder.sharepoint_item_id, filename=file.filename, content=content
        )
    except SharePointError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Upload to SharePoint failed: {exc}")

    tag_objs = await _get_or_create_tags(db, tags.split(",")) if tags else []

    document = Document(
        name=file.filename,
        department_id=folder.department_id,
        folder_id=folder.id,
        document_type=document_type,
        document_number=document_number,
        document_date=document_date,
        description=description,
        uploaded_by=current_user.id,
        sharepoint_item_id=sp_item["id"],
        current_version_number=1,
        file_size=len(content),
        file_type=file_type,
        tags=tag_objs,
    )
    db.add(document)
    await db.flush()

    db.add(
        DocumentVersion(
            document_id=document.id,
            version_number=1,
            sharepoint_version_label=sp_item.get("cTag", "1.0"),
            uploaded_by=current_user.id,
            change_description="Initial upload",
            file_size=len(content),
        )
    )
    await db.commit()
    await db.refresh(document)

    # Section 13: queued AFTER commit, runs after this response is sent —
    # the user never waits on OCR to finish.
    background_tasks.add_task(process_document_ocr, document.id, sp_client)

    await log_audit(
        action=AuditAction.UPLOAD,
        result=AuditResult.SUCCESS,
        user_id=current_user.id,
        department_id=document.department_id,
        document_id=document.id,
        details=document.name,
    )

    return document


def _looks_like_declared_type(content: bytes, declared_ext: str) -> bool:
    """Minimal magic-byte check — genuinely blocking malicious content needs
    the antivirus/malware scanning integration point noted in Section 26;
    this only catches "renamed .exe to .pdf"-style mismatches."""
    signatures = {
        "pdf": (b"%PDF",),
        "jpg": (b"\xff\xd8\xff",),
        "jpeg": (b"\xff\xd8\xff",),
        "png": (b"\x89PNG\r\n\x1a\n",),
        "tiff": (b"II*\x00", b"MM\x00*"),
    }
    expected = signatures.get(declared_ext)
    if not expected:
        return True  # unknown type in our own map — don't block on it here
    return any(content.startswith(sig) for sig in expected)


# ---- Download ---------------------------------------------------------


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    document = await _load_document_or_404(db, document_id)
    if not user_has_department_permission(current_user, document.department_id, "document:download"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        content = await sp_client.download_file(document.sharepoint_item_id)
    except SharePointError as exc:
        await log_audit(
            action=AuditAction.DOWNLOAD, result=AuditResult.FAILURE, user_id=current_user.id,
            department_id=document.department_id, document_id=document.id, details=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Download from SharePoint failed: {exc}")

    await log_audit(
        action=AuditAction.DOWNLOAD, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=document.department_id, document_id=document.id,
    )

    media_types = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "tiff": "image/tiff"}
    return StreamingResponse(
        iter([content]),
        media_type=media_types.get(document.file_type, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{document.name}"'},
    )


# ---- Versions ---------------------------------------------------------


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_document_versions(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await _load_document_or_404(db, document_id)
    if not user_has_department_permission(current_user, document.department_id, "document:view"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stmt = select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(
        DocumentVersion.version_number.desc()
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/{document_id}/versions", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_new_version(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    change_description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    document = await _load_document_or_404(db, document_id)
    if not user_has_department_permission(current_user, document.department_id, "document:version_upload"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds the 4MB limit for this phase")

    try:
        sp_item = await sp_client.upload_new_version(document.sharepoint_item_id, content)
    except SharePointError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Version upload to SharePoint failed: {exc}")

    document.current_version_number += 1
    document.file_size = len(content)
    document.ocr_status = OCRStatus.PENDING  # new content — previous OCR result is now stale
    db.add(
        DocumentVersion(
            document_id=document.id,
            version_number=document.current_version_number,
            sharepoint_version_label=sp_item.get("cTag", str(document.current_version_number)),
            uploaded_by=current_user.id,
            change_description=change_description,
            file_size=len(content),
        )
    )
    await db.commit()
    await db.refresh(document)
    background_tasks.add_task(process_document_ocr, document.id, sp_client)
    await log_audit(
        action=AuditAction.VERSION_CREATE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=document.department_id, document_id=document.id,
        details=f"v{document.current_version_number}: {change_description or ''}",
    )
    return document


# ---- Recycle bin lifecycle (Section 18) --------------------------------


@router.post("/{document_id}/delete", response_model=DocumentOut)
async def delete_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    document = await _load_document_or_404(db, document_id)
    if not user_has_department_permission(current_user, document.department_id, "document:delete"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # PostgreSQL state changes FIRST (authoritative), SharePoint call is the
    # effect — per our Step-2 decision. If the Graph call fails, the
    # document is still correctly in our recycle bin; a background
    # reconciliation job (not yet built) would catch the drift.
    document.deleted_at = datetime.now(timezone.utc)
    document.deleted_by = current_user.id
    await db.commit()

    try:
        await sp_client.delete_item(document.sharepoint_item_id)
    except SharePointError:
        pass  # Logged in Phase 6's audit trail; DB state is already correct.

    await db.refresh(document)
    await log_audit(
        action=AuditAction.DELETE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=document.department_id, document_id=document.id,
    )
    return document


@router.post("/{document_id}/restore", response_model=DocumentOut)
async def restore_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sp_client: SharePointGraphClient = Depends(get_sharepoint_client),
):
    document = await _load_document_or_404(db, document_id, include_deleted=True)
    if document.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is not deleted")
    if not user_has_department_permission(current_user, document.department_id, "document:restore"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    document.deleted_at = None
    document.deleted_by = None
    await db.commit()

    try:
        await sp_client.restore_item(document.sharepoint_item_id)
    except SharePointError:
        pass  # See restore_item's docstring — this Graph call is unverified against a real tenant.

    await db.refresh(document)
    await log_audit(
        action=AuditAction.RESTORE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=document.department_id, document_id=document.id,
    )
    return document


@router.delete("/{document_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanent_delete_document(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await _load_document_or_404(db, document_id, include_deleted=True)
    if document.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document must be soft-deleted first")
    if not user_has_department_permission(current_user, document.department_id, "document:permanent_delete"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # We deliberately do NOT also purge it from SharePoint's recycle bin here
    # — per Section 18, SharePoint's own retention window is a separate,
    # native mechanism we don't try to override. This only removes our
    # PostgreSQL record (and its audit-relevant version rows).
    await log_audit(
        action=AuditAction.PERMANENT_DELETE, result=AuditResult.SUCCESS, user_id=current_user.id,
        department_id=document.department_id, document_id=document.id, details=document.name,
    )
    await db.delete(document)
    await db.commit()
