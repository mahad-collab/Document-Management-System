"""
Document + DocumentVersion + Tag models.

Section 11's metadata fields, Section 17's version control, Section 12/13's
OCR status tracking (the actual OCR *processing* is Phase 4 — this phase
just gives OCR a place to live and defaults every new document to PENDING).

Deletion model: per our Step-2 architecture decision, PostgreSQL's
`deleted_at` is authoritative. The SharePoint recycle-bin call is an EFFECT
triggered after the DB state change, not the other way around (see
routes.py).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Table, Column, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import TimestampMixin, UUIDPrimaryKeyMixin


class OCRStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


document_tags = Table(
    "document_tags",
    Base.metadata,
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Denormalized department_id (also reachable via folder.department_id)
    # so every RBAC check on a document is a single indexed lookup, not a
    # join through folders — this is the field Section 8's "even if you
    # know the document ID" guarantee is checked against.
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    document_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    document_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    document_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # The CURRENT version's pointer. Every version's own metadata (including
    # its own sharepoint reference) lives in DocumentVersion; this is a
    # convenience denormalization so "give me the current file" never needs
    # a join.
    sharepoint_item_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    current_version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf, jpg, png, tiff

    ocr_status: Mapped[OCRStatus] = mapped_column(
        Enum(OCRStatus, name="ocr_status", values_callable=lambda e: [x.value for x in e]),
        default=OCRStatus.PENDING,
        nullable=False,
    )
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Soft-delete / recycle bin state (Section 18). PostgreSQL is
    # authoritative per our architecture decision — see routes.py for how
    # this drives the SharePoint recycle-bin call as an effect.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    folder = relationship("Folder")
    department = relationship("Department")
    versions = relationship(
        "DocumentVersion", back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_number"
    )
    tags = relationship("Tag", secondary=document_tags)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<Document {self.name} v{self.current_version_number}>"


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # SharePoint's own version label for the SAME driveItem (e.g. "2.0") —
    # NOT a separate item id. Uploading new content to the same item id
    # triggers SharePoint's automatic versioning; this just records which
    # SharePoint version corresponds to which of our version rows.
    sharepoint_version_label: Mapped[str] = mapped_column(String(50), nullable=False)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    change_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    document = relationship("Document", back_populates="versions")

    def __repr__(self) -> str:
        return f"<DocumentVersion doc={self.document_id} v{self.version_number}>"
