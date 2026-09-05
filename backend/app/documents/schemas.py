import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.documents.models import OCRStatus


class DocumentMetadataIn(BaseModel):
    """Sent alongside the file as form fields on upload (see routes.py)."""
    document_type: Optional[str] = Field(None, max_length=100)
    document_number: Optional[str] = Field(None, max_length=100)
    document_date: Optional[datetime] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class DocumentMetadataUpdate(BaseModel):
    document_type: Optional[str] = Field(None, max_length=100)
    document_number: Optional[str] = Field(None, max_length=100)
    document_date: Optional[datetime] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    department_id: uuid.UUID
    folder_id: uuid.UUID
    document_type: Optional[str]
    document_number: Optional[str]
    document_date: Optional[datetime]
    description: Optional[str]
    uploaded_by: uuid.UUID
    current_version_number: int
    file_size: int
    file_type: str
    ocr_status: OCRStatus
    is_deleted: bool
    created_at: datetime


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    sharepoint_version_label: str
    uploaded_by: uuid.UUID
    change_description: Optional[str]
    file_size: int
    created_at: datetime
