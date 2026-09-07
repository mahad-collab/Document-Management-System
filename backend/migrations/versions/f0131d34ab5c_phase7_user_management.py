"""phase7_user_management

Revision ID: f0131d34ab5c
Revises: c70d1e4a0040
Create Date: 2026-09-05 23:36:20.998192

Adds Super Admin CRUD over user accounts:

- `users.entra_object_id` becomes nullable so a Super Admin can pre-provision
  a user (email + display name only) before that person ever logs in. The
  unique constraint is untouched — Postgres allows multiple NULLs under a
  unique index, so any number of not-yet-logged-in users can coexist. The
  OAuth callback (app/auth/routes.py) is updated separately to look a user
  up by email when no entra_object_id match is found, and to backfill the
  real oid onto that pre-provisioned row on first login instead of creating
  a duplicate (which would otherwise collide on the unique email column).
- `users.job_title` becomes admin-editable (already existed, just wasn't
  writable via any endpoint).
- Adds `user_delete` to the `audit_action` enum for the new soft-delete
  endpoint (`user_create`/`user_update` already existed in the enum from
  Phase 6 but were never wired to an endpoint until now).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0131d34ab5c'
down_revision: Union[str, None] = 'c70d1e4a0040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'entra_object_id', existing_type=sa.String(length=100), nullable=True)
    # ALTER TYPE ... ADD VALUE cannot run inside the same implicit transaction
    # block that later reads the new value, but it's fine to add it here and
    # use it from a later, separate request/transaction at runtime.
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_delete'")


def downgrade() -> None:
    # Postgres has no direct "remove enum value" operation; leaving
    # 'user_delete' in the type on downgrade is harmless (unused value).
    op.alter_column('users', 'entra_object_id', existing_type=sa.String(length=100), nullable=False)
