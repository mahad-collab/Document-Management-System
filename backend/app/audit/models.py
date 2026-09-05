"""
AuditLog model — Section 19.

Two actions (DEPARTMENT_CREATE, DEPARTMENT_UPDATE) are added beyond the
spec's literal list because department management is exactly the kind of
admin action Section 19's intent (accountability for administrative
changes) implies should be tracked, even though the enumerated list didn't
name it explicitly.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models_base import TimestampMixin, UUIDPrimaryKeyMixin


class AuditAction(str, enum.Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    UPLOAD = "upload"
    VIEW = "view"
    DOWNLOAD = "download"
    UPDATE = "update"
    RENAME = "rename"
    MOVE = "move"
    DELETE = "delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"
    VERSION_CREATE = "version_create"
    VERSION_RESTORE = "version_restore"
    FOLDER_CREATE = "folder_create"
    FOLDER_UPDATE = "folder_update"
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    ROLE_CHANGE = "role_change"
    PERMISSION_CHANGE = "permission_change"
    OCR_PROCESS = "ocr_process"
    OCR_FAILURE = "ocr_failure"
    DEPARTMENT_CREATE = "department_create"
    DEPARTMENT_UPDATE = "department_update"


class AuditResult(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # Nullable: a failed login attempt may not resolve to a known user.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        index=True,
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, name="audit_result", values_callable=lambda e: [x.value for x in e]), nullable=False
    )
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} by={self.user_id} result={self.result}>"
