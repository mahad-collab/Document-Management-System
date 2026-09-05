"""
Department model.

Spec Section 3 is explicit: departments must NOT be hard-coded anywhere in
frontend/backend logic. This table is the single source of truth, and the
Super Admin manages it entirely through the API (create/rename/disable/
reactivate) — no code changes required to add a department.
"""
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # The SharePoint DriveItem id of this department's top-level folder
    # (spec Section 4's structure: one site, department folders at the
    # root). Nullable because Phase 1 departments were created before
    # SharePoint integration existed — see the Phase 2 backfill note in
    # migrations.
    sharepoint_item_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)

    # "Disable" per spec Section 3 is distinct from soft-delete: a disabled
    # department still exists and is visible to Super Admin, it's just not
    # selectable for new uploads/users. Soft-delete (deleted_at) is reserved
    # for actual removal from normal admin views.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # `folders` relationship is added in Phase 3 once the Folder model exists.
    user_roles = relationship("UserRole", back_populates="department")

    def __repr__(self) -> str:
        return f"<Department {self.code}: {self.name}>"
