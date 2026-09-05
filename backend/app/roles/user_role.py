"""
UserRole — the join table that actually drives authorization.

A single user can hold different roles in different departments, e.g.
"Department Admin of Finance" AND "Read-Only User of HR" at the same time.

department_id is nullable ONLY for the super_admin role (org-wide scope has
no single department). This is enforced at the application layer (see
app/auth/rbac.py), not by a DB constraint, because SQLAlchemy/Postgres check
constraints referencing enum values from another table are awkward — the
authorization dependency validates this invariant on every role assignment.
"""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        # A user can't hold the exact same role in the exact same department twice.
        UniqueConstraint("user_id", "role_id", "department_id", name="uq_user_role_department"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL only for org-wide roles (super_admin). Every department-scoped
    # role (department_admin, department_user, read_only) must set this.
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")
    department = relationship("Department", back_populates="user_roles")

    def __repr__(self) -> str:
        dept = self.department_id or "ORG-WIDE"
        return f"<UserRole user={self.user_id} role={self.role_id} dept={dept}>"
