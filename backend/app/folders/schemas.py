import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    department_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = None  # None = top-level folder directly under the department


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    department_id: uuid.UUID
    parent_id: Optional[uuid.UUID]
    sharepoint_item_id: str
    is_archived: bool
