"""
Folder model.

Implements our one-way sync decision: the DMS is the only writer of folder
structure. Creating a folder here also creates the matching SharePoint
folder (see routes.py); SharePoint-side folder creation is never picked up
automatically — there's no reverse sync job. `sharepoint_item_id` is the
durable link between a DMS folder row and its SharePoint DriveItem.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import TimestampMixin, UUIDPrimaryKeyMixin


class Folder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # The SharePoint DriveItem id this folder maps to — the durable link
    # described in spec Section 22 ("DMS Folder <-> SharePoint Folder").
    sharepoint_item_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    department = relationship("Department")
    parent = relationship("Folder", remote_side="Folder.id", backref="children")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __repr__(self) -> str:
        return f"<Folder {self.name} (dept={self.department_id})>"
