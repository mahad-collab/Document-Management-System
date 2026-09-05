"""
Background OCR processing.

Section 13: "Do NOT make the user wait for OCR to finish before the upload
request completes." This runs via FastAPI's BackgroundTasks — genuinely
async relative to the HTTP response, though it still runs in-process. The
`OCRProvider` abstraction (service.py) is what actually lets this be
swapped for a real task queue (Celery/RQ + Redis) later without touching
the extraction logic itself — noted as a scaling item, not done here per
Section 41's "don't over-engineer" principle for an MVP.
"""
import logging
import uuid

from sqlalchemy import select

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.core.database import AsyncSessionLocal
from app.documents.models import Document, OCRStatus
from app.ocr.service import get_ocr_provider
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.exceptions import SharePointError

logger = logging.getLogger("puma_dms.ocr")


async def process_document_ocr(document_id: uuid.UUID, sp_client: SharePointGraphClient) -> None:
    """
    Runs as a FastAPI background task after upload responds to the user.
    Uses its OWN database session — the request's session is already closed
    by the time this runs, since BackgroundTasks execute after the response
    is sent.
    """
    async with AsyncSessionLocal() as db:
        document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
        if document is None:
            logger.warning("OCR task: document %s no longer exists, skipping", document_id)
            return

        document.ocr_status = OCRStatus.PROCESSING
        await db.commit()

        try:
            content = await sp_client.download_file(document.sharepoint_item_id)
            provider = get_ocr_provider()
            extracted_text = await provider.extract_text(content, document.file_type)

            document.ocr_text = extracted_text or None
            document.ocr_status = OCRStatus.COMPLETED if extracted_text else OCRStatus.NOT_REQUIRED
        except SharePointError as exc:
            logger.error("OCR task: failed to download document %s from SharePoint: %s", document_id, exc)
            document.ocr_status = OCRStatus.FAILED
        except Exception as exc:  # noqa: BLE001 — OCR failures must never crash the worker
            logger.error("OCR task: extraction failed for document %s: %s", document_id, exc)
            document.ocr_status = OCRStatus.FAILED

        await db.commit()

        await log_audit(
            action=AuditAction.OCR_PROCESS if document.ocr_status != OCRStatus.FAILED else AuditAction.OCR_FAILURE,
            result=AuditResult.SUCCESS if document.ocr_status != OCRStatus.FAILED else AuditResult.FAILURE,
            department_id=document.department_id,
            document_id=document.id,
            details=f"ocr_status={document.ocr_status.value}",
        )
