"""
Audit log query endpoint.

Section 19: "Audit logs must be protected from ordinary users. Super Admin
should be able to filter logs by: User, Department, Action, Document, Date
range, Result." Department Admins get the department-scoped view (their own
department's "audit:view" permission); Super Admin sees everything.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog, AuditResult
from app.audit.schemas import AuditLogOut
from app.auth.rbac import CurrentUser, get_current_user, user_has_department_permission
from app.core.database import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
async def list_audit_logs(
    department_id: Optional[uuid.UUID] = Query(None, description="Required unless caller is Super Admin"),
    user_id: Optional[uuid.UUID] = Query(None),
    action: Optional[AuditAction] = Query(None),
    document_id: Optional[uuid.UUID] = Query(None),
    result: Optional[AuditResult] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_super_admin:
        if department_id is None or not user_has_department_permission(current_user, department_id, "audit:view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = select(AuditLog)
    if department_id is not None:
        stmt = stmt.where(AuditLog.department_id == department_id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if document_id is not None:
        stmt = stmt.where(AuditLog.document_id == document_id)
    if result is not None:
        stmt = stmt.where(AuditLog.result == result)
    if date_from is not None:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return (await db.execute(stmt)).scalars().all()
