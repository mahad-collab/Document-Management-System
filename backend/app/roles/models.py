"""
Role and Permission models.

Spec Section 7 defines four roles: Super Admin, Department Admin, Department
User, Read-Only User. These are the fixed catalog (unlike departments, which
are admin-manageable data). Fine-grained permissions are attached to roles
via `role_permissions`, so new capabilities can be granted to a role without
a schema change or redeploy — only a data change.
"""
import enum

from sqlalchemy import Enum, ForeignKey, String, Table, Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import TimestampMixin, UUIDPrimaryKeyMixin


class RoleName(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    DEPARTMENT_ADMIN = "department_admin"
    DEPARTMENT_USER = "department_user"
    READ_ONLY = "read_only"


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[RoleName] = mapped_column(
        Enum(RoleName, name="role_name", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        unique=True,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=True)

    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")
    user_roles = relationship("UserRole", back_populates="role")

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"

    # e.g. "document:upload", "document:delete", "user:manage", "audit:view"
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"
