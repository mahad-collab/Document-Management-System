"""
Audit logging helper.

Deliberately uses its OWN database session/transaction, independent of
whatever transaction the calling endpoint is in. Two reasons:
  1. A FAILURE audit entry (e.g. "tried to access unauthorized document")
     needs to be written even when the calling code's own transaction gets
     rolled back or never had one to begin with (a 403 raised before any
     DB write).
  2. Audit logging must never become a reason a real user-facing action
     fails — if writing the log itself has a transient DB issue, we log
     that to the application logger and swallow it rather than raising.
"""
import logging
import uuid
from typing import Optional

from app.audit.models import AuditAction, AuditLog, AuditResult
from app.core.database import AsyncSessionLocal

logger = logging.getLogger("puma_dms.audit")


async def log_audit(
    action: AuditAction,
    result: AuditResult,
    user_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    document_id: Optional[uuid.UUID] = None,
    details: Optional[str] = None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AuditLog(
                    user_id=user_id,
                    action=action,
                    department_id=department_id,
                    document_id=document_id,
                    result=result,
                    details=details,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — audit logging must never break the actual request
        logger.error("Failed to write audit log (action=%s, user=%s): %s", action, user_id, exc)
