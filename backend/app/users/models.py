"""
User model.

Per spec Section 6, Entra ID is the authentication source of truth — this
table does NOT store passwords. It mirrors identity attributes from Entra
(object ID, email, display name) the first time a user signs in, and holds
DMS-specific state (active/inactive, role assignments) that the app itself
owns.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models_base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    # Microsoft Entra ID's immutable object ID for this user — this, not
    # email, is the durable identity key (emails can be renamed in Entra).
    entra_object_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email}>"
