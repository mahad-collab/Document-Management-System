import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.documents.models import OCRStatus


class DepartmentDocumentCount(BaseModel):
    department_id: uuid.UUID
    department_name: str
    document_count: int


class OCRStatusBreakdown(BaseModel):
    status: OCRStatus
    count: int


class RecentDocumentSummary(BaseModel):
    id: uuid.UUID
    name: str
    department_id: uuid.UUID
    created_at: datetime


class OrgWideDashboard(BaseModel):
    total_documents: int
    total_users: int
    total_departments: int
    documents_uploaded_today: int
    pending_ocr: int
    ocr_failures: int
    archived_folders: int
    deleted_documents: int
    total_storage_bytes: int
    department_document_counts: list[DepartmentDocumentCount]
    ocr_status_breakdown: list[OCRStatusBreakdown]
    recent_uploads: list[RecentDocumentSummary]
    recent_deleted: list[RecentDocumentSummary]


class DepartmentDashboard(BaseModel):
    department_id: uuid.UUID
    total_documents: int
    documents_uploaded_today: int
    pending_ocr: int
    recent_uploads: list[RecentDocumentSummary]
