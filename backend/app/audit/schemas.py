import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.audit.models import AuditAction, AuditResult


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    action: AuditAction
    department_id: Optional[uuid.UUID]
    document_id: Optional[uuid.UUID]
    result: AuditResult
    details: Optional[str]
    created_at: datetime
